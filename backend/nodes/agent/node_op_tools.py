"""
node_op tools — expose integration-node operations as agent tools.

Converts a node's per-operation config schema (the discriminated union that
get_config_schema() already emits for every registered node) into discrete
agent tool definitions: one tool per operation, named
``{provider}__{operation}`` (e.g. ``linear__create_issue``), whose parameter
schema is that operation's config fields.

The resulting (tool_params, tool_configs) plug into the existing agent tool
plumbing unchanged: SDK FunctionTools and the local CLI harness's turn-scoped
MCP endpoint both route calls through ``tool_execution.execute_tool``, where
``tool_type='node_op'`` dispatches to ``nodes/core/run_op.run_node_operation``.
"""

import json
import logging
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

from litellm import ChatCompletionToolParam, ChatCompletionToolParamFunctionChunk

logger = logging.getLogger(__name__)

# Structural node types that never qualify as op-tool providers: agents
# themselves, the existing tool-provider primitives, and graph/control-flow
# machinery (which act on graph dataflow, not standalone operations).
# Everything else qualifies purely by schema shape (has at least one
# non-trigger operation); interface-* nodes are excluded as a family.
_EXCLUDED_NODE_TYPES = {
    "agent",
    "tool",
    "mcp-server",
    "alarm",
    "filesystem",
    "noclick",
    "filter",
    "merge",
}


def _provider_slug(node_type: str) -> str:
    """automation-linear → linear (matches the schema filename convention)."""
    slug = node_type.removeprefix("automation-")
    return slug.replace("-", "_")


def _clean_property(prop: Dict[str, Any], defs: Dict[str, Any]) -> Dict[str, Any]:
    """Strip frontend-only extension keys from a field schema; keep standard
    JSON Schema plus the description the LLM needs. Refs are inlined (the
    parameter schema ships standalone into sandbox MCP configs) via the
    SHARED cycle-safe inliner. Lazy import: coder.workflow's package init
    pulls the full builder stack, which node imports shouldn't pay for."""
    from coder.workflow.workflow_schema import inline_schema_refs

    inlined = inline_schema_refs(prop, defs)
    return {
        k: v
        for k, v in inlined.items()
        if not k.startswith("ui:") and not k.startswith("x-")
    }


# ---------------------------------------------------------------------------
# Per-operation entry normalization for agent_tool_operations
# ---------------------------------------------------------------------------
# Entries are either a plain operation name string (unscoped) or
# {"operation": str, "field_scopes": {field_name: [allowed_ids]}}. The
# normalizer collapses to a parallel pair: a list of op names AND a
# {op_name: {field_name: [ids]}} field-scopes map. Used by build_provider_output
# (passthrough) and build_node_op_tools (schema injection + runtime
# enforcement).


def normalize_allowed_operations(
    entries: Any,
) -> Tuple[List[str], Dict[str, Dict[str, List[str]]]]:
    """Split a mixed allowlist into ``(op_names, scopes_by_op)``.

    Garbage entries are silently dropped — validation already ran on the
    write path (validate_agent_tool_operations); this is the runtime reader.
    """
    op_names: List[str] = []
    scopes_by_op: Dict[str, Dict[str, List[str]]] = {}
    if not isinstance(entries, list):
        return op_names, scopes_by_op
    for entry in entries:
        if isinstance(entry, str) and entry:
            op_names.append(entry)
        elif isinstance(entry, dict):
            op_name = entry.get("operation")
            if not isinstance(op_name, str) or not op_name:
                continue
            op_names.append(op_name)
            raw_scopes = entry.get("field_scopes") or {}
            if not isinstance(raw_scopes, dict):
                continue
            cleaned: Dict[str, List[str]] = {}
            for field, ids in raw_scopes.items():
                if not isinstance(field, str) or not isinstance(ids, list):
                    continue
                deduped = [i for i in dict.fromkeys(ids) if isinstance(i, str) and i]
                if deduped:
                    cleaned[field] = deduped
            if cleaned:
                scopes_by_op[op_name] = cleaned
    return op_names, scopes_by_op


