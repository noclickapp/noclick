"""
WhatsApp Business Cloud API automation node.

Provides comprehensive workflow integration for WhatsApp Business Platform with 40+ operations across:
- Messaging: Text, template, media, interactive, location, contacts, reactions
- Media Management: Upload, download, retrieve, delete
- Business Profile: Get, update profile information
- Phone Numbers: Register, verify, get info
- Templates: List, get, create, delete message templates
- Commerce: Catalog, product, multi-product messages
- Message Management: Mark as read
- Webhooks: Receive messages and status updates (via webhook trigger)
- Chats (QR credentials only): List chats/contacts, read message history, edit sent messages
- Groups (QR credentials only): Read members, create, rename, add/remove people, leave, invite link

Authentication: Meta Access Token (temporary 60-day or permanent system user token)
or WAHooks QR scan (a phone's WhatsApp or WhatsApp Business app, linked as a device;
chat/message reads are QR-only)
Base URL: https://graph.facebook.com/v21.0
Documentation: https://developers.facebook.com/docs/whatsapp/cloud-api
"""

import asyncio
import logging
import os
import time
import json
from datetime import datetime, timezone
import uuid
from typing import Dict, Any, ClassVar, Optional, List, Literal, Tuple, Union, Annotated
from pydantic import BaseModel, Field, Discriminator, ConfigDict, field_validator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.whatsapp_trigger_config import CHAT_PICKER_OPTIONS, WhatsAppReceiveMessageConfig
from utils import redis_client
from utils.phone_numbers import NOCLICK_LINE_REFUSAL, is_noclick_number
from utils.wahooks_groups import members_note
from utils.self_echo import is_self_post, record_self_post, self_post_verdict
from utils.ssrf import assert_exact_url_origin, guarded_async_client
from utils.webhook_signatures import verify_wahooks
from nodes.core.connection_evidence import ConnectionEvidence

logger = logging.getLogger(__name__)

# WhatsApp Cloud API base URL (v21.0 as of 2025)
WHATSAPP_API_BASE = "https://graph.facebook.com/v21.0"
WHATSAPP_API_VERSION = "v21.0"
WAHOOKS_API_ORIGIN = "https://api.wahooks.com"
WHATSAPP_MEDIA_ORIGIN = "https://lookaside.fbsbx.com"


# ============================================================================
# WhatsApp Node Credential Schema
# ============================================================================


class WhatsAppAccessTokenCredential(BaseModel):
    """
    Meta Access Token credential for WhatsApp Business Cloud API.

    Get your access token from Meta Developer Console:
    1. Go to https://developers.facebook.com/apps
    2. Select your app -> WhatsApp -> API Setup
    3. Generate either:
       - Temporary token (60 days, testing)
       - Permanent token (via System User in Business Settings)

    Required permissions:
    - whatsapp_business_messaging
    - whatsapp_business_management
    """

    credential_type: Literal["whatsapp_access_token"] = Field(
        "whatsapp_access_token", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ...,
        min_length=1,
        title="Access Token",
        description="Meta access token from Developer Console (temporary or permanent)",
        json_schema_extra={"ui:widget": "password"},
    )
    phone_number_id: str = Field(
        ...,
        min_length=1,
        title="Phone Number ID",
        description="WhatsApp Business Phone Number ID from API Setup page",
        json_schema_extra={"placeholder": "1234567890123456"},
    )
    business_account_id: Optional[str] = Field(
        None,
        title="Business Account ID (Optional)",
        description="WhatsApp Business Account ID (required for template management and account operations)",
        json_schema_extra={
            "placeholder": "Leave empty if not managing templates/account"
        },
    )

    model_config = ConfigDict(json_schema_extra={
        "x-credential-url": "https://developers.facebook.com/apps",
        "x-credential-instructions": "1. Go to Meta Developer Console\n2. Select your app -> WhatsApp -> API Setup\n3. Copy Phone Number ID and Access Token\n4. For permanent token: Business Settings -> System Users -> Generate New Token",
    })


class WhatsAppQRCredential(BaseModel):
    """
    WAHooks QR code scan credential for WhatsApp.

    Connect your WhatsApp account by scanning a QR code.
    No Meta Developer account required - just scan with your phone.
    """

    credential_type: Literal["whatsapp_qr"] = Field(
        "whatsapp_qr", json_schema_extra={"ui:hidden": True}
    )
    connection_id: str = Field(
        ...,
        min_length=1,
        title="Connection ID",
        description="WAHooks connection ID (auto-filled after QR scan)",
        json_schema_extra={"ui:hidden": True},
    )
    # A session on NoClick's one WAHooks account: only the QR scan names it (utils.whatsapp_qr).
    linked_fields: ClassVar[tuple[str, ...]] = ("connection_id",)

    model_config = ConfigDict(json_schema_extra={
        "x-credential-type": "qr_scan",
        "x-credential-instructions": "Connect your WhatsApp by scanning a QR code. A persistent connection fee of $0.99/month will be charged to your balance.",
    })


# Union type for WhatsApp credentials - supports both Meta Access Token and QR scan
WhatsAppCredential = Union[WhatsAppQRCredential, WhatsAppAccessTokenCredential]


# Recipient guidance shared by every QR-capable send op. Leads with the
# reply-to-a-trigger case and tells the agent to echo the chat id VERBATIM:
# wahooks_chat_id() passes @-suffixed ids straight through, so reconstructing
# an E.164 number is both unnecessary and how replies got mis-addressed to
# non-existent accounts (WAHA accepts them, returns PENDING, never delivers).
_RECIPIENT_DESC = (
    "Recipient chat. When replying to an incoming message (e.g. from a WhatsApp "
    "trigger event), pass the sender's chat ID from that event EXACTLY as given "
    "(e.g. 12025550101@c.us or 12025550102@lid) — do NOT reformat it into a "
    "phone number. To start a new conversation, use a phone number in E.164 "
    "format (e.g., +12025550100)."
)


# WAHooks ops addressed by a chat id rather than a send recipient.
_WAHOOKS_CHAT_ID_OPS = frozenset({"get_chat_messages", "edit_message", "mark_chat_read"})
# A linked phone's groups (``utils.wahooks_groups``); the Cloud API has none.
GROUP_OPERATIONS = frozenset({
    "get_group",
    "create_group",
    "rename_group",
    "add_group_participants",
    "remove_group_participants",
    "leave_group",
    "get_group_invite_link",
    "revoke_group_invite_link",
})
# What a QR link (WAHooks, a linked phone) can run; the Cloud API runs the rest.
QR_OPERATIONS = frozenset({
    "send_text_message",
    "send_image_message",
    "send_video_message",
    "send_document_message",
    "send_audio_message",
    "send_location_message",
    "send_contact_card",
    "send_reaction_emoji",
    "list_recent_chats",
    "get_chat_messages",
    "read_recent_messages",
    "list_contacts",
    "edit_message",
    "mark_chat_read",
    "get_account_profile",
    *GROUP_OPERATIONS,
})
# What only a linked phone has: the Cloud API has no chat or message history, and no groups.
QR_ONLY_OPERATIONS = frozenset({
    "list_recent_chats",
    "get_chat_messages",
    "read_recent_messages",
    "list_contacts",
    "edit_message",
    "mark_chat_read",
    "get_account_profile",
    *GROUP_OPERATIONS,
})
_TRIGGER_OPERATIONS = frozenset({"receive_message", "receive_status_update"})


def _megabytes(size: int) -> str:
    return f"{round(size / (1024 * 1024), 1):g} MB"


def wahooks_chat_id(recipient: Any) -> str:
    """A phone number ("+12025550100") or chat id as WAHooks expects it.

    Ids that already carry a server suffix (@c.us / @g.us / @lid /
    @s.whatsapp.net — the chat dropdown, a trigger's ``payload.from``) pass
    through verbatim. An EMPTY recipient raises: templates resolve after the
    config parse, so a reference to a key the trigger never emits
    (``{{ $('t').chat_id }}``) arrives here as "", and WAHooks accepts a bare
    "@s.whatsapp.net", answers PENDING and never delivers — four "successful"
    replies went nowhere that way (2026-09-10).
    """
    raw = str(recipient or "").strip()
    local, _, server = raw.partition("@")
    if not server:
        local = local.lstrip("+").replace(" ", "").replace("-", "")
    if not local:
        raise ValueError(
            "WhatsApp recipient is empty after resolving the config "
            f"(got {recipient!r}). To reply to the message that triggered this "
            "run, reference its chat id verbatim: "
            "{{ $('<trigger node>').payload.from }}."
        )
    return raw if server else f"{local}@s.whatsapp.net"


# ``read_recent_messages``: every active chat read at once, a line per message, so a digest costs one small tool
# result instead of a raw page per chat (ids, media blobs and nulls are ~90% of a page's JSON).
_RECENT_CHATS_PAGE = 200
_RECENT_CHAT_PAGES = 10
_RECENT_PAGE = 100
_RECENT_READS = 8
_RECENT_TEXT_CHARS = 600
_MEDIA_LABELS = {"audio": "voice note", "ptt": "voice note", "vcard": "contact card", "multi_vcard": "contact cards"}
# Status updates, channels and broadcast lists are nobody's conversation.
_NOT_A_CHAT = ("@broadcast", "@newsletter")


def _recent_chat_kind(chat: Dict[str, Any]) -> Optional[str]:
    chat_id = str(chat.get("id") or "")
    if not chat_id or chat_id.endswith(_NOT_A_CHAT):
        return None
    return "groups" if chat.get("isGroup") or chat_id.endswith("@g.us") else "direct"


def _active_chats(client, conn_id: str, since: float, kind: str, wanted: int) -> Tuple[List[Dict[str, Any]], bool]:
    """The chats of ``kind`` with a message since ``since``, most recently active first, at most ``wanted``, and
    whether more were. get_chats lists the most recently active first, so the first older chat ends the scan."""
    found: List[Dict[str, Any]] = []
    for page_no in range(_RECENT_CHAT_PAGES):
        page = client.get_chats(conn_id, limit=_RECENT_CHATS_PAGE, offset=page_no * _RECENT_CHATS_PAGE)
        for chat in page:
            last = (chat.get("lastMessage") or {}).get("timestamp")
            if last is None:
                continue
            if last < since:
                return found, False
            chat_kind = _recent_chat_kind(chat)
            if chat_kind is None or kind not in ("all", chat_kind):
                continue
            if len(found) == wanted:
                return found, True
            found.append(chat)
        if len(page) < _RECENT_CHATS_PAGE:
            return found, False
    return found, True


def _chat_messages_since(client, conn_id: str, chat_id: str, since: float,
                         limit: int) -> Tuple[List[Dict[str, Any]], bool]:
    """A chat's messages since ``since``, oldest first, at most ``limit`` (the newest), and whether it had more."""
    kept: List[Dict[str, Any]] = []
    before = None
    while True:
        page = client.get_messages(conn_id, chat_id, limit=_RECENT_PAGE, before=before)
        messages = page.get("messages") or []
        for message in messages:  # newest first
            if message["timestamp"] < since:
                return kept[::-1], False
            if len(kept) == limit:
                return kept[::-1], True
            kept.append(message)
        before = page.get("nextBefore")
        if not messages or not before:
            return kept[::-1], False


def _recent_line(message: Dict[str, Any], *, chat_name: str, clock: str) -> str:
    at = datetime.fromtimestamp(message["timestamp"], timezone.utc).strftime(clock)
    who = ("You" if message.get("fromMe") else message.get("senderPushName")
           or (message.get("senderJid") or "").partition("@")[0] or chat_name)
    text = " ".join((message.get("text") or "").split())
    if len(text) > _RECENT_TEXT_CHARS:
        text = text[:_RECENT_TEXT_CHARS] + "…"
    kind = message.get("type") or "text"
    if kind != "text":
        text = f"[{_MEDIA_LABELS.get(kind, kind)}] {text}".rstrip()
    return f"{at} {who}: {text}"


async def _read_recent_messages(api_key: str, conn_id: str, config: "WhatsAppReadRecentMessagesConfig") -> Dict[str, Any]:
    """``read_recent_messages``: the active chats listed once, then each read in a worker thread (the client is
    sync), a few at a time."""
    from wahooks import WAHooks

    since = time.time() - config.hours * 3600
    clock = "%H:%M" if config.hours <= 24 else "%m-%d %H:%M"

    def active():
        with WAHooks(api_key=api_key) as client:
            return _active_chats(client, conn_id, since, config.chats, config.max_chats)

    def read(chat):
        with WAHooks(api_key=api_key) as client:
            return _chat_messages_since(client, conn_id, chat["id"], since, config.per_chat_limit)

    chats, truncated = await asyncio.to_thread(active)
    gate = asyncio.Semaphore(_RECENT_READS)

    async def gated(chat):
        async with gate:
            return await asyncio.to_thread(read, chat)

    out = []
    for chat, (messages, more) in zip(chats, await asyncio.gather(*(gated(chat) for chat in chats))):
        if not messages:
            continue
        name = chat.get("name") or chat["id"].partition("@")[0]
        entry = {"chat_id": chat["id"], "name": name, "group": _recent_chat_kind(chat) == "groups",
                 "messages": [_recent_line(m, chat_name=name, clock=clock) for m in messages]}
        if more:
            entry["more"] = True
        out.append(entry)
    return {
        "since": datetime.fromtimestamp(since, timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "chats": out,
        "chat_count": len(out),
        "message_count": sum(len(c["messages"]) for c in out),
        "truncated": truncated,
    }


async def _run_group_op(op_config, conn_id: str, group_id: Optional[str], people: List[str]) -> Dict[str, Any]:
    """A group operation (``utils.wahooks_groups``), answered as the agent relays it: who's in, who isn't and why,
    in its ``summary`` line."""
    from utils import wahooks_groups as groups

    action = op_config.operation
    if action == "get_group":
        return groups.summary(await groups.get_group(conn_id, group_id, refresh=op_config.refresh == "true"))
    if action == "create_group":
        made = await groups.create_group(conn_id, op_config.name, people)
        out = groups.summary(made)
        named = ", ".join(groups.member_label(m) for m in out["members"])
        line = f'Created the group "{out["name"] or op_config.name}" ({out["group_id"]}).'
        line += f" In it besides you: {named}." if named else " No one else is in it yet."
        missed = [e for e in made.get("notAdded") or [] if isinstance(e, dict)]
        not_added, why = groups.people_results(missed, add=True)
        return {**out, "not_added": not_added, "summary": f"{line} {why}" if missed else line}
    if action == "rename_group":
        renamed = await groups.rename_group(conn_id, group_id, op_config.name)
        name = (renamed or {}).get("name") or op_config.name
        return {"group_id": group_id, "name": name, "summary": f'Renamed the group to "{name}".'}
    if action in ("add_group_participants", "remove_group_participants"):
        add = action == "add_group_participants"
        entries = await groups.change_participants(conn_id, group_id, people, add=add)
        results, line = groups.people_results(entries, add=add)
        return {"group_id": group_id, "people": results, "summary": line}
    if action == "leave_group":
        await groups.leave_group(conn_id, group_id)
        return {"group_id": group_id, "left": True,
                "summary": "Left the group: this account no longer gets its messages or sends to it."}
    revoke = action == "revoke_group_invite_link"
    link = await groups.invite_link(conn_id, group_id, revoke=revoke)
    return {"group_id": group_id, "invite_link": link,
            "summary": ("Revoked the old invite link, which no longer lets anyone join; this is the new one."
                        if revoke else "Anyone with this link can join the group.")}


def _chat_key(chat_id: Any) -> str:
    """A chat id spelled one way for comparison: a phone chat arrives as either
    @c.us or @s.whatsapp.net, and a bare phone number names the same chat."""
    local, _, server = wahooks_chat_id(chat_id).partition("@")
    return f"{local}@{'s.whatsapp.net' if server == 'c.us' else server}"


# Which turn shows a chat its account typing, by its token: gone once a reply goes (``agent_turn_ended``), and once
# WAHooks stops keeping the typing up (2 minutes after it began), when nothing is left to stop.
TYPING_SHOWN_S = 120
# A live status opens with this (the agent's "✻ Pulling today's prices..." while it works, edited into its answer):
# one a turn left standing as it stopped partway is edited to say so (``agent_turn_ended``), never left at work.
LIVE_STATUS_MARK = "✻"
# What it says then, as the agent is asked to speak: short and plain.
STATUS_STOPPED = "Sorry, that didn't go through."
STATUS_RETRYING = "Sorry, that didn't go through. I'll try again."


def _is_live_status(text: Any) -> bool:
    return str(text or "").lstrip().startswith(LIVE_STATUS_MARK)


def _status_shown(message_id: str) -> str:
    """The name a turn's live status goes by in what it showed (``event_pickup.shown``)."""
    return f"whatsapp_status:{message_id}"


def _typing_key(connection_id: str, chat_id: str) -> str:
    return f"whatsapp:typing:{connection_id}:{_chat_key(chat_id)}"


async def _typing_not_shown(key: str, token: str) -> None:
    """The typing a turn asked for never started: its end has nothing to stop."""
    client = redis_client.get_shared_redis()
    try:
        if client is not None and await client.get(key) == token.encode():
            await client.delete(key)
    except Exception:
        logger.warning("[WhatsApp] clearing a chat's typing record failed", exc_info=True)


async def _reply_sent(connection_id: str, chat_id: str) -> None:
    """A message went to the chat, which ends the typing a turn showed there: its turn's end has nothing to stop."""
    client = redis_client.get_shared_redis()
    if client is None:
        return
    try:
        await client.delete(_typing_key(connection_id, chat_id))
    except Exception:
        logger.warning("[WhatsApp] clearing a chat's typing record failed", exc_info=True)


def _stanza_id(message: Any) -> Optional[str]:
    """The WhatsApp stanza id of a WAHA message record (``key.id``). It is the
    same id on both ends of one message: a send result carries it at
    ``key.id``, and the receiving connection's inbound delivery at
    ``payload._data.key.id`` (``payload.id`` = ``false_<chat>_<stanza>``)."""
    key = message.get("key") if isinstance(message, dict) else None
    stanza = key.get("id") if isinstance(key, dict) else None
    return stanza if isinstance(stanza, str) and stanza else None


def _sent_message_id(result: Dict[str, Any]) -> Optional[str]:
    """The id a sent message is edited, reacted to and quoted by (``{fromMe}_{chat}_{stanza}``). WAHooks adds it to
    a text send's result as ``id``; a media send comes back as WAHA's raw record, so it's built from ``key`` the way
    WAHooks builds it."""
    if isinstance(result.get("id"), str) and result["id"]:
        return result["id"]
    key = result.get("key") if isinstance(result.get("key"), dict) else {}
    if not (key.get("id") and key.get("remoteJid")):
        return None
    chat = str(key["remoteJid"]).replace("@s.whatsapp.net", "@c.us")
    return f"{'true' if key.get('fromMe') else 'false'}_{chat}_{key['id']}"


def chat_number(chat: Any) -> Optional[str]:
    """The phone digits a chat id or number names (+12025550101,
    12025550101@c.us, 12025550101:3@s.whatsapp.net all name the same one);
    None for a @lid, group or channel, which name no number."""
    local, _, server = str(chat or "").strip().partition("@")
    if server and server not in ("c.us", "s.whatsapp.net"):
        return None
    digits = "".join(ch for ch in local.split(":", 1)[0] if ch.isdigit())
    return digits or None


def _chat_picker_field(
    title: str, description: str = _RECIPIENT_DESC, *, field_name: str
) -> Any:
    """Recipient/chat picker backed by WhatsAppNode.load_field_options.

    QR credentials list the account's chats (with contact names); the Cloud
    API has no chat listing, so allow_custom keeps manual E.164 entry and
    {{references}} working for both credential types.
    """
    return Field(
        ...,
        title=title,
        description=description,
        json_schema_extra={
            "placeholder": "+12025550100",
            "x-dynamic-options": {**CHAT_PICKER_OPTIONS, "field_name": field_name},
            "x-resource-type": "whatsapp_chat",
        },
    )


# ============================================================================
# Message Sending Operations
# ============================================================================


class WhatsAppSendTextConfig(BaseModel):
    """Send a text message"""

    operation: Literal["send_text_message"] = Field(
        "send_text_message",
        json_schema_extra={
            "const": "send_text_message",
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Send Text Message",
        },
        title="Send Text Message",
    )
    to: str = _chat_picker_field("To (Phone or Chat)", field_name="to")
    body: str = Field(
        ...,
        title="Message Text",
        description="Text message content (up to 4096 characters)",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "Enter your message...",
        },
    )
    reply_to_message_id: Optional[str] = Field(
        None,
        title="Reply To (Message ID)",
        description="Send as a reply to this message (from a trigger payload or Get Chat Messages)",
        json_schema_extra={"placeholder": "wamid.xxx... / message id"},
    )
    preview_url: bool = Field(
        False, title="Preview URL", description="Enable URL preview in message"
    )


