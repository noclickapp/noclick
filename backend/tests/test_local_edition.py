"""Local edition (NOCLICK_LOCAL=1) — in-process event relay contract.

Pins three things:
1. LocalExecutionRelay is a faithful duck-type of ExecutionRelay (the handler
   sites and wss.sender consume the surface, so drift = broken local runs).
2. The hub's fan-out semantics mirror the managed relays (execution buffer,
   stop signals, user-event workflow filtering, request/response).
3. The WebSocket routes speak the exact browser protocol (useEventRelay +
   workflowPresenceService connect unchanged, only re-pointed via env).
"""

import asyncio
import json
import time

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import utils.local_relay as local_relay_module
from utils.local_relay import (
    LocalExecutionRelay,
    LocalRelayHub,
    UserConn,
    get_local_relay_hub,
)


@pytest.fixture(autouse=True)
def fresh_hub():
    """Each test gets an isolated hub singleton."""
    local_relay_module._hub = LocalRelayHub()
    yield local_relay_module._hub
    local_relay_module._hub = None


class FakeSocket:
    """Collects everything the hub sends; can be flipped dead."""

    def __init__(self):
        self.sent = []
        self.dead = False

    async def send_json(self, data):
        if self.dead:
            raise RuntimeError("socket closed")
        self.sent.append(data)


# ── 1. Duck-type parity ──────────────────────────────────────────────────


def test_local_relay_matches_execution_relay_surface():
    """Every public attribute the handlers/sender use on ExecutionRelay must
    exist on LocalExecutionRelay with compatible call shapes."""
    relay = LocalExecutionRelay("wf", "ex", "u")
    for name in (
        "workflow_id", "execution_id", "user_id", "connect_error",
        "connected", "start", "connect", "ready",
        "send_event", "listen_for_stop", "close",
    ):
        assert hasattr(relay, name), f"LocalExecutionRelay missing {name}"


def test_create_execution_relay_dispatches_by_edition(monkeypatch):
    from utils.execution_relay import ExecutionRelay, create_execution_relay

    monkeypatch.delenv("NOCLICK_LOCAL", raising=False)
    assert isinstance(create_execution_relay("wf", "ex", "u"), ExecutionRelay)

    monkeypatch.setenv("NOCLICK_LOCAL", "1")
    assert isinstance(create_execution_relay("wf", "ex", "u"), LocalExecutionRelay)


# ── 2. Hub semantics ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execution_events_reach_viewers_with_execution_id_stamped(fresh_hub):
    sock = FakeSocket()
    fresh_hub.register_workflow_conn("wf1", sock, user_id="u1", name="U", avatar_url=None)

    relay = LocalExecutionRelay("wf1", "exec1", "u1")
    relay.start()
    assert relay.connected
    await relay.send_event({"type": "workflow:started", "workflow_id": "wf1"})
    # workflow:node:output carries no execution_id in its schema — the relay
    # must stamp it (relay parity) so the recovery buffer keys correctly.
    await relay.send_event({"type": "workflow:node:state", "node_id": "n1", "state": "running"})
    await relay.send_event({"type": "workflow:node:output", "node_id": "n1", "output": {"x": 1}})

    types = [m["type"] for m in sock.sent]
    assert types == ["workflow:started", "workflow:node:state", "workflow:node:output"]
    assert all(m["execution_id"] == "exec1" for m in sock.sent)

    snapshot = fresh_hub.execution_state_snapshot("wf1")
    assert snapshot["executions"] == [{
        "executionId": "exec1",
        "nodeStates": {"n1": "running"},
        "nodeOutputs": {"n1": {"x": 1}},
    }]
    assert snapshot["agents"] == []

    await relay.send_event({"type": "workflow:complete", "success": True})
    assert fresh_hub.execution_state_snapshot("wf1")["executions"] == []
    await relay.close()


