"""Running an agent for real against a world that isn't.

See REHEARSAL.md for the design. The short version: during onboarding nobody can
wait for a real trigger — a support agent needs an angry customer and a new
account has neither — so the agent, model, prompt and tool wiring are all real
and only the world is fabricated.

This module owns the fabricated world. One model conversation per rehearsal,
never one call per tool: because the session sees every tool call in order and
everything it has already returned, **its own context is the ledger**. An agent
that creates a ticket and reads it back gets the same ticket, because the mock
said so earlier and can see that it did. That property is why the session is
threaded rather than stateless, and it is the whole reason an explicit
side-effect ledger is not needed.

A rehearsal proves BEHAVIOUR and says nothing about connectivity — that is
``connection_evidence``'s job, with real data. Callers must keep the two
distinct: a rehearsal allowed to read as "it works" reinvents the green tick
that evidence exists to delete.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

REHEARSAL_CONVERSATION_PREFIX = "rehearsal:"

# Same model and routing the schema tracker already uses for internal work:
# fast, cheap, and good enough to fabricate a plausible API response.
REHEARSAL_MODEL = "openrouter/openai/gpt-oss-120b"
REHEARSAL_PROVIDER_ORDER = ["groq", "cerebras"]
# Generation sits inline in the agent's turn, so this bounds how long a single
# tool call can stall. It is generous rather than tight — a rehearsal that
# half-answers is worse than one that takes a moment.
REHEARSAL_TIMEOUT_S = 20.0
REHEARSAL_TEMPERATURE = 0.3

# A rehearsal is a single onboarding moment, not a long-lived session.
REHEARSAL_TTL_S = 30 * 60

# How much of the fabricated world to keep in front of the model. Rehearsals are
# short by nature; this only bounds a pathological agent that keeps calling
# tools, and it keeps the newest (most relevant) exchanges.
MAX_REMEMBERED_CALLS = 40

_KEY = "nc:rehearsal:{conversation_id}"

# Tool types that read only NoClick's own data about this workflow and reach
# nothing outside it. Everything else is fabricated — including email_reply,
# alarms, filesystem writes and prompt_builder, all of which have real effects
# and real cost. Default-mock with a narrow allowlist rather than the reverse:
# a tool type added later is fabricated until someone decides otherwise, which
# is the safe direction for a feature whose whole promise is that nothing
# outward happens.
#
# describe_workflow is exempt because the agent's own configuration IS real
# during a rehearsal; fabricating it would have the agent reason about a
# workflow that does not exist.
REHEARSAL_PASSTHROUGH_TOOL_TYPES = frozenset({"describe_workflow"})


_SYSTEM = """You are simulating third-party APIs for a rehearsal of an automation agent.

The agent calling these tools is real and believes your responses. Your job is to
return what each API would plausibly return in the situation described.

Rules:
1. Reply with JSON only. No prose, no markdown fences. When a response schema is
   given, match it exactly — the same field names, nesting and types.
2. Stay consistent with everything you have already returned in this session. If
   you said a ticket has id 4471, it still has id 4471, and anything created
   earlier still exists.
3. THE WORLD IS BUSY. This account belongs to an active team: channels have
   yesterday's messages, inboxes have mail, boards have tickets. A read or list
   call ALWAYS returns populated data — 3 to 8 realistic entries with authors,
   timestamps and substantive content that fits the situation. `null`, `[]`,
   `{{}}` or an empty `data` field is a WRONG answer for a read; the one
   exception is a search for something the situation says does not exist.
4. Never invent a failure or an error envelope unless the scenario explicitly
   calls for one. Return the successful response the agent would get on a good
   day; a write/send returns its normal acknowledgement.
5. Fabricate concrete specifics: real-sounding names, plausible ids, timestamps,
   quantities, wording. Placeholder output like "Example Customer", "Lorem
   ipsum" or "test@test.com" makes the rehearsal look broken.
6. Answer the call that was actually made. If the agent searched for "refund not
   received", return results about refunds, not unrelated records.

