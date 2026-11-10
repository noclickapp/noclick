"""Exercise the real HTTP serialization and poll lifecycle with publisher fixtures."""
import copy
import json
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from pydantic import ValidationError

from nodes import mercado_pago_node as mp

FIXTURES = Path(__file__).parent / "fixtures/mercado-pago"
TOKEN = "mercado-pago-test-secret"
KEY = "550e8400-e29b-41d4-a716-446655440000"


def fixture(name):
    return json.loads((FIXTURES / (name + ".json")).read_text())


def node(config):
    return mp.MercadoPagoNode(node_id="mp-test", node_type=mp.MercadoPagoNode.integration_type,
        node_data={"config": config}, config=mp.MercadoPagoNodeConfig.model_validate({
            "config": config, "credentials": {"access_token": TOKEN}}), sio=Mock())


def transport(monkeypatch, respond):
    calls = []
    def handler(request):
        calls.append(request)
        return respond(request)
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as session:
            yield session
    monkeypatch.setattr(mp, "guarded_async_client", client)
    return calls


CASES = [
    ("search_payments", {}, "GET", "/v1/payments/search", None, "payment_search"),
    ("get_payment", {"payment_id": 17014025134}, "GET", "/v1/payments/17014025134", None, "payment_create"),
    ("create_payment", {"idempotency_key": KEY, "transaction_amount": 58.8, "payment_method_id": "visa", "payer_email": "test_user@testuser.com", "token": "token-001"}, "POST", "/v1/payments", {"transaction_amount": 58.8, "payment_method_id": "visa", "payer": {"email": "test_user@testuser.com"}, "token": "token-001", "installments": 1}, "payment_create"),
    ("update_payment", {"payment_id": 17014025134, "capture": True}, "PUT", "/v1/payments/17014025134", {"capture": True}, "payment_update"),
    ("create_refund", {"payment_id": 17014025134, "idempotency_key": KEY, "amount": 10}, "POST", "/v1/payments/17014025134/refunds", {"amount": 10}, "refund_create"),
    ("list_refunds", {"payment_id": 17014025134}, "GET", "/v1/payments/17014025134/refunds", None, "refund_list_all"),
    ("get_refund", {"payment_id": 17014025134, "refund_id": 123}, "GET", "/v1/payments/17014025134/refunds/123", None, "refund_get"),
    ("create_preference", {"items_json": '[{"title":"Premium Plan","quantity":1,"unit_price":99.9}]'}, "POST", "/checkout/preferences", {"items": [{"title": "Premium Plan", "quantity": 1, "unit_price": 99.9}]}, "preference_create"),
    ("get_preference", {"id": "pref-1"}, "GET", "/checkout/preferences/pref-1", None, "preference_get"),
    ("update_preference", {"id": "pref-1", "items_json": '[{"title":"Premium Plan","quantity":1,"unit_price":99.9}]', "payer_email": "customer@example.com"}, "PUT", "/checkout/preferences/pref-1", {"items": [{"title": "Premium Plan", "quantity": 1, "unit_price": 99.9}], "payer": {"email": "customer@example.com"}}, "preference_update"),
    ("search_preferences", {"offset": 30, "external_reference": "order + café"}, "GET", "/checkout/preferences/search", None, "preference_search"),
    ("create_customer", {"email": "test_user@testuser.com", "first_name": "Test"}, "POST", "/v1/customers", {"email": "test_user@testuser.com", "first_name": "Test"}, "customer_create"),
    ("update_customer", {"id": "customer-1", "email": "test_user@testuser.com"}, "PUT", "/v1/customers/customer-1", {"email": "test_user@testuser.com"}, "customer_update"),
    ("get_customer", {"id": "customer-1"}, "GET", "/v1/customers/customer-1", None, "customer_get"),
    ("search_customers", {"email": "test_user@testuser.com"}, "GET", "/v1/customers/search", None, "customer_search"),
    ("create_subscription", {"reason": "Monthly subscription", "payer_email": "test_user@testuser.com", "transaction_amount": 29.9, "currency_id": "BRL"}, "POST", "/preapproval", {"reason": "Monthly subscription", "payer_email": "test_user@testuser.com", "auto_recurring": {"frequency": 1, "frequency_type": "months", "transaction_amount": 29.9, "currency_id": "BRL"}, "status": "pending"}, "preapproval_create"),
    ("get_subscription", {"id": "sub-1"}, "GET", "/preapproval/sub-1", None, "preapproval_get"),
    ("update_subscription", {"id": "sub-1", "status": "cancelled"}, "PUT", "/preapproval/sub-1", {"status": "cancelled"}, "preapproval_update"),
    ("search_subscriptions", {"status": "authorized"}, "GET", "/preapproval/search", None, "preapproval_search"),
    ("get_subscription_invoice", {"id": 123}, "GET", "/authorized_payments/123", None, None),
    ("get_merchant_order", {"id": 123}, "GET", "/merchant_orders/123", None, None),
    ("get_chargeback", {"id": "123"}, "GET", "/v1/chargebacks/123", None, None),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,body,response_fixture", CASES, ids=[c[0] for c in CASES])
async def test_mercado_pago_published_request_mapping(monkeypatch, operation, config, method, path, body, response_fixture):
    response = fixture(response_fixture) if response_fixture else {"id": 123}
    calls = transport(monkeypatch, lambda r: httpx.Response(201 if method == "POST" else 200, json=response))
    result = await node({"operation": operation, **config}).execute({})
    assert result == {"status": "success", "data": response}
    assert len(calls) == 1
    request = calls[0]
    assert request.method == method and request.url.host == "api.mercadopago.com" and request.url.path == path
    assert request.headers["authorization"] == "Bearer " + TOKEN
    assert TOKEN not in str(request.url)
    if body is not None:
        assert json.loads(request.content) == body
    else:
        assert request.content == b""
    if "idempotency_key" in config:
        assert request.headers["x-idempotency-key"] == KEY
    if operation == "search_preferences":
        assert dict(request.url.params) == {"limit": "30", "offset": "30", "external_reference": "order + café"}
    if operation == "search_payments":
        assert dict(request.url.params) == {"limit": "30", "offset": "0", "sort": "date_created", "criteria": "desc"}


@pytest.mark.asyncio
async def test_mercado_pago_full_refund_keeps_empty_body_and_stable_key(monkeypatch):
    calls = transport(monkeypatch, lambda r: httpx.Response(201, json=fixture("refund_create")))
    config = {"operation": "create_refund", "payment_id": 17014025134, "idempotency_key": KEY}
    await node(config).execute({})
    await node(config).execute({})
    assert all(json.loads(r.content) == {} and r.headers["x-idempotency-key"] == KEY for r in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 403, 404, 422, 429, 500])
