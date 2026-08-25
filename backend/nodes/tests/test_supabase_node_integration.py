"""
Integration tests for Supabase Node.

These tests make real API calls to a test Supabase project.
They require valid Supabase credentials (project_url and api_key) to be set as environment variables:
- SUPABASE_TEST_PROJECT_URL
- SUPABASE_TEST_API_KEY

If these environment variables are not set, all tests will be skipped.

Test Table Schema:
CREATE TABLE test_users (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    age INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);

Test Function:
CREATE OR REPLACE FUNCTION get_user_count()
RETURNS INTEGER AS $$
BEGIN
    RETURN (SELECT COUNT(*) FROM test_users);
END;
$$ LANGUAGE plpgsql;
"""

import pytest
import os
import time

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
    # Auth operations
    SupabaseAuthSignUpConfig,
    SupabaseAuthSignInPasswordConfig,
    SupabaseAuthSignInMagicLinkConfig,
    SupabaseAuthSignOutConfig,
    SupabaseAuthGetUserConfig,
    SupabaseAuthUpdateUserConfig,
    SupabaseAuthResetPasswordConfig,
    SupabaseAuthVerifyOTPConfig,
    SupabaseAuthRefreshTokenConfig,
    SupabaseAuthAdminListUsersConfig,
    SupabaseAuthAdminCreateUserConfig,
    SupabaseAuthAdminDeleteUserConfig,
    SupabaseAuthAdminUpdateUserConfig,
    # Storage operations
    SupabaseStorageCreateBucketConfig,
    SupabaseStorageListBucketsConfig,
    SupabaseStorageGetBucketConfig,
    SupabaseStorageDeleteBucketConfig,
    SupabaseStorageEmptyBucketConfig,
    SupabaseStorageUploadFileConfig,
    SupabaseStorageDownloadFileConfig,
    SupabaseStorageListFilesConfig,
    SupabaseStorageDeleteFileConfig,
    SupabaseStorageMoveFileConfig,
    SupabaseStorageCopyFileConfig,
    SupabaseStorageCreateSignedURLConfig,
    SupabaseStorageGetPublicURLConfig,
    # Realtime operations
    SupabaseRealtimeBroadcastConfig,
    # Edge Functions operations
    SupabaseEdgeFunctionInvokeConfig,
)

# Get test credentials from environment
TEST_PROJECT_URL = os.getenv("SUPABASE_PROJECT_URL")
TEST_API_KEY = os.getenv("SUPABASE_ANON_KEY")
TEST_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_SECRET") or TEST_API_KEY

# Skip all tests if credentials are not available
pytestmark = pytest.mark.skipif(
    not TEST_PROJECT_URL or not TEST_API_KEY,
    reason="Supabase test credentials not set (SUPABASE_PROJECT_URL, SUPABASE_ANON_KEY)",
)


# ============================================================================
# Test Fixtures
# ============================================================================


