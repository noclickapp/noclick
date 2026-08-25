"""Socket handlers contributed by whatever is running this engine.

The receiver builds its own handlers and dispatches to them by routing key. A
platform deploying the engine has more — internal tooling, sign-in flows for
providers it has agreements with — and the receiver must not name them: naming
them publishes the shape of the hosted side and makes the engine import modules
that are not part of it.

So a platform registers a factory before the receiver is built, and the receiver
merges the result into its dispatch table.

    from wss.receiver.handler_registry import register_handler
    register_handler(Handler.DEBUG, lambda sio: DebugHandler(sio))

Factories receive the socket server and return a handler, or None to decline
(the receiver only builds handlers on the API role, and a factory may care).
Nothing registers in a plain install and the table is unchanged.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Tuple

logger = logging.getLogger(__name__)

HandlerFactory = Callable[[Any], Any]

_factories: List[Tuple[Any, HandlerFactory]] = []


def register_handler(key: Any, factory: HandlerFactory) -> None:
    """Register a handler under a routing key. Call before the receiver builds."""
    _factories.append((key, factory))


def registered_handlers(sio: Any) -> Dict[Any, Any]:
    """Build every registered handler. A factory returning None is skipped, so a
    platform can decline a handler for this process's role without the receiver
    knowing why."""
    built: Dict[Any, Any] = {}
    for key, factory in _factories:
        handler = factory(sio)
        if handler is not None:
            built[key] = handler
    if built:
        logger.info(f"[RECEIVER] {len(built)} registered handler(s) added")
    return built


def clear() -> None:
    """Reset registration state (tests)."""
    global _context_hook
    _factories.clear()
    _context_hook = None


# ── Per-dispatch context ─────────────────────────────────────────────────────
# A platform may want to stamp something for the duration of one socket event —
# the acting user on every SQL statement it logs, say. It registers a hook that
# receives what the receiver knows about the session and returns a callable to
# undo it, or None if there is nothing to undo.

_context_hook: Any = None


def register_request_context(hook: Callable[[Any, str], Any]) -> None:
    """hook(user_email, sid) -> undo callable | None."""
    global _context_hook
    _context_hook = hook


def enter_request_context(user_email: Any, sid: str) -> Any:
    """Returns the undo callable, or None when nothing is registered."""
    if _context_hook is None:
        return None
    return _context_hook(user_email, sid)
