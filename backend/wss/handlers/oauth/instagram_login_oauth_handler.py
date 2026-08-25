"""
Handler for Instagram Login OAuth operations (Instagram API with Instagram
Login — the newer, Page-free flow served from graph.instagram.com). Separate
app credentials and tokens from the Facebook-Login Instagram flow.
"""

import logging
from typing import Dict, Callable
from utils.database_pool import DatabasePoolMixin
from utils.encryption import get_encryption
from nodes.oauth.instagram_login_oauth import (
    exchange_code_for_tokens,
    refresh_access_token,
    is_token_expired,
)
from wss.schema import SocketIOHandler
from wss.sender import send_event, ResponseEvent
from wss.sender.responses import (
    InstagramLoginOAuthExchangeResponse,
    InstagramLoginOAuthRefreshResponse,
    InstagramLoginOAuthValidateResponse,
)
from wss.receiver.client_events import (
    InstagramLoginOAuthExchangeRequest,
    InstagramLoginOAuthRefreshRequest,
    InstagramLoginOAuthValidateRequest,
)

logger = logging.getLogger(__name__)


class InstagramLoginOAuthHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for Instagram Login OAuth WebSocket events."""

    def __init__(self, sio):
        super().__init__(sio)
        self.encryption = get_encryption()

    def get_events(self) -> Dict[str, Callable]:
        return {
            "instagram_login:oauth:exchange": self.exchange_oauth_code,
            "instagram_login:oauth:refresh": self.refresh_oauth_token,
            "instagram_login:oauth:validate": self.validate_oauth_token,
        }

    async def setup_user(self, sid: str) -> None:
        _ = sid

    async def exchange_oauth_code(self, sid: str, request: InstagramLoginOAuthExchangeRequest) -> None:
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=InstagramLoginOAuthExchangeResponse(success=False, message="User not authenticated").model_dump()
                ))
                return

            try:
                tokens, info = await exchange_code_for_tokens(
                    code=request.code, redirect_uri=request.redirect_uri,
                )
            except ValueError as e:
                logger.error(f"[InstagramLoginOAuthHandler] Token exchange failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=InstagramLoginOAuthExchangeResponse(success=False, message=str(e)).model_dump()
                ))
                return

            instagram_user_id = tokens.instagram_user_id or info.instagram_user_id
            if not instagram_user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=InstagramLoginOAuthExchangeResponse(
                        success=False,
                        message="Could not resolve the Instagram account id for this login.").model_dump()
                ))
                return

            credential_data = {
                'access_token': tokens.access_token,
                'expires_at': tokens.expires_at,
                'instagram_user_id': instagram_user_id,
                'instagram_username': info.username,
            }

            try:
                encrypted_data = self.encryption.encrypt_credential(credential_data)
            except Exception as e:
                logger.error(f"[InstagramLoginOAuthHandler] Encryption failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=InstagramLoginOAuthExchangeResponse(success=False, message="Failed to encrypt credential").model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=InstagramLoginOAuthExchangeResponse(success=False, message="Database connection not available").model_dump()
                ))
                return

            handle = f"@{info.username}" if info.username else instagram_user_id
            credential_name = f"Instagram ({handle})"

            async with pool.acquire() as conn:
                from repositories.credentials import create_credential_with_limit_check
                user_tier = session.get('user_data', {}).get('subscription_tier', 'free')
                row, error = await create_credential_with_limit_check(
                    conn, user_id, user_tier, 'instagram_login',
                    credential_name, encrypted_data, {
                        'provider': 'instagram_login',
                        'instagram_username': info.username,
                        'instagram_user_id': instagram_user_id,
                        'account_type': info.account_type,
                        'expires_at': tokens.expires_at,
                        'scopes': request.scopes,
                    },
                )
                if error:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={}, error=error
                    ))
                    return

                response = InstagramLoginOAuthExchangeResponse(
                    success=True,
                    credential_id=str(row['id']),
                    credential_name=row['name'],
                    name=info.username,
                    message="Instagram account connected successfully",
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data=response.model_dump()
                ))
                logger.info(f"[InstagramLoginOAuthHandler] Created Instagram Login credential {row['id']} for user {user_id}")

        except Exception as e:
            logger.error(f"[InstagramLoginOAuthHandler] Error in exchange_oauth_code: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=InstagramLoginOAuthExchangeResponse(success=False, message="Internal error").model_dump()
            ))

    async def refresh_oauth_token(self, sid: str, request: InstagramLoginOAuthRefreshRequest) -> None:
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=InstagramLoginOAuthRefreshResponse(success=False, message="User not authenticated").model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=InstagramLoginOAuthRefreshResponse(success=False, message="Database connection not available").model_dump()
                ))
                return

            from wss.handlers.oauth.manual_refresh import manual_refresh_credential
            try:
                credential_data = await manual_refresh_credential(
                    pool, user_id=user_id, credential_id=request.credential_id,
                    provider="instagram_login", refresh=refresh_access_token,
                )
            except ValueError as e:
                logger.error(f"[InstagramLoginOAuthHandler] Token refresh failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=InstagramLoginOAuthRefreshResponse(success=False, message=str(e)).model_dump()
                ))
                return

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=InstagramLoginOAuthRefreshResponse(
                    success=True, expires_at=credential_data.get('expires_at'),
                    message="Token refreshed successfully",
                ).model_dump()
            ))
        except Exception as e:
            logger.error(f"[InstagramLoginOAuthHandler] Error in refresh_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=InstagramLoginOAuthRefreshResponse(success=False, message="Internal error").model_dump()
            ))

    async def validate_oauth_token(self, sid: str, request: InstagramLoginOAuthValidateRequest) -> None:
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=InstagramLoginOAuthValidateResponse(valid=False, message="User not authenticated").model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=InstagramLoginOAuthValidateResponse(valid=False, message="Database connection not available").model_dump()
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
                        data=InstagramLoginOAuthValidateResponse(valid=False, message="Credential not found or access denied").model_dump()
                    ))
                    return
                try:
                    credential_data = self.encryption.decrypt_credential(row['credential'])
                except Exception as e:
                    logger.error(f"[InstagramLoginOAuthHandler] Decryption failed: {e}")
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=InstagramLoginOAuthValidateResponse(valid=False, message="Failed to decrypt credential").model_dump()
                    ))
                    return

                expires_at = credential_data.get('expires_at')
                name = credential_data.get('instagram_username') or (row['metadata'] or {}).get('instagram_username')
                if not expires_at:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=InstagramLoginOAuthValidateResponse(valid=True, expires_soon=False, name=name,
                                                                 message="Token is valid").model_dump()
                    ))
                    return

                is_expired = is_token_expired(expires_at, buffer_days=0)
                expires_soon = is_token_expired(expires_at, buffer_days=7)
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=InstagramLoginOAuthValidateResponse(
                        valid=not is_expired,
                        expires_soon=expires_soon and not is_expired,
                        name=name,
                        message="Token is valid" if not is_expired else "Token has expired",
                    ).model_dump()
                ))
        except Exception as e:
            logger.error(f"[InstagramLoginOAuthHandler] Error in validate_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=InstagramLoginOAuthValidateResponse(valid=False, message="Internal error").model_dump()
            ))
