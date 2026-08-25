"""
Handler for Box OAuth operations.
Manages the OAuth 2.0 Authorization Code flow for Box API access.
"""

import logging
from typing import Dict, Callable
from utils.database_pool import DatabasePoolMixin
from utils.encryption import get_encryption
from nodes.oauth.box_oauth import (
    exchange_code_for_tokens,
    refresh_access_token,
    is_token_expired,
)
from wss.schema import SocketIOHandler
from wss.sender import send_event, ResponseEvent
from wss.sender.responses import (
    BoxOAuthExchangeResponse,
    BoxOAuthRefreshResponse,
    BoxOAuthValidateResponse,
)
from wss.receiver.client_events import (
    BoxOAuthExchangeRequest,
    BoxOAuthRefreshRequest,
    BoxOAuthValidateRequest,
)

logger = logging.getLogger(__name__)


class BoxOAuthHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for Box OAuth WebSocket events"""

    def __init__(self, sio):
        super().__init__(sio)
        self.encryption = get_encryption()

    def get_events(self) -> Dict[str, Callable]:
        """Register Box OAuth events"""
        return {
            "box:oauth:exchange": self.exchange_oauth_code,
            "box:oauth:refresh": self.refresh_oauth_token,
            "box:oauth:validate": self.validate_oauth_token,
        }

    async def setup_user(self, sid: str) -> None:
        _ = sid

    async def exchange_oauth_code(self, sid: str, request: BoxOAuthExchangeRequest) -> None:
        """
        Exchange OAuth authorization code for tokens and store as credential.
        Called from the OAuth callback page after user grants permission.
        """
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=BoxOAuthExchangeResponse(
                        success=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            try:
                tokens, user_info = await exchange_code_for_tokens(
                    code=request.code,
                    redirect_uri=request.redirect_uri,
                )
            except ValueError as e:
                logger.error(f"[BoxOAuthHandler] Token exchange failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=BoxOAuthExchangeResponse(
                        success=False,
                        message=str(e)
                    ).model_dump()
                ))
                return

            credential_data = {
                'access_token': tokens.access_token,
                'refresh_token': tokens.refresh_token,
                'expires_at': tokens.expires_at,
                'name': user_info.name,
                'email': user_info.email,
            }

            try:
                encrypted_data = self.encryption.encrypt_credential(credential_data)
            except Exception as e:
                logger.error(f"[BoxOAuthHandler] Encryption failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=BoxOAuthExchangeResponse(
                        success=False,
                        message="Failed to encrypt credential"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=BoxOAuthExchangeResponse(
                        success=False,
                        message="Database connection not available"
                    ).model_dump()
                ))
                return

            credential_name = user_info.name or user_info.email or f"Box ({user_info.id})"

            async with pool.acquire() as conn:
                from repositories.credentials import create_credential_with_limit_check
                user_tier = session.get('user_data', {}).get('subscription_tier', 'free')
                row, error = await create_credential_with_limit_check(
                    conn, user_id, user_tier, 'box_oauth',
                    credential_name, encrypted_data, {
                        'provider': 'box',
                        'name': user_info.name,
                        'email': user_info.email,
                        'box_user_id': user_info.id,
                        'scopes': request.scopes,
                    },
                )
                if error:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={}, error=error
                    ))
                    return

                response = BoxOAuthExchangeResponse(
                    success=True,
                    credential_id=str(row['id']),
                    credential_name=row['name'],
                    name=user_info.name,
                    email=user_info.email,
                    message="Box account connected successfully"
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))
                logger.info(f"[BoxOAuthHandler] Created Box credential {row['id']} for user {user_id} ({user_info.name})")

        except Exception as e:
            logger.error(f"[BoxOAuthHandler] Error in exchange_oauth_code: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=BoxOAuthExchangeResponse(
                    success=False,
                    message="Internal error"
                ).model_dump()
            ))

    async def refresh_oauth_token(self, sid: str, request: BoxOAuthRefreshRequest) -> None:
        """
        Refresh an expired OAuth token and update the stored credential.
        Box access tokens expire after ~60 minutes; refresh tokens rotate.
        """
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=BoxOAuthRefreshResponse(
                        success=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=BoxOAuthRefreshResponse(
                        success=False,
                        message="Database connection not available"
                    ).model_dump()
                ))
                return

            # Refresh-if-expired through the shared freshen choke point
            # (lock, in-lock re-read, CAS persist, audit row) — never a
            # bespoke unlocked UPDATE that races the execute-path refresh. This
            # matters doubly for Box's single-use rotating refresh tokens.
            from wss.handlers.oauth.manual_refresh import manual_refresh_credential

            try:
                credential_data = await manual_refresh_credential(
                    pool,
                    user_id=user_id,
                    credential_id=request.credential_id,
                    provider="box",
                    refresh=refresh_access_token,
                )
            except ValueError as e:
                logger.error(f"[BoxOAuthHandler] Token refresh failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=BoxOAuthRefreshResponse(
                        success=False,
                        message=str(e)
                    ).model_dump()
                ))
                return

            response = BoxOAuthRefreshResponse(
                success=True,
                expires_at=credential_data.get('expires_at'),
                message="Token refreshed successfully"
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=response.model_dump()
            ))
            logger.info(f"[BoxOAuthHandler] Refreshed token for credential {request.credential_id}")

        except Exception as e:
            logger.error(f"[BoxOAuthHandler] Error in refresh_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=BoxOAuthRefreshResponse(
                    success=False,
                    message="Internal error"
                ).model_dump()
            ))

    async def validate_oauth_token(self, sid: str, request: BoxOAuthValidateRequest) -> None:
        """
        Validate if a stored OAuth credential is still valid.
        Box access tokens expire after ~60 minutes.
        """
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=BoxOAuthValidateResponse(
                        valid=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=BoxOAuthValidateResponse(
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
                        data=BoxOAuthValidateResponse(
                            valid=False,
                            message="Credential not found or access denied"
                        ).model_dump()
                    ))
                    return

                try:
                    credential_data = self.encryption.decrypt_credential(row['credential'])
                except Exception as e:
                    logger.error(f"[BoxOAuthHandler] Decryption failed: {e}")
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=BoxOAuthValidateResponse(
                            valid=False,
                            message="Failed to decrypt credential"
                        ).model_dump()
                    ))
                    return

                expires_at = credential_data.get('expires_at')
                name = credential_data.get('name') or row['metadata'].get('name')
                email = credential_data.get('email') or row['metadata'].get('email')

                # Box access tokens are short-lived (~60m) but auto-refreshed on
                # use via the rotating refresh token, so a credential with no
                # expiry stored is treated as valid.
                if not expires_at:
                    response = BoxOAuthValidateResponse(
                        valid=True,
                        expires_soon=False,
                        name=name,
                        email=email,
                        message="Token is valid"
                    )
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=response.model_dump()
                    ))
                    return

                is_expired = is_token_expired(expires_at, buffer_minutes=0)
                expires_soon = is_token_expired(expires_at, buffer_minutes=5)

                response = BoxOAuthValidateResponse(
                    valid=not is_expired,
                    expires_soon=expires_soon and not is_expired,
                    name=name,
                    email=email,
                    message="Token is valid" if not is_expired else "Token has expired"
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))

        except Exception as e:
            logger.error(f"[BoxOAuthHandler] Error in validate_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=BoxOAuthValidateResponse(
                    valid=False,
                    message="Internal error"
                ).model_dump()
            ))
