"""Burst/backpressure, restart, and lease fencing across the shared scheduler."""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from repositories.coordinator_lease import TurnLease, CoordinatorBusy, coordinator_lock
from repositories.local_schedules import LocalScheduleRepo
from tests.fixtures.local_scheduler import local_scheduler  # noqa: F401
from tests.test_builder_requests import USER, builder_request_db  # noqa: F401

pytestmark = pytest.mark.asyncio


async def add(repo, *, kind="workflow", **overrides):
    return await repo.save({"user_id": USER, "workflow_id": "wf" if kind == "workflow" else None,
                           "node_id": "alarm" if kind == "workflow" else None, "target_kind": kind,
                           "run_at": (datetime.now(timezone.utc)-timedelta(seconds=10)).isoformat(),
                           "webhook_url": "http://instance.test/webhook/abc", **overrides})


async def test_thousand_due_alarms_have_bounded_concurrency_and_short_transactions(local_scheduler, monkeypatch):
    from utils import local_cron
    _, pool = local_scheduler
    repo = LocalScheduleRepo(pool)
    await asyncio.gather(*(add(repo) for _ in range(1000)))
    gate = asyncio.Event()
    calls = []

    async def deliver(row):
        calls.append(row["id"])
        await gate.wait()
        await repo.finish(row, success=True)

    monkeypatch.setattr(local_cron, "_deliver", deliver)
    monkeypatch.setattr(local_cron, "_active_deliveries", set())
    monkeypatch.setenv("LOCAL_SCHEDULER_CONCURRENCY", "8")
    try:
        await local_cron._tick()
        await asyncio.sleep(0)
        await local_cron._tick()
        assert len(calls) == 8
        assert await pool.fetchval("SELECT count(*) FROM local_cron_schedules WHERE lease_owner IS NOT NULL") == 8
        # Everything not admitted is still durable, not a Python task waiting on a semaphore.
        assert await pool.fetchval("SELECT count(*) FROM local_cron_schedules WHERE lease_owner IS NULL") == 992
        connections = await asyncio.gather(*(pool.acquire() for _ in range(5)))
        for conn in connections:
            await pool.release(conn)
    finally:
        gate.set()
        await asyncio.gather(*local_cron._active_deliveries)
        local_cron._active_deliveries.clear()


async def test_two_local_processes_never_claim_same_occurrence(local_scheduler):
    _, pool = local_scheduler
    repo = LocalScheduleRepo(pool)
    await asyncio.gather(*(add(repo) for _ in range(30)))
    batches = await asyncio.gather(*(LocalScheduleRepo(pool).claim(8) for _ in range(5)))
    ids = [row["occurrence_id"] for batch in batches for row in batch]
    assert len(ids) == len(set(ids)) == 30


async def test_concurrent_creation_cannot_take_another_owners_stable_id(local_scheduler):
    _, pool = local_scheduler
    repo = LocalScheduleRepo(pool)
    schedule_id = str(uuid.uuid4())
    results = await asyncio.gather(
        add(repo, id=schedule_id), add(repo, id=schedule_id, user_id="another-owner"),
        return_exceptions=True,
    )
    assert sum(isinstance(result, ValueError) for result in results) == 1
    row = await repo.get(schedule_id)
    with pytest.raises(ValueError, match="another target"):
        await add(repo, id=schedule_id, user_id=row["user_id"], node_id="another-node")


async def test_retention_preserves_paused_schedules(local_scheduler):
    _, pool = local_scheduler
    repo = LocalScheduleRepo(pool)
    cancelled = await add(repo, kind="coordinator")
    paused = await add(repo)
    await repo.delete(str(cancelled["id"]))
    await repo.update(str(paused["id"]), {"enabled": False})
    await pool.execute("UPDATE local_cron_schedules SET updated_at=now()-interval '31 days'")
    await repo.prune()
    assert await repo.get(str(cancelled["id"])) is None
    assert await repo.get(str(paused["id"])) is not None


async def test_restart_reuses_delivery_id_and_fences_old_completion(local_scheduler):
    _, pool = local_scheduler
    repo = LocalScheduleRepo(pool)
    await add(repo)
    first = (await repo.claim(1))[0]
    await pool.execute("UPDATE local_cron_schedules SET lease_until=now()-interval '1 second'")
    second = (await LocalScheduleRepo(pool).claim(1))[0]
    assert second["occurrence_id"] == first["occurrence_id"]
    assert second["lease_owner"] != first["lease_owner"]
    await repo.finish(first, success=True)
    assert await repo.get(str(first["id"]))  # stale owner cannot delete
    await repo.finish(second, success=True)
    assert await repo.get(str(first["id"])) is None


