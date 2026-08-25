"""
Mock tests for Instagram Graph API node.

Tests all 23 Instagram operations using mocked HTTP responses.
No real API credentials needed - all tests use mocked httpx.AsyncClient.

This ensures:
- All operations are correctly structured
- Request formatting is correct
- Response parsing works as expected
- Error handling is robust
- All 3 credential types work correctly
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
from datetime import datetime, timedelta, timezone

# Import all Instagram node components
from nodes.instagram_node import (
    InstagramNode,
    InstagramNodeConfig,
    InstagramOAuthCredential,
    InstagramLoginCredential,
    InstagramSystemUserTokenCredential,
    InstagramPageAccessTokenCredential,
    # Profile operations (1)
    InstagramGetProfileConfig,
    # Media operations (6)
    InstagramListMediaConfig,
    InstagramGetMediaConfig,
    InstagramPublishPhotoConfig,
    InstagramPublishVideoConfig,
    InstagramPublishCarouselConfig,
    # Comment operations (5)
    InstagramListCommentsConfig,
    InstagramCreateCommentConfig,
    InstagramReplyToCommentConfig,
    InstagramHideCommentConfig,
    InstagramDeleteCommentConfig,
    # Insights operations (2)
    InstagramGetMediaInsightsConfig,
    InstagramGetAccountInsightsConfig,
    # Hashtag operations (2)
    InstagramSearchHashtagConfig,
    InstagramGetHashtagMediaConfig,
    # Discovery operations (1)
    InstagramBusinessDiscoveryConfig,
    # Stories operations (2)
    InstagramPublishStoryPhotoConfig,
    InstagramPublishStoryVideoConfig,
    # Mentions operations (2)
    InstagramGetMentionedMediaConfig,
    InstagramGetMentionedCommentsConfig,
    # Product tagging operations (3)
    InstagramTagProductsConfig,
    InstagramGetProductTagsConfig,
    InstagramDeleteProductTagsConfig,
)


# Mock credentials for testing
MOCK_ACCESS_TOKEN = "mock_access_token_12345"
MOCK_USER_ID = "1234567890"
MOCK_USERNAME = "mock_user"
MOCK_PAGE_ID = "9876543210"


def get_oauth_credential():
    """Get mock OAuth credential with future expiry (60 days from now)."""
    # Set expiry to 60 days in the future (timezone-aware)
    future_expiry = datetime.now(timezone.utc) + timedelta(days=60)
    return InstagramOAuthCredential(
        access_token=MOCK_ACCESS_TOKEN,
        instagram_user_id=MOCK_USER_ID,
        expires_at=future_expiry.isoformat(),
        email="test@example.com",
        instagram_username=MOCK_USERNAME,
    )


def get_system_user_credential():
    """Get mock System User Token credential."""
    return InstagramSystemUserTokenCredential(
        access_token=MOCK_ACCESS_TOKEN,
        instagram_user_id=MOCK_USER_ID,
        instagram_username=MOCK_USERNAME,
    )


def get_page_access_credential():
    """Get mock Page Access Token credential."""
    return InstagramPageAccessTokenCredential(
        access_token=MOCK_ACCESS_TOKEN,
        instagram_user_id=MOCK_USER_ID,
        page_id=MOCK_PAGE_ID,
        instagram_username=MOCK_USERNAME,
        expires_at=None,  # Permanent token
    )


def create_mock_response(json_data, status_code=200):
    """Create a mock httpx.Response with proper attributes."""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.json = MagicMock(return_value=json_data)
    mock_response.raise_for_status = MagicMock()
    mock_response.text = str(json_data)
    return mock_response


def mock_async_client(responses):
    """
    Create a mock AsyncClient that returns specific responses.

    Args:
        responses: List of mock responses to return in order, or a single response

    Returns:
        Patch context for httpx.AsyncClient
    """
    if not isinstance(responses, list):
        responses = [responses]

    # Keep track of which response to return next
    response_index = [0]

    async def mock_any_method(*args, **kwargs):
        """Mock function that works for any HTTP method."""
        if len(responses) == 1:
            return responses[0]
        idx = response_index[0]
        if idx < len(responses):
            response_index[0] += 1
            return responses[idx]
        # Return last response if we run out
        return responses[-1]

    mock_client = AsyncMock()
    # Set up mock to handle request() method (which is what Instagram node uses)
    mock_client.request = mock_any_method
    # Also handle get, post, delete for any tests that might use them directly
    mock_client.get = mock_any_method
    mock_client.post = mock_any_method
    mock_client.delete = mock_any_method

    async_client_mock = MagicMock()
    async_client_mock.return_value.__aenter__.return_value = mock_client

    return patch("httpx.AsyncClient", async_client_mock)


# ============================================================================
# Profile Operations Tests (1 operation)
# ============================================================================


class TestProfileOperationsMock:
    """Test profile-related operations with mocks."""

    @pytest.mark.asyncio
    async def test_get_profile(self):
        """Test getting Instagram profile information."""
        config = InstagramGetProfileConfig()
        node_config = InstagramNodeConfig(
            config=config,
            credentials=get_oauth_credential(),
        )
        node = InstagramNode(
            node_id="test_node",
            node_type="automation-instagram",
            node_data={},
            config=node_config,
        )

        mock_response_data = {
            "id": MOCK_USER_ID,
            "username": MOCK_USERNAME,
            "account_type": "BUSINESS",
            "media_count": 150,
            "followers_count": 5000,
            "follows_count": 300,
        }

        with mock_async_client(create_mock_response(mock_response_data)):
            result = await node.execute({})

        assert result["action"] == "get_user_profile"
        assert result["status"] == "success"
        assert result["data"]["username"] == MOCK_USERNAME
        assert result["data"]["account_type"] == "BUSINESS"


# ============================================================================
# Media Operations Tests (6 operations)
# ============================================================================


class TestMediaOperationsMock:
    """Test media-related operations with mocks."""

    @pytest.mark.asyncio
    async def test_list_media(self):
        """Test listing media from Instagram account."""
        config = InstagramListMediaConfig(limit=10)
        node_config = InstagramNodeConfig(
            config=config,
            credentials=get_oauth_credential(),
        )
        node = InstagramNode(
            node_id="test_node",
            node_type="automation-instagram",
            node_data={},
            config=node_config,
        )

        mock_response_data = {
            "data": [
                {"id": "media_1", "media_type": "IMAGE", "caption": "Test post 1"},
                {"id": "media_2", "media_type": "VIDEO", "caption": "Test post 2"},
            ],
            "paging": {"next": "next_page_cursor"},
        }

        with mock_async_client(create_mock_response(mock_response_data)):
            result = await node.execute({})

        assert result["action"] == "list_user_media"
        assert result["status"] == "success"
        assert len(result["data"]["data"]) == 2

    @pytest.mark.asyncio
    async def test_get_media(self):
        """Test getting specific media details."""
        config = InstagramGetMediaConfig(media_id="test_media_id")
        node_config = InstagramNodeConfig(
            config=config,
            credentials=get_oauth_credential(),
        )
        node = InstagramNode(
            node_id="test_node",
            node_type="automation-instagram",
            node_data={},
            config=node_config,
        )

        mock_response_data = {
            "id": "test_media_id",
            "media_type": "IMAGE",
            "caption": "Test caption",
            "like_count": 100,
            "comments_count": 25,
        }

        with mock_async_client(create_mock_response(mock_response_data)):
            result = await node.execute({})

        assert result["action"] == "get_media_details"
        assert result["status"] == "success"
        assert result["data"]["media_type"] == "IMAGE"

    @pytest.mark.asyncio
    async def test_publish_photo(self):
        """Test publishing a photo."""
        config = InstagramPublishPhotoConfig(
            image_url="https://example.com/photo.jpg",
            caption="Test photo",
        )
        node_config = InstagramNodeConfig(
            config=config,
            credentials=get_oauth_credential(),
        )
        node = InstagramNode(
            node_id="test_node",
            node_type="automation-instagram",
            node_data={},
            config=node_config,
        )

        # Mock container creation
        container_response = {"id": "container_123"}
        # Mock publish response
        publish_response = {"id": "media_123"}

        with mock_async_client(
            [
                create_mock_response(container_response),
                create_mock_response(publish_response),
            ]
        ):
            result = await node.execute({})

        assert result["action"] == "publish_photo_post"
        assert result["status"] == "success"
        assert "id" in result["data"]

    @pytest.mark.asyncio
    async def test_publish_video(self):
        """Test publishing a video."""
        config = InstagramPublishVideoConfig(
            video_url="https://example.com/video.mp4",
            caption="Test video",
        )
        node_config = InstagramNodeConfig(
            config=config,
            credentials=get_oauth_credential(),
        )
        node = InstagramNode(
            node_id="test_node",
            node_type="automation-instagram",
            node_data={},
            config=node_config,
        )

        # Mock container creation
        container_response = {"id": "container_456"}
        # Mock status checks (processing then complete)
        status_in_progress_response = {"status_code": "IN_PROGRESS"}
        status_finished_response = {"status_code": "FINISHED"}
        # Mock publish response
        publish_response = {"id": "media_456"}

        with mock_async_client(
            [
                create_mock_response(container_response),
                create_mock_response(status_in_progress_response),
                create_mock_response(status_finished_response),
                create_mock_response(publish_response),
            ]
        ):
            result = await node.execute({})

        assert result["action"] == "publish_video_reel"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_publish_carousel(self):
        """Test publishing a carousel."""
        config = InstagramPublishCarouselConfig(
            media_urls='[{"type": "IMAGE", "url": "https://example.com/1.jpg"}, {"type": "IMAGE", "url": "https://example.com/2.jpg"}]',
            caption="Test carousel",
        )
        node_config = InstagramNodeConfig(
            config=config,
            credentials=get_oauth_credential(),
        )
        node = InstagramNode(
            node_id="test_node",
            node_type="automation-instagram",
            node_data={},
            config=node_config,
        )

        # Mock child container creation
        child_response = {"id": "child_123"}
        # Mock carousel container
        carousel_response = {"id": "carousel_123"}
        # Mock publish response
        publish_response = {"id": "media_789"}

        with mock_async_client(
            [
                create_mock_response(child_response),
                create_mock_response(child_response),
                create_mock_response(carousel_response),
                create_mock_response(publish_response),
            ]
        ):
            result = await node.execute({})

        assert result["action"] == "publish_carousel_post"
        assert result["status"] == "success"


# ============================================================================
# Comment Operations Tests (5 operations)
# ============================================================================


class TestCommentOperationsMock:
    """Test comment-related operations with mocks."""

    @pytest.mark.asyncio
    async def test_list_comments(self):
        """Test listing comments on a media."""
        config = InstagramListCommentsConfig(media_id="test_media_id")
        node_config = InstagramNodeConfig(
            config=config,
            credentials=get_oauth_credential(),
        )
        node = InstagramNode(
            node_id="test_node",
            node_type="automation-instagram",
            node_data={},
            config=node_config,
        )

        mock_response_data = {
            "data": [
                {"id": "comment_1", "text": "Great post!", "username": "user1"},
                {"id": "comment_2", "text": "Love it!", "username": "user2"},
            ]
        }

        with mock_async_client(create_mock_response(mock_response_data)):
            result = await node.execute({})

        assert result["action"] == "list_media_comments"
        assert result["status"] == "success"
        assert len(result["data"]["data"]) == 2

    @pytest.mark.asyncio
    async def test_create_comment(self):
        """Test creating a comment."""
        config = InstagramCreateCommentConfig(
            media_id="test_media_id",
            message="Nice work!",
        )
        node_config = InstagramNodeConfig(
            config=config,
            credentials=get_oauth_credential(),
        )
        node = InstagramNode(
            node_id="test_node",
            node_type="automation-instagram",
            node_data={},
            config=node_config,
        )

        mock_response_data = {"id": "new_comment_123"}

        with mock_async_client(create_mock_response(mock_response_data)):
            result = await node.execute({})

        assert result["action"] == "create_media_comment"
        assert result["status"] == "success"
        assert "id" in result["data"]

    @pytest.mark.asyncio
    async def test_reply_to_comment(self):
        """Test replying to a comment."""
        config = InstagramReplyToCommentConfig(
            comment_id="test_comment_id",
            message="Thanks for your comment!",
        )
        node_config = InstagramNodeConfig(
            config=config,
            credentials=get_oauth_credential(),
        )
        node = InstagramNode(
            node_id="test_node",
            node_type="automation-instagram",
            node_data={},
            config=node_config,
        )

        mock_response_data = {"id": "reply_123"}

        with mock_async_client(create_mock_response(mock_response_data)):
            result = await node.execute({})

        assert result["action"] == "reply_to_comment"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_hide_comment(self):
        """Test hiding a comment."""
        config = InstagramHideCommentConfig(comment_id="test_comment_id", hide=True)
        node_config = InstagramNodeConfig(
            config=config,
            credentials=get_oauth_credential(),
        )
        node = InstagramNode(
            node_id="test_node",
            node_type="automation-instagram",
            node_data={},
            config=node_config,
        )

        mock_response_data = {"success": True}

        with mock_async_client(create_mock_response(mock_response_data)):
            result = await node.execute({})

        assert result["action"] == "hide_or_unhide_comment"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_delete_comment(self):
        """Test deleting a comment."""
        config = InstagramDeleteCommentConfig(comment_id="test_comment_id")
        node_config = InstagramNodeConfig(
            config=config,
            credentials=get_oauth_credential(),
        )
        node = InstagramNode(
            node_id="test_node",
            node_type="automation-instagram",
            node_data={},
            config=node_config,
        )

        mock_response_data = {"success": True}

        with mock_async_client(create_mock_response(mock_response_data)):
            result = await node.execute({})

        assert result["action"] == "delete_comment"
        assert result["status"] == "success"


# ============================================================================
# Insights Operations Tests (2 operations)
# ============================================================================


class TestInsightsOperationsMock:
    """Test insights-related operations with mocks."""

    @pytest.mark.asyncio
    async def test_get_media_insights(self):
        """Test getting media insights."""
        config = InstagramGetMediaInsightsConfig(
            media_id="test_media_id", metrics="impressions,reach,engagement"
        )
        node_config = InstagramNodeConfig(
            config=config,
            credentials=get_oauth_credential(),
        )
        node = InstagramNode(
            node_id="test_node",
            node_type="automation-instagram",
            node_data={},
            config=node_config,
        )

        mock_response_data = {
            "data": [
                {"name": "impressions", "values": [{"value": 1000}]},
                {"name": "reach", "values": [{"value": 800}]},
                {"name": "engagement", "values": [{"value": 150}]},
            ]
        }

        with mock_async_client(create_mock_response(mock_response_data)):
            result = await node.execute({})

        assert result["action"] == "get_media_insights"
        assert result["status"] == "success"
        assert len(result["data"]["data"]) == 3

    @pytest.mark.asyncio
    async def test_get_account_insights(self):
        """Test getting account insights."""
        config = InstagramGetAccountInsightsConfig(
            metrics="impressions,reach,profile_views",
            period="day",
            since="2024-01-01",
            until="2024-01-31",
        )
        node_config = InstagramNodeConfig(
            config=config,
            credentials=get_oauth_credential(),
        )
        node = InstagramNode(
            node_id="test_node",
            node_type="automation-instagram",
            node_data={},
            config=node_config,
        )

        mock_response_data = {
            "data": [
                {"name": "impressions", "values": [{"value": 5000}]},
                {"name": "reach", "values": [{"value": 4000}]},
                {"name": "profile_views", "values": [{"value": 500}]},
            ]
        }

        with mock_async_client(create_mock_response(mock_response_data)):
            result = await node.execute({})

        assert result["action"] == "get_account_insights"
        assert result["status"] == "success"


# ============================================================================
# Hashtag Operations Tests (2 operations)
# ============================================================================


class TestHashtagOperationsMock:
    """Test hashtag-related operations with mocks."""

    @pytest.mark.asyncio
    async def test_search_hashtag(self):
        """Test searching for hashtags."""
        config = InstagramSearchHashtagConfig(hashtag="nature")
        node_config = InstagramNodeConfig(
            config=config,
            credentials=get_oauth_credential(),
        )
        node = InstagramNode(
            node_id="test_node",
            node_type="automation-instagram",
            node_data={},
            config=node_config,
        )

        mock_response_data = {"data": [{"id": "hashtag_123", "name": "nature"}]}

        with mock_async_client(create_mock_response(mock_response_data)):
            result = await node.execute({})

        assert result["action"] == "search_hashtag_id"
        assert result["status"] == "success"
        assert result["data"]["data"][0]["name"] == "nature"

    @pytest.mark.asyncio
    async def test_get_hashtag_media(self):
        """Test getting recent media for a hashtag."""
        config = InstagramGetHashtagMediaConfig(hashtag_id="hashtag_123")
        node_config = InstagramNodeConfig(
            config=config,
            credentials=get_oauth_credential(),
        )
        node = InstagramNode(
            node_id="test_node",
            node_type="automation-instagram",
            node_data={},
            config=node_config,
        )

        mock_response_data = {
            "data": [
                {"id": "media_1", "caption": "Nature photo 1"},
                {"id": "media_2", "caption": "Nature photo 2"},
            ]
        }

        with mock_async_client(create_mock_response(mock_response_data)):
            result = await node.execute({})

        assert result["action"] == "get_hashtag_media"
        assert result["status"] == "success"


# ============================================================================
# Business Discovery Tests (1 operation)
# ============================================================================


class TestBusinessDiscoveryMock:
    """Test business discovery operation with mocks."""

    @pytest.mark.asyncio
    async def test_business_discovery(self):
        """Test discovering other business accounts."""
        config = InstagramBusinessDiscoveryConfig(username="testbusiness")
        node_config = InstagramNodeConfig(
            config=config,
            credentials=get_oauth_credential(),
        )
        node = InstagramNode(
            node_id="test_node",
            node_type="automation-instagram",
            node_data={},
            config=node_config,
        )

        mock_response_data = {
            "business_discovery": {
                "id": "business_123",
                "username": "testbusiness",
                "followers_count": 10000,
                "media_count": 250,
            }
        }

        with mock_async_client(create_mock_response(mock_response_data)):
            result = await node.execute({})

        assert result["action"] == "discover_business_account"
        assert result["status"] == "success"
        assert result["data"]["business_discovery"]["username"] == "testbusiness"


# ============================================================================
# Stories Operations Tests (2 operations)
# ============================================================================


class TestStoriesOperationsMock:
    """Test stories-related operations with mocks."""

    @pytest.mark.asyncio
    async def test_publish_story_photo(self):
        """Test publishing a photo story."""
        config = InstagramPublishStoryPhotoConfig(
            image_url="https://example.com/story.jpg"
        )
        node_config = InstagramNodeConfig(
            config=config,
            credentials=get_oauth_credential(),
        )
        node = InstagramNode(
            node_id="test_node",
            node_type="automation-instagram",
            node_data={},
            config=node_config,
        )

        # Mock container creation
        container_response = {"id": "story_container_123"}
        # Mock publish response
        publish_response = {"id": "story_123"}

        with mock_async_client(
            [
                create_mock_response(container_response),
                create_mock_response(publish_response),
            ]
        ):
            result = await node.execute({})

        assert result["action"] == "publish_photo_story"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_publish_story_video(self):
        """Test publishing a video story."""
        config = InstagramPublishStoryVideoConfig(
            video_url="https://example.com/story.mp4"
        )
        node_config = InstagramNodeConfig(
            config=config,
            credentials=get_oauth_credential(),
        )
        node = InstagramNode(
            node_id="test_node",
            node_type="automation-instagram",
            node_data={},
            config=node_config,
        )

        # Mock container creation
        container_response = {"id": "story_video_container_456"}
        # Mock status check
        status_response = {"status_code": "FINISHED"}
        # Mock publish response
        publish_response = {"id": "story_456"}

        with mock_async_client(
            [
                create_mock_response(container_response),
                create_mock_response(publish_response),
                create_mock_response(status_response),
            ]
        ):
            result = await node.execute({})

        assert result["action"] == "publish_video_story"
        assert result["status"] == "success"


# ============================================================================
# Mentions Operations Tests (2 operations)
# ============================================================================


class TestMentionsOperationsMock:
    """Test mentions-related operations with mocks."""

    @pytest.mark.asyncio
    async def test_get_mentioned_media(self):
        """Mentions are a field expansion on the IG User node keyed by media id,
        NOT a /mentioned_media edge (which returns 'Unknown path components')."""
        config = InstagramGetMentionedMediaConfig(media_id="17895695668004550")
        node_config = InstagramNodeConfig(config=config, credentials=get_oauth_credential())
        node = InstagramNode(node_id="test_node", node_type="automation-instagram",
                             node_data={}, config=node_config)

        captured = {}

        async def capturing_request(method, url, **kwargs):
            captured.update(method=method, url=url, params=kwargs.get("params") or {})
            return create_mock_response({"mentioned_media": {"id": "17895695668004550",
                                                             "caption": "Check out @mock_user!"},
                                         "id": "ig_user_123"})

        client = AsyncMock()
        client.request = capturing_request
        acm = MagicMock()
        acm.return_value.__aenter__.return_value = client
        with patch("httpx.AsyncClient", acm):
            result = await node.execute({})

        assert result["action"] == "get_mentioned_media"
        assert result["status"] == "success"
        # endpoint is the IG user node, not the (invalid) /mentioned_media edge
        assert captured["url"].endswith(f"/{get_oauth_credential().instagram_user_id}")
        assert "/mentioned_media" not in captured["url"]
        assert "mentioned_media.media_id(17895695668004550)" in captured["params"]["fields"]

    @pytest.mark.asyncio
    async def test_get_mentioned_comments(self):
        """Mentioned comments are a field expansion keyed by comment id, not an edge."""
        config = InstagramGetMentionedCommentsConfig(comment_id="17862154342000000")
        node_config = InstagramNodeConfig(config=config, credentials=get_oauth_credential())
        node = InstagramNode(node_id="test_node", node_type="automation-instagram",
                             node_data={}, config=node_config)

        captured = {}

        async def capturing_request(method, url, **kwargs):
            captured.update(method=method, url=url, params=kwargs.get("params") or {})
            return create_mock_response({"mentioned_comment": {"id": "17862154342000000",
                                                               "text": "Hey @mock_user!"},
                                         "id": "ig_user_123"})

        client = AsyncMock()
        client.request = capturing_request
        acm = MagicMock()
        acm.return_value.__aenter__.return_value = client
        with patch("httpx.AsyncClient", acm):
            result = await node.execute({})

        assert result["action"] == "get_mentioned_comments"
        assert result["status"] == "success"
        assert captured["url"].endswith(f"/{get_oauth_credential().instagram_user_id}")
        assert "/mentioned_comment" not in captured["url"]
        assert "mentioned_comment.comment_id(17862154342000000)" in captured["params"]["fields"]


# ============================================================================
# Product Tagging Operations Tests (3 operations)
# ============================================================================


class TestProductTaggingMock:
    """Test product tagging operations with mocks."""

    @pytest.mark.asyncio
    async def test_tag_products(self):
        """Test tagging products in media."""
        config = InstagramTagProductsConfig(
            media_id="test_media_id",
            product_tags='[{"product_id": "prod_123", "x": 0.5, "y": 0.5}]',
        )
        node_config = InstagramNodeConfig(
            config=config,
            credentials=get_oauth_credential(),
        )
        node = InstagramNode(
            node_id="test_node",
            node_type="automation-instagram",
            node_data={},
            config=node_config,
        )

        mock_response_data = {"success": True}

        with mock_async_client(create_mock_response(mock_response_data)):
            result = await node.execute({})

        assert result["action"] == "tag_products_in_media"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_get_product_tags(self):
        """Test getting product tags from media."""
        config = InstagramGetProductTagsConfig(media_id="test_media_id")
        node_config = InstagramNodeConfig(
            config=config,
            credentials=get_oauth_credential(),
        )
        node = InstagramNode(
            node_id="test_node",
            node_type="automation-instagram",
            node_data={},
            config=node_config,
        )

        mock_response_data = {
            "data": [
                {"product_id": "prod_123", "x": 0.5, "y": 0.5},
                {"product_id": "prod_456", "x": 0.3, "y": 0.7},
            ]
        }

        with mock_async_client(create_mock_response(mock_response_data)):
            result = await node.execute({})

        assert result["action"] == "get_media_product_tags"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_delete_product_tags(self):
        """Test deleting product tags from media."""
        config = InstagramDeleteProductTagsConfig(media_id="test_media_id")
        node_config = InstagramNodeConfig(
            config=config,
            credentials=get_oauth_credential(),
        )
        node = InstagramNode(
            node_id="test_node",
            node_type="automation-instagram",
            node_data={},
            config=node_config,
        )

        mock_response_data = {"success": True}

        with mock_async_client(create_mock_response(mock_response_data)):
            result = await node.execute({})

        assert result["action"] == "delete_product_tags_from_media"
        assert result["status"] == "success"


# ============================================================================
# Credential Types Tests (3 types)
# ============================================================================


class TestCredentialTypesMock:
    """Test all 3 credential types work correctly."""

    @pytest.mark.asyncio
    async def test_oauth_credential(self):
        """Test OAuth credential type."""
        config = InstagramGetProfileConfig()
        node_config = InstagramNodeConfig(
            config=config,
            credentials=get_oauth_credential(),
        )
        node = InstagramNode(
            node_id="test_node",
            node_type="automation-instagram",
            node_data={},
            config=node_config,
        )

        # Verify credential fields
        assert isinstance(node_config.credentials, InstagramOAuthCredential)
        assert node_config.credentials.access_token == MOCK_ACCESS_TOKEN
        assert node_config.credentials.instagram_user_id == MOCK_USER_ID
        assert node_config.credentials.email == "test@example.com"

    @pytest.mark.asyncio
    async def test_system_user_credential(self):
        """Test System User Token credential type."""
        config = InstagramGetProfileConfig()
        node_config = InstagramNodeConfig(
            config=config,
            credentials=get_system_user_credential(),
        )
        node = InstagramNode(
            node_id="test_node",
            node_type="automation-instagram",
            node_data={},
            config=node_config,
        )

        # Verify credential fields
        assert isinstance(node_config.credentials, InstagramSystemUserTokenCredential)
        assert node_config.credentials.access_token == MOCK_ACCESS_TOKEN
        assert node_config.credentials.instagram_user_id == MOCK_USER_ID

    @pytest.mark.asyncio
    async def test_page_access_credential(self):
        """Test Page Access Token credential type."""
        config = InstagramGetProfileConfig()
        node_config = InstagramNodeConfig(
            config=config,
            credentials=get_page_access_credential(),
        )
        node = InstagramNode(
            node_id="test_node",
            node_type="automation-instagram",
            node_data={},
            config=node_config,
        )

        # Verify credential fields
        assert isinstance(node_config.credentials, InstagramPageAccessTokenCredential)
        assert node_config.credentials.access_token == MOCK_ACCESS_TOKEN
        assert node_config.credentials.instagram_user_id == MOCK_USER_ID
        assert node_config.credentials.page_id == MOCK_PAGE_ID
        assert node_config.credentials.expires_at is None  # Permanent token


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandlingMock:
    """Test error handling scenarios."""

    @pytest.mark.asyncio
    async def test_api_error_response(self):
        """Test handling of API error responses."""
        config = InstagramGetProfileConfig()
        node_config = InstagramNodeConfig(
            config=config,
            credentials=get_oauth_credential(),
        )
        node = InstagramNode(
            node_id="test_node",
            node_type="automation-instagram",
            node_data={},
            config=node_config,
        )

        mock_error_response = {
            "error": {
                "message": "Invalid OAuth access token",
                "type": "OAuthException",
                "code": 190,
            }
        }

        with mock_async_client(
            create_mock_response(mock_error_response, status_code=400)
        ):
            result = await node.execute({})

        assert result["status"] == "error"
        assert "error" in result

    @pytest.mark.asyncio
    async def test_rate_limit_error(self):
        """Test handling of rate limit errors."""
        config = InstagramGetProfileConfig()
        node_config = InstagramNodeConfig(
            config=config,
            credentials=get_oauth_credential(),
        )
        node = InstagramNode(
            node_id="test_node",
            node_type="automation-instagram",
            node_data={},
            config=node_config,
        )

        mock_error_response = {
            "error": {
                "message": "Rate limit exceeded",
                "type": "OAuthException",
                "code": 4,
            }
        }

        with mock_async_client(
            create_mock_response(mock_error_response, status_code=429)
        ):
            result = await node.execute({})

        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_network_error(self):
        """Test handling of network errors."""
        config = InstagramGetProfileConfig()
        node_config = InstagramNodeConfig(
            config=config,
            credentials=get_oauth_credential(),
        )
        node = InstagramNode(
            node_id="test_node",
            node_type="automation-instagram",
            node_data={},
            config=node_config,
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.side_effect = httpx.NetworkError("Connection failed")
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await node.execute({})

        assert result["status"] == "error"
        assert "error" in result

    @pytest.mark.asyncio
    async def test_invalid_json_response(self):
        """Test handling of invalid JSON responses."""
        config = InstagramGetProfileConfig()
        node_config = InstagramNodeConfig(
            config=config,
            credentials=get_oauth_credential(),
        )
        node = InstagramNode(
            node_id="test_node",
            node_type="automation-instagram",
            node_data={},
            config=node_config,
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 200
            mock_response.json.side_effect = ValueError("Invalid JSON")
            mock_instance.get.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await node.execute({})

        assert result["status"] == "error"


class TestCredentialSchemaVisibility:
    """OAuth is hidden from the credentials UI until Meta approves our OAuth app;
    token methods stay visible and carry acquisition links. Existing OAuth
    credentials must still parse (union membership pins runtime compatibility)."""

    def test_oauth_credential_is_hidden_but_still_parses(self):
        schema = InstagramNode.get_config_schema()
        defs = schema["$defs"]
        assert defs["InstagramOAuthCredential"].get("x-credential-hidden") is True
        # still a valid runtime credential — existing OAuth creds keep executing
        cred = InstagramNodeConfig(
            config=InstagramGetProfileConfig(),
            credentials=get_oauth_credential(),
        ).credentials
        assert isinstance(cred, InstagramOAuthCredential)

    def test_token_credentials_are_visible_with_acquisition_links(self):
        defs = InstagramNode.get_config_schema()["$defs"]
        for title, url in [
            ("InstagramSystemUserTokenCredential", "https://business.facebook.com/settings/system-users"),
            ("InstagramPageAccessTokenCredential", "https://developers.facebook.com/tools/explorer/"),
        ]:
            assert "x-credential-hidden" not in defs[title]
            assert defs[title].get("x-credential-url") == url


# ---------------------------------------------------------------------------
# Instagram Login (Instagram API with Instagram Login) — dual-support
# ---------------------------------------------------------------------------


def get_instagram_login_credential():
    """Instagram Login credential (graph.instagram.com, Page-free)."""
    future_expiry = datetime.now(timezone.utc) + timedelta(days=60)
    return InstagramLoginCredential(
        access_token="ig_login_token",
        instagram_user_id="17841400000000000",
        expires_at=future_expiry.isoformat(),
        instagram_username="demo",
    )


def _capturing_node(config, credentials):
    """Build a node whose httpx client records the request URL + params."""
    node_config = InstagramNodeConfig(config=config, credentials=credentials)
    node = InstagramNode(node_id="n", node_type="automation-instagram",
                         node_data={}, config=node_config)
    captured = {}

    async def capturing_request(method, url, **kwargs):
        captured.update(method=method, url=url, params=kwargs.get("params") or {})
        return create_mock_response({"data": []})

    client = AsyncMock()
    client.request = capturing_request
    acm = MagicMock()
    acm.return_value.__aenter__.return_value = client
    return node, captured, patch("httpx.AsyncClient", acm)


class TestInstagramLoginDualSupport:
    @pytest.mark.asyncio
    async def test_instagram_login_routes_to_graph_instagram_com(self):
        """Instagram Login tokens must hit graph.instagram.com, not graph.facebook.com."""
        node, captured, patcher = _capturing_node(
            InstagramListMediaConfig(), get_instagram_login_credential())
        with patcher:
            result = await node.execute({})
        assert result["status"] == "success"
        assert "graph.instagram.com" in captured["url"]
        assert "graph.facebook.com" not in captured["url"]

    @pytest.mark.asyncio
    async def test_facebook_login_still_routes_to_graph_facebook_com(self):
        """Regression: Facebook-Login tokens keep hitting graph.facebook.com."""
        node, captured, patcher = _capturing_node(
            InstagramListMediaConfig(), get_oauth_credential())
        with patcher:
            result = await node.execute({})
        assert result["status"] == "success"
        assert "graph.facebook.com" in captured["url"]

    @pytest.mark.asyncio
    async def test_facebook_only_op_is_refused_on_instagram_login(self):
        """Hashtag search / product tagging / business discovery don't exist on
        Instagram Login — refuse them with a clear error, not an opaque API 400."""
        node_config = InstagramNodeConfig(
            config=InstagramSearchHashtagConfig(hashtag="fashion"),
            credentials=get_instagram_login_credential())
        node = InstagramNode(node_id="n", node_type="automation-instagram",
                             node_data={}, config=node_config)
        result = await node.execute({})
        assert result["status"] == "error"
        assert result["action"] == "search_hashtag_id"
        assert "Facebook Login" in result["error"]

    @pytest.mark.asyncio
    async def test_facebook_only_op_allowed_on_facebook_login(self):
        """The same op is NOT gated for a Facebook-Login credential."""
        node, captured, patcher = _capturing_node(
            InstagramSearchHashtagConfig(hashtag="fashion"), get_oauth_credential())
        with patcher:
            result = await node.execute({})
        # reaches the API (success from the mock), not the gate
        assert result["status"] == "success"
        assert "graph.facebook.com" in captured["url"]
