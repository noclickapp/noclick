"""In-process cron scheduler for the local edition (NOCLICK_LOCAL=1).

Implements the scheduler REST contract consumed by cron_scheduler_client, so
the launcher only needs to point CRON_SCHEDULER_URL at
http://<backend>/local-cron with a generated CRON_SCHEDULER_SECRET. A single
asyncio ticker scans due rows, advances next_run first (at most once per
tick), then delivers each webhook with the shared schedule payload and
X-Cron-Schedule-Id header used by the stale-schedule guard.

Storage is a local-only table created lazily at ticker start rather than a
deployment migration.
"""

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Header, HTTPException, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/local-cron")

_TICK_INTERVAL_S = 15.0
_DELIVERY_TIMEOUT_S = 300.0  # workflows run inline on delivery; allow long runs

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS local_cron_schedules (
    id uuid PRIMARY KEY,
    user_id text NOT NULL,
    workflow_id text NOT NULL,
    node_id text NOT NULL,
    cron_expression text NOT NULL,
    webhook_url text NOT NULL,
    payload jsonb,
    timezone text NOT NULL DEFAULT 'UTC',
    enabled boolean NOT NULL DEFAULT true,
    run_once boolean NOT NULL DEFAULT false,
    max_attempts integer NOT NULL DEFAULT 3,
    next_run timestamptz NOT NULL,
    last_run timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE local_cron_schedules ADD COLUMN IF NOT EXISTS last_run timestamptz;
CREATE INDEX IF NOT EXISTS local_cron_schedules_due_idx
    ON local_cron_schedules (next_run) WHERE enabled;
"""

_ticker_task: Optional[asyncio.Task] = None
_schema_ready = False


def _require_secret(authorization: Optional[str]) -> None:
    secret = os.environ.get("CRON_SCHEDULER_SECRET", "")
    if not secret or authorization != f"Bearer {secret}":
        raise HTTPException(status_code=401, detail="Unauthorized")


# Scheduler expression formats — the same custom vocabulary the CF worker's
# cron-utils speaks: "*/Ns" seconds (+ optional 5-field constraint tail),
# "… /Nh" hour durations, "base /Nw" week-stepped weeklies, plain 5-field cron.
_SECONDS_FORMAT_RE = re.compile(r'^\*/(\d+)s(?:\s+(.*))?$')
_HOURS_FORMAT_RE = re.compile(r'/(\d+)h$')
_WEEKS_FORMAT_RE = re.compile(r'^(.+)\s/(\d+)w$')


def _expand_fields(expr: str):
    """Expression → (minutes, hours, doms, months, dows) as int sets, None =
    unrestricted. croniter does the parsing; evaluation is ours (below)."""
    from croniter import croniter

    fields = croniter.expand(expr)[0]

    def to_set(field) -> Optional[set]:
        if field == ['*']:
            return None
        return {int(v) for v in field}

    return tuple(to_set(f) for f in fields)


def _fields_match(sets, local_dt: datetime) -> bool:
    """Wall-clock membership, with restricted day-of-month AND day-of-week
    INTERSECTING — our generator's semantics, where vixie cron ORs them
    (unrestricted None passes, so the AND is correct for every combination)."""
    mins, hrs, doms, mons, dows = sets
    if mins is not None and local_dt.minute not in mins:
        return False
    if hrs is not None and local_dt.hour not in hrs:
        return False
    if mons is not None and local_dt.month not in mons:
        return False
    if doms is not None and local_dt.day not in doms:
        return False
    if dows is not None and (local_dt.weekday() + 1) % 7 not in dows:
        return False
    return True


def _next_standard(expr: str, tz_name: str, after_utc: datetime) -> datetime:
    """Next fire of a 5-field expression strictly after ``after_utc``,
    DST-correct by construction: local wall-clock candidates are built
    directly with zoneinfo (fold=0 = first occurrence of a fall-back
    repeated hour; spring-forward gap times round-trip-detected and
    skipped) instead of stepping croniter, whose iteration lands fires
    ±1h around DST transitions."""
    sets = _expand_fields(expr)
    mins, hrs, doms, mons, dows = sets
    minutes = sorted(mins) if mins is not None else range(60)
    hours = sorted(hrs) if hrs is not None else range(24)
    tz = ZoneInfo(tz_name or "UTC")
    utc = timezone.utc
    start_date = after_utc.astimezone(tz).date()
    for offset in range(4000):  # ~11-year scan horizon
        d = start_date + timedelta(days=offset)
        if mons is not None and d.month not in mons:
            continue
        if doms is not None and d.day not in doms:
            continue
        if dows is not None and (d.weekday() + 1) % 7 not in dows:
            continue
        for h in hours:
            for m in minutes:
                naive = datetime(d.year, d.month, d.day, h, m)
                candidate = naive.replace(tzinfo=tz).astimezone(utc)
                if candidate.astimezone(tz).replace(tzinfo=None) != naive:
                    continue  # nonexistent wall-clock time (spring-forward gap)
                if candidate > after_utc:
                    return candidate
    raise ValueError(f"No upcoming run for {expr!r} within the scan horizon")


def _compute_next_run(
    cron_expression: str, tz_name: str, last_run: Optional[datetime] = None,
) -> datetime:
    """Next fire (UTC) for any scheduler expression, worker-parity semantics."""
    expr = cron_expression.strip()
    now_utc = datetime.now(timezone.utc)

    m = _SECONDS_FORMAT_RE.match(expr)
    if m:
        candidate = now_utc + timedelta(seconds=max(1, int(m.group(1))))
        tail = (m.group(2) or "").split()
        if len(tail) == 5:  # constrained: gate the candidate's minute
            tail_expr = " ".join(tail)
            local = candidate.astimezone(ZoneInfo(tz_name or "UTC"))
            if not _fields_match(_expand_fields(tail_expr), local):
                return _next_standard(tail_expr, tz_name, candidate)
        return candidate

    wm = _WEEKS_FORMAT_RE.match(expr)
    if wm:
        base_next = _next_standard(wm.group(1).strip(), tz_name, now_utc)
        interval = max(1, int(wm.group(2)))
        if last_run is not None and interval > 1:
            weeks_since = int((base_next - last_run).total_seconds() // (7 * 86400))
            skip = interval - (weeks_since % interval)
            if 0 < skip < interval:
                return base_next + timedelta(weeks=skip)
        return base_next

    hm = _HOURS_FORMAT_RE.search(expr)
    if hm:  # "/Nh" duration format: true every-N-hours-from-now
        return now_utc + timedelta(hours=max(1, int(hm.group(1))))

    return _next_standard(expr, tz_name, now_utc)


def _parse_run_at(run_at: str) -> datetime:
    dt = datetime.fromisoformat(run_at.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _row_json(row) -> Dict[str, Any]:
    return {
        "id": str(row["id"]),
        "user_id": row["user_id"],
        "workflow_id": row["workflow_id"],
        "node_id": row["node_id"],
        "cron_expression": row["cron_expression"],
        "webhook_url": row["webhook_url"],
        "payload": row["payload"],
        "timezone": row["timezone"],
        "enabled": row["enabled"],
        "run_once": row["run_once"],
        "max_attempts": row["max_attempts"],
        "next_run": row["next_run"].isoformat(),
        "created_at": row["created_at"].isoformat(),
    }


async def _ensure_schema(pool) -> None:
    global _schema_ready
    if _schema_ready:
        return
    async with pool.acquire() as conn:
        await conn.execute(_SCHEMA_SQL)
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

    import uuid as uuid_module
    schedule_id = str(body.get("id") or uuid_module.uuid4())
    run_once = bool(body.get("run_once"))
    # `tz` is the wire field for evaluation timezone (same contract as the CF
    # worker); the legacy `timezone` field rode alongside UTC-pre-converted
    # expressions and must stay ignored.
    tz_name = body.get("tz") or "UTC"
    if run_once:
        next_run = _parse_run_at(body["run_at"])
    else:
        try:
            next_run = _compute_next_run(body["cron_expression"], tz_name)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid cron expression: {e}")

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO local_cron_schedules
                (id, user_id, workflow_id, node_id, cron_expression, webhook_url,
                 payload, timezone, run_once, max_attempts, next_run)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            ON CONFLICT (id) DO UPDATE SET
                cron_expression = EXCLUDED.cron_expression,
                webhook_url = EXCLUDED.webhook_url,
                payload = EXCLUDED.payload,
                timezone = EXCLUDED.timezone,
                run_once = EXCLUDED.run_once,
                max_attempts = EXCLUDED.max_attempts,
                next_run = EXCLUDED.next_run,
                enabled = true,
                updated_at = now()
            """,
            schedule_id, body["user_id"], body["workflow_id"], body["node_id"],
            body["cron_expression"], body["webhook_url"], body.get("payload"),
            tz_name, run_once, int(body.get("max_attempts") or 3), next_run,
        )
    return {"id": schedule_id, "next_run": next_run.isoformat()}


