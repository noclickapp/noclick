"""Durable completion inbox and reply outbox for the account coordinator.

These rows deliver results, not pre-planned actions. Only the resumed coordinator
decides what to do next. A started turn is never blindly replayed after a crash.
"""

import asyncio
import uuid
from contextlib import asynccontextmanager

from repositories.conversation import ConversationRepo


@asynccontextmanager
async def coordinator_lock(pool, user_id):
    """Serialize web, phone, reset and completion turns across all containers.

    Use a transaction lock (safe with PgBouncer), releasing pool slots between
    attempts rather than accumulating blocked connections behind a long turn.
    """
    while True:
        async with pool.acquire() as conn:
            async with conn.transaction():
                if await conn.fetchval("SELECT pg_try_advisory_xact_lock(hashtextextended($1, 0))",
                                       f"coordinator-turn:{user_id}"):
                    yield conn
                    return
        await asyncio.sleep(0.25)


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

    async def enqueue(self, *, source, task, context, payload):
        """Transfer the source outbox to the inbox atomically and idempotently."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                if source == "builder":
                    valid = await conn.fetchval(
                        "SELECT id FROM builder_requests WHERE id=$1 AND notification_token=$2 "
                        "AND notified_at IS NULL FOR UPDATE", task["id"], task["notification_token"],
                    )
                else:
                    valid = await conn.fetchval(
                        "SELECT id FROM coordinator_agent_tasks WHERE id=$1 AND notified_at IS NULL "
                        "AND status IN ('completed','failed') FOR UPDATE", task["id"],
                    )
                if not valid:
                    return
                await conn.execute(
                    """INSERT INTO coordinator_wakeups(user_id,source,source_id,context,payload,send_to_phone)
                       VALUES ($1,$2,$3,$4,$5,$6) ON CONFLICT (source,source_id) DO NOTHING""",
                    task["user_id"], source, task["id"], context, payload,
                    task["send_to_phone"] if source == "builder" else task["channel"] != "web",
                )

    async def claim(self):
        from utils.coordinator_alarm import MAX_DAILY, MIN_GAP_SECONDS

        async with self.pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                """SELECT w.* FROM coordinator_wakeups w WHERE w.status='queued' AND w.not_before<=now()
                   AND NOT EXISTS (SELECT 1 FROM coordinator_wakeups busy WHERE busy.user_id=w.user_id
                                   AND busy.status IN ('running','ready','delivering'))
                   AND (w.source<>'alarm' OR (
                     NOT EXISTS (SELECT 1 FROM coordinator_wakeups a WHERE a.user_id=w.user_id AND a.source='alarm'
                                 AND a.id<>w.id AND (a.admitted_at>now()-$1*interval '1 second'
                                   OR (a.alarm_id=w.alarm_id AND a.admitted_at>now()-interval '15 minutes')))
                     AND (SELECT count(*) FROM coordinator_wakeups a WHERE a.user_id=w.user_id AND a.source='alarm'
                          AND a.id<>w.id AND a.admitted_at>now()-interval '24 hours')<$2))
                   ORDER BY CASE WHEN w.source='alarm' THEN 1 ELSE 0 END,w.not_before,w.created_at,w.id
                   FOR UPDATE OF w SKIP LOCKED LIMIT 1""", MIN_GAP_SECONDS, MAX_DAILY,
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

    async def finish(self, event, text, *, skipped=False, reschedule=True):
        from repositories.coordinator_alarms import CoordinatorAlarmRepo

        async with self.pool.acquire() as conn, conn.transaction():
            alarms = CoordinatorAlarmRepo(self.pool)
            if event["source"] == "alarm":
                await alarms.lock(conn, str(event["user_id"]))
            row = await conn.fetchrow(
                """UPDATE coordinator_wakeups SET status=$3, response=$4, lease_until=NULL
                   WHERE id=$1 AND attempt_id=$2 AND status='running' RETURNING *""",
                event["id"], event["attempt_id"], "skipped" if skipped else "ready", text,
            )
            if row and not skipped and reschedule:
                await alarms.repeat(conn, row)

    async def reap_stalled(self):
        await self.pool.execute(
            """UPDATE coordinator_wakeups SET
                 status=CASE WHEN started_at IS NULL THEN 'queued' ELSE 'ready' END,
                 response=CASE WHEN started_at IS NOT NULL THEN
                   'An action finished, but my follow-up was interrupted. Check build_status or agent_tasks before retrying any action.' END,
                 lease_until=NULL
               WHERE status='running' AND lease_until<now()""",
        )
        # A send may already have reached the phone. Preserve the reply in chat,
        # report uncertainty, and never blindly send it a second time.
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                rows = await conn.fetch(
                    "UPDATE coordinator_wakeups SET status='done', lease_until=NULL, delivery_error=$1 "
                    "WHERE status='delivering' AND lease_until<now() RETURNING *",
                    "Follow-up delivery was interrupted; receipt could not be confirmed. The reply is saved in chat.",
                )
                for row in rows:
                    await self._record_source_delivery(row, "uncertain" if row["send_to_phone"] else None,
                                                       row["delivery_error"], conn=conn)

    async def claim_delivery(self):
        from utils.task_notifications import notification_event

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """WITH next AS (SELECT id FROM coordinator_wakeups WHERE status='ready'
                         ORDER BY created_at,id FOR UPDATE SKIP LOCKED LIMIT 1)
                       UPDATE coordinator_wakeups w SET status='delivering', attempt_id=$1,
                         lease_until=now()+interval '2 minutes' FROM next WHERE w.id=next.id RETURNING w.*""",
                    uuid.uuid4(),
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
        db = conn or self.pool
        if row["source"] == "builder":
            await db.execute(
                "UPDATE builder_requests SET notified_at=now(), notification_lease_until=NULL, "
                "phone_state=$2, delivery_error=$3 WHERE id=$1", row["source_id"], phone_state, error,
            )
        elif row["source"] == "agent":
            await db.execute("UPDATE coordinator_agent_tasks SET notified_at=now(), delivery_error=$2 WHERE id=$1",
                             row["source_id"], error)

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
