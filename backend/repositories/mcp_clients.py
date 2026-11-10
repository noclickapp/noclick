"""The OAuth clients NoClick registered with vendor MCP authorization servers.

One per authorization server and redirect URI (``nodes.oauth.mcp_connect``), so
every person connecting that integration signs in through the same client. Two
connects racing to register both reach the server; the first insert keeps its
client and the other's registration is simply never used.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class McpClientRepo:
    def __init__(self, pool):
        self.pool = pool

    async def get(self, issuer: str, redirect_uri: str) -> Optional[Dict[str, Any]]:
        row = await self.pool.fetchrow(
            "SELECT client_id, client_secret_sealed FROM mcp_oauth_clients WHERE issuer = $1 AND redirect_uri = $2",
            issuer, redirect_uri,
        )
        return dict(row) if row else None

    async def keep(
        self, issuer: str, redirect_uri: str, client_id: str, client_secret_sealed: Optional[str],
        registration: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Store a registration unless another landed first; the client to use either way."""
        await self.pool.execute(
            """
            INSERT INTO mcp_oauth_clients (issuer, redirect_uri, client_id, client_secret_sealed, registration)
            VALUES ($1, $2, $3, $4, $5::jsonb)
            ON CONFLICT (issuer, redirect_uri) DO NOTHING
            """,
            issuer, redirect_uri, client_id, client_secret_sealed, registration,
        )
        return await self.get(issuer, redirect_uri)

    async def forget(self, issuer: str, redirect_uri: str, client_id: str) -> None:
        """Drop a client the server no longer knows, so the next connect registers afresh."""
        await self.pool.execute(
            "DELETE FROM mcp_oauth_clients WHERE issuer = $1 AND redirect_uri = $2 AND client_id = $3",
            issuer, redirect_uri, client_id,
        )
