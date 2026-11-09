"""Front Core API action, auth, OAuth, and request contracts."""

import json
import re
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from pydantic import ValidationError

from nodes.front_node import CONFIG_MODELS, FRONT_SCOPES, FrontNode, FrontNodeConfig
from nodes.front_operations import OPERATIONS
from nodes.oauth.front_oauth import exchange_code_for_tokens, refresh_access_token

OAUTH = {"credential_type": "front_oauth", "access_token": "access", "refresh_token": "refresh",
         "expires_at": "2099-01-01T00:00:00+00:00"}
API_TOKEN = {"credential_type": "front_api_token", "token": "api-token"}


def node_for(operation_name, *, credentials=None, **fields):
    node = object.__new__(FrontNode)
    node._config = FrontNodeConfig.model_validate({
        "config": {"operation": operation_name, **fields}, "credentials": credentials or API_TOKEN,
    })
    return node


def fields_for(op):
    fields = {key: "id/a @b" for key in re.findall(r"\{([^}]+)\}", op.path)}
    fields.update({key: "required value" for key in op.required_query_fields if key not in fields})
    if op.has_body:
        fields["body_json"] = '{"name":"Example"}'
    return fields


@pytest.mark.parametrize("name", OPERATIONS)
@pytest.mark.asyncio
async def test_every_front_action_dispatches(name):
    op = OPERATIONS[name]
    node = node_for(name, **fields_for(op))
    with patch.object(FrontNode, "_request", new_callable=AsyncMock) as request:
        request.return_value = {"_results": []}
        result = await node.execute({})
    request.assert_awaited_once()
    method, path, token, params, body = request.await_args.args
    assert (method, token) == (op.method, "api-token")
    assert path.startswith("/") and "{" not in path
    if "{" in op.path:
        assert "%2F" in path
    for field in op.required_query_fields:
        assert params[field] == ("id/a @b" if "{" + field + "}" in op.path else "required value")
    assert body == ({"name": "Example"} if op.has_body else None)
    assert result["data"] == {"_results": []}


def test_catalog_and_credentials():
    assert len(OPERATIONS) == len(CONFIG_MODELS) == 244
    assert FRONT_SCOPES.keys_declared == frozenset((*OPERATIONS, "on_new_or_updated_conversation"))
    assert FRONT_SCOPES.declared_scopes() == []
    assert FrontNode.connection_evidence.operation == "get_token_identity"
    with pytest.raises(ValidationError):
        node_for("get_token_identity", credentials={"credential_type": "front_api_token"})


@pytest.mark.asyncio
async def test_request_json_query_and_path():
    node = node_for("update_conversation", conversation_id="cnv/x", body_json='{"status":"open"}',
                    query_json=json.dumps({"limit": 25, "include_archived": False}))
    with patch.object(FrontNode, "_request", new_callable=AsyncMock) as request:
        request.return_value = {"ok": True}
        await node.execute({})
    assert request.await_args.args[1:] == (
        "/conversations/cnv%2Fx", "api-token", {"limit": "25", "include_archived": "false"},
        {"status": "open"})
    with pytest.raises(ValueError, match="JSON object"):
        await node_for("get_token_identity", query_json="[]").execute({})


@pytest.mark.asyncio
async def test_bearer_auth_and_non_json_response():
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"id": "usr_1"})
    real_client = httpx.AsyncClient
    with patch("nodes.front_node.httpx.AsyncClient", side_effect=lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw)):
        result = await node_for("get_token_identity", credentials=API_TOKEN).execute({})
    assert calls[0].url.host == "api2.frontapp.com"
    assert calls[0].headers["Authorization"] == "Bearer api-token"
    assert result["data"] == {"id": "usr_1"}
    with patch("nodes.front_node.httpx.AsyncClient", side_effect=lambda **kw: real_client(
        transport=httpx.MockTransport(lambda request: httpx.Response(
            200, content=b"file", headers={"content-type": "application/octet-stream"})), **kw)):
        data = await FrontNode._request("GET", "/attachments/file", "token", {}, None)
    from nodes.core.binary_output import BinaryOutput
    assert isinstance(data["file"], BinaryOutput)
    assert data["file"].data == b"file"
    assert data["file"].content_type == "application/octet-stream"


@pytest.mark.asyncio
async def test_oauth_credential_calls_core_api_with_bearer_token():
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"id": "usr_1"})
    node = node_for("get_token_identity", credentials=OAUTH)
    node.node_data = {}
    node.user_id = None
    real_client = httpx.AsyncClient
    with patch("nodes.front_node.httpx.AsyncClient", side_effect=lambda **kw: real_client(
        transport=httpx.MockTransport(respond), **kw)):
        await node.execute({})
    assert calls[0].headers["Authorization"] == "Bearer access"


