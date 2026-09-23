"""Shared scheduler → signed callback → durable coordinator turn, with real PostgreSQL."""
import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import httpx
import pytest

from repositories.coordinator_alarms import CoordinatorAlarmRepo
from repositories.coordinator_wakeups import CoordinatorWakeupRepo
from repositories.local_schedules import LocalScheduleRepo
from tests.fixtures.local_scheduler import local_scheduler  # noqa: F401
from tests.test_builder_requests import USER, builder_request_db  # noqa: F401
from utils.coordinator_alarm import alarm_time
from utils.scheduler_delivery import delivery_headers

pytestmark = pytest.mark.asyncio
CONTEXT = {"epoch": "", "depth": 0, "request": "Remind me to check the report", "channel": "web", "turn_id": "user-turn"}


@pytest.fixture
async def alarm_db(local_scheduler):
    app, pool = local_scheduler
    try:
        yield app, pool, CoordinatorAlarmRepo(pool), CoordinatorWakeupRepo(pool)
    finally:
        await pool.execute("DELETE FROM coordinator_wakeups WHERE user_id=$1::uuid", USER)


async def schedule(repo, **overrides):
    return await repo.schedule(USER, **{**dict(alarm_type="countdown", delay_or_time="10m", message="Check the report", context=CONTEXT), **overrides})


async def fire(pool, schedule_id):
    await pool.execute("UPDATE local_cron_schedules SET next_run=now()-interval '1 minute' WHERE id=$1::uuid", schedule_id)
    row = dict((await LocalScheduleRepo(pool).claim(1))[0])
    return row, {"schedule_id": str(row["id"]), "delivery_id": str(row["occurrence_id"]),
                 "user_id": row["user_id"], "revision": str(row["revision"]), "target_kind": row["target_kind"],
                 "triggered_at": row["triggered_at"].isoformat(), "payload": row["payload"]}


async def post(app, body, *, signature=True):
    raw = json.dumps(body).encode()
    headers = delivery_headers(raw, "test-scheduler-secret") if signature else {}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://scheduler.test") as client:
        return await client.post("/internal/scheduler/coordinator", content=raw, headers=headers)


async def test_timing_is_owned_by_shared_scheduler_not_inbox(alarm_db):
    _, pool, alarms, inbox = alarm_db
    result = await schedule(alarms)
    assert await pool.fetchval("SELECT count(*) FROM coordinator_wakeups") == 0
    assert await inbox.claim() is None
    row = await LocalScheduleRepo(pool).get(result["schedule_id"])
    assert row["target_kind"] == "coordinator" and row["workflow_id"] is None and row["node_id"] is None
    assert (await alarms.list(USER))[0]["message"] == "Check the report"
    assert await alarms.list(str(uuid.uuid4())) == []
    with pytest.raises(ValueError, match="belongs"):
        await alarms.cancel(str(uuid.uuid4()), result["schedule_id"])


async def test_failed_old_occurrence_cannot_disable_an_edited_alarm(alarm_db):
    _, pool, alarms, inbox = alarm_db
    alarm = await schedule(alarms)
    _, body = await fire(pool, alarm["schedule_id"])
    await inbox.accept_alarm(body)
    event = await inbox.claim()
    # The scheduler edit can commit before invalidation reaches the inbox.
    await LocalScheduleRepo(pool).update(alarm["schedule_id"], {"payload": {"message": "edited"}})
    await inbox.finish(event, "Failed", reschedule=False)
    assert (await LocalScheduleRepo(pool).get(alarm["schedule_id"]))["enabled"]


async def test_recovery_cannot_run_an_alarm_cancelled_before_inbox_invalidation(alarm_db, monkeypatch):
    app, pool, alarms, inbox = alarm_db
    alarm = await schedule(alarms)
    _, body = await fire(pool, alarm["schedule_id"])
    event = await inbox.accept_alarm(body)
    # Simulate a crash after scheduler cancellation but before the inbox update.
    await LocalScheduleRepo(pool).delete(alarm["schedule_id"])
    process = AsyncMock()
    monkeypatch.setattr("coder.coordinator.wakeups.process_event", process)
    body.update(target_kind="coordinator_wakeup", payload={"event_id": str(event["id"])})
    assert (await post(app, body)).json() == {"skipped": True}
    process.assert_not_called()
    assert (await inbox.get(event["id"]))["status"] == "skipped"


