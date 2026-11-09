"""Offline HTTP-boundary checks for the published Userback REST routes."""
import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import userback_node as mod

CASES = json.loads((Path(__file__).parent / "fixtures/userback/requests.json").read_text())
TOKEN = "test-userback-token-value"
CREDENTIAL = {"api_token": TOKEN}


def node(config):
    full = mod.UserbackNode.parse_config({"config": config, "credentials": CREDENTIAL})
    return mod.UserbackNode("userback", "automation-userback", {}, config=full)


def mock_transport(monkeypatch, handler):
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs) as session:
            yield session
    monkeypatch.setattr(mod, "guarded_async_client", client)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["config"]["operation"])
async def test_contract_request(monkeypatch, case):
    calls = []
    operation = case["config"]["operation"]
    if operation.startswith("list_"):
        payload = {"data": [{"id": 4455, "name": "My project"}], "_links": {"self": "https://rest.userback.io/1.0/project"},
                   "_pagination": {"totalPages": 2, "totalRecords": 11, "pageSize": 10, "records": 1, "pageNumber": 2}}
    else:
        payload = True if case["method"] == "DELETE" else {"id": 4455}

    def handler(request):
        calls.append(request)
        assert request.method == case["method"]
        assert request.url.host == "rest.userback.io"
        assert request.url.path == "/1.0" + case["path"]
        assert request.headers["authorization"] == "Bearer " + TOKEN
        assert dict(request.url.params) == case.get("query", {})
        if "body" in case:
            assert json.loads(request.content) == case["body"]
        else:
            assert not request.content
        return httpx.Response(202 if case["method"] == "DELETE" else 201 if case["method"] in {"POST", "PATCH"} else 200, json=payload)
    mock_transport(monkeypatch, handler)
    result = await node(case["config"]).execute({})
    assert len(calls) == 1
    assert result["status"] == "success"
    if operation.startswith("list_"):
        assert result["data"] == payload["data"]
        assert result["_pagination"] == payload["_pagination"]
    if case["method"] == "DELETE":
        assert result["accepted"] is True
        assert result["deletion_verified"] is False


@pytest.mark.parametrize("config", [
    {"operation": "get_feedback", "id": -1},
    {"operation": "get_project", "id": 2147483648},
    {"operation": "list_projects", "limit": 51},
    {"operation": "list_feedback", "page": 0},
    {"operation": "list_members", "sort": "name"},
    {"operation": "update_feedback", "id": 1},
    {"operation": "update_project", "id": 1, "url": "invalid"},
    {"operation": "create_workflow", "projectId": 1, "name": "X", "color": "red"},
    {"operation": "create_feedback", "projectId": 1, "title": "X", "description": "X", "feedbackType": "Bug"},
])
def test_invalid_config(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 422, 429, 500])
async def test_errors_preserve_provider_rejection_and_redact_token(monkeypatch, status):
    mock_transport(monkeypatch, lambda request: httpx.Response(status, json={"message": "Rejected " + TOKEN}))
    result = await node({"operation": "list_projects"}).execute({})
    assert result["status"] == "error"
    assert result["http_status"] == status
    assert result["error"] == "Rejected [redacted]"
    assert result["status_code"] == status
    assert TOKEN not in json.dumps(result)


@pytest.mark.asyncio
async def test_non_json_and_unexpected_response(monkeypatch):
    mock_transport(monkeypatch, lambda request: httpx.Response(200, text="<html>"))
    assert (await node({"operation": "list_projects"}).execute({}))["status"] == "error"
    mock_transport(monkeypatch, lambda request: httpx.Response(200, json={"id": 99}))
    with pytest.raises(ValueError, match="different resource"):
        await node({"operation": "get_project", "id": 4455}).execute({})


@pytest.mark.asyncio
async def test_write_timeout_is_ambiguous_without_retry(monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("timeout", request=request)
    mock_transport(monkeypatch, handler)
    result = await node({"operation": "update_project", "id": 4455, "name": "Updated"}).execute({})
    assert result["status"] == "unknown"
    assert len(calls) == 1


def test_manual_credential_and_connection_evidence():
    credential = mod.UserbackAPITokenCredential.model_validate({"api_token": "  " + TOKEN + "  "})
    assert credential.credential_type == "userback_api_token"
    assert credential.api_token == TOKEN
    assert mod.UserbackNode.connection_evidence.operation == "list_projects"
    assert len(CASES) == len(mod.ROUTES) == 22


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 401])
async def test_unsaved_credential_evidence(monkeypatch, status):
    from nodes.core.connection_evidence import collect_evidence
    payload = {"data": [{"id": 4455, "name": "Customer Portal"}], "_pagination": {}} if status == 200 else {"message": "Token rejected", "status": 401}
    mock_transport(monkeypatch, lambda request: httpx.Response(status, json=payload))
    result = await collect_evidence(node_type="automation-userback", user_id="test-user", credential_data=CREDENTIAL)
    assert result.reachable is (status == 200)
    if status == 200:
        assert result.samples[0].label == "Customer Portal"
    else:
        assert "Token rejected" in result.error
