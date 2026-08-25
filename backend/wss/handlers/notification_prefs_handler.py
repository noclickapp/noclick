"""
Notification Preferences Handler

Socket get/update for the per-user system-alert email opt-outs
(user_notification_preferences). The same prefs gate every send in
utils/notifications.py and back the one-click unsubscribe links, so the
settings toggles, the email footers, and the send path all read one store.
"""

import logging
from typing import Callable, Dict

from utils.database_pool import DatabasePoolMixin
from utils.notifications import CATEGORIES, get_prefs, set_category_enabled
from wss.schema import SocketIOHandler
from wss.sender import send_event
from wss.sender.events import ResponseEvent
from wss.receiver.client_events import (
    NotificationPrefsGetRequest,
    NotificationPrefsUpdateRequest,
)

logger = logging.getLogger(__name__)


class NotificationPrefsHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for notification email preference reads/writes"""

    def __init__(self, sio):
        super().__init__(sio)

    def get_events(self) -> Dict[str, Callable]:
        return {
            "notifications:prefs:get": self.handle_get,
            "notifications:prefs:update": self.handle_update,
        }

    async def setup_user(self, sid: str) -> None:
        _ = sid

    async def _user_id(self, sid: str):
        session = await self.sio.get_session(sid)
        return session.get('user_id') if session else None

    async def handle_get(self, sid: str, request: NotificationPrefsGetRequest) -> None:
        try:
            user_id = await self._user_id(sid)
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data=None, error="Not authenticated"))
                return
            prefs = await get_prefs(user_id)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={'prefs': prefs}))
        except Exception as e:
            logger.error(f"[NotificationPrefs] get failed: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data=None, error=str(e)))

    async def handle_update(self, sid: str, request: NotificationPrefsUpdateRequest) -> None:
        try:
            user_id = await self._user_id(sid)
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data=None, error="Not authenticated"))
                return
            unknown = set(request.prefs) - CATEGORIES
            if unknown:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data=None,
                    error=f"Unknown notification categories: {sorted(unknown)}"))
                return
            for category, enabled in request.prefs.items():
                await set_category_enabled(user_id, category, bool(enabled))
            prefs = await get_prefs(user_id)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={'success': True, 'prefs': prefs}))
        except Exception as e:
            logger.error(f"[NotificationPrefs] update failed: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data=None, error=str(e)))