async def test_failed_alarm_stays_stopped_if_scheduler_disable_is_temporarily_unavailable(alarm_db, monkeypatch):
    app, pool, alarms, inbox = alarm_db
    alarm = await schedule(alarms, alarm_type="cron", delay_or_time="*/15 * * * *")
    _, body = await fire(pool, alarm["schedule_id"])
    await inbox.accept_alarm(body)
    event = await inbox.claim()
    with monkeypatch.context() as patch:
        patch.setattr("utils.cron_scheduler_client.update_schedule", AsyncMock(return_value={"error": "outage"}))
        await inbox.finish(event, "Failed", reschedule=False)
    body["delivery_id"] = str(uuid.uuid4())
    assert (await post(app, body)).json() == {"skipped": True}
    assert not (await LocalScheduleRepo(pool).get(alarm["schedule_id"]))["enabled"]


async def test_concurrent_creates_cannot_exceed_pending_limit(alarm_db):
    _, _, alarms, _ = alarm_db
    results = await asyncio.gather(*(schedule(alarms) for _ in range(15)), return_exceptions=True)
    assert len([r for r in results if isinstance(r, dict)]) == 10
    assert all("10 pending" in str(r) for r in results if isinstance(r, Exception))


async def test_cancel_cannot_evade_daily_creation_limit(alarm_db):
    _, _, alarms, _ = alarm_db
    for _ in range(24):
        alarm = await schedule(alarms)
        await alarms.cancel(USER, alarm["schedule_id"])
    with pytest.raises(ValueError, match="24"):
        await schedule(alarms)


async def test_due_events_are_deduplicated_and_account_limits_still_apply(alarm_db):
    _, pool, alarms, inbox = alarm_db
    first, second = await schedule(alarms), await schedule(alarms)
    _, a = await fire(pool, first["schedule_id"])
    _, b = await fire(pool, second["schedule_id"])
    one = await inbox.accept_alarm(a)
    assert (await inbox.accept_alarm(a))["id"] == one["id"]
    two = await inbox.accept_alarm(b)
    event = await inbox.claim(one["id"])
    assert event and await inbox.claim(two["id"]) is None
    await inbox.start(event)
    await inbox.finish(event, "Done")
    delivery = await inbox.claim_delivery(event["id"])
    await inbox.delivered(delivery, None, None)
    assert await inbox.claim(two["id"]) is None
    await pool.execute("UPDATE coordinator_wakeups SET admitted_at=now()-interval '6 minutes' WHERE id=$1", one["id"])
    assert await inbox.claim(two["id"])


async def test_recurring_clock_and_restart_state_belong_to_scheduler(alarm_db):
    _, pool, alarms, inbox = alarm_db
    alarm = await schedule(alarms, alarm_type="cron", delay_or_time="0 * * * *", timezone_name="Asia/Kolkata")
    scheduled, body = await fire(pool, alarm["schedule_id"])
    event = await inbox.accept_alarm(body)
    assert (await inbox.accept_alarm({**body, "delivery_id": str(uuid.uuid4())}))["id"] == event["id"]  # coalesce
    claimed = await inbox.claim(event["id"])
    await inbox.start(claimed)
    await inbox.finish(claimed, "Checked")
    assert await pool.fetchval("SELECT count(*) FROM coordinator_wakeups") == 1  # no second clock
    await LocalScheduleRepo(pool).finish(scheduled, success=True)
    row = await LocalScheduleRepo(pool).get(alarm["schedule_id"])
    assert row["enabled"] and row["next_run"] > datetime.now(timezone.utc)
    await alarms.cancel(USER, alarm["schedule_id"])
    assert not await inbox.heartbeat(claimed)


