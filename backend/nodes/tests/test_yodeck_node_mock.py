"""Yodeck factory, connect, dispatcher and credential regressions.
Synthetic MockTransport resources exercise native seams, not provider or DB access.
"""
from contextlib import asynccontextmanager
from copy import deepcopy
from unittest.mock import AsyncMock

import httpx
import pytest
from nodes import yodeck_node as native
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation
from nodes.core.credential_connect import validate_for_connect

NT = "automation-yodeck"
USER = "11111111-1111-4111-8111-111111111111"
CID = "22222222-2222-4222-8222-222222222222"
KEY = {"credential_type": native.TYPE, "token_label": "fixture", "token_value": "synthetic-issued-value", "workspace_id": "42"}
WORKSPACE = {"id": 42, "name": "opt-in-workspace", "parent_workspace": None, "last_applied": "2026-10-01T12:30:00.123", "description": "omit-private", "working_hours": {"secret": "omit-private"}}
FOLDER = {"id": 12, "name": "opt-in-folder", "workspace": {"id": 42, "name": "omit-nested"}, "parent_folder": None, "description": "omit-private"}
PLAYLIST = {"id": 13, "name": "opt-in-playlist", "workspace": {"id": 42, "name": "omit-nested"}, "created_at": "2026-10-01T12:30:00Z", "last_modified": "2026-10-02T12:30:00Z", "items": [{"url": "omit-private"}], "thumbnail_url": "omit-capability", "description": "omit-private"}
SCREEN = {"id": 14, "uuid": "71a9ef47-28d4-4e03-af9e-3056d328c3dd", "name": "opt-in-screen", "workspace": {"id": 42}, "state": {"online": True, "registered": False, "last_seen": "2026-10-01T12:30:00Z", "private": "omit-private"}, "configuration": {"player": {"password": "omit-private"}}, "reg_code": "omit-pairing", "last_ip_address": "omit-IP", "screenshot_url": "omit-capability", "takeover_content": {"name": "omit-content"}, "advanced": {"secret": "omit-private"}, "basic": {"tags": ["omit-private"]}}


def page(items, count=None, next=None):
    return {"count": len(items) if count is None else count, "results": deepcopy(items), "next": next, "previous": None}


def node(operation="list_workspaces", raw=KEY, **args):
    return NodeFactory.create_node(node_id="yodeck-fixture", node_type=NT, node_data={"config": {"operation": operation, **args}, "credentials": deepcopy(raw)}, sio=None, sid=None, user_id=USER)


@pytest.fixture(autouse=True)
def admission(monkeypatch):
    monkeypatch.setattr("utils.credential_approval.admit_node", AsyncMock(return_value=None))


@pytest.fixture
def transport(monkeypatch):
    calls, responses = [], []
    async def receive(request):
        assert request.url.host == "app.yodeck.com" and request.url.scheme == "https"
        assert request.method == "GET" and request.content == b"" and not request.url.username and not request.url.password
        assert KEY["token_value"] not in str(request.url)
        assert request.headers["Authorization"] == "Token fixture:" + KEY["token_value"]
        calls.append(request)
        value = responses.pop(0)
        if callable(value): value = value(request)
        return value if isinstance(value, httpx.Response) else httpx.Response(200, json=value)
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs == {"timeout": 30, "follow_redirects": False, "trust_env": False}
        async with httpx.AsyncClient(transport=httpx.MockTransport(receive)) as instance:
            yield instance
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls, responses


@pytest.mark.parametrize("args", [{"offset": "1"}, {"offset": True}, {"offset": -1}, {"offset": 1000001}, {"limit": 101}, {"limit": "20x"}, {"limit": 20.5}, {"include_names": "false"}, {"host": "https://evil.example.test"}, {"operation": "push"}, {"operation": "create_playlist"}])
def test_actual_factory_refuses_untyped_bounds_and_unimplemented_routes(transport, args):
    with pytest.raises(ValueError): node(args.get("operation", "list_workspaces"), **{k:v for k,v in args.items() if k != "operation"})
    assert transport[0] == []


@pytest.mark.parametrize("change", [{"token_value": 42}, {"token_value": "Bearer value"}, {"token_value": "value\r\nprivate"}, {"token_label": "label:secret"}, {"workspace_id": "001"}, {"workspace_id": True}])
def test_original_credential_malformed_fields_are_safely_rejected(change):
    with pytest.raises(ValueError) as error: native.credential({**KEY, **change})
    assert KEY["token_value"] not in str(error.value)


@pytest.mark.asyncio
async def test_actual_foreign_factory_and_preparsed_execute_zero_io(transport):
    with pytest.raises(ValueError):
        NodeFactory.create_node(node_id="foreign", node_type=NT, node_data={"config": {"operation": "list_workspaces"}, "credentials": {**KEY, "credential_type": "foreign"}, "credentialIds": {native.TYPE: CID}}, sio=None, sid=None)
    instance = node(); instance.node_data["credentials"]["credential_type"] = "foreign"
    with pytest.raises(ValueError): await instance.execute({})
    assert transport[0] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("items", [[], [WORKSPACE]])
