"""The usage page's reads are rate limited per tab (wss/receiver/rate_limits.py):
``usage:page`` reads every group of two billing windows, so a client looping on
it is refused, while the page's own re-reads and a CSV export paging through
every charge get through."""

from types import SimpleNamespace

import pytest

from wss.receiver import rate_limiter as rate_limiter_module
from wss.receiver.rate_limiter import RateLimiter
from wss.receiver.rate_limits import get_rate_limit_config

pytestmark = pytest.mark.asyncio


@pytest.fixture
def clock(monkeypatch):
    now = [1_000.0]
    monkeypatch.setattr(rate_limiter_module, "time", SimpleNamespace(time=lambda: now[0]))
    return now


@pytest.mark.parametrize("event", ["usage:page", "usage:charges"])
async def test_a_loop_on_a_usage_read_is_refused(clock, event):
    limiter = RateLimiter(get_rate_limit_config())
    allowed = [(await limiter.check_rate_limit("sid", event))[0] for _ in range(100)]
    assert allowed.count(False) > 0 and allowed[0] is True
    assert (await limiter.check_rate_limit("other-sid", event))[0] is True


async def test_the_pages_own_rereads_get_through(clock):
    """A load, a re-read a usage frame settles to (every 5 s) and a focus, for a minute."""
    limiter = RateLimiter(get_rate_limit_config())
    allowed = []
    for _ in range(12):
        allowed.append((await limiter.check_rate_limit("sid", "usage:page"))[0])
        clock[0] += 0.5
        allowed.append((await limiter.check_rate_limit("sid", "usage:page"))[0])
        clock[0] += 4.5
    assert all(allowed)


async def test_a_csv_export_pages_through_every_charge(clock):
    """Download CSV reads every page of 500 back to back: 100,000 charges at a fast round trip."""
    limiter = RateLimiter(get_rate_limit_config())
    allowed = []
    for _ in range(200):
        allowed.append((await limiter.check_rate_limit("sid", "usage:charges"))[0])
        clock[0] += 0.06
    assert all(allowed)
