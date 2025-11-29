"""
MCP (Model Context Protocol) integration for NoClick.

Provides Socket.IO-based MCP tools with request-response correlation
and OAuth 2.1 authentication for external MCP clients.
"""

from .mcp_socket_adapter import MCPSocketAdapter
from .mcp_socket_context import SocketContext, get_active_mcp_context

__all__ = ['MCPSocketAdapter', 'SocketContext', 'get_active_mcp_context']
