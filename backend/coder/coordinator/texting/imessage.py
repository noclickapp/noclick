"""A text to the assistant's iMessage line, as Sendblue delivers it: verified by the webhook secret Sendblue sends with
every call, marked read with a typing indicator while the turn runs, and answered in plain text (iMessage renders no
markup) with media sent as attachments, then the line's name and photo shared into the chat. Apple authenticates the
sender's handle and Sendblue relays it. One-to-one only: a group message is left alone. Also how the assistant messages
its owner over iMessage outside a reply."""

from __future__ import annotations

import hmac
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from urllib.parse import unquote, urlsplit

from coder.coordinator.reach import with_link
from coder.coordinator.texting.channel import (
    TEXT_LIMIT, Embed, PhoneText, PhoneTransport, chunk, handle_phone_text, media_name, read_embeds,
)
from nodes.core.media_resolver import read_url
from repositories.phones import PhoneRepo
from utils.app_event_dedup import mark_delivered, was_delivered
from utils.async_helpers import spawn
from utils.prompts import PromptPack
from utils.sendblue import UPLOAD_LIMIT, Sendblue, SendblueError

logger = logging.getLogger(__name__)

PROMPTS = PromptPack("coordinator")

CHANNEL = "imessage_text"
DEDUP_PROVIDER = "sendblue"
SOURCE = "imessage"
SECRET_VAR = "SENDBLUE_WEBHOOK_SECRET"
UNSUPPORTED_NOTICE = "I couldn't read that message. Try text, a photo, a voice message or a document."
IMAGE_LIMIT = 10 * 1024 * 1024

_IMAGE_EXT = (".jpg", ".jpeg", ".png", ".heic", ".heif", ".gif", ".webp")
_AUDIO_EXT = (".caf", ".m4a", ".mp3", ".aac", ".amr", ".wav", ".ogg")
_VIDEO_EXT = (".mp4", ".mov", ".m4v")


@dataclass(frozen=True)
class InboundMessage:
    handle: str  # Sendblue's message_handle
    sender: str  # E.164
    text: str
    media_url: str = ""
    kind: str = "text"  # text | image | audio | video | document
    service: str = "iMessage"  # or "SMS", when the phone has no iMessage
    raw: Dict[str, Any] = field(default_factory=dict, compare=False)  # Sendblue's payload


def webhook_secret() -> str:
    return os.environ.get(SECRET_VAR, "").strip()


def verify_secret(expected: str, header: Optional[str]) -> bool:
    """Sendblue sends the configured webhook secret as is, in ``sb-signing-secret``."""
    return bool(expected) and bool(header) and hmac.compare_digest(header, expected)


def _media_kind(url: str) -> str:
    path = url.lower().split("?", 1)[0]
    if path.endswith(_IMAGE_EXT):
        return "image"
    if path.endswith(_AUDIO_EXT):
        return "audio"
    if path.endswith(_VIDEO_EXT):
        return "video"
    return "document"


def parse_inbound(payload: Dict[str, Any], *, line: str) -> Optional[InboundMessage]:
    """The message in a "receive" delivery addressed to our line, or None for
    what isn't one: our own sends echoed back, another line's traffic, groups,
    and anything that isn't a message."""
    if payload.get("is_outbound") or payload.get("group_id"):
        return None
    if (payload.get("sendblue_number") or payload.get("to_number")) != line:
        return None
    if (payload.get("message_type") or "message") != "message":
        return None
    handle, sender = payload.get("message_handle") or "", payload.get("number") or payload.get("from_number") or ""
    text, media_url = (payload.get("content") or "").strip(), payload.get("media_url") or ""
    if not handle or not sender or not (text or media_url):
        return None
    return InboundMessage(
        handle=handle, sender=f"+{sender.lstrip('+')}", text=text, media_url=media_url,
        kind=_media_kind(media_url) if media_url else "text", service=payload.get("service") or "iMessage",
        raw=payload,
    )


