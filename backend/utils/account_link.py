"""Connecting a phone-only account (made by messaging NoClick on WhatsApp) to
an email, from inside the chat: no link, no sign-in.

The owner names an email; a code goes to it; the owner types the code back.
Only a matching code moves anything, so naming someone else's email reaches
nothing. Then either the email's existing account absorbs the phone-only one
(``repositories/account_merge.py``: workflows, credentials, the coordinator
thread and the numbers move) or, when no account has that email, the
phone-only account takes it for sign-in. Whether an account exists for an
email is disclosed only after the code proves the owner holds it.

Verifying and moving are two steps: a code is checked during a coordinator
turn, and the move runs once that turn has been persisted (``complete``),
because the turn itself lives in the conversation the move rewrites.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional

from repositories.account_merge import merge_accounts
from repositories.phones import PhoneRepo
from repositories.users import get_user_email
from utils.phone_numbers import mask_e164
from utils.supabase_admin import SupabaseAdminClient, get_supabase_admin

logger = logging.getLogger(__name__)

CODE_TTL = timedelta(minutes=15)
MAX_SENDS_PER_ACCOUNT = 3   # per hour
MAX_SENDS_PER_EMAIL = 5     # per hour, across accounts
MAX_CHECKS = 5
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_MESSAGES = {
    "invalid_email": "That doesn't look like an email address",
    "has_email": "This chat is already connected to an account with an email",
    "too_many_sends": "Too many codes requested. Wait an hour before asking again",
    "send_failed": "The code email couldn't be sent. Try again in a minute",
    "no_code": "There's no code waiting. Ask for one first",
    "expired": "That code has expired. Ask for a new one",
    "invalid_code": "That code isn't right",
    "too_many_checks": "Too many wrong codes. Ask for a new one",
}


class AccountLinkError(ValueError):
    def __init__(self, kind: str):
        super().__init__(_MESSAGES[kind])
        self.kind = kind


@dataclass(frozen=True)
class Verified:
    email: str
    merges: bool  # an account with this email exists and absorbs this one


def _hash(challenge_id: str, code: str) -> str:
    return hashlib.sha256(f"{challenge_id}:{code}".encode()).hexdigest()


def normalize_email(raw: str) -> Optional[str]:
    value = (raw or "").strip().lower()
    return value if _EMAIL.match(value) else None


async def _lock(conn, *user_ids: str) -> None:
    for user_id in sorted(user_ids):
        await conn.execute("SELECT pg_advisory_xact_lock(hashtext('account:' || $1))", user_id)


async def merge_into(pool, *, source: str, target: str) -> None:
    """The one entry to a merge: both accounts locked, one transaction."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _lock(conn, source, target)
            result = await merge_accounts(conn, source=source, target=target)
    logger.info("account_merged source=%s target=%s moved=%s", source, target, result.moved)


