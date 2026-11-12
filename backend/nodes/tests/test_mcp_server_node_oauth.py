"""Tests for MCP Server node OAuth token refresh on the execute path.

MCP servers use rotating OAuth 2.1; a stored access token expires. The step
signs in through the credential it ran with (``nodes.agent.mcp_auth``), which
re-reads the full stored credential (the MCPServerCredentials model strips the
rotation material) and routes it through the shared refresh choke point, as
each of an agent's calls does. These tests pin that behavior at discovery.

Run: pytest nodes/tests/test_mcp_server_node_oauth.py -v
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from nodes.mcp_server_node import MCPServerConfig, MCPServerCredentials, MCPServerNode, MCPServerNodeConfig

URL = "https://srv/mcp"


def _iso(delta_seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)).isoformat()


def _node(credentials, credential_id=None):
    config = MCPServerNodeConfig(config=MCPServerConfig(server_url=URL), credentials=credentials)
    return MCPServerNode("n", "mcp-server", {"credential_id": credential_id} if credential_id else {}, config,
                         workflow_id="wf", user_id="uid")


async def _signed_in_with(node, stored=None):
    """Run discovery; the access token it signed in with."""
    with patch("nodes.core.run_op.resolve_credential_with_owner_fallback",
               new=AsyncMock(return_value=dict(stored) if stored else None)), \
            patch("utils.credential_loader.load_credential",
                  new=AsyncMock(return_value=dict(stored) if stored else None)), \
            patch("coder.openai_agent.mcp.discover_tools", new=AsyncMock(return_value=[])) as discover:
        output = await node.execute({})
    assert output.get("error") is None, output
    return discover.await_args.args[0].get("access_token")


class TestMCPOAuthRefresh:
    async def test_refreshes_expired_token_and_persists(self):
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
            "nodes.oauth.mcp_oauth.refresh_access_token",
            new=AsyncMock(return_value=fresh),
        ) as refresh, patch(
            "utils.credentials.update_credential_data_detailed", new=AsyncMock(return_value=(1, None))
        ) as persisted:
            token = await _signed_in_with(_node(MCPServerCredentials(auth_type="oauth", access_token="stale"),
                                                "cid"), stored)
        refresh.assert_awaited_once()
        persisted.assert_awaited()
        assert token == "fresh-token"

    async def test_no_refresh_when_token_still_valid(self):
        stored = {
            "access_token": "db-token", "refresh_token": "r1", "expires_at": _iso(3600),
            "token_endpoint": "https://srv/token", "client_id": "client-1",
        }
        with patch(
            "nodes.oauth.mcp_oauth.refresh_access_token", new=AsyncMock()
        ) as refresh:
            token = await _signed_in_with(_node(MCPServerCredentials(auth_type="oauth", access_token="db-token"),
                                                "cid"), stored)
        refresh.assert_not_awaited()
        assert token == "db-token"  # the fresh stored token, no refresh needed

    async def test_a_token_typed_into_the_step_is_used_as_it_is(self):
        # No credential row holds it, so there is nothing to refresh against.
        with patch("nodes.oauth.mcp_oauth.refresh_access_token", new=AsyncMock()) as refresh:
            token = await _signed_in_with(_node(MCPServerCredentials(auth_type="oauth", access_token="only-this")))
        refresh.assert_not_awaited()
        assert token == "only-this"

    async def test_a_typed_sign_in_naming_its_credential_refreshes_through_it(self):
        stored = {
            "access_token": "stale", "refresh_token": "r1", "expires_at": _iso(-3600),
            "token_endpoint": "https://srv/token", "client_id": "client-1",
        }
        fresh = SimpleNamespace(access_token="fresh-token", refresh_token="r2", scope=None, token_type="Bearer",
                                expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
        creds = MCPServerCredentials(auth_type="oauth", oauth_credential_id="cid", access_token="stale")
        with patch("nodes.oauth.mcp_oauth.refresh_access_token", new=AsyncMock(return_value=fresh)) as refresh, \
                patch("utils.credentials.update_credential_data_detailed", new=AsyncMock(return_value=(1, None))):
            token = await _signed_in_with(_node(creds), stored)
        refresh.assert_awaited_once()
        assert token == "fresh-token"

    async def test_missing_rotation_material_uses_the_stored_token(self):
        # A credential without token_endpoint can't be refreshed: its stored token is the one there is.
        stored = {"access_token": "stale", "refresh_token": "r1", "expires_at": _iso(-3600)}
        with patch(
            "nodes.oauth.mcp_oauth.refresh_access_token", new=AsyncMock()
        ) as refresh:
            token = await _signed_in_with(_node(MCPServerCredentials(auth_type="oauth", access_token="stale"),
                                                "cid"), stored)
        refresh.assert_not_awaited()
        assert token == "stale"
