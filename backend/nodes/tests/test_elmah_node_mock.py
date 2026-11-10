"""HTTP-boundary regressions and documented payload checks; no live API key."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import elmah_node as native
from nodes.core.registry import NodeFactory, NODE_REGISTRY
from nodes.core.poll_trigger import poll_scope

TOKEN = "elmah-test-key-42"
_HTTP_CLIENT = httpx.AsyncClient


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(operation, **values):
    return NodeFactory.create_node(
        node_id="elmah-test",
        node_type="automation-elmah",
        node_data={
            "config": {"operation": operation, **values},
            "credentials": {"credential_type": "elmah_api_key", "api_key": TOKEN},
        },
    )


def transport(monkeypatch, reply):
    requests = []
    original = _HTTP_CLIENT

    def respond(request):
        requests.append(request)
        return reply(request) if callable(reply) else httpx.Response(200, json=reply)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return original(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native.httpx, "AsyncClient", client)
    return requests


def test_discovered_schema_manual_credential_and_scope():
    assert NODE_REGISTRY["automation-elmah"] is native.ElmahNode
    credential = native.ElmahAPIKeyCredential(api_key=TOKEN)
    assert credential.credential_type == "elmah_api_key"
    assert native.ElmahNode.connection_evidence.operation == "list_logs"
    scope = {"operation": "on_new_message", "log_id": "log-1"}
    assert poll_scope(native.ElmahNode, scope) == poll_scope(
        native.ElmahNode, {**scope, "label": "new name"}
    )
    assert poll_scope(native.ElmahNode, scope) != poll_scope(
        native.ElmahNode, {**scope, "log_id": "log-2"}
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,config,method,path,body",
    [
        ("list_logs", {}, "GET", "/v3/logs", None),
        ("get_log", {"log_id": "l1"}, "GET", "/v3/logs/l1", None),
        (
            "create_log",
            {"body": {"name": "Production", "disabled": False}},
            "POST",
            "/v3/logs",
            {"name": "Production", "disabled": False},
        ),
        ("enable_log", {"log_id": "l1"}, "POST", "/v3/logs/l1/_enable", None),
        ("disable_log", {"log_id": "l1"}, "POST", "/v3/logs/l1/_disable", None),
        ("diagnose_log", {"log_id": "l1"}, "GET", "/v3/logs/l1/_diagnose", None),
        ("delete_log", {"log_id": "l1"}, "DELETE", "/v3/logs/l1", None),
        ("list_deployments", {}, "GET", "/v3/deployments", None),
        ("get_deployment", {"deployment_id": "d1"}, "GET", "/v3/deployments/d1", None),
        (
            "delete_deployment",
            {"deployment_id": "d1"},
            "DELETE",
            "/v3/deployments/d1",
            None,
        ),
        (
            "create_deployment",
            {"body": {"version": "1.0.0", "logId": "l1"}},
            "POST",
            "/v3/deployments",
            {"version": "1.0.0", "logId": "l1"},
        ),
        (
            "send_heartbeat",
            {
                "log_id": "l1",
                "heartbeat_id": "h1",
                "body": {"result": "Healthy", "took": 0},
            },
            "POST",
            "/v3/heartbeats/l1/h1",
            {"result": "Healthy", "took": 0},
        ),
        (
            "get_message",
            {"log_id": "l1", "message_id": "m1"},
            "GET",
            "/v3/messages/l1/m1",
            None,
        ),
        (
            "delete_message",
            {"log_id": "l1", "message_id": "m1"},
            "DELETE",
            "/v3/messages/l1/m1",
            None,
        ),
        (
            "hide_message",
            {"log_id": "l1", "message_id": "m1"},
            "POST",
            "/v3/messages/l1/m1/_hide",
            None,
        ),
        (
            "fix_message",
            {"log_id": "l1", "message_id": "m1"},
            "POST",
            "/v3/messages/l1/m1/_fix",
            None,
        ),
        (
            "create_message",
            {"log_id": "l1", "body": {"title": "This is a test message"}},
            "POST",
            "/v3/messages/l1",
            {"title": "This is a test message"},
        ),
        (
            "create_messages_bulk",
            {"log_id": "l1", "body": [{"title": "This is a test message"}]},
            "POST",
            "/v3/messages/l1/_bulk",
            [{"title": "This is a test message"}],
        ),
        (
            "fix_messages",
            {
                "log_id": "l1",
                "body": {
                    "query": "severity:Error",
                    "from_time": "2026-01-01T00:00:00Z",
                },
            },
            "POST",
            "/v3/messages/l1/_fix",
            {"query": "severity:Error", "from": "2026-01-01T00:00:00Z"},
        ),
        (
            "delete_messages",
            {"log_id": "l1", "body": {"query": "severity:Error"}},
            "DELETE",
            "/v3/messages/l1",
            {"query": "severity:Error"},
        ),
    ],
)
async def test_exact_request_mapping(
    monkeypatch, operation, config, method, path, body
):
    requests = transport(monkeypatch, lambda r: httpx.Response(204))
    output = await node(operation, **config).execute({})
    req = requests[0]
    assert len(requests) == 1 and req.method == method and req.url.path == path
    assert req.url.host == "api.elmah.io" and req.url.params["api_key"] == TOKEN
    assert (json.loads(req.content) if req.content else None) == body
    assert output["data"] is None and output["http_status"] == 204


@pytest.mark.asyncio
async def test_search_pagination_dates_and_boolean_params(monkeypatch):
    payload = json.loads(
        (Path(__file__).parent / "fixtures/elmah/messages.json").read_text()
    )["body"]
    requests = transport(monkeypatch, payload)
    result = await node(
        "list_messages",
        log_id="l1",
        pageIndex=2,
        pageSize=100,
        from_time="2016-07-01T00:00:00Z",
        includeHeaders=True,
        searchAfter="cursor + 1",
    ).execute({})
    assert result["data"] == payload
    assert dict(requests[0].url.params) == {
        "api_key": TOKEN,
        "pageIndex": "2",
        "pageSize": "100",
        "from": "2016-07-01T00:00:00Z",
        "includeHeaders": "true",
        "searchAfter": "cursor + 1",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("status,created", [(200, False), (201, True)])
async def test_message_creation_semantics(monkeypatch, status, created):
    transport(
        monkeypatch,
        lambda r: httpx.Response(
            status,
            json={"location": "https://api.elmah.io/v3/messages/l1/m1"}
            if created
            else {},
        ),
    )
    result = await node(
        "create_message", log_id="l1", body={"title": "This is a test message"}
    ).execute({})
    assert result["message_created"] is created


@pytest.mark.asyncio
async def test_provider_errors_and_transport_errors_do_not_leak_key(monkeypatch):
    transport(
        monkeypatch, lambda r: httpx.Response(401, text="API key not valid: " + TOKEN)
    )
    with pytest.raises(ValueError, match="401") as exc:
        await node("list_logs").execute({})
    assert TOKEN not in str(exc.value)

    def timeout(req):
        raise httpx.ReadTimeout(str(req.url), request=req)

    transport(monkeypatch, timeout)
    with pytest.raises(ValueError, match="before retrying") as exc:
        await node("list_logs").execute({})
    assert TOKEN not in str(exc.value)


@pytest.mark.asyncio
async def test_documented_poll_payload_baseline_dedup_and_agent(monkeypatch):
    documented = json.loads(
        (Path(__file__).parent / "fixtures/elmah/messages.json").read_text()
    )["body"]
    requests = transport(monkeypatch, documented)
    n = node("on_new_message", log_id="l1", from_time="2016-07-01T00:00:00Z")
    state = {}

    async def update(mutator, **kwargs):
        new, result = mutator(dict(state))
        if new is not None:
            state.clear()
            state.update(new)
        return result

    n._update_node_state = update
    first = await n.execute({})
    assert first["messages"] == [] and n.trigger_produced_no_event(first)
    state["seen_ids"] = [documented["messages"][1]["id"]]
    second = await n.execute({})
    assert second["new_message_count"] == 1 and n.trigger_emitted_event(second)
    event = n.resolve_agent_event(second)
    assert (
        "This is another test message" in event["text"]
        and "81C7C282C9FDAEA3" in event["text"]
    )
    assert event["conversation_key"] == "elmah:l1"
    assert (await n.execute({}))["new_message_count"] == 0
    assert requests[0].url.params["from"] == "2016-07-01T00:00:00Z"


@pytest.mark.asyncio
async def test_poll_follows_cursor_before_baselining(monkeypatch):
    replies = [
        httpx.Response(
            200, json={"messages": [{"id": "m1"}], "searchAfter": "next", "total": 2}
        ),
        httpx.Response(200, json={"messages": [{"id": "m2"}], "total": 2}),
    ]
    # Reinstall once so each response is a real HTTP response.
    requests = transport(monkeypatch, lambda r: replies.pop(0))
    n = node("on_new_message", log_id="l1")
    state = {}

    async def update(mutator, **kwargs):
        new, result = mutator(state)
        state.update(new or {})
        return result

    n._update_node_state = update
    assert (await n.execute({}))["messages"] == []
    assert (
        state["seen_ids"] == ["m1", "m2"]
        and requests[1].url.params["searchAfter"] == "next"
    )


@pytest.mark.parametrize(
    "values", [{"log_id": "../another"}, {"log_id": "https://example.com"}]
)
def test_path_injection_rejected(values):
    with pytest.raises(ValidationError):
        native.ElmahGetLogConfig(**values)


@pytest.mark.parametrize(
    "body",
    [
        {"version": "1.0", "created": "2026-01-01T00:00:00"},
        {"version": "1.0", "userEmail": "invalid"},
    ],
)
def test_deployment_rejects_non_contract_timestamp_and_email(body):
    with pytest.raises(ValidationError):
        native.CreateDeployment(**body)
