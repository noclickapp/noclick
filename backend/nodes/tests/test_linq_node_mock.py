"""Offline Linq request tests; response fixtures are from the pinned provider OpenAPI."""
import json
from pathlib import Path

import httpx
import pytest

from nodes import linq_node as native
from nodes.core.registry import NodeFactory
from nodes.core.connection_evidence import _rows_from_operation

TOKEN = "linq-synthetic-test-token"
ID = "550e8400-e29b-41d4-a716-446655440000"
FIXTURES = json.loads((Path(__file__).parent / "fixtures/linq/responses.json").read_text())


def node(config):
    return NodeFactory.create_node(node_id="linq-test", node_type="automation-linq", node_data={
        "config": config, "credentials": {"credential_type": "linq_api_token", "api_token": TOKEN}})


def transport(monkeypatch, status, body=None):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


# Independent endpoint expectations deliberately do not use the implementation's ROUTES table.
CASES = [
    ({"operation": "list_chats", "from_number": "+13343284472", "cursor": "20"}, "GET", "/v3/chats", 200, {"chats": [], "next_cursor": "40"}),
    ({"operation": "get_chat", "chat_id": ID}, "GET", f"/v3/chats/{ID}", 200, {"id": ID}),
    ({"operation": "create_chat", "from_number": "+12052535597", "to": ["+12052532136"], "text": "Hello! How can I help you today?"}, "POST", "/v3/chats", 201, {"chat": {"id": ID}}),
    ({"operation": "update_chat", "chat_id": ID, "display_name": "Team Discussion"}, "PUT", f"/v3/chats/{ID}", 202, {"status": "pending", "chat_id": ID}),
    ({"operation": "send_message", "chat_id": ID, "text": "Hello, world!", "idempotency_key": "msg-abc123xyz", "reply_to_message_id": ID}, "POST", f"/v3/chats/{ID}/messages", 202, {"chat_id": ID, "message": {"id": ID}}),
    ({"operation": "list_messages", "chat_id": ID, "limit": 50}, "GET", f"/v3/chats/{ID}/messages", 200, {"messages": []}),
    ({"operation": "get_message", "message_id": ID}, "GET", f"/v3/messages/{ID}", 200, {"id": ID}),
    ({"operation": "edit_message", "message_id": ID, "text": "This is the edited message content"}, "PATCH", f"/v3/messages/{ID}", 200, {"id": ID}),
    ({"operation": "delete_message", "message_id": ID}, "DELETE", f"/v3/messages/{ID}", 204, None),
    ({"operation": "send_reaction", "message_id": ID}, "POST", f"/v3/messages/{ID}/reactions", 202, {"status": "accepted"}),
    ({"operation": "list_phone_numbers"}, "GET", "/v3/phone_numbers", 200, FIXTURES["listPhoneNumbers"]),
    ({"operation": "get_attachment", "attachment_id": ID}, "GET", f"/v3/attachments/{ID}", 200, FIXTURES["getAttachment"]),
    ({"operation": "list_blocked_handles"}, "GET", "/v3/blocked_handles", 200, FIXTURES["listBlockedHandles"]),
    ({"operation": "block_handle", "handle": "+12025551234", "reason": "spam"}, "POST", "/v3/blocked_handles", 201, FIXTURES["blockHandle"]),
    ({"operation": "unblock_handle", "handle": "+12025551234"}, "DELETE", "/v3/blocked_handles", 204, None),
    ({"operation": "mark_chat_read", "chat_id": ID}, "POST", f"/v3/chats/{ID}/read", 204, None),
    ({"operation": "start_typing", "chat_id": ID}, "POST", f"/v3/chats/{ID}/typing", 204, None),
    ({"operation": "stop_typing", "chat_id": ID}, "DELETE", f"/v3/chats/{ID}/typing", 204, None),
    ({"operation": "check_imessage", "address": "+15551234567"}, "POST", "/v3/capability/check_imessage", 200, FIXTURES["checkImessageCapability"]),
    ({"operation": "check_rcs", "address": "+15551234567", "from_number": "+15559876543"}, "POST", "/v3/capability/check_rcs", 200, {"address": "+15551234567", "available": False}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,status,body", CASES, ids=[c[0]["operation"] for c in CASES])
async def test_linq_each_operation_one_exact_request(monkeypatch, config, method, path, status, body):
    requests = transport(monkeypatch, status, body)
    result = await node(config).execute({})
    assert result["status"] == "success" and result["data"] == body
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == "/api/partner" + path
    assert request.url.host == "api.linqapp.com"
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    if method == "GET":
        expected = {k: str(v) for k, v in config.items() if k in {"cursor", "limit", "to"}}
        if config["operation"] in {"list_chats", "list_messages"}: expected.setdefault("limit", "20")
        if "from_number" in config: expected["from"] = config["from_number"]
        assert dict(request.url.params) == expected
    elif request.content:
        sent = json.loads(request.content)
        assert not {"chat_id", "message_id", "attachment_id"} & sent.keys()
        action = config["operation"]
        if action in {"create_chat", "send_message"}:
            assert sent["message"]["parts"] == [{"type": "text", "value": config["text"]}]
            assert result["delivery_verified"] is False
            if action == "create_chat": assert sent["from"] == config["from_number"] and sent["to"] == config["to"]
            else:
                assert sent["message"]["idempotency_key"] == config["idempotency_key"]
                assert sent["message"]["reply_to"] == {"message_id": ID}
        elif action == "send_reaction": assert sent == {"operation": "add", "type": "love", "part_index": 0}
        elif action == "unblock_handle": assert sent == {"handle": config["handle"]}
        elif action == "edit_message": assert sent == {"text": config["text"], "part_index": 0}
        elif action.startswith("check_"): assert sent["address"] == config["address"]
    if status == 202: assert result["outcome"] == "accepted"
    if config["operation"] == "delete_message": assert result["unsent"] is False
    if config["operation"] == "list_phone_numbers":
        assert _rows_from_operation(result)[0]["phone_number"] == "+12025551234"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 403, 429, 500])
async def test_linq_rejection_is_not_success_and_redacts_secrets(monkeypatch, status):
    requests = transport(monkeypatch, status, {"error": {"message": "Rejected " + TOKEN}})
    result = await node({"operation": "list_phone_numbers"}).execute({})
    assert result == {"status": "error", "http_status": status, "error": "Rejected [redacted]"}
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"phone_numbers": {}}, {"success": False, "phone_numbers": []}, {"error": {}, "phone_numbers": []}])
async def test_linq_malformed_evidence_is_not_a_working_connection(monkeypatch, body):
    transport(monkeypatch, 200, body)
    with pytest.raises(ValueError): await node({"operation": "list_phone_numbers"}).execute({})


@pytest.mark.asyncio
async def test_linq_edit_empty_204_and_zero_content_actions(monkeypatch):
    transport(monkeypatch, 204)
    result = await node({"operation": "edit_message", "message_id": ID, "text": "Edited"}).execute({})
    assert result["data"] is None and result["outcome"] == "acknowledged"


@pytest.mark.parametrize("config", [{"operation": "get_chat", "chat_id": "../messages"}, {"operation": "list_chats", "limit": 101}, {"operation": "create_chat", "from_number": "invalid", "to": [], "text": "hello"}])
def test_linq_invalid_arguments_refused(config):
    with pytest.raises(ValueError): node(config)
