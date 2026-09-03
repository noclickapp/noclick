"""Charges that repeat on a clock — a connected WhatsApp number, anything else
a platform bills per period.

The engine has no recurring charges of its own: it runs workflows. A platform
that does registers its sweep, and the daily maintenance job calls through here.
"""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

_impl: Optional[Any] = None


def register_recurring_charges(impl: Any) -> None:
    """Install a platform's recurring-charge processor."""
    global _impl
    _impl = impl
    logger.info(f"[recurring] Registered: {type(impl).__name__}")


async def start_connection_charge(conn, *, user_id, credential_id, charge_type: str) -> None:
    """Begin billing a connection-backed credential (a linked WhatsApp number)
    per period, inside the caller's transaction. Nothing registered means
    nothing to bill — the credential simply exists."""
    if _impl is None or not hasattr(_impl, "start_connection_charge"):
        return
    await _impl.start_connection_charge(
        conn, user_id=user_id, credential_id=credential_id, charge_type=charge_type
    )


async def process_all_recurring_charges(*args, **kwargs) -> dict:
    """Returns a per-run summary. Nothing registered means nothing recurs."""
    if _impl is None:
        return {"processed": 0, "charged": 0, "skipped": 0, "errors": 0}
    return await _impl.process_all_recurring_charges(*args, **kwargs)
