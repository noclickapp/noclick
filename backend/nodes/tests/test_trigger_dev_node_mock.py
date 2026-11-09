"""Request contract regression tests; no live credentials or network access."""
import json
from pathlib import Path
from urllib.parse import unquote

import httpx
import pytest
from pydantic import ValidationError
from nodes import trigger_dev_node as native

CASES = json.loads((Path(__file__).parent / "fixtures/trigger-dev/requests.json").read_text())["cases"]
CREDENTIAL = {"credential_type": "trigger_dev_api_key", "api_key": "test-environment-token"}


def node(config):
    from nodes.core.registry import NodeFactory
    return NodeFactory.create_node(node_id="trigger-dev-test", node_type="automation-trigger-dev",
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, body=None, status=200, empty=False):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, **({"content": b""} if empty else {"json": body if body is not None else {"data": [{"id": "run_1234"}], "pagination": {"next": "run_5678"}}}))
    monkeypatch.setattr(native, "guarded_async_client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(reply), **kw))
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["config"]["operation"])
async def test_trigger_dev_request_contract(monkeypatch, case):
    requests = transport(monkeypatch)
    result = await node(case["config"]).execute({})
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert request.url.host == "api.trigger.dev"
    assert unquote(request.url.path) == case["path"]
    assert dict(request.url.params) == case["query"]
    assert (json.loads(request.content) if request.content else None) == case["body"]
    assert request.headers["Authorization"] == "Bearer test-environment-token"
    assert result


@pytest.mark.asyncio
async def test_trigger_dev_null_payload_and_nested_metadata(monkeypatch):
    requests = transport(monkeypatch)
    await node({"operation": "trigger_task", "task_identifier": "my-task", "payload": None, "context": False}).execute({})
    assert json.loads(requests[0].content) == {"payload": None, "context": False}


@pytest.mark.asyncio
async def test_trigger_dev_list_keeps_provider_pagination(monkeypatch):
    body = {"data": [{"id": "run_1234"}], "pagination": {"next": "run_5678", "previous": None}}
    requests = transport(monkeypatch, body)
    assert await node({"operation": "list_runs"}).execute({}) == body
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_trigger_dev_failed_task_result_is_data(monkeypatch):
    body = {"ok": False, "id": "run_1234", "error": {"message": "Task failed"}}
    transport(monkeypatch, body)
    assert await node({"operation": "get_run_result", "run_id": "run_1234"}).execute({}) == {"result": body}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 204])
async def test_trigger_dev_empty_delete(monkeypatch, status):
    transport(monkeypatch, status=status, empty=True)
    assert await node({"operation": "delete_schedule", "schedule_id": "sched_1234"}).execute({}) == {"success": True}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 401, 403, 404, 429, 500])
async def test_trigger_dev_http_failure_is_not_success(monkeypatch, status):
    requests = transport(monkeypatch, {"error": "Rejected"}, status=status)
    with pytest.raises(httpx.HTTPStatusError):
        await node({"operation": "list_runs"}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["..", "../other", "run_1?x=1", "https://evil.test"])
async def test_trigger_dev_path_injection_is_refused(monkeypatch, value):
    requests = transport(monkeypatch)
    with pytest.raises(ValueError):
        await node({"operation": "cancel_run", "run_id": value}).execute({})
    assert requests == []


def test_trigger_dev_manual_credential_and_evidence():
    assert native.TriggerDevAPIKey(api_key="test-key").credential_type == "trigger_dev_api_key"
    assert native.TriggerDevNode.connection_evidence.operation == "list_runs"
    with pytest.raises(ValidationError):
        native.TriggerDevAPIKey(api_key="tr_pat_1234")
    with pytest.raises(ValidationError):
        native.ListRuns(after="run_1", before="run_2")
    with pytest.raises(ValidationError):
        native.BatchTriggerTask(task_identifier="my-task", items=[])
    with pytest.raises(ValidationError):
        native.UpdateSchedule(schedule_id="sched_1", task="my-task")
