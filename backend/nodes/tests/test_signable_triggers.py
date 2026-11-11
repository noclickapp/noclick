"""Exercise Signable lifecycle and payload hooks using published event examples.

Signature tests preserve the raw body as Signable's verification guide requires.
Agent tests retain resource IDs, the actor, and the provider's event content.
"""
import base64
import hashlib
import hmac
import json
from pathlib import Path
from urllib.parse import urlencode
import pytest
from nodes import signable_node as native
from nodes.tests.test_signable_node_mock import CREDENTIAL, node, transport

EVENTS = json.loads((Path(__file__).parent / "fixtures/signable/webhook_events.json").read_text())

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

@pytest.mark.parametrize("event", EVENTS)
def test_documented_delivery_and_agent(event):
    payload = EVENTS[event]["body"]
    config = {"operation": "on_event", "event_type": event}
    assert native.SignableNode.filter_trigger_payload(payload, config)
    assert not native.SignableNode.filter_trigger_payload(payload, {**config, "event_type": "add-user"})
    output = native.SignableNode.resolve_trigger_payload(payload, config)
    assert output == payload
    message = native.SignableNode.resolve_agent_event(output)
    for field in ("envelope_fingerprint", "action_date", "contact_name", "contact_email", "envelope_fields"):
        if payload.get(field):
            assert payload[field] in message["text"]
    assert payload["envelope_fingerprint"] in message["conversation_key"]
    assert "get_envelope envelope_fingerprint=" in message["text"]

@pytest.mark.parametrize("wire", ["json", "form"])
def test_raw_signature(monkeypatch, wire):
    monkeypatch.setattr(native.time, "time", lambda: 1710000000)
    payload = EVENTS["signed-envelope"]["body"]
    body = (json.dumps(payload) if wire == "json" else urlencode(payload)).encode()
    secret = "test-only-signing-secret"
    signature = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()
    headers = {"Signature": signature, "X-Signable-Webhook": "1710000000"}
    config = {"signing_secret": secret}
    verify = native.SignableNode.verify_webhook_signature
    assert verify(body, headers, config)
    assert not verify(body + b" ", headers, config)
    assert not verify(body, headers, {"signing_secret": "wrong"})
    assert not verify(body, {"X-Signable-Webhook": "1710000000"}, config)
    for timestamp in ("1709999000", "garbage", "²", "1" * 5000):
        assert not verify(body, {**headers, "X-Signable-Webhook": timestamp}, config)
    assert not verify(body, headers, {})
    assert verify(body, {}, {})

@pytest.mark.asyncio
@pytest.mark.parametrize("event", native.SIGNABLE_EVENTS)
async def test_registration_selected_event(monkeypatch, event):
    requests = transport(monkeypatch, 200, {"http": 200, "webhook_id": "152691"})
    config = {"operation": "on_event", "event_type": event}
    saved = await native.SignableNode._register_external_webhook(
        webhook_url="https://example.com", credential=CREDENTIAL, config=config, node_id="test")
    assert saved == {"external_webhook_id": "152691", "signing_secret": None}
    assert requests[0].method == "POST" and requests[0].url.path == "/v1/webhooks"
    assert json.loads(requests[0].content) == {"webhook_url": "https://example.com", "webhook_type": event}
    assert requests[0].headers["authorization"] == "Basic " + base64.b64encode((CREDENTIAL["api_key"] + ":x").encode()).decode()
    assert native.SignableNode.registration_fingerprint_fields(config) == {"event_type": event}
    assert node(config).config.config.event_type == event

@pytest.mark.asyncio
async def test_signed_registration_and_teardown(monkeypatch):
    # Guide: webhook_secret is returned at creation. The example value is from
    # the contract's WebhookPutResponseExample; these are synthetic HTTP replies.
    transport(monkeypatch, 200, {"http": 200, "webhook_id": "152691", "webhook_secret": "whsec_example_redacted"})
    saved = await native.SignableNode._register_external_webhook(
        webhook_url="https://example.com", credential=CREDENTIAL, config={"operation": "on_event"}, node_id="test")
    assert saved["signing_secret"] == "whsec_example_redacted"
    requests = transport(monkeypatch, 200, {"http": 200})
    await native.SignableNode._unregister_external_webhook(credential=CREDENTIAL, config=saved, node_id="test")
    assert requests[0].method == "DELETE" and requests[0].url.path == "/v1/webhooks/152691"
    assert not requests[0].content
    transport(monkeypatch, 404, {})
    await native.SignableNode._unregister_external_webhook(credential=CREDENTIAL, config=saved, node_id="test")
    with pytest.raises(ValueError, match="Connect"):
        await native.SignableNode._unregister_external_webhook(credential=None, config=saved, node_id="test")

@pytest.mark.asyncio
async def test_errors_and_manual_run(monkeypatch):
    for status, body in [(401, {}), (200, {"http": 401}), (200, {})]:
        transport(monkeypatch, status, body)
        with pytest.raises(ValueError):
            await native.SignableNode._register_external_webhook(webhook_url="https://example.com",
                credential=CREDENTIAL, config={"operation": "on_event"}, node_id="test")
    with pytest.raises(ValueError, match="supported"):
        await native.SignableNode._register_external_webhook(webhook_url="https://example.com",
            credential=CREDENTIAL, config={"event_type": "invented"}, node_id="test")
    assert (await node({"operation": "on_event"}).execute({"action": "signed-envelope"}))["status"] == "no_event"


@pytest.mark.parametrize("event", EVENTS)
def test_standard_form_delivery_through_receiver_envelope(event):
    expected = EVENTS[event]["body"]
    payload = {"raw": urlencode(expected), "_webhook": {
        "headers": {"content-type": "application/x-www-form-urlencoded; charset=UTF-8"}}}
    config = {"operation": "on_event", "event_type": event}
    assert native.SignableNode.filter_trigger_payload(payload, config)
    output = native.SignableNode.resolve_trigger_payload(payload, config)
    assert {k: v for k, v in output.items() if k != "_webhook"} == {k: str(v) for k, v in expected.items()}
    assert expected["envelope_fingerprint"] in native.SignableNode.resolve_agent_event(output)["text"]
    assert not native.SignableNode.filter_trigger_payload({"raw": "garbage"}, config)
