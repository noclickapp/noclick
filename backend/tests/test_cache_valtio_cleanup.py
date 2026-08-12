from unittest.mock import AsyncMock, MagicMock

import pytest

from wss.handlers.cache_valtio_handler import CacheValtioHandler


def _handler(monkeypatch):
    monkeypatch.setattr(
        "wss.handlers.cache_valtio_handler.redis.from_url", MagicMock()
    )
    sio = MagicMock()
    ypy_handler = MagicMock()
    ypy_handler.cleanup_synced_state = AsyncMock()
    return CacheValtioHandler(sio, ypy_handler), sio, ypy_handler


@pytest.mark.asyncio
async def test_cleanup_releases_local_state_after_session_eviction(monkeypatch):
    handler, sio, ypy_handler = _handler(monkeypatch)
    sio.get_session = AsyncMock(side_effect=KeyError("Session not found"))
    timer = MagicMock()
    handler.upload_timers["sid-1"] = timer

    await handler.cleanup_user("sid-1")

    timer.cancel.assert_called_once_with()
    assert "sid-1" not in handler.upload_timers
    ypy_handler.cleanup_synced_state.assert_awaited_once_with("sid-1")


@pytest.mark.asyncio
async def test_cleanup_releases_yjs_state_without_redis(monkeypatch):
    handler, _sio, ypy_handler = _handler(monkeypatch)
    handler.redis_client = None
    timer = MagicMock()
    handler.upload_timers["sid-1"] = timer

    await handler.cleanup_user("sid-1")

    timer.cancel.assert_called_once_with()
    assert "sid-1" not in handler.upload_timers
    ypy_handler.cleanup_synced_state.assert_awaited_once_with("sid-1")
