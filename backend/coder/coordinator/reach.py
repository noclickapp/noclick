"""How the coordinator reaches its owner outside a reply: their phone over
WhatsApp or iMessage (where the instance can send them), its own email
address, or the web conversation.

How the owner likes to be reached is a memory, not a setting: the coordinator
reads it and names the channel. ``auto`` is the channel the owner last wrote
to the coordinator on, else the web. A channel that can't deliver says so; the
coordinator decides whether to try another.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

CHANNELS = ("whatsapp", "imessage", "email", "web")
_AS_CHANNEL = {"whatsapp_text": "whatsapp", "whatsapp": "whatsapp", "voice": "whatsapp", "phone": "whatsapp",
               "callback": "whatsapp", "imessage_text": "imessage", "imessage": "imessage",
               "email": "email", "web": "web"}
PHONE_APPS = ("whatsapp", "imessage")
_PHONE_EVENT_CHANNELS = [c for c, app in _AS_CHANNEL.items() if app in PHONE_APPS]


def normalize_channel(channel: Optional[str]) -> Optional[str]:
    return _AS_CHANNEL.get(channel)


async def last_used_channel(pool, user_id: str) -> Optional[str]:
    """The channel of the owner's newest message in the coordinator thread."""
    return normalize_channel(await pool.fetchval(
        """SELECT e->>'channel' FROM conversations c, jsonb_array_elements(c.events) WITH ORDINALITY AS t(e, i)
           WHERE c.conversation_id = $1 AND c.user_id = $2::uuid AND e->>'role' = 'user'
           ORDER BY i DESC LIMIT 1""",
        f"coordinator:{user_id}", user_id,
    ) or "web")


async def last_phone_app(pool, user_id: str) -> Optional[str]:
    """The app ("whatsapp" | "imessage") of the owner's newest message from their phone, if any."""
    return normalize_channel(await pool.fetchval(
        """SELECT e->>'channel' FROM conversations c, jsonb_array_elements(c.events) WITH ORDINALITY AS t(e, i)
           WHERE c.conversation_id = $1 AND c.user_id = $2::uuid AND e->>'role' = 'user'
             AND e->>'channel' = ANY($3::text[])
           ORDER BY i DESC LIMIT 1""",
        f"coordinator:{user_id}", user_id, _PHONE_EVENT_CHANNELS,
    ))


async def phone_text_channel(pool, user_id: str) -> str:
    """The text channel a follow-up for the owner's phone runs as: the app they text on, WhatsApp by default."""
    return "imessage_text" if await last_phone_app(pool, user_id) == "imessage" else "whatsapp_text"


def with_link(text: str, link: Optional[str]) -> str:
    """The message with its link on a line of its own, once: the text often carries it already."""
    if not link or link in text:
        return text
    return f"{text}\n{link}" if text else link


async def resolve_channel(pool, user_id: str, channel: str = "auto") -> str:
    if channel != "auto":
        return channel
    return await last_used_channel(pool, user_id) or "web"


async def reach_owner(
    pool, user_id: str, text: str, *, link: Optional[str] = None, channel: str = "auto",
    subject: Optional[str] = None, organization_id: Optional[str] = None,
) -> Dict[str, Any]:
    from utils.capabilities import OWNER_MESSAGE, capability

    resolved = await resolve_channel(pool, user_id, channel)
    if resolved in PHONE_APPS:
        send = capability(OWNER_MESSAGE)
        if send is None:
            label = "WhatsApp" if resolved == "whatsapp" else "iMessage"
            return {"success": False, "channel": resolved, "error": f"{label} isn't available on this instance."}
        return {**await send(pool, user_id, text, link=link, channel=resolved), "channel": resolved}
    if resolved == "email":
        from coder.coordinator.email_channel import send_owner_email

        return {**await send_owner_email(pool, user_id, with_link(text, link), subject=subject,
                                         organization_id=organization_id),
                "channel": resolved}
    if resolved == "web":
        return {**await _post_to_web(pool, user_id, with_link(text, link)), "channel": resolved}
    return {"success": False, "error": f"channel must be auto or one of {', '.join(CHANNELS)}"}


async def _post_to_web(pool, user_id: str, text: str) -> Dict[str, Any]:
    """A notification in the coordinator thread, live if the dock is open."""
    import uuid

    from repositories.conversation import ConversationRepo
    from utils.socket_singleton import get_sio
    from utils.task_notifications import emit_notification, notification_event

    conversation_id = f"coordinator:{user_id}"
    event = notification_event(text, f"coordinator-message:{uuid.uuid4()}")
    await pool.execute(ConversationRepo._UPSERT_CHAT_EVENT_SQL, conversation_id, user_id, None,
                       "__coordinator__", [event], "Coordinator", None)
    await emit_notification(get_sio(), user_id, conversation_id, event)
    return {"success": True}


async def reach_note(pool, user_id: str, *, phone_only: bool = False) -> str:
    """What the coordinator should know about reaching its owner this turn."""
    from coder.coordinator.email_channel import coordinator_address

    if phone_only:
        email_part = "Email: unavailable until the owner connects an email to this account (connect_account)."
    else:
        address = await coordinator_address(pool, user_id)
        email_part = "Your email address: " + (
            f"{address} (the owner can email you there; only their own mail is read)."
            if address else "none yet (set_email_address when email is first needed).")
    return (email_part
            + " How the owner likes to be reached is a memory: save it when they say, and pass that channel to "
              "message_owner.")