class WhatsAppSendTemplateConfig(BaseModel):
    """Send a pre-approved template message"""

    operation: Literal["send_template_message"] = Field(
        "send_template_message",
        json_schema_extra={
            "const": "send_template_message",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Template",
            "x-is-trigger": False,
            "x-display-name": "Send Template Message",
        },
        title="Send Template Message",
    )
    to: str = Field(
        ...,
        title="To (Phone Number)",
        description="Recipient phone number in E.164 format",
        json_schema_extra={"placeholder": "+12025550100"},
    )
    template_name: str = Field(
        ...,
        title="Template Name",
        description="Name of the approved message template",
        json_schema_extra={"placeholder": "hello_world"},
    )
    language_code: str = Field(
        "en_US",
        title="Language Code",
        description="Template language code (e.g., en_US, es_ES, pt_BR)",
        json_schema_extra={"placeholder": "en_US"},
    )
    parameters: Optional[str] = Field(
        None,
        title="Template Parameters (JSON)",
        description='JSON array of parameter values for template variables (e.g., [{"type":"text","text":"John"}])',
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": '[{"type":"text","text":"value1"},{"type":"text","text":"value2"}]',
        },
    )


class WhatsAppSendImageConfig(BaseModel):
    """Send an image message"""

    operation: Literal["send_image_message"] = Field(
        "send_image_message",
        json_schema_extra={
            "const": "send_image_message",
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Send Image Message",
        },
        title="Send Image Message",
    )
    to: str = _chat_picker_field("To (Phone or Chat)", field_name="to")
    image_url: Optional[str] = Field(
        None,
        title="Image URL",
        description="The image to send — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}). Use this OR media_id.",
        json_schema_extra={
            "placeholder": "https://example.com/image.jpg",
            "ui:widget": "media_upload",
            "ui:accept": "image/*",
        },
    )
    media_id: Optional[str] = Field(
        None,
        title="Media ID",
        description="Uploaded media ID from WhatsApp (use this OR image_url)",
        json_schema_extra={"placeholder": "Leave empty if using URL"},
    )
    caption: Optional[str] = Field(
        None,
        title="Caption (Optional)",
        description="Image caption",
        json_schema_extra={"ui:widget": "textarea", "placeholder": "Enter caption..."},
    )


class WhatsAppSendVideoConfig(BaseModel):
    """Send a video message"""

    operation: Literal["send_video_message"] = Field(
        "send_video_message",
        json_schema_extra={
            "const": "send_video_message",
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Send Video Message",
        },
        title="Send Video Message",
    )
    to: str = _chat_picker_field("To (Phone or Chat)", field_name="to")
    video_url: Optional[str] = Field(
        None,
        title="Video URL",
        description="The video to send — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}). Use this OR media_id.",
        json_schema_extra={
            "placeholder": "https://example.com/video.mp4",
            "ui:widget": "media_upload",
            "ui:accept": "video/*",
        },
    )
    media_id: Optional[str] = Field(
        None,
        title="Media ID",
        description="Uploaded media ID from WhatsApp (use this OR video_url)",
        json_schema_extra={"placeholder": "Leave empty if using URL"},
    )
    caption: Optional[str] = Field(
        None,
        title="Caption (Optional)",
        description="Video caption",
        json_schema_extra={"ui:widget": "textarea", "placeholder": "Enter caption..."},
    )


class WhatsAppSendDocumentConfig(BaseModel):
    """Send a document message"""

    operation: Literal["send_document_message"] = Field(
        "send_document_message",
        json_schema_extra={
            "const": "send_document_message",
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Send Document Message",
        },
        title="Send Document Message",
    )
    to: str = _chat_picker_field("To (Phone or Chat)", field_name="to")
    document_url: Optional[str] = Field(
        None,
        title="Document URL",
        description="The document to send — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}). Use this OR media_id.",
        json_schema_extra={
            "placeholder": "https://example.com/document.pdf",
            "ui:widget": "media_upload",
        },
    )
    media_id: Optional[str] = Field(
        None,
        title="Media ID",
        description="Uploaded media ID from WhatsApp (use this OR document_url)",
        json_schema_extra={"placeholder": "Leave empty if using URL"},
    )
    filename: Optional[str] = Field(
        None,
        title="Filename (Optional)",
        description="Document filename",
        json_schema_extra={"placeholder": "document.pdf"},
    )
    caption: Optional[str] = Field(
        None,
        title="Caption (Optional)",
        description="Document caption",
        json_schema_extra={"ui:widget": "textarea", "placeholder": "Enter caption..."},
    )


class WhatsAppSendAudioConfig(BaseModel):
    """Send an audio message"""

    operation: Literal["send_audio_message"] = Field(
        "send_audio_message",
        json_schema_extra={
            "const": "send_audio_message",
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Send Audio Message",
        },
        title="Send Audio Message",
    )
    to: str = _chat_picker_field("To (Phone or Chat)", field_name="to")
    audio_url: Optional[str] = Field(
        None,
        title="Audio URL",
        description="The audio to send — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}). Use this OR media_id.",
        json_schema_extra={
            "placeholder": "https://example.com/audio.mp3",
            "ui:widget": "media_upload",
            "ui:accept": "audio/*",
        },
    )
    media_id: Optional[str] = Field(
        None,
        title="Media ID",
        description="Uploaded media ID from WhatsApp (use this OR audio_url)",
        json_schema_extra={"placeholder": "Leave empty if using URL"},
    )


class WhatsAppSendLocationConfig(BaseModel):
    """Send a location message"""

    operation: Literal["send_location_message"] = Field(
        "send_location_message",
        json_schema_extra={
            "const": "send_location_message",
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Send Location Message",
        },
        title="Send Location Message",
    )
    to: str = _chat_picker_field("To (Phone or Chat)", field_name="to")
    latitude: str = Field(
        ...,
        title="Latitude",
        description="Location latitude (e.g., 37.7749)",
        json_schema_extra={"placeholder": "37.7749"},
    )
    longitude: str = Field(
        ...,
        title="Longitude",
        description="Location longitude (e.g., -122.4194)",
        json_schema_extra={"placeholder": "-122.4194"},
    )
    name: Optional[str] = Field(
        None,
        title="Name (Optional)",
        description="Location name",
        json_schema_extra={"placeholder": "My Office"},
    )
    address: Optional[str] = Field(
        None,
        title="Address (Optional)",
        description="Location address",
        json_schema_extra={"placeholder": "123 Main St, San Francisco, CA"},
    )


class WhatsAppSendContactConfig(BaseModel):
    """Send a contact card message"""

    operation: Literal["send_contact_card"] = Field(
        "send_contact_card",
        json_schema_extra={
            "const": "send_contact_card",
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Send Contact Card",
        },
        title="Send Contact Card",
    )
    to: str = _chat_picker_field("To (Phone or Chat)", field_name="to")
    contact_name: str = Field(
        ...,
        title="Contact Name",
        description="Contact's full name",
        json_schema_extra={"placeholder": "John Doe"},
    )
    contact_phone: str = Field(
        ...,
        title="Contact Phone",
        description="Contact's phone number",
        json_schema_extra={"placeholder": "+12025550100"},
    )
    contact_email: Optional[str] = Field(
        None,
        title="Contact Email (Optional)",
        description="Contact's email address",
        json_schema_extra={"placeholder": "john@example.com"},
    )


class WhatsAppSendButtonsConfig(BaseModel):
    """Send an interactive message with quick reply buttons"""

    operation: Literal["send_interactive_buttons"] = Field(
        "send_interactive_buttons",
        json_schema_extra={
            "const": "send_interactive_buttons",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Send Interactive Buttons",
        },
        title="Send Interactive Buttons",
    )
    to: str = Field(
        ...,
        title="To (Phone Number)",
        description="Recipient phone number in E.164 format",
        json_schema_extra={"placeholder": "+12025550100"},
    )
    body: str = Field(
        ...,
        title="Message Body",
        description="Main message text",
        json_schema_extra={"ui:widget": "textarea", "placeholder": "Choose an option:"},
    )
    buttons: str = Field(
        ...,
        title="Buttons (JSON Array)",
        description='JSON array of button objects (max 3): [{"type":"reply","reply":{"id":"btn1","title":"Button 1"}}]',
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": '[{"type":"reply","reply":{"id":"btn1","title":"Option 1"}},{"type":"reply","reply":{"id":"btn2","title":"Option 2"}}]',
        },
    )
    header: Optional[str] = Field(
        None,
        title="Header (Optional)",
        description="Optional header text",
        json_schema_extra={"placeholder": "Select your choice"},
    )
    footer: Optional[str] = Field(
        None,
        title="Footer (Optional)",
        description="Optional footer text",
        json_schema_extra={"placeholder": "Powered by MyBusiness"},
    )


class WhatsAppSendListConfig(BaseModel):
    """Send an interactive list message"""

    operation: Literal["send_interactive_list"] = Field(
        "send_interactive_list",
        json_schema_extra={
            "const": "send_interactive_list",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Send Interactive List",
        },
        title="Send Interactive List",
    )
    to: str = Field(
        ...,
        title="To (Phone Number)",
        description="Recipient phone number in E.164 format",
        json_schema_extra={"placeholder": "+12025550100"},
    )
    body: str = Field(
        ...,
        title="Message Body",
        description="Main message text",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "Please select from the list:",
        },
    )
    button_text: str = Field(
        "View Options",
        title="Button Text",
        description="Text shown on the list button (max 20 chars)",
        json_schema_extra={"placeholder": "View Options"},
    )
    sections: str = Field(
        ...,
        title="List Sections (JSON Array)",
        description='JSON array of sections with rows (max 10 total): [{"title":"Section 1","rows":[{"id":"row1","title":"Option 1","description":"Description"}]}]',
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": '[{"title":"Section 1","rows":[{"id":"opt1","title":"Option 1","description":"First option"}]}]',
        },
    )
    header: Optional[str] = Field(
        None,
        title="Header (Optional)",
        description="Optional header text",
        json_schema_extra={"placeholder": "Choose from menu"},
    )
    footer: Optional[str] = Field(
        None,
        title="Footer (Optional)",
        description="Optional footer text",
        json_schema_extra={"placeholder": "Select one option"},
    )


class WhatsAppSendReactionConfig(BaseModel):
    """Send a reaction (emoji) to a message"""

    operation: Literal["send_reaction_emoji"] = Field(
        "send_reaction_emoji",
        json_schema_extra={
            "const": "send_reaction_emoji",
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Send Reaction Emoji",
        },
        title="Send Reaction Emoji",
    )
    to: str = _chat_picker_field("To (Phone or Chat)", field_name="to")
    message_id: str = Field(
        ...,
        title="Message ID",
        description="The id of the message to react to: an incoming message's id, or the message_id a send returned (a wamid on the Cloud API)",
        json_schema_extra={"placeholder": "wamid.xxx... / message id"},
    )
    emoji: str = Field(
        ...,
        title="Emoji",
        description="Single emoji character (use empty string to remove reaction)",
        json_schema_extra={"placeholder": "👍"},
    )


class WhatsAppMarkReadConfig(BaseModel):
    """Mark a message as read"""

    operation: Literal["mark_message_read"] = Field(
        "mark_message_read",
        json_schema_extra={
            "const": "mark_message_read",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Mark Message Read",
        },
        title="Mark Message Read",
    )
    message_id: str = Field(
        ...,
        title="Message ID",
        description="WhatsApp message ID to mark as read (wamid)",
        json_schema_extra={"placeholder": "wamid.xxx..."},
    )


# ============================================================================
# Media Management Operations
# ============================================================================


class WhatsAppUploadMediaConfig(BaseModel):
    """Upload media to WhatsApp"""

    operation: Literal["upload_media"] = Field(
        "upload_media",
        json_schema_extra={
            "const": "upload_media",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Media",
            "x-is-trigger": False,
            "x-display-name": "Upload Media",
        },
        title="Upload Media",
    )
    media_url: str = Field(
        ...,
        title="Media URL",
        description="The media to upload — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}). Max 100MB.",
        json_schema_extra={
            "placeholder": "https://example.com/image.jpg",
            "ui:widget": "media_upload",
            "ui:accept": "image/*,video/*",
        },
    )
    media_type: str = Field(
        ...,
        title="Media Type",
        description="MIME type of the media (e.g., image/jpeg, video/mp4, application/pdf)",
        json_schema_extra={
            "enum": [
                "image/jpeg",
                "image/png",
                "video/mp4",
                "video/3gpp",
                "audio/aac",
                "audio/mp4",
                "audio/mpeg",
                "audio/amr",
                "audio/ogg",
                "application/pdf",
                "text/plain",
            ],
            "enumNames": [
                "Image (JPEG)",
                "Image (PNG)",
                "Video (MP4)",
                "Video (3GPP)",
                "Audio (AAC)",
                "Audio (MP4)",
                "Audio (MP3)",
                "Audio (AMR)",
                "Audio (OGG)",
                "Document (PDF)",
                "Document (TXT)",
            ],
        },
    )


class WhatsAppGetMediaUrlConfig(BaseModel):
    """Retrieve media URL from media ID"""

    operation: Literal["get_media_url"] = Field(
        "get_media_url",
        json_schema_extra={
            "const": "get_media_url",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Media",
            "x-is-trigger": False,
            "x-display-name": "Get Media Url",
        },
        title="Get Media Url",
    )
    media_id: str = Field(
        ...,
        title="Media ID",
        description="WhatsApp media ID",
        json_schema_extra={"placeholder": "1234567890123456"},
    )


class WhatsAppDownloadMediaConfig(BaseModel):
    """Download media file (returns binary data)"""

    operation: Literal["download_media"] = Field(
        "download_media",
        json_schema_extra={
            "const": "download_media",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Media",
            "x-is-trigger": False,
            "x-display-name": "Download Media",
        },
        title="Download Media",
    )
    media_url: str = Field(
        ...,
        title="Media URL",
        description="Media download URL from get_media_url operation (valid for 5 minutes)",
        json_schema_extra={"placeholder": "https://lookaside.fbsbx.com/..."},
    )


class WhatsAppDeleteMediaConfig(BaseModel):
    """Delete media from WhatsApp servers"""

    operation: Literal["delete_media"] = Field(
        "delete_media",
        json_schema_extra={
            "const": "delete_media",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Media",
            "x-is-trigger": False,
            "x-display-name": "Delete Media",
        },
        title="Delete Media",
    )
    media_id: str = Field(
        ...,
        title="Media ID",
        description="WhatsApp media ID to delete",
        json_schema_extra={"placeholder": "1234567890123456"},
    )


# ============================================================================
# Business Profile Operations
# ============================================================================


class WhatsAppGetBusinessProfileConfig(BaseModel):
    """Get business profile information"""

    operation: Literal["get_business_profile"] = Field(
        "get_business_profile",
        json_schema_extra={
            "const": "get_business_profile",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Profile",
            "x-is-trigger": False,
            "x-display-name": "Get Business Profile",
        },
        title="Get Business Profile",
    )
    fields: str = Field(
        "about,address,description,email,profile_picture_url,websites,vertical",
        title="Fields",
        description="Comma-separated list of fields to retrieve",
        json_schema_extra={"placeholder": "about,address,description,email"},
    )


class WhatsAppUpdateBusinessProfileConfig(BaseModel):
    """Update business profile information"""

    operation: Literal["update_business_profile"] = Field(
        "update_business_profile",
        json_schema_extra={
            "const": "update_business_profile",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Profile",
            "x-is-trigger": False,
            "x-display-name": "Update Business Profile",
        },
        title="Update Business Profile",
    )
    about: Optional[str] = Field(
        None,
        title="About (Optional)",
        description="Business description (max 139 chars)",
        json_schema_extra={"ui:widget": "textarea", "placeholder": "We are a..."},
    )
    address: Optional[str] = Field(
        None,
        title="Address (Optional)",
        description="Business address (max 256 chars)",
        json_schema_extra={"placeholder": "123 Main St, City"},
    )
    description: Optional[str] = Field(
        None,
        title="Description (Optional)",
        description="Extended business description (max 512 chars)",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "Full business description...",
        },
    )
    email: Optional[str] = Field(
        None,
        title="Email (Optional)",
        description="Business email address",
        json_schema_extra={"placeholder": "business@example.com"},
    )
    vertical: Optional[str] = Field(
        None,
        title="Vertical/Industry (Optional)",
        description="Business category",
        json_schema_extra={
            "enum": [
                "AUTO",
                "BEAUTY",
                "APPAREL",
                "EDU",
                "ENTERTAIN",
                "EVENT_PLAN",
                "FINANCE",
                "GROCERY",
                "GOVT",
                "HOTEL",
                "HEALTH",
                "NONPROFIT",
                "PROF_SERVICES",
                "RETAIL",
                "TRAVEL",
                "RESTAURANT",
                "NOT_A_BIZ",
            ],
            "enumNames": [
                "Automotive",
                "Beauty/Spa/Salon",
                "Apparel/Clothing",
                "Education",
                "Entertainment",
                "Event Planning",
                "Finance/Banking",
                "Grocery",
                "Government",
                "Hotel/Lodging",
                "Healthcare",
                "Nonprofit",
                "Professional Services",
                "Retail",
                "Travel/Transportation",
                "Restaurant",
                "Not a Business",
            ],
        },
    )
    websites: Optional[str] = Field(
        None,
        title="Websites (Optional)",
        description="Comma-separated list of website URLs",
        json_schema_extra={
            "placeholder": "https://example.com,https://shop.example.com"
        },
    )


# ============================================================================
# Phone Number Operations
# ============================================================================


class WhatsAppRegisterPhoneConfig(BaseModel):
    """Register a phone number with WhatsApp Business"""

    operation: Literal["register_phone_number"] = Field(
        "register_phone_number",
        json_schema_extra={
            "const": "register_phone_number",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Phone",
            "x-is-trigger": False,
            "x-display-name": "Register Phone Number",
        },
        title="Register Phone Number",
    )
    pin: str = Field(
        ...,
        title="6-Digit PIN",
        description="6-digit PIN received via SMS or voice call",
        json_schema_extra={"placeholder": "123456"},
    )


class WhatsAppRequestCodeConfig(BaseModel):
    """Request verification code via SMS or voice"""

    operation: Literal["request_verification_code"] = Field(
        "request_verification_code",
        json_schema_extra={
            "const": "request_verification_code",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Phone",
            "x-is-trigger": False,
            "x-display-name": "Request Verification Code",
        },
        title="Request Verification Code",
    )
    code_method: str = Field(
        "SMS",
        title="Code Method",
        description="Method to receive verification code",
        json_schema_extra={
            "enum": ["SMS", "VOICE"],
            "enumNames": ["SMS Text Message", "Voice Call"],
        },
    )
    language: str = Field(
        "en_US",
        title="Language",
        description="Language for the verification message",
        json_schema_extra={"placeholder": "en_US"},
    )


class WhatsAppGetPhoneInfoConfig(BaseModel):
    """Get phone number information"""

    operation: Literal["get_phone_number_info"] = Field(
        "get_phone_number_info",
        json_schema_extra={
            "const": "get_phone_number_info",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Phone",
            "x-is-trigger": False,
            "x-display-name": "Get Phone Number Info",
        },
        title="Get Phone Number Info",
    )
    fields: str = Field(
        "verified_name,code_verification_status,display_phone_number,quality_rating,messaging_limit_tier",
        title="Fields",
        description="Comma-separated list of fields to retrieve",
        json_schema_extra={"placeholder": "verified_name,quality_rating"},
    )


# ============================================================================
# Template Management Operations
# ============================================================================


class WhatsAppListTemplatesConfig(BaseModel):
    """List all message templates"""

    operation: Literal["list_message_templates"] = Field(
        "list_message_templates",
        json_schema_extra={
            "const": "list_message_templates",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Template",
            "x-is-trigger": False,
            "x-display-name": "List Message Templates",
        },
        title="List Message Templates",
    )
    limit: int = Field(
        50,
        title="Limit",
        description="Number of templates to retrieve (1-250)",
        ge=1,
        le=250,
    )
    status: Optional[str] = Field(
        None,
        title="Filter by Status (Optional)",
        description="Filter templates by approval status",
        json_schema_extra={
            "enum": ["", "APPROVED", "PENDING", "REJECTED"],
            "enumNames": ["All Statuses", "Approved", "Pending", "Rejected"],
        },
    )


