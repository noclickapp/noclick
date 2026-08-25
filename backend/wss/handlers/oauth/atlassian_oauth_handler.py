"""
Handler for Atlassian OAuth operations.
Manages OAuth 2.0 (3LO) flow for Jira/Confluence API access.
"""

import logging
from typing import Dict, Callable
from utils.database_pool import DatabasePoolMixin
from utils.encryption import get_encryption
from nodes.oauth.atlassian_oauth import (
    AtlassianSiteAccessError,
    exchange_code_for_tokens,
    refresh_access_token,
    is_token_expired,
)
from wss.schema import SocketIOHandler
from wss.sender import send_event, ResponseEvent
from wss.sender.responses import (
    AtlassianOAuthExchangeResponse,
    AtlassianOAuthRefreshResponse,
    AtlassianOAuthValidateResponse,
)
from wss.receiver.client_events import (
    AtlassianOAuthExchangeRequest,
    AtlassianOAuthRefreshRequest,
    AtlassianOAuthValidateRequest,
)

logger = logging.getLogger(__name__)


def _granted_scopes(scope_value) -> list[str]:
    if not scope_value:
        return []
    if isinstance(scope_value, str):
        return [scope for scope in scope_value.split() if scope]
    if isinstance(scope_value, list):
        return [str(scope) for scope in scope_value if scope]
    return []


class AtlassianOAuthHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for Atlassian OAuth WebSocket events"""

    def __init__(self, sio):
        super().__init__(sio)
        self.encryption = get_encryption()

    def get_events(self) -> Dict[str, Callable]:
        """Register Atlassian OAuth events"""
        return {
            "atlassian:oauth:exchange": self.exchange_oauth_code,
            "atlassian:oauth:refresh": self.refresh_oauth_token,
            "atlassian:oauth:validate": self.validate_oauth_token,
        }

    async def setup_user(self, sid: str) -> None:
        _ = sid

    async def exchange_oauth_code(self, sid: str, request: AtlassianOAuthExchangeRequest) -> None:
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
                    data=AtlassianOAuthExchangeResponse(
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
                    jira_site=request.jira_site,
                )
            except ValueError as e:
                logger.error(f"[AtlassianOAuthHandler] Token exchange failed: {e}")
                available_sites = None
                if isinstance(e, AtlassianSiteAccessError):
                    available_sites = [
                        {
                            "id": str(site.get("id") or ""),
                            "name": str(site.get("name") or ""),
                            "url": str(site.get("url") or ""),
                        }
                        for site in e.available_sites
                    ]
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=AtlassianOAuthExchangeResponse(
                        success=False,
                        message=str(e),
                        available_sites=available_sites,
                    ).model_dump()
                ))
                return

            # Prepare credential data
            credential_data = {
                'access_token': tokens.access_token,
                'refresh_token': tokens.refresh_token,
                'expires_at': tokens.expires_at,
                'scope': tokens.scope,
                'cloud_id': user_info.cloud_id,
                'site_name': user_info.site_name,
                'site_url': user_info.site_url,
                'email': user_info.email,
            }

            # Encrypt and store credential
            try:
                encrypted_data = self.encryption.encrypt_credential(credential_data)
            except Exception as e:
                logger.error(f"[AtlassianOAuthHandler] Encryption failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=AtlassianOAuthExchangeResponse(
                        success=False,
                        message="Failed to encrypt credential"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=AtlassianOAuthExchangeResponse(
                        success=False,
                        message="Database connection not available"
                    ).model_dump()
                ))
                return

            # Infer credential type from granted scopes: Confluence scopes are
            # distinct from Jira scopes (e.g. read:confluence-content.all).
            granted = _granted_scopes(tokens.scope)
            is_confluence = any("confluence" in s for s in granted)
            cred_type = "confluence_oauth" if is_confluence else "jira_oauth"
            credential_name = user_info.site_name or ("Confluence" if is_confluence else "Jira")

            async with pool.acquire() as conn:
                from repositories.credentials import create_credential_with_limit_check
                user_tier = session.get('user_data', {}).get('subscription_tier', 'free')
                row, error = await create_credential_with_limit_check(
                    conn, user_id, user_tier, cred_type,
                    credential_name, encrypted_data, {
                        'provider': 'atlassian',
                        'cloud_id': user_info.cloud_id,
                        'site_name': user_info.site_name,
                        'site_url': user_info.site_url,
                        'scopes': granted,
                    },
                )
                if error:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={}, error=error
                    ))
                    return

                product = "Confluence" if is_confluence else "Jira"
                response = AtlassianOAuthExchangeResponse(
                    success=True,
                    credential_id=str(row['id']),
                    credential_name=row['name'],
                    cloud_id=user_info.cloud_id,
                    site_name=user_info.site_name,
                    site_url=user_info.site_url,
                    message=f"{product} account connected successfully"
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))
                logger.info(f"[AtlassianOAuthHandler] Created {cred_type} credential {row['id']} for user {user_id} (site: {user_info.site_name})")

        except Exception as e:
            logger.error(f"[AtlassianOAuthHandler] Error in exchange_oauth_code: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=AtlassianOAuthExchangeResponse(
                    success=False,
                    message="Internal error"
                ).model_dump()
            ))

    async def refresh_oauth_token(self, sid: str, request: AtlassianOAuthRefreshRequest) -> None:
        """
        Refresh an expired OAuth token and update the stored credential.
        """
        try:
            # Get user session
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=AtlassianOAuthRefreshResponse(
                        success=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=AtlassianOAuthRefreshResponse(
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
                    provider="atlassian",
                    refresh=refresh_access_token,
                )
            except ValueError as e:
                logger.error(f"[AtlassianOAuthHandler] Token refresh failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=AtlassianOAuthRefreshResponse(
                        success=False,
                        message=str(e)
                    ).model_dump()
                ))
                return

            # The choke point's persist merges expires_at + last_refreshed_at
            # into metadata; the scopes sync is Atlassian-specific, so apply it
            # here (metadata-only — never touch the credential column).
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE credentials SET metadata = metadata || $2::jsonb WHERE id = $1",
                    request.credential_id,
                    {"scopes": _granted_scopes(credential_data.get("scope"))},
                )

            response = AtlassianOAuthRefreshResponse(
                success=True,
                expires_at=credential_data.get('expires_at'),
                message="Token refreshed successfully"
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=response.model_dump()
            ))
            logger.info(f"[AtlassianOAuthHandler] Refreshed token for credential {request.credential_id}")

        except Exception as e:
            logger.error(f"[AtlassianOAuthHandler] Error in refresh_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=AtlassianOAuthRefreshResponse(
                    success=False,
                    message="Internal error"
                ).model_dump()
            ))

    async def validate_oauth_token(self, sid: str, request: AtlassianOAuthValidateRequest) -> None:
        """
        Validate if a stored OAuth credential is still valid.
        """
        try:
            # Get user session
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=AtlassianOAuthValidateResponse(
                        valid=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=AtlassianOAuthValidateResponse(
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
                        data=AtlassianOAuthValidateResponse(
                            valid=False,
                            message="Credential not found or access denied"
                        ).model_dump()
                    ))
                    return

                # Decrypt credential
                try:
                    credential_data = self.encryption.decrypt_credential(row['credential'])
                except Exception as e:
                    logger.error(f"[AtlassianOAuthHandler] Decryption failed: {e}")
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=AtlassianOAuthValidateResponse(
                            valid=False,
                            message="Failed to decrypt credential"
                        ).model_dump()
                    ))
                    return

                expires_at = credential_data.get('expires_at')
                site_name = credential_data.get('site_name') or row['metadata'].get('site_name')
                cloud_id = credential_data.get('cloud_id') or row['metadata'].get('cloud_id')

                # Check if token is expired or expiring soon
                is_expired = is_token_expired(expires_at, buffer_minutes=0)
                expires_soon = is_token_expired(expires_at, buffer_minutes=5)

                response = AtlassianOAuthValidateResponse(
                    valid=not is_expired,
                    expires_soon=expires_soon and not is_expired,
                    cloud_id=cloud_id,
                    site_name=site_name,
                    message="Token is valid" if not is_expired else "Token has expired"
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))

        except Exception as e:
            logger.error(f"[AtlassianOAuthHandler] Error in validate_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=AtlassianOAuthValidateResponse(
                    valid=False,
                    message="Internal error"
                ).model_dump()
            ))
