"""
MCP node hosting mode: an mcp-server node with tool providers wired into its
bottom handle aggregates their allowlisted operations into one bundle
(node_op_tool_provider_bundle) instead of proxying an external server.
Pins the either-or contract (hosting XOR server_url), the provider
short-circuit extension, the agent-side bundle flattening, and the DSL
wiring rules shared by the MCP server and the agentic builder.
"""

import pytest

from coder.workflow.workflow_ops import (
    mcp_hosting_conflict,
    mcp_server_url_conflict,
    resolve_tools_edge,
)
from nodes.agent.node_op_tools import is_node_op_provider
from nodes.mcp_server_node import MCPServerNode, MCPServerNodeConfig


def _make_mcp_node(config: dict) -> MCPServerNode:
    return MCPServerNode(
        node_id="mcp-1",
        node_type="mcp-server",
        node_data={},
        config=MCPServerNodeConfig.model_validate(config),
        sio=None,
        sid=None,
        workflow_id="test_wf",
    )


_PROVIDER_OUTPUT = {
    "type": "node_op_tool_provider",
    "node_type": "automation-linear",
    "allowed_operations": ["create_issue", "update_issue"],
    "credential_id": "cred-7",
    "label": "Work Linear",
    "sandbox_repos": [],
}


# ============================================================================
# MCPServerNode.execute — mode resolution
# ============================================================================

class TestHostingMode:
    @pytest.mark.asyncio
    async def test_providers_bundle(self):
        """Bottom-wired provider outputs aggregate into one bundle, each
        entry stamped with the provider's node id."""
        node = _make_mcp_node({"config": {}})
        output = await node.execute({"linear-1": _PROVIDER_OUTPUT})

        assert output["type"] == "node_op_tool_provider_bundle"
        assert output["provider_count"] == 1
        assert output["tool_count"] == 2
        entry = output["providers"][0]
        assert entry["node_id"] == "linear-1"
        assert entry["node_type"] == "automation-linear"
        assert entry["allowed_operations"] == ["create_issue", "update_issue"]
        assert entry["credential_id"] == "cred-7"

    @pytest.mark.asyncio
    async def test_non_provider_inputs_ignored(self):
        """Only node_op_tool_provider outputs join the bundle — stray dataflow
        outputs (legacy left-handle edges) don't corrupt it."""
        node = _make_mcp_node({"config": {}})
        output = await node.execute({
            "linear-1": _PROVIDER_OUTPUT,
            "upstream-1": {"type": "something_else", "data": 42},
            "upstream-2": "scalar",
        })
        assert output["provider_count"] == 1

    @pytest.mark.asyncio
    async def test_both_modes_is_error(self):
        """server_url + wired providers → loud either-or error, empty bundle
        (hosting-wins shape so a downstream agent gets no phantom tools)."""
        node = _make_mcp_node({"config": {"server_url": "https://api.example.com/mcp"}})
        output = await node.execute({"linear-1": _PROVIDER_OUTPUT})
        assert output["type"] == "node_op_tool_provider_bundle"
        assert "either-or" in output["error"]
        assert output["providers"] == []

    @pytest.mark.asyncio
    async def test_neither_mode_is_error(self):
        node = _make_mcp_node({"config": {}})
        output = await node.execute({})
        assert output["type"] == "mcp_tool_definitions"
        assert "no server_url" in output["error"]
        assert output["tools"] == []


# ============================================================================
# Provider short-circuit — mcp-server is a valid consumer
# ============================================================================

_NODES = [
    {"id": "agent-1", "type": "agent"},
    {"id": "mcp-1", "type": "mcp-server"},
    {"id": "linear-1", "type": "automation-linear"},
]


def test_provider_short_circuits_when_wired_to_mcp():
    edges = [{"source": "linear-1", "target": "mcp-1", "targetHandle": "bottom", "sourceHandle": "top"}]
    assert is_node_op_provider("linear-1", "automation-linear", _NODES, edges)


# ============================================================================
# Agent-side bundle flattening
# ============================================================================

def test_agent_flattens_bundle_into_node_op_tools():
    """An MCP bundle wired to the agent's bottom handle yields the same
    node_op tools as directly-wired providers — including cross-source
    collision handling when the bundle and a direct provider share a type."""
    from nodes.agent_node import AgentNode

    agent = object.__new__(AgentNode)
    agent.node_id = "agent-1"
    agent._workflow_edges = [
        {"source": "mcp-1", "target": "agent-1", "targetHandle": "bottom"},
        {"source": "linear_direct", "target": "agent-1", "targetHandle": "bottom"},
    ]
    inputs = {
        "mcp-1": {
            "type": "node_op_tool_provider_bundle",
            "provider_count": 1,
            "providers": [{**_PROVIDER_OUTPUT, "node_id": "linear_hosted", "credential_label": "operator@example.com"}],
        },
        "linear_direct": {
            "type": "node_op_tool_provider",
            "node_type": "automation-linear",
            "allowed_operations": ["create_issue"],
            "credential_id": "cred-b",
        },
    }

    tool_params, tool_configs, _ = agent._collect_tool_definitions(inputs)
    names = [p["function"]["name"] for p in tool_params]
    assert len(names) == len(set(names)), f"colliding tool names: {names}"

    # Bundled provider: label-derived slug, its own credential
    assert tool_configs["work_linear__create_issue"]["credential_id"] == "cred-7"
    assert tool_configs["work_linear__create_issue"]["tool_type"] == "node_op"
    # Direct provider coexists under its own slug
    assert tool_configs["linear_direct__create_issue"]["credential_id"] == "cred-b"


