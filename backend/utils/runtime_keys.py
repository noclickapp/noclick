"""Runtime keys: the ``_``-prefixed node config keys the server sets on a run.

An agent's turn bindings (``_sandboxCheckouts``, ``_sandboxVolumes``,
``_sandboxPlace``, ``_sandboxEnv``, ``_turnNote``, ``_memoryReadonly``, …) and a
delivery's data (``_triggerPayload``, ``_deliveredEvent``) say what a run may
reach, for whom and who pays, so only the server sets them, for the run at hand:

- no write of a graph keeps one: every writer of ``workflows.workflow`` (and of
  a checkpoint) passes its graph through ``graph_without_runtime_keys``
  (``tests/test_runtime_keys_writes.py`` is the ratchet);
- a run takes none from a saved graph or a client's request: the executor
  strips them (``nodes_without_runtime_keys``) and honours only a server
  caller's config overrides, plus the ``DELIVERED_KEYS`` server code puts on
  the graph it hands the engine.

The few ``_``-prefixed keys a person or the builder writes (``AUTHORED_KEYS``)
are config like any other.
"""

from __future__ import annotations

import json
from typing import Any, Collection, Dict, List, Mapping, Optional

AUTHORED_KEYS = frozenset({
    "_settings",  # the node's settings panel (on-error handling, …)
    # A sticky note's anchoring, written by the builder and MCP.
    "_anchor_after", "_anchor_before", "_anchor_near", "_anchor_direction", "_anchor_width", "_anchor_height",
})

# What server code puts on a node of a graph it hands the engine to run: the
# fired trigger's payload, a CLI turn's reply, the failed run an on-error node
# reports. Any other runtime key reaches a run only as a server caller's
# config override.
DELIVERED_KEYS = frozenset({"_triggerPayload", "_agent_turn_output", "_error_inputs"})


def is_runtime_key(key: Any) -> bool:
    return isinstance(key, str) and key.startswith("_") and key not in AUTHORED_KEYS


def config_without_runtime_keys(config: Mapping[str, Any], keep: Collection[str] = ()) -> Dict[str, Any]:
    """``config`` without its runtime keys (except ``keep``), its nested
    ``config`` mirror's included: the executor flattens that into the node's
    config."""
    out = {k: v for k, v in config.items() if k in keep or not is_runtime_key(k)}
    if isinstance(out.get("config"), Mapping):
        out["config"] = config_without_runtime_keys(out["config"], keep)
    return out


def node_without_runtime_keys(node: Any, keep: Collection[str] = ()) -> Any:
    """A copy of a stored node (either shape: ``config``, or ``data.config``)
    without runtime keys."""
    if not isinstance(node, Mapping):
        return node
    out = dict(node)
    if isinstance(out.get("config"), Mapping):
        out["config"] = config_without_runtime_keys(out["config"], keep)
    data = out.get("data")
    if isinstance(data, Mapping) and isinstance(data.get("config"), Mapping):
        out["data"] = {**data, "config": config_without_runtime_keys(data["config"], keep)}
    return out


def nodes_without_runtime_keys(nodes: Optional[List[Any]], keep: Collection[str] = ()) -> Optional[List[Any]]:
    return None if nodes is None else [node_without_runtime_keys(n, keep) for n in nodes]


def graph_without_runtime_keys(graph: Any) -> Any:
    """A workflow blob (dict, or its JSON text: returned as given) without
    runtime keys on any node; ``None`` stays ``None``."""
    if isinstance(graph, str):
        try:
            parsed = json.loads(graph)
        except ValueError:
            return graph
        return json.dumps(graph_without_runtime_keys(parsed)) if isinstance(parsed, dict) else graph
    if not isinstance(graph, Mapping) or not isinstance(graph.get("nodes"), list):
        return graph
    return {**graph, "nodes": nodes_without_runtime_keys(graph["nodes"])}


def runtime_key_refusal(field: str) -> Optional[str]:
    """Why a config write of ``field`` is refused, for the builder and MCP; None when it isn't."""
    if not is_runtime_key(field):
        return None
    return (f"'{field}' is set by NoClick on a run and can't be written into a node's config. "
            "Set the node's own fields instead.")
