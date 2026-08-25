"""
Handler for WordPress OAuth operations.
Manages OAuth token exchange, refresh, and validation for WordPress.com integrations.
"""

import logging
from typing import Dict, Callable
from utils.database_pool import DatabasePoolMixin
from utils.encryption import get_encryption
from nodes.oauth.wordpress_oauth import (
    exchange_code_for_tokens,
    refresh_access_token,
    is_token_expired,
)
from wss.schema import SocketIOHandler
from wss.sender import send_event, ResponseEvent
from wss.sender.responses import (
    WordPressOAuthExchangeResponse,
    WordPressOAuthRefreshResponse,
    WordPressOAuthValidateResponse,
    CredentialInfo,
)
from wss.receiver.client_events import (
    WordPressOAuthExchangeRequest,
    WordPressOAuthRefreshRequest,
    WordPressOAuthValidateRequest,
)

logger = logging.getLogger(__name__)


class WordPressOAuthHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for WordPress OAuth WebSocket events"""

    def __init__(self, sio):
        super().__init__(sio)
        self.encryption = get_encryption()

    def get_events(self) -> Dict[str, Callable]:
        """Register WordPress OAuth events"""
        return {
            "wordpress:oauth:exchange": self.exchange_oauth_code,
            "wordpress:oauth:refresh": self.refresh_oauth_token,
            "wordpress:oauth:validate": self.validate_oauth_token,
        }

    async def setup_user(self, sid: str) -> None:
        _ = sid

    async def exchange_oauth_code(self, sid: str, request: WordPressOAuthExchangeRequest) -> None:
        """
        Exchange OAuth authorization code for tokens and store as credential.
        Called from the OAuth callback page after user grants permission.
        """
        try:
            # Get user session
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WordPressOAuthExchangeResponse(
                        success=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            # Exchange code for tokens
            try:
                tokens, user_info = await exchange_code_for_tokens(
                    code=request.code,
                    redirect_uri=request.redirect_uri,
                )
            except ValueError as e:
                logger.error(f"[WordPressOAuthHandler] Token exchange failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WordPressOAuthExchangeResponse(
                        success=False,
                        message=str(e)
                    ).model_dump()
                ))
                return

            # Prepare credential data
            # Clean site_id: remove protocol if present (WordPress.com API expects domain only)
            site_id = request.site_id or user_info.primary_site_url
            if site_id and isinstance(site_id, str):
                # Remove http:// or https:// prefix
                site_id = site_id.replace('https://', '').replace('http://', '').rstrip('/')
            elif not site_id:
                # Fallback to user ID
                site_id = str(user_info.id)

            credential_data = {
                'access_token': tokens.access_token,
                'refresh_token': tokens.refresh_token,
                'expires_at': tokens.expires_at,
                'scope': tokens.scope,
                'site_id': site_id,
                'email': user_info.email,
                'username': user_info.username,
                'primary_site_url': user_info.primary_site_url,
            }

            # Encrypt and store credential
            try:
                encrypted_data = self.encryption.encrypt_credential(credential_data)
            except Exception as e:
                logger.error(f"[WordPressOAuthHandler] Encryption failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WordPressOAuthExchangeResponse(
                        success=False,
                        message="Failed to encrypt credential"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WordPressOAuthExchangeResponse(
                        success=False,
                        message="Database connection not available"
                    ).model_dump()
                ))
                return

            # Credential type is always wordpress_oauth for OAuth flow
            credential_type = 'wordpress_oauth'

            # Use site URL or username as the credential name for better identification
            credential_name = user_info.primary_site_url or user_info.username or user_info.email

            async with pool.acquire() as conn:
                from repositories.credentials import create_credential_with_limit_check
                user_tier = session.get('user_data', {}).get('subscription_tier', 'free')
                row, error = await create_credential_with_limit_check(
                    conn, user_id, user_tier, credential_type,
                    credential_name, encrypted_data, {
                        'provider': 'wordpress',
                        'email': user_info.email,
                        'username': user_info.username,
                        'site_id': credential_data['site_id'],
                        'site_url': user_info.primary_site_url,
                        'scopes': request.scopes,
                    },
                )
                if error:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={}, error=error
                    ))
                    return

                response = WordPressOAuthExchangeResponse(
                    success=True,
                    credential_id=str(row['id']),
                    credential_name=row['name'],
                    email=user_info.email,
                    username=user_info.username,
                    site_url=user_info.primary_site_url,
                    message="WordPress.com account connected successfully"
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))
                logger.info(f"[WordPressOAuthHandler] Created WordPress credential {row['id']} for user {user_id} ({user_info.username})")

        except Exception as e:
            logger.error(f"[WordPressOAuthHandler] Error in exchange_oauth_code: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=WordPressOAuthExchangeResponse(
                    success=False,
                    message="Internal error"
                ).model_dump()
            ))

    async def refresh_oauth_token(self, sid: str, request: WordPressOAuthRefreshRequest) -> None:
        """
        Refresh an expired OAuth token and update the stored credential.
        Note: WordPress.com tokens are long-lived and typically don't expire.
        """
        try:
            # Get user session
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WordPressOAuthRefreshResponse(
                        success=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WordPressOAuthRefreshResponse(
                        success=False,
                        message="Database connection not available"
                    ).model_dump()
                ))
                return

            # Refresh-if-expired through the shared freshen choke point
            # (lock, in-lock re-read, CAS persist, audit row) — never a
            # bespoke unlocked UPDATE that races the execute-path refresh.
            from wss.handlers.oauth.manual_refresh import manual_refresh_credential

            try:
                await manual_refresh_credential(
                    pool,
                    user_id=user_id,
                    credential_id=request.credential_id,
                    provider="wordpress",
                    refresh=refresh_access_token,
                )
            except ValueError as e:
                logger.error(f"[WordPressOAuthHandler] Token refresh failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WordPressOAuthRefreshResponse(
                        success=False,
                        message=str(e)
                    ).model_dump()
                ))
                return

            response = WordPressOAuthRefreshResponse(
                success=True,
                message="Token refreshed successfully"
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=response.model_dump()
            ))
            logger.info(f"[WordPressOAuthHandler] Refreshed token for credential {request.credential_id}")

        except Exception as e:
            logger.error(f"[WordPressOAuthHandler] Error in refresh_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=WordPressOAuthRefreshResponse(
                    success=False,
                    message="Internal error"
                ).model_dump()
            ))

    async def validate_oauth_token(self, sid: str, request: WordPressOAuthValidateRequest) -> None:
        """
        Validate if a WordPress OAuth token is still valid.
        WordPress.com tokens are long-lived and don't typically expire.
        """
        try:
            # Get user session
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WordPressOAuthValidateResponse(
                        success=False,
                        is_valid=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WordPressOAuthValidateResponse(
                        success=False,
                        is_valid=False,
                        message="Database connection not available"
                    ).model_dump()
                ))
                return

            async with pool.acquire() as conn:
                # Fetch credential (verify ownership)
                row = await conn.fetchrow("""
                    SELECT id, credential
                    FROM credentials
                    WHERE id = $1 AND owner_id = $2
                """, request.credential_id, user_id)

                if not row:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=WordPressOAuthValidateResponse(
                            success=False,
                            is_valid=False,
                            message="Credential not found or access denied"
                        ).model_dump()
                    ))
                    return

                # Decrypt credential
                try:
                    credential_data = self.encryption.decrypt_credential(row['credential'])
                except Exception as e:
                    logger.error(f"[WordPressOAuthHandler] Decryption failed: {e}")
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=WordPressOAuthValidateResponse(
                            success=False,
                            is_valid=False,
                            message="Failed to decrypt credential"
                        ).model_dump()
                    ))
                    return

                # Check if token is expired
                expires_at = credential_data.get('expires_at')
                is_expired = is_token_expired(expires_at) if expires_at else False

                response = WordPressOAuthValidateResponse(
                    success=True,
                    is_valid=not is_expired,
                    message="Token is valid" if not is_expired else "Token is expired"
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))

        except Exception as e:
            logger.error(f"[WordPressOAuthHandler] Error in validate_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=WordPressOAuthValidateResponse(
                    success=False,
                    is_valid=False,
                    message="Internal error"
                ).model_dump()
            ))