@lru_cache(maxsize=None)
def scopable_fields_for_operation(node_type: str, operation: str) -> frozenset:
    """Fields of ``operation`` that can be scoped — tagged with both
    ``x-dynamic-options`` and ``x-resource-type``. Cached for the process
    lifetime (depends only on import-time-static config schemas)."""
    from nodes.core.registry import NODE_REGISTRY

    node_class = NODE_REGISTRY.get(node_type)
    if node_class is None:
        return frozenset()
    for entry in _iter_operation_defs(node_class):
        if entry["operation"] != operation:
            continue
        out = set()
        for field, prop in entry["member"].get("properties", {}).items():
            if not isinstance(prop, dict):
                continue
            if prop.get("x-dynamic-options") and prop.get("x-resource-type"):
                out.add(field)
        return frozenset(out)
    return frozenset()


@lru_cache(maxsize=None)
def resource_field_index(node_type: str) -> Tuple[Tuple[str, str, str], ...]:
    """All scopable fields on ``node_type``, as ``(operation, field, resource_type)``
    triples. Used by the auto-extend path to find every field that a newly
    created resource of a given resource_type should join."""
    from nodes.core.registry import NODE_REGISTRY

    node_class = NODE_REGISTRY.get(node_type)
    if node_class is None:
        return tuple()
    out: List[Tuple[str, str, str]] = []
    for entry in _iter_operation_defs(node_class):
        op = entry["operation"]
        for field, prop in entry["member"].get("properties", {}).items():
            if not isinstance(prop, dict):
                continue
            rt = prop.get("x-resource-type")
            if rt and prop.get("x-dynamic-options"):
                out.append((op, field, str(rt)))
    return tuple(out)


@lru_cache(maxsize=None)
def resource_creators(node_type: str) -> Tuple[Tuple[str, str, str], ...]:
    """All creator ops on ``node_type``, as ``(operation, resource_type,
    resource_id_path)`` triples. Reads ``x-creates-resource`` /
    ``x-resource-type`` / ``x-resource-id-path`` from the operation
    discriminator field. ``resource_id_path`` is a dotted path into the
    op's output dict where the new resource's ID lives."""
    from nodes.core.registry import NODE_REGISTRY

    node_class = NODE_REGISTRY.get(node_type)
    if node_class is None:
        return tuple()
    out: List[Tuple[str, str, str]] = []
    for entry in _iter_operation_defs(node_class):
        op_schema = entry["operation_schema"]
        if not op_schema.get("x-creates-resource"):
            continue
        rt = op_schema.get("x-resource-type")
        path = op_schema.get("x-resource-id-path")
        if not (isinstance(rt, str) and rt and isinstance(path, str) and path):
            logger.warning(
                f"[NodeOpTools] {node_type}.{entry['operation']}: x-creates-resource set "
                f"but x-resource-type / x-resource-id-path missing — auto-extend disabled"
            )
            continue
        out.append((entry["operation"], rt, path))
    return tuple(out)


def extract_resource_id_from_output(
    output: Any, resource_id_path: str,
) -> Optional[str]:
    """Walk a dotted path into a node's execute() output dict to pull the new
    resource ID, returned as a string. Numeric ids (PostHog, Monday, GitLab,
    …) are coerced to str; booleans are rejected. Returns None if the path
    doesn't resolve to a non-empty scalar — the create may have failed soft, or
    the schema annotation is out of date with the implementation."""
    if not resource_id_path or not isinstance(output, dict):
        return None
    cur: Any = output
    for segment in resource_id_path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(segment)
        if cur is None:
            return None
    if isinstance(cur, bool):
        return None
    if isinstance(cur, str):
        return cur or None
    if isinstance(cur, int):
        return str(cur)
    return None