async def test_failed_one_shot_is_retained_and_backpressure_is_durable(local_scheduler):
    _, pool = local_scheduler
    repo = LocalScheduleRepo(pool)
    await add(repo)
    row = (await repo.claim(1))[0]
    await repo.finish(row, success=False, error="HTTP 503", retry_after=120)
    pending = await repo.get(str(row["id"]))
    assert pending["enabled"] and pending["occurrence_id"] == row["occurrence_id"]
    assert await repo.claim(1) == []
    await pool.execute("UPDATE local_cron_schedules SET next_run=now()-interval '1 second'")
    retry = (await repo.claim(1))[0]
    await repo.finish(retry, success=False, error="HTTP 403")
    failed = await repo.get(str(row["id"]))
    assert not failed["enabled"] and failed["last_status"] == "failed"


async def test_update_and_cancel_fence_in_flight_scheduler_delivery(local_scheduler):
    _, pool = local_scheduler
    repo = LocalScheduleRepo(pool)
    saved = await add(repo, kind="coordinator")
    claimed = (await repo.claim(1))[0]
    await add(repo, kind="coordinator", id=str(saved["id"]), payload={"message": "new"})
    assert not await repo.heartbeat(claimed)
    await repo.finish(claimed, success=True)
    assert (await repo.get(str(saved["id"])))["enabled"]
    current = (await repo.claim(1))[0]
    await repo.delete(str(saved["id"]))
    await repo.finish(current, success=True)
    assert (await repo.get(str(saved["id"])))["last_status"] == "cancelled"


async def test_account_lease_does_not_hold_connection_and_expired_owner_is_fenced(local_scheduler):
    _, pool = local_scheduler
    first = TurnLease(pool, USER)
    assert await first.acquire()
    connections = await asyncio.gather(*(pool.acquire() for _ in range(5)))
    for conn in connections:
        await pool.release(conn)
    await pool.execute("UPDATE conversations SET coordinator_lease_until=now()-interval '1 second'")
    second = TurnLease(pool, USER)
    assert await second.acquire()
    with pytest.raises(RuntimeError, match="expired"):
        await first.check()
    await first.release()
    await second.check()
    await second.release()


async def test_global_concurrency_budget_is_shared_between_processes(local_scheduler, monkeypatch):
    _, pool = local_scheduler
    monkeypatch.setenv("COORDINATOR_MAX_CONCURRENT_TURNS", "1")
    async with coordinator_lock(pool, USER):
        with pytest.raises(CoordinatorBusy):
            async with coordinator_lock(pool, str(uuid.uuid4()), wait_seconds=0):
                pytest.fail("No capacity should have been granted")


async def test_dispatch_reconciles_failed_registration_without_replacing_existing_timer(local_scheduler, monkeypatch):
    from repositories.coordinator_wakeups import CoordinatorWakeupRepo
    from utils import coordinator_dispatch, cron_scheduler_client as client
    _, pool = local_scheduler
    event_id = uuid.uuid4()
    await pool.execute("INSERT INTO coordinator_wakeups(id,user_id,source,source_id,context,payload) VALUES($1,$2::uuid,'builder',$3,'{}','{}')", event_id, USER, uuid.uuid4())
    repo = CoordinatorWakeupRepo(pool)
    event = await repo.get(event_id)
    original = client.create_alarm
    monkeypatch.setattr(client, "create_alarm", AsyncMock(return_value={"error": "outage"}))
    assert not await coordinator_dispatch.dispatch_event(pool, event)
    assert (await repo.get(event_id))["status"] == "queued"
    monkeypatch.setattr(client, "create_alarm", original)
    await coordinator_dispatch.reconcile(pool)
    row = dict((await LocalScheduleRepo(pool).list(user_id=USER, target_kind="coordinator_wakeup"))[0])
    assert await coordinator_dispatch.dispatch_event(pool, event)
    unchanged = await LocalScheduleRepo(pool).get(str(row["id"]))
    assert unchanged["revision"] == row["revision"]
    await pool.execute("DELETE FROM coordinator_wakeups WHERE id=$1", event_id)
