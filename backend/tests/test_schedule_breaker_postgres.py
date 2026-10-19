"""The schedule breaker judges each trigger by its own runs, on the real schema.

A workflow with two schedules (two polls, or two crons) interleaves their runs.
Read as one stream, one trigger's identical failures never stand next to each
other, so the breaker never tripped: a workflow whose Gmail and Notion polls
had no credentials failed every five minutes for two weeks (8,257 runs). A run
belongs to the trigger that ran in it (its manifest); a run that failed before
any node ran belongs to every trigger.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

TEST_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
GMAIL_ERR = "Node email failed: [GmailNode] Gmail credentials are required"
NOTION_ERR = "Node notion failed: Credentials are required."
NEWEST = datetime(2026, 10, 16, 16, 40, tzinfo=timezone.utc)


class _Pool:
    def __init__(self, conn):
        self.fetch = conn.fetch


async def _workflow(conn):
    wid = uuid.uuid4()
    await conn.execute("INSERT INTO workflows (id, owner_id, name) VALUES ($1, $2, 'two polls')",
                       wid, TEST_USER_ID)
    return wid


async def _run(conn, wid, at, *, status, error=None, ran=()):
    eid = uuid.uuid4()
    await conn.execute(
        "INSERT INTO workflow_executions (id, workflow_id, user_id, status, error, started_at, trigger_source) "
        "VALUES ($1, $2, $3, $4, $5, $6, 'webhook')", eid, wid, TEST_USER_ID, status, error, at)
    for node_id in ran:
        await conn.execute(
            "INSERT INTO cas_manifests (workflow_id, execution_id, node_id, manifest, last_run_status) "
            "VALUES ($1, $2, $3, '{}'::jsonb, 'error')", wid, eid, node_id)


async def _streak(conn, wid, node_id):
    from utils.webhook_routes import _schedule_failure_streak
    with patch("utils.webhook_routes.get_native_pool", return_value=_Pool(conn)):
        return await _schedule_failure_streak(str(wid), "webhook", node_id)


@pytest.mark.asyncio
async def test_two_polls_failing_differently_each_trip_their_own_breaker(postgres_db):
    wid = await _workflow(postgres_db)
    for tick in range(6):
        at = NEWEST - timedelta(minutes=5 * tick)
        await _run(postgres_db, wid, at, status="error", error=GMAIL_ERR, ran=("email", "tools"))
        await _run(postgres_db, wid, at + timedelta(seconds=1), status="error", error=NOTION_ERR,
                   ran=("notion", "tools"))

    gmail = await _streak(postgres_db, wid, "email")
    notion = await _streak(postgres_db, wid, "notion")

    assert (gmail.count, gmail.error, gmail.span_s) == (6, GMAIL_ERR, 25 * 60)
    assert (notion.count, notion.error) == (6, NOTION_ERR)


@pytest.mark.asyncio
async def test_a_healthy_schedule_beside_a_failing_one_is_not_paused(postgres_db):
    wid = await _workflow(postgres_db)
    for tick in range(6):
        at = NEWEST - timedelta(hours=tick)
        await _run(postgres_db, wid, at, status="completed", ran=("healthy",))
        await _run(postgres_db, wid, at + timedelta(seconds=2), status="error", error=GMAIL_ERR,
                   ran=("broken",))

    assert await _streak(postgres_db, wid, "healthy") is None
    broken = await _streak(postgres_db, wid, "broken")
    assert broken.count == 6 and broken.trips_breaker


@pytest.mark.asyncio
async def test_a_run_that_failed_before_any_node_ran_counts_for_every_trigger(postgres_db):
    cycle = "Failed to determine execution order — the workflow contains a cycle."
    wid = await _workflow(postgres_db)
    for tick in range(5):
        await _run(postgres_db, wid, NEWEST - timedelta(hours=tick), status="error", error=cycle)

    streak = await _streak(postgres_db, wid, "email")
    assert streak.count == 5 and streak.trips_breaker
