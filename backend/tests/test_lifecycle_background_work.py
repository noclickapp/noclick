"""NOCLICK_BACKGROUND_WORK=off: a process starts none of the startup hooks that claim shared work."""
import pytest

from utils import lifecycle


@pytest.fixture
def started(monkeypatch):
    for phase in lifecycle.STARTUP_PHASES:
        monkeypatch.setitem(lifecycle._startup, phase, [])
    ran = []
    lifecycle.register_startup_hook(lambda: ran.append("telemetry"), name="telemetry")
    lifecycle.register_startup_hook(lambda: ran.append("claims"), name="claims", background=True)
    return ran


async def test_background_hooks_start_by_default(monkeypatch, started):
    monkeypatch.delenv("NOCLICK_BACKGROUND_WORK", raising=False)
    await lifecycle.run_startup_hooks("ready")
    assert started == ["telemetry", "claims"]


async def test_background_hooks_are_skipped_when_background_work_is_off(monkeypatch, started):
    monkeypatch.setenv("NOCLICK_BACKGROUND_WORK", "off")
    await lifecycle.run_startup_hooks("ready")
    assert started == ["telemetry"]
    assert not lifecycle.background_work_enabled()
