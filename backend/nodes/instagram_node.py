"""
Instagram Graph API automation node.

Provides workflow integration with Instagram for Business/Creator accounts:
- Profile Operations: get user profile, account info
- Media Operations: list media, get media details, publish photos/videos/reels/carousels
- Comment Operations: list, create, reply to, hide, delete comments
- Insights Operations: get media insights, account insights
- Hashtag Operations: search hashtags, get top/recent media
- Stories Operations: publish photo/video stories
- Mentions Operations: get media/comments where account is @mentioned
- Product Tagging: tag products, get/delete product tags (Instagram Shopping)
- Business Discovery: discover public business/creator accounts

Authentication: Facebook OAuth 2.0 (Instagram Graph API requires Facebook Login)
API Base URL: https://graph.instagram.com (or https://graph.facebook.com for some endpoints)
Documentation: https://developers.facebook.com/docs/instagram-platform/instagram-graph-api
Rate Limit: 200 requests per hour per Instagram User account

Note: Only Business and Creator accounts are supported (Personal accounts deprecated Dec 2024)
Total Operations: 23
"""

import asyncio
import json
import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, Discriminator, ConfigDict
import httpx

from nodes.core.apify_runner import ApifyRunnerMixin
from nodes.core.platform_billing import platform_keyed_operation

# Scraping runs on Apify with NoClick's token; the node's own credential funds none of it.
PLATFORM_KEYED = platform_keyed_operation("APIFY_API_TOKEN", byok=False)
from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.oauth.facebook_oauth import is_token_expired, refresh_access_token
from nodes.oauth.instagram_login_oauth import (
    is_token_expired as _ig_login_is_expired,
    refresh_access_token as _ig_login_refresh,
)
from nodes.scopes.meta import INSTAGRAM_SCOPES

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

GRAPH_API_VERSION = "v21.0"
INSTAGRAM_API_BASE = f"https://graph.instagram.com/{GRAPH_API_VERSION}"
FACEBOOK_GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

# Per-credential asyncio locks to prevent concurrent token refresh races.

# Apify Instagram actor IDs (~ separator required in URL paths)
APIFY_PROFILE_SCRAPER = "apify~instagram-profile-scraper"
APIFY_POST_SCRAPER = "apify~instagram-post-scraper"
APIFY_SCRAPER = "apify~instagram-scraper"
APIFY_REEL_SCRAPER = "apify~instagram-reel-scraper"
APIFY_COMMENT_SCRAPER = "apify~instagram-comment-scraper"

# ============================================================================
# Credential Schema
# ============================================================================


class InstagramOAuthCredential(BaseModel):
    """
    OAuth 2.0 credential for Instagram via Facebook Login.
    Tokens are obtained via Facebook OAuth flow, not entered manually.

    Register OAuth app at: https://developers.facebook.com/apps/
    """

    credential_type: Literal["instagram_oauth"] = Field(
        "instagram_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ...,
        title="Access Token",
        description="Long-lived OAuth 2.0 access token from Facebook",
    )
    instagram_user_id: str = Field(
        ...,
        title="Instagram User ID",
        description="The Instagram Business/Creator account ID",
    )
    expires_at: str = Field(
        ...,
        title="Token Expiry",
        description="ISO 8601 timestamp when access token expires",
    )
    email: Optional[str] = Field(
        None,
        title="Account Email",
        description="Email address of the connected Facebook account",
    )
    instagram_username: Optional[str] = Field(
        None,
        title="Instagram Username",
        description="Username of the connected Instagram account",
    )

    model_config = ConfigDict(json_schema_extra={
        "x-credential-type": "oauth",
        "x-oauth-provider": "facebook",
        # Hidden until Meta approves our OAuth app — existing OAuth credentials
        # still parse/execute; new connections use the token credentials below.
        # PostHog flag reveals it for allow-listed accounts (e.g. Meta reviewers).
        "x-credential-hidden": True,
        "x-credential-preview-flag": "meta-oauth-preview",
        "x-oauth-scopes": [
            "instagram_basic",
            "instagram_content_publish",
            "instagram_manage_comments",
            "instagram_manage_messages",
            "pages_show_list",
            "pages_read_engagement",
            # business_management deliberately NOT requested: no IG operation
            # requires it (scope-registry verified) and it is excluded from App
            # Review — requesting an unapproved permission fails the login dialog.
        ],
    })


class InstagramLoginCredential(BaseModel):
    """
    Instagram Login credential (Instagram API *with Instagram Login*).

    The Meta-recommended flow where the user logs in with their Instagram
    account directly — NO Facebook Page required. Served from
    graph.instagram.com with the instagram_business_* scope family. Distinct
    from InstagramOAuthCredential, which is Instagram *with Facebook Login*
    (graph.facebook.com, needs a linked Page).
    """

    credential_type: Literal["instagram_login"] = Field(
        "instagram_login", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ...,
        title="Access Token",
        description="Long-lived Instagram user access token (60-day, refreshable)",
    )
    instagram_user_id: str = Field(
        ...,
        title="Instagram User ID",
        description="The Instagram professional account ID (graph.instagram.com)",
    )
    expires_at: str = Field(
        ...,
        title="Token Expiry",
        description="ISO 8601 timestamp when the access token expires",
    )
    instagram_username: Optional[str] = Field(
        None,
        title="Instagram Username",
        description="Username of the connected Instagram account",
    )

    model_config = ConfigDict(json_schema_extra={
        "x-credential-type": "oauth",
        # Provider key must match the frontend OAUTH_PROVIDER_CONFIG entry + hook
        # registration (instagram_login); the route path stays /api/auth/instagram
        # via the hook's authorizePath override. A mismatch surfaces as
        # "Unknown OAuth provider" when the user clicks Connect.
        "x-oauth-provider": "instagram_login",
        "x-oauth-scopes": [
            "instagram_business_basic",
            "instagram_business_content_publish",
            "instagram_business_manage_comments",
            "instagram_business_manage_messages",
        ],
    })


class InstagramSystemUserTokenCredential(BaseModel):
    """
    System User Token credential for server-side automation.
    Non-expiring token suitable for long-running background tasks.

    Create at: https://business.facebook.com/settings/system-users
    """

    credential_type: Literal["instagram_system_user_token"] = Field(
        "instagram_system_user_token", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ...,
        title="System User Access Token",
        description="Non-expiring access token from Facebook Business Manager System User",
    )
    instagram_user_id: str = Field(
        ...,
        title="Instagram User ID",
        description="The Instagram Business/Creator account ID",
    )
    instagram_username: Optional[str] = Field(
        None,
        title="Instagram Username",
        description="Username of the connected Instagram account",
    )

    model_config = ConfigDict(json_schema_extra={
        "x-credential-url": "https://business.facebook.com/settings/system-users",
    })


class InstagramPageAccessTokenCredential(BaseModel):
    """
    Page Access Token credential (can be made permanent).
    Suitable for Facebook Page-based Instagram integrations.

    Generate at: Graph API Explorer or via Facebook Login
    """

    credential_type: Literal["instagram_page_access_token"] = Field(
        "instagram_page_access_token", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ...,
        title="Page Access Token",
        description="Long-lived or permanent Page Access Token",
    )
    instagram_user_id: str = Field(
        ...,
        title="Instagram User ID",
        description="The Instagram Business account ID connected to the Facebook Page",
    )
    page_id: Optional[str] = Field(
        None,
        title="Facebook Page ID",
        description="The Facebook Page ID that owns this Instagram account",
    )
    instagram_username: Optional[str] = Field(
        None,
        title="Instagram Username",
        description="Username of the connected Instagram account",
    )
    expires_at: Optional[str] = Field(
        None,
        title="Token Expiry",
        description="ISO 8601 timestamp when token expires (None if permanent)",
    )

    model_config = ConfigDict(json_schema_extra={
        "x-credential-url": "https://developers.facebook.com/tools/explorer/",
    })


# Support all three credential types
InstagramCredential = Union[
    InstagramOAuthCredential,
    InstagramLoginCredential,
    InstagramSystemUserTokenCredential,
    InstagramPageAccessTokenCredential,
]

# Operations that only exist on Instagram API *with Facebook Login*
# (graph.facebook.com). Instagram Login (graph.instagram.com) does not expose
# hashtag search, product tagging, or business discovery, so these are refused
# with a clear message when an instagram_login credential is used.
_FACEBOOK_LOGIN_ONLY_OPS = {
    "search_hashtag_id",
    "get_hashtag_media",
    "discover_business_account",
    "tag_products_in_media",
    "get_media_product_tags",
    "delete_product_tags_from_media",
}


# ============================================================================
# Profile Operations
# ============================================================================


class InstagramGetProfileConfig(BaseModel):
    """Get the authenticated user's Instagram profile"""

    operation: Literal["get_user_profile"] = Field(
        "get_user_profile",
        json_schema_extra={
            "const": "get_user_profile",
            "ui:hidden": True,
            "x-category": "Profile",
            "x-is-trigger": False,
            "x-display-name": "Get User Profile",
        },
        title="Get User Profile",
    )
    fields: Optional[str] = Field(
        "id,username,name,biography,followers_count,follows_count,media_count,profile_picture_url,website",
        title="Fields",
        description="Comma-separated list of fields to retrieve",
    )


# ============================================================================
# Media Operations
# ============================================================================


class InstagramListMediaConfig(BaseModel):
    """List media from the authenticated user's account"""

    operation: Literal["list_user_media"] = Field(
        "list_user_media",
        json_schema_extra={
            "const": "list_user_media",
            "ui:hidden": True,
            "x-category": "Media",
            "x-is-trigger": False,
            "x-display-name": "List User Media",
        },
        title="List User Media",
    )
    fields: Optional[str] = Field(
        "id,caption,media_type,media_url,permalink,thumbnail_url,timestamp,username",
        title="Fields",
        description="Comma-separated list of fields to retrieve for each media",
    )
    limit: Optional[int] = Field(
        25,
        title="Limit",
        description="Number of media items to retrieve (max 100)",
        ge=1,
        le=100,
    )
    after: Optional[str] = Field(
        None, title="After Cursor", description="Pagination cursor for next page"
    )


