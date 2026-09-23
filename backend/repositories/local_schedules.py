"""Local implementation of the shared scheduler's durable delivery contract.

Bounded SKIP LOCKED claims, stable occurrence IDs, attempt fencing, and retry
state survive process exits. No connection is held during webhook delivery.
"""
import uuid
from datetime import datetime, timedelta, timezone

from utils.cron_timing import _compute_next_run, _parse_run_at

SCHEMA = """
CREATE TABLE IF NOT EXISTS local_cron_schedules (
 id uuid PRIMARY KEY, user_id text NOT NULL, workflow_id text, node_id text,
 cron_expression text NOT NULL, webhook_url text NOT NULL, payload jsonb,
 timezone text NOT NULL DEFAULT 'UTC', enabled boolean NOT NULL DEFAULT true,
 run_once boolean NOT NULL DEFAULT false, max_attempts integer NOT NULL DEFAULT 3,
 next_run timestamptz NOT NULL, last_run timestamptz,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE local_cron_schedules ALTER COLUMN workflow_id DROP NOT NULL;
ALTER TABLE local_cron_schedules ALTER COLUMN node_id DROP NOT NULL;
ALTER TABLE local_cron_schedules ADD COLUMN IF NOT EXISTS last_run timestamptz;
ALTER TABLE local_cron_schedules ADD COLUMN IF NOT EXISTS target_kind text NOT NULL DEFAULT 'workflow';
ALTER TABLE local_cron_schedules ADD COLUMN IF NOT EXISTS revision uuid NOT NULL DEFAULT gen_random_uuid();
ALTER TABLE local_cron_schedules ADD COLUMN IF NOT EXISTS occurrence_id uuid;
ALTER TABLE local_cron_schedules ADD COLUMN IF NOT EXISTS triggered_at timestamptz;
ALTER TABLE local_cron_schedules ADD COLUMN IF NOT EXISTS lease_owner uuid;
ALTER TABLE local_cron_schedules ADD COLUMN IF NOT EXISTS lease_until timestamptz;
ALTER TABLE local_cron_schedules ADD COLUMN IF NOT EXISTS attempts integer NOT NULL DEFAULT 0;
ALTER TABLE local_cron_schedules ADD COLUMN IF NOT EXISTS last_error text;
ALTER TABLE local_cron_schedules ADD COLUMN IF NOT EXISTS last_status text;
CREATE INDEX IF NOT EXISTS local_cron_schedules_due_idx ON local_cron_schedules(next_run) WHERE enabled;
CREATE INDEX IF NOT EXISTS local_cron_schedules_owner_idx ON local_cron_schedules(user_id,target_kind,created_at);
CREATE INDEX IF NOT EXISTS local_cron_schedules_retention_idx ON local_cron_schedules(updated_at) WHERE NOT enabled;
ALTER TABLE local_cron_schedules ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON local_cron_schedules FROM anon, authenticated;
"""


