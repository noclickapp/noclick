"""
Handler for Threads OAuth operations.
Manages the Threads OAuth 2.0 flow (separate app + tokens from Facebook/Instagram).
"""

import logging
from typing import Dict, Callable
from utils.database_pool import DatabasePoolMixin
from utils.encryption import get_encryption
from nodes.oauth.threads_oauth import (
    exchange_code_for_tokens,
    refresh_access_token,
    is_token_expired,
)
from wss.schema import SocketIOHandler
from wss.sender import send_event, ResponseEvent
from wss.sender.responses import (
    ThreadsOAuthExchangeResponse,
    ThreadsOAuthRefreshResponse,
    ThreadsOAuthValidateResponse,
)
from wss.receiver.client_events import (
    ThreadsOAuthExchangeRequest,
    ThreadsOAuthRefreshRequest,
    ThreadsOAuthValidateRequest,
)

logger = logging.getLogger(__name__)


class ThreadsOAuthHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for Threads OAuth WebSocket events"""

    def __init__(self, sio):
        super().__init__(sio)
        self.encryption = get_encryption()

    def get_events(self) -> Dict[str, Callable]:
        return {
            "threads:oauth:exchange": self.exchange_oauth_code,
            "threads:oauth:refresh": self.refresh_oauth_token,
            "threads:oauth:validate": self.validate_oauth_token,
        }

    async def setup_user(self, sid: str) -> None:
        _ = sid

    async def exchange_oauth_code(self, sid: str, request: ThreadsOAuthExchangeRequest) -> None:
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=ThreadsOAuthExchangeResponse(success=False, message="User not authenticated").model_dump()
                ))
                return

            try:
                tokens, info = await exchange_code_for_tokens(
                    code=request.code, redirect_uri=request.redirect_uri,
                )
            except ValueError as e:
                logger.error(f"[ThreadsOAuthHandler] Token exchange failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=ThreadsOAuthExchangeResponse(success=False, message=str(e)).model_dump()
                ))
                return

            credential_data = {
                'access_token': tokens.access_token,
                'expires_at': tokens.expires_at,
                'threads_user_id': tokens.threads_user_id or info.threads_user_id,
                'username': info.username,
            }

            try:
                encrypted_data = self.encryption.encrypt_credential(credential_data)
            except Exception as e:
                logger.error(f"[ThreadsOAuthHandler] Encryption failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=ThreadsOAuthExchangeResponse(success=False, message="Failed to encrypt credential").model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=ThreadsOAuthExchangeResponse(success=False, message="Database connection not available").model_dump()
                ))
                return

            handle = f"@{info.username}" if info.username else (info.threads_user_id or "")
            credential_name = f"Threads ({handle})" if handle else "Threads"

            async with pool.acquire() as conn:
                from repositories.credentials import create_credential_with_limit_check
                user_tier = session.get('user_data', {}).get('subscription_tier', 'free')
                row, error = await create_credential_with_limit_check(
                    conn, user_id, user_tier, 'threads_oauth',
                    credential_name, encrypted_data, {
                        'provider': 'threads',
                        'username': info.username,
                        'threads_user_id': info.threads_user_id,
                        'scopes': request.scopes,
                    },
                )
                if error:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={}, error=error
                    ))
                    return

                response = ThreadsOAuthExchangeResponse(
                    success=True,
                    credential_id=str(row['id']),
                    credential_name=row['name'],
                    name=info.username,
                    message="Threads account connected successfully",
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data=response.model_dump()
                ))
                logger.info(f"[ThreadsOAuthHandler] Created Threads credential {row['id']} for user {user_id}")

        except Exception as e:
            logger.error(f"[ThreadsOAuthHandler] Error in exchange_oauth_code: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=ThreadsOAuthExchangeResponse(success=False, message="Internal error").model_dump()
            ))

    async def refresh_oauth_token(self, sid: str, request: ThreadsOAuthRefreshRequest) -> None:
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=ThreadsOAuthRefreshResponse(success=False, message="User not authenticated").model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=ThreadsOAuthRefreshResponse(success=False, message="Database connection not available").model_dump()
                ))
                return

            from wss.handlers.oauth.manual_refresh import manual_refresh_credential
            try:
                credential_data = await manual_refresh_credential(
                    pool, user_id=user_id, credential_id=request.credential_id,
                    provider="threads", refresh=refresh_access_token,
                )
            except ValueError as e:
                logger.error(f"[ThreadsOAuthHandler] Token refresh failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=ThreadsOAuthRefreshResponse(success=False, message=str(e)).model_dump()
                ))
                return

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=ThreadsOAuthRefreshResponse(
                    success=True, expires_at=credential_data.get('expires_at'),
                    message="Token refreshed successfully",
                ).model_dump()
            ))
        except Exception as e:
            logger.error(f"[ThreadsOAuthHandler] Error in refresh_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=ThreadsOAuthRefreshResponse(success=False, message="Internal error").model_dump()
            ))

    async def validate_oauth_token(self, sid: str, request: ThreadsOAuthValidateRequest) -> None:
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=ThreadsOAuthValidateResponse(valid=False, message="User not authenticated").model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=ThreadsOAuthValidateResponse(valid=False, message="Database connection not available").model_dump()
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
                        data=ThreadsOAuthValidateResponse(valid=False, message="Credential not found or access denied").model_dump()
                    ))
                    return
                try:
                    credential_data = self.encryption.decrypt_credential(row['credential'])
                except Exception as e:
                    logger.error(f"[ThreadsOAuthHandler] Decryption failed: {e}")
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=ThreadsOAuthValidateResponse(valid=False, message="Failed to decrypt credential").model_dump()
                    ))
                    return

                expires_at = credential_data.get('expires_at')
                name = credential_data.get('username') or (row['metadata'] or {}).get('username')
                if not expires_at:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=ThreadsOAuthValidateResponse(valid=True, expires_soon=False, name=name,
                                                          message="Token is valid").model_dump()
                    ))
                    return

                is_expired = is_token_expired(expires_at, buffer_days=0)
                expires_soon = is_token_expired(expires_at, buffer_days=7)
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=ThreadsOAuthValidateResponse(
                        valid=not is_expired,
                        expires_soon=expires_soon and not is_expired,
                        name=name,
                        message="Token is valid" if not is_expired else "Token has expired",
                    ).model_dump()
                ))
        except Exception as e:
            logger.error(f"[ThreadsOAuthHandler] Error in validate_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=ThreadsOAuthValidateResponse(valid=False, message="Internal error").model_dump()
            ))
