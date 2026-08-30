"""
Operation catalog: pure introspection over the node registry.

Enumerates operations from Pydantic config unions, resolves operation
schemas/config classes, validates and coerces config values, and derives
credential requirements. Shared by the AI builder, the MCP server, and the
webhook/bridge utilities — no LLM code lives here.
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union, get_args, get_origin

from nodes.core.base import runtime_config_view
from nodes.core.registry import NODE_REGISTRY
from nodes.agent.config.providers import (
    agent_credential_requirement,
    agent_credential_types,
)
from .workflow_ops import find_placeholder_tokens

logger = logging.getLogger(__name__)


# ============================================================================
# Operation Introspection
# ============================================================================

@dataclass
class OperationInfo:
    """Information about a single operation for a node type.

    `display_name`, `category`, and `is_trigger` come from the rename-refactor
    metadata (`x-display-name` / `x-category` / `x-is-trigger`) on the
    operation discriminator field's `json_schema_extra`. They drive the
    grouped operations list shown to the LLM in node drafter.
    """
    name: str
    description: str
    config_class: type
    display_name: Optional[str] = None
    category: Optional[str] = None
    is_trigger: bool = False


def get_operations_for_node_type(node_type: str) -> List[OperationInfo]:
    """
    Get available operations for a node type by introspecting its config model.

    Returns list of OperationInfo with name, description, and config class.

    NOTE: the agent node_op tool builder has a sibling enumerator
    (nodes/agent/node_op_tools._iter_operation_defs) that walks the emitted
    JSON schema instead — it needs member schemas, this needs config CLASSES,
    so they can't share one implementation.
    test_operation_enumerators_agree_across_registry pins them together.
    """
    node_class = NODE_REGISTRY.get(node_type)
    if not node_class:
        logger.warning(f"Node type '{node_type}' not found in registry")
        return []

    # Get the config model
    config_model = getattr(node_class, 'get_config_model', lambda: None)()
    if not config_model:
        return []

    # Get the 'config' field's type annotation
    config_field_type = None
    for field_name, field_info in config_model.model_fields.items():
        if field_name == 'config':
            config_field_type = field_info.annotation
            break

    if not config_field_type:
        return []

    # Handle Annotated[Union[...], Discriminator] — unwrap to get the Union.
    # CRITICAL: only unwrap when the outer origin is typing.Annotated. A
    # plain Union[...] also has a non-None origin (typing.Union), and
    # blindly taking args[0] would collapse the Union to its first member
    # — silently making every multi-op node look single-op (node drafter then
    # has nothing to select among, which is what broke
    # Cancellation regression coverage and
    # test_n8n_import_full_pipeline_wires_prompts_end_to_end on 2026-05-26).
    import typing as _typing
    origin = get_origin(config_field_type)
    if origin is _typing.Annotated:
        args = get_args(config_field_type)
        if args:
            config_field_type = args[0]

    # Now get the union members
    origin = get_origin(config_field_type)
    if origin is Union:
        union_members = get_args(config_field_type)
    else:
        union_members = [config_field_type]

    operations = []
    for member in union_members:
        if not hasattr(member, 'model_fields'):
            continue

        op_field = member.model_fields.get('operation')

        if not op_field:
            # Single-operation node (no discriminator) - treat the config itself as the operation
            # Use "default" as the operation name for single-operation nodes
            operations.append(OperationInfo(
                name="default",
                description=f"Execute {node_type} node",
                config_class=member,
            ))
            continue

        # Get the Literal value
        op_annotation = op_field.annotation
        origin = get_origin(op_annotation)

        # Handle Literal type to get the operation name
        op_name = None
        if hasattr(op_annotation, '__args__'):
            # Literal["name"] has __args__ = ("name",)
            args = op_annotation.__args__
            if args:
                op_name = args[0]

        if not op_name:
            continue

        # Get description from the operation field, falling back to the
        # config class docstring (which is where the meaningful one-liners
        # actually live for most node ops — `Field(description=…)` is rarely
        # set on the discriminator itself).
        description = op_field.description or (member.__doc__ or "").strip() or ""

        # Pull rename-refactor metadata off the field's json_schema_extra.
        # Available since the operation rename + metadata propagation; older
        # nodes without the metadata fall back to the legacy display
        # (snake_case name + description, no grouping).
        extra = op_field.json_schema_extra or {}
        if not isinstance(extra, dict):
            extra = {}
        display_name = extra.get('x-display-name')
        category = extra.get('x-category')
        is_trigger = bool(extra.get('x-is-trigger', False))

        operations.append(OperationInfo(
            name=op_name,
            description=description,
            config_class=member,
            display_name=display_name if isinstance(display_name, str) else None,
            category=category if isinstance(category, str) else None,
            is_trigger=is_trigger,
        ))

    return operations

# ============================================================================
# Utility Functions
# ============================================================================

def get_operation_schema(node_type: str, operation: str) -> Optional[Dict[str, Any]]:
    """
    Get the JSON schema for a specific operation.

    Used in node drafter for configuration.
    """
    operations = get_operations_for_node_type(node_type)
    for op in operations:
        if op.name == operation:
            # Generate JSON schema from Pydantic model
            return op.config_class.model_json_schema()
    return None


def get_operation_config_class(node_type: str, operation: str):
    """Get the Pydantic config model class for a specific operation.

    Returns None if node type or operation not found.
    """
    operations = get_operations_for_node_type(node_type)
    for op in operations:
        if op.name == operation:
            return op.config_class
    return None


def is_operation_credentials_optional(
    node_type: str,
    operation: Optional[str],
    config: Optional[Dict[str, Any]] = None,
) -> bool:
    """Return whether the selected operation can run without credentials.

    This mirrors the frontend's operation-aware credential gating, but lives
    in the backend so node drafting, the agentic builder summary, and query paths
    all make the same decision.
    """
    if not operation:
        return False

    config_class = get_operation_config_class(node_type, operation)
    if not config_class:
        return False

    schema = config_class.model_json_schema()
    from nodes.core.platform_billing import platform_key_funds

    if schema.get("x-credentials-optional") is True:
        return platform_key_funds(schema)

    condition = schema.get("x-credentials-optional-if")
    if not isinstance(condition, dict) or not config:
        return False

    def evaluate_condition(rule: Dict[str, Any]) -> bool:
        if rule.get("anyOf"):
            subrules = rule.get("anyOf")
            if isinstance(subrules, list):
                return any(
                    isinstance(subrule, dict) and evaluate_condition(subrule)
                    for subrule in subrules
                )
            return False

        field_name = rule.get("field")
        if not isinstance(field_name, str):
            return False

        field_value = str(config.get(field_name, "")).lower()
        passes = False

        contains_any = rule.get("containsAny")
        if isinstance(contains_any, list):
            passes = any(str(item).lower() in field_value for item in contains_any)
        elif "containsAll" in rule and isinstance(rule["containsAll"], list):
            passes = all(str(item).lower() in field_value for item in rule["containsAll"])
        elif "contains" in rule:
            passes = str(rule["contains"]).lower() in field_value
        else:
            return False

        if not passes:
            return False

        if "notContains" in rule:
            return str(rule["notContains"]).lower() not in field_value

        return True

    return evaluate_condition(condition) and platform_key_funds(schema)


def _validate_jsx(source: str) -> Optional[str]:
    """
    Validate JSX by transpiling and executing in a stubbed browser environment.
    Catches syntax errors AND runtime errors (e.g. .map() on non-array).
    Returns None if valid, or an error message.
    """
    from utils.jsx_transpiler import validate_jsx_runtime
    return validate_jsx_runtime(source)


def validate_node_config(node_type: str, operation: str, config: Dict[str, Any]) -> Optional[str]:
    """Validate a node's config dict against its Pydantic model.

    Returns None if valid, or an error string if validation fails.
    Used by both node drafter (node drafter retry) and the brain (field ops feedback).
    Includes compile checks for code fields (e.g. JSX transpilation).
    """
    config_class = get_operation_config_class(node_type, operation)
    if not config_class or not config:
        return None
    try:
        # Validate the canonical runtime view (""→None, str coercions,
        # rejected unset markers dropped) — judging the raw config let values
        # through that the runtime transform then broke (cc="" valid,
        # cc=None not — Gmail validation regression).
        config_class.model_validate(runtime_config_view(config, config_class))
    except Exception as e:
        err = str(e)
        return err[:300] + '...' if len(err) > 300 else err

    # Post-validation compile checks for code fields
    if node_type == 'interface-html-react' and operation == 'render_jsx_react_interface':
        jsx_source = config.get('jsx_source', '')
        if jsx_source:
            jsx_err = _validate_jsx(jsx_source)
            if jsx_err:
                return jsx_err

    # Placeholder-secret lint: invented tokens like {{API_KEY}} resolve to
    # nothing at runtime. Skips code fields (JSX object literals) and the
    # http-request headers field, whose placeholders are the auth signal the
    # post-drafter sanitizer converts into a credential input request.
    hits = find_placeholder_tokens(config, _placeholder_skip_fields(node_type, config_class))
    if hits:
        path, token = hits[0]
        return (
            f"Field '{path}' contains the placeholder '{token}' — placeholder variables "
            f"resolve to NOTHING at runtime; never invent them. For secrets/API keys: omit "
            f"the value and rely on an attached credential, or emit "
            f'<field name="..." type="user_input" label="..." reason="..." />. '
            f"For upstream data use {{{{ $('node_id').field }}}}."
        )

    # Foreign template-dialect lint: accessors from other automation tools
    # ($('x').item.json, $input, $node[...]) validate fine and then throw at
    # run time — catch them at write time with the correct form.
    from coder.workflow.workflow_ops import find_foreign_expression_tokens, foreign_expression_error
    foreign = find_foreign_expression_tokens(config, _placeholder_skip_fields(node_type, config_class))
    if foreign:
        return foreign_expression_error(*foreign[0])

    return None


# Pydantic error types the write gate ENFORCES: the value's structural shape
# is wrong regardless of how the operation's config class resolved (a string
# where the model wants a list/dict/object — the class that killed the
# 2026-07-16 trial). Value-DOMAIN errors (literal_error, enum) stay advisory:
# canvas-level discriminators like the agent's model_type carry values the
# single resolved operation class doesn't know about, so a domain mismatch
# is not proof the value is wrong (reverting model_type='image' broke the
# explicit-discriminator batch contract).
_SHAPE_ERROR_TYPES = frozenset({
    'list_type', 'dict_type', 'model_type', 'model_attributes_type',
})


def config_value_errors(
    node_type: str, operation: str, config: Dict[str, Any]
) -> List[Tuple[str, str]]:
    """Pydantic errors for STRUCTURALLY WRONG present values only.

    Reported: container-shape errors (see _SHAPE_ERROR_TYPES) and 'missing'
    errors NESTED inside a provided container (e.g. fields[0].name — the
    provided value itself is malformed). Excluded: top-level missing-required
    (AI paths build configs incrementally) and value-domain errors
    (literal/enum — advisory via validate_node_config, never enforced).

    Returns (top_level_key, 'dotted.path: message') pairs. Unexpected
    (non-pydantic) validation failures return [] — enforcement backs off and
    validate_node_config's advisory string still covers them.
    """
    config_class = get_operation_config_class(node_type, operation)
    if not config_class or not config:
        return []
    from pydantic import ValidationError
    try:
        # Same canonical runtime view as validate_node_config / execution.
        config_class.model_validate(runtime_config_view(config, config_class))
        return []
    except ValidationError as e:
        out: List[Tuple[str, str]] = []
        for err in e.errors():
            loc = err.get('loc') or ()
            err_type = err.get('type')
            is_nested_missing = err_type == 'missing' and len(loc) > 1
            if err_type not in _SHAPE_ERROR_TYPES and not is_nested_missing:
                continue
            key = str(loc[0]) if loc else ''
            path = '.'.join(str(p) for p in loc) or key
            out.append((key, f"{path}: {err.get('msg')}"))
        return out
    except Exception:
        return []


def coerce_config_value_types(
    node_type: str, operation: str, config: Dict[str, Any]
) -> List[str]:
    """Deterministically normalize the commonest LLM config mistake —
    stringified JSON in a structured field — IN PLACE.

    For each wrong-typed key: a string value that json-parses into a dict or
    list is replaced with the parsed value, and a lone object where the model
    wants a list is wrapped into [object]. Applied only when it strictly
    reduces the validation error count. Returns human-readable notes of what
    changed (empty = nothing coerced).
    """
    import json as _json

    errors = config_value_errors(node_type, operation, config)
    if not errors:
        return []
    candidate = dict(config)
    notes: List[str] = []
    for key in {k for k, _ in errors if k}:
        val = candidate.get(key)
        if not isinstance(val, str):
            continue
        s = val.strip()
        if not (s.startswith('{') or s.startswith('[')):
            continue
        try:
            candidate[key] = _json.loads(s)
        except ValueError:
            continue
        notes.append(f"{key}: parsed JSON string into structured value")
    for key, msg in config_value_errors(node_type, operation, candidate):
        if isinstance(candidate.get(key), dict) and 'valid list' in msg:
            candidate[key] = [candidate[key]]
            notes.append(f"{key}: wrapped single object into a list")
    if not notes:
        return []
    if len(config_value_errors(node_type, operation, candidate)) >= len(errors):
        return []
    config.clear()
    config.update(candidate)
    return notes


def reject_invalid_config_values(
    node_type: str, operation: str, config: Dict[str, Any],
    changed_keys: set,
) -> Tuple[List[str], List[Tuple[str, str]]]:
    """Write-time gate for AI-written config values: coerce what can be
    deterministically fixed (in place), then report the changed keys whose
    values are STILL wrong-typed so the caller can revert them — a
    wrong-typed value must never persist. Pure-template strings
    ('{{ … }}') are exempt because they resolve at
    runtime and can't be judged statically.

    Returns (coercion_notes, rejected) where rejected is (key, error) pairs.
    """
    notes = coerce_config_value_types(node_type, operation, config)
    rejected: List[Tuple[str, str]] = []
    for key, msg in config_value_errors(node_type, operation, config):
        if key not in changed_keys:
            continue
        val = config.get(key)
        if isinstance(val, str) and '{{' in val:
            continue
        rejected.append((key, msg))
    return notes, rejected


_CODE_FIELD_WIDGETS = frozenset({'code_editor', 'python_editor'})


def _placeholder_skip_fields(node_type: str, config_class) -> frozenset:
    """Fields exempt from the placeholder lint for this operation."""
    skip = set()
    for name, model_field in config_class.model_fields.items():
        extra = model_field.json_schema_extra
        if isinstance(extra, dict) and extra.get('ui:widget') in _CODE_FIELD_WIDGETS:
            skip.add(name)
    if node_type == 'automation-http-request':
        skip.add('headers')
    return frozenset(skip)


@dataclass
class CredentialInfo:
    """Information about credentials required by a node type."""
    provider_key: str  # Frontend provider key (e.g., 'google_sheets', 'telegram', 'slack')
    credential_type: str = ""  # DB credential_type for search (e.g., 'google_gmail_oauth')
    label: str = ""  # Human-readable label for the credential
    is_oauth: bool = True  # Whether this is an OAuth credential


# Override map for node types where the derived name doesn't match frontend expectations
# Most node types can be derived: automation-X → X (replace - with _)
# This map only contains exceptions
_PROVIDER_KEY_OVERRIDES: Dict[str, str] = {
    'automation-github-rest': 'github',  # github_rest → github
    'automation-outlook': 'microsoft',   # outlook → microsoft
}

# Node types that can genuinely run with NO credentials at all. Mirrors the FE's
# TRULY_OPTIONAL_CREDENTIALS (NodeCredentials.tsx) — pinned by
# tests/test_api_key_node_credential_prompts.py. Node-level rather than
# schema-stamped (`x-credentials-optional`) because these have no per-operation
# config class to stamp, so the operation-aware check can't reach them.
TRULY_OPTIONAL_CREDENTIAL_NODES = {
    'automation-rss',           # Public feeds
    'automation-http-request',  # Public endpoints
    'mcp-server',               # auth_type defaults to none; hosting mode needs none
}


def credentials_truly_optional(node_type: str) -> bool:
    """Whether the node can run credential-less regardless of operation."""
    return node_type in TRULY_OPTIONAL_CREDENTIAL_NODES


def _derive_provider_key(node_type: str) -> str:
    """
    Derive frontend provider key from node type.

    Examples:
        automation-google-sheets → google_sheets
        automation-slack → slack
        automation-github-rest → github (via override)
    """
    # Check override map first
    if node_type in _PROVIDER_KEY_OVERRIDES:
        return _PROVIDER_KEY_OVERRIDES[node_type]

    # Default: strip 'automation-' prefix and replace - with _
    if node_type.startswith('automation-'):
        return node_type[len('automation-'):].replace('-', '_')

    return node_type.replace('-', '_')


def _credential_schema_refs(
    node_type: str,
    operation: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], List[str]]:
    """Return (config schema, credential $refs) for a node whose selected
    operation actually requires credentials. ``({}, [])`` when the node type
    is unknown, has no credentials property, or the operation waives them
    (``x-credentials-optional`` / ``-if``).

    Tool-provider nodes (non-empty ``agent_tool_operations``) are decided by
    their ALLOWLIST via the same predicate that gates runtime tool exposure
    (``allowlist_requires_credentials``): all-optional waives, anything else
    requires. The single-op waiver is skipped for them either way — provider
    nodes skip node drafter, so ``operation`` is unset or a stale pre-wiring value
    that must not speak for the allowlist (2026-07-29 exa incident: the brain
    asked for an Exa key on an all-optional allowlist).
    """
    node_class = NODE_REGISTRY.get(node_type)
    if not node_class:
        return {}, []

    allowlisted_ops = (config or {}).get('agent_tool_operations')
    if isinstance(allowlisted_ops, list) and allowlisted_ops:
        from nodes.agent.node_op_tools import allowlist_requires_credentials

        if not allowlist_requires_credentials(node_type, allowlisted_ops):
            return {}, []
    elif is_operation_credentials_optional(node_type, operation, config):
        return {}, []

    schema = node_class.get_config_schema()
    if not schema:
        return {}, []

    creds_schema = schema.get('properties', {}).get('credentials')
    if not creds_schema:
        return schema, []

    # Collect all credential refs (some nodes have multiple: PAT + OAuth)
    cred_refs = []
    if 'anyOf' in creds_schema:
        for item in creds_schema['anyOf']:
            if item.get('type') != 'null' and '$ref' in item:
                cred_refs.append(item['$ref'])
    elif '$ref' in creds_schema:
        cred_refs.append(creds_schema['$ref'])

    return schema, cred_refs


def node_requires_credentials(
    node_type: str,
    operation: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> bool:
    """Whether the node's selected operation needs credentials at all.

    Broader than ``get_credential_info``: True also for non-OAuth API-key
    nodes (which get_credential_info deliberately skips when auto-prompting
    during generation). False when the schema has no credentials property or
    the operation is marked credentials-optional — the signal the builder
    uses to tell the brain NOT to ask the user to connect an account.
    """
    if node_type == 'agent':
        return agent_credential_requirement(config).required
    return bool(_credential_schema_refs(node_type, operation, config)[1])


_KNOWN_CREDENTIAL_TYPES: Optional[frozenset] = None


def known_credential_types() -> frozenset:
    """All ``credential_type`` strings any registered node accepts.

    Built once from the node schemas' credential ``$defs`` (the same place
    ``get_credential_info`` reads per-node types from) plus the agent
    credential types (``agent_<provider>`` / ``agent_*_oauth``, which live in
    the FE + OAuth handlers, not in any node schema); used to tell the brain
    when it searched for a credential type that doesn't exist.
    """
    global _KNOWN_CREDENTIAL_TYPES
    if _KNOWN_CREDENTIAL_TYPES is None:
        types = set(agent_credential_types())
        for node_class in NODE_REGISTRY.values():
            try:
                schema = node_class.get_config_schema() or {}
            except Exception:
                continue
            for cred_def in schema.get('$defs', {}).values():
                ct_prop = cred_def.get('properties', {}).get('credential_type', {})
                ct = ct_prop.get('const') or ct_prop.get('default')
                if ct:
                    types.add(ct)
        _KNOWN_CREDENTIAL_TYPES = frozenset(types)
    return _KNOWN_CREDENTIAL_TYPES


def node_accepted_credential_types(
    node_type: str,
    operation: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> set:
    """The set of ``credential_type`` strings a node's selected operation accepts.

    Unlike :func:`get_credential_info` (which returns only the FIRST union member),
    this returns ALL of them — so a write path can verify a credential's ACTUAL DB
    type is one the node really accepts before filing it (e.g. reject a GitHub PAT
    placed on a Slack node). Empty set when the node needs no credentials.
    """
    if node_type == 'agent':
        # The MODEL requirement's accepted types PLUS agent_env — a NON-PRIMARY
        # secondary the agent legitimately accepts. It is kept OUT of
        # agent_credential_requirement().accepted_types (which drives the model
        # satisfaction/hint), so adding it only here lets <set_credentials> attach
        # an env bundle without it counting as the model credential.
        from utils.credentials import NON_PRIMARY_CREDENTIAL_TYPES

        return set(agent_credential_requirement(config).accepted_types) | NON_PRIMARY_CREDENTIAL_TYPES
    schema, cred_refs = _credential_schema_refs(node_type, operation, config)
    out: set = set()
    for cred_ref in cred_refs:
        ref_name = cred_ref.split('/')[-1]
        cred_def = schema.get('$defs', {}).get(ref_name, {})
        ct_prop = cred_def.get('properties', {}).get('credential_type', {})
        ct = ct_prop.get('const') or ct_prop.get('default')
        if ct:
            out.add(ct)
    return out


def derive_credential_type(
    node_type: str,
    operation: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> str:
    """The credential_type string of a node's credential schema — the pure
    def-scan WITHOUT get_credential_info's OAuth/allowlist gating, so it works
    for EVERY credentialed node (WhatsApp QR, API keys, …). The general seam
    the builder input bridge keys credential_requests on: an ask for any
    node's credential must always carry a usable type (2026-07-19 — WhatsApp
    asks minted no provide link because the gated path returned nothing)."""
    schema, cred_refs = _credential_schema_refs(node_type, operation, config)
    for cred_ref in cred_refs:
        ref_name = cred_ref.split('/')[-1]
        ct_prop = (
            schema.get('$defs', {}).get(ref_name, {})
            .get('properties', {}).get('credential_type', {})
        )
        if ct_prop.get('const'):
            return ct_prop['const']
        if ct_prop.get('default'):
            return ct_prop['default']
    return ""


def get_credential_info(
    node_type: str,
    operation: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Optional[CredentialInfo]:
    """
    Get credential information for a node type by introspecting its schema.

    Returns CredentialInfo if the node requires credentials that should be
    prompted during workflow generation. This includes:
    - OAuth nodes (have x-oauth-provider in schema)
    - Nodes with required API tokens (like Telegram bot tokens)

    Returns None for:
    - Nodes without credentials
    - Nodes with optional credentials (like HTTP Request)
    - Trigger nodes
    """
    if node_type == 'agent':
        # Dynamic: depends on config.model + harness sub-model, not the schema.
        req = agent_credential_requirement(config)
        if not req.required:
            return None
        return CredentialInfo(
            # Both carry the real DB type: 'agent' names no credential, and
            # provider_key is what the [credentials: X ✓] status line shows.
            provider_key=req.credential_type,
            credential_type=req.credential_type,
            label=req.label,
            is_oauth=False,
        )
    schema, cred_refs = _credential_schema_refs(node_type, operation, config)
    if not cred_refs:
        return None

    # Check if ANY credential type is OAuth
    is_oauth = False
    for cred_ref in cred_refs:
        ref_name = cred_ref.split('/')[-1]
        cred_def = schema.get('$defs', {}).get(ref_name)
        if cred_def and cred_def.get('x-oauth-provider'):
            is_oauth = True
            break

    # Auto-prompt for every credentialed node. Gating only on OAuth leaves
    # API-key nodes without a credential signal and permits unrunnable
    # workflows to be drafted.
    if credentials_truly_optional(node_type):
        return None

    # Derive the provider key for frontend
    provider_key = _derive_provider_key(node_type)

    # Extract credential_type from schema (e.g., 'google_gmail_oauth')
    credential_type = derive_credential_type(node_type, operation, config)

    # Generate human-readable label
    label = f"{provider_key.replace('_', ' ').title()} Account"

    return CredentialInfo(
        provider_key=provider_key,
        credential_type=credential_type,
        label=label,
        is_oauth=is_oauth,
    )


def _agent_env_status_line(config: Optional[Dict[str, Any]], node_id: str) -> Optional[str]:
    """Brain-facing status for a declared sandbox env-var need, or None when the
    agent didn't declare one. Fulfilled = an agent_env credential is attached
    (we can't cheaply verify it covers every name — attaching is the signal)."""
    from nodes.agent.user_env import requested_env_var_names

    names = requested_env_var_names(config)
    if not names:
        return None
    cred_ids = (config or {}).get('credentialIds', {})
    if isinstance(cred_ids, dict) and cred_ids.get('agent_env'):
        return f"[env vars: {', '.join(names)} ✓]"
    return (
        f"[env vars needed: {', '.join(names)}] "
        f"Ask the user to provide these — <ask node=\"{node_id}\" field=\"env\" /> "
        f"(headless runs mint a shareable link), or tell them to add the values in "
        f"the agent's Credentials → Advanced → Environment variables."
    )


def _attached_unhealthy_line(
    provider: str, attached_id: Optional[str], health: Optional[Dict[str, Any]]
) -> Optional[str]:
    """Dead-session line for an ATTACHED credential, or None when healthy /
    unknown. ``health`` maps credential id → CredentialHealth (populated
    out-of-band on GraphState); absent id = unknown = healthy, so surfaces
    without the pre-fetch keep today's plain ✓."""
    verdict = (health or {}).get(str(attached_id)) if attached_id else None
    if verdict is None or verdict.healthy:
        return None
    return (
        f"[credentials: {provider} ✗ attached but DISCONNECTED "
        f"(session {verdict.status})] {verdict.hint or ''}".rstrip()
    )


def credential_status_line(
    node_type: str,
    operation: Optional[str],
    config: Optional[Dict[str, Any]],
    node_id: str,
    health: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """One-line credential status for brain-facing node renderings (execution
    summaries and the workflow snapshot). None when there's nothing useful to
    say (non-integration node, or an API-key node we don't auto-prompt for).
    ``health``: optional credential-id → CredentialHealth map; when a referenced
    credential is definitively dead the ✓ becomes an actionable ✗ line.
    """
    if node_type == 'agent':
        # Declared sandbox env-var need (canvas-level, opt-in). Independent of the
        # model credential below — agent_env is a NON-PRIMARY credential, so it
        # neither satisfies nor is required by the model line. Only surfaces when
        # the brain has declared names AND no agent_env credential is attached yet.
        env_line = _agent_env_status_line(config, node_id)
        req = agent_credential_requirement(config)
        if not req.required:
            base = (
                "[credentials: not required — this model runs on NoClick's "
                "platform key and is billed per use]"
            )
            return f"{base} {env_line}" if env_line else base
        cred_ids = (config or {}).get('credentialIds', {})
        # Any accepted type satisfies (API-key bundle OR subscription OAuth).
        if isinstance(cred_ids, dict) and any(
            cred_ids.get(t) for t in req.accepted_types
        ):
            attached_id = next(
                (cred_ids.get(t) for t in req.accepted_types if cred_ids.get(t)), None
            )
            base = (
                _attached_unhealthy_line(req.provider, attached_id, health)
                or f"[credentials: {req.provider} ✓]"
            )
        else:
            base = (
                f"[credentials needed: {req.label}] "
                f"Use <search_credentials type=\"{req.credential_type}\" /> to find credentials, "
                f"then <set_credentials node=\"{node_id}\" id=\"CREDENTIAL_ID\" />"
            )
        return f"{base} {env_line}" if env_line else base
    cred_info = get_credential_info(node_type, operation, config)
    if cred_info:
        cred_ids = (config or {}).get('credentialIds', {})
        attached_id = cred_ids.get(cred_info.credential_type) or cred_ids.get(cred_info.provider_key)
        if attached_id:
            return (
                _attached_unhealthy_line(cred_info.provider_key, attached_id, health)
                or f"[credentials: {cred_info.provider_key} ✓]"
            )
        search_type = cred_info.credential_type or cred_info.provider_key
        return (
            f"[credentials needed: {cred_info.provider_key}] "
            f"Use <search_credentials type=\"{search_type}\" /> to find credentials, "
            f"then <set_credentials node=\"{node_id}\" id=\"CREDENTIAL_ID\" />"
        )
    # Positive signal — absence of [credentials needed] alone doesn't stop the
    # brain from pattern-matching "integration node → connect account".
    if credentials_truly_optional(node_type) or (
        node_type.startswith('automation-')
        and not node_requires_credentials(node_type, operation, config)
    ):
        return "[credentials: not required for this operation]"
    return None


def trigger_status_line(
    node_type: str,
    operation: Optional[str],
    config: Optional[Dict[str, Any]],
) -> Optional[str]:
    """One-line trigger registration context for brain-facing renderings.

    Gives the brain the registration model it can't infer from config alone:
    app-event triggers (Slack/HubSpot/Discord) have NO webhook URL — events
    arrive at NoClick's shared app endpoint via a subscription that registers
    automatically on save (operation + credential are all it needs). Without
    this the brain invents webhook-URL mental models and manual registration
    steps (2026-07-30 interface-chat transcript).
    """
    if not operation:
        return None
    from utils.webhook_manager import WebhookManager, _app_event_trigger_class

    if not WebhookManager.operation_requires_registration(node_type, operation):
        return None
    cfg = config or {}
    is_app_event = _app_event_trigger_class(node_type) is not None
    kind = "trigger (app-event — no webhook URL)" if is_app_event else "trigger"
    if cfg.get("trigger_registered") is True:
        status = cfg.get("subscription_status") or "registered"
        return f"[{kind}: {status}]"
    if cfg.get("trigger_error"):
        return (
            f"[{kind}: NOT registered — {cfg['trigger_error']}. Registration "
            f"re-runs automatically when operation/credentials are saved]"
        )
    if is_app_event:
        return (
            f"[{kind}: not yet registered — registers automatically once a "
            f"credential is attached; no URL or manual setup involved]"
        )
    # Webhook-family nodes surface their state via the webhook_url config
    # field already rendered in the snapshot.
    return None


def missing_required_fields(
    node_type: str,
    operation: Optional[str],
    config: Optional[Dict[str, Any]],
    user_fields: Optional[List[str]] = None,
) -> List[str]:
    """Required fields of the selected operation with no usable value.

    Fields already flagged for user input are excluded (they render as
    [needs user input]). Empty string counts as missing — node drafter sometimes
    emits value="" when it doesn't know.
    """
    schema = get_operation_schema(node_type, operation or 'default')
    if not schema:
        return []
    cfg = config or {}
    pending = set(user_fields or [])
    missing = []
    for name in schema.get('required', []):
        if name in ('operation', 'credentials') or name in pending:
            continue
        value = cfg.get(name)
        if value is None or value == '':
            missing.append(name)
    return missing
