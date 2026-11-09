"""Synthetic transport tests of Teamcamp's pinned v1.0 public API contract."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import teamcamp_node as native
from nodes.core.credential_connect import shape_credential
from nodes.core.registry import NODE_REGISTRY, NodeFactory

TOKEN = "synthetic-teamcamp-key-42"
PROJECT = "project_1234567890"
TASK = "task_1234567890"
FIXTURE = Path(__file__).parent / "fixtures/teamcamp/responses.json"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="teamcamp-test", node_type="automation-teamcamp",
        node_data={"config": config, "credentials": {"credential_type": "teamcamp_api_key", "api_key": TOKEN}})


def transport(monkeypatch, payload, status=200, content_type="application/json"):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=payload, headers={"content-type": content_type})
    def client(**kwargs):
        assert kwargs == {"timeout": 30, "trust_env": False, "follow_redirects": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [
    ("check_connection", {}, "GET", "https://api.teamcamp.app/v1.0/verify", None, None),
    ("list_projects", {}, "GET", "https://api.teamcamp.app/v1.0/project", None, None),
    ("get_project", {"projectId": PROJECT}, "GET", f"https://api.teamcamp.app/v1.0/project/{PROJECT}", None, None),
    ("get_project_details", {"projectId": PROJECT}, "GET", f"https://back.teamcamp.app/api/v1/project/{PROJECT}/getCurrentProjectDetails", None, None),
    ("list_project_groups", {"projectId": PROJECT}, "GET", f"https://api.teamcamp.app/v1.0/project/{PROJECT}/group", None, None),
    ("create_project", {"projectName": "Launch", "startDate": "2026-11-09", "templateId": "template_01"}, "POST", "https://api.teamcamp.app/v1.0/project", None, {"projectName": "Launch", "startDate": "2026-11-09", "templateId": "template_01"}),
    ("update_project", {"projectId": PROJECT, "priority": False, "estimate": True, "description": ""}, "PUT", f"https://api.teamcamp.app/v1.0/project/{PROJECT}", None, {"priority": False, "estimate": True}),
    ("delete_project", {"projectId": PROJECT}, "DELETE", f"https://api.teamcamp.app/v1.0/project/{PROJECT}", None, None),
    ("list_users", {}, "GET", "https://api.teamcamp.app/v1.0/company/users", None, None),
    ("list_customers", {}, "GET", "https://api.teamcamp.app/v1.0/company/customers", None, None),
    ("list_tasks", {"projectId": PROJECT, "complete": False}, "GET", "https://api.teamcamp.app/v1.0/task", {"projectId": PROJECT, "complete": "false"}, None),
    ("get_task", {"taskId": TASK}, "GET", f"https://api.teamcamp.app/v1.0/task/{TASK}", None, None),
    ("create_task", {"projectId": PROJECT, "name": "Ship", "priority": 0, "taskUsers": ["user_1"], "files": [{"name": "Notes", "href": "https://files.example.test/notes"}]}, "POST", "https://api.teamcamp.app/v1.0/task", None, {"projectId": PROJECT, "name": "Ship", "priority": 0, "taskUsers": ["user_1"], "files": [{"name": "Notes", "href": "https://files.example.test/notes"}]}),
    ("update_task", {"taskId": TASK, "projectId": PROJECT, "statusId": "status_2", "taskUsers": []}, "PUT", f"https://back.teamcamp.app/api/v1/task/updateTask/{TASK}", None, {"projectId": PROJECT, "statusId": "status_2", "taskUsers": []}),
    ("post_comment", {"taskId": TASK, "content": "Ready to ship"}, "POST", f"https://api.teamcamp.app/v1.0/task/{TASK}/comments", None, {"content": "Ready to ship"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,url,params,body", CASES)
async def test_teamcamp_one_documented_request(monkeypatch, operation, config, method, url, params, body):
    payload = json.loads(FIXTURE.read_text())[operation]
    requests = transport(monkeypatch, payload, status=204 if operation == "delete_project" else 200)
    result = await node({"operation": operation, **config}).execute({})
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert str(request.url.copy_with(query=None)) == url
    assert dict(request.url.params) == (params or {})
    assert request.headers["apiKey"] == TOKEN
    assert "authorization" not in request.headers
    assert (json.loads(request.content) if request.content else None) == body
    assert result["status"] == "success"
    assert result["data"] == payload
    if operation == "delete_project":
        assert result["deleted_project_id"] == PROJECT


def test_teamcamp_discovery_and_hand_connect():
    assert NODE_REGISTRY["automation-teamcamp"] is native.TeamcampNode
    shaped, errors, resolved = shape_credential("teamcamp_api_key", {"api_key": " " + TOKEN + " "})
    assert not errors and resolved is not None
    assert native.TeamcampAPIKeyCredential.model_validate(shaped).credential_type == "teamcamp_api_key"
    assert shaped["api_key"] == TOKEN
    assert native.TeamcampNode.connection_evidence.operation == "list_projects"
    assert native.TeamcampNode.connection_evidence.identity_operation == "check_connection"


@pytest.mark.parametrize("key", ["https://example.test/key", "<token>", "bad\r\nkey", "key with spaces"])
def test_teamcamp_bad_key(key):
    with pytest.raises((ValueError, ValidationError)):
        native.TeamcampAPIKeyCredential(api_key=key)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 403, 404, 429, 500])
async def test_teamcamp_http_failure_is_not_success_or_retried(monkeypatch, status):
    requests = transport(monkeypatch, {"error": "Provider rejected " + TOKEN}, status=status)
    with pytest.raises(ValueError) as exc:
        await node({"operation": "create_project", "projectName": "Launch"}).execute({})
    assert TOKEN not in str(exc.value)
    assert str(status) in str(exc.value)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_teamcamp_error_envelope_and_response_secret_redaction(monkeypatch):
    transport(monkeypatch, {"error": "Invalid key: " + TOKEN})
    with pytest.raises(ValueError, match="Invalid key") as exc:
        await node({"operation": "list_projects"}).execute({})
    assert TOKEN not in str(exc.value)
    transport(monkeypatch, [{"projectName": "Secret " + TOKEN}])
    assert TOKEN not in str(await node({"operation": "list_projects"}).execute({}))


@pytest.mark.asyncio
async def test_teamcamp_company_responses_preserve_singleton_and_list(monkeypatch):
    # Preserve the declared singleton and tolerate a collection without dropping records.
    for payload in ({"id": "user_1", "name": "Ada"}, [{"id": "user_1", "name": "Ada"}], []):
        transport(monkeypatch, payload)
        assert (await node({"operation": "list_users"}).execute({}))["data"] == payload


@pytest.mark.asyncio
async def test_teamcamp_list_tasks_omits_unset_filter(monkeypatch):
    requests = transport(monkeypatch, [])
    await node({"operation": "list_tasks", "projectId": PROJECT}).execute({})
    assert dict(requests[0].url.params) == {"projectId": PROJECT}
    requests = transport(monkeypatch, [])
    await node({"operation": "list_tasks", "projectId": PROJECT, "complete": True}).execute({})
    assert requests[0].url.params["complete"] == "true"


@pytest.mark.asyncio
@pytest.mark.parametrize("payload,content_type", [("not an object", "application/json"), ({}, "text/html")])
async def test_teamcamp_unexpected_response(monkeypatch, payload, content_type):
    transport(monkeypatch, payload, content_type=content_type)
    with pytest.raises(ValueError):
        await node({"operation": "list_projects"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "get_project", "projectId": "../../bad"},
    {"operation": "get_task", "taskId": "short"},
    {"operation": "post_comment", "taskId": TASK},
    {"operation": "create_task", "name": "Missing project"},
    {"operation": "update_task", "projectId": PROJECT, "taskId": TASK},
    {"operation": "update_project", "projectId": PROJECT},
    {"operation": "create_task", "projectId": PROJECT, "name": "Bad priority", "priority": 5},
    {"operation": "create_project", "projectName": "Bad date", "dueDate": "not-a-date"},
])
def test_teamcamp_invalid_configs(config):
    with pytest.raises(ValueError):
        node(config)


@pytest.mark.asyncio
async def test_teamcamp_write_timeout_has_one_attempt(monkeypatch):
    requests = []
    def reply(request):
        requests.append(request)
        raise httpx.ReadTimeout("synthetic timeout", request=request)
    monkeypatch.setattr(native, "guarded_async_client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(reply), **kw))
    with pytest.raises(ValueError, match="inspect any write before retrying"):
        await node({"operation": "post_comment", "taskId": TASK, "content": "Ship"}).execute({})
    assert len(requests) == 1
