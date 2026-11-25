"""Room: a realtime room's server side. Publish to the pages in it, see who's there, ask them, and mint a token for a
page to join (the TypeScript SDK's ``Room.join``).

Rooms are named by what they're about: ``workflow:{id}`` (everyone who may open the workflow) and ``owner`` (your own
open tabs, as a signed-in person). Publishing and asking need edit access to a workflow's room; an event you publish
names you (``from``), where NoClick's own events name nobody.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from ._client import Client, resolve_client
from ._object import parse_time
from ._sync import synced


@dataclass(frozen=True)
class RoomMember:
    """One member of a room: a page (``user`` who they are, ``color`` the room gave them, ``data`` what they say of
    themselves) or one NoClick holds (``server``: an agent's sandbox at work, ``user`` None)."""

    id: str
    user: Optional[Dict[str, Any]]
    color: Optional[str]
    data: Dict[str, Any]
    server: bool
    joined_at: Optional[datetime]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "RoomMember":
        raw = raw if isinstance(raw, dict) else {}
        joined = raw.get("joined_at")
        return cls(str(raw.get("id") or ""), raw.get("user") if isinstance(raw.get("user"), dict) else None,
                   raw.get("color"), raw.get("data") if isinstance(raw.get("data"), dict) else {},
                   raw.get("server") is True,
                   datetime.fromtimestamp(joined / 1000, timezone.utc) if isinstance(joined, (int, float)) else None,
                   raw)


@dataclass(frozen=True)
class RoomEvent:
    """What was published in a room: its ``id`` (what ``history(since=)`` reads after), its name, its data, and who
    published it (``from_``; None for NoClick's own)."""

    id: str
    event: str
    data: Any
    from_: Optional[Dict[str, Any]]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "RoomEvent":
        raw = raw if isinstance(raw, dict) else {}
        sender = raw.get("from")
        return cls(str(raw.get("id") or ""), str(raw.get("event") or ""), raw.get("data"),
                   sender if isinstance(sender, dict) else None, raw)


@dataclass(frozen=True)
class RoomToken:
    """A single-use token for a room's socket: hand ``url`` and ``token`` to the page that joins, within a minute."""

    url: str
    token: str
    access: str
    expires_at: Optional[datetime]
    connection_ends_at: Optional[datetime]
    raw: Dict[str, Any] = dc_field(repr=False)


class Room:
    """A room by its name (``workflow:{id}``, ``owner``). Nothing is read until you call a method.

    Usage::

        room = noclick.Room(f"workflow:{workflow_id}")
        print([m.user["name"] for m in room.members() if m.user])
    """

    def __init__(self, name: str, *, client: Optional[Client] = None) -> None:
        self.name = name
        self._client = client

    def __repr__(self) -> str:
        return f"Room({self.name!r})"

    def _path(self, tail: str) -> str:
        return f"/v1/rooms/{quote(self.name, safe='')}/{tail}"

    @synced
    async def members(self) -> List[RoomMember]:
        """Who is in the room now, each as the room shows them.

        Returns:
            Every member: the pages in the room, and the members NoClick holds (``server``).

        Usage::

            for member in noclick.Room(f"workflow:{workflow_id}").members():
                print(member.user and member.user["name"], member.data.get("selection"))
        """
        raw = await resolve_client(self._client).request("GET", self._path("presence"))
        return [RoomMember._from(m) for m in (raw.get("data") or [])]

    @synced
    async def history(self, *, since: Optional[str] = None) -> Dict[str, Any]:
        """The room's recent events (at most its last 500 of the last ten minutes), after ``since`` when it names one
        still kept.

        Returns:
            ``{"events": [RoomEvent, ...], "reset": bool}``; ``reset`` True when ``since`` was too old, so read what
            you show again.

        Usage::

            found = noclick.Room(f"workflow:{workflow_id}").history(since=last_id)
            for event in found["events"]:
                print(event.event, event.data)
        """
        raw = await resolve_client(self._client).request("GET", self._path("events"),
                                                         params={"since": since} if since else None)
        return {"events": [RoomEvent._from(e) for e in (raw.get("data") or [])], "reset": raw.get("reset") is True}

    @synced
    async def publish(self, event: str, data: Any = None) -> str:
        """Publishes ``event`` (lower case: letters, digits, ``_ . : -``) with ``data`` (at most 64 KB as JSON) to
        everyone in the room, named as from you.

        Returns:
            The event's id in the room.

        Usage::

            noclick.Room(f"workflow:{workflow_id}").publish("review.ready", {"step": "draft"})
        """
        raw = await resolve_client(self._client).request("POST", self._path("events"),
                                                         json={"event": event, "data": data})
        return str(raw.get("id") or "")

    @synced
    async def ask(self, name: str, args: Optional[Dict[str, Any]] = None, *, timeout: float = 10.0,
                  collect_ms: int = 0) -> Dict[str, Any]:
        """Asks the room's pages that answer ``name`` (the TypeScript SDK's ``room.answer``) and waits for an
        answer, at most ``timeout`` seconds (25 at most). With ``collect_ms``, waits that long after the first answer
        for the others'.

        Returns:
            ``{"answer": {...}}`` (or ``{"answers": [...]}`` collecting), each naming the member that gave it, or
            ``{"error": "no_viewer" | "timeout"}``.

        Usage::

            reply = noclick.Room(f"workflow:{workflow_id}").ask("canvas.get_selected", timeout=5)
        """
        body = {"name": name, "args": args or {}, "timeout_s": timeout, "collect_ms": collect_ms}
        raw = await resolve_client(self._client).request("POST", self._path("ask"), json=body, timeout=timeout + 10)
        return {k: v for k, v in raw.items() if k != "object"}

    @synced
    async def token(self, *, origin: Optional[str] = None) -> RoomToken:
        """A single-use token for a page to join the room with (``Room.join(name, {token})`` in TypeScript): pass
        ``url`` and ``token`` on as they are. ``origin`` is the page's (``location.origin``); the socket must come from
        it.

        Returns:
            The token, the socket's ``url`` (carrying its ticket) and what it lets the page do (``access``).

        Usage::

            token = noclick.Room(f"workflow:{workflow_id}").token(origin="https://app.example.com")
            return {"url": token.url, "token": token.token}
        """
        raw = await resolve_client(self._client).request("POST", self._path("tokens"),
                                                         json={"origin": origin} if origin else {})
        return RoomToken(str(raw.get("url") or ""), str(raw.get("token") or ""), str(raw.get("access") or "view"),
                         parse_time(raw.get("expires_at")), parse_time(raw.get("connection_ends_at")), raw)


__all__ = ["Room", "RoomEvent", "RoomMember", "RoomToken"]
