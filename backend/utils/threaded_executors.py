"""Dedicated thread pool for non-loop-safe execution paths.

One pool today (``js_executor``), kept separate from asyncio's default
ThreadPoolExecutor so it doesn't compete with other sync wrappers for slots.

- ``js_executor``: runs QuickJS code (utils/js_executor.execute_js). QuickJS
  is native code that releases the GIL during JS execution, so threads
  actually parallelize.

If we ever discover OpenHands or another node kind is blocking the asyncio
loop (look at ``event_loop.block`` in Honeycomb grouped by ``blocking.stack``),
the playbook is: add a second ``ThreadPoolExecutor`` here with its own
``run_*_threaded`` wrapper, dispatch the relevant call site through it, and
solve any cross-loop callback bridging at the same time. There used to be
an ``agent_executor`` here as speculative infrastructure — deleted because
unused infrastructure rots faster than it would save us.

Design notes:

- ``threading.stack_size(512 * 1024)`` is set at module import. Bounds per-thread
  memory at 512 KB instead of the default 8 MB, so 500 concurrent threads cost
  ~250 MB of stack overhead instead of ~4 GB.
- ``max_workers`` is intentionally large. It's a safety net against pathological
  cases, not an operational cap. Real backpressure happens at the worker process
  level (``max_concurrent_inputs``), not here.
- ``await run_threaded(...)`` wraps the loop.run_in_executor + asyncio.wait_for
  + cooperative cancellation glue. Callers pass an optional ``cancel_event``
  (threading.Event) that long-running native code checks periodically to exit
  early when the user disconnects.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

# Smaller stacks → more concurrent threads fit in the same container RAM.
# Set before any ThreadPoolExecutor is constructed so its worker threads inherit.
threading.stack_size(512 * 1024)

# Wall-clock default. Callers can override per-invocation.
JS_DEFAULT_TIMEOUT_S = 30.0

js_executor = ThreadPoolExecutor(max_workers=512, thread_name_prefix="js")

T = TypeVar("T")


class ThreadedExecutionTimeout(Exception):
    """The threaded call exceeded its wall-clock timeout."""


async def run_threaded(
    executor: ThreadPoolExecutor,
    fn: Callable[..., T],
    *args,
    timeout_s: float,
    cancel_event: Optional[threading.Event] = None,
    **kwargs,
) -> T:
    """Run ``fn(*args, **kwargs)`` in ``executor``, awaitable from asyncio.

    Enforces a hard wall-clock timeout via ``asyncio.wait_for``. If a
    ``cancel_event`` is provided, asyncio-side cancellation (e.g. user
    disconnected) sets the event so the threaded body can exit cooperatively
    on its next check.

    The threaded body itself must be cancellation-aware — i.e., it must
    periodically check ``cancel_event.is_set()`` between work chunks. Threads
    cannot be killed externally in Python; cooperation is the only mechanism.
    Plan around it.
    """
    loop = asyncio.get_running_loop()
    fut = loop.run_in_executor(executor, lambda: fn(*args, **kwargs))
    try:
        return await asyncio.wait_for(fut, timeout=timeout_s)
    except asyncio.TimeoutError:
        if cancel_event is not None:
            cancel_event.set()
        raise ThreadedExecutionTimeout(
            f"threaded call to {fn.__qualname__} exceeded {timeout_s}s"
        )
    except asyncio.CancelledError:
        if cancel_event is not None:
            cancel_event.set()
        raise


async def run_js_threaded(
    fn: Callable[..., T],
    *args,
    timeout_s: float = JS_DEFAULT_TIMEOUT_S,
    cancel_event: Optional[threading.Event] = None,
    **kwargs,
) -> T:
    """Convenience wrapper for the JS pool."""
    return await run_threaded(
        js_executor, fn, *args, timeout_s=timeout_s, cancel_event=cancel_event, **kwargs
    )


def shutdown_executors(wait: bool = False) -> None:
    """Process-exit hook. ``wait=True`` blocks until in-flight threads finish."""
    js_executor.shutdown(wait=wait)
