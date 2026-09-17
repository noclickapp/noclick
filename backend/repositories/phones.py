"""Repository for verified phone identity: verification challenges and the
per-account phone binding (user_phones). Backend-only tables (RLS on, no
policies); the linking rules live in utils/phone_identity.py.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional


class PhoneRepo:
    def __init__(self, pool):
        self._pool = pool

    async def create_challenge(
        self, *, user_id: str, phone_e164: str, provider_sid: str, expires_at: datetime,
    ) -> Dict[str, Any]:
        """Mint a pending challenge; any older pending one for the user is superseded."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE public.phone_verification_challenges SET status = 'superseded' "
                    "WHERE user_id = $1 AND status = 'pending'",
                    user_id,
                )
                row = await conn.fetchrow(
                    """
                    INSERT INTO public.phone_verification_challenges
                        (user_id, phone_e164, provider_sid, expires_at)
                    VALUES ($1, $2, $3, $4)
                    RETURNING id, phone_e164, expires_at
                    """,
                    user_id, phone_e164, provider_sid, expires_at,
                )
        return dict(row)

    async def get_challenge(self, challenge_id: str, *, user_id: str) -> Optional[Dict[str, Any]]:
        row = await self._pool.fetchrow(
            "SELECT id, user_id, phone_e164, provider_sid, status, attempts, expires_at "
            "FROM public.phone_verification_challenges WHERE id = $1 AND user_id = $2",
            challenge_id, user_id,
        )
        return dict(row) if row else None

    async def record_check(
        self, challenge_id: str, *, status: str, attempted: bool = True, consumed: bool = False,
    ) -> None:
        await self._pool.execute(
            """
            UPDATE public.phone_verification_challenges
            SET status = $2,
                attempts = attempts + CASE WHEN $3::boolean THEN 1 ELSE 0 END,
                consumed_at = CASE WHEN $4::boolean THEN now() ELSE consumed_at END
            WHERE id = $1
            """,
            challenge_id, status, attempted, consumed,
        )

    async def count_starts(
        self, *, since: datetime, user_id: Optional[str] = None, phone_e164: Optional[str] = None,
    ) -> int:
        if (user_id is None) == (phone_e164 is None):
            raise ValueError("count_starts takes exactly one of user_id or phone_e164")
        column, key = ("user_id", user_id) if user_id else ("phone_e164", phone_e164)
        return int(await self._pool.fetchval(
            f"SELECT COUNT(*) FROM public.phone_verification_challenges "
            f"WHERE {column} = $1 AND created_at >= $2",
            key, since,
        ) or 0)

    async def get_active_phone(self, user_id: str) -> Optional[Dict[str, Any]]:
        row = await self._pool.fetchrow(
            "SELECT phone_e164, verified_at, link_version FROM public.user_phones "
            "WHERE user_id = $1 AND unlinked_at IS NULL",
            user_id,
        )
        return dict(row) if row else None

    async def get_user_by_phone(self, phone_e164: str) -> Optional[Dict[str, Any]]:
        """The account a live number resolves to — what inbound channels key on."""
        row = await self._pool.fetchrow(
            "SELECT user_id, verified_at, link_version FROM public.user_phones "
            "WHERE phone_e164 = $1 AND unlinked_at IS NULL",
            phone_e164,
        )
        return dict(row) if row else None

    async def consume_and_link(
        self, *, user_id: str, phone_e164: str, challenge_id: str,
    ) -> Dict[str, Any]:
        """Approve the challenge and bind the number in one transaction.

        Raises asyncpg.UniqueViolationError when another account holds the
        number live (user_phones_active_phone_idx); nothing is written then.
        """
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE public.phone_verification_challenges "
                    "SET status = 'approved', attempts = attempts + 1, consumed_at = now() WHERE id = $1",
                    challenge_id,
                )
                row = await conn.fetchrow(
                    """
                    INSERT INTO public.user_phones (user_id, phone_e164, challenge_id)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (user_id) DO UPDATE SET
                        phone_e164 = EXCLUDED.phone_e164,
                        verified_at = now(),
                        unlinked_at = NULL,
                        challenge_id = EXCLUDED.challenge_id,
                        link_version = public.user_phones.link_version + 1
                    RETURNING phone_e164, verified_at, link_version
                    """,
                    user_id, phone_e164, challenge_id,
                )
        return dict(row)

    async def unlink(self, user_id: str) -> bool:
        status = await self._pool.execute(
            "UPDATE public.user_phones SET unlinked_at = now() "
            "WHERE user_id = $1 AND unlinked_at IS NULL",
            user_id,
        )
        return str(status).endswith(" 1")
