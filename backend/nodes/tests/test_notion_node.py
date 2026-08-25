"""
Integration tests for Notion API node.

Tests the complete Notion API node functionality including all 19 operations
organized by category: search, databases, pages, blocks, users, and comments.

Uses a real Notion Integration Token or OAuth token to test against the Notion API.
Tests are designed to be non-destructive where possible (read operations).
Write operations test the action name is correct but may fail due to permission constraints.
"""

import asyncio
import os
import time
import pytest

# Import the node and config classes - ALL 19 operations
from nodes.notion_node import (
    NotionNode,
    NotionNodeConfig,
    NotionIntegrationTokenCredential,
    NotionOAuthCredential,
    # Search operation (1)
    NotionSearchConfig,
    # Database operations (4)
    NotionQueryDatabaseConfig,
    NotionRetrieveDatabaseConfig,
    NotionCreateDatabaseConfig,
    NotionUpdateDatabaseConfig,
    # Page operations (3)
    NotionRetrievePageConfig,
    NotionCreatePageConfig,
    NotionUpdatePageConfig,
    # Block operations (5)
    NotionRetrieveBlockConfig,
    NotionRetrieveBlockChildrenConfig,
    NotionAppendBlockChildrenConfig,
    NotionUpdateBlockConfig,
    NotionDeleteBlockConfig,
    # User operations (3)
    NotionListUsersConfig,
    NotionRetrieveUserConfig,
    NotionRetrieveBotUserConfig,
    # Comment operations (3)
    NotionCreateCommentConfig,
    NotionRetrieveCommentConfig,
    NotionListCommentsConfig,
)

# Environment variable for Integration Token (don't hardcode in tests)
NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")

# Test IDs - will be populated during tests
TEST_DATABASE_ID = None
TEST_PAGE_ID = None
TEST_BLOCK_ID = None
TEST_USER_ID = None


def get_credentials():
    """Get Notion credentials from environment."""
    if not NOTION_TOKEN:
        pytest.skip(
            "NOTION_TOKEN is not set — these are live Notion calls, not a\n"
            "failure of the code under test. Set it to run them."
        )
    return NotionIntegrationTokenCredential(integration_token=NOTION_TOKEN)


def create_node(config) -> NotionNode:
    """Create a NotionNode instance with the given config."""
    credentials = get_credentials()
    node_config = NotionNodeConfig(config=config, credentials=credentials)
    node = NotionNode(
        node_id="test-node",
        node_type="automation-notion",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow",
    )
    return node


# ============================================================================
# Search Operations Tests (1 operation)
# ============================================================================


class TestSearchOperations:
    """Test search-related Notion API operations (1 total)."""

    @pytest.mark.asyncio
    async def test_search_all(self):
        """Test searching all accessible content."""
        global TEST_DATABASE_ID, TEST_PAGE_ID

        config = NotionSearchConfig()
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "search_pages_and_databases"
        assert result["status"] == "success"
        assert "results" in result["data"]
        assert isinstance(result["data"]["results"], list)

        # Store IDs for later tests
        for item in result["data"]["results"]:
            if item.get("object") == "database" and not TEST_DATABASE_ID:
                TEST_DATABASE_ID = item["id"]
            elif item.get("object") == "page" and not TEST_PAGE_ID:
                TEST_PAGE_ID = item["id"]

    @pytest.mark.asyncio
    async def test_search_with_query(self):
        """Test searching with a specific query."""
        config = NotionSearchConfig(query="test", page_size=5)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "search_pages_and_databases"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_search_filter_databases(self):
        """Test searching with database filter."""
        config = NotionSearchConfig(filter_type="database", page_size=10)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "search_pages_and_databases"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_search_filter_pages(self):
        """Test searching with page filter."""
        config = NotionSearchConfig(filter_type="page", page_size=10)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "search_pages_and_databases"
        assert result["status"] == "success"


# ============================================================================
# Database Operations Tests (4 operations)
# ============================================================================


