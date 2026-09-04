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

from utils.edition import is_local_edition

logger = logging.getLogger(__name__)

SUBMIT_FEEDBACK_TOOL = "submit_feedback"
PROMPT_BUILDER_TOOL = "prompt_builder"
BUILDER_RESPOND_TOOL = "builder_respond"
DESCRIBE_WORKFLOW_TOOL = "describe_workflow"
EMAIL_USER_TOOL = "email_user"
# Excluded from per-harness capability gates (e.g. codex's API-key model gate):
# platform tools are ambient, not user-wired capability the run depends on.
PLATFORM_TOOL_TYPES = {
    "submit_feedback", "prompt_builder", "builder_respond", "describe_workflow",
    "email_user",
}

_FEEDBACK_MAX_LEN = 4000
_PROMPT_MAX_LEN = 8000
_FEEDBACK_DEDUPE_HOURS = 24

_SUBMIT_FEEDBACK_PARAM = {
    "type": "function",
    "function": {
        "name": SUBMIT_FEEDBACK_TOOL,
        "description": (
            "Report a confirmed NoClick PLATFORM bug to the engineering team, "
            "after a platform-provided operation or tool actually failed or "
            "returned a provably wrong result. Include what you expected, what "
            "you observed, and exact errors or paths, then keep working around "
            "the failure if possible. Do NOT use this for progress narration "
            "(starting, searching, waiting, or what you plan to do), missing "
            "user input or source data, missing credentials/configuration, an "
            "unavailable user, lack of a capability you were never given, "
            "expected validation errors, or a task you have not attempted. If "
            "you cannot distinguish a platform defect from one of those cases, "
            "do not report it. Submit one report per root cause, never per "
            "retry, item, city, or scheduled run. Reuse the exact same "
            "issue_key whenever the same root cause recurs."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "feedback": {
                    "type": "string",
                    "description": "The bug report: what you did, what happened, what you expected.",
                },
                "issue_key": {
                    "type": "string",
                    "description": (
                        "Stable snake_case root-cause key, reused across retries "
                        "and runs, e.g. firecrawl_http_500 or workspace_file_missing."
                    ),
                    "pattern": "^[a-z0-9][a-z0-9_]{2,79}$",
                },
            },
            "required": ["feedback", "issue_key"],
        },
    },
}

_PROMPT_BUILDER_PARAM = {
    "type": "function",
    "function": {
        "name": PROMPT_BUILDER_TOOL,
        "description": (
            "Add new integrations, tools, or capabilities to yourself, or "
            "change THIS workflow (add/remove/rewire/configure nodes), by "
            "submitting a natural-language prompt to the NoClick AI workflow "
            "builder. This is the ONLY way to gain new INTEGRATION tools "
            "(e.g. Telegram, Slack, Gmail): those come from integration "
            "nodes wired to you in the workflow, with credentials managed by "
            "NoClick. (Your platform tools — like this one, or email_user "
            "when present in your tool list — are built in and need no "
            "wiring.) Do NOT "
            "install packages, SDKs, or MCP servers in your sandbox to add an "
            "integration — sandbox-installed bridges have no credentials and "
            "are not real NoClick tools. ALWAYS call describe_workflow first "
            "and write prompts that FIT the existing structure — blind edits "
            "can break the surrounding workflow. You may also ask the builder "
            "a question (it answers without editing), but every builder run "
            "consumes the user's build credits: get facts from the free "
            "describe_workflow and reserve builder questions for judgment "
            "calls. In interactive chats the user is asked to approve before "
            "the builder runs; in background runs the builder runs headlessly. "
            "Describe the desired end state, not click-by-click steps."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The edit to make, e.g. \"add a Slack node that posts the agent's summary to #alerts\".",
                },
            },
            "required": ["prompt"],
        },
    },
}


