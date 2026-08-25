"""
Mock tests for Supabase Node.

Tests all 6 PostgREST operations using mocked responses:
- select: Query rows with filtering, ordering, and pagination
- insert: Insert one or more rows
- update: Update rows matching filters
- delete: Delete rows matching filters
- upsert: Insert or update rows based on conflicts
- rpc: Call database functions

No real API calls are made - all responses are simulated.
This allows tests to run in CI without dependencies and without making real requests.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from nodes.supabase_node import (
    SupabaseNode,
    SupabaseNodeConfig,
    SupabaseSelectConfig,
    SupabaseInsertConfig,
    SupabaseUpdateConfig,
    SupabaseDeleteConfig,
    SupabaseUpsertConfig,
    SupabaseRpcConfig,
    SupabaseApiKeyCredential,
)


# ============================================================================
# Mock Response Factory
# ============================================================================


def mock_httpx_response(status_code=200, json_data=None, text_data=None, headers=None):
    """Create a mock httpx response."""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.text = text_data or ""
    mock_response.headers = headers or {}
    if json_data is not None:
        mock_response.json.return_value = json_data
    else:
        mock_response.json.side_effect = Exception("No JSON")
    mock_response.raise_for_status = MagicMock()
    return mock_response


# ============================================================================
# Test Fixtures
# ============================================================================


def create_node(config, credentials=None) -> SupabaseNode:
    """Create a SupabaseNode instance with the given config."""
    if credentials is None:
        credentials = SupabaseApiKeyCredential(
            project_url="https://test.supabase.co", api_key="test-api-key"
        )

    node_config = SupabaseNodeConfig(config=config, credentials=credentials)
    node = SupabaseNode(
        node_id="test-node",
        node_type="automation-supabase",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow",
    )
    return node


# ============================================================================
# Select Operation Tests
# ============================================================================


class TestSelectOperation:
    """Test select (query) operations."""

    @pytest.mark.asyncio
    async def test_select_all_rows(self):
        """Test selecting all rows from a table."""
        config = SupabaseSelectConfig(table="users", columns="*")
        node = create_node(config)

        mock_data = [
            {"id": 1, "name": "Alice", "email": "alice@example.com"},
            {"id": 2, "name": "Bob", "email": "bob@example.com"},
        ]

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(json_data=mock_data)
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "select_table_rows"
        assert len(result["data"]) == 2
        assert result["data"][0]["name"] == "Alice"

    @pytest.mark.asyncio
    async def test_select_with_filters(self):
        """Test selecting rows with filters."""
        config = SupabaseSelectConfig(
            table="users",
            columns="id,name,email",
            filters=[{"column": "name", "operator": "eq", "value": "Alice"}],
        )
        node = create_node(config)

        mock_data = [{"id": 1, "name": "Alice", "email": "alice@example.com"}]

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(json_data=mock_data)
            result = await node.execute({})

        assert result["status"] == "success"
        assert len(result["data"]) == 1
        assert result["data"][0]["name"] == "Alice"

    @pytest.mark.asyncio
    async def test_select_with_ordering(self):
        """Test selecting rows with ordering."""
        config = SupabaseSelectConfig(
            table="users", columns="*", order_by="created_at.desc", limit=10
        )
        node = create_node(config)

        mock_data = [
            {"id": 3, "name": "Charlie"},
            {"id": 2, "name": "Bob"},
            {"id": 1, "name": "Alice"},
        ]

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(json_data=mock_data)
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["data"][0]["id"] == 3  # Most recent first

    @pytest.mark.asyncio
    async def test_select_single_row(self):
        """Test selecting a single row."""
        config = SupabaseSelectConfig(
            table="users",
            filters=[{"column": "id", "operator": "eq", "value": "1"}],
            single=True,
        )
        node = create_node(config)

        mock_data = {"id": 1, "name": "Alice", "email": "alice@example.com"}

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(json_data=mock_data)
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["data"]["id"] == 1
        assert isinstance(result["data"], dict)  # Single object, not array

    @pytest.mark.asyncio
    async def test_select_with_count(self):
        """Test selecting rows with count."""
        config = SupabaseSelectConfig(table="users", columns="*", count="exact")
        node = create_node(config)

        mock_data = [{"id": 1}, {"id": 2}]
        mock_headers = {"content-range": "0-1/100"}

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(
                json_data=mock_data, headers=mock_headers
            )
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["count"] == 100


# ============================================================================
# Insert Operation Tests
# ============================================================================


class TestInsertOperation:
    """Test insert operations."""

    @pytest.mark.asyncio
    async def test_insert_single_row(self):
        """Test inserting a single row."""
        config = SupabaseInsertConfig(
            table="users", rows={"name": "Alice", "email": "alice@example.com"}
        )
        node = create_node(config)

        mock_data = [{"id": 1, "name": "Alice", "email": "alice@example.com"}]

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(json_data=mock_data)
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "insert_table_rows"
        assert result["data"][0]["name"] == "Alice"

    @pytest.mark.asyncio
    async def test_insert_multiple_rows(self):
        """Test inserting multiple rows."""
        config = SupabaseInsertConfig(
            table="users",
            rows=[
                {"name": "Alice", "email": "alice@example.com"},
                {"name": "Bob", "email": "bob@example.com"},
            ],
        )
        node = create_node(config)

        mock_data = [
            {"id": 1, "name": "Alice", "email": "alice@example.com"},
            {"id": 2, "name": "Bob", "email": "bob@example.com"},
        ]

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(json_data=mock_data)
            result = await node.execute({})

        assert result["status"] == "success"
        assert len(result["data"]) == 2

    @pytest.mark.asyncio
    async def test_insert_with_conflict_resolution(self):
        """Test insert with on_conflict."""
        config = SupabaseInsertConfig(
            table="users",
            rows={"id": 1, "name": "Alice", "email": "alice@example.com"},
            on_conflict="id",
        )
        node = create_node(config)

        mock_data = [{"id": 1, "name": "Alice", "email": "alice@example.com"}]

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(json_data=mock_data)
            result = await node.execute({})

        assert result["status"] == "success"


# ============================================================================
# Update Operation Tests
# ============================================================================


class TestUpdateOperation:
    """Test update operations."""

    @pytest.mark.asyncio
    async def test_update_rows(self):
        """Test updating rows matching filters."""
        config = SupabaseUpdateConfig(
            table="users",
            values={"email": "newemail@example.com"},
            filters=[{"column": "id", "operator": "eq", "value": "1"}],
        )
        node = create_node(config)

        mock_data = [{"id": 1, "name": "Alice", "email": "newemail@example.com"}]

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(json_data=mock_data)
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "update_table_rows"
        assert result["data"][0]["email"] == "newemail@example.com"

    @pytest.mark.asyncio
    async def test_update_multiple_rows(self):
        """Test updating multiple rows."""
        config = SupabaseUpdateConfig(
            table="users",
            values={"status": "active"},
            filters=[{"column": "verified", "operator": "eq", "value": "true"}],
        )
        node = create_node(config)

        mock_data = [{"id": 1, "status": "active"}, {"id": 2, "status": "active"}]

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(json_data=mock_data)
            result = await node.execute({})

        assert result["status"] == "success"
        assert len(result["data"]) == 2


# ============================================================================
# Delete Operation Tests
# ============================================================================


class TestDeleteOperation:
    """Test delete operations."""

    @pytest.mark.asyncio
    async def test_delete_rows(self):
        """Test deleting rows matching filters."""
        config = SupabaseDeleteConfig(
            table="users", filters=[{"column": "id", "operator": "eq", "value": "1"}]
        )
        node = create_node(config)

        mock_data = [{"id": 1, "name": "Alice"}]

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(json_data=mock_data)
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "delete_table_rows"
        assert result["data"][0]["id"] == 1


# ============================================================================
# Upsert Operation Tests
# ============================================================================


class TestUpsertOperation:
    """Test upsert operations."""

    @pytest.mark.asyncio
    async def test_upsert_single_row(self):
        """Test upserting a single row."""
        config = SupabaseUpsertConfig(
            table="users", rows={"id": 1, "name": "Alice", "email": "alice@example.com"}
        )
        node = create_node(config)

        mock_data = [{"id": 1, "name": "Alice", "email": "alice@example.com"}]

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(json_data=mock_data)
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "upsert_table_rows"

    @pytest.mark.asyncio
    async def test_upsert_with_on_conflict(self):
        """Test upsert with specific conflict column."""
        config = SupabaseUpsertConfig(
            table="users",
            rows={"email": "alice@example.com", "name": "Alice Updated"},
            on_conflict="email",
        )
        node = create_node(config)

        mock_data = [{"id": 1, "name": "Alice Updated", "email": "alice@example.com"}]

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(json_data=mock_data)
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["data"][0]["name"] == "Alice Updated"


# ============================================================================
# RPC Operation Tests
# ============================================================================


class TestRpcOperation:
    """Test RPC (remote procedure call) operations."""

    @pytest.mark.asyncio
    async def test_rpc_call(self):
        """Test calling a database function."""
        config = SupabaseRpcConfig(function_name="get_user_count", params={})
        node = create_node(config)

        mock_data = [{"count": 100}]

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(json_data=mock_data)
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "call_database_function"
        assert result["data"][0]["count"] == 100

    @pytest.mark.asyncio
    async def test_rpc_with_params(self):
        """Test calling a function with parameters."""
        config = SupabaseRpcConfig(
            function_name="get_user_by_email",
            params={"email_param": "alice@example.com"},
        )
        node = create_node(config)

        mock_data = [{"id": 1, "name": "Alice", "email": "alice@example.com"}]

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(json_data=mock_data)
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["data"][0]["email"] == "alice@example.com"

    @pytest.mark.asyncio
    async def test_rpc_single_row(self):
        """Test RPC returning a single row."""
        config = SupabaseRpcConfig(function_name="get_current_user", single=True)
        node = create_node(config)

        mock_data = {"id": 1, "name": "Alice"}

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(json_data=mock_data)
            result = await node.execute({})

        assert result["status"] == "success"
        assert isinstance(result["data"], dict)


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Test error handling for various failure scenarios."""

    @pytest.mark.asyncio
    async def test_api_error_response(self):
        """Test handling of API error responses."""
        config = SupabaseSelectConfig(table="nonexistent", columns="*")
        node = create_node(config)

        error_response = {
            "message": 'relation "public.nonexistent" does not exist',
            "hint": "Check the table name",
        }

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(
                status_code=404, json_data=error_response
            )
            result = await node.execute({})

        assert result["status"] == "error"
        assert "does not exist" in result["error"]
        assert result["status_code"] == 404

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        """Test error when credentials are missing."""
        config = SupabaseSelectConfig(table="users", columns="*")
        node_config = SupabaseNodeConfig(config=config, credentials=None)
        node = SupabaseNode(
            node_id="test-node",
            node_type="automation-supabase",
            node_data={},
            config=node_config,
            sio=None,
            sid=None,
            workflow_id="test-workflow",
        )

        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})

    @pytest.mark.asyncio
    async def test_timeout_error(self):
        """Test handling of timeout errors."""
        config = SupabaseSelectConfig(table="users", columns="*")
        node = create_node(config)

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            import httpx

            mock_request.side_effect = httpx.TimeoutException("Request timed out")
            result = await node.execute({})

        assert result["status"] == "error"
        assert "timed out" in result["error"].lower()
        assert result["status_code"] == 408

    @pytest.mark.asyncio
    async def test_invalid_filter_operator(self):
        """Test handling of invalid filter operators."""
        config = SupabaseSelectConfig(
            table="users",
            filters=[{"column": "id", "operator": "invalid_op", "value": "1"}],
        )
        node = create_node(config)

        mock_data = []

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(json_data=mock_data)
            result = await node.execute({})

        # Should default to 'eq' operator and succeed
        assert result["status"] == "success"


