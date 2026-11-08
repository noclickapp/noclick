"""Exercise AgencyZoom's public action and manual-token contracts without a login.

Requests run through the real node and HTTP serialization. Synthetic responses
cover acknowledgement, pagination, error and connection-evidence behavior.
"""
import json

import httpx
import pytest
from pydantic import ValidationError

from nodes import agencyzoom_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-agencyzoom-token-42"
LEAD = {"firstname": "Pat", "email": "pat@example.com", "country": "US", "leadSourceId": 3,
        "assignTo": 4, "pipelineId": 5, "stageId": 6}
CUSTOMER = {"firstname": "Pat", "email": "pat@example.com", "agentId": 4}
TASK = {"title": "Call Pat", "dueDatetime": "2026-12-12 09:00:00", "assigneeId": 4, "type": "call"}
PAGE = {"page": 0, "pageSize": 20}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(
        node_id="agencyzoom-test", node_type="automation-agencyzoom",
        node_data={"config": config, "credentials": credential or {
            "credential_type": "agencyzoom_bearer_token", "access_token": TOKEN}})


def transport(monkeypatch, body=None, *, status=200, raw=None):
    requests = []

    def reply(request):
        requests.append(request)
        if raw is not None:
            return httpx.Response(status, content=raw)
        return httpx.Response(status, json=body)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