class WhatsAppGetTemplateConfig(BaseModel):
    """Get a specific message template"""

    operation: Literal["get_message_template"] = Field(
        "get_message_template",
        json_schema_extra={
            "const": "get_message_template",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Template",
            "x-is-trigger": False,
            "x-display-name": "Get Message Template",
        },
        title="Get Message Template",
    )
    template_id: str = Field(
        ...,
        title="Template ID",
        description="WhatsApp template ID",
        json_schema_extra={"placeholder": "1234567890123456"},
    )


class WhatsAppCreateTemplateConfig(BaseModel):
    """Create a new message template"""

    operation: Literal["create_message_template"] = Field(
        "create_message_template",
        json_schema_extra={
            "const": "create_message_template",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Template",
            "x-is-trigger": False,
            "x-display-name": "Create Message Template",
        },
        title="Create Message Template",
    )
    name: str = Field(
        ...,
        title="Template Name",
        description="Template name (lowercase, underscores only)",
        json_schema_extra={"placeholder": "welcome_message"},
    )
    language: str = Field(
        "en_US",
        title="Language",
        description="Template language code",
        json_schema_extra={"placeholder": "en_US"},
    )
    category: str = Field(
        ...,
        title="Category",
        description="Template category",
        json_schema_extra={
            "enum": ["AUTHENTICATION", "MARKETING", "UTILITY"],
            "enumNames": [
                "Authentication (OTP, verification)",
                "Marketing (promotions, announcements)",
                "Utility (account updates, alerts)",
            ],
        },
    )
    body: str = Field(
        ...,
        title="Body Text",
        description="Template body text (use {{1}}, {{2}} for variables)",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "Hello {{1}}, your order {{2}} is ready!",
        },
    )
    header: Optional[str] = Field(
        None,
        title="Header (Optional)",
        description="Optional header text or media",
        json_schema_extra={"placeholder": "Welcome!"},
    )
    footer: Optional[str] = Field(
        None,
        title="Footer (Optional)",
        description="Optional footer text (max 60 chars)",
        json_schema_extra={"placeholder": "Reply STOP to unsubscribe"},
    )


class WhatsAppDeleteTemplateConfig(BaseModel):
    """Delete a message template"""

    operation: Literal["delete_message_template"] = Field(
        "delete_message_template",
        json_schema_extra={
            "const": "delete_message_template",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Template",
            "x-is-trigger": False,
            "x-display-name": "Delete Message Template",
        },
        title="Delete Message Template",
    )
    template_name: str = Field(
        ...,
        title="Template Name",
        description="Name of the template to delete",
        json_schema_extra={"placeholder": "hello_world"},
    )


# ============================================================================
# Commerce Operations
# ============================================================================


class WhatsAppSendCatalogConfig(BaseModel):
    """Send catalog message"""

    operation: Literal["send_catalog_message"] = Field(
        "send_catalog_message",
        json_schema_extra={
            "const": "send_catalog_message",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Send Catalog Message",
        },
        title="Send Catalog Message",
    )
    to: str = Field(
        ...,
        title="To (Phone Number)",
        description="Recipient phone number in E.164 format",
        json_schema_extra={"placeholder": "+12025550100"},
    )
    body: str = Field(
        ...,
        title="Message Body",
        description="Catalog message text",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "Check out our catalog!",
        },
    )
    thumbnail_product_id: Optional[str] = Field(
        None,
        title="Thumbnail Product ID (Optional)",
        description="Product ID to show as thumbnail",
        json_schema_extra={"placeholder": "product_123"},
    )


class WhatsAppSendProductConfig(BaseModel):
    """Send a single product message"""

    operation: Literal["send_product_message"] = Field(
        "send_product_message",
        json_schema_extra={
            "const": "send_product_message",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Send Product Message",
        },
        title="Send Product Message",
    )
    to: str = Field(
        ...,
        title="To (Phone Number)",
        description="Recipient phone number in E.164 format",
        json_schema_extra={"placeholder": "+12025550100"},
    )
    catalog_id: str = Field(
        ...,
        title="Catalog ID",
        description="Your Meta Commerce catalog ID",
        json_schema_extra={"placeholder": "1234567890"},
    )
    product_id: str = Field(
        ...,
        title="Product ID",
        description="Product ID from your catalog",
        json_schema_extra={"placeholder": "SKU_123"},
    )
    body: Optional[str] = Field(
        None,
        title="Message Body (Optional)",
        description="Optional message text",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "Check out this product!",
        },
    )


class WhatsAppSendMultiProductConfig(BaseModel):
    """Send multiple products message"""

    operation: Literal["send_multi_product_message"] = Field(
        "send_multi_product_message",
        json_schema_extra={
            "const": "send_multi_product_message",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Send Multi Product Message",
        },
        title="Send Multi Product Message",
    )
    to: str = Field(
        ...,
        title="To (Phone Number)",
        description="Recipient phone number in E.164 format",
        json_schema_extra={"placeholder": "+12025550100"},
    )
    catalog_id: str = Field(
        ...,
        title="Catalog ID",
        description="Your Meta Commerce catalog ID",
        json_schema_extra={"placeholder": "1234567890"},
    )
    product_ids: str = Field(
        ...,
        title="Product IDs (JSON Array)",
        description='JSON array of product IDs (max 30): ["SKU_1", "SKU_2", "SKU_3"]',
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": '["SKU_1", "SKU_2", "SKU_3"]',
        },
    )
    header: str = Field(
        "Our Products",
        title="Header Text",
        description="Section header text",
        json_schema_extra={"placeholder": "Our Products"},
    )
    body: str = Field(
        ...,
        title="Message Body",
        description="Message text",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "Browse our collection!",
        },
    )


# ============================================================================
# Account Management Operations
# ============================================================================


class WhatsAppGetAccountInfoConfig(BaseModel):
    """Get WhatsApp Business Account information"""

    operation: Literal["get_account_info"] = Field(
        "get_account_info",
        json_schema_extra={
            "const": "get_account_info",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Get Account Info",
        },
        title="Get Account Info",
    )
    fields: str = Field(
        "id,name,message_template_namespace,timezone_id,currency,account_review_status",
        title="Fields",
        description="Comma-separated list of fields to retrieve",
        json_schema_extra={"placeholder": "id,name,timezone_id"},
    )


class WhatsAppListPhoneNumbersConfig(BaseModel):
    """List all phone numbers in the account"""

    operation: Literal["list_account_phone_numbers"] = Field(
        "list_account_phone_numbers",
        json_schema_extra={
            "const": "list_account_phone_numbers",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": "Phone",
            "x-is-trigger": False,
            "x-display-name": "List Account Phone Numbers",
        },
        title="List Account Phone Numbers",
    )
    limit: int = Field(
        50,
        title="Limit",
        description="Number of phone numbers to retrieve",
        ge=1,
        le=100,
    )


# ============================================================================
# QR-supported Read Operations
# ============================================================================


class WhatsAppGetChatsConfig(BaseModel):
    """List recent WhatsApp conversations"""

    operation: Literal["list_recent_chats"] = Field(
        "list_recent_chats",
        json_schema_extra={
            "const": "list_recent_chats",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_qr"],
            "x-category": "Chats",
            "x-is-trigger": False,
            "x-display-name": "List Recent Chats",
            "x-keywords": ["conversations", "inbox", "chat list"],
        },
        title="List Recent Chats",
    )
    limit: int = Field(
        50,
        title="Limit",
        description="Maximum number of chats to return",
        ge=1,
        le=500,
    )
    unread_only: str = Field(
        "false",
        title="Unread Only",
        description="Only return chats marked unread (best-effort)",
        json_schema_extra={
            "enum": ["false", "true"],
            "enumNames": ["No (all chats)", "Yes (unread only)"],
            "x-enum-searchable": True,
        },
    )


class WhatsAppGetChatMessagesConfig(BaseModel):
    """Read message history from a chat (QR credentials)"""

    operation: Literal["get_chat_messages"] = Field(
        "get_chat_messages",
        json_schema_extra={
            "const": "get_chat_messages",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_qr"],
            "x-category": "Chats",
            "x-is-trigger": False,
            "x-display-name": "Get Chat Messages",
            "x-keywords": ["read messages", "chat history", "conversation history"],
        },
        title="Get Chat Messages",
    )
    chat_id: str = _chat_picker_field(
        "Chat",
        "Chat to read messages from (pick from your WhatsApp chats)",
        field_name="chat_id",
    )
    limit: int = Field(
        50,
        title="Limit",
        description="Number of messages to return, newest first",
        ge=1,
        le=100,
    )
    before: Optional[str] = Field(
        None,
        title="Before (Cursor)",
        description="Pagination cursor from a previous page's next_before — fetches the next (older) page",
        json_schema_extra={"placeholder": "Leave empty for the newest messages"},
    )


class WhatsAppReadRecentMessagesConfig(BaseModel):
    """Read every chat's messages from the last few hours in one call, compactly: per chat, one line per message ("<UTC time> <sender>: <text>", your own as You, media as [image] or [voice note] with its caption), oldest first, with no ids or media data. The cheap read for a digest or summary across chats (QR credentials)"""

    operation: Literal["read_recent_messages"] = Field(
        "read_recent_messages",
        json_schema_extra={
            "const": "read_recent_messages",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_qr"],
            "x-category": "Chats",
            "x-is-trigger": False,
            "x-display-name": "Read Recent Messages",
            "x-keywords": ["digest", "summary", "today's messages", "all chats", "group messages",
                           "messages since"],
        },
        title="Read Recent Messages",
    )
    hours: int = Field(24, title="Hours", description="How far back to read, in hours", ge=1, le=168)
    chats: Literal["all", "groups", "direct"] = Field(
        "all",
        title="Chats",
        description="Which chats to read: all, group chats only, or one-to-one chats only",
        json_schema_extra={"enumNames": ["All chats", "Group chats", "Direct chats"], "x-enum-searchable": True},
    )
    max_chats: int = Field(
        100, title="Max Chats", description="Most chats to read, the most recently active first", ge=1, le=200
    )
    per_chat_limit: int = Field(
        100, title="Messages per Chat", description="Most messages to read from one chat, the newest kept", ge=1,
        le=500,
    )


class WhatsAppListContactsConfig(BaseModel):
    """List the connected account's WhatsApp contacts (QR credentials)"""

    operation: Literal["list_contacts"] = Field(
        "list_contacts",
        json_schema_extra={
            "const": "list_contacts",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_qr"],
            "x-category": "Chats",
            "x-is-trigger": False,
            "x-display-name": "List Contacts",
            "x-keywords": ["address book", "phone numbers", "people"],
        },
        title="List Contacts",
    )
    limit: int = Field(
        200,
        title="Limit",
        description="Maximum number of contacts to return",
        ge=1,
        le=1000,
    )


class WhatsAppEditMessageConfig(BaseModel):
    """Edit a previously sent message (QR credentials)"""

    operation: Literal["edit_message"] = Field(
        "edit_message",
        json_schema_extra={
            "const": "edit_message",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_qr"],
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Edit Message",
        },
        title="Edit Message",
    )
    chat_id: str = _chat_picker_field(
        "Chat",
        "Chat containing the message to edit",
        field_name="chat_id",
    )
    message_id: str = Field(
        ...,
        title="Message ID",
        description="The message_id a send operation returned for the message (or its id from Get Chat Messages)",
        json_schema_extra={"placeholder": "message id"},
    )
    body: str = Field(
        ...,
        title="New Text",
        description="Replacement message text",
        json_schema_extra={"ui:widget": "textarea"},
    )


class WhatsAppMarkChatReadConfig(BaseModel):
    """Mark a chat's messages as read (QR credentials)"""

    operation: Literal["mark_chat_read"] = Field(
        "mark_chat_read",
        json_schema_extra={
            "const": "mark_chat_read",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_qr"],
            "x-category": "Chats",
            "x-is-trigger": False,
            "x-display-name": "Mark Chat Read",
        },
        title="Mark Chat Read",
    )
    chat_id: str = _chat_picker_field(
        "Chat",
        "Chat to mark as read",
        field_name="chat_id",
    )


class WhatsAppGetProfileConfig(BaseModel):
    """Get the connected WhatsApp account profile info"""

    operation: Literal["get_account_profile"] = Field(
        "get_account_profile",
        json_schema_extra={
            "const": "get_account_profile",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_qr"],
            "x-category": "Profile",
            "x-is-trigger": False,
            "x-display-name": "Get Account Profile",
        },
        title="Get Account Profile",
    )


# ============================================================================
# Group Operations (QR credentials: WAHooks' group routes, utils.wahooks_groups)
# ============================================================================

GROUP_RESOURCE = "whatsapp_group"
NOCLICK_LINE_IN_GROUP = (
    "Not changed: one of those numbers is NoClick's own line, where the owner texts their NoClick assistant. It isn't "
    "one of their contacts and never goes in a group: leave it out and name the people themselves."
)
_PARTICIPANTS_DESC = (
    "People, each a phone number in international form (e.g. +12025550100) or a WhatsApp id (…@c.us or …@lid, "
    "as a message or get_group names them); at most 256"
)


def _group_op(name: str, display: str, keywords: List[str], **extra: Any) -> Any:
    return Field(
        name,
        json_schema_extra={
            "const": name,
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_qr"],
            "x-category": "Groups",
            "x-is-trigger": False,
            "x-display-name": display,
            "x-keywords": keywords,
            **extra,
        },
        title=display,
    )


def _group_picker_field(description: str) -> Any:
    """A group of the account's (``load_field_options`` lists its group chats)."""
    return Field(
        ...,
        title="Group",
        description=description,
        json_schema_extra={
            "placeholder": "120000000000000001@g.us",
            "x-dynamic-options": {**CHAT_PICKER_OPTIONS, "placeholder": "Select a group...",
                                  "custom_placeholder": "Or enter a group id (…@g.us)", "field_name": "group_id"},
            "x-resource-type": GROUP_RESOURCE,
        },
    )


class _GroupPeopleConfig(BaseModel):
    @field_validator("participants", mode="before", check_fields=False)
    @classmethod
    def _listed(cls, value: Any) -> Any:
        # A template or a model may name them as one comma- or line-separated string.
        if isinstance(value, str):
            return [p for p in (s.strip() for s in value.replace("\n", ",").split(",")) if p]
        return value


class WhatsAppGetGroupConfig(BaseModel):
    """Read a WhatsApp group: its name and description, how many members it has and who they are (each one's name, number where WhatsApp shows it, id, and admin or member), and whether you're one of its admins (QR credentials)"""

    operation: Literal["get_group"] = _group_op("get_group", "Get Group",
                                                ["group members", "who is in the group", "participants", "admins"])
    group_id: str = _group_picker_field("The group, by its id (…@g.us)")
    refresh: str = Field(
        "false",
        title="Fresh Read",
        description="Read it from WhatsApp now rather than from the copy kept for up to a minute",
        json_schema_extra={"enum": ["false", "true"], "enumNames": ["No", "Yes"], "x-enum-searchable": True},
    )


class WhatsAppCreateGroupConfig(_GroupPeopleConfig):
    """Create a WhatsApp group with you as its admin, adding the people named. Answers the new group's id and, per person, who was added and who wasn't and why (someone whose privacy settings let only their contacts add them gets the invite link instead) (QR credentials)"""

    operation: Literal["create_group"] = _group_op(
        "create_group", "Create Group", ["new group", "start a group", "group chat"],
        **{"x-creates-resource": True, "x-resource-type": GROUP_RESOURCE, "x-resource-id-path": "data.group_id"})
    name: str = Field(..., min_length=1, max_length=100, title="Group Name", description="The group's name")
    participants: List[str] = Field(default_factory=list, title="People", description=_PARTICIPANTS_DESC)


class WhatsAppRenameGroupConfig(BaseModel):
    """Rename a WhatsApp group (an admin's, when the group is locked to admins) (QR credentials)"""

    operation: Literal["rename_group"] = _group_op("rename_group", "Rename Group",
                                                   ["group name", "change group subject"])
    group_id: str = _group_picker_field("The group to rename, by its id (…@g.us)")
    name: str = Field(..., min_length=1, max_length=100, title="New Name", description="The group's new name")


class WhatsAppAddGroupParticipantsConfig(_GroupPeopleConfig):
    """Add people to a WhatsApp group you're an admin of. Answers, per person, whether they were added, were already in it, or weren't added and why: someone whose privacy settings let only their contacts add them, or who left recently, can join by the group's invite link instead; a number not on WhatsApp can't (QR credentials)"""

    operation: Literal["add_group_participants"] = _group_op(
        "add_group_participants", "Add Group Participants", ["add members", "add people to group", "invite"])
    group_id: str = _group_picker_field("The group to add them to, by its id (…@g.us)")
    participants: List[str] = Field(..., min_length=1, title="People", description=_PARTICIPANTS_DESC)


class WhatsAppRemoveGroupParticipantsConfig(_GroupPeopleConfig):
    """Remove people from a WhatsApp group you're an admin of. Answers, per person, whether they were removed or weren't in it (QR credentials)"""

    operation: Literal["remove_group_participants"] = _group_op(
        "remove_group_participants", "Remove Group Participants", ["kick", "remove members", "remove from group"])
    group_id: str = _group_picker_field("The group to remove them from, by its id (…@g.us)")
    participants: List[str] = Field(..., min_length=1, title="People", description=_PARTICIPANTS_DESC)


class WhatsAppLeaveGroupConfig(BaseModel):
    """Leave a WhatsApp group: the account stops getting its messages and can't rejoin without an invite. A group whose last member leaves is gone (QR credentials)"""

    operation: Literal["leave_group"] = _group_op("leave_group", "Leave Group", ["exit group", "quit group"])
    group_id: str = _group_picker_field("The group to leave, by its id (…@g.us)")


class WhatsAppGetGroupInviteLinkConfig(BaseModel):
    """Get a WhatsApp group's invite link, which lets anyone who has it join (an admin's) (QR credentials)"""

    operation: Literal["get_group_invite_link"] = _group_op(
        "get_group_invite_link", "Get Group Invite Link", ["join link", "invite link", "share group"])
    group_id: str = _group_picker_field("The group, by its id (…@g.us)")


class WhatsAppRevokeGroupInviteLinkConfig(BaseModel):
    """Revoke a WhatsApp group's invite link so it no longer lets anyone join, and get its new one (an admin's) (QR credentials)"""

    operation: Literal["revoke_group_invite_link"] = _group_op(
        "revoke_group_invite_link", "Revoke Group Invite Link", ["reset invite link", "new invite link"])
    group_id: str = _group_picker_field("The group, by its id (…@g.us)")


# ============================================================================
# Webhook Operations (receive-only via webhook trigger)
# ============================================================================


class WhatsAppReceiveStatusConfig(BaseModel):
    """Receive message status updates via webhook"""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["receive_status_update"] = Field(
        "receive_status_update",
        json_schema_extra={
            "const": "receive_status_update",
            "ui:hidden": True,
            "x-supported-credential-types": ["whatsapp_access_token"],
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "Receive Status Update",
        },
        title="Receive Status Update",
    )
    webhook_id: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="Configure this URL in Meta Developer Console to receive status updates (sent, delivered, read, failed)",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:copyable": True,
            "ui:loadValue": True,
        },
    )
    verify_token: Optional[str] = Field(
        default=None,
        title="Verify Token (Optional)",
        description="Token to verify webhook subscription",
        json_schema_extra={"ui:widget": "password"},
    )


# ============================================================================
# Discriminated Union - ALL Operations
# ============================================================================

