"""Owner-approved phone purchases, carried by the existing credential request.

A durable claim precedes the provider call. An ambiguous provider outcome stays
claimed, so a timeout or retry cannot create another paid resource. A number
whose carrier reviews what was filed stays claimed while its order is in
review (the quote names the order): the request is fulfilled when the order
completes, and re-opened, with the carrier's reason, when it ends without the
number; one the carrier sends back is corrected and resubmitted here.
"""

from datetime import datetime, timedelta, timezone
import logging
from uuid import uuid4

from fastapi import HTTPException

from billing.plan_limits import get_user_tier_from_db
from billing.gates import GateDenied, check_product
from repositories.credentials import CredentialsRepo
from repositories.users import get_user_email
from utils.capabilities import PHONE_NUMBERS, capability
from utils.encryption import get_encryption
from utils.feature_gates import require_feature
from utils.phone_numbers import PhoneDocumentRefused, PhonePurchaseRejected
from wss.handlers.phone_number_handler import (
    PhoneNumberError, buy_number_for_user, check_requirements, document_upload_path, live_offer, number_price,
    priced_offers, resubmit_order, search_numbers_for_user,
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
        # A number the carrier is reviewing waits on its order, for days sometimes.
        ordered = status == "provisioning" and bool(quote and quote.get("order_id"))
        if status == "provisioning" and not error and not ordered and (
            started is None or started < datetime.now(timezone.utc) - timedelta(minutes=2)
        ):
            error = "This purchase is taking longer than expected. Do not start another purchase; contact support to verify its outcome."
        return {
            "request_id": str(row["id"]), "status": status, "purpose": row["message"],
            "quote": quote, "credential_id": str(row["credential_id"]) if row["credential_id"] else None,
            "phone_number": quote["phone_number"] if quote else None,
            "error": error, "order_id": quote["order_id"] if ordered else None,
        }

    async def status(self, token):
        return await self.status_of(await self.request(token))

    async def status_of(self, row):
        """The request; while its number's order is in the carrier's review, the order (in_review | rejected)."""
        view = self.view(row)
        if view["order_id"] is None:
            return view
        [order] = await priced_offers(self.user_id, [await capability(PHONE_NUMBERS).order(self.user_id,
                                                                                            view["order_id"])])
        return {**view, "status": order["status"], "order": order}

    async def search(self, **filters):
        await self.actor()
        return await search_numbers_for_user(user_id=self.user_id, **filters)

    async def quote(self, token, phone_number, *, country, number_type="local"):
        row = await self.request(token)
        if self.view(row)["status"] != "pending":
            raise HTTPException(409, "This purchase request is no longer awaiting a selection.")
        await self.actor()
        # A caller cannot quote a number that isn't for sale or invent a price: the number as it's for sale now
        # prices it.
        offer = await live_offer(phone_number, country=country, number_type=number_type)
        price = await number_price(self.user_id, offer)
        quote = {"id": str(uuid4()), "phone_number": offer["phone_number"], "country": offer["country"],
                 "number_type": offer["number_type"], "locality": offer["locality"], "region": offer["region"],
                 "capabilities": offer["capabilities"], "requirements": offer["requirements"],
                 "texting": offer["texting"], "monthly_credits": price.monthly_credits,
                 "upfront_credits": price.upfront_credits,
                 "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()}
        if not await self.repo.set_phone_quote(token, self.user_id, quote):
            raise HTTPException(409, "The request changed. Reload to see its status.")
        return {"quote": quote}

    async def confirm(self, token, quote_id, holder=None, answers=None):
        row = await self.request(token)
        if row["status"] in ("fulfilled", "provisioning"):
            return await self.status_of(row)
        tier = await self.actor()
        quote = row["purchase_quote"]
        if not quote or quote["id"] != quote_id:
            raise HTTPException(409, "This price confirmation has expired or changed. Select the number again.")
        offer = await live_offer(quote["phone_number"], country=quote["country"], number_type=quote["number_type"])
        check_requirements(offer, holder, answers)
        price = await number_price(self.user_id, offer)
        # The claim holds only while the number's price is still the quoted one.
        claimed = await self.repo.claim_phone_purchase(token, self.user_id, quote_id, price.monthly_credits,
                                                       price.upfront_credits)
        if claimed is None:
            current = await self.request(token)
            if current["status"] in ("fulfilled", "provisioning"):
                return await self.status_of(current)
            raise HTTPException(409, "This price confirmation has expired or changed. Select the number again.")

        async def complete(conn, result):
            await self.repo.fulfill_phone_purchase(conn, str(claimed["id"]), result["credential_id"])

        try:
            bought = await buy_number_for_user(
                self.pool, user_id=self.user_id, user_tier=tier, offer=offer, credential_name=None,
                encryption=get_encryption(), holder=holder, answers=answers, price=price, on_created=complete,
                origin={"kind": "link", "request_id": str(claimed["id"])},
            )
            if "order_id" in bought:
                await self.repo.set_phone_purchase_order(str(claimed["id"]), bought["order_id"])
        except Exception as exc:
            # Only a definitive rejection (or a failure before the provider call)
            # may re-open selection. Never retry an uncertain paid side effect.
            rejected = isinstance(exc, (PhonePurchaseRejected, PhoneDocumentRefused, GateDenied)) or (
                isinstance(exc, PhoneNumberError)
                and exc.kind in ("credits", "plan", "number", "unavailable", "address", "requirements", "steps",
                                 "price")
            )
            message = str(exc) if rejected else (
                "We could not confirm the purchase outcome. Do not start another purchase; contact support to check this request."
            )
            logger.warning("Phone purchase %s failed; rejected=%s", claimed["id"], rejected, exc_info=True)
            await self.repo.record_phone_purchase_error(str(claimed["id"]), message, rejected=rejected)
        from utils.coordinator_links import dispatch_link
        dispatch_link(self.pool, "credential_request", claimed['id'])
        return await self.status(token)

    async def resubmit(self, token, holder=None, answers=None):
        """Correct and resubmit what was filed for the request's number, which the carrier sent back."""
        view = self.view(await self.request(token))
        if view["order_id"] is None:
            raise HTTPException(409, "This purchase has nothing the carrier sent back.")
        await self.actor()
        await resubmit_order(self.user_id, view["order_id"], holder=holder, answers=answers)
        return await self.status(token)

    async def document_upload(self, *, country, number_type, requirement_id):
        """A link to upload a document for one of the number's requirements to."""
        await self.actor()
        return {"upload_url_path": document_upload_path(self.user_id, country=country, number_type=number_type,
                                                        requirement_id=requirement_id)}

    async def create(self, purpose: str, phone_number: str | None = None, *, country: str | None = None,
                     number_type: str = "local", continuation=None):
        if not purpose.strip() or len(purpose) > 1000:
            raise ValueError("Explain the intended use in 1–1000 characters.")
        tier = await self.actor()
        # An unquoted link must check the same prerequisites as a purchase, so an account short of the purchase
        # floor learns it needs funds before sign-in; a chosen number's own price counts too where it's more.
        projected = None
        if phone_number:
            projected = (await number_price(self.user_id, await live_offer(
                phone_number, country=country, number_type=number_type))).due_now
        await check_product(self.pool, "phone_numbers", user_id=self.user_id, personal_tier=tier,
                            projected_credits=projected)
        row = await self.repo.upsert_credential_request(
            requester_id=self.user_id, target_email="", credential_type="phone_number", message=purpose.strip(),
            continuation=continuation,
        )
        current = await self.request(row.token)
        # Never overwrite the number/price the owner may already be reviewing.
        if phone_number and current["status"] == "pending" and not current["purchase_quote"]:
            await self.quote(row.token, phone_number, country=country, number_type=number_type)
        from mcp_adapter.auth.endpoints import get_frontend_url
        return {**await self.status(row.token),
                "auto_resume": continuation is not None,
                "approval_url": f"{get_frontend_url().rstrip('/')}/credential/purchase/{row.token}"}
