"""In-process cron scheduler for the local edition (NOCLICK_LOCAL=1).

Serves the SAME REST API as the Cloudflare cron-scheduler Worker
(infra/cloudflare/cron-scheduler), so utils.cron_scheduler_client needs no
local-mode branches — the launcher just points CRON_SCHEDULER_URL at
http://<backend>/local-cron with a generated CRON_SCHEDULER_SECRET. A single
asyncio ticker replaces the per-schedule Durable Object alarms. It claims
only available delivery capacity with short PostgreSQL leases and delivers
outside the transaction. Retries retain the occurrence ID; edits and
cancellations fence stale completions. The payload and signed headers match
the hosted scheduler for both workflow alarms and coordinator wakeups.

Storage is a local-only table created lazily at ticker start (NOT a supabase
migration — this table must never exist in the hosted schema).
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Header, HTTPException, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/local-cron")

_TICK_INTERVAL_S = 15.0  # Compatibility for callers of the idle-delay helper.

from repositories.local_schedules import LocalScheduleRepo

_ticker_task: Optional[asyncio.Task] = None
_schema_ready = False


def _require_secret(authorization: Optional[str]) -> None:
    secret = os.environ.get("CRON_SCHEDULER_SECRET", "")
    if not secret or authorization != f"Bearer {secret}":
        raise HTTPException(status_code=401, detail="Unauthorized")


from utils.cron_timing import _compute_next_run, _parse_run_at


def _row_json(row):
    import uuid
    result = {key: (value.isoformat() if isinstance(value, datetime) else str(value) if isinstance(value, uuid.UUID) else value)
              for key, value in dict(row).items()}
    return result


async def _ensure_schema(pool) -> None:
    global _schema_ready
    if _schema_ready:
        return
    await LocalScheduleRepo(pool).ensure_schema()
    _schema_ready = True


def _get_pool():
    from utils.database_pool import get_native_pool
    return get_native_pool()


# ── REST API (client contract: utils.cron_scheduler_client) ──────────────


@router.post("/schedules", status_code=201)
async def create_schedule(request: Request, authorization: Optional[str] = Header(None)):
    _require_secret(authorization)
    body = await request.json()
    pool = _get_pool()
    await _ensure_schema(pool)

    try:
        row = await LocalScheduleRepo(pool).save(body)
    except (ValueError, KeyError) as error:
        raise HTTPException(status_code=400, detail=str(error))
    return {"id": str(row["id"]), "next_run": row["next_run"].isoformat()}


@router.put("/schedules/{schedule_id}")
async def update_schedule(
    schedule_id: str, request: Request, authorization: Optional[str] = Header(None),
):
    _require_secret(authorization)
    body = await request.json()
    pool = _get_pool()
    await _ensure_schema(pool)

    try:
        return await LocalScheduleRepo(pool).update(schedule_id, body)
    except ValueError as error:
        raise HTTPException(404 if str(error) == "Schedule not found" else 400, str(error))


@router.get("/schedules")
async def list_schedules(workflow_id: Optional[str] = None, user_id: Optional[str] = None,
                         target_kind: Optional[str] = None, authorization: Optional[str] = Header(None)):
    _require_secret(authorization)
    pool = _get_pool()
    await _ensure_schema(pool)
    return [_row_json(r) for r in await LocalScheduleRepo(pool).list(workflow_id, user_id, target_kind)]


@router.get("/schedules/{schedule_id}")
async def get_schedule(schedule_id: str, authorization: Optional[str] = Header(None)):
    _require_secret(authorization)
    pool = _get_pool()
    await _ensure_schema(pool)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM local_cron_schedules WHERE id = $1", schedule_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return _row_json(row)


@router.delete("/schedules/by-workflow/{workflow_id}")
async def delete_by_workflow(workflow_id: str, authorization: Optional[str] = Header(None)):
    _require_secret(authorization)
    pool = _get_pool()
    await _ensure_schema(pool)
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM local_cron_schedules WHERE workflow_id = $1", workflow_id,
        )
    return {"deleted": int(result.split()[-1])}


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(schedule_id: str, authorization: Optional[str] = Header(None)):
    _require_secret(authorization)
    pool = _get_pool()
    await _ensure_schema(pool)
    deleted = await LocalScheduleRepo(pool).delete(schedule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"deleted": True}


@router.post("/schedules/bulk-delete-nodes")
async def bulk_delete_nodes(request: Request, authorization: Optional[str] = Header(None)):
    _require_secret(authorization)
    body = await request.json()
    workflow_id = body["workflow_id"]
    node_ids: List[str] = body.get("node_ids") or []
    keep_ids: List[str] = body.get("keep_ids") or []
    pool = _get_pool()
    await _ensure_schema(pool)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            DELETE FROM local_cron_schedules
            WHERE workflow_id = $1 AND node_id = ANY($2)
              AND NOT (id::text = ANY($3))
            RETURNING id
            """,
            workflow_id, node_ids, keep_ids,
        )
    return {"deleted": len(rows), "deleted_schedules": [str(r["id"]) for r in rows]}


