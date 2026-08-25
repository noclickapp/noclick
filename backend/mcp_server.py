"""
FastMCP server for external MCP clients (Claude Code, Cursor) to manage workflows.

Provides workflow CRUD, batch XML mutations via update_workflow, and execution tools
with OAuth authentication. Emits builder-style events to connected frontends for
real-time canvas animations.
"""

import hashlib
import json
import os
import re
import uuid
import time
import xml.etree.ElementTree as ET
import logging
import asyncio
from contextvars import ContextVar
from typing import Any, Dict, List, Literal, Optional, Tuple, Union, get_args, get_origin

import litellm

from fastmcp import FastMCP
from fastmcp.tools import ToolResult
from mcp.types import TextContent
from mcp_adapter.branding import NOCLICK_WEBSITE_URL, noclick_icons

from utils.database_pool import DatabasePoolMixin
from utils.access_control import check_resource_access, Permission
from nodes.core.registry import NODE_REGISTRY
from coder.workflow.operation_catalog import (
    get_operations_for_node_type,
    get_operation_schema,
    node_accepted_credential_types,
    validate_node_config,
    missing_required_fields,
    coerce_config_value_types,
    config_value_errors,
)
from coder.workflow.option_registries.resolver import resolve_config_dict, format_resolution_block
from coder.workflow.workflow_xml import XmlOp, parse_xml, coerce_value, coerce_value_for_field, escape_xml_attr
from coder.workflow.workflow_ops import (
    PROVIDER_TARGET_HANDLE,
    append_rehearsal_run,
    parse_add_test_run,
    parse_define_variable,
    upsert_variable_definitions,
    deep_merge_config,
    drop_stale_agent_discriminator,
    is_trigger_source,
    strip_agent_trigger_message_refs,
    strip_label_sidecars,
    set_node_disabled,
    set_mock_output,
    merge_credentials,
    node_has_credential,
    apply_config_patch,
    update_node_settings,
    mcp_hosting_conflict,
    mcp_server_url_conflict,
    provider_dataflow_conflict,
    trigger_provider_conflict,
    resolve_sticky_note_position,
    create_sticky_note_dict,
    resolve_tools_edge,
    validate_agent_tool_operations,
    strip_placeholder_auth_headers,
    http_auth_credential_hint,
)
from nodes.core.registry import validate_edge
from coder.workflow.workflow_schema import (
    resolve_schema_refs,
    compact_schema,
    extract_output_paths,
    get_discriminator_field,
    strip_discriminator,
)
from utils.expression_evaluator import is_js_expression, extract_expression_node_ids
from utils.credentials import (
    get_credential,
    list_credentials,
    get_workflow_owner_id,
    authorize_credentials_for_workflow,
    resolve_accessible_credential_types,
)

logger = logging.getLogger(__name__)

# ── MCP Apps widget constants ──

WIDGET_WORKFLOW_VIEWER = "ui://noclick/workflow-viewer.html"
_WIDGET_URIS = {WIDGET_WORKFLOW_VIEWER}
from utils.hosted_defaults import frontend_url, mcp_server_url

_MCP_APP_MIME = "text/html;profile=mcp-app"  # FastMCP rejects semicolons in Pydantic; patched after creation
_FRONTEND_URL = frontend_url()
_MCP_SERVER_URL = mcp_server_url()
# Claude.ai requires ui.domain = sha256(mcp_server_url)[:32] + ".claudemcpcontent.com"
_CLAUDE_WIDGET_DOMAIN = hashlib.sha256(_MCP_SERVER_URL.encode()).hexdigest()[:32] + ".claudemcpcontent.com"

# Maps tool names → widget resource URIs.  Used by _patch_widget_metadata()
# so ChatGPT knows which widget to render for each tool's result.
TOOL_WIDGET_MAP: Dict[str, str] = {
    "get_workflow": WIDGET_WORKFLOW_VIEWER,
    "get_current_workflow": WIDGET_WORKFLOW_VIEWER,
}

# CSP metadata for MCP Apps hosts. Both standard (camelCase) and ChatGPT
# legacy (snake_case, openai/ prefix) formats are needed.
_WIDGET_CSP_META = {
    "ui": {
        "domain": _CLAUDE_WIDGET_DOMAIN,
        "csp": {
            "connectDomains": [_FRONTEND_URL],
            "imgDomains": [_FRONTEND_URL],
        },
    },
    "openai/widgetDomain": _FRONTEND_URL,
    "openai/widgetCSP": {
        "connect_domains": [_FRONTEND_URL],
        "img_domains": [_FRONTEND_URL],
    },
}

# CORS headers for all MCP-related paths (OAuth discovery, streamable HTTP, etc.)
_MCP_CORS_PREFIXES = ("/mcp", "/.well-known/oauth", "/.well-known/openid", "/register", "/authorize", "/token")
_MCP_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type, Mcp-Session-Id, mcp-protocol-version",
    "Access-Control-Expose-Headers": "Mcp-Session-Id",
    "Access-Control-Max-Age": "86400",
}

# Reference pattern for validating node references in config values
_REFERENCE_PATTERN = re.compile(r'\{\{([^}]+)\}\}')

# Interface grid constants
_INTERFACE_GRID_COLS = 12
_INTERFACE_DEFAULT_LAYOUT = {"defaultW": 6, "defaultH": 4, "minW": 3, "minH": 2}


def _get_interface_block_constraints() -> Dict[str, Dict[str, int]]:
    """Build block constraints from NODE_REGISTRY at runtime.

    Reads WorkflowNode.grid_layout from each interface-* node class,
    so adding a new interface node automatically includes its constraints.
    """
    constraints: Dict[str, Dict[str, int]] = {}
    for node_type, node_cls in NODE_REGISTRY.items():
        if not node_type.startswith("interface-"):
            continue
        block_type = node_type[len("interface-"):]
        layout = getattr(node_cls, "grid_layout", None)
        if layout:
            constraints[block_type] = layout
    return constraints


def _derive_block_type(node_type: str) -> Optional[str]:
    """Derive block type from interface node type (e.g. 'interface-markdown' -> 'markdown')."""
    if not node_type.startswith("interface-"):
        return None
    return node_type[len("interface-"):]


def _check_overlaps(layout: List[Dict[str, Any]]) -> Optional[str]:
    """Check for overlapping blocks in the layout. Returns error message or None."""
    for i, a in enumerate(layout):
        for b in layout[i + 1:]:
            if (a["x"] < b["x"] + b["w"] and a["x"] + a["w"] > b["x"] and
                    a["y"] < b["y"] + b["h"] and a["y"] + a["h"] > b["y"]):
                return f"Blocks {a['i']} and {b['i']} overlap"
    return None


def _auto_layout_interface(
    layout_by_id: Dict[str, Dict[str, Any]],
    interface_nodes: Dict[str, str],
    constraints: Dict[str, Dict[str, int]],
    strategy: str = "grid",
) -> None:
    """Auto-arrange interface blocks. Mutates layout_by_id in place."""
    block_ids = list(layout_by_id.keys())
    if not block_ids:
        return

    if strategy == "stack":
        y = 0
        for bid in block_ids:
            block_type = interface_nodes.get(bid, "")
            c = constraints.get(block_type, _INTERFACE_DEFAULT_LAYOUT)
            w = min(c["defaultW"], 12)
            h = c["defaultH"]
            layout_by_id[bid] = {"i": bid, "x": 0, "y": y, "w": w, "h": h}
            y += h
    else:
        # 2-column balanced grid (left col x=0..5, right col x=6..11)
        left_y = 0
        right_y = 0
        for bid in block_ids:
            block_type = interface_nodes.get(bid, "")
            c = constraints.get(block_type, _INTERFACE_DEFAULT_LAYOUT)
            w = min(c["defaultW"], 6)
            h = c["defaultH"]
            if left_y <= right_y:
                layout_by_id[bid] = {"i": bid, "x": 0, "y": left_y, "w": w, "h": h}
                left_y += h
            else:
                layout_by_id[bid] = {"i": bid, "x": 6, "y": right_y, "w": w, "h": h}
                right_y += h


def _parse_xml_operations(xml: str) -> List[Dict[str, Any]]:
    """Parse XML operations string into a list of {tag, attrs, body?} dicts.

    Delegates to the shared XML parser (workflow_xml.parse_xml) and converts
    XmlOp objects to the dict format expected by the processing code.
    """
    return [
        {"tag": op.tag, "attrs": op.attrs, **({"body": op.body} if op.body is not None else {})}
        for op in parse_xml(xml)
    ]


# Aliases — delegate to shared implementations
_coerce_config_value = coerce_value
_escape_xml_attr = escape_xml_attr

# Tags update_workflow actually applies. Tags parsed by the shared DSL but NOT
# in this set (agentic-loop tags, canonical <field>/<patch>) are rejected rather
# than silently dropped (P1).
_UPDATE_WORKFLOW_TAGS = frozenset({
    "add_node", "add_edge", "update_config", "set_credentials",
    "disable_node", "enable_node", "mock_node", "unmock_node",
    "update_settings", "patch_config", "remove_edge", "remove_node",
    "add_sticky_note",
    "define_variable", "add_test_run", "run_test",
})


def _coerce_field_value(node_type: str, operation: Optional[str], field_name: str, raw_value: str) -> Any:
    """Schema-aware field coercion for MCP add_node / update_workflow.

    Resolves the field's JSON schema (via the node type and operation) and
    delegates to ``coerce_value_for_field``. This keeps ``value="false"`` as
    a string when the field is a string-typed enum, avoiding the Pydantic
    bool/str validation loop that the AI builder hit on ``show_in_interface``.

    Falls back to plain ``coerce_value`` if the schema can't be resolved.
    """
    field_schema = None
    if operation:
        schema = get_operation_schema(node_type, operation)
        if schema:
            field_schema = schema.get("properties", {}).get(field_name)
    return coerce_value_for_field(raw_value, field_schema)


def _workflow_to_xml(nodes: List[Dict], edges: List[Dict]) -> str:
    """Convert workflow nodes and edges to the update_workflow XML format."""
    lines = []
    for n in nodes:
        node_id = n.get("id", "")
        node_type = n.get("type", "")
        # Get config - handle both flat and nested data formats
        config = n.get("config") or n.get("data") or {}
        if isinstance(config, dict) and "config" in config:
            config = config.get("config", {})

        # Sticky notes get their own tag with anchor params and body content
        if node_type == "stickyNote":
            pos = n.get("position", {})
            pos_x = pos.get("x", 0) if isinstance(pos, dict) else 0
            pos_y = pos.get("y", 0) if isinstance(pos, dict) else 0
            style = n.get("style") or {}
            nw = n.get("width") or (style.get("width") if isinstance(style, dict) else None) or 200
            nh = n.get("height") or (style.get("height") if isinstance(style, dict) else None) or 200
            attrs = f'id="{_escape_xml_attr(node_id)}" x="{pos_x}" y="{pos_y}" width="{nw}" height="{nh}"'
            color = config.get("color", 8)
            attrs += f' color="{color}"'
            # Include anchor params so LLM can see/update positioning
            if config.get("_anchor_after"):
                attrs += f' after="{_escape_xml_attr(config["_anchor_after"])}"'
            if config.get("_anchor_before"):
                attrs += f' before="{_escape_xml_attr(config["_anchor_before"])}"'
            if config.get("_anchor_near"):
                attrs += f' near="{_escape_xml_attr(",".join(config["_anchor_near"]))}"'
            if config.get("_anchor_direction"):
                attrs += f' direction="{_escape_xml_attr(config["_anchor_direction"])}"'
            content = config.get("content", "")
            if content:
                lines.append(f"<sticky_note {attrs}>{_escape_xml_attr(content)}</sticky_note>")
            else:
                lines.append(f"<sticky_note {attrs} />")
            continue

        # Include position for widget SVG canvas rendering
        pos = n.get("position", {})
        pos_x = pos.get("x", 0) if isinstance(pos, dict) else 0
        pos_y = pos.get("y", 0) if isinstance(pos, dict) else 0
        attrs = f'id="{_escape_xml_attr(node_id)}" type="{_escape_xml_attr(node_type)}" x="{pos_x}" y="{pos_y}"'
        # Include per-instance dimensions (from ReactFlow resize or style).
        # The React widget uses real node components with their own default sizes,
        # so 90×90 fallback is fine — nodes auto-size to their content.
        style = n.get("style") or {}
        nw = n.get("width") or (style.get("width") if isinstance(style, dict) else None) or 90
        nh = n.get("height") or (style.get("height") if isinstance(style, dict) else None) or 90
        attrs += f' width="{nw}" height="{nh}"'
        has_output = False
        has_mock = False
        for k, v in config.items():
            if k == "output":
                has_output = v is not None
                continue
            if k == "mockedOutput":
                has_mock = v is not None
                continue
            if k == "configValid":
                continue
            val_str = json.dumps(v) if not isinstance(v, str) else v
            attrs += f' {k}="{_escape_xml_attr(val_str)}"'
        if has_output:
            attrs += ' has_output="true"'
        if has_mock:
            attrs += ' has_mock="true"'
        node_class = NODE_REGISTRY.get(node_type)
        if node_class:
            handles = node_class.get_output_handles()
            if handles:
                handle_summary = ", ".join(f"{h['id']}={h['label']}" for h in handles)
                attrs += f' output_handles="{_escape_xml_attr(handle_summary)}"'
        lines.append(f"<node {attrs} />")

    agent_ids = {n.get("id") for n in nodes if n.get("type") == "agent"}
    for e in edges:
        source = e.get("source", "")
        target = e.get("target", "")
        # Provider edges round-trip as type="tools" (the form add_edge accepts)
        # rather than raw handles.
        if e.get("targetHandle") == PROVIDER_TARGET_HANDLE and target in agent_ids:
            lines.append(f'<edge from="{_escape_xml_attr(source)}" to="{_escape_xml_attr(target)}" type="tools" />')
            continue
        handle_attr = ""
        if e.get("sourceHandle"):
            handle_attr = f' handle="{_escape_xml_attr(e["sourceHandle"])}"'
        lines.append(f'<edge from="{_escape_xml_attr(source)}" to="{_escape_xml_attr(target)}"{handle_attr} />')

    return "\n".join(lines)

def _normalize_credential_name(name: str) -> str:
    """Normalize credential class name to snake_case format (e.g. GoogleSheetsOAuthCredential -> google_sheets_oauth)."""
    name = re.sub(r'Credential$', '', name)
    name = re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()
    name = name.replace('_o_auth', '_oauth').replace('_a_p_i', '_api')
    if name.startswith('o_auth'):
        name = 'oauth' + name[6:]
    if name.startswith('a_p_i'):
        name = 'api' + name[5:]
    return name


def _extract_credential_type(annotation) -> Optional[str]:
    """Extract credential type string from a type annotation (handles Optional[X])."""
    origin = get_origin(annotation)
    if origin is Union:
        for arg in get_args(annotation):
            if arg is not type(None):
                if hasattr(arg, '__name__'):
                    return _normalize_credential_name(arg.__name__)
        return None
    if hasattr(annotation, '__name__'):
        return _normalize_credential_name(annotation.__name__)
    return None


def _get_credential_type_for_node(node_type: str) -> Optional[str]:
    """Get the credential_type string for a node type, or None if it doesn't need credentials."""
    node_class = NODE_REGISTRY.get(node_type)
    if not node_class:
        return None
    config_model = node_class.get_config_model()
    if not config_model or not hasattr(config_model, 'model_fields'):
        return None
    cred_field = config_model.model_fields.get('credentials')
    if not cred_field or not cred_field.annotation:
        return None
    return _extract_credential_type(cred_field.annotation)


def _is_oauth_credential(node_type: str) -> bool:
    """Check if a node type uses OAuth credentials (vs API key/token)."""
    node_class = NODE_REGISTRY.get(node_type)
    if not node_class:
        return False
    config_model = node_class.get_config_model()
    if not config_model or not hasattr(config_model, 'model_fields'):
        return False
    cred_field = config_model.model_fields.get('credentials')
    if not cred_field or not cred_field.annotation:
        return False
    # Check the schema for x-credential-type or x-oauth-provider
    try:
        schema = config_model.model_json_schema()
        cred_props = schema.get('properties', {}).get('credentials', {})
        if cred_props.get('x-credential-type') == 'oauth':
            return True
        if cred_props.get('x-oauth-provider'):
            return True
    except Exception:
        pass
    # Default: credential type name containing 'oauth' is OAuth
    cred_type = _extract_credential_type(cred_field.annotation)
    return bool(cred_type and 'oauth' in cred_type)


def _credential_schema_meta(node_type: str) -> Dict[str, Any]:
    """Actionable credential-connect metadata (x-credential-url,
    x-credential-instructions, x-oauth-provider) pulled from a node's schema —
    the pieces an agent needs to tell its user HOW to connect. Walks the
    credentials property + its anyOf/oneOf members ($refs inlined)."""
    node_class = NODE_REGISTRY.get(node_type)
    if not node_class:
        return {}
    config_model = node_class.get_config_model()
    if not config_model or not hasattr(config_model, "model_json_schema"):
        return {}
    try:
        schema = resolve_schema_refs(config_model.model_json_schema())
    except Exception:
        return {}
    cred = (schema.get("properties") or {}).get("credentials") or {}
    candidates = [cred, *cred.get("anyOf", []), *cred.get("oneOf", [])]
    meta: Dict[str, Any] = {}
    for c in candidates:
        if not isinstance(c, dict):
            continue
        for k in ("x-credential-url", "x-credential-instructions", "x-oauth-provider"):
            if c.get(k) and k not in meta:
                meta[k] = c[k]
    return meta


_JINJA_COMMENT_RE = re.compile(r"\{#.*?#\}", re.DOTALL)


def _node_guidance(node_type: str, section: str) -> Optional[str]:
    """Curated per-node Best-Practices guidance for the MCP surface (I2), with the
    raw Jinja `{# #}` comments the loader leaves in stripped out."""
    load = capability(NODE_GUIDANCE)
    if load is None:
        return None
    text = load(node_type, section)
    if not text:
        return None
    text = _JINJA_COMMENT_RE.sub("", text).strip()
    return text or None


# Widgets whose fields are computed live via load_field_value (not stored in
# config) — alongside the explicit ui:loadValue flag. Used to self-describe
# what load_value can fetch for a node.
_LOAD_VALUE_WIDGETS = frozenset({"webhook", "alarm_viewer", "file_browser"})


def _loadable_fields(node_type: str) -> List[Dict[str, Any]]:
    """Config fields a node computes live via load_field_value (webhook_url,
    active_alarms and file_browser) — flagged either ui:loadValue or
    a load-on-view widget. Lets load_value(field_name="") describe itself."""
    node_class = NODE_REGISTRY.get(node_type)
    if not node_class or not hasattr(node_class, "get_config_schema"):
        return []
    try:
        schema = resolve_schema_refs(node_class.get_config_schema())
    except Exception:
        return []
    cfg = (schema.get("properties") or {}).get("config") or schema
    out: List[Dict[str, Any]] = []
    for name, prop in (cfg.get("properties") or {}).items():
        if not isinstance(prop, dict):
            continue
        widget = prop.get("ui:widget")
        if prop.get("ui:loadValue") is True or widget in _LOAD_VALUE_WIDGETS:
            out.append({"field_name": name, "title": prop.get("title", name), "widget": widget})
    return out


def _op_to_dict(op) -> Dict[str, Any]:
    """Serialize an OperationInfo for the MCP surface, including the
    display_name/category ranking metadata the FE picker uses (I4)."""
    d: Dict[str, Any] = {"name": op.name, "description": op.description}
    if getattr(op, "display_name", None):
        d["display_name"] = op.display_name
    if getattr(op, "category", None):
        d["category"] = op.category
    return d


# Context variables set by ASGI middleware before forwarding to FastMCP
_user_id_var: ContextVar[str] = ContextVar("mcp_user_id")
_client_id_var: ContextVar[str] = ContextVar("mcp_client_id", default="")

from utils.capabilities import NODE_GUIDANCE, capability

# Singleton accessor for in-process tool execution (NoClickNode)
_mcp_server_instance: Optional['NoClickMCPServer'] = None

def set_mcp_server(server: 'NoClickMCPServer') -> None:
    """Register the NoClickMCPServer singleton for in-process access."""
    global _mcp_server_instance
    _mcp_server_instance = server

def get_mcp_server() -> Optional['NoClickMCPServer']:
    """Get the NoClickMCPServer singleton."""
    return _mcp_server_instance


# Import resources package (auto-discovers documentation topics from resources/*.py)
import resources  # noqa: F401