@pytest.mark.asyncio
async def test_stop_signal_cancels_execution(fresh_hub):
    relay = LocalExecutionRelay("wf1", "exec1", "u1")
    relay.start()
    cancellation = asyncio.Event()

    async def _fake_run():
        await asyncio.sleep(30)

    execution_task = asyncio.create_task(_fake_run())
    listen_task = asyncio.create_task(relay.listen_for_stop(cancellation, execution_task))
    await asyncio.sleep(0)  # let listen register its handle

    assert fresh_hub.fire_stop("exec1") is True
    await asyncio.sleep(0)
    assert cancellation.is_set()
    with pytest.raises(asyncio.CancelledError):
        await execution_task
    await asyncio.wait_for(listen_task, timeout=1)
    await relay.close()


@pytest.mark.asyncio
async def test_stop_before_listener_registers_is_honored(fresh_hub):
    """A viewer's stop can land in the window before listen_for_stop spawns."""
    assert fresh_hub.fire_stop("exec-early") is False  # queued as pending

    relay = LocalExecutionRelay("wf1", "exec-early", "u1")
    relay.start()
    cancellation = asyncio.Event()
    listen_task = asyncio.create_task(relay.listen_for_stop(cancellation, None))
    await asyncio.wait_for(listen_task, timeout=1)  # pending stop fires immediately
    assert cancellation.is_set()
    await relay.close()


@pytest.mark.asyncio
async def test_close_with_live_execution_synthesizes_crash_complete(fresh_hub):
    sock = FakeSocket()
    fresh_hub.register_workflow_conn("wf1", sock, user_id="u1", name="U", avatar_url=None)

    relay = LocalExecutionRelay("wf1", "exec1", "u1")
    relay.start()
    await relay.send_event({"type": "workflow:started"})
    await relay.close()  # no workflow:complete was ever sent

    last = sock.sent[-1]
    assert last["type"] == "workflow:complete"
    assert last["success"] is False
    assert last["execution_id"] == "exec1"
    assert fresh_hub.execution_state_snapshot("wf1")["executions"] == []


@pytest.mark.asyncio
async def test_user_events_respect_workflow_subscription(fresh_hub):
    everything = FakeSocket()
    filtered = FakeSocket()
    fresh_hub.register_user_conn(UserConn(socket=everything, user_id="u1"))
    fresh_hub.register_user_conn(UserConn(socket=filtered, user_id="u1", workflow_id="wfA"))

    await fresh_hub.publish_user_event("u1", {"type": "e1"})
    await fresh_hub.publish_user_event("u1", {"type": "e2"}, workflow_id="wfA")
    await fresh_hub.publish_user_event("u1", {"type": "e3"}, workflow_id="wfB")
    await fresh_hub.publish_user_event("other-user", {"type": "e4"})

    assert [m["type"] for m in everything.sent] == ["e1", "e2", "e3"]
    assert [m["type"] for m in filtered.sent] == ["e1", "e2"]


@pytest.mark.asyncio
async def test_dead_socket_is_dropped_on_send(fresh_hub):
    sock = FakeSocket()
    conn = UserConn(socket=sock, user_id="u1")
    fresh_hub.register_user_conn(conn)
    sock.dead = True
    sent = await fresh_hub.publish_user_event("u1", {"type": "e1"})
    assert sent == 0
    assert "u1" not in fresh_hub._user_conns


@pytest.mark.asyncio
async def test_request_frontend_roundtrip(fresh_hub):
    sock = FakeSocket()
    fresh_hub.register_user_conn(UserConn(socket=sock, user_id="u1"))

    async def _respond():
        while not sock.sent:
            await asyncio.sleep(0.01)
        req = sock.sent[0]
        assert req["type"] == "mcp_request"
        fresh_hub.resolve_frontend_response(req["request_id"], {"answer": 42}, None)

    responder = asyncio.create_task(_respond())
    result = await fresh_hub.request_frontend("u1", "eval", {"expr": "6*7"}, timeout=2)
    await responder
    assert result == {"data": {"answer": 42}, "error": None}


@pytest.mark.asyncio
async def test_request_frontend_without_viewers_errors(fresh_hub):
    result = await fresh_hub.request_frontend("nobody", "eval", {}, timeout=0.1)
    assert result == {"error": "No browser sessions connected"}


