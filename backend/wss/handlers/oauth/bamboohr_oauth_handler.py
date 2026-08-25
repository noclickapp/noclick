"""
Handler for BambooHR OAuth operations.
Manages the OAuth 2.0 authorization_code flow for the BambooHR REST API.

BambooHR OAuth is subdomain-scoped, so the subdomain travels with the exchange
request and is stored on the credential — the refresher reads it back off the
loaded credential via a make_refresh closure (mirrors Zendesk / Salesforce).
BambooHR OAuth is limited to approved Marketplace apps; the API-key credential
is the primary, unrestricted path.
"""

import logging
from typing import Dict, Callable
from utils.database_pool import DatabasePoolMixin
from utils.encryption import get_encryption
from nodes.oauth.bamboohr_oauth import (
    exchange_code_for_tokens,
    refresh_access_token,
    is_token_expired,
)
from wss.schema import SocketIOHandler
from wss.sender import send_event, ResponseEvent
from wss.sender.responses import (
    BambooHROAuthExchangeResponse,
    BambooHROAuthRefreshResponse,
    BambooHROAuthValidateResponse,
)
from wss.receiver.client_events import (
    BambooHROAuthExchangeRequest,
    BambooHROAuthRefreshRequest,
    BambooHROAuthValidateRequest,
)

logger = logging.getLogger(__name__)


class BambooHROAuthHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for BambooHR OAuth WebSocket events"""

    def __init__(self, sio):
        super().__init__(sio)
        self.encryption = get_encryption()

    def get_events(self) -> Dict[str, Callable]:
        return {
            "bamboohr:oauth:exchange": self.exchange_oauth_code,
            "bamboohr:oauth:refresh": self.refresh_oauth_token,
            "bamboohr:oauth:validate": self.validate_oauth_token,
        }

    async def setup_user(self, sid: str) -> None:
        _ = sid

    async def exchange_oauth_code(self, sid: str, request: BambooHROAuthExchangeRequest) -> None:
        """Exchange the authorization code for tokens and store as a credential."""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=BambooHROAuthExchangeResponse(success=False, message="User not authenticated").model_dump()
                ))
                return

            try:
                tokens, user_info = await exchange_code_for_tokens(
                    code=request.code,
                    redirect_uri=request.redirect_uri,
                    subdomain=request.subdomain,
                )
            except ValueError as e:
                logger.error(f"[BambooHROAuthHandler] Token exchange failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=BambooHROAuthExchangeResponse(success=False, message=str(e)).model_dump()
                ))
                return

            # OAuth returns the company context; fall back to the requested subdomain.
            subdomain = tokens.company_domain or request.subdomain
            credential_data = {
                'subdomain': subdomain,
                'access_token': tokens.access_token,
                'refresh_token': tokens.refresh_token,
                'expires_at': tokens.expires_at,
                'name': user_info.name,
                'email': user_info.email,
            }

            try:
                encrypted_data = self.encryption.encrypt_credential(credential_data)
            except Exception as e:
                logger.error(f"[BambooHROAuthHandler] Encryption failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=BambooHROAuthExchangeResponse(success=False, message="Failed to encrypt credential").model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=BambooHROAuthExchangeResponse(success=False, message="Database connection not available").model_dump()
                ))
                return

            credential_name = user_info.name or user_info.email or f"BambooHR ({subdomain})"
            async with pool.acquire() as conn:
                from repositories.credentials import create_credential_with_limit_check
                user_tier = session.get('user_data', {}).get('subscription_tier', 'free')
                row, error = await create_credential_with_limit_check(
                    conn, user_id, user_tier, 'bamboohr_oauth',
                    credential_name, encrypted_data, {
                        'provider': 'bamboohr',
                        'name': user_info.name,
                        'email': user_info.email,
                        'subdomain': subdomain,
                        'scopes': request.scopes,
                    },
                )
                if error:
                    await send_event(self.sio, sid, ResponseEvent(request_id=request.request_id, data={}, error=error))
                    return

                response = BambooHROAuthExchangeResponse(
                    success=True,
                    credential_id=str(row['id']),
                    credential_name=row['name'],
                    name=user_info.name,
                    email=user_info.email,
                    message="BambooHR account connected successfully",
                )
                await send_event(self.sio, sid, ResponseEvent(request_id=request.request_id, data=response.model_dump()))
                logger.info(f"[BambooHROAuthHandler] Created BambooHR credential {row['id']} for user {user_id}")

        except Exception as e:
            logger.error(f"[BambooHROAuthHandler] Error in exchange_oauth_code: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=BambooHROAuthExchangeResponse(success=False, message="Internal error").model_dump()
            ))

    async def refresh_oauth_token(self, sid: str, request: BambooHROAuthRefreshRequest) -> None:
        """Refresh an expired OAuth token through the shared freshen choke point."""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=BambooHROAuthRefreshResponse(success=False, message="User not authenticated").model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=BambooHROAuthRefreshResponse(success=False, message="Database connection not available").model_dump()
                ))
                return

            from wss.handlers.oauth.manual_refresh import manual_refresh_credential

            def _make_refresh(credential):
                subdomain = credential.get('subdomain')

                async def _refresh(refresh_token: str):
                    return await refresh_access_token(refresh_token=refresh_token, subdomain=subdomain)

                return _refresh

            try:
                credential_data = await manual_refresh_credential(
                    pool,
                    user_id=user_id,
                    credential_id=request.credential_id,
                    provider="bamboohr",
                    make_refresh=_make_refresh,
                )
            except ValueError as e:
                logger.error(f"[BambooHROAuthHandler] Token refresh failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=BambooHROAuthRefreshResponse(success=False, message=str(e)).model_dump()
                ))
                return

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=BambooHROAuthRefreshResponse(
                    success=True,
                    expires_at=credential_data.get('expires_at'),
                    message="Token refreshed successfully",
                ).model_dump()
            ))
            logger.info(f"[BambooHROAuthHandler] Refreshed token for credential {request.credential_id}")

        except Exception as e:
            logger.error(f"[BambooHROAuthHandler] Error in refresh_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=BambooHROAuthRefreshResponse(success=False, message="Internal error").model_dump()
            ))

    async def validate_oauth_token(self, sid: str, request: BambooHROAuthValidateRequest) -> None:
        """Validate whether a stored OAuth credential is still valid."""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=BambooHROAuthValidateResponse(valid=False, message="User not authenticated").model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=BambooHROAuthValidateResponse(valid=False, message="Database connection not available").model_dump()
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
                        data=BambooHROAuthValidateResponse(valid=False, message="Credential not found or access denied").model_dump()
                    ))
                    return

                try:
                    credential_data = self.encryption.decrypt_credential(row['credential'])
                except Exception as e:
                    logger.error(f"[BambooHROAuthHandler] Decryption failed: {e}")
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=BambooHROAuthValidateResponse(valid=False, message="Failed to decrypt credential").model_dump()
                    ))
                    return

                expires_at = credential_data.get('expires_at')
                name = credential_data.get('name') or (row['metadata'] or {}).get('name')
                email = credential_data.get('email') or (row['metadata'] or {}).get('email')

                if not expires_at:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=BambooHROAuthValidateResponse(valid=True, expires_soon=False, name=name, email=email, message="Token is valid").model_dump()
                    ))
                    return

                is_expired = is_token_expired(expires_at, buffer_minutes=0)
                expires_soon = is_token_expired(expires_at, buffer_minutes=5)
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=BambooHROAuthValidateResponse(
                        valid=not is_expired,
                        expires_soon=expires_soon and not is_expired,
                        name=name, email=email,
                        message="Token is valid" if not is_expired else "Token has expired",
                    ).model_dump()
                ))

        except Exception as e:
            logger.error(f"[BambooHROAuthHandler] Error in validate_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=BambooHROAuthValidateResponse(valid=False, message="Internal error").model_dump()
            ))
