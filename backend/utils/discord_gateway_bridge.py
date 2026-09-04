"""Discord Gateway → app-event fan-out bridge.

The Gateway hands us every message in every server the bot is installed in;
the bridge keeps the ones some workflow subscribed to and delivers them as
signed envelopes to the same ``/webhook/app/discord`` receiver Discord's HTTP
webhooks use, so subscriptions, channel scoping, fire budgets, dedup and the
trigger→agent delivery are one code path for both transports.

Shape:

    DiscordGatewayClient ──on_dispatch──▶ DiscordGatewayBridge
        (transport only)                    │ own-message drop
                                            │ guild subscription filter (DB, refreshed)
                                            │ bounded queue (heartbeats never wait on delivery)
                                            ▼
                                        Forwarder
                                          ├─ HttpForwarder      hosted: HMAC-signed POST to the receiver
                                          └─ InProcessForwarder self-hosted: dispatch_app_events()

The self-hosted edition runs the whole thing in-process (``LocalDiscordListener``,
started from the server lifespan); the hosted edition runs it in a dedicated
always-on process that must be the only session for the bot token.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol, Set, Tuple

from utils.discord_gateway import (
    INTENT_DIRECT_MESSAGES,
    INTENT_GUILD_MESSAGES,
    INTENT_GUILDS,
    INTENT_MESSAGE_CONTENT,
    DiscordGatewayClient,
    MemorySessionStore,
    SessionStore,
)

logger = logging.getLogger(__name__)

PROVIDER = "discord"
# Gateway dispatch types the bridge forwards.
GATEWAY_EVENT_TYPES = frozenset({"MESSAGE_CREATE"})
# Dispatches that keep the guild/channel name directory current: a message
# carries ids only, and names are what a person reads in a run.
DIRECTORY_EVENT_TYPES = frozenset({
    "GUILD_CREATE", "GUILD_UPDATE", "GUILD_DELETE",
    "CHANNEL_CREATE", "CHANNEL_UPDATE", "CHANNEL_DELETE",
    "THREAD_CREATE", "THREAD_UPDATE", "THREAD_DELETE", "THREAD_LIST_SYNC",
})
# Discord channel types that are threads. A message in one carries the
# thread's id as its channel_id; the channel a person scoped the trigger to is
# the thread's parent.
THREAD_CHANNEL_TYPES = frozenset({10, 11, 12})
# A message from a guild the filter does not know triggers one re-read of the
# subscriptions, at most this often: a trigger saved seconds ago gets its
# first message instead of losing it to the periodic refresh window.
MISS_REFRESH_MIN_S = 5.0
# NoClick-side event types subscriptions key on. MESSAGE_MENTION is minted by
# the receiver's parse from a MESSAGE_CREATE that mentions the bot — both the
# bridge's guild filter and the node's trigger map speak these names.
SUBSCRIBED_EVENT_TYPES = ("MESSAGE_CREATE", "MESSAGE_MENTION")

DEFAULT_INTENTS = INTENT_GUILDS | INTENT_GUILD_MESSAGES | INTENT_DIRECT_MESSAGES | INTENT_MESSAGE_CONTENT

# The receiver verifies this header against DISCORD_GATEWAY_RELAY_SECRET.
GATEWAY_SIGNATURE_HEADER = "x-noclick-gateway-signature"
GATEWAY_TIMESTAMP_HEADER = "x-noclick-gateway-timestamp"
GATEWAY_SECRET_ENV = "DISCORD_GATEWAY_RELAY_SECRET"

SUBSCRIPTION_REFRESH_S = 30.0
QUEUE_SIZE = 2000
FORWARD_ATTEMPTS = 3
FORWARD_TIMEOUT_S = 15.0
LOG_EVERY_N_DROPS = 100


def build_gateway_envelope(
    event_type: str,
    data: Dict[str, Any],
    *,
    bot_user_id: Optional[str],
    application_id: Optional[str],
    guild_name: Optional[str] = None,
    channel_name: Optional[str] = None,
    parent_channel_id: Optional[str] = None,
    parent_channel_name: Optional[str] = None,
) -> Dict[str, Any]:
    """The wire shape the receiver's Discord adapter parses (``source`` tells
    it apart from Discord's own HTTP payloads, which carry ``type``). The
    parent fields are set only for a message in a thread: the channel the
    thread was opened in."""
    return {
        "source": "gateway",
        "t": event_type,
        "d": data,
        "bot_user_id": bot_user_id,
        "application_id": application_id,
        "guild_name": guild_name,
        "channel_name": channel_name,
        "parent_channel_id": parent_channel_id,
        "parent_channel_name": parent_channel_name,
        "received_at": time.time(),
    }


DISCORD_API = "https://discord.com/api/v10"

# A guild fill: its name plus the channel objects (channels and active
# threads) the directory ingests. A channel fill: one channel object.
NameLookup = Callable[[str], Awaitable[Tuple[Optional[str], List[Dict[str, Any]]]]]
ChannelLookup = Callable[[str], Awaitable[Optional[Dict[str, Any]]]]


def _bot_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bot {token.strip().removeprefix('Bot ').strip()}"}


def rest_name_lookup(token: str) -> NameLookup:
    """One-time REST fill for a guild the stream never described — a RESUMED
    session sees no GUILD_CREATE replay. Guild name, channels and active
    threads: three calls per guild per process, only for subscribed guilds."""
    headers = _bot_headers(token)

    async def lookup(guild_id: str) -> Tuple[Optional[str], List[Dict[str, Any]]]:
        import httpx

        async with httpx.AsyncClient(timeout=15) as client:
            guild = await client.get(f"{DISCORD_API}/guilds/{guild_id}", headers=headers)
            guild.raise_for_status()
            channels = await client.get(f"{DISCORD_API}/guilds/{guild_id}/channels", headers=headers)
            channels.raise_for_status()
            threads = await client.get(f"{DISCORD_API}/guilds/{guild_id}/threads/active", headers=headers)
            threads.raise_for_status()
        return (
            (guild.json() or {}).get("name"),
            list(channels.json() or []) + list((threads.json() or {}).get("threads") or []),
        )

    return lookup


def rest_channel_lookup(token: str) -> ChannelLookup:
    """One-time REST fill for a channel neither the stream nor the guild fill
    described — a thread opened during a gap in the session. One call per
    unknown channel per process."""
    headers = _bot_headers(token)

    async def lookup(channel_id: str) -> Optional[Dict[str, Any]]:
        import httpx

        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(f"{DISCORD_API}/channels/{channel_id}", headers=headers)
            response.raise_for_status()
        channel = response.json()
        return channel if isinstance(channel, dict) else None

    return lookup


class GuildDirectory:
    """Guild and channel names from the Gateway's own stream: GUILD_CREATE
    (sent for every guild at READY, channels and threads included) and the
    create/update/delete events after it — plus one REST fill per guild, and
    per channel, the stream never described. No lookup per message.

    A thread is remembered with its parent channel: a trigger scoped to a
    channel hears the threads opened in it, and the parent on the envelope is
    how the receiver knows a thread message belongs."""

    def __init__(self) -> None:
        self.guild_names: Dict[str, str] = {}
        self.channel_names: Dict[str, str] = {}
        self.thread_parents: Dict[str, str] = {}
        self.fetched: Set[str] = set()
        self.fetched_channels: Set[str] = set()

    async def ensure(self, guild_id: str, lookup: NameLookup) -> None:
        """Fill a guild's names once per process when the stream has not."""
        if not guild_id or guild_id in self.guild_names or guild_id in self.fetched:
            return
        self.fetched.add(guild_id)  # once, even on failure — never a call per message
        try:
            name, channels = await lookup(guild_id)
        except Exception as e:
            logger.warning(f"[DiscordGateway] name lookup for guild {guild_id} failed: {e}")
            return
        if name:
            self.guild_names[guild_id] = name
        for channel in channels:
            self._ingest(channel)

    async def ensure_channel(self, channel_id: str, lookup: ChannelLookup) -> None:
        """Fill one channel once per process when the stream and the guild fill
        both missed it."""
        if not channel_id or channel_id in self.channel_names or channel_id in self.fetched_channels:
            return
        self.fetched_channels.add(channel_id)
        try:
            channel = await lookup(channel_id)
        except Exception as e:
            logger.warning(f"[DiscordGateway] lookup for channel {channel_id} failed: {e}")
            return
        if channel:
            self._ingest(channel)

    def _ingest(self, channel: Any, *, thread: bool = False) -> None:
        """A channel object from the stream or REST: its name, and its parent
        when it is a thread (by type, or by arriving in a threads list)."""
        if not isinstance(channel, dict) or not channel.get("id"):
            return
        channel_id = str(channel["id"])
        if isinstance(channel.get("name"), str):
            self.channel_names[channel_id] = channel["name"]
        if (thread or channel.get("type") in THREAD_CHANNEL_TYPES) and channel.get("parent_id"):
            self.thread_parents[channel_id] = str(channel["parent_id"])

    def _forget(self, channel_id: str) -> None:
        self.channel_names.pop(channel_id, None)
        self.thread_parents.pop(channel_id, None)

    def apply(self, event_type: str, data: Dict[str, Any]) -> None:
        object_id = str(data.get("id") or "")
        name = data.get("name") if isinstance(data.get("name"), str) else None
        if event_type == "GUILD_CREATE":
            if object_id and name:
                self.guild_names[object_id] = name
            for channel in data.get("channels") or []:
                self._ingest(channel)
            for channel in data.get("threads") or []:
                self._ingest(channel, thread=True)
        elif event_type == "THREAD_LIST_SYNC":
            for channel in data.get("threads") or []:
                self._ingest(channel, thread=True)
        elif event_type == "GUILD_UPDATE":
            if object_id and name:
                self.guild_names[object_id] = name
        elif event_type == "GUILD_DELETE":
            self.guild_names.pop(object_id, None)
        elif event_type in ("CHANNEL_CREATE", "CHANNEL_UPDATE"):
            self._ingest(data)
        elif event_type in ("THREAD_CREATE", "THREAD_UPDATE"):
            self._ingest(data, thread=True)
        elif event_type in ("CHANNEL_DELETE", "THREAD_DELETE"):
            self._forget(object_id)


