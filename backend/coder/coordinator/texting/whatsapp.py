"""A WhatsApp message to the assistant's number, as Meta delivers it: verified, parsed, acknowledged at once,
read-receipted and answered in WhatsApp's own markup inside the service window the message opened. Meta authenticates
the sender. Also how the assistant messages its owner on WhatsApp outside a reply: free-form text, which WhatsApp only
delivers within 24 hours of the owner's last text."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from coder.coordinator.reach import with_link
from coder.coordinator.texting.channel import (
    Embed, PhoneText, PhoneTransport, chunk, handle_phone_text, media_name, read_embeds,
)
from nodes.core.media_resolver import read_url
from repositories.phones import PhoneRepo
from utils.app_event_dedup import mark_delivered, was_delivered
from utils.async_helpers import spawn
from utils.prompts import PromptPack
from utils.whatsapp_cloud_api import CAPTION_LIMIT, CloudApi, WhatsAppSendError

logger = logging.getLogger(__name__)

PROMPTS = PromptPack("coordinator")

CHANNEL = "whatsapp_text"
DEDUP_PROVIDER = "whatsapp_meta"
SOURCE = "whatsapp"
UNSUPPORTED_NOTICE = "I couldn't read that message type. Try text, a photo, voice note, document, contact card or location."
DIGEST_KINDS = ("audio", "document", "video")
VISUAL_KINDS = ("image", "sticker")
TURN_KINDS = ("text", "contacts", "location", *DIGEST_KINDS, *VISUAL_KINDS)
SHARED_ITEM_LIMIT = 16000
IMAGE_LIMIT = 10 * 1024 * 1024

RE_ENGAGEMENT_ERROR = 131047  # Meta: more than 24h since the recipient last wrote to this number
# How long after the owner's last text the assistant may message them on WhatsApp.
SERVICE_WINDOW = timedelta(hours=24)
# A text sent this close to the window's end could land after it, so it's treated as shut.
WINDOW_EDGE = timedelta(minutes=5)
PAST_WINDOW = ("WhatsApp only delivers a message within 24 hours of the owner's last text to this number, and that "
               "window is shut, so nothing was sent. It's in the web chat; texting this number opens the window again")


@dataclass(frozen=True)
class InboundMessage:
    wamid: str
    sender: str  # E.164
    sender_name: str
    kind: str  # TURN_KINDS or "unsupported"
    text: str = ""  # the body, a button's title, or a media caption
    type: str = "text"
    media_id: str = ""
    mime_type: str = ""
    filename: str = ""
    voice: bool = False  # a voice note rather than an audio file
    animated: bool = False
    raw: Dict[str, Any] = field(default_factory=dict, compare=False)  # Meta's message object


def verify_signature(app_secret: str, body: bytes, header: Optional[str]) -> bool:
    if not app_secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header[7:], expected)


def _message_text(m: Dict[str, Any]) -> Optional[str]:
    kind = m.get("type")
    if kind == "text":
        return (m.get("text") or {}).get("body") or None
    if kind == "button":
        return (m.get("button") or {}).get("text") or None
    if kind == "interactive":
        interactive = m.get("interactive") or {}
        reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
        return reply.get("title") or None
    return None


def _ours(change: Dict[str, Any], phone_number_id: str) -> Optional[Dict[str, Any]]:
    value = change.get("value") or {}
    if change.get("field") != "messages" or (value.get("metadata") or {}).get("phone_number_id") != phone_number_id:
        return None
    return value


def parse_failed(payload: Dict[str, Any], *, phone_number_id: str) -> List[Tuple[str, str]]:
    """``(wamid, why)`` for each message from our number Meta reports it failed after taking it (a status
    ``failed``: 131047 outside the window, 131049 held back by Meta, 131026 undeliverable)."""
    out: List[Tuple[str, str]] = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = _ours(change, phone_number_id)
            for status in (value or {}).get("statuses") or []:
                if status.get("status") == "failed" and status.get("id"):
                    errors = status.get("errors") or [{}]
                    why = "; ".join(f"({e.get('code')}) {e.get('title') or e.get('message') or 'failed'}" for e in errors)
                    out.append((status["id"], f"WhatsApp failed it after sending: {why}"))
    return out


def parse_inbound(payload: Dict[str, Any], *, phone_number_id: str) -> List[InboundMessage]:
    """The messages in one delivery addressed to our number. Status receipts
    and another number's traffic are not messages."""
    out: List[InboundMessage] = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = _ours(change, phone_number_id)
            if value is None:
                continue
            names = {c.get("wa_id"): (c.get("profile") or {}).get("name") or "" for c in value.get("contacts") or []}
            for m in value.get("messages") or []:
                sender, wamid = m.get("from") or "", m.get("id") or ""
                if not sender or not wamid:
                    continue
                kind, media = (m.get("type") or ""), {}
                text = _message_text(m)
                if kind in DIGEST_KINDS or kind in VISUAL_KINDS:
                    media = m.get(kind) or {}
                    if not media.get("id"):
                        kind = "unsupported"
                elif kind in ("contacts", "location") and m.get(kind):
                    # Message contents, distinct from value.contacts (the authenticated sender's profile).
                    text = PROMPTS.shared_item(kind, json.dumps(m[kind], ensure_ascii=False))
                    if len(text) > SHARED_ITEM_LIMIT:
                        text = text[:SHARED_ITEM_LIMIT] + PROMPTS.SHARED_ITEM_CUT
                elif text:
                    kind = "text"
                else:
                    kind = "unsupported"
                out.append(InboundMessage(
                    wamid=wamid, sender=f"+{sender.lstrip('+')}", sender_name=names.get(sender, ""),
                    kind=kind, text=text or media.get("caption") or "", type=m.get("type") or "",
                    media_id=media.get("id") or "", mime_type=media.get("mime_type") or "",
                    filename=media.get("filename") or "", voice=bool(media.get("voice")),
                    animated=bool(media.get("animated")), raw=m,
                ))
    return out


