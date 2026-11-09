"""Houzz Pro wire, connection and response regressions; no live service access."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import houzz_pro_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-houzz-access-token"
CREDENTIAL = {"credential_type": "houzz_pro_access_token", "access_token": TOKEN}
FIXTURES = Path(__file__).parent / "fixtures" / "houzz-pro"
CASES = json.loads((FIXTURES / "wire-cases.json").read_text())
PROJECTS = json.loads((FIXTURES / "projects.json").read_text())["body"]

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id="houzz-pro-test", node_type="automation-houzz-pro",
        node_data={"config": config, "credentials": credential if credential is not None else CREDENTIAL})


def transport(monkeypatch, payload, status=200, content_type="application/json"):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=payload, headers={"Content-Type": content_type})
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["config"]["operation"])
async def test_all_operations_exact_wire(monkeypatch, case):
    listing = case["config"]["operation"].startswith("list_")
    response = PROJECTS if listing else {"data": {"id": 123, "name": "Sample"}}
    requests = transport(monkeypatch, response, 201 if case["config"]["operation"].startswith("create_") else 200)
    result = await node(case["config"]).execute({})
    assert result["status"] == "success" and result["data"] == response["data"]
    assert len(requests) == 1
    request = requests[0]
    assert request.url.host == "pro-api.houzz.com"
    assert request.method == case["method"] and request.url.path == case["path"]
    assert dict(request.url.params) == case["query"]
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert request.headers["Accept"] == "application/json"
    assert (json.loads(request.content) if request.content else None) == case["body"]
    if case["body"] is not None:
        assert request.headers["Content-Type"] == "application/json"


@pytest.mark.asyncio
async def test_filters_false_zero_and_write_idempotency(monkeypatch):
    requests = transport(monkeypatch, PROJECTS)
    await node({"operation": "list_projects", "archived": False, "status_id": 3, "contact_id": 4471, "limit": 50, "offset": 20}).execute({})
    assert dict(requests[0].url.params) == {"archived": "false", "statusId": "3", "contactId": "4471", "limit": "50", "offset": "20"}
    requests = transport(monkeypatch, {"data": {"id": 123}})
    await node({"operation": "update_project", "resource_id": "123", "archived": False, "budget": 0, "idempotency_key": "one-write-123"}).execute({})
    assert json.loads(requests[0].content) == {"archived": False, "budget": 0}
    assert requests[0].headers["Idempotency-Key"] == "one-write-123"


@pytest.mark.asyncio
async def test_pagination_and_optional_total(monkeypatch):
    transport(monkeypatch, PROJECTS)
    result = await node({"operation": "list_projects"}).execute({})
    assert result["has_more"] is False and result["next_offset"] is None
    transport(monkeypatch, {"data": [{"id": 1}], "limit": 1, "offset": 3, "total": 5})
    result = await node({"operation": "list_projects", "limit": 1, "offset": 3}).execute({})
    assert result["has_more"] is True and result["next_offset"] == 4
    transport(monkeypatch, {"data": [{"id": 1}], "limit": 1, "offset": 0})
    result = await node({"operation": "list_projects", "limit": 1}).execute({})
    assert result["has_more"] is True and result["total"] is None
    transport(monkeypatch, {"data": [], "limit": 20, "offset": 0})
    assert (await node({"operation": "list_projects"}).execute({}))["has_more"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 422, 429, 503])
async def test_provider_errors_are_verbatim_redacted_and_never_retried(monkeypatch, status):
    requests = transport(monkeypatch, {"error": {"code": "FORBIDDEN", "message": "Permission denied " + TOKEN}}, status)
    with pytest.raises(ValueError, match=r"Permission denied \[redacted\]"):
        await node({"operation": "create_project", "name": "Test"}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"error": {"message": "Denied"}, "data": []}, {"data": {}}, {"data": [], "limit": 0, "offset": 0}, {"data": [], "limit": 20, "offset": -1}])
async def test_malformed_page_does_not_succeed(monkeypatch, payload):
    transport(monkeypatch, payload)
    with pytest.raises(ValueError):
        await node({"operation": "list_projects"}).execute({})


@pytest.mark.asyncio
async def test_token_cannot_escape_in_response(monkeypatch):
    transport(monkeypatch, {"data": {"name": "Echo " + TOKEN}})
    assert TOKEN not in str(await node({"operation": "get_project", "resource_id": "123"}).execute({}))
    transport(monkeypatch, PROJECTS, content_type="text/html")
    with pytest.raises(ValueError, match="unexpected JSON"):
        await node({"operation": "list_projects"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "get_project", "resource_id": "../leads"},
    {"operation": "get_project", "resource_id": "123?fields=secret"},
    {"operation": "update_project", "resource_id": "123"},
    {"operation": "update_lead_phase", "resource_id": "123"},
    {"operation": "list_projects", "limit": 301},
    {"operation": "list_projects", "offset": -1},
    {"operation": "create_project_task", "project_id": "123", "title": "Task", "visibility": "everyone"},
    {"operation": "create_project", "name": "Test", "budget": float("nan")},
])
def test_invalid_config_rejected_before_request(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


def test_credential_manual_default_and_foreign_family():
    assert native.HouzzProAccessToken(access_token=TOKEN).credential_type == native.FAMILY
    with pytest.raises(ValueError, match="Houzz Pro"):
        node({"operation": "list_projects"}, {"credential_type": "other_token", "access_token": TOKEN})
    for token in ["https://example.com/token", "Bearer abc", "test token"]:
        with pytest.raises(ValueError):
            native.HouzzProAccessToken(access_token=token)
