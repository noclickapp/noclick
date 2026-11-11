"""Pidgeon request routing and documented webhook behavior (no live account)."""
import hashlib
import hmac
import json
import time
from pathlib import Path

import httpx
import pytest

from nodes.core.registry import NodeFactory
from nodes.pidgeon_node import CONFIG_MODELS, PidgeonCredential, PidgeonNode

KEY = {"credential_type": "pidgeon_api_key", "api_key": "pgn_test_fixture_key"}
ID = "1a70b25d-bc53-4a94-a51a-10fd88ebd19a"
EVENT = json.loads((Path(__file__).parent / "fixtures/pidgeon/message_received.json").read_text())


def node(config):
    return NodeFactory.create_node(node_id="pidgeon-test", node_type="automation-pidgeon",
        node_data={"config": config, "credentials": KEY})


def transport(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr("nodes.pidgeon_node.httpx.AsyncClient",
        lambda **kw: original(transport=httpx.MockTransport(handler), **kw))


# Independent route expectations: changing the dispatch table must not silently
# change what this test accepts. Wire schemas are also checked by conformance.
ROUTES = [
    ("get_account", "GET", "/me"),
    ("list_identities", "GET", "/identities"),
    ("create_identity", "POST", "/identities"),
    ("get_identity", "GET", "/identities/{id}"),
    ("update_identity", "PATCH", "/identities/{id}"),
    ("delete_identity", "DELETE", "/identities/{id}"),
    ("list_messages", "GET", "/messages"),
    ("search_messages", "GET", "/messages/search"),
    ("get_message", "GET", "/messages/{id}"),
    ("send_message", "POST", "/messages"),
    ("reply_to_message", "POST", "/messages/{id}/reply"),
    ("reply_all", "POST", "/messages/{id}/reply-all"),
    ("forward_message", "POST", "/messages/{id}/forward"),
    ("update_message", "PATCH", "/messages/{id}"),
    ("list_events", "GET", "/events"),
    ("get_thread", "GET", "/threads/{id}"),
    ("update_thread", "PATCH", "/threads/{id}"),
    ("list_drafts", "GET", "/drafts"),
    ("create_draft", "POST", "/drafts"),
    ("get_draft", "GET", "/drafts/{id}"),
    ("update_draft", "PATCH", "/drafts/{id}"),
    ("delete_draft", "DELETE", "/drafts/{id}"),
    ("send_draft", "POST", "/drafts/{id}/send"),
    ("list_contacts", "GET", "/contacts"),
]

@pytest.mark.asyncio
@pytest.mark.parametrize("operation,method,path", ROUTES)
async def test_every_action_routes_and_preserves_envelope(monkeypatch, operation, method, path):
    config = {"operation": operation}
    for key, field in CONFIG_MODELS[operation].model_fields.items():
        if field.is_required():
            config[key] = "sender@example.com" if key in {"from_address", "to"} else ID
    if operation == "create_identity":
        config["address"] = "agent@example.com"
    if operation == "send_message":
        config.update(text="Hello", subject="Status", idempotency_key="attempt-1")
    if operation.startswith("list_"):
        config.update(limit=25, cursor="opaque-next-page")
    if operation == "search_messages":
        config.update(from_address="person@example.com", folder="inbox", q="invoice")
    if operation == "get_message":
        config["body_format"] = "clean"
    if operation == "update_thread":
        config.update(status="resolved", owner_type="automation", reason="Handled")
    seen = []
    def handler(request):
        seen.append(request)
        assert request.method == method
        assert request.url.host == "pidgeon.ai"
        assert request.url.path == "/api/v1" + path.replace("{id}", ID)
        assert request.headers["Authorization"] == "Bearer " + KEY["api_key"]
        if operation.startswith("list_"):
            assert request.url.params["cursor"] == "opaque-next-page"
            assert request.url.params["limit"] == "25"
        if operation == "list_messages":
            assert request.url.params["thread_id"] == ID
        if operation == "search_messages":
            assert dict(request.url.params) == {"from": "person@example.com", "in": "inbox", "q": "invoice"}
        if operation == "get_message":
            assert dict(request.url.params) == {"body": "clean"}
        if operation == "send_message":
            assert json.loads(request.content) == {"from": "sender@example.com", "to": "sender@example.com", "text": "Hello", "subject": "Status"}
            assert request.headers["Idempotency-Key"] == "attempt-1"
        if operation == "update_thread":
            assert json.loads(request.content) == {"status": "resolved", "owner_type": "automation", "reason": "Handled"}
        return httpx.Response(200, json={"data": [], "has_more": True, "next_cursor": "next"})
    transport(monkeypatch, handler)
    result = await node(config).execute({})
    assert len(seen) == 1
    assert result["status"] == "success"
    assert result["has_more"] is True and result["next_cursor"] == "next"


@pytest.mark.asyncio
async def test_provider_rejection_preserves_message(monkeypatch):
    transport(monkeypatch, lambda r: httpx.Response(403, json={"error": {"code": "forbidden", "message": "This key cannot send"}}))
    with pytest.raises(ValueError, match="This key cannot send"):
        await node({"operation": "get_account"}).execute({})


@pytest.mark.asyncio
async def test_webhook_lifecycle(monkeypatch):
    seen = []
    def handler(request):
        seen.append(request)
        if request.method == "POST":
            assert json.loads(request.content) == {"url": "https://hooks.hooks.example.test/pidgeon", "event_types": ["message.received"], "identity_id": ID}
            return httpx.Response(201, json={"data": {"id": ID, "secret": "one-time-secret"}})
        assert request.method == "DELETE" and request.url.path.endswith("/webhooks/" + ID)
        return httpx.Response(200, json={"data": {"deleted": True}})
    transport(monkeypatch, handler)
    config = await PidgeonNode._register_external_webhook(webhook_url="https://hooks.hooks.example.test/pidgeon", credential=KEY, config={"identity_id": ID}, node_id="n")
    assert config == {"external_webhook_id": ID, "signing_secret": "one-time-secret"}
    await PidgeonNode._unregister_external_webhook(credential=KEY, config=config, node_id="n")
    assert len(seen) == 2


def signed(body, stamp, secret="fixture-secret"):
    digest = hmac.new(secret.encode(), str(stamp).encode() + b"." + body, hashlib.sha256).hexdigest()
    return {"X-Pidgeon-Timestamp": str(stamp), "X-Pidgeon-Signature": "v1=" + digest}


def test_signature_raw_body_and_replay_window():
    body = json.dumps(EVENT).encode()
    stamp = int(time.time())
    config = {"signing_secret": "fixture-secret"}
    headers = signed(body, stamp)
    assert PidgeonNode.verify_webhook_signature(body, headers, config)
    assert not PidgeonNode.verify_webhook_signature(body + b" ", headers, config)
    assert not PidgeonNode.verify_webhook_signature(body, signed(body, stamp - 301), config)
    assert not PidgeonNode.verify_webhook_signature(body, signed(body, stamp + 301), config)
    assert not PidgeonNode.verify_webhook_signature(body, headers, {})
    assert not PidgeonNode.verify_webhook_signature(body, {}, config)
    assert not PidgeonNode.verify_webhook_signature(body, {**headers, "X-Pidgeon-Signature": "é"}, config)


def test_documented_event_filter_payload_and_agent_turn():
    assert PidgeonNode.filter_trigger_payload(EVENT, {}) is True
    assert PidgeonNode.resolve_trigger_payload(EVENT, {}) == EVENT
    assert not PidgeonNode.filter_trigger_payload({**EVENT, "type": "unrelated"}, {})
    for key, value in [("from_self", True), ("owner_type", "human")]:
        assert not PidgeonNode.filter_trigger_payload({**EVENT, "data": {**EVENT["data"], key: value}}, {})
    turn = PidgeonNode.resolve_agent_event(EVENT)
    assert turn["conversation_key"] == EVENT["data"]["thread_id"]
    for text in ["Supplier Billing", "Invoice 4417", EVENT["data"]["message_id"], "get_message", "reply_to_message"]:
        assert text in turn["text"]


@pytest.mark.asyncio
async def test_manual_trigger_run_does_not_invent_event():
    assert (await node({"operation": "on_message_received"}).execute({}))["status"] == "no_event"


def test_manual_credential_has_default_type():
    assert PidgeonCredential(api_key="pgn_test_fixture_key").credential_type == "pidgeon_api_key"


def test_event_recovery_chooses_one_direction():
    with pytest.raises(ValueError, match="either Cursor"):
        CONFIG_MODELS["list_events"](cursor="opaque", after="2026-01-01T00:00:00Z")
