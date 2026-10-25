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

# Each tool call this instance's MCP server answered, for whatever keeps a
# record of them: async (*, user_id, client, tool, arguments, response,
# duration_ms) -> None, run off the response path. ``response`` is the
# JSON-RPC reply's body; ``client`` the name the client registered under.
# Without one, nothing is kept.
MCP_TOOL_CALLED = "mcp.tool_called"

# Curated per-node authoring guidance for the builder, over and above what the
# node catalog says about itself: load(node_type, section) -> str | None.
NODE_GUIDANCE = "builder.node_guidance"

# Where a workflow's published interfaces are: async (pool, workflow_id) ->
# {node_id: url}. Publishing needs a host serving them; without one there are none.
PUBLISHED_APP_URLS = "publish_app.urls"

# Publish a saved, owned interface: async (pool, *, user_id, workflow_id,
# node_id, subdomain, title, action) -> {url, app_id, node_id, subdomain, state}.
INTERFACE_PUBLISH = "interface.publish"

# Take down what was published from interface nodes that left their graph (all
# of a workflow deleted for good: node_ids None): async (pool, workflow_id,
# node_ids) -> None; raises when one couldn't be.
INTERFACES_REMOVED = "interface.removed"

# What a user whose balance ran out should do next, for the credit alerts:
# async (billing_user_id, pool=None) -> (button label, url). Without one the
# alerts point at the dashboard.
CREDIT_CTA = "billing.credit_cta"

# What an account that ran out of money can do besides add funds, for the credit
# alerts and the coordinator's refusal: async (pool, user_id, *, organization_id=None,
# request=None) -> {headline, line, url, reward_usd} | None (None: nothing to offer this
# account). ``request`` is what the refusal turned down. Without one, nothing.
REFERRAL_OFFER = "billing.referral_offer"

# The money behind the usage page, where the deployment bills: an object with
# ``columns`` ({name: (row expression, group aggregate)}: how each charge was
# paid, added to the page's reads), ``async period(pool, user_id)`` -> {window_start,
# window_end, previous_start, billing} and ``async names(pool, user_id, ids)`` ->
# {kind: {id: {name}}} for the ids it owns. Without one the period is the UTC
# calendar month and the page shows what each thing cost, with nothing billed.
USAGE_BILLING = "usage.billing"

# Tell whoever runs this instance that a user hit a plan cap, as a sales signal:
# (user_data, gate, details=None) -> None, fire-and-forget.
PLAN_GATE_ALERT = "billing.plan_gate_alert"

# Tell whoever runs this instance what its users are doing, as an activity feed:
# (user, action, details=None, *, key=None) -> None, fire-and-forget. ``user`` is a
# user id or the session's user_data, ``action`` one of the feed's names ("text",
# "chat", "connect", "automation.create", "automation.edit", "buy.number",
# "search.numbers", ...) and ``details`` its facts; records sharing ``key`` in a
# row are one line. Call it through ``utils.activity.signal_activity``.
ACTIVITY_SIGNAL = "activity.signal"

# The live public URLs a workflow is reachable at (published apps, hosted MCP
# links) for the builder's and the agent's view of it: async (pool, workflow_id,
# *, mint_hosted_for=None, user_id=None) -> {node_id: endpoint}; the builder
# passes the hosting nodes whose link should exist (minted as user_id). Without
# one a workflow has no public endpoints to describe.
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

# A builder run's step as it happens (its status line: "Reading schema for
# Gmail"), for whatever follows the run outside the canvas: async (pool, *,
# user_context, step) -> None, fire-and-forget.
BUILDER_STEP_NOTIFY = "builder.step_notify"

# Message the account owner on their phone, over WhatsApp or iMessage: async (pool, user_id, text, *, link=None,
# channel=None) -> {"success", "channel"} or {"success": False, "error"}. ``channel`` ("whatsapp" | "imessage") names
# the app; None means the one the owner last texted on. Without one, the instance's own lines send it
# (coder/coordinator/texting/owner_message.py), and with no line the coordinator can't message the owner's phone.
OWNER_MESSAGE = "owner.message"

