"""Wire-level tests against Hubstaff's documented Time Tracking API v2."""
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import hubstaff_node as hs
from nodes.core.registry import NODE_REGISTRY
from utils import ssrf
from nodes.core.run_op import run_node_operation

AUTH = {"credential_type": "hubstaff_organization_token", "access_token": "hsoat_synthetic-secret"}
CASES = [
    ("list_organizations", {}, "GET", "/v2/organizations", {"organizations": [{"id": 1, "name": "Example"}]}),
    ("get_organization", {"organization_id": 1}, "GET", "/v2/organizations/1", {"organization": {"id": 1}}),
    ("list_members", {"organization_id": 1}, "GET", "/v2/organizations/1/members", {"members": []}),
    ("list_projects", {"organization_id": 1, "status": "archived"}, "GET", "/v2/organizations/1/projects", {"projects": []}),
    ("get_project", {"project_id": 3}, "GET", "/v2/projects/3", {"project": {"id": 3}}),
    ("create_project", {"organization_id": 1, "name": "Example", "billable": False}, "POST", "/v2/organizations/1/projects", {"project": {"id": 3}}),
    ("update_project", {"project_id": 3, "name": "Updated"}, "PUT", "/v2/projects/3", {"project": {"id": 3}}),
    ("list_clients", {"organization_id": 1}, "GET", "/v2/organizations/1/clients", {"clients": []}),
    ("get_client", {"client_id": 4}, "GET", "/v2/clients/4", {"client": {"id": 4}}),
    ("create_client", {"organization_id": 1, "name": "Example"}, "POST", "/v2/organizations/1/clients", {"client": {"id": 4}}),
    ("update_client", {"client_id": 4, "phone": "123"}, "PUT", "/v2/clients/4", {"client": {"id": 4}}),
    ("list_tasks", {"project_id": 3}, "GET", "/v2/projects/3/tasks", {"tasks": []}),
    ("get_task", {"task_id": 5}, "GET", "/v2/tasks/5", {"task": {"id": 5, "lock_version": 6}}),
    ("create_task", {"project_id": 3, "summary": "Example"}, "POST", "/v2/projects/3/tasks", {"task": {"id": 5}}),
    ("update_task", {"task_id": 5, "lock_version": 6, "status": "completed"}, "PUT", "/v2/tasks/5", {"task": {"id": 5}}),
    ("delete_task", {"task_id": 5}, "DELETE", "/v2/tasks/5", None),
    ("list_daily_activities", {"organization_id": 1, "date_start": "2026-01-01", "date_stop": "2026-01-02"}, "GET", "/v2/organizations/1/activities/daily", {"daily_activities": []}),
    ("list_timesheets", {"organization_id": 1}, "GET", "/v2/organizations/1/timesheets", {"timesheets": []}),
    ("update_timesheet", {"timesheet_id": 7, "status": "denied", "denial_reason": "Example"}, "PUT", "/v2/timesheets/7", {"timesheet": {"id": 7}}),
    ("create_time_entry", {"user_id": 2, "project_id": 3, "start_time": "2026-01-01T12:00:00Z", "tracked": 60, "note": "Example"}, "POST", "/v2/users/2/time_entries", None),
]


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        assert request.url.host == "api.hubstaff.com"
        assert request.headers["Authorization"] == "Bearer " + AUTH["access_token"]
        code, body, headers = replies.pop(0)
        return httpx.Response(code, content=body, headers=headers)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(hs, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


def reply(transport, body, code=200):
    transport[1].append((code, json.dumps(body).encode(), {"Content-Type": "application/json"}))


async def run(operation, config=None):
    return await run_node_operation(node_type="automation-hubstaff", operation=operation,
        arguments=config or {}, credential_data=dict(AUTH), user_id="00000000-0000-0000-0000-000000000001")


@pytest.mark.asyncio
@pytest.mark.parametrize("op,config,method,path,body", CASES)
async def test_one_contract_operation_per_action(transport, op, config, method, path, body):
    if body is None:
        transport[1].append((204 if method == "DELETE" else 201, b"", {}))
    else:
        reply(transport, body, 201 if method == "POST" and op != "create_task" else 200)
    result = await run(op, config)
    assert result["status"] == "success"
    assert len(transport[0]) == 1
    request = transport[0][0]
    assert (request.method, request.url.path) == (method, path)
    assert AUTH["access_token"] not in str(request.url)
    if method in {"POST", "PUT"}:
        sent = json.loads(request.content)
        assert "operation" not in sent and "organization_id" not in sent and "user_id" not in sent
        if op == "update_task": assert sent == {"lock_version": 6, "status": "completed"}
        if op == "create_project": assert sent == {"name": "Example", "billable": False}
    if op == "list_daily_activities":
        assert request.url.params["date[start]"] == "2026-01-01"
        assert request.url.params["date[stop]"] == "2026-01-02"
    if body:
        assert result[next(iter(body))] == next(iter(body.values()))


@pytest.mark.asyncio
async def test_pagination(transport):
    reply(transport, {"organizations": [{"id": 1}], "pagination": {"next_page_start_id": 20}})
    out = await run("list_organizations", {"page_limit": 1})
    assert out["next_page_start_id"] == 20
    reply(transport, {"organizations": []})
    out = await run("list_organizations", {"page_start_id": 20, "page_limit": 1})
    assert out["next_page_start_id"] is None
    assert transport[0][-1].url.params["page_start_id"] == "20"


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [401, 403, 404, 409, 429, 500])
async def test_provider_errors_and_secret_redaction(transport, code):
    reply(transport, {"error": "Rejected " + AUTH["access_token"]}, code)
    out = await run("list_organizations")
    assert out["status"] == "error" and out["status_code"] == code
    assert AUTH["access_token"] not in json.dumps(out)


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"organizations": {}}, {"organizations": [None]}, {"error": "failure"}, {"organizations": [], "pagination": {"next_page_start_id": "bad"}}])
async def test_malformed_success(transport, body):
    reply(transport, body)
    with pytest.raises(ValueError):
        await run("list_organizations")


@pytest.mark.asyncio
async def test_redirect_refused(transport):
    transport[1].append((302, b"", {"Location": "https://other.test"}))
    assert (await run("list_organizations"))["status"] == "error"
    assert len(transport[0]) == 1


@pytest.mark.parametrize("config", [
    {"operation": "get_project", "project_id": "../other"},
    {"operation": "get_task", "task_id": 0},
    {"operation": "update_task", "task_id": 5, "status": "completed"},
    {"operation": "create_time_entry", "user_id": 2, "project_id": 3, "start_time": "2026-01-01T00:00:00", "tracked": 60, "note": "Example"},
    {"operation": "list_daily_activities", "organization_id": 1, "date_start": "2026-02-02", "date_stop": "2026-01-01"},
    {"operation": "create_project", "organization_id": 1, "name": "Example", "undocumented": True},
])
def test_invalid_config(config):
    with pytest.raises(ValueError):
        hs.HubstaffNode.parse_config({"config": config, "credentials": AUTH})


def test_registration_and_manual_credential_defaults():
    assert NODE_REGISTRY["automation-hubstaff"] is hs.HubstaffNode
    cred = hs.HubstaffOrganizationTokenCredential(access_token=" hsoat_synthetic-secret ")
    assert cred.credential_type == "hubstaff_organization_token"
    assert cred.access_token == AUTH["access_token"]
