"""Compatibility no-op for managed team-observability hooks."""

from __future__ import annotations


async def notify_tool_use(*args, **kwargs) -> None:
    return None


def notify_tool_use_background(*args, **kwargs) -> None:
    return None
