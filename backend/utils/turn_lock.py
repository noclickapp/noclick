"""One in-flight agent turn per conversation, held in Redis.

A concurrency guard, not spend protection (credit gates own that), so it fails
open: with no Redis, or on a Redis error, the caller proceeds unguarded. A held
lock is waited on briefly before the caller refuses, because the turn holding
it may be moments from releasing it.
"""

import asyncio
import logging
from typing import Awaitable, Callable, Optional

from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

TTL_S = 900  # backstop for a crashed holder; agent turns can run minutes
WAIT_S = 8.0
POLL_S = 0.25
_FAILURES = (RedisError, OSError, asyncio.TimeoutError)


def _key(conversation_id: str) -> str:
    return f"nc:shared:inflight:{conversation_id}"


def _redis():
    from utils.redis_client import get_shared_redis

    return get_shared_redis()


def _text(value) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


async def acquire(
    conversation_id: str,
    *,
    holder: str = "1",
    wait_s: float = WAIT_S,
    poll_s: float = POLL_S,
    ttl_s: int = TTL_S,
    is_stale: Optional[Callable[[str], Awaitable[bool]]] = None,
) -> Optional[bool]:
    """True once held; False when another holder kept it for ``wait_s``; None
    without a working Redis (proceed unguarded). ``is_stale(holder)`` lets a
    caller take over a lock whose holder it knows has finished."""
    redis = _redis()
    if redis is None:
        return None
    key = _key(conversation_id)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait_s
    try:
        while True:
            if await redis.set(key, holder, nx=True, ex=ttl_s):
                return True
            if is_stale is not None:
                current = await redis.get(key)
                if current is not None and await is_stale(_text(current)):
                    await _delete_if_held_by(redis, key, _text(current))
                    continue
            if loop.time() >= deadline:
                return False
            await asyncio.sleep(poll_s)
    except _FAILURES as e:
        logger.warning(f"[TurnLock] unavailable ({e}); proceeding unguarded")
        return None


async def holder(conversation_id: str) -> Optional[str]:
    """Who holds the conversation's lock: None when it is free or unreadable,
    so a caller asking "is a turn live?" hears no."""
    redis = _redis()
    if redis is None:
        return None
    try:
        current = await redis.get(_key(conversation_id))
    except _FAILURES as e:
        logger.warning(f"[TurnLock] could not read {conversation_id}: {e}")
        return None
    return None if current is None else _text(current)


async def hold(conversation_id: str, holder: str, *, ttl_s: int = TTL_S) -> None:
    """Hand a held lock to a new holder (e.g. the job that will run the turn)."""
    redis = _redis()
    if redis is None:
        return
    try:
        await redis.set(_key(conversation_id), holder, xx=True, ex=ttl_s)
    except _FAILURES as e:
        logger.warning(f"[TurnLock] could not hand over {conversation_id}: {e}")


async def release(conversation_id: str, *, holder: Optional[str] = None) -> None:
    """Free the lock; with ``holder``, only while that holder still has it."""
    redis = _redis()
    if redis is None:
        return
    key = _key(conversation_id)
    try:
        if holder is None:
            await redis.delete(key)
        else:
            await _delete_if_held_by(redis, key, holder)
    except _FAILURES as e:
        logger.warning(f"[TurnLock] failed to release {key}: {e}")


async def _delete_if_held_by(redis, key: str, holder: str) -> None:
    # Not atomic: a lock that expired and was re-taken between the two calls
    # could be freed early. The TTL is minutes, so the window is negligible.
    current = await redis.get(key)
    if current is not None and _text(current) == holder:
        await redis.delete(key)
