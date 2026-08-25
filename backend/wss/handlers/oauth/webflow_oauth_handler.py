"""
Handler for Webflow OAuth operations.
Manages the OAuth 2.0 authorization_code flow for Webflow Data API (v2) access.

Webflow access tokens are long-lived and non-expiring, so refresh is a no-op
(reconnect to recover from a revoked token) and validation treats any stored
credential as valid.
"""

import logging
from typing import Dict, Callable
from utils.database_pool import DatabasePoolMixin
from utils.encryption import get_encryption
from nodes.oauth.webflow_oauth import (
    exchange_code_for_tokens,
    refresh_access_token,
    is_token_expired,
)
from wss.schema import SocketIOHandler
from wss.sender import send_event, ResponseEvent
from wss.sender.responses import (
    WebflowOAuthExchangeResponse,
    WebflowOAuthRefreshResponse,
    WebflowOAuthValidateResponse,
)
from wss.receiver.client_events import (
    WebflowOAuthExchangeRequest,
    WebflowOAuthRefreshRequest,
    WebflowOAuthValidateRequest,
)

logger = logging.getLogger(__name__)


class WebflowOAuthHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for Webflow OAuth WebSocket events"""

    def __init__(self, sio):
        super().__init__(sio)
        self.encryption = get_encryption()

    def get_events(self) -> Dict[str, Callable]:
        """Register Webflow OAuth events"""
        return {
            "webflow:oauth:exchange": self.exchange_oauth_code,
            "webflow:oauth:refresh": self.refresh_oauth_token,
            "webflow:oauth:validate": self.validate_oauth_token,
        }

    async def setup_user(self, sid: str) -> None:
        _ = sid

    async def exchange_oauth_code(self, sid: str, request: WebflowOAuthExchangeRequest) -> None:
        """
        Exchange OAuth authorization code for tokens and store as credential.
        Called from the OAuth callback page after user grants permission.
        """
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WebflowOAuthExchangeResponse(
                        success=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            try:
                tokens, user_info = await exchange_code_for_tokens(
                    code=request.code,
                    redirect_uri=request.redirect_uri,
                )
            except ValueError as e:
                logger.error(f"[WebflowOAuthHandler] Token exchange failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WebflowOAuthExchangeResponse(
                        success=False,
                        message=str(e)
                    ).model_dump()
                ))
                return

            credential_data = {
                'access_token': tokens.access_token,
                'refresh_token': tokens.refresh_token,
                'expires_at': tokens.expires_at,
                'name': user_info.name,
                'email': user_info.email,
            }

            try:
                encrypted_data = self.encryption.encrypt_credential(credential_data)
            except Exception as e:
                logger.error(f"[WebflowOAuthHandler] Encryption failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WebflowOAuthExchangeResponse(
                        success=False,
                        message="Failed to encrypt credential"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WebflowOAuthExchangeResponse(
                        success=False,
                        message="Database connection not available"
                    ).model_dump()
                ))
                return

            credential_name = user_info.name or user_info.email or f"Webflow ({user_info.id})"

            async with pool.acquire() as conn:
                from repositories.credentials import create_credential_with_limit_check
                user_tier = session.get('user_data', {}).get('subscription_tier', 'free')
                row, error = await create_credential_with_limit_check(
                    conn, user_id, user_tier, 'webflow_oauth',
                    credential_name, encrypted_data, {
                        'provider': 'webflow',
                        'name': user_info.name,
                        'email': user_info.email,
                        'webflow_user_id': user_info.id,
                        'scopes': request.scopes,
                    },
                )
                if error:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={}, error=error
                    ))
                    return

                response = WebflowOAuthExchangeResponse(
                    success=True,
                    credential_id=str(row['id']),
                    credential_name=row['name'],
                    name=user_info.name,
                    email=user_info.email,
                    message="Webflow account connected successfully"
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))
                logger.info(f"[WebflowOAuthHandler] Created Webflow credential {row['id']} for user {user_id} ({user_info.name})")

        except Exception as e:
            logger.error(f"[WebflowOAuthHandler] Error in exchange_oauth_code: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=WebflowOAuthExchangeResponse(
                    success=False,
                    message="Internal error"
                ).model_dump()
            ))

    async def refresh_oauth_token(self, sid: str, request: WebflowOAuthRefreshRequest) -> None:
        """
        Refresh an OAuth token. Webflow access tokens are non-expiring and have
        no refresh flow, so this always reports success without doing work — the
        stored token remains valid until the user revokes it.
        """
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WebflowOAuthRefreshResponse(
                        success=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            response = WebflowOAuthRefreshResponse(
                success=True,
                expires_at=None,
                message="Webflow tokens are non-expiring; no refresh needed"
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=response.model_dump()
            ))
            logger.info(f"[WebflowOAuthHandler] Refresh no-op for credential {request.credential_id} (non-expiring token)")

        except Exception as e:
            logger.error(f"[WebflowOAuthHandler] Error in refresh_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=WebflowOAuthRefreshResponse(
                    success=False,
                    message="Internal error"
                ).model_dump()
            ))

    async def validate_oauth_token(self, sid: str, request: WebflowOAuthValidateRequest) -> None:
        """
        Validate if a stored OAuth credential is still present.
        Webflow access tokens are non-expiring, so a stored credential is
        treated as valid.
        """
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WebflowOAuthValidateResponse(
                        valid=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WebflowOAuthValidateResponse(
                        valid=False,
                        message="Database connection not available"
                    ).model_dump()
                ))
                return

            async with pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT id, credential, metadata
                    FROM credentials
                    WHERE id = $1 AND owner_id = $2
                """, request.credential_id, user_id)

                if not row:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=WebflowOAuthValidateResponse(
                            valid=False,
                            message="Credential not found or access denied"
                        ).model_dump()
                    ))
                    return

                try:
                    credential_data = self.encryption.decrypt_credential(row['credential'])
                except Exception as e:
                    logger.error(f"[WebflowOAuthHandler] Decryption failed: {e}")
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=WebflowOAuthValidateResponse(
                            valid=False,
                            message="Failed to decrypt credential"
                        ).model_dump()
                    ))
                    return

                name = credential_data.get('name') or row['metadata'].get('name')
                email = credential_data.get('email') or row['metadata'].get('email')

                # Webflow tokens are non-expiring: a present credential is valid.
                response = WebflowOAuthValidateResponse(
                    valid=True,
                    expires_soon=False,
                    name=name,
                    email=email,
                    message="Token is valid"
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))

        except Exception as e:
            logger.error(f"[WebflowOAuthHandler] Error in validate_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=WebflowOAuthValidateResponse(
                    valid=False,
                    message="Internal error"
                ).model_dump()
            ))
