"""Authenticated scheduler callbacks; each request is one bounded execution input."""
import json
import uuid

from fastapi import APIRouter, HTTPException, Request

from repositories.coordinator_wakeups import CoordinatorWakeupRepo
from utils import cron_scheduler_client as scheduler
from utils.database_pool import get_native_pool
from utils.scheduler_delivery import verify_delivery

router = APIRouter()


@router.post("/internal/scheduler/coordinator")
async def scheduled_coordinator(request: Request):
    raw = await request.body()
    if len(raw) > 32768 or not verify_delivery(raw, request.headers, scheduler.CRON_SCHEDULER_SECRET, max_age=None):
        raise HTTPException(401, "Invalid scheduler signature")
    if not verify_delivery(raw, request.headers, scheduler.CRON_SCHEDULER_SECRET):
        # A valid signed request may age while queued at the cloud concurrency
        # ceiling. Retry with a fresh signature; never treat overload as a lost alarm.
        raise HTTPException(503, "Scheduler delivery expired in transit", headers={"Retry-After": "30"})
    try:
        body = json.loads(raw)
        uuid.UUID(body["user_id"])
        uuid.UUID(body["schedule_id"])
        uuid.UUID(body["delivery_id"])
        kind = body["target_kind"]
        payload = body["payload"]
        if kind not in ("coordinator", "coordinator_wakeup") or not isinstance(payload, dict):
            raise ValueError("Invalid target")
        if kind == "coordinator" and (not isinstance(body.get("revision"), str)
                or not isinstance(payload.get("context"), dict) or not isinstance(payload.get("message"), str)):
            raise ValueError("Invalid alarm")
    except (KeyError, TypeError, ValueError):
        raise HTTPException(400, "Invalid scheduler event")
    pool = get_native_pool()
    repo = CoordinatorWakeupRepo(pool)
    if kind == "coordinator":
        # Verify current ownership/revision; cancelled or replaced schedules cannot act.
        current = await scheduler.get_schedule(body["schedule_id"])
        if current.get("error"):
            if current["error"] == "Schedule not found":
                return {"skipped": True}
            raise HTTPException(503, "Scheduler lookup unavailable", headers={"Retry-After": "30"})
        if (current.get("user_id") != body["user_id"] or not current.get("enabled")
                or current.get("revision") != body["revision"]):
            return {"skipped": True}
        if ((payload.get("context") or {}).get("epoch") != await repo.epoch(body["user_id"])
                or await repo.alarm_stopped(body["schedule_id"], body["revision"])):
            await scheduler.update_schedule(body["schedule_id"], enabled=False, expected_revision=body["revision"])
            return {"skipped": True}
        event = await repo.accept_alarm(body)
    else:
        try:
            event = await repo.get(str(uuid.UUID(payload["event_id"])))
        except (ValueError, KeyError, TypeError):
            raise HTTPException(400, "Invalid event ID")
        if not event or str(event["user_id"]) != body["user_id"]:
            return {"skipped": True}
    if event["source"] == "alarm":
        # Also validate recovered inbox events, and close the window between
        # the first lookup and insertion racing an edit/cancel in another store.
        current = await scheduler.get_schedule(str(event["alarm_id"]))
        if current.get("error") and current["error"] != "Schedule not found":
            raise HTTPException(503, "Scheduler lookup unavailable", headers={"Retry-After": "30"})
        if (not current.get("enabled") or current.get("user_id") != str(event["user_id"])
                or current.get("revision") != event["payload"].get("scheduler_revision")):
            await repo.discard(event)
            return {"skipped": True}
    from coder.coordinator.wakeups import process_event
    from datetime import datetime, timezone
    from utils.otel import get_tracer
    with get_tracer("noclick.coordinator").start_as_current_span("coordinator.wakeup") as span:
        span.set_attributes({"coordinator.event_id": str(event["id"]), "user.id": body["user_id"],
                             "coordinator.source": event["source"], "coordinator.status": event["status"],
                             "coordinator.queue_age_seconds": max(0, (datetime.now(timezone.utc) - event["created_at"]).total_seconds())})
        complete = await process_event(pool, event)
        span.set_attribute("coordinator.backpressure", not complete)
    if not complete:
        delay = await repo.retry_delay(event)
        raise HTTPException(503, "Coordinator is busy", headers={"Retry-After": str(delay)})
    return {"delivered": True}


@router.post("/internal/scheduler/credential-approval")
async def scheduled_credential_approval(request: Request):
    """The same signed scheduler transports approved workflow continuations."""
    raw = await request.body()
    if len(raw) > 32768 or not verify_delivery(raw, request.headers, scheduler.CRON_SCHEDULER_SECRET, max_age=None):
        raise HTTPException(401, "Invalid scheduler signature")
    if not verify_delivery(raw, request.headers, scheduler.CRON_SCHEDULER_SECRET):
        raise HTTPException(503, "Scheduler delivery expired in transit", headers={"Retry-After": "30"})
    try:
        body = json.loads(raw)
        caller_id = str(uuid.UUID(body["user_id"]))
        approval_id = str(uuid.UUID(body["payload"]["approval_id"]))
        if body["target_kind"] != "credential_approval":
            raise ValueError("Invalid target")
    except (KeyError, TypeError, ValueError):
        raise HTTPException(400, "Invalid approval delivery")
    from repositories.credential_approvals import CredentialApprovalRepo
    from utils.credential_approval_dispatch import resume_workflows
    pool = get_native_pool()
    row = await CredentialApprovalRepo(pool).scheduled_request(approval_id, caller_id)
    if not row or row["status"] != "approved" or row["consumed_at"] or not row["execution_id"]:
        return {"skipped": True}
    if not await resume_workflows(pool, str(row["execution_id"])):
        raise HTTPException(503, "Workflow checkpoint is not ready", headers={"Retry-After": "10"})
    return {"delivered": True}
