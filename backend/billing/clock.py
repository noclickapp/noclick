"""UTC clock helpers for metering windows."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional


_source: Optional[Any] = None


def register_clock_source(source: Any) -> None:
    global _source
    _source = source


def billing_now() -> datetime:
    if _source is not None:
        return _source.now()
    return datetime.now(timezone.utc)


def billing_day_start_utc(now: Optional[datetime] = None) -> datetime:
    return (now or billing_now()).astimezone(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def billing_month_start_utc(now: Optional[datetime] = None) -> datetime:
    return (now or billing_now()).astimezone(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )


async def set_dev_clock(*_args, **_kwargs) -> None:
    return None


async def clear_dev_clock(*_args, **_kwargs) -> None:
    return None
