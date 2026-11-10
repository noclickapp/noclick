"""Replay Whop's published commerce-event examples through the trigger hooks.
These tests pin registration, signing and agent delivery to the provider contract.
"""
import base64
import hashlib
import hmac
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import whop_node as whop
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / "fixtures/whop/events.json").read_text())["events"]
SECRET = "ws_0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


@pytest.fixture
def ensure_native_db_pool():
    yield


def signed(body, timestamp=None, message_id="msg_bQPHmO2eBnHYtWWuxAN9K3Xd"):
    timestamp = str(int(time.time()) if timestamp is None else timestamp)
    signature = base64.b64encode(hmac.new(SECRET.encode(), message_id.encode() + b"." + timestamp.encode() + b"." + body, hashlib.sha256).digest()).decode()
    return {"webhook-id": message_id, "webhook-timestamp": timestamp, "webhook-signature": "v1," + signature}


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", whop.WHOP_WEBHOOK_EVENTS)
async def test_whop_registration_and_teardown(monkeypatch, event_type):
    calls = []
    def answer(request):
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer whop-test-key"
        assert request.headers["Api-Version-Date"] == "2026-11-07"
        if request.method == "POST":
            assert request.url.path == "/api/v1/webhooks"
            assert json.loads(request.content) == {"url": "https://hooks.example.com/whop", "events": [event_type], "enabled": True, "api_version_date": "2026-11-07", "resource_id": "biz_xxxxxxxxxxxxxx"}
            return httpx.Response(200, json={"id": "hook_xxxxxxxxxxxxxx", "webhook_secret": SECRET})
        assert request.method == "DELETE"
        assert request.url.path == "/api/v1/webhooks/hook_xxxxxxxxxxxxxx"
        return httpx.Response(200, json={"id": "hook_xxxxxxxxxxxxxx", "deleted": True})
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs == {"timeout": 30, "follow_redirects": False, "trust_env": False}
        async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as value:
            yield value
    monkeypatch.setattr(whop, "guarded_async_client", client)
    config = {"operation": "on_event", "event_type": event_type, "resource_id": "biz_xxxxxxxxxxxxxx"}
    credential = {"credential_type": "whop_api_key", "api_key": "whop-test-key"}
    state = await whop.WhopNode._register_external_webhook(webhook_url="https://hooks.example.com/whop", credential=credential, config=config, node_id="whop-test")
    assert state == {"external_webhook_id": "hook_xxxxxxxxxxxxxx", "signing_secret": SECRET}
    await whop.WhopNode._unregister_external_webhook(credential=credential, config={**config, **state}, node_id="whop-test")
    assert len(calls) == 2


@pytest.mark.parametrize("event_type", whop.WHOP_WEBHOOK_EVENTS)
def test_whop_documented_deliveries(event_type):
    payload = EXAMPLES[event_type]
    body = json.dumps(payload).encode()
    config = {"operation": "on_event", "event_type": event_type, "signing_secret": SECRET}
    assert whop.WhopNode.verify_webhook_signature(body, signed(body), config)
    assert whop.WhopNode.filter_trigger_payload(payload, config)
    other = "payment.failed" if event_type != "payment.failed" else "payment.succeeded"
    assert not whop.WhopNode.filter_trigger_payload(EXAMPLES[other], config)
    assert not whop.WhopNode.filter_trigger_payload(payload, {"operation": "get_account", "event_type": event_type})
    output = whop.WhopNode.resolve_trigger_payload(payload, config)
    for envelope in (output, {"status": "success", "data": output}):
        turn = whop.WhopNode.resolve_agent_event(envelope)
        assert turn["conversation_key"] == payload["data"]["id"]
        assert payload["data"]["id"] in turn["text"]
        assert event_type.replace(".", " ") in turn["text"]
        assert payload["account_id"] in turn["text"]
        assert payload["id"] in turn["text"]
        assert "Status:" in turn["text"]
        if event_type.startswith("payment."):
            assert payload["data"]["customer_email"] in turn["text"]
        elif event_type.startswith("membership."):
            assert payload["data"]["product"]["title"] in turn["text"]
        elif event_type.startswith("refund."):
            assert payload["data"]["payment"]["user"]["name"] in turn["text"]
        else:
            assert payload["data"]["buyer"]["name"] in turn["text"]


