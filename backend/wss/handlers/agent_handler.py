"""Socket.io handler for agent chat surfaces: proposal verdicts, pauses, warm
sandbox counts, and the emit/persist plumbing the coordinator's chat reuses."""

import logging
from datetime import datetime, timezone
from typing import Dict, Callable, Optional, List, Any

from wss.schema import SocketIOHandler
from wss.sender import send_event, ChatMessageEvent, AgentStateEvent, ResponseEvent
from wss.receiver.client_events import (
    AgentPauseRequest,
    AgentWarmSandboxesRequest,
    AgentBuilderDecisionRequest,
)
from utils.database_pool import DatabasePoolMixin
from repositories.conversation import ConversationRepo


logger = logging.getLogger(__name__)


class AgentHandler(DatabasePoolMixin, SocketIOHandler):
    """Agent chat events, and the chat transcript plumbing the coordinator shares."""

    def get_events(self) -> Dict[str, Callable]:
        return {
            "agent:pause": self.handle_pause,
            "agent:warm_sandboxes": self.handle_warm_sandboxes,
            "agent:builder_decision": self.handle_builder_decision,
        }

    async def handle_builder_decision(self, sid: str, data: AgentBuilderDecisionRequest) -> None:
        """Persist the user's verdict on a prompt_builder proposal card.

        The verdict lands in conversations.events so (a) the card's decided
        state restores across devices/reloads (source of truth over the old
        localStorage-only memory) and (b) the agent's next turn relays the
        outcome as a platform note (AgentNode._relay_builder_decisions) — the
        agent otherwise answered from its stale 'awaiting approval' tool
        result (2026-07-19)."""
        from datetime import datetime, timezone

        from utils.access_control import Permission, check_resource_access

        async def respond(**payload) -> None:
            await send_event(self.sio, sid, ResponseEvent(
                request_id=data.request_id or "", data=payload,
            ))

        try:
            session = await self.sio.get_session(sid)
            user_id = session.get("user_id") if session else None
            if not user_id:
                await respond(success=False, error="Not authenticated")
                return
            if data.decision not in ("approved", "dismissed"):
                await respond(success=False, error="decision must be 'approved' or 'dismissed'")
                return

            pool = await self.get_pool()
            async with pool.acquire() as conn:
                access = await check_resource_access(
                    conn, str(user_id), "workflow", data.workflow_id
                )
            if not access.has_access:
                await respond(success=False, error="Access denied")
                return
            # Approving hands the proposal to the builder, which edits the workflow.
            if data.decision == "approved" and access.permission not in (Permission.EDIT, Permission.OWNER):
                await respond(success=False, error="Approving a change takes edit access to this workflow")
                return
            # A verdict answers a proposal the agent put in the caller's own
            # conversation about this workflow; anything else names nothing to decide.
            proposal = {"proposal_id": data.proposal_id, **({"node_id": data.node_id} if data.node_id else {})}
            if not await ConversationRepo(pool).holds_event(
                data.conversation_id, str(user_id), data.workflow_id, "builder_prompt", proposal,
            ):
                await respond(success=False, error="No such proposal in this conversation")
                return

            await ConversationRepo(pool).append_chat_event(
                conversation_id=data.conversation_id,
                user_id=str(user_id),
                workflow_id=data.workflow_id,
                node_id=data.node_id,
                event={
                    "builder_decision": {
                        "proposal_id": data.proposal_id,
                        "decision": data.decision,
                        "node_id": data.node_id,
                    },
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
                label=None,
                model=None,
            )
            await respond(success=True)
        except Exception as e:
            logger.warning(f"handle_builder_decision failed for sid {sid}: {e}", exc_info=True)
            await respond(success=False, error="Failed to record decision")

    async def handle_warm_sandboxes(self, sid: str, data: AgentWarmSandboxesRequest) -> None:
        """Return the live warm-sandbox count per agent node for a workflow's
        canvas (polled ~30s by the FE). Reads the TTL-fresh Redis registry the
        in-sandbox uptime reporter maintains; counts distinct conversations
        (session_keys) per node — a node can hold several warm sandboxes at once."""
        counts: Dict[str, int] = {}
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get("user_id") if session else None
            if user_id:
                from utils.capabilities import WARM_SANDBOX_LIST, capability

                list_active_sandboxes = capability(WARM_SANDBOX_LIST)
                if list_active_sandboxes is not None:
                    for entry in await list_active_sandboxes(user_id=user_id):
                        node_id = entry.get("node_id")
                        if node_id and entry.get("workflow_id") == data.workflow_id:
                            counts[node_id] = counts.get(node_id, 0) + 1
        except Exception as e:
            logger.warning(f"handle_warm_sandboxes failed for sid {sid}: {e}", exc_info=True)
        await send_event(self.sio, sid, ResponseEvent(request_id=data.request_id, data={"counts": counts}))

    async def handle_pause(self, sid: str, data: AgentPauseRequest) -> None:
        """Stop the caller's builder run in this conversation (its CancelScope in
        cancellation._ACTIVE_BUILDER_SCOPES). Only the run's own user (or, for a
        scope that names none, the conversation's owner) can stop it; a check
        that can't be made stops nothing."""
        conversation_id = data.conversation_id

        from utils.cancellation import builder_scope_owner, get_builder_scope
        builder_scope = get_builder_scope(conversation_id) if conversation_id else None
        if not builder_scope:
            logger.warning(f"Pause requested for conversation {conversation_id} but no builder is active")
            return

        try:
            session = await self.sio.get_session(sid)
            user_id = session.get("user_id") if session else None
            # The run's own user may stop it before its conversation row is written.
            owner_id = builder_scope_owner(conversation_id)
            if user_id and owner_id is None:
                owner_id = await ConversationRepo(await self.get_pool()).owner_id(conversation_id)
        except Exception:
            logger.exception(f"Pause for conversation {conversation_id}: owner check failed")
            return
        if not user_id or owner_id != str(user_id):
            logger.warning(f"Pause for conversation {conversation_id} refused: not the caller's")
            return

        builder_scope.cancel()
        logger.info(f"[AgentHandler] Cancelled builder run for conversation {conversation_id}")
        try:
            await send_event(self.sio, sid, AgentStateEvent(state='paused', conversation_id=conversation_id))
        except Exception as exc:
            logger.error(f"Failed to send paused state for conversation {conversation_id}: {exc}")

    async def _persist_chat_event(
        self,
        *,
        conversation_id: str,
        user_id: str,
        workflow_id: Optional[str],
        node_id: Optional[str],
        source: str,
        content: str,
        model: Optional[str],
        label: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Append one chat event to ``conversations.events``.

        Matches the ``PersistedMessage`` shape ``mapPersistedMessage``
        on the frontend reads — ``{role, message, ...}``. The
        ``action/source/args.content`` shape OpenHands' PostgresStore
        used to write is NOT what the current chat UI consumes; the
        ``useConversation`` + ``ChatHistory`` paths both call
        ``mapPersistedMessage`` which keys on ``role === 'user'`` and
        reads ``msg.message`` for the text body. Writing the legacy
        shape lands the row in Postgres but the bubble never renders
        on restore.

        ``label`` is non-null only for the FIRST user message in a
        conversation — the upsert's COALESCE locks ``title``/``preview``
        on first non-empty write, so subsequent calls with label=None
        leave them alone.
        """
        # ``source`` is 'user' or 'agent' on the caller side (mirrors
        # OpenHands' nomenclature); the FE shape uses 'user' / 'assistant'.
        role = "user" if source == "user" else "assistant"

        event = {
            "role": role,
            "message": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if role == "assistant":
            # Attach the turn's compacted tool timeline so the chat's step rows
            # survive reloads — the CLI path already did this; the
            # in-process SDK path skipping it left refreshed transcripts
            # stepless (2026-07-19). Same shared boundary gather as the
            # callback, so the window advances once per response either way.
            from utils.tool_call_log import (
                compact_tool_calls_for_transcript,
                gather_turn_tool_calls,
            )

            calls = await gather_turn_tool_calls(
                node_id=node_id, conversation_id=conversation_id,
            )
            compact = compact_tool_calls_for_transcript(calls) or None
            if compact:
                event["tool_calls"] = compact
        if extra:
            # Where the turn came from (e.g. a voice call), for surfaces that badge it.
            event.update(extra)
        try:
            # Awaiting (vs fire-and-forget) is critical here: each chat
            # message produces TWO writes in quick succession (user message
            # + agent reply), and a fire-and-forget write loses ordering.
            # With await each write completes before the next is enqueued,
            # so events land in their emit order.
            repo = ConversationRepo(await self.get_pool())
            await repo.append_chat_event(
                conversation_id=conversation_id,
                user_id=user_id,
                workflow_id=workflow_id,
                node_id=node_id,
                event=event,
                label=label,
                model=model,
            )
        except Exception as e:
            # Persistence failure should never break the live chat flow.
            # Log loudly so the chat-history regression is detectable.
            logger.warning(
                f"[AGENT_HANDLER] Failed to persist {source} event "
                f"for conversation {conversation_id}: {e}"
            )

    async def _persist_chat_error(
        self,
        *,
        conversation_id: str,
        user_id: str,
        workflow_id: Optional[str],
        node_id: Optional[str],
        reason: str,
        model: Optional[str],
    ) -> None:
        """Record a terminal error as an assistant message with
        ``cancelled: true`` — ``mapPersistedMessage`` translates that to
        ``wasInterrupted: true`` which renders the "Response interrupted"
        notice on the bubble.
        """
        event = {
            "role": "assistant",
            "message": reason,
            "cancelled": True,
        }
        try:
            repo = ConversationRepo(await self.get_pool())
            await repo.append_chat_event(
                conversation_id=conversation_id,
                user_id=user_id,
                workflow_id=workflow_id,
                node_id=node_id,
                event=event,
                label=None,  # don't set title/preview on an error event
                model=model,
            )
        except Exception as e:
            logger.warning(
                f"[AGENT_HANDLER] Failed to persist error event "
                f"for conversation {conversation_id}: {e}"
            )

    async def _create_emit_callback(
        self,
        sid: str,
        model: str,
        *,
        conversation_id: str,
        user_id: Optional[str],
        workflow_id: Optional[str],
        node_id: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
        mirror_to_user: bool = False,
    ):
        """Create an emit callback for a specific session.

        Side effects beyond forwarding to the socket:
          - Accumulate streaming chunks (``finished=False``) so we can
            persist the assembled assistant message on completion.
          - On the terminal frame (``finished=True``), write the
            assembled message to ``conversations.events`` so the chat
            history sidebar + ``conversation:resume`` flow can replay
            this turn later. Skip persistence when no user_id is set
            (anonymous flows).
          - On AgentStateEvent(state='error'), write a terminal error
            event matching the CLI handlers' shape.

        ``mirror_to_user`` is for a turn with no socket of its own (a text or
        a call to the coordinator): the owner's open tabs get its tool steps,
        its end and its states through their user room, never each token (a
        relay round trip apiece), and the end only once the reply is saved, so
        a tab can read the whole turn back when it hears it.
        """
        accumulated: List[str] = []

        async def emit_message(event):
            """Callback to emit events to the frontend."""
            if isinstance(event, (ChatMessageEvent, AgentStateEvent)) and not event.conversation_id:
                # The agent wrapper's frames name no conversation, and a chat keyed on
                # one (the coordinator's) drops every frame that isn't its own.
                event.conversation_id = conversation_id
            if isinstance(event, ChatMessageEvent):
                # Add model information so the chat UI shows which model
                # produced this reply.
                event.model = model
                if not mirror_to_user:
                    await send_event(self.sio, sid, event)

                if event.message:
                    accumulated.append(event.message)

                # Persist the assembled assistant message when the run
                # finishes. The agent's wire format guarantees exactly
                # one finished=True frame per __call__.
                if event.finished and user_id:
                    final_text = "".join(accumulated).strip()
                    if final_text:
                        await self._persist_chat_event(
                            conversation_id=conversation_id,
                            user_id=user_id,
                            workflow_id=workflow_id,
                            node_id=node_id,
                            source="agent",
                            content=final_text,
                            model=model,
                            extra=extra,
                        )
                    accumulated.clear()
                if mirror_to_user and (event.finished or event.agentic_steps):
                    await send_event(self.sio, sid, event, user_id=user_id)
            elif isinstance(event, AgentStateEvent):
                await send_event(self.sio, sid, event, user_id=user_id if mirror_to_user else None)
                if event.state == "error" and user_id:
                    reason = event.reason or "Agent terminated with an error."
                    await self._persist_chat_error(
                        conversation_id=conversation_id,
                        user_id=user_id,
                        workflow_id=workflow_id,
                        node_id=node_id,
                        reason=reason,
                        model=model,
                    )

        return emit_message
