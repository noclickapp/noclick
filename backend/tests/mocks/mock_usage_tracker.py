"""
Mock usage tracker for testing.

Provides credit-balance mocking for the real UsageTracker. (The legacy
database-layer patch helpers targeted the deleted sync manager verbs and
were removed with the 2026-07-01 native-pool migration.)
"""

import logging
from unittest.mock import patch, AsyncMock

logger = logging.getLogger(__name__)


# Credit balance mocking for tests. Sets the value returned by
# usage_tracker.check_credit_balance — None for unlimited (Enterprise),
# float for a specific credit count. The legacy configure_account_balance
# helper that pretended a $ balance existed was removed alongside the
# Phase 2.1 sunset of the user_billing.balance pool.
_mock_credits_remaining: float | None = None
_balance_patch = None


def configure_credits_remaining(credits: float | None):
    """Configure the value returned by check_credit_balance in tests, until
    ``reset_credit_balance``.

    Args:
        credits: Float for a specific credit count (e.g. 50.0), or None to
                 simulate Enterprise / unlimited.
    """
    global _mock_credits_remaining, _balance_patch
    _mock_credits_remaining = credits
    if _balance_patch is not None:
        return

    from billing.usage_tracker import usage_tracker

    async def mock_check_credit_balance(user_id, use_cache=True):
        return _mock_credits_remaining

    _balance_patch = patch.multiple(
        usage_tracker,
        check_credit_balance=AsyncMock(side_effect=mock_check_credit_balance),
        spend_cap_refusal=AsyncMock(return_value=None),  # no monthly spending cap
    )
    _balance_patch.start()


def reset_credit_balance():
    """Put the real check_credit_balance back: a balance left mocked answers
    every later test in the process, whose credit gates then never refuse."""
    global _mock_credits_remaining, _balance_patch
    _mock_credits_remaining = None
    if _balance_patch is not None:
        _balance_patch.stop()
        _balance_patch = None
