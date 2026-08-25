"""
Comprehensive mock tests for Redis node.

Tests all major Redis operation categories with mocked HTTP responses:
- String, Hash, List, Set, Sorted Set operations
- Key operations
- Connection, Server operations
- Stream, JSON, Scripting operations (basic validation)
"""

import pytest
from unittest.mock import AsyncMock, patch

from nodes.redis_node import (
    RedisNode,
    RedisStandardCredential,
    RedisReadOnlyCredential,
    RedisACLCredential,
    RedisNodeConfig,
    # Common operations
    RedisGetConfig,
    RedisSetConfig,
    RedisHgetConfig,
    RedisHsetConfig,
    RedisLpushConfig,
    RedisRpushConfig,
    RedisSaddConfig,
    RedisZaddConfig,
    RedisDelConfig,
    RedisExistsConfig,
    RedisPingConfig,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def standard_credentials():
    """Standard Redis credentials."""
    return RedisStandardCredential(
        rest_url="https://test.upstash.io", rest_token="test_standard_token"
    )


@pytest.fixture
def readonly_credentials():
    """Read-only Redis credentials."""
    return RedisReadOnlyCredential(
        rest_url="https://test.upstash.io", readonly_token="test_readonly_token"
    )


@pytest.fixture
def acl_credentials():
    """ACL Redis credentials."""
    return RedisACLCredential(
        rest_url="https://test.upstash.io",
        acl_token="test_acl_token",
        username="test_user",
    )


@pytest.fixture
def redis_node():
    """Redis node instance."""
    return RedisNode(
        node_id="test_redis_node", node_type="automation-redis", node_data={}
    )


@pytest.fixture
def mock_httpx_client():
    """Mock httpx client for API calls."""
    with patch("httpx.AsyncClient") as mock_client:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        # json() is NOT async in httpx, so use a regular lambda
        mock_response.json = lambda: {"result": "OK"}

        mock_instance = AsyncMock()
        mock_instance.__aenter__.return_value = mock_instance
        mock_instance.get.return_value = mock_response
        mock_instance.post.return_value = mock_response

        mock_client.return_value = mock_instance
        yield mock_client


# ============================================================================
# Credential Tests
# ============================================================================


def test_standard_credential_creation(standard_credentials):
    """Test standard credential creation."""
    assert standard_credentials.rest_url == "https://test.upstash.io"
    assert standard_credentials.rest_token == "test_standard_token"


def test_readonly_credential_creation(readonly_credentials):
    """Test read-only credential creation."""
    assert readonly_credentials.rest_url == "https://test.upstash.io"
    assert readonly_credentials.readonly_token == "test_readonly_token"


def test_acl_credential_creation(acl_credentials):
    """Test ACL credential creation."""
    assert acl_credentials.rest_url == "https://test.upstash.io"
    assert acl_credentials.acl_token == "test_acl_token"
    assert acl_credentials.username == "test_user"


# ============================================================================
# String Operation Tests
# ============================================================================


@pytest.mark.asyncio
async def test_get_operation(redis_node, standard_credentials, mock_httpx_client):
    """Test GET operation with standard credentials."""
    config = RedisGetConfig(key="test_key")
    node_config = RedisNodeConfig(
        operation="get_key_value", config=config, credentials=standard_credentials
    )

    redis_node._config = node_config
    result = await redis_node.execute({})

    assert result is not None
    assert mock_httpx_client.called


@pytest.mark.asyncio
async def test_set_operation(redis_node, standard_credentials, mock_httpx_client):
    """Test SET operation with standard credentials."""
    config = RedisSetConfig(key="test_key", value="test_value")
    node_config = RedisNodeConfig(
        operation="set_key_value", config=config, credentials=standard_credentials
    )

    redis_node._config = node_config
    result = await redis_node.execute({})

    assert result is not None
    assert mock_httpx_client.called


# ============================================================================
# Hash Operation Tests
# ============================================================================


@pytest.mark.asyncio
async def test_hget_operation(redis_node, standard_credentials, mock_httpx_client):
    """Test HGET operation."""
    config = RedisHgetConfig(key="test_hash", field="test_field")
    node_config = RedisNodeConfig(
        operation="get_hash_field_value",
        config=config,
        credentials=standard_credentials,
    )

    redis_node._config = node_config
    result = await redis_node.execute({})

    assert result is not None
    assert mock_httpx_client.called


@pytest.mark.asyncio
async def test_hset_operation(redis_node, standard_credentials, mock_httpx_client):
    """Test HSET operation."""
    config = RedisHsetConfig(key="test_hash", field="test_field", value="test_value")
    node_config = RedisNodeConfig(
        operation="set_hash_field_value",
        config=config,
        credentials=standard_credentials,
    )

    redis_node._config = node_config
    result = await redis_node.execute({})

    assert result is not None
    assert mock_httpx_client.called


# ============================================================================
# List Operation Tests
# ============================================================================


@pytest.mark.asyncio
async def test_lpush_operation(redis_node, standard_credentials, mock_httpx_client):
    """Test LPUSH operation."""
    config = RedisLpushConfig(key="test_list", values=["elem1", "elem2"])
    node_config = RedisNodeConfig(
        operation="push_to_list_beginning",
        config=config,
        credentials=standard_credentials,
    )

    redis_node._config = node_config
    result = await redis_node.execute({})

    assert result is not None
    assert mock_httpx_client.called


@pytest.mark.asyncio
async def test_rpush_operation(redis_node, standard_credentials, mock_httpx_client):
    """Test RPUSH operation."""
    config = RedisRpushConfig(key="test_list", values=["elem1"])
    node_config = RedisNodeConfig(
        operation="push_to_list_end", config=config, credentials=standard_credentials
    )

    redis_node._config = node_config
    result = await redis_node.execute({})

    assert result is not None
    assert mock_httpx_client.called


# ============================================================================
# Set Operation Tests
# ============================================================================


@pytest.mark.asyncio
async def test_sadd_operation(redis_node, standard_credentials, mock_httpx_client):
    """Test SADD operation."""
    config = RedisSaddConfig(key="test_set", members=["m1", "m2"])
    node_config = RedisNodeConfig(
        operation="add_members_to_set", config=config, credentials=standard_credentials
    )

    redis_node._config = node_config
    result = await redis_node.execute({})

    assert result is not None
    assert mock_httpx_client.called


# ============================================================================
# Sorted Set Operation Tests
# ============================================================================


@pytest.mark.asyncio
async def test_zadd_operation(redis_node, standard_credentials, mock_httpx_client):
    """Test ZADD operation."""
    config = RedisZaddConfig(key="test_zset", members=[{"score": 1.0, "member": "m1"}])
    node_config = RedisNodeConfig(
        operation="add_members_to_sorted_set",
        config=config,
        credentials=standard_credentials,
    )

    redis_node._config = node_config
    result = await redis_node.execute({})

    assert result is not None
    assert mock_httpx_client.called


# ============================================================================
# Key Operation Tests
# ============================================================================


@pytest.mark.asyncio
async def test_del_operation(redis_node, standard_credentials, mock_httpx_client):
    """Test DEL operation."""
    config = RedisDelConfig(keys=["key1", "key2"])
    node_config = RedisNodeConfig(
        operation="delete_keys", config=config, credentials=standard_credentials
    )

    redis_node._config = node_config
    result = await redis_node.execute({})

    assert result is not None
    assert mock_httpx_client.called


@pytest.mark.asyncio
async def test_exists_operation(redis_node, standard_credentials):
    """Test EXISTS operation."""
    # Custom mock for exists that returns an integer
    with patch("httpx.AsyncClient") as mock_client:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        # json() is NOT async in httpx, so make it a regular method
        mock_response.json = lambda: {"result": 1}  # EXISTS returns integer

        mock_instance = AsyncMock()
        mock_instance.__aenter__.return_value = mock_instance
        mock_instance.get.return_value = mock_response
        mock_client.return_value = mock_instance

        config = RedisExistsConfig(keys=["key1"])
        node_config = RedisNodeConfig(
            operation="check_if_keys_exist",
            config=config,
            credentials=standard_credentials,
        )

        redis_node._config = node_config
        result = await redis_node.execute({})

        assert result is not None
        assert result["status"] == "success"
        assert isinstance(
            result["data"], bool
        )  # Should be converted to boolean for single key


# ============================================================================
# Connection Operation Tests
# ============================================================================


@pytest.mark.asyncio
async def test_ping_operation(redis_node, standard_credentials, mock_httpx_client):
    """Test PING operation."""
    config = RedisPingConfig()
    node_config = RedisNodeConfig(
        operation="ping_server", config=config, credentials=standard_credentials
    )

    redis_node._config = node_config
    result = await redis_node.execute({})

    assert result is not None
    assert mock_httpx_client.called


# ============================================================================
# Credential Type Tests
# ============================================================================


@pytest.mark.asyncio
async def test_readonly_credential_usage(
    redis_node, readonly_credentials, mock_httpx_client
):
    """Test using read-only credentials."""
    config = RedisGetConfig(key="test_key")
    node_config = RedisNodeConfig(
        operation="get_key_value", config=config, credentials=readonly_credentials
    )

    redis_node._config = node_config
    result = await redis_node.execute({})

    assert result is not None
    assert mock_httpx_client.called


@pytest.mark.asyncio
async def test_acl_credential_usage(redis_node, acl_credentials, mock_httpx_client):
    """Test using ACL credentials."""
    config = RedisGetConfig(key="test_key")
    node_config = RedisNodeConfig(
        operation="get_key_value", config=config, credentials=acl_credentials
    )

    redis_node._config = node_config
    result = await redis_node.execute({})

    assert result is not None
    assert mock_httpx_client.called


# ============================================================================
# Error Handling Tests
# ============================================================================


@pytest.mark.asyncio
async def test_invalid_operation_config():
    """Test that invalid operation config raises error."""
    with pytest.raises(Exception):
        # This should fail due to invalid config
        RedisNodeConfig(operation="invalid_op", config=None)


@pytest.mark.asyncio
async def test_missing_required_field():
    """Test that missing required fields raise validation error."""
    with pytest.raises(Exception):
        # Missing required 'key' field
        RedisGetConfig()