# Phone numbers a workflow can own: coverage() -> [{country, number_types, texting_types, documents_types,
# steps_types}] (where they're in stock, the kinds that text, the kinds bought with documents the provider reviews
# first and the kinds that ask a step that can't be taken here; CoverageNotReady until that's first found out),
# places(country, number_type) -> [{kind, value, region}] (the cities,
# or area codes, with numbers for sale), search(query) -> [offer] (query: phone_number_handler.number_query),
# offer(e164, *, country, number_type) -> offer | None (as it's for sale now), where an offer is
# {phone_number, country, number_type, locality, region, capabilities, monthly_usd, upfront_usd
# (the provider's prices, decimal strings), requirements: {needs: none | address | documents | steps,
# items: [{id, kind, name, description, example, values}]}, texting: registration | unavailable | none};
# buy(offer, *, label, user_id, holder=None, answers=None, credential_name=None, origin=None) ->
# {number_sid, phone_number, provider}, or {order_id, phone_number, status} while the provider reviews what was
# filed (holder: the name and address a country that asks who holds it gets; answers: by requirement id, text or
# a document's id from upload_document; origin: how the order is finished once it completes;
# PhonePurchaseRejected when the provider refuses), release(number_sid), route(number_sid, *, webhook_id) /
# unroute(number_sid) (where its calls go), exists(number_sid) -> bool; documents(user_id) -> [{id,
# requirement_id, requirement_name, filename, uploaded_at}], upload_document(user_id, *, country, number_type,
# requirement_id, filename, content) -> one of those, remove_document(user_id, document_id) -> {id, removed,
# kept_by_carrier} (PhoneDocumentRefused for a file or document it can't take); orders(user_id) -> [order] (in
# review or sent back), order(user_id, order_id) -> order (PhoneOrderNotFound), resubmit(user_id, order_id, *,
# holder, answers) -> order, where an order is {id, phone_number, country, number_type, status (in_review |
# rejected | completed | failed), reason, deadline, monthly_usd, upfront_usd, credential_id, created_at,
# updated_at, requirements (while open)}. Without one, numbers cannot be bought here.
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
# async hang_up(*, call_sid, operation_id) ends such a call from the owner's
# chat (ValueError when it can't).
PHONE_CALLS = "phone.calls"

# What this platform sells and the one-tap links that buy it, for the account
# coordinator: catalog(email=None) -> {plans, funds: {presets_usd, min_usd, max_usd},
# checkout_note} with the prices charged to the account with that email
# (yearly_usd None: sold monthly only; checkout_note: what checkout charges
# instead where it charges another currency, "" where it never does), or, for
# an account on the old plans (billing.gates.bills_on_old_plans), topups:
# [{credits_per_month, monthly_usd, ...}] in place of funds;
# suggested_funds(shortfall_usd) / suggested_topups(shortfall_credits) -> the
# amounts (top-up offers) worth offering; purchases_for(offer) -> mint's
# arguments for each purchase that lifts a billing.gates.Offer; async mint(pool, *, user_id, kind
# ("plan" | "funds" | "topup"), plan=None, amount_usd=None,
# credits_per_month=None, billing_period="monthly", continuation=None,
# send_to_phone=False) -> {job_id, url, label, ...}. The
# link needs no sign-in — it opens payment for that account alone — and the
# payment wakes the coordinator. Without one, a refusal names the plans and
# stops there.
PURCHASES = "billing.purchases"