@pytest.mark.asyncio
async def test_broadcast_to_user_safe_routes_locally(monkeypatch, fresh_hub):
    monkeypatch.setenv("NOCLICK_LOCAL", "1")
    from pydantic import BaseModel
    from utils.event_relay import broadcast_to_user_safe

    class _Evt(BaseModel):
        event_name: str = "test:event"
        value: int = 7

    sock = FakeSocket()
    fresh_hub.register_user_conn(UserConn(socket=sock, user_id="u1"))
    result = await broadcast_to_user_safe("u1", _Evt())
    assert result["success"] is True
    assert sock.sent == [{"type": "test:event", "event_name": "test:event", "value": 7}]


# ── 3. WebSocket route protocol ──────────────────────────────────────────


@pytest.fixture
def relay_app(monkeypatch):
    monkeypatch.setenv("NOCLICK_LOCAL", "1")
    monkeypatch.setenv("WORKFLOW_JWT_SECRET", "test-secret")
    from utils.local_relay_routes import router

    app = FastAPI()
    app.include_router(router)
    return app


def _collab_token(workflow_id: str, user_id: str = "u1", name: str = "Tester") -> str:
    return jwt.encode(
        {
            "sub": user_id, "workflowId": workflow_id, "name": name,
            "role": "viewer", "iat": int(time.time()), "exp": int(time.time()) + 600,
        },
        "test-secret", algorithm="HS256",
    )


def test_user_room_protocol(relay_app, fresh_hub):
    client = TestClient(relay_app)
    with client.websocket_connect("/relay/u1?workflowId=wfA") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "connected"
        assert hello["connectionCount"] == 1

        # Raw-text keepalive (relay auto-response parity — the FE checks the raw string)
        ws.send_text("ping")
        assert ws.receive_text() == "pong"

        ws.send_text(json.dumps({"type": "subscribe", "workflowId": "wfB"}))
        assert ws.receive_json() == {"type": "subscribed", "workflowId": "wfB"}
        ws.send_text(json.dumps({"type": "unsubscribe"}))
        assert ws.receive_json() == {"type": "unsubscribed"}


def test_workflow_room_auth_and_execution_replay(relay_app, fresh_hub):
    # Buffered state from a run that started before the viewer connected
    fresh_hub._update_execution_state("wfA", {
        "type": "workflow:started", "execution_id": "ex1",
    })
    fresh_hub._update_execution_state("wfA", {
        "type": "workflow:node:state", "execution_id": "ex1",
        "node_id": "n1", "state": "running",
    })

    client = TestClient(relay_app)
    with client.websocket_connect("/relay/workflow/wfA") as ws:
        assert ws.receive_json() == {"type": "auth:required"}
        ws.send_text(json.dumps({"type": "auth", "token": _collab_token("wfA")}))
        success = ws.receive_json()
        assert success["type"] == "auth:success"
        assert success["collaborators"] == []

        ws.send_text(json.dumps({"type": "get:execution_state"}))
        state = ws.receive_json()
        assert state["type"] == "execution_state"
        assert state["executions"][0]["executionId"] == "ex1"
        assert state["executions"][0]["nodeStates"] == {"n1": "running"}

        # Stop routing: a viewer stop reaches a registered handle
        fired = {}
        fresh_hub.register_stop_handle("ex1", asyncio.Event(), None)
        ws.send_text(json.dumps({"type": "execution:stop", "executionId": "ex1"}))
        # Round-trip a ping so the stop message is processed before we assert
        ws.send_text(json.dumps({"type": "ping"}))
        assert ws.receive_json()["type"] == "pong"
        assert fresh_hub._stop_handles["ex1"].done.is_set()


def test_workflow_room_rejects_bad_token(relay_app, fresh_hub):
    client = TestClient(relay_app)
    with client.websocket_connect("/relay/workflow/wfA") as ws:
        assert ws.receive_json()["type"] == "auth:required"
        ws.send_text(json.dumps({"type": "auth", "token": _collab_token("OTHER-wf")}))
        assert ws.receive_json()["type"] == "auth:error"