def _iter_operation_defs(node_class) -> List[Dict[str, Any]]:
    """Yield resolved per-operation member schemas from a node's config schema.

    Handles both the discriminated-union shape (properties.config.oneOf of
    $refs) and a flat single-model config carrying an operation const.

    NOTE: the extension builder has a sibling enumerator
    (coder/workflow/operation_catalog.get_operations_for_node_type)
    that introspects the Pydantic union instead — it needs config CLASSES,
    this needs member JSON schemas, so they can't share one implementation.
    test_operation_enumerators_agree_across_registry pins them together.
    """
    schema = node_class.get_config_schema() or {}
    config = schema.get("properties", {}).get("config", {})
    defs = schema.get("$defs", {})

    members: List[Dict[str, Any]] = []
    refs = config.get("oneOf") or config.get("anyOf")
    if refs:
        for ref in refs:
            key = ref.get("$ref", "").split("/")[-1]
            member = defs.get(key)
            if member:
                members.append(member)
    elif "$ref" in config:
        member = defs.get(config["$ref"].split("/")[-1])
        if member:
            members.append(member)
    elif config.get("properties"):
        members.append(config)

    out = []
    for member in members:
        op = member.get("properties", {}).get("operation", {})
        const = op.get("const") or (op.get("enum") or [None])[0]
        if not const:
            continue
        if op.get("x-is-trigger"):
            continue
        out.append({"operation": const, "operation_schema": op, "member": member, "defs": defs})
    return out


@lru_cache(maxsize=None)
def _trigger_operations(node_type: str) -> frozenset:
    """Operation names flagged ``x-is-trigger`` in node_type's config schema —
    the operations that register external subscriptions and start runs."""
    from nodes.core.registry import NODE_REGISTRY

    node_class = NODE_REGISTRY.get(node_type)
    if node_class is None:
        return frozenset()
    schema = node_class.get_config_schema() or {}
    config = schema.get("properties", {}).get("config", {})
    defs = schema.get("$defs", {})
    refs = config.get("oneOf") or config.get("anyOf") or ([{"$ref": config["$ref"]}] if "$ref" in config else [])
    members = [defs.get(r.get("$ref", "").split("/")[-1]) for r in refs] or [config]
    out = set()
    for member in members:
        op = (member or {}).get("properties", {}).get("operation", {})
        const = op.get("const") or (op.get("enum") or [None])[0]
        if const and op.get("x-is-trigger"):
            out.add(const)
    return frozenset(out)


def is_trigger_operation(node_type: str, operation: Optional[str]) -> bool:
    """Whether ``operation`` is one of node_type's trigger operations."""
    return bool(operation) and operation in _trigger_operations(node_type)


def is_node_op_provider(
    node_id: str,
    node_type: str,
    workflow_nodes: Optional[List[Dict[str, Any]]],
    workflow_edges: Optional[List[Dict[str, Any]]],
) -> bool:
    """Whether this node is wired to an agent's (or a hosting-mode MCP
    node's) bottom handle as a tool provider (and is a type that can provide
    op tools). Used by the workflow execution handler to short-circuit
    execution into provider mode."""
    if not workflow_nodes or not workflow_edges:
        return False
    # Cheap edge scan FIRST: node_supports_op_tools generates the node's full
    # JSON schema (~40ms for large unions) and this predicate runs for every
    # node of every workflow run — only pay the schema cost for nodes that
    # are actually wired to a consumer.
    consumer_ids = {
        n.get("id") for n in workflow_nodes if n.get("type") in ("agent", "mcp-server")
    }
    wired = any(
        e.get("source") == node_id
        and e.get("targetHandle") == "bottom"
        and e.get("target") in consumer_ids
        for e in workflow_edges
    )
    return wired and node_supports_op_tools(node_type)


_SANDBOX_REPO_RE = r"[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+"


