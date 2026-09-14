"""Grace window for provider "connection down" pushes.

A WAHA worker restart makes every session on it flap STARTING→FAILED for
25–40 s (one looped 20× before WORKING, 2026-09-14), so the first FAILED a
provider pushes is not a death. The push path arms a per-credential window
on the first down signal and only judges the connection once it has stayed
down for GRACE_S: a real death keeps emitting FAILED/STOPPED (the provider's
own recovery retries every ~3 min for 15 min, then stops the session), so it
is alerted minutes late instead of the owner being told to re-scan a link
that is about to come back. Past the window, live checks are throttled per
credential so an event loop cannot hammer the provider's API (it rate-limited
NoClick's verifies at 06:31). Redis errors fail OPEN to the immediate path —
an early email beats a missed death.
"""

import logging
import time

from utils import redis_client

logger = logging.getLogger(__name__)

GRACE_S = 120
_DOWN_TTL_S = 3600
_VERIFY_COOLDOWN_S = 60


def _down_key(credential_id: str) -> str:
    return f"conn:down:{credential_id}"


async def down_signal(credential_id: str) -> str:
    """Register a down push for a credential's connection.

    'armed'   — first sighting: the window opened, do not judge yet.
    'waiting' — still inside the window, or a live check ran < 60 s ago.
    'due'     — down for GRACE_S: verify and, if still down, alert.
    'unknown' — no Redis: judge immediately (fail open).
    """
    client = redis_client.get_shared_redis()
    if client is None:
        return "unknown"
    now = int(time.time())
    try:
        if await client.set(_down_key(credential_id), now, ex=_DOWN_TTL_S, nx=True):
            return "armed"
        first = await client.get(_down_key(credential_id))
        first_ts = int(first) if first else now
        if now - first_ts < GRACE_S:
            return "waiting"
        if not await client.set(
            f"conn:verify:{credential_id}", now, ex=_VERIFY_COOLDOWN_S, nx=True
        ):
            return "waiting"
        return "due"
    except Exception as e:
        logger.warning(f"[ConnectionGrace] Redis check failed for {credential_id}: {e}")
        return "unknown"


async def up_signal(credential_id: str) -> bool:
    """Close the window on a healthy signal. True iff one was open."""
    client = redis_client.get_shared_redis()
    if client is None:
        return False
    try:
        return bool(await client.delete(_down_key(credential_id)))
    except Exception as e:
        logger.warning(f"[ConnectionGrace] Redis clear failed for {credential_id}: {e}")
        return False
