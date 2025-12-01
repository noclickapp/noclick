"""
MCP OAuth Authentication module.

Provides OAuth 2.1 authentication for external MCP clients (Cursor, Claude Code, etc.)
to connect to NoClick's MCP server with browser-based "Continue with NoClick" consent flow.
"""

from mcp_adapter.auth.tokens import issue_mcp_token, verify_mcp_token
from mcp_adapter.auth.storage import MCPOAuthStorage
from mcp_adapter.auth.endpoints import create_mcp_oauth_router

__all__ = [
    "issue_mcp_token",
    "verify_mcp_token",
    "MCPOAuthStorage",
    "create_mcp_oauth_router",
]