def sign_gateway_body(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class Forwarder(Protocol):
    async def forward(self, body: bytes) -> None:
        """Deliver one serialized envelope; raise on failure."""


class HttpForwarder:
    """Hosted delivery: a signed POST to the app-webhook receiver on the
    autoscaling worker, retried on transport failure. The receiver dedups by
    message id, so a retry after an ambiguous failure can't double-fire."""

    def __init__(self, url: str, secret: str, *, client=None) -> None:
        if not url or not secret:
            raise ValueError("HttpForwarder needs a receiver URL and a signing secret")
        self._url = url
        self._secret = secret
        self._client = client

    async def forward(self, body: bytes) -> None:
        import httpx

        headers = {
            "content-type": "application/json",
            GATEWAY_SIGNATURE_HEADER: sign_gateway_body(body, self._secret),
            GATEWAY_TIMESTAMP_HEADER: str(int(time.time())),
        }
        last_error: Optional[Exception] = None
        for attempt in range(1, FORWARD_ATTEMPTS + 1):
            try:
                client = self._client or httpx.AsyncClient(timeout=FORWARD_TIMEOUT_S)
                try:
                    response = await client.post(self._url, content=body, headers=headers)
                finally:
                    if self._client is None:
                        await client.aclose()
                if response.status_code < 500:
                    if response.status_code >= 400:
                        raise RuntimeError(
                            f"receiver rejected the envelope: {response.status_code} "
                            f"{response.text[:200]}"
                        )
                    return
                last_error = RuntimeError(f"receiver returned {response.status_code}")
            except RuntimeError:
                raise  # a 4xx is deterministic — retrying can't help
            except Exception as e:
                last_error = e
            await asyncio.sleep(0.5 * attempt)
        raise RuntimeError(f"forward failed after {FORWARD_ATTEMPTS} attempts: {last_error}")


class InProcessForwarder:
    """Open-edition delivery: the receiver runs in this very process, so hand
    the envelope straight to the fan-out (no HTTP, no signature)."""

    async def forward(self, body: bytes) -> None:
        from utils.webhook_routes import dispatch_app_events

        await dispatch_app_events(PROVIDER, body)


PoolGetter = Callable[[], Any]


class GuildSubscriptionFilter:
    """The guild ids with at least one live message subscription, refreshed
    from ``webhook_subscriptions`` — everything else is dropped at the edge
    before it costs an HTTP round-trip. A refresh error keeps the last good
    set (never an empty one, which would silently drop every message)."""

    def __init__(self, pool_getter: PoolGetter) -> None:
        self._pool_getter = pool_getter
        self.guild_ids: Set[str] = set()
        self.refreshed_at: Optional[float] = None
        self.last_error: Optional[str] = None

    async def refresh(self) -> None:
        pool = self._pool_getter()
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT DISTINCT tenant_id FROM webhook_subscriptions
                    WHERE provider = $1 AND event_type = ANY($2::text[])
                    """,
                    PROVIDER,
                    list(SUBSCRIBED_EVENT_TYPES),
                )
            self.guild_ids = {str(r["tenant_id"]) for r in rows}
            self.refreshed_at = time.time()
            self.last_error = None
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            logger.warning(f"[DiscordGateway] subscription refresh failed: {self.last_error}")

    def allows(self, guild_id: Optional[str]) -> bool:
        return bool(guild_id) and str(guild_id) in self.guild_ids

    def stale_for(self, seconds: float) -> bool:
        return self.refreshed_at is None or time.time() - self.refreshed_at >= seconds


@dataclass
class BridgeCounters:
    forwarded: int = 0
    dropped_unsubscribed: int = 0
    dropped_own: int = 0
    dropped_dm: int = 0
    dropped_overflow: int = 0
    forward_failures: int = 0
    last_forward_error: Optional[str] = None
    last_forwarded_at: Optional[float] = None


class DiscordGatewayBridge:
    def __init__(
        self,
        token: str,
        *,
        forwarder: Forwarder,
        pool_getter: PoolGetter,
        session_store: Optional[SessionStore] = None,
        intents: int = DEFAULT_INTENTS,
        connect: Optional[Callable[..., Any]] = None,
        refresh_interval_s: float = SUBSCRIPTION_REFRESH_S,
        queue_size: int = QUEUE_SIZE,
        name_lookup: Optional[NameLookup] = None,
        channel_lookup: Optional[ChannelLookup] = None,
    ) -> None:
        self._forwarder = forwarder
        self._filter = GuildSubscriptionFilter(pool_getter)
        self.directory = GuildDirectory()
        self._name_lookup = name_lookup or rest_name_lookup(token)
        self._channel_lookup = channel_lookup or rest_channel_lookup(token)
        self._refresh_interval = refresh_interval_s
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=queue_size)
        self.counters = BridgeCounters()
        self.client = DiscordGatewayClient(
            token,
            intents=intents,
            on_dispatch=self._on_dispatch,
            session_store=session_store or MemorySessionStore(),
            connect=connect,
        )
        self._tasks: list = []
        self._stopping = False

    # ----------------------------------------------------------- lifecycle
    async def run(self) -> None:
        """Serve until ``stop()``. The first subscription refresh happens
        BEFORE connecting so the filter is never empty while events flow."""
        await self._filter.refresh()
        self._tasks = [
            asyncio.create_task(self._refresh_loop(), name="discord-gateway-refresh"),
            asyncio.create_task(self._sender_loop(), name="discord-gateway-sender"),
        ]
        try:
            await self.client.run()
        finally:
            for task in self._tasks:
                task.cancel()
            for task in self._tasks:
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
            self._tasks = []

    async def stop(self) -> None:
        self._stopping = True
        await self.client.stop()

    async def refresh_subscriptions(self) -> None:
        """Re-read the guild filter now (a registration write can call this
        instead of waiting a refresh interval)."""
        await self._filter.refresh()

    def status(self) -> Dict[str, Any]:
        data = self.client.status.as_dict()
        data.update({
            "subscribed_guilds": len(self._filter.guild_ids),
            "subscriptions_refreshed_at": self._filter.refreshed_at,
            "subscriptions_error": self._filter.last_error,
            "directory_guilds": len(self.directory.guild_names),
            "directory_channels": len(self.directory.channel_names),
            "directory_threads": len(self.directory.thread_parents),
            "queue_depth": self._queue.qsize(),
            **self.counters.__dict__,
        })
        return data

    # --------------------------------------------------------------- loops
    async def _refresh_loop(self) -> None:
        while True:
            await asyncio.sleep(self._refresh_interval)
            await self._filter.refresh()

    async def _sender_loop(self) -> None:
        while True:
            event_type, data = await self._queue.get()
            try:
                # Names resolve here, off the read loop: the directory answers
                # from the stream, or one REST fill per guild the stream never
                # described (a resumed session gets no GUILD_CREATE replay).
                guild_id = str(data.get("guild_id") or "")
                channel_id = str(data.get("channel_id") or "")
                await self.directory.ensure(guild_id, self._name_lookup)
                await self.directory.ensure_channel(channel_id, self._channel_lookup)
                parent_id = self.directory.thread_parents.get(channel_id)
                status = self.client.status
                envelope = build_gateway_envelope(
                    event_type, data,
                    bot_user_id=status.bot_user_id,
                    application_id=status.application_id,
                    guild_name=self.directory.guild_names.get(guild_id),
                    channel_name=self.directory.channel_names.get(channel_id),
                    parent_channel_id=parent_id,
                    parent_channel_name=self.directory.channel_names.get(parent_id) if parent_id else None,
                )
                await self._forwarder.forward(json.dumps(envelope, separators=(",", ":")).encode())
                self.counters.forwarded += 1
                self.counters.last_forwarded_at = time.time()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.counters.forward_failures += 1
                self.counters.last_forward_error = f"{type(e).__name__}: {e}"
                logger.error(f"[DiscordGateway] forward failed: {self.counters.last_forward_error}")
            finally:
                self._queue.task_done()

    # ------------------------------------------------------------ dispatch
    async def _on_dispatch(self, event_type: str, data: Dict[str, Any]) -> None:
        if event_type in DIRECTORY_EVENT_TYPES:
            self.directory.apply(event_type, data)
            return
        if event_type not in GATEWAY_EVENT_TYPES:
            return
        status = self.client.status
        author = data.get("author") if isinstance(data.get("author"), dict) else {}
        if status.bot_user_id and str(author.get("id")) == status.bot_user_id:
            self.counters.dropped_own += 1  # the bot's own posts never re-trigger it
            return
        guild_id = data.get("guild_id")
        if not guild_id:
            self.counters.dropped_dm += 1  # DMs have no guild tenant to route by
            return
        if not self._filter.allows(guild_id):
            if self._filter.stale_for(MISS_REFRESH_MIN_S):
                await self._filter.refresh()
            if not self._filter.allows(guild_id):
                self.counters.dropped_unsubscribed += 1
                return
        try:
            self._queue.put_nowait((event_type, data))
        except asyncio.QueueFull:
            self.counters.dropped_overflow += 1
            if self.counters.dropped_overflow % LOG_EVERY_N_DROPS == 1:
                logger.error(
                    f"[DiscordGateway] delivery queue full ({self._queue.maxsize}) — "
                    f"dropped {self.counters.dropped_overflow} message(s); the receiver is "
                    "not keeping up"
                )


# ============================================================================
# Open edition: in-process listener
# ============================================================================

TOKEN_ENV = "DISCORD_BOT_TOKEN"
LOCAL_POLL_S = 30.0


def _current_token() -> Optional[str]:
    return (os.environ.get(TOKEN_ENV) or "").strip() or None


class LocalDiscordListener:
    """Runs the bridge inside the backend process while ``DISCORD_BOT_TOKEN``
    is set. Instance keys land in the environment at runtime (Settings →
    Self-hosted), so the supervisor re-reads the token every ``poll_s`` and
    starts, stops or restarts the bridge to match — no restart needed."""

    def __init__(
        self,
        *,
        pool_getter: PoolGetter,
        forwarder: Optional[Forwarder] = None,
        connect: Optional[Callable[..., Any]] = None,
        poll_s: float = LOCAL_POLL_S,
    ) -> None:
        self._pool_getter = pool_getter
        self._forwarder = forwarder or InProcessForwarder()
        self._connect = connect
        self._poll_s = poll_s
        self._bridge: Optional[DiscordGatewayBridge] = None
        self._bridge_task: Optional[asyncio.Task] = None
        self._token: Optional[str] = None
        self._supervisor: Optional[asyncio.Task] = None

    @property
    def bridge(self) -> Optional[DiscordGatewayBridge]:
        return self._bridge

    def start(self) -> None:
        if self._supervisor is None or self._supervisor.done():
            self._supervisor = asyncio.create_task(self._supervise(), name="discord-gateway-local")

    async def stop(self) -> None:
        if self._supervisor is not None:
            self._supervisor.cancel()
            try:
                await self._supervisor
            except (asyncio.CancelledError, Exception):
                pass
            self._supervisor = None
        await self._stop_bridge()

    async def reconcile(self) -> None:
        """One supervisor step: match the running bridge to the current token."""
        token = _current_token()
        if token == self._token and (self._bridge_task is None or not self._bridge_task.done()):
            return
        await self._stop_bridge()
        self._token = token
        if not token:
            return
        self._bridge = DiscordGatewayBridge(
            token,
            forwarder=self._forwarder,
            pool_getter=self._pool_getter,
            connect=self._connect,
        )
        self._bridge_task = asyncio.create_task(self._bridge.run(), name="discord-gateway-bridge")
        logger.info("[DiscordGateway] local listener started")

    def status(self) -> Dict[str, Any]:
        if self._bridge is None:
            return {"state": "disabled", "reason": f"{TOKEN_ENV} is not set"}
        return self._bridge.status()

    async def _supervise(self) -> None:
        while True:
            try:
                await self.reconcile()
            except Exception as e:
                logger.error(f"[DiscordGateway] local supervisor step failed: {e}")
            await asyncio.sleep(self._poll_s)

    async def _stop_bridge(self) -> None:
        bridge, task = self._bridge, self._bridge_task
        self._bridge, self._bridge_task = None, None
        if bridge is not None:
            await bridge.stop()
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass


_local_listener: Optional[LocalDiscordListener] = None


def start_local_discord_listener() -> LocalDiscordListener:
    """Server-lifespan entry for the open edition."""
    global _local_listener
    from utils.database_pool import get_native_pool

    if _local_listener is None:
        _local_listener = LocalDiscordListener(pool_getter=get_native_pool)
    _local_listener.start()
    return _local_listener


async def stop_local_discord_listener() -> None:
    global _local_listener
    listener, _local_listener = _local_listener, None
    if listener is not None:
        await listener.stop()


def local_discord_listener_status() -> Dict[str, Any]:
    if _local_listener is None:
        return {"state": "disabled", "reason": "listener not started"}
    return _local_listener.status()