def normalize_sandbox_repos(value: Any) -> Tuple[Optional[List[Dict[str, str]]], Optional[str]]:
    """Normalize an ``agent_sandbox_repos`` value to ``[{'repo', 'branch'}]``.

    Accepts a JSON string, a single ``"owner/name"`` string, or a list whose
    entries are ``"owner/name"`` strings or ``{"repo", "branch"}`` dicts.
    Returns ``(normalized, error)``; an empty/missing value normalizes to
    ``([], None)``. Exact duplicate repos keep the first entry.
    """
    import re

    if value is None or value == "" or value == []:
        return [], None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            pass
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return None, (
            'agent_sandbox_repos must be a JSON array like ["owner/name"] or '
            '[{"repo": "owner/name", "branch": "dev"}].'
        )
    normalized: List[Dict[str, str]] = []
    seen: set = set()
    for entry in value:
        if isinstance(entry, str):
            entry = {"repo": entry, "branch": ""}
        if not isinstance(entry, dict) or not isinstance(entry.get("repo"), str):
            return None, (
                'Each agent_sandbox_repos entry must be "owner/name" or '
                '{"repo": "owner/name", "branch": "dev"}.'
            )
        repo = entry["repo"].strip()
        branch = entry.get("branch")
        branch = branch.strip() if isinstance(branch, str) else ""
        if not repo:
            # Draft row from the mount editor UI — absent, not an error.
            continue
        if not re.fullmatch(_SANDBOX_REPO_RE, repo):
            return None, f"Repository must be 'owner/name', got {repo!r}."
        if repo in seen:
            continue
        seen.add(repo)
        normalized.append({"repo": repo, "branch": branch})
    return normalized, None


def build_provider_output(node_type: str, raw_config: Dict[str, Any]) -> Dict[str, Any]:
    """Build the provider-mode output an integration node publishes to the
    agent instead of running an operation. Consumed by
    AgentNode._collect_tool_definitions (type='node_op_tool_provider').

    raw_config is the node's frontend config blob (flat fields, possibly a
    mirrored nested 'config' sub-object, credentialIds at either level).
    """
    nested = raw_config.get("config") if isinstance(raw_config.get("config"), dict) else {}
    merged = {**nested, **{k: v for k, v in raw_config.items() if k not in ("config", "credentials")}}

    # Pass through agent_tool_operations VERBATIM (mixed strings + scoped
    # objects). build_node_op_tools normalizes via normalize_allowed_operations
    # at collection time; the runtime reads scopes off tool_configs.
    allowed = merged.get("agent_tool_operations") or []
    if not isinstance(allowed, list):
        allowed = []

    # Shared extraction/pick (utils.credentials) — same variants the workflow
    # execution handler accepts, so a config that resolves a credential in a
    # normal run can't silently lose it in provider mode. The merge above
    # strips the 'credentials' key, so re-read legacy shapes from raw_config.
    from utils.credentials import extract_credential_ids, pick_credential_id

    credential_ids = extract_credential_ids(merged) or extract_credential_ids(raw_config)
    credential_id = pick_credential_id(credential_ids)

    label = merged.get("label")
    # Sandbox mount requests (canvas-level config, like agent_tool_operations):
    # the provider asks the agent runtime to materialize environment in the
    # bash sandbox at boot (e.g. authenticated GitHub clones). Derivation of
    # the actual setups happens later via NODE_REGISTRY[type].get_sandbox_setup.
    repos, _err = normalize_sandbox_repos(merged.get("agent_sandbox_repos"))
    return {
        "type": "node_op_tool_provider",
        "node_type": node_type,
        "allowed_operations": allowed,
        "credential_id": credential_id,
        # User-given node label ("Work Linear") — the agent-facing signal for
        # telling same-type providers apart (drives slugs + description tags).
        "label": label if isinstance(label, str) and label.strip() else None,
        "sandbox_repos": repos or [],
    }


def allowlist_requires_credentials(node_type: str, operations: List[Any]) -> bool:
    """Whether a provider's allowlisted operations need credentials — False
    when EVERY allowlisted op is x-credentials-optional (e.g. reddit's
    get_subreddit_posts). Conditional optionality (x-credentials-optional-if)
    is treated as requiring credentials — it depends on config values a
    provider doesn't pin. Empty allowlist → True (conservative).

    Accepts the mixed (string | {operation, field_scopes}) shape.
    """
    from nodes.core.registry import NODE_REGISTRY

    op_names, _ = normalize_allowed_operations(operations)
    node_class = NODE_REGISTRY.get(node_type)
    if node_class is None or not op_names:
        return True
    by_op = {e["operation"]: e for e in _iter_operation_defs(node_class)}
    for op in op_names:
        entry = by_op.get(op)
        if entry is None or entry["member"].get("x-credentials-optional") is not True:
            return True
    return False


