"""A converged schedule still reports a moving next_run.

The reconciler's live fast path used to answer with no values, so the panel's
countdown — which refetches through it on expiry — stayed on "Running…" after
the first tick. The refresh asks the scheduler and patches the mirror only
when it moved; a scheduler error keeps the mirror.
"""

import pytest

from utils import webhook_manager as wm


@pytest.mark.asyncio
async def test_a_moved_next_run_is_returned_and_persisted(monkeypatch):
    calls = []

    async def fake_get_schedule(schedule_id, timeout=10.0):
        return {"id": schedule_id, "next_run": {"s1": "2026-08-30T12:00:05+00:00", "s2": "2026-08-30T12:00:03+00:00"}[schedule_id]}

    async def fake_merge(pool, wf, node, patch):
        calls.append(patch)

    monkeypatch.setattr("utils.cron_scheduler_client.get_schedule", fake_get_schedule)
    monkeypatch.setattr(wm.WebhookManager, "merge_node_config_patch", staticmethod(fake_merge))
    got = await wm.WebhookManager._refresh_schedule_next_run(
        None, "wf", "n", {"schedule_ids": ["s1", "s2"], "next_run": "2026-08-30T11:59:50+00:00"}, persist=True,
    )
    assert got == {"next_run": "2026-08-30T12:00:03+00:00"}, "the earliest across the node's schedules"
    assert calls == [{"next_run": "2026-08-30T12:00:03+00:00"}]


@pytest.mark.asyncio
async def test_an_unchanged_or_unknowable_next_run_leaves_the_mirror(monkeypatch):
    async def same(schedule_id, timeout=10.0):
        return {"next_run": "2026-08-30T12:00:00+00:00"}

    monkeypatch.setattr("utils.cron_scheduler_client.get_schedule", same)
    cfg = {"schedule_id": "s1", "next_run": "2026-08-30T12:00:00+00:00"}
    assert await wm.WebhookManager._refresh_schedule_next_run(None, "wf", "n", cfg, persist=True) is None

    async def broken(schedule_id, timeout=10.0):
        return {"error": "Cron scheduler not configured", "skipped": True}

    monkeypatch.setattr("utils.cron_scheduler_client.get_schedule", broken)
    assert await wm.WebhookManager._refresh_schedule_next_run(None, "wf", "n", cfg, persist=True) is None
    assert await wm.WebhookManager._refresh_schedule_next_run(None, "wf", "n", {}, persist=True) is None
