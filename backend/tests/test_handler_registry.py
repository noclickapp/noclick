"""The receiver's registration seams: handlers, lifecycle handlers, per-dispatch
context and the dispatch span hook. A plain install registers nothing and every
accessor answers "nothing to do"."""

import pytest

from wss.receiver import handler_registry as reg


@pytest.fixture(autouse=True)
def _clean():
    saved = (list(reg._factories), dict(reg._lifecycle), list(reg._context_hooks), list(reg._span_hooks))
    reg.clear()
    yield
    reg.clear()
    reg._factories.extend(saved[0]); reg._lifecycle.update(saved[1])
    reg._context_hooks.extend(saved[2]); reg._span_hooks.extend(saved[3])


def test_nothing_registered_is_a_no_op():
    assert reg.registered_handlers(sio=object()) == {}
    assert reg.lifecycle_handler_keys("API") == []
    assert reg.enter_request_context({"user_data": {}}, "sid") is None
    reg.finish_dispatch_span(span=None, span_start_ms=0)  # no hooks, no error


def test_declining_factories_are_skipped():
    reg.register_handler("a_handler", lambda sio: "A")
    reg.register_handler("b_handler", lambda sio: None)
    assert reg.registered_handlers(sio=object()) == {"a_handler": "A"}


def test_lifecycle_handlers_are_per_environment():
    reg.register_lifecycle_handler("API", "relay_handler")
    assert reg.lifecycle_handler_keys("API") == ["relay_handler"]
    assert reg.lifecycle_handler_keys("WORKER") == []


def test_every_context_hook_runs_and_undoes_in_reverse():
    trail = []
    reg.register_request_context(lambda session, sid: trail.append(("a", session["x"], sid)) or (lambda: trail.append("undo-a")))
    reg.register_request_context(lambda session, sid: None)  # nothing to undo
    reg.register_request_context(lambda session, sid: trail.append(("c", sid)) or (lambda: trail.append("undo-c")))
    undo = reg.enter_request_context({"x": 1}, "sid-1")
    assert trail == [("a", 1, "sid-1"), ("c", "sid-1")]
    undo()
    assert trail[-2:] == ["undo-c", "undo-a"]


def test_a_failing_span_hook_never_breaks_the_dispatch():
    seen = []

    def boom(span, start_ms):
        raise RuntimeError("profiler down")

    reg.register_dispatch_span_hook(boom)
    reg.register_dispatch_span_hook(lambda span, start_ms: seen.append((span, start_ms)))
    reg.finish_dispatch_span("span", 42)
    assert seen == [("span", 42)]
