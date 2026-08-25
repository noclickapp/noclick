"""Tests for MCP Server node OAuth token refresh on the execute path.

MCP servers use rotating OAuth 2.1; the stored access token expires and is
frozen into every emitted tool definition. The node must refresh it at
discovery time. The MCPServerCredentials model strips the rotation material, so
the node re-loads the full credential by oauth_credential_id and routes through
the shared refresh choke point. These tests pin that behavior.

Run: pytest nodes/tests/test_mcp_server_node_oauth.py -v
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from nodes.mcp_server_node import MCPServerNode, MCPServerCredentials


def _iso(delta_seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)).isoformat()


def _node():
    node = MCPServerNode("n", "automation-mcp-server", {})
    node.user_id = "uid"
    return node


class TestMCPOAuthRefresh:
    async def test_refreshes_expired_token_and_persists(self):
        creds = MCPServerCredentials(
            auth_type="oauth", oauth_credential_id="cid", access_token="stale"
        )
        stored = {
            "access_token": "stale", "refresh_token": "r1", "expires_at": _iso(-3600),
            "token_endpoint": "https://srv/token", "client_id": "client-1",
        }
        fresh = SimpleNamespace(
            access_token="fresh-token", refresh_token="r2",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            scope=None, token_type="Bearer",
        )
        with patch(
            "utils.credential_loader.load_credential",
            new=AsyncMock(return_value=dict(stored)),
        ), patch(
            "nodes.oauth.mcp_oauth.refresh_access_token",
            new=AsyncMock(return_value=fresh),
        ) as refresh, patch(
            "utils.credentials.update_credential_data_detailed", new=AsyncMock(return_value=(1, None))
        ):
            token = await _node()._ensure_fresh_oauth_token(creds)
        refresh.assert_awaited_once()
        assert token == "fresh-token"

    async def test_no_refresh_when_token_still_valid(self):
        creds = MCPServerCredentials(
            auth_type="oauth", oauth_credential_id="cid", access_token="stale"
        )
        stored = {
            "access_token": "db-token", "refresh_token": "r1", "expires_at": _iso(3600),
            "token_endpoint": "https://srv/token", "client_id": "client-1",
        }
        with patch(
            "utils.credential_loader.load_credential",
            new=AsyncMock(return_value=dict(stored)),
        ), patch(
            "nodes.oauth.mcp_oauth.refresh_access_token", new=AsyncMock()
        ) as refresh:
            token = await _node()._ensure_fresh_oauth_token(creds)
        refresh.assert_not_awaited()
        assert token == "db-token"  # the fresh stored token, no refresh needed

    async def test_no_oauth_credential_id_returns_stored_token(self):
        creds = MCPServerCredentials(auth_type="oauth", access_token="only-this")
        with patch("nodes.oauth.mcp_oauth.refresh_access_token", new=AsyncMock()) as refresh:
            token = await _node()._ensure_fresh_oauth_token(creds)
        refresh.assert_not_awaited()
        assert token == "only-this"

    async def test_missing_rotation_material_returns_stored_token(self):
        # A credential without token_endpoint can't be refreshed; fall back to
        # the stored token rather than erroring.
        creds = MCPServerCredentials(
            auth_type="oauth", oauth_credential_id="cid", access_token="stale"
        )
        stored = {"access_token": "stale", "refresh_token": "r1", "expires_at": _iso(-3600)}
        with patch(
            "utils.credential_loader.load_credential",
            new=AsyncMock(return_value=dict(stored)),
        ), patch(
            "nodes.oauth.mcp_oauth.refresh_access_token", new=AsyncMock()
        ) as refresh:
            token = await _node()._ensure_fresh_oauth_token(creds)
        refresh.assert_not_awaited()
        assert token == "stale"
