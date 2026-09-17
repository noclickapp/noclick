"""
Verified phone identity (Settings → Phone).

The number a signed-in user proves possession of here is what WhatsApp
messages and calls resolve to an account through. Every event is gated on
the phone_channel rollout; the rules (Twilio Verify approval, one live number
per account, rate limits) live in utils/phone_identity.py.
"""

import logging
from typing import Any, Awaitable, Callable, Dict, Optional

from utils.feature_gates import FeatureNotAvailable, require_feature
from utils.phone_identity import PhoneIdentity, PhoneLinkError, default_service
from wss.receiver.client_events import (
    PhoneLinkCheckRequest,
    PhoneLinkStartRequest,
    PhoneStatusRequest,
    PhoneUnlinkRequest,
)
from wss.schema import SocketIOHandler
from wss.sender import send_event
from wss.sender.events import ResponseEvent
from wss.session_actor import session_actor

logger = logging.getLogger(__name__)

FEATURE = "phone_channel"


class PhoneHandler(SocketIOHandler):
    """Handler for linking, checking and unlinking a user's verified phone"""

    def __init__(self, sio, service_factory: Optional[Callable[[], PhoneIdentity]] = None):
        super().__init__(sio)
        self._service_factory = service_factory

    def get_events(self) -> Dict[str, Callable]:
        return {
            "phone:status": self.handle_status,
            "phone:link:start": self.handle_link_start,
            "phone:link:check": self.handle_link_check,
            "phone:unlink": self.handle_unlink,
        }

    async def _respond(
        self, sid: str, request_id: str,
        op: Callable[[PhoneIdentity, str], Awaitable[Any]],
    ) -> None:
        try:
            actor = await session_actor(self.sio, sid)
            if actor is None:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id, data=None, error="Not authenticated"))
                return
            user_id, email = actor
            require_feature(FEATURE, email=email)
            # Resolved per request so the module-level default stays patchable.
            service = (self._service_factory or default_service)()
            data = await op(service, user_id)
            await send_event(self.sio, sid, ResponseEvent(request_id=request_id, data=data))
        except FeatureNotAvailable as e:
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id, data={"kind": "gated"}, error=str(e)))
        except PhoneLinkError as e:
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id, data={"kind": e.kind}, error=str(e)))
        except Exception as e:
            logger.error(f"[Phone] request failed: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id, data=None, error=str(e)))

    async def handle_status(self, sid: str, request: PhoneStatusRequest) -> None:
        await self._respond(sid, request.request_id, lambda svc, uid: svc.status(uid))

    async def handle_link_start(self, sid: str, request: PhoneLinkStartRequest) -> None:
        await self._respond(
            sid, request.request_id, lambda svc, uid: svc.start_link(uid, request.phone))

    async def handle_link_check(self, sid: str, request: PhoneLinkCheckRequest) -> None:
        await self._respond(
            sid, request.request_id,
            lambda svc, uid: svc.check_link(uid, request.challenge_id, request.code))

    async def handle_unlink(self, sid: str, request: PhoneUnlinkRequest) -> None:
        async def op(svc: PhoneIdentity, uid: str) -> Dict[str, Any]:
            return {"unlinked": await svc.unlink(uid)}
        await self._respond(sid, request.request_id, op)
