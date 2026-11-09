"""Offline Langfuse request, authentication, parser and failure regressions."""
import base64
import json

import httpx
import pytest
from pydantic import ValidationError

from nodes import langfuse_node as native
from nodes.core.registry import NodeFactory

CREDS = {"credential_type": native.FAMILY, "public_key": "pk-lf-test", "secret_key": "sk-lf-test"}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, **credential):
    return NodeFactory.create_node(node_id="langfuse-test", node_type="automation-langfuse",
        node_data={"config": config, "credentials": {**CREDS, **credential}})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body) if status != 204 else httpx.Response(status)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [
    ({"operation": "list_projects"}, "GET", "/api/public/projects", {}, None),
    ({"operation": "list_prompts", "name": "support"}, "GET", "/api/public/v2/prompts", {"page": "1", "limit": "50", "name": "support"}, None),
    ({"operation": "get_prompt", "prompt_name": "folder/a + b", "label": "production"}, "GET", "/api/public/v2/prompts/folder%2Fa%20%2B%20b", {"label": "production"}, None),
    ({"operation": "create_text_prompt", "name": "support", "prompt": "Be helpful", "commit_message": "Initial"}, "POST", "/api/public/v2/prompts", {}, {"name": "support", "prompt": "Be helpful", "type": "text", "commitMessage": "Initial"}),
    ({"operation": "update_prompt_labels", "name": "support", "version": 2, "new_labels_json": '["production"]'}, "PATCH", "/api/public/v2/prompts/support/versions/2", {}, {"newLabels": ["production"]}),
    ({"operation": "list_datasets", "page": 2}, "GET", "/api/public/v2/datasets", {"page": "2", "limit": "50"}, None),
    ({"operation": "get_dataset", "dataset_name": "evals/test"}, "GET", "/api/public/v2/datasets/evals%2Ftest", {}, None),
    ({"operation": "create_dataset", "name": "evals", "description": "Evaluation"}, "POST", "/api/public/v2/datasets", {}, {"name": "evals", "description": "Evaluation"}),
    ({"operation": "list_dataset_items", "dataset_name": "evals", "source_trace_id": "trace"}, "GET", "/api/public/dataset-items", {"page": "1", "limit": "50", "datasetName": "evals", "sourceTraceId": "trace"}, None),
    ({"operation": "get_dataset_item", "item_id": "item"}, "GET", "/api/public/dataset-items/item", {}, None),
    ({"operation": "upsert_dataset_item", "dataset_name": "evals", "item_id": "item", "input_json": '{"question":"Hi"}', "expected_output_json": '"Hello"'}, "POST", "/api/public/dataset-items", {}, {"datasetName": "evals", "id": "item", "input": {"question": "Hi"}, "expectedOutput": "Hello", "status": "ACTIVE"}),
    ({"operation": "delete_dataset_item", "item_id": "item"}, "DELETE", "/api/public/dataset-items/item", {}, None),
    ({"operation": "list_observations", "trace_id": "trace", "cursor": "cursor", "from_start_time": "2026-01-01T00:00:00Z"}, "GET", "/api/public/v2/observations", {"limit": "50", "cursor": "cursor", "traceId": "trace", "fromStartTime": "2026-01-01T00:00:00Z"}, None),
    ({"operation": "list_scores", "name": "quality"}, "GET", "/api/public/v3/scores", {"limit": "50", "name": "quality"}, None),
    ({"operation": "delete_score", "score_id": "score"}, "DELETE", "/api/public/scores/score", {}, None),
    ({"operation": "list_comments", "object_type": "trace", "object_id": "trace"}, "GET", "/api/public/comments", {"page": "1", "limit": "50", "objectType": "trace", "objectId": "trace"}, None),
    ({"operation": "get_comment", "comment_id": "comment"}, "GET", "/api/public/comments/comment", {}, None),
    ({"operation": "create_comment", "project_id": "project", "object_type": "trace", "object_id": "trace", "content": "Review"}, "POST", "/api/public/comments", {}, {"projectId": "project", "objectType": "trace", "objectId": "trace", "content": "Review"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,query,body", CASES)
async def test_all_contract_routes_and_bodies(monkeypatch, config, method, path, query, body):
    response = {"data": [{"id": "project", "name": "My project"}], "meta": {"page": 1, "totalPages": 3}} if config["operation"].startswith("list_") else {"id": "result", "message": "Deleted"}
    if config["operation"] in {"get_prompt", "create_text_prompt", "update_prompt_labels"}:
        response = {"name": "support", "version": 1, "type": "text", "prompt": "Be helpful", "labels": [], "tags": [], "config": {}}
    status = 204 if config["operation"] == "delete_score" else 200
    requests = transport(monkeypatch, response, status)
    result = await node(config).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert request.url.raw_path.decode().split("?")[0] == path
    assert dict(request.url.params) == query
    assert (json.loads(request.content) if request.content else None) == body
    assert request.headers["authorization"] == "Basic " + base64.b64encode(b"pk-lf-test:sk-lf-test").decode()
    assert CREDS["secret_key"] not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("region,host", list(native.HOSTS.items()))
async def test_regional_host_and_recognizable_connection_evidence(monkeypatch, region, host):
    requests = transport(monkeypatch, {"data": [{"id": "project", "name": "My project"}]})
    result = await node({"operation": "list_projects"}, region=region).run({})
    assert result["data"][0]["name"] == "My project"
    assert str(requests[0].url).startswith(host + "/")
    assert native.LangfuseNode.connection_evidence.operation == "list_projects"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["list_observations", "list_scores"])
async def test_empty_cursor_page_preserved(monkeypatch, operation):
    transport(monkeypatch, {"data": [], "meta": {"cursor": "continue-even-empty"}})
    result = await node({"operation": operation}).run({})
    assert result["status"] == "success" and result["meta"]["cursor"] == "continue-even-empty"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [202, 207, 301, 400, 401, 403, 404, 429, 500])
async def test_unconfirmed_status_fails_and_secrets_do_not_escape(monkeypatch, status):
    requests = transport(monkeypatch, {"message": CREDS["secret_key"]}, status)
    result = await node({"operation": "list_projects"}).run({})
    assert result["status"] == "error" and result["http_status"] == status
    assert CREDS["secret_key"] not in str(result) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, [], {"data": {}}, {"data": [], "error": "failed"}])
