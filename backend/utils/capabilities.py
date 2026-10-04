"""Things the environment running this engine may provide, and the engine
works without.

Distinct from the registries elsewhere, which replace something the engine
already does — a Python runtime, a billing gate, a socket handler. These have no
default behaviour to replace: there is either a fleet of warm sandboxes to count
or there is not, either a shared store to mirror session logs onto or there is
not. The engine asks, gets None, and does the simpler thing.

    # provider, at start-up
    provide(WARM_SANDBOX_LIST, list_active_sandboxes)

    # engine, at the point of use
    list_sandboxes = capability(WARM_SANDBOX_LIST)
    if list_sandboxes is None:
        return {}

Names are constants rather than bare strings so that both halves are one
grep apart, and so a typo is an AttributeError rather than a silent None.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Count the warm agent sandboxes a user currently has running.
WARM_SANDBOX_LIST = "warm_sandbox.list_active"

# The durable workspace an agent run writes into: (default mount, volume namer).
WORKSPACE_VOLUME = "workspace.volume"

# Mirror builder session logs onto storage other processes can read.
SESSION_LOG_MIRROR = "session_log.mirror"

# A session-debug capture the AI builder reports into.
DEBUG_CAPTURE = "debug.capture"

# Per-request tools an MCP caller carries in its own token, rather than tools
# this server owns. An agent sandbox reaches back in this way.
MCP_REQUEST_TOOLS = "mcp.request_tools"

# Curated per-node authoring guidance for the builder, over and above what the
# node catalog says about itself: load(node_type, section) -> str | None.
NODE_GUIDANCE = "builder.node_guidance"

# The domain published interface apps are served under. Publishing one needs
# that front door; without it there are none.
PUBLISHED_APP_DOMAIN = "publish_app.domain"

# Publish a saved, owned interface: async (pool, *, user_id, workflow_id,
# node_id, subdomain, title) -> {url, app_id, node_id, subdomain}.
INTERFACE_PUBLISH = "interface.publish"

# What a user whose balance ran out should do next, for the credit alerts:
# async (billing_user_id, pool=None) -> (button label, url). Without one the
# alerts point at the dashboard.
CREDIT_CTA = "billing.credit_cta"

# Tell whoever runs this instance that a user hit a plan cap, as a sales signal:
# (user_data, gate, details=None) -> None, fire-and-forget.
PLAN_GATE_ALERT = "billing.plan_gate_alert"

# Tell whoever runs this instance what its users are doing, as an activity feed:
# (user_data, action, details=None) -> None, fire-and-forget.
ACTIVITY_SIGNAL = "activity.signal"

# The live public URLs a workflow is reachable at (published apps, hosted MCP
# links) for the builder's and the agent's view of it: async (pool, workflow_id)
# -> list. Without one a workflow has no public endpoints to describe.
PUBLIC_ENDPOINTS = "workflow.public_endpoints"

# Tell whoever runs this instance that one node's execution grew the process
# by a lot: async (workflow_id, node_id, node_label, node_type, rss_mb,
# rss_delta_mb, threads) -> None. The engine logs the allocators either way.
MEMORY_SPIKE_ALERT = "diagnostics.memory_spike_alert"

# Tell the account, on channels the engine does not have (a WhatsApp number,
# a per-account thread), that a builder run parked on a question:
# async (pool, *, user_id, workflow_id, workflow_name, builder_conversation_id,
#        ask_id, inputs, user_context) -> None, fire-and-forget.
BUILDER_ASK_NOTIFY = "builder.ask_notify"

# ...or finished: async (pool, *, user_id, workflow_id, workflow_name,
# builder_conversation_id, summary, success, error, user_context) -> None.
BUILDER_RESULT_NOTIFY = "builder.result_notify"

# Message the account owner on a channel of their own the engine does not
# have (a WhatsApp number): async (pool, user_id, text, *, link=None) ->
# {"success", "channel"} or {"success": False, "error"}. Without one the
# coordinator has no message_owner tool.
OWNER_MESSAGE = "owner.message"

# Phone numbers a workflow can own: search(country, area_code, limit, *, contains=None) -> list,
# buy(e164, *, label) -> {number_sid, phone_number, provider}, release(number_sid),
# route(number_sid, *, webhook_id) / unroute(number_sid) (where its calls go),
# exists(number_sid) -> bool. Without one, numbers cannot be bought here.
PHONE_NUMBERS = "phone.numbers"

# Live calls with the wired agent as the voice, on a number the platform
# bought OR one the user brought from their own Twilio account:
# receiver_url(webhook_id) -> the URL a number's voice webhook points at;
# async place(*, user_id, workflow_id, node_id, credential_id, from_number,
# number_sid, to_number, goal, carrier=None, conversation_id=None, operation_context=None) -> dict,
# where carrier is {"account_sid", "auth_token"} for a brought number (None =
# platform account) and conversation_id names the agent turn placing the call,
# which the finished call comes back to. With no workflow, the trusted runtime's
# operation_context registers a coordinator completion; remote speech stays in
# a goal-scoped call assistant, never the owner's account conversation.
PHONE_CALLS = "phone.calls"

# What this platform sells and the one-tap links that buy it, for the account
# coordinator: catalog() -> {plans, topups} with the prices charged;
# suggested_topups(shortfall) -> the sizes worth offering; async mint(pool, *,
# user_id, kind, plan=None, credits_per_month=None, billing_period="monthly",
# continuation=None, send_to_phone=False) -> {job_id, url, label, ...}. The
# link needs no sign-in — it opens payment for that account alone — and the
# payment wakes the coordinator. Without one, a refusal names the plans and
# stops there.
PURCHASES = "billing.purchases"

# Vet an agent's tool call before it runs: async (*, user_id, workflow_id,
# node_id, conversation_id, tool_name, tool_info, arguments) -> None to run it,
# or the result dict ({"success": False, "error": ...}) to return instead.
# Called for every non-rehearsed call (via tool_execution.tool_call_refusal,
# including execute_bash as tool_info {"tool_type": "bash"}), so it must answer
# cheaply for workflows it has no say over.
TOOL_CALL_GUARD = "agent.tool_call_guard"

# The nodes of a workflow whose credential its product binds on every run as
# a config override, so the saved graph holds none: async (pool, workflow_id)
# -> iterable of node ids. Activation readiness (every trigger registration
# path) doesn't ask them for a saved credential. Without one, every node's
# credential must be saved in the graph.
BOUND_CREDENTIALS = "workflow.bound_credentials"

# Receive mail to a reserved inbound address whose kind the engine has no
# receiver for (neither a trigger's nor the coordinator's): async (pool,
# reservation, message, *, defer) -> str, what happened, for the log.
# ``reservation`` is the email_reservations row; ``message`` is the parsed
# mail (from, to, subject, text, html, headers, spf/dkim verdicts, stored
# attachments, reply_token + timestamp for utils.email_reply); ``defer(fn,
# *args)`` runs work after the relay is acked. Without one, such addresses
# are unknown.
EMAIL_ADDRESS_RECEIVER = "email.address_receiver"

# The OAuth app a credential request's minting surface brings for a provider,
# in place of the instance's own: async (pool, *, requester_id, metadata,
# provider) -> {client_id, client_secret} or None (the instance's app).
# ``metadata`` is the request's; raises OAuthAppUnavailable when the app it
# named can't be used any more (the request then can't connect that provider).
OAUTH_APPS = "credentials.oauth_apps"

# Let an agent ask its user to connect an account it may then act in (the
# ``request_connection`` tool): async (pool, *, spec, arguments) -> result dict.
# ``spec`` is what the platform put on the turn (the agent's
# ``_connectionRequests`` runtime config); without a provider the tool is
# never offered.
CONNECTION_REQUESTS = "agent.connection_requests"

# Let an agent take a turn in its conversation later (the ``wake_me`` tool):
# async (pool, *, spec, arguments) -> result dict. ``spec`` is the agent's
# ``_wakeMe`` runtime config; without a provider the tool is never offered.
WAKEUPS = "agent.wakeups"

# Let a spawned agent reach the agent that gave it its task (the
# ``tell_parent`` tool): async (pool, *, spec, arguments) -> result dict.
# ``spec`` is the agent's ``_tellParent`` runtime config; without a provider
# the tool is never offered.
PARENT_UPDATES = "agent.parent_updates"

# Let an agent manage other agents with tools a platform defines (start them on
# work, message, ask and check on them, stop what it started): an object with
# ``tools(spec) -> [tool params]`` (function params, unique names) and async
# ``call(pool, *, spec, arguments) -> result dict``. ``spec`` is the agent's
# ``_agentTools`` runtime config; each offered tool's own spec adds ``tool``,
# its function name. Without a provider no tool is offered.
AGENT_COORDINATION = "agent.coordination"

# Tools a platform defines whole for an agent's turn (the runtime key
# nodes.agent.platform_tools.PLATFORM_TOOLS_KEY): async (pool, *, spec,
# arguments) -> result, called with the tool's own spec. ``spec["policy"]``
# names the tool for policy where the wire name doesn't.
PLATFORM_TOOLS = "agent.platform_tools"

# Let an agent keep named notes across its conversations (the memory__search,
# memory__read, memory__save and memory__delete tools of nodes.agent.agent_memory):
# async (pool, *, spec, arguments) -> result dict. ``spec`` is the agent's
# ``_agentMemory`` runtime config plus ``tool``, the function's name; without a
# provider the tools are never offered.
AGENT_MEMORY = "agent.memory"

# Text steered into an in-process agent's running turn before its next model
# call (a question asked mid-turn, a progress check): async (conversation_id)
# -> [text], each taken once. Asked before every model call, so it must
# answer cheaply for conversations it has no say over.
TURN_STEERING = "agent.turn_steering"

# Environment variables an edition keeps itself for an agent's sandbox (named
# secrets): async (spec) -> {NAME: value}. ``spec`` is the agent's
# ``_sandboxEnv`` runtime config (nodes.agent.user_env.SANDBOX_ENV_KEY); the
# values join the agent_env credential's and are checked the same way.
SANDBOX_ENV = "agent.sandbox_env"

# Take a fired trigger's delivery in place of a run of its workflow, for a
# trigger node a product delivers its own way: async (*, workflow_id, node,
# payload) -> None (not one of its nodes: the workflow runs as usual) or
# (status_code, body) for the sender. Asked once the delivery passed the
# node's own checks (signature, filters, fire budget, transform), so it must
# answer cheaply for nodes it has no say over.
TRIGGER_DELIVERY = "trigger.delivery"

# Watch an agent's turns as they happen: (conversation_id, event) -> None,
# synchronous and fire-and-forget, for each piece of reply text
# ({type: text, text}), each tool call about to run or held ({type: tool_call,
# tool, arguments, held?}) and each tool result ({type: tool_result, tool,
# result, is_error}). Called on every turn's hot path, so it must answer
# cheaply for conversations it has no say over.
TURN_EVENTS = "agent.turn_events"

# Run a shared agent link's visitor turns a product's own way (its billing,
# budgets and credentials) for an agent it owns: async (pool, link) -> None
# (not its agent: the engine runs the turn) or an object with
# ``conversation_prefix`` (a visitor's thread is ``{prefix}:{visitor id}:{chat
# key}``), async ``send(conversation_id, text) -> None`` (accepted) or the
# refusal's reason (``busy``, ``agent_unavailable``), and ``brand`` (the page's
# name, logo_url, color and support_url, or None). ``link`` is
# ``SharedAgentLinkRepo.load_for_visit``'s row.
SHARED_AGENT_TURNS = "agent.shared_turns"

_providers: Dict[str, Any] = {}


def provide(name: str, implementation: Any) -> None:
    """Register a capability. Call before serving traffic."""
    _providers[name] = implementation
    logger.info(f"[capabilities] {name} provided")


def capability(name: str) -> Optional[Any]:
    """The registered implementation, or None. None is an ordinary answer."""
    return _providers.get(name)


def clear() -> None:
    """Reset registration state (tests)."""
    _providers.clear()