@pytest.mark.asyncio
async def test_oauth_basic_exchange_and_refresh(monkeypatch):
    monkeypatch.setenv("FRONT_CLIENT_ID", "client")
    monkeypatch.setenv("FRONT_CLIENT_SECRET", "secret")
    calls = []
    def respond(request):
        calls.append(request)
        if request.url.path == "/me":
            return httpx.Response(200, json={"name": "Dunder Mifflin Paper Company, Inc."})
        return httpx.Response(200, json={"access_token": "new", "refresh_token": "same-token",
                                         "expires_at": 4070908800})
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(respond)
    with patch("nodes.core.oauth_provider.httpx.AsyncClient", side_effect=lambda **kw: real_client(transport=transport, **kw)):
        minted, account_name = await exchange_code_for_tokens("code", "https://noclick.com/api/auth/front/callback")
        refreshed = await refresh_access_token("same-token")
    assert minted.access_token == refreshed.access_token == "new"
    assert refreshed.refresh_token == "same-token"  # Front rotates only near expiry
    assert calls[0].url.host == "app.frontapp.com"
    assert calls[0].headers["Authorization"].startswith("Basic ")
    assert b"grant_type=authorization_code" in calls[0].content
    assert account_name == "Dunder Mifflin Paper Company, Inc."
    assert b"grant_type=refresh_token" in calls[2].content


@pytest.mark.asyncio
async def test_oauth_refresh_replaces_token_near_expiry(monkeypatch):
    monkeypatch.setenv("FRONT_CLIENT_ID", "client")
    monkeypatch.setenv("FRONT_CLIENT_SECRET", "secret")
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
        "access_token": "new", "refresh_token": "rotated", "expires_at": 4070908800}))
    with patch("nodes.core.oauth_provider.httpx.AsyncClient", side_effect=lambda **kw: real_client(transport=transport, **kw)):
        refreshed = await refresh_access_token("old")
    assert refreshed.refresh_token == "rotated"


@pytest.mark.parametrize(("operation", "fields", "expected_path"), [
    ("update_comment", {"comment_id": "com_123"}, "/comments/com_123"),
    ("edit_draft", {"message_id": "msg_123"}, "/drafts/msg_123"),
])
@pytest.mark.asyncio
async def test_front_patch_routes_match_provider_contract(operation, fields, expected_path):
    # CommentResponse.body and the channel parameter use Front's documented examples.
    body = {"body": "Sometimes I'll start a sentence and I don't even know where it's going. I just hope I find it along the way."}
    if operation == "edit_draft":
        body["channel_id"] = "cha_123"
    node = node_for(operation, **fields, body_json=json.dumps(body))
    with patch.object(FrontNode, "_request", new_callable=AsyncMock) as request:
        request.return_value = {}
        await node.execute({})
    assert request.await_args.args[:2] == ("PATCH", expected_path)


@pytest.mark.asyncio
async def test_front_poll_baseline_update_and_no_duplicate_emission():
    # Values are the pinned provider schema's field examples, projected onto
    # the fields the poll consumes. The list envelope is a transport stub,
    # not a claimed provider-authored response witness.
    from pathlib import Path
    schema = json.loads((Path(__file__).parent / "fixtures/front/conversation-schema.json").read_text())
    item = {key: schema["properties"][key]["example"]
            for key in ("id", "subject", "status", "created_at", "updated_at")}
    node = node_for("on_new_or_updated_conversation")
    node.node_id = "front-poll-test"
    state = {}
    async def update(mutator, **kwargs):
        updated, result = mutator(dict(state))
        if updated is not None:
            state.clear()
            state.update(updated)
        return result
    node._update_node_state = update
    with patch.object(FrontNode, "_request", new_callable=AsyncMock) as request:
        request.return_value = {"_results": [item], "_pagination": {"next": None}}
        assert (await node.execute({}))["conversations"] == []
        assert (await node.execute({}))["conversations"] == []
        item["updated_at"] += 1
        output = await node.execute({})
        assert output["conversations"] == [item]
        event = FrontNode.resolve_agent_event(output)
        assert item["id"] in event["text"] and item["subject"] in event["text"]
        assert (await node.execute({}))["conversations"] == []
        assert request.await_args.args[:4] == (
            "GET", "/conversations", "api-token",
            {"limit": "100", "sort_by": "date", "sort_order": "desc"})


@pytest.mark.asyncio
async def test_front_poll_refuses_malformed_list_and_unbounded_pagination():
    node = node_for("on_new_or_updated_conversation")
    with patch.object(FrontNode, "_request", new_callable=AsyncMock) as request:
        request.return_value = {"error": "not a conversation list"}
        with pytest.raises(ValueError, match="invalid conversation list"):
            await node.execute({})
        request.return_value = {"_results": [], "_pagination": {"next": "/conversations?page_token=repeat"}}
        with pytest.raises(ValueError, match="exceeds 2,000"):
            await node.execute({})
