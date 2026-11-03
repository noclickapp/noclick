"""Slack's shape for the self-echo guard (utils/self_echo.py).

A workflow whose Slack trigger listens to a channel (``on_channel_message``)
and whose agent replies into that same channel re-triggers itself: Slack
delivers the app's own post back to its events subscription. ``send_as="user"``
posts (xoxp) carry no ``bot_id``/``app_id``, so every message the Slack node
CREATES is fingerprinted by ``(channel, ts)`` (a ts is only unique within its
channel) and the app-webhook path drops inbound message events that match.
"""

from typing import Any, Dict, Optional

from utils import self_echo


async def record_self_post(channel: Optional[str], ts: Optional[str]) -> None:
    """Fingerprint a message the platform just created (chat.postMessage /
    chat.update response). Never raises."""
    if channel and ts:
        await self_echo.record_self_post("slack", f"{channel}:{ts}")


async def is_self_echo_event(event: Dict[str, Any]) -> bool:
    """Whether an inbound Slack event references a message NoClick itself
    posted. Covers plain messages, ``app_mention`` (a self-post that @mentions
    the bot fires both event types with the same ts), and ``message_changed``
    (a chat.update fires a message event whose edited ts is nested under
    ``event.message.ts``)."""
    if event.get("type") not in ("message", "app_mention"):
        return False
    channel = event.get("channel")
    if not isinstance(channel, str) or not channel:
        return False
    candidate_ts = {
        ts for ts in (
            event.get("ts"),
            (event.get("message") or {}).get("ts"),
        )
        if isinstance(ts, str) and ts
    }
    for ts in candidate_ts:
        if await self_echo.is_self_post("slack", f"{channel}:{ts}"):
            return True
    return False
