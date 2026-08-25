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

import logging
from typing import Any, Dict, Optional

from billing.exceptions import InsufficientBalanceError, OwnerResolutionError
from nodes.core.registry import NodeFactory
from nodes.core.oauth_audit import caller_path_scope
from utils.credentials import resolve_credential_with_owner_fallback

logger = logging.getLogger(__name__)


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
        # The model can't act on a bare UUID — tell it the actionable cause so
        # it relays "reconnect the credential" instead of a dead-end error
        # (resolution returns empty for revoked/disconnected rows too).
        raise ValueError(
            f"Failed to resolve credential {credential_id} — it may have been "
            f"disconnected or revoked. Ask the user to reconnect the credential "
            f"on this tool's provider node and try again."
        )
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
) -> Dict[str, Any]:
    """
    Run a single integration-node operation and return its output dict.

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
    credentials = None
    if credential_id:
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

    node_data: Dict[str, Any] = {"config": config}
    if credentials:
        node_data["credentials"] = credentials
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
        with caller_path_scope("execute"):
            return await instance.run({})
    except (InsufficientBalanceError, OwnerResolutionError):
        # Billing-gate verdicts are actionable as-is; the missing-credential
        # hint below would mis-blame auth for an out-of-credits abort on a
        # platform-keyed (credential-less) operation.
        raise
    except Exception as e:
        if credentials is None:
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
    from nodes.core.registry import NODE_REGISTRY
    from nodes.core.dynamic_options import normalize_search

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

    lookup_context = dict(context or {})
    lookup_context["_user_id"] = user_id

    logger.info(f"[RunOp] Lookup {node_type}.{field_name} for user {user_id}")
    try:
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
