"""Offline requests and publisher-authored response examples for Kudosity."""
import json
from pathlib import Path

import httpx
import pytest

import nodes.kudosity_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory

TOKEN = "kudosity-test-secret"
ID = "6fdae71c-dad7-4c36-9734-a69693ecf3b4"
EXAMPLES = json.loads((Path(__file__).parent / "fixtures/kudosity/responses.json").read_text())["responses"]


def node(config):
    return NodeFactory.create_node(node_id="kudosity-test", node_type="automation-kudosity", node_data={
        "config": config, "credentials": {"credential_type": "kudosity_api_key", "api_key": TOKEN}})


def transport(monkeypatch, body, status=200, content_type="application/json"):
    requests = []
    def respond(request):
        requests.append(request)
        assert request.url.host == "api.transmitmessage.com"
        assert request.headers["x-api-key"] == TOKEN
        return httpx.Response(status, json=body, headers={"Content-Type": content_type})
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("op,path", [
    ("get_sms", "/v2/sms/{id}"), ("get_mms", "/v2/mms/{id}"),
    ("get_whatsapp_message", "/v2/whatsapp/messages/{id}"),
    ("get_rcs_message", "/v2/rcs/messages/{id}"), ("get_webhook", "/v2/webhook/{id}")])
async def test_gets_preserve_published_responses(monkeypatch, op, path):
    body = EXAMPLES.get("GET " + path, {"id": ID, "status": "DELIVERED"})
    requests = transport(monkeypatch, body)
    result = await node({"operation": op, "id": ID}).execute({})
    assert result["data"] == body
    assert requests[0].method == "GET"
    assert requests[0].url.path == path.replace("{id}", ID)
    assert not requests[0].url.query and not requests[0].content


@pytest.mark.asyncio
@pytest.mark.parametrize("op,path", [("list_whatsapp_messages", "/v2/whatsapp/messages"), ("list_rcs_messages", "/v2/rcs/messages")])
async def test_one_cursor_page_keeps_metadata_without_auto_follow(monkeypatch, op, path):
    body = EXAMPLES["GET " + path]
    requests = transport(monkeypatch, body)
    result = await node({"operation": op, "cursor": "MTIzNDU2", "limit": 10, "date_range": "last_week"}).execute({})
    assert len(requests) == 1
    assert dict(requests[0].url.params) == {"cursor": "MTIzNDU2", "limit": "10", "date_range": "last_week", "direction": "next"}
    assert result["data"]["meta"]["pagination"]["has_next"] is True


@pytest.mark.asyncio
async def test_templates_and_account_specific_webhook_evidence(monkeypatch):
    assert NODE_REGISTRY["automation-kudosity"] is native.KudosityNode
    body = EXAMPLES["GET /v2/whatsapp/templates"]
    requests = transport(monkeypatch, body)
    result = await node({"operation": "list_whatsapp_templates", "status": "APPROVED", "language": "en_US"}).execute({})
    assert result["data"] == body
    assert requests[0].url.params["status"] == "APPROVED"
    requests = transport(monkeypatch, {"webhooks": []})
    result = await node({"operation": native.KudosityNode.connection_evidence.operation}).execute({})
    assert result["data"] == {"webhooks": []} and len(requests) == 1
    assert requests[0].url.path == "/v2/webhook"


