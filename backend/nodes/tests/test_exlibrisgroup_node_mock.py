"""Request mapping and trigger behavior against Alma's published Task Lists contract."""
import copy
import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes.core.registry import NodeFactory
from nodes.exlibrisgroup_node import ExLibrisCredential, ExLibrisNode

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures/exlibrisgroup/authority_task.json").read_text()
)
KEY = "not-a-real-alma-key-123456789"


def node(operation, **values):
    return NodeFactory.create_node(
        node_id="exlibris-test",
        node_type="automation-exlibrisgroup",
        node_data={
            "config": {"operation": operation, **values},
            "credentials": {"credential_type": "exlibrisgroup_api_key", "api_key": KEY},
        },
    )


@pytest.fixture
def api(monkeypatch):
    calls = []
    replies = []

    async def handle(request):
        calls.append(request)
        status, body = replies.pop(0) if replies else (200, {})
        if isinstance(body, str):
            return httpx.Response(
                status, text=body, headers={"Content-Type": "application/xml"}
            )
        return httpx.Response(status, json=body)

    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as value:
            yield value

    monkeypatch.setattr("nodes.exlibrisgroup_node.guarded_async_client", client)
    return calls, replies


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,config,method,path,query,body",
    [
        (
            "list_authority_control_tasks",
            {"title": "The great book title"},
            "GET",
            "/authority-control-tasks",
            {
                "title": "The great book title",
                "mode": "review",
                "limit": "10",
                "offset": "0",
            },
            None,
        ),
        (
            "get_authority_control_task",
            {"task_id": "1234567890000121"},
            "GET",
            "/authority-control-tasks/1234567890000121",
            {},
            None,
        ),
        (
            "dismiss_authority_control_task",
            {"task_id": "1234567890000121"},
            "POST",
            "/authority-control-tasks/1234567890000121",
            {"op": "dismiss"},
            None,
        ),
        (
            "list_printouts",
            {"status": "Pending"},
            "GET",
            "/printouts",
            {"status": "Pending", "letter": "ALL", "limit": "10", "offset": "0"},
            None,
        ),
        (
            "act_on_printouts",
            {"op": "mark_as_printed", "printout_id": "129313760000121"},
            "POST",
            "/printouts",
            {"op": "mark_as_printed", "printout_id": "129313760000121"},
            None,
        ),
        (
            "create_printout",
            {
                "body": {
                    "printout": "Testing",
                    "printer": {"value": "Printout Queue."},
                    "letter": "<div> Welcome to...</div>",
                }
            },
            "POST",
            "/printouts/create",
            {},
            {
                "printout": "Testing",
                "printer": {"value": "Printout Queue."},
                "letter": "<div> Welcome to...</div>",
            },
        ),
        (
            "get_printout",
            {"printout_id": "129313760000121"},
            "GET",
            "/printouts/129313760000121",
            {},
            None,
        ),
        (
            "act_on_printout",
            {"printout_id": "129313760000121", "op": "mark_as_canceled"},
            "POST",
            "/printouts/129313760000121",
            {"op": "mark_as_canceled"},
            None,
        ),
        (
            "list_requested_resources",
            {"library": "MAIN", "circ_desk": "DEFAULT_CIRC_DESK"},
            "GET",
            "/requested-resources",
            {"library": "MAIN", "circ_desk": "DEFAULT_CIRC_DESK"},
            None,
        ),
        (
            "mark_requested_resources_reported",
            {"library": "MAIN", "circ_desk": "DEFAULT_CIRC_DESK"},
            "POST",
            "/requested-resources",
            {
                "op": "mark_reported",
                "library": "MAIN",
                "circ_desk": "DEFAULT_CIRC_DESK",
            },
            None,
        ),
        (
            "list_lending_requests",
            {"library": "MAIN", "reported": "N"},
            "GET",
            "/rs/lending-requests",
            {"library": "MAIN", "reported": "N"},
            None,
        ),
        (
            "mark_lending_requests_reported",
            {"library": "MAIN"},
            "POST",
            "/rs/lending-requests",
            {"op": "mark_reported", "library": "MAIN"},
            None,
        ),
        ("get_connection_test", {}, "GET", "/test", {}, None),
        ("test_write_permissions", {}, "POST", "/test", {}, None),
    ],
)
async def test_request_contract(api, operation, config, method, path, query, body):
    calls, replies = api
    await node(operation, **config).execute({})
    request = calls[0]
    assert len(calls) == 1
    assert request.method == method
    assert request.url.host == "api-eu.hosted.exlibrisgroup.com"
    assert request.url.path == "/almaws/v1/task-lists" + path
    assert request.url.params["apikey"] == KEY
    for key, value in query.items():
        assert request.url.params[key] == value
    assert request.headers["Accept"] == "application/json"
    assert "Authorization" not in request.headers
    assert (json.loads(request.content) if request.content else None) == body


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,text",
    [
        ("get_connection_test", "GET - OK - institutionCode: 01ABC_INST"),
        ("test_write_permissions", "POST - OK"),
    ],
)
async def test_documented_test_xml(api, operation, text):
    # Exact examples are in each /test operation's description in Task Lists OpenAPI.
    calls, replies = api
    replies.append((200, "<test>" + text + "</test>"))
    assert (await node(operation).execute({}))["data"]["test"] == text