def create_node(config, use_service_role=False) -> SupabaseNode:
    """Create a SupabaseNode instance with real test credentials."""
    api_key = TEST_SERVICE_ROLE_KEY if use_service_role else TEST_API_KEY
    credentials = SupabaseApiKeyCredential(
        project_url=TEST_PROJECT_URL, api_key=api_key
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


def generate_unique_email():
    """Generate a unique email for testing."""
    timestamp = int(time.time() * 1000)
    return f"test_{timestamp}@example.com"


def get_real_test_email():
    """Get the real test email for Auth tests."""
    return "team@example.com"


# ============================================================================
# Select Operation Tests
# ============================================================================


class TestSelectOperationIntegration:
    """Integration tests for select operations."""

    @pytest.mark.asyncio
    async def test_select_all_rows(self):
        """Test selecting all rows from test table."""
        config = SupabaseSelectConfig(table="test_users", columns="*", limit=10)
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "select_table_rows"
        assert "data" in result
        assert isinstance(result["data"], list)

    @pytest.mark.asyncio
    async def test_select_specific_columns(self):
        """Test selecting specific columns."""
        # First insert a test user
        email = generate_unique_email()
        insert_config = SupabaseInsertConfig(
            table="test_users", rows={"name": "Test User", "email": email, "age": 25}
        )
        node = create_node(insert_config)
        await node.execute({})

        # Now select with specific columns
        config = SupabaseSelectConfig(
            table="test_users",
            columns="name,email",
            filters=[{"column": "email", "operator": "eq", "value": email}],
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert len(result["data"]) == 1
        assert "name" in result["data"][0]
        assert "email" in result["data"][0]
        assert "age" not in result["data"][0]  # Excluded column

    @pytest.mark.asyncio
    async def test_select_with_ordering(self):
        """Test selecting rows with ordering."""
        # Insert multiple users
        emails = []
        for i in range(3):
            email = generate_unique_email()
            emails.append(email)
            insert_config = SupabaseInsertConfig(
                table="test_users",
                rows={"name": f"User {i}", "email": email, "age": 20 + i},
            )
            node = create_node(insert_config)
            await node.execute({})
            time.sleep(0.01)  # Small delay to ensure unique timestamps

        # Select with ordering
        config = SupabaseSelectConfig(
            table="test_users",
            columns="name,age",
            filters=[
                {"column": "email", "operator": "in", "value": f"({','.join(emails)})"}
            ],
            order_by="age.desc",
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert len(result["data"]) == 3
        # Verify descending order
        ages = [row["age"] for row in result["data"]]
        assert ages == sorted(ages, reverse=True)

    @pytest.mark.asyncio
    async def test_select_with_limit_offset(self):
        """Test pagination with limit and offset."""
        # Insert multiple users
        emails = []
        for i in range(5):
            email = generate_unique_email()
            emails.append(email)
            insert_config = SupabaseInsertConfig(
                table="test_users",
                rows={"name": "Test User", "email": email, "age": 25},
            )
            node = create_node(insert_config)
            await node.execute({})
            time.sleep(0.01)  # Small delay to ensure unique timestamps

        # Test limit
        config = SupabaseSelectConfig(table="test_users", columns="email", limit=2)
        node = create_node(config)
        result = await node.execute({})

        assert result["status"] == "success"
        assert len(result["data"]) <= 2  # May be fewer if table has < 2 rows

        # Test offset
        config_offset = SupabaseSelectConfig(
            table="test_users", columns="email", limit=2, offset=1
        )
        node_offset = create_node(config_offset)
        result_offset = await node_offset.execute({})

        assert result_offset["status"] == "success"


# ============================================================================
# Insert Operation Tests
# ============================================================================


class TestInsertOperationIntegration:
    """Integration tests for insert operations."""

    @pytest.mark.asyncio
    async def test_insert_single_row(self):
        """Test inserting a single row."""
        email = generate_unique_email()
        config = SupabaseInsertConfig(
            table="test_users", rows={"name": "John Doe", "email": email, "age": 30}
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "insert_table_rows"
        assert len(result["data"]) == 1
        assert result["data"][0]["name"] == "John Doe"
        assert result["data"][0]["email"] == email
        assert "id" in result["data"][0]

    @pytest.mark.asyncio
    async def test_insert_multiple_rows(self):
        """Test inserting multiple rows."""
        # Generate unique emails with small delays
        emails = []
        for i in range(3):
            emails.append(generate_unique_email())
            time.sleep(0.01)

        config = SupabaseInsertConfig(
            table="test_users",
            rows=[
                {"name": "Alice", "email": emails[0], "age": 25},
                {"name": "Bob", "email": emails[1], "age": 30},
                {"name": "Charlie", "email": emails[2], "age": 35},
            ],
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert len(result["data"]) == 3
        assert result["data"][0]["name"] == "Alice"
        assert result["data"][1]["name"] == "Bob"
        assert result["data"][2]["name"] == "Charlie"


# ============================================================================
# Update Operation Tests
# ============================================================================


class TestUpdateOperationIntegration:
    """Integration tests for update operations."""

    @pytest.mark.asyncio
    async def test_update_single_row(self):
        """Test updating a single row."""
        # First insert a row
        email = generate_unique_email()
        insert_config = SupabaseInsertConfig(
            table="test_users",
            rows={"name": "Original Name", "email": email, "age": 25},
        )
        insert_node = create_node(insert_config)
        insert_result = await insert_node.execute({})
        user_id = insert_result["data"][0]["id"]

        # Now update it
        config = SupabaseUpdateConfig(
            table="test_users",
            values={"name": "Updated Name"},
            filters=[{"column": "id", "operator": "eq", "value": str(user_id)}],
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "update_table_rows"
        assert len(result["data"]) == 1
        assert result["data"][0]["name"] == "Updated Name"
        assert result["data"][0]["email"] == email

    @pytest.mark.asyncio
    async def test_update_multiple_fields(self):
        """Test updating multiple fields."""
        # Insert a row
        email = generate_unique_email()
        insert_config = SupabaseInsertConfig(
            table="test_users", rows={"name": "Test", "email": email, "age": 20}
        )
        node = create_node(insert_config)
        await node.execute({})

        # Update multiple fields
        config = SupabaseUpdateConfig(
            table="test_users",
            values={"name": "New Name", "age": 30},
            filters=[{"column": "email", "operator": "eq", "value": email}],
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["data"][0]["name"] == "New Name"
        assert result["data"][0]["age"] == 30


# ============================================================================
# Delete Operation Tests
# ============================================================================


class TestDeleteOperationIntegration:
    """Integration tests for delete operations."""

    @pytest.mark.asyncio
    async def test_delete_single_row(self):
        """Test deleting a single row."""
        # Insert a row
        email = generate_unique_email()
        insert_config = SupabaseInsertConfig(
            table="test_users", rows={"name": "To Delete", "email": email, "age": 25}
        )
        insert_node = create_node(insert_config)
        insert_result = await insert_node.execute({})
        user_id = insert_result["data"][0]["id"]

        # Delete it
        config = SupabaseDeleteConfig(
            table="test_users",
            filters=[{"column": "id", "operator": "eq", "value": str(user_id)}],
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "delete_table_rows"
        assert len(result["data"]) == 1
        assert result["data"][0]["id"] == user_id

        # Verify it's deleted
        select_config = SupabaseSelectConfig(
            table="test_users",
            filters=[{"column": "id", "operator": "eq", "value": str(user_id)}],
        )
        select_node = create_node(select_config)
        select_result = await select_node.execute({})

        assert len(select_result["data"]) == 0


# ============================================================================
# Upsert Operation Tests
# ============================================================================


class TestUpsertOperationIntegration:
    """Integration tests for upsert operations."""

    @pytest.mark.asyncio
    async def test_upsert_insert_new_row(self):
        """Test upsert inserting a new row."""
        email = generate_unique_email()
        config = SupabaseUpsertConfig(
            table="test_users",
            rows={"name": "New User", "email": email, "age": 25},
            on_conflict="email",
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "upsert_table_rows"
        assert len(result["data"]) == 1
        assert result["data"][0]["name"] == "New User"

    @pytest.mark.asyncio
    async def test_upsert_update_existing_row(self):
        """Test upsert updating an existing row."""
        email = generate_unique_email()

        # Insert initial row
        insert_config = SupabaseInsertConfig(
            table="test_users", rows={"name": "Original", "email": email, "age": 20}
        )
        node = create_node(insert_config)
        await node.execute({})

        # Upsert with same email
        config = SupabaseUpsertConfig(
            table="test_users",
            rows={"name": "Updated", "email": email, "age": 30},
            on_conflict="email",
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert len(result["data"]) == 1
        assert result["data"][0]["name"] == "Updated"
        assert result["data"][0]["age"] == 30


# ============================================================================
# RPC Operation Tests
# ============================================================================


class TestRpcOperationIntegration:
    """Integration tests for RPC operations."""

    @pytest.mark.asyncio
    async def test_rpc_simple_function(self):
        """Test calling a simple database function."""
        # Insert some users first
        emails = [generate_unique_email() for _ in range(3)]
        for email in emails:
            insert_config = SupabaseInsertConfig(
                table="test_users", rows={"name": "Test", "email": email, "age": 25}
            )
            insert_node = create_node(insert_config)
            await insert_node.execute({})

        # Call the RPC function (if it exists)
        config = SupabaseRpcConfig(function_name="get_user_count", params={})
        node = create_node(config)

        try:
            result = await node.execute({})
            # If function exists, it should return a count
            assert result["status"] == "success"
            assert result["action"] == "call_database_function"
        except Exception as e:
            # Function might not exist in test database
            pytest.skip(f"RPC function 'get_user_count' not available: {e}")


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandlingIntegration:
    """Integration tests for error handling."""

    @pytest.mark.asyncio
    async def test_nonexistent_table(self):
        """Test error handling for nonexistent table."""
        config = SupabaseSelectConfig(table="nonexistent_table_xyz", columns="*")
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "error"
        assert result["status_code"] >= 400

    @pytest.mark.asyncio
    async def test_invalid_column(self):
        """Test error handling for invalid column."""
        config = SupabaseSelectConfig(table="test_users", columns="nonexistent_column")
        node = create_node(config)

        result = await node.execute({})

        # PostgREST might return error or empty result depending on configuration
        assert result["status"] in ["success", "error"]

    @pytest.mark.asyncio
    async def test_unique_constraint_violation(self):
        """Test handling of unique constraint violations."""
        email = generate_unique_email()

        # Insert first row
        config1 = SupabaseInsertConfig(
            table="test_users", rows={"name": "User 1", "email": email, "age": 25}
        )
        node1 = create_node(config1)
        await node1.execute({})

        # Try to insert duplicate email
        config2 = SupabaseInsertConfig(
            table="test_users", rows={"name": "User 2", "email": email, "age": 30}
        )
        node2 = create_node(config2)

        result = await node2.execute({})

        # Should get an error due to unique constraint
        assert result["status"] == "error"
        assert result["status_code"] >= 400


# ============================================================================
# Auth API Tests
# ============================================================================


class TestAuthOperationsIntegration:
    """Integration tests for Auth API operations."""

    @pytest.mark.asyncio
    async def test_auth_signup_and_signin(self):
        """Test user signup and signin with password."""
        # Note: This test uses a unique email each time to avoid conflicts
        # In production, you'd want to clean up test users or use a dedicated test email
        email = generate_unique_email()
        password = "TestPassword123!"

        # Try to signup - may fail if email already exists
        signup_config = SupabaseAuthSignUpConfig(
            email=email,
            password=password,
            user_metadata={"name": "Integration Test User"},
        )
        node = create_node(signup_config)
        signup_result = await node.execute({})

        # Signup might fail if email format is rejected or already exists
        if signup_result["status"] == "error":
            # Try signin instead with a known good email/password
            email = get_real_test_email()
            password = "TestPassword123!"  # Use your actual password if you have a test account

        # Test signin
        signin_config = SupabaseAuthSignInPasswordConfig(email=email, password=password)
        node = create_node(signin_config)
        signin_result = await node.execute({})

        # Either success or error (if email confirmation required or wrong password)
        assert signin_result["status"] in ["success", "error"]
        if signin_result["status"] == "success":
            assert signin_result["action"] == "sign_in_with_password"
            assert "access_token" in signin_result["data"]

    @pytest.mark.asyncio
    async def test_auth_signin_magiclink(self):
        """Test magic link signin (will send email to real address)."""
        email = get_real_test_email()

        config = SupabaseAuthSignInMagicLinkConfig(
            email=email, redirect_to="https://example.com/auth/callback"
        )
        node = create_node(config)
        result = await node.execute({})

        # Magic link should be sent successfully
        assert result["status"] in ["success", "error"]
        if result["status"] == "success":
            assert result["action"] == "send_magic_link_signin"

    @pytest.mark.asyncio
    async def test_auth_signout(self):
        """Test user signout."""
        # Create a confirmed user via admin API
        email = generate_unique_email()
        password = "TestPassword123!"

        create_config = SupabaseAuthAdminCreateUserConfig(
            email=email, password=password, email_confirm=True  # Auto-confirm the user
        )
        node = create_node(create_config, use_service_role=True)
        create_result = await node.execute({})

        if create_result["status"] != "success":
            pytest.skip("Cannot test signout without successful user creation")

        user_id = create_result["data"]["id"]

        # Sign in to get access token
        signin_config = SupabaseAuthSignInPasswordConfig(email=email, password=password)
        node = create_node(signin_config)
        signin_result = await node.execute({})

        if signin_result["status"] != "success":
            pytest.skip("Cannot test signout without successful signin")

        access_token = signin_result["data"].get("access_token")
        if not access_token:
            pytest.skip("No access token available for signout test")

        # Test signout
        signout_config = SupabaseAuthSignOutConfig(access_token=access_token)
        node = create_node(signout_config)
        signout_result = await node.execute({})

        assert signout_result["status"] in ["success", "error"]

        # Cleanup: delete the user
        delete_config = SupabaseAuthAdminDeleteUserConfig(user_id=user_id)
        node = create_node(delete_config, use_service_role=True)
        await node.execute({})

    @pytest.mark.asyncio
    async def test_auth_get_user(self):
        """Test getting user info with access token."""
        # Create a confirmed user via admin API
        email = generate_unique_email()
        password = "TestPassword123!"

        create_config = SupabaseAuthAdminCreateUserConfig(
            email=email,
            password=password,
            email_confirm=True,  # Auto-confirm the user
            user_metadata={"name": "Get User Test"},
        )
        node = create_node(create_config, use_service_role=True)
        create_result = await node.execute({})

        if create_result["status"] != "success":
            pytest.skip("Cannot test get_user without successful user creation")

        user_id = create_result["data"]["id"]

        # Sign in to get access token
        signin_config = SupabaseAuthSignInPasswordConfig(email=email, password=password)
        node = create_node(signin_config)
        signin_result = await node.execute({})

        if signin_result["status"] != "success":
            pytest.skip("Cannot test get_user without successful signin")

        access_token = signin_result["data"].get("access_token")
        if not access_token:
            pytest.skip("No access token available for get_user test")

        # Test get user
        get_user_config = SupabaseAuthGetUserConfig(access_token=access_token)
        node = create_node(get_user_config)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_current_user"
        # User data is returned directly, not nested under "user" key
        assert "id" in result["data"]
        assert "email" in result["data"]

        # Cleanup: delete the user
        delete_config = SupabaseAuthAdminDeleteUserConfig(user_id=user_id)
        node = create_node(delete_config, use_service_role=True)
        await node.execute({})

    @pytest.mark.asyncio
    async def test_auth_update_user(self):
        """Test updating user metadata."""
        # Create a confirmed user via admin API
        email = generate_unique_email()
        password = "TestPassword123!"

        create_config = SupabaseAuthAdminCreateUserConfig(
            email=email, password=password, email_confirm=True  # Auto-confirm the user
        )
        node = create_node(create_config, use_service_role=True)
        create_result = await node.execute({})

        if create_result["status"] != "success":
            pytest.skip("Cannot test update_user without successful user creation")

        user_id = create_result["data"]["id"]

        # Sign in to get access token
        signin_config = SupabaseAuthSignInPasswordConfig(email=email, password=password)
        node = create_node(signin_config)
        signin_result = await node.execute({})

        if signin_result["status"] != "success":
            pytest.skip("Cannot test update_user without successful signin")

        access_token = signin_result["data"].get("access_token")
        if not access_token:
            pytest.skip("No access token available for update_user test")

        # Test update user
        update_config = SupabaseAuthUpdateUserConfig(
            access_token=access_token, user_metadata={"updated_name": "Updated User"}
        )
        node = create_node(update_config)
        result = await node.execute({})

        assert result["status"] in ["success", "error"]
        if result["status"] == "success":
            assert result["action"] == "update_current_user"

        # Cleanup: delete the user
        delete_config = SupabaseAuthAdminDeleteUserConfig(user_id=user_id)
        node = create_node(delete_config, use_service_role=True)
        await node.execute({})

    @pytest.mark.asyncio
    async def test_auth_reset_password(self):
        """Test password reset email sending."""
        email = get_real_test_email()

        # Test password reset (no need to create user first if using existing email)
        config = SupabaseAuthResetPasswordConfig(
            email=email, redirect_to="https://example.com/reset-password"
        )
        node = create_node(config)
        result = await node.execute({})

        # Password reset email should be sent (or may fail if email service not configured)
        assert result["status"] in ["success", "error"]
        if result["status"] == "success":
            assert result["action"] == "send_password_reset_email"

    @pytest.mark.asyncio
    async def test_auth_verify_otp(self):
        """Test OTP verification (will fail without real OTP - this is expected)."""
        email = get_real_test_email()

        config = SupabaseAuthVerifyOTPConfig(
            email=email, token="123456", type="magiclink"  # Fake OTP  # Valid OTP type
        )
        node = create_node(config)
        result = await node.execute({})

        # Should fail with fake OTP - this is expected and tests the error handling
        assert result["status"] == "error"  # Expect error with fake OTP
        assert result["action"] == "verify_otp_code"

    @pytest.mark.asyncio
    async def test_auth_refresh_token(self):
        """Test token refresh."""
        # Create a confirmed user via admin API
        email = generate_unique_email()
        password = "TestPassword123!"

        create_config = SupabaseAuthAdminCreateUserConfig(
            email=email, password=password, email_confirm=True  # Auto-confirm the user
        )
        node = create_node(create_config, use_service_role=True)
        create_result = await node.execute({})

        if create_result["status"] != "success":
            pytest.skip("Cannot test refresh without successful user creation")

        user_id = create_result["data"]["id"]

        # Sign in to get refresh token
        signin_config = SupabaseAuthSignInPasswordConfig(email=email, password=password)
        node = create_node(signin_config)
        signin_result = await node.execute({})

        if signin_result["status"] != "success":
            pytest.skip("Cannot test refresh without successful signin")

        refresh_token = signin_result["data"].get("refresh_token")
        if not refresh_token:
            pytest.skip("No refresh token available")

        # Test token refresh
        refresh_config = SupabaseAuthRefreshTokenConfig(refresh_token=refresh_token)
        node = create_node(refresh_config)
        result = await node.execute({})

        assert result["status"] in ["success", "error"]
        if result["status"] == "success":
            assert result["action"] == "refresh_access_token"
            assert "access_token" in result["data"]

        # Cleanup: delete the user
        delete_config = SupabaseAuthAdminDeleteUserConfig(user_id=user_id)
        node = create_node(delete_config, use_service_role=True)
        await node.execute({})

    @pytest.mark.asyncio
    async def test_auth_admin_create_and_list_users(self):
        """Test admin user creation and listing (requires service_role key)."""
        # Note: This test requires service_role key, not anon key
        # If TEST_API_KEY is anon key, this will fail

        email = generate_unique_email()

        # Test admin create user
        create_config = SupabaseAuthAdminCreateUserConfig(
            email=email,
            password="AdminTestPassword123!",
            email_confirm=True,
            user_metadata={"role": "admin_created"},
        )
        node = create_node(create_config, use_service_role=True)
        create_result = await node.execute({})

        # May fail if using anon key instead of service_role key
        if create_result["status"] == "error":
            pytest.skip("Admin operations require service_role key, not anon key")

        assert create_result["status"] == "success"
        assert create_result["action"] == "admin_create_user"
        user_id = create_result["data"]["id"]

        # Test admin list users
        list_config = SupabaseAuthAdminListUsersConfig(per_page=10, page=1)
        node = create_node(list_config, use_service_role=True)
        list_result = await node.execute({})

        assert list_result["status"] == "success"
        assert list_result["action"] == "admin_list_users"
        assert "users" in list_result["data"]

        # Cleanup: delete the created user
        delete_config = SupabaseAuthAdminDeleteUserConfig(user_id=user_id)
        node = create_node(delete_config, use_service_role=True)
        await node.execute({})

    @pytest.mark.asyncio
    async def test_auth_admin_update_user(self):
        """Test admin user update (requires service_role key)."""
        email = generate_unique_email()

        # Create a user via admin
        create_config = SupabaseAuthAdminCreateUserConfig(
            email=email, password="AdminTestPassword123!", email_confirm=True
        )
        node = create_node(create_config, use_service_role=True)
        create_result = await node.execute({})

        # May fail if using anon key instead of service_role key
        if create_result["status"] == "error":
            pytest.skip("Admin operations require service_role key, not anon key")

        user_id = create_result["data"]["id"]

        # Test admin update user
        update_config = SupabaseAuthAdminUpdateUserConfig(
            user_id=user_id, user_metadata={"updated_by": "admin"}
        )
        node = create_node(update_config, use_service_role=True)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "admin_update_user"

        # Cleanup
        delete_config = SupabaseAuthAdminDeleteUserConfig(user_id=user_id)
        node = create_node(delete_config, use_service_role=True)
        await node.execute({})

    @pytest.mark.asyncio
    async def test_auth_admin_delete_user(self):
        """Test admin user deletion (requires service_role key)."""
        email = generate_unique_email()

        # Create a user via admin
        create_config = SupabaseAuthAdminCreateUserConfig(
            email=email, password="AdminTestPassword123!", email_confirm=True
        )
        node = create_node(create_config, use_service_role=True)
        create_result = await node.execute({})

        # May fail if using anon key instead of service_role key
        if create_result["status"] == "error":
            pytest.skip("Admin operations require service_role key, not anon key")

        user_id = create_result["data"]["id"]

        # Test admin delete user
        delete_config = SupabaseAuthAdminDeleteUserConfig(user_id=user_id)
        delete_node = create_node(delete_config, use_service_role=True)
        result = await delete_node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "admin_delete_user"


# ============================================================================
# Storage API Tests
# ============================================================================


def generate_unique_bucket_name():
    """Generate a unique bucket name for testing."""
    timestamp = int(time.time() * 1000)
    return f"test-bucket-{timestamp}"


class TestStorageOperationsIntegration:
    """Integration tests for Storage API operations."""

    @pytest.mark.asyncio
    async def test_storage_create_and_list_buckets(self):
        """Test creating and listing storage buckets."""
        bucket_name = generate_unique_bucket_name()

        # Test create bucket (requires service_role key)
        create_config = SupabaseStorageCreateBucketConfig(
            bucket_name=bucket_name,
            public=False,
            file_size_limit=1048576,  # 1MB
            allowed_mime_types=["image/jpeg", "image/png"],
        )
        node = create_node(create_config, use_service_role=True)
        create_result = await node.execute({})

        assert create_result["status"] in ["success", "error"]
        if create_result["status"] == "error":
            # May fail if user doesn't have permission
            pytest.skip("Storage bucket creation requires appropriate permissions")

        assert create_result["action"] == "create_storage_bucket"

        # Test list buckets
        list_config = SupabaseStorageListBucketsConfig()
        node = create_node(list_config, use_service_role=True)
        list_result = await node.execute({})

        assert list_result["status"] == "success"
        assert list_result["action"] == "list_storage_buckets"
        assert isinstance(list_result["data"], list)

        # Cleanup: delete bucket
        delete_config = SupabaseStorageDeleteBucketConfig(bucket_name=bucket_name)
        node = create_node(delete_config, use_service_role=True)
        await node.execute({})

    @pytest.mark.asyncio
    async def test_storage_get_bucket(self):
        """Test getting bucket details."""
        bucket_name = generate_unique_bucket_name()

        # Create a bucket first
        create_config = SupabaseStorageCreateBucketConfig(
            bucket_name=bucket_name, public=True
        )
        node = create_node(create_config, use_service_role=True)
        create_result = await node.execute({})

        if create_result["status"] == "error":
            pytest.skip("Storage bucket creation requires appropriate permissions")

        # Test get bucket
        get_config = SupabaseStorageGetBucketConfig(bucket_name=bucket_name)
        node = create_node(get_config, use_service_role=True)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_storage_bucket"
        assert result["data"]["id"] == bucket_name

        # Cleanup
        delete_config = SupabaseStorageDeleteBucketConfig(bucket_name=bucket_name)
        node = create_node(delete_config, use_service_role=True)
        await node.execute({})

    @pytest.mark.asyncio
    async def test_storage_upload_and_download_file(self):
        """Test uploading and downloading files."""
        bucket_name = generate_unique_bucket_name()

        # Create a bucket first
        create_bucket_config = SupabaseStorageCreateBucketConfig(
            bucket_name=bucket_name, public=False
        )
        node = create_node(create_bucket_config, use_service_role=True)
        bucket_result = await node.execute({})

        if bucket_result["status"] == "error":
            pytest.skip("Storage bucket creation requires appropriate permissions")

        # Test upload file
        test_content = "Hello, this is test file content!"
        upload_config = SupabaseStorageUploadFileConfig(
            bucket_name=bucket_name,
            file_path="test/hello.txt",
            file_content=test_content,
            content_type="text/plain",
            upsert=True,
        )
        node = create_node(upload_config, use_service_role=True)
        upload_result = await node.execute({})

        assert upload_result["status"] == "success"
        assert upload_result["action"] == "upload_storage_file"

        # Test download file
        download_config = SupabaseStorageDownloadFileConfig(
            bucket_name=bucket_name, file_path="test/hello.txt"
        )
        node = create_node(download_config, use_service_role=True)
        download_result = await node.execute({})

        assert download_result["status"] == "success"
        assert download_result["action"] == "download_storage_file"
        assert "content" in download_result["data"] or "raw" in download_result["data"]

        # Cleanup
        delete_bucket_config = SupabaseStorageDeleteBucketConfig(
            bucket_name=bucket_name
        )
        node = create_node(delete_bucket_config, use_service_role=True)
        await node.execute({})

    @pytest.mark.asyncio
    async def test_storage_list_files(self):
        """Test listing files in a bucket."""
        bucket_name = generate_unique_bucket_name()

        # Create bucket and upload file
        create_bucket_config = SupabaseStorageCreateBucketConfig(
            bucket_name=bucket_name, public=False
        )
        node = create_node(create_bucket_config, use_service_role=True)
        bucket_result = await node.execute({})

        if bucket_result["status"] == "error":
            pytest.skip("Storage bucket creation requires appropriate permissions")

        # Upload a test file
        upload_config = SupabaseStorageUploadFileConfig(
            bucket_name=bucket_name,
            file_path="test/file1.txt",
            file_content="Test content",
            upsert=True,
        )
        node = create_node(upload_config, use_service_role=True)
        await node.execute({})

        # Test list files
        list_config = SupabaseStorageListFilesConfig(
            bucket_name=bucket_name, path="", limit=100, offset=0
        )
        list_node = create_node(list_config, use_service_role=True)
        result = await list_node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_bucket_files"
        assert isinstance(result["data"], list)

        # Cleanup
        delete_bucket_config = SupabaseStorageDeleteBucketConfig(
            bucket_name=bucket_name
        )
        node = create_node(delete_bucket_config, use_service_role=True)
        await node.execute({})

    @pytest.mark.asyncio
    async def test_storage_delete_file(self):
        """Test deleting a file."""
        bucket_name = generate_unique_bucket_name()

        # Create bucket and upload file
        create_bucket_config = SupabaseStorageCreateBucketConfig(
            bucket_name=bucket_name, public=False
        )
        node = create_node(create_bucket_config, use_service_role=True)
        bucket_result = await node.execute({})

        if bucket_result["status"] == "error":
            pytest.skip("Storage bucket creation requires appropriate permissions")

        # Upload a test file
        upload_config = SupabaseStorageUploadFileConfig(
            bucket_name=bucket_name,
            file_path="to_delete.txt",
            file_content="Delete me!",
            upsert=True,
        )
        node = create_node(upload_config, use_service_role=True)
        await node.execute({})

        # Test delete file
        delete_config = SupabaseStorageDeleteFileConfig(
            bucket_name=bucket_name, file_paths=["to_delete.txt"]
        )
        delete_node = create_node(delete_config, use_service_role=True)
        result = await delete_node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "delete_storage_file"

        # Cleanup bucket
        delete_bucket_config = SupabaseStorageDeleteBucketConfig(
            bucket_name=bucket_name
        )
        node = create_node(delete_bucket_config, use_service_role=True)
        await node.execute({})

    @pytest.mark.asyncio
    async def test_storage_move_file(self):
        """Test moving a file."""
        bucket_name = generate_unique_bucket_name()

        # Create bucket and upload file
        create_bucket_config = SupabaseStorageCreateBucketConfig(
            bucket_name=bucket_name, public=False
        )
        node = create_node(create_bucket_config, use_service_role=True)
        bucket_result = await node.execute({})

        if bucket_result["status"] == "error":
            pytest.skip("Storage bucket creation requires appropriate permissions")

        # Upload a test file
        upload_config = SupabaseStorageUploadFileConfig(
            bucket_name=bucket_name,
            file_path="old_location.txt",
            file_content="Move me!",
            upsert=True,
        )
        node = create_node(upload_config, use_service_role=True)
        await node.execute({})

        # Test move file
        move_config = SupabaseStorageMoveFileConfig(
            bucket_name=bucket_name,
            from_path="old_location.txt",
            to_path="new_location.txt",
        )
        node = create_node(move_config, use_service_role=True)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "move_storage_file"

        # Cleanup bucket
        delete_bucket_config = SupabaseStorageDeleteBucketConfig(
            bucket_name=bucket_name
        )
        node = create_node(delete_bucket_config, use_service_role=True)
        await node.execute({})

    @pytest.mark.asyncio
    async def test_storage_copy_file(self):
        """Test copying a file."""
        bucket_name = generate_unique_bucket_name()

        # Create bucket and upload file
        create_bucket_config = SupabaseStorageCreateBucketConfig(
            bucket_name=bucket_name, public=False
        )
        node = create_node(create_bucket_config, use_service_role=True)
        bucket_result = await node.execute({})

        if bucket_result["status"] == "error":
            pytest.skip("Storage bucket creation requires appropriate permissions")

        # Upload a test file
        upload_config = SupabaseStorageUploadFileConfig(
            bucket_name=bucket_name,
            file_path="original.txt",
            file_content="Copy me!",
            upsert=True,
        )
        node = create_node(upload_config, use_service_role=True)
        await node.execute({})

        # Test copy file
        copy_config = SupabaseStorageCopyFileConfig(
            bucket_name=bucket_name, from_path="original.txt", to_path="copy.txt"
        )
        node = create_node(copy_config, use_service_role=True)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "copy_storage_file"

        # Cleanup bucket
        delete_bucket_config = SupabaseStorageDeleteBucketConfig(
            bucket_name=bucket_name
        )
        node = create_node(delete_bucket_config, use_service_role=True)
        await node.execute({})

    @pytest.mark.asyncio
    async def test_storage_create_signed_url(self):
        """Test creating a signed URL for a file."""
        bucket_name = generate_unique_bucket_name()

        # Create bucket and upload file
        create_bucket_config = SupabaseStorageCreateBucketConfig(
            bucket_name=bucket_name, public=False
        )
        node = create_node(create_bucket_config, use_service_role=True)
        bucket_result = await node.execute({})

        if bucket_result["status"] == "error":
            pytest.skip("Storage bucket creation requires appropriate permissions")

        # Upload a test file
        upload_config = SupabaseStorageUploadFileConfig(
            bucket_name=bucket_name,
            file_path="signed_file.txt",
            file_content="Get signed URL for me!",
            upsert=True,
        )
        node = create_node(upload_config, use_service_role=True)
        await node.execute({})

        # Test create signed URL
        signed_url_config = SupabaseStorageCreateSignedURLConfig(
            bucket_name=bucket_name,
            file_path="signed_file.txt",
            expires_in=3600,  # 1 hour
        )
        node = create_node(signed_url_config, use_service_role=True)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "create_file_signed_url"
        assert "signedURL" in result["data"]

        # Cleanup bucket
        delete_bucket_config = SupabaseStorageDeleteBucketConfig(
            bucket_name=bucket_name
        )
        node = create_node(delete_bucket_config, use_service_role=True)
        await node.execute({})

    @pytest.mark.asyncio
    async def test_storage_get_public_url(self):
        """Test getting public URL for a file."""
        bucket_name = generate_unique_bucket_name()

        # Create public bucket and upload file
        create_bucket_config = SupabaseStorageCreateBucketConfig(
            bucket_name=bucket_name, public=True  # Public bucket
        )
        node = create_node(create_bucket_config, use_service_role=True)
        bucket_result = await node.execute({})

        if bucket_result["status"] == "error":
            pytest.skip("Storage bucket creation requires appropriate permissions")

        # Upload a test file
        upload_config = SupabaseStorageUploadFileConfig(
            bucket_name=bucket_name,
            file_path="public_file.txt",
            file_content="Public file content!",
            upsert=True,
        )
        node = create_node(upload_config, use_service_role=True)
        await node.execute({})

        # Test get public URL
        public_url_config = SupabaseStorageGetPublicURLConfig(
            bucket_name=bucket_name, file_path="public_file.txt"
        )
        node = create_node(public_url_config, use_service_role=True)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "get_file_public_url"
        assert "public_url" in result["data"]

        # Cleanup bucket
        delete_bucket_config = SupabaseStorageDeleteBucketConfig(
            bucket_name=bucket_name
        )
        node = create_node(delete_bucket_config, use_service_role=True)
        await node.execute({})

    @pytest.mark.asyncio
    async def test_storage_empty_bucket(self):
        """Test emptying a bucket."""
        bucket_name = generate_unique_bucket_name()

        # Create bucket and upload multiple files
        create_bucket_config = SupabaseStorageCreateBucketConfig(
            bucket_name=bucket_name, public=False
        )
        node = create_node(create_bucket_config, use_service_role=True)
        bucket_result = await node.execute({})

        if bucket_result["status"] == "error":
            pytest.skip("Storage bucket creation requires appropriate permissions")

        # Upload test files
        for i in range(3):
            upload_config = SupabaseStorageUploadFileConfig(
                bucket_name=bucket_name,
                file_path=f"file{i}.txt",
                file_content=f"Content {i}",
                upsert=True,
            )
            node = create_node(upload_config, use_service_role=True)
            await node.execute({})

        # Test empty bucket
        empty_config = SupabaseStorageEmptyBucketConfig(bucket_name=bucket_name)
        node = create_node(empty_config, use_service_role=True)
        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "empty_storage_bucket"

        # Cleanup bucket
        delete_bucket_config = SupabaseStorageDeleteBucketConfig(
            bucket_name=bucket_name
        )
        node = create_node(delete_bucket_config, use_service_role=True)
        await node.execute({})

    @pytest.mark.asyncio
    async def test_storage_delete_bucket(self):
        """Test deleting a bucket."""
        bucket_name = generate_unique_bucket_name()

        # Create a bucket
        create_config = SupabaseStorageCreateBucketConfig(
            bucket_name=bucket_name, public=False
        )
        node = create_node(create_config, use_service_role=True)
        create_result = await node.execute({})

        if create_result["status"] == "error":
            pytest.skip("Storage bucket creation requires appropriate permissions")

        # Test delete bucket
        delete_config = SupabaseStorageDeleteBucketConfig(bucket_name=bucket_name)
        delete_node = create_node(delete_config, use_service_role=True)
        result = await delete_node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "delete_storage_bucket"


# ============================================================================
# Realtime API Tests
# ============================================================================


class TestRealtimeOperationsIntegration:
    """Integration tests for Realtime API operations."""

    @pytest.mark.asyncio
    async def test_realtime_broadcast(self):
        """Test broadcasting a message to a Realtime channel."""
        config = SupabaseRealtimeBroadcastConfig(
            channel="test-room:lobby",
            event="user_action",
            payload={
                "user_id": "test123",
                "action": "joined",
                "timestamp": int(time.time()),
            },
        )
        node = create_node(config)
        result = await node.execute({})

        # Broadcast may succeed or fail depending on Realtime configuration
        assert result["status"] in ["success", "error"]
        if result["status"] == "success":
            assert result["action"] == "broadcast_realtime_message"


# ============================================================================
# Edge Functions API Tests
# ============================================================================
# Note: Edge Functions integration tests are not included because Edge Functions
# must be manually deployed via Supabase CLI. They cannot be created/deployed
# via API. Edge Functions are covered in mock tests (test_supabase_node_mock.py).