# ============================================================================
# Auth API Tests
# ============================================================================


class TestAuthOperations:
    """Test Auth API operations."""

    @pytest.mark.asyncio
    async def test_auth_signup(self):
        """Test user signup."""
        from nodes.supabase_node import SupabaseAuthSignUpConfig

        config = SupabaseAuthSignUpConfig(
            email="test@example.com", password="password123"
        )
        node = create_node(config)

        mock_data = {
            "user": {"id": "user-123", "email": "test@example.com"},
            "session": {"access_token": "token-abc"},
        }

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(json_data=mock_data)
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "sign_up_user"
        assert "user" in result["data"]

    @pytest.mark.asyncio
    async def test_auth_signin_password(self):
        """Test signin with password."""
        from nodes.supabase_node import SupabaseAuthSignInPasswordConfig

        config = SupabaseAuthSignInPasswordConfig(
            email="test@example.com", password="password123"
        )
        node = create_node(config)

        mock_data = {
            "access_token": "token-abc",
            "refresh_token": "refresh-xyz",
            "user": {"id": "user-123", "email": "test@example.com"},
        }

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(json_data=mock_data)
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "sign_in_with_password"
        assert "access_token" in result["data"]

    @pytest.mark.asyncio
    async def test_auth_signin_magiclink(self):
        """Test magic link signin."""
        from nodes.supabase_node import SupabaseAuthSignInMagicLinkConfig

        config = SupabaseAuthSignInMagicLinkConfig(email="test@example.com")
        node = create_node(config)

        mock_data = {"success": True}

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(json_data=mock_data)
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "send_magic_link_signin"

    @pytest.mark.asyncio
    async def test_auth_signout(self):
        """Test user signout."""
        from nodes.supabase_node import SupabaseAuthSignOutConfig

        config = SupabaseAuthSignOutConfig(access_token="token-abc")
        node = create_node(config)

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(status_code=204)
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "sign_out_user"

    @pytest.mark.asyncio
    async def test_auth_get_user(self):
        """Test getting user details."""
        from nodes.supabase_node import SupabaseAuthGetUserConfig

        config = SupabaseAuthGetUserConfig(access_token="token-abc")
        node = create_node(config)

        mock_data = {
            "id": "user-123",
            "email": "test@example.com",
            "user_metadata": {"name": "Test User"},
        }

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(json_data=mock_data)
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["data"]["email"] == "test@example.com"

    @pytest.mark.asyncio
    async def test_auth_update_user(self):
        """Test updating user."""
        from nodes.supabase_node import SupabaseAuthUpdateUserConfig

        config = SupabaseAuthUpdateUserConfig(
            access_token="token-abc", user_metadata={"name": "Updated Name"}
        )
        node = create_node(config)

        mock_data = {
            "id": "user-123",
            "email": "test@example.com",
            "user_metadata": {"name": "Updated Name"},
        }

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(json_data=mock_data)
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["data"]["user_metadata"]["name"] == "Updated Name"

    @pytest.mark.asyncio
    async def test_auth_reset_password(self):
        """Test password reset."""
        from nodes.supabase_node import SupabaseAuthResetPasswordConfig

        config = SupabaseAuthResetPasswordConfig(email="test@example.com")
        node = create_node(config)

        mock_data = {"success": True}

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(json_data=mock_data)
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "send_password_reset_email"

    @pytest.mark.asyncio
    async def test_auth_verify_otp(self):
        """Test OTP verification."""
        from nodes.supabase_node import SupabaseAuthVerifyOTPConfig

        config = SupabaseAuthVerifyOTPConfig(
            email="test@example.com", token="123456", type="magiclink"
        )
        node = create_node(config)

        mock_data = {
            "access_token": "token-abc",
            "user": {"id": "user-123", "email": "test@example.com"},
        }

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(json_data=mock_data)
            result = await node.execute({})

        assert result["status"] == "success"
        assert "access_token" in result["data"]

    @pytest.mark.asyncio
    async def test_auth_refresh_token(self):
        """Test token refresh."""
        from nodes.supabase_node import SupabaseAuthRefreshTokenConfig

        config = SupabaseAuthRefreshTokenConfig(refresh_token="refresh-xyz")
        node = create_node(config)

        mock_data = {
            "access_token": "new-token-abc",
            "refresh_token": "new-refresh-xyz",
        }

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(json_data=mock_data)
            result = await node.execute({})

        assert result["status"] == "success"
        assert "access_token" in result["data"]

    @pytest.mark.asyncio
    async def test_auth_admin_list_users(self):
        """Test admin list users."""
        from nodes.supabase_node import SupabaseAuthAdminListUsersConfig

        config = SupabaseAuthAdminListUsersConfig(page=1, per_page=50)
        node = create_node(config)

        mock_data = {
            "users": [
                {"id": "user-1", "email": "user1@example.com"},
                {"id": "user-2", "email": "user2@example.com"},
            ]
        }

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(json_data=mock_data)
            result = await node.execute({})

        assert result["status"] == "success"
        assert "users" in result["data"]

    @pytest.mark.asyncio
    async def test_auth_admin_create_user(self):
        """Test admin create user."""
        from nodes.supabase_node import SupabaseAuthAdminCreateUserConfig

        config = SupabaseAuthAdminCreateUserConfig(
            email="newuser@example.com", password="password123", email_confirm=True
        )
        node = create_node(config)

        mock_data = {"id": "user-123", "email": "newuser@example.com"}

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(json_data=mock_data)
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["data"]["email"] == "newuser@example.com"

    @pytest.mark.asyncio
    async def test_auth_admin_delete_user(self):
        """Test admin delete user."""
        from nodes.supabase_node import SupabaseAuthAdminDeleteUserConfig

        config = SupabaseAuthAdminDeleteUserConfig(user_id="user-123")
        node = create_node(config)

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(status_code=204)
            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_auth_admin_update_user(self):
        """Test admin update user."""
        from nodes.supabase_node import SupabaseAuthAdminUpdateUserConfig

        config = SupabaseAuthAdminUpdateUserConfig(
            user_id="user-123", email_confirm=True, user_metadata={"role": "admin"}
        )
        node = create_node(config)

        mock_data = {
            "id": "user-123",
            "email": "user@example.com",
            "user_metadata": {"role": "admin"},
        }

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(json_data=mock_data)
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["data"]["user_metadata"]["role"] == "admin"