def test_workflow_room_presence_fanout(relay_app, fresh_hub):
    # Entered as a context manager so both websocket sessions share the
    # client's single portal (one event loop). Bare TestClient gives each
    # session its OWN portal thread, and the hub then awaits send_json on a
    # socket owned by a foreign loop — anyio streams aren't cross-loop safe,
    # so the delivery wakeup is occasionally lost and receive_json() blocks
    # forever (wedged the open-edition CI suite for hours, 2026-08-22).
    with TestClient(relay_app) as client, \
         client.websocket_connect("/relay/workflow/wfA") as ws1, \
         client.websocket_connect("/relay/workflow/wfA") as ws2:
        # Auth alice to completion first: bob's auth:success must list her.
        assert ws1.receive_json()["type"] == "auth:required"
        ws1.send_text(json.dumps({"type": "auth", "token": _collab_token("wfA", user_id="alice", name="alice")}))
        assert ws1.receive_json()["type"] == "auth:success"

        assert ws2.receive_json()["type"] == "auth:required"
        ws2.send_text(json.dumps({"type": "auth", "token": _collab_token("wfA", user_id="bob", name="bob")}))
        auth2 = ws2.receive_json()
        assert auth2["type"] == "auth:success"
        assert [c["id"] for c in auth2["collaborators"]] == ["alice"]
        assert ws1.receive_json()["type"] == "collaborator:join"  # bob joined

        ws1.send_text(json.dumps({"type": "presence:cursor", "x": 10, "y": 20}))
        cursor = ws2.receive_json()
        assert cursor == {"type": "presence:cursor", "userId": "alice", "x": 10, "y": 20}

        # Unknown payload keys must not pass through the fan-out
        ws1.send_text(json.dumps({"type": "node:update", "nodeId": "n1", "data": {"a": 1}, "sneaky": True}))
        update = ws2.receive_json()
        assert update == {"type": "node:update", "userId": "alice", "nodeId": "n1", "data": {"a": 1}}


# ── 4. Local cron pure helpers ───────────────────────────────────────────


def test_local_cron_next_run_computation():
    from utils.local_cron import _compute_next_run, _parse_run_at
    from datetime import datetime, timezone as tz

    nxt = _compute_next_run("*/5 * * * *", "UTC")
    now = datetime.now(tz.utc)
    assert nxt > now
    assert (nxt - now).total_seconds() <= 5 * 60
    assert nxt.tzinfo is not None

    parsed = _parse_run_at("2030-01-01T00:00:00Z")
    assert parsed == datetime(2030, 1, 1, tzinfo=tz.utc)


def _frozen_local_cron(frozen):
    from datetime import datetime
    from unittest.mock import patch
    from zoneinfo import ZoneInfo

    class _FrozenDT(datetime):
        @classmethod
        def now(cls, tzinfo=None):
            return frozen.astimezone(tzinfo or ZoneInfo("UTC"))

    return patch("utils.local_cron.datetime", _FrozenDT)


def test_local_cron_evaluates_expressions_in_schedule_timezone():
    """Same contract as the CF worker: expressions are LOCAL wall-clock in
    the schedule's timezone (windowed weekday schedules depend on this)."""
    from utils.local_cron import _compute_next_run
    from datetime import datetime, timezone as tz

    # Friday 2026-07-03 22:30 UTC = 18:30 New York — past the window's last
    # fire; the next must be Monday 9:00 NY = 13:00 UTC (EDT).
    with _frozen_local_cron(datetime(2026, 7, 3, 22, 30, tzinfo=tz.utc)):
        nxt = _compute_next_run("0-59/30 9-17 * * 1-5", "America/New_York")
    assert nxt == datetime(2026, 7, 6, 13, 0, tzinfo=tz.utc)


def test_local_cron_is_dst_correct_across_fall_back():
    """The day-walker exists because croniter iteration lands fires ±1h around
    DST transitions: from Sat Oct 31 2026, the next daily-9am NY fire is
    Sun Nov 1 9:00 EST = 14:00 UTC (croniter returned 15:00 = 10:00 local)."""
    from utils.local_cron import _compute_next_run
    from datetime import datetime, timezone as tz

    with _frozen_local_cron(datetime(2026, 10, 31, 16, 0, tzinfo=tz.utc)):
        nxt = _compute_next_run("0 9 * * *", "America/New_York")
    assert nxt == datetime(2026, 11, 1, 14, 0, tzinfo=tz.utc)


