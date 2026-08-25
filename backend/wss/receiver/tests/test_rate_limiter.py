"""
Test suite for rate limiting functionality.
"""

import asyncio
import pytest
from wss.schema import SocketIORateLimit, SocketIORateLimitConfig
from wss.receiver.rate_limiter import RateLimiter


@pytest.fixture
def rate_limiter_config():
    """Create a test rate limiter configuration."""
    return SocketIORateLimitConfig(
        per_event_rate_limits={
            "chat:message": SocketIORateLimit(second=2, minute=10),
            "yjs:sync": SocketIORateLimit(second=50, minute=500),
        }
    )


@pytest.fixture
def rate_limiter(rate_limiter_config):
    """Create a rate limiter instance."""
    return RateLimiter(rate_limiter_config)


@pytest.mark.asyncio
async def test_normal_usage_within_limits(rate_limiter):
    """Test that requests within rate limits are allowed."""
    test_sid = "test-user-123"
    
    # Make 2 requests (within the 2/sec limit)
    for i in range(2):
        allowed, msg = await rate_limiter.check_rate_limit(test_sid, "chat:message")
        assert allowed is True
        assert msg is None


@pytest.mark.asyncio
async def test_exceed_per_second_limit(rate_limiter):
    """Test that exceeding per-second limit blocks requests."""
    test_sid = "test-user-456"
    
    # Make 2 requests to reach the limit
    for _ in range(2):
        allowed, _ = await rate_limiter.check_rate_limit(test_sid, "chat:message")
        assert allowed is True
    
    # Third request should be blocked
    allowed, msg = await rate_limiter.check_rate_limit(test_sid, "chat:message")
    assert allowed is False
    assert "Rate limit exceeded" in msg
    assert "max 2/sec" in msg


@pytest.mark.asyncio
async def test_rate_limit_reset_after_time_window(rate_limiter):
    """Test that rate limits reset after the time window."""
    test_sid = "test-user-789"
    
    # Exceed the limit
    for _ in range(2):
        await rate_limiter.check_rate_limit(test_sid, "chat:message")
    
    # Should be blocked
    allowed, _ = await rate_limiter.check_rate_limit(test_sid, "chat:message")
    assert allowed is False
    
    # Wait for the second window to pass
    await asyncio.sleep(1.1)
    
    # Should be allowed again
    allowed, _ = await rate_limiter.check_rate_limit(test_sid, "chat:message")
    assert allowed is True



@pytest.mark.asyncio
async def test_per_minute_limit(rate_limiter):
    """Test that per-minute limits are enforced."""
    test_sid = "test-user-minute"
    
    # chat:message has a limit of 10/minute
    # Make requests slowly to avoid per-second limit but hit per-minute limit
    for i in range(10):
        allowed, _ = await rate_limiter.check_rate_limit(test_sid, "chat:message")
        assert allowed is True
        await asyncio.sleep(0.5)  # Wait to avoid per-second limit
    
    # 11th request should be blocked by minute limit
    allowed, msg = await rate_limiter.check_rate_limit(test_sid, "chat:message")
    assert allowed is False
    assert "10/min" in msg


@pytest.mark.asyncio
async def test_usage_statistics(rate_limiter):
    """Test that usage statistics are tracked correctly."""
    test_sid = "test-user-stats"
    
    # Make some requests
    await rate_limiter.check_rate_limit(test_sid, "chat:message")
    await rate_limiter.check_rate_limit(test_sid, "chat:message")
    await rate_limiter.check_rate_limit(test_sid, "yjs:sync")
    
    # Check stats
    stats = await rate_limiter.get_usage_stats(test_sid)
    
    assert "chat:message" in stats
    assert stats["chat:message"]["per_second"] == 2
    assert stats["chat:message"]["per_minute"] == 2
    
    assert "yjs:sync" in stats
    assert stats["yjs:sync"]["per_second"] == 1
    assert stats["yjs:sync"]["per_minute"] == 1


@pytest.mark.asyncio
async def test_cleanup_user(rate_limiter):
    """Test that cleanup removes all user data."""
    test_sid = "test-user-cleanup"
    
    # Make some requests
    await rate_limiter.check_rate_limit(test_sid, "chat:message")
    await rate_limiter.check_rate_limit(test_sid, "yjs:sync")
    
    # Verify data exists
    stats = await rate_limiter.get_usage_stats(test_sid)
    assert len(stats) > 0
    
    # Cleanup
    await rate_limiter.cleanup_user(test_sid)
    
    # Verify data is removed
    stats = await rate_limiter.get_usage_stats(test_sid)
    assert len(stats) == 0




@pytest.mark.asyncio
async def test_multiple_users_isolated(rate_limiter):
    """Test that rate limits are isolated per user."""
    user1 = "user-1"
    user2 = "user-2"
    
    # User 1 hits their limit
    for _ in range(2):
        allowed, _ = await rate_limiter.check_rate_limit(user1, "chat:message")
        assert allowed is True
    
    allowed, _ = await rate_limiter.check_rate_limit(user1, "chat:message")
    assert allowed is False
    
    # User 2 should still be able to make requests
    allowed, _ = await rate_limiter.check_rate_limit(user2, "chat:message")
    assert allowed is True


@pytest.mark.asyncio
async def test_events_without_limits_are_allowed(rate_limiter):
    """Test that events without specific rate limits are always allowed."""
    test_sid = "test-user-unlimited"
    
    # Send many requests for an event type that has no configured limit
    for i in range(100):
        allowed, msg = await rate_limiter.check_rate_limit(test_sid, "unconfigured:event")
        assert allowed is True, f"Request {i+1} should be allowed for unconfigured event"
        assert msg is None

