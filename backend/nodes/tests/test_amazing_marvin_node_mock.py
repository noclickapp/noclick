"""HTTP-boundary regressions for Amazing Marvin; never use a live account."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import amazing_marvin_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-marvin-token-123456"
CASES = json.loads((Path(__file__).parent / "fixtures/amazing-marvin/requests.json").read_text())
EXPECTED = {
    "create_task": ("POST", "/addTask"), "mark_task_done": ("POST", "/markDone"),
    "create_project": ("POST", "/addProject"), "create_event": ("POST", "/addEvent"),
    "get_tracked_task": ("GET", "/trackedItem"), "list_children": ("GET", "/children"),
    "list_today_items": ("GET", "/todayItems"), "list_due_items": ("GET", "/dueItems"),
    "list_today_time_blocks": ("GET", "/todayTimeBlocks"), "list_categories": ("GET", "/categories"),
    "list_labels": ("GET", "/labels"), "track_time": ("POST", "/track"),
    "get_time_tracks": ("POST", "/tracks"), "get_kudos": ("GET", "/kudos"),
    "get_profile": ("GET", "/me"), "list_goals": ("GET", "/goals"),
    "record_habit": ("POST", "/updateHabit"), "get_habit": ("GET", "/habit"),
    "list_habits": ("GET", "/habits"),
}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(operation, **config):
    return NodeFactory.create_node(node_id="marvin-fixture", node_type="automation-amazing-marvin",
        node_data={"config": {"operation": operation, **CASES[operation], **config},
            "credentials": {"credential_type": "amazing_marvin_api_token", "api_token": TOKEN}})


def transport(monkeypatch, *, status=200, data=None, text=None):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, text=text) if text is not None else httpx.Response(status, json=data)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CASES)
async def test_amazing_marvin_routes_and_wire_payload(monkeypatch, operation):
    arrays = {"list_children", "list_today_items", "list_due_items", "list_today_time_blocks", "list_categories", "list_labels", "get_time_tracks", "list_goals", "list_habits"}
    reply = [{"_id": "owned", "title": "Owned example"}] if operation in arrays else {"title": "Owned example"}
    requests = transport(monkeypatch, data=reply)
    result = await node(operation).execute({})
    assert result["status"] == "success" and len(requests) == 1
    request = requests[0]
    method, path = EXPECTED[operation]
    assert request.method == method and str(request.url).startswith(native.BASE + path)
    assert request.url.path == "/api" + path
    assert request.headers["X-API-Token"] == TOKEN and "X-Full-Access-Token" not in request.headers
    assert "raw" not in request.url.params and TOKEN not in str(result)
    if operation == "create_task":
        assert request.headers["X-Auto-Complete"] == "false"
        assert json.loads(request.content) == {"title": "Example API task +today", "parentId": "xyz", "labelIds": ["abc", "def"], "day": "2020-07-17", "dueDate": "2020-07-20", "timeEstimate": 300000, "isStarred": 3, "backburner": False}
    if operation == "mark_task_done":
        assert json.loads(request.content) == {"itemId": "x23n123nk", "timeZoneOffset": 60}
    if operation == "record_habit":
        assert json.loads(request.content) == {"habitId": "1n2ifni0qnf31", "value": 4, "time": 1678378323530, "updateDB": True}
    if operation == "track_time":
        assert json.loads(request.content) == {"taskId": "nfieamewpemnfiqe", "action": "STOP"}
    if operation == "get_time_tracks":
        assert json.loads(request.content) == {"taskIds": ["nfieamewpemnfiqe"]}
    if operation == "list_children":
        assert dict(request.url.params) == {"parentId": "unassigned"}
    if operation in {"list_today_items", "list_today_time_blocks"}:
        assert dict(request.url.params) == {"date": "2023-02-28"}
    if operation in {"create_task", "mark_task_done", "create_project", "create_event"}:
        assert result == {"status": "success", "http_status": 200, "acknowledged": True}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 400, 401, 403, 404, 429, 500])
async def test_amazing_marvin_refusal_no_retry_or_token_echo(monkeypatch, status):
    requests = transport(monkeypatch, status=status, text="Refused " + TOKEN)
    result = await node("create_task").execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
async def test_amazing_marvin_empty_write_body_and_timer_without_task(monkeypatch):
    transport(monkeypatch, text="")
    assert (await node("create_task").execute({}))["acknowledged"]
    transport(monkeypatch, text="null")
    assert (await node("get_tracked_task").execute({}))["data"] is None
    transport(monkeypatch, data=4)
    assert (await node("record_habit").execute({}))["data"] == 4


@pytest.mark.asyncio
async def test_amazing_marvin_evidence_empty_list_and_redaction(monkeypatch):
    transport(monkeypatch, data=[])
    assert (await node("list_categories").execute({}))["data"] == []
    transport(monkeypatch, data={"email": "person@example.test", "api_token": "other-secret", "note": TOKEN})
    result = await node("get_profile").execute({})
    assert result["data"] == {"email": "person@example.test", "note": "[redacted]"}
    transport(monkeypatch, data={"error": "Rejected " + TOKEN})
    assert (await node("get_profile").execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_amazing_marvin_malformed_success_fails(monkeypatch):
    transport(monkeypatch, data={})
    with pytest.raises(ValueError):
        await node("list_categories").execute({})
    transport(monkeypatch, text="<html>Not JSON</html>")
    with pytest.raises(ValueError):
        await node("get_profile").execute({})


@pytest.mark.parametrize("operation,config", [
    ("list_today_items", {"date": "2026-02-30"}),
    ("create_event", {"start": "2026-02-28T14:00:00"}),
    ("track_time", {"action": "start"}),
    ("get_time_tracks", {"task_ids": ["id"] * 101}),
    ("list_habits", {"raw": 1}),
])
def test_amazing_marvin_rejects_invalid_inputs(operation, config):
    with pytest.raises(ValueError):
        node(operation, **config)


def test_amazing_marvin_schema_and_single_endpoint_per_operation():
    assert set(CASES) == set(EXPECTED) == set(native.ROUTES) and len(CASES) == 19
    assert len(set(EXPECTED.values())) == 19
    assert native.AmazingMarvinNode.connection_evidence.operation == "list_categories"
    with pytest.raises(ValidationError):
        native.AmazingMarvinAPITokenCredential(api_token="https://example.test/token")