The situation:
{scenario}
"""


@dataclass(frozen=True)
class RehearsalScenario:
    """The staged world, authored by hand alongside a template.

    ``scenario`` describes the situation, NOT the desired outcome. "The agent
    should apologise and offer a refund" produces a rehearsal that flatters the
    agent instead of testing it.
    """

    scenario: str
    #: Node the fabricated event arrives at.
    trigger_node_id: str
    #: Exact provider shape. Hand-authored, never generated — each node class
    #: translates this through ``resolve_agent_event`` to build the agent's turn,
    #: and an almost-right payload breaks that silently.
    trigger_payload: Dict[str, Any]


class RehearsalUnavailable(RuntimeError):
    """The fabricated world could not answer.

    Raised rather than degrading to ``{}``: an agent reasoning over an empty
    response produces a confident, plausible, entirely misleading trace, which
    is a worse outcome than stopping and saying the rehearsal failed.
    """


def _key(conversation_id: str) -> str:
    return _KEY.format(conversation_id=conversation_id)


async def start_rehearsal(
    conversation_id: str,
    scenario: RehearsalScenario,
    user_id: Optional[str] = None,
    sid: Optional[str] = None,
    organization_id: Optional[str] = None,
    public: bool = False,
) -> None:
    """Mark a conversation as rehearsing and seed its fabricated world.

    ``sid`` is the socket that asked, and it is the primary delivery target:
    that client is by definition present and listening. ``user_id`` is the
    fallback for their other tabs.

    Neither is the workflow room, deliberately — a rehearsal is watched from
    surfaces that never opened the workflow (onboarding, a template preview),
    and those are not in the room, so room-routed frames never arrive.
    """
    from utils.redis_client import get_shared_redis

    client = get_shared_redis()
    if client is None:
        # Without Redis there is no way to tell the tool-call mirrors that this
        # run is rehearsing, and a rehearsal that cannot be recognised would
        # execute against real accounts. Refuse to start.
        raise RehearsalUnavailable("Redis unavailable; cannot start a rehearsal")

    state = {
        "scenario": scenario.scenario,
        "trigger_node_id": scenario.trigger_node_id,
        "user_id": user_id,
        "sid": sid,
        # Billing attribution for the world model's own LLM calls (Agent
        # Testing) — organization attribution policy keys on a truthy organization_id.
        "organization_id": organization_id,
        # Anonymous template-page runs: progress frames ALSO buffer in Redis
        # so a visitor with no socket can poll them (utils/public_routes).
        "public": public,
        "calls": [],
    }
    await client.set(_key(conversation_id), json.dumps(state), ex=REHEARSAL_TTL_S)
    logger.info("[rehearsal] started for conversation %s", conversation_id)


async def end_rehearsal(conversation_id: str) -> None:
    from utils.redis_client import get_shared_redis

    client = get_shared_redis()
    if client is not None:
        await client.delete(_key(conversation_id))


async def load_rehearsal(conversation_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """The rehearsal state for a conversation, or None if it is not rehearsing.

    This is the gate both tool-call mirrors consult. It is a lookup rather than a
    parameter threaded through the tool capability because a rehearsal is a property
    of the RUN, not of a tool — and looking it up works cross-container for free,
    which the CLI-harness path needs.

    Fails CLOSED on a Redis error: unknown means "not rehearsing", so a blip can
    only ever cause a normal (real) tool call to be refused by the caller, never
    cause a rehearsal to silently execute against a real account.
    """
    if not conversation_id:
        return None
    from utils.redis_client import get_shared_redis

    client = get_shared_redis()
    if client is None:
        return None
    try:
        raw = await client.get(_key(conversation_id))
    except Exception as e:
        logger.warning("[rehearsal] state lookup failed for %s: %s", conversation_id, e)
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


async def is_rehearsing(conversation_id: Optional[str]) -> bool:
    return await load_rehearsal(conversation_id) is not None


def _messages(state: Dict[str, Any], ask: str) -> List[Dict[str, str]]:
    """Rebuild the session transcript, newest exchanges preserved.

    The transcript IS the ledger — replaying prior calls and their responses is
    what makes a created-then-read-back entity stay the same entity.
    """
    msgs: List[Dict[str, str]] = [
        {"role": "system", "content": _SYSTEM.format(scenario=state.get("scenario", ""))}
    ]
    for call in (state.get("calls") or [])[-MAX_REMEMBERED_CALLS:]:
        msgs.append({"role": "user", "content": call["ask"]})
        msgs.append({"role": "assistant", "content": call["response"]})
    msgs.append({"role": "user", "content": ask})
    return msgs


def _build_ask(
    tool_name: str,
    description: Optional[str],
    arguments: Dict[str, Any],
    output_schema: Optional[Any],
) -> str:
    parts = [f"The agent called `{tool_name}`."]
    if description:
        parts.append(f"What it does: {description}")
    parts.append(f"Arguments: {json.dumps(arguments, default=str)[:2000]}")
    if output_schema:
        parts.append(
            "Respond with JSON matching this observed response schema:\n"
            + json.dumps(output_schema, default=str)[:4000]
            + "\n\nThe schema shows SHAPE only — populate it fully. Every list "
            "field carries several realistic entries; nullable fields carry "
            "values, not null. A response whose data payload is null or empty "
            "is wrong."
        )
    else:
        # No learned schema for this operation. Say so plainly — the model
        # improvising a shape is the known weak spot, and pretending otherwise
        # would hide it.
        parts.append(
            "No response schema is on record for this operation. Return the JSON "
            "object this API would realistically return."
        )
    return "\n\n".join(parts)


# Argument names that carry a message a human would read, rather than an id or a
# flag. Ordered by how likely they are to hold the thing itself.
_OUTBOUND_KEYS = ("text", "message", "body", "content", "comment", "description", "subject")

# Short enough to be a channel name, an id or a status — not the artifact.
_OUTBOUND_MIN_CHARS = 25


def outbound_text(arguments: Optional[Dict[str, Any]]) -> Optional[str]:
    """The message this call would actually have sent.

    The payoff panel exists to show what the agent COMPOSED, and that lives in
    the tool call's arguments — not in the agent's closing narration, which is a
    summary addressed to the user ("I have posted the briefing to Slack...").
    Rendering the narration under "what it would have posted" shows a report of
    the work instead of the work.
    """
    if not isinstance(arguments, dict):
        return None
    candidates = [
        v.strip()
        for k in _OUTBOUND_KEYS
        for v in [arguments.get(k)]
        if isinstance(v, str) and len(v.strip()) >= _OUTBOUND_MIN_CHARS
    ]
    # Longest wins: a call carrying both a subject and a body should surface the
    # body, which is the part worth reading.
    return max(candidates, key=len) if candidates else None


def _parse_response(text: str) -> Any:
    """The model's JSON, tolerating a fenced block."""
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]
    return json.loads(cleaned.strip())


