"""Account alarms in the coordinator inbox; no parallel scheduling lifecycle."""

import uuid

from utils.coordinator_alarm import MAX_DAILY, MAX_PENDING, MIN_GAP_SECONDS, alarm_time, next_cron


def alarm_view(row):
    return {"schedule_id": str(row["alarm_id"]), "message": row["payload"]["message"],
            "alarm_type": row["payload"]["alarm_type"], "schedule": row["payload"]["schedule"],
            "timezone": row["payload"]["timezone"], "next_run": row["not_before"].isoformat(),
            "status": row["status"], "send_to_phone": row["send_to_phone"],
            "response": row["response"], "delivery_error": row["delivery_error"]}


class CoordinatorAlarmRepo:
    def __init__(self, pool):
        self.pool = pool

    async def lock(self, conn, user_id):
        await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", f"coordinator-alarm:{user_id}")

    async def schedule(self, user_id, *, alarm_type, delay_or_time, message, context, timezone_name="UTC", send_to_phone=False):
        if not isinstance(message, str) or not 1 <= len(message.strip()) <= 2000:
            raise ValueError("Alarm messages must contain 1–2,000 characters.")
        due = alarm_time(alarm_type, delay_or_time, timezone_name)
        async with self.pool.acquire() as conn, conn.transaction():
            await self.lock(conn, user_id)
            pending = await conn.fetchval(
                "SELECT count(DISTINCT alarm_id) FROM coordinator_wakeups WHERE user_id=$1::uuid AND source='alarm' "
                "AND status IN ('queued','running','ready','delivering')", user_id,
            )
            if pending >= MAX_PENDING:
                raise ValueError(f"You already have {MAX_PENDING} pending coordinator alarms. Cancel one first.")
            created = await conn.fetchval(
                "SELECT count(DISTINCT alarm_id) FROM coordinator_wakeups WHERE user_id=$1::uuid AND source='alarm' "
                "AND id=alarm_id AND created_at>now()-interval '24 hours'", user_id,
            )
            if created >= MAX_DAILY:
                raise ValueError(f"Only {MAX_DAILY} new coordinator alarms may be created in 24 hours.")
            alarm_id = uuid.uuid4()
            payload = {"message": message.strip(), "alarm_type": alarm_type, "schedule": delay_or_time,
                       "timezone": timezone_name}
            row = await conn.fetchrow(
                """INSERT INTO coordinator_wakeups(id,user_id,source,source_id,alarm_id,context,payload,send_to_phone,not_before)
                   VALUES ($1,$2::uuid,'alarm',$1,$1,$3,$4,$5,$6) RETURNING *""",
                alarm_id, user_id, context, payload, send_to_phone, due,
            )
        return {"success": True, **alarm_view(row), "limits":
                f"At most {MAX_DAILY} alarm turns per 24 hours, at least {MIN_GAP_SECONDS//60} minutes apart. "
                "Busy or rate-limited alarms are delayed; missed recurring occurrences are not replayed."}

    async def list(self, user_id):
        rows = await self.pool.fetch(
            """SELECT * FROM (SELECT DISTINCT ON (alarm_id) * FROM coordinator_wakeups
               WHERE user_id=$1::uuid AND source='alarm' ORDER BY alarm_id,created_at DESC,id DESC) latest
               ORDER BY CASE WHEN status IN ('queued','running','ready','delivering') THEN 0 ELSE 1 END,
               not_before LIMIT 50""", user_id,
        )
        return [alarm_view(row) for row in rows]

    async def cancel(self, user_id, schedule_id):
        async with self.pool.acquire() as conn, conn.transaction():
            await self.lock(conn, user_id)
            rows = await conn.fetch(
                "UPDATE coordinator_wakeups SET status='skipped',lease_until=NULL WHERE user_id=$1::uuid "
                "AND alarm_id=$2::uuid AND status NOT IN ('done','skipped') RETURNING id", user_id, schedule_id,
            )
        if not rows:
            raise ValueError("No pending alarm with that ID belongs to this account.")
        return {"success": True, "schedule_id": schedule_id, "status": "cancelled"}

    async def update(self, user_id, schedule_id, *, alarm_type, delay_or_time, message, context, timezone_name="UTC"):
        if not isinstance(message, str) or not 1 <= len(message.strip()) <= 2000:
            raise ValueError("Alarm messages must contain 1–2,000 characters.")
        due = alarm_time(alarm_type, delay_or_time, timezone_name)
        async with self.pool.acquire() as conn, conn.transaction():
            await self.lock(conn, user_id)
            row = await conn.fetchrow(
                """UPDATE coordinator_wakeups SET not_before=$3,payload=$4,context=$5
                   WHERE user_id=$1::uuid AND alarm_id=$2::uuid AND status='queued' RETURNING *""",
                user_id, schedule_id, due,
                {"message": message.strip(), "alarm_type": alarm_type, "schedule": delay_or_time, "timezone": timezone_name}, context,
            )
        if row is None:
            raise ValueError("This alarm has already started or is no longer pending. List alarms before changing it.")
        return {"success": True, **alarm_view(row)}

    async def repeat(self, conn, row):
        """Called in the terminal transition transaction, at most once. No catch-up burst."""
        if row["source"] != "alarm" or row["payload"]["alarm_type"] != "cron":
            return
        due = next_cron(row["payload"]["schedule"], row["payload"]["timezone"])
        await conn.execute(
            """INSERT INTO coordinator_wakeups(user_id,source,source_id,alarm_id,context,payload,send_to_phone,not_before)
               VALUES ($1,'alarm',$2,$3,$4,$5,$6,$7)""",
            row["user_id"], uuid.uuid4(), row["alarm_id"], row["context"], row["payload"], row["send_to_phone"], due,
        )
