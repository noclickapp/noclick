"""Delivery primitives shared by builder outcomes and agent replies.

Callers own the durable outbox claim; delivery never changes a task's outcome.
"""

import asyncio
import logging
from datetime import datetime, timezone

from utils.capabilities import OWNER_MESSAGE, capability
from wss.sender import send_event
from wss.sender.events import ChatMessageEvent

logger = logging.getLogger(__name__)


def notification_event(text, turn_id, **metadata):
    return {"role": "assistant", "message": text, "turn_id": turn_id, "notification": True,
            "timestamp": datetime.now(timezone.utc).isoformat(), **metadata}


async def deliver_phone(pool, user_id, text, *, link=None):
    send = capability(OWNER_MESSAGE)
    if send is None:
        return "failed", "No phone delivery channel; the result is saved in the conversation."
    try:
        kwargs = {"link": link} if link else {}
        result = await asyncio.wait_for(send(pool, user_id, text, **kwargs), 45)
        if result.get("success"):
            return "sent", None
        return "failed", result.get("error") or "Phone delivery failed."
    except Exception:
        logger.exception("Task phone delivery could not be confirmed")
        return "uncertain", "Phone delivery could not be confirmed. The result is saved in the conversation."


async def emit_notification(sio, user_id, conversation_id, event):
    await send_event(sio, "", ChatMessageEvent(
        conversation_id=conversation_id, message=event["message"], finished=True,
        turn_id=event["turn_id"], notification=True,
    ), user_id=user_id)
