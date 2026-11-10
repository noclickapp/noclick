"""Exercise Payaca authentication, writes, registration and signed delivery.

Event fixtures retain the provider's schema and property examples from the pinned contract.
"""
import base64
import hashlib
import hmac
import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from pydantic import ValidationError
from nodes.payaca_node import API_VERSION, EVENTS, PayacaAPIKeyCredential, PayacaFullConfig, PayacaNode

CREDENTIAL = {"credential_type": "payaca_api_key", "client_id": "test-client", "client_secret": "test-secret"}


def node(config):
    return PayacaNode(node_id="test", node_type="automation-payaca", node_data={"config": config},
        config=PayacaFullConfig.model_validate({"config": config, "credentials": CREDENTIAL}), sio=Mock())


@pytest.mark.asyncio
async def test_customer_write_uses_basic_auth_and_exact_contact_shape(monkeypatch):
    requests = []
    async def request(self, method, url, **kwargs):
        requests.append((method, url, kwargs))
        return httpx.Response(201, json={"customer": {"id": "xyz"}})
    monkeypatch.setattr(httpx.AsyncClient, "request", request)
    result = await node({"operation": "create_customer", "contacts": [{"fullName": "John Doe", "email": "john.doe@email.com"}]}).execute({})
    method, url, kwargs = requests[0]
    assert (method, url) == ("POST", "https://api.payaca.com/openapi/customers")
    assert kwargs["json"] == {"contacts": [{"fullName": "John Doe", "email": "john.doe@email.com"}]}
    assert kwargs["headers"]["Authorization"] == "Basic " + base64.b64encode(b"test-client:test-secret").decode()
    assert kwargs["headers"]["X-Payaca-API-Version"] == API_VERSION
    assert result["data"]["customer"]["id"] == "xyz"


@pytest.mark.asyncio
async def test_project_id_encoded_and_no_invoice_email_by_default(monkeypatch):
    requests = []
    async def request(self, method, url, **kwargs):
        requests.append((method, url, kwargs))
        return httpx.Response(201, json={"invoice": {"id": "xyz"}})
    monkeypatch.setattr(httpx.AsyncClient, "request", request)
    await node({"operation": "create_next_invoice", "project_id": "a/b", "due_in_days": 30}).execute({})
    assert requests[0][1].endswith("/projects/a%2Fb/invoices/next")
    assert requests[0][2]["json"] == {"dueInDays": 30}


@pytest.mark.asyncio
async def test_provider_rejection_preserves_message(monkeypatch):
    async def request(*args, **kwargs):
        return httpx.Response(401, json={"message": "Invalid client credentials"})
    monkeypatch.setattr(httpx.AsyncClient, "request", request)
    with pytest.raises(ValueError, match="Invalid client credentials"):
        await node({"operation": "list_customers"}).execute({})


@pytest.mark.asyncio
async def test_registration_secret_is_ours_and_delete_uses_returned_id(monkeypatch):
    calls = []
    async def request(credential, method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"webhook": {"id": "xyz"}} if method == "POST" else {"deleted": True}
    monkeypatch.setattr(PayacaNode, "_request", request)
    config = {"operation": "on_event", "event_type": "invoice.fullyPaid"}
    extra = await PayacaNode._register_external_webhook(webhook_url="https://example.com/webhook", credential=CREDENTIAL, config=config, node_id="test")
    assert calls[0][2]["body"]["events"] == ["invoice.fullyPaid"]
    assert calls[0][2]["body"]["apiVersion"] == API_VERSION
    assert calls[0][2]["body"]["secret"] == extra["signing_secret"]
    assert len(extra["signing_secret"]) == 64
    await PayacaNode._unregister_external_webhook(credential=CREDENTIAL, config={**config, **extra}, node_id="test")
    assert calls[-1][:2] == ("DELETE", "/account/webhooks/xyz")


FIXTURES = json.loads((Path(__file__).parent / "fixtures/payaca/events.json").read_text())


@pytest.mark.parametrize("event", EVENTS)
def test_every_documented_event_is_routed_signed_and_readable(event):
    payload = FIXTURES["events"][event]
    body = json.dumps(payload).encode()
    config = {"event_type": event, "signing_secret": "my-secret"}
    signature = hmac.new(b"my-secret", body, hashlib.sha256).hexdigest()
    headers = {"X-Payaca-Event": event, "X-Payaca-Signature": signature}
    assert PayacaNode.verify_webhook_signature(body, headers, config)
    assert not PayacaNode.verify_webhook_signature(body + b" ", headers, config)
    assert not PayacaNode.verify_webhook_signature(body, {"X-Payaca-Signature": "é" * 64}, config)
    assert not PayacaNode.verify_webhook_signature(body, {}, config)
    assert not PayacaNode.verify_webhook_signature(body, headers, {})
    payload = {**payload, "_webhook": {"headers": headers}}
    assert PayacaNode.filter_trigger_payload(payload, config)
    assert not PayacaNode.filter_trigger_payload(payload, {"event_type": "other.event"})
    output = PayacaNode.resolve_trigger_payload(payload, config)
    turn = PayacaNode.resolve_agent_event(output)
    assert event in turn["text"]
    assert payload["account"]["id"] in turn["conversation_key"]
    record = payload["payload"][event.split(".")[0]]
    assert record["id"] in turn["text"]


@pytest.mark.asyncio
async def test_manual_trigger_cannot_pass_other_steps_data_as_an_event():
    assert (await node({"operation": "on_event"}).execute({"data": {"eventName": "project.created"}}))["status"] == "no_event"


def test_manual_credential_defaults_type_and_refuses_header_parts():
    assert PayacaAPIKeyCredential(client_id="client", client_secret="secret").credential_type == "payaca_api_key"
    with pytest.raises(ValidationError):
        PayacaAPIKeyCredential(client_id="client:secret", client_secret="secret")
