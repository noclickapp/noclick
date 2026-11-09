"""Typebot token, exact request bodies, pagination and failure regressions.

Offline synthetic fixtures; conformance separately checks the provider OpenAPI.
"""
import json

import httpx
import pytest
from pydantic import ValidationError

from nodes import typebot_node as native
from nodes.core.registry import NodeFactory

TOKEN = "typebot-synthetic-token-42"
ORIGINAL_CLIENT = httpx.AsyncClient


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="typebot-fixture", node_type="automation-typebot",
        node_data={"config": config, "credentials": {"credential_type": "typebot_api_token", "api_token": TOKEN}})


def transport(monkeypatch, response):
    requests = []
    real_client = ORIGINAL_CLIENT

    def reply(request):
        requests.append(request)
        return response(request) if callable(response) else httpx.Response(200, json=response)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return real_client(transport=httpx.MockTransport(reply), **kwargs)

    monkeypatch.setattr(native.httpx, "AsyncClient", client)
    return requests


@pytest.mark.asyncio
async def test_workspaces_connection_evidence_and_manual_token(monkeypatch):
    requests = transport(monkeypatch, {"workspaces": [{"id": "workspace1", "name": "Customer support"}]})
    result = await node({"operation": "list_workspaces"}).execute({})
    assert result == {"status": "success", "workspaces": [{"id": "workspace1", "name": "Customer support"}]}
    assert len(requests) == 1
    assert str(requests[0].url) == "https://app.typebot.com/api/v1/workspaces"
    assert requests[0].headers["Authorization"] == "Bearer " + TOKEN
    assert native.TypebotNode.connection_evidence.operation == "list_workspaces"
    credential = native.TypebotAPITokenCredential(api_token="  " + TOKEN + "  ")
    assert credential.api_token == TOKEN and credential.credential_type == "typebot_api_token"
    assert TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,body,response", [
    ({"operation": "create_workspace", "name": "Sales", "icon": "🚀"}, "POST", "/v1/workspaces", {"name": "Sales", "icon": "🚀"}, {"workspace": {"id": "w1"}}),
    ({"operation": "update_workspace", "workspace_id": "w1", "name": "New name"}, "PATCH", "/v1/workspaces/w1", {"name": "New name"}, {"workspace": {"id": "w1"}}),
    ({"operation": "create_typebot", "workspace_id": "w1", "name": "Lead form", "folder_id": "f1"}, "POST", "/v1/typebots", {"workspaceId": "w1", "typebot": {"name": "Lead form", "folderId": "f1"}}, {"typebot": {"id": "b1"}}),
    ({"operation": "update_typebot", "typebot_id": "b1", "name": "New name"}, "PATCH", "/v1/typebots/b1", {"typebot": {"name": "New name"}}, {"typebot": {"id": "b1"}}),
    ({"operation": "publish_typebot", "typebot_id": "b1"}, "POST", "/v1/typebots/b1/publish", None, {"message": "success", "warnings": []}),
    ({"operation": "unpublish_typebot", "typebot_id": "b1"}, "POST", "/v1/typebots/b1/unpublish", None, {"message": "success"}),
    ({"operation": "delete_typebot", "typebot_id": "b1"}, "DELETE", "/v1/typebots/b1", None, {"message": "success"}),
    ({"operation": "create_folder", "workspace_id": "w1", "name": "Leads", "parent_folder_id": "f0"}, "POST", "/v1/folders", {"workspaceId": "w1", "folderName": "Leads", "parentFolderId": "f0"}, {"folder": {"id": "f1"}}),
    ({"operation": "update_folder", "workspace_id": "w1", "folder_id": "f1", "name": "Qualified"}, "PATCH", "/v1/folders/f1", {"workspaceId": "w1", "folder": {"name": "Qualified"}}, {"folder": {"id": "f1"}}),
    ({"operation": "delete_folder", "workspace_id": "w1", "folder_id": "f1"}, "DELETE", "/v1/folders/f1", {"workspaceId": "w1"}, {"folder": {"id": "f1"}}),
])
async def test_mutations_send_exact_documented_body(monkeypatch, config, method, path, body, response):
    requests = transport(monkeypatch, response)
    result = await node(config).execute({})
    assert result["status"] == "success" and len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == "/api" + path
    assert (json.loads(request.content) if request.content else None) == body


@pytest.mark.asyncio
async def test_numeric_result_cursor_is_forwarded_without_truncating_page(monkeypatch):
    requests = transport(monkeypatch, {"results": [{"id": "r1", "variables": []}], "nextCursor": 73})
    result = await node({"operation": "list_results", "typebot_id": "b1", "limit": 10, "cursor": 42,
        "time_filter": "allTime", "time_zone": "Europe/Paris"}).execute({})
    assert dict(requests[0].url.params) == {"limit": "10", "cursor": "42", "timeFilter": "allTime", "timeZone": "Europe/Paris"}
    assert result["nextCursor"] == 73 and len(result["results"]) == 1 and len(requests) == 1


@pytest.mark.asyncio
async def test_folder_query_and_nullable_unpublished_bot(monkeypatch):
    requests = transport(monkeypatch, {"folders": []})
    assert (await node({"operation": "list_folders", "workspace_id": "w1", "parent_folder_id": "f1"}).execute({}))["folders"] == []
    assert dict(requests[0].url.params) == {"workspaceId": "w1", "parentFolderId": "f1"}
    transport(monkeypatch, {"publishedTypebot": None})
    assert (await node({"operation": "get_published_typebot", "typebot_id": "b1"}).execute({}))["publishedTypebot"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_failed_requests_never_retry_or_report_success(monkeypatch, status):
    requests = transport(monkeypatch, lambda r: httpx.Response(status, text="Provider rejection " + TOKEN))
    result = await node({"operation": "publish_typebot", "typebot_id": "b1"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status and len(requests) == 1
    assert TOKEN not in str(result) and "Provider rejection" in result["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(200, text="<html>Sign in</html>"), httpx.Response(200, json={"wrong": []}), httpx.Response(200, json={"workspaces": "wrong"})])
async def test_bad_response_is_not_connection_evidence(monkeypatch, response):
    transport(monkeypatch, lambda r: response)
    assert (await node({"operation": "list_workspaces"}).execute({}))["status"] == "error"


@pytest.mark.parametrize("token", ["Bearer secret", "https://example.com/key", "<token>", ""])
def test_reject_invalid_tokens(token):
    with pytest.raises((ValueError, ValidationError)):
        native.TypebotAPITokenCredential(api_token=token)


@pytest.mark.parametrize("config", [
    {"operation": "get_typebot", "typebot_id": "../other"},
    {"operation": "get_typebot", "typebot_id": "bot?query=1"},
    {"operation": "list_results", "typebot_id": "b1", "limit": 501},
    {"operation": "list_results", "typebot_id": "b1", "cursor": "opaque"},
    {"operation": "list_results", "typebot_id": "b1", "time_filter": "yesterday"},
])
def test_reject_bad_config_before_network(config):
    with pytest.raises(ValueError):
        node(config)
