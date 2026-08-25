"""
Live integration tests for Redis node operations.

Tests Redis operations directly using httpx against a live Upstash Redis instance.
Requires UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN environment variables.

Run with: pytest nodes/tests/test_redis_node_integration.py -v
Or skip if credentials not available: pytest nodes/tests/test_redis_node_integration.py -v --skip-integration
"""

import pytest
import pytest_asyncio
import httpx
import os
import time
from typing import Dict, List, Any


# Skip all tests in this file if Upstash credentials not available
pytestmark = pytest.mark.skipif(
    not os.environ.get("UPSTASH_REDIS_REST_URL") or not os.environ.get("UPSTASH_REDIS_REST_TOKEN"),
    reason="Upstash Redis credentials not available (set UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN)"
)


class RedisIntegrationTester:
    """Helper class for Redis integration testing."""

    def __init__(self, rest_url: str, rest_token: str):
        self.rest_url = rest_url.rstrip('/')
        self.rest_token = rest_token
        self.test_prefix = f"test_{int(time.time())}_"
        self.created_keys = []

    def test_key(self, suffix: str) -> str:
        """Generate a unique test key."""
        key = f"{self.test_prefix}{suffix}"
        self.created_keys.append(key)
        return key

    async def redis_get(self, path: str) -> Dict[str, Any]:
        """Make a GET request to Upstash Redis REST API."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.rest_url}{path}",
                headers={"Authorization": f"Bearer {self.rest_token}"},
                timeout=30.0
            )
            if response.status_code == 200:
                data = response.json()
                return {"status": "success", "data": data.get("result", data)}
            return {"status": "error", "code": response.status_code, "text": response.text}

    async def redis_post(self, command: List[Any]) -> Dict[str, Any]:
        """Make a POST request to Upstash Redis REST API."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.rest_url}",
                json=command,
                headers={"Authorization": f"Bearer {self.rest_token}"},
                timeout=30.0
            )
            if response.status_code == 200:
                data = response.json()
                return {"status": "success", "data": data.get("result", data)}
            return {"status": "error", "code": response.status_code, "text": response.text}

    async def cleanup(self):
        """Clean up test keys."""
        if self.created_keys:
            try:
                await self.redis_post(["DEL"] + self.created_keys)
            except Exception:
                pass  # Ignore cleanup errors


@pytest_asyncio.fixture
async def tester():
    """Create a Redis integration tester instance."""
    rest_url = os.environ.get("UPSTASH_REDIS_REST_URL", "")
    rest_token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")

    t = RedisIntegrationTester(rest_url, rest_token)
    yield t
    await t.cleanup()


# ========== CONNECTION OPERATIONS ==========

@pytest.mark.asyncio
async def test_ping(tester):
    """Test PING operation."""
    r = await tester.redis_post(["PING"])
    assert r["status"] == "success"
    assert r["data"] in ["PONG", "pong"]


@pytest.mark.asyncio
async def test_ping_with_message(tester):
    """Test PING with message."""
    r = await tester.redis_post(["PING", "Hello"])
    assert r["status"] == "success"
    assert r["data"] == "Hello"


@pytest.mark.asyncio
async def test_echo(tester):
    """Test ECHO operation."""
    r = await tester.redis_post(["ECHO", "test"])
    assert r["status"] == "success"
    assert r["data"] == "test"


@pytest.mark.asyncio
async def test_select(tester):
    """Test SELECT operation."""
    r = await tester.redis_post(["SELECT", "0"])
    assert r["status"] == "success"


# ========== SERVER OPERATIONS ==========

@pytest.mark.asyncio
async def test_dbsize(tester):
    """Test DBSIZE operation."""
    r = await tester.redis_post(["DBSIZE"])
    assert r["status"] == "success"
    assert isinstance(r["data"], int)


@pytest.mark.asyncio
async def test_time(tester):
    """Test TIME operation."""
    r = await tester.redis_post(["TIME"])
    assert r["status"] == "success"
    assert isinstance(r["data"], list)
    assert len(r["data"]) == 2


# ========== STRING OPERATIONS ==========

@pytest.mark.asyncio
async def test_get_set(tester):
    """Test GET and SET operations."""
    k = tester.test_key("str1")
    # Set value
    r = await tester.redis_get(f"/set/{k}/testval")
    assert r["status"] == "success"
    # Get value
    r = await tester.redis_get(f"/get/{k}")
    assert r["status"] == "success"
    assert r["data"] == "testval"


@pytest.mark.asyncio
async def test_mget_mset(tester):
    """Test MGET and MSET operations."""
    k1, k2 = tester.test_key("str2"), tester.test_key("str3")
    # MSET
    r = await tester.redis_post(["MSET", k1, "v1", k2, "v2"])
    assert r["status"] == "success"
    # MGET
    r = await tester.redis_get(f"/mget/{k1}/{k2}")
    assert r["status"] == "success"
    assert isinstance(r["data"], list)


