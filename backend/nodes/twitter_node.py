"""
Twitter/X REST API v2 automation node.

Provides workflow integration for Twitter/X with operations for:
- Tweets: Create, delete, get, search
- Users: Lookup by ID, username, get authenticated user
- Likes: Like, unlike, get liked tweets
- Retweets: Retweet, undo retweet, get retweeters
- Follows: Follow, unfollow, get followers/following
- Blocks: Block, unblock, get blocked users
- Mutes: Mute, unmute, get muted users
- Bookmarks: Add, remove, get bookmarks

API Reference: https://developer.x.com/en/docs/x-api
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Union, Literal, List, Annotated

import httpx
from pydantic import BaseModel, Field, Discriminator, ConfigDict

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.dynamic_options import require_credential_token
from nodes.oauth.twitter_oauth import is_token_expired, refresh_access_token
from nodes.scopes.twitter import TWITTER_SCOPES
from utils.credentials import update_credential_data

logger = logging.getLogger(__name__)

TWITTER_API_BASE = "https://api.x.com/2"


# ============================================================================
# Twitter Credential Schemas
# ============================================================================


class TwitterOAuthCredential(BaseModel):
    """OAuth 2.0 credential for Twitter/X.

    Use NoClick's OAuth app (easiest - just click to connect) or provide your own
    client credentials for premium access and custom rate limits.

    Register your own app at: https://developer.x.com/en/portal/dashboard
    """

    credential_type: Literal["twitter_oauth"] = Field(
        "twitter_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(..., title="Access Token")
    refresh_token: Optional[str] = Field(None, title="Refresh Token")
    expires_at: Optional[str] = Field(None, title="Token Expiry")  # ISO 8601
    username: Optional[str] = Field(None, title="Twitter Username")
    user_id: Optional[str] = Field(None, title="Twitter User ID")

    # Optional custom client credentials (for premium/enterprise users)
    client_id: Optional[str] = Field(
        None,
        title="Client ID (Optional)",
        description="Your OAuth 2.0 Client ID - leave empty to use NoClick's OAuth app",
        json_schema_extra={"x-optional-custom": True},
    )
    client_secret: Optional[str] = Field(
        None,
        title="Client Secret (Optional)",
        description="Your OAuth 2.0 Client Secret - leave empty to use NoClick's OAuth app",
        json_schema_extra={"ui:widget": "password", "x-optional-custom": True},
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "twitter",
            "x-oauth-supports-custom-client": True,  # Flag for UI to show custom fields toggle
            "x-oauth-scopes": [
                # Core scopes (available on all tiers)
                "tweet.read",
                "tweet.write",
                "users.read",
                "offline.access",  # Required for refresh tokens
                # Extended scopes (may require Basic tier or higher)
                "like.read",
                "like.write",
                "follows.read",
                "follows.write",
                "bookmark.read",
                "bookmark.write",
                "block.read",
                "block.write",
                "mute.read",
                "mute.write",
                "list.read",
                "list.write",
                # Premium scopes (require elevated access)
                # "dm.read",      # Direct messages - may require premium
                # "dm.write",     # Direct messages - may require premium
                # "space.read",   # Spaces API - requires premium/enterprise
            ],
        }
    )


class TwitterBearerTokenCredential(BaseModel):
    """Bearer Token (App-Only) credential for Twitter/X.
    For read-only access to public data.

    Get your Bearer Token at: https://developer.x.com/en/portal/dashboard
    """

    credential_type: Literal["twitter_bearer_token"] = Field(
        "twitter_bearer_token", json_schema_extra={"ui:hidden": True}
    )
    bearer_token: str = Field(
        ...,
        title="Bearer Token",
        description="Your Twitter/X App Bearer Token for read-only access",
        json_schema_extra={
            "ui:widget": "password",
        },
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://developer.x.com/en/portal/dashboard"
        }
    )


# Union type - OAuth shown first in UI (required for write operations)
TwitterCredential = Union[TwitterOAuthCredential, TwitterBearerTokenCredential]


# ============================================================================
# Tweet Operation Configs
# ============================================================================


class TwitterCreateTweetConfig(BaseModel):
    """Create a new tweet"""

    model_config = ConfigDict(title="Create Tweet", populate_by_name=True)

    operation: Literal["create_tweet"] = Field(
        default="create_tweet",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "Tweet",
            "x-is-trigger": False,
            "x-display-name": "Create Tweet",
            "x-keywords": ["compose tweet", "write a tweet", "post status", "new post"],
        },
        title="Create Tweet",
    )
    text: str = Field(
        ...,
        title="Tweet Text",
        description="The text of the tweet (max 280 characters)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    reply_to_tweet_id: Optional[str] = Field(
        default=None,
        title="Reply To Tweet ID",
        description="ID of the tweet to reply to (optional)",
    )
    quote_tweet_id: Optional[str] = Field(
        default=None,
        title="Quote Tweet ID",
        description="ID of the tweet to quote (optional)",
    )


class TwitterDeleteTweetConfig(BaseModel):
    """Delete a tweet"""

    model_config = ConfigDict(title="Delete Tweet", populate_by_name=True)

    operation: Literal["delete_tweet"] = Field(
        default="delete_tweet",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "Tweet",
            "x-is-trigger": False,
            "x-display-name": "Delete Tweet",
            "x-keywords": ["remove tweet", "take down tweet", "delete post"],
        },
        title="Delete Tweet",
    )
    tweet_id: str = Field(
        ..., title="Tweet ID", description="The ID of the tweet to delete"
    )


class TwitterGetTweetConfig(BaseModel):
    """Get a single tweet by ID"""

    model_config = ConfigDict(
        title="Get Tweet",
        populate_by_name=True,
        json_schema_extra={"x-requires-tier": "basic", "x-tier-label": "⭐"},
    )
    operation: Literal["get_tweet_by_id"] = Field(
        default="get_tweet_by_id",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Tweet",
            "x-is-trigger": False,
            "x-display-name": "Get Tweet by Id",
            "x-keywords": ["single tweet", "tweet details", "one tweet", "tweet by id"],
        },
        title="Get Tweet by Id",
    )
    tweet_id: str = Field(
        ..., title="Tweet ID", description="The ID of the tweet to retrieve"
    )
    tweet_fields: Optional[str] = Field(
        default="created_at,author_id,public_metrics,text",
        title="Tweet Fields",
        description="Comma-separated list of fields (e.g., created_at,author_id,public_metrics)",
    )
    expansions: Optional[str] = Field(
        default="author_id",
        title="Expansions",
        description="Comma-separated list of expansions (e.g., author_id,attachments.media_keys)",
    )


class TwitterGetTweetsConfig(BaseModel):
    """Get multiple tweets by IDs"""

    model_config = ConfigDict(
        title="Get Tweets",
        populate_by_name=True,
        json_schema_extra={"x-requires-tier": "basic", "x-tier-label": "⭐"},
    )
    operation: Literal["get_tweets_by_ids"] = Field(
        default="get_tweets_by_ids",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Tweet",
            "x-is-trigger": False,
            "x-display-name": "Get Tweets by Ids",
            "x-keywords": [
                "multiple tweets",
                "batch tweets",
                "several tweets",
                "tweets by ids",
            ],
        },
        title="Get Tweets by Ids",
    )
    tweet_ids: str = Field(
        ...,
        title="Tweet IDs",
        description="Comma-separated list of tweet IDs (max 100)",
    )
    tweet_fields: Optional[str] = Field(
        default="created_at,author_id,public_metrics,text",
        title="Tweet Fields",
        description="Comma-separated list of fields",
    )
    expansions: Optional[str] = Field(
        default="author_id",
        title="Expansions",
        description="Comma-separated list of expansions",
    )


class TwitterSearchRecentTweetsConfig(BaseModel):
    """Search recent tweets (last 7 days)"""

    model_config = ConfigDict(
        title="Search Recent Tweets",
        populate_by_name=True,
        json_schema_extra={"x-requires-tier": "basic", "x-tier-label": "⭐"},
    )
    operation: Literal["search_recent_tweets"] = Field(
        default="search_recent_tweets",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Tweet",
            "x-is-trigger": False,
            "x-display-name": "Search Recent Tweets",
            "x-keywords": ["recent tweets", "last 7 days", "this week tweets"],
        },
        title="Search Recent Tweets",
    )
    query: str = Field(
        ...,
        title="Search Query",
        description="Search query (e.g., 'from:username' or '#hashtag')",
    )
    max_results: Optional[int] = Field(
        default=10, title="Max Results", description="Number of results (10-100)"
    )
    tweet_fields: Optional[str] = Field(
        default="created_at,author_id,public_metrics,text",
        title="Tweet Fields",
        description="Comma-separated list of fields",
    )
    expansions: Optional[str] = Field(
        default="author_id",
        title="Expansions",
        description="Comma-separated list of expansions",
    )


# ============================================================================
# User Operation Configs
# ============================================================================


class TwitterGetUserConfig(BaseModel):
    """Get a user by ID"""

    model_config = ConfigDict(
        title="Get User",
        populate_by_name=True,
        json_schema_extra={"x-requires-tier": "basic", "x-tier-label": "⭐"},
    )
    operation: Literal["get_user_by_id"] = Field(
        default="get_user_by_id",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get User by Id",
            "x-keywords": ["profile by id", "user details", "account by id"],
        },
        title="Get User by Id",
    )
    user_id: str = Field(..., title="User ID", description="The Twitter user ID")
    user_fields: Optional[str] = Field(
        default="created_at,description,public_metrics,verified",
        title="User Fields",
        description="Comma-separated list of fields",
    )


class TwitterGetUserByUsernameConfig(BaseModel):
    """Get a user by username"""

    model_config = ConfigDict(
        title="Get User By Username",
        populate_by_name=True,
        json_schema_extra={"x-requires-tier": "basic", "x-tier-label": "⭐"},
    )
    operation: Literal["get_user_by_username"] = Field(
        default="get_user_by_username",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get User by Username",
            "x-keywords": [
                "profile by handle",
                "by username",
                "account by handle",
                "by screen name",
            ],
        },
        title="Get User by Username",
    )
    username: str = Field(
        ..., title="Username", description="The Twitter username (without @)"
    )
    user_fields: Optional[str] = Field(
        default="created_at,description,public_metrics,verified",
        title="User Fields",
        description="Comma-separated list of fields",
    )


class TwitterGetMeConfig(BaseModel):
    """Get the authenticated user"""

    model_config = ConfigDict(
        title="Get Me",
        populate_by_name=True,
        json_schema_extra={"x-requires-tier": "basic", "x-tier-label": "⭐"},
    )
    operation: Literal["get_authenticated_user"] = Field(
        default="get_authenticated_user",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get Authenticated User",
            "x-keywords": ["my profile", "current account", "me", "logged in user"],
        },
        title="Get Authenticated User",
    )
    user_fields: Optional[str] = Field(
        default="created_at,description,public_metrics,verified",
        title="User Fields",
        description="Comma-separated list of fields",
    )


class TwitterGetUsersConfig(BaseModel):
    """Get multiple users by IDs"""

    model_config = ConfigDict(
        title="Get Users",
        populate_by_name=True,
        json_schema_extra={"x-requires-tier": "basic", "x-tier-label": "⭐"},
    )
    operation: Literal["get_users_by_ids"] = Field(
        default="get_users_by_ids",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get Users by Ids",
            "x-keywords": [
                "multiple users",
                "batch profiles",
                "several accounts",
                "users by ids",
            ],
        },
        title="Get Users by Ids",
    )
    user_ids: str = Field(
        ..., title="User IDs", description="Comma-separated list of user IDs (max 100)"
    )
    user_fields: Optional[str] = Field(
        default="created_at,description,public_metrics,verified",
        title="User Fields",
        description="Comma-separated list of fields",
    )


# ============================================================================
# Like Operation Configs
# ============================================================================


class TwitterLikeTweetConfig(BaseModel):
    """Like a tweet"""

    model_config = ConfigDict(title="Like Tweet", populate_by_name=True)

    operation: Literal["like_tweet"] = Field(
        default="like_tweet",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "Tweet",
            "x-is-trigger": False,
            "x-display-name": "Like Tweet",
            "x-keywords": ["favorite tweet", "heart tweet"],
        },
        title="Like Tweet",
    )
    tweet_id: str = Field(
        ..., title="Tweet ID", description="The ID of the tweet to like"
    )


class TwitterUnlikeTweetConfig(BaseModel):
    """Unlike a tweet"""

    model_config = ConfigDict(title="Unlike Tweet", populate_by_name=True)

    operation: Literal["unlike_tweet"] = Field(
        default="unlike_tweet",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "Tweet",
            "x-is-trigger": False,
            "x-display-name": "Unlike Tweet",
            "x-keywords": ["unfavorite tweet", "remove like", "unheart tweet"],
        },
        title="Unlike Tweet",
    )
    tweet_id: str = Field(
        ..., title="Tweet ID", description="The ID of the tweet to unlike"
    )


class TwitterGetLikedTweetsConfig(BaseModel):
    """Get tweets liked by a user"""

    model_config = ConfigDict(
        title="Get Liked Tweets",
        populate_by_name=True,
        json_schema_extra={"x-requires-tier": "basic", "x-tier-label": "⭐"},
    )
    operation: Literal["get_user_liked_tweets"] = Field(
        default="get_user_liked_tweets",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Tweet",
            "x-is-trigger": False,
            "x-display-name": "Get User Liked Tweets",
            "x-keywords": ["tweets a user liked", "liked posts", "favorites by user"],
        },
        title="Get User Liked Tweets",
    )
    user_id: str = Field(
        ..., title="User ID", description="The user ID to get liked tweets for"
    )
    max_results: Optional[int] = Field(
        default=10, title="Max Results", description="Number of results (10-100)"
    )
    tweet_fields: Optional[str] = Field(
        default="created_at,author_id,public_metrics,text",
        title="Tweet Fields",
        description="Comma-separated list of fields",
    )


class TwitterGetLikingUsersConfig(BaseModel):
    """Get users who liked a tweet"""

    model_config = ConfigDict(
        title="Get Liking Users",
        populate_by_name=True,
        json_schema_extra={"x-requires-tier": "basic", "x-tier-label": "⭐"},
    )
    operation: Literal["get_users_who_liked_tweet"] = Field(
        default="get_users_who_liked_tweet",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Tweet",
            "x-is-trigger": False,
            "x-display-name": "Get Users Who Liked Tweet",
            "x-keywords": ["likers of tweet", "who liked tweet", "accounts that liked"],
        },
        title="Get Users Who Liked Tweet",
    )
    tweet_id: str = Field(
        ..., title="Tweet ID", description="The tweet ID to get liking users for"
    )
    max_results: Optional[int] = Field(
        default=100, title="Max Results", description="Number of results (1-100)"
    )
    user_fields: Optional[str] = Field(
        default="created_at,description,public_metrics",
        title="User Fields",
        description="Comma-separated list of fields",
    )


# ============================================================================
# Retweet Operation Configs
# ============================================================================


class TwitterRetweetConfig(BaseModel):
    """Retweet a tweet"""

    model_config = ConfigDict(title="Retweet", populate_by_name=True)

    operation: Literal["retweet_tweet"] = Field(
        default="retweet_tweet",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "Tweet",
            "x-is-trigger": False,
            "x-display-name": "Retweet Tweet",
            "x-keywords": ["reshare tweet", "repost tweet", "boost tweet"],
        },
        title="Retweet Tweet",
    )
    tweet_id: str = Field(
        ..., title="Tweet ID", description="The ID of the tweet to retweet"
    )


class TwitterUndoRetweetConfig(BaseModel):
    """Undo a retweet"""

    model_config = ConfigDict(title="Undo Retweet", populate_by_name=True)

    operation: Literal["undo_retweet"] = Field(
        default="undo_retweet",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "Tweet",
            "x-is-trigger": False,
            "x-display-name": "Undo Retweet",
            "x-keywords": ["unretweet", "remove retweet", "cancel reshare"],
        },
        title="Undo Retweet",
    )
    tweet_id: str = Field(
        ..., title="Tweet ID", description="The ID of the tweet to undo retweet"
    )


class TwitterGetRetweetersConfig(BaseModel):
    """Get users who retweeted a tweet"""

    model_config = ConfigDict(
        title="Get Retweeters",
        populate_by_name=True,
        json_schema_extra={"x-requires-tier": "basic", "x-tier-label": "⭐"},
    )
    operation: Literal["get_tweet_retweeters"] = Field(
        default="get_tweet_retweeters",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Tweet",
            "x-is-trigger": False,
            "x-display-name": "Get Tweet Retweeters",
            "x-keywords": [
                "who retweeted tweet",
                "retweeters list",
                "accounts that retweeted",
            ],
        },
        title="Get Tweet Retweeters",
    )
    tweet_id: str = Field(
        ..., title="Tweet ID", description="The tweet ID to get retweeters for"
    )
    max_results: Optional[int] = Field(
        default=100, title="Max Results", description="Number of results (1-100)"
    )
    user_fields: Optional[str] = Field(
        default="created_at,description,public_metrics",
        title="User Fields",
        description="Comma-separated list of fields",
    )


# ============================================================================
# Follow Operation Configs
# ============================================================================


class TwitterFollowUserConfig(BaseModel):
    """Follow a user"""

    model_config = ConfigDict(title="Follow User", populate_by_name=True)

    operation: Literal["follow_user"] = Field(
        default="follow_user",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Follow User",
            "x-keywords": ["start following", "add follow"],
        },
        title="Follow User",
    )
    target_user_id: str = Field(
        ..., title="Target User ID", description="The ID of the user to follow"
    )


class TwitterUnfollowUserConfig(BaseModel):
    """Unfollow a user"""

    model_config = ConfigDict(title="Unfollow User", populate_by_name=True)

    operation: Literal["unfollow_user"] = Field(
        default="unfollow_user",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Unfollow User",
            "x-keywords": ["stop following", "remove follow"],
        },
        title="Unfollow User",
    )
    target_user_id: str = Field(
        ..., title="Target User ID", description="The ID of the user to unfollow"
    )


class TwitterGetFollowersConfig(BaseModel):
    """Get followers of a user"""

    model_config = ConfigDict(
        title="Get Followers",
        populate_by_name=True,
        json_schema_extra={"x-requires-tier": "basic", "x-tier-label": "⭐"},
    )
    operation: Literal["get_user_followers"] = Field(
        default="get_user_followers",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get User Followers",
            "x-keywords": ["followers of user", "who follows", "follower list"],
        },
        title="Get User Followers",
    )
    user_id: str = Field(
        ..., title="User ID", description="The user ID to get followers for"
    )
    max_results: Optional[int] = Field(
        default=100, title="Max Results", description="Number of results (1-1000)"
    )
    user_fields: Optional[str] = Field(
        default="created_at,description,public_metrics",
        title="User Fields",
        description="Comma-separated list of fields",
    )


class TwitterGetFollowingConfig(BaseModel):
    """Get users followed by a user"""

    model_config = ConfigDict(
        title="Get Following",
        populate_by_name=True,
        json_schema_extra={"x-requires-tier": "basic", "x-tier-label": "⭐"},
    )
    operation: Literal["get_users_followed_by_user"] = Field(
        default="get_users_followed_by_user",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get Users Followed by User",
            "x-keywords": [
                "following list",
                "accounts followed",
                "who user follows",
                "friends list",
            ],
        },
        title="Get Users Followed by User",
    )
    user_id: str = Field(
        ..., title="User ID", description="The user ID to get following for"
    )
    max_results: Optional[int] = Field(
        default=100, title="Max Results", description="Number of results (1-1000)"
    )
    user_fields: Optional[str] = Field(
        default="created_at,description,public_metrics",
        title="User Fields",
        description="Comma-separated list of fields",
    )


# ============================================================================
# Block Operation Configs
# ============================================================================


class TwitterBlockUserConfig(BaseModel):
    """Block a user"""

    model_config = ConfigDict(title="Block User", populate_by_name=True)

    operation: Literal["block_user"] = Field(
        default="block_user",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "Block",
            "x-is-trigger": False,
            "x-display-name": "Block User",
            "x-keywords": ["block account", "blacklist user"],
        },
        title="Block User",
    )
    target_user_id: str = Field(
        ..., title="Target User ID", description="The ID of the user to block"
    )


class TwitterUnblockUserConfig(BaseModel):
    """Unblock a user"""

    model_config = ConfigDict(title="Unblock User", populate_by_name=True)

    operation: Literal["unblock_user"] = Field(
        default="unblock_user",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "Block",
            "x-is-trigger": False,
            "x-display-name": "Unblock User",
            "x-keywords": ["unblock account", "remove block", "lift block"],
        },
        title="Unblock User",
    )
    target_user_id: str = Field(
        ..., title="Target User ID", description="The ID of the user to unblock"
    )


class TwitterGetBlockedUsersConfig(BaseModel):
    """Get blocked users"""

    model_config = ConfigDict(
        title="Get Blocked Users",
        populate_by_name=True,
        json_schema_extra={"x-requires-tier": "basic", "x-tier-label": "⭐"},
    )
    operation: Literal["get_blocked_users"] = Field(
        default="get_blocked_users",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "Block",
            "x-is-trigger": False,
            "x-display-name": "Get Blocked Users",
            "x-keywords": ["block list", "blocked accounts", "who i blocked"],
        },
        title="Get Blocked Users",
    )
    max_results: Optional[int] = Field(
        default=100, title="Max Results", description="Number of results (1-1000)"
    )
    user_fields: Optional[str] = Field(
        default="created_at,description,public_metrics",
        title="User Fields",
        description="Comma-separated list of fields",
    )


# ============================================================================
# Mute Operation Configs
# ============================================================================


class TwitterMuteUserConfig(BaseModel):
    """Mute a user"""

    model_config = ConfigDict(title="Mute User", populate_by_name=True)

    operation: Literal["mute_user"] = Field(
        default="mute_user",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "Mute",
            "x-is-trigger": False,
            "x-display-name": "Mute User",
            "x-keywords": ["mute account", "silence user"],
        },
        title="Mute User",
    )
    target_user_id: str = Field(
        ..., title="Target User ID", description="The ID of the user to mute"
    )


class TwitterUnmuteUserConfig(BaseModel):
    """Unmute a user"""

    model_config = ConfigDict(title="Unmute User", populate_by_name=True)

    operation: Literal["unmute_user"] = Field(
        default="unmute_user",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "Mute",
            "x-is-trigger": False,
            "x-display-name": "Unmute User",
            "x-keywords": ["unmute account", "remove mute", "unsilence user"],
        },
        title="Unmute User",
    )
    target_user_id: str = Field(
        ..., title="Target User ID", description="The ID of the user to unmute"
    )


class TwitterGetMutedUsersConfig(BaseModel):
    """Get muted users"""

    model_config = ConfigDict(
        title="Get Muted Users",
        populate_by_name=True,
        json_schema_extra={"x-requires-tier": "basic", "x-tier-label": "⭐"},
    )
    operation: Literal["get_muted_users"] = Field(
        default="get_muted_users",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "Mute",
            "x-is-trigger": False,
            "x-display-name": "Get Muted Users",
            "x-keywords": ["mute list", "muted accounts", "who i muted"],
        },
        title="Get Muted Users",
    )
    max_results: Optional[int] = Field(
        default=100, title="Max Results", description="Number of results (1-1000)"
    )
    user_fields: Optional[str] = Field(
        default="created_at,description,public_metrics",
        title="User Fields",
        description="Comma-separated list of fields",
    )


# ============================================================================
# Bookmark Operation Configs
# ============================================================================


class TwitterAddBookmarkConfig(BaseModel):
    """Add a tweet to bookmarks"""

    model_config = ConfigDict(title="Add Bookmark", populate_by_name=True)

    operation: Literal["add_tweet_to_bookmarks"] = Field(
        default="add_tweet_to_bookmarks",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "Tweet",
            "x-is-trigger": False,
            "x-display-name": "Add Tweet to Bookmarks",
            "x-keywords": ["bookmark tweet", "save tweet", "add bookmark"],
        },
        title="Add Tweet to Bookmarks",
    )
    tweet_id: str = Field(
        ..., title="Tweet ID", description="The ID of the tweet to bookmark"
    )


class TwitterRemoveBookmarkConfig(BaseModel):
    """Remove a tweet from bookmarks"""

    model_config = ConfigDict(title="Remove Bookmark", populate_by_name=True)

    operation: Literal["remove_tweet_from_bookmarks"] = Field(
        default="remove_tweet_from_bookmarks",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "Tweet",
            "x-is-trigger": False,
            "x-display-name": "Remove Tweet from Bookmarks",
            "x-keywords": ["unbookmark tweet", "remove bookmark", "unsave tweet"],
        },
        title="Remove Tweet from Bookmarks",
    )
    tweet_id: str = Field(
        ...,
        title="Tweet ID",
        description="The ID of the tweet to remove from bookmarks",
    )


class TwitterGetBookmarksConfig(BaseModel):
    """Get bookmarked tweets"""

    model_config = ConfigDict(
        title="Get Bookmarks",
        populate_by_name=True,
        json_schema_extra={"x-requires-tier": "basic", "x-tier-label": "⭐"},
    )
    operation: Literal["get_bookmarked_tweets"] = Field(
        default="get_bookmarked_tweets",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "Tweet",
            "x-is-trigger": False,
            "x-display-name": "Get Bookmarked Tweets",
            "x-keywords": [
                "my bookmarks",
                "saved tweets",
                "bookmarked posts",
                "tweets i saved",
            ],
        },
        title="Get Bookmarked Tweets",
    )
    max_results: Optional[int] = Field(
        default=10, title="Max Results", description="Number of results (10-100)"
    )
    tweet_fields: Optional[str] = Field(
        default="created_at,author_id,public_metrics,text",
        title="Tweet Fields",
        description="Comma-separated list of fields",
    )


# ============================================================================
# Direct Message Operation Configs
# ============================================================================


class TwitterCreateDMConversationConfig(BaseModel):
    """Create a group Direct Message conversation"""

    model_config = ConfigDict(
        title="Create DM Conversation",
        populate_by_name=True,
        json_schema_extra={"x-requires-tier": "pro", "x-tier-label": "⭐⭐"},
    )
    operation: Literal["create_group_direct_message_conversation"] = Field(
        default="create_group_direct_message_conversation",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "Direct Message",
            "x-is-trigger": False,
            "x-display-name": "Create Group Direct Message Conversation",
            "x-keywords": [
                "group dm",
                "start group chat",
                "new group conversation",
                "group message thread",
            ],
        },
        title="Create Group Direct Message Conversation",
    )
    participant_ids: str = Field(
        ...,
        title="Participant User IDs",
        description="Comma-separated list of user IDs to include in conversation",
    )
    message_text: str = Field(
        ...,
        title="Message Text",
        description="The text of the first message",
        json_schema_extra={"ui:widget": "textarea"},
    )


class TwitterSendDMConfig(BaseModel):
    """Send a one-to-one Direct Message"""

    model_config = ConfigDict(
        title="Send DM",
        populate_by_name=True,
        json_schema_extra={"x-requires-tier": "pro", "x-tier-label": "⭐⭐"},
    )
    operation: Literal["send_direct_message"] = Field(
        default="send_direct_message",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "Direct Message",
            "x-is-trigger": False,
            "x-display-name": "Send Direct Message",
            "x-keywords": [
                "dm a user",
                "private message",
                "direct message user",
                "message someone",
            ],
        },
        title="Send Direct Message",
    )
    participant_id: str = Field(
        ..., title="Recipient User ID", description="The user ID to send the message to"
    )
    message_text: str = Field(
        ...,
        title="Message Text",
        description="The text of the message",
        json_schema_extra={"ui:widget": "textarea"},
    )


class TwitterSendDMToConversationConfig(BaseModel):
    """Send a message to an existing conversation"""

    model_config = ConfigDict(
        title="Send DM To Conversation",
        populate_by_name=True,
        json_schema_extra={"x-requires-tier": "pro", "x-tier-label": "⭐⭐"},
    )
    operation: Literal["send_direct_message_to_conversation"] = Field(
        default="send_direct_message_to_conversation",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "Direct Message",
            "x-is-trigger": False,
            "x-display-name": "Send Direct Message to Conversation",
            "x-keywords": [
                "reply dm thread",
                "message existing conversation",
                "dm to conversation",
                "send to thread",
            ],
        },
        title="Send Direct Message to Conversation",
    )
    conversation_id: str = Field(
        ..., title="Conversation ID", description="The DM conversation ID"
    )
    message_text: str = Field(
        ...,
        title="Message Text",
        description="The text of the message",
        json_schema_extra={"ui:widget": "textarea"},
    )


class TwitterGetDMConversationConfig(BaseModel):
    """Get DM conversation events with a specific user"""

    model_config = ConfigDict(
        title="Get DM Conversation",
        populate_by_name=True,
        json_schema_extra={"x-requires-tier": "pro", "x-tier-label": "⭐⭐"},
    )
    operation: Literal["get_direct_message_conversation_with_user"] = Field(
        default="get_direct_message_conversation_with_user",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "Direct Message",
            "x-is-trigger": False,
            "x-display-name": "Get Direct Message Conversation with User",
            "x-keywords": [
                "dm history user",
                "conversation with person",
                "messages with someone",
                "chat with user",
            ],
        },
        title="Get Direct Message Conversation with User",
    )
    participant_id: str = Field(
        ...,
        title="Participant User ID",
        description="The user ID of the conversation participant",
    )
    max_results: Optional[int] = Field(
        default=100, title="Max Results", description="Number of results (1-100)"
    )


class TwitterGetDMEventsConfig(BaseModel):
    """Get DM events for a specific conversation ID"""

    model_config = ConfigDict(
        title="Get DM Events",
        populate_by_name=True,
        json_schema_extra={"x-requires-tier": "pro", "x-tier-label": "⭐⭐"},
    )
    operation: Literal["get_direct_message_events_for_conversation"] = Field(
        default="get_direct_message_events_for_conversation",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "Direct Message",
            "x-is-trigger": False,
            "x-display-name": "Get Direct Message Events for Conversation",
            "x-keywords": [
                "dm thread events",
                "conversation messages",
                "events for thread",
                "messages by conversation",
            ],
        },
        title="Get Direct Message Events for Conversation",
    )
    conversation_id: str = Field(
        ..., title="Conversation ID", description="The DM conversation ID"
    )
    max_results: Optional[int] = Field(
        default=100, title="Max Results", description="Number of results (1-100)"
    )


class TwitterGetAllDMEventsConfig(BaseModel):
    """Get all DM events for the authenticated user"""

    model_config = ConfigDict(
        title="Get All DM Events",
        populate_by_name=True,
        json_schema_extra={"x-requires-tier": "pro", "x-tier-label": "⭐⭐"},
    )
    operation: Literal["get_all_direct_message_events"] = Field(
        default="get_all_direct_message_events",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "Direct Message",
            "x-is-trigger": False,
            "x-display-name": "Get All Direct Message Events",
            "x-keywords": [
                "all my dms",
                "every direct message",
                "full dm history",
                "inbox messages",
            ],
        },
        title="Get All Direct Message Events",
    )
    max_results: Optional[int] = Field(
        default=100, title="Max Results", description="Number of results (1-100)"
    )
    dm_event_fields: Optional[str] = Field(
        default="id,text,created_at,sender_id,participant_ids",
        title="DM Event Fields",
        description="Comma-separated list of fields",
    )


# ============================================================================
# List Operation Configs
# ============================================================================


class TwitterCreateListConfig(BaseModel):
    """Create a new list"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_list"] = Field(
        default="create_list",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "List",
            "x-is-trigger": False,
            "x-display-name": "Create List",
            "x-keywords": ["make a list", "new twitter list", "start a list"],
        },
        title="Create List",
    )
    name: str = Field(..., title="List Name", description="The name of the list")
    description: Optional[str] = Field(
        default=None,
        title="Description",
        description="Description of the list (optional)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    private: Optional[bool] = Field(
        default=False, title="Private", description="Whether the list is private"
    )


