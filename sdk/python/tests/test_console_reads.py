"""Parity with the TypeScript client (test/console.test.ts): operations and
their console URLs, tool calls, the request log, human requests, agent
conversations, policy evaluation, brand reset and usage series/limits."""

import datetime

import httpx
import pytest
import respx

import noclick as nc
from noclick import _client as client_module
from platform_helpers import USER_ID, agent_row, body, listing, operation

HOSTED = "https://noclick.com/dashboard/developers"
UTC = datetime.timezone.utc
AGENT = agent_row()


@pytest.fixture
def hosted(monkeypatch):
    """The default client on the hosted base URL, over a mock."""
    c = nc.Client(api_key="nk_live_test", base_url=nc.DEFAULT_BASE_URL, max_retries=0)
    monkeypatch.setattr(client_module, "_default", c)
    with respx.mock(base_url=nc.DEFAULT_BASE_URL, assert_all_called=False) as router:
        yield router


# --- operations --------------------------------------------------------------------


def test_operation_list_page_maps_every_filter(api, client):
    route = api.get("/v1/operations").respond(
        json=listing(operation(kind="agent.message", status="running"), next_cursor="c9"),
    )
    page = nc.Operation.list_page(
        kind=["agent.message", "sandbox.exec"], status="live", status_not=["succeeded", "canceled"],
        agent=nc.Agent.from_id("ag_1"), key="nk_live_ab12",
        created_after=datetime.datetime(2026, 9, 25, tzinfo=UTC), created_before="2026-09-26T00:00:00Z",
        updated_after=datetime.datetime(2026, 9, 25, 12, tzinfo=UTC), user_filter="acme", limit=50,
    )
    params = route.calls.last.request.url.params
    assert params["kind"] == "agent.message,sandbox.exec"
    assert params["status"] == "live"
    assert params["status_not"] == "succeeded,canceled"
    assert params["agent_id"] == "ag_1"
    assert params["key_id"] == "nk_live_ab12"
    assert params["created_after"] == "2026-09-25T00:00:00+00:00"
    assert params["created_before"] == "2026-09-26T00:00:00Z"
    assert params["updated_after"] == "2026-09-25T12:00:00+00:00"
    assert params["user_id"] == "acme"
    assert params["limit"] == "50"
    assert page.next_cursor == "c9" and page.data[0].status == "running"


def test_operation_summary_and_view_fields(api, client):
    summary = api.get("/v1/operations/summary").respond(json={
        "total": 3, "by_status": {"queued": 0, "running": 1, "awaiting_human": 0,
                                  "succeeded": 1, "failed": 1, "canceled": 0, "expired": 0},
    })
    result = nc.Operation.summary(kind="agent.message", agent="ag_1", created_after="2026-09-25T00:00:00Z")
    assert (result.total, result.by_status["failed"]) == (3, 1)
    params = summary.calls.last.request.url.params
    assert (params["agent_id"], params["kind"]) == ("ag_1", "agent.message")

    api.get("/v1/operations/op_1").respond(json=operation(
        kind="agent.message", status="canceled", summary="hi there", user_id=USER_ID, key_id="key_1",
        agent_id="ag_1", input={"text": "hi there"}, started_at="2026-09-25T10:00:01Z",
        finished_at="2026-09-25T10:00:04Z", wait_ms=120, run_ms=2720, held_ms=0,
        events=[{"status": "queued", "at": "2026-09-25T10:00:00Z"},
                {"status": "canceled", "at": "2026-09-25T10:00:04Z", "by": "owner"}],
    ))
    op = nc.Operation.from_id("op_1").hydrate()
    assert op.summary_text == "hi there"
    assert (op.user_id, op.key_id, op.agent_id, op.input) == (USER_ID, "key_1", "ag_1", {"text": "hi there"})
    assert op.started_at == datetime.datetime(2026, 9, 25, 10, 0, 1, tzinfo=UTC)
    assert op.finished_at == datetime.datetime(2026, 9, 25, 10, 0, 4, tzinfo=UTC)
    assert (op.wait_ms, op.run_ms, op.held_ms) == (120, 2720, 0)
    assert [(t.status, t.by) for t in op.transitions] == [("queued", None), ("canceled", "owner")]


def test_an_operation_recorded_before_timings_reads_null_timings(api, client):
    api.get("/v1/operations/op_1").respond(json=operation(events=[], wait_ms=None, run_ms=None, held_ms=None))
    op = nc.Operation.from_id("op_1").hydrate()
    assert (op.wait_ms, op.run_ms, op.held_ms, op.transitions) == (None, None, None, [])


