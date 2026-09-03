"""The lifecycle registry: what a platform hangs onto the engine's lifespan and
socket sessions, and how the engine runs it — ordered start-up that fails
loudly, best-effort shutdown in reverse, no-ops when nothing registered."""

import asyncio

import pytest

from utils import lifecycle


@pytest.fixture(autouse=True)
def _clean_registry():
    lifecycle.clear()
    yield
    lifecycle.clear()


async def test_nothing_registered_is_a_no_op():
    await lifecycle.run_startup_hooks("boot")
    await lifecycle.run_startup_hooks("ready")
    await lifecycle.run_shutdown_hooks("drain")
    await lifecycle.run_shutdown_hooks("final")
    await lifecycle.run_socket_connect_hooks({}, {})
    await lifecycle.run_socket_auth_update_hooks("sid", {}, {}, None)


async def test_startup_runs_in_registration_order_and_awaits_coroutines():
    seen = []
    lifecycle.register_startup_hook(lambda: seen.append("a"), phase="boot")

    async def b():
        seen.append("b")
    lifecycle.register_startup_hook(b, phase="boot")
    lifecycle.register_startup_hook(lambda: seen.append("ready"), phase="ready")
    await lifecycle.run_startup_hooks("boot")
    assert seen == ["a", "b"]
    await lifecycle.run_startup_hooks("ready")
    assert seen == ["a", "b", "ready"]


async def test_a_failing_startup_hook_stops_the_boot():
    def broken():
        raise RuntimeError("profiler missing")
    lifecycle.register_startup_hook(broken, phase="boot")
    with pytest.raises(RuntimeError, match="profiler missing"):
        await lifecycle.run_startup_hooks("boot")


async def test_shutdown_runs_in_reverse_and_survives_failures_and_timeouts():
    seen = []
    lifecycle.register_shutdown_hook(lambda: seen.append("first"), phase="final")

    async def hangs():
        await asyncio.sleep(10)
    lifecycle.register_shutdown_hook(hangs, phase="final", timeout=0.05, name="hangs")

    def breaks():
        raise RuntimeError("no")
    lifecycle.register_shutdown_hook(breaks, phase="final")
    lifecycle.register_shutdown_hook(lambda: seen.append("last"), phase="final")
    await lifecycle.run_shutdown_hooks("final")
    assert seen == ["last", "first"]


async def test_socket_hooks_see_and_shape_the_session():
    async def connect(session_data, auth):
        session_data["platform_key"] = auth.get("token")

    async def update(sid, session, data, proxy):
        session["refreshed"] = (sid, data["v"], proxy)
    lifecycle.register_socket_connect_hook(connect)
    lifecycle.register_socket_auth_update_hook(update)
    session = {"user_id": "u1"}
    await lifecycle.run_socket_connect_hooks(session, {"token": "t"})
    assert session["platform_key"] == "t"
    await lifecycle.run_socket_auth_update_hooks("sid-1", session, {"v": 2}, "proxy")
    assert session["refreshed"] == ("sid-1", 2, "proxy")


def test_unknown_phases_are_rejected():
    with pytest.raises(ValueError):
        lifecycle.register_startup_hook(lambda: None, phase="later")
    with pytest.raises(ValueError):
        lifecycle.register_shutdown_hook(lambda: None, phase="sometime")


def test_registered_names_are_reported_by_phase():
    lifecycle.register_startup_hook(lambda: None, phase="boot", name="profiler")
    lifecycle.register_shutdown_hook(lambda: None, phase="drain", name="monitor")
    names = lifecycle.registered_hook_names()
    assert names["startup:boot"] == ["profiler"] and names["shutdown:drain"] == ["monitor"]
    assert names["startup:ready"] == [] and names["socket_connect"] == []