# ============================================================================
# Storage API Tests
# ============================================================================


class TestStorageOperations:
    """Test Storage API operations."""

    @pytest.mark.asyncio
    async def test_storage_create_bucket(self):
        """Test creating a storage bucket."""
        from nodes.supabase_node import SupabaseStorageCreateBucketConfig

        config = SupabaseStorageCreateBucketConfig(
            bucket_name="test-bucket", public=True
        )
        node = create_node(config)

        mock_data = {"id": "test-bucket", "name": "test-bucket", "public": True}

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(json_data=mock_data)
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "create_storage_bucket"

    @pytest.mark.asyncio
    async def test_storage_list_buckets(self):
        """Test listing storage buckets."""
        from nodes.supabase_node import SupabaseStorageListBucketsConfig

        config = SupabaseStorageListBucketsConfig()
        node = create_node(config)

        mock_data = [
            {"id": "bucket-1", "name": "bucket-1", "public": True},
            {"id": "bucket-2", "name": "bucket-2", "public": False},
        ]

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(json_data=mock_data)
            result = await node.execute({})

        assert result["status"] == "success"
        assert len(result["data"]) == 2

    @pytest.mark.asyncio
    async def test_storage_get_bucket(self):
        """Test getting bucket details."""
        from nodes.supabase_node import SupabaseStorageGetBucketConfig

        config = SupabaseStorageGetBucketConfig(bucket_name="test-bucket")
        node = create_node(config)

        mock_data = {"id": "test-bucket", "name": "test-bucket", "public": True}

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(json_data=mock_data)
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["data"]["name"] == "test-bucket"

    @pytest.mark.asyncio
    async def test_storage_delete_bucket(self):
        """Test deleting a bucket."""
        from nodes.supabase_node import SupabaseStorageDeleteBucketConfig

        config = SupabaseStorageDeleteBucketConfig(bucket_name="test-bucket")
        node = create_node(config)

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(status_code=204)
            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_storage_empty_bucket(self):
        """Test emptying a bucket."""
        from nodes.supabase_node import SupabaseStorageEmptyBucketConfig

        config = SupabaseStorageEmptyBucketConfig(bucket_name="test-bucket")
        node = create_node(config)

        mock_data = {"message": "Successfully emptied"}

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(json_data=mock_data)
            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_storage_upload_file(self):
        """Test uploading a file."""
        from nodes.supabase_node import SupabaseStorageUploadFileConfig
        import base64

        file_content = base64.b64encode(b"test file content").decode("utf-8")

        config = SupabaseStorageUploadFileConfig(
            bucket_name="test-bucket",
            file_path="test.txt",
            file_content=file_content,
            content_type="text/plain",
        )
        node = create_node(config)

        mock_data = {"Key": "test.txt", "Id": "file-123"}

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(json_data=mock_data)
            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_storage_download_file(self):
        """Test downloading a file resolves the binary body to a file reference."""
        from nodes.supabase_node import SupabaseStorageDownloadFileConfig
        from nodes.core.binary_output import BinaryOutput

        # file_path containing "download" so the binary branch of
        # _make_storage_request fires (endpoint gate is "download" in endpoint)
        config = SupabaseStorageDownloadFileConfig(
            bucket_name="test-bucket", file_path="exports/download/report.pdf"
        )
        node = create_node(config)

        # Mock download response - storage handler emits a BinaryOutput marker
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"test file content"
        mock_response.headers = {"content-type": "application/pdf"}
        mock_response.text = "raw text"

        # Make json() raise exception to trigger download path
        def raise_json_error():
            raise ValueError("Not JSON")

        mock_response.json = raise_json_error

        # execute() returns the raw BinaryOutput marker (pre-resolution)
        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            result = await node.execute({})

        assert result["status"] == "success"
        marker = result["data"]["content"]
        assert isinstance(marker, BinaryOutput)
        assert marker.data == b"test file content"
        assert marker.content_type == "application/pdf"
        assert marker.filename == "report.pdf"

        # run() resolves the marker into a {url, ...} file reference via R2
        node.user_id = "test-user"
        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            with patch(
                "nodes.core.binary_output.create_resource_from_bytes",
                new_callable=AsyncMock,
            ) as mock_store:
                mock_store.return_value = {
                    "download_url": "https://r2.example/test-user/report.pdf",
                    "mime_type": "application/pdf",
                    "name": "report.pdf",
                    "size_bytes": len(b"test file content"),
                }
                resolved = await node.run({})

        ref = resolved["data"]["content"]
        assert ref["url"] == "https://r2.example/test-user/report.pdf"
        assert ref["mime_type"] == "application/pdf"
        assert ref["name"] == "report.pdf"
        assert ref["size_bytes"] == len(b"test file content")
        assert "base64" not in ref
        mock_store.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_storage_list_files(self):
        """Test listing files in a bucket."""
        from nodes.supabase_node import SupabaseStorageListFilesConfig

        config = SupabaseStorageListFilesConfig(
            bucket_name="test-bucket", folder_path="", limit=100
        )
        node = create_node(config)

        mock_data = [
            {"name": "file1.txt", "id": "file-1"},
            {"name": "file2.txt", "id": "file-2"},
        ]

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(json_data=mock_data)
            result = await node.execute({})

        assert result["status"] == "success"
        assert len(result["data"]) == 2

    @pytest.mark.asyncio
    async def test_storage_delete_file(self):
        """Test deleting a file."""
        from nodes.supabase_node import SupabaseStorageDeleteFileConfig

        config = SupabaseStorageDeleteFileConfig(
            bucket_name="test-bucket", file_paths="test.txt"
        )
        node = create_node(config)

        mock_data = [{"name": "test.txt"}]

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(json_data=mock_data)
            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_storage_move_file(self):
        """Test moving a file."""
        from nodes.supabase_node import SupabaseStorageMoveFileConfig

        config = SupabaseStorageMoveFileConfig(
            bucket_name="test-bucket", from_path="old.txt", to_path="new.txt"
        )
        node = create_node(config)

        mock_data = {"message": "Successfully moved"}

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(json_data=mock_data)
            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_storage_copy_file(self):
        """Test copying a file."""
        from nodes.supabase_node import SupabaseStorageCopyFileConfig

        config = SupabaseStorageCopyFileConfig(
            bucket_name="test-bucket", from_path="source.txt", to_path="copy.txt"
        )
        node = create_node(config)

        mock_data = {"message": "Successfully copied"}

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(json_data=mock_data)
            result = await node.execute({})

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_storage_create_signed_url(self):
        """Test creating a signed URL."""
        from nodes.supabase_node import SupabaseStorageCreateSignedURLConfig

        config = SupabaseStorageCreateSignedURLConfig(
            bucket_name="test-bucket", file_path="test.txt", expires_in=3600
        )
        node = create_node(config)

        mock_data = {"signedURL": "https://example.com/signed-url?token=abc123"}

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(json_data=mock_data)
            result = await node.execute({})

        assert result["status"] == "success"
        assert "signedURL" in result["data"]

    @pytest.mark.asyncio
    async def test_storage_get_public_url(self):
        """Test getting public URL (no API call)."""
        from nodes.supabase_node import SupabaseStorageGetPublicURLConfig

        config = SupabaseStorageGetPublicURLConfig(
            bucket_name="test-bucket", file_path="test.txt"
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert "public_url" in result["data"]
        assert "test-bucket" in result["data"]["public_url"]
        assert "test.txt" in result["data"]["public_url"]


# ============================================================================
# Realtime API Tests
# ============================================================================


class TestRealtimeOperations:
    """Test Realtime API operations."""

    @pytest.mark.asyncio
    async def test_realtime_broadcast(self):
        """Test broadcasting a message to a Realtime channel."""
        from nodes.supabase_node import SupabaseRealtimeBroadcastConfig

        config = SupabaseRealtimeBroadcastConfig(
            channel="room:lobby",
            event="user_joined",
            payload={"user_id": "123", "username": "test_user"},
        )
        node = create_node(config)

        mock_data = {"success": True}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_httpx_response(json_data=mock_data)
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "broadcast_realtime_message"


# ============================================================================
# Edge Functions API Tests
# ============================================================================


class TestEdgeFunctionsOperations:
    """Test Edge Functions API operations."""

    @pytest.mark.asyncio
    async def test_edge_function_invoke_post(self):
        """Test invoking an edge function with POST."""
        from nodes.supabase_node import SupabaseEdgeFunctionInvokeConfig

        config = SupabaseEdgeFunctionInvokeConfig(
            function_name="hello-world", method="POST", body={"name": "Test"}
        )
        node = create_node(config)

        mock_data = {"message": "Hello Test!"}

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(json_data=mock_data)
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "invoke_edge_function"
        assert result["data"]["message"] == "Hello Test!"

    @pytest.mark.asyncio
    async def test_edge_function_invoke_get(self):
        """Test invoking an edge function with GET."""
        from nodes.supabase_node import SupabaseEdgeFunctionInvokeConfig

        config = SupabaseEdgeFunctionInvokeConfig(
            function_name="get-data", method="GET"
        )
        node = create_node(config)

        mock_data = {"data": [1, 2, 3]}

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(json_data=mock_data)
            result = await node.execute({})

        assert result["status"] == "success"
        assert "data" in result["data"]

    @pytest.mark.asyncio
    async def test_edge_function_invoke_with_headers(self):
        """Test invoking an edge function with custom headers."""
        from nodes.supabase_node import SupabaseEdgeFunctionInvokeConfig

        config = SupabaseEdgeFunctionInvokeConfig(
            function_name="custom-function",
            method="POST",
            body={"test": "data"},
            headers={"X-Custom-Header": "custom-value"},
        )
        node = create_node(config)

        mock_data = {"result": "success"}

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_httpx_response(json_data=mock_data)
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["data"]["result"] == "success"