async def test_bad_envelope_not_success(monkeypatch, body):
    transport(monkeypatch, body)
    assert (await node({"operation": "list_projects"}).run({}))["status"] == "error"


@pytest.mark.parametrize("config", [
    {"operation": "list_datasets", "page": 0},
    {"operation": "list_scores", "limit": 101},
    {"operation": "get_prompt", "prompt_name": "test", "version": 1, "label": "production"},
    {"operation": "update_prompt_labels", "name": "test", "version": 1, "new_labels_json": '["latest"]'},
    {"operation": "update_prompt_labels", "name": "test", "version": 1, "new_labels_json": '{}'},
    {"operation": "upsert_dataset_item", "dataset_name": "test", "input_json": "bad JSON"},
    {"operation": "list_comments", "object_id": "trace"},
    {"operation": "list_observations", "from_start_time": "2026-01-01"},
    {"operation": "list_observations", "from_start_time": "2026-01-02T00:00:00Z", "to_start_time": "2026-01-01T00:00:00Z"},
])
def test_invalid_config_refused(config):
    with pytest.raises(ValueError):
        native.LangfuseNode.parse_config({"config": config, "credentials": CREDS})


def test_credential_default_and_manual_fields():
    assert native.LangfuseAPIKeyCredential(public_key=" pk-lf-test ", secret_key=" sk-lf-test ").credential_type == native.FAMILY
    for bad in ["https://example.com/key", "key:password", "Bearer token"]:
        with pytest.raises(ValidationError):
            native.LangfuseAPIKeyCredential(public_key=bad, secret_key="sk-lf-test")
    with pytest.raises(ValidationError):
        native.LangfuseAPIKeyCredential(**{**CREDS, "region": "https://attacker.test"})


@pytest.mark.asyncio
async def test_item_status_preserved_inside_provider_record(monkeypatch):
    transport(monkeypatch, {"id": "item", "status": "ARCHIVED"})
    result = await node({"operation": "get_dataset_item", "item_id": "item"}).run({})
    assert result["status"] == "success" and result["data"]["status"] == "ARCHIVED"


@pytest.mark.asyncio
async def test_rejection_keeps_provider_words_for_connect(monkeypatch):
    transport(monkeypatch, {"message": "Invalid public key"}, 401)
    result = await node({"operation": "list_projects"}).run({})
    assert result["status"] == "error" and result["error"] == "Invalid public key"


@pytest.mark.asyncio
async def test_chat_prompt_uses_name_and_version_not_id(monkeypatch):
    body = {"name": "chat", "version": 1, "type": "chat", "prompt": [{"role": "user", "content": "Hello"}], "labels": [], "tags": [], "config": {}}
    transport(monkeypatch, body)
    result = await node({"operation": "get_prompt", "prompt_name": "chat"}).run({})
    assert result["status"] == "success" and result["data"] == body


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body,outcome", [
    (200, {"message": "Accepted"}, "accepted"),
    (202, {"message": "Accepted"}, "accepted"),
    (207, {"accepted": 1, "rejected": 1, "errors": [{"message": "Invalid score"}]}, "partial"),
    (207, {"accepted": 0, "rejected": 1, "errors": [{"message": "Invalid score"}]}, "error"),
])
async def test_numeric_score_is_array_and_acceptance_is_not_completion(monkeypatch, status, body, outcome):
    requests = transport(monkeypatch, body, status)
    result = await node({"operation": "create_score", "trace_id": "trace", "name": "quality", "value": 0.9, "score_id": "score"}).run({})
    assert requests[0].method == "POST" and requests[0].url.path == "/api/public/scores"
    assert json.loads(requests[0].content) == [{"traceId": "trace", "name": "quality", "value": 0.9, "id": "score", "dataType": "NUMERIC"}]
    assert result["status"] == outcome and result["processing_complete"] is False
    assert result["retry_automatically"] is False and len(requests) == 1