@router.put("/schedules/{schedule_id}")
async def update_schedule(
    schedule_id: str, request: Request, authorization: Optional[str] = Header(None),
):
    _require_secret(authorization)
    body = await request.json()
    pool = _get_pool()
    await _ensure_schema(pool)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM local_cron_schedules WHERE id = $1", schedule_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Schedule not found")

        cron_expression = body.get("cron_expression", row["cron_expression"])
        next_run = row["next_run"]
        if "cron_expression" in body:
            next_run = _compute_next_run(cron_expression, row["timezone"], row["last_run"])
        await conn.execute(
            """
            UPDATE local_cron_schedules SET
                cron_expression = $2, webhook_url = $3, payload = $4,
                enabled = $5, max_attempts = $6, next_run = $7, updated_at = now()
            WHERE id = $1
            """,
            schedule_id, cron_expression,
            body.get("webhook_url", row["webhook_url"]),
            body["payload"] if "payload" in body else row["payload"],
            bool(body.get("enabled", row["enabled"])),
            int(body.get("max_attempts", row["max_attempts"])),
            next_run,
        )
    return {"success": True, "next_run": next_run.isoformat()}


@router.get("/schedules")
async def list_schedules(workflow_id: str, authorization: Optional[str] = Header(None)):
    _require_secret(authorization)
    pool = _get_pool()
    await _ensure_schema(pool)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM local_cron_schedules WHERE workflow_id = $1", workflow_id,
        )
    return [_row_json(r) for r in rows]


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
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM local_cron_schedules WHERE id = $1", schedule_id,
        )
    deleted = int(result.split()[-1])
    if not deleted:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"deleted": deleted}


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


