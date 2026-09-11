"""Atomic, retryable enqueue guards shared by signed app-webhook providers.

This is not an exactly-once durable queue. It serializes and deduplicates
enqueue attempts; process loss after marking but before BackgroundTasks run
still needs a durable outbox to close. Downstream writes need idempotency too.
"""

import asyncio
from contextlib import asynccontextmanager
import hashlib
import uuid

from fastapi import HTTPException


_CLAIM = """
if redis.call('EXISTS', KEYS[2]) == 1 then return 0 end
if redis.call('SET', KEYS[1], ARGV[1], 'NX', 'EX', ARGV[2]) then return 1 end
return -1
"""
_COMPLETE = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
redis.call('SET', KEYS[2], '1', 'EX', ARGV[2])
redis.call('DEL', KEYS[1])
return 1
"""
_RELEASE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) end
return 0
"""


@asynccontextmanager
async def guard_app_delivery(
    event_id, *, client, provider, label, lease_seconds,
    processing_seconds, dedup_seconds,
):
    """Yield False only for previously completed work, never on an outage.

    Provider/label are trusted adapter constants, never request parameters.
    """
    if client is None or not isinstance(event_id, str) or not event_id:
        raise HTTPException(status_code=503, detail=f"{label} delivery guard unavailable")
    if not 0 < processing_seconds < lease_seconds <= dedup_seconds:
        raise ValueError("Delivery guard requires processing < lease <= dedup retention")
    digest = hashlib.sha256(event_id.encode()).hexdigest()
    key = f"appwebhook:{provider}:{{{digest}}}"
    lease, delivered = f"{key}:lease", f"{key}:delivered"
    nonce = uuid.uuid4().hex
    try:
        claimed = await client.eval(_CLAIM, 2, lease, delivered, nonce, lease_seconds)
    except Exception:
        raise HTTPException(status_code=503, detail=f"{label} delivery guard unavailable") from None
    if claimed == 0:
        yield False
        return
    if claimed != 1:
        raise HTTPException(status_code=503, detail=f"{label} event delivery already in progress")
    try:
        async with asyncio.timeout(processing_seconds):
            yield True
    except BaseException as error:
        try:
            await client.eval(_RELEASE, 1, lease, nonce)
        except Exception:
            pass  # Short lease expires; never delete a different owner's lease.
        if isinstance(error, TimeoutError):
            raise HTTPException(status_code=503, detail=f"{label} event processing timed out") from None
        raise
    else:
        try:
            completed = await client.eval(_COMPLETE, 2, lease, delivered, nonce, dedup_seconds)
        except Exception:
            raise HTTPException(status_code=503, detail=f"{label} delivery acknowledgement unavailable") from None
        if completed != 1:
            raise HTTPException(status_code=503, detail=f"{label} delivery lease expired")
