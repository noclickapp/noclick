"""Ambient tools made available to agents by this installation.

The registry below advertises each tool independently of workflow-wired
providers. Server-side policy enforces the caller context: interactive
edits require user approval, public share visitors cannot edit owner
workflows, and optional mail tools require a configured reply channel.
"""
import hashlib
import logging
import re
import uuid
from typing import Any, Dict, Optional, Tuple

from nodes.agent.agent_memory import MEMORY_READ_TOOL_TYPE, MEMORY_WRITE_TOOL_TYPE
from utils.edition import is_local_edition
from utils.prompts import PromptPack

logger = logging.getLogger(__name__)

PROMPTS = PromptPack("agent_platform_tools")

SUBMIT_FEEDBACK_TOOL = "submit_feedback"
PROMPT_BUILDER_TOOL = "prompt_builder"
BUILDER_RESPOND_TOOL = "builder_respond"
DESCRIBE_WORKFLOW_TOOL = "describe_workflow"
EMAIL_USER_TOOL = "email_user"
MESSAGE_COORDINATOR_TOOL = "message_coordinator"
REQUEST_CONNECTION_TOOL = "request_connection"
WAKE_ME_TOOL = "wake_me"
TELL_PARENT_TOOL = "tell_parent"
# The tool type of every tool a platform offers an agent to manage other agents.
AGENTS_TOOL_TYPE = "agents"
# The tool type of every tool a platform defines whole for a turn (``PLATFORM_TOOLS_KEY``).
PLATFORM_TOOL_TYPE = "platform"
# Excluded from per-harness capability gates (e.g. codex's API-key model gate):
# platform tools are ambient, not user-wired capability the run depends on.
PLATFORM_TOOL_TYPES = {
    "submit_feedback", "prompt_builder", "builder_respond", "describe_workflow",
    "email_user", "message_coordinator", "request_connection", "wake_me", "tell_parent", AGENTS_TOOL_TYPE,
    PLATFORM_TOOL_TYPE,
    MEMORY_READ_TOOL_TYPE, MEMORY_WRITE_TOOL_TYPE,
}
# The runtime config key a platform sets on an agent's turn to offer
# request_connection: {"integrations": [names] | "*", ...whatever it needs back}.
# Keep it the same on every turn of a conversation: it rides the tool config a
# warm CLI sandbox is fingerprinted by, so a per-turn value cold-starts each turn.
CONNECTION_REQUESTS_KEY = "_connectionRequests"
# The same for wake_me: whatever the platform needs to find the conversation, per-thread stable.
WAKE_ME_KEY = "_wakeMe"
# And tell_parent, on an agent another agent gave a task to.
TELL_PARENT_KEY = "_tellParent"
# And the tools to manage other agents (AGENT_COORDINATION): {"tools": [names], ...}.
AGENT_TOOLS_KEY = "_agentTools"
# And tools a platform defines whole (a bucket's operations), each called through
# PLATFORM_TOOLS with its spec: {"tools": [{name, description, parameters, spec,
# bound_arguments?}]}, the parameters already without what bound_arguments fix.
PLATFORM_TOOLS_KEY = "_platformTools"

