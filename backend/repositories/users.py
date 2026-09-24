"""UsersRepo — the auth-store read seam.

Reads of Supabase's ``auth.users`` go through here so an edition with a
different identity store swaps ONE module. Callers pass any object with the
asyncpg fetch API (pool or pinned connection); ``user_id`` may be a str or
UUID — asyncpg accepts both for uuid params.

A few owning repositories still inline ``auth.users`` where the lookup is
part of a larger join; those queries remain local to their domain.

``email`` is NULL for phone-only accounts (WhatsApp signup): never derive a
display name from it directly — use ``user_label`` / ``user_label_sql``.
"""

from typing import Any, Dict, Optional

USER_EMAIL_SQL = "SELECT email FROM auth.users WHERE id = $1"


def user_name_sql(alias: str = "") -> str:
    """SQL for a user's metadata name, including the username a phone signup
    stamps; never derived from the email (callers that show the email as a
    fallback keep doing so)."""
    meta = f"{alias}.raw_user_meta_data" if alias else "raw_user_meta_data"
    return (
        f"COALESCE(NULLIF({meta}->>'full_name', ''), NULLIF({meta}->>'name', ''), "
        f"NULLIF({meta}->>'username', ''))"
    )


def user_label_sql(alias: str = "") -> str:
    """SQL for a user's display label: metadata name, else the email's local
    part (NULL for a phone-only account). NULL only when the user has neither."""
    email = f"{alias}.email" if alias else "email"
    return f"COALESCE({user_name_sql(alias)}, NULLIF(split_part({email}, '@', 1), ''))"


def user_label(meta: Optional[Dict[str, Any]], email: Optional[str]) -> Optional[str]:
    """Python mirror of ``user_label_sql`` over user metadata (DB row or JWT
    ``user_metadata``) + email."""
    meta = meta or {}
    name = meta.get("full_name") or meta.get("name") or meta.get("username")
    return name or (email or "").split("@")[0] or None


async def get_user_email(db, user_id) -> Optional[str]:
    """The user's auth email, or None when the user doesn't exist."""
    return await db.fetchval(USER_EMAIL_SQL, user_id)


async def get_user_profile(db, user_id) -> Optional[Dict[str, Any]]:
    """Email (None for a phone-only account), metadata name, and display
    ``label``; None when the user doesn't exist."""
    row = await db.fetchrow(
        f"SELECT email, raw_user_meta_data->>'name' AS name, {user_label_sql()} AS label "
        "FROM auth.users WHERE id = $1",
        user_id,
    )
    return dict(row) if row else None


async def get_user_created_at(db, user_id):
    """The user's signup timestamp, or None when the user doesn't exist."""
    return await db.fetchval(
        "SELECT created_at FROM auth.users WHERE id = $1", user_id
    )
