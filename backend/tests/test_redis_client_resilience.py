"""Infra Redis clients must carry bounded-latency knobs (RESILIENCE_KWARGS).

A stale pooled connection (laptop network change, Upstash idling a socket out)
blocked a tool bundle SETEX for 2m31s on 2026-07-18 and killed the agent
turn dispatching it. Every infra client shares the knobs from
utils.redis_client so a dead socket fails in seconds; retry_on_timeout stays
off (INCR fire budgets / SET NX claims are not blindly retryable).
"""

import pytest

from utils.redis_client import RESILIENCE_KWARGS


def test_knobs_are_bounded_and_non_retrying():
    assert RESILIENCE_KWARGS["socket_timeout"] <= 15
    assert RESILIENCE_KWARGS["socket_connect_timeout"] <= 5
    assert RESILIENCE_KWARGS["health_check_interval"] > 0
    assert "retry_on_timeout" not in RESILIENCE_KWARGS


