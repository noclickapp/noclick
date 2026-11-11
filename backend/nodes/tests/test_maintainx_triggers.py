"""Deliveries copied from MaintainX's API reference; no live credentials."""
import hashlib
import hmac
import json
import time
from pathlib import Path

import httpx
import pytest

from nodes import maintainx_node as native
from nodes.tests.test_maintainx_node_mock import AUTH, TOKEN, node, transport

EVENTS = json.loads((Path(__file__).parent / "fixtures/maintainx/events.json").read_text())
SECRET = "maintainx-test-signing-secret"


def signed(body, timestamp=None):
    timestamp = str(int(time.time()) if timestamp is None else timestamp)
    digest = hmac.new(SECRET.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return {"X-MaintainX-Webhook-Body-Signature": f"t={timestamp},v1={digest}"}


@pytest.mark.parametrize("event", native.WEBHOOK_EVENTS)
def test_maintainx_documented_delivery_reaches_workflow_and_agent(event):
    payload = EVENTS[event]["body"]
    body = json.dumps(payload).encode()
    config = {"operation": "on_event", "event_type": event, "signing_secret": SECRET}
    assert native.MaintainxNode.verify_webhook_signature(body, signed(body), config)
    assert native.MaintainxNode.filter_trigger_payload(payload, config)
    assert not native.MaintainxNode.filter_trigger_payload(payload, {**config, "event_type": "unknown"})
    output = native.MaintainxNode.resolve_trigger_payload(payload, config)
    assert output == payload
    agent = native.MaintainxNode.resolve_agent_event(output)
    label, id_field, noun = native.WEBHOOK_EVENTS[event]
    assert label in agent["text"]
    assert str(payload["orgId"]) in agent["conversation_key"]
    assert f"{noun.replace(' ', '_')}_id={payload[id_field]}" in agent["text"]
    assert payload["occurredAt"] in agent["text"]
    if event == "NEW_COMMENT_ON_WORK_ORDER":
        assert payload["comment"] in agent["text"] and "60 minutes" in agent["text"]
    if event == "PART_QUANTITY_CHANGE":
        assert str(payload["quantityDiff"]) in agent["text"]


@pytest.mark.parametrize("event", ["NEW_WORK_ORDER", "WORK_ORDER_CHANGE", "WORK_ORDER_STATUS_CHANGE"])
def test_maintainx_system_initiated_and_unserialized_events(event):
    payload = {k: v for k, v in EVENTS[event]["body"].items() if k not in {"userId", "newWorkOrder"}}
    assert "System-initiated" in native.MaintainxNode.resolve_agent_event(payload)["text"]


@pytest.mark.parametrize("header", ["", "v1=bad", "t=bad,v1=bad", "t=1,t=2,v1=bad", "invalid", "t=1,invalid", "t=１２,v1=bad", "t="+"9"*100+",v1=bad", "t=1,v1=é"])
def test_maintainx_malformed_signature_fails_closed(header):
    assert not native.MaintainxNode.verify_webhook_signature(b"{}", {"x-maintainx-webhook-body-signature": header}, {"signing_secret": SECRET})


def test_maintainx_signatures_bind_timestamp_raw_body_and_secret():
    body = b'{"eventType": "NEW_WORK_ORDER"}'
    config = {"signing_secret": SECRET}
    headers = signed(body)
    assert native.MaintainxNode.verify_webhook_signature(body, headers, config)
    assert not native.MaintainxNode.verify_webhook_signature(body+b" ", headers, config)
    assert not native.MaintainxNode.verify_webhook_signature(body, headers, {"signing_secret": "wrong"})
    assert not native.MaintainxNode.verify_webhook_signature(body, headers, {})
    assert not native.MaintainxNode.verify_webhook_signature(body, signed(body, int(time.time())-301), config)
    assert not native.MaintainxNode.verify_webhook_signature(body, signed(body, int(time.time())+301), config)


@pytest.mark.asyncio
@pytest.mark.parametrize("event", native.WEBHOOK_EVENTS)
async def test_maintainx_register_scopes_subscription_and_unregister(monkeypatch, event):
    calls = []
    def handler(request):
        calls.append(request)
        if request.method == "POST":
            return httpx.Response(201, json={"id": 963, "status": "VALID", "secret": SECRET})
        return httpx.Response(204)
    monkeypatch.setattr(native, "guarded_async_client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(handler), **kw))
    config = {"operation": "on_event", "event_type": event}
    state = await native.MaintainxNode._register_external_webhook(webhook_url="https://example.com", credential=AUTH, config=config, node_id="test")
    assert state == {"external_webhook_id": "963", "signing_secret": SECRET}
    await native.MaintainxNode._unregister_external_webhook(credential=AUTH, config={**config, **state}, node_id="test")
    sent = json.loads(calls[0].content)
    assert sent["type"] == event and sent["url"] == "https://example.com"
    if event in {"NEW_WORK_ORDER", "WORK_ORDER_CHANGE", "WORK_ORDER_STATUS_CHANGE", "ASSET_CHANGE"}:
        assert sent["options"] == {"serializeEntity": True}
    else:
        assert "options" not in sent
    assert [(r.method, r.url.path) for r in calls] == [("POST", "/v1/subscriptions"), ("DELETE", "/v1/subscriptions/963")]
    assert all(r.headers["Authorization"] == "Bearer "+TOKEN and r.headers["x-organization-id"] == "15" for r in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["VALID", "PENDING_APPROVAL"])
async def test_maintainx_fetches_optional_secret_and_cleans_up_unusable_subscription(monkeypatch, status):
    calls = []
    def handler(request):
        calls.append(request)
        if request.method == "POST":
            return httpx.Response(201, json={"id": 963, "status": status})
        if request.method == "GET":
            return httpx.Response(200, json={"secret": SECRET})
        return httpx.Response(204)
    monkeypatch.setattr(native, "guarded_async_client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(handler), **kw))
    kwargs = dict(webhook_url="https://example.com", credential=AUTH, config={}, node_id="test")
    if status == "VALID":
        assert (await native.MaintainxNode._register_external_webhook(**kwargs))["signing_secret"] == SECRET
        assert calls[-1].url.path == "/v1/subscriptions/963/secret"
    else:
        with pytest.raises(ValueError, match="approval"):
            await native.MaintainxNode._register_external_webhook(**kwargs)
        assert calls[-1].method == "DELETE"


@pytest.mark.asyncio
async def test_maintainx_manual_trigger_does_not_invent_an_event(monkeypatch):
    calls = transport(monkeypatch, httpx.Response(500))
    result = await node({"operation": "on_event"}).execute({})
    assert result["status"] == "no_event" and not calls


def test_maintainx_event_change_reregisters():
    assert native.MaintainxNode.registration_fingerprint_fields({"event_type": "ASSET_CHANGE"}) != native.MaintainxNode.registration_fingerprint_fields({})


def test_maintainx_inventory_event_omits_unavailable_totals_and_actor():
    payload = {k: v for k, v in EVENTS["PART_QUANTITY_CHANGE"]["body"].items()
               if k not in {"oldQuantity", "newQuantity", "userId"}}
    text = native.MaintainxNode.resolve_agent_event(payload)["text"]
    assert "Quantity change: 3 units" in text
    assert "None" not in text and "System-initiated" not in text
