"""Rocketlane transport regressions; synthetic credentials and offline provider responses."""
import json

import httpx
import pytest

from nodes import rocketlane_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory

TOKEN = "synthetic-rocketlane-key-42"
CREDENTIAL = {"credential_type": native.FAMILY, "api_key": TOKEN}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id="rocketlane-test", node_type=native.NODE_TYPE,
        node_data={"config": config, "credentials": credentials or CREDENTIAL})


def transport(monkeypatch, handler):
    calls = []
    def respond(request):
        calls.append(request)
        return handler(request)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


def page(rows=None, **pagination):
    return {"data": rows or [], "pagination": {"hasMore": False, **pagination}}


CASES = [
    ({"operation": "list_projects", "name_contains": "Acme"}, "GET", "/projects", {"pageSize": "100", "projectName.cn": "Acme"}, None),
    ({"operation": "get_project", "project_id": 201}, "GET", "/projects/201", {}, None),
    ({"operation": "create_project", "project_name": "Acme onboarding", "owner_id": 201, "customer_name": "Acme Inc"}, "POST", "/projects", {}, {"projectName": "Acme onboarding", "owner": {"userId": 201}, "customer": {"companyName": "Acme Inc"}}),
    ({"operation": "update_project", "project_id": 201, "status_value": 2}, "PUT", "/projects/201", {}, {"status": {"value": 2}}),
    ({"operation": "list_tasks", "project_id": 201}, "GET", "/tasks", {"pageSize": "100", "projectId.eq": "201"}, None),
    ({"operation": "get_task", "task_id": 202}, "GET", "/tasks/202", {}, None),
    ({"operation": "create_task", "task_name": "Kick off", "project_id": 201}, "POST", "/tasks", {}, {"taskName": "Kick off", "project": {"projectId": 201}}),
    ({"operation": "update_task", "task_id": 202, "progress": 0, "at_risk": False, "task_description": "<p>Kick off</p>"}, "PUT", "/tasks/202", {}, {"progress": 0, "atRisk": False, "taskDescription": "<p>Kick off</p>"}),
    ({"operation": "list_companies"}, "GET", "/companies", {"pageSize": "100"}, None),
    ({"operation": "get_company", "company_id": 203}, "GET", "/companies/203", {}, None),
    ({"operation": "create_company", "company_name": "Acme Inc", "account_owner_id": 201}, "POST", "/companies", {}, {"companyName": "Acme Inc", "accountOwner": {"userId": 201}}),
    ({"operation": "update_company", "company_id": 203, "description": "Updated"}, "PUT", "/companies/203", {}, {"description": "Updated"}),
    ({"operation": "list_phases", "project_id": 201}, "GET", "/phases", {"pageSize": "100", "projectId": "201"}, None),
    ({"operation": "get_phase", "phase_id": 204}, "GET", "/phases/204", {}, None),
    ({"operation": "create_phase", "project_id": 201, "phase_name": "Kick off", "start_date": "2023-03-28", "due_date": "2023-03-28"}, "POST", "/phases", {}, {"project": {"projectId": 201}, "phaseName": "Kick off", "startDate": "2023-03-28", "dueDate": "2023-03-28"}),
    ({"operation": "update_phase", "phase_id": 204, "private": False}, "PUT", "/phases/204", {}, {"private": False}),
    ({"operation": "list_users"}, "GET", "/users", {"pageSize": "100"}, None),
    ({"operation": "get_user", "user_id": 205}, "GET", "/users/205", {}, None),
    ({"operation": "list_time_entries", "project_id": 201}, "GET", "/time-entries", {"pageSize": "100", "projectId.eq": "201"}, None),
    ({"operation": "get_time_entry", "time_entry_id": 206}, "GET", "/time-entries/206", {}, None),
    ({"operation": "create_time_entry", "date": "2023-03-28", "minutes": 250, "project_id": 201, "billable": False}, "POST", "/time-entries", {}, {"date": "2023-03-28", "minutes": 250, "project": {"projectId": 201}, "billable": False}),
    ({"operation": "delete_time_entry", "time_entry_id": 206}, "DELETE", "/time-entries/206", {}, None),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,query,body", CASES, ids=[case[0]["operation"] for case in CASES])
async def test_all_operations_send_exact_contract_request(monkeypatch, config, method, path, query, body):
    def respond(request):
        if method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(201 if method == "POST" else 200,
            json=page() if config["operation"].startswith("list_") else {"projectId": 201, "taskId": 202})
    calls = transport(monkeypatch, respond)
    result = await node(config).execute({})
    assert result["status"] == "success"
    assert TOKEN not in str(result)
    assert len(calls) == 1
    request = calls[0]
    assert request.method == method
    assert str(request.url.copy_with(query=None)) == native.BASE + path
    assert dict(request.url.params) == query
    assert request.headers["api-key"] == TOKEN
    assert (json.loads(request.content) if request.content else None) == body
    assert NODE_REGISTRY[native.NODE_TYPE] is native.RocketlaneNode


@pytest.mark.asyncio
async def test_token_pagination_and_project_evidence_share_loader(monkeypatch):
    calls = transport(monkeypatch, lambda request: httpx.Response(200, json=page(
        [{"projectId": 201, "projectName": "Acme onboarding"}], hasMore=True,
        nextPageToken="next-token", nextPage="https://attacker.invalid/steal")))
    result = await node({"operation": "list_projects", "page_token": "old-token"}).execute({})
    assert result["next_page_token"] == "next-token" and result["has_more"]
    options = await native.RocketlaneNode.load_field_options("project_id", CREDENTIAL, page_token="old-token")
    assert options == {"options": [{"value": "201", "label": "Acme onboarding"}], "next_page_token": "next-token"}
    assert all(r.url.host == "api.rocketlane.com" for r in calls)
    assert all(r.url.params["pageToken"] == "old-token" for r in calls)
    assert native.RocketlaneNode.connection_evidence.field == "project_id"


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"data": []}, {"data": [], "pagination": {"hasMore": True}}, {"error": "bad"}])
async def test_malformed_success_is_not_connection_evidence(monkeypatch, payload):
    transport(monkeypatch, lambda request: httpx.Response(200, json=payload))
    result = await node({"operation": "list_projects"}).execute({})
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_rejection_is_verbatim_and_secret_is_redacted(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(401, json={"message": "Invalid API key " + TOKEN}))
    result = await node({"operation": "list_projects"}).execute({})
    assert result["http_status"] == 401 and result["error"] == "Invalid API key [redacted]"


