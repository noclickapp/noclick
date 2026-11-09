"""Pneumatic wire-contract regressions; synthetic credentials, no live account."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import pneumatic_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory

TOKEN = "synthetic-pneumatic-key-42"
AUTH = {"credential_type": "pneumatic_api_key", "api_key": TOKEN}
DATE = "2027-01-10T12:00:00Z"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="pneumatic-fixture", node_type="automation-pneumatic",
        node_data={"config": config, "credentials": AUTH})


@pytest.fixture
def transport(monkeypatch):
    requests, responses = [], []
    def respond(request):
        requests.append(request)
        return responses.pop(0)
    def client(**kwargs):
        assert kwargs == {"timeout": 30, "follow_redirects": False, "trust_env": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests, responses


# Independent expected HTTP methods and paths, rather than deriving from the node table.
CASES = [
    ("get_account", {}, "GET", "/accounts/account"),
    ("list_users", {}, "GET", "/accounts/users"),
    ("get_user", {"user_id": 7}, "GET", "/accounts/users/7"),
    ("list_groups", {}, "GET", "/accounts/groups"),
    ("get_group", {"group_id": 7}, "GET", "/accounts/groups/7"),
    ("list_templates", {}, "GET", "/templates"),
    ("get_template", {"template_id": 7}, "GET", "/templates/7"),
    ("get_template_fields", {"template_id": 7}, "GET", "/templates/7/fields"),
    ("list_template_steps", {"template_id": 7}, "GET", "/templates/7/steps"),
    ("run_workflow", {"template_id": 7, "name": "Onboard customer", "kickoff": {"customer": "Example"}}, "POST", "/templates/7/run"),
    ("list_workflows", {}, "GET", "/workflows"),
    ("get_workflow", {"workflow_id": 7}, "GET", "/workflows/7"),
    ("update_workflow", {"workflow_id": 7, "is_urgent": False}, "PATCH", "/workflows/7"),
    ("comment_workflow", {"workflow_id": 7, "text": "Customer approved"}, "POST", "/workflows/7/comment"),
    ("list_workflow_events", {"workflow_id": 7}, "GET", "/workflows/7/events"),
    ("snooze_workflow", {"workflow_id": 7, "date": DATE}, "POST", "/workflows/7/snooze"),
    ("list_tasks", {}, "GET", "/v3/tasks"),
    ("get_task", {"task_id": "task-7"}, "GET", "/v2/tasks/task-7"),
    ("comment_task", {"task_id": "task-7", "text": "Ready"}, "POST", "/v2/tasks/task-7/comment"),
    ("complete_task", {"task_id": "task-7", "output": {"approved": True}}, "POST", "/v2/tasks/task-7/complete"),
    ("set_task_due_date", {"task_id": "task-7", "due_date_tsp": DATE}, "POST", "/v2/tasks/task-7/due-date"),
    ("clear_task_due_date", {"task_id": "task-7"}, "DELETE", "/v2/tasks/task-7/due-date"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path", CASES)
async def test_each_operation_uses_one_published_route(transport, operation, config, method, path):
    requests, replies = transport
    payload = {"id": 7, "name": "Example"}
    replies.append(httpx.Response(200, json=payload))
    result = await node({"operation": operation, **config}).execute({})
    assert result == {"status": "success", "operation": operation, "data": payload}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == path
    assert request.url.host == "api.pneumatic.app"
    assert request.headers["authorization"] == "Bearer " + TOKEN
    assert TOKEN not in str(request.url) and TOKEN not in request.content.decode()
    if method in {"POST", "PATCH"}:
        assert json.loads(request.content) == {k: v for k, v in config.items() if not k.endswith("_id")}
    if method == "DELETE":
        assert not request.content


@pytest.mark.asyncio
async def test_pagination_and_false_filters_are_preserved_without_following_next(transport):
    requests, replies = transport
    payload = json.loads((Path(__file__).parent / "fixtures/pneumatic/tasks-page.json").read_text())
    replies.append(httpx.Response(200, json=payload))
    result = await node({"operation": "list_tasks", "limit": 2, "offset": 4, "is_completed": False}).execute({})
    assert result["data"] == payload
    assert len(requests) == 1
    assert dict(requests[0].url.params) == {"limit": "2", "offset": "4", "is_completed": "false"}


@pytest.mark.asyncio
async def test_explicit_choice_clears_workflow_due_date(transport):
    requests, replies = transport
    replies.append(httpx.Response(200, json={"id": 7}))
    await node({"operation": "update_workflow", "workflow_id": 7, "clear_due_date": True}).execute({})
    assert json.loads(requests[0].content) == {"due_date_tsp": None}


@pytest.mark.asyncio
async def test_empty_success_and_http_error_are_distinct(transport):
    requests, replies = transport
    replies.append(httpx.Response(204))
    assert (await node({"operation": "clear_task_due_date", "task_id": "7"}).execute({}))["data"] is None
    replies.append(httpx.Response(401, json={"detail": "Invalid token."}))
    with pytest.raises(httpx.HTTPStatusError):
        await node({"operation": "get_account"}).execute({})
    assert len(requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(200, text="<html>Login</html>"), httpx.Response(200, json="bad"), httpx.Response(200, json={}), httpx.Response(200, content=b""), httpx.Response(200, content=b"x" * 5_000_001)])
async def test_unexpected_responses_fail(transport, response):
    transport[1].append(response)
    with pytest.raises(ValueError):
        await node({"operation": "get_account"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "get_task", "task_id": "../other"},
    {"operation": "get_workflow", "workflow_id": 0},
    {"operation": "snooze_workflow", "workflow_id": 7, "date": "tomorrow"},
    {"operation": "set_task_due_date", "task_id": "7", "due_date_tsp": "2027-01-10T12:00:00"},
    {"operation": "list_tasks", "limit": 101},
])
def test_invalid_config_fails_before_request(config):
    assert not native.PneumaticNode.validate_config({"config": config, "credentials": AUTH})["valid"]


def test_credential_default_and_evidence_are_discoverable():
    assert NODE_REGISTRY["automation-pneumatic"] is native.PneumaticNode
    assert native.PneumaticAPIKeyCredential(api_key=TOKEN).credential_type == "pneumatic_api_key"
    assert native.PneumaticNode.connection_evidence.identity_operation == "get_account"
    with pytest.raises(ValidationError):
        native.PneumaticAPIKeyCredential(api_key="Bearer pasted-header")
