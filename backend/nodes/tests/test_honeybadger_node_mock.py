"""Honeybadger v3 wire contracts using synthetic credentials and HTTP responses."""
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import honeybadger_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory

TOKEN = "synthetic-honeybadger-token-42"
PROJECT = "Xk9mZp"
FAULT = "12345"
COMMENT = "Cm7pLx"
NOTICE = "1e2ba1f0-4f3c-4b1a-9c7e-6f2f5c0f1a3b"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, **creds):
    result = NodeFactory.create_node(node_id="honeybadger-test", node_type=native.NODE_TYPE,
        node_data={"config": config, "credentials": {"credential_type": "honeybadger_api_token", "api_token": TOKEN, **creds}})
    result.emit = AsyncMock()
    return result


def mock_http(monkeypatch, body=None, status=200):
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(status, json=body) if status != 204 else httpx.Response(204)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [
    ({"operation": "get_token"}, "GET", "/token", {}, None),
    ({"operation": "get_account"}, "GET", "/account", {}, None),
    ({"operation": "get_account_usage"}, "GET", "/account/usage", {}, None),
    ({"operation": "list_projects", "name": "Billing API", "page": 2, "per_page": 10}, "GET", "/projects", {"name": "Billing API", "page": "2", "per_page": "10"}, None),
    ({"operation": "create_project", "name": "Billing API", "language": "ruby"}, "POST", "/projects", {}, {"name": "Billing API", "language": "ruby", "disable_email_notifications": False}),
    ({"operation": "get_project", "project_id": PROJECT}, "GET", f"/projects/{PROJECT}", {}, None),
    ({"operation": "update_project", "project_id": PROJECT, "disable_public_links": True, "language": None}, "PATCH", f"/projects/{PROJECT}", {}, {"disable_public_links": True, "language": None}),
    ({"operation": "get_project_stats", "project_id": PROJECT}, "GET", f"/projects/{PROJECT}/stats", {}, None),
    ({"operation": "list_faults", "project_id": PROJECT, "q": "environment:production", "order": "recent", "sort": "desc", "occurred_after": 1700000000}, "GET", f"/projects/{PROJECT}/faults", {"q": "environment:production", "order": "recent", "sort": "desc", "occurred_after": "1700000000.0", "page": "1", "per_page": "25"}, None),
    ({"operation": "get_fault", "project_id": PROJECT, "fault_id": FAULT}, "GET", f"/projects/{PROJECT}/faults/{FAULT}", {}, None),
    ({"operation": "update_fault", "project_id": PROJECT, "fault_id": FAULT, "resolved": False, "tags": []}, "PATCH", f"/projects/{PROJECT}/faults/{FAULT}", {}, {"resolved": False, "tags": []}),
    ({"operation": "list_comments", "project_id": PROJECT, "fault_id": FAULT, "before": "older-cursor"}, "GET", f"/projects/{PROJECT}/faults/{FAULT}/comments", {"limit": "25", "before": "older-cursor"}, None),
    ({"operation": "create_comment", "project_id": PROJECT, "fault_id": FAULT, "body": "Rolled back, watching for recurrence."}, "POST", f"/projects/{PROJECT}/faults/{FAULT}/comments", {}, {"body": "Rolled back, watching for recurrence."}),
    ({"operation": "get_comment", "project_id": PROJECT, "fault_id": FAULT, "comment_id": COMMENT}, "GET", f"/projects/{PROJECT}/faults/{FAULT}/comments/{COMMENT}", {}, None),
    ({"operation": "update_comment", "project_id": PROJECT, "fault_id": FAULT, "comment_id": COMMENT, "body": "Resolved."}, "PATCH", f"/projects/{PROJECT}/faults/{FAULT}/comments/{COMMENT}", {}, {"body": "Resolved."}),
    ({"operation": "delete_comment", "project_id": PROJECT, "fault_id": FAULT, "comment_id": COMMENT}, "DELETE", f"/projects/{PROJECT}/faults/{FAULT}/comments/{COMMENT}", {}, None),
    ({"operation": "list_notices", "project_id": PROJECT, "fault_id": FAULT, "breadcrumbs": True}, "GET", f"/projects/{PROJECT}/faults/{FAULT}/notices", {"limit": "25", "unmapped": "false", "breadcrumbs": "true"}, None),
    ({"operation": "get_notice", "uuid": NOTICE}, "GET", f"/notices/{NOTICE}", {"unmapped": "false"}, None),
    ({"operation": "list_deploys", "project_id": PROJECT, "environment": "production", "after": "newer-cursor"}, "GET", f"/projects/{PROJECT}/deploys", {"limit": "25", "after": "newer-cursor", "environment": "production"}, None),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,params,body", CASES, ids=[case[0]["operation"] for case in CASES])
async def test_honeybadger_operation_wire_contract(monkeypatch, config, method, path, params, body):
    status = 204 if method == "DELETE" else 201 if method == "POST" else 200
    response = {"data": [] if config["operation"].startswith("list_") else {"id": PROJECT, "account_id": "Ab3kL9"}, "meta": {"request_id": "request-42"}}
    requests = mock_http(monkeypatch, response, status)
    instance = node(config)
    result = await instance.execute({})
    assert result["status"] == "success"
    assert result["http_status"] == status
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert str(request.url).startswith("https://app.honeybadger.io/v3/")
    assert request.url.path == "/v3" + path
    assert dict(request.url.params) == params
    assert request.headers["authorization"] == "Bearer " + TOKEN
    assert (json.loads(request.content) if request.content else None) == body
    if method == "DELETE":
        assert result["deletion_acknowledged"] is True
    else:
        assert result["data"] == response["data"]
    instance.emit.assert_awaited_once_with(result)


@pytest.mark.asyncio
async def test_honeybadger_eu_empty_page_and_links_not_followed(monkeypatch):
    response = {"data": [], "links": {"next": "https://untrusted.invalid/page"}, "pagination": {"page": 1, "per_page": 25}}
    requests = mock_http(monkeypatch, response)
    result = await node({"operation": "list_projects"}, region="eu").execute({})
    assert requests[0].url.host == "eu-app.honeybadger.io" and len(requests) == 1
    assert result["links"] == response["links"] and result["data"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 403, 404, 422, 429, 500])