WhatsAppConfig = Annotated[
    Union[
        # Messaging (12 operations)
        WhatsAppSendTextConfig,
        WhatsAppSendTemplateConfig,
        WhatsAppSendImageConfig,
        WhatsAppSendVideoConfig,
        WhatsAppSendDocumentConfig,
        WhatsAppSendAudioConfig,
        WhatsAppSendLocationConfig,
        WhatsAppSendContactConfig,
        WhatsAppSendButtonsConfig,
        WhatsAppSendListConfig,
        WhatsAppSendReactionConfig,
        WhatsAppMarkReadConfig,
        # Media Management (4 operations)
        WhatsAppUploadMediaConfig,
        WhatsAppGetMediaUrlConfig,
        WhatsAppDownloadMediaConfig,
        WhatsAppDeleteMediaConfig,
        # Business Profile (2 operations)
        WhatsAppGetBusinessProfileConfig,
        WhatsAppUpdateBusinessProfileConfig,
        # Phone Number (3 operations)
        WhatsAppRegisterPhoneConfig,
        WhatsAppRequestCodeConfig,
        WhatsAppGetPhoneInfoConfig,
        # Templates (4 operations)
        WhatsAppListTemplatesConfig,
        WhatsAppGetTemplateConfig,
        WhatsAppCreateTemplateConfig,
        WhatsAppDeleteTemplateConfig,
        # Commerce (3 operations)
        WhatsAppSendCatalogConfig,
        WhatsAppSendProductConfig,
        WhatsAppSendMultiProductConfig,
        # Account (2 operations)
        WhatsAppGetAccountInfoConfig,
        WhatsAppListPhoneNumbersConfig,
        # QR Operations (7 operations)
        WhatsAppGetChatsConfig,
        WhatsAppGetChatMessagesConfig,
        WhatsAppReadRecentMessagesConfig,
        WhatsAppListContactsConfig,
        WhatsAppEditMessageConfig,
        WhatsAppMarkChatReadConfig,
        WhatsAppGetProfileConfig,
        # Groups (8 operations, QR)
        WhatsAppGetGroupConfig,
        WhatsAppCreateGroupConfig,
        WhatsAppRenameGroupConfig,
        WhatsAppAddGroupParticipantsConfig,
        WhatsAppRemoveGroupParticipantsConfig,
        WhatsAppLeaveGroupConfig,
        WhatsAppGetGroupInviteLinkConfig,
        WhatsAppRevokeGroupInviteLinkConfig,
        # Webhooks (2 operations)
        WhatsAppReceiveMessageConfig,
        WhatsAppReceiveStatusConfig,
    ],
    Discriminator("operation"),
]


class WhatsAppNodeConfig(NodeConfig[WhatsAppConfig, WhatsAppCredential]):
    """Full configuration for WhatsApp node including credentials"""

    pass


# ============================================================================
# Node Implementation
# ============================================================================

# Events our per-node WAHooks webhook subscribes to: message deliveries fire
# the workflow; session.status powers dead-session detection (credential
# marked + owner alerted when the phone link dies, instead of leaving the
# trigger falsely marked as healthy).
WAHOOKS_WEBHOOK_EVENTS = ["message", "session.status"]
# WAHA's "message" carries only what others send; the account's own messages arrive on "message.any" alone (with
# every other message again), so a trigger subscribes to it only to hear its owner's own chat.
SELF_CHAT_EVENT = "message.any"
_MESSAGE_EVENTS = ("message", SELF_CHAT_EVENT)
# What a group's conversation is called: a delivery names who wrote, never the group.
GROUP_CHAT_TITLE = "WhatsApp group"


def wahooks_webhook_events(config: Optional[Dict[str, Any]]) -> List[str]:
    """The WAHooks events a receive_message trigger with ``config`` subscribes to."""
    own_chat = (config or {}).get("include_self_chat") == "true"
    return [*WAHOOKS_WEBHOOK_EVENTS, *([SELF_CHAT_EVENT] if own_chat else [])]


def _wahooks_ensure_webhook(api_key: str, connection_id: str, webhook_url: str, *,
                            events: List[str] = WAHOOKS_WEBHOOK_EVENTS) -> Optional[str]:
    """Sync (thread-pool) create-or-upgrade of our WAHooks webhook on a
    connection: registers the URL if absent and upgrades a pre-existing
    config to include every one of ``events``. Returns the secret WAHooks
    signs its deliveries with, for the webhooks row to verify them by."""
    from wahooks import WAHooks

    from utils.wahooks_connections import signing_secret

    with WAHooks(api_key=api_key) as client:
        ours = [
            w for w in client.list_webhooks(connection_id)
            if w.get("url") == webhook_url
        ]
        if not ours:
            created = client.create_webhook(
                connection_id, url=webhook_url, events=list(events)
            )
            logger.info(f"[WhatsAppNode] Created WAHooks webhook on connection {connection_id}")
            return signing_secret([created], webhook_url)
        for w in ours:
            have = set(w.get("events") or [])
            if not set(events) <= have:
                client.update_webhook(
                    w["id"], events=sorted(have | set(events))
                )
        return signing_secret(ours, webhook_url)


def _wahooks_webhooks(api_key: str, connection_id: str) -> List[Dict[str, Any]]:
    """Sync (thread-pool) read of a connection's WAHooks webhooks with the platform key."""
    from wahooks import WAHooks

    with WAHooks(api_key=api_key) as client:
        return list(client.list_webhooks(connection_id))


def _wahooks_drop_webhooks(api_key: str, connection_id: str, webhook_url: str) -> int:
    """Sync (thread-pool) removal of every WAHooks webhook on a connection that
    delivers to ``webhook_url``. Needs only the platform key, never the
    credential. A connection or webhook WAHooks no longer knows is already
    gone; any other failure raises. Returns how many were removed."""
    from wahooks import WAHooks

    from utils.wahooks_connections import drop_webhook_configs

    with WAHooks(api_key=api_key) as client:
        return drop_webhook_configs(client, connection_id, webhook_url)