# ── Ticker ───────────────────────────────────────────────────────────────


async def _deliver(schedule: Dict[str, Any], triggered_at: datetime) -> None:
    """Worker-parity delivery: same body/headers, 4xx = no retry."""
    payload = schedule["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    body = {
        "schedule_id": schedule["id"],
        "workflow_id": schedule["workflow_id"],
        "user_id": schedule["user_id"],
        "node_id": schedule["node_id"],
        "triggered_at": triggered_at.isoformat(),
        "payload": payload,
    }
    max_attempts = max(1, int(schedule["max_attempts"]))
    async with httpx.AsyncClient(timeout=_DELIVERY_TIMEOUT_S) as client:
        for attempt in range(1, max_attempts + 1):
            try:
                response = await client.post(
                    schedule["webhook_url"],
                    json=body,
                    headers={
                        "X-Cron-Schedule-Id": schedule["id"],
                        "X-Cron-Attempt": str(attempt),
                    },
                )
                if response.is_success:
                    return
                logger.warning(
                    f"[local-cron] schedule {schedule['id'][:8]} attempt {attempt}: HTTP {response.status_code}"
                )
                if 400 <= response.status_code < 500:
                    return
            except Exception as e:
                logger.warning(f"[local-cron] schedule {schedule['id'][:8]} attempt {attempt}: {e}")
            if attempt < max_attempts:
                await asyncio.sleep(min(2 ** attempt, 10))


async def _tick() -> None:
    pool = _get_pool()
    await _ensure_schema(pool)
    now = datetime.now(timezone.utc)
    async with pool.acquire() as conn:
        due = await conn.fetch(
            "SELECT * FROM local_cron_schedules WHERE enabled AND next_run <= $1", now,
        )
        for row in due:
            # Advance bookkeeping BEFORE delivering so a slow/hung workflow run
            # can't re-fire the same tick, and one schedule can't block others.
            if row["run_once"]:
                await conn.execute(
                    "DELETE FROM local_cron_schedules WHERE id = $1", row["id"],
                )
            else:
                try:
                    # This delivery anchors /Nw week stepping (worker parity).
                    next_run = _compute_next_run(row["cron_expression"], row["timezone"], now)
                except Exception as e:
                    logger.error(
                        f"[local-cron] disabling schedule {row['id']} — bad expression: {e}"
                    )
                    await conn.execute(
                        "UPDATE local_cron_schedules SET enabled = false WHERE id = $1",
                        row["id"],
                    )
                    continue
                await conn.execute(
                    "UPDATE local_cron_schedules SET next_run = $2, last_run = $3, updated_at = now() WHERE id = $1",
                    row["id"], next_run, now,
                )
            from utils.async_helpers import spawn
            spawn(_deliver(_row_json(row), now), name=f"local-cron-{row['id']}")


async def _run_ticker() -> None:
    logger.info("[local-cron] ticker started")
    while True:
        try:
            await _tick()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"[local-cron] tick failed: {e}", exc_info=True)
        await asyncio.sleep(_TICK_INTERVAL_S)


def start_local_cron() -> None:
    global _ticker_task
    if _ticker_task is None or _ticker_task.done():
        _ticker_task = asyncio.create_task(_run_ticker())


async def stop_local_cron() -> None:
    global _ticker_task
    if _ticker_task is not None:
        _ticker_task.cancel()
        try:
            await _ticker_task
        except (asyncio.CancelledError, Exception):
            pass
        _ticker_task = None
