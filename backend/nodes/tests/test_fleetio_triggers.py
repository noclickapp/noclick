"""Verify Fleetio webhook lifecycle, signatures and useful agent turns.

Event fixtures copy Fleetio's official reference; transport remains mocked so
these checks never register a webhook against a live account.
"""
import hashlib
import hmac
import json
from pathlib import Path

import httpx
import pytest

from nodes import fleetio_node as native
from nodes.tests.test_fleetio_node_mock import CREDENTIAL, node, transport

EVENTS = json.loads((Path(__file__).parent / "fixtures/fleetio/events.json").read_text())
CASES = [(op, event) for op, events in native.TRIGGER_EVENTS.items() for event in events]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,event", CASES)
async def test_documented_delivery_lifecycle_and_agent(monkeypatch, operation, event):
    secret = "test-webhook-shared-key"
    requests = transport(monkeypatch, lambda request: httpx.Response(201, json={
        "id": 42, "shared_key": secret, "account_id": 7, "url": "https://example.hooks.example.test"
    }) if request.method == "POST" else httpx.Response(204))
    config = {"operation": operation, "event_type": event}
    state = await native.FleetioNode._register_external_webhook(webhook_url="https://example.hooks.example.test",
        credential=CREDENTIAL, config=config, node_id="fleetio-test")
    assert state == {"external_webhook_id": "42", "signing_secret": secret}
    assert requests[0].method == "POST" and requests[0].url.path == "/api/webhooks"
    assert json.loads(requests[0].content) == {"url": "https://example.hooks.example.test", "enabled": True,
        "all_events": False, event: True, "description": "NoClick fleetio-test"}
    assert requests[0].headers["Account-Token"] == CREDENTIAL["account_token"]
    assert requests[0].headers["Authorization"] == "Token " + CREDENTIAL["api_key"]
    assert requests[0].headers["X-Api-Version"] == native.API_VERSION
    delivery = EVENTS[event]["body"]
    body = json.dumps(delivery).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert native.FleetioNode.verify_webhook_signature(body, {"X-Fleetio-Webhook-Signature": signature}, state)
    assert native.FleetioNode.filter_trigger_payload(delivery, config)
    assert not native.FleetioNode.filter_trigger_payload(delivery, {"operation": operation,
        "event_type": next(other for other in native.TRIGGER_EVENTS[operation] if other != event)})
    agent = native.FleetioNode.resolve_agent_event(native.FleetioNode.resolve_trigger_payload(delivery, config))
    assert event.replace("_", " ") in agent["text"]
    assert delivery["triggered_by"] in agent["text"]
    assert str(delivery["id"]) in agent["text"]
    assert str(delivery["payload"]["id"]) in agent["conversation_key"]
    assert json.dumps(delivery["payload"], ensure_ascii=False) in agent["text"]
    assert secret not in agent["text"]
    assert native.FleetioNode.registration_fingerprint_fields(config) == {"event_type": event}
    parsed = native.FleetioNode.parse_config({"config": {**config, **state}, "credentials": CREDENTIAL})
    assert parsed.config.signing_secret == secret
    await native.FleetioNode._unregister_external_webhook(credential=CREDENTIAL, config=state, node_id="fleetio-test")
    assert requests[1].method == "DELETE" and requests[1].url.path == "/api/webhooks/42"


def test_signatures_fail_closed():
    body = b'{"event":"issue_created"}'
    config = {"signing_secret": "key"}
    signature = hmac.new(b"key", body, hashlib.sha256).hexdigest()
    headers = {"x-fleetio-webhook-signature": signature}
    assert not native.FleetioNode.verify_webhook_signature(body + b" ", headers, config)
    assert not native.FleetioNode.verify_webhook_signature(body, {}, config)
    assert not native.FleetioNode.verify_webhook_signature(body, headers, {})
    assert not native.FleetioNode.verify_webhook_signature(body, headers, {"signing_secret": "other"})
    assert not native.FleetioNode.verify_webhook_signature(body, {"x-fleetio-webhook-signature": "é"}, config)


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [{}, {"id": 1}, {"id": "1", "shared_key": "key"}, {"id": 1, "shared_key": ""}])
async def test_registration_requires_provider_id_and_signing_key(monkeypatch, reply):
    transport(monkeypatch, lambda _: httpx.Response(201, json=reply))
    with pytest.raises(ValueError):
        await native.FleetioNode._register_external_webhook(webhook_url="https://example.hooks.example.test",
            credential=CREDENTIAL, config={"operation": "on_issue_event"}, node_id="fleetio-test")


@pytest.mark.asyncio
@pytest.mark.parametrize("method,status", [("POST", 401), ("POST", 302), ("DELETE", 403), ("DELETE", 500)])
async def test_lifecycle_errors_propagate_without_leaking_secrets(monkeypatch, method, status):
    requests = transport(monkeypatch, lambda _: httpx.Response(status, text=CREDENTIAL["api_key"]))
    with pytest.raises(ValueError, match=f"HTTP {status}") as error:
        await native.FleetioNode._webhook_request(CREDENTIAL, method, "/webhooks")
    assert CREDENTIAL["api_key"] not in str(error.value)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_teardown_absent_and_invalid_id(monkeypatch):
    requests = transport(monkeypatch, lambda _: httpx.Response(404))
    await native.FleetioNode._unregister_external_webhook(credential=CREDENTIAL, config={"external_webhook_id": "42"}, node_id="test")
    with pytest.raises(ValueError):
        await native.FleetioNode._unregister_external_webhook(credential=CREDENTIAL, config={"external_webhook_id": "../other"}, node_id="test")
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,event", CASES)
async def test_manual_run_waits_without_registering_or_fabricating_event(monkeypatch, operation, event):
    requests = transport(monkeypatch, lambda _: pytest.fail("Manual run must not call Fleetio"))
    result = await node({"operation": operation, "event_type": event}).execute({})
    assert result["status"] == "no_event"
    assert native.FleetioNode.resolve_agent_event(result) is None
    assert requests == []


@pytest.mark.parametrize("operation,event", [(op, event) for op, events in native.TRIGGER_EVENTS.items() for event in events])
def test_each_documented_event_flag_is_selectable(operation, event):
    parsed = native.FleetioNode.parse_config({"config": {"operation": operation, "event_type": event}, "credentials": CREDENTIAL})
    assert parsed.config.event_type == event


def test_trigger_config_rejects_unrelated_fields_and_events():
    for config in ({"operation": "on_vehicle_event", "event_type": "issue_created"}, {"operation": "on_issue_event", "per_page": 50}):
        with pytest.raises(ValueError):
            native.FleetioNode.parse_config({"config": config, "credentials": CREDENTIAL})
    for output in ({}, {"event": {}}, {"event": "issue_created", "payload": []}):
        assert native.FleetioNode.resolve_agent_event(output) is None
