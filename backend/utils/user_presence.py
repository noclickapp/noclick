"""User presence: is this user looking at NoClick right now?

Two signals. The coarse one: every authenticated socket event stamps
``nc:user:last_seen:{uid}`` in Redis (throttled per process, spawned off the
hot path), so a tab left open in the background still counts. The agent's
email_user steering reads it to tell "the owner is active in the app — talk in
chat" from "the owner is away — email is the channel". Advisory only: every
reader fails open to "unknown".

The strict one, ``watching_chat``: whether the owner is watching their chat
this moment, so a message the chat shows need not also go out by text. Each
browser tab claims it with ``presence:chat`` beats while the chat is on screen
in the focused window and touched within the last minute
(``hooks/useChatPresence.ts``). A claim is a member of
``nc:user:chat_live:{uid}`` scored with the time it lapses, so one tab leaving
never clears another's, and a tab that dies without a word stops counting
within ``CHAT_LIVE_TTL_SECONDS``. Any doubt reads as not watching: a wrong
"watching" loses the message, a wrong "away" only sends it twice.
"""
import logging
import time
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

# Seen within this window ⇒ "active in the app".
ACTIVE_WINDOW_SECONDS = 5 * 60
_STAMP_THROTTLE_SECONDS = 60
_KEY_TTL_SECONDS = 30 * 86400
_last_stamped: dict = {}  # user_id -> monotonic secs, per-process throttle


def _key(user_id: str) -> str:
    return f"nc:user:last_seen:{user_id}"


def touch_user_presence(user_id: str) -> None:
    """Fire-and-forget stamp — safe on the socket dispatch hot path."""
    now = time.monotonic()
    last = _last_stamped.get(user_id)
    if last is not None and now - last < _STAMP_THROTTLE_SECONDS:
        return
    _last_stamped[user_id] = now
    try:
        from utils.async_helpers import spawn
        from utils.redis_client import get_shared_redis

        redis = get_shared_redis()
        if redis is None:
            return

        async def _stamp():
            try:
                await redis.set(
                    _key(user_id), str(int(time.time())), ex=_KEY_TTL_SECONDS
                )
            except Exception:
                # Presence is advisory. Let a later socket event retry instead
                # of surfacing a detached-task failure for a Redis blip.
                _last_stamped.pop(user_id, None)
                logger.debug("[UserPresence] stamp failed", exc_info=True)

        spawn(_stamp(), name=f"presence-stamp:{user_id[:8]}")
    except Exception:
        _last_stamped.pop(user_id, None)
        logger.debug("[UserPresence] stamp failed", exc_info=True)


async def seconds_since_active(user_id: str) -> Optional[float]:
    """Seconds since the user's last socket activity; None = unknown."""
    try:
        from utils.redis_client import get_shared_redis

        redis = get_shared_redis()
        if redis is None:
            return None
        raw = await redis.get(_key(user_id))
        if not raw:
            return None
        return max(0.0, time.time() - float(raw))
    except Exception:
        logger.debug("[UserPresence] read failed", exc_info=True)
        return None


async def describe_owner_presence(user_id: str) -> str:
    """One human-readable clause for the agent's per-turn platform note."""
    age = await seconds_since_active(user_id)
    if age is None:
        return "AWAY (no recent NoClick app activity)"
    if age < ACTIVE_WINDOW_SECONDS:
        return "ACTIVE in the NoClick app right now"
    if age < 3600:
        return f"AWAY (last active ~{int(age // 60)} minutes ago)"
    if age < 86400:
        return f"AWAY (last active ~{int(age // 3600)} hours ago)"
    return f"AWAY (last active ~{int(age // 86400)} days ago)"


# A live tab beats every 15s; a claim it stops renewing lapses after this.
CHAT_LIVE_TTL_SECONDS = 35


def _chat_key(user_id: str) -> str:
    return f"nc:user:chat_live:{user_id}"


async def claim_chat_live(user_id: str, tab_id: str) -> None:
    """Record that this tab shows the user their chat right now. Never raises."""
    try:
        from utils.redis_client import get_shared_redis

        redis = get_shared_redis()
        if redis is None:
            return
        now = time.time()
        key = _chat_key(user_id)
        async with redis.pipeline(transaction=True) as pipe:
            pipe.zadd(key, {tab_id: now + CHAT_LIVE_TTL_SECONDS})
            pipe.zremrangebyscore(key, "-inf", now)
            pipe.expire(key, CHAT_LIVE_TTL_SECONDS)
            await pipe.execute()
    except Exception:
        logger.warning("[UserPresence] chat claim failed", exc_info=True)


async def release_chat_live(user_id: str, tab_ids: Iterable[str]) -> None:
    """Withdraw these tabs' claims (any other tab's stands). Never raises."""
    tab_ids = list(tab_ids)
    if not tab_ids:
        return
    try:
        from utils.redis_client import get_shared_redis

        redis = get_shared_redis()
        if redis is None:
            return
        await redis.zrem(_chat_key(user_id), *tab_ids)
    except Exception:
        # The claim still lapses on its own within CHAT_LIVE_TTL_SECONDS.
        logger.warning("[UserPresence] chat release failed", exc_info=True)


async def watching_chat(user_id: str) -> bool:
    """True only while one of the user's tabs holds a fresh claim; False on any doubt. Never raises."""
    try:
        from utils.redis_client import get_shared_redis

        redis = get_shared_redis()
        if redis is None:
            return False
        return await redis.zcount(_chat_key(user_id), f"({time.time()}", "+inf") > 0
    except Exception:
        logger.warning("[UserPresence] chat read failed", exc_info=True)
        return False