# A merchant's UPI payment request (India) the account coordinator hands its
# owner, who pays it from their own UPI app with their PIN; no money moves
# through this instance: async request(pool, *, user_id, upi_link=None,
# vpa=None, payee_name=None, amount_inr=None, note=None, continuation=None,
# send_to_phone=False) -> {job_id, url, payee_name, vpa, amount_inr, note,
# expires_at, ...} (ValueError for details it refuses). The request is a
# ``upi_payment`` coordinator job; the owner's answer on its page ("I've paid",
# "it didn't work", their word rather than proof) finishes it and wakes the
# coordinator. Without one, the coordinator has no request_upi_payment tool.
UPI_PAYMENTS = "payments.upi"

# Automatic refills of the account's balance, for the account coordinator:
# async status(pool, user_id) -> dict; async lower(pool, user_id, *,
# threshold_usd=None, amount_usd=None, monthly_cap_usd=None, turn_off=False)
# -> the new status. The coordinator may lower them or turn them off, never
# turn them on or raise them (lower raises ValueError). Without one, the
# coordinator has no auto_topup tool.
AUTO_TOPUP = "billing.auto_topup"

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

# What a product keeps that holds a credential, beyond the workflows whose
# nodes name it (a named connection, an agent): async (pool, credential_id,
# owner_id) -> [{kind, id, name, used_by: [names]}], named before the owner
# deletes it. Without one, only workflows are named.
CREDENTIAL_HOLDERS = "credentials.holders"

# Nodes left their workflow's graph, or the whole workflow left the account
# (trashed or deleted: node_ids None): async (pool, workflow_id, node_ids) ->
# None, for what a product keeps of those nodes by id (a channel's agents).
WORKFLOW_NODES_REMOVED = "workflow.nodes_removed"

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

# Where an agent's conversation keeps its context checkpoint, so its turns
# compact a long history (``coder.openai_agent.compaction``):
# (pool, *, spec, conversation_id) -> CheckpointStore | None. ``spec`` is the
# turn's ``_agentMemory`` (the platform keeps the checkpoint in that memory);
# without a provider, on a turn without memory, or where the provider keeps no
# checkpoint (None), nothing compacts.
CONVERSATION_CHECKPOINTS = "agent.conversation_checkpoints"

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
# payload, graph) -> None (not one of its nodes: the workflow runs as usual) or
# (status_code, body) for the sender. ``graph`` is the workflow's
# ``{nodes, edges}``, for what the node is wired into. Asked once the delivery
# passed the node's own checks (signature, filters, fire budget, transform), so
# it must answer cheaply for nodes it has no say over.
TRIGGER_DELIVERY = "trigger.delivery"

# Whether an account is one no person has claimed yet (an AI agent signed it up for itself): async (user_id) -> bool.
# Until one does, its public surfaces stay closed: deliveries to its webhook URLs (its schedules' own ticks still
# run), its hosted MCP links, and answer links that would connect someone's account or take secret values into it.
# Without one, every account is a person's.
ACCOUNT_UNCLAIMED = "account.unclaimed"

# Refuse a delivery to a trigger node's webhook that stopped (deactivated: its
# trigger was removed) in a product's own words, for a node it delivers its own
# way: async (*, workflow_id, node_id) -> None (not one of its nodes: the
# engine's own 410) or (status_code, body) for the sender.
TRIGGER_STOPPED = "trigger.stopped"

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

# Something happened in an account that the platform running this engine
# publishes as one of its events, which its subscribers may be woken by:
# async (pool, type, data, *, account_user_id, dedupe_key=None) -> None.
# Without one, nothing is published.
ACCOUNT_EVENTS = "account.events"

# Whether a workflow is the one a platform runs one of its agents on: async
# (pool, workflow_id) -> bool. Its runs are the agent's turns, whose outcome
# reaches whoever asked for them, so a failed one is neither a failed run the
# coordinator triages nor a failure email. Without one, no workflow is.
AGENT_WORKFLOW = "agent.workflow"

