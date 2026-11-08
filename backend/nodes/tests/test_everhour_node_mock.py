"""Exercise real Everhour config parsing and HTTP serialization offline."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import everhour_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-everhour-key-123"
CASES = json.loads((Path(__file__).parent / "fixtures/everhour/requests.json").read_text())["cases"]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="everhour-fixture", node_type="automation-everhour",
        node_data={"config": config, "credentials": {"credential_type": "everhour_api_key", "api_key": TOKEN}})


def transport(monkeypatch, respond):
    requests = []
    def handler(request):
        requests.append(request)
        return respond(request)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["operation"])
async def test_everhour_documented_request_fields_and_response_shapes(monkeypatch, case):
    status = 204 if case["operation"] == "delete_task" else 201 if case["method"] == "POST" else 200
    requests = transport(monkeypatch, lambda _: httpx.Response(status, json=case["response"]) if status != 204 else httpx.Response(204))
    result = await node({"operation": case["operation"], **case["config"]}).execute({})
    assert result["status"] == "success"
    request, = requests
    assert request.method == case["method"]
    assert request.url.host == "api.everhour.com" and request.url.path == case["path"]
    assert dict(request.url.params) == case["query"]
    assert request.headers["X-Api-Key"] == TOKEN
    assert TOKEN not in str(request.url)
    if case["body"] is None:
        assert not request.content
    else:
        assert json.loads(request.content) == case["body"]
        assert request.headers["Content-Type"] == "application/json"
    assert "apiKey" not in str(result) and "provider-returned-key" not in str(result)
    if case["operation"] != "get_current_user":
        assert result["data"] == case["response"]


@pytest.mark.asyncio
async def test_everhour_identity_redacts_nested_keys_and_echoed_secret(monkeypatch):
    transport(monkeypatch, lambda _: httpx.Response(200, json={"id":1304, "name":"John Bender", "apiKey":"another-key", "nested":{"api_key":TOKEN}, "note":TOKEN}))
    result = await node({"operation":"get_current_user"}).execute({})
    assert result["data"]["name"] == "John Bender"
    assert result["data"]["nested"] == {} and result["data"]["note"] == "[redacted]"
    assert TOKEN not in str(result) and "another-key" not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_everhour_rejection_is_honest_redacted_and_never_retried(monkeypatch, status):
    requests = transport(monkeypatch, lambda _: httpx.Response(status, json={"message":"Access denied " + TOKEN}, headers={"Location":"https://other.example/"}))
    result = await node({"operation":"start_timer", "task":"ev:9876543210"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert result["message"] == "Access denied [redacted]" and len(requests) == 1


@pytest.mark.asyncio
async def test_everhour_timeout_does_not_retry_a_write(monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout("private transport context " + TOKEN, request=request)
    requests = transport(monkeypatch, timeout)
    with pytest.raises(ValueError, match="before repeating a write") as exc:
        await node({"operation":"start_timer", "task":"ev:9876543210"}).execute({})
    assert TOKEN not in str(exc.value) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,body", [("list_clients", {}), ("get_timer", []), ("get_current_user", None)])
async def test_everhour_wrong_response_shapes_are_not_success(monkeypatch, operation, body):
    transport(monkeypatch, lambda _: httpx.Response(200, json=body))
    with pytest.raises(ValueError):
        await node({"operation":operation}).execute({})


@pytest.mark.parametrize("config", [
    {"operation":"get_task", "task_id":"../users/me"},
    {"operation":"get_project", "project_id":"x?extra=y"},
    {"operation":"create_project", "name":"Project"},
    {"operation":"create_task", "project_id":"ev:123"},
    {"operation":"add_time", "task":"ev:123", "time":-1, "date":"2018-01-20"},
    {"operation":"add_time", "task":"ev:123", "time":3600, "date":"2018-02-30"},
    {"operation":"list_tasks", "project_id":"ev:123", "limit":251},
    {"operation":"search_tasks", "limit":101},
    {"operation":"create_client", "name":"Client", "extra":True},
])
def test_everhour_invalid_config_refused(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


def test_everhour_key_and_connection_evidence_contract():
    assert native.EverhourNode.connection_evidence.identity_operation == "get_current_user"
    assert len(CASES) == 24
    for key in ["https://example.com/key", "key with spaces", "X-Api-Key: value"]:
        with pytest.raises(ValueError):
            native.EverhourAPIKeyCredential(api_key=key)
