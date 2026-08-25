"""
Unit tests for YouTube API node using mocked responses.

Tests the complete YouTube Data API v3 node functionality with mocked HTTP responses.
No real API calls are made - all responses are simulated.

This allows tests to run in CI without API keys and without creating real data.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from utils.ssrf import SSRFError

# Import the node and config classes
from nodes.youtube_node import (
    YouTubeNode,
    YouTubeNodeConfig,
    YouTubeOAuthCredential,
    # Video operations
    YouTubeListVideosConfig,
    YouTubeListPopularVideosConfig,
    YouTubeListMyRatedVideosConfig,
    YouTubeGetVideoConfig,
    YouTubeUpdateVideoConfig,
    YouTubeDeleteVideoConfig,
    YouTubeRateVideoConfig,
    YouTubeGetVideoRatingConfig,
    YouTubeUploadVideoConfig,
    YouTubeSetThumbnailConfig,
    # Channel operations
    YouTubeListChannelsConfig,
    YouTubeGetMyChannelConfig,
    YouTubeUpdateChannelConfig,
    # Playlist operations
    YouTubeListMyPlaylistsConfig,
    YouTubeListPlaylistsByIdConfig,
    YouTubeListChannelPlaylistsConfig,
    YouTubeGetPlaylistConfig,
    YouTubeCreatePlaylistConfig,
    YouTubeUpdatePlaylistConfig,
    YouTubeDeletePlaylistConfig,
    # Playlist items operations
    YouTubeListPlaylistItemsConfig,
    YouTubeAddPlaylistItemConfig,
    YouTubeUpdatePlaylistItemConfig,
    YouTubeDeletePlaylistItemConfig,
    # Search
    YouTubeSearchConfig,
    # Comment operations
    YouTubeListCommentRepliesConfig,
    YouTubeListCommentsByIdConfig,
    YouTubeListVideoCommentsConfig,
    YouTubeListChannelCommentsConfig,
    YouTubeCreateCommentConfig,
    YouTubeCreateVideoCommentConfig,
    YouTubeCreateChannelCommentConfig,
    YouTubeUpdateCommentConfig,
    YouTubeDeleteCommentConfig,
    YouTubeSetCommentModerationConfig,
    # Subscription operations
    YouTubeListSubscriptionsConfig,
    YouTubeSubscribeConfig,
    YouTubeUnsubscribeConfig,
    # Caption operations
    YouTubeListCaptionsConfig,
    YouTubeDownloadCaptionConfig,
    # Activity operations
    YouTubeListMyActivitiesConfig,
    YouTubeListChannelActivitiesConfig,
    # Category and localization operations
    YouTubeListVideoCategoriesConfig,
    YouTubeListLanguagesConfig,
    YouTubeListRegionsConfig,
    # Channel sections
    YouTubeListMyChannelSectionsConfig,
    YouTubeListChannelSectionsConfig,
    # Members
    YouTubeListMembersConfig,
    YouTubeListMembershipLevelsConfig,
    # Analytics API
    YouTubeGetChannelAnalyticsConfig,
    YouTubeGetVideoAnalyticsConfig,
    YouTubeGetRevenueAnalyticsConfig,
    YouTubeGetTopVideosConfig,
    YouTubeGetDemographicsConfig,
    YouTubeGetTrafficSourcesConfig,
    # Reporting API
    YouTubeListReportTypesConfig,
    YouTubeCreateReportingJobConfig,
    YouTubeListReportingJobsConfig,
    YouTubeGetReportingJobConfig,
    YouTubeDeleteReportingJobConfig,
    YouTubeListReportsConfig,
    # Live Broadcasts
    YouTubeListBroadcastsConfig,
    YouTubeCreateBroadcastConfig,
    YouTubeUpdateBroadcastConfig,
    YouTubeDeleteBroadcastConfig,
    YouTubeTransitionBroadcastConfig,
    YouTubeBindBroadcastConfig,
    # Live Streams
    YouTubeListStreamsConfig,
    YouTubeCreateStreamConfig,
    YouTubeUpdateStreamConfig,
    YouTubeDeleteStreamConfig,
    # Live Chat
    YouTubeListLiveChatMessagesConfig,
    YouTubeSendLiveChatMessageConfig,
    YouTubeDeleteLiveChatMessageConfig,
    YouTubeListLiveChatModeratorsConfig,
    YouTubeAddLiveChatModeratorConfig,
    YouTubeRemoveLiveChatModeratorConfig,
    YouTubeBanLiveChatUserConfig,
    YouTubeUnbanLiveChatUserConfig,
    YouTubeListSuperChatEventsConfig,
)


# ============================================================================
# Mock Response Factory
# ============================================================================


def mock_api_response(data: dict, status_code: int = 200):
    """Create a mock httpx response with the given data."""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.json.return_value = data
    mock_response.text = str(data)
    return mock_response


def mock_api_delete_response():
    """Create a mock httpx response for DELETE (204 No Content)."""
    mock_response = MagicMock()
    mock_response.status_code = 204
    mock_response.text = ""
    return mock_response


def mock_api_error(message: str, status_code: int = 400):
    """Create a mock httpx error response."""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.json.return_value = {"error": {"message": message}}
    mock_response.text = f'{{"error": {{"message": "{message}"}}}}'
    return mock_response


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def mock_credentials():
    """Create mock OAuth credentials."""
    return YouTubeOAuthCredential(
        access_token="mock_access_token",
        refresh_token="mock_refresh_token",
        expires_at="2099-12-31T23:59:59Z",  # Far future to avoid refresh
        email="test@example.com",
    )


def create_node(config, credentials=None) -> YouTubeNode:
    """Create a YouTubeNode instance with the given config."""
    if credentials is None:
        credentials = YouTubeOAuthCredential(
            access_token="mock_access_token",
            refresh_token="mock_refresh_token",
            expires_at="2099-12-31T23:59:59Z",
            email="test@example.com",
        )
    node_config = YouTubeNodeConfig(config=config, credentials=credentials)
    node = YouTubeNode(
        node_id="test-node",
        node_type="automation-youtube",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow",
    )
    return node


# ============================================================================
# Video Operations Tests
# ============================================================================


class TestVideoOperations:
    """Test video-related YouTube API operations."""

    @pytest.mark.asyncio
    async def test_list_videos(self):
        """Test listing videos."""
        config = YouTubeListVideosConfig(video_ids="video1,video2", max_results=10)
        node = create_node(config)

        mock_data = {
            "items": [
                {
                    "id": "video1",
                    "snippet": {"title": "Video 1"},
                    "statistics": {"viewCount": "1000"},
                },
                {
                    "id": "video2",
                    "snippet": {"title": "Video 2"},
                    "statistics": {"viewCount": "2000"},
                },
            ],
            "pageInfo": {"totalResults": 2},
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "list_videos_by_id"
        assert len(result["items"]) == 2
        assert result["items"][0]["snippet"]["title"] == "Video 1"

    @pytest.mark.asyncio
    async def test_get_video(self):
        """Test getting a single video."""
        config = YouTubeGetVideoConfig(video_id="video123")
        node = create_node(config)

        mock_data = {
            "items": [
                {
                    "id": "video123",
                    "snippet": {"title": "Test Video", "description": "A test video"},
                }
            ]
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "get_video"
        assert result["video"]["id"] == "video123"
        assert result["video"]["snippet"]["title"] == "Test Video"

    @pytest.mark.asyncio
    async def test_update_video(self):
        """Test updating video metadata."""
        config = YouTubeUpdateVideoConfig(
            video_id="video123",
            title="Updated Title",
            description="Updated description",
        )
        node = create_node(config)

        # Mock get video response
        get_mock_data = {
            "items": [
                {
                    "id": "video123",
                    "snippet": {"title": "Old Title", "categoryId": "22"},
                    "status": {"privacyStatus": "public"},
                }
            ]
        }

        # Mock update response
        update_mock_data = {
            "id": "video123",
            "snippet": {"title": "Updated Title", "description": "Updated description"},
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, patch(
            "httpx.AsyncClient.put", new_callable=AsyncMock
        ) as mock_put:
            mock_get.return_value = mock_api_response(get_mock_data)
            mock_put.return_value = mock_api_response(update_mock_data)
            result = await node.execute({})

        assert result["action"] == "update_video_metadata"
        assert result["video"]["snippet"]["title"] == "Updated Title"

    @pytest.mark.asyncio
    async def test_delete_video(self):
        """Test deleting a video."""
        config = YouTubeDeleteVideoConfig(video_id="video123")
        node = create_node(config)

        with patch("httpx.AsyncClient.delete", new_callable=AsyncMock) as mock_delete:
            mock_delete.return_value = mock_api_delete_response()
            result = await node.execute({})

        assert result["action"] == "delete_video"
        assert result["success"] is True
        assert result["video_id"] == "video123"

    @pytest.mark.asyncio
    async def test_rate_video(self):
        """Test rating a video."""
        config = YouTubeRateVideoConfig(video_id="video123", rating="like")
        node = create_node(config)

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_api_delete_response()  # Rating returns 204
            result = await node.execute({})

        assert result["action"] == "rate_video"
        assert result["success"] is True
        assert result["rating"] == "like"

    @pytest.mark.asyncio
    async def test_get_video_rating(self):
        """Test getting video ratings."""
        config = YouTubeGetVideoRatingConfig(video_ids="video1,video2")
        node = create_node(config)

        mock_data = {
            "items": [
                {"videoId": "video1", "rating": "like"},
                {"videoId": "video2", "rating": "none"},
            ]
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "get_user_video_ratings"
        assert len(result["items"]) == 2

    @pytest.mark.parametrize(
        "resumable_url",
        [
            "https://attacker.example/upload/youtube/v3/videos?upload_id=abc",
            "https://evil.www.googleapis.com/upload/youtube/v3/videos?upload_id=abc",
            "https://www.googleapis.com.attacker.example/upload/youtube/v3/videos?upload_id=abc",
            "https://attacker@www.googleapis.com/upload/youtube/v3/videos?upload_id=abc",
        ],
    )
    @pytest.mark.asyncio
    async def test_upload_video_rejects_non_google_resumable_origins(
        self, resumable_url
    ):
        from nodes.core.media_resolver import ResolvedMedia

        config = YouTubeUploadVideoConfig(video_url="resource-id", title="Video")
        node = create_node(config)
        resolved = ResolvedMedia(
            data=b"video", mime_type="video/mp4", filename="video.mp4"
        )
        init_response = mock_api_response({})
        init_response.headers = {"Location": resumable_url}

        with patch(
            "nodes.core.media_resolver.resolve_media_input",
            new=AsyncMock(return_value=resolved),
        ), patch(
            "httpx.AsyncClient.post",
            new_callable=AsyncMock,
            return_value=init_response,
        ), patch("httpx.AsyncClient.put", new_callable=AsyncMock) as put:
            with pytest.raises(SSRFError, match="outside"):
                await node._upload_video(config, "oauth-token")

        put.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_upload_video_accepts_official_google_resumable_origin(self):
        from nodes.core.media_resolver import ResolvedMedia

        config = YouTubeUploadVideoConfig(video_url="resource-id", title="Video")
        node = create_node(config)
        resolved = ResolvedMedia(
            data=b"video", mime_type="video/mp4", filename="video.mp4"
        )
        init_response = mock_api_response({})
        init_response.headers = {
            "Location": (
                "https://www.googleapis.com/upload/youtube/v3/videos"
                "?uploadType=resumable&upload_id=abc"
            )
        }
        upload_response = mock_api_response({"id": "video-id"}, status_code=201)

        with patch(
            "nodes.core.media_resolver.resolve_media_input",
            new=AsyncMock(return_value=resolved),
        ), patch(
            "httpx.AsyncClient.post",
            new_callable=AsyncMock,
            return_value=init_response,
        ), patch(
            "httpx.AsyncClient.put",
            new_callable=AsyncMock,
            return_value=upload_response,
        ) as put:
            result = await node._upload_video(config, "oauth-token")

        assert result["video_id"] == "video-id"
        assert put.await_args.args[0].startswith("https://www.googleapis.com/")
        assert put.await_args.kwargs["headers"]["Authorization"] == "Bearer oauth-token"


# ============================================================================
# Channel Operations Tests
# ============================================================================


class TestChannelOperations:
    """Test channel-related YouTube API operations."""

    @pytest.mark.asyncio
    async def test_list_channels(self):
        """Test listing channels."""
        config = YouTubeListChannelsConfig(channel_ids="channel1,channel2")
        node = create_node(config)

        mock_data = {
            "items": [
                {
                    "id": "channel1",
                    "snippet": {"title": "Channel 1"},
                    "statistics": {"subscriberCount": "1000"},
                },
                {
                    "id": "channel2",
                    "snippet": {"title": "Channel 2"},
                    "statistics": {"subscriberCount": "2000"},
                },
            ],
            "pageInfo": {"totalResults": 2},
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "list_channels_by_id"
        assert len(result["items"]) == 2

    @pytest.mark.asyncio
    async def test_get_my_channel(self):
        """Test getting the authenticated user's channel."""
        config = YouTubeGetMyChannelConfig()
        node = create_node(config)

        mock_data = {
            "items": [
                {
                    "id": "my-channel-id",
                    "snippet": {"title": "My Channel"},
                    "statistics": {"subscriberCount": "5000"},
                }
            ]
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "get_authenticated_user_channel"
        assert result["channel"]["snippet"]["title"] == "My Channel"

    @pytest.mark.asyncio
    async def test_update_channel(self):
        """Test updating channel branding settings."""
        config = YouTubeUpdateChannelConfig(
            channel_id="channel123", description="Updated channel description"
        )
        node = create_node(config)

        get_mock_data = {
            "items": [
                {
                    "id": "channel123",
                    "brandingSettings": {"channel": {"description": "Old description"}},
                }
            ]
        }

        update_mock_data = {
            "id": "channel123",
            "brandingSettings": {
                "channel": {"description": "Updated channel description"}
            },
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, patch(
            "httpx.AsyncClient.put", new_callable=AsyncMock
        ) as mock_put:
            mock_get.return_value = mock_api_response(get_mock_data)
            mock_put.return_value = mock_api_response(update_mock_data)
            result = await node.execute({})

        assert result["action"] == "update_channel_branding"


# ============================================================================
# Playlist Operations Tests
# ============================================================================


class TestPlaylistOperations:
    """Test playlist-related YouTube API operations."""

    @pytest.mark.asyncio
    async def test_list_playlists(self):
        """Test listing playlists."""
        config = YouTubeListMyPlaylistsConfig()
        node = create_node(config)

        mock_data = {
            "items": [
                {"id": "playlist1", "snippet": {"title": "Playlist 1"}},
                {"id": "playlist2", "snippet": {"title": "Playlist 2"}},
            ],
            "pageInfo": {"totalResults": 2},
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "list_authenticated_user_playlists"
        assert len(result["items"]) == 2

    @pytest.mark.asyncio
    async def test_get_playlist(self):
        """Test getting a single playlist."""
        config = YouTubeGetPlaylistConfig(playlist_id="playlist123")
        node = create_node(config)

        mock_data = {
            "items": [{"id": "playlist123", "snippet": {"title": "Test Playlist"}}]
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "get_playlist"
        assert result["playlist"]["id"] == "playlist123"

    @pytest.mark.asyncio
    async def test_create_playlist(self):
        """Test creating a playlist."""
        config = YouTubeCreatePlaylistConfig(
            title="New Playlist",
            description="A test playlist",
            privacy_status="private",
        )
        node = create_node(config)

        mock_data = {
            "id": "new-playlist-id",
            "snippet": {"title": "New Playlist", "description": "A test playlist"},
            "status": {"privacyStatus": "private"},
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "create_playlist"
        assert result["playlist"]["snippet"]["title"] == "New Playlist"

    @pytest.mark.asyncio
    async def test_update_playlist(self):
        """Test updating a playlist."""
        config = YouTubeUpdatePlaylistConfig(
            playlist_id="playlist123", title="Updated Playlist Title"
        )
        node = create_node(config)

        get_mock_data = {
            "items": [
                {
                    "id": "playlist123",
                    "snippet": {"title": "Old Title"},
                    "status": {"privacyStatus": "public"},
                }
            ]
        }

        update_mock_data = {
            "id": "playlist123",
            "snippet": {"title": "Updated Playlist Title"},
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, patch(
            "httpx.AsyncClient.put", new_callable=AsyncMock
        ) as mock_put:
            mock_get.return_value = mock_api_response(get_mock_data)
            mock_put.return_value = mock_api_response(update_mock_data)
            result = await node.execute({})

        assert result["action"] == "update_playlist"

    @pytest.mark.asyncio
    async def test_delete_playlist(self):
        """Test deleting a playlist."""
        config = YouTubeDeletePlaylistConfig(playlist_id="playlist123")
        node = create_node(config)

        with patch("httpx.AsyncClient.delete", new_callable=AsyncMock) as mock_delete:
            mock_delete.return_value = mock_api_delete_response()
            result = await node.execute({})

        assert result["action"] == "delete_playlist"
        assert result["success"] is True


# ============================================================================
# Playlist Items Operations Tests
# ============================================================================


class TestPlaylistItemsOperations:
    """Test playlist items-related YouTube API operations."""

    @pytest.mark.asyncio
    async def test_list_playlist_items(self):
        """Test listing items in a playlist."""
        config = YouTubeListPlaylistItemsConfig(playlist_id="playlist123")
        node = create_node(config)

        mock_data = {
            "items": [
                {"id": "item1", "snippet": {"title": "Video 1", "position": 0}},
                {"id": "item2", "snippet": {"title": "Video 2", "position": 1}},
            ],
            "pageInfo": {"totalResults": 2},
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "list_playlist_items"
        assert len(result["items"]) == 2

    @pytest.mark.asyncio
    async def test_add_playlist_item(self):
        """Test adding a video to a playlist."""
        config = YouTubeAddPlaylistItemConfig(
            playlist_id="playlist123", video_id="video456"
        )
        node = create_node(config)

        mock_data = {
            "id": "new-item-id",
            "snippet": {
                "playlistId": "playlist123",
                "resourceId": {"kind": "youtube#video", "videoId": "video456"},
            },
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "add_video_to_playlist"

    @pytest.mark.asyncio
    async def test_update_playlist_item(self):
        """Test updating a playlist item position."""
        config = YouTubeUpdatePlaylistItemConfig(
            playlist_item_id="item123",
            playlist_id="playlist123",
            video_id="video456",
            position=5,
        )
        node = create_node(config)

        mock_data = {"id": "item123", "snippet": {"position": 5}}

        with patch("httpx.AsyncClient.put", new_callable=AsyncMock) as mock_put:
            mock_put.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "update_playlist_item_position"

    @pytest.mark.asyncio
    async def test_delete_playlist_item(self):
        """Test removing an item from a playlist."""
        config = YouTubeDeletePlaylistItemConfig(playlist_item_id="item123")
        node = create_node(config)

        with patch("httpx.AsyncClient.delete", new_callable=AsyncMock) as mock_delete:
            mock_delete.return_value = mock_api_delete_response()
            result = await node.execute({})

        assert result["action"] == "remove_item_from_playlist"
        assert result["success"] is True


# ============================================================================
# Search Operations Tests
# ============================================================================


class TestSearchOperations:
    """Test search-related YouTube API operations."""

    @pytest.mark.asyncio
    async def test_search(self):
        """Test searching for videos."""
        config = YouTubeSearchConfig(
            query="python tutorial", search_type="video", max_results=10
        )
        node = create_node(config)

        mock_data = {
            "items": [
                {
                    "id": {"kind": "youtube#video", "videoId": "video1"},
                    "snippet": {"title": "Python Tutorial 1"},
                },
                {
                    "id": {"kind": "youtube#video", "videoId": "video2"},
                    "snippet": {"title": "Python Tutorial 2"},
                },
            ],
            "pageInfo": {"totalResults": 100},
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "search_youtube"
        assert len(result["items"]) == 2


# ============================================================================
# Comment Operations Tests
# ============================================================================


class TestCommentOperations:
    """Test comment-related YouTube API operations."""

    @pytest.mark.asyncio
    async def test_list_comment_replies(self):
        """Test listing comment replies."""
        config = YouTubeListCommentRepliesConfig(parent_id="thread123")
        node = create_node(config)

        mock_data = {
            "items": [
                {"id": "comment1", "snippet": {"textDisplay": "Great video!"}},
                {"id": "comment2", "snippet": {"textDisplay": "Very helpful"}},
            ],
            "pageInfo": {"totalResults": 2},
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "list_comment_replies"
        assert len(result["items"]) == 2

    @pytest.mark.asyncio
    async def test_list_video_comments(self):
        """Test listing comment threads for a video."""
        config = YouTubeListVideoCommentsConfig(video_id="video123")
        node = create_node(config)

        mock_data = {
            "items": [
                {
                    "id": "thread1",
                    "snippet": {
                        "topLevelComment": {"snippet": {"textDisplay": "First!"}}
                    },
                },
            ],
            "pageInfo": {"totalResults": 1},
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "list_video_comments"

    @pytest.mark.asyncio
    async def test_create_comment(self):
        """Test creating a reply to a comment."""
        config = YouTubeCreateCommentConfig(
            parent_id="comment123", text="Thanks for your comment!"
        )
        node = create_node(config)

        mock_data = {
            "id": "new-comment-id",
            "snippet": {"textOriginal": "Thanks for your comment!"},
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "create_comment_reply"

    @pytest.mark.asyncio
    async def test_create_video_comment(self):
        """Test creating a top-level comment on a video."""
        config = YouTubeCreateVideoCommentConfig(
            video_id="video123", text="Great video! Thanks for sharing."
        )
        node = create_node(config)

        mock_data = {
            "id": "new-thread-id",
            "snippet": {
                "topLevelComment": {
                    "snippet": {"textOriginal": "Great video! Thanks for sharing."}
                }
            },
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "create_video_comment"

    @pytest.mark.asyncio
    async def test_update_comment(self):
        """Test updating a comment."""
        config = YouTubeUpdateCommentConfig(
            comment_id="comment123", text="Updated comment text"
        )
        node = create_node(config)

        mock_data = {
            "id": "comment123",
            "snippet": {"textOriginal": "Updated comment text"},
        }

        with patch("httpx.AsyncClient.put", new_callable=AsyncMock) as mock_put:
            mock_put.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "update_comment"

    @pytest.mark.asyncio
    async def test_delete_comment(self):
        """Test deleting a comment."""
        config = YouTubeDeleteCommentConfig(comment_id="comment123")
        node = create_node(config)

        with patch("httpx.AsyncClient.delete", new_callable=AsyncMock) as mock_delete:
            mock_delete.return_value = mock_api_delete_response()
            result = await node.execute({})

        assert result["action"] == "delete_comment"
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_set_comment_moderation(self):
        """Test setting comment moderation status."""
        config = YouTubeSetCommentModerationConfig(
            comment_ids="comment1,comment2", moderation_status="published"
        )
        node = create_node(config)

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_api_delete_response()
            result = await node.execute({})

        assert result["action"] == "set_comment_moderation_status"
        assert result["success"] is True


# ============================================================================
# Subscription Operations Tests
# ============================================================================


class TestSubscriptionOperations:
    """Test subscription-related YouTube API operations."""

    @pytest.mark.asyncio
    async def test_list_subscriptions(self):
        """Test listing subscriptions."""
        config = YouTubeListSubscriptionsConfig(mine=True)
        node = create_node(config)

        mock_data = {
            "items": [
                {"id": "sub1", "snippet": {"title": "Channel 1"}},
                {"id": "sub2", "snippet": {"title": "Channel 2"}},
            ],
            "pageInfo": {"totalResults": 2},
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "list_subscriptions"
        assert len(result["items"]) == 2

    @pytest.mark.asyncio
    async def test_subscribe(self):
        """Test subscribing to a channel."""
        config = YouTubeSubscribeConfig(channel_id="channel123")
        node = create_node(config)

        mock_data = {
            "id": "new-sub-id",
            "snippet": {"resourceId": {"channelId": "channel123"}},
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "subscribe_to_channel"

    @pytest.mark.asyncio
    async def test_unsubscribe(self):
        """Test unsubscribing from a channel."""
        config = YouTubeUnsubscribeConfig(subscription_id="sub123")
        node = create_node(config)

        with patch("httpx.AsyncClient.delete", new_callable=AsyncMock) as mock_delete:
            mock_delete.return_value = mock_api_delete_response()
            result = await node.execute({})

        assert result["action"] == "unsubscribe_from_channel"
        assert result["success"] is True


# ============================================================================
# Caption Operations Tests
# ============================================================================


class TestCaptionOperations:
    """Test caption-related YouTube API operations."""

    @pytest.mark.asyncio
    async def test_list_captions(self):
        """Test listing captions for a video."""
        config = YouTubeListCaptionsConfig(video_id="video123")
        node = create_node(config)

        mock_data = {
            "items": [
                {"id": "caption1", "snippet": {"language": "en", "name": "English"}},
                {"id": "caption2", "snippet": {"language": "es", "name": "Spanish"}},
            ]
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "list_video_captions"
        assert len(result["items"]) == 2

    @pytest.mark.asyncio
    async def test_download_caption(self):
        """Test downloading a caption track."""
        config = YouTubeDownloadCaptionConfig(caption_id="caption123", tfmt="srt")
        node = create_node(config)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "1\n00:00:01,000 --> 00:00:04,000\nHello, world!"

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response
            result = await node.execute({})

        assert result["action"] == "download_caption_track"
        assert "Hello, world!" in result["content"]


# ============================================================================
# Activity Operations Tests
# ============================================================================


class TestActivityOperations:
    """Test activity-related YouTube API operations."""

    @pytest.mark.asyncio
    async def test_list_my_activities(self):
        """Test listing your channel activities."""
        config = YouTubeListMyActivitiesConfig()
        node = create_node(config)

        mock_data = {
            "items": [
                {
                    "id": "activity1",
                    "snippet": {"type": "upload", "title": "New Video Uploaded"},
                },
                {
                    "id": "activity2",
                    "snippet": {"type": "like", "title": "Liked a video"},
                },
            ],
            "pageInfo": {"totalResults": 2},
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "list_authenticated_user_activities"
        assert len(result["items"]) == 2


# ============================================================================
# Category and Localization Operations Tests
# ============================================================================


class TestCategoryOperations:
    """Test category and localization-related YouTube API operations."""

    @pytest.mark.asyncio
    async def test_list_video_categories(self):
        """Test listing video categories."""
        config = YouTubeListVideoCategoriesConfig(region_code="US")
        node = create_node(config)

        mock_data = {
            "items": [
                {"id": "1", "snippet": {"title": "Film & Animation"}},
                {"id": "2", "snippet": {"title": "Autos & Vehicles"}},
                {"id": "10", "snippet": {"title": "Music"}},
            ]
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "list_video_categories"
        assert len(result["items"]) == 3

    @pytest.mark.asyncio
    async def test_list_languages(self):
        """Test listing supported languages."""
        config = YouTubeListLanguagesConfig()
        node = create_node(config)

        mock_data = {
            "items": [
                {"id": "en", "snippet": {"hl": "en", "name": "English"}},
                {"id": "es", "snippet": {"hl": "es", "name": "Spanish"}},
            ]
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "list_supported_languages"
        assert len(result["items"]) == 2

    @pytest.mark.asyncio
    async def test_list_regions(self):
        """Test listing supported regions."""
        config = YouTubeListRegionsConfig()
        node = create_node(config)

        mock_data = {
            "items": [
                {"id": "US", "snippet": {"gl": "US", "name": "United States"}},
                {"id": "GB", "snippet": {"gl": "GB", "name": "United Kingdom"}},
            ]
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "list_supported_regions"
        assert len(result["items"]) == 2


# ============================================================================
# Channel Sections Operations Tests
# ============================================================================


class TestChannelSectionsOperations:
    """Test channel sections-related YouTube API operations."""

    @pytest.mark.asyncio
    async def test_list_channel_sections(self):
        """Test listing channel sections."""
        config = YouTubeListMyChannelSectionsConfig()
        node = create_node(config)

        mock_data = {
            "items": [
                {
                    "id": "section1",
                    "snippet": {"type": "singlePlaylist", "title": "Featured"},
                },
                {
                    "id": "section2",
                    "snippet": {"type": "recentActivity", "title": "Recent Activity"},
                },
            ]
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "list_authenticated_user_channel_sections"
        assert len(result["items"]) == 2


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Test error handling for YouTube API operations."""

    @pytest.mark.asyncio
    async def test_api_error(self):
        """Test handling of API errors."""
        config = YouTubeGetVideoConfig(video_id="nonexistent-video")
        node = create_node(config)

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_error("Video not found", 404)

            with pytest.raises(ValueError, match="YouTube API error"):
                await node.execute({})

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        """Test that missing credentials raises an error."""
        config = YouTubeListPopularVideosConfig()
        node_config = YouTubeNodeConfig(config=config, credentials=None)
        node = YouTubeNode(
            node_id="test-node",
            node_type="automation-youtube",
            node_data={},
            config=node_config,
            sio=None,
            sid=None,
            workflow_id="test-workflow",
        )

        with pytest.raises(ValueError, match="credentials are required"):
            await node.execute({})


# ============================================================================
# Authentication Tests
# ============================================================================


class TestAuthentication:
    """Test authentication handling for YouTube API."""

    @pytest.mark.asyncio
    async def test_oauth_bearer_token(self):
        """Test that OAuth uses Bearer token format."""
        config = YouTubeListPopularVideosConfig()
        credentials = YouTubeOAuthCredential(
            access_token="test_oauth_token",
            refresh_token="test_refresh_token",
            expires_at="2099-12-31T23:59:59Z",
            email="test@example.com",
        )
        node = create_node(config, credentials)

        mock_data = {"items": [], "pageInfo": {"totalResults": 0}}

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_response(mock_data)
            await node.execute({})

            # Verify the Authorization header was set correctly with Bearer prefix
            call_args = mock_get.call_args
            headers = call_args.kwargs.get("headers", {})
            assert headers.get("Authorization") == "Bearer test_oauth_token"


# ============================================================================
# Thumbnail Operations Tests
# ============================================================================


class TestThumbnailOperations:
    """Tests for video thumbnail operations."""

    @pytest.mark.asyncio
    async def test_set_thumbnail(self):
        """Test setting a video thumbnail."""
        from nodes.core.media_resolver import ResolvedMedia

        config = YouTubeSetThumbnailConfig(
            video_id="test_video_id", thumbnail_url="https://example.com/thumbnail.jpg"
        )
        node = create_node(config)

        # The thumbnail input is resolved to bytes (uploaded file, URL, or upstream ref).
        resolved = ResolvedMedia(
            data=b"fake_image_data", mime_type="image/jpeg", filename="thumbnail.jpg"
        )

        mock_upload_data = {
            "items": [{"default": {"url": "https://i.ytimg.com/vi/test/default.jpg"}}]
        }

        with patch(
            "nodes.core.media_resolver.resolve_media_input",
            new=AsyncMock(return_value=resolved),
        ), patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_api_response(mock_upload_data)
            result = await node.execute({})

        assert result["action"] == "set_video_thumbnail"
        assert result["video_id"] == "test_video_id"


# ============================================================================
# Members Operations Tests
# ============================================================================


class TestMembersOperations:
    """Tests for channel members operations."""

    @pytest.mark.asyncio
    async def test_list_members(self):
        """Test listing channel members."""
        config = YouTubeListMembersConfig()
        node = create_node(config)

        mock_data = {
            "items": [{"snippet": {"memberDetails": {"channelId": "UC123"}}}],
            "pageInfo": {"totalResults": 1},
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "list_channel_members"
        assert len(result["items"]) == 1

    @pytest.mark.asyncio
    async def test_list_membership_levels(self):
        """Test listing membership levels."""
        config = YouTubeListMembershipLevelsConfig()
        node = create_node(config)

        mock_data = {
            "items": [{"snippet": {"levelDetails": {"displayName": "Level 1"}}}]
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "list_membership_levels"


# ============================================================================
# Analytics API Tests
# ============================================================================


class TestAnalyticsOperations:
    """Tests for YouTube Analytics API operations."""

    @pytest.mark.asyncio
    async def test_get_channel_analytics(self):
        """Test getting channel analytics."""
        config = YouTubeGetChannelAnalyticsConfig(
            start_date="2024-01-01", end_date="2024-01-31"
        )
        node = create_node(config)

        mock_data = {
            "columnHeaders": [{"name": "views"}, {"name": "estimatedMinutesWatched"}],
            "rows": [[1000, 5000]],
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "get_channel_analytics"
        assert "columnHeaders" in result
        assert "rows" in result

    @pytest.mark.asyncio
    async def test_get_video_analytics(self):
        """Test getting video analytics."""
        config = YouTubeGetVideoAnalyticsConfig(
            video_id="test_video_id", start_date="2024-01-01", end_date="2024-01-31"
        )
        node = create_node(config)

        mock_data = {"columnHeaders": [{"name": "views"}], "rows": [[500]]}

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "get_video_analytics"
        assert result["video_id"] == "test_video_id"

    @pytest.mark.asyncio
    async def test_get_revenue_analytics(self):
        """Test getting revenue analytics."""
        config = YouTubeGetRevenueAnalyticsConfig(
            start_date="2024-01-01", end_date="2024-01-31"
        )
        node = create_node(config)

        mock_data = {
            "columnHeaders": [{"name": "estimatedRevenue"}],
            "rows": [[100.50]],
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "get_channel_revenue_analytics"

    @pytest.mark.asyncio
    async def test_get_top_videos(self):
        """Test getting top videos."""
        config = YouTubeGetTopVideosConfig(
            start_date="2024-01-01", end_date="2024-01-31", max_results=10
        )
        node = create_node(config)

        mock_data = {
            "columnHeaders": [{"name": "video"}, {"name": "views"}],
            "rows": [["video1", 1000], ["video2", 500]],
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "get_top_performing_videos"

    @pytest.mark.asyncio
    async def test_get_demographics(self):
        """Test getting viewer demographics."""
        config = YouTubeGetDemographicsConfig(
            start_date="2024-01-01", end_date="2024-01-31"
        )
        node = create_node(config)

        mock_data = {
            "columnHeaders": [
                {"name": "ageGroup"},
                {"name": "gender"},
                {"name": "viewerPercentage"},
            ],
            "rows": [["age25-34", "male", 25.5]],
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "get_viewer_demographics"

    @pytest.mark.asyncio
    async def test_get_traffic_sources(self):
        """Test getting traffic sources."""
        config = YouTubeGetTrafficSourcesConfig(
            start_date="2024-01-01", end_date="2024-01-31"
        )
        node = create_node(config)

        mock_data = {
            "columnHeaders": [{"name": "insightTrafficSourceType"}, {"name": "views"}],
            "rows": [["SUGGESTED", 500], ["SEARCH", 300]],
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "get_channel_traffic_sources"


# ============================================================================
# Reporting API Tests
# ============================================================================


class TestReportingOperations:
    """Tests for YouTube Reporting API operations."""

    @pytest.mark.asyncio
    async def test_list_report_types(self):
        """Test listing report types."""
        config = YouTubeListReportTypesConfig()
        node = create_node(config)

        mock_data = {
            "reportTypes": [
                {"id": "channel_basic_a2", "name": "Channel basic statistics"}
            ]
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "list_bulk_reporting_types"
        assert "reportTypes" in result

    @pytest.mark.asyncio
    async def test_create_reporting_job(self):
        """Test creating a reporting job."""
        config = YouTubeCreateReportingJobConfig(
            report_type_id="channel_basic_a2", name="My Daily Report"
        )
        node = create_node(config)

        mock_data = {
            "id": "job123",
            "reportTypeId": "channel_basic_a2",
            "name": "My Daily Report",
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "create_reporting_job"
        assert "job" in result

    @pytest.mark.asyncio
    async def test_list_reporting_jobs(self):
        """Test listing reporting jobs."""
        config = YouTubeListReportingJobsConfig()
        node = create_node(config)

        mock_data = {"jobs": [{"id": "job123", "name": "My Report"}]}

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "list_reporting_jobs"
        assert "jobs" in result

    @pytest.mark.asyncio
    async def test_get_reporting_job(self):
        """Test getting a specific reporting job."""
        config = YouTubeGetReportingJobConfig(job_id="job123")
        node = create_node(config)

        mock_data = {"id": "job123", "reportTypeId": "channel_basic_a2"}

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "get_reporting_job"

    @pytest.mark.asyncio
    async def test_delete_reporting_job(self):
        """Test deleting a reporting job."""
        config = YouTubeDeleteReportingJobConfig(job_id="job123")
        node = create_node(config)

        mock_response = MagicMock()
        mock_response.status_code = 204

        with patch("httpx.AsyncClient.delete", new_callable=AsyncMock) as mock_delete:
            mock_delete.return_value = mock_response
            result = await node.execute({})

        assert result["action"] == "delete_reporting_job"
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_list_reports(self):
        """Test listing reports for a job."""
        config = YouTubeListReportsConfig(job_id="job123")
        node = create_node(config)

        mock_data = {
            "reports": [
                {"id": "report1", "downloadUrl": "https://example.com/report.csv"}
            ]
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "list_reporting_job_reports"
        assert "reports" in result


# ============================================================================
# Live Broadcast Tests
# ============================================================================


class TestLiveBroadcastOperations:
    """Tests for live broadcast operations."""

    @pytest.mark.asyncio
    async def test_list_broadcasts(self):
        """Test listing live broadcasts."""
        config = YouTubeListBroadcastsConfig()
        node = create_node(config)

        mock_data = {
            "items": [{"id": "broadcast1", "snippet": {"title": "My Stream"}}],
            "pageInfo": {"totalResults": 1},
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "list_live_broadcasts"
        assert len(result["items"]) == 1

    @pytest.mark.asyncio
    async def test_create_broadcast(self):
        """Test creating a live broadcast."""
        config = YouTubeCreateBroadcastConfig(
            title="Test Stream", scheduled_start_time="2024-12-25T10:00:00Z"
        )
        node = create_node(config)

        mock_data = {"id": "broadcast1", "snippet": {"title": "Test Stream"}}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "create_live_broadcast"
        assert "broadcast" in result

    @pytest.mark.asyncio
    async def test_update_broadcast(self):
        """Test updating a live broadcast."""
        config = YouTubeUpdateBroadcastConfig(
            broadcast_id="broadcast1", title="Updated Stream Title"
        )
        node = create_node(config)

        mock_get_data = {
            "items": [
                {
                    "id": "broadcast1",
                    "snippet": {"title": "Old"},
                    "status": {"privacyStatus": "private"},
                }
            ]
        }
        mock_put_data = {
            "id": "broadcast1",
            "snippet": {"title": "Updated Stream Title"},
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, patch(
            "httpx.AsyncClient.put", new_callable=AsyncMock
        ) as mock_put:
            mock_get.return_value = mock_api_response(mock_get_data)
            mock_put.return_value = mock_api_response(mock_put_data)
            result = await node.execute({})

        assert result["action"] == "update_live_broadcast"

    @pytest.mark.asyncio
    async def test_delete_broadcast(self):
        """Test deleting a live broadcast."""
        config = YouTubeDeleteBroadcastConfig(broadcast_id="broadcast1")
        node = create_node(config)

        with patch("httpx.AsyncClient.delete", new_callable=AsyncMock) as mock_delete:
            mock_delete.return_value = mock_api_response({})
            result = await node.execute({})

        assert result["action"] == "delete_live_broadcast"
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_transition_broadcast(self):
        """Test transitioning a broadcast status."""
        config = YouTubeTransitionBroadcastConfig(
            broadcast_id="broadcast1", broadcast_status="live"
        )
        node = create_node(config)

        mock_data = {"id": "broadcast1", "status": {"lifeCycleStatus": "live"}}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "transition_broadcast_status"

    @pytest.mark.asyncio
    async def test_bind_broadcast(self):
        """Test binding a broadcast to a stream."""
        config = YouTubeBindBroadcastConfig(
            broadcast_id="broadcast1", stream_id="stream1"
        )
        node = create_node(config)

        mock_data = {"id": "broadcast1", "contentDetails": {"boundStreamId": "stream1"}}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "bind_broadcast_to_stream"


# ============================================================================
# Live Stream Tests
# ============================================================================


class TestLiveStreamOperations:
    """Tests for live stream operations."""

    @pytest.mark.asyncio
    async def test_list_streams(self):
        """Test listing live streams."""
        config = YouTubeListStreamsConfig()
        node = create_node(config)

        mock_data = {
            "items": [{"id": "stream1", "snippet": {"title": "My Stream"}}],
            "pageInfo": {"totalResults": 1},
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "list_live_streams"
        assert len(result["items"]) == 1

    @pytest.mark.asyncio
    async def test_create_stream(self):
        """Test creating a live stream."""
        config = YouTubeCreateStreamConfig(title="Test Stream")
        node = create_node(config)

        mock_data = {
            "id": "stream1",
            "snippet": {"title": "Test Stream"},
            "cdn": {"ingestionInfo": {"streamName": "key123"}},
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "create_live_stream"
        assert "stream" in result

    @pytest.mark.asyncio
    async def test_update_stream(self):
        """Test updating a live stream."""
        config = YouTubeUpdateStreamConfig(stream_id="stream1", title="Updated Stream")
        node = create_node(config)

        mock_get_data = {
            "items": [{"id": "stream1", "snippet": {"title": "Old"}, "cdn": {}}]
        }
        mock_put_data = {"id": "stream1", "snippet": {"title": "Updated Stream"}}

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, patch(
            "httpx.AsyncClient.put", new_callable=AsyncMock
        ) as mock_put:
            mock_get.return_value = mock_api_response(mock_get_data)
            mock_put.return_value = mock_api_response(mock_put_data)
            result = await node.execute({})

        assert result["action"] == "update_live_stream"

    @pytest.mark.asyncio
    async def test_delete_stream(self):
        """Test deleting a live stream."""
        config = YouTubeDeleteStreamConfig(stream_id="stream1")
        node = create_node(config)

        with patch("httpx.AsyncClient.delete", new_callable=AsyncMock) as mock_delete:
            mock_delete.return_value = mock_api_response({})
            result = await node.execute({})

        assert result["action"] == "delete_live_stream"
        assert result["success"] is True


# ============================================================================
# Live Chat Tests
# ============================================================================


class TestLiveChatOperations:
    """Tests for live chat operations."""

    @pytest.mark.asyncio
    async def test_list_live_chat_messages(self):
        """Test listing live chat messages."""
        config = YouTubeListLiveChatMessagesConfig(live_chat_id="chat123")
        node = create_node(config)

        mock_data = {
            "items": [{"snippet": {"displayMessage": "Hello!"}}],
            "pageInfo": {"totalResults": 1},
            "pollingIntervalMillis": 5000,
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "list_live_chat_messages"
        assert "pollingIntervalMillis" in result

    @pytest.mark.asyncio
    async def test_send_live_chat_message(self):
        """Test sending a live chat message."""
        config = YouTubeSendLiveChatMessageConfig(
            live_chat_id="chat123", message="Hello everyone!"
        )
        node = create_node(config)

        mock_data = {"id": "msg123", "snippet": {"displayMessage": "Hello everyone!"}}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "send_live_chat_message"

    @pytest.mark.asyncio
    async def test_delete_live_chat_message(self):
        """Test deleting a live chat message."""
        config = YouTubeDeleteLiveChatMessageConfig(message_id="msg123")
        node = create_node(config)

        with patch("httpx.AsyncClient.delete", new_callable=AsyncMock) as mock_delete:
            mock_delete.return_value = mock_api_response({})
            result = await node.execute({})

        assert result["action"] == "delete_live_chat_message"
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_list_live_chat_moderators(self):
        """Test listing live chat moderators."""
        config = YouTubeListLiveChatModeratorsConfig(live_chat_id="chat123")
        node = create_node(config)

        mock_data = {
            "items": [{"snippet": {"moderatorDetails": {"channelId": "UC123"}}}],
            "pageInfo": {"totalResults": 1},
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "list_live_chat_moderators"

    @pytest.mark.asyncio
    async def test_add_live_chat_moderator(self):
        """Test adding a live chat moderator."""
        config = YouTubeAddLiveChatModeratorConfig(
            live_chat_id="chat123", channel_id="UC456"
        )
        node = create_node(config)

        mock_data = {
            "id": "mod123",
            "snippet": {"moderatorDetails": {"channelId": "UC456"}},
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "add_live_chat_moderator"

    @pytest.mark.asyncio
    async def test_remove_live_chat_moderator(self):
        """Test removing a live chat moderator."""
        config = YouTubeRemoveLiveChatModeratorConfig(moderator_id="mod123")
        node = create_node(config)

        with patch("httpx.AsyncClient.delete", new_callable=AsyncMock) as mock_delete:
            mock_delete.return_value = mock_api_response({})
            result = await node.execute({})

        assert result["action"] == "remove_live_chat_moderator"
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_ban_live_chat_user(self):
        """Test banning a user from live chat."""
        config = YouTubeBanLiveChatUserConfig(
            live_chat_id="chat123", channel_id="UC789", ban_type="permanent"
        )
        node = create_node(config)

        mock_data = {
            "id": "ban123",
            "snippet": {"bannedUserDetails": {"channelId": "UC789"}},
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "ban_live_chat_user"

    @pytest.mark.asyncio
    async def test_unban_live_chat_user(self):
        """Test unbanning a user from live chat."""
        config = YouTubeUnbanLiveChatUserConfig(ban_id="ban123")
        node = create_node(config)

        with patch("httpx.AsyncClient.delete", new_callable=AsyncMock) as mock_delete:
            mock_delete.return_value = mock_api_response({})
            result = await node.execute({})

        assert result["action"] == "unban_live_chat_user"
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_list_super_chat_events(self):
        """Test listing Super Chat events."""
        config = YouTubeListSuperChatEventsConfig()
        node = create_node(config)

        mock_data = {
            "items": [{"snippet": {"amountMicros": "5000000", "currency": "USD"}}],
            "pageInfo": {"totalResults": 1},
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_response(mock_data)
            result = await node.execute({})

        assert result["action"] == "list_super_chat_events"
