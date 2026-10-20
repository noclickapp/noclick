"""
Presence Handler

presence:chat carries a tab's claim that its person is watching their chat
right now (utils/user_presence.watching_chat). A beat renews the tab's claim,
``live: false`` withdraws it, and a socket that disconnects withdraws every
claim it made, so a closed tab stops counting even when its last word was lost.
One-way: the tab never waits on an answer.
"""

import logging
from typing import Callable, Dict, Set, Tuple

from utils.user_presence import claim_chat_live, release_chat_live
from wss.receiver.client_events import PresenceChatRequest
from wss.schema import SocketIOHandler

logger = logging.getLogger(__name__)


class PresenceHandler(SocketIOHandler):
    """Handler for a tab's watching-the-chat beats"""

    def __init__(self, sio):
        super().__init__(sio)
        # sid -> (user, tabs it claimed): sockets are per container, and so is this.
        self._claims: Dict[str, Tuple[str, Set[str]]] = {}

    def get_events(self) -> Dict[str, Callable]:
        return {"presence:chat": self.handle_chat}

    async def handle_chat(self, sid: str, request: PresenceChatRequest) -> None:
        session = await self.sio.get_session(sid)
        user_id = session.get("user_id") if session else None
        # Staff viewing an account as its owner (mimic) are not its owner watching.
        if not user_id or session.get("real_user_id"):
            return
        if request.live:
            # A socket's user never changes (update_auth refuses another user's token).
            self._claims.setdefault(sid, (user_id, set()))[1].add(request.tab_id)
            await claim_chat_live(user_id, request.tab_id)
            return
        if sid in self._claims:
            self._claims[sid][1].discard(request.tab_id)
        await release_chat_live(user_id, [request.tab_id])

    async def cleanup_user(self, sid: str) -> None:
        claimed = self._claims.pop(sid, None)
        if claimed is not None:
            await release_chat_live(*claimed)
