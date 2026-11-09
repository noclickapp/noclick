"""Offline requests through the real factory, including connection evidence."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import swaggerhub_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / "fixtures/swaggerhub/requests.json").read_text())["cases"]
AUTH = {"credential_type": "swaggerhub_api_key", "api_key": "synthetic-swaggerhub-key"}
CLIENT = httpx.AsyncClient


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(arguments, credential=AUTH):
    return NodeFactory.create_node(node_id="swaggerhub-test", node_type="automation-swaggerhub",
        node_data={"config": arguments, "credentials": credential})


def transport(monkeypatch, reply):
    requests = []
    def handler(request):
        requests.append(request)
        return reply(request)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return CLIENT(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(native.httpx, "AsyncClient", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("action,config,method,path,query,body", CASES)
async def test_swaggerhub_contract_requests(monkeypatch, action, config, method, path, query, body):
    payload = {"projects": [{"name": "CoreServices"}], "totalCount": 1, "offset": 0}
    requests = transport(monkeypatch, lambda r: httpx.Response(200, json=payload))
    result = await node({"operation": action, **config}).execute({})
    assert result == {"status": "success", "data": payload, "http_status": 200}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert request.url.host == "api.swaggerhub.com"
    assert request.url.path == path
    assert dict(request.url.params) == query
    assert request.headers["Authorization"] == AUTH["api_key"]
    if body is not None:
        assert json.loads(request.content) == body
        assert request.headers["Content-Type"] == "application/json"
    else:
        assert not request.content


@pytest.mark.asyncio
async def test_swaggerhub_empty_write_response(monkeypatch):
    transport(monkeypatch, lambda r: httpx.Response(204))
    result = await node({"operation": "delete_project", "owner": "acme-org", "project_id": "CoreServices"}).execute({})
    assert result == {"status": "success", "data": None, "http_status": 204}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_swaggerhub_preserves_rejection_and_redacts_key(monkeypatch, status):
    requests = transport(monkeypatch, lambda r: httpx.Response(status, text="Rejected " + AUTH["api_key"], headers={"Location": "https://example.test"}))
    result = await node({"operation": "list_projects"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert result["error"] == "Rejected [redacted]"
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_swaggerhub_path_components_cannot_change_route(monkeypatch):
    requests = transport(monkeypatch, lambda r: httpx.Response(200, json={}))
    await node({"operation": "get_project", "owner": "org/a?b", "project_id": "Core Services"}).execute({})
    assert requests[0].url.raw_path == b"/projects/org%2Fa%3Fb/Core%20Services"
    with pytest.raises(ValueError, match="dot path"):
        await node({"operation": "get_project", "owner": "..", "project_id": "CoreServices"}).execute({})
    assert len(requests) == 1


def test_swaggerhub_manual_credential_default_and_validation():
    assert native.SwaggerHubAPIKeyCredential(api_key="synthetic-key").credential_type == "swaggerhub_api_key"
    for bad in ("", "has spaces", "line\nbreak", "https://example.test/key"):
        with pytest.raises((ValidationError, ValueError)):
            native.SwaggerHubAPIKeyCredential(api_key=bad)
    with pytest.raises(ValidationError):
        native.SwaggerHubAPIKeyCredential(credential_type="other_api_key", api_key="synthetic-key")


@pytest.mark.asyncio
async def test_swaggerhub_connection_evidence_uses_current_users_projects(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    # Exercise the evidence seam with the real operation, without a DB or emit.
    async def run(**kwargs):
        assert kwargs["operation"] == "list_projects"
        obj = node({"operation": kwargs["operation"]}, kwargs["credential_data"])
        obj.emit = AsyncMock()
        return await obj.execute({})
    monkeypatch.setattr("nodes.core.run_op.run_node_operation", run)
    requests = transport(monkeypatch, lambda r: httpx.Response(200, json={"projects": [{"name": "CoreServices"}], "totalCount": 1, "offset": 0}))
    result = await collect_evidence(node_type="automation-swaggerhub", credential_data=AUTH, user_id="fixture-user")
    assert result.reachable is True
    assert result.samples and result.samples[0].label == "CoreServices"
    assert requests[0].url.path == "/projects"
