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
# buy(e164, *, label) -> {number_sid, phone_number}, release(number_sid),
# route(number_sid, *, webhook_id) / unroute(number_sid) (where its calls go),
# exists(number_sid) -> bool. Without one, numbers cannot be bought here.
PHONE_NUMBERS = "phone.numbers"

# Live calls with the wired agent as the voice, on a number the platform
# bought OR one the user brought from their own Twilio account:
# receiver_url(webhook_id) -> the URL a number's voice webhook points at;
# async place(*, user_id, workflow_id, node_id, credential_id, from_number,
# number_sid, to_number, goal, carrier=None, conversation_id=None) -> dict,
# where carrier is {"account_sid", "auth_token"} for a brought number (None =
# platform account) and conversation_id names the agent turn placing the call,
# which the finished call comes back to.
PHONE_CALLS = "phone.calls"

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
