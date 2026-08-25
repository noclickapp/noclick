"""
Handler for QuickBooks (Intuit) OAuth operations.
Manages the OAuth 2.0 authorization_code flow for the QuickBooks Online API.

Intuit returns a ``realmId`` (company ID) on the OAuth callback that scopes
every subsequent API call; it is persisted alongside the rotating tokens.
"""

import logging
import os
from typing import Dict, Callable
from utils.database_pool import DatabasePoolMixin
from utils.encryption import get_encryption
from nodes.oauth.quickbooks_oauth import (
    exchange_code_for_tokens,
    refresh_access_token,
    is_token_expired,
)
from wss.schema import SocketIOHandler
from wss.sender import send_event, ResponseEvent
from wss.sender.responses import (
    QuickBooksOAuthExchangeResponse,
    QuickBooksOAuthRefreshResponse,
    QuickBooksOAuthValidateResponse,
)
from wss.receiver.client_events import (
    QuickBooksOAuthExchangeRequest,
    QuickBooksOAuthRefreshRequest,
    QuickBooksOAuthValidateRequest,
)

logger = logging.getLogger(__name__)


class QuickBooksOAuthHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for QuickBooks OAuth WebSocket events"""

    def __init__(self, sio):
        super().__init__(sio)
        self.encryption = get_encryption()

    def get_events(self) -> Dict[str, Callable]:
        """Register QuickBooks OAuth events"""
        return {
            "quickbooks:oauth:exchange": self.exchange_oauth_code,
            "quickbooks:oauth:refresh": self.refresh_oauth_token,
            "quickbooks:oauth:validate": self.validate_oauth_token,
        }

    async def setup_user(self, sid: str) -> None:
        # Pool is acquired lazily via get_pool(); no per-user setup needed since
        # the native asyncpg pool refactoring.
        _ = sid

    async def exchange_oauth_code(self, sid: str, request: QuickBooksOAuthExchangeRequest) -> None:
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
                    data=QuickBooksOAuthExchangeResponse(
                        success=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            try:
                configured_redirect_uri = os.environ.get("QUICKBOOKS_REDIRECT_URI") or os.environ.get("INTUIT_REDIRECT_URI")
                if configured_redirect_uri and request.redirect_uri != configured_redirect_uri:
                    raise ValueError("Invalid redirect URI")

                tokens, user_info = await exchange_code_for_tokens(
                    code=request.code,
                    redirect_uri=request.redirect_uri,
                    client_id=request.client_id,
                    client_secret=request.client_secret,
                    realm_id=request.realm_id,
                )
            except ValueError as e:
                logger.error(f"[QuickBooksOAuthHandler] Token exchange failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=QuickBooksOAuthExchangeResponse(
                        success=False,
                        message=str(e)
                    ).model_dump()
                ))
                return

            credential_data = {
                'access_token': tokens.access_token,
                'refresh_token': tokens.refresh_token,
                'expires_at': tokens.expires_at,
                'realm_id': request.realm_id,
                'is_sandbox': request.is_sandbox,
                'name': user_info.name,
                'email': user_info.email,
            }
            if request.client_id and request.client_secret:
                credential_data['client_id'] = request.client_id
                credential_data['client_secret'] = request.client_secret

            try:
                encrypted_data = self.encryption.encrypt_credential(credential_data)
            except Exception as e:
                logger.error(f"[QuickBooksOAuthHandler] Encryption failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=QuickBooksOAuthExchangeResponse(
                        success=False,
                        message="Failed to encrypt credential"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=QuickBooksOAuthExchangeResponse(
                        success=False,
                        message="Database connection not available"
                    ).model_dump()
                ))
                return

            credential_name = user_info.name or user_info.email or f"QuickBooks ({request.realm_id})"

            async with pool.acquire() as conn:
                from repositories.credentials import create_credential_with_limit_check
                user_tier = session.get('user_data', {}).get('subscription_tier', 'free')
                row, error = await create_credential_with_limit_check(
                    conn, user_id, user_tier, 'quickbooks_oauth',
                    credential_name, encrypted_data, {
                        'provider': 'quickbooks',
                        'name': user_info.name,
                        'email': user_info.email,
                        'quickbooks_user_id': user_info.id,
                        'realm_id': request.realm_id,
                        'is_sandbox': request.is_sandbox,
                        'scopes': request.scopes,
                    },
                )
                if error:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={}, error=error
                    ))
                    return

                response = QuickBooksOAuthExchangeResponse(
                    success=True,
                    credential_id=str(row['id']),
                    credential_name=row['name'],
                    name=user_info.name,
                    email=user_info.email,
                    realm_id=request.realm_id,
                    message="QuickBooks account connected successfully"
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))
                logger.info(f"[QuickBooksOAuthHandler] Created QuickBooks credential {row['id']} for user {user_id} ({user_info.name})")

        except Exception as e:
            logger.error(f"[QuickBooksOAuthHandler] Error in exchange_oauth_code: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=QuickBooksOAuthExchangeResponse(
                    success=False,
                    message="Internal error"
                ).model_dump()
            ))

    async def refresh_oauth_token(self, sid: str, request: QuickBooksOAuthRefreshRequest) -> None:
        """
        Refresh an expired OAuth token and update the stored credential.
        QuickBooks access tokens expire after 1 hour; refresh tokens rotate.
        """
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=QuickBooksOAuthRefreshResponse(
                        success=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=QuickBooksOAuthRefreshResponse(
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
                credential_data = await manual_refresh_credential(
                    pool,
                    user_id=user_id,
                    credential_id=request.credential_id,
                    provider="quickbooks",
                    make_refresh=lambda credential: (
                        lambda refresh_token: refresh_access_token(
                            refresh_token,
                            client_id=credential.get("client_id"),
                            client_secret=credential.get("client_secret"),
                        )
                    ),
                )
            except ValueError as e:
                logger.error(f"[QuickBooksOAuthHandler] Token refresh failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=QuickBooksOAuthRefreshResponse(
                        success=False,
                        message=str(e)
                    ).model_dump()
                ))
                return

            response = QuickBooksOAuthRefreshResponse(
                success=True,
                expires_at=credential_data.get('expires_at'),
                message="Token refreshed successfully"
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=response.model_dump()
            ))
            logger.info(f"[QuickBooksOAuthHandler] Refreshed token for credential {request.credential_id}")

        except Exception as e:
            logger.error(f"[QuickBooksOAuthHandler] Error in refresh_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=QuickBooksOAuthRefreshResponse(
                    success=False,
                    message="Internal error"
                ).model_dump()
            ))

    async def validate_oauth_token(self, sid: str, request: QuickBooksOAuthValidateRequest) -> None:
        """
        Validate if a stored OAuth credential is still valid.
        QuickBooks access tokens expire after 1 hour.
        """
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=QuickBooksOAuthValidateResponse(
                        valid=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=QuickBooksOAuthValidateResponse(
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
                        data=QuickBooksOAuthValidateResponse(
                            valid=False,
                            message="Credential not found or access denied"
                        ).model_dump()
                    ))
                    return

                try:
                    credential_data = self.encryption.decrypt_credential(row['credential'])
                except Exception as e:
                    logger.error(f"[QuickBooksOAuthHandler] Decryption failed: {e}")
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=QuickBooksOAuthValidateResponse(
                            valid=False,
                            message="Failed to decrypt credential"
                        ).model_dump()
                    ))
                    return

                expires_at = credential_data.get('expires_at')
                name = credential_data.get('name') or row['metadata'].get('name')
                email = credential_data.get('email') or row['metadata'].get('email')

                # Intuit access tokens are short-lived (1h) but auto-refreshed on
                # use via the rotating refresh token, so a credential with no
                # expiry stored is treated as valid.
                if not expires_at:
                    response = QuickBooksOAuthValidateResponse(
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

                response = QuickBooksOAuthValidateResponse(
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
            logger.error(f"[QuickBooksOAuthHandler] Error in validate_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=QuickBooksOAuthValidateResponse(
                    valid=False,
                    message="Internal error"
                ).model_dump()
            ))
