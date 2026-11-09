"""Exercise Turbot Pipes through the actual discovered node and HTTP transport.

Synthetic fixtures cover every supported endpoint, opaque cursors, API errors,
partial query results, credential shaping and uncertain mutation outcomes.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import turbot_pipes_node as native
from nodes.core.credential_connect import shape_credential
from nodes.core.registry import NODE_REGISTRY, NodeFactory

TOKEN = "synthetic-pipes-test-token-42"
CASES = json.loads((Path(__file__).parent / "fixtures/turbot-pipes/requests.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="pipes-test", node_type=native.TurbotPipesNode.integration_type,
        node_data={"config": config, "credentials": {"credential_type": native.FAMILY, "api_token": TOKEN}})


def mock(monkeypatch, reply):
    requests = []

    def respond(request):
        requests.append(request)
        return reply(request)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["config"]["operation"])
async def test_turbot_pipes_all_operations_on_native_factory(monkeypatch, case):
    action = case["config"]["operation"]

    def respond(request):
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        assert request.url.host == "pipes.turbot.com"
        assert request.method == case["method"]
        assert request.url.path == "/api/v0" + case["path"]
        assert dict(request.url.params) == case["params"]
        actual_body = json.loads(request.content) if request.content else None
        assert actual_body == case["body"]
        data = {"id": "resource-42", "handle": "production", "config": {"password": "sensitive"}, "tokens": [TOKEN]}
        if action.startswith("list_"):
            return httpx.Response(200, json={"items": [data], "next_token": "cursor+next"})
        if case["method"] == "DELETE":
            return httpx.Response(204)
        return httpx.Response(201 if case["method"] == "POST" else 200, json=data)

    requests = mock(monkeypatch, respond)
    output = await node(case["config"]).execute({})
    assert output["status"] == "success"
    assert len(requests) == 1
    assert TOKEN not in str(output) and "sensitive" not in str(output)
    if action.startswith("list_"):
        assert output["next_token"] == "cursor+next" and output["has_more"]
    if case["method"] == "DELETE":
        assert output["deletion_acknowledged"] is True


@pytest.mark.asyncio
async def test_turbot_pipes_query_partial_results_and_provider_json(monkeypatch):
    payload = {"columns": [{"name": "name", "data_type": "text"}], "rows": [{"name": "bucket"}]}
    requests = mock(monkeypatch, lambda request: httpx.Response(206, json=payload))
    output = await node({"operation": "query_workspace", "org_handle": "acme", "workspace_handle": "production", "sql": "select name from aws_s3_bucket"}).execute({})
    assert output["partial"] is True and output["data"] == payload
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_turbot_pipes_http_success_with_query_error_envelope(monkeypatch):
    mock(monkeypatch, lambda request: httpx.Response(200, json={"status": 400, "detail": "SQL syntax error"}))
    output = await node({"operation": "query_workspace", "org_handle": "acme", "workspace_handle": "production", "sql": "bad sql"}).execute({})
    assert output["status"] == "error" and output["message"] == "SQL syntax error"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_turbot_pipes_provider_errors_redacted_and_no_retry(monkeypatch, status):
    requests = mock(monkeypatch, lambda request: httpx.Response(status,
        headers={"location": "https://elsewhere.example"}, json={"detail": "Rejected " + TOKEN}))
    output = await node({"operation": "list_workspaces"}).execute({})
    assert output["status"] == "error" and output["http_status"] == status
    assert output["status_code"] == status
    assert output["message"] == "Rejected [redacted]" and len(requests) == 1


@pytest.mark.asyncio
async def test_turbot_pipes_empty_evidence_and_malformed_envelopes(monkeypatch):
    mock(monkeypatch, lambda request: httpx.Response(200, json={"items": []}))
    output = await node({"operation": "list_workspaces"}).execute({})
    assert output["status"] == "success" and not output["has_more"]
    for payload in ({}, {"items": {}}, {"items": ["bad"]}, {"items": [], "next_token": 12}):
        mock(monkeypatch, lambda request: httpx.Response(200, json=payload))
        output = await node({"operation": "list_workspaces"}).execute({})
        assert output["status"] == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "html", "server"])
async def test_turbot_pipes_mutation_unknown_outcome_never_retried(monkeypatch, failure):
    def respond(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("sensitive " + TOKEN, request=request)
        if failure == "html":
            return httpx.Response(200, text="<html>gateway</html>")
        return httpx.Response(503, json={"title": "Unavailable"})

    requests = mock(monkeypatch, respond)
    output = await node({"operation": "create_workspace", "org_handle": "acme", "handle": "production"}).execute({})
    assert output["status"] == "error" and output["write_outcome"] == "unknown"
    assert TOKEN not in str(output) and len(requests) == 1


@pytest.mark.parametrize("field,value", [("org_handle", "../../evil"), ("workspace_handle", "prod/other"),
    ("schema_name", "a?query=1"), ("table_name", "../table")])
def test_turbot_pipes_path_injection_rejected(field, value):
    config = {"operation": "get_table", "org_handle": "acme", "workspace_handle": "production",
              "schema_name": "aws", "table_name": "aws_s3_bucket", field: value}
    assert native.TurbotPipesNode.validate_config({"config": config})["valid"] is False


def test_turbot_pipes_credential_is_manual_and_evidence_resolves():
    shaped, errors, resolved = shape_credential(native.FAMILY, {"api_token": "  " + TOKEN + "  "})
    assert not errors and shaped["api_token"] == TOKEN
    assert native.TurbotPipesAPITokenCredential.model_validate(shaped).credential_type == native.FAMILY
    assert resolved == ("automation-turbot-pipes", native.TurbotPipesAPITokenCredential)
    assert NODE_REGISTRY["automation-turbot-pipes"] is native.TurbotPipesNode
    assert native.TurbotPipesNode.connection_evidence.operation == "list_workspaces"
    assert node({"operation": "list_workspaces"}).config.config.limit == 25
    for value in ("Bearer " + TOKEN, "https://example.com/token", "<token>", "bad\r\nheader"):
        with pytest.raises(ValidationError):
            native.TurbotPipesAPITokenCredential(api_token=value)


def test_turbot_pipes_mutations_require_changes_and_configuration_object():
    for config in (
        {"operation": "update_workspace", "org_handle": "acme", "workspace_handle": "production"},
        {"operation": "create_connection", "org_handle": "acme", "workspace_handle": "production", "handle": "aws", "plugin": "aws", "plugin_config_json": "[]"},
    ):
        assert native.TurbotPipesNode.validate_config({"config": config})["valid"] is False
