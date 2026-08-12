"""Async utility helpers.

This module exists to centralize asyncio patterns that are easy to get
wrong — chief among them, fire-and-forget background tasks.

Background-task gotcha (Python 3.11+):
    ``asyncio.create_task(coro)`` returns a Task object, but the event loop
    only holds a *weak* reference to it. If the caller doesn't retain the
    Task, the GC can collect it mid-flight — silently dropping the work.
    The official Python docs explicitly warn about this:
    https://docs.python.org/3/library/asyncio-task.html#asyncio.create_task

    Even when the GC doesn't drop the task, exceptions raised inside an
    unawaited Task are logged via the loop's default exception handler
    only when the Task is GC'd — at an unpredictable later time, with no
    causal context.

    ``spawn()`` below fixes both problems: it holds a strong reference in
    a module-level set until the task completes, and logs unhandled
    exceptions immediately when they occur with a named-task context line.

Use ``spawn()`` instead of ``asyncio.create_task()`` for any background
work that should run to completion without the caller awaiting it
(analytics, notifications, persistence cleanup, fire-and-forget event
emits). Use ``asyncio.create_task()`` directly only when you're
retaining the returned Task and managing its lifecycle yourself.
"""

import asyncio
import logging
from typing import Coroutine, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Module-level strong reference set. Tasks are added on spawn, removed on
# done — bounded by in-flight count, not by total spawn count. This is the
# canonical fix for the Python 3.11+ weak-ref GC gotcha.
_bg_tasks: Set[asyncio.Task] = set()


def spawn(coro: Coroutine, *, name: Optional[str] = None) -> asyncio.Task:
    """Schedule a coroutine as a tracked fire-and-forget background task.

    Holds a strong reference in a module-level set until the task
    completes — preventing GC from collecting an unawaited Task mid-flight
    (a known asyncio.create_task footgun, see module docstring).

    Logs unhandled exceptions when the task finishes, with the task name
    in the log line for correlatable debugging. Cancellations are silent
    (matches asyncio's own behavior).

    Args:
        coro: The coroutine to run.
        name: Optional task name (recommended — shows up in
            ``asyncio.task_name_top`` censuses and in exception logs, so
            future leak diagnoses can identify the spawning site).

    Returns:
        The created Task. Caller usually discards this — for cases where
        you need to cancel or check the result, prefer
        ``asyncio.create_task`` directly so you remember to handle the
        lifecycle yourself.
    """
    task = asyncio.create_task(coro, name=name)
    _bg_tasks.add(task)
    task.add_done_callback(_on_done)
    return task


def _on_done(task: asyncio.Task) -> None:
    _bg_tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        name = task.get_name()
        logger.error(
            f"[spawn] background task '{name}' raised an exception",
            exc_info=exc,
        )


def active_task_count() -> int:
    """Return the count of currently in-flight ``spawn()``-tracked tasks.

    Useful for diagnostics — e.g., periodic logging, or asserting in tests
    that all background work completed before a teardown step.
    """
    return len(_bg_tasks)


async def drain_spawned_tasks(timeout: float = 2.0) -> Tuple[int, int]:
    """Finish tracked one-shot work before process resources are closed.

    Tasks spawned while the drain is in progress are included. Once the
    bounded grace period expires, remaining tasks are cancelled and awaited so
    they cannot resume against a closed database or HTTP client.

    Returns:
        ``(completed_count, cancelled_count)`` for shutdown diagnostics.
    """
    loop = asyncio.get_running_loop()
    current = asyncio.current_task()
    deadline = loop.time() + max(0.0, timeout)
    completed = 0

    while True:
        pending = {
            task
            for task in _bg_tasks
            if task is not current
            and task.get_loop() is loop
            and not task.done()
        }
        if not pending:
            return completed, 0

        remaining = deadline - loop.time()
        if remaining <= 0:
            break

        done, still_pending = await asyncio.wait(pending, timeout=remaining)
        completed += len(done)
        if still_pending:
            pending = still_pending
            break

    # Include work spawned by a task at the edge of the deadline.  No new
    # application work should be admitted once lifespan shutdown has begun,
    # but collecting the live set again makes the shutdown boundary robust to
    # a final chained fire-and-forget operation.
    pending = {
        task
        for task in _bg_tasks
        if task is not current
        and task.get_loop() is loop
        and not task.done()
    }
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    return completed, len(pending)
