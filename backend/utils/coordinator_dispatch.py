"""Deliver coordinator inbox events through the existing scheduler backend.

Registration uses a stable ID. The inbox is an outbox until registration is
confirmed; reconciliation repairs crashes between the DB commit and scheduler.
"""
import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone

from utils import cron_scheduler_client as scheduler

logger = logging.getLogger(__name__)
_callback_provider = None


def register_callback_url(provider):
    global _callback_provider
    _callback_provider = provider


async def callback_url():
    if _callback_provider:
        return await _callback_provider()
    return f"http://127.0.0.1:{os.getenv('PORT', '8000')}/internal/scheduler/coordinator"


async def dispatch_event(pool, event):
    try:
        return await _register_event(pool, event)
    except Exception:
        logger.exception("Coordinator scheduler registration deferred: %s", event["id"])
        return False


async def _register_event(pool, event):
    if event["status"] == "waiting":
        return False  # Link creation is not a completion or a scheduled model turn.
    if event["status"] in ("done", "skipped"):
        return True
    if not scheduler.is_cron_scheduler_enabled():
        return False
    schedule_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"coordinator-delivery:{event['id']}"))
    # Recovery must preserve an existing pending occurrence and its retry state.
    existing = await scheduler.get_schedule(schedule_id)
    if existing.get("id") and existing.get("enabled"):
        from repositories.coordinator_wakeups import CoordinatorWakeupRepo
        await CoordinatorWakeupRepo(pool).dispatched(event["id"])
        return True
    if existing.get("id"):
        # A failed transport can be repaired without repeating an already-started turn.
        result = await scheduler.update_schedule(schedule_id, enabled=True)
    else:
        result = await scheduler.create_alarm(
            user_id=str(event["user_id"]), workflow_id=None, node_id=None,
            run_at=datetime.now(timezone.utc).isoformat(), webhook_url=await callback_url(),
            schedule_id=schedule_id, target_kind="coordinator_wakeup", payload={"event_id": str(event["id"])},
        )
    if result.get("error") or result.get("skipped"):
        logger.warning("Coordinator dispatch registration failed: event=%s error=%s", event["id"], result.get("error"))
        return False
    from repositories.coordinator_wakeups import CoordinatorWakeupRepo
    await CoordinatorWakeupRepo(pool).dispatched(event["id"])
    return True


async def reconcile(pool):
    from repositories.coordinator_wakeups import CoordinatorWakeupRepo
    from utils.media_generation import poll_video_jobs
    from repositories.coordinator_links import CoordinatorLinkRepo

    # The coordinator's minute: advance its media jobs, then its inbox.
    await poll_video_jobs(pool)
    await CoordinatorLinkRepo(pool).expire()
    repo = CoordinatorWakeupRepo(pool)
    await repo.reap_stalled()
    await repo.prune()
    from utils.credential_approval_dispatch import dispatch_workflows
    await dispatch_workflows(pool)
    rows = await repo.reconciliation_batch(limit=50)
    semaphore = asyncio.Semaphore(10)

    async def repair(row):
        async with semaphore:
            try:
                return await dispatch_event(pool, dict(row))
            except Exception:
                logger.exception("Coordinator dispatch reconciliation failed: %s", row["id"])
                return False

    results = await asyncio.gather(*(repair(row) for row in rows))
    logger.info("Coordinator dispatch recovery: scanned=%d registered=%d", len(rows), sum(results))
