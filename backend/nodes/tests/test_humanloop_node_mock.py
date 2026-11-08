"""Humanloop v5 regressions use fake credentials and offline HTTP responses."""
import json

import httpx
import pytest
from pydantic import ValidationError

from nodes import humanloop_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-humanloop-key"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="humanloop-test", node_type="automation-humanloop",
        node_data={"config": config, "credentials": {"credential_type": "humanloop_api_key", "api_key": TOKEN}})


def transport(monkeypatch, body=None, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        assert kwargs["timeout"] == 30.0
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
async def test_humanloop_account_evidence_page_and_next_page(monkeypatch):
    body = {"records": [{"id": "pr_123", "name": "Support", "path": "support"}], "page": 2, "size": 10, "total": 21}
    requests = transport(monkeypatch, body)
    result = await node({"operation": "list_prompts", "page": 2, "name": "Support + QA", "order": "desc"}).execute({})
    assert result["data"] == body["records"] and result["next_page"] == 3
    assert result["has_more"] is True and len(requests) == 1
    request = requests[0]
    assert request.url.host == "api.humanloop.com" and request.url.path == "/v5/prompts"
    assert request.headers["X-API-KEY"] == TOKEN and "authorization" not in request.headers
    assert dict(request.url.params) == {"page": "2", "size": "10", "name": "Support + QA", "order": "desc"}
    assert request.content == b""
    assert native.HumanloopNode.connection_evidence.operation == "list_prompts"


@pytest.mark.asyncio
async def test_humanloop_empty_terminal_page(monkeypatch):
    transport(monkeypatch, {"records": [], "page": 1, "size": 10, "total": 0})
    result = await node({"operation": "list_datasets"}).execute({})
    assert result["data"] == [] and result["next_page"] is None and not result["has_more"]


@pytest.mark.asyncio
async def test_humanloop_upsert_dataset_body_and_query_are_separate(monkeypatch):
    requests = transport(monkeypatch, {"id": "ds_123", "name": "support"})
    config = {"operation": "upsert_dataset", "path": "examples/support", "action": "add",
        "version_id": "dsv_123", "include_datapoints": True,
        "datapoints": [{"inputs": {"question": "Hello"}, "target": {"answer": "Hi"}}]}
    await node(config).execute({})
    request = requests[0]
    assert request.method == "POST" and request.url.path == "/v5/datasets"
    assert dict(request.url.params) == {"version_id": "dsv_123", "include_datapoints": "true"}
    assert json.loads(request.content) == {"path": "examples/support", "action": "add", "datapoints": config["datapoints"]}


@pytest.mark.asyncio
async def test_humanloop_upsert_prompt_preserves_chat_template(monkeypatch):
    requests = transport(monkeypatch, {"id": "pr_123"})
    template = [{"role": "system", "content": "Be concise"}, {"role": "user", "content": "{{question}}"}]
    await node({"operation": "upsert_prompt", "path": "support", "model": "gpt-4", "template": template,
        "temperature": 0, "max_tokens": 100}).execute({})
    assert json.loads(requests[0].content) == {"path": "support", "model": "gpt-4", "template": template, "temperature": 0, "max_tokens": 100}


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,params,body,response", [
    ({"operation": "get_prompt", "id": "pr_123", "environment": "production"}, "GET", "/v5/prompts/pr_123", {"environment": "production"}, None, {"id": "pr_123"}),
    ({"operation": "move_dataset", "id": "ds_123", "path": "new/name"}, "PATCH", "/v5/datasets/ds_123", {}, {"path": "new/name"}, {"id": "ds_123"}),
    ({"operation": "list_datapoints", "id": "ds_123", "version_id": "dsv_123"}, "GET", "/v5/datasets/ds_123/datapoints", {"page": "1", "size": "10", "version_id": "dsv_123"}, None, {"records": [], "page": 1, "size": 10, "total": 0}),
    ({"operation": "list_logs", "file_id": "pr_123", "search": "hello"}, "GET", "/v5/logs", {"file_id": "pr_123", "page": "1", "size": "10", "search": "hello"}, None, {"records": [], "page": 1, "size": 10, "total": 0}),
    ({"operation": "create_directory", "path": "team/prompts"}, "POST", "/v5/directories", {}, {"path": "team/prompts"}, {"id": "dir_123"}),
    ({"operation": "list_prompt_versions", "id": "pr_123"}, "GET", "/v5/prompts/pr_123/versions", {}, None, {"records": []}),
    ({"operation": "list_directories"}, "GET", "/v5/directories", {}, None, []),
])
async def test_humanloop_fixed_routes(monkeypatch, config, method, path, params, body, response):
    requests = transport(monkeypatch, response)
    assert (await node(config).execute({}))["status"] == "success"
    request = requests[0]
    assert len(requests) == 1 and request.method == method and request.url.path == path
    assert dict(request.url.params) == params
    assert (json.loads(request.content) if request.content else None) == body


@pytest.mark.asyncio
async def test_humanloop_delete_accepts_empty_success(monkeypatch):
    requests = transport(monkeypatch)
    result = await node({"operation": "delete_evaluation", "id": "evr_123"}).execute({})
    assert requests[0].method == "DELETE" and requests[0].content == b""
    assert result["acknowledged"] and "data" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
async def test_humanloop_rejection_is_not_success_or_retried(monkeypatch, status):
    requests = transport(monkeypatch, {"detail": "Provider rejection " + TOKEN}, status)
    with pytest.raises(ValueError) as error:
        await node({"operation": "delete_prompt", "id": "pr_123"}).execute({})
    assert str(status) in str(error.value) and "Provider rejection" in str(error.value)
    assert TOKEN not in str(error.value) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"records": None}, {"records": [], "page": "1", "size": 10, "total": 0}])
async def test_humanloop_invalid_envelopes_are_rejected(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation": "list_prompts"}).execute({})


@pytest.mark.asyncio
async def test_humanloop_redacts_echoed_secret(monkeypatch):
    transport(monkeypatch, {"id": "pr_123", "metadata": {TOKEN: [TOKEN]}})
    assert TOKEN not in str(await node({"operation": "get_prompt", "id": "pr_123"}).execute({}))


@pytest.mark.parametrize("identifier", ["..", "x/y", "x?foo", "x#bar", "x\\y", "x\ny"])
def test_humanloop_path_injection_rejected(identifier):
    with pytest.raises(ValueError):
        node({"operation": "get_prompt", "id": identifier})


def test_humanloop_manual_credential_defaults_and_shape():
    credential = native.HumanloopAPIKeyCredential(api_key="  " + TOKEN + "  ")
    assert credential.credential_type == "humanloop_api_key" and credential.api_key == TOKEN
    with pytest.raises(ValidationError):
        native.HumanloopAPIKeyCredential(api_key="https://example.com/key")
    with pytest.raises(ValidationError):
        native.HumanloopAPIKeyCredential(credential_type="other", api_key=TOKEN)
