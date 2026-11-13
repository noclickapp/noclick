"""Whether an account may still act.

An account whose sign-in is banned or deleted is closed (``cloud.scripts.close_account`` bans it first and deletes it
last). An access token issued before still verifies until it expires, and a key or a connection carries no sign-in at
all, so each way in asks this of the account it acts for: a Supabase access token (``utils.auth.verify_token``), a
platform key, session or connection (``cloud.platform.core.principal_store``), view-as (``cloud.mimic``) and the
workflow MCP's own tokens.

A verdict is kept in this process for ``KEEP_S``, so a request reads no row for it: a closure reaches a process that
judged the account a moment before within that (``forget`` drops this process's verdict at once).

Only a row read says an account is closed. An unknown status never locks a valid token out, as an unknown balance
never reaps: a read that fails or outlasts ``READ_S`` (a pool exhausted, a timeout, a connection reset) takes this
process's last verdict for the account, however old, else open, and is logged once per account per ``KEEP_S``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional, Tuple

import asyncpg
from opentelemetry import trace

logger = logging.getLogger(__name__)

CLOSED = "This account is closed."
REASON = "account_closed"
KEEP_S = 30.0
# The most a read may take, waiting for a connection and running, each.
READ_S = 2.0
_PRUNE_AT = 10_000

# An ``auth.users`` row that can still sign in. No row (a sign-in deleted outright) is closed too.
OPEN_SIGN_IN = "deleted_at IS NULL AND (banned_until IS NULL OR banned_until <= now())"
_OPEN_SQL = f"SELECT {OPEN_SIGN_IN} FROM auth.users WHERE id = $1::uuid"
_UNREADABLE = (asyncpg.PostgresError, asyncpg.InterfaceError, OSError, asyncio.TimeoutError)

_verdicts: Dict[str, Tuple[bool, float]] = {}
_warned: Dict[str, float] = {}


async def _read(user_id: str, db: Optional[Any]) -> bool:
    if db is None:
        from utils.database_pool import get_native_pool

        db = get_native_pool()
    if hasattr(db, "acquire"):  # a pool: the wait for a connection is bounded too
        async with db.acquire(timeout=READ_S) as conn:
            return await conn.fetchval(_OPEN_SQL, user_id, timeout=READ_S) is True
    return await db.fetchval(_OPEN_SQL, user_id, timeout=READ_S) is True


async def is_open(user_id: str, db: Optional[Any] = None) -> bool:
    """Whether the account ``user_id`` names may act; ``db``: a connection the caller holds, else the pool."""
    user_id = str(user_id)
    now = time.monotonic()
    kept = _verdicts.get(user_id)
    if kept is not None and kept[1] > now:
        return kept[0]
    try:
        verdict = await _read(user_id, db)
    except _UNREADABLE as e:
        verdict = kept[0] if kept is not None else True
        span = trace.get_current_span()
        span.set_attribute("account_status.unread", True)
        span.set_attribute("account_status.assumed", "last_verdict" if kept is not None else "open")
        if _warned.get(user_id, 0.0) <= now:
            _warned[user_id] = now + KEEP_S
            logger.warning("[account_status] couldn't read whether account %s is open (%s: %s); taking it as %s",
                           user_id, type(e).__name__, e,
                           ("open" if verdict else "closed") + (", its last verdict" if kept is not None else ""))
        return verdict
    if len(_verdicts) >= _PRUNE_AT:
        for stale in [k for k, (_, until) in _verdicts.items() if until <= now]:
            del _verdicts[stale]
        for stale in [k for k, until in _warned.items() if until <= now]:
            del _warned[stale]
    _verdicts[user_id] = (verdict, now + KEEP_S)
    return verdict


def forget(user_id: str) -> None:
    _verdicts.pop(str(user_id), None)
