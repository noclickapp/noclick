"""Miro OAuth and REST contracts, including every catalogued board API action."""

import json
import re
from unittest.mock import Mock
from urllib.parse import quote

import httpx
import pytest
import respx

from nodes.miro_node import (
    AttachTag, CreateBoard, CreateCard, CreateStickyNote, CreateTag, CreateText,
    DeleteBoard, DeleteItem, GetBoard, GetItem, GetTag, GetTokenContext,
    ListBoardMembers, ListBoards, ListItems, ListItemTags, ListTags,
    BOARD_API_CONFIGS, REQUIRED_QUERY_FIELDS, MiroNode, MiroNodeConfig, MiroOAuthCredential, RemoveTag, ShareBoard,
    UpdateBoard, UpdateCard, UpdateStickyNote,
)
from nodes.miro_operations import OPERATIONS as BOARD_API_OPERATIONS
from nodes.oauth.miro_oauth import OAUTH_PROVIDER, refresh_access_token
from nodes.core.oauth_refresh import RotatedRefreshTokenMissing


def make_node(operation):
    credential = MiroOAuthCredential(
        access_token="access", refresh_token="refresh", expires_at="2099-01-01T00:00:00Z")
    return MiroNode(
        node_id="miro-test", node_type="automation-miro", node_data={},
        config=MiroNodeConfig(config=operation, credentials=credential),
        sio=Mock(), sid="sid", workflow_id="workflow", user_id="user",
    )


@pytest.mark.asyncio
async def test_oauth_exchange_and_rotating_refresh_token(monkeypatch):
    monkeypatch.setenv("MIRO_CLIENT_ID", "client")
    monkeypatch.setenv("MIRO_CLIENT_SECRET", "secret")
    with respx.mock(assert_all_called=True) as router:
        token = router.post("https://api.miro.com/v1/oauth/token").mock(side_effect=[
            httpx.Response(200, json={"access_token": "first", "refresh_token": "renew",
                                      "expires_in": 3600, "team_id": "team-1", "user_id": "user-1",
                                      "scope": "boards:read boards:write"}),
            httpx.Response(200, json={"access_token": "second", "refresh_token": "rotated", "expires_in": 3600}),
        ])
        router.get("https://api.miro.com/v1/oauth-token").mock(
            return_value=httpx.Response(200, json={"user": {"name": "John Smith"}}))
        first, account_name = await OAUTH_PROVIDER.exchange("code", "https://noclick.com/api/auth/oauth/miro/callback")
        second = await refresh_access_token(first.refresh_token)
    assert token.call_count == 2
    assert account_name == "John Smith"
    assert first.team_id == "team-1"
    assert first.scope == "boards:read boards:write"
    assert second.refresh_token == "rotated"
    exchange_form = dict(httpx.QueryParams(token.calls[0].request.content.decode()))
    refresh_form = dict(httpx.QueryParams(token.calls[1].request.content.decode()))
    assert exchange_form["grant_type"] == "authorization_code"
    assert exchange_form["redirect_uri"] == "https://noclick.com/api/auth/oauth/miro/callback"
    assert refresh_form["grant_type"] == "refresh_token"
    assert refresh_form["refresh_token"] == "renew"


