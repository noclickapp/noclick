"""
Tests for tool-provider edge awareness in the shared XML DSL and builder
graph layer: the resolver/validators in coder/workflow/workflow_ops.py,
GraphState target_handle plumbing, and the agentic command handlers
(<add_edge type="tools"> + agent_tool_operations field ops).
"""

import pytest

from coder.workflow.agentic.commands import execute_field_ops, execute_graph_mutations
from coder.workflow.graph_state import GraphState
from coder.workflow.workflow_ops import (
    PROVIDER_SOURCE_HANDLE,
    PROVIDER_TARGET_HANDLE,
    provider_dataflow_conflict,
    resolve_tools_edge,
    trigger_provider_conflict,
    validate_agent_tool_operations,
)
from coder.workflow.workflow_xml import XmlOp
from nodes.agent.node_op_tools import list_node_operations


# ============================================================================
# resolve_tools_edge
# ============================================================================


def test_explicit_tools_edge_resolves_handles():
    handles, err = resolve_tools_edge("automation-linear", "agent", edge_type="tools")
    assert err is None
    assert handles == (PROVIDER_SOURCE_HANDLE, PROVIDER_TARGET_HANDLE)


def test_handle_top_is_accepted_as_tools_request():
    handles, err = resolve_tools_edge("automation-linear", "agent", source_handle="top")
    assert err is None
    assert handles == (PROVIDER_SOURCE_HANDLE, PROVIDER_TARGET_HANDLE)


def test_tools_edge_to_non_agent_rejected():
    handles, err = resolve_tools_edge("automation-linear", "automation-slack", edge_type="tools")
    assert handles is None
    assert err and "agent" in err


def test_tools_edge_from_non_provider_rejected():
    handles, err = resolve_tools_edge("interface-form", "agent", edge_type="tools")
    assert handles is None
    assert err and "cannot provide agent tools" in err


def test_structural_tool_types_auto_normalize():
    for node_type in ("tool", "mcp-server", "alarm", "filesystem"):
        handles, err = resolve_tools_edge(node_type, "agent")
        assert err is None, node_type
        assert handles == (PROVIDER_SOURCE_HANDLE, PROVIDER_TARGET_HANDLE), node_type


def test_plain_dataflow_passes_through():
    for source, target in (
        ("automation-linear", "agent"),  # integration → agent dataflow is legal
        ("automation-linear", "automation-slack"),
        ("agent", "automation-slack"),
    ):
        handles, err = resolve_tools_edge(source, target)
        assert handles is None and err is None, (source, target)


# ============================================================================
# provider_dataflow_conflict
# ============================================================================


def test_tools_edge_blocked_when_source_feeds_dataflow():
    edges = [{"source": "linear_1", "target": "slack_1", "targetHandle": None}]
    err = provider_dataflow_conflict("linear_1", edges, new_edge_is_tools=True)
    assert err and "dataflow" in err


def test_dataflow_edge_blocked_when_source_is_provider():
    edges = [{"source": "linear_1", "target": "agent_1", "targetHandle": PROVIDER_TARGET_HANDLE}]
    err = provider_dataflow_conflict("linear_1", edges, new_edge_is_tools=False)
    assert err and "tool provider" in err


def test_no_conflict_on_clean_source():
    edges = [{"source": "other", "target": "agent_1", "targetHandle": PROVIDER_TARGET_HANDLE}]
    assert provider_dataflow_conflict("linear_1", edges, new_edge_is_tools=True) is None
    assert provider_dataflow_conflict("linear_1", edges, new_edge_is_tools=False) is None


# ============================================================================
# validate_agent_tool_operations
# ============================================================================


def test_valid_allowlist_passes():
    real_op = list_node_operations("automation-linear")[0]["operation"]
    allowed, err = validate_agent_tool_operations("automation-linear", [real_op])
    assert err is None
    assert allowed == [real_op]


def test_json_string_allowlist_is_parsed():
    real_op = list_node_operations("automation-linear")[0]["operation"]
    allowed, err = validate_agent_tool_operations("automation-linear", f'["{real_op}"]')
    assert err is None
    assert allowed == [real_op]


def test_unknown_operation_rejected_with_available_list():
    real_op = list_node_operations("automation-linear")[0]["operation"]
    allowed, err = validate_agent_tool_operations(
        "automation-linear", ["definitely_not_an_operation"]
    )
    assert allowed is None
    assert err and "definitely_not_an_operation" in err and real_op in err


