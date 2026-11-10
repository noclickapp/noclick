"""Akeneo request mapping and provider-published response regressions."""
import hashlib
import hmac
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import akeneo_node as native
from nodes.core.registry import NodeFactory

FIXTURES = Path(__file__).parent / "fixtures" / "akeneo"
TOKEN = "akeneo-fixture-private-123"
CREDS = {"credential_type": "akeneo_token", "pim_url": "https://demo.akeneo.com", "access_token": TOKEN}
UUID = "3fa85f64-5717-4562-b3fc-2c963f66afa6"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="akeneo-test", node_type="automation-akeneo",
        node_data={"config": config, "credentials": CREDS})


def intercept(monkeypatch, respond):
    calls = []
    def handle(request):
        calls.append(request)
        return respond(request)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


@pytest.mark.asyncio
async def test_documented_product_list_and_bearer(monkeypatch):
    body = json.loads((FIXTURES / "products.json").read_text())
    calls = intercept(monkeypatch, lambda _: httpx.Response(200, json=body))
    result = await node({"operation": "list_products", "search": '{"updated":[{"operator":"SINCE LAST N DAYS","value":4}]}'}).execute({})
    assert result["items"] == body["_embedded"]["items"]
    assert result["links"] == body["_links"]
    assert calls[0].headers["Authorization"] == "Bearer " + TOKEN
    assert calls[0].url.path == "/api/rest/v1/products-uuid"
    assert json.loads(calls[0].url.params["search"])["updated"][0]["value"] == 4
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_creation_exposes_documented_location_receipt(monkeypatch):
    location = CREDS["pim_url"] + "/api/rest/v1/products-uuid/" + UUID
    calls = intercept(monkeypatch, lambda _: httpx.Response(201, headers={"Location": location}))
    result = await node({"operation": "create_product", "uuid": UUID}).execute({})
    assert result["location"] == location
    assert result["acknowledged"] and not result["readback_verified"]
    assert calls[0].method == "POST" and json.loads(calls[0].content)["uuid"] == UUID


@pytest.mark.asyncio
async def test_update_preserves_false_empty_and_null(monkeypatch):
    calls = intercept(monkeypatch, lambda _: httpx.Response(204))
    result = await node({"operation": "upsert_product", "uuid": UUID, "enabled": False,
                         "categories": [], "parent": None}).execute({})
    assert calls[0].method == "PATCH"
    assert calls[0].url.path == "/api/rest/v1/products-uuid/" + UUID
    assert json.loads(calls[0].content) == {"enabled": False, "categories": [], "parent": None}
    assert result["acknowledged"] and not result["readback_verified"]


@pytest.mark.asyncio
async def test_exact_route_encoding_and_option_write(monkeypatch):
    calls = intercept(monkeypatch, lambda _: httpx.Response(204))
    await node({"operation": "upsert_attribute_option", "attribute_code": "color", "code": "blue",
                "labels": {"en_US": "Blue"}, "sort_order": 0}).execute({})
    assert calls[0].url.path == "/api/rest/v1/attributes/color/options/blue"
    assert json.loads(calls[0].content) == {"labels": {"en_US": "Blue"}, "sort_order": 0}


@pytest.mark.asyncio
async def test_subscription_registration_and_cleanup(monkeypatch):
    subscription = "018e1e57-8e96-7695-895e-34bb1f5c0614"
    subscriber = "018e1ec5-29da-78ad-aae6-92065b9ca2a5"
    config = {"operation": "on_product_event", "subscriber_id": subscriber, "pim_client_id": "fixture-client"}
    calls = intercept(monkeypatch, lambda request: httpx.Response(201 if request.method == "POST" else 200,
                       json=json.loads((FIXTURES / "subscription.json").read_text())))
    registration = await native.AkeneoNode._register_external_webhook(
        webhook_url="https://fixture.hooks.example.test", credential=CREDS, config=config, node_id="fixture")
    body = json.loads(calls[0].content)
    assert calls[0].url.host == "event.prd.sdk.akeneo.cloud"
    assert calls[0].url.path == f"/api/v1/subscribers/{subscriber}/subscriptions"
    assert calls[0].headers["x-pim-token"] == TOKEN
    assert calls[0].headers["x-pim-url"] == CREDS["pim_url"]
    assert calls[0].headers["x-pim-client-id"] == "fixture-client"
    assert "authorization" not in calls[0].headers
    assert body["type"] == "https" and body["events"] == list(native.PRODUCT_EVENTS)
    assert body["config"]["url"] == "https://fixture.hooks.example.test"
    assert body["config"]["secret"]["primary"] == registration["signing_secret"]
    assert len(registration["signing_secret"]) >= 16
    await native.AkeneoNode._unregister_external_webhook(
        credential=CREDS, config={**config, **registration}, node_id="fixture")
    assert calls[1].method == "DELETE"
    assert calls[1].url.path == f"/api/v1/subscribers/{subscriber}/subscriptions/{subscription}"


