"""Agents that coordinate agents (designed, not built yet): agent listing and channel
subscriptions to NoClick's own events (spawn, jobs, ask and the agents capability are built:
test_jobs_and_ask.py; workspaces: test_workspaces.py)."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

import noclick as nc
from platform_helpers import USER_ID, agent_row, body, listing, operation

AGENT = agent_row(id="ag_1", name="planner")
USER_AGENT = agent_row(id="ag_u", name="assistant", user_id=USER_ID)
CHANNEL = {"object": "channel", "id": "ch_1", "name": "billing", "mode": "mentions", "status": "open", "members": []}


def subscription(**extra):
    return {"object": "subscription", "id": "sub_1", "channel_id": "ch_1", "workspace_id": None, "channels": None,
            "source": {"kind": "platform", "type": "operation.failed"}, "wake": None, "filters": None,
            "status": "active", "error": None, "url": None, "last_event_at": None, "created_at": "2026-10-01T10:00:00Z",
            **extra}


def test_every_new_call_has_sync_and_aio_forms():
    agent = nc.Agent.from_id("ag_1")
    room = nc.Channel.from_id("ch_1")
    ws = nc.Workspace.from_id("ws_1")
    for bound in (agent.ask, agent.spawn, agent.children, agent.jobs, room.subscribe,
                  room.subscriptions, ws.update, ws.archive, ws.delete, ws.channels, ws.add, ws.remove, ws.subscribe,
                  ws.subscriptions, nc.Workspace.create, nc.Workspace.list, nc.Workspace.get, nc.Job.from_id("op_t").updates):
        assert asyncio.iscoroutinefunction(bound.aio), bound


# --- listing --------------------------------------------------------------------------

def test_list_takes_the_new_filters(api, client):
    rows = api.get("/v1/agents").respond(json=listing({**AGENT, "status": "working", "running_turns": 2,
                                                       "child_count": 3, "last_active_at": "2026-10-01T09:59:00Z"}))
    since = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
    [agent] = nc.Agent.list(status="working", active_since=since, parent=nc.Agent.from_id("ag_p"), temporary=False,
                            harness="claude_code", order="last_active")
    params = dict(rows.calls.last.request.url.params)
    assert params == {"status": "working", "active_since": "2026-10-01T09:00:00+00:00", "parent_id": "ag_p",
                      "temporary": "false", "harness": "claude_code", "order": "last_active"}
    assert (agent.status, agent.running_turns, agent.child_count) == ("working", 2, 3)
    assert agent.last_active_at == datetime(2026, 10, 1, 9, 59, tzinfo=timezone.utc)
    nc.Agent.list_page(temporary=True, limit=5)
    assert rows.calls.last.request.url.params["temporary"] == "true"


def test_list_refuses_an_unknown_status_or_order(api, client):
    with pytest.raises(ValueError, match="status"):
        nc.Agent.list(status="paused")  # pausing stops triggers, not work: read agent.paused
    with pytest.raises(ValueError, match="order"):
        nc.Agent.list_page(order="newest")
    assert not api.calls


def test_children_are_the_list_of_its_children_where_it_lives(api, client):
    api.get("/v1/agents/ag_u").respond(json=USER_AGENT)
    rows = api.get("/v1/agents").respond(json=listing(agent_row(id="ag_k", parent_id="ag_u", status="expired")))
    [child] = nc.Agent.from_id("ag_u").children(status="expired")
    assert rows.calls.last.request.url.params["parent_id"] == "ag_u"
    assert rows.calls.last.request.url.params["status"] == "expired"
    assert rows.calls.last.request.headers["NoClick-User"] == USER_ID
    assert child.status == "expired"


def test_an_account_agents_children_and_jobs_are_read_as_the_account(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    rows = api.get("/v1/agents").respond(json=listing())
    jobs = api.get("/v1/agents/ag_1/jobs").respond(json=listing())
    with nc.as_user(USER_ID):
        nc.Agent.from_id("ag_1").children()
        nc.Agent.from_id("ag_1").jobs()
    assert "NoClick-User" not in rows.calls.last.request.headers
    assert "NoClick-User" not in jobs.calls.last.request.headers


# --- channel subscriptions (built in test_triggers.py; NoClick's own events stay designed) ---------

def test_subscribe_to_noclicks_own_events(api, client):
    sub = api.post("/v1/channels/ch_1/subscriptions").respond(json=subscription())
    nc.Channel.from_id("ch_1").subscribe("connection.disconnected")
    assert body(sub.calls.last.request) == {"source": {"kind": "platform", "type": "connection.disconnected"},
                                            "wake": None}
    with pytest.raises(TypeError, match="wake="):
        nc.Channel.from_id("ch_1").subscribe("operation.failed", wake="billing")

