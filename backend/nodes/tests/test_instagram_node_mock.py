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
from types import SimpleNamespace
import asyncio
import copy
from urllib.parse import parse_qs
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
    InstagramOnCommentConfig,
    InstagramOnMessageConfig,
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
    InstagramGetCommentConfig,
    InstagramListConversationsConfig,
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
    mock_client.request = AsyncMock(side_effect=mock_any_method)
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
                create_mock_response({"status_code": "FINISHED"}),
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
    @pytest.mark.parametrize("credential_kind", ["login", "oauth", "system", "page"])
    @pytest.mark.parametrize("fields", [None, "id,text,timestamp,from,media"])
    async def test_get_comment_real_transport(self, monkeypatch, credential_kind, fields):
        """Prove routing, authenticated GET and lossless author/media readback."""
        credentials = {
            "login": lambda: InstagramLoginCredential(
                access_token=MOCK_ACCESS_TOKEN, instagram_user_id=MOCK_USER_ID,
                expires_at="2099-01-01T00:00:00Z",
            ),
            "oauth": get_oauth_credential,
            "system": get_system_user_credential,
            "page": get_page_access_credential,
        }[credential_kind]()
        expected = {"id": "17800123456789012", "text": "A controlled comment",
                    "from": {"id": "1300000000000001", "username": "review_tester"},
                    "media": {"id": "18300000000000001"}}
        requests = []
        def transport(request):
            requests.append(request)
            assert request.method == "GET"
            assert request.url.host == ("graph.instagram.com" if credential_kind == "login" else "graph.facebook.com")
            assert request.url.path.endswith("/17800123456789012")
            assert request.url.params["access_token"] == MOCK_ACCESS_TOKEN
            assert request.url.params.get("fields") == fields
            assert request.content == b""
            return httpx.Response(200, json=expected)
        original = httpx.AsyncClient
        monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: original(*a, transport=httpx.MockTransport(transport), **kw))
        node = InstagramNode(node_id="read-comment", node_type="automation-instagram", node_data={},
            config=InstagramNodeConfig(config=InstagramGetCommentConfig(comment_id=expected["id"], fields=fields), credentials=credentials))
        result = await node.execute({})
        assert result["status"] == "success" and result["status_code"] == 200
        assert result["action"] == "get_comment" and result["data"] == expected
        assert len(requests) == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize("participant", [None, "", "  ", "1300000000000001", " 1300000000000001 "])
    async def test_conversation_participant_filter_real_transport(self, monkeypatch, participant):
        requests = []
        expected = {"data": [{"id": "controlled-conversation"}]}
        def transport(request):
            requests.append(request)
            assert request.method == "GET" and request.url.host == "graph.instagram.com"
            assert request.url.path.endswith(f"/{MOCK_USER_ID}/conversations")
            assert request.url.params["platform"] == "instagram"
            assert request.url.params.get("user_id") == ((participant or "").strip() or None)
            assert request.url.params["fields"] == "id,participants,updated_time"
            assert request.url.params["limit"] == "10" and request.url.params["after"] == "cursor-test"
            return httpx.Response(200, json=expected)
        original = httpx.AsyncClient
        monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: original(*a, transport=httpx.MockTransport(transport), **kw))
        credential = InstagramLoginCredential(access_token=MOCK_ACCESS_TOKEN, instagram_user_id=MOCK_USER_ID, expires_at="2099-01-01T00:00:00Z")
        node = InstagramNode(node_id="read-conversation", node_type="automation-instagram", node_data={},
            config=InstagramNodeConfig(config=InstagramListConversationsConfig(user_id=participant, limit=10, after="cursor-test"), credentials=credential))
        result = await node.execute({})
        assert result["status"] == "success" and result["action"] == "list_conversations"
        assert result["data"] == expected and len(requests) == 1

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
        assert "x-credential-preview-flag" not in defs["InstagramOAuthCredential"]
        assert "x-credential-hidden" not in defs["InstagramLoginCredential"]
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