def test_operation_tool_calls(api, client):
    route = api.get("/v1/operations/op_1/tool_calls").respond(json=listing({
        "object": "tool_call", "id": "tc_1", "tool_name": "gmail.send_email", "tool_type": "node_op",
        "operation": "send_email", "status": "success", "error": None, "arguments": {"to": "a@b.c"},
        "result_preview": "sent", "duration_ms": 42, "credential_id": "cred_1", "user_id": USER_ID,
        "agent_id": "ag_1", "conversation": "c1", "execution_id": "ex_1", "source": "agent",
        "created_at": "2026-09-25T10:00:02Z",
    }))
    calls = nc.Operation.from_id("op_1", user=None).tool_calls()
    assert route.call_count == 1
    assert isinstance(calls[0], nc.ToolCall)
    assert (calls[0].tool_name, calls[0].arguments, calls[0].duration_ms) == ("gmail.send_email", {"to": "a@b.c"}, 42)
    assert calls[0].created_at == datetime.datetime(2026, 9, 25, 10, 0, 2, tzinfo=UTC)


# --- console URLs ----------------------------------------------------------------------


def test_operation_repr_names_its_console_page_on_the_hosted_api(hosted):
    op = nc.Operation.from_id("op_1")
    assert op.console_url == f"{HOSTED}/operations?op=op_1"
    assert repr(op) == f"Operation(id='op_1', hydrated=False, console_url='{HOSTED}/operations?op=op_1')"


def test_no_console_url_off_the_hosted_api(api, client):
    op = nc.Operation.from_id("op_1")
    assert op.console_url is None
    assert repr(op) == "Operation(id='op_1', hydrated=False)"


def test_errors_raised_by_wait_name_the_console_page(hosted):
    hosted.get("/v1/operations/op_1/wait").respond(json=operation(
        kind="agent.message", status="failed",
        error={"type": "spend_cap_exceeded", "message": "User cap reached.", "scope": "user"},
    ))
    with pytest.raises(nc.SpendCapExceeded) as info:
        nc.Operation.from_id("op_1").wait()
    assert info.value.message == f"User cap reached. See {HOSTED}/operations?op=op_1"
    assert str(info.value).startswith(info.value.message) and info.value.scope == "user"

    hosted.get("/v1/operations/op_2/wait").respond(json=operation(op_id="op_2", status="canceled"))
    with pytest.raises(nc.OperationCanceled) as canceled:
        nc.Operation.from_id("op_2").wait()
    assert canceled.value.message == f"Operation op_2 canceled. See {HOSTED}/operations?op=op_2"

    hosted.get("/v1/operations/op_3").respond(json=operation(op_id="op_3", status="running"))
    with pytest.raises(nc.OperationTimeout) as timeout:
        nc.Operation.from_id("op_3").wait(timeout=0)
    assert timeout.value.message.endswith(f"See {HOSTED}/operations?op=op_3")


def test_errors_off_the_hosted_api_keep_their_message(api, client):
    api.get("/v1/operations/op_1/wait").respond(json=operation(
        status="failed", error={"type": "policy_denied", "message": "Denied."},
    ))
    with pytest.raises(nc.PolicyDenied) as info:
        nc.Operation.from_id("op_1").wait()
    assert info.value.message == "Denied."


def test_agents_and_users_have_console_urls_on_the_hosted_api(hosted):
    hosted.get("/v1/agents/ag_1").respond(json=AGENT)
    assert nc.Agent.get("ag_1").console_url == f"{HOSTED}/agents/ag_1"
    assert nc.User.from_id(USER_ID).console_url == f"{HOSTED}/users/{USER_ID}"
    assert nc.User.from_id("auth0|123").console_url == f"{HOSTED}/users/auth0%7C123"


def test_user_console_url_is_none_off_the_hosted_api(api, client):
    assert nc.User.from_id(USER_ID).console_url is None


# --- tool calls, requests, humans ---------------------------------------------------------


