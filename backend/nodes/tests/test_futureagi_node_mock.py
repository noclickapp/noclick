"""Provider-published request/response examples plus transport failure regressions."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import futureagi_node as native
from nodes.core.registry import NodeFactory

FIXTURES = json.loads((Path(__file__).parent / "fixtures/futureagi/documented.json").read_text())
CREDENTIAL = {"credential_type": "futureagi_api_key", "api_key": "synthetic-api-key"}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="futureagi-fixture", node_type="automation-futureagi",
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, response):
    requests = []
    def respond(request):
        requests.append(request)
        return response
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", sorted(FIXTURES))
async def test_published_examples_exact_request_and_unmodified_response(monkeypatch, operation):
    fixture = FIXTURES[operation]
    response = httpx.Response(204) if fixture["body"] is None else httpx.Response(200, json=fixture["body"])
    requests = transport(monkeypatch, response)
    result = await node(fixture["config"]).execute({})
    assert result == {"status": "success", "data": fixture["body"]}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == fixture["method"]
    assert request.url.host == "api.futureagi.com"
    assert request.url.path == fixture["path"].replace("{id}", fixture["config"].get("id", ""))
    assert request.headers["Authorization"] == "Bearer " + CREDENTIAL["api_key"]
    config = node(fixture["config"]).config.config.model_dump(exclude={"operation", "id"}, exclude_none=True)
    if request.method == "GET":
        assert dict(request.url.params) == {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in config.items()}
        assert request.content == b""
    elif config:
        assert json.loads(request.content) == config
    else:
        assert not request.content


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 403, 429, 500])
async def test_provider_rejection_and_redirect_never_succeed(monkeypatch, status):
    requests = transport(monkeypatch, httpx.Response(status, text="Rejected synthetic-api-key"))
    with pytest.raises(ValueError, match=f"Futureagi HTTP {status}") as error:
        await node({"operation": "list_queues"}).execute({})
    assert "synthetic-api-key" not in str(error.value)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_empty_delete_response(monkeypatch):
    transport(monkeypatch, httpx.Response(204))
    result = await node({"operation": "delete_score", "id": "score-id"}).execute({})
    assert result["data"] is None


@pytest.mark.asyncio
async def test_error_envelope_rejected_and_bulk_partial_errors_preserved(monkeypatch):
    transport(monkeypatch, httpx.Response(200, json={"error": "Invalid credentials"}))
    with pytest.raises(ValueError, match="Invalid credentials"):
        await node({"operation": "list_queues"}).execute({})
    body = {"scores": [], "errors": ["Invalid label"]}
    transport(monkeypatch, httpx.Response(201, json=body))
    result = await node(FIXTURES["bulk_create_scores"]["config"]).execute({})
    assert result["data"] == body


@pytest.mark.parametrize("resource", ["../admin", "id/path", "id?query", "https://evil.test", "id#fragment"])
def test_path_injection_rejected(resource):
    with pytest.raises(ValidationError):
        native.GetQueue(id=resource)


def test_manual_connect_defaults_and_required_secret_fields():
    credential = native.FutureagiAPIKeyCredential(api_key="synthetic-api-key")
    assert credential.credential_type == "futureagi_api_key"
    assert native.FutureagiNode.connection_evidence.operation == "list_queues"
    with pytest.raises(ValidationError):
        native.FutureagiAPIKeyCredential()
