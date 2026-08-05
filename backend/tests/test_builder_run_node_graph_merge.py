"""The builder's run_node graph merge: targetHandle must survive every edge
serialization hop (CLAUDE.md invariant), and this hop dropped it twice —
both for edges loaded from the DB and for edges the brain added in-memory
this turn.

A reproduced workflow: the builder wired `cleanup_agent` with a
Linear tool provider (`<add_edge from="linear_tools" to="cleanup_agent"
type="tools" />`, allowlist + credential set) and ran it via <run_node> in
the SAME turn. The merge stripped targetHandle='bottom', so the executor's
provider backfill and AgentNode._is_wired_tool_provider both went blind:
the agent ran with zero linear__* tools, reported the bug itself via
submit_feedback ("The workflow description shows those nodes/providers and
credentials, but no callable Linear tool namespace/functions are exposed" —
describe_workflow reads the STORED graph, where the handle survives), and
the builder abandoned the agent design for a manual fallback.
"""
from __future__ import annotations

from coder.workflow.graph_state import GraphState
from nodes.agent_node import AgentNode
from wss.handlers.workflow_builder_handler import merge_builder_run_graph


def _incident_graph_state() -> GraphState:
    """The brain's in-memory state from the incident turn: agent + provider
    added this turn, wired with the tools edge, before any auto-save."""
    gs = GraphState()
    gs.add_node("cleanup_agent", "agent", "Delete All Linear Webhooks")
    gs.add_node("linear_tools", "automation-linear", "Linear Webhook Tools")
    gs.nodes["linear_tools"].config = {
        "agent_tool_operations": ["list_webhooks", "delete_webhook"],
        "credentialIds": {"linear_oauth": "linear-credential"},
    }
    edge = gs.add_edge("linear_tools", "cleanup_agent", target_handle="bottom")
    assert edge is not None and edge.target_handle == "bottom"
    return gs


def _agent_sees_provider(edges: list[dict], agent_id: str, provider_id: str) -> bool:
    """The real consumer: AgentNode's edge-scoping predicate over the merged
    edges, exactly as set_workflow_context hands them over."""
    agent = object.__new__(AgentNode)
    agent.node_id = agent_id
    agent._workflow_edges = edges
    return agent._is_wired_tool_provider(provider_id)


class TestTargetHandleSurvives:
    def test_the_incident_edge_added_this_turn(self):
        """Provider wired and run in the same turn — nothing in the DB yet."""
        nodes, edges = merge_builder_run_graph([], [], _incident_graph_state())
        assert {n["id"] for n in nodes} == {"cleanup_agent", "linear_tools"}
        (edge,) = edges
        assert edge["source"] == "linear_tools"
        assert edge["target"] == "cleanup_agent"
        assert edge["targetHandle"] == "bottom"

    def test_the_agent_actually_collects_the_provider(self):
        """Producer→consumer contract: the merged edges must satisfy
        AgentNode._is_wired_tool_provider, not just carry the key."""
        _, edges = merge_builder_run_graph([], [], _incident_graph_state())
        assert _agent_sees_provider(edges, "cleanup_agent", "linear_tools")

    def test_db_loaded_edge(self):
        """The second drop site: normalization of edges already saved."""
        db_edges = [{
            "id": "e_linear_tools_cleanup_agent",
            "source": "linear_tools",
            "target": "cleanup_agent",
            "sourceHandle": "top",
            "targetHandle": "bottom",
        }]
        _, edges = merge_builder_run_graph([], db_edges, None)
        assert edges[0]["targetHandle"] == "bottom"
        assert edges[0]["sourceHandle"] == "top"
        assert _agent_sees_provider(edges, "cleanup_agent", "linear_tools")

    def test_state_handle_survives_too(self):
        """targetHandle 'state' wires state nodes — same normalization path."""
        db_edges = [{"id": "e1", "source": "st", "target": "fn",
                     "targetHandle": "state"}]
        _, edges = merge_builder_run_graph([], db_edges, None)
        assert edges[0]["targetHandle"] == "state"


class TestExistingMergeSemanticsKept:
    def test_graph_state_config_overlays_db_and_credentials_deep_merge(self):
        db_nodes = [{
            "id": "linear_tools", "type": "automation-linear",
            "config": {"operation": "old_op",
                       "credentialIds": {"other_provider": "keep-me"}},
        }]
        gs = _incident_graph_state()
        nodes, _ = merge_builder_run_graph(db_nodes, [], gs)
        merged = next(n for n in nodes if n["id"] == "linear_tools")
        assert merged["config"]["agent_tool_operations"] == [
            "list_webhooks", "delete_webhook"]
        # credentialIds are additive: DB creds for other providers survive
        assert merged["config"]["credentialIds"]["other_provider"] == "keep-me"
        assert merged["config"]["credentialIds"]["linear_oauth"] == "linear-credential"

    def test_graph_state_ids_normalize_to_executor_field_names(self):
        _, edges = merge_builder_run_graph([], [], _incident_graph_state())
        assert "sourceId" not in edges[0] and "targetId" not in edges[0]
        assert "status" not in edges[0]

    def test_edge_already_in_db_is_not_duplicated(self):
        gs = _incident_graph_state()
        db_edges = [{"id": "e_linear_tools_cleanup_agent",
                     "source": "linear_tools", "target": "cleanup_agent",
                     "targetHandle": "bottom"}]
        _, edges = merge_builder_run_graph([], db_edges, gs)
        assert len(edges) == 1

    def test_absent_handles_stay_absent(self):
        db_edges = [{"id": "e1", "source": "a", "target": "b"}]
        _, edges = merge_builder_run_graph([], db_edges, None)
        assert "sourceHandle" not in edges[0]
        assert "targetHandle" not in edges[0]
