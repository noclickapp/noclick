"""The single interface for node-output + graph-snapshot persistence and reads.

Every consumer in the execution engine (and the MCP / builder / load paths) goes
through THIS module rather than touching a store implementation or raw SQL
directly. The backend is the content-addressed store (``utils/cas/store``);
swapping or evolving it is a one-file change here, and nothing else moves.

This replaces the scattered ``utils.node_output_store`` imports + ad-hoc
``workflow_node_outputs`` SQL that the legacy approach spread across handlers.
"""

from __future__ import annotations

from utils.cas import store as _cas

# ── Writes ──────────────────────────────────────────────────────────────────
# Capture the run's graph once at start (idempotent; resume-safe short-circuit).
snapshot_graph = _cas.persist_graph_snapshot
# Persist a whole run's node outputs + per-node terminal statuses (at run end).
persist_outputs = _cas.persist_run_outputs
# Persist a single node's output + status (iteration sub-outputs).
persist_node = _cas.persist_node_result

# ── Reads ───────────────────────────────────────────────────────────────────
# All node outputs for one execution (resume seeding / per-execution view).
execution_outputs = _cas.read_execution_outputs
# Latest output per node across executions (canvas hydrate on workflow load).
latest_outputs = _cas.read_latest_node_outputs
# Latest output for a single node (reference resolution).
latest_output = _cas.read_latest_node_output
# Latest per-node terminal status/error (status chips on load).
latest_statuses = _cas.read_latest_node_statuses
# Last N outputs for a node across executions, newest first (history carousel).
output_history = _cas.read_node_output_history

# ── Replay (execution-log viewer) ───────────────────────────────────────────
read_graph = _cas.read_graph              # reassembled graph snapshot for a run
read_node_output = _cas.read_node_output  # one node's reassembled output for a run

__all__ = [
    "snapshot_graph", "persist_outputs", "persist_node",
    "execution_outputs", "latest_outputs", "latest_output",
    "latest_statuses", "output_history", "read_graph", "read_node_output",
]
