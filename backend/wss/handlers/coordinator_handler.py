"""
Account coordinator (web transport).

coordinator:open hands the client the account's one conversation id and
the other ways into it (the number it answers on, its email address and
whether mail to it is taken; coordinator:email:inbound turns that on or off),
coordinator:send runs a turn that streams the usual chat:message frames (with
any files and references the composer added), and coordinator:reset starts the
thread over. coordinator:attachment:upload_url reserves a file the composer
uploads straight to storage; coordinator:attachments:list offers the ones sent
before; coordinator:jobs reads back the work its turns started and
coordinator:alarms the reminders they set (for the chat's live cards);
coordinator:arrival posts the setup note for a workflow the owner started on a
public page. Gated on the coordinator rollout; the turn itself lives in
coder/coordinator/agent.py so channels can share it.
"""

import logging
import uuid
from typing import Any, Awaitable, Callable, Dict, Optional

from coder.coordinator import agent as coordinator
from coder.coordinator import attachments
from coder.coordinator.email_channel import (
    CoordinatorEmailError,
    email_reach,
    ensure_coordinator_address,
    set_coordinator_address,
    set_inbound_email,
)
from coder.coordinator.web_input import web_turn_input
from repositories.coordinator_jobs import CoordinatorJobRepo
from repositories.coordinator_memories import CoordinatorMemoryRepo, MemoryConflict
from utils.activity import signal_activity
from coder.workflow.builder_config import missing_brain_key
from utils.capabilities import ACCOUNT_AGENT, capability
from utils.database_pool import DatabasePoolMixin
from utils.sendblue import line_number
from utils.whatsapp_cloud_api import display_number
from wss.handlers.workflow_handler import get_user_org_context
from utils.feature_gates import FeatureNotAvailable, require_feature
from wss.receiver.client_events import (
    CoordinatorArrivalRequest,
    CoordinatorAttachmentsListRequest,
    CoordinatorAttachmentUploadUrlRequest,
    CoordinatorEmailEnsureRequest,
    CoordinatorEmailInboundRequest,
    CoordinatorEmailSetRequest,
    CoordinatorMemoriesListRequest,
    CoordinatorMemoryGetRequest,
    CoordinatorMemorySaveRequest,
    CoordinatorMemoryDeleteRequest,
    CoordinatorAlarmsRequest,
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


class ModelKeyMissing(Exception):
    """The instance holds no key for the model the coordinator runs on (a self-hosted install before one is added)."""

    def __init__(self, env_var: str):
        super().__init__(f"Chat needs this instance's {env_var}. Add it to start.")
        self.env_var = env_var


def model_key_missing() -> Optional[str]:
    """The key the coordinator's model needs and this instance lacks, else None."""
    missing = missing_brain_key(coordinator.COORDINATOR_MODEL)
    return missing[0] if missing else None


class AnsweredByAgent(Exception):
    """The account's owner is answered by an agent in the coordinator's place: its chat talks to that agent."""

    def __init__(self, agent: Dict[str, Any]):
        super().__init__("Your assistant answers in its own conversation now.")
        self.agent = agent


async def account_agent(pool, user_id: str, *, ensure: bool = False, timezone: Optional[str] = None):
    """The agent answering the account's owner in the coordinator's place (``ACCOUNT_AGENT``), or None."""
    agent = capability(ACCOUNT_AGENT)
    return await agent(pool, user_id, ensure=ensure, timezone=timezone) if agent else None


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
            "coordinator:alarms": self.handle_alarms,
            "coordinator:arrival": self.handle_arrival,
            "coordinator:email:ensure": self.handle_email_ensure,
            "coordinator:email:set": self.handle_email_set,
            "coordinator:email:inbound": self.handle_email_inbound,
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
        except ModelKeyMissing as e:
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id, data={"kind": "instance_key", "env_var": e.env_var}, error=str(e)))
        except AnsweredByAgent as e:
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id, data={"kind": "agent", "agent": e.agent}, error=str(e)))
        except MemoryConflict as e:
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id, data={"kind": "conflict"}, error=str(e)))
        except CoordinatorEmailError as e:
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id, data={"kind": "email"}, error=str(e)))
        except FeatureNotAvailable as e:
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id, data={"kind": "gated"}, error=str(e)))
        except Exception as e:
            logger.error(f"[Coordinator] request failed: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id, data=None, error=str(e)))

    async def handle_open(self, sid: str, request: CoordinatorOpenRequest) -> None:
        async def op(user_id: str, _email):
            pool = await self.get_pool()
            # The agent that answers instead, when the account has one: the chat talks to it over /v1, and its clock
            # is where this browser is.
            agent = await account_agent(pool, user_id, ensure=True, timezone=request.timezone)
            return {
                "conversation_id": coordinator.conversation_id_for(user_id),
                "model": coordinator.COORDINATOR_MODEL,
                **({"agent": agent} if agent else {}),
                # The key the chat asks for first, where the instance has none for the coordinator's model.
                **({"needs_key": needs_key} if (needs_key := model_key_missing()) else {}),
                # The other ways into this same conversation.
                "reach": {
                    "phone": display_number(),
                    "imessage": line_number(),
                    **await email_reach(pool, user_id),
                },
            }
        await self._respond(sid, request.request_id, op)

    async def handle_send(self, sid: str, request: CoordinatorSendRequest) -> None:
        async def op(user_id: str, email):
            text = request.text.strip()
            if not (text or request.attachment_ids or request.references):
                raise ValueError("message is empty")
            pool = await self.get_pool()
            # A page that never opened the chat (an older one) still reaches the agent, made here if need be.
            if agent := await account_agent(pool, user_id, ensure=True):
                raise AnsweredByAgent(agent)
            if env_var := model_key_missing():
                raise ModelKeyMissing(env_var)
            allowed, limit_error = await plan_allows_turn(pool, user_id)
            if not allowed:
                raise ValueError(limit_error)
            signal_activity(user_id, "chat", {"text": text, "files": len(request.attachment_ids)}, key="chat")
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
            if agent := await account_agent(pool, user_id, ensure=True):
                raise AnsweredByAgent(agent)
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
            from coder.coordinator.jobs import job_entry

            ids = [str(uuid.UUID(job_id)) for job_id in request.job_ids]
            rows = await CoordinatorJobRepo(await self.get_pool()).list_by_ids(user_id, ids)
            return {"jobs": [job_entry(row) for row in rows]}
        await self._respond(sid, request.request_id, op)

    async def handle_alarms(self, sid: str, request: CoordinatorAlarmsRequest) -> None:
        async def op(user_id: str, _email):
            from repositories.coordinator_alarms import CoordinatorAlarmRepo

            ids = [str(uuid.UUID(schedule_id)) for schedule_id in request.schedule_ids]
            return {"alarms": await CoordinatorAlarmRepo(await self.get_pool()).read(user_id, ids)}
        await self._respond(sid, request.request_id, op)

    async def handle_email_ensure(self, sid: str, request: CoordinatorEmailEnsureRequest) -> None:
        async def op(user_id: str, _email):
            return {"address": await ensure_coordinator_address(await self.get_pool(), user_id)}
        await self._respond(sid, request.request_id, op)

    async def handle_email_set(self, sid: str, request: CoordinatorEmailSetRequest) -> None:
        async def op(user_id: str, _email):
            return {"address": await set_coordinator_address(await self.get_pool(), user_id, request.name)}
        await self._respond(sid, request.request_id, op)

    async def handle_email_inbound(self, sid: str, request: CoordinatorEmailInboundRequest) -> None:
        async def op(user_id: str, _email):
            return await set_inbound_email(await self.get_pool(), user_id, request.on)
        await self._respond(sid, request.request_id, op)

    async def handle_arrival(self, sid: str, request: CoordinatorArrivalRequest) -> None:
        async def op(user_id: str, _email):
            from coder.coordinator.arrival import post_arrival

            return await post_arrival(
                await self.get_pool(), user_id, workflow_id=str(uuid.UUID(request.workflow_id)), client=request.client,
            )
        await self._respond(sid, request.request_id, op)
