"""coder/coordinator/jobs.py: one registry per job kind — how a ledger row is
read back, told to the owner, and advanced each minute — so a platform's own
kind plugs in beside the engine's, and finishing any kind hands its outcome to
the coordinator's inbox exactly once."""

from unittest.mock import AsyncMock

import pytest

from coder.coordinator import jobs
from tests.mocks.mock_asyncpg import MockNativePool

pytestmark = pytest.mark.asyncio
USER = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def registry(monkeypatch):
    monkeypatch.setattr(jobs, "JOB_KINDS", {})
    return jobs.JOB_KINDS


async def test_the_engine_kinds_read_back_and_summarise_their_rows():
    assert {"build", "agent", "video"} <= set(jobs.JOB_KINDS)
    video = {"id": "j", "kind": "video", "status": "completed", "result": {"url": "https://f/v.mp4"}, "error": None,
             "spec": {"model": "m", "prompt": "p", "params": {"duration": 8, "resolution": "720p"},
                      "projected_credits": 1.0}}
    view = jobs.job_view(video)
    assert view["kind"] == "video" and jobs.job_summary(view) == "Your video is ready: https://f/v.mp4"
    assert jobs.job_summary({"kind": "video", "status": "failed", "error": "boom"}) == "The video couldn't be made: boom"
    assert jobs.job_summary({"kind": "build", "status": "completed",
                             "result": {"publication": {"url": "https://x"}}}) == "Build completed.\nhttps://x"
    assert jobs.job_summary({"kind": "agent", "status": "failed", "error": "boom"}) == "Agent request failed. boom"
    with pytest.raises(KeyError):
        jobs.job_view({"kind": "mystery"})


async def test_a_platform_kind_plugs_in_with_its_own_poller(registry):
    polled = []

    async def poll(pool):
        polled.append(pool)

    jobs.register_job_kind("purchase", view=lambda r: {"kind": "purchase"}, summary=lambda p: "paid", poll=poll)
    jobs.register_job_kind("quiet", view=lambda r: {"kind": "quiet"}, summary=lambda p: "")
    await jobs.poll_jobs("pool")
    assert polled == ["pool"]
    assert jobs.job_summary({"kind": "purchase"}) == "paid" and jobs.job_view({"kind": "quiet"}) == {"kind": "quiet"}


async def test_finish_job_closes_a_job_once_and_hands_its_outcome_to_the_inbox(registry, monkeypatch):
    jobs.register_job_kind("purchase", summary=lambda p: "",
                           view=lambda r: {"kind": "purchase", "status": r["status"], "what": r["spec"]["what"]})
    row = {"id": "j1", "user_id": USER, "kind": "purchase", "status": "completed", "spec": {"what": "plus"},
           "result": {"paid": True}, "error": None, "continuation": {"epoch": "", "depth": 0}, "send_to_phone": True}
    enqueue = AsyncMock()
    monkeypatch.setattr("repositories.coordinator_wakeups.CoordinatorWakeupRepo.enqueue", enqueue)

    pool = MockNativePool({"UPDATE coordinator_jobs SET status": row})
    done = await jobs.finish_job(pool, "j1", status="completed", result={"paid": True}, expected_status="waiting")
    assert done["status"] == "completed"
    # Only a job still in the expected state is closed, so two workers never finish one twice.
    assert pool.fetchrow.await_args.args[1:] == ("j1", "completed", {"paid": True}, None, "waiting")
    enqueue.assert_awaited_once()
    assert enqueue.await_args.kwargs["payload"] == {"kind": "purchase", "status": "completed", "what": "plus"}
    assert enqueue.await_args.kwargs["context"] == row["continuation"]

    assert await jobs.finish_job(MockNativePool(), "j1", status="completed", expected_status="waiting") is None
    enqueue.assert_awaited_once()

    # A job nobody is waiting on finishes without waking anyone.
    quiet = MockNativePool({"UPDATE coordinator_jobs SET status": {**row, "continuation": None}})
    assert await jobs.finish_job(quiet, "j1", status="completed") is not None
    enqueue.assert_awaited_once()
