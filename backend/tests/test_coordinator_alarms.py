"""Durable timed messages, account isolation and race-safe admission limits."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from repositories.coordinator_alarms import CoordinatorAlarmRepo
from repositories.coordinator_wakeups import CoordinatorWakeupRepo
from tests.test_builder_requests import USER, builder_request_db  # noqa: F401
from utils.coordinator_alarm import alarm_time

pytestmark = pytest.mark.asyncio
CONTEXT = {"epoch": "", "depth": 0, "request": "Remind me to check the report", "channel": "web", "turn_id": "user-turn"}


@pytest.fixture
async def alarm_db(builder_request_db):
    pool = builder_request_db[0]
    try:
        yield pool, CoordinatorAlarmRepo(pool), CoordinatorWakeupRepo(pool)
    finally:
        await pool.execute("DELETE FROM coordinator_wakeups WHERE user_id=$1::uuid", USER)


async def schedule(repo, **overrides):
    return await repo.schedule(USER, **{**dict(alarm_type="countdown", delay_or_time="10m", message="Check the report",
                                             context=CONTEXT), **overrides})


async def due(pool, schedule_id):
    await pool.execute("UPDATE coordinator_wakeups SET not_before=now()-interval '1 minute' WHERE alarm_id=$1::uuid", schedule_id)


async def test_future_alarm_then_one_durable_wakeup_and_cancel_is_scoped(alarm_db):
    pool, alarms, wakeups = alarm_db
    alarm = await schedule(alarms)
    assert await wakeups.claim() is None
    assert (await alarms.list(USER))[0]["message"] == "Check the report"
    assert await alarms.list(str(uuid.uuid4())) == []
    with pytest.raises(ValueError, match="belongs"):
        await alarms.cancel(str(uuid.uuid4()), alarm["schedule_id"])
    await due(pool, alarm["schedule_id"])
    claims = await asyncio.gather(*(CoordinatorWakeupRepo(pool).claim() for _ in range(4)))
    assert len([r for r in claims if r]) == 1
    event = next(r for r in claims if r)
    assert event["source"] == "alarm" and event["payload"]["message"] == "Check the report"
    assert await wakeups.start(event)
    await wakeups.finish(event, "The report is ready.")
    delivery = await wakeups.claim_delivery()
    await wakeups.delivered(delivery, None, None)
    assert await wakeups.claim() is None
    assert (await alarms.list(USER))[0]["response"] == "The report is ready."


async def test_concurrent_creates_cannot_exceed_pending_limit(alarm_db):
    _, alarms, _ = alarm_db
    results = await asyncio.gather(*(schedule(alarms) for _ in range(15)), return_exceptions=True)
    assert len([r for r in results if isinstance(r, dict)]) == 10
    assert all("pending" in str(r) for r in results if isinstance(r, Exception))


async def test_cancel_cannot_evade_daily_creation_limit(alarm_db):
    _, alarms, _ = alarm_db
    for _ in range(24):
        alarm = await schedule(alarms)
        await alarms.cancel(USER, alarm["schedule_id"])
    with pytest.raises(ValueError, match="24"):
        await schedule(alarms)


async def test_simultaneous_alarms_are_spaced_and_only_one_runs_per_account(alarm_db):
    pool, alarms, wakeups = alarm_db
    a, b = await schedule(alarms), await schedule(alarms)
    await due(pool, a["schedule_id"])
    await due(pool, b["schedule_id"])
    first = await wakeups.claim()
    assert await wakeups.claim() is None
    await wakeups.start(first)
    await wakeups.finish(first, "Done")
    delivery = await wakeups.claim_delivery()
    await wakeups.delivered(delivery, None, None)
    assert await wakeups.claim() is None  # within five-minute budget
    await pool.execute("UPDATE coordinator_wakeups SET admitted_at=now()-interval '6 minutes' WHERE id=$1", first["id"])
    assert (await wakeups.claim())["id"] != first["id"]


async def test_daily_admission_budget_delays_without_losing_alarm(alarm_db):
    pool, alarms, wakeups = alarm_db
    for _ in range(24):
        await pool.execute("""INSERT INTO coordinator_wakeups(user_id,source,source_id,alarm_id,context,payload,status,admitted_at)
                            VALUES($1::uuid,'alarm',$2,$2,$3,$4,'done',now()-interval '1 hour')""",
                           USER, uuid.uuid4(), CONTEXT, {"alarm_type": "countdown", "schedule": "1h", "timezone": "UTC", "message": "prior"})
    # These are historical occurrences (not new series creations today).
    alarm = await schedule(alarms)
    await due(pool, alarm["schedule_id"])
    assert await wakeups.claim() is None
    assert any(a["schedule_id"] == alarm["schedule_id"] and a["status"] == "queued" for a in await alarms.list(USER))


async def test_recurring_alarm_coalesces_missed_runs_and_cancel_stops_series(alarm_db):
    pool, alarms, wakeups = alarm_db
    alarm = await schedule(alarms, alarm_type="cron", delay_or_time="0 * * * *", timezone_name="Asia/Kolkata")
    await due(pool, alarm["schedule_id"])
    first = await wakeups.claim()
    await wakeups.start(first)
    await asyncio.gather(wakeups.finish(first, "Checked"), wakeups.finish(first, "Duplicate"))
    rows = await pool.fetch("SELECT * FROM coordinator_wakeups WHERE source='alarm' ORDER BY created_at")
    assert len(rows) == 2 and rows[1]["not_before"] > datetime.now(timezone.utc)
    assert rows[1]["alarm_id"] == rows[0]["alarm_id"]
    await alarms.cancel(USER, alarm["schedule_id"])
    assert await wakeups.claim() is None
    assert not await wakeups.heartbeat(first)


async def test_reset_invalidates_timers_and_started_failure_does_not_repeat(alarm_db):
    pool, alarms, wakeups = alarm_db
    alarm = await schedule(alarms, alarm_type="cron", delay_or_time="0 9 * * *")
    await due(pool, alarm["schedule_id"])
    event = await wakeups.claim()
    await wakeups.start(event)
    await wakeups.finish(event, "No credits available", reschedule=False)
    assert len(await pool.fetch("SELECT id FROM coordinator_wakeups")) == 1
    await schedule(alarms)
    await wakeups.reset(USER)
    assert await wakeups.claim() is None


@pytest.mark.parametrize("kind,value,zone", [("countdown", "1s", "UTC"), ("datetime", "2027-01-01T09:00:00", "UTC"),
                                          ("cron", "* * * * *", "UTC"), ("cron", "* * * * * *", "UTC"),
                                          ("cron", "0 9 * * *", "invalid/zone")])
async def test_reject_unsafe_or_ambiguous_schedules(kind, value, zone):
    with pytest.raises((ValueError, KeyError)):
        alarm_time(kind, value, zone)


async def test_timezone_aware_timestamp_is_preserved():
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    assert alarm_time("datetime", tomorrow.isoformat()) == tomorrow


async def test_update_is_atomic_scoped_and_cannot_change_started_alarm(alarm_db):
    pool, alarms, wakeups = alarm_db
    alarm = await schedule(alarms)
    changed = await alarms.update(USER, alarm["schedule_id"], alarm_type="countdown", delay_or_time="2h",
                                  message="New authorized task", context={**CONTEXT, "request": "Changed request"})
    assert changed["schedule_id"] == alarm["schedule_id"] and changed["message"] == "New authorized task"
    with pytest.raises(ValueError):
        await alarms.update(USER, alarm["schedule_id"], alarm_type="countdown", delay_or_time="1s", message="invalid", context=CONTEXT)
    assert (await alarms.list(USER))[0]["message"] == "New authorized task"
    with pytest.raises(ValueError):
        await alarms.update(str(uuid.uuid4()), alarm["schedule_id"], alarm_type="countdown", delay_or_time="2h", message="foreign", context=CONTEXT)
    await due(pool, alarm["schedule_id"])
    event = await wakeups.claim()
    await wakeups.start(event)
    with pytest.raises(ValueError, match="already started"):
        await alarms.update(USER, alarm["schedule_id"], alarm_type="countdown", delay_or_time="2h", message="too late", context=CONTEXT)


async def test_due_message_wakes_same_coordinator_and_delivers_to_original_channel(alarm_db, monkeypatch):
    from unittest.mock import AsyncMock
    from coder.coordinator import agent, wakeups as worker
    from wss.sender.events import ChatMessageEvent

    pool, alarms, inbox = alarm_db
    monkeypatch.setattr(agent, "get_native_pool", lambda: pool)
    monkeypatch.setattr(agent, "get_user_org_context", AsyncMock(return_value=None))
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
            assert "Check the report" in content and "untrusted reference data" in content
            captured.append(content)
            await self.kwargs["emit_message"](ChatMessageEvent(message="Your report is ready.", finished=True))

        async def cleanup(self):
            pass

    monkeypatch.setattr(agent, "Agent", ResumedAgent)
    phone = AsyncMock(return_value=("sent", None))
    monkeypatch.setattr(worker, "deliver_phone", phone)
    monkeypatch.setattr(worker, "emit_notification", AsyncMock())
    alarm = await schedule(alarms, context={**CONTEXT, "channel": "whatsapp_text"}, send_to_phone=True)
    await due(pool, alarm["schedule_id"])
    await worker.run_wakeup(pool, await inbox.claim())
    await worker.deliver_reply(pool, await inbox.claim_delivery())
    assert len(captured) == 1
    phone.assert_awaited_once_with(pool, USER, "Your report is ready.")
