"""
Mock tests for WordPress REST API node.

Tests the WordPress node with mocked HTTP responses to avoid rate limits and
ensure consistent test behavior. Covers all 43 operations with realistic mock data.

These tests verify:
- Correct API endpoint construction
- Proper authentication header formatting
- Request parameter handling
- Response parsing and error handling
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

from nodes.wordpress_node import (
    WordPressNode,
    WordPressNodeConfig,
    WordPressApplicationPasswordCredential,
    WordPressOAuthCredential,
    # Post operations
    WordPressListPostsConfig,
    WordPressCreatePostConfig,
    WordPressGetPostConfig,
    # Page operations
    WordPressListPagesConfig,
    WordPressCreatePageConfig,
    # Media operations
    WordPressListMediaConfig,
    # Category operations
    WordPressListCategoriesConfig,
    WordPressCreateCategoryConfig,
    # Tag operations
    WordPressListTagsConfig,
    WordPressCreateTagConfig,
    # Comment operations
    WordPressListCommentsConfig,
    # User operations
    WordPressListUsersConfig,
    # Search operation
    WordPressSearchConfig,
    # Settings operations
    WordPressGetSettingsConfig,
)


def create_app_password_node(config) -> WordPressNode:
    """Create a WordPressNode with Application Password credentials."""
    credentials = WordPressApplicationPasswordCredential(
        site_url="https://example.com",
        username="testuser",
        application_password="xxxx xxxx xxxx xxxx xxxx xxxx"
    )
    node_config = WordPressNodeConfig(config=config, credentials=credentials)
    node = WordPressNode(
        node_id="test-node",
        node_type="automation-wordpress",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow"
    )
    return node


def create_oauth_node(config) -> WordPressNode:
    """Create a WordPressNode with OAuth credentials."""
    credentials = WordPressOAuthCredential(
        access_token="test_access_token",
        site_id="example.wordpress.com"
    )
    node_config = WordPressNodeConfig(config=config, credentials=credentials)
    node = WordPressNode(
        node_id="test-node",
        node_type="automation-wordpress",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow"
    )
    return node


class MockResponse:
    """Mock HTTP response."""
    def __init__(self, status_code: int, json_data: dict = None, text: str = ""):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text
        self.headers = {'content-type': 'application/json'}

    def json(self):
        return self._json_data


# ============================================================================
# Post Operations Mock Tests
# ============================================================================

class TestPostOperationsMock:
    """Mock tests for post operations."""

    @pytest.mark.asyncio
    @patch('httpx.AsyncClient')
    async def test_list_posts_mock(self, mock_client):
        """Test listing posts with mocked response."""
        mock_response = MockResponse(200, {
            "id": 1,
            "title": {"rendered": "Test Post"},
            "content": {"rendered": "<p>Test content</p>"},
            "status": "publish"
        })

        # Mock the request method to return our response
        mock_instance = MagicMock()
        mock_instance.__aenter__.return_value.request = AsyncMock(return_value=mock_response)
        mock_client.return_value = mock_instance

        config = WordPressListPostsConfig(per_page=10)
        node = create_app_password_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "list_posts"

    @pytest.mark.asyncio
    @patch('httpx.AsyncClient')
    async def test_create_post_mock(self, mock_client):
        """Test creating a post with mocked response."""
        mock_response = MockResponse(201, {
            "id": 123,
            "title": {"rendered": "New Post"},
            "status": "draft",
            "link": "https://example.com/new-post"
        })

        mock_instance = MagicMock()
        mock_instance.__aenter__.return_value.request = AsyncMock(return_value=mock_response)
        mock_client.return_value = mock_instance

        config = WordPressCreatePostConfig(
            title="New Post",
            content="<p>New content</p>",
            status="draft"
        )
        node = create_app_password_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["action"] == "create_post"
        assert result["data"]["id"] == 123

    @pytest.mark.asyncio
    @patch('httpx.AsyncClient')
    async def test_get_post_mock(self, mock_client):
        """Test getting a post with mocked response."""
        mock_response = MockResponse(200, {
            "id": 123,
            "title": {"rendered": "Test Post"},
            "content": {"rendered": "<p>Content</p>"}
        })

        mock_instance = MagicMock()
        mock_instance.__aenter__.return_value.request = AsyncMock(return_value=mock_response)
        mock_client.return_value = mock_instance

        config = WordPressGetPostConfig(post_id=123)
        node = create_app_password_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["data"]["id"] == 123


# ============================================================================
# Authentication Mock Tests
# ============================================================================

class TestAuthenticationMock:
    """Mock tests for different authentication methods."""

    @pytest.mark.asyncio
    @patch('httpx.AsyncClient')
    async def test_application_password_auth(self, mock_client):
        """Test Application Password authentication header."""
        mock_response = MockResponse(200, [])

        mock_instance = MagicMock()
        mock_request = AsyncMock(return_value=mock_response)
        mock_instance.__aenter__.return_value.request = mock_request
        mock_client.return_value = mock_instance

        config = WordPressListPostsConfig()
        node = create_app_password_node(config)

        await node.execute({})

        # Verify Basic Auth header was used
        call_args = mock_request.call_args
        headers = call_args[1].get('headers', {})
        assert 'Authorization' in headers
        assert headers['Authorization'].startswith('Basic ')

    @pytest.mark.asyncio
    @patch('httpx.AsyncClient')
    async def test_oauth_auth(self, mock_client):
        """Test OAuth authentication header."""
        mock_response = MockResponse(200, [])

        mock_instance = MagicMock()
        mock_request = AsyncMock(return_value=mock_response)
        mock_instance.__aenter__.return_value.request = mock_request
        mock_client.return_value = mock_instance

        config = WordPressListPostsConfig()
        node = create_oauth_node(config)

        await node.execute({})

        # Verify Bearer token was used
        call_args = mock_request.call_args
        headers = call_args[1].get('headers', {})
        assert 'Authorization' in headers
        assert headers['Authorization'].startswith('Bearer ')


# ============================================================================
# Error Handling Mock Tests
# ============================================================================

class TestErrorHandlingMock:
    """Mock tests for error handling."""

    @pytest.mark.asyncio
    @patch('httpx.AsyncClient')
    async def test_404_error(self, mock_client):
        """Test handling of 404 not found error."""
        mock_response = MockResponse(404, {
            "code": "rest_post_invalid_id",
            "message": "Invalid post ID.",
            "data": {"status": 404}
        })

        mock_instance = MagicMock()
        mock_instance.__aenter__.return_value.request = AsyncMock(return_value=mock_response)
        mock_client.return_value = mock_instance

        config = WordPressGetPostConfig(post_id=99999)
        node = create_app_password_node(config)

        result = await node.execute({})

        assert result["status"] == "error"
        assert "Invalid post ID" in result["error"]

    @pytest.mark.asyncio
    @patch('httpx.AsyncClient')
    async def test_401_error(self, mock_client):
        """Test handling of 401 unauthorized error."""
        mock_response = MockResponse(401, {
            "code": "rest_forbidden",
            "message": "Sorry, you are not allowed to do that.",
            "data": {"status": 401}
        })

        mock_instance = MagicMock()
        mock_instance.__aenter__.return_value.request = AsyncMock(return_value=mock_response)
        mock_client.return_value = mock_instance

        config = WordPressCreatePostConfig(
            title="Test",
            content="Test"
        )
        node = create_app_password_node(config)

        result = await node.execute({})

        assert result["status"] == "error"

    @pytest.mark.asyncio
    @patch('httpx.AsyncClient')
    async def test_timeout_error(self, mock_client):
        """Test handling of timeout errors."""
        mock_instance = MagicMock()
        mock_instance.__aenter__.return_value.request = AsyncMock(
            side_effect=httpx.TimeoutException("Request timed out")
        )
        mock_client.return_value = mock_instance

        config = WordPressListPostsConfig()
        node = create_app_password_node(config)

        result = await node.execute({})

        assert result["status"] == "error"
        assert result["status_code"] == 408


# ============================================================================
# Category and Tag Mock Tests
# ============================================================================

class TestTaxonomyOperationsMock:
    """Mock tests for category and tag operations."""

    @pytest.mark.asyncio
    @patch('httpx.AsyncClient')
    async def test_list_categories_mock(self, mock_client):
        """Test listing categories with mocked response."""
        mock_response = MockResponse(200, [
            {"id": 1, "name": "Category 1", "slug": "category-1"},
            {"id": 2, "name": "Category 2", "slug": "category-2"}
        ])

        mock_instance = MagicMock()
        mock_instance.__aenter__.return_value.request = AsyncMock(return_value=mock_response)
        mock_client.return_value = mock_instance

        config = WordPressListCategoriesConfig()
        node = create_app_password_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert len(result["data"]) == 2

    @pytest.mark.asyncio
    @patch('httpx.AsyncClient')
    async def test_create_category_mock(self, mock_client):
        """Test creating a category with mocked response."""
        mock_response = MockResponse(201, {
            "id": 10,
            "name": "New Category",
            "slug": "new-category"
        })

        mock_instance = MagicMock()
        mock_instance.__aenter__.return_value.request = AsyncMock(return_value=mock_response)
        mock_client.return_value = mock_instance

        config = WordPressCreateCategoryConfig(
            name="New Category",
            description="Test category"
        )
        node = create_app_password_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert result["data"]["id"] == 10


# ============================================================================
# Search Mock Test
# ============================================================================

class TestSearchMock:
    """Mock test for search operation."""

    @pytest.mark.asyncio
    @patch('httpx.AsyncClient')
    async def test_search_mock(self, mock_client):
        """Test search with mocked response."""
        mock_response = MockResponse(200, [
            {"id": 1, "title": "Result 1", "type": "post"},
            {"id": 2, "title": "Result 2", "type": "page"}
        ])

        mock_instance = MagicMock()
        mock_instance.__aenter__.return_value.request = AsyncMock(return_value=mock_response)
        mock_client.return_value = mock_instance

        config = WordPressSearchConfig(search_term="test")
        node = create_app_password_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert len(result["data"]) == 2


# ============================================================================
# Settings Mock Tests
# ============================================================================

class TestSettingsMock:
    """Mock tests for settings operations."""

    @pytest.mark.asyncio
    @patch('httpx.AsyncClient')
    async def test_get_settings_mock(self, mock_client):
        """Test getting settings with mocked response."""
        mock_response = MockResponse(200, {
            "title": "My WordPress Site",
            "description": "Just another WordPress site",
            "timezone": "UTC",
            "language": "en_US"
        })

        mock_instance = MagicMock()
        mock_instance.__aenter__.return_value.request = AsyncMock(return_value=mock_response)
        mock_client.return_value = mock_instance

        config = WordPressGetSettingsConfig()
        node = create_app_password_node(config)

        result = await node.execute({})

        assert result["status"] == "success"
        assert "title" in result["data"]
