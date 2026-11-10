"""Check Mobile Message wire requests and webhook lifecycle against provider examples.

Published fixtures cover both inbound and multipart receipt agent turns; local
negative cases check rejection, raw-byte signing, ownership and page boundaries.
"""
import base64
import hashlib
import hmac
import json
import time
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import mobile_message_ca21345_node as native
from nodes.core.registry import NodeFactory

FIXTURE = json.loads((Path(__file__).parent / "fixtures/mobile-message-ca21345/documented.json").read_text())
CREDS = {"credential_type": native.CREDENTIAL, "api_username": "test-api-user", "api_password": "test-api-password"}
CLIENT = httpx.AsyncClient


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="mobile-message-test", node_type=native.MobileMessageNode.integration_type,
        node_data={"config": config, "credentials": CREDS})


def mock_http(monkeypatch, handler):
    calls = []
    def response(request):
        calls.append(request)
        return handler(request)
    monkeypatch.setattr(native.httpx, "AsyncClient", lambda **kw: CLIENT(transport=httpx.MockTransport(response), **kw))
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(native.OPERATIONS))
async def test_mobile_message_ca21345_documented_wire_mapping(monkeypatch, operation):
    _, method, path, _ = native.OPERATIONS[operation]
    response = FIXTURE["responses"][method + " " + path]
    calls = mock_http(monkeypatch, lambda req: httpx.Response(200, json=response))
    config = {"operation": operation, **FIXTURE["configs"][operation]}
    result = await node(config).execute({})
    assert result["data"] == response
    assert len(calls) == 1
    req = calls[0]
    assert (req.method, req.url.host, req.url.path) == (method, "api.mobilemessage.com.au", path)
    assert req.headers["Authorization"] == "Basic " + base64.b64encode(b"test-api-user:test-api-password").decode()
    if method != "GET":
        body = json.loads(req.content)
        for key, value in FIXTURE["configs"][operation].items():
            if key == "messages":
                assert all(body["messages"][0][k] == v for k, v in value[0].items())
            else:
                assert body[key] == value
    assert CREDS["api_password"] not in str(result)


@pytest.mark.asyncio
async def test_mobile_message_ca21345_pagination_dates_and_booleans(monkeypatch):
    calls = mock_http(monkeypatch, lambda req: httpx.Response(200, json=FIXTURE["responses"]["GET /v1/inbound"]))
    result = await node({"operation": "list_inbound", "from_date": "2026-01-01", "to_date": "2026-02-01", "limit": 10, "offset": 20}).execute({})
    assert dict(calls[0].url.params) == {"from": "2026-01-01", "to": "2026-02-01", "limit": "10", "offset": "20"}
    assert result["data"]["total"] == FIXTURE["responses"]["GET /v1/inbound"]["total"]
    # DELETE bodies must carry an actual boolean, never the truthy string "false".
    await node({"operation": "delete_list", "list_id": 5}).execute({})
    assert json.loads(calls[-1].content)["delete_contacts"] is False


@pytest.mark.asyncio
async def test_mobile_message_ca21345_sends_preserve_partial_failures_and_idempotency(monkeypatch):
    response = FIXTURE["partial_failure"]
    calls = mock_http(monkeypatch, lambda req: httpx.Response(200, json=response))
    result = await node({"operation": "send_messages", **FIXTURE["configs"]["send_messages"], "idempotency_key": "order-4821-attempt-1"}).execute({})
    assert calls[0].headers["Idempotency-Key"] == "order-4821-attempt-1"
    assert "idempotency_key" not in json.loads(calls[0].content)
    assert result["data"] == response and "delivered" not in result
    assert [row["status"] for row in result["data"]["results"]] == ["success", "blocked", "error"]


@pytest.mark.parametrize("config", [
    {"operation": "cancel_scheduled_messages"},
    {"operation": "get_link_tracking", "send_id": 42, "custom_ref": "Order123"},
    {"operation": "add_list_member", "list_id": 5},
    {"operation": "update_contact", "contact_id": 42},
    {"operation": "update_contact", "contact_id": 42, "first_name": None},
    {"operation": "list_inbound", "limit": 201},
])
def test_mobile_message_ca21345_refuses_unusable_inputs(config):
    with pytest.raises(ValidationError):
        native.MobileMessageNodeConfig.model_validate({"config": config, "credentials": CREDS})


