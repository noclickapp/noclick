"""Optional services an edition may provide and the engine works without.

These capabilities have no default behavior to replace. Callers ask for a
registered implementation and treat ``None`` as an ordinary answer. Names are
constants so providers and consumers share one reviewed contract.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

# Durable workspace backing for agent runs: (default mount, volume namer).
WORKSPACE_VOLUME = "workspace.volume"

# Curated per-node authoring guidance for the builder, over and above what the
# node catalog says about itself: load(node_type, section) -> str | None.
NODE_GUIDANCE = "builder.node_guidance"

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
