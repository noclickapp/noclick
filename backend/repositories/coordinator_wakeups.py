"""Durable completion inbox and reply outbox for the account coordinator.

These rows deliver results, not pre-planned actions. Only the resumed coordinator
decides what to do next. A started turn is never blindly replayed after a crash.
"""

import asyncio
import uuid

from repositories.conversation import ConversationRepo
from repositories.coordinator_jobs import TERMINAL


from repositories.coordinator_lease import coordinator_lock  # shared by all transports


class CoordinatorWakeupRepo:
    def __init__(self, pool):
        self.pool = pool

    async def epoch(self, user_id):
        return await self.pool.fetchval(
            "SELECT metadata->>'coordinator_epoch' FROM conversations "
            "WHERE conversation_id=$1 AND user_id=$2::uuid", f"coordinator:{user_id}", user_id,
        ) or ""

    async def reset(self, user_id):
        # Caller holds coordinator_lock, so a reset cannot split a model turn.
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """UPDATE conversations SET events='[]'::jsonb,
                       metadata=(COALESCE(metadata,'{}'::jsonb)-'sdk_history'-'coordinator_context') ||
                         jsonb_build_object('coordinator_epoch', $3::text),
                       pending_ask=NULL, title=NULL, preview=NULL, last_activity=now()
                       WHERE conversation_id=$1 AND user_id=$2::uuid RETURNING conversation_id""",
                    f"coordinator:{user_id}", user_id, str(uuid.uuid4()),
                )
                await conn.execute(
                    "UPDATE coordinator_wakeups SET status='skipped', lease_until=NULL "
                    "WHERE user_id=$1::uuid AND status NOT IN ('done','skipped')", user_id,
                )
        return row is not None

    async def enqueue(self, *, job, context, payload):
        """Transfer a finished job's outcome to the inbox atomically and idempotently."""
        await self._transfer(
            "job", job, context, payload, job["send_to_phone"],
            f"SELECT id FROM coordinator_jobs WHERE id=$1 AND notified_at IS NULL AND status IN {TERMINAL} FOR UPDATE",
        )

    async def enqueue_signal(self, *, signal, context, payload, conn=None):
        """A signal from elsewhere in the account (coder/coordinator/signals.py)."""
        return await self._transfer(
            "signal", signal, context, payload, False,
            "SELECT id FROM coordinator_signals WHERE id=$1 AND notified_at IS NULL FOR UPDATE",
            conn=conn,
        )

    async def _transfer(self, source, item, context, payload, send_to_phone, still_pending_sql, *, conn=None):
        async def insert(connection):
            if not await connection.fetchval(still_pending_sql, item["id"]):
                return
            await connection.execute(
                """INSERT INTO coordinator_wakeups(user_id,source,source_id,context,payload,send_to_phone)
                   VALUES ($1,$2,$3,$4,$5,$6) ON CONFLICT (source,source_id) DO NOTHING""",
                item["user_id"], source, item["id"], context, payload, send_to_phone,
            )
            row = await connection.fetchrow("SELECT * FROM coordinator_wakeups WHERE source=$1 AND source_id=$2",
                                            source, item["id"])
            return dict(row) if row else None

        if conn is not None:
            # The caller owns the source transaction and dispatches after commit.
            return await insert(conn)
        async with self.pool.acquire() as connection, connection.transaction():
            row = await insert(connection)
        if row:
            from utils.coordinator_dispatch import dispatch_event
            await dispatch_event(self.pool, row)
        return row

    async def accept_alarm(self, body):
        payload = {**body["payload"], "scheduler_revision": body["revision"]}
        async with self.pool.acquire() as conn, conn.transaction():
            # Coalesce a delayed recurring schedule: one outstanding occurrence per series.
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", "alarm:" + body["schedule_id"])
            row = await conn.fetchrow(
                "SELECT * FROM coordinator_wakeups WHERE alarm_id=$1::uuid "
                "AND status IN ('queued','running','ready','delivering') ORDER BY created_at LIMIT 1", body["schedule_id"])
            if row:
                return dict(row)
            row = await conn.fetchrow(
                """INSERT INTO coordinator_wakeups(user_id,source,source_id,alarm_id,context,payload,send_to_phone,dispatch_after)
                   VALUES($1::uuid,'alarm',$2::uuid,$3::uuid,$4,$5,$6,now()+interval '15 minutes')
                   ON CONFLICT(source,source_id) DO UPDATE SET source_id=EXCLUDED.source_id RETURNING *""",
                body["user_id"], body["delivery_id"], body["schedule_id"], payload["context"], payload,
                payload.get("send_to_phone", False))
            return dict(row)

    async def by_source(self, source, source_id):
        row = await self.pool.fetchrow(
            "SELECT * FROM coordinator_wakeups WHERE source=$1 AND source_id=$2::uuid", source, source_id,
        )
        return dict(row) if row else None

    async def get(self, event_id):
        row = await self.pool.fetchrow("SELECT * FROM coordinator_wakeups WHERE id=$1::uuid", event_id)
        return dict(row) if row else None

    async def alarm_stopped(self, schedule_id, revision):
        return await self.pool.fetchval(
            "SELECT EXISTS(SELECT 1 FROM coordinator_wakeups WHERE alarm_id=$1::uuid "
            "AND payload->>'scheduler_revision'=$2 AND payload->>'stop_schedule'='true')",
            schedule_id, revision,
        )

    async def discard(self, event):
        await self.pool.execute(
            "UPDATE coordinator_wakeups SET status='skipped',lease_until=NULL "
            "WHERE id=$1 AND status NOT IN ('done','skipped')", event["id"],
        )

    async def retry_delay(self, event):
        if event["source"] != "alarm":
            return 30
        row = await self.pool.fetchrow(
            """SELECT count(*) AS n,min(admitted_at) AS first,max(admitted_at) AS latest,
                 max(admitted_at) FILTER(WHERE alarm_id=$2) AS series
               FROM coordinator_wakeups WHERE user_id=$1 AND source='alarm' AND id<>$3
                 AND admitted_at>now()-interval '24 hours'""", event["user_id"], event["alarm_id"], event["id"])
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        deadlines = [now + timedelta(seconds=30)]
        if row["latest"]:
            deadlines.append(row["latest"] + timedelta(minutes=5))
        if row["series"]:
            deadlines.append(row["series"] + timedelta(minutes=15))
        if row["n"] >= 24:
            deadlines.append(row["first"] + timedelta(days=1))
        return max(30, int((max(deadlines) - now).total_seconds()) + 1)

    async def defer(self, event):
        await self.pool.execute("UPDATE coordinator_wakeups SET status='queued',lease_until=NULL,admitted_at=NULL "
                                "WHERE id=$1 AND attempt_id=$2 AND started_at IS NULL", event["id"], event["attempt_id"])

    async def reconciliation_batch(self, limit=100):
        # Only a recovery dispatcher polls this index, never every API container.
        return await self.pool.fetch(
            """WITH due AS (SELECT id FROM coordinator_wakeups WHERE status IN ('queued','running','ready','delivering')
                 AND dispatch_after<=now() ORDER BY dispatch_after,id FOR UPDATE SKIP LOCKED LIMIT $1)
               UPDATE coordinator_wakeups w SET dispatch_after=now()+interval '2 minutes'
               FROM due WHERE w.id=due.id RETURNING w.*""", limit)

    async def dispatched(self, event_id):
        await self.pool.execute("UPDATE coordinator_wakeups SET dispatch_after=now()+interval '15 minutes' WHERE id=$1", event_id)

    async def claim(self, event_id=None):
        from utils.coordinator_alarm import MAX_DAILY, MIN_GAP_SECONDS

        async with self.pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                """SELECT w.* FROM coordinator_wakeups w WHERE w.status='queued' AND w.not_before<=now() AND ($3::uuid IS NULL OR w.id=$3::uuid)
                   AND (w.payload->>'parent_operation_id' IS NULL OR EXISTS (
                     SELECT 1 FROM coordinator_wakeups parent WHERE parent.id=(w.payload->>'parent_operation_id')::uuid
                       AND parent.user_id=w.user_id AND parent.status='done'))
                   AND NOT EXISTS (SELECT 1 FROM coordinator_wakeups busy WHERE busy.user_id=w.user_id
                                   AND busy.status IN ('running','ready','delivering'))
                   AND (w.source<>'alarm' OR (
                     NOT EXISTS (SELECT 1 FROM coordinator_wakeups a WHERE a.user_id=w.user_id AND a.source='alarm'
                                 AND a.id<>w.id AND (a.admitted_at>now()-$1*interval '1 second'
                                   OR (a.alarm_id=w.alarm_id AND a.admitted_at>now()-interval '15 minutes')))
                     AND (SELECT count(*) FROM coordinator_wakeups a WHERE a.user_id=w.user_id AND a.source='alarm'
                          AND a.id<>w.id AND a.admitted_at>now()-interval '24 hours')<$2))
                   ORDER BY CASE WHEN w.source='alarm' THEN 1 ELSE 0 END,w.not_before,w.created_at,w.id
                   FOR UPDATE OF w SKIP LOCKED LIMIT 1""", MIN_GAP_SECONDS, MAX_DAILY, event_id,
            )
            if row is None:
                return None
            # Row locks alone do not serialize *different* events for one
            # account. Reserve the account across competing worker containers.
            if not await conn.fetchval("SELECT pg_try_advisory_xact_lock(hashtextextended($1,0))",
                                       f"coordinator-claim:{row['user_id']}"):
                return None
            if await conn.fetchval("SELECT EXISTS(SELECT 1 FROM coordinator_wakeups WHERE user_id=$1 "
                                   "AND status IN ('running','ready','delivering'))", row["user_id"]):
                return None
            if row["source"] == "alarm":
                # Recheck under the account admission lock: another selected
                # event might have finished between our initial read and lock.
                blocked = await conn.fetchval(
                    """SELECT count(*) >= $3 OR COALESCE(bool_or(
                         admitted_at>now()-$4*interval '1 second' OR
                         (alarm_id=$5 AND admitted_at>now()-interval '15 minutes')),false)
                       FROM coordinator_wakeups WHERE user_id=$1 AND source='alarm' AND id<>$2
                       AND admitted_at>now()-interval '24 hours'""",
                    row["user_id"], row["id"], MAX_DAILY, MIN_GAP_SECONDS, row["alarm_id"],
                )
                if blocked:
                    return None
            row = await conn.fetchrow(
                """UPDATE coordinator_wakeups SET status='running', attempt_id=$2,
                   admitted_at=COALESCE(admitted_at,now()),lease_until=now()+interval '2 minutes'
                   WHERE id=$1 RETURNING *""", row["id"], uuid.uuid4(),
            )
        return dict(row) if row else None

    async def start(self, event):
        return await self.pool.fetchval(
            """UPDATE coordinator_wakeups SET started_at=now(),
               admitted_at=CASE WHEN source='alarm' THEN now() ELSE admitted_at END WHERE id=$1 AND attempt_id=$2
               AND status='running' AND started_at IS NULL AND lease_until>now() RETURNING id""", event["id"], event["attempt_id"],
        ) is not None

    async def heartbeat(self, event):
        return await self.pool.fetchval(
            """UPDATE coordinator_wakeups SET lease_until=now()+interval '2 minutes'
               WHERE id=$1 AND attempt_id=$2 AND status='running' AND lease_until>now() RETURNING id""",
            event["id"], event["attempt_id"],
        ) is not None

    async def finish(self, event, text, *, skipped=False, reschedule=True, delivery=None):
        # An intentional silent completion is terminal, not an empty outbox
        # message. Acknowledge its source too, so reconciliation cannot requeue it.
        silent = delivery is not None and not text
        payload = {"delivery": delivery} if delivery is not None else {}
        if not reschedule:
            payload["stop_schedule"] = True
        async with self.pool.acquire() as conn, conn.transaction():
            won = await conn.fetchrow(
                """UPDATE coordinator_wakeups SET status=$3,response=$4,lease_until=NULL,payload=payload || $5::jsonb
                   WHERE id=$1 AND attempt_id=$2 AND status='running' AND lease_until>now() RETURNING *""",
                event["id"], event["attempt_id"], "skipped" if skipped else "done" if silent else "ready", text, payload)
            if won and silent and not skipped:
                await self._record_source_delivery(won, None, None, conn=conn)
        if won and event["source"] == "alarm" and not reschedule:
            await self._stop_alarm(event)

    async def _stop_alarm(self, event):
        # A failed old occurrence cannot disable an alarm the user has edited.
        from utils.cron_scheduler_client import update_schedule
        revision = event["payload"].get("scheduler_revision")
        if revision:
            await update_schedule(str(event["alarm_id"]), enabled=False, expected_revision=revision)

    async def reap_stalled(self):
        expired = await self.pool.fetch(
            """WITH expired AS (SELECT id FROM coordinator_wakeups WHERE status='running' AND lease_until<now()
                 ORDER BY lease_until LIMIT 100 FOR UPDATE SKIP LOCKED)
               UPDATE coordinator_wakeups w SET
                 status=CASE WHEN started_at IS NULL THEN 'queued' ELSE 'ready' END,
                 payload=CASE WHEN started_at IS NOT NULL THEN payload || '{"stop_schedule":true}'::jsonb ELSE payload END,
                 response=CASE WHEN started_at IS NOT NULL THEN
                   'An action finished, but my follow-up was interrupted. Check job_status before retrying any action.' END,
                 lease_until=NULL
               FROM expired WHERE w.id=expired.id RETURNING w.*""",
        )
        semaphore = asyncio.Semaphore(10)

        async def stop(row):
            async with semaphore:
                await self._stop_alarm(row)
        await asyncio.gather(*(stop(row) for row in expired if row["source"] == "alarm" and row["started_at"] is not None))
        # A send may already have reached the phone. Preserve the reply in chat,
        # report uncertainty, and never blindly send it a second time.
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                rows = await conn.fetch(
                    "WITH expired AS (SELECT id FROM coordinator_wakeups WHERE status='delivering' AND lease_until<now() "
                    "ORDER BY lease_until LIMIT 100 FOR UPDATE SKIP LOCKED) "
                    "UPDATE coordinator_wakeups w SET status='done', lease_until=NULL, delivery_error=$1 "
                    "FROM expired WHERE w.id=expired.id RETURNING w.*",
                    "Follow-up delivery was interrupted; receipt could not be confirmed. The reply is saved in chat.",
                )
                for row in rows:
                    await self._record_source_delivery(row, "uncertain" if row["send_to_phone"] else None,
                                                       row["delivery_error"], conn=conn)

    async def prune(self):
        await self.pool.execute("DELETE FROM coordinator_wakeups WHERE id IN (SELECT id FROM coordinator_wakeups "
                                "WHERE status IN ('done','skipped') AND created_at<now()-interval '30 days' LIMIT 1000)")

    async def claim_delivery(self, event_id=None):
        from utils.task_notifications import notification_event

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """WITH next AS (SELECT id FROM coordinator_wakeups WHERE status='ready' AND ($2::uuid IS NULL OR id=$2::uuid)
                         ORDER BY created_at,id FOR UPDATE SKIP LOCKED LIMIT 1)
                       UPDATE coordinator_wakeups w SET status='delivering', attempt_id=$1,
                         lease_until=now()+interval '2 minutes' FROM next WHERE w.id=next.id RETURNING w.*""",
                    uuid.uuid4(), event_id,
                )
                if row is None:
                    return None
                event = notification_event(row["response"], f"coordinator-wakeup:{row['id']}",
                                           coordinator_wakeup_id=str(row["id"]))
                await conn.execute(
                    ConversationRepo._UPSERT_CHAT_EVENT_SQL,
                    f"coordinator:{row['user_id']}", row["user_id"], None, "__coordinator__", [event], "Coordinator", None,
                )
        return {**dict(row), "notification": event}

    async def _record_source_delivery(self, row, phone_state, error, *, conn=None):
        if row["source"] == "job":
            await (conn or self.pool).execute(
                "UPDATE coordinator_jobs SET notified_at=now(), notification_lease_until=NULL, "
                "phone_state=$2, delivery_error=$3 WHERE id=$1", row["source_id"], phone_state, error,
            )
        elif row["source"] == "signal":
            await (conn or self.pool).execute("UPDATE coordinator_signals SET notified_at=now() WHERE id=$1",
                                              row["source_id"])

    async def delivered(self, row, phone_state, error):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                won = await conn.fetchval(
                    """UPDATE coordinator_wakeups SET status='done', lease_until=NULL, delivery_error=$3
                       WHERE id=$1 AND attempt_id=$2 AND status='delivering' RETURNING id""",
                    row["id"], row["attempt_id"], error,
                )
                if won:
                    await self._record_source_delivery(row, phone_state, error, conn=conn)
