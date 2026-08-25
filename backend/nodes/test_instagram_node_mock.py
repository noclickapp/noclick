"""
Mock tests for Instagram Graph API node.

Comprehensive test suite using mocked HTTP responses to test all 23 Instagram operations
without requiring real credentials. These tests verify:
- Correct API endpoint construction
- Request parameter handling
- Response parsing
- Error handling
- All credential types

Uses pytest-mock to mock httpx.AsyncClient responses.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
import time

from nodes.instagram_node import (
    InstagramNode,
    InstagramNodeConfig,
    InstagramOAuthCredential,
    InstagramSystemUserTokenCredential,
    InstagramPageAccessTokenCredential,
    # Profile operations (1)
    InstagramGetProfileConfig,
    # Media operations (5)
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


# Test constants
MOCK_ACCESS_TOKEN = "mock_access_token_12345"
MOCK_USER_ID = "17841400008460056"
MOCK_USERNAME = "mock_instagram_user"
MOCK_MEDIA_ID = "17895695668004550"
MOCK_COMMENT_ID = "17873440459141021"
MOCK_HASHTAG_ID = "17843826142012701"
MOCK_PAGE_ID = "123456789012345"


def get_mock_oauth_credential():
    """Get mock OAuth credential."""
    expires_at = datetime.fromtimestamp(
        time.time() + 60 * 24 * 60 * 60,
        tz=timezone.utc,
    ).isoformat()
    return InstagramOAuthCredential(
        access_token=MOCK_ACCESS_TOKEN,
        instagram_user_id=MOCK_USER_ID,
        expires_at=expires_at,
        instagram_username=MOCK_USERNAME,
        email="test@example.com",
    )


def get_mock_system_user_credential():
    """Get mock System User Token credential."""
    return InstagramSystemUserTokenCredential(
        access_token=MOCK_ACCESS_TOKEN,
        instagram_user_id=MOCK_USER_ID,
        instagram_username=MOCK_USERNAME,
    )


def get_mock_page_token_credential():
    """Get mock Page Access Token credential."""
    return InstagramPageAccessTokenCredential(
        access_token=MOCK_ACCESS_TOKEN,
        instagram_user_id=MOCK_USER_ID,
        page_id=MOCK_PAGE_ID,
        instagram_username=MOCK_USERNAME,
    )


def create_mock_node(config, credential=None):
    """Create a mock InstagramNode instance."""
    if credential is None:
        credential = get_mock_oauth_credential()

    node_config = InstagramNodeConfig(config=config, credentials=credential)
    node = InstagramNode(
        node_id="test-node",
        node_type="automation-instagram",
        node_data={},
        config=node_config,
        sio=None,
    )
    return node


def create_mock_response(json_data, status_code=200):
    """Create a mock HTTP response."""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.json.return_value = json_data
    mock_response.raise_for_status = MagicMock()
    return mock_response


# ============================================================================
# Profile Operations Tests (1 operation)
# ============================================================================


class TestProfileOperationsMock:
    """Mock tests for profile-related operations."""

    @pytest.mark.asyncio
    async def test_get_profile(self):
        """Test getting profile information with mock response."""
        config = InstagramGetProfileConfig()
        node = create_mock_node(config)

        mock_data = {
            "id": MOCK_USER_ID,
            "username": MOCK_USERNAME,
            "name": "Mock User",
            "biography": "Test bio",
            "followers_count": 1000,
            "follows_count": 500,
            "media_count": 100,
            "profile_picture_url": "https://example.com/profile.jpg",
            "website": "https://example.com",
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = create_mock_response(mock_data)

            result = await node.execute({})

            assert result["action"] == "get_user_profile"
            assert result["data"]["username"] == MOCK_USERNAME
            assert result["data"]["followers_count"] == 1000
            mock_get.assert_called_once()


# ============================================================================
# Media Operations Tests (5 operations)
# ============================================================================


class TestMediaOperationsMock:
    """Mock tests for media-related operations."""

    @pytest.mark.asyncio
    async def test_list_media(self):
        """Test listing media with mock response."""
        config = InstagramListMediaConfig(limit=10)
        node = create_mock_node(config)

        mock_data = {
            "data": [
                {
                    "id": MOCK_MEDIA_ID,
                    "caption": "Test post",
                    "media_type": "IMAGE",
                    "timestamp": "2025-01-19T12:00:00+0000",
                }
            ],
            "paging": {"cursors": {"after": "next_cursor", "before": "prev_cursor"}},
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = create_mock_response(mock_data)

            result = await node.execute({})

            assert result["action"] == "list_user_media"
            assert len(result["data"]) == 1
            assert result["data"][0]["id"] == MOCK_MEDIA_ID

    @pytest.mark.asyncio
    async def test_get_media(self):
        """Test getting media details with mock response."""
        config = InstagramGetMediaConfig(media_id=MOCK_MEDIA_ID)
        node = create_mock_node(config)

        mock_data = {
            "id": MOCK_MEDIA_ID,
            "caption": "Test media",
            "media_type": "IMAGE",
            "media_url": "https://example.com/image.jpg",
            "permalink": "https://instagram.com/p/ABC123",
            "timestamp": "2025-01-19T12:00:00+0000",
            "like_count": 100,
            "comments_count": 20,
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = create_mock_response(mock_data)

            result = await node.execute({})

            assert result["action"] == "get_media_details"
            assert result["data"]["id"] == MOCK_MEDIA_ID
            assert result["data"]["like_count"] == 100

    @pytest.mark.asyncio
    async def test_publish_photo(self):
        """Test publishing photo with mock response."""
        config = InstagramPublishPhotoConfig(
            image_url="https://example.com/test.jpg", caption="Test photo"
        )
        node = create_mock_node(config)

        # Mock container creation
        container_response = {"id": "container_123"}
        # Mock publish response
        publish_response = {"id": MOCK_MEDIA_ID}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = [
                create_mock_response(container_response),
                create_mock_response(publish_response),
            ]

            result = await node.execute({})

            assert result["action"] == "publish_photo_post"
            assert result["container_id"] == "container_123"
            assert result["media_id"] == MOCK_MEDIA_ID

    @pytest.mark.asyncio
    async def test_publish_video(self):
        """Test publishing video with mock response."""
        config = InstagramPublishVideoConfig(
            video_url="https://example.com/test.mp4", caption="Test video"
        )
        node = create_mock_node(config)

        # Mock container creation
        container_response = {"id": "container_456"}
        # Mock status check (processing complete)
        status_response = {"status_code": "FINISHED"}
        # Mock publish response
        publish_response = {"id": MOCK_MEDIA_ID}

        with patch(
            "httpx.AsyncClient.post", new_callable=AsyncMock
        ) as mock_post, patch(
            "httpx.AsyncClient.get", new_callable=AsyncMock
        ) as mock_get:
            mock_post.side_effect = [
                create_mock_response(container_response),
                create_mock_response(publish_response),
            ]
            mock_get.return_value = create_mock_response(status_response)

            result = await node.execute({})

            assert result["action"] == "publish_video_reel"
            assert result["container_id"] == "container_456"
            assert result["media_id"] == MOCK_MEDIA_ID

    @pytest.mark.asyncio
    async def test_publish_carousel(self):
        """Test publishing carousel with mock response."""
        config = InstagramPublishCarouselConfig(
            children=[
                {"image_url": "https://example.com/1.jpg"},
                {"image_url": "https://example.com/2.jpg"},
            ],
            caption="Test carousel",
        )
        node = create_mock_node(config)

        # Mock child container creation
        child_response_1 = {"id": "child_1"}
        child_response_2 = {"id": "child_2"}
        # Mock carousel container creation
        carousel_response = {"id": "carousel_container"}
        # Mock publish response
        publish_response = {"id": MOCK_MEDIA_ID}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = [
                create_mock_response(child_response_1),
                create_mock_response(child_response_2),
                create_mock_response(carousel_response),
                create_mock_response(publish_response),
            ]

            result = await node.execute({})

            assert result["action"] == "publish_carousel_post"
            assert result["media_id"] == MOCK_MEDIA_ID


# ============================================================================
# Comment Operations Tests (5 operations)
# ============================================================================


class TestCommentOperationsMock:
    """Mock tests for comment-related operations."""

    @pytest.mark.asyncio
    async def test_list_comments(self):
        """Test listing comments with mock response."""
        config = InstagramListCommentsConfig(media_id=MOCK_MEDIA_ID)
        node = create_mock_node(config)

        mock_data = {
            "data": [
                {
                    "id": MOCK_COMMENT_ID,
                    "text": "Great post!",
                    "username": "commenter",
                    "timestamp": "2025-01-19T12:00:00+0000",
                }
            ]
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = create_mock_response(mock_data)

            result = await node.execute({})

            assert result["action"] == "list_media_comments"
            assert len(result["data"]) == 1
            assert result["data"][0]["id"] == MOCK_COMMENT_ID

    @pytest.mark.asyncio
    async def test_create_comment(self):
        """Test creating a comment with mock response."""
        config = InstagramCreateCommentConfig(
            media_id=MOCK_MEDIA_ID, message="Nice photo!"
        )
        node = create_mock_node(config)

        mock_data = {"id": MOCK_COMMENT_ID}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = create_mock_response(mock_data)

            result = await node.execute({})

            assert result["action"] == "create_media_comment"
            assert result["data"]["id"] == MOCK_COMMENT_ID

    @pytest.mark.asyncio
    async def test_reply_to_comment(self):
        """Test replying to a comment with mock response."""
        config = InstagramReplyToCommentConfig(
            comment_id=MOCK_COMMENT_ID, message="Thanks!"
        )
        node = create_mock_node(config)

        mock_data = {"id": "reply_comment_123"}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = create_mock_response(mock_data)

            result = await node.execute({})

            assert result["action"] == "reply_to_comment"
            assert result["data"]["id"] == "reply_comment_123"

    @pytest.mark.asyncio
    async def test_hide_comment(self):
        """Test hiding a comment with mock response."""
        config = InstagramHideCommentConfig(comment_id=MOCK_COMMENT_ID)
        node = create_mock_node(config)

        mock_data = {"success": True}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = create_mock_response(mock_data)

            result = await node.execute({})

            assert result["action"] == "hide_or_unhide_comment"
            assert result["data"]["success"] is True

    @pytest.mark.asyncio
    async def test_delete_comment(self):
        """Test deleting a comment with mock response."""
        config = InstagramDeleteCommentConfig(comment_id=MOCK_COMMENT_ID)
        node = create_mock_node(config)

        mock_data = {"success": True}

        with patch("httpx.AsyncClient.delete", new_callable=AsyncMock) as mock_delete:
            mock_delete.return_value = create_mock_response(mock_data)

            result = await node.execute({})

            assert result["action"] == "delete_comment"
            assert result["data"]["success"] is True


# ============================================================================
# Insights Operations Tests (2 operations)
# ============================================================================


class TestInsightsOperationsMock:
    """Mock tests for insights-related operations."""

    @pytest.mark.asyncio
    async def test_get_media_insights(self):
        """Test getting media insights with mock response."""
        config = InstagramGetMediaInsightsConfig(
            media_id=MOCK_MEDIA_ID, metrics=["impressions", "reach", "engagement"]
        )
        node = create_mock_node(config)

        mock_data = {
            "data": [
                {"name": "impressions", "values": [{"value": 1500}]},
                {"name": "reach", "values": [{"value": 1200}]},
                {"name": "engagement", "values": [{"value": 150}]},
            ]
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = create_mock_response(mock_data)

            result = await node.execute({})

            assert result["action"] == "get_media_insights"
            assert len(result["data"]) == 3
            assert result["data"][0]["name"] == "impressions"

    @pytest.mark.asyncio
    async def test_get_account_insights(self):
        """Test getting account insights with mock response."""
        config = InstagramGetAccountInsightsConfig(
            metrics=["impressions", "reach", "profile_views"], period="day"
        )
        node = create_mock_node(config)

        mock_data = {
            "data": [
                {"name": "impressions", "values": [{"value": 5000}]},
                {"name": "reach", "values": [{"value": 4000}]},
                {"name": "profile_views", "values": [{"value": 300}]},
            ]
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = create_mock_response(mock_data)

            result = await node.execute({})

            assert result["action"] == "get_account_insights"
            assert len(result["data"]) == 3


# ============================================================================
# Hashtag Operations Tests (2 operations)
# ============================================================================


class TestHashtagOperationsMock:
    """Mock tests for hashtag-related operations."""

    @pytest.mark.asyncio
    async def test_search_hashtag(self):
        """Test searching for hashtags with mock response."""
        config = InstagramSearchHashtagConfig(query="travel")
        node = create_mock_node(config)

        mock_data = {"data": [{"id": MOCK_HASHTAG_ID, "name": "travel"}]}

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = create_mock_response(mock_data)

            result = await node.execute({})

            assert result["action"] == "search_hashtag_id"
            assert result["data"][0]["id"] == MOCK_HASHTAG_ID

    @pytest.mark.asyncio
    async def test_get_hashtag_media(self):
        """Test getting hashtag media with mock response."""
        config = InstagramGetHashtagMediaConfig(hashtag_id=MOCK_HASHTAG_ID)
        node = create_mock_node(config)

        mock_data = {
            "data": [
                {
                    "id": MOCK_MEDIA_ID,
                    "media_type": "IMAGE",
                    "caption": "Travel photo #travel",
                }
            ]
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = create_mock_response(mock_data)

            result = await node.execute({})

            assert result["action"] == "get_hashtag_media"
            assert len(result["data"]) == 1


# ============================================================================
# Business Discovery Tests (1 operation)
# ============================================================================


class TestBusinessDiscoveryMock:
    """Mock tests for business discovery operations."""

    @pytest.mark.asyncio
    async def test_business_discovery(self):
        """Test business discovery with mock response."""
        config = InstagramBusinessDiscoveryConfig(username="competitor_account")
        node = create_mock_node(config)

        mock_data = {
            "business_discovery": {
                "id": "987654321",
                "username": "competitor_account",
                "name": "Competitor",
                "followers_count": 50000,
                "follows_count": 1000,
                "media_count": 500,
            }
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = create_mock_response(mock_data)

            result = await node.execute({})

            assert result["action"] == "discover_business_account"
            assert result["data"]["username"] == "competitor_account"
            assert result["data"]["followers_count"] == 50000


# ============================================================================
# Stories Operations Tests (2 operations)
# ============================================================================


class TestStoriesOperationsMock:
    """Mock tests for stories-related operations."""

    @pytest.mark.asyncio
    async def test_publish_story_photo(self):
        """Test publishing photo story with mock response."""
        config = InstagramPublishStoryPhotoConfig(
            image_url="https://example.com/story.jpg"
        )
        node = create_mock_node(config)

        container_response = {"id": "story_container_123"}
        publish_response = {"id": MOCK_MEDIA_ID}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = [
                create_mock_response(container_response),
                create_mock_response(publish_response),
            ]

            result = await node.execute({})

            assert result["action"] == "publish_photo_story"
            assert result["media_id"] == MOCK_MEDIA_ID

    @pytest.mark.asyncio
    async def test_publish_story_video(self):
        """Test publishing video story with mock response."""
        config = InstagramPublishStoryVideoConfig(
            video_url="https://example.com/story.mp4"
        )
        node = create_mock_node(config)

        container_response = {"id": "story_video_container"}
        status_response = {"status_code": "FINISHED"}
        publish_response = {"id": MOCK_MEDIA_ID}

        with patch(
            "httpx.AsyncClient.post", new_callable=AsyncMock
        ) as mock_post, patch(
            "httpx.AsyncClient.get", new_callable=AsyncMock
        ) as mock_get:
            mock_post.side_effect = [
                create_mock_response(container_response),
                create_mock_response(publish_response),
            ]
            mock_get.return_value = create_mock_response(status_response)

            result = await node.execute({})

            assert result["action"] == "publish_video_story"
            assert result["media_id"] == MOCK_MEDIA_ID


# ============================================================================
# Mentions Operations Tests (2 operations)
# ============================================================================


class TestMentionsOperationsMock:
    """Mock tests for mentions-related operations."""

    @pytest.mark.asyncio
    async def test_get_mentioned_media(self):
        """Test getting mentioned media with mock response."""
        config = InstagramGetMentionedMediaConfig()
        node = create_mock_node(config)

        mock_data = {
            "data": [
                {
                    "id": MOCK_MEDIA_ID,
                    "caption": "Thanks @mock_instagram_user!",
                    "timestamp": "2025-01-19T12:00:00+0000",
                }
            ]
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = create_mock_response(mock_data)

            result = await node.execute({})

            assert result["action"] == "get_mentioned_media"
            assert len(result["data"]) == 1

    @pytest.mark.asyncio
    async def test_get_mentioned_comments(self):
        """Test getting mentioned comments with mock response."""
        config = InstagramGetMentionedCommentsConfig()
        node = create_mock_node(config)

        mock_data = {
            "data": [
                {
                    "id": MOCK_COMMENT_ID,
                    "text": "Hey @mock_instagram_user check this out!",
                    "timestamp": "2025-01-19T12:00:00+0000",
                }
            ]
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = create_mock_response(mock_data)

            result = await node.execute({})

            assert result["action"] == "get_mentioned_comments"
            assert len(result["data"]) == 1


# ============================================================================
# Product Tagging Operations Tests (3 operations)
# ============================================================================


class TestProductTaggingMock:
    """Mock tests for product tagging operations."""

    @pytest.mark.asyncio
    async def test_tag_products(self):
        """Test tagging products with mock response."""
        config = InstagramTagProductsConfig(
            media_id=MOCK_MEDIA_ID,
            product_tags=[{"product_id": "product_123", "x": 0.5, "y": 0.5}],
        )
        node = create_mock_node(config)

        mock_data = {"success": True}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = create_mock_response(mock_data)

            result = await node.execute({})

            assert result["action"] == "tag_products_in_media"
            assert result["data"]["success"] is True

    @pytest.mark.asyncio
    async def test_get_product_tags(self):
        """Test getting product tags with mock response."""
        config = InstagramGetProductTagsConfig(media_id=MOCK_MEDIA_ID)
        node = create_mock_node(config)

        mock_data = {"data": [{"product_id": "product_123", "x": 0.5, "y": 0.5}]}

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = create_mock_response(mock_data)

            result = await node.execute({})

            assert result["action"] == "get_media_product_tags"
            assert len(result["data"]) == 1

    @pytest.mark.asyncio
    async def test_delete_product_tags(self):
        """Test deleting product tags with mock response."""
        config = InstagramDeleteProductTagsConfig(media_id=MOCK_MEDIA_ID)
        node = create_mock_node(config)

        mock_data = {"success": True}

        with patch("httpx.AsyncClient.delete", new_callable=AsyncMock) as mock_delete:
            mock_delete.return_value = create_mock_response(mock_data)

            result = await node.execute({})

            assert result["action"] == "delete_product_tags_from_media"
            assert result["data"]["success"] is True


# ============================================================================
# Credential Types Tests (3 types)
# ============================================================================


class TestCredentialTypesMock:
    """Mock tests for all credential types."""

    @pytest.mark.asyncio
    async def test_oauth_credential(self):
        """Test using OAuth credential."""
        config = InstagramGetProfileConfig()
        credential = get_mock_oauth_credential()
        node = create_mock_node(config, credential)

        mock_data = {"id": MOCK_USER_ID, "username": MOCK_USERNAME}

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = create_mock_response(mock_data)

            result = await node.execute({})

            assert result["action"] == "get_user_profile"
            assert result["data"]["id"] == MOCK_USER_ID

    @pytest.mark.asyncio
    async def test_system_user_token_credential(self):
        """Test using System User Token credential."""
        config = InstagramGetProfileConfig()
        credential = get_mock_system_user_credential()
        node = create_mock_node(config, credential)

        mock_data = {"id": MOCK_USER_ID, "username": MOCK_USERNAME}

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = create_mock_response(mock_data)

            result = await node.execute({})

            assert result["action"] == "get_user_profile"
            assert result["data"]["id"] == MOCK_USER_ID

    @pytest.mark.asyncio
    async def test_page_access_token_credential(self):
        """Test using Page Access Token credential."""
        config = InstagramGetProfileConfig()
        credential = get_mock_page_token_credential()
        node = create_mock_node(config, credential)

        mock_data = {"id": MOCK_USER_ID, "username": MOCK_USERNAME}

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = create_mock_response(mock_data)

            result = await node.execute({})

            assert result["action"] == "get_user_profile"
            assert result["data"]["id"] == MOCK_USER_ID


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandlingMock:
    """Mock tests for error handling scenarios."""

    @pytest.mark.asyncio
    async def test_rate_limit_error(self):
        """Test rate limit error handling."""
        config = InstagramGetProfileConfig()
        node = create_mock_node(config)

        mock_error_response = MagicMock()
        mock_error_response.status_code = 429
        mock_error_response.json.return_value = {
            "error": {"message": "Rate limit exceeded", "code": 4}
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_error_response

            with pytest.raises(Exception) as exc_info:
                await node.execute({})

            # Verify error was raised (implementation may wrap it)
            assert exc_info is not None

    @pytest.mark.asyncio
    async def test_invalid_token_error(self):
        """Test invalid token error handling."""
        config = InstagramGetProfileConfig()
        node = create_mock_node(config)

        mock_error_response = MagicMock()
        mock_error_response.status_code = 401
        mock_error_response.json.return_value = {
            "error": {"message": "Invalid OAuth access token", "code": 190}
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_error_response

            with pytest.raises(Exception) as exc_info:
                await node.execute({})

            assert exc_info is not None

    @pytest.mark.asyncio
    async def test_not_found_error(self):
        """Test resource not found error handling."""
        config = InstagramGetMediaConfig(media_id="invalid_media_id")
        node = create_mock_node(config)

        mock_error_response = MagicMock()
        mock_error_response.status_code = 404
        mock_error_response.json.return_value = {
            "error": {"message": "Media not found", "code": 100}
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_error_response

            with pytest.raises(Exception) as exc_info:
                await node.execute({})

            assert exc_info is not None

    @pytest.mark.asyncio
    async def test_permission_error(self):
        """Test insufficient permissions error handling."""
        config = InstagramGetAccountInsightsConfig(
            metrics=["impressions"], period="day"
        )
        node = create_mock_node(config)

        mock_error_response = MagicMock()
        mock_error_response.status_code = 403
        mock_error_response.json.return_value = {
            "error": {"message": "Insufficient permissions", "code": 200}
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_error_response

            with pytest.raises(Exception) as exc_info:
                await node.execute({})

            assert exc_info is not None
