"""The CPU a workflow run spends on this process, measured as the run goes.

One event loop serves many runs at once, so neither the process's CPU nor a
clock around a node's ``execute`` is any one run's: an ``await`` hands the
thread to whichever run is ready. A run's CPU is the time its own code holds
the thread, between one suspension and the next. ``drive`` times exactly that:
it steps a coroutine itself, reading ``time.thread_time`` around each ``send``
and ``throw``. Every task the run starts is stepped the same way (a task factory
installed on the loop the first time a run is metered wraps each task created
inside a run's context), and nested driving counts once: an inner meter's time
is its own, never also the outer's.

What it can't see, so a run is charged a little less than it used, never more:
work the run hands to other threads (``asyncio.to_thread``, executors), the
loop's own bookkeeping between steps, and anything a task the run started does
after the run has finished.

``metered_run`` wraps a run's entry point; the run names itself with ``bind``
once it knows its ids; when it ends, its CPU goes on its span (``run.cpu_ms``)
and to ``RUN_CPU_SPENT`` where the instance provides one (hosted: billing).
"""

from __future__ import annotations

import asyncio
import functools
import logging
import threading
import time
from contextvars import ContextVar
from typing import Any, Awaitable, Callable, Optional

from utils.capabilities import RUN_CPU_SPENT, capability

logger = logging.getLogger(__name__)


class RunMeter:
    """One run's CPU so far, and who it's for once the run says (``bind``)."""

    __slots__ = ("seconds", "closed", "execution_id", "user_id", "organization_id", "workflow_id")

    def __init__(self) -> None:
        self.seconds = 0.0
        self.closed = False
        self.execution_id: Optional[str] = None
        self.user_id: Optional[str] = None
        self.organization_id: Optional[str] = None
        self.workflow_id: Optional[str] = None


RUN_METER: ContextVar[Optional[RunMeter]] = ContextVar("run_meter", default=None)

# The steps being timed on this thread, innermost last: [meter, started]. Starting an inner step charges the
# outer one up to that moment and restarts its clock when the inner one ends, so each second is counted once.
_steps = threading.local()


def _timed(meter: RunMeter, step: Callable[[], Any]) -> Any:
    stack = getattr(_steps, "stack", None)
    if stack is None:
        stack = _steps.stack = []
    now = time.thread_time()
    if stack:
        outer = stack[-1]
        outer[0].seconds += now - outer[1]
    frame = [meter, now]
    stack.append(frame)
    try:
        return step()
    finally:
        now = time.thread_time()
        stack.pop()
        meter.seconds += now - frame[1]
        if stack:
            stack[-1][1] = now


class _Driven:
    """Awaiting it runs ``coro`` to its end, each step of it timed for ``meter``."""

    __slots__ = ("_coro", "_meter")

    def __init__(self, coro, meter: RunMeter) -> None:
        self._coro = coro
        self._meter = meter

    def __await__(self):
        coro, meter = self._coro, self._meter
        value: Any = None
        error: Optional[BaseException] = None
        while True:
            try:
                if meter.closed:
                    yielded = coro.throw(error) if error is not None else coro.send(value)
                elif error is not None:
                    yielded = _timed(meter, functools.partial(coro.throw, error))
                else:
                    yielded = _timed(meter, functools.partial(coro.send, value))
            except StopIteration as done:
                return done.value
            error = None
            try:
                value = yield yielded
            except GeneratorExit:
                coro.close()
                raise
            except BaseException as thrown:  # a cancel or anything else thrown into the task: the run's to handle
                value, error = None, thrown


async def drive(coro, meter: RunMeter):
    """Run ``coro`` to its end with each of its steps counted for ``meter``."""
    return await _Driven(coro, meter)


def _metered_factory(previous):
    def factory(loop, coro, **kwargs):
        context = kwargs.get("context")
        meter = context.get(RUN_METER) if context is not None else RUN_METER.get()
        if meter is not None and not meter.closed:
            coro = drive(coro, meter)
        if previous is not None:
            return previous(loop, coro, **kwargs)
        return asyncio.Task(coro, loop=loop, **kwargs)

    factory.metered = True  # type: ignore[attr-defined]
    return factory


def _install(loop: asyncio.AbstractEventLoop) -> None:
    current = loop.get_task_factory()
    if not getattr(current, "metered", False):
        loop.set_task_factory(_metered_factory(current))


def bind(*, execution_id: Optional[str], user_id: Optional[str], organization_id: Optional[str],
         workflow_id: Optional[str]) -> None:
    """Name the run being metered (a no-op outside one): whose CPU it is and which run."""
    meter = RUN_METER.get()
    if meter is None:
        return
    meter.execution_id = str(execution_id) if execution_id else None
    meter.user_id = str(user_id) if user_id else None
    meter.organization_id = str(organization_id) if organization_id else None
    meter.workflow_id = str(workflow_id) if workflow_id else None


def cpu_ms(meter: RunMeter) -> float:
    return meter.seconds * 1000


def _spent(meter: RunMeter) -> None:
    """Put the run's CPU on its span, and hand it to whatever records it, off the run's own return."""
    from opentelemetry import trace

    from utils.async_helpers import spawn

    ms = cpu_ms(meter)
    trace.get_current_span().set_attribute("run.cpu_ms", round(ms, 3))
    record = capability(RUN_CPU_SPENT)
    if record is None or not meter.execution_id or not meter.user_id or not meter.workflow_id:
        return

    async def recorded() -> None:
        try:
            await record(
                execution_id=meter.execution_id, user_id=meter.user_id, organization_id=meter.organization_id,
                workflow_id=meter.workflow_id, cpu_ms=ms,
            )
        except Exception:
            # The run happened: a lost record is CPU used and never charged, so it's loud.
            logger.error("[run_cpu] couldn't record %.3f CPU ms for run %s", ms, meter.execution_id, exc_info=True)

    spawn(recorded(), name=f"run-cpu:{meter.execution_id}")


def metered_run(run: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    """Wrap a run's entry point: its CPU, and every task's it starts, counted until it returns. A run started
    inside another run is metered on its own, and its time is not also the outer run's."""

    @functools.wraps(run)
    async def measured(*args, **kwargs):
        _install(asyncio.get_running_loop())
        meter = RunMeter()
        token = RUN_METER.set(meter)
        try:
            return await drive(run(*args, **kwargs), meter)
        finally:
            RUN_METER.reset(token)
            meter.closed = True
            _spent(meter)

    return measured
