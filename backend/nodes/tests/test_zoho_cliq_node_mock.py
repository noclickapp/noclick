"""Exercise the native node factory with publisher response fixtures and HTTP interception.

These checks pin request serialization, pagination and credential handling without
contacting Zoho or requiring a signed-in account.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import zoho_cliq_node as cliq
from nodes.core.registry import NodeFactory
from utils import ssrf

AUTH = {"credential_type": "zoho_cliq_oauth", "access_token": "fixture-access-token"}
RESPONSES = json.loads((Path(__file__).parent / "fixtures/zoho-cliq/responses.json").read_text())


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def wire(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def send(request):
        requests.append(request)
        assert request.url.host == "cliq.zoho.com"
        assert request.headers["Authorization"] == "Bearer fixture-access-token"
        assert AUTH["access_token"] not in str(request.url)
        status, body = replies.pop(0)
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(cliq, "guarded_async_client", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, arguments=None, credential=None):
    node = NodeFactory.create_node(node_id="cliq-test", node_type="automation-zoho-cliq",
        node_data={"config": {"operation": operation, **(arguments or {})}, "credentials": credential or AUTH})
    return await node.execute({})


CASES = [
    ("list_chats", {"name": "Product", "modified_before": 1711929600000}, {"limit": "100", "name": "Product", "modified_before": "1711929600000"}),
    ("get_chat", {"chat_id": "CHAT_ID"}, {}),
    ("list_chat_members", {"chat_id": "CHAT_ID"}, {}),
    ("create_chat", {"user_id": "70027934"}, {"chat_type": "direct_message", "user_id": "70027934"}),
    ("rename_chat", {"chat_id": "CHAT_ID", "title": "Quarterly Rewards"}, {"operation": "update_title", "title": "Quarterly Rewards"}),
    ("add_chat_members", {"chat_id": "CHAT_ID", "user_ids": ["55743307", "55622727"]}, {"user_ids": ["55743307", "55622727"]}),
    ("leave_chat", {"chat_id": "CHAT_ID"}, {}),
    ("list_channels", {"next_token": "opaque-cursor"}, {"limit": "100", "next_token": "opaque-cursor"}),
    ("get_channel", {"channel_id": "CHANNEL_ID"}, {}),
    ("create_channel", {"name": "Product Launch Planning"}, {"name": "Product Launch Planning", "level": "private", "visibility": "closed"}),
    ("update_channel", {"channel_id": "CHANNEL_ID", "description": "Coordination for all product launch activities"}, {"description": "Coordination for all product launch activities"}),
    ("list_channel_members", {"channel_id": "CHANNEL_ID", "next_token": "next-page"}, {"limit": "50", "next_token": "next-page"}),
    ("add_channel_members", {"channel_id": "CHANNEL_ID", "user_ids": ["108799347"]}, {"members": [{"user_id": "108799347"}]}),
    ("remove_channel_member", {"channel_id": "CHANNEL_ID", "user_id": "USER_ID"}, {}),
    ("send_chat_message", {"chat_id": "CHAT_ID", "text": "Hey!"}, {"text": "Hey!", "sync_message": True}),
    ("send_channel_message", {"channel_id": "CHANNEL_ID", "text": "Hello team", "reply_to": "72374289911"}, {"text": "Hello team", "reply_to": "72374289911", "sync_message": True}),
    ("search_messages", {"query": "release", "next_token": 1790812800000}, {"query": "release", "limit": "50", "next_token": "1790812800000"}),
    ("edit_message", {"chat_id": "CHAT_ID", "message_id": "MESSAGE_ID", "text": "Updated release notes are available."}, {"text": "Updated release notes are available.", "notify_edit": False}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments,expected", CASES, ids=["zoho-cliq-" + row[0] for row in CASES])
async def test_zoho_cliq_operations(wire, operation, arguments, expected):
    requests, replies = wire
    fixture = RESPONSES[operation]
    replies.append((fixture["status"], fixture["body"]))
    result = await run(operation, arguments)
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == fixture["method"]
    path = fixture["path"]
    for key, value in arguments.items():
        path = path.replace("{" + key.upper() + "}", str(value))
    assert request.url.path == "/api/v3" + path
    if request.method == "GET":
        assert dict(request.url.params) == expected
    else:
        assert (json.loads(request.content) if request.content else {}) == expected
    if fixture["body"] is not None:
        assert result["data"] == fixture["body"]


@pytest.mark.asyncio
async def test_zoho_cliq_pagination_is_preserved(wire):
    _, replies = wire
    body = RESPONSES["list_channels"]["body"]
    replies.append((200, body))
    result = await run("list_channels")
    assert result["data"]["has_more"] is True
    assert result["data"]["next_token"] == body["next_token"]


@pytest.mark.asyncio
async def test_zoho_cliq_rejection_preserves_provider_message_and_redacts_token(wire):
    _, replies = wire
    replies.append((401, {"message": "Request was rejected because of invalid AuthToken. fixture-access-token"}))
    with pytest.raises(ValueError) as caught:
        await run("list_channels")
    assert "Request was rejected because of invalid AuthToken." in str(caught.value)
    assert "fixture-access-token" not in str(caught.value)


@pytest.mark.asyncio
async def test_zoho_cliq_refresh_uses_shared_choke_point(wire, monkeypatch):
    import nodes.core.oauth_refresh as oauth
    refresh = AsyncMock()
    monkeypatch.setattr(oauth, "ensure_fresh_oauth_token", refresh)
    wire[1].append((200, RESPONSES["list_channels"]["body"]))
    await run("list_channels")
    assert refresh.call_args.kwargs["provider"] == "zoho_cliq"
    assert refresh.call_args.kwargs["refresh"] == cliq.OAUTH_PROVIDER.refresh


@pytest.mark.parametrize("bad_id", ["../other", "id?token=secret", "https://example.com", "x/y"])
def test_zoho_cliq_rejects_path_injection(bad_id):
    with pytest.raises(ValidationError):
        cliq.GetChat(chat_id=bad_id)


def test_zoho_cliq_manual_credential_default():
    credential = cliq.ZohoCliqOAuthCredential(access_token="fixture-access-token")
    assert credential.credential_type == "zoho_cliq_oauth"
    assert credential.refresh_token is None


def test_zoho_cliq_scopes_and_operations_match():
    assert set(cliq.ROUTES) == {row[0] for row in CASES}
    assert set(cliq.ROUTES) == set(cliq.ZOHO_CLIQ_SCOPES)
    for name, fixture in RESPONSES.items():
        assert set(cliq.ZOHO_CLIQ_SCOPES.require(name).scopes) == set(fixture["scopes"])
    assert "aaaserver.profile.READ" in cliq.ZOHO_CLIQ_SCOPES.declared_scopes()