# ── Bounded durable delivery (shared by workflow alarms and coordinator events) ──
_active_deliveries = set()
_recovery_tasks = set()


def _delivery_url(webhook_url):
    from urllib.parse import urlsplit, urlunsplit
    origin = os.environ.get("LOCAL_CRON_DELIVERY_ORIGIN", "").strip()
    if not origin:
        return webhook_url
    o, parts = urlsplit(origin), urlsplit(webhook_url)
    return urlunsplit((o.scheme, o.netloc, parts.path, parts.query, parts.fragment))


async def _deliver(row):
    runner = asyncio.current_task()

    async def heartbeat():
        try:
            while True:
                await asyncio.sleep(30)
                if not await LocalScheduleRepo(_get_pool()).heartbeat(row):
                    runner.cancel()
                    return
        except Exception:
            runner.cancel()

    lease = asyncio.create_task(heartbeat())
    try:
        await _deliver_owned(row)
    finally:
        lease.cancel()
        await asyncio.gather(lease, return_exceptions=True)


async def _deliver_owned(row):
    from utils.scheduler_delivery import delivery_headers
    body = json.dumps({"schedule_id": str(row["id"]), "delivery_id": str(row["occurrence_id"]),
                       "target_kind": row["target_kind"], "revision": str(row["revision"]),
                       "workflow_id": row["workflow_id"], "node_id": row["node_id"],
                       "user_id": row["user_id"], "triggered_at": row["triggered_at"].isoformat(),
                       "payload": row["payload"]}, separators=(",", ":")).encode()
    headers = {"Content-Type": "application/json", "X-Cron-Schedule-Id": str(row["id"]),
               "X-Cron-Attempt": str(row["attempts"]),
               **delivery_headers(body, os.environ.get("CRON_SCHEDULER_SECRET", ""))}
    retry_after, error, success = None, None, False
    try:
        async with httpx.AsyncClient(timeout=660) as client:
            response = await client.post(_delivery_url(row["webhook_url"]), content=body, headers=headers)
        success = response.is_success
        if not success:
            error = f"HTTP {response.status_code}"
            if response.status_code in (429, 503) or (response.status_code >= 500 and row["attempts"] < row["max_attempts"]):
                retry_after = min(86400, max(1, int(response.headers.get("Retry-After", "30"))))
            # Transient errors are bounded in time, not discarded after three busy responses.
    except Exception as exc:
        error = str(exc)
        retry_after = min(300, 2 ** min(row["attempts"], 8)) if row["attempts"] < row["max_attempts"] else None
    if (datetime.now(timezone.utc) - row["triggered_at"]).total_seconds() > 86400:
        retry_after = None
    await LocalScheduleRepo(_get_pool()).finish(row, success=success, error=error, retry_after=retry_after)


async def _tick():
    pool = _get_pool()
    await _ensure_schema(pool)
    for task in tuple(_active_deliveries):
        if task.done():
            _active_deliveries.remove(task)
            if not task.cancelled() and task.exception():
                logger.error("Local scheduler delivery failed", exc_info=task.exception())
    capacity = max(0, int(os.getenv("LOCAL_SCHEDULER_CONCURRENCY", "8")) - len(_active_deliveries))
    if capacity:
        for row in await LocalScheduleRepo(pool).claim(capacity):
            _active_deliveries.add(asyncio.create_task(_deliver(dict(row))))


def _sleep_seconds(earliest_next_run, now):
    if earliest_next_run is None:
        return _TICK_INTERVAL_S
    return min(_TICK_INTERVAL_S, max(1.0, (earliest_next_run - now).total_seconds()))


async def _run_ticker():
    import time
    next_recovery = 0.0
    recovery = None
    while True:
        try:
            await _tick()
            if time.monotonic() >= next_recovery and (recovery is None or recovery.done()):
                if recovery and not recovery.cancelled() and recovery.exception():
                    logger.error("Scheduler reconciliation failed", exc_info=recovery.exception())
                next_recovery = time.monotonic() + 60
                from utils.coordinator_dispatch import reconcile
                recovery = asyncio.create_task(reconcile(_get_pool()))
                _recovery_tasks.add(recovery)
                recovery.add_done_callback(_recovery_tasks.discard)
                await LocalScheduleRepo(_get_pool()).prune()
        except Exception:
            logger.exception("Local scheduler tick failed")
        # One second keeps short alarms responsive without spawning unbounded work.
        await asyncio.sleep(1)


def start_local_cron():
    global _ticker_task
    if _ticker_task is None or _ticker_task.done():
        _ticker_task = asyncio.create_task(_run_ticker())


async def stop_local_cron():
    global _ticker_task
    tasks = [*_active_deliveries, *_recovery_tasks, *([_ticker_task] if _ticker_task else [])]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    _active_deliveries.clear()
    _recovery_tasks.clear()
    _ticker_task = None
