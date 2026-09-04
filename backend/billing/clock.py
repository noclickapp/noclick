"""Billing time.

Every window calculation reads the clock through here, so that time can be
moved in tests and in development without the rest of the system knowing. The
default is the real UTC clock, offset by whatever `set_dev_clock` was given.

A platform whose billing periods are anchored elsewhere — a payment
provider's test clock, say — registers its own source, and every window
follows it.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_dev_offset: Optional[timedelta] = None
_source: Optional[Callable[[], datetime]] = None


def register_clock_source(source: Callable[[], datetime]) -> None:
    """Install a platform's time source. Call before serving traffic."""
    global _source
    _source = source
    logger.info("[clock] Time source registered")


def billing_now() -> datetime:
    if _source is not None:
        return _source()
    now = datetime.now(timezone.utc)
    return now + _dev_offset if _dev_offset else now


def billing_day_start_utc(now: Optional[datetime] = None) -> datetime:
    now = now or billing_now()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def billing_month_start_utc(now: Optional[datetime] = None) -> datetime:
    now = now or billing_now()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def set_dev_clock(epoch_seconds: float) -> None:
    """Pin the simulated clock to an absolute epoch, matching the hosted
    signature — it takes epoch seconds, not a datetime, and its one caller
    passes a float. Held in process rather than Redis: this build has no test
    clock to mirror, so there is nothing to share across containers."""
    global _dev_offset
    _dev_offset = datetime.fromtimestamp(epoch_seconds, timezone.utc) - datetime.now(timezone.utc)


def clear_dev_clock() -> None:
    global _dev_offset
    _dev_offset = None
