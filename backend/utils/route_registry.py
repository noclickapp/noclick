"""HTTP routes contributed by whatever is running this engine.

The engine builds one FastAPI app and mounts its own routes on it. A platform
deploying it has more, and the engine must not know their names: naming them
here publishes the shape of the hosted side, and makes the engine import
modules that are not part of it.

So a platform registers a provider before the app is built, and the engine calls
it while building. A provider receives the app and the socket server, because
some routes need to reach the latter.

    # in the platform's start-up, before the engine is imported
    from utils.route_registry import register_routes
    register_routes(lambda app, sio: app.include_router(my_router))

Nothing registers in a plain install, and `apply_registered_routes` does nothing.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, List

logger = logging.getLogger(__name__)

RouteProvider = Callable[[Any, Any], None]

_providers: List[RouteProvider] = []
_inline_webhook_routes = True


def set_inline_webhook_routes(enabled: bool) -> None:
    """Whether the interactive app serves webhook and inbound-email routes
    itself. A deployment that runs them from a separate process turns this
    off before the app is built; a plain install serves everything from one."""
    global _inline_webhook_routes
    _inline_webhook_routes = enabled


def inline_webhook_routes() -> bool:
    return _inline_webhook_routes


def register_routes(provider: RouteProvider) -> None:
    """Register a callable that mounts routes. Call before the app is built."""
    _providers.append(provider)


def apply_registered_routes(app: Any, sio: Any) -> None:
    """Mount every registered provider's routes onto `app`.

    A provider that raises is fatal: it means the platform expected to serve
    something and does not. Failing at start-up is the honest answer — the
    alternative is a deployment that looks healthy and 404s a route its own
    sandboxes depend on.
    """
    for provider in _providers:
        provider(app, sio)
    if _providers:
        logger.info(f"[Routes] Mounted {len(_providers)} registered route provider(s)")


def clear() -> None:
    """Reset registration state (tests)."""
    global _inline_webhook_routes
    _providers.clear()
    _inline_webhook_routes = True
