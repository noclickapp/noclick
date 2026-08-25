"""
Handler for HubSpot OAuth operations.
Manages OAuth 2.0 Web Server Flow for HubSpot API access.
"""

import logging
from typing import Dict, Callable
from datetime import datetime, timezone, timedelta
from utils.database_pool import DatabasePoolMixin
from utils.encryption import get_encryption
from nodes.oauth.hubspot_oauth import (
    exchange_code_for_tokens,
    refresh_access_token,
)
from wss.schema import SocketIOHandler
from wss.sender import send_event, ResponseEvent
from wss.sender.responses import (
    HubSpotOAuthExchangeResponse,
    HubSpotOAuthRefreshResponse,
    HubSpotOAuthValidateResponse,
)
from wss.receiver.client_events import (
    HubSpotOAuthExchangeRequest,
    HubSpotOAuthRefreshRequest,
    HubSpotOAuthValidateRequest,
)

logger = logging.getLogger(__name__)


def is_token_expired(expires_at: str, buffer_minutes: int = 0) -> bool:
    """
    Check if a token is expired or will expire soon.

    Args:
        expires_at: ISO 8601 timestamp string
        buffer_minutes: Consider token expired if it expires within this many minutes

    Returns:
        True if token is expired or will expire within buffer_minutes
    """
    try:
        expiry = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        buffer = timedelta(minutes=buffer_minutes)
        return now + buffer >= expiry
    except (ValueError, AttributeError):
        # If we can't parse the timestamp, assume it's expired
        return True


class HubSpotOAuthHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for HubSpot OAuth WebSocket events"""

    def __init__(self, sio):
        super().__init__(sio)
        self.encryption = get_encryption()

    def get_events(self) -> Dict[str, Callable]:
        """Register HubSpot OAuth events"""
        return {
            "hubspot:oauth:exchange": self.exchange_oauth_code,
            "hubspot:oauth:refresh": self.refresh_oauth_token,
            "hubspot:oauth:validate": self.validate_oauth_token,
        }

    async def setup_user(self, sid: str) -> None:
        _ = sid

    async def exchange_oauth_code(self, sid: str, request: HubSpotOAuthExchangeRequest) -> None:
        """
        Exchange OAuth authorization code for tokens and store as credential.
        Called from the OAuth callback page after user grants permission.
        """
        try:
            # Get user session
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=HubSpotOAuthExchangeResponse(
                        success=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            # Exchange code for tokens
            try:
                tokens, user_info = await exchange_code_for_tokens(
                    code=request.code,
                    redirect_uri=request.redirect_uri,
                )
            except ValueError as e:
                logger.error(f"[HubSpotOAuthHandler] Token exchange failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=HubSpotOAuthExchangeResponse(
                        success=False,
                        message=str(e)
                    ).model_dump()
                ))
                return

            # Prepare credential data
            credential_data = {
                'access_token': tokens.access_token,
                'refresh_token': tokens.refresh_token,
                'expires_at': tokens.expires_at,
                'token_type': tokens.token_type,
                'hub_id': user_info.hub_id,
                'hub_domain': user_info.hub_domain,
            }

            # Encrypt and store credential
            try:
                encrypted_data = self.encryption.encrypt_credential(credential_data)
            except Exception as e:
                logger.error(f"[HubSpotOAuthHandler] Encryption failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=HubSpotOAuthExchangeResponse(
                        success=False,
                        message="Failed to encrypt credential"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=HubSpotOAuthExchangeResponse(
                        success=False,
                        message="Database connection not available"
                    ).model_dump()
                ))
                return

            # Use the credential_name from request, or default to hub domain
            credential_name = request.credential_name or user_info.hub_domain or f"HubSpot ({user_info.hub_id})"

            async with pool.acquire() as conn:
                from repositories.credentials import create_credential_with_limit_check
                user_tier = session.get('user_data', {}).get('subscription_tier', 'free')
                row, error = await create_credential_with_limit_check(
                    conn, user_id, user_tier, 'hubspot_oauth',
                    credential_name, encrypted_data, {
                        'provider': 'hubspot',
                        'hub_id': user_info.hub_id,
                        'hub_domain': user_info.hub_domain,
                        'scopes': request.scopes,
                    },
                )
                if error:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={}, error=error
                    ))
                    return

                response = HubSpotOAuthExchangeResponse(
                    success=True,
                    credential_id=str(row['id']),
                    credential_name=row['name'],
                    hub_id=user_info.hub_id,
                    message="HubSpot account connected successfully"
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))
                logger.info(f"[HubSpotOAuthHandler] Created HubSpot credential {row['id']} for user {user_id} (hub_id: {user_info.hub_id})")

        except Exception as e:
            logger.error(f"[HubSpotOAuthHandler] Error in exchange_oauth_code: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=HubSpotOAuthExchangeResponse(
                    success=False,
                    message="Internal error"
                ).model_dump()
            ))

    async def refresh_oauth_token(self, sid: str, request: HubSpotOAuthRefreshRequest) -> None:
        """
        Refresh an expired OAuth token and update the stored credential.
        HubSpot tokens typically expire after 6 hours.
        """
        try:
            # Get user session
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=HubSpotOAuthRefreshResponse(
                        success=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=HubSpotOAuthRefreshResponse(
                        success=False,
                        message="Database connection not available"
                    ).model_dump()
                ))
                return

            # Refresh-if-expired through the shared freshen choke point
            # (lock, in-lock re-read, CAS persist, audit row) — never a
            # bespoke unlocked UPDATE that races the execute-path refresh.
            from wss.handlers.oauth.manual_refresh import manual_refresh_credential

            try:
                credential_data = await manual_refresh_credential(
                    pool,
                    user_id=user_id,
                    credential_id=request.credential_id,
                    provider="hubspot",
                    refresh=refresh_access_token,
                )
            except ValueError as e:
                logger.error(f"[HubSpotOAuthHandler] Token refresh failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=HubSpotOAuthRefreshResponse(
                        success=False,
                        message=str(e)
                    ).model_dump()
                ))
                return

            response = HubSpotOAuthRefreshResponse(
                success=True,
                expires_at=credential_data.get('expires_at'),
                message="Token refreshed successfully"
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=response.model_dump()
            ))
            logger.info(f"[HubSpotOAuthHandler] Refreshed token for credential {request.credential_id}")

        except Exception as e:
            logger.error(f"[HubSpotOAuthHandler] Error in refresh_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=HubSpotOAuthRefreshResponse(
                    success=False,
                    message="Internal error"
                ).model_dump()
            ))

    async def validate_oauth_token(self, sid: str, request: HubSpotOAuthValidateRequest) -> None:
        """
        Validate if a stored OAuth credential is still valid.
        Checks token expiry time.
        """
        try:
            # Get user session
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=HubSpotOAuthValidateResponse(
                        valid=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=HubSpotOAuthValidateResponse(
                        valid=False,
                        message="Database connection not available"
                    ).model_dump()
                ))
                return

            async with pool.acquire() as conn:
                # Fetch credential (verify ownership)
                row = await conn.fetchrow("""
                    SELECT id, credential, metadata
                    FROM credentials
                    WHERE id = $1 AND owner_id = $2
                """, request.credential_id, user_id)

                if not row:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=HubSpotOAuthValidateResponse(
                            valid=False,
                            message="Credential not found or access denied"
                        ).model_dump()
                    ))
                    return

                # Decrypt credential
                try:
                    credential_data = self.encryption.decrypt_credential(row['credential'])
                except Exception as e:
                    logger.error(f"[HubSpotOAuthHandler] Decryption failed: {e}")
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=HubSpotOAuthValidateResponse(
                            valid=False,
                            message="Failed to decrypt credential"
                        ).model_dump()
                    ))
                    return

                expires_at = credential_data.get('expires_at')
                hub_id = credential_data.get('hub_id') or row['metadata'].get('hub_id')

                # Check if token is expired or expiring soon
                is_expired = is_token_expired(expires_at, buffer_minutes=0)
                expires_soon = is_token_expired(expires_at, buffer_minutes=5)

                response = HubSpotOAuthValidateResponse(
                    valid=not is_expired,
                    expires_soon=expires_soon and not is_expired,
                    hub_id=hub_id,
                    message="Token is valid" if not is_expired else "Token has expired"
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))

        except Exception as e:
            logger.error(f"[HubSpotOAuthHandler] Error in validate_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=HubSpotOAuthValidateResponse(
                    valid=False,
                    message="Internal error"
                ).model_dump()
            ))