@pytest.mark.asyncio
async def test_incr_decr(tester):
    """Test INCR and DECR operations."""
    k = tester.test_key("ctr1")
    # INCR
    r = await tester.redis_get(f"/incr/{k}")
    assert r["status"] == "success"
    assert r["data"] == 1
    # DECR
    r = await tester.redis_get(f"/decr/{k}")
    assert r["status"] == "success"
    assert r["data"] == 0


@pytest.mark.asyncio
async def test_incrby_decrby(tester):
    """Test INCRBY and DECRBY operations."""
    k = tester.test_key("ctr2")
    # INCRBY
    r = await tester.redis_get(f"/incrby/{k}/5")
    assert r["status"] == "success"
    assert r["data"] == 5
    # DECRBY
    r = await tester.redis_get(f"/decrby/{k}/3")
    assert r["status"] == "success"
    assert r["data"] == 2


@pytest.mark.asyncio
async def test_append_strlen(tester):
    """Test APPEND and STRLEN operations."""
    k = tester.test_key("app1")
    await tester.redis_post(["SET", k, "hello"])
    # APPEND
    r = await tester.redis_get(f"/append/{k}/world")
    assert r["status"] == "success"
    # STRLEN
    r = await tester.redis_get(f"/strlen/{k}")
    assert r["status"] == "success"
    assert r["data"] == 10  # "helloworld"


@pytest.mark.asyncio
async def test_getdel(tester):
    """Test GETDEL operation."""
    k = tester.test_key("gdel1")
    await tester.redis_post(["SET", k, "value"])
    r = await tester.redis_get(f"/getdel/{k}")
    assert r["status"] == "success"
    assert r["data"] == "value"
    # Verify deleted
    r = await tester.redis_get(f"/get/{k}")
    assert r["data"] is None


# ========== HASH OPERATIONS ==========

@pytest.mark.asyncio
async def test_hget_hset(tester):
    """Test HGET and HSET operations."""
    k = tester.test_key("hash1")
    # HSET
    r = await tester.redis_get(f"/hset/{k}/field/value")
    assert r["status"] == "success"
    # HGET
    r = await tester.redis_get(f"/hget/{k}/field")
    assert r["status"] == "success"
    assert r["data"] == "value"


@pytest.mark.asyncio
async def test_hgetall(tester):
    """Test HGETALL operation."""
    k = tester.test_key("hash2")
    await tester.redis_post(["HSET", k, "f1", "v1", "f2", "v2"])
    r = await tester.redis_get(f"/hgetall/{k}")
    assert r["status"] == "success"
    assert isinstance(r["data"], (list, dict))


@pytest.mark.asyncio
async def test_hdel(tester):
    """Test HDEL operation."""
    k = tester.test_key("hash3")
    await tester.redis_post(["HSET", k, "f1", "v1"])
    r = await tester.redis_get(f"/hdel/{k}/f1")
    assert r["status"] == "success"


@pytest.mark.asyncio
async def test_hkeys_hvals(tester):
    """Test HKEYS and HVALS operations."""
    k = tester.test_key("hash4")
    await tester.redis_post(["HSET", k, "f1", "v1", "f2", "v2"])
    # HKEYS
    r = await tester.redis_get(f"/hkeys/{k}")
    assert r["status"] == "success"
    assert isinstance(r["data"], list)
    # HVALS
    r = await tester.redis_get(f"/hvals/{k}")
    assert r["status"] == "success"
    assert isinstance(r["data"], list)


@pytest.mark.asyncio
async def test_hexists_hlen(tester):
    """Test HEXISTS and HLEN operations."""
    k = tester.test_key("hash5")
    await tester.redis_post(["HSET", k, "f1", "v1"])
    # HEXISTS
    r = await tester.redis_get(f"/hexists/{k}/f1")
    assert r["status"] == "success"
    assert r["data"] == 1
    # HLEN
    r = await tester.redis_get(f"/hlen/{k}")
    assert r["status"] == "success"
    assert r["data"] == 1


# ========== LIST OPERATIONS ==========

@pytest.mark.asyncio
async def test_lpush_rpush(tester):
    """Test LPUSH and RPUSH operations."""
    k = tester.test_key("list1")
    # LPUSH
    r = await tester.redis_post(["LPUSH", k, "v1", "v2"])
    assert r["status"] == "success"
    # RPUSH
    r = await tester.redis_post(["RPUSH", k, "v3"])
    assert r["status"] == "success"


@pytest.mark.asyncio
async def test_lpop_rpop(tester):
    """Test LPOP and RPOP operations."""
    k = tester.test_key("list2")
    await tester.redis_post(["RPUSH", k, "v1", "v2", "v3"])
    # LPOP
    r = await tester.redis_get(f"/lpop/{k}")
    assert r["status"] == "success"
    # RPOP
    r = await tester.redis_get(f"/rpop/{k}")
    assert r["status"] == "success"


