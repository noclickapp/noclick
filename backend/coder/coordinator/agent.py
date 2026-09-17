"""One coordinator turn: the account's agent, built per turn on the SDK
wrapper with its Postgres-backed session, so any container can serve the next
message and nothing warm is billed between turns."""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, Optional

from billing.exceptions import InsufficientBalanceError
from coder.coordinator.tools import COORDINATOR_NODE_ID, CoordinatorTools, coordinator_tool_params
from coder.openai_agent import Agent
from coder.openai_agent.config import AgentConfiguration
from nodes.agent.config.llm import DEFAULT_LLM_AGENT_MODEL
from utils.database_pool import get_native_pool
from wss.handlers.agent_handler import AgentHandler
from wss.handlers.workflow_handler import get_user_org_context
from wss.sender import send_event
from wss.sender.events import ChatMessageEvent
from wss.sender.schema import ContentItem

logger = logging.getLogger(__name__)

COORDINATOR_FEATURE = "coordinator"
COORDINATOR_MODEL = DEFAULT_LLM_AGENT_MODEL

SYSTEM_PROMPT = (
    "You are the NoClick account coordinator: the one assistant that sees this whole NoClick account "
    "and gets things done in it. NoClick builds and runs AI agents and automations across the user's apps.\n\n"
    "What you can do: read the account (account_overview, list_workflows, describe_workflow) and hand builds "
    "or edits to the AI builder (request_build), then follow them up (build_status).\n\n"
    "How to work: look before you speak — check the account or the workflow before answering questions about "
    "them. When asked to build or change something, gather what the builder needs (which workflow, what "
    "exactly should happen, which apps are involved) in at most a couple of questions, then delegate with "
    "complete instructions and tell the user it is running. If a build is waiting on the owner, give them "
    "the questions and the link. Never claim something ran, was built, or was fixed unless a tool said so. "
    "Never ask for passwords, API keys or one-time codes; credentials are connected through NoClick's own "
    "links. Be concise and concrete: names, counts, next steps."
)

_turn_locks: Dict[str, asyncio.Lock] = {}


def conversation_id_for(user_id: str) -> str:
    """One durable thread per account, shared by every channel."""
    return f"coordinator:{user_id}"


async def run_coordinator_turn(*, sio, sid: str, user_id: str, user_email: Optional[str], text: str) -> None:
    """Persist the user's message, run one agent turn streaming chat frames to
    the socket, persist the reply. Turns of one account never interleave."""
    pool = get_native_pool()
    conversation_id = conversation_id_for(user_id)
    lock = _turn_locks.setdefault(user_id, asyncio.Lock())
    async with lock:
        async with pool.acquire() as conn:
            organization_id = await get_user_org_context(conn, user_id)
        tools = CoordinatorTools(
            pool=pool, sio=sio, user_id=user_id, organization_id=organization_id,
            conversation_id=conversation_id,
        )
        config = AgentConfiguration.from_kwargs(
            model=COORDINATOR_MODEL, enable_cmd=False, enable_editor=False, enable_mcp=False,
            custom_tools=coordinator_tool_params(), system_prompt=SYSTEM_PROMPT,
        )
        # The interactive chat's persistence and emit plumbing, unchanged: the
        # coordinator's transcript is a normal conversation row.
        chat = AgentHandler(sio)
        emit = await chat._create_emit_callback(
            sid, COORDINATOR_MODEL, conversation_id=conversation_id, user_id=user_id,
            workflow_id=None, node_id=COORDINATOR_NODE_ID,
        )
        await chat._persist_chat_event(
            conversation_id=conversation_id, user_id=user_id, workflow_id=None,
            node_id=COORDINATOR_NODE_ID, source="user", content=text,
            model=COORDINATOR_MODEL, label="Coordinator",
        )
        agent = await Agent.create(
            emit_message=emit, config=config, conversation_id=conversation_id, sid=sid,
            user_id=user_id, user_email=user_email, sio=sio, enable_persistence=True,
            custom_tool_executor=tools.execute, organization_id=organization_id,
        )
        try:
            await agent({"content_items": [ContentItem(type="text", text=text)]})
        except InsufficientBalanceError:
            return  # the billing hook already told the client
        except Exception as exc:
            logger.error("coordinator turn failed for %s", user_id, exc_info=True)
            await send_event(sio, sid, ChatMessageEvent(
                conversation_id=conversation_id, message=f"Sorry, something went wrong: {exc}",
                finished=True, model=COORDINATOR_MODEL,
            ))
        finally:
            await agent.cleanup()
