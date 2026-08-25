"""UsersRepo — the auth-store read seam.

Reads of Supabase's ``auth.users`` go through here so an edition with a
different identity store swaps ONE module. Callers pass any object with the
asyncpg fetch API (pool or pinned connection); ``user_id`` may be a str or
UUID — asyncpg accepts both for uuid params.

A few owning repositories still inline ``auth.users`` where the lookup is
part of a larger join; those queries remain local to their domain.
"""

from typing import Any, Dict, Optional

USER_EMAIL_SQL = "SELECT email FROM auth.users WHERE id = $1"


async def get_user_email(db, user_id) -> Optional[str]:
    """The user's auth email, or None when the user doesn't exist."""
    return await db.fetchval(USER_EMAIL_SQL, user_id)


async def get_user_profile(db, user_id) -> Optional[Dict[str, Any]]:
    """Email + display name (from raw_user_meta_data), or None."""
    row = await db.fetchrow(
        "SELECT email, raw_user_meta_data->>'name' AS name FROM auth.users WHERE id = $1",
        user_id,
    )
    return dict(row) if row else None


async def get_user_created_at(db, user_id):
    """The user's signup timestamp, or None when the user doesn't exist."""
    return await db.fetchval(
        "SELECT created_at FROM auth.users WHERE id = $1", user_id
    )
