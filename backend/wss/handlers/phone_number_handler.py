"""Buying a phone number for a workflow: the number becomes a
``phone_number`` credential with a recurring charge, minted in one
transaction so a bought number is never left without an owner. Gated on the
phone_numbers rollout; the provider is a platform capability (``PHONE_NUMBERS``),
which says where numbers are for sale, finds them, prices each one and buys it.

Each number has its own price: the provider's monthly and one-time costs for
it, priced for the paying account (``billing.recurring.charge_credits``). A
search shows that price and a purchase charges exactly it: the number is read
again just before it's bought, and a price that moved since the person saw it
refuses the purchase (``price``) with the new one. A country that asks who
holds a number before it's sold (an address on file, their contact
information) gets the holder's name, address and contact phone with the
purchase; one that asks for documents gets them too, uploaded first
(``document_upload_path``), and answers in text (``answers``, by requirement
id), and the carrier reviews them: the purchase leaves the number's order in
review, and the number is the account's, and charged, once the review
completes (the capability's ``orders``). One that asks a step that can't be
taken here (an identity check at the carrier's link, a company the carrier
approved first) can't be bought here yet (``steps``)."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import asdict, dataclass
from typing import Any, Awaitable, Callable, Dict, Mapping, Optional
from urllib.parse import quote

from billing.gates import GateDenied, check_product
from billing.recurring import charge_credits, start_connection_charge
from nodes.phone_node import PHONE_NUMBER_CHARGE_TYPE, PHONE_NUMBER_CREDENTIAL_TYPE, PHONE_NUMBER_SETUP_CHARGE_TYPE
from repositories.credentials import create_credential_with_limit_check
from repositories.phones import PhoneRepo
from utils.activity import signal_activity
from utils.capabilities import PHONE_NUMBERS, capability
from utils.database_pool import DatabasePoolMixin
from utils.encryption import get_encryption
from utils.feature_gates import FeatureNotAvailable, require_feature
from utils.phone_numbers import (
    CONTACT_KIND, DOCUMENT_KIND, TEXT_KIND, CoverageNotReady, PhoneDocumentRefused, PhoneOrderNotFound,
    normalize_e164,
)
from wss.receiver.client_events import (
    PhoneNumberBuyRequest, PhoneNumberCoverageRequest, PhoneNumberDocumentRemoveRequest,
    PhoneNumberDocumentUploadRequest, PhoneNumberDocumentsRequest, PhoneNumberOrdersRequest, PhoneNumberPlacesRequest,
    PhoneNumberResubmitRequest, PhoneNumberSearchRequest,
)
from wss.schema import SocketIOHandler
from wss.sender import send_event
from wss.sender.events import ResponseEvent
from wss.sender.phone_responses import (
    PhoneNumberBuyResponse, PhoneNumberCoverageResponse, PhoneNumberDocumentRemoveResponse,
    PhoneNumberDocumentUploadResponse, PhoneNumberDocumentsResponse, PhoneNumberOrdersResponse,
    PhoneNumberPlacesResponse, PhoneNumberResubmitResponse, PhoneNumberSearchResponse,
)

logger = logging.getLogger(__name__)

FEATURE = "phone_numbers"
# The kinds of number, as the providers name them.
NUMBER_TYPES = ("local", "mobile", "toll_free", "national", "shared_cost")
# What every result must do: take calls, or take calls and texts.
FEATURES = {"voice": ("voice",), "voice_sms": ("voice", "SMS")}
COUNTRY = re.compile(r"^[A-Z]{2}$")
# The provider matches a pattern of digits, letters (keypad-mapped) and * for any digit.
CONTAINS_PATTERN = re.compile(r"^[0-9A-Z*]{1,10}$")
DIGITS = re.compile(r"^[0-9]{1,10}$")
PLACE_MAX = 64
MAX_RESULTS = 30
# The requirements the holder's name, address and phone answer.
HOLDER_KINDS = ("address", CONTACT_KIND)
# A document is uploaded to a short-lived link of its own, signed for one account and requirement.
DOCUMENT_UPLOAD_AUDIENCE = "noclick-phone-document"
DOCUMENT_UPLOAD_TTL_S = 15 * 60
DOCUMENT_UPLOAD_PATH = "/api/phone-numbers/documents"


class PhoneNumberError(ValueError):
    """A refusal the person can act on; ``kind`` names what to change, ``details`` what they need to."""

    def __init__(self, message: str, kind: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.kind = kind
        self.details = details or {}


@dataclass(frozen=True)
class NumberPrice:
    """What a number charges, in credits: each month, and once when it's bought."""

    monthly_credits: float
    upfront_credits: float

    @property
    def due_now(self) -> float:
        return self.monthly_credits + self.upfront_credits


