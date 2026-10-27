"""A text to the assistant's own number, whichever app carried it (WhatsApp, iMessage). A transport parses and
verifies the delivery, then hands the text here as a ``PhoneText`` with the ``PhoneTransport`` that answers it.

The rule (``handle_phone_text``): a link code from the web's draft binds the number to the account that minted it;
otherwise the number reaches the account it is bound to, and the coordinator answers in that account's one
conversation; a number bound to no account gets one short notice a day and never an account. A platform with its own
rule for texts registers it as ``PHONE_TEXT`` and gets every text instead."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from coder.coordinator.agent import COORDINATOR_MODEL, run_coordinator_turn
from coder.workflow.builder_config import missing_brain_key
from nodes.core.media_resolver import FileInfo, describe_url
from repositories.phones import PhoneRepo
from repositories.users import get_user_email
from utils.capabilities import PHONE_TEXT, capability
from utils.database_pool import get_native_pool
from utils.phone_identity import PhoneLinkError, default_service, link_code_in
from utils.phone_numbers import normalize_e164
from utils.redis_client import get_shared_redis
from utils.resource_store import download_url
from utils.socket_singleton import get_sio
from wss.handlers.coordinator_handler import plan_allows_turn
from wss.handlers.workflow_handler import get_user_org_context

logger = logging.getLogger(__name__)

TEXT_LIMIT = 4000  # one message's worth of text; WhatsApp caps a body at 4096
NOTICE_TTL_S = 24 * 60 * 60
LINKED_REPLY = "Linked. Texts from this number now reach your NoClick account{who}, in the same conversation as the web. What can I do for you?"
ALREADY_LINKED_REPLY = "This number is already linked to your NoClick account{who}. What can I do for you?"
UNBOUND_NOTICE = ("This number isn't linked to an account on this NoClick instance. To link it, open Chat on the web, "
                  "tap Connect and scan the code.")
NO_MODEL_KEY_REPLY = ("This NoClick instance has no {env_var} yet, so I can't answer. Add it under Settings → "
                      "Self-hosted, then text again.")


@dataclass(frozen=True)
class PhoneTransport:
    """What a channel brings to a text: what it calls itself and how it answers."""

    source: str  # the app the number is recorded as texting from: "whatsapp" | "imessage"
    turn_channel: str  # stamped on the turn: "whatsapp_text" | "imessage_text"
    label: str  # "WhatsApp" | "iMessage"
    id_key: str  # the provider message id's key on the turn ("wamid", "message_handle")
    reply: Callable[[str, str], Awaitable[None]]  # (to, markdown); logs a failed send, never raises
    unsupported: str  # what to say to a message it can't read
    # How a later reply to this text is sent (iMessage shares the line's contact card unless it's SMS).
    options: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PhoneText:
    message_id: str
    sender: str  # E.164
    sender_name: str
    text: str  # the body, a button's title or a media caption
    readable: bool  # a turn can take it; else the transport's unsupported notice
    # The turn's input for a message with media: (account, caption) -> (text, attachments), where ``account`` is who
    # pays for reading it (``user_id``, ``organization_id``) and ``caption`` the words the turn reads with it; None for
    # plain text.
    prepare_input: Optional[Callable[[Any, str], Awaitable[Tuple[str, list]]]] = None
    media: str = ""  # what it carries besides words, as a person names it (``media_name``)
    raw: Dict[str, Any] = field(default_factory=dict, compare=False)  # the provider's message, for a platform's rule


@dataclass(frozen=True)
class TextAccount:
    """The account a bound number reaches."""

    user_id: str
    email: Optional[str]
    organization_id: Optional[str]


VOICE_NOTE = "voice note"
MEDIA_NAMES = {"audio": "audio", "image": "photo", "sticker": "sticker", "video": "video", "document": "document",
               "contacts": "contact card", "location": "location", "unsupported": "unsupported message"}


def media_name(kind: str, *, voice: bool = False) -> str:
    """What a message of ``kind`` carries besides its words ("" for words alone)."""
    return VOICE_NOTE if voice else MEDIA_NAMES.get(kind, "")


def chunk(text: str, limit: int = TEXT_LIMIT) -> List[str]:
    parts: List[str] = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = text.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = limit
        parts.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text:
        parts.append(text)
    return parts


_MEDIA = re.compile(r"!\[([^\]]*)\]\((https?://[^)\s]+)\)")


def split_media(markdown: str) -> Tuple[List[Tuple[str, str]], str]:
    """(url, caption) for each file the Markdown embeds as ``![caption](url)``, and the text left."""
    return [(url, caption) for caption, url in _MEDIA.findall(markdown)], _MEDIA.sub("", markdown)


# A page a browser draws (HTML, SVG): a phone may open it as a file in a chat (as its source, or not at all) or save it
# from a link, so one NoClick stores goes as both, the file and the link that saves it.
PAGE_TYPES = frozenset({"text/html", "application/xhtml+xml", "image/svg+xml"})


@dataclass(frozen=True)
class Embed:
    """A file a reply embeds, and what it holds (``file``; None when nothing could tell, so it goes as a link)."""

    url: str
    caption: str
    file: Optional[FileInfo]
    download: Optional[str] = None  # the link that saves it, for a file NoClick stores (resource_store.download_url)

    @property
    def link(self) -> str:
        """The embed as a line of text: the link that saves the file where there is one, else its URL."""
        label = self.caption or (self.file.name if self.file else "")
        url = self.download or self.url
        return f"{label}: {url}" if label else url

    @property
    def page(self) -> bool:
        """A page NoClick stores: its link goes in the text even when the file itself is sent."""
        return bool(self.download and self.file and self.file.mime_type in PAGE_TYPES)

    @property
    def note(self) -> str:
        """Its caption, unless that only repeats the file's name, which the chat shows already."""
        if self.file and self.caption in (self.file.name, os.path.splitext(self.file.name)[0]):
            return ""
        return self.caption


