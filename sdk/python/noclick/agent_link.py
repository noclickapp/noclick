"""AgentLink: an agent step's public chat page, as its visitor talks through it. The link is the capability, so it
takes no key: a public page talks to the agent with it alone."""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from ._client import Client
from ._sync import synced
from ._object import parse_time
from .room import RoomToken

_VISITOR_HEADER = "NoClick-Visitor"


@dataclass(frozen=True)
class AgentLinkThread:
    """A visitor's thread with the agent (``AgentLink.thread``): its conversation's id and its messages, oldest
    first."""

    conversation: str
    messages: List[Dict[str, Any]] = dc_field(default_factory=list)


class AgentLink:
    """An agent step's public chat page (``/a/{id}``), as one visitor talks through it. Anyone holding the link talks
    to the agent, billed to the workflow's owner, who turns it off or rotates it from the step's share link. A visitor
    is named by an id their browser keeps (a UUID), and each of their threads by a ``chat`` key; they read their own
    threads alone.

    Usage::

        link = noclick.AgentLink(link_id, visitor=visitor_id)
        link.send("Do you ship to Canada?")
        print(link.thread().messages)
    """

    def __init__(self, link_id: str, *, visitor: str, base_url: Optional[str] = None) -> None:
        self.id = link_id
        self.visitor = visitor
        self._client = Client(api_key="", base_url=base_url, headers={_VISITOR_HEADER: visitor})

    def __repr__(self) -> str:
        return f"noclick.AgentLink(id={self.id!r})"

    def _path(self, suffix: str = "messages") -> str:
        return f"/v1/public/agent_links/{quote(self.id, safe='')}/{suffix}"

    @synced
    async def send(self, text: str, *, chat: str = "main") -> str:
        """Say something to the agent in the visitor's thread ``chat`` (a new key starts a new thread). It returns
        once the agent's turn is under way; read its reply back with ``thread()``. Raises ``noclick.Conflict``
        (``details["reason"]`` ``busy``) while the thread's last message is still being handed to the agent,
        ``noclick.NotAvailable`` when the agent can't take a turn, and ``noclick.NotFound`` once the link is off.

        Returns:
            The thread's conversation id.

        Usage::

            noclick.AgentLink(link_id, visitor=visitor_id).send("Hi!")
        """
        raw = await self._client.request("POST", self._path(), json={"text": text, "chat": chat}, user=None,
                                         anonymous=True)
        return str(raw["conversation"])

    @synced
    async def thread(self, *, chat: str = "main") -> AgentLinkThread:
        """The visitor's thread ``chat``, as the page shows it.

        Returns:
            The ``AgentLinkThread``.

        Usage::

            for message in noclick.AgentLink(link_id, visitor=visitor_id).thread().messages:
                print(message["role"], message.get("message"))
        """
        raw = await self._client.request("GET", self._path(), params={"chat": chat}, user=None, anonymous=True)
        return AgentLinkThread(str(raw["conversation"]), [m for m in raw.get("messages") or [] if isinstance(m, dict)])

    @synced
    async def room_token(self, *, chat: str = "main", origin: Optional[str] = None) -> RoomToken:
        """A single-use token for the room of the visitor's thread ``chat``, where its turns' frames
        (``chat:message``, ``agent:state``) arrive as they happen: a page joins with it (``AgentLink.join`` in
        TypeScript). View-only. ``origin`` is the page's (``location.origin``); the socket must come from it.

        Returns:
            The token, the socket's ``url`` (carrying its ticket) and what it lets the page do (``view``).

        Usage::

            token = noclick.AgentLink(link_id, visitor=visitor_id).room_token(origin="https://chat.example.com")
            return {"url": token.url, "token": token.token}
        """
        body: Dict[str, Any] = {"chat": chat, **({"origin": origin} if origin else {})}
        raw = await self._client.request("POST", self._path("room"), json=body, user=None, anonymous=True)
        return RoomToken(str(raw.get("url") or ""), str(raw.get("token") or ""), str(raw.get("access") or "view"),
                         parse_time(raw.get("expires_at")), parse_time(raw.get("connection_ends_at")), raw)
