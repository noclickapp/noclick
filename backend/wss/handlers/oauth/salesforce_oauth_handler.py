"""
Handler for Salesforce OAuth operations.
Manages OAuth 2.0 Web Server Flow for Salesforce API access.
"""

import logging
from typing import Dict, Callable
from utils.database_pool import DatabasePoolMixin
from utils.encryption import get_encryption
from nodes.oauth.salesforce_oauth import (
    exchange_code_for_tokens,
    refresh_access_token,
    is_token_expired,
)
from wss.schema import SocketIOHandler
from wss.sender import send_event, ResponseEvent
from wss.sender.responses import (
    SalesforceOAuthExchangeResponse,
    SalesforceOAuthRefreshResponse,
    SalesforceOAuthValidateResponse,
)
from wss.receiver.client_events import (
    SalesforceOAuthExchangeRequest,
    SalesforceOAuthRefreshRequest,
    SalesforceOAuthValidateRequest,
)

logger = logging.getLogger(__name__)


class SalesforceOAuthHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for Salesforce OAuth WebSocket events"""

    def __init__(self, sio):
        super().__init__(sio)
        self.encryption = get_encryption()

    def get_events(self) -> Dict[str, Callable]:
        """Register Salesforce OAuth events"""
        return {
            "salesforce:oauth:exchange": self.exchange_oauth_code,
            "salesforce:oauth:refresh": self.refresh_oauth_token,
            "salesforce:oauth:validate": self.validate_oauth_token,
        }

    async def setup_user(self, sid: str) -> None:
        _ = sid

    async def exchange_oauth_code(self, sid: str, request: SalesforceOAuthExchangeRequest) -> None:
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
                    data=SalesforceOAuthExchangeResponse(
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
                    is_sandbox=request.is_sandbox,
                    code_verifier=request.code_verifier,  # PKCE support
                )
            except ValueError as e:
                logger.error(f"[SalesforceOAuthHandler] Token exchange failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=SalesforceOAuthExchangeResponse(
                        success=False,
                        message=str(e)
                    ).model_dump()
                ))
                return

            # Prepare credential data
            credential_data = {
                'access_token': tokens.access_token,
                'refresh_token': tokens.refresh_token,
                'expires_at': tokens.expires_at,
                'instance_url': tokens.instance_url,
                'scope': tokens.scope,
                'is_sandbox': request.is_sandbox,
                'user_id': user_info.user_id,
                'organization_id': user_info.organization_id,
                'username': user_info.username,
                'email': user_info.email,
            }

            # Encrypt and store credential
            try:
                encrypted_data = self.encryption.encrypt_credential(credential_data)
            except Exception as e:
                logger.error(f"[SalesforceOAuthHandler] Encryption failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=SalesforceOAuthExchangeResponse(
                        success=False,
                        message="Failed to encrypt credential"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=SalesforceOAuthExchangeResponse(
                        success=False,
                        message="Database connection not available"
                    ).model_dump()
                ))
                return

            # Use the username or email as the credential name
            credential_name = user_info.username or user_info.email or f"Salesforce ({user_info.organization_id})"

            async with pool.acquire() as conn:
                from repositories.credentials import create_credential_with_limit_check
                user_tier = session.get('user_data', {}).get('subscription_tier', 'free')
                row, error = await create_credential_with_limit_check(
                    conn, user_id, user_tier, 'salesforce_oauth',
                    credential_name, encrypted_data, {
                        'provider': 'salesforce',
                        'username': user_info.username,
                        'email': user_info.email,
                        'organization_id': user_info.organization_id,
                        'instance_url': tokens.instance_url,
                        'is_sandbox': request.is_sandbox,
                        'scopes': request.scopes,
                    },
                )
                if error:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={}, error=error
                    ))
                    return

                response = SalesforceOAuthExchangeResponse(
                    success=True,
                    credential_id=str(row['id']),
                    credential_name=row['name'],
                    username=user_info.username,
                    email=user_info.email,
                    organization_id=user_info.organization_id,
                    instance_url=tokens.instance_url,
                    message="Salesforce account connected successfully"
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))
                logger.info(f"[SalesforceOAuthHandler] Created Salesforce credential {row['id']} for user {user_id} ({user_info.username})")

        except Exception as e:
            logger.error(f"[SalesforceOAuthHandler] Error in exchange_oauth_code: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=SalesforceOAuthExchangeResponse(
                    success=False,
                    message="Internal error"
                ).model_dump()
            ))

    async def refresh_oauth_token(self, sid: str, request: SalesforceOAuthRefreshRequest) -> None:
        """
        Refresh an expired OAuth token and update the stored credential.
        Salesforce tokens typically expire after 2 hours.
        """
        try:
            # Get user session
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=SalesforceOAuthRefreshResponse(
                        success=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=SalesforceOAuthRefreshResponse(
                        success=False,
                        message="Database connection not available"
                    ).model_dump()
                ))
                return

            # Refresh-if-expired through the shared freshen choke point
            # (lock, in-lock re-read, CAS persist, audit row) — never a
            # bespoke unlocked UPDATE that races the execute-path refresh.
            from wss.handlers.oauth.manual_refresh import manual_refresh_credential

            def _make_refresh(credential):
                # Salesforce's refresher needs fields from the loaded credential.
                instance_url = credential.get('instance_url')
                is_sandbox = credential.get('is_sandbox', False)

                async def _refresh(refresh_token: str):
                    return await refresh_access_token(
                        refresh_token=refresh_token,
                        instance_url=instance_url,
                        is_sandbox=is_sandbox,
                    )

                return _refresh

            try:
                credential_data = await manual_refresh_credential(
                    pool,
                    user_id=user_id,
                    credential_id=request.credential_id,
                    provider="salesforce",
                    make_refresh=_make_refresh,
                )
            except ValueError as e:
                logger.error(f"[SalesforceOAuthHandler] Token refresh failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=SalesforceOAuthRefreshResponse(
                        success=False,
                        message=str(e)
                    ).model_dump()
                ))
                return

            response = SalesforceOAuthRefreshResponse(
                success=True,
                expires_at=credential_data.get('expires_at'),
                message="Token refreshed successfully"
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=response.model_dump()
            ))
            logger.info(f"[SalesforceOAuthHandler] Refreshed token for credential {request.credential_id}")

        except Exception as e:
            logger.error(f"[SalesforceOAuthHandler] Error in refresh_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=SalesforceOAuthRefreshResponse(
                    success=False,
                    message="Internal error"
                ).model_dump()
            ))

    async def validate_oauth_token(self, sid: str, request: SalesforceOAuthValidateRequest) -> None:
        """
        Validate if a stored OAuth credential is still valid.
        Checks token expiry time.
        """
        try:
            # Get user session
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=SalesforceOAuthValidateResponse(
                        valid=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=SalesforceOAuthValidateResponse(
                        valid=False,
                        message="Database connection not available"
                    ).model_dump()
                ))
                return

            async with pool.acquire() as conn:
                # Fetch credential (verify ownership)
                row = await conn.fetchrow("""
                    SELECT id, credential, metadata
                    FROM credentials
                    WHERE id = $1 AND owner_id = $2
                """, request.credential_id, user_id)

                if not row:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=SalesforceOAuthValidateResponse(
                            valid=False,
                            message="Credential not found or access denied"
                        ).model_dump()
                    ))
                    return

                # Decrypt credential
                try:
                    credential_data = self.encryption.decrypt_credential(row['credential'])
                except Exception as e:
                    logger.error(f"[SalesforceOAuthHandler] Decryption failed: {e}")
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=SalesforceOAuthValidateResponse(
                            valid=False,
                            message="Failed to decrypt credential"
                        ).model_dump()
                    ))
                    return

                expires_at = credential_data.get('expires_at')
                username = credential_data.get('username') or row['metadata'].get('username')
                email = credential_data.get('email') or row['metadata'].get('email')
                organization_id = credential_data.get('organization_id') or row['metadata'].get('organization_id')
                instance_url = credential_data.get('instance_url') or row['metadata'].get('instance_url')

                # Check if token is expired or expiring soon
                is_expired = is_token_expired(expires_at, buffer_minutes=0)
                expires_soon = is_token_expired(expires_at, buffer_minutes=5)

                response = SalesforceOAuthValidateResponse(
                    valid=not is_expired,
                    expires_soon=expires_soon and not is_expired,
                    username=username,
                    email=email,
                    organization_id=organization_id,
                    instance_url=instance_url,
                    message="Token is valid" if not is_expired else "Token has expired"
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))

        except Exception as e:
            logger.error(f"[SalesforceOAuthHandler] Error in validate_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=SalesforceOAuthValidateResponse(
                    valid=False,
                    message="Internal error"
                ).model_dump()
            ))