class NoClickMCPServer(DatabasePoolMixin):
    """
    MCP server with directly-defined workflow tools.

    Tools call the database directly and emit builder events to the user's
    connected frontend sessions for real-time canvas animations.
    """

    def __init__(self, sio):
        super().__init__()
        self.sio = sio

        self.mcp = FastMCP(
            name="noclick",
            version="1.0.0",
            website_url=NOCLICK_WEBSITE_URL,
            icons=noclick_icons(),
            instructions=(
                "NoClick workflow automation server. "
                "Use these tools to create, modify, and run workflows.\n\n"
                "Workflow building uses a progressive disclosure pattern with update_workflow:\n"
                "1. get_available_node_types() to discover node types\n"
                "2. update_workflow(xml: add nodes + edges, include_operations=true) → creates nodes, returns available operations per type\n"
                "3. update_workflow(xml: update_config setting operations, include_configs=true) → sets operations, returns config schemas + available credentials\n"
                "4. update_workflow(xml: set_credentials + update_config filling config fields) → sets credentials and completes configuration\n"
                "5. For dynamic dropdowns (e.g. pick spreadsheet): use field__fuzzy=\"query\" in update_config to auto-resolve, "
                "or load_options() tool to browse options\n\n"
                "Or in a single call if you already know the operations and config:\n"
                "  update_workflow(xml: add nodes with operation + full config + edges)\n\n"
                "Discover by intent: search_operations(query) finds the right node+operation for a goal "
                "(e.g. search_operations(\"post to slack\"), detail_level='name'|'description'|'full'); "
                "get_available_node_types() browses the full node catalog. get_node_operations/get_node_configs "
                "are manual fallbacks — prefer search_operations or the include_operations/include_configs flags.\n\n"
                "Verify & recover (use these — they're cheap and prevent broken runs):\n"
                "- validate_workflow(workflow_id) BEFORE run_workflow: catches invalid config, bad references, missing "
                "required fields, and unattached credentials with NO side effects (same checks update_workflow surfaces "
                "inline per touched node).\n"
                "- create_checkpoint(workflow_id, name) before a risky batch of edits; restore_checkpoint / list_checkpoints "
                "to roll back or review snapshots.\n"
                "- When a node needs a credential the user hasn't connected: connect_credential(node_type) returns a link to "
                "hand the user; search_credentials finds existing ones. update_workflow already surfaces credential_requests "
                "for provider-wired nodes.\n\n"
                "Inspect runs: list_executions(workflow_id) finds past/triggered/failed runs (filter by status/trigger_source/"
                "after/before); get_execution_status(execution_id) drills into one by id; get_node_output(workflow_id, node_ids"
                "[, execution_id]) reads latest or a specific past run; get_node_output_history / get_node_statuses / "
                "list_tool_calls give cross-run history, per-node status, and agent tool-call logs. get_health() self-tests "
                "the server (distinguish an infra failure from bad input).\n\n"
                "Live computed fields: some node info the config panel shows is computed live and NOT stored in config — "
                "a webhook's webhook_url, the alarm node's active_alarms list, and the filesystem node's "
                "file_browser listing. Fetch these with load_value(workflow_id, node_id, field_name); call "
                "load_value with field_name='' to list what a given node can load.\n\n"
                "Reference syntax — connect node outputs to inputs with the $('nodeId') accessor (ONE consistent form for plain refs AND transforms):\n"
                "  {{ $('nodeId').path.to.field }} — nodeId is the FULL node ID (e.g. automation-rss-1770385448353-1c922d)\n"
                "  {{ $('nodeId') }} — the entire node output\n"
                "  {{ $('nodeId').entries[0].title }} — array index access\n"
                "Use node IDs from alias_map or get_workflow response. Check reference_warnings in update_workflow responses.\n"
                "To TRANSFORM a value, just append JS to the accessor — no code node needed: {{ $('nodeId').field.split(',')[0] }}, "
                "{{ $('nodeId').items.map(x => x.name) }} (map produces a LIST, not a per-item loop — add an iteration node to run once per item), "
                "{{ $('nodeId').text.toUpperCase() }}. Also {{ $vars.x }} (variables), {{ $json.field }} (single direct upstream output), "
                "$if(cond,a,b), $ifEmpty(value,fallback).\n"
                "NEVER use the bare {{nodeId.field}} form for a transform — {{nodeId.field.toUpperCase()}} can't carry JS and is passed through as literal text.\n"
                "For array-typed config fields (see placeholder in schema), embed references in a JSON array: "
                '[["\u007b\u007bnodeId.items[].col1\u007d\u007d", "\u007b\u007bnodeId.items[].col2\u007d\u007d"]]\n\n'
                "Complete example — RSS feed → filter with JS → post to Slack:\n\n"
                "Step 1: Create workflow and add nodes with edges (discover operations):\n"
                '  create_workflow(name="RSS to Slack")\n'
                '  update_workflow(workflow_id, include_operations=true, xml:\n'
                '    <add_node type="automation-rss" name="rss" />\n'
                '    <add_node type="automation-serverless-function" name="filter" after="rss" />\n'
                '    <add_node type="automation-slack" name="slack" after="filter" />\n'
                "  ) → returns available operations per type + alias_map with real node IDs\n\n"
                "Step 2: Set operations (discover config schemas + credentials):\n"
                "  update_workflow(workflow_id, include_configs=true, xml:\n"
                '    <update_config id="rss" operation="parse_rss_atom_feed" />\n'
                '    <update_config id="filter" operation="run_javascript_function" />\n'
                '    <update_config id="slack" operation="send_message_to_channel" />\n'
                "  ) → returns config fields for each operation + available credentials\n\n"
                "Step 3: Fill configs + set credentials (use FULL node IDs from alias_map):\n"
                "  update_workflow(workflow_id, xml:\n"
                '    <update_config id="FULL_RSS_ID" feed_url="https://example.com/feed.xml" />\n'
                '    <update_config id="FULL_FILTER_ID" function_inputs=\'[{"name":"data","value":"{{FULL_RSS_ID}}"}]\' />\n'
                "    <update_config id=\"FULL_FILTER_ID\" field=\"function_body\">\n"
                "const items = inputs.data.entries.filter(e => e.title.includes('AI'));\n"
                "return { items, count: items.length };\n"
                "    </update_config>\n"
                '    <update_config id="FULL_SLACK_ID" channel="#general" text="Found {{FULL_FILTER_ID.result.count}} AI articles" />\n'
                '    <set_credentials id="FULL_SLACK_ID" slack_oauth="credential-uuid-from-step2" />\n'
                "  ) → returns affected_configs to verify changes\n\n"
                "Step 4: Test and run:\n"
                '  run_nodes(workflow_id, ["FULL_RSS_ID"], return_output=true) → test RSS node\n'
                "  run_workflow(workflow_id) → execute full pipeline\n\n"
                "Testing: When you build a deterministic dataflow pipeline, test it when possible before finishing — "
                "run read/fetch/transform nodes with run_nodes(workflow_id, [node_id], return_output=true) and confirm "
                "each step's output matches what the next node consumes, fixing and re-running if it doesn't. Do NOT "
                "auto-run nodes with un-approved real-world side effects (send message/email, external writes, payments, "
                "deletes) or nodes whose credentials aren't attached yet — leave those for the user to run. Agent and "
                "provider-wired tool nodes don't execute in the flow, so this applies to deterministic nodes only.\n\n"
                "Interface blocks: When building workflows, include interface nodes (UI components) so users can "
                "interact with the workflow via a visual interface. Available interface node types:\n"
                "  interface-form (user input forms), "
                "interface-file (universal file display — image, audio, video, PDF, or download), interface-file-upload (user file uploads), "
                "interface-dataframe (tabular data), "
                "interface-html-react (HTML or React/JSX component with @noclick/sdk — set operation='render_html_interface' or operation='render_jsx_react_interface')\n"
                "Add these as workflow nodes connected to relevant data sources. For example, add an interface-dataframe "
                "node after a data-fetching node to let users view results, or an interface-form node as input to collect "
                "user parameters before processing. Use update_interface to arrange blocks on the grid layout.\n\n"
                "Custom interface (interface-html-react): Two modes via operation field:\n"
                "  - operation='render_html_interface': Write raw HTML/JS with SDK access. npm packages are auto-imported — "
                "just use `import { X } from 'package-name'` in a `<script type=\"module\">` tag and the import map "
                "auto-resolves to esm.sh. No build step needed.\n"
                "  - operation='render_jsx_react_interface': Write React/JSX with Sucrase transpilation, Tailwind CSS, and auto npm resolution. "
                "Set jsx_source via update_config with field=\"jsx_source\" body syntax.\n"
                "Both modes include @noclick/sdk (nodes.getOutput/setConfig/getConfig, execution.runNodesAndGetOutput/runNodesInBackground, "
                "state.get/set/update/del, auth.requestCredential, resources.upload/getUrl, dataset.create/getRows/appendRows). "
                "Set fullscreen=\"true\" for full-viewport tab rendering. "
                "Use the 'build_custom_interface' prompt for the full SDK reference.\n\n"
                "Setting jsx_source via XML: JSX contains <, >, & which conflict with XML. Two approaches:\n"
                "  1. CDATA (recommended): <update_config id=\"x\" field=\"jsx_source\"><![CDATA[...raw JSX here...]]></update_config>\n"
                "     Raw JSX with <div>, &&, arrow functions etc. works directly. Only limitation: JSX cannot contain the literal sequence ]]>\n"
                "  2. Entity encoding: Replace & with &amp; then < with &lt; and > with &gt; in the body content.\n"
                "     For large JSX, write raw code to a temp file, encode with: sed 's/&/\\&amp;/g; s/</\\&lt;/g; s/>/\\&gt;/g'\n"
                "  patch_config works for small targeted JSX edits (e.g. changing a className) but reports an error if the anchor doesn't match. "
                "Prefer full jsx_source re-send for significant changes.\n\n"
                "SDK persistence notes:\n"
                "  - nodes.setConfig() persists to the backend database. For reading values back, use nodes.getConfig(nodeId).\n"
                "  - For reliable persistence in interface components, store data in known config fields (e.g. function_inputs "
                "on serverless-function nodes) rather than custom ad-hoc fields.\n"
                "  - state.get/set/update/del REQUIRES a 'state-manager' node in the workflow. Without one, these calls "
                "throw 'No state-manager node found'. Alternative: use nodes.setConfig/getConfig on existing nodes.\n"
                "  - nodes.getConfig returns node data as a flat object. Array fields like function_inputs may come back "
                "as a JSON string — always handle both: if (typeof val === 'string') val = JSON.parse(val)\n\n"
                "Setup flow pattern: For workflows that need one-time configuration (credentials, sheet creation, etc.), "
                "use a setup subgraph:\n"
                "  1. setup trigger → interface-form (collect credentials/settings) → set-variable (store as workflow vars)\n"
                "  2. → resource creation nodes (e.g. Google Sheets create) → set-variable (store created IDs)\n"
                "  3. Main pipeline references stored variables: {{vars.spreadsheet_id}}, {{vars.google_sheet_cred}}\n"
                "  set-variable assignments use: [{\"variable_name\": \"my_var\", \"value\": \"{{node.field}}\"}]\n"
                "  Variables are referenced as {{vars.variable_name}} in downstream nodes "
                "(or {{ $vars.variable_name }} inside a JS expression to transform them).\n\n"
            ),
        )

        self._register_widget_resources()
        self._register_docs()
        self._register_tools()
        self._patch_widget_metadata()
        self._http_app = self.mcp.http_app(stateless_http=True, json_response=True)
        self._lifespan_started = False
        self._lifespan_cm = None

        # Suppress expected ClosedResourceError noise from stateless HTTP + json_response mode.
        # Each request creates/destroys a transport session; the message_router's stream
        # closes before its async-for loop exits, which is harmless (response already sent).
        logging.getLogger("mcp.server.streamable_http").setLevel(logging.CRITICAL)

        logger.info("[MCP Server] Initialized with workflow tools")

    async def startup(self):
        """Start FastMCP's lifespan (session manager task group)."""
        if not self._lifespan_started:
            self._lifespan_cm = self._http_app.router.lifespan_context(self._http_app)
            await self._lifespan_cm.__aenter__()
            self._lifespan_started = True
            logger.info("[MCP Server] Lifespan started")

    async def shutdown(self):
        """Stop FastMCP's lifespan."""
        if self._lifespan_started and self._lifespan_cm:
            await self._lifespan_cm.__aexit__(None, None, None)
            self._lifespan_started = False
            logger.info("[MCP Server] Lifespan stopped")

    # =========================================================================
    # Integration helpers (called from api.py)
    # =========================================================================

    def get_oauth_router(self):
        """Return the FastAPI router for MCP OAuth endpoints (discovery, registration, authorization, token)."""
        from mcp_adapter.auth.endpoints import create_mcp_oauth_router
        return create_mcp_oauth_router()

    def create_asgi_middleware(self, fastapi_inner_app):
        """Wrap a FastAPI ASGI app to intercept /mcp requests with OAuth auth.

        Returns an ASGI app that authenticates Bearer tokens on /mcp and
        forwards to the FastMCP handler, passing all other requests through.
        """
        from starlette.requests import Request as StarletteRequest
        from starlette.responses import JSONResponse as StarletteJSON
        from mcp_adapter.auth.tokens import verify_mcp_token, extract_bearer_token
        import jwt as pyjwt

        server = self  # capture for closure

        def _add_cors(response):
            """Add CORS headers to a Starlette/FastAPI Response."""
            for k, v in _MCP_CORS_HEADERS.items():
                response.headers[k] = v

        async def asgi_app(scope, receive, send):
            if scope["type"] != "http":
                await fastapi_inner_app(scope, receive, send)
                return

            path = scope["path"]
            is_mcp_route = any(path.startswith(p) for p in _MCP_CORS_PREFIXES)

            # CORS preflight for all MCP-related routes
            if scope.get("method", "").upper() == "OPTIONS" and is_mcp_route:
                from starlette.responses import Response as StarletteResponse
                resp = StarletteResponse(status_code=204, headers=_MCP_CORS_HEADERS)
                await resp(scope, receive, send)
                return

            # /mcp: authenticate Bearer token, forward to MCP handler
            if path.rstrip("/") == "/mcp":
                request = StarletteRequest(scope, receive, send)
                token = extract_bearer_token(request.headers.get("Authorization"))
                from mcp_adapter.auth.endpoints import _get_base_url_from_request
                base_url = _get_base_url_from_request(request)
                resource_metadata_url = f"{base_url}/.well-known/oauth-protected-resource"
                if not token:
                    resp = StarletteJSON(
                        status_code=401,
                        content={"error": "Bearer token required"},
                        headers={**_MCP_CORS_HEADERS, "WWW-Authenticate": f'Bearer resource_metadata="{resource_metadata_url}", scope="mcp:tools"'},
                    )
                    await resp(scope, receive, send)
                    return
                try:
                    token_data = verify_mcp_token(token)
                except pyjwt.InvalidTokenError as e:
                    logger.warning(f"[MCP ASGI] Invalid token: {e}")
                    resp = StarletteJSON(
                        status_code=401,
                        content={"error": f"Invalid token: {e}"},
                        headers={**_MCP_CORS_HEADERS, "WWW-Authenticate": f'Bearer error="invalid_token", resource_metadata="{resource_metadata_url}", scope="mcp:tools"'},
                    )
                    await resp(scope, receive, send)
                    return

                response = await server.handle_request(request, token_data["sub"], token_data.get("client_id", ""))
                _add_cors(response)
                await response(scope, receive, send)
                return

            # Other MCP-related sub-routes: inject CORS via ASGI send wrapper
            if is_mcp_route:
                _cors_bytes = [(k.lower().encode(), v.encode()) for k, v in _MCP_CORS_HEADERS.items()]
                async def send_with_cors(message):
                    if message["type"] == "http.response.start":
                        message["headers"] = list(message.get("headers", [])) + _cors_bytes
                    await send(message)
                await fastapi_inner_app(scope, receive, send_with_cors)
                return

            await fastapi_inner_app(scope, receive, send)
        return asgi_app

    # =========================================================================
    # Request handling
    # =========================================================================

    async def handle_request(self, request, user_id: str, client_id: str = ""):
        """Forward a FastAPI request to the FastMCP ASGI app with user context."""
        from httpx import AsyncClient, ASGITransport
        from fastapi.responses import Response

        # Resolve client_id → human-readable client_name from OAuth registration
        client_name = ""
        if client_id:
            try:
                from mcp_adapter.auth.storage import MCPOAuthStorage
                stored = await MCPOAuthStorage().get_client(client_id)
                if stored:
                    client_name = stored.client_name
            except Exception:
                pass
        token = _user_id_var.set(user_id)
        client_token = _client_id_var.set(client_name or client_id)
        try:
            transport = ASGITransport(app=self._http_app)
            async with AsyncClient(transport=transport, base_url="http://mcp", follow_redirects=True) as client:
                body = await request.body()
                headers = dict(request.headers)
                headers.pop("host", None)

                response = await client.request(
                    method=request.method, url="/mcp/", content=body, headers=headers,
                )

                return Response(
                    content=response.content,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                )
        finally:
            _user_id_var.reset(token)
            _client_id_var.reset(client_token)

    # =========================================================================
    # Builder event emission
    # =========================================================================

    async def _emit_builder_event(
        self, user_id: str, workflow_id: str, event_type: str, data: dict
    ):
        """Emit a builder-style event to the user's connected frontends.

        Uses the configured event relay when available and otherwise delivers
        through local Socket.IO connections.
        """
        payload = {"workflow_id": workflow_id, "event_type": event_type, "data": data}

        from utils.event_relay import EVENT_RELAY_SECRET, broadcast_dict_to_user_safe
        if EVENT_RELAY_SECRET:
            try:
                relay_data = {"type": "mcp:builder_event", **payload}
                await broadcast_dict_to_user_safe(user_id, "mcp:builder_event", relay_data, workflow_id)
                return
            except Exception as e:
                logger.error(f"[MCP Server] Relay broadcast failed, falling back to local Socket.IO: {e}")

        # Fallback: local Socket.IO (also used when relay fails)
        from wss.receiver.receiver import get_receiver_instance
        receiver = get_receiver_instance()
        if not receiver:
            logger.warning(f"[MCP Builder] No receiver instance — dropping {event_type}")
            return
        for sid in receiver.get_frontend_sids_for_user(user_id):
            await self.sio.emit("mcp:builder_event", payload, to=sid)


    @staticmethod
    def _make_visual_result(data: dict) -> ToolResult:
        """Create a ToolResult with text JSON + structuredContent for the widget."""
        return ToolResult(
            content=[
                TextContent(type="text", text=json.dumps(data, indent=2, default=str)),
            ],
            structured_content=data,
        )

    # =========================================================================
    # DB helpers (reuse patterns from WorkflowMCPHandler)
    # =========================================================================

    async def _load_workflow(
        self, user_id: str, workflow_id: str, meta_out: Optional[Dict[str, Any]] = None,
    ) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Load workflow from database. Returns (workflow_data, error).

        Pass ``meta_out={}`` to also capture the row's ``updated_at`` (for the
        optimistic-concurrency guard in _save_workflow) without polluting the
        returned blob."""
        pool = await self.get_pool()
        if not pool:
            return None, "Database connection not available"
        try:
            async with pool.acquire() as conn:
                access = await check_resource_access(conn, user_id, "workflow", workflow_id)
                if not access.has_access:
                    return None, f"Workflow not found or access denied: {workflow_id}"

                row = await conn.fetchrow(
                    "SELECT workflow, updated_at FROM workflows WHERE id = $1",
                    uuid.UUID(workflow_id),
                )
                if not row:
                    return None, f"Workflow not found: {workflow_id}"

                data = row["workflow"] or {"nodes": [], "edges": []}
                data.setdefault("nodes", [])
                data.setdefault("edges", [])
                if meta_out is not None:
                    meta_out["updated_at"] = row["updated_at"]
                return data, None
        except Exception as e:
            logger.error(f"[MCP Server] Error loading workflow: {e}", exc_info=True)
            return None, str(e)

    async def _save_workflow(
        self, user_id: str, workflow_id: str, workflow_data: Dict[str, Any],
        expected_updated_at: Optional[Any] = None,
    ) -> Optional[str]:
        """Save workflow to database. Returns error string or None.

        S1: when ``expected_updated_at`` is provided, the write is compare-and-swap
        on ``updated_at`` — a concurrent canvas edit (YJS autosave) or another MCP
        call that changed the row since load loses with a 'conflict' error instead
        of silently clobbering the other writer's changes."""
        pool = await self.get_pool()
        if not pool:
            return "Database connection not available"
        try:
            async with pool.acquire() as conn:
                access = await check_resource_access(conn, user_id, "workflow", workflow_id)
                if not access.has_access:
                    return f"Workflow not found or access denied: {workflow_id}"
                if access.permission not in (Permission.EDIT, Permission.OWNER):
                    return "You don't have permission to edit this workflow"

                if expected_updated_at is not None:
                    result = await conn.execute(
                        "UPDATE workflows SET workflow = $1, updated_at = NOW() "
                        "WHERE id = $2 AND updated_at = $3",
                        workflow_data, uuid.UUID(workflow_id), expected_updated_at,
                    )
                    if result == "UPDATE 0":
                        exists = await conn.fetchval(
                            "SELECT 1 FROM workflows WHERE id = $1", uuid.UUID(workflow_id)
                        )
                        if exists:
                            return (
                                "conflict: the workflow was modified concurrently (a canvas edit "
                                "or another MCP call) since it was loaded — reload it and retry"
                            )
                        return f"Workflow not found: {workflow_id}"
                    return None

                result = await conn.execute(
                    "UPDATE workflows SET workflow = $1, updated_at = NOW() WHERE id = $2",
                    workflow_data,
                    uuid.UUID(workflow_id),
                )
                if result == "UPDATE 0":
                    return f"Workflow not found: {workflow_id}"
                return None
        except Exception as e:
            logger.error(f"[MCP Server] Error saving workflow: {e}", exc_info=True)
            return str(e)

    async def _process_workflow_content_ops(
        self,
        user_id: str,
        workflow_id: str,
        define_variable_ops: List[Dict[str, Any]],
        add_test_run_ops: List[Dict[str, Any]],
        nodes: List[Dict[str, Any]],
        edges: List[Dict[str, Any]],
        operations_log: List[dict],
        errors: List[dict],
        authored_out: List[Dict[str, str]],
    ) -> None:
        """define_variable / add_test_run for update_workflow: parse via the
        shared pure helpers, merge into workflows.settings (one top-level key
        write per family), emit settings_updated so an open canvas re-reads."""
        pool = await self.get_pool()
        if not pool:
            for op in (*define_variable_ops, *add_test_run_ops):
                msg = "Database connection not available"
                errors.append({"action": op["tag"], "error": msg})
                operations_log.append({"action": op["tag"], "success": False, "error": msg})
            return
        owner_id = await get_workflow_owner_id(pool, workflow_id)
        if not owner_id or str(owner_id) != str(user_id):
            for op in (*define_variable_ops, *add_test_run_ops):
                msg = "Only the workflow owner can change workflow settings"
                errors.append({"action": op["tag"], "error": msg})
                operations_log.append({"action": op["tag"], "success": False, "error": msg})
            return

        definitions: List[Dict[str, Any]] = []
        for op in define_variable_ops:
            definition, err = parse_define_variable(
                XmlOp(tag=op["tag"], attrs=op["attrs"], body=op.get("body")),
            )
            if err:
                errors.append({"action": "define_variable", "error": err})
                operations_log.append({"action": "define_variable", "success": False, "error": err})
            else:
                definitions.append(definition)

        parsed_runs: List[Dict[str, Any]] = []
        if add_test_run_ops:
            from nodes.agent.rehearsal_scenarios import (
                base_scenario_key_for_type,
                can_stage_trigger,
            )
            by_id = {n.get("id"): n for n in nodes}
            for op in add_test_run_ops:
                parsed, err = parse_add_test_run(
                    XmlOp(tag=op["tag"], attrs=op["attrs"], body=op.get("body")),
                )
                if not err:
                    ref = parsed["trigger_ref"]
                    node = by_id.get(ref) or next(
                        (n for n in nodes if n.get("type") == ref), None,
                    )
                    if not node:
                        err = f"no node '{ref}' in this workflow"
                    elif not can_stage_trigger(node, nodes, edges):
                        err = (
                            f"'{ref}' is not rehearsable: it must be a trigger "
                            "(not a provider-wired tool) with an agent downstream"
                        )
                if err:
                    errors.append({"action": "add_test_run", "error": err})
                    operations_log.append({"action": "add_test_run", "success": False, "error": err})
                    continue
                node_type = node.get("type") or ""
                parsed_runs.append({
                    **parsed,
                    "node_type": node_type,
                    "base_key": base_scenario_key_for_type(node_type),
                })

        if not definitions and not parsed_runs:
            return
        try:
            from repositories.workflow import WorkflowRepo
            repo = WorkflowRepo(pool)
            async with pool.acquire() as conn:
                row = await repo.get_workflow_data_and_settings(conn, uuid.UUID(workflow_id))
                settings = row["settings"] if row else None
                if isinstance(settings, str):
                    settings = json.loads(settings)
                settings = settings if isinstance(settings, dict) else {}
                settings_patch: Dict[str, Any] = {}
                if definitions:
                    settings_patch["variable_definitions"] = upsert_variable_definitions(
                        settings.get("variable_definitions"), definitions,
                    )
                authoring = settings.get("rehearsal_authoring")
                authored: List[Dict[str, str]] = []
                for run in parsed_runs:
                    authoring, slug = append_rehearsal_run(
                        authoring, run["node_type"], run["name"], run["lead"], run["base_key"],
                    )
                    authored.append({
                        "node_type": run["node_type"], "name": run["name"], "slug": slug,
                    })
                if parsed_runs:
                    settings_patch["rehearsal_authoring"] = authoring
                await repo.update_workflow_dynamic(
                    conn, uuid.UUID(workflow_id), settings=settings_patch,
                )
            authored_out.extend(authored)
            for d in definitions:
                operations_log.append({
                    "action": "define_variable", "success": True, "name": d["name"],
                    "note": f"bind with {{{{vars.{d['name']}}}}} as a config field's whole value",
                })
            for a in authored:
                operations_log.append({
                    "action": "add_test_run", "success": True,
                    "name": a["name"], "slug": a["slug"], "trigger_type": a["node_type"],
                })
            await self._emit_builder_event(user_id, workflow_id, "settings_updated", {})
        except Exception as e:
            logger.error(f"[MCP Server] workflow content ops failed: {e}", exc_info=True)
            for d in definitions:
                errors.append({"action": "define_variable", "error": str(e)})
                operations_log.append({"action": "define_variable", "success": False, "error": str(e)})
            for run in parsed_runs:
                errors.append({"action": "add_test_run", "error": str(e)})
                operations_log.append({"action": "add_test_run", "success": False, "error": str(e)})

    def _create_node_dict(
        self, node_type: str, config: Optional[Dict[str, Any]], position: Dict[str, float],
        label: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a node structure for the workflow."""
        node_id = f"{node_type}-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}"
        node_config = dict(config) if config else {}
        if label:
            node_config["label"] = label
        return {
            "id": node_id,
            "type": node_type,
            "position": position,
            "config": node_config,
        }

    def _find_node_position(
        self, nodes: List[Dict[str, Any]], prev_node_id: Optional[str]
    ) -> Dict[str, float]:
        """Calculate position for a new node."""
        if prev_node_id:
            for node in nodes:
                if node.get("id") == prev_node_id:
                    return {
                        "x": node.get("position", {}).get("x", 0) + 300,
                        "y": node.get("position", {}).get("y", 0),
                    }
        if nodes:
            last = nodes[-1]
            return {
                "x": last.get("position", {}).get("x", 0) + 300,
                "y": last.get("position", {}).get("y", 150),
            }
        return {"x": 250, "y": 150}

    @staticmethod
    def _score_frontend_response(data: dict) -> int:
        """Score a frontend response to pick the best one among multiple tabs/worktrees.

        Higher score = more likely to be the tab the user is actively working in.
        """
        score = 0
        if not isinstance(data, dict):
            return score
        # "Loading..." means the workflow hasn't finished loading — this tab
        # is stale or mid-navigation, so cap its score as a last-resort fallback
        if data.get('workflowName') == 'Loading...':
            return 1
        if data.get('isTabVisible'):
            score += 100
        if data.get('workflowId'):
            score += 50
        if isinstance(data.get('nodes'), list) and len(data['nodes']) > 0:
            score += 5
        # Prefer more recently interacted tab
        last_interaction = data.get('lastInteractionAt', 0)
        if last_interaction:
            # Normalize: interactions within the last 60s get up to +10
            age_s = max(0, (time.time() * 1000 - last_interaction) / 1000)
            score += max(0, int(10 * (1 - age_s / 60)))
        return score

    async def _request_frontend(
        self, request_type: str, params: dict, *, timeout: float = 10,
        is_valid=None, collect_ms: int = 0, workflow_id: str | None = None,
    ) -> dict:
        """Send a request to the user's frontend and wait for a response.

        Uses the configured event relay (works cross-container) when configured,
        falls back to local Socket.IO SIDs for local development.

        Args:
            workflow_id: When set, only the frontend with this workflow open will respond.
            collect_ms: When > 0, collect all responses within this window and
                        return the highest-scored one (for multi-tab disambiguation).
        """
        user_id = _user_id_var.get()

        # Inject workflow_id so the frontend can filter by active workflow
        if workflow_id:
            params = {**params, "_workflow_id": workflow_id}

        # Use event relay if configured (production — works cross-container)
        from utils.event_relay import request_from_frontend, EVENT_RELAY_SECRET
        if EVENT_RELAY_SECRET:
            result = await request_from_frontend(
                user_id, request_type, params, timeout, collect_ms=collect_ms,
            )

            # Multi-response mode: pick the best response
            if "responses" in result:
                responses = result["responses"]
                valid = [r.get("data") for r in responses
                         if isinstance(r, dict) and r.get("data") is not None and not r.get("error")]
                if not valid:
                    return {"error": "No valid frontend responses"}
                return max(valid, key=self._score_frontend_response)

            # Single-response mode (legacy / collect_ms=0)
            if "data" in result and result.get("error") is None:
                return result["data"]
            return result

        # Fallback: local Socket.IO (local development, same container)
        from wss.receiver.receiver import get_receiver_instance
        from wss.sender.events import WorkflowMCPRequestEvent
        from wss.sender import send_event as ws_send_event
        from wss.receiver.event_routing import Handler

        receiver = get_receiver_instance()
        if not receiver:
            return {"error": "Backend receiver not available"}

        frontend_sids = receiver.get_frontend_sids_for_user(user_id)
        if not frontend_sids:
            return {"error": "No browser session found. Please open NoClick in your browser."}

        request_id = f"mcp_{uuid.uuid4()}"
        future: asyncio.Future = asyncio.get_event_loop().create_future()

        mcp_handler = receiver.handler_instances.get(Handler.WORKFLOW_MCP)
        if mcp_handler and hasattr(mcp_handler, '_pending_requests'):
            mcp_handler._pending_requests[request_id] = {
                'future': future,
                'is_valid': is_valid or (lambda r: True),
                'fallback_response': None,
                'response_count': 0,
                'expected_count': len(frontend_sids),
            }

        try:
            for sid in frontend_sids:
                await ws_send_event(self.sio, sid, WorkflowMCPRequestEvent(
                    request_id=request_id,
                    request_type=request_type,
                    params=params,
                ))
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            return {"error": "Frontend did not respond in time. Is the workflow editor open?"}
        finally:
            if mcp_handler and hasattr(mcp_handler, '_pending_requests'):
                mcp_handler._pending_requests.pop(request_id, None)


    @staticmethod
    def _deep_merge_config(base: dict, updates: dict) -> dict:
        """Deep merge updates into base config dict.

        Delegates to the shared ``deep_merge_config`` from workflow_ops.
        """
        return deep_merge_config(base, updates)

    async def _resolve_node_output(self, node: Dict[str, Any], workflow_id: str, node_id: str, pool) -> tuple:
        """Resolve node output with priority: mockedOutput > node_outputs table > JSONB.

        Returns (output, is_mocked) tuple. Reads from the flat ``node["config"]`` blob.
        """
        config = node.get("config", {}) or {}
        output = config.get("mockedOutput")
        is_mocked = output is not None
        if not is_mocked:
            if pool:
                try:
                    from utils.node_outputs import latest_output
                    table_output = await latest_output(pool, workflow_id, node_id)
                    if table_output is not None:
                        output = table_output
                except Exception as e:
                    logger.debug(f"[MCP] Failed to read from node_outputs table for {node_id}: {e}")
            if output is None:
                output = config.get("output")
        return output, is_mocked

    async def _get_credential_info_for_node(
        self, node_type: str, user_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get credential requirements and user's matching credentials for a node type.

        The returned dict carries the actionable connect metadata (x-credential-url,
        x-credential-instructions, x-oauth-provider) so a dead-end (no `available`)
        ships a next step (CR3)."""
        cred_type = _get_credential_type_for_node(node_type)
        if not cred_type:
            return None

        base = {
            "credential_type": cred_type,
            "is_oauth": _is_oauth_credential(node_type),
            **_credential_schema_meta(node_type),
        }

        pool = await self.get_pool()
        if not pool:
            return {**base, "available": []}

        try:
            async with pool.acquire() as conn:
                from wss.handlers.workflow_handler import get_user_org_context
                org_id = await get_user_org_context(conn, user_id)

                rows = await conn.fetch("""
                    SELECT DISTINCT ON (c.id) c.id, c.name, c.metadata
                    FROM credentials c
                    LEFT JOIN resource_shares us
                        ON us.resource_type = 'credential' AND us.resource_id = c.id
                        AND us.target_type = 'user' AND us.target_user_id = $1
                    LEFT JOIN resource_shares os
                        ON os.resource_type = 'credential' AND os.resource_id = c.id
                        AND os.target_type = 'organization' AND os.target_org_id = $3
                    WHERE c.credential_type = $2
                      AND (c.owner_id = $1 OR us.id IS NOT NULL
                           OR ($3::uuid IS NOT NULL AND os.id IS NOT NULL))
                    ORDER BY c.id, c.created_at DESC
                    LIMIT 10
                """, user_id, cred_type, org_id)

                return {
                    **base,
                    "available": [
                        {"id": str(r["id"]), "name": r["name"], "metadata": r["metadata"] or {}}
                        for r in rows
                    ],
                }
        except Exception as e:
            logger.warning(f"[MCP Server] Error fetching credentials for {node_type}: {e}")
            return {**base, "available": []}

    async def _auto_attach_agent_credential(
        self, user_id: str, config: Dict[str, Any], hint: Dict[str, Any],
    ) -> Optional[Dict[str, str]]:
        """Attach the sole credential satisfying an agent's harness requirement
        — parity with the builder's post-model-flip autoselect. A sole
        credential of the PRIMARY type wins outright; otherwise a sole
        credential across all accepted types. Returns ``{credential_type, id}``
        when attached, None when there's a real decision to make.
        """
        pool = await self.get_pool()
        if not pool:
            return None
        primary = hint.get("credential_type") or ""
        accepted = [t for t in hint.get("accepted_types") or [] if t] or [primary]
        try:
            async with pool.acquire() as conn:
                from wss.handlers.workflow_handler import get_user_org_context
                org_id = await get_user_org_context(conn, user_id)
                rows = await conn.fetch("""
                    SELECT DISTINCT ON (c.id) c.id, c.credential_type
                    FROM credentials c
                    LEFT JOIN resource_shares us
                        ON us.resource_type = 'credential' AND us.resource_id = c.id
                        AND us.target_type = 'user' AND us.target_user_id = $1
                    LEFT JOIN resource_shares os
                        ON os.resource_type = 'credential' AND os.resource_id = c.id
                        AND os.target_type = 'organization' AND os.target_org_id = $3
                    WHERE c.credential_type = ANY($2::text[])
                      AND (c.owner_id = $1 OR us.id IS NOT NULL
                           OR ($3::uuid IS NOT NULL AND os.id IS NOT NULL))
                    LIMIT 20
                """, user_id, accepted, org_id)
        except Exception as e:
            logger.warning(f"[MCP Server] Agent credential auto-attach lookup failed: {e}")
            return None
        primaries = [r for r in rows if r["credential_type"] == primary]
        pick = None
        if len(primaries) == 1:
            pick = primaries[0]
        elif len(rows) == 1:
            pick = rows[0]
        if pick is None:
            return None
        merge_credentials(config, {pick["credential_type"]: str(pick["id"])})
        return {"credential_type": pick["credential_type"], "id": str(pick["id"])}

    async def _decrypt_credential_for_node(
        self, node: Dict[str, Any], user_id: str
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Get (decrypted credential data, credential_id) for a node using its
        credentialIds config. credential_id is returned so callers can pass it
        to freshen_credential (OAuth token refresh) at load."""
        config = node.get("config", {}) or {}
        cred_ids = config.get("credentialIds", {})
        if not cred_ids:
            return None, None
        # Use the first credential ID found
        cred_id = next(iter(cred_ids.values()), None)
        if not cred_id:
            return None, None
        pool = await self.get_pool()
        return await get_credential(cred_id, user_id, pool=pool), cred_id

    async def _load_dynamic_options_for_field(
        self,
        node_type: str,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        user_id: Optional[str] = None,
        credential_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Load dynamic dropdown options for a field on a node type."""
        node_class = NODE_REGISTRY.get(node_type)
        if not node_class:
            return {"error": f"Unknown node type: {node_type}"}
        if not hasattr(node_class, 'load_field_options'):
            return {"error": f"Node type {node_type} does not support dynamic options"}

        # Inject user_id into context for credential-less nodes (e.g., resource picker)
        ctx = dict(context or {})
        if user_id:
            ctx['_user_id'] = user_id

        # Refresh expiring OAuth tokens at load so option queries never hit the
        # provider with a stale token — the MCP twin of the workflow handler's
        # freshen (no-op for nodes that don't override freshen_credential).
        if credential_id and credential_data:
            from nodes.core.oauth_audit import caller_path_scope
            pool = await self.get_pool()
            with caller_path_scope("mcp"):
                credential_data = await node_class.freshen_credential(
                    credential_data, pool=pool, user_id=user_id, credential_id=credential_id
                )

        result = await node_class.load_field_options(
            field_name=field_name,
            credential_data=credential_data,
            context=ctx,
            page_token=page_token or None,
        )

        # Normalize: some nodes return list, some return dict with {options, next_page_token}
        if isinstance(result, list):
            return {"options": result, "next_page_token": None}
        return result

    # =========================================================================
    # Batch update_workflow processor
    # =========================================================================

    async def _process_update_workflow(
        self,
        workflow_id: str,
        updates_xml: str,
        include_operations: bool,
        include_configs: bool,
        include_dynamic_options: bool = False,
        dynamic_options_limit: int = 10,
    ) -> dict:
        """Process batch XML mutations with progressive disclosure flags."""
        user_id = _user_id_var.get()

        # Parse XML into operations
        parsed_ops = _parse_xml_operations(updates_xml)
        if not parsed_ops:
            return {"error": "No valid operations found in XML. Check syntax."}

        # Categorize operations by tag
        add_node_ops = [op for op in parsed_ops if op["tag"] == "add_node"]
        add_edge_ops = [op for op in parsed_ops if op["tag"] == "add_edge"]
        update_config_ops = [op for op in parsed_ops if op["tag"] == "update_config"]
        set_cred_ops = [op for op in parsed_ops if op["tag"] == "set_credentials"]
        disable_node_ops = [op for op in parsed_ops if op["tag"] == "disable_node"]
        enable_node_ops = [op for op in parsed_ops if op["tag"] == "enable_node"]
        mock_node_ops = [op for op in parsed_ops if op["tag"] == "mock_node"]
        unmock_node_ops = [op for op in parsed_ops if op["tag"] == "unmock_node"]
        update_settings_ops = [op for op in parsed_ops if op["tag"] == "update_settings"]
        patch_config_ops = [op for op in parsed_ops if op["tag"] == "patch_config"]
        remove_edge_ops = [op for op in parsed_ops if op["tag"] == "remove_edge"]
        remove_node_ops = [op for op in parsed_ops if op["tag"] == "remove_node"]
        sticky_note_ops = [op for op in parsed_ops if op["tag"] == "add_sticky_note"]
        define_variable_ops = [op for op in parsed_ops if op["tag"] == "define_variable"]
        add_test_run_ops = [op for op in parsed_ops if op["tag"] == "add_test_run"]
        run_test_ops = [op for op in parsed_ops if op["tag"] == "run_test"]

        # Load workflow once (capture updated_at baseline for the S1 CAS save).
        load_meta: Dict[str, Any] = {}
        data, err = await self._load_workflow(user_id, workflow_id, meta_out=load_meta)
        if err:
            return {"error": err}

        nodes = data["nodes"]
        edges = data["edges"]
        alias_map: Dict[str, str] = {}  # name → real node_id
        operations_log: List[dict] = []
        errors: List[dict] = []
        any_succeeded = False
        # Webhook lifecycle hooks collected during processing and run AFTER
        # _save_workflow: the reconciler reads the SAVED graph as desired
        # truth, so a hook fired mid-processing would converge against the
        # stale pre-save blob and no-op. Each entry is an argless coroutine
        # factory.
        deferred_webhook_hooks: List[Any] = []
        # Credential ids placed via set_credentials this call — authorized for
        # run-as-owner resolution after the save, IF the actor is the workflow owner.
        set_cred_ids: set = set()
        # Node ids that gained a credential this call — webhook-provisioning
        # candidates (provider registration needs the credential).
        cred_set_node_ids: set = set()

        # Track which node types were added (for include_operations)
        added_node_types: set = set()
        # Track nodes where operation was specified (for include_configs)
        nodes_with_operation: List[Dict[str, str]] = []  # [{alias, node_id, node_type, operation}]
        # Track affected node IDs for returning configs in response
        affected_node_ids: set = set()
        # Per-node config validation verdicts (config_valid/errors/missing_required/
        # resolutions/auth hint) surfaced in affected_configs and the op log.
        node_config_verdicts: Dict[str, dict] = {}
        # (op_log_index, node_id) of add_node ops whose inline config needs a
        # reference-validation post-pass once all nodes/edges exist.
        pending_ref_checks: List[tuple] = []
        # <ask>/<input> ops surfaced back to the caller (CR4) rather than dropped.
        input_requests: List[dict] = []
        # Per-call cache for credential autoselection lookups, keyed by node type
        cred_autoselect_cache: Dict[str, Optional[Dict[str, Any]]] = {}

        def _resolve_id(ref: str) -> str:
            """Resolve an alias or pass through a real node id."""
            return alias_map.get(ref, ref)

        # P1: fail loudly on tags that PARSED but aren't update_workflow ops
        # (agentic-loop tags like <done>/<ask>/<query_*>, or the shared-DSL
        # canonical <field>/<patch>) instead of silently dropping them and
        # still returning success:true.
        for op in parsed_ops:
            tag = op["tag"]
            if tag in _UPDATE_WORKFLOW_TAGS:
                continue
            # CR4: <ask>/<input> aren't graph mutations — surface them back to the
            # caller as input_requests rather than dropping or erroring them.
            if tag in ("ask", "input"):
                input_requests.append({"type": tag, **op.get("attrs", {})})
                continue
            msg = (
                f"'{tag}' is not a valid update_workflow operation. "
                f"Use update_config/patch_config for config, or the dedicated tool for {tag}."
            )
            errors.append({"action": tag, "error": msg})
            operations_log.append({"action": tag, "success": False, "error": msg})

        # --- Process add_node ops ---
        for op in add_node_ops:
            attrs = op["attrs"]
            node_type = attrs.get("type", "")
            name = attrs.get("name", "")
            after = attrs.get("after")
            operation = attrs.get("operation")
            label = attrs.get("label")

            try:
                if not node_type:
                    raise ValueError("add_node requires type attribute")
                if not name:
                    raise ValueError("add_node requires name attribute")
                if node_type not in NODE_REGISTRY:
                    raise ValueError(f"Unknown node type: {node_type}")

                # Build config from remaining attrs
                reserved = {"type", "name", "after", "operation", "label"}
                config = {}
                for k, v in attrs.items():
                    if k not in reserved:
                        config[k] = _coerce_field_value(node_type, operation, k, v)
                if operation:
                    # Detect discriminator field name for this node type
                    disc_field = get_discriminator_field(node_type)
                    config[disc_field] = operation

                # Parse after="node:handle" syntax for multi-output nodes
                after_handle = None
                if after and ":" in after:
                    after_parts = after.rsplit(":", 1)
                    after = after_parts[0]
                    after_handle = after_parts[1]
                after_id = _resolve_id(after) if after else None
                position = self._find_node_position(nodes, after_id)
                node = self._create_node_dict(node_type, config or None, position, label=label)
                node_id = node["id"]
                alias_map[name] = node_id

                # Canonicalize + validate the inline config (single-call add form)
                # before it's emitted/persisted, so the saved config is canonical.
                # Every inline key counts as changed (no prior config exists), so
                # wrong-typed values are dropped with a rejected_values verdict.
                add_config_verdict = self._postprocess_config(
                    node_type, operation, node["config"],
                    changed_keys=set(node["config"].keys()),
                    prior_config={},
                )

                # Emit node_start (node appears, pulse animation — no operation yet)
                # If operation is already set, emit node_processing_start instead
                node_event_data: Dict[str, Any] = {"id": node_id, "type": node_type, "position": position}
                if label:
                    node_event_data["label"] = label
                if operation:
                    await self._emit_builder_event(user_id, workflow_id, "node_start", {
                        "node": node_event_data
                    })
                    await self._emit_builder_event(user_id, workflow_id, "node_processing_start", {
                        "nodeId": node_id,
                    })
                else:
                    await self._emit_builder_event(user_id, workflow_id, "node_start", {
                        "node": node_event_data
                    })

                nodes.append(node)
                added_node_types.add(node_type)

                # Auto-attach a credential when the user has exactly one of the
                # matching type — no decision to make. A later <set_credentials>
                # for this node overrides it (processed after add_node).
                if not node_has_credential(node["config"]):
                    if node_type not in cred_autoselect_cache:
                        cred_autoselect_cache[node_type] = await self._get_credential_info_for_node(
                            node_type, user_id
                        )
                    cred_info = cred_autoselect_cache[node_type]
                    if cred_info and len(cred_info["available"]) == 1:
                        merge_credentials(node["config"], {
                            cred_info["credential_type"]: cred_info["available"][0]["id"],
                        })
                        set_cred_ids.add(cred_info["available"][0]["id"])
                        await self._emit_builder_event(user_id, workflow_id, "node_updated", {
                            "nodeId": node_id, "config": node["config"],
                        })
                        affected_node_ids.add(node_id)

                # Track if operation was specified
                if operation:
                    nodes_with_operation.append({
                        "alias": name, "node_id": node_id,
                        "node_type": node_type, "operation": operation,
                    })

                # drafter: if a same-batch tools edge will source this node (making it
                # an agent tool provider), skip the after= dataflow auto-edge —
                # providers take no dataflow and autolayout already places them.
                will_be_provider = any(
                    e_op["attrs"].get("from") in (name, node_id)
                    and (e_op["attrs"].get("type") == "tools" or e_op["attrs"].get("handle") == "top")
                    for e_op in add_edge_ops
                )

                # Auto-edge if after is specified (supports after="node:handle" for multi-output nodes)
                if after_id and not will_be_provider and any(n.get("id") == after_id for n in nodes):
                    edge_id = f"{after_id}-{node_id}" + (f"-{after_handle}" if after_handle else "")
                    edge = {
                        "id": edge_id,
                        "source": after_id,
                        "target": node_id,
                        "type": "animated",
                    }
                    if after_handle:
                        edge["sourceHandle"] = after_handle
                    edges.append(edge)
                    await self._emit_builder_event(user_id, workflow_id, "edge_added", {
                        "edge": {
                            "id": edge_id, "source": after_id, "target": node_id,
                            **({"sourceHandle": after_handle} if after_handle else {}),
                        }
                    })

                operations_log.append({
                    "action": "add_node", "name": name,
                    "node_id": node_id, "success": True,
                })
                any_succeeded = True

                if add_config_verdict:
                    operations_log[-1].update(add_config_verdict)
                    node_config_verdicts[node_id] = add_config_verdict
                # C5: reference-validate the inline config in a post-pass, once
                # all nodes/edges exist (so forward references resolve).
                pending_ref_checks.append((len(operations_log) - 1, node_id))

            except Exception as e:
                errors.append({"action": "add_node", "name": name, "error": str(e)})
                operations_log.append({
                    "action": "add_node", "name": name, "success": False, "error": str(e),
                })

        # --- Process add_edge ops ---
        for op in add_edge_ops:
            attrs = op["attrs"]
            source_ref = attrs.get("from", "")
            target_ref = attrs.get("to", "")
            handle = attrs.get("handle")

            try:
                source_id = _resolve_id(source_ref)
                target_id = _resolve_id(target_ref)

                nodes_by_id = {n.get("id"): n for n in nodes}
                if source_id not in nodes_by_id:
                    raise ValueError(f"Source node not found: {source_ref}")
                if target_id not in nodes_by_id:
                    raise ValueError(f"Target node not found: {target_ref}")

                # Reject edges involving connectionless (SDK-based) node types
                edge_err = validate_edge(nodes_by_id[source_id].get("type", ""), nodes_by_id[target_id].get("type", ""))
                if edge_err:
                    raise ValueError(edge_err)

                # Tool-provider edges (type="tools" or handle="top", plus
                # auto-normalized tool/mcp-server/alarm/filesystem → agent):
                # top→bottom handles, source ops become agent tools.
                target_handle = None
                tools_handles, tools_err = resolve_tools_edge(
                    nodes_by_id[source_id].get("type", ""),
                    nodes_by_id[target_id].get("type", ""),
                    edge_type=attrs.get("type"), source_handle=handle,
                )
                if tools_err:
                    raise ValueError(tools_err)
                if tools_handles:
                    handle, target_handle = tools_handles

                # Provider mode and dataflow are mutually exclusive on the
                # source node (mirrors FlowCanvas.isValidConnection).
                conflict = provider_dataflow_conflict(
                    source_id, edges, new_edge_is_tools=tools_handles is not None,
                )
                if conflict:
                    raise ValueError(conflict)
                # Either-or: a trigger-operation node can't be a provider.
                if tools_handles:
                    trig_conflict = trigger_provider_conflict(
                        nodes_by_id[source_id].get("type", ""),
                        (nodes_by_id[source_id].get("config") or {}).get("operation"),
                    )
                    if trig_conflict:
                        raise ValueError(trig_conflict)
                    # Either-or: an MCP node hosts wired tools XOR proxies an
                    # external server.
                    host_conflict = mcp_hosting_conflict(
                        nodes_by_id[target_id].get("type", ""),
                        nodes_by_id[target_id].get("config"),
                    )
                    if host_conflict:
                        raise ValueError(host_conflict)

                # drafter: validate a plain-dataflow handle against the source node's
                # declared output handles (mirrors the builder). Skipped for tools
                # edges, which legitimately carry handle="top"/target "bottom".
                if tools_handles is None and handle:
                    source_type = nodes_by_id[source_id].get("type", "")
                    source_class = NODE_REGISTRY.get(source_type)
                    source_handles = source_class.get_output_handles() if source_class else None
                    valid_handles = {h["id"] for h in (source_handles or []) if isinstance(h, dict) and "id" in h}
                    if not valid_handles:
                        raise ValueError(
                            f'handle="{handle}" but source \'{source_ref}\' ({source_type}) is a '
                            f"single-output node with no named handles — remove handle= and encode "
                            f"any branching inside the source node's config."
                        )
                    if handle not in valid_handles:
                        valid_list = ", ".join(f'"{h}"' for h in sorted(valid_handles))
                        raise ValueError(
                            f'handle="{handle}" but source \'{source_ref}\' ({source_type}) only '
                            f"supports handles: {valid_list}."
                        )

                # Check for duplicate
                if any(e.get("source") == source_id and e.get("target") == target_id
                       and e.get("sourceHandle") == handle for e in edges):
                    raise ValueError(f"Edge already exists from {source_ref} to {target_ref}")

                edge_id = f"{source_id}-{target_id}" + (f"-{handle}" if handle else "")
                edge = {
                    "id": edge_id,
                    "source": source_id,
                    "target": target_id,
                    "type": "animated",
                }
                if handle:
                    edge["sourceHandle"] = handle
                if target_handle:
                    edge["targetHandle"] = target_handle
                edges.append(edge)

                await self._emit_builder_event(user_id, workflow_id, "edge_added", {
                    "edge": {
                        "id": edge_id, "source": source_id, "target": target_id,
                        **({"sourceHandle": handle} if handle else {}),
                        **({"targetHandle": target_handle} if target_handle else {}),
                    }
                })

                operations_log.append({
                    "action": "add_edge", "edge_id": edge_id, "success": True,
                })
                any_succeeded = True

            except Exception as e:
                errors.append({"action": "add_edge", "from": source_ref, "to": target_ref, "error": str(e)})
                operations_log.append({
                    "action": "add_edge", "from": source_ref, "to": target_ref,
                    "success": False, "error": str(e),
                })

        # --- Process add_sticky_note ops ---
        for op in sticky_note_ops:
            attrs = op["attrs"]
            body = op.get("body", "")
            name = attrs.get("name", "")

            try:
                content = body or attrs.get("content", "")
                color = int(attrs.get("color", "8"))

                # Build sticky config with positioning anchors
                sticky_config: Dict[str, Any] = {"content": content, "color": color}

                # Cover mode: after + before
                if "after" in attrs and "before" in attrs:
                    sticky_config["_anchor_after"] = _resolve_id(attrs["after"])
                    sticky_config["_anchor_before"] = _resolve_id(attrs["before"])
                # Near mode: near + direction
                elif "near" in attrs:
                    near_ids = [_resolve_id(n.strip()) for n in attrs["near"].split(",")]
                    sticky_config["_anchor_near"] = near_ids
                    sticky_config["_anchor_direction"] = attrs.get("direction", "above")

                # Width/height overrides
                if "width" in attrs:
                    sticky_config["_anchor_width"] = int(attrs["width"])
                if "height" in attrs:
                    sticky_config["_anchor_height"] = int(attrs["height"])

                # Compute position from current node positions
                pos_result = resolve_sticky_note_position(nodes, edges, sticky_config)
                node = create_sticky_note_dict(
                    sticky_config, pos_result["position"],
                    pos_result["width"], pos_result["height"],
                )
                node_id = node["id"]

                if name:
                    alias_map[name] = node_id
                nodes.append(node)

                # Emit builder event for frontend
                await self._emit_builder_event(user_id, workflow_id, "node_start", {
                    "node": {
                        "id": node_id, "type": "stickyNote",
                        "position": pos_result["position"],
                        "content": content, "color": color,
                        "width": pos_result["width"],
                        "height": pos_result["height"],
                    }
                })

                operations_log.append({
                    "action": "add_sticky_note", "name": name,
                    "node_id": node_id, "success": True,
                })
                any_succeeded = True

            except Exception as e:
                errors.append({"action": "add_sticky_note", "name": name, "error": str(e)})
                operations_log.append({
                    "action": "add_sticky_note", "name": name,
                    "success": False, "error": str(e),
                })

        # --- Process update_config ops (with dynamic suffix detection) ---
        # Queued dynamic operations: list of {node_id, node_type, alias, field, mode, query, limit}
        dynamic_queue: List[Dict[str, Any]] = []

        for op in update_config_ops:
            attrs = op["attrs"]
            id_ref = attrs.get("id", "")

            try:
                node_id = _resolve_id(id_ref)
                target = None
                for n in nodes:
                    if n.get("id") == node_id:
                        target = n
                        break
                if not target:
                    raise ValueError(f"Node not found: {id_ref}")

                # Separate regular config attrs from dynamic suffixes
                config_updates = {}
                search_limits: Dict[str, int] = {}  # field -> limit from __search_limit
                operation_fuzzy: Optional[str] = None  # fuzzy query string

                target_type = target.get("type", "")
                target_operation = self._get_current_operation(target)

                # Body syntax: <update_config id="x" field="y">large value</update_config>
                # Body content is kept as-is — it's intended for long string fields
                # (jsx_source, function_body, system_prompt) where coercion would
                # be wrong if the content happens to look like JSON.
                field_attr = attrs.get("field")
                body_content = op.get("body")
                if field_attr and body_content is not None:
                    config_updates[field_attr] = body_content

                for k, v in attrs.items():
                    if k in ("id", "field"):
                        continue
                    if k == "operation__fuzzy":
                        operation_fuzzy = v
                    elif k.endswith("__search_limit"):
                        field = k[:-len("__search_limit")]
                        try:
                            search_limits[field] = min(int(v), 50)
                        except ValueError:
                            search_limits[field] = 10
                    elif k.endswith("__fuzzy"):
                        field = k[:-len("__fuzzy")]
                        dynamic_queue.append({
                            "node_id": node_id, "node_type": target_type,
                            "alias": id_ref, "field": field, "mode": "fuzzy", "query": v,
                        })
                    elif k.endswith("__search"):
                        field = k[:-len("__search")]
                        dynamic_queue.append({
                            "node_id": node_id, "node_type": target_type,
                            "alias": id_ref, "field": field, "mode": "search", "query": v,
                        })
                    else:
                        config_updates[k] = _coerce_field_value(target_type, target_operation, k, v)

                # Provider sandbox mounts: canvas-level field. Normalize +
                # validate here so the agent gets immediate feedback.
                if "agent_sandbox_repos" in config_updates:
                    from nodes.agent.node_op_tools import normalize_sandbox_repos

                    repos, repos_err = normalize_sandbox_repos(config_updates["agent_sandbox_repos"])
                    if repos_err:
                        raise ValueError(f"agent_sandbox_repos: {repos_err}")
                    config_updates["agent_sandbox_repos"] = repos

                # Provider allowlist: not in any operation schema — validate
                # against the node's actual operation names instead.
                if "agent_tool_operations" in config_updates:
                    allowed_ops, ops_err = validate_agent_tool_operations(
                        target_type, config_updates["agent_tool_operations"]
                    )
                    if ops_err:
                        raise ValueError(f"agent_tool_operations: {ops_err}")
                    config_updates["agent_tool_operations"] = allowed_ops

                # Declared env-var need: the brain names variables the user must
                # provide (special cases only — an agent that calls an API with no
                # NoClick node). Names only; values become an agent_env credential.
                if "agent_env_requested" in config_updates:
                    from nodes.agent.user_env import normalize_requested_env_vars

                    reqd, reqd_err = normalize_requested_env_vars(
                        config_updates["agent_env_requested"]
                    )
                    if reqd_err:
                        raise ValueError(f"agent_env_requested: {reqd_err}")
                    config_updates["agent_env_requested"] = reqd

                # Inbound-email trigger: the chosen inbox name must be unique
                # across all workflows. Validate + claim the reservation now
                # (mirrors the FE email:reserve_address commit) so the AI can't
                # write an address already held by another node — which would
                # break routing at runtime. Stamps email_address + reservation_id
                # so the saved config matches the FE-reserved shape.
                if target_type == "trigger-email" and "local_part" in config_updates:
                    from utils.email_reservation_manager import EmailReservationManager
                    pool = await self.get_pool()
                    try:
                        config_updates.update(await EmailReservationManager.reserve_from_config(
                            pool, user_id, workflow_id, node_id, config_updates,
                        ))
                    except ValueError as e:
                        raise ValueError(f"local_part: {e} — choose a different available inbox name and retry.")

                # Apply search_limits to queued search ops
                for dq in dynamic_queue:
                    if dq["mode"] == "search" and dq["field"] in search_limits:
                        dq["limit"] = search_limits[dq["field"]]

                # Resolve operation__fuzzy before discriminator detection
                node_type = target.get("type", "")
                disc_field = get_discriminator_field(node_type)
                if operation_fuzzy:
                    ops = get_operations_for_node_type(node_type)
                    if ops:
                        q_lower = operation_fuzzy.lower()
                        matches = [
                            op for op in ops
                            if q_lower in op.name.lower() or q_lower in op.description.lower()
                        ]
                        if len(matches) == 1:
                            config_updates[disc_field] = matches[0].name
                            operations_log.append({
                                "action": "operation_fuzzy", "id": id_ref,
                                "resolved": True, "operation": matches[0].name,
                                "description": matches[0].description,
                            })
                        elif len(matches) == 0:
                            operations_log.append({
                                "action": "operation_fuzzy", "id": id_ref,
                                "resolved": False, "error": f"No operations matching '{operation_fuzzy}'",
                                "available": [{"name": op.name, "description": op.description} for op in ops],
                            })
                        else:
                            operations_log.append({
                                "action": "operation_fuzzy", "id": id_ref,
                                "resolved": False,
                                "matches": [{"name": m.name, "description": m.description} for m in matches],
                            })
                    else:
                        operations_log.append({
                            "action": "operation_fuzzy", "id": id_ref,
                            "resolved": False, "error": f"No operations found for {node_type}",
                        })

                # Detect discriminator field for operation tracking
                operation_value = config_updates.get(disc_field)

                # Either-or: a provider-wired node can't switch to a trigger
                # operation (mirror of the add_edge-time check).
                if operation_value and any(
                    e.get("source") == node_id and e.get("targetHandle") == "bottom"
                    for e in edges
                ):
                    trig_conflict = trigger_provider_conflict(node_type, operation_value)
                    if trig_conflict:
                        raise ValueError(trig_conflict)

                # Either-or: an MCP node that hosts wired tools can't gain a
                # server_url (mirror of the add_edge-time check).
                if "server_url" in config_updates:
                    url_conflict = mcp_server_url_conflict(
                        node_id, node_type, config_updates.get("server_url"), edges,
                    )
                    if url_conflict:
                        raise ValueError(url_conflict)

                await self._emit_builder_event(user_id, workflow_id, "node_processing_start", {
                    "nodeId": node_id,
                })

                # Deep merge config
                existing_config = target.get("config", {})
                if isinstance(target.get("data"), dict):
                    existing_config = target["data"].get("config", {})
                merged = self._deep_merge_config(existing_config, config_updates)
                drop_stale_agent_discriminator(node_type, config_updates, merged)

                # Canonicalize queryable enums + validate the merged config
                # (mutates `merged` in place); verdict attached to the response.
                is_provider = any(
                    e.get("source") == node_id and e.get("targetHandle") == "bottom"
                    for e in edges
                )
                config_verdict = self._postprocess_config(
                    node_type, operation_value or target_operation, merged,
                    is_provider=is_provider,
                    upstream_trigger_ids=(
                        self._upstream_trigger_ids(node_id, nodes, edges)
                        if node_type == "agent" else None
                    ),
                    changed_keys=set(config_updates.keys()),
                    prior_config=existing_config,
                )

                # Builder parity: a model flip that lands on a BYOK harness
                # auto-attaches the sole matching credential instead of only
                # hinting. Rides the same owner-gated post-save authorization
                # as set_credentials via set_cred_ids.
                if config_verdict and config_verdict.get("agent_credential_hint"):
                    auto_attached = await self._auto_attach_agent_credential(
                        user_id, merged, config_verdict["agent_credential_hint"],
                    )
                    if auto_attached:
                        set_cred_ids.add(auto_attached["id"])
                        config_verdict.pop("agent_credential_hint", None)
                        config_verdict["agent_credential_auto_attached"] = auto_attached

                if "data" in target and isinstance(target.get("data"), dict):
                    target["data"]["config"] = merged
                else:
                    target["config"] = merged

                await self._emit_builder_event(user_id, workflow_id, "node_updated", {
                    "nodeId": node_id, "config": merged,
                })
                affected_node_ids.add(node_id)

                # Track if operation was set, and clean up stale resources
                if operation_value:
                    alias = id_ref if id_ref in alias_map else node_id
                    nodes_with_operation.append({
                        "alias": alias, "node_id": node_id,
                        "node_type": node_type, "operation": operation_value,
                    })
                    # If operation changed away from a webhook-requiring one,
                    # clean up the orphaned cron schedule + webhook. The hook
                    # itself is DEFERRED to post-save (the reconciler reads the
                    # saved graph); the config strip is decided now from the
                    # ops alone — old-requires → new-doesn't is exactly when
                    # the mirrored registration fields become stale display
                    # state (a trigger→trigger change re-registers instead,
                    # and stripping would drop the webhook_id the delivery
                    # path matches on).
                    if target_operation and target_operation != operation_value:
                        try:
                            from utils.webhook_manager import WebhookManager, _WEBHOOK_CONFIG_FIELDS

                            if WebhookManager.operation_requires_webhook(
                                node_type, target_operation
                            ) and not WebhookManager.operation_requires_webhook(
                                node_type, operation_value
                            ):
                                for f in _WEBHOOK_CONFIG_FIELDS:
                                    merged.pop(f, None)
                                if isinstance(target.get("data"), dict):
                                    target["data"]["config"] = merged
                                else:
                                    target["config"] = merged

                            def _op_change_hook(
                                _nt=node_type, _nid=node_id,
                                _old=target_operation, _new=operation_value,
                            ):
                                async def _run(pool):
                                    await WebhookManager.handle_operation_change(
                                        pool, _nt, workflow_id, _nid,
                                        _old, _new, user_id=user_id,
                                    )
                                return _run

                            deferred_webhook_hooks.append(_op_change_hook())
                        except Exception as e:
                            logger.warning(f"[MCP Server] Operation change cleanup error for {node_id}: {e}")

                # Registration-relevant field edits (PostHog event_name, GitHub
                # repository) with an UNCHANGED operation reconcile post-save
                # too — otherwise the provider registration silently stays on
                # the OLD value until a panel reopen. Op changes are covered by
                # their own deferred hook above.
                if not (operation_value and target_operation and target_operation != operation_value):
                    try:
                        from utils.webhook_manager import WebhookManager as _WM

                        def _fields_hook(
                            _nt=node_type, _nid=node_id,
                            _old=dict(existing_config or {}), _new=dict(merged or {}),
                        ):
                            async def _run(pool):
                                await _WM.handle_registration_fields_change(
                                    pool, _nt, workflow_id, _nid,
                                    _old, _new, user_id=user_id,
                                )
                            return _run

                        deferred_webhook_hooks.append(_fields_hook())
                    except Exception as e:
                        logger.warning(f"[MCP Server] Fields-change hook error for {node_id}: {e}")

                operations_log.append({
                    "action": "update_config", "id": id_ref,
                    "node_id": node_id, "success": True,
                })
                any_succeeded = True

                # Attach the config verdict (config_valid / errors / missing_required /
                # resolutions / credential hint) to the op log + per-node map.
                if config_verdict:
                    operations_log[-1].update(config_verdict)
                    node_config_verdicts[node_id] = config_verdict

                # Validate references in the config values
                ref_warnings = self._validate_references(config_updates, nodes, edges, node_id)
                if ref_warnings:
                    operations_log[-1]["reference_warnings"] = ref_warnings

            except Exception as e:
                errors.append({"action": "update_config", "id": id_ref, "error": str(e)})
                operations_log.append({
                    "action": "update_config", "id": id_ref,
                    "success": False, "error": str(e),
                })

        # --- Process patch_config ops ---
        for op in patch_config_ops:
            attrs = op["attrs"]
            id_ref = attrs.get("id", "")
            field_name = attrs.get("field", "")

            try:
                if not field_name:
                    raise ValueError("patch_config requires a field attribute")

                node_id = _resolve_id(id_ref)
                target = None
                for n in nodes:
                    if n.get("id") == node_id:
                        target = n
                        break
                if not target:
                    raise ValueError(f"Node not found: {id_ref}")

                patch_text = op.get("body", "")
                if not patch_text:
                    raise ValueError("patch_config requires patch content in body")

                # Get existing config and apply patch via shared function
                existing_config = target.get("config", {})
                if isinstance(target.get("data"), dict):
                    existing_config = target["data"].get("config", {})

                prior_field_config = {field_name: existing_config.get(field_name)} \
                    if field_name in existing_config else {}
                err = apply_config_patch(existing_config, field_name, patch_text)
                if err:
                    raise ValueError(err)

                # Same canonicalize + validate + enforce pass as update_config —
                # patch_config previously skipped validation entirely.
                patch_verdict = self._postprocess_config(
                    target.get("type", ""),
                    self._get_current_operation(target),
                    existing_config,
                    changed_keys={field_name},
                    prior_config=prior_field_config,
                )

                if "data" in target and isinstance(target.get("data"), dict):
                    target["data"]["config"] = existing_config
                else:
                    target["config"] = existing_config

                await self._emit_builder_event(user_id, workflow_id, "node_updated", {
                    "nodeId": node_id, "config": existing_config,
                })
                affected_node_ids.add(node_id)

                patch_log: Dict[str, Any] = {
                    "action": "patch_config", "id": id_ref,
                    "node_id": node_id, "field": field_name, "success": True,
                }
                if patch_verdict:
                    patch_log["config_validation"] = patch_verdict
                operations_log.append(patch_log)
                any_succeeded = True

            except Exception as e:
                errors.append({"action": "patch_config", "id": id_ref, "error": str(e)})
                operations_log.append({
                    "action": "patch_config", "id": id_ref,
                    "success": False, "error": str(e),
                })

        # --- Process set_credentials ops ---
        for op in set_cred_ops:
            attrs = op["attrs"]
            id_ref = attrs.get("id", "")

            try:
                node_id = _resolve_id(id_ref)
                target = None
                for n in nodes:
                    if n.get("id") == node_id:
                        target = n
                        break
                if not target:
                    raise ValueError(f"Node not found: {id_ref}")

                # All non-reserved attrs are credential_type → credential_id mappings
                cred_map = {k: v for k, v in attrs.items() if k != "id"}
                if not cred_map:
                    raise ValueError("set_credentials requires at least one credential_type=credential_id pair")
                # Validate each credential exists + is accessible before applying.
                # A bogus/inaccessible id would FK-violate
                # workflow_authorized_credentials or get silently persisted to fail
                # later with invalid_auth — reject it so the agent picks a real one.
                # Then RE-KEY each id under its ACTUAL credential_type from the DB
                # (not the brain's chosen key): the frontend keys credentialIds by
                # credential_type, so a slack_bot_token placed under "slack_oauth"
                # would show as unselected. Skipped when no DB pool is available
                # (degraded / no-DB contexts), matching the authorize step below.
                cred_pool = await self.get_pool()
                if cred_pool is not None:
                    real_types = await resolve_accessible_credential_types(
                        [v for v in cred_map.values() if v], user_id, pool=cred_pool,
                    )
                    missing = [v for v in cred_map.values() if v and v not in real_types]
                    if missing:
                        raise ValueError(
                            f"credential(s) not found or not accessible: {', '.join(missing)} — "
                            "use an id from the available credentials list, don't invent one"
                        )
                    accepted = node_accepted_credential_types(target.get("type", ""))
                    rekeyed: Dict[str, str] = {}
                    for v in cred_map.values():
                        if not v:
                            continue
                        real_type = real_types[v]
                        if accepted and real_type not in accepted:
                            raise ValueError(
                                f"credential {v} is a '{real_type}' credential, which node "
                                f"{id_ref} does not accept (expects: {', '.join(sorted(accepted))}) "
                                "— pick a matching credential"
                            )
                        rekeyed[real_type] = v
                    cred_map = rekeyed
                set_cred_ids.update(v for v in cred_map.values() if v)

                # Use shared merge_credentials on the normalized config dict
                existing_config = target.get("config", {})
                if isinstance(target.get("data"), dict):
                    existing_config = target["data"].get("config", {})
                old_cred_ids = dict(existing_config.get("credentialIds") or {})
                merge_credentials(existing_config, cred_map)

                if "data" in target and isinstance(target.get("data"), dict):
                    target["data"]["config"] = existing_config
                else:
                    target["config"] = existing_config

                await self._emit_builder_event(user_id, workflow_id, "node_updated", {
                    "nodeId": node_id, "config": existing_config,
                })
                affected_node_ids.add(node_id)
                cred_set_node_ids.add(node_id)

                # S3: self-heal external push-trigger webhooks when the credential
                # changed — the choke point tears down the provider endpoint bound
                # to the OLD credential and re-registers under the new one (no-op
                # for non-webhook nodes). DEFERRED to post-save: the reconciler
                # reads the SAVED graph as desired truth, so firing here would
                # converge against the stale pre-save blob and no-op.
                if old_cred_ids != (existing_config.get("credentialIds") or {}):
                    try:
                        from utils.webhook_manager import WebhookManager as _WMc

                        def _cred_change_hook(
                            _nt=target.get("type", ""), _nid=node_id,
                            _old=dict(old_cred_ids or {}),
                            _new=dict(existing_config.get("credentialIds") or {}),
                        ):
                            async def _run(pool):
                                await _WMc.handle_credential_change(
                                    pool, _nt, workflow_id, _nid,
                                    {"credentialIds": _old},
                                    {"credentialIds": _new},
                                    user_id,
                                )
                            return _run

                        deferred_webhook_hooks.append(_cred_change_hook())
                    except Exception as e:
                        logger.warning(f"[MCP Server] Credential change self-heal error for {node_id}: {e}")

                operations_log.append({
                    "action": "set_credentials", "id": id_ref,
                    "node_id": node_id, "success": True,
                })
                any_succeeded = True

            except Exception as e:
                errors.append({"action": "set_credentials", "id": id_ref, "error": str(e)})
                operations_log.append({
                    "action": "set_credentials", "id": id_ref,
                    "success": False, "error": str(e),
                })

        # --- Process disable_node / enable_node ops ---
        for op in disable_node_ops + enable_node_ops:
            attrs = op["attrs"]
            id_ref = attrs.get("id", "")
            is_disable = op["tag"] == "disable_node"

            try:
                node_id = _resolve_id(id_ref)
                target = None
                for n in nodes:
                    if n.get("id") == node_id:
                        target = n
                        break
                if not target:
                    raise ValueError(f"Node not found: {id_ref}")

                # The disabled flag lives in the flat config blob — the wire
                # shape that frontend buildSaveConfig produces and frontend
                # rawConfigToPayload restores. Previously we also wrote
                # target["disabled"] and target["data"]["disabled"] for legacy
                # readers; both are now dropped now that workflow_ops only
                # reads from node["config"]["disabled"].
                existing_config = target.setdefault("config", {})
                if isinstance(existing_config, dict):
                    set_node_disabled(existing_config, is_disable)

                await self._emit_builder_event(user_id, workflow_id, "node_updated", {
                    "nodeId": node_id,
                    "disabled": is_disable,
                    "config": target.get("config", {}) or {},
                })
                affected_node_ids.add(node_id)

                operations_log.append({
                    "action": op["tag"], "id": id_ref,
                    "node_id": node_id, "success": True,
                })
                any_succeeded = True

            except Exception as e:
                errors.append({"action": op["tag"], "id": id_ref, "error": str(e)})
                operations_log.append({
                    "action": op["tag"], "id": id_ref,
                    "success": False, "error": str(e),
                })

        # --- Process mock_node / unmock_node ops ---
        for op in mock_node_ops + unmock_node_ops:
            attrs = op["attrs"]
            id_ref = attrs.get("id", "")
            is_mock = op["tag"] == "mock_node"

            try:
                node_id = _resolve_id(id_ref)
                target = None
                for n in nodes:
                    if n.get("id") == node_id:
                        target = n
                        break
                if not target:
                    raise ValueError(f"Node not found: {id_ref}")

                # Get normalized config dict
                existing_config = target.get("config", {})
                if isinstance(target.get("data"), dict):
                    existing_config = target["data"].get("config", existing_config)

                if is_mock:
                    body = op.get("body")
                    raw = body if body else attrs.get("output")
                    if not raw:
                        raise ValueError("mock_node requires output (as body content or output attribute)")
                    err = set_mock_output(existing_config, raw)
                    if err:
                        raise ValueError(err)
                    # Mirror to top-level for MCP format compatibility
                    target["mockedOutput"] = existing_config["mockedOutput"]
                else:
                    set_mock_output(existing_config, None)
                    # Clear from all MCP locations
                    target.pop("mockedOutput", None)
                    if isinstance(target.get("data"), dict):
                        target["data"].pop("mockedOutput", None)

                emit_config = dict(target.get("config", {}) or {})
                if not is_mock:
                    # Explicitly send None so the frontend spread overwrites (not merges) the key
                    emit_config["mockedOutput"] = None
                await self._emit_builder_event(user_id, workflow_id, "node_updated", {
                    "nodeId": node_id,
                    "config": emit_config,
                })
                affected_node_ids.add(node_id)

                operations_log.append({
                    "action": op["tag"], "id": id_ref,
                    "node_id": node_id, "success": True,
                })
                any_succeeded = True

            except Exception as e:
                errors.append({"action": op["tag"], "id": id_ref, "error": str(e)})
                operations_log.append({
                    "action": op["tag"], "id": id_ref,
                    "success": False, "error": str(e),
                })

        # --- Process update_settings ops ---
        for op in update_settings_ops:
            attrs = op["attrs"]
            id_ref = attrs.get("id", "")

            try:
                node_id = _resolve_id(id_ref)
                target = None
                for n in nodes:
                    if n.get("id") == node_id:
                        target = n
                        break
                if not target:
                    raise ValueError(f"Node not found: {id_ref}")

                # Get normalized config dict (prefer data.config path if present)
                existing_config = target.get("config", {})
                if isinstance(target.get("data"), dict):
                    existing_config = target["data"].get("config", existing_config)
                if not isinstance(existing_config, dict):
                    existing_config = {}

                settings_map = {k: v for k, v in attrs.items() if k != "id"}
                if not settings_map:
                    raise ValueError("update_settings requires at least one setting attribute")

                err = update_node_settings(existing_config, settings_map)
                if err:
                    raise ValueError(err)

                # Mirror _settings back to all config locations
                if isinstance(target.get("config"), dict):
                    target["config"]["_settings"] = existing_config["_settings"]
                if isinstance(target.get("data"), dict) and isinstance(target["data"].get("config"), dict):
                    target["data"]["config"]["_settings"] = existing_config["_settings"]

                await self._emit_builder_event(user_id, workflow_id, "node_updated", {
                    "nodeId": node_id,
                    "config": target.get("config", {}) or {},
                })
                affected_node_ids.add(node_id)

                operations_log.append({
                    "action": "update_settings", "id": id_ref,
                    "node_id": node_id, "settings": existing_config["_settings"],
                    "success": True,
                })
                any_succeeded = True

            except Exception as e:
                errors.append({"action": "update_settings", "id": id_ref, "error": str(e)})
                operations_log.append({
                    "action": "update_settings", "id": id_ref,
                    "success": False, "error": str(e),
                })

        # --- Resolve dynamic options (after set_credentials so creds are available) ---
        dynamic_options_response: Dict[str, Dict[str, Any]] = {}

        # Process queued __fuzzy / __search ops
        for dq in dynamic_queue:
            node_id = dq["node_id"]
            alias = dq["alias"]
            field = dq["field"]
            mode = dq["mode"]
            query = dq.get("query", "")
            limit = dq.get("limit", 10)

            try:
                # Find the node to get credentials
                target = None
                for n in nodes:
                    if n.get("id") == node_id:
                        target = n
                        break
                if not target:
                    continue

                cred_data, cred_id = await self._decrypt_credential_for_node(target, user_id)
                if cred_data is None:
                    cred_data = {}

                # Get context from existing config (for dependent fields)
                config = target.get("config", {})
                if isinstance(target.get("data"), dict):
                    config = target["data"].get("config", {})
                context = {k: v for k, v in config.items() if k != "credentialIds" and isinstance(v, str)}

                result = await self._load_dynamic_options_for_field(
                    dq["node_type"], field, cred_data, context=context,
                    user_id=user_id, credential_id=cred_id,
                )
                if "error" in result:
                    dynamic_options_response.setdefault(alias, {})[field] = result
                    continue

                all_options = result.get("options", [])

                if mode == "fuzzy":
                    # Filter by case-insensitive substring match on label
                    q_lower = query.lower()
                    matches = [o for o in all_options if q_lower in o.get("label", "").lower()]
                    if len(matches) == 1:
                        # Auto-resolve: set the field value on the node
                        resolved_val = matches[0]["value"]
                        config[field] = resolved_val
                        if isinstance(target.get("data"), dict):
                            target["data"]["config"] = config
                        else:
                            target["config"] = config
                        await self._emit_builder_event(user_id, workflow_id, "node_updated", {
                            "nodeId": node_id, "config": config,
                        })
                        dynamic_options_response.setdefault(alias, {})[field] = {
                            "options": matches, "resolved": True, "resolved_value": resolved_val,
                        }
                    else:
                        dynamic_options_response.setdefault(alias, {})[field] = {
                            "options": matches[:limit], "resolved": False,
                        }
                elif mode == "search":
                    q_lower = query.lower()
                    matches = [o for o in all_options if q_lower in o.get("label", "").lower()]
                    dynamic_options_response.setdefault(alias, {})[field] = {
                        "options": matches[:limit],
                    }

            except Exception as e:
                logger.warning(f"[MCP Server] Dynamic option resolution error for {field}: {e}")
                dynamic_options_response.setdefault(alias, {})[field] = {"error": str(e)}

        # Process include_dynamic_options flag (auto-load first-level fields)
        if include_dynamic_options:
            # Collect all nodes that were touched in this batch and have credentials
            touched_node_ids = set()
            for op_log in operations_log:
                if op_log.get("success") and op_log.get("node_id"):
                    touched_node_ids.add(op_log["node_id"])

            for n in nodes:
                nid = n.get("id")
                if nid not in touched_node_ids:
                    continue
                nt = n.get("type", "")
                node_class = NODE_REGISTRY.get(nt)
                if not node_class or not hasattr(node_class, 'load_field_options'):
                    continue

                cred_data, cred_id = await self._decrypt_credential_for_node(n, user_id)
                if cred_data is None:
                    cred_data = {}

                # Find first-level dynamic fields (no depends_on)
                try:
                    schema = get_operation_schema(nt, self._get_current_operation(n))
                    if not schema:
                        continue
                    for fname, fschema in schema.get("properties", {}).items():
                        dyn = fschema.get("x-dynamic-options")
                        if not dyn or dyn.get("depends_on"):
                            continue
                        # Find alias for this node
                        alias = nid
                        for a, rid in alias_map.items():
                            if rid == nid:
                                alias = a
                                break
                        if alias in dynamic_options_response and fname in dynamic_options_response[alias]:
                            continue  # Already resolved by __fuzzy/__search
                        result = await self._load_dynamic_options_for_field(
                            nt, fname, cred_data, context={},
                            user_id=user_id, credential_id=cred_id,
                        )
                        if "error" not in result:
                            opts = result.get("options", [])[:dynamic_options_limit]
                            dynamic_options_response.setdefault(alias, {})[fname] = {"options": opts}
                except Exception as e:
                    logger.warning(f"[MCP Server] include_dynamic_options error for {nt}: {e}")

        # --- Provision webhooks for operations that require them ---
        # Candidates: operation set this batch, newly added nodes, and nodes
        # that just gained a credential (provider-side registration — e.g.
        # Telegram setWebhook — can only happen once the credential exists).
        # WebhookManager.provision_node_webhook filters by schema and does the
        # panel-equivalent load, shared with the agentic builder.
        webhook_candidates: List[Dict[str, Any]] = []
        seen_webhook_node_ids: set = set()

        for info in nodes_with_operation:
            webhook_candidates.append(info)
            seen_webhook_node_ids.add(info["node_id"])

        # Config writes count too: registration is gated on config validity,
        # so the batch that completes a required field (e.g. form_id) is the
        # one that can finally arm a poll trigger's schedule + baseline.
        config_touched_ids: set = set()
        for op in update_config_ops + patch_config_ops:
            try:
                config_touched_ids.add(_resolve_id(op["attrs"].get("id", "")))
            except Exception:
                continue

        for real_id in (
            [rid for rid in alias_map.values()]
            + sorted(cred_set_node_ids)
            + sorted(config_touched_ids)
        ):
            if real_id in seen_webhook_node_ids:
                continue
            target = next((n for n in nodes if n.get("id") == real_id), None)
            if not target:
                continue
            seen_webhook_node_ids.add(real_id)
            webhook_candidates.append({
                "node_id": real_id, "node_type": target.get("type", ""),
                # Current operation (may be set in same batch); None for
                # non-discriminated nodes → single schema.
                "operation": self._get_current_operation(target),
            })

        if webhook_candidates:
            from utils.webhook_manager import WebhookManager

            # Pure schema pre-filter BEFORE any pool access: most touched
            # nodes carry no webhook field, and get_pool() fail-fast raises
            # in pool-less contexts where nothing needed provisioning anyway.
            webhook_candidates = [
                info for info in webhook_candidates
                if WebhookManager.node_webhook_field_for(
                    info["node_type"], info.get("operation")
                )
            ]
            pool = await self.get_pool() if webhook_candidates else None
            if not pool:
                webhook_candidates = []
            for info in webhook_candidates:
                node_id = info["node_id"]
                try:
                    target = next((n for n in nodes if n.get("id") == node_id), None)
                    if not target:
                        continue
                    config = target.get("config", {})
                    if isinstance(target.get("data"), dict):
                        config = target["data"].get("config", {})

                    updates = await WebhookManager.provision_node_webhook(
                        pool,
                        user_id=user_id,
                        workflow_id=workflow_id,
                        node_id=node_id,
                        node_type=info["node_type"],
                        operation=info.get("operation"),
                        config=config,
                    )
                    if not updates:
                        continue
                    config.update(updates)
                    if isinstance(target.get("data"), dict):
                        target["data"]["config"] = config
                    else:
                        target["config"] = config

                    await self._emit_builder_event(user_id, workflow_id, "node_updated", {
                        "nodeId": node_id, "config": config,
                    })
                    affected_node_ids.add(node_id)

                    logger.info(
                        f"[MCP Server] Provisioned webhook for "
                        f"{info['node_type']}:{info.get('operation')} on node {node_id}"
                    )

                except Exception as e:
                    logger.warning(f"[MCP Server] Webhook provisioning error for {node_id}: {e}")
                    # Surface it — a trigger saved without its webhook is a
                    # broken build the caller must see, not just a log line.
                    operations_log.append({
                        "action": "provision_webhook", "node_id": node_id,
                        "success": False, "error": str(e),
                    })

        # --- Process remove_edge ops ---
        # Collect edge IDs added in this batch to avoid removing newly added edges
        batch_added_edge_ids = {
            log["edge_id"] for log in operations_log
            if log.get("action") == "add_edge" and log.get("success")
        }
        for op in remove_edge_ops:
            attrs = op["attrs"]
            source_ref = attrs.get("from", "")
            target_ref = attrs.get("to", "")
            handle = attrs.get("handle")

            try:
                source_id = _resolve_id(source_ref)
                target_id = _resolve_id(target_ref)

                edge_to_remove = None
                for e in edges:
                    if e.get("source") == source_id and e.get("target") == target_id:
                        # If handle specified, match exactly
                        if handle is not None and e.get("sourceHandle") != handle:
                            continue
                        # If no handle specified, prefer removing old edges over batch-added ones
                        if handle is None and e["id"] in batch_added_edge_ids:
                            continue
                        edge_to_remove = e
                        break
                # Fallback: if no non-batch edge found, try batch edges too
                if not edge_to_remove:
                    for e in edges:
                        if e.get("source") == source_id and e.get("target") == target_id:
                            if handle is not None and e.get("sourceHandle") != handle:
                                continue
                            edge_to_remove = e
                            break
                if not edge_to_remove:
                    raise ValueError(f"Edge not found from {source_ref} to {target_ref}")

                data["edges"] = [e for e in edges if e["id"] != edge_to_remove["id"]]
                edges = data["edges"]

                await self._emit_builder_event(user_id, workflow_id, "edge_removed", {
                    "edgeId": edge_to_remove["id"],
                })

                operations_log.append({
                    "action": "remove_edge", "edge_id": edge_to_remove["id"], "success": True,
                })
                any_succeeded = True

            except Exception as e:
                errors.append({"action": "remove_edge", "from": source_ref, "to": target_ref, "error": str(e)})
                operations_log.append({
                    "action": "remove_edge", "from": source_ref, "to": target_ref,
                    "success": False, "error": str(e),
                })

        # --- Process remove_node ops ---
        removed_node_ids: List[str] = []
        removed_nodes_data: List[Dict[str, Any]] = []
        for op in remove_node_ops:
            attrs = op["attrs"]
            id_ref = attrs.get("id", "")

            try:
                node_id = _resolve_id(id_ref)

                node_obj = next((n for n in nodes if n.get("id") == node_id), None)
                if not node_obj:
                    raise ValueError(f"Node not found: {id_ref}")

                # Capture node data before removal for external webhook cleanup
                removed_nodes_data.append(node_obj)

                removed_edge_ids = [
                    e["id"] for e in edges
                    if e.get("source") == node_id or e.get("target") == node_id
                ]
                data["nodes"] = [n for n in nodes if n.get("id") != node_id]
                data["edges"] = [e for e in edges if e["id"] not in removed_edge_ids]
                nodes = data["nodes"]
                edges = data["edges"]
                removed_node_ids.append(node_id)

                await self._emit_builder_event(user_id, workflow_id, "node_removed", {
                    "nodeId": node_id, "removedEdgeIds": removed_edge_ids,
                })

                operations_log.append({
                    "action": "remove_node", "id": id_ref,
                    "node_id": node_id, "success": True,
                })
                any_succeeded = True

            except Exception as e:
                errors.append({"action": "remove_node", "id": id_ref, "error": str(e)})
                operations_log.append({
                    "action": "remove_node", "id": id_ref,
                    "success": False, "error": str(e),
                })

        # Clean up ALL resources for removed nodes through the shared facade —
        # cron schedules, provider-side webhook deregistration (every provider,
        # via cleanup_external_webhook dispatch) and node state.
        # The webhooks row is deactivated, not deleted, so a later re-add
        # reuses the same URL. Uses the captured pre-removal node dicts since
        # they've already been spliced out of the in-memory graph;
        # background=True keeps provider round-trips off the response path.
        if removed_node_ids:
            try:
                pool = await self.get_pool()
                if pool:
                    from utils.workflow_resource_manager import cleanup_nodes_resources
                    await cleanup_nodes_resources(
                        pool=pool,
                        workflow_id=workflow_id,
                        node_ids=removed_node_ids,
                        background=True,
                        old_nodes=removed_nodes_data,
                        requesting_user_id=user_id,
                    )
            except Exception as e:
                logger.warning(f"[MCP Server] Webhook cleanup error for removed nodes: {e}")

        # C5: reference-validate inline add_node configs now that all nodes and
        # edges exist (a post-pass so forward references resolve).
        if pending_ref_checks:
            nodes_by_id = {n.get("id"): n for n in nodes}
            for log_idx, nid in pending_ref_checks:
                node = nodes_by_id.get(nid)
                if not node:
                    continue
                ref_warnings = self._validate_references(
                    node.get("config", {}) or {}, nodes, edges, nid,
                )
                if ref_warnings and 0 <= log_idx < len(operations_log):
                    operations_log[log_idx]["reference_warnings"] = ref_warnings

        # Save if any operation succeeded
        if any_succeeded:
            # Apply incremental autolayout + compute sticky-note updates via
            # the shared helper (mirrored by the internal agentic builder).
            from coder.workflow.layout import compute_incremental_layout
            layout_data = compute_incremental_layout(
                data["nodes"], data["edges"],
                newly_added_ids=alias_map.values(),
            )
            await self._emit_builder_event(
                user_id, workflow_id, "layout_applied", layout_data,
            )

            save_err = await self._save_workflow(
                user_id, workflow_id, data, expected_updated_at=load_meta.get("updated_at"),
            )
            if save_err:
                return {"error": save_err, "operations": operations_log}

            # Deferred webhook lifecycle hooks — AFTER the save, so the
            # reconciler's desired-state read sees the graph these ops built.
            # Spawned: provider round-trips must not sit on the MCP response.
            if deferred_webhook_hooks:
                from utils.async_helpers import spawn

                async def _run_deferred_hooks(hooks=list(deferred_webhook_hooks)):
                    try:
                        _pool = await self.get_pool()
                        if not _pool:
                            return
                        for hook in hooks:
                            try:
                                await hook(_pool)
                            except Exception:
                                logger.warning(
                                    "[MCP Server] Deferred webhook hook failed",
                                    exc_info=True,
                                )
                    except Exception:
                        logger.warning(
                            "[MCP Server] Deferred webhook hooks aborted", exc_info=True
                        )

                spawn(
                    _run_deferred_hooks(),
                    name=f"mcp-webhook-hooks:{workflow_id}",
                )

            # Authorize credentials placed via set_credentials for run-as-owner
            # resolution. Owner-gated: only if the MCP actor is the workflow owner
            # (a collaborator's MCP set_credentials must not self-authorize a run).
            if set_cred_ids:
                try:
                    pool = await self.get_pool()
                    owner_id = await get_workflow_owner_id(pool, workflow_id)
                    if owner_id and str(owner_id) == str(user_id):
                        async with pool.acquire() as conn:
                            await authorize_credentials_for_workflow(
                                conn, workflow_id, owner_id, set_cred_ids)
                except Exception as e:
                    logger.warning(f"[MCP] Failed to authorize credentials for {workflow_id}: {e}")

        # --- Workflow variables + authored test runs (settings-level content) ---
        # Processed AFTER the graph save so a failed save never orphans
        # settings; the write itself is a top-level JSONB key merge, so
        # variables and rehearsal authoring can't clobber each other.
        # Owner-gated — mirrors the socket path's settings rule.
        authored_test_runs: List[Dict[str, str]] = []
        if define_variable_ops or add_test_run_ops:
            await self._process_workflow_content_ops(
                user_id, workflow_id,
                define_variable_ops, add_test_run_ops,
                nodes, edges, operations_log, errors, authored_test_runs,
            )

        # --- Test-run hand-off — LAST, so authored content is persisted
        # before the frontend rehydrates. The event switches an open canvas to
        # the Test Run screen and arms its auto-start; with no canvas open it
        # is a no-op.
        if run_test_ops:
            op = run_test_ops[-1]
            trigger_ref = (op["attrs"].get("trigger") or "").strip()
            node = next((n for n in nodes if n.get("id") == _resolve_id(trigger_ref)), None)
            trigger_type = (node.get("type") if node else trigger_ref) or None
            run_ref = (op["attrs"].get("run") or "").strip() or None
            for a in reversed(authored_test_runs):
                if run_ref in (a["name"], a["slug"]) or (not run_ref and not trigger_ref):
                    trigger_type, run_ref = a["node_type"], a["slug"]
                    break
            await self._emit_builder_event(
                user_id, workflow_id, "run_test",
                {
                    **({"trigger": trigger_type} if trigger_type else {}),
                    **({"run": run_ref} if run_ref else {}),
                },
            )
            operations_log.append({
                "action": "run_test", "success": True,
                "note": "Test Run screen opened on the user's canvas (no-op if the workflow isn't open in a browser)",
            })

        # Build response
        response: Dict[str, Any] = {
            "success": len(errors) == 0,
            "workflow_id": workflow_id,
            "operations": operations_log,
            "alias_map": alias_map,
            "errors": errors,
        }

        # Progressive disclosure: include operations for added node types
        if include_operations and added_node_types:
            from utils.node_schema_tracker import get_schema_for_node
            node_operations = {}
            for nt in added_node_types:
                ops = get_operations_for_node_type(nt)
                # Build operations list with per-operation output schemas from DB
                ops_list = []
                for op in ops:
                    op_entry: Dict[str, Any] = _op_to_dict(op)  # I4: +display_name/category
                    db_schema = await get_schema_for_node(nt, op.name)
                    if db_schema:
                        op_entry["output_schema"] = db_schema
                    ops_list.append(op_entry)
                node_class = NODE_REGISTRY.get(nt)
                handles = node_class.get_output_handles() if node_class else None
                nt_entry: Dict[str, Any] = {"operations": ops_list}
                if handles:
                    nt_entry["output_handles"] = handles
                guidance = _node_guidance(nt, "operations")  # I2
                if guidance:
                    nt_entry["guidance"] = guidance
                node_operations[nt] = nt_entry
            response["node_operations"] = node_operations

        # Progressive disclosure: include configs for nodes where operation was set
        if include_configs and nodes_with_operation:
            node_configs = {}
            for info in nodes_with_operation:
                schema = get_operation_schema(info["node_type"], info["operation"])
                if schema:
                    schema = resolve_schema_refs(schema)
                    props, required = strip_discriminator(schema, info["node_type"])
                    compact = compact_schema(props, required)
                    entry: Dict[str, Any] = {
                        "operation": info["operation"],
                        "schema": compact,
                    }
                    # Include credential info
                    cred_info = await self._get_credential_info_for_node(info["node_type"], user_id)
                    if cred_info:
                        entry["credentials"] = cred_info
                    # I2: curated config Best-Practices guidance for this node type.
                    guidance = _node_guidance(info["node_type"], "config")
                    if guidance:
                        entry["guidance"] = guidance
                    # Include upstream nodes with output info for reference building
                    target_nid = info["node_id"]
                    upstream_inputs = []
                    for n in nodes:
                        nid = n.get("id")
                        if nid == target_nid:
                            continue
                        is_upstream = any(
                            e.get("source") == nid and e.get("target") == target_nid
                            for e in edges
                        )
                        if not is_upstream:
                            continue
                        _config = n.get("config", {}) or {}
                        output = _config.get("output") or _config.get("mockedOutput")
                        up_type = n.get("type", "")
                        input_info: Dict[str, Any] = {
                            "node_id": nid, "type": up_type,
                            "has_output": output is not None,
                        }
                        paths = None
                        if output is not None and isinstance(output, dict):
                            paths = extract_output_paths(output)
                        else:
                            # I3: no live output — fall back to the DB-learned schema
                            # so a never-run pipeline still gets ready-made references.
                            from utils.node_schema_tracker import get_schema_for_node
                            db_schema = await get_schema_for_node(up_type, self._get_current_operation(n) or "default")
                            if db_schema:
                                paths = extract_output_paths(db_schema)
                        if paths:
                            input_info["output_fields"] = paths
                            input_info["references"] = [f"{{{{ $('{nid}').{p} }}}}" for p in paths[:8]]
                        upstream_inputs.append(input_info)
                    if upstream_inputs:
                        entry["available_inputs"] = upstream_inputs
                    node_configs[info["alias"]] = entry
            response["node_configs"] = node_configs

        # Include dynamic_options if any were resolved
        if dynamic_options_response:
            response["dynamic_options"] = dynamic_options_response

        # Include affected configs so callers can verify changes without extra round-trips
        if affected_node_ids:
            affected_configs = {}
            for n in nodes:
                nid = n.get("id")
                if nid in affected_node_ids:
                    _config = n.get("config", {}) or {}
                    entry = {
                        "config": _config,
                        "disabled": _config.get("disabled", False),
                        "has_mock": _config.get("mockedOutput") is not None,
                    }
                    # Surface the validation verdict (config_valid / errors /
                    # missing_required / resolutions / credential hint) inline.
                    if nid in node_config_verdicts:
                        entry.update(node_config_verdicts[nid])
                    affected_configs[nid] = entry
            response["affected_configs"] = affected_configs

        # CR2: provider-wired nodes whose allowlisted operations need a credential
        # but have none attached. The include_configs credential block never fires
        # for providers (they carry no discriminator operation), so surface it here.
        provider_source_ids = {e.get("source") for e in edges if e.get("targetHandle") == "bottom"}
        if provider_source_ids:
            from nodes.agent.node_op_tools import allowlist_requires_credentials
            nodes_by_id = {n.get("id"): n for n in nodes}
            cred_requests = []
            for nid in provider_source_ids:
                n = nodes_by_id.get(nid)
                if not n:
                    continue
                cfg = n.get("config", {}) or {}
                if node_has_credential(cfg):
                    continue
                node_type = n.get("type", "")
                try:
                    if not allowlist_requires_credentials(node_type, cfg.get("agent_tool_operations") or []):
                        continue
                except Exception:
                    continue
                req: Dict[str, Any] = {"node_id": nid, "type": node_type}
                info = await self._get_credential_info_for_node(node_type, user_id)
                if info:
                    req.update({k: v for k, v in info.items() if k != "available"})
                    req["available"] = info.get("available", [])
                cred_requests.append(req)
            if cred_requests:
                response["credential_requests"] = cred_requests

        # CR4: surface any <ask>/<input> ops the caller included.
        if input_requests:
            response["input_requests"] = input_requests

        return response

    def _get_current_operation(self, node: Dict[str, Any]) -> Optional[str]:
        """Get the current operation value from a node's config."""
        config = node.get("config", {}) or {}
        node_type = node.get("type", "")
        disc_field = get_discriminator_field(node_type)
        return config.get(disc_field)

    async def _collect_node_results(
        self, workflow_id: str, user_id: str, node_ids: Optional[set] = None,
    ) -> tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
        """Collect node outputs and execution record after a workflow run.

        Returns (node_results, execution_record) where node_results maps
        node_id -> {type, output_preview} and execution_record is the latest
        execution row for this workflow+user (or None).
        """
        pool = await self.get_pool()
        if not pool:
            return {}, None

        node_results: Dict[str, Any] = {}
        execution_record = None

        async with pool.acquire() as conn:
            # Load workflow data to read persisted outputs
            row = await conn.fetchrow(
                "SELECT workflow FROM workflows WHERE id = $1",
                uuid.UUID(workflow_id),
            )
            if row:
                wf_data = row["workflow"] or {"nodes": []}
                for node in wf_data.get("nodes", []):
                    nid = node.get("id")
                    if node_ids and nid not in node_ids:
                        continue
                    _config = node.get("config", {}) or {}
                    output = _config.get("output")
                    if output is not None:
                        # Truncate large outputs for MCP response
                        output_str = json.dumps(output) if not isinstance(output, str) else output
                        preview = output_str[:500] + "..." if len(output_str) > 500 else output_str
                        node_results[nid] = {
                            "type": node.get("type", "unknown"),
                            "output_preview": preview,
                        }

            # Get the most recent execution record
            exec_row = await conn.fetchrow("""
                SELECT id, status, started_at, finished_at, nodes_executed, error
                FROM workflow_executions
                WHERE workflow_id = $1 AND user_id = $2
                ORDER BY started_at DESC LIMIT 1
            """, uuid.UUID(workflow_id), uuid.UUID(user_id))
            if exec_row:
                execution_record = {
                    "execution_id": str(exec_row["id"]),
                    "status": exec_row["status"],
                    "started_at": exec_row["started_at"].isoformat() if exec_row["started_at"] else None,
                    "finished_at": exec_row["finished_at"].isoformat() if exec_row["finished_at"] else None,
                    "nodes_executed": exec_row["nodes_executed"],
                    "error": exec_row["error"],
                }

        return node_results, execution_record

    async def _read_node_states(self, workflow_id: str) -> Dict[str, Any]:
        """Latest per-node terminal status/error map (the source that drives the
        canvas chips), best-effort. Reused by run_workflow/run_nodes/get_node_statuses."""
        pool = await self.get_pool()
        if not pool:
            return {}
        try:
            from utils.cas.store import read_latest_node_statuses
            return await read_latest_node_statuses(pool, workflow_id)
        except Exception as e:
            logger.debug(f"[MCP] Failed to read node statuses for {workflow_id}: {e}")
            return {}

    # Canvas-level config keys that live outside the node's Pydantic operation
    # model (agent tool allowlist, sandbox mounts, hosted-link display fields).
    # Validating a config that carries these against the operation model would
    # spuriously fail, so nodes carrying them skip Pydantic validation.
    _CANVAS_ONLY_CONFIG_KEYS = frozenset({"agent_tool_operations", "agent_sandbox_repos", "agent_env_requested"})

    def _upstream_trigger_ids(
        self,
        node_id: str,
        nodes: List[Dict[str, Any]],
        edges: List[Dict[str, Any]],
    ) -> set:
        """Ids of direct-upstream nodes acting as trigger sources for node_id."""
        by_id = {n.get("id"): n for n in nodes}
        out: set = set()
        for e in edges:
            if e.get("target") != node_id:
                continue
            src = by_id.get(e.get("source"))
            if src and is_trigger_source(
                src.get("type", ""), self._get_current_operation(src)
            ):
                out.add(src.get("id"))
        return out

    def _postprocess_config(
        self,
        node_type: str,
        operation: Optional[str],
        config: Dict[str, Any],
        *,
        is_provider: bool = False,
        upstream_trigger_ids: Optional[set] = None,
        changed_keys: Optional[set] = None,
        prior_config: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Canonicalize + validate a merged node config IN PLACE, returning a
        structured verdict for the response — the MCP equivalent of the builder's
        shared configuration validation routine (resolve queryable enums → strip placeholder auth
        headers → Pydantic/JSX/placeholder validation → missing-required).

        Mutates *config*: queryable-enum values are rewritten to their canonical
        id, ``__label`` display-cache sidecars are dropped (the FE re-derives
        them; an AI-written or stale one renders the wrong label), stringified
        JSON in structured fields is parsed, and placeholder auth headers are
        removed (their presence surfaced as a credential hint). When
        ``changed_keys`` is given, changed keys whose values are STILL
        wrong-typed after coercion are REVERTED to ``prior_config`` (dropped
        when absent there) — a wrong-typed value must never persist, it kills
        every run at the node's runtime parse. Returns None when there's
        nothing meaningful to validate (provider-wired node, or a config
        carrying canvas-only keys) so callers can skip attaching a verdict.
        Reuses the exact functions the internal builder uses so both paths agree.
        """
        # Sidecar strip applies to every AI write, provider-wired or not.
        strip_label_sidecars(config)

        if is_provider or (self._CANVAS_ONLY_CONFIG_KEYS & set(config.keys())):
            return None

        op = operation or "default"

        # C4: canonicalize queryable-enum fields (e.g. agent model) in place.
        resolutions = resolve_config_dict(get_operation_schema(node_type, op), config)

        # C4b: parse stringified-JSON values for structured fields in place,
        # then revert changed keys whose values are still wrong-typed.
        coerced_notes = coerce_config_value_types(node_type, op, config)
        rejected_values: List[Dict[str, str]] = []
        if changed_keys:
            for key, msg in config_value_errors(node_type, op, config):
                if key not in changed_keys:
                    continue
                val = config.get(key)
                if isinstance(val, str) and "{{" in val:
                    continue  # runtime template — can't be judged statically
                prior = (prior_config or {}).get(key)
                if prior is None and key not in (prior_config or {}):
                    config.pop(key, None)
                else:
                    config[key] = prior
                rejected_values.append({"field": key, "error": msg})

        # C3: strip placeholder auth headers (http-request) → credential hint.
        auth_hint = None
        if node_type == "automation-http-request":
            stripped = strip_placeholder_auth_headers(config)
            if stripped:
                cred_type, label = http_auth_credential_hint(stripped)
                auth_hint = {"credential_type": cred_type, "label": label}

        # Agent model → credential requirement is config-dependent (a CLI
        # harness is always BYOK), so a model/sub-model update can flip a
        # platform-billed agent into needing a user credential. Surface it —
        # the schema-based credential block never fires for agents.
        agent_cred_hint = None
        stripped_trigger_refs: List[str] = []
        if node_type == "agent":
            from nodes.agent.config.providers import agent_credential_requirement

            req = agent_credential_requirement(config)
            if req.required and not node_has_credential(config):
                agent_cred_hint = {
                    "credential_type": req.credential_type,
                    "accepted_types": list(req.accepted_types),
                    "label": req.label,
                }
            # Templated refs to a direct-upstream trigger in `message` break
            # at runtime (event delivery is automatic) — strip, like C3.
            stripped_trigger_refs = strip_agent_trigger_message_refs(
                config, upstream_trigger_ids or (),
            )

        # C1: Pydantic + JSX + placeholder lint, and missing required fields.
        error = validate_node_config(node_type, op, config)
        missing = missing_required_fields(node_type, operation, config)

        verdict: Dict[str, Any] = {"config_valid": error is None}
        if error:
            verdict["validation_error"] = error
        if missing:
            verdict["missing_required"] = missing
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
        if agent_cred_hint:
            verdict["agent_credential_hint"] = agent_cred_hint
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
        return verdict

    def _validate_references(
        self,
        config: Dict[str, Any],
        nodes: List[Dict[str, Any]],
        edges: List[Dict[str, Any]],
        node_id: str,
    ) -> List[Dict[str, str]]:
        """Validate node references in config values against the workflow graph.

        Handles both legacy {{nodeId.path}} references and {{ $('nodeId').field… }}
        JS expressions. For a legacy ref: node exists, is upstream, has output, and the
        path is navigable. For a `$()` expression: only its `$('id')` data sources are
        checked (exist + upstream) — the property chain is JavaScript, not a data path.
        Returns list of warning dicts (empty if all references are valid).
        """
        warnings = []
        node_ids_set = {n.get("id") for n in nodes}
        nodes_by_id = {n.get("id"): n for n in nodes}

        # BFS to find all upstream node IDs
        upstream = set()
        to_process = [node_id]
        while to_process:
            current = to_process.pop()
            for edge in edges:
                if edge.get("target") == current:
                    src = edge.get("source")
                    if src and src in node_ids_set and src not in upstream:
                        upstream.add(src)
                        to_process.append(src)

        def _check_value(field: str, value: Any):
            if isinstance(value, str):
                for match in _REFERENCE_PATTERN.finditer(value):
                    ref_path = match.group(1)

                    # A `$()` JS expression: validate only that its `$('id')` data sources
                    # exist and are upstream. The property chain (`.field.split(...)`) is
                    # JavaScript, evaluated server-side — not a navigable data path.
                    if is_js_expression(ref_path):
                        from coder.workflow.workflow_ops import (
                            _FOREIGN_ACCESSOR_RE, foreign_expression_error,
                        )
                        foreign = _FOREIGN_ACCESSOR_RE.search(ref_path)
                        if foreign:
                            warnings.append({
                                "field": field,
                                "reference": f"{{{{{ref_path}}}}}",
                                "warning": foreign_expression_error(field, foreign.group(0).strip()),
                            })
                        for expr_node_id in extract_expression_node_ids(ref_path):
                            if expr_node_id not in node_ids_set:
                                warnings.append({"field": field, "reference": f"{{{{{ref_path}}}}}", "warning": f"Referenced node '{expr_node_id}' not found in workflow"})
                            elif expr_node_id not in upstream:
                                warnings.append({"field": field, "reference": f"{{{{{ref_path}}}}}", "warning": f"Referenced node '{expr_node_id}' is not upstream of this node"})
                        continue

                    parts = ref_path.split(".")
                    ref_node_id = parts[0]
                    path_parts = parts[1:]

                    if ref_node_id not in node_ids_set:
                        warnings.append({"field": field, "reference": f"{{{{{ref_path}}}}}", "warning": f"Referenced node '{ref_node_id}' not found in workflow"})
                        continue
                    if ref_node_id not in upstream:
                        warnings.append({"field": field, "reference": f"{{{{{ref_path}}}}}", "warning": f"Referenced node '{ref_node_id}' is not upstream of this node"})
                        continue

                    ref_node = nodes_by_id.get(ref_node_id)
                    if not ref_node:
                        continue
                    _config = ref_node.get("config", {}) or {}
                    output = _config.get("output") or _config.get("mockedOutput")
                    if output is None:
                        # Skip "no output yet" warnings — they're expected during build time
                        # and produce excessive noise. Real errors (bad ID, not upstream) still fire.
                        continue

                    # Validate path through output (skip [] iteration markers)
                    if not path_parts:
                        continue
                    current = output
                    for part in path_parts:
                        if "[]" in part:
                            break  # Can't validate iteration paths statically
                        key_match = re.match(r'^([^\[]*)((?:\[\d+\])*)$', part)
                        if not key_match:
                            break
                        key_name = key_match.group(1)
                        indices_str = key_match.group(2)
                        if key_name:
                            if isinstance(current, dict) and key_name in current:
                                current = current[key_name]
                            else:
                                available = list(current.keys()) if isinstance(current, dict) else []
                                warnings.append({
                                    "field": field,
                                    "reference": f"{{{{{ref_path}}}}}",
                                    "warning": f"Key '{key_name}' not found. Available: {available}",
                                })
                                break
                        if indices_str:
                            for idx_match in re.finditer(r'\[(\d+)\]', indices_str):
                                idx = int(idx_match.group(1))
                                if isinstance(current, list) and 0 <= idx < len(current):
                                    current = current[idx]
                                else:
                                    warnings.append({
                                        "field": field,
                                        "reference": f"{{{{{ref_path}}}}}",
                                        "warning": f"Array index [{idx}] out of bounds",
                                    })
                                    break
            elif isinstance(value, dict):
                for k, v in value.items():
                    _check_value(f"{field}.{k}", v)

        for field, value in config.items():
            _check_value(field, value)

        return warnings

    # =========================================================================
    # Widget resource registration (MCP Apps)
    # =========================================================================

    def _register_docs(self):
        """Auto-register all documentation prompts and resources from the resources package."""
        from resources import list_all, list_prompts, get
        from fastmcp.resources import FunctionResource

        for entry in list_all():
            name = entry["name"]
            title = entry["title"]
            self.mcp.add_resource(FunctionResource(
                uri=f"noclick://docs/{name}",
                name=title,
                description=f"Documentation: {title}",
                mime_type="text/markdown",
                fn=lambda n=name: get(n) or "",
            ))

        for prompt_def in list_prompts():
            pname = prompt_def["name"]
            pdesc = prompt_def["description"]
            presource = prompt_def["resource"]

            @self.mcp.prompt(name=pname, description=pdesc)
            def _prompt(r=presource) -> str:
                return get(r) or "Documentation not available."

    def _register_widget_resources(self):
        """Register MCP Apps widget HTML as a resource for ChatGPT/hosts to fetch."""
        from functools import lru_cache
        from fastmcp.resources import FunctionResource

        widget_path = os.path.join(os.path.dirname(__file__), "mcp_adapter", "html_widgets", "dist", "workflow-viewer.html")

        @lru_cache(maxsize=1)
        def load_workflow_viewer() -> str:
            with open(widget_path) as f:
                return f.read()

        # Use FunctionResource (not @mcp.resource decorator) because ui:// URIs
        # get misinterpreted as URI templates by the decorator.
        resource = FunctionResource.from_function(
            fn=load_workflow_viewer,
            uri=WIDGET_WORKFLOW_VIEWER,
            name="Workflow Viewer",
            description="Visual graph of workflow nodes and edges",
            mime_type="text/html",
        )
        resource.mime_type = _MCP_APP_MIME  # bypass Pydantic semicolon rejection
        self.mcp.add_resource(resource)

    # =========================================================================
    # Widget metadata patching (MCP Apps)
    # =========================================================================

    def _patch_widget_metadata(self):
        """Patch MCP request handlers to inject widget metadata and CSP for MCP Apps hosts.

        FastMCP's low-level server registers handlers via closures, so we must
        replace them in ``_mcp_server.request_handlers`` directly.  Three handlers
        are wrapped:

        - ListToolsRequest  → adds _meta.ui.resourceUri so hosts know which widget to render
        - CallToolRequest   → copies structuredContent into _meta (hosts forward _meta to iframe)
        - ReadResourceRequest → adds CSP frameDomains so sandbox allows embedded content
        """
        from mcp import types as mcp_types
        handlers = self.mcp._mcp_server.request_handlers

        # ── ListToolsRequest: inject widget URI + CSP into tool descriptors ──
        orig_list_tools = handlers.get(mcp_types.ListToolsRequest)

        async def patched_list_tools(req: Any) -> mcp_types.ServerResult:
            result: mcp_types.ServerResult = await orig_list_tools(req)
            inner = result.root
            if hasattr(inner, "tools"):
                for tool in inner.tools:
                    if tool.name in TOOL_WIDGET_MAP:
                        tool.meta = {
                            **_WIDGET_CSP_META,
                            "ui": {
                                "resourceUri": TOOL_WIDGET_MAP[tool.name],
                                **_WIDGET_CSP_META.get("ui", {}),
                            },
                            "openai/outputTemplate": TOOL_WIDGET_MAP[tool.name],
                        }

            return result

        handlers[mcp_types.ListToolsRequest] = patched_list_tools

        # ── CallToolRequest: copy structuredContent into _meta for widget hydration ──
        orig_call_tool = handlers.get(mcp_types.CallToolRequest)

        async def patched_call_tool(req: mcp_types.CallToolRequest) -> mcp_types.ServerResult:
            tool_name = req.params.name if req.params else None

            result: mcp_types.ServerResult = await orig_call_tool(req)
            inner = result.root
            if (
                tool_name and tool_name in TOOL_WIDGET_MAP
                and getattr(inner, "structuredContent", None) is not None
                and inner.meta is None
            ):
                meta = dict(inner.structuredContent) if isinstance(inner.structuredContent, dict) else {}
                meta.update(_WIDGET_CSP_META)
                inner.meta = meta
            return result

        handlers[mcp_types.CallToolRequest] = patched_call_tool

        # ── ReadResourceRequest: inject CSP into widget resource responses ──
        orig_read_resource = handlers.get(mcp_types.ReadResourceRequest)

        async def patched_read_resource(req: mcp_types.ReadResourceRequest) -> mcp_types.ServerResult:
            result: mcp_types.ServerResult = await orig_read_resource(req)
            inner = result.root
            uri_str = str(req.params.uri) if req.params else ""
            if uri_str in _WIDGET_URIS:
                if hasattr(inner, "meta"):
                    inner.meta = _WIDGET_CSP_META
                for content in getattr(inner, "contents", []):
                    if hasattr(content, "meta"):
                        content.meta = _WIDGET_CSP_META
            return result

        handlers[mcp_types.ReadResourceRequest] = patched_read_resource
        logger.info(f"[MCP Server] Patched widget metadata for {len(TOOL_WIDGET_MAP)} tools")

    # =========================================================================
    # Feedback helpers
    # =========================================================================



    # =========================================================================
    # Tool registration
    # =========================================================================

    def _register_tools(self):
        """Register all MCP tools on the FastMCP instance."""

        # ----- Workflow CRUD -----

        @self.mcp.tool(
            name="list_workflows",
            description="List the user's workflows. Returns id, name, description, and timestamps.",
            annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
        )
        async def list_workflows(query: str = "", limit: int = 20, folder_id: str | None = None) -> ToolResult | dict:
            user_id = _user_id_var.get()
            try:
                pool = await self.get_pool()
                if not pool:
                    return {"error": "Database not available"}
                async with pool.acquire() as conn:
                    from wss.handlers.workflow_handler import get_user_org_context
                    org_id = await get_user_org_context(conn, user_id)

                    if org_id:
                        # Org context: private org workflows + shared with org + folder-shared with org
                        conditions = [
                            "((w.organization_id = $1 AND w.owner_id = $2) OR rs.id IS NOT NULL OR (rs_folder_org.id IS NOT NULL AND rs.id IS NULL))",
                            "w.deleted_at IS NULL",
                        ]
                        params: list[Any] = [uuid.UUID(org_id), uuid.UUID(user_id)]
                        idx = 3
                        join = (
                            "LEFT JOIN resource_shares rs ON rs.resource_id = w.id "
                            "AND rs.resource_type = 'workflow' "
                            "AND rs.target_type = 'organization' "
                            "AND rs.target_org_id = $1 "
                            "LEFT JOIN resource_shares rs_folder_org ON rs_folder_org.resource_id = w.folder_id "
                            "AND rs_folder_org.resource_type = 'workflow_folder' "
                            "AND rs_folder_org.target_type = 'organization' "
                            "AND rs_folder_org.target_org_id = $1"
                        )
                    else:
                        # Personal context: owned personal + directly shared + folder-shared
                        conditions = [
                            "(w.owner_id = $1 AND w.organization_id IS NULL AND rs_org.id IS NULL) OR (rs_user.id IS NOT NULL AND w.owner_id != $1) OR (rs_folder.id IS NOT NULL AND w.owner_id != $1 AND rs_user.id IS NULL)",
                            "w.deleted_at IS NULL",
                        ]
                        params = [uuid.UUID(user_id)]
                        idx = 2
                        join = (
                            "LEFT JOIN resource_shares rs_org ON rs_org.resource_id = w.id "
                            "AND rs_org.resource_type = 'workflow' "
                            "AND rs_org.target_type = 'organization' "
                            "LEFT JOIN resource_shares rs_user ON rs_user.resource_id = w.id "
                            "AND rs_user.resource_type = 'workflow' "
                            "AND rs_user.target_type = 'user' "
                            "AND rs_user.target_user_id = $1 "
                            "LEFT JOIN resource_shares rs_folder ON rs_folder.resource_id = w.folder_id "
                            "AND rs_folder.resource_type = 'workflow_folder' "
                            "AND rs_folder.target_type = 'user' "
                            "AND rs_folder.target_user_id = $1"
                        )

                    if query:
                        conditions.append(f"(w.name ILIKE ${idx} OR w.description ILIKE ${idx})")
                        params.append(f"%{query}%")
                        idx += 1

                    if folder_id is not None:
                        if folder_id == "":
                            conditions.append("w.folder_id IS NULL")
                        else:
                            conditions.append(f"w.folder_id = ${idx}")
                            params.append(uuid.UUID(folder_id))
                            idx += 1

                    params.append(limit)
                    where = " AND ".join(f"({c})" for c in conditions)

                    rows = await conn.fetch(
                        f"""SELECT DISTINCT w.id, w.name, w.description, w.folder_id,
                                   w.created_at, w.updated_at, w.organization_id
                            FROM workflows w
                            {join}
                            WHERE {where}
                            ORDER BY w.updated_at DESC LIMIT ${idx}""",
                        *params,
                    )
                    workflows = [
                        {
                            "id": str(r["id"]),
                            "name": r["name"],
                            "description": r["description"],
                            "folder_id": str(r["folder_id"]) if r["folder_id"] else None,
                            "organization_id": str(r["organization_id"]) if r["organization_id"] else None,
                            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
                        }
                        for r in rows
                    ]
                    data = {"workflows": workflows, "count": len(workflows)}
                    return data
            except Exception as e:
                logger.error(f"[MCP Server] list_workflows error: {e}", exc_info=True)
                return {"error": f"Database query failed: {e}"}

        @self.mcp.tool(
            name="get_workflow",
            description=(
                "Get full workflow details including all nodes, edges, and their configs. "
                "Use node_ids to fetch only specific nodes (reduces token usage for large workflows)."
            ),
            annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
        )
        async def get_workflow(workflow_id: str, node_ids: Optional[list[str]] = None) -> ToolResult | dict:
            user_id = _user_id_var.get()
            data, err = await self._load_workflow(user_id, workflow_id)
            if err:
                return {"error": err}

            # Also fetch name/description
            pool = await self.get_pool()
            meta = {}
            if pool:
                async with pool.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT name, description FROM workflows WHERE id = $1",
                        uuid.UUID(workflow_id),
                    )
                    if row:
                        meta = {"name": row["name"], "description": row["description"]}

            nodes = data.get("nodes", [])
            if node_ids:
                node_ids_set = set(node_ids)
                nodes = [n for n in nodes if n.get("id") in node_ids_set]

            resp: Dict[str, Any] = {
                **meta,
                "workflow_id": workflow_id,
                "workflow_xml": _workflow_to_xml(nodes, data.get("edges", [])),
            }

            # Include interface block positions if any exist
            interface_data = data.get("interface")
            if interface_data:
                layout_by_id = {item["i"]: item for item in interface_data.get("layout", [])}
                block_constraints = _get_interface_block_constraints()
                blocks_list = []
                for b in interface_data.get("blocks", []):
                    if b["id"] not in layout_by_id:
                        continue
                    lay = layout_by_id[b["id"]]
                    c = block_constraints.get(b["type"], _INTERFACE_DEFAULT_LAYOUT)
                    blocks_list.append({
                        "id": b["id"], "type": b["type"],
                        "x": lay.get("x"), "y": lay.get("y"),
                        "w": lay.get("w"), "h": lay.get("h"),
                        "minW": c.get("minW", 2), "minH": c.get("minH", 2),
                    })
                resp["interface"] = {"blocks": blocks_list}

            return self._make_visual_result(resp)

        @self.mcp.tool(
            name="create_workflow",
            description="Create a new empty workflow. Returns the new workflow's id.",
            annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False, "idempotentHint": False},
        )
        async def create_workflow(name: str, description: str = "", folder_id: str | None = None, visibility: Literal["organization", "personal"] = "organization", organization_permission: Literal["view", "edit"] = "edit") -> dict:
            user_id = _user_id_var.get()
            pool = await self.get_pool()
            if not pool:
                return {"error": "Database not available"}
            async with pool.acquire() as conn:
                from wss.handlers.workflow_handler import get_user_org_context
                org_id = await get_user_org_context(conn, user_id)

                # Check workflow limit
                from billing.plan_limits import check_workflow_limit, get_user_tier_from_db
                user_tier = await get_user_tier_from_db(conn, user_id)
                can_create, limit_error = await check_workflow_limit(conn, user_id, user_tier)
                if not can_create:
                    return {"error": limit_error}

                # Validate folder access if provided
                if folder_id:
                    has_access = await conn.fetchval(
                        "SELECT can_access_folder($1, $2)",
                        uuid.UUID(user_id), uuid.UUID(folder_id),
                    )
                    if not has_access:
                        return {"error": "Invalid folder or access denied"}

                workflow_id = await conn.fetchval(
                    """INSERT INTO workflows (name, description, owner_id, organization_id, workflow, folder_id)
                       VALUES ($1, $2, $3, $4, $5, $6) RETURNING id""",
                    name, description, uuid.UUID(user_id),
                    uuid.UUID(org_id) if org_id else None,
                    {"nodes": [], "edges": []},
                    uuid.UUID(folder_id) if folder_id else None,
                )
                wf_id_str = str(workflow_id)

                if visibility not in ("organization", "personal"):
                    return {"error": "visibility must be 'organization' or 'personal'"}
                if organization_permission not in ("view", "edit"):
                    return {"error": "organization_permission must be 'view' or 'edit'"}

                # If in org context and visibility is organization, share with the org
                if org_id and visibility == "organization":
                    await conn.execute(
                        """INSERT INTO resource_shares (resource_type, resource_id, target_type, target_org_id, permission, shared_by)
                           VALUES ('workflow', $1, 'organization', $2, $3, $4)""",
                        workflow_id, uuid.UUID(org_id), organization_permission, uuid.UUID(user_id),
                    )

            # Notify the frontend to add the workflow to the list
            from utils.event_relay import EVENT_RELAY_SECRET, broadcast_dict_to_user_safe
            event_name = "mcp:workflow:create_workflow:response"
            # organization_id + folder_id let the frontend place the card in the
            # exact scope/folder (no-op if that scope isn't loaded) instead of
            # guessing the currently-viewed scope.
            payload = {"success": True, "workflow_id": wf_id_str, "name": name, "description": description,
                       "organization_id": org_id, "folder_id": folder_id}
            if EVENT_RELAY_SECRET:
                try:
                    await broadcast_dict_to_user_safe(user_id, event_name, {"type": event_name, **payload})
                except Exception as e:
                    logger.error(f"[MCP Server] Create broadcast failed: {e}")
            else:
                from wss.receiver.receiver import get_receiver_instance
                receiver = get_receiver_instance()
                if receiver:
                    for sid in receiver.get_frontend_sids_for_user(user_id):
                        await self.sio.emit(event_name, payload, to=sid)

            return {
                "success": True,
                "workflow_id": wf_id_str,
                "name": name,
            }

        @self.mcp.tool(
            name="delete_workflow",
            description="Delete a workflow by id. This is irreversible.",
            annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False, "idempotentHint": True},
        )
        async def delete_workflow(workflow_id: str) -> dict:
            user_id = _user_id_var.get()
            pool = await self.get_pool()
            if not pool:
                return {"error": "Database not available"}
            async with pool.acquire() as conn:
                access = await check_resource_access(conn, user_id, "workflow", workflow_id)
                if access.permission != Permission.OWNER:
                    return {"error": "Only the owner can delete a workflow"}

            # Soft-delete: move to trash (30-day grace period before permanent deletion).
            # Only clean up operational resources (cron + webhooks) — preserve R2/state for restore.
            from utils.workflow_resource_manager import cleanup_workflow_operational_resources
            await cleanup_workflow_operational_resources(pool, workflow_id)

            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE workflows SET deleted_at = NOW() WHERE id = $1", uuid.UUID(workflow_id)
                )

            # Notify the frontend to remove the workflow from the list
            from utils.event_relay import EVENT_RELAY_SECRET, broadcast_dict_to_user_safe
            event_name = "mcp:workflow:delete_workflow:response"
            payload = {"success": True, "workflow_id": workflow_id, "message": "Workflow moved to trash"}
            if EVENT_RELAY_SECRET:
                try:
                    await broadcast_dict_to_user_safe(user_id, event_name, {"type": event_name, **payload})
                except Exception as e:
                    logger.error(f"[MCP Server] Delete broadcast failed: {e}")
            else:
                from wss.receiver.receiver import get_receiver_instance
                receiver = get_receiver_instance()
                if receiver:
                    for sid in receiver.get_frontend_sids_for_user(user_id):
                        await self.sio.emit(event_name, payload, to=sid)

            return payload

        @self.mcp.tool(
            name="update_workflow_metadata",
            description="Update a workflow's name and/or description.",
            annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False, "idempotentHint": True},
        )
        async def update_workflow_metadata(
            workflow_id: str, name: str | None = None, description: str | None = None
        ) -> dict:
            if name is None and description is None:
                return {"error": "Provide at least one of name or description"}
            user_id = _user_id_var.get()
            pool = await self.get_pool()
            if not pool:
                return {"error": "Database not available"}
            async with pool.acquire() as conn:
                access = await check_resource_access(conn, user_id, "workflow", workflow_id)
                if not access.has_access:
                    return {"error": "Access denied"}
                sets, vals = [], []
                if name is not None:
                    sets.append(f"name = ${len(vals)+2}")
                    vals.append(name)
                if description is not None:
                    sets.append(f"description = ${len(vals)+2}")
                    vals.append(description)
                await conn.execute(
                    f"UPDATE workflows SET {', '.join(sets)} WHERE id = $1",
                    uuid.UUID(workflow_id), *vals,
                )

            # Notify frontend
            from utils.event_relay import EVENT_RELAY_SECRET, broadcast_dict_to_user_safe
            event_name = "mcp:workflow:update_workflow_metadata:response"
            payload: dict = {"success": True, "workflow_id": workflow_id}
            if name is not None:
                payload["name"] = name
            if description is not None:
                payload["description"] = description
            if EVENT_RELAY_SECRET:
                try:
                    await broadcast_dict_to_user_safe(user_id, event_name, {"type": event_name, **payload})
                except Exception as e:
                    logger.error(f"[MCP Server] Metadata broadcast failed: {e}")
            else:
                from wss.receiver.receiver import get_receiver_instance
                receiver = get_receiver_instance()
                if receiver:
                    for sid in receiver.get_frontend_sids_for_user(user_id):
                        await self.sio.emit(event_name, payload, to=sid)

            return payload


        # ----- Node type discovery & progressive disclosure -----

        @self.mcp.tool(
            name="get_available_node_types",
            description=(
                "Returns all ~65 node types with labels (optional query filters by name). Use to BROWSE the "
                "catalog; to find the node+operation for an intent (e.g. 'post to slack'), prefer search_operations. "
                "Returns: {node_types: [{node_type, label}], count}."
            ),
            annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
        )
        async def get_available_node_types(query: str = "") -> ToolResult | dict:
            results = []
            q = query.lower()
            for node_type, node_class in NODE_REGISTRY.items():
                label = node_type.replace("automation-", "").replace("trigger-", "").replace("-", " ").title()
                if not q or q in node_type.lower() or q in label.lower():
                    results.append({"node_type": node_type, "label": label})
            data = {"node_types": results, "count": len(results)}
            return data

        @self.mcp.tool(
            name="get_node_operations",
            description=(
                "Manual fallback: enumerate ALL operations of a known node type. Prefer search_operations "
                "for intent-driven lookup, or update_workflow(include_operations=true) while building. "
                "Returns: {node_type: {operations: [{name, description, display_name?, category?}], guidance?}}."
            ),
            annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
        )
        async def get_node_operations(node_types: list[str]) -> dict:
            result = {}
            for nt in node_types:
                ops = get_operations_for_node_type(nt)
                entry: Dict[str, Any] = {"operations": [_op_to_dict(op) for op in ops]}
                guidance = _node_guidance(nt, "operations")  # I2
                if guidance:
                    entry["guidance"] = guidance
                result[nt] = entry
            return result

        @self.mcp.tool(
            name="search_operations",
            description=(
                "Search operations across node types by intent (matches name/description/"
                "display_name/category). detail_level: 'name' | 'description' (default) | 'full' "
                "(adds the config schema). Scope with node_types, or search all. Progressive "
                "disclosure over the thousands of operations without loading them all."
            ),
            annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
        )
        async def search_operations(
            query: str,
            node_types: Optional[list[str]] = None,
            detail_level: str = "description",
            limit: int = 30,
        ) -> dict:
            if detail_level not in ("name", "description", "full"):
                return {"error": "detail_level must be name|description|full"}
            types = node_types or list(NODE_REGISTRY.keys())
            q = query.lower().strip()
            matches: List[Dict[str, Any]] = []
            for nt in types:
                if nt not in NODE_REGISTRY:
                    continue
                for op in get_operations_for_node_type(nt):
                    hay = f"{op.name} {op.description} {getattr(op, 'display_name', '') or ''} {getattr(op, 'category', '') or ''}".lower()
                    if q and q not in hay:
                        continue
                    m: Dict[str, Any] = {"node_type": nt, "name": op.name}
                    if detail_level in ("description", "full"):
                        m.update({k: v for k, v in _op_to_dict(op).items() if k != "name"})
                    if detail_level == "full":
                        schema = get_operation_schema(nt, op.name)
                        if schema:
                            props, required = strip_discriminator(resolve_schema_refs(schema), nt)
                            m["schema"] = compact_schema(props, required)
                    matches.append(m)
                    if len(matches) >= limit:
                        break
                if len(matches) >= limit:
                    break
            return {"query": query, "detail_level": detail_level, "operations": matches}

        @self.mcp.tool(
            name="get_node_configs",
            description=(
                "Manual fallback: returns a node type+operation's config SCHEMA (the fields you can set) — NOT a "
                'live node\'s saved config (use get_node for that). Takes "type:operation" pairs (e.g. '
                '["automation-slack:send_message_to_channel"]). Prefer search_operations(detail_level=\'full\') for '
                "intent lookup, or update_workflow(include_configs=true) while building."
            ),
            annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
        )
        async def get_node_configs(node_types_and_ops: list[str]) -> dict:
            user_id = _user_id_var.get()
            result = {}
            for entry in node_types_and_ops:
                if ":" not in entry:
                    result[entry] = {"error": "Expected 'type:operation' format"}
                    continue
                nt, op = entry.split(":", 1)
                schema = get_operation_schema(nt, op)
                if not schema:
                    result[entry] = {"error": f"No schema found for {nt}:{op}"}
                    continue
                schema = resolve_schema_refs(schema)
                props, required = strip_discriminator(schema, nt)
                compact = compact_schema(props, required)
                entry_result: Dict[str, Any] = {
                    "operation": op,
                    "schema": compact,
                }
                # Include credential info
                cred_info = await self._get_credential_info_for_node(nt, user_id)
                if cred_info:
                    entry_result["credentials"] = cred_info
                result[entry] = entry_result
            return result

        # ----- Batch update_workflow -----

        @self.mcp.tool(
            name="update_workflow",
            description=(
                "Batch XML mutations on a workflow with optional progressive disclosure.\n\n"
                "XML tags:\n"
                '  <add_node type="..." name="alias" label="Human Readable Title" after="node-or-alias" operation="..." key="val" />\n'
                '  after= supports "node:handle" syntax for multi-output nodes, e.g. after="conditional:true" or after="iteration:loop"\n'
                '  <add_edge from="alias-or-id" to="alias-or-id" handle="source-handle-id" />\n'
                '  handle is REQUIRED for multi-output nodes (iteration: loop|done, switch: case values, conditional: true|false). '
                'Output handles are returned by include_operations and shown in get_workflow XML.\n'
                '  For iteration nodes: add a loop-back edge from the last body node TO the iteration node '
                'to mark which body node output to aggregate into collected_results. '
                'Example: <add_edge from="body-node" to="iteration-node" />\n'
                '  <add_edge from="integration-node" to="agent-node" type="tools" /> — TOOL-PROVIDER wiring: '
                "instead of dataflow, the source node's operations become callable agent tools "
                '(e.g. a linear node exposes linear__create_issue). Then set the operation allowlist: '
                '<update_config id="integration-node" agent_tool_operations=\'["create_issue","list_issues"]\' /> '
                '(operation names from include_operations; invalid names are rejected with the valid list). '
                'The agent also gets an auto-included {provider}__lookup_options tool for ID fields. '
                'Provider-wired nodes do NOT execute in the flow and cannot also feed dataflow consumers, '
                'and cannot have a trigger operation selected (either-or — use a separate node per role); '
                'they still need credentials (set_credentials) for the agent to call their tools. '
                'Use this whenever an AI agent should ACT on a service (create/update/search) rather than '
                'a fixed pipeline step. Provider edges appear as type="tools" in get_workflow XML. '
                'Rule of thumb: deterministic steps with known inputs → dataflow pipeline; open-ended '
                'instructions where the agent picks actions and arguments → provider wiring. When the '
                'request is UNDERSPECIFIED (a goal and the services involved but not the exact steps, '
                'fields, or branching), PREFER an agent with the relevant integration node(s) wired as '
                'tool providers over guessing a rigid pipeline — the agent resolves the specifics at '
                'runtime and degrades far more gracefully than a hardcoded flow built on assumptions. '
                'Keep its input minimal too: wire any trigger STRAIGHT into the agent rather than a '
                'trigger->node->...->agent chain of fetch/transform nodes — the agent fetches itself. '
                'The AGENT node\'s built-in chat (streaming, history) shows in the Interface tab by '
                'default — set show_in_interface="false" only when the user explicitly asks to hide it '
                '(the chat is also the Test Run surface), and never build a custom chat interface '
                'component. '
                'Prefer the agent node for open-ended "act on my behalf" work over a one-shot LLM '
                'integration node. The agent runs a plain LLM or a full agentic HARNESS — Claude Code/'
                'Codex/OpenCode/OpenClaw/Hermes, each a CLI agent with its own built-in tools in a '
                'sandbox — set via the agent node model; these are agent models, NOT standalone node '
                'types (there is no hermes/codex node). '
                'GitHub providers can also MOUNT repos into the agent sandbox: '
                '<update_config id="github-node" agent_sandbox_repos=\'["owner/repo"]\' /> — entries are '
                '"owner/repo" strings or {"repo": "owner/repo", "branch": "dev"} objects; each is cloned '
                'with push access at run start; the agent edits/pushes via execute_bash and opens PRs '
                'with github__create_pull_request. '
                'RARELY, when an agent must call an API that has NO NoClick node from its shell, request '
                'sandbox env vars by declaring their NAMES: '
                '<update_config id="agent-node" agent_env_requested=\'["STRIPE_KEY"]\' /> (names only — '
                'the user provides values, which become a credential you can never read). Prefer a '
                'provider or HTTP Request node; only use env vars when no node exists for the API.\n'
                '  <add_edge from="trigger-node" to="agent-node" /> — TRIGGER wiring: a trigger wired '
                "directly into an agent delivers its fired event as part of the agent's user turn "
                'automatically. Do NOT template trigger references into the agent message — it holds '
                'standing instructions; multiple triggers can feed one agent and only the fired one '
                'delivers. Channel triggers (Telegram/Slack message, alarms) also auto-supply their '
                'chat/thread id as the conversation key (per-chat history). For replies into the '
                'channel, wire the same service as a tools provider and allowlist its send operations. '
                'Trigger choice: the trigger-* nodes each create a NEW NoClick-hosted entry point '
                '(trigger-webhook a URL, trigger-email a name@noclick.app inbox, interface-form a '
                'public form, trigger-cron a schedule, trigger-run a manual button) and do NOT read the '
                "user's existing accounts. For something they already own (\"my inbox/Slack/calendar/"
                'sheet"), use that integration\'s OWN trigger operation instead (its x-is-trigger op, '
                "e.g. automation-gmail poll_for_new_emails); reserve trigger-* for a genuinely new "
                'endpoint.\n'
                '  <update_config id="alias-or-id" key="val" />\n'
                '  <update_config id="alias-or-id" field="field_name">large value</update_config>\n'
                '  <set_credentials id="alias-or-id" credential_type="credential-uuid" />\n'
                '  <disable_node id="alias-or-id" />\n'
                '  <enable_node id="alias-or-id" />\n'
                '  <mock_node id="alias-or-id" output=\'{"key":"val"}\' />\n'
                '  <mock_node id="alias-or-id">{"key":"val"}</mock_node>\n'
                '  <unmock_node id="alias-or-id" />\n'
                '  <update_settings id="alias-or-id" retryOnFail="true" maxTries="3" waitBetweenTries="1000" onError="stopWorkflow" />\n'
                '  update_settings fields: retryOnFail (true|false), maxTries (2-5), waitBetweenTries (0-5000 ms), '
                'onError (stopWorkflow|continueRegularOutput|continueErrorOutput), alwaysOutputData (true|false), '
                'executeOnce (true|false), notes (free text). All fields are optional — only provided fields are updated.\n'
                '  <patch_config id="alias-or-id" field="field_name">unified diff</patch_config>\n'
                '  patch_config format (simplified unified diff): @@ anchor_line (locates position in existing code), '
                '-old_line (remove), +new_line (add), (space)context_line (unchanged). '
                'Example: @@ function App() / -  return <div>old</div> / +  return <div>new</div>\n'
                '  <remove_edge from="..." to="..." handle="optional-handle" />\n'
                '  <remove_node id="..." />\n'
                '  <add_sticky_note name="alias" after="node-a" before="node-b" color="8">markdown content</add_sticky_note>\n'
                '  <add_sticky_note name="alias" near="node-a,node-b" direction="above" color="8">markdown content</add_sticky_note>\n'
                '  add_sticky_note positioning modes: cover (after+before spans bounding box between two nodes), '
                'near (near+direction places adjacent to node group). Anchor params are persisted so sticky notes '
                'reposition automatically when nodes move via autolayout. color=0-8 (default 8=black).\n\n'
                "Reserved attrs per tag: add_node(type, name, label, after, operation), "
                "add_edge(from, to, handle, type), remove_edge(from, to, handle), "
                "remove_node(id), update_config(id, field), set_credentials(id), "
                "disable_node(id), enable_node(id), mock_node(id, output), unmock_node(id), "
                "update_settings(id, retryOnFail, maxTries, waitBetweenTries, onError, alwaysOutputData, executeOnce, notes), "
                "patch_config(id, field), add_sticky_note(name, after, before, near, direction, color, width, height). "
                "All other attrs are config.\n\n"
                "name= on add_node is a local alias usable in from/to/after/id within the same batch.\n\n"
                "Dynamic option suffixes in update_config:\n"
                '  key__fuzzy="query" - auto-resolve dynamic field by fuzzy match (sets value if 1 match)\n'
                '  key__search="query" - preview matching options without setting value\n'
                '  key__search_limit="N" - limit search results (default 10, max 50)\n'
                '  operation__fuzzy="query" - fuzzy match operation by name or description (auto-sets if 1 match)\n\n'
                "Flags:\n"
                "- include_operations: returns available operations for each added node type (+ output_handles for multi-output nodes, + per-operation output_schema from past runs showing reference paths)\n"
                "- include_configs: returns config schemas for nodes where operation was set (includes credentials)\n"
                "- include_dynamic_options: auto-load first-level dynamic field options for touched nodes\n\n"
                "Processing order: add_node → add_edge → add_sticky_note → update_config → patch_config → set_credentials → "
                "disable/enable → mock/unmock → update_settings → resolve dynamic options → remove_edge → remove_node\n\n"
                "IMPORTANT — Sticky note best practice:\n"
                "After building or modifying a workflow, ALWAYS add covering sticky notes to label each major section. "
                "Use cover mode (after+before) with a short markdown title only (e.g. '## Data Processing'). "
                "For complex workflows, add additional nearby sticky notes with descriptive content explaining the section. "
                "This makes workflows self-documenting and easy to understand at a glance."
            ),
            annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False, "idempotentHint": False},
        )
        async def update_workflow(
            workflow_id: str,
            updates_xml: str,
            include_operations: bool = False,
            include_configs: bool = False,
            include_dynamic_options: bool = False,
            dynamic_options_limit: int = 10,
            idempotency_key: str = "",
        ) -> dict:
            # S4: dedup an at-least-once retry (client timeout → resend) so it
            # doesn't create a second copy of the graph. Per-container in-memory
            # cache keyed by (user, key); replays the prior successful result.
            ck = None
            if idempotency_key:
                from collections import OrderedDict
                cache = getattr(self, "_update_idem_cache", None)
                if cache is None:
                    cache = self._update_idem_cache = OrderedDict()
                ck = (_user_id_var.get(), idempotency_key)
                if ck in cache:
                    return {**cache[ck], "idempotent_replay": True}
            result = await self._process_update_workflow(
                workflow_id, updates_xml, include_operations, include_configs,
                include_dynamic_options, dynamic_options_limit,
            )
            if ck is not None and result.get("success"):
                cache[ck] = result
                while len(cache) > 256:
                    cache.popitem(last=False)
            return result

        @self.mcp.tool(
            name="validate_workflow",
            description=(
                "Validate a workflow WITHOUT running it (no side effects). Per node: config vs Pydantic model + "
                "JSX/placeholder lint, missing required fields, reference validity, and whether a required credential "
                "is attached. Runs the SAME checks update_workflow surfaces inline per touched node — use the inline "
                "verdict while building, and validate_workflow as the final gate before run_workflow. "
                "Returns: {nodes: [{node_id, type, operation, config_valid, validation_error?, missing_required?, "
                "reference_warnings?, credentials_missing?, credentials_disconnected?}]}. credentials_disconnected "
                "means an ATTACHED credential's provider session is dead (e.g. WhatsApp phone unlinked) — the fix is "
                "reconnecting that credential, never creating a duplicate."
            ),
            annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
        )
        async def validate_workflow(workflow_id: str, node_ids: Optional[list[str]] = None) -> dict:
            user_id = _user_id_var.get()
            data, err = await self._load_workflow(user_id, workflow_id)  # gates access
            if err:
                return {"error": err}
            nodes = data["nodes"]
            edges = data["edges"]
            want = set(node_ids) if node_ids else None
            # Provider-session health for attached credentials (whatsapp_qr etc.) —
            # an attached-but-dead credential passes every config check while the
            # node can never fire/send, so validation must call it out. The
            # extractor pre-filters to health-checked types + real UUIDs, so
            # workflows without connection-backed credentials cost zero I/O.
            # {} on provider-unreachable (unknown, never dead).
            from utils.credential_health import (
                fetch_credential_health_for_ids,
                health_relevant_credential_ids,
            )
            node_cred_ids = {
                n.get("id"): health_relevant_credential_ids(n.get("config", {}) or {})
                for n in nodes
                if not want or n.get("id") in want
            }
            all_cred_ids = list({cid for ids in node_cred_ids.values() for cid in ids})
            pool = await self.get_pool()
            cred_health = await fetch_credential_health_for_ids(pool, all_cred_ids) if pool else {}
            report = []
            for n in nodes:
                nid = n.get("id")
                if want and nid not in want:
                    continue
                node_type = n.get("type", "")
                config = n.get("config", {}) or {}
                op = self._get_current_operation(n)
                is_provider = any(
                    e.get("source") == nid and e.get("targetHandle") == "bottom" for e in edges
                )
                entry: Dict[str, Any] = {"node_id": nid, "type": node_type, "operation": op}
                # Reuse the write-path validation pass (on a shallow copy — read-only).
                verdict = self._postprocess_config(node_type, op, dict(config), is_provider=is_provider)
                entry.update(verdict or {"config_valid": True})
                ref_warnings = self._validate_references(config, nodes, edges, nid)
                if ref_warnings:
                    entry["reference_warnings"] = ref_warnings
                # Soft credential check: node's operation accepts a credential type but none attached.
                if not is_provider and node_accepted_credential_types(node_type, op, config) and not node_has_credential(config):
                    entry["credentials_missing"] = True
                dead = [
                    {"credential_id": cid, "status": cred_health[cid].status, "hint": cred_health[cid].hint}
                    for cid in node_cred_ids.get(nid, [])
                    if cid in cred_health and not cred_health[cid].healthy
                ]
                if dead:
                    entry["credentials_disconnected"] = dead
                report.append(entry)
            return {"workflow_id": workflow_id, "nodes": report}

        @self.mcp.tool(
            name="autofill_node",
            description=(
                "Auto-fill a node's operation and/or config using the internal builder's node drafting "
                "engine (goal + upstream-context driven) — offload a hard node instead of hand-authoring "
                "every field. mode: 'full' (operation+fields), 'operation', 'fields', or 'single_field' "
                "(needs target_field). Saves the result. The node's goal/label guides the fill."
            ),
            annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False, "idempotentHint": False},
        )
        async def autofill_node(
            workflow_id: str, node_id: str, mode: str = "full", target_field: str = "",
        ) -> dict:
            if mode not in ("full", "operation", "fields", "single_field"):
                return {"error": f"Invalid mode: {mode} (use full|operation|fields|single_field)"}
            if mode == "single_field" and not target_field:
                return {"error": "target_field is required when mode='single_field'"}
            user_id = _user_id_var.get()
            load_meta: Dict[str, Any] = {}
            data, err = await self._load_workflow(user_id, workflow_id, meta_out=load_meta)
            if err:
                return {"error": err}
            from coder.workflow.graph_state import GraphState
            from coder.workflow.node_drafter import create_node_drafter
            graph_state = GraphState.from_dict({**data, "workflow_id": workflow_id})
            node = graph_state.get_node(node_id)
            if not node:
                return {"error": f"Node not found: {node_id}"}
            processor = create_node_drafter(
                generation_id=str(uuid.uuid4()), debug_callback=None
            )
            processor.graph_state = graph_state
            processor.user_prompt = (
                processor.autofill_prompt(node_id, mode, target_field or None)
                or node.goal or node.label or ""
            )
            autofill_error = None
            async for event in processor.autofill_node(node_id, mode=mode, target_field=target_field or None):
                if event.type == "error":
                    autofill_error = event.data.get("error", "Autofill error")
                    break
            if autofill_error:
                return {"error": autofill_error}

            # Write back ONLY the autofilled node's config (not a whole-blob
            # overwrite), then save under the S1 concurrency guard.
            updated = graph_state.get_node(node_id)
            new_config = dict(updated.config or {})
            if updated.operation:
                new_config[get_discriminator_field(updated.type)] = updated.operation
            for n in data["nodes"]:
                if n.get("id") == node_id:
                    if isinstance(n.get("data"), dict):
                        n["data"]["config"] = new_config
                    else:
                        n["config"] = new_config
                    break
            save_err = await self._save_workflow(
                user_id, workflow_id, data, expected_updated_at=load_meta.get("updated_at"),
            )
            if save_err:
                return {"error": save_err}
            return {"success": True, "node_id": node_id, "operation": updated.operation, "config": new_config}

        # ----- Checkpoints (snapshot / rollback) -----

        @self.mcp.tool(
            name="create_checkpoint",
            description=(
                "Snapshot the current workflow as a named checkpoint you can restore later. "
                "Use before a risky batch of edits so you can roll back."
            ),
            annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False, "idempotentHint": False},
        )
        async def create_checkpoint(workflow_id: str, name: str, description: str = "") -> dict:
            user_id = _user_id_var.get()
            pool = await self.get_pool()
            if not pool:
                return {"error": "Database not available"}
            from repositories.workflow import WorkflowRepo
            from billing.plan_limits import check_checkpoint_limit, get_user_tier_from_db
            async with pool.acquire() as conn:
                access = await check_resource_access(conn, user_id, "workflow", workflow_id)
                if not access.has_access:
                    return {"error": "Access denied"}
                user_tier = await get_user_tier_from_db(conn, user_id)
                can_create, limit_error = await check_checkpoint_limit(conn, user_id, user_tier, workflow_id)
                if not can_create:
                    return {"error": limit_error}
                repo = WorkflowRepo(pool)
                wf_row = await repo.get_workflow_data(conn, workflow_id)
                if not wf_row:
                    return {"error": "Workflow not found"}
                row = await repo.create_checkpoint(
                    conn, user_id=user_id, workflow_id=workflow_id,
                    name=name, description=description, workflow_data=wf_row["workflow"] or {},
                )
            if not row:
                return {"error": "Failed to create checkpoint"}
            return {
                "checkpoint_id": str(row["id"]), "name": row["name"],
                "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
            }

        @self.mcp.tool(
            name="list_checkpoints",
            description="List a workflow's saved checkpoints (newest first) with id, name, and timestamp.",
            annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
        )
        async def list_checkpoints(workflow_id: str) -> dict:
            user_id = _user_id_var.get()
            pool = await self.get_pool()
            if not pool:
                return {"error": "Database not available"}
            async with pool.acquire() as conn:
                access = await check_resource_access(conn, user_id, "workflow", workflow_id)
                if not access.has_access:
                    return {"error": "Access denied"}
                from repositories.workflow import WorkflowRepo
                rows = await WorkflowRepo(pool).list_checkpoints(conn, workflow_id)
            return {"workflow_id": workflow_id, "checkpoints": [
                {
                    "checkpoint_id": str(r["id"]), "name": r["name"],
                    "description": r.get("description"),
                    "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                }
                for r in rows
            ]}

        @self.mcp.tool(
            name="restore_checkpoint",
            description=(
                "Restore a workflow to a saved checkpoint. Replaces the current graph and "
                "re-registers webhook/cron resources for restored nodes. Irreversible — "
                "create_checkpoint first if you might want the current state back."
            ),
            annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False, "idempotentHint": False},
        )
        async def restore_checkpoint(workflow_id: str, checkpoint_id: str) -> dict:
            user_id = _user_id_var.get()
            pool = await self.get_pool()
            if not pool:
                return {"error": "Database not available"}
            from repositories.workflow import WorkflowRepo
            from utils.workflow_resource_manager import cleanup_nodes_resources, restore_nodes_resources
            from utils.async_helpers import spawn
            repo = WorkflowRepo(pool)
            async with pool.acquire() as conn:
                access = await check_resource_access(conn, user_id, "workflow", workflow_id)
                if not access.has_access or access.permission not in (Permission.EDIT, Permission.OWNER):
                    return {"error": "You don't have permission to restore this workflow"}
                row = await repo.get_checkpoint_and_current(conn, uuid.UUID(checkpoint_id), workflow_id)
                if not row:
                    return {"error": f"Checkpoint not found: {checkpoint_id}"}
                checkpoint_workflow = row["checkpoint_workflow"] or {}
                current_workflow = row["current_workflow"] or {}
            # Diff nodes (mirrors workflow_checkpoint_handler.restore_checkpoint).
            checkpoint_nodes = checkpoint_workflow.get("nodes", [])
            current_nodes = current_workflow.get("nodes", [])
            checkpoint_ids = {n.get("id") for n in checkpoint_nodes if n.get("id")}
            current_ids = {n.get("id") for n in current_nodes if n.get("id")}
            deleted = list(current_ids - checkpoint_ids)
            restored = checkpoint_ids - current_ids
            if deleted:
                _removed = set(deleted)
                await cleanup_nodes_resources(
                    pool=pool, workflow_id=workflow_id, node_ids=deleted, background=True,
                    old_nodes=[n for n in current_nodes if n.get("id") in _removed],
                    requesting_user_id=user_id,
                )
            async with pool.acquire() as conn:
                await repo.restore_workflow_from_checkpoint(conn, workflow_id, checkpoint_workflow)
            if restored:
                spawn(
                    restore_nodes_resources(
                        pool=pool, user_id=user_id, workflow_id=workflow_id,
                        nodes=checkpoint_nodes, node_ids_to_restore=restored,
                    ),
                    name=f"mcp-checkpoint-restore:{workflow_id}",
                )
            return {
                "success": True, "workflow_id": workflow_id,
                "restored_nodes": len(restored), "deleted_nodes": len(deleted),
            }

        # ----- Interface & Skills -----

        @self.mcp.tool(
            name="validate_interface",
            description=(
                "Validate an interface node's JSX/React component headlessly (transpile + render "
                "in a server-side sandbox) and return any syntax/runtime error — no browser tab "
                "needed. Reads the node's jsx_source."
            ),
            annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
        )
        async def validate_interface(workflow_id: str, node_id: str) -> dict:
            user_id = _user_id_var.get()
            data, err = await self._load_workflow(user_id, workflow_id)
            if err:
                return {"error": err}
            node = next((n for n in data["nodes"] if n.get("id") == node_id), None)
            if not node:
                return {"error": f"Node not found: {node_id}"}
            jsx = (node.get("config", {}) or {}).get("jsx_source")
            if not jsx:
                return {"error": f"Node {node_id} has no jsx_source to validate"}
            import asyncio
            from utils.jsx_transpiler import validate_jsx_runtime
            error = await asyncio.to_thread(validate_jsx_runtime, jsx)
            return {"node_id": node_id, "valid": error is None, **({"error": error} if error else {})}

        @self.mcp.tool(
            name="list_skills",
            description=(
                "List the reusable skills (curated reference workflows + domain guidance) the "
                "user can load — building blocks the internal builder draws on. Returns id, name, "
                "description; use load_skill to get the body."
            ),
            annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
        )
        async def list_skills() -> dict:
            user_id = _user_id_var.get()
            pool = await self.get_pool()
            if not pool:
                return {"error": "Database not available"}
            from repositories.skills import SkillRepo
            skills = await SkillRepo(pool).accessible_skills(user_id, is_internal=False)
            return {"skills": [
                {"id": s.id, "name": s.name, "description": s.description} for s in skills
            ]}

        @self.mcp.tool(
            name="load_skill",
            description=(
                "Load a skill's full body (a reference workflow rendered as XML, and/or guidance "
                "text) to mimic its structure when building. Use ids from list_skills."
            ),
            annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
        )
        async def load_skill(skill_id: str) -> dict:
            user_id = _user_id_var.get()
            pool = await self.get_pool()
            if not pool:
                return {"error": "Database not available"}
            from repositories.skills import SkillRepo
            repo = SkillRepo(pool)
            accessible = await repo.accessible_skills(
                user_id, is_internal=False, include_disabled=True, include_muted=True,
            )
            if skill_id not in {s.id for s in accessible}:
                return {"error": f"Skill not found or not accessible: {skill_id}"}
            loaded = await repo.load_bodies([skill_id])
            if not loaded:
                return {"error": f"Skill not found: {skill_id}"}
            s = loaded[0]
            return {
                "id": s.id, "name": s.name, "description": s.description,
                "is_system": s.is_system, "body_text": s.body_text,
                "body_workflow": s.body_workflow,
            }

        # ----- Credentials & Dynamic Options -----

        @self.mcp.tool(
            name="search_credentials",
            description=(
                "Search the user's credentials. Returns matching credentials with id, name, type, and metadata. "
                "Use to find credentials when configuring nodes that require authentication."
            ),
            annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
        )
        async def search_credentials(
            credential_type: str = "",
            query: str = "",
            limit: int = 20,
        ) -> list[dict]:
            user_id = _user_id_var.get()
            pool = await self.get_pool()
            if not pool:
                return [{"error": "Database not available"}]
            async with pool.acquire() as conn:
                from wss.handlers.workflow_handler import get_user_org_context
                org_id = await get_user_org_context(conn, user_id)

                # Build query with optional filters
                conditions = [
                    "(c.owner_id = $1 OR us.id IS NOT NULL OR ($2::uuid IS NOT NULL AND os.id IS NOT NULL))"
                ]
                params: list = [user_id, org_id]
                idx = 3

                if credential_type:
                    conditions.append(f"c.credential_type = ${idx}")
                    params.append(credential_type)
                    idx += 1

                if query:
                    conditions.append(
                        f"(c.name ILIKE ${idx} OR c.metadata->>'email' ILIKE ${idx})"
                    )
                    params.append(f"%{query}%")
                    idx += 1

                limit = min(limit, 50)

                sql = f"""
                    SELECT DISTINCT ON (c.id) c.id, c.name, c.credential_type, c.metadata
                    FROM credentials c
                    LEFT JOIN resource_shares us
                        ON us.resource_type = 'credential' AND us.resource_id = c.id
                        AND us.target_type = 'user' AND us.target_user_id = $1
                    LEFT JOIN resource_shares os
                        ON os.resource_type = 'credential' AND os.resource_id = c.id
                        AND os.target_type = 'organization' AND os.target_org_id = $2
                    WHERE {' AND '.join(conditions)}
                    ORDER BY c.id, c.created_at DESC
                    LIMIT {limit}
                """
                rows = await conn.fetch(sql, *params)
            # Provider-session health for connection-backed rows — the picker's
            # same enrichment. Without it the agent's documented path
            # (search_credentials → attach) sees a dead WhatsApp credential as
            # healthy. Zero I/O when no row has a health-checked type.
            from utils.credential_health import get_credential_health
            health = await get_credential_health([dict(r) for r in rows])
            return [
                {
                    "id": str(r["id"]),
                    "name": r["name"],
                    "credential_type": r["credential_type"],
                    "metadata": r["metadata"] or {},
                    **(
                        {"connection_status": health[str(r["id"])].status}
                        if str(r["id"]) in health else {}
                    ),
                }
                for r in rows
            ]

        @self.mcp.tool(
            name="connect_credential",
            description=(
                "Get a link the user opens to CONNECT a credential (OAuth or API key) for a node type or credential "
                "type. Returns {connect_url, credential_type, ...}. NOTE: the credential is NOT live until the user "
                "finishes the flow at that link — re-check with search_credentials afterward before attaching it. Use "
                "when a node needs a credential the user hasn't connected yet (search_credentials returns none / "
                "credential_requests surfaced)."
            ),
            annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
        )
        async def connect_credential(node_type: str = "", credential_type: str = "") -> dict:
            user_id = _user_id_var.get()
            cred_type = credential_type or (_get_credential_type_for_node(node_type) if node_type else None)
            if not cred_type:
                return {"error": "Provide a credential_type, or a node_type that requires credentials."}
            pool = await self.get_pool()
            if not pool:
                return {"error": "Database not available"}
            from repositories.users import get_user_email
            async with pool.acquire() as conn:
                email = await get_user_email(conn, uuid.UUID(user_id))
            if not email:
                return {"error": "Could not resolve your account email to anchor the connect request."}
            from repositories.credentials import CredentialsRepo
            from utils.email import credential_provide_url
            req = await CredentialsRepo(pool).upsert_credential_request(
                requester_id=user_id, target_email=email,
                credential_type=cred_type, message="Connect requested via MCP",
            )
            if not req or not req.token:
                return {"error": "Failed to create credential request"}
            result: Dict[str, Any] = {
                "credential_type": cred_type,
                "connect_url": credential_provide_url(req.token),
            }
            from utils.credential_health import CREDENTIAL_HEALTH_CHECKS, get_credential_health
            if cred_type in CREDENTIAL_HEALTH_CHECKS:
                # Reconnect-not-remint for connection-backed credentials: the QR
                # finalize rebinds a scan of an already-credentialed phone to its
                # EXISTING credential, so an agent must never treat a dead
                # credential as a reason to collect a second one (dup credentials
                # stacked device links until WhatsApp logged them all out).
                async with pool.acquire() as conn:
                    existing = [
                        dict(r)  # asyncpg Records aren't attribute-accessible for the health seam
                        for r in await conn.fetch(
                            """SELECT id, name, credential_type, metadata FROM credentials
                               WHERE owner_id = $1::uuid AND credential_type = $2""",
                            user_id, cred_type,
                        )
                    ]
                if existing:
                    health = await get_credential_health(existing)
                    result["existing_credentials"] = [
                        {
                            "credential_id": str(r["id"]),
                            "name": r["name"],
                            "connection_status": h.status if (h := health.get(str(r["id"]))) else "unknown",
                        }
                        for r in existing
                    ]
                    result["note"] = (
                        "This user already has credential(s) of this type. Reconnecting the "
                        "SAME account at connect_url repairs the existing credential in place "
                        "(same credential_id — re-check with search_credentials); it never "
                        "creates a duplicate."
                    )
            if node_type:
                result["is_oauth"] = _is_oauth_credential(node_type)
                result.update(_credential_schema_meta(node_type))
            return result

        @self.mcp.tool(
            name="list_credential_requests",
            description=(
                "Poll the status of connect_credential requests you've minted. Use after handing the user a "
                "connect_url to see when they finished — a 'fulfilled' request carries the resulting credential_id "
                "you can then attach via set_credentials. "
                "Returns: {requests: [{id, credential_type, target_email, status (pending|fulfilled|cancelled), "
                "credential_id, created_at, fulfilled_at, expires_at}]}. Filter with status."
            ),
            annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
        )
        async def list_credential_requests(status: str = "") -> dict:
            user_id = _user_id_var.get()
            pool = await self.get_pool()
            if not pool:
                return {"error": "Database not available"}
            from repositories.credentials import CredentialsRepo
            rows = await CredentialsRepo(pool).list_credential_requests(user_id)
            requests = [
                {
                    "id": r.id,
                    "credential_type": r.credential_type,
                    "target_email": r.target_email,
                    "status": r.status,
                    "credential_id": r.credential_id,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "fulfilled_at": r.fulfilled_at.isoformat() if r.fulfilled_at else None,
                    "expires_at": r.expires_at.isoformat() if r.expires_at else None,
                }
                for r in rows
                if not status or r.status == status
            ]
            return {"requests": requests}

        @self.mcp.tool(
            name="load_options",
            description=(
                "Load dynamic dropdown options for a node field (e.g. list spreadsheets, sheets, channels). "
                "Requires a credential_id for authenticated nodes. Use context for dependent fields "
                "(e.g. pass spreadsheet_id to load sheet names)."
            ),
            annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
        )
        async def load_options(
            node_type: str,
            field_name: str,
            credential_id: str = "",
            context: Optional[dict] = None,
            page_token: str = "",
        ) -> dict:
            user_id = _user_id_var.get()

            node_class = NODE_REGISTRY.get(node_type)
            if not node_class:
                return {"error": f"Unknown node type: {node_type}"}
            if not hasattr(node_class, 'load_field_options'):
                return {"error": f"Node type {node_type} does not support dynamic options"}

            # Allow credential-less dynamic options (e.g., dataset resource picker)
            if credential_id:
                pool = await self.get_pool()
                cred_data = await get_credential(credential_id, user_id, pool=pool)
                if not cred_data:
                    return {"error": f"Credential not found or access denied: {credential_id}"}
            else:
                cred_data = {}

            try:
                result = await self._load_dynamic_options_for_field(
                    node_type, field_name, cred_data,
                    context=context, page_token=page_token or None,
                    user_id=user_id, credential_id=credential_id or None,
                )
                return result
            except Exception as e:
                logger.error(f"[MCP Server] load_options error: {e}", exc_info=True)
                return {"error": str(e)}

        @self.mcp.tool(
            name="load_value",
            description=(
                "Fetch a node's LIVE computed field — the info the config panel shows that is NOT stored in config: "
                "webhook_url (webhook/trigger), active_alarms (alarm node's scheduled-alarm list), file_browser "
                "(filesystem node's file list), cron next_run, etc. Call with field_name='' to list what "
                "THIS node can load. Returns {value|values} (the field's native shape). NOTE: some fields "
                "provision on load — for example, webhook_url registers the endpoint — so this is "
                "idempotent but not always a pure read."
            ),
            annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False, "idempotentHint": True},
        )
        async def load_value(
            workflow_id: str,
            node_id: str,
            field_name: str = "",
            context: Optional[dict] = None,
        ) -> dict:
            user_id = _user_id_var.get()
            data, err = await self._load_workflow(user_id, workflow_id)  # gates access
            if err:
                return {"error": err}
            node = next((n for n in data["nodes"] if n.get("id") == node_id), None)
            if not node:
                return {"error": f"Node not found: {node_id}"}
            node_type = node.get("type", "")
            node_class = NODE_REGISTRY.get(node_type)
            if not node_class:
                return {"error": f"Unknown node type: {node_type}"}

            # Discovery: no field_name → describe what this node can load.
            if not field_name:
                return {"node_type": node_type, "loadable_fields": _loadable_fields(node_type)}

            config = node.get("config", {}) or {}
            merged_context = {**config, **(context or {})}  # caller context overrides config
            pool = await self.get_pool()
            try:
                # Priority 1: the node's own load_field_value (alarm/filesystem/mcp-server/…).
                if hasattr(node_class, "load_field_value"):
                    result = await node_class.load_field_value(
                        field_name=field_name, user_id=user_id,
                        workflow_id=uuid.UUID(workflow_id), node_id=node_id, pool=pool,
                        context=merged_context, credential_ids=config.get("credentialIds"),
                    )
                    if isinstance(result, dict) and "values" in result:
                        return {"values": result["values"]}
                    if isinstance(result, dict) and "value" in result:
                        return {"value": result["value"]}
                    return {"value": result}

                # Priority 2: generic webhook field for nodes without a custom loader.
                from utils.webhook_manager import WebhookManager
                op_schema = get_operation_schema(node_type, self._get_current_operation(node))
                webhook_field = WebhookManager.get_webhook_field(resolve_schema_refs(op_schema)) if op_schema else None
                if webhook_field and field_name == webhook_field:
                    return {"values": await WebhookManager.get_or_create_webhook(
                        pool=pool, user_id=user_id, workflow_id=uuid.UUID(workflow_id), node_id=node_id,
                    )}

                return {"error": (
                    f"'{node_type}' has no computed field '{field_name}'. "
                    "Call load_value(field_name='') to see this node's loadable fields."
                )}
            except Exception as e:
                logger.error(f"[MCP Server] load_value error: {e}", exc_info=True)
                return {"error": str(e)}

        # ----- Execution & Debugging -----

        @self.mcp.tool(
            name="run_workflow",
            description=(
                "Execute a workflow. Run validate_workflow first to catch build errors. "
                "SIDE EFFECTS: this really runs every node — sends, external writes, payments, deletes. "
                "Do NOT run write/send/payment nodes without explicit user approval. "
                "Returns {execution_id, status, node_results, node_states (terminal status/error per node)}; "
                "fetch full authoritative outputs with get_node_output, inspect agent-node actions with list_tool_calls. "
                "Pass inputs={...} to simulate a form submission / webhook body (injected as the trigger node's output). "
                "Set return_output=true for full node outputs instead of truncated previews."
            ),
            annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": True, "idempotentHint": False},
        )
        async def run_workflow(
            workflow_id: str,
            inputs: Optional[dict] = None,
            return_output: bool = False,
        ) -> ToolResult | dict:
            user_id = _user_id_var.get()
            data, err = await self._load_workflow(user_id, workflow_id)
            if err:
                return {"error": err}

            try:
                from wss.receiver.receiver import get_receiver_instance
                from wss.receiver.event_routing import Handler
                from wss.receiver.client_events import WorkflowExecuteRequest

                receiver = get_receiver_instance()
                if not receiver:
                    return {"error": "Backend receiver not available"}

                handler = receiver.handler_instances.get(Handler.WORKFLOW_EXECUTION)
                if not handler:
                    return {"error": "Workflow execution handler not available"}

                # Prepare nodes for execution
                exec_nodes = []
                for node in data.get("nodes", []):
                    _config = node.get("config", {}) or {}
                    exec_node = {
                        "id": node["id"],
                        "type": node["type"],
                        "config": _config,
                    }
                    if _config.get("mockedOutput"):
                        exec_node["config"]["mockedOutput"] = _config["mockedOutput"]
                    if _config.get("disabled"):
                        exec_node["config"]["disabled"] = _config["disabled"]
                    exec_nodes.append(exec_node)

                exec_edges = [
                    {"id": e["id"], "source": e["source"], "target": e["target"],
                     "sourceHandle": e.get("sourceHandle"), "targetHandle": e.get("targetHandle")}
                    for e in data.get("edges", [])
                ]

                request = WorkflowExecuteRequest(
                    workflow_id=workflow_id,
                    nodes=exec_nodes,
                    edges=exec_edges,
                    trigger_source="mcp",
                    inputs=inputs,  # E7: injected as the trigger node's output
                )

                # Await execution directly (don't pass execution_id — let handler create DB record).
                # Tag as 'mcp_execute' so AI-builder runs are distinguishable from user-clicked Run
                # in oauth.refresh spans / operator refresh audit.
                from nodes.core.oauth_audit import caller_path_scope
                with caller_path_scope("mcp_execute"):
                    run_result = await handler.handle_execute(
                        sid=f"mcp:{user_id}",
                        request=request,
                        caller_user_id=user_id,
                    )

                # E2: build node_results from the FRESH in-memory outputs the run
                # returned, not the dead post-CAS JSONB config.output blob (which
                # is empty for modern workflows).
                node_types = {n["id"]: n.get("type", "unknown") for n in data.get("nodes", [])}
                node_results: Dict[str, Any] = {}
                for nid, out in (run_result.node_outputs if run_result else {}).items():
                    if out is None:
                        continue
                    entry: Dict[str, Any] = {"type": node_types.get(nid, "unknown")}
                    if return_output:
                        entry["output"] = out
                    else:
                        out_str = json.dumps(out) if not isinstance(out, str) else out
                        entry["output_preview"] = out_str[:500] + "..." if len(out_str) > 500 else out_str
                    node_results[nid] = entry

                result: Dict[str, Any] = {
                    "success": bool(run_result.success) if run_result else True,
                    "workflow_id": workflow_id,
                }
                if run_result:
                    result["execution_id"] = run_result.execution_id
                    result["status"] = "error" if not run_result.success else "completed"
                    result["error"] = run_result.error
                    result["nodes_executed"] = run_result.nodes_executed
                if node_results:
                    result["node_results"] = node_results
                # E3: per-node terminal status/error map.
                node_states = await self._read_node_states(workflow_id)
                if node_states:
                    result["node_states"] = node_states

                return result

            except Exception as e:
                logger.error(f"[MCP Server] Error running workflow: {e}", exc_info=True)
                return {"error": str(e)}

        @self.mcp.tool(
            name="run_nodes",
            description=(
                "Run specific nodes in a workflow for testing. Predecessor nodes are auto-mocked from their last "
                "output (missing upstream outputs resolve empty, not an error). Nodes run sequentially in order. "
                "SIDE EFFECTS: the target node really executes — don't run write/send/payment nodes without user "
                "approval. A node wired into an agent (tool-provider) returns its tool metadata, not an execution. "
                "Returns [{node_id, type, success, status: success|error|empty, output|error}] plus a node_states map; "
                "set return_output=true for full output instead of a truncated preview (or fetch it via get_node_output)."
            ),
            annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": True, "idempotentHint": False},
        )
        async def run_nodes(workflow_id: str, node_ids: list[str], return_output: bool = False) -> dict:
            user_id = _user_id_var.get()
            data, err = await self._load_workflow(user_id, workflow_id)
            if err:
                return {"error": err}

            try:
                from wss.receiver.receiver import get_receiver_instance
                from wss.receiver.event_routing import Handler
                from wss.receiver.client_events import WorkflowExecuteRequest

                receiver = get_receiver_instance()
                if not receiver:
                    return {"error": "Backend receiver not available"}

                handler = receiver.handler_instances.get(Handler.WORKFLOW_EXECUTION)
                if not handler:
                    return {"error": "Workflow execution handler not available"}

                mcp_handler = receiver.handler_instances.get(Handler.WORKFLOW_MCP)

                nodes = data.get("nodes", [])
                edges = data.get("edges", [])
                nodes_by_id = {n.get("id"): n for n in nodes}
                all_node_ids = set(nodes_by_id.keys())

                results = []

                for node_id in node_ids:
                    target_node = nodes_by_id.get(node_id)
                    if not target_node:
                        results.append({"node_id": node_id, "success": False, "error": f"Node not found: {node_id}"})
                        continue

                    # A node wired to an agent's bottom handle is a TOOL
                    # PROVIDER — running it means publishing its provider
                    # output, never executing an operation. Check against the
                    # FULL workflow graph (the execution subset below excludes
                    # the downstream agent, which would make the canvas-run
                    # short-circuit in _execute_node miss and execute whatever
                    # stale config.operation the node carries, for real).
                    from nodes.agent.node_op_tools import is_node_op_provider, build_provider_output
                    if is_node_op_provider(node_id, target_node.get("type", ""), nodes, edges):
                        provider_output = build_provider_output(
                            target_node.get("type", ""), target_node.get("config", {}) or {}
                        )
                        if provider_output.get("credential_id"):
                            _prov_pool = await self.get_pool()
                            if _prov_pool:
                                from utils.credentials import get_credential_name
                                provider_output["credential_label"] = await get_credential_name(
                                    _prov_pool, provider_output["credential_id"]
                                )
                        results.append({
                            "node_id": node_id,
                            "success": True,
                            "output": provider_output,
                        })
                        continue

                    # Find predecessors using MCP handler's BFS method
                    if mcp_handler and hasattr(mcp_handler, '_find_predecessors'):
                        predecessor_ids = mcp_handler._find_predecessors(node_id, edges, all_node_ids)
                    else:
                        predecessor_ids = set()

                    # Build mocked predecessor nodes + unmocked target
                    execution_nodes = []
                    missing_outputs = []

                    _pool = await self.get_pool()

                    for pred_id in predecessor_ids:
                        pred_node = nodes_by_id.get(pred_id)
                        if not pred_node:
                            continue
                        _config = pred_node.get("config", {}) or {}
                        output = _config.get("mockedOutput") or _config.get("output")
                        # Try dedicated node_outputs table if JSONB has no output
                        if output is None and _pool:
                            try:
                                from utils.node_outputs import latest_output
                                table_output = await latest_output(_pool, workflow_id, pred_id)
                                if table_output is not None:
                                    output = table_output
                            except Exception:
                                pass
                        if output is None:
                            missing_outputs.append(pred_id)
                        else:
                            pred_config = dict(_config)
                            pred_config["mockedOutput"] = output
                            execution_nodes.append({
                                "id": pred_id,
                                "type": pred_node.get("type", "unknown"),
                                "config": pred_config,
                            })

                    # E5: don't hard-fail on missing predecessor outputs — run the
                    # target with whatever upstream outputs exist (references to
                    # the missing ones resolve empty), matching the builder's
                    # run-from-here tolerance.
                    if missing_outputs:
                        logger.debug(
                            f"[MCP] run_nodes {node_id}: predecessors {missing_outputs} have no "
                            "cached output — running with empty references"
                        )

                    # Add target node (executes normally, no mock)
                    _target_config = target_node.get("config", {}) or {}
                    target_config = dict(_target_config)
                    if _target_config.get("disabled"):
                        target_config["disabled"] = True

                    execution_nodes.append({
                        "id": node_id,
                        "type": target_node.get("type", "unknown"),
                        "config": target_config,
                    })

                    # Build edge subset
                    execution_node_ids = {n["id"] for n in execution_nodes}
                    execution_edges = [
                        e for e in edges
                        if e.get("source") in execution_node_ids and e.get("target") in execution_node_ids
                    ]

                    request = WorkflowExecuteRequest(
                        workflow_id=workflow_id,
                        nodes=execution_nodes,
                        edges=execution_edges,
                        trigger_source="mcp",
                    )

                    # Await execution directly. Tag as 'mcp_execute' so AI-builder runs
                    # are distinguishable from user-clicked Run.
                    from nodes.core.oauth_audit import caller_path_scope
                    with caller_path_scope("mcp_execute"):
                        run_result = await handler.handle_execute(
                            sid=f"mcp:{user_id}",
                            request=request,
                            caller_user_id=user_id,
                        )

                    # E1: prefer the FRESH in-memory output from the run result
                    # (race-free) over re-reading the CAS store, which is written
                    # by a not-yet-awaited background persist task.
                    output = run_result.node_outputs.get(node_id) if run_result else None
                    if output is None and _pool:
                        try:
                            from utils.node_outputs import latest_output
                            output = await latest_output(_pool, workflow_id, node_id)
                        except Exception:
                            pass

                    # Reload workflow data (also needed to update local cache for subsequent iterations)
                    refreshed_data, _ = await self._load_workflow(user_id, workflow_id)
                    if refreshed_data:
                        data = refreshed_data
                        nodes = data.get("nodes", [])
                        nodes_by_id = {n.get("id"): n for n in nodes}

                        # Fall back to JSONB if fresh output + table had none
                        if output is None:
                            refreshed_node = nodes_by_id.get(node_id)
                            if refreshed_node:
                                output = (refreshed_node.get("config", {}) or {}).get("output")

                    node_type = target_node.get("type", "unknown")
                    if output is not None:
                        if not return_output:
                            output_str = json.dumps(output) if not isinstance(output, str) else output
                            output = output_str[:500] + "..." if len(output_str) > 500 else output_str
                        results.append({
                            "node_id": node_id, "type": node_type,
                            "success": True, "status": "success", "output": output,
                        })
                        continue

                    # E3: no output — distinguish a genuine failure from an
                    # empty-but-successful run instead of reporting success:true/None.
                    run_err = run_result.error if (run_result and not run_result.success) else None
                    if not run_err:
                        _, exec_record = await self._collect_node_results(workflow_id, user_id, node_ids={node_id})
                        run_err = exec_record.get("error") if exec_record else None
                    if run_err:
                        results.append({
                            "node_id": node_id, "type": node_type,
                            "success": False, "status": "error", "error": run_err,
                        })
                    else:
                        results.append({
                            "node_id": node_id, "type": node_type,
                            "success": True, "status": "empty", "output": None,
                        })

                response: Dict[str, Any] = {"workflow_id": workflow_id, "results": results}
                # E3: per-node terminal status/error map (best-effort; the same
                # source that drives the canvas chips).
                node_states = await self._read_node_states(workflow_id)
                if node_states:
                    response["node_states"] = node_states
                return response

            except Exception as e:
                logger.error(f"[MCP Server] Error running nodes: {e}", exc_info=True)
                return {"error": str(e)}

        @self.mcp.tool(
            name="get_execution_status",
            description=(
                "Look up ONE run by execution_id when you don't have its workflow_id; otherwise use list_executions. "
                "Returns: {execution_id, workflow_id, status, started_at, finished_at, nodes_executed, error, trigger_source}."
            ),
            annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
        )
        async def get_execution_status(execution_id: str) -> ToolResult | dict:
            user_id = _user_id_var.get()
            pool = await self.get_pool()
            if not pool:
                return {"error": "Database not available"}
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """SELECT id, workflow_id, status, started_at, finished_at,
                              nodes_executed, error, trigger_source
                       FROM workflow_executions WHERE id = $1""",
                    uuid.UUID(execution_id),
                )
                if not row:
                    return {"error": f"Execution not found: {execution_id}"}

                # Verify user has access to the workflow
                access = await check_resource_access(
                    conn, user_id, "workflow", str(row["workflow_id"])
                )
                if not access.has_access:
                    return {"error": "Access denied"}

                result = {
                    "execution_id": str(row["id"]),
                    "workflow_id": str(row["workflow_id"]),
                    "status": row["status"],
                    "started_at": row["started_at"].isoformat() if row["started_at"] else None,
                    "finished_at": row["finished_at"].isoformat() if row["finished_at"] else None,
                    "nodes_executed": row["nodes_executed"],
                    "error": row["error"],
                    "trigger_source": row["trigger_source"],
                }
                return result

        @self.mcp.tool(
            name="list_executions",
            description=(
                "List recent executions of a workflow (newest first): execution_id, status, "
                "trigger_source, timing, nodes_executed, error. Filter by status and/or "
                "trigger_source (manual|webhook|cron|mcp|api), or search the error text. "
                "Use to find triggered/scheduled/failed runs and their execution_ids."
            ),
            annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
        )
        async def list_executions(
            workflow_id: str,
            status: Optional[list[Literal["running", "completed", "error", "awaiting_approval", "awaiting_delay"]]] = None,
            trigger_source: Optional[list[Literal["manual", "webhook", "cron", "mcp", "api", "email", "agent_turn"]]] = None,
            search: str = "",
            after: str = "",
            before: str = "",
            limit: int = 20,
        ) -> dict:
            user_id = _user_id_var.get()
            pool = await self.get_pool()
            if not pool:
                return {"error": "Database not available"}
            from datetime import datetime
            def _parse_ts(s: str):
                if not s:
                    return None
                try:
                    return datetime.fromisoformat(s.replace("Z", "+00:00"))
                except ValueError:
                    return None
            async with pool.acquire() as conn:
                access = await check_resource_access(conn, user_id, "workflow", workflow_id)
                if not access.has_access:
                    return {"error": "Access denied"}
                from repositories.workflow import WorkflowRepo
                rows = await WorkflowRepo(pool).list_executions(
                    conn,
                    workflow_id=workflow_id,
                    status_filter=status or None,
                    trigger_filter=trigger_source or None,
                    search=search or None,
                    cursor_ts=None, cursor_id=None,
                    limit=min(limit, 200),
                    from_ts=_parse_ts(after),  # L6
                    to_ts=_parse_ts(before),
                )

            def _iso(v):
                return v.isoformat() if hasattr(v, "isoformat") else v
            return {"workflow_id": workflow_id, "executions": [
                {
                    "execution_id": str(r["id"]),
                    "status": r["status"],
                    "trigger_source": r.get("trigger_source"),
                    "started_at": _iso(r.get("started_at")),
                    "finished_at": _iso(r.get("finished_at")),
                    "nodes_executed": r.get("nodes_executed"),
                    "error": r.get("error"),
                }
                for r in rows
            ]}

        @self.mcp.tool(
            name="get_node_statuses",
            description=(
                "Get the latest terminal status (completed/error/skipped) + error per node for a workflow — the "
                "same per-node status that drives the canvas chips. run_workflow/run_nodes already include this "
                "node_states map in their response, so use this to re-fetch WITHOUT re-running. "
                "Returns: {node_states: {node_id: {status, error, finishedAt}}}."
            ),
            annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
        )
        async def get_node_statuses(workflow_id: str) -> dict:
            user_id = _user_id_var.get()
            data, err = await self._load_workflow(user_id, workflow_id)  # gates access
            if err:
                return {"error": err}
            return {"workflow_id": workflow_id, "node_states": await self._read_node_states(workflow_id)}

        @self.mcp.tool(
            name="list_tool_calls",
            description=(
                "List the agent tool calls made during a workflow execution: tool_name, "
                "operation, provider node, arguments, result_status, error, duration_ms, "
                "created_at. Use to debug what an AI agent node did during a run."
            ),
            annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
        )
        async def list_tool_calls(execution_id: str) -> dict:
            user_id = _user_id_var.get()
            pool = await self.get_pool()
            if not pool:
                return {"error": "Database not available"}
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT workflow_id FROM workflow_executions WHERE id = $1",
                    uuid.UUID(execution_id),
                )
                if not row:
                    return {"error": f"Execution not found: {execution_id}"}
                access = await check_resource_access(conn, user_id, "workflow", str(row["workflow_id"]))
                if not access.has_access:
                    return {"error": "Access denied"}
                from repositories.workflow import WorkflowRepo
                calls = await WorkflowRepo(pool).list_tool_calls_for_execution(conn, uuid.UUID(execution_id))

            def _ser(c):
                return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in c.items()}
            return {"execution_id": execution_id, "tool_calls": [_ser(c) for c in calls]}

        @self.mcp.tool(
            name="get_health",
            description=(
                "Self-test the MCP server: reports whether the DB pool and execution receiver are reachable. "
                "Use to distinguish a backend/infra problem from a bad-input error. "
                "Returns: {status: healthy|degraded, checks: {database, receiver}}."
            ),
            annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
        )
        async def get_health() -> dict:
            checks: Dict[str, Any] = {}
            try:
                pool = await self.get_pool()
                if pool:
                    async with pool.acquire() as conn:
                        await conn.fetchval("SELECT 1")
                    checks["database"] = "ok"
                else:
                    checks["database"] = "unavailable"
            except Exception as e:
                checks["database"] = f"error: {e}"
            try:
                from wss.receiver.receiver import get_receiver_instance
                checks["receiver"] = "ok" if get_receiver_instance() else "unavailable"
            except Exception as e:
                checks["receiver"] = f"error: {e}"
            healthy = all(v == "ok" for v in checks.values())
            return {"status": "healthy" if healthy else "degraded", "checks": checks}

        @self.mcp.tool(
            name="get_node_output",
            description=(
                "Get node outputs in a workflow (batch: pass multiple node_ids). By default returns each node's "
                "LATEST output; pass execution_id to fetch a SPECIFIC past run's output instead. "
                "Returns: {node_id: {output, has_mock, execution_id?}} — output is null when the node has no output "
                "for that run/latest."
            ),
            annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
        )
        async def get_node_output(workflow_id: str, node_ids: list[str], execution_id: str = "") -> dict:
            user_id = _user_id_var.get()
            data, err = await self._load_workflow(user_id, workflow_id)  # gates access
            if err:
                return {"error": err}

            ids = set(node_ids)
            pool = await self.get_pool()
            results: Dict[str, Any] = {}
            if execution_id:
                # L1: a SPECIFIC past run's output, not just the latest. Keep the
                # return shape identical to the latest branch (output + has_mock).
                from utils.cas.store import read_node_output
                valid_ids = {n.get("id") for n in data["nodes"]}
                for nid in ids:
                    if nid not in valid_ids:
                        continue
                    try:
                        output = await read_node_output(
                            pool, execution_id=execution_id, node_id=nid, workflow_id=workflow_id,
                        )
                    except Exception as e:
                        logger.debug(f"[MCP] read_node_output failed for {nid}@{execution_id}: {e}")
                        output = None
                    results[nid] = {"output": output, "has_mock": False, "execution_id": execution_id}
            else:
                for n in data["nodes"]:
                    nid = n.get("id")
                    if nid in ids:
                        output, is_mocked = await self._resolve_node_output(n, workflow_id, nid, pool)
                        results[nid] = {"output": output, "has_mock": is_mocked}
            if not results:
                return {"error": f"Node(s) not found: {', '.join(ids)}"}
            return results

        @self.mcp.tool(
            name="get_node_output_history",
            description=(
                "Get the last N outputs of a SINGLE node (node_id, not a list) ACROSS executions, newest first — "
                "vs get_node_output which reads many nodes for ONE run. Use to compare a node's output over time or "
                "find a past run. Returns: {history: [{execution_id, created_at, output}]}."
            ),
            annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
        )
        async def get_node_output_history(workflow_id: str, node_id: str, limit: int = 20) -> dict:
            user_id = _user_id_var.get()
            data, err = await self._load_workflow(user_id, workflow_id)  # gates access
            if err:
                return {"error": err}
            pool = await self.get_pool()
            if not pool:
                return {"error": "Database not available"}
            from utils.cas.store import read_node_output_history
            history = await read_node_output_history(pool, workflow_id, node_id, limit=min(limit, 50))
            return {"workflow_id": workflow_id, "node_id": node_id, "history": history}

        @self.mcp.tool(
            name="get_node",
            description=(
                "Get how node(s) are SET UP — config + type + handles (plus latest output/has_mock) — without "
                "loading the whole workflow. For just a node's output, prefer the leaner get_node_output. "
                "Returns: {node_id: {type, config, output, disabled, has_mock, output_handles?}}."
            ),
            annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
        )
        async def get_node(workflow_id: str, node_ids: list[str]) -> dict:
            user_id = _user_id_var.get()
            data, err = await self._load_workflow(user_id, workflow_id)
            if err:
                return {"error": err}

            ids = set(node_ids)
            results = {}
            pool = await self.get_pool()
            for n in data["nodes"]:
                nid = n.get("id")
                if nid in ids:
                    _config = n.get("config", {}) or {}
                    output, is_mocked = await self._resolve_node_output(n, workflow_id, nid, pool)

                    result = {
                        "type": n.get("type"),
                        "config": _config,
                        "output": output,
                        "disabled": _config.get("disabled", False),
                        "has_mock": is_mocked,
                    }
                    node_class = NODE_REGISTRY.get(n.get("type"))
                    if node_class:
                        handles = node_class.get_output_handles()
                        if handles:
                            result["output_handles"] = handles
                    results[nid] = result
            if not results:
                return {"error": f"Node(s) not found: {', '.join(ids)}"}
            return results

        # ----- Frontend-interactive -----

        @self.mcp.tool(
            name="get_current_workflow",
            description=(
                "Get the workflow currently OPEN in the user's browser (nodes, edges, selected node). "
                "WARNING: with no browser session (the normal headless case) it does NOT error — it falls back to "
                "the user's most-recently-updated workflow (a GUESS) flagged with _fallback/_warning. If you have a "
                "specific workflow in mind, use get_workflow(workflow_id) instead; list_workflows to choose. "
                "Use node_ids to fetch only specific nodes."
            ),
            annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
        )
        async def get_current_workflow(node_ids: Optional[list[str]] = None) -> ToolResult | dict:
            user_id = _user_id_var.get()
            result = await self._request_frontend(
                "get_state", {},
                is_valid=lambda data: (
                    isinstance(data, dict)
                    and data.get('workflowId')
                ),
                collect_ms=100,
            )

            if "error" not in result:
                # Live browser session — use frontend state
                nodes = result.get("nodes", [])
                edges = result.get("edges", [])
                wf_id = result.get("workflowId")
                if node_ids:
                    node_ids_set = set(node_ids)
                    nodes = [n for n in nodes if n.get("id") in node_ids_set]
                resp: Dict[str, Any] = {
                    "workflowId": wf_id,
                    "name": result.get("workflowName"),
                    "selectedNodeId": result.get("selectedNodeId"),
                    "isRunning": result.get("isRunning", False),
                    "workflow_xml": _workflow_to_xml(nodes, edges),
                }
                if wf_id:
                    pool = await self.get_pool()
                    if pool:
                        try:
                            async with pool.acquire() as conn:
                                row = await conn.fetchrow(
                                    "SELECT description FROM workflows WHERE id = $1",
                                    uuid.UUID(wf_id),
                                )
                                if row:
                                    resp["description"] = row["description"] or ""
                        except Exception:
                            pass
                return self._make_visual_result(resp)

            # No browser session — fall back to most recently updated workflow
            logger.info("[MCP Server] get_current_workflow: no browser session, falling back to DB")
            try:
                pool = await self.get_pool()
                if not pool:
                    return {"error": "Database not available"}
                async with pool.acquire() as conn:
                    from wss.handlers.workflow_handler import get_user_org_context
                    org_id = await get_user_org_context(conn, user_id)

                    if org_id:
                        row = await conn.fetchrow(
                            """SELECT DISTINCT w.id, w.name, w.description, w.updated_at FROM workflows w
                               LEFT JOIN resource_shares rs ON rs.resource_id = w.id
                                   AND rs.resource_type = 'workflow'
                                   AND rs.target_type = 'organization'
                                   AND rs.target_org_id = $1
                               WHERE ((w.organization_id = $1 AND w.owner_id = $2) OR rs.id IS NOT NULL)
                               ORDER BY w.updated_at DESC LIMIT 1""",
                            uuid.UUID(org_id), uuid.UUID(user_id),
                        )
                    else:
                        row = await conn.fetchrow(
                            """SELECT w.id, w.name, w.description FROM workflows w
                               LEFT JOIN resource_shares rs ON rs.resource_id = w.id
                                   AND rs.resource_type = 'workflow'
                                   AND rs.target_type = 'organization'
                               WHERE w.owner_id = $1 AND w.organization_id IS NULL AND rs.id IS NULL
                               ORDER BY w.updated_at DESC LIMIT 1""",
                            uuid.UUID(user_id),
                        )
                    if not row:
                        return {"error": "No workflows found for this user."}
                    wf_id = str(row["id"])

                data, err = await self._load_workflow(user_id, wf_id)
                if err:
                    return {"error": err}

                nodes = data.get("nodes", [])
                if node_ids:
                    node_ids_set = set(node_ids)
                    nodes = [n for n in nodes if n.get("id") in node_ids_set]

                resp = {
                    "workflowId": wf_id,
                    "name": row["name"],
                    "description": row["description"] or "",
                    "workflow_xml": _workflow_to_xml(nodes, data.get("edges", [])),
                    "_fallback": True,
                    "_warning": (
                        f"No browser session — this is a GUESS (the most recently updated workflow, {wf_id}), "
                        "NOT a workflow the user pointed at. Do not mutate it unless you confirmed it's the intended "
                        "one; use get_workflow(workflow_id) / list_workflows to target a specific workflow."
                    ),
                }
                return self._make_visual_result(resp)
            except Exception as e:
                logger.error(f"[MCP Server] get_current_workflow DB fallback error: {e}", exc_info=True)
                return {"error": f"Failed to load workflow: {e}"}



        @self.mcp.tool(
            name="get_sdk_logs",
            description=(
                "Get recent SDK call logs from the interface iframe (errors, pending calls, etc.). "
                "Useful for debugging interface node issues — shows what SDK methods were called, "
                "their results or errors, timing, and which node triggered them."
            ),
            annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
        )
        async def get_sdk_logs(
            filter: Literal["errors", "pending", "all"] = "errors",
            limit: int = 20,
            workflow_id: Optional[str] = None,
        ) -> dict:
            """filter: 'errors' | 'pending' | 'all'. limit: max entries. workflow_id: target workflow."""
            result = await self._request_frontend(
                "get_sdk_logs", {"filter": filter, "limit": limit},
                workflow_id=workflow_id,
                collect_ms=100,
            )
            if "error" in result:
                return result
            return {"logs": result}

        @self.mcp.tool(
            name="get_selected_node",
            description=(
                "Get the node the user currently has SELECTED in their browser (BROWSER-ONLY: returns null with no "
                "open workflow / API-only access). get_current_workflow already returns selectedNodeId — use this only "
                "for a quick peek at the selected node's data."
            ),
            annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
        )
        async def get_selected_node() -> dict:
            result = await self._request_frontend("get_selected", {})
            if result is None:
                return {"selected_node": None}
            if isinstance(result, dict) and "error" in result:
                return {"selected_node": None, "_note": "No browser session active. Use get_workflow with a workflow_id instead."}
            return result

        @self.mcp.tool(
            name="open_workflow",
            description=(
                "Open a workflow in the user's browser. "
                "Requires the user to have a NoClick tab open."
            ),
            annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False, "idempotentHint": True},
        )
        async def open_workflow(workflow_id: str) -> dict:
            user_id = _user_id_var.get()
            pool = await self.get_pool()
            if pool:
                async with pool.acquire() as conn:
                    access = await check_resource_access(conn, user_id, "workflow", workflow_id)
                    if not access.has_access:
                        return {"error": f"Workflow not found or access denied: {workflow_id}"}

            result = await self._request_frontend(
                "open_workflow",
                {"workflow_id": workflow_id},
                is_valid=lambda r: r.get('success', False),
            )
            if "error" in result:
                return result
            return {"success": True, "workflow_id": workflow_id}

        # ----- Interface Layout -----

        @self.mcp.tool(
            name="update_interface",
            description=(
                "Position and arrange interface blocks on the 12-column grid layout.\n\n"
                "Interface blocks correspond to interface-* workflow nodes (e.g. interface-form, "
                "interface-markdown). Any interface nodes not yet on the grid are auto-created with defaults.\n\n"
                "XML commands:\n"
                '  <set_block_layout id="node-id" x="0" y="0" w="6" h="5" />\n'
                '  <remove_block id="node-id" />\n'
                '  <auto_layout />                   <!-- 2-column grid (default) -->\n'
                '  <auto_layout strategy="stack" />   <!-- Single column -->\n\n'
                "Grid: 12 columns, row height 40px. Blocks cannot overlap.\n"
                "id must be a full interface-* node ID from the workflow."
            ),
            annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False, "idempotentHint": True},
        )
        async def update_interface(workflow_id: str, updates_xml: str) -> dict:
            user_id = _user_id_var.get()

            data, err = await self._load_workflow(user_id, workflow_id)
            if err:
                return {"error": err}

            nodes = data.get("nodes", [])
            interface = data.get("interface") or {"layout": [], "blocks": []}

            # Build constraints from NODE_REGISTRY (reads WorkflowNode.grid_layout)
            constraints = _get_interface_block_constraints()

            # Build interface_nodes map: node_id -> block_type
            interface_nodes: Dict[str, str] = {}
            for node in nodes:
                node_type = node.get("type", "")
                block_type = _derive_block_type(node_type)
                if block_type is not None:
                    interface_nodes[node["id"]] = block_type

            # Index current layout and blocks
            layout_by_id: Dict[str, Dict[str, Any]] = {
                item["i"]: item for item in interface.get("layout", [])
            }
            blocks_by_id: Dict[str, Dict[str, Any]] = {
                b["id"]: b for b in interface.get("blocks", [])
            }

            # Auto-create blocks/layout for interface nodes not yet on the grid
            bottom_y = max((item["y"] + item["h"] for item in layout_by_id.values()), default=0)
            for nid, btype in interface_nodes.items():
                if nid not in layout_by_id:
                    c = constraints.get(btype, _INTERFACE_DEFAULT_LAYOUT)
                    layout_by_id[nid] = {
                        "i": nid, "x": 0, "y": bottom_y,
                        "w": c["defaultW"], "h": c["defaultH"],
                    }
                    bottom_y += c["defaultH"]
                if nid not in blocks_by_id:
                    blocks_by_id[nid] = {"id": nid, "type": btype, "config": {"label": btype.capitalize()}}

            # Parse XML commands
            try:
                root = ET.fromstring(f"<root>{updates_xml}</root>")
            except ET.ParseError as e:
                return {"error": f"Invalid XML: {e}"}

            # Process commands
            for elem in root:
                tag = elem.tag

                if tag == "set_block_layout":
                    block_id = elem.get("id", "")
                    if block_id not in interface_nodes:
                        return {"error": f"'{block_id}' is not an interface node"}

                    x = int(elem.get("x", "0"))
                    y = int(elem.get("y", "0"))
                    w = int(elem.get("w", str(layout_by_id.get(block_id, {}).get("w", 6))))
                    h = int(elem.get("h", str(layout_by_id.get(block_id, {}).get("h", 4))))

                    btype = interface_nodes[block_id]
                    c = constraints.get(btype, _INTERFACE_DEFAULT_LAYOUT)
                    if x < 0 or y < 0:
                        return {"error": f"Block {block_id}: x and y must be >= 0"}
                    if x + w > _INTERFACE_GRID_COLS:
                        return {"error": f"Block {block_id}: x({x}) + w({w}) exceeds grid width ({_INTERFACE_GRID_COLS})"}
                    if w < c.get("minW", 1):
                        return {"error": f"Block {block_id}: w({w}) < minW({c['minW']}) for type '{btype}'"}
                    if h < c.get("minH", 1):
                        return {"error": f"Block {block_id}: h({h}) < minH({c['minH']}) for type '{btype}'"}

                    layout_by_id[block_id] = {"i": block_id, "x": x, "y": y, "w": w, "h": h}

                elif tag == "remove_block":
                    block_id = elem.get("id", "")
                    layout_by_id.pop(block_id, None)
                    blocks_by_id.pop(block_id, None)

                elif tag == "auto_layout":
                    strategy = elem.get("strategy", "grid")
                    _auto_layout_interface(layout_by_id, interface_nodes, constraints, strategy)

                else:
                    return {"error": f"Unknown command: <{tag}>"}

            # Check for overlaps
            final_layout = list(layout_by_id.values())
            overlap_err = _check_overlaps(final_layout)
            if overlap_err:
                return {"error": f"Overlap detected: {overlap_err}"}

            # Build final state and save
            interface_state = {
                "layout": final_layout,
                "blocks": list(blocks_by_id.values()),
            }
            data["interface"] = interface_state

            save_err = await self._save_workflow(user_id, workflow_id, data)
            if save_err:
                return {"error": save_err}

            # Build block info for response (include minW/minH so agent has constraints)
            blocks_info = []
            for item in final_layout:
                bid = item["i"]
                btype = interface_nodes.get(bid, blocks_by_id.get(bid, {}).get("type", "unknown"))
                c = constraints.get(btype, _INTERFACE_DEFAULT_LAYOUT)
                blocks_info.append({
                    "id": bid, "type": btype,
                    "x": item["x"], "y": item["y"], "w": item["w"], "h": item["h"],
                    "minW": c.get("minW", 2), "minH": c.get("minH", 2),
                })

            # Broadcast to frontend for real-time sync
            from utils.event_relay import EVENT_RELAY_SECRET, broadcast_dict_to_user_safe
            event_name = "mcp:workflow:update_interface:response"
            broadcast_payload = {
                "success": True,
                "workflow_id": workflow_id,
                "blocks": blocks_info,
                "interface_state": interface_state,
            }
            if EVENT_RELAY_SECRET:
                try:
                    await broadcast_dict_to_user_safe(user_id, event_name, {"type": event_name, **broadcast_payload})
                except Exception as e:
                    logger.error(f"[MCP Server] Interface broadcast failed: {e}")
            else:
                from wss.receiver.receiver import get_receiver_instance
                receiver = get_receiver_instance()
                if receiver:
                    for sid in receiver.get_frontend_sids_for_user(user_id):
                        await self.sio.emit(event_name, broadcast_payload, to=sid)

            return {
                "success": True,
                "workflow_id": workflow_id,
                "blocks": blocks_info,
            }

        # ----- Folder Management -----

        @self.mcp.tool(
            name="get_workflow_folders",
            description=(
                "Get the complete folder tree for organizing workflows. "
                "Returns all folders the user has access to in a hierarchical structure with workflow counts. "
                "Use this to discover folder IDs for list_workflows or create_workflow."
            ),
            annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False, "idempotentHint": True},
        )
        async def get_workflow_folders() -> dict:
            user_id = _user_id_var.get()
            pool = await self.get_pool()
            if not pool:
                return {"error": "Database not available"}
            async with pool.acquire() as conn:
                from wss.handlers.workflow_handler import get_user_org_context
                org_id = await get_user_org_context(conn, user_id)

                if org_id:
                    # Org context: folders owned by user in this org OR shared with org
                    rows = await conn.fetch(
                        """SELECT DISTINCT f.id, f.name, f.description, f.parent_folder_id,
                                  f.path, f.depth, f.created_at, f.updated_at,
                                  COUNT(w.id) as workflow_count
                           FROM workflow_folders f
                           LEFT JOIN workflows w ON w.folder_id = f.id
                           WHERE (
                               (f.organization_id = $2 AND f.owner_id = $1)
                               OR EXISTS (
                                   SELECT 1 FROM resource_shares rs
                                   WHERE rs.resource_type = 'workflow_folder'
                                   AND rs.resource_id = f.id
                                   AND rs.target_type = 'organization'
                                   AND rs.target_org_id = $2
                               )
                           )
                           GROUP BY f.id, f.name, f.description, f.parent_folder_id,
                                    f.path, f.depth, f.created_at, f.updated_at
                           ORDER BY f.depth ASC, f.name ASC""",
                        uuid.UUID(user_id), uuid.UUID(org_id),
                    )
                else:
                    # Personal context: only owned personal folders
                    rows = await conn.fetch(
                        """SELECT f.id, f.name, f.description, f.parent_folder_id,
                                  f.path, f.depth, f.created_at, f.updated_at,
                                  COUNT(w.id) as workflow_count
                           FROM workflow_folders f
                           LEFT JOIN workflows w ON w.folder_id = f.id
                           WHERE f.owner_id = $1
                             AND f.organization_id IS NULL
                           GROUP BY f.id, f.name, f.description, f.parent_folder_id,
                                    f.path, f.depth, f.created_at, f.updated_at
                           ORDER BY f.depth ASC, f.name ASC""",
                        uuid.UUID(user_id),
                    )

                # Build tree structure
                folders_by_id: Dict[str, dict] = {}
                root_folders: list[dict] = []

                for row in rows:
                    folder = {
                        "id": str(row["id"]),
                        "name": row["name"],
                        "description": row["description"] or "",
                        "parent_folder_id": str(row["parent_folder_id"]) if row["parent_folder_id"] else None,
                        "depth": row["depth"],
                        "workflow_count": row["workflow_count"] or 0,
                        "children": [],
                    }
                    folders_by_id[folder["id"]] = folder
                    if row["parent_folder_id"] is None:
                        root_folders.append(folder)

                # Wire parent-child relationships
                for fid, folder in folders_by_id.items():
                    pid = folder["parent_folder_id"]
                    if pid and pid in folders_by_id:
                        folders_by_id[pid]["children"].append(folder)

                return {"folders": root_folders}

        @self.mcp.tool(
            name="update_folders",
            description=(
                "Batch folder mutations using XML commands. Multiple operations in one call.\n\n"
                "XML commands:\n"
                '  <create_folder name="My Folder" description="optional" parent_folder_id="optional-uuid" />\n'
                '  <update_folder id="folder-uuid" name="New Name" description="New desc" parent_folder_id="new-parent-uuid" />\n'
                '  <delete_folder id="folder-uuid" />\n'
                '  <move_workflow id="workflow-uuid" folder_id="target-folder-uuid" />\n'
                '  <move_workflow id="workflow-uuid" /> <!-- move to root (no folder) -->\n\n'
                "Processing order: create_folder → update_folder → move_workflow → delete_folder\n\n"
                "name= on create_folder is a local alias usable in folder_id/parent_folder_id/id within the same batch.\n\n"
                "Examples:\n"
                '  <create_folder name="Projects" />\n'
                '  <create_folder name="Sub" parent_folder_id="Projects" />\n'
                '  <move_workflow id="wf-uuid" folder_id="Projects" />'
            ),
            annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False, "idempotentHint": False},
        )
        async def update_folders(updates_xml: str) -> dict:
            user_id = _user_id_var.get()
            uid = uuid.UUID(user_id)
            pool = await self.get_pool()
            if not pool:
                return {"error": "Database not available"}

            try:
                root = ET.fromstring(f"<root>{updates_xml}</root>")
            except ET.ParseError as e:
                return {"error": f"Invalid XML: {e}"}

            # Classify operations
            creates, updates, moves, deletes = [], [], [], []
            for elem in root:
                tag = elem.tag
                if tag == "create_folder":
                    creates.append(elem)
                elif tag == "update_folder":
                    updates.append(elem)
                elif tag == "move_workflow":
                    moves.append(elem)
                elif tag == "delete_folder":
                    deletes.append(elem)
                else:
                    return {"error": f"Unknown command: <{tag}>"}

            # alias_map: local name aliases → real folder UUIDs
            alias_map: Dict[str, str] = {}
            results: Dict[str, list] = {"created": [], "updated": [], "moved": [], "deleted": []}

            def _resolve(val: str | None) -> str | None:
                """Resolve an alias or pass through a UUID."""
                if val is None:
                    return None
                return alias_map.get(val, val)

            async with pool.acquire() as conn:
                from wss.handlers.workflow_handler import get_user_org_context
                org_id = await get_user_org_context(conn, user_id)

                # 1. Create folders
                for elem in creates:
                    name = elem.get("name")
                    if not name:
                        return {"error": "create_folder requires name attribute"}
                    desc = elem.get("description", "")
                    parent = _resolve(elem.get("parent_folder_id"))

                    if parent:
                        has_access = await conn.fetchval(
                            "SELECT can_access_folder($1, $2)", uid, uuid.UUID(parent),
                        )
                        if not has_access:
                            return {"error": f"Invalid parent folder or access denied: {parent}"}
                        # Validate parent folder is in same org context
                        parent_row = await conn.fetchrow(
                            "SELECT organization_id FROM workflow_folders WHERE id = $1",
                            uuid.UUID(parent),
                        )
                        if parent_row:
                            parent_org = str(parent_row["organization_id"]) if parent_row["organization_id"] else None
                            if parent_org != org_id:
                                return {"error": f"Parent folder must be in the same workspace context: {parent}"}

                    row = await conn.fetchrow(
                        """INSERT INTO workflow_folders (owner_id, organization_id, name, description, parent_folder_id)
                           VALUES ($1, $2, $3, $4, $5)
                           RETURNING id, name, description, parent_folder_id, depth""",
                        uid, uuid.UUID(org_id) if org_id else None, name, desc,
                        uuid.UUID(parent) if parent else None,
                    )
                    folder_id = str(row["id"])
                    alias_map[name] = folder_id
                    results["created"].append({
                        "id": folder_id, "name": row["name"],
                        "description": row["description"] or "",
                        "parent_folder_id": str(row["parent_folder_id"]) if row["parent_folder_id"] else None,
                        "depth": row["depth"],
                    })

                # 2. Update folders
                for elem in updates:
                    fid = _resolve(elem.get("id"))
                    if not fid:
                        return {"error": "update_folder requires id attribute"}

                    row = await conn.fetchrow(
                        "SELECT owner_id FROM workflow_folders WHERE id = $1", uuid.UUID(fid),
                    )
                    if not row:
                        return {"error": f"Folder not found: {fid}"}
                    if str(row["owner_id"]) != user_id:
                        return {"error": f"Only the folder owner can update: {fid}"}

                    sets, vals = [], []
                    for attr in ("name", "description"):
                        val = elem.get(attr)
                        if val is not None:
                            sets.append(f"{attr} = ${len(vals)+2}")
                            vals.append(val)
                    parent = elem.get("parent_folder_id")
                    if parent is not None:
                        parent = _resolve(parent)
                        has_access = await conn.fetchval(
                            "SELECT can_access_folder($1, $2)", uid, uuid.UUID(parent),
                        )
                        if not has_access:
                            return {"error": f"Invalid parent folder or access denied: {parent}"}
                        sets.append(f"parent_folder_id = ${len(vals)+2}")
                        vals.append(uuid.UUID(parent))

                    if not sets:
                        return {"error": f"update_folder for {fid}: no fields to update"}

                    updated = await conn.fetchrow(
                        f"""UPDATE workflow_folders SET {', '.join(sets)}
                            WHERE id = $1
                            RETURNING id, name, description, parent_folder_id, depth""",
                        uuid.UUID(fid), *vals,
                    )
                    results["updated"].append({
                        "id": str(updated["id"]), "name": updated["name"],
                        "description": updated["description"] or "",
                        "parent_folder_id": str(updated["parent_folder_id"]) if updated["parent_folder_id"] else None,
                        "depth": updated["depth"],
                    })

                # 3. Move workflows
                for elem in moves:
                    wf_id = elem.get("id")
                    if not wf_id:
                        return {"error": "move_workflow requires id attribute"}
                    target = _resolve(elem.get("folder_id"))

                    access = await check_resource_access(conn, user_id, "workflow", wf_id)
                    if access.permission != Permission.OWNER:
                        return {"error": f"Only the workflow owner can move: {wf_id}"}

                    if target:
                        has_access = await conn.fetchval(
                            "SELECT can_access_folder($1, $2)", uid, uuid.UUID(target),
                        )
                        if not has_access:
                            return {"error": f"Invalid folder or access denied: {target}"}

                    await conn.execute(
                        "UPDATE workflows SET folder_id = $1, updated_at = NOW() WHERE id = $2",
                        uuid.UUID(target) if target else None, uuid.UUID(wf_id),
                    )
                    results["moved"].append({"workflow_id": wf_id, "folder_id": target})

                # 4. Delete folders (last — so moves can reference them first)
                for elem in deletes:
                    fid = _resolve(elem.get("id"))
                    if not fid:
                        return {"error": "delete_folder requires id attribute"}

                    row = await conn.fetchrow(
                        "SELECT owner_id, parent_folder_id FROM workflow_folders WHERE id = $1",
                        uuid.UUID(fid),
                    )
                    if not row:
                        return {"error": f"Folder not found: {fid}"}
                    if str(row["owner_id"]) != user_id:
                        return {"error": f"Only the folder owner can delete: {fid}"}

                    # Move workflows to parent folder (or root)
                    await conn.execute(
                        "UPDATE workflows SET folder_id = $1 WHERE folder_id = $2",
                        row["parent_folder_id"], uuid.UUID(fid),
                    )
                    await conn.execute(
                        "DELETE FROM workflow_folders WHERE id = $1", uuid.UUID(fid),
                    )
                    results["deleted"].append(fid)

            # Strip empty result keys
            results = {k: v for k, v in results.items() if v}
            return {"success": True, "alias_map": alias_map, **results}

        # ----- Workspace Management -----

        @self.mcp.tool(
            name="list_workspaces",
            description=(
                "List the user's available workspaces (personal + organizations). "
                "Shows which workspace is currently active. Use switch_workspace to change."
            ),
            annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
        )
        async def list_workspaces() -> dict:
            user_id = _user_id_var.get()
            pool = await self.get_pool()
            if not pool:
                return {"error": "Database not available"}
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT om.organization_id, om.role, om.is_primary,
                              o.name, o.slug
                       FROM organization_members om
                       JOIN organizations o ON o.id = om.organization_id
                       WHERE om.user_id = $1
                       ORDER BY o.name ASC""",
                    uuid.UUID(user_id),
                )

                active_org = None
                orgs = []
                for r in rows:
                    org = {
                        "id": str(r["organization_id"]),
                        "name": r["name"],
                        "slug": r["slug"],
                        "role": r["role"],
                        "is_active": bool(r["is_primary"]),
                    }
                    if r["is_primary"]:
                        active_org = org["id"]
                    orgs.append(org)

                return {
                    "active_workspace": active_org or "personal",
                    "workspaces": [
                        {"id": "personal", "name": "Personal", "is_active": active_org is None},
                        *orgs,
                    ],
                }

        @self.mcp.tool(
            name="switch_workspace",
            description=(
                "Switch between personal and organization workspaces. "
                "Pass an organization_id to switch to that org, or pass null/empty to switch to personal. "
                "Affects which workflows, folders, and credentials are visible."
            ),
            annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
        )
        async def switch_workspace(organization_id: str | None = None) -> dict:
            user_id = _user_id_var.get()
            uid = uuid.UUID(user_id)
            pool = await self.get_pool()
            if not pool:
                return {"error": "Database not available"}
            async with pool.acquire() as conn:
                # Clear all is_primary flags for this user
                await conn.execute(
                    "UPDATE organization_members SET is_primary = false WHERE user_id = $1",
                    uid,
                )

                if organization_id:
                    # Verify membership
                    membership = await conn.fetchval(
                        "SELECT id FROM organization_members WHERE organization_id = $1 AND user_id = $2",
                        uuid.UUID(organization_id), uid,
                    )
                    if not membership:
                        return {"error": "You are not a member of this organization"}

                    # Set the new primary organization
                    await conn.execute(
                        "UPDATE organization_members SET is_primary = true WHERE organization_id = $1 AND user_id = $2",
                        uuid.UUID(organization_id), uid,
                    )

                    # Get org name for confirmation
                    org_name = await conn.fetchval(
                        "SELECT name FROM organizations WHERE id = $1",
                        uuid.UUID(organization_id),
                    )
                    return {"success": True, "active_workspace": organization_id, "name": org_name}

                return {"success": True, "active_workspace": "personal", "name": "Personal"}


