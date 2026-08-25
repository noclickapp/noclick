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


def configure_credits_remaining(credits: float | None):
    """Configure the value returned by check_credit_balance in tests.

    Args:
        credits: Float for a specific credit count (e.g. 50.0), or None to
                 simulate Enterprise / unlimited.
    """
    global _mock_credits_remaining
    _mock_credits_remaining = credits

    from billing.usage_tracker import usage_tracker

    async def mock_check_credit_balance(user_id, use_cache=True):
        return _mock_credits_remaining

    patch.object(usage_tracker, 'check_credit_balance', new=AsyncMock(side_effect=mock_check_credit_balance)).start()


def reset_credit_balance():
    """Reset credit balance mocking to default (no mocking)."""
    global _mock_credits_remaining
    _mock_credits_remaining = None
