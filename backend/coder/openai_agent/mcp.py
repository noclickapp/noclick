"""MCP client helpers for the OpenAI Agents SDK-backed Agent.

Replaces the OpenHands-coupled MCP path that lived in
``coder/openhands/mcp/*``. Two public helpers:

  - ``discover_tools(server_config) -> list[dict]``
        Connect to an MCP server, list its tools, and return them in the
        shape ``nodes/mcp_server_node.py`` already publishes downstream.

  - ``call_tool(server_config, tool_name, arguments) -> dict``
        Invoke one tool on an MCP server. Returns the
        ``{"success": True, "result": ...}`` / ``{"success": False, "error": ...}``
        contract that ``nodes/agent/tool_execution.py`` already expects.

Both helpers fully own the connection lifecycle: open transport, open
``ClientSession``, initialize, do the work, close everything on every
exit path (including exceptions). The official ``mcp`` SDK ties stream
+ session lifetime to ``async with`` blocks, so cleanup is intrinsic —
no per-Agent connection pool to leak the way OpenHands' ``MCPClient``
wrapper did.

Transport selection mirrors ``MCPServerConfig.transport_type``:
  - ``'shttp'`` → ``streamablehttp_client`` (Streamable HTTP, the modern transport)
  - ``'sse'``   → ``sse_client``           (Server-Sent Events, legacy fallback)

Authentication is collapsed into a single ``headers`` dict before we
hand off to the transport. The MCP SDK transports accept headers
natively, so the OpenHands ``connect_http_with_custom_headers``
monkey-patch is obsolete.
"""
from __future__ import annotations

import contextlib
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client

logger = logging.getLogger(__name__)


# Always-on Accept header. Some MCP servers (notably Notion) reject
# requests that don't advertise both JSON and SSE. Matches the value
# the OpenHands fork was sending after our patch.
_DEFAULT_ACCEPT = "application/json, text/event-stream"


def _build_headers(
    *,
    api_key: Optional[str],
    access_token: Optional[str],
    custom_headers: Optional[Dict[str, str]],
) -> Dict[str, str]:
    """Build the HTTP headers dict for an MCP request.

    Auth precedence: OAuth access_token > api_key. Custom headers
    overlay last so callers can override anything if they need to.
    """
    headers: Dict[str, str] = {"Accept": _DEFAULT_ACCEPT}

    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    elif api_key:
        # Match OpenHands' multi-header layout — different servers read
        # different header names (Authorization, 's', X-Session-API-Key).
        headers["Authorization"] = f"Bearer {api_key}"
        headers["s"] = api_key
        headers["X-Session-API-Key"] = api_key

    if custom_headers:
        headers.update(custom_headers)

    return headers


# MCP-recommended timeouts. ``streamable_http_client`` documents 30s
# connect / 300s read for SSE-style long-poll streams. We match those so
# behavior is identical to the SDK default when callers don't customize.
_HTTP_TIMEOUT = httpx.Timeout(connect=30.0, read=300.0, write=30.0, pool=30.0)


@contextlib.asynccontextmanager
async def _transport(
    url: str, transport_type: str, headers: Dict[str, str]
) -> AsyncIterator[tuple]:
    """Open the right MCP transport for ``transport_type``.

    Both transports yield streams that ClientSession consumes. Callers
    use ``async with _transport(...) as streams: ...`` and then nest a
    ``ClientSession(*streams[:2])`` inside.

    For Streamable HTTP we build the ``httpx.AsyncClient`` ourselves
    because the SDK's new ``streamable_http_client`` puts headers on the
    client, not on a kwarg. We own that client's lifecycle so it always
    closes — even if MCP handshake raises.
    """
    if transport_type == "shttp":
        async with httpx.AsyncClient(headers=headers, timeout=_HTTP_TIMEOUT) as client:
            async with streamable_http_client(url, http_client=client) as streams:
                yield streams
        return
    if transport_type == "sse":
        async with sse_client(url, headers=headers) as streams:
            yield streams
        return
    raise ValueError(f"Unsupported MCP transport_type: {transport_type!r}")


def _normalize_content(content: List[Any]) -> Any:
    """Convert CallToolResult.content into a JSON-friendly value.

    The SDK returns a list of TextContent / ImageContent / AudioContent /
    ResourceLink / EmbeddedResource. The Agent node consuming this
    result downstream expects either a plain string (text-only case,
    by far the common one) or a list of dicts. Match that.
    """
    if not content:
        return ""

    # Text-only fast path: 1+ TextContent → concatenated string.
    if all(getattr(c, "type", None) == "text" for c in content):
        return "".join(getattr(c, "text", "") for c in content)

    # Heterogeneous content → dump each item to a dict. Pydantic's
    # model_dump preserves the discriminator (.type) so the consumer
    # can branch on type if it wants to.
    return [c.model_dump(mode="json") for c in content]


async def discover_tools(server_config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """List the tools exposed by an MCP server.

    Args:
        server_config: dict with keys
            url (str), transport_type ('shttp' | 'sse'),
            api_key (str | None), access_token (str | None),
            custom_headers (dict | None).

    Returns:
        Each entry is a dict with keys:
            name (str)           — tool name as the server reports it
            description (str)    — tool description (server may omit)
            inputSchema (dict)   — JSON Schema for arguments

        Matches the shape ``nodes/mcp_server_node.py`` was already
        massaging out of OpenHands' MCPClient.
    """
    url = server_config["url"]
    transport_type = server_config.get("transport_type", "shttp")
    headers = _build_headers(
        api_key=server_config.get("api_key"),
        access_token=server_config.get("access_token"),
        custom_headers=server_config.get("custom_headers"),
    )

    tools_out: List[Dict[str, Any]] = []
    async with _transport(url, transport_type, headers) as streams:
        read, write = streams[0], streams[1]
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            for tool in result.tools:
                tools_out.append(
                    {
                        "name": tool.name,
                        "description": tool.description or "",
                        "inputSchema": tool.inputSchema or {},
                    }
                )

    logger.info("[mcp] discovered %d tool(s) from %s", len(tools_out), url)
    return tools_out


async def call_tool(
    server_config: Dict[str, Any],
    tool_name: str,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """Invoke one tool on an MCP server.

    Returns the wire-format the Agent node already expects:
        {"success": True,  "result": <text or list-of-dicts>}
        {"success": False, "error":  <message>}

    A non-2xx HTTP response or transport-level failure raises an
    exception out of the SDK, which we catch and translate into the
    error shape.
    """
    url = server_config["url"]
    transport_type = server_config.get("transport_type", "shttp")
    headers = _build_headers(
        api_key=server_config.get("api_key"),
        access_token=server_config.get("access_token"),
        custom_headers=server_config.get("custom_headers"),
    )

    try:
        async with _transport(url, transport_type, headers) as streams:
            read, write = streams[0], streams[1]
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments=arguments)
                # Server-reported error (isError flag) — surface as
                # success=False so the Agent can decide to retry / give up
                # without us raising and aborting the whole turn.
                if result.isError:
                    err_text = _normalize_content(result.content) or "MCP tool reported isError"
                    logger.warning(
                        "[mcp] tool %s on %s returned isError: %s",
                        tool_name, url, str(err_text)[:300],
                    )
                    return {"success": False, "error": str(err_text)}

                return {"success": True, "result": _normalize_content(result.content)}

    except Exception as e:
        logger.error(
            "[mcp] tool %s on %s failed: %s", tool_name, url, e, exc_info=True,
        )
        return {"success": False, "error": f"MCP tool execution failed: {e}"}