@lru_cache(maxsize=None)
def node_supports_op_tools(node_type: str) -> bool:
    """A node qualifies as an op-tool provider iff it isn't structural
    (agent/tool/control-flow) and exposes at least one non-trigger operation.

    Cached for the process lifetime: the verdict is a pure function of the
    import-time-static NODE_REGISTRY and config models, and the underlying
    schema generation costs ~40ms for large unions.
    """
    if node_type in _EXCLUDED_NODE_TYPES or node_type.startswith("interface-"):
        return False
    from nodes.core.registry import NODE_REGISTRY

    node_class = NODE_REGISTRY.get(node_type)
    if node_class is None:
        return False
    try:
        return bool(_iter_operation_defs(node_class))
    except Exception as e:
        logger.warning(f"[NodeOpTools] Schema inspection failed for {node_type}: {e}")
        return False


def list_node_operations(node_type: str) -> List[Dict[str, Any]]:
    """All exposable (non-trigger) operations of a node with display metadata.
    Used by the allowlist UI and by build_node_op_tools."""
    from nodes.core.registry import NODE_REGISTRY

    node_class = NODE_REGISTRY.get(node_type)
    if node_class is None:
        raise ValueError(f"Unknown node type: {node_type}")

    ops = []
    for entry in _iter_operation_defs(node_class):
        op_schema = entry["operation_schema"]
        member = entry["member"]
        ops.append(
            {
                "operation": entry["operation"],
                "display_name": op_schema.get("x-display-name") or op_schema.get("title") or entry["operation"],
                "category": op_schema.get("x-category"),
                "description": member.get("description") or "",
            }
        )
    return ops


