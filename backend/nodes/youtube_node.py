"""
YouTube workflow node implementation.
Enables interacting with YouTube Data API v3 via OAuth credentials.
Supports videos, playlists, channels, comments, subscriptions, and search operations.
"""

import logging
import io
from typing import Dict, Any, Optional, Union, Type, List, Literal, Annotated
from pydantic import BaseModel, Field, ConfigDict, model_validator, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.oauth.google_oauth import is_token_expired, refresh_access_token
from nodes.scopes.youtube import YOUTUBE_SCOPES
from utils.ssrf import assert_exact_url_origin

logger = logging.getLogger(__name__)

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
YOUTUBE_ANALYTICS_API_BASE = "https://youtubeanalytics.googleapis.com/v2"
YOUTUBE_REPORTING_API_BASE = "https://youtubereporting.googleapis.com/v1"
YOUTUBE_UPLOAD_ORIGIN = "https://www.googleapis.com"
YOUTUBE_UPLOAD_URL = f"{YOUTUBE_UPLOAD_ORIGIN}/upload/youtube/v3/videos"


# ============================================================================
# YouTube Node Credential Schema
# ============================================================================


class YouTubeOAuthCredential(BaseModel):
    """
    OAuth credential for YouTube access.
    Tokens are obtained via OAuth flow, not entered manually.
    """

    credential_type: Literal["google_youtube_oauth"] = Field(
        "google_youtube_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ..., title="Access Token", description="OAuth 2.0 access token from Google"
    )
    refresh_token: str = Field(
        ...,
        title="Refresh Token",
        description="OAuth 2.0 refresh token for automatic renewal",
    )
    expires_at: str = Field(
        ...,
        title="Token Expiry",
        description="ISO 8601 timestamp when access token expires",
    )
    email: str = Field(
        ...,
        title="Google Account",
        description="Email address of the connected Google account",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "google",
            "x-oauth-scopes": [
                # YouTube Data API v3 - Full access for read/write/delete
                "https://www.googleapis.com/auth/youtube.force-ssl",
                # Video uploads
                "https://www.googleapis.com/auth/youtube.upload",
                # YouTube Analytics API - View analytics
                "https://www.googleapis.com/auth/yt-analytics.readonly",
                # YouTube Analytics API - View monetary analytics (revenue)
                "https://www.googleapis.com/auth/yt-analytics-monetary.readonly",
                # Channel memberships
                "https://www.googleapis.com/auth/youtube.channel-memberships.creator",
            ],
        }
    )


# ============================================================================
# Video Operation Configs
# ============================================================================


class YouTubeListVideosConfig(BaseModel):
    """Get videos by their IDs"""

    model_config = ConfigDict(title="Get Videos by ID")

    operation: Literal["list_videos_by_id"] = Field(
        default="list_videos_by_id",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Video",
            "x-is-trigger": False,
            "x-display-name": "List Videos by Id",
            "x-keywords": [
                "videos by id",
                "multiple video details",
                "batch video lookup",
                "videos by their ids",
                "specific videos",
            ],
        },
        title="List Videos by Id",
    )
    video_ids: str = Field(
        ...,
        title="Video IDs",
        description="Comma-separated list of video IDs to retrieve",
    )
    part: str = Field(
        default="snippet,contentDetails,statistics",
        title="Parts",
        description="Comma-separated list of video resource parts (snippet,contentDetails,statistics,status,player)",
    )
    max_results: Optional[int] = Field(
        default=25, title="Max Results", description="Maximum number of results (1-50)"
    )


class YouTubeListPopularVideosConfig(BaseModel):
    """Get most popular videos in a region"""

    model_config = ConfigDict(title="Get Popular Videos")

    operation: Literal["list_region_popular_videos"] = Field(
        default="list_region_popular_videos",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Video",
            "x-is-trigger": False,
            "x-display-name": "List Region Popular Videos",
            "x-keywords": [
                "popular videos",
                "trending videos",
                "most popular",
                "top videos region",
                "trending in country",
            ],
        },
        title="List Region Popular Videos",
    )
    region_code: str = Field(
        default="US",
        title="Region Code",
        description="ISO 3166-1 alpha-2 country code (e.g., US, GB, IN)",
    )
    part: str = Field(
        default="snippet,contentDetails,statistics",
        title="Parts",
        description="Comma-separated list of video resource parts",
    )
    max_results: Optional[int] = Field(
        default=25, title="Max Results", description="Maximum number of results (1-50)"
    )


class YouTubeListMyRatedVideosConfig(BaseModel):
    """Get videos you've liked or disliked"""

    model_config = ConfigDict(title="Get My Rated Videos")

    operation: Literal["list_authenticated_user_rated_videos"] = Field(
        default="list_authenticated_user_rated_videos",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Rating",
            "x-is-trigger": False,
            "x-display-name": "List Authenticated User Rated Videos",
            "x-keywords": [
                "my liked videos",
                "videos i liked",
                "my disliked videos",
                "videos i rated",
                "my rated videos",
            ],
        },
        title="List Authenticated User Rated Videos",
    )
    my_rating: str = Field(
        default="like",
        title="Rating",
        description="Filter by your rating (like or dislike)",
    )
    part: str = Field(
        default="snippet,contentDetails,statistics",
        title="Parts",
        description="Comma-separated list of video resource parts",
    )
    max_results: Optional[int] = Field(
        default=25, title="Max Results", description="Maximum number of results (1-50)"
    )


class YouTubeGetVideoConfig(BaseModel):
    """Get a single video by ID"""

    model_config = ConfigDict(title="Get Video")

    operation: Literal["get_video"] = Field(
        default="get_video",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Video",
            "x-is-trigger": False,
            "x-display-name": "Get Video",
            "x-keywords": [
                "single video",
                "one video details",
                "video by id",
                "video info",
            ],
        },
        title="Get Video",
    )
    video_id: str = Field(..., title="Video ID", description="The YouTube video ID")
    part: str = Field(
        default="snippet,contentDetails,statistics,status",
        title="Parts",
        description="Comma-separated list of video resource parts",
    )


class YouTubeUpdateVideoConfig(BaseModel):
    """Update video metadata"""

    model_config = ConfigDict(title="Update Video")

    operation: Literal["update_video_metadata"] = Field(
        default="update_video_metadata",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Video",
            "x-is-trigger": False,
            "x-display-name": "Update Video Metadata",
            "x-keywords": [
                "edit video title",
                "change video description",
                "edit video details",
                "video metadata",
                "rename video",
            ],
        },
        title="Update Video Metadata",
    )
    video_id: str = Field(..., title="Video ID", description="The video ID to update")
    title: Optional[str] = Field(
        default=None, title="Title", description="New video title"
    )
    description: Optional[str] = Field(
        default=None,
        title="Description",
        description="New video description",
        json_schema_extra={"ui:widget": "textarea"},
    )
    tags: Optional[str] = Field(
        default=None, title="Tags", description="Comma-separated list of tags"
    )
    category_id: Optional[str] = Field(
        default=None, title="Category ID", description="Video category ID"
    )
    privacy_status: Optional[str] = Field(
        default=None,
        title="Privacy Status",
        description="Privacy status (public, private, unlisted)",
    )


class YouTubeDeleteVideoConfig(BaseModel):
    """Delete a video"""

    model_config = ConfigDict(title="Delete Video")

    operation: Literal["delete_video"] = Field(
        default="delete_video",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Video",
            "x-is-trigger": False,
            "x-display-name": "Delete Video",
            "x-keywords": ["take down video", "remove my upload", "unpublish video"],
        },
        title="Delete Video",
    )
    video_id: str = Field(..., title="Video ID", description="The video ID to delete")


class YouTubeRateVideoConfig(BaseModel):
    """Rate a video (like/dislike/none)"""

    model_config = ConfigDict(title="Rate Video")

    operation: Literal["rate_video"] = Field(
        default="rate_video",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Video",
            "x-is-trigger": False,
            "x-display-name": "Rate Video",
            "x-keywords": [
                "like a video",
                "dislike video",
                "thumbs up video",
                "give rating",
            ],
        },
        title="Rate Video",
    )
    video_id: str = Field(..., title="Video ID", description="The video ID to rate")
    rating: str = Field(
        ..., title="Rating", description="Rating to apply (like, dislike, none)"
    )


class YouTubeGetVideoRatingConfig(BaseModel):
    """Get your rating for videos"""

    model_config = ConfigDict(title="Get Video Rating")

    operation: Literal["get_user_video_ratings"] = Field(
        default="get_user_video_ratings",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Video",
            "x-is-trigger": False,
            "x-display-name": "Get User Video Ratings",
            "x-keywords": [
                "my rating for video",
                "check my rating",
                "did i like",
                "video rating status",
            ],
        },
        title="Get User Video Ratings",
    )
    video_ids: str = Field(
        ..., title="Video IDs", description="Comma-separated list of video IDs"
    )


