"""Socket.io handler for the interactive chat agent (chat:message)."""

import logging
from typing import Dict, Callable, Optional, List, Any

from coder.openai_agent import Agent
from coder.openai_agent.config import AgentConfiguration
from wss.schema import SocketIOHandler
from wss.sender.schema import ContentItem
from wss.sender import send_event, ChatMessageEvent, AgentStateEvent, ResponseEvent
from wss.receiver.client_events import (
    ChatMessageRequest,
    AgentSetCwdRequest,
    AgentPauseRequest,
    AgentBuilderDecisionRequest,
)
from utils.database_pool import DatabasePoolMixin
from repositories.conversation import ConversationRepo


logger = logging.getLogger(__name__)


class AgentHandler(DatabasePoolMixin, SocketIOHandler):
    """Handles chat:message events with multi-turn conversation support via coder/openai_agent."""

    def __init__(self, sio):
        super().__init__(sio)
        self._agents: Dict[str, Agent] = {}  # Track agents by conversation_id
        self._sid_conversations: Dict[str, set] = {}  # Map sid to set of conversation_ids
        self._pending_cwd: Dict[str, str] = {}  # Track pending cwd updates by conversation_id
        self._current_cwd: Dict[str, str] = {}  # Track current working directory by conversation_id
    
    def get_events(self) -> Dict[str, Callable]:
        return {
            "chat:message": self.respond,
            "agent:set:cwd": self.handle_set_cwd,
            "agent:pause": self.handle_pause,
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

        from utils.access_control import check_resource_access

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


    async def handle_set_cwd(self, sid: str, data: AgentSetCwdRequest) -> None:
        """Handle working directory updates initiated from the frontend."""
        logger.info(f"handle_set_cwd called for session {sid} with data {data}")
        path = data.path
        if not path:
            logger.warning(f"Received empty cwd update for session {sid}")
            return

        conversation_id = data.conversation_id
        self._current_cwd[conversation_id] = path

        # Update conversation's app context in database if provided
        if conversation_id and (data.app_id or data.app_name):
            try:
                # Get user_id from session
                session = await self.sio.get_session(sid)
                user_id = session.get('user_id')

                if user_id:
                    logger.info(f"Updating conversation {conversation_id} with app context: app_id={data.app_id}, app_name={data.app_name}")

                    # Update app_id and app_name in conversations table.
                    # Migrated 2026-07-01 to ConversationRepo — SQL lives in
                    # repositories/conversation.py so the same UPDATE is not
                    # spelled inline in three handlers.
                    repo = ConversationRepo(await self.get_pool())
                    await repo.update_app_context(
                        conversation_id=conversation_id,
                        user_id=user_id,
                        app_id=data.app_id,
                        app_name=data.app_name,
                    )

                    logger.info(f"Successfully updated app context for conversation {conversation_id}")
                else:
                    logger.warning(f"Cannot update app context: user_id not found in session for sid {sid}")
            except Exception as e:
                logger.error(f"Failed to update app context for conversation {conversation_id}: {e}", exc_info=True)

        agent = self._agents.get(conversation_id)
        if agent:
            try:
                logger.info(f"Calling set_working_directory for conversation {conversation_id} with path {path}")
                await agent.set_working_directory(path)
                logger.info(f"Updated working directory for conversation {conversation_id} to {path}")
            except Exception as exc:
                logger.error(f"Failed to update working directory for conversation {conversation_id}: {exc}")
        else:
            # Cache the desired cwd so we can apply it once the agent exists
            self._pending_cwd[conversation_id] = path
            logger.debug(f"Queued cwd update for conversation {conversation_id} (agent not yet initialized)")

    async def handle_pause(self, sid: str, data: AgentPauseRequest) -> None:
        """Handle pause requests from the frontend.

        A pause can target one of two active runs for the conversation:
          1) A chat agent (chat:message path) — Agent.pause() cancels the
             active RunResultStreaming via result.cancel("immediate").
          2) An agentic workflow builder (workflow:builder:edit path) — uses a
             CancelScope registered in cancellation._ACTIVE_BUILDER_SCOPES.

        Both can be active simultaneously in principle (different surfaces
        sharing one conversation_id), so we signal both if present.
        """
        conversation_id = data.conversation_id
        agent = self._agents.get(conversation_id)

        from utils.cancellation import get_builder_scope
        builder_scope = get_builder_scope(conversation_id)

        if not agent and not builder_scope:
            logger.warning(f"Pause requested for conversation {conversation_id} but no agent or builder is active")
            return

        if agent:
            try:
                await agent.pause()
            except Exception as exc:
                logger.error(f"Failed to pause agent for conversation {conversation_id}: {exc}")

        if builder_scope:
            try:
                builder_scope.cancel()
                logger.info(f"[AgentHandler] Cancelled builder run for conversation {conversation_id}")
            except Exception as exc:
                logger.error(f"Failed to cancel builder for conversation {conversation_id}: {exc}")

        try:
            await send_event(self.sio, sid, AgentStateEvent(state='paused', conversation_id=conversation_id))
        except Exception as exc:
            logger.error(f"Failed to send paused state for conversation {conversation_id}: {exc}")

    async def respond(self, sid: str, data: ChatMessageRequest) -> None:
        """Process messages via coder.openai_agent.Agent with conversation management."""
        model = data.model
        conversation_id = data.conversation_id or sid

        logger.info(f"[AGENT_HANDLER] respond() called: sid={sid}, conversation_id={conversation_id}, content_items={len(data.content) if data.content else 0}")

        # Check daily AI builder limit
        session = await self.sio.get_session(sid)
        user_id = session.get('user_id') if session else None
        if user_id:
            try:
                pool = await self.get_pool()
                if pool:
                    async with pool.acquire() as conn:
                        from billing.plan_limits import check_ai_builder_limit
                        can_use, limit_error = await check_ai_builder_limit(conn, user_id)
                        if not can_use:
                            await send_event(self.sio, sid, ChatMessageEvent(
                                conversation_id=conversation_id,
                                message=limit_error,
                                finished=True,
                            ))
                            user_data = session.get('user_data', {})
                            pass
                            return
            except Exception as e:
                logger.warning(f"[AGENT_HANDLER] AI builder limit check failed, proceeding: {e}")

        agent = await self._ensure_agent(
            conversation_id=conversation_id,
            sid=sid,
            model=model,
            env=data.env,
            workflow_id=(data.context.workflow_id if data.context else None),
        )

        # Apply app context (cwd + db tracking) if provided
        if data.context and data.context.app_id:
            await self._apply_app_context(agent, sid, conversation_id, data.context)

        # Persist the user message to conversations.events BEFORE
        # dispatching to the agent. Two reasons:
        #   1. If the agent errors mid-stream, the user's text still
        #      shows up in history (matches OpenHands' write-on-receive
        #      semantics).
        #   2. The first user message's text becomes title + preview
        #      via the COALESCE-on-NULL upsert. Setting `label` on this
        #      call locks them on the first turn; subsequent calls (the
        #      emit_callback's agent persist) pass `label=None`.
        if user_id and data.content:
            # Pull the first non-empty text item out of the
            # ContentItem list for the message body.
            user_text_parts: list = []
            for item in data.content:
                txt = getattr(item, "text", None)
                if isinstance(txt, str) and txt:
                    user_text_parts.append(txt)
            user_text = "\n".join(user_text_parts).strip()
            if user_text:
                workflow_id = (
                    data.context.workflow_id if data.context else None
                )
                await self._persist_chat_event(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    workflow_id=workflow_id,
                    node_id=None,
                    source="user",
                    content=user_text,
                    model=model,
                    label=user_text[:100],
                )

        await self._process_message_with_content(agent, sid, data.content, model, conversation_id)

    async def _apply_app_context(self, agent, sid: str, conversation_id: str, context) -> None:
        """Apply app context to agent working directory and update database tracking.

        Ensures the agent always has accurate app context, avoiding race conditions
        with separate agent:set:cwd events.
        """
        # Skip temporary creating-* IDs - the app doesn't exist yet
        if context.app_id.startswith('creating-'):
            logger.info(f"[AGENT_HANDLER] Skipping cwd for temporary app_id: {context.app_id}")
            return

        # Use /tmp/apps path since agent runs in sandbox
        app_path = f"/tmp/apps/{context.app_id}"
        logger.info(f"[AGENT_HANDLER] Setting cwd from context: app_id={context.app_id}")

        # Update tracking for subsequent messages
        self._current_cwd[conversation_id] = app_path

        # Apply to agent if different from current
        current_cwd = getattr(agent, '_current_workdir', None)
        if current_cwd != app_path:
            try:
                await agent.set_working_directory(app_path)
            except Exception as exc:
                logger.error(f"[AGENT_HANDLER] Failed to set cwd for {conversation_id}: {exc}")

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
        """
        accumulated: List[str] = []

        async def emit_message(event):
            """Callback to emit events to the frontend."""
            if isinstance(event, ChatMessageEvent):
                # Add model information so the chat UI shows which model
                # produced this reply.
                event.model = model
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
                            node_id=None,
                            source="agent",
                            content=final_text,
                            model=model,
                        )
                    accumulated.clear()
            elif isinstance(event, AgentStateEvent):
                await send_event(self.sio, sid, event)
                if event.state == "error" and user_id:
                    reason = event.reason or "Agent terminated with an error."
                    await self._persist_chat_error(
                        conversation_id=conversation_id,
                        user_id=user_id,
                        workflow_id=workflow_id,
                        node_id=None,
                        reason=reason,
                        model=model,
                    )

        return emit_message

    async def _process_message_with_content(self, agent, sid: str, content: List[ContentItem], model: str, conversation_id: str) -> None:
        """Process a message with sequence-sensitive content."""
        try:
            # Pass content array to agent
            message_dict = {"content_items": content}

            # Call the agent - events are emitted via callback
            await agent(message_dict)

        except Exception as e:
            logger.error(f"Error processing message for {sid}: {e}")

            event = ChatMessageEvent(
                conversation_id=conversation_id,
                message=f"Sorry, I encountered an error: {str(e)}",
                finished=True,
                model=model
            )
            await send_event(self.sio, sid, event)


    async def _update_agent(self, conversation_id: str, model: str, env: Optional[Dict[str, str]] = None):
        """
        Update the model for a given conversation's agent.
        """
        # Get the existing agent - don't call _ensure_agent as that would cause recursion
        if conversation_id not in self._agents:
            logger.error(f"Cannot update agent for conversation {conversation_id} - no agent exists")
            return

        agent = self._agents[conversation_id]
        
        # Call agent's update_model method if available
        if hasattr(agent, 'update_model'):
            try:
                # Pass env dict to agent's update_model
                agent.update_model(
                    model=model,
                    temperature=None,
                    env=env  # Pass environment overrides
                )
                logger.info(f"Updated model configuration for conversation {conversation_id} to {model}")
            except Exception as e:
                logger.error(f"Error updating model for conversation {conversation_id}: {e}")
        else:
            logger.warning(f"Agent for conversation {conversation_id} does not support update_model")

    async def _ensure_agent(
        self,
        conversation_id: str,
        sid: str,
        model: str = "gpt-4o",
        env: Optional[Dict[str, str]] = None,
        workflow_id: Optional[str] = None,
    ):
        """Ensure an agent exists for the conversation, creating or updating as needed.

        Args:
            conversation_id: Unique conversation identifier
            sid: Socket session ID
            model: LLM model to use
            env: Optional environment overrides (API keys)
            workflow_id: Active workflow ID — written to conversations.workflow_id on
                first message so the sidebar can later auto-restore the latest
                conversation per workflow.
        """

        # First, ensure the agent is created (key by conversation_id)
        if conversation_id not in self._agents:
            session = await self.sio.get_session(sid)

            if session is None:
                logger.error(f"No session found for sid={sid}")
                event = ChatMessageEvent(
                    conversation_id=conversation_id,
                    message="Authentication error: No session found",
                    finished=True,
                    model=model  # Include requested model in error
                )
                await send_event(self.sio, sid, event)
                return None

            user_id = session.get('user_id')
            if not user_id:
                logger.error(f"No user_id in session for {sid}")
                event = ChatMessageEvent(
                    conversation_id=conversation_id,
                    message="Authentication error: No user ID found in session",
                    finished=True,
                    model=model  # Include requested model in error
                )
                await send_event(self.sio, sid, event)
                return None

            # Get user email for debug features
            user_email = session.get('user_data', {}).get('email')

            # Create config without explicit API key - let litellm read from environment
            # MCP is enabled by default in production, but can be disabled via environment
            import os
            enable_mcp = os.getenv("ENABLE_MCP", "true").lower() == "true"

            # Detect backend port from command line args or environment
            # Supports --port flag for multi-worktree setups
            from utils.port_detection import detect_port_from_argv
            backend_port = detect_port_from_argv(default=int(os.getenv("PORT", "8000")))

            config = AgentConfiguration.from_kwargs(
                model=model,
                env=env,
                enable_cmd=False,
                enable_editor=False,
                enable_mcp=enable_mcp,
                mcp_server_url=f"http://localhost:{backend_port}/mcp/",
            )

            # Create emit callback for this session.
            # Pass conversation_id + user_id + workflow_id so the
            # callback can persist assistant messages and terminal
            # errors to ``conversations.events`` as they finalize —
            # restoring the chat history persistence the OpenHands
            # PostgresStore used to do automatically.
            emit_callback = await self._create_emit_callback(
                sid, model,
                conversation_id=conversation_id,
                user_id=user_id,
                workflow_id=workflow_id,
            )

            self._agents[conversation_id] = await Agent.create(
                emit_message=emit_callback,
                config=config,
                conversation_id=conversation_id,
                sid=sid,
                user_id=user_id,
                user_email=user_email,
                sio=self.sio,
                env=env,
                workflow_id=workflow_id,
            )

            # Track this conversation for the sid
            if sid not in self._sid_conversations:
                self._sid_conversations[sid] = set()
            self._sid_conversations[sid].add(conversation_id)

            # Apply any working directory selection (pending or current)
            cwd_to_apply = self._pending_cwd.get(conversation_id) or self._current_cwd.get(conversation_id)
            if cwd_to_apply:
                try:
                    await self._agents[conversation_id].set_working_directory(cwd_to_apply)
                    logger.info(f"Applied cwd {cwd_to_apply} for new agent conversation {conversation_id}")
                    # Clear the pending cwd after applying (but keep current_cwd)
                    if conversation_id in self._pending_cwd:
                        del self._pending_cwd[conversation_id]
                    # Skip applying it again at the end of this function
                    agent_created_with_cwd = True
                except Exception as exc:
                    logger.error(f"Failed to apply cwd for session {sid}: {exc}")
                    agent_created_with_cwd = False
            else:
                agent_created_with_cwd = False
        else:
            agent_created_with_cwd = False
        
        # Ensure the model matches and user_api_key flag is correct
        agent = self._agents[conversation_id]

        if agent.model != model or agent.env != env:
            # Need to update the agent's sid if it changed
            if hasattr(agent, '_sid') and agent._sid != sid:
                agent._sid = sid
            await self._update_agent(conversation_id, model, env)

        # Always ensure the current working directory is applied
        # (even if model hasn't changed, the cwd might have been updated)
        # But skip if we just created the agent with the cwd already
        if not agent_created_with_cwd:
            cwd_to_apply = self._current_cwd.get(conversation_id)
            if cwd_to_apply:
                # Check if the agent's current working directory matches
                current_agent_cwd = getattr(agent, '_current_workdir', None)
                if current_agent_cwd != cwd_to_apply:
                    try:
                        await self._agents[conversation_id].set_working_directory(cwd_to_apply)
                        logger.info(f"Applied cwd {cwd_to_apply} for conversation {conversation_id}")
                    except Exception as exc:
                        logger.error(f"Failed to apply cwd for conversation {conversation_id}: {exc}")

        return self._agents[conversation_id]

    async def cleanup_user(self, sid: str):
        """Cleanup all agent sessions for a disconnected user."""
        # Get all conversations for this sid
        conversation_ids = self._sid_conversations.get(sid, set())

        # Clean up each agent
        for conversation_id in conversation_ids:
            try:
                if conversation_id in self._agents:
                    await self._agents[conversation_id].cleanup() # type: ignore
                    del self._agents[conversation_id]
                    logger.info(f"Cleaned up agent for conversation {conversation_id} (session {sid})")
            except Exception as e:
                logger.error(f"Error cleaning up agent for conversation {conversation_id}: {e}")

            # Clean up related cwd tracking
            if conversation_id in self._pending_cwd:
                del self._pending_cwd[conversation_id]
            if conversation_id in self._current_cwd:
                del self._current_cwd[conversation_id]

        # Clean up the sid mapping
        if sid in self._sid_conversations:
            del self._sid_conversations[sid]
