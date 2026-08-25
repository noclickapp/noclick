"""Socket handlers for persisted agent conversations."""

import logging
import uuid
from typing import Callable, Dict

from repositories.conversation import ConversationRepo
from utils.database_pool import DatabasePoolMixin
from wss.receiver.client_events import (
    DeleteConversationRequest,
    ListConversationsForAgentRequest,
    ResumeConversationRequest,
)
from wss.schema import SocketIOHandler
from wss.sender import send_event
from wss.sender.events import ResponseEvent

logger = logging.getLogger(__name__)


class ConversationHandler(DatabasePoolMixin, SocketIOHandler):
    """Read, list, and soft-delete conversations owned by the current user."""

    def get_events(self) -> Dict[str, Callable]:
        return {
            "conversation:resume": self.handle_resume,
            "conversation:delete": self.handle_delete,
            "conversation:list_for_agent": self.handle_list_for_agent,
        }

    async def _user_id(self, sid: str):
        session = await self.sio.get_session(sid)
        return session.get("user_id") if session else None

    async def handle_resume(self, sid: str, data: ResumeConversationRequest) -> None:
        request_id = data.request_id or str(uuid.uuid4())
        empty = {"session_id": data.session_id, "messages": [], "workflow_id": None}
        try:
            user_id = await self._user_id(sid)
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(request_id=request_id, data=empty))
                return

            repo = ConversationRepo(await self.get_pool())
            row = await repo.get_for_resume(data.session_id, user_id)
            if row is None:
                await send_event(self.sio, sid, ResponseEvent(request_id=request_id, data=empty))
                return

            events = row.get("events") or []
            if (
                events
                and isinstance(events[-1], dict)
                and events[-1].get("role") == "user"
                and row.get("workflow_id")
                and row.get("node_id")
            ):
                prefix = f"ck:{row['workflow_id']}:{row['node_id']}:"
                if data.session_id.startswith(prefix):
                    from nodes.agent.interrupted_turns import resolve_interrupted_chat_turn

                    healed = await resolve_interrupted_chat_turn(
                        await self.get_pool(),
                        conversation_id=data.session_id,
                        workflow_id=str(row["workflow_id"]),
                        node_id=str(row["node_id"]),
                        conversation_key=data.session_id[len(prefix):],
                        owner_user_id=user_id,
                    )
                    if healed:
                        row = await repo.get_for_resume(data.session_id, user_id) or row
                        events = row.get("events") or []

            await send_event(
                self.sio,
                sid,
                ResponseEvent(
                    request_id=request_id,
                    data={
                        "session_id": data.session_id,
                        "messages": events,
                        "workflow_id": row.get("workflow_id"),
                    },
                ),
            )
        except Exception as exc:
            logger.error("Could not resume conversation", exc_info=True)
            await send_event(
                self.sio,
                sid,
                ResponseEvent(request_id=request_id, data=empty, error=str(exc)),
            )

    async def handle_delete(self, sid: str, data: DeleteConversationRequest) -> None:
        request_id = data.request_id or str(uuid.uuid4())
        try:
            user_id = await self._user_id(sid)
            if not user_id:
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(request_id=request_id, data={"success": False}, error="Not authenticated"),
                )
                return

            deleted_id = await ConversationRepo(await self.get_pool()).soft_delete(
                data.conversation_id, user_id
            )
            await send_event(
                self.sio,
                sid,
                ResponseEvent(
                    request_id=request_id,
                    data={"success": bool(deleted_id), "conversation_id": data.conversation_id},
                    error=None if deleted_id else "Conversation not found",
                ),
            )
        except Exception as exc:
            logger.error("Could not delete conversation", exc_info=True)
            await send_event(
                self.sio,
                sid,
                ResponseEvent(request_id=request_id, data={"success": False}, error=str(exc)),
            )

    async def handle_list_for_agent(
        self, sid: str, data: ListConversationsForAgentRequest
    ) -> None:
        request_id = data.request_id or str(uuid.uuid4())
        empty = {"conversations": []}
        try:
            user_id = await self._user_id(sid)
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(request_id=request_id, data=empty))
                return

            prefix = f"ck:{data.workflow_id}:{data.node_id}:"
            rows = await ConversationRepo(await self.get_pool()).list_for_agent(
                user_id, data.workflow_id, data.node_id, prefix + "%"
            )
            conversations = []
            for row in rows:
                conversation_id = row["conversation_id"]
                key = (
                    conversation_id[len(prefix):]
                    if conversation_id.startswith(prefix)
                    else conversation_id
                )
                conversations.append(
                    {
                        "conversation_id": conversation_id,
                        "conversation_key": key,
                        "title": row.get("title") or "",
                        "preview": row.get("preview") or "",
                        "agent_model": row.get("agent_model"),
                        "last_activity": row["last_activity"].isoformat()
                        if row.get("last_activity")
                        else "",
                        "created_at": row["created_at"].isoformat()
                        if row.get("created_at")
                        else "",
                        "turn_count": row.get("turn_count") or 0,
                        "shared": key.startswith("share:"),
                    }
                )

            await send_event(
                self.sio,
                sid,
                ResponseEvent(request_id=request_id, data={"conversations": conversations}),
            )
        except Exception as exc:
            logger.error("Could not list agent conversations", exc_info=True)
            await send_event(
                self.sio,
                sid,
                ResponseEvent(request_id=request_id, data=empty, error=str(exc)),
            )
