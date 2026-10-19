"""An instance that bills nobody (no platform tracker registered) records an
unreported cost as $0 without asking OpenRouter for it (utils/openrouter_cost.settle):
there is nothing to charge, so nothing to look up or warn about."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from billing.usage_tracker import UsageTracker, charges_usage, usage_tracker
from utils import openrouter_cost


async def test_nothing_is_looked_up_where_nothing_is_billed(monkeypatch):
    lookup = AsyncMock(return_value=Decimal("0.01"))
    monkeypatch.setattr(openrouter_cost, "generation_cost", lookup)
    monkeypatch.setattr(usage_tracker, "_impl", UsageTracker())  # the engine's own: records nothing

    assert charges_usage() is False
    assert await openrouter_cost.settle(None, False, "gen-1") == Decimal(0)
    assert await openrouter_cost.settle(0.2, True, "gen-1") == Decimal("0.2")
    lookup.assert_not_awaited()


async def test_where_usage_is_charged_a_missing_cost_is_looked_up(monkeypatch):
    lookup = AsyncMock(return_value=Decimal("0.01"))
    monkeypatch.setattr(openrouter_cost, "generation_cost", lookup)
    monkeypatch.setattr(usage_tracker, "_impl", SimpleNamespace())  # a platform's tracker

    assert charges_usage() is True
    assert await openrouter_cost.settle(None, False, "gen-1") == Decimal("0.01")
    with pytest.raises(openrouter_cost.CostUnknown):
        await openrouter_cost.settle(None, False, None)
