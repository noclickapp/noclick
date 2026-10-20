"""Buying a number: affordable first, bought at the provider at the price the
person saw, then credential and recurring charge in one transaction — a
credential that cannot be saved gives the number back."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from billing.markup import CREDITS_PER_DOLLAR
from billing.usage_tracker import usage_tracker

from tests.fixtures.activity_fixtures import activity_signals  # noqa: F401
from tests.mocks.mock_asyncpg import MockNativePool
from utils import capabilities
from utils.capabilities import PHONE_NUMBERS, provide
from repositories.phones import PhoneRepo
from wss.handlers import phone_number_handler as h
from wss.receiver.client_events import PhoneNumberHolder

USER = "11111111-1111-1111-1111-111111111111"
CONTACT = "Contact Information (Name, Business Name, Phone Number)"


def _asked(id, kind, name, values=()):
    return {"id": id, "kind": kind, "name": name, "description": "", "example": "", "values": list(values)}


HOLDER_ASKS = [_asked("r-address", "address", "Worldwide Physical Address"), _asked("r-contact", "contact", CONTACT)]
# Italy's local numbers (Telnyx, read live 2026-10-10): who holds it, which identity document, and the document.
DOCUMENT_ASKS = HOLDER_ASKS + [_asked("r-type", "textual", "Identity Document Type",
                                      ("Identity card", "Driving license", "Passport", "Other")),
                               _asked("r-id", "document", "Identity Document")]


def offer(number="+15674833618", *, country="US", number_type="local", monthly="1.00", upfront="1.00",
          needs="none"):
    items = {"none": [], "address": HOLDER_ASKS, "documents": DOCUMENT_ASKS,
             "steps": [_asked("r-onfido", "step", "Onfido Verification Link - End User")]}[needs]
    return {"phone_number": number, "country": country, "number_type": number_type, "locality": "Lucas",
            "region": "OH", "capabilities": ["voice", "SMS"], "monthly_usd": monthly, "upfront_usd": upfront,
            "requirements": {"needs": needs, "items": items}, "texting": "registration"}


@pytest.fixture(autouse=True)
def _own_capabilities():
    saved = dict(capabilities._providers)
    capabilities.clear()
    yield
    capabilities.clear()
    capabilities._providers.update(saved)


def usd(dollars: float) -> float:
    """Dollars in the credits the gate reads."""
    return dollars * float(CREDITS_PER_DOLLAR)


async def funds_as_modeled(conn, payer):
    """The funds a purchase reads (``billing.gates.funds_usd``): the balance these tests model, in dollars."""
    from decimal import Decimal

    return Decimal(str(usage_tracker.fetch_credit_remaining.return_value)) / CREDITS_PER_DOLLAR


@pytest.fixture
def seams(monkeypatch):
    numbers = MagicMock()
    numbers.buy = AsyncMock(return_value={"number_sid": "PN1", "phone_number": "+15674833618", "provider": "carrier-a"})
    numbers.release = AsyncMock()
    numbers.search = AsyncMock(return_value=[offer(), offer("+15674833619", monthly="1.50", upfront="0.00")])
    numbers.offer = AsyncMock(side_effect=lambda number, country, number_type: offer(number, country=country,
                                                                                      number_type=number_type))
    numbers.coverage = AsyncMock(return_value=[{"country": "US", "number_types": ["local"], "texting_types": ["local"]}])
    numbers.places = AsyncMock(return_value=[{"kind": "area_code", "value": "567", "region": "OH"}])
    provide(PHONE_NUMBERS, numbers)
    monkeypatch.setattr("billing.plan_limits.registered_plan_limits", lambda: object())  # plans exist (hosted)
    monkeypatch.setattr("billing.plan_limits.get_effective_tier", AsyncMock(side_effect=lambda conn, uid, tier: tier))
    monkeypatch.setattr(usage_tracker, "resolve_billing_user_id", AsyncMock(return_value=USER))
    monkeypatch.setattr(usage_tracker, "fetch_credit_remaining", AsyncMock(return_value=40.0))
    monkeypatch.setattr(usage_tracker, "spend_cap_refusal", AsyncMock(return_value=None))  # no monthly cap
    monkeypatch.setattr("billing.gates.funds_usd", funds_as_modeled)
    created = AsyncMock(return_value=({"id": "cred-1"}, None))
    charge = AsyncMock()
    monkeypatch.setattr(h, "create_credential_with_limit_check", created)
    monkeypatch.setattr(h, "start_connection_charge", charge)

    # Each charge at 3x its vendor price, 4 credits a dollar (the old plans; per-account pricing:
    # test_free_member_postgres.py).
    async def credits(user_id, charge_type, vendor_usd):
        return round(float(vendor_usd) * 12, 4)

    monkeypatch.setattr(h, "charge_credits", AsyncMock(side_effect=credits))
    enc = MagicMock(); enc.encrypt_credential = lambda blob: f"enc:{blob['number_sid']}"
    return numbers, created, charge, enc


async def _buy(pool, numbers, enc, *, tier="pro", number="+15674833618", expected=None, **kwargs):
    found = await h.live_offer(number, country=kwargs.pop("country", "US"),
                               number_type=kwargs.pop("number_type", "local"))
    return await h.buy_number_for_user(pool, user_id=USER, user_tier=tier, offer=found, credential_name=None,
                                       encryption=enc, expected=expected, **kwargs)


async def test_buy_mints_credential_and_charges_the_numbers_own_price_together(seams):
    numbers, created, charge, enc = seams
    out = await _buy(MockNativePool(), numbers, enc, expected=h.NumberPrice(12, 12))
    assert out == {"credential_id": "cred-1", "phone_number": "+15674833618"}
    numbers.offer.assert_awaited_once_with("+15674833618", country="US", number_type="local")
    assert numbers.buy.await_args.args[0]["phone_number"] == "+15674833618"
    assert numbers.buy.await_args.kwargs == {"label": f"NoClick {USER[:8]}", "user_id": USER, "holder": None,
                                             "answers": {}, "credential_name": None, "origin": {"kind": "app"}}
    args = created.await_args.args
    assert args[1:4] == (USER, "pro", "phone_number") and args[4] == "+15674833618" and args[5] == "enc:PN1"
    assert args[6] == {"provider": "carrier-a", "phone_number": "+15674833618", "number_sid": "PN1"}
    assert charge.await_args.kwargs == {"user_id": USER, "credential_id": "cred-1", "charge_type": "phone_number",
                                        "period_usd": "1.00", "upfront_usd": "1.00"}
    numbers.release.assert_not_awaited()


async def test_a_price_that_moved_since_it_was_shown_buys_nothing(seams):
    numbers, created, _, enc = seams
    with pytest.raises(h.PhoneNumberError) as exc:
        await _buy(MockNativePool(), numbers, enc, expected=h.NumberPrice(12, 0))
    assert exc.value.kind == "price" and exc.value.details == {"monthly_credits": 12, "upfront_credits": 12}
    numbers.buy.assert_not_awaited(); created.assert_not_awaited()


async def test_what_it_charges_now_must_be_affordable_before_anything_is_bought(seams):
    numbers, created, _, enc = seams
    usage_tracker.fetch_credit_remaining.return_value = usd(5)  # a month's $3, not the $6 due now
    with pytest.raises(h.GateDenied) as exc:
        await _buy(MockNativePool(), numbers, enc, tier="plus", price=h.NumberPrice(usd(3), usd(3)))
    assert exc.value.kind == "credits"
    assert str(exc.value) == ("Buying phone numbers needs $6 of funds the account added (included usage doesn't "
                              "count); it has $5.")
    numbers.buy.assert_not_awaited(); created.assert_not_awaited()


async def test_a_caller_prices_the_number_and_records_it_before_its_charge(seams):
    numbers, created, charge, enc = seams
    order = []
    charge.side_effect = lambda *a, **k: order.append("charge")

    async def record(conn, held):
        order.append("record")

    usage_tracker.fetch_credit_remaining.return_value = 22.0  # short of the app's 24 credits; the floor's 20 and 10
    await _buy(MockNativePool(), numbers, enc, on_created=record, price=h.NumberPrice(5, 5))
    # The charge can price the number by who holds it.
    assert order == ["record", "charge"]


async def test_a_country_that_asks_who_holds_it_gets_them_and_one_that_asks_a_step_is_refused(seams):
    numbers, created, _, enc = seams
    holder = {"name": "Dana Ruiz", "street": "Keizersgracht 1", "city": "Amsterdam", "postal_code": "1015 CJ",
              "country": "NL"}
    numbers.offer.side_effect = lambda number, country, number_type: offer(number, country=country,
                                                                           number_type=number_type, needs="address")
    with pytest.raises(h.PhoneNumberError) as exc:
        await _buy(MockNativePool(), numbers, enc, number="+31612345678", country="NL", number_type="mobile")
    assert exc.value.kind == "address" and "name and address" in str(exc.value)
    # Its contact requirement asks for a phone too.
    with pytest.raises(h.PhoneNumberError) as exc:
        await _buy(MockNativePool(), numbers, enc, number="+31612345678", country="NL", number_type="mobile",
                   holder=holder)
    assert exc.value.kind == "address" and "phone" in str(exc.value)
    numbers.buy.assert_not_awaited()
    holder["phone"] = "+31612345670"
    await _buy(MockNativePool(), numbers, enc, number="+31612345678", country="NL", number_type="mobile",
               holder=holder)
    assert numbers.buy.await_args.kwargs["holder"] == holder
    numbers.offer.side_effect = lambda number, country, number_type: offer(number, country=country,
                                                                           number_type=number_type, needs="steps")
    numbers.buy.reset_mock()
    with pytest.raises(h.PhoneNumberError) as exc:
        await _buy(MockNativePool(), numbers, enc, number="+919812345678", country="IN", number_type="mobile")
    assert exc.value.kind == "steps" and "Onfido Verification Link" in str(exc.value)
    numbers.buy.assert_not_awaited()


HOLDER = {"name": "Giulia Rossi", "street": "Via Roma 1", "city": "Milano", "postal_code": "20121", "country": "IT",
          "phone": "+393471234567"}


async def test_a_number_that_asks_for_documents_needs_each_answered_before_anything_is_bought(seams):
    numbers, created, _, enc = seams
    numbers.offer.side_effect = lambda number, country, number_type: offer(number, country=country,
                                                                           number_type=number_type, needs="documents")
    answers = {"r-type": "Passport", "r-id": "doc-1"}
    for given, kind, named in (({"r-type": "Passport"}, "requirements", "r-id"),
                               ({"r-id": "doc-1"}, "requirements", "r-type"),
                               ({**answers, "r-type": "Library card"}, "requirements", "r-type"),
                               ({**answers, "r-other": "x"}, "requirements", "r-other")):
        with pytest.raises(h.PhoneNumberError) as exc:
            await _buy(MockNativePool(), numbers, enc, number="+390212345678", country="IT", holder=HOLDER,
                       answers=given)
        assert (exc.value.kind, exc.value.details["requirement_id"]) == (kind, named)
    with pytest.raises(h.PhoneNumberError) as exc:  # who holds it is asked too
        await _buy(MockNativePool(), numbers, enc, number="+390212345678", country="IT", answers=answers)
    assert exc.value.kind == "address"
    numbers.buy.assert_not_awaited()


async def test_a_number_the_carrier_reviews_is_left_in_review_and_nothing_is_held_or_charged(seams):
    numbers, created, charge, enc = seams
    numbers.offer.side_effect = lambda number, country, number_type: offer(number, country=country,
                                                                           number_type=number_type, needs="documents")
    numbers.buy.return_value = {"order_id": "order-1", "phone_number": "+390212345678", "status": "in_review"}
    answers = {"r-type": "Passport", "r-id": "doc-1"}
    out = await _buy(MockNativePool(), numbers, enc, number="+390212345678", country="IT", holder=HOLDER,
                     answers=answers, origin={"kind": "link", "request_id": "req-1"})
    assert out == {"order_id": "order-1", "phone_number": "+390212345678", "status": "in_review"}
    kwargs = numbers.buy.await_args.kwargs
    assert (kwargs["holder"], kwargs["answers"], kwargs["origin"]) == (
        HOLDER, answers, {"kind": "link", "request_id": "req-1"})
    # The account must afford it now; it's charged, with its credential, only once the carrier completes it.
    created.assert_not_awaited(); charge.assert_not_awaited(); numbers.release.assert_not_awaited()


async def test_a_number_no_longer_for_sale_or_not_a_number_is_refused(seams):
    numbers, _, _, enc = seams
    for number, kind in (("+44 20 7123", "number"), ("not a number", "number")):
        numbers.offer.side_effect = lambda *a, **k: None
        with pytest.raises(h.PhoneNumberError) as exc:
            await _buy(MockNativePool(), numbers, enc, number=number)
        assert exc.value.kind == kind
    with pytest.raises(h.PhoneNumberError) as exc:
        await h.live_offer("+15674833618", country="USA", number_type="local")
    assert exc.value.kind == "country"
    with pytest.raises(h.PhoneNumberError) as exc:
        await h.live_offer("+15674833618", country="US", number_type="landline")
    assert exc.value.kind == "number_type"
    numbers.buy.assert_not_awaited()


async def test_any_plan_may_hold_a_number_with_five_dollars_in_its_balance(seams, monkeypatch):
    from billing.gates import Offer

    numbers, created, _, enc = seams
    monkeypatch.setattr("billing.plan_limits.on_old_plans", AsyncMock(return_value=False))
    cheap = h.NumberPrice(usd(0.5), usd(0.5))  # $1 due now, under the floor
    usage_tracker.fetch_credit_remaining.return_value = usd(4.99)
    with pytest.raises(h.GateDenied) as exc:
        await _buy(MockNativePool(), numbers, enc, tier="free", price=cheap)
    assert exc.value.kind == "credits"
    assert str(exc.value) == ("Buying phone numbers needs at least $5 of funds the account added (included usage "
                              "doesn't count); it has $4.99.")
    assert exc.value.offer == Offer(funds_usd=0.01)  # funds, never a plan
    numbers.buy.assert_not_awaited(); created.assert_not_awaited()
    # $5 is enough on Free, and no plan is read.
    usage_tracker.fetch_credit_remaining.return_value = usd(5)
    out = await _buy(MockNativePool(), numbers, enc, tier="free", price=cheap)
    assert out["credential_id"] == "cred-1"
    from billing import plan_limits
    plan_limits.get_effective_tier.assert_not_awaited()


async def test_a_credential_that_cannot_be_saved_releases_the_number(seams):
    numbers, created, charge, enc = seams
    created.return_value = (None, "Credential limit reached for this plan")
    with pytest.raises(h.PhoneNumberError) as exc:
        await _buy(MockNativePool(), numbers, enc, tier="plus")
    assert exc.value.kind == "credential" and "limit" in str(exc.value)
    numbers.release.assert_awaited_once_with("PN1")
    charge.assert_not_awaited()


async def test_a_search_passes_every_filter_and_prices_each_number_for_the_account(seams):
    numbers = seams[0]
    found = await h.search_numbers_for_user(
        user_id=USER, country="gb", number_type="mobile", area_code="7700",
        locality="London", region="England", contains="no click", starts_with="900", ends_with="23",
        features="voice_sms", limit=12)
    [query] = numbers.search.await_args.args
    assert query == {"country": "GB", "number_type": "mobile", "area_code": "7700", "locality": "London",
                     "region": "England", "contains": "NOCLICK", "starts_with": "900", "ends_with": "23",
                     "features": ("voice", "SMS"), "limit": 12}
    first, second = found["numbers"]
    assert (first["monthly_credits"], first["upfront_credits"]) == (12, 12)
    assert (second["monthly_credits"], second["upfront_credits"]) == (18, 0)
    assert first["requirements"]["needs"] == "none" and first["texting"] == "registration"


@pytest.mark.parametrize("filters,kind", [
    ({"country": "USA"}, "country"), ({"number_type": "landline"}, "number_type"),
    ({"contains": "hello world!!"}, "pattern"), ({"starts_with": "12a"}, "starts_with"),
    ({"ends_with": "12345678901"}, "ends_with"), ({"area_code": "4-1-5x"}, "area_code"),
    ({"locality": "x" * 65}, "locality"), ({"features": "sms"}, "features"), ({"limit": 31}, "limit"),
])
async def test_a_search_refuses_a_filter_it_cant_send(seams, filters, kind):
    with pytest.raises(h.PhoneNumberError) as exc:
        await h.search_numbers_for_user(user_id=USER, **{"country": "US", **filters})
    assert exc.value.kind == kind
    seams[0].search.assert_not_awaited()


class FakeSio:
    def __init__(self, session): self._session = session; self.sent = []
    async def get_session(self, sid): return self._session
    async def emit(self, *a, **k): self.sent.append((a, k))


async def test_handler_gates_on_the_rollout_then_the_provider(seams, monkeypatch):
    from utils import feature_gates
    from wss.receiver.client_events import (
        PhoneNumberBuyRequest, PhoneNumberCoverageRequest, PhoneNumberPlacesRequest, PhoneNumberSearchRequest,
    )
    numbers = seams[0]
    sent = []
    monkeypatch.setattr(h, "send_event", AsyncMock(side_effect=lambda sio, sid, ev: sent.append(ev)))
    monkeypatch.setattr(h.PhoneNumberHandler, "get_pool", AsyncMock(return_value=MockNativePool()))  # CI has no live pool
    monkeypatch.setattr(feature_gates, "is_internal_user", lambda email: email.endswith("@noclick.com"))
    monkeypatch.setitem(feature_gates.FEATURE_ROLLOUT, "phone_numbers", feature_gates.INTERNAL)
    handler = h.PhoneNumberHandler(FakeSio({"user_id": USER, "user_data": {"email": "someone@example.com"}}))
    await handler.handle_search("sid", PhoneNumberSearchRequest(request_id="r1", country="US"))
    assert sent[-1].data == {"kind": "gated"}
    handler = h.PhoneNumberHandler(FakeSio({"user_id": USER, "user_data": {"email": "dhruv@noclick.com"}}))
    usage_tracker.fetch_credit_remaining.return_value = usd(4.99)  # short of a purchase, but browsing is free
    await handler.handle_search("sid", PhoneNumberSearchRequest(request_id="r1b", country="US"))
    assert sent[-1].error is None and len(sent[-1].data["numbers"]) == 2
    usage_tracker.fetch_credit_remaining.return_value = 40.0
    handler = h.PhoneNumberHandler(FakeSio({"user_id": USER, "user_data": {"email": "dhruv@noclick.com", "subscription_tier": "pro"}}))
    await handler.handle_search("sid", PhoneNumberSearchRequest(request_id="r2", country="US", area_code="567", contains="no click", limit=12))
    assert sent[-1].error is None and sent[-1].data["numbers"][0]["phone_number"] == "+15674833618"
    assert sent[-1].data["numbers"][0]["monthly_credits"] == 12
    [query] = numbers.search.await_args.args
    assert (query["area_code"], query["contains"], query["limit"]) == ("567", "NOCLICK", 12)  # spaces dropped, letters kept for the keypad
    await handler.handle_search("sid", PhoneNumberSearchRequest(request_id="r2c", country="US", contains="hello world!!"))
    assert sent[-1].data == {"kind": "pattern"}
    # Where numbers are sold, with the account's own verified phone to offer as a holder's contact.
    monkeypatch.setattr(PhoneRepo, "get_reach_phone", AsyncMock(return_value={"phone_e164": "+15674830000"}))
    await handler.handle_coverage("sid", PhoneNumberCoverageRequest(request_id="r3"))
    assert sent[-1].data == {"countries": [{"country": "US", "number_types": ["local"], "texting_types": ["local"]}],
                             "contact_phone": "+15674830000"}
    await handler.handle_places("sid", PhoneNumberPlacesRequest(request_id="r3b", country="us"))
    assert sent[-1].data["places"][0]["value"] == "567"
    numbers.places.assert_awaited_once_with("US", "local")
    # A purchase carries the price the person agreed to; a moved one comes back with the new price.
    await handler.handle_buy("sid", PhoneNumberBuyRequest(request_id="r4", phone_number="+15674833618", country="US",
                                                          number_type="local", monthly_credits=12,
                                                          upfront_credits=0))
    assert sent[-1].data == {"kind": "price", "monthly_credits": 12, "upfront_credits": 12}
    numbers.buy.assert_not_awaited()
    await handler.handle_buy("sid", PhoneNumberBuyRequest(request_id="r5", phone_number="+15674833618", country="US",
                                                          number_type="local", monthly_credits=12,
                                                          upfront_credits=12))
    assert sent[-1].data == {"credential_id": "cred-1", "phone_number": "+15674833618"}
    capabilities.clear()
    await handler.handle_search("sid", PhoneNumberSearchRequest(request_id="r6", country="US"))
    assert sent[-1].data == {"kind": "unavailable"}


async def test_where_numbers_are_sold_before_its_first_check_is_a_refusal_the_page_can_read(seams, monkeypatch):
    from utils import feature_gates
    from utils.phone_numbers import CoverageNotReady
    from wss.receiver.client_events import PhoneNumberCoverageRequest

    seams[0].coverage = AsyncMock(side_effect=CoverageNotReady(
        "Where numbers are for sale is still being checked. Try again in a minute."))
    sent = []
    monkeypatch.setattr(h, "send_event", AsyncMock(side_effect=lambda sio, sid, ev: sent.append(ev)))
    monkeypatch.setattr(h.PhoneNumberHandler, "get_pool", AsyncMock(return_value=MockNativePool()))
    monkeypatch.setattr(feature_gates, "is_internal_user", lambda email: True)
    monkeypatch.setitem(feature_gates.FEATURE_ROLLOUT, "phone_numbers", feature_gates.INTERNAL)
    handler = h.PhoneNumberHandler(FakeSio({"user_id": USER, "user_data": {"email": "dhruv@noclick.com"}}))
    await handler.handle_coverage("sid", PhoneNumberCoverageRequest(request_id="r1"))
    assert sent[-1].data == {"kind": "not_ready"} and "still being checked" in sent[-1].error


def test_a_holders_contact_phone_is_a_valid_international_number_kept_in_e164():
    holder = {"name": "Dana Ruiz", "street": "Keizersgracht 1", "city": "Amsterdam", "postal_code": "1015 CJ",
              "country": "NL"}
    assert PhoneNumberHolder(**holder, phone="+31 6 1234 5670").phone == "+31612345670"
    assert PhoneNumberHolder(**holder).phone is None and PhoneNumberHolder(**holder, phone=" ").phone is None
    for wrong in ("0612345670", "+31 6 12", "+999 1234 5678", "call me"):
        with pytest.raises(ValueError, match="international number"):
            PhoneNumberHolder(**holder, phone=wrong)


async def test_an_older_client_searches_and_buys_a_number_alone_at_the_price_read_here(seams, monkeypatch):
    """main's purchase form sends a search with no kind and a buy with the number
    alone, and reads one monthly price off the search: a US local number, priced
    here for the account, never by the client."""
    from wss.receiver.client_events import PhoneNumberBuyRequest, PhoneNumberSearchRequest

    numbers, created, charge, enc = seams
    sent = []
    monkeypatch.setattr(h, "send_event", AsyncMock(side_effect=lambda sio, sid, ev: sent.append(ev)))
    monkeypatch.setattr(h.PhoneNumberHandler, "get_pool", AsyncMock(return_value=MockNativePool()))
    handler = h.PhoneNumberHandler(FakeSio({"user_id": USER, "user_data": {"email": "x@example.com",
                                                                            "subscription_tier": "pro"}}))
    numbers.search.return_value = [offer(), offer("+15674833619")]
    await handler.handle_search("sid", PhoneNumberSearchRequest(request_id="r1", country="US", area_code="567",
                                                                limit=10))
    assert sent[-1].data["monthly_credits"] == 12 and len(sent[-1].data["numbers"]) == 2
    # Numbers priced apart share no one price.
    numbers.search.return_value = [offer(), offer("+15674833619", monthly="1.50")]
    await handler.handle_search("sid", PhoneNumberSearchRequest(request_id="r2", country="US"))
    assert sent[-1].data["monthly_credits"] is None

    request = PhoneNumberBuyRequest(request_id="r3", phone_number="+15674833618")
    assert (request.country, request.number_type, request.monthly_credits, request.upfront_credits) == (
        "US", "local", None, None)
    await handler.handle_buy("sid", request)
    assert sent[-1].data == {"credential_id": "cred-1", "phone_number": "+15674833618"}
    numbers.offer.assert_awaited_with("+15674833618", country="US", number_type="local")
    assert charge.await_args.kwargs["period_usd"] == "1.00"


async def test_documents_orders_and_resubmission_go_through_the_capability(seams, monkeypatch):
    import jwt

    from wss.receiver.client_events import (
        PhoneNumberDocumentRemoveRequest, PhoneNumberDocumentUploadRequest, PhoneNumberDocumentsRequest,
        PhoneNumberOrdersRequest, PhoneNumberResubmitRequest,
    )

    numbers = seams[0]
    sent = []
    monkeypatch.setattr(h, "send_event", AsyncMock(side_effect=lambda sio, sid, ev: sent.append(ev)))
    monkeypatch.setattr(h.PhoneNumberHandler, "get_pool", AsyncMock(return_value=MockNativePool()))
    monkeypatch.setattr("mcp_adapter.auth.tokens.get_mcp_signing_key", lambda: "k" * 32)
    handler = h.PhoneNumberHandler(FakeSio({"user_id": USER, "user_data": {"email": "x@example.com",
                                                                            "subscription_tier": "pro"}}))
    document = {"id": "doc-1", "requirement_id": "r-id", "requirement_name": "Identity Document",
                "filename": "passport.pdf", "uploaded_at": "2026-10-10T12:00:00+00:00"}
    numbers.documents = AsyncMock(return_value=[document])
    await handler.handle_documents("sid", PhoneNumberDocumentsRequest(request_id="r1"))
    assert sent[-1].data == {"documents": [document]}
    numbers.documents.assert_awaited_once_with(USER)

    # An upload goes to a link signed for this account and requirement, straight to the backend.
    await handler.handle_document_upload("sid", PhoneNumberDocumentUploadRequest(
        request_id="r2", country="IT", number_type="local", requirement_id="r-id"))
    path = sent[-1].data["upload_url_path"]
    assert path.startswith(h.DOCUMENT_UPLOAD_PATH + "?token=")
    token = path.split("token=")[1]
    assert h.document_upload_claims(token) == {"user_id": USER, "country": "IT", "number_type": "local",
                                               "requirement_id": "r-id"}
    assert h.document_upload_claims(jwt.encode({"aud": "noclick-workspace-upload", "sub": USER}, "k" * 32,
                                               algorithm="HS256")) is None

    numbers.remove_document = AsyncMock(return_value={"id": "doc-1", "removed": True, "kept_by_carrier": True})
    await handler.handle_document_remove("sid", PhoneNumberDocumentRemoveRequest(request_id="r3", document_id="doc-1"))
    assert sent[-1].data == {"id": "doc-1", "removed": True, "kept_by_carrier": True}

    order = {"id": "order-1", "phone_number": "+390212345678", "country": "IT", "number_type": "local",
             "status": "rejected", "reason": "The scan is cut off.", "deadline": None, "monthly_usd": "1.00",
             "upfront_usd": "1.00", "credential_id": None, "created_at": "x", "updated_at": "x",
             "requirements": {"needs": "documents", "items": DOCUMENT_ASKS}}
    numbers.orders = AsyncMock(return_value=[order])
    await handler.handle_orders("sid", PhoneNumberOrdersRequest(request_id="r4"))
    [listed] = sent[-1].data["orders"]
    assert (listed["status"], listed["monthly_credits"], listed["upfront_credits"]) == ("rejected", 12, 12)

    numbers.order = AsyncMock(return_value=order)
    numbers.resubmit = AsyncMock(return_value={**order, "status": "in_review", "reason": None})
    await handler.handle_resubmit("sid", PhoneNumberResubmitRequest(request_id="r5", order_id="order-1",
                                                                   answers={"r-type": "Passport"}))
    assert sent[-1].data["kind"] == "address"  # the holder is asked again, with every answer
    numbers.resubmit.assert_not_awaited()
    holder = PhoneNumberHolder(**HOLDER)
    await handler.handle_resubmit("sid", PhoneNumberResubmitRequest(
        request_id="r6", order_id="order-1", holder=holder, answers={"r-type": "Passport", "r-id": "doc-2"}))
    assert sent[-1].data["order"]["status"] == "in_review"
    numbers.resubmit.assert_awaited_once_with(USER, "order-1", holder=holder.model_dump(),
                                              answers={"r-type": "Passport", "r-id": "doc-2"})
    # Only an order the carrier sent back can be resubmitted.
    numbers.order = AsyncMock(return_value={**order, "status": "in_review"})
    await handler.handle_resubmit("sid", PhoneNumberResubmitRequest(
        request_id="r7", order_id="order-1", holder=holder, answers={"r-type": "Passport", "r-id": "doc-2"}))
    assert sent[-1].data == {"kind": "order"}


# ── the activity feed ────────────────────────────────────────────────────────

async def test_a_number_bought_is_the_buyers_activity_once(seams, activity_signals):
    numbers, _, _, enc = seams
    await _buy(MockNativePool(), numbers, enc)

    assert activity_signals == [(USER, "buy.number", {"number": "+15674833618", "monthly_usd": "1.00",
                                                      "upfront_usd": "1.00"}, None)]


async def test_a_number_in_review_or_bought_for_a_platform_user_is_not_yet_the_accounts_activity(seams,
                                                                                               activity_signals):
    numbers, _, _, enc = seams
    await _buy(MockNativePool(), numbers, enc, origin={"kind": "api", "tenant_id": "t-1"})
    numbers.offer.side_effect = lambda number, country, number_type: offer(number, country=country,
                                                                           number_type=number_type, needs="documents")
    numbers.buy.return_value = {"order_id": "order-1", "phone_number": "+390212345678", "status": "in_review"}
    await _buy(MockNativePool(), numbers, enc, number="+390212345678", country="IT", holder=HOLDER,
               answers={"r-type": "Passport", "r-id": "doc-1"})

    assert activity_signals == []  # the order's own completion reports the number it buys


async def test_a_search_is_activity_keyed_to_its_session(seams, activity_signals):
    await h.search_numbers_for_user(user_id=USER, country="us", number_type="local", area_code="415")

    assert activity_signals == [(USER, "search.numbers", {"country": "US", "number_type": "local",
                                                          "area_code": "415", "found": 2}, "search:numbers")]
