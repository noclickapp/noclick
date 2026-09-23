"""Deliver credential decisions and recover approved workflow continuations.

The existing approval rows remain the outbox. The shared maintenance tick (both
editions) retries unstarted work; a consumed grant is never blindly replayed.
"""

import asyncio
import logging

from repositories.credential_approvals import CredentialApprovalRepo

logger = logging.getLogger(__name__)


async def dispatch_decision(pool, row):
    from repositories.coordinator_wakeups import CoordinatorWakeupRepo
    from utils.coordinator_dispatch import dispatch_event
    event = await CoordinatorWakeupRepo(pool).by_source("credential_approval", str(row["id"]))
    if event:
        await dispatch_event(pool, event)
    try:
        from utils.socket_singleton import get_sio
        from wss.sender import send_event
        from wss.sender.events import ApprovalRequestResolvedEvent
        await send_event(get_sio(), None, ApprovalRequestResolvedEvent(
            approval_id=str(row["id"]), workflow_id=str(row["workflow_id"] or ""),
            status=row["status"], decided_by=str(row["decided_by"]),
        ), user_id=str(row["user_id"]))
    except Exception:
        logger.warning("Credential decision notification deferred: %s", row["id"], exc_info=True)
    if row["execution_id"] and row["status"] == "approved":
        await dispatch_workflows(pool, str(row["execution_id"]))


async def dispatch_workflows(pool, execution_id=None):
    """Register bounded deliveries; never execute workflows in maintenance."""
    import uuid
    from datetime import datetime, timezone
    from utils import cron_scheduler_client as scheduler
    from utils.coordinator_dispatch import callback_url
    if not scheduler.is_cron_scheduler_enabled():
        return
    repo = CredentialApprovalRepo(pool)
    for item in await repo.resumable_workflows(execution_id):
        await repo.defer_dispatch(str(item["execution_id"]))
        grants = await repo.workflow_grants(str(item["execution_id"]))
        if not grants:
            continue
        first = grants[0]
        schedule_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"credential-approval:{first['id']}"))
        existing = await scheduler.get_schedule(schedule_id)
        if existing.get("id") and existing.get("enabled"):
            continue
        if existing.get("id"):
            result = await scheduler.update_schedule(schedule_id, enabled=True)
        else:
            result = await scheduler.create_alarm(
                user_id=first["action_payload"]["caller_user_id"], workflow_id=None,
                node_id=None, schedule_id=schedule_id, target_kind="credential_approval",
                run_at=datetime.now(timezone.utc).isoformat(),
                webhook_url=(await callback_url()).rsplit("/", 1)[0] + "/credential-approval",
                payload={"approval_id": str(first["id"])},
            )
        if result.get("error") or result.get("skipped"):
            logger.warning("Credential resume registration deferred: %s", first["id"])


async def resume_workflows(pool, execution_id=None):
    from utils.node_outputs import execution_outputs
    from utils.socket_singleton import get_sio
    from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler

    repo = CredentialApprovalRepo(pool)
    semaphore = asyncio.Semaphore(5)

    async def resume(item):
        async with semaphore:
            eid = str(item["execution_id"])
            claimed = False
            try:
                grants = await repo.workflow_grants(eid)
                if not grants:
                    return
                outputs = await execution_outputs(pool, eid)
                # Admission happens before the original run checkpoints. An
                # instant approval waits for that checkpoint, never runs twice.
                if any(not isinstance(outputs.get(g["node_id"]), dict)
                       or outputs[g["node_id"]].get("approval_id") != str(g["id"]) for g in grants):
                    return False
                claimed = await repo.claim_workflow_resume(eid, [g["id"] for g in grants])
                if not claimed:
                    return
                first = grants[0]
                payload = first["action_payload"]
                await WorkflowExecutionHandler(get_sio()).handle_resume(
                    sid="", caller_user_id=payload["caller_user_id"],
                    data={"execution_id": eid, "workflow_id": str(first["workflow_id"]),
                          "workflow_org_id": payload.get("organization_id"), "resume_node_id": first["node_id"],
                          "from_status": "awaiting_approval", "retry_credential_node": True,
                          "credential_resume_nodes": [g["node_id"] for g in grants]},
                )
            except Exception:
                logger.exception("Credential workflow resume deferred: %s", eid)
            finally:
                if claimed:
                    await repo.restore_unstarted_resume(eid)
            return True

    results = await asyncio.gather(*(resume(item) for item in await repo.resumable_workflows(execution_id)))
    return all(result is not False for result in results)
