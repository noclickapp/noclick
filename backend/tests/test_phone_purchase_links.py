"""Paid credential links: real PostgreSQL claims, isolated provider side effects."""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from billing import recurring
from billing.markup import CREDITS_PER_DOLLAR
from billing.usage_tracker import usage_tracker
from repositories.credentials import CredentialsRepo
from utils import capabilities, phone_purchase as purchase, phone_purchase_routes as routes
from utils.phone_numbers import PhonePurchaseRejected
from wss.handlers import phone_number_handler as handler

USER = "00000000-0000-0000-0000-000000000001"
NUMBER = "+15674833618"
# A US local number as the carrier offers it now: $1 a month and $1 once, nothing asked before it's sold.
OFFER = {"phone_number": NUMBER, "country": "US", "number_type": "local", "locality": "Lucas", "region": "OH",
         "capabilities": ["voice", "SMS"], "monthly_usd": "1.00", "upfront_usd": "1.00",
         "requirements": {"needs": "none", "items": []}, "texting": "registration"}
pytestmark = pytest.mark.asyncio


def on_free_member(monkeypatch):
    """Let the test account (test@example.com) into the free_member rollout."""
    from utils import feature_gates

    monkeypatch.setitem(feature_gates.FEATURE_ALLOWLIST, "free_member", {"test@example.com"})


async def _quote(service, token, number=NUMBER):
    return (await service.quote(token, number, country="US"))["quote"]


async def funds_as_modeled(conn, payer):
    """The funds a purchase reads (``billing.gates.funds_usd``): the balance these tests model, in dollars."""
    from decimal import Decimal

    from billing.markup import CREDITS_PER_DOLLAR

    return Decimal(str(usage_tracker.fetch_credit_remaining.return_value)) / CREDITS_PER_DOLLAR


@pytest.fixture
async def phone_db(postgres_db, postgres_container, monkeypatch):
    from tests.fixtures.postgres_fixtures import asyncpg
    from utils.database_pool import setup_asyncpg_codecs

    pool = await asyncpg.create_pool(
        host=postgres_container.get_container_host_ip(), port=postgres_container.get_exposed_port(5432),
        user=postgres_container.username, password=postgres_container.password, database=postgres_container.dbname,
        min_size=1, max_size=5, init=setup_asyncpg_codecs,
    )
    saved = dict(capabilities._providers)
    numbers = MagicMock(
        search=AsyncMock(return_value=[OFFER]), offer=AsyncMock(return_value=OFFER),
        buy=AsyncMock(return_value={"phone_number": NUMBER, "number_sid": "PN_test", "provider": "carrier-a"}), release=AsyncMock(),
    )
    capabilities.provide(capabilities.PHONE_NUMBERS, numbers)
    monkeypatch.setattr(purchase, "require_feature", lambda *a, **k: None)
    monkeypatch.setattr(purchase, "get_user_tier_from_db", AsyncMock(return_value="pro"))
    monkeypatch.setattr("billing.plan_limits.get_effective_tier", AsyncMock(return_value="pro"))
    monkeypatch.setattr("billing.plan_limits.check_credential_limit", AsyncMock(return_value=(True, None)))
    monkeypatch.setattr("repositories.credentials.log_activity_background", lambda *a, **k: None)
    monkeypatch.setattr(usage_tracker, "resolve_billing_user_id", AsyncMock(return_value=USER))
    monkeypatch.setattr(usage_tracker, "fetch_credit_remaining", AsyncMock(return_value=100))
    monkeypatch.setattr("billing.gates.funds_usd", funds_as_modeled)
    monkeypatch.setattr(handler, "start_connection_charge", AsyncMock())
    monkeypatch.setattr(purchase, "get_encryption", lambda: MagicMock(encrypt_credential=lambda blob: "test-encrypted"))
    # A number's prices are priced for the paying account (billing.recurring.charge_credits) on this database.
    monkeypatch.setattr("utils.database_pool._native_pool", pool)
    monkeypatch.setattr("utils.database_pool._native_pool_loop", None)
    repo = CredentialsRepo(pool)
    row = await repo.upsert_credential_request(requester_id=USER, target_email="", credential_type="phone_number", message="Receptionist")
    service = purchase.PhonePurchase(pool, USER)
    try:
        yield pool, service, row.token, numbers
    finally:
        await pool.execute("DELETE FROM credential_requests WHERE requester_id=$1::uuid", USER)
        await pool.execute("DELETE FROM credentials WHERE owner_id=$1::uuid AND credential_type='phone_number'", USER)
        capabilities._providers.clear()
        capabilities._providers.update(saved)
        await pool.close()


