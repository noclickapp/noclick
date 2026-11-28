"""Hosted MCP servers: your tools at one URL for any MCP client.

    server = noclick.McpServer.from_name("crm-tools", tools=["hubspot", "search"], create_if_missing=True)
    print(server.url)   # paste into Claude, ChatGPT, Cursor or any MCP client

The tools are the ones a ``Toolkit`` or an agent takes (connections, single
operations, ``search`` and ``fetch``), served over Streamable HTTP. Calls act in
the server's user's connections, under your policy, and bill like toolkit calls.
A name that is no connection there serves an integration's operations that need
no account, on NoClick's key: ``tools=["exa.search"]`` needs no connection.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional, Sequence

from ._client import Client, resolve_client
from ._object import UNSET, Page, _Object, compact, field, list_all, list_page, parse_time
from ._sync import synced
from ._scope import AMBIENT, resolve_scope
from .connection import tool_refs
from .exceptions import Conflict, NotFound

# What ``from_name`` sets on an existing server.
_CONVERGED = ("tools",)


@dataclass(frozen=True)
class McpClient:
    """An MCP client that has connected to a server, as it named itself
    (``Claude``, ``cursor``, ``openai-mcp``). ``tool_count`` is how many tools
    it saw when it last listed them: fewer than the server serves means it
    listed them before you added some, and most clients list again only when a
    session starts."""

    name: str
    version: Optional[str]
    first_seen_at: Any
    last_seen_at: Any
    tool_count: Optional[int]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "McpClient":
        return cls(
            raw.get("name") or "unknown", raw.get("version"), parse_time(raw.get("first_seen_at")),
            parse_time(raw.get("last_seen_at")), raw.get("tool_count"), raw,
        )


class McpServer(_Object):
    """Your tools at one URL, for Claude, ChatGPT, Cursor or any MCP client.
    Anyone with ``url`` can call the tools, so keep it like a key and
    ``rotate()`` it if it leaks. ``tool_count`` is how many tools the server
    serves right now (a connection's operations count one each; a connection
    that isn't connected serves none); ``last_client_at`` is when any client last
    talked to it."""

    _repr_keys = ("id", "name", "tool_count")

    id: str = field("id")
    name: str = field("name")
    url: str = field("url", doc="The URL MCP clients connect to; the path is its secret.")
    tools: List[Any] = field(
        "tools", doc="What it serves, as you listed it: refs, and ``{tool, bind}`` for an operation with arguments bound.",
    )
    tool_count: int = field("tool_count")
    user_id: Optional[str] = field("user_id")
    created_at: Any = field("created_at", parse_time)
    last_client_at: Any = field("last_client_at", parse_time, doc="When a client last called it (None until one does).")

    def _init(self, **kwargs: Any) -> None:
        self._create_with: Optional[Dict[str, Any]] = None
        super()._init(**kwargs)

    @staticmethod
    async def _wire(body: Dict[str, Any], *, scope: Any) -> Dict[str, Any]:
        if "tools" in body:
            body = {**body, "tools": await tool_refs(body["tools"], scope=scope)}
        return body

    # --- construction ----------------------------------------------------

    @synced
    @classmethod
    async def create(
        cls,
        name: str,
        *,
        tools: Sequence[Any],
        allow_existing: bool = False,
        user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> "McpServer":
        """Create a server called ``name`` (unique per account and user; a
        duplicate raises ``noclick.Conflict`` with ``existing_id``, or with
        ``allow_existing=True`` returns the server already there, as it is: its tools don't change). ``tools`` are
        what an agent or a ``Toolkit`` takes: connections (a ``Connection`` or its
        name), single operations (``"hubspot.create_contact"``), ``"search"`` and
        ``"fetch"``, or a ``Toolkit``, at most 64 tools in all. A name is a connection
        in the server's user (the account for an account server), else an integration's
        operations that need no account (on NoClick's key), so ``"exa.search"`` needs no connection.
        Operations with arguments bound (``hubspot.only(...).bind(...)``, ``ConnectionOperations.bind``)
        keep them out of every client's reach; there ``{{user...}}`` is the server's user.

        Returns:
            The new server, with the ``url`` to give your MCP client.

        Usage::

            with noclick.as_user("acme"):
                hubspot = noclick.Connection.from_name("hubspot", integration="hubspot", create_if_missing=True)
                server = noclick.McpServer.create("crm-tools", tools=[hubspot, "search"])
            print(server.url)
        """
        scope = resolve_scope(user)
        body = await cls._wire({"name": name, "tools": tools}, scope=scope)
        raw = await cls._create_named("/v1/mcp_servers", body, allow_existing=allow_existing, user=scope, client=client)
        return cls._new(raw=raw, client=client, user=scope)

    @classmethod
    def from_name(
        cls,
        name: str,
        *,
        tools: Optional[Sequence[Any]] = None,
        create_if_missing: bool = False,
        user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> "McpServer":
        """A lazy reference to the server called ``name`` in the current (or given)
        user. Given ``tools``, it gets the server and sets them, on every run: an existing server
        whose tools differ gets yours. ``create_if_missing=True`` creates it when there's none;
        without it, a missing server raises ``noclick.NotFound``. Its URL stays the same either way. Each run is a write: set the tools at
        startup or in a setup script, and take the bare ``from_name`` in request handlers.

        Returns:
            A server that loads (or is created, or has your tools set) the first time you read a
            field. Nothing is sent yet.

        Usage:
            Serve a user's CRM and web search to their Claude::

                server = noclick.McpServer.from_name(
                    "crm-tools", tools=["hubspot", "search"], create_if_missing=True, user="acme",
                )
                print(server.url)

            Refer to one by name::

                server = noclick.McpServer.from_name("crm-tools", user="acme")
                print(server.tool_count, server.last_client_at)
        """
        server = cls._new(hints={"name": name}, client=client, user=user)
        if create_if_missing and tools is None:
            raise ValueError("McpServer.from_name(create_if_missing=True) needs tools=")
        server._define({"name": name, **({} if tools is None else {"tools": tools})},
                       create_if_missing=create_if_missing)
        return server

    @classmethod
    def from_id(cls, server_id: str, *, client: Optional[Client] = None, user: Any = AMBIENT) -> "McpServer":
        """A lazy reference to a server by id.

        Returns:
            A server that loads the first time you read a field. Nothing is sent yet.

        Usage::

            server = noclick.McpServer.from_id("6f1d8b3a-2c7e-4a9f-b0d5-3e8c1a7f4b92")
            for client in server.clients():
                print(client.name, client.last_seen_at)
        """
        return cls._new(hints={"id": server_id}, client=client, user=user)

    @synced
    @classmethod
    async def get(cls, server_id: str, *, user: Any = AMBIENT, client: Optional[Client] = None) -> "McpServer":
        """Load a server by id now; an unknown id raises ``noclick.NotFound``.

        Returns:
            The server, loaded.

        Usage::

            server = noclick.McpServer.get("6f1d8b3a-2c7e-4a9f-b0d5-3e8c1a7f4b92")
            print(server.name, server.url, server.tools)
        """
        server = cls.from_id(server_id, client=client, user=user)
        await server._ensure()
        return server

    @synced
    @classmethod
    async def list(
        cls, *, limit: Optional[int] = None, user_filter: Any = None, user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> List["McpServer"]:
        """The current user's servers (the account's own outside ``as_user``, or those ``user_filter`` covers).

        Returns:
            Every matching server, newest first, fetched page by page.

        Usage::

            for server in noclick.McpServer.list(user_filter=noclick.ALL_USERS):
                print(server.name, server.user_id, server.tool_count, server.last_client_at)
        """
        return await list_all(
            "/v1/mcp_servers", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            user=user, user_filter=user_filter, limit=limit, client=client,
        )

    @synced
    @classmethod
    async def list_page(
        cls, *, cursor: Optional[str] = None, limit: Optional[int] = None, user_filter: Any = None,
        user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> Page:
        """One page of servers; pass ``next_cursor`` back as ``cursor``.

        Returns:
            A page whose ``data`` holds the servers and whose ``next_cursor`` is ``None`` on the last page.

        Usage::

            page = noclick.McpServer.list_page(limit=50)
            while True:
                for server in page.data:
                    print(server.name)
                if page.next_cursor is None:
                    break
                page = noclick.McpServer.list_page(limit=50, cursor=page.next_cursor)
        """
        return await list_page(
            "/v1/mcp_servers", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            user=user, user_filter=user_filter, cursor=cursor, limit=limit, client=client,
        )

    # --- hydration -------------------------------------------------------

    async def _load(self) -> Dict[str, Any]:
        server_id = self._known("id")
        if server_id:
            return await self._request("GET", f"/v1/mcp_servers/{server_id}")
        name = self._hints["name"]
        page = await self._request("GET", "/v1/mcp_servers", params={"name": name}) or {}
        rows = [row for row in page.get("data") or [] if row.get("name") == name]
        if rows:
            return await self._converge(rows[0])
        if not self._creates:
            raise NotFound(
                f"No MCP server is named {name!r}.",
                next_step="Create it with noclick.McpServer.create(...) or pass create_if_missing=True.",
                details={"name": name, "kind": "mcp_server"},
            )
        try:
            body = await self._wire(self._create_with, scope=self._scope)
            return await self._request("POST", "/v1/mcp_servers", json=body)
        except Conflict as exc:  # created concurrently
            if not exc.existing_id:
                raise
            return await self._converge(await self._request("GET", f"/v1/mcp_servers/{exc.existing_id}"))

    async def _converge(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Set the tools ``from_name`` was given on an existing server."""
        if self._create_with is None:
            return raw
        wanted = await self._wire(
            {k: v for k, v in self._create_with.items() if k in _CONVERGED}, scope=self._scope,
        )
        changes = {k: v for k, v in wanted.items() if raw.get(k) != v}
        if not changes:
            return raw
        return await self._request("PATCH", f"/v1/mcp_servers/{raw['id']}", json=changes)

    async def _path(self) -> str:
        return f"/v1/mcp_servers/{(await self._ensure())['id']}"

    # --- management ------------------------------------------------------

    @synced
    async def update(self, *, tools: Any = UNSET, name: Any = UNSET) -> "McpServer":
        """Change what it serves, or its name; the URL stays. A connected client
        sees new tools when it next lists them (most do when a session starts).

        Returns:
            This server, updated.

        Usage::

            server = noclick.McpServer.from_name("crm-tools", user="acme")
            server.update(tools=["hubspot", "search", "fetch"])
        """
        changes = compact(name=None if name is UNSET else name)
        if tools is not UNSET:
            changes["tools"] = await tool_refs(tools, scope=self._call_scope())
        self._raw = await self._request("PATCH", await self._path(), json=changes)
        return self

    @synced
    async def rotate(self) -> "McpServer":
        """Give it a new URL; the old one stops answering at once, so reconnect
        your clients with the new one.

        Returns:
            This server, with its new ``url``.

        Usage::

            server = noclick.McpServer.from_name("crm-tools", user="acme")
            server.rotate()
            print(server.url)
        """
        self._raw = await self._request("POST", f"{await self._path()}/rotate")
        return self

    @synced
    async def clients(self) -> List[McpClient]:
        """The MCP clients that have connected, most recently seen first: whether
        your agent has actually started using the server, apart from whether the
        server is ready.

        Returns:
            Each client's ``name`` and ``version`` as it reported them, when it was first and last seen,
            and how many tools it listed. An empty list until a client connects.

        Usage::

            server = noclick.McpServer.from_name("crm-tools", user="acme")
            for client in server.clients():
                print(client.name, client.version, client.last_seen_at, client.tool_count)
        """
        response = await self._request("GET", f"{await self._path()}/clients") or {}
        return [McpClient._from(row) for row in response.get("data") or []]

    @synced
    async def delete(self) -> None:
        """Delete the server; its URL stops answering. The connections it served stay.

        Usage::

            noclick.McpServer.from_name("crm-tools", user="acme").delete()
        """
        await self._request("DELETE", await self._path())
