"""Socket handlers contributed by whatever is running this engine, and the
per-dispatch hooks that go with them.

The receiver builds its own handlers and dispatches to them by routing key. A
platform deploying the engine has more — internal tooling, sign-in flows for
providers it has agreements with, a relay-registration handler for its
developers' machines — and the receiver must not name them: naming them
publishes the shape of the hosted side and makes the engine import modules
that are not part of it.

So a platform registers before the receiver is built, and the receiver merges
the result into its tables:

    from wss.receiver.handler_registry import register_handler
    register_handler("debug_handler", lambda sio: DebugHandler(sio))

Keys are whatever the event table names for that handler: the engine's own are
``Handler`` members, a platform's are the plain strings its routes carry.
Factories receive the socket server and return a handler, or None to decline
(the receiver only builds handlers on the API role, and a factory may care).
Nothing registers in a plain install and the tables are unchanged.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

HandlerFactory = Callable[[Any], Any]

_factories: List[Tuple[Any, HandlerFactory]] = []
_lifecycle: Dict[str, List[Any]] = {}
_context_hooks: List[Callable[[Any, str], Any]] = []
_span_hooks: List[Callable[[Any, int], None]] = []


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


def register_lifecycle_handler(env: str, key: Any) -> None:
    """A registered handler that gets ``setup_user``/``cleanup_user`` on
    connect and disconnect without owning any event."""
    _lifecycle.setdefault(env, []).append(key)


def lifecycle_handler_keys(env: str) -> List[Any]:
    return list(_lifecycle.get(env, ()))


# ── Per-dispatch context ─────────────────────────────────────────────────────
# A platform may want to stamp something for the duration of one socket event —
# the acting user on every SQL statement it logs, the browser session its
# analytics events should link to. It registers a hook that receives the
# connection's session and sid and returns a callable to undo it, or None if
# there is nothing to undo.


def register_request_context(hook: Callable[[Any, str], Any]) -> None:
    """hook(session, sid) -> undo callable | None. Several may register."""
    _context_hooks.append(hook)


def enter_request_context(session: Any, sid: str) -> Optional[Callable[[], None]]:
    """Run every registered hook; returns one undo for all of them, or None."""
    undos = [undo for hook in _context_hooks if (undo := hook(session, sid)) is not None]
    if not undos:
        return None

    def undo_all() -> None:
        for undo in reversed(undos):
            undo()

    return undo_all


# ── Per-dispatch span ────────────────────────────────────────────────────────
# Something a platform knows how to attach to the socket span once the handler
# has run — a profiler deep-link for the container and time window, say.


def register_dispatch_span_hook(hook: Callable[[Any, int], None]) -> None:
    """hook(span, span_start_ms), called when a dispatch finishes, success or not."""
    _span_hooks.append(hook)


def finish_dispatch_span(span: Any, span_start_ms: int) -> None:
    for hook in _span_hooks:
        try:
            hook(span, span_start_ms)
        except Exception:
            pass


def clear() -> None:
    """Reset registration state (tests)."""
    _factories.clear()
    _lifecycle.clear()
    _context_hooks.clear()
    _span_hooks.clear()
