"""Shared graph and configuration mutation helpers."""

from __future__ import annotations

import functools
import json
import logging
import re
import time
import uuid
from collections import deque
from dataclasses import dataclass
from typing import Any, Collection, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Set, Tuple

from .workflow_xml import XmlOp

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Graph utility functions (shared by MCP handler, builder handler, etc.)
# ---------------------------------------------------------------------------

def find_predecessors(
    node_id: str,
    edges: List[Dict[str, Any]],
    all_node_ids: set,
) -> set:
    """Find all predecessor node IDs for a given node (recursive BFS backwards)."""
    predecessors: set = set()
    to_process = [node_id]
    while to_process:
        current = to_process.pop()
        for edge in edges:
            if edge.get("target") == current:
                source = edge.get("source")
                if source and source in all_node_ids and source not in predecessors:
                    predecessors.add(source)
                    to_process.append(source)
    return predecessors


# ---------------------------------------------------------------------------
# Tool-provider edges (node → agent bottom handle)
# ---------------------------------------------------------------------------
# A provider edge runs from a node's top handle into an agent's bottom handle
# and exposes the source's operations as agent tools instead of dataflow.
# targetHandle == "bottom" is the load-bearing attribute at execution time
# (nodes/agent/node_op_tools.is_node_op_provider, AgentNode._is_wired_tool_provider).

PROVIDER_SOURCE_HANDLE = "top"
PROVIDER_TARGET_HANDLE = "bottom"

# Structural tool nodes whose ONLY meaningful agent connection is provider
# wiring — an edge from one of these into an agent is normalized to
# top→bottom even without an explicit type="tools".
# Kept with the builder's structural-tool catalog so newly added native or
# runtime-discovered providers cannot be visible to one layer but rejected by
# another.
from .structural_tools import STRUCTURAL_AGENT_TOOL_TYPES as STRUCTURAL_TOOL_TYPES


def resolve_tools_edge(
    source_type: str,
    target_type: str,
    *,
    edge_type: Optional[str] = None,
    source_handle: Optional[str] = None,
) -> tuple[Optional[tuple[str, str]], Optional[str]]:
    """Classify an add_edge op as a tool-provider edge or plain dataflow.

    Returns ``(handles, error)``: *handles* is
    ``(PROVIDER_SOURCE_HANDLE, PROVIDER_TARGET_HANDLE)`` for a provider edge
    and ``None`` for plain dataflow; *error* is set when provider wiring was
    requested (``type="tools"`` or ``handle="top"``) but the endpoints don't
    support it.
    """
    wants_tools = edge_type == "tools" or source_handle == PROVIDER_SOURCE_HANDLE
    # A hosting-mode MCP node aggregates op-capable integration nodes wired
    # into its bottom handle. It has NO dataflow input, so EVERY edge into an
    # mcp-server is provider wiring — auto-normalized like structural→agent.
    if target_type == "mcp-server":
        if source_type == "mcp-server":
            return None, (
                "An MCP node cannot feed another MCP node — hosted servers don't "
                "nest. Wire the tool nodes into one MCP node, or wire both MCP "
                "nodes into the agent directly."
            )
        if source_type in STRUCTURAL_TOOL_TYPES:
            return None, (
                f"'{source_type}' cannot be hosted by an MCP node — only integration "
                f"nodes with operations can. Wire it into the agent's bottom handle "
                f"directly."
            )
        from nodes.agent.node_op_tools import node_supports_op_tools

        if not node_supports_op_tools(source_type):
            return None, (
                f"'{source_type}' cannot provide tools to an MCP node (it exposes "
                f"no operations)."
            )
        return (PROVIDER_SOURCE_HANDLE, PROVIDER_TARGET_HANDLE), None
    if wants_tools:
        if target_type != "agent":
            return None, (
                f'type="tools" edges must target an agent node (or an MCP node for '
                f"hosting) — '{target_type}' is neither. Tool-provider wiring exposes "
                f"the source node's operations as agent tools; for dataflow, re-emit "
                f"without type=\"tools\"."
            )
        if source_type not in STRUCTURAL_TOOL_TYPES:
            from nodes.agent.node_op_tools import node_supports_op_tools

            if not node_supports_op_tools(source_type):
                return None, (
                    f"'{source_type}' cannot provide agent tools (it exposes no "
                    f"operations). Use a normal edge for dataflow instead."
                )
        return (PROVIDER_SOURCE_HANDLE, PROVIDER_TARGET_HANDLE), None
    # Structural tool nodes have no dataflow meaning toward an agent — wiring
    # one to an agent IS provider wiring, so normalize the handles.
    if target_type == "agent" and source_type in STRUCTURAL_TOOL_TYPES:
        return (PROVIDER_SOURCE_HANDLE, PROVIDER_TARGET_HANDLE), None
    return None, None


def mcp_hosting_conflict(
    target_type: str,
    target_config: Optional[Dict[str, Any]],
) -> Optional[str]:
    """Wiring a provider into an MCP node that has ``server_url`` configured —
    hosting and external-proxy modes are either-or. Checked when adding an
    edge into an mcp-server node. Returns an error string on conflict."""
    if target_type != "mcp-server":
        return None
    server_url = ((target_config or {}).get("server_url") or "").strip()
    if server_url:
        return (
            "This MCP node proxies an external server (server_url is set) — hosting "
            "wired tools and proxying are either-or. Clear server_url first, or use "
            "a separate MCP node to host the tools."
        )
    return None


def mcp_server_url_conflict(
    node_id: str,
    node_type: str,
    new_server_url: Any,
    edges: List[Dict[str, Any]],
) -> Optional[str]:
    """Setting ``server_url`` on an MCP node that already hosts wired tool
    providers (bottom-handle edges INTO it) — either-or, mirror of
    mcp_hosting_conflict for the config-update direction. *edges* are
    FE-format dicts. Returns an error string on conflict."""
    if node_type != "mcp-server" or not (str(new_server_url or "").strip()):
        return None
    has_providers = any(
        e.get("target") == node_id and e.get("targetHandle") == PROVIDER_TARGET_HANDLE
        for e in edges
    )
    if has_providers:
        return (
            f"'{node_id}' hosts wired tool nodes (bottom handle) — it cannot also "
            f"proxy an external server. Remove the wired tools first, or add a "
            f"separate MCP node for the external server."
        )
    return None


def provider_dataflow_conflict(
    source_id: str,
    edges: List[Dict[str, Any]],
    *,
    new_edge_is_tools: bool,
) -> Optional[str]:
    """A node cannot both provide agent tools and feed dataflow consumers —
    in provider mode its output is tool metadata, not data. Mirrors the
    frontend's FlowCanvas.isValidConnection rule. *edges* are FE-format dicts
    (source/target/targetHandle). Returns an error string on conflict."""
    has_tools = any(
        e.get("source") == source_id and e.get("targetHandle") == PROVIDER_TARGET_HANDLE
        for e in edges
    )
    has_dataflow = any(
        e.get("source") == source_id and e.get("targetHandle") != PROVIDER_TARGET_HANDLE
        for e in edges
    )
    if new_edge_is_tools and has_dataflow:
        return (
            f"'{source_id}' already feeds dataflow consumers — a tool-provider node "
            f"does not execute in the flow, so it cannot do both. Remove its outgoing "
            f"dataflow edges first, or use a separate node instance as the provider."
        )
    if not new_edge_is_tools and has_tools:
        return (
            f"'{source_id}' is wired as a tool provider to an agent — its output is "
            f"tool metadata, not data, so it cannot also feed dataflow consumers. "
            f"Use a separate node instance for the dataflow step."
        )
    return None


def trigger_provider_conflict(
    node_type: str,
    operation: Optional[Any],
) -> Optional[str]:
    """A node whose SELECTED operation is a trigger cannot also be an agent
    tool provider (either-or): a fired trigger and provider mode fight over
    the node's output, so each role gets its own node instance — that's also
    the channels pattern (trigger node in, provider node out). Enforced when
    wiring a tools edge AND when setting `operation` on a provider-wired node.
    Returns an error string on conflict."""
    from nodes.agent.node_op_tools import is_trigger_operation

    if operation and is_trigger_operation(node_type, str(operation)):
        return (
            f"'{node_type}' has trigger operation '{operation}' selected — a node "
            f"cannot be both a workflow trigger and an agent tool provider. Add a "
            f"separate {node_type} node for the agent's tools; wire the trigger "
            f"into the agent's input instead (its event is delivered automatically)."
        )
    return None