def test_non_list_value_rejected():
    allowed, err = validate_agent_tool_operations("automation-linear", "create_issue")
    assert allowed is None
    assert err and "JSON array" in err


def test_non_provider_type_rejected():
    allowed, err = validate_agent_tool_operations("agent", ["anything"])
    assert allowed is None
    assert err and "cannot provide agent tools" in err


# ============================================================================
# GraphState plumbing
# ============================================================================


def _graph_with_provider_pair() -> GraphState:
    gs = GraphState()
    gs.add_node(name="linear_1", node_type="automation-linear", label="Linear")
    gs.add_node(name="agent_1", node_type="agent", label="Agent")
    return gs


def test_edge_state_roundtrips_target_handle():
    gs = _graph_with_provider_pair()
    edge = gs.add_edge("linear_1", "agent_1", source_handle="top", target_handle="bottom")
    assert edge is not None
    d = edge.to_dict()
    assert d["sourceHandle"] == "top"
    assert d["targetHandle"] == "bottom"


def test_is_tool_provider_requires_bottom_handle_into_agent():
    gs = _graph_with_provider_pair()
    gs.add_node(name="slack_1", node_type="automation-slack", label="Slack")
    gs.add_edge("linear_1", "agent_1", source_handle="top", target_handle="bottom")
    gs.add_edge("slack_1", "agent_1")  # plain dataflow into the agent
    assert gs.is_tool_provider("linear_1") is True
    assert gs.is_tool_provider("slack_1") is False
    assert gs.is_tool_provider("agent_1") is False


def test_to_xml_renders_tools_edge_and_allowlist():
    gs = _graph_with_provider_pair()
    gs.add_edge("linear_1", "agent_1", source_handle="top", target_handle="bottom")
    gs.nodes["linear_1"].config["agent_tool_operations"] = ["create_issue"]
    xml = gs.to_xml()
    assert '<edge from="linear_1" to="agent_1" type="tools"/>' in xml
    # The allowlist is canvas-level (not in the operation schema) but must
    # stay visible to the brain for later edits.
    assert "agent_tool_operations" in xml




def test_from_dict_hydrates_target_handle():
    gs = _graph_with_provider_pair()
    gs.add_edge("linear_1", "agent_1", source_handle="top", target_handle="bottom")
    data = {
        "nodes": [n.to_dict() for n in gs.nodes.values()],
        "edges": [e.to_dict() for e in gs.edges.values()],
    }
    restored = GraphState.from_dict(data)
    assert restored.is_tool_provider("linear_1") is True


# ============================================================================
# Agentic command handlers
# ============================================================================


def test_add_edge_type_tools_creates_provider_edge():
    gs = _graph_with_provider_pair()
    ops = [XmlOp(tag="add_edge", attrs={"from": "linear_1", "to": "agent_1", "type": "tools"})]
    results, _ = execute_graph_mutations(ops, gs)
    assert any("tools edge" in r for r in results), results
    assert any("agent_tool_operations" in r for r in results), results
    assert gs.is_tool_provider("linear_1") is True


def test_add_edge_type_tools_to_non_agent_errors():
    gs = GraphState()
    gs.add_node(name="linear_1", node_type="automation-linear", label="Linear")
    gs.add_node(name="slack_1", node_type="automation-slack", label="Slack")
    ops = [XmlOp(tag="add_edge", attrs={"from": "linear_1", "to": "slack_1", "type": "tools"})]
    results, _ = execute_graph_mutations(ops, gs)
    assert any(r.startswith("ERROR") and "agent" in r for r in results), results
    assert not gs.edge_set


def test_add_edge_dataflow_from_provider_conflicts():
    gs = _graph_with_provider_pair()
    gs.add_node(name="slack_1", node_type="automation-slack", label="Slack")
    execute_graph_mutations(
        [XmlOp(tag="add_edge", attrs={"from": "linear_1", "to": "agent_1", "type": "tools"})], gs
    )
    results, _ = execute_graph_mutations(
        [XmlOp(tag="add_edge", attrs={"from": "linear_1", "to": "slack_1"})], gs
    )
    assert any(r.startswith("ERROR") and "tool provider" in r for r in results), results
    assert ("linear_1", "slack_1") not in gs.edge_set


def test_legacy_tool_to_agent_edge_gets_handles():
    gs = GraphState()
    gs.add_node(name="tool_1", node_type="tool", label="Tool")
    gs.add_node(name="agent_1", node_type="agent", label="Agent")
    results, _ = execute_graph_mutations(
        [XmlOp(tag="add_edge", attrs={"from": "tool_1", "to": "agent_1"})], gs
    )
    edge = next(iter(gs.edges.values()))
    assert edge.source_handle == PROVIDER_SOURCE_HANDLE
    assert edge.target_handle == PROVIDER_TARGET_HANDLE
    # Structural tool nodes get no allowlist reminder (they have no operations).
    assert not any("agent_tool_operations" in r for r in results), results


