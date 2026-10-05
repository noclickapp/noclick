"""GET /api/public/instance-status reports what the UI must not guess at: here,
the rate that turns metered credits into the dollars people read (4 on the
hosted service, 1 on an install that bills nobody)."""

from decimal import Decimal

import pytest

from billing import markup
from utils.public_routes import instance_status


@pytest.mark.asyncio
@pytest.mark.parametrize("rate", [Decimal("4"), Decimal("1")])
async def test_reports_the_deployments_credits_per_dollar(monkeypatch, rate):
    monkeypatch.setattr(markup, "CREDITS_PER_DOLLAR", rate)
    body = await instance_status()
    assert body["capabilities"]["creditsPerDollar"] == float(rate)
