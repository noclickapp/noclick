"""Sendbird requests use the actual factory and an offline HTTP transport."""
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import sendbird_node as sb
from nodes.core.registry import NodeFactory
from utils import ssrf

AUTH = {"credential_type": "sendbird_api_token", "app_id": "test-application", "api_token": "fixture-secret-123"}


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        assert request.url.host == "api-test-application.sendbird.com"
        assert request.headers["Api-Token"] == AUTH["api_token"]
        assert AUTH["api_token"] not in str(request.url)
        status, payload = replies.pop(0)
        return httpx.Response(status, json=payload)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(sb, "guarded_async_client", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, replies


def node(operation, **arguments):
    return NodeFactory.create_node(node_id="sendbird-test", node_type="automation-sendbird",
        node_data={"config": {"operation": operation, **arguments}, "credentials": AUTH})


CASES = [
    ("list_users", {}, {"users": [{"user_id": "u1", "nickname": "Jane"}], "next": "page2"}),
    ("get_user", {"user_id": "u1"}, {"user_id": "u1"}),
    ("create_user", {"user_id": "u1", "nickname": "Jane"}, {"user_id": "u1"}),
    ("update_user", {"user_id": "u1", "nickname": "New name"}, {"user_id": "u1"}),
    ("delete_user", {"user_id": "u1"}, {}),
    ("list_group_channels", {}, {"channels": [], "next": ""}),
    ("get_group_channel", {"channel_url": "chat_room"}, {"channel_url": "chat_room"}),
    ("create_group_channel", {"name": "Support", "user_ids": ["u1", "u2"]}, {"channel_url": "chat_room"}),
    ("update_group_channel", {"channel_url": "chat_room", "name": "New name"}, {"channel_url": "chat_room"}),
    ("delete_group_channel", {"channel_url": "chat_room"}, {}),
    ("list_members", {"channel_url": "chat_room"}, {"members": [{"user_id": "u1"}], "next": ""}),
    ("invite_members", {"channel_url": "chat_room", "user_ids": ["u2"]}, {"channel_url": "chat_room"}),
    ("send_message", {"channel_url": "chat_room", "user_id": "u1", "message": "Hello"}, {"message_id": 123, "message": "Hello"}),
    ("get_message", {"channel_url": "chat_room", "message_id": 123}, {"message_id": 123}),
    ("update_message", {"channel_url": "chat_room", "message_id": 123, "message": "Updated"}, {"message_id": 123}),
    ("delete_message", {"channel_url": "chat_room", "message_id": 123}, {}),
    ("list_open_channels", {}, {"channels": [], "next": ""}),
    ("get_open_channel", {"channel_url": "open_room"}, {"channel_url": "open_room"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments,payload", CASES)
async def test_each_operation_sends_one_contract_request(transport, operation, arguments, payload):
    requests, replies = transport
    replies.append((200, payload))
    result = await node(operation, **arguments).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1 and not replies
    method, template, _, fields, queries = sb.OPERATIONS[operation]
    request = requests[0]
    assert request.method == method
    expected = template.format(**{"channel_type": "group_channels", **arguments})
    assert request.url.path == expected
    body = json.loads(request.content) if request.content else None
    if operation == "create_group_channel":
        assert body == {"name": "Support", "users": [{"user_id": "u1"}, {"user_id": "u2"}], "is_distinct": False}
    elif fields:
        assert body == {**{k: arguments.get(k, "") for k in fields}, **({"message_type": "MESG"} if "message" in fields else {})}
    else:
        assert body is None
    if queries:
        assert request.url.params["limit"] == "20"
        assert result["has_more"] == bool(payload["next"])
    if method != "GET":
        assert result["write_acknowledged"] and not result["readback_verified"]


@pytest.mark.asyncio
async def test_query_continuation_and_secret_redaction(transport):
    requests, replies = transport
    replies.append((200, {"users": [{"user_id": "u1", "access_token": "user-secret", "metadata": {"api_token": "nested-secret"}}], "next": "page3"}))
    result = await node("list_users", token="page2", limit=10).execute({})
    assert dict(requests[0].url.params) == {"token": "page2", "limit": "10"}
    assert result["next_page_token"] == "page3"
    assert "secret" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_provider_errors_do_not_claim_success_or_retry(transport, status):
    requests, replies = transport
    replies.append((status, {"error": True, "message": "Rejected " + AUTH["api_token"]}))
    result = await node("update_user", user_id="u1", nickname="Jane").execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert AUTH["api_token"] not in json.dumps(result)
    assert result["write_outcome"] == "unverified" and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"users": {}}, {"users": ["wrong"]}, {"users": [], "next": 5}])
async def test_malformed_lists_are_not_success(transport, payload):
    transport[1].append((200, payload))
    with pytest.raises(ValueError):
        await node("list_users").execute({})


@pytest.mark.parametrize("app_id", ["evil.com", "https://sendbird.com", "x/y", "x@evil", "x:443", "x_foo"])
def test_application_cannot_change_destination(app_id):
    with pytest.raises(ValueError):
        sb.SendbirdAPITokenCredential.model_validate({**AUTH, "app_id": app_id})


@pytest.mark.parametrize("token", ["https://example.com/key", "Bearer secret", "secret\r\nHeader: bad"])
def test_bad_secrets_rejected(token):
    with pytest.raises(ValueError):
        sb.SendbirdAPITokenCredential.model_validate({**AUTH, "api_token": token})


@pytest.mark.asyncio
async def test_path_identifier_is_encoded(transport):
    transport[1].append((200, {"user_id": "person@example.com"}))
    await node("get_user", user_id="person@example.com").execute({})
    assert b"person%40example.com" in transport[0][0].url.raw_path


def test_manual_credential_type_has_default_and_required_fields_are_user_inputs():
    credential = sb.SendbirdAPITokenCredential.model_validate({"app_id": " app-123 ", "api_token": "fixture-token"})
    assert credential.credential_type == "sendbird_api_token" and credential.app_id == "app-123"
    assert {k for k, f in sb.SendbirdAPITokenCredential.model_fields.items() if f.is_required()} == {"app_id", "api_token"}


@pytest.mark.parametrize("identifier", [".", "..", "bad/id", "x?query", "x\x00id"])
def test_user_identifiers_cannot_change_route(identifier):
    with pytest.raises(ValueError):
        node("get_user", user_id=identifier)
    with pytest.raises(ValueError):
        node("create_group_channel", name="Room", user_ids=[identifier])
