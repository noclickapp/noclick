"""
Handler for Typeform OAuth operations.
Manages OAuth 2.0 Authorization Code Flow for Typeform API access.
"""

import logging
from typing import Dict, Callable
from utils.database_pool import DatabasePoolMixin
from utils.encryption import get_encryption
from nodes.oauth.typeform_oauth import exchange_code_for_tokens
from wss.schema import SocketIOHandler
from wss.sender import send_event, ResponseEvent
from wss.sender.responses import TypeformOAuthExchangeResponse
from wss.receiver.client_events import TypeformOAuthExchangeRequest

logger = logging.getLogger(__name__)


class TypeformOAuthHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for Typeform OAuth WebSocket events"""

    def __init__(self, sio):
        super().__init__(sio)
        self.encryption = get_encryption()

    def get_events(self) -> Dict[str, Callable]:
        """Register Typeform OAuth events"""
        return {
            "typeform:oauth:exchange": self.exchange_oauth_code,
        }

    async def setup_user(self, sid: str) -> None:
        _ = sid

    async def exchange_oauth_code(self, sid: str, request: TypeformOAuthExchangeRequest) -> None:
        """
        Exchange OAuth authorization code for tokens and store as credential.
        Called from the OAuth callback page after user grants permission.

        Typeform OAuth tokens expire after 1 week by default and can be refreshed.
        """
        try:
            # Get user session
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=TypeformOAuthExchangeResponse(
                        success=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            # Exchange code for tokens
            logger.info(f"[TypeformOAuthHandler] Exchanging code for user {user_id}, redirect_uri: {request.redirect_uri}")
            try:
                tokens, user_info = await exchange_code_for_tokens(
                    code=request.code,
                    redirect_uri=request.redirect_uri,
                )
            except ValueError as e:
                logger.error(f"[TypeformOAuthHandler] Token exchange failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=TypeformOAuthExchangeResponse(
                        success=False,
                        message=str(e)
                    ).model_dump()
                ))
                return

            # Prepare credential data (includes access token, optional refresh token, and expiry)
            credential_data = {
                'access_token': tokens.access_token,
                'expires_at': tokens.expires_at,
                'token_type': tokens.token_type,
                'scope': tokens.scope,
            }

            # Only include refresh_token if Typeform provided one
            # (Personal Access Token apps don't support refresh tokens)
            if tokens.refresh_token:
                credential_data['refresh_token'] = tokens.refresh_token
                logger.info("[TypeformOAuthHandler] Refresh token received from Typeform")
            else:
                logger.warning("[TypeformOAuthHandler] No refresh token - using Personal Access Token app")

            # Encrypt and store credential
            try:
                encrypted_data = self.encryption.encrypt_credential(credential_data)
            except Exception as e:
                logger.error(f"[TypeformOAuthHandler] Encryption failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=TypeformOAuthExchangeResponse(
                        success=False,
                        message="Failed to encrypt credential"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=TypeformOAuthExchangeResponse(
                        success=False,
                        message="Database connection not available"
                    ).model_dump()
                ))
                return

            # Use the credential_name from request, or default
            credential_name = request.credential_name or "Typeform"

            async with pool.acquire() as conn:
                from repositories.credentials import create_credential_with_limit_check
                user_tier = session.get('user_data', {}).get('subscription_tier', 'free')
                row, error = await create_credential_with_limit_check(
                    conn, user_id, user_tier, 'typeform_oauth',
                    credential_name, encrypted_data, {
                        'provider': 'typeform',
                        'scopes': request.scopes,
                        'expires_at': tokens.expires_at,
                    },
                )
                if error:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={}, error=error
                    ))
                    return

                response = TypeformOAuthExchangeResponse(
                    success=True,
                    credential_id=str(row['id']),
                    credential_name=row['name'],
                    message="Typeform account connected successfully"
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))

                logger.info(f"[TypeformOAuthHandler] Successfully stored Typeform OAuth credential for user {user_id}")

        except Exception as e:
            logger.exception(f"[TypeformOAuthHandler] Unexpected error in exchange_oauth_code: {e}")
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=TypeformOAuthExchangeResponse(
                    success=False,
                    message=f"Unexpected error: {str(e)}"
                ).model_dump()
            ))
