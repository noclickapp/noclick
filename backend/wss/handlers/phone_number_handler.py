"""Buying a phone number for a workflow: the number becomes a
``phone_number`` credential with a recurring charge, minted in one
transaction so a bought number is never left without an owner. Gated on the
phone_numbers rollout; the provider is a platform capability."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict, Optional

from billing.markup import CREDITS_PER_DOLLAR
from billing.recurring import start_connection_charge
from billing.usage_tracker import usage_tracker
from nodes.phone_node import PHONE_NUMBER_CREDENTIAL_TYPE, PHONE_NUMBER_MONTHLY_CREDITS
from repositories.credentials import create_credential_with_limit_check
from utils.capabilities import PHONE_NUMBERS, capability
from utils.database_pool import DatabasePoolMixin
from utils.encryption import get_encryption
from utils.feature_gates import FeatureNotAvailable, require_feature
from utils.phone_numbers import normalize_e164
from wss.receiver.client_events import PhoneNumberBuyRequest, PhoneNumberSearchRequest
from wss.schema import SocketIOHandler
from wss.sender import send_event
from wss.sender.events import ResponseEvent
from wss.sender.phone_responses import PhoneNumberBuyResponse, PhoneNumberSearchResponse

logger = logging.getLogger(__name__)

FEATURE = "phone_numbers"
CHARGE_TYPE = "phone_number"
COUNTRIES = ("US",)


class PhoneNumberError(ValueError):
    def __init__(self, message: str, kind: str):
        super().__init__(message)
        self.kind = kind


class PhoneNumberHandler(DatabasePoolMixin, SocketIOHandler):
    def __init__(self, sio):
        super().__init__(sio)
        self.encryption = get_encryption()

    def get_events(self) -> Dict[str, Callable]:
        return {
            "phone_number:search": self.handle_search,
            "phone_number:buy": self.handle_buy,
        }

    async def setup_user(self, sid: str) -> None:
        _ = sid

    async def _respond(self, sid: str, request_id: str, op: Callable[[Dict[str, Any]], Awaitable[Any]]) -> None:
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get("user_id") if session else None
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(request_id=request_id, data=None, error="Not authenticated"))
                return
            user_data = session.get("user_data") or {}
            require_feature(FEATURE, email=user_data.get("email"))
            if capability(PHONE_NUMBERS) is None:
                raise PhoneNumberError("Phone numbers cannot be bought on this instance.", "unavailable")
            data = await op({"user_id": user_id, "user_tier": user_data.get("subscription_tier", "free")})
            await send_event(self.sio, sid, ResponseEvent(request_id=request_id, data=data))
        except FeatureNotAvailable as e:
            await send_event(self.sio, sid, ResponseEvent(request_id=request_id, data={"kind": "gated"}, error=str(e)))
        except PhoneNumberError as e:
            await send_event(self.sio, sid, ResponseEvent(request_id=request_id, data={"kind": e.kind}, error=str(e)))
        except Exception as e:
            logger.error("[PhoneNumbers] request failed: %s", e, exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(request_id=request_id, data=None, error=str(e)))

    async def handle_search(self, sid: str, request: PhoneNumberSearchRequest) -> None:
        async def op(actor: Dict[str, Any]) -> Dict[str, Any]:
            country = (request.country or "US").upper()
            if country not in COUNTRIES:
                raise PhoneNumberError("Only US numbers can be bought right now.", "country")
            area_code = (request.area_code or "").strip() or None
            if area_code and not (area_code.isdigit() and len(area_code) == 3):
                raise PhoneNumberError("An area code is three digits.", "area_code")
            numbers = await capability(PHONE_NUMBERS).search(country, area_code, 5)
            return PhoneNumberSearchResponse(numbers=numbers, monthly_credits=PHONE_NUMBER_MONTHLY_CREDITS).model_dump()
        await self._respond(sid, request.request_id, op)

    async def handle_buy(self, sid: str, request: PhoneNumberBuyRequest) -> None:
        async def op(actor: Dict[str, Any]) -> Dict[str, Any]:
            e164 = normalize_e164(request.phone_number)
            if e164 is None:
                raise PhoneNumberError("That is not a valid phone number.", "number")
            result = await buy_number_for_user(
                await self.get_pool(), user_id=actor["user_id"], user_tier=actor["user_tier"],
                e164=e164, credential_name=request.credential_name, encryption=self.encryption,
            )
            return PhoneNumberBuyResponse(**result).model_dump()
        await self._respond(sid, request.request_id, op)


async def buy_number_for_user(pool, *, user_id: str, user_tier: str, e164: str,
                              credential_name: Optional[str], encryption) -> Dict[str, str]:
    """Buy at the provider, then mint the credential and its recurring charge
    in ONE transaction; a credential that cannot be written releases the
    number again, so nothing is ever billed to nobody. The first month must
    be affordable before anything is bought."""
    numbers = capability(PHONE_NUMBERS)
    if numbers is None:
        raise PhoneNumberError("Phone numbers cannot be bought on this instance.", "unavailable")
    billing_user = await usage_tracker.resolve_billing_user_id(user_id)
    remaining = await usage_tracker.fetch_credit_remaining(billing_user)
    if remaining is not None and remaining < PHONE_NUMBER_MONTHLY_CREDITS:
        raise PhoneNumberError(
            f"Buying a number needs {PHONE_NUMBER_MONTHLY_CREDITS} credits available for its first month; "
            f"you have {remaining:.1f}.", "credits",
        )
    bought = await numbers.buy(e164, label=f"NoClick {user_id[:8]}")
    blob = {"credential_type": PHONE_NUMBER_CREDENTIAL_TYPE, "phone_number": bought["phone_number"],
            "number_sid": bought["number_sid"]}
    metadata = {"provider": "twilio", "phone_number": bought["phone_number"], "number_sid": bought["number_sid"],
                "monthly_credits": PHONE_NUMBER_MONTHLY_CREDITS}
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                row, error = await create_credential_with_limit_check(
                    conn, user_id, user_tier, PHONE_NUMBER_CREDENTIAL_TYPE,
                    (credential_name or "").strip() or bought["phone_number"],
                    encryption.encrypt_credential(blob), metadata,
                )
                if error or row is None:
                    raise PhoneNumberError(error or "Could not save the number", "credential")
                await start_connection_charge(conn, user_id=user_id, credential_id=row["id"], charge_type=CHARGE_TYPE)
    except Exception:
        try:
            await numbers.release(bought["number_sid"])
        except Exception:
            logger.error("[PhoneNumbers] bought %s but could not save it AND could not release it", bought["number_sid"], exc_info=True)
        raise
    logger.info("[PhoneNumbers] user=%s bought %s (%s)", user_id, bought["phone_number"], bought["number_sid"])
    return {"credential_id": str(row["id"]), "phone_number": bought["phone_number"]}