def test_tool_call_list_page_and_summary(api, client):
    route = api.get("/v1/tool_calls").respond(
        json=listing({"id": "tc_1", "tool_name": "search", "status": "error", "error": "boom"}, next_cursor="n"),
    )
    page = nc.ToolCall.list_page(
        tool="gmail.*", status="error", source="agent", agent="ag_1", user_filter=nc.ALL_USERS,
        since=datetime.datetime(2026, 9, 25, tzinfo=UTC), until="2026-09-26T00:00:00Z", limit=200,
    )
    p = route.calls.last.request.url.params
    assert [p["tool"], p["status"], p["source"], p["agent_id"], p["user_id"], p["since"], p["until"], p["limit"]] == [
        "gmail.*", "error", "agent", "ag_1", "all", "2026-09-25T00:00:00+00:00", "2026-09-26T00:00:00Z", "200",
    ]
    assert page.data[0].error == "boom" and page.next_cursor == "n"

    summary = api.get("/v1/tool_calls/summary").respond(json={"total": 1204, "success": 1195, "error": 9})
    counts = nc.ToolCall.summary(agent="ag_1", since="2026-09-25T00:00:00Z")
    assert (counts.total, counts.success, counts.error) == (1204, 1195, 9)
    assert summary.calls.last.request.url.params["agent_id"] == "ag_1"


def test_tool_calls_through_a_hosted_mcp_server_name_it(api, client):
    route = api.get("/v1/tool_calls").respond(json=listing(
        {"id": "tc_2", "tool_name": "hubspot.create_contact", "status": "success", "source": "mcp_server",
         "mcp_server_id": "mcp_1", "user_id": "acme"}))
    [call] = nc.ToolCall.list(source="mcp_server", user="acme")
    assert route.calls.last.request.url.params["source"] == "mcp_server"
    assert (call.source, call.mcp_server_id, call.user_id) == ("mcp_server", "mcp_1", "acme")


def test_api_request_list_page(api, client):
    route = api.get("/v1/requests").respond(json=listing({
        "id": "rq_1", "actor": "key", "key_id": "key_1", "method": "POST", "route": "/v1/policy", "path_params": {},
        "status": 422, "error_type": "invalid_request", "duration_ms": 12, "idempotency_replayed": True,
        "operation_id": None, "request_id": "req_9", "created_at": "2026-09-25T10:00:00Z",
    }))
    page = nc.ApiRequest.list_page(
        method="POST", status="4xx", key="nk_live_ab12", route="/v1/policy", error_type="invalid_request",
    )
    p = route.calls.last.request.url.params
    assert [p["method"], p["status"], p["key_id"], p["route"], p["error_type"]] == [
        "POST", "4xx", "nk_live_ab12", "/v1/policy", "invalid_request",
    ]
    row = page.data[0]
    assert (row.status, row.route, row.idempotency_replayed) == (422, "/v1/policy", True)
    assert row.error_type == "invalid_request"


def test_human_request_list_page_builds_lazy_operations(api, client):
    route = api.get("/v1/humans/requests").respond(json=listing({
        "object": "human_request", "id": "hr_1", "kind": "approve", "status": "pending", "operation_id": "op_7",
        "message": "Send it?", "user_id": None, "url": "https://noclick.com/h/hr_1", "owner_can_answer": True,
    }))
    page = nc.HumanRequest.list_page(
        status="pending", kind="approve", answerable="owner", status_not=["expired"], user_filter=nc.ALL_USERS,
    )
    p = route.calls.last.request.url.params
    assert [p["status"], p["kind"], p["answerable"], p["status_not"], p["user_id"]] == [
        "pending", "approve", "owner", "expired", "all",
    ]
    request = page.data[0]
    assert (request.id, request.request_id, request.request_status) == ("op_7", "hr_1", "pending")
    assert request.url == "https://noclick.com/h/hr_1" and request.request["owner_can_answer"] is True
    api.get("/v1/operations/op_7/wait").respond(json=operation(
        op_id="op_7", kind="human.approve", status="succeeded", result={"approved": True},
    ))
    assert request.wait() is True


# --- agents, policy, brand, usage -------------------------------------------------------


