"""
Handler for OpenAI Codex device code OAuth flow.
Manages the device code authorization process that allows users to authenticate
with their ChatGPT account for use with the Codex CLI agent.
"""

import logging
from typing import Dict, Callable

from utils.database_pool import DatabasePoolMixin
from utils.encryption import get_encryption
from wss.schema import SocketIOHandler
from wss.sender import send_event, ResponseEvent
from wss.sender.responses import (
    CodexDeviceCodeStartResponse,
    CodexDeviceCodePollResponse,
)
from wss.receiver.client_events import (
    CodexDeviceCodeStartRequest,
    CodexDeviceCodePollRequest,
)

logger = logging.getLogger(__name__)

# Provider device-code mechanics live in harness_oauth_flows (the shared source
# used by both this handler and the public credential-provide endpoints).
from nodes.agent.harness_oauth_flows import codex_start, codex_complete, OAuthFlowError


class CodexAuthHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for Codex device code OAuth WebSocket events"""

    def __init__(self, sio):
        super().__init__(sio)
        self.encryption = get_encryption()

    def get_events(self) -> Dict[str, Callable]:
        return {
            "codex:auth:start": self.start_device_code,
            "codex:auth:poll": self.poll_device_code,
        }

    async def setup_user(self, sid: str) -> None:
        _ = sid

    async def start_device_code(self, sid: str, request: CodexDeviceCodeStartRequest) -> None:
        """
        Initiate the device code flow by requesting a user code from OpenAI.
        Returns a verification URL and one-time code for the user to enter in their browser.
        """
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=CodexDeviceCodeStartResponse(
                        success=False,
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            try:
                result = await codex_start()
            except OAuthFlowError as e:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=CodexDeviceCodeStartResponse(success=False, message=str(e)).model_dump()
                ))
                return

            display, poll = result["display"], result["poll"]
            logger.info(f"[CodexAuthHandler] Device code issued for user {user_id}: code={display['user_code']}")

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=CodexDeviceCodeStartResponse(
                    success=True,
                    verification_url=display["verification_url"],
                    user_code=display["user_code"],
                    device_auth_id=poll["device_auth_id"],
                    interval=display["interval"],
                    message="Open the verification URL and enter the code to connect your ChatGPT account."
                ).model_dump()
            ))

        except Exception as e:
            logger.error(f"[CodexAuthHandler] start_device_code error: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=CodexDeviceCodeStartResponse(success=False, message=str(e)).model_dump()
            ))

    async def poll_device_code(self, sid: str, request: CodexDeviceCodePollRequest) -> None:
        """
        Poll the device code token endpoint. Call this repeatedly (every `interval` seconds)
        until it returns success (user approved) or an error (expired/denied).
        On success, exchanges the authorization code for tokens and stores them as a credential.
        """
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=CodexDeviceCodePollResponse(
                        success=False,
                        status="error",
                        message="User not authenticated"
                    ).model_dump()
                ))
                return

            try:
                result = await codex_complete({
                    "device_auth_id": request.device_auth_id,
                    "user_code": request.user_code,
                })
            except OAuthFlowError as e:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=CodexDeviceCodePollResponse(success=False, status="error", message=str(e)).model_dump()
                ))
                return

            if result["status"] == "pending":
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=CodexDeviceCodePollResponse(
                        success=True,
                        status="pending",
                        message="Waiting for user approval..."
                    ).model_dump()
                ))
                return

            credential_data = result["credential_data"]

            try:
                encrypted_data = self.encryption.encrypt_credential(credential_data)
            except Exception as e:
                logger.error(f"[CodexAuthHandler] Encryption failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=CodexDeviceCodePollResponse(
                        success=False, status="error", message="Failed to encrypt credentials"
                    ).model_dump()
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=CodexDeviceCodePollResponse(
                        success=False, status="error", message="Database connection not available"
                    ).model_dump()
                ))
                return

            credential_name = request.credential_name or "ChatGPT (Codex)"

            async with pool.acquire() as conn:
                from repositories.credentials import create_credential_with_limit_check
                user_tier = session.get('user_data', {}).get('subscription_tier', 'free')
                row, error = await create_credential_with_limit_check(
                    conn, user_id, user_tier, 'agent_codex_oauth',
                    credential_name, encrypted_data, {
                        'provider': 'codex',
                        'auth_mode': 'chatgpt',
                    },
                )
                if error:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={}, error=error
                    ))
                    return

                logger.info(f"[CodexAuthHandler] Created Codex OAuth credential {row['id']} for user {user_id}")

                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=CodexDeviceCodePollResponse(
                        success=True,
                        status="completed",
                        credential_id=str(row['id']),
                        credential_name=row['name'],
                        message="ChatGPT account connected successfully"
                    ).model_dump()
                ))

        except Exception as e:
            logger.error(f"[CodexAuthHandler] poll_device_code error: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=CodexDeviceCodePollResponse(
                    success=False, status="error", message=str(e)
                ).model_dump()
            ))