async def test_mercado_pago_rejections_are_not_success_and_redact_token(monkeypatch, status):
    calls = transport(monkeypatch, lambda r: httpx.Response(status, json={"message": "Rejected " + TOKEN}))
    with pytest.raises(ValueError) as error:
        await node({"operation": "search_payments"}).execute({})
    assert str(status) in str(error.value) and "Rejected" in str(error.value) and TOKEN not in str(error.value)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_mercado_pago_poll_baseline_dedup_and_update_with_official_sdk_payload(monkeypatch):
    response = fixture("payment_search")  # Publisher search fixture omits date_last_updated.
    calls = transport(monkeypatch, lambda r: httpx.Response(200, json=response))
    poll = node({"operation": "on_new_or_updated_payment", "external_reference": "order-1"})
    state = {}
    async def update(mutator, **kwargs):
        value, result = mutator(copy.deepcopy(state))
        if value is not None:
            state.clear(); state.update(value)
        return result
    poll._update_node_state = update
    assert (await poll.execute({}))["payments"] == []
    assert (await poll.execute({}))["payments"] == []
    # The documented create fixture contains the same payment in a different state.
    response = {"results": [fixture("payment_create")], "paging": {"total": 1}}
    result = await poll.execute({})
    assert result["new_payment_count"] == 1 and poll.trigger_emitted_event(result)
    event = mp.MercadoPagoNode.resolve_agent_event(result)
    assert "17014025134" in event["text"] and "pending" in event["text"] and "BRL" in event["text"]
    assert (await poll.execute({}))["payments"] == []
    query = calls[0].url.params
    assert query["sort"] == query["range"] == "date_last_updated" and query["external_reference"] == "order-1"
    assert datetime_value(query["end_date"]) > datetime_value(query["begin_date"])
    # A changed watched resource gets a fresh baseline.
    poll._config.config.external_reference = "another-order"
    assert (await poll.execute({}))["payments"] == []


def datetime_value(value):
    from datetime import datetime
    return datetime.fromisoformat(value)


@pytest.mark.asyncio
async def test_mercado_pago_poll_paginates_before_advancing_state(monkeypatch):
    payment = fixture("payment_create")
    calls = transport(monkeypatch, lambda r: httpx.Response(200, json={"results": [payment] * 100 if r.url.params["offset"] == "0" else [payment], "paging": {"total": 101}}))
    poll = node({"operation": "on_new_or_updated_payment"})
    seen = []
    async def capture(items, key):
        seen.extend(items)
        return items
    poll._filter_unseen = capture
    assert (await poll.execute({}))["new_payment_count"] == 101
    assert len(seen) == 101 and [r.url.params["offset"] for r in calls] == ["0", "100"]


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [{}, {"results": None}, {"results": [{}]}, {"results": [{"id": 1}]}])
async def test_mercado_pago_bad_poll_response_never_advances_state(monkeypatch, response):
    transport(monkeypatch, lambda r: httpx.Response(200, json=response))
    poll = node({"operation": "on_new_or_updated_payment"})
    async def forbidden(*args):
        pytest.fail("Malformed poll must not advance state")
    poll._filter_unseen = forbidden
    with pytest.raises(ValueError):
        await poll.execute({})


def test_mercado_pago_catalog_and_manual_connect():
    assert len(mp.ROUTES) == len(CASES) == 22
    credential = mp.MercadoPagoAccessToken(access_token=TOKEN)
    assert credential.credential_type == "mercado_pago_access_token"
    assert mp.MercadoPagoNode.connection_evidence.operation == "search_payments"
    assert mp.MercadoPagoNode.resolve_agent_event({"payments": []}) is None


@pytest.mark.parametrize("secret", ["", "https://example.com/token", "Bearer secret", "secret\nkey"])
def test_mercado_pago_invalid_tokens(secret):
    with pytest.raises((ValidationError, ValueError)):
        mp.MercadoPagoAccessToken(access_token=secret)