_DESCRIBE_WORKFLOW_PARAM = {
    "type": "function",
    "function": {
        "name": DESCRIBE_WORKFLOW_TOOL,
        "description": (
            "See the workflow you are embedded in: every node, its operation "
            "and field values, the wiring between them, which triggers feed "
            "you, and which nodes provide your tools — the SAME snapshot the "
            "workflow builder reads. FREE and instant (a database read, no "
            "credits, no builder run). ALWAYS call this before proposing "
            "workflow edits with prompt_builder, and whenever you are unsure "
            "what you are connected to or capable of — edit prompts written "
            "blind can break the surrounding workflow. For factual questions "
            "about the workflow, this tool IS the answer; only ask the "
            "builder (via prompt_builder) when you need its judgment, since "
            "builder runs consume the user's build credits."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "focus": {
                    "type": "string",
                    "description": "Optional node id to spotlight (defaults to yourself).",
                },
            },
            "required": [],
        },
    },
}

_BUILDER_RESPOND_PARAM = {
    "type": "function",
    "function": {
        "name": BUILDER_RESPOND_TOOL,
        "description": (
            "Answer the workflow builder's pending questions so a build you "
            "started with prompt_builder keeps moving WITHOUT waiting for the "
            "user. When a '--- Platform note ---' says the builder PAUSED with "
            "questions, answer every design/configuration question you can "
            "decide yourself (channel names, schedules, options — reference "
            "inputs by their [id]); the builder resumes immediately and you "
            "will be woken with the next update. CREDENTIAL inputs are the "
            "exception: only a human can connect an account, via the shared "
            "no-login link in the note — send that link through your channel "
            "and do NOT call this tool when only credential inputs remain. "
            "Answers you make up badly waste the user's build credits, so "
            "only answer what you genuinely know or can sensibly decide."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "answers": {
                    "type": "object",
                    "description": "Input id → answer value, e.g. {\"ask_0\": \"#alerts\"}. Ids come from the platform note.",
                    "additionalProperties": {"type": "string"},
                },
                "message": {
                    "type": "string",
                    "description": "Optional free-form reply for anything the structured answers don't cover (the builder's brain reads it).",
                },
            },
            "required": [],
        },
    },
}


_EMAIL_USER_PARAM = {
    "type": "function",
    "function": {
        "name": EMAIL_USER_TOOL,
        "description": (
            "Email the workflow owner directly. This tool IS your built-in "
            "email capability — it needs NO email node or wiring in the "
            "workflow, and it works even though it never appears in the "
            "graph. Primarily your channel to the user when they are AWAY "
            "from the NoClick app: deliver things that need a human and "
            "can't wait for them to come back — builder or credential links "
            "that are blocking you, questions only they can answer, reports "
            "of failures or important updates. (If the user explicitly asks "
            "you to email them, just do it, active or not.) The owner "
            "can REPLY to the email and their reply arrives as your next "
            "message, so write like a real conversation: each conversation is "
            "ONE email thread — follow-up sends automatically continue it as "
            "replies (your subject is only used on the first email). Each "
            "turn's platform note tells you whether the owner is currently "
            "active; when they are ACTIVE (or you're already talking with "
            "them in a chat or channel), speak there instead of emailing. "
            "Tone: informal and CONCISE — write like a sharp colleague "
            "emailing an executive: their time is scarce, lead with the "
            "point, keep it short, no corporate boilerplate, no markdown "
            "headers. Open the FIRST email of a thread with a one-line "
            "introduction in your own words — which workflow you're the "
            "agent in and what you do there (e.g. \"I'm the agent in your "
            "Support Desk workflow — I watch the inbox and triage tickets\"); "
            "never re-introduce yourself in later replies on the same thread "
            "(the tool result says whether a send opened a thread or replied "
            "into one). NoClick adds the provenance footer and unsubscribe "
            "link automatically — never add your own footers or sign-offs. "
            "Sends are capped per day and cost the owner a small credit fee "
            "— at most ONE email can be sent per workflow execution. Batch "
            "related updates into that email. When running inside an iteration, "
            "email_user is withheld because per-item sends would spam and charge "
            "the owner; use a downstream notification node for intentional "
            "per-item delivery."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "subject": {
                    "type": "string",
                    "description": "Short, specific subject line, e.g. \"Need you to connect Slack\".",
                },
                "body": {
                    "type": "string",
                    "description": "The message (plain text; links pasted inline). Concise and informal.",
                },
            },
            "required": ["subject", "body"],
        },
    },
}


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