@pytest.mark.asyncio
async def test_refresh_rejects_missing_rotated_token(monkeypatch):
    monkeypatch.setenv("MIRO_CLIENT_ID", "client")
    monkeypatch.setenv("MIRO_CLIENT_SECRET", "secret")
    with respx.mock(assert_all_called=True) as router:
        router.post("https://api.miro.com/v1/oauth/token").mock(
            return_value=httpx.Response(200, json={"access_token": "new", "expires_in": 3600}))
        with pytest.raises(RotatedRefreshTokenMissing, match="consumed single-use token"):
            await refresh_access_token("consumed")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,method,path,expected_body", [
    (ListBoards(), "GET", "/boards", None),
    (GetBoard(board_id="board/1"), "GET", "/boards/board%2F1", None),
    (CreateBoard(name="Planning", description="Q4"), "POST", "/boards", {"name": "Planning", "description": "Q4"}),
    (UpdateBoard(board_id="b", name="Updated"), "PATCH", "/boards/b", {"name": "Updated"}),
    (DeleteBoard(board_id="b"), "DELETE", "/boards/b", None),
    (ListBoardMembers(board_id="b"), "GET", "/boards/b/members", None),
    (ShareBoard(board_id="b", email="member@example.com"), "POST", "/boards/b/members", {"emails": ["member@example.com"], "role": "viewer"}),
    (ListItems(board_id="b"), "GET", "/boards/b/items", None),
    (ListItems(board_id="b", tag_id="tag-1"), "GET", "/boards/b/items", None),
    (GetItem(board_id="b", item_id="i"), "GET", "/boards/b/items/i", None),
    (CreateStickyNote(board_id="b", content="Remember"), "POST", "/boards/b/sticky_notes", {"data": {"content": "Remember"}, "position": {"x": 0, "y": 0}}),
    (UpdateStickyNote(board_id="b", item_id="i", content="Done"), "PATCH", "/boards/b/sticky_notes/i", {"data": {"content": "Done"}}),
    (CreateCard(board_id="b", title="Task"), "POST", "/boards/b/cards", {"data": {"title": "Task", "description": ""}}),
    (UpdateCard(board_id="b", item_id="i", title="Done"), "PATCH", "/boards/b/cards/i", {"data": {"title": "Done"}}),
    (CreateText(board_id="b", content="Title"), "POST", "/boards/b/texts", {"data": {"content": "Title"}}),
    (DeleteItem(board_id="b", item_id="i"), "DELETE", "/boards/b/items/i", None),
    (ListTags(board_id="b"), "GET", "/boards/b/tags", None),
    (GetTag(board_id="b", tag_id="t"), "GET", "/boards/b/tags/t", None),
    (ListItemTags(board_id="b", item_id="i"), "GET", "/boards/b/items/i/tags", None),
    (CreateTag(board_id="b", title="Urgent"), "POST", "/boards/b/tags", {"title": "Urgent", "fillColor": "red"}),
    (AttachTag(board_id="b", item_id="i", tag_id="t"), "POST", "/boards/b/items/i", None),
    (RemoveTag(board_id="b", item_id="i", tag_id="t"), "DELETE", "/boards/b/items/i", None),
])
async def test_operation_request_contract(operation, method, path, expected_body, monkeypatch):
    node = make_node(operation)
    async def no_refresh(_):
        return "access"
    monkeypatch.setattr(node, "_token", no_refresh)
    with respx.mock(assert_all_called=True) as router:
        response = httpx.Response(204) if method == "DELETE" else httpx.Response(200, json={"id": "result"})
        route = router.request(method, "https://api.miro.com/v2" + path).mock(return_value=response)
        result = await node.execute({})
    assert route.called
    request = route.calls[0].request
    assert request.headers["Authorization"] == "Bearer access"
    if expected_body is not None:
        assert json.loads(request.content) == expected_body
    if isinstance(operation, (AttachTag, RemoveTag)):
        assert request.url.params["tag_id"] == "t"
    if isinstance(operation, ListItems) and operation.tag_id:
        assert request.url.params["tag_id"] == operation.tag_id
    if isinstance(operation, ListItems) and not operation.tag_id:
        assert "tag_id" not in request.url.params
        assert "cursor" not in request.url.params
        assert "type" not in request.url.params
    assert result["status"] == "success"
    assert result["operation"] == operation.operation