class TwitterDeleteListConfig(BaseModel):
    """Delete a list"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_list"] = Field(
        default="delete_list",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "List",
            "x-is-trigger": False,
            "x-display-name": "Delete List",
            "x-keywords": ["remove a list", "delete twitter list", "erase list"],
        },
        title="Delete List",
    )
    list_id: str = Field(
        ..., title="List ID", description="The ID of the list to delete"
    )


class TwitterUpdateListConfig(BaseModel):
    """Update list metadata"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["update_list_metadata"] = Field(
        default="update_list_metadata",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "List",
            "x-is-trigger": False,
            "x-display-name": "Update List Metadata",
            "x-keywords": [
                "rename list",
                "edit list details",
                "change list name",
                "list description",
            ],
        },
        title="Update List Metadata",
    )
    list_id: str = Field(
        ..., title="List ID", description="The ID of the list to update"
    )
    name: Optional[str] = Field(
        default=None, title="List Name", description="New name for the list (optional)"
    )
    description: Optional[str] = Field(
        default=None,
        title="Description",
        description="New description (optional)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    private: Optional[bool] = Field(
        default=None,
        title="Private",
        description="Whether the list is private (optional)",
    )


class TwitterGetListConfig(BaseModel):
    """Get a list by ID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_list_by_id"] = Field(
        default="get_list_by_id",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "List",
            "x-is-trigger": False,
            "x-display-name": "Get List by Id",
            "x-keywords": ["single list", "list details", "one list", "fetch a list"],
        },
        title="Get List by Id",
    )
    list_id: str = Field(..., title="List ID", description="The ID of the list")
    list_fields: Optional[str] = Field(
        default="name,description,member_count,follower_count,private",
        title="List Fields",
        description="Comma-separated list of fields",
    )


class TwitterGetUserOwnedListsConfig(BaseModel):
    """Get lists owned by a user"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_user_owned_lists"] = Field(
        default="get_user_owned_lists",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "List",
            "x-is-trigger": False,
            "x-display-name": "Get User Owned Lists",
            "x-keywords": [
                "lists user owns",
                "owned lists",
                "lists created by",
                "my lists",
            ],
        },
        title="Get User Owned Lists",
    )
    user_id: str = Field(..., title="User ID", description="The user ID")
    max_results: Optional[int] = Field(
        default=100, title="Max Results", description="Number of results (1-100)"
    )


class TwitterGetUserListMembershipsConfig(BaseModel):
    """Get lists a user is a member of"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_user_list_memberships"] = Field(
        default="get_user_list_memberships",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "List",
            "x-is-trigger": False,
            "x-display-name": "Get User List Memberships",
            "x-keywords": [
                "list memberships",
                "lists containing user",
                "member of lists",
                "user belongs to",
            ],
        },
        title="Get User List Memberships",
    )
    user_id: str = Field(..., title="User ID", description="The user ID")
    max_results: Optional[int] = Field(
        default=100, title="Max Results", description="Number of results (1-100)"
    )


class TwitterGetListTweetsConfig(BaseModel):
    """Get tweets from a list"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_tweets_from_list"] = Field(
        default="get_tweets_from_list",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "List",
            "x-is-trigger": False,
            "x-display-name": "Get Tweets from List",
            "x-keywords": [
                "list timeline",
                "tweets in list",
                "posts from list",
                "list feed",
            ],
        },
        title="Get Tweets from List",
    )
    list_id: str = Field(..., title="List ID", description="The ID of the list")
    max_results: Optional[int] = Field(
        default=100, title="Max Results", description="Number of results (10-100)"
    )
    tweet_fields: Optional[str] = Field(
        default="created_at,author_id,public_metrics,text",
        title="Tweet Fields",
        description="Comma-separated list of fields",
    )


class TwitterAddListMemberConfig(BaseModel):
    """Add a member to a list"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["add_member_to_list"] = Field(
        default="add_member_to_list",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "List",
            "x-is-trigger": False,
            "x-display-name": "Add Member to List",
            "x-keywords": ["add to list", "put in list", "include member"],
        },
        title="Add Member to List",
    )
    list_id: str = Field(..., title="List ID", description="The ID of the list")
    user_id: str = Field(..., title="User ID", description="The ID of the user to add")


class TwitterRemoveListMemberConfig(BaseModel):
    """Remove a member from a list"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["remove_member_from_list"] = Field(
        default="remove_member_from_list",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "List",
            "x-is-trigger": False,
            "x-display-name": "Remove Member from List",
            "x-keywords": ["remove from list", "drop member", "take off list"],
        },
        title="Remove Member from List",
    )
    list_id: str = Field(..., title="List ID", description="The ID of the list")
    user_id: str = Field(
        ..., title="User ID", description="The ID of the user to remove"
    )


class TwitterGetListMembersConfig(BaseModel):
    """Get members of a list"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_list_members"] = Field(
        default="get_list_members",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "List",
            "x-is-trigger": False,
            "x-display-name": "Get List Members",
            "x-keywords": [
                "who in list",
                "list members",
                "people in list",
                "members of list",
            ],
        },
        title="Get List Members",
    )
    list_id: str = Field(..., title="List ID", description="The ID of the list")
    max_results: Optional[int] = Field(
        default=100, title="Max Results", description="Number of results (1-100)"
    )


class TwitterPinListConfig(BaseModel):
    """Pin a list"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["pin_list"] = Field(
        default="pin_list",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "List",
            "x-is-trigger": False,
            "x-display-name": "Pin List",
            "x-keywords": ["pin a list", "pin to top", "favorite list"],
        },
        title="Pin List",
    )
    list_id: str = Field(..., title="List ID", description="The ID of the list to pin")


class TwitterUnpinListConfig(BaseModel):
    """Unpin a list"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["unpin_list"] = Field(
        default="unpin_list",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "List",
            "x-is-trigger": False,
            "x-display-name": "Unpin List",
            "x-keywords": ["unpin a list", "remove pinned list", "unpin from top"],
        },
        title="Unpin List",
    )
    list_id: str = Field(
        ..., title="List ID", description="The ID of the list to unpin"
    )


class TwitterGetPinnedListsConfig(BaseModel):
    """Get pinned lists"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_user_pinned_lists"] = Field(
        default="get_user_pinned_lists",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "List",
            "x-is-trigger": False,
            "x-display-name": "Get User Pinned Lists",
            "x-keywords": ["my pinned lists", "pinned lists", "lists i pinned"],
        },
        title="Get User Pinned Lists",
    )
    user_id: str = Field(..., title="User ID", description="The user ID")


# ============================================================================
# Space Operation Configs
# ============================================================================


class TwitterGetSpaceConfig(BaseModel):
    """Get a Space by ID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_space_by_id"] = Field(
        default="get_space_by_id",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Space",
            "x-is-trigger": False,
            "x-display-name": "Get Space by Id",
            "x-keywords": ["single space", "space details", "audio room", "one space"],
        },
        title="Get Space by Id",
    )
    space_id: str = Field(..., title="Space ID", description="The ID of the Space")
    space_fields: Optional[str] = Field(
        default="host_ids,created_at,creator_id,id,lang,is_ticketed,participant_count,scheduled_start,speaker_ids,started_at,state,title,updated_at",
        title="Space Fields",
        description="Comma-separated list of fields",
    )


class TwitterGetSpacesConfig(BaseModel):
    """Get multiple Spaces by IDs"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_spaces_by_ids"] = Field(
        default="get_spaces_by_ids",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Space",
            "x-is-trigger": False,
            "x-display-name": "Get Spaces by Ids",
            "x-keywords": [
                "multiple spaces",
                "batch spaces",
                "several audio rooms",
                "bulk spaces",
            ],
        },
        title="Get Spaces by Ids",
    )
    space_ids: str = Field(
        ...,
        title="Space IDs",
        description="Comma-separated list of Space IDs (max 100)",
    )
    space_fields: Optional[str] = Field(
        default="host_ids,created_at,creator_id,id,lang,is_ticketed,participant_count,scheduled_start,speaker_ids,started_at,state,title",
        title="Space Fields",
        description="Comma-separated list of fields",
    )