@pytest.mark.asyncio
@pytest.mark.parametrize("http_status", [401, 429, 500])
async def test_mobile_message_ca21345_provider_errors_no_retry(monkeypatch, http_status):
    calls = mock_http(monkeypatch, lambda req: httpx.Response(http_status, json={"error": "API request rejected"}))
    with pytest.raises(ValueError, match="API request rejected"):
        await node({"operation": "list_lists"}).execute({})
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,kind", [("on_inbound_sms", "inbound"), ("on_delivery_receipt", "status")])
async def test_mobile_message_ca21345_webhook_lifecycle_and_ownership(monkeypatch, operation, kind):
    url = "https://test.hooks.example.test/webhook/mobile-message"
    current = {"inbound": None, "status": None}
    def handler(req):
        if req.method == "GET":
            return httpx.Response(200, json={"status": "complete", "webhooks": dict(current), "has_signing_secret": True})
        body = json.loads(req.content)
        if req.method == "POST":
            current[body["type"]] = body["url"]
        else:
            current[body["type"]] = None
        return httpx.Response(200, json=FIXTURE["responses"][req.method + " /v1/webhooks"])
    calls = mock_http(monkeypatch, handler)
    cred = {**CREDS, "webhook_signing_secret": "local-test-signing-secret"}
    config = {"operation": operation, "webhook_url": url}
    extra = await native.MobileMessageNode._register_external_webhook(webhook_url=url, credential=cred, config=config, node_id="test")
    assert extra == {"external_webhook_id": kind, "signing_secret": cred["webhook_signing_secret"]}
    assert current[kind] == url
    await native.MobileMessageNode._unregister_external_webhook(credential=cred, config={**config, **extra}, node_id="test")
    assert current[kind] is None and calls[-1].method == "DELETE"
    current[kind] = "https://other.example.com/hook"
    with pytest.raises(ValueError, match="different"):
        await native.MobileMessageNode._register_external_webhook(webhook_url=url, credential=cred, config=config, node_id="test")
    before = len(calls)
    await native.MobileMessageNode._unregister_external_webhook(credential=cred, config={**config, **extra}, node_id="test")
    assert len(calls) == before + 1 and calls[-1].method == "GET"
    await native.MobileMessageNode._register_external_webhook(webhook_url=url, credential=cred,
        config={**config, "replace_webhook_url": current[kind]}, node_id="test")
    assert current[kind] == url


def test_mobile_message_ca21345_raw_body_hmac_freshness_case_and_unsigned_mode():
    body = b'{"test":1}'
    secret, stamp = "abc123", str(int(time.time()))
    signature = hmac.new(secret.encode(), stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    headers = {"X-MM-Timestamp": stamp, "X-MM-Signature": signature}
    verify = native.MobileMessageNode.verify_webhook_signature
    assert verify(body, headers, {"signing_secret": secret})
    assert not verify(body + b" ", headers, {"signing_secret": secret})
    assert not verify(body, {**headers, "X-MM-Timestamp": "1754640000"}, {"signing_secret": secret})
    assert not verify(body, {}, {"signing_secret": secret})
    assert verify(body, {}, {})
    assert not verify(body, headers, {})


@pytest.mark.parametrize("key", ["inbound", "delivery", "multipart"])
def test_mobile_message_ca21345_documented_events_agent_turns_and_filter(key):
    event = FIXTURE["events"][key]
    op = "on_inbound_sms" if key == "inbound" else "on_delivery_receipt"
    assert native.MobileMessageNode.filter_trigger_payload(event, {"operation": op})
    assert not native.MobileMessageNode.filter_trigger_payload(event, {"operation": "on_delivery_receipt" if key == "inbound" else "on_inbound_sms"})
    output = native.MobileMessageNode.resolve_trigger_payload(event, {"operation": op})
    turn = native.MobileMessageNode.resolve_agent_event(output)
    for field in ("sender", "to", "message", "received_at"):
        assert event[field] in turn["text"]
    assert turn["conversation_key"]
    if key != "inbound":
        assert event["message_id"] in turn["text"]
        assert f"part {event['part_number']} of {event['total_parts']}" in turn["text"]


def test_mobile_message_ca21345_manual_credential_type_defaults():
    credential = native.MobileMessageCredential.model_validate({"api_username": "test-user", "api_password": "test-password"})
    assert credential.credential_type == native.CREDENTIAL


@pytest.mark.asyncio
async def test_mobile_message_ca21345_cleanup_uses_registered_type_and_row_url(monkeypatch):
    from utils import webhook_delivery
    url = "https://test.hooks.example.test/webhook/row-id"
    monkeypatch.setattr(webhook_delivery, "get_webhook_url", lambda row_id: url)
    def handler(req):
        if req.method == "GET":
            return httpx.Response(200, json={"status": "complete", "webhooks": {"inbound": url, "status": None}, "has_signing_secret": False})
        return httpx.Response(200, json=FIXTURE["responses"]["DELETE /v1/webhooks"])
    calls = mock_http(monkeypatch, handler)
    await native.MobileMessageNode._unregister_external_webhook(credential=CREDS,
        config={"operation": "on_delivery_receipt", "external_webhook_id": "inbound", "webhook_id": "row-id"}, node_id="test")
    assert calls[-1].method == "DELETE" and json.loads(calls[-1].content) == {"type": "inbound"}
