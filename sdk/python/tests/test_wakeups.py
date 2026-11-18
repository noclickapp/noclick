"""Wake-ups: ``agent.wake`` at a time, after a while, when an operation
settles or on a NoClick event, in the acting user's thread; ``agent.wakeups``,
a wake-up's reload and ``cancel``."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

import noclick as nc
from platform_helpers import USER_ID, agent_row, body, listing

AGENT = agent_row(id="ag_1", name="planner")
USER_AGENT = agent_row(id="ag_u", name="assistant", user_id=USER_ID)
WAKEUP = {
    "object": "wakeup", "id": "wk_1", "agent_id": "ag_1", "user_id": None, "conversation": "launch-plan",
    "note": "Check the research.", "at": "2026-10-02T07:00:00Z", "when": None, "source": "code", "status": "pending",
    "woken_by": None, "operation_id": None, "depth": 0, "error": None, "created_at": "2026-10-01T10:00:00Z",
    "delivered_at": None,
}


def test_every_call_has_sync_and_aio_forms():
    agent = nc.Agent.from_id("ag_1")
    for bound in (agent.wake, agent.wakeups, nc.Wakeup._new(raw=WAKEUP).cancel, nc.Wakeup._new(raw=WAKEUP).update):
        assert asyncio.iscoroutinefunction(bound.aio), bound


def test_wake_at_a_time_in_the_acting_users_conversation(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    wake = api.post("/v1/agents/ag_1/wakeups").respond(json=WAKEUP)
    at = datetime(2026, 10, 2, 9, 0, tzinfo=timezone(timedelta(hours=2)))
    with nc.as_user(USER_ID):
        wakeup = nc.Agent.from_id("ag_1").wake("launch-plan", at=at, note="Check the research.")
    assert body(wake.calls.last.request) == {
        "conversation": "launch-plan", "note": "Check the research.", "at": "2026-10-02T09:00:00+02:00",
    }
    # An account agent talked to by a user wakes in that user's thread.
    assert wake.calls.last.request.headers["NoClick-User"] == USER_ID
    assert isinstance(wakeup, nc.Wakeup)
    assert (wakeup.id, wakeup.status, wakeup.source, wakeup.depth) == ("wk_1", "pending", "code", 0)
    assert wakeup.at == datetime(2026, 10, 2, 7, 0, tzinfo=timezone.utc)
    assert wakeup.operation is None


def test_a_users_own_agent_wakes_in_its_users_thread(api, client):
    api.get("/v1/agents/ag_u").respond(json=USER_AGENT)
    wake = api.post("/v1/agents/ag_u/wakeups").respond(json={**WAKEUP, "agent_id": "ag_u"})
    nc.Agent.from_id("ag_u").wake("inbox", after=timedelta(hours=1), note="Look again.")
    assert body(wake.calls.last.request) == {"conversation": "inbox", "note": "Look again.", "after_s": 3600.0}
    assert wake.calls.last.request.headers["NoClick-User"] == USER_ID
    nc.Agent.from_id("ag_u").wake("inbox", after=90, note="Look again.")
    assert body(wake.calls.last.request)["after_s"] == 90


def test_wake_when_an_operation_settles(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    wake = api.post("/v1/agents/ag_1/wakeups").respond(json={**WAKEUP, "at": None, "when": {"operation_id": "op_h"}})
    agent = nc.Agent.from_id("ag_1")
    agent.wake("launch-plan", when=nc.Job.from_id("op_t"), note="The research is in.")
    assert body(wake.calls.last.request)["when"] == {"operation_id": "op_t"}
    wakeup = agent.wake("launch-plan", when=nc.HumanRequest.from_id("op_h"), note="Ana answered.")
    assert body(wake.calls.last.request)["when"] == {"operation_id": "op_h"}
    assert wakeup.at is None and wakeup.when == {"operation_id": "op_h"}
    # Several: it wakes once, when the last of them settles.
    agent.wake("launch-plan", when=[nc.Job.from_id("op_a"), nc.Job.from_id("op_b")], note="Both looks are in.")
    assert body(wake.calls.last.request)["when"] == {"operation_ids": ["op_a", "op_b"]}
    with pytest.raises(TypeError):
        agent.wake("launch-plan", when=[], note="Nothing to wait for.")


def test_wake_on_an_event_and_read_what_woke_it(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    when = {"event": "connection.connected", "filters": {"name": "gmail"}}
    wake = api.post("/v1/agents/ag_1/wakeups").respond(json={**WAKEUP, "at": None, "when": when})
    with nc.as_user("user_42"):
        wakeup = nc.Agent.from_id("ag_1").wake("inbox-zero", when="connection.connected", filters={"name": "gmail"},
                                               note="Gmail is in.")
    assert body(wake.calls.last.request) == {"conversation": "inbox-zero", "note": "Gmail is in.", "when": when}
    assert wake.calls.last.request.headers["NoClick-User"] == "user_42"
    assert wakeup.at is None and wakeup.when == when
    event = {"object": "event", "id": "evt_1", "type": "connection.connected", "user_id": "user_42",
             "created_at": "2026-10-01T10:05:00Z", "data": {"object": "connection", "name": "gmail"}}
    api.get("/v1/agents/ag_1/wakeups/wk_1").respond(json={
        **WAKEUP, "at": "2026-10-01T10:05:01Z", "when": when, "woken_by": {"event": event}, "status": "delivered"})
    wakeup.refresh()
    assert wakeup.status == "delivered" and wakeup.woken_by["event"]["data"]["name"] == "gmail"
    nc.Agent.from_id("ag_1").wake("anything", when="connection.*", note="A connection changed.")
    assert body(wake.calls.last.request)["when"] == {"event": "connection.*"}


def test_wake_refuses_anything_but_exactly_one_moment_and_a_note(api, client):
    agent = nc.Agent.from_id("ag_1")
    soon = datetime.now(timezone.utc) + timedelta(hours=1)
    with pytest.raises(ValueError, match="exactly one"):
        agent.wake("c", note="x")
    with pytest.raises(ValueError, match="exactly one of at=, after=, when= and every=; got at, after"):
        agent.wake("c", at=soon, after=60, note="x")
    with pytest.raises(ValueError, match="filters="):
        agent.wake("c", at=soon, filters={"name": "gmail"}, note="x")
    with pytest.raises(ValueError, match="timezone-aware"):
        agent.wake("c", at=datetime(2026, 10, 2, 9), note="x")
    with pytest.raises(ValueError, match="note="):
        agent.wake("c", after=60, note="  ")
    with pytest.raises(ValueError, match="4000"):
        agent.wake("c", after=60, note="x" * 4001)
    with pytest.raises(ValueError, match="time ahead"):
        agent.wake("c", after=0, note="x")
    with pytest.raises(TypeError, match="seconds or a timedelta"):
        agent.wake("c", after="1h", note="x")
    with pytest.raises(TypeError, match="Operation"):
        agent.wake("c", when=42, note="x")
    assert not api.calls  # every refusal is the client's own


def test_a_routine_wakes_on_a_schedule_and_changes(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    every = {"cron": "0 8 * * 1-5", "tz": "user"}
    view = {**WAKEUP, "every": every, "fired": 3}
    wake = api.post("/v1/agents/ag_1/wakeups").respond(json=view)
    with nc.as_user(USER_ID):
        briefing = nc.Agent.from_id("ag_1").wake("briefing", every=nc.Cron("0 8 * * 1-5", tz="user"),
                                                 note="Brief me on today's calendar.")
    assert body(wake.calls.last.request) == {"conversation": "briefing", "note": "Brief me on today's calendar.",
                                             "every": every}
    assert briefing.every == nc.Cron("0 8 * * 1-5", tz="user") and briefing.fired == 3
    assert nc.Wakeup._new(raw=WAKEUP).every is None

    patch = api.patch("/v1/agents/ag_1/wakeups/wk_1").respond(json={**view, "note": "Brief me at 7."})
    briefing.update(note="Brief me at 7.", every=nc.Cron("0 7 * * 1-5", tz="user"))
    assert body(patch.calls.last.request) == {"note": "Brief me at 7.", "every": {"cron": "0 7 * * 1-5", "tz": "user"}}
    assert briefing.note == "Brief me at 7."
    briefing.update(after=timedelta(hours=2))
    assert body(patch.calls.last.request) == {"after_s": 7200.0}

    with pytest.raises(ValueError, match="Nothing to change"):
        briefing.update()
    with pytest.raises(ValueError, match="one of at=, after= and every="):
        briefing.update(after=60, every=nc.Cron("0 7 * * *"))
    with pytest.raises(TypeError, match="noclick.Cron"):
        nc.Agent.from_id("ag_1").wake("c", every="0 9 * * 1", note="x")
    with pytest.raises(ValueError, match="no message="):
        nc.Agent.from_id("ag_1").wake("c", every=nc.Cron("0 9 * * 1", message="hi"), note="x")


def test_the_server_refuses_too_many_or_too_soon(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    wake = api.post("/v1/agents/ag_1/wakeups")
    wake.respond(429, json={"error": {"type": "quota_exceeded", "message": "The agent already has 100 pending wake-ups.",
                                      "limit": 100}})
    with pytest.raises(nc.QuotaExceeded):
        nc.Agent.from_id("ag_1").wake("c", after=60, note="x")
    wake.respond(400, json={"error": {"type": "invalid_request", "field": "at",
                                      "message": "A wake-up's time is between a minute and a year ahead."}})
    with pytest.raises(nc.InvalidRequest, match="a minute and a year"):
        nc.Agent.from_id("ag_1").wake("c", after=30, note="x")


def test_wakeups_list_filters_and_cancel(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    delivered = {**WAKEUP, "id": "wk_2", "status": "delivered", "operation_id": "op_m", "source": "wake_me", "depth": 2,
                 "woken_by": {"at": "2026-10-02T07:00:00+00:00"}, "delivered_at": "2026-10-02T07:00:01Z"}
    rows = api.get("/v1/agents/ag_1/wakeups").respond(json=listing(WAKEUP, delivered))
    cancel = api.post("/v1/agents/ag_1/wakeups/wk_1/cancel").respond(json={**WAKEUP, "status": "canceled"})
    pending, done = nc.Agent.from_id("ag_1").wakeups("launch-plan", status=["pending", "delivered"], limit=10)
    params = rows.calls.last.request.url.params
    assert (params["conversation"], params["status"], params["limit"]) == ("launch-plan", "pending,delivered", "10")
    assert done.operation.id == "op_m" and isinstance(done.operation, nc.Operation)
    assert (done.source, done.depth, done.woken_by) == ("wake_me", 2, {"at": "2026-10-02T07:00:00+00:00"})
    assert done.delivered_at.second == 1
    assert pending.cancel().status == "canceled"
    assert cancel.called
    with pytest.raises(ValueError, match="status"):
        nc.Agent.from_id("ag_1").wakeups(status="due")


def test_cancelling_one_that_already_ran_is_a_conflict(api, client):
    api.post("/v1/agents/ag_1/wakeups/wk_1/cancel").respond(409, json={"error": {
        "type": "conflict", "message": "The wake-up is already delivered.", "wakeup_status": "delivered"}})
    with pytest.raises(nc.Conflict, match="already delivered"):
        nc.Wakeup._new(raw=WAKEUP, client=client).cancel()


def test_a_wakeup_reloads_itself_under_its_agent(api, client):
    one = api.get("/v1/agents/ag_1/wakeups/wk_1").respond(json={**WAKEUP, "status": "failed",
                                                                  "error": {"type": "payment_required", "message": "No funds."}})
    wakeup = nc.Wakeup._new(raw=WAKEUP, client=client)
    wakeup.refresh()
    assert one.called and wakeup.status == "failed" and wakeup.error["type"] == "payment_required"


def test_wakeups_read_across_users_threads_and_cancel_in_each(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    theirs = {**WAKEUP, "id": "wk_2", "user_id": USER_ID, "conversation": "ada"}
    rows = api.get("/v1/agents/ag_1/wakeups").respond(json=listing(WAKEUP, theirs))
    cancel = api.post("/v1/agents/ag_1/wakeups/wk_2/cancel").respond(json={**theirs, "status": "canceled"})
    with nc.as_user(USER_ID):  # a filtered read never acts as a user
        ours, other = nc.Agent.from_id("ag_1").wakeups(status="pending", user_filter=nc.ALL_USERS)
    request = rows.calls.last.request
    assert (request.url.params["user_id"], request.url.params["status"]) == ("all", "pending")
    assert "NoClick-User" not in request.headers
    assert (ours.user_id, other.user_id) == (None, USER_ID)
    other.cancel()  # in the user's own thread
    assert cancel.calls.last.request.headers["NoClick-User"] == USER_ID
    nc.Agent.from_id("ag_1").wakeups(user_filter=nc.NO_USER)
    assert rows.calls.last.request.url.params["user_id"] == "none"
    with pytest.raises(TypeError, match="user_filter"):
        nc.Agent.from_id("ag_1").wakeups(user="someone", user_filter=nc.ALL_USERS)
