"""Offline tests exercise factory parsing and the actual HTTP request builder."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import agenty_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-agenty-token"
CASES = json.loads((Path(__file__).parent / "fixtures/agenty/requests.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=True):
    return NodeFactory.create_node(node_id="agenty-test", node_type="automation-agenty",
        node_data={"config": config, **({"credentials": {"credential_type": "agenty_api_key", "api_key": TOKEN}} if credentials else {})})


def mock_client(monkeypatch, status=200, body=None, content=None):
    requests = []
    def respond(request):
        requests.append(request)
        if content is not None:
            return httpx.Response(status, content=content)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,query,body", CASES, ids=[c[0]["operation"] for c in CASES])
async def test_exact_contract_requests(monkeypatch, config, method, path, query, body):
    reply = {"message": "Accepted", "data": [{"name": "Product scraper"}]}
    requests = mock_client(monkeypatch, status=201 if method == "POST" else 200, body=reply)
    result = await node(config).execute({})
    assert result == {"status": "success", "data": reply}
    assert len(requests) == 1
    req = requests[0]
    assert req.method == method and req.url.path == path
    assert req.url.host == "api.agenty.com"
    assert dict(req.url.params) == query
    assert req.headers["Authorization"] == "Bearer " + TOKEN
    assert (json.loads(req.content) if req.content else None) == body


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_http_failures_and_redirects_preserve_status_redact_token(monkeypatch, status):
    requests = mock_client(monkeypatch, status=status, body={"message": TOKEN})
    result = await node({"operation": "list_agents"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [[], {"data": [], "total": 0}, {"items": [{"name": "Products"}]}])
async def test_provider_page_shape_is_preserved(monkeypatch, body):
    mock_client(monkeypatch, body=body)
    assert (await node({"operation": "list_agents"}).execute({}))["data"] == body


@pytest.mark.asyncio
async def test_empty_delete_and_error_envelope(monkeypatch):
    mock_client(monkeypatch, status=204, content=b"")
    assert await node({"operation": "delete_list", "id": 123}).execute({}) == {"status": "success", "data": None}
    mock_client(monkeypatch, body={"statusCode": 401, "message": TOKEN})
    result = await node({"operation": "list_agents"}).execute({})
    assert result["status"] == "error" and TOKEN not in str(result)


@pytest.mark.asyncio
async def test_missing_credential_refuses_before_network(monkeypatch):
    requests = mock_client(monkeypatch, body=[])
    with pytest.raises(ValueError, match="Connect an Agenty"):
        await node({"operation": "list_agents"}, credentials=False).execute({})
    assert requests == []


@pytest.mark.parametrize("config", [
    {"operation": "start_job", "agent_id": "../jobs"},
    {"operation": "get_job", "job_id": 0},
    {"operation": "list_agents", "limit": 1001},
    {"operation": "list_agents", "offset": -1},
    {"operation": "update_input", "agent_id": "abc", "input_source": '{"type":"manual","data":[]}'},
    {"operation": "add_rows", "list_id": 1, "rows": "[]"},
    {"operation": "start_job"},
])
def test_invalid_config_is_refused(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


def test_schema_and_account_evidence():
    assert len(CASES) == len(native.ROUTES) == 23
    assert native.AgentyNode.connection_evidence.operation == "list_agents"
    schema = native.AgentyConfig.model_json_schema()
    assert schema["$defs"]["AgentyAPIKeyCredential"]["properties"]["api_key"]["ui:widget"] == "password"
