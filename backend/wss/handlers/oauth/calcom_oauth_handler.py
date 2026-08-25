"""
Handler for Cal.com OAuth operations.
Manages OAuth 2.0 (authorization-code) flow for Cal.com API v2 access.
"""

import logging
from typing import Dict, Callable
from utils.database_pool import DatabasePoolMixin
from utils.encryption import get_encryption
from nodes.oauth.calcom_oauth import (
    exchange_code_for_tokens,
    refresh_access_token,
    is_token_expired,
)
from wss.schema import SocketIOHandler
from wss.sender import send_event, ResponseEvent
from wss.sender.responses import (
    CalComOAuthExchangeResponse,
    CalComOAuthRefreshResponse,
    CalComOAuthValidateResponse,
)
from wss.receiver.client_events import (
    CalComOAuthExchangeRequest,
    CalComOAuthRefreshRequest,
    CalComOAuthValidateRequest,
)

logger = logging.getLogger(__name__)


class CalComOAuthHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for Cal.com OAuth WebSocket events"""

    def __init__(self, sio):
        super().__init__(sio)
        self.encryption = get_encryption()

    def get_events(self) -> Dict[str, Callable]:
        return {
            "calcom:oauth:exchange": self.exchange_oauth_code,
            "calcom:oauth:refresh": self.refresh_oauth_token,
            "calcom:oauth:validate": self.validate_oauth_token,
        }

    async def setup_user(self, sid: str) -> None:
        _ = sid

    async def exchange_oauth_code(self, sid: str, request: CalComOAuthExchangeRequest) -> None:
        """Exchange OAuth authorization code for tokens and store as credential."""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=CalComOAuthExchangeResponse(
                        success=False, message="User not authenticated"
                    ).model_dump()
                ))
                return

            try:
                tokens, user_info = await exchange_code_for_tokens(
                    code=request.code,
                    redirect_uri=request.redirect_uri,
                )
            except ValueError as e:
                logger.error(f"[CalComOAuthHandler] Token exchange failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=CalComOAuthExchangeResponse(success=False, message=str(e)).model_dump()
                ))
                return

            credential_data = {
                'access_token': tokens.access_token,
                'refresh_token': tokens.refresh_token,
                'expires_at': tokens.expires_at,
                'scope': tokens.scope,
                'name': user_info.name,
                'email': user_info.email,
            }

            try:
                encrypted_data = self.encryption.encrypt_credential(credential_data)
            except Exception as e:
                logger.error(f"[CalComOAuthHandler] Encryption failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=CalComOAuthExchangeResponse(
                        success=False, message="Failed to encrypt credential"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=CalComOAuthExchangeResponse(
                        success=False, message="Database connection not available"
                    ).model_dump()
                ))
                return

            credential_name = user_info.username or user_info.email or user_info.name or f"Cal.com ({user_info.id})"

            async with pool.acquire() as conn:
                from repositories.credentials import create_credential_with_limit_check
                user_tier = session.get('user_data', {}).get('subscription_tier', 'free')
                row, error = await create_credential_with_limit_check(
                    conn, user_id, user_tier, 'cal_com_oauth',
                    credential_name, encrypted_data, {
                        'provider': 'calcom',
                        'name': user_info.name,
                        'email': user_info.email,
                        'calcom_user_id': user_info.id,
                        'scopes': request.scopes,
                    },
                )
                if error:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={}, error=error
                    ))
                    return

                response = CalComOAuthExchangeResponse(
                    success=True,
                    credential_id=str(row['id']),
                    credential_name=row['name'],
                    name=user_info.name,
                    email=user_info.email,
                    message="Cal.com account connected successfully"
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data=response.model_dump()
                ))
                logger.info(f"[CalComOAuthHandler] Created Cal.com credential {row['id']} for user {user_id} ({user_info.name})")

        except Exception as e:
            logger.error(f"[CalComOAuthHandler] Error in exchange_oauth_code: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=CalComOAuthExchangeResponse(success=False, message="Internal error").model_dump()
            ))

    async def refresh_oauth_token(self, sid: str, request: CalComOAuthRefreshRequest) -> None:
        """Refresh an expired OAuth token and update the stored credential."""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=CalComOAuthRefreshResponse(
                        success=False, message="User not authenticated"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=CalComOAuthRefreshResponse(
                        success=False, message="Database connection not available"
                    ).model_dump()
                ))
                return

            from wss.handlers.oauth.manual_refresh import manual_refresh_credential

            try:
                credential_data = await manual_refresh_credential(
                    pool,
                    user_id=user_id,
                    credential_id=request.credential_id,
                    provider="calcom",
                    refresh=refresh_access_token,
                )
            except ValueError as e:
                logger.error(f"[CalComOAuthHandler] Token refresh failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=CalComOAuthRefreshResponse(success=False, message=str(e)).model_dump()
                ))
                return

            response = CalComOAuthRefreshResponse(
                success=True,
                expires_at=credential_data.get('expires_at'),
                message="Token refreshed successfully"
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data=response.model_dump()
            ))
            logger.info(f"[CalComOAuthHandler] Refreshed token for credential {request.credential_id}")

        except Exception as e:
            logger.error(f"[CalComOAuthHandler] Error in refresh_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=CalComOAuthRefreshResponse(success=False, message="Internal error").model_dump()
            ))

    async def validate_oauth_token(self, sid: str, request: CalComOAuthValidateRequest) -> None:
        """Validate whether a stored Cal.com OAuth credential is still valid."""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=CalComOAuthValidateResponse(valid=False, message="User not authenticated").model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=CalComOAuthValidateResponse(
                        valid=False, message="Database connection not available"
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
                        data=CalComOAuthValidateResponse(
                            valid=False, message="Credential not found or access denied"
                        ).model_dump()
                    ))
                    return

                try:
                    credential_data = self.encryption.decrypt_credential(row['credential'])
                except Exception as e:
                    logger.error(f"[CalComOAuthHandler] Decryption failed: {e}")
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=CalComOAuthValidateResponse(
                            valid=False, message="Failed to decrypt credential"
                        ).model_dump()
                    ))
                    return

                expires_at = credential_data.get('expires_at')
                name = credential_data.get('name') or row['metadata'].get('name')
                email = credential_data.get('email') or row['metadata'].get('email')

                is_expired = is_token_expired(expires_at, buffer_minutes=0)
                expires_soon = is_token_expired(expires_at, buffer_minutes=5)

                response = CalComOAuthValidateResponse(
                    valid=not is_expired,
                    expires_soon=expires_soon and not is_expired,
                    name=name,
                    email=email,
                    message="Token is valid" if not is_expired else "Token has expired"
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data=response.model_dump()
                ))

        except Exception as e:
            logger.error(f"[CalComOAuthHandler] Error in validate_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=CalComOAuthValidateResponse(valid=False, message="Internal error").model_dump()
            ))
