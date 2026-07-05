"""Delivery dedup for app-level webhooks.

Slack redelivers an event (same ``event_id``) when the receiver doesn't ACK
2xx within ~3s — a slow handler double-fired every subscribed workflow.

Two-phase on purpose: ``was_delivered`` is checked before fan-out and
``mark_delivered`` is recorded only AFTER the event's subscriptions were
enqueued — a crash mid-processing leaves the event unmarked, so the provider's
retry recovers it instead of being swallowed. Redis errors fail open (a
duplicate fire beats a dropped event).
"""

import logging
from typing import Optional

from utils.redis_client import get_shared_redis

logger = logging.getLogger(__name__)

# Slack retries within the hour; anything older is a genuinely new event.
DEDUP_TTL_SECONDS = 60 * 60


def _key(provider: str, event_id: str) -> str:
    return f"appwebhook:delivered:{provider}:{event_id}"


async def was_delivered(provider: str, event_id: Optional[str]) -> bool:
    if not event_id:
        return False
    client = get_shared_redis()
    if client is None:
        return False
    try:
        return await client.exists(_key(provider, event_id)) > 0
    except Exception as e:
        logger.warning(f"[AppEventDedup] Check failed for {provider}:{event_id}: {e}")
        return False


async def mark_delivered(provider: str, event_id: Optional[str]) -> None:
    if not event_id:
        return
    client = get_shared_redis()
    if client is None:
        return
    try:
        await client.set(_key(provider, event_id), "1", ex=DEDUP_TTL_SECONDS)
    except Exception as e:
        logger.warning(f"[AppEventDedup] Mark failed for {provider}:{event_id}: {e}")
