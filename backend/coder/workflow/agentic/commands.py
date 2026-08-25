"""Apply the public workflow XML operations and build result summaries."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol, Set, Tuple, TYPE_CHECKING

from opentelemetry import trace

from ..graph_state import GraphState, NodeState
from ..workflow_xml import XmlOp, coerce_value, coerce_value_for_field
from ..workflow_ops import (
    STRUCTURAL_TOOL_TYPES,
    drop_stale_agent_discriminator,
    is_trigger_source,
    resolve_sticky_note_position,
    create_sticky_note_dict,
    update_node_settings,
    merge_credentials,
    node_has_credential,
    strip_agent_trigger_message_refs,
    strip_label_sidecars,
    strip_placeholder_auth_headers,
    http_auth_credential_hint,
    mcp_hosting_conflict,
    provider_dataflow_conflict,
    resolve_tools_edge,
    trigger_provider_conflict,
    validate_agent_tool_operations,
)
from ..operation_catalog import (
    get_operations_for_node_type,
    get_operation_schema,
    get_operation_config_class,
    credential_status_line,
    credentials_truly_optional,
    get_credential_info,
    known_credential_types,
    missing_required_fields,
    node_accepted_credential_types,
    node_requires_credentials,
    reject_invalid_config_values,
    validate_node_config,
)
from utils.capabilities import NODE_GUIDANCE, capability


def load_node_guidance(*args, **kwargs):
    """Curated per-node guidance, where a platform provides it. Without one the
    brain relies on the node catalog's own descriptions."""
    load = capability(NODE_GUIDANCE)
    return load(*args, **kwargs) if load is not None else None
from ..option_registries.resolver import (
    resolve_field_value,
    format_resolution_block,
)

if TYPE_CHECKING:
    from ..builder_events import BuilderStreamEvent

logger = logging.getLogger(__name__)
# Public operation spans share one stable builder namespace.
_tracer = trace.get_tracer("noclick.builder")


# Tags the agentic brain is allowed to emit
AGENTIC_TAGS: Set[str] = {
    # Graph mutations
    'add_node', 'add_edge', 'remove_node', 'remove_edge',
    'add_sticky_note',
    # Config
    'field', 'set_credentials',
    # Execution settings
    'update_settings',
    # Queries
    'query_operations', 'query_schema', 'search_credentials', 'read',
    # Workflow management
    'list_workflows', 'open_workflow', 'create_workflow',
    # Folder management
    'list_folders', 'create_folder', 'delete_folder', 'move_workflow',
    # Config inspection
    'read_config',
    # Node output inspection and execution
    'get_output', 'run_node',
    # Workflow variables + test runs
    'define_variable', 'add_test_run', 'run_test',
    # Output
    'message',
    # User input (blocking request to user)
    'ask',
    # Control
    'done',
}


