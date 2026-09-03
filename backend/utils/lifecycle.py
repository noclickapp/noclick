"""Start-up, shutdown and socket-session hooks contributed by whatever is
running this engine.

The engine's lifespan starts its own services — telemetry, the database pool,
the socket handlers, the MCP server, the self-hosted cron and relay — and
knows nothing else. A platform deploying it has more to start (profilers, log
shippers, warm caches, dev tunnels) and more to stop, and the engine must not
name them: doing so publishes the shape of the hosted side and makes the
engine import modules that are not part of it.

So a platform registers hooks before the app is built, and the lifespan runs
them at fixed points:

    startup   ``boot``   right after telemetry, before the database pool
              ``ready``  after every engine service is up, before serving
    shutdown  ``drain``  after in-flight work was asked to stop, while the
                         pool and HTTP clients are still usable
              ``final``  after the pool and telemetry are gone

Socket hooks see each authenticated session as it is created or re-authed,
for platform-side session state (analytics identity, admin impersonation).

Nothing registers in a plain install, and every ``run_*`` is a no-op.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

STARTUP_PHASES = ("boot", "ready")
SHUTDOWN_PHASES = ("drain", "final")

Hook = Callable[..., Any]

_startup: Dict[str, List[Tuple[str, Hook]]] = {phase: [] for phase in STARTUP_PHASES}
_shutdown: Dict[str, List[Tuple[str, Hook, Optional[float]]]] = {phase: [] for phase in SHUTDOWN_PHASES}
_socket_connect: List[Hook] = []
_socket_auth_update: List[Hook] = []


def _named(fn: Hook, name: Optional[str]) -> str:
    return name or getattr(fn, "__name__", repr(fn))


def register_startup_hook(fn: Hook, *, phase: str = "ready", name: Optional[str] = None) -> None:
    """``fn`` runs (awaited if it returns an awaitable) at ``phase``. A hook
    that raises stops the boot — a platform that expected to start something
    and could not must not come up looking healthy."""
    if phase not in _startup:
        raise ValueError(f"unknown startup phase {phase!r}; one of {STARTUP_PHASES}")
    _startup[phase].append((_named(fn, name), fn))


def register_shutdown_hook(
    fn: Hook, *, phase: str = "final", timeout: Optional[float] = None, name: Optional[str] = None
) -> None:
    """``fn`` runs at ``phase``, in reverse registration order, bounded by
    ``timeout`` seconds when given. Shutdown is best-effort: a hook that
    fails or times out is logged and the next one still runs."""
    if phase not in _shutdown:
        raise ValueError(f"unknown shutdown phase {phase!r}; one of {SHUTDOWN_PHASES}")
    _shutdown[phase].append((_named(fn, name), fn, timeout))


def register_socket_connect_hook(fn: Hook) -> None:
    """``await fn(session_data, auth)`` before a new socket session is saved;
    the hook may add platform-side keys to ``session_data``."""
    _socket_connect.append(fn)


def register_socket_auth_update_hook(fn: Hook) -> None:
    """``await fn(sid, session, data, proxy)`` when a connected socket re-sends
    its auth; ``data`` is the client payload, ``proxy`` the socket proxy."""
    _socket_auth_update.append(fn)


async def _call(fn: Hook, *args: Any) -> None:
    result = fn(*args)
    if inspect.isawaitable(result):
        await result


async def run_startup_hooks(phase: str) -> None:
    for name, fn in _startup[phase]:
        await _call(fn)
    if _startup[phase]:
        logger.info(f"[lifecycle] ran {len(_startup[phase])} {phase} hook(s)")


async def run_shutdown_hooks(phase: str) -> None:
    for name, fn, timeout in reversed(_shutdown[phase]):
        try:
            if timeout is None:
                await _call(fn)
            else:
                await asyncio.wait_for(_call(fn), timeout=timeout)
        except (asyncio.TimeoutError, Exception) as e:
            logger.warning(f"[shutdown] {name} failed or timed out: {e}")


async def run_socket_connect_hooks(session_data: dict, auth: dict) -> None:
    for fn in _socket_connect:
        await _call(fn, session_data, auth)


async def run_socket_auth_update_hooks(sid: str, session: dict, data: dict, proxy: Any) -> None:
    for fn in _socket_auth_update:
        await _call(fn, sid, session, data, proxy)


def registered_hook_names() -> Dict[str, List[str]]:
    """What is registered, by phase (tests and the boot log)."""
    out: Dict[str, List[str]] = {f"startup:{p}": [n for n, _ in hooks] for p, hooks in _startup.items()}
    out.update({f"shutdown:{p}": [n for n, _, _ in hooks] for p, hooks in _shutdown.items()})
    out["socket_connect"] = [_named(fn, None) for fn in _socket_connect]
    out["socket_auth_update"] = [_named(fn, None) for fn in _socket_auth_update]
    return out


def clear() -> None:
    """Reset registration state (tests)."""
    for hooks in _startup.values():
        hooks.clear()
    for hooks in _shutdown.values():
        hooks.clear()
    _socket_connect.clear()
    _socket_auth_update.clear()