async def emit_rehearsal_thought(conversation_id: str, text: str) -> None:
    """A slice of the agent's visible reasoning between tool calls, rendered as
    a thought row in the live trace — the narrative beat that explains WHY the
    next call happens. Best-effort and silent on failure: a lost thought must
    never cost a frame of the run itself."""
    try:
        state = await load_rehearsal(conversation_id)
        if state is None:
            return
        clip = " ".join(text.split())
        if not clip:
            return
        if len(clip) > 500:
            clip = clip[:500].rstrip() + "…"
        await _emit_progress(
            state,
            conversation_id,
            kind="thought",
            step_id=f"th-{abs(hash((conversation_id, clip[:64], len(clip))))}",
            text=clip,
        )
    except Exception:
        logger.debug("[rehearsal] thought emit failed", exc_info=True)


def _looks_like_empty_world(result: Any) -> bool:
    """A fabricated response that would read as a broken world: nothing at all,
    or an envelope whose data payload is null/empty. Deliberately narrow — a
    write's acknowledgement ({"ok": true, "ts": ...}) must pass untouched."""
    if result is None or result == {} or result == []:
        return True
    if isinstance(result, dict) and "data" in result:
        return result["data"] in (None, {}, [])
    return False


async def mock_tool_call(
    *,
    conversation_id: str,
    tool_name: str,
    arguments: Optional[Dict[str, Any]] = None,
    description: Optional[str] = None,
    node_type: Optional[str] = None,
    operation: Optional[str] = None,
) -> Any:
    """Answer one tool call from the fabricated world.

    Raises :class:`RehearsalUnavailable` rather than returning something empty —
    see the class docstring for why that matters more than it looks.
    """
    import litellm

    state = await load_rehearsal(conversation_id)
    if state is None:
        raise RehearsalUnavailable(f"conversation {conversation_id} is not rehearsing")

    output_schema = None
    if node_type and operation:
        from utils.node_schema_tracker import get_schema_with_suggestions

        row = await get_schema_with_suggestions(node_type, operation)
        output_schema = (row or {}).get("schema")

    ask = _build_ask(tool_name, description, arguments or {}, output_schema)

    step_id = f"reh-{abs(hash((conversation_id, tool_name, len(state.get('calls') or []))))}"
    await _emit_progress(state, conversation_id, kind="step", step_id=step_id,
                         tool=tool_name, status="in_progress",
                         args=arguments or {})

    # Provider $ + tokens accumulated across the call (and its one retry) —
    # charged as ONE Agent Testing usage event after success.
    spent: Dict[str, float] = {"cost": 0.0, "tokens": 0.0}

    async def _fabricate(messages: list) -> tuple[str, Any]:
        response = await litellm.acompletion(
            model=REHEARSAL_MODEL,
            messages=messages,
            temperature=REHEARSAL_TEMPERATURE,
            timeout=REHEARSAL_TIMEOUT_S,
            response_format={"type": "json_object"},
            extra_body={
                "provider": {
                    "order": REHEARSAL_PROVIDER_ORDER,
                    "allow_fallbacks": True,
                },
                # OpenRouter usage accounting: provider-reported cost rides
                # back on response.usage. Safe here — REHEARSAL_MODEL is
                # always openrouter/ (this extra_body 400s elsewhere; the
                # Groq incident class).
                "usage": {"include": True},
            },
        )
        from coder.openai_agent.litellm_model import extract_cost_from_response

        cost, _ = extract_cost_from_response(response)
        spent["cost"] += cost or 0.0
        usage = getattr(response, "usage", None)
        spent["tokens"] += float(getattr(usage, "total_tokens", 0) or 0)
        raw = response.choices[0].message.content
        return raw, _parse_response(raw)

    try:
        text, result = await _fabricate(_messages(state, ask))
        # The small world-model sometimes nulls the data payload despite the
        # busy-world doctrine (the empty Slack digest, 2026-08-10). One
        # corrective retry — an empty read makes the whole demo look broken,
        # which is worth a second cheap call; write acks pass through.
        if _looks_like_empty_world(result):
            logger.info("[rehearsal] %s fabricated empty — retrying once", tool_name)
            nudge = (
                ask
                + "\n\nYour previous answer had a null/empty data payload. The "
                "world is BUSY: return the same shape fully populated with "
                "several realistic entries."
            )
            text, result = await _fabricate(_messages(state, nudge))
    except Exception as e:
        logger.error("[rehearsal] %s could not be simulated: %s", tool_name, e)
        raise RehearsalUnavailable(f"could not simulate {tool_name}: {e}") from e

    await _charge_world_call(state, conversation_id, tool_name,
                             spent["cost"], int(spent["tokens"]))

    # Append to the ledger before returning, so the next call sees this one even
    # if the agent fires them back to back.
    await _remember(conversation_id, ask, text)
    await _emit_progress(state, conversation_id, kind="step", step_id=step_id,
                         tool=tool_name, status="completed",
                         outbound=outbound_text(arguments),
                         args=arguments or {}, result=result)
    logger.info("[rehearsal] simulated %s for %s", tool_name, conversation_id)
    return result