class TestDatabaseOperations:
    """Test database-related Notion API operations (4 total)."""

    @pytest.mark.asyncio
    async def test_retrieve_database(self):
        """Test retrieving a database's metadata and schema."""
        global TEST_DATABASE_ID

        # First ensure we have a database ID
        if not TEST_DATABASE_ID:
            search_config = NotionSearchConfig(filter_type="database", page_size=1)
            search_node = create_node(search_config)
            search_result = await search_node.execute({})
            if search_result["status"] == "success" and search_result["data"].get(
                "results"
            ):
                TEST_DATABASE_ID = search_result["data"]["results"][0]["id"]
            else:
                pytest.skip("No databases available for testing")
                return

        config = NotionRetrieveDatabaseConfig(database_id=TEST_DATABASE_ID)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "fetch_database_metadata"
        if result["status"] == "success":
            # Notion returns IDs with hyphens, normalize for comparison
            assert result["data"]["id"].replace("-", "") == TEST_DATABASE_ID.replace(
                "-", ""
            )

    @pytest.mark.asyncio
    async def test_query_database(self):
        """Test querying a database to retrieve pages."""
        if not TEST_DATABASE_ID:
            pytest.skip("No database ID available for testing")

        config = NotionQueryDatabaseConfig(database_id=TEST_DATABASE_ID, page_size=10)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "query_notion_database"
        if result["status"] == "success":
            assert "results" in result["data"]
            assert isinstance(result["data"]["results"], list)

    @pytest.mark.asyncio
    async def test_query_database_with_filter(self):
        """Test querying a database with a filter."""
        if not TEST_DATABASE_ID:
            pytest.skip("No database ID available for testing")

        # Use a timestamp filter that should return all results
        config = NotionQueryDatabaseConfig(
            database_id=TEST_DATABASE_ID,
            page_size=5,
            sorts='[{"timestamp": "last_edited_time", "direction": "descending"}]',
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "query_notion_database"

    @pytest.mark.asyncio
    async def test_create_database(self):
        """Test creating a new database as a child of a page."""
        if not TEST_PAGE_ID:
            pytest.skip("No page ID available for testing")

        config = NotionCreateDatabaseConfig(
            parent_page_id=TEST_PAGE_ID,
            title=f"Test Database {int(time.time())}",
            properties='{"Name": {"title": {}}, "Status": {"select": {"options": [{"name": "To Do"}, {"name": "Done"}]}}}',
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "create_page_database"
        # May fail due to permissions

    @pytest.mark.asyncio
    async def test_update_database(self):
        """Test updating a database's title or description."""
        if not TEST_DATABASE_ID:
            pytest.skip("No database ID available for testing")

        config = NotionUpdateDatabaseConfig(
            database_id=TEST_DATABASE_ID,
            description=f"Updated description {int(time.time())}",
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "update_database_metadata"
        # May fail due to permissions


# ============================================================================
# Page Operations Tests (3 operations)
# ============================================================================


class TestPageOperations:
    """Test page-related Notion API operations (3 total)."""

    @pytest.mark.asyncio
    async def test_retrieve_page(self):
        """Test retrieving a page's properties."""
        global TEST_PAGE_ID, TEST_BLOCK_ID

        # First ensure we have a page ID
        if not TEST_PAGE_ID:
            search_config = NotionSearchConfig(filter_type="page", page_size=1)
            search_node = create_node(search_config)
            search_result = await search_node.execute({})
            if search_result["status"] == "success" and search_result["data"].get(
                "results"
            ):
                TEST_PAGE_ID = search_result["data"]["results"][0]["id"]
            else:
                pytest.skip("No pages available for testing")
                return

        config = NotionRetrievePageConfig(page_id=TEST_PAGE_ID)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "fetch_page_properties"
        if result["status"] == "success":
            assert "id" in result["data"]
            # Store the page ID as a block ID for block tests
            TEST_BLOCK_ID = TEST_PAGE_ID

    @pytest.mark.asyncio
    async def test_create_page_in_database(self):
        """Test creating a new page in a database."""
        if not TEST_DATABASE_ID:
            pytest.skip("No database ID available for testing")

        config = NotionCreatePageConfig(
            parent_type="database_id",
            parent_id=TEST_DATABASE_ID,
            properties='{"Name": {"title": [{"text": {"content": "Test Page '
            + str(int(time.time()))
            + '"}}]}}',
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "create_notion_page"
        # May fail due to permissions or missing required properties

    @pytest.mark.asyncio
    async def test_create_page_in_page(self):
        """Test creating a new page as a child of another page."""
        if not TEST_PAGE_ID:
            pytest.skip("No page ID available for testing")

        config = NotionCreatePageConfig(
            parent_type="page_id",
            parent_id=TEST_PAGE_ID,
            properties='{"title": {"title": [{"text": {"content": "Child Page '
            + str(int(time.time()))
            + '"}}]}}',
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "create_notion_page"
        # May fail due to permissions

    @pytest.mark.asyncio
    async def test_update_page(self):
        """Test updating a page's properties."""
        if not TEST_PAGE_ID:
            pytest.skip("No page ID available for testing")

        config = NotionUpdatePageConfig(page_id=TEST_PAGE_ID, icon="📝")
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "update_page_properties"
        # May fail due to permissions


# ============================================================================
# Block Operations Tests (5 operations)
# ============================================================================


class TestBlockOperations:
    """Test block-related Notion API operations (5 total)."""

    @pytest.mark.asyncio
    async def test_retrieve_block(self):
        """Test retrieving a block."""
        if not TEST_BLOCK_ID:
            pytest.skip("No block ID available for testing")

        config = NotionRetrieveBlockConfig(block_id=TEST_BLOCK_ID)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "fetch_notion_block"
        if result["status"] == "success":
            assert "id" in result["data"]

    @pytest.mark.asyncio
    async def test_retrieve_block_children(self):
        """Test retrieving a block's children."""
        if not TEST_BLOCK_ID:
            pytest.skip("No block ID available for testing")

        config = NotionRetrieveBlockChildrenConfig(block_id=TEST_BLOCK_ID, page_size=10)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "fetch_block_children"
        if result["status"] == "success":
            assert "results" in result["data"]
            assert isinstance(result["data"]["results"], list)

    @pytest.mark.asyncio
    async def test_append_block_children(self):
        """Test appending new children blocks to a parent block."""
        if not TEST_BLOCK_ID:
            pytest.skip("No block ID available for testing")

        config = NotionAppendBlockChildrenConfig(
            block_id=TEST_BLOCK_ID,
            children='[{"type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": "Test paragraph from automated tests"}}]}}]',
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "append_children_to_block"
        # May fail due to permissions

    @pytest.mark.asyncio
    async def test_update_block(self):
        """Test updating a block's content."""
        # First we need to find a non-page block to update
        if not TEST_BLOCK_ID:
            pytest.skip("No block ID available for testing")

        # Get block children to find an updatable block
        children_config = NotionRetrieveBlockChildrenConfig(
            block_id=TEST_BLOCK_ID, page_size=5
        )
        children_node = create_node(children_config)
        children_result = await children_node.execute({})

        if children_result["status"] != "success" or not children_result["data"].get(
            "results"
        ):
            # Try updating with a non-existent block to test action routing
            config = NotionUpdateBlockConfig(
                block_id="nonexistent-block-id",
                block_type="paragraph",
                content='{"rich_text": [{"text": {"content": "Updated content"}}]}',
            )
            node = create_node(config)
            result = await node.execute({})
            assert result["action"] == "update_block_content"
            return

        # Find a paragraph block to update
        block_to_update = None
        for block in children_result["data"]["results"]:
            if block.get("type") == "paragraph":
                block_to_update = block
                break

        if not block_to_update:
            pytest.skip("No paragraph block available for testing update")

        config = NotionUpdateBlockConfig(
            block_id=block_to_update["id"],
            block_type="paragraph",
            content='{"rich_text": [{"text": {"content": "Updated content '
            + str(int(time.time()))
            + '"}}]}',
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "update_block_content"
        # May fail due to permissions

    @pytest.mark.asyncio
    async def test_delete_block(self):
        """Test deleting (archiving) a block."""
        # Try to delete a non-existent block to test action routing
        config = NotionDeleteBlockConfig(block_id="nonexistent-block-id")
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "delete_notion_block"
        # Will fail with 404 but action should be correct


# ============================================================================
# User Operations Tests (3 operations)
# ============================================================================


class TestUserOperations:
    """Test user-related Notion API operations (3 total)."""

    @pytest.mark.asyncio
    async def test_list_users(self):
        """Test listing all users in the workspace."""
        global TEST_USER_ID

        config = NotionListUsersConfig(page_size=10)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "list_workspace_users"
        if result["status"] == "success":
            assert "results" in result["data"]
            assert isinstance(result["data"]["results"], list)

            # Store a user ID for later tests
            if result["data"]["results"]:
                TEST_USER_ID = result["data"]["results"][0]["id"]

    @pytest.mark.asyncio
    async def test_retrieve_user(self):
        """Test retrieving a user by ID."""
        if not TEST_USER_ID:
            # First list users to get an ID
            list_config = NotionListUsersConfig(page_size=1)
            list_node = create_node(list_config)
            list_result = await list_node.execute({})
            if list_result["status"] == "success" and list_result["data"].get(
                "results"
            ):
                user_id = list_result["data"]["results"][0]["id"]
            else:
                pytest.skip("No users available for testing")
                return
        else:
            user_id = TEST_USER_ID

        config = NotionRetrieveUserConfig(user_id=user_id)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "fetch_workspace_user"
        if result["status"] == "success":
            assert result["data"]["id"] == user_id

    @pytest.mark.asyncio
    async def test_retrieve_bot_user(self):
        """Test retrieving the bot user for the current integration."""
        config = NotionRetrieveBotUserConfig()
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "fetch_bot_integration_user"
        if result["status"] == "success":
            assert "id" in result["data"]
            assert result["data"].get("type") == "bot"


# ============================================================================
# Comment Operations Tests (3 operations)
# ============================================================================


class TestCommentOperations:
    """Test comment-related Notion API operations (3 total)."""

    @pytest.mark.asyncio
    async def test_list_comments(self):
        """Test listing comments on a block or page."""
        if not TEST_BLOCK_ID:
            pytest.skip("No block/page ID available for testing")

        config = NotionListCommentsConfig(block_id=TEST_BLOCK_ID, page_size=10)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "list_block_comments"
        if result["status"] == "success":
            assert "results" in result["data"]
            assert isinstance(result["data"]["results"], list)

    @pytest.mark.asyncio
    async def test_create_comment(self):
        """Test creating a comment on a page."""
        if not TEST_PAGE_ID:
            pytest.skip("No page ID available for testing")

        config = NotionCreateCommentConfig(
            parent_type="page_id",
            parent_id=TEST_PAGE_ID,
            rich_text='[{"type": "text", "text": {"content": "Test comment from automated tests '
            + str(int(time.time()))
            + '"}}]',
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "create_page_comment"
        # May fail due to permissions

    @pytest.mark.asyncio
    async def test_retrieve_comment(self):
        """Test retrieving a comment by ID."""
        # Try to retrieve a non-existent comment to test action routing
        config = NotionRetrieveCommentConfig(comment_id="nonexistent-comment-id")
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "fetch_page_comment"
        # Will fail with 404 but action should be correct


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Test error handling scenarios."""

    @pytest.mark.asyncio
    async def test_invalid_database_id(self):
        """Test handling of invalid database ID."""
        config = NotionRetrieveDatabaseConfig(database_id="invalid-database-id-12345")
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "error"
        assert result["action"] == "fetch_database_metadata"

    @pytest.mark.asyncio
    async def test_invalid_page_id(self):
        """Test handling of invalid page ID."""
        config = NotionRetrievePageConfig(page_id="invalid-page-id-12345")
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "error"
        assert result["action"] == "fetch_page_properties"

    @pytest.mark.asyncio
    async def test_invalid_block_id(self):
        """Test handling of invalid block ID."""
        config = NotionRetrieveBlockConfig(block_id="invalid-block-id-12345")
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "error"
        assert result["action"] == "fetch_notion_block"

    @pytest.mark.asyncio
    async def test_invalid_user_id(self):
        """Test handling of invalid user ID."""
        config = NotionRetrieveUserConfig(user_id="invalid-user-id-12345")
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "error"
        assert result["action"] == "fetch_workspace_user"

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        """Test handling of missing credentials."""
        config = NotionSearchConfig()
        node_config = NotionNodeConfig(config=config, credentials=None)
        node = NotionNode(
            node_id="test-node",
            node_type="automation-notion",
            node_data={},
            config=node_config,
            sio=None,
            sid=None,
            workflow_id="test-workflow",
        )

        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


# ============================================================================
# Timing and Performance Tests
# ============================================================================


class TestPerformance:
    """Test performance and timing information."""

    @pytest.mark.asyncio
    async def test_timing_information(self):
        """Test that timing information is included in responses."""
        config = NotionSearchConfig(page_size=1)
        node = create_node(config)

        result = await node.execute({})

        assert "timing_ms" in result
        assert "api_request" in result["timing_ms"]
        assert "total" in result["timing_ms"]
        assert result["timing_ms"]["api_request"] > 0
        assert result["timing_ms"]["total"] > 0


if __name__ == "__main__":
    # Run tests with: NOTION_TOKEN=your_token pytest nodes/tests/test_notion_node.py -v
    pytest.main([__file__, "-v"])
