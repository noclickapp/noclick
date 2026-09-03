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

# What a user whose balance ran out should do next, for the credit alerts:
# async (billing_user_id, pool=None) -> (button label, url). Without one the
# alerts point at the dashboard.
CREDIT_CTA = "billing.credit_cta"

# Tell whoever runs this instance that a user hit a plan cap, as a sales signal:
# (user_data, gate, details=None) -> None, fire-and-forget.
PLAN_GATE_ALERT = "billing.plan_gate_alert"

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
