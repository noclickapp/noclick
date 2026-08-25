"""Owner-managed agent links and scope-restricted visitor chat.

Only an owner may create a link. Visitor sessions carry no user identity and
are restricted to their link-scoped events; workflow, node, and conversation
identity resolve from that server-side scope. Executions are attributed through
the installation usage-policy seam.
"""

import asyncio
import logging
from typing import Any, Callable, Dict, Optional

from repositories.conversation import ConversationRepo
from repositories.shared_agent_link import SharedAgentLinkRepo
from repositories.shared_run_link import SharedRunLinkRepo
from repositories.workflow import WorkflowRepo
from utils.database_pool import DatabasePoolMixin
from wss.receiver.client_events import (
    AgentShareGetOrCreateRequest,
    AgentShareRotateRequest,
    AgentShareSetActiveRequest,
    RunShareCreateRequest,
    SharedAgentResumeRequest,
    SharedAgentSendRequest,
    WorkflowExecuteRequest,
)
from wss.schema import SocketIOHandler
from wss.sender import send_event
from wss.sender.events import ResponseEvent
from wss.sender.responses import (
    AgentShareLinkResponse,
    RunShareCreateResponse,
    SharedAgentAckResponse,
    SharedAgentResumeResponse,
)

logger = logging.getLogger(__name__)

_INFLIGHT_TTL_SECONDS = 900  # backstop for crashed runs; agent turns can run minutes
# The lock is held while a message is dispatched, so a held lock means another
# send from the last few seconds is still wrapping up. Wait instead of instant-
# rejecting — read-the-reply-and-send-again landed inside that window and got a
# spurious "busy" (2026-07-18). Bounded well under the FE's 30s request timeout.
_INFLIGHT_WAIT_SECONDS = 8.0
_INFLIGHT_POLL_SECONDS = 0.25


def shared_agent_page_url(link_id: str) -> str:
    """Public chat page URL for a link."""
    from mcp_adapter.auth.endpoints import get_frontend_url

    return f"{get_frontend_url()}/a/{link_id}"


def shared_run_page_url(link_id: str) -> str:
    """Public read-only page URL for a shared Test Run result."""
    from mcp_adapter.auth.endpoints import get_frontend_url

    return f"{get_frontend_url()}/r/{link_id}"


# Display fields only — the snapshot is served verbatim to the public page,
# so the allowlist is what keeps ids/config out of it structurally.
_RUN_SNAPSHOT_KEYS = frozenset({
    "version", "workflowName", "agentName", "scenario",
    "rows", "artifacts", "failed", "reply", "providers",
})
_RUN_SNAPSHOT_MAX_BYTES = 400_000


def derive_shared_conversation(scope: Dict[str, Any], chat_key: str) -> tuple:
    """(conversation_key, conversation_id) for a visitor thread. Must mirror
    AgentNode's ck:{workflow}:{node}:{key} derivation."""
    conversation_key = f"share:{scope['link_id']}:{scope['visitor_id']}:{chat_key}"
    conversation_id = f"ck:{scope['workflow_id']}:{scope['node_id']}:{conversation_key}"
    return conversation_key, conversation_id


def _find_node(workflow_config: Any, node_id: str) -> Optional[Dict[str, Any]]:
    """Locate a node in a stored workflow blob (dict, or legacy JSON string)."""
    config = workflow_config
    if isinstance(config, str):
        import json

        try:
            config = json.loads(config)
        except (ValueError, TypeError):
            return None
    if not isinstance(config, dict):
        return None
    for node in config.get("nodes", []) or []:
        if isinstance(node, dict) and node.get("id") == node_id:
            return node
    return None


def _node_unavailable_reason(node: Optional[Dict[str, Any]]) -> Optional[str]:
    """Why a shared node can't take a visitor turn (None = it can)."""
    if not node or node.get("type") != "agent":
        return "agent_unavailable"
    if node.get("config", {}).get("disabled"):
        return "agent_unavailable"
    return None


