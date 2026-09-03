"""The Discord Gateway client against a scripted gateway on localhost.

Discord's contract, not a mock of it: HELLO → IDENTIFY/RESUME → READY/RESUMED,
heartbeats carrying the last sequence, op 7 → resume, op 9 (false) →
re-identify, a zombied socket (no heartbeat ACK) → resumable close, a fatal
close code → stop with a message that names the fix.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

import pytest
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from utils import discord_gateway as gw
from utils.discord_gateway import (
    INTENT_GUILD_MESSAGES,
    INTENT_GUILDS,
    DiscordGatewayClient,
    GatewaySession,
    MemorySessionStore,
)

pytestmark = pytest.mark.asyncio

INTENTS = INTENT_GUILDS | INTENT_GUILD_MESSAGES


class Conn:
    """One accepted connection: what the client sent, and a way to script it."""

    def __init__(self, ws) -> None:
        self.ws = ws
        self.identify: Optional[Dict[str, Any]] = None
        self.resume: Optional[Dict[str, Any]] = None
        self.heartbeats: List[Any] = []
        self.handshaken = asyncio.Event()
        self.closed = asyncio.Event()
        self.close_code: Optional[int] = None

    async def send(self, frame: Dict[str, Any]) -> None:
        await self.ws.send(json.dumps(frame))

    async def dispatch(self, t: str, d: Dict[str, Any], s: int) -> None:
        await self.send({"op": 0, "t": t, "d": d, "s": s})

    async def close(self, code: int) -> None:
        await self.ws.close(code=code)


class FakeGateway:
    def __init__(self, *, heartbeat_ms: int = 100, ack_heartbeats: bool = True,
                 close_after_hello: Optional[int] = None) -> None:
        self.heartbeat_ms = heartbeat_ms
        self.ack_heartbeats = ack_heartbeats
        self.close_after_hello = close_after_hello
        self.connections: List[Conn] = []
        self.seq = 0
        self.url = ""

    async def __aenter__(self):
        self._server = await serve(self._handler, "127.0.0.1", 0)
        port = self._server.sockets[0].getsockname()[1]
        self.url = f"ws://127.0.0.1:{port}"
        return self

    async def __aexit__(self, *exc):
        self._server.close()
        await self._server.wait_closed()

    async def _handler(self, ws) -> None:
        conn = Conn(ws)
        self.connections.append(conn)
        await conn.send({"op": gw.OP_HELLO, "d": {"heartbeat_interval": self.heartbeat_ms}})
        if self.close_after_hello:
            await ws.close(code=self.close_after_hello, reason="scripted")
            conn.close_code = self.close_after_hello
            conn.closed.set()
            return
        try:
            async for raw in ws:
                frame = json.loads(raw)
                op = frame.get("op")
                if op == gw.OP_IDENTIFY:
                    conn.identify = frame["d"]
                    self.seq += 1
                    await conn.dispatch("READY", {
                        "session_id": f"sess-{len(self.connections)}",
                        "resume_gateway_url": self.url,
                        "user": {"id": "bot-1", "username": "noclick"},
                        "application": {"id": "app-1"},
                        "guilds": [{"id": "g1"}, {"id": "g2"}],
                    }, self.seq)
                    conn.handshaken.set()
                elif op == gw.OP_RESUME:
                    conn.resume = frame["d"]
                    self.seq += 1
                    await conn.dispatch("RESUMED", {}, self.seq)
                    conn.handshaken.set()
                elif op == gw.OP_HEARTBEAT:
                    conn.heartbeats.append(frame.get("d"))
                    if self.ack_heartbeats:
                        await conn.send({"op": gw.OP_HEARTBEAT_ACK})
        except ConnectionClosed:
            pass
        finally:
            conn.close_code = ws.close_code
            conn.closed.set()

    async def connection(self, index: int, timeout: float = 5.0) -> Conn:
        """The index-th accepted connection, once its handshake completed."""
        async def _wait():
            while len(self.connections) <= index:
                await asyncio.sleep(0.01)
            await self.connections[index].handshaken.wait()
            return self.connections[index]
        return await asyncio.wait_for(_wait(), timeout)


async def _until(predicate, timeout: float = 5.0) -> None:
    async def _wait():
        while not predicate():
            await asyncio.sleep(0.01)
    await asyncio.wait_for(_wait(), timeout)


class Recorder:
    def __init__(self) -> None:
        self.events: List[tuple] = []

    async def __call__(self, event_type: str, data: Dict[str, Any]) -> None:
        self.events.append((event_type, data))


@pytest.fixture(autouse=True)
def fast_reconnects(monkeypatch):
    monkeypatch.setattr(gw, "RECONNECT_BACKOFF_MIN_S", 0.01)
    monkeypatch.setattr(gw, "RECONNECT_BACKOFF_MAX_S", 0.05)
    monkeypatch.setattr(gw, "INVALID_SESSION_WAIT_S", (0.0, 0.0))


def _client(server: FakeGateway, recorder: Recorder, store=None, **kwargs) -> DiscordGatewayClient:
    return DiscordGatewayClient(
        "Bot secret-token",
        intents=INTENTS,
        on_dispatch=recorder,
        session_store=store,
        gateway_url=server.url,
        **kwargs,
    )


async def _run(client: DiscordGatewayClient) -> asyncio.Task:
    return asyncio.create_task(client.run())


async def _finish(client: DiscordGatewayClient, task: asyncio.Task) -> None:
    await client.stop()
    await asyncio.wait_for(task, 5)


async def test_identify_ready_and_dispatch():
    recorder = Recorder()
    async with FakeGateway() as server:
        client = _client(server, recorder)
        task = await _run(client)
        conn = await server.connection(0)

        assert conn.identify["token"] == "secret-token"  # "Bot " prefix stripped
        assert conn.identify["intents"] == INTENTS
        assert conn.identify["shard"] == [0, 1]
        await _until(lambda: client.status.state == "connected")
        assert client.status.bot_user_id == "bot-1"
        assert client.status.application_id == "app-1"
        assert client.status.guild_count == 2
        assert client.status.identifies == 1

        await conn.dispatch("MESSAGE_CREATE", {"id": "m1", "content": "hi"}, 42)
        await _until(lambda: recorder.events)
        assert recorder.events == [("MESSAGE_CREATE", {"id": "m1", "content": "hi"})]

        await _finish(client, task)
        await asyncio.wait_for(conn.closed.wait(), 5)
        # A shutdown close keeps the session resumable for the next process.
        assert conn.close_code == gw.RESUMABLE_CLOSE_CODE
        assert client.status.state == "stopped"
        assert (await client._store.load()).session_id == "sess-1"


async def test_heartbeats_carry_last_sequence_and_track_acks():
    recorder = Recorder()
    async with FakeGateway(heartbeat_ms=40) as server:
        client = _client(server, recorder)
        task = await _run(client)
        conn = await server.connection(0)
        await conn.dispatch("MESSAGE_CREATE", {"id": "m1"}, 7)
        await _until(lambda: 7 in conn.heartbeats)
        assert client.status.last_heartbeat_ack_at is not None
        await _finish(client, task)


async def test_reconnect_request_resumes_the_session():
    recorder = Recorder()
    async with FakeGateway() as server:
        client = _client(server, recorder)
        task = await _run(client)
        first = await server.connection(0)
        await first.dispatch("MESSAGE_CREATE", {"id": "m1"}, 9)
        await _until(lambda: recorder.events)

        await first.send({"op": gw.OP_RECONNECT, "d": None})
        second = await server.connection(1)
        assert second.identify is None
        assert second.resume == {"token": "secret-token", "session_id": "sess-1", "seq": 9}
        await _until(lambda: client.status.resumes == 1)
        assert client.status.identifies == 1
        assert client.status.state == "connected"
        await _finish(client, task)


async def test_invalid_session_reidentifies_from_scratch():
    recorder = Recorder()
    store = MemorySessionStore()
    async with FakeGateway() as server:
        client = _client(server, recorder, store)
        task = await _run(client)
        first = await server.connection(0)
        await first.send({"op": gw.OP_INVALID_SESSION, "d": False})
        second = await server.connection(1)
        assert second.resume is None
        assert second.identify is not None
        assert client.status.identifies == 2
        # The new session replaced the dead one in the store.
        assert (await store.load()).session_id == "sess-2"
        await _finish(client, task)


async def test_persisted_session_resumes_on_first_connect():
    recorder = Recorder()
    store = MemorySessionStore()
    await store.save(GatewaySession(session_id="sess-old", resume_gateway_url="", seq=3))
    async with FakeGateway() as server:
        client = _client(server, recorder, store)
        task = await _run(client)
        conn = await server.connection(0)
        assert conn.identify is None
        assert conn.resume["session_id"] == "sess-old" and conn.resume["seq"] == 3
        await _finish(client, task)


async def test_fatal_close_code_stops_and_names_the_fix():
    recorder = Recorder()
    store = MemorySessionStore()
    await store.save(GatewaySession(session_id="s", resume_gateway_url="", seq=1))
    async with FakeGateway(close_after_hello=4014) as server:
        client = _client(server, recorder, store)
        await asyncio.wait_for(client.run(), 5)
    assert client.status.state == "fatal"
    assert "MESSAGE CONTENT INTENT" in client.status.last_error
    assert await store.load() is None  # a dead session is never resumed


async def test_unacknowledged_heartbeat_reconnects_resumably():
    recorder = Recorder()
    async with FakeGateway(heartbeat_ms=30, ack_heartbeats=False) as server:
        client = _client(server, recorder)
        task = await _run(client)
        first = await server.connection(0)
        await asyncio.wait_for(first.closed.wait(), 5)
        assert first.close_code == gw.RESUMABLE_CLOSE_CODE
        second = await server.connection(1)
        assert second.resume is not None and second.resume["session_id"] == "sess-1"
        await _finish(client, task)


async def test_transport_error_reconnects_with_backoff():
    recorder = Recorder()
    async with FakeGateway() as server:
        client = _client(server, recorder)
        task = await _run(client)
        first = await server.connection(0)
        await first.close(1011)  # server-side error, not a fatal code
        second = await server.connection(1)
        assert second.resume is not None
        await _until(lambda: client.status.state == "connected")
        await _finish(client, task)


async def test_rejects_empty_token():
    with pytest.raises(ValueError):
        DiscordGatewayClient("   ", intents=INTENTS, on_dispatch=Recorder())


async def test_redis_session_store_roundtrip():
    import fakeredis.aioredis

    client = fakeredis.aioredis.FakeRedis()
    store = gw.RedisSessionStore(client, "nc:test:discord:session", ttl_seconds=60)
    assert await store.load() is None
    await store.save(GatewaySession(session_id="s1", resume_gateway_url="wss://r", seq=5))
    loaded = await store.load()
    assert loaded == GatewaySession(session_id="s1", resume_gateway_url="wss://r", seq=5)
    assert 0 < await client.ttl("nc:test:discord:session") <= 60
    await store.clear()
    assert await store.load() is None
