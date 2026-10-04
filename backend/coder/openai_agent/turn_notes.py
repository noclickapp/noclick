"""What the model wrote beside its latest model call in a run: the reason it
gave for that response's tool calls, for whatever vets them (a product's
tool-call guard). A mutable holder set per run, so the run hooks and the tool
calls, each in tasks of their own, share it."""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any, Dict, Optional

_NOTES: ContextVar[Optional[Dict[str, Any]]] = ContextVar("openai_agent_turn_notes", default=None)


def start() -> Token:
    return _NOTES.set({})


def reset(token: Token) -> None:
    _NOTES.reset(token)


def remember(response: Any) -> None:
    """Keep the text of a model response (its message parts), or none."""
    notes = _NOTES.get()
    if notes is None:
        return
    parts = [getattr(part, "text", None) for item in getattr(response, "output", None) or []
             if getattr(item, "type", None) == "message" for part in getattr(item, "content", None) or []]
    notes["reason"] = "".join(p for p in parts if isinstance(p, str)).strip() or None


def stated_reason() -> Optional[str]:
    notes = _NOTES.get()
    return notes.get("reason") if notes else None