@pytest.mark.asyncio
@pytest.mark.parametrize("name,spec", list(BOARD_API_OPERATIONS.items()))
async def test_generated_board_api_request_contract(name, spec, monkeypatch):
    """Every generated action reaches the documented method and encoded path."""
    path_args = {field: "sample/id" for field in re.findall(r"\{([^}]+)\}", spec.path)}
    kwargs = {"operation": name, **path_args}
    for field, typ in REQUIRED_QUERY_FIELDS.get(name, {}).items():
        kwargs[field] = True if typ is bool else "sample/id"
    if spec.body_type == "application/json":
        kwargs["body_json"] = '{"name":"demo"}'
    config = BOARD_API_CONFIGS[name](**kwargs)
    node = make_node(config)
    async def no_refresh(_):
        return "access"
    monkeypatch.setattr(node, "_token", no_refresh)
    path = spec.path
    for field in path_args:
        path = path.replace("{" + field + "}", quote(path_args[field], safe=""))
    with respx.mock(assert_all_called=True) as router:
        route = router.request(spec.method, "https://api.miro.com" + path).mock(
            return_value=httpx.Response(200, json={"id": "result"}))
        result = await node.execute({})
    assert route.called
    assert route.calls[0].request.headers["Authorization"] == "Bearer access"
    for field, typ in REQUIRED_QUERY_FIELDS.get(name, {}).items():
        assert route.calls[0].request.url.params[field] == ("true" if typ is bool else "sample/id")
    if spec.body_type == "application/json":
        assert json.loads(route.calls[0].request.content) == {"name": "demo"}
    assert result == {"status": "success", "operation": name, "data": {"id": "result"}}


@pytest.mark.asyncio
async def test_token_context_operation_and_api_error(monkeypatch):
    node = make_node(GetTokenContext())
    async def no_refresh(_):
        return "access"
    monkeypatch.setattr(node, "_token", no_refresh)
    with respx.mock(assert_all_called=True) as router:
        route = router.get("https://api.miro.com/v1/oauth-token").mock(
            return_value=httpx.Response(200, json={"user": {"name": "Ava"}}))
        result = await node.execute({})
    assert route.called
    assert result["data"]["user"]["name"] == "Ava"
    with respx.mock(assert_all_called=True) as router:
        router.get("https://api.miro.com/v2/boards").mock(
            return_value=httpx.Response(403, json={"message": "Insufficient permissions"}))
        with pytest.raises(ValueError, match="403: Insufficient permissions"):
            await make_node(ListBoards())._request("access", "GET", "/boards")


@pytest.mark.asyncio
async def test_board_picker_and_missing_update_data():
    with respx.mock(assert_all_called=True) as router:
        router.get("https://api.miro.com/v2/boards").mock(return_value=httpx.Response(200, json={
            "data": [{"id": "b", "name": "Planning"}],
        }))
        options = await MiroNode.load_field_options("board_id", {"access_token": "access"}, page_token="0", search="Plan")
    assert options == [{"value": "b", "label": "Planning"}]
    with pytest.raises(ValueError, match="Provide a name or description"):
        node = make_node(UpdateBoard(board_id="b"))
        async def no_refresh(_):
            return "access"
        node._token = no_refresh
        await node.execute({})


@pytest.mark.asyncio
async def test_binary_response_returns_binary_output():
    from nodes.core.binary_output import BinaryOutput

    with respx.mock(assert_all_called=True) as router:
        router.get("https://api.miro.com/v2/boards/b/export").mock(
            return_value=httpx.Response(200, content=b"%PDF-1.7", headers={"content-type": "application/pdf"}))
        result = await MiroNode._request("access", "GET", "/boards/b/export")
    assert isinstance(result, BinaryOutput)
    assert result.data == b"%PDF-1.7"
    assert result.content_type == "application/pdf"


@pytest.mark.asyncio
async def test_oauth_identity_missing_name_fails_connection(monkeypatch):
    monkeypatch.setenv("MIRO_CLIENT_ID", "client")
    monkeypatch.setenv("MIRO_CLIENT_SECRET", "secret")
    with respx.mock(assert_all_called=True) as router:
        router.post("https://api.miro.com/v1/oauth/token").mock(return_value=httpx.Response(
            200, json={"access_token": "first", "refresh_token": "renew", "expires_in": 3600}))
        router.get("https://api.miro.com/v1/oauth-token").mock(return_value=httpx.Response(
            200, json={"user": {"name": ""}}))
        with pytest.raises(ValueError, match="returned no account name"):
            await OAUTH_PROVIDER.exchange("code", "https://noclick.com/api/auth/oauth/miro/callback")
