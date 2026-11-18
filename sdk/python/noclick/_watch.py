"""Watch: one socket that says which of your objects changed, so what shows them reads them again instead of polling.

    for message in noclick.watch(objects=["deployment", "domain"]):
        if message.type == "change":
            refresh(message.object, message.object_id)
        elif message.type == "reset" or (message.type == "ready" and not message.resumed):
            refresh_all()

A change names an object (as its read's ``object`` says it: ``deployment``, ``channel``, ``agent``, ...) and its
id, never its data: read it again. It is not the event log (``noclick.Event``, webhooks), which records what
happened, with data, for 30 days and delivers each event at least once. A change is a hint, delivered at most once:
re-read everything you show on ``reset``, on a ``ready`` that didn't resume (the first one too, for anything you read
before it), and on a slow timer of your own if you must never be stale.

Your key follows the account's objects, its users' included; acting for one user (``user``), only that user's. A
server whose page should watch hands the page a token from ``watch_token`` (pass the page's ``origin``); the page
opens it with the TypeScript SDK's ``watch({ token })``.

``watch`` needs the ``websockets`` package: ``pip install "noclick[live]"``.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import random
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple, Union
from urllib.parse import urlsplit

from ._client import Client, resolve_client
from ._object import parse_time
from ._scope import AMBIENT
from ._sync import synced
from .exceptions import Error

# The room's close codes: renew (lifetime reached: reconnect), refused (the token, or access), too many connections.
CLOSE_RENEW, CLOSE_REFUSED, CLOSE_AUTH_TIMEOUT, CLOSE_TOO_MANY = 4000, 4401, 4408, 4429
_BACKOFF_S = (0.5, 1.0, 2.0, 5.0, 10.0, 30.0)
_TOO_MANY_S = 30.0
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


def _spread(seconds: float) -> float:
    """A wait spread over half to one and a half of ``seconds``, so sockets that dropped together don't all come
    back at once."""
    return seconds * (0.5 + random.random())


def _socket_url(url: str) -> str:
    """The socket's address, if the token's answer named one a token is sent to: wss://, or ws:// on this
    machine. Anything else is refused before the token leaves."""
    parts = urlsplit(url)
    if parts.scheme == "wss" and parts.hostname or parts.scheme == "ws" and parts.hostname in _LOCAL_HOSTS:
        return url
    raise Error("The watch socket's address isn't a wss:// URL, so its token was not sent.",
                next_step="Check that the token comes from NoClick's API (or your server passes its url on as it is).")
_PING_S = 30.0

TokenSource = Callable[[], Union[Tuple[str, str], Awaitable[Tuple[str, str]]]]


class WatchRefused(Error):
    """The room refused two fresh tokens in a row: access ended (a revoked key, a deleted user)."""

    type = "watch_refused"


@dataclass(frozen=True)
class WatchToken:
    """A single-use token for the socket at ``url``, good until ``expires_at``."""

    url: str
    token: str = field(repr=False)
    expires_at: Any
    #: When the connection it opens ends (``watch`` then reconnects with a new token).
    connection_ends_at: Any
    objects: List[str]
    #: The user whose objects it follows; None for the account's.
    user_id: Optional[str]
    #: The page's origin the socket must come from, when one was given.
    origin: Optional[str]
    raw: Dict[str, Any] = field(repr=False)


@dataclass(frozen=True)
class WatchReady:
    """The socket is open: ``resumed`` when it carried on from the last change you got, so nothing was missed."""

    resumed: bool
    type: str = "ready"


@dataclass(frozen=True)
class WatchChange:
    """An object changed: read it again."""

    #: This change's place in the stream (what a reconnect resumes after).
    id: str
    at: Any
    object: str
    #: Its id; None for a ``coding_agent`` change that may be any of them.
    object_id: Optional[str]
    #: Its status as its read gave it then (advisory: the read is the truth); None once it's gone.
    status: Optional[str] = None
    #: What it belongs to (``{"object": "project", "id": ...}`` for a deployment), else None.
    parent: Optional[Dict[str, str]] = None
    #: What moved: an agent's ``turn``, ``step``, ``definition``, ...; a channel's ``message``, ``reaction``, ...
    change: Optional[str] = None
    #: A workflow's graph version now.
    version: Optional[int] = None
    workspace_id: Optional[str] = None
    message_id: Optional[str] = None
    thread_id: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)
    type: str = "change"


@dataclass(frozen=True)
class WatchTyping:
    """Someone started or stopped typing in a channel you read (never sent to the one typing)."""

    channel_id: str
    workspace_id: Optional[str]
    #: Who: a user's id, or ``account`` for the account's owner.
    user_id: str
    typing: bool
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)
    type: str = "typing"


@dataclass(frozen=True)
class WatchReset:
    """Too much changed to say each: read again everything you show."""

    type: str = "reset"


#: What ``watch`` yields; a message type this version doesn't know is skipped, so the stream can grow.
WatchMessage = Union[WatchReady, WatchChange, WatchTyping, WatchReset]


def _message(raw: Any) -> Optional[WatchMessage]:
    if not isinstance(raw, dict):  # JSON that isn't an object: ignored, as an unknown type is
        return None
    kind = raw.get("type")
    if kind == "ready":
        return WatchReady(resumed=raw.get("resumed") is True)
    if kind == "reset":
        return WatchReset()
    if kind == "typing":
        return WatchTyping(channel_id=str(raw.get("channel_id") or ""), workspace_id=raw.get("workspace_id"),
                           user_id=str(raw.get("user_id") or ""), typing=raw.get("typing") is True, raw=raw)
    if kind == "change":
        parent = raw.get("parent")
        return WatchChange(
            id=str(raw.get("id") or ""), at=parse_time(raw.get("at")), object=str(raw.get("object") or ""),
            object_id=raw.get("object_id"), status=raw.get("status"),
            parent=dict(parent) if isinstance(parent, dict) else None, change=raw.get("change"),
            version=raw.get("version"), workspace_id=raw.get("workspace_id"), message_id=raw.get("message_id"),
            thread_id=raw.get("thread_id"), raw=raw)
    return None


@synced
async def watch_token(*, objects: Optional[Sequence[str]] = None, origin: Optional[str] = None, user: Any = AMBIENT,
                      client: Optional[Client] = None) -> WatchToken:
    """A single-use token for the watch socket (``POST /v1/watch/tokens``), to open within a minute: hand ``url`` and
    ``token`` to the page that connects, with its ``origin`` (the socket must then come from that page).

    Returns:
        A ``WatchToken``: the socket's ``url``, the ``token``, when it expires and when the connection it opens ends.

    Usage::

        token = noclick.watch_token(user="user_42", origin="https://app.example.com")
        return {"url": token.url, "token": token.token}
    """
    body: Dict[str, Any] = {}
    if objects is not None:
        body["objects"] = list(objects)
    if origin is not None:
        body["origin"] = origin
    raw = await resolve_client(client).request("POST", "/v1/watch/tokens", json=body, user=user)
    return WatchToken(url=raw["url"], token=raw["token"], expires_at=parse_time(raw.get("expires_at")),
                      connection_ends_at=parse_time(raw.get("connection_ends_at")), objects=list(raw.get("objects") or []),
                      user_id=raw.get("user_id"), origin=raw.get("origin"), raw=raw)


def _connector() -> Callable[..., Any]:
    try:
        from websockets.asyncio.client import connect
    except ImportError:
        raise ImportError('noclick.watch needs the websockets package: pip install "noclick[live]"') from None
    return connect


@synced
async def watch(*, objects: Optional[Sequence[str]] = None, user: Any = AMBIENT, client: Optional[Client] = None,
                token: Optional[TokenSource] = None,
                on_status: Optional[Callable[[str], None]] = None) -> AsyncIterator[WatchMessage]:
    """Follow your objects' changes until you stop reading. Reconnects by itself (a new token each time), resuming
    after the last change it gave you; raises only what trying again can't fix: the token call refused (a revoked
    key, a scope the key lacks, a deployment where watching isn't available) or ``WatchRefused``, the room refusing
    two fresh tokens in a row. ``token``: where tokens come from instead of this client, a function returning
    ``(url, token)``. ``on_status`` hears ``connecting``, ``live``, ``reconnecting`` and ``stopped``.

    A change can be lost (a deploy, a dropped connection, a busy second), and nothing says so but these: read again
    what you show on ``reset``, on a ``ready`` that didn't resume, and on a slow timer of your own if it must never be
    stale.

    Returns:
        ``WatchMessage`` values: ``ready`` as each connection opens, ``change``, ``typing`` and ``reset``.

    Usage::

        for message in noclick.watch(objects=["deployment"]):
            if message.type == "change":
                print(message.object, message.object_id, message.status)

    In async code::

        async for message in noclick.watch.aio(objects=["channel"]):
            if message.type == "change":
                await websocket.send_json(message.raw)
    """
    connect = _connector()
    status = on_status or (lambda _s: None)
    after: Optional[str] = None
    failures = refused_in_a_row = 0
    status("connecting")
    try:
        while True:
            try:
                if token is not None:
                    found = token()
                    url, secret = await found if inspect.isawaitable(found) else found
                else:
                    minted = await watch_token.aio(objects=objects, user=user, client=client)
                    url, secret = minted.url, minted.token
            except Error as err:
                if err.status is not None and err.status < 500 and err.status != 429:
                    raise
                status("reconnecting")
                await asyncio.sleep(_BACKOFF_S[min(failures, len(_BACKOFF_S) - 1)])
                failures += 1
                continue
            ready = False
            code: Optional[int] = None
            reason = ""
            try:
                async with connect(_socket_url(url), ping_interval=_PING_S, ping_timeout=_PING_S,
                                   max_size=2 ** 16) as socket:
                    await socket.send(json.dumps({"type": "auth", "token": secret, "after": after}))
                    async for frame in socket:
                        if frame == "pong":
                            continue
                        try:
                            message = _message(json.loads(frame))
                        except (TypeError, ValueError):
                            continue
                        if message is None:
                            continue
                        if isinstance(message, WatchReady):
                            ready, failures, refused_in_a_row = True, 0, 0
                            status("live")
                        elif isinstance(message, WatchChange) and message.id:
                            after = message.id
                        yield message
                    code, reason = socket.close_code, socket.close_reason or ""
            except (OSError, asyncio.TimeoutError) as exc:
                code, reason = None, str(exc)
            except Exception as exc:  # the library's connection errors: reconnect
                if type(exc).__module__.split(".")[0] != "websockets":
                    raise
                code = getattr(getattr(exc, "rcvd", None), "code", None)
                reason = getattr(getattr(exc, "rcvd", None), "reason", "") or str(exc)
            if code == CLOSE_REFUSED:
                refused_in_a_row = 1 if ready else refused_in_a_row + 1
                if refused_in_a_row >= 2:
                    raise WatchRefused(f"The watch socket was refused: {reason or 'access ended'}.",
                                       next_step="Check the key is still live and may read these objects, then "
                                                 "watch again.")
            else:
                refused_in_a_row = 0
            status("reconnecting")
            if code == CLOSE_TOO_MANY:
                await asyncio.sleep(_spread(_TOO_MANY_S))
            elif code not in (CLOSE_RENEW, CLOSE_REFUSED):
                await asyncio.sleep(_spread(_BACKOFF_S[min(failures, len(_BACKOFF_S) - 1)]))
                failures += 1
    finally:
        status("stopped")