# Explicit expected API paths and bodies, independent of the node's route table.
CASES = [
    ("search_leads", {}, "POST", "/v1/api/leads/list", PAGE),
    ("create_lead", LEAD, "POST", "/v1/api/leads/create", LEAD),
    ("get_lead", {"lead_id": 12}, "GET", "/v1/api/leads/12", None),
    ("list_lead_notes", {"lead_id": 12}, "GET", "/v1/api/leads/12/notes", None),
    ("add_lead_note", {"lead_id": 12, "note": "Spoke to Pat\nFollow up"}, "POST", "/v1/api/leads/12/notes", {"note": "Spoke to Pat\nFollow up"}),
    ("list_lead_tasks", {"lead_id": 12}, "GET", "/v1/api/leads/12/tasks", None),
    ("search_customers", {}, "POST", "/v1/api/customers", PAGE),
    ("create_customer", CUSTOMER, "POST", "/v1/api/customers/create", CUSTOMER),
    ("get_customer", {"customer_id": 18}, "GET", "/v1/api/customers/18", None),
    ("add_customer_note", {"customer_id": 18, "note": "Renewal discussion"}, "POST", "/v1/api/customers/18/notes", {"note": "Renewal discussion"}),
    ("list_customer_tasks", {"customer_id": 18}, "GET", "/v1/api/customers/18/tasks", None),
    ("list_customer_policies", {"customer_id": 18}, "GET", "/v1/api/customers/18/policies", None),
    ("list_customer_ams_policies", {"customer_id": 18}, "GET", "/v1/api/customers/18/ams-policies", None),
    ("search_tasks", {}, "POST", "/v1/api/tasks/list", PAGE),
    ("create_task", TASK, "POST", "/v1/api/tasks", TASK),
    ("get_task", {"task_id": 27}, "GET", "/v1/api/tasks/27", None),
    ("update_task", {"task_id": 27, **TASK, "status": 0, "timeSpecific": False}, "PUT", "/v1/api/tasks/27", {**TASK, "status": 0, "timeSpecific": False}),
    ("complete_task", {"task_id": 27}, "PUT", "/v1/api/tasks/27/completed", None),
    ("reopen_task", {"task_id": 27, "comments": "Follow up again"}, "PUT", "/v1/api/tasks/27/reopened", {"comments": "Follow up again"}),
    ("delete_task", {"task_id": 27}, "DELETE", "/v1/api/tasks/27", None),
    ("list_employees", {}, "GET", "/v1/api/employees", None),
    ("list_pipelines", {"type": "service"}, "GET", "/v1/api/pipelines-and-stages", None),
    ("list_lead_sources", {}, "GET", "/v1/api/lead-sources", None),
    ("list_tags", {}, "GET", "/v1/api/tags", None),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,body", CASES, ids=[c[0] for c in CASES])
async def test_action_serializes_exact_contract_request(monkeypatch, operation, config, method, path, body):
    response = {"result": True, "id": 27, "message": "Success"}
    requests = transport(monkeypatch, response)
    out = await node({"operation": operation, **config}).execute({})
    assert out == {"status": "success", "operation": operation, "data": response, "http_status": 200}
    assert len(requests) == 1
    req = requests[0]
    assert req.method == method
    assert str(req.url).split("?")[0] == "https://api.agencyzoom.com" + path
    assert req.headers["authorization"] == "Bearer " + TOKEN
    assert json.loads(req.content) == body if body is not None else req.content == b""
    assert dict(req.url.params) == ({"type": "service"} if operation == "list_pipelines" else {})
    assert TOKEN not in str(out)


@pytest.mark.asyncio
async def test_search_keeps_server_pagination_and_empty_page(monkeypatch):
    response = {"leads": [], "totalCount": 101, "page": 4, "pageSize": 25}
    requests = transport(monkeypatch, response)
    out = await node({"operation": "search_leads", "page": 4, "pageSize": 25,
                      "customerEmail": "pat+home@example.com", "status": 0}).execute({})
    assert out["data"] == response
    assert json.loads(requests[0].content) == {"page": 4, "pageSize": 25, "customerEmail": "pat+home@example.com", "status": 0}
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_connection_evidence_returns_recognizable_account_employees(monkeypatch):
    from nodes.core.connection_evidence import _rows_from_operation, _label_from
    employees = [{"id": 4, "firstname": "Pat", "lastname": "Agent", "email": "pat@example.com"}]
    transport(monkeypatch, employees)
    evidence = native.AgencyZoomNode.connection_evidence
    out = await node({"operation": evidence.operation}).execute({})
    rows = _rows_from_operation(out)
    assert rows == employees
    assert _label_from(rows[0], evidence.label_keys) == "pat@example.com"
    assert evidence.proves == "account"


@pytest.mark.asyncio
@pytest.mark.parametrize("body,status", [
    ({"error": "Token expired"}, 401),
    ({"error": "Not authorized"}, 403),
    ({"error": "Slow down"}, 429),
    ({"result": False, "message": "Could not save task"}, 200),
    ({"fieldErrors": [{"field": "title", "message": "Required"}]}, 200),
    ({"error": "Invalid token " + TOKEN}, 401),
])
async def test_rejection_and_negative_ack_never_succeed_or_retry(monkeypatch, body, status):
    requests = transport(monkeypatch, body, status=status)
    out = await node({"operation": "create_task", **TASK}).execute({})
    assert out["status"] == "error"
    assert out["http_status"] == status
    assert TOKEN not in str(out)
    assert len(requests) == 1
    if body.get("error") and TOKEN not in body["error"]:
        assert out["error"] == body["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [b"<html>Login</html>", b'"unexpected"', b"null"])
async def test_non_json_or_scalar_response_is_failure(monkeypatch, raw):
    requests = transport(monkeypatch, raw=raw)
    assert (await node({"operation": "list_employees"}).execute({}))["status"] == "error"
    assert len(requests) == 1


@pytest.mark.parametrize("config", [
    {"operation": "get_lead", "lead_id": "../auth/login"},
    {"operation": "get_customer", "customer_id": 0},
    {"operation": "create_lead", **{k: v for k, v in LEAD.items() if k != "stageId"}},
    {"operation": "search_customers", "pageSize": 101},
    {"operation": "search_tasks", "pageSize": 201},
    {"operation": "update_task", "task_id": 27},
    {"operation": "list_employees", "url": "https://example.com"},
])
def test_invalid_configuration_fails_before_request(config):
    with pytest.raises(ValidationError):
        native.AgencyZoomConfig.model_validate({"config": config})


@pytest.mark.parametrize("token", ["Bearer abc", "abc\ndef", "https://example.com/token"])
def test_manual_token_rejects_headers_and_urls(token):
    with pytest.raises(ValidationError):
        native.AgencyZoomBearerToken(access_token=token)


@pytest.mark.asyncio
async def test_reopen_sends_required_body_even_without_optional_comments(monkeypatch):
    requests = transport(monkeypatch, {"result": True})
    out = await node({"operation": "reopen_task", "task_id": 27}).execute({})
    assert out["status"] == "success"
    assert json.loads(requests[0].content) == {}
    assert requests[0].headers["content-type"] == "application/json"
