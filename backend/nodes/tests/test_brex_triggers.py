"""Signed webhook lifecycle; event bodies are copied from Brex's published guides."""
import base64
import hashlib
import hmac
import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest

from nodes.brex_node import BREX_TRIGGER_EVENTS, BrexNode, BrexNodeConfig

EVENTS = json.loads((Path(__file__).parent / "fixtures/brex/events.json").read_text())
# The verified signature vector from https://developer.brex.com/guides/webhooks.md.
SECRET = "4j7OxQ4wlv1GmkZ9qLjoFjEFXjpzvHkr"
BODY = b'{"event_type": "TRANSFER_PROCESSED", "transfer_id": "dptx_ckyypz30n000101kgzgnrtqlf", "company_id": "cuacc_ckqckhadg000601r95ox48c2s"}'
HEADERS = {
    "Webhook-Id": "msg_24Ky2257Hzd0tgc5bWs8TwK9Kod",
    "Webhook-Timestamp": "1643393361",
    "Webhook-Signature": "v1,6mFFi/Bg0gw1Yz2KJwZSVq6Bh+XzllS7JVltAlZ8yCU= v1,9dEEi/Bg0gw1Yz2KJwZSVq6Bh+XzllS7JVltAlZ8yDY=",
}


def test_provider_signature_vector_and_rotation(monkeypatch):
    monkeypatch.setattr("nodes.brex_node.time.time", lambda: 1643393361)
    config = {"signing_secret": SECRET}
    assert BrexNode.verify_webhook_signature(BODY, HEADERS, config)
    assert not BrexNode.verify_webhook_signature(BODY + b" ", HEADERS, config)
    assert not BrexNode.verify_webhook_signature(BODY, {**HEADERS, "Webhook-Id": "other"}, config)
    assert not BrexNode.verify_webhook_signature(BODY, {**HEADERS, "Webhook-Signature": "v2,unknown"}, config)
    assert BrexNode.verify_webhook_signature(BODY, HEADERS, {"signing_secret": "invalid," + SECRET})
    assert not BrexNode.verify_webhook_signature(BODY, HEADERS, {})
    assert not BrexNode.verify_webhook_signature(BODY, HEADERS, {"signing_secret": None})
    monkeypatch.setattr("nodes.brex_node.time.time", lambda: 1643393422)
    assert not BrexNode.verify_webhook_signature(BODY, HEADERS, config)
    monkeypatch.setattr("nodes.brex_node.time.time", lambda: 1643393300)
    assert not BrexNode.verify_webhook_signature(BODY, HEADERS, config)


@pytest.mark.parametrize("timestamp", ["", "invalid", "-1"])
def test_bad_timestamp(monkeypatch, timestamp):
    assert not BrexNode.verify_webhook_signature(BODY, {**HEADERS, "Webhook-Timestamp": timestamp}, {"signing_secret": SECRET})


@pytest.mark.parametrize("operation,event", BREX_TRIGGER_EVENTS.items())
@pytest.mark.asyncio
async def test_documented_delivery_to_agent(operation, event):
    config = {"operation": operation}
    model = BrexNodeConfig.model_validate({"config": config, "credentials": {"api_token": "test-token"}})
    assert model.config.model_json_schema()["properties"]["operation"]["x-is-trigger"] is True
    body = EVENTS[event]["body"]
    assert BrexNode.filter_trigger_payload(body, config)
    assert not BrexNode.filter_trigger_payload({"event_type": "USER_UPDATED"}, config)
    output = BrexNode.resolve_trigger_payload(body, config)
    assert output["data"] == body
    agent = BrexNode.resolve_agent_event(output)
    assert body["company_id"] in agent["text"]
    resource = body.get("expense_id") or body["transfer_id"]
    assert resource in agent["text"] and resource in agent["conversation_key"]
    if event == "EXPENSE_PAYMENT_UPDATED":
        assert "Schrute Farms" in agent["text"] and "PENDING" in agent["text"]
    node = BrexNode(node_id="test", node_type="automation-brex", node_data={}, config=model, sio=Mock())
    assert (await node.execute({}))["status"] == "no_event"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,event", BREX_TRIGGER_EVENTS.items())
async def test_registration_unregistration_and_rotation_keys(monkeypatch, operation, event):
    requests = []
    second = base64.b64encode(b"second-signing-key").decode()

    def handle(request):
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer test-token"
        if request.url.path == "/v1/webhooks/secrets":
            # Schema-shaped secrets response using the guide's verified secret.
            return httpx.Response(200, json=[{"secret": SECRET, "status": "ACTIVE"},
                                            {"secret": second, "status": "PENDING_REVOKE"},
                                            {"secret": "revoked", "status": "REVOKED"}])
        if request.method == "POST":
            assert request.headers["Idempotency-Key"]
            assert json.loads(request.content) == {"url": "https://your-webhook.url/", "event_types": [event]}
            return httpx.Response(200, json={"id": "subscription-id", "url": "https://your-webhook.url/",
                                            "event_types": [event], "status": "ACTIVE"})
        assert request.method == "DELETE" and request.url.path == "/v1/webhooks/subscription-id"
        return httpx.Response(200)

    original = httpx.AsyncClient
    monkeypatch.setattr("nodes.brex_node.httpx.AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handle)))
    config = {"operation": operation}
    registration = await BrexNode._register_external_webhook(
        webhook_url="https://your-webhook.url/", credential={"api_token": "test-token"}, config=config, node_id="test")
    assert registration == {"external_webhook_id": "subscription-id", "signing_secret": SECRET + "," + second}
    monkeypatch.setattr("nodes.brex_node.time.time", lambda: 1643393361)
    signature = base64.b64encode(hmac.new(base64.b64decode(second), b"msg_24Ky2257Hzd0tgc5bWs8TwK9Kod.1643393361." + BODY, hashlib.sha256).digest()).decode()
    assert BrexNode.verify_webhook_signature(BODY, {**HEADERS, "Webhook-Signature": "v1," + signature}, registration)
    await BrexNode._unregister_external_webhook(credential={"api_token": "test-token"}, config=registration, node_id="test")
    assert len(requests) == 3


@pytest.mark.asyncio
async def test_secrets_failure_cannot_create_subscription(monkeypatch):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(403, json={"message": "Forbidden"})

    original = httpx.AsyncClient
    monkeypatch.setattr("nodes.brex_node.httpx.AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handle)))
    with pytest.raises(httpx.HTTPStatusError):
        await BrexNode._register_external_webhook(webhook_url="https://your-webhook.url/", credential={"api_token": "test-token"}, config={"operation": "on_transfer_processed"}, node_id="test")
    assert len(calls) == 1 and calls[0].url.path == "/v1/webhooks/secrets"
