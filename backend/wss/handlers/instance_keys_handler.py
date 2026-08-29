"""Instance model-provider key settings (self-hosted only).

Reads and writes `instance_provider_keys` — the server-side provider keys the
builder brain and agents run on. See utils/instance_provider_keys.py for how
they relate to environment variables.

Self-hosted only, and refused rather than hidden, for the same reason as the
instance OAuth apps: a hosted deployment's keys are its own.
"""

import logging
from typing import Callable, Dict

from utils.database_pool import DatabasePoolMixin
from utils.edition import is_local_edition
from utils.instance_provider_keys import (
    SUPPORTED_ENV_VARS,
    delete_key,
    env_configured,
    list_keys,
    set_key,
)
from wss.schema import SocketIOHandler
from wss.sender import send_event
from wss.sender.events import ResponseEvent
from wss.receiver.client_events import (
    InstanceKeysDeleteRequest,
    InstanceKeysListRequest,
    InstanceKeysSetRequest,
)

logger = logging.getLogger(__name__)

_HOSTED_REFUSAL = "Instance provider keys are configured per deployment; not available on the hosted service."


class InstanceKeysHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for self-hosted server-side provider keys."""

    def __init__(self, sio):
        super().__init__(sio)

    def get_events(self) -> Dict[str, Callable]:
        return {
            "instance_keys:list": self.handle_list,
            "instance_keys:set": self.handle_set,
            "instance_keys:delete": self.handle_delete,
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
        return {
            "keys": await list_keys(await self.get_pool()),
            "env_vars": env_configured(),
            "supported": list(SUPPORTED_ENV_VARS),
        }

    async def handle_list(self, sid: str, request: InstanceKeysListRequest) -> None:
        try:
            if not await self._authorize(sid, request):
                return
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data=await self._state()))
        except Exception as e:
            logger.error(f"[InstanceKeys] list failed: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data=None, error=str(e)))

    async def handle_set(self, sid: str, request: InstanceKeysSetRequest) -> None:
        try:
            user_id = await self._authorize(sid, request)
            if not user_id:
                return
            await set_key(await self.get_pool(), request.env_var, request.value, user_id)
            logger.info(f"[InstanceKeys] {request.env_var} configured by {user_id}")
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data=await self._state()))
        except Exception as e:
            logger.error(f"[InstanceKeys] set failed: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data=None, error=str(e)))

    async def handle_delete(self, sid: str, request: InstanceKeysDeleteRequest) -> None:
        try:
            if not await self._authorize(sid, request):
                return
            await delete_key(await self.get_pool(), request.env_var)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data=await self._state()))
        except Exception as e:
            logger.error(f"[InstanceKeys] delete failed: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data=None, error=str(e)))
