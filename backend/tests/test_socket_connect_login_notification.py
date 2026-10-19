"""The Slack login post runs after the socket handshake, never inside it.

Drives server.py's real connect / update_auth / disconnect handlers over a real
Socket.IO connection: a browser's first request on a page load can't be
answered until connect returns, so connect must not wait on the post's Redis,
database, geo-IP and Slack round-trips.
"""

import asyncio
import socket
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio
import socketio
import uvicorn

import server

USER_ID = "user-1"
USER_DATA = {"email": "person@example.test"}
LOGIN_POST = {"ts": "1760000000.000100", "channel": "C0LOGINS"}


class SlowLoginPost:
    """A login post that lands only when the test releases it."""

    def __init__(self):
        self.release = asyncio.Event()
        self.calls = []

    async def __call__(self, user_id, user_data, client_ip):
        self.calls.append((user_id, user_data, client_ip))
        await self.release.wait()
        return dict(LOGIN_POST)


async def _eventually(probe, timeout=5.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not await probe():
        assert loop.time() < deadline, "condition never held"
        await asyncio.sleep(0.01)


async def _awaited(mock):
    return mock.await_count > 0


@pytest_asyncio.fixture
async def live(monkeypatch):
    sio = socketio.AsyncServer(async_mode="asgi", transports=["websocket"])
    for event in ("connect", "disconnect", "update_auth"):
        sio.on(event, getattr(server, event))
    monkeypatch.setattr(server, "sio", sio)
    monkeypatch.setattr(
        server, "verify_socket_token", AsyncMock(return_value=(USER_ID, dict(USER_DATA)))
    )
    # Per-handler provisioning is not what's under test (it reaches databases).
    monkeypatch.setattr(server.socketio_proxy, "setup_user", AsyncMock())
    monkeypatch.setattr(server.socketio_proxy, "cleanup_user", AsyncMock())
    monkeypatch.setattr(server, "login_notifications_enabled", lambda: True)
    post = SlowLoginPost()
    monkeypatch.setattr(server, "send_login_notification", post)
    mark_complete = AsyncMock(return_value=True)
    monkeypatch.setattr(server, "mark_session_complete", mark_complete)

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    web = uvicorn.Server(uvicorn.Config(socketio.ASGIApp(sio), log_level="error", lifespan="off"))
    serving = asyncio.create_task(web.serve(sockets=[sock]))
    while not web.started:
        await asyncio.sleep(0.01)
    client = socketio.AsyncClient()
    try:
        yield {
            "url": f"http://127.0.0.1:{sock.getsockname()[1]}",
            "sio": sio,
            "client": client,
            "post": post,
            "mark_complete": mark_complete,
        }
    finally:
        # A handler still waiting on the post must not hold the server open.
        post.release.set()
        await client.disconnect()
        await sio.shutdown()
        web.should_exit = True
        await asyncio.wait_for(serving, 10)
        # engineio leaves each closed socket's ping timer asleep for ping_interval.
        for task in asyncio.all_tasks():
            if task.get_coro().__qualname__ == "AsyncSocket._send_ping":
                task.cancel()


async def _connect(live):
    await live["client"].connect(
        live["url"],
        auth={"token": "access-token"},
        headers={"X-Forwarded-For": "203.0.113.7"},
        transports=["websocket"],
        wait_timeout=5,
    )
    return live["client"].get_sid()


async def test_connect_returns_before_the_login_post_and_threads_the_session_once_it_lands(live):
    sid = await _connect(live)
    sio, post = live["sio"], live["post"]

    # Accepted while the post is still in flight.
    assert post.calls == [(USER_ID, USER_DATA, "203.0.113.7")]
    assert not post.release.is_set()
    assert (await sio.get_session(sid)).get("slack_thread_ts") is None

    # Something saves the session while the post is in flight; attaching the
    # thread must keep it.
    refreshed = {"email": "person@example.test", "user_metadata": {"name": "Person"}}
    server.verify_socket_token.return_value = (USER_ID, refreshed)
    assert (await live["client"].call("update_auth", {"token": "fresh"}))["success"] is True

    post.release.set()

    async def threaded():
        return (await sio.get_session(sid)).get("slack_thread_ts") == LOGIN_POST["ts"]

    await _eventually(threaded)
    session = await sio.get_session(sid)
    assert session["slack_channel"] == LOGIN_POST["channel"]
    assert session["user_id"] == USER_ID
    assert session["user_data"] == refreshed

    # The disconnect closes the thread it now finds in the session.
    await live["client"].disconnect()
    await _eventually(lambda: _awaited(live["mark_complete"]))
    live["mark_complete"].assert_awaited_once_with(LOGIN_POST["channel"], LOGIN_POST["ts"])


async def test_a_post_that_lands_after_disconnect_still_closes_its_thread(live):
    sid = await _connect(live)
    sio = live["sio"]

    await live["client"].disconnect()
    await _eventually(lambda: _awaited(server.socketio_proxy.cleanup_user))
    assert not sio.manager.is_connected(sid, "/")
    # Disconnect found no thread to close yet.
    live["mark_complete"].assert_not_awaited()

    live["post"].release.set()
    await _eventually(lambda: _awaited(live["mark_complete"]))
    live["mark_complete"].assert_awaited_once_with(LOGIN_POST["channel"], LOGIN_POST["ts"])


async def test_without_login_notifications_connect_never_reads_the_client_address(live, monkeypatch):
    monkeypatch.setattr(server, "login_notifications_enabled", lambda: False)
    extract = Mock(return_value="203.0.113.7")
    monkeypatch.setattr(server, "extract_client_ip", extract)

    sid = await _connect(live)

    assert (await live["sio"].get_session(sid))["user_id"] == USER_ID
    extract.assert_not_called()
    assert live["post"].calls == []
