"""
Graph-free single-operation runner.

Executes ONE operation of an integration node outside a workflow graph run.
This is the execution backend for agent "node action" tools
(tool_type='node_op' in nodes/agent/tool_execution.py): the agent supplies
the operation's field values as tool arguments, and the node runs standalone
with the credential bound on the provider node.

Deliberately NOT routed through the workflow execution handler or MCP
run_nodes — both carry full-graph assumptions (saved workflow, predecessor
mocking, reference resolution, execution records) that don't hold for an
ad-hoc agent-initiated call.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Optional

from billing.exceptions import InsufficientBalanceError, OwnerResolutionError
from nodes.core.registry import NODE_REGISTRY, NodeFactory
from nodes.core.oauth_audit import caller_path_scope
from utils.credentials import resolve_credential_with_owner_fallback, unresolved_credential_error

logger = logging.getLogger(__name__)

# At most this many calls run at once against one credential (one connected account), in this process: providers
# cap concurrent requests per account (Microsoft Graph answers a fifth to one mailbox 429 MailboxConcurrency), and an
# agent's parallel tool calls all land on the same one.
CREDENTIAL_CONCURRENCY = 4
_places: Dict[str, List[Any]] = {}  # credential id -> [its semaphore, how many hold or wait on it]


@asynccontextmanager
async def credential_place(credential_id: Optional[str]) -> AsyncIterator[None]:
    """One of the credential's ``CREDENTIAL_CONCURRENCY`` places, waited for; no credential, no wait."""
    if not credential_id:
        yield
        return
    place = _places.setdefault(credential_id, [asyncio.Semaphore(CREDENTIAL_CONCURRENCY), 0])
    place[1] += 1
    try:
        async with place[0]:
            yield
    finally:
        place[1] -= 1
        if not place[1]:
            del _places[credential_id]


def needs_credential_hint(node_type: str, operation: Optional[str], config=None) -> bool:
    """Whether a failure with no credential attached may be its missing account: never for a node that takes none
    (Send email, Table), nor a platform scraper's, which a user credential can't fix."""
    from coder.workflow.operation_catalog import get_operation_config_class, is_operation_credentials_optional
    from nodes.core.credential_connect import credential_classes_for_node
    from nodes.core.platform_billing import platform_key_of

    node_class = NODE_REGISTRY.get(node_type)
    if node_class is not None and not credential_classes_for_node(node_class):
        return False

    config_class = get_operation_config_class(node_type, operation) if operation else None
    marker = platform_key_of(config_class.model_json_schema()) if config_class else None
    if marker and marker.get("byok") is False:
        return False
    return not is_operation_credentials_optional(node_type, operation, config)


