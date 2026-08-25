"""
Handler for Supabase OAuth operations.
Manages OAuth 2.0 + PKCE token exchange for Supabase Management API access.

After exchanging the authorization code for tokens, the handler lists all of the user's
projects. If there is only one project it is auto-selected. If there are multiple, the
frontend receives a 'needs_project_selection' response with the project list and a
pending_id, then the user picks a project and sends supabase:oauth:select_project.

Project API keys (anon + service_role) are fetched once after project selection and
cached in the stored credential so node executions call the Supabase REST API directly
without additional Management API round-trips.
"""

import logging
import uuid
from typing import Callable, Dict

from repositories.credentials import create_credential_with_limit_check
from nodes.oauth.supabase_oauth import (
    exchange_code_for_tokens,
    fetch_project_api_keys,
    is_token_expired,
    list_projects,
    refresh_access_token,
)
from utils.database_pool import DatabasePoolMixin
from utils.encryption import get_encryption
from wss.receiver.client_events import SupabaseOAuthExchangeRequest, SupabaseOAuthSelectProjectRequest
from wss.schema import SocketIOHandler
from wss.sender import ResponseEvent, send_event
from wss.sender.responses import SupabaseOAuthExchangeResponse

logger = logging.getLogger(__name__)


class SupabaseOAuthHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for Supabase OAuth WebSocket events."""

    def __init__(self, sio):
        super().__init__(sio)
        self.encryption = get_encryption()
        # Temporary in-memory store for pending project selections.
        # Key: pending_id (uuid str); Value: dict with tokens + credential_name + sid
        self._pending_tokens: Dict[str, dict] = {}

    def get_events(self) -> Dict[str, Callable]:
        return {
            "supabase:oauth:exchange": self.exchange_oauth_code,
            "supabase:oauth:select_project": self.select_project,
            "supabase:oauth:refresh": self.refresh_oauth_token,
            "supabase:oauth:validate": self.validate_oauth_token,
        }

    async def setup_user(self, sid: str) -> None:
        _ = sid

    async def _store_credential(
        self,
        sid: str,
        request_id: str,
        user_id: str,
        session: dict,
        tokens,
        project: dict,
        credential_name: str,
    ) -> None:
        """Fetch API keys for *project* and store the full credential."""
        project_ref = project.get('id') or project.get('ref', '')
        project_name = project.get('name', project_ref)
        project_url = f"https://{project_ref}.supabase.co"

        project_keys = await fetch_project_api_keys(tokens.access_token, project_ref)
        if not project_keys.anon_key and not project_keys.service_role_key:
            logger.error(
                f"[SupabaseOAuthHandler] No API keys retrieved for {project_ref!r}. "
                "Ensure the OAuth app has the 'secrets:read' scope."
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data=SupabaseOAuthExchangeResponse(
                    success=False,
                    message=(
                        "Could not retrieve project API keys. Make sure your Supabase OAuth app "
                        "has the 'secrets:read' scope enabled in the Supabase dashboard "
                        "(supabase.com/dashboard/org/_/apps)."
                    ),
                ).model_dump()
            ))
            return

        credential_data = {
            'access_token': tokens.access_token,
            'expires_at': tokens.expires_at,
            'token_type': tokens.token_type,
            'project_url': project_url,
            'project_ref': project_ref,
        }
        if tokens.refresh_token:
            credential_data['refresh_token'] = tokens.refresh_token
        if project_keys.anon_key:
            credential_data['anon_key'] = project_keys.anon_key
        if project_keys.service_role_key:
            credential_data['service_role_key'] = project_keys.service_role_key

        try:
            encrypted_data = self.encryption.encrypt_credential(credential_data)
        except Exception as e:
            logger.error(f"[SupabaseOAuthHandler] Encryption failed: {e}")
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data=SupabaseOAuthExchangeResponse(
                    success=False, message="Failed to encrypt credential"
                ).model_dump()
            ))
            return

        pool = await self.get_pool()
        if not pool:
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data=SupabaseOAuthExchangeResponse(
                    success=False, message="Database connection not available"
                ).model_dump()
            ))
            return

        final_name = credential_name or f"Supabase – {project_name}"

        async with pool.acquire() as conn:
            user_tier = session.get('user_data', {}).get('subscription_tier', 'free')
            row, error = await create_credential_with_limit_check(
                conn, user_id, user_tier, 'supabase_oauth',
                final_name, encrypted_data, {
                    'provider': 'supabase',
                    'project_url': project_url,
                    'project_ref': project_ref,
                    'project_name': project_name,
                    'expires_at': tokens.expires_at,
                    'has_anon_key': bool(project_keys.anon_key),
                    'has_service_role_key': bool(project_keys.service_role_key),
                },
            )
            if error:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id, data={}, error=error
                ))
                return

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data=SupabaseOAuthExchangeResponse(
                    success=True,
                    credential_id=str(row['id']),
                    credential_name=row['name'],
                    project_url=project_url,
                    message="Supabase account connected successfully",
                ).model_dump()
            ))
            logger.info(
                f"[SupabaseOAuthHandler] Stored Supabase OAuth credential for user {user_id}, "
                f"project={project_ref!r}"
            )

    async def exchange_oauth_code(self, sid: str, request: SupabaseOAuthExchangeRequest) -> None:
        """
        Exchange OAuth authorization code for tokens, then list projects.
        - 1 project  → auto-select, fetch API keys, persist credential.
        - Multiple   → return project list to frontend for user selection.
        """
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=SupabaseOAuthExchangeResponse(success=False, message="User not authenticated").model_dump()
                ))
                return

            logger.info(f"[SupabaseOAuthHandler] Exchanging code for user {user_id}")
            try:
                tokens = await exchange_code_for_tokens(
                    code=request.code,
                    redirect_uri=request.redirect_uri,
                    code_verifier=request.code_verifier,
                )
            except ValueError as e:
                logger.error(f"[SupabaseOAuthHandler] Token exchange failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=SupabaseOAuthExchangeResponse(success=False, message=str(e)).model_dump()
                ))
                return

            # List all accessible projects
            projects = await list_projects(tokens.access_token)
            if not projects:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=SupabaseOAuthExchangeResponse(
                        success=False,
                        message="No Supabase projects found. Make sure your account has at least one project."
                    ).model_dump()
                ))
                return

            if len(projects) == 1:
                # Auto-select the only project
                await self._store_credential(
                    sid, request.request_id, user_id, session,
                    tokens, projects[0], request.credential_name,
                )
            else:
                # Multiple projects — ask user to pick one
                pending_id = str(uuid.uuid4())
                self._pending_tokens[pending_id] = {
                    'tokens': tokens,
                    'credential_name': request.credential_name,
                    'user_id': user_id,
                    'sid': sid,
                    'session': session,
                }
                project_options = [
                    {
                        'ref': p.get('id') or p.get('ref', ''),
                        'name': p.get('name', p.get('id', '')),
                        'organization_id': p.get('organization_id', ''),
                    }
                    for p in projects
                ]
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=SupabaseOAuthExchangeResponse(
                        success=True,
                        needs_project_selection=True,
                        projects=project_options,
                        pending_id=pending_id,
                        message="Please select a project to connect.",
                    ).model_dump()
                ))

        except Exception as e:
            logger.exception(f"[SupabaseOAuthHandler] Unexpected error in exchange_oauth_code: {e}")
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=SupabaseOAuthExchangeResponse(
                    success=False, message=f"Unexpected error: {str(e)}"
                ).model_dump()
            ))

    async def select_project(self, sid: str, request: SupabaseOAuthSelectProjectRequest) -> None:
        """Complete the OAuth flow after the user selects a specific project."""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=SupabaseOAuthExchangeResponse(success=False, message="User not authenticated").model_dump()
                ))
                return

            pending = self._pending_tokens.pop(request.pending_id, None)
            if not pending or pending['user_id'] != user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=SupabaseOAuthExchangeResponse(
                        success=False, message="Session expired. Please reconnect your Supabase account."
                    ).model_dump()
                ))
                return

            project = {'id': request.project_ref, 'name': request.project_ref}
            await self._store_credential(
                sid, request.request_id, user_id, pending['session'],
                pending['tokens'], project, pending['credential_name'],
            )

        except Exception as e:
            logger.exception(f"[SupabaseOAuthHandler] Unexpected error in select_project: {e}")
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=SupabaseOAuthExchangeResponse(
                    success=False, message=f"Unexpected error: {str(e)}"
                ).model_dump()
            ))

    async def refresh_oauth_token(self, sid: str, request) -> None:
        """Refresh an expired Supabase Management API token and re-fetch project API keys."""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=SupabaseOAuthExchangeResponse(success=False, message="User not authenticated").model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=SupabaseOAuthExchangeResponse(success=False, message="Database unavailable").model_dump()
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
                    provider="supabase",
                    refresh=refresh_access_token,
                )
            except ValueError as e:
                logger.error(f"[SupabaseOAuthHandler] Token refresh failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=SupabaseOAuthExchangeResponse(success=False, message=str(e)).model_dump()
                ))
                return

            # Re-fetch project API keys with the fresh Management API token and
            # persist them into the blob if they changed (the token refresh
            # itself is already persisted by the choke point).
            project_ref = credential_data.get('project_ref', '')
            if project_ref:
                new_keys = await fetch_project_api_keys(credential_data['access_token'], project_ref)
                updated = dict(credential_data)
                if new_keys.anon_key:
                    updated['anon_key'] = new_keys.anon_key
                if new_keys.service_role_key:
                    updated['service_role_key'] = new_keys.service_role_key
                if updated != credential_data:
                    from utils.credentials import update_credential_data
                    await update_credential_data(
                        credential_id=request.credential_id,
                        user_id=user_id,
                        new_data=updated,
                        pool=pool,
                    )

            async with pool.acquire() as conn:
                credential_name = await conn.fetchval(
                    "SELECT name FROM credentials WHERE id = $1", request.credential_id
                )

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=SupabaseOAuthExchangeResponse(
                    success=True,
                    credential_id=str(request.credential_id),
                    credential_name=credential_name,
                    project_url=credential_data.get('project_url', ''),
                    message="Token refreshed successfully",
                ).model_dump()
            ))
            logger.info(f"[SupabaseOAuthHandler] Refreshed token for credential {request.credential_id}")

        except Exception as e:
            logger.exception(f"[SupabaseOAuthHandler] Unexpected error in refresh_oauth_token: {e}")
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=SupabaseOAuthExchangeResponse(
                    success=False, message=f"Unexpected error: {str(e)}"
                ).model_dump()
            ))

    async def validate_oauth_token(self, sid: str, request) -> None:
        """Check if the stored Supabase OAuth token is still valid."""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=SupabaseOAuthExchangeResponse(success=False, message="Database unavailable").model_dump()
                ))
                return

            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id, name, encrypted_data FROM credentials WHERE id = $1 AND user_id = $2",
                    request.credential_id, user_id
                )
                if not row:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=SupabaseOAuthExchangeResponse(success=False, message="Credential not found").model_dump()
                    ))
                    return

                decrypted = self.encryption.decrypt_credential(row['encrypted_data'])
                expires_at = decrypted.get('expires_at', '')
                is_valid = not is_token_expired(expires_at)
                project_url = decrypted.get('project_url', '')

                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=SupabaseOAuthExchangeResponse(
                        success=is_valid,
                        credential_id=str(row['id']),
                        credential_name=row['name'],
                        project_url=project_url,
                        message="Token valid" if is_valid else "Token expired — please refresh",
                    ).model_dump()
                ))

        except Exception as e:
            logger.exception(f"[SupabaseOAuthHandler] Unexpected error in validate_oauth_token: {e}")
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=SupabaseOAuthExchangeResponse(
                    success=False, message=f"Unexpected error: {str(e)}"
                ).model_dump()
            ))
