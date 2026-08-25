"""
Handler for Microsoft OAuth operations.
Manages OAuth token exchange, refresh, and validation for Microsoft Graph integrations (Outlook, etc.).
"""

import logging
import re
from typing import Dict, Callable
from utils.database_pool import DatabasePoolMixin
from utils.encryption import get_encryption
from nodes.oauth.microsoft_oauth import (
    exchange_code_for_tokens,
    refresh_access_token,
    is_token_expired,
)
from wss.schema import SocketIOHandler
from wss.sender import send_event, ResponseEvent
from wss.sender.responses import (
    MicrosoftOAuthExchangeResponse,
    MicrosoftOAuthRefreshResponse,
    MicrosoftOAuthValidateResponse,
    CredentialInfo,
)
from wss.receiver.client_events import (
    MicrosoftOAuthExchangeRequest,
    MicrosoftOAuthRefreshRequest,
    MicrosoftOAuthValidateRequest,
)

logger = logging.getLogger(__name__)


class MicrosoftOAuthHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for Microsoft OAuth WebSocket events"""

    def __init__(self, sio):
        super().__init__(sio)
        self.encryption = get_encryption()

    def get_events(self) -> Dict[str, Callable]:
        """Register Microsoft OAuth events"""
        return {
            "microsoft:oauth:exchange": self.exchange_oauth_code,
            "microsoft:oauth:refresh": self.refresh_oauth_token,
            "microsoft:oauth:validate": self.validate_oauth_token,
        }

    async def setup_user(self, sid: str) -> None:
        _ = sid

    async def exchange_oauth_code(self, sid: str, request: MicrosoftOAuthExchangeRequest) -> None:
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
                    data=MicrosoftOAuthExchangeResponse(
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
                logger.error(f"[MicrosoftOAuthHandler] Token exchange failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=MicrosoftOAuthExchangeResponse(
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
                'scope': tokens.scope,
                'email': user_info.email,
            }

            # Encrypt and store credential
            try:
                encrypted_data = self.encryption.encrypt_credential(credential_data)
            except Exception as e:
                logger.error(f"[MicrosoftOAuthHandler] Encryption failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=MicrosoftOAuthExchangeResponse(
                        success=False,
                        message="Failed to encrypt credential"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=MicrosoftOAuthExchangeResponse(
                        success=False,
                        message="Database connection not available"
                    ).model_dump()
                ))
                return

            # Determine credential type from credential_name (e.g., "OneDriveOAuth", "ExcelOAuth")
            # Falls back to scope-based detection for backward compatibility
            credential_type = self._get_credential_type_from_name(request.credential_name, request.scopes)

            # Use the credential name from the request
            credential_name = request.credential_name

            async with pool.acquire() as conn:
                from repositories.credentials import create_credential_with_limit_check
                user_tier = session.get('user_data', {}).get('subscription_tier', 'free')
                row, error = await create_credential_with_limit_check(
                    conn, user_id, user_tier, credential_type,
                    credential_name, encrypted_data, {
                        'provider': 'microsoft',
                        'email': user_info.email,
                        'scopes': request.scopes,
                    },
                )
                if error:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={}, error=error
                    ))
                    return

                response = MicrosoftOAuthExchangeResponse(
                    success=True,
                    credential_id=str(row['id']),
                    credential_name=row['name'],
                    email=user_info.email,
                    message="Microsoft account connected successfully"
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))
                logger.info(f"[MicrosoftOAuthHandler] Created Microsoft credential {row['id']} for user {user_id} ({user_info.email})")

        except Exception as e:
            logger.error(f"[MicrosoftOAuthHandler] Error in exchange_oauth_code: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=MicrosoftOAuthExchangeResponse(
                    success=False,
                    message="Internal error"
                ).model_dump()
            ))

    async def refresh_oauth_token(self, sid: str, request: MicrosoftOAuthRefreshRequest) -> None:
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
                    data=MicrosoftOAuthRefreshResponse(
                        success=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=MicrosoftOAuthRefreshResponse(
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
                    provider="microsoft",
                    refresh=refresh_access_token,
                )
            except ValueError as e:
                logger.error(f"[MicrosoftOAuthHandler] Token refresh failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=MicrosoftOAuthRefreshResponse(
                        success=False,
                        message=str(e)
                    ).model_dump()
                ))
                return

            response = MicrosoftOAuthRefreshResponse(
                success=True,
                expires_at=credential_data.get('expires_at'),
                message="Token refreshed successfully"
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=response.model_dump()
            ))
            logger.info(f"[MicrosoftOAuthHandler] Refreshed token for credential {request.credential_id}")

        except Exception as e:
            logger.error(f"[MicrosoftOAuthHandler] Error in refresh_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=MicrosoftOAuthRefreshResponse(
                    success=False,
                    message="Internal error"
                ).model_dump()
            ))

    async def validate_oauth_token(self, sid: str, request: MicrosoftOAuthValidateRequest) -> None:
        """
        Validate if a stored OAuth credential is still valid.
        Used during config validation to show warning badge in UI.
        """
        try:
            # Get user session
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=MicrosoftOAuthValidateResponse(
                        valid=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=MicrosoftOAuthValidateResponse(
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
                        data=MicrosoftOAuthValidateResponse(
                            valid=False,
                            message="Credential not found or access denied"
                        ).model_dump()
                    ))
                    return

                # Decrypt credential
                try:
                    credential_data = self.encryption.decrypt_credential(row['credential'])
                except Exception as e:
                    logger.error(f"[MicrosoftOAuthHandler] Decryption failed: {e}")
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=MicrosoftOAuthValidateResponse(
                            valid=False,
                            message="Failed to decrypt credential"
                        ).model_dump()
                    ))
                    return

                expires_at = credential_data.get('expires_at')
                email = credential_data.get('email') or row['metadata'].get('email')

                # Check if token is expired or expiring soon
                if not expires_at:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=MicrosoftOAuthValidateResponse(
                            valid=False,
                            email=email,
                            message="No expiry information available"
                        ).model_dump()
                    ))
                    return

                is_expired = is_token_expired(expires_at, buffer_minutes=0)
                expires_soon = is_token_expired(expires_at, buffer_minutes=5)

                response = MicrosoftOAuthValidateResponse(
                    valid=not is_expired,
                    expires_soon=expires_soon and not is_expired,
                    email=email,
                    message="Token is valid" if not is_expired else "Token has expired"
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))

        except Exception as e:
            logger.error(f"[MicrosoftOAuthHandler] Error in validate_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=MicrosoftOAuthValidateResponse(
                    valid=False,
                    message="Internal error"
                ).model_dump()
            ))

    def _get_credential_type_from_name(self, credential_name: str, scopes: list[str]) -> str:
        """
        Determine the credential type from the credential name provided by the frontend.
        The credential_name comes from the schema title (e.g., "OneDriveOAuth", "ExcelOAuth").
        Falls back to scope-based detection for backward compatibility.

        Args:
            credential_name: Name from frontend (e.g., "OneDriveOAuth - 2/3/2026", "ExcelOAuth - 2/3/2026")
            scopes: OAuth scopes for fallback detection

        Returns:
            Database credential type (e.g., 'microsoft_onedrive_oauth', 'microsoft_excel_oauth')
        """
        # Collapse separators so a humanized label ("One Drive OAuth",
        # "One Lake OAuth") matches the same keyword as the schema title
        # ("OneDriveOAuthCredential"). Word/Excel/OneDrive request identical
        # scopes, so the NAME is the only reliable discriminator — a missed
        # match here silently misroutes them to each other's type.
        name_key = re.sub(r'[^a-z0-9]', '', credential_name.lower())

        # Map credential names to types. onelake before onedrive: 'onelake'
        # must not be shadowed, and neither contains the other.
        if 'onelake' in name_key:
            return 'microsoft_onelake_oauth'
        elif 'onedrive' in name_key:
            return 'microsoft_onedrive_oauth'
        elif 'excel' in name_key:
            return 'microsoft_excel_oauth'
        elif 'word' in name_key:
            return 'microsoft_word_oauth'
        elif 'outlook' in name_key or 'calendar' in name_key:
            # Calendar folded into the Outlook node — both map to the Outlook credential.
            return 'microsoft_outlook_oauth'
        elif 'teams' in name_key:
            return 'microsoft_teams_oauth'
        elif 'sharepoint' in name_key:
            return 'microsoft_sharepoint_oauth'
        elif 'todo' in name_key:
            return 'microsoft_todo_oauth'

        # Fallback to scope-based detection for backward compatibility
        return self._get_credential_type_from_scopes(scopes)

    def _get_credential_type_from_scopes(self, scopes: list[str]) -> str:
        """
        Determine the credential type based on requested OAuth scopes.
        Maps scopes to specific credential types for different Microsoft services.
        """
        scope_string = ' '.join(scopes).lower()

        # Check for Excel/Workbook scopes
        if 'files.readwrite' in scope_string or 'workbook' in scope_string:
            return 'microsoft_excel_oauth'

        # Check for OneDrive scopes
        if 'onedrive' in scope_string or ('files.read' in scope_string and 'files.readwrite' not in scope_string):
            return 'microsoft_onedrive_oauth'

        # Check for Outlook/Mail scopes. The Outlook node owns Mail AND Calendar/Contacts
        # (the standalone calendar node was folded into it), so any credential carrying a
        # Mail scope is an Outlook credential — checked before calendar to avoid misrouting
        # the merged node's calendar scopes to the orphaned microsoft_calendar_oauth type.
        if 'mail' in scope_string:
            return 'microsoft_outlook_oauth'

        # Calendar-only scopes also belong to the Outlook node now.
        if 'calendars' in scope_string or 'calendar' in scope_string:
            return 'microsoft_outlook_oauth'

        # Check for Teams scopes
        if 'team' in scope_string or 'channel' in scope_string:
            return 'microsoft_teams_oauth'

        # Check for SharePoint scopes
        if 'sites' in scope_string or 'sharepoint' in scope_string:
            return 'microsoft_sharepoint_oauth'

        # Check for Tasks/To Do scopes
        if 'tasks' in scope_string or 'task' in scope_string:
            return 'microsoft_todo_oauth'

        # Default to generic Microsoft OAuth
        return 'microsoft_oauth'
