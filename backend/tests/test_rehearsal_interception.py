"""A rehearsal must not be able to touch a real account.

The promise of scripted rehearsal is not "we try not to send things" — it is
that `run_node_operation` is never reached, so no credential is resolved and no
provider request is made. Safety is structural rather than a policy someone can
forget to apply, and these tests are what makes that claim checkable.

Two mirrors, because the runtimes reach tools by different routes: the
in-process SDK agent through `execute_tool`, and MCP-served harness tools
through `run_node_op_tool`. Gating one and not the other would leave the
harnesses executing for real.
"""

from __future__ import annotations

from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]


class FakeNode:
    """Just enough of an agent node for the tool choke point."""

    def __init__(self, conversation_id="conv-rehearsing"):
        self.conversation_id = conversation_id
        self.workflow_id = "wf-1"
        self.execution_id = "ex-1"
        self.user_id = "user-1"
        self.node_id = "agent-1"
        self.organization_id = None


NODE_OP_TOOL = {
    "slack__send_message_to_channel": {
        "tool_type": "node_op",
        "node_type": "automation-slack",
        "operation": "send_message_to_channel",
        "credential_id": "cred-1",
        "_description": "Post a message to a Slack channel",
    }
}


@pytest.fixture
def no_audit(monkeypatch):
    """The durable audit record is fire-and-forget and needs a DB; stub it."""
    monkeypatch.setattr("utils.tool_call_log.record_tool_call", lambda **kw: None)


@pytest.fixture
def tripwire(monkeypatch):
    """Explodes if anything reaches the real provider path."""
    calls = []

    async def boom(*a, **kw):
        calls.append(kw)
        raise AssertionError(
            "run_node_operation was reached during a rehearsal — a fabricated "
            "run just executed against a real account"
        )

    monkeypatch.setattr("nodes.core.run_op.run_node_operation", boom)
    return calls


def _rehearsing(monkeypatch, yes=True, result=None):
    async def _is(conversation_id):
        return yes

    async def _mock(**kw):
        return result if result is not None else {"ok": True, "ts": "1786.0001"}

    monkeypatch.setattr("nodes.agent.rehearsal.is_rehearsing", _is)
    monkeypatch.setattr("nodes.agent.tool_execution.is_rehearsing", _is)
    monkeypatch.setattr("nodes.agent.rehearsal.mock_tool_call", _mock)


# ------------------------------------------------- mirror 1: in-process


@pytest.mark.asyncio
async def test_in_process_rehearsal_never_reaches_the_provider(
    monkeypatch, no_audit, tripwire
):
    from nodes.agent.tool_execution import execute_tool

    _rehearsing(monkeypatch)
    result = await execute_tool(
        FakeNode(), "slack__send_message_to_channel", {"channel": "#sales"}, NODE_OP_TOOL
    )
    assert result == {"ok": True, "ts": "1786.0001"}
    assert not tripwire, "the real provider path must not be entered at all"


@pytest.mark.asyncio
async def test_a_normal_run_still_reaches_the_provider(monkeypatch, no_audit):
    """The gate must be inert outside a rehearsal, or it breaks every real run."""
    from nodes.agent.tool_execution import execute_tool

    _rehearsing(monkeypatch, yes=False)
    reached = []

    async def real(*a, **kw):
        reached.append(kw)
        return {"success": True, "sent": True}

    monkeypatch.setattr("nodes.core.run_op.run_node_operation", real)

    result = await execute_tool(
        FakeNode(), "slack__send_message_to_channel", {"channel": "#sales"}, NODE_OP_TOOL
    )
    assert reached, "a non-rehearsing run must execute for real"
    assert result["success"] is True


@pytest.mark.asyncio
async def test_the_agents_own_config_is_not_fabricated(monkeypatch, no_audit):
    """describe_workflow reads the REAL workflow, and must keep doing so.

    Fabricating it would have the agent reason about a workflow that does not
    exist — the one place where mocking makes the rehearsal less truthful rather
    than more contained.
    """
    from nodes.agent.tool_execution import execute_tool

    async def _is(conversation_id):
        return True

    fabricated = []

    async def _mock(**kw):
        fabricated.append(kw["tool_name"])
        return {"workflow": "<fabricated>"}

    monkeypatch.setattr("nodes.agent.tool_execution.is_rehearsing", _is)
    monkeypatch.setattr("nodes.agent.rehearsal.mock_tool_call", _mock)

    tools = {"describe_workflow": {"tool_type": "describe_workflow"}}
    await execute_tool(FakeNode(), "describe_workflow", {}, tools)

    assert not fabricated, (
        "describe_workflow was answered by the mock. The agent must see its own "
        f"real configuration during a rehearsal, not a fabricated one: {fabricated}"
    )