async def test_actual_visible_form_connect_proves_selected_workspace_access_not_identity(transport, items):
    transport[1].extend([WORKSPACE, page(items)])
    verdict = await validate_for_connect(credential_type=native.TYPE, credential_data={key:value for key,value in KEY.items() if key != "credential_type"}, user_id=USER)
    assert verdict.ok and verdict.credential_data["credential_type"] == native.TYPE
    assert verdict.evidence.reachable is True and not verdict.evidence.account_label
    assert [r.url.path for r in transport[0]] == ["/api/v2/workspaces/42", "/api/v2/workspaces"]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,args,reply,path", [
    ("list_workspaces", {}, page([WORKSPACE]), "/workspaces"),
    ("get_workspace", {}, None, None),
    ("list_folders", {}, page([FOLDER]), "/folders"),
    ("get_folder", {"folder_id": "12"}, FOLDER, "/folders/12"),
    ("list_playlists", {}, page([PLAYLIST]), "/playlists"),
    ("get_playlist", {"playlist_id": "13"}, PLAYLIST, "/playlists/13"),
    ("list_screens", {}, page([SCREEN]), "/screens"),
])
async def test_actual_all_seven_routes_project_private_fields_and_exact_parents(transport, operation, args, reply, path):
    transport[1].append(WORKSPACE)
    if reply is not None: transport[1].append(reply)
    result = await node(operation, **args).execute({})
    assert "omit" not in repr(result) and "opt-in" not in repr(result)
    assert transport[0][0].url.path == "/api/v2/workspaces/42"
    if path is not None: assert transport[0][-1].url.path == "/api/v2" + path
    if operation == "list_screens": assert dict(transport[0][-1].url.params) == {"offset": "0", "limit": "20", "workspace": "42", "subset": "basic"}
    if operation == "list_playlists": assert "workspace" not in transport[0][-1].url.params


@pytest.mark.asyncio
async def test_dispatcher_keeps_real_count_next_marker_and_local_playlist_scope(transport):
    other = {**PLAYLIST, "id": 15, "workspace": {"id": 999}}
    transport[1].extend([WORKSPACE, page([other, PLAYLIST], count=50, next="https://evil.example.test/omit-capability")])
    result = await run_node_operation(node_type=NT, operation="list_playlists", arguments={"offset": 2, "limit": 20}, user_id=USER, credential_data=KEY)
    data = result["data"]
    assert [item["id"] for item in data["items"]] == [13] and data["catalog_page_count"] == 2
    assert data["provider_count"] == 50 and data["count_scope"] == "full_accessible_playlist_catalog"
    assert data["has_more"] and data["next_offset"] == 4 and "evil" not in repr(data)
    assert len(transport[0]) == 2


@pytest.mark.asyncio
async def test_explicit_folder_parent_read_precedes_filtered_child_page(transport):
    child = {**FOLDER, "id": 16, "parent_folder": {"id": 12, "name": "omit-parent"}}
    transport[1].extend([WORKSPACE, FOLDER, page([child])])
    result = await node("list_folders", parent_folder_id="12").execute({})
    assert result["data"]["items"][0]["parent_folder_id"] == 12
    assert [r.url.path for r in transport[0]] == ["/api/v2/workspaces/42", "/api/v2/folders/12", "/api/v2/folders"]
    assert dict(transport[0][-1].url.params)["parent_folder"] == "12"


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [{}, {"id": True}, {**WORKSPACE, "id": 43}, []])
async def test_wrong_workspace_witness_never_requests_catalog(transport, reply):
    transport[1].append(reply)
    with pytest.raises(native.OutcomeUnverified): await node("list_screens").execute({})
    assert len(transport[0]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [page([{**FOLDER, "workspace": {"id": 43}}]), page([{**FOLDER, "id": True}]), {**page([]), "count": "1"}, {**page([]), "next": {}}, {**page([FOLDER]), "next": "not-a-url"}, page([FOLDER, FOLDER])])
async def test_malformed_catalog_and_foreign_child_ancestry_never_returns(transport, reply):
    transport[1].extend([WORKSPACE, reply])
    with pytest.raises(native.OutcomeUnverified): await node("list_folders").execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 404, 429, 500, 302])
async def test_statuses_are_private_and_not_retried(transport, status):
    transport[1].append(httpx.Response(status, json={"message": "omit-private"}))
    with pytest.raises(native.ApiError) as error: await node().execute({})
    assert error.value.status_code == status and "omit" not in str(error.value) and len(transport[0]) == 1
    if status == 401: assert "authentication" in str(error.value)
    if status == 403: assert "forbidden" in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("body,content_type", [(b'{"id":42,"id":43}', "application/json"), (b'{"id":NaN}', "application/json"), (b'omit-private', "text/plain")])
async def test_non_json_duplicate_and_nonfinite_bodies_are_unverified(transport, body, content_type):
    transport[1].append(httpx.Response(200, content=body, headers={"content-type": content_type}))
    with pytest.raises(native.OutcomeUnverified) as error: await node().execute({})
    assert "omit" not in str(error.value)


@pytest.mark.asyncio
async def test_names_opt_in_does_not_expand_private_parent_or_player_output(transport):
    transport[1].extend([WORKSPACE, page([SCREEN])])
    result = await node("list_screens", include_names=True).execute({})
    item = result["data"]["items"][0]
    assert item["name"] == SCREEN["name"] and item["workspace_id"] == 42
    assert "omit" not in repr(result) and set(item) == {"id", "uuid", "workspace_id", "online", "registered", "last_seen", "name", "resource_type"}



@pytest.mark.asyncio
async def test_saved_credentials_use_staging_resolver_and_reject_changed_token(monkeypatch):
    resolver = AsyncMock(return_value=deepcopy(KEY))
    monkeypatch.setattr(native, "resolve_credential_with_owner_fallback", resolver)
    auth = await native.Authority.create(KEY, pool=object(), user_id=USER, credential_id=CID, organization_id=None)
    await auth.require_current()
    assert resolver.await_count == 2
    resolver.return_value = {**KEY, "token_value": "changed-token"}
    with pytest.raises(ValueError, match="unavailable"):
        await auth.require_current()
