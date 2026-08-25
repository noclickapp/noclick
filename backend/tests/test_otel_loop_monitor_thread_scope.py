"""Regression tests for the otel-loop-monitor thread-scoping fix (2026-05-10).

The loop monitor patches ``asyncio.Handle._run`` globally, so callbacks on
*every* asyncio loop in the process flow through ``_patched_run`` — main
API loop, wahooks docket Redis pubsub poller, database_pool worker,
OpenHands sub-loops, etc. Before this fix, the first thread to call any
asyncio.Handle._run would set ``_main_thread_id``, and subsequent
callbacks on background loops were being measured and reported as
``event_loop.block`` spans, indistinguishable from real main-loop blocks
in Honeycomb.

These tests pin the new contract: only callbacks on the thread that
called ``init_loop_monitor`` get instrumented; everything else is a
pass-through to the original ``asyncio.Handle._run``.
"""

import asyncio
import os
import threading
import time
from unittest.mock import patch

import pytest


@pytest.fixture
def fresh_monitor(monkeypatch):
    """Reset module state and restore asyncio.Handle._run around each test.

    The monitor mutates global module state and the global asyncio.Handle
    class, so without this fixture the first test would leave the patch
    installed and subsequent tests would observe stale state.
    """
    monkeypatch.setenv("HONEYCOMB_API_KEY", "test-key-for-monitor-init")

    from utils import otel_loop_monitor

    saved_handle_run = asyncio.Handle._run
    saved_initialized = otel_loop_monitor._initialized
    saved_main_thread_id = otel_loop_monitor._main_thread_id

    otel_loop_monitor._initialized = False
    otel_loop_monitor._main_thread_id = None
    otel_loop_monitor._current_started_at = None
    otel_loop_monitor._pending_stack = None

    yield otel_loop_monitor

    asyncio.Handle._run = saved_handle_run
    otel_loop_monitor._initialized = saved_initialized
    otel_loop_monitor._main_thread_id = saved_main_thread_id
    otel_loop_monitor._current_started_at = None
    otel_loop_monitor._pending_stack = None


def _make_handle(loop, fn):
    """Build a real asyncio.Handle whose `_run` will execute `fn`."""
    return asyncio.Handle(fn, (), loop)


def test_init_captures_calling_thread_as_main(fresh_monitor):
    loop = asyncio.new_event_loop()
    try:
        fresh_monitor.init_loop_monitor(loop)
    finally:
        loop.close()

    assert fresh_monitor._initialized is True
    assert fresh_monitor._main_thread_id == threading.get_ident()
    assert asyncio.Handle._run is fresh_monitor._patched_run


def test_callback_on_main_thread_is_instrumented(fresh_monitor):
    """A slow callback on the init thread must produce an emit_block call."""
    loop = asyncio.new_event_loop()
    fresh_monitor.init_loop_monitor(loop)

    with patch.object(fresh_monitor, "_emit_block") as emit:
        # threshold is 100ms by default — sleep 150ms to exceed it
        handle = _make_handle(loop, lambda: time.sleep(0.15))
        handle._run()

    loop.close()
    assert emit.call_count == 1, "main-thread slow callback should emit a block span"
    duration_ms = emit.call_args.args[0]
    assert duration_ms >= 100


def test_callback_on_background_thread_is_passthrough(fresh_monitor):
    """A slow callback on a background thread must NOT emit a block span.

    This is the load-bearing assertion. A slow callback on a background
    event loop must not be emitted as a main-loop block. ``_patched_run``
    early-exits when
    ``threading.get_ident() != _main_thread_id`` and the callback runs
    via ``_orig_handle_run`` with no instrumentation overhead.
    """
    main_loop = asyncio.new_event_loop()
    fresh_monitor.init_loop_monitor(main_loop)

    bg_loop = asyncio.new_event_loop()
    callback_ran = threading.Event()

    def bg_callback():
        # Sleep well past the 100ms threshold to prove threshold isn't the gate
        time.sleep(0.15)
        callback_ran.set()

    with patch.object(fresh_monitor, "_emit_block") as emit:
        def run_in_bg():
            handle = _make_handle(bg_loop, bg_callback)
            handle._run()

        t = threading.Thread(target=run_in_bg, name="bg-loop-thread")
        t.start()
        t.join(timeout=5)

    main_loop.close()
    bg_loop.close()

    assert callback_ran.is_set(), "background callback should still execute"
    assert emit.call_count == 0, (
        "background-thread slow callbacks must not emit event_loop.block "
        "spans — they're not on the main loop"
    )


def test_reinit_from_different_thread_raises(fresh_monitor):
    """Defensive guard: a second init from a different thread must fail loudly.

    Silently re-binding ``_main_thread_id`` would mis-attribute spans
    for the rest of the process's lifetime — the kind of bug that hides
    for a week before someone notices the daily report is wrong.
    """
    loop = asyncio.new_event_loop()
    fresh_monitor.init_loop_monitor(loop)

    error_box: dict = {}

    def reinit_from_other_thread():
        try:
            fresh_monitor.init_loop_monitor(loop)
        except RuntimeError as e:
            error_box["err"] = e

    t = threading.Thread(target=reinit_from_other_thread)
    t.start()
    t.join(timeout=2)

    loop.close()

    assert "err" in error_box, "re-init from a different thread must raise"
    assert "thread" in str(error_box["err"]).lower()


def test_reinit_from_same_thread_is_idempotent(fresh_monitor):
    """A second init from the same thread is a normal idempotent no-op."""
    loop = asyncio.new_event_loop()
    fresh_monitor.init_loop_monitor(loop)
    main_tid_before = fresh_monitor._main_thread_id

    fresh_monitor.init_loop_monitor(loop)  # should not raise

    loop.close()
    assert fresh_monitor._main_thread_id == main_tid_before


def test_no_op_when_honeycomb_key_unset(monkeypatch):
    """Without HONEYCOMB_API_KEY the monitor should not patch anything."""
    monkeypatch.delenv("HONEYCOMB_API_KEY", raising=False)

    from utils import otel_loop_monitor

    saved_handle_run = asyncio.Handle._run
    saved_initialized = otel_loop_monitor._initialized
    saved_main_thread_id = otel_loop_monitor._main_thread_id

    otel_loop_monitor._initialized = False
    otel_loop_monitor._main_thread_id = None

    try:
        loop = asyncio.new_event_loop()
        otel_loop_monitor.init_loop_monitor(loop)
        loop.close()

        assert otel_loop_monitor._initialized is False
        assert otel_loop_monitor._main_thread_id is None
        assert asyncio.Handle._run is saved_handle_run
    finally:
        asyncio.Handle._run = saved_handle_run
        otel_loop_monitor._initialized = saved_initialized
        otel_loop_monitor._main_thread_id = saved_main_thread_id
