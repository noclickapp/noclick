"""The builder's deterministic done-gate: before finalizing <done/>, every
executing node's config is validated against the runtime view and failures
hold the turn open with a corrective system message — the brain fixes what
would die at run time before the user ever sees "done" (Gmail validation
cc="" incident: prompt-checklist-only completion shipped a config the run
engine rejected). Also pins the ConfigValidationError telemetry type."""
from __future__ import annotations

import pytest

from coder.workflow.agentic.builder import EXEC_RESULT_MARKER, AgenticBuilder
from coder.workflow.graph_state import GraphState, NodeState
from nodes.core.base import ConfigValidationError
from nodes.gmail_node import GmailNode
from wss.handlers.workflow_execution_handler import tag_config_validation_failure

_MARKER = AgenticBuilder._CONFIG_NUDGE_MARKER
_WORKED = [{"role": "user", "content": f"{EXEC_RESULT_MARKER}\nadded nodes"}]


def _builder(nodes: dict[str, NodeState], messages: list | None = None) -> AgenticBuilder:
    b = object.__new__(AgenticBuilder)
    b.messages = list(_WORKED if messages is None else messages)
    b.graph_state = GraphState()
    b.graph_state.nodes.update(nodes)
    return b


def _node(node_id: str, node_type: str, operation: str | None, config: dict) -> NodeState:
    return NodeState(id=node_id, type=node_type, label=node_id, goal="", operation=operation, config=config)


_INVALID = _node("web", "automation-exa", "search", {"operation": "search"})  # missing required query
_VALID = _node("web", "automation-exa", "search", {"operation": "search", "query": "ai"})


def test_invalid_config_gates_done():
    b = _builder({"web": _INVALID})
    nudge = b._config_done_nudge()
    assert nudge and _MARKER in nudge and "web (automation-exa:search)" in nudge


def test_valid_config_passes():
    assert _builder({"web": _VALID})._config_done_nudge() is None


def test_no_nudge_without_executed_ops():
    b = _builder({"web": _INVALID}, messages=[{"role": "user", "content": "hi"}])
    assert b._config_done_nudge() is None


def test_nudge_bounded_per_conversation():
    prior = _WORKED + [{"role": "user", "content": f"{_MARKER}\nfix it"}] * 2
    b = _builder({"web": _INVALID}, messages=prior)
    assert b._config_done_nudge() is None


def test_skips_disabled_provider_and_operationless_nodes():
    nodes = {
        "off": _node("off", "automation-exa", "search", {"operation": "search", "disabled": True}),
        "provider": _node(
            "provider", "automation-exa", None,
            {"agent_tool_operations": ["search", "create_monitor"]},
        ),
        "unpicked": _node("unpicked", "automation-exa", None, {}),
    }
    assert _builder(nodes)._config_done_nudge() is None


def test_gate_appends_message_and_continues():
    b = _builder({"web": _INVALID})
    assert b._gate_on_invalid_configs("Done") is True
    assert _MARKER in b.messages[-1]["content"]
    assert b._last_turn_result.next_action == "continue"
    # The appended marker counts toward the bound on the next attempt.
    assert b._gate_on_invalid_configs("Done") is True
    assert b._gate_on_invalid_configs("Done") is False


# ── ConfigValidationError telemetry type ─────────────────────────────────────


def test_parse_config_raises_typed_error():
    with pytest.raises(ConfigValidationError):
        GmailNode.parse_config({"config": {"operation": "send_email_message", "cc": {"bad": "shape"}}})


def test_tagger_matches_only_config_validation_errors():
    assert tag_config_validation_failure(ConfigValidationError("boom"), "n1", "automation-gmail") is True
    assert tag_config_validation_failure(ValueError("boom"), "n1", "automation-gmail") is False
    assert tag_config_validation_failure(RuntimeError("boom"), "n1", None) is False
