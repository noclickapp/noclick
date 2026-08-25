"""Detect event-loop blocking and emit a span per slow callback.

Patches `asyncio.Handle._run` to time every callback. Callbacks that exceed
HEAVY_THRESHOLD_MS produce an `event_loop.block` span attached to whatever
parent span is active in the callback's context, so per-handler attribution
is automatic.

A watchdog thread captures the main thread's stack while the callback is
still running, so the span carries `blocking.module` and `blocking.file_line`
attributes pointing at the actual blocking code, not just the await point
that asyncio records in the callback repr.

When that stack holds none of our frames the loop was starved rather than
busy — almost always another thread holding the GIL, which `asyncio.to_thread`
does not prevent for pure-Python CPU work. The watchdog then scans for the
offending thread and adds `blocking.gil_starved` + `blocking.offender_*`, so
those stalls name their likely cause instead of arriving as a bare
`Task.task_wakeup` with no attribution.

Scope: only the main API asyncio loop is measured. The patch on
`asyncio.Handle._run` is global (Python only allows one), so callbacks on
background event loops still flow through `_patched_run`, but they short-circuit
to `_orig_handle_run` without instrumentation. Without this gate, slow
background-loop callbacks produce false `event_loop.block` spans that look
identical to main-loop blocks even while main-loop lag remains low.
"""
import asyncio
import logging
import os
import sys
import threading
import time
import traceback
from typing import Optional

from opentelemetry import trace

logger = logging.getLogger(__name__)

THRESHOLD_S = float(os.getenv("OTEL_LOOP_MONITOR_THRESHOLD_MS", "100")) / 1000
SAMPLE_INTERVAL_S = float(os.getenv("OTEL_LOOP_MONITOR_SAMPLE_INTERVAL_MS", "50")) / 1000
MAX_STACK_FRAMES = int(os.getenv("OTEL_LOOP_MONITOR_MAX_STACK_FRAMES", "50"))
SKIP_FILE_FRAGMENTS = ("/asyncio/", "/site-packages/opentelemetry/", "otel_loop_monitor.py")

# Innermost-frame locations that mean a thread is parked rather than burning
# CPU. Used to find which *other* thread is holding the GIL when the loop
# stalls with nothing of our own on its stack (see _capture_offender_thread).
IDLE_FRAME_FRAGMENTS = (
    "/threading.py",
    "/selectors.py",
    "/queue.py",
    "/socket.py",
    "/ssl.py",
    "/asyncio/",
    "otel_loop_monitor.py",
)
# Bound the cost of the offender scan on containers with many threads.
MAX_THREADS_SCANNED = int(os.getenv("OTEL_LOOP_MONITOR_MAX_THREADS", "64"))

_tracer = trace.get_tracer("noclick.loop")
_orig_handle_run = asyncio.Handle._run

_main_thread_id: Optional[int] = None
_current_started_at: Optional[float] = None
_pending_stack: Optional[list] = None
_pending_offender: Optional[tuple] = None
_lock = threading.Lock()
_initialized = False


def _top_user_frame(stack: Optional[list]):
    """Innermost frame that is ours, skipping asyncio/otel plumbing."""
    if not stack:
        return None
    user_frames = [f for f in stack if not any(s in f.filename for s in SKIP_FILE_FRAGMENTS)]
    return user_frames[-1] if user_frames else None


def _capture_offender_thread() -> Optional[tuple]:
    """Find the thread most likely holding the GIL. Returns (name, stack) or None.

    When the loop stalls but the main thread's own stack has nothing of ours on
    it, the loop wasn't running our code — it was starved. The usual cause is
    another thread holding the GIL for CPU-bound pure-Python work, which
    `asyncio.to_thread` does NOT prevent: offloading a regex or a parse moves it
    off the loop's *stack* while still blocking the loop's *progress*.

    Without this, such stalls record no `blocking.file_line`, leaving the
    responsible worker unattributed.

    Heuristic, not proof: we take the innermost non-parked thread, preferring one
    in our own code over site-packages. Good enough to point an investigation at
    the likely function while clearly marking the result as heuristic.
    """
    try:
        frames_by_tid = sys._current_frames()
        names_by_tid = {t.ident: t.name for t in threading.enumerate()}
        watchdog_tid = threading.get_ident()

        busy = []
        for tid, frame in list(frames_by_tid.items())[:MAX_THREADS_SCANNED]:
            if tid in (_main_thread_id, watchdog_tid):
                continue
            # lookup_lines=False keeps this off the filesystem — we only ever
            # read filename/lineno, and this runs while the loop is stalled.
            stack = traceback.StackSummary.extract(
                traceback.walk_stack(frame), lookup_lines=False
            )
            if not stack:
                continue
            # walk_stack yields innermost-first; match extract_stack's ordering.
            stack = list(reversed(stack))
            if any(s in stack[-1].filename for s in IDLE_FRAME_FRAGMENTS):
                continue  # parked in a wait/select/queue — not burning CPU
            busy.append((names_by_tid.get(tid, f"tid-{tid}"), stack))

        if not busy:
            return None
        # Several threads can be mid-work; prefer one running our own code, since
        # "which of our functions ate the loop" is the answer we actually want.
        for name, stack in busy:
            top = _top_user_frame(stack)
            if top is not None and "/site-packages/" not in top.filename:
                return name, stack
        return busy[0]
    except Exception:
        pass
    return None