@pytest.mark.asyncio
async def test_a_failed_simulation_surfaces_as_a_tool_error(monkeypatch, no_audit, tripwire):
    """Never fall through to the real call when the mock fails.

    Falling through would mean a rehearsal quietly sending a real Slack message
    the moment the mock model had a bad minute.
    """
    from nodes.agent.rehearsal import RehearsalUnavailable
    from nodes.agent.tool_execution import execute_tool

    async def _is(conversation_id):
        return True

    async def _boom(**kw):
        raise RehearsalUnavailable("model unreachable")

    monkeypatch.setattr("nodes.agent.tool_execution.is_rehearsing", _is)
    monkeypatch.setattr("nodes.agent.rehearsal.mock_tool_call", _boom)

    result = await execute_tool(
        FakeNode(), "slack__send_message_to_channel", {"channel": "#sales"}, NODE_OP_TOOL
    )
    assert result["success"] is False
    assert "rehearsal" in result["error"]
    assert not tripwire


# --------------------------------------------- mirror 2: cross-container


@pytest.mark.asyncio
async def test_cli_harness_path_never_reaches_the_provider(monkeypatch, tripwire):
    """The MCP-served path the CLI harnesses use."""
    from nodes.core.run_op import run_node_op_tool

    _rehearsing(monkeypatch)
    out = await run_node_op_tool(
        {
            "tool_type": "node_op",
            "node_type": "automation-slack",
            "operation": "send_message_to_channel",
            "credential_id": "cred-1",
        },
        {"channel": "#sales"},
        user_id="user-1",
        conversation_id="conv-rehearsing",
    )
    assert out == {"ok": True, "ts": "1786.0001"}
    assert not tripwire


def test_graph_nodes_cannot_act_on_real_accounts_in_a_rehearsal():
    """The tool gates cover the AGENT'S calls; graph nodes are a separate
    execution path. A send node wired after the agent — or, before start_node
    semantics, any disconnected credentialed node on the canvas — executed for
    real during a test. Two mirrors again: the concurrent runner skips visibly,
    and _execute_node raises for callers that bypass the runner (iteration
    bodies)."""
    text = (BACKEND / "wss/handlers/workflow_execution_handler.py").read_text()
    assert text.count("rehearsal_excluded_node_types") >= 2, (
        "the runner skip and the _execute_node mirror must BOTH gate on "
        "rehearsal_excluded_node_types — one alone leaves a path (iteration "
        "bodies, or a runner refactor) that executes for real"
    )
    assert "is_rehearsal_conversation" in text


def test_the_rehearsal_runs_from_the_fired_trigger_only():
    """Real deliveries run the reachable subgraph from the trigger; a rehearsal
    that runs the whole canvas executes every parentless node as a start node —
    which is how a disconnected Gmail node failed a Telegram test on
    credentials."""
    # The dispatch lives in the shared launcher (one implementation for the
    # socket handler AND the public template page's anonymous runs).
    text = (BACKEND / "nodes/agent/rehearsal_launch.py").read_text()
    assert "start_node_id=trigger_node_id" in text, (
        "launch_rehearsal must dispatch with start_node_id so the test mimics "
        "a real trigger delivery instead of a whole-canvas manual run"
    )


def test_the_exclusion_set_is_registry_derived_and_correct():
    from nodes.agent.rehearsal import (
        is_rehearsal_conversation,
        rehearsal_excluded_node_types,
    )

    excluded = rehearsal_excluded_node_types()
    # Credentialed integrations, from the registry — including API-key nodes,
    # which the x-credential-type marker famously missed (Telegram).
    for t in (
        "automation-gmail",
        "automation-telegram",
        "automation-slack",
        "automation-whatsapp",
        "automation-linear",
    ):
        assert t in excluded, f"{t} is credentialed and must never execute in a test"
    # Credential-less external actors, by name.
    for t in ("automation-send-email", "automation-http-request", "noclick"):
        assert t in excluded, f"{t} acts externally without a credential"
    # The world the rehearsal NEEDS: the agent itself, data providers, and pure
    # compute must keep executing or trigger→transform→agent graphs break.
    for t in (
        "agent",
        "interface-form",
        "state-manager",
        "automation-serverless-function",
        "iteration",
    ):
        assert t not in excluded, f"{t} must keep executing during a test"

    assert is_rehearsal_conversation("rehearsal:wf-1:abc123")
    assert not is_rehearsal_conversation("conv-1")
    assert not is_rehearsal_conversation(None)


# ------------------------------------- the fence must outlive an async turn


