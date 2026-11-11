"""Behavior checks for Bitsnap's Connect wire format and documented deliveries."""
import hashlib
import hmac
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes.bitsnap_node import (
    BitsnapAPIKeyCredential, BitsnapNode, BitsnapNodeConfig, CONFIG_MODELS, WEBHOOK_EVENTS,
)

CREDENTIAL = {"credential_type": "bitsnap_api_key", "api_key": "bs_test_fixture_credential"}
EVENTS = json.loads((Path(__file__).parent / "fixtures/bitsnap/events.json").read_text())


def node(config):
    return BitsnapNode(node_id="bitsnap", node_type="automation-bitsnap", node_data={},
                       config=BitsnapNodeConfig.model_validate({"config": config, "credentials": CREDENTIAL}))


def transport(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))


@pytest.mark.asyncio
async def test_identity_read_bearer_and_empty_json_body(monkeypatch):
    def handler(request):
        assert str(request.url) == "https://bitsnap.pl/api/v1/bitsnap.v1.AccountService/GetAccount"
        assert request.headers["Authorization"] == "Bearer bs_test_fixture_credential"
        assert json.loads(request.content) == {}
        assert "Origin" not in request.headers
        return httpx.Response(200, json={"projectId": "18", "projectName": "Shop", "environment": "ENVIRONMENT_TEST"})
    transport(monkeypatch, handler)
    result = await node({"operation": "get_account"}).execute({})
    assert result["data"]["projectId"] == "18"


@pytest.mark.asyncio
async def test_nested_checkout_and_idempotency_header(monkeypatch):
    def handler(request):
        assert request.url.path.endswith("CheckoutService/CreateCheckoutLink")
        assert request.headers["Idempotency-Key"] == "cart-42"
        assert json.loads(request.content) == {"items": [{"productId": "product-1", "quantity": 2}], "clientReferenceId": "cart-42"}
        return httpx.Response(200, json={"url": "https://shop.bitsnap.pl/checkout/example"})
    transport(monkeypatch, handler)
    await node({"operation": "create_checkout_link", "items": [{"product_id": "product-1", "quantity": 2}], "client_reference_id": "cart-42", "idempotency_key": "cart-42"}).execute({})


@pytest.mark.asyncio
async def test_product_update_omits_unset_and_keeps_revision(monkeypatch):
    def handler(request):
        assert request.url.path.endswith("ProductsService/UpdateProduct")
        assert json.loads(request.content) == {"id": "product-1", "revision": 3, "availableQuantity": 0, "images": [], "variants": []}
        return httpx.Response(200, json={"product": {"id": "product-1", "revision": 4}})
    transport(monkeypatch, handler)
    await node({"operation": "update_product", "id": "product-1", "revision": 3, "available_quantity": 0}).execute({})


@pytest.mark.asyncio
async def test_cursor_passes_through_and_is_one_request(monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        body = json.loads(request.content)
        assert body["cursor"] == "opaque-token"
        assert body["createdFrom"] == "2026-01-01T00:00:00Z"
        return httpx.Response(200, json={"orders": [], "nextCursor": "next-token"})
    transport(monkeypatch, handler)
    result = await node({"operation": "list_orders", "cursor": "opaque-token", "created_from": "2026-01-01T00:00:00Z"}).execute({})
    assert result["data"]["nextCursor"] == "next-token"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_api_rejection_propagates_provider_reason_and_redacts_key(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(403, json={"code": "permission_denied", "message": "[writes_disabled] bs_test_fixture_credential"}))
    with pytest.raises(ValueError, match=r"\[writes_disabled\] \[redacted\]"):
        await node({"operation": "get_account"}).execute({})


@pytest.mark.parametrize("value", ["Bearer bs_test_key", "https://bitsnap.pl/key", "key\r\nInjected: value"])
def test_refuse_bad_credentials(value):
    with pytest.raises(ValidationError):
        BitsnapAPIKeyCredential(api_key=value)


def test_required_fields_defaults_and_timestamp_bounds():
    assert BitsnapAPIKeyCredential(api_key="bs_test_example").credential_type == "bitsnap_api_key"
    with pytest.raises(ValidationError):
        CONFIG_MODELS["create_payment_link"].model_validate({"name": "Consultation", "price": {"amount": 0, "currency": "PLN"}})
    with pytest.raises(ValidationError):
        CONFIG_MODELS["create_product"].model_validate({"name": "Product"})
    with pytest.raises(ValidationError):
        CONFIG_MODELS["get_sales_summary"].model_validate({"from_time": "2026-02-01T00:00:00Z", "to_time": "2026-01-01T00:00:00Z"})
    with pytest.raises(ValidationError):
        CONFIG_MODELS["delete_coupon"].model_validate({"id": "coupon", "idempotency_key": "bad\nkey"})


@pytest.mark.asyncio
async def test_register_and_unregister_persist_only_provider_state(monkeypatch):
    calls = []
    def handler(request):
        calls.append((request.url.path, json.loads(request.content)))
        if request.url.path.endswith("CreateWebhook"):
            return httpx.Response(200, json={"webhook": {"id": "hook-1"}, "signingSecret": "whsec_documented"})
        return httpx.Response(200, json={})
    transport(monkeypatch, handler)
    state = await BitsnapNode._register_external_webhook(webhook_url="https://unit.hooks.example.test/webhook/one", credential=CREDENTIAL, config={"operation": "on_event", "event_type": "TRANSACTION_SUCCESS"}, node_id="one")
    assert state == {"external_webhook_id": "hook-1", "signing_secret": "whsec_documented"}
    assert calls[0][1]["events"] == ["TRANSACTION_SUCCESS"]
    await BitsnapNode._unregister_external_webhook(credential=CREDENTIAL, config=state, node_id="one")
    assert calls[1][0].endswith("WebhooksService/DeleteWebhook")
    assert calls[1][1] == {"id": "hook-1"}


@pytest.mark.parametrize("event", WEBHOOK_EVENTS)
def test_each_documented_event_is_signed_filtered_and_human_shaped(event):
    body = EVENTS[event]["body"]
    raw = json.dumps(body).encode()
    secret = "whsec_documented"
    headers = {"X-Content-Signature": hmac.new(secret.encode(), raw, hashlib.sha512).hexdigest()}
    assert BitsnapNode.verify_webhook_signature(raw, headers, {"signing_secret": secret})
    assert not BitsnapNode.verify_webhook_signature(raw + b" ", headers, {"signing_secret": secret})
    assert not BitsnapNode.verify_webhook_signature(raw, {}, {"signing_secret": secret})
    assert BitsnapNode.filter_trigger_payload(body, {"event_type": "ALL"})
    assert BitsnapNode.filter_trigger_payload(body, {"event_type": event})
    assert not BitsnapNode.filter_trigger_payload(body, {"event_type": "different-event"})
    assert BitsnapNode.resolve_trigger_payload(body, {}) == body
    turn = BitsnapNode.resolve_agent_event(body)
    assert body["eventData"]["id"] in turn["text"]
    assert body["eventData"]["eventId"] in turn["text"]
    assert "18:" in turn["conversation_key"]
    assert EVENTS[event]["source"] == "https://docs.bitsnap.pl/reference/webhook-events/"


@pytest.mark.asyncio
async def test_manual_trigger_run_waits_for_event():
    result = await node({"operation": "on_event"}).execute({})
    assert result["status"] == "no_event"
