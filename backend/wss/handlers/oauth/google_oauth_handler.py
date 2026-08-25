"""
Handler for Google OAuth operations.
Manages OAuth token exchange, refresh, and validation for Google integrations.
"""

import logging
from typing import Dict, Callable, List
from utils.database_pool import DatabasePoolMixin
from utils.encryption import get_encryption
from nodes.oauth.google_oauth import (
    exchange_code_for_tokens,
    refresh_access_token,
    is_token_expired,
)
from wss.schema import SocketIOHandler
from wss.sender import send_event, ResponseEvent
from wss.sender.responses import (
    GoogleOAuthExchangeResponse,
    GoogleOAuthRefreshResponse,
    GoogleOAuthValidateResponse,
    CredentialInfo,
)
from wss.receiver.client_events import (
    GoogleOAuthExchangeRequest,
    GoogleOAuthRefreshRequest,
    GoogleOAuthValidateRequest,
)

logger = logging.getLogger(__name__)


# Google always grants these identity scopes when ``email``/``profile``/
# ``openid`` are requested, and normalises ``email``/``profile`` to their
# ``userinfo.*`` aliases in the granted scope string. They're invisible on the
# consent screen (no checkbox), so we mustn't treat them as "user-skippable"
# when computing whether the user opted out of any *real* API scopes.
_GOOGLE_IMPLICIT_IDENTITY_SCOPES = frozenset({
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
})

# Scopes a node REQUESTS but does not REQUIRE to connect — a secondary
# capability the core credential can live without. They ride the consent screen
# (so a user who grants them unlocks the extra feature), but declining one must
# not block the connection. DV360's Bid Manager reporting scope is the case: the
# node needs `display-video` for ~all operations, while `doubleclickbidmanager`
# only powers the 3 report ops — requiring both would reject every user who
# unticks Bid Manager on Google's granular-consent screen.
_GOOGLE_OPTIONAL_SCOPES = frozenset({
    "https://www.googleapis.com/auth/doubleclickbidmanager",
})


# Map well-known scope prefixes to the human service name shown on Google's
# consent screen. Used only to make the missing-scopes error message friendly
# — falls back to the bare scope URL when nothing matches.
_GOOGLE_SCOPE_SERVICE_NAMES = (
    ("https://www.googleapis.com/auth/gmail.", "Gmail"),
    ("https://www.googleapis.com/auth/spreadsheets", "Google Sheets"),
    ("https://www.googleapis.com/auth/drive", "Google Drive"),
    ("https://www.googleapis.com/auth/devstorage", "Google Cloud Storage"),
    ("https://www.googleapis.com/auth/calendar", "Google Calendar"),
    ("https://www.googleapis.com/auth/documents", "Google Docs"),
    ("https://www.googleapis.com/auth/presentations", "Google Slides"),
    ("https://www.googleapis.com/auth/forms", "Google Forms"),
    ("https://www.googleapis.com/auth/tasks", "Google Tasks"),
    ("https://www.googleapis.com/auth/contacts", "Google Contacts"),
    ("https://www.googleapis.com/auth/youtube", "YouTube"),
    ("https://www.googleapis.com/auth/analytics", "Google Analytics"),
    ("https://www.googleapis.com/auth/adwords", "Google Ads"),
    ("https://www.googleapis.com/auth/business.manage", "Google Business Profile"),
    ("https://www.googleapis.com/auth/webmasters", "Google Search Console"),
)


def find_missing_granted_scopes(requested: List[str], granted: str) -> List[str]:
    """Return the subset of ``requested`` API scopes the user didn't grant.

    Compares against the space-separated ``granted`` string Google returned in
    the token response. ``_GOOGLE_IMPLICIT_IDENTITY_SCOPES`` (always granted) and
    ``_GOOGLE_OPTIONAL_SCOPES`` (requested-but-not-required secondary features)
    are dropped from the requested set first — they'd otherwise reject a
    perfectly usable credential when the user declines a non-essential scope.

    Empty / whitespace-only ``granted`` is treated as "nothing granted" so a
    malformed token response surfaces every API scope as missing.
    """
    granted_set = set((granted or "").split())
    return [
        scope
        for scope in requested
        if scope not in _GOOGLE_IMPLICIT_IDENTITY_SCOPES
        and scope not in _GOOGLE_OPTIONAL_SCOPES
        and scope not in granted_set
    ]


def format_missing_scopes_message(missing: List[str]) -> str:
    """Build the user-facing error for a missing-scopes credential rejection.

    Groups scopes by the well-known service name (Gmail, Google Sheets, etc.)
    so the message tells the user exactly which checkbox on Google's consent
    screen they need to tick on the next retry.
    """
    services = []
    leftover = []
    for scope in missing:
        for prefix, name in _GOOGLE_SCOPE_SERVICE_NAMES:
            if scope.startswith(prefix):
                if name not in services:
                    services.append(name)
                break
        else:
            leftover.append(scope)

    labels = services + leftover
    if len(labels) == 1:
        permission = labels[0]
    elif len(labels) == 2:
        permission = f"{labels[0]} and {labels[1]}"
    else:
        permission = ", ".join(labels[:-1]) + f", and {labels[-1]}"

    return (
        f"Google didn't grant the {permission} permission. "
        "Please reconnect and make sure every checkbox on Google's consent "
        "screen is checked before clicking Continue."
    )


class GoogleOAuthHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for Google OAuth WebSocket events"""

    def __init__(self, sio):
        super().__init__(sio)
        self.encryption = get_encryption()

    def get_events(self) -> Dict[str, Callable]:
        """Register Google OAuth events"""
        return {
            "google:oauth:exchange": self.exchange_oauth_code,
            "google:oauth:refresh": self.refresh_oauth_token,
            "google:oauth:validate": self.validate_oauth_token,
        }

    async def setup_user(self, sid: str) -> None:
        _ = sid

    async def exchange_oauth_code(self, sid: str, request: GoogleOAuthExchangeRequest) -> None:
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
                    data=GoogleOAuthExchangeResponse(
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
                    custom_client_id=request.custom_client_id,
                    custom_client_secret=request.custom_client_secret,
                )
            except ValueError as e:
                logger.error(f"[GoogleOAuthHandler] Token exchange failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=GoogleOAuthExchangeResponse(
                        success=False,
                        message=str(e)
                    ).model_dump()
                ))
                return

            # Reject "sign in only" tokens before persisting them.
            #
            # Google's granular consent screen lets users uncheck individual
            # scopes while still clicking Continue, so the OAuth flow returns
            # a 200 OK with a token that only has `email`/`profile`/`openid`
            # — every API call against it then fails with "insufficient
            # authentication scopes" at runtime, long after the credential
            # appears healthy in the UI. Catch the divergence here, refuse
            # to create the credential, and tell the user exactly which
            # consent checkbox to tick on the next attempt.
            missing_scopes = find_missing_granted_scopes(request.scopes, tokens.scope)
            if missing_scopes:
                logger.warning(
                    "[GoogleOAuthHandler] Rejecting credential for %s: missing scopes %s "
                    "(requested=%s, granted=%r)",
                    user_info.email,
                    missing_scopes,
                    request.scopes,
                    tokens.scope,
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=GoogleOAuthExchangeResponse(
                        success=False,
                        message=format_missing_scopes_message(missing_scopes),
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
            if request.custom_client_id and request.custom_client_secret:
                credential_data['client_id'] = request.custom_client_id
                credential_data['client_secret'] = request.custom_client_secret

            # Encrypt and store credential
            try:
                encrypted_data = self.encryption.encrypt_credential(credential_data)
            except Exception as e:
                logger.error(f"[GoogleOAuthHandler] Encryption failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=GoogleOAuthExchangeResponse(
                        success=False,
                        message="Failed to encrypt credential"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=GoogleOAuthExchangeResponse(
                        success=False,
                        message="Database connection not available"
                    ).model_dump()
                ))
                return

            # Determine credential type based on scopes
            credential_type = self._get_credential_type_from_scopes(request.scopes)

            # Use the email address as the credential name for better identification
            credential_name = user_info.email

            async with pool.acquire() as conn:
                from repositories.credentials import create_credential_with_limit_check
                user_tier = session.get('user_data', {}).get('subscription_tier', 'free')
                row, error = await create_credential_with_limit_check(
                    conn, user_id, user_tier, credential_type,
                    credential_name, encrypted_data, {
                        'provider': 'google',
                        'email': user_info.email,
                        'scopes': request.scopes,
                    },
                )
                if error:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={}, error=error
                    ))
                    return

                response = GoogleOAuthExchangeResponse(
                    success=True,
                    credential_id=str(row['id']),
                    credential_name=row['name'],
                    credential_type=credential_type,
                    email=user_info.email,
                    message="Google account connected successfully"
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))
                logger.info(f"[GoogleOAuthHandler] Created Google credential {row['id']} for user {user_id} ({user_info.email})")

        except Exception as e:
            logger.error(f"[GoogleOAuthHandler] Error in exchange_oauth_code: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=GoogleOAuthExchangeResponse(
                    success=False,
                    message="Internal error"
                ).model_dump()
            ))

    async def refresh_oauth_token(self, sid: str, request: GoogleOAuthRefreshRequest) -> None:
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
                    data=GoogleOAuthRefreshResponse(
                        success=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=GoogleOAuthRefreshResponse(
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
                    provider="google",
                    refresh=refresh_access_token,
                )
            except ValueError as e:
                logger.error(f"[GoogleOAuthHandler] Token refresh failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=GoogleOAuthRefreshResponse(
                        success=False,
                        message=str(e)
                    ).model_dump()
                ))
                return

            response = GoogleOAuthRefreshResponse(
                success=True,
                expires_at=credential_data.get('expires_at'),
                message="Token refreshed successfully"
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=response.model_dump()
            ))
            logger.info(f"[GoogleOAuthHandler] Refreshed token for credential {request.credential_id}")

        except Exception as e:
            logger.error(f"[GoogleOAuthHandler] Error in refresh_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=GoogleOAuthRefreshResponse(
                    success=False,
                    message="Internal error"
                ).model_dump()
            ))

    async def validate_oauth_token(self, sid: str, request: GoogleOAuthValidateRequest) -> None:
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
                    data=GoogleOAuthValidateResponse(
                        valid=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=GoogleOAuthValidateResponse(
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
                        data=GoogleOAuthValidateResponse(
                            valid=False,
                            message="Credential not found or access denied"
                        ).model_dump()
                    ))
                    return

                # Decrypt credential
                try:
                    credential_data = self.encryption.decrypt_credential(row['credential'])
                except Exception as e:
                    logger.error(f"[GoogleOAuthHandler] Decryption failed: {e}")
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=GoogleOAuthValidateResponse(
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
                        data=GoogleOAuthValidateResponse(
                            valid=False,
                            email=email,
                            message="No expiry information available"
                        ).model_dump()
                    ))
                    return

                is_expired = is_token_expired(expires_at, buffer_minutes=0)
                expires_soon = is_token_expired(expires_at, buffer_minutes=5)

                response = GoogleOAuthValidateResponse(
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
            logger.error(f"[GoogleOAuthHandler] Error in validate_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=GoogleOAuthValidateResponse(
                    valid=False,
                    message="Internal error"
                ).model_dump()
            ))

    def _get_credential_type_from_scopes(self, scopes: list[str]) -> str:
        """
        Determine the credential type based on requested OAuth scopes.
        """
        scope_set = set(scopes)

        # Check specific Google service scopes first (before generic drive scope)
        if 'https://www.googleapis.com/auth/spreadsheets' in scope_set:
            return 'google_sheets_oauth'
        elif 'https://www.googleapis.com/auth/gmail.readonly' in scope_set or \
             'https://www.googleapis.com/auth/gmail.send' in scope_set or \
             'https://www.googleapis.com/auth/gmail.modify' in scope_set or \
             'https://www.googleapis.com/auth/gmail.compose' in scope_set or \
             'https://www.googleapis.com/auth/gmail.labels' in scope_set or \
             'https://www.googleapis.com/auth/gmail.settings.basic' in scope_set:
            return 'google_gmail_oauth'
        elif 'https://www.googleapis.com/auth/calendar.events' in scope_set or \
             'https://www.googleapis.com/auth/calendar' in scope_set:
            return 'google_calendar_oauth'
        elif 'https://www.googleapis.com/auth/youtube.force-ssl' in scope_set or \
             'https://www.googleapis.com/auth/youtube' in scope_set or \
             'https://www.googleapis.com/auth/youtube.readonly' in scope_set:
            return 'google_youtube_oauth'
        elif 'https://www.googleapis.com/auth/tasks' in scope_set:
            return 'google_tasks_oauth'
        elif 'https://www.googleapis.com/auth/contacts' in scope_set:
            return 'google_contacts_oauth'
        elif 'https://www.googleapis.com/auth/documents' in scope_set:
            return 'google_docs_oauth'
        elif 'https://www.googleapis.com/auth/forms.body' in scope_set or \
             'https://www.googleapis.com/auth/forms.responses.readonly' in scope_set:
            return 'google_forms_oauth'
        elif 'https://www.googleapis.com/auth/presentations' in scope_set:
            return 'google_slides_oauth'
        elif 'https://www.googleapis.com/auth/analytics.readonly' in scope_set or \
             'https://www.googleapis.com/auth/analytics' in scope_set:
            return 'google_analytics_oauth'
        elif 'https://www.googleapis.com/auth/adwords' in scope_set:
            return 'google_ads_oauth'
        elif 'https://www.googleapis.com/auth/business.manage' in scope_set:
            return 'google_business_profile_oauth'
        elif 'https://www.googleapis.com/auth/webmasters' in scope_set:
            return 'google_search_console_oauth'
        elif 'https://www.googleapis.com/auth/devstorage.full_control' in scope_set or \
             'https://www.googleapis.com/auth/devstorage.read_write' in scope_set or \
             'https://www.googleapis.com/auth/devstorage.read_only' in scope_set or \
             'https://www.googleapis.com/auth/devstorage.write_only' in scope_set:
            return 'google_cloud_storage_oauth'
        elif 'https://www.googleapis.com/auth/datastore' in scope_set:
            return 'firestore_oauth'
        elif 'https://www.googleapis.com/auth/bigquery' in scope_set or \
             'https://www.googleapis.com/auth/bigquery.readonly' in scope_set:
            return 'bigquery_oauth'
        elif 'https://www.googleapis.com/auth/meetings.space.created' in scope_set or \
             'https://www.googleapis.com/auth/meetings.space.readonly' in scope_set or \
             'https://www.googleapis.com/auth/meetings.space.settings' in scope_set:
            return 'google_meet_oauth'
        elif 'https://www.googleapis.com/auth/cloud-translation' in scope_set:
            return 'google_translate_oauth'
        elif 'https://www.googleapis.com/auth/display-video' in scope_set or \
             'https://www.googleapis.com/auth/doubleclickbidmanager' in scope_set:
            return 'dv360_oauth'
        elif 'https://www.googleapis.com/auth/drive' in scope_set:
            return 'google_drive_oauth'
        else:
            return 'google_oauth'
