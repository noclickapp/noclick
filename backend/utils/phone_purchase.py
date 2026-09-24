"""Owner-approved phone purchases, carried by the existing credential request.

A durable claim precedes the provider call. An ambiguous provider outcome stays
claimed, so a timeout or retry cannot create another paid resource.
"""

from datetime import datetime, timedelta, timezone
import logging
from uuid import uuid4

from fastapi import HTTPException

from billing.plan_limits import get_user_tier_from_db
from nodes.phone_node import PHONE_NUMBER_MONTHLY_CREDITS
from repositories.credentials import CredentialsRepo
from repositories.users import get_user_email
from utils.capabilities import PHONE_NUMBERS, capability
from utils.encryption import get_encryption
from utils.feature_gates import require_feature
from utils.phone_numbers import PhonePurchaseRejected, normalize_e164
from wss.handlers.phone_number_handler import (
    PhoneNumberError, buy_number_for_user, is_local_number, search_numbers_for_user,
)

logger = logging.getLogger(__name__)


class PhonePurchase:
    def __init__(self, pool, user_id: str):
        self.pool = pool
        self.user_id = user_id
        self.repo = CredentialsRepo(pool)

    async def actor(self):
        async with self.pool.acquire() as conn:
            email = await get_user_email(conn, self.user_id)
            tier = await get_user_tier_from_db(conn, self.user_id)
        require_feature("phone_numbers", email=email)
        if capability(PHONE_NUMBERS) is None:
            raise PhoneNumberError("Phone numbers cannot be bought on this instance.", "unavailable")
        return tier

    async def request(self, token: str):
        row = await self.repo.phone_purchase_request(token, self.user_id)
        if row is None:
            raise HTTPException(404, "Purchase request not found for this account.")
        return row

    @staticmethod
    def view(row):
        status = row["status"]
        if status == "pending" and row["expires_at"] <= datetime.now(timezone.utc):
            status = "expired"
        quote = row["purchase_quote"]
        error = row["provision_error"]
        started = row["provisioning_started_at"]
        if status == "provisioning" and not error and (
            started is None or started < datetime.now(timezone.utc) - timedelta(minutes=2)
        ):
            error = "This purchase is taking longer than expected. Do not start another purchase; contact support to verify its outcome."
        return {
            "request_id": str(row["id"]), "status": status, "purpose": row["message"],
            "quote": quote, "credential_id": str(row["credential_id"]) if row["credential_id"] else None,
            "phone_number": quote["phone_number"] if quote else None,
            "error": error,
        }

    async def status(self, token):
        return self.view(await self.request(token))

    async def search(self, **kwargs):
        return await search_numbers_for_user(self.pool, user_id=self.user_id,
                                            user_tier=await self.actor(), **kwargs)

    async def quote(self, token, phone_number):
        row = await self.request(token)
        if self.view(row)["status"] != "pending":
            raise HTTPException(409, "This purchase request is no longer awaiting a selection.")
        e164 = normalize_e164(phone_number)
        if not e164 or not is_local_number(e164):
            raise PhoneNumberError("Choose a local US number from the search results.", "number")
        # A caller cannot quote a premium/international number or invent a price.
        found = await self.search(area_code=e164[2:5], contains=e164[-7:], limit=20)
        if not any(n["phone_number"] == e164 for n in found["numbers"]):
            raise PhoneNumberError("That number is no longer available. Choose another number.", "number")
        quote = {"id": str(uuid4()), "phone_number": e164,
                 "monthly_credits": PHONE_NUMBER_MONTHLY_CREDITS,
                 "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()}
        if not await self.repo.set_phone_quote(token, self.user_id, quote):
            raise HTTPException(409, "The request changed. Reload to see its status.")
        return {"quote": quote}

    async def confirm(self, token, quote_id):
        row = await self.request(token)
        if row["status"] in ("fulfilled", "provisioning"):
            return self.view(row)
        tier = await self.actor()
        claimed = await self.repo.claim_phone_purchase(token, self.user_id, quote_id, PHONE_NUMBER_MONTHLY_CREDITS)
        if claimed is None:
            current = await self.request(token)
            if current["status"] in ("fulfilled", "provisioning"):
                return self.view(current)
            raise HTTPException(409, "This price confirmation has expired or changed. Select the number again.")

        async def complete(conn, result):
            await self.repo.fulfill_phone_purchase(conn, str(claimed["id"]), result["credential_id"])

        try:
            await buy_number_for_user(
                self.pool, user_id=self.user_id, user_tier=tier,
                e164=claimed["purchase_quote"]["phone_number"], credential_name=None,
                encryption=get_encryption(), on_created=complete,
            )
        except Exception as exc:
            # Only a definitive rejection (or a failure before the provider call)
            # may re-open selection. Never retry an uncertain paid side effect.
            rejected = isinstance(exc, PhonePurchaseRejected) or (
                isinstance(exc, PhoneNumberError) and exc.kind in ("credits", "plan", "number", "unavailable")
            )
            message = str(exc) if rejected else (
                "We could not confirm the purchase outcome. Do not start another purchase; contact support to check this request."
            )
            logger.warning("Phone purchase %s failed; rejected=%s", claimed["id"], rejected, exc_info=True)
            await self.repo.record_phone_purchase_error(str(claimed["id"]), message, rejected=rejected)
        from utils.coordinator_links import dispatch_link
        dispatch_link(self.pool, "credential_request", claimed['id'])
        return await self.status(token)

    async def create(self, purpose: str, phone_number: str | None = None, *, continuation=None):
        if not purpose.strip() or len(purpose) > 1000:
            raise ValueError("Explain the intended use in 1–1000 characters.")
        await self.actor()
        row = await self.repo.upsert_credential_request(
            requester_id=self.user_id, target_email="", credential_type="phone_number", message=purpose.strip(),
            continuation=continuation,
        )
        current = await self.request(row.token)
        # Never overwrite the number/price the owner may already be reviewing.
        if phone_number and current["status"] == "pending" and not current["purchase_quote"]:
            await self.quote(row.token, phone_number)
        from mcp_adapter.auth.endpoints import get_frontend_url
        return {**await self.status(row.token),
                "auto_resume": continuation is not None,
                "approval_url": f"{get_frontend_url().rstrip('/')}/credential/purchase/{row.token}"}