async def read_embeds(markdown: str) -> Tuple[List[Embed], str]:
    """Each file the Markdown embeds, judged by what it holds rather than its URL (``describe_url``), with the link
    that saves it, and the text left."""
    found, text = split_media(markdown)
    files = await asyncio.gather(*(describe_url(url) for url, _ in found))
    return [Embed(url, caption, file, download_url(url)) for (url, caption), file in zip(found, files)], text


def _masked(email: Optional[str]) -> str:
    if not email or "@" not in email:
        return ""
    name, domain = email.split("@", 1)
    return f" ({name[:1]}•••@{domain})"


async def notice_once(transport: PhoneTransport, to: str, code: str, text: str) -> None:
    """One notice of kind ``code`` per sender per day; without Redis, one per message."""
    client = get_shared_redis()
    if client is not None:
        try:
            if not await client.set(f"{transport.source}:notice:{code}:{to}", "1", ex=NOTICE_TTL_S, nx=True):
                return
        except Exception as exc:
            logger.warning("%s notice budget unavailable: %s", transport.source, exc)
    await transport.reply(to, text)


async def link_by_code(transport: PhoneTransport, sender: str, code: str) -> None:
    """The first message from the web's draft: link the number, say which account, and run no turn on the draft."""
    try:
        result = await default_service().link_by_code(sender, code, source=transport.source)
    except PhoneLinkError as exc:
        logger.info("%s_link_code_refused sender=%s kind=%s", transport.source, sender, exc.kind)
        await transport.reply(sender, f"{exc}.")
        return
    who = _masked(await get_user_email(get_native_pool(), result["user_id"]))
    await transport.reply(sender, (ALREADY_LINKED_REPLY if result["already"] else LINKED_REPLY).format(who=who))


async def coordinator_reply(transport: PhoneTransport, message: PhoneText, account: Any, *, text: str, caption: str,
                            note: Optional[str] = None) -> None:
    """One coordinator turn on the text, in the account's conversation, its reply sent back on the app it came on.
    ``account`` has ``user_id``, ``email`` and ``organization_id``; ``text`` is what the turn reads for a plain text,
    ``caption`` the words read with a file; ``note``, what the turn is told beside it."""

    async def prepare_input():
        if message.prepare_input is None:
            return text, []
        return await message.prepare_input(account, caption)

    pieces: List[str] = []

    async def sink(event) -> None:
        if event.message:
            pieces.append(event.message)

    await run_coordinator_turn(
        sio=get_sio(), sid="", user_id=account.user_id, user_email=account.email, text=text,
        sink=sink, extra={"channel": transport.turn_channel, transport.id_key: message.message_id}, note=note,
        prepare_input=prepare_input,
    )
    reply = "".join(pieces).strip()
    if reply:
        await transport.reply(message.sender, reply)
    else:
        logger.warning("%s_turn_silent user=%s message=%s", transport.source, account.user_id, message.message_id)


async def handle_phone_text(transport: PhoneTransport, message: PhoneText) -> None:
    """Answer one text; the transport has already claimed it against redelivery."""
    rule = capability(PHONE_TEXT)
    if rule is not None:
        await rule(transport, message)
        return
    code = link_code_in(message.text) if message.prepare_input is None else None
    if code:
        await link_by_code(transport, message.sender, code)
        return
    if get_shared_redis() is None:
        # Nothing counts notices or redeliveries: answering would be once per delivery, to anyone.
        logger.warning("%s text from %s left unanswered: texting needs REDIS_URL", transport.source, message.sender)
        return
    pool = get_native_pool()
    phones = PhoneRepo(pool)
    sender = normalize_e164(message.sender)
    binding = await phones.get_user_by_phone(sender) if sender else None
    if binding is None:
        await notice_once(transport, message.sender, "unbound", UNBOUND_NOTICE)
        return
    user_id = str(binding["user_id"])
    await phones.touch_seen(sender)
    await phones.record_app(sender, transport.source)
    if not message.readable:
        await transport.reply(message.sender, transport.unsupported)
        return
    missing = missing_brain_key(COORDINATOR_MODEL)
    if missing:
        await transport.reply(message.sender, NO_MODEL_KEY_REPLY.format(env_var=missing[0]))
        return
    allowed, limit_error = await plan_allows_turn(pool, user_id)
    if not allowed:
        await transport.reply(message.sender, limit_error or "You have reached today's limit; try again tomorrow.")
        return
    async with pool.acquire() as conn:
        organization_id = await get_user_org_context(conn, user_id)
    account = TextAccount(user_id=user_id, email=await get_user_email(pool, user_id) or None,
                          organization_id=organization_id)
    await coordinator_reply(transport, message, account, text=message.text, caption=message.text)
