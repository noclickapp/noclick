"""
Handler for Slack OAuth operations.
Manages OAuth 2.0 flow for Slack workspace access.
"""

import logging
from typing import Dict, Callable
from utils.credentials import update_credential_data
from utils.database_pool import DatabasePoolMixin
from utils.encryption import get_encryption
from nodes.oauth.slack_oauth import (
    exchange_code_for_tokens,
    is_token_expired,
    validate_token,
)
from utils.slack_installations import upsert_slack_installation_from_exchange
from wss.schema import SocketIOHandler
from wss.sender import send_event, ResponseEvent
from wss.sender.responses import (
    SlackOAuthExchangeResponse,
    SlackOAuthRefreshResponse,
    SlackOAuthValidateResponse,
)
from wss.receiver.client_events import (
    SlackOAuthExchangeRequest,
    SlackOAuthRefreshRequest,
    SlackOAuthValidateRequest,
)

logger = logging.getLogger(__name__)


def _slack_metadata(
    *,
    workspace_info,
    tokens,
    scopes,
    client_id=None,
) -> Dict[str, str]:
    metadata = {
        "provider": "slack",
        "team_id": workspace_info.team_id,
        "team_name": workspace_info.team_name,
        "bot_user_id": workspace_info.bot_user_id,
        "scopes": scopes,
        "app_id": tokens.app_id,
        "expires_at": tokens.expires_at,
        "user_expires_at": tokens.user_expires_at,
    }
    if client_id:
        metadata["client_id"] = client_id
    return {k: v for k, v in metadata.items() if v is not None}


class SlackOAuthHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for Slack OAuth WebSocket events"""

    def __init__(self, sio):
        super().__init__(sio)
        self.encryption = get_encryption()

    def get_events(self) -> Dict[str, Callable]:
        """Register Slack OAuth events"""
        return {
            "slack:oauth:exchange": self.exchange_oauth_code,
            "slack:oauth:refresh": self.refresh_oauth_token,
            "slack:oauth:validate": self.validate_oauth_token,
        }

    async def setup_user(self, sid: str) -> None:
        _ = sid

    async def exchange_oauth_code(self, sid: str, request: SlackOAuthExchangeRequest) -> None:
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
                    data=SlackOAuthExchangeResponse(
                        success=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            # Exchange code for tokens
            try:
                tokens, workspace_info = await exchange_code_for_tokens(
                    code=request.code,
                    redirect_uri=request.redirect_uri,
                    client_id=request.client_id,
                    client_secret=request.client_secret,
                )
            except ValueError as e:
                logger.error(f"[SlackOAuthHandler] Token exchange failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=SlackOAuthExchangeResponse(
                        success=False,
                        message=str(e)
                    ).model_dump()
                ))
                return

            # Prepare credential data (include custom client credentials for refresh)
            credential_data = {
                'access_token': tokens.access_token,
                'refresh_token': tokens.refresh_token,
                'expires_at': tokens.expires_at,
                'scope': tokens.scope,
                'token_type': tokens.token_type,
                'team_id': workspace_info.team_id,
                'team_name': workspace_info.team_name,
                'bot_user_id': workspace_info.bot_user_id,
                'app_id': tokens.app_id,
            }
            # Capture the authed_user xoxp- token alongside the bot xoxb- one
            # when Slack returns it. Used solely by automated trigger tests to
            # post as a real user (bot-self messages are dropped from Event
            # Subscriptions delivery). Production node execution paths read
            # ``access_token`` (the bot token) — never this one.
            if tokens.user_access_token:
                credential_data['user_access_token'] = tokens.user_access_token
                credential_data['user_refresh_token'] = tokens.user_refresh_token
                credential_data['user_expires_at'] = tokens.user_expires_at
                credential_data['user_id_xoxp'] = tokens.user_id_xoxp
            # Store custom client credentials for token refresh if provided
            if request.client_id and request.client_secret:
                credential_data['client_id'] = request.client_id
                credential_data['client_secret'] = request.client_secret

            # Encrypt and store credential
            try:
                encrypted_data = self.encryption.encrypt_credential(credential_data)
            except Exception as e:
                logger.error(f"[SlackOAuthHandler] Encryption failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=SlackOAuthExchangeResponse(
                        success=False,
                        message="Failed to encrypt credential"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=SlackOAuthExchangeResponse(
                        success=False,
                        message="Database connection not available"
                    ).model_dump()
                ))
                return

            # Use the user-provided name, falling back to workspace name
            credential_name = request.credential_name or (f"Slack - {workspace_info.team_name}" if workspace_info.team_name else "Slack Workspace")

            async with pool.acquire() as conn:
                from repositories.credentials import create_credential_with_limit_check
                user_tier = session.get('user_data', {}).get('subscription_tier', 'free')
                metadata = _slack_metadata(
                    workspace_info=workspace_info,
                    tokens=tokens,
                    scopes=request.scopes,
                    client_id=request.client_id,
                )
                existing_row = await conn.fetchrow(
                    """
                    SELECT id, name, credential, metadata
                    FROM credentials
                    WHERE owner_id = $1
                      AND credential_type = 'slack_oauth'
                      AND metadata->>'provider' = 'slack'
                      AND metadata->>'team_id' = $2
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    user_id,
                    workspace_info.team_id,
                )
                if existing_row:
                    existing = self.encryption.decrypt_credential(existing_row["credential"])
                    same_client = (
                        existing.get("client_id") == credential_data.get("client_id")
                    )
                    same_app = (
                        not existing.get("app_id")
                        or not credential_data.get("app_id")
                        or existing.get("app_id") == credential_data.get("app_id")
                    )
                    if same_client and same_app:
                        updated = await update_credential_data(
                            credential_id=str(existing_row["id"]),
                            user_id=user_id,
                            new_data=credential_data,
                            metadata_updates=metadata,
                            pool=pool,
                        )
                        if not updated:
                            await send_event(self.sio, sid, ResponseEvent(
                                request_id=request.request_id,
                                data=SlackOAuthExchangeResponse(
                                    success=False,
                                    message="Failed to update Slack credential"
                                ).model_dump()
                            ))
                            return
                        await conn.execute(
                            "UPDATE credentials SET name = $1 WHERE id = $2",
                            credential_name,
                            existing_row["id"],
                        )
                        row = {
                            "id": existing_row["id"],
                            "name": credential_name,
                        }
                    else:
                        row, error = await create_credential_with_limit_check(
                            conn, user_id, user_tier, 'slack_oauth',
                            credential_name, encrypted_data, metadata,
                        )
                        if error:
                            await send_event(self.sio, sid, ResponseEvent(
                                request_id=request.request_id, data={}, error=error
                            ))
                            return
                else:
                    row, error = await create_credential_with_limit_check(
                        conn, user_id, user_tier, 'slack_oauth',
                        credential_name, encrypted_data, metadata,
                    )
                    if error:
                        await send_event(self.sio, sid, ResponseEvent(
                            request_id=request.request_id, data={}, error=error
                        ))
                        return

            # The fresh grant is the authoritative workspace bot bundle — Slack
            # rotates the installation token on re-install, so every sibling
            # credential's next load must see THIS bundle, not its blob copy.
            await upsert_slack_installation_from_exchange(pool, credential_data)

            response = SlackOAuthExchangeResponse(
                success=True,
                credential_id=str(row['id']),
                credential_name=row['name'],
                team_id=workspace_info.team_id,
                team_name=workspace_info.team_name,
                message="Slack workspace connected successfully"
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=response.model_dump()
            ))
            logger.info(
                f"[SlackOAuthHandler] Saved Slack credential {row['id']} for user {user_id} "
                f"({workspace_info.team_name})"
            )

        except Exception as e:
            logger.error(f"[SlackOAuthHandler] Error in exchange_oauth_code: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=SlackOAuthExchangeResponse(
                    success=False,
                    message="Internal error"
                ).model_dump()
            ))

    async def refresh_oauth_token(self, sid: str, request: SlackOAuthRefreshRequest) -> None:
        """
        Refresh an expiring OAuth credential via the shared freshen choke point.

        Refresh-if-needed: bot and user tokens are renewed only when expired.
        Node execute and config-load paths refresh automatically, so this is a
        manual/admin entry point that reuses the same locked, persist-safe path.
        """
        try:
            # Get user session
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=SlackOAuthRefreshResponse(
                        success=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=SlackOAuthRefreshResponse(
                        success=False,
                        message="Database connection not available"
                    ).model_dump()
                ))
                return

            from utils.credential_loader import load_credential
            from nodes.slack_node import SlackNode

            credential_data = await load_credential(pool, user_id, request.credential_id)
            if not credential_data:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=SlackOAuthRefreshResponse(
                        success=False,
                        message="Credential not found or access denied"
                    ).model_dump()
                ))
                return

            if not credential_data.get('refresh_token') and not credential_data.get('user_refresh_token'):
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=SlackOAuthRefreshResponse(
                        success=False,
                        message="No refresh token available"
                    ).model_dump()
                ))
                return

            # Delegate to the shared freshen choke point (per-credential lock,
            # DB re-read, rotated-token persist, raise on lost write) rather than
            # a bespoke unlocked UPDATE — this refreshes the bot AND user tokens
            # and can't double-spend the single-use rotating refresh token.
            try:
                from nodes.core.oauth_audit import caller_path_scope
                with caller_path_scope("manual_refresh"):
                    await SlackNode.freshen_credential(
                        credential_data,
                        pool=pool,
                        user_id=user_id,
                        credential_id=request.credential_id,
                    )
            except Exception as e:
                logger.error(f"[SlackOAuthHandler] Token refresh failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=SlackOAuthRefreshResponse(
                        success=False,
                        message=str(e)
                    ).model_dump()
                ))
                return

            response = SlackOAuthRefreshResponse(
                success=True,
                expires_at=credential_data.get('expires_at'),
                message="Token refreshed successfully"
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=response.model_dump()
            ))
            logger.info(f"[SlackOAuthHandler] Refreshed token for credential {request.credential_id}")

        except Exception as e:
            logger.error(f"[SlackOAuthHandler] Error in refresh_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=SlackOAuthRefreshResponse(
                    success=False,
                    message="Internal error"
                ).model_dump()
            ))

    async def validate_oauth_token(self, sid: str, request: SlackOAuthValidateRequest) -> None:
        """
        Validate if a stored OAuth credential is still valid.
        Uses Slack's auth.test API to verify the token.
        """
        try:
            # Get user session
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=SlackOAuthValidateResponse(
                        valid=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=SlackOAuthValidateResponse(
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
                        data=SlackOAuthValidateResponse(
                            valid=False,
                            message="Credential not found or access denied"
                        ).model_dump()
                    ))
                    return

                # Decrypt credential
                try:
                    credential_data = self.encryption.decrypt_credential(row['credential'])
                except Exception as e:
                    logger.error(f"[SlackOAuthHandler] Decryption failed: {e}")
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=SlackOAuthValidateResponse(
                            valid=False,
                            message="Failed to decrypt credential"
                        ).model_dump()
                    ))
                    return

                expires_at = credential_data.get('expires_at')
                team_id = credential_data.get('team_id') or row['metadata'].get('team_id')
                team_name = credential_data.get('team_name') or row['metadata'].get('team_name')

                # Check if token is expired or expiring soon
                is_expired = is_token_expired(expires_at, buffer_minutes=0)
                expires_soon = is_token_expired(expires_at, buffer_minutes=5)

                # Even if not expired by time, validate token with Slack API
                access_token = credential_data.get('access_token')
                if access_token and not is_expired:
                    is_valid, workspace_info = await validate_token(access_token)
                    if not is_valid:
                        # Token was revoked or is invalid
                        response = SlackOAuthValidateResponse(
                            valid=False,
                            expires_soon=False,
                            team_id=team_id,
                            team_name=team_name,
                            message="Token has been revoked or is invalid"
                        )
                        await send_event(self.sio, sid, ResponseEvent(
                            request_id=request.request_id,
                            data=response.model_dump()
                        ))
                        return
                    # Update team info from validation
                    if workspace_info:
                        team_id = workspace_info.team_id
                        team_name = workspace_info.team_name

                response = SlackOAuthValidateResponse(
                    valid=not is_expired,
                    expires_soon=expires_soon and not is_expired,
                    team_id=team_id,
                    team_name=team_name,
                    message="Token is valid" if not is_expired else "Token has expired"
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))

        except Exception as e:
            logger.error(f"[SlackOAuthHandler] Error in validate_oauth_token: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=SlackOAuthValidateResponse(
                    valid=False,
                    message="Internal error"
                ).model_dump()
            ))
