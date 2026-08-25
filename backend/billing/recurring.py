"""Optional recurring-usage processor."""

from __future__ import annotations

from typing import Any, Optional


_impl: Optional[Any] = None


def register_recurring_charges(impl: Any) -> None:
    global _impl
    _impl = impl


async def process_all_recurring_charges(*args, **kwargs) -> dict:
    if _impl is None:
        return {"processed": 0, "charged": 0, "skipped": 0, "errors": 0}
    return await _impl.process_all_recurring_charges(*args, **kwargs)
