"""Coordinator adapter to the shared scheduler. It owns all timer CRUD/state.

Postgres receives an inbox event only when a schedule actually fires.
"""
import uuid

from utils import cron_scheduler_client as scheduler
from utils.coordinator_alarm import alarm_time, MAX_DAILY, MIN_GAP_SECONDS


def checked(result):
    if isinstance(result, dict) and (result.get("error") or result.get("skipped")):
        raise ValueError(result.get("error") or "Scheduler is not configured")
    return result


def alarm_view(row):
    payload = row.get("payload") or {}
    return {"schedule_id": row["id"], "message": payload.get("message", ""),
            "alarm_type": payload.get("alarm_type"), "schedule": payload.get("schedule"),
            "timezone": row.get("timezone", "UTC"), "next_run": row.get("next_run") or row.get("next_run_at"),
            "status": "scheduled" if row.get("enabled") else row.get("last_status") or "disabled",
            "send_to_phone": payload.get("send_to_phone", False), "delivery_error": row.get("last_error")}


class CoordinatorAlarmRepo:
    def __init__(self, pool):
        self.pool = pool

    async def _owned(self, user_id, schedule_id):
        row = checked(await scheduler.get_schedule(schedule_id))
        if row.get("user_id") != str(user_id) or row.get("target_kind") != "coordinator":
            raise ValueError("No alarm with that ID belongs to this account")
        return row

    async def schedule(self, user_id, *, alarm_type, delay_or_time, message, context,
                       timezone_name="UTC", send_to_phone=False, schedule_id=None):
        from utils.coordinator_dispatch import callback_url
        if not isinstance(message, str) or not 1 <= len(message.strip()) <= 2000:
            raise ValueError("Alarm messages must contain 1–2,000 characters")
        due = alarm_time(alarm_type, delay_or_time, timezone_name)
        payload = {"message": message.strip(), "alarm_type": alarm_type, "schedule": delay_or_time,
                   "timezone": timezone_name, "context": context, "send_to_phone": send_to_phone,
                   "version": str(uuid.uuid4())}
        result = checked(await scheduler.create_schedule(
            user_id=str(user_id), workflow_id=None, node_id=None, target_kind="coordinator",
            schedule_id=schedule_id or str(uuid.uuid4()), webhook_url=await callback_url(), payload=payload,
            cron_expression=delay_or_time if alarm_type == "cron" else "__run_at__",
            run_at=None if alarm_type == "cron" else due.isoformat(), timezone=timezone_name,
        ))
        return {"success": True, "schedule_id": result["id"], "next_run": result.get("next_run"),
                "message": message.strip(), "limits":
                f"At most {MAX_DAILY} alarm turns per 24 hours, at least {MIN_GAP_SECONDS//60} minutes apart. "
                "Busy or rate-limited alarms are delayed; missed recurring occurrences are not replayed."}

    async def list(self, user_id):
        rows = checked(await scheduler.list_schedules(user_id=str(user_id), target_kind="coordinator"))
        outcomes = await self.pool.fetch(
            "SELECT DISTINCT ON(alarm_id) alarm_id,response,delivery_error FROM coordinator_wakeups "
            "WHERE user_id=$1::uuid AND source='alarm' ORDER BY alarm_id,created_at DESC", user_id)
        latest = {str(row["alarm_id"]): row for row in outcomes}
        result = []
        for row in rows:
            view = alarm_view(row)
            outcome = latest.get(row["id"])
            if outcome:
                view["response"] = outcome["response"]
                view["delivery_error"] = outcome["delivery_error"] or view["delivery_error"]
            result.append(view)
        return result

    async def cancel(self, user_id, schedule_id):
        await self._owned(user_id, schedule_id)
        checked(await scheduler.delete_schedule(schedule_id))
        # Also fence an already-delivered occurrence, before any further tool effects.
        await self.pool.execute(
            "UPDATE coordinator_wakeups SET status='skipped',lease_until=NULL WHERE user_id=$1::uuid "
            "AND alarm_id=$2::uuid AND status NOT IN ('done','skipped')", user_id, schedule_id)
        return {"success": True, "schedule_id": schedule_id, "status": "cancelled"}

    async def update(self, user_id, schedule_id, *, alarm_type, delay_or_time, message, context, timezone_name="UTC"):
        old = await self._owned(user_id, schedule_id)
        if not old.get("enabled"):
            raise ValueError("This alarm is no longer pending")
        result = await self.schedule(user_id, alarm_type=alarm_type, delay_or_time=delay_or_time, message=message,
                                    context=context, timezone_name=timezone_name, schedule_id=schedule_id,
                                    send_to_phone=(old.get("payload") or {}).get("send_to_phone", False))
        await self.pool.execute(
            "UPDATE coordinator_wakeups SET status='skipped',lease_until=NULL WHERE user_id=$1::uuid "
            "AND alarm_id=$2::uuid AND COALESCE(payload->>'version','')=$3 AND status NOT IN ('done','skipped')",
            user_id, schedule_id, (old.get("payload") or {}).get("version", ""))
        return result