class AccountLink:
    def __init__(
        self, pool, *,
        send_code: Optional[Callable[[str, str, str], Awaitable[bool]]] = None,
        admin: Callable[[], SupabaseAdminClient] = get_supabase_admin,
    ):
        self.pool = pool
        self._send_code = send_code
        self._admin = admin

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    async def _account_by_email(self, email: str) -> Optional[str]:
        value = await self.pool.fetchval(
            "SELECT id FROM auth.users WHERE lower(email) = $1 AND deleted_at IS NULL", email)
        return str(value) if value else None

    async def start(self, user_id: str, raw_email: str) -> dict:
        email = normalize_email(raw_email)
        if email is None:
            raise AccountLinkError("invalid_email")
        if await get_user_email(self.pool, user_id):
            raise AccountLinkError("has_email")
        since = self._now() - timedelta(hours=1)
        by_account = await self.pool.fetchval(
            "SELECT COUNT(*) FROM account_link_challenges WHERE user_id = $1::uuid AND created_at >= $2", user_id, since)
        by_email = await self.pool.fetchval(
            "SELECT COUNT(*) FROM account_link_challenges WHERE email = $1 AND created_at >= $2", email, since)
        if by_account >= MAX_SENDS_PER_ACCOUNT or by_email >= MAX_SENDS_PER_EMAIL:
            raise AccountLinkError("too_many_sends")
        code = f"{secrets.randbelow(10**6):06d}"
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE account_link_challenges SET status = 'superseded' WHERE user_id = $1::uuid AND status = 'pending'",
                    user_id)
                challenge_id = await conn.fetchval(
                    "INSERT INTO account_link_challenges (user_id, email, code_hash, expires_at) "
                    "VALUES ($1::uuid, $2, '', $3) RETURNING id", user_id, email, self._now() + CODE_TTL)
                await conn.execute("UPDATE account_link_challenges SET code_hash = $2 WHERE id = $1",
                                   challenge_id, _hash(str(challenge_id), code))
        phone = await PhoneRepo(self.pool).get_reach_phone(user_id)
        send = self._send_code or _default_send_code
        if not await send(email, code, mask_e164(phone["phone_e164"]) if phone else "your phone"):
            raise AccountLinkError("send_failed")
        logger.info("account_link_code_sent user=%s", user_id)
        return {"sent_to": email, "expires_in_minutes": int(CODE_TTL.total_seconds() // 60)}

    async def verify(self, user_id: str, raw_code: str) -> Verified:
        """Check the code; on a match the move is queued for ``complete``."""
        code = re.sub(r"\D", "", raw_code or "")
        row = await self.pool.fetchrow(
            "SELECT id, email, code_hash, attempts, expires_at FROM account_link_challenges "
            "WHERE user_id = $1::uuid AND status = 'pending' ORDER BY created_at DESC LIMIT 1", user_id)
        if row is None:
            raise AccountLinkError("no_code")
        if row["expires_at"] <= self._now():
            await self.pool.execute("UPDATE account_link_challenges SET status = 'failed' WHERE id = $1", row["id"])
            raise AccountLinkError("expired")
        if row["attempts"] >= MAX_CHECKS:
            await self.pool.execute("UPDATE account_link_challenges SET status = 'failed' WHERE id = $1", row["id"])
            raise AccountLinkError("too_many_checks")
        if len(code) != 6 or not hmac.compare_digest(_hash(str(row["id"]), code), row["code_hash"]):
            await self.pool.execute("UPDATE account_link_challenges SET attempts = attempts + 1 WHERE id = $1", row["id"])
            raise AccountLinkError("invalid_code")
        target = await self._account_by_email(row["email"])
        await self.pool.execute(
            "UPDATE account_link_challenges SET status = 'verified', attempts = attempts + 1, target_user_id = $2::uuid "
            "WHERE id = $1", row["id"], target)
        logger.info("account_link_verified user=%s merges=%s", user_id, target is not None)
        return Verified(email=row["email"], merges=target is not None)

    async def complete(self, user_id: str) -> Optional[str]:
        """Carry out a verified connection; the account the chat now reaches,
        or None when nothing was waiting."""
        row = await self.pool.fetchrow(
            "UPDATE account_link_challenges SET status = 'completed', completed_at = now() "
            "WHERE id = (SELECT id FROM account_link_challenges WHERE user_id = $1::uuid AND status = 'verified' "
            "ORDER BY created_at DESC LIMIT 1) RETURNING email, target_user_id", user_id)
        if row is None:
            return None
        target = str(row["target_user_id"]) if row["target_user_id"] else None
        if target is None:
            # No account had the email when the code was checked: this one takes it.
            await self._admin().update_user(user_id, email=row["email"], email_confirm=True)
            logger.info("account_link_email_attached user=%s", user_id)
            return user_id
        await merge_into(self.pool, source=user_id, target=target)
        return target


async def _default_send_code(email: str, code: str, phone_masked: str) -> bool:
    from utils.email import send_account_link_code_email

    return await send_account_link_code_email(email, code, phone_masked)
