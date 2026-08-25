"""
Handler for PostHog OAuth operations (authorization_code + PKCE).

Access tokens are short-ish (~10h) and refresh tokens are single-use / rotating,
so refresh goes through the shared freshen choke point (manual_refresh_credential).
The exchange takes the PKCE code_verifier from the frontend and resolves the
account's default project id + region base URL for the stored credential.
"""

import logging
from typing import Dict, Callable

from utils.database_pool import DatabasePoolMixin
from utils.encryption import get_encryption
from nodes.oauth.posthog_oauth import (
    exchange_code_for_tokens,
    refresh_access_token,
    is_token_expired,
    normalize_posthog_oauth_base_url,
    POSTHOG_DEFAULT_SCOPES,
)
from utils.ssrf import guarded_async_client
from wss.schema import SocketIOHandler
from wss.sender import send_event, ResponseEvent
from wss.sender.responses import (
    PostHogOAuthExchangeResponse,
    PostHogOAuthRefreshResponse,
    PostHogOAuthValidateResponse,
)
from wss.receiver.client_events import (
    PostHogOAuthExchangeRequest,
    PostHogOAuthRefreshRequest,
    PostHogOAuthValidateRequest,
)

logger = logging.getLogger(__name__)


# Identity scopes granted implicitly with any PostHog OAuth token — excluded
# from the missing-scope comparison so they can't produce false rejections.
_POSTHOG_IMPLICIT_IDENTITY_SCOPES = {"openid", "email", "profile"}


def find_missing_granted_scopes(requested, granted: str):
    """Return the subset of ``requested`` API scopes the user didn't grant.

    Mirrors the Google OAuth handler's post-exchange validation: compares
    against the space-separated ``scope`` string from the token response. A
    read-only / partial grant on PostHog's consent screen otherwise mints a
    credential that fails every write operation with a 403 later.

    PostHog scope semantics (posthog/scopes.py): ``X:write`` IMPLIES ``X:read``
    — a full grant returns only the write scope per resource, so a requested
    ``X:read`` is satisfied by a granted ``X:write`` (comparing literally
    false-rejected every full-access connect). ``*`` is the all-access grant.
    """
    granted_set = set((granted or "").split())
    if "*" in granted_set:
        return []

    def _satisfied(scope: str) -> bool:
        if scope in granted_set:
            return True
        if scope.endswith(":read") and f"{scope[:-5]}:write" in granted_set:
            return True  # write implies read
        return False

    return [
        s for s in (requested or [])
        if s not in _POSTHOG_IMPLICIT_IDENTITY_SCOPES and not _satisfied(s)
    ]


def format_missing_scopes_message(missing) -> str:
    """User-facing rejection copy. Must contain "didn't grant" — the frontend
    OAuthErrorPanel keys its "Permissions missing" heading off that marker."""
    shown = ", ".join(missing[:6]) + ("…" if len(missing) > 6 else "")
    return (
        f"PostHog didn't grant the requested permissions ({shown}). "
        "Reconnect and approve all requested permissions on PostHog's consent "
        "screen — a read-only or partial grant can't run this node's operations."
    )


async def _resolve_default_project(base_url: str, access_token: str, scoped_teams=None):
    """Return (project_id, project_name) for the credential's default project.

    A team-scoped grant names its projects in the token response and 403s on
    org-level endpoints, so scoped_teams wins; otherwise the org's first project;
    finally /api/users/@me/ (exempt from team scoping) as the fallback.
    """
    if isinstance(scoped_teams, (list, tuple)) and scoped_teams:
        return str(scoped_teams[0]), None
    base_url = normalize_posthog_oauth_base_url(base_url)
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    try:
        async with guarded_async_client(timeout=20.0) as client:
            resp = await client.get(f"{base_url}/api/organizations/@current/projects/", headers=headers)
            if resp.status_code == 200:
                results = (resp.json() or {}).get("results", [])
                if results:
                    return str(results[0].get("id")), results[0].get("name")
                return None, None
            me = await client.get(f"{base_url}/api/users/@me/", headers=headers)
            if me.status_code == 200:
                team = (me.json() or {}).get("team") or {}
                if team.get("id") is not None:
                    return str(team["id"]), team.get("name")
    except Exception as e:
        logger.warning(f"[PostHogOAuthHandler] Could not resolve default project: {e}")
    return None, None


class PostHogOAuthHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for PostHog OAuth WebSocket events"""

    def __init__(self, sio):
        super().__init__(sio)
        self.encryption = get_encryption()

    def get_events(self) -> Dict[str, Callable]:
        return {
            "posthog:oauth:exchange": self.exchange_oauth_code,
            "posthog:oauth:refresh": self.refresh_oauth_token,
            "posthog:oauth:validate": self.validate_oauth_token,
        }

    async def setup_user(self, sid: str) -> None:
        _ = sid

    async def exchange_oauth_code(self, sid: str, request: PostHogOAuthExchangeRequest) -> None:
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=PostHogOAuthExchangeResponse(success=False, message="User not authenticated").model_dump()))
                return

            try:
                tokens, user_info = await exchange_code_for_tokens(
                    code=request.code, redirect_uri=request.redirect_uri, code_verifier=request.code_verifier)
            except ValueError as e:
                logger.error(f"[PostHogOAuthHandler] Token exchange failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=PostHogOAuthExchangeResponse(success=False, message=str(e)).model_dump()))
                return

            # Reject partial/read-only grants BEFORE persisting the credential —
            # same pattern as Google OAuth: the frontend shows the "Permissions
            # missing" panel and offers Reconnect.
            requested_scopes = request.scopes or POSTHOG_DEFAULT_SCOPES
            missing_scopes = find_missing_granted_scopes(requested_scopes, tokens.scope)
            if missing_scopes:
                logger.warning(
                    "[PostHogOAuthHandler] Rejecting credential for %s: missing scopes %s (granted=%r)",
                    user_info.email, missing_scopes, tokens.scope,
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=PostHogOAuthExchangeResponse(
                        success=False,
                        message=format_missing_scopes_message(missing_scopes),
                    ).model_dump()))
                return

            project_id, project_name = await _resolve_default_project(
                user_info.base_url, tokens.access_token, scoped_teams=tokens.scoped_teams,
            )

            credential_data = {
                'access_token': tokens.access_token,
                'refresh_token': tokens.refresh_token,
                'expires_at': tokens.expires_at,
                'base_url': user_info.base_url,
                'project_id': project_id,
                'name': user_info.name,
                'email': user_info.email,
                # Consent-screen access level — a team-scoped grant 403s on org
                # endpoints, so the node resolves projects from scoped_teams.
                'scoped_teams': tokens.scoped_teams,
                'scoped_organizations': tokens.scoped_organizations,
            }
            try:
                encrypted_data = self.encryption.encrypt_credential(credential_data)
            except Exception as e:
                logger.error(f"[PostHogOAuthHandler] Encryption failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=PostHogOAuthExchangeResponse(success=False, message="Failed to encrypt credential").model_dump()))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=PostHogOAuthExchangeResponse(success=False, message="Database connection not available").model_dump()))
                return

            credential_name = user_info.email or user_info.name or "PostHog"
            if project_name:
                credential_name = f"{credential_name} ({project_name})"
            async with pool.acquire() as conn:
                from repositories.credentials import create_credential_with_limit_check
                user_tier = session.get('user_data', {}).get('subscription_tier', 'free')
                row, error = await create_credential_with_limit_check(
                    conn, user_id, user_tier, 'posthog_oauth',
                    credential_name, encrypted_data, {
                        'provider': 'posthog', 'name': user_info.name, 'email': user_info.email,
                        'base_url': user_info.base_url, 'region': user_info.region,
                        'project_id': project_id, 'scopes': request.scopes,
                    })
                if error:
                    await send_event(self.sio, sid, ResponseEvent(request_id=request.request_id, data={}, error=error))
                    return
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=PostHogOAuthExchangeResponse(
                        success=True, credential_id=str(row['id']), credential_name=row['name'],
                        name=user_info.name, email=user_info.email,
                        message="PostHog account connected successfully").model_dump()))
                logger.info(f"[PostHogOAuthHandler] Created PostHog credential {row['id']} for user {user_id}")

        except Exception as e:
            logger.error(f"[PostHogOAuthHandler] Error in exchange_oauth_code: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=PostHogOAuthExchangeResponse(success=False, message="Internal error").model_dump()))

    async def refresh_oauth_token(self, sid: str, request: PostHogOAuthRefreshRequest) -> None:
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=PostHogOAuthRefreshResponse(success=False, message="User not authenticated").model_dump()))
                return
            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=PostHogOAuthRefreshResponse(success=False, message="Database connection not available").model_dump()))
                return
            from wss.handlers.oauth.manual_refresh import manual_refresh_credential
            try:
                credential_data = await manual_refresh_credential(
                    pool, user_id=user_id, credential_id=request.credential_id,
                    provider="posthog", make_refresh=lambda credential: refresh_access_token)
            except ValueError as e:
                logger.error(f"[PostHogOAuthHandler] Token refresh failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=PostHogOAuthRefreshResponse(success=False, message=str(e)).model_dump()))
                return
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=PostHogOAuthRefreshResponse(success=True, expires_at=credential_data.get('expires_at'),
                                                 message="Token refreshed successfully").model_dump()))
        except Exception as e:
            logger.error(f"[PostHogOAuthHandler] Error in refresh_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=PostHogOAuthRefreshResponse(success=False, message="Internal error").model_dump()))

    async def validate_oauth_token(self, sid: str, request: PostHogOAuthValidateRequest) -> None:
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=PostHogOAuthValidateResponse(valid=False, message="User not authenticated").model_dump()))
                return
            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=PostHogOAuthValidateResponse(valid=False, message="Database connection not available").model_dump()))
                return
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id, credential, metadata FROM credentials WHERE id = $1 AND owner_id = $2",
                    request.credential_id, user_id)
                if not row:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=PostHogOAuthValidateResponse(valid=False, message="Credential not found").model_dump()))
                    return
                try:
                    credential_data = self.encryption.decrypt_credential(row['credential'])
                except Exception as e:
                    logger.error(f"[PostHogOAuthHandler] Decryption failed: {e}")
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=PostHogOAuthValidateResponse(valid=False, message="Failed to decrypt credential").model_dump()))
                    return
                expires_at = credential_data.get('expires_at')
                name = credential_data.get('name') or (row['metadata'] or {}).get('name')
                email = credential_data.get('email') or (row['metadata'] or {}).get('email')
                if not expires_at:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=PostHogOAuthValidateResponse(valid=True, expires_soon=False, name=name, email=email, message="Token is valid").model_dump()))
                    return
                is_expired = is_token_expired(expires_at, buffer_minutes=0)
                expires_soon = is_token_expired(expires_at, buffer_minutes=5)
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=PostHogOAuthValidateResponse(
                        valid=not is_expired, expires_soon=expires_soon and not is_expired, name=name, email=email,
                        message="Token is valid" if not is_expired else "Token has expired").model_dump()))
        except Exception as e:
            logger.error(f"[PostHogOAuthHandler] Error in validate_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=PostHogOAuthValidateResponse(valid=False, message="Internal error").model_dump()))