class TestPhotoContainerReadiness:
    """Exercise the real photo handler and HTTP boundary without provider calls."""

    @pytest.fixture
    def photo_node(self):
        return InstagramNode(
            node_id="photo",
            node_type="automation-instagram",
            node_data={},
            config=InstagramNodeConfig(
                config=InstagramPublishPhotoConfig(
                    image_url="https://example.com/photo.jpg", caption="Test photo"
                ),
                credentials=get_instagram_login_credential(),
            ),
        )

    @staticmethod
    def requests(client_factory):
        return client_factory.return_value.__aenter__.return_value.request.await_args_list

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "credentials_factory",
        [get_instagram_login_credential, get_oauth_credential,
         get_system_user_credential, get_page_access_credential],
    )
    @pytest.mark.parametrize("statuses", [["FINISHED"], ["IN_PROGRESS", "FINISHED"]])
    async def test_publishes_once_only_after_finished(
        self, photo_node, credentials_factory, statuses
    ):
        credentials = credentials_factory()
        photo_node.config.credentials = credentials
        responses = [create_mock_response({"id": "container_123"})]
        responses += [create_mock_response({"status_code": status}) for status in statuses]
        responses += [create_mock_response({"id": "media_123"})]
        with (
            mock_async_client(responses) as factory,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await photo_node.execute({})

        requests = self.requests(factory)
        host = (
            "graph.instagram.com"
            if isinstance(credentials, InstagramLoginCredential)
            else "graph.facebook.com"
        )
        assert all(f"https://{host}/" in request.kwargs["url"] for request in requests)
        assert [request.kwargs["method"] for request in requests] == [
            "POST", *(["GET"] * len(statuses)), "POST"
        ]
        assert requests[0].kwargs["url"].endswith(f"/{credentials.instagram_user_id}/media")
        assert requests[0].kwargs["params"]["image_url"] == "https://example.com/photo.jpg"
        assert requests[0].kwargs["params"]["caption"] == "Test photo"
        for request in requests[1:-1]:
            assert request.kwargs["url"].endswith("/container_123")
            assert request.kwargs["params"]["fields"] == "status_code,status"
        assert requests[-1].kwargs["url"].endswith(
            f"/{credentials.instagram_user_id}/media_publish"
        )
        assert requests[-1].kwargs["params"]["creation_id"] == "container_123"
        assert result["status"] == "success"
        assert result["action"] == "publish_photo_post"
        assert result["data"] == {"id": "media_123"}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", ["ERROR", "EXPIRED", "PUBLISHED"])
    @pytest.mark.parametrize("media_kind", ["photo", "video"])
    async def test_terminal_container_never_publishes(self, photo_node, status, media_kind):
        if media_kind == "video":
            photo_node.config.config = InstagramPublishVideoConfig(
                video_url="https://example.com/video.mp4"
            )
        responses = [
            create_mock_response({"id": "container_123"}),
            create_mock_response({"status_code": status}),
        ]
        with mock_async_client(responses) as factory:
            result = await photo_node.execute({})
        assert result["status"] == "error"
        expected_action = "publish_photo_post" if media_kind == "photo" else "publish_video_reel"
        assert result["action"] == expected_action
        assert result["container_id"] == "container_123"
        assert status in result["error"]
        assert "status_poll_total" in result["timing_ms"]
        assert [request.kwargs["method"] for request in self.requests(factory)] == [
            "POST", "GET"
        ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_code", [400, 500])
    async def test_status_request_failure_never_publishes(self, photo_node, status_code):
        responses = [
            create_mock_response({"id": "container_123"}),
            create_mock_response({"error": {"message": "Status lookup failed"}}, status_code),
        ]
        with mock_async_client(responses) as factory:
            result = await photo_node.execute({})
        assert result["status"] == "error"
        assert result["action"] == "publish_photo_post"
        assert result["status_code"] == status_code
        assert result["container_id"] == "container_123"
        assert result["error"] == "Status lookup failed"
        assert [request.kwargs["method"] for request in self.requests(factory)] == [
            "POST", "GET"
        ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", ["IN_PROGRESS", "UNKNOWN", None])
    async def test_processing_timeout_never_publishes_or_recreates(self, photo_node, status):
        elapsed = [0.0]

        async def advance_time(seconds):
            elapsed[0] += seconds

        clock = SimpleNamespace(time=lambda: elapsed[0], monotonic=lambda: elapsed[0])
        responses = [
            create_mock_response({"id": "container_123"}),
            create_mock_response({"status_code": status}),
        ]
        with (
            mock_async_client(responses) as factory,
            patch("nodes.instagram_node.time", clock),
            patch("asyncio.sleep", side_effect=advance_time),
        ):
            result = await photo_node.execute({})
        assert result["status"] == "error"
        assert result["action"] == "publish_photo_post"
        assert result["status_code"] == 408
        assert result["container_id"] == "container_123"
        assert "timed out" in result["error"]
        assert 120 <= elapsed[0] <= 123
        requests = self.requests(factory)
        assert len(requests) == 41  # One creation plus the bounded status polls.
        assert all(request.kwargs["method"] == "GET" for request in requests[1:])

    @pytest.mark.asyncio
    @pytest.mark.parametrize("failure_stage", ["status", "publish"])
    async def test_http_timeout_does_not_retry_write(self, photo_node, failure_stage):
        responses = [create_mock_response({"id": "container_123"})]
        if failure_stage == "publish":
            responses += [create_mock_response({"status_code": "FINISHED"})]
        with mock_async_client(responses) as factory:
            client = factory.return_value.__aenter__.return_value
            client.request.side_effect = [*responses, httpx.ReadTimeout("Synthetic timeout")]
            result = await photo_node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 408
        assert result["container_id"] == "container_123"
        assert len(self.requests(factory)) == len(responses) + 1
        expected_methods = ["POST", "GET"]
        if failure_stage == "publish":
            expected_methods.append("POST")
        assert [request.kwargs["method"] for request in self.requests(factory)] == expected_methods

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_code", [400, 500])
    async def test_publish_failure_does_not_retry_or_recreate(self, photo_node, status_code):
        responses = [
            create_mock_response({"id": "container_123"}),
            create_mock_response({"status_code": "FINISHED"}),
            create_mock_response({"error": {"message": "Publish failed"}}, status_code),
        ]
        with mock_async_client(responses) as factory:
            result = await photo_node.execute({})
        assert result["status"] == "error"
        assert result["error"] == "Publish failed"
        assert result["container_id"] == "container_123"
        assert result["status_code"] == status_code
        assert [request.kwargs["method"] for request in self.requests(factory)] == [
            "POST", "GET", "POST"
        ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_code", [200, 400])
    async def test_failed_container_creation_stops_before_status_or_publish(self, photo_node, status_code):
        payload = {} if status_code == 200 else {"error": {"message": "Creation failed"}}
        with mock_async_client(create_mock_response(payload, status_code)) as factory:
            result = await photo_node.execute({})
        assert result["status"] == "error"
        assert len(self.requests(factory)) == 1
        assert self.requests(factory)[0].kwargs["url"].endswith("/media")


# Signed app-event triggers: all provider calls use real HTTPX serialization
# against MockTransport. No live credentials, Redis, or database are accessed.
TRIGGER_ACCOUNT = "17841400000000001"
TRIGGER_APP = "19461100000000001"
TRIGGER_PRODUCT_APP = "28360000000000001"
TRIGGER_CREDENTIAL_ID = "00000000-0000-4000-8000-000000000001"
TRIGGER_USER = "00000000-0000-4000-8000-000000000002"
TRIGGER_WORKFLOW = "00000000-0000-4000-8000-000000000003"


class _InstagramRegistrationRedis:
    def __init__(self):
        self.values = {}
        self.releases = []

    async def set(self, key, value, *, nx, ex):
        assert nx is True and ex == 90
        if key in self.values:
            return False
        self.values[key] = value
        return True

    async def eval(self, script, count, key, owner):
        assert "get" in script and "del" in script and count == 1
        self.releases.append((key, owner))
        if self.values.get(key) == owner:
            del self.values[key]
            return 1
        return 0


@pytest.fixture
def instagram_registration(monkeypatch):
    state = SimpleNamespace(
        fields=set(), rows={}, requests=[], posts=[], response_app=TRIGGER_APP,
        identity=TRIGGER_ACCOUNT, failure=None, readback_missing=False,
        post_success=True, gate=None, entered=None, redis=_InstagramRegistrationRedis(),
    )
    credential = {
        "credential_type": "instagram_login", "access_token": "synthetic-instagram-token",
        "instagram_user_id": TRIGGER_ACCOUNT, "expires_at": "2099-01-01T00:00:00Z",
    }
    state.credential = credential
    monkeypatch.setenv("INSTAGRAM_CLIENT_ID", TRIGGER_PRODUCT_APP)
    monkeypatch.setattr("utils.instagram_webhooks.require_instagram_webhook_configuration", lambda: TRIGGER_APP)
    monkeypatch.setattr("utils.redis_client.get_shared_redis", lambda: state.redis)
    state.freshen = AsyncMock(side_effect=lambda data, **kwargs: data)
    monkeypatch.setattr(InstagramNode, "freshen_credential", state.freshen)

    async def existing(pool, workflow_id, node_id):
        return copy.deepcopy(state.rows.get((workflow_id, node_id), []))

    async def save(pool, **kwargs):
        state.rows[(kwargs["workflow_id"], kwargs["node_id"])] = [
            dict(provider=kwargs["provider"], tenant_id=kwargs["tenant_id"],
                 credential_id=kwargs["credential_id"], user_id=kwargs["user_id"],
                 event_type=event) for event in kwargs["event_types"]
        ]

    async def delete(pool, workflow_id, node_id):
        state.rows.pop((workflow_id, node_id), None)

    state.save = AsyncMock(side_effect=save)
    monkeypatch.setattr("nodes.core.webhook_subscriptions.get_node_subscriptions", existing)
    monkeypatch.setattr("nodes.core.webhook_subscriptions.save_subscriptions", state.save)
    monkeypatch.setattr("nodes.core.webhook_subscriptions.delete_subscriptions", delete)
    original_client = httpx.AsyncClient

    async def transport(request):
        state.requests.append(request)
        assert request.url.host == "graph.instagram.com"
        assert request.headers["Authorization"] == "Bearer synthetic-instagram-token"
        assert "access_token" not in request.url.params
        if state.failure:
            return state.failure(request)
        if request.url.path.endswith("/me"):
            return httpx.Response(200, json={"user_id": state.identity})
        assert request.url.path.endswith(f"/{TRIGGER_ACCOUNT}/subscribed_apps")
        if request.method == "POST":
            fields = set(parse_qs(request.content.decode())["subscribed_fields"][0].split(","))
            state.posts.append(fields)
            if state.post_success:
                state.fields = fields
            return httpx.Response(200, json={"success": state.post_success})
        assert request.method == "GET"
        if state.gate is not None:
            state.entered.set()
            await state.gate.wait()
        fields = [] if state.readback_missing and state.posts else sorted(state.fields)
        rows = [{"id": state.response_app, "subscribed_fields": fields}] if state.fields else []
        return httpx.Response(200, json={"data": rows})

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: original_client(
        *a, transport=httpx.MockTransport(transport), **kw))

    async def register(operation="on_comment", node_id="ig-comments", **overrides):
        return await InstagramNode.register_node_subscriptions(
            object(), user_id=TRIGGER_USER, workflow_id=TRIGGER_WORKFLOW,
            node_id=node_id, operation=operation,
            credential_id=overrides.get("credential_id", TRIGGER_CREDENTIAL_ID),
            credential=overrides.get("credential", dict(credential)),
            config=overrides.get("config", {"credentialIds": {"instagram_login": TRIGGER_CREDENTIAL_ID}}),
        )
    state.register = register
    return state


class TestInstagramEventRegistration:
    @pytest.mark.asyncio
    async def test_incremental_union_idempotence_and_local_cleanup(self, instagram_registration):
        s = instagram_registration
        s.fields = {"messaging_seen"}
        assert (await s.register()).startswith("Registered — listening")
        assert s.posts == [{"comments", "messaging_seen"}]
        assert s.rows[(TRIGGER_WORKFLOW, "ig-comments")][0]["tenant_id"] == TRIGGER_ACCOUNT
        await s.register("on_message", "ig-messages")
        assert s.posts[-1] == {"comments", "messages", "messaging_seen"}
        assert s.rows[(TRIGGER_WORKFLOW, "ig-messages")][0]["event_type"] == "messages"
        await s.register("on_message", "ig-messages")
        assert len(s.posts) == 2 and s.save.await_count == 2
        before = len(s.requests)
        await InstagramNode.cleanup_external_webhook(object(), TRIGGER_WORKFLOW, "ig-comments", {})
        assert len(s.requests) == before
        assert (TRIGGER_WORKFLOW, "ig-messages") in s.rows
        assert s.fields == {"comments", "messages", "messaging_seen"}
        assert not s.redis.values

    @pytest.mark.asyncio
    @pytest.mark.parametrize("app_id", [TRIGGER_APP, TRIGGER_PRODUCT_APP])
    async def test_known_configured_app_identities_are_verified(self, instagram_registration, app_id):
        s = instagram_registration
        s.response_app = app_id
        await s.register()
        assert s.posts == [{"comments"}]
        assert s.save.await_count == 1

    @pytest.mark.asyncio
    async def test_unknown_existing_app_id_stops_before_write(self, instagram_registration):
        s = instagram_registration
        s.fields = {"messages"}
        s.response_app = "99999999999999999"
        with pytest.raises(ValueError, match="identity"):
            await s.register()
        assert not s.posts and not s.rows and not s.redis.values

    @pytest.mark.asyncio
    async def test_unknown_readback_app_reports_partial_remote_update(self, instagram_registration):
        s = instagram_registration
        s.response_app = "99999999999999999"
        with pytest.raises(ValueError, match="accepted the subscription update") as error:
            await s.register()
        assert "remote fields may have changed" in str(error.value)
        assert "existing fields were not changed" not in str(error.value)
        assert s.posts == [{"comments"}] and s.fields == {"comments"}
        assert not s.rows and not s.redis.values
        s.save.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("case", [
        "invalid_data", "invalid_row", "invalid_paging", "missing_cursor",
        "invalid_cursor", "repeated_cursor", "page_bound", "ambiguous_app", "invalid_fields",
    ])
    async def test_incomplete_subscription_listing_never_overwrites_fields(self, instagram_registration, case):
        s = instagram_registration
        pages = []

        def response(request):
            if request.url.path.endswith("/me"):
                return httpx.Response(200, json={"user_id": TRIGGER_ACCOUNT})
            assert request.method == "GET"
            pages.append(dict(request.url.params))
            body = {"data": [{"id": TRIGGER_APP, "subscribed_fields": ["messages"]}]}
            if case == "invalid_data": body["data"] = {}
            elif case == "invalid_row": body["data"] = ["not-a-row"]
            elif case == "invalid_paging": body["paging"] = ["invalid"]
            elif case == "ambiguous_app": body["data"].append({"id": TRIGGER_PRODUCT_APP, "subscribed_fields": []})
            elif case == "invalid_fields": body["data"][0]["subscribed_fields"] = "messages"
            else:
                cursor = len(pages) if case == "invalid_cursor" else f"cursor-{len(pages)}"
                if case == "repeated_cursor": cursor = "same-cursor"
                body["paging"] = {"next": "https://untrusted.example/not-followed", "cursors": {"after": cursor}}
                if case == "missing_cursor": body["paging"].pop("cursors")
            return httpx.Response(200, json=body)

        s.failure = response
        with pytest.raises(ValueError):
            await s.register()
        assert not s.posts and not s.rows and not s.redis.values
        assert len(pages) == (5 if case == "page_bound" else 2 if case == "repeated_cursor" else 1)
        if len(pages) > 1:
            assert pages[1]["after"] == ("same-cursor" if case == "repeated_cursor" else "cursor-1")

    @pytest.mark.asyncio
    async def test_subscription_listing_combines_pages_without_following_urls(self, instagram_registration):
        s = instagram_registration
        seen = []

        def response(request):
            seen.append(request)
            if "after" not in request.url.params:
                return httpx.Response(200, json={"data": [{"id": "99999999999999999", "subscribed_fields": ["messages"]}],
                    "paging": {"next": "https://untrusted.example/not-followed", "cursors": {"after": "page-2"}}})
            assert request.url.params["after"] == "page-2"
            return httpx.Response(200, json={"data": [{"id": TRIGGER_APP, "subscribed_fields": ["comments", "messaging_seen"]}]})

        s.failure = response
        async with httpx.AsyncClient(headers={"Authorization": "Bearer synthetic-instagram-token"}) as client:
            fields = await InstagramNode._read_subscribed_fields(client, TRIGGER_ACCOUNT, TRIGGER_APP)
        assert fields == {"comments", "messaging_seen"}
        assert len(seen) == 2 and all(r.url.host == "graph.instagram.com" for r in seen)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("identity", ["99999999999999999", None])
    async def test_account_mismatch_stops_before_subscription(self, instagram_registration, identity):
        s = instagram_registration
        s.identity = identity
        with pytest.raises(ValueError, match="identity"):
            await s.register()
        assert len(s.requests) == 1 and not s.rows and not s.redis.values

    @pytest.mark.asyncio
    @pytest.mark.parametrize("kind", ["instagram_oauth", "instagram_system_user_token", None])
    async def test_legacy_or_untagged_credentials_never_register(self, instagram_registration, kind):
        s = instagram_registration
        credential = dict(s.credential, credential_type=kind)
        with pytest.raises(ValueError, match="Instagram Login"):
            await s.register(credential=credential)
        assert not s.requests and not s.rows

    @pytest.mark.asyncio
    async def test_ambiguous_binding_never_registers(self, instagram_registration):
        s = instagram_registration
        with pytest.raises(ValueError, match="exactly one"):
            await s.register(config={"credentialIds": {
                "instagram_login": TRIGGER_CREDENTIAL_ID,
                "instagram_oauth": "00000000-0000-4000-8000-000000000009",
            }})
        assert not s.requests and not s.rows

    @pytest.mark.asyncio
    async def test_unready_callback_stops_before_refresh_or_http(self, instagram_registration, monkeypatch):
        s = instagram_registration
        def unready():
            raise ValueError("Callback configuration incomplete")
        monkeypatch.setattr("utils.instagram_webhooks.require_instagram_webhook_configuration", unready)
        with pytest.raises(ValueError, match="Callback"):
            await s.register()
        assert s.freshen.await_count == 0 and not s.requests and not s.rows

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [400, 401, 429, 500])
    async def test_http_failures_do_not_save_rows_or_leak_provider_body(self, instagram_registration, status):
        s = instagram_registration
        s.failure = lambda request: httpx.Response(status, json={"error": {"message": "SECRET-SENTINEL"}})
        with pytest.raises(ValueError) as exc:
            await s.register()
        assert "SECRET-SENTINEL" not in str(exc.value)
        assert len(s.requests) == 1 and not s.rows

    @pytest.mark.asyncio
    @pytest.mark.parametrize("body", [{"success": False}, {"error": {"message": "SECRET-SENTINEL"}}, []])
    async def test_http_200_error_or_false_subscription_never_saves(self, instagram_registration, body):
        s = instagram_registration
        if body == {"success": False}:
            s.post_success = False
        else:
            s.failure = lambda request: httpx.Response(200, json=body)
        with pytest.raises(ValueError):
            await s.register()
        assert not s.rows and not s.redis.values

    @pytest.mark.asyncio
    async def test_readback_failure_preserves_remote_subscription_without_active_rows(self, instagram_registration):
        s = instagram_registration
        s.readback_missing = True
        with pytest.raises(ValueError, match="readback"):
            await s.register()
        assert s.fields == {"comments"} and not s.rows
        assert not any(r.method == "DELETE" for r in s.requests)

    @pytest.mark.asyncio
    async def test_contention_then_retry_preserves_both_event_fields(self, instagram_registration):
        s = instagram_registration
        s.gate, s.entered = asyncio.Event(), asyncio.Event()
        first = asyncio.create_task(s.register())
        await asyncio.wait_for(s.entered.wait(), timeout=1)
        try:
            with pytest.raises(ValueError, match="already in progress"):
                await s.register("on_message", "ig-messages")
        finally:
            s.gate.set()
            await first
        await s.register("on_message", "ig-messages")
        assert s.posts == [{"comments"}, {"comments", "messages"}]
        assert len(s.rows) == 2 and not s.redis.values

    @pytest.mark.asyncio
    async def test_transport_error_redacts_request_url(self, instagram_registration):
        s = instagram_registration
        def fail(request):
            raise httpx.ReadError("request SECRET-SENTINEL", request=request)
        s.failure = fail
        with pytest.raises(ValueError) as exc:
            await s.register()
        assert "SECRET-SENTINEL" not in str(exc.value) and not s.rows

    @pytest.mark.asyncio
    async def test_lock_outage_fails_closed(self, instagram_registration, monkeypatch):
        s = instagram_registration
        monkeypatch.setattr("utils.redis_client.get_shared_redis", lambda: None)
        with pytest.raises(ValueError, match="lock is unavailable"):
            await s.register()
        assert not s.posts and not s.rows

    @pytest.mark.asyncio
    async def test_lease_does_not_release_a_replacement_owner(self, instagram_registration):
        s = instagram_registration
        async with InstagramNode._registration_lease(TRIGGER_ACCOUNT, TRIGGER_APP):
            key = next(iter(s.redis.values))
            s.redis.values[key] = "replacement-owner"
        assert s.redis.values[key] == "replacement-owner"

    @pytest.mark.asyncio
    async def test_canceled_registration_releases_lease_without_local_activation(self, instagram_registration):
        s = instagram_registration
        s.gate, s.entered = asyncio.Event(), asyncio.Event()
        registration = asyncio.create_task(s.register())
        await asyncio.wait_for(s.entered.wait(), timeout=1)
        registration.cancel()
        with pytest.raises(asyncio.CancelledError):
            await registration
        assert not s.redis.values and not s.rows and not s.posts

    @pytest.mark.asyncio
    async def test_registration_freshens_credential_before_provider_call(self, instagram_registration):
        s = instagram_registration
        await s.register()
        s.freshen.assert_awaited_once()
        assert s.freshen.await_args.kwargs["credential_id"] == TRIGGER_CREDENTIAL_ID

    @pytest.mark.asyncio
    @pytest.mark.parametrize("unready", [False, True])
    async def test_panel_provisioning_uses_shared_core_and_truthful_status(self, instagram_registration, monkeypatch, unready):
        s = instagram_registration
        load = AsyncMock(return_value=s.credential)
        monkeypatch.setattr("utils.credential_loader.load_credential", load)
        monkeypatch.setattr("utils.webhook_manager._load_workflow_owner_and_nodes", AsyncMock(return_value=(TRIGGER_USER, [])))
        if unready:
            def unavailable():
                raise ValueError("Callback configuration incomplete")
            monkeypatch.setattr("utils.instagram_webhooks.require_instagram_webhook_configuration", unavailable)
        result = await InstagramNode.load_field_value(
            "subscription_status", TRIGGER_USER, TRIGGER_WORKFLOW, "ig-comments", object(),
            context={"operation": "on_comment", "media_id": "18300000000000001"},
            credential_ids={"instagram_login": TRIGGER_CREDENTIAL_ID},
        )
        assert load.await_args.args[2] == TRIGGER_CREDENTIAL_ID
        assert result["values"]["trigger_registered"] is (not unready)
        if unready:
            assert "Callback configuration incomplete" in result["values"]["trigger_error"]
            assert not s.requests and not s.rows
        else:
            assert result["values"]["trigger_error"] is None
            assert result["values"]["subscription_status"].startswith("Registered — listening")
            assert "filtered" in result["values"]["subscription_status"]
            assert s.rows[(TRIGGER_WORKFLOW, "ig-comments")][0]["user_id"] == TRIGGER_USER


def _instagram_event(kind="comments"):
    data = ({"id": "17900000000000001", "text": "Controlled review comment",
             "from": {"id": "10000000000000001", "username": "reviewer"},
             "media": {"id": "18300000000000001"}} if kind == "comments" else
            {"sender": {"id": "10000000000000001"}, "recipient": {"id": TRIGGER_ACCOUNT},
             "message": {"mid": "synthetic-message-id", "text": "Controlled review message"}})
    return {"object": "instagram", "account_id": TRIGGER_ACCOUNT,
            "event_type": kind, "event_id": f"{TRIGGER_ACCOUNT}:{kind}:synthetic",
            "timestamp": 1788790000, "data": data}


class TestInstagramEventOutputs:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("config", [InstagramOnCommentConfig(), InstagramOnMessageConfig()])
    async def test_manual_run_has_no_event_or_http_and_halts_downstream(self, config):
        credential = InstagramLoginCredential(
            access_token="synthetic-only", instagram_user_id=TRIGGER_ACCOUNT,
            expires_at="2099-01-01T00:00:00Z",
        )
        node = InstagramNode("ig", "automation-instagram", {}, InstagramNodeConfig(config=config, credentials=credential))
        with patch("httpx.AsyncClient", side_effect=AssertionError("manual trigger must not contact provider")):
            result = await node.run({})
        assert result["status"] == "no_event" and result["data"] == {}
        assert node.trigger_produced_no_event(result)
        assert not node.manual_run_replays_last_event

    @pytest.mark.parametrize("kind,operation", [("comments", "on_comment"), ("messages", "on_message")])
    def test_normalized_outputs_preserve_exact_reply_guard_ids(self, kind, operation):
        payload = _instagram_event(kind)
        result = InstagramNode.resolve_trigger_payload(payload, {"operation": operation})
        assert result["status"] == "success" and result["account_id"] == TRIGGER_ACCOUNT
        assert result["data"] == payload["data"] and result["event_id"] == payload["event_id"]
        if kind == "comments":
            assert result["comment_id"] == payload["data"]["id"]
            assert result["media_id"] == payload["data"]["media"]["id"]
            assert result["author_id"] == "10000000000000001"
        else:
            assert result["sender_id"] == "10000000000000001"
            assert result["message_id"] == "synthetic-message-id"
            assert result["recipient_id"] == TRIGGER_ACCOUNT

    def test_official_username_only_comment_does_not_invent_author_id(self):
        payload = _instagram_event()
        payload["data"]["from"].pop("id")
        result = InstagramNode.resolve_trigger_payload(payload, {"operation": "on_comment"})
        assert result["author_id"] is None
        assert result["author_username"] == "reviewer"
        assert result["comment_id"] == payload["data"]["id"]
        assert result["media_id"] == payload["data"]["media"]["id"]

    @pytest.mark.parametrize("author", [{}, {"username": " "}, {"username": 123}])
    def test_comment_without_any_author_identity_fails_closed(self, author):
        payload = _instagram_event()
        payload["data"]["from"] = author
        with pytest.raises(ValueError, match="author identity"):
            InstagramNode.resolve_trigger_payload(payload, {"operation": "on_comment"})

    @pytest.mark.parametrize("case", ["echo", "wrong_recipient", "self", "missing_mid", "sender_filter"])
    def test_message_scope_errors_fail_closed(self, case):
        payload = _instagram_event("messages")
        config = {"operation": "on_message"}
        if case == "echo": payload["data"]["message"]["is_echo"] = True
        elif case == "wrong_recipient": payload["data"]["recipient"]["id"] = "99999999999999999"
        elif case == "self": payload["data"]["sender"]["id"] = TRIGGER_ACCOUNT
        elif case == "missing_mid": payload["data"]["message"].pop("mid")
        else: config["sender_id"] = "99999999999999999"
        with pytest.raises(ValueError):
            InstagramNode.resolve_trigger_payload(payload, config)

    @pytest.mark.parametrize("case", ["self", "media_filter", "missing_author", "wrong_operation"])
    def test_comment_scope_errors_fail_closed(self, case):
        payload = _instagram_event()
        config = {"operation": "on_comment"}
        if case == "self": payload["data"]["from"]["id"] = TRIGGER_ACCOUNT
        elif case == "media_filter": config["media_id"] = "99999999999999999"
        elif case == "missing_author": payload["data"].pop("from")
        else: config["operation"] = "on_message"
        with pytest.raises(ValueError):
            InstagramNode.resolve_trigger_payload(payload, config)

    @pytest.mark.parametrize("mapping", [
        {}, {"instagram_oauth": TRIGGER_CREDENTIAL_ID},
        {"instagram_login": TRIGGER_CREDENTIAL_ID, "instagram_oauth": "other"},
        {"instagram_login": TRIGGER_CREDENTIAL_ID, "credential_type": "instagram_oauth"},
        {"instagram_login": "{{unresolved}}"}, {"instagram_login": "not-a-uuid"},
    ])
    def test_unsupported_and_ambiguous_trigger_credential_maps(self, mapping):
        assert InstagramNode._pick_trigger_credential_id(mapping) is None

    def test_valid_trigger_map_and_schema(self):
        assert InstagramNode._pick_trigger_credential_id({"instagram_login": TRIGGER_CREDENTIAL_ID}) == TRIGGER_CREDENTIAL_ID
        schema = InstagramNode.get_config_schema()
        for name, operation in [("InstagramOnCommentConfig", "on_comment"), ("InstagramOnMessageConfig", "on_message")]:
            fields = schema["$defs"][name]["properties"]
            assert fields["operation"]["const"] == operation
            assert fields["operation"]["x-is-trigger"] is True
            assert fields["subscription_status"]["ui:loadValue"] is True
            assert "webhook_url" not in fields

    @pytest.mark.parametrize("operation,capability", [
        ("on_comment", "instagram_business_manage_comments"),
        ("on_message", "instagram_business_manage_messages"),
    ])
    def test_trigger_scope_map_uses_only_the_selected_instagram_login_capability(self, operation, capability):
        from nodes.scopes.meta import _INSTAGRAM_REQUIREMENTS
        assert _INSTAGRAM_REQUIREMENTS[operation].scopes == ("instagram_business_basic", capability)
