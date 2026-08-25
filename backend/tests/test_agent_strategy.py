"""Unit tests for the synchronous AgentExecutionStrategy."""
import asyncio

import pytest

from nodes.agent.agent_strategy import AgentExecutionStrategy

pytestmark = pytest.mark.asyncio


class _FakeCtx:
    def __init__(self, node, output, successors):
        self.node_id = node["id"]
        self.node = node
        self.successors = successors
        self.node_by_id = {nid: {"id": nid, "type": "automation-slack"} for s in successors.values() for nid in s}
        self.node_outputs = {}
        self.execution_id = None  # skip the DB status write
        self.semaphore = asyncio.Semaphore(1)
        self._output = output
        self.skipped = []
        self.completed = []
        self.done = []

    async def emit_state(self, *a):
        pass

    async def emit_output(self, *a):
        pass

    async def execute_node(self, node, outputs):
        return self._output

    async def mark_completed(self, nid, out):
        self.completed.append(nid)
        self.node_outputs[nid] = out

    async def mark_failed(self, nid, err):
        pass

    async def mark_skipped(self, nid):
        self.skipped.append(nid)

    def signal_done(self, nid):
        self.done.append(nid)


async def test_normal_output_flows_downstream():
    assert AgentExecutionStrategy().handles("agent") is True
    assert AgentExecutionStrategy().handles("automation-slack") is False
    node = {"id": "agent-1", "type": "agent", "config": {}}
    ctx = _FakeCtx(node, {"type": "agent", "status": "completed", "response": "hi"}, {"agent-1": {"slack-1"}})
    result = await AgentExecutionStrategy().execute(ctx)
    assert result.success
    assert result.body_nodes_handled == set()  # nothing claimed → engine runs downstream
    assert ctx.skipped == []                    # nothing skipped
    assert ctx.completed == ["agent-1"]


async def test_failed_output_halts_downstream():
    # Failures reported IN the output (credit gate, provider errors) must halt
    # exactly like a raised exception; otherwise error strings flow downstream
    # as ordinary data and mask the root cause.
    node = {"id": "agent-1", "type": "agent", "config": {}}
    ctx = _FakeCtx(
        node,
        {"type": "agent", "status": "failed", "response": "Insufficient balance."},
        {"agent-1": {"slack-1"}},
    )
    ctx.failed = []
    original = ctx.mark_failed

    async def mark_failed(nid, err):
        ctx.failed.append((nid, err))

    ctx.mark_failed = mark_failed
    result = await AgentExecutionStrategy().execute(ctx)
    assert result.success is False
    assert "Insufficient balance." in (result.error or "")
    assert ctx.completed == []                       # never marked completed
    assert ctx.failed and ctx.failed[0][0] == "agent-1"
    assert result.body_nodes_handled == set()        # successors cascade-skip normally
    assert ctx.done == ["agent-1"]                   # finally still signals


async def test_mocked_failed_output_is_exempt_from_the_check():
    # mockedOutput is user-authored test data — a mocked {status:'failed'}
    # payload flows as data, not as a live failure.
    node = {"id": "agent-1", "type": "agent",
            "config": {"mockedOutput": {"type": "agent", "status": "failed", "response": "x"}}}
    ctx = _FakeCtx(node, {"unused": True}, {"agent-1": {"slack-1"}})
    result = await AgentExecutionStrategy().execute(ctx)
    assert result.success is True
    assert ctx.completed == ["agent-1"]