def build_node_op_tools(
    node_type: str,
    allowed_operations: List[Any],
    *,
    node_id: str,
    credential_id: Optional[str] = None,
    slug: Optional[str] = None,
    provider_label: Optional[str] = None,
    credential_label: Optional[str] = None,
) -> Tuple[List[ChatCompletionToolParam], Dict[str, Dict[str, Any]]]:
    """
    Build agent tool definitions for the allowlisted operations of a node.

    Returns (tool_params, tool_configs) in the exact shapes
    AgentNode._collect_tool_definitions produces: tool_params for the LLM,
    tool_configs entries (tool_type='node_op') carrying everything
    _execute_node_op_tool needs plus the _description/_parameters pair the
    local CLI harness advertises over its turn-scoped MCP endpoint.

    `slug` overrides the tool-name prefix ({slug}__{operation}) — used when
    multiple providers of the same node type feed one agent, so their tool
    names (and credential bindings) don't collide. `provider_label` (the
    user-given node label, e.g. "Work Linear") and `credential_label` (the
    credential's display name, e.g. "alex@work") are appended to every tool
    description so the MODEL can tell same-type providers apart — the slug
    alone is just a namespace, not a semantic signal.
    """
    from nodes.core.registry import NODE_REGISTRY

    node_class = NODE_REGISTRY.get(node_type)
    if node_class is None:
        raise ValueError(f"Unknown node type: {node_type}")

    slug = slug or _provider_slug(node_type)
    lookup_tool_name = f"{slug}__lookup_options"
    provider_tag = ""
    if provider_label or credential_label:
        parts = []
        if provider_label:
            parts.append(f"the '{provider_label}' node")
        if credential_label:
            parts.append(f"the '{credential_label}' credential")
        provider_tag = f" Acts via {' using '.join(parts)}."
    op_names, scopes_by_op = normalize_allowed_operations(allowed_operations)
    allowed = set(op_names)
    # Resource types this allowlist can CREATE — derived from creator ops.
    # When a creator for a field's resource_type is allowlisted, that field's
    # scope cannot live in the wire-level JSON-schema enum: a fresh ID minted
    # mid-run wouldn't be in the model's frozen schema and its own tool call
    # would be rejected. Drop the enum for those fields; server-side
    # enforcement (which grows with the runtime allowlist) stays the source
    # of truth. See `extend_node_field_scopes` for the runtime growth path.
    creatable_resource_types: set = {
        rt for op, rt, _path in resource_creators(node_type) if op in allowed
    }
    tool_params: List[ChatCompletionToolParam] = []
    tool_configs: Dict[str, Dict[str, Any]] = {}
    # Dynamic-option fields seen across allowlisted ops: config key →
    # {field_name (loader key), depends_on, label}. Drives the companion
    # lookup tool and the field-description enrichment.
    dynamic_fields: Dict[str, Dict[str, Any]] = {}
    # tool_name → the dynamic-option field keys that operation exposes. Used to
    # point each op tool at the lookup tool so the failure path can nudge the
    # agent to resolve a bad ID (a name passed where an ID is expected).
    op_dynamic_keys: Dict[str, List[str]] = {}
    # For the lookup tool: per-field union of scopes across allowlisted ops.
    # A field becomes None (unscoped) the moment ANY op that uses it has no
    # scope — otherwise the lookup would hide IDs an unscoped op can still see.
    lookup_field_scopes: Dict[str, Optional[List[str]]] = {}

    for entry in _iter_operation_defs(node_class):
        operation = entry["operation"]
        if operation not in allowed:
            continue
        member, defs = entry["member"], entry["defs"]
        op_schema = entry["operation_schema"]
        op_scopes = scopes_by_op.get(operation, {})

        properties: Dict[str, Any] = {}
        op_dyn_keys: List[str] = []
        for field, prop in member.get("properties", {}).items():
            # Most ui:hidden fields are discriminators, credentials, or runtime
            # state and must stay out of agent tools. Composite editors can hide
            # their backing fields from the form while explicitly exposing them
            # to agents via x-agent-tool-visible (for example HTTP request bodies).
            if field == "operation" or (
                prop.get("ui:hidden") and not prop.get("x-agent-tool-visible")
            ):
                continue
            cleaned = _clean_property(prop, defs)
            dyn = prop.get("x-dynamic-options")
            if isinstance(dyn, dict):
                dynamic_fields.setdefault(field, {
                    "field_name": dyn.get("field_name") or field,
                    "depends_on": dyn.get("depends_on"),
                    "label": prop.get("title") or field,
                })
                op_dyn_keys.append(field)
                hint = (
                    f'If you don\'t know this value, call {lookup_tool_name} '
                    f'with field="{field}" to list valid options.'
                )
                desc = (cleaned.get("description") or "").rstrip(". ")
                cleaned["description"] = f"{desc}. {hint}" if desc else hint
                # Resource-scoping: pin the schema to an enum so the model's
                # tool-call validator rejects off-list IDs at the wire layer —
                # but ONLY when this provider can't create that resource type.
                # If a creator op for the field's resource_type is allowlisted,
                # the enum would prevent the agent from passing a brand-new ID
                # it just created (the model's schema is frozen for the run);
                # server-side enforcement (which grows via extend_node_field_scopes)
                # remains the source of truth in that mode.
                scope = op_scopes.get(field)
                field_resource_type = prop.get("x-resource-type")
                enum_safe = scope and field_resource_type not in creatable_resource_types
                if scope:
                    if enum_safe:
                        cleaned["enum"] = list(scope)
                    cleaned["description"] = (
                        f"{cleaned['description']} (Restricted to a specific "
                        f"set of resources.)"
                    )
                    if field not in lookup_field_scopes:
                        lookup_field_scopes[field] = list(scope)
                    else:
                        existing = lookup_field_scopes[field]
                        if existing is not None:
                            # Union with prior scope (dedupe, stable order).
                            merged_ids = list(dict.fromkeys([*existing, *scope]))
                            lookup_field_scopes[field] = merged_ids
                else:
                    # An unscoped op using this field collapses the lookup
                    # filter — model can use IDs an unscoped op can see.
                    lookup_field_scopes[field] = None
            properties[field] = cleaned
        required = [r for r in member.get("required", []) if r in properties]

        display = op_schema.get("x-display-name") or op_schema.get("title") or operation
        description = member.get("description") or display
        if provider_tag:
            description = f"{description.rstrip('. ')}.{provider_tag}"
        parameters = {"type": "object", "properties": properties, "required": required}

        tool_name = f"{slug}__{operation}"
        tool_params.append(
            ChatCompletionToolParam(
                type="function",
                function=ChatCompletionToolParamFunctionChunk(
                    name=tool_name,
                    description=description,
                    parameters=parameters,
                ),
            )
        )
        tool_configs[tool_name] = {
            "node_id": node_id,
            "tool_type": "node_op",
            "node_type": node_type,
            "operation": operation,
            "credential_id": credential_id,
            "_description": description,
            "_parameters": parameters,
        }
        if op_scopes:
            # Server-side enforcement reads this at execute time —
            # defense-in-depth behind the schema-level enum.
            tool_configs[tool_name]["field_scopes"] = {
                k: list(v) for k, v in op_scopes.items()
            }
        if op_dyn_keys:
            op_dynamic_keys[tool_name] = op_dyn_keys

    missing = allowed - {
        tc["operation"] for tc in tool_configs.values() if tc.get("tool_type") == "node_op"
    }
    if missing:
        logger.warning(
            f"[NodeOpTools] {node_type}: allowlisted operations not found or not exposable: {sorted(missing)}"
        )

    # Companion lookup tool — only when the allowlisted ops actually carry
    # dynamic-option fields, and the node has a loader to serve them. One
    # tool per provider (field is an enum), proxying load_field_options so
    # the agent sees exactly the options the UI dropdowns show.
    if dynamic_fields and hasattr(node_class, "load_field_options"):
        field_lines = []
        for key, meta in dynamic_fields.items():
            dep = f" (requires {meta['depends_on']} in context)" if meta.get("depends_on") else ""
            field_lines.append(f"{key} = {meta['label']}{dep}")
        description = (
            "List valid options for the ID fields used by this provider's tools. "
            "Returns {options: [{label, value}], next_page_token}. Fields: "
            + "; ".join(field_lines) + "."
        )
        if provider_tag:
            description += provider_tag
        parameters = {
            "type": "object",
            "properties": {
                "field": {
                    "type": "string",
                    "enum": sorted(dynamic_fields),
                    "description": "Which field to list options for",
                },
                "context": {
                    "type": "object",
                    "description": (
                        "Field values the lookup depends on, keyed by field name "
                        '(e.g. {"spreadsheet_id": "..."} when listing sheet_name options)'
                    ),
                },
                "search": {"type": "string", "description": "Optional search filter"},
                "page_token": {"type": "string", "description": "Pagination token from a previous call"},
            },
            "required": ["field"],
        }
        tool_params.append(
            ChatCompletionToolParam(
                type="function",
                function=ChatCompletionToolParamFunctionChunk(
                    name=lookup_tool_name,
                    description=description,
                    parameters=parameters,
                ),
            )
        )
        # Drop entries where the union ended up None (unscoped) — keep only
        # fields where EVERY consuming op was scoped, so the lookup actually
        # filters there. (None entries are computed but only used as the
        # "collapse to unscoped" signal during build.)
        lookup_scopes_locked = {
            k: v for k, v in lookup_field_scopes.items()
            if isinstance(v, list) and v
        }
        tool_configs[lookup_tool_name] = {
            "node_id": node_id,
            "tool_type": "node_op_lookup",
            "node_type": node_type,
            "credential_id": credential_id,
            # config key → loader field_name, used by the dispatch branch to
            # validate the field arg and translate to the loader's key
            "fields": {k: v["field_name"] for k, v in dynamic_fields.items()},
            # config key → allowlist of valid IDs (subset of dynamic_fields keys).
            # When set, run_node_lookup intersects loaded options with this set
            # so the model can't discover off-list IDs even via search.
            "field_scopes": lookup_scopes_locked,
            "_description": description,
            "_parameters": parameters,
        }
        # Point each op tool that has dynamic ID fields at the lookup tool, so
        # when a call fails (e.g. a name passed where an ID is needed) the
        # failure path can tell the agent how to resolve the right value.
        for tname, keys in op_dynamic_keys.items():
            tool_configs[tname]["lookup_tool"] = lookup_tool_name
            tool_configs[tname]["lookup_fields"] = keys

    return tool_params, tool_configs
