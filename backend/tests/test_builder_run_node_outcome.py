"""The builder's <run_node> answers from the run it started, never from the store.

A run's outputs are stored after it returns, so the builder read the store
too early: one build asked to "run it once now" ran its manual trigger, whose
run went through and emailed the owner, was told the trigger "produced no
output", and ran the agent again, which emailed them a second time
(2026-10-24). Running from a node runs the steps after it too, so the answer
also names the other steps that ran.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from wss.handlers.workflow_builder_handler import WorkflowBuilderHandler, builder_run_outcome
from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler, WorkflowExecutionResult

WORKFLOW_ID = "8648544f-36f0-4007-ac95-94bb5ef8a7a8"
USER_ID = "c0ffee00-0000-4000-8000-000000000001"

# The incident's workflow: a schedule and a manual trigger into an agent with a search tool and an email tool.
NODES = [
    {"id": "monday", "type": "trigger-cron", "config": {}},
    {"id": "run_now", "type": "trigger-run", "config": {}},
    {"id": "researcher", "type": "agent", "config": {}},
    {"id": "web_research", "type": "automation-exa", "config": {"agent_tool_operations": ["search"]}},
    {"id": "owner_email", "type": "automation-send-email", "config": {"agent_tool_operations": ["send"]}},
]
EDGES = [
    {"id": "e1", "source": "monday", "target": "researcher"},
    {"id": "e2", "source": "run_now", "target": "researcher"},
    {"id": "e3", "source": "web_research", "target": "researcher", "sourceHandle": "top", "targetHandle": "bottom"},
    {"id": "e4", "source": "owner_email", "target": "researcher", "sourceHandle": "top", "targetHandle": "bottom"},
]
TRIGGERED = {"type": "run-trigger", "status": "triggered", "timestamp": 1792863845.0}
REPLY = {"type": "agent", "status": "completed", "response": "I emailed the comparison to the workflow owner."}


def _result(statuses, outputs, error=None):
    return WorkflowExecutionResult(
        execution_id="exec-1", workflow_id=WORKFLOW_ID, success=error is None, nodes_executed=len(statuses),
        duration=1.0, error=error, node_outputs=outputs,
        node_statuses={nid: {"status": status, "error": err} for nid, (status, err) in statuses.items()},
    )


def _incident_run():
    provided = {"type": "node_op_tool_provider"}
    return _result(
        {"run_now": ("completed", None), "researcher": ("completed", None),
         "web_research": ("completed", None), "owner_email": ("completed", None)},
        {"run_now": TRIGGERED, "researcher": REPLY, "web_research": provided, "owner_email": provided},
    )


@pytest.mark.asyncio
async def test_a_run_the_store_has_not_caught_up_with_is_reported_as_it_ran(monkeypatch):
    handler = WorkflowBuilderHandler(MagicMock())
    conn = MagicMock()
    handler.get_pool = AsyncMock(return_value=MagicMock(acquire=MagicMock(return_value=MagicMock(
        __aenter__=AsyncMock(return_value=conn), __aexit__=AsyncMock(return_value=False)))))
    stored = {"workflow": {"nodes": [dict(n) for n in NODES], "edges": [dict(e) for e in EDGES]}}
    monkeypatch.setattr("wss.handlers.workflow_builder_handler.WorkflowRepo", lambda _pool: SimpleNamespace(
        get_workflow_for_builder_run_node=AsyncMock(return_value=stored)))
    # The run's outputs haven't reached the store yet: only the run itself knows what happened.
    monkeypatch.setattr("utils.cas.store.read_latest_node_outputs", AsyncMock(return_value={}))
    started = []

    async def run(self, sid, request, execution_id=None, caller_user_id=None):
        started.append((request.start_node_id, request.forward_only, caller_user_id))
        return _incident_run()

    monkeypatch.setattr(WorkflowExecutionHandler, "handle_execute", run)
    ops = handler._create_platform_ops(USER_ID, "sid-1", WORKFLOW_ID)

    assert await ops.run_node("run_now", include_downstream=True) == {
        "success": True, "ran": {"researcher": "completed"}}
    assert started == [("run_now", True, USER_ID)]
    assert await ops.run_node("run_now") == {"success": True, "output": TRIGGERED, "ran": {"researcher": "completed"}}


def test_the_target_failing_is_its_own_error_with_what_else_ran():
    run = _result({"run_now": ("completed", None), "researcher": ("error", "Exa refused the search: 429")},
                  {"run_now": TRIGGERED})
    assert builder_run_outcome(run, "researcher", EDGES, include_downstream=False) == {
        "error": "Exa refused the search: 429", "failed_node": "researcher", "ran": {"run_now": "completed"}}
    failed_output = _result({"researcher": ("completed", None)}, {"researcher": {"error": "no model key"}})
    assert builder_run_outcome(failed_output, "researcher", EDGES, include_downstream=False)["error"] == "no model key"


def test_a_target_that_never_ran_says_whether_anything_did():
    other = _result({"monday": ("error", "boom")}, {}, error="Node monday failed: boom")
    assert builder_run_outcome(other, "researcher", EDGES, include_downstream=False) == {
        "error": "Node monday failed: boom", "failed_node": "other", "target_node": "researcher",
        "ran": {"monday": "error"}}
    refused = _result({}, {}, error="Insufficient credits: 0.00 < 0.20 required")
    assert builder_run_outcome(refused, "researcher", EDGES, include_downstream=False) == {
        "error": "Insufficient credits: 0.00 < 0.20 required"}


def test_a_skipped_target_is_not_a_success():
    run = _result({"run_now": ("completed", None), "researcher": ("skipped", None)}, {"run_now": TRIGGERED})
    outcome = builder_run_outcome(run, "researcher", EDGES, include_downstream=False)
    assert "skipped" in outcome["error"] and outcome["ran"] == {"run_now": "completed"}
