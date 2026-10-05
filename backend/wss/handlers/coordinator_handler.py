"""
Account coordinator (web transport).

coordinator:open hands the client the account's one conversation id and
the other ways into it (the number it answers on, its email address),
coordinator:send runs a turn that streams the usual chat:message frames (with
any files and references the composer added), and coordinator:reset starts the
thread over. coordinator:attachment:upload_url reserves a file the composer
uploads straight to storage; coordinator:attachments:list offers the ones sent
before; coordinator:jobs reads back the work its turns started (for the chat's
live cards). Gated on the coordinator rollout; the turn itself lives in
coder/coordinator/agent.py so channels can share it.
"""

import logging
import uuid
from typing import Any, Awaitable, Callable, Dict

from coder.coordinator import agent as coordinator
from coder.coordinator import attachments
from coder.coordinator.email_channel import coordinator_address
from coder.coordinator.web_input import web_turn_input
from repositories.coordinator_jobs import CoordinatorJobRepo
from repositories.coordinator_memories import CoordinatorMemoryRepo, MemoryConflict
from utils.capabilities import COORDINATOR_IMESSAGE, COORDINATOR_NUMBER, capability
from utils.database_pool import DatabasePoolMixin
from wss.handlers.workflow_handler import get_user_org_context
from utils.feature_gates import FeatureNotAvailable, require_feature
from wss.receiver.client_events import (
    CoordinatorAttachmentsListRequest,
    CoordinatorAttachmentUploadUrlRequest,
    CoordinatorMemoriesListRequest,
    CoordinatorMemoryGetRequest,
    CoordinatorMemorySaveRequest,
    CoordinatorMemoryDeleteRequest,
    CoordinatorJobsRequest,
    CoordinatorOpenRequest,
    CoordinatorResetRequest,
    CoordinatorSendRequest,
)
from wss.schema import SocketIOHandler
from wss.sender import send_event
from wss.sender.events import ResponseEvent
from wss.session_actor import session_actor

logger = logging.getLogger(__name__)


async def plan_allows_turn(pool, user_id: str):
    """The daily AI cap the interactive chat and the builder honour."""
    from billing.plan_limits import check_ai_builder_limit

    async with pool.acquire() as conn:
        return await check_ai_builder_limit(conn, user_id)


class CoordinatorHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for the account coordinator's web conversation"""

    def get_events(self) -> Dict[str, Callable]:
        return {
            "coordinator:open": self.handle_open,
            "coordinator:send": self.handle_send,
            "coordinator:attachment:upload_url": self.handle_attachment_upload_url,
            "coordinator:attachments:list": self.handle_attachments_list,
            "coordinator:reset": self.handle_reset,
            "coordinator:memories:list": self.handle_memories_list,
            "coordinator:memories:get": self.handle_memory_get,
            "coordinator:memories:save": self.handle_memory_save,
            "coordinator:memories:delete": self.handle_memory_delete,
            "coordinator:jobs": self.handle_jobs,
        }

    async def _respond(self, sid: str, request_id: str, op: Callable[[str, Any], Awaitable[Any]]) -> None:
        try:
            actor = await session_actor(self.sio, sid)
            if actor is None:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id, data=None, error="Not authenticated"))
                return
            user_id, email = actor
            require_feature(coordinator.COORDINATOR_FEATURE, email=email)
            data = await op(user_id, email)
            await send_event(self.sio, sid, ResponseEvent(request_id=request_id, data=data))
        except MemoryConflict as e:
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id, data={"kind": "conflict"}, error=str(e)))
        except FeatureNotAvailable as e:
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id, data={"kind": "gated"}, error=str(e)))
        except Exception as e:
            logger.error(f"[Coordinator] request failed: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id, data=None, error=str(e)))

    async def handle_open(self, sid: str, request: CoordinatorOpenRequest) -> None:
        async def op(user_id: str, _email):
            number, imessage = capability(COORDINATOR_NUMBER), capability(COORDINATOR_IMESSAGE)
            return {
                "conversation_id": coordinator.conversation_id_for(user_id),
                "model": coordinator.COORDINATOR_MODEL,
                # The other ways into this same conversation.
                "reach": {
                    "phone": number() if number else None,
                    "imessage": imessage() if imessage else None,
                    "email": await coordinator_address(await self.get_pool(), user_id),
                },
            }
        await self._respond(sid, request.request_id, op)

    async def handle_send(self, sid: str, request: CoordinatorSendRequest) -> None:
        async def op(user_id: str, email):
            text = request.text.strip()
            if not (text or request.attachment_ids or request.references):
                raise ValueError("message is empty")
            pool = await self.get_pool()
            allowed, limit_error = await plan_allows_turn(pool, user_id)
            if not allowed:
                raise ValueError(limit_error)
            extras = {}
            if request.attachment_ids or request.references:
                prepare_input, user_event = await web_turn_input(
                    pool, user_id=user_id, text=text,
                    attachment_ids=request.attachment_ids, references=request.references,
                )
                extras = {"prepare_input": prepare_input, "user_event": user_event}
            await coordinator.run_coordinator_turn(
                sio=self.sio, sid=sid, user_id=user_id, user_email=email, text=text, **extras,
            )
            return {"ok": True}
        await self._respond(sid, request.request_id, op)

    async def handle_attachment_upload_url(self, sid: str, request: CoordinatorAttachmentUploadUrlRequest) -> None:
        async def op(user_id: str, _email):
            pool = await self.get_pool()
            async with pool.acquire() as conn:
                organization_id = await get_user_org_context(conn, user_id)
            return await attachments.start_upload(
                pool, user_id=user_id, organization_id=organization_id,
                name=request.name, mime_type=request.mime_type, size_bytes=request.size_bytes,
            )
        await self._respond(sid, request.request_id, op)

    async def handle_attachments_list(self, sid: str, request: CoordinatorAttachmentsListRequest) -> None:
        async def op(user_id: str, _email):
            return await attachments.list_account_attachments(
                await self.get_pool(), user_id, query=request.query, limit=request.limit,
            )
        await self._respond(sid, request.request_id, op)

    async def handle_reset(self, sid: str, request: CoordinatorResetRequest) -> None:
        async def op(user_id: str, _email):
            from repositories.coordinator_wakeups import CoordinatorWakeupRepo, coordinator_lock

            pool = await self.get_pool()
            async with coordinator_lock(pool, user_id):
                return {"reset": await CoordinatorWakeupRepo(pool).reset(user_id)}
        await self._respond(sid, request.request_id, op)

    async def handle_memories_list(self, sid: str, request: CoordinatorMemoriesListRequest) -> None:
        async def op(user_id: str, _email):
            return await CoordinatorMemoryRepo(await self.get_pool()).list_headers(
                user_id, query=request.query, offset=request.offset,
            )
        await self._respond(sid, request.request_id, op)

    async def handle_memory_get(self, sid: str, request: CoordinatorMemoryGetRequest) -> None:
        async def op(user_id: str, _email):
            return {"memory": await CoordinatorMemoryRepo(await self.get_pool()).get(user_id, request.memory_id)}
        await self._respond(sid, request.request_id, op)

    async def handle_memory_save(self, sid: str, request: CoordinatorMemorySaveRequest) -> None:
        async def op(user_id: str, _email):
            return {"memory": await CoordinatorMemoryRepo(await self.get_pool()).save(user_id, request.memory)}
        await self._respond(sid, request.request_id, op)

    async def handle_memory_delete(self, sid: str, request: CoordinatorMemoryDeleteRequest) -> None:
        async def op(user_id: str, _email):
            return await CoordinatorMemoryRepo(await self.get_pool()).delete(
                user_id, request.memory_id, request.expected_version,
            )
        await self._respond(sid, request.request_id, op)

    async def handle_jobs(self, sid: str, request: CoordinatorJobsRequest) -> None:
        async def op(user_id: str, _email):
            from coder.coordinator.jobs import job_view

            ids = [str(uuid.UUID(job_id)) for job_id in request.job_ids]
            rows = await CoordinatorJobRepo(await self.get_pool()).list_by_ids(user_id, ids)
            # The coordinator's own view of each job, and when it started and last moved for the card's clock.
            return {"jobs": [{**job_view(row), "created_at": row["created_at"].isoformat(),
                              "updated_at": row["updated_at"].isoformat()} for row in rows]}
        await self._respond(sid, request.request_id, op)
