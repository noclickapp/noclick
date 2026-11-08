"""Smartsheet OAuth and REST request contracts for all 21 operations."""

import json
from unittest.mock import Mock

import httpx
import pytest
import respx

from nodes.oauth.smartsheet_oauth import OAUTH_PROVIDER, refresh_access_token
from nodes.smartsheet_node import (
    AddColumn, AddRows, CreateComment, CreateDiscussion, CreateSheet, DeleteColumn,
    DeleteRows, DeleteSheet, GetColumn, GetCurrentUser, GetDiscussion, GetRow,
    GetSheet, GetWorkspace, ListColumns, ListDiscussions, ListSheets,
    ListWorkspaces, SmartsheetNode, SmartsheetNodeConfig,
    SmartsheetOAuthCredential, SmartsheetPATCredential, UpdateColumn,
    UpdateRows, UpdateSheet,
)


def make_node(operation, credential=None):
    credential = credential or SmartsheetOAuthCredential(
        access_token="access", refresh_token="refresh", expires_at="2099-01-01T00:00:00Z")
    return SmartsheetNode(
        node_id="smartsheet-test", node_type="automation-smartsheet", node_data={},
        config=SmartsheetNodeConfig(config=operation, credentials=credential),
        sio=Mock(), sid="sid", workflow_id="workflow", user_id="user",
    )


@pytest.mark.asyncio
async def test_oauth_exchange_and_rotating_refresh(monkeypatch):
    monkeypatch.setenv("SMARTSHEET_CLIENT_ID", "client")
    monkeypatch.setenv("SMARTSHEET_CLIENT_SECRET", "secret")
    with respx.mock(assert_all_called=True) as router:
        route = router.post("https://api.smartsheet.com/2.0/token").mock(side_effect=[
            httpx.Response(200, json={"access_token": "first", "refresh_token": "renew", "expires_in": 604799}),
            httpx.Response(200, json={"access_token": "second", "refresh_token": "rotated", "expires_in": 604799}),
        ])
        router.get("https://api.smartsheet.com/2.0/users/me").mock(
            return_value=httpx.Response(200, json={"email": "member@example.com"}))
        first, name = await OAUTH_PROVIDER.exchange("code", "https://app.example.com/api/auth/oauth/smartsheet/callback")
        assert name == "member@example.com"
        second = await refresh_access_token(first.refresh_token)
    assert route.call_count == 2
    assert second.refresh_token == "rotated"
    exchange_form = dict(httpx.QueryParams(route.calls[0].request.content.decode()))
    refresh_form = dict(httpx.QueryParams(route.calls[1].request.content.decode()))
    assert exchange_form == {"grant_type": "authorization_code", "code": "code", "client_id": "client", "client_secret": "secret", "redirect_uri": "https://app.example.com/api/auth/oauth/smartsheet/callback"}
    assert refresh_form["grant_type"] == "refresh_token"
    assert refresh_form["refresh_token"] == "renew"


