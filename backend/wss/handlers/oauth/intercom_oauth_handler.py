"""
Handler for Intercom OAuth operations.
Manages the OAuth 2.0 authorization_code flow for Intercom API access.

Intercom access tokens are long-lived (no expiry) and there is no refresh token,
so the refresh path is a no-op error and validation always treats a stored token
as valid (the credential carries no expires_at to check).
"""

import logging
from typing import Dict, Callable
from utils.database_pool import DatabasePoolMixin
from utils.encryption import get_encryption
from nodes.oauth.intercom_oauth import (
    exchange_code_for_tokens,
    refresh_access_token,
    is_token_expired,
)
from wss.schema import SocketIOHandler
from wss.sender import send_event, ResponseEvent
from wss.sender.responses import (
    IntercomOAuthExchangeResponse,
    IntercomOAuthRefreshResponse,
    IntercomOAuthValidateResponse,
)
from wss.receiver.client_events import (
    IntercomOAuthExchangeRequest,
    IntercomOAuthRefreshRequest,
    IntercomOAuthValidateRequest,
)

logger = logging.getLogger(__name__)


class IntercomOAuthHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for Intercom OAuth WebSocket events"""

    def __init__(self, sio):
        super().__init__(sio)
        self.encryption = get_encryption()

    def get_events(self) -> Dict[str, Callable]:
        """Register Intercom OAuth events"""
        return {
            "intercom:oauth:exchange": self.exchange_oauth_code,
            "intercom:oauth:refresh": self.refresh_oauth_token,
            "intercom:oauth:validate": self.validate_oauth_token,
        }

    async def setup_user(self, sid: str) -> None:
        _ = sid

    async def exchange_oauth_code(self, sid: str, request: IntercomOAuthExchangeRequest) -> None:
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
                    data=IntercomOAuthExchangeResponse(
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
                logger.error(f"[IntercomOAuthHandler] Token exchange failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=IntercomOAuthExchangeResponse(
                        success=False,
                        message=str(e)
                    ).model_dump()
                ))
                return

            credential_data = {
                'access_token': tokens.access_token,
                'region': request.region or 'us',
                'name': user_info.name,
                'email': user_info.email,
            }

            try:
                encrypted_data = self.encryption.encrypt_credential(credential_data)
            except Exception as e:
                logger.error(f"[IntercomOAuthHandler] Encryption failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=IntercomOAuthExchangeResponse(
                        success=False,
                        message="Failed to encrypt credential"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=IntercomOAuthExchangeResponse(
                        success=False,
                        message="Database connection not available"
                    ).model_dump()
                ))
                return

            credential_name = user_info.name or user_info.email or f"Intercom ({user_info.id})"

            async with pool.acquire() as conn:
                from repositories.credentials import create_credential_with_limit_check
                user_tier = session.get('user_data', {}).get('subscription_tier', 'free')
                row, error = await create_credential_with_limit_check(
                    conn, user_id, user_tier, 'intercom_oauth',
                    credential_name, encrypted_data, {
                        'provider': 'intercom',
                        'name': user_info.name,
                        'email': user_info.email,
                        'intercom_admin_id': user_info.id,
                        'region': request.region or 'us',
                        'scopes': request.scopes,
                    },
                )
                if error:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={}, error=error
                    ))
                    return

                response = IntercomOAuthExchangeResponse(
                    success=True,
                    credential_id=str(row['id']),
                    credential_name=row['name'],
                    name=user_info.name,
                    email=user_info.email,
                    message="Intercom account connected successfully"
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))
                logger.info(f"[IntercomOAuthHandler] Created Intercom credential {row['id']} for user {user_id} ({user_info.name})")

        except Exception as e:
            logger.error(f"[IntercomOAuthHandler] Error in exchange_oauth_code: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=IntercomOAuthExchangeResponse(
                    success=False,
                    message="Internal error"
                ).model_dump()
            ))

    async def refresh_oauth_token(self, sid: str, request: IntercomOAuthRefreshRequest) -> None:
        """
        Intercom access tokens are long-lived and have no refresh token, so there
        is nothing to refresh. Report success with no expiry so callers treat the
        credential as permanently valid.
        """
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=IntercomOAuthRefreshResponse(
                        success=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            # is_token_expired is always False for Intercom; refresh_access_token
            # would raise. Imported to keep the provider surface honest, referenced
            # here so the no-op contract is explicit rather than silently dropped.
            _ = (refresh_access_token, is_token_expired)

            response = IntercomOAuthRefreshResponse(
                success=True,
                expires_at=None,
                message="Intercom tokens are long-lived and never need refreshing"
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=response.model_dump()
            ))

        except Exception as e:
            logger.error(f"[IntercomOAuthHandler] Error in refresh_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=IntercomOAuthRefreshResponse(
                    success=False,
                    message="Internal error"
                ).model_dump()
            ))

    async def validate_oauth_token(self, sid: str, request: IntercomOAuthValidateRequest) -> None:
        """
        Validate a stored Intercom OAuth credential. Intercom tokens never expire,
        so a present credential is always valid (we don't store an expires_at to
        check against).
        """
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=IntercomOAuthValidateResponse(
                        valid=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=IntercomOAuthValidateResponse(
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
                        data=IntercomOAuthValidateResponse(
                            valid=False,
                            message="Credential not found or access denied"
                        ).model_dump()
                    ))
                    return

                try:
                    credential_data = self.encryption.decrypt_credential(row['credential'])
                except Exception as e:
                    logger.error(f"[IntercomOAuthHandler] Decryption failed: {e}")
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=IntercomOAuthValidateResponse(
                            valid=False,
                            message="Failed to decrypt credential"
                        ).model_dump()
                    ))
                    return

                name = credential_data.get('name') or row['metadata'].get('name')
                email = credential_data.get('email') or row['metadata'].get('email')

                # Intercom tokens never expire — a stored credential is valid.
                response = IntercomOAuthValidateResponse(
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

        except Exception as e:
            logger.error(f"[IntercomOAuthHandler] Error in validate_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=IntercomOAuthValidateResponse(
                    valid=False,
                    message="Internal error"
                ).model_dump()
            ))
