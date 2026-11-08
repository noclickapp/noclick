"""Published TimeCamp examples exercised through the native node and HTTP boundary."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import timecamp_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-timecamp-token"
CASES = json.loads((Path(__file__).parent / "fixtures/timecamp/requests.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id="timecamp-test", node_type="automation-timecamp",
        node_data={"config": config, "credentials": credentials or {
            "credential_type": "timecamp_api_token", "api_token": TOKEN}})


def transport(monkeypatch, response):
    requests = []

    def respond(request):
        requests.append(request)
        return response

    def client(**kwargs):
        assert kwargs == {"timeout": 30, "trust_env": False, "follow_redirects": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["config"]["operation"])
async def test_published_request_and_response(monkeypatch, case):
    requests = transport(monkeypatch, httpx.Response(case["status"], json=case["response"]))
    result = await node(case["config"]).execute({})
    assert result == {"status": "success", "http_status": case["status"],
        "operation": case["config"]["operation"], "data": case["response"]}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert request.url.host == "app.timecamp.com"
    assert request.url.path == "/third_party/api" + case["path"]
    assert dict(request.url.params) == case["query"]
    assert (json.loads(request.content) if request.content else None) == case["body"]
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert request.headers["Accept"] == "application/json"


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [400, 401, 403, 404, 429, 500])
async def test_provider_rejection_is_error_and_secret_redacted(monkeypatch, code):
    transport(monkeypatch, httpx.Response(code, json={"message": "Rejected " + TOKEN}))
    result = await node({"operation": "get_me"}).execute({})
    assert result == {"status": "error", "http_status": code, "error": {"message": "Rejected [redacted]"}}


@pytest.mark.asyncio
async def test_success_http_error_envelope(monkeypatch):
    transport(monkeypatch, httpx.Response(200, json={"error": "No permission"}))
    assert (await node({"operation": "list_tasks"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    httpx.Response(302, headers={"Location": "https://example.com"}),
    httpx.Response(200, text="<html>wrong host</html>"),
    httpx.Response(200, headers={"content-type": "application/json"}, content=b"invalid"),
    httpx.Response(200, json=[]), httpx.Response(200, json={}),
])
async def test_identity_never_accepts_unproven_account(monkeypatch, response):
    transport(monkeypatch, response)
    try:
        result = await node({"operation": "get_me"}).execute({})
    except ValueError:
        return
    assert result["status"] == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,status,config", [
    ("delete_entry", 204, {"id": 52321}),
    ("update_tag", 201, {"tag_id": 13, "name": "Development"}),
])
async def test_documented_empty_success(monkeypatch, operation, status, config):
    transport(monkeypatch, httpx.Response(status))
    result = await node({"operation": operation, **config}).execute({})
    assert result["data"] is None and result["acknowledged"] is True


@pytest.mark.asyncio
async def test_secret_redaction_in_nested_response_and_keys(monkeypatch):
    transport(monkeypatch, httpx.Response(200, json={TOKEN: {"note": TOKEN}}))
    result = await node({"operation": "list_tasks"}).execute({})
    assert TOKEN not in str(result)


@pytest.mark.parametrize("config", [
    {"operation": "get_user", "user_id": -1},
    {"operation": "get_user", "user_id": "../me"},
    {"operation": "list_tasks", "task_id": "../me"},
    {"operation": "list_entries", "from_date": "2021-03-11", "to_date": "2021-03-01"},
    {"operation": "create_entry", "date": "2021-02-30", "duration": 60},
    {"operation": "create_entry", "date": "2021-03-02", "duration": 0},
    {"operation": "update_entry", "id": 1},
    {"operation": "update_task", "task_id": 1},
    {"operation": "update_tag", "tag_id": 1},
    {"operation": "get_me", "unknown": "field"},
])
def test_invalid_inputs(config):
    with pytest.raises(ValueError):
        node(config)


@pytest.mark.parametrize("token", ["Bearer private-token", "https://example.com/token", "<token>", "a\r\nb"])
def test_credentials_do_not_expose_secret(token):
    with pytest.raises(ValidationError) as caught:
        native.TimecampAPITokenCredential(api_token=token)
    assert token not in str(caught.value)


def test_connection_evidence_reads_current_account():
    assert native.TimecampNode.connection_evidence.identity_operation == "get_me"
