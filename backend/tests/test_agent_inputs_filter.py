"""Tests for _filter_input_nodes — the run-results inputs rail's node filter.

Pins two guards: the IDOR workflow-scope gate (a node absent from the
workflow-scoped `statuses` set is never surfaced, so a foreign execution id leaks
nothing) and the delivery-plumbing filter (agent awaiting-marker + tool-provider
metadata are dropped)."""
from wss.handlers.workflow_handler import _filter_input_nodes


def test_keeps_only_real_inputs_in_the_workflow_scoped_status_set():
    outputs = {
        "webhook_1": {"_webhook": {"body": {}}, "headers": {}},          # real trigger input → keep
        "agent_1": {"type": "agent", "status": "agent_turn_pending"},    # delivery marker → drop
        "gdocs_1": {"type": "node_op_tool_provider", "operations": []},   # tool provider → drop
        "foreign_1": {"data": "another workflow's node"},                 # NOT in statuses → gated out
    }
    statuses = {"webhook_1": "completed", "agent_1": "completed", "gdocs_1": "completed"}

    nodes = _filter_input_nodes(outputs, statuses)

    assert {n["node_id"] for n in nodes} == {"webhook_1"}
    assert nodes[0]["status"] == "completed"


def test_foreign_execution_yields_nothing():
    # A cross-workflow execution id → the workflow-scoped status query returns no rows,
    # so every output is gated out even though read_execution_outputs returned them.
    outputs = {"b_node_1": {"secret": 1}, "b_node_2": {"secret": 2}}
    assert _filter_input_nodes(outputs, statuses={}) == []


def test_drops_the_bundle_variant_too():
    outputs = {"mcp_1": {"type": "node_op_tool_provider_bundle"}, "data_1": {"rows": [1]}}
    statuses = {"mcp_1": "completed", "data_1": "completed"}
    assert {n["node_id"] for n in _filter_input_nodes(outputs, statuses)} == {"data_1"}