@pytest.mark.asyncio
async def test_missing_refresh_token_is_rejected(monkeypatch):
    monkeypatch.setenv("SMARTSHEET_CLIENT_ID", "client")
    monkeypatch.setenv("SMARTSHEET_CLIENT_SECRET", "secret")
    with respx.mock(assert_all_called=True) as router:
        router.post("https://api.smartsheet.com/2.0/token").mock(
            return_value=httpx.Response(200, json={"access_token": "new", "expires_in": 604799}))
        with pytest.raises(ValueError, match="did not include a refresh_token"):
            await refresh_access_token("consumed")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,method,path,expected_body", [
    (GetCurrentUser(), "GET", "/users/me", None),
    (ListSheets(), "GET", "/sheets", None),
    (GetSheet(sheet_id="1"), "GET", "/sheets/1", None),
    (CreateSheet(workspace_id="2", name="Plan", columns_json='[{"title":"Task","type":"TEXT_NUMBER","primary":true}]'),
     "POST", "/workspaces/2/sheets", {"name": "Plan", "columns": [{"title": "Task", "type": "TEXT_NUMBER", "primary": True}]}),
    (UpdateSheet(sheet_id="1", name="Renamed"), "PUT", "/sheets/1", {"name": "Renamed"}),
    (DeleteSheet(sheet_id="1"), "DELETE", "/sheets/1", None),
    (ListWorkspaces(), "GET", "/workspaces", None),
    (GetWorkspace(workspace_id="2"), "GET", "/workspaces/2/metadata", None),
    (GetRow(sheet_id="1", row_id="3"), "GET", "/sheets/1/rows/3", None),
    (AddRows(sheet_id="1", rows_json='[{"toBottom":true,"cells":[{"columnId":4,"value":"Task"}]}]'),
     "POST", "/sheets/1/rows", [{"toBottom": True, "cells": [{"columnId": 4, "value": "Task"}]}]),
    (UpdateRows(sheet_id="1", rows_json='[{"id":3,"cells":[{"columnId":4,"value":"Done"}]}]'),
     "PUT", "/sheets/1/rows", [{"id": 3, "cells": [{"columnId": 4, "value": "Done"}]}]),
    (DeleteRows(sheet_id="1", row_ids="3, 4"), "DELETE", "/sheets/1/rows", None),
    (ListColumns(sheet_id="1"), "GET", "/sheets/1/columns", None),
    (GetColumn(sheet_id="1", column_id="4"), "GET", "/sheets/1/columns/4", None),
    (AddColumn(sheet_id="1", title="Owner", column_type="CONTACT_LIST", index=1),
     "POST", "/sheets/1/columns", [{"title": "Owner", "type": "CONTACT_LIST", "index": 1}]),
    (UpdateColumn(sheet_id="1", column_id="4", title="Assignee"),
     "PUT", "/sheets/1/columns/4", {"title": "Assignee"}),
    (DeleteColumn(sheet_id="1", column_id="4"), "DELETE", "/sheets/1/columns/4", None),
    (ListDiscussions(sheet_id="1"), "GET", "/sheets/1/discussions", None),
    (GetDiscussion(sheet_id="1", discussion_id="5"), "GET", "/sheets/1/discussions/5", None),
    (CreateDiscussion(sheet_id="1", comment="Please review"),
     "POST", "/sheets/1/discussions", {"comment": {"text": "Please review"}}),
    (CreateComment(sheet_id="1", discussion_id="5", comment="Done"),
     "POST", "/sheets/1/discussions/5/comments", {"text": "Done"}),
])
async def test_operation_request_contract(operation, method, path, expected_body, monkeypatch):
    node = make_node(operation)
    async def no_refresh(_):
        return "access"
    monkeypatch.setattr(node, "_token", no_refresh)
    with respx.mock(assert_all_called=True) as router:
        response = httpx.Response(204) if method == "DELETE" else httpx.Response(200, json={"result": {"id": "result"}})
        route = router.request(method, "https://api.smartsheet.com/2.0" + path).mock(return_value=response)
        result = await node.execute({})
    assert route.called
    request = route.calls[0].request
    assert request.headers["Authorization"] == "Bearer access"
    if expected_body is not None:
        assert json.loads(request.content) == expected_body
    if isinstance(operation, DeleteRows):
        assert request.url.params["ids"] == "3,4"
    assert result["status"] == "success"
    assert result["operation"] == operation.operation


@pytest.mark.asyncio
async def test_pat_credential_and_resource_picker(monkeypatch):
    node = make_node(GetCurrentUser(), SmartsheetPATCredential(access_token="pat"))
    with respx.mock(assert_all_called=True) as router:
        router.get("https://api.smartsheet.com/2.0/users/me").mock(
            return_value=httpx.Response(200, json={"email": "admin@noclick.com"}))
        result = await node.execute({})
    assert result["data"]["email"] == "admin@noclick.com"
    with respx.mock(assert_all_called=True) as router:
        router.get("https://api.smartsheet.com/2.0/sheets").mock(
            return_value=httpx.Response(200, json={"data": [{"id": 1, "name": "Plan"}]}))
        options = await SmartsheetNode.load_field_options("sheet_id", {"access_token": "pat"}, page_token="1", search="Plan")
    assert options == [{"value": "1", "label": "Plan"}]


@pytest.mark.asyncio
async def test_invalid_row_json_and_api_error(monkeypatch):
    node = make_node(AddRows(sheet_id="1", rows_json='{"not":"an array"}'))
    async def no_refresh(_):
        return "access"
    monkeypatch.setattr(node, "_token", no_refresh)
    with pytest.raises(ValueError, match="JSON array"):
        await node.execute({})
    with respx.mock(assert_all_called=True) as router:
        router.get("https://api.smartsheet.com/2.0/sheets").mock(
            return_value=httpx.Response(403, json={"message": "Permission denied"}))
        with pytest.raises(ValueError, match="403: Permission denied"):
            await SmartsheetNode._request("pat", "GET", "/sheets")


@pytest.mark.asyncio
async def test_execute_keeps_rotated_credentials_for_repeated_calls(monkeypatch):
    from unittest.mock import AsyncMock

    node = make_node(GetCurrentUser())
    credential = node.config.credentials

    async def rotate(**kwargs):
        kwargs["credential"].update(
            access_token="fresh", refresh_token="successor", expires_at="2099-02-01T00:00:00Z")
        return "fresh"

    refresh = AsyncMock(side_effect=rotate)
    monkeypatch.setattr("nodes.core.oauth_refresh.ensure_fresh_oauth_token", refresh)
    assert await node._token(credential) == "fresh"
    assert credential.access_token == "fresh"
    assert credential.refresh_token == "successor"
    assert credential.expires_at == "2099-02-01T00:00:00Z"
    assert await node._token(credential) == "fresh"
    assert refresh.call_args.kwargs["credential"]["refresh_token"] == "successor"