def _emit_block(
    duration_ms: float,
    repr_str: str,
    stack: Optional[list],
    end_ns: int,
    offender: Optional[tuple] = None,
) -> None:
    """Run inside the callback's contextvars context so the parent span resolves."""
    file_line = ""
    module_hint = ""
    stack_str = ""
    is_compression = False
    if stack:
        top = _top_user_frame(stack)
        if top is not None:
            module_hint = os.path.basename(top.filename).rsplit(".", 1)[0]
            file_line = f"{os.path.basename(top.filename)}:{top.lineno}"
        stack_str = " | ".join(
            f"{os.path.basename(f.filename)}:{f.lineno}"
            for f in stack[-MAX_STACK_FRAMES:]
        )
        # Tag compression-attributed blocks so telemetry can slice them out
        # separately. Per-event attribution would require threading additional
        # context through the websocket send path.
        is_compression = any('permessage_deflate' in f.filename for f in stack)

    start_ns = end_ns - int(duration_ms * 1_000_000)
    span = _tracer.start_span("event_loop.block", start_time=start_ns)
    span.set_attribute("blocking.duration_ms", duration_ms)
    span.set_attribute("blocking.callback_repr", repr_str[:300])
    if _main_thread_id is not None:
        span.set_attribute("loop.thread_id", _main_thread_id)
    if is_compression:
        span.set_attribute("blocking.is_compression", True)
    if file_line:
        span.set_attribute("blocking.file_line", file_line)
    if module_hint:
        span.set_attribute("blocking.module", module_hint)
    if stack_str:
        span.set_attribute("blocking.stack", stack_str)
    if offender is not None:
        # The loop had none of our code on it, so it was starved rather than
        # busy. Name the thread that was actually holding the GIL — querying
        # `blocking.offender_file_line` is what turns this class of stall from a
        # an unattributed stall into a directly queryable span.
        offender_name, offender_stack = offender
        span.set_attribute("blocking.gil_starved", True)
        span.set_attribute("blocking.offender_thread", offender_name)
        offender_top = _top_user_frame(offender_stack)
        if offender_top is not None:
            span.set_attribute(
                "blocking.offender_file_line",
                f"{os.path.basename(offender_top.filename)}:{offender_top.lineno}",
            )
            span.set_attribute(
                "blocking.offender_module",
                os.path.basename(offender_top.filename).rsplit(".", 1)[0],
            )
        span.set_attribute(
            "blocking.offender_stack",
            " | ".join(
                f"{os.path.basename(f.filename)}:{f.lineno}"
                for f in offender_stack[-MAX_STACK_FRAMES:]
            ),
        )
    span.end(end_time=end_ns)


def _patched_run(self):
    global _current_started_at, _pending_stack, _pending_offender
    if _main_thread_id is None or threading.get_ident() != _main_thread_id:
        return _orig_handle_run(self)
    t0 = time.monotonic()
    with _lock:
        _current_started_at = t0
        _pending_stack = None
        _pending_offender = None
    try:
        return _orig_handle_run(self)
    finally:
        dt = time.monotonic() - t0
        with _lock:
            stack = _pending_stack
            offender = _pending_offender
            _current_started_at = None
            _pending_stack = None
            _pending_offender = None
        if dt >= THRESHOLD_S:
            try:
                end_ns = time.time_ns()
                self._context.run(
                    _emit_block, dt * 1000, repr(self), stack, end_ns, offender
                )
            except Exception as exc:
                logger.debug("loop monitor emit failed: %s", exc)


def _watchdog_loop() -> None:
    global _pending_stack, _pending_offender
    while True:
        time.sleep(SAMPLE_INTERVAL_S)
        with _lock:
            started = _current_started_at
            already_captured = _pending_stack is not None
        if started is None or already_captured:
            continue
        if (time.monotonic() - started) < THRESHOLD_S:
            continue
        try:
            frame = sys._current_frames().get(_main_thread_id)
            if frame is None:
                continue
            stack = traceback.extract_stack(frame)
        except Exception:
            continue
        # Nothing of ours on the loop's stack means it wasn't running our code,
        # so the stall came from elsewhere — scan for the thread holding the GIL.
        # Gated on that check so the multi-thread walk only runs for the stalls
        # that would otherwise be unattributable.
        offender = None
        if _top_user_frame(stack) is None:
            offender = _capture_offender_thread()
        with _lock:
            if _current_started_at == started and _pending_stack is None:
                _pending_stack = stack
                _pending_offender = offender


def init_loop_monitor(loop: asyncio.AbstractEventLoop) -> None:
    """Install the asyncio.Handle._run wrapper and start the watchdog thread.

    Must be called from the thread that owns `loop` (i.e. from inside a
    coroutine running on the main API loop, typically from FastAPI's
    lifespan startup). The calling thread's id is captured as the main
    thread id and used to gate measurement so callbacks on background
    asyncio loops don't get reported as main-loop blocks.

    No-op if HONEYCOMB_API_KEY is unset (matches init_otel gating).
    Idempotent — but re-init from a different thread raises loudly to
    surface accidental wiring errors.
    """
    global _initialized, _main_thread_id
    current_tid = threading.get_ident()
    if _initialized:
        if _main_thread_id is not None and current_tid != _main_thread_id:
            raise RuntimeError(
                f"otel-loop-monitor re-init from thread {current_tid} "
                f"but already initialized on thread {_main_thread_id} — "
                "this would silently mis-attribute event_loop.block spans"
            )
        return
    if not os.getenv("HONEYCOMB_API_KEY"):
        return
    _main_thread_id = current_tid
    asyncio.Handle._run = _patched_run
    t = threading.Thread(target=_watchdog_loop, name="otel-loop-monitor", daemon=True)
    t.start()
    _initialized = True
    logger.info(
        "otel-loop-monitor installed (threshold=%.0fms, sample=%.0fms, main_thread_id=%d, loop=%r)",
        THRESHOLD_S * 1000,
        SAMPLE_INTERVAL_S * 1000,
        _main_thread_id,
        loop,
    )
