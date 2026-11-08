"""Offline factory tests against Process Street's published v1.1 wire shapes."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import process_street_node as provider
from nodes.core.registry import NodeFactory

KEY = "synthetic-process-street-api-key"
ID = "laeBb_tXVTkBobaKyAB7oA"
RUN = "rGDurSofIm8BobaKyO13pQ"
TASK = "m50jWhRkdhcBobaKyO1_Rw"
AUTH = {"credential_type": "process_street_api_key", "api_key": KEY}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id="process-street-test", node_type="automation-process-street",
        node_data={"config": config, "credentials": AUTH if credentials is None else credentials})


@pytest.fixture
def wire(monkeypatch):
    requests, replies = [], []
    def respond(request):
        requests.append(request)
        status, payload = replies.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return httpx.Response(status, json=payload) if payload is not None else httpx.Response(status)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(provider, "guarded_async_client", client)
    return requests, replies


CASES = [
    ("list_workflows", {"name": "Audit"}, "GET", "/workflows", {"name": "Audit"}, None, {"workflows": [{"id": ID, "name": "Audit"}]}),
    ("get_workflow", {"workflow_id": ID}, "GET", f"/workflows/{ID}", {}, None, {"id": ID}),
    ("list_workflow_tasks", {"workflow_id": ID}, "GET", f"/workflows/{ID}/tasks", {}, None, {"tasks": []}),
    ("list_workflow_runs", {"workflow_id": ID, "status": "Active"}, "GET", "/workflow-runs/list", {"workflowId": ID, "status": "Active"}, None, {"data": []}),
    ("create_workflow_run", {"workflow_id": ID, "name": "Project Kickoff", "shared": False}, "POST", "/workflow-runs", {}, {"workflowId": ID, "name": "Project Kickoff", "shared": False}, {"id": RUN}),
    ("get_workflow_run", {"workflow_run_id": RUN}, "GET", f"/workflow-runs/{RUN}", {}, None, {"id": RUN}),
    ("update_workflow_run", {"workflow_run_id": RUN, "name": "Existing Name", "status": "Completed", "shared": False}, "PUT", f"/workflow-runs/{RUN}", {}, {"name": "Existing Name", "status": "Completed", "shared": False}, None),
    ("delete_workflow_run", {"workflow_run_id": RUN}, "DELETE", f"/workflow-runs/{RUN}", {}, None, None),
    ("assign_workflow_run", {"workflow_run_id": RUN, "email": "jane+audit@example.com"}, "POST", f"/workflow-runs/{RUN}/assignees/jane+audit@example.com", {}, None, None),
    ("unassign_workflow_run", {"workflow_run_id": RUN, "email": "jane@example.com"}, "DELETE", f"/workflow-runs/{RUN}/assignees/jane@example.com", {}, None, None),
    ("list_workflow_run_assignees", {"workflow_run_id": RUN}, "GET", f"/workflow-runs/{RUN}/assignees", {}, None, {"assignees": []}),
    ("list_tasks", {"workflow_run_id": RUN}, "GET", f"/workflow-runs/{RUN}/tasks", {}, None, {"tasks": []}),
    ("get_task", {"workflow_run_id": RUN, "task_id": TASK}, "GET", f"/workflow-runs/{RUN}/tasks/{TASK}", {}, None, {"id": TASK, "workflowRunId": RUN}),
    ("update_task", {"workflow_run_id": RUN, "task_id": TASK, "status": "Completed"}, "PUT", f"/workflow-runs/{RUN}/tasks/{TASK}", {}, {"status": "Completed"}, None),
    ("assign_task", {"workflow_run_id": RUN, "task_id": TASK, "email": "jane@example.com"}, "PUT", f"/workflow-runs/{RUN}/tasks/{TASK}/assignees/jane@example.com", {}, None, None),
    ("unassign_task", {"workflow_run_id": RUN, "task_id": TASK, "email": "jane@example.com"}, "DELETE", f"/workflow-runs/{RUN}/tasks/{TASK}/assignees/jane@example.com", {}, None, None),
    ("list_form_fields", {"workflow_id": ID}, "GET", f"/workflows/{ID}/form-fields", {}, None, {"fields": []}),
    ("list_form_field_values", {"workflow_run_id": RUN}, "GET", f"/workflow-runs/{RUN}/form-fields", {}, None, {"fields": []}),
    ("update_form_field_values", {"workflow_run_id": RUN, "fields": [{"id": ID, "values": ["A", "B"]}]}, "POST", f"/workflow-runs/{RUN}/form-fields", {}, {"fields": [{"id": ID, "values": ["A", "B"]}]}, {"fields": []}),
    ("list_comments", {"workflow_run_id": RUN, "task_id": TASK}, "GET", "/comments", {"workflowRunId": RUN, "taskId": TASK}, None, {"data": []}),
    ("create_comment", {"workflow_run_id": RUN, "task_id": TASK, "text": "Verified"}, "POST", "/comments", {}, {"workflowRunId": RUN, "taskId": TASK, "text": "Verified"}, {"id": ID, "text": "Verified"}),
    ("list_users", {}, "GET", "/users", {}, None, {"users": []}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,query,body,payload", CASES)
async def test_process_street_exact_operation_contract(wire, operation, config, method, path, query, body, payload):
    requests, replies = wire
    replies.append((provider.SUCCESS_STATUS.get(operation, 200), payload))
    result = await node({"operation": operation, **config}).execute({})
    assert result["success"] is True and len(requests) == 1 and not replies
    request = requests[0]
    assert request.method == method and request.url.path == "/api/v1.1" + path
    assert request.url.host == "public-api.process.st" and request.headers["X-API-Key"] == KEY
    assert dict(request.url.params) == query
    assert (json.loads(request.content) if request.content else None) == body
    if method != "GET":
        assert result["acknowledged"] and result["readback_verified"] is False
    assert KEY not in json.dumps(result)


@pytest.mark.asyncio
async def test_process_street_cursor_roundtrip_and_evidence(wire):
    requests, replies = wire
    replies.extend([(200, {"workflows": [{"id": ID, "name": "Audit"}], "links": [{"name": "next", "href": provider.BASE + "/workflows?name=Audit&_=opaque%2Bnext", "type": "Api"}]}), (200, {"workflows": [], "links": []})])
    first = await node({"operation": "list_workflows", "name": "Audit"}).execute({})
    assert first["items"][0]["name"] == "Audit" and first["next_cursor"] == "opaque+next" and first["has_more"]
    final = await node({"operation": "list_workflows", "name": "Audit", "page_cursor": first["next_cursor"]}).execute({})
    assert requests[1].url.params["_"] == "opaque+next" and not final["has_more"]
    assert provider.ProcessStreetNode.connection_evidence.operation == "list_workflows"


@pytest.mark.asyncio
@pytest.mark.parametrize("href", ["https://evil.test/api/v1.1/workflows?_=x", provider.BASE + "/users?_=x", provider.BASE + "/workflows?_=x&name=other", provider.BASE + "/workflows?_=x&_=y", provider.BASE + "/workflows?_=old"])
async def test_process_street_unsafe_changed_duplicate_and_stalled_links(wire, href):
    requests, replies = wire
    replies.append((200, {"workflows": [], "links": [{"name": "next", "href": href}]}))
    with pytest.raises(ValueError):
        await node({"operation": "list_workflows", "page_cursor": "old"}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_process_street_failure_is_not_acknowledged_or_retried(wire, status):
    requests, replies = wire
    replies.append((status, {"error": "Denied " + KEY}))
    result = await node({"operation": "create_workflow_run", "workflow_id": ID}).execute({})
    assert not result["success"] and len(requests) == 1 and KEY not in str(result)
    assert result["message"] == "Denied [redacted]"
    assert result["status"] == ("unknown" if status >= 500 else "error")


@pytest.mark.asyncio
async def test_process_street_transport_failure_has_unknown_write_outcome(wire):
    requests, replies = wire
    replies.append((0, httpx.ReadTimeout("secret " + KEY)))
    result = await node({"operation": "create_workflow_run", "workflow_id": ID}).execute({})
    assert result["status"] == "unknown" and result["write_outcome"] == "unverified" and len(requests) == 1
    assert KEY not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"workflows": "wrong"}, {"workflows": [1]}, {"error": "Denied", "workflows": []}])
async def test_process_street_malformed_and_error_envelopes(wire, payload):
    wire[1].append((200, payload))
    with pytest.raises(ValueError):
        await node({"operation": "list_workflows"}).execute({})


def test_process_street_required_replacement_fields_and_credential_shape():
    for config in [
        {"operation": "update_workflow_run", "workflow_run_id": RUN, "name": "New"},
        {"operation": "update_task", "workflow_run_id": RUN, "task_id": TASK},
        {"operation": "get_workflow", "workflow_id": "../users"},
        {"operation": "assign_task", "workflow_run_id": RUN, "task_id": TASK, "email": "bad"},
        {"operation": "update_form_field_values", "workflow_run_id": RUN, "fields": [{"id": ID, "value": "A", "values": ["B"]}]},
    ]:
        with pytest.raises(ValueError):
            provider.ProcessStreetNode.parse_config({"config": config, "credentials": AUTH})
    with pytest.raises(ValidationError):
        provider.ProcessStreetAPIKey.model_validate({**AUTH, "api_key": "https://example.com/key"})
    with pytest.raises(ValueError):
        provider.ProcessStreetNode.parse_config({"config": {"operation": "list_workflows"}, "credentials": {**AUTH, "credential_type": "other_api_key"}})


@pytest.mark.asyncio
async def test_process_street_documented_request_examples(wire):
    examples = json.loads((Path(__file__).parent / "fixtures/process-street/request_examples.json").read_text())
    for config in examples["configs"]:
        payload = {"fields": []} if config["operation"] == "update_form_field_values" else {"id": RUN}
        wire[1].append((provider.SUCCESS_STATUS.get(config["operation"], 200), payload))
        assert (await node(config).execute({}))["success"]
