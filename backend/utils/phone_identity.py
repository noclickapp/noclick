"""Linking a phone number to a NoClick account by proving possession of it.

Two ways to prove possession. On the web, the signed-in user asks for a code,
Twilio Verify sends it, and only Twilio's own ``approved`` verdict on the
challenge minted for that exact user and number binds the two. On a channel
whose provider authenticates the sender (a Meta-signed WhatsApp message),
first contact binds the number to the account it already has, or to a new
phone-only account (``claim_for_channel``). Caller id, a ``pending`` result
or anything a client asserts never binds. An account holds up to
``MAX_PHONES_PER_ACCOUNT`` live numbers, each one more channel to it; a live
number belongs to one account. A rebind bumps ``link_version`` so work queued
for the old binding can be told from the new one. Whether a number belongs to
someone else is disclosed only after possession is proven.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional

import asyncpg

from repositories.phones import PhoneRepo
from utils.database_pool import get_native_pool
from utils.phone_numbers import mask_e164, normalize_e164
from utils.supabase_admin import SupabaseAdminClient, get_supabase_admin
from utils.twilio_verify import PlatformVerify, TwilioVerifyError

logger = logging.getLogger(__name__)

CHALLENGE_TTL = timedelta(minutes=10)  # Twilio Verify's default validity
MAX_STARTS_PER_USER = 3                # per CHALLENGE_TTL
MAX_STARTS_PER_NUMBER = 5              # per hour, across accounts
MAX_PHONES_PER_ACCOUNT = 5
MAX_CHECKS = 5                         # Twilio's own cap, refused here first so the wording is ours
_CODE = re.compile(r"^[0-9]{4,10}$")

_MESSAGES = {
    "not_configured": "Phone verification isn't set up on this instance",
    "invalid_number": "Enter the full number with its country code, like +1 424 242 1064",
    "too_many_sends": "Too many codes requested. Wait a few minutes before trying again",
    "rate_limited": "Too many requests right now. Try again in a minute",
    "expired": "That code has expired. Request a new one",
    "invalid_code": "That code isn't right",
    "too_many_checks": "Too many attempts. Request a new code",
    "linked_elsewhere": "That number is already linked to another NoClick account. Unlink it there first",
    "already_linked": "That number is already linked to this account",
    "too_many_phones": f"An account can link up to {MAX_PHONES_PER_ACCOUNT} numbers. Unlink one first",
    "not_linked": "That number isn't linked to this account",
    "last_way_in": "This number is the only way into this account. Add an email before unlinking it",
}


@dataclass(frozen=True)
class ChannelClaim:
    user_id: str
    created: bool  # a new phone-only account was made for this contact


class PhoneLinkError(ValueError):
    def __init__(self, kind: str, message: Optional[str] = None):
        super().__init__(message or _MESSAGES[kind])
        self.kind = kind


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if isinstance(value, datetime) else value


class PhoneIdentity:
    def __init__(
        self, repo: PhoneRepo, verify: Optional[PlatformVerify],
        admin: Callable[[], SupabaseAdminClient] = get_supabase_admin,
    ):
        self.repo = repo
        self.verify = verify
        self._admin = admin

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    async def status(self, user_id: str) -> Dict[str, Any]:
        phones = await self.repo.list_active_phones(user_id)
        return {
            "configured": self.verify is not None,
            "max_phones": MAX_PHONES_PER_ACCOUNT,
            "phones": [
                {"phone": p["phone_e164"], "verified_at": _iso(p["verified_at"]), "source": p["source"]}
                for p in phones
            ],
        }

    async def start_link(self, user_id: str, raw_phone: str) -> Dict[str, Any]:
        if self.verify is None:
            raise PhoneLinkError("not_configured")
        phone = normalize_e164(raw_phone)
        if phone is None:
            raise PhoneLinkError("invalid_number")
        linked = {p["phone_e164"] for p in await self.repo.list_active_phones(user_id)}
        if phone in linked:
            raise PhoneLinkError("already_linked")
        if len(linked) >= MAX_PHONES_PER_ACCOUNT:
            raise PhoneLinkError("too_many_phones")
        now = self._now()
        if await self.repo.count_starts(user_id=user_id, since=now - CHALLENGE_TTL) >= MAX_STARTS_PER_USER:
            raise PhoneLinkError("too_many_sends")
        if await self.repo.count_starts(phone_e164=phone, since=now - timedelta(hours=1)) >= MAX_STARTS_PER_NUMBER:
            raise PhoneLinkError("too_many_sends")
        try:
            provider_sid = await self.verify.start(phone)
        except TwilioVerifyError as exc:
            raise self._from_provider(exc) from exc
        challenge = await self.repo.create_challenge(
            user_id=user_id, phone_e164=phone, provider_sid=provider_sid,
            expires_at=now + CHALLENGE_TTL,
        )
        logger.info("phone_link_started user=%s phone=%s", user_id, mask_e164(phone))
        return {
            "challenge_id": str(challenge["id"]),
            "phone": phone,
            "expires_at": _iso(challenge["expires_at"]),
        }

    async def check_link(self, user_id: str, challenge_id: str, code: str) -> Dict[str, Any]:
        if self.verify is None:
            raise PhoneLinkError("not_configured")
        code = (code or "").replace(" ", "").strip()
        if not _CODE.match(code):
            raise PhoneLinkError("invalid_code")
        challenge = await self.repo.get_challenge(challenge_id, user_id=user_id)
        if challenge is None or challenge["status"] != "pending":
            raise PhoneLinkError("expired")
        if challenge["expires_at"] <= self._now():
            await self.repo.record_check(challenge_id, status="expired", attempted=False)
            raise PhoneLinkError("expired")
        if challenge["attempts"] >= MAX_CHECKS:
            await self.repo.record_check(challenge_id, status="failed", attempted=False)
            raise PhoneLinkError("too_many_checks")
        try:
            status = await self.verify.check(challenge["provider_sid"], code)
        except TwilioVerifyError as exc:
            error = self._from_provider(exc)
            if error.kind == "expired":
                await self.repo.record_check(challenge_id, status="expired")
            elif error.kind == "too_many_checks":
                await self.repo.record_check(challenge_id, status="failed")
            raise error from exc
        if status != "approved":
            await self.repo.record_check(challenge_id, status="pending")
            raise PhoneLinkError("invalid_code")
        phone = challenge["phone_e164"]
        try:
            binding = await self.repo.consume_and_link(
                user_id=user_id, phone_e164=phone, challenge_id=challenge_id,
            )
        except asyncpg.UniqueViolationError:
            # Possession is proven, so telling them the number is taken is
            # not an enumeration leak; the transaction rolled the bind back.
            await self.repo.record_check(challenge_id, status="conflict", consumed=True)
            raise PhoneLinkError("linked_elsewhere") from None
        logger.info(
            "phone_linked user=%s phone=%s version=%s",
            user_id, mask_e164(phone), binding["link_version"],
        )
        return {
            "phone": binding["phone_e164"],
            "verified_at": _iso(binding["verified_at"]),
            "link_version": binding["link_version"],
        }

    async def unlink(self, user_id: str, raw_phone: str) -> bool:
        phone = normalize_e164(raw_phone)
        linked = {p["phone_e164"] for p in await self.repo.list_active_phones(user_id)}
        if phone not in linked:
            raise PhoneLinkError("not_linked")
        if len(linked) == 1 and not await self.repo.account_email(user_id):
            raise PhoneLinkError("last_way_in")
        removed = await self.repo.unlink(user_id, phone)
        if removed:
            logger.info("phone_unlinked user=%s phone=%s", user_id, mask_e164(phone))
        return removed

    async def claim_for_channel(self, phone_e164: str, *, name: str, source: str) -> ChannelClaim:
        """The account a channel-authenticated number reaches, made on first
        contact: a phone-only account with the normal free tier, no signup."""
        binding = await self.repo.get_user_by_phone(phone_e164)
        if binding is not None:
            return ChannelClaim(user_id=str(binding["user_id"]), created=False)
        async with self.repo.claiming(phone_e164) as conn:
            binding = await self.repo.get_user_by_phone(phone_e164, conn=conn)
            if binding is not None:
                return ChannelClaim(user_id=str(binding["user_id"]), created=False)
            user_id = await self.repo.orphan_phone_user(conn, phone_e164)
            created = user_id is None
            if created:
                metadata = {"username": name or mask_e164(phone_e164), "signup_channel": source}
                if name:
                    metadata["name"] = name
                user = await self._admin().create_user(phone=phone_e164, phone_confirm=True, user_metadata=metadata)
                user_id = str(user["id"])
            await self.repo.bind_channel(conn, user_id=user_id, phone_e164=phone_e164, source=source)
        logger.info("phone_claimed user=%s phone=%s source=%s created=%s", user_id, mask_e164(phone_e164), source, created)
        return ChannelClaim(user_id=user_id, created=created)

    @staticmethod
    def _from_provider(exc: TwilioVerifyError) -> PhoneLinkError:
        if exc.kind == "provider":
            logger.error("twilio_verify_failed code=%s status=%s: %s", exc.code, exc.status, exc)
            return PhoneLinkError("provider", f"Phone verification failed: {exc}")
        return PhoneLinkError(exc.kind)


def default_service() -> PhoneIdentity:
    return PhoneIdentity(PhoneRepo(get_native_pool()), PlatformVerify.from_env())