def validate_agent_tool_operations(
    node_type: str,
    value: Any,
) -> tuple[Optional[List[Any]], Optional[str]]:
    """Validate an ``agent_tool_operations`` allowlist for a provider node.

    Returns ``(normalized_list, error)``. Each entry is either an operation
    name (string, unscoped) or ``{"operation": str, "field_scopes":
    {field_name: [allowed_ids]}}`` (scoped to specific resource IDs).
    ``field_scopes`` keys must be ``x-dynamic-options`` + ``x-resource-type``
    fields on that operation; values are non-empty string lists. An object
    entry may also ``bind`` some of the operation's parameters
    (``{param: value}``, ``nodes.agent.tool_binding``).
    """
    from nodes.agent.node_op_tools import (
        list_node_operations,
        node_supports_op_tools,
        operation_parameter_names,
        scopable_fields_for_operation,
    )
    from nodes.agent.tool_binding import BIND_KEY, template_error

    if not node_supports_op_tools(node_type):
        return None, f"'{node_type}' cannot provide agent tools (it exposes no operations)."
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            pass
    if not isinstance(value, list):
        return None, (
            'agent_tool_operations must be a JSON array of operation names '
            '(strings) or scoped entries '
            '({"operation": "...", "field_scopes": {"field": ["id1","id2"]}}).'
        )
    valid_ops = {op["operation"] for op in list_node_operations(node_type)}
    normalized: List[Any] = []
    seen_ops: set = set()
    for entry in value:
        if isinstance(entry, str):
            op_name = entry
            field_scopes_raw: Optional[Dict[str, Any]] = None
        elif isinstance(entry, dict):
            op_name = entry.get("operation")
            if not isinstance(op_name, str):
                return None, (
                    f"agent_tool_operations entry missing string 'operation': {entry!r}."
                )
            field_scopes_raw = entry.get("field_scopes")
            if field_scopes_raw is not None and not isinstance(field_scopes_raw, dict):
                return None, (
                    f"'{op_name}': field_scopes must be an object mapping "
                    f"field_name → [allowed_ids]."
                )
            bind = entry.get(BIND_KEY)
            if bind is not None and (not isinstance(bind, dict) or not bind):
                return None, f"'{op_name}': bind must be an object mapping parameter → value."
        else:
            return None, (
                f"agent_tool_operations entry must be a string or "
                f"{{operation, field_scopes}} object, got {type(entry).__name__}."
            )
        if op_name not in valid_ops:
            return None, (
                f"Unknown operation '{op_name}' for {node_type}. "
                f"Available operations: {', '.join(sorted(valid_ops))}."
            )
        if op_name in seen_ops:
            return None, f"Duplicate operation entry: '{op_name}'."
        seen_ops.add(op_name)

        bound: Dict[str, Any] = {}
        if isinstance(entry, dict) and entry.get(BIND_KEY):
            takes = operation_parameter_names(node_type, op_name) or frozenset()
            unknown = sorted(set(entry[BIND_KEY]) - takes)
            if unknown:
                return None, (f"'{op_name}' takes no parameter {', '.join(map(repr, unknown))} to bind. "
                              f"Its parameters: {', '.join(sorted(takes))}.")
            problem = template_error(entry[BIND_KEY])
            if problem:
                return None, f"'{op_name}': {problem}"
            bound = {BIND_KEY: dict(entry[BIND_KEY])}

        if not field_scopes_raw:
            normalized.append({"operation": op_name, **bound} if bound else op_name)
            continue

        scopable = scopable_fields_for_operation(node_type, op_name)
        if not scopable:
            return None, (
                f"'{op_name}' has no scopable fields — field_scopes only apply "
                f"to fields tagged with x-resource-type."
            )
        field_scopes_clean: Dict[str, List[str]] = {}
        for field_name, ids in field_scopes_raw.items():
            if field_name not in scopable:
                return None, (
                    f"'{op_name}.{field_name}' is not scopable (not tagged with "
                    f"x-resource-type). Scopable fields: {sorted(scopable)}."
                )
            if not isinstance(ids, list) or not all(isinstance(i, str) and i for i in ids):
                return None, (
                    f"'{op_name}.{field_name}': field_scopes values must be "
                    f"non-empty arrays of resource ID strings."
                )
            dedup = list(dict.fromkeys(ids))
            if dedup:
                field_scopes_clean[field_name] = dedup
        if field_scopes_clean:
            normalized.append({"operation": op_name, "field_scopes": field_scopes_clean, **bound})
        else:
            # All field_scopes entries normalized to empty — treat as unscoped.
            normalized.append({"operation": op_name, **bound} if bound else op_name)
    return normalized, None


# Canvas-level config keys outside every operation's Pydantic model (an agent's tool allowlist, sandbox mounts,
# requested env vars): a config carrying one isn't judged against the operation model.
CANVAS_ONLY_CONFIG_KEYS = frozenset({"agent_tool_operations", "agent_sandbox_repos", "agent_env_requested"})


def normalize_canvas_fields(node_type: str, updates: Dict[str, Any]) -> None:
    """Normalize the canvas-level fields a write sets (``CANVAS_ONLY_CONFIG_KEYS``), in place; raises
    ``ValueError`` naming the field when one can't be."""
    if "agent_sandbox_repos" in updates:
        from nodes.agent.node_op_tools import normalize_sandbox_repos

        repos, err = normalize_sandbox_repos(updates["agent_sandbox_repos"])
        if err:
            raise ValueError(f"agent_sandbox_repos: {err}")
        updates["agent_sandbox_repos"] = repos
    if "agent_tool_operations" in updates:
        allowed, err = validate_agent_tool_operations(node_type, updates["agent_tool_operations"])
        if err:
            raise ValueError(f"agent_tool_operations: {err}")
        updates["agent_tool_operations"] = allowed
    if "agent_env_requested" in updates:
        from nodes.agent.user_env import normalize_requested_env_vars

        requested, err = normalize_requested_env_vars(updates["agent_env_requested"])
        if err:
            raise ValueError(f"agent_env_requested: {err}")
        updates["agent_env_requested"] = requested


# ---------------------------------------------------------------------------
# Graph primitives over the stored shape ({nodes, edges} dicts)
# ---------------------------------------------------------------------------

def new_node(
    node_type: str,
    config: Optional[Dict[str, Any]],
    position: Dict[str, float],
    *,
    label: Optional[str] = None,
) -> Dict[str, Any]:
    """A node in the stored shape, its id minted from its type."""
    node_config = dict(config) if config else {}
    if label:
        node_config["label"] = label
    return {
        "id": f"{node_type}-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}",
        "type": node_type,
        "position": position,
        "config": node_config,
    }


