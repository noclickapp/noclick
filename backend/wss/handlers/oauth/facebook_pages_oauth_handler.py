"""
Handler for the Facebook Pages OAuth flow (distinct from the Instagram-focused
`facebook` provider). Exchanges a Facebook Login code into a facebook_oauth
credential — a long-lived user token from which Page tokens are derived.
"""

import logging
from typing import Callable, Dict

from utils.database_pool import DatabasePoolMixin
from utils.encryption import get_encryption
from nodes.oauth.facebook_oauth import (
    exchange_code_for_facebook_tokens,
    refresh_access_token,
    is_token_expired,
)
from wss.schema import SocketIOHandler
from wss.sender import send_event, ResponseEvent
from wss.sender.responses import (
    FacebookPagesOAuthExchangeResponse,
    FacebookPagesOAuthRefreshResponse,
    FacebookPagesOAuthValidateResponse,
)
from wss.receiver.client_events import (
    FacebookPagesOAuthExchangeRequest,
    FacebookPagesOAuthRefreshRequest,
    FacebookPagesOAuthValidateRequest,
)

logger = logging.getLogger(__name__)


class FacebookPagesOAuthHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for Facebook Pages OAuth WebSocket events"""

    def __init__(self, sio):
        super().__init__(sio)
        self.encryption = get_encryption()

    def get_events(self) -> Dict[str, Callable]:
        return {
            "facebook_pages:oauth:exchange": self.exchange_oauth_code,
            "facebook_pages:oauth:refresh": self.refresh_oauth_token,
            "facebook_pages:oauth:validate": self.validate_oauth_token,
        }

    async def setup_user(self, sid: str) -> None:
        _ = sid

    async def exchange_oauth_code(self, sid: str, request: FacebookPagesOAuthExchangeRequest) -> None:
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(request_id=request.request_id,
                    data=FacebookPagesOAuthExchangeResponse(success=False, message="User not authenticated").model_dump()))
                return
            try:
                tokens, info = await exchange_code_for_facebook_tokens(code=request.code, redirect_uri=request.redirect_uri)
            except ValueError as e:
                logger.error(f"[FacebookPagesOAuthHandler] Token exchange failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(request_id=request.request_id,
                    data=FacebookPagesOAuthExchangeResponse(success=False, message=str(e)).model_dump()))
                return

            credential_data = {
                'access_token': tokens.access_token, 'expires_at': tokens.expires_at,
                'email': info.email, 'facebook_user_id': info.facebook_user_id,
            }
            try:
                encrypted = self.encryption.encrypt_credential(credential_data)
            except Exception as e:
                logger.error(f"[FacebookPagesOAuthHandler] Encryption failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(request_id=request.request_id,
                    data=FacebookPagesOAuthExchangeResponse(success=False, message="Failed to encrypt credential").model_dump()))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(request_id=request.request_id,
                    data=FacebookPagesOAuthExchangeResponse(success=False, message="Database connection not available").model_dump()))
                return

            credential_name = info.name or info.email or "Facebook"
            async with pool.acquire() as conn:
                from repositories.credentials import create_credential_with_limit_check
                user_tier = session.get('user_data', {}).get('subscription_tier', 'free')
                row, error = await create_credential_with_limit_check(
                    conn, user_id, user_tier, 'facebook_oauth', credential_name, encrypted,
                    {'provider': 'facebook_pages', 'name': info.name, 'email': info.email,
                     'facebook_user_id': info.facebook_user_id, 'scopes': request.scopes})
                if error:
                    await send_event(self.sio, sid, ResponseEvent(request_id=request.request_id, data={}, error=error))
                    return
                await send_event(self.sio, sid, ResponseEvent(request_id=request.request_id,
                    data=FacebookPagesOAuthExchangeResponse(
                        success=True, credential_id=str(row['id']), credential_name=row['name'],
                        name=info.name, email=info.email, message="Facebook account connected successfully").model_dump()))
                logger.info(f"[FacebookPagesOAuthHandler] Created facebook_oauth credential {row['id']} for user {user_id}")
        except Exception as e:
            logger.error(f"[FacebookPagesOAuthHandler] Error in exchange_oauth_code: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(request_id=request.request_id,
                data=FacebookPagesOAuthExchangeResponse(success=False, message="Internal error").model_dump()))

    async def refresh_oauth_token(self, sid: str, request: FacebookPagesOAuthRefreshRequest) -> None:
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(request_id=request.request_id,
                    data=FacebookPagesOAuthRefreshResponse(success=False, message="User not authenticated").model_dump()))
                return
            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(request_id=request.request_id,
                    data=FacebookPagesOAuthRefreshResponse(success=False, message="Database connection not available").model_dump()))
                return
            from wss.handlers.oauth.manual_refresh import manual_refresh_credential
            try:
                cred = await manual_refresh_credential(pool, user_id=user_id, credential_id=request.credential_id,
                                                       provider="facebook", refresh=refresh_access_token)
            except ValueError as e:
                await send_event(self.sio, sid, ResponseEvent(request_id=request.request_id,
                    data=FacebookPagesOAuthRefreshResponse(success=False, message=str(e)).model_dump()))
                return
            await send_event(self.sio, sid, ResponseEvent(request_id=request.request_id,
                data=FacebookPagesOAuthRefreshResponse(success=True, expires_at=cred.get('expires_at'),
                    message="Token refreshed successfully").model_dump()))
        except Exception as e:
            logger.error(f"[FacebookPagesOAuthHandler] Error in refresh_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(request_id=request.request_id,
                data=FacebookPagesOAuthRefreshResponse(success=False, message="Internal error").model_dump()))

    async def validate_oauth_token(self, sid: str, request: FacebookPagesOAuthValidateRequest) -> None:
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(request_id=request.request_id,
                    data=FacebookPagesOAuthValidateResponse(valid=False, message="User not authenticated").model_dump()))
                return
            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(request_id=request.request_id,
                    data=FacebookPagesOAuthValidateResponse(valid=False, message="Database connection not available").model_dump()))
                return
            async with pool.acquire() as conn:
                row = await conn.fetchrow("SELECT id, credential, metadata FROM credentials WHERE id = $1 AND owner_id = $2",
                                          request.credential_id, user_id)
                if not row:
                    await send_event(self.sio, sid, ResponseEvent(request_id=request.request_id,
                        data=FacebookPagesOAuthValidateResponse(valid=False, message="Credential not found or access denied").model_dump()))
                    return
                cred = self.encryption.decrypt_credential(row['credential'])
                expires_at = cred.get('expires_at')
                name = cred.get('name') or (row['metadata'] or {}).get('name')
                email = cred.get('email') or (row['metadata'] or {}).get('email')
                if not expires_at:
                    await send_event(self.sio, sid, ResponseEvent(request_id=request.request_id,
                        data=FacebookPagesOAuthValidateResponse(valid=True, expires_soon=False, name=name, email=email,
                            message="Token is valid").model_dump()))
                    return
                is_exp = is_token_expired(expires_at, buffer_days=0)
                soon = is_token_expired(expires_at, buffer_days=7)
                await send_event(self.sio, sid, ResponseEvent(request_id=request.request_id,
                    data=FacebookPagesOAuthValidateResponse(valid=not is_exp, expires_soon=soon and not is_exp,
                        name=name, email=email, message="Token is valid" if not is_exp else "Token has expired").model_dump()))
        except Exception as e:
            logger.error(f"[FacebookPagesOAuthHandler] Error in validate_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(request_id=request.request_id,
                data=FacebookPagesOAuthValidateResponse(valid=False, message="Internal error").model_dump()))
