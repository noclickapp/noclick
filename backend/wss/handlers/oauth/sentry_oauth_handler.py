"""
Handler for Sentry OAuth operations.
Manages the OAuth 2.0 authorization_code flow for the Sentry REST API.

Access tokens last ~30 days; refresh goes through the shared freshen choke point
(manual_refresh_credential), never a bespoke unlocked UPDATE. The default org
slug is resolved right after exchange so dropdowns work immediately.
"""

import logging
from typing import Dict, Callable, Optional

import httpx

from utils.database_pool import DatabasePoolMixin
from utils.encryption import get_encryption
from nodes.oauth.sentry_oauth import (
    exchange_code_for_tokens,
    refresh_access_token,
    is_token_expired,
)
from wss.schema import SocketIOHandler
from wss.sender import send_event, ResponseEvent
from wss.sender.responses import (
    SentryOAuthExchangeResponse,
    SentryOAuthRefreshResponse,
    SentryOAuthValidateResponse,
)
from wss.receiver.client_events import (
    SentryOAuthExchangeRequest,
    SentryOAuthRefreshRequest,
    SentryOAuthValidateRequest,
)

logger = logging.getLogger(__name__)


async def _resolve_default_org(access_token: str) -> Optional[str]:
    """First accessible org slug (US host — org is region-scoped but the slug is
    stable; the node re-resolves per its configured region if blank)."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://sentry.io/api/0/organizations/",
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
                params={"per_page": 1},
            )
            if resp.status_code == 200:
                rows = resp.json()
                if isinstance(rows, list) and rows:
                    return rows[0].get("slug")
    except Exception as e:
        logger.warning(f"[SentryOAuthHandler] Could not resolve default org: {e}")
    return None


class SentryOAuthHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for Sentry OAuth WebSocket events"""

    def __init__(self, sio):
        super().__init__(sio)
        self.encryption = get_encryption()

    def get_events(self) -> Dict[str, Callable]:
        return {
            "sentry:oauth:exchange": self.exchange_oauth_code,
            "sentry:oauth:refresh": self.refresh_oauth_token,
            "sentry:oauth:validate": self.validate_oauth_token,
        }

    async def setup_user(self, sid: str) -> None:
        _ = sid

    async def exchange_oauth_code(self, sid: str, request: SentryOAuthExchangeRequest) -> None:
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=SentryOAuthExchangeResponse(success=False, message="User not authenticated").model_dump()))
                return

            try:
                tokens, user_info = await exchange_code_for_tokens(
                    code=request.code, redirect_uri=request.redirect_uri,
                )
            except ValueError as e:
                logger.error(f"[SentryOAuthHandler] Token exchange failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=SentryOAuthExchangeResponse(success=False, message=str(e)).model_dump()))
                return

            org_slug = await _resolve_default_org(tokens.access_token)
            credential_data = {
                'access_token': tokens.access_token,
                'refresh_token': tokens.refresh_token,
                'expires_at': tokens.expires_at,
                'region': 'us',
                'organization_slug': org_slug,
                'name': user_info.name,
                'email': user_info.email,
            }
            try:
                encrypted_data = self.encryption.encrypt_credential(credential_data)
            except Exception as e:
                logger.error(f"[SentryOAuthHandler] Encryption failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=SentryOAuthExchangeResponse(success=False, message="Failed to encrypt credential").model_dump()))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=SentryOAuthExchangeResponse(success=False, message="Database connection not available").model_dump()))
                return

            credential_name = user_info.name or user_info.email or "Sentry"
            async with pool.acquire() as conn:
                from repositories.credentials import create_credential_with_limit_check
                user_tier = session.get('user_data', {}).get('subscription_tier', 'free')
                row, error = await create_credential_with_limit_check(
                    conn, user_id, user_tier, 'sentry_oauth',
                    credential_name, encrypted_data, {
                        'provider': 'sentry',
                        'name': user_info.name,
                        'email': user_info.email,
                        'organization_slug': org_slug,
                        'scopes': request.scopes,
                    },
                )
                if error:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={}, error=error))
                    return

                response = SentryOAuthExchangeResponse(
                    success=True,
                    credential_id=str(row['id']),
                    credential_name=row['name'],
                    name=user_info.name,
                    email=user_info.email,
                    message="Sentry account connected successfully",
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data=response.model_dump()))
                logger.info(f"[SentryOAuthHandler] Created Sentry credential {row['id']} for user {user_id}")

        except Exception as e:
            logger.error(f"[SentryOAuthHandler] Error in exchange_oauth_code: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=SentryOAuthExchangeResponse(success=False, message="Internal error").model_dump()))

    async def refresh_oauth_token(self, sid: str, request: SentryOAuthRefreshRequest) -> None:
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=SentryOAuthRefreshResponse(success=False, message="User not authenticated").model_dump()))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=SentryOAuthRefreshResponse(success=False, message="Database connection not available").model_dump()))
                return

            from wss.handlers.oauth.manual_refresh import manual_refresh_credential
            try:
                credential_data = await manual_refresh_credential(
                    pool, user_id=user_id, credential_id=request.credential_id,
                    provider="sentry",
                    make_refresh=lambda credential: refresh_access_token,
                )
            except ValueError as e:
                logger.error(f"[SentryOAuthHandler] Token refresh failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=SentryOAuthRefreshResponse(success=False, message=str(e)).model_dump()))
                return

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=SentryOAuthRefreshResponse(
                    success=True, expires_at=credential_data.get('expires_at'),
                    message="Token refreshed successfully").model_dump()))

        except Exception as e:
            logger.error(f"[SentryOAuthHandler] Error in refresh_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=SentryOAuthRefreshResponse(success=False, message="Internal error").model_dump()))

    async def validate_oauth_token(self, sid: str, request: SentryOAuthValidateRequest) -> None:
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=SentryOAuthValidateResponse(valid=False, message="User not authenticated").model_dump()))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=SentryOAuthValidateResponse(valid=False, message="Database connection not available").model_dump()))
                return

            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id, credential, metadata FROM credentials WHERE id = $1 AND owner_id = $2",
                    request.credential_id, user_id)
                if not row:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=SentryOAuthValidateResponse(valid=False, message="Credential not found or access denied").model_dump()))
                    return

                try:
                    credential_data = self.encryption.decrypt_credential(row['credential'])
                except Exception as e:
                    logger.error(f"[SentryOAuthHandler] Decryption failed: {e}")
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=SentryOAuthValidateResponse(valid=False, message="Failed to decrypt credential").model_dump()))
                    return

                expires_at = credential_data.get('expires_at')
                name = credential_data.get('name') or (row['metadata'] or {}).get('name')
                email = credential_data.get('email') or (row['metadata'] or {}).get('email')

                if not expires_at:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=SentryOAuthValidateResponse(valid=True, expires_soon=False, name=name, email=email, message="Token is valid").model_dump()))
                    return

                is_expired = is_token_expired(expires_at, buffer_minutes=0)
                expires_soon = is_token_expired(expires_at, buffer_minutes=5)
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=SentryOAuthValidateResponse(
                        valid=not is_expired, expires_soon=expires_soon and not is_expired,
                        name=name, email=email,
                        message="Token is valid" if not is_expired else "Token has expired").model_dump()))

        except Exception as e:
            logger.error(f"[SentryOAuthHandler] Error in validate_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=SentryOAuthValidateResponse(valid=False, message="Internal error").model_dump()))
