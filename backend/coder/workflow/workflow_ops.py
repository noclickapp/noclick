"""Shared graph and configuration mutation helpers."""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections import deque
from typing import Any, Dict, List, Optional, Set

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
STRUCTURAL_TOOL_TYPES = frozenset({"tool", "mcp-server", "alarm", "filesystem"})


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
    fields on that operation; values are non-empty string lists.
    """
    from nodes.agent.node_op_tools import (
        list_node_operations,
        node_supports_op_tools,
        scopable_fields_for_operation,
    )

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

        if not field_scopes_raw:
            normalized.append(op_name)
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
            normalized.append({"operation": op_name, "field_scopes": field_scopes_clean})
        else:
            # All field_scopes entries normalized to empty — treat as unscoped.
            normalized.append(op_name)
    return normalized, None


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
    safe precisely because no DSL op removes a credential (``set_credentials``
    is the only credential mutation), so "absent" always means "this writer
    didn't know", never "the user detached it".
    """
    old_by_id = {
        n.get("id"): ((n.get("config") or {}).get("credentialIds") or {})
        for n in (old_nodes or [])
        if isinstance(n, dict) and n.get("id")
    }
    for node in new_nodes or []:
        if not isinstance(node, dict):
            continue
        stored = old_by_id.get(node.get("id"))
        if not stored:
            continue
        config = node.setdefault("config", {})
        incoming = config.get("credentialIds")
        if not isinstance(incoming, dict):
            incoming = {}
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


def find_foreign_expression_tokens(
    config: Dict[str, Any], skip_fields: frozenset = frozenset()
) -> List[tuple]:
    """Scan config string values (recursively) for foreign template-dialect
    accessors inside ``{{ … }}`` expression blocks.

    Returns ``[(field_path, offending_snippet), ...]``. Same walker contract
    as :func:`find_placeholder_tokens` (``skip_fields`` exempts code fields).
    """
    hits: List[tuple] = []

    def walk(value: Any, path: str) -> None:
        if isinstance(value, str):
            for block in _FOREIGN_EXPR_BLOCK_RE.finditer(value):
                m = _FOREIGN_ACCESSOR_RE.search(block.group(1))
                if m:
                    hits.append((path, m.group(0).strip()))
        elif isinstance(value, dict):
            for k, v in value.items():
                walk(v, f"{path}.{k}")
        elif isinstance(value, list):
            for i, v in enumerate(value):
                walk(v, f"{path}[{i}]")

    for key, value in (config or {}).items():
        if key not in skip_fields:
            walk(value, key)
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


def find_placeholder_tokens(
    config: Dict[str, Any], skip_fields: frozenset = frozenset()
) -> List[tuple]:
    """Scan config string values (recursively) for placeholder tokens.

    Returns ``[(field_path, token), ...]``. ``skip_fields`` names top-level
    fields to ignore — code fields (JSX object literals can look like
    placeholders) and fields owned by a downstream sanitizer.
    """
    hits: List[tuple] = []

    def walk(value: Any, path: str) -> None:
        if isinstance(value, str):
            for m in PLACEHOLDER_TOKEN_RE.finditer(value):
                hits.append((path, m.group(0)))
        elif isinstance(value, dict):
            for k, v in value.items():
                walk(v, f"{path}.{k}")
        elif isinstance(value, list):
            for i, v in enumerate(value):
                walk(v, f"{path}[{i}]")

    for key, value in (config or {}).items():
        if key not in skip_fields:
            walk(value, key)
    return hits


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
