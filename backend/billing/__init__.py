"""Metering, and the seams a platform bills through.

The engine records what work cost and asks whether an account may proceed. It
does not know how to charge anyone, and an installation running on its own
provider keys never needs it to: the defaults record nothing, refuse nothing and
price everything at zero.

A platform installs its own behaviour through the register_* functions in these
modules — usage_tracker, plan_limits, pricing, recurring — before it serves
traffic. What differs by deployment rather than by code (the markup floor, the
per-unit prices) comes from the environment.
"""

from .schema import UsageEventData
from .usage_tracker import UsageTracker, usage_tracker

__all__ = ["UsageTracker", "usage_tracker", "UsageEventData"]
