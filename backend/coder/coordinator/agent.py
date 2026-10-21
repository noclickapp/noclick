"""One coordinator turn: the account's agent, built per turn on the SDK
wrapper with its Postgres-backed session, so any container can serve the next
message and nothing warm is billed between turns."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

from billing.exceptions import InsufficientBalanceError, SpendCapReached, match_insufficient_credits, match_spend_cap
from billing.gates import bills_on_old_plans
from billing.usage_tracker import running
from coder.coordinator.compaction import CoordinatorCompactor
from coder.coordinator.followup import FollowupDelivery, FollowupReply
from coder.coordinator.memory import memory_context
from coder.coordinator.tools import COORDINATOR_NODE_ID, CoordinatorTools, step_preview
from coder.openai_agent import Agent
from coder.openai_agent.agent import CURRENT_TOOL_CALL_ID
from coder.openai_agent.config import AgentConfiguration
from coder.openai_agent.guards import TurnLimits
from nodes.agent.config.llm import DEFAULT_LLM_AGENT_MODEL
from repositories.coordinator_wakeups import CoordinatorWakeupRepo, coordinator_lock
from utils.account_link import AccountLink
from utils.capabilities import REFERRAL_OFFER, capability
from utils.database_pool import get_native_pool
from utils.prompts import PromptPack
from utils.tool_call_log import compact_tool_calls_for_transcript, gather_turn_tool_calls
from utils.turn_events import TURN_FAILED_LINE
from wss.handlers.agent_handler import AgentHandler
from wss.handlers.workflow_handler import get_user_org_context
from wss.sender import send_event
from wss.sender.events import AgentStateEvent, ChatMessageEvent
from wss.sender.schema import ContentItem

logger = logging.getLogger(__name__)

COORDINATOR_FEATURE = "coordinator"
COORDINATOR_MODEL = DEFAULT_LLM_AGENT_MODEL
# Building a site or shipping an app takes more model calls than a workflow agent's turn: the account's agent goes
# further in one turn, and wraps up at a dollar or a quarter of an hour.
COORDINATOR_LIMITS = TurnLimits(steps=100, spend_usd=1.0, minutes=15)

PROMPTS = PromptPack("coordinator")

VOICE_CHANNELS = ("phone", "whatsapp", "callback", "voice")
# Wake-ups that bring text from outside the owner (a failure signal, a job's result, an operation's report): the
# platform holds acting outside the account for a person on them.
UNTRUSTED_WAKEUPS = ("signal", "job", "operation")
TEXT_CHANNELS = ("whatsapp_text", "imessage_text")

_turn_locks: Dict[str, asyncio.Lock] = {}


class FollowupFailed(RuntimeError):
    """A follow-up turn that failed, with the tool calls it made first: its note carries them too."""

    def __init__(self, tool_calls: list):
        super().__init__("Coordinator follow-up failed; its transcript and task records are preserved.")
        self.tool_calls = tool_calls


def system_prompt_for(extra: Optional[Dict[str, Any]], note: Optional[str], *, cards: bool = False,
                      in_credits: bool = False, phone_steps: bool = True) -> str:
    """The base prompt (its refusals in credits for an account on the old
    plans, without its own phone tools' steps when a platform's tools buy
    numbers this turn), the channel's style (spoken on a call, terse on a
    text, links left to the cards in the web chat), and the caller's own
    context for this turn when the channel has it."""
    prompt = PROMPTS.system_prompt(in_credits=in_credits, phone_steps=phone_steps)
    channel = (extra or {}).get("channel")
    if cards:
        prompt += "\n\n" + PROMPTS.WEB_STYLE
    elif channel in VOICE_CHANNELS:
        prompt += "\n\n" + PROMPTS.VOICE_STYLE
    elif channel in TEXT_CHANNELS:
        prompt += "\n\n" + (PROMPTS.IMESSAGE_STYLE if channel == "imessage_text" else PROMPTS.TEXT_STYLE)
    elif channel == "email":
        prompt += "\n\n" + PROMPTS.EMAIL_STYLE
    if note:
        prompt += "\n\n" + note.strip()
    return prompt


def conversation_id_for(user_id: str) -> str:
    """One durable thread per account, shared by every channel."""
    return f"coordinator:{user_id}"


async def run_coordinator_turn(
    *, sio, sid: str, user_id: str, user_email: Optional[str], text: str,
    sink: Optional[Callable[[ChatMessageEvent], Awaitable[None]]] = None,
    extra: Optional[Dict[str, Any]] = None,
    note: Optional[str] = None,
    completion: Optional[Dict[str, Any]] = None,
    attachments: Optional[list[ContentItem]] = None,
    prepare_input: Optional[Callable[[], Awaitable[tuple[str, list[ContentItem]]]]] = None,
    user_event: Optional[Dict[str, Any]] = None,
    reply_event: Optional[Dict[str, Any]] = None,
) -> Optional[str | FollowupReply]:
    """Persist the user's message, run one agent turn, persist the reply.
    Frames stream to the socket ``sid`` and, when given, to ``sink`` — how a
    channel with no socket (a voice call) hears the same turn. ``extra`` is
    stamped on the persisted events (e.g. the channel). ``user_event`` is what
    the persisted user message shows instead of the model's input: its
    ``message`` and fields only that event carries (the web composer's files
    and references); ``reply_event``, fields only the reply's event carries (an
    email reply's receipt). Turns of one account never interleave."""
    pool = get_native_pool()
    conversation_id = conversation_id_for(user_id)
    lock = _turn_locks.setdefault(user_id, asyncio.Lock())
    if completion and lock.locked():
        from repositories.coordinator_lease import CoordinatorBusy
        raise CoordinatorBusy("An interactive turn is already running")
    async with (
        lock,
        coordinator_lock(pool, user_id, wait_seconds=0 if completion else 600) as turn_lease,
        running(surface="coordinator"),  # every charge of the turn is the chat with NoClick's
    ):
        # Channel downloads/digests belong to this turn's ownership too: a
        # later text must not overtake a slow image/document before it is seen.
        if prepare_input is not None and not completion:
            text, attachments = await prepare_input()
        wakeups = CoordinatorWakeupRepo(pool)
        epoch = await wakeups.epoch(user_id)
        followup = None
        if completion:
            if not await wakeups.start(completion):
                return None
            if completion["context"]["epoch"] != epoch:
                await wakeups.finish(completion, "", skipped=True)
                return None
            continuation = {**completion["context"], "depth": completion["context"]["depth"] + 1}
            if completion["source"] in ("alarm", "signal"):
                continuation["origin"] = "background"
            parent = None
            if parent_id := completion["payload"].get("parent_operation_id"):
                from repositories.coordinator_operations import CoordinatorOperationRepo
                parent = await CoordinatorOperationRepo(pool).get(parent_id, user_id)
            followup = FollowupDelivery(completion, parent=parent)
        else:
            continuation = {"epoch": epoch, "depth": 0, "request": text,
                            "channel": (extra or {}).get("channel") or "web", "turn_id": str(uuid.uuid4())}
        async with pool.acquire() as conn:
            organization_id = await get_user_org_context(conn, user_id)
        in_credits = await bills_on_old_plans(pool, user_id=user_id, organization_id=organization_id)
        tools = CoordinatorTools(
            pool=pool, sio=sio, user_id=user_id, organization_id=organization_id,
            conversation_id=conversation_id,
            reply_channel=(extra or {}).get("channel") or "web", continuation=continuation,
            phone_only=not user_email,
            followup=followup,
            email=user_email,
        )
        # Only a turn the web chat follows live leaves links to its tools' cards and gets the card-only tools: a
        # follow-up's note may also reach a phone, so its text stands alone (its cards still draw under it).
        cards = not completion and continuation["channel"] == "web"
        await tools.open_platform(turn_id=str(completion["id"]) if completion else continuation["turn_id"],
                                  untrusted=bool(completion) and completion["source"] in UNTRUSTED_WAKEUPS,
                                  voice=(extra or {}).get("channel") in VOICE_CHANNELS, cards=cards)
        from coder.coordinator.jobs import job_context

        jobs_note = await job_context(pool, user_id)
        memories_note = await memory_context(pool, user_id, model=COORDINATOR_MODEL)
        from coder.coordinator.reach import reach_note

        context_note = "\n\n".join(part for part in (
            "Current UTC time: " + datetime.now(timezone.utc).isoformat(), note,
            tools.platform.instructions if tools.platform is not None else None, jobs_note, memories_note,
            await reach_note(pool, user_id, phone_only=not user_email),
        ) if part)
        config = AgentConfiguration.from_kwargs(
            model=COORDINATOR_MODEL, enable_cmd=False, enable_editor=False, enable_mcp=False,
            custom_tools=tools.tool_params(),
            system_prompt=system_prompt_for(extra, context_note, in_credits=in_credits, cards=cards,
                                            phone_steps="request_phone_number" not in tools.superseded),
        )
        # The interactive chat's persistence and emit plumbing, unchanged: the
        # coordinator's transcript is a normal conversation row.
        chat = AgentHandler(sio)
        chat_emit = None if completion else await chat._create_emit_callback(
            sid, COORDINATOR_MODEL, conversation_id=conversation_id, user_id=user_id,
            workflow_id=None, node_id=COORDINATOR_NODE_ID, extra={**(extra or {}), **(reply_event or {})} or None,
            mirror_to_user=not sid,
        )

        failed: Dict[str, bool] = {}
        pieces = []

        async def out_of_funds() -> str:
            # Running out (never the cap its owner set) is when there's something to offer besides funds.
            stop = ("Your NoClick account is out of credits, so I have to stop here." if in_credits
                    else "Your NoClick account has run out of usage, so I have to stop here.")
            offer = capability(REFERRAL_OFFER)
            offered = offer and await offer(pool, user_id, organization_id=organization_id,
                                            request=None if completion else text)
            return f"{stop}\n\n{offered['line']}" if offered else stop

        async def emit(event) -> None:
            if isinstance(event, ChatMessageEvent) and event.status == "error":
                # The wrapper's failure frame carries the provider's raw text. A
                # phone or a WhatsApp thread gets one plain line; the log keeps the detail.
                logger.error("coordinator turn failed for %s: %s", user_id, event.message)
                failed["turn"] = True
                # NoClick's own words at the account's monthly cap are said as they are, and running out plainly.
                said = (event.message if match_spend_cap(event.message)
                        else await out_of_funds() if match_insufficient_credits(event.message) else TURN_FAILED_LINE)
                event = event.model_copy(update={"message": said, "status": None})
            if isinstance(event, ChatMessageEvent) and event.message:
                pieces.append(event.message)
            # The sink first: the transport speaks while the transcript write lands.
            if sink is not None and isinstance(event, ChatMessageEvent):
                await sink(event)
            if chat_emit is not None:
                await chat_emit(event)

        if not completion:
            shown = dict(user_event or {})
            content = shown.pop("message", text)
            await chat._persist_chat_event(
                conversation_id=conversation_id, user_id=user_id, workflow_id=None,
                node_id=COORDINATOR_NODE_ID, source="user", content=content,
                model=COORDINATOR_MODEL, label="Coordinator", extra={**(extra or {}), **shown} or None,
            )
            if not sid:
                # A text, a call or an email: the owner's open chat reads it back now and follows the reply.
                await send_event(sio, "", AgentStateEvent(state="running", conversation_id=conversation_id),
                                 user_id=user_id)

        tool_guard = asyncio.Lock()
        installed_discovery = []

        async def execute(name, arguments):
            nonlocal installed_discovery
            # Fail closed if renewable turn ownership was lost. An orphaned
            # turn cannot begin further tool effects.
            async with tool_guard:
                await turn_lease.check()
                if completion and not await wakeups.heartbeat(completion):
                    raise RuntimeError("Coordinator completion lease was lost")
            result = await tools.execute(name, arguments, call_id=CURRENT_TOOL_CALL_ID.get())
            discovered = tools.discovered.tool_params()
            if discovered != installed_discovery:
                agent.set_discovered_tools(discovered)
                installed_discovery = discovered
            return result

        agent = await Agent.create(
            emit_message=emit, config=config, conversation_id=conversation_id, sid=sid,
            user_id=user_id, user_email=user_email, sio=sio, enable_persistence=True,
            custom_tool_executor=execute, organization_id=organization_id, tool_step_preview=step_preview,
            wrap_up=PROMPTS.WRAP_UP, limits=COORDINATOR_LIMITS,
            call_model_input_filter=CoordinatorCompactor(
                pool, user_id, epoch=epoch, model=COORDINATOR_MODEL,
                user_email=user_email, organization_id=organization_id,
            ),
        )
        try:
            if completion and completion["source"] == "credential_approval":
                try:
                    await tools.credential_tools.load_approval_tools(completion["payload"])
                    installed_discovery = tools.discovered.tool_params()
                    if installed_discovery:
                        agent.set_discovered_tools(installed_discovery)
                except Exception:
                    # An account revoked/removed during review must still get
                    # the wakeup. Fresh execution access checks remain binding.
                    logger.warning("Could not restore approved operation schema", exc_info=True)
            if completion:
                if completion["source"] == "signal":
                    from coder.coordinator.signals import describe

                    event_description = describe(completion)
                elif completion["source"] == "alarm":
                    event_description = PROMPTS.ALARM_WAKEUP
                else:
                    event_description = PROMPTS.JOB_WAKEUP
                payload = json.dumps({"source": completion["source"], "source_id": str(completion["source_id"]),
                                      "original_request": continuation["request"], "outcome": completion["payload"]})
                await agent({"input_items": [{"role": "developer", "content": PROMPTS.wakeup_input(
                    event_description, followup.instructions(), payload)}]})
            else:
                await agent({"content_items": [ContentItem(type="text", text=text), *(attachments or [])]})
        except InsufficientBalanceError as exc:
            # The billing hook already told the socket; a sink hears it too,
            # unless the wrapper's own failure frame already reached it.
            if not failed and isinstance(exc, SpendCapReached):
                await emit(ChatMessageEvent(
                    conversation_id=conversation_id, finished=True, model=COORDINATOR_MODEL, message=str(exc),
                ))
            elif not failed:
                await emit(ChatMessageEvent(
                    conversation_id=conversation_id, finished=True, model=COORDINATOR_MODEL,
                    message=await out_of_funds(),
                ))
            failed["turn"] = True
        except Exception:
            failed["turn"] = True
            logger.error("coordinator turn crashed for %s", user_id, exc_info=True)
            await emit(ChatMessageEvent(
                conversation_id=conversation_id, message=TURN_FAILED_LINE, finished=True, model=COORDINATOR_MODEL,
            ))
        finally:
            await agent.cleanup()
        if tools.connect_verified:
            # The turn is persisted; the thread it lives in can now move.
            await AccountLink(pool).complete(user_id)
        text = "".join(pieces)
        if followup is None:
            return text
        # Its note, done or failed, carries the turn's tool calls, so the web chat draws their cards there (the site
        # it served at a domain), never under the next reply that would gather them.
        calls = compact_tool_calls_for_transcript(
            await gather_turn_tool_calls(node_id=COORDINATOR_NODE_ID, conversation_id=conversation_id))
        if failed:
            # A recurring alarm stops after a failed turn. Do not silently
            # repeat a provider/context failure on every scheduled occurrence.
            raise FollowupFailed(calls)
        return followup.reply(text, calls)