def _topo_sort_field_asks(asks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sort field-bound (non-credential) asks so dependents come after parents.

    Reads ``x-dynamic-options.depends_on`` from each ask's already-resolved
    ``fieldSchema`` (set by ``_resolve_ask_field_schema``), so this works for
    provider nodes too — it no longer depends on the node carrying a concrete
    operation. If a referenced parent isn't itself in the batch, the dependent
    ask still gets emitted in its original relative position — the snapshot
    logic in the drawer (or a later turn) will deal with it. Cycles are
    detected and the asks fall back to original order.
    """
    asks_by_field: Dict[str, Dict[str, Any]] = {a['fieldKey']: a for a in asks if a.get('fieldKey')}

    def depends_on(field: str) -> Optional[str]:
        ask = asks_by_field.get(field)
        dyn = (ask.get('fieldSchema') or {}).get('x-dynamic-options') if ask else None
        return dyn.get('depends_on') if isinstance(dyn, dict) else None

    visited: Set[str] = set()
    visiting: Set[str] = set()
    ordered: List[Dict[str, Any]] = []

    def visit(field: str) -> None:
        if field in visited or field in visiting:
            return  # already done, or cycle — skip
        visiting.add(field)
        ask = asks_by_field.get(field)
        if ask:
            dep = depends_on(field)
            if dep and dep in asks_by_field:
                visit(dep)
            ordered.append(ask)
            visited.add(field)
        visiting.discard(field)

    for ask in asks:
        fk = ask.get('fieldKey')
        if fk:
            visit(fk)
    return ordered


def _post_process_node_asks(requests: List[Dict[str, Any]], graph_state: 'GraphState') -> List[Dict[str, Any]]:
    """Group field-bound asks by node, auto-inject missing credential asks,
    and topo-sort by depends_on. Free-form asks (no nodeId) are passed through
    in their original position. Cross-node order is preserved by first-occurrence.
    """
    result: List[Dict[str, Any]] = []
    handled_nodes: Set[str] = set()

    for req in requests:
        node_id = req.get('nodeId') or ''
        if not node_id:
            result.append(req)
            continue
        if node_id in handled_nodes:
            continue
        handled_nodes.add(node_id)

        group = [r for r in requests if r.get('nodeId') == node_id]
        node = graph_state.get_node(node_id)
        if not node:
            result.extend(group)
            continue

        cred_asks = [a for a in group if a.get('fieldKey') == 'credential']
        field_asks = [a for a in group if a.get('fieldKey') and a.get('fieldKey') != 'credential']

        # Auto-inject a credential ask if the node needs creds, has none attached,
        # and the brain didn't already ask for one. Required for any non-cred
        # field-bound ask to be useful (the picker can't load options otherwise).
        if field_asks and not cred_asks:
            if not node_has_credential(node.config):
                cred_info = get_credential_info(node.type, node.operation, node.config)
                if cred_info:
                    cfg = node.config or {}
                    cred_asks.append({
                        'id': f'auto_cred_{node_id}',
                        'nodeId': node_id,
                        'nodeType': node.type,
                        'fieldKey': 'credential',
                        'type': 'credential',
                        'label': f'Connect {cred_info.label}',
                        'description': '',
                        'required': True,
                        'credentialType': cred_info.credential_type,
                        'credentialIds': cfg.get('credentialIds', {}),
                        'nodeConfig': {k: v for k, v in cfg.items() if k != 'credentialIds'},
                    })

        sorted_field_asks = _topo_sort_field_asks(field_asks)
        result.extend(cred_asks + sorted_field_asks)

    return result


async def autoselect_single_credentials(
    node_ids: List[str],
    graph_state: 'GraphState',
    platform_ops: Optional['PlatformOps'],
) -> List[str]:
    """Attach a credential to newly-added nodes when the choice is unambiguous.

    For each node in ``node_ids`` that needs credentials and has none, look up
    the user's credentials of the matching type. If the user has *exactly one*,
    attach it — there is no decision to make. With zero or 2+, leave it unset so
    the credential picker (or the brain's ``<set_credentials>``) decides.

    Returns the ids of nodes that received a credential.
    """
    if not platform_ops or not node_ids:
        return []

    # Nodes that need a credential and don't have one yet, paired with EVERY
    # credential_type their selected operation accepts (all union members —
    # e.g. slack_oauth + slack_bot_token, or an agent harness's API-key type +
    # its subscription-OAuth type). Searching only the first/primary type
    # would miss a user whose single satisfying credential is another member.
    pending: List[tuple[NodeState, str, Tuple[str, ...]]] = []
    for nid in node_ids:
        node = graph_state.get_node(nid)
        if not node:
            continue
        if node_has_credential(node.config):
            continue
        cred_info = get_credential_info(node.type, node.operation, node.config)
        if not cred_info or not cred_info.credential_type:
            continue
        accepted = node_accepted_credential_types(node.type, node.operation, node.config)
        pending.append((
            node,
            cred_info.credential_type,
            tuple(sorted(accepted)) or (cred_info.credential_type,),
        ))

    if not pending:
        return []

    # One org-aware lookup per distinct credential type.
    creds_by_type: Dict[str, List[Dict[str, Any]]] = {}
    for cred_type in {ct for _, _, types in pending for ct in types}:
        creds_by_type[cred_type] = await platform_ops.search_credentials(cred_type, '', 50)

    attached: List[str] = []
    placed_cred_ids: List[str] = []
    for node, primary_type, accepted_types in pending:
        # A sole credential of the PRIMARY type wins outright; otherwise a
        # sole credential across ALL accepted types. One of each accepted
        # type is only ambiguous when none of them is the primary.
        matching = [(primary_type, c) for c in creds_by_type.get(primary_type, [])]
        if len(matching) != 1:
            matching = [
                (ct, cred) for ct in accepted_types for cred in creds_by_type.get(ct, [])
            ]
        if len(matching) != 1:
            continue
        cred_type, cred = matching[0]
        merge_credentials(node.config, {cred_type: cred['id']})
        placed_cred_ids.append(cred['id'])
        attached.append(node.id)
    # Authorize auto-attached credentials for run-as-owner resolution (owner-gated
    # in platform_ops). The frontend autosave that persists these no longer authorizes.
    if placed_cred_ids:
        await platform_ops.authorize_credentials(placed_cred_ids)
    return attached


def _normalize_op_allowlist(value: Any) -> Set[str]:
    """Coerce a node's ``agent_tool_operations`` config value into a set of
    operation names. Stored either as a real list or a JSON string."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return set()
    if isinstance(value, list):
        return {v for v in value if isinstance(v, str)}
    return set()


def _field_value_signature(prop: Dict[str, Any]) -> Tuple[Any, ...]:
    """A signature of what *values* a field's widget would show.

    Two same-named fields on different operations are only genuinely
    ambiguous when their option source differs — a dynamic loader keyed on a
    different ``field_name``/``depends_on``, or a different ``enum``. Cosmetic
    differences (title, placeholder, description) must NOT trigger ambiguity,
    so they're excluded from the signature.
    """
    dyn = prop.get('x-dynamic-options')
    if isinstance(dyn, dict):
        return ('dynamic', dyn.get('field_name'), dyn.get('depends_on'))
    enum = prop.get('enum')
    if isinstance(enum, list):
        return ('enum', tuple(str(v) for v in enum))
    return ('plain',)


def _resolve_ask_field_schema(
    node: 'NodeState', field: str, explicit_operation: Optional[str] = None,
) -> Tuple[Optional[str], Optional[Dict[str, Any]], Optional[str]]:
    """Resolve which operation's schema defines ``field`` for an ``<ask>``.

    Returns ``(operation, field_schema, error)``:
      - ``(op, schema, None)``  — resolved; render the field with ``schema``.
      - ``(None, None, msg)``   — invalid/ambiguous; caller rejects with ``msg``.

    A live picker is fundamentally ``(node_type, field-with-x-dynamic-options,
    credential)`` — it does NOT require the node's *selected* operation to be
    the one carrying the field. Provider nodes (operation ``default``) and
    operation-bearing nodes before their op is chosen both need the field's
    schema resolved from somewhere other than the selected operation. The
    ladder below resolves from the most specific operation available, and
    *rejects rather than guesses* when a same-named field diverges across
    operations (so the user never gets the wrong dropdown).
    """
    node_type = node.type

    def prop_for(operation: str) -> Optional[Dict[str, Any]]:
        schema = get_operation_schema(node_type, operation)
        props = (schema or {}).get('properties', {}) if schema else {}
        return props.get(field) if props else None

    # 1. Explicit operation= on the ask — the brain's deterministic override.
    if explicit_operation:
        if get_operation_schema(node_type, explicit_operation) is None:
            return None, None, (
                f"<ask> rejected: '{node_type}' has no operation '{explicit_operation}'."
            )
        prop = prop_for(explicit_operation)
        if prop is None:
            return None, None, (
                f"<ask> rejected: '{field}' is not a config field on "
                f"{node_type}:{explicit_operation}."
            )
        return explicit_operation, prop, None

    # 2. Node's concrete operation (a real op, not the provider 'default').
    #    The selected operation already disambiguates same-named fields.
    if node.operation and node.operation != 'default':
        schema = get_operation_schema(node_type, node.operation)
        props = (schema or {}).get('properties', {}) if schema else {}
        if props:
            if field not in props:
                return None, None, (
                    f"<ask> rejected: '{field}' is not a config field on "
                    f"{node_type}:{node.operation}. "
                    f"Valid fields: {', '.join(sorted(props))}."
                )
            return node.operation, props[field], None

    # 3/4. No concrete operation. Prefer the provider's allowlist (it narrows
    #      to the operations the agent will actually use, which can resolve an
    #      otherwise-ambiguous field); fall back to every operation of the type
    #      (the value may be destined for the agent's prompt, not a tool arg).
    all_ops = [op.name for op in get_operations_for_node_type(node_type)]
    allow = _normalize_op_allowlist((node.config or {}).get('agent_tool_operations'))
    candidate_sets: List[List[str]] = []
    if allow:
        candidate_sets.append([op for op in all_ops if op in allow])
    candidate_sets.append(all_ops)

    for candidates in candidate_sets:
        matches = [(op, prop_for(op)) for op in candidates]
        matches = [(op, p) for op, p in matches if p is not None]
        if not matches:
            continue
        if len({_field_value_signature(p) for _op, p in matches}) > 1:
            return None, None, (
                f"<ask> rejected: '{field}' resolves to different option sources "
                f"across operations of {node_type} "
                f"({', '.join(op for op, _ in matches)}); set the node's operation, "
                f"narrow agent_tool_operations, or pass operation= on the <ask>."
            )
        op, prop = matches[0]
        return op, prop, None

    # Field isn't defined on any operation of the node type.
    return None, None, (
        f"<ask> rejected: '{field}' is not a config field on any operation of {node_type}."
    )


def extract_ask_requests(
    ops: List[XmlOp], graph_state: Optional['GraphState'] = None,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Convert ``<ask>`` XmlOps into serializable dicts for the frontend.

    Two shapes the brain can emit:
      1. Field-bound: ``<ask node="X" field="Y" label="..." />``
         The frontend renders the right widget by introspecting the field's
         schema. ``field="credential"`` is a magic value that routes to the
         credential picker; any other field key resolves to its JSON schema
         property (which carries ``x-dynamic-options``, ``enum``, etc.).
      2. Free-form: ``<ask label="...">opt A\\nopt B</ask>`` for selection
         (``multiple="true"`` renders checkboxes instead of radios), or
         ``<ask label="..." />`` for plain text. Used when the question
         isn't tied to a specific node config field.

    Returns ``(requests, rejections)``. Invalid field-bound asks — unknown
    node, credential ask on an operation that needs no credentials, or a
    field that isn't on the operation's schema — are dropped and explained
    in ``rejections`` so the builder can feed the error back to the brain
    instead of showing the user a junk question.
    """
    requests: List[Dict[str, Any]] = []
    rejections: List[str] = []
    for i, op in enumerate(ops):
        if op.tag != 'ask':
            continue
        node_ref = op.attrs.get('node', '')
        field = op.attrs.get('field', '')
        req: Dict[str, Any] = {
            'id': op.attrs.get('id', f'ask_{i}'),
            'nodeId': node_ref,
            'label': op.attrs.get('label', ''),
            'description': op.attrs.get('description', ''),
            'required': op.attrs.get('required', 'true').lower() != 'false',
        }

        if node_ref and field:
            node = graph_state.get_node(node_ref) if graph_state else None
            if graph_state is not None and not node:
                rejections.append(
                    f"<ask> rejected: node '{node_ref}' not found in the workflow."
                )
                continue
            req['nodeType'] = node.type if node else ''
            req['fieldKey'] = field

            if field == 'credential':
                if node and not node_requires_credentials(node.type, node.operation, node.config):
                    rejections.append(
                        f"<ask> rejected: {node_ref} ({node.type}:{node.operation or 'default'}) "
                        f"does not require credentials for its selected operation — "
                        f"do not ask the user to connect an account for it."
                    )
                    continue
                req['type'] = 'credential'
                if node:
                    cred_info = get_credential_info(node.type, node.operation, node.config)
                    if cred_info:
                        req['credentialType'] = cred_info.credential_type
                        if not req['label']:
                            req['label'] = f"Connect {cred_info.label}"
                    if not req.get('credentialType'):
                        # get_credential_info gates on OAuth/allowlist; nodes
                        # outside it (WhatsApp QR, API keys) still need a type
                        # so the public bridge can mint a provide link. The
                        # ungated def-scan covers every credentialed node.
                        from coder.workflow.operation_catalog import (
                            derive_credential_type,
                        )

                        req['credentialType'] = derive_credential_type(
                            node.type, node.operation, node.config
                        )
                    # Config-sensitive credential forms (agent: harness +
                    # sub-model pick the fields; mcp-server: auth mode) need
                    # the node's config to render the right inputs.
                    cfg = node.config or {}
                    req['credentialIds'] = cfg.get('credentialIds', {})
                    req['nodeConfig'] = {k: v for k, v in cfg.items() if k != 'credentialIds'}
            elif field == 'env':
                # Sandbox env-var request: the variables come from the node's
                # declared agent_env_requested (set first via <field
                # name="agent_env_requested" ...>). Values are collected as a
                # key/value form and become an agent_env credential on submit —
                # never stored raw. The env keys, not a schema field, drive the UI.
                from nodes.agent.user_env import normalize_requested_env_vars

                declared, _ = normalize_requested_env_vars(
                    (node.config or {}).get('agent_env_requested')
                ) if node else ([], None)
                if not declared:
                    rejections.append(
                        f"<ask> rejected: {node_ref} has no agent_env_requested — declare "
                        f"the variables first with <field node=\"{node_ref}\" "
                        f"name=\"agent_env_requested\" value='[\"NAME\"]' />, then ask for them."
                    )
                    continue
                req['type'] = 'env'
                req['fieldKey'] = 'env'
                req['envKeys'] = declared
                if not req['label']:
                    names = ", ".join(e['name'] for e in declared)
                    req['label'] = f"Provide environment variables: {names}"
            else:
                req['type'] = 'config'
                if node:
                    # Resolve the field's schema independently of the node's
                    # selected operation (a provider node carries 'default', so
                    # its dynamic-options fields live in its allowlisted/other
                    # operations' schemas, not the selected one). Ambiguous or
                    # unknown fields are rejected — never silently degraded to a
                    # plain textbox, which gives the user the wrong picker and
                    # the brain no feedback.
                    explicit_op = op.attrs.get('operation') or None
                    _operation, field_schema, error = _resolve_ask_field_schema(
                        node, field, explicit_op
                    )
                    if error:
                        rejections.append(error)
                        continue
                    # Snapshot the node's current credentials + sibling config so
                    # the picker (DynamicOptionsField) has what it needs to load
                    # options, without coupling the drawer to any particular
                    # frontend valtio path.
                    cfg = node.config or {}
                    req['credentialIds'] = cfg.get('credentialIds', {})
                    req['nodeConfig'] = {k: v for k, v in cfg.items() if k != 'credentialIds'}
                    # If the node already has a value for this field (e.g., drafter
                    # extracted a real ID from the user's prompt), seed the
                    # picker with it so the user just confirms instead of
                    # picking from scratch.
                    existing = cfg.get(field)
                    if existing is not None and existing != '':
                        req['defaultValue'] = str(existing)
                    if field_schema is not None:
                        req['fieldSchema'] = field_schema
        elif op.body:
            req['type'] = 'selection'
            # multiple="true" → multi-select checkboxes; the answer comes back
            # as a comma-joined list of the chosen options.
            req['multiple'] = op.attrs.get('multiple', '').lower() == 'true'
            req['options'] = [
                {'id': line.strip(), 'label': line.strip()}
                for line in op.body.strip().splitlines()
                if line.strip()
            ]
        else:
            req['type'] = 'text'

        requests.append(req)

    if graph_state:
        requests = _post_process_node_asks(requests, graph_state)

    return requests, rejections


def _get_valid_config_keys(node_type: str, operation: Optional[str] = None) -> Optional[Set[str]]:
    """Return the set of valid config field names for a node type + operation.

    Uses the Pydantic schema to determine which keys are real config fields.
    Returns ``None`` if the schema can't be resolved (caller should skip filtering).
    """
    return GraphState._get_valid_config_keys(node_type, operation)


def group_ops(ops: List[XmlOp]) -> Dict[str, List[XmlOp]]:
    """Group operations by tag for ordered execution."""
    groups: Dict[str, List[XmlOp]] = {}
    for op in ops:
        groups.setdefault(op.tag, []).append(op)
    return groups


def execute_graph_mutations(
    ops: List[XmlOp],
    graph_state: GraphState,
) -> tuple[List[str], List[str]]:
    """
    Execute graph mutation ops (add_node, add_edge, remove_edge, remove_node).

    Returns:
        (results, new_node_ids): Human-readable results and IDs of newly added nodes.
    """
    groups = group_ops(ops)
    results: List[str] = []
    new_node_ids: List[str] = []

    # Process in order: remove_edge → remove_node → add_node → add_edge.
    # Removes run first so the brain can emit a `<remove_node>` plus a
    # replacement `<add_node>` with the SAME name in one turn and have it
    # behave as a real replace — under the old order the add ran first,
    # collided with the existing node, skipped as "already exists", and then
    # the remove wiped the original, leaving nothing.
    from nodes.core.registry import NODE_REGISTRY
    # Track names the brain tried to add but we rejected. Used to give edges
    # that reference those names a specific "was rejected earlier" error
    # instead of a generic "target not found" — that steers the retry more
    # cleanly (the brain knows to swap the type, not redeclare the node).
    rejected_node_names: Set[str] = set()

    for op in groups.get('remove_edge', []):
        from_name = op.attrs.get('from', '')
        to_name = op.attrs.get('to', '')
        if graph_state.remove_edge(from_name, to_name):
            results.append(f"Removed edge: {from_name} → {to_name}")

    for op in groups.get('remove_node', []):
        name = op.attrs.get('name', '')
        if graph_state.remove_node(name):
            results.append(f"Removed node '{name}'")

    for op in groups.get('add_node', []):
        name = op.attrs.get('name', '')
        node_type = op.attrs.get('type', '')
        label = op.attrs.get('label', name)
        goal = op.attrs.get('goal', '')
        description = op.attrs.get('description', '')

        # Reject invented node types early — otherwise graph_state stores a
        # broken node that renders as a blank rectangle in the canvas and
        # no operation / schema is resolvable downstream. Reporting the
        # failure back to the brain lets it retry with a valid type or
        # collapse the work into automation-serverless-function.
        if node_type not in NODE_REGISTRY:
            rejected_node_names.add(name)
            results.append(
                f"ERROR: add_node '{name}' skipped — '{node_type}' is not a valid NoClick node type. "
                f"Pick a type from the Available Node Types list above, or fall back to "
                f"`automation-serverless-function` with custom code."
            )
            continue

        # If brain set operation= instead of goal=, convert it to a goal hint
        # (the brain shouldn't pick operations — node drafter does that)
        brain_operation = op.attrs.get('operation', '')
        if brain_operation and not goal:
            goal = f"{label} (hint: {brain_operation})"

        # n8n import: brain tags each translated node with the source n8n node IDs.
        # Resolved against graph._n8n_context by node drafting for full-param context.
        refs_attr = op.attrs.get('n8n_refs', '')
        n8n_refs = [r.strip() for r in refs_attr.split(',') if r.strip()] if refs_attr else None

        node = graph_state.add_node(
            name=name,
            node_type=node_type,
            label=label,
            goal=goal,
            description=description,
            n8n_refs=n8n_refs,
        )
        if node:
            new_node_ids.append(node.id)
            results.append(f"Added node '{name}' ({node_type})")
        else:
            results.append(f"Node '{name}' already exists, skipped")

    for op in groups.get('add_edge', []):
        from_name = op.attrs.get('from', '')
        to_name = op.attrs.get('to', '')
        handle = op.attrs.get('handle')

        # Missing attrs — malformed op from the brain.
        if not from_name or not to_name:
            results.append(
                "ERROR: add_edge skipped — both `from` and `to` attributes are required."
            )
            continue

        # Already wired — idempotent skip with a specific message so the
        # brain doesn't mistake it for a failure.
        if (from_name, to_name) in graph_state.edge_set:
            results.append(f"Edge {from_name} → {to_name} already exists, skipped")
            continue

        # Endpoint references a name that was rejected by add_node in this
        # turn. That's a different failure mode than "doesn't exist" —
        # redeclaring the edge without fixing the node first won't help.
        if from_name in rejected_node_names:
            results.append(
                f"ERROR: add_edge {from_name} → {to_name} skipped — source '{from_name}' "
                f"was rejected on add_node earlier this turn. Fix that node's type first."
            )
            continue
        if to_name in rejected_node_names:
            results.append(
                f"ERROR: add_edge {from_name} → {to_name} skipped — target '{to_name}' "
                f"was rejected on add_node earlier this turn. Fix that node's type first."
            )
            continue

        # Truly missing endpoints.
        if from_name not in graph_state.nodes:
            results.append(
                f"ERROR: add_edge {from_name} → {to_name} skipped — source node "
                f"'{from_name}' does not exist. Add it first with <add_node>."
            )
            continue
        if to_name not in graph_state.nodes:
            results.append(
                f"ERROR: add_edge {from_name} → {to_name} skipped — target node "
                f"'{to_name}' does not exist. Add it first with <add_node>."
            )
            continue

        # Tool-provider edges (type="tools" or handle="top", plus auto-normalized
        # tool/mcp-server/alarm/filesystem → agent edges): top→bottom handles,
        # source operations become agent tools instead of dataflow.
        source_type = graph_state.nodes[from_name].type
        target_type = graph_state.nodes[to_name].type
        tools_handles, tools_err = resolve_tools_edge(
            source_type, target_type,
            edge_type=op.attrs.get('type'), source_handle=handle,
        )
        if tools_err:
            results.append(f"ERROR: add_edge {from_name} → {to_name} skipped — {tools_err}")
            continue
        # Provider mode and dataflow are mutually exclusive on the source node
        # (mirrors FlowCanvas.isValidConnection).
        existing_edges = [
            {'source': e.source_id, 'targetHandle': e.target_handle}
            for e in graph_state.edges.values()
        ]
        conflict = provider_dataflow_conflict(
            from_name, existing_edges, new_edge_is_tools=tools_handles is not None,
        )
        if conflict:
            results.append(f"ERROR: add_edge {from_name} → {to_name} skipped — {conflict}")
            continue
        if tools_handles:
            # Either-or: a trigger-operation node can't be a provider.
            src = graph_state.nodes[from_name]
            trig_conflict = trigger_provider_conflict(
                source_type, src.operation or (src.config or {}).get('operation'),
            )
            if trig_conflict:
                results.append(f"ERROR: add_edge {from_name} → {to_name} skipped — {trig_conflict}")
                continue
            # Either-or: an MCP node hosts wired tools XOR proxies an external server.
            host_conflict = mcp_hosting_conflict(
                target_type, graph_state.nodes[to_name].config,
            )
            if host_conflict:
                results.append(f"ERROR: add_edge {from_name} → {to_name} skipped — {host_conflict}")
                continue
        if tools_handles:
            edge = graph_state.add_edge(
                from_name, to_name,
                source_handle=tools_handles[0], target_handle=tools_handles[1],
            )
            if edge:
                hint = (
                    f" Set its allowlist next: <field node=\"{from_name}\" "
                    f"name=\"agent_tool_operations\" value='[\"op_name\", ...]' /> "
                    f"(use <query_operations> to list operation names)."
                    if source_type not in STRUCTURAL_TOOL_TYPES else ""
                )
                results.append(
                    f"Added tools edge: {from_name} now provides agent tools to {to_name}.{hint}"
                )
            else:
                last_err = graph_state.errors[-1] if graph_state.errors else "rejected by graph validation"
                results.append(f"ERROR: add_edge {from_name} → {to_name} skipped — {last_err}")
            continue

        # Validate the handle against the source node's declared output handles.
        # Collapsed branching (e.g., n8n IF → automation-serverless-function)
        # silently lost semantics when handle="true"/"false" was accepted on a
        # single-output node. Fail loudly so the brain encodes the branch as
        # part of the node's logic instead.
        if handle:
            source_class = NODE_REGISTRY.get(source_type)
            source_handles = source_class.get_output_handles() if source_class else None
            valid_handles = {h['id'] for h in (source_handles or []) if isinstance(h, dict) and 'id' in h}
            if not valid_handles:
                results.append(
                    f"ERROR: add_edge {from_name} → {to_name} has handle=\"{handle}\" but source "
                    f"'{from_name}' ({source_type}) is a single-output node with no named handles. "
                    f"Branching semantics must live INSIDE the source node (e.g., a serverless "
                    f"function returns a status field and downstream nodes check it) — not via "
                    f"an edge handle. Re-emit without `handle=`, and encode the branch in the "
                    f"source node's config."
                )
                continue
            if handle not in valid_handles:
                valid_list = ', '.join(f'"{h}"' for h in sorted(valid_handles))
                results.append(
                    f"ERROR: add_edge {from_name} → {to_name} has handle=\"{handle}\" but source "
                    f"'{from_name}' ({source_type}) only supports handles: {valid_list}."
                )
                continue

        edge = graph_state.add_edge(from_name, to_name, source_handle=handle)
        if edge:
            results.append(f"Added edge: {from_name} → {to_name}")
        else:
            # Only remaining failure is validate_edge (connectionless node types).
            last_err = graph_state.errors[-1] if graph_state.errors else "rejected by graph validation"
            results.append(f"ERROR: add_edge {from_name} → {to_name} skipped — {last_err}")

    return results, new_node_ids


def execute_sticky_note_ops(
    ops: List[XmlOp],
    graph_state: GraphState,
) -> tuple[List[str], List[Dict[str, Any]]]:
    """Execute add_sticky_note ops using positioned nodes from graph_state.

    Returns (results, sticky_note_dicts) where each dict has id, type, position,
    config, width, height — ready for frontend rendering.
    """
    results: List[str] = []
    sticky_notes: List[Dict[str, Any]] = []

    # Build positioned node/edge lists from graph_state for position resolution
    nodes_for_pos = []
    nodes_with_pos = 0
    for nid, ns in graph_state.nodes.items():
        node_dict: Dict[str, Any] = {"id": nid, "type": ns.type, "position": ns.position or {"x": 0, "y": 0}}
        if ns.position:
            nodes_with_pos += 1
        if ns.width is not None:
            node_dict["width"] = ns.width
        if ns.height is not None:
            node_dict["height"] = ns.height
        nodes_for_pos.append(node_dict)

    edges_for_pos = [
        {"source": es.source_id, "target": es.target_id}
        for es in graph_state.edges.values()
    ]
    logger.info(f"[StickyNote] {len(nodes_for_pos)} nodes ({nodes_with_pos} with positions), {len(edges_for_pos)} edges")

    for op in ops:
        content = op.body or op.attrs.get("content", "")
        color = 8  # Always default to black
        name = op.attrs.get("name", "")

        sticky_config: Dict[str, Any] = {"content": content, "color": color}

        # Cover mode: after + before
        after_id = op.attrs.get("after")
        before_id = op.attrs.get("before")
        if after_id and before_id:
            sticky_config["_anchor_after"] = after_id
            sticky_config["_anchor_before"] = before_id
        # Near mode: near + direction
        elif "near" in op.attrs:
            near_ids = [n.strip() for n in op.attrs["near"].split(",")]
            sticky_config["_anchor_near"] = near_ids
            sticky_config["_anchor_direction"] = op.attrs.get("direction", "above")

        if "width" in op.attrs:
            sticky_config["_anchor_width"] = int(op.attrs["width"])
        if "height" in op.attrs:
            sticky_config["_anchor_height"] = int(op.attrs["height"])

        pos_result = resolve_sticky_note_position(nodes_for_pos, edges_for_pos, sticky_config)
        anchors = {ak: av for ak, av in sticky_config.items() if ak.startswith('_anchor')}
        logger.info(f"[StickyNote] '{name}' anchors={anchors} pos={pos_result['position']}, size={pos_result['width']}x{pos_result['height']}")
        node_dict = create_sticky_note_dict(
            sticky_config, pos_result["position"],
            pos_result["width"], pos_result["height"],
        )

        # Register in graph_state so subsequent sticky notes see this one's position
        sticky_node = NodeState(
            id=node_dict["id"], type="stickyNote", label=name or "Sticky Note",
            goal="", position=pos_result["position"],
            width=pos_result["width"], height=pos_result["height"],
            config=sticky_config,
        )
        graph_state.nodes[node_dict["id"]] = sticky_node
        nodes_for_pos.append(node_dict)

        sticky_notes.append(node_dict)
        results.append(f"Added sticky note '{name}' ({node_dict['id']})")

    return results, sticky_notes


def _mark_field_provided(node: NodeState, field_name: str) -> None:
    """A field write satisfies any pending ``[needs user input: …]`` flag —
    otherwise the stale flag keeps telling the brain the field is unset."""
    if field_name in node.user_fields:
        node.user_fields.remove(field_name)


# Fields the brain may legitimately set on a node in the SAME turn it adds that
# node, because node drafting never authors them:
#   - agent_tool_operations / agent_sandbox_repos — canvas-level provider config
#     with no operation-schema entry. Tool-provider nodes skip node drafting entirely
#     (builder gates on GraphState.is_tool_provider), so the brain is the
#     SOLE author of the allowlist / sandbox mounts. execute_field_ops validates
#     both against the node's real operations.
# Every other field on a freshly added node is left to node drafting, which selects the
# operation and fills its schema fields (a brain-set schema field would be clobbered,
# and the brain doesn't yet know the valid field names). Kept in sync with the
# same-turn EXCEPTIONS documented to the brain in agentic/prompts.py.
# `show_in_interface` is deliberately NOT here: the agent chat hosts the Test Run
# screen, so a same-turn hide breaks the closing <run_test/> demo. Hiding is
# reserved for explicit user requests; a same-turn attempt is dropped and can be
# re-issued next turn.
SAME_TURN_FIELD_ALLOWLIST = frozenset({
    'agent_tool_operations',
    'agent_sandbox_repos',
    'agent_env_requested',
})


def filter_premature_field_ops(ops: List[XmlOp]) -> Tuple[List[XmlOp], List[str]]:
    """Drop ``<field>`` ops that target a node added in this same turn, keeping
    only the same-turn exception fields the brain must author itself.

    Without this carve-out, an allowlist set in the same turn the provider node
    is added (the natural way the brain builds an agent-with-tools) is silently
    discarded, leaving the agent with zero tools. Field ops run after node drafting
    (see ``_execute_commands_streaming``), so the kept ones land without being
    overwritten. See ``SAME_TURN_FIELD_ALLOWLIST``.

    Returns ``(kept_ops, dropped_notes)`` — each drop produces a note for the
    brain's execution result, so it re-issues the field next turn instead of
    believing it was set (a silently dropped ``model`` left an agent on the
    default model with no credential ask).
    """
    new_node_names = {op.attrs.get('name', '') for op in ops if op.tag == 'add_node'}
    if not new_node_names:
        return ops, []
    kept: List[XmlOp] = []
    notes: List[str] = []
    for op in ops:
        if (
            op.tag == 'field'
            and op.attrs.get('node', '') in new_node_names
            and op.attrs.get('name', '') not in SAME_TURN_FIELD_ALLOWLIST
        ):
            notes.append(
                f"NOT applied: <field name=\"{op.attrs.get('name', '')}\" "
                f"node=\"{op.attrs.get('node', '')}\"> — the node was added this "
                f"turn, so node drafting configures it and would clobber the value. "
                f"Check the configured result below and re-issue the <field> next "
                f"turn if it still needs changing."
            )
        else:
            kept.append(op)
    return kept, notes


def credential_recheck_ids(field_ops: List[XmlOp], graph_state: GraphState) -> List[str]:
    """Node ids whose field ops changed a credential-RELEVANT field this batch.

    An agent's model / harness sub-model picks its billing rule
    (``agent_credential_requirement``), and any node's operation picks which
    credential schema applies — so a <field> write to one of these can flip a
    node from credential-free to credential-required after node drafting already
    ran its checks. Callers re-evaluate credentials for the returned nodes.
    """
    from nodes.agent.config.providers import HARNESS_SUBMODEL_FIELDS

    submodel_fields = set(HARNESS_SUBMODEL_FIELDS.values())
    out: List[str] = []
    for op in field_ops:
        node_id = op.attrs.get('node', '')
        field_name = op.attrs.get('name', '')
        node = graph_state.get_node(node_id)
        if not node or node_id in out:
            continue
        relevant = field_name == 'operation' or (
            node.type == 'agent'
            and (field_name == 'model' or field_name in submodel_fields)
        )
        if relevant:
            out.append(node_id)
    return out


def graph_has_active_trigger(graph_state: GraphState) -> bool:
    """True when an enabled node fires this workflow on its own (dedicated
    trigger-* node, or an integration node whose selected operation is a
    trigger). Decides whether a missing credential means "dormant until
    connected" or "fires on schedule and fails until connected"."""
    from nodes.agent.node_op_tools import is_trigger_operation

    return any(
        not (n.config or {}).get('disabled')
        and (
            (n.type or '').startswith('trigger-')
            or is_trigger_operation(n.type, n.operation)
        )
        for n in graph_state.nodes.values()
    )


def nodes_missing_credentials(graph_state: GraphState) -> List[NodeState]:
    """Enabled nodes whose selected operation requires credentials but have
    none attached (disabled nodes never execute, so they can't fail on it).

    Skips the truly-optional nodes: they carry credential $refs but run fine
    without them, so nagging about a public RSS feed is noise.
    """
    return [
        n for n in graph_state.nodes.values()
        if not (n.config or {}).get('disabled')
        and not credentials_truly_optional(n.type)
        and node_requires_credentials(n.type, n.operation, n.config)
        and not node_has_credential(n.config)
    ]


def execute_field_ops(
    ops: List[XmlOp],
    graph_state: GraphState,
) -> List[str]:
    """
    Execute field override operations.
    Validates field names against the node's schema when available.

    Returns human-readable results.
    """
    results: List[str] = []
    warned_nodes: set = set()  # Track nodes we've already shown valid fields for

    # Snapshot prior values so a wrong-typed write can be REVERTED after the
    # batch — an invalid value must never persist (it kills every run at the
    # node's runtime parse, which the brain never sees).
    _ABSENT = object()
    prior_values: Dict[Tuple[str, str], Any] = {}
    for op in ops:
        _n = graph_state.get_node(op.attrs.get('node', ''))
        _f = op.attrs.get('name', '')
        _key = (op.attrs.get('node', ''), _f)
        if _n and _key not in prior_values:
            prior_values[_key] = _n.config.get(_f, _ABSENT)

    for op in ops:
        node_name = op.attrs.get('node', '')
        field_name = op.attrs.get('name', '')
        raw_value = op.attrs.get('value', op.body or '')

        node = graph_state.get_node(node_name)
        if not node:
            results.append(f"Field error: node '{node_name}' not found")
            continue

        # __label keys are the frontend's display cache (DynamicOptionsField
        # recreates them from options) — an AI-written one that disagrees with
        # its value renders the wrong label and blocks the FE self-heal.
        if field_name.endswith('__label'):
            results.append(
                f"Field error: {node_name}.{field_name} — '__label' keys are the UI's "
                f"display cache and are never set directly; set "
                f"'{field_name[: -len('__label')]}' and the UI derives the label."
            )
            continue

        # Provider sandbox mounts: canvas-level field. Normalize + validate
        # early so the brain gets feedback this turn instead of a boot
        # failure at run time.
        if field_name == 'agent_sandbox_repos':
            from nodes.agent.node_op_tools import normalize_sandbox_repos

            repos, repos_err = normalize_sandbox_repos(raw_value)
            if repos_err:
                results.append(f"Field error: {node_name}.agent_sandbox_repos — {repos_err}")
                continue
            node.config[field_name] = repos
            _mark_field_provided(node, field_name)
            results.append(
                f"Set {node_name}.agent_sandbox_repos = "
                f"{[r['repo'] for r in repos]} ({len(repos)} mount(s))"
            )
            continue

        # Declared env-var need: canvas-level field naming variables the user must
        # provide. Names only (values become an agent_env credential). Validate the
        # names here so the brain gets feedback this turn.
        if field_name == 'agent_env_requested':
            from nodes.agent.user_env import normalize_requested_env_vars

            reqd, reqd_err = normalize_requested_env_vars(raw_value)
            if reqd_err:
                results.append(f"Field error: {node_name}.agent_env_requested — {reqd_err}")
                continue
            node.config[field_name] = reqd
            _mark_field_provided(node, field_name)
            results.append(
                f"Set {node_name}.agent_env_requested = {[r['name'] for r in reqd]} "
                f"({len(reqd)} env var(s) requested from the user)"
            )
            continue

        # Either-or: an MCP node that hosts wired providers can't gain a
        # server_url (mirror of mcp_server_url_conflict in the MCP-server DSL).
        if field_name == 'server_url' and node.type == 'mcp-server':
            if str(raw_value or '').strip() and graph_state.has_wired_providers(node_name):
                results.append(
                    f"Field error: {node_name}.server_url — this MCP node hosts wired "
                    f"tool providers (bottom handle); hosting and external-proxy modes "
                    f"are either-or. Leave server_url empty, or use a separate mcp-server "
                    f"node for the external server."
                )
                continue

        # Provider allowlist: not in any operation schema (canvas-level field),
        # validated against the node's actual operation names instead.
        if field_name == 'agent_tool_operations':
            allowed, err = validate_agent_tool_operations(node.type, coerce_value(raw_value))
            if err:
                results.append(f"Field error: {node_name}.agent_tool_operations — {err}")
                continue
            node.config[field_name] = allowed
            _mark_field_provided(node, field_name)
            results.append(
                f"Set {node_name}.agent_tool_operations = {allowed} "
                f"({len(allowed)} operations exposed as agent tools)"
            )
            continue

        # Look up the field's schema so we can coerce values intelligently
        # (string-enum fields like `show_in_interface: enum('true','false')`
        # need the raw "false" preserved as a string, not JSON-decoded to bool).
        warning = ""
        field_schema: Optional[Dict[str, Any]] = None
        meta_fields = {'label', 'goal', 'operation', 'fullscreen', 'disabled'}
        if field_name not in meta_fields:
            schema = get_operation_schema(node.type, node.operation or 'default')
            if schema:
                properties = schema.get('properties', {})
                valid_fields = set(properties.keys())
                field_schema = properties.get(field_name)
                if valid_fields and field_name not in valid_fields:
                    if node_name not in warned_nodes:
                        # First invalid field for this node — show full valid fields list
                        warning = (
                            f" WARNING: '{field_name}' is not a valid field. "
                            f"Valid fields for {node.type}:{node.operation or 'default'}: {', '.join(sorted(valid_fields))}."
                        )
                        warned_nodes.add(node_name)
                    else:
                        # Subsequent invalid fields — short warning only
                        warning = f" WARNING: '{field_name}' is not a valid field."

        value = coerce_value_for_field(raw_value, field_schema) if raw_value else raw_value

        # Detect patch mode: if body starts with @@ hunk header, apply as diff
        if isinstance(value, str) and value.lstrip().startswith('@@'):
            from ..patch_utils import apply_patch, parse_patch_content
            # Only treat as patch if parsing yields chunks with actual diff content
            # (old_lines or new_lines). Otherwise the brain likely intended a full
            # replacement that happens to start with @@.
            chunks = parse_patch_content(value)
            has_diff_content = any(c.old_lines or c.new_lines for c in chunks)
            if has_diff_content:
                existing = str(node.config.get(field_name, ''))
                if not existing:
                    results.append(f"Field error: cannot patch {node_name}.{field_name} — field is empty. Use full replacement instead.")
                    continue
                patched = apply_patch(existing, value)
                if patched == existing:
                    results.append(
                        f"PATCH FAILED for {node_name}.{field_name}: no hunks matched. "
                        f"The @@ lines must match existing code exactly. "
                        f"Use <read_config node=\"{node_name}\" field=\"{field_name}\"> to see the current value, "
                        f"then retry with correct anchors — or send a full replacement without @@ prefix."
                    )
                    continue
                node.config[field_name] = patched
                _mark_field_provided(node, field_name)
                results.append(f"Patched {node_name}.{field_name}{warning}")
            else:
                # No actual diff hunks — treat as full replacement
                stored, resolution = resolve_field_value(
                    get_operation_schema(node.type, node.operation or 'default'),
                    field_name, value,
                )
                node.config[field_name] = stored
                _mark_field_provided(node, field_name)
                results.append(f"Set {node_name}.{field_name} = {repr(stored)[:50]}{warning}")
                if resolution and not resolution.exact:
                    results.extend(format_resolution_block(resolution))
        else:
            stored, resolution = resolve_field_value(
                get_operation_schema(node.type, node.operation or 'default'),
                field_name, value,
            )
            node.config[field_name] = stored
            _mark_field_provided(node, field_name)
            results.append(f"Set {node_name}.{field_name} = {repr(stored)[:50]}{warning}")
            if resolution and not resolution.exact:
                results.extend(format_resolution_block(resolution))
        # When changing operation via <field>, also update node.operation
        # so subsequent field validations use the correct schema
        if field_name == 'operation':
            node.operation = node.config.get(field_name, value)

    # Validate full config against Pydantic model after all fields are set.
    # This catches value-level issues (wrong enum, wrong type, bad field names
    # inside nested objects like schedules) that field-name validation misses.
    affected_nodes = {op.attrs.get('node', '') for op in ops}
    for node_name in affected_nodes:
        node = graph_state.get_node(node_name)
        if not node:
            continue
        # Batch-aware: a batch that sets model AND model_type keeps the
        # explicit discriminator regardless of op order.
        changed_fields = {
            op.attrs.get('name', '') for op in ops
            if op.attrs.get('node', '') == node_name
        }
        drop_stale_agent_discriminator(node.type, changed_fields, node.config)
        # http-request: strip placeholder auth headers (Bearer {{API_KEY}}) —
        # they resolve to nothing at runtime; auth comes from an attached
        # credential. Feed the removal back so the brain asks for one.
        if node.type == 'automation-http-request':
            stripped = strip_placeholder_auth_headers(node.config)
            if stripped:
                cred_type, cred_label = http_auth_credential_hint(stripped)
                results.append(
                    f"Removed placeholder auth header(s) "
                    f"{[h.get('key') for h in stripped]} from {node_name} — placeholder "
                    f"tokens resolve to nothing at runtime. The node applies an attached "
                    f"credential automatically: use <ask> for the user to connect a "
                    f"{cred_label} credential ({cred_type}), or <set_credentials> if one exists."
                )
        # Trigger refs templated into an agent's message break at runtime —
        # the fired event is delivered automatically. Strip + tell the brain.
        if node.type == 'agent':
            upstream_trigger_ids = [
                u.id for u in graph_state.get_upstream_nodes(node_name)
                if is_trigger_source(u.type, u.operation)
            ]
            stripped_refs = strip_agent_trigger_message_refs(
                node.config, upstream_trigger_ids, standing_message=node.goal,
            )
            if stripped_refs:
                results.append(
                    f"Removed trigger reference(s) {', '.join(stripped_refs)} from "
                    f"{node_name}.message — the fired trigger's event is delivered to "
                    f"the agent automatically; message holds STANDING instructions "
                    f"(now: {node.config.get('message')!r})."
                )
        # Any AI write of a node invalidates its __label display caches —
        # canonicalization may have rewritten values, and a stale sidecar
        # both shows the wrong label and blocks the FE's self-heal.
        strip_label_sidecars(node.config, changed_keys=changed_fields)
        # Provider-wired nodes never execute an operation — their config is
        # just the allowlist + credentials, which the operation schema would
        # reject as incomplete.
        if graph_state.is_tool_provider(node_name):
            continue
        # ENFORCED write-time gate: coerce deterministically fixable values
        # (stringified JSON in structured fields), then revert any changed key
        # whose value is still wrong-typed. Advisory-only feedback let a
        # broken value persist and kill every run (2026-07-16 approval node).
        notes, rejected = reject_invalid_config_values(
            node.type, node.operation or 'default', node.config, changed_fields
        )
        for note in notes:
            results.append(f"Normalized {node_name}.{note}")
        schema = get_operation_schema(node.type, node.operation or 'default')
        defs = (schema or {}).get('$defs', {})
        for key, msg in rejected:
            prior = prior_values.get((node_name, key), _ABSENT)
            if prior is _ABSENT:
                node.config.pop(key, None)
            else:
                node.config[key] = prior
            results.append(
                f"REJECTED {node_name}.{key}: {msg} — the value was NOT saved. "
                f"Re-send <field name=\"{key}\" node=\"{node_name}\"> with a value "
                f"matching the schema."
            )
            if schema and key in schema.get('properties', {}):
                desc = _describe_field(schema['properties'][key], defs)
                results.append(f"  Expected schema for {key}: {desc}")
        err = validate_node_config(node.type, node.operation or 'default', node.config)
        if err:
            results.append(f"VALIDATION ERROR for {node_name} ({node.type}:{node.operation}): {err}")
            # Append schema hint so the agent knows the correct field names/types
            if schema:
                set_fields = {op.attrs.get('name', '') for op in ops if op.attrs.get('node', '') == node_name}
                for fname in set_fields:
                    if fname in schema.get('properties', {}):
                        desc = _describe_field(schema['properties'][fname], defs)
                        results.append(f"  Expected schema for {fname}: {desc}")

    return results


def execute_settings_ops(
    ops: List[XmlOp],
    graph_state: GraphState,
) -> List[str]:
    """
    Execute update_settings operations on nodes in the graph state.

    Returns human-readable results.
    """
    results: List[str] = []
    for op in ops:
        node_name = op.attrs.get('node', '') or op.attrs.get('id', '')
        settings_map = {k: v for k, v in op.attrs.items() if k not in ('node', 'id')}

        node = graph_state.get_node(node_name)
        if not node:
            results.append(f"Settings error: node '{node_name}' not found")
            continue

        if not settings_map:
            results.append(f"Settings error: no fields provided for '{node_name}'")
            continue

        err = update_node_settings(node.config, settings_map)
        if err:
            results.append(f"Settings error on '{node_name}': {err}")
        else:
            applied = ', '.join(f"{k}={v!r}" for k, v in settings_map.items())
            results.append(f"Updated settings for '{node_name}': {applied}")

    return results


def execute_query_operations(ops: List[XmlOp]) -> List[str]:
    """Execute query_operations commands, returning available operations."""
    results: List[str] = []
    for op in ops:
        node_type = op.attrs.get('type', '')
        operations = get_operations_for_node_type(node_type)
        if not operations:
            results.append(f"[Query: operations for {node_type}]\nNo operations found for type '{node_type}'")
            continue

        lines = [f"[Query: operations for {node_type}]"]
        for op_info in operations:
            lines.append(f"- {op_info.name}: {op_info.description or 'No description'}")

        # Append node-level operations guidance if available
        guidance = load_node_guidance(node_type, section="operations", context={"type": node_type})
        if guidance:
            lines.append(f"\n## Operations Guidance\n{guidance}")

        results.append('\n'.join(lines))

    return results


def execute_read(ops: List[XmlOp]) -> List[str]:
    """Execute <read topic="name"> commands, returning documentation from the shared resource registry."""
    from resources import get as get_resource, list_all
    results: List[str] = []
    for op in ops:
        topic = op.attrs.get('topic', '')
        if not topic:
            # List available topics
            available = list_all()
            lines = ["[Available documentation topics]"]
            for entry in available:
                lines.append(f"- {entry['name']}: {entry['title']}")
            results.append('\n'.join(lines))
            continue

        content = get_resource(topic)
        if not content:
            available = list_all()
            names = [e['name'] for e in available]
            results.append(f"[Read: topic '{topic}' not found. Available: {', '.join(names)}]")
        else:
            results.append(f"[Read: {topic}]\n{content}")

    return results


def _describe_field(field_schema: Dict[str, Any], defs: Dict[str, Any], indent: str = "") -> str:
    """Build a human-readable description of a field schema, resolving $refs and nested types."""
    # Resolve $ref
    if '$ref' in field_schema:
        ref_name = field_schema['$ref'].split('/')[-1]
        if ref_name in defs:
            return _describe_object(defs[ref_name], defs, indent)
        return ref_name

    # anyOf: pick the most informative variant (skip null)
    if 'anyOf' in field_schema:
        variants = [v for v in field_schema['anyOf'] if v.get('type') != 'null']
        if len(variants) == 1:
            return _describe_field(variants[0], defs, indent)
        # Multiple real types — summarize
        parts = [_describe_field(v, defs, indent) for v in variants]
        return ' | '.join(parts)

    # Array with items
    if field_schema.get('type') == 'array' and 'items' in field_schema:
        item_desc = _describe_field(field_schema['items'], defs, indent)
        return f"array of {item_desc}"

    # Enum
    if 'enum' in field_schema:
        return f"enum({', '.join(repr(v) for v in field_schema['enum'])})"

    return field_schema.get('type', 'string')


def _describe_object(schema: Dict[str, Any], defs: Dict[str, Any], indent: str = "") -> str:
    """Describe an object schema's fields inline."""
    props = schema.get('properties', {})
    if not props:
        return schema.get('title', 'object')
    parts = []
    for name, fs in props.items():
        field_type = _describe_field(fs, defs, indent + "  ")
        desc = fs.get('description', '')
        default = fs.get('default')
        extras = []
        if desc:
            extras.append(desc)
        if default is not None:
            extras.append(f"default={default}")
        extra_str = f" — {'; '.join(extras)}" if extras else ""
        parts.append(f"{indent}  {name}: {field_type}{extra_str}")
    return "{\n" + "\n".join(parts) + f"\n{indent}}}"


def execute_query_schema(ops: List[XmlOp]) -> List[str]:
    """Execute query_schema commands, returning config schema for an operation."""
    results: List[str] = []
    for op in ops:
        node_type = op.attrs.get('type', '')
        operation = op.attrs.get('operation', 'default')
        schema = get_operation_schema(node_type, operation)
        if not schema:
            results.append(f"[Query: schema for {node_type}:{operation}]\nNo schema found")
            continue

        defs = schema.get('$defs', {})
        props = schema.get('properties', {})
        required = set(schema.get('required', []))
        lines = [f"[Query: schema for {node_type}:{operation}]"]
        for field_name, field_schema in props.items():
            field_type = _describe_field(field_schema, defs)
            req = ' (required)' if field_name in required else ''
            desc = field_schema.get('description', '')
            desc_str = f' — {desc}' if desc else ''
            queryable = field_schema.get('x-queryable-enum')
            queryable_str = f' [queryable: {queryable}]' if queryable else ''
            lines.append(f"- {field_name}: {field_type}{queryable_str}{req}{desc_str}")
            hint = field_schema.get('x-enum-hint')
            if hint:
                lines.append(f"    hint: {hint}")

        # Credential info
        cred_info = get_credential_info(node_type, operation)
        if cred_info:
            lines.append(f"Credentials: {cred_info.label} ({cred_info.provider_key})")

        # Append node-level config guidance if available
        guidance = load_node_guidance(node_type, section="config", context={
            "type": node_type, "operation": operation,
        })
        if guidance:
            lines.append(f"\n## Config Guidance\n{guidance}")

        results.append('\n'.join(lines))

    return results


# ============================================================================
# Config inspection — reads full field values from graph_state on demand
# ============================================================================

def execute_read_config(ops: List[XmlOp], graph_state: GraphState) -> List[str]:
    """Execute <read_config node="alias" field="field_name" /> to return full config values."""
    results: List[str] = []
    for op in ops:
        node_name = op.attrs.get('node', '')
        field_name = op.attrs.get('field', '')

        if not node_name:
            results.append("[read_config] Error: 'node' attribute is required.")
            continue

        node = graph_state.get_node(node_name)
        if not node:
            results.append(f"[read_config node={node_name}] Node not found.")
            continue

        # Determine valid config keys from schema to filter out metadata
        valid_keys = _get_valid_config_keys(node.type, node.operation)

        if not field_name:
            # List all config fields with actual values (clipped for long ones)
            lines = [f"[read_config node={node_name}] Config fields:"]
            for k, v in node.config.items():
                if v is None or v == '':
                    continue
                if valid_keys is not None and k not in valid_keys:
                    continue
                val_str = str(v)
                if len(val_str) > 200:
                    lines.append(f"  - {k}: {val_str[:150]}... ({len(val_str)} chars, use field=\"{k}\" for full)")
                else:
                    lines.append(f"  - {k}: {val_str}")
            if len(lines) == 1:
                lines.append("  (no config fields set)")
            results.append('\n'.join(lines))
        else:
            if valid_keys is not None and field_name not in valid_keys:
                results.append(f"[read_config node={node_name} field={field_name}] Not a valid config field.")
            else:
                value = node.config.get(field_name)
                if value is None:
                    results.append(f"[read_config node={node_name} field={field_name}] Field not set.")
                else:
                    results.append(f"[read_config node={node_name} field={field_name}]\n{value}")

    return results


# ============================================================================
# Output schema summarizer — compact type description for brain context
# ============================================================================

def summarize_output(data: Any, max_depth: int = 3, depth: int = 0, indent: str = "  ") -> str:
    """Build a compact schema summary of a JSON value for brain context."""
    if data is None:
        return "null"
    if isinstance(data, bool):
        return str(data).lower()
    if isinstance(data, (int, float)):
        return str(data)
    if isinstance(data, str):
        if len(data) > 100:
            return f'"{data[:60]}..." ({len(data)} chars)'
        return repr(data)
    if isinstance(data, list):
        if not data:
            return "[]"
        if depth >= max_depth:
            return f"array[{len(data)}]"
        item = summarize_output(data[0], max_depth, depth + 1, indent)
        return f"array[{len(data)}] of {item}"
    if isinstance(data, dict):
        if not data:
            return "{}"
        if depth >= max_depth:
            return f"object({len(data)} keys)"
        pad = indent * (depth + 1)
        lines = []
        items = list(data.items())[:20]
        for k, v in items:
            lines.append(f"{pad}{k}: {summarize_output(v, max_depth, depth + 1, indent)}")
        if len(data) > 20:
            lines.append(f"{pad}... +{len(data) - 20} more keys")
        end_pad = indent * depth
        return "{\n" + "\n".join(lines) + f"\n{end_pad}}}"
    return type(data).__name__


# ============================================================================
# Platform operations — require async DB / socket access provided by handler
# ============================================================================

class PlatformOps(Protocol):
    """Async callbacks for operations that need DB or socket access."""

    async def get_node_output(self, node_id: str) -> Optional[Dict[str, Any]]:
        """Get latest output with metadata. Returns {output, created_at} or None."""
        ...

    async def get_nodes_with_output(self, node_ids: List[str]) -> Set[str]:
        """Return the subset of node_ids that have persisted output in the DB."""
        ...

    async def run_node(self, node_id: str, include_downstream: bool = False) -> Dict[str, Any]:
        """Execute a node (and downstream if requested). Returns {success, output?} or {error}."""
        ...

    async def list_workflows(self, query: str, limit: int) -> List[Dict[str, Any]]:
        """Search user's workflows by name/description. Returns list of {id, name, description, updated_at}."""
        ...

    async def open_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Request frontend to navigate to a workflow. Returns {success, workflow_id} or {error}."""
        ...

    async def create_workflow(self, name: str, description: str) -> Dict[str, Any]:
        """Create a new empty workflow. Returns {success, workflow_id, name} or {error}."""
        ...

    async def list_folders(self) -> List[Dict[str, Any]]:
        """List all folders. Returns list of {id, name, parent_folder_id, workflow_count}."""
        ...

    async def create_folder(self, name: str, parent_folder_id: Optional[str]) -> Dict[str, Any]:
        """Create a folder. Returns {success, folder_id, name} or {error}."""
        ...

    async def delete_folder(self, folder_id: str) -> Dict[str, Any]:
        """Delete a folder (workflows move to parent). Returns {success} or {error}."""
        ...

    async def move_workflow(self, workflow_id: str, folder_id: Optional[str]) -> Dict[str, Any]:
        """Move a workflow to a folder (or root if folder_id is None). Returns {success} or {error}."""
        ...

    async def search_credentials(self, credential_type: str, query: str, limit: int) -> List[Dict[str, Any]]:
        """Search user's credentials. Returns list of {id, name, credential_type, metadata}."""
        ...

    async def fetch_credential_health(self, credential_ids: List[str]) -> Dict[str, Any]:
        """Provider-session health verdicts (utils.credential_health) for the
        given credential ids. {} = all unknown/healthy — never fails the turn."""
        ...


    async def authorize_credentials(self, credential_ids: List[str]) -> None:
        """Authorize credentials the builder placed (set_credentials / autoselect) for
        run-as-owner resolution on this workflow. Owner-gated in the implementation — the
        builder is the trusted, owner-attributed signal the de-authorized frontend autosave
        no longer provides."""
        ...

    async def upsert_variable_definitions(self, definitions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Merge definitions into workflows.settings.variable_definitions
        (shallow settings merge, upsert by name). Owner-gated in the
        implementation — mirrors the socket path's settings rule.
        Returns {success: True} or {error}."""
        ...

    async def add_rehearsal_run(
        self, node_type: str, name: str, lead: Dict[str, str], base_key: str,
    ) -> Dict[str, Any]:
        """Append an authored test run to workflows.settings.rehearsal_authoring
        (owner-gated). Returns {success: True, slug} or {error}."""
        ...


# Workflow-level content ops (settings writes — DB access via PlatformOps)
WORKFLOW_CONTENT_TAGS: Set[str] = {'define_variable', 'add_test_run'}

# Tags that require platform ops (async, DB access)
NODE_OPS_TAGS: Set[str] = {'get_output', 'run_node'}
PLATFORM_TAGS: Set[str] = {
    *NODE_OPS_TAGS,
    'search_credentials',
    'list_workflows', 'open_workflow', 'create_workflow',
    'list_folders', 'create_folder', 'delete_folder', 'move_workflow',
}


MAX_PLATFORM_OPS_PER_TURN = 5


import json as _json


# Per-field truncation cap for `get_full_output` / `run_node get_full_output`.
# A single 38KB raw HTML email body can blow the brain's context window; truncate
# each long string in place so the rest of the output remains useful.
_FULL_OUTPUT_FIELD_CHAR_CAP = 5000
# Final safety net on the serialized JSON length, applied after per-field truncation.
_FULL_OUTPUT_TOTAL_CHAR_CAP = 30000


def _truncate_large_strings(value: Any, max_len: int = _FULL_OUTPUT_FIELD_CHAR_CAP) -> Any:
    """Recursively replace strings longer than max_len with a preview + omitted-chars marker.

    Preserves the structure of the data so the brain can still see field names,
    array shapes, and short values; only long string leaves get shortened.
    """
    if isinstance(value, str):
        if len(value) > max_len:
            return f"{value[:max_len]}... <{len(value) - max_len} more chars omitted; use schema view for shape>"
        return value
    if isinstance(value, list):
        return [_truncate_large_strings(v, max_len) for v in value]
    if isinstance(value, dict):
        return {k: _truncate_large_strings(v, max_len) for k, v in value.items()}
    return value


def _serialize_full_output(output: Any) -> str:
    """Serialize a node output for the brain, with per-field truncation."""
    truncated = _truncate_large_strings(output)
    output_str = _json.dumps(truncated, default=str, indent=2)
    if len(output_str) > _FULL_OUTPUT_TOTAL_CHAR_CAP:
        output_str = (
            output_str[:_FULL_OUTPUT_TOTAL_CHAR_CAP]
            + f"\n... truncated ({len(output_str)} chars total)"
        )
    return output_str


async def execute_node_ops(
    ops: List[XmlOp],
    platform: PlatformOps,
    graph_state: GraphState,
) -> List[str]:
    """Execute node output/execution ops (get_output, run_node).

    Returns human-readable results for the brain's next turn.
    """
    results: List[str] = []
    for op in ops:
        # Per-op span. Wraps the platform call + result formatting. Attributes
        # carry the op kind (`run_node` etc.) and the node-id target so a
        # dashboard query like `HEATMAP(duration_ms) GROUP BY agent.op.tag`
        # answers "which op type is eating the most brain-turn time".
        # `continue` inside the with-block runs span.__exit__ before the loop
        # advances, so each iteration cleanly produces exactly one span.
        with _tracer.start_as_current_span("agent.op") as _op_span:
            _op_span.set_attribute("agent.op.tag", op.tag)
            _op_span.set_attribute("agent.op.kind", "node_op")
            _op_started = time.monotonic()
            if op.tag == 'get_output':
                node_ref = op.attrs.get('node', '')
                is_full = 'full' in op.attrs
                _op_span.set_attribute("agent.op.node", node_ref)
                _op_span.set_attribute("agent.op.full_output", is_full)
                if not node_ref:
                    results.append("[get_output] Error: 'node' attribute is required.")
                    _op_span.set_attribute("agent.op.error", "missing_node_attr")
                    continue
                node = graph_state.get_node(node_ref)
                if not node:
                    results.append(f"[get_output node={node_ref}] Node '{node_ref}' does not exist in the workflow. Add it first with <add_node>.")
                    _op_span.set_attribute("agent.op.error", "node_not_found")
                    continue
                node_id = node.id
                result = await platform.get_node_output(node_id)
                if result is None:
                    results.append(f"[get_output node={node_ref}] No output available. Run the node first with <run_node node=\"{node_ref}\" />")
                    _op_span.set_attribute("agent.op.empty_output", True)
                    continue
                output = result.get("output")
                created_at = result.get("created_at", "")
                status_line = f" (last output: {created_at})" if created_at else ""
                if output is None:
                    results.append(f"[get_output node={node_ref}] No output available. Run the node first with <run_node node=\"{node_ref}\" />")
                    _op_span.set_attribute("agent.op.empty_output", True)
                elif is_full:
                    output_str = _serialize_full_output(output)
                    results.append(f"[get_output node={node_ref} full]{status_line}\n{output_str}")
                else:
                    results.append(f"[get_output node={node_ref}]{status_line} Output schema:\n{summarize_output(output)}")

            elif op.tag == 'run_node':
                node_ref = op.attrs.get('node', '')
                wants_output = 'get_output' in op.attrs
                wants_full = 'get_full_output' in op.attrs
                downstream = 'include_downstream' in op.attrs
                _op_span.set_attribute("agent.op.node", node_ref)
                _op_span.set_attribute("agent.op.include_downstream", downstream)
                if not node_ref:
                    results.append("[run_node] Error: 'node' attribute is required.")
                    _op_span.set_attribute("agent.op.error", "missing_node_attr")
                    continue
                node = graph_state.get_node(node_ref)
                node_id = node.id if node else node_ref
                result = await platform.run_node(node_id, include_downstream=downstream)
                if result.get('error'):
                    failed_node = result.get('failed_node')
                    _op_span.set_attribute("agent.op.error", str(result['error'])[:200])
                    if failed_node == 'other':
                        # A node other than the target failed first; the target itself
                        # did not run. Make this unambiguous so the brain doesn't
                        # mis-attribute the error to the target.
                        results.append(
                            f"[run_node node={node_ref}] Target node did not run because a different node failed first.\n"
                            f"Failure: {result['error']}"
                        )
                    else:
                        results.append(f"[run_node node={node_ref}] Error: {result['error']}")
                else:
                    if downstream:
                        results.append(f"[run_node node={node_ref}] Workflow executed from this node onwards.")
                    elif (wants_output or wants_full) and result.get('output') is not None:
                        output = result['output']
                        if wants_full:
                            output_str = _serialize_full_output(output)
                            results.append(f"[run_node node={node_ref}] Executed successfully. Full output:\n{output_str}")
                        else:
                            results.append(f"[run_node node={node_ref}] Executed successfully. Output schema:\n{summarize_output(output)}")
                    else:
                        results.append(f"[run_node node={node_ref}] Executed successfully.")
                    # Update has_output on the graph state
                    if node:
                        node.has_output = True
            _op_span.set_attribute("agent.op.duration_ms", (time.monotonic() - _op_started) * 1000)
    return results


async def execute_platform_ops(
    ops: List[XmlOp],
    platform: PlatformOps,
    graph_state: Optional[GraphState] = None,
) -> List[str]:
    """Execute workflow management operations that require DB access.

    Deduplicates identical ops and caps execution at MAX_PLATFORM_OPS_PER_TURN.
    Returns human-readable results for the brain's next turn.
    """
    # Deduplicate by (tag, sorted attrs)
    seen: set = set()
    unique_ops: List[XmlOp] = []
    for op in ops:
        key = (op.tag, tuple(sorted(op.attrs.items())))
        if key not in seen:
            seen.add(key)
            unique_ops.append(op)
    skipped = len(ops) - len(unique_ops)

    results: List[str] = []
    if skipped:
        results.append(f"[System: {skipped} duplicate operations removed]")

    if len(unique_ops) > MAX_PLATFORM_OPS_PER_TURN:
        results.append(f"[System: Capped at {MAX_PLATFORM_OPS_PER_TURN} operations per turn ({len(unique_ops)} requested). Use fewer, more targeted queries.]")
        unique_ops = unique_ops[:MAX_PLATFORM_OPS_PER_TURN]

    for op in unique_ops:
        # Per-op span. Same kind tag as execute_node_ops so dashboards can
        # query "all agent ops" with a single name filter. The dispatch body
        # is factored into _dispatch_platform_op below so the outer wrap
        # stays five lines instead of repeating the with-block per op tag.
        with _tracer.start_as_current_span("agent.op") as _op_span:
            _op_span.set_attribute("agent.op.tag", op.tag)
            _op_span.set_attribute("agent.op.kind", "platform_op")
            _started = time.monotonic()
            try:
                await _dispatch_platform_op(op, platform, results, _op_span, graph_state)
            finally:
                _op_span.set_attribute(
                    "agent.op.duration_ms", (time.monotonic() - _started) * 1000,
                )

    return results


async def execute_workflow_content_ops(
    ops: List[XmlOp],
    platform: PlatformOps,
    graph_state: GraphState,
) -> tuple[List[str], List[Dict[str, str]]]:
    """Execute define_variable / add_test_run — settings-level content writes.

    Returns (results for the brain, authored test runs as
    [{node_type, name, slug}]) — the caller uses the authored list to resolve
    a same-turn <run_test run="<name>"/> to the slug the FE selects by.
    """
    from coder.workflow.workflow_ops import (
        parse_add_test_run,
        parse_define_variable,
        upsert_variable_definitions,
    )

    results: List[str] = []
    authored: List[Dict[str, str]] = []

    definitions: List[Dict[str, Any]] = []
    for op in (o for o in ops if o.tag == 'define_variable'):
        definition, err = parse_define_variable(op)
        if err:
            results.append(f"ERROR: {err}")
        else:
            definitions.append(definition)
    if definitions:
        outcome = await platform.upsert_variable_definitions(definitions)
        if outcome.get('error'):
            results.append(f"ERROR: define_variable — {outcome['error']}")
        else:
            # Mirror into the snapshot so later turns see the declarations.
            graph_state.variable_definitions = upsert_variable_definitions(
                graph_state.variable_definitions, definitions,
            )
            for d in definitions:
                bind_hint = (
                    f" Bind it with {{{{vars.{d['name']}}}}} as a config field's whole value."
                )
                results.append(
                    f"Defined variable '{d['name']}'"
                    + (" (per-user: cleared on fork, Setup asks each new owner)" if d.get('per_user') else "")
                    + ("" if d.get('value') else " (no value yet — Setup will ask)")
                    + bind_hint
                )

    test_run_ops = [o for o in ops if o.tag == 'add_test_run']
    if test_run_ops:
        from nodes.agent.rehearsal_scenarios import (
            base_scenario_key_for_type,
            can_stage_trigger,
        )
        wf = graph_state.to_workflow_data()
        wf_nodes, wf_edges = wf.get('nodes') or [], wf.get('edges') or []
        by_id = {n.get('id'): n for n in wf_nodes}
        for op in test_run_ops:
            parsed, err = parse_add_test_run(op)
            if err:
                results.append(f"ERROR: {err}")
                continue
            ref = parsed['trigger_ref']
            node = by_id.get(ref) or next(
                (n for n in wf_nodes if n.get('type') == ref), None,
            )
            if not node:
                results.append(f"ERROR: add_test_run — no node '{ref}' in this workflow")
                continue
            if not can_stage_trigger(node, wf_nodes, wf_edges):
                results.append(
                    f"ERROR: add_test_run — '{ref}' is not rehearsable: it must be "
                    "a trigger (not a provider-wired tool) with an agent downstream"
                )
                continue
            node_type = node.get('type') or ''
            outcome = await platform.add_rehearsal_run(
                node_type, parsed['name'], parsed['lead'],
                base_scenario_key_for_type(node_type),
            )
            if outcome.get('error'):
                results.append(f"ERROR: add_test_run — {outcome['error']}")
            else:
                slug = str(outcome.get('slug') or '')
                authored.append({'node_type': node_type, 'name': parsed['name'], 'slug': slug})
                results.append(
                    f"Added test run '{parsed['name']}' (slug {slug}) for {node_type}"
                )

    return results, authored


def _no_credentials_guidance(cred_type: str, graph_state: Optional[GraphState]) -> str:
    """Truthful follow-up for an empty credential search.

    The old message ("the user needs to add credentials") asserted a
    requirement for ANY queried type string — including invented types for
    nodes that need no credentials — and trained the brain to keep re-asking.
    """
    parts: List[str] = []
    if cred_type and cred_type not in known_credential_types():
        parts.append(f"'{cred_type}' is not a known credential type.")

    if graph_state is None:
        parts.append(
            "Only ask the user to connect an account when a node's summary "
            "shows [credentials needed: …]."
        )
        return ' '.join(parts)

    needing = [f"{n.id} ({n.type})" for n in nodes_missing_credentials(graph_state)]
    if needing:
        parts.append(
            "Nodes whose selected operation requires credentials: "
            + ", ".join(needing)
            + '. Ask the user to connect with <ask node="..." field="credential" />.'
        )
    else:
        parts.append(
            "No node in this workflow is missing credentials for its selected "
            "operation — do not ask the user to connect an account."
        )
    return ' '.join(parts)


async def _dispatch_platform_op(
    op: XmlOp,
    platform: PlatformOps,
    results: List[str],
    span,
    graph_state: Optional[GraphState] = None,
) -> None:
    """Dispatch one platform op (`list_workflows`, `open_workflow`, etc.).

    Body extracted out of execute_platform_ops so the outer loop can wrap
    each call in a single agent.op span without re-indenting the whole
    if/elif chain. The span attributes set inside the elif branches are
    op-tag-specific (`agent.op.workflow_id`, `agent.op.query`, …) so the
    Honeycomb columns stay tidy.
    """
    if op.tag == 'list_workflows':
        query = op.attrs.get('query', op.attrs.get('search', ''))
        limit = int(op.attrs.get('limit', '10'))
        span.set_attribute("agent.op.query", query)
        workflows = await platform.list_workflows(query, limit)
        span.set_attribute("agent.op.result_count", len(workflows))
        if not workflows:
            results.append(f"[list_workflows query=\"{query}\"] No workflows found.")
        else:
            lines = [f"[list_workflows query=\"{query}\"] Found {len(workflows)} workflow(s):"]
            for wf in workflows:
                desc = f" — {wf['description']}" if wf.get('description') else ""
                lines.append(f"  - {wf['name']} (id={wf['id']}){desc}")
            results.append('\n'.join(lines))

    elif op.tag == 'open_workflow':
        workflow_id = op.attrs.get('id', '')
        span.set_attribute("agent.op.workflow_id", workflow_id)
        if not workflow_id:
            results.append("[open_workflow] Error: 'id' attribute is required.")
            span.set_attribute("agent.op.error", "missing_id")
            return
        result = await platform.open_workflow(workflow_id)
        if result.get('error'):
            results.append(f"[open_workflow id={workflow_id}] Error: {result['error']}")
            span.set_attribute("agent.op.error", str(result['error'])[:200])
        else:
            results.append(f"[open_workflow id={workflow_id}] Workflow opened in the user's browser.")

    elif op.tag == 'create_workflow':
        name = op.attrs.get('name', '')
        if not name:
            results.append("[create_workflow] Error: 'name' attribute is required.")
            span.set_attribute("agent.op.error", "missing_name")
            return
        description = op.attrs.get('description', '')
        result = await platform.create_workflow(name, description)
        if result.get('error'):
            results.append(f"[create_workflow name={name}] Error: {result['error']}")
            span.set_attribute("agent.op.error", str(result['error'])[:200])
        else:
            wf_id = result.get('workflow_id', '')
            span.set_attribute("agent.op.workflow_id", wf_id)
            results.append(f"[create_workflow name={name}] Created workflow (id={wf_id}). Use <open_workflow id=\"{wf_id}\" /> to open it.")

    elif op.tag == 'list_folders':
        folders = await platform.list_folders()
        span.set_attribute("agent.op.result_count", len(folders))
        if not folders:
            results.append("[list_folders] No folders found.")
        else:
            lines = [f"[list_folders] {len(folders)} folder(s):"]
            for f in folders:
                parent = f" (in {f['parent_folder_id']})" if f.get('parent_folder_id') else " (root)"
                lines.append(f"  - {f['name']} (id={f['id']}){parent} — {f.get('workflow_count', 0)} workflows")
            results.append('\n'.join(lines))

    elif op.tag == 'create_folder':
        name = op.attrs.get('name', '')
        if not name:
            results.append("[create_folder] Error: 'name' attribute is required.")
            span.set_attribute("agent.op.error", "missing_name")
            return
        parent_id = op.attrs.get('parent_folder_id') or op.attrs.get('parent')
        result = await platform.create_folder(name, parent_id)
        if result.get('error'):
            results.append(f"[create_folder name={name}] Error: {result['error']}")
            span.set_attribute("agent.op.error", str(result['error'])[:200])
        else:
            results.append(f"[create_folder name={name}] Created folder (id={result.get('folder_id', '')}).")

    elif op.tag == 'delete_folder':
        folder_id = op.attrs.get('id', '')
        span.set_attribute("agent.op.folder_id", folder_id)
        if not folder_id:
            results.append("[delete_folder] Error: 'id' attribute is required.")
            span.set_attribute("agent.op.error", "missing_id")
            return
        result = await platform.delete_folder(folder_id)
        if result.get('error'):
            results.append(f"[delete_folder id={folder_id}] Error: {result['error']}")
            span.set_attribute("agent.op.error", str(result['error'])[:200])
        else:
            results.append(f"[delete_folder id={folder_id}] Folder deleted. Workflows moved to parent folder.")

    elif op.tag == 'move_workflow':
        workflow_id = op.attrs.get('id', '')
        span.set_attribute("agent.op.workflow_id", workflow_id)
        if not workflow_id:
            results.append("[move_workflow] Error: 'id' attribute is required.")
            span.set_attribute("agent.op.error", "missing_id")
            return
        folder_id = op.attrs.get('folder_id') or op.attrs.get('folder')  # None = move to root
        result = await platform.move_workflow(workflow_id, folder_id if folder_id else None)
        if result.get('error'):
            results.append(f"[move_workflow id={workflow_id}] Error: {result['error']}")
            span.set_attribute("agent.op.error", str(result['error'])[:200])
        else:
            dest = f"folder {folder_id}" if folder_id else "root"
            results.append(f"[move_workflow id={workflow_id}] Moved to {dest}.")

    elif op.tag == 'search_credentials':
        cred_type = op.attrs.get('type', '')
        query = op.attrs.get('query', '')
        limit = int(op.attrs.get('limit', '10'))
        span.set_attribute("agent.op.credential_type", cred_type)
        creds = await platform.search_credentials(cred_type, query, limit)
        span.set_attribute("agent.op.result_count", len(creds))
        if not creds:
            type_hint = f" of type '{cred_type}'" if cred_type else ""
            results.append(
                f"[search_credentials] No credentials found{type_hint}. "
                f"{_no_credentials_guidance(cred_type, graph_state)}"
            )
        else:
            lines = [f"[search_credentials] Found {len(creds)} credential(s):"]
            for c in creds:
                meta = c.get('metadata', {})
                if isinstance(meta, str):
                    try:
                        meta = _json.loads(meta)
                    except Exception:
                        meta = {}
                email = meta.get('email', '') if isinstance(meta, dict) else ''
                email_hint = f" ({email})" if email else ""
                lines.append(f"  - {c['name']}{email_hint} (type={c['credential_type']}, id={c['id']})")
            results.append('\n'.join(lines))


def build_node_summary(node: NodeState, graph_state: Optional[GraphState] = None) -> str:
    """Build a summary of a node's state after processing, showing actual config values."""
    parts = [f"- {node.id} ({node.type}): operation={node.operation or 'default'}"]

    if node.config:
        valid_keys = _get_valid_config_keys(node.type, node.operation)
        for k, v in node.config.items():
            if v is None or v == '':
                continue
            if valid_keys is not None and k not in valid_keys:
                continue
            # Skip meta fields that duplicate the operation
            if k in ('operation', 'action', 'content') and str(v) in (node.operation or '', node.label or ''):
                continue
            val_str = str(v)
            if len(val_str) > 80:
                parts.append(f"    {k}={val_str[:60]}... ({len(val_str)} chars)")
            else:
                parts.append(f"    {k}={val_str}")

    # Surface queryable-enum resolutions (matched id + alternatives) for any
    # field written this turn, then drain the buffer so they only render once.
    if node.pending_resolutions:
        for resolution in node.pending_resolutions:
            parts.extend(format_resolution_block(resolution))
        node.pending_resolutions.clear()

    if node.user_fields:
        parts.append(f"  [needs user input: {', '.join(node.user_fields)}]")

    # Tool-provider nodes never execute their operation, so its required
    # fields don't apply (their config is just the allowlist + credentials).
    is_provider = bool(graph_state and graph_state.is_tool_provider(node.id))
    if not is_provider:
        missing = missing_required_fields(node.type, node.operation, node.config, node.user_fields)
        if missing:
            parts.append(
                f"  [missing required: {', '.join(missing)}] "
                f"Set with <field> (derive from the user's request) or <ask> for it — "
                f"the node cannot run without it."
            )

    cred_status = credential_status_line(
        node.type, node.operation, node.config, node.id,
        health=graph_state._credential_health if graph_state else None,
    )
    if cred_status:
        parts.append(f"  {cred_status}")

    return '\n'.join(parts)


def build_execution_summary(
    graph_state: GraphState,
    mutation_results: List[str],
    new_node_ids: List[str],
    field_results: List[str],
    query_results: List[str],
    processed_node_ids: List[str],
) -> str:
    """Build a structured summary of command execution for the brain's next turn."""
    sections: List[str] = []

    if mutation_results:
        sections.append("Graph changes:\n" + '\n'.join(f"  {r}" for r in mutation_results))

    if processed_node_ids:
        node_summaries = []
        for nid in processed_node_ids:
            node = graph_state.get_node(nid)
            if node:
                node_summaries.append(build_node_summary(node, graph_state))
        if node_summaries:
            sections.append("Nodes configured (node drafting):\n" + '\n'.join(node_summaries))

    if field_results:
        sections.append("Field overrides:\n" + '\n'.join(f"  {r}" for r in field_results))

    if query_results:
        sections.append('\n'.join(query_results))

    if not sections:
        return "No changes made."

    return '\n\n'.join(sections)
