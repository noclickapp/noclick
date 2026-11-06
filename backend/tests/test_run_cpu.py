"""A workflow run's CPU, measured on a loop many runs share (utils/run_cpu.py): each run counts its own steps and
its tasks', never another run's, a run inside a run counts once, and what it hands on reaches RUN_CPU_SPENT."""

import asyncio
import time

import pytest

from utils import capabilities, run_cpu
from utils.capabilities import RUN_CPU_SPENT
from utils.run_cpu import RUN_METER, bind, metered_run

pytestmark = pytest.mark.asyncio


def burn(ms: float) -> None:
    """Hold the thread for ``ms`` of CPU."""
    end = time.thread_time() + ms / 1000
    while time.thread_time() < end:
        pass


@pytest.fixture
def spent(monkeypatch):
    """What each run handed to RUN_CPU_SPENT, by execution id."""
    out = {}

    async def record(**kwargs):
        out[kwargs["execution_id"]] = kwargs

    monkeypatch.setitem(capabilities._providers, RUN_CPU_SPENT, record)
    return out


async def settled():
    """Let the spawned records land."""
    for _ in range(5):
        await asyncio.sleep(0)


def run_named(execution_id: str):
    def named(body):
        @metered_run
        async def run():
            bind(execution_id=execution_id, user_id="u-" + execution_id, organization_id=None, workflow_id="wf")
            return await body()

        return run

    return named


async def test_two_runs_on_one_loop_count_only_their_own_steps(spent):
    @run_named("heavy")
    async def heavy():
        for _ in range(5):
            burn(20)
            await asyncio.sleep(0)

    @run_named("light")
    async def light():
        for _ in range(5):
            burn(4)
            await asyncio.sleep(0)

    await asyncio.gather(heavy(), light())
    await settled()
    assert spent["heavy"]["cpu_ms"] == pytest.approx(100, rel=0.15)
    assert spent["light"]["cpu_ms"] == pytest.approx(20, abs=6)
    assert spent["heavy"]["user_id"] == "u-heavy" and spent["heavy"]["workflow_id"] == "wf"


async def test_the_tasks_a_run_starts_are_its_own(spent):
    @run_named("fanout")
    async def fanout():
        async def node(ms):
            await asyncio.sleep(0)
            burn(ms)

        await asyncio.gather(node(15), node(15), asyncio.create_task(node(10)))

    @run_named("bystander")
    async def bystander():
        await asyncio.sleep(0.05)

    await asyncio.gather(fanout(), bystander())
    await settled()
    assert spent["fanout"]["cpu_ms"] == pytest.approx(40, rel=0.2)
    assert spent["bystander"]["cpu_ms"] < 3


async def test_a_run_inside_a_run_counts_once(spent):
    @run_named("inner")
    async def inner():
        burn(30)
        await asyncio.sleep(0)

    @run_named("outer")
    async def outer():
        burn(20)
        await inner()
        burn(20)

    await outer()
    await settled()
    assert spent["inner"]["cpu_ms"] == pytest.approx(30, rel=0.2)
    assert spent["outer"]["cpu_ms"] == pytest.approx(40, rel=0.2)


async def test_a_task_that_outlives_its_run_stops_counting(spent):
    later = asyncio.Event()

    @run_named("brief")
    async def brief():
        async def lingers():
            await later.wait()
            burn(30)

        asyncio.get_running_loop().create_task(lingers())
        burn(5)

    await brief()
    later.set()
    await asyncio.sleep(0.05)
    await settled()
    assert spent["brief"]["cpu_ms"] == pytest.approx(5, abs=3)


async def test_a_cancelled_run_is_still_measured(spent):
    @run_named("stopped")
    async def stopped():
        burn(10)
        await asyncio.sleep(10)

    task = asyncio.create_task(stopped())
    await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await settled()
    assert spent["stopped"]["cpu_ms"] == pytest.approx(10, abs=4)


async def test_an_unnamed_run_records_nothing_and_leaves_no_meter(spent):
    @metered_run
    async def anonymous():
        burn(2)
        return "done"

    assert await anonymous() == "done"
    await settled()
    assert spent == {}
    assert RUN_METER.get() is None


async def test_without_a_recorder_the_run_is_unchanged(monkeypatch):
    monkeypatch.delitem(capabilities._providers, RUN_CPU_SPENT, raising=False)

    @run_named("plain")
    async def plain():
        await asyncio.sleep(0)
        return 7

    assert await plain() == 7
    assert run_cpu.cpu_ms(run_cpu.RunMeter()) == 0
