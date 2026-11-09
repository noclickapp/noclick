"""Native factory regressions for DealMachine's single-request API contract."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import dealmachine_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-dealmachine-token"
CASES = json.loads((Path(__file__).parent / "fixtures/dealmachine/requests.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="dealmachine-test", node_type="automation-dealmachine",
        node_data={"config": config, "credentials": {"credential_type": "dealmachine_api_key", "api_key": TOKEN}})


def transport(monkeypatch, response):
    requests = []
    def respond(request):
        requests.append(request)
        return response(request) if callable(response) else response
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CASES)
async def test_dealmachine_exact_single_request_and_provider_envelope(monkeypatch, operation):
    config, method, path, expected_body = CASES[operation]
    body = {"data": {"id": "owned", "name": "My workspace"}, "pagination": {"page": 2, "has_more": True}, "credits": {"used": 1}}
    if operation == "get_account":
        body = {"data": {"organization": {"id": 1, "name": "My workspace", "slug": "owned", "createdAt": "2026-03-01T09:00:00Z"}, "user": {"id": 5, "authType": "api_key"}, "plan": {"name": "API"}}}
    requests = transport(monkeypatch, httpx.Response(201 if operation in {"create_task", "create_tag", "add_prospect_note"} else 200, json=body))
    result = await node({"operation": operation, **config}).execute({})
    assert result == {**body, "status": "success"}
    assert len(requests) == 1
    req = requests[0]
    assert req.method == method and req.url.path == path
    assert req.url.host == "api.v2.dealmachine.com"
    assert req.headers["Authorization"] == "Bearer " + TOKEN
    if expected_body is not None:
        assert json.loads(req.content) == expected_body
    else:
        assert not req.content
    if operation == "archive_prospect":
        assert dict(req.url.params) == {"cascade": "false"}
    if operation == "list_tasks":
        assert dict(req.url.params) == {"page": "2", "per_page": "10", "status": "open"}
    if operation == "get_property":
        assert dict(req.url.params) == {"enrich": "false", "contact_audience": "none"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 400, 401, 402, 403, 404, 429, 500])
async def test_dealmachine_errors_are_not_successful_and_no_retry(monkeypatch, status):
    requests = transport(monkeypatch, httpx.Response(status, json={"error": {"code": "rejected", "message": "Provider says rejected " + TOKEN}}, headers={"Location": "https://example.test"}))
    result = await node({"operation": "get_account"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert "Provider says rejected" in result["error"] and TOKEN not in str(result)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, [], {"data": None}, {"data": "bad"}, {"data": {}}, {"data": {"organization": {"id": 1, "name": ""}}}, {"error": {"message": "Bad key"}}])
async def test_dealmachine_invalid_or_error_envelopes_fail(monkeypatch, body):
    transport(monkeypatch, httpx.Response(200, json=body))
    assert (await node({"operation": "get_account"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_dealmachine_empty_lists_and_search_session_preserved(monkeypatch):
    body = {"data": [], "pagination": {"has_next_page": False}, "result_session_id": "owned-session", "credits": {"used": 0}}
    requests = transport(monkeypatch, httpx.Response(200, json=body))
    result = await node({"operation": "search_properties", "zip_code": "02108", "page": 2, "result_session_id": "owned-session"}).execute({})
    assert result == {**body, "status": "success"}
    assert json.loads(requests[0].content)["result_session_id"] == "owned-session"


@pytest.mark.asyncio
async def test_dealmachine_published_task_response_preserves_nullable_fields(monkeypatch):
    # Exact provider example; its nulls are documented even though the published
    # OpenAPI 3.1 schema uses the older nullable keyword beside type: string.
    witness = json.loads((Path(__file__).parent / "fixtures/dealmachine/task_completed.json").read_text())
    requests = transport(monkeypatch, httpx.Response(200, json=witness["body"]))
    result = await node({"operation": "update_task", "task_id": "task_001", "is_completed": True}).execute({})
    assert result == {**witness["body"], "status": "success"}
    assert result["data"]["person_id"] is None and result["data"]["assigned_to_agent_id"] is None
    assert json.loads(requests[0].content) == {"is_completed": True}


@pytest.mark.asyncio
async def test_dealmachine_transport_and_non_json_fail(monkeypatch):
    transport(monkeypatch, httpx.Response(200, text="<html>wrong response</html>"))
    assert (await node({"operation": "get_account"}).execute({}))["status"] == "error"
    def timeout(request):
        raise httpx.ReadTimeout("timeout", request=request)
    requests = transport(monkeypatch, timeout)
    result = await node({"operation": "create_task", "title": "Inspect"}).execute({})
    assert result["status"] == "error" and "inspect writes" in result["error"] and len(requests) == 1


@pytest.mark.parametrize("config", [
    {"operation": "get_property", "property_id": "../account"},
    {"operation": "search_properties", "zip_code": "bad"},
    {"operation": "list_tasks", "per_page": 101},
    {"operation": "add_list_items", "list_id": "owned", "ids": ["prop_123"]},
    {"operation": "update_task", "task_id": "owned"},
    {"operation": "update_task", "task_id": "owned", "title": "new", "clear_fields": ["title"]},
    {"operation": "update_task", "task_id": "owned", "description": "new", "clear_fields": ["description"]},
    {"operation": "create_task", "title": ""},
    {"operation": "add_prospects", "record_ids": []},
])
def test_dealmachine_invalid_configs_refused(config):
    with pytest.raises((ValueError, ValidationError)):
        native.DealMachineNode.parse_config({"config": config})


def test_dealmachine_manual_credential_default_and_read_only_evidence():
    credential = native.DealMachineAPIKeyCredential(api_key=TOKEN)
    assert credential.credential_type == "dealmachine_api_key"
    assert native.DealMachineNode.connection_evidence.identity_operation == "get_account"
    assert native.ROUTES["get_account"] == ("GET", "/v1/account", False)
    assert len(CASES) == len(native.ROUTES) == 25