@pytest.mark.asyncio
async def test_write_timeout_is_not_retried(monkeypatch):
    def fail(request):
        raise httpx.ReadTimeout("secret " + TOKEN, request=request)
    calls = transport(monkeypatch, fail)
    result = await node({"operation": "update_task", "task_id": 201, "progress": 50}).execute({})
    assert len(calls) == 1 and result["write_outcome"] == "unverified"
    assert result["status"] == "error" and TOKEN not in str(result)


@pytest.mark.parametrize("config", [
    {"operation": "list_phases"},
    {"operation": "update_project", "project_id": 201},
    {"operation": "create_phase", "phase_name": "Kick off", "project_id": 1, "start_date": "2023-03-29", "due_date": "2023-03-28"},
    {"operation": "get_project", "project_id": "../../users"},
    {"operation": "create_time_entry", "date": "2023-03-28", "minutes": 1441, "project_id": 1},
    {"operation": "update_task", "task_id": 1, "progress": 101},
    {"operation": "create_project", "project_name": "Acme"},
])
def test_invalid_inputs_are_rejected(config):
    assert not native.RocketlaneNode.validate_config({"config": config})["valid"]


def test_reviewed_cases_cover_every_operation():
    assert {case[0]["operation"] for case in CASES} == set(native.OPERATIONS)


def test_editor_picker_metadata_is_not_sent_to_provider():
    parsed = native.RocketlaneNode.parse_config({"config": {"operation": "get_project", "project_id": 201,
        "project_id__label": "Acme onboarding", "credentialIds": {native.FAMILY: "saved-id"}}, "credentials": CREDENTIAL})
    assert native.RocketlaneNode._request_parts(parsed.config) == ("GET", "/projects/201", {}, None)
