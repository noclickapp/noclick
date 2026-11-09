"""Exercise Reclaim AI through the real node factory with a fake HTTP transport.

The fixtures are synthetic contract-shaped responses, not live account evidence.
These tests pin route selection, partial writes, pagination and connection identity.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import reclaim_ai_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory

TOKEN = "synthetic-reclaim-key-42"
FIXTURES = Path(__file__).parent / "fixtures" / "reclaim-ai"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="reclaim-fixture", node_type="automation-reclaim-ai",
        node_data={"config": config, "credentials": {"credential_type": "reclaim_ai_api_key", "api_key": TOKEN}})


def transport(monkeypatch, body=None, status=200):
    requests = []

    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=body)

    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [
    ({"operation": "get_current_user"}, "GET", "/api/users/current", {}, None, {"id": "account-1", "name": "Test account", "email": "test@example.test", "intercomHash": "private"}),
    ({"operation": "list_tasks"}, "GET", "/api/reclaim-tasks/page", {"count": "20"}, None, {"items": [], "last": "cursor-2", "hasNextPage": True}),
    ({"operation": "get_task", "task_id": 42}, "GET", "/api/reclaim-tasks/42", {}, None, {"id": "42", "title": "Test"}),
    ({"operation": "create_task", "title": "Test", "estimateMinutes": 30, "dueDate": "2026-11-20"}, "POST", "/api/reclaim-tasks", {}, {"title": "Test", "estimateMinutes": 30, "dueDate": "2026-11-20"}, {"id": "42", "title": "Test"}),
    ({"operation": "update_task", "task_id": 42, "completed": True}, "PATCH", "/api/reclaim-tasks/42", {}, {"completed": True}, {"id": "42", "completed": True}),
    ({"operation": "delete_task", "task_id": 42}, "DELETE", "/api/reclaim-tasks/42", {}, None, None),
    ({"operation": "get_primary_calendar"}, "GET", "/api/calendars/primary", {}, None, {"id": 3}),
    ({"operation": "list_personal_calendars"}, "GET", "/api/calendars/personal", {}, None, [{"id": 3}]),
    ({"operation": "list_habits"}, "GET", "/api/smart-habits", {}, None, [{"lineageId": 7}]),
    ({"operation": "get_habit", "lineage_id": 7}, "GET", "/api/smart-habits/7", {}, None, {"lineageId": 7}),
    ({"operation": "update_habit", "lineage_id": 7, "title": "Lunch", "durationMinMins": 30, "sendUpdates": False}, "PATCH", "/api/smart-habits/7", {"sendUpdates": "false"}, {"title": "Lunch", "durationMinMins": 30}, {"lineageId": 7}),
    ({"operation": "delete_habit", "lineage_id": 7, "restoreIfAvailable": False}, "DELETE", "/api/smart-habits/7", {"restoreIfAvailable": "false"}, None, {}),
    ({"operation": "disable_habit", "lineage_id": 7}, "DELETE", "/api/smart-habits/7/disable", {}, None, {}),
    ({"operation": "enable_habit", "lineage_id": 7}, "POST", "/api/smart-habits/7/enable", {}, None, {}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,query,body,response", CASES)
async def test_reclaim_ai_operation_contract(monkeypatch, config, method, path, query, body, response):
    requests = transport(monkeypatch, response)
    result = await node(config).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.host == "api.app.reclaim.ai"
    assert request.url.path == path and dict(request.url.params) == query
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert (json.loads(request.content) if request.content else None) == body
    assert TOKEN not in str(result)
    if config["operation"] == "get_current_user":
        assert "intercomHash" not in result["data"]
    elif config["operation"] == "list_tasks":
        assert result["data"]["last"] == "cursor-2" and result["data"]["hasNextPage"]


@pytest.mark.asyncio
async def test_reclaim_ai_cursor_and_filters(monkeypatch):
    page = json.loads((FIXTURES / "task_page.json").read_text())
    requests = transport(monkeypatch, page)
    result = await node({"operation": "list_tasks", "after": "opaque/+cursor", "count": 10,
        "completed": False, "dueBefore": "2026-11-20", "sort": "DUE_DATE", "query": "Report & plan"}).execute({})
    assert result["data"] == page
    assert len(requests) == 1
    assert dict(requests[0].url.params) == {"after": "opaque/+cursor", "count": "10", "completed": "false",
        "dueBefore": "2026-11-20", "sort": "DUE_DATE", "query": "Report & plan"}


@pytest.mark.asyncio
async def test_reclaim_ai_omitted_fields_do_not_overwrite_task(monkeypatch):
    requests = transport(monkeypatch, {"id": "42", "completed": False})
    await node({"operation": "update_task", "task_id": 42, "completed": False, "estimateMinutes": 0}).execute({})
    assert json.loads(requests[0].content) == {"completed": False, "estimateMinutes": 0}


@pytest.mark.asyncio
async def test_reclaim_ai_null_query_never_leaks_into_habit_body(monkeypatch):
    requests = transport(monkeypatch, {"lineageId": 7})
    await node({"operation": "update_habit", "lineage_id": 7, "description": "Updated", "sendUpdates": None}).execute({})
    assert not requests[0].url.params
    assert json.loads(requests[0].content) == {"description": "Updated"}


@pytest.mark.asyncio
@pytest.mark.parametrize("config", [{"operation": "update_task", "task_id": 42},
    {"operation": "update_habit", "lineage_id": 7, "sendUpdates": True}])
async def test_reclaim_ai_empty_update_never_sends(monkeypatch, config):
    requests = transport(monkeypatch, {})
    with pytest.raises(ValueError, match="at least one field"):
        await node(config).execute({})
    assert not requests


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_reclaim_ai_provider_errors_preserve_words_and_redact_key(monkeypatch, status):
    requests = transport(monkeypatch, {"message": "Key was rejected " + TOKEN}, status)
    result = await node({"operation": "get_current_user"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert "Key was rejected" in result["error"] and TOKEN not in result["error"]
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_reclaim_ai_error_envelope_is_not_evidence(monkeypatch):
    transport(monkeypatch, {"error": "Access denied"})
    assert (await node({"operation": "get_current_user"}).execute({}))["status"] == "error"
    transport(monkeypatch, {})
    with pytest.raises(ValueError, match="account ID"):
        await node({"operation": "get_current_user"}).execute({})


@pytest.mark.parametrize("key", ["https://example.test/key", "Bearer secret-key", "secret\nkey", "<token>"])
def test_reclaim_ai_rejects_bad_secret(key):
    with pytest.raises(ValidationError):
        native.ReclaimAIAPIKeyCredential(api_key=key)


def test_reclaim_ai_registration_manual_credential_and_evidence():
    assert NODE_REGISTRY["automation-reclaim-ai"] is native.ReclaimAINode
    credential = native.ReclaimAIAPIKeyCredential(api_key="  " + TOKEN + "  ")
    assert credential.api_key == TOKEN and credential.credential_type == "reclaim_ai_api_key"
    assert native.ReclaimAINode.connection_evidence.identity_operation == "get_current_user"
    assert len(native.ROUTES) == 14


@pytest.mark.parametrize("config", [{"operation": "get_task", "task_id": "../users/current"},
    {"operation": "get_habit", "lineage_id": -1}, {"operation": "list_tasks", "count": 0},
    {"operation": "create_task", "title": ""}, {"operation": "create_task", "title": "Test", "url": "https://example.test"}])
def test_reclaim_ai_invalid_inputs(config):
    with pytest.raises((ValueError, ValidationError)):
        native.ReclaimAINode.parse_config({"config": config, "credentials": {"api_key": TOKEN}})
