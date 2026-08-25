"""
Cooperative cancellation for extension + agentic builder LLM streams.

A CancelScope wraps an asyncio.Event. Streaming loops poll `cancelled` on
every chunk; when set, they call `response.aclose()` to tear down the HTTP
stream and raise `CancelledByUser`. Callers (the agentic builder, autofill,
the socket handler) catch CancelledByUser at the outer turn boundary and
discard partial state so the next prompt starts from the previous turn's
context.

The scope is also stashed in a ContextVar so deep call sites don't all need
explicit passing — pass it once at the entry point and `current_scope()`
picks it up anywhere downstream. Explicit passing still works (and wins)
when a scope is provided directly.
"""
from __future__ import annotations

import asyncio
import contextvars
from typing import Optional


class CancelledByUser(Exception):
    """Raised when a user-initiated pause cancels an in-flight LLM stream."""


# Cancellation reason markers. Default ("user") means a user-initiated pause
# (ChatBox stop button) — terminal. "op_limit" means the brain emitted more
# than the runaway-detection threshold of XML ops in a single turn — the
# turn is discarded but the run continues with a corrective system message.
CancelReason = str  # "user" | "op_limit" | other future markers


class CancelScope:
    """Thread-safe-ish (single-loop) cancellation token.

    Created once per builder run / autofill call. `cancel()` sets the underlying
    event; checks anywhere downstream see the change immediately. After
    cancellation the scope stays cancelled — create a new one for the next run.

    `reason` distinguishes user-initiated pauses from internal kills (e.g.
    runaway op-count detection) so the turn loop can dispatch differently.
    """

    __slots__ = ("_event", "_reason")

    def __init__(self) -> None:
        self._event = asyncio.Event()
        self._reason: CancelReason = "user"

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> CancelReason:
        return self._reason

    def cancel(self, reason: CancelReason = "user") -> None:
        # First-cancel-wins: if already cancelled, keep the original reason.
        if not self._event.is_set():
            self._reason = reason
        self._event.set()

    def reset(self) -> None:
        """Clear the cancel state so the same scope can keep watching.

        Used after an internal kill (e.g. op_limit) so the registered scope
        remains valid for a subsequent user-initiated pause. The registry
        keys on conversation_id, so swapping the scope object would orphan
        the registration — clearing the event in place avoids that.
        """
        self._event.clear()
        self._reason = "user"

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise CancelledByUser()


_CURRENT_SCOPE: contextvars.ContextVar[Optional[CancelScope]] = contextvars.ContextVar(
    "extension_cancel_scope", default=None,
)


def current_scope() -> Optional[CancelScope]:
    """Return the scope bound to the current async context, or None."""
    return _CURRENT_SCOPE.get()


def bind_scope(scope: Optional[CancelScope]) -> contextvars.Token:
    """Bind `scope` for the duration of the current task. Returns a token to reset with."""
    return _CURRENT_SCOPE.set(scope)


def reset_scope(token: contextvars.Token) -> None:
    _CURRENT_SCOPE.reset(token)


def check_cancelled(scope: Optional[CancelScope] = None) -> None:
    """Raise CancelledByUser if the given scope (or the contextvar) is cancelled."""
    s = scope if scope is not None else _CURRENT_SCOPE.get()
    if s is not None and s.cancelled:
        raise CancelledByUser()


async def aclose_quietly(response) -> None:
    """Close a litellm streaming response without letting cleanup errors mask CancelledByUser.

    litellm wraps the provider's async generator in a CustomStreamWrapper,
    which itself wraps a provider-specific handler (e.g.
    OpenRouterChatCompletionStreamingHandler) whose `streaming_response` and
    `response_iterator` are the real async generators with `aclose()`. The
    wrapper does not forward aclose, so we walk one level into
    `completion_stream.streaming_response` / `response_iterator` and close
    whichever exposes aclose. Belt-and-suspenders: also try the top-level.
    """
    if response is None:
        return

    candidates = [response]
    inner = getattr(response, "completion_stream", None)
    if inner is not None:
        candidates.append(inner)
        for attr in ("streaming_response", "response_iterator"):
            sub = getattr(inner, attr, None)
            if sub is not None:
                candidates.append(sub)

    for cand in candidates:
        aclose = getattr(cand, "aclose", None)
        if aclose is None:
            continue
        try:
            await aclose()
        except Exception:
            pass


# Process-level registry of active builder runs keyed by conversation_id.
# Populated by the workflow builder handler when a run starts; the agent
# handler's pause endpoint reads it so a single agent:pause event can cancel
# whichever path is currently running (OpenHands chat or builder edit).
# Keyed by conversation_id (not generation_id) because the frontend sends
# conversation_id on AgentPauseRequest.
_ACTIVE_BUILDER_SCOPES: dict[str, CancelScope] = {}


def register_builder_scope(conversation_id: str, scope: CancelScope) -> None:
    """Register a builder run's CancelScope so external pause events can find it."""
    if conversation_id:
        _ACTIVE_BUILDER_SCOPES[conversation_id] = scope


def unregister_builder_scope(conversation_id: str, scope: CancelScope) -> None:
    """Remove the registration if the slot still points at this scope."""
    if not conversation_id:
        return
    existing = _ACTIVE_BUILDER_SCOPES.get(conversation_id)
    if existing is scope:
        _ACTIVE_BUILDER_SCOPES.pop(conversation_id, None)


def get_builder_scope(conversation_id: str) -> Optional[CancelScope]:
    """Return the active builder scope for a conversation, or None."""
    return _ACTIVE_BUILDER_SCOPES.get(conversation_id)


def cancel_all_builder_scopes(reason: CancelReason = "shutdown") -> int:
    """Cancel every registered builder run. Returns the number cancelled.

    Called from the ASGI lifespan shutdown so a container drain/scale-down
    flips active runs into the cooperative teardown path (stream aclose →
    CancelledByUser → finalize) within the drain grace window, instead of the
    coroutine being hard-killed mid-stream and the run left as a zombie. The
    distinct ``reason`` ("shutdown", not "user") lets the turn loop tell a
    drain apart from a user-initiated pause if it ever needs to. Iterates a
    snapshot so a concurrent unregister during teardown can't mutate-mid-loop.
    """
    scopes = list(_ACTIVE_BUILDER_SCOPES.values())
    for scope in scopes:
        scope.cancel(reason)
    return len(scopes)
