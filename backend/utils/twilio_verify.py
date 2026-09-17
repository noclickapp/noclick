"""Twilio Verify: proving possession of a phone number.

One client for two callers — the instance's own Verify service (phone linking,
credentials from the environment) and the Twilio node's start/check
operations (the user's credentials). Only a server-observed ``approved`` from
a check proves anything; a sent code, a ``pending`` result or a client-side
flag never does.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

VERIFY_API_BASE = "https://verify.twilio.com/v2"

# Twilio error code → what the caller should tell the user. Anything else is
# a provider problem, reported with Twilio's own words.
_KINDS = {
    60200: "invalid_number",   # invalid parameter (the To number)
    60205: "invalid_number",   # SMS not supported by landline
    60203: "too_many_sends",   # max send attempts for this number
    60212: "too_many_sends",   # too many concurrent requests for this number
    60202: "too_many_checks",  # max check attempts
    20404: "expired",          # no pending verification: expired or consumed
    20429: "rate_limited",
}


class TwilioVerifyError(Exception):
    def __init__(self, message: str, *, code: Optional[int] = None, status: Optional[int] = None):
        super().__init__(message)
        self.code = code
        self.status = status

    @property
    def kind(self) -> str:
        return _KINDS.get(self.code or 0, "provider")


async def _post(auth: Tuple[str, str], url: str, data: Dict[str, Any]) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            response = await client.post(url, auth=auth, data=data)
        except httpx.HTTPError as exc:
            raise TwilioVerifyError(f"Twilio Verify unreachable: {type(exc).__name__}") from exc
    if response.status_code >= 400:
        try:
            body = response.json()
        except ValueError:
            body = {}
        raise TwilioVerifyError(
            f"Twilio Verify error: {body.get('message') or response.text[:200]}",
            code=body.get("code"), status=response.status_code,
        )
    return response.json()


async def start_verification(
    auth: Tuple[str, str], service_sid: str, *, to: str, channel: str = "sms",
    locale: Optional[str] = None,
) -> Dict[str, Any]:
    """Send a code; returns Twilio's Verification resource (``sid``, ``status``)."""
    data: Dict[str, Any] = {"To": to, "Channel": channel}
    if locale:
        data["Locale"] = locale
    return await _post(auth, f"{VERIFY_API_BASE}/Services/{service_sid}/Verifications", data)


async def check_verification(
    auth: Tuple[str, str], service_sid: str, *, code: str, to: Optional[str] = None,
    verification_sid: Optional[str] = None,
) -> Dict[str, Any]:
    """Check a code against the number or, tighter, the exact verification
    that was started; returns the VerificationCheck resource (``status``)."""
    if not (to or verification_sid):
        raise ValueError("check_verification needs a number or a verification sid")
    data: Dict[str, Any] = {"Code": code}
    if verification_sid:
        data["VerificationSid"] = verification_sid
    else:
        data["To"] = to
    return await _post(auth, f"{VERIFY_API_BASE}/Services/{service_sid}/VerificationCheck", data)


class PlatformVerify:
    """The instance's own Verify service, used to link phones to accounts."""

    ENV_VARS = ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_VERIFY_SERVICE_SID")

    def __init__(self, account_sid: str, auth_token: str, service_sid: str):
        self._auth = (account_sid, auth_token)
        self._service_sid = service_sid

    @classmethod
    def from_env(cls) -> Optional["PlatformVerify"]:
        values = [os.getenv(name, "").strip() for name in cls.ENV_VARS]
        return cls(*values) if all(values) else None

    @classmethod
    def is_configured(cls) -> bool:
        return cls.from_env() is not None

    async def start(self, to: str) -> str:
        """Returns the verification sid the check must be bound to."""
        return (await start_verification(self._auth, self._service_sid, to=to))["sid"]

    async def check(self, verification_sid: str, code: str) -> str:
        """Returns Twilio's status: ``approved`` is the only proof."""
        result = await check_verification(
            self._auth, self._service_sid, code=code, verification_sid=verification_sid,
        )
        return str(result.get("status", ""))
