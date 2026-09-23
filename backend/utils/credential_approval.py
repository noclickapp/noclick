"""Enforce credential restrictions at the shared operation execution boundary.

No caller may supply an approval verdict. Only an unexpired, exact-call grant
written by the owner's authenticated review page can admit a restricted call.
"""

from mcp_adapter.auth.endpoints import get_frontend_url
from repositories.credential_approvals import CredentialApprovalRepo
from utils.database_pool import get_native_pool


async def notify_created(row):
    if not row or not row.get("new_request"):
        return
    from utils.socket_singleton import get_sio
    from wss.sender import send_event
    from wss.sender.events import ApprovalRequestCreatedEvent
    try:
        await send_event(get_sio(), None, ApprovalRequestCreatedEvent(
            approval_id=str(row["id"]), workflow_id="", execution_id="", node_id="__credential__",
            title=row["title"], fields=[], values={},
        ), user_id=row["owner_id"])
    except Exception:
        # Durable queue admission already committed. A disconnected browser
        # reloads the queue on focus; notification failure never authorizes I/O.
        import logging
        logging.getLogger(__name__).warning("Could not notify browser of credential approval %s", row["id"], exc_info=True)


def pending_result(row):
    return {"status": "pending_approval" if row["status"] == "pending" else "rejected",
            "executed": False, "approval_id": str(row["id"]),
            "approval_url": f"{get_frontend_url().rstrip('/')}/credential/approval/{row['id']}",
            "message": "The credential owner must review this exact call. Retry the same call after approval.",
            "_halt_downstream": True}


async def admit_node(node, inputs):
    credential_id = node.node_data.get("credential_id")
    if not credential_id:
        return None
    config = node.config
    inner = getattr(config, "config", config)
    arguments = inner.model_dump(mode="json") if hasattr(inner, "model_dump") else dict(inner or {})
    operation = arguments.pop("operation", None) or "execute"
    # Inputs matter for nodes that consume predecessor data; keep them bound
    # without ever serializing the outer config's decrypted credentials.
    if inputs:
        arguments["__inputs__"] = inputs
    row = await CredentialApprovalRepo(node.node_data.get("_approval_pool") or get_native_pool()).admit(
        credential_id=str(credential_id), user_id=node.user_id, node_type=node.node_type,
        operation=operation, arguments=arguments, organization_id=node.organization_id,
        workflow_id=node.workflow_id, execution_id=node.execution_id, node_id=node.node_id,
        conversation_id=node.conversation_id, continuation=node.node_data.get("_approval_context"),
    )
    await notify_created(row)
    return pending_result(row) if row else None


async def forbid_secret_export(credential_id, *, pool=None):
    """A restricted integration token cannot be exported to a shell/git mount.

    Giving a sandbox the raw token would bypass every per-operation decision.
    Restricted credentials remain usable through their mediated node/MCP tools.
    """
    pool = pool or get_native_pool()
    restricted = await CredentialApprovalRepo(pool).has_restrictions(credential_id)
    if restricted:
        raise PermissionError("This credential requires operation approval and cannot be exported to a sandbox. Use its integration tools.")


async def admit_lookup(*, credential_id, user_id, node_type, arguments, pool=None,
                       organization_id=None, workflow_id=None, conversation_id=None, continuation=None):
    row = await CredentialApprovalRepo(pool or get_native_pool()).admit(
        credential_id=credential_id, user_id=user_id, node_type=node_type, operation="__lookup__",
        arguments=arguments, organization_id=organization_id, workflow_id=workflow_id,
        conversation_id=conversation_id, continuation=continuation,
    )
    await notify_created(row)
    return pending_result(row) if row else None


async def admit_lookups(*, credential_ids, user_id, node_type, arguments, pool, workflow_id=None):
    """One loader invocation can touch multiple credentials; none is consumed early."""
    rows = await CredentialApprovalRepo(pool).admit_many([
        {"credential_id": cid, "user_id": user_id, "node_type": node_type, "operation": "__lookup__",
         "arguments": arguments, "workflow_id": workflow_id}
        for cid in sorted(set(credential_ids))
    ])
    for row in rows:
        await notify_created(row)
    if not rows:
        return None
    results = [pending_result(row) for row in rows]
    return {**results[0], "approvals": results}