# The agent that answers an account's owner in the coordinator's place, when
# the account has one: async (pool, user_id, *, ensure=False, timezone=None)
# -> {"id", "conversation"} or None; ``ensure`` makes it first where the account
# is meant to have one, with ``timezone`` the IANA zone of the browser the owner
# is opening the chat in. Without one (or on None), the coordinator answers.
ACCOUNT_AGENT = "account.agent"

# What would have woken the coordinator, handed to the agent that answers the
# account's owner in its place (``ACCOUNT_AGENT``): async (pool, user_id, note,
# *, from_outside=False) -> the wake-up's id, or None when no agent answers the
# account. The agent is made first where the account is meant to have one, and
# its turn reads ``note`` in its owner's conversation (``from_outside``: the
# note quotes what someone outside the account wrote). Without one, the
# coordinator is woken.
ACCOUNT_AGENT_HANDOVER = "account.agent_handover"

# The email of the agent that answers an account's owner in the coordinator's
# place (``ACCOUNT_AGENT``): its address stands in for the coordinator's. An
# object with async ``reach(pool, user_id, *, ensure=False)`` -> {"address",
# "paused", "anyone"} (``anyone``: mail from anyone wakes it, not only the
# owner's; ``ensure`` makes the agent and an address first), ``rename(pool,
# user_id, name)`` -> the new address and ``take_mail(pool, user_id, on)`` ->
# {"address", "paused"}; each answers None for an account no agent answers,
# whose coordinator keeps its own address. Without one, every account's does.
ACCOUNT_AGENT_EMAIL = "account.agent_email"

# A platform's own rule for a text to the assistant's number: async (transport, message) -> None, with the
# coder/coordinator/texting/channel.py PhoneTransport and PhoneText. Without one, a text reaches the account its number
# is bound to, and the coordinator answers.
PHONE_TEXT = "coordinator.phone_text"

# What a platform does with a WhatsApp delivery's statuses (billing the messages it's charged for, falling back from a
# send WhatsApp failed after taking it): async (pool, payload, *, phone_number_id) -> None, awaited before the delivery
# is acknowledged so a write that didn't land is delivered again. Without one, statuses are ignored.
WHATSAPP_STATUSES = "whatsapp.statuses"

# Tools a platform gives the account coordinator on top of its own: async
# (pool, *, user_id, turn_id, untrusted, voice, cards, discovered,
# continuation) -> the turn's tools, or None when the account has none this
# turn. Judged once, at the turn's start: ``untrusted`` says the turn was woken
# by text from outside the owner (a failure signal, a job's result, an
# operation's report), ``voice`` that it is spoken, ``cards`` that the web chat
# draws its tools' results as cards below the reply, ``discovered`` is the turn's
# utils.discovered_tools.DiscoveredTools, where they install what they load
# mid-turn, and ``continuation`` is the turn's, which the coordinator jobs its
# tools open carry so their outcome wakes it. A turn's tools have
# ``supersedes`` (the coordinator's own tools they replace), ``instructions``
# (for its prompt), ``tool_params()``, async
# ``call(name, arguments, *, call_id) -> result dict`` (``call_id``: the
# model's id for the call, which keys its writes) and
# ``shown_arguments(arguments, result)`` (what the audit row keeps). Without
# one the coordinator has exactly its own tools.
COORDINATOR_PLATFORM_TOOLS = "coordinator.platform_tools"

# Who may act as another account, for a REST request naming one in
# utils.auth.VIEW_AS_HEADER: async (request, claims, identifier) -> the
# account's user id; raises PermissionError for someone who may not, and
# LookupError for no such account. Without one, the header is refused.
VIEW_AS = "auth.view_as"

# Whether an account may hold a made-up value in a field only NoClick's own
# linking flow sets (nodes.core.credential_connect, ``linked_fields``): async
# (pool, *, user_id, value) -> bool. A deployment's own test accounts, so a
# benchmark can stand in for a QR scan no phone makes; without one, never.
LINKED_TEST_VALUE = "credentials.linked_test_value"

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