class _FakeRedis:
    def __init__(self):
        self.store = {}

    async def set(self, key, value, ex=None):
        self.store[key] = value.encode() if isinstance(value, str) else value

    async def get(self, key):
        return self.store.get(key)

    async def delete(self, key):
        self.store.pop(key, None)


def _launch_rig(monkeypatch, agent_output):
    """Rig launch_rehearsal's collaborators around a graph whose agent
    produces ``agent_output``, capturing frames + the spawned run coro."""
    import json
    from types import SimpleNamespace

    fake = _FakeRedis()
    monkeypatch.setattr("utils.redis_client.get_shared_redis", lambda: fake)
    monkeypatch.setattr("utils.socket_singleton.get_sio", lambda: object())

    nodes = [
        {"id": "t1", "type": "automation-telegram", "config": {}},
        {"id": "agent-1", "type": "agent", "config": {}},
    ]
    edges = [{"source": "t1", "target": "agent-1"}]

    class RigHandler:
        def __init__(self, sio):
            pass

        async def _fetch_workflow(self, workflow_id, user_id):
            return nodes, edges, None, {}, {}

        async def handle_execute(self, sid, request, caller_user_id=None):
            return SimpleNamespace(
                success=True,
                node_outputs={"t1": {}, "agent-1": agent_output},
                last_output_node_id="agent-1",
                error=None,
            )

    monkeypatch.setattr(
        "wss.handlers.workflow_execution_handler.WorkflowExecutionHandler", RigHandler
    )

    from billing.usage_tracker import usage_tracker

    async def _owner(user_id, org):
        return user_id

    async def _balance(user_id):
        return None

    monkeypatch.setattr(usage_tracker, "resolve_billing_user_id", _owner)
    monkeypatch.setattr(usage_tracker, "check_credit_balance", _balance)

    finished = []

    async def _finish(conversation_id, reply, error=None):
        finished.append((conversation_id, reply, error))

    monkeypatch.setattr("nodes.agent.rehearsal.emit_rehearsal_finished", _finish)

    spawned = []
    monkeypatch.setattr(
        "utils.async_helpers.spawn", lambda coro, name=None: spawned.append(coro)
    )
    return fake, finished, spawned


@pytest.mark.asyncio
async def test_a_synchronous_turn_still_finishes_inline(monkeypatch):
    """The SDK path completes inside handle_execute; the launcher must keep
    emitting + tearing down there or every sync rehearsal hangs to TTL."""
    from nodes.agent import rehearsal as rh
    from nodes.agent.rehearsal_launch import launch_rehearsal

    fake, finished, spawned = _launch_rig(monkeypatch, {"response": "Booked it."})
    cid, error = await launch_rehearsal(
        workflow_id="wf-1",
        scenario_key="generic:automation-telegram",
        user_id="user-1",
    )
    assert error is None
    await spawned[0]

    assert finished == [(cid, "Booked it.", None)]
    assert not await rh.is_rehearsing(cid)


@pytest.mark.asyncio
async def test_a_structured_reply_still_delivers_the_done_frame(monkeypatch):
    """A structured agent's `response` is a parsed DICT. The done frame's
    `reply` is typed str, so the dict failed Pydantic validation inside
    _emit_progress's never-raise guard — the terminal frame silently vanished
    and the Test Run screen spun forever (2026-08-21). The launcher must hand
    the emitter text, and that text must survive the frame's validation."""
    from nodes.agent.rehearsal_launch import launch_rehearsal
    from wss.sender.events import RehearsalProgressEvent

    raw = '```json\n{"summary": "the staged event was empty"}\n```'
    fake, finished, spawned = _launch_rig(
        monkeypatch,
        {
            "type": "agent",
            "status": "completed",
            "response": {"_raw": raw, "summary": "the staged event was empty"},
        },
    )
    cid, error = await launch_rehearsal(
        workflow_id="wf-1",
        scenario_key="generic:automation-telegram",
        user_id="user-1",
    )
    assert error is None
    await spawned[0]

    assert len(finished) == 1
    _, reply, err = finished[0]
    assert err is None
    assert reply == raw
    RehearsalProgressEvent(conversation_id=cid, kind="done", reply=reply)


def test_reply_text_serializes_rawless_structured_output():
    """A structured response without `_raw` still becomes text, never a dict."""
    import json

    from nodes.agent.rehearsal_launch import _reply_text

    reply = _reply_text({"response": {"summary": "done", "count": 2}})
    assert isinstance(reply, str)
    assert json.loads(reply) == {"summary": "done", "count": 2}
    assert _reply_text({"output": "plain text"}) == "plain text"
    assert _reply_text("bare string") == "bare string"
    assert _reply_text(None) is None