@pytest.mark.asyncio
async def test_create_and_choose_event_subscriber(monkeypatch):
    body = json.loads((FIXTURES / "subscriber.json").read_text())
    calls = intercept(monkeypatch, lambda request: httpx.Response(
        201 if request.method == "POST" else 200, json=body if request.method == "POST" else [body]))
    result = await node({"operation": "create_event_subscriber", "pim_client_id": "fixture-client",
                         "name": "translation app", "technical_email": "john.doe@example.com"}).execute({})
    assert result["data"]["id"] == body["id"]
    assert calls[0].url.path == "/api/v1/subscribers"
    assert json.loads(calls[0].content) == {"name": "translation app", "contact": {"technical_email": "john.doe@example.com"}}
    choices = await native.AkeneoNode.load_field_options("subscriber_id", CREDS, {"pim_client_id": "fixture-client"})
    assert choices["options"] == [{"value": body["id"], "label": "translation app"}]
    assert calls[1].method == "GET"


@pytest.mark.parametrize("kind", ["created", "updated", "deleted"])
def test_published_events_signatures_and_agent_turn(kind):
    fixtures = json.loads((FIXTURES / "events.json").read_text())
    event_type = "com.akeneo.pim.v1.product." + kind
    payload = fixtures[event_type]["body"]
    raw = json.dumps(payload).encode()
    secret = "akeneo-unit-test-signing-secret"
    headers = {"X-AKENEO-SIGNATURE-PRIMARY": hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest(),
               "X-AKENEO-SIGNATURE-ALGORITHM": "HmacSHA256"}
    config = {"signing_secret": secret, "events": list(native.PRODUCT_EVENTS)}
    assert native.AkeneoNode.verify_webhook_signature(raw, headers, config)
    assert not native.AkeneoNode.verify_webhook_signature(raw + b" ", headers, config)
    assert not native.AkeneoNode.verify_webhook_signature(raw, headers, {})
    assert not native.AkeneoNode.verify_webhook_signature(raw, {"X-AKENEO-SIGNATURE-PRIMARY": "é" * 64}, config)
    assert not native.AkeneoNode.verify_webhook_signature(raw, {"X-AKENEO-SIGNATURE-PRIMARY": "0" * 64}, config)
    assert not native.AkeneoNode.verify_webhook_signature(raw, {**headers, "X-AKENEO-SIGNATURE-ALGORITHM": "none"}, config)
    assert native.AkeneoNode.filter_trigger_payload(payload, config)
    assert not native.AkeneoNode.filter_trigger_payload({"type": "other"}, config)
    output = native.AkeneoNode.resolve_trigger_payload(payload, config)
    event = native.AkeneoNode.resolve_agent_event(output)
    assert payload["data"]["product"]["uuid"] in event["text"]
    assert payload["data"]["author"]["identifier"] in event["text"]
    assert payload["subject"] in event["text"] and payload["id"] in event["text"]
    assert kind in event["text"]
    assert "Get Product" not in event["text"] if kind == "deleted" else "Get Product" in event["text"]


@pytest.mark.asyncio
async def test_trigger_manual_run_has_no_event():
    result = await node({"operation": "on_product_event", "pim_client_id": "fixture-client",
                         "subscriber_id": "018e1ec5-29da-78ad-aae6-92065b9ca2a5"}).execute({})
    assert result["status"] == "no_event"


@pytest.mark.asyncio
async def test_http_failure_redacts_response(monkeypatch):
    intercept(monkeypatch, lambda _: httpx.Response(401, json={"message": TOKEN}))
    with pytest.raises(ValueError) as exc:
        await node({"operation": "list_products"}).execute({})
    assert "401" in str(exc.value) and TOKEN not in str(exc.value)


def test_credentials_and_input_validation():
    cred = native.AkeneoTokenCredential.model_validate({"pim_url": "demo.akeneo.com/dashboard", "access_token": TOKEN})
    assert cred.credential_type == "akeneo_token" and cred.pim_url == "https://demo.akeneo.com"
    for change in ({"pim_url": "http://demo.akeneo.com"}, {"pim_url": "https://user:pass@demo.akeneo.com"}, {"access_token": "Bearer " + TOKEN}):
        with pytest.raises(ValidationError):
            native.AkeneoTokenCredential.model_validate({**CREDS, **change})
    for config in ({"operation": "get_product", "uuid": "invalid"},
                   {"operation": "list_products", "search": "[]"},
                   {"operation": "upsert_product", "uuid": UUID, "values": {"sku": [{"data": "top", "linked_data": {}}]}}):
        with pytest.raises(ValidationError):
            native.AkeneoNodeConfig.model_validate({"config": config, "credentials": CREDS})
