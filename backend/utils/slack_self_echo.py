"""Self-echo suppression for the Slack events receiver.

A workflow whose Slack trigger listens to a channel (``on_channel_message``)
and whose agent replies into that same channel re-triggers itself: Slack
delivers the app's own post back to its events subscription. Authorship fields
can't identify the default case — ``send_as="user"`` posts (xoxp) carry no
``bot_id``/``app_id`` — so the guard is exact instead: every message the
platform CREATES via the Slack node is fingerprinted here by ``(channel, ts)``,
and the app-webhook path drops inbound message events that match.

Fingerprints are deliberately global (not per-workflow): per-workflow keys
would still allow A→B→A cross-workflow loops. NoClick-authored messages never
trigger NoClick Slack triggers — same containment stance as inbound email
(which refuses all @noclick.app senders). Chain workflows directly, not via a
Slack channel.

Failure posture: recording must never fail the user's send, and a Redis blip
fails OPEN on the check (one extra fire — today's behavior) rather than eating
a real human message. Both paths log.
"""

import logging
from typing import Any, Dict, Optional

from utils.redis_client import get_shared_redis

logger = logging.getLogger(__name__)

# Comfortably past Slack's event-redelivery window (retries within ~1h);
# edits re-record on each chat.update, so a long TTL costs nothing.
SELF_POST_TTL_SECONDS = 6 * 60 * 60


def _key(channel: str, ts: str) -> str:
    return f"slack:selfpost:{channel}:{ts}"


async def record_self_post(channel: Optional[str], ts: Optional[str]) -> None:
    """Fingerprint a message the platform just created (chat.postMessage /
    chat.update response). Never raises — the send already succeeded and a
    guard bookkeeping failure must not fail the node run."""
    if not channel or not ts:
        return
    client = get_shared_redis()
    if client is None:
        logger.warning(
            "[SlackSelfEcho] REDIS_URL not set — self-post %s/%s not recorded; "
            "a same-channel trigger may re-fire on this message",
            channel, ts,
        )
        return
    try:
        await client.set(_key(channel, ts), "1", ex=SELF_POST_TTL_SECONDS)
    except Exception as e:
        logger.warning(
            f"[SlackSelfEcho] Failed to record self-post {channel}/{ts}: {e}"
        )


async def _is_self_post(channel: str, ts: str) -> bool:
    client = get_shared_redis()
    if client is None:
        return False
    try:
        return await client.exists(_key(channel, ts)) > 0
    except Exception as e:
        # Fail open: one extra fire beats dropping a real human message.
        logger.warning(
            f"[SlackSelfEcho] Fingerprint check failed for {channel}/{ts}: {e}"
        )
        return False


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
        if await _is_self_post(channel, ts):
            return True
    return False
