"""Instance OAuth app settings (self-hosted only).

Reads and writes `instance_oauth_apps` — the per-provider OAuth client the whole
install connects through. See utils/instance_oauth.py for why it exists and how
it relates to environment variables.

Self-hosted only, and refused rather than hidden: the hosted service's OAuth
apps are its own, and a request to overwrite them from a client would be a
serious thing to accept quietly. The Settings tab that sends these events is
gated the same way, so a refusal here means someone reached past the UI.
"""

import logging
from typing import Callable, Dict

from utils.database_pool import DatabasePoolMixin
from utils.edition import is_local_edition
from utils.instance_oauth import delete_app, env_configured_providers, list_apps, upsert_app
from wss.schema import SocketIOHandler
from wss.sender import send_event
from wss.sender.events import ResponseEvent
from wss.receiver.client_events import (
    InstanceOAuthDeleteRequest,
    InstanceOAuthListRequest,
    InstanceOAuthSetRequest,
)

logger = logging.getLogger(__name__)

_HOSTED_REFUSAL = "Instance OAuth apps are configured per deployment; not available on the hosted service."


class InstanceOAuthHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for self-hosted per-provider OAuth app configuration."""

    def __init__(self, sio):
        super().__init__(sio)

    def get_events(self) -> Dict[str, Callable]:
        return {
            "instance_oauth:list": self.handle_list,
            "instance_oauth:set": self.handle_set,
            "instance_oauth:delete": self.handle_delete,
        }

    async def setup_user(self, sid: str) -> None:
        _ = sid

    async def _authorize(self, sid: str, request) -> str:
        """The caller's user id, or None after answering with the reason."""
        session = await self.sio.get_session(sid)
        user_id = session.get("user_id") if session else None
        if not user_id:
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data=None, error="Not authenticated"))
            return None
        if not is_local_edition():
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data=None, error=_HOSTED_REFUSAL))
            return None
        return user_id

    async def _state(self) -> Dict:
        """What every response carries: stored apps, plus the providers already
        covered by environment variables so the UI can say so instead of showing
        them as unconfigured."""
        return {
            "apps": await list_apps(await self.get_pool()),
            "env_providers": env_configured_providers(),
        }

    async def handle_list(self, sid: str, request: InstanceOAuthListRequest) -> None:
        try:
            if not await self._authorize(sid, request):
                return
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data=await self._state()))
        except Exception as e:
            logger.error(f"[InstanceOAuth] list failed: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data=None, error=str(e)))

    async def handle_set(self, sid: str, request: InstanceOAuthSetRequest) -> None:
        try:
            user_id = await self._authorize(sid, request)
            if not user_id:
                return
            await upsert_app(
                await self.get_pool(),
                request.provider,
                request.client_id.strip(),
                (request.client_secret or "").strip() or None,
                user_id,
            )
            logger.info(f"[InstanceOAuth] {request.provider} app configured by {user_id}")
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data=await self._state()))
        except Exception as e:
            logger.error(f"[InstanceOAuth] set failed: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data=None, error=str(e)))

    async def handle_delete(self, sid: str, request: InstanceOAuthDeleteRequest) -> None:
        try:
            if not await self._authorize(sid, request):
                return
            await delete_app(await self.get_pool(), request.provider)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data=await self._state()))
        except Exception as e:
            logger.error(f"[InstanceOAuth] delete failed: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data=None, error=str(e)))
