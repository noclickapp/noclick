from unittest.mock import AsyncMock, MagicMock

import pytest

import utils.execution_stop as execution_stop

pytestmark = pytest.mark.asyncio






async def test_local_stop_client_uses_pending_stop_capable_hub(monkeypatch):
    hub = MagicMock()
    monkeypatch.setattr(execution_stop, "get_local_relay_hub", lambda: hub)

    sent = await execution_stop.request_execution_stops(
        "wf-1", "user-1", ["exec-1", "exec-2"]
    )

    assert sent == 2
    assert [call.args[0] for call in hub.fire_stop.call_args_list] == [
        "exec-1",
        "exec-2",
    ]


async def test_waits_until_running_execution_becomes_terminal(monkeypatch):
    running = AsyncMock(side_effect=[["exec-1"], []])
    request_stops = AsyncMock(return_value=1)
    monkeypatch.setattr(execution_stop, "_running_execution_ids", running)
    monkeypatch.setattr(execution_stop, "request_execution_stops", request_stops)
    monkeypatch.setattr(execution_stop.asyncio, "sleep", AsyncMock())

    remaining = await execution_stop.stop_running_workflow_executions(
        MagicMock(),
        "wf-1",
        "user-1",
        timeout_s=1,
    )

    assert remaining == []
    request_stops.assert_awaited_once_with("wf-1", "user-1", ["exec-1"])


async def test_returns_running_ids_when_stop_deadline_expires(monkeypatch):
    running = AsyncMock(return_value=["exec-1"])
    request_stops = AsyncMock(return_value=1)
    monkeypatch.setattr(execution_stop, "_running_execution_ids", running)
    monkeypatch.setattr(execution_stop, "request_execution_stops", request_stops)

    remaining = await execution_stop.stop_running_workflow_executions(
        MagicMock(),
        "wf-1",
        "user-1",
        timeout_s=0,
    )

    assert remaining == ["exec-1"]
    request_stops.assert_awaited_once()
