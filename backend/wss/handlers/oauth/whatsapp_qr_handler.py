"""
Handler for the WhatsApp QR code credential flow via WAHooks (socket surface).

Thin adapter over ``utils.whatsapp_qr``: it resolves the signed-in user as the
binding owner, delegates start/finalize to the shared user-agnostic core, and
maps the core's result dicts onto the socket Response models. The binding-safety
logic (reservation + unique index + recurring charge + idempotent finalize)
lives once in the core so the public credential-provide link shares it verbatim.
"""

import logging
from typing import Callable, Dict

from utils.database_pool import DatabasePoolMixin
from utils.encryption import get_encryption
from utils.whatsapp_qr import finalize_qr_connection, start_qr_connection
from wss.schema import SocketIOHandler
from wss.sender import send_event, ResponseEvent
from wss.sender.responses import (
    WhatsAppQRStartResponse,
    WhatsAppQRStatusResponse,
)
from wss.receiver.client_events import (
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