async def test_signed_delivery_rejects_forgery_and_stale_update(alarm_db, monkeypatch):
    app, pool, alarms, _ = alarm_db
    alarm = await schedule(alarms)
    _, body = await fire(pool, alarm["schedule_id"])
    assert (await post(app, body, signature=False)).status_code == 401
    await alarms.update(USER, alarm["schedule_id"], alarm_type="countdown", delay_or_time="2h", message="Changed", context=CONTEXT)
    assert (await post(app, body)).json() == {"skipped": True}
    assert await pool.fetchval("SELECT count(*) FROM coordinator_wakeups") == 0


async def test_reset_invalidates_remote_schedule_when_it_fires(alarm_db):
    app, pool, alarms, inbox = alarm_db
    alarm = await schedule(alarms)
    await pool.execute("INSERT INTO conversations(conversation_id,user_id) VALUES($1,$2::uuid)", f"coordinator:{USER}", USER)
    await inbox.reset(USER)
    _, body = await fire(pool, alarm["schedule_id"])
    assert (await post(app, body)).json() == {"skipped": True}
    assert not (await LocalScheduleRepo(pool).get(alarm["schedule_id"]))["enabled"]


@pytest.mark.parametrize("kind,value,zone", [("countdown", "1s", "UTC"), ("datetime", "2027-01-01T09:00:00", "UTC"),
    ("cron", "* * * * *", "UTC"), ("cron", "* * * * * *", "UTC"), ("cron", "0 9 * * *", "invalid/zone")])
async def test_reject_unsafe_or_ambiguous_schedules(kind, value, zone):
    with pytest.raises((ValueError, KeyError)):
        alarm_time(kind, value, zone)


async def test_timezone_aware_timestamp_is_preserved():
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    assert alarm_time("datetime", tomorrow.isoformat()) == tomorrow


async def test_due_message_wakes_same_coordinator_and_delivers_once(alarm_db, monkeypatch):
    from coder.coordinator import agent, wakeups as worker
    from wss.sender.events import ChatMessageEvent
    app, pool, alarms, inbox = alarm_db
    monkeypatch.setattr(agent, "get_native_pool", lambda: pool)
    monkeypatch.setattr(agent, "get_user_org_context", AsyncMock(return_value=None))
    monkeypatch.setattr(agent, "memory_context", AsyncMock(return_value=""))
    monkeypatch.setattr(worker, "get_sio", lambda: None)
    monkeypatch.setattr("utils.feature_gates.require_feature", lambda *args, **kwargs: None)
    monkeypatch.setattr("wss.handlers.coordinator_handler.plan_allows_turn", AsyncMock(return_value=(True, None)))
    captured = []

    class ResumedAgent:
        @classmethod
        async def create(cls, **kwargs):
            self = cls()
            self.kwargs = kwargs
            assert kwargs["conversation_id"] == f"coordinator:{USER}"
            return self

        async def __call__(self, message):
            content = message["input_items"][0]["content"]
            assert content.startswith("A scheduled coordinator message is due.")
            captured.append(content)
            # A five-connection pool remains fully available while a model runs.
            connections = await asyncio.gather(*(pool.acquire() for _ in range(5)))
            for conn in connections:
                await pool.release(conn)
            await self.kwargs["emit_message"](ChatMessageEvent(message="Your report is ready.", finished=True))

        async def cleanup(self):
            pass

    monkeypatch.setattr(agent, "Agent", ResumedAgent)
    phone = AsyncMock(return_value=("sent", None))
    monkeypatch.setattr(worker, "deliver_phone", phone)
    monkeypatch.setattr(worker, "emit_notification", AsyncMock())
    alarm = await schedule(alarms, context={**CONTEXT, "channel": "whatsapp_text"}, send_to_phone=True)
    _, body = await fire(pool, alarm["schedule_id"])
    assert (await post(app, body)).status_code == 200
    assert (await post(app, body)).status_code == 200
    assert len(captured) == 1
    phone.assert_awaited_once()
    assert await pool.fetchval("SELECT status FROM coordinator_wakeups") == "done"
