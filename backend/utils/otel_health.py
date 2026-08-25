"""Background process-health emitter.

Emits a `container.health` span with process and event-loop metrics. The
OpenTelemetry resource identifies the self-hosted service instance.

Also includes per-snapshot name censuses for asyncio tasks and threads
(`asyncio.task_name_top` / `process.thread_name_top`). When a leak appears
in the high-level counters (`asyncio.task_count` or `process.thread_count`
growing monotonically), these tell you *which named things* are accumulating,
in one Honeycomb query — no separate debug endpoint needed.
"""
import asyncio
import gc
import json
import logging
import os
import threading
import time
from collections import Counter

import psutil
from opentelemetry import trace

logger = logging.getLogger(__name__)

_tracer = trace.get_tracer("noclick.health")
_task: asyncio.Task | None = None
_proc = psutil.Process(os.getpid())

LOOP_LAG_PROBE_S = 0.05

# Top-N census limit. Keeps the attribute payload small enough that Honeycomb
# accepts it (string attrs are bounded) while still surfacing the leaker.
# 15 is enough to comfortably cover the typical thread/task population on a
# warm container plus headroom for the new-and-growing class.
CENSUS_TOP_N = 15


def _thread_name_census() -> Counter[str]:
    """Counter of thread name *prefixes* (split on first hyphen). Per-thread
    suffixes (`asyncio_1`, `asyncio_2`) collapse into the prefix so a leak
    of N threads with the same role aggregates instead of fragmenting."""
    return Counter(t.name.split("-")[0].split("_")[0] for t in threading.enumerate())


def _task_name_census() -> Counter[str]:
    """Counter of asyncio task names. Names come from `name=` arg on
    asyncio.create_task — if a task author didn't set one, it's "Task-N"
    which still groups by prefix here (we strip the numeric suffix)."""
    try:
        tasks = asyncio.all_tasks()
    except RuntimeError:
        return Counter()
    return Counter(_normalize_task_name(t.get_name()) for t in tasks)


def _normalize_task_name(name: str) -> str:
    """Strip trailing -N or _N numeric suffix so per-call tasks aggregate."""
    parts = name.rsplit("-", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return parts[0]
    return name


def _read_proc_stats() -> tuple[object, float, int, int]:
    """Read the psutil process stats. Each of these hits procfs (a blocking
    syscall), so the caller runs this in a worker thread to keep the reads off
    the event loop — otherwise the health monitor itself adds loop lag, which is
    exactly what it's supposed to be measuring. Called once per cycle on the
    same `_proc`, so `cpu_percent(interval=None)`'s since-last-call diff is
    unaffected by the thread hop."""
    mem = _proc.memory_info()
    cpu_pct = _proc.cpu_percent(interval=None)
    thread_count = _proc.num_threads()
    try:
        open_fds = _proc.num_fds()
    except Exception:
        open_fds = -1
    return mem, cpu_pct, thread_count, open_fds


async def _emit_health() -> None:
    """Sample once and emit a single `container.health` span."""
    probe_start = time.monotonic()
    await asyncio.sleep(LOOP_LAG_PROBE_S)
    loop_lag_ms = max(0.0, (time.monotonic() - probe_start - LOOP_LAG_PROBE_S) * 1000)

    mem, cpu_pct, thread_count, open_fds = await asyncio.to_thread(_read_proc_stats)
    g0, g1, g2 = gc.get_count()
    try:
        task_count = len(asyncio.all_tasks())
    except RuntimeError:
        task_count = -1

    thread_census = _thread_name_census()
    task_census = _task_name_census()

    with _tracer.start_as_current_span("container.health") as span:
        span.set_attribute("process.rss_mb", mem.rss / 1024 / 1024)
        span.set_attribute("process.vms_mb", mem.vms / 1024 / 1024)
        span.set_attribute("process.cpu_pct", cpu_pct)
        span.set_attribute("process.thread_count", thread_count)
        span.set_attribute("process.open_fds", open_fds)
        span.set_attribute("asyncio.loop_lag_ms", loop_lag_ms)
        span.set_attribute("asyncio.task_count", task_count)
        span.set_attribute("gc.gen0_count", g0)
        span.set_attribute("gc.gen1_count", g1)
        span.set_attribute("gc.gen2_count", g2)
        # Top-N censuses as JSON strings. Honeycomb's string-contains and
        # JSON-path operators let you GROUP BY individual names from these.
        # Diff two snapshots in time to find the growing name = the leaker.
        span.set_attribute(
            "process.thread_name_top",
            json.dumps(dict(thread_census.most_common(CENSUS_TOP_N))),
        )
        span.set_attribute(
            "asyncio.task_name_top",
            json.dumps(dict(task_census.most_common(CENSUS_TOP_N))),
        )

        # DB pool health is a leading indicator of connection starvation. Emit
        # it on the periodic health cadence so idle_size=0 is observable.
        # Wrapped in try — the pool may
        # not be up yet during early lifespan or already down in shutdown;
        # either state should not crash the health emitter.
        try:
            from utils.database_pool import get_pool_status
            pool_status = get_pool_status()
            # Only emit when we have real numbers (status="unavailable"
            # means the pool never spun up — pre-lifespan / config gap).
            if pool_status.get("status") in ("healthy", "closing"):
                span.set_attribute("db.pool.size", pool_status.get("size", 0))
                span.set_attribute("db.pool.idle_size", pool_status.get("idle_size", 0))
                span.set_attribute("db.pool.max_size", pool_status.get("max_size", 0))
                span.set_attribute("db.pool.is_closing", bool(pool_status.get("is_closing", False)))
        except Exception as e:
            # Never crash the health emitter on pool introspection errors —
            # the emitter is the last line of visibility when the container
            # is degraded.
            logger.debug("container.health db pool status probe failed: %s", e)


async def _health_loop(interval_s: float) -> None:
    _proc.cpu_percent(interval=None)
    while True:
        try:
            await _emit_health()
        except Exception as e:
            logger.warning("container.health emitter failed: %s", e)
        await asyncio.sleep(interval_s)


def start_health_emitter(interval_seconds: float = 3.0) -> None:
    """Start the background health emitter. No-op if Honeycomb is not configured."""
    global _task
    if _task is not None:
        return
    if not os.getenv("HONEYCOMB_API_KEY"):
        return
    loop = asyncio.get_event_loop()
    _task = loop.create_task(_health_loop(interval_seconds))
    logger.info("container.health emitter started (interval=%ss)", interval_seconds)


async def stop_health_emitter() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except asyncio.CancelledError:
        pass
    _task = None