async def _charge_world_call(
    state: Dict[str, Any],
    conversation_id: str,
    tool_name: str,
    provider_cost: float,
    total_tokens: int,
) -> None:
    """Charge one fabricated tool answer as Agent Testing usage.

    Mirrors the builder's `_store_builder_usage_event` doctrine: markup at
    write time, versioned subtype sentinel (the world model's identity is
    private), record-everything (a $0 answer still lands a row), and a
    billing failure never kills the rehearsal — the demo is worth more than
    the fraction of a cent. organization attribution policy applies via track_usage_event's choke
    point when the workflow is org-owned."""
    user_id = state.get("user_id")
    if not user_id:
        # Pre-billing rehearsal states (or tests) carry no runner — nothing
        # to attribute the spend to.
        return
    try:
        from decimal import Decimal

        from billing.markup import apply_ai_testing_markup
        from billing.schema import UsageEventData
        from billing.usage_tracker import usage_tracker

        if provider_cost < 0:
            logger.warning("[rehearsal] negative world-model cost %s for %s; skipping",
                           provider_cost, conversation_id)
            return
        event = UsageEventData(
            user_id=str(user_id),
            total_cost=apply_ai_testing_markup(Decimal(str(provider_cost))),
            usage_type="ai_testing",
            usage_subtype="noclick/testing-1",
            quantity=Decimal(str(total_tokens or 0)),
            unit_type="tokens",
            user_resource=False,
            organization_id=state.get("organization_id"),
            # metadata.workflow_id stamps itself at the write choke point via
            # the CURRENT_WORKFLOW_ID context — fabricate runs inside the run.
            metadata={
                "conversation_id": conversation_id,
                "tool_name": tool_name,
                "_internal_model": REHEARSAL_MODEL,
            },
        )
        await usage_tracker.track_usage_event(event)
    except Exception as e:
        logger.warning("[rehearsal] failed to record Agent Testing usage: %s", e)


