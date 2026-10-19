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


async def start_connection_charge(conn, *, user_id, credential_id, charge_type: str, period_usd=None,
                                  upfront_usd=None) -> None:
    """Begin billing a connection-backed credential (a linked WhatsApp number,
    a bought phone number) per period, inside the caller's transaction. A
    credential priced on its own (a phone number) names its vendor's price:
    ``period_usd`` a period, ``upfront_usd`` once to acquire it. Nothing
    registered means nothing to bill — the credential simply exists."""
    if _impl is None or not hasattr(_impl, "start_connection_charge"):
        return
    priced = {k: v for k, v in (("period_usd", period_usd), ("upfront_usd", upfront_usd)) if v is not None}
    await _impl.start_connection_charge(
        conn, user_id=user_id, credential_id=credential_id, charge_type=charge_type, **priced
    )


async def charge_credits(user_id: str, charge_type: str, vendor_usd) -> float:
    """What a charge of ``charge_type`` whose vendor price is ``vendor_usd``
    costs the account that pays for it, in credits (a platform's plans can
    price it differently by account); the vendor's price where nothing is
    registered to say."""
    if _impl is None or not hasattr(_impl, "charge_credits"):
        from billing.markup import CREDITS_PER_DOLLAR

        return round(float(vendor_usd) * float(CREDITS_PER_DOLLAR), 4)
    return await _impl.charge_credits(user_id, charge_type, vendor_usd)


async def process_all_recurring_charges(*args, **kwargs) -> dict:
    """Returns a per-run summary. Nothing registered means nothing recurs."""
    if _impl is None:
        return {"processed": 0, "charged": 0, "skipped": 0, "errors": 0}
    return await _impl.process_all_recurring_charges(*args, **kwargs)
