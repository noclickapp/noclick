"""Whether an account may still act.

An account whose sign-in is banned or deleted is closed (``cloud.scripts.close_account`` bans it first and deletes it
last). An access token issued before still verifies until it expires, and a key or a connection carries no sign-in at
all, so each way in asks this of the account it acts for: a Supabase access token (``utils.auth.verify_token``), a
platform key, session or connection (``cloud.platform.core.principal_store``), view-as (``cloud.mimic``) and the
workflow MCP's own tokens.

A verdict is kept in this process for ``KEEP_S``, so a request reads no row for it: a closure reaches a process that
judged the account a moment before within that (``forget`` drops this process's verdict at once).
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple

CLOSED = "This account is closed."
REASON = "account_closed"
KEEP_S = 30.0
_PRUNE_AT = 10_000

# An ``auth.users`` row that can still sign in. No row (a sign-in deleted outright) is closed too.
OPEN_SIGN_IN = "deleted_at IS NULL AND (banned_until IS NULL OR banned_until <= now())"
_OPEN_SQL = f"SELECT {OPEN_SIGN_IN} FROM auth.users WHERE id = $1::uuid"

_verdicts: Dict[str, Tuple[bool, float]] = {}


async def is_open(user_id: str, db: Optional[Any] = None) -> bool:
    """Whether the account ``user_id`` names may act; ``db``: a connection the caller holds, else the pool."""
    user_id = str(user_id)
    now = time.monotonic()
    kept = _verdicts.get(user_id)
    if kept is not None and kept[1] > now:
        return kept[0]
    if db is None:
        from utils.database_pool import get_native_pool

        db = get_native_pool()
    verdict = await db.fetchval(_OPEN_SQL, user_id) is True
    if len(_verdicts) >= _PRUNE_AT:
        for stale in [k for k, (_, until) in _verdicts.items() if until <= now]:
            del _verdicts[stale]
    _verdicts[user_id] = (verdict, now + KEEP_S)
    return verdict


def forget(user_id: str) -> None:
    _verdicts.pop(str(user_id), None)
