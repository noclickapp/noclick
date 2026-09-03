"""Read node identity out of a stored workflow graph (``workflows.workflow``).

Two node shapes reach the blob: the save shape
``{id, type, config: {label, operation, model, credentialIds, …}}`` and the
canvas shape ``{id, type, data: {label, operation, config: {model, …}}}``.
Every reader here accepts both, so callers never guess which one they got.
Added for the Dashboard tab, which derives workflow "marks" (the brand icons
that identify a workflow), agent harness slugs and credential usage from graphs.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

# CLI harness slugs an agent node's ``model`` can carry; anything else is an API model.
HARNESS_SLUGS = frozenset({"codex", "claude-code", "opencode", "openclaw", "hermes"})

# Built-in trigger node types (operation-less); integration triggers are per operation.
BUILTIN_TRIGGER_TYPES = frozenset({
    "trigger-run", "trigger-webhook", "trigger-email", "trigger-cron",
    "interface-form", "trigger-form-input", "interface-config-form",
})

# Nodes that say nothing about what a workflow *is*.
_UNMARKED_TYPES = frozenset({"sticky-note", "sticky_note", "note", "tool"})


def parse_graph(graph: Any) -> Dict[str, Any]:
    """The graph as a dict; ``{}`` for NULL/invalid/non-object blobs."""
    if isinstance(graph, str):
        try:
            graph = json.loads(graph)
        except (ValueError, TypeError):
            return {}
    return graph if isinstance(graph, dict) else {}


def graph_nodes(graph: Any) -> List[Dict[str, Any]]:
    nodes = parse_graph(graph).get("nodes")
    return [n for n in nodes if isinstance(n, dict)] if isinstance(nodes, list) else []


def graph_edges(graph: Any) -> List[Dict[str, Any]]:
    edges = parse_graph(graph).get("edges")
    return [e for e in edges if isinstance(e, dict)] if isinstance(edges, list) else []


def node_config(node: Dict[str, Any]) -> Dict[str, Any]:
    """One merged config view over both shapes. Save-shape ``config`` wins;
    canvas-shape top-level ``data`` fields (label/operation/credentialIds) fill in."""
    cfg: Dict[str, Any] = {}
    data = node.get("data")
    if isinstance(data, dict):
        inner = data.get("config")
        if isinstance(inner, dict):
            cfg.update(inner)
        for key in ("label", "operation", "credentialIds", "model", "disabled"):
            if key in data and key not in cfg:
                cfg[key] = data[key]
    top = node.get("config")
    if isinstance(top, dict):
        cfg.update(top)
    return cfg


def node_type(node: Dict[str, Any]) -> str:
    return str(node.get("type") or "")


def node_label(node: Dict[str, Any]) -> str:
    return str(node_config(node).get("label") or "")


def node_operation(node: Dict[str, Any]) -> Optional[str]:
    op = node_config(node).get("operation")
    return str(op) if op else None


def node_model(node: Dict[str, Any]) -> str:
    return str(node_config(node).get("model") or "")


def node_credential_ids(node: Dict[str, Any]) -> List[str]:
    ids = node_config(node).get("credentialIds")
    if isinstance(ids, dict):
        return [str(v) for v in ids.values() if v]
    if isinstance(ids, list):
        return [str(v) for v in ids if v]
    return []


def agent_mark(model: str) -> str:
    """The icon-registry key for an agent node: ``agent:<harness>`` for a CLI
    harness, the generic ``agent`` for API models."""
    return f"agent:{model}" if model in HARNESS_SLUGS else "agent"


def is_trigger_node(node: Dict[str, Any]) -> bool:
    ntype = node_type(node)
    if ntype in BUILTIN_TRIGGER_TYPES or ntype.startswith("trigger-"):
        return True
    op = node_operation(node)
    if not op:
        return False
    # Lazy: the operation catalog is a heavy import and only integration
    # triggers need it.
    from nodes.agent.node_op_tools import is_trigger_operation

    return is_trigger_operation(ntype, op)


def node_mark(node: Dict[str, Any]) -> str:
    ntype = node_type(node)
    return agent_mark(node_model(node)) if ntype == "agent" else ntype


def workflow_marks(graph: Any, limit: int = 4) -> List[str]:
    """Distinct marks identifying a workflow: triggers first, then agents
    (with their harness), then providers in graph order."""
    nodes = graph_nodes(graph)
    triggers: List[str] = []
    agents: List[str] = []
    rest: List[str] = []
    for node in nodes:
        ntype = node_type(node)
        if not ntype or ntype in _UNMARKED_TYPES:
            continue
        mark = node_mark(node)
        if ntype == "agent":
            agents.append(mark)
        elif is_trigger_node(node):
            triggers.append(mark)
        else:
            rest.append(mark)
    out: List[str] = []
    for mark in triggers + agents + rest:
        if mark not in out:
            out.append(mark)
        if len(out) >= limit:
            break
    return out


def node_meta_map(graph: Any) -> Dict[str, Dict[str, Any]]:
    """``{node_id: {label, type, model, operation, config}}`` for one graph."""
    meta: Dict[str, Dict[str, Any]] = {}
    for node in graph_nodes(graph):
        node_id = node.get("id")
        if not node_id:
            continue
        cfg = node_config(node)
        meta[str(node_id)] = {
            "label": str(cfg.get("label") or ""),
            "type": node_type(node),
            "model": str(cfg.get("model") or ""),
            "operation": cfg.get("operation") or None,
            "config": cfg,
        }
    return meta