def test_whop_signature_rejects_tampering_and_replay():
    body = json.dumps(EXAMPLES["payment.succeeded"]).encode()
    headers = signed(body)
    config = {"signing_secret": SECRET}
    assert whop.WhopNode.verify_webhook_signature(body, {k.upper(): v for k, v in headers.items()}, config)
    rotated = {**headers, "webhook-signature": "v1,bad " + headers["webhook-signature"]}
    assert whop.WhopNode.verify_webhook_signature(body, rotated, config)
    assert not whop.WhopNode.verify_webhook_signature(body + b" ", headers, config)
    assert not whop.WhopNode.verify_webhook_signature(body, headers, {"signing_secret": SECRET[3:]})
    assert not whop.WhopNode.verify_webhook_signature(body, headers, {})
    for delta in (-301, 301):
        assert not whop.WhopNode.verify_webhook_signature(body, signed(body, int(time.time()) + delta), config)
    for key, value in [("webhook-timestamp", "bad"), ("webhook-timestamp", "1" * 5000), ("webhook-id", "changed"), ("webhook-signature", "v2,bad"), ("webhook-signature", "v1,☃")]:
        assert not whop.WhopNode.verify_webhook_signature(body, {**headers, key: value}, config)
    for key in headers:
        assert not whop.WhopNode.verify_webhook_signature(body, {k: v for k, v in headers.items() if k != key}, config)


@pytest.mark.asyncio
async def test_whop_registration_requires_secret_and_valid_config(monkeypatch):
    request = AsyncMock(return_value={"id": "hook_xxxxxxxxxxxxxx", "webhook_secret": None})
    monkeypatch.setattr(whop.WhopNode, "_request", request)
    with pytest.raises(ValueError, match="signing secret"):
        await whop.WhopNode._register_external_webhook(webhook_url="https://hooks.example.com/whop", credential={}, config={}, node_id="whop-test")
    assert "resource_id" not in request.call_args.kwargs["json"]
    request.reset_mock()
    for config in ({"event_type": "made.up"}, {"resource_id": "../accounts/me"}):
        with pytest.raises(ValueError):
            await whop.WhopNode._register_external_webhook(webhook_url="https://hooks.example.com/whop", credential={}, config=config, node_id="whop-test")
    request.assert_not_called()


def test_whop_registration_scope_fingerprint():
    fingerprint = whop.WhopNode.registration_fingerprint_fields({})
    assert fingerprint == {"event_type": "payment.succeeded", "resource_id": None}
    assert fingerprint == whop.WhopNode.registration_fingerprint_fields({"operation": "get_account"})
    for field, value in [("event_type", "membership.updated"), ("resource_id", "biz_xxxxxxxxxxxxxx")]:
        assert fingerprint != whop.WhopNode.registration_fingerprint_fields({field: value})
    assert fingerprint == whop.WhopNode.registration_fingerprint_fields({"webhook_url": "https://hooks.example.com/changed"})


@pytest.mark.asyncio
async def test_whop_trigger_manual_run_carries_no_other_node_outputs():
    node = NodeFactory.create_node(node_id="whop-test", node_type="automation-whop", node_data={"config": {"operation": "on_event"}, "credentials": {"credential_type": "whop_api_key", "api_key": "whop-test-key"}})
    assert await node.execute({"other-node": {"private": "data"}}) == {"status": "success", "data": {}}
    assert whop.WhopNode.resolve_agent_event({"status": "success", "data": {}}) is None