@pytest.mark.asyncio
async def test_lrange_llen(tester):
    """Test LRANGE and LLEN operations."""
    k = tester.test_key("list3")
    await tester.redis_post(["RPUSH", k, "v1", "v2", "v3"])
    # LRANGE
    r = await tester.redis_get(f"/lrange/{k}/0/-1")
    assert r["status"] == "success"
    assert isinstance(r["data"], list)
    # LLEN
    r = await tester.redis_get(f"/llen/{k}")
    assert r["status"] == "success"
    assert r["data"] == 3


# ========== SET OPERATIONS ==========

@pytest.mark.asyncio
async def test_sadd_smembers(tester):
    """Test SADD and SMEMBERS operations."""
    k = tester.test_key("set1")
    # SADD
    r = await tester.redis_post(["SADD", k, "m1", "m2", "m3"])
    assert r["status"] == "success"
    # SMEMBERS
    r = await tester.redis_post(["SMEMBERS", k])
    assert r["status"] == "success"
    assert isinstance(r["data"], list)


@pytest.mark.asyncio
async def test_sismember_scard(tester):
    """Test SISMEMBER and SCARD operations."""
    k = tester.test_key("set2")
    await tester.redis_post(["SADD", k, "m1", "m2"])
    # SISMEMBER
    r = await tester.redis_post(["SISMEMBER", k, "m1"])
    assert r["status"] == "success"
    # SCARD
    r = await tester.redis_post(["SCARD", k])
    assert r["status"] == "success"
    assert r["data"] == 2


# ========== SORTED SET OPERATIONS ==========

@pytest.mark.asyncio
async def test_zadd_zrange(tester):
    """Test ZADD and ZRANGE operations."""
    k = tester.test_key("zset1")
    # ZADD
    r = await tester.redis_post(["ZADD", k, "1", "m1", "2", "m2"])
    assert r["status"] == "success"
    # ZRANGE
    r = await tester.redis_post(["ZRANGE", k, "0", "-1"])
    assert r["status"] == "success"
    assert isinstance(r["data"], list)


@pytest.mark.asyncio
async def test_zrank_zscore(tester):
    """Test ZRANK and ZSCORE operations."""
    k = tester.test_key("zset2")
    await tester.redis_post(["ZADD", k, "10", "m1", "20", "m2"])
    # ZRANK
    r = await tester.redis_post(["ZRANK", k, "m1"])
    assert r["status"] == "success"
    # ZSCORE
    r = await tester.redis_post(["ZSCORE", k, "m1"])
    assert r["status"] == "success"


# ========== KEY OPERATIONS ==========

@pytest.mark.asyncio
async def test_del_exists(tester):
    """Test DEL and EXISTS operations."""
    k = tester.test_key("key1")
    await tester.redis_post(["SET", k, "value"])
    # EXISTS
    r = await tester.redis_get(f"/exists/{k}")
    assert r["status"] == "success"
    assert r["data"] == 1
    # DEL
    r = await tester.redis_get(f"/del/{k}")
    assert r["status"] == "success"


@pytest.mark.asyncio
async def test_expire_ttl(tester):
    """Test EXPIRE and TTL operations."""
    k = tester.test_key("key2")
    await tester.redis_post(["SET", k, "value"])
    # EXPIRE
    r = await tester.redis_get(f"/expire/{k}/60")
    assert r["status"] == "success"
    # TTL
    r = await tester.redis_get(f"/ttl/{k}")
    assert r["status"] == "success"
    assert r["data"] > 0


@pytest.mark.asyncio
async def test_type(tester):
    """Test TYPE operation."""
    k = tester.test_key("key3")
    await tester.redis_post(["SET", k, "value"])
    r = await tester.redis_get(f"/type/{k}")
    assert r["status"] == "success"
    assert r["data"] == "string"


# ========== SCRIPTING OPERATIONS ==========

@pytest.mark.asyncio
async def test_eval(tester):
    """Test EVAL operation."""
    r = await tester.redis_post(["EVAL", "return 'OK'", "0"])
    assert r["status"] == "success"
    assert r["data"] == "OK"


# ========== PUBSUB OPERATIONS ==========

@pytest.mark.asyncio
async def test_publish(tester):
    """Test PUBLISH operation."""
    r = await tester.redis_post(["PUBLISH", "channel1", "message"])
    assert r["status"] == "success"


# ========== STREAM OPERATIONS ==========

@pytest.mark.asyncio
async def test_xadd_xlen(tester):
    """Test XADD and XLEN operations."""
    k = tester.test_key("stream1")
    # XADD
    r = await tester.redis_post(["XADD", k, "*", "f1", "v1"])
    assert r["status"] == "success"
    # XLEN
    r = await tester.redis_post(["XLEN", k])
    assert r["status"] == "success"
    assert r["data"] >= 1