class PhoneNumberHandler(DatabasePoolMixin, SocketIOHandler):
    def __init__(self, sio):
        super().__init__(sio)
        self.encryption = get_encryption()

    def get_events(self) -> Dict[str, Callable]:
        return {
            "phone_number:coverage": self.handle_coverage,
            "phone_number:places": self.handle_places,
            "phone_number:search": self.handle_search,
            "phone_number:buy": self.handle_buy,
            "phone_number:documents": self.handle_documents,
            "phone_number:document_upload": self.handle_document_upload,
            "phone_number:document_remove": self.handle_document_remove,
            "phone_number:orders": self.handle_orders,
            "phone_number:resubmit": self.handle_resubmit,
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
            data = await op({"user_id": user_id, "user_tier": user_data.get("subscription_tier", "free"),
                             "pool": await self.get_pool()})
            await send_event(self.sio, sid, ResponseEvent(request_id=request_id, data=data))
        except PhoneDocumentRefused as e:
            await send_event(self.sio, sid, ResponseEvent(request_id=request_id, data={"kind": "document"},
                                                          error=str(e)))
        except FeatureNotAvailable as e:
            await send_event(self.sio, sid, ResponseEvent(request_id=request_id, data={"kind": "gated"}, error=str(e)))
        except PhoneNumberError as e:
            await send_event(self.sio, sid, ResponseEvent(request_id=request_id, data={"kind": e.kind, **e.details},
                                                          error=str(e)))
        except GateDenied as e:
            await send_event(self.sio, sid, ResponseEvent(request_id=request_id, data={"kind": e.kind}, error=str(e)))
        except Exception as e:
            logger.error("[PhoneNumbers] request failed: %s", e, exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(request_id=request_id, data=None, error=str(e)))

    async def handle_coverage(self, sid: str, request: PhoneNumberCoverageRequest) -> None:
        async def op(actor: Dict[str, Any]) -> Dict[str, Any]:
            return PhoneNumberCoverageResponse(countries=await sold_coverage(),
                                               contact_phone=await contact_phone(actor["pool"],
                                                                                 actor["user_id"])).model_dump()
        await self._respond(sid, request.request_id, op)

    async def handle_places(self, sid: str, request: PhoneNumberPlacesRequest) -> None:
        async def op(actor: Dict[str, Any]) -> Dict[str, Any]:
            country, number_type = _country(request.country), _number_type(request.number_type)
            places = await capability(PHONE_NUMBERS).places(country, number_type)
            return PhoneNumberPlacesResponse(places=places).model_dump()
        await self._respond(sid, request.request_id, op)

    async def handle_search(self, sid: str, request: PhoneNumberSearchRequest) -> None:
        async def op(actor: Dict[str, Any]) -> Dict[str, Any]:
            return await search_numbers_for_user(user_id=actor["user_id"],
                                                 **request.model_dump(exclude={"request_id"}))
        await self._respond(sid, request.request_id, op)

    async def handle_buy(self, sid: str, request: PhoneNumberBuyRequest) -> None:
        async def op(actor: Dict[str, Any]) -> Dict[str, Any]:
            offer = await live_offer(request.phone_number, country=request.country, number_type=request.number_type)
            result = await buy_number_for_user(
                actor["pool"], user_id=actor["user_id"], user_tier=actor["user_tier"], offer=offer,
                credential_name=request.credential_name, encryption=self.encryption,
                holder=request.holder.model_dump() if request.holder is not None else None, answers=request.answers,
                expected=(NumberPrice(request.monthly_credits, request.upfront_credits)
                          if request.monthly_credits is not None and request.upfront_credits is not None else None),
            )
            return PhoneNumberBuyResponse(**result).model_dump(exclude_none=True)
        await self._respond(sid, request.request_id, op)

    async def handle_documents(self, sid: str, request: PhoneNumberDocumentsRequest) -> None:
        async def op(actor: Dict[str, Any]) -> Dict[str, Any]:
            documents = await capability(PHONE_NUMBERS).documents(actor["user_id"])
            return PhoneNumberDocumentsResponse(documents=documents).model_dump()
        await self._respond(sid, request.request_id, op)

    async def handle_document_upload(self, sid: str, request: PhoneNumberDocumentUploadRequest) -> None:
        async def op(actor: Dict[str, Any]) -> Dict[str, Any]:
            path = document_upload_path(actor["user_id"], country=request.country, number_type=request.number_type,
                                        requirement_id=request.requirement_id)
            return PhoneNumberDocumentUploadResponse(upload_url_path=path).model_dump()
        await self._respond(sid, request.request_id, op)

    async def handle_document_remove(self, sid: str, request: PhoneNumberDocumentRemoveRequest) -> None:
        async def op(actor: Dict[str, Any]) -> Dict[str, Any]:
            removed = await capability(PHONE_NUMBERS).remove_document(actor["user_id"], request.document_id)
            return PhoneNumberDocumentRemoveResponse(**removed).model_dump()
        await self._respond(sid, request.request_id, op)

    async def handle_orders(self, sid: str, request: PhoneNumberOrdersRequest) -> None:
        async def op(actor: Dict[str, Any]) -> Dict[str, Any]:
            orders = await capability(PHONE_NUMBERS).orders(actor["user_id"])
            return PhoneNumberOrdersResponse(orders=await priced_offers(actor["user_id"], orders)).model_dump()
        await self._respond(sid, request.request_id, op)

    async def handle_resubmit(self, sid: str, request: PhoneNumberResubmitRequest) -> None:
        async def op(actor: Dict[str, Any]) -> Dict[str, Any]:
            order = await resubmit_order(actor["user_id"], request.order_id,
                                         holder=request.holder.model_dump() if request.holder is not None else None,
                                         answers=request.answers)
            [priced] = await priced_offers(actor["user_id"], [order])
            return PhoneNumberResubmitResponse(order=priced).model_dump()
        await self._respond(sid, request.request_id, op)


# ── what a search asks ──────────────────────────────────────────────────────


def _country(value: Optional[str]) -> str:
    country = (value or "").strip().upper()
    if not COUNTRY.fullmatch(country):
        raise PhoneNumberError("A country is its two-letter code, like US or GB.", "country")
    return country


def _number_type(value: Optional[str]) -> str:
    if value not in NUMBER_TYPES:
        raise PhoneNumberError(f"A number is one of these kinds: {', '.join(NUMBER_TYPES)}.", "number_type")
    return value


def _digits(value: Optional[str], field: str) -> Optional[str]:
    digits = re.sub(r"[\s\-().]", "", value or "") or None
    if digits is not None and not DIGITS.fullmatch(digits):
        raise PhoneNumberError(f"{field.replace('_', ' ').capitalize()} is up to 10 digits.", field)
    return digits


def _place(value: Optional[str], field: str) -> Optional[str]:
    place = (value or "").strip() or None
    if place is not None and len(place) > PLACE_MAX:
        raise PhoneNumberError(f"A {field} is up to {PLACE_MAX} characters.", field)
    return place


def number_query(*, country: Optional[str], number_type: str = "local", area_code: Optional[str] = None,
                 locality: Optional[str] = None, region: Optional[str] = None, contains: Optional[str] = None,
                 starts_with: Optional[str] = None, ends_with: Optional[str] = None, features: str = "voice",
                 limit: int = 10) -> Dict[str, Any]:
    """A search the provider takes, checked field by field (``PhoneNumberError`` names the one that's wrong)."""
    pattern = (contains or "").strip().upper().replace(" ", "").replace("-", "") or None
    if pattern and not CONTAINS_PATTERN.fullmatch(pattern):
        raise PhoneNumberError("A pattern is up to 10 digits, letters or * wildcards.", "pattern")
    if features not in FEATURES:
        raise PhoneNumberError("Search for numbers that take calls (voice), or calls and texts (voice_sms).",
                               "features")
    if not 1 <= limit <= MAX_RESULTS:
        raise PhoneNumberError(f"Ask for 1 to {MAX_RESULTS} numbers.", "limit")
    return {
        "country": _country(country), "number_type": _number_type(number_type),
        "area_code": _digits(area_code, "area_code"), "locality": _place(locality, "locality"),
        "region": _place(region, "region"), "contains": pattern, "starts_with": _digits(starts_with, "starts_with"),
        "ends_with": _digits(ends_with, "ends_with"), "features": FEATURES[features], "limit": limit,
    }


# ── prices ──────────────────────────────────────────────────────────────────


async def number_price(user_id: str, offer: Dict[str, Any]) -> NumberPrice:
    """What ``offer`` charges this account, in credits, at the platform's price for its plan."""
    return NumberPrice(
        monthly_credits=await charge_credits(user_id, PHONE_NUMBER_CHARGE_TYPE, offer["monthly_usd"]),
        upfront_credits=await charge_credits(user_id, PHONE_NUMBER_SETUP_CHARGE_TYPE, offer["upfront_usd"]),
    )


async def priced_offers(user_id: str, offers) -> list:
    """Each offer with its price for this account (``monthly_credits``, ``upfront_credits``)."""
    prices: Dict[tuple, NumberPrice] = {}
    out = []
    for offer in offers:
        key = (offer["monthly_usd"], offer["upfront_usd"])
        if key not in prices:
            prices[key] = await number_price(user_id, offer)
        out.append({**offer, **asdict(prices[key])})
    return out


async def _gate(pool, user_id: str, user_tier: str, *, projected_credits: Optional[float] = None) -> None:
    """The product gate's balance floor on any plan, and for a purchase what
    it charges now where that's more."""
    # Preserve the typed denial and its offer so every caller can guide the
    # owner through the same add-funds flow.
    await check_product(pool, "phone_numbers", user_id=user_id, personal_tier=user_tier,
                        projected_credits=projected_credits)


async def sold_coverage() -> list:
    """Where numbers are for sale (the capability's ``coverage()``), refused while it's still being found out."""
    try:
        return await capability(PHONE_NUMBERS).coverage()
    except CoverageNotReady as exc:
        raise PhoneNumberError(str(exc), "not_ready") from exc


async def search_offers(**filters) -> list:
    """Numbers for sale matching ``filters`` (``number_query``'s), as the provider offers them. Browsing is
    free: the balance floor is a purchase's (``_gate``)."""
    numbers = capability(PHONE_NUMBERS)
    if numbers is None:
        raise PhoneNumberError("Phone numbers cannot be bought on this instance.", "unavailable")
    return await numbers.search(number_query(**filters))


def searched(filters: Mapping[str, Any], found: int) -> Dict[str, Any]:
    """A search as the activity feed names it: what was asked for, as the provider was asked, and how many came back."""
    query = number_query(**filters)
    asked = ("country", "number_type", "area_code", "locality", "region", "contains", "starts_with", "ends_with")
    return {**{k: query[k] for k in asked if query.get(k)}, "found": found}


async def search_numbers_for_user(*, user_id, **filters) -> Dict[str, Any]:
    """Numbers for sale matching ``filters``, each with its price for this account,
    and the one monthly price they share where they do (the old plans' flat price)."""
    offers = await search_offers(**filters)
    signal_activity(user_id, "search.numbers", searched(filters, len(offers)), key="search:numbers")
    numbers = await priced_offers(user_id, offers)
    monthly = {n["monthly_credits"] for n in numbers}
    return PhoneNumberSearchResponse(numbers=numbers,
                                     monthly_credits=monthly.pop() if len(monthly) == 1 else None).model_dump()


# ── buying ──────────────────────────────────────────────────────────────────


async def live_offer(phone_number: str, *, country: str, number_type: str) -> Dict[str, Any]:
    """``phone_number`` as it's for sale now, refused when it isn't or can't be bought here."""
    numbers = capability(PHONE_NUMBERS)
    if numbers is None:
        raise PhoneNumberError("Phone numbers cannot be bought on this instance.", "unavailable")
    e164 = normalize_e164(phone_number)
    if e164 is None:
        raise PhoneNumberError("That is not a valid phone number.", "number")
    offer = await numbers.offer(e164, country=_country(country), number_type=_number_type(number_type))
    if offer is None:
        raise PhoneNumberError("That number is no longer for sale. Search again and choose another.", "number")
    if offer["requirements"]["needs"] == "steps":
        named = "; ".join(r["name"] for r in offer["requirements"]["items"]
                          if r["kind"] not in (*HOLDER_KINDS, TEXT_KIND, DOCUMENT_KIND) and r["name"])
        raise PhoneNumberError(
            "Numbers like this one ask for a step that can't be taken here yet"
            + (f" ({named})" if named else "") + ". Choose a number that doesn't.", "steps")
    return offer


def check_requirements(offer: Mapping[str, Any], holder: Optional[Dict[str, Any]],
                       answers: Optional[Mapping[str, str]] = None) -> None:
    """Refuse a purchase without what ``offer``'s country asks (``offer`` or an
    order: anything with its ``requirements``): the holder's name and address
    where it asks who holds it, and a phone where it asks for their contact
    information (``address``); an answer to each textual requirement, one of
    its ``values`` where it lists them, and a document for each document
    requirement (``requirements``, naming it in ``details.requirement_id``)."""
    items = offer["requirements"]["items"]
    if any(r["kind"] in HOLDER_KINDS for r in items):
        if holder is None:
            raise PhoneNumberError("This number's country asks who holds it before it's sold: add the "
                                   "holder's name and address.", "address")
        if not holder.get("phone") and any(r["kind"] == CONTACT_KIND for r in items):
            raise PhoneNumberError("This number's country asks for a phone to contact its holder on: add one.",
                                   "address")
    answers = answers or {}
    asked = {r["id"]: r for r in items if r["kind"] in (TEXT_KIND, DOCUMENT_KIND)}
    unknown = set(answers) - set(asked)
    if unknown:
        raise PhoneNumberError("That answers something this number's country doesn't ask.", "requirements",
                               details={"requirement_id": sorted(unknown)[0]})
    for requirement in asked.values():
        answer = answers.get(requirement["id"])
        if requirement["kind"] == DOCUMENT_KIND and not answer:
            raise PhoneNumberError(f"Add a document for “{requirement['name']}”.", "requirements",
                                   details={"requirement_id": requirement["id"]})
        if requirement["kind"] == TEXT_KIND and not answer:
            raise PhoneNumberError(f"Answer “{requirement['name']}”.", "requirements",
                                   details={"requirement_id": requirement["id"]})
        if requirement["kind"] == TEXT_KIND and requirement["values"] and answer not in requirement["values"]:
            raise PhoneNumberError(f"“{requirement['name']}” is one of: {', '.join(requirement['values'])}.",
                                   "requirements", details={"requirement_id": requirement["id"]})


def _holder_asked(subject: Mapping[str, Any], holder: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """``holder`` where ``subject``'s country asks who holds the number; None where it doesn't."""
    return holder if any(r["kind"] in HOLDER_KINDS for r in subject["requirements"]["items"]) else None


def document_upload_path(user_id: str, *, country: str, number_type: str, requirement_id: str) -> str:
    """Where the account uploads a document for one of ``country``'s requirements for its numbers of
    ``number_type``: a path on the backend's origin, signed for ``DOCUMENT_UPLOAD_TTL_S``; the file's bytes are
    POSTed to it with ``&filename=``."""
    import jwt

    from mcp_adapter.auth.tokens import get_mcp_signing_key

    token = jwt.encode({"aud": DOCUMENT_UPLOAD_AUDIENCE, "exp": int(time.time()) + DOCUMENT_UPLOAD_TTL_S,
                        "sub": user_id, "country": _country(country), "type": _number_type(number_type),
                        "requirement": requirement_id}, get_mcp_signing_key(), algorithm="HS256")
    return f"{DOCUMENT_UPLOAD_PATH}?token={quote(token)}"


def document_upload_claims(token: str) -> Optional[Dict[str, str]]:
    """``{user_id, country, number_type, requirement_id}`` for a valid, unexpired upload link's token."""
    import jwt

    from mcp_adapter.auth.tokens import get_mcp_signing_key

    try:
        claims = jwt.decode(token, get_mcp_signing_key(), algorithms=["HS256"], audience=DOCUMENT_UPLOAD_AUDIENCE)
    except jwt.PyJWTError:
        return None
    return {"user_id": claims["sub"], "country": claims["country"], "number_type": claims["type"],
            "requirement_id": claims["requirement"]}


async def resubmit_order(user_id: str, order_id: str, *, holder: Optional[Dict[str, Any]],
                         answers: Optional[Mapping[str, str]]) -> Dict[str, Any]:
    """File corrected answers for one of the account's orders the carrier sent back (``check_requirements``)."""
    numbers = capability(PHONE_NUMBERS)
    if numbers is None:
        raise PhoneNumberError("Phone numbers cannot be bought on this instance.", "unavailable")
    try:
        order = await numbers.order(user_id, order_id)
    except PhoneOrderNotFound:
        raise PhoneNumberError("No order of this account has that id.", "order") from None
    if order["status"] != "rejected":
        raise PhoneNumberError("Only an order the carrier sent back can be resubmitted.", "order")
    check_requirements(order, holder, answers)
    return await numbers.resubmit(user_id, order_id, holder=_holder_asked(order, holder), answers=answers or {})


async def contact_phone(pool, user_id: str) -> Optional[str]:
    """The account's own verified phone (the one it last reached NoClick from), to offer as a holder's contact."""
    phone = await PhoneRepo(pool).get_reach_phone(user_id)
    return phone["phone_e164"] if phone else None


async def buy_number_for_user(pool, *, user_id: str, user_tier: str, offer: Dict[str, Any],
                              credential_name: Optional[str], encryption,
                              holder: Optional[Dict[str, Any]] = None, answers: Optional[Mapping[str, str]] = None,
                              expected: Optional[NumberPrice] = None, price: Optional[NumberPrice] = None,
                              on_created=None, origin: Optional[Mapping[str, Any]] = None) -> Dict[str, str]:
    """Buy ``offer`` (``live_offer``: the number as it's for sale now) at the
    provider, then make the number the user's (``hold_number_for_user``); a
    number that cannot be recorded is released again, so nothing is ever
    billed to nobody. ``expected`` (what the person agreed to) must still be
    its price for this account, and the balance must hold the purchase floor
    and what it charges now (``_gate``). ``price`` is the caller's own price
    for it, where the caller sells it (the platform API); ``holder`` and ``answers`` what its country
    asks (``check_requirements``). Where the carrier reviews what was filed,
    nothing is held or charged yet: ``{order_id, phone_number, status}``, an
    order the provider finishes as ``origin`` says (``{"kind": "app"}``, a
    purchase link's ``{"kind": "link", "request_id"}``, or a platform's own)
    once the review completes; ``on_created`` is the same for a number bought
    at once."""
    check_requirements(offer, holder, answers)
    charged = price or await number_price(user_id, offer)
    if expected is not None and (round(expected.monthly_credits, 4), round(expected.upfront_credits, 4)) != (
            round(charged.monthly_credits, 4), round(charged.upfront_credits, 4)):
        raise PhoneNumberError("This number's price changed since it was shown. Review the new price and buy it "
                               "again.", "price", details=asdict(charged))
    await _gate(pool, user_id, user_tier, projected_credits=charged.due_now)
    numbers = capability(PHONE_NUMBERS)
    bought = await numbers.buy(offer, label=f"NoClick {user_id[:8]}", user_id=user_id,
                               holder=_holder_asked(offer, holder), answers=answers or {},
                               credential_name=credential_name, origin=origin or {"kind": "app"})
    if "order_id" in bought:
        logger.info("[PhoneNumbers] user=%s ordered %s, in the carrier's review (order %s)", user_id,
                    bought["phone_number"], bought["order_id"])
        return bought
    try:
        held = await hold_number_for_user(pool, user_id=user_id, user_tier=user_tier, held=bought,
                                          credential_name=credential_name, encryption=encryption,
                                          period_usd=offer["monthly_usd"], upfront_usd=offer["upfront_usd"],
                                          on_created=on_created)
    except Exception:
        try:
            await numbers.release(bought["number_sid"])
        except Exception:
            logger.error("[PhoneNumbers] bought %s but could not save it AND could not release it", bought["number_sid"], exc_info=True)
        raise
    logger.info("[PhoneNumbers] user=%s bought %s (%s)", user_id, bought["phone_number"], bought["number_sid"])
    if not (origin or {}).get("tenant_id"):  # a platform user's number is theirs to tell of, not the account's
        signal_activity(user_id, "buy.number", {"number": held["phone_number"], "monthly_usd": offer["monthly_usd"],
                                                "upfront_usd": offer["upfront_usd"]})
    return held


async def hold_number_for_user(pool, *, user_id: str, user_tier: str, held: Dict[str, str],
                               credential_name: Optional[str], encryption, period_usd, upfront_usd=0,
                               on_created=None) -> Dict[str, str]:
    """Make a number the provider now holds for the platform (``held``: the
    capability's ``{number_sid, phone_number, provider}``, bought or moved in)
    the user's: mint the credential and charge its first month (and its
    one-time cost) in ONE transaction (the provider bills a month in advance,
    and so do we: the charge renews on each anniversary while the number is
    kept). ``period_usd`` and ``upfront_usd`` are the provider's prices for
    this number. ``on_created`` records the number first, so its charge can
    price it by who holds it."""
    blob = {"credential_type": PHONE_NUMBER_CREDENTIAL_TYPE, "phone_number": held["phone_number"],
            "number_sid": held["number_sid"]}
    metadata = {"provider": held["provider"], "phone_number": held["phone_number"], "number_sid": held["number_sid"]}
    async with pool.acquire() as conn:
        async with conn.transaction():
            row, error = await create_credential_with_limit_check(
                conn, user_id, user_tier, PHONE_NUMBER_CREDENTIAL_TYPE,
                (credential_name or "").strip() or held["phone_number"],
                encryption.encrypt_credential(blob), metadata,
            )
            if error or row is None:
                from billing.plan_limits import plans_lifting

                raise PhoneNumberError(error or "Could not save the number", "credential",
                                       {"plans": list(await plans_lifting(conn, user_id, "credentials_per_type"))})
            if on_created is not None:
                await on_created(conn, {"credential_id": str(row["id"]), "phone_number": held["phone_number"]})
            await start_connection_charge(conn, user_id=user_id, credential_id=row["id"],
                                          charge_type=PHONE_NUMBER_CHARGE_TYPE, period_usd=period_usd,
                                          upfront_usd=upfront_usd)
    return {"credential_id": str(row["id"]), "phone_number": held["phone_number"]}
