"""Bounded projections of stored values, for readers that want their shape, not their bulk."""

from typing import Any

MAX_ITEMS = 10
MAX_CHARS = 280


def bounded(value: Any, *, max_items: int = MAX_ITEMS, max_chars: int = MAX_CHARS, depth: int = 8) -> Any:
    """``value`` with lists capped, strings clipped and nesting limited. Keys
    are kept, so ids stay usable by whatever reads them next."""
    if depth <= 0:
        return "…"
    if isinstance(value, dict):
        return {str(k): bounded(v, max_items=max_items, max_chars=max_chars, depth=depth - 1) for k, v in value.items()}
    if isinstance(value, list):
        clipped = [bounded(v, max_items=max_items, max_chars=max_chars, depth=depth - 1) for v in value[:max_items]]
        if len(value) > max_items:
            clipped.append(f"… {len(value) - max_items} more")
        return clipped
    if isinstance(value, str) and len(value) > max_chars:
        return value[: max_chars - 1] + "…"
    return value
