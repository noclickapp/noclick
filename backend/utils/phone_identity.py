"""Linking a phone number to a NoClick account by proving possession of it.

Web-first: the signed-in user asks for a code, Twilio Verify sends it, and
only Twilio's own ``approved`` verdict on the challenge minted for that exact
user and number binds the two. Caller id, a WhatsApp sender, a ``pending``
result or anything the client asserts never does. One live number per
account and one account per live number; a rebind bumps ``link_version`` so
work queued for the old binding can be told from the new one. Whether a
number belongs to someone else is disclosed only after possession is proven.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import asyncpg

from repositories.phones import PhoneRepo
from utils.database_pool import get_native_pool
from utils.phone_numbers import mask_e164, normalize_e164
from utils.twilio_verify import PlatformVerify, TwilioVerifyError

logger = logging.getLogger(__name__)

CHALLENGE_TTL = timedelta(minutes=10)  # Twilio Verify's default validity
MAX_STARTS_PER_USER = 3                # per CHALLENGE_TTL
MAX_STARTS_PER_NUMBER = 5              # per hour, across accounts
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
}


class PhoneLinkError(ValueError):
    def __init__(self, kind: str, message: Optional[str] = None):
        super().__init__(message or _MESSAGES[kind])
        self.kind = kind


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if isinstance(value, datetime) else value


class PhoneIdentity:
    def __init__(self, repo: PhoneRepo, verify: Optional[PlatformVerify]):
        self.repo = repo
        self.verify = verify

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    async def status(self, user_id: str) -> Dict[str, Any]:
        binding = await self.repo.get_active_phone(user_id)
        return {
            "configured": self.verify is not None,
            "phone": binding["phone_e164"] if binding else None,
            "verified_at": _iso(binding["verified_at"]) if binding else None,
            "link_version": binding["link_version"] if binding else None,
        }

    async def start_link(self, user_id: str, raw_phone: str) -> Dict[str, Any]:
        if self.verify is None:
            raise PhoneLinkError("not_configured")
        phone = normalize_e164(raw_phone)
        if phone is None:
            raise PhoneLinkError("invalid_number")
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

    async def unlink(self, user_id: str) -> bool:
        removed = await self.repo.unlink(user_id)
        if removed:
            logger.info("phone_unlinked user=%s", user_id)
        return removed

    @staticmethod
    def _from_provider(exc: TwilioVerifyError) -> PhoneLinkError:
        if exc.kind == "provider":
            logger.error("twilio_verify_failed code=%s status=%s: %s", exc.code, exc.status, exc)
            return PhoneLinkError("provider", f"Phone verification failed: {exc}")
        return PhoneLinkError(exc.kind)


def default_service() -> PhoneIdentity:
    return PhoneIdentity(PhoneRepo(get_native_pool()), PlatformVerify.from_env())
