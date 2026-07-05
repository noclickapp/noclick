"""Delivery dedup for app-level webhooks.

Providers redeliver an event (same id) when the receiver doesn't ACK 2xx
fast enough (Slack: ~3s) — a slow handler double-fired every subscribed
workflow. Enabled per provider via the ``event_id`` extractor on
APP_PROVIDERS; the generic wiring lives in ``handle_app_webhook_payload``.

Deliberately best-effort at-least-once, biased toward firing:
- ``mark_delivered`` runs only AFTER the event's fan-out was ENQUEUED — a
  crash before that leaves the event unmarked and the provider's retry
  recovers it. Residual window: a crash after enqueue but before the queued
  run completes still marks the event; that loss is accepted (closing it
  needs a durable queue, not a marker).
- The check-then-mark split is NOT atomic: a retry arriving while the first
  delivery is still mid-processing passes the check and double-fires. Spaced
  retries (the common case — Slack backs off ~1m/5m) are deduped; making the
  concurrent case atomic would mean claiming BEFORE processing, turning
  every mid-processing crash into a permanently lost event.
- Redis errors fail open (a duplicate fire beats a dropped event).
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