def check_edge(
    nodes_by_id: Mapping[str, Dict[str, Any]],
    edges: List[Dict[str, Any]],
    source_id: str,
    target_id: str,
    *,
    edge_type: Optional[str] = None,
    handle: Optional[str] = None,
    source_name: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """The ``(sourceHandle, targetHandle)`` a new edge between two existing
    nodes takes: a tool-provider edge (``edge_type="tools"``, or wiring that
    can only be one) runs top→bottom, a dataflow edge keeps ``handle``, which
    must be one of the source's output handles. Raises ``ValueError`` saying
    why the edge can't be added (connectionless types, provider-vs-dataflow,
    trigger-vs-provider and hosting-vs-proxy conflicts). ``source_name`` is
    what the messages call the source."""
    from nodes.core.registry import NODE_REGISTRY, validate_edge

    name = source_name or source_id
    source, target = nodes_by_id[source_id], nodes_by_id[target_id]
    source_type, target_type = source.get("type", ""), target.get("type", "")
    edge_err = validate_edge(source_type, target_type)
    if edge_err:
        raise ValueError(edge_err)
    tools_handles, tools_err = resolve_tools_edge(source_type, target_type, edge_type=edge_type, source_handle=handle)
    if tools_err:
        raise ValueError(tools_err)
    conflict = provider_dataflow_conflict(source_id, edges, new_edge_is_tools=tools_handles is not None)
    if conflict:
        raise ValueError(conflict)
    if tools_handles:
        from utils.graph_nodes import node_config

        conflict = (trigger_provider_conflict(source_type, node_config(source).get("operation"))
                    or mcp_hosting_conflict(target_type, node_config(target)))
        if conflict:
            raise ValueError(conflict)
        return tools_handles
    if handle:
        source_class = NODE_REGISTRY.get(source_type)
        source_handles = source_class.get_output_handles() if source_class else None
        valid = {h["id"] for h in (source_handles or []) if isinstance(h, dict) and "id" in h}
        if not valid:
            raise ValueError(
                f'handle="{handle}" but source \'{name}\' ({source_type}) is a single-output node with no named '
                f"handles — remove handle= and encode any branching inside the source node's config.")
        if handle not in valid:
            shown = ", ".join(f'"{h}"' for h in sorted(valid))
            raise ValueError(f'handle="{handle}" but source \'{name}\' ({source_type}) only supports handles: {shown}.')
    return handle, None


def new_edge(source_id: str, target_id: str, source_handle: Optional[str] = None,
             target_handle: Optional[str] = None) -> Dict[str, Any]:
    edge: Dict[str, Any] = {
        "id": f"{source_id}-{target_id}" + (f"-{source_handle}" if source_handle else ""),
        "source": source_id, "target": target_id, "type": "animated",
    }
    if source_handle:
        edge["sourceHandle"] = source_handle
    if target_handle:
        edge["targetHandle"] = target_handle
    return edge


# ---------------------------------------------------------------------------
# Primitive config mutations
# ---------------------------------------------------------------------------

def strip_label_sidecars(config: dict, changed_keys: Optional[Set[str]] = None) -> List[str]:
    """Drop ``*__label`` sidecar keys from an AI-written config IN PLACE.

    The ``__label`` keys are the frontend's display cache (owned by
    DynamicOptionsField, which recreates them from dynamic options). An
    AI-written or left-behind sidecar that disagrees with its value renders
    the wrong label and blocks the frontend's self-heal because a present label
    short-circuits the options auto-load.

    Drops every ``*__label`` key, plus (when ``changed_keys`` is given) the
    now-stale sidecar of each changed base key. Returns the dropped keys.
    """
    dropped = [k for k in config if str(k).endswith("__label")]
    for key in dropped:
        config.pop(key, None)
    if changed_keys:
        for key in changed_keys:
            sidecar = f"{key}__label"
            if config.pop(sidecar, None) is not None:
                dropped.append(sidecar)
    return dropped


def deep_merge_config(base: dict, updates: dict) -> dict:
    """Deep-merge ``updates`` into ``base``, returning a new dict.

    Nested dicts are merged recursively; all other values are overwritten.
    """
    merged = dict(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge_config(merged[key], value)
        else:
            merged[key] = value
    return merged


def set_node_disabled(config: dict, disabled: bool) -> None:
    """Set or clear the disabled flag on a node config dict (in-place)."""
    config["disabled"] = disabled


def set_mock_output(config: dict, raw: Optional[str]) -> Optional[str]:
    """Set or clear mock output on a node config dict (in-place).

    *raw* is a JSON string (or ``None`` to clear).  Returns an error string
    on invalid JSON, or ``None`` on success.
    """
    if raw is None:
        config.pop("mockedOutput", None)
        return None

    try:
        config["mockedOutput"] = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return f"Invalid JSON in mock output: {raw[:100]}"
    return None


def merge_credentials(config: dict, credential_map: dict) -> None:
    """Merge credential IDs into ``config["credentialIds"]`` (in-place).

    *credential_map* is ``{provider_name: credential_id}``.
    Existing credentials for other providers are preserved.
    """
    existing = config.get("credentialIds", {})
    if not isinstance(existing, dict):
        existing = {}
    existing.update(credential_map)
    config["credentialIds"] = existing


def preserve_existing_credentials(new_nodes: list, old_nodes: list) -> None:
    """Carry already-persisted ``credentialIds`` forward onto *new_nodes*
    (in-place), so a whole-blob write can never UN-ATTACH a credential.

    The builder persists its entire graph at every turn boundary, built from a
    client-supplied ``current_graph``. A client whose canvas lost a credential
    (stale snapshot, second tab, an event applied outside the canvas's own
    writer) can therefore delete a working credential from the database.

    Additive by construction: the incoming value wins per provider key, the
    stored value survives for keys the incoming graph doesn't carry. That is
    safe because the only DSL op that removes a credential is an agent's move
    to another harness or provider (``switch_agent_harness``), and the stored
    config says when that happened: a key only the stored model used isn't
    carried.
    Otherwise "absent" means "this writer didn't know", never "the user
    detached it".
    """
    old_by_id = {
        n.get("id"): n.get("config") or {}
        for n in (old_nodes or [])
        if isinstance(n, dict) and n.get("id")
    }
    for node in new_nodes or []:
        if not isinstance(node, dict):
            continue
        old_config = old_by_id.get(node.get("id")) or {}
        stored = old_config.get("credentialIds") or {}
        if not stored:
            continue
        config = node.setdefault("config", {})
        incoming = config.get("credentialIds")
        if not isinstance(incoming, dict):
            incoming = {}
        if node.get("type") == "agent":
            unlinked = stale_model_credentials(old_config, config, {**stored, **incoming})
            stored = {k: v for k, v in stored.items() if k not in unlinked}
        merged = {**stored, **incoming}
        if merged:
            config["credentialIds"] = merged


def node_has_credential(config: dict) -> bool:
    """True if the node config has at least one non-empty PRIMARY credential id.

    Non-primary types (``agent_env``) ride the same map without authenticating the
    node, so they must not count: an agent carrying only sandbox env vars would
    otherwise look credentialed and the builder would stop asking the user to
    connect the model key it actually needs.
    """
    from utils.credentials import NON_PRIMARY_CREDENTIAL_TYPES

    cred_ids = (config or {}).get("credentialIds", {})
    if not isinstance(cred_ids, dict):
        return False
    return any(
        cid for key, cid in cred_ids.items()
        if cid and key not in NON_PRIMARY_CREDENTIAL_TYPES
    )


AGENT_MESSAGE_REQUIRED_ERROR = (
    "Message is empty. Write the agent's standing instructions in Message, or wire "
    "a trigger into the agent so each delivered event becomes the turn."
)


def agent_trigger_fed(node_id: str, nodes: Sequence[Any], edges: Sequence[Any]) -> bool:
    """Whether a trigger source feeds ``node_id`` through an input handle (not
    the bottom tools handle) — the wiring under which a delivered event is the
    agent's turn. Takes either stored shape (dict nodes/edges) or the builder's
    GraphState objects; mirrors the FE's ``getAgentTriggerSources``."""
    def _get(obj: Any, *keys: str) -> Any:
        for key in keys:
            value = obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)
            if value is not None:
                return value
        return None

    by_id = {_get(n, "id"): n for n in nodes}
    for e in edges:
        if _get(e, "target", "target_id") != node_id or _get(e, "targetHandle", "target_handle") == "bottom":
            continue
        src = by_id.get(_get(e, "source", "source_id"))
        if src is None:
            continue
        op = _get(src, "operation")
        if op is None and isinstance(src, dict):
            op = (src.get("config") or {}).get("operation") or (src.get("data") or {}).get("operation")
        if is_trigger_source(str(_get(src, "type") or ""), op):
            return True
    return False


def agent_message_error(config: Optional[Mapping[str, Any]], *, trigger_fed: bool) -> Optional[str]:
    """An agent's Message is required unless a trigger feeds it or each turn
    brings its own (``message_per_turn``) — the same rule the canvas
    (``validateNode``) and the run engine apply."""
    config = config or {}
    if trigger_fed or config.get("message_per_turn") is True or str(config.get("message") or "").strip():
        return None
    return AGENT_MESSAGE_REQUIRED_ERROR


def is_trigger_source(node_type: str, operation: Optional[str]) -> bool:
    """Whether a node acts as a trigger source: a dedicated ``trigger-*`` node,
    the unified form node (public form URL whose submissions start runs), or an
    integration node whose SELECTED operation is a trigger op. Resolves legacy
    aliases so pre-merge saved types classify like their canonical node."""
    from nodes.core.registry import resolve_node_type
    node_type = resolve_node_type(node_type or "") or ""
    if node_type.startswith("trigger-"):
        return True
    if node_type == "interface-form":
        return True
    from nodes.agent.node_op_tools import is_trigger_operation
    return is_trigger_operation(node_type, operation)


_TEMPLATE_EXPR_RE = re.compile(r"\{\{.*?\}\}", re.DOTALL)
_REF_NODE_RE = re.compile(r"\$\(\s*['\"]([^'\"]+)['\"]\s*\)")

# Standing instruction used when stripping trigger refs empties the message
# and the node carries no goal to derive one from.
DEFAULT_AGENT_STANDING_MESSAGE = (
    "Handle the incoming event according to your instructions."
)


def strip_agent_trigger_message_refs(
    config: dict,
    upstream_trigger_ids: Any,
    standing_message: Optional[str] = None,
) -> List[str]:
    """Remove template expressions referencing a DIRECT-upstream trigger from
    an agent's ``message``, replacing an emptied message with standing
    instructions (*standing_message*, usually the node goal).

    The fired trigger's event is delivered to the agent automatically
    (``resolve_agent_event``) — a templated reference is the legacy pattern
    that replaced: it re-resolves stale preloaded output on manual runs and
    injects non-string payload objects that fail config validation. ``message``
    must hold STANDING instructions for whichever event arrives.

    Mutates *config*; returns the stripped trigger ids (empty list = untouched).
    """
    message = config.get("message")
    trigger_ids = {t for t in (upstream_trigger_ids or ()) if t}
    if not isinstance(message, str) or not trigger_ids or "{{" not in message:
        return []

    stripped: set = set()

    def _replace(m: "re.Match[str]") -> str:
        hit = set(_REF_NODE_RE.findall(m.group(0))) & trigger_ids
        if hit:
            stripped.update(hit)
            return ""
        return m.group(0)

    new_message = _TEMPLATE_EXPR_RE.sub(_replace, message)
    if not stripped:
        return []
    new_message = re.sub(r"[ \t]{2,}", " ", new_message).strip()
    config["message"] = new_message or (
        (standing_message or "").strip() or DEFAULT_AGENT_STANDING_MESSAGE
    )
    return sorted(stripped)


def drop_stale_agent_discriminator(
    node_type: str, changed_fields: Any, config: dict
) -> None:
    """When a write changes an agent's ``model`` without also setting
    ``model_type``, drop the stored discriminator so validation and credential
    checks re-derive the variant from the new model (``infer_model_type``)
    instead of routing through the old one — a stale ``model_type: llm`` next
    to ``model: openclaw`` would classify a BYOK harness as platform-billed.
    """
    if (
        node_type == "agent"
        and "model" in changed_fields
        and "model_type" not in changed_fields
    ):
        config.pop("model_type", None)


# What each CLI harness is called on a node and in a scaffolded workflow's name;
# the first is the one written. Mirrors the /agents pages' displayName
# (frontend data/harness-content) and the provider titles (types/provider.tsx);
# agentCredentialModel.ts AGENT_HARNESS_NAMES mirrors this table.
AGENT_HARNESS_NAMES: Dict[str, Tuple[str, ...]] = {
    "claude_code": ("Claude Code",),
    "codex": ("Codex", "OpenAI Codex"),
    "opencode": ("OpenCode",),
    "openclaw": ("OpenClaw",),
    "hermes_agent": ("Hermes", "Hermes Agent"),
}
# NoClick's own runtime (every model that isn't a CLI harness) is named like a
# new agent node on the canvas.
SDK_AGENT_LABEL = "AI Agent"


@dataclass(frozen=True)
class AgentHarnessSwitch:
    """An agent a write moved to another harness, or to a model of another
    provider on the same one (``old == new``: only credentials change). Harness
    ids are ``model_type``s; NoClick's own runtime is ``llm``."""
    old: str
    new: str
    dropped_fields: Tuple[str, ...]
    unlinked_credentials: Tuple[str, ...]
    label: Optional[str]  # the node's new label; None keeps its own

    def as_dict(self) -> Dict[str, Any]:
        return {
            "from": self.old, "to": self.new,
            "removed_fields": list(self.dropped_fields),
            "unlinked_credentials": list(self.unlinked_credentials),
            **({"label": self.label} if self.label else {}),
        }

    @property
    def moved(self) -> bool:
        return self.old != self.new

    @property
    def changed_node(self) -> bool:
        return bool(self.dropped_fields or self.unlinked_credentials or self.label)

    def summary(self, node: str) -> str:
        if not self.moved:
            return (f"{node}'s model runs on another provider now: unlinked "
                    f"{', '.join(self.unlinked_credentials)}, which it can't use.")
        changes = [
            *([f"removed {', '.join(self.dropped_fields)}"] if self.dropped_fields else []),
            *([f"unlinked {', '.join(self.unlinked_credentials)}"] if self.unlinked_credentials else []),
            *([f"renamed it {self.label!r}"] if self.label else []),
        ]
        return f"{node} moved from {harness_name(self.old)} to {harness_name(self.new)}: {'; '.join(changes)}."


def harness_name(harness: str) -> str:
    return AGENT_HARNESS_NAMES.get(harness, (SDK_AGENT_LABEL,))[0]


def _agent_variant(config: Mapping[str, Any]) -> Optional[str]:
    """The agent config variant (``model_type``) a config runs as, or None for
    a templated model, which can't be judged until run time."""
    from nodes.agent.config.base import infer_model_type

    if any("{{" in str(config.get(k) or "") for k in ("model", "model_type")):
        return None
    probe = {k: config[k] for k in ("model", "model_type") if config.get(k)}
    return infer_model_type(probe).get("model_type", "llm")


def _agent_harness(variant: str) -> str:
    from nodes.agent.config.providers import WRAPPER_ID_BY_MODEL_TYPE

    return variant if variant in WRAPPER_ID_BY_MODEL_TYPE else "llm"


@functools.lru_cache(maxsize=None)
def _agent_variant_fields() -> Dict[str, frozenset]:
    """The config fields each agent variant adds to the ones every agent has,
    read from the AgentConfig union (``opencode`` → ``opencode_model``)."""
    import typing

    from nodes.agent.config import AgentConfig, BaseAgentFields

    shared = set(BaseAgentFields.model_fields) | {"model", "model_type"}
    out: Dict[str, frozenset] = {}
    for member in typing.get_args(typing.get_args(AgentConfig)[0]):
        cls = typing.get_args(member)[0]
        out[cls.model_fields["model_type"].default] = frozenset(set(cls.model_fields) - shared)
    return out


def _harness_switch(old_config: Mapping[str, Any], config: Mapping[str, Any]) -> Optional[Tuple[str, str]]:
    old, new = _agent_variant(old_config), _agent_variant(config)
    if old is None or new is None or _agent_harness(old) == _agent_harness(new):
        return None
    return old, new


def _judgeable_model(config: Mapping[str, Any]) -> bool:
    """Whether what an agent runs on can be told before run time: no templated
    model, harness or sub-model (a templated one reads as some provider's)."""
    from nodes.agent.config.providers import HARNESS_MODEL_FIELDS

    fields = ("model", "model_type", *HARNESS_MODEL_FIELDS.values())
    return not any("{{" in str(config.get(k) or "") for k in fields)


def stale_model_credentials(
    old_config: Mapping[str, Any], config: Mapping[str, Any], credential_ids: Any,
) -> List[str]:
    """The keys in ``credential_ids`` only the old model used, when a write
    changed what an agent runs on (another harness, or a model or sub-model of
    another provider): accepted by its old model, not by its new one, as on the
    canvas (``staleCredentialKeysForProvider``). Secondary slots (``agent_env``)
    stay, as does a Claude plan the new model refuses: ``claude_plan_refusal``
    names the fix and moving back to Claude Code takes it back. A model that
    can't be judged (templated, or one no credential runs) unlinks nothing."""
    if not isinstance(credential_ids, dict) or not (_judgeable_model(old_config) and _judgeable_model(config)):
        return []
    from nodes.agent.config.providers import (
        CLAUDE_PLAN_CREDENTIAL_TYPE,
        claude_plan_refusal,
        model_credential_accepted_types,
    )
    from utils.credentials import NON_PRIMARY_CREDENTIAL_TYPES

    kept = set(model_credential_accepted_types(dict(config)))
    if not kept:
        return []
    stale = [
        key for key in model_credential_accepted_types(dict(old_config))
        if key in credential_ids and key not in kept and key not in NON_PRIMARY_CREDENTIAL_TYPES
    ]
    if CLAUDE_PLAN_CREDENTIAL_TYPE in stale and claude_plan_refusal(dict(config), credential_ids):
        stale.remove(CLAUDE_PLAN_CREDENTIAL_TYPE)
    return stale


def switch_agent_harness(
    node_type: str,
    old_config: Mapping[str, Any],
    config: dict,
    *,
    label: str = "",
    keep_label: bool = False,
) -> Optional[AgentHarnessSwitch]:
    """When a write moves an agent to another harness, take the old one's
    leftovers off ``config`` (in place): its own fields (``opencode_model``)
    and the credentials only it used. A node named after its old harness
    ("OpenCode", "OpenCode agent") gets the new one's name, unless the write
    set ``label`` itself (``keep_label``); the caller applies it, since a
    label lives in different places. A model or sub-model of another provider
    on the same harness unlinks the credentials only the old one used too
    (``moved`` False). None when neither changed."""
    if node_type != "agent":
        return None
    switch = _harness_switch(old_config, config)
    ids = config.get("credentialIds")
    unlinked = stale_model_credentials(old_config, config, ids)
    if unlinked:
        config["credentialIds"] = {k: v for k, v in ids.items() if k not in unlinked}
    if switch is None:
        if not unlinked:
            return None
        harness = _agent_harness(_agent_variant(config))
        return AgentHarnessSwitch(harness, harness, (), tuple(unlinked), None)
    old, new = switch
    fields = _agent_variant_fields()
    dropped = sorted(
        key for key in fields.get(old, frozenset()) - fields.get(new, frozenset()) if key in config
    )
    for key in dropped:
        config.pop(key)
    old_harness, new_harness = _agent_harness(old), _agent_harness(new)
    new_label = None
    current = (label or "").strip().casefold()
    if not keep_label and any(
        current in (alias.casefold(), f"{alias.casefold()} agent")
        for alias in AGENT_HARNESS_NAMES.get(old_harness, ())
    ):
        new_label = harness_name(new_harness)
    return AgentHarnessSwitch(old_harness, new_harness, tuple(dropped), tuple(unlinked), new_label)


def rename_workflow_for_harness_switches(
    name: str, switches: Sequence[Tuple[str, str]],
) -> Optional[str]:
    """A workflow's name after its agent moved harness, when it is the name
    the scaffold gave it ("OpenCode + Confluence and Monday.com",
    lib/agentScaffold.ts); None for any other name."""
    current = name or ""
    for old, new in switches:
        for alias in AGENT_HARNESS_NAMES.get(old, ()):
            prefix = f"{alias} + "
            if current.casefold().startswith(prefix.casefold()) and current[len(prefix):].strip():
                current = f"{harness_name(new)} + {current[len(prefix):]}"
                break
    return current if current != (name or "") else None


def misplaced_agent_model(values: Mapping[str, Any]) -> Optional[str]:
    """Why an agent's config can't run because a model id sits in the wrong
    field, or None: a model only a CLI harness runs in Model (``model``), or a
    harness id in that harness's own model field (``opencode_model``, …).
    ``values`` is a whole config or just the fields a write sets; the AI write
    paths refuse such a write, and validation reports a saved one."""
    from nodes.agent.config._cli_models_loader import harness_default_model
    from nodes.agent.config.harness_model_lists import zen_gateway_refusal_sync
    from nodes.agent.config.providers import HARNESS_MODEL_FIELDS

    for field, value in values.items():
        if not isinstance(value, str) or "{{" in value:
            continue
        value = value.strip()
        if field == "model":
            refusal = zen_gateway_refusal_sync(value)
            if refusal:
                return refusal
            continue
        harness = next((h for h, f in HARNESS_MODEL_FIELDS.items() if f == field), None)
        if harness and value.lower() in HARNESS_MODEL_FIELDS:
            example = harness_default_model(harness.replace("-", "_"))
            return (
                f"{value!r} names a harness, which belongs in Model (model). {field} holds the "
                f"model the {harness} harness runs, such as {example!r}."
            )
    return None


async def read_model_catalog(nodes: Iterable[Dict[str, Any]], written: Iterable[Any] = ()) -> None:
    """Read models.dev off the event loop for the agents' Models, saved or
    ``written``: writes and verdicts judge them against it synchronously
    (``misplaced_agent_model``, ``agent_credential_requirement``); and the
    model list a write resolves a model against (``option_registries``), so a
    write never builds it under its lock."""
    from nodes.agent.config.harness_model_lists import AGENT_ZEN_MODEL_FIELDS, read_zen_catalog

    from .option_registries import warm_registries

    models = [
        *(((n.get("data") or n).get("config") or {}).get(f) for n in nodes if n.get("type") == "agent"
          for f in AGENT_ZEN_MODEL_FIELDS),
        *written,
    ]
    if any(models):  # an agent's Model may be resolved
        await warm_registries()
    await read_zen_catalog(models)


def judge_config(
    node_type: str, operation: Optional[str], config: Dict[str, Any], *, trigger_fed: bool,
) -> Dict[str, Any]:
    """Whether a node's config can run, as the run engine judges it: Pydantic +
    JSX + placeholder lint (``config_valid``, ``validation_error``), the
    required fields still empty, and an agent's Message (required unless a
    trigger feeds it) and the account its model needs."""
    from .operation_catalog import missing_required_fields, validate_node_config

    error = validate_node_config(node_type, operation or "default", config)
    if error is None and node_type == "agent":
        error = agent_message_error(config, trigger_fed=trigger_fed)
    verdict: Dict[str, Any] = {"config_valid": error is None}
    if error:
        verdict["validation_error"] = error
    missing = missing_required_fields(node_type, operation, config)
    if missing:
        verdict["missing_required"] = missing
    if node_type == "agent":
        from nodes.agent.config.providers import agent_credential_requirement, claude_plan_refusal

        req = agent_credential_requirement(config)
        refusal = claude_plan_refusal(config, config.get("credentialIds"))
        if req.required and (refusal or not node_has_credential(config)):
            verdict["agent_credential_hint"] = {
                "credential_type": req.credential_type,
                "accepted_types": list(req.accepted_types),
                "label": req.label,
                **({"refused": refusal} if refusal else {}),
            }
    return verdict


def postprocess_config(
    node_type: str,
    operation: Optional[str],
    config: Dict[str, Any],
    *,
    is_provider: bool = False,
    upstream_trigger_ids: Optional[Collection[str]] = None,
    changed_keys: Optional[Collection[str]] = None,
    prior_config: Optional[Dict[str, Any]] = None,
    harness_prior: Optional[Dict[str, Any]] = None,
    judge: bool = True,
) -> Optional[Dict[str, Any]]:
    """Canonicalize a merged node config IN PLACE and return a structured
    verdict: the post-write pass every AI and API write runs (resolve
    queryable enums → coerce stringified JSON → revert wrong-typed changed
    keys → strip placeholder auth headers and an agent's trigger references →
    ``judge_config`` unless ``judge`` is False).

    ``harness_prior`` is the whole config before an update: an agent the
    update moved to another harness drops the old one's leftovers
    (``switch_agent_harness``, judged on the resolved model), reported as
    ``harness_switch``.

    Mutates *config*: queryable-enum values are rewritten to their canonical
    id, ``__label`` display-cache sidecars are dropped (the FE re-derives
    them), stringified JSON in structured fields is parsed, and placeholder
    auth headers are removed (surfaced as a credential hint). Changed keys
    whose values are STILL wrong-typed after coercion are REVERTED to
    ``prior_config`` (dropped when absent there) and named in
    ``rejected_values``: a wrong-typed value kills every run at the node's
    runtime parse. Returns None when there's nothing to judge (a
    provider-wired node, or a config carrying canvas-only keys).
    """
    from .operation_catalog import coerce_config_value_types, config_value_errors, get_operation_schema
    from .option_registries.resolver import format_resolution_block, resolve_config_dict

    strip_label_sidecars(config)

    def _switch_harness() -> Optional[Dict[str, Any]]:
        if harness_prior is None:
            return None
        switch = switch_agent_harness(
            node_type, harness_prior, config,
            label=config.get("label", ""), keep_label="label" in (changed_keys or ()),
        )
        if switch and switch.label:
            config["label"] = switch.label
        return switch.as_dict() if switch else None

    if is_provider or (CANVAS_ONLY_CONFIG_KEYS & set(config.keys())):
        harness_switch = _switch_harness()
        return {"harness_switch": harness_switch} if harness_switch else None

    op = operation or "default"
    resolutions = resolve_config_dict(get_operation_schema(node_type, op), config)
    harness_switch = _switch_harness()

    coerced_notes = coerce_config_value_types(node_type, op, config)
    rejected_values: List[Dict[str, str]] = []
    if changed_keys:
        for key, msg in config_value_errors(node_type, op, config):
            if key not in changed_keys:
                continue
            val = config.get(key)
            if isinstance(val, str) and "{{" in val:
                continue  # runtime template — can't be judged statically
            if key not in (prior_config or {}):
                config.pop(key, None)
            else:
                config[key] = (prior_config or {})[key]
            rejected_values.append({"field": key, "error": msg})

    auth_hint = None
    if node_type == "automation-http-request":
        stripped = strip_placeholder_auth_headers(config)
        if stripped:
            cred_type, label = http_auth_credential_hint(stripped)
            auth_hint = {"credential_type": cred_type, "label": label}

    stripped_trigger_refs: List[str] = []
    if node_type == "agent":
        # Templated refs to a direct-upstream trigger break at runtime (event delivery is automatic).
        stripped_trigger_refs = strip_agent_trigger_message_refs(config, upstream_trigger_ids or ())

    verdict: Dict[str, Any] = (
        judge_config(node_type, operation, config, trigger_fed=bool(upstream_trigger_ids)) if judge else {}
    )
    if coerced_notes:
        verdict["coerced_values"] = coerced_notes
    if rejected_values:
        verdict["rejected_values"] = {
            "fields": rejected_values,
            "reason": (
                "these values were wrong-typed for the operation's schema "
                "and were NOT saved — re-send them matching the schema"
            ),
        }
    if auth_hint:
        verdict["http_auth_credential_hint"] = auth_hint
    if stripped_trigger_refs:
        verdict["stripped_trigger_refs"] = {
            "node_ids": stripped_trigger_refs,
            "reason": (
                "a wired trigger's fired event is delivered to the agent "
                "automatically — message must hold standing instructions, "
                "not a template of the event"
            ),
            "message": config.get("message"),
        }
    res_lines = [line for r in resolutions for line in format_resolution_block(r)]
    if res_lines:
        verdict["resolutions"] = res_lines
    if harness_switch:
        verdict["harness_switch"] = harness_switch
    return verdict


# ---------------------------------------------------------------------------
# Placeholder-secret detection (shared by node drafter validation, brain field ops,
# and the http-request auth-header sanitizer)
# ---------------------------------------------------------------------------
# LLMs invent tokens like {{NVIDIA_API_KEY}} / {{YOUR_TOKEN}} for secrets they
# don't have. These resolve to NOTHING at runtime (valid expressions are
# {{ $('node_id').field }} / {{ $now }} / {{ $vars.x }}), so a config carrying
# one is guaranteed broken — a placeholder Authorization header otherwise
# produces a misleading 401 and a long debugging detour.

PLACEHOLDER_TOKEN_RE = re.compile(r"\{\{\s*([A-Z][A-Z0-9_]{2,})\s*\}\}")


# Foreign expression accessors (other automation tools' template dialects)
# inside {{ … }} blocks. $('x') returns the node output DIRECTLY — there is no
# .item/.json wrapper — and $input/$items/$node[...] etc. don't exist here.
# These expressions parse at write time but fail deterministically at runtime.
_FOREIGN_EXPR_BLOCK_RE = re.compile(r"\{\{([^}]*)\}\}")
_FOREIGN_ACCESSOR_RE = re.compile(
    r"\$\(\s*['\"][^'\"]*['\"]\s*\)\s*\.item\b"
    r"|\$node\s*\["
    r"|\$input\b"
    r"|\$items\s*\("
    r"|\.itemMatching\s*\("
    r"|\$prevNode\b|\$execution\b|\$workflow\b|\$parameter\b|\$binary\b"
)


def _config_strings(
    config: Dict[str, Any], skip_fields: frozenset = frozenset()
) -> Iterator[Tuple[str, str]]:
    """Every string value in ``config`` (recursively) with its dotted/indexed
    path — the one walker behind the write-time lints. ``skip_fields`` names
    top-level fields to leave alone (code fields, sanitizer-owned fields)."""

    def walk(value: Any, path: str) -> Iterator[Tuple[str, str]]:
        if isinstance(value, str):
            yield path, value
        elif isinstance(value, dict):
            for k, v in value.items():
                yield from walk(v, f"{path}.{k}")
        elif isinstance(value, list):
            for i, v in enumerate(value):
                yield from walk(v, f"{path}[{i}]")

    for key, value in (config or {}).items():
        if key not in skip_fields:
            yield from walk(value, key)


def find_foreign_expression_tokens(
    config: Dict[str, Any], skip_fields: frozenset = frozenset()
) -> List[tuple]:
    """Scan config string values (recursively) for foreign template-dialect
    accessors inside ``{{ … }}`` expression blocks.

    Returns ``[(field_path, offending_snippet), ...]``. Same walker contract
    as :func:`find_placeholder_tokens` (``skip_fields`` exempts code fields).
    """
    hits: List[tuple] = []
    for path, text in _config_strings(config, skip_fields):
        for block in _FOREIGN_EXPR_BLOCK_RE.finditer(text):
            m = _FOREIGN_ACCESSOR_RE.search(block.group(1))
            if m:
                hits.append((path, m.group(0).strip()))
    return hits


def foreign_expression_error(path: str, snippet: str) -> str:
    """The actionable lint message for one foreign-accessor hit — shared by
    the hard validator and the soft reference warnings so wording can't
    drift."""
    return (
        f"Field '{path}' uses '{snippet}' inside an expression — that accessor "
        f"does not exist here and will fail at run time. $('node_id') already "
        f"returns the node's output object directly (no .item/.json wrapper). "
        f"Use {{{{ $('node_id').field }}}} or {{{{ $('node_id') }}}} for the whole "
        f"output; other accessors: $json, $vars, $if(cond,a,b), $ifEmpty(v,fallback), $now."
    )


# A `$('node')` read followed by its first key — `.key` or `['key']` — and
# whether that key is being CALLED (a method, not an output field).
_OUTPUT_REF_RE = re.compile(
    r"""\$\(\s*(['"])(?P<node>[^'"]+)\1\s*\)\s*"""
    r"""(?:\.(?P<key>[A-Za-z_$][\w$]*)|\[\s*(['"])(?P<bkey>[^'"]+)\4\s*\])(?P<call>\s*\()?"""
)
# A `$('step')` call, whatever is read off it.
_STEP_CALL_RE = re.compile(r"""\$\(\s*(['"])(?P<node>[^'"]+)\1\s*\)""")
# A whole `{{ step.key… }}` block in the path form the run resolves (utils/reference_resolver.py): its step, then
# at least one `.key` or index. A bare `{{word}}` may be another system's template and is left alone.
_PATH_REF_RE = re.compile(r"^(?P<node>[A-Za-z0-9_-]+)(?P<rest>(?:\.[A-Za-z0-9_]+|\[\d+\]|\[\])+)$")


def output_top_level_keys(output: Any) -> Optional[List[str]]:
    """The keys a stored node output exposes to ``$('node').key`` references,
    or None when nothing can be asserted: a non-object output, or a manual
    run's ``no_event`` placeholder (its keys describe the placeholder, not a
    delivery — read as the trigger's shape they would flag every real
    reference)."""
    if not isinstance(output, dict) or output.get("status") == "no_event":
        return None
    return [str(k) for k in output]


def _node_class(node_type: str):
    from nodes.core.registry import NODE_REGISTRY, resolve_node_type

    return NODE_REGISTRY.get(resolve_node_type(node_type or "") or "")


def declares_output_keys(node_type: str) -> bool:
    """Whether the node's code fixes its output shape (``WorkflowNode.declared_output_keys``):
    such a node never takes the shape learned from other workflows' runs."""
    from nodes.core.base import WorkflowNode

    node_class = _node_class(node_type)
    return node_class is not None and (
        node_class.declared_output_keys.__func__ is not WorkflowNode.declared_output_keys.__func__
    )


def declared_output_keys(nodes: Iterable[Any]) -> Dict[str, List[str]]:
    """Node id → the keys its output has, for each node whose code fixes its
    shape for the config it has now. ``nodes`` carry ``id``, ``type``,
    ``operation`` and ``config``."""
    declared: Dict[str, List[str]] = {}
    for node in nodes:
        node_class = _node_class(node.type)
        config = {**(node.config or {}), **({"operation": node.operation} if node.operation else {})}
        keys = node_class.declared_output_keys(config) if node_class else None
        if keys is not None:
            declared[node.id] = keys
    return declared


def known_output_keys(nodes: Iterable[Any], observed: Mapping[str, Sequence[str]]) -> Dict[str, List[str]]:
    """The top-level keys each node's output is known to have: what the node
    declares (:func:`declared_output_keys`), else ``observed`` (its stored
    output, or the shape learned across runs). A node absent from the result
    has an unknown shape."""
    return {**{node_id: list(keys) for node_id, keys in observed.items()}, **declared_output_keys(nodes)}


def _output_references(config: Dict[str, Any], skip_fields: frozenset) -> Iterator[Tuple[str, str, str]]:
    """``(field_path, node_id, key)`` for each ``$('node').key`` read inside a
    ``{{ … }}`` block, and each ``{{node.key}}`` path read; method calls
    (``$('n').toString()``) aren't reads."""
    for path, text in _config_strings(config, skip_fields):
        for block in _FOREIGN_EXPR_BLOCK_RE.finditer(text):
            for m in _OUTPUT_REF_RE.finditer(block.group(1)):
                if not m.group("call"):
                    yield path, m.group("node"), m.group("key") or m.group("bkey")
            plain = _PATH_REF_RE.match(block.group(1).strip())
            if plain and plain.group("rest").startswith("."):
                yield path, plain.group("node"), plain.group("rest")[1:].split(".")[0].split("[")[0]


def find_unknown_output_references(
    config: Dict[str, Any],
    output_keys: Mapping[str, Sequence[str]],
    skip_fields: frozenset = frozenset(),
) -> List[tuple]:
    """``$('node').key`` reads inside ``{{ … }}`` blocks whose first key is
    not among the keys ``node``'s output is known to have.

    ``output_keys`` maps node id → known top-level keys. Nodes absent from it
    are never judged (an unknown shape is not a wrong reference), nor are
    method calls (``$('n').toString()``). Returns
    ``[(field_path, node_id, key, known_keys), …]`` — same walker contract as
    :func:`find_foreign_expression_tokens`.
    """
    hits: List[tuple] = []
    for path, node_id, key in _output_references(config, skip_fields):
        known = output_keys.get(node_id)
        if known and key not in known:
            hits.append((path, node_id, key, list(known)))
    return hits


def find_output_references_to(config: Dict[str, Any], node_ids: Collection[str]) -> List[tuple]:
    """``(field_path, node_id, key)`` for each ``$('node').key`` read of one of ``node_ids``."""
    return [ref for ref in _output_references(config, frozenset()) if ref[1] in node_ids]


def unknown_output_reference_error(
    path: str, node_id: str, key: str, known_keys: Sequence[str]
) -> str:
    """The actionable lint message for one unknown-key hit — shared by the
    write-time check and the done-gate so wording can't drift."""
    shown = ", ".join(list(known_keys)[:12]) + (", …" if len(known_keys) > 12 else "")
    return (
        f"Field '{path}' reads $('{node_id}').{key}, but that node's output has no key "
        f"'{key}' — it resolves to nothing at run time. Its keys are: {shown}. Reference "
        f"one of those, or <get_output node=\"{node_id}\" /> to see the stored output."
    )


# Words a drafted {{word.key}} uses for a step that no workflow has (a drafted {{trigger.name}} emailed the owner
# "{{trigger.name}}"); any other unknown word may be another system's template ({{ contact.FIRSTNAME }}).
MISTAKEN_STEP_NAMES = frozenset({"trigger", "input", "node", "previous"})
# What an iteration step puts in scope for the steps in its loop (nodes/iteration_node.py), and the workflow's
# variables: neither is a step.
ITERATION_VARIABLES = frozenset({"item", "index", "items", "total", "row_number"})


def _near_step(word: str, node_ids: Collection[str]) -> Optional[str]:
    """The step id ``word`` is a slip of (case, a dash for an underscore, a letter or two), if any."""
    import difflib

    normal = {node_id.lower().replace("-", "_"): node_id for node_id in node_ids}
    if word.lower().replace("-", "_") in normal:
        return normal[word.lower().replace("-", "_")]
    close = difflib.get_close_matches(word, list(node_ids), n=1, cutoff=0.8)
    return close[0] if close else None


def find_missing_node_references(
    config: Dict[str, Any], node_ids: Collection[str], skip_fields: frozenset = frozenset(),
) -> List[tuple]:
    """``(field_path, reference, step, near)`` for each read of a step the
    workflow doesn't have: ``$('step')``, which fails the run there, always;
    and a ``{{word.key}}`` path, which passes through as that literal text,
    only where ``word`` is a slip of a step id here (``near``) or a name
    drafters use for a step no workflow has (:data:`MISTAKEN_STEP_NAMES`).
    Iteration variables, ``vars``, ``${{ … }}`` and other systems' templates
    (``{{ contact.FIRSTNAME }}``) are left alone."""
    hits: List[tuple] = []
    for path, text in _config_strings(config, skip_fields):
        for block in _FOREIGN_EXPR_BLOCK_RE.finditer(text):
            if block.start() > 0 and text[block.start() - 1] == "$":
                continue  # ${{ … }}: a CI system's, passed through as text
            inner = block.group(1).strip()
            for step in dict.fromkeys(m.group("node") for m in _STEP_CALL_RE.finditer(inner)):
                if step not in node_ids:
                    hits.append((path, block.group(0), step, _near_step(step, node_ids)))
            plain = _PATH_REF_RE.match(inner)
            word = plain.group("node") if plain else None
            if not word or word in node_ids or word == "vars" or word in ITERATION_VARIABLES:
                continue
            near = _near_step(word, node_ids)
            if near or word in MISTAKEN_STEP_NAMES:
                hits.append((path, block.group(0), word, near))
    return hits


def missing_node_reference_error(
    path: str, reference: str, step: str, node_ids: Collection[str], near: Optional[str] = None,
) -> str:
    """The actionable lint message for one read of a step that isn't there."""
    ids = sorted(node_ids)
    shown = ", ".join(ids[:12]) + (", …" if len(ids) > 12 else "")
    outcome = "the run fails there" if reference.lstrip("{ ").startswith("$") else "it is sent as that literal text"
    guess = f" Did you mean '{near}'?" if near else ""
    return (
        f"Field '{path}' reads {reference}, but this workflow has no step '{step}': {outcome}.{guess} Read a "
        f"step's output as {{{{ $('step_id').key }}}}; the steps here are: {shown}."
    )


STICKY_NOTE_TYPE = "stickyNote"


def workflow_steps(nodes: Iterable[Any]) -> List[Any]:
    """The nodes that are steps of the workflow (graph nodes or their stored dicts): all but sticky notes."""
    return [n for n in nodes if (n.get("type") if isinstance(n, dict) else n.type) != STICKY_NOTE_TYPE]


def step_reference_errors(
    node: Any, node_ids: Collection[str], output_keys: Mapping[str, Sequence[str]],
    fields: Optional[Collection[str]] = None,
) -> List[Tuple[str, str]]:
    """``(field_path, message)`` for each read in ``node``'s config (only
    ``fields``, when given) that can't hold at run time: a key the step's
    output doesn't have, or a step that isn't there. ``node`` carries ``type``,
    ``operation`` and ``config``; ``output_keys`` is what each step's output is
    known to have (:func:`known_output_keys`). The one check the builders run
    on a <field> write, on what the drafter wrote, and before <done/>."""
    from .operation_catalog import template_lint_skip_fields

    config = node.config or {}
    if fields is not None:
        config = {key: config[key] for key in fields if key in config}
    errors = [
        (path, unknown_output_reference_error(path, ref, key, known))
        for path, ref, key, known in find_unknown_output_references(config, output_keys)
    ]
    skip = template_lint_skip_fields(node.type, node.operation or "default", node.config or {})
    errors += [
        (path, missing_node_reference_error(path, reference, step, node_ids, near))
        for path, reference, step, near in find_missing_node_references(config, node_ids, skip)
    ]
    return errors


def find_placeholder_tokens(
    config: Dict[str, Any], skip_fields: frozenset = frozenset()
) -> List[tuple]:
    """Scan config string values (recursively) for placeholder tokens.

    Returns ``[(field_path, token), ...]``. ``skip_fields`` names top-level
    fields to ignore — code fields (JSX object literals can look like
    placeholders) and fields owned by a downstream sanitizer.
    """
    return [
        (path, m.group(0))
        for path, text in _config_strings(config, skip_fields)
        for m in PLACEHOLDER_TOKEN_RE.finditer(text)
    ]


def strip_placeholder_auth_headers(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Remove http-request headers whose value contains a placeholder token
    (e.g. ``Authorization: Bearer {{API_KEY}}``) — in place.

    The placeholder is the LLM's signal that the API needs auth: the caller
    converts the removed header into a credential input request (the node
    auto-applies bearer/api-key/basic credentials at runtime), because sending
    the literal placeholder would be a guaranteed 401. Returns the removed
    headers.
    """
    headers = config.get("headers")
    if not isinstance(headers, list):
        return []
    stripped = [
        h for h in headers
        if isinstance(h, dict)
        and isinstance(h.get("value"), str)
        and PLACEHOLDER_TOKEN_RE.search(h["value"])
    ]
    if stripped:
        config["headers"] = [h for h in headers if h not in stripped]
    return stripped


def http_auth_credential_hint(stripped_headers: List[Dict[str, Any]]) -> tuple:
    """Map stripped placeholder auth headers to ``(credential_type, label)``
    for the credential input request. Bearer-shaped Authorization headers get
    the bearer credential; anything else is an API key sent under that header
    name."""
    for h in stripped_headers:
        name = str(h.get("key", "")).strip().lower()
        value = str(h.get("value", "")).strip().lower()
        if name == "authorization" and value.startswith("bearer"):
            return ("bearertokencredential", "API Bearer Token")
    header_name = str(stripped_headers[0].get("key", "")).strip() or "header"
    return ("apikeycredential", f"API Key ({header_name})")


_VALID_SETTINGS_FIELDS = frozenset({
    "retryOnFail", "maxTries", "waitBetweenTries", "onError",
    "alwaysOutputData", "executeOnce", "notes",
})

_ON_ERROR_VALUES = frozenset({"stopWorkflow", "continueRegularOutput", "continueErrorOutput"})


def update_node_settings(config: dict, updates: dict) -> Optional[str]:
    """Merge execution settings into ``config["_settings"]`` (in-place).

    *updates* is a dict of setting_name → value.  Only the fields listed in
    ``_VALID_SETTINGS_FIELDS`` are accepted; invalid field names or out-of-range
    values return an error string.  Returns ``None`` on success.
    """
    unknown = set(updates) - _VALID_SETTINGS_FIELDS
    if unknown:
        return f"Unknown settings field(s): {', '.join(sorted(unknown))}. Valid: {', '.join(sorted(_VALID_SETTINGS_FIELDS))}"

    validated: dict = {}

    for key, raw in updates.items():
        value = str(raw).strip()

        if key in ("retryOnFail", "alwaysOutputData", "executeOnce"):
            if value.lower() in ("true", "1", "yes"):
                validated[key] = "true"
            elif value.lower() in ("false", "0", "no"):
                validated[key] = "false"
            else:
                return f"'{key}' must be 'true' or 'false', got: {value!r}"

        elif key == "maxTries":
            try:
                n = int(value)
            except ValueError:
                return f"'maxTries' must be an integer between 2 and 5, got: {value!r}"
            if not (2 <= n <= 5):
                return f"'maxTries' must be between 2 and 5, got: {n}"
            validated[key] = str(n)

        elif key == "waitBetweenTries":
            try:
                n = int(value)
            except ValueError:
                return f"'waitBetweenTries' must be an integer between 0 and 5000 (ms), got: {value!r}"
            if not (0 <= n <= 5000):
                return f"'waitBetweenTries' must be between 0 and 5000 ms, got: {n}"
            validated[key] = str(n)

        elif key == "onError":
            if value not in _ON_ERROR_VALUES:
                return f"'onError' must be one of {sorted(_ON_ERROR_VALUES)}, got: {value!r}"
            validated[key] = value

        else:  # notes
            validated[key] = value

    existing = config.get("_settings")
    if not isinstance(existing, dict):
        existing = {}
    existing.update(validated)
    config["_settings"] = existing
    return None


def _check_mismatched_tags(text: str) -> Optional[str]:
    """Quick check for obviously mismatched HTML/JSX tags.

    Returns an error description if broken, or None if OK.
    Not a full parser — just catches nesting errors like <button><button></button></button>.
    """
    import re
    # Match opening tags (not self-closing) and closing tags
    tag_pattern = re.compile(r'<(/?)([a-zA-Z][a-zA-Z0-9]*)\b[^>]*(/?)\s*>')
    stack: list[str] = []
    # Tags that are self-closing in HTML (void elements)
    void_tags = {'br', 'hr', 'img', 'input', 'meta', 'link', 'area', 'base', 'col', 'embed', 'source', 'track', 'wbr'}

    for match in tag_pattern.finditer(text):
        is_close = match.group(1) == '/'
        tag_name = match.group(2).lower()
        is_self_closing = match.group(3) == '/'

        if is_self_closing or tag_name in void_tags:
            continue
        if is_close:
            if not stack:
                return f"unexpected closing </{tag_name}> with no matching open tag"
            if stack[-1] != tag_name:
                return f"<{stack[-1]}> closed by </{tag_name}>"
            stack.pop()
        else:
            stack.append(tag_name)

    if stack:
        return f"unclosed tag(s): {', '.join(f'<{t}>' for t in stack)}"
    return None


def apply_config_patch(config: dict, field: str, patch_text: str) -> Optional[str]:
    """Apply a simplified unified diff patch to a config field (in-place).

    Returns an error string on failure, or ``None`` on success.
    """
    from .patch_utils import apply_patch, parse_patch_content

    existing_value = config.get(field)
    if existing_value is None:
        available = [k for k in config if not k.startswith('_')]
        operation = config.get('operation', 'unknown')
        return (
            f"Field {field!r} not found in node config. "
            f"Current operation: {operation!r}. "
            f"Available fields: {available}"
        )

    # Check if the patch text uses the correct format (has @@ anchors)
    chunks = parse_patch_content(patch_text)
    if not chunks:
        return (
            f"patch_config could not parse any chunks from the patch body. "
            f"Expected simplified unified diff format with @@ anchors, -old/+new lines. "
            f"Example:\n"
            f"  @@ anchor line from existing code\n"
            f"  -line to remove\n"
            f"  +line to add"
        )

    original = str(existing_value)
    patched = apply_patch(original, patch_text)
    if patched == original:
        # Build a helpful error showing what anchors were tried
        tried_anchors = [c.context_anchor for c in chunks if c.context_anchor]
        anchor_hint = f" Tried anchors: {tried_anchors}" if tried_anchors else ""
        return (
            f"patch_config had no effect — could not locate the target lines in {field!r}.{anchor_hint} "
            f"Verify the @@ anchor line and -old lines match the existing code."
        )

    # Sanity check: detect obviously broken HTML/JSX (mismatched tags)
    tag_err = _check_mismatched_tags(patched)
    if tag_err:
        return f"patch_config produced broken markup: {tag_err}. Patch was NOT applied."

    config[field] = patched
    return None


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

# Tags handled by execute_node_op (everything except graph-level ops and
# builder-specific type-aware ``field`` tags).
_NODE_OPS = frozenset({
    "disable_node",
    "enable_node",
    "mock_node",
    "unmock_node",
    "set_credentials",
    "update_settings",
    "patch_config",
    "patch",
})


def is_node_op(tag: str) -> bool:
    """Return True if *tag* is a node-level config operation."""
    return tag in _NODE_OPS


def execute_node_op(op: XmlOp, config: dict) -> Optional[str]:
    """Execute a node-level XML operation on a config dict.

    Handles: disable_node, enable_node, mock_node, unmock_node,
    set_credentials, update_settings, patch_config, patch.

    ``update_config`` is intentionally **not** included because the MCP wraps
    it with fuzzy-matching / dynamic-option pre-processing, while the builder
    uses the type-aware ``field`` tag instead.  Both systems call
    ``deep_merge_config`` directly when they need a plain config merge.

    Returns an error string on failure, or ``None`` on success.
    """
    tag = op.tag
    attrs = op.attrs
    body = op.body

    if tag == "disable_node":
        set_node_disabled(config, True)
        return None

    if tag == "enable_node":
        set_node_disabled(config, False)
        return None

    if tag == "mock_node":
        raw = body if body else attrs.get("output")
        if not raw:
            return "mock_node requires output (as body content or output attribute)"
        return set_mock_output(config, raw)

    if tag == "unmock_node":
        return set_mock_output(config, None)

    if tag == "set_credentials":
        # All non-reserved attrs are credential_type → credential_id pairs
        cred_map = {k: v for k, v in attrs.items() if k != "id"}
        if not cred_map:
            return "set_credentials requires at least one credential_type=credential_id pair"
        merge_credentials(config, cred_map)
        return None

    if tag == "update_settings":
        # All non-reserved attrs are setting_name → value pairs
        settings_map = {k: v for k, v in attrs.items() if k != "id"}
        if not settings_map:
            return "update_settings requires at least one setting attribute (e.g. retryOnFail=\"true\")"
        return update_node_settings(config, settings_map)

    if tag in ("patch_config", "patch"):
        field = attrs.get("field") or attrs.get("name")
        if not field:
            return f"{tag} requires a 'field' or 'name' attribute"
        if not body:
            return f"{tag} requires body content with patch text"
        return apply_config_patch(config, field, body)

    return f"Unknown node operation: {tag!r}"


# ---------------------------------------------------------------------------
# Sticky note positioning
# ---------------------------------------------------------------------------

def compute_node_group_bbox(
    nodes: List[Dict[str, Any]], node_ids: Set[str],
) -> Optional[Dict[str, float]]:
    """Compute bounding box covering a set of nodes (position + dimensions)."""
    from utils.autolayout import get_dims
    matched = [n for n in nodes if n.get("id") in node_ids and n.get("type") != "stickyNote"]
    if not matched:
        return None
    min_x = float("inf")
    min_y = float("inf")
    max_x = float("-inf")
    max_y = float("-inf")
    for n in matched:
        pos = n.get("position", {})
        x = pos.get("x", 0)
        y = pos.get("y", 0)
        w, h = get_dims(n)
        min_x = min(min_x, x)
        min_y = min(min_y, y)
        max_x = max(max_x, x + w)
        max_y = max(max_y, y + h)
    return {"min_x": min_x, "min_y": min_y, "max_x": max_x, "max_y": max_y}


def find_nodes_between(
    nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]],
    start_id: str, end_id: str,
) -> Set[str]:
    """Find all node IDs between start and end in the directed graph.

    Returns the intersection of descendants(start) and ancestors(end).
    This naturally handles iteration loops where body nodes cycle back
    through the iteration node to reach downstream nodes.
    """
    node_ids = {n.get("id") for n in nodes if n.get("type") != "stickyNote"}
    if start_id not in node_ids or end_id not in node_ids:
        return {start_id, end_id} & node_ids

    # Build directed adjacency (forward and reverse)
    forward: Dict[str, Set[str]] = {nid: set() for nid in node_ids}
    reverse: Dict[str, Set[str]] = {nid: set() for nid in node_ids}
    for e in edges:
        s, t = e.get("source", ""), e.get("target", "")
        if s in forward and t in forward:
            forward[s].add(t)
            reverse[t].add(s)

    # BFS forward from start (all descendants)
    descendants: Set[str] = set()
    queue = deque([start_id])
    while queue:
        curr = queue.popleft()
        if curr in descendants:
            continue
        descendants.add(curr)
        for nb in forward[curr]:
            if nb not in descendants:
                queue.append(nb)

    # BFS backward from end (all ancestors)
    ancestors: Set[str] = set()
    queue = deque([end_id])
    while queue:
        curr = queue.popleft()
        if curr in ancestors:
            continue
        ancestors.add(curr)
        for nb in reverse[curr]:
            if nb not in ancestors:
                queue.append(nb)

    return descendants & ancestors


def resolve_sticky_note_position(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """Compute position and dimensions for a sticky note from its anchor config.

    Returns {"position": {"x": ..., "y": ...}, "width": ..., "height": ...}.
    """
    PADDING = 60
    TITLE_HEIGHT = 40  # Extra space for the sticky note title/header

    # Cover mode: after + before
    after_id = config.get("_anchor_after")
    before_id = config.get("_anchor_before")
    if after_id and before_id:
        between = find_nodes_between(nodes, edges, after_id, before_id)
        bbox = compute_node_group_bbox(nodes, between)
        if bbox:
            # Detect back-edges (loops) within covered nodes — these render as
            # curved edges that need extra clearance on sides and bottom.
            has_back_edge = any(
                e.get("target") in between and e.get("source") in between
                and e.get("target") == after_id
                for e in edges
                if e.get("source") != after_id
            )
            pad_top = PADDING + TITLE_HEIGHT
            pad_sides = PADDING + (40 if has_back_edge else 0)
            pad_bottom = PADDING + (30 if has_back_edge else 0)

            w = config.get("_anchor_width") or int(bbox["max_x"] - bbox["min_x"] + pad_sides * 2)
            h = config.get("_anchor_height") or int(bbox["max_y"] - bbox["min_y"] + pad_top + pad_bottom)
            return {
                "position": {"x": bbox["min_x"] - pad_sides, "y": bbox["min_y"] - pad_top},
                "width": w,
                "height": h,
            }

    # Near mode: near + direction
    near_ids = config.get("_anchor_near")
    direction = config.get("_anchor_direction", "above")
    if near_ids:
        bbox = compute_node_group_bbox(nodes, set(near_ids))
        if bbox:
            w = config.get("_anchor_width") or max(200, int(bbox["max_x"] - bbox["min_x"] + PADDING))
            h = config.get("_anchor_height") or 150
            gap = 20
            if direction == "above":
                pos = {"x": bbox["min_x"], "y": bbox["min_y"] - h - gap}
            elif direction == "below":
                pos = {"x": bbox["min_x"], "y": bbox["max_y"] + gap}
            elif direction == "left":
                pos = {"x": bbox["min_x"] - w - gap, "y": bbox["min_y"]}
            elif direction == "right":
                pos = {"x": bbox["max_x"] + gap, "y": bbox["min_y"]}
            else:
                pos = {"x": bbox["min_x"], "y": bbox["min_y"] - h - gap}
            return {"position": pos, "width": w, "height": h}

    # Fallback: no anchoring
    return {"position": {"x": 0, "y": 0}, "width": 200, "height": 200}


def create_sticky_note_dict(
    config: Dict[str, Any],
    position: Dict[str, float],
    width: int,
    height: int,
) -> Dict[str, Any]:
    """Create a sticky note node dict for the workflow."""
    node_id = f"stickyNote-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}"
    return {
        "id": node_id,
        "type": "stickyNote",
        "position": position,
        "config": config,
        "width": width,
        "height": height,
    }


def recompute_sticky_positions(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
) -> None:
    """Recompute positions for all anchored sticky notes in-place."""
    for node in nodes:
        if node.get("type") != "stickyNote":
            continue
        config = node.get("config", {})
        if "_anchor_after" not in config and "_anchor_near" not in config:
            continue
        result = resolve_sticky_note_position(nodes, edges, config)
        node["position"] = result["position"]
        if "_anchor_width" not in config:
            node["width"] = result["width"]
        if "_anchor_height" not in config:
            node["height"] = result["height"]


# ---------------------------------------------------------------------------
# Workflow variables + authored test runs (settings-level content)
#
# The first DSL ops that write OUTSIDE the graph blob: variable definitions
# and rehearsal authoring live in workflows.settings (shallow-merged, immune
# to the graph autosave). These pure functions parse/merge; the DB write is
# each system's own (PlatformOps for the agentic builder, direct repo call
# for the MCP server), owner-gated to mirror the socket path's settings rule.
# ---------------------------------------------------------------------------

# Mirrors the FE binding regex (`{{vars.<name>}}` full-string match): names the
# FE cannot bind are refused at write time, not discovered at setup time.
VARIABLE_NAME_RE = re.compile(r"^[A-Za-z_][\w-]*$")


def parse_define_variable(op: XmlOp) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    """<define_variable name=".." description=".." per_user>value</define_variable>
    → (definition dict, None) or (None, error)."""
    name = (op.attrs.get("name") or "").strip()
    if not name:
        return None, "define_variable requires a 'name' attribute"
    if not VARIABLE_NAME_RE.match(name):
        return None, (
            f"define_variable: invalid name {name!r} — use letters, digits, "
            "underscores or hyphens, starting with a letter or underscore"
        )
    definition: Dict[str, Any] = {"name": name, "value": (op.body or "").strip()}
    description = (op.attrs.get("description") or "").strip()
    if description:
        definition["description"] = description
    per_user = op.attrs.get("per_user")
    # Bare attr parses as empty string; any value except "false" means true.
    if per_user is not None and str(per_user).lower() != "false":
        definition["per_user"] = True
    return definition, None


def upsert_variable_definitions(
    existing: Any,
    incoming: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Merge new definitions into settings.variable_definitions by name.

    An upsert REPLACES value/description/per_user for a matching name but
    never drops definitions it doesn't mention — the Variables dialog owns
    deletion. Malformed existing rows are preserved untouched (they're the
    dialog's problem, not ours to silently eat).
    """
    merged: List[Any] = list(existing) if isinstance(existing, list) else []
    by_name = {
        d.get("name"): i
        for i, d in enumerate(merged)
        if isinstance(d, dict) and d.get("name")
    }
    for definition in incoming:
        at = by_name.get(definition["name"])
        if at is None:
            by_name[definition["name"]] = len(merged)
            merged.append(dict(definition))
        else:
            # Keep an existing value when the new definition carries none —
            # declaring intent must not wipe a value the user already set.
            current = merged[at] if isinstance(merged[at], dict) else {}
            replacement = {**current, **definition}
            if not definition.get("value") and current.get("value"):
                replacement["value"] = current["value"]
            merged[at] = replacement
    return merged


def parse_add_test_run(op: XmlOp) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    """<add_test_run trigger="node_id" name=".." title=".." author=".." handle="..">body</add_test_run>
    → ({trigger_ref, name, lead}, None) or (None, error)."""
    trigger_ref = (op.attrs.get("trigger") or "").strip()
    if not trigger_ref:
        return None, "add_test_run requires a 'trigger' attribute (trigger node id or type)"
    name = (op.attrs.get("name") or "").strip()
    if not name:
        return None, "add_test_run requires a 'name' attribute"
    body = (op.body or "").strip()
    if not body:
        return None, "add_test_run requires body content (the staged message body)"
    title = (op.attrs.get("title") or "").strip()
    lead: Dict[str, str] = {
        "title": title or name,
        "meta": (op.attrs.get("author") or "").strip() or title or name,
        "body": body,
    }
    for key in ("author", "handle"):
        value = (op.attrs.get(key) or "").strip()
        if value:
            lead[key] = value
    return {"trigger_ref": trigger_ref, "name": name, "lead": lead}, None


def _test_run_slug(name: str, taken: Set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "test-run"
    slug = base
    n = 2
    while slug in taken:
        slug = f"{base}-{n}"
        n += 1
    return slug


def append_rehearsal_run(
    authoring: Any,
    node_type: str,
    name: str,
    lead: Dict[str, str],
    base_key: str,
) -> tuple[Dict[str, Any], str]:
    """Append an authored test run to settings.rehearsal_authoring.

    Returns (new authoring dict, run slug). Matches the FE authoring shape
    exactly (useRehearsalAuthoring): runs keyed by trigger node TYPE, names
    keyed `{type}:{slug}`. A run whose name already exists for the trigger is
    replaced in place — re-running the builder must not stack duplicates.
    """
    base = authoring if isinstance(authoring, dict) else {}
    runs = dict(base.get("runs") or {})
    names = dict(base.get("names") or {})
    entries = [dict(r) for r in (runs.get(node_type) or []) if isinstance(r, dict)]

    replaced = None
    for i, entry in enumerate(entries):
        if names.get(f"{node_type}:{entry.get('slug')}") == name:
            replaced = i
            break
    if replaced is not None:
        slug = entries[replaced].get("slug") or _test_run_slug(name, set())
        entries[replaced] = {"slug": slug, "backendKey": base_key, "lead": dict(lead)}
    else:
        taken = {str(entry.get("slug")) for entry in entries}
        slug = _test_run_slug(name, taken)
        entries.append({"slug": slug, "backendKey": base_key, "lead": dict(lead)})

    runs[node_type] = entries
    names[f"{node_type}:{slug}"] = name
    return {**base, "runs": runs, "names": names}, slug