@pytest.mark.asyncio
async def test_china_origin(api):
    calls, _ = api
    instance = node("get_connection_test")
    instance.config.credentials.region = "cn"
    await instance.execute({})
    assert calls[0].url.host == "api-cn.hosted.exlibrisgroup.com.cn"


@pytest.mark.asyncio
async def test_errors_do_not_expose_query_secret(api):
    _, replies = api
    replies.append((401, "Invalid API key " + KEY))
    with pytest.raises(ValueError) as caught:
        await node("get_connection_test").execute({})
    assert KEY not in str(caught.value)
    assert "401" in str(caught.value)
    replies.append((200, {"errorsExist": True, "errorList": {"error": []}}))
    with pytest.raises(ValueError, match="error"):
        await node("get_connection_test").execute({})


@pytest.mark.asyncio
async def test_poll_baseline_new_and_repeat(api):
    calls, replies = api
    instance = node("on_new_authority_task", vocabulary_code="LCNAMES")
    state = {}

    async def update(mutator, **kwargs):
        new, result = mutator(copy.deepcopy(state))
        if new is not None:
            state.clear()
            state.update(new)
        return result

    instance._update_node_state = update
    task = FIXTURE["task"]
    for rows in [[], [task], [task]]:
        replies.append(
            (200, {"authority_control_task": rows, "total_record_count": len(rows)})
        )
    assert (await instance.execute({}))["new_task_count"] == 0
    result = await instance.execute({})
    assert result["tasks"] == [task]
    event = ExLibrisNode.resolve_agent_event(result)
    assert (
        task["id"] in event["text"]
        and task["title"] in event["text"]
        and task["mms_id"] in event["text"]
    )
    assert (await instance.execute({}))["new_task_count"] == 0
    assert not ExLibrisNode.should_propagate_output(
        {"new_task_count": 0}, {"operation": "on_new_authority_task"}
    )
    assert calls[0].url.params["order_by"] == "create_date"
    assert calls[0].url.params["direction"] == "desc"
    assert calls[0].url.params["vocabulary_code"] == "LCNAMES"


@pytest.mark.asyncio
async def test_poll_does_not_advance_state_on_missing_ids(api):
    _, replies = api
    replies.append((200, {"authority_control_task": [{"title": "Missing ID"}]}))
    with pytest.raises(ValueError, match="IDs"):
        await node("on_new_authority_task").execute({})


@pytest.mark.parametrize(
    "config",
    [
        {"operation": "get_authority_control_task", "task_id": "../x"},
        {"operation": "list_requested_resources", "library": "MAIN"},
        {"operation": "list_lending_requests"},
        {"operation": "act_on_printout", "printout_id": "123", "op": "delete"},
        {"operation": "list_authority_control_tasks", "limit": 101},
        {"operation": "list_authority_control_tasks", "submit_date_from": "yesterday"},
    ],
)
def test_invalid_config(config):
    assert not ExLibrisNode.validate_config({"config": config})["valid"]


def test_credential_manual_defaults():
    assert ExLibrisCredential(api_key=KEY).credential_type == "exlibrisgroup_api_key"
    with pytest.raises(ValidationError):
        ExLibrisCredential(api_key=KEY, region="attacker.example")


@pytest.mark.asyncio
async def test_transport_failure_does_not_expose_url(monkeypatch):
    async def handle(request):
        raise httpx.ConnectError(str(request.url), request=request)

    @asynccontextmanager
    async def client(**kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as value:
            yield value

    monkeypatch.setattr("nodes.exlibrisgroup_node.guarded_async_client", client)
    with pytest.raises(ValueError) as caught:
        await node("get_connection_test").execute({})
    assert KEY not in str(caught.value)
    assert "apikey" not in str(caught.value)