def test_local_cron_speaks_the_custom_duration_and_weeks_formats():
    """"/Nh" and "base /Nw" previously failed croniter parsing outright, so
    every-5-hours and every-2-weeks schedules could never register locally."""
    from utils.local_cron import _compute_next_run
    from datetime import datetime, timedelta, timezone as tz

    frozen = datetime(2026, 7, 6, 14, 0, tzinfo=tz.utc)  # Monday 10:00 NY
    with _frozen_local_cron(frozen):
        assert _compute_next_run("0 0 * * * /5h", "UTC") == frozen + timedelta(hours=5)

        # Biweekly Monday 9:00 NY, anchored on this morning's fire → skips
        # next Monday for the one after (worker-parity stepping).
        anchored = _compute_next_run(
            "0 9 * * 1 /2w", "America/New_York",
            last_run=datetime(2026, 7, 6, 13, 0, tzinfo=tz.utc),
        )
        assert anchored == datetime(2026, 7, 20, 13, 0, tzinfo=tz.utc)
        # No anchor (first-ever fire) → next weekly occurrence.
        assert _compute_next_run("0 9 * * 1 /2w", "America/New_York") == \
            datetime(2026, 7, 13, 13, 0, tzinfo=tz.utc)


def test_local_cron_constrained_seconds_and_impossible_expressions():
    from utils.local_cron import _compute_next_run
    from datetime import datetime, timedelta, timezone as tz
    import pytest as _pytest

    # In-window Wednesday 10:30 NY: candidate now+10s stands.
    frozen = datetime(2026, 7, 1, 14, 30, 7, tzinfo=tz.utc)
    with _frozen_local_cron(frozen):
        assert _compute_next_run("*/10s * 9-17 * * 1-5", "America/New_York") == \
            frozen + timedelta(seconds=10)
    # Out-of-window Friday evening: sleeps to Monday 9:00 NY.
    with _frozen_local_cron(datetime(2026, 7, 3, 22, 30, tzinfo=tz.utc)):
        assert _compute_next_run("*/10s * 9-17 * * 1-5", "America/New_York") == \
            datetime(2026, 7, 6, 13, 0, tzinfo=tz.utc)
    # A never-fires expression raises (create → 400) instead of scanning forever.
    with _frozen_local_cron(datetime(2026, 7, 1, tzinfo=tz.utc)):
        with _pytest.raises(ValueError):
            _compute_next_run("0 9 30-31 2 *", "UTC")


@pytest.mark.asyncio
async def test_agent_presence_deltas_and_snapshot(fresh_hub):
    sock = FakeSocket()
    fresh_hub.register_workflow_conn("wfP", sock, user_id="u1", name="U", avatar_url=None)

    await fresh_hub.set_agent_presence("wfP", "agent1", "ck1", "u1", busy=True)
    await fresh_hub.set_agent_presence("wfP", "agent1", "ck1", "u1", busy=True)  # steady beat: silent
    await fresh_hub.set_agent_presence("wfP", "agent1", "ck1", "u1", busy=False)
    await fresh_hub.clear_agent_presence("wfP", "agent1", "ck1")

    frames = [m for m in sock.sent if m["type"] == "agent:presence"]
    assert len(frames) == 3  # appear, busy-flip, clear — no steady-beat spam
    assert frames[0]["agents"] == [
        {"nodeId": "agent1", "conversationKey": "ck1", "userId": "u1", "busy": True}
    ]
    assert frames[-1]["agents"] == []

    await fresh_hub.set_agent_presence("wfP", "agent2", "ck", "u1", busy=True)
    snapshot = fresh_hub.execution_state_snapshot("wfP")
    assert snapshot["agents"] == [
        {"nodeId": "agent2", "conversationKey": "ck", "userId": "u1", "busy": True}
    ]
