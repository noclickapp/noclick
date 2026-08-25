"""A loop stall caused by another thread must name that thread's code.

`asyncio.to_thread` does not release the GIL for pure-Python CPU work, so
offloading a parse moves it off the loop's *stack* while still blocking the
loop's *progress*. A main-thread-only sample cannot identify the worker responsible, so the
monitor also captures the likely GIL-holding thread.

These pin that the monitor now identifies the offending thread instead.
"""
import threading
import time

from utils import otel_loop_monitor as olm


def _burn_cpu_in_this_file(stop: threading.Event) -> None:
    """Pure-Python CPU work — holds the GIL, innermost frame stays in this file."""
    total = 0
    while not stop.is_set():
        for i in range(5000):
            total += i * i
    return total


def _park(stop: threading.Event) -> None:
    """Blocks in threading.py — the shape the scan must ignore."""
    stop.wait()


class TestCaptureOffenderThread:
    def test_names_the_thread_burning_cpu(self):
        stop = threading.Event()
        burner = threading.Thread(
            target=_burn_cpu_in_this_file, args=(stop,), name="burner", daemon=True
        )
        burner.start()
        try:
            time.sleep(0.05)  # let it get going
            offender = olm._capture_offender_thread()
        finally:
            stop.set()
            burner.join(timeout=5)

        assert offender is not None, "a CPU-burning thread must be found"
        name, stack = offender
        assert name == "burner"
        top = olm._top_user_frame(stack)
        assert top is not None
        assert top.filename.endswith("test_loop_monitor_gil_attribution.py"), (
            f"expected the burner's own frame, got {top.filename}:{top.lineno}"
        )

    def test_ignores_parked_threads(self):
        """A thread waiting on an Event is not holding the GIL."""
        stop = threading.Event()
        idle = threading.Thread(target=_park, args=(stop,), name="parked", daemon=True)
        idle.start()
        try:
            time.sleep(0.05)
            offender = olm._capture_offender_thread()
        finally:
            stop.set()
            idle.join(timeout=5)

        assert offender is None or offender[0] != "parked", (
            "a thread blocked in Event.wait must never be blamed"
        )


class TestTopUserFrame:
    def test_returns_none_when_only_plumbing_is_on_the_stack(self):
        """The condition that gates the offender scan.

        A stall whose stack is pure asyncio is exactly the starved case — that is
        the case that previously produced an empty `blocking.file_line`.
        """
        import traceback

        fake = [
            traceback.FrameSummary("/usr/lib/python3.12/asyncio/events.py", 84, "_run"),
            traceback.FrameSummary(
                "/usr/lib/python3.12/asyncio/base_events.py", 1971, "_run_once"
            ),
        ]
        assert olm._top_user_frame(fake) is None

    def test_returns_our_frame_when_present(self):
        import traceback

        fake = [
            traceback.FrameSummary("/usr/lib/python3.12/asyncio/events.py", 84, "_run"),
            traceback.FrameSummary("/root/coder/workflow/workflow_xml.py", 427, "parse"),
        ]
        top = olm._top_user_frame(fake)
        assert top is not None and top.lineno == 427


class TestEmittedSpanAttributes:
    """The detected offender has to reach Honeycomb, not just be computed."""

    @staticmethod
    def _capture(monkeypatch):
        emitted = []

        class FakeSpan:
            def __init__(self):
                self.attrs = {}

            def set_attribute(self, key, value):
                self.attrs[key] = value

            def end(self, end_time=None):
                emitted.append(self)

        class FakeTracer:
            def start_span(self, name, start_time=None):
                return FakeSpan()

        monkeypatch.setattr(olm, "_tracer", FakeTracer())
        return emitted

    def test_offender_lands_on_the_span(self, monkeypatch):
        import traceback

        emitted = self._capture(monkeypatch)
        offender_stack = [
            traceback.FrameSummary("/usr/lib/python3.12/threading.py", 1010, "run"),
            traceback.FrameSummary("/root/coder/workflow/workflow_xml.py", 427, "_parse_xml_impl"),
        ]

        olm._emit_block(
            8000.0,
            "<Handle Task.task_wakeup(<Future finished result=None>)>",
            [traceback.FrameSummary("/usr/lib/python3.12/asyncio/events.py", 84, "_run")],
            end_ns=1_700_000_000_000_000_000,
            offender=("ThreadPoolExecutor-0_0", offender_stack),
        )

        assert len(emitted) == 1
        attrs = emitted[0].attrs
        # The incident signature: no file_line of our own on the loop's stack.
        assert "blocking.file_line" not in attrs
        # ...but the cause is now named outright.
        assert attrs["blocking.gil_starved"] is True
        assert attrs["blocking.offender_thread"] == "ThreadPoolExecutor-0_0"
        assert attrs["blocking.offender_file_line"] == "workflow_xml.py:427"
        assert attrs["blocking.offender_module"] == "workflow_xml"
        assert "workflow_xml.py:427" in attrs["blocking.offender_stack"]

    def test_normal_blocks_are_unchanged(self, monkeypatch):
        """No offender means no new attributes — existing spans keep their shape."""
        import traceback

        emitted = self._capture(monkeypatch)
        olm._emit_block(
            250.0,
            "<Handle SomeHandler.run()>",
            [traceback.FrameSummary("/root/wss/handlers/thing.py", 12, "run")],
            end_ns=1_700_000_000_000_000_000,
            offender=None,
        )

        attrs = emitted[0].attrs
        assert attrs["blocking.file_line"] == "thing.py:12"
        assert "blocking.gil_starved" not in attrs
        assert "blocking.offender_thread" not in attrs
