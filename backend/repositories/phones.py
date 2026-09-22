"""Repository for verified phone identity: verification challenges and the
per-account phone bindings (user_phones: several numbers per account, one
account per live number). Backend-only tables (RLS on, no
policies); the linking rules live in utils/phone_identity.py.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional

from repositories.users import get_user_email

_PHONE_COLUMNS = "phone_e164, verified_at, link_version, source, last_seen_at"


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

    async def list_active_phones(self, user_id: str) -> List[Dict[str, Any]]:
        rows = await self._pool.fetch(
            f"SELECT {_PHONE_COLUMNS} FROM public.user_phones "
            "WHERE user_id = $1 AND unlinked_at IS NULL ORDER BY verified_at",
            user_id,
        )
        return [dict(r) for r in rows]

    async def get_reach_phone(self, user_id: str) -> Optional[Dict[str, Any]]:
        """The number to reach the account on: the live one it last messaged from."""
        row = await self._pool.fetchrow(
            f"SELECT {_PHONE_COLUMNS} FROM public.user_phones "
            "WHERE user_id = $1 AND unlinked_at IS NULL "
            "ORDER BY last_seen_at DESC NULLS LAST, verified_at DESC LIMIT 1",
            user_id,
        )
        return dict(row) if row else None

    async def get_user_by_phone(self, phone_e164: str, *, conn=None) -> Optional[Dict[str, Any]]:
        """The account a live number resolves to — what inbound channels key on."""
        row = await (conn or self._pool).fetchrow(
            "SELECT user_id, verified_at, link_version, source FROM public.user_phones "
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
                return await self._bind(conn, user_id, phone_e164, source="verify", challenge_id=challenge_id)

    @asynccontextmanager
    async def claiming(self, phone_e164: str) -> AsyncIterator[Any]:
        """A transaction holding the number's claim lock: two first messages
        from one new number must not mint two accounts."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock(hashtext('user_phones:' || $1))", phone_e164)
                yield conn

    async def bind_channel(self, conn, *, user_id: str, phone_e164: str, source: str) -> Dict[str, Any]:
        """Bind a number whose possession the channel itself authenticated."""
        return await self._bind(conn, user_id, phone_e164, source=source, challenge_id=None)

    @staticmethod
    async def _bind(conn, user_id: str, phone_e164: str, *, source: str, challenge_id: Optional[str]) -> Dict[str, Any]:
        row = await conn.fetchrow(
            """
            INSERT INTO public.user_phones (user_id, phone_e164, challenge_id, source)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_id, phone_e164) DO UPDATE SET
                verified_at = now(),
                unlinked_at = NULL,
                challenge_id = EXCLUDED.challenge_id,
                source = EXCLUDED.source,
                link_version = public.user_phones.link_version + 1
            RETURNING phone_e164, verified_at, link_version, source
            """,
            user_id, phone_e164, challenge_id, source,
        )
        return dict(row)

    async def orphan_phone_user(self, conn, phone_e164: str) -> Optional[str]:
        """An auth user created for this number whose binding never landed (a
        crash between the two writes). Auth stores the number without its +."""
        value = await conn.fetchval(
            "SELECT u.id FROM auth.users u WHERE u.phone = $1 AND u.deleted_at IS NULL "
            "AND NOT EXISTS (SELECT 1 FROM public.user_phones p WHERE p.user_id = u.id AND p.unlinked_at IS NULL)",
            phone_e164.lstrip("+"),
        )
        return str(value) if value else None

    async def account_email(self, user_id: str) -> Optional[str]:
        return await get_user_email(self._pool, user_id) or None

    async def absorb(self, *, source: str, target: str) -> None:
        """Fold a phone-only account into ``target`` (its numbers included)."""
        from utils.account_link import merge_into

        await merge_into(self._pool, source=source, target=target)

    async def touch_seen(self, phone_e164: str) -> None:
        await self._pool.execute(
            "UPDATE public.user_phones SET last_seen_at = now() "
            "WHERE phone_e164 = $1 AND unlinked_at IS NULL",
            phone_e164,
        )

    async def unlink(self, user_id: str, phone_e164: str) -> bool:
        """Unlink one number. The account's auth phone is cleared with it, so
        whoever holds the number next cannot sign in to this account by it."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                status = await conn.execute(
                    "UPDATE public.user_phones SET unlinked_at = now() "
                    "WHERE user_id = $1 AND phone_e164 = $2 AND unlinked_at IS NULL",
                    user_id, phone_e164,
                )
                await conn.execute(
                    "UPDATE auth.users SET phone = NULL, phone_confirmed_at = NULL "
                    "WHERE id = $1 AND phone = $2",
                    user_id, phone_e164.lstrip("+"),
                )
        return str(status).endswith(" 1")