class WhatsAppNode(WorkflowNode):
    """
    WhatsApp Business Cloud API automation node.

    Provides 32 operations across messaging, media, profiles, templates, and commerce.
    Uses Meta access tokens for authentication.
    """

    # The chat list comes from the linked phone, so it is both recognisable and
    # the only thing that proves the QR session is actually still alive.
    connection_evidence = ConnectionEvidence(
        field="chat_id",
        noun="chats",
    )

    # A QR session's incoming messages are registered with WAHooks by
    # load_field_value; the Cloud API's go to a URL set in Meta's console.
    self_registering_triggers = {"receive_message": ("whatsapp_qr",)}

    # WAHooks signs each delivery with its webhook's own secret, which the
    # webhooks row keeps (never the graph: a fork or template would carry it),
    # one per connection: a URL can be registered on several, each its own.
    webhook_secret_on_row = True

    @classmethod
    def webhook_signer(cls, payload):
        """The WAHooks connection a delivery comes from, whose webhook's secret signs it."""
        return str(payload.get("connectionId") or "").strip() or None

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        """WAHooks' ``X-WAHooks-Signature``: ``sha256=`` HMAC-SHA256 of
        ``{X-WAHooks-Timestamp}.{body}`` with the webhook's signing secret, the
        timestamp within 5 minutes. A connection NoClick holds no secret for
        (a registration from before it kept them, a link it never recorded) has
        none to check: its deliveries run unverified, which is never an owner's
        own note (``_owner_note``)."""
        secret = (config or {}).get("signing_secret")
        if not secret:
            return True
        return verify_wahooks(
            body, headers.get("x-wahooks-timestamp", ""), headers.get("x-wahooks-signature", ""), secret
        )

    @classmethod
    def registration_fingerprint_fields(cls, config):
        # Hearing the owner's own chat takes another WAHooks event. Nothing when off, so every registration made
        # before the setting keeps its fingerprint.
        return {"include_self_chat": "true"} if (config or {}).get("include_self_chat") == "true" else {}

    edit_examples = [
        "Send order confirmation message using approved template",
        "Reply to customer inquiry with shipping tracking info",
        "Send invoice PDF as media attachment to customer",
        "Create interactive menu for product selection",
        "List templates and send personalized promotional message",
        "Update business profile with hours and contact info",
        "Mark messages as read after handling customer support",
        "Read recent messages from a chat and summarize them",
    ]

    @classmethod
    def get_config_model(cls):
        return WhatsAppNodeConfig

    @classmethod
    async def observe_registration(
        cls, pool, *, webhook_url: str, credential_id: Optional[str], config: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """What WAHooks holds for the trigger, read with NoClick's own key and
        the connection the credential's metadata names (nothing decrypted): the
        row's fields (``signing_secrets``: that connection's secret, by its id)
        when the connection delivers to ``webhook_url`` with every event the
        loader asks for, False when it doesn't, None when it can't say."""
        from utils.wahooks_connections import get_wahooks_api_key

        api_key = get_wahooks_api_key()
        if not (api_key and credential_id):
            return None
        async with pool.acquire() as conn:
            connection_id = await conn.fetchval(
                "SELECT metadata->>'connection_id' FROM credentials WHERE id::text = $1", str(credential_id))
        if not connection_id:
            return None
        try:
            hooks = await asyncio.to_thread(_wahooks_webhooks, api_key, connection_id)
        except Exception as e:
            logger.warning(f"[WhatsAppNode] Couldn't read connection {connection_id}'s webhooks: {e}")
            return None
        ours = [w for w in hooks if w.get("url") == webhook_url]
        wanted = set(wahooks_webhook_events(config))
        if ours and all(wanted <= set(w.get("events") or []) for w in ours):
            from utils.wahooks_connections import signing_secret

            secret = signing_secret(ours, webhook_url)
            return {"external_webhook_id": connection_id,
                    **({"signing_secrets": {connection_id: secret}} if secret else {})}
        return False

    @classmethod
    def resolve_agent_event(cls, output: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Inbound WhatsApp message → the agent's user turn text + the sender
        chat id as conversation key (one conversation per chat).

        The chat id is surfaced VERBATIM with its @c.us/@lid/@s.whatsapp.net
        suffix so a send tool can pass it straight back as ``to`` — to_chat_id()
        passes @-suffixed ids through untouched. Without this the agent gets the
        raw WAHooks JSON, hand-builds an E.164 number, and mis-addresses the
        reply to a non-existent account (WAHA returns PENDING, never delivers).
        Non-message envelopes fall back to the base raw-JSON default. The
        owner writing in their own "Message yourself" chat is ``from_owner``;
        a direct chat's writer is named by number (``from_number``), which a
        platform knowing its owner's number takes as theirs. Both are what the
        delivery says, so only a verified one carries either (``_verified``).
        """
        # WAHooks 'message' envelope (QR-linked accounts) — the channel case.
        if output.get("event") in _MESSAGE_EVENTS and isinstance(output.get("payload"), dict):
            p = output["payload"]
            chat_id, participant = cls._message_chat(p)  # participant: the writer, in a group
            if not chat_id:
                return super().resolve_agent_event(output)
            owner = cls._owner_note(output)
            me = output.get("me") if isinstance(output.get("me"), dict) else {}
            # Their own chat is mostly named by their @lid; their number reaches it too (a send to it lands there),
            # and keeps it one conversation whichever of their devices they write from.
            if owner and (number := cls._account_part(me.get("id"))):
                chat_id = f"{number}@c.us"
            from nodes.core.agent_events import media_entry
            from nodes.core.media_digest import media_kind, media_placeholder

            media = p.get("media") if isinstance(p.get("media"), dict) else {}
            has_media = bool(p.get("hasMedia") or media)
            kind = media_kind(media.get("mimetype"), media.get("filename")) if media else None
            voice = kind == "audio" and cls._is_voice_note(p, media)
            # For media messages, body is the caption (may be empty).
            body = p.get("body") or p.get("caption") or (
                media_placeholder(kind, voice=voice, filename=media.get("filename"))
                if has_media else "[non-text message]"
            )
            # A @lid chat id hides the number, but WAHooks still names the
            # writer (senderPhone + pushName). Without them in the turn a
            # "supervisor = +1 868 …" rule can never match — 12 real approvals
            # got the customer greeting (2026-09-22). Identity only: the reply
            # address stays the chat id.
            sender_phone = str(p.get("senderPhone") or "").strip().lstrip("+")
            push_name = str((p.get("_data") or {}).get("pushName") or p.get("notifyName") or "").strip()
            sender_id = participant or chat_id
            phone_shown = not owner and bool(sender_phone) and sender_phone != sender_id.split("@", 1)[0]
            identity = [push_name] if push_name else []
            if phone_shown:
                identity.append(f"phone +{sender_phone}")
            group = chat_id.endswith("@g.us")
            seen_chat, seen_sender = cls._seen_profiles(output)
            group_name = cls._group_name(output) if group else None
            header = f"WhatsApp message from {chat_id}"
            if owner:
                header = ("WhatsApp message from the account's owner, to you, in their own \"Message yourself\" "
                          f"chat {chat_id}")
            elif group:
                named = f'the group "{group_name}"' if group_name else "a group"
                header = f"WhatsApp message in {named} ({chat_id})"
                if participant and participant != chat_id:
                    header += f", sent by {participant}"
                if identity:
                    header += f" ({', '.join(identity)})"
            elif participant and participant != chat_id:
                header += f" (sent by {', '.join([participant, *identity])})"
            elif identity:
                header += f" ({', '.join(identity)})"
            own = cls._own_ids(output)
            if cls._mentions_any(p, own):
                header += ", mentioning you"
            quoted = cls._quoted_line(p, own)
            if quoted:
                body = f"{quoted}\n{body}"
            media_note = ""
            entries = []
            if has_media:
                desc = ", ".join(
                    str(x) for x in (media.get("mimetype"), media.get("filename")) if x
                )
                if media.get("too_large") and media.get("max_bytes"):
                    size = f"{_megabytes(media['size'])}; " if media.get("size") else ""
                    media_note = (
                        f"\n[The attachment ({desc or 'unknown type'}) arrived but is too large to use "
                        f"({size}the limit is {_megabytes(media['max_bytes'])}), so you cannot "
                        f"see its content. Tell the sender and ask them to send a smaller version.]"
                    )
                elif media.get("rehosted") and media.get("url"):
                    inbox = media.get("inbox") if isinstance(media.get("inbox"), dict) else {}
                    media_note = f"\nAttached media ({desc or 'unknown type'}): {media['url']}\n"
                    if inbox.get("path"):
                        label = "voice note" if inbox.get("kind") == "voice" else inbox.get("kind") or "file"
                        media_note += (
                            f"{label}: {inbox['path']} (saved in your workspace: open, edit or convert it there; "
                            f"the link is public and unguessable, for sending it on unchanged)"
                        )
                    else:
                        media_note += (
                            "Download that URL (e.g. curl -o) to view or process the file — "
                            "it is a public, unguessable link."
                        )
                        if inbox.get("error"):
                            media_note += f"\n[It wasn't saved in your workspace: {inbox['error']}.]"
                    entries.append(media_entry(
                        url=media["url"],
                        mime_type=media.get("mimetype"),
                        filename=media.get("filename"),
                        size_bytes=media.get("size"),
                        duration_s=cls._audio_seconds(p),
                        voice=voice,
                        resource_id=media.get("resource_id"),
                        record=media,
                    ))
                else:
                    # Not rehosted: the provider URL is platform-authed and
                    # useless to the run — say so instead of dangling it.
                    media_note = (
                        "\n[The attached media could not be retrieved — ask the sender to "
                        "describe it or resend it (smaller, if it is a large file) if its content matters.]"
                    )
            identity_note = (
                " The phone number in the header identifies the sender; it is not the reply address."
                if phone_shown else ""
            )
            message_id = p.get("id") if isinstance(p.get("id"), str) else ""
            # Reacting to a message or quoting it takes its id; without it the agent had to page the chat first.
            id_note = (f" This message's id is {message_id}: pass it as message_id to react to it, or as "
                       f"reply_to_message_id to quote it." if message_id else "")
            # Who's in it, as its delivery read them (``_stamp_profiles``), or that they're unknown.
            group_note = (" Everyone in the group reads what you send to it." + members_note(output.get("group"))
                          if group else "")
            text = (
                f"{header}:\n{body}{media_note}\n\n"
                f"To reply, call a send tool with to={chat_id} "
                f"(pass this chat id exactly — do not convert it to a phone number).{group_note}{identity_note}"
                f"{id_note}"
            )
            # Who wrote it, by number when WhatsApp gives no name. A group's conversation is the group's, never its
            # first writer's.
            title = push_name or cls._number_label(sender_id, sender_phone)
            # Never a group's: there the reply reaches everyone in it.
            number = (None if owner or participant or group or not cls._verified(output)
                      else cls._sender_number(output))
            # For the pages that draw the chat; the model's text never carries them.
            chat = {"key": chat_id, "name": group_name if group else title, "avatar": seen_chat.get("avatar_url"),
                    "kind": "self" if owner else "group" if group else "direct"}
            sender = {"id": sender_id, "name": push_name or None, "avatar": seen_sender.get("avatar_url")}
            return {"text": text, "conversation_key": chat_id, "title": title, "media": entries,
                    "chat": chat, "sender": sender,
                    **({"conversation_title": group_name or GROUP_CHAT_TITLE} if group else {}),
                    **({"from_owner": True} if owner else {}), **({"from_number": number} if number else {})}

        # Meta Cloud API envelope — bare E.164 sender numbers.
        if output.get("object") == "whatsapp_business_account":
            try:
                value = output["entry"][0]["changes"][0]["value"]
                msg = (value.get("messages") or [])[0]
            except (KeyError, IndexError, TypeError):
                return super().resolve_agent_event(output)
            sender = str(msg.get("from") or "").strip()
            if not sender:
                return super().resolve_agent_event(output)
            body = (msg.get("text") or {}).get("body") or "[non-text message]"
            text = (
                f"WhatsApp message from {sender}:\n{body}\n\n"
                f"To reply, call a send tool with to={sender}."
            )
            profile = (value.get("contacts") or [{}])[0].get("profile") or {}
            return {"text": text, "conversation_key": sender, "title": profile.get("name") or sender}

        return super().resolve_agent_event(output)

    @classmethod
    def summarize_agent_event(cls, output: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """A WAHooks message as it looked on WhatsApp: who wrote (their profile name, their number where WhatsApp
        names it), their words, a voice note or file with its transcript once the turn digested it, and the message
        it quoted. A group's own name isn't in its messages: it's the one kept for it (``profiles``), else unnamed;
        the chat's and the writer's pictures likewise."""
        if not (output.get("event") in _MESSAGE_EVENTS and isinstance(output.get("payload"), dict)):
            return super().summarize_agent_event(output)
        from nodes.core.agent_events import event_summary
        from nodes.core.media_digest import media_kind

        p = output["payload"]
        chat, participant = cls._message_chat(p)
        group = chat.endswith("@g.us")
        seen_chat, seen_sender = cls._seen_profiles(output)
        name = str((p.get("_data") or {}).get("pushName") or p.get("notifyName") or "").strip()
        number = cls._sender_number(output)
        number = f"+{number.lstrip('+')}" if number else None
        media = p.get("media") if isinstance(p.get("media"), dict) else {}
        found = None
        if p.get("hasMedia") or media:
            kind = media_kind(media.get("mimetype"), media.get("filename")) if media else "file"
            found = {"kind": "voice" if kind == "audio" and cls._is_voice_note(p, media) else kind,
                     "url": media.get("url") if media.get("rehosted") else None,
                     "duration": cls._audio_seconds(p) if kind == "audio" else None,
                     "transcript": media.get("transcript") or media.get("extracted_text")}
        elif p.get("location"):
            found = {"kind": "location", "url": None, "duration": None, "transcript": None}
        elif p.get("vCards"):
            found = {"kind": "contact", "url": None, "duration": None, "transcript": None}
        quoted = p.get("replyTo") if isinstance(p.get("replyTo"), dict) else {}
        return event_summary(
            chat_name=cls._group_name(output) if group else name, chat_avatar=seen_chat.get("avatar_url"),
            sender_avatar=seen_sender.get("avatar_url"), chat_kind="self" if cls._owner_note(output) else
            "group" if group else "direct", chat_number=None if group else number, sender_name=name,
            sender_id=participant or chat, sender_number=number, text=p.get("body") or p.get("caption"),
            media=found, quoted_text=" ".join(str(quoted.get("body") or "").split()),
            message_id=p.get("id") if isinstance(p.get("id"), str) else None)

    @classmethod
    def agent_pickup(cls, output: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """The chat of a verified WAHooks message an agent takes into a turn, whose end tells it when the turn stopped
        partway (``agent_turn_ended``); the owner's own messages count only in their "Message yourself" chat. It
        shows the account ``typing`` at once, which WAHooks counts toward the pause it keeps before the reply, except
        in the owner's own chat and in a group's talk not addressed to the account (mentioning it, or replying to its
        message), which the agent may well let pass."""
        p = output.get("payload")
        if output.get("event") not in _MESSAGE_EVENTS or not isinstance(p, dict) or not cls._verified(output):
            return None
        owner = cls._owner_note(output)
        if cls._from_me(p) and not owner:
            return None
        connection_id = str(output.get("connectionId") or "").strip()
        chat_id, _ = cls._message_chat(p)
        if not connection_id or not chat_id:
            return None
        typing = not owner
        if chat_id.endswith("@g.us"):
            own = cls._own_ids(output)
            quoted = p.get("replyTo") if isinstance(p.get("replyTo"), dict) else {}
            typing = cls._mentions_any(p, own) or cls._account_part(quoted.get("participant")) in own
        return {"connection_id": connection_id, "chat_id": chat_id, "token": uuid.uuid4().hex, "typing": typing}

    @classmethod
    async def agent_working(cls, picked: Dict[str, Any]) -> None:
        """One typing call, never a read receipt (a reply marks the chat read, and a turn that stays quiet leaves it
        unread), and none while the chat already shows typing: every NoClick call shares one WAHooks token's calls a
        minute. A refused call (429 once that minute is used up) is given up, never retried: the reply then waits its
        usual pause."""
        from wahooks import WAHooksError

        api_key = os.environ.get("WAHOOKS_API_KEY")
        client = redis_client.get_shared_redis()
        if not api_key or client is None or not picked.get("typing", True):
            return
        conn, chat = picked["connection_id"], picked["chat_id"]
        key = _typing_key(conn, chat)
        try:
            if not await client.set(key, picked["token"], nx=True, ex=TYPING_SHOWN_S):
                return  # a turn before this one has it typing, and its end or its reply takes it down

            def show():
                from wahooks import WAHooks

                with WAHooks(api_key=api_key) as wahooks:
                    wahooks.start_typing(conn, chat)

            await asyncio.to_thread(show)
        except Exception as e:
            level = logging.INFO if isinstance(e, WAHooksError) and e.status_code == 429 else logging.WARNING
            logger.log(level, "[WhatsApp] typing in a chat while the agent works failed: %s", e)
            await _typing_not_shown(key, picked["token"])

    @classmethod
    async def agent_turn_ended(cls, picked: Dict[str, Any], *, shown: Optional[Dict[str, Any]] = None,
                               finished: bool = True, again: bool = False) -> None:
        """Stops the typing a quiet turn left; a turn that stopped partway edits the live status it left standing to
        say so, and that it tries again when it goes round again (whose own status is then the only one at work)."""
        api_key = os.environ.get("WAHOOKS_API_KEY")
        client = redis_client.get_shared_redis()
        if not api_key or client is None:
            return
        conn, chat = picked["connection_id"], picked["chat_id"]
        statuses = [] if finished else [s for name, s in (shown or {}).items() if name.startswith("whatsapp_status:")]
        if statuses:
            def say_stopped():
                from wahooks import WAHooks

                with WAHooks(api_key=api_key) as wahooks:
                    for status in statuses:
                        wahooks.edit_message(status["connection_id"], status["message_id"], status["chat_id"],
                                             STATUS_RETRYING if again else STATUS_STOPPED)

            try:
                await asyncio.to_thread(say_stopped)
            except Exception:
                # Past WhatsApp's ~15 minutes to edit a message, it stands as it is.
                logger.warning("[WhatsApp] saying a stopped turn's status didn't go through failed", exc_info=True)
        try:
            # Gone when a reply went (``_execute_wahooks``); another turn's once a later message took the chat.
            if await client.get(_typing_key(conn, chat)) != picked["token"].encode():
                return
            await client.delete(_typing_key(conn, chat))

            def stop():
                from wahooks import WAHooks

                with WAHooks(api_key=api_key) as wahooks:
                    wahooks.stop_typing(conn, chat)

            await asyncio.to_thread(stop)
        except Exception:
            logger.warning("[WhatsApp] stopping the typing a quiet turn left failed", exc_info=True)

    @classmethod
    def describe_trigger(cls, operation: str, config: Dict[str, Any],
                         account: Optional[str]) -> Optional[Dict[str, Any]]:
        """Messages to the linked number, and whether its groups' reach it too (off unless the config says so)."""
        if operation != "receive_message":
            return None
        groups = str(config.get("include_group_messages") or "").lower() == "true"
        return {"title": f"Messages to {account}" if account else "WhatsApp messages",
                "hears": "Chats and groups" if groups else "Direct chats only", "groups": groups,
                "disconnected": "Phone disconnected", "reconnect": "Scan the code again"}

    @staticmethod
    def _seen_profiles(output: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """The chat's and its writer's profiles ``transform_trigger_payload`` put on a delivery (``{}`` for none)."""
        profiles = output.get("profiles") if isinstance(output.get("profiles"), dict) else {}
        return profiles.get("chat") or {}, profiles.get("sender") or {}

    @classmethod
    def _group_name(cls, output: Dict[str, Any]) -> Optional[str]:
        """A group message's group name, which the message doesn't carry: the one kept for the chat, else the one its
        delivery read with the members (``payload["group"]``)."""
        group = output.get("group") if isinstance(output.get("group"), dict) else {}
        return cls._seen_profiles(output)[0].get("name") or group.get("name") or None

    @staticmethod
    def _message_chat(p: Dict[str, Any]) -> Tuple[str, str]:
        """A WAHooks message's chat id, and in a group its writer's ("" in a direct chat)."""
        key = (p.get("_data") or {}).get("key") or {}
        return str(p.get("from") or key.get("remoteJid") or "").strip(), str(key.get("participant") or "").strip()

    @staticmethod
    def _sender_number(payload: Dict[str, Any]) -> Optional[str]:
        """The phone number an inbound message came from, in either envelope:
        WAHooks' ``senderPhone`` (its reading of a @lid sender's number) or a
        phone chat id, the Cloud API's ``from``. None when only a @lid names them."""
        p = payload.get("payload")
        if payload.get("event") == "message" and isinstance(p, dict):
            if p.get("senderPhone"):
                return str(p["senderPhone"])
            key = (p.get("_data") or {}).get("key") or {}
            jid = str(key.get("participant") or p.get("from") or key.get("remoteJid") or "")
            user, _, server = jid.partition("@")
            return user.split(":", 1)[0] if server in ("c.us", "s.whatsapp.net") else None
        if payload.get("object") == "whatsapp_business_account":
            try:
                return payload["entry"][0]["changes"][0]["value"]["messages"][0].get("from")
            except (KeyError, IndexError, TypeError, AttributeError):
                return None
        return None

    @staticmethod
    def _number_label(jid: str, phone: str) -> str:
        """A writer named by their number: WAHooks' reading of it, else their chat id's when it is a phone's (a @lid
        hides the number)."""
        if phone:
            return f"+{phone}"
        local, _, server = jid.partition("@")
        return f"+{local.split(':', 1)[0]}" if server in ("c.us", "s.whatsapp.net") else local

    @staticmethod
    def _account_part(jid: Any) -> str:
        """The account a jid names, without its server or device (12025550101:3@s.whatsapp.net → 12025550101)."""
        return str(jid or "").strip().partition("@")[0].split(":", 1)[0]

    @classmethod
    def _own_ids(cls, envelope: Dict[str, Any]) -> frozenset:
        """The linked account's own ids as a delivery names them (its number and its @lid), for telling what is
        addressed to it."""
        me = envelope.get("me") if isinstance(envelope.get("me"), dict) else {}
        return frozenset(filter(None, (cls._account_part(me.get("id")), cls._account_part(me.get("lid")))))

    @staticmethod
    def _from_me(p: Dict[str, Any]) -> bool:
        key = (p.get("_data") or {}).get("key") or {}
        return bool(p.get("fromMe") or key.get("fromMe"))

    @staticmethod
    def _unverified(envelope: Dict[str, Any], why: str) -> None:
        """Run a delivery as an unverified one (``_verified``), whatever its signature said."""
        webhook = envelope.get("_webhook")
        if isinstance(webhook, dict) and webhook.get("signature_verified"):
            webhook["signature_verified"] = False
            logger.warning(f"[WhatsAppNode] Delivery from a stale link runs without owner privileges: {why}")

    @staticmethod
    def _verified(envelope: Dict[str, Any]) -> bool:
        """Whether the receiver verified the delivery's WAHooks signature (``_webhook``, its own record of the request,
        which no body can set): only then is what it says about who wrote it the account's to vouch for."""
        webhook = envelope.get("_webhook")
        return isinstance(webhook, dict) and webhook.get("signature_verified") is True

    @classmethod
    def _owner_note(cls, envelope: Dict[str, Any]) -> bool:
        """Whether a delivery is the account's owner writing in their own "Message yourself" chat: their own message,
        in the chat that is the account itself by either spelling WhatsApp gives it (its number, or its @lid with the
        number as ``remoteJidAlt``), addressed to no one else (``to`` names only a group), and not one of the
        device-sync records WhatsApp keeps in that chat (``protocolMessage``). All of that is what the delivery says,
        so only a verified one can be it (``_verified``)."""
        if not cls._verified(envelope):
            return False
        p = envelope.get("payload")
        if not isinstance(p, dict) or not cls._from_me(p) or cls._raw_message(p).get("protocolMessage"):
            return False
        own = cls._own_ids(envelope)
        key = (p.get("_data") or {}).get("key") or {}

        def is_own(jid: Any) -> bool:
            server = str(jid or "").partition("@")[2]
            return server in ("c.us", "s.whatsapp.net", "lid") and cls._account_part(jid) in own

        chat = (key.get("remoteJid") or p.get("from"), key.get("remoteJidAlt"))
        return any(is_own(c) for c in chat) and (not p.get("to") or is_own(p["to"]))

    @classmethod
    def _mentions_any(cls, p: Dict[str, Any], ids: frozenset) -> bool:
        """Whether a message @mentions one of ``ids``: WAHA's raw record lists them in its ``contextInfo``, one
        ``message`` further down in a wrapper (``ephemeralMessage``)."""
        if not ids:
            return False

        def mentioned(message: Dict[str, Any]) -> List[str]:
            found: List[str] = []
            for value in message.values():
                if not isinstance(value, dict):
                    continue
                context = value.get("contextInfo") if isinstance(value.get("contextInfo"), dict) else {}
                found += [str(j) for j in context.get("mentionedJid") or []]
                if isinstance(value.get("message"), dict):
                    found += mentioned(value["message"])
            return found

        return any(cls._account_part(jid) in ids for jid in mentioned(cls._raw_message(p)))

    @classmethod
    def _quoted_line(cls, p: Dict[str, Any], own: frozenset) -> str:
        """What a swipe-to-reply quotes (WAHA's ``replyTo``), as the line opening the turn's message: in a long
        thread the quote is often the whole meaning of the message ("yes, that one")."""
        quoted = p.get("replyTo") if isinstance(p.get("replyTo"), dict) else None
        if quoted is None:
            return ""
        author = cls._account_part(quoted.get("participant"))
        who = ("your earlier message" if author and author in own
               else f"a message from {quoted['participant']}" if author else "an earlier message")
        text = " ".join(str(quoted.get("body") or "").split())
        if len(text) > 500:
            text = f"{text[:500]}…"
        return f'[Replying to {who}: "{text}"]' if text else f"[Replying to {who}]"

    @classmethod
    def operation_credential_types(cls, operation: str) -> Optional[frozenset]:
        if operation in QR_ONLY_OPERATIONS:
            return frozenset({"whatsapp_qr"})
        if operation in QR_OPERATIONS or operation in _TRIGGER_OPERATIONS:
            return None
        return frozenset({"whatsapp_access_token"})

    @staticmethod
    def _writer(p: Dict[str, Any]) -> str:
        """Who wrote an inbound message, as WhatsApp names them: a group's participant, else the chat."""
        data = p.get("_data") if isinstance(p.get("_data"), dict) else {}
        key = data.get("key") if isinstance(data.get("key"), dict) else {}
        return str(key.get("participant") or p.get("participant") or p.get("from") or "").strip()

    @classmethod
    async def _remember_sender_number(cls, payload: Dict[str, Any]) -> None:
        """Record the number a @lid writer's message names, so a scope written
        as numbers knows their chat (utils.whatsapp_lids)."""
        p = payload.get("payload")
        if not isinstance(p, dict) or p.get("fromMe") or not p.get("senderPhone"):
            return
        writer = cls._writer(p)
        number = chat_number(p["senderPhone"])
        if writer.endswith("@lid") and number:
            from utils import whatsapp_lids

            await whatsapp_lids.remember(payload.get("connectionId"), writer, number)

    @classmethod
    async def scope_matches(
        cls, field: str, value: str, allowed: List[str], credentials: Dict[str, Any],
    ) -> bool:
        """A recipient is the same person whichever id names them: a number in
        any of its spellings, or the @lid WhatsApp moved their chat to, once a
        message from it said whose it is. A scope picked as numbers otherwise
        refused every reply to an allowed person who now writes as a @lid."""
        if field not in ("to", "chat_id"):
            return False
        from utils import whatsapp_lids

        known = await whatsapp_lids.phones(credentials.get("connection_id"), [value, *allowed])

        def number(chat: str) -> Optional[str]:
            return known.get(chat) or chat_number(chat)

        wanted = number(value)
        return bool(wanted) and any(number(chat) == wanted for chat in allowed)

    @classmethod
    def filter_trigger_payload(cls, payload: Dict[str, Any], config: Dict[str, Any]) -> bool:
        """Drop WAHooks events a receive_message trigger must never fire on.

        A QR-linked account receives EVERY WhatsApp Web event as a
        "message": contact stories (status@broadcast) and Channel posts
        (@newsletter) — an auto-reply workflow fed those DMs arbitrary contacts
        (incl. replying to their stories). Group chats are opt-in via
        include_group_messages, unless chat_ids is set: then it alone names the
        chats that fire, groups included. A message from one of NoClick's own
        numbers never fires, in either envelope (``is_noclick_number``).
        The account's own messages (fromMe) come only on "message.any", which
        repeats every other message too: of it, only the owner writing in
        their own "Message yourself" chat fires, with include_self_chat on
        (``_owner_note``; the agent's own replies there drop_trigger_event
        drops by their id).
        """
        if (config or {}).get("operation") != "receive_message":
            return True
        if is_noclick_number(cls._sender_number(payload)):
            return False
        if payload.get("event") == SELF_CHAT_EVENT:
            return (config or {}).get("include_self_chat") == "true" and cls._owner_note(payload)
        event_payload = payload.get("payload")
        if payload.get("event") != "message" or not isinstance(event_payload, dict):
            # A WAHooks envelope (event + session or connectionId) that isn't a
            # message is control-plane traffic (session.status, a group's
            # group.v2.* membership changes, …) — normally consumed by
            # handle_control_event before this filter; dropping it here too
            # means a missed control event can never fire the workflow as a
            # ghost trigger. Non-WAHooks shapes (Meta Cloud API) pass through.
            if "event" in payload and ("session" in payload or "connectionId" in payload
                                       or str(payload["event"] or "").startswith("group.")):
                return False
            return True

        key = (event_payload.get("_data") or {}).get("key") or {}
        if cls._from_me(event_payload):
            return False
        chat_id = str(event_payload.get("from") or key.get("remoteJid") or "")
        if chat_id == "status@broadcast" or chat_id.endswith("@newsletter"):
            return False
        allowed = {_chat_key(c) for c in (config or {}).get("chat_ids") or [] if str(c).strip()}
        if allowed:
            # An @lid chat also carries its phone jid as remoteJidAlt, and the
            # picker may list either spelling.
            spellings = (chat_id, key.get("remoteJid"), key.get("remoteJidAlt"))
            return any(_chat_key(c) in allowed for c in spellings if str(c or "").strip())
        if chat_id.endswith("@g.us") and (config or {}).get("include_group_messages") != "true":
            return False
        return True

    @classmethod
    async def drop_trigger_event(
        cls, payload: Dict[str, Any], config: Dict[str, Any]
    ) -> Optional[str]:
        """A message a NoClick WhatsApp node sent never fires receive_message:
        two agents on different linked numbers would otherwise answer each
        other until credits run out (each reply is a genuine inbound message
        to the other, so ``fromMe`` can't see it). Exact match on the stanza
        id fingerprinted at send (utils/self_echo.py). Nor does one from
        NoClick's own line that names it only by a @lid already known to be it
        (``_from_noclick_lid``). In the owner's own chat, the agent's reply is
        the account's own message too (``_own_echo``)."""
        event_payload = payload.get("payload")
        if (
            (config or {}).get("operation") != "receive_message"
            or payload.get("event") not in _MESSAGE_EVENTS
            or not isinstance(event_payload, dict)
        ):
            return None
        stanza = _stanza_id(event_payload.get("_data"))
        if cls._from_me(event_payload):
            return await cls._own_echo(event_payload, stanza)
        if await is_self_post("whatsapp", stanza):
            return f"message {stanza} was sent by a NoClick WhatsApp node"
        if await cls._from_noclick_lid(payload):
            return "message from one of NoClick's own numbers, by its @lid"
        return None

    @staticmethod
    async def _own_echo(p: Dict[str, Any], stanza: Optional[str]) -> Optional[str]:
        """Why the account's own message, heard in its own chat, is a NoClick send rather than its owner writing:
        WAHA marks a send through its API (``source``; the owner's own is ``app``), and every NoClick send is
        fingerprinted by its id. Unlike another chat's, this check fails closed: a missed echo here is the agent
        answering itself, and the fire budget fails open on the same Redis."""
        if p.get("source") == "api":
            return "message sent through the API, in the account's own chat"
        sent = await self_post_verdict("whatsapp", stanza)
        if sent is None:
            return "message in the account's own chat that the echo guard can't check"
        return f"message {stanza} was sent by a NoClick WhatsApp node" if sent else None

    @classmethod
    async def _from_noclick_lid(cls, payload: Dict[str, Any]) -> bool:
        """Whether a message names its writer only by a @lid that an earlier delivery on this connection said is one
        of NoClick's numbers (``whatsapp_lids``). ``filter_trigger_payload`` judges a number, and a delivery without
        ``senderPhone`` names none."""
        from utils import whatsapp_lids

        writer = cls._writer(payload["payload"])
        if not writer.endswith("@lid"):
            return False
        return is_noclick_number((await whatsapp_lids.phones(payload.get("connectionId"), [writer])).get(writer))

    @classmethod
    def trigger_fire_budget_channel(
        cls, payload: Dict[str, Any], config: Dict[str, Any]
    ) -> Optional[str]:
        """Budget receive_message fires per chat — bounds two-party echo loops
        (bot replies, the counterparty auto-responds, repeat) that no
        authorship filter can catch."""
        if (config or {}).get("operation") != "receive_message":
            return None
        event_payload = payload.get("payload")
        if payload.get("event") not in _MESSAGE_EVENTS or not isinstance(event_payload, dict):
            return None
        key = (event_payload.get("_data") or {}).get("key") or {}
        return str(event_payload.get("from") or key.get("remoteJid") or "unknown")

    @classmethod
    def trigger_event_ids(
        cls, payload: Dict[str, Any], config: Dict[str, Any]
    ) -> Optional[Tuple[str, ...]]:
        """A WAHooks delivery's event ``id`` (``evt_…``), the same on every
        retry and re-post, and a message's ``payload.id``: ``message`` and
        ``message.any`` are two events for one message, and a re-sync after a
        reconnect sends a message again under a new event id. None for other
        shapes (Meta's Cloud API)."""
        if "event" not in payload or "session" not in payload:
            return None
        ids = []
        if isinstance(payload.get("id"), str) and payload["id"]:
            ids.append(f"event:{payload['id']}")
        message = payload.get("payload")
        if payload.get("event") in _MESSAGE_EVENTS and isinstance(message, dict) \
                and isinstance(message.get("id"), str) and message["id"]:
            ids.append(f"message:{message['id']}")
        return tuple(ids) or None

    # Provider media URLs require a service credential and are not safe to hand
    # to a run, and they expire within minutes: copy at delivery time. The copy
    # runs before the delivery is acked, and WAHooks aborts a delivery unanswered
    # after 15s and sends it again (5 attempts; trigger_event_ids keeps a copy
    # from rehosting or running twice): the timeout bounds the WHOLE copy and
    # its save to the chat's workspace, leaving room for the rest of the delivery.
    MEDIA_REHOST_MAX_BYTES = 100 * 1024 * 1024
    MEDIA_REHOST_TIMEOUT_S = 12

    @staticmethod
    def _raw_message(p: Dict[str, Any]) -> Dict[str, Any]:
        """WAHA's raw message record, when the engine ships it."""
        data = p.get("_data") if isinstance(p.get("_data"), dict) else {}
        return data.get("message") if isinstance(data.get("message"), dict) else {}

    @classmethod
    def _declared_media_size(cls, message: Dict[str, Any]) -> Optional[int]:
        """The size a raw message declares for its media: ``fileLength`` on its
        ``videoMessage``/``documentMessage``/…, one ``message`` further down in a
        wrapper (``documentWithCaptionMessage``, ``ephemeralMessage``). A protobuf
        Long reaches us as a number, a string or ``{low, high}``. Never reads
        ``contextInfo``, where a quoted message's size lives. None when absent."""
        for value in message.values():
            if not isinstance(value, dict):
                continue
            length = value.get("fileLength")
            if isinstance(length, dict) and isinstance(length.get("low"), int):
                length = (int(length.get("high") or 0) << 32) | (length["low"] & 0xFFFFFFFF)
            if isinstance(length, (int, str)) and str(length).isdigit():
                return int(length)
            if isinstance(value.get("message"), dict):
                nested = cls._declared_media_size(value["message"])
                if nested is not None:
                    return nested
        return None

    @classmethod
    def _audio_message(cls, p: Dict[str, Any]) -> Dict[str, Any]:
        """WAHA's raw record for a voice/audio message, when the engine ships it."""
        audio = cls._raw_message(p).get("audioMessage")
        return audio if isinstance(audio, dict) else {}

    @classmethod
    def _is_voice_note(cls, p: Dict[str, Any], media: Dict[str, Any]) -> bool:
        """A push-to-talk note rather than an audio file: WAHA marks it ``ptt``
        (NOWEB engine) or ``type: "ptt"`` (WEBJS); Opus-in-Ogg is the voice
        note codec either way."""
        data = p.get("_data") if isinstance(p.get("_data"), dict) else {}
        if cls._audio_message(p).get("ptt") is True or data.get("type") == "ptt":
            return True
        return "opus" in str(media.get("mimetype") or "").lower()

    @classmethod
    def _audio_seconds(cls, p: Dict[str, Any]) -> Optional[float]:
        secs = cls._audio_message(p).get("seconds")
        if secs is None:
            data = p.get("_data") if isinstance(p.get("_data"), dict) else {}
            secs = data.get("duration")
        return float(secs) if isinstance(secs, (int, float)) and secs > 0 else None

    # A delivery waits at most this long for what is kept of its chat's profiles.
    PROFILE_READ_TIMEOUT_S = 3

    @classmethod
    async def transform_trigger_payload(
        cls, payload, config, *, pool, workflow_id, node_id
    ):
        """An inbound message with what is kept of its chat's and writer's
        WhatsApp profiles on it (``_stamp_profiles``) and its media rehosted
        (``_rehost_media``)."""
        profiled = await cls._stamp_profiles(payload, config, pool=pool, workflow_id=workflow_id)
        rehosted = await cls._rehost_media(payload, config, pool=pool, workflow_id=workflow_id, node_id=node_id)
        return rehosted if rehosted is not None else (payload if profiled else None)

    @classmethod
    async def _stamp_profiles(cls, payload, config, *, pool, workflow_id) -> bool:
        """``payload["profiles"]``: the chat's and its writer's ``{jid, name,
        avatar_url}`` as kept for the node's own connection
        (``utils.whatsapp_profiles``; a group's ``name`` too), which fetches
        what isn't kept yet in the background. It holds the delivery only for
        a group it has no name for, within ``PROFILE_READ_TIMEOUT_S``: the
        agent's turn names the group by it. A group message's
        ``payload["group"]`` is who's in the group (``_group_members``), read
        alongside within the same budget; without it the turn says they're
        unknown. False when nothing could be read."""
        if payload.get("event") not in _MESSAGE_EVENTS or not workflow_id:
            return False
        chat, participant = cls._message_chat(payload.get("payload") or {})
        if not chat:
            return False
        from utils.inbound_media import resolve_delivery_credential
        from utils.whatsapp_profiles import chat_profiles

        writer = participant or chat
        loop = asyncio.get_running_loop()
        deadline = loop.time() + cls.PROFILE_READ_TIMEOUT_S
        try:
            async with asyncio.timeout_at(deadline):
                # The credential's own connection, never the one a delivery names.
                credential, _ = await resolve_delivery_credential(pool, config, str(workflow_id), "whatsapp_qr")
                connection_id = str((credential or {}).get("connection_id") or "")
                if not connection_id:
                    return False
                # Half a second of the budget stays for reading back what the wait found.
                reads = [chat_profiles(pool, connection_id, [chat, writer],
                                       name_wait_s=max(0.0, deadline - loop.time() - 0.5))]
                if chat.endswith("@g.us"):
                    reads.append(cls._group_members(connection_id, chat, writer, deadline - 0.25))
                found, *members = await asyncio.gather(*reads)
        except Exception as e:
            logger.warning(f"[WhatsApp] Chat profiles not read for workflow {workflow_id}: {type(e).__name__}: {e}")
            return False
        payload["profiles"] = {"chat": found[chat].as_dict(), "sender": found[writer].as_dict()}
        if members and members[0] is not None:
            payload["group"] = members[0]
        return True

    @staticmethod
    async def _group_members(connection_id: str, group_id: str, sender: str, deadline: float):
        """Who's in the group a message came from (``utils.wahooks_groups.turn_record``), read by ``deadline``
        (WAHooks keeps a group up to a minute and drops it on any change, so a busy group costs it little). None,
        logged, when it can't be read in time: the turn then says its members are unknown and goes on."""
        from utils import wahooks_groups

        loop = asyncio.get_running_loop()
        try:
            async with asyncio.timeout_at(deadline):
                group = await wahooks_groups.get_group(connection_id, group_id,
                                                       timeout=max(0.1, deadline - loop.time()))
        except Exception as e:
            logger.warning(f"[WhatsApp] Members of group {group_id} on {connection_id} not read: "
                           f"{type(e).__name__}: {e}")
            return None
        return wahooks_groups.turn_record(group, sender)

    @classmethod
    async def _rehost_media(cls, payload, config, *, pool, workflow_id, node_id):
        """Rehost an inbound message's media to workflow resources (R2) and
        swap ``payload.media.url`` for the public capability URL the agent can
        actually download, and keep the same bytes as a file in the workspace of
        the chat's turn (``utils.agent_inbox``): the slot's ``inbox`` says where
        (``path``), or why it isn't there (``error``). Media that can't be copied
        still runs as a message, without the provider URL (only the platform key
        opens it, and briefly): its slot says ``too_large`` with ``max_bytes`` and
        any known ``size``, or ``unavailable`` for a dead link, a transport
        failure or a missed deadline."""
        if payload.get("event") not in _MESSAGE_EVENTS:
            return None
        p = payload.get("payload") or {}
        await cls._remember_sender_number(payload)
        media = p.get("media") or {}
        url = media.get("url")
        if not url or not isinstance(url, str):
            return None
        api_key = os.environ.get("WAHOOKS_API_KEY")
        if not api_key or not workflow_id:
            return None

        # The service credential must only be sent to its provider. The URL is
        # carried in an inbound payload, so validate the parsed origin
        # before attaching the bearer (also blocks private-network SSRF).
        assert_exact_url_origin(url, WAHOOKS_API_ORIGIN)

        from utils.agent_inbox import Held, Spot, delivery_workspaces, keep, release, reserve
        from utils.inbound_media import MediaFetchFailed, MediaTooLarge, copy_inbound_media

        deadline = asyncio.get_running_loop().time() + cls.MEDIA_REHOST_TIMEOUT_S
        held = Held()

        async def place():
            # Where the chat's turn keeps the file, found while its bytes download.
            async with asyncio.timeout_at(deadline):
                event = cls.resolve_agent_event(payload) or {}
                chat = event.get("chat") or {}
                workspaces = await delivery_workspaces(pool, workflow_id=str(workflow_id), node_id=node_id,
                                                       payload=payload, conversation_key=event.get("conversation_key"))
                return await reserve(workspaces, cls._inbox_kind(p, media), cls._sent_at(p),
                                     chat_key=chat.get("key") or event.get("conversation_key"),
                                     chat_name=chat.get("name") or event.get("conversation_title"),
                                     original=media.get("filename"), mimetype=media.get("mimetype"))

        async def copy():
            async with asyncio.timeout_at(deadline):
                return await copy_inbound_media(
                    pool,
                    workflow_id=str(workflow_id),
                    node_id=node_id,
                    url=url,
                    source="whatsapp_inbound_media",
                    mimetype=media.get("mimetype"),
                    filename=media.get("filename") or url.rsplit("/", 1)[-1] or "whatsapp-media",
                    headers={"Authorization": f"Bearer {api_key}"},
                    declared_size=cls._declared_media_size(cls._raw_message(p)),
                    max_bytes=cls.MEDIA_REHOST_MAX_BYTES,
                    timeout_s=cls.MEDIA_REHOST_TIMEOUT_S,
                    sink=held,
                )

        spot, rehosted = await asyncio.gather(place(), copy(), return_exceptions=True)
        if isinstance(rehosted, BaseException) or not rehosted:
            if isinstance(spot, Spot):
                await release(spot)
            if not rehosted:
                return None
            if not isinstance(rehosted, Exception):
                raise rehosted
            no_url = {k: v for k, v in media.items() if k != "url"}
            if isinstance(rehosted, MediaTooLarge):
                logger.warning(f"[WhatsApp] {rehosted}; telling the agent")
                p["media"] = {**no_url, "too_large": True, "size": rehosted.size, "max_bytes": rehosted.max_bytes}
                return payload
            # By name: an R2 status error's message holds a signed URL. A fetch failure says only its status.
            why = rehosted if isinstance(rehosted, MediaFetchFailed) else type(rehosted).__name__
            logger.warning(f"[WhatsApp] inbound media not copied for node {node_id}: {why}")
            p["media"] = {**no_url, "unavailable": True}
            return payload
        p["media"] = {**media, **rehosted}
        inbox = await keep(spot, held, deadline=deadline, what=f"WhatsApp media for node {node_id} of {workflow_id}")
        if inbox is not None:
            p["media"]["inbox"] = {"kind": cls._inbox_kind(p, media), **inbox}
        return payload

    @classmethod
    def _inbox_kind(cls, p: Dict[str, Any], media: Dict[str, Any]) -> str:
        """What a message's file is, as its inbox name says: photo, sticker, voice (a voice note), audio, video or
        document."""
        from nodes.core.media_digest import media_kind

        kind = media_kind(media.get("mimetype"), media.get("filename"))
        if kind == "image":
            data = p.get("_data") if isinstance(p.get("_data"), dict) else {}
            return "sticker" if "stickerMessage" in cls._raw_message(p) or data.get("type") == "sticker" else "photo"
        if kind == "audio":
            return "voice" if cls._is_voice_note(p, media) else "audio"
        return kind if kind == "video" else "document"

    @staticmethod
    def _sent_at(p: Dict[str, Any]) -> datetime:
        """When a message was sent (its ``timestamp``, in seconds), else now."""
        ts = p.get("timestamp")
        if isinstance(ts, (int, float)) and not isinstance(ts, bool) and ts > 0:
            return datetime.fromtimestamp(ts, timezone.utc)
        return datetime.now(timezone.utc)

    @classmethod
    async def _foreign_account_delivery(cls, payload, config, *, pool, node_id) -> Optional[str]:
        """Why a WAHooks delivery is from a WhatsApp account this node's
        credential is not on (a webhook left on a previous credential's
        connection), or None. Running it would answer from the credential's
        number, not the one the sender wrote to. Judged on the envelope's
        ``connectionId`` against the credential's connection; the same phone
        through another of its links is still this account (a re-scan whose
        webhook carry-over failed keeps delivering from the old link), but
        runs as it would unsigned: owner privileges come from the credential's
        own connection alone. Whatever can't be judged lets the delivery
        through: no connectionId, no credential id, a lookup error. A lost
        message is worse."""
        from utils.credentials import _is_credential_uuid, credential_metadata

        delivered = str(payload.get("connectionId") or "")
        credential_id = ((config or {}).get("credentialIds") or {}).get("whatsapp_qr")
        if not delivered or not _is_credential_uuid(credential_id):
            return None
        try:
            from utils.encryption import get_encryption

            row = await pool.fetchrow(
                "SELECT credential, metadata FROM credentials WHERE id = $1::uuid", credential_id
            )
            bound = (
                str(get_encryption().decrypt_credential(row["credential"]).get("connection_id") or "")
                if row else None
            )
        except Exception as e:
            logger.warning(
                f"[WhatsAppNode] Can't tell which connection credential {credential_id} is on ({e}); "
                f"letting the delivery to {node_id} through"
            )
            return None
        if bound == delivered or bound == "":
            return None

        def digits(value) -> str:
            return "".join(ch for ch in str(value or "") if ch.isdigit())

        receiving = digits(str((payload.get("me") or {}).get("id") or "").split("@")[0].split(":")[0])
        if row and receiving and receiving == digits(credential_metadata(row).get("phone_number")):
            cls._unverified(payload, f"connection {delivered} is not credential {credential_id}'s ({bound})")
            return None
        logger.warning(
            f"[WhatsAppNode] Dropped a delivery to {node_id} from WhatsApp connection {delivered}: "
            f"its credential {credential_id} is "
            f"{f'on connection {bound}' if bound else 'deleted'}, so the webhook is a leftover"
        )
        return (
            f"Delivery from WhatsApp connection {delivered} ignored: this trigger's "
            f"credential is connected to a different WhatsApp account"
        )

    @classmethod
    async def handle_control_event(
        cls, payload, config, *, pool, workflow_id, node_id
    ):
        """Consume, without a run, WAHooks deliveries from an account the
        node's credential isn't on (``_foreign_account_delivery``) and
        ``session.status`` pushes.
        A down signal (FAILED/STOPPED) first arms a grace window — a worker
        restart flaps every session for ~30 s and the link comes back on its
        own — and only once the connection has stayed down past it do we
        live-verify the node's OWN credential's connection (an envelope from
        before WAHooks stamped ``connectionId`` can't be mapped to one, so a
        stale registration delivering another session's death must not
        mis-flag a healthy credential) and alert the owner. WORKING closes the
        window and, if an alert had gone out, tells the owner it reconnected
        so they don't re-scan a healthy link. Either way the credential's
        session moved (``session_moved``): no process keeps judging it by the
        status it had before, and the owner's pages read it again."""
        if "session" not in payload:
            return None
        if foreign := await cls._foreign_account_delivery(payload, config, pool=pool, node_id=node_id):
            return foreign
        if is_noclick_number(cls._sender_number(payload)):
            # It never reaches the trigger, but its chat may be a @lid an agent could send to.
            await cls._remember_sender_number(payload)
        if payload.get("event") != "session.status":
            return None
        status = str((payload.get("payload") or {}).get("status") or "").upper()
        consumed = f"session.status {status or 'unknown'} consumed"
        credential_id = ((config or {}).get("credentialIds") or {}).get("whatsapp_qr")
        if status == "WORKING":
            if not credential_id:
                return consumed
            from utils.whatsapp_qr import session_moved

            told = await cls._connection_back(str(credential_id), workflow_id, pool)
            await session_moved(pool, str(credential_id), up=True)  # after: the notice reads the alert's open window
            return f"{consumed} — owner told it reconnected" if told else consumed
        if status not in ("FAILED", "STOPPED"):
            return consumed
        if not credential_id:
            return f"{consumed} (no QR credential attached)"

        from utils.connection_grace import down_signal, up_signal

        verdict = await down_signal(str(credential_id))
        if verdict == "armed":
            return f"{consumed} (grace window armed)"
        if verdict == "waiting":
            return f"{consumed} (within grace window)"

        try:
            from utils.credentials import credential_metadata

            row = await pool.fetchrow(
                """SELECT (SELECT metadata FROM credentials WHERE id = $1::uuid) AS metadata,
                          (SELECT name FROM workflows WHERE id = $2::uuid) AS workflow_name""",
                credential_id, workflow_id,
            )
            connection_id = credential_metadata(row).get("connection_id") if row else None
            api_key = os.environ.get("WAHOOKS_API_KEY")
            if not (connection_id and api_key):
                return consumed

            from wahooks import WAHooks

            def _live_status():
                with WAHooks(api_key=api_key) as client:
                    return (client.get_connection(connection_id) or {}).get("status", "")

            live = await asyncio.wait_for(asyncio.to_thread(_live_status), timeout=5)
            if live == "connected":
                await up_signal(str(credential_id))
                return f"{consumed} (credential connection healthy)"

            from utils.notifications import send_channel_disconnected_alert
            from utils.whatsapp_qr import session_moved

            await send_channel_disconnected_alert(
                str(credential_id),
                provider_label="WhatsApp",
                session_status=live or status.lower(),
                workflow_id=workflow_id,
                workflow_name=row["workflow_name"] if row else None,
                pool=pool,
            )
            await session_moved(pool, str(credential_id), up=False)
            return f"{consumed} — owner alerted"
        except Exception as e:
            logger.warning(f"[WhatsAppNode] session.status handling failed: {e}")
            return consumed

    @staticmethod
    async def _connection_back(credential_id: str, workflow_id, pool) -> bool:
        """A WORKING push: close the grace window; if it was open AND the
        disconnect alert had been emailed, tell the owner it healed itself."""
        from utils.connection_grace import up_signal

        try:
            if not await up_signal(credential_id):
                return False
            from utils.notifications import send_channel_reconnected_notice

            return await send_channel_reconnected_notice(
                credential_id, provider_label="WhatsApp", workflow_id=workflow_id, pool=pool,
            )
        except Exception as e:
            logger.warning(f"[WhatsAppNode] reconnected notice failed: {e}")
            return False

    @staticmethod
    async def _registered_connections(pool, workflow_id, node_id) -> tuple:
        """``(webhooks row id, connection ids)``: the WAHooks connections this
        node's recorded registration lives on — the one the row recorded at
        registration (``external_webhook_id``), its registering credential's
        (metadata; covers rows from before the record), and every one it holds
        a signing secret for. None needs access to the credential, so one that
        belongs to another member or was deleted can't strand a webhook:
        WAHooks calls take only the platform key."""
        from utils.credentials import credential_metadata
        from utils.webhook_manager import recorded_signing_secrets

        row = await pool.fetchrow(
            """SELECT w.id, w.external_webhook_id, w.signing_secrets,
                      (SELECT c.metadata FROM credentials c
                        WHERE c.id::text = w.registered_credential_id) AS metadata
               FROM webhooks w WHERE w.workflow_id = $1 AND w.node_id = $2""",
            workflow_id if isinstance(workflow_id, uuid.UUID) else uuid.UUID(str(workflow_id)),
            node_id,
        )
        if not row:
            return None, set()
        recorded = {row["external_webhook_id"], credential_metadata(row).get("connection_id"),
                    *recorded_signing_secrets(row["signing_secrets"])}
        return str(row["id"]), {str(c) for c in recorded if c}

    @classmethod
    async def cleanup_external_webhook(
        cls, pool, workflow_id, node_id, config, credentials=None
    ):
        """Remove this node's WAHooks webhook from every connection it may be
        on: those its row records and the passed credential's (a re-scan moves
        a credential to a new connection). Raises when WAHooks can't, so the
        choke point keeps the record for a retry."""
        webhook_id, connections = await cls._registered_connections(pool, workflow_id, node_id)
        if credentials and credentials.get("credential_type") == "whatsapp_qr" and credentials.get("connection_id"):
            connections.add(str(credentials["connection_id"]))
        if not (webhook_id and connections):
            return
        api_key = os.environ.get("WAHOOKS_API_KEY")
        if not api_key:
            raise RuntimeError("WAHOOKS_API_KEY is not set; can't remove the WhatsApp webhook")
        from utils.webhook_delivery import get_webhook_url

        url = get_webhook_url(webhook_id)
        for connection_id in sorted(connections):
            if await asyncio.to_thread(_wahooks_drop_webhooks, api_key, connection_id, url):
                logger.info(f"[WhatsAppNode] Removed {node_id}'s WAHooks webhook from connection {connection_id}")

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Load chat options for recipient/chat picker fields, and group chats alone for ``group_id``.

        QR credentials list the account's chats via WAHooks (offset-paginated;
        search delegates to load_paginated_options' paginate-and-filter). The
        Cloud API has no chat listing, so non-QR credentials get an empty set —
        allow_custom on the field keeps manual phone entry working.
        """
        if field_name not in ("to", "chat_id", "group_id"):
            return {"options": [], "next_page_token": None}
        groups_only = field_name == "group_id"

        from nodes.core.dynamic_options import load_paginated_options, normalize_search

        connection_id = credential_data.get("connection_id")
        if not connection_id:
            if credential_data.get("credential_type") == "whatsapp_qr":
                raise ValueError("Reconnect WhatsApp via QR scan to load chats")
            return {"options": [], "next_page_token": None}

        api_key = os.environ.get("WAHOOKS_API_KEY")
        if not api_key:
            raise ValueError(
                "WhatsApp QR service is not configured; set WAHOOKS_API_KEY "
                "on this backend"
            )

        from wahooks import WAHooks

        page_size = 200

        def _fetch_contacts():
            from wahooks import WAHooks
            with WAHooks(api_key=api_key) as client:
                return client.get_contacts(connection_id, limit=1000)

        async def fetch_page(cursor):
            offset = int(cursor) if cursor else 0

            def _fetch():
                from wahooks import WAHooks
                with WAHooks(api_key=api_key) as client:
                    return client.get_chats(connection_id, limit=page_size, offset=offset)

            chats = await asyncio.to_thread(_fetch)
            last_page = len(chats) < page_size
            # Contacts fill two gaps chats can't: names for number-only chats,
            # and people with no chat history at all (contacts > chats on real
            # accounts). One fetch per load; appended after the final chats page.
            contacts = await asyncio.to_thread(_fetch_contacts) if last_page and not groups_only else []
            contact_names = {c.get("jid"): c.get("name") for c in contacts if c.get("jid")}
            seen = set()
            options = []
            for chat in chats:
                cid = chat.get("id")
                if not cid or (groups_only and not (chat.get("isGroup") or str(cid).endswith("@g.us"))):
                    continue
                seen.add(cid)
                options.append({
                    "value": cid,
                    "label": chat.get("name") or contact_names.get(cid)
                    or cid.split("@")[0],
                    "metadata": {
                        "is_group": chat.get("isGroup", False),
                        "unread": chat.get("unread", False),
                    },
                })
            for c in contacts:
                jid = c.get("jid")
                if not jid or jid in seen or c.get("isGroup"):
                    continue
                options.append({
                    "value": jid,
                    "label": c.get("name") or c.get("phoneNumber") or jid.split("@")[0],
                    "metadata": {"is_group": False, "contact_only": True},
                })
            # Advance by what the server actually returned — it may cap below
            # page_size, and requested==returned is not a reliable end signal.
            next_cursor = None if last_page else str(offset + len(chats))
            return options, next_cursor

        return await load_paginated_options(
            fetch_page,
            page_token=page_token,
            search=normalize_search(search),
            log_label="whatsapp_chats",
        )

    @classmethod
    async def load_field_value(
        cls,
        field_name: str,
        user_id: str,
        workflow_id,
        node_id: str,
        pool,
        context: Optional[Dict[str, Any]] = None,
        credential_ids: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Load computed values for webhook fields.
        For QR credentials, auto-registers the webhook URL with WAHooks
        so incoming messages are forwarded to our webhook endpoint.
        """
        if field_name != "webhook_url":
            return {"value": None}

        from utils.webhook_manager import WebhookManager, registration_fingerprint

        # Create our internal webhook URL
        webhook_data = await WebhookManager.get_or_create_webhook(
            pool=pool,
            user_id=user_id,
            workflow_id=workflow_id,
            node_id=node_id,
        )

        webhook_url = webhook_data.get("webhook_url")
        wahooks_registered = False
        registration_error = None

        # If QR credentials are selected, auto-register the webhook with WAHooks
        credential_id = (credential_ids or {}).get("whatsapp_qr")
        if credential_id and webhook_url:
            try:
                from utils.encryption import get_encryption

                encryption = get_encryption()

                async with pool.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT credential FROM credentials WHERE id = $1 AND owner_id = $2",
                        credential_id,
                        user_id,
                    )
                    if row:
                        cred_data = encryption.decrypt_credential(row["credential"])
                        connection_id = cred_data.get("connection_id")

                        if connection_id:
                            api_key = os.environ.get("WAHOOKS_API_KEY")
                            if api_key:
                                # Registering on a definitively dead session
                                # would report success on a webhook that can
                                # never fire (the builder did exactly this on a
                                # 3-day-dead session). Unknown status (WAHooks
                                # unreachable) still registers — never dead on
                                # a non-definitive signal.
                                from utils.whatsapp_qr import dead_session_status

                                if dead := await dead_session_status(connection_id):
                                    registration_error = f"WhatsApp session is {dead}; reconnect this saved account."
                                    logger.warning(
                                        f"[WhatsAppNode] NOT registering webhook: connection "
                                        f"{connection_id} session is {dead} — "
                                        f"credential needs a re-scan"
                                    )
                                else:
                                    # Moving to another connection: the previous one
                                    # stops delivering here first. Best-effort, like a
                                    # replaced provider endpoint — the delivery-time
                                    # account check drops anything a failure leaves.
                                    _, recorded = await cls._registered_connections(pool, workflow_id, node_id)
                                    for stale in sorted(recorded - {str(connection_id)}):
                                        try:
                                            await asyncio.to_thread(
                                                _wahooks_drop_webhooks, api_key, stale, webhook_url
                                            )
                                        except Exception as e:
                                            logger.warning(
                                                f"[WhatsAppNode] Couldn't remove {node_id}'s webhook from "
                                                f"previous connection {stale}: {e}"
                                            )
                                    secret = await asyncio.to_thread(
                                        _wahooks_ensure_webhook, api_key, connection_id, webhook_url,
                                        events=wahooks_webhook_events(context),
                                    )
                                    # The row records the connection, so teardown never
                                    # needs the credential (another member's, or deleted),
                                    # and the secret its deliveries are verified by.
                                    await WebhookManager.persist_registration_state(
                                        pool, webhook_data['webhook_id'],
                                        signing_secrets={connection_id: secret},
                                        external_webhook_id=connection_id,
                                        registered_operation='receive_message',
                                        registered_credential_id=credential_id,
                                        registered_fingerprint=registration_fingerprint(
                                            cls, 'receive_message', credential_id, context
                                        ),
                                    )
                                    wahooks_registered = True
                                    logger.info(
                                        f"[WhatsAppNode] WAHooks webhook registered for connection {connection_id}"
                                    )
            except Exception as e:
                registration_error = str(e)
                logger.warning(
                    f"[WhatsAppNode] Failed to auto-register WAHooks webhook: {e}"
                )

        # The row alone records the connection: a config copy would be a stale
        # record for handle_credential_change's pre-swap endpoint cleanup.
        webhook_data.pop("external_webhook_id", None)
        return {
            "values": {
                **webhook_data,
                "wahooks_registered": wahooks_registered,
                "trigger_registered": wahooks_registered if credential_id else None,
                # Provisioning drops None values to preserve unknown fields.
                # An explicit empty error clears a previous failed registration.
                "trigger_error": registration_error or (
                    "WhatsApp webhook registration is incomplete."
                    if credential_id and not wahooks_registered else ""
                ),
            }
        }

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute WhatsApp operation"""
        config = self.config
        if not config or not isinstance(config, WhatsAppNodeConfig):
            raise ValueError("WhatsApp configuration required")

        credentials = config.credentials
        if not credentials:
            raise ValueError(
                "WhatsApp credentials required. Add your access token in the credentials tab."
            )

        op_config = config.config
        action = op_config.operation

        # Webhook trigger operations work the same for both credential types —
        # data comes from webhook payload, not from API calls. execute() only
        # runs WITHOUT a live delivery (real firings short-circuit via
        # resolve_trigger_payload), so this is the manual/test path: the one
        # chance to tell the user the truth about whether events CAN arrive.
        if action == "receive_message":
            if isinstance(credentials, WhatsAppQRCredential):
                conn_id = credentials.connection_id

                # Definitively dead session = messages can never arrive; fail
                # the manual run loudly instead of returning a green no-event.
                from utils.whatsapp_qr import dead_session_status

                if dead := await dead_session_status(conn_id):
                    raise ValueError(
                        f"WhatsApp connection is dead (session {dead}) — "
                        f"incoming messages cannot reach this trigger. Re-scan the QR "
                        f"code for THIS WhatsApp credential to reconnect it; do NOT "
                        f"create a new credential (repeated fresh scans can get all "
                        f"of the phone's links logged out by WhatsApp)."
                    )

                webhook_url = getattr(op_config, "webhook_url", None)
                api_key = os.environ.get("WAHOOKS_API_KEY")
                if webhook_url and api_key:
                    try:
                        secret = await asyncio.to_thread(
                            _wahooks_ensure_webhook, api_key, conn_id, webhook_url,
                            events=wahooks_webhook_events(op_config.model_dump()),
                        )
                        if self.workflow_id:
                            from utils.database_pool import get_native_pool
                            from utils.webhook_manager import WebhookManager

                            await WebhookManager.record_signing_secrets(
                                get_native_pool(), webhook_url, {conn_id: secret},
                                workflow_id=self.workflow_id, node_id=self.node_id,
                            )
                    except Exception as e:
                        logger.warning(
                            f"[WhatsAppNode] Failed to verify WAHooks webhook: {e}"
                        )
            # Real firings never reach here — the payload short-circuits in
            # resolve_trigger_payload, so execute() is always the no-event path.
            return self.no_event_output(
                "receive_message",
                "To test: send a WhatsApp message to the connected number from "
                "ANOTHER phone (the number's own messages never trigger, but for its "
                "\"Message yourself\" chat with Trigger on Your Own Chat on), or mock "
                "this node's output.",
            )
        elif action == "receive_status_update":
            return self.no_event_output("receive_status_update")

        if action.startswith("send_"):
            await self._refuse_noclick_line([getattr(op_config, "to", "")], credentials)
        elif action in ("create_group", "add_group_participants"):
            await self._refuse_noclick_line(op_config.participants, credentials, NOCLICK_LINE_IN_GROUP)

        # Route to WAHooks handler for QR scan credentials
        if isinstance(credentials, WhatsAppQRCredential):
            return await self._execute_wahooks(op_config, credentials)

        if action in QR_ONLY_OPERATIONS:
            raise ValueError(
                f"The '{action}' operation requires a WhatsApp QR credential "
                "(the Meta Cloud API has no chat/message read access)."
            )

        # Route to appropriate handler
        if action == "send_text_message":
            return await self._handle_send_text(op_config, credentials)
        elif action == "send_template_message":
            return await self._handle_send_template(op_config, credentials)
        elif action == "send_image_message":
            return await self._handle_send_image(op_config, credentials)
        elif action == "send_video_message":
            return await self._handle_send_video(op_config, credentials)
        elif action == "send_document_message":
            return await self._handle_send_document(op_config, credentials)
        elif action == "send_audio_message":
            return await self._handle_send_audio(op_config, credentials)
        elif action == "send_location_message":
            return await self._handle_send_location(op_config, credentials)
        elif action == "send_contact_card":
            return await self._handle_send_contact(op_config, credentials)
        elif action == "send_interactive_buttons":
            return await self._handle_send_buttons(op_config, credentials)
        elif action == "send_interactive_list":
            return await self._handle_send_list(op_config, credentials)
        elif action == "send_reaction_emoji":
            return await self._handle_send_reaction(op_config, credentials)
        elif action == "mark_message_read":
            return await self._handle_mark_read(op_config, credentials)
        elif action == "upload_media":
            return await self._handle_upload_media(op_config, credentials)
        elif action == "get_media_url":
            return await self._handle_get_media_url(op_config, credentials)
        elif action == "download_media":
            return await self._handle_download_media(op_config, credentials)
        elif action == "delete_media":
            return await self._handle_delete_media(op_config, credentials)
        elif action == "get_business_profile":
            return await self._handle_get_business_profile(op_config, credentials)
        elif action == "update_business_profile":
            return await self._handle_update_business_profile(op_config, credentials)
        elif action == "register_phone_number":
            return await self._handle_register_phone(op_config, credentials)
        elif action == "request_verification_code":
            return await self._handle_request_code(op_config, credentials)
        elif action == "get_phone_number_info":
            return await self._handle_get_phone_info(op_config, credentials)
        elif action == "list_message_templates":
            return await self._handle_list_templates(op_config, credentials)
        elif action == "get_message_template":
            return await self._handle_get_template(op_config, credentials)
        elif action == "create_message_template":
            return await self._handle_create_template(op_config, credentials)
        elif action == "delete_message_template":
            return await self._handle_delete_template(op_config, credentials)
        elif action == "send_catalog_message":
            return await self._handle_send_catalog(op_config, credentials)
        elif action == "send_product_message":
            return await self._handle_send_product(op_config, credentials)
        elif action == "send_multi_product_message":
            return await self._handle_send_multi_product(op_config, credentials)
        elif action == "get_account_info":
            return await self._handle_get_account_info(op_config, credentials)
        elif action == "list_account_phone_numbers":
            return await self._handle_list_phone_numbers(op_config, credentials)
        raise ValueError(f"Unknown WhatsApp action: {action}")

    @staticmethod
    async def _refuse_noclick_line(recipients: List[Any], credentials, refusal: str = NOCLICK_LINE_REFUSAL) -> None:
        """A send to NoClick's own line, or a group change bringing it in, fails the call, its error (``refusal``)
        telling the agent why and what to do instead. A @lid counts once a delivery has said whose it is
        (``handle_control_event``)."""
        named = [str(r or "").strip() for r in recipients]
        lids = [r for r in named if r.endswith("@lid")]
        if lids and isinstance(credentials, WhatsAppQRCredential):
            from utils import whatsapp_lids

            known = await whatsapp_lids.phones(credentials.connection_id, lids)
            named = [known.get(r, r) for r in named]
        if any(is_noclick_number(r) for r in named):
            raise ValueError(refusal)

    async def _execute_wahooks(
        self, op_config, credentials: WhatsAppQRCredential
    ) -> Dict[str, Any]:
        """Execute WhatsApp operation via WAHooks API (v0.3.1+)"""
        from wahooks import WAHooks, WAHooksError

        from nodes.agent import event_pickup

        action = op_config.operation

        if action not in QR_OPERATIONS:
            raise ValueError(
                f"The '{action}' operation requires Meta Cloud API credentials (Access Token). "
                f"QR scan credentials support: {', '.join(sorted(QR_OPERATIONS))}"
            )

        # Resolved OUTSIDE the try below: an empty recipient must fail the node
        # (red run), not be folded into the error envelope a caller may read
        # as a returned call.
        chat_id: Optional[str] = None
        if action in _WAHOOKS_CHAT_ID_OPS:
            chat_id = wahooks_chat_id(op_config.chat_id)
        elif action.startswith("send_"):
            chat_id = wahooks_chat_id(op_config.to)
        from utils import wahooks_groups

        group_id = wahooks_groups.group_jid(op_config.group_id) if hasattr(op_config, "group_id") else None
        people = wahooks_groups.participant_ids(op_config.participants) if hasattr(op_config, "participants") else []

        start_time = time.time()
        try:
            api_key = os.environ.get("WAHOOKS_API_KEY")
            if not api_key:
                raise ValueError(
                    "WhatsApp QR service is not configured; set WAHOOKS_API_KEY "
                    "on this backend"
                )
            conn_id = credentials.connection_id

            # wahooks==0.10.0 ships only a synchronous httpx client; run the
            # blocking call off the event loop so a slow WhatsApp API request
            # can't freeze every other coroutine in the container.
            def _run_wahooks_op():
                with WAHooks(api_key=api_key) as client:
                    if action == "list_recent_chats":
                        res = client.get_chats(
                            conn_id,
                            limit=op_config.limit,
                            unread_only=op_config.unread_only == "true",
                        )
                        if isinstance(res, list):
                            res = {"chats": res, "count": len(res)}
                        return res
                    if action == "get_chat_messages":
                        page = client.get_messages(
                            conn_id,
                            chat_id,
                            limit=op_config.limit,
                            before=op_config.before or None,
                        )
                        return {
                            "messages": page.get("messages", []),
                            "next_before": page.get("nextBefore"),
                            "history_starts_at": page.get("historyStartsAt"),
                        }
                    if action == "list_contacts":
                        res = client.get_contacts(conn_id, limit=op_config.limit)
                        if isinstance(res, list):
                            res = {"contacts": res, "count": len(res)}
                        return res
                    if action == "edit_message":
                        return client.edit_message(
                            conn_id,
                            op_config.message_id,
                            chat_id,
                            op_config.body,
                        )
                    if action == "mark_chat_read":
                        return client.mark_read(conn_id, chat_id)
                    if action == "get_account_profile":
                        return client.get_profile(conn_id)
                    if action == "send_reaction_emoji":
                        return client.react(
                            conn_id,
                            chat_id=chat_id,
                            message_id=op_config.message_id,
                            reaction=op_config.emoji,
                        )
                    if action == "send_text_message":
                        return client.send_message(
                            conn_id,
                            chat_id=chat_id,
                            text=op_config.body,
                            reply_to=op_config.reply_to_message_id or None,
                        )
                    if action == "send_image_message":
                        return client.send_image(
                            conn_id,
                            chat_id=chat_id,
                            url=op_config.image_url or op_config.media_id,
                            caption=getattr(op_config, "caption", None),
                        )
                    if action == "send_video_message":
                        return client.send_video(
                            conn_id,
                            chat_id=chat_id,
                            url=op_config.video_url or op_config.media_id,
                            caption=getattr(op_config, "caption", None),
                        )
                    if action == "send_document_message":
                        return client.send_document(
                            conn_id,
                            chat_id=chat_id,
                            url=op_config.document_url or op_config.media_id,
                            filename=getattr(op_config, "filename", None),
                            caption=getattr(op_config, "caption", None),
                        )
                    if action == "send_audio_message":
                        return client.send_audio(
                            conn_id,
                            chat_id=chat_id,
                            url=op_config.audio_url or op_config.media_id,
                        )
                    if action == "send_location_message":
                        return client.send_location(
                            conn_id,
                            chat_id=chat_id,
                            latitude=float(op_config.latitude),
                            longitude=float(op_config.longitude),
                            name=getattr(op_config, "name", None),
                            address=getattr(op_config, "address", None),
                        )
                    if action == "send_contact_card":
                        return client.send_contact(
                            conn_id,
                            chat_id=chat_id,
                            contact_name=op_config.contact_name,
                            contact_phone=op_config.contact_phone,
                        )

            if action in GROUP_OPERATIONS:
                result = await _run_group_op(op_config, conn_id, group_id, people)
            elif action == "read_recent_messages":
                result = await _read_recent_messages(api_key, conn_id, op_config)
            else:
                result = await asyncio.to_thread(_run_wahooks_op)
            if action.startswith("send_"):
                # Self-echo guard: another NoClick WhatsApp trigger that
                # receives this message must not fire on it (drop_trigger_event).
                await record_self_post("whatsapp", _stanza_id(result))
                if action != "send_reaction_emoji":  # a reaction leaves the typing a turn showed
                    await _reply_sent(conn_id, chat_id)
                if isinstance(result, dict) and (sent := _sent_message_id(result)):
                    result = {**result, "message_id": sent}
                    if action == "send_text_message" and _is_live_status(op_config.body):
                        await event_pickup.shown(self.conversation_id, _status_shown(sent),
                                                 {"connection_id": conn_id, "chat_id": chat_id, "message_id": sent})
            elif action == "edit_message" and not _is_live_status(op_config.body):
                # The status became the answer (or its last word before a file): it no longer says the turn works.
                await event_pickup.shown(self.conversation_id, _status_shown(op_config.message_id), None)

            api_time = (time.time() - start_time) * 1000
            return {
                "status": "success",
                "action": action,
                "data": result if isinstance(result, dict) else {"result": result},
                "provider": "wahooks",
                "timing_ms": {"api_request": round(api_time, 2)},
            }

        except (WAHooksError, wahooks_groups.GroupError) as e:
            api_time = (time.time() - start_time) * 1000
            return {
                "status": "error",
                "action": action,
                "error": str(e),
                "error_code": getattr(e, "status_code", None) or getattr(e, "status", None),
                "provider": "wahooks",
                "timing_ms": {"api_request": round(api_time, 2)},
            }
        except Exception as e:
            api_time = (time.time() - start_time) * 1000
            return {
                "status": "error",
                "action": action,
                "error": str(e),
                "provider": "wahooks",
                "timing_ms": {"api_request": round(api_time, 2)},
            }

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        credentials: WhatsAppAccessTokenCredential,  # Only for Cloud API calls
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        action_name: str = "request",
    ) -> Dict[str, Any]:
        """Make authenticated request to WhatsApp API"""
        url = f"{WHATSAPP_API_BASE}/{endpoint}"
        headers = {
            "Authorization": f"Bearer {credentials.access_token}",
            "Content-Type": "application/json",
        }

        start_time = time.time()

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=json_body,
                )

                api_time = (time.time() - start_time) * 1000

                # Handle successful responses
                if response.status_code in [200, 201]:
                    return {
                        "status": "success",
                        "action": action_name,
                        "data": response.json() if response.text else {},
                        "status_code": response.status_code,
                        "timing_ms": {"api_request": round(api_time, 2)},
                    }

                # Handle errors
                error_data = {}
                try:
                    error_data = response.json()
                except:
                    error_data = {"message": response.text}

                error_message = error_data.get("error", {}).get(
                    "message", str(error_data)
                )
                error_code = error_data.get("error", {}).get(
                    "code", response.status_code
                )

                return {
                    "status": "error",
                    "action": action_name,
                    "error": error_message,
                    "error_code": error_code,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": round(api_time, 2)},
                }

        except httpx.TimeoutException:
            return {
                "status": "error",
                "action": action_name,
                "error": "Request timeout (30s)",
                "timing_ms": {
                    "api_request": round((time.time() - start_time) * 1000, 2)
                },
            }
        except Exception as e:
            return {
                "status": "error",
                "action": action_name,
                "error": str(e),
                "timing_ms": {
                    "api_request": round((time.time() - start_time) * 1000, 2)
                },
            }

    # ========================================================================
    # Messaging Handlers
    # ========================================================================

    async def _handle_send_text(
        self, config: WhatsAppSendTextConfig, credentials: WhatsAppAccessTokenCredential
    ) -> Dict[str, Any]:
        """Send text message"""
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": config.to,
            "type": "text",
            "text": {"preview_url": config.preview_url, "body": config.body},
        }
        if config.reply_to_message_id:
            payload["context"] = {"message_id": config.reply_to_message_id}

        return await self._make_request(
            "POST",
            f"{credentials.phone_number_id}/messages",
            credentials,
            json_body=payload,
            action_name="send_text_message",
        )

    async def _handle_send_template(
        self,
        config: WhatsAppSendTemplateConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Send template message"""
        template_params = []
        if config.parameters:
            try:
                template_params = json.loads(config.parameters)
            except:
                template_params = []

        payload = {
            "messaging_product": "whatsapp",
            "to": config.to,
            "type": "template",
            "template": {
                "name": config.template_name,
                "language": {"code": config.language_code},
            },
        }

        if template_params:
            payload["template"]["components"] = [
                {"type": "body", "parameters": template_params}
            ]

        return await self._make_request(
            "POST",
            f"{credentials.phone_number_id}/messages",
            credentials,
            json_body=payload,
            action_name="send_template_message",
        )

    async def _handle_send_image(
        self,
        config: WhatsAppSendImageConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Send image message"""
        image_obj = {}
        if config.image_url:
            image_obj["link"] = config.image_url
        elif config.media_id:
            image_obj["id"] = config.media_id
        else:
            return {
                "status": "error",
                "error": "Either image_url or media_id is required",
            }

        if config.caption:
            image_obj["caption"] = config.caption

        payload = {
            "messaging_product": "whatsapp",
            "to": config.to,
            "type": "image",
            "image": image_obj,
        }

        return await self._make_request(
            "POST",
            f"{credentials.phone_number_id}/messages",
            credentials,
            json_body=payload,
            action_name="send_image_message",
        )

    async def _handle_send_video(
        self,
        config: WhatsAppSendVideoConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Send video message"""
        video_obj = {}
        if config.video_url:
            video_obj["link"] = config.video_url
        elif config.media_id:
            video_obj["id"] = config.media_id
        else:
            return {
                "status": "error",
                "error": "Either video_url or media_id is required",
            }

        if config.caption:
            video_obj["caption"] = config.caption

        payload = {
            "messaging_product": "whatsapp",
            "to": config.to,
            "type": "video",
            "video": video_obj,
        }

        return await self._make_request(
            "POST",
            f"{credentials.phone_number_id}/messages",
            credentials,
            json_body=payload,
            action_name="send_video_message",
        )

    async def _handle_send_document(
        self,
        config: WhatsAppSendDocumentConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Send document message"""
        document_obj = {}
        if config.document_url:
            document_obj["link"] = config.document_url
        elif config.media_id:
            document_obj["id"] = config.media_id
        else:
            return {
                "status": "error",
                "error": "Either document_url or media_id is required",
            }

        if config.filename:
            document_obj["filename"] = config.filename
        if config.caption:
            document_obj["caption"] = config.caption

        payload = {
            "messaging_product": "whatsapp",
            "to": config.to,
            "type": "document",
            "document": document_obj,
        }

        return await self._make_request(
            "POST",
            f"{credentials.phone_number_id}/messages",
            credentials,
            json_body=payload,
            action_name="send_document_message",
        )

    async def _handle_send_audio(
        self,
        config: WhatsAppSendAudioConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Send audio message"""
        audio_obj = {}
        if config.audio_url:
            audio_obj["link"] = config.audio_url
        elif config.media_id:
            audio_obj["id"] = config.media_id
        else:
            return {
                "status": "error",
                "error": "Either audio_url or media_id is required",
            }

        payload = {
            "messaging_product": "whatsapp",
            "to": config.to,
            "type": "audio",
            "audio": audio_obj,
        }

        return await self._make_request(
            "POST",
            f"{credentials.phone_number_id}/messages",
            credentials,
            json_body=payload,
            action_name="send_audio_message",
        )

    async def _handle_send_location(
        self,
        config: WhatsAppSendLocationConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Send location message"""
        location_obj = {"latitude": config.latitude, "longitude": config.longitude}

        if config.name:
            location_obj["name"] = config.name
        if config.address:
            location_obj["address"] = config.address

        payload = {
            "messaging_product": "whatsapp",
            "to": config.to,
            "type": "location",
            "location": location_obj,
        }

        return await self._make_request(
            "POST",
            f"{credentials.phone_number_id}/messages",
            credentials,
            json_body=payload,
            action_name="send_location_message",
        )

    async def _handle_send_contact(
        self,
        config: WhatsAppSendContactConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Send contact card message"""
        contact_obj = {
            "name": {
                "formatted_name": config.contact_name,
                "first_name": config.contact_name.split()[0]
                if " " in config.contact_name
                else config.contact_name,
            },
            "phones": [{"phone": config.contact_phone, "type": "MOBILE"}],
        }

        if config.contact_email:
            contact_obj["emails"] = [{"email": config.contact_email, "type": "WORK"}]

        payload = {
            "messaging_product": "whatsapp",
            "to": config.to,
            "type": "contacts",
            "contacts": [contact_obj],
        }

        return await self._make_request(
            "POST",
            f"{credentials.phone_number_id}/messages",
            credentials,
            json_body=payload,
            action_name="send_contact_card",
        )

    async def _handle_send_buttons(
        self,
        config: WhatsAppSendButtonsConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Send interactive message with buttons"""
        try:
            buttons = json.loads(config.buttons)
        except:
            return {"status": "error", "error": "Invalid buttons JSON format"}

        interactive_obj = {
            "type": "button",
            "body": {"text": config.body},
            "action": {"buttons": buttons},
        }

        if config.header:
            interactive_obj["header"] = {"type": "text", "text": config.header}
        if config.footer:
            interactive_obj["footer"] = {"text": config.footer}

        payload = {
            "messaging_product": "whatsapp",
            "to": config.to,
            "type": "interactive",
            "interactive": interactive_obj,
        }

        return await self._make_request(
            "POST",
            f"{credentials.phone_number_id}/messages",
            credentials,
            json_body=payload,
            action_name="send_interactive_buttons",
        )

    async def _handle_send_list(
        self, config: WhatsAppSendListConfig, credentials: WhatsAppAccessTokenCredential
    ) -> Dict[str, Any]:
        """Send interactive list message"""
        try:
            sections = json.loads(config.sections)
        except:
            return {"status": "error", "error": "Invalid sections JSON format"}

        interactive_obj = {
            "type": "list",
            "body": {"text": config.body},
            "action": {"button": config.button_text, "sections": sections},
        }

        if config.header:
            interactive_obj["header"] = {"type": "text", "text": config.header}
        if config.footer:
            interactive_obj["footer"] = {"text": config.footer}

        payload = {
            "messaging_product": "whatsapp",
            "to": config.to,
            "type": "interactive",
            "interactive": interactive_obj,
        }

        return await self._make_request(
            "POST",
            f"{credentials.phone_number_id}/messages",
            credentials,
            json_body=payload,
            action_name="send_interactive_list",
        )

    async def _handle_send_reaction(
        self,
        config: WhatsAppSendReactionConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Send reaction to a message"""
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": config.to,
            "type": "reaction",
            "reaction": {"message_id": config.message_id, "emoji": config.emoji},
        }

        return await self._make_request(
            "POST",
            f"{credentials.phone_number_id}/messages",
            credentials,
            json_body=payload,
            action_name="send_reaction_emoji",
        )

    async def _handle_mark_read(
        self, config: WhatsAppMarkReadConfig, credentials: WhatsAppAccessTokenCredential
    ) -> Dict[str, Any]:
        """Mark message as read"""
        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": config.message_id,
        }

        return await self._make_request(
            "POST",
            f"{credentials.phone_number_id}/messages",
            credentials,
            json_body=payload,
            action_name="mark_message_read",
        )

    # ========================================================================
    # Media Management Handlers
    # ========================================================================

    async def _handle_upload_media(
        self,
        config: WhatsAppUploadMediaConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Upload media to WhatsApp — multipart binary upload to the /media endpoint."""
        from nodes.core.media_resolver import resolve_media_input

        resolved = await resolve_media_input(
            config.media_url, default_mime=config.media_type
        )
        # WhatsApp keys media on the declared MIME type; honor the chosen media_type.
        mime = config.media_type or resolved.mime_type

        url = f"{WHATSAPP_API_BASE}/{credentials.phone_number_id}/media"
        headers = {"Authorization": f"Bearer {credentials.access_token}"}
        start_time = time.time()
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    url,
                    headers=headers,
                    data={"messaging_product": "whatsapp", "type": mime},
                    files={"file": (resolved.filename, resolved.data, mime)},
                )
                api_time = (time.time() - start_time) * 1000

                if response.status_code in [200, 201]:
                    return {
                        "status": "success",
                        "action": "upload_media",
                        "data": response.json() if response.text else {},
                        "status_code": response.status_code,
                        "timing_ms": {"api_request": round(api_time, 2)},
                    }

                error_data = {}
                try:
                    error_data = response.json()
                except Exception:
                    error_data = {"message": response.text}
                error_message = error_data.get("error", {}).get(
                    "message", str(error_data)
                )
                error_code = error_data.get("error", {}).get(
                    "code", response.status_code
                )
                return {
                    "status": "error",
                    "action": "upload_media",
                    "error": error_message,
                    "error_code": error_code,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": round(api_time, 2)},
                }
        except httpx.TimeoutException:
            return {
                "status": "error",
                "action": "upload_media",
                "error": "Request timeout (120s)",
                "timing_ms": {
                    "api_request": round((time.time() - start_time) * 1000, 2)
                },
            }

    async def _handle_get_media_url(
        self,
        config: WhatsAppGetMediaUrlConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Get media URL from media ID"""
        return await self._make_request(
            "GET", config.media_id, credentials, action_name="get_media_url"
        )

    async def _handle_download_media(
        self,
        config: WhatsAppDownloadMediaConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Download media file"""
        # Download binary data from media URL
        try:
            # Meta's get-media endpoint returns a short-lived URL on this
            # code-owned media origin. Never attach the WhatsApp bearer to an
            # arbitrary URL copied into the hidden operation config.
            assert_exact_url_origin(config.media_url, WHATSAPP_MEDIA_ORIGIN)
            async with guarded_async_client(timeout=60.0) as client:
                headers = {"Authorization": f"Bearer {credentials.access_token}"}
                response = await client.get(config.media_url, headers=headers)

                if response.status_code == 200:
                    import mimetypes

                    from nodes.core.binary_output import BinaryOutput

                    mime = (
                        response.headers.get("content-type")
                        or "application/octet-stream"
                    )
                    ext = mimetypes.guess_extension(mime.split(";")[0].strip()) or ""
                    return {
                        "status": "success",
                        "action": "download_media",
                        "data": {
                            "media": BinaryOutput(
                                data=response.content,
                                content_type=mime,
                                filename=f"whatsapp_media{ext}",
                            ),
                        },
                    }
                else:
                    return {
                        "status": "error",
                        "action": "download_media",
                        "error": f"Failed to download media: {response.status_code}",
                    }
        except Exception as e:
            return {"status": "error", "action": "download_media", "error": str(e)}

    async def _handle_delete_media(
        self,
        config: WhatsAppDeleteMediaConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Delete media from WhatsApp"""
        return await self._make_request(
            "DELETE", config.media_id, credentials, action_name="delete_media"
        )

    # ========================================================================
    # Business Profile Handlers
    # ========================================================================

    async def _handle_get_business_profile(
        self,
        config: WhatsAppGetBusinessProfileConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Get business profile"""
        params = {"fields": config.fields}

        return await self._make_request(
            "GET",
            f"{credentials.phone_number_id}/whatsapp_business_profile",
            credentials,
            params=params,
            action_name="get_business_profile",
        )

    async def _handle_update_business_profile(
        self,
        config: WhatsAppUpdateBusinessProfileConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Update business profile"""
        payload = {"messaging_product": "whatsapp"}

        if config.about:
            payload["about"] = config.about
        if config.address:
            payload["address"] = config.address
        if config.description:
            payload["description"] = config.description
        if config.email:
            payload["email"] = config.email
        if config.vertical:
            payload["vertical"] = config.vertical
        if config.websites:
            payload["websites"] = [url.strip() for url in config.websites.split(",")]

        return await self._make_request(
            "POST",
            f"{credentials.phone_number_id}/whatsapp_business_profile",
            credentials,
            json_body=payload,
            action_name="update_business_profile",
        )

    # ========================================================================
    # Phone Number Handlers
    # ========================================================================

    async def _handle_register_phone(
        self,
        config: WhatsAppRegisterPhoneConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Register phone number"""
        payload = {"messaging_product": "whatsapp", "pin": config.pin}

        return await self._make_request(
            "POST",
            f"{credentials.phone_number_id}/register",
            credentials,
            json_body=payload,
            action_name="register_phone_number",
        )

    async def _handle_request_code(
        self,
        config: WhatsAppRequestCodeConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Request verification code"""
        payload = {"code_method": config.code_method, "language": config.language}

        return await self._make_request(
            "POST",
            f"{credentials.phone_number_id}/request_code",
            credentials,
            json_body=payload,
            action_name="request_verification_code",
        )

    async def _handle_get_phone_info(
        self,
        config: WhatsAppGetPhoneInfoConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Get phone number info"""
        params = {"fields": config.fields}

        return await self._make_request(
            "GET",
            credentials.phone_number_id,
            credentials,
            params=params,
            action_name="get_phone_number_info",
        )

    # ========================================================================
    # Template Management Handlers
    # ========================================================================

    async def _handle_list_templates(
        self,
        config: WhatsAppListTemplatesConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """List message templates"""
        if not credentials.business_account_id:
            return {
                "status": "error",
                "error": "Business Account ID required for template operations",
            }

        params = {"limit": config.limit}
        if config.status:
            params["status"] = config.status

        return await self._make_request(
            "GET",
            f"{credentials.business_account_id}/message_templates",
            credentials,
            params=params,
            action_name="list_message_templates",
        )

    async def _handle_get_template(
        self,
        config: WhatsAppGetTemplateConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Get specific template"""
        return await self._make_request(
            "GET", config.template_id, credentials, action_name="get_message_template"
        )

    async def _handle_create_template(
        self,
        config: WhatsAppCreateTemplateConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Create message template"""
        if not credentials.business_account_id:
            return {
                "status": "error",
                "error": "Business Account ID required for template operations",
            }

        components = [{"type": "BODY", "text": config.body}]

        if config.header:
            components.insert(
                0, {"type": "HEADER", "format": "TEXT", "text": config.header}
            )
        if config.footer:
            components.append({"type": "FOOTER", "text": config.footer})

        payload = {
            "name": config.name,
            "language": config.language,
            "category": config.category,
            "components": components,
        }

        return await self._make_request(
            "POST",
            f"{credentials.business_account_id}/message_templates",
            credentials,
            json_body=payload,
            action_name="create_message_template",
        )

    async def _handle_delete_template(
        self,
        config: WhatsAppDeleteTemplateConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Delete template"""
        if not credentials.business_account_id:
            return {
                "status": "error",
                "error": "Business Account ID required for template operations",
            }

        params = {"name": config.template_name}

        return await self._make_request(
            "DELETE",
            f"{credentials.business_account_id}/message_templates",
            credentials,
            params=params,
            action_name="delete_message_template",
        )

    # ========================================================================
    # Commerce Handlers
    # ========================================================================

    async def _handle_send_catalog(
        self,
        config: WhatsAppSendCatalogConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Send catalog message"""
        action_obj = {"name": "catalog_message"}

        if config.thumbnail_product_id:
            action_obj["parameters"] = {
                "thumbnail_product_retailer_id": config.thumbnail_product_id
            }

        payload = {
            "messaging_product": "whatsapp",
            "to": config.to,
            "type": "interactive",
            "interactive": {
                "type": "catalog_message",
                "body": {"text": config.body},
                "action": action_obj,
            },
        }

        return await self._make_request(
            "POST",
            f"{credentials.phone_number_id}/messages",
            credentials,
            json_body=payload,
            action_name="send_catalog_message",
        )

    async def _handle_send_product(
        self,
        config: WhatsAppSendProductConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Send product message"""
        interactive_obj = {
            "type": "product",
            "action": {
                "catalog_id": config.catalog_id,
                "product_retailer_id": config.product_id,
            },
        }

        if config.body:
            interactive_obj["body"] = {"text": config.body}

        payload = {
            "messaging_product": "whatsapp",
            "to": config.to,
            "type": "interactive",
            "interactive": interactive_obj,
        }

        return await self._make_request(
            "POST",
            f"{credentials.phone_number_id}/messages",
            credentials,
            json_body=payload,
            action_name="send_product_message",
        )

    async def _handle_send_multi_product(
        self,
        config: WhatsAppSendMultiProductConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Send multi-product message"""
        try:
            product_ids = json.loads(config.product_ids)
        except:
            return {"status": "error", "error": "Invalid product_ids JSON format"}

        sections = [
            {
                "title": config.header,
                "product_items": [{"product_retailer_id": pid} for pid in product_ids],
            }
        ]

        payload = {
            "messaging_product": "whatsapp",
            "to": config.to,
            "type": "interactive",
            "interactive": {
                "type": "product_list",
                "header": {"type": "text", "text": config.header},
                "body": {"text": config.body},
                "action": {"catalog_id": config.catalog_id, "sections": sections},
            },
        }

        return await self._make_request(
            "POST",
            f"{credentials.phone_number_id}/messages",
            credentials,
            json_body=payload,
            action_name="send_multi_product_message",
        )

    # ========================================================================
    # Account Management Handlers
    # ========================================================================

    async def _handle_get_account_info(
        self,
        config: WhatsAppGetAccountInfoConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """Get account info"""
        if not credentials.business_account_id:
            return {
                "status": "error",
                "error": "Business Account ID required for account operations",
            }

        params = {"fields": config.fields}

        return await self._make_request(
            "GET",
            credentials.business_account_id,
            credentials,
            params=params,
            action_name="get_account_info",
        )

    async def _handle_list_phone_numbers(
        self,
        config: WhatsAppListPhoneNumbersConfig,
        credentials: WhatsAppAccessTokenCredential,
    ) -> Dict[str, Any]:
        """List phone numbers"""
        if not credentials.business_account_id:
            return {
                "status": "error",
                "error": "Business Account ID required for account operations",
            }

        params = {
            "fields": "id,verified_name,display_phone_number,quality_rating,messaging_limit_tier",
            "limit": config.limit,
        }

        return await self._make_request(
            "GET",
            f"{credentials.business_account_id}/phone_numbers",
            credentials,
            params=params,
            action_name="list_account_phone_numbers",
        )

    # ========================================================================
    # Webhook Handlers
    # ========================================================================
