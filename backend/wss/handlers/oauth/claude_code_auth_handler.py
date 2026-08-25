"""
Handler for Claude Code CLI OAuth 2.0 PKCE flow.
Manages the authorization code + PKCE exchange that allows users to authenticate
with their Anthropic account for use with the Claude Code agent.
"""

import logging
from typing import Dict, Callable

from utils.database_pool import DatabasePoolMixin
from utils.encryption import get_encryption
from wss.schema import SocketIOHandler
from wss.sender import send_event, ResponseEvent
from wss.sender.responses import (
    ClaudeCodeAuthStartResponse,
    ClaudeCodeAuthExchangeResponse,
)
from wss.receiver.client_events import (
    ClaudeCodeAuthStartRequest,
    ClaudeCodeAuthExchangeRequest,
)

logger = logging.getLogger(__name__)

# PKCE mechanics (verifier stash + token exchange) live in harness_oauth_flows,
# the shared source used by both this handler and the public provide endpoints.
from nodes.agent.harness_oauth_flows import (
    claude_code_start,
    claude_code_complete,
    OAuthFlowError,
)


class ClaudeCodeAuthHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for Claude Code OAuth PKCE WebSocket events"""

    def __init__(self, sio):
        super().__init__(sio)
        self.encryption = get_encryption()

    def get_events(self) -> Dict[str, Callable]:
        return {
            "claude-code:auth:start": self.start_oauth,
            "claude-code:auth:exchange": self.exchange_code,
        }

    async def setup_user(self, sid: str) -> None:
        _ = sid

    async def start_oauth(self, sid: str, request: ClaudeCodeAuthStartRequest) -> None:
        """
        Initiate the OAuth 2.0 PKCE flow by generating a code verifier/challenge pair,
        storing the verifier in Redis, and returning the authorization URL for the user
        to open in their browser.
        """
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=ClaudeCodeAuthStartResponse(
                        success=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            try:
                result = await claude_code_start()
            except OAuthFlowError as e:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=ClaudeCodeAuthStartResponse(success=False, message=str(e)).model_dump()
                ))
                return

            auth_session_id = result["poll"]["auth_session_id"]
            logger.info(f"[ClaudeCodeAuthHandler] PKCE flow started for user {user_id}, session {auth_session_id}")

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=ClaudeCodeAuthStartResponse(
                    success=True,
                    auth_url=result["display"]["authorize_url"],
                    auth_session_id=auth_session_id,
                ).model_dump()
            ))

        except Exception as e:
            logger.error(f"[ClaudeCodeAuthHandler] start_oauth error: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=ClaudeCodeAuthStartResponse(success=False, message=str(e)).model_dump()
            ))

    async def exchange_code(self, sid: str, request: ClaudeCodeAuthExchangeRequest) -> None:
        """
        Exchange an authorization code for tokens using the stored PKCE code verifier.
        On success, encrypts and stores the tokens as a credential.
        """
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=ClaudeCodeAuthExchangeResponse(
                        success=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            try:
                result = await claude_code_complete({
                    "auth_session_id": request.auth_session_id,
                    "code": request.authorization_code,
                })
            except OAuthFlowError as e:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=ClaudeCodeAuthExchangeResponse(success=False, message=str(e)).model_dump()
                ))
                return

            credential_data = result["credential_data"]

            try:
                encrypted_data = self.encryption.encrypt_credential(credential_data)
            except Exception as e:
                logger.error(f"[ClaudeCodeAuthHandler] Encryption failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=ClaudeCodeAuthExchangeResponse(
                        success=False, message="Failed to encrypt credentials"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=ClaudeCodeAuthExchangeResponse(
                        success=False, message="Database connection not available"
                    ).model_dump()
                ))
                return

            credential_name = request.credential_name or "Anthropic (Claude Code)"

            async with pool.acquire() as conn:
                from repositories.credentials import create_credential_with_limit_check
                user_tier = session.get('user_data', {}).get('subscription_tier', 'free')
                row, error = await create_credential_with_limit_check(
                    conn, user_id, user_tier, 'agent_claude_code_oauth',
                    credential_name, encrypted_data, {
                        'provider': 'claude_code',
                        'auth_mode': 'oauth',
                    },
                )
                if error:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={}, error=error
                    ))
                    return

                logger.info(f"[ClaudeCodeAuthHandler] Created Claude Code OAuth credential {row['id']} for user {user_id}")

                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=ClaudeCodeAuthExchangeResponse(
                        success=True,
                        credential_id=str(row['id']),
                        credential_name=row['name'],
                        message="Anthropic account connected successfully"
                    ).model_dump()
                ))

        except Exception as e:
            logger.error(f"[ClaudeCodeAuthHandler] exchange_code error: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=ClaudeCodeAuthExchangeResponse(
                    success=False, message=str(e)
                ).model_dump()
            ))
