"""
Handler for the WhatsApp QR code credential flow via WAHooks (socket surface).

Thin adapter over ``utils.whatsapp_qr``: it resolves the signed-in user as the
binding owner, delegates start/finalize to the shared user-agnostic core, and
maps the core's result dicts onto the socket Response models. The binding-safety
logic (reservation + unique index + recurring charge + idempotent finalize)
lives once in the core so the public credential-provide link shares it verbatim.

Linking makes the credential alone. A linked number's agent is the platform's
(``WHATSAPP_AGENT``): ``whatsapp:agent:status`` says whether the app may offer
one and which agent already answers it, and ``whatsapp:agent:create`` makes it
on the owner's yes.
"""

import logging
import os
from typing import Callable, Dict

from repositories.credentials import CredentialsRepo
from utils.capabilities import WHATSAPP_AGENT, capability
from utils.database_pool import DatabasePoolMixin
from utils.encryption import get_encryption
from utils.whatsapp_qr import finalize_qr_connection, start_qr_connection
from wss.schema import SocketIOHandler
from wss.sender import send_event, ResponseEvent
from wss.sender.responses import (
    WhatsAppQRStartResponse,
    WhatsAppQRStatusResponse,
)
from wss.sender.whatsapp_agent_responses import WhatsAppAgentCreateResponse, WhatsAppAgentStatusResponse
from wss.receiver.client_events import (
    WhatsAppAgentCreateRequest,
    WhatsAppAgentStatusRequest,
    WhatsAppQRStartRequest,
    WhatsAppQRStatusRequest,
)

logger = logging.getLogger(__name__)


class WhatsAppQRHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for WhatsApp QR code credential WebSocket events"""

    def __init__(self, sio):
        super().__init__(sio)
        self.encryption = get_encryption()

    def get_events(self) -> Dict[str, Callable]:
        return {
            "whatsapp:qr:start": self.start_qr_flow,
            "whatsapp:qr:status": self.check_status,
            "whatsapp:agent:status": self.agent_status,
            "whatsapp:agent:create": self.create_agent,
        }

    async def setup_user(self, sid: str) -> None:
        _ = sid

    async def start_qr_flow(self, sid: str, request: WhatsAppQRStartRequest) -> None:
        """Create a scannable WAHooks connection bound to the signed-in user."""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WhatsAppQRStartResponse(success=False, message="User not authenticated").model_dump(),
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WhatsAppQRStartResponse(success=False, message="Database not available").model_dump(),
                ))
                return

            if not os.environ.get("WAHOOKS_API_KEY", "").strip():
                # Typed, so the panel can ask for the instance's key in place
                # instead of showing an error with nowhere to go.
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WhatsAppQRStartResponse(
                        success=False, code="wahooks_key_missing",
                        message="WhatsApp QR sign-in runs through WAHooks, and this instance has no WAHooks API key yet.",
                    ).model_dump(),
                ))
                return
            result = await start_qr_connection(
                pool, owner_id=user_id,
                reconnect_credential_id=request.reconnect_credential_id,
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=WhatsAppQRStartResponse(
                    success=result.get("success", False),
                    connection_id=result.get("connection_id"),
                    qr_code=result.get("qr_code"),
                    message=result.get("message", ""),
                    code=result.get("code"),
                ).model_dump(),
            ))
        except Exception as e:
            logger.error(f"[WhatsAppQRHandler] start_qr_flow error: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=WhatsAppQRStartResponse(success=False, message=str(e)).model_dump(),
            ))

    async def check_status(self, sid: str, request: WhatsAppQRStatusRequest) -> None:
        """Poll the connection; on connect, mint the credential for the signed-in user."""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WhatsAppQRStatusResponse(
                        success=False, status="error", message="User not authenticated"
                    ).model_dump(),
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=WhatsAppQRStatusResponse(
                        success=False, status="error", message="Database not available"
                    ).model_dump(),
                ))
                return

            user_tier = session.get('user_data', {}).get('subscription_tier', 'free')
            result = await finalize_qr_connection(
                pool, owner_id=user_id, connection_id=request.connection_id,
                user_tier=user_tier, encryption=self.encryption,
                credential_name=request.credential_name,
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=WhatsAppQRStatusResponse(
                    success=result.get("success", False),
                    status=result.get("status", "error"),
                    credential_id=result.get("credential_id"),
                    credential_name=result.get("credential_name"),
                    phone_number=result.get("phone_number"),
                    qr_code=result.get("qr_code"),
                    message=result.get("message", ""),
                ).model_dump(),
            ))
        except Exception as e:
            logger.error(f"[WhatsAppQRHandler] check_status error: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=WhatsAppQRStatusResponse(
                    success=False, status="error", message=str(e)
                ).model_dump(),
            ))

    async def _number(self, sid: str, credential_id: str):
        """The signed-in user, the pool and their own WhatsApp number's credential, or the reason there are none."""
        user_id = (await self.sio.get_session(sid)).get('user_id')
        if not user_id:
            return None, "User not authenticated"
        pool = await self.get_pool()
        if not pool:
            return None, "Database not available"
        number = await CredentialsRepo(pool).get_owned_header(credential_id, user_id)
        if number is None or number["credential_type"] != "whatsapp_qr":
            return None, "That isn't a WhatsApp number of yours"
        return (pool, user_id, number), None

    async def agent_status(self, sid: str, request: WhatsAppAgentStatusRequest) -> None:
        """Whether the app may offer the number an agent, and the agent that answers it already."""
        try:
            found, refused = await self._number(sid, request.credential_id)
            agents = capability(WHATSAPP_AGENT)
            if refused or agents is None:
                answer = WhatsAppAgentStatusResponse(success=refused is None, message=refused)
            else:
                pool, user_id, _ = found
                answer = WhatsAppAgentStatusResponse(success=True, **await agents.status(
                    pool, user_id, request.credential_id))
        except Exception as e:
            logger.error(f"[WhatsAppQRHandler] agent_status error: {e}", exc_info=True)
            answer = WhatsAppAgentStatusResponse(success=False, message="Couldn't read the number's agent")
        await send_event(self.sio, sid, ResponseEvent(request_id=request.request_id, data=answer.model_dump()))

    async def create_agent(self, sid: str, request: WhatsAppAgentCreateRequest) -> None:
        """The number's agent, made with its channel; one already answering it is answered instead."""
        try:
            found, refused = await self._number(sid, request.credential_id)
            agents = capability(WHATSAPP_AGENT)
            if refused or agents is None:
                answer = WhatsAppAgentCreateResponse(success=False, message=refused or "No agents here")
            else:
                pool, user_id, number = found
                answer = WhatsAppAgentCreateResponse(success=True, **await agents.create(
                    pool, user_id, request.credential_id, number.get("phone_number")))
        except Exception as e:
            logger.error(f"[WhatsAppQRHandler] create_agent error: {e}", exc_info=True)
            answer = WhatsAppAgentCreateResponse(success=False, message="Couldn't create the agent")
        await send_event(self.sio, sid, ResponseEvent(request_id=request.request_id, data=answer.model_dump()))