class InstagramGetMediaConfig(BaseModel):
    """Get details of a specific media item"""

    operation: Literal["get_media_details"] = Field(
        "get_media_details",
        json_schema_extra={
            "const": "get_media_details",
            "ui:hidden": True,
            "x-category": "Media",
            "x-is-trigger": False,
            "x-display-name": "Get Media Details",
        },
        title="Get Media Details",
    )
    media_id: str = Field(
        ..., title="Media ID", description="The ID of the media to retrieve"
    )
    fields: Optional[str] = Field(
        "id,caption,media_type,media_url,permalink,thumbnail_url,timestamp,username,like_count,comments_count",
        title="Fields",
        description="Comma-separated list of fields to retrieve",
    )


class InstagramPublishPhotoConfig(BaseModel):
    """Publish a photo to Instagram"""

    operation: Literal["publish_photo_post"] = Field(
        "publish_photo_post",
        json_schema_extra={
            "const": "publish_photo_post",
            "ui:hidden": True,
            "x-category": "Media",
            "x-is-trigger": False,
            "x-display-name": "Publish Photo Post",
        },
        title="Publish Photo Post",
    )
    image_url: str = Field(
        ...,
        title="Image URL",
        description="The image to publish — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}). JPEG only; must be reachable by Instagram's servers.",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": "image/*"},
    )
    caption: Optional[str] = Field(
        None,
        title="Caption",
        description="Caption for the post (hashtags should be included here)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    location_id: Optional[str] = Field(
        None, title="Location ID", description="Facebook Page ID of a location to tag"
    )
    user_tags: Optional[str] = Field(
        None,
        title="User Tags",
        description="JSON array of user tags: [{username: 'user', x: 0.5, y: 0.5}]",
    )


class InstagramPublishVideoConfig(BaseModel):
    """Publish a video (Reel) to Instagram"""

    operation: Literal["publish_video_reel"] = Field(
        "publish_video_reel",
        json_schema_extra={
            "const": "publish_video_reel",
            "ui:hidden": True,
            "x-category": "Media",
            "x-is-trigger": False,
            "x-display-name": "Publish Video Reel",
        },
        title="Publish Video Reel",
    )
    video_url: str = Field(
        ...,
        title="Video URL",
        description="The video to publish — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}). MP4 recommended.",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": "video/*"},
    )
    caption: Optional[str] = Field(
        None,
        title="Caption",
        description="Caption for the reel",
        json_schema_extra={"ui:widget": "textarea"},
    )
    cover_url: Optional[str] = Field(
        None,
        title="Cover Image URL",
        description="The cover image to send — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}). JPEG.",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": "image/*"},
    )
    share_to_feed: Optional[bool] = Field(
        True,
        title="Share to Feed",
        description="Whether to also share the reel to the main feed",
    )
    location_id: Optional[str] = Field(
        None, title="Location ID", description="Facebook Page ID of a location to tag"
    )


class InstagramPublishCarouselConfig(BaseModel):
    """Publish a carousel (multiple images/videos) to Instagram"""

    operation: Literal["publish_carousel_post"] = Field(
        "publish_carousel_post",
        json_schema_extra={
            "const": "publish_carousel_post",
            "ui:hidden": True,
            "x-category": "Media",
            "x-is-trigger": False,
            "x-display-name": "Publish Carousel Post",
        },
        title="Publish Carousel Post",
    )
    media_urls: str = Field(
        ...,
        title="Media URLs",
        description="JSON array of media URLs (2-10 items): [{type: 'IMAGE', url: '...'}, {type: 'VIDEO', url: '...'}]",
        json_schema_extra={"ui:widget": "textarea"},
    )
    caption: Optional[str] = Field(
        None,
        title="Caption",
        description="Caption for the carousel post",
        json_schema_extra={"ui:widget": "textarea"},
    )
    location_id: Optional[str] = Field(
        None, title="Location ID", description="Facebook Page ID of a location to tag"
    )


# ============================================================================
# Comment Operations
# ============================================================================


class InstagramListCommentsConfig(BaseModel):
    """List comments on a media item"""

    operation: Literal["list_media_comments"] = Field(
        "list_media_comments",
        json_schema_extra={
            "const": "list_media_comments",
            "ui:hidden": True,
            "x-category": "Comment",
            "x-is-trigger": False,
            "x-display-name": "List Media Comments",
        },
        title="List Media Comments",
    )
    media_id: str = Field(
        ..., title="Media ID", description="The ID of the media to get comments for"
    )
    fields: Optional[str] = Field(
        "id,text,username,timestamp,like_count,replies{id,text,username,timestamp}",
        title="Fields",
        description="Comma-separated list of fields to retrieve for each comment",
    )
    limit: Optional[int] = Field(
        25, title="Limit", description="Number of comments to retrieve", ge=1, le=50
    )
    after: Optional[str] = Field(
        None, title="After Cursor", description="Pagination cursor for next page"
    )


class InstagramCreateCommentConfig(BaseModel):
    """Create a comment on a media item"""

    operation: Literal["create_media_comment"] = Field(
        "create_media_comment",
        json_schema_extra={
            "const": "create_media_comment",
            "ui:hidden": True,
            "x-category": "Comment",
            "x-is-trigger": False,
            "x-display-name": "Create Media Comment",
        },
        title="Create Media Comment",
    )
    media_id: str = Field(
        ..., title="Media ID", description="The ID of the media to comment on"
    )
    message: str = Field(
        ...,
        title="Comment Text",
        description="The comment text",
        json_schema_extra={"ui:widget": "textarea"},
    )


class InstagramReplyToCommentConfig(BaseModel):
    """Reply to a comment"""

    operation: Literal["reply_to_comment"] = Field(
        "reply_to_comment",
        json_schema_extra={
            "const": "reply_to_comment",
            "ui:hidden": True,
            "x-category": "Comment",
            "x-is-trigger": False,
            "x-display-name": "Reply to Comment",
        },
        title="Reply to Comment",
    )
    comment_id: str = Field(
        ..., title="Comment ID", description="The ID of the comment to reply to"
    )
    message: str = Field(
        ...,
        title="Reply Text",
        description="The reply text",
        json_schema_extra={"ui:widget": "textarea"},
    )


class InstagramHideCommentConfig(BaseModel):
    """Hide or unhide a comment"""

    operation: Literal["hide_or_unhide_comment"] = Field(
        "hide_or_unhide_comment",
        json_schema_extra={
            "const": "hide_or_unhide_comment",
            "ui:hidden": True,
            "x-category": "Comment",
            "x-is-trigger": False,
            "x-display-name": "Hide or Unhide Comment",
        },
        title="Hide or Unhide Comment",
    )
    comment_id: str = Field(
        ..., title="Comment ID", description="The ID of the comment to hide/unhide"
    )
    hide: bool = Field(True, title="Hide", description="True to hide, False to unhide")


class InstagramDeleteCommentConfig(BaseModel):
    """Delete a comment"""

    operation: Literal["delete_comment"] = Field(
        "delete_comment",
        json_schema_extra={
            "const": "delete_comment",
            "ui:hidden": True,
            "x-category": "Comment",
            "x-is-trigger": False,
            "x-display-name": "Delete Comment",
        },
        title="Delete Comment",
    )
    comment_id: str = Field(
        ...,
        title="Comment ID",
        description="The ID of the comment to delete (must be your own comment)",
    )


# ============================================================================
# Insights Operations
# ============================================================================


class InstagramGetMediaInsightsConfig(BaseModel):
    """Get insights for a specific media item"""

    operation: Literal["get_media_insights"] = Field(
        "get_media_insights",
        json_schema_extra={
            "const": "get_media_insights",
            "ui:hidden": True,
            "x-category": "Media",
            "x-is-trigger": False,
            "x-display-name": "Get Media Insights",
        },
        title="Get Media Insights",
    )
    media_id: str = Field(
        ..., title="Media ID", description="The ID of the media to get insights for"
    )
    metrics: Optional[str] = Field(
        "reach,likes,comments,shares,saved",
        title="Metrics",
        description="Comma-separated metrics: reach, likes, comments, shares, saved, views (impressions/engagement were deprecated by Meta and 400 on graph.instagram.com).",
    )


class InstagramGetAccountInsightsConfig(BaseModel):
    """Get insights for the Instagram account"""

    operation: Literal["get_account_insights"] = Field(
        "get_account_insights",
        json_schema_extra={
            "const": "get_account_insights",
            "ui:hidden": True,
            "x-category": "Profile",
            "x-is-trigger": False,
            "x-display-name": "Get Account Insights",
        },
        title="Get Account Insights",
    )
    metrics: Optional[str] = Field(
        "reach,follower_count,profile_views",
        title="Metrics",
        description="Comma-separated metrics: reach, follower_count, profile_views, website_clicks (impressions was deprecated by Meta and 400s on graph.instagram.com).",
    )
    period: Optional[str] = Field(
        "day",
        title="Period",
        description="Time aggregation period",
        json_schema_extra={"enum": ["day", "week", "days_28", "lifetime"]},
    )
    since: Optional[str] = Field(
        None,
        title="Since",
        description="Start date (YYYY-MM-DD) for time-based metrics",
    )
    until: Optional[str] = Field(
        None, title="Until", description="End date (YYYY-MM-DD) for time-based metrics"
    )


# ============================================================================
# Hashtag Operations
# ============================================================================


class InstagramSearchHashtagConfig(BaseModel):
    """Search for a hashtag ID"""

    operation: Literal["search_hashtag_id"] = Field(
        "search_hashtag_id",
        json_schema_extra={
            "const": "search_hashtag_id",
            "x-requires-login": "facebook",
            "ui:hidden": True,
            "x-category": "Hashtag",
            "x-is-trigger": False,
            "x-display-name": "Search Hashtag Id",
        },
        title="Search Hashtag Id",
    )
    hashtag: str = Field(
        ..., title="Hashtag", description="The hashtag to search for (without #)"
    )


class InstagramGetHashtagMediaConfig(BaseModel):
    """Get top or recent media for a hashtag"""

    operation: Literal["get_hashtag_media"] = Field(
        "get_hashtag_media",
        json_schema_extra={
            "const": "get_hashtag_media",
            "x-requires-login": "facebook",
            "ui:hidden": True,
            "x-category": "Hashtag",
            "x-is-trigger": False,
            "x-display-name": "Get Hashtag Media",
        },
        title="Get Hashtag Media",
    )
    hashtag_id: str = Field(
        ...,
        title="Hashtag ID",
        description="The ID of the hashtag (from search_hashtag)",
    )
    media_type: str = Field(
        "top_media",
        title="Media Type",
        description="Which media to retrieve",
        json_schema_extra={"enum": ["top_media", "recent_media"]},
    )
    fields: Optional[str] = Field(
        "id,caption,media_type,media_url,permalink,timestamp",
        title="Fields",
        description="Comma-separated list of fields",
    )
    limit: Optional[int] = Field(
        25, title="Limit", description="Number of media items to retrieve", ge=1, le=50
    )


# ============================================================================
# Business Discovery Operations
# ============================================================================


class InstagramBusinessDiscoveryConfig(BaseModel):
    """Discover public business/creator account information"""

    operation: Literal["discover_business_account"] = Field(
        "discover_business_account",
        json_schema_extra={
            "const": "discover_business_account",
            "x-requires-login": "facebook",
            "ui:hidden": True,
            "x-category": "Profile",
            "x-is-trigger": False,
            "x-display-name": "Discover Business Account",
        },
        title="Discover Business Account",
    )
    username: str = Field(
        ..., title="Username", description="The Instagram username to look up"
    )
    fields: Optional[str] = Field(
        "id,username,name,biography,followers_count,follows_count,media_count,profile_picture_url,website",
        title="Fields",
        description="Comma-separated list of fields to retrieve",
    )


# ============================================================================
# Stories Operations
# ============================================================================


class InstagramPublishStoryPhotoConfig(BaseModel):
    """Publish a photo story to Instagram"""

    operation: Literal["publish_photo_story"] = Field(
        "publish_photo_story",
        json_schema_extra={
            "const": "publish_photo_story",
            "ui:hidden": True,
            "x-category": "Story",
            "x-is-trigger": False,
            "x-display-name": "Publish Photo Story",
        },
        title="Publish Photo Story",
    )
    image_url: str = Field(
        ...,
        title="Image URL",
        description="The image to publish — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}). JPEG only; 1080x1920 recommended.",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": "image/*"},
    )
    caption: Optional[str] = Field(
        None,
        title="Caption",
        description="Optional caption for the story",
        json_schema_extra={"ui:widget": "textarea"},
    )


class InstagramPublishStoryVideoConfig(BaseModel):
    """Publish a video story to Instagram"""

    operation: Literal["publish_video_story"] = Field(
        "publish_video_story",
        json_schema_extra={
            "const": "publish_video_story",
            "ui:hidden": True,
            "x-category": "Story",
            "x-is-trigger": False,
            "x-display-name": "Publish Video Story",
        },
        title="Publish Video Story",
    )
    video_url: str = Field(
        ...,
        title="Video URL",
        description="The video to publish — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}). MP4 recommended; max 15 seconds.",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": "video/*"},
    )
    caption: Optional[str] = Field(
        None,
        title="Caption",
        description="Optional caption for the story",
        json_schema_extra={"ui:widget": "textarea"},
    )


# ============================================================================
# Mentions Operations
# ============================================================================


class InstagramGetMentionedMediaConfig(BaseModel):
    """Get media where the account is @mentioned"""

    operation: Literal["get_mentioned_media"] = Field(
        "get_mentioned_media",
        json_schema_extra={
            "const": "get_mentioned_media",
            "ui:hidden": True,
            "x-category": "Media",
            "x-is-trigger": False,
            "x-display-name": "Get Mentioned Media",
        },
        title="Get Mentioned Media",
    )
    media_id: str = Field(
        ...,
        title="Media ID",
        description="ID of the media you were @mentioned in (delivered by the Instagram "
                    "'mentions' webhook). The API has no list edge for mentions — you look up "
                    "one mention at a time by its id.",
    )
    fields: Optional[str] = Field(
        "id,caption,media_type,media_url,permalink,timestamp,username",
        title="Fields",
        description="Comma-separated list of fields to retrieve for the mentioned media",
    )


class InstagramGetMentionedCommentsConfig(BaseModel):
    """Get comments where the account is @mentioned"""

    operation: Literal["get_mentioned_comments"] = Field(
        "get_mentioned_comments",
        json_schema_extra={
            "const": "get_mentioned_comments",
            "ui:hidden": True,
            "x-category": "Comment",
            "x-is-trigger": False,
            "x-display-name": "Get Mentioned Comments",
        },
        title="Get Mentioned Comments",
    )
    comment_id: str = Field(
        ...,
        title="Comment ID",
        description="ID of the comment you were @mentioned in (delivered by the Instagram "
                    "'mentions' webhook). The API has no list edge for mentions — you look up "
                    "one mention at a time by its id.",
    )
    fields: Optional[str] = Field(
        "id,text,username,timestamp,media{id,caption,media_type}",
        title="Fields",
        description="Comma-separated list of fields to retrieve for the mentioned comment",
    )


# ============================================================================
# Product Tagging / Shopping Operations
# ============================================================================


class InstagramTagProductsConfig(BaseModel):
    """Tag products in a media post for Instagram Shopping"""

    operation: Literal["tag_products_in_media"] = Field(
        "tag_products_in_media",
        json_schema_extra={
            "const": "tag_products_in_media",
            "x-requires-login": "facebook",
            "ui:hidden": True,
            "x-category": "Media",
            "x-is-trigger": False,
            "x-display-name": "Tag Products in Media",
        },
        title="Tag Products in Media",
    )
    media_id: str = Field(
        ..., title="Media ID", description="The ID of the media to tag products in"
    )
    product_tags: str = Field(
        ...,
        title="Product Tags",
        description="JSON array of product tags: [{product_id: '123', x: 0.5, y: 0.5}]",
        json_schema_extra={"ui:widget": "textarea"},
    )


class InstagramGetProductTagsConfig(BaseModel):
    """Get product tags on a media post"""

    operation: Literal["get_media_product_tags"] = Field(
        "get_media_product_tags",
        json_schema_extra={
            "const": "get_media_product_tags",
            "x-requires-login": "facebook",
            "ui:hidden": True,
            "x-category": "Media",
            "x-is-trigger": False,
            "x-display-name": "Get Media Product Tags",
        },
        title="Get Media Product Tags",
    )
    media_id: str = Field(
        ...,
        title="Media ID",
        description="The ID of the media to get product tags from",
    )


class InstagramDeleteProductTagsConfig(BaseModel):
    """Delete product tags from a media post"""

    operation: Literal["delete_product_tags_from_media"] = Field(
        "delete_product_tags_from_media",
        json_schema_extra={
            "const": "delete_product_tags_from_media",
            "x-requires-login": "facebook",
            "ui:hidden": True,
            "x-category": "Media",
            "x-is-trigger": False,
            "x-display-name": "Delete Product Tags from Media",
        },
        title="Delete Product Tags from Media",
    )
    media_id: str = Field(
        ...,
        title="Media ID",
        description="The ID of the media to delete product tags from",
    )


# ============================================================================
# Direct Messaging (DM) Operations
# ============================================================================
# Instagram Messaging is served from graph.facebook.com via the linked Page and
# requires the instagram_manage_messages permission. Sends are subject to the
# platform's 24-hour messaging window. The recipient id is the Instagram-scoped
# user id (IGSID) carried on inbound message events.


class InstagramSendDMConfig(BaseModel):
    """Send a text direct message"""

    operation: Literal["send_dm"] = Field(
        "send_dm",
        json_schema_extra={
            "const": "send_dm",
            "ui:hidden": True,
            "x-category": "Messaging",
            "x-is-trigger": False,
            "x-display-name": "Send DM",
        },
        title="Send DM",
    )
    recipient_id: str = Field(
        ...,
        title="Recipient ID",
        description="The Instagram-scoped user id (IGSID) of the recipient",
    )
    text: str = Field(
        ...,
        title="Message Text",
        description="The text of the direct message",
        json_schema_extra={"ui:widget": "textarea"},
    )


class InstagramSendDMAttachmentConfig(BaseModel):
    """Send a media attachment (image/video/audio) as a direct message"""

    operation: Literal["send_dm_attachment"] = Field(
        "send_dm_attachment",
        json_schema_extra={
            "const": "send_dm_attachment",
            "ui:hidden": True,
            "x-category": "Messaging",
            "x-is-trigger": False,
            "x-display-name": "Send DM Attachment",
        },
        title="Send DM Attachment",
    )
    recipient_id: str = Field(
        ...,
        title="Recipient ID",
        description="The Instagram-scoped user id (IGSID) of the recipient",
    )
    attachment_type: str = Field(
        "image",
        title="Attachment Type",
        description="Type of media attachment to send",
        json_schema_extra={"enum": ["image", "video", "audio"]},
    )
    attachment_url: str = Field(
        ...,
        title="Attachment URL",
        description="Public URL of the media to send",
    )


class InstagramSendDMReactionConfig(BaseModel):
    """React to a direct message"""

    operation: Literal["send_dm_reaction"] = Field(
        "send_dm_reaction",
        json_schema_extra={
            "const": "send_dm_reaction",
            "ui:hidden": True,
            "x-category": "Messaging",
            "x-is-trigger": False,
            "x-display-name": "Send DM Reaction",
        },
        title="Send DM Reaction",
    )
    recipient_id: str = Field(
        ...,
        title="Recipient ID",
        description="The Instagram-scoped user id (IGSID) of the recipient",
    )
    message_id: str = Field(
        ...,
        title="Message ID",
        description="The id of the message to react to",
    )
    reaction: str = Field(
        "love",
        title="Reaction",
        description="The reaction to apply to the message",
    )


class InstagramMarkDMSeenConfig(BaseModel):
    """Mark direct messages from a sender as seen"""

    operation: Literal["mark_dm_seen"] = Field(
        "mark_dm_seen",
        json_schema_extra={
            "const": "mark_dm_seen",
            "ui:hidden": True,
            "x-category": "Messaging",
            "x-is-trigger": False,
            "x-display-name": "Mark DM Seen",
        },
        title="Mark DM Seen",
    )
    recipient_id: str = Field(
        ...,
        title="Recipient ID",
        description="The Instagram-scoped user id (IGSID) whose messages to mark seen",
    )


class InstagramListConversationsConfig(BaseModel):
    """List Instagram DM conversations"""

    operation: Literal["list_conversations"] = Field(
        "list_conversations",
        json_schema_extra={
            "const": "list_conversations",
            "ui:hidden": True,
            "x-category": "Messaging",
            "x-is-trigger": False,
            "x-display-name": "List Conversations",
        },
        title="List Conversations",
    )
    fields: Optional[str] = Field(
        "id,participants,updated_time",
        title="Fields",
        description="Comma-separated list of fields to retrieve for each conversation",
    )
    limit: Optional[int] = Field(
        25,
        title="Limit",
        description="Number of conversations to retrieve",
        ge=1,
        le=100,
    )
    after: Optional[str] = Field(
        None, title="After Cursor", description="Pagination cursor for next page"
    )


class InstagramGetConversationConfig(BaseModel):
    """Get a conversation and its messages"""

    operation: Literal["get_conversation"] = Field(
        "get_conversation",
        json_schema_extra={
            "const": "get_conversation",
            "ui:hidden": True,
            "x-category": "Messaging",
            "x-is-trigger": False,
            "x-display-name": "Get Conversation",
        },
        title="Get Conversation",
    )
    conversation_id: str = Field(
        ..., title="Conversation ID", description="The id of the conversation to retrieve"
    )
    fields: Optional[str] = Field(
        "messages{id,from,to,message,created_time}",
        title="Fields",
        description="Comma-separated list of fields to retrieve",
    )


class InstagramGetDMMessageConfig(BaseModel):
    """Get a single direct message"""

    operation: Literal["get_dm_message"] = Field(
        "get_dm_message",
        json_schema_extra={
            "const": "get_dm_message",
            "ui:hidden": True,
            "x-category": "Messaging",
            "x-is-trigger": False,
            "x-display-name": "Get DM Message",
        },
        title="Get DM Message",
    )
    message_id: str = Field(
        ..., title="Message ID", description="The id of the message to retrieve"
    )
    fields: Optional[str] = Field(
        "id,from,to,message,created_time,attachments",
        title="Fields",
        description="Comma-separated list of fields to retrieve",
    )


# ============================================================================
# Scraping Operations (Apify — no user credential required)
# ============================================================================


class InstagramScrapeProfileConfig(BaseModel):
    """Scrape public Instagram profile metadata via Apify ($1.60/1k profiles)."""

    model_config = ConfigDict(
        populate_by_name=True,
        title="Scrape Profile",
        json_schema_extra=PLATFORM_KEYED,
    )

    operation: Literal["scrape_profile_metadata"] = Field(
        default="scrape_profile_metadata",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Profile",
            "x-is-trigger": False,
            "x-display-name": "Scrape Profile Metadata",
        },
        title="Scrape Profile Metadata",
    )
    usernames: str = Field(
        ...,
        title="Usernames",
        description=("One Instagram username per line (without @). " "Example: natgeo"),
        json_schema_extra={"ui:widget": "textarea"},
    )
    max_results: int = Field(
        default=10,
        title="Max Profiles",
        description="Maximum number of profiles to return.",
        ge=1,
        le=200,
    )


class InstagramScrapePostsConfig(BaseModel):
    """Scrape recent posts from one or more public Instagram profiles via Apify ($1/1k posts)."""

    model_config = ConfigDict(
        populate_by_name=True,
        title="Scrape Posts from Profile",
        json_schema_extra=PLATFORM_KEYED,
    )

    operation: Literal["scrape_profile_posts"] = Field(
        default="scrape_profile_posts",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Profile",
            "x-is-trigger": False,
            "x-display-name": "Scrape Profile Posts",
        },
        title="Scrape Profile Posts",
    )
    usernames: str = Field(
        ...,
        title="Usernames",
        description="One Instagram username per line (without @).",
        json_schema_extra={"ui:widget": "textarea"},
    )
    max_results: int = Field(
        default=30,
        title="Max Posts Per Profile",
        description="Maximum number of posts to return per username.",
        ge=1,
        le=500,
    )


class InstagramScrapePostConfig(BaseModel):
    """Scrape a specific Instagram post or reel by URL via Apify ($1.50/1k results)."""

    model_config = ConfigDict(
        populate_by_name=True,
        title="Scrape Post by URL",
        json_schema_extra=PLATFORM_KEYED,
    )

    operation: Literal["scrape_individual_post"] = Field(
        default="scrape_individual_post",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Media",
            "x-is-trigger": False,
            "x-display-name": "Scrape Individual Post",
        },
        title="Scrape Individual Post",
    )
    post_urls: str = Field(
        ...,
        title="Post URLs",
        description=(
            "One Instagram post or reel URL per line. "
            "Example: https://www.instagram.com/p/ABC123/"
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )


class InstagramScrapeHashtagConfig(BaseModel):
    """Scrape recent posts for a hashtag via Apify ($1.50/1k results)."""

    model_config = ConfigDict(
        populate_by_name=True,
        title="Scrape Hashtag Feed",
        json_schema_extra=PLATFORM_KEYED,
    )

    operation: Literal["scrape_hashtag_posts"] = Field(
        default="scrape_hashtag_posts",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Hashtag",
            "x-is-trigger": False,
            "x-display-name": "Scrape Hashtag Posts",
        },
        title="Scrape Hashtag Posts",
    )
    hashtags: str = Field(
        ...,
        title="Hashtags",
        description=("One hashtag per line (without #). " "Example: photography"),
        json_schema_extra={"ui:widget": "textarea"},
    )
    max_results: int = Field(
        default=30,
        title="Max Posts Per Hashtag",
        ge=1,
        le=500,
    )


class InstagramScrapeReelsConfig(BaseModel):
    """Scrape reels from public Instagram profiles via Apify ($1/1k reels)."""

    model_config = ConfigDict(
        populate_by_name=True,
        title="Scrape Reels from Profile",
        json_schema_extra=PLATFORM_KEYED,
    )

    operation: Literal["scrape_profile_reels"] = Field(
        default="scrape_profile_reels",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Profile",
            "x-is-trigger": False,
            "x-display-name": "Scrape Profile Reels",
        },
        title="Scrape Profile Reels",
    )
    profile_urls: str = Field(
        ...,
        title="Profile URLs or Reel URLs",
        description=(
            "One Instagram profile URL or reel URL per line. "
            "Example: https://www.instagram.com/natgeo/"
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )
    max_results: int = Field(
        default=30,
        title="Max Reels",
        ge=1,
        le=500,
    )


class InstagramScrapeCommentsConfig(BaseModel):
    """Scrape comments from Instagram posts or reels via Apify ($1–$1.50/1k comments)."""

    model_config = ConfigDict(
        populate_by_name=True,
        title="Scrape Comments",
        json_schema_extra=PLATFORM_KEYED,
    )

    operation: Literal["scrape_post_comments"] = Field(
        default="scrape_post_comments",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Comment",
            "x-is-trigger": False,
            "x-display-name": "Scrape Post Comments",
        },
        title="Scrape Post Comments",
    )
    post_urls: str = Field(
        ...,
        title="Post or Reel URLs",
        description=(
            "One Instagram post or reel URL per line. "
            "Example: https://www.instagram.com/p/ABC123/"
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )
    max_results: int = Field(
        default=50,
        title="Max Comments Per Post",
        ge=1,
        le=1000,
    )


# ============================================================================
# Discriminated Union
# ============================================================================

InstagramConfig = Annotated[
    Union[
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
        # Business discovery (1)
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
        # Direct messaging operations (7)
        InstagramSendDMConfig,
        InstagramSendDMAttachmentConfig,
        InstagramSendDMReactionConfig,
        InstagramMarkDMSeenConfig,
        InstagramListConversationsConfig,
        InstagramGetConversationConfig,
        InstagramGetDMMessageConfig,
        # Scraping operations via Apify — no credential required (6)
        InstagramScrapeProfileConfig,
        InstagramScrapePostsConfig,
        InstagramScrapePostConfig,
        InstagramScrapeHashtagConfig,
        InstagramScrapeReelsConfig,
        InstagramScrapeCommentsConfig,
    ],
    Discriminator("operation"),
]


# ============================================================================
# Full Node Configuration
# ============================================================================


class InstagramNodeConfig(NodeConfig[InstagramConfig, InstagramCredential]):
    """Full configuration for Instagram node including credentials"""

    pass


# ============================================================================
# Node Implementation
# ============================================================================


class InstagramNode(ApifyRunnerMixin, WorkflowNode):
    """
    Instagram Graph API automation node.

    Executes Instagram API operations for workflow automation.
    Supports 23 operations across profile, media, comments, insights, hashtags, stories, mentions, and shopping.
    """

    edit_examples = [
        "Publish photo with caption and tag products for Instagram Shop",
        "Get last 20 media items and retrieve insights like reach/engagement",
        "Create comment reply to customer question on latest post",
        "Search hashtag #ProductLaunch and get top media from that hashtag",
        "List mentions where account was tagged and hide spam comments",
        "Publish carousel with 3 product images and publish story photo",
        "Get account followers/engagement stats and discover @competitor profile",
    ]

    scope_registry = INSTAGRAM_SCOPES
    connection_evidence = ConnectionEvidence(
        operation="list_user_media",
        noun="posts",
        identity_operation="get_user_profile",
    )

    @classmethod
    def get_config_model(cls):
        """Return the Pydantic model for node configuration."""
        return InstagramNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the configured operation.

        Args:
            inputs: Output data from upstream nodes

        Returns:
            Dict with operation results including status, action, data, and timing
        """
        start_time = time.time()

        # Validate configuration
        config = self.config
        if not config or not isinstance(config, InstagramNodeConfig):
            raise ValueError("Valid configuration is required")

        op_config = config.config

        # Scraping operations run through NoClick's Apify integration (server-side token).
        # No Instagram OAuth credential is required; billed against the user's NoClick balance.
        scraping_handlers = {
            InstagramScrapeProfileConfig: self._scrape_profile,
            InstagramScrapePostsConfig: self._scrape_posts,
            InstagramScrapePostConfig: self._scrape_post,
            InstagramScrapeHashtagConfig: self._scrape_hashtag,
            InstagramScrapeReelsConfig: self._scrape_reels,
            InstagramScrapeCommentsConfig: self._scrape_comments,
        }
        if type(op_config) in scraping_handlers:
            return await scraping_handlers[type(op_config)](op_config)

        # OAuth operations — credentials are required
        credentials = config.credentials
        if not credentials:
            raise ValueError(
                "Credentials are required. Connect your Instagram Business account via Facebook OAuth."
            )

        # Route to appropriate handler based on action
        handlers = {
            # Profile operations
            "get_user_profile": self._handle_get_profile,
            # Media operations
            "list_user_media": self._handle_list_media,
            "get_media_details": self._handle_get_media,
            "publish_photo_post": self._handle_publish_photo,
            "publish_video_reel": self._handle_publish_video,
            "publish_carousel_post": self._handle_publish_carousel,
            # Comment operations
            "list_media_comments": self._handle_list_comments,
            "create_media_comment": self._handle_create_comment,
            "reply_to_comment": self._handle_reply_to_comment,
            "hide_or_unhide_comment": self._handle_hide_comment,
            "delete_comment": self._handle_delete_comment,
            # Insights operations
            "get_media_insights": self._handle_get_media_insights,
            "get_account_insights": self._handle_get_account_insights,
            # Hashtag operations
            "search_hashtag_id": self._handle_search_hashtag,
            "get_hashtag_media": self._handle_get_hashtag_media,
            # Business discovery
            "discover_business_account": self._handle_business_discovery,
            # Stories operations
            "publish_photo_story": self._handle_publish_story_photo,
            "publish_video_story": self._handle_publish_story_video,
            # Mentions operations
            "get_mentioned_media": self._handle_get_mentioned_media,
            "get_mentioned_comments": self._handle_get_mentioned_comments,
            # Product tagging operations
            "tag_products_in_media": self._handle_tag_products,
            "get_media_product_tags": self._handle_get_product_tags,
            "delete_product_tags_from_media": self._handle_delete_product_tags,
            # Direct messaging operations
            "send_dm": self._handle_send_dm,
            "send_dm_attachment": self._handle_send_dm_attachment,
            "send_dm_reaction": self._handle_send_dm_reaction,
            "mark_dm_seen": self._handle_mark_dm_seen,
            "list_conversations": self._handle_list_conversations,
            "get_conversation": self._handle_get_conversation,
            "get_dm_message": self._handle_get_dm_message,
        }

        action = op_config.operation
        handler = handlers.get(action)

        if not handler:
            raise ValueError(f"Unknown action: {action}")

        # Instagram Login (graph.instagram.com) does not expose hashtag search,
        # product tagging or business discovery — refuse those clearly rather
        # than let the API return an opaque "Unknown path components".
        if isinstance(credentials, InstagramLoginCredential) and action in _FACEBOOK_LOGIN_ONLY_OPS:
            return {
                "status": "error",
                "action": action,
                "error": (f"'{action}' is only available with Instagram via Facebook Login. "
                          "The Instagram Login connection does not support hashtag search, "
                          "product tagging, or business discovery — connect via Facebook Login "
                          "to use this operation."),
                "status_code": 400,
            }

        # Execute the handler
        result = await handler(op_config, credentials)

        # Add timing information
        total_time = (time.time() - start_time) * 1000
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round(total_time, 2),
        }

        return result

    # =========================================================================
    # HTTP Request Helper
    # =========================================================================

    async def _get_access_token(self, credentials: InstagramCredential) -> str:
        """
        Get access token from credentials, refreshing if expired (OAuth type only).

        System User tokens and Page Access Tokens without expiry are returned
        as-is. OAuth tokens refresh through the shared choke point (per-
        credential lock, in-lock DB re-read, CAS persist that raises on a lost
        write, audit row).

        Returns:
            Access token string
        """
        # System User tokens never expire; Page Access Tokens may have no expiry
        expires_at = getattr(credentials, "expires_at", None)
        if expires_at is None:
            return credentials.access_token

        # Two refreshable OAuth types with distinct token endpoints: Facebook
        # Login (graph.facebook.com, fb_exchange_token) and Instagram Login
        # (graph.instagram.com, ig_refresh_token). Others are returned as-is.
        if isinstance(credentials, InstagramLoginCredential):
            refresh_fn, expired_fn, provider = _ig_login_refresh, _ig_login_is_expired, "instagram_login"
        elif isinstance(credentials, InstagramOAuthCredential):
            refresh_fn, expired_fn, provider = refresh_access_token, is_token_expired, "instagram"
        else:
            return credentials.access_token

        if not expired_fn(expires_at):
            return credentials.access_token

        from nodes.core.oauth_refresh import ensure_fresh_oauth_token

        cred_dict = credentials.model_dump()
        # Both flows renew by exchanging the CURRENT access token — there is no
        # separate refresh token, hence the key override (the exchange response
        # carries no refresh_token, so nothing collides).
        token = await ensure_fresh_oauth_token(
            credential_id=self.node_data.get("credential_id"),
            user_id=self.user_id,
            credential=cred_dict,
            refresh=refresh_fn,
            is_expired=expired_fn,
            refresh_token_key="access_token",
            provider=provider,
            caller_path="execute",
        )
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        return token

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        credentials: InstagramCredential,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        action_name: str = "request",
        base_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Make an HTTP request to the Instagram/Facebook Graph API.

        Args:
            method: HTTP method (GET, POST, DELETE)
            endpoint: API endpoint (without base URL)
            credentials: OAuth credentials
            params: Query parameters
            json_body: JSON request body
            action_name: Name of the action (for response metadata)
            base_url: API base URL (Instagram or Facebook)

        Returns:
            Dict with status, action, data, status_code, and timing
        """
        # Host depends on the auth model. Instagram Login (instagram_login) tokens
        # are served from graph.instagram.com; Facebook Login tokens (and system-
        # user / page tokens) from graph.facebook.com. A Facebook-Login token sent
        # to graph.instagram.com is rejected with "Cannot parse access token", and
        # vice-versa, so this routing is not optional.
        if base_url is None:
            base_url = (INSTAGRAM_API_BASE if isinstance(credentials, InstagramLoginCredential)
                        else FACEBOOK_GRAPH_API_BASE)
        url = f"{base_url}{endpoint}"

        # Get access token (handles refresh if needed)
        access_token = await self._get_access_token(credentials)

        # Add access token to params
        if params is None:
            params = {}
        params["access_token"] = access_token

        # Clean params (remove None values)
        params = {k: v for k, v in params.items() if v is not None}

        start_time = time.time()
        max_retries = 3

        async with httpx.AsyncClient(timeout=60.0) as client:
            for attempt in range(max_retries):
                try:
                    response = await client.request(
                        method=method, url=url, params=params, json=json_body
                    )

                    api_time = (time.time() - start_time) * 1000

                    # Handle rate limit: back off and retry up to max_retries times
                    if response.status_code == 429 and attempt < max_retries - 1:
                        retry_after = int(
                            response.headers.get(
                                "Retry-After", min(2**attempt * 5, 30)
                            )
                        )
                        logger.warning(
                            f"[InstagramNode] Rate limited (429) on {action_name}, "
                            f"retrying in {retry_after}s (attempt {attempt + 1}/{max_retries})"
                        )
                        await asyncio.sleep(retry_after)
                        continue

                    if response.status_code >= 400:
                        error_text = response.text
                        try:
                            error_data = response.json()
                            error_message = error_data.get("error", {})
                            if isinstance(error_message, dict):
                                error_message = error_message.get(
                                    "message", str(error_message)
                                )
                        except Exception:
                            error_message = error_text

                        logger.error(f"[InstagramNode] API error: {error_message}")
                        return {
                            "status": "error",
                            "action": action_name,
                            "error": error_message,
                            "status_code": response.status_code,
                            "timing_ms": {"api_request": round(api_time, 2)},
                        }

                    try:
                        data = response.json()
                    except Exception:
                        data = {"raw": response.text}

                    return {
                        "status": "success",
                        "action": action_name,
                        "data": data,
                        "status_code": response.status_code,
                        "timing_ms": {"api_request": round(api_time, 2)},
                    }

                except httpx.TimeoutException:
                    return {
                        "status": "error",
                        "action": action_name,
                        "error": "Request timed out",
                        "status_code": 408,
                        "timing_ms": {
                            "api_request": round((time.time() - start_time) * 1000, 2)
                        },
                    }
                except Exception as e:
                    logger.exception(f"[InstagramNode] Request failed: {e}")
                    return {
                        "status": "error",
                        "action": action_name,
                        "error": str(e),
                        "status_code": 500,
                        "timing_ms": {
                            "api_request": round((time.time() - start_time) * 1000, 2)
                        },
                    }

        # Should not be reached, but satisfy the type checker
        return {
            "status": "error",
            "action": action_name,
            "error": "Max retries exceeded",
            "status_code": 429,
            "timing_ms": {"api_request": round((time.time() - start_time) * 1000, 2)},
        }

    # =========================================================================
    # Profile Operations
    # =========================================================================

    async def _handle_get_profile(
        self, config: InstagramGetProfileConfig, credentials: InstagramCredential
    ) -> Dict[str, Any]:
        """Get the authenticated user's Instagram profile."""
        params = {"fields": config.fields} if config.fields else {}

        return await self._make_request(
            method="GET",
            endpoint=f"/{credentials.instagram_user_id}",
            credentials=credentials,
            params=params,
            action_name="get_user_profile",
        )

    # =========================================================================
    # Media Operations
    # =========================================================================

    async def _handle_list_media(
        self, config: InstagramListMediaConfig, credentials: InstagramCredential
    ) -> Dict[str, Any]:
        """List media from the authenticated user's account."""
        params: Dict[str, Any] = {}
        if config.fields:
            params["fields"] = config.fields
        if config.limit:
            params["limit"] = config.limit
        if config.after:
            params["after"] = config.after

        return await self._make_request(
            method="GET",
            endpoint=f"/{credentials.instagram_user_id}/media",
            credentials=credentials,
            params=params,
            action_name="list_user_media",
        )

    async def _handle_get_media(
        self, config: InstagramGetMediaConfig, credentials: InstagramCredential
    ) -> Dict[str, Any]:
        """Get details of a specific media item."""
        params = {"fields": config.fields} if config.fields else {}

        return await self._make_request(
            method="GET",
            endpoint=f"/{config.media_id}",
            credentials=credentials,
            params=params,
            action_name="get_media_details",
        )

    async def _handle_publish_photo(
        self, config: InstagramPublishPhotoConfig, credentials: InstagramCredential
    ) -> Dict[str, Any]:
        """Publish a photo to Instagram (two-step process)."""
        # Step 1: Create container
        container_params: Dict[str, Any] = {
            "image_url": config.image_url,
        }
        if config.caption:
            container_params["caption"] = config.caption
        if config.location_id:
            container_params["location_id"] = config.location_id
        if config.user_tags:
            container_params["user_tags"] = config.user_tags

        container_result = await self._make_request(
            method="POST",
            endpoint=f"/{credentials.instagram_user_id}/media",
            credentials=credentials,
            params=container_params,
            action_name="create_media_container",
        )

        if container_result["status"] == "error":
            return container_result

        container_id = container_result["data"].get("id")
        if not container_id:
            return {
                "status": "error",
                "action": "publish_photo_post",
                "error": "Failed to create media container",
                "timing_ms": container_result.get("timing_ms", {}),
            }

        # Step 2: Publish
        publish_result = await self._make_request(
            method="POST",
            endpoint=f"/{credentials.instagram_user_id}/media_publish",
            credentials=credentials,
            params={"creation_id": container_id},
            action_name="publish_photo_post",
        )

        publish_result["timing_ms"] = {
            "container_creation": container_result.get("timing_ms", {}).get(
                "api_request", 0
            ),
            **publish_result.get("timing_ms", {}),
        }

        if publish_result["status"] == "error":
            publish_result["container_id"] = container_id

        return publish_result

    async def _handle_publish_video(
        self, config: InstagramPublishVideoConfig, credentials: InstagramCredential
    ) -> Dict[str, Any]:
        """Publish a video (Reel) to Instagram (two-step process)."""
        # Step 1: Create container
        container_params: Dict[str, Any] = {
            "video_url": config.video_url,
            "media_type": "REELS",
        }
        if config.caption:
            container_params["caption"] = config.caption
        if config.cover_url:
            container_params["cover_url"] = config.cover_url
        if config.share_to_feed is not None:
            container_params["share_to_feed"] = str(config.share_to_feed).lower()
        if config.location_id:
            container_params["location_id"] = config.location_id

        container_result = await self._make_request(
            method="POST",
            endpoint=f"/{credentials.instagram_user_id}/media",
            credentials=credentials,
            params=container_params,
            action_name="create_video_container",
        )

        if container_result["status"] == "error":
            return container_result

        container_id = container_result["data"].get("id")
        if not container_id:
            return {
                "status": "error",
                "action": "publish_video_reel",
                "error": "Failed to create video container",
                "timing_ms": container_result.get("timing_ms", {}),
            }

        # Step 2: Wait for video processing to finish before publish.
        # Without this, Meta can return "Media ID is not available".
        wait_result = await self._wait_for_video_container_ready(
            container_id=container_id,
            credentials=credentials,
            action_name="publish_video_reel",
            timeout_seconds=120,
        )
        if wait_result is not None:
            wait_result["container_id"] = container_id
            wait_result["timing_ms"] = {
                "container_creation": container_result.get("timing_ms", {}).get(
                    "api_request", 0
                ),
                **wait_result.get("timing_ms", {}),
            }
            return wait_result

        # Step 3: Publish
        publish_result = await self._make_request(
            method="POST",
            endpoint=f"/{credentials.instagram_user_id}/media_publish",
            credentials=credentials,
            params={"creation_id": container_id},
            action_name="publish_video_reel",
        )

        publish_result["timing_ms"] = {
            "container_creation": container_result.get("timing_ms", {}).get(
                "api_request", 0
            ),
            **publish_result.get("timing_ms", {}),
        }
        publish_result["container_id"] = container_id

        if publish_result["status"] == "error":
            publish_result.setdefault(
                "error", "Publish failed. Container will auto-expire in 24 hours."
            )

        return publish_result

    async def _wait_for_video_container_ready(
        self,
        container_id: str,
        credentials: InstagramCredential,
        action_name: str,
        timeout_seconds: int = 120,
    ) -> Optional[Dict[str, Any]]:
        """
        Poll a media container until video processing is finished.

        Returns:
            None when container is ready to publish.
            Error dict when processing fails or times out.
        """
        import asyncio

        poll_start = time.time()
        poll_interval = 3
        last_status = None

        while (time.time() - poll_start) < timeout_seconds:
            status_result = await self._make_request(
                method="GET",
                endpoint=f"/{container_id}",
                credentials=credentials,
                params={"fields": "status_code,status"},
                action_name=f"{action_name}_status",
            )

            if status_result["status"] != "success":
                return {
                    "status": "error",
                    "action": action_name,
                    "error": status_result.get(
                        "error", "Failed to check video processing status"
                    ),
                    "status_code": status_result.get("status_code", 400),
                    "timing_ms": {
                        "status_poll_total": round(
                            (time.time() - poll_start) * 1000, 2
                        ),
                    },
                }

            data = status_result.get("data", {}) or {}
            status_code = data.get("status_code") or data.get("status")
            last_status = status_code

            if status_code == "FINISHED":
                return None

            if status_code in ("ERROR", "EXPIRED"):
                return {
                    "status": "error",
                    "action": action_name,
                    "error": f"Video processing failed with status: {status_code}",
                    "status_code": 400,
                    "timing_ms": {
                        "status_poll_total": round(
                            (time.time() - poll_start) * 1000, 2
                        ),
                    },
                }

            await asyncio.sleep(poll_interval)

        return {
            "status": "error",
            "action": action_name,
            "error": (
                f"Video processing timed out after {timeout_seconds} seconds"
                + (f" (last status: {last_status})" if last_status else "")
            ),
            "status_code": 408,
            "timing_ms": {
                "status_poll_total": round((time.time() - poll_start) * 1000, 2),
            },
        }

    async def _handle_publish_carousel(
        self, config: InstagramPublishCarouselConfig, credentials: InstagramCredential
    ) -> Dict[str, Any]:
        """Publish a carousel to Instagram (multi-step process)."""
        import json

        try:
            media_items = json.loads(config.media_urls)
        except json.JSONDecodeError:
            return {
                "status": "error",
                "action": "publish_carousel_post",
                "error": "Invalid media_urls JSON format",
            }

        if len(media_items) < 2 or len(media_items) > 10:
            return {
                "status": "error",
                "action": "publish_carousel_post",
                "error": "Carousel must have 2-10 media items",
            }

        # Step 1: Create containers for each media item
        children_ids = []
        for item in media_items:
            media_type = item.get("type", "IMAGE").upper()
            media_url = item.get("url")

            if not media_url:
                return {
                    "status": "error",
                    "action": "publish_carousel_post",
                    "error": "Each media item must have a 'url' field",
                }

            params: Dict[str, Any] = {
                "is_carousel_item": "true",
            }

            if media_type == "IMAGE":
                params["image_url"] = media_url
            elif media_type == "VIDEO":
                params["video_url"] = media_url
                params["media_type"] = "VIDEO"
            else:
                return {
                    "status": "error",
                    "action": "publish_carousel_post",
                    "error": f"Invalid media type: {media_type}. Use 'IMAGE' or 'VIDEO'",
                }

            child_result = await self._make_request(
                method="POST",
                endpoint=f"/{credentials.instagram_user_id}/media",
                credentials=credentials,
                params=params,
                action_name="create_carousel_item",
            )

            if child_result["status"] == "error":
                return child_result

            child_id = child_result["data"].get("id")
            if child_id:
                children_ids.append(child_id)

        # Step 2: Create carousel container
        carousel_params: Dict[str, Any] = {
            "media_type": "CAROUSEL",
            "children": ",".join(children_ids),
        }
        if config.caption:
            carousel_params["caption"] = config.caption
        if config.location_id:
            carousel_params["location_id"] = config.location_id

        carousel_result = await self._make_request(
            method="POST",
            endpoint=f"/{credentials.instagram_user_id}/media",
            credentials=credentials,
            params=carousel_params,
            action_name="create_carousel_container",
        )

        if carousel_result["status"] == "error":
            return carousel_result

        carousel_id = carousel_result["data"].get("id")

        # Step 3: Publish
        publish_result = await self._make_request(
            method="POST",
            endpoint=f"/{credentials.instagram_user_id}/media_publish",
            credentials=credentials,
            params={"creation_id": carousel_id},
            action_name="publish_carousel_post",
        )

        if publish_result["status"] == "error":
            publish_result["container_id"] = carousel_id
            publish_result["child_container_ids"] = children_ids

        return publish_result

    # =========================================================================
    # Comment Operations
    # =========================================================================

    async def _handle_list_comments(
        self, config: InstagramListCommentsConfig, credentials: InstagramCredential
    ) -> Dict[str, Any]:
        """List comments on a media item."""
        params: Dict[str, Any] = {}
        if config.fields:
            params["fields"] = config.fields
        if config.limit:
            params["limit"] = config.limit
        if config.after:
            params["after"] = config.after

        return await self._make_request(
            method="GET",
            endpoint=f"/{config.media_id}/comments",
            credentials=credentials,
            params=params,
            action_name="list_media_comments",
        )

    async def _handle_create_comment(
        self, config: InstagramCreateCommentConfig, credentials: InstagramCredential
    ) -> Dict[str, Any]:
        """Create a comment on a media item."""
        return await self._make_request(
            method="POST",
            endpoint=f"/{config.media_id}/comments",
            credentials=credentials,
            params={"message": config.message},
            action_name="create_media_comment",
        )

    async def _handle_reply_to_comment(
        self, config: InstagramReplyToCommentConfig, credentials: InstagramCredential
    ) -> Dict[str, Any]:
        """Reply to a comment."""
        return await self._make_request(
            method="POST",
            endpoint=f"/{config.comment_id}/replies",
            credentials=credentials,
            params={"message": config.message},
            action_name="reply_to_comment",
        )

    async def _handle_hide_comment(
        self, config: InstagramHideCommentConfig, credentials: InstagramCredential
    ) -> Dict[str, Any]:
        """Hide or unhide a comment."""
        return await self._make_request(
            method="POST",
            endpoint=f"/{config.comment_id}",
            credentials=credentials,
            params={"hide": str(config.hide).lower()},
            action_name="hide_or_unhide_comment",
        )

    async def _handle_delete_comment(
        self, config: InstagramDeleteCommentConfig, credentials: InstagramCredential
    ) -> Dict[str, Any]:
        """Delete a comment."""
        return await self._make_request(
            method="DELETE",
            endpoint=f"/{config.comment_id}",
            credentials=credentials,
            action_name="delete_comment",
        )

    # =========================================================================
    # Insights Operations
    # =========================================================================

    async def _handle_get_media_insights(
        self, config: InstagramGetMediaInsightsConfig, credentials: InstagramCredential
    ) -> Dict[str, Any]:
        """Get insights for a specific media item."""
        params: Dict[str, Any] = {}
        if config.metrics:
            params["metric"] = config.metrics

        return await self._make_request(
            method="GET",
            endpoint=f"/{config.media_id}/insights",
            credentials=credentials,
            params=params,
            action_name="get_media_insights",
        )

    async def _handle_get_account_insights(
        self,
        config: InstagramGetAccountInsightsConfig,
        credentials: InstagramCredential,
    ) -> Dict[str, Any]:
        """Get insights for the Instagram account."""
        params: Dict[str, Any] = {}
        if config.metrics:
            params["metric"] = config.metrics
        if config.period:
            params["period"] = config.period
        if config.since:
            params["since"] = config.since
        if config.until:
            params["until"] = config.until

        return await self._make_request(
            method="GET",
            endpoint=f"/{credentials.instagram_user_id}/insights",
            credentials=credentials,
            params=params,
            action_name="get_account_insights",
        )

    # =========================================================================
    # Hashtag Operations
    # =========================================================================

    async def _handle_search_hashtag(
        self, config: InstagramSearchHashtagConfig, credentials: InstagramCredential
    ) -> Dict[str, Any]:
        """Search for a hashtag ID."""
        return await self._make_request(
            method="GET",
            endpoint="/ig_hashtag_search",
            credentials=credentials,
            params={"user_id": credentials.instagram_user_id, "q": config.hashtag},
            action_name="search_hashtag_id",
        )

    async def _handle_get_hashtag_media(
        self, config: InstagramGetHashtagMediaConfig, credentials: InstagramCredential
    ) -> Dict[str, Any]:
        """Get top or recent media for a hashtag."""
        params: Dict[str, Any] = {"user_id": credentials.instagram_user_id}
        if config.fields:
            params["fields"] = config.fields
        if config.limit:
            params["limit"] = config.limit

        endpoint = f"/{config.hashtag_id}/{config.media_type}"

        return await self._make_request(
            method="GET",
            endpoint=endpoint,
            credentials=credentials,
            params=params,
            action_name="get_hashtag_media",
        )

    # =========================================================================
    # Business Discovery Operations
    # =========================================================================

    async def _handle_business_discovery(
        self, config: InstagramBusinessDiscoveryConfig, credentials: InstagramCredential
    ) -> Dict[str, Any]:
        """Discover public business/creator account information."""
        fields = f"business_discovery.username({config.username}){{{config.fields}}}"

        return await self._make_request(
            method="GET",
            endpoint=f"/{credentials.instagram_user_id}",
            credentials=credentials,
            params={"fields": fields},
            action_name="discover_business_account",
        )

    # =========================================================================
    # Stories Operations
    # =========================================================================

    async def _handle_publish_story_photo(
        self, config: InstagramPublishStoryPhotoConfig, credentials: InstagramCredential
    ) -> Dict[str, Any]:
        """Publish a photo story to Instagram."""
        # Step 1: Create the media container for story
        container_params: Dict[str, Any] = {
            "image_url": config.image_url,
            "media_type": "STORIES",
        }
        if config.caption:
            container_params["caption"] = config.caption

        container_result = await self._make_request(
            method="POST",
            endpoint=f"/{credentials.instagram_user_id}/media",
            credentials=credentials,
            params=container_params,
            action_name="publish_photo_story",
        )

        if container_result["status"] != "success":
            return container_result

        container_id = container_result["data"]["id"]

        # Step 2: Publish the container
        publish_result = await self._make_request(
            method="POST",
            endpoint=f"/{credentials.instagram_user_id}/media_publish",
            credentials=credentials,
            params={"creation_id": container_id},
            action_name="publish_photo_story",
        )

        if publish_result["status"] == "error":
            publish_result["container_id"] = container_id

        return publish_result

    async def _handle_publish_story_video(
        self, config: InstagramPublishStoryVideoConfig, credentials: InstagramCredential
    ) -> Dict[str, Any]:
        """Publish a video story to Instagram."""
        # Step 1: Create the media container for story
        container_params: Dict[str, Any] = {
            "video_url": config.video_url,
            "media_type": "STORIES",
        }
        if config.caption:
            container_params["caption"] = config.caption

        container_result = await self._make_request(
            method="POST",
            endpoint=f"/{credentials.instagram_user_id}/media",
            credentials=credentials,
            params=container_params,
            action_name="publish_video_story",
        )

        if container_result["status"] != "success":
            return container_result

        container_id = container_result["data"]["id"]

        # Step 2: Poll for video processing completion (asyncio.sleep is non-blocking)
        max_attempts = 30
        finished = False
        for _ in range(max_attempts):
            status_result = await self._make_request(
                method="GET",
                endpoint=f"/{container_id}",
                credentials=credentials,
                params={"fields": "status_code"},
                action_name="publish_video_story",
            )

            if status_result["status"] == "success":
                status_code = status_result["data"].get("status_code")
                if status_code == "FINISHED":
                    finished = True
                    break
                elif status_code == "ERROR":
                    return {
                        "status": "error",
                        "action": "publish_video_story",
                        "error": "Video processing failed",
                        "container_id": container_id,
                        "data": status_result["data"],
                        "timing_ms": {"api_request": 0},
                    }

            await asyncio.sleep(2)

        if not finished:
            return {
                "status": "error",
                "action": "publish_video_story",
                "error": "Video processing timed out after 60 seconds. The container will auto-expire in 24 hours.",
                "container_id": container_id,
                "timing_ms": {"api_request": 0},
            }

        # Step 3: Publish the container
        publish_result = await self._make_request(
            method="POST",
            endpoint=f"/{credentials.instagram_user_id}/media_publish",
            credentials=credentials,
            params={"creation_id": container_id},
            action_name="publish_video_story",
        )

        if publish_result["status"] == "error":
            publish_result["container_id"] = container_id

        return publish_result

    # =========================================================================
    # Mentions Operations
    # =========================================================================

    async def _handle_get_mentioned_media(
        self, config: InstagramGetMentionedMediaConfig, credentials: InstagramCredential
    ) -> Dict[str, Any]:
        """Get a media the account is @mentioned in.

        Mentions are exposed only as a field expansion on the IG User node keyed
        by a specific media id (there is no list edge — that returns
        "Unknown path components"). The id is delivered by the mentions webhook.
        """
        sub_fields = config.fields or "id,caption,media_type,media_url,permalink,timestamp,username"
        return await self._make_request(
            method="GET",
            endpoint=f"/{credentials.instagram_user_id}",
            credentials=credentials,
            params={"fields": f"mentioned_media.media_id({config.media_id}){{{sub_fields}}}"},
            action_name="get_mentioned_media",
        )

    async def _handle_get_mentioned_comments(
        self,
        config: InstagramGetMentionedCommentsConfig,
        credentials: InstagramCredential,
    ) -> Dict[str, Any]:
        """Get a comment the account is @mentioned in.

        Like mentioned media, this is a field expansion on the IG User node keyed
        by a specific comment id (no list edge exists). The id is delivered by the
        mentions webhook.
        """
        sub_fields = config.fields or "id,text,username,timestamp,media{id,caption,media_type}"
        return await self._make_request(
            method="GET",
            endpoint=f"/{credentials.instagram_user_id}",
            credentials=credentials,
            params={"fields": f"mentioned_comment.comment_id({config.comment_id}){{{sub_fields}}}"},
            action_name="get_mentioned_comments",
        )

    # =========================================================================
    # Product Tagging / Shopping Operations
    # =========================================================================

    async def _handle_tag_products(
        self, config: InstagramTagProductsConfig, credentials: InstagramCredential
    ) -> Dict[str, Any]:
        """Tag products in a media post for Instagram Shopping."""
        import json

        # Parse product tags JSON
        try:
            product_tags = json.loads(config.product_tags)
        except json.JSONDecodeError as e:
            return {
                "status": "error",
                "action": "tag_products_in_media",
                "error": f"Invalid product_tags JSON: {str(e)}",
                "data": {},
                "timing_ms": {"api_request": 0},
            }

        return await self._make_request(
            method="POST",
            endpoint=f"/{config.media_id}/product_tags",
            credentials=credentials,
            params={"product_tags": product_tags},
            action_name="tag_products_in_media",
        )

    async def _handle_get_product_tags(
        self, config: InstagramGetProductTagsConfig, credentials: InstagramCredential
    ) -> Dict[str, Any]:
        """Get product tags on a media post."""
        return await self._make_request(
            method="GET",
            endpoint=f"/{config.media_id}/product_tags",
            credentials=credentials,
            action_name="get_media_product_tags",
        )

    async def _handle_delete_product_tags(
        self, config: InstagramDeleteProductTagsConfig, credentials: InstagramCredential
    ) -> Dict[str, Any]:
        """Delete product tags from a media post."""
        return await self._make_request(
            method="DELETE",
            endpoint=f"/{config.media_id}/product_tags",
            credentials=credentials,
            action_name="delete_product_tags_from_media",
        )

    # =========================================================================
    # Direct Messaging (DM) Operations
    # =========================================================================
    # Instagram Messaging goes through POST /{ig_user_id}/messages on
    # graph.facebook.com. recipient/message/payload objects are JSON-encoded
    # into the request the same way the Facebook Messenger node encodes them.

    async def _handle_send_dm(
        self, config: InstagramSendDMConfig, credentials: InstagramCredential
    ) -> Dict[str, Any]:
        """Send a text direct message."""
        params = {
            "recipient": json.dumps({"id": config.recipient_id}),
            "message": json.dumps({"text": config.text}),
        }
        return await self._make_request(
            method="POST",
            endpoint=f"/{credentials.instagram_user_id}/messages",
            credentials=credentials,
            params=params,
            action_name="send_dm",
        )

    async def _handle_send_dm_attachment(
        self,
        config: InstagramSendDMAttachmentConfig,
        credentials: InstagramCredential,
    ) -> Dict[str, Any]:
        """Send a media attachment as a direct message."""
        params = {
            "recipient": json.dumps({"id": config.recipient_id}),
            "message": json.dumps(
                {
                    "attachment": {
                        "type": config.attachment_type,
                        "payload": {"url": config.attachment_url},
                    }
                }
            ),
        }
        return await self._make_request(
            method="POST",
            endpoint=f"/{credentials.instagram_user_id}/messages",
            credentials=credentials,
            params=params,
            action_name="send_dm_attachment",
        )

    async def _handle_send_dm_reaction(
        self, config: InstagramSendDMReactionConfig, credentials: InstagramCredential
    ) -> Dict[str, Any]:
        """React to a direct message."""
        params = {
            "recipient": json.dumps({"id": config.recipient_id}),
            "sender_action": "react",
            "payload": json.dumps(
                {"message_id": config.message_id, "reaction": config.reaction}
            ),
        }
        return await self._make_request(
            method="POST",
            endpoint=f"/{credentials.instagram_user_id}/messages",
            credentials=credentials,
            params=params,
            action_name="send_dm_reaction",
        )

    async def _handle_mark_dm_seen(
        self, config: InstagramMarkDMSeenConfig, credentials: InstagramCredential
    ) -> Dict[str, Any]:
        """Mark direct messages from a sender as seen."""
        params = {
            "recipient": json.dumps({"id": config.recipient_id}),
            "sender_action": "mark_seen",
        }
        return await self._make_request(
            method="POST",
            endpoint=f"/{credentials.instagram_user_id}/messages",
            credentials=credentials,
            params=params,
            action_name="mark_dm_seen",
        )

    async def _handle_list_conversations(
        self, config: InstagramListConversationsConfig, credentials: InstagramCredential
    ) -> Dict[str, Any]:
        """List Instagram DM conversations."""
        params: Dict[str, Any] = {"platform": "instagram"}
        if config.fields:
            params["fields"] = config.fields
        if config.limit:
            params["limit"] = config.limit
        if config.after:
            params["after"] = config.after

        return await self._make_request(
            method="GET",
            endpoint=f"/{credentials.instagram_user_id}/conversations",
            credentials=credentials,
            params=params,
            action_name="list_conversations",
        )

    async def _handle_get_conversation(
        self, config: InstagramGetConversationConfig, credentials: InstagramCredential
    ) -> Dict[str, Any]:
        """Get a conversation and its messages."""
        params = {"fields": config.fields} if config.fields else {}

        return await self._make_request(
            method="GET",
            endpoint=f"/{config.conversation_id}",
            credentials=credentials,
            params=params,
            action_name="get_conversation",
        )

    async def _handle_get_dm_message(
        self, config: InstagramGetDMMessageConfig, credentials: InstagramCredential
    ) -> Dict[str, Any]:
        """Get a single direct message."""
        params = {"fields": config.fields} if config.fields else {}

        return await self._make_request(
            method="GET",
            endpoint=f"/{config.message_id}",
            credentials=credentials,
            params=params,
            action_name="get_dm_message",
        )

    # =========================================================================
    # Scraping Operation Handlers
    # =========================================================================

    async def _scrape_profile(
        self, config: InstagramScrapeProfileConfig
    ) -> Dict[str, Any]:
        usernames = self._split_lines(config.usernames)
        if not usernames:
            raise ValueError("At least one username is required.")
        actor_input = {"usernames": usernames}
        result = await self._run_apify_actor(
            APIFY_PROFILE_SCRAPER,
            actor_input,
            action_name="scrape_profile_metadata",
            usage_subtype="instagram/scrape_profile",
            platform="instagram",
        )
        if result.get("data") and isinstance(result["data"].get("items"), list):
            items = result["data"]["items"][: config.max_results]
            result["data"]["items"] = items
            result["data"]["count"] = len(items)
        return result

    async def _scrape_posts(self, config: InstagramScrapePostsConfig) -> Dict[str, Any]:
        usernames = self._split_lines(config.usernames)
        if not usernames:
            raise ValueError("At least one username is required.")
        actor_input = {"username": usernames, "resultsLimit": config.max_results}
        return await self._run_apify_actor(
            APIFY_POST_SCRAPER,
            actor_input,
            action_name="scrape_profile_posts",
            usage_subtype="instagram/scrape_posts",
            platform="instagram",
        )

    async def _scrape_post(self, config: InstagramScrapePostConfig) -> Dict[str, Any]:
        urls = self._split_lines(config.post_urls)
        if not urls:
            raise ValueError("At least one post URL is required.")
        actor_input = {
            "directUrls": urls,
            "resultsType": "posts",
            "resultsLimit": len(urls),
        }
        return await self._run_apify_actor(
            APIFY_SCRAPER,
            actor_input,
            action_name="scrape_individual_post",
            usage_subtype="instagram/scrape_post",
            platform="instagram",
        )

    async def _scrape_hashtag(
        self, config: InstagramScrapeHashtagConfig
    ) -> Dict[str, Any]:
        hashtags = self._split_lines(config.hashtags)
        if not hashtags:
            raise ValueError("At least one hashtag is required.")
        # Single hashtag: use search mode. Multiple: use directUrls for each tag page.
        if len(hashtags) == 1:
            actor_input: Dict[str, Any] = {
                "search": hashtags[0],
                "searchType": "hashtag",
                "searchLimit": 1,
                "resultsType": "posts",
                "resultsLimit": config.max_results,
            }
        else:
            actor_input = {
                "directUrls": [
                    f"https://www.instagram.com/explore/tags/{h}/" for h in hashtags
                ],
                "resultsType": "posts",
                "resultsLimit": config.max_results,
            }
        return await self._run_apify_actor(
            APIFY_SCRAPER,
            actor_input,
            action_name="scrape_hashtag_posts",
            usage_subtype="instagram/scrape_hashtag",
            platform="instagram",
        )

    async def _scrape_reels(self, config: InstagramScrapeReelsConfig) -> Dict[str, Any]:
        urls = self._split_lines(config.profile_urls)
        if not urls:
            raise ValueError("At least one profile URL is required.")
        actor_input = {"directUrls": urls}
        result = await self._run_apify_actor(
            APIFY_REEL_SCRAPER,
            actor_input,
            action_name="scrape_profile_reels",
            usage_subtype="instagram/scrape_reels",
            platform="instagram",
        )
        if result.get("data") and isinstance(result["data"].get("items"), list):
            items = result["data"]["items"][: config.max_results]
            result["data"]["items"] = items
            result["data"]["count"] = len(items)
        return result

    async def _scrape_comments(
        self, config: InstagramScrapeCommentsConfig
    ) -> Dict[str, Any]:
        urls = self._split_lines(config.post_urls)
        if not urls:
            raise ValueError("At least one post URL is required.")
        actor_input = {"postUrls": urls, "commentsLimit": config.max_results}
        return await self._run_apify_actor(
            APIFY_COMMENT_SCRAPER,
            actor_input,
            action_name="scrape_post_comments",
            usage_subtype="instagram/scrape_comments",
            platform="instagram",
        )
