"""Exercise every Lokalise operation at its HTTP boundary without an account.

Cases pin methods, routes, bodies, filters and page controls; error cases protect
connection evidence and prevent unacknowledged or partial writes looking successful.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import lokalise_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-lokalise-test-token"
CASES = json.loads((Path(__file__).parent / "fixtures/lokalise/requests.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    result = NodeFactory.create_node(node_id="lokalise-test", node_type="automation-lokalise",
        node_data={"config": config, "credentials": credentials or {
            "credential_type": "lokalise_api_token", "api_token": TOKEN}})
    result.emit = AsyncMock()
    return result


def transport(monkeypatch, response):
    requests = []

    def respond(request):
        requests.append(request)
        return response(request) if callable(response) else response

    def client(**kwargs):
        assert kwargs == {"timeout": 30, "trust_env": False, "follow_redirects": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["config"]["operation"])
async def test_lokalise_request_contract(monkeypatch, case):
    requests = transport(monkeypatch, httpx.Response(200, json=case["response"]))
    instance = node(case["config"])
    result = await instance.execute({})
    assert result["status"] == "success"
    assert result["response"] == case["response"]
    instance.emit.assert_awaited_once_with(result)
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert request.url.host == "api.lokalise.com"
    assert request.url.path == "/api2" + case["path"]
    assert dict(request.url.params) == case.get("query", {})
    assert (json.loads(request.content) if request.content else None) == case.get("body")
    assert request.headers["X-Api-Token"] == TOKEN


@pytest.mark.asyncio
async def test_lokalise_evidence_and_explicit_pagination(monkeypatch):
    payload = {"projects": [{"project_id": "one", "name": "My app"}]}
    transport(monkeypatch, httpx.Response(200, json=payload, headers={
        "X-Pagination-Total-Count": "3", "X-Pagination-Page-Count": "3"}))
    result = await node({"operation": "list_projects", "page": 2, "limit": 1}).execute({})
    assert result["data"] == payload["projects"]
    assert result["pagination"] == {"page": 2, "limit": 1, "next_page": 3,
        "total_count": "3", "page_count": "3"}
    assert native.LokaliseNode.connection_evidence.operation == "list_projects"
    transport(monkeypatch, httpx.Response(200, json={"projects": []}))
    result = await node({"operation": "list_projects"}).execute({})
    assert result["data"] == [] and result["pagination"]["next_page"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [401, 403, 404, 422, 429, 500])
async def test_lokalise_provider_rejection_is_redacted(monkeypatch, code):
    transport(monkeypatch, httpx.Response(code, json={"error": {"code": code, "message": "Rejected " + TOKEN}}))
    result = await node({"operation": "list_projects"}).execute({})
    assert result["status"] == "error" and result["http_status"] == code
    assert result["error"]["message"] == "Rejected [redacted]"
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_lokalise_partial_write_errors_are_not_success(monkeypatch):
    transport(monkeypatch, httpx.Response(200, json={"keys": [], "errors": [{"message": "Invalid key"}]}))
    result = await node({"operation": "create_keys", "project_id": "app", "keys": [{"key_name": "greeting", "platforms": ["web"]}]}).execute({})
    assert result["status"] == "error" and result["error"][0]["message"] == "Invalid key"


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(200, text="<html>Login</html>"),
    httpx.Response(200, json=[]), httpx.Response(200, json={"projects": {}})])
async def test_lokalise_malformed_response_does_not_prove_access(monkeypatch, response):
    transport(monkeypatch, response)
    with pytest.raises(ValueError, match="Lokalise returned"):
        await node({"operation": "list_projects"}).execute({})


@pytest.mark.asyncio
async def test_lokalise_timeout_never_retries_write_or_leaks_token(monkeypatch):
    def fail(request):
        raise httpx.ReadTimeout(TOKEN, request=request)
    requests = transport(monkeypatch, fail)
    with pytest.raises(ValueError, match="inspect the resource") as error:
        await node({"operation": "create_project", "name": "App"}).execute({})
    assert TOKEN not in str(error.value) and len(requests) == 1


@pytest.mark.parametrize("config", [
    {"operation": "get_project", "project_id": "../secrets"},
    {"operation": "get_project", "project_id": "app:branch"},
    {"operation": "get_key", "project_id": "app", "key_id": 0},
    {"operation": "list_projects", "limit": 501},
    {"operation": "list_projects", "page": 0},
    {"operation": "update_key", "project_id": "app", "key_id": 1},
    {"operation": "create_keys", "project_id": "app", "keys": []},
    {"operation": "create_project", "name": "App", "base_lang_iso": "en"},
])
def test_lokalise_rejects_invalid_input(config):
    assert not native.LokaliseNode.validate_config({"config": config})["valid"]


@pytest.mark.parametrize("token", ["https://lokalise.com/token", "<token>", "X-Api-Token: secret", "a\nb", "tökén"])
def test_lokalise_rejects_bad_token(token):
    with pytest.raises(ValidationError):
        native.LokaliseAPITokenCredential(api_token=token)


def test_lokalise_trims_token_and_refuses_foreign_credential():
    assert native.LokaliseAPITokenCredential(api_token="  synthetic-token\n").api_token == "synthetic-token"
    assert not native.LokaliseNode.validate_config({"config": {"operation": "list_projects"},
        "credentials": {"credential_type": "other_api_token", "api_token": TOKEN}})["valid"]
