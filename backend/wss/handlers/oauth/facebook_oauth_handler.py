"""
Handler for Facebook OAuth operations (used for Instagram Graph API).
Manages OAuth 2.0 flow for Instagram Business/Creator accounts via Facebook Login.

Instagram Graph API requires connecting via Facebook Pages, not direct Instagram OAuth.
This handler exchanges Facebook OAuth codes for tokens and retrieves Instagram account info.

Multi-account flow: When multiple Instagram accounts are linked to the user's Facebook
profile, the handler returns needs_selection=True with the account list. The frontend
then presents a selection UI and re-calls with selected_instagram_user_id +
pending_selection_key to complete the credential creation.
"""

import logging
import secrets
import time
from typing import Dict, Callable
from utils.database_pool import DatabasePoolMixin
from utils.encryption import get_encryption
from nodes.oauth.facebook_oauth import (
    exchange_code_for_tokens,
    refresh_access_token,
    is_token_expired,
    MultipleAccountsError,
)
from wss.schema import SocketIOHandler
from wss.sender import send_event, ResponseEvent
from wss.sender.responses import (
    FacebookOAuthExchangeResponse,
    FacebookOAuthRefreshResponse,
    FacebookOAuthValidateResponse,
)
from wss.receiver.client_events import (
    FacebookOAuthExchangeRequest,
    FacebookOAuthRefreshRequest,
    FacebookOAuthValidateRequest,
)

logger = logging.getLogger(__name__)

# In-memory store for pending multi-account selections.
# key → {'tokens': FacebookTokens, 'accounts': list, 'email': str|None, 'created_at': float, 'user_id': str}
# Entries expire after 10 minutes.
_pending_account_selections: Dict[str, dict] = {}
_PENDING_TTL_SECONDS = 600


def _purge_expired_selections() -> None:
    """Remove expired pending account selection entries."""
    cutoff = time.time() - _PENDING_TTL_SECONDS
    expired = [k for k, v in _pending_account_selections.items() if v['created_at'] < cutoff]
    for k in expired:
        del _pending_account_selections[k]


class FacebookOAuthHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for Facebook OAuth WebSocket events (Instagram integration)"""

    def __init__(self, sio):
        super().__init__(sio)
        self.encryption = get_encryption()

    def get_events(self) -> Dict[str, Callable]:
        """Register Facebook OAuth events"""
        return {
            "facebook:oauth:exchange": self.exchange_oauth_code,
            "facebook:oauth:refresh": self.refresh_oauth_token,
            "facebook:oauth:validate": self.validate_oauth_token,
        }

    async def setup_user(self, sid: str) -> None:
        _ = sid

    async def exchange_oauth_code(self, sid: str, request: FacebookOAuthExchangeRequest) -> None:
        """
        Exchange OAuth authorization code for tokens and store as credential.
        Called from the OAuth callback page after user grants permission.

        Supports two-step multi-account selection flow:
        - First call (no pending_selection_key): exchange code, auto-select if 1 account,
          or return needs_selection=True with account list if multiple.
        - Second call (with pending_selection_key + selected_instagram_user_id): complete
          credential creation using tokens stored from the first call.
        """
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=FacebookOAuthExchangeResponse(
                        success=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            # ----------------------------------------------------------------
            # Step A: Second call — complete account selection from pending state
            # ----------------------------------------------------------------
            if request.pending_selection_key and request.selected_instagram_user_id:
                _purge_expired_selections()
                pending = _pending_account_selections.get(request.pending_selection_key)

                if not pending:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=FacebookOAuthExchangeResponse(
                            success=False,
                            message="Account selection expired or invalid. Please reconnect."
                        ).model_dump()
                    ))
                    return

                if pending['user_id'] != user_id:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=FacebookOAuthExchangeResponse(
                            success=False,
                            message="Session mismatch. Please reconnect."
                        ).model_dump()
                    ))
                    return

                chosen = next(
                    (a for a in pending['accounts'] if a['instagram_user_id'] == request.selected_instagram_user_id),
                    None,
                )
                if not chosen:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=FacebookOAuthExchangeResponse(
                            success=False,
                            message="Selected account not found. Please reconnect."
                        ).model_dump()
                    ))
                    return

                # Use tokens from the first call
                tokens = pending['tokens']
                email = pending['email']
                del _pending_account_selections[request.pending_selection_key]

                await self._store_instagram_credential(
                    sid=sid,
                    request=request,
                    user_id=user_id,
                    tokens=tokens,
                    chosen_account=chosen,
                    email=email,
                )
                return

            # ----------------------------------------------------------------
            # Step B: First call — exchange authorization code
            # ----------------------------------------------------------------
            try:
                tokens, instagram_info = await exchange_code_for_tokens(
                    code=request.code,
                    redirect_uri=request.redirect_uri,
                    selected_instagram_user_id=request.selected_instagram_user_id,
                )
            except MultipleAccountsError as exc:
                # Multiple accounts found — store tokens and ask frontend to select
                _purge_expired_selections()
                key = secrets.token_urlsafe(32)
                _pending_account_selections[key] = {
                    'tokens': exc.tokens,
                    'accounts': exc.accounts,
                    'email': exc.email,
                    'user_id': user_id,
                    'created_at': time.time(),
                }
                logger.info(
                    f"[FacebookOAuthHandler] Multiple Instagram accounts found for user {user_id}, "
                    f"stored pending selection key {key[:8]}..."
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=FacebookOAuthExchangeResponse(
                        success=False,
                        needs_selection=True,
                        accounts=exc.accounts,
                        pending_selection_key=key,
                        message=f"Multiple Instagram accounts found. Please select one."
                    ).model_dump()
                ))
                return
            except ValueError as e:
                logger.error(f"[FacebookOAuthHandler] Token exchange failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=FacebookOAuthExchangeResponse(
                        success=False,
                        message=str(e)
                    ).model_dump()
                ))
                return

            chosen_account = {
                'instagram_user_id': instagram_info.instagram_user_id,
                'instagram_username': instagram_info.instagram_username,
                'facebook_page_id': instagram_info.facebook_page_id,
                'facebook_page_name': instagram_info.facebook_page_name,
            }
            await self._store_instagram_credential(
                sid=sid,
                request=request,
                user_id=user_id,
                tokens=tokens,
                chosen_account=chosen_account,
                email=instagram_info.email,
            )

        except Exception as e:
            logger.error(f"[FacebookOAuthHandler] Error in exchange_oauth_code: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=FacebookOAuthExchangeResponse(
                    success=False,
                    message="Internal error"
                ).model_dump()
            ))

    async def _store_instagram_credential(
        self,
        sid: str,
        request: FacebookOAuthExchangeRequest,
        user_id: str,
        tokens,
        chosen_account: dict,
        email: str | None,
    ) -> None:
        """Encrypt and INSERT a new Instagram credential row into the database."""
        credential_data = {
            'access_token': tokens.access_token,
            'expires_at': tokens.expires_at,
            'instagram_user_id': chosen_account['instagram_user_id'],
            'instagram_username': chosen_account.get('instagram_username'),
            'email': email,
            'facebook_page_id': chosen_account.get('facebook_page_id'),
            'facebook_page_name': chosen_account.get('facebook_page_name'),
        }

        try:
            encrypted_data = self.encryption.encrypt_credential(credential_data)
        except Exception as e:
            logger.error(f"[FacebookOAuthHandler] Encryption failed: {e}")
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=FacebookOAuthExchangeResponse(
                    success=False,
                    message="Failed to encrypt credential"
                ).model_dump()
            ))
            return

        pool = await self.get_pool()
        if not pool:
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=FacebookOAuthExchangeResponse(
                    success=False,
                    message="Database connection not available"
                ).model_dump()
            ))
            return

        instagram_username = chosen_account.get('instagram_username')
        instagram_user_id = chosen_account['instagram_user_id']
        credential_name = (
            f"@{instagram_username}" if instagram_username
            else (email or f"Instagram ({instagram_user_id})")
        )

        async with pool.acquire() as conn:
            session = await self.sio.get_session(sid)
            from repositories.credentials import create_credential_with_limit_check
            user_tier = session.get('user_data', {}).get('subscription_tier', 'free')
            row, error = await create_credential_with_limit_check(
                conn, user_id, user_tier, 'instagram_oauth',
                credential_name, encrypted_data, {
                'provider': 'facebook',
                'instagram_user_id': instagram_user_id,
                'instagram_username': instagram_username,
                'email': email,
                'facebook_page_id': chosen_account.get('facebook_page_id'),
                'facebook_page_name': chosen_account.get('facebook_page_name'),
                'expires_at': tokens.expires_at,
                'scopes': request.scopes,
                },
            )
            if error:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data={}, error=error
                ))
                return

            response = FacebookOAuthExchangeResponse(
                success=True,
                credential_id=str(row['id']),
                credential_name=row['name'],
                instagram_username=instagram_username,
                email=email,
                message="Instagram account connected successfully"
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=response.model_dump()
            ))
            logger.info(
                f"[FacebookOAuthHandler] Created Instagram credential {row['id']} "
                f"for user {user_id} (@{instagram_username})"
            )

    async def refresh_oauth_token(self, sid: str, request: FacebookOAuthRefreshRequest) -> None:
        """
        Refresh a Facebook/Instagram OAuth token and update the stored credential.

        Facebook long-lived tokens last 60 days. They can be refreshed after 24 hours
        to extend their validity. Token refresh exchanges the current token for a new one.
        The metadata column is updated alongside the encrypted blob to keep expires_at
        consistent for display and validation queries.
        """
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=FacebookOAuthRefreshResponse(
                        success=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=FacebookOAuthRefreshResponse(
                        success=False,
                        message="Database connection not available"
                    ).model_dump()
                ))
                return

            # Refresh-if-expired through the shared freshen choke point
            # (lock, in-lock re-read, CAS persist, audit row) — never a
            # bespoke unlocked UPDATE that races the execute-path refresh.
            # Facebook long-lived tokens have no refresh_token: the exchange
            # submits the CURRENT access token, so key the rotation on it.
            # is_expired is the provider's 7-day-buffer check — a token that
            # close to its 60-day expiry was last refreshed ~53 days ago, so
            # Facebook's 24hr minimum between refreshes can't be violated.
            from wss.handlers.oauth.manual_refresh import manual_refresh_credential

            try:
                credential_data = await manual_refresh_credential(
                    pool,
                    user_id=user_id,
                    credential_id=request.credential_id,
                    provider="facebook",
                    refresh=refresh_access_token,
                    is_expired=is_token_expired,
                    refresh_token_key="access_token",
                )
            except ValueError as e:
                logger.error(f"[FacebookOAuthHandler] Token refresh failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=FacebookOAuthRefreshResponse(
                        success=False,
                        message=str(e)
                    ).model_dump()
                ))
                return

            response = FacebookOAuthRefreshResponse(
                success=True,
                expires_at=credential_data.get('expires_at'),
                message="Token refreshed successfully"
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=response.model_dump()
            ))
            logger.info(f"[FacebookOAuthHandler] Refreshed token for credential {request.credential_id}")

        except Exception as e:
            logger.error(f"[FacebookOAuthHandler] Error in refresh_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=FacebookOAuthRefreshResponse(
                    success=False,
                    message="Internal error"
                ).model_dump()
            ))

    async def validate_oauth_token(self, sid: str, request: FacebookOAuthValidateRequest) -> None:
        """
        Validate if a stored OAuth credential is still valid.

        Facebook/Instagram tokens expire after 60 days. This checks the expiry time
        and returns whether the token is valid and if it's expiring soon.
        """
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=FacebookOAuthValidateResponse(
                        valid=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=FacebookOAuthValidateResponse(
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
                        data=FacebookOAuthValidateResponse(
                            valid=False,
                            message="Credential not found or access denied"
                        ).model_dump()
                    ))
                    return

                try:
                    credential_data = self.encryption.decrypt_credential(row['credential'])
                except Exception as e:
                    logger.error(f"[FacebookOAuthHandler] Decryption failed: {e}")
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=FacebookOAuthValidateResponse(
                            valid=False,
                            message="Failed to decrypt credential"
                        ).model_dump()
                    ))
                    return

                expires_at = credential_data.get('expires_at')
                instagram_username = credential_data.get('instagram_username') or (row['metadata'] or {}).get('instagram_username')
                email = credential_data.get('email') or (row['metadata'] or {}).get('email')

                if not expires_at:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=FacebookOAuthValidateResponse(
                            valid=False,
                            instagram_username=instagram_username,
                            email=email,
                            message="No expiry information available"
                        ).model_dump()
                    ))
                    return

                is_expired = is_token_expired(expires_at, buffer_days=0)
                expires_soon = is_token_expired(expires_at, buffer_days=7)

                response = FacebookOAuthValidateResponse(
                    valid=not is_expired,
                    expires_soon=expires_soon and not is_expired,
                    instagram_username=instagram_username,
                    email=email,
                    message="Token is valid" if not is_expired else "Token has expired"
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))

        except Exception as e:
            logger.error(f"[FacebookOAuthHandler] Error in validate_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=FacebookOAuthValidateResponse(
                    valid=False,
                    message="Internal error"
                ).model_dump()
            ))
