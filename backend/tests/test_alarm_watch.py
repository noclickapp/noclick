"""Missing-update deadlines use real persisted state and a controlled clock.

Only scheduler HTTP and URL registration are replaced; calls run through the
agent's alarm tool and the same delivery claim used by both webhook transports.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import json
import uuid

import pytest
import pytest_asyncio
from tests.fixtures.real_db_fixture import real_database
from nodes.agent.tool_execution import _execute_schedule_alarm
from utils import alarm_watch


@pytest_asyncio.fixture
async def watch(real_database, monkeypatch):
    db = real_database
    owner, wid = str(uuid.uuid4()), str(uuid.uuid4())
    await db.execute(
        "INSERT INTO auth.users(id,email) VALUES($1,$2)", owner, f"{owner}@example.test"
    )
    await db.execute(
        "INSERT INTO workflows(id,owner_id,name,workflow) VALUES($1,$2,'Missing updates','{}'::jsonb)",
        wid,
        owner,
    )
    clock = [datetime(2026, 9, 14, 8, tzinfo=timezone.utc)]
    monkeypatch.setattr(alarm_watch, "_now", lambda: clock[0])
    scheduled = []

    async def schedule(**kwargs):
        scheduled.append(kwargs)
        return {"id": f"timer-{len(scheduled)}", "next_run": kwargs["run_at"]}

    monkeypatch.setattr("utils.cron_scheduler_client.create_alarm", schedule)
    monkeypatch.setattr(
        "utils.cron_scheduler_client.delete_schedule",
        AsyncMock(return_value={"success": True}),
    )
    monkeypatch.setattr(
        "utils.webhook_manager.WebhookManager.get_or_create_webhook",
        AsyncMock(return_value={"webhook_url": "https://example.test/alarm"}),
    )

    def agent():
        return SimpleNamespace(node_id="brain", workflow_id=wid, user_id=owner)

    async def arm(deadline, observed=None, **extra):
        return await _execute_schedule_alarm(
            agent(),
            {
                "alarm_type": "datetime",
                "delay_or_time": deadline.isoformat(),
                "message": "Site A missed its reporting window. Alert the manager privately.",
                "watch_key": "site-a",
                **({"observed_at": observed.isoformat()} if observed else {}),
                **extra,
            },
            {"node_id": "alarm"},
        )

    async def fire(index):
        # No state instance is retained between calls: each models a fresh process.
        return await alarm_watch.claim_watch_delivery(
            wid, "alarm", "brain", scheduled[index]["payload"]
        )

    return db, wid, clock, scheduled, arm, fire


async def test_silence_dispatches_once_after_restart_and_never_early(watch):
    db, wid, clock, scheduled, arm, fire = watch
    deadline = clock[0] + timedelta(hours=1)
    assert (await arm(deadline))["status"] == "armed"
    with pytest.raises(RuntimeError, match="not due"):
        await fire(0)
    clock[0] = deadline
    assert await fire(0) is True
    assert await fire(0) is False
    stored = await db.fetchval(
        "SELECT state FROM workflow_node_state WHERE workflow_id=$1 AND node_id='alarm'",
        wid,
    )
    if isinstance(stored, str):
        stored = json.loads(stored)
    incident = stored["deadline_watches"]["brain:site-a"]
    assert incident["status"] == "fired" and incident["fired_at"]


async def test_on_time_update_replaces_old_deadline_and_duplicate_does_not_delay_it(
    watch,
):
    _, _, clock, scheduled, arm, fire = watch
    initial = clock[0] + timedelta(hours=1)
    await arm(initial)
    clock[0] += timedelta(minutes=30)
    next_deadline = initial + timedelta(hours=1)
    assert (await arm(next_deadline, clock[0]))["status"] == "armed"
    assert (await arm(next_deadline + timedelta(days=1), clock[0]))[
        "schedule_id"
    ] == "timer-2"
    assert len(scheduled) == 2
    clock[0] = initial
    assert await fire(0) is False
    clock[0] = next_deadline
    assert await fire(1) is True
    assert await fire(1) is False


async def test_scheduler_failure_is_unarmed_and_can_retry_same_observation(
    watch, monkeypatch
):
    _, _, clock, scheduled, arm, fire = watch
    deadline = clock[0] + timedelta(hours=1)
    await arm(deadline)
    real_scheduler = __import__(
        "utils.cron_scheduler_client", fromlist=["create_alarm"]
    ).create_alarm
    monkeypatch.setattr(
        "utils.cron_scheduler_client.create_alarm",
        AsyncMock(return_value={"error": "scheduler unavailable"}),
    )
    clock[0] += timedelta(minutes=30)
    updated = clock[0]
    result = await arm(deadline + timedelta(hours=1), updated)
    assert result["success"] is False and "not armed" in result["error"]
    clock[0] = deadline
    assert await fire(0) is False  # never alert about an update already received
    monkeypatch.setattr("utils.cron_scheduler_client.create_alarm", real_scheduler)
    assert (await arm(deadline + timedelta(hours=1), updated))["success"] is True


async def test_watch_rejects_ambiguous_time_and_recurring_cron(watch):
    _, _, clock, scheduled, arm, _ = watch
    result = await arm(clock[0] + timedelta(hours=1), alarm_type="cron")
    assert result["success"] is False
    result = await arm((clock[0] + timedelta(hours=1)).replace(tzinfo=None))
    assert result["success"] is False and "timezone" in result["error"]
    assert not scheduled


async def test_cancelling_a_watch_suppresses_an_already_queued_delivery(watch):
    _, wid, clock, scheduled, arm, fire = watch
    from nodes.agent.tool_execution import _execute_alarm_tool

    deadline = clock[0] + timedelta(hours=1)
    await arm(deadline)
    node = SimpleNamespace(node_id="brain", workflow_id=wid, user_id="owner")
    result = await _execute_alarm_tool(
        node, "cancel_alarm", {"schedule_id": "timer-1"}, {"node_id": "alarm"}
    )
    assert result["success"] is True
    clock[0] = deadline
    assert await fire(0) is False


async def test_concurrent_timer_deliveries_dispatch_one_private_alert(
    watch, monkeypatch
):
    import asyncio
    from nodes.agent.node_op_tools import build_provider_output, build_node_op_tools
    from nodes.core.run_op import run_node_op_tool

    _, _, clock, scheduled, arm, fire = watch
    deadline = clock[0] + timedelta(hours=1)
    await arm(deadline)
    output = build_provider_output(
        "automation-whatsapp",
        {"to": "manager@lid", "agent_tool_operations": ["send_text_message"]},
    )
    _, tools = build_node_op_tools(
        "automation-whatsapp", output["allowed_operations"], node_id="alerts"
    )
    info = next(t for t in tools.values() if t.get("operation") == "send_text_message")
    provider = AsyncMock(return_value={"status": "provider_accepted"})
    monkeypatch.setattr("nodes.core.run_op.run_node_operation", provider)
    clock[0] = deadline

    async def deliver():
        if await fire(0):
            await run_node_op_tool(
                info,
                {"to": "manager@lid", "body": scheduled[0]["payload"]["message"]},
                user_id="owner",
            )
            return True
        return False

    assert sorted(await asyncio.gather(deliver(), deliver())) == [False, True]
    provider.assert_awaited_once()
    assert provider.call_args.kwargs["arguments"]["to"] == "manager@lid"
