"""
Handler for MCP OAuth operations.

Handles OAuth discovery and token exchange for MCP Server nodes connecting
to external OAuth-protected MCP servers.
"""

import logging
from typing import Dict, Callable

from utils.database_pool import DatabasePoolMixin
from utils.encryption import get_encryption
from nodes.oauth.mcp_oauth import (
    discover_oauth_requirements,
    exchange_code_for_tokens,
    generate_pkce_pair,
    register_dynamic_client,
)
from wss.schema import SocketIOHandler
from wss.sender import send_event, ResponseEvent
from wss.sender.responses import (
    MCPOAuthDiscoverResponse,
    MCPOAuthExchangeResponse,
    MCPOAuthRegisterClientResponse,
)
from wss.receiver.client_events import (
    MCPOAuthDiscoverRequest,
    MCPOAuthExchangeRequest,
    MCPOAuthRegisterClientRequest,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Handler Implementation
# ============================================================================

class MCPOAuthHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for MCP OAuth WebSocket events."""

    def __init__(self, sio):
        super().__init__(sio)
        self.encryption = get_encryption()

    def get_events(self) -> Dict[str, Callable]:
        """Register MCP OAuth events."""
        return {
            "mcp:oauth:discover": self.discover_oauth,
            "mcp:oauth:exchange": self.exchange_oauth_code,
            "mcp:oauth:register-client": self.register_client,
        }

    async def setup_user(self, sid: str) -> None:
        """Initialize database connection pool on user setup."""
        _ = sid

    async def discover_oauth(self, sid: str, request: MCPOAuthDiscoverRequest) -> None:
        """
        Discover OAuth requirements for an MCP server URL.

        Called when user enters an MCP server URL to check if OAuth is required.
        """
        try:
            logger.info(f"[MCPOAuthHandler] Discovery request for {request.server_url}")

            # Perform discovery
            result = await discover_oauth_requirements(request.server_url)

            # Generate PKCE pair if OAuth is required
            code_verifier = None
            code_challenge = None
            if result.requires_oauth and not result.error:
                code_verifier, code_challenge = generate_pkce_pair()

            response = MCPOAuthDiscoverResponse(
                success=True,
                requires_oauth=result.requires_oauth,
                provider_name=result.provider_name,
                authorization_endpoint=result.authorization_endpoint,
                token_endpoint=result.token_endpoint,
                scopes_supported=result.scopes_supported,
                supports_dynamic_registration=result.supports_dynamic_registration,
                registration_endpoint=result.registration_endpoint,
                code_verifier=code_verifier,
                code_challenge=code_challenge,
                resource_url=result.resource_url,
                error=result.error,
            )

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=response.model_dump()
            ))

        except Exception as e:
            logger.error(f"[MCPOAuthHandler] Discovery error: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=MCPOAuthDiscoverResponse(
                    success=False,
                    requires_oauth=False,
                    error=str(e)
                ).model_dump()
            ))

    async def exchange_oauth_code(self, sid: str, request: MCPOAuthExchangeRequest) -> None:
        """
        Exchange authorization code for tokens and store as credential.

        Called from the OAuth callback page after user grants permission.
        """
        try:
            # Get user session
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=MCPOAuthExchangeResponse(
                        success=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            logger.info(f"[MCPOAuthHandler] Token exchange for user {user_id}")

            # Exchange code for tokens
            try:
                tokens = await exchange_code_for_tokens(
                    code=request.code,
                    code_verifier=request.code_verifier,
                    token_endpoint=request.token_endpoint,
                    client_id=request.client_id,
                    redirect_uri=request.redirect_uri,
                    resource_url=request.resource_url,
                )
            except ValueError as e:
                logger.error(f"[MCPOAuthHandler] Token exchange failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=MCPOAuthExchangeResponse(
                        success=False,
                        message=str(e)
                    ).model_dump()
                ))
                return

            # Prepare credential data
            credential_data = {
                'access_token': tokens.access_token,
                'refresh_token': tokens.refresh_token,
                'token_type': tokens.token_type,
                'expires_at': tokens.expires_at.isoformat() if tokens.expires_at else None,
                'scope': tokens.scope,
                'token_endpoint': request.token_endpoint,
                'client_id': request.client_id,
                'resource_url': request.resource_url,
                'server_url': request.server_url,
            }

            # Encrypt credential
            try:
                encrypted_data = self.encryption.encrypt_credential(credential_data)
            except Exception as e:
                logger.error(f"[MCPOAuthHandler] Encryption failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=MCPOAuthExchangeResponse(
                        success=False,
                        message="Failed to encrypt credential"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=MCPOAuthExchangeResponse(
                        success=False,
                        message="Database connection not available"
                    ).model_dump()
                ))
                return

            # Build credential name
            provider_name = request.provider_name or "MCP Server"
            domain = _extract_domain(request.server_url)
            credential_name = request.credential_name or f"{provider_name} ({domain})"

            async with pool.acquire() as conn:
                from repositories.credentials import create_credential_with_limit_check
                user_tier = session.get('user_data', {}).get('subscription_tier', 'free')
                row, error = await create_credential_with_limit_check(
                    conn, user_id, user_tier, 'mcp_oauth',
                    credential_name, encrypted_data, {
                    'provider': 'mcp',
                    'provider_name': provider_name,
                    'server_url': request.server_url,
                    'created_via': 'oauth_flow',
                    },
                )
                if error:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={}, error=error
                    ))
                    return

                response = MCPOAuthExchangeResponse(
                    success=True,
                    credential_id=str(row['id']),
                    credential_name=row['name'],
                    provider_name=provider_name,
                    message=f"Connected to {provider_name} successfully"
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))
                logger.info(f"[MCPOAuthHandler] Created MCP credential {row['id']} for user {user_id} (server: {request.server_url})")

        except Exception as e:
            logger.error(f"[MCPOAuthHandler] Error in exchange_oauth_code: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=MCPOAuthExchangeResponse(
                    success=False,
                    message="Internal error"
                ).model_dump()
            ))

    async def register_client(self, sid: str, request: MCPOAuthRegisterClientRequest) -> None:
        """
        Register a dynamic OAuth client with an MCP server's auth provider.

        Called when the MCP server supports dynamic client registration.
        """
        try:
            logger.info(f"[MCPOAuthHandler] Registering client at {request.registration_endpoint}")

            result = await register_dynamic_client(
                registration_endpoint=request.registration_endpoint,
                client_name=request.client_name,
                redirect_uris=request.redirect_uris,
            )

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=MCPOAuthRegisterClientResponse(
                    success=True,
                    client_id=result.get("client_id"),
                    message="Client registered successfully"
                ).model_dump()
            ))

        except Exception as e:
            logger.error(f"[MCPOAuthHandler] Register client error: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=MCPOAuthRegisterClientResponse(
                    success=False,
                    message=str(e)
                ).model_dump()
            ))


def _extract_domain(url: str) -> str:
    """Extract domain from URL for display."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    return parsed.netloc or url
