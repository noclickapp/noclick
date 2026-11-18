"""Tool calls: every integration run, capability call and agent tool call
your platform work made, newest first.

    page = noclick.ToolCall.list_page(tool="gmail.*", status="error", user_filter=noclick.ALL_USERS)
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional

from ._client import Client, resolve_client
from ._object import Page, iso_time, list_all, list_page, parse_time, read_scope, ref_id, required_number
from ._sync import synced
from ._scope import AMBIENT

_PATH = "/v1/tool_calls"


async def _params(agent: Any, tool: Optional[str], status: Optional[str], source: Optional[str],
                  since: Any, until: Any) -> Dict[str, Any]:
    return {
        "agent_id": await ref_id(agent), "tool": tool, "status": status, "source": source,
        "since": iso_time(since), "until": iso_time(until),
    }


@dataclass(frozen=True)
class ToolCallSummary:
    """How many calls match, and how many of them errored."""

    total: int
    success: int
    error: int
    raw: Dict[str, Any] = dc_field(repr=False)


@dataclass(frozen=True)
class ToolCall:
    """One recorded tool call. ``tool_name`` is the name policy judges it by: dotted
    (``gmail.send_email_message``), or a capability's own (``search``, ``fetch``, an agent's too).
    ``source`` is ``api`` (your own calls), ``agent`` (your agents' turns) or
    ``mcp_server`` (an MCP client's, through the hosted server ``mcp_server_id``)."""

    id: str
    tool_name: str
    tool_type: Optional[str]
    operation: Optional[str]
    status: Optional[str]
    error: Optional[str]
    arguments: Dict[str, Any]
    result_preview: Optional[str]
    duration_ms: Optional[int]
    credential_id: Optional[str]
    user_id: Optional[str]
    agent_id: Optional[str]
    conversation: Optional[str]
    execution_id: Optional[str]
    source: Optional[str]
    created_at: Any
    raw: Dict[str, Any] = dc_field(repr=False)
    mcp_server_id: Optional[str] = None
    #: The connection it ran on, as the account names it (a named connection's name, else its name in the app).
    connection: Optional[str] = None

    @classmethod
    def _from(cls, raw: Dict[str, Any], _scope: Any = None) -> "ToolCall":
        return cls(
            id=raw.get("id"), tool_name=raw.get("tool_name") or "", tool_type=raw.get("tool_type"),
            operation=raw.get("operation"), status=raw.get("status"), error=raw.get("error"),
            arguments=dict(raw.get("arguments") or {}), result_preview=raw.get("result_preview"),
            duration_ms=raw.get("duration_ms"), credential_id=raw.get("credential_id"),
            user_id=raw.get("user_id"), agent_id=raw.get("agent_id"), conversation=raw.get("conversation"),
            execution_id=raw.get("execution_id"), source=raw.get("source"),
            created_at=parse_time(raw.get("created_at")), raw=raw, mcp_server_id=raw.get("mcp_server_id"),
            connection=raw.get("connection"),
        )

    @synced
    @classmethod
    async def list(
        cls, *, agent: Any = None, tool: Optional[str] = None, status: Optional[str] = None,
        source: Optional[str] = None, since: Any = None, until: Any = None, limit: Optional[int] = None,
        user_filter: Any = None, user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> List["ToolCall"]:
        """Every matching call (or the first ``limit``). ``tool`` is a name or a
        ``*`` pattern (``gmail.*``); ``status`` ``success``/``error``;
        ``source`` ``api`` (your calls), ``agent`` (your agents' turns) or
        ``mcp_server`` (MCP clients' calls through your hosted servers).

        Returns:
            Every matching call, newest first, fetched page by page.

        Usage:
            See which Gmail calls your agents got wrong in the last day::

                from datetime import datetime, timedelta, timezone

                yesterday = datetime.now(timezone.utc) - timedelta(days=1)
                for call in noclick.ToolCall.list(tool="gmail.*", status="error", source="agent", since=yesterday):
                    print(call.tool_name, call.error)

            Or one agent's calls, across every user::

                support = noclick.Agent.from_name("support")
                calls = noclick.ToolCall.list(agent=support, user_filter=noclick.ALL_USERS, limit=50)

            Or what MCP clients did through a user's hosted server::

                server = noclick.McpServer.from_name("crm-tools", user="acme")
                for call in noclick.ToolCall.list(source="mcp_server", user="acme", limit=50):
                    if call.mcp_server_id == server.id:
                        print(call.tool_name, call.status, call.created_at)
        """
        params = await _params(agent, tool, status, source, since, until)
        return await list_all(
            _PATH, cls._from, params=params, user=user, user_filter=user_filter, limit=limit, client=client,
        )

    @synced
    @classmethod
    async def list_page(
        cls, *, cursor: Optional[str] = None, limit: Optional[int] = None, agent: Any = None,
        tool: Optional[str] = None, status: Optional[str] = None, source: Optional[str] = None,
        since: Any = None, until: Any = None, user_filter: Any = None, user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> Page:
        """One page of matching calls; pass ``next_cursor`` back as ``cursor``.

        Returns:
            A page whose ``data`` holds up to ``limit`` calls (at most 200) and whose ``next_cursor``
            is ``None`` on the last page.

        Usage::

            page = noclick.ToolCall.list_page(status="error", limit=200)
            while True:
                for call in page.data:
                    print(call.tool_name, call.error)
                if page.next_cursor is None:
                    break
                page = noclick.ToolCall.list_page(status="error", limit=200, cursor=page.next_cursor)
        """
        params = await _params(agent, tool, status, source, since, until)
        return await list_page(
            _PATH, cls._from, params=params, user=user, user_filter=user_filter,
            cursor=cursor, limit=limit, client=client,
        )

    @synced
    @classmethod
    async def summary(
        cls, *, agent: Any = None, tool: Optional[str] = None, status: Optional[str] = None,
        source: Optional[str] = None, since: Any = None, until: Any = None,
        user_filter: Any = None, user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> ToolCallSummary:
        """How many calls match the same filters, and how many errored.

        Returns:
            The ``total``, split into ``success`` and ``error``.

        Usage::

            from datetime import datetime, timedelta, timezone

            yesterday = datetime.now(timezone.utc) - timedelta(days=1)
            counts = noclick.ToolCall.summary(tool="gmail.*", since=yesterday)
            print(counts.total, counts.success, counts.error)
        """
        scope, user_id = await read_scope(user, user_filter)
        params = {**await _params(agent, tool, status, source, since, until), "user_id": user_id}
        raw = await resolve_client(client).request("GET", f"{_PATH}/summary", params=params, user=scope) or {}
        return ToolCallSummary(*(int(required_number(raw, k)) for k in ("total", "success", "error")), raw)
