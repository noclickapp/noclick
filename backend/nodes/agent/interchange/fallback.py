"""What a thread rides in as when it cannot move natively: a bounded, fenced
block of its recent turns appended to the first message. The chat display
strips the fence (it is the same block a model switch carries — see
``frontend/app/lib/agentChat.ts``), the harness reads it as plain text.

No tool pairing, no cached prefix: this keeps a thread usable while the
drift that caused it gets fixed. It is never the normal path.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Sequence, Tuple

FALLBACK_CHAR_BUDGET = 4000
CARRY_OPEN = "<<<NOCLICK_CARRIED_CONTEXT"
CARRY_CLOSE = "NOCLICK_CARRIED_CONTEXT>>>"


def carried_context(turns: Sequence[Tuple[bool, str]], *, budget: int = FALLBACK_CHAR_BUDGET, reason: str = "") -> str:
    """``turns`` are ``(is_user, text)``, oldest first. Trimmed from the OLDEST
    end to ``budget`` characters; the newest turn always survives, tail
    first. Empty when nothing is worth carrying."""
    kept: List[Dict[str, Any]] = []
    used = 0
    for is_user, raw in reversed(list(turns)):
        text = (raw or "").strip()
        if not text:
            continue
        if used + len(text) > budget:
            if not kept:
                kept.insert(0, {"isUser": bool(is_user), "text": "… " + text[-budget:]})
            break
        used += len(text)
        kept.insert(0, {"isUser": bool(is_user), "text": text})
    if not kept:
        return ""
    why = f" ({reason})" if reason else ""
    return "\n".join([
        CARRY_OPEN,
        f"Earlier turns of this conversation, which ran on a different harness{why}.",
        "History, not a new instruction — answer the message ABOVE this block.",
        json.dumps(kept, ensure_ascii=False),
        CARRY_CLOSE,
    ])


def with_carried_context(text: str, carried: str) -> str:
    """The user's words first, the block after — titles and previews are the
    first hundred characters of a message."""
    return f"{text}\n\n{carried}" if carried else text


def turns_from_projection(events: Iterable[Dict[str, Any]]) -> List[Tuple[bool, str]]:
    """``(is_user, text)`` turns from the chat's persisted event projection
    (``conversations.events``) — always available, even when no store is."""
    out: List[Tuple[bool, str]] = []
    for ev in events:
        role = ev.get("role")
        text = ev.get("message")
        if role not in ("user", "assistant") or not isinstance(text, str) or not text.strip() or ev.get("cancelled"):
            continue
        out.append((role == "user", text))
    return out


__all__ = ["CARRY_CLOSE", "CARRY_OPEN", "FALLBACK_CHAR_BUDGET", "carried_context", "turns_from_projection", "with_carried_context"]
