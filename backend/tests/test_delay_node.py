"""Tests for the delay node — short in-process delays and long durable delays.

Short delays (<= 15 min) sleep in-process. Long delays schedule a wake-up via
the cron scheduler and suspend the run (DelayExecutionStrategy + the generic
suspend/resume core).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from tests.mocks.mock_asyncpg import MockNativePool

import pytest

from nodes.delay_node import (
    DelayNode,
    DelayNodeConfig,
    DelayInnerConfig,
    DelayExecutionStrategy,
    compute_delay_seconds,
    IN_PROCESS_DELAY_MAX_SECONDS,
)
from nodes.core.suspend_strategy import SuspendingExecutionStrategy


def _make_node(delay_amount: int, delay_unit: str, **kwargs) -> DelayNode:
    config = DelayNodeConfig(
        config=DelayInnerConfig(delay_amount=delay_amount, delay_unit=delay_unit)
    )
    return DelayNode(
        node_id=kwargs.get("node_id", "delay-1"),
        node_type="delay",
        node_data={},
        config=config,
        sio=None,
        sid=None,
        workflow_id=kwargs.get("workflow_id", "wf-1"),
        user_id=kwargs.get("user_id", "user-1"),
        execution_id=kwargs.get("execution_id", "exec-1"),
    )


# ---------------------------------------------------------------------------
# Duration helpers
# ---------------------------------------------------------------------------


def test_compute_delay_seconds_all_units():
    assert compute_delay_seconds(30, "seconds") == 30
    assert compute_delay_seconds(5, "minutes") == 300
    assert compute_delay_seconds(2, "hours") == 7200
    assert compute_delay_seconds(3, "days") == 259200
    assert compute_delay_seconds(2, "weeks") == 1209600


def test_compute_delay_seconds_rejects_unknown_unit():
    with pytest.raises(ValueError):
        compute_delay_seconds(1, "fortnights")


# ---------------------------------------------------------------------------
# Strategy classification
# ---------------------------------------------------------------------------


def test_strategy_is_a_suspending_strategy():
    strat = DelayExecutionStrategy()
    assert isinstance(strat, SuspendingExecutionStrategy)
    assert strat.suspended_status == "awaiting_delay"
    assert strat.handles("delay")
    assert not strat.handles("approval")


def test_strategy_delay_seconds_for_short_and_long():
    # The runtime node blob holds config fields flat on node["config"]
    # (matching the persisted workflow format).
    short = {"type": "delay", "config": {"delay_amount": 30, "delay_unit": "seconds"}}
    long = {"type": "delay", "config": {"delay_amount": 2, "delay_unit": "weeks"}}
    assert DelayExecutionStrategy._delay_seconds_for(short) == 30
    assert DelayExecutionStrategy._delay_seconds_for(short) <= IN_PROCESS_DELAY_MAX_SECONDS
    assert DelayExecutionStrategy._delay_seconds_for(long) == 1209600
    assert DelayExecutionStrategy._delay_seconds_for(long) > IN_PROCESS_DELAY_MAX_SECONDS


def test_strategy_delay_seconds_for_persisted_workflow_shape():
    # A 30-minute delay from a persisted workflow must be
    # classified as long (> 15 min) so it suspends instead of running through.
    node = {"id": "delay_4llf", "type": "delay",
            "config": {"delay_amount": 30, "delay_unit": "minutes", "credentialIds": {}}}
    seconds = DelayExecutionStrategy._delay_seconds_for(node)
    assert seconds == 1800
    assert seconds > IN_PROCESS_DELAY_MAX_SECONDS


def test_strategy_delay_seconds_for_malformed_config():
    # A malformed config must not crash orchestration — it falls back to 0
    # (treated as a short delay so the node runs and surfaces its own error).
    bad = {"type": "delay", "config": {"delay_amount": "oops", "delay_unit": "weeks"}}
    assert DelayExecutionStrategy._delay_seconds_for(bad) == 0


# ---------------------------------------------------------------------------
# Short delay — in-process
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_short_delay_runs_in_process():
    node = _make_node(2, "seconds")
    with patch("nodes.delay_node.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        output = await node.execute({})
    mock_sleep.assert_awaited_once_with(2)
    assert output["status"] == "completed"
    assert output["delay_seconds"] == 2


# ---------------------------------------------------------------------------
# Long delay — durable suspend
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_long_delay_schedules_wakeup_and_returns_waiting():
    node = _make_node(2, "weeks")

    from tests.mocks.mock_asyncpg import MockNativePool

    create_alarm = AsyncMock(return_value={"id": "sched-abc"})
    get_webhook = AsyncMock(return_value={"webhook_url": "https://wh.example/abc"})
    pool = MockNativePool()

    with patch("utils.cron_scheduler_client.is_cron_scheduler_enabled", return_value=True), \
         patch("utils.cron_scheduler_client.create_alarm", create_alarm), \
         patch("utils.webhook_manager.WebhookManager.get_or_create_webhook", get_webhook), \
         patch("utils.database_pool.get_native_pool", return_value=pool):
        output = await node.execute({})

    # Returns a 'waiting' output (the strategy then suspends the run).
    assert output["status"] == "waiting"
    assert output["delay_seconds"] == 1209600
    assert "wake_at" in output

    # Scheduled a one-time wake-up carrying the delay_resume payload.
    create_alarm.assert_awaited_once()
    kwargs = create_alarm.await_args.kwargs
    assert kwargs["payload"]["type"] == "delay_resume"
    assert kwargs["payload"]["execution_id"] == "exec-1"
    assert kwargs["payload"]["resume_node_id"] == "delay-1"
    assert kwargs["webhook_url"] == "https://wh.example/abc"

    # Recorded resume info on the execution row.
    pool.execute.assert_awaited_once()
    update_sql = pool.execute.await_args.args[0]
    assert "UPDATE workflow_executions" in update_sql
    assert "external_schedule_id" in update_sql


@pytest.mark.asyncio
async def test_long_delay_errors_when_scheduler_disabled():
    node = _make_node(3, "days")
    with patch("utils.cron_scheduler_client.is_cron_scheduler_enabled", return_value=False):
        with pytest.raises(RuntimeError, match="cron scheduler"):
            await node.execute({})


@pytest.mark.asyncio
async def test_long_delay_errors_when_scheduling_fails():
    node = _make_node(3, "days")
    create_alarm = AsyncMock(return_value={"error": "HTTP 500"})
    get_webhook = AsyncMock(return_value={"webhook_url": "https://wh.example/abc"})

    with patch("utils.cron_scheduler_client.is_cron_scheduler_enabled", return_value=True), \
         patch("utils.cron_scheduler_client.create_alarm", create_alarm), \
         patch("utils.webhook_manager.WebhookManager.get_or_create_webhook", get_webhook), \
         patch("utils.database_pool.get_native_pool", return_value=MockNativePool()):
        with pytest.raises(RuntimeError, match="failed to schedule"):
            await node.execute({})


# ---------------------------------------------------------------------------
# Delay-resume webhook routing
# ---------------------------------------------------------------------------


def test_build_delay_resume_data_recognises_callback():
    from utils.webhook_routes import _build_delay_resume_data

    payload = {
        "schedule_id": "sched-1",
        "workflow_id": "wf-ignored-in-payload",
        "payload": {
            "type": "delay_resume",
            "execution_id": "exec-9",
            "resume_node_id": "delay-9",
        },
    }
    data = _build_delay_resume_data(payload, "wf-9")
    assert data == {
        "execution_id": "exec-9",
        "workflow_id": "wf-9",
        "resume_node_id": "delay-9",
        "from_status": "awaiting_delay",
        "decision": None,
    }


def test_build_delay_resume_data_ignores_non_delay_webhooks():
    from utils.webhook_routes import _build_delay_resume_data

    # A regular webhook trigger payload
    assert _build_delay_resume_data({"some": "event"}, "wf-1") is None
    # An alarm-style payload that isn't a delay resume
    assert _build_delay_resume_data({"payload": {"type": "alarm_trigger"}}, "wf-1") is None
    # A delay_resume missing required ids
    assert _build_delay_resume_data({"payload": {"type": "delay_resume"}}, "wf-1") is None
