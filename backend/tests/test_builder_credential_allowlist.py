"""The builder brain's credential predicate must be allowlist-aware for
tool-provider nodes (2026-07-29 exa incident: the brain asked the user for an
Exa API key on a provider whose entire allowlist was credential-optional).

Provider-wired nodes skip node drafter, so `operation` is None or a stale
pre-wiring value — a non-empty `agent_tool_operations` allowlist must decide
via the same `allowlist_requires_credentials` predicate that gates runtime
tool exposure, pre-empting the single-op waiver in BOTH directions.
"""
from __future__ import annotations

from coder.workflow.graph_state import GraphState, NodeState
from coder.workflow.agentic.commands import nodes_missing_credentials
from coder.workflow.operation_catalog import node_requires_credentials


ALL_OPTIONAL = {"agent_tool_operations": ["search", "get_contents", "answer"]}
MIXED = {"agent_tool_operations": ["search", "create_monitor"]}


# ── node_requires_credentials (the shared predicate) ─────────────────────────


def test_all_optional_allowlist_waives_credentials():
    # The incident shape: provider-wired exa, no operation (node drafter skipped).
    assert node_requires_credentials("automation-exa", None, ALL_OPTIONAL) is False


def test_scoped_allowlist_entries_are_normalized():
    config = {"agent_tool_operations": [{"operation": "search"}, "answer"]}
    assert node_requires_credentials("automation-exa", None, config) is False


def test_mixed_allowlist_requires_even_with_stale_optional_operation():
    # A lingering pre-wiring operation ('search' is optional) must not wave
    # a credential-requiring allowlist through — the FE bug's backend twin.
    assert node_requires_credentials("automation-exa", "search", MIXED) is True


def test_empty_allowlist_stays_conservative():
    assert node_requires_credentials("automation-exa", None, {"agent_tool_operations": []}) is True


def test_single_op_behavior_unchanged_without_allowlist():
    assert node_requires_credentials("automation-exa", "search", {}) is False
    assert node_requires_credentials("automation-exa", "create_webset", {}) is True
    # No operation selected yet, no allowlist → conservative.
    assert node_requires_credentials("automation-exa", None, {}) is True


# ── nodes_missing_credentials (feeds search_credentials + [credentials needed]) ──


def _graph_with_exa(config: dict) -> GraphState:
    gs = GraphState()
    gs.nodes["web-search"] = NodeState(
        id="web-search",
        type="automation-exa",
        label="Web Search",
        goal="Search the web",
        config=config,
    )
    return gs


def test_all_optional_provider_not_reported_missing():
    assert nodes_missing_credentials(_graph_with_exa(ALL_OPTIONAL)) == []


def test_mixed_provider_reported_missing():
    missing = nodes_missing_credentials(_graph_with_exa(MIXED))
    assert [n.id for n in missing] == ["web-search"]
