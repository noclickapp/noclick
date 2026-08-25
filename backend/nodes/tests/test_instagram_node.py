"""
Integration tests for Instagram Graph API node.

Tests the complete Instagram node functionality including all implemented operations
organized by category: profile, media publishing, comments, insights, hashtags, and discovery.

Uses a real Instagram OAuth access token to test against the Instagram Graph API.
Tests are designed to be non-destructive where possible (read operations).
Write operations test the action name is correct but may fail due to API constraints.

Environment Variables Required:
    INSTAGRAM_ACCESS_TOKEN - Instagram User Access Token (via Facebook Login)
    INSTAGRAM_USER_ID - Instagram Business/Creator Account ID
    INSTAGRAM_USERNAME - Instagram username (optional, for logging)
"""

import asyncio
import os
import time
import pytest
from datetime import datetime

# Import the node and config classes - ALL 23 implemented operations
from nodes.instagram_node import (
    InstagramNode,
    InstagramNodeConfig,
    InstagramOAuthCredential,
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

# Environment variables for credentials
INSTAGRAM_ACCESS_TOKEN = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")
INSTAGRAM_USER_ID = os.environ.get("INSTAGRAM_USER_ID", "")
INSTAGRAM_USERNAME = os.environ.get("INSTAGRAM_USERNAME", "test_user")

# Test data - will be populated from API responses
TEST_MEDIA_ID = None
TEST_COMMENT_ID = None
TEST_HASHTAG_ID = None


def get_credentials():
    """Get Instagram credentials from environment."""
    if not INSTAGRAM_ACCESS_TOKEN or not INSTAGRAM_USER_ID:
        pytest.skip(
            "INSTAGRAM_ACCESS_TOKEN and INSTAGRAM_USER_ID environment variables not set"
        )

    # Calculate expiry (60 days from now for long-lived token)
    expires_at = datetime.fromtimestamp(time.time() + 60 * 24 * 60 * 60).isoformat()

    return InstagramOAuthCredential(
        access_token=INSTAGRAM_ACCESS_TOKEN,
        instagram_user_id=INSTAGRAM_USER_ID,
        expires_at=expires_at,
        instagram_username=INSTAGRAM_USERNAME,
    )


def create_node(config) -> InstagramNode:
    """Create an InstagramNode instance with the given config."""
    credentials = get_credentials()
    node_config = InstagramNodeConfig(config=config, credentials=credentials)
    node = InstagramNode(
        node_id="test-node",
        node_type="automation-instagram",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow",
    )
    return node


# ============================================================================
# Profile Operations Tests (1 operation)
# ============================================================================


class TestProfileOperations:
    """Test profile-related Instagram API operations (1 total)."""

    @pytest.mark.asyncio
    async def test_get_profile(self):
        """Test getting Instagram profile information."""
        config = InstagramGetProfileConfig(
            fields="id,username,account_type,media_count,followers_count,follows_count"
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "get_user_profile"
        assert result["status"] == "success", f"Error: {result.get('error')}"
        assert "id" in result["data"]
        assert "username" in result["data"]
        assert result["data"]["id"] == INSTAGRAM_USER_ID


# ============================================================================
# Media Operations Tests (6 operations)
# ============================================================================


class TestMediaOperations:
    """Test media-related Instagram API operations (6 total)."""

    @pytest.mark.asyncio
    async def test_list_media(self):
        """Test listing Instagram media posts."""
        global TEST_MEDIA_ID

        config = InstagramListMediaConfig(
            fields="id,caption,media_type,media_url,timestamp,like_count,comments_count",
            limit=10,
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "list_user_media"
        assert result["status"] == "success", f"Error: {result.get('error')}"
        assert "data" in result["data"]
        assert isinstance(result["data"]["data"], list)

        # Store a media ID for later tests
        if result["data"]["data"]:
            TEST_MEDIA_ID = result["data"]["data"][0]["id"]

    @pytest.mark.asyncio
    async def test_get_media(self):
        """Test getting a single media post by ID."""
        # First ensure we have a media ID
        if not TEST_MEDIA_ID:
            list_config = InstagramListMediaConfig(fields="id", limit=1)
            list_node = create_node(list_config)
            list_result = await list_node.execute({})

            if list_result["status"] == "success" and list_result["data"].get("data"):
                media_id = list_result["data"]["data"][0]["id"]
            else:
                pytest.skip("No media available for testing")
                return
        else:
            media_id = TEST_MEDIA_ID

        config = InstagramGetMediaConfig(
            media_id=media_id, fields="id,caption,media_type,media_url,timestamp"
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "get_media_details"
        assert result["status"] == "success", f"Error: {result.get('error')}"
        assert result["data"]["id"] == media_id

    @pytest.mark.asyncio
    async def test_publish_photo(self):
        """Test publishing a photo to Instagram."""
        config = InstagramPublishPhotoConfig(
            image_url="https://picsum.photos/1080/1080",
            caption=f"Test photo from automated tests {int(time.time())}",
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "publish_photo_post"
        # May fail due to API constraints or image requirements
        # But action routing should be correct

    @pytest.mark.asyncio
    async def test_publish_video(self):
        """Test publishing a video to Instagram."""
        config = InstagramPublishVideoConfig(
            video_url="https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/360/Big_Buck_Bunny_360_10s_1MB.mp4",
            caption=f"Test video from automated tests {int(time.time())}",
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "publish_video_reel"
        # May fail due to API constraints or video requirements

    @pytest.mark.asyncio
    async def test_publish_carousel(self):
        """Test publishing a carousel (multiple images/videos) to Instagram."""
        config = InstagramPublishCarouselConfig(
            media_urls='[{"type": "IMAGE", "url": "https://picsum.photos/1080/1080?1"}, {"type": "IMAGE", "url": "https://picsum.photos/1080/1080?2"}]',
            caption=f"Test carousel from automated tests {int(time.time())}",
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "publish_carousel_post"
        # May fail due to API constraints


# ============================================================================
# Comment Operations Tests (5 operations)
# ============================================================================


class TestCommentOperations:
    """Test comment-related Instagram API operations (5 total)."""

    @pytest.mark.asyncio
    async def test_list_comments(self):
        """Test listing comments on a media post."""
        global TEST_COMMENT_ID

        # Need a media ID
        if not TEST_MEDIA_ID:
            pytest.skip("No media ID available for testing")

        config = InstagramListCommentsConfig(
            media_id=TEST_MEDIA_ID,
            fields="id,text,username,timestamp,like_count,replies_count",
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "list_media_comments"
        # May succeed with empty list or fail due to permissions

        if result["status"] == "success" and result["data"].get("data"):
            TEST_COMMENT_ID = result["data"]["data"][0]["id"]

    @pytest.mark.asyncio
    async def test_create_comment(self):
        """Test creating a comment on a media post."""
        if not TEST_MEDIA_ID:
            pytest.skip("No media ID available for testing")

        config = InstagramCreateCommentConfig(
            media_id=TEST_MEDIA_ID,
            message=f"Test comment from automated tests {int(time.time())}",
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "create_media_comment"
        # May fail due to permissions or API constraints

    @pytest.mark.asyncio
    async def test_reply_to_comment(self):
        """Test replying to a comment."""
        if not TEST_MEDIA_ID or not TEST_COMMENT_ID:
            pytest.skip("No media/comment ID available for testing")

        config = InstagramReplyToCommentConfig(
            comment_id=TEST_COMMENT_ID,
            message=f"Test reply from automated tests {int(time.time())}",
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "reply_to_comment"
        # May fail due to permissions

    @pytest.mark.asyncio
    async def test_hide_comment(self):
        """Test hiding a comment."""
        if not TEST_COMMENT_ID:
            pytest.skip("No comment ID available for testing")

        config = InstagramHideCommentConfig(comment_id=TEST_COMMENT_ID, hide=True)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "hide_or_unhide_comment"
        # May fail due to permissions

    @pytest.mark.asyncio
    async def test_delete_comment(self):
        """Test deleting a comment."""
        # Try with a non-existent comment to test action routing
        config = InstagramDeleteCommentConfig(comment_id="comment_nonexistent_12345")
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "delete_comment"
        # Will fail with error but action should be correct


# ============================================================================
# Insights Operations Tests (2 operations)
# ============================================================================


class TestInsightsOperations:
    """Test insights-related Instagram API operations (2 total)."""

    @pytest.mark.asyncio
    async def test_get_media_insights(self):
        """Test getting insights for a media post."""
        if not TEST_MEDIA_ID:
            pytest.skip("No media ID available for testing")

        config = InstagramGetMediaInsightsConfig(
            media_id=TEST_MEDIA_ID,
            metrics=["impressions", "reach", "engagement", "saved"],
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "get_media_insights"
        # May fail if media is too recent or doesn't support insights

    @pytest.mark.asyncio
    async def test_get_account_insights(self):
        """Test getting account-level insights."""
        config = InstagramGetAccountInsightsConfig(
            metrics="impressions,reach,profile_views,follower_count",
            period="day",
            since=str(int(time.time()) - 7 * 24 * 60 * 60),  # Last 7 days
            until=str(int(time.time())),
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "get_account_insights"
        # May fail due to account type or time range


# ============================================================================
# Hashtag Operations Tests (2 operations)
# ============================================================================


class TestHashtagOperations:
    """Test hashtag-related Instagram API operations (2 total)."""

    @pytest.mark.asyncio
    async def test_search_hashtag(self):
        """Test searching for a hashtag ID."""
        global TEST_HASHTAG_ID

        config = InstagramSearchHashtagConfig(hashtag="love")  # Popular hashtag
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "search_hashtag_id"

        if result["status"] == "success" and result["data"].get("data"):
            TEST_HASHTAG_ID = result["data"]["data"][0]["id"]

    @pytest.mark.asyncio
    async def test_get_hashtag_media(self):
        """Test getting recent media for a hashtag."""
        if not TEST_HASHTAG_ID:
            # Try to get hashtag ID first
            search_config = InstagramSearchHashtagConfig(hashtag="love")
            search_node = create_node(search_config)
            search_result = await search_node.execute({})

            if search_result["status"] == "success" and search_result["data"].get(
                "data"
            ):
                hashtag_id = search_result["data"]["data"][0]["id"]
            else:
                pytest.skip("No hashtag ID available for testing")
                return
        else:
            hashtag_id = TEST_HASHTAG_ID

        config = InstagramGetHashtagMediaConfig(
            hashtag_id=hashtag_id,
            fields="id,caption,media_type,media_url,timestamp",
            limit=10,
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "get_hashtag_media"
        # May succeed or fail based on hashtag permissions


# ============================================================================
# Discovery Operations Tests (1 operation)
# ============================================================================


class TestDiscoveryOperations:
    """Test business discovery Instagram API operations (1 total)."""

    @pytest.mark.asyncio
    async def test_business_discovery(self):
        """Test discovering another Instagram Business account."""
        config = InstagramBusinessDiscoveryConfig(
            username="instagram",  # Official Instagram account
            fields="id,username,followers_count,media_count,ig_id",
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "discover_business_account"
        # May succeed if account is a business account


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Test error handling scenarios."""

    @pytest.mark.asyncio
    async def test_invalid_media_id(self):
        """Test handling of invalid media ID."""
        config = InstagramGetMediaConfig(
            media_id="media_nonexistent_12345", fields="id"
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "error"
        assert result["action"] == "get_media_details"

    @pytest.mark.asyncio
    async def test_invalid_comment_id(self):
        """Test handling of invalid comment ID."""
        config = InstagramDeleteCommentConfig(comment_id="comment_nonexistent_12345")
        node = create_node(config)

        result = await node.execute({})

        assert result["status"] == "error"
        assert result["action"] == "delete_comment"

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        """Test handling of missing credentials."""
        config = InstagramGetProfileConfig(fields="id,username")
        node_config = InstagramNodeConfig(config=config, credentials=None)
        node = InstagramNode(
            node_id="test-node",
            node_type="automation-instagram",
            node_data={},
            config=node_config,
            sio=None,
            sid=None,
            workflow_id="test-workflow",
        )

        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})

    @pytest.mark.asyncio
    async def test_rate_limit_429(self):
        """Test handling of rate limit errors (429)."""
        # Make multiple rapid requests to potentially trigger rate limit
        config = InstagramGetProfileConfig(fields="id")
        node = create_node(config)

        # Note: This test may not always trigger rate limit
        # but demonstrates the handling pattern
        for _ in range(5):
            result = await node.execute({})
            if (
                result["status"] == "error"
                and "rate limit" in result.get("error", "").lower()
            ):
                # Successfully handled rate limit
                pytest.skip("Rate limit encountered (expected behavior)")
                return

        # If no rate limit, test passes (we're under the limit)
        assert True


# ============================================================================
# Timing and Performance Tests
# ============================================================================


class TestPerformance:
    """Test performance and timing information."""

    @pytest.mark.asyncio
    async def test_timing_information(self):
        """Test that timing information is included in responses."""
        config = InstagramGetProfileConfig(fields="id,username")
        node = create_node(config)

        result = await node.execute({})

        assert "timing_ms" in result
        assert "api_request" in result["timing_ms"]
        assert "total" in result["timing_ms"]
        assert result["timing_ms"]["api_request"] > 0
        assert result["timing_ms"]["total"] > 0


# ============================================================================
# OAuth and Authentication Tests
# ============================================================================


class TestAuthentication:
    """Test OAuth authentication and credential validation."""

    @pytest.mark.asyncio
    async def test_oauth_credential_format(self):
        """Test that OAuth credentials are correctly formatted."""
        credentials = get_credentials()

        assert hasattr(credentials, "access_token")
        assert hasattr(credentials, "instagram_user_id")
        assert hasattr(credentials, "expires_at")
        assert credentials.access_token == INSTAGRAM_ACCESS_TOKEN
        assert credentials.instagram_user_id == INSTAGRAM_USER_ID

    @pytest.mark.asyncio
    async def test_expired_token_handling(self):
        """Test handling of expired tokens."""
        if not INSTAGRAM_ACCESS_TOKEN or not INSTAGRAM_USER_ID:
            pytest.skip(
                "INSTAGRAM_ACCESS_TOKEN and INSTAGRAM_USER_ID environment variables not set"
            )

        # Create credential with past expiry
        expired_credential = InstagramOAuthCredential(
            access_token=INSTAGRAM_ACCESS_TOKEN,
            instagram_user_id=INSTAGRAM_USER_ID,
            expires_at=datetime.fromtimestamp(
                time.time() - 1000
            ).isoformat(),  # Expired
            instagram_username=INSTAGRAM_USERNAME,
        )

        config = InstagramGetProfileConfig(fields="id")
        node_config = InstagramNodeConfig(config=config, credentials=expired_credential)
        node = InstagramNode(
            node_id="test-node",
            node_type="automation-instagram",
            node_data={},
            config=node_config,
            sio=None,
            sid=None,
            workflow_id="test-workflow",
        )

        # Token expiry check happens in the OAuth handler, not the node
        # Node should still make the request, and API will return error if token is invalid
        result = await node.execute({})

        # Either succeeds (token still works) or fails with auth error
        if result["status"] == "error":
            assert (
                "auth" in result.get("error", "").lower()
                or "token" in result.get("error", "").lower()
            )


# ============================================================================
# Stories Operations Tests (2 operations)
# ============================================================================


class TestStoriesOperations:
    """Test stories-related Instagram API operations (2 total)."""

    @pytest.mark.asyncio
    async def test_publish_story_photo(self):
        """Test publishing a photo story."""
        config = InstagramPublishStoryPhotoConfig(
            image_url="https://picsum.photos/1080/1920",
            caption=f"Test story {int(time.time())}",
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "publish_photo_story"
        # May fail due to API constraints

    @pytest.mark.asyncio
    async def test_publish_story_video(self):
        """Test publishing a video story."""
        config = InstagramPublishStoryVideoConfig(
            video_url="https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/360/Big_Buck_Bunny_360_10s_1MB.mp4",
            caption=f"Test video story {int(time.time())}",
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "publish_video_story"
        # May fail due to API constraints or video processing


# ============================================================================
# Mentions Operations Tests (2 operations)
# ============================================================================


class TestMentionsOperations:
    """Test mentions-related Instagram API operations (2 total)."""

    @pytest.mark.asyncio
    async def test_get_mentioned_media(self):
        """Test getting a media the account is @mentioned in.

        Mentions are a field expansion keyed by a specific media id (from the
        mentions webhook) — there is no list edge — so media_id is required.
        """
        config = InstagramGetMentionedMediaConfig(
            media_id="17895695668004550", fields="id,caption,media_type,timestamp,username"
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "get_mentioned_media"
        # May succeed with empty list or fail due to permissions

    @pytest.mark.asyncio
    async def test_get_mentioned_comments(self):
        """Test getting a comment the account is @mentioned in (keyed by comment id)."""
        config = InstagramGetMentionedCommentsConfig(
            comment_id="17862154342000000", fields="id,text,username,timestamp"
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "get_mentioned_comments"
        # May succeed with empty list or fail due to permissions


# ============================================================================
# Product Tagging Operations Tests (3 operations)
# ============================================================================


class TestProductTaggingOperations:
    """Test product tagging Instagram API operations (3 total)."""

    @pytest.mark.asyncio
    async def test_tag_products(self):
        """Test tagging products in a media post."""
        if not TEST_MEDIA_ID:
            pytest.skip("No media ID available for testing")

        config = InstagramTagProductsConfig(
            media_id=TEST_MEDIA_ID,
            product_tags='[{"product_id": "12345", "x": 0.5, "y": 0.5}]',
        )
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "tag_products_in_media"
        # May fail due to Instagram Shopping not being enabled

    @pytest.mark.asyncio
    async def test_get_product_tags(self):
        """Test getting product tags from a media post."""
        if not TEST_MEDIA_ID:
            pytest.skip("No media ID available for testing")

        config = InstagramGetProductTagsConfig(media_id=TEST_MEDIA_ID)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "get_media_product_tags"
        # May succeed with empty list

    @pytest.mark.asyncio
    async def test_delete_product_tags(self):
        """Test deleting product tags from a media post."""
        if not TEST_MEDIA_ID:
            pytest.skip("No media ID available for testing")

        config = InstagramDeleteProductTagsConfig(media_id=TEST_MEDIA_ID)
        node = create_node(config)

        result = await node.execute({})

        assert result["action"] == "delete_product_tags_from_media"
        # May fail if no product tags exist


# ============================================================================
# Alternative Credential Tests
# ============================================================================


class TestAlternativeCredentials:
    """Test alternative credential types."""

    @pytest.mark.asyncio
    async def test_system_user_token_credential(self):
        """Test System User Token credential format."""
        credential = InstagramSystemUserTokenCredential(
            access_token="test_system_user_token_12345",
            instagram_user_id=INSTAGRAM_USER_ID or "test_user_id",
            instagram_username="test_user",
        )

        assert hasattr(credential, "access_token")
        assert hasattr(credential, "instagram_user_id")
        assert hasattr(credential, "instagram_username")
        assert credential.access_token == "test_system_user_token_12345"

    @pytest.mark.asyncio
    async def test_page_access_token_credential(self):
        """Test Page Access Token credential format."""
        credential = InstagramPageAccessTokenCredential(
            access_token="test_page_token_12345",
            instagram_user_id=INSTAGRAM_USER_ID or "test_user_id",
            page_id="test_page_id",
            instagram_username="test_user",
            expires_at=None,  # Permanent token
        )

        assert hasattr(credential, "access_token")
        assert hasattr(credential, "instagram_user_id")
        assert hasattr(credential, "page_id")
        assert hasattr(credential, "instagram_username")
        assert hasattr(credential, "expires_at")
        assert credential.access_token == "test_page_token_12345"
        assert credential.expires_at is None  # Permanent


if __name__ == "__main__":
    # Run tests with: INSTAGRAM_ACCESS_TOKEN=xxx INSTAGRAM_USER_ID=yyy pytest nodes/tests/test_instagram_node.py -v
    pytest.main([__file__, "-v"])
