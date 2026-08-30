"""Schedule ticks are posted through the instance's own front door.

Webhook URLs carry the public origin. From inside the instance that origin may
not route back at all — on a laptop, localhost:PORT is the container's own
loopback — so a tick that reached zero was "Running" and nothing ever ran.
"""

import pytest

from utils.local_cron import _delivery_url


def test_public_origin_is_swapped_for_the_reachable_one(monkeypatch):
    monkeypatch.setenv("LOCAL_CRON_DELIVERY_ORIGIN", "http://127.0.0.1:8080")
    assert (
        _delivery_url("https://noclick.example.com/abc-123?x=1")
        == "http://127.0.0.1:8080/abc-123?x=1"
    ), "only the origin changes — the webhook path is delivered exactly as minted"


def test_unset_origin_delivers_to_the_minted_url(monkeypatch):
    monkeypatch.delenv("LOCAL_CRON_DELIVERY_ORIGIN", raising=False)
    assert _delivery_url("https://noclick.example.com/abc-123") == "https://noclick.example.com/abc-123"


def test_the_ticker_sleeps_until_the_earliest_due_schedule():
    from datetime import datetime, timedelta, timezone
    from utils.local_cron import _TICK_INTERVAL_S, _sleep_seconds

    now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    assert _sleep_seconds(None, now) == _TICK_INTERVAL_S, "nothing scheduled: a full tick"
    assert _sleep_seconds(now + timedelta(seconds=5), now) == 5.0, "an every-5s schedule fires every 5s, not every tick"
    assert _sleep_seconds(now + timedelta(hours=1), now) == _TICK_INTERVAL_S, "never longer than a tick"
    assert _sleep_seconds(now - timedelta(seconds=30), now) == 1.0, "overdue: straight back, but never a busy loop"