class AgentShareHandler(DatabasePoolMixin, SocketIOHandler):
    """Owner-side agent share-link management + anonymous visitor chat."""

    def __init__(self, sio):
        super().__init__(sio)

    def get_events(self) -> Dict[str, Callable]:
        return {
            "agent_share:get_or_create": self.get_or_create_link,
            "agent_share:rotate": self.rotate_link,
            "agent_share:set_active": self.set_link_active,
            "run_share:create": self.create_run_link,
            "shared_agent:send": self.visitor_send,
            "shared_agent:resume": self.visitor_resume,
        }

    # ── Owner-side manage events ────────────────────────────────────────────

    async def _authorize_owner(
        self, sid: str, workflow_id: str, node_id: str
    ) -> tuple:
        """(user_id, error). Requires the session user to be the workflow
        OWNER and the target node to be an agent node in the stored graph."""
        session = await self.sio.get_session(sid)
        user_id = session.get("user_id") if session else None
        if not user_id:
            return None, "Not authenticated"

        pool = await self.get_pool()
        owner_id = await WorkflowRepo(pool).get_owner_id(workflow_id)
        if not owner_id or str(owner_id) != str(user_id):
            return None, "Only the workflow owner can manage share links"

        async with pool.acquire() as conn:
            import uuid as uuid_module

            row = await WorkflowRepo(pool).get_workflow_org_and_data(
                conn, uuid_module.UUID(workflow_id)
            )
        node = _find_node(row["workflow"] if row else None, node_id)
        if not node or node.get("type") != "agent":
            return None, "Node is not an agent node in this workflow"
        return str(user_id), None

    async def _respond_link(self, sid: str, request_id: Optional[str], **kwargs) -> None:
        await send_event(self.sio, sid, ResponseEvent(
            request_id=request_id or "",
            data=AgentShareLinkResponse(**kwargs).model_dump(),
        ))

    async def get_or_create_link(self, sid: str, data: AgentShareGetOrCreateRequest) -> None:
        try:
            user_id, error = await self._authorize_owner(sid, data.workflow_id, data.node_id)
            if error:
                await self._respond_link(sid, data.request_id, success=False, error=error)
                return
            repo = SharedAgentLinkRepo(await self.get_pool())
            link = await repo.get_or_create(user_id, data.workflow_id, data.node_id)
            await self._respond_link(
                sid, data.request_id, success=True,
                link_id=link["link_id"], url=shared_agent_page_url(link["link_id"]),
                is_active=link["is_active"],
            )
        except Exception as e:
            logger.error(f"[AgentShare] get_or_create failed: {e}", exc_info=True)
            await self._respond_link(sid, data.request_id, success=False, error="Failed to create share link")

    async def rotate_link(self, sid: str, data: AgentShareRotateRequest) -> None:
        try:
            user_id, error = await self._authorize_owner(sid, data.workflow_id, data.node_id)
            if error:
                await self._respond_link(sid, data.request_id, success=False, error=error)
                return
            repo = SharedAgentLinkRepo(await self.get_pool())
            link = await repo.rotate(user_id, data.workflow_id, data.node_id)
            await self._respond_link(
                sid, data.request_id, success=True,
                link_id=link["link_id"], url=shared_agent_page_url(link["link_id"]),
                is_active=link["is_active"],
            )
        except Exception as e:
            logger.error(f"[AgentShare] rotate failed: {e}", exc_info=True)
            await self._respond_link(sid, data.request_id, success=False, error="Failed to rotate share link")

    async def set_link_active(self, sid: str, data: AgentShareSetActiveRequest) -> None:
        try:
            user_id, error = await self._authorize_owner(sid, data.workflow_id, data.node_id)
            if error:
                await self._respond_link(sid, data.request_id, success=False, error=error)
                return
            repo = SharedAgentLinkRepo(await self.get_pool())
            if not await repo.set_active(data.workflow_id, data.node_id, data.is_active):
                await self._respond_link(sid, data.request_id, success=False, error="No share link exists for this agent")
                return
            link = await repo.get_or_create(user_id, data.workflow_id, data.node_id)
            await self._respond_link(
                sid, data.request_id, success=True,
                link_id=link["link_id"], url=shared_agent_page_url(link["link_id"]),
                is_active=link["is_active"],
            )
        except Exception as e:
            logger.error(f"[AgentShare] set_active failed: {e}", exc_info=True)
            await self._respond_link(sid, data.request_id, success=False, error="Failed to update share link")

    # ── Shared run links (/r/{id}) ──────────────────────────────────────────
    # A STATIC snapshot of a finished Test Run — nothing executes through it,
    # so the gate is workflow ownership only (no agent-node check). The
    # snapshot is allowlisted to display fields at mint: whatever the FE ever
    # sends, ids and future stray keys never reach the public page.

    async def create_run_link(self, sid: str, data: RunShareCreateRequest) -> None:
        def respond(**kwargs):
            return send_event(self.sio, sid, ResponseEvent(
                request_id=data.request_id or "",
                data=RunShareCreateResponse(**kwargs).model_dump(),
            ))

        try:
            session = await self.sio.get_session(sid)
            user_id = session.get("user_id") if session else None
            if not user_id:
                await respond(success=False, error="Not authenticated")
                return
            pool = await self.get_pool()
            owner_id = await WorkflowRepo(pool).get_owner_id(data.workflow_id)
            if not owner_id or str(owner_id) != str(user_id):
                await respond(success=False, error="Only the workflow owner can share run results")
                return
            snapshot = {
                k: v for k, v in (data.snapshot or {}).items()
                if k in _RUN_SNAPSHOT_KEYS
            }
            if not snapshot.get("scenario") or not isinstance(snapshot.get("rows"), list):
                await respond(success=False, error="Nothing to share yet — run a test first")
                return
            import json as _json
            if len(_json.dumps(snapshot)) > _RUN_SNAPSHOT_MAX_BYTES:
                await respond(success=False, error="This run is too large to share")
                return
            link_id = await SharedRunLinkRepo(pool).create(
                str(user_id), data.workflow_id, data.title or "", snapshot
            )
            await respond(success=True, link_id=link_id, url=shared_run_page_url(link_id))
        except Exception as e:
            logger.error(f"[RunShare] create failed: {e}", exc_info=True)
            await respond(success=False, error="Failed to create run link")

    # ── Visitor events (restricted share-scope sessions) ────────────────────

    async def _visitor_scope(self, sid: str) -> Optional[Dict[str, Any]]:
        session = await self.sio.get_session(sid)
        scope = session.get("share_scope") if session else None
        return scope if isinstance(scope, dict) else None

    async def visitor_send(self, sid: str, data: SharedAgentSendRequest) -> None:
        async def ack(**kwargs):
            await send_event(self.sio, sid, ResponseEvent(
                request_id=data.request_id or "",
                data=SharedAgentAckResponse(**kwargs).model_dump(),
            ))

        scope = await self._visitor_scope(sid)
        if not scope:
            await ack(accepted=False, error="link_inactive")
            return

        pool = await self.get_pool()
        # Re-load the link so revocation (rotate / set_active) applies to
        # already-connected sockets on their next send.
        link = await SharedAgentLinkRepo(pool).load_for_visit(scope["link_id"])
        if not link:
            await ack(accepted=False, error="link_inactive")
            return

        node = _find_node(link["workflow_config"], scope["node_id"])
        unavailable = _node_unavailable_reason(node)
        if unavailable:
            await ack(accepted=False, error=unavailable)
            return

        conversation_key, conversation_id = derive_shared_conversation(scope, data.chat_key)

        # One in-flight turn per visitor thread. Fail-open on Redis errors —
        # this is a concurrency guard, not spend protection (the owner's
        # credit gates own that).
        lock_key = f"nc:shared:inflight:{conversation_id}"
        lock_acquired = False
        redis = None
        try:
            from utils.redis_client import get_shared_redis

            redis = get_shared_redis()
            if redis is not None:
                deadline = asyncio.get_event_loop().time() + _INFLIGHT_WAIT_SECONDS
                while True:
                    lock_acquired = bool(await redis.set(lock_key, "1", nx=True, ex=_INFLIGHT_TTL_SECONDS))
                    if lock_acquired or asyncio.get_event_loop().time() >= deadline:
                        break
                    await asyncio.sleep(_INFLIGHT_POLL_SECONDS)
                if not lock_acquired:
                    await ack(accepted=False, error="busy")
                    return
        except Exception as e:
            logger.warning(f"[AgentShare] in-flight lock unavailable ({e}); proceeding")
            redis = None

        try:
            await ack(accepted=True, conversation_id=conversation_id)

            # DB-fetch mode: the executor re-fetches the OWNER's saved graph
            # (check_resource_access passes for the owner) and merges the
            # one-shot override; the visitor never supplies graph or model.
            request = WorkflowExecuteRequest(
                request_id=data.request_id or f"shared-{scope['link_id'][:8]}",
                workflow_id=scope["workflow_id"],
                start_node_id=scope["node_id"],
                trigger_source="shared_agent",
                conversation_id=conversation_id,
                config_overrides={
                    scope["node_id"]: {
                        "message": data.text,
                        "conversation_key": conversation_key,
                        # Neutralize stale canvas mocks — a visitor turn must
                        # never replay a mocked output (check is `is not None`).
                        "mockedOutput": None,
                    }
                },
            )
            execution_handler = self._get_execution_handler()
            await execution_handler.handle_execute(
                sid=sid, request=request, caller_user_id=str(link["user_id"])
            )
        finally:
            if redis is not None and lock_acquired:
                try:
                    await redis.delete(lock_key)
                except Exception:
                    logger.warning(f"[AgentShare] failed to release in-flight lock {lock_key}")
            try:
                await SharedAgentLinkRepo(pool).touch_usage(scope["link_id"])
            except Exception:
                logger.warning(f"[AgentShare] touch_usage failed for {scope['link_id']}")

    async def visitor_resume(self, sid: str, data: SharedAgentResumeRequest) -> None:
        async def respond(**kwargs):
            await send_event(self.sio, sid, ResponseEvent(
                request_id=data.request_id or "",
                data=SharedAgentResumeResponse(**kwargs).model_dump(),
            ))

        try:
            scope = await self._visitor_scope(sid)
            if not scope:
                await respond(messages=[], error="link_inactive")
                return

            pool = await self.get_pool()
            link = await SharedAgentLinkRepo(pool).load_for_visit(scope["link_id"])
            if not link:
                await respond(messages=[], error="link_inactive")
                return

            # The conversation id embeds the link + visitor ids from the
            # session scope — no other thread is derivable, so this can only
            # ever return the visitor's own history (stored under the owner).
            conversation_key, conversation_id = derive_shared_conversation(scope, data.chat_key)
            repo = ConversationRepo(pool)
            owner_id = str(link["user_id"])
            row = await repo.get_for_resume(conversation_id, owner_id)
            events = row["events"] if row else []

            # Visitors get no live frames or presence beats — this resume poll
            # is their ONLY liveness signal. A user-tail conversation whose
            # backing run died without terminal evidence (worker killed
            # mid-dispatch) would lock their composer forever, so self-heal it
            # here; the poll that follows adopts the persisted interruption.
            if events and (events[-1] or {}).get("role") == "user":
                from nodes.agent.interrupted_turns import resolve_interrupted_chat_turn

                healed = await resolve_interrupted_chat_turn(
                    pool,
                    conversation_id=conversation_id,
                    workflow_id=str(scope["workflow_id"]),
                    node_id=str(scope["node_id"]),
                    conversation_key=conversation_key,
                    owner_user_id=owner_id,
                )
                if healed:
                    row = await repo.get_for_resume(conversation_id, owner_id)
                    events = row["events"] if row else events

            await respond(
                conversation_id=conversation_id,
                messages=events,
            )
        except Exception as e:
            logger.error(f"[AgentShare] resume failed: {e}", exc_info=True)
            await respond(messages=[], error="link_inactive")

    def _get_execution_handler(self):
        from wss.receiver.event_routing import Handler
        from wss.receiver.receiver import get_receiver_instance

        receiver = get_receiver_instance()
        handler = receiver.handler_instances.get(Handler.WORKFLOW_EXECUTION) if receiver else None
        if handler is None:
            raise RuntimeError("WorkflowExecutionHandler unavailable")
        return handler