def test_agent_conversations_with_a_user_filter_and_budget_updates(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    route = api.get("/v1/agents/ag_1/conversations").respond(json=listing({
        "conversation": "c1", "user_id": USER_ID, "title": "Refund", "preview": "Can I…", "turns": 4,
        "cost_usd": 0.42, "last_activity": "2026-09-25T11:00:00Z",
    }, next_cursor="k"))
    agent = nc.Agent.from_id("ag_1")
    page = agent.conversations_page(user_filter=nc.ALL_USERS, limit=20)
    request = route.calls.last.request
    assert request.url.params["user_id"] == "all" and "NoClick-User" not in request.headers
    first = page.data[0]
    assert page.next_cursor == "k" and (first.conversation, first.turns, first.cost_usd) == ("c1", 4, 0.42)
    assert first.last_activity == datetime.datetime(2026, 9, 25, 11, tzinfo=UTC)

    route.side_effect = [
        httpx.Response(200, json=listing({"conversation": "c1"}, next_cursor="k")),
        httpx.Response(200, json=listing({"conversation": "c2"})),
    ]
    assert [c.conversation for c in agent.conversations(user="acme")] == ["c1", "c2"]
    assert route.calls.last.request.headers["NoClick-User"] == "acme"

    assert agent.budget_usd_per_month == 50
    patch = api.patch("/v1/agents/ag_1").respond(json={**AGENT, "budget_usd_per_month": None})
    agent.update(budget_usd_per_month=None)
    assert body(patch.calls.last.request) == {"budget_usd_per_month": None}


def test_policy_list_and_evaluate(api, client):
    api.get("/v1/policies").respond(json=listing(
        {"object": "policy", "user_id": None, "allow": [], "deny": ["*.delete_*"], "require_approval": []},
        {"object": "policy", "user_id": "user_42", "allow": ["gmail.*"], "deny": [], "require_approval": []},
    ))
    assert [p.user_id for p in nc.Policy.list()] == [None, "user_42"]

    route = api.post("/v1/policy/evaluate").respond(json={"results": [
        {"tool": "gmail.send_email", "verdict": "approval", "matched_pattern": "gmail.*", "layer": "user"},
    ]})
    verdicts = nc.Policy.evaluate(
        ["gmail__send_email"], user="user_42", draft={"layer": "user", "require_approval": ["gmail.*"]},
    )
    assert body(route.calls.last.request) == {
        "tools": ["gmail__send_email"], "user_id": "user_42",
        "draft": {"layer": "user", "allow": [], "deny": [], "require_approval": ["gmail.*"]},
    }
    assert "NoClick-User" not in route.calls.last.request.headers
    v = verdicts[0]
    assert (v.tool, v.verdict, v.matched_pattern, v.layer) == ("gmail.send_email", "approval", "gmail.*", "user")

    nc.Policy.evaluate("search")
    assert body(route.calls.last.request) == {"tools": ["search"]}
    with pytest.raises(TypeError, match="list of patterns"):
        nc.Policy.evaluate("search", draft={"layer": "account", "deny": "*.delete_*"})


def test_brand_reset_and_is_default(api, client):
    delete = api.delete("/v1/brand").respond(json={"object": "brand", "name": None, "color": None, "is_default": True})
    reset = nc.Brand.reset()
    assert delete.call_count == 1
    assert isinstance(reset, nc.Brand) and reset.is_default is True and reset.name is None
    api.get("/v1/brand").respond(json={"object": "brand", "name": "NoClick", "is_default": True})
    assert nc.Brand.get().is_default is True


def test_usage_series_and_limits(api, client):
    series = api.get("/v1/usage/series").respond(json={
        "object": "usage_series", "interval": "day", "from": "2026-09-01T00:00:00Z", "to": "2026-10-01T00:00:00Z",
        "total_usd": 12.5, "series": [{"id": "key_1", "label": "Console", "total_usd": 12.5, "events": 3,
                                        "points": [{"t": "2026-09-02T00:00:00Z", "usd": 12.5, "events": 3}]}],
    })
    result = nc.Usage.series(
        from_=datetime.datetime(2026, 9, 1, tzinfo=UTC), to="2026-10-01T00:00:00Z", group_by="key",
        key="nk_live_ab12", agent="ag_1", user_filter=nc.NO_USER, interval="day",
    )
    p = series.calls.last.request.url.params
    assert [p["from"], p["to"], p["group_by"], p["key_id"], p["agent_id"], p["user_id"], p["interval"]] == [
        "2026-09-01T00:00:00+00:00", "2026-10-01T00:00:00Z", "key", "nk_live_ab12", "ag_1", "none", "day",
    ]
    assert result.total_usd == 12.5 and result.series[0].label == "Console"
    assert result.series[0].points[0].t == datetime.datetime(2026, 9, 2, tzinfo=UTC)

    api.get("/v1/usage/limits").respond(json={
        "period_start": "2026-09-01T00:00:00Z", "resets_at": "2026-10-01T00:00:00Z",
        "keys": [{"id": "key_1", "name": "Console", "cap": 50, "spent": 12.5}],
        "users": [{"id": "acme", "cap": 10, "spent": 11.2}],
        "agents": [{"id": "ag_1", "name": "support", "budget": 20, "spent": 3, "subtree_spent": 4}],
    })
    limits = nc.Usage.limits()
    assert (limits.keys[0].name, limits.keys[0].cap, limits.keys[0].spent) == ("Console", 50, 12.5)
    assert (limits.users[0].id, limits.users[0].cap, limits.users[0].spent) == ("acme", 10, 11.2)
    assert (limits.agents[0].budget, limits.agents[0].subtree_spent) == (20, 4)
    assert limits.resets_at == datetime.datetime(2026, 10, 1, tzinfo=UTC)


# --- verifier round: kind-pinned subclasses, required numbers ------------------------


def test_connect_link_reads_only_credential_connect_operations(api, client):
    route = api.get("/v1/operations").respond(json=listing(operation(kind="credential.connect")))
    listed = nc.ConnectLink.list(status="live")
    params = route.calls.last.request.url.params
    assert params["kind"] == "credential.connect" and params["status"] == "live"
    assert [op.kind for op in listed] == ["credential.connect"]

    route.respond(json=listing(operation(kind="credential.connect"), next_cursor="k"))
    page = nc.ConnectLink.list_page(limit=5)
    params = route.calls.last.request.url.params
    assert params["kind"] == "credential.connect" and params["limit"] == "5" and page.next_cursor == "k"

    summary = api.get("/v1/operations/summary").respond(json={"total": 2, "by_status": {"awaiting_human": 2}})
    assert nc.ConnectLink.summary().total == 2
    assert summary.calls.last.request.url.params["kind"] == "credential.connect"

    for method, name in ((nc.ConnectLink.list, "list"), (nc.ConnectLink.list_page, "list_page"),
                         (nc.ConnectLink.summary, "summary")):
        with pytest.raises(TypeError, match=rf"Operation\.{name}\b"):
            method(kind="agent.message")
    assert summary.call_count == 1


def test_human_request_summary_counts_only_human_request_operations(api, client):
    summary = api.get("/v1/operations/summary").respond(json={"total": 4, "by_status": {"awaiting_human": 3}})
    assert nc.HumanRequest.summary(status="live").total == 4
    params = summary.calls.last.request.url.params
    assert params["kind"] == "human.ask,human.approve,human.notify" and params["status"] == "live"
    with pytest.raises(TypeError, match=r"HumanRequest\.summary reads only"):
        nc.HumanRequest.summary(kind="ask")
    assert summary.call_count == 1


def test_a_users_own_agent_read_with_user_filter_goes_out_as_an_owner_read(api, client):
    api.get("/v1/agents/ag_1").respond(json={**AGENT, "user_id": USER_ID})
    route = api.get("/v1/agents/ag_1/conversations").respond(json=listing({"conversation": "c1"}))
    nc.Agent.from_id("ag_1").conversations_page(user_filter=nc.ALL_USERS)
    request = route.calls.last.request
    assert request.url.params["user_id"] == "all" and "NoClick-User" not in request.headers
    # Without the filter the agent's own user is the header, which any key may read.
    nc.Agent.from_id("ag_1").conversations_page()
    request = route.calls.last.request
    assert request.headers["NoClick-User"] == USER_ID and "user_id" not in request.url.params


def test_a_summary_or_series_missing_a_required_number_is_an_error(api, client):
    api.get("/v1/operations/summary").respond(json={"by_status": {}})
    with pytest.raises(nc.Error, match="`total`"):
        nc.Operation.summary()
    api.get("/v1/tool_calls/summary").respond(json={"total": 3, "success": 3})
    with pytest.raises(nc.Error, match="`error`"):
        nc.ToolCall.summary()
    api.get("/v1/usage/series").respond(json={"interval": "day", "total_usd": 1,
                                              "series": [{"id": "k", "total_usd": 1, "points": []}]})
    with pytest.raises(nc.Error, match="`events`"):
        nc.Usage.series()
    limits = api.get("/v1/usage/limits")
    limits.respond(json={"keys": [], "users": [], "agents": [{"id": "ag_1", "budget": None, "spent": 1}]})
    with pytest.raises(nc.Error, match="`subtree_spent`"):
        nc.Usage.limits()
    # Nullable numbers stay None.
    limits.respond(json={"keys": [{"id": "key_1", "cap": None, "spent": 0}], "users": [], "agents": []})
    key = nc.Usage.limits().keys[0]
    assert (key.cap, key.spent) == (None, 0)