async def test_honeybadger_rejection_retains_provider_reason_without_token_or_retry(monkeypatch, status):
    requests = mock_http(monkeypatch, {"error": {"code": "insufficient_scope", "message": "Missing faults:write " + TOKEN}}, status)
    with pytest.raises(ValueError, match="Missing faults:write") as error:
        await node({"operation": "update_fault", "project_id": PROJECT, "fault_id": FAULT, "resolved": True}).execute({})
    assert TOKEN not in str(error.value)
    assert str(status) in str(error.value) and "insufficient_scope" in str(error.value)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"data": {}}, {"data": None}, {"data": "invalid"}, {"data": []}, {"error": {"message": "Denied"}}])
async def test_honeybadger_malformed_single_resource_never_success(monkeypatch, body):
    mock_http(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation": "get_token"}).execute({})


@pytest.mark.asyncio
async def test_honeybadger_token_evidence_and_output_redaction(monkeypatch):
    mock_http(monkeypatch, {"data": {"account_id": "Ab3kL9", "name": TOKEN, "scopes": ["faults:read"]}})
    result = await node({"operation": "get_token"}).execute({})
    assert result["data"]["account_id"] == "Ab3kL9" and TOKEN not in str(result)
    assert native.HoneybadgerNode.connection_evidence.identity_operation == "get_token"
    assert NODE_REGISTRY[native.NODE_TYPE] is native.HoneybadgerNode


@pytest.mark.parametrize("config", [
    {"operation": "get_project", "project_id": "../token"},
    {"operation": "get_project", "project_id": "bad?query"},
    {"operation": "list_projects", "per_page": 101},
    {"operation": "list_deploys", "project_id": PROJECT, "before": "x", "after": "y"},
    {"operation": "create_comment", "project_id": PROJECT, "fault_id": FAULT, "body": ""},
    {"operation": "get_notice", "uuid": "invalid"},
])
def test_honeybadger_invalid_input(config):
    assert native.HoneybadgerNode.validate_config({"config": config, "credentials": {"api_token": TOKEN}})["valid"] is False


@pytest.mark.parametrize("token", ["", "https://example.com/key", "token with spaces", "<token>"])
def test_honeybadger_manual_credential_rejects_bad_secrets(token):
    with pytest.raises((ValidationError, ValueError)):
        native.HoneybadgerAPITokenCredential(api_token=token)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["update_fault", "update_project"])
async def test_honeybadger_empty_update_has_no_request(monkeypatch, operation):
    requests = mock_http(monkeypatch, {"data": {}})
    config = {"operation": operation, "project_id": PROJECT}
    if operation == "update_fault":
        config["fault_id"] = FAULT
    with pytest.raises(ValueError, match="at least one"):
        await node(config).execute({})
    assert requests == []