def test_agent_ignores_unwired_bundle():
    """Edge scoping: a bundle from an MCP node wired to a DIFFERENT agent
    must not leak its tools here."""
    from nodes.agent_node import AgentNode

    agent = object.__new__(AgentNode)
    agent.node_id = "agent-1"
    agent._workflow_edges = [
        {"source": "mcp-1", "target": "agent-OTHER", "targetHandle": "bottom"},
    ]
    inputs = {
        "mcp-1": {
            "type": "node_op_tool_provider_bundle",
            "providers": [{**_PROVIDER_OUTPUT, "node_id": "linear_hosted"}],
        },
    }
    tool_params, tool_configs, _ = agent._collect_tool_definitions(inputs)
    # Only the ambient upload_file (on every SDK agent) — nothing from the
    # unwired bundle.
    assert [t["function"]["name"] for t in tool_params] == ["upload_file"]
    assert list(tool_configs) == ["upload_file"]


# ============================================================================
# DSL wiring rules (shared by MCP server + agentic builder)
# ============================================================================

def test_resolve_tools_edge_provider_into_mcp_auto_normalizes():
    handles, err = resolve_tools_edge("automation-linear", "mcp-server")
    assert handles == ("top", "bottom")
    assert err is None


def test_resolve_tools_edge_rejects_mcp_nesting():
    handles, err = resolve_tools_edge("mcp-server", "mcp-server")
    assert handles is None
    assert "nest" in err


def test_resolve_tools_edge_rejects_structural_into_mcp():
    for structural in ("tool", "alarm", "filesystem"):
        handles, err = resolve_tools_edge(structural, "mcp-server")
        assert handles is None
        assert err is not None


def test_resolve_tools_edge_mcp_into_agent_unchanged():
    handles, err = resolve_tools_edge("mcp-server", "agent")
    assert handles == ("top", "bottom")
    assert err is None


def test_mcp_hosting_conflict_blocks_external_mode_targets():
    assert mcp_hosting_conflict("mcp-server", {"server_url": "https://x"}) is not None
    assert mcp_hosting_conflict("mcp-server", {"server_url": "  "}) is None
    assert mcp_hosting_conflict("mcp-server", None) is None
    assert mcp_hosting_conflict("agent", {"server_url": "https://x"}) is None


def test_mcp_server_url_conflict_blocks_hosting_nodes():
    hosting_edges = [{"target": "mcp-1", "targetHandle": "bottom", "source": "linear-1"}]
    assert mcp_server_url_conflict("mcp-1", "mcp-server", "https://x", hosting_edges) is not None
    assert mcp_server_url_conflict("mcp-1", "mcp-server", "", hosting_edges) is None
    assert mcp_server_url_conflict("mcp-1", "mcp-server", "https://x", []) is None
    assert mcp_server_url_conflict("mcp-1", "automation-linear", "https://x", hosting_edges) is None


# ============================================================================
# Agentic builder — graph-state predicates + mutation/field paths
# ============================================================================

def _agentic_state():
    from coder.workflow.graph_state import GraphState

    gs = GraphState()
    gs.add_node('mcp1', 'mcp-server', 'Hosted Tools', goal='host tools')
    gs.add_node('agent1', 'agent', 'Agent', goal='do work')
    gs.add_node('linear1', 'automation-linear', 'Linear', goal='linear tools')
    return gs


def test_graph_state_provider_wired_to_mcp_is_tool_provider():
    gs = _agentic_state()
    gs.add_edge('linear1', 'mcp1', source_handle='top', target_handle='bottom')
    assert gs.is_tool_provider('linear1')
    assert gs.has_wired_providers('mcp1')
    assert not gs.has_wired_providers('agent1')


def test_agentic_field_rejects_server_url_on_hosting_mcp():
    from coder.workflow.agentic.commands import execute_field_ops
    from coder.workflow.workflow_xml import XmlOp

    gs = _agentic_state()
    gs.add_edge('linear1', 'mcp1', source_handle='top', target_handle='bottom')
    results = execute_field_ops(
        [XmlOp(tag='field', attrs={'node': 'mcp1', 'name': 'server_url', 'value': 'https://x.example/mcp'})],
        gs,
    )
    assert any('either-or' in r for r in results), results
    assert 'server_url' not in (gs.get_node('mcp1').config or {})


def test_agentic_add_edge_into_mcp_auto_normalizes():
    """The brain wires a provider into an mcp node with a PLAIN add_edge —
    resolve_tools_edge normalizes it to top/bottom and the allowlist hint
    fires, same as provider→agent wiring."""
    from coder.workflow.agentic.commands import execute_graph_mutations
    from coder.workflow.workflow_xml import XmlOp

    gs = _agentic_state()
    results, _ = execute_graph_mutations(
        [XmlOp(tag='add_edge', attrs={'from': 'linear1', 'to': 'mcp1'})],
        gs,
    )
    edge = next(iter(gs.edges.values()))
    assert (edge.source_handle, edge.target_handle) == ('top', 'bottom')
    assert any('agent_tool_operations' in r for r in results), results


def test_allowlist_requires_credentials():
    """Providers whose every allowlisted op is x-credentials-optional need no
    credential (reddit get_subreddit_posts); any op without the flag — or an
    empty allowlist — keeps the requirement."""
    from nodes.agent.node_op_tools import allowlist_requires_credentials

    assert not allowlist_requires_credentials('automation-reddit', ['get_subreddit_posts'])
    assert allowlist_requires_credentials('automation-gmail', ['fetch_emails_from_inbox'])
    assert allowlist_requires_credentials('automation-reddit', [])
    assert allowlist_requires_credentials('automation-reddit', ['get_subreddit_posts', 'nope_op'])
