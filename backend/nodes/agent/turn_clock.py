"""The current date and time an agent's turn is told, in a timezone a platform
picks per turn.

A platform sets the runtime config key ``TURN_CLOCK_KEY`` on the agent node
(``{"timezone": "<IANA name>"}``); the agent node then opens the turn with
``clock_line`` before dispatch, so every harness reads the same line and
"last month" or "this Friday" mean what they say."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

TURN_CLOCK_KEY = "_turnClock"


def clock_of(node_config: Any) -> Optional[str]:
    """The turn's timezone, when a platform set the clock."""
    spec = node_config.get(TURN_CLOCK_KEY) if isinstance(node_config, dict) else None
    zone = spec.get("timezone") if isinstance(spec, dict) else None
    return zone if isinstance(zone, str) and zone else None


def clock_line(zone: str, now: Optional[datetime] = None) -> str:
    """``It is Wednesday, 1 October 2026, 14:03 in Europe/London (UTC+01:00).``"""
    local = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(zone))
    offset = local.strftime("%z")
    return (f"It is {local.strftime('%A')}, {local.day} {local.strftime('%B %Y, %H:%M')} in {zone} "
            f"(UTC{offset[:3]}:{offset[3:]}).")