async def _remember(conversation_id: str, ask: str, response: str) -> None:
    """Persist one exchange, refreshing the TTL so a live rehearsal cannot expire
    out from under the agent mid-turn."""
    from utils.redis_client import get_shared_redis

    client = get_shared_redis()
    if client is None:
        return
    raw = await client.get(_key(conversation_id))
    if not raw:
        return
    state = json.loads(raw)
    state.setdefault("calls", []).append({"ask": ask, "response": response})
    state["calls"] = state["calls"][-MAX_REMEMBERED_CALLS:]
    await client.set(_key(conversation_id), json.dumps(state), ex=REHEARSAL_TTL_S)


async def resolve_trigger_node_id(
    workflow_nodes: List[Dict[str, Any]],
    workflow_edges: Optional[List[Dict[str, Any]]],
    node_type: str,
) -> Optional[str]:
    """The saved graph's node of ``node_type`` that the fabricated event lands on.

    Resolved from the graph rather than pinned in the scenario so a template can
    be rebuilt or re-imported — which changes node ids — without every scenario
    silently pointing at a node that no longer exists. Filtered by the same
    ``can_stage_trigger`` the picker uses: a provider-wired node of the right
    type must not swallow the event a differently-wired sibling would receive.
    """
    from nodes.agent.rehearsal_scenarios import can_stage_trigger

    for node in workflow_nodes or []:
        if node.get("type") != node_type:
            continue
        if not can_stage_trigger(node, workflow_nodes, workflow_edges):
            continue
        return node.get("id")
    return None


def rehearsal_conversation_id(workflow_id: str, nonce: str) -> str:
    """Conversation key for one rehearsal.

    Distinct per run so two rehearsals of the same workflow never share a
    fabricated world, and prefixed so it is obvious in logs and audit rows that
    the tool calls under it were staged.
    """
    return f"{REHEARSAL_CONVERSATION_PREFIX}{workflow_id}:{nonce}"


def is_rehearsal_conversation(conversation_id: Optional[str]) -> bool:
    """Pure prefix check for hot paths where the async Redis gate is too heavy
    (per-node in the execution runner). The ids are minted by run_rehearsal;
    a forged prefix fails SAFE — it makes nodes skip, never execute.
    ``is_rehearsing`` stays the authority wherever fabrication happens."""
    return bool(conversation_id) and str(conversation_id).startswith(
        REHEARSAL_CONVERSATION_PREFIX
    )


def effective_conversation_key(
    run_conversation_id: Optional[str],
    event_ck: Optional[str],
    config_ck: Optional[str],
) -> Optional[str]:
    """Which conversation key an agent turn adopts.

    Normally the fired trigger's key wins — it is the medium's native thread
    identity (Telegram chat id, Slack thread). In a rehearsal the CONFIG key
    wins instead: run_rehearsal stamps it with the staged run's isolation key,
    and following the event's key — which is the FIXTURE'S chat id — would
    write fabricated exchanges into the very history a real chat with that id
    resumes, and interleave repeat runs of one scenario into a single session
    (the tool_call_ids-without-responses failure the stamp exists to prevent).
    """
    if is_rehearsal_conversation(run_conversation_id):
        return config_ck or event_ck
    return event_ck or config_ck


