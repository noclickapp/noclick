"""Process-wide shared redis.asyncio client.

Lazy singleton over REDIS_URL. Several modules historically built their own
clients per call (utils/slack.py, tool_use_notifier.py, ...); new call sites
should use this accessor so connections pool per process. Returns None when
REDIS_URL is unset (local dev without Redis) — callers own their degraded
behavior.
"""

import logging
import os
from typing import Optional

import redis.asyncio as redis

logger = logging.getLogger(__name__)

# Bounded-latency knobs EVERY infra Redis client must apply (spread into
# from_url alongside each module's own kwargs). A stale pooled connection —
# a network change or provider-idled socket — must fail within the configured
# timeout instead of stalling the request that owns it.
# health_check_interval revalidates idle connections before reuse (the
# stale-socket case specifically). retry_on_timeout stays OFF deliberately:
# callers run non-idempotent commands (INCR fire budgets, SET NX claims) that
# a blind retry could double-apply.
RESILIENCE_KWARGS: dict = {
    "socket_connect_timeout": 5,
    "socket_timeout": 10,
    "health_check_interval": 30,
}

_client: Optional[redis.Redis] = None
_warned_missing = False


def redis_url_or_none() -> Optional[str]:
    """The configured Redis URL, or None when there is no Redis.

    Redis is optional in this edition, so "no Redis" has to be a first-class
    answer rather than a connection error. Two ways it arrives: unset, and set
    to the empty string — which is what a compose file or a PaaS dashboard
    produces for a variable nobody filled in. A `redis://localhost:6379`
    default turns both into a refused connection on a host that never ran
    Redis, logged as an error, on every process start. Whitespace counts as
    empty for the same reason.
    """
    return (os.getenv("REDIS_URL") or "").strip() or None


def get_shared_redis() -> Optional[redis.Redis]:
    """Never raises: a missing OR malformed REDIS_URL returns None (warned
    once per process) — callers are guards on send/ingest hot paths whose
    bookkeeping must not fail the underlying operation. Values come back as
    bytes (no decode_responses) — decode explicitly if a caller needs str."""
    global _client, _warned_missing
    if _client is None:
        redis_url = redis_url_or_none()
        if not redis_url:
            _warn_once("REDIS_URL not set")
            return None
        try:
            _client = redis.from_url(redis_url, **RESILIENCE_KWARGS)
        except Exception as e:
            _warn_once(f"REDIS_URL invalid ({e})")
            return None
    return _client


def _warn_once(reason: str) -> None:
    # Once per process, not per call — callers run per-event/per-send and a
    # broken Redis config in prod silently disables every guard built on
    # this client.
    global _warned_missing
    if not _warned_missing:
        _warned_missing = True
        logger.warning(
            f"[RedisClient] {reason} — Redis-backed guards "
            f"(self-echo, dedup, fire budget) are disabled"
        )