class YouTubeUploadVideoConfig(BaseModel):
    """Upload a video (file upload, URL, or upstream reference)"""

    model_config = ConfigDict(title="Upload Video")

    # operation value stays "upload_video_from_url" for back-compat with saved
    # workflows; the display name dropped "from Url" once uploads went binary.
    operation: Literal["upload_video_from_url"] = Field(
        default="upload_video_from_url",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Video",
            "x-is-trigger": False,
            "x-display-name": "Upload Video",
            "x-keywords": [
                "upload video",
                "publish video",
                "post video",
                "video from url",
            ],
        },
        title="Upload Video",
    )
    video_url: str = Field(
        ...,
        title="Video",
        description="The video to upload — upload a file, paste a direct URL, or reference an upstream file (e.g. {{http-1.response.url}}).",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": "video/*"},
    )
    title: str = Field(..., title="Title", description="Video title (required)")
    description: Optional[str] = Field(
        default=None,
        title="Description",
        description="Video description",
        json_schema_extra={"ui:widget": "textarea"},
    )
    tags: Optional[str] = Field(
        default=None, title="Tags", description="Comma-separated list of tags"
    )
    category_id: str = Field(
        default="22",
        title="Category ID",
        description="Video category ID (22 = People & Blogs)",
    )
    privacy_status: str = Field(
        default="private",
        title="Privacy Status",
        description="Privacy status (public, private, unlisted)",
    )
    made_for_kids: bool = Field(
        default=False,
        title="Made for Kids",
        description="Whether the video is made for kids",
    )


# ============================================================================
# Channel Operation Configs
# ============================================================================


class YouTubeListChannelsConfig(BaseModel):
    """Get channels by their IDs"""

    model_config = ConfigDict(title="Get Channels by ID")

    operation: Literal["list_channels_by_id"] = Field(
        default="list_channels_by_id",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "List Channels by Id",
            "x-keywords": [
                "channels by id",
                "multiple channel details",
                "batch channel lookup",
                "specific channels",
            ],
        },
        title="List Channels by Id",
    )
    channel_ids: str = Field(
        ..., title="Channel IDs", description="Comma-separated list of channel IDs"
    )
    part: str = Field(
        default="snippet,contentDetails,statistics",
        title="Parts",
        description="Comma-separated list of channel resource parts",
    )
    max_results: Optional[int] = Field(
        default=25, title="Max Results", description="Maximum results (1-50)"
    )


class YouTubeGetMyChannelConfig(BaseModel):
    """Get the authenticated user's channel"""

    model_config = ConfigDict(title="Get My Channel")

    operation: Literal["get_authenticated_user_channel"] = Field(
        default="get_authenticated_user_channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Get Authenticated User Channel",
            "x-keywords": [
                "my channel",
                "my own channel",
                "current channel",
                "this account channel",
            ],
        },
        title="Get Authenticated User Channel",
    )
    part: str = Field(
        default="snippet,contentDetails,statistics,status,brandingSettings",
        title="Parts",
        description="Comma-separated list of channel resource parts",
    )


class YouTubeUpdateChannelConfig(BaseModel):
    """Update channel branding settings"""

    model_config = ConfigDict(title="Update Channel")

    operation: Literal["update_channel_branding"] = Field(
        default="update_channel_branding",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Update Channel Branding",
            "x-keywords": [
                "channel branding",
                "channel banner",
                "channel art",
                "branding settings",
            ],
        },
        title="Update Channel Branding",
    )
    channel_id: str = Field(
        ..., title="Channel ID", description="The channel ID to update"
    )
    description: Optional[str] = Field(
        default=None,
        title="Description",
        description="New channel description",
        json_schema_extra={"ui:widget": "textarea"},
    )
    keywords: Optional[str] = Field(
        default=None, title="Keywords", description="Channel keywords"
    )
    default_language: Optional[str] = Field(
        default=None, title="Default Language", description="Default language code"
    )


# ============================================================================
# Playlist Operation Configs
# ============================================================================


class YouTubeListMyPlaylistsConfig(BaseModel):
    """Get your own playlists"""

    model_config = ConfigDict(title="Get My Playlists")

    operation: Literal["list_authenticated_user_playlists"] = Field(
        default="list_authenticated_user_playlists",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Playlist",
            "x-is-trigger": False,
            "x-display-name": "List Authenticated User Playlists",
            "x-keywords": [
                "my playlists",
                "my own playlists",
                "playlists i own",
                "own playlists",
            ],
        },
        title="List Authenticated User Playlists",
    )
    part: str = Field(default="snippet,contentDetails,status", title="Parts")
    max_results: Optional[int] = Field(
        default=50, title="Max Results", description="Maximum results per page (1-50)"
    )
    page_token: Optional[str] = Field(
        default=None,
        title="Page Token",
        description="Token for fetching the next page of results",
    )


class YouTubeListPlaylistsByIdConfig(BaseModel):
    """Get playlists by their IDs"""

    model_config = ConfigDict(title="Get Playlists by ID")

    operation: Literal["list_playlists_by_id"] = Field(
        default="list_playlists_by_id",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Playlist",
            "x-is-trigger": False,
            "x-display-name": "List Playlists by Id",
            "x-keywords": [
                "playlists by id",
                "specific playlists",
                "batch playlist lookup",
                "playlists by their ids",
            ],
        },
        title="List Playlists by Id",
    )
    playlist_ids: str = Field(
        ..., title="Playlist IDs", description="Comma-separated playlist IDs"
    )
    part: str = Field(default="snippet,contentDetails,status", title="Parts")
    max_results: Optional[int] = Field(
        default=50, title="Max Results", description="Maximum results per page (1-50)"
    )
    page_token: Optional[str] = Field(
        default=None,
        title="Page Token",
        description="Token for fetching the next page of results",
    )


class YouTubeListChannelPlaylistsConfig(BaseModel):
    """Get playlists from a specific channel"""

    model_config = ConfigDict(title="Get Channel Playlists")

    operation: Literal["list_channel_playlists"] = Field(
        default="list_channel_playlists",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "List Channel Playlists",
            "x-keywords": [
                "playlists from channel",
                "another channel playlists",
                "playlists of channel",
            ],
        },
        title="List Channel Playlists",
    )
    channel_id: str = Field(
        ..., title="Channel ID", description="Channel ID to list playlists for"
    )
    part: str = Field(default="snippet,contentDetails,status", title="Parts")
    max_results: Optional[int] = Field(
        default=50, title="Max Results", description="Maximum results per page (1-50)"
    )
    page_token: Optional[str] = Field(
        default=None,
        title="Page Token",
        description="Token for fetching the next page of results",
    )


class YouTubeGetPlaylistConfig(BaseModel):
    """Get a single playlist"""

    model_config = ConfigDict(title="Get Playlist")

    operation: Literal["get_playlist"] = Field(
        default="get_playlist",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Playlist",
            "x-is-trigger": False,
            "x-display-name": "Get Playlist",
            "x-keywords": ["single playlist", "one playlist details", "playlist info"],
        },
        title="Get Playlist",
    )
    playlist_id: str = Field(..., title="Playlist ID", description="The playlist ID")
    part: str = Field(default="snippet,contentDetails,status", title="Parts")


class YouTubeCreatePlaylistConfig(BaseModel):
    """Create a new playlist"""

    model_config = ConfigDict(title="Create Playlist")

    operation: Literal["create_playlist"] = Field(
        default="create_playlist",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Playlist",
            "x-is-trigger": False,
            "x-display-name": "Create Playlist",
            "x-keywords": ["new playlist", "make playlist", "start a playlist"],
        },
        title="Create Playlist",
    )
    title: str = Field(..., title="Title", description="Playlist title")
    description: Optional[str] = Field(
        default=None,
        title="Description",
        description="Playlist description",
        json_schema_extra={"ui:widget": "textarea"},
    )
    privacy_status: str = Field(
        default="private",
        title="Privacy Status",
        description="Privacy status (public, private, unlisted)",
    )
    tags: Optional[str] = Field(
        default=None, title="Tags", description="Comma-separated tags"
    )


class YouTubeUpdatePlaylistConfig(BaseModel):
    """Update a playlist"""

    model_config = ConfigDict(title="Update Playlist")

    operation: Literal["update_playlist"] = Field(
        default="update_playlist",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Playlist",
            "x-is-trigger": False,
            "x-display-name": "Update Playlist",
            "x-keywords": ["edit playlist", "rename playlist", "change playlist title"],
        },
        title="Update Playlist",
    )
    playlist_id: str = Field(
        ..., title="Playlist ID", description="The playlist ID to update"
    )
    title: Optional[str] = Field(
        default=None, title="Title", description="New playlist title"
    )
    description: Optional[str] = Field(
        default=None, title="Description", json_schema_extra={"ui:widget": "textarea"}
    )
    privacy_status: Optional[str] = Field(default=None, title="Privacy Status")


class YouTubeDeletePlaylistConfig(BaseModel):
    """Delete a playlist"""

    model_config = ConfigDict(title="Delete Playlist")

    operation: Literal["delete_playlist"] = Field(
        default="delete_playlist",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Playlist",
            "x-is-trigger": False,
            "x-display-name": "Delete Playlist",
            "x-keywords": ["remove playlist", "trash playlist", "destroy playlist"],
        },
        title="Delete Playlist",
    )
    playlist_id: str = Field(
        ..., title="Playlist ID", description="The playlist ID to delete"
    )


# ============================================================================
# Playlist Items Operation Configs
# ============================================================================


class YouTubeListPlaylistItemsConfig(BaseModel):
    """List items in a playlist"""

    model_config = ConfigDict(title="List Playlist Items")

    operation: Literal["list_playlist_items"] = Field(
        default="list_playlist_items",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Playlist",
            "x-is-trigger": False,
            "x-display-name": "List Playlist Items",
            "x-keywords": [
                "videos in playlist",
                "playlist contents",
                "playlist videos",
                "items in playlist",
            ],
        },
        title="List Playlist Items",
    )
    playlist_id: str = Field(
        ..., title="Playlist ID", description="The playlist to get items from"
    )
    part: str = Field(default="snippet,contentDetails,status", title="Parts")
    max_results: Optional[int] = Field(default=50, title="Max Results")
    page_token: Optional[str] = Field(
        default=None, title="Page Token", description="Token for pagination"
    )


class YouTubeAddPlaylistItemConfig(BaseModel):
    """Add a video to a playlist"""

    model_config = ConfigDict(title="Add to Playlist")

    operation: Literal["add_video_to_playlist"] = Field(
        default="add_video_to_playlist",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Playlist",
            "x-is-trigger": False,
            "x-display-name": "Add Video to Playlist",
            "x-keywords": [
                "add to playlist",
                "put video in playlist",
                "insert video playlist",
                "save video to playlist",
            ],
        },
        title="Add Video to Playlist",
    )
    playlist_id: str = Field(
        ..., title="Playlist ID", description="The playlist to add to"
    )
    video_id: str = Field(..., title="Video ID", description="The video ID to add")
    position: Optional[int] = Field(
        default=None, title="Position", description="Position in playlist (0-based)"
    )


class YouTubeUpdatePlaylistItemConfig(BaseModel):
    """Update a playlist item position"""

    model_config = ConfigDict(title="Update Playlist Item")

    operation: Literal["update_playlist_item_position"] = Field(
        default="update_playlist_item_position",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Playlist",
            "x-is-trigger": False,
            "x-display-name": "Update Playlist Item Position",
            "x-keywords": [
                "reorder playlist",
                "move video in playlist",
                "change playlist order",
                "reposition playlist item",
            ],
        },
        title="Update Playlist Item Position",
    )
    playlist_item_id: str = Field(
        ..., title="Playlist Item ID", description="The playlist item ID"
    )
    playlist_id: str = Field(..., title="Playlist ID", description="The playlist ID")
    video_id: str = Field(..., title="Video ID", description="The video ID")
    position: int = Field(..., title="Position", description="New position in playlist")


class YouTubeDeletePlaylistItemConfig(BaseModel):
    """Remove an item from a playlist"""

    model_config = ConfigDict(title="Remove from Playlist")

    operation: Literal["remove_item_from_playlist"] = Field(
        default="remove_item_from_playlist",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Playlist",
            "x-is-trigger": False,
            "x-display-name": "Remove Item from Playlist",
            "x-keywords": [
                "remove from playlist",
                "take video out playlist",
                "delete playlist video",
            ],
        },
        title="Remove Item from Playlist",
    )
    playlist_item_id: str = Field(
        ..., title="Playlist Item ID", description="The playlist item ID to remove"
    )


# ============================================================================
# Search Config
# ============================================================================


class YouTubeSearchConfig(BaseModel):
    """Search for videos, channels, or playlists"""

    model_config = ConfigDict(title="Search")

    operation: Literal["search_youtube"] = Field(
        default="search_youtube",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Search",
            "x-is-trigger": False,
            "x-display-name": "Search Youtube",
            "x-keywords": [
                "search videos",
                "find videos channels",
                "youtube search",
                "search content",
            ],
        },
        title="Search Youtube",
    )
    query: str = Field(..., title="Search Query", description="Search query string")
    part: str = Field(default="snippet", title="Parts")
    search_type: Optional[str] = Field(
        default="video",
        title="Type",
        description="Resource type (video, channel, playlist, or comma-separated)",
    )
    channel_id: Optional[str] = Field(
        default=None, title="Channel ID", description="Filter by channel"
    )
    order: Optional[str] = Field(
        default="relevance",
        title="Order",
        description="Sort order (date, rating, relevance, title, videoCount, viewCount)",
    )
    published_after: Optional[str] = Field(
        default=None,
        title="Published After",
        description="Filter by publish date (RFC 3339 format)",
    )
    published_before: Optional[str] = Field(
        default=None,
        title="Published Before",
        description="Filter by publish date (RFC 3339 format)",
    )
    region_code: Optional[str] = Field(
        default=None, title="Region Code", description="ISO 3166-1 alpha-2 country code"
    )
    video_duration: Optional[str] = Field(
        default=None,
        title="Video Duration",
        description="Filter by duration (any, long, medium, short)",
    )
    video_definition: Optional[str] = Field(
        default=None,
        title="Video Definition",
        description="Filter by definition (any, high, standard)",
    )
    max_results: Optional[int] = Field(
        default=25, title="Max Results", description="Maximum results (1-50)"
    )


# ============================================================================
# Comment Configs
# ============================================================================


class YouTubeListCommentRepliesConfig(BaseModel):
    """List replies to a comment"""

    model_config = ConfigDict(title="List Comment Replies")

    operation: Literal["list_comment_replies"] = Field(
        default="list_comment_replies",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Comment",
            "x-is-trigger": False,
            "x-display-name": "List Comment Replies",
            "x-keywords": [
                "replies to comment",
                "comment replies",
                "responses to comment",
            ],
        },
        title="List Comment Replies",
    )
    parent_id: str = Field(
        ...,
        title="Parent Comment ID",
        description="Comment thread ID to get replies for",
    )
    part: str = Field(default="snippet", title="Parts")
    max_results: Optional[int] = Field(default=100, title="Max Results")


class YouTubeListCommentsByIdConfig(BaseModel):
    """Get comments by their IDs"""

    model_config = ConfigDict(title="Get Comments by ID")

    operation: Literal["list_comments_by_id"] = Field(
        default="list_comments_by_id",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Comment",
            "x-is-trigger": False,
            "x-display-name": "List Comments by Id",
            "x-keywords": [
                "comments by id",
                "specific comments",
                "batch comment lookup",
            ],
        },
        title="List Comments by Id",
    )
    comment_ids: str = Field(
        ..., title="Comment IDs", description="Comma-separated comment IDs"
    )
    part: str = Field(default="snippet", title="Parts")
    max_results: Optional[int] = Field(default=100, title="Max Results")


class YouTubeListVideoCommentsConfig(BaseModel):
    """List comment threads for a video"""

    model_config = ConfigDict(title="List Video Comments")

    operation: Literal["list_video_comments"] = Field(
        default="list_video_comments",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Comment",
            "x-is-trigger": False,
            "x-display-name": "List Video Comments",
            "x-keywords": [
                "comments on video",
                "video comment threads",
                "read video comments",
                "fetch video comments",
            ],
        },
        title="List Video Comments",
    )
    video_id: str = Field(
        ..., title="Video ID", description="Video to get comments for"
    )
    part: str = Field(default="snippet,replies", title="Parts")
    order: Optional[str] = Field(
        default="relevance", title="Order", description="Sort order (time, relevance)"
    )
    search_terms: Optional[str] = Field(
        default=None,
        title="Search Terms (Not Supported)",
        description="Note: YouTube API doesn't support text search for comments. This field is ignored.",
    )
    max_results: Optional[int] = Field(default=100, title="Max Results")

    # Time-based filtering
    time_period: Optional[str] = Field(
        default="all_time",
        title="Time Period",
        description="Filter comments by time period (overrides custom date range if set)",
        json_schema_extra={
            "enum": [
                "last_hour",
                "last_24_hours",
                "last_7_days",
                "last_30_days",
                "all_time",
            ],
            "x-enum-searchable": True,
        },
    )
    published_after: Optional[str] = Field(
        default=None,
        title="Published After (Custom)",
        description="ISO 8601 timestamp (e.g., 2025-01-20T00:00:00Z). Only used if time_period is 'all_time'. Client-side filtering.",
    )
    published_before: Optional[str] = Field(
        default=None,
        title="Published Before (Custom)",
        description="ISO 8601 timestamp (e.g., 2025-01-21T00:00:00Z). Client-side filtering.",
    )


class YouTubeListChannelCommentsConfig(BaseModel):
    """List comment threads for a channel's videos"""

    model_config = ConfigDict(title="List Channel Comments")

    operation: Literal["list_channel_video_comments"] = Field(
        default="list_channel_video_comments",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "List Channel Video Comments",
            "x-keywords": [
                "all channel comments",
                "comments across channel",
                "channel videos comments",
            ],
        },
        title="List Channel Video Comments",
    )
    channel_id: str = Field(
        ..., title="Channel ID", description="Channel to get comments for"
    )
    part: str = Field(default="snippet,replies", title="Parts")
    order: Optional[str] = Field(
        default="relevance", title="Order", description="Sort order (time, relevance)"
    )
    search_terms: Optional[str] = Field(
        default=None,
        title="Search Terms (Not Supported)",
        description="Note: YouTube API doesn't support text search for comments. This field is ignored.",
    )
    max_results: Optional[int] = Field(default=100, title="Max Results")

    # Time-based filtering
    time_period: Optional[str] = Field(
        default="all_time",
        title="Time Period",
        description="Filter comments by time period (overrides custom date range if set)",
        json_schema_extra={
            "enum": [
                "last_hour",
                "last_24_hours",
                "last_7_days",
                "last_30_days",
                "all_time",
            ],
            "x-enum-searchable": True,
        },
    )
    published_after: Optional[str] = Field(
        default=None,
        title="Published After (Custom)",
        description="ISO 8601 timestamp (e.g., 2025-01-20T00:00:00Z). Only used if time_period is 'all_time'. Client-side filtering.",
    )
    published_before: Optional[str] = Field(
        default=None,
        title="Published Before (Custom)",
        description="ISO 8601 timestamp (e.g., 2025-01-21T00:00:00Z). Client-side filtering.",
    )


class YouTubeCreateCommentConfig(BaseModel):
    """Create a reply to an existing comment"""

    model_config = ConfigDict(title="Reply to Comment")

    operation: Literal["create_comment_reply"] = Field(
        default="create_comment_reply",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Comment",
            "x-is-trigger": False,
            "x-display-name": "Create Comment Reply",
            "x-keywords": [
                "reply to comment",
                "respond to comment",
                "answer a comment",
            ],
        },
        title="Create Comment Reply",
    )
    parent_id: str = Field(
        ..., title="Parent Comment ID", description="The comment ID to reply to"
    )
    text: str = Field(
        ...,
        title="Comment Text",
        description="The reply text",
        json_schema_extra={"ui:widget": "textarea"},
    )


class YouTubeCreateVideoCommentConfig(BaseModel):
    """Create a top-level comment on a video"""

    model_config = ConfigDict(title="Comment on Video")

    operation: Literal["create_video_comment"] = Field(
        default="create_video_comment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Comment",
            "x-is-trigger": False,
            "x-display-name": "Create Video Comment",
            "x-keywords": [
                "comment on video",
                "top level comment",
                "leave video comment",
                "post video comment",
            ],
        },
        title="Create Video Comment",
    )
    video_id: str = Field(..., title="Video ID", description="Video to comment on")
    text: str = Field(
        ...,
        title="Comment Text",
        description="The comment text",
        json_schema_extra={"ui:widget": "textarea"},
    )


class YouTubeCreateChannelCommentConfig(BaseModel):
    """Create a comment on a channel's discussion tab"""

    model_config = ConfigDict(title="Comment on Channel")

    operation: Literal["create_channel_discussion_comment"] = Field(
        default="create_channel_discussion_comment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Comment",
            "x-is-trigger": False,
            "x-display-name": "Create Channel Discussion Comment",
            "x-keywords": [
                "channel discussion",
                "comment on channel",
                "channel community post",
                "discussion tab comment",
            ],
        },
        title="Create Channel Discussion Comment",
    )
    channel_id: str = Field(
        ..., title="Channel ID", description="Channel to comment on"
    )
    text: str = Field(
        ...,
        title="Comment Text",
        description="The comment text",
        json_schema_extra={"ui:widget": "textarea"},
    )


class YouTubeUpdateCommentConfig(BaseModel):
    """Update a comment"""

    model_config = ConfigDict(title="Update Comment")

    operation: Literal["update_comment"] = Field(
        default="update_comment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Comment",
            "x-is-trigger": False,
            "x-display-name": "Update Comment",
            "x-keywords": ["edit comment", "change comment text", "rephrase comment"],
        },
        title="Update Comment",
    )
    comment_id: str = Field(
        ..., title="Comment ID", description="The comment ID to update"
    )
    text: str = Field(
        ...,
        title="Comment Text",
        description="The updated comment text",
        json_schema_extra={"ui:widget": "textarea"},
    )


class YouTubeDeleteCommentConfig(BaseModel):
    """Delete a comment"""

    model_config = ConfigDict(title="Delete Comment")

    operation: Literal["delete_comment"] = Field(
        default="delete_comment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Comment",
            "x-is-trigger": False,
            "x-display-name": "Delete Comment",
            "x-keywords": ["remove comment", "trash comment", "take down comment"],
        },
        title="Delete Comment",
    )
    comment_id: str = Field(
        ..., title="Comment ID", description="The comment ID to delete"
    )


class YouTubeSetCommentModerationConfig(BaseModel):
    """Set moderation status for a comment"""

    model_config = ConfigDict(title="Moderate Comment")

    operation: Literal["set_comment_moderation_status"] = Field(
        default="set_comment_moderation_status",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Comment",
            "x-is-trigger": False,
            "x-display-name": "Set Comment Moderation Status",
            "x-keywords": [
                "moderate comment",
                "approve comment",
                "reject comment",
                "hold comment",
                "mark spam",
            ],
        },
        title="Set Comment Moderation Status",
    )
    comment_ids: str = Field(
        ..., title="Comment IDs", description="Comma-separated comment IDs"
    )
    moderation_status: str = Field(
        ...,
        title="Moderation Status",
        description="Status (heldForReview, published, rejected)",
    )
    ban_author: Optional[bool] = Field(
        default=False, title="Ban Author", description="Ban the comment author"
    )


# ============================================================================
# Subscription Configs
# ============================================================================


class YouTubeListSubscriptionsConfig(BaseModel):
    """List subscriptions"""

    model_config = ConfigDict(title="List Subscriptions")

    operation: Literal["list_subscriptions"] = Field(
        default="list_subscriptions",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Subscription",
            "x-is-trigger": False,
            "x-display-name": "List Subscriptions",
            "x-keywords": [
                "my subscriptions",
                "channels i follow",
                "subscribed channels",
            ],
        },
        title="List Subscriptions",
    )
    part: str = Field(default="snippet,contentDetails", title="Parts")
    mine: Optional[bool] = Field(
        default=True, title="Mine", description="List my subscriptions"
    )
    channel_id: Optional[str] = Field(
        default=None,
        title="Channel ID",
        description="Channel to list subscriptions for",
    )
    for_channel_id: Optional[str] = Field(
        default=None,
        title="For Channel ID",
        description="Filter subscriptions to a specific channel",
    )
    order: Optional[str] = Field(
        default="relevance",
        title="Order",
        description="Sort order (alphabetical, relevance, unread)",
    )
    max_results: Optional[int] = Field(default=50, title="Max Results")


class YouTubeSubscribeConfig(BaseModel):
    """Subscribe to a channel"""

    model_config = ConfigDict(title="Subscribe")

    operation: Literal["subscribe_to_channel"] = Field(
        default="subscribe_to_channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Subscription",
            "x-is-trigger": False,
            "x-display-name": "Subscribe to Channel",
            "x-keywords": ["subscribe channel", "follow channel", "hit subscribe"],
        },
        title="Subscribe to Channel",
    )
    channel_id: str = Field(
        ..., title="Channel ID", description="The channel ID to subscribe to"
    )


class YouTubeUnsubscribeConfig(BaseModel):
    """Unsubscribe from a channel"""

    model_config = ConfigDict(title="Unsubscribe")

    operation: Literal["unsubscribe_from_channel"] = Field(
        default="unsubscribe_from_channel",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Subscription",
            "x-is-trigger": False,
            "x-display-name": "Unsubscribe from Channel",
            "x-keywords": ["unsubscribe channel", "unfollow channel", "stop following"],
        },
        title="Unsubscribe from Channel",
    )
    subscription_id: str = Field(
        ..., title="Subscription ID", description="The subscription ID to remove"
    )


# ============================================================================
# Caption Configs
# ============================================================================


class YouTubeListCaptionsConfig(BaseModel):
    """List captions for a video"""

    model_config = ConfigDict(title="List Captions")

    operation: Literal["list_video_captions"] = Field(
        default="list_video_captions",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Caption",
            "x-is-trigger": False,
            "x-display-name": "List Video Captions",
            "x-keywords": [
                "video captions",
                "subtitle tracks",
                "available subtitles",
                "closed captions",
            ],
        },
        title="List Video Captions",
    )
    video_id: str = Field(..., title="Video ID", description="The video ID")
    part: str = Field(default="snippet", title="Parts")


class YouTubeDownloadCaptionConfig(BaseModel):
    """Download a caption track"""

    model_config = ConfigDict(title="Download Caption")

    operation: Literal["download_caption_track"] = Field(
        default="download_caption_track",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Caption",
            "x-is-trigger": False,
            "x-display-name": "Download Caption Track",
            "x-keywords": [
                "download captions",
                "export subtitles",
                "get caption file",
                "save srt",
            ],
        },
        title="Download Caption Track",
    )
    caption_id: str = Field(..., title="Caption ID", description="The caption track ID")
    tfmt: Optional[str] = Field(
        default=None,
        title="Format",
        description="Caption format (sbv, scc, srt, ttml, vtt)",
    )


# ============================================================================
# Activity Configs
# ============================================================================


class YouTubeListMyActivitiesConfig(BaseModel):
    """List your channel activities"""

    model_config = ConfigDict(title="Get My Activities")

    operation: Literal["list_authenticated_user_activities"] = Field(
        default="list_authenticated_user_activities",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Activity",
            "x-is-trigger": False,
            "x-display-name": "List Authenticated User Activities",
            "x-keywords": [
                "my channel activity",
                "my recent actions",
                "own activity feed",
            ],
        },
        title="List Authenticated User Activities",
    )
    part: str = Field(default="snippet,contentDetails", title="Parts")
    published_after: Optional[str] = Field(
        default=None, title="Published After", description="RFC 3339 timestamp"
    )
    published_before: Optional[str] = Field(
        default=None, title="Published Before", description="RFC 3339 timestamp"
    )
    max_results: Optional[int] = Field(default=25, title="Max Results")


class YouTubeListChannelActivitiesConfig(BaseModel):
    """List activities for a specific channel"""

    model_config = ConfigDict(title="Get Channel Activities")

    operation: Literal["list_channel_activities"] = Field(
        default="list_channel_activities",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "List Channel Activities",
            "x-keywords": [
                "channel activity",
                "recent channel actions",
                "another channel activity",
            ],
        },
        title="List Channel Activities",
    )
    channel_id: str = Field(
        ..., title="Channel ID", description="Channel to get activities for"
    )
    part: str = Field(default="snippet,contentDetails", title="Parts")
    published_after: Optional[str] = Field(
        default=None, title="Published After", description="RFC 3339 timestamp"
    )
    published_before: Optional[str] = Field(
        default=None, title="Published Before", description="RFC 3339 timestamp"
    )
    max_results: Optional[int] = Field(default=25, title="Max Results")


# ============================================================================
# Category and Localization Configs
# ============================================================================


class YouTubeListVideoCategoriesConfig(BaseModel):
    """List video categories"""

    model_config = ConfigDict(title="List Video Categories")

    operation: Literal["list_video_categories"] = Field(
        default="list_video_categories",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Video Category",
            "x-is-trigger": False,
            "x-display-name": "List Video Categories",
            "x-keywords": ["video categories", "available categories", "category list"],
        },
        title="List Video Categories",
    )
    part: str = Field(default="snippet", title="Parts")
    region_code: Optional[str] = Field(
        default="US", title="Region Code", description="ISO 3166-1 alpha-2 country code"
    )
    hl: Optional[str] = Field(
        default="en", title="Language", description="Language for localized text"
    )


class YouTubeListLanguagesConfig(BaseModel):
    """List supported languages"""

    model_config = ConfigDict(title="List Languages")

    operation: Literal["list_supported_languages"] = Field(
        default="list_supported_languages",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Language",
            "x-is-trigger": False,
            "x-display-name": "List Supported Languages",
            "x-keywords": [
                "supported languages",
                "available languages",
                "language list",
                "i18n languages",
            ],
        },
        title="List Supported Languages",
    )
    part: str = Field(default="snippet", title="Parts")
    hl: Optional[str] = Field(
        default="en", title="Language", description="Language for localized names"
    )


class YouTubeListRegionsConfig(BaseModel):
    """List supported regions"""

    model_config = ConfigDict(title="List Regions")

    operation: Literal["list_supported_regions"] = Field(
        default="list_supported_regions",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Region",
            "x-is-trigger": False,
            "x-display-name": "List Supported Regions",
            "x-keywords": [
                "supported regions",
                "available countries",
                "region list",
                "i18n regions",
            ],
        },
        title="List Supported Regions",
    )
    part: str = Field(default="snippet", title="Parts")
    hl: Optional[str] = Field(
        default="en", title="Language", description="Language for localized names"
    )


# ============================================================================
# Channel Sections Config
# ============================================================================


class YouTubeListMyChannelSectionsConfig(BaseModel):
    """List your channel sections"""

    model_config = ConfigDict(title="Get My Channel Sections")

    operation: Literal["list_authenticated_user_channel_sections"] = Field(
        default="list_authenticated_user_channel_sections",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "List Authenticated User Channel Sections",
            "x-keywords": [
                "my channel sections",
                "my homepage layout",
                "own channel shelves",
            ],
        },
        title="List Authenticated User Channel Sections",
    )
    part: str = Field(default="snippet,contentDetails", title="Parts")


class YouTubeListChannelSectionsConfig(BaseModel):
    """List channel sections for a specific channel"""

    model_config = ConfigDict(title="Get Channel Sections")

    operation: Literal["list_channel_sections"] = Field(
        default="list_channel_sections",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "List Channel Sections",
            "x-keywords": [
                "channel sections",
                "channel shelves",
                "homepage layout sections",
            ],
        },
        title="List Channel Sections",
    )
    channel_id: str = Field(
        ..., title="Channel ID", description="The channel ID to get sections for"
    )
    part: str = Field(default="snippet,contentDetails", title="Parts")


# ============================================================================
# Analytics API Configs
# ============================================================================


class YouTubeGetChannelAnalyticsConfig(BaseModel):
    """Get analytics for your channel (views, watch time, subscribers, etc.)"""

    model_config = ConfigDict(title="Get Channel Analytics")

    operation: Literal["get_channel_analytics"] = Field(
        default="get_channel_analytics",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Channel",
            "x-is-trigger": False,
            "x-display-name": "Get Channel Analytics",
            "x-keywords": [
                "channel stats",
                "views watch time",
                "subscriber metrics",
                "channel performance",
            ],
        },
        title="Get Channel Analytics",
    )
    start_date: str = Field(
        ..., title="Start Date", description="Start date in YYYY-MM-DD format"
    )
    end_date: str = Field(
        ..., title="End Date", description="End date in YYYY-MM-DD format"
    )
    metrics: str = Field(
        default="views,estimatedMinutesWatched,averageViewDuration,subscribersGained,subscribersLost",
        title="Metrics",
        description="Comma-separated metrics: views, estimatedMinutesWatched, averageViewDuration, subscribersGained, subscribersLost, likes, dislikes, comments, shares",
    )
    dimensions: Optional[str] = Field(
        default=None,
        title="Dimensions",
        description="Comma-separated dimensions to group by: day, month, video, country, deviceType, operatingSystem",
    )
    filters: Optional[str] = Field(
        default=None,
        title="Filters",
        description="Filter expression (e.g., country==US, video==VIDEO_ID)",
    )
    sort: Optional[str] = Field(
        default=None,
        title="Sort",
        description="Sort order (e.g., -views for descending by views)",
    )
    max_results: Optional[int] = Field(default=200, title="Max Results")


class YouTubeGetVideoAnalyticsConfig(BaseModel):
    """Get analytics for specific videos"""

    model_config = ConfigDict(title="Get Video Analytics")

    operation: Literal["get_video_analytics"] = Field(
        default="get_video_analytics",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Video",
            "x-is-trigger": False,
            "x-display-name": "Get Video Analytics",
            "x-keywords": [
                "video stats",
                "video performance",
                "per video metrics",
                "video views",
            ],
        },
        title="Get Video Analytics",
    )
    video_id: str = Field(
        ..., title="Video ID", description="The video ID to get analytics for"
    )
    start_date: str = Field(
        ..., title="Start Date", description="Start date in YYYY-MM-DD format"
    )
    end_date: str = Field(
        ..., title="End Date", description="End date in YYYY-MM-DD format"
    )
    metrics: str = Field(
        default="views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,likes,dislikes,comments,shares",
        title="Metrics",
        description="Comma-separated metrics to retrieve",
    )
    dimensions: Optional[str] = Field(
        default=None,
        title="Dimensions",
        description="Comma-separated dimensions: day, country, deviceType, operatingSystem, subscribedStatus, trafficSourceType",
    )


class YouTubeGetRevenueAnalyticsConfig(BaseModel):
    """Get revenue analytics for your channel (requires monetization)"""

    model_config = ConfigDict(title="Get Revenue Analytics")

    operation: Literal["get_channel_revenue_analytics"] = Field(
        default="get_channel_revenue_analytics",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Analytics",
            "x-is-trigger": False,
            "x-display-name": "Get Channel Revenue Analytics",
            "x-keywords": [
                "revenue stats",
                "ad earnings",
                "monetization income",
                "estimated revenue",
                "money earned",
            ],
        },
        title="Get Channel Revenue Analytics",
    )
    start_date: str = Field(
        ..., title="Start Date", description="Start date in YYYY-MM-DD format"
    )
    end_date: str = Field(
        ..., title="End Date", description="End date in YYYY-MM-DD format"
    )
    metrics: str = Field(
        default="estimatedRevenue,estimatedAdRevenue,grossRevenue,estimatedRedPartnerRevenue,cpm,adImpressions,monetizedPlaybacks",
        title="Metrics",
        description="Revenue metrics: estimatedRevenue, estimatedAdRevenue, grossRevenue, cpm, adImpressions, monetizedPlaybacks",
    )
    dimensions: Optional[str] = Field(
        default="day",
        title="Dimensions",
        description="Dimensions: day, month, video, country, adType",
    )


class YouTubeGetTopVideosConfig(BaseModel):
    """Get your top performing videos by various metrics"""

    model_config = ConfigDict(title="Get Top Videos")

    operation: Literal["get_top_performing_videos"] = Field(
        default="get_top_performing_videos",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Video",
            "x-is-trigger": False,
            "x-display-name": "Get Top Performing Videos",
            "x-keywords": [
                "best videos",
                "top videos",
                "highest performing",
                "most successful videos",
            ],
        },
        title="Get Top Performing Videos",
    )
    start_date: str = Field(
        ..., title="Start Date", description="Start date in YYYY-MM-DD format"
    )
    end_date: str = Field(
        ..., title="End Date", description="End date in YYYY-MM-DD format"
    )
    metric: str = Field(
        default="estimatedMinutesWatched",
        title="Sort By Metric",
        description="Metric to rank by: views, estimatedMinutesWatched, subscribersGained, likes",
    )
    max_results: int = Field(
        default=10,
        title="Number of Videos",
        description="Number of top videos to return (max 200)",
    )


class YouTubeGetDemographicsConfig(BaseModel):
    """Get viewer demographics (age, gender)"""

    model_config = ConfigDict(title="Get Viewer Demographics")

    operation: Literal["get_viewer_demographics"] = Field(
        default="get_viewer_demographics",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Analytics",
            "x-is-trigger": False,
            "x-display-name": "Get Viewer Demographics",
            "x-keywords": [
                "audience demographics",
                "age gender",
                "viewer breakdown",
                "who watches",
            ],
        },
        title="Get Viewer Demographics",
    )
    start_date: str = Field(
        ..., title="Start Date", description="Start date in YYYY-MM-DD format"
    )
    end_date: str = Field(
        ..., title="End Date", description="End date in YYYY-MM-DD format"
    )


class YouTubeGetTrafficSourcesConfig(BaseModel):
    """Get traffic source breakdown for your channel"""

    model_config = ConfigDict(title="Get Traffic Sources")

    operation: Literal["get_channel_traffic_sources"] = Field(
        default="get_channel_traffic_sources",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Analytics",
            "x-is-trigger": False,
            "x-display-name": "Get Channel Traffic Sources",
            "x-keywords": [
                "traffic sources",
                "where views come from",
                "discovery breakdown",
                "referral sources",
            ],
        },
        title="Get Channel Traffic Sources",
    )
    start_date: str = Field(
        ..., title="Start Date", description="Start date in YYYY-MM-DD format"
    )
    end_date: str = Field(
        ..., title="End Date", description="End date in YYYY-MM-DD format"
    )


# ============================================================================
# Reporting API Configs
# ============================================================================


class YouTubeListReportTypesConfig(BaseModel):
    """List available report types for bulk reporting"""

    model_config = ConfigDict(title="List Report Types")

    operation: Literal["list_bulk_reporting_types"] = Field(
        default="list_bulk_reporting_types",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Reporting Job",
            "x-is-trigger": False,
            "x-display-name": "List Bulk Reporting Types",
            "x-keywords": [
                "report types",
                "available bulk reports",
                "reporting report types",
            ],
        },
        title="List Bulk Reporting Types",
    )


class YouTubeCreateReportingJobConfig(BaseModel):
    """Create a scheduled reporting job"""

    model_config = ConfigDict(title="Create Reporting Job")

    operation: Literal["create_reporting_job"] = Field(
        default="create_reporting_job",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Reporting Job",
            "x-is-trigger": False,
            "x-display-name": "Create Reporting Job",
            "x-keywords": [
                "schedule bulk report",
                "new reporting job",
                "set up bulk report",
            ],
        },
        title="Create Reporting Job",
    )
    report_type_id: str = Field(
        ...,
        title="Report Type ID",
        description="The report type ID from list_report_types",
    )
    name: str = Field(
        ..., title="Job Name", description="A name for this reporting job"
    )


class YouTubeListReportingJobsConfig(BaseModel):
    """List all scheduled reporting jobs"""

    model_config = ConfigDict(title="List Reporting Jobs")

    operation: Literal["list_reporting_jobs"] = Field(
        default="list_reporting_jobs",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Reporting Job",
            "x-is-trigger": False,
            "x-display-name": "List Reporting Jobs",
            "x-keywords": ["reporting jobs", "scheduled reports", "all bulk reports"],
        },
        title="List Reporting Jobs",
    )


class YouTubeGetReportingJobConfig(BaseModel):
    """Get details of a specific reporting job"""

    model_config = ConfigDict(title="Get Reporting Job")

    operation: Literal["get_reporting_job"] = Field(
        default="get_reporting_job",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Reporting Job",
            "x-is-trigger": False,
            "x-display-name": "Get Reporting Job",
            "x-keywords": [
                "single reporting job",
                "one bulk report",
                "reporting job details",
            ],
        },
        title="Get Reporting Job",
    )
    job_id: str = Field(..., title="Job ID", description="The reporting job ID")


class YouTubeDeleteReportingJobConfig(BaseModel):
    """Delete a reporting job"""

    model_config = ConfigDict(title="Delete Reporting Job")

    operation: Literal["delete_reporting_job"] = Field(
        default="delete_reporting_job",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Reporting Job",
            "x-is-trigger": False,
            "x-display-name": "Delete Reporting Job",
            "x-keywords": [
                "remove reporting job",
                "cancel bulk report",
                "stop scheduled report",
            ],
        },
        title="Delete Reporting Job",
    )
    job_id: str = Field(
        ..., title="Job ID", description="The reporting job ID to delete"
    )


class YouTubeListReportsConfig(BaseModel):
    """List reports generated by a reporting job"""

    model_config = ConfigDict(title="List Reports")

    operation: Literal["list_reporting_job_reports"] = Field(
        default="list_reporting_job_reports",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Reporting Job",
            "x-is-trigger": False,
            "x-display-name": "List Reporting Job Reports",
            "x-keywords": [
                "generated reports",
                "report files",
                "downloadable reports",
                "job report outputs",
            ],
        },
        title="List Reporting Job Reports",
    )
    job_id: str = Field(..., title="Job ID", description="The reporting job ID")


# ============================================================================
# Live Streaming API - Broadcasts
# ============================================================================


class YouTubeListBroadcastsConfig(BaseModel):
    """List live broadcasts"""

    model_config = ConfigDict(title="List Live Broadcasts")

    operation: Literal["list_live_broadcasts"] = Field(
        default="list_live_broadcasts",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Live Broadcast",
            "x-is-trigger": False,
            "x-display-name": "List Live Broadcasts",
            "x-keywords": [
                "livestreams",
                "live broadcasts",
                "scheduled streams",
                "my broadcasts",
            ],
        },
        title="List Live Broadcasts",
    )
    broadcast_status: Optional[str] = Field(
        default=None,
        title="Broadcast Status",
        description="Filter by status: all, active, completed, upcoming",
    )
    mine: bool = Field(
        default=True,
        title="Mine Only",
        description="Only return broadcasts owned by authenticated user",
    )
    part: str = Field(default="snippet,contentDetails,status", title="Parts")
    max_results: Optional[int] = Field(default=25, title="Max Results")


class YouTubeCreateBroadcastConfig(BaseModel):
    """Create a new live broadcast"""

    model_config = ConfigDict(title="Create Live Broadcast")

    operation: Literal["create_live_broadcast"] = Field(
        default="create_live_broadcast",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Live Broadcast",
            "x-is-trigger": False,
            "x-display-name": "Create Live Broadcast",
            "x-keywords": [
                "schedule livestream",
                "new broadcast",
                "set up live event",
                "go live setup",
            ],
        },
        title="Create Live Broadcast",
    )
    title: str = Field(..., title="Title", description="Broadcast title")
    description: Optional[str] = Field(
        default=None, title="Description", json_schema_extra={"ui:widget": "textarea"}
    )
    scheduled_start_time: str = Field(
        ...,
        title="Scheduled Start Time",
        description="ISO 8601 datetime (e.g., 2024-12-25T10:00:00Z)",
    )
    privacy_status: str = Field(
        default="private",
        title="Privacy Status",
        description="public, private, or unlisted",
    )
    made_for_kids: bool = Field(default=False, title="Made for Kids")
    enable_auto_start: bool = Field(
        default=False,
        title="Enable Auto Start",
        description="Auto start when stream goes live",
    )
    enable_auto_stop: bool = Field(
        default=False,
        title="Enable Auto Stop",
        description="Auto stop when stream ends",
    )
    enable_dvr: bool = Field(
        default=True, title="Enable DVR", description="Allow viewers to rewind"
    )
    enable_live_chat: bool = Field(default=True, title="Enable Live Chat")


class YouTubeUpdateBroadcastConfig(BaseModel):
    """Update a live broadcast"""

    model_config = ConfigDict(title="Update Live Broadcast")

    operation: Literal["update_live_broadcast"] = Field(
        default="update_live_broadcast",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Live Broadcast",
            "x-is-trigger": False,
            "x-display-name": "Update Live Broadcast",
            "x-keywords": [
                "edit broadcast",
                "change livestream details",
                "broadcast settings",
            ],
        },
        title="Update Live Broadcast",
    )
    broadcast_id: str = Field(
        ..., title="Broadcast ID", description="The broadcast ID to update"
    )
    title: Optional[str] = Field(default=None, title="Title")
    description: Optional[str] = Field(
        default=None, title="Description", json_schema_extra={"ui:widget": "textarea"}
    )
    privacy_status: Optional[str] = Field(
        default=None, title="Privacy Status", description="public, private, or unlisted"
    )


class YouTubeDeleteBroadcastConfig(BaseModel):
    """Delete a live broadcast"""

    model_config = ConfigDict(title="Delete Live Broadcast")

    operation: Literal["delete_live_broadcast"] = Field(
        default="delete_live_broadcast",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Live Broadcast",
            "x-is-trigger": False,
            "x-display-name": "Delete Live Broadcast",
            "x-keywords": [
                "remove broadcast",
                "cancel livestream",
                "delete live event",
            ],
        },
        title="Delete Live Broadcast",
    )
    broadcast_id: str = Field(
        ..., title="Broadcast ID", description="The broadcast ID to delete"
    )


class YouTubeTransitionBroadcastConfig(BaseModel):
    """Transition broadcast to a new status (start/end)"""

    model_config = ConfigDict(title="Transition Live Broadcast")

    operation: Literal["transition_broadcast_status"] = Field(
        default="transition_broadcast_status",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Live Broadcast",
            "x-is-trigger": False,
            "x-display-name": "Transition Broadcast Status",
            "x-keywords": [
                "start broadcast",
                "end stream",
                "go live now",
                "stop streaming",
                "change broadcast state",
            ],
        },
        title="Transition Broadcast Status",
    )
    broadcast_id: str = Field(..., title="Broadcast ID")
    broadcast_status: str = Field(
        ..., title="New Status", description="testing, live, or complete"
    )


class YouTubeBindBroadcastConfig(BaseModel):
    """Bind a broadcast to a stream"""

    model_config = ConfigDict(title="Bind Broadcast to Stream")

    operation: Literal["bind_broadcast_to_stream"] = Field(
        default="bind_broadcast_to_stream",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Live Broadcast",
            "x-is-trigger": False,
            "x-display-name": "Bind Broadcast to Stream",
            "x-keywords": [
                "bind stream",
                "attach stream",
                "link broadcast stream",
                "connect encoder",
            ],
        },
        title="Bind Broadcast to Stream",
    )
    broadcast_id: str = Field(..., title="Broadcast ID")
    stream_id: Optional[str] = Field(
        default=None,
        title="Stream ID",
        description="Stream ID to bind (leave empty to unbind)",
    )


# ============================================================================
# Live Streaming API - Streams
# ============================================================================


class YouTubeListStreamsConfig(BaseModel):
    """List live streams"""

    model_config = ConfigDict(title="List Live Streams")

    operation: Literal["list_live_streams"] = Field(
        default="list_live_streams",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Live Stream",
            "x-is-trigger": False,
            "x-display-name": "List Live Streams",
            "x-keywords": [
                "live streams",
                "stream ingestions",
                "encoder streams",
                "my streams",
            ],
        },
        title="List Live Streams",
    )
    mine: bool = Field(default=True, title="Mine Only")
    part: str = Field(default="snippet,cdn,contentDetails,status", title="Parts")
    max_results: Optional[int] = Field(default=25, title="Max Results")


class YouTubeCreateStreamConfig(BaseModel):
    """Create a new live stream"""

    model_config = ConfigDict(title="Create Live Stream")

    operation: Literal["create_live_stream"] = Field(
        default="create_live_stream",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Live Stream",
            "x-is-trigger": False,
            "x-display-name": "Create Live Stream",
            "x-keywords": [
                "new stream",
                "create ingestion",
                "set up encoder stream",
                "rtmp stream",
            ],
        },
        title="Create Live Stream",
    )
    title: str = Field(..., title="Title", description="Stream title")
    description: Optional[str] = Field(default=None, title="Description")
    frame_rate: str = Field(
        default="variable", title="Frame Rate", description="30fps, 60fps, or variable"
    )
    resolution: str = Field(
        default="variable",
        title="Resolution",
        description="240p, 360p, 480p, 720p, 1080p, 1440p, 2160p, or variable",
    )
    ingestion_type: str = Field(
        default="rtmp", title="Ingestion Type", description="rtmp, dash, webrtc, or hls"
    )


class YouTubeUpdateStreamConfig(BaseModel):
    """Update a live stream"""

    model_config = ConfigDict(title="Update Live Stream")

    operation: Literal["update_live_stream"] = Field(
        default="update_live_stream",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Live Stream",
            "x-is-trigger": False,
            "x-display-name": "Update Live Stream",
            "x-keywords": ["edit stream", "change stream settings", "stream config"],
        },
        title="Update Live Stream",
    )
    stream_id: str = Field(..., title="Stream ID")
    title: Optional[str] = Field(default=None, title="Title")
    description: Optional[str] = Field(default=None, title="Description")


class YouTubeDeleteStreamConfig(BaseModel):
    """Delete a live stream"""

    model_config = ConfigDict(title="Delete Live Stream")

    operation: Literal["delete_live_stream"] = Field(
        default="delete_live_stream",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Live Stream",
            "x-is-trigger": False,
            "x-display-name": "Delete Live Stream",
            "x-keywords": [
                "delete rtmp stream",
                "remove ingestion stream",
                "delete stream key",
                "tear down livestream",
            ],
        },
        title="Delete Live Stream",
    )
    stream_id: str = Field(..., title="Stream ID")


# ============================================================================
# Live Streaming API - Live Chat
# ============================================================================


class YouTubeListLiveChatMessagesConfig(BaseModel):
    """List messages from a live chat"""

    model_config = ConfigDict(title="List Live Chat Messages")

    operation: Literal["list_live_chat_messages"] = Field(
        default="list_live_chat_messages",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Live Chat",
            "x-is-trigger": False,
            "x-display-name": "List Live Chat Messages",
            "x-keywords": [
                "read live chat",
                "stream chat messages",
                "fetch livestream chat",
                "live chat feed",
            ],
        },
        title="List Live Chat Messages",
    )
    live_chat_id: str = Field(
        ..., title="Live Chat ID", description="The live chat ID (from broadcast)"
    )
    part: str = Field(default="snippet,authorDetails", title="Parts")
    max_results: Optional[int] = Field(default=200, title="Max Results")
    page_token: Optional[str] = Field(default=None, title="Page Token")


class YouTubeSendLiveChatMessageConfig(BaseModel):
    """Send a message to live chat"""

    model_config = ConfigDict(title="Send Live Chat Message")

    operation: Literal["send_live_chat_message"] = Field(
        default="send_live_chat_message",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Live Chat",
            "x-is-trigger": False,
            "x-display-name": "Send Live Chat Message",
            "x-keywords": [
                "post live chat",
                "chat in livestream",
                "write chat message",
                "say in chat",
            ],
        },
        title="Send Live Chat Message",
    )
    live_chat_id: str = Field(..., title="Live Chat ID")
    message: str = Field(..., title="Message", description="Message text to send")


class YouTubeDeleteLiveChatMessageConfig(BaseModel):
    """Delete a message from live chat"""

    model_config = ConfigDict(title="Delete Live Chat Message")

    operation: Literal["delete_live_chat_message"] = Field(
        default="delete_live_chat_message",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Live Chat",
            "x-is-trigger": False,
            "x-display-name": "Delete Live Chat Message",
            "x-keywords": [
                "delete chat message",
                "remove livestream chat",
                "purge chat message",
            ],
        },
        title="Delete Live Chat Message",
    )
    message_id: str = Field(..., title="Message ID")


class YouTubeListLiveChatModeratorsConfig(BaseModel):
    """List moderators for a live chat"""

    model_config = ConfigDict(title="List Live Chat Moderators")

    operation: Literal["list_live_chat_moderators"] = Field(
        default="list_live_chat_moderators",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Live Chat",
            "x-is-trigger": False,
            "x-display-name": "List Live Chat Moderators",
            "x-keywords": [
                "live chat mods",
                "stream moderators list",
                "chat moderator list",
            ],
        },
        title="List Live Chat Moderators",
    )
    live_chat_id: str = Field(..., title="Live Chat ID")
    max_results: Optional[int] = Field(default=50, title="Max Results")


class YouTubeAddLiveChatModeratorConfig(BaseModel):
    """Add a moderator to live chat"""

    model_config = ConfigDict(title="Add Live Chat Moderator")

    operation: Literal["add_live_chat_moderator"] = Field(
        default="add_live_chat_moderator",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Live Chat",
            "x-is-trigger": False,
            "x-display-name": "Add Live Chat Moderator",
            "x-keywords": [
                "make chat mod",
                "add chat moderator",
                "promote stream moderator",
                "assign chat mod",
            ],
        },
        title="Add Live Chat Moderator",
    )
    live_chat_id: str = Field(..., title="Live Chat ID")
    channel_id: str = Field(
        ..., title="Channel ID", description="Channel ID of user to make moderator"
    )


class YouTubeRemoveLiveChatModeratorConfig(BaseModel):
    """Remove a moderator from live chat"""

    model_config = ConfigDict(title="Remove Live Chat Moderator")

    operation: Literal["remove_live_chat_moderator"] = Field(
        default="remove_live_chat_moderator",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Live Chat",
            "x-is-trigger": False,
            "x-display-name": "Remove Live Chat Moderator",
            "x-keywords": [
                "demote chat mod",
                "remove chat moderator",
                "strip moderator role",
                "unmod chat user",
            ],
        },
        title="Remove Live Chat Moderator",
    )
    moderator_id: str = Field(..., title="Moderator ID")


class YouTubeBanLiveChatUserConfig(BaseModel):
    """Ban a user from live chat"""

    model_config = ConfigDict(title="Ban Live Chat User")

    operation: Literal["ban_live_chat_user"] = Field(
        default="ban_live_chat_user",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Live Chat",
            "x-is-trigger": False,
            "x-display-name": "Ban Live Chat User",
            "x-keywords": [
                "ban chat viewer",
                "block chat user",
                "timeout chat user",
                "kick from chat",
            ],
        },
        title="Ban Live Chat User",
    )
    live_chat_id: str = Field(..., title="Live Chat ID")
    channel_id: str = Field(
        ..., title="Channel ID", description="Channel ID of user to ban"
    )
    ban_type: str = Field(
        default="permanent", title="Ban Type", description="permanent or temporary"
    )
    ban_duration_seconds: Optional[int] = Field(
        default=None,
        title="Ban Duration (seconds)",
        description="Duration for temporary bans",
    )


class YouTubeUnbanLiveChatUserConfig(BaseModel):
    """Remove a ban from live chat"""

    model_config = ConfigDict(title="Unban Live Chat User")

    operation: Literal["unban_live_chat_user"] = Field(
        default="unban_live_chat_user",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Live Chat",
            "x-is-trigger": False,
            "x-display-name": "Unban Live Chat User",
            "x-keywords": [
                "unban chat viewer",
                "lift chat ban",
                "remove chat ban",
                "restore banned user",
            ],
        },
        title="Unban Live Chat User",
    )
    ban_id: str = Field(..., title="Ban ID")


class YouTubeListSuperChatEventsConfig(BaseModel):
    """List Super Chat events from live streams"""

    model_config = ConfigDict(title="List Super Chat Events")

    operation: Literal["list_super_chat_events"] = Field(
        default="list_super_chat_events",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Super Chat",
            "x-is-trigger": False,
            "x-display-name": "List Super Chat Events",
            "x-keywords": [
                "super chat donations",
                "paid chat messages",
                "stream tips list",
                "superchat history",
            ],
        },
        title="List Super Chat Events",
    )
    max_results: Optional[int] = Field(default=50, title="Max Results")


# ============================================================================
# Additional Data API Configs
# ============================================================================


class YouTubeSetThumbnailConfig(BaseModel):
    """Set a custom thumbnail for a video"""

    model_config = ConfigDict(title="Set Video Thumbnail")

    operation: Literal["set_video_thumbnail"] = Field(
        default="set_video_thumbnail",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Video",
            "x-is-trigger": False,
            "x-display-name": "Set Video Thumbnail",
            "x-keywords": [
                "video thumbnail",
                "custom thumbnail",
                "change thumbnail",
                "set cover image",
            ],
        },
        title="Set Video Thumbnail",
    )
    video_id: str = Field(..., title="Video ID")
    thumbnail_url: str = Field(
        ...,
        title="Thumbnail",
        description="The thumbnail to send — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}). Image (JPEG, PNG, GIF, BMP), max 2MB.",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": "image/*"},
    )


class YouTubeListMembersConfig(BaseModel):
    """List channel members (requires channel membership feature)"""

    model_config = ConfigDict(title="List Channel Members")

    operation: Literal["list_channel_members"] = Field(
        default="list_channel_members",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Member",
            "x-is-trigger": False,
            "x-display-name": "List Channel Members",
            "x-keywords": [
                "channel members",
                "paid memberships",
                "channel sponsors",
                "membership roster",
            ],
        },
        title="List Channel Members",
    )
    mode: str = Field(
        default="all_current", title="Mode", description="all_current or updates"
    )
    max_results: Optional[int] = Field(default=100, title="Max Results")


class YouTubeListMembershipLevelsConfig(BaseModel):
    """List channel membership levels"""

    model_config = ConfigDict(title="List Membership Levels")

    operation: Literal["list_membership_levels"] = Field(
        default="list_membership_levels",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Member",
            "x-is-trigger": False,
            "x-display-name": "List Membership Levels",
            "x-keywords": [
                "membership levels",
                "membership tiers",
                "sponsor levels",
                "perk tiers",
            ],
        },
        title="List Membership Levels",
    )


# ============================================================================
# Union of all config types - with explicit discriminator
# ============================================================================
#
# IMPORTANT: Using Annotated[Union[...], Discriminator('operation')] tells Pydantic to:
# 1. ONLY look at the 'operation' field to choose which union member to use
# 2. Once a member is chosen, validate ONLY that member's fields
# 3. If validation fails (e.g., missing required field), report errors for THAT member only
#
# Without the Discriminator, Pydantic tries ALL 167 union members when ANY field fails,
# resulting in 167 validation errors instead of the 1-3 actual errors.

YouTubeConfig = Annotated[
    Union[
        # Videos
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
        # Channels
        YouTubeListChannelsConfig,
        YouTubeGetMyChannelConfig,
        YouTubeUpdateChannelConfig,
        # Playlists
        YouTubeListMyPlaylistsConfig,
        YouTubeListPlaylistsByIdConfig,
        YouTubeListChannelPlaylistsConfig,
        YouTubeGetPlaylistConfig,
        YouTubeCreatePlaylistConfig,
        YouTubeUpdatePlaylistConfig,
        YouTubeDeletePlaylistConfig,
        # Playlist Items
        YouTubeListPlaylistItemsConfig,
        YouTubeAddPlaylistItemConfig,
        YouTubeUpdatePlaylistItemConfig,
        YouTubeDeletePlaylistItemConfig,
        # Search
        YouTubeSearchConfig,
        # Comments
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
        # Subscriptions
        YouTubeListSubscriptionsConfig,
        YouTubeSubscribeConfig,
        YouTubeUnsubscribeConfig,
        # Captions
        YouTubeListCaptionsConfig,
        YouTubeDownloadCaptionConfig,
        # Activities
        YouTubeListMyActivitiesConfig,
        YouTubeListChannelActivitiesConfig,
        # Categories & Localization
        YouTubeListVideoCategoriesConfig,
        YouTubeListLanguagesConfig,
        YouTubeListRegionsConfig,
        # Channel Sections
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
    ],
    Discriminator(
        "operation"
    ),  # Tell Pydantic to use 'operation' field for union discrimination
]


class YouTubeNodeConfig(NodeConfig[YouTubeConfig, YouTubeOAuthCredential]):
    """Full configuration for YouTube node including credentials"""

    pass


# ============================================================================
# YouTube Node Implementation
# ============================================================================


class YouTubeNode(WorkflowNode):
    """
    YouTube workflow node for interacting with YouTube Data API v3.
    """

    edit_examples = [
        "Get stats for the last 10 videos and find which had highest engagement",
        "Search for trending AI content and get top 20 results with view counts",
        'Add the latest 5 uploads to the "Marketing" playlist automatically',
        "Get comments from the product demo video and flag suspicious activity",
        "Fetch channel analytics for the past 30 days and export to CSV format",
        "List all playlists and update descriptions with latest publish dates",
        "Get popular videos in Tech category and calculate average like-to-view ratio",
    ]

    scope_registry = YOUTUBE_SCOPES
    connection_evidence = ConnectionEvidence(
        operation="list_authenticated_user_playlists",
        noun="playlists",
        identity_operation="get_authenticated_user_channel",
    )

    @classmethod
    def get_config_model(cls) -> Optional[Union[Type, type]]:
        return YouTubeNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute YouTube API operation"""
        logger.info(f"[YouTubeNode] Executing node {self.node_id}")

        node_config = self.config
        if not node_config or not isinstance(node_config, YouTubeNodeConfig):
            raise ValueError("Configuration required")

        credentials = node_config.credentials
        if not credentials:
            raise ValueError(
                "YouTube credentials are required. Connect a Google account in the credentials tab."
            )

        # Ensure token is fresh
        access_token = await self._ensure_fresh_token(credentials)

        config = node_config.config
        action = getattr(config, "operation", None)

        # Route to appropriate handler
        handlers = {
            # Videos
            "list_videos_by_id": self._list_videos,
            "list_region_popular_videos": self._list_popular_videos,
            "list_authenticated_user_rated_videos": self._list_my_rated_videos,
            "get_video": self._get_video,
            "update_video_metadata": self._update_video,
            "delete_video": self._delete_video,
            "rate_video": self._rate_video,
            "get_user_video_ratings": self._get_video_rating,
            "upload_video_from_url": self._upload_video,
            "set_video_thumbnail": self._set_thumbnail,
            # Channels
            "list_channels_by_id": self._list_channels,
            "get_authenticated_user_channel": self._get_my_channel,
            "update_channel_branding": self._update_channel,
            # Playlists
            "list_authenticated_user_playlists": self._list_my_playlists,
            "list_playlists_by_id": self._list_playlists_by_id,
            "list_channel_playlists": self._list_channel_playlists,
            "get_playlist": self._get_playlist,
            "create_playlist": self._create_playlist,
            "update_playlist": self._update_playlist,
            "delete_playlist": self._delete_playlist,
            # Playlist Items
            "list_playlist_items": self._list_playlist_items,
            "add_video_to_playlist": self._add_playlist_item,
            "update_playlist_item_position": self._update_playlist_item,
            "remove_item_from_playlist": self._delete_playlist_item,
            # Search
            "search_youtube": self._search,
            # Comments
            "list_comment_replies": self._list_comment_replies,
            "list_comments_by_id": self._list_comments_by_id,
            "list_video_comments": self._list_video_comments,
            "list_channel_video_comments": self._list_channel_comments,
            "create_comment_reply": self._create_comment,
            "create_video_comment": self._create_video_comment,
            "create_channel_discussion_comment": self._create_channel_comment,
            "update_comment": self._update_comment,
            "delete_comment": self._delete_comment,
            "set_comment_moderation_status": self._set_comment_moderation,
            # Subscriptions
            "list_subscriptions": self._list_subscriptions,
            "subscribe_to_channel": self._subscribe,
            "unsubscribe_from_channel": self._unsubscribe,
            # Captions
            "list_video_captions": self._list_captions,
            "download_caption_track": self._download_caption,
            # Activities
            "list_authenticated_user_activities": self._list_my_activities,
            "list_channel_activities": self._list_channel_activities,
            # Categories & Localization
            "list_video_categories": self._list_video_categories,
            "list_supported_languages": self._list_languages,
            "list_supported_regions": self._list_regions,
            # Channel Sections
            "list_authenticated_user_channel_sections": self._list_my_channel_sections,
            "list_channel_sections": self._list_channel_sections,
            # Members
            "list_channel_members": self._list_members,
            "list_membership_levels": self._list_membership_levels,
            # Analytics API
            "get_channel_analytics": self._get_channel_analytics,
            "get_video_analytics": self._get_video_analytics,
            "get_channel_revenue_analytics": self._get_revenue_analytics,
            "get_top_performing_videos": self._get_top_videos,
            "get_viewer_demographics": self._get_demographics,
            "get_channel_traffic_sources": self._get_traffic_sources,
            # Reporting API
            "list_bulk_reporting_types": self._list_report_types,
            "create_reporting_job": self._create_reporting_job,
            "list_reporting_jobs": self._list_reporting_jobs,
            "get_reporting_job": self._get_reporting_job,
            "delete_reporting_job": self._delete_reporting_job,
            "list_reporting_job_reports": self._list_reports,
            # Live Broadcasts
            "list_live_broadcasts": self._list_broadcasts,
            "create_live_broadcast": self._create_broadcast,
            "update_live_broadcast": self._update_broadcast,
            "delete_live_broadcast": self._delete_broadcast,
            "transition_broadcast_status": self._transition_broadcast,
            "bind_broadcast_to_stream": self._bind_broadcast,
            # Live Streams
            "list_live_streams": self._list_streams,
            "create_live_stream": self._create_stream,
            "update_live_stream": self._update_stream,
            "delete_live_stream": self._delete_stream,
            # Live Chat
            "list_live_chat_messages": self._list_live_chat_messages,
            "send_live_chat_message": self._send_live_chat_message,
            "delete_live_chat_message": self._delete_live_chat_message,
            "list_live_chat_moderators": self._list_live_chat_moderators,
            "add_live_chat_moderator": self._add_live_chat_moderator,
            "remove_live_chat_moderator": self._remove_live_chat_moderator,
            "ban_live_chat_user": self._ban_live_chat_user,
            "unban_live_chat_user": self._unban_live_chat_user,
            "list_super_chat_events": self._list_super_chat_events,
        }

        handler = handlers.get(action)
        if not handler:
            raise ValueError(f"Unknown action: {action}")

        output = await handler(config, access_token)
        await self.emit(output)
        return output

    @classmethod
    async def freshen_credential(
        cls, credential_data, *, pool=None, user_id=None, credential_id=None
    ):
        """Refresh an expiring OAuth token at credential load (dropdowns,
        trigger registration). No-op for non-rotating credentials (API keys /
        offline / non-expiring tokens)."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.google_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data,
            pool=pool,
            user_id=user_id,
            credential_id=credential_id,
            refresh=refresh_access_token,
            provider="google",
        )

    async def _ensure_fresh_token(self, credentials: YouTubeOAuthCredential) -> str:
        """Return a valid YouTube access token, refreshing + persisting if expired."""
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.google_oauth import refresh_access_token
        
        cred_dict = credentials.model_dump()
        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=cred_dict,
            refresh=refresh_access_token,
            provider="google",
        )
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        if cred_dict.get("refresh_token"):
            credentials.refresh_token = cred_dict["refresh_token"]
        return token

    def _calculate_time_filter(
        self,
        time_period: Optional[str],
        published_after: Optional[str],
        published_before: Optional[str],
    ) -> tuple[Optional[str], Optional[str]]:
        """
        Calculate published_after and published_before timestamps based on time_period preset or custom values.

        Args:
            time_period: Preset time period (last_hour, last_24_hours, last_7_days, last_30_days, all_time)
            published_after: Custom ISO 8601 timestamp for start of range
            published_before: Custom ISO 8601 timestamp for end of range

        Returns:
            Tuple of (published_after, published_before) timestamps in ISO 8601 format
        """
        from datetime import datetime, timedelta, timezone

        # If time_period is set and not "all_time", calculate from preset
        if time_period and time_period != "all_time":
            now = datetime.now(timezone.utc)

            if time_period == "last_hour":
                after = now - timedelta(hours=1)
            elif time_period == "last_24_hours":
                after = now - timedelta(days=1)
            elif time_period == "last_7_days":
                after = now - timedelta(days=7)
            elif time_period == "last_30_days":
                after = now - timedelta(days=30)
            else:
                after = None

            if after:
                return (after.isoformat(), published_before)

        # Otherwise use custom values
        return (published_after, published_before)

    def _filter_comments_by_time(
        self,
        items: List[Dict],
        published_after: Optional[str],
        published_before: Optional[str],
    ) -> List[Dict]:
        """
        Filter comment threads by their published timestamp.
        YouTube API doesn't support time filtering for commentThreads, so we do it client-side.

        Args:
            items: List of comment thread items from YouTube API
            published_after: ISO 8601 timestamp - only include comments after this
            published_before: ISO 8601 timestamp - only include comments before this

        Returns:
            Filtered list of comment threads
        """
        from datetime import datetime

        if not published_after and not published_before:
            return items

        filtered = []
        for item in items:
            try:
                # Extract publishedAt from the comment thread structure
                # Structure: item['snippet']['topLevelComment']['snippet']['publishedAt']
                published_at_str = (
                    item.get("snippet", {})
                    .get("topLevelComment", {})
                    .get("snippet", {})
                    .get("publishedAt")
                )

                if not published_at_str:
                    # If we can't find publishedAt, skip this item
                    continue

                # Parse the timestamp
                published_at = datetime.fromisoformat(
                    published_at_str.replace("Z", "+00:00")
                )

                # Check if within range
                if published_after:
                    after_dt = datetime.fromisoformat(
                        published_after.replace("Z", "+00:00")
                    )
                    if published_at < after_dt:
                        continue

                if published_before:
                    before_dt = datetime.fromisoformat(
                        published_before.replace("Z", "+00:00")
                    )
                    if published_at > before_dt:
                        continue

                # Passed all filters
                filtered.append(item)

            except (ValueError, KeyError, AttributeError) as e:
                logger.warning(f"[YouTubeNode] Failed to parse comment timestamp: {e}")
                continue

        return filtered

    async def _api_request(
        self,
        method: str,
        endpoint: str,
        access_token: str,
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """Make YouTube API request"""
        url = f"{YOUTUBE_API_BASE}/{endpoint}"
        headers = {"Authorization": f"Bearer {access_token}"}

        async with httpx.AsyncClient() as client:
            if method == "GET":
                response = await client.get(url, headers=headers, params=params)
            elif method == "POST":
                response = await client.post(
                    url, headers=headers, params=params, json=json_data
                )
            elif method == "PUT":
                response = await client.put(
                    url, headers=headers, params=params, json=json_data
                )
            elif method == "DELETE":
                response = await client.delete(url, headers=headers, params=params)
            else:
                raise ValueError(f"Unsupported method: {method}")

            if response.status_code not in (200, 204):
                error_data = response.json() if response.text else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"YouTube API error: {error_msg}")

            if response.status_code == 204:
                return {"success": True}

            return response.json()

    # ========== Video Operations ==========

    async def _list_videos(
        self, config: YouTubeListVideosConfig, token: str
    ) -> Dict[str, Any]:
        params = {"part": config.part, "id": config.video_ids}
        if config.max_results:
            params["maxResults"] = config.max_results

        data = await self._api_request("GET", "videos", token, params=params)
        return {
            "action": "list_videos_by_id",
            "items": data.get("items", []),
            "pageInfo": data.get("pageInfo", {}),
        }

    async def _list_popular_videos(
        self, config: YouTubeListPopularVideosConfig, token: str
    ) -> Dict[str, Any]:
        params = {
            "part": config.part,
            "chart": "mostPopular",
            "regionCode": config.region_code,
        }
        if config.max_results:
            params["maxResults"] = config.max_results

        data = await self._api_request("GET", "videos", token, params=params)
        return {
            "action": "list_region_popular_videos",
            "items": data.get("items", []),
            "pageInfo": data.get("pageInfo", {}),
        }

    async def _list_my_rated_videos(
        self, config: YouTubeListMyRatedVideosConfig, token: str
    ) -> Dict[str, Any]:
        params = {"part": config.part, "myRating": config.my_rating}
        if config.max_results:
            params["maxResults"] = config.max_results

        data = await self._api_request("GET", "videos", token, params=params)
        return {
            "action": "list_authenticated_user_rated_videos",
            "items": data.get("items", []),
            "pageInfo": data.get("pageInfo", {}),
        }

    async def _get_video(
        self, config: YouTubeGetVideoConfig, token: str
    ) -> Dict[str, Any]:
        params = {"part": config.part, "id": config.video_id}
        data = await self._api_request("GET", "videos", token, params=params)
        items = data.get("items", [])
        return {"action": "get_video", "video": items[0] if items else None}

    async def _update_video(
        self, config: YouTubeUpdateVideoConfig, token: str
    ) -> Dict[str, Any]:
        # First get the current video data
        current = await self._get_video(
            YouTubeGetVideoConfig(video_id=config.video_id, part="snippet,status"),
            token,
        )
        if not current.get("video"):
            raise ValueError(f"Video not found: {config.video_id}")

        video = current["video"]
        snippet = video.get("snippet", {})
        status = video.get("status", {})

        # Update fields
        if config.title:
            snippet["title"] = config.title
        if config.description is not None:
            snippet["description"] = config.description
        if config.tags:
            snippet["tags"] = [t.strip() for t in config.tags.split(",")]
        if config.category_id:
            snippet["categoryId"] = config.category_id
        if config.privacy_status:
            status["privacyStatus"] = config.privacy_status

        body = {"id": config.video_id, "snippet": snippet, "status": status}

        data = await self._api_request(
            "PUT", "videos", token, params={"part": "snippet,status"}, json_data=body
        )
        return {"action": "update_video_metadata", "video": data}

    async def _delete_video(
        self, config: YouTubeDeleteVideoConfig, token: str
    ) -> Dict[str, Any]:
        await self._api_request(
            "DELETE", "videos", token, params={"id": config.video_id}
        )
        return {"action": "delete_video", "success": True, "video_id": config.video_id}

    async def _rate_video(
        self, config: YouTubeRateVideoConfig, token: str
    ) -> Dict[str, Any]:
        await self._api_request(
            "POST",
            "videos/rate",
            token,
            params={"id": config.video_id, "rating": config.rating},
        )
        return {
            "action": "rate_video",
            "success": True,
            "video_id": config.video_id,
            "rating": config.rating,
        }

    async def _get_video_rating(
        self, config: YouTubeGetVideoRatingConfig, token: str
    ) -> Dict[str, Any]:
        data = await self._api_request(
            "GET", "videos/getRating", token, params={"id": config.video_ids}
        )
        return {"action": "get_user_video_ratings", "items": data.get("items", [])}

    async def _upload_video(
        self, config: YouTubeUploadVideoConfig, token: str
    ) -> Dict[str, Any]:
        """Upload a video (uploaded file, URL, or upstream reference) using the resumable protocol."""
        from nodes.core.media_resolver import resolve_media_input

        # Step 1: Resolve the video input to bytes (uploaded file, URL, data URI)
        logger.info(f"[YouTubeNode] Resolving video input: {config.video_url[:80]}")
        resolved = await resolve_media_input(config.video_url, default_mime="video/mp4")
        video_content = resolved.data
        content_type = resolved.mime_type or "video/*"

        # Validate it's a video
        if not (content_type.startswith("video/") or content_type == "application/octet-stream"):
            if "text/html" in content_type:
                raise ValueError(
                    "The URL returned an HTML page instead of a video file. "
                    "Please provide a direct download link to a video file (e.g., .mp4, .mov). "
                    "YouTube/Vimeo watch pages and Google Drive share links won't work - you need a direct video URL."
                )
            raise ValueError(
                f"Invalid content type '{content_type}'. Expected a video file. "
                "Upload a video file, paste a direct video URL, or reference an upstream file."
            )

        # Generic octet-stream — infer from the resolved filename's extension
        if content_type == "application/octet-stream":
            name_lower = resolved.filename.lower()
            content_type = {
                ".mp4": "video/mp4",
                ".mov": "video/quicktime",
                ".avi": "video/x-msvideo",
                ".webm": "video/webm",
                ".mkv": "video/x-matroska",
            }.get("." + name_lower.rsplit(".", 1)[-1] if "." in name_lower else "", "video/*")

        # Step 2: Prepare video metadata
        snippet = {
            "title": config.title,
            "categoryId": config.category_id,
        }
        if config.description:
            snippet["description"] = config.description
        if config.tags:
            snippet["tags"] = [t.strip() for t in config.tags.split(",")]

        status = {
            "privacyStatus": config.privacy_status,
            "selfDeclaredMadeForKids": config.made_for_kids,
        }

        metadata = {"snippet": snippet, "status": status}

        # Step 3: Initiate resumable upload
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Length": str(len(video_content)),
            "X-Upload-Content-Type": content_type,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            # Get upload URL
            init_response = await client.post(
                YOUTUBE_UPLOAD_URL,
                params={"uploadType": "resumable", "part": "snippet,status"},
                headers=headers,
                json=metadata,
            )

            if init_response.status_code != 200:
                error_data = init_response.json() if init_response.text else {}
                error_msg = error_data.get("error", {}).get(
                    "message", init_response.text
                )
                raise ValueError(f"Failed to initiate upload: {error_msg}")

            # Get the resumable upload URL from Location header
            resumable_url = init_response.headers.get("Location")
            if not resumable_url:
                raise ValueError("No upload URL received from YouTube")
            # Location is provider-returned data. It must stay on the exact
            # official upload origin before the OAuth bearer is constructed for
            # the content PUT (rejects userinfo, suffix hosts, and alternate
            # schemes/ports as well as private-network targets).
            assert_exact_url_origin(resumable_url, YOUTUBE_UPLOAD_ORIGIN)

        # Step 4: Upload the video content
        async with httpx.AsyncClient(
            timeout=600.0
        ) as client:  # 10 minute timeout for large uploads
            upload_response = await client.put(
                resumable_url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": content_type,
                },
                content=video_content,
            )

            if upload_response.status_code not in (200, 201):
                error_data = upload_response.json() if upload_response.text else {}
                error_msg = error_data.get("error", {}).get(
                    "message", upload_response.text
                )
                raise ValueError(f"Video upload failed: {error_msg}")

            video_data = upload_response.json()

        return {
            "action": "upload_video_from_url",
            "success": True,
            "video": video_data,
            "video_id": video_data.get("id"),
            "title": config.title,
        }

    # ========== Channel Operations ==========

    async def _list_channels(
        self, config: YouTubeListChannelsConfig, token: str
    ) -> Dict[str, Any]:
        params = {"part": config.part, "id": config.channel_ids}
        if config.max_results:
            params["maxResults"] = config.max_results

        data = await self._api_request("GET", "channels", token, params=params)
        return {
            "action": "list_channels_by_id",
            "items": data.get("items", []),
            "pageInfo": data.get("pageInfo", {}),
        }

    async def _get_my_channel(
        self, config: YouTubeGetMyChannelConfig, token: str
    ) -> Dict[str, Any]:
        params = {"part": config.part, "mine": True}
        data = await self._api_request("GET", "channels", token, params=params)
        items = data.get("items", [])
        return {
            "action": "get_authenticated_user_channel",
            "channel": items[0] if items else None,
        }

    async def _update_channel(
        self, config: YouTubeUpdateChannelConfig, token: str
    ) -> Dict[str, Any]:
        # Get current channel data
        current_params = {"part": "brandingSettings", "id": config.channel_id}
        current = await self._api_request(
            "GET", "channels", token, params=current_params
        )
        items = current.get("items", [])
        if not items:
            raise ValueError(f"Channel not found: {config.channel_id}")

        channel = items[0]
        branding = channel.get("brandingSettings", {})
        channel_settings = branding.get("channel", {})

        if config.description is not None:
            channel_settings["description"] = config.description
        if config.keywords:
            channel_settings["keywords"] = config.keywords
        if config.default_language:
            channel_settings["defaultLanguage"] = config.default_language

        body = {
            "id": config.channel_id,
            "brandingSettings": {"channel": channel_settings},
        }

        data = await self._api_request(
            "PUT",
            "channels",
            token,
            params={"part": "brandingSettings"},
            json_data=body,
        )
        return {"action": "update_channel_branding", "channel": data}

    # ========== Playlist Operations ==========

    async def _list_my_playlists(
        self, config: YouTubeListMyPlaylistsConfig, token: str
    ) -> Dict[str, Any]:
        params = {"part": config.part, "mine": True}
        if config.max_results:
            params["maxResults"] = config.max_results
        if config.page_token:
            params["pageToken"] = config.page_token

        data = await self._api_request("GET", "playlists", token, params=params)
        result = {
            "action": "list_authenticated_user_playlists",
            "items": data.get("items", []),
            "pageInfo": data.get("pageInfo", {}),
        }
        if data.get("nextPageToken"):
            result["nextPageToken"] = data["nextPageToken"]
        return result

    async def _list_playlists_by_id(
        self, config: YouTubeListPlaylistsByIdConfig, token: str
    ) -> Dict[str, Any]:
        params = {"part": config.part, "id": config.playlist_ids}
        if config.max_results:
            params["maxResults"] = config.max_results
        if config.page_token:
            params["pageToken"] = config.page_token

        data = await self._api_request("GET", "playlists", token, params=params)
        result = {
            "action": "list_playlists_by_id",
            "items": data.get("items", []),
            "pageInfo": data.get("pageInfo", {}),
        }
        if data.get("nextPageToken"):
            result["nextPageToken"] = data["nextPageToken"]
        return result

    async def _list_channel_playlists(
        self, config: YouTubeListChannelPlaylistsConfig, token: str
    ) -> Dict[str, Any]:
        params = {"part": config.part, "channelId": config.channel_id}
        if config.max_results:
            params["maxResults"] = config.max_results
        if config.page_token:
            params["pageToken"] = config.page_token

        data = await self._api_request("GET", "playlists", token, params=params)
        result = {
            "action": "list_channel_playlists",
            "items": data.get("items", []),
            "pageInfo": data.get("pageInfo", {}),
        }
        if data.get("nextPageToken"):
            result["nextPageToken"] = data["nextPageToken"]
        return result

    async def _get_playlist(
        self, config: YouTubeGetPlaylistConfig, token: str
    ) -> Dict[str, Any]:
        params = {"part": config.part, "id": config.playlist_id}
        data = await self._api_request("GET", "playlists", token, params=params)
        items = data.get("items", [])
        return {"action": "get_playlist", "playlist": items[0] if items else None}

    async def _create_playlist(
        self, config: YouTubeCreatePlaylistConfig, token: str
    ) -> Dict[str, Any]:
        body = {
            "snippet": {
                "title": config.title,
                "description": config.description or "",
            },
            "status": {"privacyStatus": config.privacy_status},
        }
        if config.tags:
            body["snippet"]["tags"] = [t.strip() for t in config.tags.split(",")]

        data = await self._api_request(
            "POST",
            "playlists",
            token,
            params={"part": "snippet,status"},
            json_data=body,
        )
        return {"action": "create_playlist", "playlist": data}

    async def _update_playlist(
        self, config: YouTubeUpdatePlaylistConfig, token: str
    ) -> Dict[str, Any]:
        # Get current playlist
        current = await self._get_playlist(
            YouTubeGetPlaylistConfig(playlist_id=config.playlist_id), token
        )
        if not current.get("playlist"):
            raise ValueError(f"Playlist not found: {config.playlist_id}")

        playlist = current["playlist"]
        snippet = playlist.get("snippet", {})
        status = playlist.get("status", {})

        if config.title:
            snippet["title"] = config.title
        if config.description is not None:
            snippet["description"] = config.description
        if config.privacy_status:
            status["privacyStatus"] = config.privacy_status

        body = {"id": config.playlist_id, "snippet": snippet, "status": status}
        data = await self._api_request(
            "PUT", "playlists", token, params={"part": "snippet,status"}, json_data=body
        )
        return {"action": "update_playlist", "playlist": data}

    async def _delete_playlist(
        self, config: YouTubeDeletePlaylistConfig, token: str
    ) -> Dict[str, Any]:
        await self._api_request(
            "DELETE", "playlists", token, params={"id": config.playlist_id}
        )
        return {
            "action": "delete_playlist",
            "success": True,
            "playlist_id": config.playlist_id,
        }

    # ========== Playlist Items Operations ==========

    async def _list_playlist_items(
        self, config: YouTubeListPlaylistItemsConfig, token: str
    ) -> Dict[str, Any]:
        params = {"part": config.part, "playlistId": config.playlist_id}
        if config.max_results:
            params["maxResults"] = config.max_results
        if config.page_token:
            params["pageToken"] = config.page_token

        data = await self._api_request("GET", "playlistItems", token, params=params)
        return {
            "action": "list_playlist_items",
            "items": data.get("items", []),
            "pageInfo": data.get("pageInfo", {}),
            "nextPageToken": data.get("nextPageToken"),
        }

    async def _add_playlist_item(
        self, config: YouTubeAddPlaylistItemConfig, token: str
    ) -> Dict[str, Any]:
        body = {
            "snippet": {
                "playlistId": config.playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": config.video_id},
            }
        }
        if config.position is not None:
            body["snippet"]["position"] = config.position

        data = await self._api_request(
            "POST", "playlistItems", token, params={"part": "snippet"}, json_data=body
        )
        return {"action": "add_video_to_playlist", "item": data}

    async def _update_playlist_item(
        self, config: YouTubeUpdatePlaylistItemConfig, token: str
    ) -> Dict[str, Any]:
        body = {
            "id": config.playlist_item_id,
            "snippet": {
                "playlistId": config.playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": config.video_id},
                "position": config.position,
            },
        }
        data = await self._api_request(
            "PUT", "playlistItems", token, params={"part": "snippet"}, json_data=body
        )
        return {"action": "update_playlist_item_position", "item": data}

    async def _delete_playlist_item(
        self, config: YouTubeDeletePlaylistItemConfig, token: str
    ) -> Dict[str, Any]:
        await self._api_request(
            "DELETE", "playlistItems", token, params={"id": config.playlist_item_id}
        )
        return {
            "action": "remove_item_from_playlist",
            "success": True,
            "playlist_item_id": config.playlist_item_id,
        }

    # ========== Search ==========

    async def _search(self, config: YouTubeSearchConfig, token: str) -> Dict[str, Any]:
        params = {"part": config.part, "q": config.query}
        if config.search_type:
            params["type"] = config.search_type
        if config.channel_id:
            params["channelId"] = config.channel_id
        if config.order:
            params["order"] = config.order
        if config.published_after:
            params["publishedAfter"] = config.published_after
        if config.published_before:
            params["publishedBefore"] = config.published_before
        if config.region_code:
            params["regionCode"] = config.region_code
        if config.video_duration:
            params["videoDuration"] = config.video_duration
        if config.video_definition:
            params["videoDefinition"] = config.video_definition
        if config.max_results:
            params["maxResults"] = config.max_results

        data = await self._api_request("GET", "search", token, params=params)
        return {
            "action": "search_youtube",
            "items": data.get("items", []),
            "pageInfo": data.get("pageInfo", {}),
            "nextPageToken": data.get("nextPageToken"),
        }

    # ========== Comment Operations ==========

    async def _list_comment_replies(
        self, config: YouTubeListCommentRepliesConfig, token: str
    ) -> Dict[str, Any]:
        params = {"part": config.part, "parentId": config.parent_id}
        if config.max_results:
            params["maxResults"] = config.max_results

        data = await self._api_request("GET", "comments", token, params=params)
        return {
            "action": "list_comment_replies",
            "items": data.get("items", []),
            "pageInfo": data.get("pageInfo", {}),
        }

    async def _list_comments_by_id(
        self, config: YouTubeListCommentsByIdConfig, token: str
    ) -> Dict[str, Any]:
        params = {"part": config.part, "id": config.comment_ids}
        if config.max_results:
            params["maxResults"] = config.max_results

        data = await self._api_request("GET", "comments", token, params=params)
        return {
            "action": "list_comments_by_id",
            "items": data.get("items", []),
            "pageInfo": data.get("pageInfo", {}),
        }

    async def _list_video_comments(
        self, config: YouTubeListVideoCommentsConfig, token: str
    ) -> Dict[str, Any]:
        params = {"part": config.part, "videoId": config.video_id}
        if config.order:
            params["order"] = config.order
        # Note: searchTerms is not supported by commentThreads API (only by search API)
        # Client-side text filtering could be added if needed
        if config.max_results:
            params["maxResults"] = config.max_results

        data = await self._api_request("GET", "commentThreads", token, params=params)

        # Client-side time filtering (YouTube API doesn't support publishedAfter/publishedBefore for commentThreads)
        items = data.get("items", [])
        published_after, published_before = self._calculate_time_filter(
            config.time_period, config.published_after, config.published_before
        )

        if published_after or published_before:
            items = self._filter_comments_by_time(
                items, published_after, published_before
            )

        return {
            "action": "list_video_comments",
            "items": items,
            "pageInfo": data.get("pageInfo", {}),
            "nextPageToken": data.get("nextPageToken"),
            "original_count": len(data.get("items", [])),
            "filtered_count": len(items),
        }

    async def _list_channel_comments(
        self, config: YouTubeListChannelCommentsConfig, token: str
    ) -> Dict[str, Any]:
        params = {
            "part": config.part,
            "allThreadsRelatedToChannelId": config.channel_id,
        }
        if config.order:
            params["order"] = config.order
        # Note: searchTerms is not supported by commentThreads API (only by search API)
        # Client-side text filtering could be added if needed
        if config.max_results:
            params["maxResults"] = config.max_results

        data = await self._api_request("GET", "commentThreads", token, params=params)

        # Client-side time filtering (YouTube API doesn't support publishedAfter/publishedBefore for commentThreads)
        items = data.get("items", [])
        published_after, published_before = self._calculate_time_filter(
            config.time_period, config.published_after, config.published_before
        )

        if published_after or published_before:
            items = self._filter_comments_by_time(
                items, published_after, published_before
            )

        return {
            "action": "list_channel_video_comments",
            "items": items,
            "pageInfo": data.get("pageInfo", {}),
            "nextPageToken": data.get("nextPageToken"),
            "original_count": len(data.get("items", [])),
            "filtered_count": len(items),
        }

    async def _create_comment(
        self, config: YouTubeCreateCommentConfig, token: str
    ) -> Dict[str, Any]:
        body = {"snippet": {"parentId": config.parent_id, "textOriginal": config.text}}
        data = await self._api_request(
            "POST", "comments", token, params={"part": "snippet"}, json_data=body
        )
        return {"action": "create_comment_reply", "comment": data}

    async def _create_video_comment(
        self, config: YouTubeCreateVideoCommentConfig, token: str
    ) -> Dict[str, Any]:
        body = {
            "snippet": {
                "videoId": config.video_id,
                "topLevelComment": {"snippet": {"textOriginal": config.text}},
            }
        }
        data = await self._api_request(
            "POST", "commentThreads", token, params={"part": "snippet"}, json_data=body
        )
        return {"action": "create_video_comment", "commentThread": data}

    async def _create_channel_comment(
        self, config: YouTubeCreateChannelCommentConfig, token: str
    ) -> Dict[str, Any]:
        body = {
            "snippet": {
                "channelId": config.channel_id,
                "topLevelComment": {"snippet": {"textOriginal": config.text}},
            }
        }
        data = await self._api_request(
            "POST", "commentThreads", token, params={"part": "snippet"}, json_data=body
        )
        return {"action": "create_channel_discussion_comment", "commentThread": data}

    async def _update_comment(
        self, config: YouTubeUpdateCommentConfig, token: str
    ) -> Dict[str, Any]:
        body = {"id": config.comment_id, "snippet": {"textOriginal": config.text}}
        data = await self._api_request(
            "PUT", "comments", token, params={"part": "snippet"}, json_data=body
        )
        return {"action": "update_comment", "comment": data}

    async def _delete_comment(
        self, config: YouTubeDeleteCommentConfig, token: str
    ) -> Dict[str, Any]:
        await self._api_request(
            "DELETE", "comments", token, params={"id": config.comment_id}
        )
        return {
            "action": "delete_comment",
            "success": True,
            "comment_id": config.comment_id,
        }

    async def _set_comment_moderation(
        self, config: YouTubeSetCommentModerationConfig, token: str
    ) -> Dict[str, Any]:
        params = {
            "id": config.comment_ids,
            "moderationStatus": config.moderation_status,
        }
        if config.ban_author:
            params["banAuthor"] = True

        await self._api_request(
            "POST", "comments/setModerationStatus", token, params=params
        )
        return {"action": "set_comment_moderation_status", "success": True}

    # ========== Subscription Operations ==========

    async def _list_subscriptions(
        self, config: YouTubeListSubscriptionsConfig, token: str
    ) -> Dict[str, Any]:
        params = {"part": config.part}
        if config.mine:
            params["mine"] = True
        if config.channel_id:
            params["channelId"] = config.channel_id
        if config.for_channel_id:
            params["forChannelId"] = config.for_channel_id
        if config.order:
            params["order"] = config.order
        if config.max_results:
            params["maxResults"] = config.max_results

        data = await self._api_request("GET", "subscriptions", token, params=params)
        return {
            "action": "list_subscriptions",
            "items": data.get("items", []),
            "pageInfo": data.get("pageInfo", {}),
            "nextPageToken": data.get("nextPageToken"),
        }

    async def _subscribe(
        self, config: YouTubeSubscribeConfig, token: str
    ) -> Dict[str, Any]:
        body = {
            "snippet": {
                "resourceId": {
                    "kind": "youtube#channel",
                    "channelId": config.channel_id,
                }
            }
        }
        data = await self._api_request(
            "POST", "subscriptions", token, params={"part": "snippet"}, json_data=body
        )
        return {"action": "subscribe_to_channel", "subscription": data}

    async def _unsubscribe(
        self, config: YouTubeUnsubscribeConfig, token: str
    ) -> Dict[str, Any]:
        await self._api_request(
            "DELETE", "subscriptions", token, params={"id": config.subscription_id}
        )
        return {
            "action": "unsubscribe_from_channel",
            "success": True,
            "subscription_id": config.subscription_id,
        }

    # ========== Caption Operations ==========

    async def _list_captions(
        self, config: YouTubeListCaptionsConfig, token: str
    ) -> Dict[str, Any]:
        params = {"part": config.part, "videoId": config.video_id}
        data = await self._api_request("GET", "captions", token, params=params)
        return {"action": "list_video_captions", "items": data.get("items", [])}

    async def _download_caption(
        self, config: YouTubeDownloadCaptionConfig, token: str
    ) -> Dict[str, Any]:
        params = {}
        if config.tfmt:
            params["tfmt"] = config.tfmt

        url = f"{YOUTUBE_API_BASE}/captions/{config.caption_id}"
        headers = {"Authorization": f"Bearer {token}"}

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params=params)
            if response.status_code != 200:
                error_data = response.json() if response.text else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"YouTube API error: {error_msg}")

            return {
                "action": "download_caption_track",
                "content": response.text,
                "caption_id": config.caption_id,
            }

    # ========== Activity Operations ==========

    async def _list_my_activities(
        self, config: YouTubeListMyActivitiesConfig, token: str
    ) -> Dict[str, Any]:
        params = {"part": config.part, "mine": True}
        if config.published_after:
            params["publishedAfter"] = config.published_after
        if config.published_before:
            params["publishedBefore"] = config.published_before
        if config.max_results:
            params["maxResults"] = config.max_results

        data = await self._api_request("GET", "activities", token, params=params)
        return {
            "action": "list_authenticated_user_activities",
            "items": data.get("items", []),
            "pageInfo": data.get("pageInfo", {}),
        }

    async def _list_channel_activities(
        self, config: YouTubeListChannelActivitiesConfig, token: str
    ) -> Dict[str, Any]:
        params = {"part": config.part, "channelId": config.channel_id}
        if config.published_after:
            params["publishedAfter"] = config.published_after
        if config.published_before:
            params["publishedBefore"] = config.published_before
        if config.max_results:
            params["maxResults"] = config.max_results

        data = await self._api_request("GET", "activities", token, params=params)
        return {
            "action": "list_channel_activities",
            "items": data.get("items", []),
            "pageInfo": data.get("pageInfo", {}),
        }

    # ========== Category & Localization Operations ==========

    async def _list_video_categories(
        self, config: YouTubeListVideoCategoriesConfig, token: str
    ) -> Dict[str, Any]:
        params = {"part": config.part}
        if config.region_code:
            params["regionCode"] = config.region_code
        if config.hl:
            params["hl"] = config.hl

        data = await self._api_request("GET", "videoCategories", token, params=params)
        return {"action": "list_video_categories", "items": data.get("items", [])}

    async def _list_languages(
        self, config: YouTubeListLanguagesConfig, token: str
    ) -> Dict[str, Any]:
        params = {"part": config.part}
        if config.hl:
            params["hl"] = config.hl

        data = await self._api_request("GET", "i18nLanguages", token, params=params)
        return {"action": "list_supported_languages", "items": data.get("items", [])}

    async def _list_regions(
        self, config: YouTubeListRegionsConfig, token: str
    ) -> Dict[str, Any]:
        params = {"part": config.part}
        if config.hl:
            params["hl"] = config.hl

        data = await self._api_request("GET", "i18nRegions", token, params=params)
        return {"action": "list_supported_regions", "items": data.get("items", [])}

    # ========== Channel Section Operations ==========

    async def _list_my_channel_sections(
        self, config: YouTubeListMyChannelSectionsConfig, token: str
    ) -> Dict[str, Any]:
        params = {"part": config.part, "mine": True}

        data = await self._api_request("GET", "channelSections", token, params=params)
        return {
            "action": "list_authenticated_user_channel_sections",
            "items": data.get("items", []),
        }

    async def _list_channel_sections(
        self, config: YouTubeListChannelSectionsConfig, token: str
    ) -> Dict[str, Any]:
        params = {"part": config.part, "channelId": config.channel_id}

        data = await self._api_request("GET", "channelSections", token, params=params)
        return {"action": "list_channel_sections", "items": data.get("items", [])}

    # ========== Member Operations ==========

    async def _list_members(
        self, config: YouTubeListMembersConfig, token: str
    ) -> Dict[str, Any]:
        params = {"part": "snippet", "mode": config.mode}
        if config.max_results:
            params["maxResults"] = config.max_results

        data = await self._api_request("GET", "members", token, params=params)
        return {
            "action": "list_channel_members",
            "items": data.get("items", []),
            "pageInfo": data.get("pageInfo", {}),
        }

    async def _list_membership_levels(
        self, config: YouTubeListMembershipLevelsConfig, token: str
    ) -> Dict[str, Any]:
        data = await self._api_request(
            "GET", "membershipsLevels", token, params={"part": "snippet"}
        )
        return {"action": "list_membership_levels", "items": data.get("items", [])}

    # ========== Thumbnail Operations ==========

    async def _set_thumbnail(
        self, config: YouTubeSetThumbnailConfig, token: str
    ) -> Dict[str, Any]:
        """Set a custom thumbnail for a video"""
        from nodes.core.media_resolver import resolve_media_input

        # Resolve the thumbnail input to bytes (uploaded file, URL, data URI, upstream ref)
        resolved = await resolve_media_input(config.thumbnail_url, default_mime="image/jpeg")
        img_content = resolved.data
        content_type = resolved.mime_type or "image/jpeg"

        # Validate image type
        if not content_type.startswith("image/"):
            raise ValueError(
                f"Invalid content type: {content_type}. Expected an image file."
            )

        # Upload thumbnail
        upload_url = f"{YOUTUBE_API_BASE}/thumbnails/set"
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                upload_url,
                params={"videoId": config.video_id},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": content_type,
                },
                content=img_content,
            )

            if response.status_code not in (200, 201):
                error_data = response.json() if response.text else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Failed to set thumbnail: {error_msg}")

            data = response.json()

        return {
            "action": "set_video_thumbnail",
            "thumbnails": data.get("items", []),
            "video_id": config.video_id,
        }

    # ========== Analytics API Operations ==========

    async def _analytics_request(
        self, token: str, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Make a request to the YouTube Analytics API"""
        url = f"{YOUTUBE_ANALYTICS_API_BASE}/reports"
        headers = {"Authorization": f"Bearer {token}"}

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(url, headers=headers, params=params)

            if response.status_code != 200:
                error_data = response.json() if response.text else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"YouTube Analytics API error: {error_msg}")

            return response.json()

    async def _get_channel_analytics(
        self, config: YouTubeGetChannelAnalyticsConfig, token: str
    ) -> Dict[str, Any]:
        params = {
            "ids": "channel==MINE",
            "startDate": config.start_date,
            "endDate": config.end_date,
            "metrics": config.metrics,
        }
        if config.dimensions:
            params["dimensions"] = config.dimensions
        if config.filters:
            params["filters"] = config.filters
        if config.sort:
            params["sort"] = config.sort
        if config.max_results:
            params["maxResults"] = config.max_results

        data = await self._analytics_request(token, params)
        return {
            "action": "get_channel_analytics",
            "columnHeaders": data.get("columnHeaders", []),
            "rows": data.get("rows", []),
        }

    async def _get_video_analytics(
        self, config: YouTubeGetVideoAnalyticsConfig, token: str
    ) -> Dict[str, Any]:
        params = {
            "ids": "channel==MINE",
            "startDate": config.start_date,
            "endDate": config.end_date,
            "metrics": config.metrics,
            "filters": f"video=={config.video_id}",
        }
        if config.dimensions:
            params["dimensions"] = config.dimensions

        data = await self._analytics_request(token, params)
        return {
            "action": "get_video_analytics",
            "video_id": config.video_id,
            "columnHeaders": data.get("columnHeaders", []),
            "rows": data.get("rows", []),
        }

    async def _get_revenue_analytics(
        self, config: YouTubeGetRevenueAnalyticsConfig, token: str
    ) -> Dict[str, Any]:
        params = {
            "ids": "channel==MINE",
            "startDate": config.start_date,
            "endDate": config.end_date,
            "metrics": config.metrics,
        }
        if config.dimensions:
            params["dimensions"] = config.dimensions

        data = await self._analytics_request(token, params)
        return {
            "action": "get_channel_revenue_analytics",
            "columnHeaders": data.get("columnHeaders", []),
            "rows": data.get("rows", []),
        }

    async def _get_top_videos(
        self, config: YouTubeGetTopVideosConfig, token: str
    ) -> Dict[str, Any]:
        params = {
            "ids": "channel==MINE",
            "startDate": config.start_date,
            "endDate": config.end_date,
            "dimensions": "video",
            "metrics": f"views,{config.metric},subscribersGained",
            "maxResults": config.max_results,
            "sort": f"-{config.metric}",
        }

        data = await self._analytics_request(token, params)
        return {
            "action": "get_top_performing_videos",
            "columnHeaders": data.get("columnHeaders", []),
            "rows": data.get("rows", []),
        }

    async def _get_demographics(
        self, config: YouTubeGetDemographicsConfig, token: str
    ) -> Dict[str, Any]:
        params = {
            "ids": "channel==MINE",
            "startDate": config.start_date,
            "endDate": config.end_date,
            "dimensions": "ageGroup,gender",
            "metrics": "viewerPercentage",
        }

        data = await self._analytics_request(token, params)
        return {
            "action": "get_viewer_demographics",
            "columnHeaders": data.get("columnHeaders", []),
            "rows": data.get("rows", []),
        }

    async def _get_traffic_sources(
        self, config: YouTubeGetTrafficSourcesConfig, token: str
    ) -> Dict[str, Any]:
        params = {
            "ids": "channel==MINE",
            "startDate": config.start_date,
            "endDate": config.end_date,
            "dimensions": "insightTrafficSourceType",
            "metrics": "views,estimatedMinutesWatched",
            "sort": "-views",
        }

        data = await self._analytics_request(token, params)
        return {
            "action": "get_channel_traffic_sources",
            "columnHeaders": data.get("columnHeaders", []),
            "rows": data.get("rows", []),
        }

    # ========== Reporting API Operations ==========

    async def _reporting_request(
        self,
        method: str,
        endpoint: str,
        token: str,
        params: Dict[str, Any] = None,
        json_data: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """Make a request to the YouTube Reporting API"""
        url = f"{YOUTUBE_REPORTING_API_BASE}/{endpoint}"
        headers = {"Authorization": f"Bearer {token}"}

        async with httpx.AsyncClient(timeout=60.0) as client:
            if method == "GET":
                response = await client.get(url, headers=headers, params=params)
            elif method == "POST":
                response = await client.post(
                    url, headers=headers, params=params, json=json_data
                )
            elif method == "DELETE":
                response = await client.delete(url, headers=headers, params=params)
            else:
                raise ValueError(f"Unsupported method: {method}")

            if response.status_code not in (200, 204):
                error_data = response.json() if response.text else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"YouTube Reporting API error: {error_msg}")

            if response.status_code == 204:
                return {}
            return response.json()

    async def _list_report_types(
        self, config: YouTubeListReportTypesConfig, token: str
    ) -> Dict[str, Any]:
        data = await self._reporting_request("GET", "reportTypes", token)
        return {
            "action": "list_bulk_reporting_types",
            "reportTypes": data.get("reportTypes", []),
        }

    async def _create_reporting_job(
        self, config: YouTubeCreateReportingJobConfig, token: str
    ) -> Dict[str, Any]:
        json_data = {
            "reportTypeId": config.report_type_id,
            "name": config.name,
        }
        data = await self._reporting_request("POST", "jobs", token, json_data=json_data)
        return {"action": "create_reporting_job", "job": data}

    async def _list_reporting_jobs(
        self, config: YouTubeListReportingJobsConfig, token: str
    ) -> Dict[str, Any]:
        data = await self._reporting_request("GET", "jobs", token)
        return {"action": "list_reporting_jobs", "jobs": data.get("jobs", [])}

    async def _get_reporting_job(
        self, config: YouTubeGetReportingJobConfig, token: str
    ) -> Dict[str, Any]:
        data = await self._reporting_request("GET", f"jobs/{config.job_id}", token)
        return {"action": "get_reporting_job", "job": data}

    async def _delete_reporting_job(
        self, config: YouTubeDeleteReportingJobConfig, token: str
    ) -> Dict[str, Any]:
        await self._reporting_request("DELETE", f"jobs/{config.job_id}", token)
        return {
            "action": "delete_reporting_job",
            "success": True,
            "job_id": config.job_id,
        }

    async def _list_reports(
        self, config: YouTubeListReportsConfig, token: str
    ) -> Dict[str, Any]:
        data = await self._reporting_request(
            "GET", f"jobs/{config.job_id}/reports", token
        )
        return {
            "action": "list_reporting_job_reports",
            "reports": data.get("reports", []),
            "job_id": config.job_id,
        }

    # ========== Live Broadcast Operations ==========

    async def _list_broadcasts(
        self, config: YouTubeListBroadcastsConfig, token: str
    ) -> Dict[str, Any]:
        params = {"part": config.part}
        if config.mine:
            params["mine"] = True
        if config.broadcast_status:
            params["broadcastStatus"] = config.broadcast_status
        if config.max_results:
            params["maxResults"] = config.max_results

        data = await self._api_request("GET", "liveBroadcasts", token, params=params)
        return {
            "action": "list_live_broadcasts",
            "items": data.get("items", []),
            "pageInfo": data.get("pageInfo", {}),
        }

    async def _create_broadcast(
        self, config: YouTubeCreateBroadcastConfig, token: str
    ) -> Dict[str, Any]:
        body = {
            "snippet": {
                "title": config.title,
                "scheduledStartTime": config.scheduled_start_time,
            },
            "status": {
                "privacyStatus": config.privacy_status,
                "selfDeclaredMadeForKids": config.made_for_kids,
            },
            "contentDetails": {
                "enableAutoStart": config.enable_auto_start,
                "enableAutoStop": config.enable_auto_stop,
                "enableDvr": config.enable_dvr,
                "enableContentEncryption": True,
                "enableEmbed": True,
                "recordFromStart": True,
                "startWithSlate": False,
            },
        }
        if config.description:
            body["snippet"]["description"] = config.description
        if config.enable_live_chat:
            body["contentDetails"]["enableLowLatency"] = True

        data = await self._api_request(
            "POST",
            "liveBroadcasts",
            token,
            params={"part": "snippet,status,contentDetails"},
            json_data=body,
        )
        return {"action": "create_live_broadcast", "broadcast": data}

    async def _update_broadcast(
        self, config: YouTubeUpdateBroadcastConfig, token: str
    ) -> Dict[str, Any]:
        # First get the current broadcast
        current = await self._api_request(
            "GET",
            "liveBroadcasts",
            token,
            params={"part": "snippet,status", "id": config.broadcast_id},
        )
        items = current.get("items", [])
        if not items:
            raise ValueError(f"Broadcast not found: {config.broadcast_id}")

        broadcast = items[0]
        snippet = broadcast.get("snippet", {})
        status = broadcast.get("status", {})

        if config.title:
            snippet["title"] = config.title
        if config.description is not None:
            snippet["description"] = config.description
        if config.privacy_status:
            status["privacyStatus"] = config.privacy_status

        body = {"id": config.broadcast_id, "snippet": snippet, "status": status}
        data = await self._api_request(
            "PUT",
            "liveBroadcasts",
            token,
            params={"part": "snippet,status"},
            json_data=body,
        )
        return {"action": "update_live_broadcast", "broadcast": data}

    async def _delete_broadcast(
        self, config: YouTubeDeleteBroadcastConfig, token: str
    ) -> Dict[str, Any]:
        await self._api_request(
            "DELETE", "liveBroadcasts", token, params={"id": config.broadcast_id}
        )
        return {
            "action": "delete_live_broadcast",
            "success": True,
            "broadcast_id": config.broadcast_id,
        }

    async def _transition_broadcast(
        self, config: YouTubeTransitionBroadcastConfig, token: str
    ) -> Dict[str, Any]:
        data = await self._api_request(
            "POST",
            "liveBroadcasts/transition",
            token,
            params={
                "broadcastStatus": config.broadcast_status,
                "id": config.broadcast_id,
                "part": "status",
            },
        )
        return {"action": "transition_broadcast_status", "broadcast": data}

    async def _bind_broadcast(
        self, config: YouTubeBindBroadcastConfig, token: str
    ) -> Dict[str, Any]:
        params = {"id": config.broadcast_id, "part": "id,contentDetails"}
        if config.stream_id:
            params["streamId"] = config.stream_id

        data = await self._api_request(
            "POST", "liveBroadcasts/bind", token, params=params
        )
        return {"action": "bind_broadcast_to_stream", "broadcast": data}

    # ========== Live Stream Operations ==========

    async def _list_streams(
        self, config: YouTubeListStreamsConfig, token: str
    ) -> Dict[str, Any]:
        params = {"part": config.part}
        if config.mine:
            params["mine"] = True
        if config.max_results:
            params["maxResults"] = config.max_results

        data = await self._api_request("GET", "liveStreams", token, params=params)
        return {
            "action": "list_live_streams",
            "items": data.get("items", []),
            "pageInfo": data.get("pageInfo", {}),
        }

    async def _create_stream(
        self, config: YouTubeCreateStreamConfig, token: str
    ) -> Dict[str, Any]:
        body = {
            "snippet": {
                "title": config.title,
            },
            "cdn": {
                "frameRate": config.frame_rate,
                "resolution": config.resolution,
                "ingestionType": config.ingestion_type,
            },
        }
        if config.description:
            body["snippet"]["description"] = config.description

        data = await self._api_request(
            "POST",
            "liveStreams",
            token,
            params={"part": "snippet,cdn,contentDetails,status"},
            json_data=body,
        )
        return {"action": "create_live_stream", "stream": data}

    async def _update_stream(
        self, config: YouTubeUpdateStreamConfig, token: str
    ) -> Dict[str, Any]:
        # Get current stream
        current = await self._api_request(
            "GET",
            "liveStreams",
            token,
            params={"part": "snippet,cdn", "id": config.stream_id},
        )
        items = current.get("items", [])
        if not items:
            raise ValueError(f"Stream not found: {config.stream_id}")

        stream = items[0]
        snippet = stream.get("snippet", {})
        cdn = stream.get("cdn", {})

        if config.title:
            snippet["title"] = config.title
        if config.description is not None:
            snippet["description"] = config.description

        body = {"id": config.stream_id, "snippet": snippet, "cdn": cdn}
        data = await self._api_request(
            "PUT", "liveStreams", token, params={"part": "snippet,cdn"}, json_data=body
        )
        return {"action": "update_live_stream", "stream": data}

    async def _delete_stream(
        self, config: YouTubeDeleteStreamConfig, token: str
    ) -> Dict[str, Any]:
        await self._api_request(
            "DELETE", "liveStreams", token, params={"id": config.stream_id}
        )
        return {
            "action": "delete_live_stream",
            "success": True,
            "stream_id": config.stream_id,
        }

    # ========== Live Chat Operations ==========

    async def _list_live_chat_messages(
        self, config: YouTubeListLiveChatMessagesConfig, token: str
    ) -> Dict[str, Any]:
        params = {"part": config.part, "liveChatId": config.live_chat_id}
        if config.max_results:
            params["maxResults"] = config.max_results
        if config.page_token:
            params["pageToken"] = config.page_token

        data = await self._api_request("GET", "liveChat/messages", token, params=params)
        result = {
            "action": "list_live_chat_messages",
            "items": data.get("items", []),
            "pageInfo": data.get("pageInfo", {}),
            "pollingIntervalMillis": data.get("pollingIntervalMillis"),
        }
        if data.get("nextPageToken"):
            result["nextPageToken"] = data["nextPageToken"]
        return result

    async def _send_live_chat_message(
        self, config: YouTubeSendLiveChatMessageConfig, token: str
    ) -> Dict[str, Any]:
        body = {
            "snippet": {
                "liveChatId": config.live_chat_id,
                "type": "textMessageEvent",
                "textMessageDetails": {
                    "messageText": config.message,
                },
            },
        }

        data = await self._api_request(
            "POST",
            "liveChat/messages",
            token,
            params={"part": "snippet"},
            json_data=body,
        )
        return {"action": "send_live_chat_message", "message": data}

    async def _delete_live_chat_message(
        self, config: YouTubeDeleteLiveChatMessageConfig, token: str
    ) -> Dict[str, Any]:
        await self._api_request(
            "DELETE", "liveChat/messages", token, params={"id": config.message_id}
        )
        return {
            "action": "delete_live_chat_message",
            "success": True,
            "message_id": config.message_id,
        }

    async def _list_live_chat_moderators(
        self, config: YouTubeListLiveChatModeratorsConfig, token: str
    ) -> Dict[str, Any]:
        params = {"part": "snippet", "liveChatId": config.live_chat_id}
        if config.max_results:
            params["maxResults"] = config.max_results

        data = await self._api_request(
            "GET", "liveChat/moderators", token, params=params
        )
        return {
            "action": "list_live_chat_moderators",
            "items": data.get("items", []),
            "pageInfo": data.get("pageInfo", {}),
        }

    async def _add_live_chat_moderator(
        self, config: YouTubeAddLiveChatModeratorConfig, token: str
    ) -> Dict[str, Any]:
        body = {
            "snippet": {
                "liveChatId": config.live_chat_id,
                "moderatorDetails": {
                    "channelId": config.channel_id,
                },
            },
        }

        data = await self._api_request(
            "POST",
            "liveChat/moderators",
            token,
            params={"part": "snippet"},
            json_data=body,
        )
        return {"action": "add_live_chat_moderator", "moderator": data}

    async def _remove_live_chat_moderator(
        self, config: YouTubeRemoveLiveChatModeratorConfig, token: str
    ) -> Dict[str, Any]:
        await self._api_request(
            "DELETE", "liveChat/moderators", token, params={"id": config.moderator_id}
        )
        return {
            "action": "remove_live_chat_moderator",
            "success": True,
            "moderator_id": config.moderator_id,
        }

    async def _ban_live_chat_user(
        self, config: YouTubeBanLiveChatUserConfig, token: str
    ) -> Dict[str, Any]:
        body = {
            "snippet": {
                "liveChatId": config.live_chat_id,
                "type": config.ban_type,
                "bannedUserDetails": {
                    "channelId": config.channel_id,
                },
            },
        }
        if config.ban_type == "temporary" and config.ban_duration_seconds:
            body["snippet"]["banDurationSeconds"] = config.ban_duration_seconds

        data = await self._api_request(
            "POST", "liveChat/bans", token, params={"part": "snippet"}, json_data=body
        )
        return {"action": "ban_live_chat_user", "ban": data}

    async def _unban_live_chat_user(
        self, config: YouTubeUnbanLiveChatUserConfig, token: str
    ) -> Dict[str, Any]:
        await self._api_request(
            "DELETE", "liveChat/bans", token, params={"id": config.ban_id}
        )
        return {
            "action": "unban_live_chat_user",
            "success": True,
            "ban_id": config.ban_id,
        }

    async def _list_super_chat_events(
        self, config: YouTubeListSuperChatEventsConfig, token: str
    ) -> Dict[str, Any]:
        params = {"part": "snippet"}
        if config.max_results:
            params["maxResults"] = config.max_results

        data = await self._api_request("GET", "superChatEvents", token, params=params)
        return {
            "action": "list_super_chat_events",
            "items": data.get("items", []),
            "pageInfo": data.get("pageInfo", {}),
        }
