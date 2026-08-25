"""Optional HTTP routes contributed by an installation.

The engine builds one FastAPI app and mounts its own routes on it. Extensions
can register additional routes before the app is built without coupling their
modules to the core server. A provider receives the app and socket server.

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


def register_routes(provider: RouteProvider) -> None:
    """Register a callable that mounts routes. Call before the app is built."""
    _providers.append(provider)


def apply_registered_routes(app: Any, sio: Any) -> None:
    """Mount every registered provider's routes onto `app`.

    A provider that raises is fatal: an enabled extension must either mount its
    routes successfully or fail at start-up.
    """
    for provider in _providers:
        provider(app, sio)
    if _providers:
        logger.info(f"[Routes] Mounted {len(_providers)} registered route provider(s)")


def clear() -> None:
    """Reset registration state (tests)."""
    _providers.clear()
