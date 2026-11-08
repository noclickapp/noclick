"""Offline wire-contract regressions for Fullstory's published v2 APIs."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import fullstory_node as native
from nodes.core.registry import NodeFactory

TOKEN = "fullstory-synthetic-test-key"
CREDENTIAL = {"credential_type": "fullstory_api_key", "api_key": TOKEN}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="fullstory-test", node_type="automation-fullstory",
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [
    ("list_users", {"is_identified": False, "email": "daniel.falko@example.com"}, {"results": [], "total_records": "0"}),
    ("get_user", {"id": "123"}, {"id": "123", "is_being_deleted": False}),
    ("create_user", {"uid": "xyz123", "display_name": "Daniel Falko", "properties": {"pricing_plan": "paid"}, "idempotency_key": "user-key"}, {"id": "123"}),
    ("update_user", {"id": "123", "email": "daniel.falko@example.com", "schema": {"properties": {"email": "str"}}}, {}),
    ("delete_user", {"id": "123"}, {}),
    ("delete_user_by_uid", {"uid": "abc + xyz"}, {}),
    ("import_users", {"requests": [{"uid": "xyz123", "properties": {"rewards_status": "platinum"}}]}, {"job": {"id": "abc123", "status": "PROCESSING", "created": "2017-01-15T01:30:15.01Z"}}),
    ("get_user_import", {"job_id": "abc123="}, {"imports": 42, "errors": 2, "job": {"id": "abc123", "status": "FAILED", "created": "2017-01-15T01:30:15.01Z"}}),
    ("list_user_import_errors", {"job_id": "abc123=", "page_token": "next+="}, {"results": [], "total_records": "0"}),
    ("list_user_imports", {"job_id": "abc123=", "include_schema": True}, {"results": [], "total_records": "0"}),
    ("create_event", {"name": "Support Ticket", "user": {"uid": "xyz123"}, "properties": {"priority": "Normal"}}, {}),
    ("import_events", {"requests": [{"name": "Support Ticket", "session": {"id": "123456789:123456789"}}]}, {"job": {"id": "abc123", "status": "PROCESSING", "created": "2017-01-15T01:30:15.01Z"}}),
    ("get_event_import", {"job_id": "abc123"}, {"imports": 42, "errors": 2, "job": {"id": "abc123", "status": "FAILED", "created": "2017-01-15T01:30:15.01Z"}}),
    ("list_event_import_errors", {"job_id": "abc123"}, {"results": [], "total_records": "0"}),
    ("list_event_imports", {"job_id": "abc123"}, {"results": [], "total_records": "0"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,body", CASES)
async def test_every_operation_exact_wire_request(monkeypatch, operation, config, body):
    requests = transport(monkeypatch, body)
    result = await node({"operation": operation, **config}).execute({})
    assert result["status"] == "success" and result["data"] == body
    assert len(requests) == 1
    req = requests[0]
    method, path = native.ROUTES[operation]
    for key in ("id", "job_id"):
        if "{" + key + "}" in path:
            path = path.replace("{" + key + "}", config[key])
    assert req.method == method and req.url.path == path
    assert req.url.host == "api.fullstory.com"
    assert req.headers["Authorization"] == "Basic " + TOKEN
    expected = {k: v for k, v in config.items() if k not in {"id", "job_id", "idempotency_key"}}
    if method == "POST":
        assert json.loads(req.content) == expected
    else:
        assert dict(req.url.params) == {k: str(v).lower() if isinstance(v, bool) else v for k, v in expected.items()}
    if "idempotency_key" in config:
        assert req.headers["Idempotency-Key"] == config["idempotency_key"]
    if method == "DELETE":
        assert result["deletion_requested"] and not result["deletion_complete"]


@pytest.mark.asyncio
async def test_pagination_returns_cursor_without_following(monkeypatch):
    body = json.loads((Path(__file__).parent / "fixtures/fullstory/list_users.json").read_text())
    requests = transport(monkeypatch, body)
    result = await node({"operation": "list_users", "page_token": "old+="}).execute({})
    assert result["next_page_token"] == body["next_page_token"] and result["has_more"]
    assert len(requests) == 1 and requests[0].url.params["page_token"] == "old+="


@pytest.mark.asyncio
async def test_202_import_results_are_pending(monkeypatch):
    transport(monkeypatch, {}, 202)
    result = await node({"operation": "list_event_imports", "job_id": "abc123"}).execute({})
    assert result["pending"] and "results" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_provider_rejection_preserved_and_key_redacted(monkeypatch, status):
    requests = transport(monkeypatch, {"message": "Rejected " + TOKEN, "code": "unauthorized"}, status)
    result = await node({"operation": "list_users"}).execute({})
    assert result == {"status": "error", "error": "Rejected [redacted]", "http_status": status}
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"results": {}}, {"results": [], "next_page_token": 42}])
async def test_bad_list_response_fails(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation": "list_users"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "delete_user_by_uid"},
    {"operation": "create_event", "name": "Event", "user": {"id": "1", "uid": "x"}},
    {"operation": "create_event", "name": "Event", "session": {"use_most_recent": True}},
    {"operation": "create_event", "name": "Event", "session": {"id": "1:2"}, "user": {"uid": "x"}},
    {"operation": "import_users", "requests": []},
    {"operation": "create_user", "idempotency_key": "bad\r\nheader"},
    {"operation": "list_users", "unsupported": True},
])
def test_invalid_inputs_fail(config):
    with pytest.raises((ValueError, ValidationError)):
        native.FullstoryNode.parse_config({"config": config, "credentials": CREDENTIAL})


@pytest.mark.asyncio
@pytest.mark.parametrize("identifier", ["..", "../users", "abc?x", "a\\b"])
async def test_resource_paths_cannot_escape(monkeypatch, identifier):
    requests = transport(monkeypatch, {})
    with pytest.raises(ValueError):
        await node({"operation": "get_user", "id": identifier}).execute({})
    assert requests == []
