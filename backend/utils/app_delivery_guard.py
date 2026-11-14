"""Atomic, retryable enqueue guards for webhook deliveries: the signed app-webhook
providers' and per-node trigger webhooks' (``WorkflowNode.trigger_event_ids``).

This is not an exactly-once durable queue. It serializes and deduplicates
enqueue attempts; process loss after marking but before BackgroundTasks run
still needs a durable outbox to close. Downstream writes need idempotency too.

What an outage means is the caller's choice (``fail_open``). A provider that
keeps retrying for a day or more is answered 503 and retries until Redis is
back. One that gives up within minutes (WAHooks: five attempts in about two) is
delivered unguarded: a 503 there drops the event for good, and a duplicate
needs a retry during the outage.
"""

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
import hashlib
import logging
import uuid

from fastapi import HTTPException

logger = logging.getLogger(__name__)

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
    processing_seconds, dedup_seconds, fail_open=False,
):
    """Yield False only for previously completed work, never on an outage.

    An outage (no client, or Redis failing) answers 503, or with ``fail_open``
    yields True with nothing claimed or recorded. Contention and a lost lease
    answer 503 either way. Provider/label are trusted adapter constants, never
    request parameters.
    """
    if not isinstance(event_id, str) or not event_id:
        raise HTTPException(status_code=503, detail=f"{label} delivery guard unavailable")
    if not 0 < processing_seconds < lease_seconds <= dedup_seconds:
        raise ValueError("Delivery guard requires processing < lease <= dedup retention")
    if client is None:
        # redis_client warns once per process that its guards are off.
        if not fail_open:
            raise HTTPException(status_code=503, detail=f"{label} delivery guard unavailable")
        yield True
        return
    digest = hashlib.sha256(event_id.encode()).hexdigest()
    key = f"appwebhook:{provider}:{{{digest}}}"
    lease, delivered = f"{key}:lease", f"{key}:delivered"
    nonce = uuid.uuid4().hex
    unguarded = False
    try:
        claimed = await client.eval(_CLAIM, 2, lease, delivered, nonce, lease_seconds)
    except Exception as error:
        if not fail_open:
            raise HTTPException(status_code=503, detail=f"{label} delivery guard unavailable") from None
        logger.error(f"[DeliveryGuard] {label} delivery guard unavailable, delivering unguarded: "
                     f"{type(error).__name__}: {error}")
        unguarded = True
    if unguarded:
        yield True
        return
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
        except Exception as error:
            if not fail_open:
                raise HTTPException(status_code=503, detail=f"{label} delivery acknowledgement unavailable") from None
            # The work is dispatched: a 503 would have it sent, and run, again.
            logger.error(f"[DeliveryGuard] {label} delivery dispatched but not recorded: "
                         f"{type(error).__name__}: {error}")
            return
        if completed != 1:
            raise HTTPException(status_code=503, detail=f"{label} delivery lease expired")


@asynccontextmanager
async def guard_app_deliveries(event_ids, **guard):
    """One delivery known by several ids (an event's, and the message's it
    carries) under ``guard_app_delivery``: already delivered if any of them
    was, claimed only once all of them are, each recorded when the work is."""
    async with AsyncExitStack() as stack:
        for event_id in event_ids:
            if not await stack.enter_async_context(guard_app_delivery(event_id, **guard)):
                yield False
                return
        yield True
