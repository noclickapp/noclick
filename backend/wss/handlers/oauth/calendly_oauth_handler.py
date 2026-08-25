"""
Handler for Calendly OAuth operations.
Manages the OAuth 2.0 authorization_code flow for the Calendly REST API v2.

Calendly access tokens are short-lived (~2h) and refresh tokens are single-use /
rotating, so refresh goes through the shared freshen choke point
(manual_refresh_credential), never a bespoke unlocked UPDATE.
"""

import logging
from typing import Dict, Callable

from utils.database_pool import DatabasePoolMixin
from utils.encryption import get_encryption
from nodes.oauth.calendly_oauth import (
    exchange_code_for_tokens,
    refresh_access_token,
    is_token_expired,
)
from wss.schema import SocketIOHandler
from wss.sender import send_event, ResponseEvent
from wss.sender.responses import (
    CalendlyOAuthExchangeResponse,
    CalendlyOAuthRefreshResponse,
    CalendlyOAuthValidateResponse,
)
from wss.receiver.client_events import (
    CalendlyOAuthExchangeRequest,
    CalendlyOAuthRefreshRequest,
    CalendlyOAuthValidateRequest,
)

logger = logging.getLogger(__name__)


class CalendlyOAuthHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for Calendly OAuth WebSocket events"""

    def __init__(self, sio):
        super().__init__(sio)
        self.encryption = get_encryption()

    def get_events(self) -> Dict[str, Callable]:
        return {
            "calendly:oauth:exchange": self.exchange_oauth_code,
            "calendly:oauth:refresh": self.refresh_oauth_token,
            "calendly:oauth:validate": self.validate_oauth_token,
        }

    async def setup_user(self, sid: str) -> None:
        # Pool is acquired lazily via get_pool(); no per-user setup needed.
        _ = sid

    async def exchange_oauth_code(self, sid: str, request: CalendlyOAuthExchangeRequest) -> None:
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=CalendlyOAuthExchangeResponse(success=False, message="User not authenticated").model_dump()))
                return

            try:
                tokens, user_info = await exchange_code_for_tokens(
                    code=request.code, redirect_uri=request.redirect_uri,
                )
            except ValueError as e:
                logger.error(f"[CalendlyOAuthHandler] Token exchange failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=CalendlyOAuthExchangeResponse(success=False, message=str(e)).model_dump()))
                return

            credential_data = {
                'access_token': tokens.access_token,
                'refresh_token': tokens.refresh_token,
                'expires_at': tokens.expires_at,
                'owner': tokens.owner,
                'organization': tokens.organization,
                'name': user_info.name,
                'email': user_info.email,
            }
            try:
                encrypted_data = self.encryption.encrypt_credential(credential_data)
            except Exception as e:
                logger.error(f"[CalendlyOAuthHandler] Encryption failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=CalendlyOAuthExchangeResponse(success=False, message="Failed to encrypt credential").model_dump()))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=CalendlyOAuthExchangeResponse(success=False, message="Database connection not available").model_dump()))
                return

            credential_name = user_info.name or user_info.email or "Calendly"
            async with pool.acquire() as conn:
                from repositories.credentials import create_credential_with_limit_check
                user_tier = session.get('user_data', {}).get('subscription_tier', 'free')
                row, error = await create_credential_with_limit_check(
                    conn, user_id, user_tier, 'calendly_oauth',
                    credential_name, encrypted_data, {
                        'provider': 'calendly',
                        'name': user_info.name,
                        'email': user_info.email,
                        'calendly_user_uri': user_info.uri,
                        'organization': tokens.organization,
                        'scopes': request.scopes,
                    },
                )
                if error:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={}, error=error))
                    return

                response = CalendlyOAuthExchangeResponse(
                    success=True,
                    credential_id=str(row['id']),
                    credential_name=row['name'],
                    name=user_info.name,
                    email=user_info.email,
                    message="Calendly account connected successfully",
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data=response.model_dump()))
                logger.info(f"[CalendlyOAuthHandler] Created Calendly credential {row['id']} for user {user_id}")

        except Exception as e:
            logger.error(f"[CalendlyOAuthHandler] Error in exchange_oauth_code: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=CalendlyOAuthExchangeResponse(success=False, message="Internal error").model_dump()))

    async def refresh_oauth_token(self, sid: str, request: CalendlyOAuthRefreshRequest) -> None:
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=CalendlyOAuthRefreshResponse(success=False, message="User not authenticated").model_dump()))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=CalendlyOAuthRefreshResponse(success=False, message="Database connection not available").model_dump()))
                return

            from wss.handlers.oauth.manual_refresh import manual_refresh_credential
            try:
                credential_data = await manual_refresh_credential(
                    pool, user_id=user_id, credential_id=request.credential_id,
                    provider="calendly",
                    make_refresh=lambda credential: refresh_access_token,
                )
            except ValueError as e:
                logger.error(f"[CalendlyOAuthHandler] Token refresh failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=CalendlyOAuthRefreshResponse(success=False, message=str(e)).model_dump()))
                return

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=CalendlyOAuthRefreshResponse(
                    success=True, expires_at=credential_data.get('expires_at'),
                    message="Token refreshed successfully").model_dump()))

        except Exception as e:
            logger.error(f"[CalendlyOAuthHandler] Error in refresh_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=CalendlyOAuthRefreshResponse(success=False, message="Internal error").model_dump()))

    async def validate_oauth_token(self, sid: str, request: CalendlyOAuthValidateRequest) -> None:
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=CalendlyOAuthValidateResponse(valid=False, message="User not authenticated").model_dump()))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=CalendlyOAuthValidateResponse(valid=False, message="Database connection not available").model_dump()))
                return

            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id, credential, metadata FROM credentials WHERE id = $1 AND owner_id = $2",
                    request.credential_id, user_id)
                if not row:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=CalendlyOAuthValidateResponse(valid=False, message="Credential not found or access denied").model_dump()))
                    return

                try:
                    credential_data = self.encryption.decrypt_credential(row['credential'])
                except Exception as e:
                    logger.error(f"[CalendlyOAuthHandler] Decryption failed: {e}")
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=CalendlyOAuthValidateResponse(valid=False, message="Failed to decrypt credential").model_dump()))
                    return

                expires_at = credential_data.get('expires_at')
                name = credential_data.get('name') or (row['metadata'] or {}).get('name')
                email = credential_data.get('email') or (row['metadata'] or {}).get('email')

                if not expires_at:
                    # No stored expiry: auto-refreshed on use, treat as valid.
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=CalendlyOAuthValidateResponse(valid=True, expires_soon=False, name=name, email=email, message="Token is valid").model_dump()))
                    return

                is_expired = is_token_expired(expires_at, buffer_minutes=0)
                expires_soon = is_token_expired(expires_at, buffer_minutes=5)
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=CalendlyOAuthValidateResponse(
                        valid=not is_expired, expires_soon=expires_soon and not is_expired,
                        name=name, email=email,
                        message="Token is valid" if not is_expired else "Token has expired").model_dump()))

        except Exception as e:
            logger.error(f"[CalendlyOAuthHandler] Error in validate_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=CalendlyOAuthValidateResponse(valid=False, message="Internal error").model_dump()))
