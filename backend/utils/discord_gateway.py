"""Discord Gateway client — the persistent WebSocket Discord requires for
channel-message events.

Discord's HTTP event webhooks carry application lifecycle, entitlement and
Social-SDK events only; ``MESSAGE_CREATE`` and every other guild event exist
solely on the Gateway. This module speaks that protocol for ONE bot token:
hello → identify (or resume) → heartbeats → dispatches, with the reconnect
rules Discord documents (resume on op 7 / close, re-identify on an invalid
session, never retry a fatal close code). It is transport only: what to do
with a dispatch is the caller's ``on_dispatch`` — see
``utils/discord_gateway_bridge.py`` for the NoClick side.

Both editions run this exact client: the self-hosted edition as an in-process
task, the hosted one in a dedicated always-on process.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional, Protocol, Tuple

logger = logging.getLogger(__name__)

GATEWAY_URL = "wss://gateway.discord.gg"
GATEWAY_QUERY = "?v=10&encoding=json"

# Gateway intents (https://docs.discord.com/developers/events/gateway#gateway-intents)
INTENT_GUILDS = 1 << 0
INTENT_GUILD_MESSAGES = 1 << 9
INTENT_GUILD_MESSAGE_REACTIONS = 1 << 10
INTENT_DIRECT_MESSAGES = 1 << 12
INTENT_MESSAGE_CONTENT = 1 << 15  # privileged: toggled in the Developer Portal

OP_DISPATCH = 0
OP_HEARTBEAT = 1
OP_IDENTIFY = 2
OP_RESUME = 6
OP_RECONNECT = 7
OP_INVALID_SESSION = 9
OP_HELLO = 10
OP_HEARTBEAT_ACK = 11

# Closing with 1000/1001 invalidates the session server-side; any other code
# keeps it resumable. Used for every close the client initiates.
RESUMABLE_CLOSE_CODE = 4000

# Close codes where reconnecting is pointless until an operator acts. The
# message is what the status surface shows, so it names the fix.
FATAL_CLOSE_CODES: Dict[int, str] = {
    4004: "Discord rejected the bot token (close 4004) — check DISCORD_BOT_TOKEN",
    4010: "invalid shard (close 4010)",
    4011: (
        "sharding required (close 4011) — the bot is in more than 2,500 servers; "
        "run the gateway with more shards"
    ),
    4012: "invalid Gateway API version (close 4012)",
    4013: "invalid intents (close 4013)",
    4014: (
        "disallowed intents (close 4014) — enable MESSAGE CONTENT INTENT under "
        "Bot → Privileged Gateway Intents in the Discord Developer Portal, or "
        "start the gateway without INTENT_MESSAGE_CONTENT"
    ),
}
# Session is gone; re-identify instead of resuming.
NON_RESUMABLE_CLOSE_CODES = frozenset({4007, 4009})

RECONNECT_BACKOFF_MIN_S = 1.0
RECONNECT_BACKOFF_MAX_S = 60.0
# Discord's own recommended pause before re-identifying after an invalid session.
INVALID_SESSION_WAIT_S = (1.0, 5.0)
# A dispatch handler must return quickly (enqueue, never do network I/O): the
# read loop it blocks is the one that answers heartbeats.
DISPATCH_SLOW_WARN_S = 1.0


@dataclass
class GatewaySession:
    """What RESUME needs; persisted so a restarted process resumes instead of
    spending one of the bot's 1,000 daily IDENTIFYs and missing the gap.

    Carries the bot's identity too: only READY announces it, and a resumed
    session never sees READY — without these a fresh process could not tell
    its own messages or its mentions apart until the next full identify."""

    session_id: str
    resume_gateway_url: str
    seq: Optional[int] = None
    bot_user_id: Optional[str] = None
    application_id: Optional[str] = None


class SessionStore(Protocol):
    async def load(self) -> Optional[GatewaySession]: ...

    async def save(self, session: GatewaySession) -> None: ...

    async def clear(self) -> None: ...


class MemorySessionStore:
    """Process-lifetime store (open edition): a restart re-identifies."""

    def __init__(self) -> None:
        self._session: Optional[GatewaySession] = None

    async def load(self) -> Optional[GatewaySession]:
        return self._session

    async def save(self, session: GatewaySession) -> None:
        self._session = session

    async def clear(self) -> None:
        self._session = None


class RedisSessionStore:
    """Cross-restart store. TTL bounds how stale a resume attempt can be —
    Discord answers a dead session with op 9, which re-identifies cleanly."""

    def __init__(self, client, key: str, ttl_seconds: int = 30 * 60) -> None:
        self._client = client
        self._key = key
        self._ttl = ttl_seconds

    async def load(self) -> Optional[GatewaySession]:
        raw = await self._client.get(self._key)
        if not raw:
            return None
        data = json.loads(raw if isinstance(raw, str) else raw.decode())
        return GatewaySession(**data)

    async def save(self, session: GatewaySession) -> None:
        await self._client.set(self._key, json.dumps(asdict(session)), ex=self._ttl)

    async def clear(self) -> None:
        await self._client.delete(self._key)


@dataclass
class GatewayStatus:
    """Observable state, read by health probes; ``fatal`` is terminal until an
    operator acts (the ``last_error`` names the fix)."""

    state: str = "starting"  # starting | connecting | connected | reconnecting | stopped | fatal
    bot_user_id: Optional[str] = None
    application_id: Optional[str] = None
    session_id: Optional[str] = None
    shard: Tuple[int, int] = (0, 1)
    guild_count: int = 0
    identifies: int = 0
    resumes: int = 0
    dispatches: int = 0
    connected_since: Optional[float] = None
    last_event_at: Optional[float] = None
    last_heartbeat_ack_at: Optional[float] = None
    last_error: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["shard"] = list(self.shard)
        return data


DispatchHandler = Callable[[str, Dict[str, Any]], Awaitable[None]]


class _ReconnectRequested(Exception):
    """Internal: close the socket and reconnect (resume when ``resumable``)."""

    def __init__(self, reason: str, *, resumable: bool = True) -> None:
        super().__init__(reason)
        self.resumable = resumable


class DiscordGatewayClient:
    """One bot token, one shard, one session — reconnects until ``stop()``.

    ``connect`` is injectable for tests (a fake gateway on localhost); the
    default is ``websockets.asyncio.client.connect``.
    """

    def __init__(
        self,
        token: str,
        *,
        intents: int,
        on_dispatch: DispatchHandler,
        session_store: Optional[SessionStore] = None,
        shard: Tuple[int, int] = (0, 1),
        gateway_url: str = GATEWAY_URL,
        connect: Optional[Callable[..., Any]] = None,
    ) -> None:
        if not token or not token.strip():
            raise ValueError("A Discord bot token is required")
        self._token = token.strip().removeprefix("Bot ").strip()
        self._intents = intents
        self._on_dispatch = on_dispatch
        self._store: SessionStore = session_store or MemorySessionStore()
        self._gateway_url = gateway_url
        self._connect = connect or _default_connect
        self.status = GatewayStatus(shard=shard)

        self._ws = None
        self._session: Optional[GatewaySession] = None
        self._stop = asyncio.Event()
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._heartbeat_acked = True
        self._backoff = RECONNECT_BACKOFF_MIN_S

    # ------------------------------------------------------------------ run
    async def run(self) -> None:
        """Connect and serve until ``stop()``; returns on stop or a fatal close.
        Never raises for transport trouble — that is what reconnecting is for."""
        self._session = await self._store.load()
        if self._session is not None:
            self.status.bot_user_id = self._session.bot_user_id
            self.status.application_id = self._session.application_id
        while not self._stop.is_set():
            resumable = True
            try:
                self.status.state = "connecting"
                await self._serve_one_connection()
            except _ReconnectRequested as e:
                resumable = e.resumable
                logger.info(f"[DiscordGateway] reconnecting: {e}")
            except asyncio.CancelledError:
                raise
            except Exception as e:  # network / protocol trouble
                close_code = getattr(e, "code", None)
                if close_code in FATAL_CLOSE_CODES:
                    self.status.state = "fatal"
                    self.status.last_error = FATAL_CLOSE_CODES[close_code]
                    logger.error(f"[DiscordGateway] {self.status.last_error}")
                    await self._forget_session()
                    return
                if close_code in NON_RESUMABLE_CLOSE_CODES:
                    resumable = False
                self.status.last_error = f"{type(e).__name__}: {e}"
                logger.warning(f"[DiscordGateway] connection lost: {self.status.last_error}")
            finally:
                await self._stop_heartbeat()
                self._ws = None
            if self._stop.is_set():
                break
            if not resumable:
                await self._forget_session()
            self.status.state = "reconnecting"
            await self._sleep_backoff()
        self.status.state = "stopped"

    async def stop(self) -> None:
        """Close resumably: the session survives for the next process."""
        self._stop.set()
        ws = self._ws
        if ws is not None:
            try:
                await ws.close(code=RESUMABLE_CLOSE_CODE, reason="shutdown")
            except Exception:
                pass

    # -------------------------------------------------------- one connection
    async def _serve_one_connection(self) -> None:
        url = self._gateway_url
        if self._session and self._session.resume_gateway_url:
            url = self._session.resume_gateway_url
        async with self._connect(url.rstrip("/") + GATEWAY_QUERY) as ws:
            self._ws = ws
            hello = await self._recv(ws)
            if hello.get("op") != OP_HELLO:
                raise _ReconnectRequested(f"expected HELLO, got op {hello.get('op')}")
            interval_s = float(hello["d"]["heartbeat_interval"]) / 1000.0
            self._heartbeat_acked = True
            self._heartbeat_task = asyncio.create_task(
                self._heartbeat_loop(ws, interval_s), name="discord-gateway-heartbeat"
            )
            if self._session:
                await self._send(ws, OP_RESUME, {
                    "token": self._token,
                    "session_id": self._session.session_id,
                    "seq": self._session.seq,
                })
            else:
                await self._identify(ws)
            async for raw in ws:
                await self._handle_frame(ws, json.loads(raw))
            # Clean EOF without a close frame we asked for: reconnect.
            raise _ReconnectRequested(
                f"socket closed (code {ws.close_code}, {ws.close_reason or 'no reason'})",
                resumable=ws.close_code not in NON_RESUMABLE_CLOSE_CODES,
            )

    async def _identify(self, ws) -> None:
        await self._send(ws, OP_IDENTIFY, {
            "token": self._token,
            "intents": self._intents,
            "properties": {"os": sys.platform, "browser": "noclick", "device": "noclick"},
            "shard": list(self.status.shard),
        })
        self.status.identifies += 1

    async def _handle_frame(self, ws, frame: Dict[str, Any]) -> None:
        op = frame.get("op")
        if frame.get("s") is not None and self._session is not None:
            self._session.seq = frame["s"]
        if op == OP_DISPATCH:
            await self._handle_dispatch(frame)
        elif op == OP_HEARTBEAT:
            await self._send_heartbeat(ws)
        elif op == OP_HEARTBEAT_ACK:
            self._heartbeat_acked = True
            self.status.last_heartbeat_ack_at = time.time()
        elif op == OP_RECONNECT:
            raise _ReconnectRequested("Discord asked us to reconnect (op 7)")
        elif op == OP_INVALID_SESSION:
            resumable = bool(frame.get("d"))
            if not resumable:
                lo, hi = INVALID_SESSION_WAIT_S
                await asyncio.sleep(random.uniform(lo, hi))
            raise _ReconnectRequested("invalid session (op 9)", resumable=resumable)
        elif op == OP_HELLO:
            raise _ReconnectRequested("unexpected second HELLO")

    async def _handle_dispatch(self, frame: Dict[str, Any]) -> None:
        event_type = frame.get("t") or ""
        data = frame.get("d") if isinstance(frame.get("d"), dict) else {}
        seq = frame.get("s")
        self.status.dispatches += 1
        self.status.last_event_at = time.time()
        if event_type == "READY":
            self.status.bot_user_id = str((data.get("user") or {}).get("id") or "") or None
            self.status.application_id = (
                str((data.get("application") or {}).get("id") or "") or None
            )
            self._session = GatewaySession(
                session_id=str(data.get("session_id")),
                resume_gateway_url=str(data.get("resume_gateway_url") or self._gateway_url),
                seq=seq,
                bot_user_id=self.status.bot_user_id,
                application_id=self.status.application_id,
            )
            await self._store.save(self._session)
            self.status.guild_count = len(data.get("guilds") or [])
            self._on_session_up()
            logger.info(
                f"[DiscordGateway] READY as bot {self.status.bot_user_id} "
                f"(session {self._session.session_id}, {self.status.guild_count} guilds)"
            )
            return
        if event_type == "RESUMED":
            self.status.resumes += 1
            self._on_session_up()
            logger.info(f"[DiscordGateway] RESUMED session {self.status.session_id}")
            return
        if event_type == "GUILD_CREATE":
            self.status.guild_count += 1
        elif event_type == "GUILD_DELETE":
            self.status.guild_count = max(0, self.status.guild_count - 1)
        started = time.monotonic()
        await self._on_dispatch(event_type, data)
        elapsed = time.monotonic() - started
        if elapsed > DISPATCH_SLOW_WARN_S:
            logger.warning(
                f"[DiscordGateway] on_dispatch({event_type}) took {elapsed:.1f}s — "
                "handlers must enqueue, not do I/O, or heartbeats starve"
            )

    def _on_session_up(self) -> None:
        self.status.state = "connected"
        self.status.session_id = self._session.session_id if self._session else None
        self.status.connected_since = time.time()
        self.status.last_error = None
        self._backoff = RECONNECT_BACKOFF_MIN_S

    # ------------------------------------------------------------ heartbeat
    async def _heartbeat_loop(self, ws, interval_s: float) -> None:
        # First beat at a random point in the interval, per the Gateway docs.
        await asyncio.sleep(interval_s * random.random())
        while True:
            if not self._heartbeat_acked:
                # Zombied connection: Discord never ACKed the last beat. Close
                # resumably and let run() reconnect.
                logger.warning("[DiscordGateway] heartbeat not acknowledged — reconnecting")
                await ws.close(code=RESUMABLE_CLOSE_CODE, reason="heartbeat timeout")
                return
            await self._send_heartbeat(ws)
            if self._session is not None:
                await self._store.save(self._session)  # keeps seq fresh for resume
            await asyncio.sleep(interval_s)

    async def _send_heartbeat(self, ws) -> None:
        self._heartbeat_acked = False
        await self._send(ws, OP_HEARTBEAT, self._session.seq if self._session else None)

    async def _stop_heartbeat(self) -> None:
        task, self._heartbeat_task = self._heartbeat_task, None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    # ------------------------------------------------------------ helpers
    async def _forget_session(self) -> None:
        self._session = None
        self.status.session_id = None
        await self._store.clear()

    async def _sleep_backoff(self) -> None:
        delay = self._backoff * random.uniform(0.8, 1.2)
        self._backoff = min(self._backoff * 2, RECONNECT_BACKOFF_MAX_S)
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=delay)
        except asyncio.TimeoutError:
            pass

    @staticmethod
    async def _recv(ws) -> Dict[str, Any]:
        return json.loads(await ws.recv())

    @staticmethod
    async def _send(ws, op: int, data: Any) -> None:
        await ws.send(json.dumps({"op": op, "d": data}))


def _default_connect(url: str):
    from websockets.asyncio.client import connect

    # Liveness is Discord's heartbeat, not the WebSocket ping; READY for a
    # bot in many guilds exceeds the library's 1 MiB default.
    return connect(url, ping_interval=None, max_size=8 * 1024 * 1024, open_timeout=20)
