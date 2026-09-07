"""A tool provider cut out of its graph is still a tool provider.

A single-node "Run" from the canvas sends only the node and its inputs
(prepareNodeExecution) — the bottom-handle edge into the agent / hosting-mode
MCP node is not in the slice. Judged on the slice alone, the provider looked
like a plain node and parse_config failed with "'operation' field is required"
(12 users, 2026-08-24 → 09-07); with a leftover operation it would have acted
on a real account. The runner now judges provider wiring on the full workflow
graph the slice was cut from (``workflow_graph``).
"""

from unittest.mock import AsyncMock

import pytest

from nodes.agent.node_op_tools import is_node_op_provider, with_provider_wiring
from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler

PROVIDER = {
    "id": "slack-1",
    "type": "automation-slack",
    "config": {"label": "Slack", "agent_tool_operations": ["send_message"]},
}
AGENT = {"id": "agent-1", "type": "agent", "config": {"model": "openai/gpt-4o", "message": "hi"}}
MCP = {"id": "mcp-1", "type": "mcp-server", "config": {}}
FEED = {"id": "rss-1", "type": "automation-rss", "config": {}}


def _bottom(src: str, dst: str):
    return {"id": f"{src}-{dst}", "source": src, "target": dst,
            "sourceHandle": "top", "targetHandle": "bottom"}


def test_slice_alone_cannot_see_the_wiring():
    """The mechanism: the slice a single-node run sends carries no consumer."""
    assert is_node_op_provider("slack-1", "automation-slack", [PROVIDER], []) is False


def test_with_provider_wiring_adds_only_the_consumers_of_slice_nodes():
    graph_nodes = [PROVIDER, AGENT, MCP, FEED]
    graph_edges = [
        _bottom("slack-1", "agent-1"),
        {"source": "rss-1", "target": "agent-1"},          # dataflow, not wiring
        _bottom("rss-1", "mcp-1"),                          # wiring of a node outside the slice
    ]
    nodes, edges = with_provider_wiring([PROVIDER], [], graph_nodes, graph_edges)
    assert [n["id"] for n in nodes] == ["slack-1", "agent-1"]
    assert edges == [_bottom("slack-1", "agent-1")]
    assert is_node_op_provider("slack-1", "automation-slack", nodes, edges) is True


def test_with_provider_wiring_is_idempotent_on_a_full_graph():
    nodes = [PROVIDER, MCP]
    edges = [_bottom("slack-1", "mcp-1")]
    out_nodes, out_edges = with_provider_wiring(nodes, edges, nodes, edges)
    assert out_nodes == nodes and out_edges == edges


def test_with_provider_wiring_without_a_graph_returns_the_slice():
    assert with_provider_wiring([PROVIDER], [], None, None) == ([PROVIDER], [])


@pytest.mark.asyncio
@pytest.mark.parametrize("consumer", [AGENT, MCP], ids=["agent", "mcp-hosting"])
async def test_single_node_run_of_a_provider_publishes_tools(consumer):
    """A real run (2026-09-07): Facebook wired into a hosting-mode MCP node,
    'Run' on the Facebook node → slice = [facebook], edges = []. Must produce
    the provider bundle, never parse an operation-less config."""
    handler = WorkflowExecutionHandler(sio=AsyncMock())
    executed, error, outputs = await handler._execute_nodes_concurrent(
        [PROVIDER], [], "sid", "user", "wf",
        workflow_graph=([PROVIDER, consumer], [_bottom("slack-1", consumer["id"])]),
    )
    assert error is None, error
    assert executed == 1
    assert outputs["slack-1"]["type"] == "node_op_tool_provider"
    assert outputs["slack-1"]["allowed_operations"] == ["send_message"]