def build_platform_tools(
    enable_prompt_builder: bool, enable_email_updates: bool = False,
    in_iteration: bool = False,
) -> list:
    """``(tool_param, tool_config)`` pairs to append to the agent's collected
    tool set. The config carries the tool type and its model-facing schema;
    execution context comes from the active agent turn."""
    pairs = [_platform_pair(_SUBMIT_FEEDBACK_PARAM, "submit_feedback")]
    if enable_prompt_builder:
        pairs.append(_platform_pair(_PROMPT_BUILDER_PARAM, "prompt_builder"))
        pairs.append(_platform_pair(_BUILDER_RESPOND_PARAM, "builder_respond"))
        pairs.append(_platform_pair(_DESCRIBE_WORKFLOW_PARAM, "describe_workflow"))
    # email_user requires a configured inbound/reply mail channel. Community
    # installs advertise it only after the operator configures that channel.
    if enable_email_updates and not in_iteration and agent_email_available():
        pairs.append(_platform_pair(_EMAIL_USER_PARAM, "email_user"))
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
    return (
        f"{prompt}\n\n"
        f"(Requested by the existing agent node with id '{node_id}'. Apply the "
        f"change to that agent — e.g. wire new tool-provider nodes into it — "
        f"and leave other agent nodes unchanged unless the request says "
        f"otherwise.)"
    )


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
    prompt_builder_part = (
        "Your NoClick integrations come from nodes wired to you in this "
        "workflow — never from software installed in this sandbox. To gain a "
        "new integration or capability (Telegram, Slack, Gmail, …), call the "
        "prompt_builder tool with the change you want: the NoClick builder "
        "wires real nodes with managed credentials. Do not install packages "
        "or configure MCP servers in the sandbox for this — such bridges have "
        "no credentials and are not NoClick tools. "
    ) if enable_prompt_builder else ""
    email_part = (
        "When the workflow owner is AWAY from the app (each turn's platform "
        "note says), the email_user tool is your channel to them: send "
        "blocking links, questions, and failure reports there instead of "
        "waiting silently — they can reply to the email to answer you. "
    ) if enable_email_updates and not in_iteration and agent_email_available() else ""
    return (
        f"{prompt_builder_part}"
        f"{email_part}"
        "Use submit_feedback only after a platform-provided operation actually "
        "fails or returns a provably wrong result. Never use it for progress "
        "updates, missing user input/data/credentials, an unavailable user, or "
        "a capability you were never given. Report one root cause once, reuse "
        "the same issue_key across retries and scheduled runs, then continue "
        "the task or work around the failure."
    )


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
            parts = []
            for e in providers:
                src = nodes_by_id.get(e.get("source"), {})
                ops = _cfg(src).get("agent_tool_operations")
                parts.append(f"{e.get('source')} ({src.get('type', '?')}"
                             + (f"; allowlisted ops: {', '.join(ops)}" if ops else "") + ")")
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
        if (
            cfg.get("enable_email_updates") != "false"
            and not in_iteration
            and agent_email_available()
        ):
            ambient.append("email_user (emails the workflow owner directly — needs NO email node)")
        notes.append(
            "Your ambient NoClick platform tools are NOT graph nodes and never "
            "appear above: " + ", ".join(ambient) + "."
        )

    return {
        "success": True,
        "workflow_name": row["name"],
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


async def execute_platform_tool_from_ctx(
    st_config: Dict[str, Any], arguments: Dict[str, Any], pool,
) -> Dict[str, Any]:
    """Pool-local execution for MCP-served tool calls (CLI harnesses):
    everything needed rides the token's tool_ctx (merged into st_config by the
    pool), so this runs identically in any backend process — no executor
    callback required."""
    tool_type = st_config.get("tool_type")
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
