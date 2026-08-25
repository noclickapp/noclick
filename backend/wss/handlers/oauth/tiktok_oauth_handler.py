"""
Handler for TikTok Open Platform OAuth operations.
Manages OAuth 2.0 Authorization Code flow for TikTok API access.

Key implementation notes:
- TikTok uses 'client_key' instead of 'client_id' in OAuth requests
- Access tokens expire in 24 hours (buffer_minutes=60 for expires_soon check)
- Refresh tokens rotate on each refresh — both access_token and refresh_token are updated
- open_id is TikTok's unique user identifier per app (stored in credential data)
"""

import logging
from typing import Dict, Callable
from utils.database_pool import DatabasePoolMixin
from utils.encryption import get_encryption
from nodes.oauth.tiktok_oauth import (
    exchange_code_for_tokens,
    refresh_access_token,
    is_token_expired,
)
from wss.schema import SocketIOHandler
from wss.sender import send_event, ResponseEvent
from wss.sender.responses import (
    TikTokOAuthExchangeResponse,
    TikTokOAuthRefreshResponse,
    TikTokOAuthValidateResponse,
)
from wss.receiver.client_events import (
    TikTokOAuthExchangeRequest,
    TikTokOAuthRefreshRequest,
    TikTokOAuthValidateRequest,
)

logger = logging.getLogger(__name__)


class TikTokOAuthHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for TikTok OAuth WebSocket events"""

    def __init__(self, sio):
        super().__init__(sio)
        self.encryption = get_encryption()

    def get_events(self) -> Dict[str, Callable]:
        """Register TikTok OAuth events"""
        return {
            "tiktok:oauth:exchange": self.exchange_oauth_code,
            "tiktok:oauth:refresh": self.refresh_oauth_token,
            "tiktok:oauth:validate": self.validate_oauth_token,
        }

    async def setup_user(self, sid: str) -> None:
        _ = sid

    async def exchange_oauth_code(self, sid: str, request: TikTokOAuthExchangeRequest) -> None:
        """
        Exchange OAuth authorization code for tokens and store as credential.
        Called from the OAuth callback page after user grants permission.
        TikTok does not use PKCE, so only code + redirect_uri are needed.
        """
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=TikTokOAuthExchangeResponse(
                        success=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            # Exchange code for tokens (standard auth code, no PKCE)
            try:
                tokens, user_info = await exchange_code_for_tokens(
                    code=request.code,
                    redirect_uri=request.redirect_uri,
                )
            except ValueError as e:
                logger.error(f"[TikTokOAuthHandler] Token exchange failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=TikTokOAuthExchangeResponse(
                        success=False,
                        message=str(e)
                    ).model_dump()
                ))
                return

            # Prepare credential data — includes rotating refresh token
            credential_data = {
                'access_token': tokens.access_token,
                'refresh_token': tokens.refresh_token,
                'expires_at': tokens.expires_at,
                'refresh_expires_at': tokens.refresh_expires_at,
                'open_id': tokens.open_id,
                'display_name': user_info.display_name,
                'avatar_url': user_info.avatar_url,
                'scope': tokens.scope,
            }

            # Encrypt and store credential
            try:
                encrypted_data = self.encryption.encrypt_credential(credential_data)
            except Exception as e:
                logger.error(f"[TikTokOAuthHandler] Encryption failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=TikTokOAuthExchangeResponse(
                        success=False,
                        message="Failed to encrypt credential"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=TikTokOAuthExchangeResponse(
                        success=False,
                        message="Database connection not available"
                    ).model_dump()
                ))
                return

            # Use provided credential_name or derive from display_name
            credential_name = request.credential_name or (
                user_info.display_name or "TikTok Account"
            )

            async with pool.acquire() as conn:
                from repositories.credentials import create_credential_with_limit_check
                user_tier = session.get('user_data', {}).get('subscription_tier', 'free')
                row, error = await create_credential_with_limit_check(
                    conn, user_id, user_tier, 'tiktok_oauth',
                    credential_name, encrypted_data, {
                    'provider': 'tiktok',
                    'open_id': tokens.open_id,
                    'display_name': user_info.display_name,
                    'avatar_url': user_info.avatar_url,
                    'scopes': request.scopes,
                    },
                )
                if error:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={}, error=error
                    ))
                    return

                response = TikTokOAuthExchangeResponse(
                    success=True,
                    credential_id=str(row['id']),
                    credential_name=row['name'],
                    display_name=user_info.display_name,
                    message="TikTok account connected successfully"
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))
                logger.info(
                    f"[TikTokOAuthHandler] Created TikTok credential {row['id']} "
                    f"for user {user_id} (open_id={tokens.open_id})"
                )

        except Exception as e:
            logger.error(f"[TikTokOAuthHandler] Error in exchange_oauth_code: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=TikTokOAuthExchangeResponse(
                    success=False,
                    message="Internal error"
                ).model_dump()
            ))

    async def refresh_oauth_token(self, sid: str, request: TikTokOAuthRefreshRequest) -> None:
        """
        Refresh an expired OAuth token and update the stored credential.
        TikTok rotates refresh tokens, so both access_token and refresh_token are updated.
        """
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=TikTokOAuthRefreshResponse(
                        success=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=TikTokOAuthRefreshResponse(
                        success=False,
                        message="Database connection not available"
                    ).model_dump()
                ))
                return

            # Refresh-if-expired through the shared freshen choke point
            # (lock, in-lock re-read, CAS persist, audit row) — never a
            # bespoke unlocked UPDATE that races the execute-path refresh.
            from wss.handlers.oauth.manual_refresh import manual_refresh_credential

            def make_tiktok_refresh(credential):
                async def refresh(refresh_token: str):
                    # TikTok rotates refresh tokens and also issues a fresh
                    # refresh_expires_at, which the shared helper doesn't carry —
                    # stamp it into the credential dict so it persists with the rest.
                    tokens = await refresh_access_token(refresh_token)
                    if tokens.refresh_expires_at:
                        credential['refresh_expires_at'] = tokens.refresh_expires_at
                    return tokens
                return refresh

            try:
                credential_data = await manual_refresh_credential(
                    pool,
                    user_id=user_id,
                    credential_id=request.credential_id,
                    provider="tiktok",
                    make_refresh=make_tiktok_refresh,
                )
            except ValueError as e:
                logger.error(f"[TikTokOAuthHandler] Token refresh failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=TikTokOAuthRefreshResponse(
                        success=False,
                        message=str(e)
                    ).model_dump()
                ))
                return

            response = TikTokOAuthRefreshResponse(
                success=True,
                expires_at=credential_data.get('expires_at'),
                message="Token refreshed successfully"
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=response.model_dump()
            ))
            logger.info(f"[TikTokOAuthHandler] Refreshed token for credential {request.credential_id}")

        except Exception as e:
            logger.error(f"[TikTokOAuthHandler] Error in refresh_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=TikTokOAuthRefreshResponse(
                    success=False,
                    message="Internal error"
                ).model_dump()
            ))

    async def validate_oauth_token(self, sid: str, request: TikTokOAuthValidateRequest) -> None:
        """
        Validate if a stored OAuth credential is still valid.
        Uses a 60-minute expiry buffer since TikTok tokens only last 24 hours.
        """
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=TikTokOAuthValidateResponse(
                        valid=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=TikTokOAuthValidateResponse(
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
                        data=TikTokOAuthValidateResponse(
                            valid=False,
                            message="Credential not found or access denied"
                        ).model_dump()
                    ))
                    return

                try:
                    credential_data = self.encryption.decrypt_credential(row['credential'])
                except Exception as e:
                    logger.error(f"[TikTokOAuthHandler] Decryption failed: {e}")
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=TikTokOAuthValidateResponse(
                            valid=False,
                            message="Failed to decrypt credential"
                        ).model_dump()
                    ))
                    return

                expires_at = credential_data.get('expires_at')
                display_name = (
                    credential_data.get('display_name')
                    or row['metadata'].get('display_name')
                )

                # TikTok tokens expire in 24h — warn 60 minutes before expiry
                is_expired = is_token_expired(expires_at, buffer_minutes=0)
                expires_soon = is_token_expired(expires_at, buffer_minutes=60)

                response = TikTokOAuthValidateResponse(
                    valid=not is_expired,
                    expires_soon=expires_soon and not is_expired,
                    display_name=display_name,
                    message="Token is valid" if not is_expired else "Token has expired"
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))

        except Exception as e:
            logger.error(f"[TikTokOAuthHandler] Error in validate_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=TikTokOAuthValidateResponse(
                    valid=False,
                    message="Internal error"
                ).model_dump()
            ))
