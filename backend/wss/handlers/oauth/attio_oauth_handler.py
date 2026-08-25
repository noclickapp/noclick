"""
Handler for Attio OAuth operations.
Manages the OAuth 2.0 authorization-code flow for Attio API access.
"""

import logging
from typing import Dict, Callable
from utils.database_pool import DatabasePoolMixin
from utils.encryption import get_encryption
from nodes.oauth.attio_oauth import (
    exchange_code_for_tokens,
    refresh_access_token,
    is_token_expired,
)
from wss.schema import SocketIOHandler
from wss.sender import send_event, ResponseEvent
from wss.sender.responses import (
    AttioOAuthExchangeResponse,
    AttioOAuthRefreshResponse,
    AttioOAuthValidateResponse,
)
from wss.receiver.client_events import (
    AttioOAuthExchangeRequest,
    AttioOAuthRefreshRequest,
    AttioOAuthValidateRequest,
)

logger = logging.getLogger(__name__)


class AttioOAuthHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for Attio OAuth WebSocket events."""

    def __init__(self, sio):
        super().__init__(sio)
        self.encryption = get_encryption()

    def get_events(self) -> Dict[str, Callable]:
        return {
            "attio:oauth:exchange": self.exchange_oauth_code,
            "attio:oauth:refresh": self.refresh_oauth_token,
            "attio:oauth:validate": self.validate_oauth_token,
        }

    async def setup_user(self, sid: str) -> None:
        _ = sid

    async def exchange_oauth_code(self, sid: str, request: AttioOAuthExchangeRequest) -> None:
        """Exchange an authorization code for tokens and store as a credential."""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=AttioOAuthExchangeResponse(success=False, message="User not authenticated").model_dump()
                ))
                return

            try:
                tokens, user_info = await exchange_code_for_tokens(
                    code=request.code, redirect_uri=request.redirect_uri
                )
            except ValueError as e:
                logger.error(f"[AttioOAuthHandler] Token exchange failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=AttioOAuthExchangeResponse(success=False, message=str(e)).model_dump()
                ))
                return

            credential_data = {
                'access_token': tokens.access_token,
                'refresh_token': tokens.refresh_token,
                'expires_at': tokens.expires_at,
                'scope': tokens.scope,
                'name': user_info.name,
                'workspace_member_id': user_info.workspace_member_id,
            }
            try:
                encrypted_data = self.encryption.encrypt_credential(credential_data)
            except Exception as e:
                logger.error(f"[AttioOAuthHandler] Encryption failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=AttioOAuthExchangeResponse(success=False, message="Failed to encrypt credential").model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=AttioOAuthExchangeResponse(success=False, message="Database connection not available").model_dump()
                ))
                return

            credential_name = user_info.name or f"Attio ({user_info.id})"
            async with pool.acquire() as conn:
                from repositories.credentials import create_credential_with_limit_check
                user_tier = session.get('user_data', {}).get('subscription_tier', 'free')
                row, error = await create_credential_with_limit_check(
                    conn, user_id, user_tier, 'attio_oauth',
                    credential_name, encrypted_data, {
                        'provider': 'attio',
                        'name': user_info.name,
                        'workspace_id': user_info.id,
                        'scopes': request.scopes,
                    },
                )
                if error:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={}, error=error
                    ))
                    return

                response = AttioOAuthExchangeResponse(
                    success=True,
                    credential_id=str(row['id']),
                    credential_name=row['name'],
                    name=user_info.name,
                    message="Attio workspace connected successfully",
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data=response.model_dump()
                ))
                logger.info(f"[AttioOAuthHandler] Created Attio credential {row['id']} for user {user_id}")

        except Exception as e:
            logger.error(f"[AttioOAuthHandler] Error in exchange_oauth_code: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=AttioOAuthExchangeResponse(success=False, message="Internal error").model_dump()
            ))

    async def refresh_oauth_token(self, sid: str, request: AttioOAuthRefreshRequest) -> None:
        """Refresh-if-expired via the shared freshen choke point."""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=AttioOAuthRefreshResponse(success=False, message="User not authenticated").model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=AttioOAuthRefreshResponse(success=False, message="Database connection not available").model_dump()
                ))
                return

            from wss.handlers.oauth.manual_refresh import manual_refresh_credential
            try:
                credential_data = await manual_refresh_credential(
                    pool, user_id=user_id, credential_id=request.credential_id,
                    provider="attio", refresh=refresh_access_token,
                )
            except ValueError as e:
                logger.error(f"[AttioOAuthHandler] Token refresh failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=AttioOAuthRefreshResponse(success=False, message=str(e)).model_dump()
                ))
                return

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=AttioOAuthRefreshResponse(
                    success=True, expires_at=credential_data.get('expires_at'),
                    message="Token refreshed successfully",
                ).model_dump()
            ))

        except Exception as e:
            logger.error(f"[AttioOAuthHandler] Error in refresh_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=AttioOAuthRefreshResponse(success=False, message="Internal error").model_dump()
            ))

    async def validate_oauth_token(self, sid: str, request: AttioOAuthValidateRequest) -> None:
        """Validate a stored Attio OAuth credential (tokens are long-lived)."""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=AttioOAuthValidateResponse(valid=False, message="User not authenticated").model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=AttioOAuthValidateResponse(valid=False, message="Database connection not available").model_dump()
                ))
                return

            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id, credential, metadata FROM credentials WHERE id = $1 AND owner_id = $2",
                    request.credential_id, user_id,
                )
                if not row:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=AttioOAuthValidateResponse(valid=False, message="Credential not found or access denied").model_dump()
                    ))
                    return

                try:
                    credential_data = self.encryption.decrypt_credential(row['credential'])
                except Exception as e:
                    logger.error(f"[AttioOAuthHandler] Decryption failed: {e}")
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=AttioOAuthValidateResponse(valid=False, message="Failed to decrypt credential").model_dump()
                    ))
                    return

                expires_at = credential_data.get('expires_at')
                name = credential_data.get('name') or row['metadata'].get('name')
                if not expires_at:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=AttioOAuthValidateResponse(
                            valid=True, expires_soon=False, name=name,
                            message="Token is valid (long-lived)",
                        ).model_dump()
                    ))
                    return

                is_expired = is_token_expired(expires_at, buffer_minutes=0)
                expires_soon = is_token_expired(expires_at, buffer_minutes=5)
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=AttioOAuthValidateResponse(
                        valid=not is_expired,
                        expires_soon=expires_soon and not is_expired,
                        name=name,
                        message="Token is valid" if not is_expired else "Token has expired",
                    ).model_dump()
                ))

        except Exception as e:
            logger.error(f"[AttioOAuthHandler] Error in validate_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=AttioOAuthValidateResponse(valid=False, message="Internal error").model_dump()
            ))
