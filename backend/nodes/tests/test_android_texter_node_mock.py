"""Exercise the native factory and HTTP boundary without a provider account."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import android_texter_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory
from nodes.core.connection_evidence import _rows_from_operation, _identity_label

TOKEN = "synthetic-android-texter-api-key"
DOCS = json.loads((Path(__file__).parent / "fixtures/android-texter/documented_responses.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=True):
    return NodeFactory.create_node(node_id="android-texter-fixture", node_type="automation-android-texter",
        node_data={"config": config, "credentials": {"credential_type": "android_texter_api_key", "api_key": TOKEN} if credentials else None})


def transport(monkeypatch, reply, status=200):
    requests = []

    def respond(request):
        requests.append(request)
        return reply(request) if callable(reply) else httpx.Response(status, json=reply)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


# Request expectations are independently transcribed from the provider contract.
CASES = [
    ("get_current_user", {}, "GET", "/me", {}, None, 200, "GET /api/me"),
    ("list_devices", {}, "GET", "/v1/devices", {}, None, 200, "GET /api/devices"),
    ("get_device", {"device_id": "uuid"}, "GET", "/devices/uuid", {}, None, 200, "GET /api/devices/:id"),
    ("send_message", {"phone": "+14155551234", "message": "Hello from the API!"}, "POST", "/v1/messages/send", {}, {"phone": "+14155551234", "message": "Hello from the API!"}, 200, "POST /api/messages/send"),
    ("send_broadcast", {"phones": ["+14155551234"], "message": "Hello"}, "POST", "/messages/broadcast", {}, {"phones": ["+14155551234"], "message": "Hello", "device_mode": "auto"}, 200, None),
    ("get_message_status", {"message_id": "uuid"}, "GET", "/v1/messages/status/uuid", {}, None, 200, "GET /api/v1/messages/status/:id"),
    ("get_conversation_history", {"phone": "+14155551234"}, "GET", "/v1/messages/history/+14155551234", {"page": "1", "limit": "50"}, None, 200, "GET /api/v1/messages/history/:phone"),
    ("list_received_messages", {}, "GET", "/messages/received", {"page": "1", "limit": "50"}, None, 200, "GET /api/messages/received"),
    ("list_conversations", {}, "GET", "/messages/conversations", {"view": "inbox", "limit": "50"}, None, 200, "GET /api/messages/conversations"),
    ("archive_conversation", {"thread_ref": "uuid", "archived": False}, "POST", "/messages/conversations/archive", {"thread_ref": "uuid", "archived": "false"}, None, 200, "POST /api/messages/conversations/archive"),
    ("delete_conversation", {"thread_ref": "uuid"}, "DELETE", "/v1/messages/thread", {"thread_ref": "uuid"}, None, 200, "DELETE /api/messages/thread"),
    ("list_scheduled_messages", {}, "GET", "/messages/scheduled", {}, None, 200, "GET /api/messages/scheduled"),
    ("cancel_scheduled_message", {"message_id": "uuid"}, "DELETE", "/messages/scheduled/uuid", {}, None, 200, "DELETE /api/messages/scheduled/:id"),
    ("list_contacts", {"page": 2, "limit": 75, "search": "A + B", "tag": "customer"}, "GET", "/contacts", {"page": "2", "limit": "75", "search": "A + B", "tag": "customer"}, None, 200, None),
    ("upsert_contact", {"phone": "+14155551234", "name": "Sam", "tags": []}, "POST", "/contacts", {}, {"phone": "+14155551234", "name": "Sam", "tags": []}, 201, None),
    ("list_quick_replies", {}, "GET", "/quick-replies", {}, None, 200, "GET /api/quick-replies"),
    ("create_quick_reply", {"shortcut": "thanks", "title": "thanks", "body": "Thank you!"}, "POST", "/quick-replies", {}, {"shortcut": "thanks", "title": "thanks", "body": "Thank you!"}, 201, "POST /api/quick-replies"),
    ("update_quick_reply", {"quick_reply_id": "uuid", "shortcut": "thanks", "title": "thanks", "body": "Updated message body"}, "PUT", "/quick-replies/uuid", {}, {"shortcut": "thanks", "title": "thanks", "body": "Updated message body"}, 200, "PUT /api/quick-replies/:id"),
    ("delete_quick_reply", {"quick_reply_id": "uuid"}, "DELETE", "/quick-replies/uuid", {}, None, 200, "DELETE /api/quick-replies/:id"),
    ("flag_spam", {"phone": "+15551234567", "country": "GB"}, "POST", "/spam/flag", {}, {"phone": "+15551234567", "country": "GB"}, 200, None),
    ("unflag_spam", {"phone": "+15551234567"}, "POST", "/spam/unflag", {}, {"phone": "+15551234567"}, 200, None),
    ("list_spam_threads", {}, "GET", "/spam/threads", {}, None, 200, None),
    ("list_webhooks", {}, "GET", "/webhooks", {}, None, 200, "GET /api/webhooks"),
    ("create_webhook", {"url": "https://your-server.com/webhook", "events": ["message.received"]}, "POST", "/v1/webhooks", {}, {"url": "https://your-server.com/webhook", "events": ["message.received"]}, 201, "POST /api/v1/webhooks"),
    ("delete_webhook", {"webhook_id": "uuid"}, "DELETE", "/v1/webhooks/uuid", {}, None, 200, "DELETE /api/webhooks/:id"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,query,body,status,example", CASES, ids=["android-texter-" + case[0] for case in CASES])
async def test_android_texter_native_requests_and_documented_responses(monkeypatch, operation, config, method, path, query, body, status, example):
    response = DOCS[example]["body"] if example else {"synthetic_fixture": True}
    requests = transport(monkeypatch, response, status)
    result = await node({"operation": operation, **config}).execute({})
    assert result == {"operation": operation, "status": "success", "data": response}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == "/api" + path
    assert request.url.host == "androidtexter.com" and request.url.scheme == "https"
    assert dict(request.url.params) == query
    assert request.headers["X-API-Key"] == TOKEN and "Authorization" not in request.headers
    assert (json.loads(request.content) if request.content else None) == body
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_android_texter_optional_send_fields_zero_sim_slot_and_broadcast_partial_failure(monkeypatch):
    requests = transport(monkeypatch, {"message_id": "uuid", "status": 200})
    config = {"phone": "+14155551234", "message": "Hello", "country": "GB", "sim_slot": 0,
        "thread_id": "42", "device_id": "uuid", "media_url": "https://example.com/flyer.jpg", "scheduled_at": "2026-06-01T10:30:00Z"}
    assert (await node({"operation": "send_message", **config}).execute({}))["status"] == "success"
    assert json.loads(requests[0].content) == config
    partial = {"sent": 0, "failed": 1, "results": [{"phone": "+14155551234", "error": "no online device"}]}
    requests = transport(monkeypatch, partial)
    result = await node({"operation": "send_broadcast", "phones": ["+14155551234"], "message": "Hello"}).execute({})
    assert result["data"] == partial and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 400, 401, 403, 404, 409, 429, 500, 503])
async def test_android_texter_errors_preserve_provider_words_without_retry_or_key(monkeypatch, status):
    requests = transport(monkeypatch, {"error": "provider rejected " + TOKEN}, status)
    result = await node({"operation": "send_message", "phone": "+14155551234", "message": "Hello"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert result["error"] == "provider rejected [redacted]" and TOKEN not in str(result)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [[], {"error": "denied"}, {"success": False, "message": "denied"}])
async def test_android_texter_success_status_does_not_hide_provider_failure(monkeypatch, response):
    transport(monkeypatch, response)
    assert (await node({"operation": "list_devices"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_android_texter_non_json_and_timeout_are_errors(monkeypatch):
    requests = transport(monkeypatch, lambda r: httpx.Response(200, text="<html>Sign in</html>"))
    assert (await node({"operation": "list_devices"}).execute({}))["status"] == "error"
    assert len(requests) == 1

    def timeout(request):
        raise httpx.ReadTimeout("synthetic timeout", request=request)

    requests = transport(monkeypatch, timeout)
    assert (await node({"operation": "list_devices"}).execute({}))["status"] == "error"
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_android_texter_connection_evidence_exposes_account_owned_devices_and_identity(monkeypatch):
    transport(monkeypatch, DOCS["GET /api/devices"]["body"])
    payload = await node({"operation": "list_devices"}).execute({})
    assert _rows_from_operation(payload)[0]["name"] == "Pixel 7"
    transport(monkeypatch, DOCS["GET /api/me"]["body"])
    payload = await node({"operation": "get_current_user"}).execute({})
    assert _identity_label(payload["data"], native.AndroidTexterNode.connection_evidence.identity_keys) == "Phil"


@pytest.mark.parametrize("config", [
    {"operation": "send_message", "phone": "x"},
    {"operation": "send_message", "phone": "x", "message": "x" * 1601},
    {"operation": "send_broadcast", "phones": ["x"], "message": "x", "device_mode": "specific"},
    {"operation": "send_broadcast", "phones": [], "message": "x"},
    {"operation": "list_received_messages", "page": 0},
    {"operation": "list_received_messages", "limit": 101},
    {"operation": "archive_conversation"},
    {"operation": "upsert_contact", "phone": "x", "unknown_field": "x"},
])
def test_android_texter_invalid_configs_fail_before_transport(config):
    with pytest.raises((ValidationError, ValueError)):
        native.AndroidTexterNode.parse_config({"config": config})


@pytest.mark.asyncio
@pytest.mark.parametrize("identifier", ["..", "../me", "x?token=bad", "x#fragment", "x\\other", "x\nheader"])
async def test_android_texter_resource_ids_cannot_change_route(monkeypatch, identifier):
    requests = transport(monkeypatch, {})
    with pytest.raises(ValueError):
        await node({"operation": "get_device", "device_id": identifier}).execute({})
    assert not requests


def test_android_texter_registered_schema_and_evidence_contract():
    assert NODE_REGISTRY["automation-android-texter"] is native.AndroidTexterNode
    schema = native.AndroidTexterNode.get_config_schema()
    assert len(schema["properties"]["config"]["discriminator"]["mapping"]) == 25
    assert schema["$defs"]["AndroidTexterApiKeyCredential"]["properties"]["api_key"]["ui:widget"] == "password"
    assert native.AndroidTexterNode.connection_evidence.operation == "list_devices"
