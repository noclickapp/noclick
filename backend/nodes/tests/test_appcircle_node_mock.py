"""Offline Appcircle regressions exercise the real factory and HTTP boundary.

Fixtures use synthetic account identifiers; no provider account or sign-in is used.
"""
import json
from pathlib import Path

import httpx
import pytest

from nodes import appcircle_node as native
from nodes.core.registry import NodeFactory
from nodes.core.connection_evidence import _rows_from_operation

TOKEN = "synthetic-appcircle-access-token"
FIXTURES = json.loads((Path(__file__).parent / "fixtures/appcircle/operations.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id="appcircle-fixture", node_type="automation-appcircle",
        node_data={"config": config, "credentials": credentials or {
            "credential_type": "appcircle_access_token", "access_token": TOKEN}})


def mock_transport(monkeypatch, response):
    requests = []
    def handle(request):
        requests.append(request)
        return response(request) if callable(response) else httpx.Response(200, json=response)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", FIXTURES, ids=lambda x: x["config"]["operation"])
async def test_published_routes_query_casing_and_bodies(monkeypatch, case):
    requests = mock_transport(monkeypatch, case["response"])
    result = await node(case["config"]).execute({})
    assert result["status"] == "success"
    assert result["data"] == case["response"]
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert request.url.host == "api.appcircle.io"
    assert request.url.path == case["path"]
    assert dict(request.url.params) == case["query"]
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert request.headers["Accept"] == "application/json"
    if "body" in case:
        assert json.loads(request.content) == case["body"]
        assert request.headers["Content-Type"] == "application/json"
    else:
        assert request.content == b""


@pytest.mark.asyncio
async def test_organization_response_proves_account_and_preserves_pagination(monkeypatch):
    body = {"data": [{"id": "organization-one", "name": "Mobile engineering"}],
        "page": 1, "perPage": 200, "total": 1}
    mock_transport(monkeypatch, body)
    result = await node({"operation": "list_organizations"}).run({})
    assert _rows_from_operation(result) == body["data"]
    assert result["data"]["total"] == 1
    assert native.AppcircleNode.connection_evidence.operation == "list_organizations"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 400, 401, 403, 404, 429, 500])
async def test_rejections_preserve_provider_words_redact_token_and_never_retry(monkeypatch, status):
    requests = mock_transport(monkeypatch, lambda req: httpx.Response(status,
        text="Access denied: " + TOKEN, headers={"Location": "https://other.example/"}))
    result = await node({"operation": "list_build_profiles"}).execute({})
    assert result == {"status": "error", "http_status": status, "error": "Access denied: [redacted]"}
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_empty_success_is_acknowledgment_not_build_completion(monkeypatch):
    mock_transport(monkeypatch, lambda req: httpx.Response(200))
    result = await node({"operation": "start_build", "commit_id": "123e4567-e89b-12d3-a456-426614174000"}).execute({})
    assert result == {"status": "success", "http_status": 200, "data": None}


@pytest.mark.asyncio
async def test_error_envelope_and_malformed_json_cannot_succeed(monkeypatch):
    mock_transport(monkeypatch, {"errors": ["rejected " + TOKEN]})
    result = await node({"operation": "list_build_profiles"}).execute({})
    assert result["status"] == "error" and TOKEN not in str(result)
    mock_transport(monkeypatch, lambda req: httpx.Response(200, text="<html>sign in</html>"))
    with pytest.raises(ValueError):
        await node({"operation": "list_build_profiles"}).execute({})


@pytest.mark.asyncio
async def test_pagination_is_sent_without_hiding_provider_envelope(monkeypatch):
    requests = mock_transport(monkeypatch, {"items": [], "totalCount": 300})
    result = await node({"operation": "list_distribution_profiles", "page": 3, "size": 25, "search": "QA + iOS"}).execute({})
    assert dict(requests[0].url.params) == {"Page": "3", "Size": "25", "search": "QA + iOS"}
    assert result["page"] == 3 and result["size"] == 25
    assert result["data"]["totalCount"] == 300
    assert "complete" not in result


def test_manual_credential_defaults_hidden_secret_and_required_operation_fields():
    cred = native.AppcircleAccessTokenCredential(access_token=TOKEN)
    assert cred.credential_type == "appcircle_access_token"
    schema = cred.model_json_schema()
    assert schema["required"] == ["access_token"]
    assert schema["properties"]["access_token"]["ui:widget"] == "password"
    assert len(FIXTURES) == len(native.ROUTES) == 24
    assert native.AppcircleAddTestersConfig.model_json_schema()["properties"]["emails"]["items"]["format"] == "email"
    for token in ["", "Bearer secret", "https://example.com/token", "bad\x00token"]:
        with pytest.raises(ValueError):
            native.AppcircleAccessTokenCredential(access_token=token)
    for config in [
        {"operation": "get_build_profile", "profile_id": "../other"},
        {"operation": "start_workflow_build", "commit_id": "123e4567-e89b-12d3-a456-426614174000"},
        {"operation": "list_build_profiles", "page": 0},
        {"operation": "list_build_profiles", "url": "https://evil.example"},
        {"operation": "create_testing_group", "name": "QA"},
    ]:
        with pytest.raises(ValueError):
            native.AppcircleNode.parse_config({"config": config, "credentials": cred.model_dump()})
