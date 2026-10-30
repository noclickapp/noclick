"""How the coordinator reaches its owner outside a reply: their phone over
WhatsApp or iMessage (where the instance can send them), its own email
address, or the web conversation.

How the owner likes to be reached is a memory, not a setting: the coordinator
reads it and names the channel. ``auto`` is the channel the owner last wrote
to the coordinator on, else the web, and the web in place of a text that
shouldn't go now (``unreachable_by_text``), saying why. A channel the
coordinator names that can't deliver says so; it decides whether to try another.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from utils.capabilities import OWNER_MESSAGE, capability
from utils.prompts import PromptPack

PROMPTS = PromptPack("coordinator")

CHANNELS = ("whatsapp", "imessage", "email", "web")
# "whatsapp" is also a WhatsApp call; the other calls came to NoClick's number from a phone, by no app.
_AS_CHANNEL = {"whatsapp_text": "whatsapp", "whatsapp": "whatsapp", "imessage_text": "imessage", "imessage": "imessage",
               "email": "email", "web": "web"}
CALLS = ("phone", "callback", "voice")
PHONE_APPS = ("whatsapp", "imessage")
APP_LABELS = {"whatsapp": "WhatsApp", "imessage": "iMessage"}


def normalize_channel(channel: Optional[str]) -> Optional[str]:
    return _AS_CHANNEL.get(channel)


async def last_used_channel(pool, user_id: str) -> Optional[str]:
    """The channel of the owner's newest message in the coordinator thread; after a phone call, the app they text
    on, if any (a call says nothing about which app reaches them)."""
    channel = await pool.fetchval(
        """SELECT e->>'channel' FROM conversations c, jsonb_array_elements(c.events) WITH ORDINALITY AS t(e, i)
           WHERE c.conversation_id = $1 AND c.user_id = $2::uuid AND e->>'role' = 'user'
           ORDER BY i DESC LIMIT 1""",
        f"coordinator:{user_id}", user_id,
    ) or "web"
    if channel in CALLS:
        return await last_phone_app(pool, user_id) or "web"
    return normalize_channel(channel)


async def last_phone_app(pool, user_id: str) -> Optional[str]:
    """The app ("whatsapp" | "imessage") the owner last texted from their phone on, if any: read from
    their numbers (``user_phones.last_seen_app``), whoever their texts went to."""
    from repositories.phones import PhoneRepo

    return await PhoneRepo(pool).last_seen_app(user_id)


async def phone_text_channel(pool, user_id: str) -> str:
    """The text channel a follow-up for the owner's phone runs as: the app they text on, WhatsApp by default."""
    return "imessage_text" if await last_phone_app(pool, user_id) == "imessage" else "whatsapp_text"


async def unreachable_by_text(pool, user_id: str, app: str) -> Optional[str]:
    """Why a text on ``app`` the owner isn't waiting on shouldn't go now, else None: they have the web chat open (it
    shows there as it lands), this instance can't send on ``app``, or WhatsApp's 24-hour window since their last
    text there has closed and nothing here sends past it (a platform's ``OWNER_MESSAGE`` sends its templates)."""
    from coder.coordinator.texting.owner_message import phone_sender
    from utils.user_presence import watching_chat

    if await watching_chat(user_id):
        return "the owner has the web chat open"
    if phone_sender(app) is None:
        return f"{APP_LABELS[app]} isn't available on this instance"
    if app == "whatsapp" and capability(OWNER_MESSAGE) is None:
        from coder.coordinator.texting.whatsapp import window_until

        if await window_until(pool, user_id) is None:
            return "WhatsApp's 24-hour window since the owner's last text there has closed"
    return None


def with_link(text: str, link: Optional[str]) -> str:
    """The message with its link on a line of its own, once: the text often carries it already."""
    if not link or link in text:
        return text
    return f"{text}\n{link}" if text else link


async def resolve_channel(pool, user_id: str, channel: str = "auto") -> str:
    if channel != "auto":
        return channel
    return await last_used_channel(pool, user_id) or "web"


async def choose_channel(pool, user_id: str, channel: str = "auto") -> Tuple[str, Optional[str]]:
    """``resolve_channel``, with ``auto``'s text held for the web when it shouldn't go now, and why."""
    resolved = await resolve_channel(pool, user_id, channel)
    if channel == "auto" and resolved in PHONE_APPS:
        why = await unreachable_by_text(pool, user_id, resolved)
        if why:
            return "web", why
    return resolved, None


async def reach_owner(
    pool, user_id: str, text: str, *, link: Optional[str] = None, channel: str = "auto",
    subject: Optional[str] = None, organization_id: Optional[str] = None,
) -> Dict[str, Any]:
    from coder.coordinator.texting.owner_message import phone_sender

    resolved, held = await choose_channel(pool, user_id, channel)
    if resolved in PHONE_APPS:
        send = phone_sender(resolved)
        if send is None:
            return {"success": False, "channel": resolved,
                    "error": f"{APP_LABELS[resolved]} isn't available on this instance."}
        return {**await send(pool, user_id, text, link=link, channel=resolved), "channel": resolved}
    if resolved == "email":
        from coder.coordinator.email_channel import send_owner_email

        return {**await send_owner_email(pool, user_id, with_link(text, link), subject=subject,
                                         organization_id=organization_id),
                "channel": resolved}
    if resolved == "web":
        posted = {**await _post_to_web(pool, user_id, with_link(text, link)), "channel": resolved}
        return {**posted, "note": f"Posted in the web chat, not texted: {held}."} if held else posted
    return {"success": False, "error": f"channel must be auto or one of {', '.join(CHANNELS)}"}


async def _post_to_web(pool, user_id: str, text: str) -> Dict[str, Any]:
    """A notification in the coordinator thread, live if the dock is open."""
    import uuid

    from repositories.conversation import ConversationRepo
    from utils.socket_singleton import get_sio
    from utils.task_notifications import emit_notification, notification_event

    conversation_id = f"coordinator:{user_id}"
    event = notification_event(text, f"coordinator-message:{uuid.uuid4()}")
    async with pool.acquire() as conn:
        await ConversationRepo.write_chat_event(conn, conversation_id, user_id, None, "__coordinator__", [event],
                                                "Coordinator", None)
    await emit_notification(get_sio(), user_id, conversation_id, event)
    return {"success": True}


async def reach_note(pool, user_id: str, *, phone_only: bool = False, owner_email: Optional[str] = None) -> str:
    """What the coordinator should know about reaching its owner this turn; ``owner_email`` is their own address."""
    from coder.coordinator.email_channel import coordinator_address, inbound_paused, instance_sender

    address = None if phone_only else await coordinator_address(pool, user_id)
    paused = bool(address) and await inbound_paused(pool, user_id)
    sends_from = None if phone_only or address else instance_sender()
    return PROMPTS.reach_note(phone_only=phone_only, address=address, paused=paused, instance_address=sends_from,
                              owner_email=owner_email)