def test_field_op_sets_validated_allowlist():
    gs = _graph_with_provider_pair()
    execute_graph_mutations(
        [XmlOp(tag="add_edge", attrs={"from": "linear_1", "to": "agent_1", "type": "tools"})], gs
    )
    real_op = list_node_operations("automation-linear")[0]["operation"]
    results = execute_field_ops(
        [XmlOp(tag="field", attrs={"node": "linear_1", "name": "agent_tool_operations",
                                   "value": f'["{real_op}"]'})],
        gs,
    )
    assert gs.nodes["linear_1"].config["agent_tool_operations"] == [real_op]
    # Provider nodes skip full-config Pydantic validation — no VALIDATION ERROR
    # for the (intentionally) unfilled operation fields.
    assert not any("VALIDATION ERROR" in r for r in results), results


def test_field_op_rejects_unknown_operation():
    gs = _graph_with_provider_pair()
    results = execute_field_ops(
        [XmlOp(tag="field", attrs={"node": "linear_1", "name": "agent_tool_operations",
                                   "value": '["not_a_real_op"]'})],
        gs,
    )
    assert any("not_a_real_op" in r and "Field error" in r for r in results), results
    assert "agent_tool_operations" not in gs.nodes["linear_1"].config


# ============================================================================
# Trigger/provider either-or (a node can't be both)
# ============================================================================


def test_is_trigger_operation_predicate():
    from nodes.agent.node_op_tools import is_trigger_operation

    assert is_trigger_operation("automation-google-sheets", "on_new_row") is True
    assert is_trigger_operation("automation-github-rest", "create_pull_request") is False
    assert is_trigger_operation("automation-nonexistent", "on_new_row") is False
    assert is_trigger_operation("automation-google-sheets", None) is False


def test_trigger_provider_conflict_helper():
    assert trigger_provider_conflict("automation-google-sheets", "on_new_row") is not None
    assert "trigger operation" in trigger_provider_conflict("automation-google-sheets", "on_new_row")
    assert trigger_provider_conflict("automation-google-sheets", "append_row") is None
    assert trigger_provider_conflict("automation-google-sheets", None) is None


def test_add_edge_tools_from_trigger_op_node_errors():
    """Agentic DSL: wiring a node with a trigger operation as a provider fails."""
    gs = GraphState()
    gs.add_node(name="sheets_1", node_type="automation-google-sheets", label="Sheets")
    gs.add_node(name="agent_1", node_type="agent", label="Agent")
    gs.nodes["sheets_1"].operation = "on_new_row"
    results, _ = execute_graph_mutations(
        [XmlOp(tag="add_edge", attrs={"from": "sheets_1", "to": "agent_1", "type": "tools"})], gs
    )
    assert any(r.startswith("ERROR") and "trigger operation" in r for r in results), results
    assert not gs.edge_set


def test_add_edge_tools_reads_operation_from_config():
    """The conflict also fires when operation lives in NodeState.config."""
    gs = GraphState()
    gs.add_node(name="sheets_1", node_type="automation-google-sheets", label="Sheets")
    gs.add_node(name="agent_1", node_type="agent", label="Agent")
    gs.nodes["sheets_1"].config["operation"] = "on_new_row"
    results, _ = execute_graph_mutations(
        [XmlOp(tag="add_edge", attrs={"from": "sheets_1", "to": "agent_1", "type": "tools"})], gs
    )
    assert any(r.startswith("ERROR") and "trigger operation" in r for r in results), results
    assert not gs.edge_set


def test_add_edge_tools_from_non_trigger_op_node_succeeds():
    """A non-trigger operation on the source doesn't trip the either-or rule."""
    gs = GraphState()
    gs.add_node(name="sheets_1", node_type="automation-google-sheets", label="Sheets")
    gs.add_node(name="agent_1", node_type="agent", label="Agent")
    gs.nodes["sheets_1"].operation = "append_row"
    results, _ = execute_graph_mutations(
        [XmlOp(tag="add_edge", attrs={"from": "sheets_1", "to": "agent_1", "type": "tools"})], gs
    )
    assert any("tools edge" in r for r in results), results
    assert gs.is_tool_provider("sheets_1") is True