_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_EMPHASIS = re.compile(r"(\*\*|__)(.+?)\1")
_HEADING = re.compile(r"^#{1,6}[ \t]+", re.M)
_BULLET = re.compile(r"^[ \t]*[-*][ \t]+", re.M)
_FENCE = re.compile(r"^```[A-Za-z0-9_-]*\n?", re.M)
_CODE = re.compile(r"`([^`\n]+)`")


def to_imessage_text(markdown: str) -> str:
    """Plain text: iMessage shows markup characters as they are, so links,
    emphasis, headings, list markers and code fences become plain lines."""
    text = _LINK.sub(r"\1: \2", markdown)
    text = _EMPHASIS.sub(r"\2", text)
    text = _HEADING.sub("", text)
    text = _BULLET.sub("• ", text)
    text = _FENCE.sub("", text)
    text = _CODE.sub(r"\1", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _shown_inline(embed: Embed) -> bool:
    """A picture or a video, which the chat shows as itself (a page NoClick stores also goes as its link)."""
    return embed.file.mime_type.split("/", 1)[0] in ("image", "video") and not embed.page


async def _media_url(api: Sendblue, embed: Embed) -> str:
    """Where Sendblue sends an embedded file from. Sendblue reads a file's type off its URL, which must end in its
    extension and carry no signature; a file whose URL doesn't, or one sent in its place (an SVG's picture), goes up
    to Sendblue under its own name first."""
    ext = os.path.splitext(embed.file.name)[1].lower()
    parts = urlsplit(embed.url)
    if embed.data is not None:
        data = embed.data
    elif ext and not parts.query and not parts.fragment and unquote(parts.path).lower().endswith(ext):
        return embed.url
    else:
        try:
            data = await read_url(embed.url, max_bytes=UPLOAD_LIMIT)
        except ValueError as exc:
            raise SendblueError(f"couldn't read {embed.file.name} to send it: {exc}") from exc
    return await api.upload_file(data, filename=embed.file.name, mime_type=embed.file.mime_type)


async def send_rich(api: Sendblue, to: str, markdown: str) -> Optional[str]:
    """Plain text, then each embedded file as an attachment (iMessage takes any file), with its caption; one nothing
    can tell the type of, or past Sendblue's cap, goes as a link line with the text, and so does a page NoClick stores
    (``Embed.page``) beside its attachment, and an SVG goes as the picture it draws. A reply whose one file is a picture
    or a video goes in one send, the file with the text (in place of the embed's caption), as WhatsApp captions it.
    Every attachment is ready before
    anything is sent. The first message handle, or None when nothing could be sent."""
    try:
        embeds, text = await read_embeds(markdown)
    except ValueError as exc:
        raise SendblueError(str(exc)) from exc
    files = [embed for embed in embeds if embed.file is not None and (embed.file.size_bytes or 0) <= UPLOAD_LIMIT]
    attachments = [(embed, await _media_url(api, embed)) for embed in files]
    text = to_imessage_text("\n".join([text.rstrip(),
                                       *(embed.link for embed in embeds if embed not in files or embed.page)]))
    if len(embeds) == 1 and len(files) == 1 and _shown_inline(files[0]) and 0 < len(text) <= TEXT_LIMIT:
        return await api.send(to, content=text, media_url=attachments[0][1])
    first: Optional[str] = None
    for part in chunk(text):
        sent = await api.send(to, content=part)
        first = first or sent
    for embed, media_url in attachments:
        sent = await api.send(to, content=embed.note or None, media_url=media_url)
        first = first or sent
    return first


def transport(api: Sendblue, *, share_profile: bool) -> PhoneTransport:
    async def reply(to: str, text: str) -> None:
        try:
            await send_rich(api, to, text)
        except SendblueError as exc:
            logger.error("imessage_reply_failed to=%s status=%s key=%s: %s", to, exc.status, exc.key, exc)
            return
        if share_profile:
            try:
                await api.share_profile(to)
            except SendblueError as exc:
                logger.warning("imessage_share_profile_failed to=%s status=%s key=%s: %s", to, exc.status, exc.key, exc)

    return PhoneTransport(source=SOURCE, turn_channel=CHANNEL, label="iMessage", id_key="message_handle",
                          reply=reply, unsupported=UNSUPPORTED_NOTICE, options={"share_profile": share_profile})


async def _read_and_typing(message: InboundMessage, api: Sendblue) -> None:
    for step in (api.mark_read, api.typing):
        try:
            await step(message.sender)
        except SendblueError as exc:
            logger.warning("imessage_%s_failed handle=%s status=%s: %s", step.__name__, message.handle, exc.status, exc)


async def handle_inbound(message: InboundMessage, api: Sendblue) -> None:
    # Claimed before the turn, as on WhatsApp: a message answered twice is worse than one lost to a crash.
    if await was_delivered(DEDUP_PROVIDER, message.handle):
        return
    await mark_delivered(DEDUP_PROVIDER, message.handle)
    if message.service == "iMessage":
        # Receipts and typing exist on iMessage only; neither may hold up the reply, so they go beside it.
        spawn(_read_and_typing(message, api), name=f"imessage-typing:{message.handle}")

    async def prepare_media(account, caption: str):
        from coder.coordinator.attachments import prepare_attachment
        from nodes.core.media_digest import MAX_TRANSCRIBE_BYTES
        from utils.content_extraction import MAX_EXTRACT_BYTES, BillingContext

        limit = {"image": IMAGE_LIMIT, "document": MAX_EXTRACT_BYTES}.get(message.kind, MAX_TRANSCRIBE_BYTES)
        try:
            data, mime_type = await api.download(message.media_url, max_bytes=limit)
            return await prepare_attachment(
                data, kind=message.kind, mime_type=mime_type, filename=message.media_url.rsplit("/", 1)[-1].split("?", 1)[0],
                caption=caption, voice=message.kind == "audio",
                billing=BillingContext(user_id=account.user_id, organization_id=account.organization_id),
            )
        except Exception as exc:
            # Never put a provider error body or a media URL into the conversation.
            logger.warning("imessage_media_failed handle=%s kind=%s error=%s", message.handle, message.kind, type(exc).__name__)
            return f"{caption}\n\n{PROMPTS.unreadable_attachment(message.kind)}".strip(), []

    # Name & Photo Sharing is iMessage only.
    await handle_phone_text(transport(api, share_profile=message.service == "iMessage"), PhoneText(
        message_id=message.handle, sender=message.sender, sender_name="", text=message.text, readable=True,
        prepare_input=prepare_media if message.media_url else None,
        media=media_name(message.kind, voice=message.kind == "audio") if message.media_url else "",
        raw=message.raw,
    ))


async def send_owner_imessage(pool, user_id: str, text: str, *, link: Optional[str] = None,
                              share_profile: bool = False, typing: bool = False) -> Dict[str, Any]:
    """Plain text (and any media) to the number the owner texts from. ``share_profile``: share the line's contact
    card after it (best effort), as a reply to an iMessage text does. ``typing``: more is coming, so the typing
    indicator shows again after it (best effort). A refused send says why rather than pretending."""
    api = Sendblue.from_env()
    if api is None:
        return {"success": False, "error": "iMessage is not configured on this instance", "permanent": True}
    binding = await PhoneRepo(pool).get_reach_phone(user_id)
    if binding is None:
        return {"success": False, "error": "The owner has no linked phone; they can text NoClick to link one.",
                "permanent": True}
    body = with_link(text, link)
    try:
        handle = await send_rich(api, binding["phone_e164"], body)
    except SendblueError as exc:
        logger.error("owner_imessage_failed user=%s status=%s key=%s: %s", user_id, exc.status, exc.key, exc)
        return {"success": False, "error": f"iMessage refused the message: {exc}"}
    if share_profile:
        try:
            await api.share_profile(binding["phone_e164"])
        except SendblueError as exc:
            logger.warning("owner_imessage_share_profile_failed user=%s status=%s: %s", user_id, exc.status, exc)
    if typing:
        try:
            await api.typing(binding["phone_e164"])
        except SendblueError as exc:
            logger.warning("owner_imessage_typing_failed user=%s status=%s: %s", user_id, exc.status, exc)
    return {"success": True, "channel": "imessage", "message_id": handle}