class LocalScheduleRepo:
    def __init__(self, pool):
        self.pool = pool

    async def ensure_schema(self):
        # Multiple local backend processes may start against the same database.
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('local-scheduler-schema',0))")
            await conn.execute(SCHEMA)

    async def save(self, body):
        kind = body.get("target_kind", "workflow")
        if kind not in ("workflow", "coordinator", "coordinator_wakeup", "credential_approval"):
            raise ValueError("Invalid schedule target")
        if not body.get("user_id") or not body.get("webhook_url"):
            raise ValueError("Missing user_id or webhook_url")
        if kind == "workflow" and not (body.get("workflow_id") and body.get("node_id")):
            raise ValueError("Workflow targets require workflow_id and node_id")
        if kind != "workflow" and (body.get("workflow_id") or body.get("node_id")):
            raise ValueError("Account targets cannot specify a workflow")
        once = bool(body.get("run_at"))
        cron = "__run_at__" if once else body["cron_expression"]
        zone = body.get("tz") or "UTC"
        due = _parse_run_at(body["run_at"]) if once else _compute_next_run(cron, zone)
        schedule_id = uuid.UUID(str(body.get("id") or uuid.uuid4()))
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", f"schedule:{body['user_id']}")
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", f"schedule-id:{schedule_id}")
            old = await conn.fetchrow("SELECT * FROM local_cron_schedules WHERE id=$1 FOR UPDATE", schedule_id)
            if old and (old["user_id"] != body["user_id"] or old["target_kind"] != kind
                        or old["workflow_id"] != body.get("workflow_id") or old["node_id"] != body.get("node_id")):
                raise ValueError("Schedule belongs to another target")
            if kind == "coordinator" and not old:
                counts = await conn.fetchrow(
                    "SELECT count(*) FILTER (WHERE enabled) AS pending, "
                    "count(*) FILTER (WHERE created_at>now()-interval '24 hours') AS created "
                    "FROM local_cron_schedules WHERE user_id=$1 AND target_kind='coordinator'", body["user_id"])
                if counts["pending"] >= 10 or counts["created"] >= 24:
                    raise ValueError("Limit: 10 pending coordinator alarms and 24 new alarms per day")
            return dict(await conn.fetchrow(
                """INSERT INTO local_cron_schedules(id,user_id,workflow_id,node_id,cron_expression,webhook_url,payload,
                     timezone,run_once,max_attempts,next_run,target_kind)
                   VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                   ON CONFLICT(id) DO UPDATE SET cron_expression=EXCLUDED.cron_expression,webhook_url=EXCLUDED.webhook_url,
                     payload=EXCLUDED.payload,timezone=EXCLUDED.timezone,run_once=EXCLUDED.run_once,
                     max_attempts=EXCLUDED.max_attempts,next_run=EXCLUDED.next_run,revision=gen_random_uuid(),
                     occurrence_id=NULL,triggered_at=NULL,lease_owner=NULL,lease_until=NULL,attempts=0,updated_at=now()
                   RETURNING *""", schedule_id, body["user_id"], body.get("workflow_id"), body.get("node_id"), cron,
                body["webhook_url"], body.get("payload"), zone, once, max(1, min(int(body.get("max_attempts", 3)), 20)), due, kind))

    async def update(self, schedule_id, body):
        async with self.pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                "SELECT * FROM local_cron_schedules WHERE id = $1::uuid FOR UPDATE", schedule_id,
            )
            if row is None:
                raise ValueError("Schedule not found")
            if body.get("expected_revision") is not None and str(row["revision"]) != body["expected_revision"]:
                raise ValueError("Schedule changed")

            cron_expression = body.get("cron_expression", row["cron_expression"])
            next_run = row["next_run"]
            if "cron_expression" in body:
                next_run = _compute_next_run(cron_expression, row["timezone"], row["last_run"])
            await conn.execute(
                """
                UPDATE local_cron_schedules SET
                    cron_expression = $2, webhook_url = $3, payload = $4,
                    enabled = $5, max_attempts = $6, next_run = $7, revision=gen_random_uuid(),occurrence_id=NULL,triggered_at=NULL,lease_owner=NULL,lease_until=NULL,attempts=0, updated_at = now()
                WHERE id = $1
                """,
                schedule_id, cron_expression,
                body.get("webhook_url", row["webhook_url"]),
                body["payload"] if "payload" in body else row["payload"],
                bool(body.get("enabled", row["enabled"])),
                max(1, min(int(body.get("max_attempts", row["max_attempts"])), 20)),
                next_run,
            )
        return {"success": True, "next_run": next_run.isoformat()}

    async def get(self, schedule_id):
        row = await self.pool.fetchrow("SELECT * FROM local_cron_schedules WHERE id=$1::uuid", schedule_id)
        return dict(row) if row else None

    async def list(self, workflow_id=None, user_id=None, target_kind=None):
        return await self.pool.fetch(
            "SELECT * FROM local_cron_schedules WHERE ($1::text IS NULL OR workflow_id=$1) "
            "AND ($2::text IS NULL OR user_id=$2) AND ($3::text IS NULL OR target_kind=$3) ORDER BY created_at DESC",
            workflow_id, user_id, target_kind)

    async def delete(self, schedule_id):
        # Keep coordinator tombstones so create/cancel cannot bypass the daily cap.
        async with self.pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow("SELECT * FROM local_cron_schedules WHERE id=$1::uuid FOR UPDATE", schedule_id)
            if not row:
                return False
            if row["target_kind"] == "coordinator":
                await conn.execute("UPDATE local_cron_schedules SET enabled=false,last_status='cancelled',"
                                   "revision=gen_random_uuid(),lease_owner=NULL,lease_until=NULL,updated_at=now() WHERE id=$1::uuid", schedule_id)
            else:
                await conn.execute("DELETE FROM local_cron_schedules WHERE id=$1::uuid", schedule_id)
            return True

    async def claim(self, limit):
        async with self.pool.acquire() as conn, conn.transaction():
            return await conn.fetch(
                """WITH due AS (SELECT id FROM local_cron_schedules WHERE enabled AND next_run<=now()
                     AND (lease_until IS NULL OR lease_until<=now()) ORDER BY next_run,id
                     FOR UPDATE SKIP LOCKED LIMIT $1)
                   UPDATE local_cron_schedules s SET lease_owner=gen_random_uuid(),lease_until=now()+interval '2 minutes',
                     occurrence_id=COALESCE(occurrence_id,gen_random_uuid()),triggered_at=COALESCE(triggered_at,now()),
                   attempts=attempts+1 FROM due WHERE s.id=due.id RETURNING s.*""", limit)

    async def heartbeat(self, row):
        return await self.pool.fetchval(
            "UPDATE local_cron_schedules SET lease_until=now()+interval '2 minutes' "
            "WHERE id=$1 AND revision=$2 AND lease_owner=$3 AND lease_until>now() RETURNING id",
            row["id"], row["revision"], row["lease_owner"],
        ) is not None

    async def finish(self, row, *, success, error=None, retry_after=None):
        now = datetime.now(timezone.utc)
        retry = not success and retry_after is not None
        # Recurring failures stay inspectable; the next occurrence is still independent.
        enabled = retry or not row["run_once"]
        due = (now + timedelta(seconds=retry_after)) if retry else (
            now if row["run_once"] else _compute_next_run(row["cron_expression"], row["timezone"], row["triggered_at"]))
        async with self.pool.acquire() as conn, conn.transaction():
            won = await conn.fetchval(
                """UPDATE local_cron_schedules SET enabled=$4,next_run=$5,last_error=$6,last_status=$7,
                     occurrence_id=CASE WHEN $8 THEN occurrence_id ELSE NULL END,
                     triggered_at=CASE WHEN $8 THEN triggered_at ELSE NULL END,
                     attempts=CASE WHEN $8 THEN attempts ELSE 0 END,lease_owner=NULL,lease_until=NULL,
                     last_run=CASE WHEN $8 THEN last_run ELSE $9 END,updated_at=now()
                   WHERE id=$1 AND revision=$2 AND lease_owner=$3 AND lease_until>now() RETURNING id""",
                row["id"], row["revision"], row["lease_owner"], enabled, due, error,
                "retrying" if retry else ("success" if success else "failed"), retry, row["triggered_at"])
            if won and row["run_once"] and success and row["target_kind"] != "coordinator":
                await conn.execute("DELETE FROM local_cron_schedules WHERE id=$1 AND revision=$2", row["id"], row["revision"])

    async def prune(self):
        await self.pool.execute(
            "WITH expired AS (SELECT id FROM local_cron_schedules WHERE NOT enabled "
            "AND (last_status='cancelled' OR (run_once AND last_status IN ('success','failed'))) "
            "AND updated_at<now()-interval '30 days' ORDER BY updated_at LIMIT 1000 FOR UPDATE SKIP LOCKED) "
            "DELETE FROM local_cron_schedules USING expired WHERE local_cron_schedules.id=expired.id"
        )