class TwitterGetSpacesByCreatorsConfig(BaseModel):
    """Get Spaces by creator user IDs"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_spaces_by_creator_user_ids"] = Field(
        default="get_spaces_by_creator_user_ids",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Space",
            "x-is-trigger": False,
            "x-display-name": "Get Spaces by Creator User Ids",
            "x-keywords": [
                "spaces by host",
                "spaces created by",
                "host audio rooms",
                "creator spaces",
            ],
        },
        title="Get Spaces by Creator User Ids",
    )
    user_ids: str = Field(
        ..., title="User IDs", description="Comma-separated list of user IDs (max 100)"
    )
    space_fields: Optional[str] = Field(
        default="host_ids,created_at,creator_id,id,state,title",
        title="Space Fields",
        description="Comma-separated list of fields",
    )


# ============================================================================
# Media Upload Operation Configs
# ============================================================================


class TwitterUploadMediaConfig(BaseModel):
    """Upload media (simple upload for small files)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["upload_media"] = Field(
        default="upload_media",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "Tweet",
            "x-is-trigger": False,
            "x-display-name": "Upload Media",
            "x-keywords": [
                "attach image",
                "upload photo",
                "add media",
                "simple upload",
            ],
        },
        title="Upload Media",
    )
    media_data: str = Field(
        ...,
        title="Media",
        description="The media to upload — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}).",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": "image/*,video/*"},
    )
    media_type: str = Field(
        ..., title="Media Type", description="MIME type (e.g., image/jpeg, video/mp4)"
    )


class TwitterUploadMediaChunkedConfig(BaseModel):
    """Upload large media using chunked upload"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["upload_media_chunked"] = Field(
        default="upload_media_chunked",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "Tweet",
            "x-is-trigger": False,
            "x-display-name": "Upload Media Chunked",
            "x-keywords": ["large upload", "chunked upload", "big video upload"],
        },
        title="Upload Media Chunked",
    )
    media_data: str = Field(
        ...,
        title="Media",
        description="The media to upload — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}).",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": "image/*,video/*"},
    )
    media_type: str = Field(
        ..., title="Media Type", description="MIME type (e.g., image/jpeg, video/mp4)"
    )
    media_category: Optional[str] = Field(
        default="tweet_image",
        title="Media Category",
        description="Category: tweet_image, tweet_video, tweet_gif",
    )


# ============================================================================
# Timeline Operation Configs
# ============================================================================


class TwitterGetUserTweetsConfig(BaseModel):
    """Get tweets posted by a user"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_tweets_posted_by_user"] = Field(
        default="get_tweets_posted_by_user",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Tweet",
            "x-is-trigger": False,
            "x-display-name": "Get Tweets Posted by User",
            "x-keywords": ["user tweets", "someones tweets", "posts by user"],
        },
        title="Get Tweets Posted by User",
    )
    user_id: str = Field(..., title="User ID", description="The user ID")
    max_results: Optional[int] = Field(
        default=10, title="Max Results", description="Number of results (5-100)"
    )
    tweet_fields: Optional[str] = Field(
        default="created_at,author_id,public_metrics,text",
        title="Tweet Fields",
        description="Comma-separated list of fields",
    )
    exclude: Optional[str] = Field(
        default=None,
        title="Exclude",
        description="Comma-separated types to exclude (e.g., retweets,replies)",
    )


class TwitterGetUserMentionsConfig(BaseModel):
    """Get tweets mentioning a user"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_tweets_mentioning_user"] = Field(
        default="get_tweets_mentioning_user",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Tweet",
            "x-is-trigger": False,
            "x-display-name": "Get Tweets Mentioning User",
            "x-keywords": ["mentions", "user mentions", "tweets mentioning"],
        },
        title="Get Tweets Mentioning User",
    )
    user_id: str = Field(..., title="User ID", description="The user ID")
    max_results: Optional[int] = Field(
        default=10, title="Max Results", description="Number of results (5-100)"
    )
    tweet_fields: Optional[str] = Field(
        default="created_at,author_id,public_metrics,text",
        title="Tweet Fields",
        description="Comma-separated list of fields",
    )


class TwitterGetHomeTimelineConfig(BaseModel):
    """Get reverse chronological home timeline"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_home_timeline"] = Field(
        default="get_home_timeline",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "Timeline",
            "x-is-trigger": False,
            "x-display-name": "Get Home Timeline",
            "x-keywords": [
                "home feed",
                "my timeline",
                "following feed",
                "for you feed",
            ],
        },
        title="Get Home Timeline",
    )
    max_results: Optional[int] = Field(
        default=10, title="Max Results", description="Number of results (5-100)"
    )
    tweet_fields: Optional[str] = Field(
        default="created_at,author_id,public_metrics,text",
        title="Tweet Fields",
        description="Comma-separated list of fields",
    )


# ============================================================================
# Quote Tweet Operation Configs
# ============================================================================


class TwitterGetQuoteTweetsConfig(BaseModel):
    """Get tweets that quote a specific tweet"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_tweets_quoting_tweet"] = Field(
        default="get_tweets_quoting_tweet",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Tweet",
            "x-is-trigger": False,
            "x-display-name": "Get Tweets Quoting Tweet",
            "x-keywords": ["quote tweets", "quotes of tweet", "who quoted"],
        },
        title="Get Tweets Quoting Tweet",
    )
    tweet_id: str = Field(
        ..., title="Tweet ID", description="The ID of the tweet to get quotes for"
    )
    max_results: Optional[int] = Field(
        default=10, title="Max Results", description="Number of results (10-100)"
    )
    tweet_fields: Optional[str] = Field(
        default="created_at,author_id,public_metrics,text",
        title="Tweet Fields",
        description="Comma-separated list of fields",
    )


# ============================================================================
# Hide Reply Operation Configs
# ============================================================================


class TwitterHideReplyConfig(BaseModel):
    """Hide a reply to a tweet"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["hide_reply_to_tweet"] = Field(
        default="hide_reply_to_tweet",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "Tweet",
            "x-is-trigger": False,
            "x-display-name": "Hide Reply to Tweet",
            "x-keywords": ["hide reply", "moderate reply"],
        },
        title="Hide Reply to Tweet",
    )
    tweet_id: str = Field(
        ..., title="Tweet ID", description="The ID of the reply tweet to hide"
    )


class TwitterUnhideReplyConfig(BaseModel):
    """Unhide a reply to a tweet"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["unhide_reply_to_tweet"] = Field(
        default="unhide_reply_to_tweet",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "Tweet",
            "x-is-trigger": False,
            "x-display-name": "Unhide Reply to Tweet",
            "x-keywords": ["unhide reply", "restore reply", "show reply"],
        },
        title="Unhide Reply to Tweet",
    )
    tweet_id: str = Field(
        ..., title="Tweet ID", description="The ID of the reply tweet to unhide"
    )


# ============================================================================
# Additional Tweet Operation Configs
# ============================================================================


class TwitterSearchAllTweetsConfig(BaseModel):
    """Search all tweets (full archive, Enterprise)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["search_all_tweets_full_archive"] = Field(
        default="search_all_tweets_full_archive",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Tweet",
            "x-is-trigger": False,
            "x-display-name": "Search All Tweets Full Archive",
            "x-keywords": [
                "full archive search",
                "historical tweets",
                "all time tweets",
                "enterprise tweet search",
            ],
        },
        title="Search All Tweets Full Archive",
    )
    query: str = Field(
        ..., title="Search Query", description="Search query for full archive"
    )
    max_results: Optional[int] = Field(
        default=10, title="Max Results", description="Number of results (10-500)"
    )
    tweet_fields: Optional[str] = Field(
        default=None, title="Tweet Fields", description="Comma-separated list of fields"
    )
    expansions: Optional[str] = Field(
        default=None,
        title="Expansions",
        description="Comma-separated list of expansions",
    )
    start_time: Optional[str] = Field(
        default=None,
        title="Start Time",
        description="ISO 8601 start time (e.g. 2020-01-01T00:00:00Z)",
    )
    end_time: Optional[str] = Field(
        default=None, title="End Time", description="ISO 8601 end time"
    )


class TwitterGetTweetCountsRecentConfig(BaseModel):
    """Get tweet counts for recent tweets (last 7 days)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_tweet_counts_recent"] = Field(
        default="get_tweet_counts_recent",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Tweet Analytics",
            "x-is-trigger": False,
            "x-display-name": "Get Tweet Counts Recent",
            "x-keywords": [
                "recent tweet volume",
                "count recent tweets",
                "tweet count week",
                "tweet frequency recent",
            ],
        },
        title="Get Tweet Counts Recent",
    )
    query: str = Field(
        ..., title="Search Query", description="Search query to count tweets for"
    )
    granularity: Optional[str] = Field(
        default="day",
        title="Granularity",
        description="Time granularity",
        json_schema_extra={
            "enum": ["day", "hour", "minute"],
            "x-enum-searchable": True,
        },
    )
    start_time: Optional[str] = Field(
        default=None, title="Start Time", description="ISO 8601 start time"
    )
    end_time: Optional[str] = Field(
        default=None, title="End Time", description="ISO 8601 end time"
    )


class TwitterGetTweetCountsAllConfig(BaseModel):
    """Get tweet counts for full archive (Enterprise only)"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_tweet_counts_full_archive"] = Field(
        default="get_tweet_counts_full_archive",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Tweet Analytics",
            "x-is-trigger": False,
            "x-display-name": "Get Tweet Counts Full Archive",
            "x-keywords": [
                "full archive count",
                "historical tweet volume",
                "count all tweets",
                "tweet count archive",
            ],
        },
        title="Get Tweet Counts Full Archive",
    )
    query: str = Field(
        ..., title="Search Query", description="Search query to count tweets for"
    )
    granularity: Optional[str] = Field(
        default="day",
        title="Granularity",
        description="Time granularity",
        json_schema_extra={
            "enum": ["day", "hour", "minute"],
            "x-enum-searchable": True,
        },
    )
    start_time: Optional[str] = Field(
        default=None, title="Start Time", description="ISO 8601 start time"
    )
    end_time: Optional[str] = Field(
        default=None, title="End Time", description="ISO 8601 end time"
    )


class TwitterGetTweetAnalyticsConfig(BaseModel):
    """Get analytics for tweets"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_tweet_analytics"] = Field(
        default="get_tweet_analytics",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "Tweet Analytics",
            "x-is-trigger": False,
            "x-display-name": "Get Tweet Analytics",
            "x-keywords": [
                "tweet metrics",
                "tweet impressions",
                "tweet engagement",
                "tweet performance",
            ],
        },
        title="Get Tweet Analytics",
    )
    tweet_ids: str = Field(
        ..., title="Tweet IDs", description="Comma-separated list of tweet IDs"
    )
    start_time: Optional[str] = Field(
        default=None, title="Start Time", description="ISO 8601 start time"
    )
    end_time: Optional[str] = Field(
        default=None, title="End Time", description="ISO 8601 end time"
    )


class TwitterGetRetweetsConfig(BaseModel):
    """Get retweets of a tweet"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_tweet_retweets"] = Field(
        default="get_tweet_retweets",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Tweet",
            "x-is-trigger": False,
            "x-display-name": "Get Tweet Retweets",
            "x-keywords": ["retweets of tweet", "who retweeted", "tweet reshares"],
        },
        title="Get Tweet Retweets",
    )
    tweet_id: str = Field(
        ..., title="Tweet ID", description="The ID of the tweet to get retweets for"
    )
    max_results: Optional[int] = Field(
        default=10, title="Max Results", description="Number of results (1-100)"
    )
    tweet_fields: Optional[str] = Field(
        default=None, title="Tweet Fields", description="Comma-separated list of fields"
    )


# ============================================================================
# Additional User Operation Configs
# ============================================================================


class TwitterGetUsersByUsernamesConfig(BaseModel):
    """Get multiple users by usernames"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_users_by_usernames"] = Field(
        default="get_users_by_usernames",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get Users by Usernames",
            "x-keywords": [
                "multiple handles",
                "batch usernames",
                "accounts by handle",
                "users by usernames",
            ],
        },
        title="Get Users by Usernames",
    )
    usernames: str = Field(
        ...,
        title="Usernames",
        description="Comma-separated list of usernames (without @)",
    )
    user_fields: Optional[str] = Field(
        default=None, title="User Fields", description="Comma-separated list of fields"
    )


class TwitterSearchUsersConfig(BaseModel):
    """Search for users"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["search_users"] = Field(
        default="search_users",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Search Users",
            "x-keywords": ["find people", "find accounts", "discover profiles"],
        },
        title="Search Users",
    )
    query: str = Field(..., title="Search Query", description="User search query")
    max_results: Optional[int] = Field(
        default=10, title="Max Results", description="Number of results (1-100)"
    )
    user_fields: Optional[str] = Field(
        default=None, title="User Fields", description="Comma-separated list of fields"
    )


# ============================================================================
# Additional DM Operation Configs
# ============================================================================


class TwitterDeleteDMEventConfig(BaseModel):
    """Delete a DM event"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_direct_message_event"] = Field(
        default="delete_direct_message_event",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "Direct Message",
            "x-is-trigger": False,
            "x-display-name": "Delete Direct Message Event",
            "x-keywords": ["remove a dm", "delete direct message", "erase dm"],
        },
        title="Delete Direct Message Event",
    )
    event_id: str = Field(
        ..., title="Event ID", description="The ID of the DM event to delete"
    )


class TwitterGetDMEventConfig(BaseModel):
    """Get a specific DM event by ID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_direct_message_event_by_id"] = Field(
        default="get_direct_message_event_by_id",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "Direct Message",
            "x-is-trigger": False,
            "x-display-name": "Get Direct Message Event by Id",
            "x-keywords": [
                "single dm",
                "one direct message",
                "dm details",
                "specific message",
            ],
        },
        title="Get Direct Message Event by Id",
    )
    event_id: str = Field(
        ..., title="Event ID", description="The ID of the DM event to retrieve"
    )
    dm_event_fields: Optional[str] = Field(
        default=None,
        title="DM Event Fields",
        description="Comma-separated list of fields",
    )


class TwitterBlockDMsConfig(BaseModel):
    """Block DMs from a user"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["block_user_dms"] = Field(
        default="block_user_dms",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "DM Block",
            "x-is-trigger": False,
            "x-display-name": "Block User Dms",
            "x-keywords": ["block dms", "stop messages from", "block private messages"],
        },
        title="Block User Dms",
    )
    target_user_id: str = Field(
        ..., title="Target User ID", description="The ID of the user to block DMs from"
    )


class TwitterUnblockDMsConfig(BaseModel):
    """Unblock DMs from a user"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["unblock_user_dms"] = Field(
        default="unblock_user_dms",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "DM Block",
            "x-is-trigger": False,
            "x-display-name": "Unblock User Dms",
            "x-keywords": [
                "unblock dms",
                "allow messages again",
                "unblock private messages",
            ],
        },
        title="Unblock User Dms",
    )
    target_user_id: str = Field(
        ...,
        title="Target User ID",
        description="The ID of the user to unblock DMs from",
    )


# ============================================================================
# Additional List Operation Configs
# ============================================================================


class TwitterGetListFollowersConfig(BaseModel):
    """Get followers of a list"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_list_followers"] = Field(
        default="get_list_followers",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "List",
            "x-is-trigger": False,
            "x-display-name": "Get List Followers",
            "x-keywords": ["who follows list", "list followers", "subscribers of list"],
        },
        title="Get List Followers",
    )
    list_id: str = Field(..., title="List ID", description="The ID of the list")
    max_results: Optional[int] = Field(
        default=10, title="Max Results", description="Number of results (1-100)"
    )
    user_fields: Optional[str] = Field(
        default=None, title="User Fields", description="Comma-separated list of fields"
    )


class TwitterGetFollowedListsConfig(BaseModel):
    """Get lists followed by a user"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_lists_followed_by_user"] = Field(
        default="get_lists_followed_by_user",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "List",
            "x-is-trigger": False,
            "x-display-name": "Get Lists Followed by User",
            "x-keywords": [
                "lists user follows",
                "followed lists",
                "lists subscribed to",
                "lists i follow",
            ],
        },
        title="Get Lists Followed by User",
    )
    user_id: str = Field(..., title="User ID", description="The user ID")
    max_results: Optional[int] = Field(
        default=10, title="Max Results", description="Number of results (1-100)"
    )


class TwitterFollowListConfig(BaseModel):
    """Follow a list"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["follow_list"] = Field(
        default="follow_list",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "List",
            "x-is-trigger": False,
            "x-display-name": "Follow List",
            "x-keywords": ["follow a list", "subscribe to list", "track a list"],
        },
        title="Follow List",
    )
    list_id: str = Field(
        ..., title="List ID", description="The ID of the list to follow"
    )


class TwitterUnfollowListConfig(BaseModel):
    """Unfollow a list"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["unfollow_list"] = Field(
        default="unfollow_list",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "List",
            "x-is-trigger": False,
            "x-display-name": "Unfollow List",
            "x-keywords": [
                "unfollow a list",
                "unsubscribe from list",
                "stop following list",
            ],
        },
        title="Unfollow List",
    )
    list_id: str = Field(
        ..., title="List ID", description="The ID of the list to unfollow"
    )


# ============================================================================
# Additional Space Operation Configs
# ============================================================================


class TwitterSearchSpacesConfig(BaseModel):
    """Search for Spaces"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["search_spaces"] = Field(
        default="search_spaces",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Space",
            "x-is-trigger": False,
            "x-display-name": "Search Spaces",
            "x-keywords": [
                "find spaces",
                "audio room search",
                "query spaces",
                "discover spaces",
            ],
        },
        title="Search Spaces",
    )
    query: str = Field(..., title="Search Query", description="Space search query")
    max_results: Optional[int] = Field(
        default=10, title="Max Results", description="Number of results (1-100)"
    )
    space_fields: Optional[str] = Field(
        default=None, title="Space Fields", description="Comma-separated list of fields"
    )


class TwitterGetSpaceTweetsConfig(BaseModel):
    """Get tweets from a Space"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_tweets_from_space"] = Field(
        default="get_tweets_from_space",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Space",
            "x-is-trigger": False,
            "x-display-name": "Get Tweets from Space",
            "x-keywords": ["tweets in space", "space tweets", "posts in space"],
        },
        title="Get Tweets from Space",
    )
    space_id: str = Field(..., title="Space ID", description="The ID of the Space")
    tweet_fields: Optional[str] = Field(
        default=None, title="Tweet Fields", description="Comma-separated list of fields"
    )


class TwitterGetSpaceBuyersConfig(BaseModel):
    """Get buyers (ticket holders) of a Space"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_space_ticket_holders"] = Field(
        default="get_space_ticket_holders",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Space",
            "x-is-trigger": False,
            "x-display-name": "Get Space Ticket Holders",
            "x-keywords": [
                "space ticket buyers",
                "who bought tickets",
                "ticketed attendees",
                "space buyers",
            ],
        },
        title="Get Space Ticket Holders",
    )
    space_id: str = Field(..., title="Space ID", description="The ID of the Space")
    user_fields: Optional[str] = Field(
        default=None, title="User Fields", description="Comma-separated list of fields"
    )


# ============================================================================
# Bookmark Folder Operation Configs
# ============================================================================


class TwitterGetBookmarkFoldersConfig(BaseModel):
    """Get bookmark folders for the authenticated user"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_bookmark_folders"] = Field(
        default="get_bookmark_folders",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "Bookmark Folder",
            "x-is-trigger": False,
            "x-display-name": "Get Bookmark Folders",
            "x-keywords": [
                "bookmark folders",
                "saved folders",
                "organize bookmarks",
                "folder list bookmarks",
            ],
        },
        title="Get Bookmark Folders",
    )


# ============================================================================
# Media Operation Configs
# ============================================================================


class TwitterGetMediaUploadStatusConfig(BaseModel):
    """Get the upload status of media"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_media_upload_status"] = Field(
        default="get_media_upload_status",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "Media",
            "x-is-trigger": False,
            "x-display-name": "Get Media Upload Status",
            "x-keywords": ["upload status", "media processing", "check upload"],
        },
        title="Get Media Upload Status",
    )
    media_id: str = Field(
        ..., title="Media ID", description="The ID of the media to check status for"
    )


class TwitterCreateMediaMetadataConfig(BaseModel):
    """Create metadata for uploaded media"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_media_metadata"] = Field(
        default="create_media_metadata",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "Media",
            "x-is-trigger": False,
            "x-display-name": "Create Media Metadata",
            "x-keywords": ["alt text", "media metadata", "image description"],
        },
        title="Create Media Metadata",
    )
    media_id: str = Field(..., title="Media ID", description="The ID of the media")
    alt_text: Optional[str] = Field(
        default=None,
        title="Alt Text",
        description="Accessibility alt text for the media",
    )
    sensitive_media_warnings: Optional[str] = Field(
        default=None,
        title="Sensitive Media Warnings",
        description="Comma-separated warnings",
        json_schema_extra={
            "enum": ["adult_content", "graphic_violence", "other"],
            "x-enum-searchable": True,
        },
    )


class TwitterCreateMediaSubtitlesConfig(BaseModel):
    """Create subtitles for media"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_media_subtitles"] = Field(
        default="create_media_subtitles",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "Media",
            "x-is-trigger": False,
            "x-display-name": "Create Media Subtitles",
            "x-keywords": ["add subtitles", "add captions", "closed captions"],
        },
        title="Create Media Subtitles",
    )
    media_id: str = Field(..., title="Media ID", description="The ID of the media")
    subtitle_data: str = Field(
        ...,
        title="Subtitle Data",
        description="Base64-encoded SRT/VTT subtitle file content",
        json_schema_extra={"ui:widget": "textarea"},
    )
    language_code: str = Field(
        ..., title="Language Code", description="Language code (e.g. 'en')"
    )
    display_name: Optional[str] = Field(
        default=None,
        title="Display Name",
        description="Display name for the subtitle track (optional)",
    )


class TwitterDeleteMediaSubtitlesConfig(BaseModel):
    """Delete subtitles from media"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_media_subtitles"] = Field(
        default="delete_media_subtitles",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "Media",
            "x-is-trigger": False,
            "x-display-name": "Delete Media Subtitles",
            "x-keywords": ["remove subtitles", "remove captions"],
        },
        title="Delete Media Subtitles",
    )
    media_id: str = Field(..., title="Media ID", description="The ID of the media")
    language_code: str = Field(
        ...,
        title="Language Code",
        description="Language code of the subtitle track to delete",
    )


class TwitterGetMediaAnalyticsConfig(BaseModel):
    """Get analytics for media"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_media_analytics"] = Field(
        default="get_media_analytics",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "Media",
            "x-is-trigger": False,
            "x-display-name": "Get Media Analytics",
            "x-keywords": ["media stats", "video analytics", "media insights"],
        },
        title="Get Media Analytics",
    )
    media_keys: str = Field(
        ..., title="Media Keys", description="Comma-separated list of media keys"
    )
    start_time: Optional[str] = Field(
        default=None, title="Start Time", description="ISO 8601 start time"
    )
    end_time: Optional[str] = Field(
        default=None, title="End Time", description="ISO 8601 end time"
    )


# ============================================================================
# Filtered Stream Operation Configs
# ============================================================================


class TwitterGetFilteredStreamConfig(BaseModel):
    """Connect to filtered stream and collect tweets"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["collect_filtered_stream_tweets"] = Field(
        default="collect_filtered_stream_tweets",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Stream",
            "x-is-trigger": False,
            "x-display-name": "Collect Filtered Stream Tweets",
            "x-keywords": ["filtered stream", "live stream tweets", "realtime filter"],
        },
        title="Collect Filtered Stream Tweets",
    )
    max_events: Optional[int] = Field(
        default=10,
        title="Max Events",
        description="Max tweets to collect before disconnecting",
    )
    timeout_seconds: Optional[int] = Field(
        default=30,
        title="Timeout Seconds",
        description="Seconds to wait before disconnecting",
    )
    tweet_fields: Optional[str] = Field(
        default=None, title="Tweet Fields", description="Comma-separated list of fields"
    )
    expansions: Optional[str] = Field(
        default=None,
        title="Expansions",
        description="Comma-separated list of expansions",
    )


class TwitterGetStreamRulesConfig(BaseModel):
    """Get stream filter rules"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_stream_filter_rules"] = Field(
        default="get_stream_filter_rules",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Stream",
            "x-is-trigger": False,
            "x-display-name": "Get Stream Filter Rules",
            "x-keywords": ["stream rules", "list filter rules"],
        },
        title="Get Stream Filter Rules",
    )
    rule_ids: Optional[str] = Field(
        default=None,
        title="Rule IDs",
        description="Comma-separated rule IDs to filter by (optional)",
    )


class TwitterAddStreamRulesConfig(BaseModel):
    """Add stream filter rules"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["add_stream_filter_rules"] = Field(
        default="add_stream_filter_rules",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Stream",
            "x-is-trigger": False,
            "x-display-name": "Add Stream Filter Rules",
            "x-keywords": ["add stream rule", "new filter rule", "set stream rules"],
        },
        title="Add Stream Filter Rules",
    )
    rules: str = Field(
        ..., title="Rules", description="Comma-separated list of filter rules"
    )
    tags: Optional[str] = Field(
        default=None,
        title="Tags",
        description="Comma-separated tags for each rule (matched by position)",
    )


class TwitterDeleteStreamRulesConfig(BaseModel):
    """Delete stream filter rules by ID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_stream_filter_rules"] = Field(
        default="delete_stream_filter_rules",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Stream",
            "x-is-trigger": False,
            "x-display-name": "Delete Stream Filter Rules",
            "x-keywords": ["remove stream rule", "delete filter rule"],
        },
        title="Delete Stream Filter Rules",
    )
    rule_ids: str = Field(
        ..., title="Rule IDs", description="Comma-separated rule IDs to delete"
    )


class TwitterGetStreamRuleCountsConfig(BaseModel):
    """Get stream rule counts"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_stream_rule_counts"] = Field(
        default="get_stream_rule_counts",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Stream",
            "x-is-trigger": False,
            "x-display-name": "Get Stream Rule Counts",
            "x-keywords": ["rule counts", "stream rule limits", "filter rule usage"],
        },
        title="Get Stream Rule Counts",
    )


# ============================================================================
# Sampled Stream Operation Configs
# ============================================================================


class TwitterGetSampledStreamConfig(BaseModel):
    """Connect to sampled stream and collect tweets"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["collect_sampled_stream_tweets"] = Field(
        default="collect_sampled_stream_tweets",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Stream",
            "x-is-trigger": False,
            "x-display-name": "Collect Sampled Stream Tweets",
            "x-keywords": [
                "sampled stream",
                "random tweets stream",
                "one percent stream",
            ],
        },
        title="Collect Sampled Stream Tweets",
    )
    max_events: Optional[int] = Field(
        default=10,
        title="Max Events",
        description="Max tweets to collect before disconnecting",
    )
    timeout_seconds: Optional[int] = Field(
        default=30,
        title="Timeout Seconds",
        description="Seconds to wait before disconnecting",
    )
    tweet_fields: Optional[str] = Field(
        default=None, title="Tweet Fields", description="Comma-separated list of fields"
    )


class TwitterGetSampled10StreamConfig(BaseModel):
    """Connect to 10% sampled stream and collect tweets"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["collect_10_percent_sampled_stream_tweets"] = Field(
        default="collect_10_percent_sampled_stream_tweets",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Stream",
            "x-is-trigger": False,
            "x-display-name": "Collect 10 Percent Sampled Stream Tweets",
            "x-keywords": ["ten percent stream", "decahose", "sample stream tweets"],
        },
        title="Collect 10 Percent Sampled Stream Tweets",
    )
    partition: int = Field(
        ..., title="Partition", description="Stream partition (1 or 2)"
    )
    max_events: Optional[int] = Field(
        default=10,
        title="Max Events",
        description="Max tweets to collect before disconnecting",
    )
    timeout_seconds: Optional[int] = Field(
        default=30,
        title="Timeout Seconds",
        description="Seconds to wait before disconnecting",
    )
    tweet_fields: Optional[str] = Field(
        default=None, title="Tweet Fields", description="Comma-separated list of fields"
    )


# ============================================================================
# Trends Operation Configs
# ============================================================================


class TwitterGetTrendsByWOEIDConfig(BaseModel):
    """Get trending topics by WOEID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_trending_topics_by_woeid"] = Field(
        default="get_trending_topics_by_woeid",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Trend",
            "x-is-trigger": False,
            "x-display-name": "Get Trending Topics by Woeid",
            "x-keywords": ["trends by location", "local trends", "woeid trends"],
        },
        title="Get Trending Topics by Woeid",
    )
    woeid: str = Field(
        ...,
        title="WOEID",
        description="Where On Earth Identifier e.g. 1 for worldwide, 23424977 for USA",
    )
    max_results: Optional[int] = Field(
        default=20, title="Max Results", description="Number of results"
    )


class TwitterGetPersonalizedTrendsConfig(BaseModel):
    """Get personalized trending topics for the authenticated user"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_personalized_trending_topics"] = Field(
        default="get_personalized_trending_topics",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "Trend",
            "x-is-trigger": False,
            "x-display-name": "Get Personalized Trending Topics",
            "x-keywords": ["my trends", "personalized trends", "for you trends"],
        },
        title="Get Personalized Trending Topics",
    )


# ============================================================================
# News Operation Configs
# ============================================================================


class TwitterSearchNewsConfig(BaseModel):
    """Search news articles"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["search_news_articles"] = Field(
        default="search_news_articles",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "News",
            "x-is-trigger": False,
            "x-display-name": "Search News Articles",
            "x-keywords": ["find news", "news search"],
        },
        title="Search News Articles",
    )
    query: str = Field(
        ..., title="Search Query", description="News search query (max 2048 characters)"
    )
    max_results: Optional[int] = Field(
        default=10, title="Max Results", description="Number of results (1-100)"
    )
    start_time: Optional[str] = Field(
        default=None, title="Start Time", description="ISO 8601 start time"
    )


class TwitterGetNewsByIdConfig(BaseModel):
    """Get a news article by ID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_news_article_by_id"] = Field(
        default="get_news_article_by_id",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "News",
            "x-is-trigger": False,
            "x-display-name": "Get News Article by Id",
            "x-keywords": ["news article", "single news story"],
        },
        title="Get News Article by Id",
    )
    news_id: str = Field(..., title="News ID", description="The ID of the news article")


# ============================================================================
# Usage Operation Configs
# ============================================================================


class TwitterGetUsageConfig(BaseModel):
    """Get API usage data"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_api_usage"] = Field(
        default="get_api_usage",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_bearer_token"],
            "x-category": "API Usage",
            "x-is-trigger": False,
            "x-display-name": "Get Api Usage",
            "x-keywords": ["api usage", "rate limit usage", "quota usage"],
        },
        title="Get Api Usage",
    )
    days: Optional[int] = Field(
        default=7, title="Days", description="Number of days of usage data (1-90)"
    )


# ============================================================================
# Communities Operation Configs
# ============================================================================


class TwitterGetCommunityConfig(BaseModel):
    """Get a community by ID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_community_by_id"] = Field(
        default="get_community_by_id",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Community",
            "x-is-trigger": False,
            "x-display-name": "Get Community by Id",
            "x-keywords": ["community details", "single community"],
        },
        title="Get Community by Id",
    )
    community_id: str = Field(
        ..., title="Community ID", description="The ID of the community"
    )


class TwitterSearchCommunitiesConfig(BaseModel):
    """Search for communities"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["search_communities"] = Field(
        default="search_communities",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Community",
            "x-is-trigger": False,
            "x-display-name": "Search Communities",
            "x-keywords": ["find communities", "discover communities"],
        },
        title="Search Communities",
    )
    query: str = Field(..., title="Search Query", description="Community search query")
    max_results: Optional[int] = Field(
        default=10, title="Max Results", description="Number of results"
    )


# ============================================================================
# Community Notes Operation Configs
# ============================================================================


class TwitterCreateNoteConfig(BaseModel):
    """Create a community note on a tweet"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_community_note_on_tweet"] = Field(
        default="create_community_note_on_tweet",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "Tweet",
            "x-is-trigger": False,
            "x-display-name": "Create Community Note on Tweet",
            "x-keywords": ["add community note", "birdwatch note", "fact check note"],
        },
        title="Create Community Note on Tweet",
    )
    tweet_id: str = Field(
        ..., title="Tweet ID", description="The ID of the tweet to add a note to"
    )
    note_text: str = Field(
        ...,
        title="Note Text",
        description="Text of the community note",
        json_schema_extra={"ui:widget": "textarea"},
    )
    misleading_as: Optional[str] = Field(
        default=None,
        title="Misleading As",
        description="Classification of why tweet is misleading",
    )


class TwitterDeleteNoteConfig(BaseModel):
    """Delete a community note"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_community_note"] = Field(
        default="delete_community_note",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "Tweet",
            "x-is-trigger": False,
            "x-display-name": "Delete Community Note",
            "x-keywords": ["remove community note", "delete birdwatch"],
        },
        title="Delete Community Note",
    )
    note_id: str = Field(
        ..., title="Note ID", description="The ID of the community note to delete"
    )


class TwitterEvaluateNoteConfig(BaseModel):
    """Evaluate a community note"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["evaluate_community_note"] = Field(
        default="evaluate_community_note",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_oauth"],
            "x-category": "Tweet",
            "x-is-trigger": False,
            "x-display-name": "Evaluate Community Note",
            "x-keywords": ["rate community note", "review note", "helpful note vote"],
        },
        title="Evaluate Community Note",
    )
    note_id: str = Field(
        ..., title="Note ID", description="The ID of the community note to evaluate"
    )


class TwitterGetNotesWrittenConfig(BaseModel):
    """Get community notes written by the authenticated user"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_community_notes_written"] = Field(
        default="get_community_notes_written",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Tweet",
            "x-is-trigger": False,
            "x-display-name": "Get Community Notes Written",
            "x-keywords": ["my community notes", "notes i wrote", "birdwatch written"],
        },
        title="Get Community Notes Written",
    )
    max_results: Optional[int] = Field(
        default=10, title="Max Results", description="Number of results"
    )


class TwitterGetPostsEligibleForNotesConfig(BaseModel):
    """Get posts eligible for community notes"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_posts_eligible_for_community_notes"] = Field(
        default="get_posts_eligible_for_community_notes",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Bookmark Folder",
            "x-is-trigger": False,
            "x-display-name": "Get Posts Eligible for Community Notes",
            "x-keywords": [
                "notable posts",
                "eligible for notes",
                "posts needing notes",
            ],
        },
        title="Get Posts Eligible for Community Notes",
    )
    max_results: Optional[int] = Field(
        default=10, title="Max Results", description="Number of results"
    )


# ============================================================================
# Compliance Job Operation Configs
# ============================================================================


class TwitterCreateComplianceJobConfig(BaseModel):
    """Create a compliance job"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_compliance_job"] = Field(
        default="create_compliance_job",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_bearer_token"],
            "x-category": "Compliance Job",
            "x-is-trigger": False,
            "x-display-name": "Create Compliance Job",
            "x-keywords": [
                "new compliance job",
                "compliance batch",
                "start compliance",
            ],
        },
        title="Create Compliance Job",
    )
    type: str = Field(
        ...,
        title="Type",
        description="Type of compliance job",
        json_schema_extra={"enum": ["tweets", "users"], "x-enum-searchable": True},
    )
    name: Optional[str] = Field(
        default=None, title="Name", description="Optional name for the compliance job"
    )


class TwitterGetComplianceJobConfig(BaseModel):
    """Get a compliance job by ID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_compliance_job_by_id"] = Field(
        default="get_compliance_job_by_id",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_bearer_token"],
            "x-category": "Compliance Job",
            "x-is-trigger": False,
            "x-display-name": "Get Compliance Job by Id",
            "x-keywords": ["compliance job details", "single compliance job"],
        },
        title="Get Compliance Job by Id",
    )
    job_id: str = Field(..., title="Job ID", description="The ID of the compliance job")


class TwitterListComplianceJobsConfig(BaseModel):
    """List compliance jobs"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["list_compliance_jobs"] = Field(
        default="list_compliance_jobs",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_bearer_token"],
            "x-category": "Compliance Job",
            "x-is-trigger": False,
            "x-display-name": "List Compliance Jobs",
            "x-keywords": ["compliance batches", "list compliance jobs"],
        },
        title="List Compliance Jobs",
    )
    type: Optional[str] = Field(
        default=None,
        title="Type",
        description="Filter by job type",
        json_schema_extra={"enum": ["tweets", "users"], "x-enum-searchable": True},
    )


# ============================================================================
# Webhook Operation Configs
# ============================================================================


class TwitterCreateWebhookConfig(BaseModel):
    """Create a webhook"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_webhook"] = Field(
        default="create_webhook",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_bearer_token"],
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Create Webhook",
            "x-keywords": [
                "register webhook",
                "webhook endpoint",
                "callback url",
                "new webhook",
            ],
        },
        title="Create Webhook",
    )
    url: str = Field(..., title="URL", description="The URL for the webhook endpoint")
    name: Optional[str] = Field(
        default=None, title="Name", description="Optional name for the webhook"
    )


class TwitterDeleteWebhookConfig(BaseModel):
    """Delete a webhook"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_webhook"] = Field(
        default="delete_webhook",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_bearer_token"],
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Delete Webhook",
            "x-keywords": ["remove webhook", "delete callback", "drop webhook"],
        },
        title="Delete Webhook",
    )
    webhook_id: str = Field(
        ..., title="Webhook ID", description="The ID of the webhook to delete"
    )


class TwitterGetWebhookConfig(BaseModel):
    """Get a webhook by ID"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_webhook_by_id"] = Field(
        default="get_webhook_by_id",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_bearer_token"],
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Get Webhook by Id",
            "x-keywords": [
                "single webhook",
                "webhook details",
                "callback by id",
                "one webhook",
            ],
        },
        title="Get Webhook by Id",
    )
    webhook_id: str = Field(
        ..., title="Webhook ID", description="The ID of the webhook"
    )


class TwitterValidateWebhookConfig(BaseModel):
    """Validate a webhook"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["validate_webhook"] = Field(
        default="validate_webhook",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_bearer_token"],
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Validate Webhook",
            "x-keywords": [
                "verify webhook",
                "check webhook",
                "crc challenge",
                "webhook health",
            ],
        },
        title="Validate Webhook",
    )
    webhook_id: str = Field(
        ..., title="Webhook ID", description="The ID of the webhook to validate"
    )


class TwitterCreateStreamLinkConfig(BaseModel):
    """Create a stream link for a webhook"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_webhook_stream_link"] = Field(
        default="create_webhook_stream_link",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_bearer_token"],
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Create Webhook Stream Link",
            "x-keywords": [
                "link webhook stream",
                "attach stream",
                "connect webhook stream",
            ],
        },
        title="Create Webhook Stream Link",
    )
    webhook_id: str = Field(
        ..., title="Webhook ID", description="The ID of the webhook"
    )


class TwitterDeleteStreamLinkConfig(BaseModel):
    """Delete a stream link from a webhook"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_webhook_stream_link"] = Field(
        default="delete_webhook_stream_link",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_bearer_token"],
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Delete Webhook Stream Link",
            "x-keywords": [
                "unlink webhook stream",
                "detach stream",
                "remove stream link",
            ],
        },
        title="Delete Webhook Stream Link",
    )
    webhook_id: str = Field(
        ..., title="Webhook ID", description="The ID of the webhook"
    )
    stream_link_id: str = Field(
        ..., title="Stream Link ID", description="The ID of the stream link to delete"
    )


class TwitterGetStreamLinksConfig(BaseModel):
    """Get stream links for a webhook"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_webhook_stream_links"] = Field(
        default="get_webhook_stream_links",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_bearer_token"],
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Get Webhook Stream Links",
            "x-keywords": [
                "list stream links",
                "webhook stream links",
                "attached streams",
            ],
        },
        title="Get Webhook Stream Links",
    )
    webhook_id: str = Field(
        ..., title="Webhook ID", description="The ID of the webhook"
    )


class TwitterCreateWebhookReplayConfig(BaseModel):
    """Create a webhook replay"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_webhook_replay"] = Field(
        default="create_webhook_replay",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_bearer_token"],
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Create Webhook Replay",
            "x-keywords": [
                "replay webhook",
                "redeliver webhook",
                "resend webhook events",
            ],
        },
        title="Create Webhook Replay",
    )
    webhook_id: str = Field(
        ..., title="Webhook ID", description="The ID of the webhook"
    )
    from_date: Optional[str] = Field(
        default=None, title="From Date", description="ISO 8601 start date for replay"
    )
    to_date: Optional[str] = Field(
        default=None, title="To Date", description="ISO 8601 end date for replay"
    )


# ============================================================================
# Account Activity Subscription Operation Configs
# ============================================================================


class TwitterCreateSubscriptionConfig(BaseModel):
    """Create an account activity subscription"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_account_activity_subscription"] = Field(
        default="create_account_activity_subscription",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_bearer_token"],
            "x-category": "Subscription",
            "x-is-trigger": False,
            "x-display-name": "Create Account Activity Subscription",
            "x-keywords": [
                "subscribe account activity",
                "add activity feed",
                "register activity subscription",
            ],
        },
        title="Create Account Activity Subscription",
    )
    webhook_id: str = Field(
        ..., title="Webhook ID", description="Webhook ID to subscribe to"
    )


class TwitterDeleteSubscriptionConfig(BaseModel):
    """Delete an account activity subscription"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["delete_account_activity_subscription"] = Field(
        default="delete_account_activity_subscription",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_bearer_token"],
            "x-category": "Subscription",
            "x-is-trigger": False,
            "x-display-name": "Delete Account Activity Subscription",
            "x-keywords": [
                "unsubscribe account activity",
                "remove activity feed",
                "drop activity subscription",
            ],
        },
        title="Delete Account Activity Subscription",
    )
    webhook_id: str = Field(
        ..., title="Webhook ID", description="Webhook ID of the subscription to delete"
    )


class TwitterGetSubscriptionsConfig(BaseModel):
    """Get account activity subscriptions"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_account_activity_subscriptions"] = Field(
        default="get_account_activity_subscriptions",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_bearer_token"],
            "x-category": "Subscription",
            "x-is-trigger": False,
            "x-display-name": "Get Account Activity Subscriptions",
            "x-keywords": [
                "list activity subscriptions",
                "active activity feeds",
                "subscribed accounts",
            ],
        },
        title="Get Account Activity Subscriptions",
    )
    webhook_id: str = Field(
        ..., title="Webhook ID", description="The Webhook ID to list subscriptions for"
    )


class TwitterGetSubscriptionCountConfig(BaseModel):
    """Get account activity subscription count"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_account_activity_subscription_count"] = Field(
        default="get_account_activity_subscription_count",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_bearer_token"],
            "x-category": "Subscription",
            "x-is-trigger": False,
            "x-display-name": "Get Account Activity Subscription Count",
            "x-keywords": [
                "subscription count",
                "how many subscriptions",
                "activity subscription total",
            ],
        },
        title="Get Account Activity Subscription Count",
    )


class TwitterValidateSubscriptionConfig(BaseModel):
    """Validate account activity subscription"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["validate_account_activity_subscription"] = Field(
        default="validate_account_activity_subscription",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_bearer_token"],
            "x-category": "Subscription",
            "x-is-trigger": False,
            "x-display-name": "Validate Account Activity Subscription",
            "x-keywords": [
                "verify activity subscription",
                "check subscription status",
                "is subscribed",
            ],
        },
        title="Validate Account Activity Subscription",
    )


class TwitterCreateSubscriptionReplayConfig(BaseModel):
    """Create an account activity subscription replay"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["create_account_activity_subscription_replay"] = Field(
        default="create_account_activity_subscription_replay",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_bearer_token"],
            "x-category": "Subscription",
            "x-is-trigger": False,
            "x-display-name": "Create Account Activity Subscription Replay",
            "x-keywords": [
                "replay account activity",
                "redeliver activity events",
                "resend activity feed",
            ],
        },
        title="Create Account Activity Subscription Replay",
    )
    webhook_id: str = Field(..., title="Webhook ID", description="The Webhook ID")
    from_date: Optional[str] = Field(
        default=None, title="From Date", description="ISO 8601 start date for replay"
    )
    to_date: Optional[str] = Field(
        default=None, title="To Date", description="ISO 8601 end date for replay"
    )


# ============================================================================
# Streaming Connections Management Configs
# ============================================================================


class TwitterGetConnectionsConfig(BaseModel):
    """Get all streaming connections"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["get_all_streaming_connections"] = Field(
        default="get_all_streaming_connections",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_bearer_token"],
            "x-category": "Stream",
            "x-is-trigger": False,
            "x-display-name": "Get All Streaming Connections",
            "x-keywords": [
                "list stream connections",
                "active streams",
                "open connections",
            ],
        },
        title="Get All Streaming Connections",
    )


class TwitterTerminateAllConnectionsConfig(BaseModel):
    """Terminate all streaming connections"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["terminate_all_streaming_connections"] = Field(
        default="terminate_all_streaming_connections",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_bearer_token"],
            "x-category": "Stream",
            "x-is-trigger": False,
            "x-display-name": "Terminate All Streaming Connections",
            "x-keywords": [
                "kill all streams",
                "close all connections",
                "disconnect everything",
            ],
        },
        title="Terminate All Streaming Connections",
    )


class TwitterTerminateConnectionsByEndpointConfig(BaseModel):
    """Terminate streaming connections by endpoint type"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["terminate_streaming_connections_by_endpoint_type"] = Field(
        default="terminate_streaming_connections_by_endpoint_type",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_bearer_token"],
            "x-category": "Stream",
            "x-is-trigger": False,
            "x-display-name": "Terminate Streaming Connections by Endpoint Type",
            "x-keywords": [
                "kill endpoint streams",
                "close endpoint connections",
                "disconnect by endpoint",
            ],
        },
        title="Terminate Streaming Connections by Endpoint Type",
    )
    endpoint_type: str = Field(
        ...,
        title="Endpoint Type",
        description="Endpoint type to terminate connections for",
    )


class TwitterTerminateConnectionConfig(BaseModel):
    """Terminate a specific streaming connection"""

    model_config = ConfigDict(populate_by_name=True)

    operation: Literal["terminate_streaming_connection"] = Field(
        default="terminate_streaming_connection",
        json_schema_extra={
            "ui:hidden": True,
            "x-supported-credential-types": ["twitter_bearer_token"],
            "x-category": "Stream",
            "x-is-trigger": False,
            "x-display-name": "Terminate Streaming Connection",
            "x-keywords": [
                "kill one stream",
                "close single connection",
                "disconnect specific stream",
            ],
        },
        title="Terminate Streaming Connection",
    )
    connection_id: str = Field(
        ..., title="Connection ID", description="The ID of the connection to terminate"
    )


# ============================================================================
# Discriminated Union
# ============================================================================

TwitterConfig = Annotated[
    Union[
        # Tweet operations
        TwitterCreateTweetConfig,
        TwitterDeleteTweetConfig,
        TwitterGetTweetConfig,
        TwitterGetTweetsConfig,
        TwitterSearchRecentTweetsConfig,
        TwitterSearchAllTweetsConfig,
        TwitterGetTweetCountsRecentConfig,
        TwitterGetTweetCountsAllConfig,
        TwitterGetTweetAnalyticsConfig,
        TwitterGetRetweetsConfig,
        # User operations
        TwitterGetUserConfig,
        TwitterGetUserByUsernameConfig,
        TwitterGetMeConfig,
        TwitterGetUsersConfig,
        TwitterGetUsersByUsernamesConfig,
        TwitterSearchUsersConfig,
        # Like operations
        TwitterLikeTweetConfig,
        TwitterUnlikeTweetConfig,
        TwitterGetLikedTweetsConfig,
        TwitterGetLikingUsersConfig,
        # Retweet operations
        TwitterRetweetConfig,
        TwitterUndoRetweetConfig,
        TwitterGetRetweetersConfig,
        # Follow operations
        TwitterFollowUserConfig,
        TwitterUnfollowUserConfig,
        TwitterGetFollowersConfig,
        TwitterGetFollowingConfig,
        # Block operations
        TwitterBlockUserConfig,
        TwitterUnblockUserConfig,
        TwitterGetBlockedUsersConfig,
        # Mute operations
        TwitterMuteUserConfig,
        TwitterUnmuteUserConfig,
        TwitterGetMutedUsersConfig,
        # Bookmark operations
        TwitterAddBookmarkConfig,
        TwitterRemoveBookmarkConfig,
        TwitterGetBookmarksConfig,
        TwitterGetBookmarkFoldersConfig,
        # Direct Message operations
        TwitterCreateDMConversationConfig,
        TwitterSendDMConfig,
        TwitterSendDMToConversationConfig,
        TwitterGetDMConversationConfig,
        TwitterGetDMEventsConfig,
        TwitterGetAllDMEventsConfig,
        TwitterDeleteDMEventConfig,
        TwitterGetDMEventConfig,
        TwitterBlockDMsConfig,
        TwitterUnblockDMsConfig,
        # List operations
        TwitterCreateListConfig,
        TwitterDeleteListConfig,
        TwitterUpdateListConfig,
        TwitterGetListConfig,
        TwitterGetUserOwnedListsConfig,
        TwitterGetUserListMembershipsConfig,
        TwitterGetListTweetsConfig,
        TwitterAddListMemberConfig,
        TwitterRemoveListMemberConfig,
        TwitterGetListMembersConfig,
        TwitterPinListConfig,
        TwitterUnpinListConfig,
        TwitterGetPinnedListsConfig,
        TwitterGetListFollowersConfig,
        TwitterGetFollowedListsConfig,
        TwitterFollowListConfig,
        TwitterUnfollowListConfig,
        # Space operations
        TwitterGetSpaceConfig,
        TwitterGetSpacesConfig,
        TwitterGetSpacesByCreatorsConfig,
        TwitterSearchSpacesConfig,
        TwitterGetSpaceTweetsConfig,
        TwitterGetSpaceBuyersConfig,
        # Media upload operations
        TwitterUploadMediaConfig,
        TwitterUploadMediaChunkedConfig,
        TwitterGetMediaUploadStatusConfig,
        TwitterCreateMediaMetadataConfig,
        TwitterCreateMediaSubtitlesConfig,
        TwitterDeleteMediaSubtitlesConfig,
        TwitterGetMediaAnalyticsConfig,
        # Timeline operations
        TwitterGetUserTweetsConfig,
        TwitterGetUserMentionsConfig,
        TwitterGetHomeTimelineConfig,
        # Quote operations
        TwitterGetQuoteTweetsConfig,
        # Hide reply operations
        TwitterHideReplyConfig,
        TwitterUnhideReplyConfig,
        # Filtered stream operations
        TwitterGetFilteredStreamConfig,
        TwitterGetStreamRulesConfig,
        TwitterAddStreamRulesConfig,
        TwitterDeleteStreamRulesConfig,
        TwitterGetStreamRuleCountsConfig,
        # Sampled stream operations
        TwitterGetSampledStreamConfig,
        TwitterGetSampled10StreamConfig,
        # Trends operations
        TwitterGetTrendsByWOEIDConfig,
        TwitterGetPersonalizedTrendsConfig,
        # News operations
        TwitterSearchNewsConfig,
        TwitterGetNewsByIdConfig,
        # Usage operations
        TwitterGetUsageConfig,
        # Communities operations
        TwitterGetCommunityConfig,
        TwitterSearchCommunitiesConfig,
        # Community Notes operations
        TwitterCreateNoteConfig,
        TwitterDeleteNoteConfig,
        TwitterEvaluateNoteConfig,
        TwitterGetNotesWrittenConfig,
        TwitterGetPostsEligibleForNotesConfig,
        # Compliance job operations
        TwitterCreateComplianceJobConfig,
        TwitterGetComplianceJobConfig,
        TwitterListComplianceJobsConfig,
        # Webhook operations
        TwitterCreateWebhookConfig,
        TwitterDeleteWebhookConfig,
        TwitterGetWebhookConfig,
        TwitterValidateWebhookConfig,
        TwitterCreateStreamLinkConfig,
        TwitterDeleteStreamLinkConfig,
        TwitterGetStreamLinksConfig,
        TwitterCreateWebhookReplayConfig,
        # Account activity subscription operations
        TwitterCreateSubscriptionConfig,
        TwitterDeleteSubscriptionConfig,
        TwitterGetSubscriptionsConfig,
        TwitterGetSubscriptionCountConfig,
        TwitterValidateSubscriptionConfig,
        TwitterCreateSubscriptionReplayConfig,
        # Streaming connections management
        TwitterGetConnectionsConfig,
        TwitterTerminateAllConnectionsConfig,
        TwitterTerminateConnectionsByEndpointConfig,
        TwitterTerminateConnectionConfig,
    ],
    Discriminator("operation"),
]


class TwitterNodeConfig(NodeConfig[TwitterConfig, TwitterCredential]):
    """Full configuration for Twitter node including credentials"""

    pass


# ============================================================================
# Twitter Node Implementation
# ============================================================================


class TwitterNode(WorkflowNode):
    """
    Twitter/X REST API v2 automation node.

    Executes Twitter/X operations via REST API.
    Supports OAuth 2.0 with PKCE for write operations and Bearer Token for read-only.
    """

    edit_examples = [
        "Post a tweet announcing the latest product release",
        "Search tweets mentioning the product name and sentiment",
        "Retweet announcements from @anthropic about updates",
        "Like tweets from followers who mention the brand",
        "Follow accounts that engage with security content",
        "Get list of users who liked a specific product tweet",
        "Block spam accounts replying to customer support tweets",
    ]

    scope_registry = TWITTER_SCOPES
    connection_evidence = ConnectionEvidence(
        noun="account",
        identity_operation="get_authenticated_user",
    )

    @classmethod
    def get_config_model(cls):
        return TwitterNodeConfig

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Load dynamic options for dropdown fields.
        Called when frontend needs to populate a dynamic select field.

        Args:
            field_name: Name of the field to load options for
            credential_data: Decrypted credential data
            context: Optional context (e.g., current node config)

        Returns:
            List of options with value, label, and optional metadata
        """
        if field_name == "list_id":
            return await cls._load_user_lists(credential_data, search=search)

        return []

    @classmethod
    async def _load_user_lists(
        cls, credential_data: Dict[str, Any], search: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Load authenticated user's owned lists for dropdown."""
        # Fail loud when the credential token is missing so the UI shows
        # "Open Credentials" instead of a misleading empty list. API errors
        # below also raise so a real failure never masquerades as "No options".
        access_token = require_credential_token(
            credential_data.get("access_token"),
            "Connect a Twitter account to load lists",
        )
        try:
            # Get authenticated user ID first
            async with httpx.AsyncClient() as client:
                me_response = await client.get(
                    f"{TWITTER_API_BASE}/users/me",
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=10.0,
                )

                if me_response.status_code != 200:
                    raise ValueError(
                        f"Twitter API error: failed to get user ID "
                        f"({me_response.status_code}): {me_response.text}"
                    )

                user_data = me_response.json()
                user_id = user_data.get("data", {}).get("id")

                if not user_id:
                    raise ValueError("Twitter API error: no user ID in response")

                # Fetch owned lists
                lists_response = await client.get(
                    f"{TWITTER_API_BASE}/users/{user_id}/owned_lists",
                    headers={"Authorization": f"Bearer {access_token}"},
                    params={
                        "max_results": 100,
                        "list.fields": "name,description,member_count",
                    },
                    timeout=10.0,
                )

                if lists_response.status_code != 200:
                    raise ValueError(
                        f"Twitter API error: failed to fetch lists "
                        f"({lists_response.status_code}): {lists_response.text}"
                    )

                lists_data = lists_response.json()
                lists = lists_data.get("data", [])

                # Convert to dropdown options
                options = []
                for list_item in lists:
                    label = list_item.get("name", "Unnamed List")
                    description = list_item.get("description", "")
                    member_count = list_item.get("member_count", 0)

                    # Add member count to label for context
                    if member_count > 0:
                        label = f"{label} ({member_count} members)"

                    options.append(
                        {
                            "value": list_item.get("id"),
                            "label": label,
                            "metadata": {
                                "description": description,
                                "member_count": member_count,
                            },
                        }
                    )

                logger.info(f"[TwitterNode] Loaded {len(options)} lists for dropdown")
                return options

        except ValueError:
            raise
        except Exception as e:
            logger.error(f"[TwitterNode] Error loading lists: {e}", exc_info=True)
            raise ValueError(f"Failed to load Twitter options: {e}") from e

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute Twitter action via REST API."""
        logger.info(f"[TwitterNode] Executing node {self.node_id}")

        node_config = self.config
        if not node_config or not isinstance(node_config, TwitterNodeConfig):
            raise ValueError("TwitterNode requires valid configuration")

        config = node_config.config
        credentials = node_config.credentials

        if not credentials:
            raise ValueError(
                "[TwitterNode] Credentials are required. "
                "Please add your Twitter OAuth or Bearer Token in the node's credentials tab."
            )

        # Pre-flight credit gate (standardized) — fail before any X API cost when
        # the billing pool (org owner under the configured attribution policy, else the caller) is out of
        # credits or its owner can't be resolved. BYOK skips automatically. The
        # post-op track_usage_event still records actual spend; this just stops
        # zero-credit org members from incurring X cost first.
        if self.user_id:
            from billing.usage_tracker import usage_tracker

            await usage_tracker.enforce_credit_gate(
                self.user_id,
                organization_id=self.organization_id,
                sio=self.sio,
                sid=self.sid,
                user_resource=self._is_user_resource(credentials),
                surface="twitter",
            )

        # Route to appropriate handler based on config type
        action_handlers = {
            # Tweet operations
            TwitterCreateTweetConfig: self._create_tweet,
            TwitterDeleteTweetConfig: self._delete_tweet,
            TwitterGetTweetConfig: self._get_tweet,
            TwitterGetTweetsConfig: self._get_tweets,
            TwitterSearchRecentTweetsConfig: self._search_recent_tweets,
            TwitterSearchAllTweetsConfig: self._search_all_tweets,
            TwitterGetTweetCountsRecentConfig: self._get_tweet_counts_recent,
            TwitterGetTweetCountsAllConfig: self._get_tweet_counts_all,
            TwitterGetTweetAnalyticsConfig: self._get_tweet_analytics,
            TwitterGetRetweetsConfig: self._get_retweets,
            # User operations
            TwitterGetUserConfig: self._get_user,
            TwitterGetUserByUsernameConfig: self._get_user_by_username,
            TwitterGetMeConfig: self._get_me,
            TwitterGetUsersConfig: self._get_users,
            TwitterGetUsersByUsernamesConfig: self._get_users_by_usernames,
            TwitterSearchUsersConfig: self._search_users,
            # Like operations
            TwitterLikeTweetConfig: self._like_tweet,
            TwitterUnlikeTweetConfig: self._unlike_tweet,
            TwitterGetLikedTweetsConfig: self._get_liked_tweets,
            TwitterGetLikingUsersConfig: self._get_liking_users,
            # Retweet operations
            TwitterRetweetConfig: self._retweet,
            TwitterUndoRetweetConfig: self._undo_retweet,
            TwitterGetRetweetersConfig: self._get_retweeters,
            # Follow operations
            TwitterFollowUserConfig: self._follow_user,
            TwitterUnfollowUserConfig: self._unfollow_user,
            TwitterGetFollowersConfig: self._get_followers,
            TwitterGetFollowingConfig: self._get_following,
            # Block operations
            TwitterBlockUserConfig: self._block_user,
            TwitterUnblockUserConfig: self._unblock_user,
            TwitterGetBlockedUsersConfig: self._get_blocked_users,
            # Mute operations
            TwitterMuteUserConfig: self._mute_user,
            TwitterUnmuteUserConfig: self._unmute_user,
            TwitterGetMutedUsersConfig: self._get_muted_users,
            # Bookmark operations
            TwitterAddBookmarkConfig: self._add_bookmark,
            TwitterRemoveBookmarkConfig: self._remove_bookmark,
            TwitterGetBookmarksConfig: self._get_bookmarks,
            TwitterGetBookmarkFoldersConfig: self._get_bookmark_folders,
            # Direct Message operations
            TwitterCreateDMConversationConfig: self._create_dm_conversation,
            TwitterSendDMConfig: self._send_dm,
            TwitterSendDMToConversationConfig: self._send_dm_to_conversation,
            TwitterGetDMConversationConfig: self._get_dm_conversation,
            TwitterGetDMEventsConfig: self._get_dm_events,
            TwitterGetAllDMEventsConfig: self._get_all_dm_events,
            TwitterDeleteDMEventConfig: self._delete_dm_event,
            TwitterGetDMEventConfig: self._get_dm_event,
            TwitterBlockDMsConfig: self._block_dms,
            TwitterUnblockDMsConfig: self._unblock_dms,
            # List operations
            TwitterCreateListConfig: self._create_list,
            TwitterDeleteListConfig: self._delete_list,
            TwitterUpdateListConfig: self._update_list,
            TwitterGetListConfig: self._get_list,
            TwitterGetUserOwnedListsConfig: self._get_user_owned_lists,
            TwitterGetUserListMembershipsConfig: self._get_user_list_memberships,
            TwitterGetListTweetsConfig: self._get_list_tweets,
            TwitterAddListMemberConfig: self._add_list_member,
            TwitterRemoveListMemberConfig: self._remove_list_member,
            TwitterGetListMembersConfig: self._get_list_members,
            TwitterPinListConfig: self._pin_list,
            TwitterUnpinListConfig: self._unpin_list,
            TwitterGetPinnedListsConfig: self._get_pinned_lists,
            TwitterGetListFollowersConfig: self._get_list_followers,
            TwitterGetFollowedListsConfig: self._get_followed_lists,
            TwitterFollowListConfig: self._follow_list,
            TwitterUnfollowListConfig: self._unfollow_list,
            # Space operations
            TwitterGetSpaceConfig: self._get_space,
            TwitterGetSpacesConfig: self._get_spaces,
            TwitterGetSpacesByCreatorsConfig: self._get_spaces_by_creators,
            TwitterSearchSpacesConfig: self._search_spaces,
            TwitterGetSpaceTweetsConfig: self._get_space_tweets,
            TwitterGetSpaceBuyersConfig: self._get_space_buyers,
            # Media upload operations
            TwitterUploadMediaConfig: self._upload_media,
            TwitterUploadMediaChunkedConfig: self._upload_media_chunked,
            TwitterGetMediaUploadStatusConfig: self._get_media_upload_status,
            TwitterCreateMediaMetadataConfig: self._create_media_metadata,
            TwitterCreateMediaSubtitlesConfig: self._create_media_subtitles,
            TwitterDeleteMediaSubtitlesConfig: self._delete_media_subtitles,
            TwitterGetMediaAnalyticsConfig: self._get_media_analytics,
            # Timeline operations
            TwitterGetUserTweetsConfig: self._get_user_tweets,
            TwitterGetUserMentionsConfig: self._get_user_mentions,
            TwitterGetHomeTimelineConfig: self._get_home_timeline,
            # Quote operations
            TwitterGetQuoteTweetsConfig: self._get_quote_tweets,
            # Hide reply operations
            TwitterHideReplyConfig: self._hide_reply,
            TwitterUnhideReplyConfig: self._unhide_reply,
            # Filtered stream operations
            TwitterGetFilteredStreamConfig: self._get_filtered_stream,
            TwitterGetStreamRulesConfig: self._get_stream_rules,
            TwitterAddStreamRulesConfig: self._add_stream_rules,
            TwitterDeleteStreamRulesConfig: self._delete_stream_rules,
            TwitterGetStreamRuleCountsConfig: self._get_stream_rule_counts,
            # Sampled stream operations
            TwitterGetSampledStreamConfig: self._get_sampled_stream,
            TwitterGetSampled10StreamConfig: self._get_sampled10_stream,
            # Trends operations
            TwitterGetTrendsByWOEIDConfig: self._get_trends_by_woeid,
            TwitterGetPersonalizedTrendsConfig: self._get_personalized_trends,
            # News operations
            TwitterSearchNewsConfig: self._search_news,
            TwitterGetNewsByIdConfig: self._get_news_by_id,
            # Usage operations
            TwitterGetUsageConfig: self._get_usage,
            # Communities operations
            TwitterGetCommunityConfig: self._get_community,
            TwitterSearchCommunitiesConfig: self._search_communities,
            # Community Notes operations
            TwitterCreateNoteConfig: self._create_note,
            TwitterDeleteNoteConfig: self._delete_note,
            TwitterEvaluateNoteConfig: self._evaluate_note,
            TwitterGetNotesWrittenConfig: self._get_notes_written,
            TwitterGetPostsEligibleForNotesConfig: self._get_posts_eligible_for_notes,
            # Compliance job operations
            TwitterCreateComplianceJobConfig: self._create_compliance_job,
            TwitterGetComplianceJobConfig: self._get_compliance_job,
            TwitterListComplianceJobsConfig: self._list_compliance_jobs,
            # Webhook operations
            TwitterCreateWebhookConfig: self._create_webhook,
            TwitterDeleteWebhookConfig: self._delete_webhook,
            TwitterGetWebhookConfig: self._get_webhook,
            TwitterValidateWebhookConfig: self._validate_webhook,
            TwitterCreateStreamLinkConfig: self._create_stream_link,
            TwitterDeleteStreamLinkConfig: self._delete_stream_link,
            TwitterGetStreamLinksConfig: self._get_stream_links,
            TwitterCreateWebhookReplayConfig: self._create_webhook_replay,
            # Account activity subscription operations
            TwitterCreateSubscriptionConfig: self._create_subscription,
            TwitterDeleteSubscriptionConfig: self._delete_subscription,
            TwitterGetSubscriptionsConfig: self._get_subscriptions,
            TwitterGetSubscriptionCountConfig: self._get_subscription_count,
            TwitterValidateSubscriptionConfig: self._validate_subscription,
            TwitterCreateSubscriptionReplayConfig: self._create_subscription_replay,
            # Streaming connections management
            TwitterGetConnectionsConfig: self._get_connections,
            TwitterTerminateAllConnectionsConfig: self._terminate_all_connections,
            TwitterTerminateConnectionsByEndpointConfig: self._terminate_connections_by_endpoint,
            TwitterTerminateConnectionConfig: self._terminate_connection,
        }

        handler = action_handlers.get(type(config))
        if not handler:
            raise ValueError(f"Unknown config type: {type(config)}")

        return await handler(config, credentials)

    @classmethod
    async def freshen_credential(
        cls, credential_data, *, pool=None, user_id=None, credential_id=None
    ):
        """Refresh an expiring OAuth token at credential load (dropdowns,
        trigger registration). No-op for non-rotating credentials (API keys /
        offline / non-expiring tokens)."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.twitter_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data,
            pool=pool,
            user_id=user_id,
            credential_id=credential_id,
            refresh=refresh_access_token,
            provider="twitter",
        )

    async def _get_access_token(self, credentials: TwitterCredential) -> str:
        """
        Get access token from credentials, refreshing if expired (OAuth only).

        Bearer tokens are returned as-is (they don't expire via OAuth flow).
        For OAuth tokens, a per-credential lock prevents concurrent refresh races.
        On successful refresh, the new token is persisted to the database.
        """
        if isinstance(credentials, TwitterBearerTokenCredential):
            return credentials.bearer_token

        if isinstance(credentials, TwitterOAuthCredential):
            # No expiry info — nothing to refresh against.
            if not credentials.expires_at:
                return credentials.access_token

            from nodes.core.oauth_refresh import ensure_fresh_oauth_token
            
            async def _refresh(refresh_token: str):
                # Pass custom client credentials if the user brought their own app.
                return await refresh_access_token(
                    refresh_token,
                    client_id=credentials.client_id,
                    client_secret=credentials.client_secret,
                )

            cred_dict = credentials.model_dump()
            token = await ensure_fresh_oauth_token(
                credential_id=self.node_data.get("credential_id"),
                user_id=self.user_id,
                credential=cred_dict,
                is_expired=is_token_expired,
                refresh=_refresh,
                provider="twitter",
            )
            # Mirror the refreshed tokens back onto the in-memory model.
            credentials.access_token = cred_dict["access_token"]
            credentials.expires_at = cred_dict.get("expires_at")
            if cred_dict.get("refresh_token"):
                credentials.refresh_token = cred_dict["refresh_token"]
            return token

        # Fallback for dict-like access (when loaded from DB)
        if hasattr(credentials, "access_token"):
            return credentials.access_token
        elif hasattr(credentials, "bearer_token"):
            return credentials.bearer_token
        raise ValueError("Invalid credential type - no access token found")

    def _get_user_id(self, credentials: TwitterCredential) -> Optional[str]:
        """Get the authenticated user's ID from credentials."""
        if isinstance(credentials, TwitterOAuthCredential):
            return credentials.user_id
        return None

    def _get_client_credentials(
        self, credentials: TwitterCredential
    ) -> Optional[tuple[str, str]]:
        """Get client ID and secret from OAuth credentials if custom credentials provided."""
        if isinstance(credentials, TwitterOAuthCredential):
            # Check if user provided custom client credentials
            if credentials.client_id and credentials.client_secret:
                return (credentials.client_id, credentials.client_secret)
        return None

    def _is_user_resource(self, credentials: TwitterCredential) -> bool:
        """True when user provides their own X developer app credentials (they pay X directly)."""
        if isinstance(credentials, TwitterBearerTokenCredential):
            return True
        if isinstance(credentials, TwitterOAuthCredential):
            return bool(credentials.client_id)
        return True

    @staticmethod
    def _infer_x_operation(method: str, endpoint: str) -> Optional[str]:
        """Map HTTP method + endpoint to X API billing operation type."""
        if method in ("DELETE", "PUT"):
            return None
        if method == "POST":
            if endpoint == "/tweets":
                return "post_create"
            if "dm_conversations" in endpoint:
                return "dm_create"
            if "/users/" in endpoint and any(
                k in endpoint for k in ("/likes", "/retweets", "/following")
            ):
                return "user_interaction"
            if endpoint.startswith("/notes"):
                return "user_interaction"
            return None
        if method == "GET":
            # Non-billed meta/utility endpoints
            if (
                endpoint.startswith("/tweets/counts")
                or endpoint.startswith("/usage")
                or endpoint.startswith("/trends")
                or endpoint.startswith("/communities")
                or endpoint.startswith("/compliance")
                or endpoint.startswith("/webhooks")
                or endpoint.startswith("/account_activity")
                or endpoint.startswith("/connections")
                or endpoint.startswith("/media/analytics")
                or endpoint == "/users/personalized_trends"
                or endpoint.startswith("/spaces/search")
                or (endpoint.startswith("/spaces/") and endpoint.endswith("/buyers"))
            ):
                return None
            # Post reads — check tweet-returning endpoints before generic /users catch-all
            if (
                endpoint.startswith("/tweets")
                or endpoint.endswith("/liked_tweets")
                or endpoint.endswith("/tweets")
                or endpoint.endswith("/mentions")
                or "timelines" in endpoint
                or endpoint.endswith("/quote_tweets")
                or (endpoint.startswith("/lists/") and endpoint.endswith("/tweets"))
                or endpoint.startswith("/news")
            ):
                return "post_read"
            # User lookups
            if (
                endpoint.startswith("/users")
                or endpoint.endswith("/liking_users")
                or endpoint.endswith("/retweeted_by")
                or endpoint.endswith("/followers")
                or endpoint.endswith("/following")
                or (endpoint.startswith("/lists/") and endpoint.endswith("/members"))
                or (endpoint.startswith("/spaces/") and endpoint.endswith("/buyers"))
            ):
                return "user_lookup"
            # DM reads
            if "dm_conversations" in endpoint or endpoint.startswith("/dm_events"):
                return "dm_event_read"
        return None

    @staticmethod
    def _count_x_resources(operation_type: str, data: Optional[Dict]) -> int:
        """Count billable resources returned in X API response."""
        if operation_type in ("post_create", "user_interaction", "dm_create"):
            return 1
        if not data:
            return 0
        # Handle stream responses where top-level data is a list
        if isinstance(data, list):
            return len(data)
        items = data.get("data")
        if isinstance(items, list):
            return len(items)
        return 1 if items is not None else 0

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        credentials: TwitterCredential,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        action_name: str = "request",
    ) -> Dict[str, Any]:
        """Make an authenticated Twitter API request with timing."""
        total_start = time.time()

        access_token = await self._get_access_token(credentials)
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        url = f"{TWITTER_API_BASE}{endpoint}"

        # Filter out None params
        if params:
            params = {k: v for k, v in params.items() if v is not None}

        async with httpx.AsyncClient() as client:
            # API request timing
            api_start = time.time()
            logger.info(f"[TwitterNode] 🐦 {method} {endpoint}")

            try:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=json_body,
                    timeout=30.0,
                )
            except httpx.TimeoutException:
                total_time = (time.time() - total_start) * 1000
                output = {
                    "type": "twitter",
                    "action": action_name,
                    "status": "error",
                    "error": "Request timeout",
                    "status_code": 408,
                    "data": None,
                    "timestamp": time.time(),
                    "timing_ms": {"total": round(total_time, 1)},
                }
                await self.emit(output)
                return output

            api_time = (time.time() - api_start) * 1000
            logger.info(
                f"[TwitterNode] ⏱️ API request: {api_time:.1f}ms (status: {response.status_code})"
            )

            # Response parsing timing
            parse_start = time.time()

            if response.status_code >= 400:
                # Always log the raw response for 5xx errors to aid debugging
                if response.status_code >= 500:
                    logger.error(
                        f"[TwitterNode] Raw {response.status_code} response: headers={dict(response.headers)} body={response.text[:500]!r}"
                    )
                try:
                    error_data = response.json() if response.content else {}
                except Exception:
                    error_data = {}
                # Twitter API returns errors in different formats
                if "errors" in error_data:
                    error_msg = error_data["errors"][0].get("message", response.text)
                elif "detail" in error_data:
                    error_msg = error_data["detail"]
                elif "error" in error_data:
                    error_msg = error_data["error"]
                else:
                    error_msg = response.text

                # Translate opaque X portal errors into actionable messages
                if response.status_code == 403 and "attached to a Project" in error_msg:
                    error_msg = (
                        "Twitter app not enrolled in a Developer Project. "
                        "Go to developer.x.com → Projects & Apps, attach your app to a project, "
                        "then reconnect your Twitter account in NoClick."
                    )

                logger.error(f"[TwitterNode] API error: {error_msg}")

                total_time = (time.time() - total_start) * 1000
                output = {
                    "type": "twitter",
                    "action": action_name,
                    "status": "error",
                    "error": error_msg,
                    "status_code": response.status_code,
                    "data": None,
                    "timestamp": time.time(),
                    "timing_ms": {
                        "api_request": round(api_time, 1),
                        "total": round(total_time, 1),
                    },
                }
                await self.emit(output)
                return output

            # Parse successful response
            data = response.json() if response.content else None
            parse_time = (time.time() - parse_start) * 1000
            logger.info(f"[TwitterNode] ⏱️ Response parsing: {parse_time:.1f}ms")

            total_time = (time.time() - total_start) * 1000
            logger.info(f"[TwitterNode] ⏱️ TOTAL time: {total_time:.1f}ms")

            output = {
                "type": "twitter",
                "action": action_name,
                "status": "success",
                "data": data,
                "timestamp": time.time(),
                "timing_ms": {
                    "api_request": round(api_time, 1),
                    "response_parsing": round(parse_time, 1),
                    "total": round(total_time, 1),
                },
            }

            await self.emit(output)

            # Track X API pay-per-use cost
            operation_type = self._infer_x_operation(method, endpoint)
            if operation_type and self.user_id:
                quantity = self._count_x_resources(operation_type, data)
                if quantity > 0:
                    from decimal import Decimal
                    from billing.schema import UsageEventData
                    from billing.pricing import get_x_cost
                    from billing.markup import apply_x_markup
                    from billing.usage_tracker import usage_tracker

                    user_resource = self._is_user_resource(credentials)
                    total_cost = apply_x_markup(
                        get_x_cost(operation_type, quantity), user_resource
                    )
                    if total_cost > 0:
                        await usage_tracker.track_usage_event(
                            UsageEventData(
                                user_id=self.user_id,
                                total_cost=total_cost,
                                usage_type="api_usage",
                                usage_subtype="twitter/x_api",
                                quantity=Decimal(str(quantity)),
                                unit_type="requests",
                                user_resource=user_resource,
                                organization_id=self.organization_id,
                                metadata={
                                    "operation": operation_type,
                                    "endpoint": endpoint,
                                    "method": method,
                                    "action": action_name,
                                },
                            ),
                            sio=self.sio,
                            sid=self.sid,
                        )

            return output

    async def _get_authenticated_user_id(self, credentials: TwitterCredential) -> str:
        """Get the authenticated user's ID. Required for many write operations."""
        # Try to get from cached credentials first
        cached_id = self._get_user_id(credentials)
        if cached_id:
            return cached_id

        # Otherwise fetch from API
        result = await self._make_request(
            "GET", "/users/me", credentials, action_name="get_me_for_id"
        )

        if result["status"] == "error":
            raise ValueError(f"Failed to get authenticated user ID: {result['error']}")

        return result["data"]["data"]["id"]

    # ============================================================================
    # Tweet Actions
    # ============================================================================

    async def _create_tweet(
        self, config: TwitterCreateTweetConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Create a new tweet."""
        body: Dict[str, Any] = {"text": config.text}

        if config.reply_to_tweet_id:
            body["reply"] = {"in_reply_to_tweet_id": config.reply_to_tweet_id}

        if config.quote_tweet_id:
            body["quote_tweet_id"] = config.quote_tweet_id

        return await self._make_request(
            "POST", "/tweets", credentials, json_body=body, action_name="create_tweet"
        )

    async def _delete_tweet(
        self, config: TwitterDeleteTweetConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Delete a tweet."""
        return await self._make_request(
            "DELETE",
            f"/tweets/{config.tweet_id}",
            credentials,
            action_name="delete_tweet",
        )

    async def _get_tweet(
        self, config: TwitterGetTweetConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get a single tweet."""
        params = {}
        if config.tweet_fields:
            params["tweet.fields"] = config.tweet_fields
        if config.expansions:
            params["expansions"] = config.expansions

        return await self._make_request(
            "GET",
            f"/tweets/{config.tweet_id}",
            credentials,
            params=params if params else None,
            action_name="get_tweet_by_id",
        )

    async def _get_tweets(
        self, config: TwitterGetTweetsConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get multiple tweets."""
        params = {"ids": config.tweet_ids}
        if config.tweet_fields:
            params["tweet.fields"] = config.tweet_fields
        if config.expansions:
            params["expansions"] = config.expansions

        return await self._make_request(
            "GET",
            "/tweets",
            credentials,
            params=params,
            action_name="get_tweets_by_ids",
        )

    async def _search_recent_tweets(
        self, config: TwitterSearchRecentTweetsConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Search recent tweets."""
        params: Dict[str, Any] = {"query": config.query}
        if config.max_results:
            params["max_results"] = config.max_results
        if config.tweet_fields:
            params["tweet.fields"] = config.tweet_fields
        if config.expansions:
            params["expansions"] = config.expansions

        return await self._make_request(
            "GET",
            "/tweets/search/recent",
            credentials,
            params=params,
            action_name="search_recent_tweets",
        )

    # ============================================================================
    # User Actions
    # ============================================================================

    async def _get_user(
        self, config: TwitterGetUserConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get a user by ID or username. Automatically routes to the username endpoint
        when a non-numeric value (with or without leading @) is provided."""
        params = {}
        if config.user_fields:
            params["user.fields"] = config.user_fields

        user_id = config.user_id.strip()
        # Route to username endpoint if input starts with '@' or is non-numeric
        if user_id.startswith("@") or not user_id.isdigit():
            username = user_id.lstrip("@")
            return await self._make_request(
                "GET",
                f"/users/by/username/{username}",
                credentials,
                params=params if params else None,
                action_name="get_user_by_id",
            )

        return await self._make_request(
            "GET",
            f"/users/{user_id}",
            credentials,
            params=params if params else None,
            action_name="get_user_by_id",
        )

    async def _get_user_by_username(
        self, config: TwitterGetUserByUsernameConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get a user by username."""
        params = {}
        if config.user_fields:
            params["user.fields"] = config.user_fields

        return await self._make_request(
            "GET",
            f"/users/by/username/{config.username}",
            credentials,
            params=params if params else None,
            action_name="get_user_by_username",
        )

    async def _get_me(
        self, config: TwitterGetMeConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get the authenticated user."""
        params = {}
        if config.user_fields:
            params["user.fields"] = config.user_fields

        return await self._make_request(
            "GET",
            "/users/me",
            credentials,
            params=params if params else None,
            action_name="get_authenticated_user",
        )

    async def _get_users(
        self, config: TwitterGetUsersConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get multiple users by IDs."""
        params = {"ids": config.user_ids}
        if config.user_fields:
            params["user.fields"] = config.user_fields

        return await self._make_request(
            "GET", "/users", credentials, params=params, action_name="get_users_by_ids"
        )

    # ============================================================================
    # Like Actions
    # ============================================================================

    async def _like_tweet(
        self, config: TwitterLikeTweetConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Like a tweet."""
        user_id = await self._get_authenticated_user_id(credentials)
        body = {"tweet_id": config.tweet_id}

        return await self._make_request(
            "POST",
            f"/users/{user_id}/likes",
            credentials,
            json_body=body,
            action_name="like_tweet",
        )

    async def _unlike_tweet(
        self, config: TwitterUnlikeTweetConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Unlike a tweet."""
        user_id = await self._get_authenticated_user_id(credentials)

        return await self._make_request(
            "DELETE",
            f"/users/{user_id}/likes/{config.tweet_id}",
            credentials,
            action_name="unlike_tweet",
        )

    async def _get_liked_tweets(
        self, config: TwitterGetLikedTweetsConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get tweets liked by a user."""
        params: Dict[str, Any] = {}
        if config.max_results:
            params["max_results"] = config.max_results
        if config.tweet_fields:
            params["tweet.fields"] = config.tweet_fields

        return await self._make_request(
            "GET",
            f"/users/{config.user_id}/liked_tweets",
            credentials,
            params=params if params else None,
            action_name="get_user_liked_tweets",
        )

    async def _get_liking_users(
        self, config: TwitterGetLikingUsersConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get users who liked a tweet."""
        params: Dict[str, Any] = {}
        if config.max_results:
            params["max_results"] = config.max_results
        if config.user_fields:
            params["user.fields"] = config.user_fields

        return await self._make_request(
            "GET",
            f"/tweets/{config.tweet_id}/liking_users",
            credentials,
            params=params if params else None,
            action_name="get_users_who_liked_tweet",
        )

    # ============================================================================
    # Retweet Actions
    # ============================================================================

    async def _retweet(
        self, config: TwitterRetweetConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Retweet a tweet."""
        user_id = await self._get_authenticated_user_id(credentials)
        body = {"tweet_id": config.tweet_id}

        return await self._make_request(
            "POST",
            f"/users/{user_id}/retweets",
            credentials,
            json_body=body,
            action_name="retweet_tweet",
        )

    async def _undo_retweet(
        self, config: TwitterUndoRetweetConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Undo a retweet."""
        user_id = await self._get_authenticated_user_id(credentials)

        return await self._make_request(
            "DELETE",
            f"/users/{user_id}/retweets/{config.tweet_id}",
            credentials,
            action_name="undo_retweet",
        )

    async def _get_retweeters(
        self, config: TwitterGetRetweetersConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get users who retweeted a tweet."""
        params: Dict[str, Any] = {}
        if config.max_results:
            params["max_results"] = config.max_results
        if config.user_fields:
            params["user.fields"] = config.user_fields

        return await self._make_request(
            "GET",
            f"/tweets/{config.tweet_id}/retweeted_by",
            credentials,
            params=params if params else None,
            action_name="get_tweet_retweeters",
        )

    # ============================================================================
    # Follow Actions
    # ============================================================================

    async def _follow_user(
        self, config: TwitterFollowUserConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Follow a user."""
        user_id = await self._get_authenticated_user_id(credentials)
        body = {"target_user_id": config.target_user_id}

        return await self._make_request(
            "POST",
            f"/users/{user_id}/following",
            credentials,
            json_body=body,
            action_name="follow_user",
        )

    async def _unfollow_user(
        self, config: TwitterUnfollowUserConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Unfollow a user."""
        user_id = await self._get_authenticated_user_id(credentials)

        return await self._make_request(
            "DELETE",
            f"/users/{user_id}/following/{config.target_user_id}",
            credentials,
            action_name="unfollow_user",
        )

    async def _get_followers(
        self, config: TwitterGetFollowersConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get followers of a user."""
        params: Dict[str, Any] = {}
        if config.max_results:
            params["max_results"] = config.max_results
        if config.user_fields:
            params["user.fields"] = config.user_fields

        return await self._make_request(
            "GET",
            f"/users/{config.user_id}/followers",
            credentials,
            params=params if params else None,
            action_name="get_user_followers",
        )

    async def _get_following(
        self, config: TwitterGetFollowingConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get users followed by a user."""
        params: Dict[str, Any] = {}
        if config.max_results:
            params["max_results"] = config.max_results
        if config.user_fields:
            params["user.fields"] = config.user_fields

        return await self._make_request(
            "GET",
            f"/users/{config.user_id}/following",
            credentials,
            params=params if params else None,
            action_name="get_users_followed_by_user",
        )

    # ============================================================================
    # Block Actions
    # ============================================================================

    async def _block_user(
        self, config: TwitterBlockUserConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Block a user."""
        user_id = await self._get_authenticated_user_id(credentials)
        body = {"target_user_id": config.target_user_id}

        return await self._make_request(
            "POST",
            f"/users/{user_id}/blocking",
            credentials,
            json_body=body,
            action_name="block_user",
        )

    async def _unblock_user(
        self, config: TwitterUnblockUserConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Unblock a user."""
        user_id = await self._get_authenticated_user_id(credentials)

        return await self._make_request(
            "DELETE",
            f"/users/{user_id}/blocking/{config.target_user_id}",
            credentials,
            action_name="unblock_user",
        )

    async def _get_blocked_users(
        self, config: TwitterGetBlockedUsersConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get blocked users."""
        user_id = await self._get_authenticated_user_id(credentials)
        params: Dict[str, Any] = {}
        if config.max_results:
            params["max_results"] = config.max_results
        if config.user_fields:
            params["user.fields"] = config.user_fields

        return await self._make_request(
            "GET",
            f"/users/{user_id}/blocking",
            credentials,
            params=params if params else None,
            action_name="get_blocked_users",
        )

    # ============================================================================
    # Mute Actions
    # ============================================================================

    async def _mute_user(
        self, config: TwitterMuteUserConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Mute a user."""
        user_id = await self._get_authenticated_user_id(credentials)
        body = {"target_user_id": config.target_user_id}

        return await self._make_request(
            "POST",
            f"/users/{user_id}/muting",
            credentials,
            json_body=body,
            action_name="mute_user",
        )

    async def _unmute_user(
        self, config: TwitterUnmuteUserConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Unmute a user."""
        user_id = await self._get_authenticated_user_id(credentials)

        return await self._make_request(
            "DELETE",
            f"/users/{user_id}/muting/{config.target_user_id}",
            credentials,
            action_name="unmute_user",
        )

    async def _get_muted_users(
        self, config: TwitterGetMutedUsersConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get muted users."""
        user_id = await self._get_authenticated_user_id(credentials)
        params: Dict[str, Any] = {}
        if config.max_results:
            params["max_results"] = config.max_results
        if config.user_fields:
            params["user.fields"] = config.user_fields

        return await self._make_request(
            "GET",
            f"/users/{user_id}/muting",
            credentials,
            params=params if params else None,
            action_name="get_muted_users",
        )

    # ============================================================================
    # Bookmark Actions
    # ============================================================================

    async def _add_bookmark(
        self, config: TwitterAddBookmarkConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Add a tweet to bookmarks."""
        user_id = await self._get_authenticated_user_id(credentials)
        body = {"tweet_id": config.tweet_id}

        return await self._make_request(
            "POST",
            f"/users/{user_id}/bookmarks",
            credentials,
            json_body=body,
            action_name="add_tweet_to_bookmarks",
        )

    async def _remove_bookmark(
        self, config: TwitterRemoveBookmarkConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Remove a tweet from bookmarks."""
        user_id = await self._get_authenticated_user_id(credentials)

        return await self._make_request(
            "DELETE",
            f"/users/{user_id}/bookmarks/{config.tweet_id}",
            credentials,
            action_name="remove_tweet_from_bookmarks",
        )

    async def _get_bookmarks(
        self, config: TwitterGetBookmarksConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get bookmarked tweets."""
        user_id = await self._get_authenticated_user_id(credentials)
        params: Dict[str, Any] = {}
        if config.max_results:
            params["max_results"] = config.max_results
        if config.tweet_fields:
            params["tweet.fields"] = config.tweet_fields

        return await self._make_request(
            "GET",
            f"/users/{user_id}/bookmarks",
            credentials,
            params=params if params else None,
            action_name="get_bookmarked_tweets",
        )

    # ============================================================================
    # Direct Message Actions
    # ============================================================================

    async def _create_dm_conversation(
        self, config: TwitterCreateDMConversationConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Create a group Direct Message conversation."""
        participant_ids = [pid.strip() for pid in config.participant_ids.split(",")]
        body = {
            "conversation_type": "Group",
            "participant_ids": participant_ids,
            "message": {"text": config.message_text},
        }

        return await self._make_request(
            "POST",
            "/dm_conversations",
            credentials,
            json_body=body,
            action_name="create_group_direct_message_conversation",
        )

    async def _send_dm(
        self, config: TwitterSendDMConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Send a one-to-one Direct Message."""
        body = {"text": config.message_text}

        return await self._make_request(
            "POST",
            f"/dm_conversations/with/{config.participant_id}/messages",
            credentials,
            json_body=body,
            action_name="send_direct_message",
        )

    async def _send_dm_to_conversation(
        self, config: TwitterSendDMToConversationConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Send a message to an existing conversation."""
        body = {"text": config.message_text}

        return await self._make_request(
            "POST",
            f"/dm_conversations/{config.conversation_id}/messages",
            credentials,
            json_body=body,
            action_name="send_direct_message_to_conversation",
        )

    async def _get_dm_conversation(
        self, config: TwitterGetDMConversationConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get DM conversation events with a specific user."""
        params: Dict[str, Any] = {}
        if config.max_results:
            params["max_results"] = config.max_results

        return await self._make_request(
            "GET",
            f"/dm_conversations/with/{config.participant_id}/dm_events",
            credentials,
            params=params if params else None,
            action_name="get_direct_message_conversation_with_user",
        )

    async def _get_dm_events(
        self, config: TwitterGetDMEventsConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get DM events for a specific conversation ID."""
        params: Dict[str, Any] = {}
        if config.max_results:
            params["max_results"] = config.max_results

        return await self._make_request(
            "GET",
            f"/dm_conversations/{config.conversation_id}/dm_events",
            credentials,
            params=params if params else None,
            action_name="get_direct_message_events_for_conversation",
        )

    async def _get_all_dm_events(
        self, config: TwitterGetAllDMEventsConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get all DM events for the authenticated user."""
        params: Dict[str, Any] = {}
        if config.max_results:
            params["max_results"] = config.max_results
        if config.dm_event_fields:
            params["dm_event.fields"] = config.dm_event_fields

        return await self._make_request(
            "GET",
            "/dm_events",
            credentials,
            params=params if params else None,
            action_name="get_all_direct_message_events",
        )

    # ============================================================================
    # List Actions
    # ============================================================================

    async def _create_list(
        self, config: TwitterCreateListConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Create a new list."""
        body: Dict[str, Any] = {"name": config.name}
        if config.description:
            body["description"] = config.description
        if config.private is not None:
            body["private"] = config.private

        return await self._make_request(
            "POST", "/lists", credentials, json_body=body, action_name="create_list"
        )

    async def _delete_list(
        self, config: TwitterDeleteListConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Delete a list."""
        return await self._make_request(
            "DELETE", f"/lists/{config.list_id}", credentials, action_name="delete_list"
        )

    async def _update_list(
        self, config: TwitterUpdateListConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Update list metadata."""
        body: Dict[str, Any] = {}
        if config.name:
            body["name"] = config.name
        if config.description is not None:
            body["description"] = config.description
        if config.private is not None:
            body["private"] = config.private

        return await self._make_request(
            "PUT",
            f"/lists/{config.list_id}",
            credentials,
            json_body=body if body else None,
            action_name="update_list_metadata",
        )

    async def _get_list(
        self, config: TwitterGetListConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get a list by ID."""
        params: Dict[str, Any] = {}
        if config.list_fields:
            params["list.fields"] = config.list_fields

        return await self._make_request(
            "GET",
            f"/lists/{config.list_id}",
            credentials,
            params=params if params else None,
            action_name="get_list_by_id",
        )

    async def _get_user_owned_lists(
        self, config: TwitterGetUserOwnedListsConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get lists owned by a user."""
        params: Dict[str, Any] = {}
        if config.max_results:
            params["max_results"] = config.max_results

        return await self._make_request(
            "GET",
            f"/users/{config.user_id}/owned_lists",
            credentials,
            params=params if params else None,
            action_name="get_user_owned_lists",
        )

    async def _get_user_list_memberships(
        self,
        config: TwitterGetUserListMembershipsConfig,
        credentials: TwitterCredential,
    ) -> Dict[str, Any]:
        """Get lists a user is a member of."""
        params: Dict[str, Any] = {}
        if config.max_results:
            params["max_results"] = config.max_results

        return await self._make_request(
            "GET",
            f"/users/{config.user_id}/list_memberships",
            credentials,
            params=params if params else None,
            action_name="get_user_list_memberships",
        )

    async def _get_list_tweets(
        self, config: TwitterGetListTweetsConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get tweets from a list."""
        params: Dict[str, Any] = {}
        if config.max_results:
            params["max_results"] = config.max_results
        if config.tweet_fields:
            params["tweet.fields"] = config.tweet_fields

        return await self._make_request(
            "GET",
            f"/lists/{config.list_id}/tweets",
            credentials,
            params=params if params else None,
            action_name="get_tweets_from_list",
        )

    async def _add_list_member(
        self, config: TwitterAddListMemberConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Add a member to a list."""
        body = {"user_id": config.user_id}

        return await self._make_request(
            "POST",
            f"/lists/{config.list_id}/members",
            credentials,
            json_body=body,
            action_name="add_member_to_list",
        )

    async def _remove_list_member(
        self, config: TwitterRemoveListMemberConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Remove a member from a list."""
        return await self._make_request(
            "DELETE",
            f"/lists/{config.list_id}/members/{config.user_id}",
            credentials,
            action_name="remove_member_from_list",
        )

    async def _get_list_members(
        self, config: TwitterGetListMembersConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get members of a list."""
        params: Dict[str, Any] = {}
        if config.max_results:
            params["max_results"] = config.max_results

        return await self._make_request(
            "GET",
            f"/lists/{config.list_id}/members",
            credentials,
            params=params if params else None,
            action_name="get_list_members",
        )

    async def _pin_list(
        self, config: TwitterPinListConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Pin a list."""
        user_id = await self._get_authenticated_user_id(credentials)
        body = {"list_id": config.list_id}

        return await self._make_request(
            "POST",
            f"/users/{user_id}/pinned_lists",
            credentials,
            json_body=body,
            action_name="pin_list",
        )

    async def _unpin_list(
        self, config: TwitterUnpinListConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Unpin a list."""
        user_id = await self._get_authenticated_user_id(credentials)

        return await self._make_request(
            "DELETE",
            f"/users/{user_id}/pinned_lists/{config.list_id}",
            credentials,
            action_name="unpin_list",
        )

    async def _get_pinned_lists(
        self, config: TwitterGetPinnedListsConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get pinned lists."""
        return await self._make_request(
            "GET",
            f"/users/{config.user_id}/pinned_lists",
            credentials,
            action_name="get_user_pinned_lists",
        )

    # ============================================================================
    # Space Actions
    # ============================================================================

    async def _get_space(
        self, config: TwitterGetSpaceConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get a Space by ID."""
        params: Dict[str, Any] = {}
        if config.space_fields:
            params["space.fields"] = config.space_fields

        return await self._make_request(
            "GET",
            f"/spaces/{config.space_id}",
            credentials,
            params=params if params else None,
            action_name="get_space_by_id",
        )

    async def _get_spaces(
        self, config: TwitterGetSpacesConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get multiple Spaces by IDs."""
        params: Dict[str, Any] = {"ids": config.space_ids}
        if config.space_fields:
            params["space.fields"] = config.space_fields

        return await self._make_request(
            "GET",
            "/spaces",
            credentials,
            params=params,
            action_name="get_spaces_by_ids",
        )

    async def _get_spaces_by_creators(
        self, config: TwitterGetSpacesByCreatorsConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get Spaces by creator user IDs."""
        params: Dict[str, Any] = {"user_ids": config.user_ids}
        if config.space_fields:
            params["space.fields"] = config.space_fields

        return await self._make_request(
            "GET",
            "/spaces/by/creator_ids",
            credentials,
            params=params,
            action_name="get_spaces_by_creator_user_ids",
        )

    # ============================================================================
    # Media Upload Actions
    # ============================================================================

    async def _upload_media(
        self, config: TwitterUploadMediaConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Upload media (simple upload for small files)."""
        import base64
        from nodes.core.media_resolver import resolve_media_input

        # Resolve the media input (resource_id / URL / data URI / base64) to bytes
        try:
            media_bytes = (
                await resolve_media_input(
                    config.media_data, default_mime=config.media_type or "application/octet-stream"
                )
            ).data
        except ValueError as e:
            return {
                "type": "twitter",
                "action": "upload_media",
                "status": "error",
                "error": f"Could not load media: {str(e)}",
                "data": None,
                "timestamp": time.time(),
            }

        # Encode media as base64 for API
        media_b64 = base64.b64encode(media_bytes).decode("utf-8")

        body = {"media_data": media_b64, "media_type": config.media_type}

        return await self._make_request(
            "POST",
            "/media/upload",
            credentials,
            json_body=body,
            action_name="upload_media",
        )

    async def _upload_media_chunked(
        self, config: TwitterUploadMediaChunkedConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Upload large media using chunked upload."""
        import base64
        from nodes.core.media_resolver import resolve_media_input

        # Resolve the media input (resource_id / URL / data URI / base64) to bytes
        try:
            media_bytes = (
                await resolve_media_input(
                    config.media_data, default_mime=config.media_type or "application/octet-stream"
                )
            ).data
        except ValueError as e:
            return {
                "type": "twitter",
                "action": "upload_media_chunked",
                "status": "error",
                "error": f"Could not load media: {str(e)}",
                "data": None,
                "timestamp": time.time(),
            }

        total_bytes = len(media_bytes)
        chunk_size = 5 * 1024 * 1024  # 5MB chunks

        # INIT phase
        init_body = {
            "command": "INIT",
            "total_bytes": total_bytes,
            "media_type": config.media_type,
            "media_category": config.media_category,
        }

        init_result = await self._make_request(
            "POST",
            "/media/upload",
            credentials,
            json_body=init_body,
            action_name="upload_media_init",
        )

        if init_result["status"] == "error":
            return init_result

        media_id = init_result["data"].get("media_id_string")
        if not media_id:
            return {
                "type": "twitter",
                "action": "upload_media_chunked",
                "status": "error",
                "error": "No media_id returned from INIT",
                "data": None,
                "timestamp": time.time(),
            }

        # APPEND phase
        segment_index = 0
        for i in range(0, total_bytes, chunk_size):
            chunk = media_bytes[i : i + chunk_size]
            chunk_b64 = base64.b64encode(chunk).decode("utf-8")

            append_body = {
                "command": "APPEND",
                "media_id": media_id,
                "media_data": chunk_b64,
                "segment_index": segment_index,
            }

            append_result = await self._make_request(
                "POST",
                "/media/upload",
                credentials,
                json_body=append_body,
                action_name=f"upload_media_append_{segment_index}",
            )

            if append_result["status"] == "error":
                return append_result

            segment_index += 1

        # FINALIZE phase
        finalize_body = {"command": "FINALIZE", "media_id": media_id}

        return await self._make_request(
            "POST",
            "/media/upload",
            credentials,
            json_body=finalize_body,
            action_name="upload_media_finalize",
        )

    # ============================================================================
    # Timeline Actions
    # ============================================================================

    async def _get_user_tweets(
        self, config: TwitterGetUserTweetsConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get tweets posted by a user."""
        params: Dict[str, Any] = {}
        if config.max_results:
            params["max_results"] = config.max_results
        if config.tweet_fields:
            params["tweet.fields"] = config.tweet_fields
        if config.exclude:
            params["exclude"] = config.exclude

        return await self._make_request(
            "GET",
            f"/users/{config.user_id}/tweets",
            credentials,
            params=params if params else None,
            action_name="get_tweets_posted_by_user",
        )

    async def _get_user_mentions(
        self, config: TwitterGetUserMentionsConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get tweets mentioning a user."""
        params: Dict[str, Any] = {}
        if config.max_results:
            params["max_results"] = config.max_results
        if config.tweet_fields:
            params["tweet.fields"] = config.tweet_fields

        return await self._make_request(
            "GET",
            f"/users/{config.user_id}/mentions",
            credentials,
            params=params if params else None,
            action_name="get_tweets_mentioning_user",
        )

    async def _get_home_timeline(
        self, config: TwitterGetHomeTimelineConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get reverse chronological home timeline."""
        user_id = await self._get_authenticated_user_id(credentials)
        params: Dict[str, Any] = {}
        if config.max_results:
            params["max_results"] = config.max_results
        if config.tweet_fields:
            params["tweet.fields"] = config.tweet_fields

        return await self._make_request(
            "GET",
            f"/users/{user_id}/timelines/reverse_chronological",
            credentials,
            params=params if params else None,
            action_name="get_home_timeline",
        )

    # ============================================================================
    # Quote Tweet Actions
    # ============================================================================

    async def _get_quote_tweets(
        self, config: TwitterGetQuoteTweetsConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get tweets that quote a specific tweet."""
        params: Dict[str, Any] = {}
        if config.max_results:
            params["max_results"] = config.max_results
        if config.tweet_fields:
            params["tweet.fields"] = config.tweet_fields

        return await self._make_request(
            "GET",
            f"/tweets/{config.tweet_id}/quote_tweets",
            credentials,
            params=params if params else None,
            action_name="get_tweets_quoting_tweet",
        )

    # ============================================================================
    # Hide Reply Actions
    # ============================================================================

    async def _hide_reply(
        self, config: TwitterHideReplyConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Hide a reply to a tweet."""
        body = {"hidden": True}

        return await self._make_request(
            "PUT",
            f"/tweets/{config.tweet_id}/hidden",
            credentials,
            json_body=body,
            action_name="hide_reply_to_tweet",
        )

    async def _unhide_reply(
        self, config: TwitterUnhideReplyConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Unhide a reply to a tweet."""
        body = {"hidden": False}

        return await self._make_request(
            "PUT",
            f"/tweets/{config.tweet_id}/hidden",
            credentials,
            json_body=body,
            action_name="unhide_reply_to_tweet",
        )

    # ============================================================================
    # Additional Tweet Actions
    # ============================================================================

    async def _search_all_tweets(
        self, config: TwitterSearchAllTweetsConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Search all tweets (full archive, Enterprise)."""
        params: Dict[str, Any] = {"query": config.query}
        if config.max_results:
            params["max_results"] = config.max_results
        if config.tweet_fields:
            params["tweet.fields"] = config.tweet_fields
        if config.expansions:
            params["expansions"] = config.expansions
        if config.start_time:
            params["start_time"] = config.start_time
        if config.end_time:
            params["end_time"] = config.end_time

        return await self._make_request(
            "GET",
            "/tweets/search/all",
            credentials,
            params=params,
            action_name="search_all_tweets_full_archive",
        )

    async def _get_tweet_counts_recent(
        self, config: TwitterGetTweetCountsRecentConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get tweet counts for recent tweets (last 7 days)."""
        params: Dict[str, Any] = {"query": config.query}
        if config.granularity:
            params["granularity"] = config.granularity
        if config.start_time:
            params["start_time"] = config.start_time
        if config.end_time:
            params["end_time"] = config.end_time

        return await self._make_request(
            "GET",
            "/tweets/counts/recent",
            credentials,
            params=params,
            action_name="get_tweet_counts_recent",
        )

    async def _get_tweet_counts_all(
        self, config: TwitterGetTweetCountsAllConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get tweet counts for full archive (Enterprise only)."""
        params: Dict[str, Any] = {"query": config.query}
        if config.granularity:
            params["granularity"] = config.granularity
        if config.start_time:
            params["start_time"] = config.start_time
        if config.end_time:
            params["end_time"] = config.end_time

        return await self._make_request(
            "GET",
            "/tweets/counts/all",
            credentials,
            params=params,
            action_name="get_tweet_counts_full_archive",
        )

    async def _get_tweet_analytics(
        self, config: TwitterGetTweetAnalyticsConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get analytics for tweets."""
        params: Dict[str, Any] = {"ids": config.tweet_ids}
        if config.start_time:
            params["start_time"] = config.start_time
        if config.end_time:
            params["end_time"] = config.end_time

        return await self._make_request(
            "GET",
            "/tweets/analytics",
            credentials,
            params=params,
            action_name="get_tweet_analytics",
        )

    async def _get_retweets(
        self, config: TwitterGetRetweetsConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get retweets of a tweet."""
        params: Dict[str, Any] = {}
        if config.max_results:
            params["max_results"] = config.max_results
        if config.tweet_fields:
            params["tweet.fields"] = config.tweet_fields

        return await self._make_request(
            "GET",
            f"/tweets/{config.tweet_id}/retweets",
            credentials,
            params=params if params else None,
            action_name="get_tweet_retweets",
        )

    # ============================================================================
    # Additional User Actions
    # ============================================================================

    async def _get_users_by_usernames(
        self, config: TwitterGetUsersByUsernamesConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get multiple users by usernames."""
        params: Dict[str, Any] = {"usernames": config.usernames}
        if config.user_fields:
            params["user.fields"] = config.user_fields

        return await self._make_request(
            "GET",
            "/users/by",
            credentials,
            params=params,
            action_name="get_users_by_usernames",
        )

    async def _search_users(
        self, config: TwitterSearchUsersConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Search for users."""
        params: Dict[str, Any] = {"query": config.query}
        if config.max_results:
            params["max_results"] = config.max_results
        if config.user_fields:
            params["user.fields"] = config.user_fields

        return await self._make_request(
            "GET",
            "/users/search",
            credentials,
            params=params,
            action_name="search_users",
        )

    # ============================================================================
    # Additional DM Actions
    # ============================================================================

    async def _delete_dm_event(
        self, config: TwitterDeleteDMEventConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Delete a DM event."""
        return await self._make_request(
            "DELETE",
            f"/dm_events/{config.event_id}",
            credentials,
            action_name="delete_direct_message_event",
        )

    async def _get_dm_event(
        self, config: TwitterGetDMEventConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get a specific DM event by ID."""
        params: Dict[str, Any] = {}
        if config.dm_event_fields:
            params["dm_event.fields"] = config.dm_event_fields

        return await self._make_request(
            "GET",
            f"/dm_events/{config.event_id}",
            credentials,
            params=params if params else None,
            action_name="get_direct_message_event_by_id",
        )

    async def _block_dms(
        self, config: TwitterBlockDMsConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Block DMs from a user."""
        user_id = await self._get_authenticated_user_id(credentials)
        body = {"target_user_id": config.target_user_id}

        return await self._make_request(
            "POST",
            f"/users/{user_id}/dm/block",
            credentials,
            json_body=body,
            action_name="block_user_dms",
        )

    async def _unblock_dms(
        self, config: TwitterUnblockDMsConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Unblock DMs from a user."""
        user_id = await self._get_authenticated_user_id(credentials)
        body = {"target_user_id": config.target_user_id}

        return await self._make_request(
            "POST",
            f"/users/{user_id}/dm/unblock",
            credentials,
            json_body=body,
            action_name="unblock_user_dms",
        )

    # ============================================================================
    # Additional List Actions
    # ============================================================================

    async def _get_list_followers(
        self, config: TwitterGetListFollowersConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get followers of a list."""
        params: Dict[str, Any] = {}
        if config.max_results:
            params["max_results"] = config.max_results
        if config.user_fields:
            params["user.fields"] = config.user_fields

        return await self._make_request(
            "GET",
            f"/lists/{config.list_id}/followers",
            credentials,
            params=params if params else None,
            action_name="get_list_followers",
        )

    async def _get_followed_lists(
        self, config: TwitterGetFollowedListsConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get lists followed by a user."""
        params: Dict[str, Any] = {}
        if config.max_results:
            params["max_results"] = config.max_results

        return await self._make_request(
            "GET",
            f"/users/{config.user_id}/followed_lists",
            credentials,
            params=params if params else None,
            action_name="get_lists_followed_by_user",
        )

    async def _follow_list(
        self, config: TwitterFollowListConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Follow a list."""
        user_id = await self._get_authenticated_user_id(credentials)
        body = {"list_id": config.list_id}

        return await self._make_request(
            "POST",
            f"/users/{user_id}/followed_lists",
            credentials,
            json_body=body,
            action_name="follow_list",
        )

    async def _unfollow_list(
        self, config: TwitterUnfollowListConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Unfollow a list."""
        user_id = await self._get_authenticated_user_id(credentials)

        return await self._make_request(
            "DELETE",
            f"/users/{user_id}/followed_lists/{config.list_id}",
            credentials,
            action_name="unfollow_list",
        )

    # ============================================================================
    # Additional Space Actions
    # ============================================================================

    async def _search_spaces(
        self, config: TwitterSearchSpacesConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Search for Spaces."""
        params: Dict[str, Any] = {"query": config.query}
        if config.max_results:
            params["max_results"] = config.max_results
        if config.space_fields:
            params["space.fields"] = config.space_fields

        return await self._make_request(
            "GET",
            "/spaces/search",
            credentials,
            params=params,
            action_name="search_spaces",
        )

    async def _get_space_tweets(
        self, config: TwitterGetSpaceTweetsConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get tweets from a Space."""
        params: Dict[str, Any] = {}
        if config.tweet_fields:
            params["tweet.fields"] = config.tweet_fields

        return await self._make_request(
            "GET",
            f"/spaces/{config.space_id}/tweets",
            credentials,
            params=params if params else None,
            action_name="get_tweets_from_space",
        )

    async def _get_space_buyers(
        self, config: TwitterGetSpaceBuyersConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get buyers (ticket holders) of a Space."""
        params: Dict[str, Any] = {}
        if config.user_fields:
            params["user.fields"] = config.user_fields

        return await self._make_request(
            "GET",
            f"/spaces/{config.space_id}/buyers",
            credentials,
            params=params if params else None,
            action_name="get_space_ticket_holders",
        )

    # ============================================================================
    # Bookmark Folder Actions
    # ============================================================================

    async def _get_bookmark_folders(
        self, config: TwitterGetBookmarkFoldersConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get bookmark folders for the authenticated user."""
        user_id = await self._get_authenticated_user_id(credentials)

        return await self._make_request(
            "GET",
            f"/users/{user_id}/bookmarks/folders",
            credentials,
            action_name="get_bookmark_folders",
        )

    # ============================================================================
    # Additional Media Actions
    # ============================================================================

    async def _get_media_upload_status(
        self, config: TwitterGetMediaUploadStatusConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get the upload status of media."""
        params: Dict[str, Any] = {"media_id": config.media_id}

        return await self._make_request(
            "GET",
            "/media/upload/status",
            credentials,
            params=params,
            action_name="get_media_upload_status",
        )

    async def _create_media_metadata(
        self, config: TwitterCreateMediaMetadataConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Create metadata for uploaded media."""
        body: Dict[str, Any] = {"media_id": config.media_id}
        if config.alt_text:
            body["alt_text"] = {"text": config.alt_text}
        if config.sensitive_media_warnings:
            warnings = [w.strip() for w in config.sensitive_media_warnings.split(",")]
            body["sensitive_media_warnings"] = warnings

        return await self._make_request(
            "POST",
            "/media/metadata",
            credentials,
            json_body=body,
            action_name="create_media_metadata",
        )

    async def _create_media_subtitles(
        self, config: TwitterCreateMediaSubtitlesConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Create subtitles for media."""
        body: Dict[str, Any] = {
            "media_id": config.media_id,
            "subtitle_data": config.subtitle_data,
            "language_code": config.language_code,
        }
        if config.display_name:
            body["display_name"] = config.display_name

        return await self._make_request(
            "POST",
            "/media/subtitles",
            credentials,
            json_body=body,
            action_name="create_media_subtitles",
        )

    async def _delete_media_subtitles(
        self, config: TwitterDeleteMediaSubtitlesConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Delete subtitles from media."""
        body: Dict[str, Any] = {
            "media_id": config.media_id,
            "language_code": config.language_code,
        }

        return await self._make_request(
            "DELETE",
            "/media/subtitles",
            credentials,
            json_body=body,
            action_name="delete_media_subtitles",
        )

    async def _get_media_analytics(
        self, config: TwitterGetMediaAnalyticsConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get analytics for media."""
        params: Dict[str, Any] = {"media_keys": config.media_keys}
        if config.start_time:
            params["start_time"] = config.start_time
        if config.end_time:
            params["end_time"] = config.end_time

        return await self._make_request(
            "GET",
            "/media/analytics",
            credentials,
            params=params,
            action_name="get_media_analytics",
        )

    # ============================================================================
    # Filtered Stream Actions
    # ============================================================================

    async def _get_filtered_stream(
        self, config: TwitterGetFilteredStreamConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Connect to filtered stream and collect tweets."""
        import asyncio

        access_token = await self._get_access_token(credentials)
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        params: Dict[str, Any] = {}
        if config.tweet_fields:
            params["tweet.fields"] = config.tweet_fields
        if config.expansions:
            params["expansions"] = config.expansions

        events: list = []
        timeout_seconds = config.timeout_seconds or 30
        max_events = config.max_events or 10

        try:
            async with httpx.AsyncClient() as client:
                async with client.stream(
                    "GET",
                    f"{TWITTER_API_BASE}/tweets/search/stream",
                    headers=headers,
                    params=params,
                    timeout=timeout_seconds + 5,
                ) as response:
                    if response.status_code >= 400:
                        error_text = await response.aread()
                        output = {
                            "type": "twitter",
                            "action": "collect_filtered_stream_tweets",
                            "status": "error",
                            "error": error_text.decode()[:400],
                            "status_code": response.status_code,
                            "data": None,
                            "timestamp": time.time(),
                        }
                        await self.emit(output)
                        return output

                    start = time.time()
                    async for line in response.aiter_lines():
                        if time.time() - start > timeout_seconds:
                            break
                        if len(events) >= max_events:
                            break
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            tweet = json.loads(line)
                            if "data" in tweet:
                                events.append(tweet)
                        except Exception:
                            pass
        except httpx.TimeoutException:
            pass

        output = {
            "type": "twitter",
            "action": "collect_filtered_stream_tweets",
            "status": "success",
            "data": {"data": events, "meta": {"result_count": len(events)}},
            "timestamp": time.time(),
        }
        await self.emit(output)
        return output

    async def _get_stream_rules(
        self, config: TwitterGetStreamRulesConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get stream filter rules."""
        params: Dict[str, Any] = {}
        if config.rule_ids:
            params["ids"] = config.rule_ids

        return await self._make_request(
            "GET",
            "/tweets/search/stream/rules",
            credentials,
            params=params if params else None,
            action_name="get_stream_filter_rules",
        )

    async def _add_stream_rules(
        self, config: TwitterAddStreamRulesConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Add stream filter rules."""
        rules_list = [r.strip() for r in config.rules.split(",")]
        tags_list = [t.strip() for t in config.tags.split(",")] if config.tags else []

        add_rules = []
        for i, rule in enumerate(rules_list):
            rule_obj: Dict[str, Any] = {"value": rule}
            if i < len(tags_list) and tags_list[i]:
                rule_obj["tag"] = tags_list[i]
            add_rules.append(rule_obj)

        body = {"add": add_rules}

        return await self._make_request(
            "POST",
            "/tweets/search/stream/rules",
            credentials,
            json_body=body,
            action_name="add_stream_filter_rules",
        )

    async def _delete_stream_rules(
        self, config: TwitterDeleteStreamRulesConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Delete stream filter rules by ID."""
        rule_ids = [rid.strip() for rid in config.rule_ids.split(",")]
        body = {"delete": {"ids": rule_ids}}

        return await self._make_request(
            "POST",
            "/tweets/search/stream/rules",
            credentials,
            json_body=body,
            action_name="delete_stream_filter_rules",
        )

    async def _get_stream_rule_counts(
        self, config: TwitterGetStreamRuleCountsConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get stream rule counts."""
        return await self._make_request(
            "GET",
            "/tweets/search/stream/rules/counts",
            credentials,
            action_name="get_stream_rule_counts",
        )

    # ============================================================================
    # Sampled Stream Actions
    # ============================================================================

    async def _get_sampled_stream(
        self, config: TwitterGetSampledStreamConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Connect to sampled stream and collect tweets."""
        access_token = await self._get_access_token(credentials)
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        params: Dict[str, Any] = {}
        if config.tweet_fields:
            params["tweet.fields"] = config.tweet_fields

        events: list = []
        timeout_seconds = config.timeout_seconds or 30
        max_events = config.max_events or 10

        try:
            async with httpx.AsyncClient() as client:
                async with client.stream(
                    "GET",
                    f"{TWITTER_API_BASE}/tweets/sample/stream",
                    headers=headers,
                    params=params,
                    timeout=timeout_seconds + 5,
                ) as response:
                    if response.status_code >= 400:
                        error_text = await response.aread()
                        output = {
                            "type": "twitter",
                            "action": "collect_sampled_stream_tweets",
                            "status": "error",
                            "error": error_text.decode()[:400],
                            "status_code": response.status_code,
                            "data": None,
                            "timestamp": time.time(),
                        }
                        await self.emit(output)
                        return output

                    start = time.time()
                    async for line in response.aiter_lines():
                        if time.time() - start > timeout_seconds:
                            break
                        if len(events) >= max_events:
                            break
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            tweet = json.loads(line)
                            if "data" in tweet:
                                events.append(tweet)
                        except Exception:
                            pass
        except httpx.TimeoutException:
            pass

        output = {
            "type": "twitter",
            "action": "collect_sampled_stream_tweets",
            "status": "success",
            "data": {"data": events, "meta": {"result_count": len(events)}},
            "timestamp": time.time(),
        }
        await self.emit(output)
        return output

    async def _get_sampled10_stream(
        self, config: TwitterGetSampled10StreamConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Connect to 10% sampled stream and collect tweets."""
        access_token = await self._get_access_token(credentials)
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        params: Dict[str, Any] = {"partition": config.partition}
        if config.tweet_fields:
            params["tweet.fields"] = config.tweet_fields

        events: list = []
        timeout_seconds = config.timeout_seconds or 30
        max_events = config.max_events or 10

        try:
            async with httpx.AsyncClient() as client:
                async with client.stream(
                    "GET",
                    f"{TWITTER_API_BASE}/tweets/sample10/stream",
                    headers=headers,
                    params=params,
                    timeout=timeout_seconds + 5,
                ) as response:
                    if response.status_code >= 400:
                        error_text = await response.aread()
                        output = {
                            "type": "twitter",
                            "action": "collect_10_percent_sampled_stream_tweets",
                            "status": "error",
                            "error": error_text.decode()[:400],
                            "status_code": response.status_code,
                            "data": None,
                            "timestamp": time.time(),
                        }
                        await self.emit(output)
                        return output

                    start = time.time()
                    async for line in response.aiter_lines():
                        if time.time() - start > timeout_seconds:
                            break
                        if len(events) >= max_events:
                            break
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            tweet = json.loads(line)
                            if "data" in tweet:
                                events.append(tweet)
                        except Exception:
                            pass
        except httpx.TimeoutException:
            pass

        output = {
            "type": "twitter",
            "action": "collect_10_percent_sampled_stream_tweets",
            "status": "success",
            "data": {"data": events, "meta": {"result_count": len(events)}},
            "timestamp": time.time(),
        }
        await self.emit(output)
        return output

    # ============================================================================
    # Trends Actions
    # ============================================================================

    async def _get_trends_by_woeid(
        self, config: TwitterGetTrendsByWOEIDConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get trending topics by WOEID."""
        params: Dict[str, Any] = {}
        if config.max_results:
            params["max_results"] = config.max_results

        return await self._make_request(
            "GET",
            f"/trends/by/woeid/{config.woeid}",
            credentials,
            params=params if params else None,
            action_name="get_trending_topics_by_woeid",
        )

    async def _get_personalized_trends(
        self, config: TwitterGetPersonalizedTrendsConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get personalized trending topics for the authenticated user."""
        return await self._make_request(
            "GET",
            "/users/personalized_trends",
            credentials,
            action_name="get_personalized_trending_topics",
        )

    # ============================================================================
    # News Actions
    # ============================================================================

    async def _search_news(
        self, config: TwitterSearchNewsConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Search news articles."""
        params: Dict[str, Any] = {"query": config.query}
        if config.max_results:
            params["max_results"] = config.max_results
        if config.start_time:
            params["start_time"] = config.start_time

        return await self._make_request(
            "GET",
            "/news/search",
            credentials,
            params=params,
            action_name="search_news_articles",
        )

    async def _get_news_by_id(
        self, config: TwitterGetNewsByIdConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get a news article by ID."""
        return await self._make_request(
            "GET",
            f"/news/{config.news_id}",
            credentials,
            action_name="get_news_article_by_id",
        )

    # ============================================================================
    # Usage Actions
    # ============================================================================

    async def _get_usage(
        self, config: TwitterGetUsageConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get API usage data."""
        params: Dict[str, Any] = {}
        if config.days:
            params["days"] = config.days

        return await self._make_request(
            "GET",
            "/usage/tweets",
            credentials,
            params=params if params else None,
            action_name="get_api_usage",
        )

    # ============================================================================
    # Communities Actions
    # ============================================================================

    async def _get_community(
        self, config: TwitterGetCommunityConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get a community by ID."""
        return await self._make_request(
            "GET",
            f"/communities/{config.community_id}",
            credentials,
            action_name="get_community_by_id",
        )

    async def _search_communities(
        self, config: TwitterSearchCommunitiesConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Search for communities."""
        params: Dict[str, Any] = {"query": config.query}
        if config.max_results:
            params["max_results"] = config.max_results

        return await self._make_request(
            "GET",
            "/communities/search",
            credentials,
            params=params,
            action_name="search_communities",
        )

    # ============================================================================
    # Community Notes Actions
    # ============================================================================

    async def _create_note(
        self, config: TwitterCreateNoteConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Create a community note on a tweet."""
        body: Dict[str, Any] = {
            "tweet_id": config.tweet_id,
            "note_text": config.note_text,
        }
        if config.misleading_as:
            body["misleading_as"] = config.misleading_as

        return await self._make_request(
            "POST",
            "/notes",
            credentials,
            json_body=body,
            action_name="create_community_note_on_tweet",
        )

    async def _delete_note(
        self, config: TwitterDeleteNoteConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Delete a community note."""
        return await self._make_request(
            "DELETE",
            f"/notes/{config.note_id}",
            credentials,
            action_name="delete_community_note",
        )

    async def _evaluate_note(
        self, config: TwitterEvaluateNoteConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Evaluate a community note."""
        body: Dict[str, Any] = {"note_id": config.note_id}

        return await self._make_request(
            "POST",
            "/evaluate_note",
            credentials,
            json_body=body,
            action_name="evaluate_community_note",
        )

    async def _get_notes_written(
        self, config: TwitterGetNotesWrittenConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get community notes written by the authenticated user."""
        params: Dict[str, Any] = {}
        if config.max_results:
            params["max_results"] = config.max_results

        return await self._make_request(
            "GET",
            "/notes/search/notes_written",
            credentials,
            params=params if params else None,
            action_name="get_community_notes_written",
        )

    async def _get_posts_eligible_for_notes(
        self,
        config: TwitterGetPostsEligibleForNotesConfig,
        credentials: TwitterCredential,
    ) -> Dict[str, Any]:
        """Get posts eligible for community notes."""
        params: Dict[str, Any] = {}
        if config.max_results:
            params["max_results"] = config.max_results

        return await self._make_request(
            "GET",
            "/notes/search/posts_eligible_for_notes",
            credentials,
            params=params if params else None,
            action_name="get_posts_eligible_for_community_notes",
        )

    # ============================================================================
    # Compliance Job Actions
    # ============================================================================

    async def _create_compliance_job(
        self, config: TwitterCreateComplianceJobConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Create a compliance job."""
        body: Dict[str, Any] = {"type": config.type}
        if config.name:
            body["name"] = config.name

        return await self._make_request(
            "POST",
            "/compliance/jobs",
            credentials,
            json_body=body,
            action_name="create_compliance_job",
        )

    async def _get_compliance_job(
        self, config: TwitterGetComplianceJobConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get a compliance job by ID."""
        return await self._make_request(
            "GET",
            f"/compliance/jobs/{config.job_id}",
            credentials,
            action_name="get_compliance_job_by_id",
        )

    async def _list_compliance_jobs(
        self, config: TwitterListComplianceJobsConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """List compliance jobs."""
        params: Dict[str, Any] = {}
        if config.type:
            params["type"] = config.type

        return await self._make_request(
            "GET",
            "/compliance/jobs",
            credentials,
            params=params if params else None,
            action_name="list_compliance_jobs",
        )

    # ============================================================================
    # Webhook Actions
    # ============================================================================

    async def _create_webhook(
        self, config: TwitterCreateWebhookConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Create a webhook."""
        body: Dict[str, Any] = {"url": config.url}
        if config.name:
            body["name"] = config.name

        return await self._make_request(
            "POST",
            "/webhooks",
            credentials,
            json_body=body,
            action_name="create_webhook",
        )

    async def _delete_webhook(
        self, config: TwitterDeleteWebhookConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Delete a webhook."""
        return await self._make_request(
            "DELETE",
            f"/webhooks/{config.webhook_id}",
            credentials,
            action_name="delete_webhook",
        )

    async def _get_webhook(
        self, config: TwitterGetWebhookConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get a webhook by ID."""
        return await self._make_request(
            "GET",
            f"/webhooks/{config.webhook_id}",
            credentials,
            action_name="get_webhook_by_id",
        )

    async def _validate_webhook(
        self, config: TwitterValidateWebhookConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Validate a webhook."""
        return await self._make_request(
            "POST",
            f"/webhooks/{config.webhook_id}/validate",
            credentials,
            action_name="validate_webhook",
        )

    async def _create_stream_link(
        self, config: TwitterCreateStreamLinkConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Create a stream link for a webhook."""
        return await self._make_request(
            "POST",
            f"/webhooks/{config.webhook_id}/stream_links",
            credentials,
            action_name="create_webhook_stream_link",
        )

    async def _delete_stream_link(
        self, config: TwitterDeleteStreamLinkConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Delete a stream link from a webhook."""
        return await self._make_request(
            "DELETE",
            f"/webhooks/{config.webhook_id}/stream_links/{config.stream_link_id}",
            credentials,
            action_name="delete_webhook_stream_link",
        )

    async def _get_stream_links(
        self, config: TwitterGetStreamLinksConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get stream links for a webhook."""
        return await self._make_request(
            "GET",
            f"/webhooks/{config.webhook_id}/stream_links",
            credentials,
            action_name="get_webhook_stream_links",
        )

    async def _create_webhook_replay(
        self, config: TwitterCreateWebhookReplayConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Create a webhook replay."""
        body: Dict[str, Any] = {}
        if config.from_date:
            body["from_date"] = config.from_date
        if config.to_date:
            body["to_date"] = config.to_date

        return await self._make_request(
            "POST",
            f"/webhooks/{config.webhook_id}/replay",
            credentials,
            json_body=body if body else None,
            action_name="create_webhook_replay",
        )

    # ============================================================================
    # Account Activity Subscription Actions
    # ============================================================================

    async def _create_subscription(
        self, config: TwitterCreateSubscriptionConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Create an account activity subscription."""
        return await self._make_request(
            "POST",
            "/account_activity/subscriptions",
            credentials,
            json_body={"webhook_id": config.webhook_id},
            action_name="create_account_activity_subscription",
        )

    async def _delete_subscription(
        self, config: TwitterDeleteSubscriptionConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Delete an account activity subscription."""
        return await self._make_request(
            "DELETE",
            "/account_activity/subscriptions",
            credentials,
            params={"webhook_id": config.webhook_id},
            action_name="delete_account_activity_subscription",
        )

    async def _get_subscriptions(
        self, config: TwitterGetSubscriptionsConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get account activity subscriptions."""
        return await self._make_request(
            "GET",
            "/account_activity/subscriptions",
            credentials,
            params={"webhook_id": config.webhook_id},
            action_name="get_account_activity_subscriptions",
        )

    async def _get_subscription_count(
        self, config: TwitterGetSubscriptionCountConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get account activity subscription count."""
        return await self._make_request(
            "GET",
            "/account_activity/subscriptions/count",
            credentials,
            action_name="get_account_activity_subscription_count",
        )

    async def _validate_subscription(
        self, config: TwitterValidateSubscriptionConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Validate account activity subscription."""
        return await self._make_request(
            "GET",
            "/account_activity/subscriptions/validate",
            credentials,
            action_name="validate_account_activity_subscription",
        )

    async def _create_subscription_replay(
        self,
        config: TwitterCreateSubscriptionReplayConfig,
        credentials: TwitterCredential,
    ) -> Dict[str, Any]:
        """Create an account activity subscription replay."""
        body: Dict[str, Any] = {"webhook_id": config.webhook_id}
        if config.from_date:
            body["from_date"] = config.from_date
        if config.to_date:
            body["to_date"] = config.to_date

        return await self._make_request(
            "POST",
            "/account_activity/subscriptions/replay",
            credentials,
            json_body=body,
            action_name="create_account_activity_subscription_replay",
        )

    # ============================================================================
    # Streaming Connections Management Actions
    # ============================================================================

    async def _get_connections(
        self, config: TwitterGetConnectionsConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Get all streaming connections."""
        return await self._make_request(
            "GET",
            "/connections",
            credentials,
            action_name="get_all_streaming_connections",
        )

    async def _terminate_all_connections(
        self,
        config: TwitterTerminateAllConnectionsConfig,
        credentials: TwitterCredential,
    ) -> Dict[str, Any]:
        """Terminate all streaming connections."""
        return await self._make_request(
            "DELETE",
            "/connections",
            credentials,
            action_name="terminate_all_streaming_connections",
        )

    async def _terminate_connections_by_endpoint(
        self,
        config: TwitterTerminateConnectionsByEndpointConfig,
        credentials: TwitterCredential,
    ) -> Dict[str, Any]:
        """Terminate streaming connections by endpoint type."""
        body: Dict[str, Any] = {"endpoint_type": config.endpoint_type}

        return await self._make_request(
            "DELETE",
            "/connections/by/endpoint",
            credentials,
            json_body=body,
            action_name="terminate_streaming_connections_by_endpoint_type",
        )

    async def _terminate_connection(
        self, config: TwitterTerminateConnectionConfig, credentials: TwitterCredential
    ) -> Dict[str, Any]:
        """Terminate a specific streaming connection."""
        return await self._make_request(
            "DELETE",
            f"/connections/{config.connection_id}",
            credentials,
            action_name="terminate_streaming_connection",
        )