def _described(name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
    """A platform tool's param, its description read from the ``agent_platform_tools`` prompt pack."""
    return {"type": "function", "function": {"name": name, "description": PROMPTS.DESCRIPTIONS[name],
                                             "parameters": parameters}}


def _about(key: str, **schema: Any) -> Dict[str, Any]:
    """A parameter's schema with its description (``tool.parameter`` in the pack)."""
    return {**schema, "description": PROMPTS.PARAMETERS[key]}


def _tell_parent_param() -> Dict[str, Any]:
    return _described(TELL_PARENT_TOOL, {
        "type": "object",
        "properties": {"message": _about("tell_parent.message", type="string")},
        "required": ["message"],
    })


def _wake_me_params() -> Tuple[Dict[str, Any], ...]:
    """wake_me, list_wakeups and cancel_wakeup."""
    return (
        _described(WAKE_ME_TOOL, {
            "type": "object",
            "properties": {
                "note": _about("wake_me.note", type="string"),
                "at": _about("wake_me.at", type="string"),
                "after_minutes": _about("wake_me.after_minutes", type="number"),
                "operation_id": _about("wake_me.operation_id", type="string"),
                "every": _about("wake_me.every", type="string"),
                "wakeup_id": _about("wake_me.wakeup_id", type="string"),
                "conversation": _about("wake_me.conversation", type="string"),
            },
            "required": ["note"],
        }),
        _described("list_wakeups", {
            "type": "object",
            "properties": {"conversation": _about("list_wakeups.conversation", type="string")},
        }),
        _described("cancel_wakeup", {
            "type": "object",
            "properties": {"wakeup_id": _about("cancel_wakeup.wakeup_id", type="string"),
                           "conversation": _about("cancel_wakeup.conversation", type="string")},
            "required": ["wakeup_id"],
        }),
    )


def _request_connection_param(integrations: Any) -> Dict[str, Any]:
    integration: Dict[str, Any] = _about("request_connection.integration", type="string")
    if isinstance(integrations, list):
        integration["enum"] = list(integrations)
    return _described(REQUEST_CONNECTION_TOOL, {
        "type": "object",
        "properties": {
            "integration": integration,
            "operations": _about("request_connection.operations", type="array", items={"type": "string"}),
            "name": _about("request_connection.name", type="string"),
            "reason": _about("request_connection.reason", type="string"),
        },
        "required": ["integration", "reason"],
    })


def connection_requests_of(node: Any) -> Optional[Dict[str, Any]]:
    """The turn's request_connection spec, when a platform offers the tool."""
    data = getattr(node, "node_data", None) or {}
    config = data.get("config") if isinstance(data.get("config"), dict) else {}
    spec = config.get(CONNECTION_REQUESTS_KEY) or data.get(CONNECTION_REQUESTS_KEY)
    return spec if isinstance(spec, dict) and spec.get("integrations") else None


def _runtime_spec(node: Any, key: str) -> Optional[Dict[str, Any]]:
    data = getattr(node, "node_data", None) or {}
    config = data.get("config") if isinstance(data.get("config"), dict) else {}
    spec = config.get(key) or data.get(key)
    return spec if isinstance(spec, dict) and spec else None


def wake_me_of(node: Any) -> Optional[Dict[str, Any]]:
    """The turn's wake_me spec, when a platform offers the tool."""
    return _runtime_spec(node, WAKE_ME_KEY)


def tell_parent_of(node: Any) -> Optional[Dict[str, Any]]:
    """The turn's tell_parent spec, when a platform offers the tool."""
    return _runtime_spec(node, TELL_PARENT_KEY)


def agent_tools_of(node: Any) -> Optional[Dict[str, Any]]:
    """The turn's spec for the tools that manage other agents, when a platform offers them."""
    return _runtime_spec(node, AGENT_TOOLS_KEY)


def platform_tools_of(node: Any) -> Optional[Dict[str, Any]]:
    """The tools a platform defines whole for the turn, when it offers some."""
    return _runtime_spec(node, PLATFORM_TOOLS_KEY)

def _message_coordinator_param() -> Dict[str, Any]:
    return _described(MESSAGE_COORDINATOR_TOOL, {
        "type": "object",
        "properties": {"message": _about("message_coordinator.message", type="string")},
        "required": ["message"],
    })


_FEEDBACK_MAX_LEN = 4000
_PROMPT_MAX_LEN = 8000
_FEEDBACK_DEDUPE_HOURS = 24


def submit_feedback_param() -> Dict[str, Any]:
    return _described(SUBMIT_FEEDBACK_TOOL, {
        "type": "object",
        "properties": {
            "feedback": _about("submit_feedback.feedback", type="string"),
            "issue_key": {"type": "string", "description": PROMPTS.PARAMETERS["submit_feedback.issue_key"],
                          "pattern": "^[a-z0-9][a-z0-9_]{2,79}$"},
        },
        "required": ["feedback", "issue_key"],
    })


def _prompt_builder_param() -> Dict[str, Any]:
    return _described(PROMPT_BUILDER_TOOL, {
        "type": "object",
        "properties": {"prompt": _about("prompt_builder.prompt", type="string")},
        "required": ["prompt"],
    })


def _describe_workflow_param() -> Dict[str, Any]:
    return _described(DESCRIBE_WORKFLOW_TOOL, {
        "type": "object",
        "properties": {"focus": _about("describe_workflow.focus", type="string")},
        "required": [],
    })


def _builder_respond_param() -> Dict[str, Any]:
    return _described(BUILDER_RESPOND_TOOL, {
        "type": "object",
        "properties": {
            "answers": {"type": "object", "description": PROMPTS.PARAMETERS["builder_respond.answers"],
                        "additionalProperties": {"type": "string"}},
            "message": _about("builder_respond.message", type="string"),
        },
        "required": [],
    })


def _email_user_param() -> Dict[str, Any]:
    return _described(EMAIL_USER_TOOL, {
        "type": "object",
        "properties": {
            "subject": _about("email_user.subject", type="string"),
            "body": _about("email_user.body", type="string"),
        },
        "required": ["subject", "body"],
    })


def _platform_pair(param: Dict[str, Any], tool_type: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """(tool_param, tool_config) with the description/schema mirrored into the
    config's ``_description``/``_parameters`` — the tool bundle entry builder
    reads THOSE (same convention as node_op tools), and without them the CLI
    harnesses advertised the tool with no description and no arguments
    (unusable; effectively invisible to the model)."""
    fn = param["function"]
    return param, {
        "tool_type": tool_type,
        "_description": fn["description"],
        "_parameters": fn["parameters"],
    }


def agent_email_available() -> bool:
    """Whether this edition can mint a reply address for ``email_user``."""
    if not is_local_edition():
        return True
    from utils.email_reservation_manager import get_inbound_email_domain

    return bool(get_inbound_email_domain())


async def email_user_offered(pool, user_id: Optional[str], enabled: bool, in_iteration: bool = False) -> bool:
    """Whether this turn offers email_user: the node flag, the edition's mail
    channel, no iteration fan-out, and an owner with an email address (a
    phone-only account has none, so the tool could only fail). ``pool`` None =
    the native pool, resolved only once the cheap checks pass."""
    if not (enabled and user_id and not in_iteration and agent_email_available()):
        return False
    from repositories.users import get_user_email

    if pool is None:
        from utils.database_pool import get_native_pool

        pool = get_native_pool()
    return bool(await get_user_email(pool, user_id))


def build_platform_tools(
    enable_prompt_builder: bool, enable_email_updates: bool = False,
    in_iteration: bool = False, *, enable_coordinator_messages: bool = True,
    connection_requests: Optional[Dict[str, Any]] = None, wake_me: Optional[Dict[str, Any]] = None,
    tell_parent: Optional[Dict[str, Any]] = None, agent_tools: Optional[Dict[str, Any]] = None,
    agent_memory: Optional[Dict[str, Any]] = None,
    platform_tools: Optional[Dict[str, Any]] = None,
) -> list:
    """``(tool_param, tool_config)`` pairs to append to the agent's collected
    tool set. The config carries the tool type and its model-facing schema;
    execution context comes from the active agent turn."""
    from nodes.agent.agent_memory import memory_params
    from utils.capabilities import (
        AGENT_COORDINATION, AGENT_MEMORY, CONNECTION_REQUESTS, PARENT_UPDATES, PLATFORM_TOOLS, WAKEUPS, capability,
    )

    pairs = [_platform_pair(submit_feedback_param(), "submit_feedback")]
    if connection_requests and capability(CONNECTION_REQUESTS) is not None:
        param, cfg = _platform_pair(_request_connection_param(connection_requests["integrations"]),
                                    REQUEST_CONNECTION_TOOL)
        pairs.append((param, {**cfg, "spec": connection_requests}))
    if wake_me and capability(WAKEUPS) is not None:
        # One tool type for the three: the spec's ``tool`` says which was called.
        for wakeup_param in _wake_me_params():
            param, cfg = _platform_pair(wakeup_param, WAKE_ME_TOOL)
            pairs.append((param, {**cfg, "spec": {**wake_me, "tool": param["function"]["name"]}}))
    if tell_parent and capability(PARENT_UPDATES) is not None:
        param, cfg = _platform_pair(_tell_parent_param(), TELL_PARENT_TOOL)
        pairs.append((param, {**cfg, "spec": tell_parent}))
    coordination = capability(AGENT_COORDINATION) if agent_tools else None
    if coordination is not None:
        for param in coordination.tools(agent_tools):
            param, cfg = _platform_pair(param, AGENTS_TOOL_TYPE)
            pairs.append((param, {**cfg, "spec": {**agent_tools, "tool": param["function"]["name"]}}))
    if agent_memory and capability(AGENT_MEMORY) is not None:
        for param, tool_type in memory_params(agent_memory):
            param, cfg = _platform_pair(param, tool_type)
            pairs.append((param, {**cfg, "spec": {**agent_memory, "tool": param["function"]["name"]}}))
    if platform_tools and capability(PLATFORM_TOOLS) is not None:
        from nodes.agent.tool_binding import BOUND_ARGUMENTS_KEY

        for tool in platform_tools.get("tools") or []:
            param, cfg = _platform_pair({"type": "function", "function": {
                "name": tool["name"], "description": tool["description"], "parameters": tool["parameters"],
            }}, PLATFORM_TOOL_TYPE)
            bound = {BOUND_ARGUMENTS_KEY: tool["bound_arguments"]} if tool.get("bound_arguments") else {}
            pairs.append((param, {**cfg, "spec": tool["spec"], **bound}))
    if enable_coordinator_messages:
        pairs.append(_platform_pair(_message_coordinator_param(), "message_coordinator"))
    if enable_prompt_builder:
        pairs.append(_platform_pair(_prompt_builder_param(), "prompt_builder"))
        pairs.append(_platform_pair(_builder_respond_param(), "builder_respond"))
        pairs.append(_platform_pair(_describe_workflow_param(), "describe_workflow"))
    # email_user requires a configured inbound/reply mail channel. Community
    # installs advertise it only after the operator configures that channel.
    # Hosted callers pass email_user_offered()'s verdict (owner has an email).
    if enable_email_updates and not in_iteration and agent_email_available():
        pairs.append(_platform_pair(_email_user_param(), "email_user"))
    return pairs


def inputs_are_iteration_fanout(inputs: Dict[str, Any]) -> bool:
    """Whether this node is executing once per item inside an iteration body."""
    return any(
        isinstance(value, dict) and value.get("isIterationNode") is True
        for value in inputs.values()
    )


def anchored_builder_prompt(prompt: str, node_id: Optional[str]) -> str:
    """The prompt the BUILDER receives: the agent's ask, anchored to the
    requesting node. Without the anchor a multi-agent workflow misroutes
    'add telegram support to yourself' — the builder sees only the graph and
    guesses which agent meant 'yourself'. Composed ONCE here (rides the
    proposal for the interactive approve; used directly by the headless run)
    so the two paths can't drift."""
    if not node_id:
        return prompt
    return f"{prompt}\n\n{PROMPTS.builder_anchor(node_id)}"


def platform_tools_note(
    enable_prompt_builder: bool, enable_email_updates: bool = False,
    in_iteration: bool = False,
) -> str:
    """Per-turn steering for CLI harnesses (rides the '--- Sandbox environment
    ---' block): where NoClick tools come from and how to gain more. Without
    it, a model may install an unusable local bridge instead of requesting a
    workflow capability. CLI models follow their harness's extension idioms
    unless explicitly told the platform's. The submit_feedback steering is
    UNCONDITIONAL —
    that tool is always injected, so disabling prompt_builder must not strip
    the report-platform-bugs guidance with it."""
    return PROMPTS.platform_tools_note(
        prompt_builder=enable_prompt_builder,
        email=enable_email_updates and not in_iteration and agent_email_available(),
    )


async def owner_presence_note(user_id: str) -> str:
    """The per-turn platform note on whether the workflow owner is in the app (steering email_user)."""
    from utils.user_presence import describe_owner_presence

    return PROMPTS.presence_note(await describe_owner_presence(user_id))


# Each builder outcome event, and the payload key it's marked relayed by.
_BUILDER_RELAY_KEYS = {"builder_decision": "proposal_id", "builder_ask": "relay_id", "builder_result": "relay_id"}


def builder_updates_note(events: list) -> Tuple[str, list]:
    """``(note, relay_keys)`` for a conversation's undelivered builder outcome events (card verdicts, parked asks
    with their bridge links, run results): the platform note composed from them, and the keys that mark them
    relayed."""
    lines, relay_keys = [], []
    for event in events:
        kind, payload = event["kind"], event["payload"]
        if kind in _BUILDER_RELAY_KEYS:
            lines.append(PROMPTS.builder_update(kind, payload))
            relay_keys.append((kind, payload.get(_BUILDER_RELAY_KEYS[kind])))
    return PROMPTS.builder_updates(lines), relay_keys


def prompt_builder_mode(conversation_key: Optional[str]) -> str:
    """'interactive' | 'shared' | 'background' — see the module docstring.

    The interface-chat prefix is the FE's DEFAULT_INTERFACE_CONV_KEY: the
    default thread is the bare constant, later threads append ``_<suffix>``
    (useAgentChatConversations), so a prefix match covers both."""
    ck = conversation_key or ""
    if ck.startswith("share:"):
        return "shared"
    if ck.startswith("__interface_chat__"):
        return "interactive"
    return "background"


async def submit_feedback_impl(
    *,
    pool,
    user_id: Optional[str],
    workflow_id: Optional[str],
    node_id: Optional[str],
    conversation_id: Optional[str],
    model: Optional[str],
    feedback: str,
    issue_key: Optional[str] = None,
    execution_id: Optional[str] = None,
) -> Dict[str, Any]:
    from utils.feedback import record_feedback

    feedback = (feedback or "").strip()
    if not feedback:
        return {"success": False, "error": "feedback must be a non-empty string"}
    if not user_id:
        return {"success": False, "error": "no user context for this run"}
    normalized_issue_key = _normalize_feedback_issue_key(issue_key, feedback)
    agent_dedupe_key = ":".join(
        (str(workflow_id or "unknown"), str(node_id or "unknown"), normalized_issue_key)
    )
    inserted = await record_feedback(
        pool,
        user_id=user_id,
        feedback_type="agent_bug",
        message=feedback[:_FEEDBACK_MAX_LEN],
        metadata={
            "source": "agent_tool",
            "workflow_id": workflow_id,
            "node_id": node_id,
            "execution_id": execution_id,
            "conversation_id": conversation_id,
            "model": model,
            "agent_issue_key": normalized_issue_key,
            "agent_dedupe_key": agent_dedupe_key,
        },
        dedupe_key=agent_dedupe_key,
        dedupe_window_hours=_FEEDBACK_DEDUPE_HOURS,
    )
    if not inserted:
        return {
            "success": True,
            "status": "duplicate_suppressed",
            "message": (
                "This root cause was already reported in the last 24 hours. "
                "Do not call submit_feedback for it again; continue the task."
            ),
        }
    return {
        "success": True,
        "status": "submitted",
        "message": "Bug report submitted to the NoClick engineering team.",
    }


def _normalize_feedback_issue_key(issue_key: Optional[str], feedback: str) -> str:
    """Normalize model-provided keys and tolerate older tool schemas."""
    normalized = re.sub(r"[^a-z0-9]+", "_", (issue_key or "").strip().lower())
    normalized = normalized.strip("_")[:80]
    if len(normalized) >= 3:
        return normalized
    # A hash dedupes verbatim calls from an older schema without rejecting them.
    digest = hashlib.sha256(feedback.casefold().encode("utf-8")).hexdigest()[:16]
    return f"legacy_{digest}"


async def prompt_builder_impl(
    *,
    pool,
    user_id: Optional[str],
    workflow_id: Optional[str],
    node_id: Optional[str],
    conversation_id: Optional[str],
    conversation_key: Optional[str],
    prompt: str,
) -> Dict[str, Any]:
    prompt = (prompt or "").strip()
    if not prompt:
        return {"success": False, "error": "prompt must be a non-empty string"}
    if len(prompt) > _PROMPT_MAX_LEN:
        return {"success": False, "error": f"prompt exceeds {_PROMPT_MAX_LEN} characters"}
    if not (user_id and workflow_id):
        return {"success": False, "error": "no workflow context for this run"}

    mode = prompt_builder_mode(conversation_key)
    if mode == "shared":
        return {
            "success": False,
            "error": "prompt_builder is not available on shared agent links.",
        }

    if mode == "interactive":
        proposal = {
            "prompt": prompt,
            "node_id": node_id,
            "proposal_id": uuid.uuid4().hex[:12],
            # What the approve actually submits — the card DISPLAYS `prompt`.
            "anchored_prompt": anchored_builder_prompt(prompt, node_id),
        }
        await _emit_builder_approval_card(user_id=user_id, conversation_id=conversation_id, proposal=proposal)
        # Persist the card as a conversation event — the chat's reconcile poll
        # ADOPTS the persisted transcript wholesale on turn end, so a live-only
        # card vanished the moment the turn finished (2026-07-18). proposal_id
        # dedupes the live frame against the adopted copy on the client.
        if conversation_id:
            from datetime import datetime, timezone

            from repositories.conversation import ConversationRepo

            try:
                await ConversationRepo(pool).append_chat_event(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    workflow_id=workflow_id,
                    node_id=node_id,
                    event={
                        "builder_prompt": proposal,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                    label=None,
                    model=None,
                )
            except Exception:
                logger.error(
                    "[prompt_builder] failed to persist approval card event", exc_info=True
                )
        return {
            "success": True,
            "status": "approval_requested",
            "message": (
                "The user has been shown your proposed builder prompt in the chat "
                "and asked to approve it. If they approve, the builder will run "
                "with it. You will receive a '--- Platform note ---' with their "
                "verdict (approved/dismissed) alongside their next message — "
                "until then you do NOT know the outcome, so don't assume either "
                "way, and do not resubmit the same prompt."
            ),
        }

    from utils.async_helpers import spawn

    spawn(
        _run_headless_builder_edit(
            user_id=user_id, workflow_id=workflow_id, node_id=node_id, prompt=prompt,
            agent_conversation_id=conversation_id,
        ),
        name=f"agent-prompt-builder:{workflow_id}:{node_id}",
    )
    return {
        "success": True,
        "status": "builder_started",
        "message": (
            "A headless builder run was started with your prompt. Changes apply "
            "to the workflow as the run completes (typically within a few "
            "minutes); this run's graph is NOT updated mid-flight. You will be "
            "WOKEN with a '--- Platform note ---' the moment the builder "
            "finishes or pauses on questions: answer design questions yourself "
            "with builder_respond to keep it moving, and for credential inputs "
            "share the note's public no-login link through your channel so a "
            "human can connect the account."
        ),
    }


async def _emit_builder_approval_card(
    *, user_id: str, conversation_id: Optional[str], proposal: Dict[str, Any],
) -> None:
    """Surface the approval card through the event relay so any open tab can
    receive it, even when no live socket id is available to this handler."""
    from utils.event_relay import broadcast_to_user_safe
    from wss.sender.events import ChatMessageEvent

    await broadcast_to_user_safe(user_id, ChatMessageEvent(
        conversation_id=conversation_id,
        builder_prompt=proposal,
    ))


async def _run_headless_builder_edit(
    *, user_id: str, workflow_id: str, node_id: Optional[str], prompt: str,
    agent_conversation_id: Optional[str] = None,
) -> None:
    """Run the AI builder on the workflow's CURRENT saved graph as the owner.
    The run persists a normal builder conversation (visible in the sidebar
    history) and its progress events ride the owner's event relay, so an open tab
    watches it live. Failures are logged — the tool call already returned."""
    try:
        from utils.socket_singleton import get_sio
        from wss.handlers.workflow_builder_handler import WorkflowBuilderHandler
        from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler
        from wss.receiver.client_events import WorkflowBuilderEditRequest

        sio = get_sio()
        fetched = await WorkflowExecutionHandler(sio)._fetch_workflow(workflow_id, user_id)
        if not fetched:
            logger.warning(
                f"[prompt_builder] workflow {workflow_id} not found / no access for {user_id}"
            )
            return
        nodes, edges, _org, _vars, _settings = fetched
        request = WorkflowBuilderEditRequest(
            request_id=f"agent-builder-{uuid.uuid4().hex[:8]}",
            current_graph={"nodes": nodes, "edges": edges},
            edit_prompt=anchored_builder_prompt(prompt, node_id),
            conversation_id=f"agent-builder:{workflow_id}:{node_id}:{uuid.uuid4().hex[:8]}",
            # agent_conversation_id/agent_node_id: the return address for the
            # builder outcome relay (builder_ask bridge links + builder_result).
            user_context={
                "workflow_id": workflow_id,
                "source": "agent_prompt_builder",
                "agent_conversation_id": agent_conversation_id,
                "agent_node_id": node_id,
            },
        )
        logger.info(
            f"[prompt_builder] headless builder run starting: workflow={workflow_id} "
            f"agent={node_id}"
        )
        await WorkflowBuilderHandler(sio).edit_workflow(
            "", request, caller_user_id=user_id,
        )
    except Exception:
        logger.error(
            f"[prompt_builder] headless builder run failed for {workflow_id}",
            exc_info=True,
        )


async def describe_workflow_impl(
    pool,
    *,
    user_id: Optional[str],
    workflow_id: Optional[str],
    node_id: Optional[str],
    focus: Optional[str] = None,
    in_iteration: bool = False,
) -> Dict[str, Any]:
    """Free read-only introspection: the SAME snapshot rendering the builder
    brain reads (GraphState.to_xml), anchored on the asking agent — wired
    triggers, tool providers + allowlists, and downstream consumers called
    out so the agent understands its own position before proposing edits."""
    if not (user_id and workflow_id):
        return {"success": False, "error": "no workflow context for this run"}
    row = await pool.fetchrow(
        "SELECT name, workflow FROM workflows WHERE id = $1::uuid", workflow_id
    )
    if not row:
        return {"success": False, "error": "workflow not found"}
    workflow = row["workflow"]
    if isinstance(workflow, str):
        import json as _json

        workflow = _json.loads(workflow)
    workflow = workflow or {}

    from coder.workflow.graph_state import GraphState
    from utils.credential_health import fetch_credential_health_for_ids

    gs = GraphState.from_dict(workflow)
    # Attached-but-dead credentials must read ✗ here, not ✓ — this snapshot is
    # what the agent uses to rule causes in/out when its channel goes silent.
    gs._credential_health = await fetch_credential_health_for_ids(
        pool, gs.attached_credential_ids()
    )
    # Live public URLs (published apps, hosted MCP links) — read-only here:
    # describing a workflow must never mint a capability. Fails open.
    from utils.capabilities import PUBLIC_ENDPOINTS, capability

    fetch_public_endpoints = capability(PUBLIC_ENDPOINTS)
    if fetch_public_endpoints is not None:
        try:
            gs._public_endpoints = await fetch_public_endpoints(pool, workflow_id)
        except Exception:
            logger.warning("[describe_workflow] public endpoint fetch failed", exc_info=True)
    snapshot = gs.to_xml()

    anchor = focus or node_id
    notes = []
    edges = workflow.get("edges") or []
    nodes_by_id = {n.get("id"): n for n in (workflow.get("nodes") or [])}

    def _cfg(n):
        d = n.get("data") or {}
        return d.get("config") or n.get("config") or {}

    if anchor and anchor in nodes_by_id:
        into = [e for e in edges if e.get("target") == anchor]
        providers = [e for e in into if e.get("targetHandle") == "bottom"]
        inputs = [e for e in into if e.get("targetHandle") != "bottom"]
        out = [e for e in edges if e.get("source") == anchor]
        if inputs:
            notes.append("Feeds INTO you (triggers/dataflow): " + ", ".join(
                f"{e.get('source')} ({nodes_by_id.get(e.get('source'), {}).get('type', '?')})"
                for e in inputs))
        if providers:
            import json
            from nodes.agent.node_op_tools import effective_provider_operations
            parts = []
            for e in providers:
                src = nodes_by_id.get(e.get("source"), {})
                ops = effective_provider_operations(src.get('type', ''), _cfg(src))
                parts.append(f"{e.get('source')} ({src.get('type', '?')}"
                             + (f"; allowlisted ops: {', '.join(op if isinstance(op, str) else json.dumps(op) for op in ops)}" if ops else "") + ")")
            notes.append("Your TOOL PROVIDERS (bottom handle): " + ", ".join(parts))
        if out:
            notes.append(
                "Nodes CONSUMING your output (breaking your output shape breaks them): "
                + ", ".join(f"{e.get('target')} ({nodes_by_id.get(e.get('target'), {}).get('type', '?')})"
                            for e in out))
        if not (into or out):
            notes.append("You are not wired to any other nodes.")
        # The graph shows WIRED capability only — without this note, models
        # read "no email node" as "cannot email" even with email_user in
        # their own tool list (2026-07-19).
        cfg = _cfg(nodes_by_id[anchor])
        ambient = ["submit_feedback"]
        if cfg.get("enable_prompt_builder") != "false":
            ambient += ["prompt_builder", "builder_respond", "describe_workflow"]
        if await email_user_offered(
            pool, user_id, cfg.get("enable_email_updates") != "false", in_iteration,
        ):
            ambient.append("email_user (emails the workflow owner directly — needs NO email node)")
        notes.append(
            "Your ambient NoClick platform tools are NOT graph nodes and never "
            "appear above: " + ", ".join(ambient) + "."
        )

    from utils.workflow_readiness import readiness_report
    readiness = await readiness_report(pool, workflow_id, workflow, credential_health=gs._credential_health)
    return {
        "success": True,
        "workflow_name": row["name"],
        "readiness": readiness,
        "your_node_id": node_id,
        "position_notes": notes,
        "snapshot": snapshot,
    }


async def email_user_impl(
    pool,
    *,
    user_id: Optional[str],
    organization_id: Optional[str],
    workflow_id: Optional[str],
    node_id: Optional[str],
    conversation_id: Optional[str],
    subject: str,
    body: str,
    execution_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Email the workflow owner (utils/agent_email.py owns the engine:
    owner-resolved recipient, credit gate + flat charge, execution/daily caps,
    reply channel, per-node unsubscribe)."""
    if not (user_id and workflow_id and node_id):
        return {"success": False, "error": "no workflow context for this run"}
    try:
        from utils.agent_email import send_agent_email

        return await send_agent_email(
            pool,
            user_id=user_id,
            organization_id=organization_id,
            workflow_id=workflow_id,
            node_id=node_id,
            conversation_id=conversation_id,
            subject=subject,
            body=body,
            execution_id=execution_id,
        )
    except Exception as exc:
        logger.error(f"[email_user] send failed for {workflow_id}/{node_id}", exc_info=True)
        return {"success": False, "error": f"email send failed: {exc}"}


async def builder_respond_impl(
    pool,
    *,
    user_id: Optional[str],
    workflow_id: Optional[str],
    conversation_id: Optional[str],
    answers: Optional[Dict[str, Any]],
    message: Optional[str],
) -> Dict[str, Any]:
    """Answer THIS conversation's newest pending builder ask and resume the
    run as the caller. The ask is resolved via its bridge link row (the
    builder_ask event's relay_id); consuming the link here gives exactly-once
    against a racing bridge submit, and the resume's void seam expires any
    other outstanding links for the ask."""
    values = {str(k): str(v)[:_PROMPT_MAX_LEN] for k, v in (answers or {}).items() if v}
    free_text = str(message or "").strip()[:_PROMPT_MAX_LEN]
    if not (values or free_text):
        return {"success": False, "error": "provide answers and/or message"}
    if not (user_id and workflow_id and conversation_id):
        return {"success": False, "error": "no workflow context for this run"}

    row = await pool.fetchrow(
        """
        SELECT e.value->'builder_ask' AS ask
        FROM conversations, jsonb_array_elements(events) WITH ORDINALITY e
        WHERE conversation_id = $1 AND e.value ? 'builder_ask'
        ORDER BY e.ordinality DESC LIMIT 1
        """,
        conversation_id,
    )
    if not row:
        return {"success": False, "error": "There is no builder question on this conversation."}
    ask = row["ask"]
    if isinstance(ask, str):
        import json as _json

        ask = _json.loads(ask)

    from repositories.builder_bridge import BuilderBridgeRepo

    repo = BuilderBridgeRepo(pool)
    link = await repo.load_pending(str(ask.get("relay_id") or ""))
    if not link or not await repo.mark_answered(str(link["id"])):
        return {
            "success": False,
            "error": (
                "That builder question was already answered — by you, the "
                "user, or someone via the shared link. Wait for the next "
                "platform note."
            ),
        }

    from utils.async_helpers import spawn
    from utils.socket_singleton import get_sio
    from wss.handlers.workflow_builder_handler import WorkflowBuilderHandler

    handler = WorkflowBuilderHandler(get_sio())
    spawn(
        handler.handle_input_response(
            "",
            {
                "conversation_id": link["builder_conversation_id"],
                "ask_id": link["ask_id"],
                "values": values,
                **({"message": free_text} if free_text else {}),
            },
            caller_user_id=str(user_id),
        ),
        name=f"builder-respond-resume:{link['id']}",
    )
    return {
        "success": True,
        "status": "answers_submitted",
        "message": (
            "Submitted — the builder resumed with your answers. You will be "
            "woken with a platform note when it finishes or asks again. "
            "Credential inputs still need a human via the shared link."
        ),
    }


# ── node-context adapters (SDK path via tool_execution.execute_tool) ─────────


async def execute_submit_feedback(node: Any, arguments: Dict[str, Any]) -> Dict[str, Any]:
    from utils.database_pool import get_native_pool

    return await submit_feedback_impl(
        pool=get_native_pool(),
        user_id=getattr(node, "user_id", None),
        workflow_id=getattr(node, "workflow_id", None),
        node_id=getattr(node, "node_id", None),
        execution_id=getattr(node, "execution_id", None),
        conversation_id=getattr(node, "conversation_id", None) or node.chat_routing_id(),
        model=getattr(node, "_effective_model", None),
        feedback=str(arguments.get("feedback") or ""),
        issue_key=str(arguments.get("issue_key") or "") or None,
    )


async def execute_message_coordinator(node: Any, arguments: Dict[str, Any]) -> Dict[str, Any]:
    from coder.coordinator.signals import record_agent_message
    from utils.database_pool import get_native_pool

    return await record_agent_message(
        get_native_pool(),
        user_id=getattr(node, "user_id", None),
        workflow_id=getattr(node, "workflow_id", None),
        node_id=getattr(node, "node_id", None),
        conversation_id=getattr(node, "conversation_id", None) or node.chat_routing_id(),
        message=str(arguments.get("message") or ""),
    )


async def execute_describe_workflow(node: Any, arguments: Dict[str, Any]) -> Dict[str, Any]:
    from utils.database_pool import get_native_pool

    return await describe_workflow_impl(
        get_native_pool(),
        user_id=getattr(node, "user_id", None),
        workflow_id=getattr(node, "workflow_id", None),
        node_id=getattr(node, "node_id", None),
        focus=str(arguments.get("focus") or "") or None,
        in_iteration=bool(getattr(node, "_in_iteration_fanout", False)),
    )


async def execute_builder_respond(node: Any, arguments: Dict[str, Any]) -> Dict[str, Any]:
    from utils.database_pool import get_native_pool

    return await builder_respond_impl(
        get_native_pool(),
        user_id=getattr(node, "user_id", None),
        workflow_id=getattr(node, "workflow_id", None),
        conversation_id=getattr(node, "conversation_id", None) or node.chat_routing_id(),
        answers=arguments.get("answers") if isinstance(arguments.get("answers"), dict) else None,
        message=arguments.get("message"),
    )


async def execute_email_user(node: Any, arguments: Dict[str, Any]) -> Dict[str, Any]:
    from utils.database_pool import get_native_pool

    return await email_user_impl(
        get_native_pool(),
        user_id=getattr(node, "user_id", None),
        organization_id=getattr(node, "organization_id", None),
        workflow_id=getattr(node, "workflow_id", None),
        node_id=getattr(node, "node_id", None),
        conversation_id=getattr(node, "conversation_id", None) or node.chat_routing_id(),
        execution_id=getattr(node, "execution_id", None),
        subject=str(arguments.get("subject") or ""),
        body=str(arguments.get("body") or ""),
    )


async def execute_prompt_builder(node: Any, arguments: Dict[str, Any]) -> Dict[str, Any]:
    from utils.database_pool import get_native_pool

    return await prompt_builder_impl(
        pool=get_native_pool(),
        user_id=getattr(node, "user_id", None),
        workflow_id=getattr(node, "workflow_id", None),
        node_id=getattr(node, "node_id", None),
        conversation_id=getattr(node, "conversation_id", None) or node.chat_routing_id(),
        conversation_key=getattr(node, "_conversation_key", None),
        prompt=str(arguments.get("prompt") or ""),
    )


async def request_connection_impl(pool, spec: Optional[Dict[str, Any]], arguments: Dict[str, Any]) -> Dict[str, Any]:
    from utils.capabilities import CONNECTION_REQUESTS, capability

    provider = capability(CONNECTION_REQUESTS)
    if provider is None or not spec:
        return {"success": False, "error": "Connecting accounts isn't available here."}
    return await provider(pool, spec=spec, arguments=arguments)


async def execute_request_connection(node: Any, arguments: Dict[str, Any], tool_info: Dict[str, Any]) -> Dict[str, Any]:
    from utils.database_pool import get_native_pool

    return await request_connection_impl(get_native_pool(), tool_info.get("spec"), arguments)


async def wake_me_impl(pool, spec: Optional[Dict[str, Any]], arguments: Dict[str, Any]) -> Dict[str, Any]:
    from utils.capabilities import WAKEUPS, capability

    provider = capability(WAKEUPS)
    if provider is None or not spec:
        return {"success": False, "error": "Wake-ups aren't available here."}
    return await provider(pool, spec=spec, arguments=arguments)


async def execute_wake_me(node: Any, arguments: Dict[str, Any], tool_info: Dict[str, Any]) -> Dict[str, Any]:
    from utils.database_pool import get_native_pool

    return await wake_me_impl(get_native_pool(), tool_info.get("spec"), arguments)


async def tell_parent_impl(pool, spec: Optional[Dict[str, Any]], arguments: Dict[str, Any]) -> Dict[str, Any]:
    from utils.capabilities import PARENT_UPDATES, capability

    provider = capability(PARENT_UPDATES)
    if provider is None or not spec:
        return {"success": False, "error": "There's no parent to tell here."}
    return await provider(pool, spec=spec, arguments=arguments)


async def execute_tell_parent(node: Any, arguments: Dict[str, Any], tool_info: Dict[str, Any]) -> Dict[str, Any]:
    from utils.database_pool import get_native_pool

    return await tell_parent_impl(get_native_pool(), tool_info.get("spec"), arguments)


async def agent_tools_impl(pool, spec: Optional[Dict[str, Any]], arguments: Dict[str, Any]) -> Dict[str, Any]:
    from utils.capabilities import AGENT_COORDINATION, capability

    provider = capability(AGENT_COORDINATION)
    if provider is None or not spec:
        return {"success": False, "error": "Managing other agents isn't available here."}
    return await provider.call(pool, spec=spec, arguments=arguments)


async def execute_agent_tool(node: Any, arguments: Dict[str, Any], tool_info: Dict[str, Any]) -> Dict[str, Any]:
    from utils.database_pool import get_native_pool

    return await agent_tools_impl(get_native_pool(), tool_info.get("spec"), arguments)


async def platform_tool_impl(pool, spec: Optional[Dict[str, Any]], arguments: Dict[str, Any]) -> Dict[str, Any]:
    from utils.capabilities import PLATFORM_TOOLS, capability

    provider = capability(PLATFORM_TOOLS)
    if provider is None or not spec:
        return {"success": False, "error": "This tool isn't available here."}
    return await provider(pool, spec=spec, arguments=arguments)


async def execute_platform_tool(node: Any, arguments: Dict[str, Any], tool_info: Dict[str, Any]) -> Dict[str, Any]:
    from utils.database_pool import get_native_pool

    return await platform_tool_impl(get_native_pool(), tool_info.get("spec"), arguments)


async def execute_platform_tool_from_ctx(
    st_config: Dict[str, Any], arguments: Dict[str, Any], pool,
) -> Dict[str, Any]:
    """Pool-local execution for MCP-served tool calls (CLI harnesses):
    everything needed rides the token's tool_ctx (merged into st_config by the
    pool), so this runs identically in any backend process — no executor
    callback required."""
    tool_type = st_config.get("tool_type")
    if tool_type == REQUEST_CONNECTION_TOOL:
        return await request_connection_impl(pool, st_config.get("spec"), arguments)
    if tool_type == WAKE_ME_TOOL:
        return await wake_me_impl(pool, st_config.get("spec"), arguments)
    if tool_type == TELL_PARENT_TOOL:
        return await tell_parent_impl(pool, st_config.get("spec"), arguments)
    if tool_type == AGENTS_TOOL_TYPE:
        return await agent_tools_impl(pool, st_config.get("spec"), arguments)
    if tool_type == PLATFORM_TOOL_TYPE:
        return await platform_tool_impl(pool, st_config.get("spec"), arguments)
    if tool_type in (MEMORY_READ_TOOL_TYPE, MEMORY_WRITE_TOOL_TYPE):
        from nodes.agent.agent_memory import memory_impl

        return await memory_impl(pool, st_config.get("spec"), arguments)
    if tool_type == "submit_feedback":
        return await submit_feedback_impl(
            pool=pool,
            user_id=st_config.get("user_id"),
            workflow_id=st_config.get("workflow_id"),
            node_id=st_config.get("agent_node_id"),
            execution_id=st_config.get("execution_id"),
            conversation_id=st_config.get("conversation_id"),
            model=st_config.get("model"),
            feedback=str(arguments.get("feedback") or ""),
            issue_key=str(arguments.get("issue_key") or "") or None,
        )
    if tool_type == "message_coordinator":
        from coder.coordinator.signals import record_agent_message

        return await record_agent_message(
            pool,
            user_id=st_config.get("user_id"),
            workflow_id=st_config.get("workflow_id"),
            node_id=st_config.get("agent_node_id"),
            conversation_id=st_config.get("conversation_id"),
            message=str(arguments.get("message") or ""),
        )
    if tool_type == "prompt_builder":
        return await prompt_builder_impl(
            pool=pool,
            user_id=st_config.get("user_id"),
            workflow_id=st_config.get("workflow_id"),
            node_id=st_config.get("agent_node_id"),
            conversation_id=st_config.get("conversation_id"),
            conversation_key=st_config.get("conversation_key"),
            prompt=str(arguments.get("prompt") or ""),
        )
    if tool_type == "describe_workflow":
        return await describe_workflow_impl(
            pool,
            user_id=st_config.get("user_id"),
            workflow_id=st_config.get("workflow_id"),
            node_id=st_config.get("agent_node_id"),
            focus=str(arguments.get("focus") or "") or None,
            in_iteration=bool(st_config.get("in_iteration_fanout")),
        )
    if tool_type == "builder_respond":
        return await builder_respond_impl(
            pool,
            user_id=st_config.get("user_id"),
            workflow_id=st_config.get("workflow_id"),
            conversation_id=st_config.get("conversation_id"),
            answers=arguments.get("answers") if isinstance(arguments.get("answers"), dict) else None,
            message=arguments.get("message"),
        )
    if tool_type == "email_user":
        return await email_user_impl(
            pool,
            user_id=st_config.get("user_id"),
            organization_id=st_config.get("organization_id"),
            workflow_id=st_config.get("workflow_id"),
            node_id=st_config.get("agent_node_id"),
            conversation_id=st_config.get("conversation_id"),
            execution_id=st_config.get("execution_id"),
            subject=str(arguments.get("subject") or ""),
            body=str(arguments.get("body") or ""),
        )
    return {"success": False, "error": f"unknown platform tool type {tool_type!r}"}
