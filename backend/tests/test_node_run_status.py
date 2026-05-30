# Unit tests for build_node_run_statuses — the pure helper that turns the
# executor's completed/failed/skipped sets + per-node errors into the per-node
# last-run record persisted to workflow_node_outputs (drives the frontend status
# chip; survives headless webhook runs + reload). Pure function, no DB needed.

from wss.handlers.workflow_execution_handler import build_node_run_statuses


def test_completed_failed_skipped_mapping():
    statuses = build_node_run_statuses(
        completed={"a"},
        failed={"b"},
        skipped={"c"},
        node_errors={"b": "boom"},
    )
    assert statuses["a"] == {"status": "completed", "error": None}
    assert statuses["b"] == {"status": "error", "error": "boom"}
    assert statuses["c"] == {"status": "skipped", "error": None}


def test_failed_node_without_recorded_error_has_none():
    statuses = build_node_run_statuses(
        completed=set(), failed={"x"}, skipped=set(), node_errors={},
    )
    assert statuses["x"]["status"] == "error"
    assert statuses["x"]["error"] is None


def test_failed_node_error_is_truncated():
    long_err = "z" * 5000
    statuses = build_node_run_statuses(set(), {"x"}, set(), {"x": long_err})
    assert statuses["x"]["status"] == "error"
    assert len(statuses["x"]["error"]) == 2000


def test_skipped_does_not_clobber_terminal_status():
    # A node should never be in both, but if it were, completed/error win over skipped.
    statuses = build_node_run_statuses(
        completed={"n"}, failed=set(), skipped={"n"}, node_errors={},
    )
    assert statuses["n"]["status"] == "completed"


def test_empty_inputs_produce_empty_map():
    assert build_node_run_statuses(set(), set(), set(), {}) == {}