_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_HEADING = re.compile(r"^#{1,6}[ \t]+", re.M)
_BULLET = re.compile(r"^[ \t]*[-*][ \t]+", re.M)
_FENCE = re.compile(r"```[A-Za-z0-9_-]*\n")


def to_whatsapp_text(markdown: str) -> str:
    """WhatsApp's own markup (*bold*, _italic_, ```mono```); what it does not
    render — headings, link syntax, list markers — becomes plain lines."""
    text = _LINK.sub(r"\1: \2", markdown)
    text = _BOLD.sub(r"*\1*", text)
    text = _HEADING.sub("", text)
    text = _BULLET.sub("• ", text)
    text = _FENCE.sub("```\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


MB = 1024 * 1024
# What Meta plays as each kind of media sent by link, and its cap for each (Cloud API, supported media types).
NATIVE_MEDIA = {
    "image": ({"image/jpeg", "image/png"}, 5 * MB),
    "video": ({"video/mp4", "video/3gpp"}, 16 * MB),
    "audio": ({"audio/aac", "audio/amr", "audio/mpeg", "audio/mp4", "audio/ogg", "audio/opus"}, 16 * MB),
}
# The documents Meta takes (PDF, plain text, Word, Excel, PowerPoint), each up to DOCUMENT_LIMIT. It reads a file's
# type from what it holds and refuses any other (an HTML page, a ZIP): another text file goes up as the plain text it
# is, under its own name (``TEXT``); anything else goes as a link.
DOCUMENT_TYPES = {
    "application/pdf", "text/plain", "application/msword", "application/vnd.ms-excel", "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
DOCUMENT_LIMIT = 100 * MB
# The files WhatsApp shows a caption under, as a photo's: a reply's text can ride one of them.
CAPTIONED = ("image", "video")
TEXT = "text"
_TEXT_TYPES = ("application/json", "application/xml", "application/javascript", "application/yaml",
               "application/x-yaml", "application/x-sh", "application/xhtml+xml")
_SAME_TYPE = {"image/jpg": "image/jpeg", "audio/mp3": "audio/mpeg", "audio/x-m4a": "audio/mp4",
              "audio/mp4a-latm": "audio/mp4", "audio/x-aac": "audio/aac"}


def sent_as(embed: Embed) -> Optional[str]:
    """How WhatsApp carries an embedded file: as an image, video, audio or document by its link, as a text file
    uploaded (``TEXT``), or None: as a link (``Embed.link``), when Meta takes no file of its type or size, or nothing
    says what it holds."""
    file = embed.file
    if file is None:
        return None
    mime, size = _SAME_TYPE.get(file.mime_type, file.mime_type), file.size_bytes or 0
    for kind, (types, cap) in NATIVE_MEDIA.items():
        if mime in types:
            return kind if size <= cap else None
    if size > DOCUMENT_LIMIT:
        return None
    if mime in DOCUMENT_TYPES:
        return "document"
    return TEXT if mime.startswith("text/") or mime in _TEXT_TYPES else None


async def _uploaded_text(api: CloudApi, embed: Embed) -> str:
    try:
        data = await read_url(embed.url, max_bytes=DOCUMENT_LIMIT)
    except ValueError as exc:
        raise WhatsAppSendError(f"couldn't read {embed.file.name} to send it: {exc}") from exc
    return await api.upload_media(data, filename=embed.file.name, mime_type="text/plain")


async def send_rich(api: CloudApi, to: str, markdown: str) -> Optional[str]:
    """Text in WhatsApp markup, then each embedded file as a file (``sent_as``), an SVG as the picture it draws; one
    that can't go as a file is a link line in the text, and so is a page NoClick stores (``Embed.page``) beside its
    file. A reply whose one file is a picture or a video, with text that fits a caption, is one message: the file with
    the text as its caption (in place of the embed's own). Every file is ready before anything is sent. The first
    message id, or None when nothing could be sent."""
    try:
        embeds, text = await read_embeds(markdown)
    except ValueError as exc:
        raise WhatsAppSendError(str(exc)) from exc
    files = []
    for embed in embeds:
        kind = sent_as(embed)
        if kind == TEXT:
            files.append((embed, "document", {"media_id": await _uploaded_text(api, embed)}))
        elif kind is not None and embed.data is not None:
            media_id = await api.upload_media(embed.data, filename=embed.file.name, mime_type=embed.file.mime_type)
            files.append((embed, kind, {"media_id": media_id}))
        elif kind is not None:
            files.append((embed, kind, {"link": embed.url}))
    sent_files = [embed for embed, _, _ in files]
    text = to_whatsapp_text("\n".join([text.rstrip(),
                                       *(embed.link for embed in embeds if embed not in sent_files or embed.page)]))
    if len(embeds) == 1 and len(files) == 1 and files[0][1] in CAPTIONED and 0 < len(text) <= CAPTION_LIMIT:
        embed, kind, where = files[0]
        return await api.send_media(to, kind, caption=text, filename=embed.file.name, **where)
    first: Optional[str] = None
    for part in chunk(text):
        sent = await api.send_text(to, part)
        first = first or sent
    for embed, kind, where in files:
        sent = await api.send_media(to, kind, caption=embed.note, filename=embed.file.name, **where)
        first = first or sent
    return first


def transport(api: CloudApi) -> PhoneTransport:
    async def reply(to: str, text: str) -> None:
        try:
            await send_rich(api, to, text)
        except WhatsAppSendError as exc:
            logger.error("whatsapp_reply_failed to=%s code=%s: %s", to, exc.code, exc)

    return PhoneTransport(source=SOURCE, turn_channel=CHANNEL, label="WhatsApp", id_key="wamid",
                          reply=reply, unsupported=UNSUPPORTED_NOTICE)


async def prepare_media_message(message: InboundMessage, api: CloudApi, account) -> Tuple[str, list]:
    """A received file as the turn reads it, fetched with our token and digested by the shared attachment readers;
    ``account`` (``user_id``, ``organization_id``) pays for reading it."""
    from coder.coordinator.attachments import prepare_attachment
    from nodes.core.media_digest import MAX_TRANSCRIBE_BYTES, DigestError
    from utils.content_extraction import MAX_EXTRACT_BYTES, BillingContext

    meta = await api.get_media(message.media_id)
    limit = IMAGE_LIMIT if message.kind in VISUAL_KINDS else MAX_EXTRACT_BYTES if message.kind == "document" else MAX_TRANSCRIBE_BYTES
    if meta.get("file_size", 0) > limit:
        raise DigestError(f"Attachment exceeds the {limit // (1024 * 1024)}MB limit")
    data = await api.download(meta["url"], max_bytes=limit)
    return await prepare_attachment(
        data, kind=message.kind, mime_type=meta.get("mime_type") or message.mime_type,
        filename=message.filename, caption=message.text, voice=message.voice,
        animated=message.animated,
        billing=BillingContext(user_id=account.user_id, organization_id=account.organization_id),
    )


async def _read(message: InboundMessage, api: CloudApi) -> None:
    try:
        await api.mark_read(message.wamid, typing=message.kind in TURN_KINDS)
    except WhatsAppSendError as exc:
        logger.warning("whatsapp_mark_read_failed wamid=%s: %s", message.wamid, exc)


async def handle_inbound(message: InboundMessage, api: CloudApi) -> None:
    # Claimed BEFORE the turn, unlike app-event fan-out: a message answered
    # twice is worse than one lost to a crash mid-turn, and Meta only redelivers
    # when the ack itself was lost.
    if await was_delivered(DEDUP_PROVIDER, message.wamid):
        return
    await mark_delivered(DEDUP_PROVIDER, message.wamid)
    # The receipt (and typing) goes beside the turn, never ahead of it.
    spawn(_read(message, api), name=f"whatsapp-read:{message.wamid}")

    async def prepare_media(account, caption: str):
        try:
            return await prepare_media_message(replace(message, text=caption), api, account)
        except Exception as exc:
            # Do not put provider error bodies / signed URLs into the conversation.
            logger.warning("whatsapp_media_failed wamid=%s kind=%s error=%s", message.wamid, message.kind, type(exc).__name__)
            return f"{caption}\n\n{PROMPTS.unreadable_attachment(message.kind)}".strip(), []

    await handle_phone_text(transport(api), PhoneText(
        message_id=message.wamid, sender=message.sender, sender_name=message.sender_name, text=message.text,
        readable=message.kind in TURN_KINDS,
        prepare_input=prepare_media if message.kind in (*DIGEST_KINDS, *VISUAL_KINDS) else None,
        media=media_name(message.kind, voice=message.voice), raw=message.raw,
    ))


async def _window_until(phones: PhoneRepo, user_id: str, reach: Dict[str, Any]) -> Optional[datetime]:
    """Until when a free-form message goes (the window the owner's last text opened, when it came over WhatsApp,
    less ``WINDOW_EDGE``); None when it's shut."""
    seen = reach.get("last_seen_at")
    until = seen + SERVICE_WINDOW - WINDOW_EDGE if seen is not None else None
    if until is None or until <= datetime.now(timezone.utc):
        return None
    return until if await phones.last_seen_app(user_id) == "whatsapp" else None


async def window_until(pool, user_id: str) -> Optional[datetime]:
    """``_window_until`` for the owner's number; None without one."""
    phones = PhoneRepo(pool)
    binding = await phones.get_reach_phone(user_id)
    return await _window_until(phones, user_id, binding) if binding else None


PastWindow = Callable[[Any, CloudApi, str, str, str, Optional[str]], Awaitable[Dict[str, Any]]]


async def send_owner_whatsapp(pool, user_id: str, text: str, *, link: Optional[str] = None,
                              past_window: Optional[PastWindow] = None) -> Dict[str, Any]:
    """The assistant's message to its owner's number: WhatsApp markup inside the window, ``past_window(pool, api,
    user_id, phone, body, link)`` once it's shut (judged here or by Meta's own refusal), else a refusal saying so.
    A send Meta refuses is reported as a failure, so the caller can try another channel."""
    api = CloudApi.from_env()
    if api is None:
        return {"success": False, "error": "WhatsApp is not configured on this instance", "permanent": True}
    phones = PhoneRepo(pool)
    binding = await phones.get_reach_phone(user_id)
    if binding is None:
        return {"success": False, "error": "The owner has no linked phone; they can link one under Settings → Phone.",
                "permanent": True}
    phone, body = binding["phone_e164"], with_link(text, link)
    if await _window_until(phones, user_id, binding) is not None:
        try:
            # Text in WhatsApp markup, and any ![caption](url) as native media.
            message_id = await send_rich(api, phone, body)
        except WhatsAppSendError as exc:
            if exc.code != RE_ENGAGEMENT_ERROR:
                logger.error("owner_message_failed user=%s code=%s: %s", user_id, exc.code, exc)
                return {"success": False, "error": f"WhatsApp refused the message: {exc}"}
        else:
            return {"success": True, "channel": "whatsapp", "message_id": message_id}
    if past_window is not None:
        return await past_window(pool, api, user_id, phone, body, link)
    return {"success": False, "error": PAST_WINDOW, "permanent": True}
