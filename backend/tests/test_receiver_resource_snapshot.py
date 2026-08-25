"""The per-event resource snapshot must not scandir /proc/self/fd.

psutil's ``num_fds()`` (open-fd count) reads the whole /proc/self/fd directory.
Running it twice per socket event adds filesystem work to the receiver hot path,
so fd trends stay in the periodic process-health sampler. rss / task / thread
deltas (the latter backs the
resource-leak trigger) stay.
"""

from unittest.mock import patch

from wss.receiver import receiver


class _FakeSpan:
    def __init__(self):
        self.attrs = {}

    def set_attribute(self, key, value):
        self.attrs[key] = value


def test_snapshot_does_not_call_num_fds():
    with patch.object(
        receiver._proc, "num_fds",
        side_effect=AssertionError("num_fds() scandir must not run on the per-event hot path"),
    ):
        snap = receiver._snapshot_resources()
    assert set(snap) == {"rss_bytes", "task_count", "thread_count"}
    assert "fd_count" not in snap


def test_stamp_delta_records_rss_task_thread_but_not_fd():
    before = {"rss_bytes": 1024, "task_count": 5, "thread_count": 10}
    after = {"rss_bytes": 1024 + 2048, "task_count": 7, "thread_count": 12}
    with patch.object(receiver, "_snapshot_resources", return_value=after):
        span = _FakeSpan()
        receiver._stamp_resource_delta(span, before)

    assert span.attrs["resource.rss_delta_kb"] == 2.0
    assert span.attrs["resource.task_delta"] == 2
    assert span.attrs["resource.thread_delta"] == 2
    # The leak trigger depends on thread_delta; fd_delta is intentionally gone.
    assert "resource.fd_delta" not in span.attrs
