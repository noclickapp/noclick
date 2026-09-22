"""Paid credential links: real PostgreSQL claims, isolated provider side effects."""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from repositories.credentials import CredentialsRepo
from utils import capabilities, phone_purchase as purchase, phone_purchase_routes as routes
from utils.phone_numbers import PhonePurchaseRejected
from wss.handlers import phone_number_handler as handler

USER = "00000000-0000-0000-0000-000000000001"
NUMBER = "+15674833618"
pytestmark = pytest.mark.asyncio


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
        search=AsyncMock(return_value=[{"phone_number": NUMBER, "locality": "Lucas", "region": "OH", "capabilities": ["voice"]}]),
        buy=AsyncMock(return_value={"phone_number": NUMBER, "number_sid": "PN_test"}), release=AsyncMock(),
    )
    capabilities.provide(capabilities.PHONE_NUMBERS, numbers)
    monkeypatch.setattr(purchase, "require_feature", lambda *a, **k: None)
    monkeypatch.setattr(purchase, "get_user_tier_from_db", AsyncMock(return_value="pro"))
    monkeypatch.setattr("billing.plan_limits.get_effective_tier", AsyncMock(return_value="pro"))
    monkeypatch.setattr("billing.plan_limits.check_credential_limit", AsyncMock(return_value=(True, None)))
    monkeypatch.setattr("repositories.credentials.log_activity_background", lambda *a, **k: None)
    monkeypatch.setattr(handler.usage_tracker, "resolve_billing_user_id", AsyncMock(return_value=USER))
    monkeypatch.setattr(handler.usage_tracker, "fetch_credit_remaining", AsyncMock(return_value=100))
    monkeypatch.setattr(handler, "start_connection_charge", AsyncMock())
    monkeypatch.setattr(purchase, "get_encryption", lambda: MagicMock(encrypt_credential=lambda blob: "test-encrypted"))
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
    quote = (await service.quote(token, NUMBER))["quote"]
    assert quote["monthly_credits"] == 15
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
    quote = (await service.quote(token, NUMBER))["quote"]
    if invalid == "quote_id":
        quote["id"] = str(uuid4())
    elif invalid in ("quote_expired", "price"):
        changed = dict(quote)
        if invalid == "price": changed["monthly_credits"] = 1
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
    first = (await service.quote(token, NUMBER))["quote"]
    await service.quote(token, NUMBER)
    with pytest.raises(HTTPException): await service.confirm(token, first["id"])
    numbers.buy.assert_not_awaited()


@pytest.mark.parametrize("error,reopens", [(PhonePurchaseRejected("Unavailable"), True), (TimeoutError("unknown"), False)])
async def test_definitive_rejection_vs_uncertain_provider_result(phone_db, error, reopens):
    _, service, token, numbers = phone_db
    quote = (await service.quote(token, NUMBER))["quote"]
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
    quote = (await service.quote(token, NUMBER))["quote"]
    monkeypatch.setattr(service.repo, "fulfill_phone_purchase", AsyncMock(side_effect=RuntimeError("DB failed")))
    result = await service.confirm(token, quote["id"])
    assert result["status"] == "provisioning"  # release errors would also remain quarantined
    assert await pool.fetchval("SELECT count(*) FROM credentials WHERE owner_id=$1::uuid AND credential_type='phone_number'", USER) == 0
    numbers.release.assert_awaited_once_with("PN_test")
    await service.confirm(token, quote["id"])
    numbers.buy.assert_awaited_once()


async def test_request_refresh_preserves_review_and_inflight_purchase(phone_db):
    _, service, token, numbers = phone_db
    quote = (await service.quote(token, NUMBER))["quote"]
    for in_flight in (False, True):
        if in_flight: await service.repo.claim_phone_purchase(token, USER, quote["id"], 15)
        result = await service.create("A second description", "+14155551234")
        assert result["quote"] == quote and result["purpose"] == "Receptionist"
        assert result["approval_url"].endswith(token)
    numbers.buy.assert_not_awaited()


async def test_abandoned_purchase_surfaces_uncertainty_without_buying_again(phone_db):
    pool, service, token, numbers = phone_db
    quote = (await service.quote(token, NUMBER))["quote"]
    await service.repo.claim_phone_purchase(token, USER, quote["id"], 15)
    await pool.execute("UPDATE credential_requests SET provisioning_started_at=now()-interval '3 minutes' WHERE token=$1", token)
    result = await service.confirm(token, quote["id"])
    assert result["status"] == "provisioning" and "contact support" in result["error"]
    numbers.buy.assert_not_awaited()


async def test_owner_auth_and_request_scope_http(phone_db, monkeypatch):
    pool, service, token, numbers = phone_db
    quote = (await service.quote(token, NUMBER))["quote"]
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
        for path, body in (("/search", {}), ("/quote", {"phone_number": NUMBER}), ("/confirm", {"quote_id": quote["id"]})):
            assert (await client.post(url+path, headers=headers, json=body)).status_code == 404
        verifier.return_value = {"sub": USER}
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
        quote = (await service.quote(token, NUMBER))["quote"]
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


async def test_coordinator_advertises_only_available_purchase_tools(phone_db):
    from coder.coordinator.tools import CoordinatorTools, coordinator_tool_params
    pool, service, token, numbers = phone_db
    names = lambda params: {p["function"]["name"] for p in params}
    assert "request_phone_number" not in names(coordinator_tool_params())
    tools = CoordinatorTools(pool=pool, sio=None, user_id=USER, organization_id=None, conversation_id=f"coordinator:{USER}")
    assert {"find_phone_numbers", "request_phone_number", "phone_number_request_status"} <= names(tools.tool_params())
    result = await tools.request_phone_number("Receptionist", NUMBER)
    assert result["status"] == "pending" and result["approval_url"].endswith(token)
    assert (await tools.phone_number_request_status(result["request_id"]))["quote"] == result["quote"]
    numbers.buy.assert_not_awaited()
    other = CoordinatorTools(pool=pool, sio=None, user_id=str(uuid4()), organization_id=None, conversation_id="other")
    assert (await other.phone_number_request_status(result["request_id"]))["success"] is False