@lru_cache(maxsize=1)
def rehearsal_excluded_node_types() -> frozenset:
    """Node types a rehearsal must never really execute.

    The fabricated world answers the AGENT'S tool calls; graph nodes are a
    separate execution path, and any of them that reaches an external service —
    a send node wired after the agent, an HTTP call, a sub-workflow — would act
    for real, credentials and all. Derived from the registry (any node whose
    config model carries a credential) rather than hand-listed, so a new
    integration node is excluded the moment it is registered; the union covers
    the credential-less external actors. Agents are exempt — the agent running
    for real is the entire point.
    """
    from nodes.core.registry import NODE_REGISTRY

    found = set()
    for node_type, node_cls in NODE_REGISTRY.items():
        try:
            schema = node_cls.get_config_schema()
        except Exception:  # a broken schema fails its own tests, not the gate
            continue
        # A node with a real credential class renders `credentials` as an
        # anyOf/$ref; credential-less nodes render `"type": "null"`. NOT the
        # `x-credential-type` marker — that only stamps some providers, and
        # missed every API-key node (Telegram was the tell).
        cred = (schema.get("properties", {}) or {}).get("credentials") or {}
        if isinstance(cred, dict) and (cred.get("$ref") or cred.get("anyOf")):
            found.add(node_type)
    found.discard("agent")
    # Credential-less nodes with real external effects: the self-notification
    # email (charges credits, sends mail), raw HTTP, and nested workflows
    # (whose inner nodes never see this run's rehearsal conversation key).
    found |= {"automation-send-email", "automation-http-request", "noclick"}
    return frozenset(found)


async def _emit_progress(
    state: Optional[Dict[str, Any]],
    conversation_id: str,
    **fields: Any,
) -> None:
    """Tell whoever is watching. Never raises — a dropped frame costs a row in a
    trace, and must never fail the run it is describing."""
    state = state or {}
    if state.get("public"):
        # Anonymous watchers have no socket: buffer every frame in Redis for
        # the public polling endpoint. Same never-raises doctrine.
        try:
            await _push_public_frame(conversation_id, fields)
        except Exception as e:
            logger.warning("[rehearsal] public frame push failed: %s", e)
    sid, user_id = state.get("sid"), state.get("user_id")
    if not sid and not user_id:
        return
    try:
        from wss.sender.events import RehearsalProgressEvent

        event = RehearsalProgressEvent(conversation_id=conversation_id, **fields)

        # Straight to the socket that asked. The relay reaches a user's OTHER
        # tabs but only if they subscribe to the user room, which a standalone
        # surface has no reason to do — the frames were being produced and
        # delivered nowhere.
        if sid:
            from utils.socket_singleton import get_sio
            from wss.sender import send_event

            sio = get_sio()
            if sio is not None:
                await send_event(sio, sid, event)
                return

        if user_id:
            from utils.event_relay import broadcast_to_user_safe

            await broadcast_to_user_safe(user_id, event)
    except Exception as e:
        # warning, not debug: a dropped step frame costs a trace row, but a
        # dropped TERMINAL frame leaves the watcher spinning forever — the
        # done-frame validation failure hid at debug level (2026-08-21).
        logger.warning("[rehearsal] progress frame dropped (kind=%s): %s",
                       fields.get("kind"), e)


_PUBLIC_FRAMES_TTL_S = 900


def public_frames_key(conversation_id: str) -> str:
    return f"rehearsal:frames:{conversation_id}"


async def _push_public_frame(conversation_id: str, fields: Dict[str, Any]) -> None:
    from utils.redis_client import get_shared_redis

    client = get_shared_redis()
    if client is None:
        return
    key = public_frames_key(conversation_id)
    await client.rpush(key, json.dumps({"conversation_id": conversation_id, **fields}))
    await client.expire(key, _PUBLIC_FRAMES_TTL_S)


async def read_public_frames(conversation_id: str, after: int = 0) -> list:
    """Frames [after:] for the public polling endpoint. The conversation id is
    the capability — unguessable, minted per run, TTL-bounded."""
    from utils.redis_client import get_shared_redis

    client = get_shared_redis()
    if client is None:
        return []
    raw = await client.lrange(public_frames_key(conversation_id), after, -1)
    out = []
    for item in raw:
        try:
            out.append(json.loads(item))
        except (ValueError, TypeError):
            continue
    return out


async def emit_rehearsal_finished(
    conversation_id: str, reply: Optional[str], error: Optional[str] = None
) -> None:
    """Final frame. Sent before the session is torn down, since teardown drops
    the user_id the broadcast needs."""
    state = await load_rehearsal(conversation_id)
    await _emit_progress(
        state,
        conversation_id,
        kind="failed" if error else "done",
        reply=reply,
        error=error,
    )