async def test_review_is_read_only_and_concurrent_confirmations_buy_once(phone_db):
    pool, service, token, numbers = phone_db
    quote = await _quote(service, token)
    # The number's own price, for this account: its carrier's month and one-time cost, priced for who pays.
    price = await handler.number_price(USER, OFFER)
    assert (quote["monthly_credits"], quote["upfront_credits"]) == (price.monthly_credits, price.upfront_credits)
    assert price.monthly_credits == await recurring.charge_credits(USER, "phone_number", "1.00") > 0
    assert (quote["country"], quote["number_type"], quote["requirements"]["needs"]) == ("US", "local", "none")
    numbers.offer.assert_awaited_with(NUMBER, country="US", number_type="local")
    numbers.buy.assert_not_awaited()
    replies = await asyncio.gather(*(service.confirm(token, quote["id"]) for _ in range(6)))
    assert {r["status"] for r in replies} <= {"fulfilled", "provisioning"}
    result = await service.confirm(token, quote["id"])
    assert result["status"] == "fulfilled" and result["credential_id"]
    numbers.buy.assert_awaited_once()
    handler.start_connection_charge.assert_awaited_once()
    assert await pool.fetchval("SELECT count(*) FROM credentials WHERE id=$1::uuid", result["credential_id"]) == 1
    # A restarted service returns the same result, even after the link expires.
    await pool.execute("UPDATE credential_requests SET expires_at=now()-interval '1 day' WHERE token=$1", token)
    assert await purchase.PhonePurchase(pool, USER).confirm(token, quote["id"]) == result
    next_request = await service.create("A second line")
    assert next_request["request_id"] != result["request_id"]
    assert await service.confirm(token, quote["id"]) == result
    numbers.buy.assert_awaited_once()