def credential_note_result(tool_info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """A provider with no credential but a ``credential_note`` (e.g. where to
    connect one) answers with the note instead of running a call that needs
    auth; an operation that needs no account still runs (on NoClick's key)."""
    note = tool_info.get("credential_note")
    if not note or tool_info.get("credential_id"):
        return None
    if not needs_credential_hint(tool_info.get("node_type", ""), tool_info.get("operation")):
        return None
    return {"success": False, "error": note}


async def resolve_operation_credential(
    credential_id: str,
    user_id: str,
    pool=None,
    organization_id: Optional[str] = None,
    workflow_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Resolve and decrypt a credential for a standalone operation run.

    Delegates to the SHARED owner-fallback policy (the same definition the
    workflow execution handler uses): runner first, then the workflow owner
    gated by workflow_authorized_credentials (fail-closed, prevents
    collaborator credential exfiltration).

    Raises ValueError if the credential cannot be resolved.
    """
    credential_data = await resolve_credential_with_owner_fallback(
        credential_id,
        user_id,
        pool,
        org_id=organization_id,
        workflow_id=workflow_id,
    )
    if not credential_data:
        # The model can't act on a bare UUID: give it the cause to relay.
        raise ValueError(await unresolved_credential_error(
            pool, credential_id, user_id=user_id, workflow_id=workflow_id,
            where="this tool's provider node",
        ))
    return credential_data


async def run_node_operation(
    *,
    node_type: str,
    operation: str,
    arguments: Dict[str, Any],
    user_id: str,
    pool=None,
    credential_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    workflow_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    credential_data: Optional[Dict[str, Any]] = None,
    approval_context: Optional[Dict[str, Any]] = None,
    operation_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Run a single integration-node operation and return its output dict.

    ``credential_data`` runs the operation with a credential that is not stored
    (the connect flow proving a typed-in key before saving it); otherwise
    ``credential_id`` is resolved through the owner-fallback seam.

    Builds the same node_data shape the workflow handler produces
    ({config, credentials, credential_id}), instantiates the node via
    NodeFactory (which parses/coerces config through the node's discriminated
    union), and calls execute({}) — integration nodes read only their config
    and credentials, not graph inputs.

    No sio/sid is passed: emit() is a guarded no-op, so no orphaned progress
    events reach the canvas for a node_id that doesn't exist on it. Credit
    gating/billing is unchanged: charging nodes enforce their own gate inside
    execute() (e.g. reddit_node enforce_credit_gate) using the
    user_id/organization_id passed here.
    """
    credentials = credential_data
    if credentials is None and credential_id:
        credentials = await resolve_operation_credential(
            credential_id, user_id, pool, organization_id, workflow_id
        )

    # Same empty-string → None cleanup as the workflow handler so optional
    # fields don't fail validation. `operation` is applied LAST so a caller-
    # supplied 'operation' argument can never override the declared
    # (allowlisted) one.
    from nodes.core.base import clean_config_empty_strings

    config = clean_config_empty_strings(arguments or {})
    config["operation"] = operation

    node_data: Dict[str, Any] = {"config": config, "_approval_context": approval_context, "_approval_pool": pool,
                               "_operation_context": operation_context}
    if credentials:
        node_data["credentials"] = credentials
        if credential_id:
            node_data["credential_id"] = credential_id

    instance = NodeFactory.create_node(
        node_id=f"node-op:{node_type}:{operation}",
        node_type=node_type,
        node_data=node_data,
        sio=None,
        sid=None,
        workflow_id=workflow_id,
        user_id=user_id,
        conversation_id=conversation_id,
        organization_id=organization_id,
    )

    logger.info(f"[RunOp] Executing {node_type}.{operation} for user {user_id}")
    try:
        async with credential_place(credential_id):
            with caller_path_scope("execute"):
                return await instance.run({})
    except (InsufficientBalanceError, OwnerResolutionError):
        # Billing-gate verdicts are actionable as-is; the missing-credential
        # hint below would mis-blame auth for an out-of-credits abort on a
        # platform-keyed (credential-less) operation.
        raise
    except Exception as e:
        if credentials is None and needs_credential_hint(node_type, operation, config):
            # Same seam as run_node_lookup: every node fails its own cryptic
            # way on missing auth, so give the model the actionable cause.
            raise ValueError(
                f"{node_type}.{operation} failed with no credential connected "
                f"to this tool's provider node ({e}) — if this action requires "
                f"auth, ask the user to connect a credential on the node and "
                f"try again."
            ) from e
        raise


async def run_node_lookup(
    *,
    node_type: str,
    field_name: str,
    user_id: str,
    pool=None,
    credential_id: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    page_token: Optional[str] = None,
    search: Optional[str] = None,
    organization_id: Optional[str] = None,
    workflow_id: Optional[str] = None,
    allowed_values: Optional[list] = None,
    conversation_id: Optional[str] = None,
    approval_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Run a node's dynamic-options loader standalone — the backend for the
    agent's {provider}__lookup_options tool. Mirrors the dropdown path in
    workflow_handler.handle_load_options: resolve+freshen the credential
    (non-execute read path, so freshen_credential under
    caller_path_scope('dropdown')), inject _user_id into context, normalize
    search, and call the node's load_field_options classmethod.

    Always returns {"options": [...], "next_page_token": ...} (legacy
    list-shaped loader results are normalized).
    """
    from nodes.core.dynamic_options import loader_context, normalize_search

    if credential_id:
        # Resolve access before creating a review request, just as execution does.
        await resolve_operation_credential(credential_id, user_id, pool, organization_id, workflow_id)
        from utils.credential_approval import admit_lookup
        pending = await admit_lookup(
            credential_id=credential_id, user_id=user_id, node_type=node_type, pool=pool,
            arguments={"field_name": field_name, "context": context, "page_token": page_token, "search": search},
            organization_id=organization_id, workflow_id=workflow_id,
            conversation_id=conversation_id, continuation=approval_context,
        )
        if pending:
            return pending

    node_class = NODE_REGISTRY.get(node_type)
    if node_class is None:
        raise ValueError(f"Unknown node type: {node_type}")
    if not hasattr(node_class, "load_field_options"):
        raise ValueError(f"{node_type} has no dynamic options loader")

    credential_data = None
    if credential_id:
        credential_data = await resolve_operation_credential(
            credential_id, user_id, pool, organization_id, workflow_id
        )
        with caller_path_scope("dropdown"):
            credential_data = await node_class.freshen_credential(
                credential_data,
                pool=pool,
                user_id=user_id,
                credential_id=credential_id,
            )

    lookup_context = loader_context(context, user_id=user_id, workflow_id=workflow_id)

    logger.info(f"[RunOp] Lookup {node_type}.{field_name} for user {user_id}")
    try:
        async with credential_place(credential_id):
            result = await node_class.load_field_options(
                field_name=field_name,
                credential_data=credential_data,
                context=lookup_context,
                page_token=page_token,
                search=normalize_search(search),
            )
    except Exception as e:
        if credential_data is None:
            # Loaders assume an authenticated credential dict; without one they
            # die with provider-specific noise ("'NoneType' object has no
            # attribute 'get'") the model can't act on, so surface a stable hint.
            raise ValueError(
                f"{node_type} options lookup failed because no credential is "
                f"connected to this tool's provider node — ask the user to "
                f"connect one on the workflow and try again."
            ) from e
        raise

    if isinstance(result, dict):
        options = result.get("options", []) or []
        next_token = result.get("next_page_token")
    else:
        options = result or []
        next_token = None

    # Resource scoping: when the agent's tool is locked to a specific set of
    # resource IDs, hide off-list options here too so the model can't discover
    # them via search. The execute_tool scope check rejects any off-list value
    # the model proposes anyway.
    if allowed_values:
        allow = {str(v) for v in allowed_values if isinstance(v, str)}
        options = [
            opt for opt in options
            if isinstance(opt, dict) and str(opt.get("value", "")) in allow
        ]

    return {"options": options, "next_page_token": next_token}

async def run_node_op_tool(
    info: Dict[str, Any],
    arguments: Optional[Dict[str, Any]],
    *,
    user_id: str,
    workflow_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Dispatch one node_op / node_op_lookup tool call (build_node_op_tools
    config shape) to the graph-free seam. Container-agnostic — shared by the
    hosted MCP endpoint and the shadow-tool cross-container fallback, so a
    tool call can execute on ANY backend container, not just the one holding
    the live agent."""
    # Mirror of the rehearsal gate in nodes/agent/tool_execution.py. This is the
    # path MCP-served tool calls take (CLI harnesses, hosted MCP links), so a
    # gate on only the in-process side would leave them executing for real
    # during a rehearsal.
    #
    # Keyed on the conversation, which the hosted-MCP endpoint also reaches this
    # function with — its `mcp-host:{id}` conversations can never match a
    # rehearsal key, so sharing this function is safe.
    from nodes.agent.rehearsal import UNFENCED_RESULT, is_rehearsing, must_rehearse

    if await is_rehearsing(conversation_id):
        from nodes.agent.rehearsal import rehearse_tool

        return await rehearse_tool(
            conversation_id, info.get("name") or info.get("operation") or "tool", arguments, info)
    if must_rehearse(conversation_id):  # its fence can't be read: refused, never run for real
        return dict(UNFENCED_RESULT)

    if info.get("tool_type") == "node_op_lookup":
        fields = info.get("fields") or {}
        field = (arguments or {}).get("field")
        if field not in fields:
            return {"success": False, "error": f"Unknown field '{field}'. Valid fields: {sorted(fields)}"}
        unconnected = credential_note_result(info)
        if unconnected:
            return unconnected
        context = (arguments or {}).get("context")
        scopes = info.get("field_scopes") or {}
        scope_for_field = scopes.get(field) if isinstance(scopes, dict) else None
        return await run_node_lookup(
            node_type=info["node_type"],
            field_name=fields[field],
            user_id=user_id,
            credential_id=info.get("credential_id"),
            context=context if isinstance(context, dict) else None,
            page_token=(arguments or {}).get("page_token"),
            search=(arguments or {}).get("search"),
            organization_id=organization_id,
            workflow_id=workflow_id,
            allowed_values=scope_for_field if isinstance(scope_for_field, list) else None,
        )

    # Resource-scope enforcement on the cross-container path (mirror of
    # _execute_node_op_tool in nodes/agent/tool_execution.py).
    scope_error = await field_scope_refusal(
        arguments or {}, info, user_id=user_id, organization_id=organization_id, workflow_id=workflow_id,
    )
    if scope_error:
        return {"success": False, "error": scope_error}
    unconnected = credential_note_result(info)
    if unconnected:
        return unconnected

    return await run_node_operation(
        node_type=info["node_type"],
        operation=info["operation"],
        arguments=arguments or {},
        user_id=user_id,
        credential_id=info.get("credential_id"),
        organization_id=organization_id,
        workflow_id=workflow_id,
        conversation_id=conversation_id,
    )


async def field_scope_refusal(
    arguments: Dict[str, Any],
    tool_info: Dict[str, Any],
    *,
    user_id: str,
    organization_id: Optional[str] = None,
    workflow_id: Optional[str] = None,
) -> Optional[str]:
    """Why a call's arguments fall outside its tool's ``field_scopes`` (stamped by
    build_node_op_tools when the user pinned an op to specific resource ids),
    else None. One check for the in-process and cross-container paths. A value
    the plain match refuses is put to the node's ``scope_matches``, which may
    know it by another id."""
    scopes = tool_info.get("field_scopes")
    if not isinstance(scopes, dict):
        return None
    from nodes.core.base import WorkflowNode

    node_class = NODE_REGISTRY.get(tool_info.get("node_type") or "")
    knows_aliases = node_class is not None and (
        node_class.scope_matches.__func__ is not WorkflowNode.scope_matches.__func__
    )
    credentials: Optional[Dict[str, Any]] = None
    for field, allowed in scopes.items():
        if not isinstance(allowed, list) or not allowed:
            continue
        value = arguments.get(field)
        # Unset scoped fields slip past here — the node's own required-field
        # check fails the call with a clear schema error. Avoid double-failing.
        if value is None or value == "" or value in allowed:
            continue
        if knows_aliases:
            if credentials is None:
                credentials = await _credentials_for_scope(tool_info, user_id, organization_id, workflow_id)
            if await node_class.scope_matches(field, str(value), [str(a) for a in allowed], credentials):
                continue
        return (
            f"'{field}' is restricted to a specific set of resources for this "
            f"tool. Allowed values: {sorted(allowed)}. Got: {value!r}."
        )
    return None


async def _credentials_for_scope(
    tool_info: Dict[str, Any], user_id: str, organization_id: Optional[str], workflow_id: Optional[str],
) -> Dict[str, Any]:
    """The provider's credential, for a node to read its other ids by. Empty when
    none is bound or it can't be resolved: the call is then judged on the ids
    alone, and running it fails on the credential anyway."""
    credential_id = tool_info.get("credential_id")
    if not credential_id:
        return {}
    try:
        return await resolve_operation_credential(credential_id, user_id, None, organization_id, workflow_id)
    except ValueError:
        return {}
