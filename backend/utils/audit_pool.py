"""Optional credential-refresh audit sink for community installations.

Refresh health is emitted through OpenTelemetry by default. Operators that
need durable, installation-local audit rows can replace this module with a
sink designed for their own retention and privacy policy.
"""

from __future__ import annotations

from typing import Any, Mapping


async def record_refresh_event(row: Mapping[str, Any]) -> None:
    """Accept the compatibility hook without persisting sensitive token data."""
    del row


async def close_audit_pool() -> None:
    """Compatibility shutdown hook for installations without a durable sink."""
    return None