@pytest.mark.parametrize("invalid", ["quote_id", "quote_expired", "request_expired", "price", "cancelled"])
async def test_stale_or_changed_confirmation_cannot_buy(phone_db, invalid):
    pool, service, token, numbers = phone_db
    quote = await _quote(service, token)
    if invalid == "quote_id":
        quote["id"] = str(uuid4())
    elif invalid in ("quote_expired", "price"):
        changed = dict(quote)
        if invalid == "price": changed["monthly_credits"] = quote["monthly_credits"] + 1
        else: changed["expires_at"] = (datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
        await pool.execute("UPDATE credential_requests SET purchase_quote=$2 WHERE token=$1", token, changed)
    elif invalid == "request_expired":
        await pool.execute("UPDATE credential_requests SET expires_at=now()-interval '1 second' WHERE token=$1", token)
    else:
        await pool.execute("UPDATE credential_requests SET status='cancelled' WHERE token=$1", token)
    with pytest.raises(HTTPException) as exc:
        await service.confirm(token, quote["id"])
    assert exc.value.status_code == 409
    numbers.buy.assert_not_awaited()


async def test_reselection_invalidates_old_confirmation(phone_db):
    _, service, token, numbers = phone_db
    first = await _quote(service, token)
    await _quote(service, token)
    with pytest.raises(HTTPException): await service.confirm(token, first["id"])
    numbers.buy.assert_not_awaited()


@pytest.mark.parametrize("error,reopens", [(PhonePurchaseRejected("Unavailable"), True), (TimeoutError("unknown"), False)])
async def test_definitive_rejection_vs_uncertain_provider_result(phone_db, error, reopens):
    _, service, token, numbers = phone_db
    quote = await _quote(service, token)
    numbers.buy.side_effect = error
    result = await service.confirm(token, quote["id"])
    assert result["status"] == ("pending" if reopens else "provisioning")
    if reopens:
        assert result["quote"] is None
        with pytest.raises(HTTPException): await service.confirm(token, quote["id"])
    else:
        assert "contact support" in result["error"]
        assert await service.confirm(token, quote["id"]) == result
    numbers.buy.assert_awaited_once()


async def test_failed_atomic_fulfillment_rolls_back_credential_and_releases_number(phone_db, monkeypatch):
    pool, service, token, numbers = phone_db
    quote = await _quote(service, token)
    monkeypatch.setattr(service.repo, "fulfill_phone_purchase", AsyncMock(side_effect=RuntimeError("DB failed")))
    result = await service.confirm(token, quote["id"])
    assert result["status"] == "provisioning"  # release errors would also remain quarantined
    assert await pool.fetchval("SELECT count(*) FROM credentials WHERE owner_id=$1::uuid AND credential_type='phone_number'", USER) == 0
    numbers.release.assert_awaited_once_with("PN_test")
    await service.confirm(token, quote["id"])
    numbers.buy.assert_awaited_once()


async def test_request_refresh_preserves_review_and_inflight_purchase(phone_db):
    _, service, token, numbers = phone_db
    quote = await _quote(service, token)
    for in_flight in (False, True):
        if in_flight: await service.repo.claim_phone_purchase(token, USER, quote["id"], quote["monthly_credits"],
                                                              quote["upfront_credits"])
        result = await service.create("A second description", "+14155551234", country="US")
        assert result["quote"] == quote and result["purpose"] == "Receptionist"
        assert result["approval_url"].endswith(token)
    numbers.buy.assert_not_awaited()


async def test_abandoned_purchase_surfaces_uncertainty_without_buying_again(phone_db):
    pool, service, token, numbers = phone_db
    quote = await _quote(service, token)
    await service.repo.claim_phone_purchase(token, USER, quote["id"], quote["monthly_credits"], quote["upfront_credits"])
    await pool.execute("UPDATE credential_requests SET provisioning_started_at=now()-interval '3 minutes' WHERE token=$1", token)
    result = await service.confirm(token, quote["id"])
    assert result["status"] == "provisioning" and "contact support" in result["error"]
    numbers.buy.assert_not_awaited()


async def test_owner_auth_and_request_scope_http(phone_db, monkeypatch):
    pool, service, token, numbers = phone_db
    quote = await _quote(service, token)
    monkeypatch.setattr(routes, "get_native_pool", lambda: pool)
    verifier = AsyncMock(return_value={"sub": USER})
    monkeypatch.setattr(routes, "verify_token", verifier)
    app = FastAPI(); app.include_router(routes.router, prefix="/api/credential-request")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        url = f"/api/credential-request/{token}/phone"
        assert (await client.post(url+"/confirm", json={"quote_id": quote["id"]})).status_code == 401
        headers = {"Authorization": "Bearer signed-session"}
        verifier.side_effect = ValueError("bad JWT")
        assert (await client.get(url, headers=headers)).status_code == 401
        verifier.side_effect = None; verifier.return_value = {"sub": str(uuid4())}
        for path, body in (("/search", {}), ("/quote", {"phone_number": NUMBER, "country": "US"}),
                           ("/confirm", {"quote_id": quote["id"]}), ("/coverage", None),
                           ("/places", {"country": "US"})):
            assert (await client.post(url+path, headers=headers, json=body)).status_code == 404
        verifier.return_value = {"sub": USER}
        # The purchase page on main quotes a number alone: a US local one, priced here.
        older = (await client.post(url+"/quote", headers=headers, json={"phone_number": NUMBER})).json()["quote"]
        assert (older["country"], older["number_type"]) == ("US", "local")
        assert older["monthly_credits"] == (await handler.number_price(USER, OFFER)).monthly_credits
        quote = older
        assert (await client.post(url+"/confirm", headers=headers, json={"quote_id": quote["id"], "monthly_credits": 1})).status_code == 422
        assert (await client.post(url+"/confirm", headers=headers, json={"quote_id": quote["id"]})).json()["status"] == "fulfilled"
    numbers.buy.assert_awaited_once()


async def test_postgrest_cannot_modify_server_quotes_or_purchase_claims(phone_db):
    pool, *_ = phone_db
    assert await pool.fetchval("SELECT relrowsecurity FROM pg_class WHERE relname='credential_requests'")
    for role in ("anon", "authenticated"):
        assert not await pool.fetchval("SELECT has_table_privilege($1,'credential_requests','SELECT,INSERT,UPDATE,DELETE')", role)


async def test_public_manual_credential_route_cannot_forge_phone_number(phone_db, monkeypatch):
    from utils import credential_request_routes as public
    pool, _, token, numbers = phone_db
    monkeypatch.setattr(public, "get_native_pool", lambda: pool)
    with pytest.raises(HTTPException) as exc:
        await public.provide_credential(token, public.ProvideCredentialBody(credential_data={"phone_number": NUMBER, "number_sid": "forged"}))
    assert exc.value.status_code == 403
    assert await pool.fetchval("SELECT provision_attempts FROM credential_requests WHERE token=$1", token) == 0
    numbers.buy.assert_not_awaited()


async def test_purchased_credential_resumes_the_existing_builder_link(phone_db, monkeypatch):
    from repositories.builder_bridge import BuilderBridgeRepo
    from utils import builder_bridge_routes as bridge
    from wss.handlers.workflow_builder_handler import WorkflowBuilderHandler

    pool, service, token, _ = phone_db
    row = await service.request(token)
    repo = BuilderBridgeRepo(pool)
    link_id = await repo.create_link(
        user_id=USER, workflow_id=str(uuid4()), builder_conversation_id="phone-builder-test",
        agent_conversation_id=None, agent_node_id=None, workflow_name="Receptionist",
        ask_id="phone-ask", inputs=[{"id": "line", "type": "credential", "credential_type": "phone_number",
                                     "credential_request_id": str(row["id"]), "required": True}],
    )
    monkeypatch.setattr(bridge, "get_native_pool", lambda: pool)
    resumed = AsyncMock()
    monkeypatch.setattr(WorkflowBuilderHandler, "handle_input_response", resumed)
    monkeypatch.setattr("utils.socket_singleton.get_sio", lambda: MagicMock())
    spawned = []
    monkeypatch.setattr("utils.async_helpers.spawn", lambda coro, **kwargs: spawned.append(coro))
    try:
        # A public builder visitor cannot supply a credential id before purchase.
        with pytest.raises(HTTPException):
            await bridge.submit_bridge_answers(link_id, bridge.BridgeSubmitBody(values={"line": "forged"}))
        quote = await _quote(service, token)
        bought = await service.confirm(token, quote["id"])
        await bridge.submit_bridge_answers(link_id, bridge.BridgeSubmitBody(values={"line": "forged"}))
        for coroutine in spawned: await coroutine
        assert resumed.await_args.args[1] == {"conversation_id": "phone-builder-test", "ask_id": "phone-ask", "values": {"line": bought["credential_id"]}}
        assert resumed.await_args.kwargs["caller_user_id"] == USER
        with pytest.raises(HTTPException):
            await bridge.submit_bridge_answers(link_id, bridge.BridgeSubmitBody(values={}))
        assert resumed.await_count == 1
    finally:
        await pool.execute("DELETE FROM builder_input_links WHERE id=$1::uuid", link_id)


async def test_coordinator_finds_numbers_in_the_owners_country_unless_told_another(phone_db, monkeypatch):
    from coder.coordinator.tools import CoordinatorTools
    from repositories.phones import PhoneRepo

    pool, _, _, numbers = phone_db
    tools = CoordinatorTools(pool=pool, sio=None, user_id=USER, organization_id=None, conversation_id=f"coordinator:{USER}")
    reach = AsyncMock(return_value=None)
    monkeypatch.setattr(PhoneRepo, "get_reach_phone", reach)
    unknown = await tools.execute("find_phone_numbers", {})
    assert unknown["success"] is False and "country" in unknown["error"]
    numbers.search.assert_not_awaited()
    # The owner reaches NoClick from a London number: numbers are found in the UK.
    reach.return_value = {"phone_e164": "+442071234567"}
    found = await tools.execute("find_phone_numbers", {"number_type": "mobile", "locality": "London",
                                                       "features": "voice_sms"})
    [query] = numbers.search.await_args.args
    assert (query["country"], query["number_type"], query["locality"], query["features"]) == (
        "GB", "mobile", "London", ("voice", "SMS"))
    assert found["country"] == "GB"
    assert found["numbers"][0]["monthly_credits"] == (await handler.number_price(USER, OFFER)).monthly_credits
    # Told another country, it searches there.
    await tools.execute("find_phone_numbers", {"country": "de"})
    assert numbers.search.await_args.args[0]["country"] == "DE"


# A Netherlands mobile number as Telnyx sells it: an address on file and the holder's contact information.
WHO_HOLDS_IT = {**OFFER, "phone_number": "+31612345678", "country": "NL", "number_type": "mobile",
                "requirements": {"needs": "address", "items": [
                    {"kind": "address", "name": "Worldwide Physical Address", "description": ""},
                    {"kind": "contact", "name": "Contact Information (Name, Business Name, Phone Number)",
                     "description": ""}]}}
HOLDER = {"name": "Dana Ruiz", "business_name": None, "street": "Keizersgracht 1", "street2": None,
          "city": "Amsterdam", "region": None, "postal_code": "1015 CJ", "country": "NL"}


async def test_a_number_whose_country_asks_who_holds_it_is_confirmed_with_their_address_and_phone(phone_db):
    _, service, token, numbers = phone_db
    numbers.offer.return_value = WHO_HOLDS_IT
    quote = (await service.quote(token, "+31612345678", country="NL", number_type="mobile"))["quote"]
    assert quote["requirements"]["needs"] == "address"
    for holder in (None, HOLDER):  # nothing, then no phone to contact them on: nothing is claimed
        with pytest.raises(handler.PhoneNumberError) as exc:
            await service.confirm(token, quote["id"], holder)
        assert exc.value.kind == "address"
        assert (await service.status(token))["status"] == "pending"
    numbers.buy.assert_not_awaited()
    holder = {**HOLDER, "phone": "+31612345670"}
    assert (await service.confirm(token, quote["id"], holder))["status"] == "fulfilled"
    assert numbers.buy.await_args.kwargs["holder"] == holder


async def test_the_link_offers_the_owners_phone_and_takes_only_a_valid_contact_phone(phone_db, monkeypatch):
    from repositories.phones import PhoneRepo

    pool, service, token, numbers = phone_db
    numbers.offer.return_value = WHO_HOLDS_IT
    quote = (await service.quote(token, "+31612345678", country="NL", number_type="mobile"))["quote"]
    monkeypatch.setattr(routes, "get_native_pool", lambda: pool)
    monkeypatch.setattr(routes, "verify_token", AsyncMock(return_value={"sub": USER}))
    monkeypatch.setattr(PhoneRepo, "get_reach_phone", AsyncMock(return_value={"phone_e164": "+31612345670"}))
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/credential-request")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                 headers={"Authorization": "Bearer signed-session"}) as client:
        url = f"/api/credential-request/{token}/phone"
        numbers.coverage = AsyncMock(return_value=[{"country": "NL", "number_types": ["mobile"],
                                                    "texting_types": []}])
        assert (await client.post(url + "/coverage")).json()["contact_phone"] == "+31612345670"
        refused = await client.post(url + "/confirm", json={"quote_id": quote["id"],
                                                            "holder": {**HOLDER, "phone": "0612345670"}})
        assert refused.status_code == 422
        numbers.buy.assert_not_awaited()
        confirmed = await client.post(url + "/confirm", json={"quote_id": quote["id"],
                                                              "holder": {**HOLDER, "phone": "+31 6 1234 5670"}})
        assert confirmed.json()["status"] == "fulfilled"
    assert numbers.buy.await_args.kwargs["holder"]["phone"] == "+31612345670"


async def test_a_number_whose_country_asks_a_step_cant_be_quoted(phone_db):
    _, service, token, numbers = phone_db
    numbers.offer.return_value = {**OFFER, "requirements": {"needs": "steps", "items": [
        {"id": "r-1", "kind": "step", "name": "Onfido Verification Link - End User", "description": "",
         "example": "", "values": []}]}}
    with pytest.raises(handler.PhoneNumberError) as exc:
        await _quote(service, token)
    assert exc.value.kind == "steps" and "Onfido Verification Link" in str(exc.value)
    assert (await service.status(token))["quote"] is None


def _asked(id, kind, name, values=()):
    return {"id": id, "kind": kind, "name": name, "description": "", "example": "", "values": list(values)}


# An Italian local number as Telnyx sells it: who holds it, which identity document, and the document itself.
NEEDS_DOCUMENTS = {**OFFER, "phone_number": "+390212345678", "country": "IT", "number_type": "local",
                   "requirements": {"needs": "documents", "items": [
                       _asked("r-address", "address", "Worldwide Physical Address"),
                       _asked("r-type", "textual", "Identity Document Type", ("Passport", "Identity card")),
                       _asked("r-id", "document", "Identity Document")]}}
IT_HOLDER = {**HOLDER, "street": "Via Roma 1", "city": "Milano", "postal_code": "20121", "country": "IT"}


async def test_a_number_the_carrier_reviews_waits_on_its_order_and_is_corrected_on_the_link(phone_db):
    pool, service, token, numbers = phone_db
    numbers.offer.return_value = NEEDS_DOCUMENTS
    quote = (await service.quote(token, "+390212345678", country="IT"))["quote"]
    assert quote["requirements"]["needs"] == "documents"
    with pytest.raises(handler.PhoneNumberError) as exc:  # every requirement answered, or nothing is claimed
        await service.confirm(token, quote["id"], IT_HOLDER, {"r-type": "Passport"})
    assert (exc.value.kind, exc.value.details["requirement_id"]) == ("requirements", "r-id")
    numbers.buy.assert_not_awaited()
    numbers.buy.return_value = {"order_id": "order-1", "phone_number": "+390212345678", "status": "in_review"}
    order = {"id": "order-1", "phone_number": "+390212345678", "country": "IT", "number_type": "local",
             "status": "in_review", "reason": None, "deadline": None, "monthly_usd": "1.00", "upfront_usd": "1.00",
             "credential_id": None, "created_at": "x", "updated_at": "x",
             "requirements": NEEDS_DOCUMENTS["requirements"]}
    numbers.order = AsyncMock(return_value=order)
    answers = {"r-type": "Passport", "r-id": "doc-1"}
    waiting = await service.confirm(token, quote["id"], IT_HOLDER, answers)
    # In review for days, perhaps: not "taking longer than expected", and nothing held or charged yet.
    assert (waiting["status"], waiting["order_id"], waiting["error"]) == ("in_review", "order-1", None)
    assert waiting["order"]["monthly_credits"] == quote["monthly_credits"]
    kwargs = numbers.buy.await_args.kwargs
    assert kwargs["answers"] == answers and kwargs["origin"]["kind"] == "link"
    assert kwargs["origin"]["request_id"] == waiting["request_id"]
    handler.start_connection_charge.assert_not_awaited()
    row = await service.request(token)
    assert row["status"] == "provisioning" and row["purchase_quote"]["order_id"] == "order-1"
    assert await pool.fetchval("SELECT count(*) FROM credentials WHERE owner_id=$1::uuid "
                               "AND credential_type='phone_number'", USER) == 0
    # Confirming again doesn't order again.
    assert (await service.confirm(token, quote["id"], IT_HOLDER, answers))["status"] == "in_review"
    numbers.buy.assert_awaited_once()

    # The carrier sends it back: the link says why and takes corrected answers.
    numbers.order.return_value = {**order, "status": "rejected", "reason": "The scan is cut off."}
    sent_back = await service.status(token)
    assert (sent_back["status"], sent_back["order"]["reason"]) == ("rejected", "The scan is cut off.")
    numbers.resubmit = AsyncMock(return_value={**order, "status": "in_review"})
    with pytest.raises(handler.PhoneNumberError):
        await service.resubmit(token, IT_HOLDER, {"r-type": "Passport"})
    numbers.resubmit.assert_not_awaited()
    await service.resubmit(token, IT_HOLDER, {"r-type": "Passport", "r-id": "doc-2"})
    numbers.resubmit.assert_awaited_once_with(USER, "order-1", holder=IT_HOLDER,
                                              answers={"r-type": "Passport", "r-id": "doc-2"})


async def test_a_document_is_posted_to_its_signed_link_and_nowhere_else(phone_db, monkeypatch):
    _, service, token, numbers = phone_db
    monkeypatch.setattr("mcp_adapter.auth.tokens.get_mcp_signing_key", lambda: "k" * 32)
    path = (await service.document_upload(country="IT", number_type="local", requirement_id="r-id"))["upload_url_path"]
    uploaded = {"id": "doc-1", "requirement_id": "r-id", "requirement_name": "Identity Document",
                "filename": "passport.pdf", "uploaded_at": "2026-10-10T12:00:00+00:00"}
    numbers.upload_document = AsyncMock(return_value=uploaded)
    app = FastAPI()
    app.include_router(routes.documents_router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        posted = await client.post(path + "&filename=passport.pdf", content=b"%PDF-1.4 passport")
        assert posted.status_code == 200 and posted.json() == {"document": uploaded}
        numbers.upload_document.assert_awaited_once_with(
            USER, country="IT", number_type="local", requirement_id="r-id", filename="passport.pdf",
            content=b"%PDF-1.4 passport")
        assert posted.headers["access-control-allow-origin"] == "*"
        forged = await client.post(handler.DOCUMENT_UPLOAD_PATH + "?token=forged&filename=x.pdf", content=b"%PDF")
        assert forged.status_code == 403
        too_big = await client.post(path + "&filename=big.pdf", content=b"0" * (routes.DOCUMENT_MAX_BYTES + 1))
        assert too_big.status_code == 413
        numbers.upload_document.side_effect = handler.PhoneDocumentRefused("Upload the document as a PDF, PNG or "
                                                                          "JPEG file.")
        refused = await client.post(path + "&filename=notes.txt", content=b"hello")
        assert refused.status_code == 400 and refused.json()["kind"] == "document"
    assert numbers.upload_document.await_count == 2


async def test_a_price_that_moved_after_the_quote_cant_be_confirmed(phone_db, monkeypatch):
    _, service, token, numbers = phone_db
    on_free_member(monkeypatch)
    quote = await _quote(service, token)
    numbers.offer.return_value = {**OFFER, "monthly_usd": "1.50"}
    with pytest.raises(HTTPException) as exc:
        await service.confirm(token, quote["id"])
    assert exc.value.status_code == 409
    numbers.buy.assert_not_awaited()




async def test_coordinator_advertises_only_available_purchase_tools(phone_db):
    from coder.coordinator.tools import CoordinatorTools, coordinator_tool_params
    pool, service, token, numbers = phone_db
    names = lambda params: {p["function"]["name"] for p in params}
    assert "request_phone_number" not in names(coordinator_tool_params())
    tools = CoordinatorTools(pool=pool, sio=None, user_id=USER, organization_id=None, conversation_id=f"coordinator:{USER}")
    assert {"find_phone_numbers", "request_phone_number", "phone_number_request_status"} <= names(tools.tool_params())
    assert (await tools.request_phone_number("Receptionist", NUMBER))["success"] is False  # its country, please
    result = await tools.request_phone_number("Receptionist", NUMBER, country="US")
    assert result["status"] == "pending" and result["approval_url"].endswith(token)
    assert (await tools.phone_number_request_status(result["request_id"]))["quote"] == result["quote"]
    numbers.buy.assert_not_awaited()
    other = CoordinatorTools(pool=pool, sio=None, user_id=str(uuid4()), organization_id=None, conversation_id="other")
    assert (await other.phone_number_request_status(result["request_id"]))["success"] is False


async def test_coordinator_purchase_registers_before_confirmation_and_wakes_after_buy(phone_db, monkeypatch):
    monkeypatch.setattr('utils.coordinator_links.dispatch_link', lambda *args: None)
    pool, service, token, numbers = phone_db
    context = {'epoch': '', 'depth': 0, 'request': 'Buy a line and build my receptionist', 'channel': 'whatsapp_text'}
    request = await service.create('Receptionist', continuation=context)
    assert request['auto_resume'] and request['approval_url'].endswith(token)
    before = await pool.fetchrow("SELECT * FROM coordinator_wakeups WHERE await_key=$1", f"credential_request:{request['request_id']}")
    assert before['status'] == 'waiting'
    quote = await _quote(service, token)
    result = await service.confirm(token, quote['id'])
    after = await pool.fetchrow('SELECT * FROM coordinator_wakeups WHERE id=$1', before['id'])
    assert after['status'] == 'queued'
    assert after['context'] == context and after['send_to_phone']
    assert after['payload']['credential_id'] == result['credential_id']
    numbers.buy.assert_awaited_once()
    await pool.execute('DELETE FROM coordinator_wakeups WHERE id=$1', before['id'])


async def test_coordinator_free_account_short_of_the_floor_gets_funds_then_existing_purchase_wakeup(phone_db,
                                                                                                    monkeypatch):
    from coder.coordinator.tools import CoordinatorTools
    from tests.test_coordinator import FakePurchases
    from utils.feature_gates import require_feature

    pool, service, token, numbers = phone_db
    # Exercise the real rollout with a phone-only identity, like WhatsApp signup.
    monkeypatch.setattr(purchase, "require_feature", require_feature)
    monkeypatch.setattr(purchase, "get_user_email", AsyncMock(return_value=None))
    purchases = FakePurchases()
    monkeypatch.setitem(capabilities._providers, capabilities.PURCHASES, purchases)
    monkeypatch.setattr("billing.plan_limits.registered_plan_limits", lambda: object())
    tier = {"value": "free"}
    monkeypatch.setattr(purchase, "get_user_tier_from_db", AsyncMock(side_effect=lambda *a: tier["value"]))
    monkeypatch.setattr("billing.plan_limits.get_effective_tier", AsyncMock(side_effect=lambda *a: tier["value"]))
    monkeypatch.setattr("billing.plan_limits.on_old_plans", AsyncMock(return_value=False))
    usage_tracker.fetch_credit_remaining.return_value = 4.99 * float(CREDITS_PER_DOLLAR)  # $4.99, short of the $5 floor
    monkeypatch.setattr("utils.coordinator_links.dispatch_link", lambda *a: None)
    context = {"epoch": "", "depth": 0, "request": "Call my dentist to ask about availability",
               "channel": "whatsapp_text"}
    tools = CoordinatorTools(pool=pool, sio=None, user_id=USER, organization_id=None,
                             conversation_id=f"coordinator:{USER}", phone_only=True,
                             reply_channel="whatsapp_text", continuation=context)
    # Finding numbers is browsing, open on any balance; asking for one starts a purchase, which keeps the
    # gate's funds offer (never a plan) and starts no paid-resource request short of the floor.
    found = await tools.execute("find_phone_numbers", {"country": "US"})
    assert found["country"] == "US" and found["numbers"]
    result = await tools.execute("request_phone_number", {"purpose": context["request"]})
    assert result["kind"] == "credits" and "at least $5" in result["error"]
    assert len(result["purchase_links"]) == 2
    assert all(p["kind"] == "funds" for p in purchases.minted)
    assert all(p["continuation"] == context and p["send_to_phone"] for p in purchases.minted)
    numbers.search.reset_mock()
    numbers.buy.assert_not_awaited()
    assert not await pool.fetchval("SELECT count(*) FROM coordinator_wakeups WHERE user_id=$1::uuid", USER)

    # Resume after the existing payment wakeup, with the same original request: the funds landed, still on Free.
    usage_tracker.fetch_credit_remaining.return_value = 100
    result = await tools.execute("request_phone_number", {"purpose": context["request"]})
    assert result["auto_resume"] and result["approval_url"].endswith(token)
    numbers.buy.assert_not_awaited()
    quote = await _quote(service, token)
    bought = await service.confirm(token, quote["id"])
    wakeup = await pool.fetchrow("SELECT * FROM coordinator_wakeups WHERE await_key=$1",
                                f"credential_request:{result['request_id']}")
    try:
        assert wakeup["status"] == "queued" and wakeup["context"] == context
        assert wakeup["payload"]["credential_id"] == bought["credential_id"]
        found = await tools.execute("search_credential_tools", {"query": "place call", "credential_id": bought["credential_id"]})
        call = next(op for op in found["operations"] if op["operation"] == "place_call")
        assert call["credentials"][0]["id"] == bought["credential_id"] and call["tool_names"]
        numbers.buy.assert_awaited_once()
    finally:
        await pool.execute("DELETE FROM coordinator_wakeups WHERE id=$1", wakeup["id"])


async def test_setup_low_credits_offers_funds_and_restricted_rollout_offers_no_upgrade(phone_db, monkeypatch):
    from coder.coordinator.tools import CoordinatorTools
    from tests.test_coordinator import FakePurchases
    from utils.feature_gates import FeatureNotAvailable

    pool, service, token, numbers = phone_db
    purchases = FakePurchases()
    monkeypatch.setitem(capabilities._providers, capabilities.PURCHASES, purchases)
    monkeypatch.setattr("billing.plan_limits.registered_plan_limits", lambda: object())
    monkeypatch.setattr(usage_tracker, "fetch_credit_remaining", AsyncMock(return_value=0))
    tools = CoordinatorTools(pool=pool, sio=None, user_id=USER, organization_id=None,
                             conversation_id=f"coordinator:{USER}")
    # On the old plans a paid account short of credits is offered monthly top-ups, as main offered.
    old_plans = AsyncMock(return_value=True)
    monkeypatch.setattr("billing.plan_limits.on_old_plans", old_plans)
    result = await tools.execute("request_phone_number", {"purpose": "Call my dentist", "phone_number": NUMBER,
                                                          "country": "US"})
    assert result["kind"] == "credits" and result["purchase_links"]
    assert purchases.minted and all(p["kind"] == "topup" for p in purchases.minted)
    purchases.minted.clear()
    old_plans.return_value = False
    # A chosen number's own price is what the account must cover (one not chosen yet is priced when it is).
    result = await tools.execute("request_phone_number", {"purpose": "Call my dentist", "phone_number": NUMBER,
                                                          "country": "US"})
    assert result["kind"] == "credits" and result["purchase_links"]
    assert purchases.minted and all(p["kind"] == "funds" for p in purchases.minted)
    purchases.minted.clear()
    monkeypatch.setattr(purchase, "require_feature", MagicMock(side_effect=FeatureNotAvailable("phone_numbers")))
    result = await tools.execute("request_phone_number", {"purpose": "Call my dentist"})
    assert not result["success"] and "available on your account" in result["error"]
    assert "purchase_links" not in result and not purchases.minted
    numbers.search.assert_not_awaited()
    numbers.buy.assert_not_awaited()


async def test_floor_denial_at_confirm_is_definitive_and_keeps_http_error_contract(phone_db, monkeypatch):
    from billing.gates import GateDenied, Offer

    pool, service, token, numbers = phone_db
    quote = await _quote(service, token)
    short = ("Buying phone numbers needs at least $5 of funds the account added (included usage doesn't count); "
             "it has $4.99.")
    monkeypatch.setattr(handler, "check_product",
                        AsyncMock(side_effect=GateDenied("credits", short, Offer(funds_usd=0.01))))
    result = await service.confirm(token, quote["id"])
    assert result["status"] == "pending" and result["quote"] is None
    assert result["error"] == short
    numbers.buy.assert_not_awaited()
    # Looking at numbers isn't buying one: the page's search still answers.
    assert (await routes.response(service.search(country="US")))["numbers"]