@pytest.mark.asyncio
@pytest.mark.parametrize("config,path,expected", [
    ({"operation": "send_sms", "sender": "DemoSender", "recipient": "61411122211", "message": "Hello", "track_links": False}, "/v2/sms", {"sender": "DemoSender", "recipient": "61411122211", "message": "Hello", "track_links": False}),
    ({"operation": "send_mms", "sender": "61481074185", "recipient": "61435795809", "content_urls": ["https://example.com/image.jpg"]}, "/v2/mms", {"sender": "61481074185", "recipient": "61435795809", "content_urls": ["https://example.com/image.jpg"]}),
    ({"operation": "send_whatsapp_message", "sender": "14155238886", "recipient": "61411122211", "template_name": "welcome_new_customer", "parameters": ["Joe"]}, "/v2/whatsapp/messages", {"sender": "14155238886", "recipient": "61411122211", "content_type": "template", "content": {"template": {"name": "welcome_new_customer", "parameters": ["Joe"]}}}),
    ({"operation": "send_rcs_message", "sender": "DemoSender", "recipient": "447903749662", "message": "Hi Michael"}, "/v2/rcs/messages", {"sender": "DemoSender", "recipient": "447903749662", "content_type": "text", "content": {"text": {"message": "Hi Michael"}}}),
    ({"operation": "check_rcs_capabilities", "sender": "DemoSender", "phone_numbers": ["61491570156"]}, "/v2/rcs/capabilities", {"sender": "DemoSender", "phone_numbers": ["61491570156"]}),
])
async def test_send_bodies_and_capabilities_are_one_request(monkeypatch, config, path, expected):
    body = EXAMPLES.get("POST " + path, {"id": ID, "status": "PENDING"})
    requests = transport(monkeypatch, body)
    result = await node(config).execute({})
    assert len(requests) == 1 and requests[0].method == "POST"
    assert requests[0].url.path == path and json.loads(requests[0].content) == expected
    assert result["data"] == body
    assert "delivered" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize("op,method,status", [("create_webhook", "POST", 201), ("create_webhook", "POST", 200), ("update_webhook", "PUT", 200)])
async def test_webhook_create_existing_and_full_update(monkeypatch, op, method, status):
    expected = {"name": "My Webhook", "url": "https://example.com/webhook", "filter": {"event_type": ["SMS_STATUS"]}, "rate_limit": 0}
    body = EXAMPLES["POST /v2/webhook"]
    requests = transport(monkeypatch, body, status)
    result = await node({"operation": op, **expected, **({"id": ID} if method == "PUT" else {})}).execute({})
    assert requests[0].method == method
    assert requests[0].url.path == "/v2/webhook" + ("/" + ID if method == "PUT" else "")
    assert json.loads(requests[0].content) == expected
    assert result["http_status"] == status and result["data"] == body


@pytest.mark.asyncio
async def test_delete_preserves_documented_confirmation(monkeypatch):
    requests = transport(monkeypatch, {"message": "deleted"})
    result = await node({"operation": "delete_webhook", "id": ID}).execute({})
    assert result["data"] == {"message": "deleted"}
    assert requests[0].method == "DELETE" and not requests[0].content


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body,mime", [
    (401, {"status": "Invalid api key"}, "application/json"),
    (429, {"error": {"detail": "Rate limit exceeded"}}, "application/json"),
    (302, {}, "text/html"), (200, [], "application/json"),
    (200, {"error": {"detail": "failure"}}, "application/json"), (200, {}, "text/html"),
])
async def test_failures_never_look_successful_and_do_not_retry(monkeypatch, status, body, mime):
    requests = transport(monkeypatch, body, status, mime)
    with pytest.raises(ValueError) as exc:
        await node({"operation": "list_webhooks"}).execute({})
    assert TOKEN not in str(exc.value)
    assert len(requests) == 1
    if status == 401:
        assert "Invalid api key" in str(exc.value)


@pytest.mark.parametrize("config", [
    {"operation": "get_sms", "id": "../webhook"},
    {"operation": "list_rcs_messages", "limit": 101},
    {"operation": "list_whatsapp_templates", "status": "anything"},
    {"operation": "check_rcs_capabilities", "sender": "DemoSender", "phone_numbers": []},
    {"operation": "create_webhook", "name": "My Webhook", "url": "http://example.com"},
])
def test_invalid_inputs_fail_before_network(config):
    assert native.KudosityNode.validate_config({"config": config, "credentials": {"api_key": TOKEN}})["valid"] is False


def test_manual_credential_default_and_secret_shaping():
    credential = native.KudosityAPIKeyCredential(api_key="  " + TOKEN + "  ")
    assert credential.credential_type == "kudosity_api_key" and credential.api_key == TOKEN
    with pytest.raises(ValueError):
        native.KudosityAPIKeyCredential(api_key="https://example.com")
