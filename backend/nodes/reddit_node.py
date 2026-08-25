"""
Reddit API automation node.

This node provides Reddit operations in workflows via the Reddit API.
Uses httpx for high-performance async HTTP requests.

API Reference: https://www.reddit.com/dev/api/
OAuth Reference: https://github.com/reddit-archive/reddit/wiki/OAuth2
"""

import asyncio
import html as html_lib
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from decimal import Decimal
from typing import Dict, Any, Optional, Union, Literal, List, Annotated
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, Field, Discriminator, ConfigDict, model_validator

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.scopes.reddit import REDDIT_SCOPES
from utils.oauth_token_cache import (
    OAuthTokenCache,
    oauth_authority_digest,
    token_expiry_input,
)

logger = logging.getLogger(__name__)

REDDIT_API_BASE = "https://oauth.reddit.com"
USER_AGENT = "NoClick/1.0 (workflow automation)"
BRIGHTDATA_DATASETS_API_BASE = "https://api.brightdata.com/datasets/v3"
BRIGHTDATA_REDDIT_POSTS_DATASET_ID = "gd_lvz8ah06191smkebj4"
BRIGHTDATA_REDDIT_SNAPSHOT_TIMEOUT_SECONDS = 120.0
BRIGHTDATA_REDDIT_COST_PER_RECORD_USD = Decimal("0.0015")
PUBLIC_REDDIT_COMMENT_LIMIT = 10
PUBLIC_REDDIT_COMMENT_FETCH_CONCURRENCY = 8

# Optional[Literal] nests its enum inside anyOf, which the config renderer can't
# turn into a dropdown — time fields need the enum hoisted explicitly.
TIME_PERIOD_SCHEMA_EXTRA = {
    "enum": ["hour", "day", "week", "month", "year", "all"],
    "enumNames": ["Past Hour", "Past 24 Hours", "Past Week", "Past Month", "Past Year", "All Time"],
    "x-enum-searchable": True,
}


def _get_brightdata_api_token() -> str:
    return (
        os.environ.get("BRIGHTDATA_API_TOKEN")
        or os.environ.get("BRIGHTDATA_DATASET_API_TOKEN")
        or os.environ.get("BRIGHTDATA_TOKEN")
        or ""
    )


def _get_brightdata_proxy_url() -> str:
    """Read Bright Data proxy config lazily so dotenv load order can't stale it."""
    user = os.environ.get("BRIGHTDATA_PROXY_USER", "")
    password = os.environ.get("BRIGHTDATA_PROXY_PASS", "")
    host = os.environ.get("BRIGHTDATA_PROXY_HOST", "brd.superproxy.io")
    port = os.environ.get("BRIGHTDATA_PROXY_PORT", "33335")
    return f"http://{user}:{password}@{host}:{port}" if user else ""

# ============================================================================
# Reddit Credential Schemas
# ============================================================================


class RedditOAuthCredential(BaseModel):
    """OAuth 2.0 credential for Reddit.
    Tokens are obtained via OAuth flow, not entered manually.

    Register OAuth app at: https://www.reddit.com/prefs/apps
    """

    credential_type: Literal["reddit_oauth"] = Field(
        default="reddit_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(..., title="Access Token")
    refresh_token: str = Field(..., title="Refresh Token")
    expires_at: str = Field(..., title="Token Expiry")  # ISO 8601
    username: Optional[str] = Field(None, title="Reddit Username")

    model_config = ConfigDict(json_schema_extra={
        "x-credential-type": "oauth",
        "x-oauth-provider": "reddit",
        "x-credential-hidden": True,
        "x-oauth-scopes": [
            "identity",  # Access user identity
            "read",  # Read public content
            "submit",  # Submit posts and comments
            "vote",  # Vote on posts and comments
            "edit",  # Edit user content
            "history",  # View user history
            "privatemessages",  # Read and send private messages
            "mysubreddits",  # Access subscribed subreddits
            "save",  # Save/unsave content
            "subscribe",  # Manage subscriptions
            "report",  # Report content
            "flair",  # Manage flair
            "modflair",  # Moderate flair (mod)
            "modposts",  # Moderate posts (mod)
            "modconfig",  # Moderate config (mod)
            "modlog",  # Access mod log (mod)
            "wikiread",  # Read wiki pages
            "wikiedit",  # Edit wiki pages
            "livemanage",  # Manage live threads
        ],
    })


class RedditScriptCredential(BaseModel):
    """Script/Personal Use credential for Reddit.
    Users provide their own Reddit app credentials.

    Create a "script" app at: https://www.reddit.com/prefs/apps
    1. Click "create another app..." at the bottom
    2. Select "script" as the app type
    3. Set redirect uri to http://localhost:8080 (not used for script apps)
    4. Copy the client_id (under the app name) and client_secret
    """

    credential_type: Literal["reddit_script"] = Field(
        default="reddit_script", json_schema_extra={"ui:hidden": True}
    )
    client_id: str = Field(
        ...,
        title="Client ID",
        description="Your Reddit app's client ID (found under app name)",
        json_schema_extra={
            "ui:help": "Create app at https://www.reddit.com/prefs/apps"
        },
    )
    client_secret: str = Field(
        ...,
        title="Client Secret",
        description="Your Reddit app's client secret",
        json_schema_extra={"ui:widget": "password"},
    )
    username: str = Field(
        ..., title="Reddit Username", description="Your Reddit username"
    )
    password: str = Field(
        ...,
        title="Reddit Password",
        description="Your Reddit account password",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(json_schema_extra={
        "x-credential-type": "script",
        "x-help-url": "https://www.reddit.com/prefs/apps",
        "x-help-text": "Create a 'script' type app to get your credentials",
    })


# Union of credential types - OAuth flow or user-provided script credentials
RedditCredential = Union[RedditOAuthCredential, RedditScriptCredential]


# ============================================================================
# Reddit Configuration Models (One per action)
# ============================================================================


class RedditGetMeConfig(BaseModel):
    """Get information about the authenticated user"""

    model_config = ConfigDict(populate_by_name=True, title="Get Me")

    operation: Literal["get_authenticated_user_info"] = Field(
        default="get_authenticated_user_info",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get Authenticated User Info",
        },
        title="Get Authenticated User Info",
    )


class RedditGetUserConfig(BaseModel):
    """Get information about a specific user"""

    model_config = ConfigDict(populate_by_name=True, title="Get User")

    operation: Literal["get_user_info"] = Field(
        default="get_user_info",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get User Info",
        },
        title="Get User Info",
    )
    username: str = Field(
        ..., title="Username", description="Reddit username (without u/)"
    )


class RedditGetSubredditPostsConfig(BaseModel):
    """Fetch public posts from a subreddit feed without Reddit credentials"""
    model_config = ConfigDict(
        populate_by_name=True,
        title="Get Subreddit Posts",
        json_schema_extra={
            "ui:help": (
                "Fetches public subreddit posts without Reddit credentials. "
                "Fast mode uses Reddit's public RSS feed directly and retries through "
                "the configured proxy only when needed. Rich mode uses Bright Data's "
                "Reddit scraper and may take longer, but can return richer metadata."
            ),
            "x-credentials-optional": True,
        }
    )

    operation: Literal["get_subreddit_posts"] = Field(
        default="get_subreddit_posts",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Subreddit",
            "x-is-trigger": False,
            "x-display-name": "Get Subreddit Posts",
        },
        title="Get Subreddit Posts",
    )
    subreddit: str = Field(
        ..., title="Subreddit", description="Subreddit name (without r/)"
    )
    sort: Optional[Literal["", "hot", "new", "top", "rising", "controversial"]] = Field(
        default="hot",
        title="Sort By",
        description="Sort order for posts",
        json_schema_extra={
            "enum": ["", "hot", "new", "top", "rising", "controversial"],
            "enumNames": ["Default Feed", "Hot", "New", "Top", "Rising", "Controversial"],
            "x-enum-searchable": True,
        }
    )
    time: Optional[Literal["hour", "day", "week", "month", "year", "all"]] = Field(
        default="day",
        title="Time Period",
        description="Time period for top/controversial sorting (fast mode only)",
        json_schema_extra={
            **TIME_PERIOD_SCHEMA_EXTRA,
            "ui:show-if": {"field": "sort", "containsAny": ["top", "controversial"]},
        },
    )
    limit: Optional[int] = Field(
        default=25,
        title="Limit",
        description=(
            "Number of top-level posts to fetch. When comments are enabled, each returned "
            "entry is one post with corresponding comments nested under it when available."
        )
    )
    fetch_comments: Optional[str] = Field(
        default="false",
        title="Fetch Comments",
        description="Fetch top comments for each post (adds latency - 1-2 seconds per post)",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        }
    )
    content_mode: Optional[str] = Field(
        default="fast",
        title="Content Detail",
        description=(
            "Fast uses Reddit RSS and is usually quicker. Rich uses Bright Data's "
            "Reddit scraper for richer post metadata and may take significantly longer. "
            "Rich mode does not support the Time Period filter."
        ),
        json_schema_extra={
            "enum": ["fast", "rich"],
            "enumNames": ["Fast (RSS, less detail)", "Rich (Bright Data, slower)"],
            "x-enum-searchable": True,
        }
    )
    use_proxy: Optional[str] = Field(
        default="auto",
        title="Proxy Mode",
        description="How the fast RSS path should handle Reddit blocks. Auto tries direct first and retries through Bright Data proxy only if needed. Always forces proxy. Never keeps requests direct-only.",
        json_schema_extra={
            "enum": ["auto", "always", "never"],
            "enumNames": ["Auto (direct + proxy retry)", "Always use proxy", "Never use proxy"],
            "x-enum-searchable": True,
            "ui:category": "Advanced",
        }
    )


class RedditGetPostConfig(BaseModel):
    """Get a specific post by ID"""

    model_config = ConfigDict(populate_by_name=True, title="Get Post")

    operation: Literal["get_post"] = Field(
        default="get_post",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Get Post",
        },
        title="Get Post",
    )
    post_id: str = Field(
        ...,
        title="Post ID",
        description="Reddit post ID (the 'thing' ID, e.g., 't3_abc123' or just 'abc123')",
    )


class RedditGetPostCommentsConfig(BaseModel):
    """Get comments on a post"""

    model_config = ConfigDict(populate_by_name=True, title="Get Post Comments")

    operation: Literal["get_post_comments"] = Field(
        default="get_post_comments",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Get Post Comments",
        },
        title="Get Post Comments",
    )
    post_id: str = Field(..., title="Post ID", description="Reddit post ID")
    sort: Optional[
        Literal["confidence", "top", "new", "controversial", "old", "qa"]
    ] = Field(default="confidence", title="Sort", description="How to sort comments")
    limit: Optional[int] = Field(
        default=25, title="Limit", description="Number of comments to return"
    )


class RedditSubmitTextPostConfig(BaseModel):
    """Submit a text post to a subreddit"""

    model_config = ConfigDict(populate_by_name=True, title="Submit Text Post")

    operation: Literal["submit_text_post"] = Field(
        default="submit_text_post",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Submit Text Post",
        },
        title="Submit Text Post",
    )
    subreddit: str = Field(
        ..., title="Subreddit", description="Subreddit to post to (without r/)"
    )
    title: str = Field(..., title="Title", description="Post title")
    text: str = Field(
        ...,
        title="Text",
        description="Post body (Markdown supported)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    nsfw: Optional[bool] = Field(
        default=False, title="NSFW", description="Mark as NSFW content"
    )
    spoiler: Optional[bool] = Field(
        default=False, title="Spoiler", description="Mark as containing spoilers"
    )


class RedditSubmitLinkPostConfig(BaseModel):
    """Submit a link post to a subreddit"""

    model_config = ConfigDict(populate_by_name=True, title="Submit Link Post")

    operation: Literal["submit_link_post"] = Field(
        default="submit_link_post",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Submit Link Post",
        },
        title="Submit Link Post",
    )
    subreddit: str = Field(
        ..., title="Subreddit", description="Subreddit to post to (without r/)"
    )
    title: str = Field(..., title="Title", description="Post title")
    url: str = Field(..., title="URL", description="URL to link to")
    nsfw: Optional[bool] = Field(
        default=False, title="NSFW", description="Mark as NSFW content"
    )
    spoiler: Optional[bool] = Field(
        default=False, title="Spoiler", description="Mark as containing spoilers"
    )


class RedditSubmitCommentConfig(BaseModel):
    """Submit a comment on a post or reply to a comment"""

    model_config = ConfigDict(populate_by_name=True, title="Submit Comment")

    operation: Literal["submit_comment"] = Field(
        default="submit_comment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Submit Comment",
        },
        title="Submit Comment",
    )
    thing_id: str = Field(
        ...,
        title="Thing ID",
        description="Full ID of post (t3_xxx) or comment (t1_xxx) to reply to",
    )
    text: str = Field(
        ...,
        title="Comment Text",
        description="Comment body (Markdown supported)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class RedditVoteConfig(BaseModel):
    """Vote on a post or comment"""

    model_config = ConfigDict(populate_by_name=True, title="Vote")

    operation: Literal["vote_on_post_or_comment"] = Field(
        default="vote_on_post_or_comment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Vote on Post or Comment",
        },
        title="Vote on Post or Comment",
    )
    thing_id: str = Field(
        ...,
        title="Thing ID",
        description="Full ID of post (t3_xxx) or comment (t1_xxx) to vote on",
    )
    direction: Literal["up", "down", "none"] = Field(
        ...,
        title="Direction",
        description="Vote direction: up (upvote), down (downvote), none (remove vote)",
    )


class RedditEditConfig(BaseModel):
    """Edit a post or comment"""

    model_config = ConfigDict(populate_by_name=True, title="Edit")

    operation: Literal["edit_post_or_comment"] = Field(
        default="edit_post_or_comment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Edit Post or Comment",
        },
        title="Edit Post or Comment",
    )
    thing_id: str = Field(
        ...,
        title="Thing ID",
        description="Full ID of post (t3_xxx) or comment (t1_xxx) to edit",
    )
    text: str = Field(
        ...,
        title="New Text",
        description="New content (Markdown supported)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class RedditDeleteConfig(BaseModel):
    """Delete a post or comment"""

    model_config = ConfigDict(populate_by_name=True, title="Delete")

    operation: Literal["delete_post_or_comment"] = Field(
        default="delete_post_or_comment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Delete Post or Comment",
        },
        title="Delete Post or Comment",
    )
    thing_id: str = Field(
        ...,
        title="Thing ID",
        description="Full ID of post (t3_xxx) or comment (t1_xxx) to delete",
    )


class RedditSearchConfig(BaseModel):
    """Search Reddit"""

    model_config = ConfigDict(populate_by_name=True, title="Search")

    operation: Literal["search_reddit"] = Field(
        default="search_reddit",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Misc",
            "x-is-trigger": False,
            "x-display-name": "Search Reddit",
        },
        title="Search Reddit",
    )
    query: str = Field(..., title="Search Query", description="Search query")
    subreddit: Optional[str] = Field(
        default=None,
        title="Subreddit",
        description="Limit search to a specific subreddit (without r/)",
    )
    sort: Optional[Literal["relevance", "hot", "top", "new", "comments"]] = Field(
        default="relevance", title="Sort", description="How to sort search results"
    )
    time: Optional[Literal["hour", "day", "week", "month", "year", "all"]] = Field(
        default="all",
        title="Time Period",
        description="Time period to search within",
        json_schema_extra={**TIME_PERIOD_SCHEMA_EXTRA},
    )
    type: Optional[Literal["link", "sr", "user"]] = Field(
        default="link",
        title="Result Type",
        description="Type of results: link (posts), sr (subreddits), user (users)",
    )
    limit: Optional[int] = Field(
        default=25, title="Limit", description="Number of results to return (max 100)"
    )


class RedditGetMySubredditsConfig(BaseModel):
    """Get the authenticated user's subscribed subreddits"""

    model_config = ConfigDict(populate_by_name=True, title="Get My Subreddits")

    operation: Literal["get_my_subscribed_subreddits"] = Field(
        default="get_my_subscribed_subreddits",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Subreddit",
            "x-is-trigger": False,
            "x-display-name": "Get My Subscribed Subreddits",
        },
        title="Get My Subscribed Subreddits",
    )
    where: Optional[Literal["subscriber", "moderator", "contributor"]] = Field(
        default="subscriber",
        title="Relationship",
        description="Filter by relationship to subreddit",
    )
    limit: Optional[int] = Field(
        default=25,
        title="Limit",
        description="Number of subreddits to return (max 100)",
    )


class RedditGetSubredditInfoConfig(BaseModel):
    """Get information about a subreddit"""

    model_config = ConfigDict(populate_by_name=True, title="Get Subreddit Info")

    operation: Literal["get_subreddit_info"] = Field(
        default="get_subreddit_info",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Subreddit",
            "x-is-trigger": False,
            "x-display-name": "Get Subreddit Info",
        },
        title="Get Subreddit Info",
    )
    subreddit: str = Field(
        ..., title="Subreddit", description="Subreddit name (without r/)"
    )


class RedditSendMessageConfig(BaseModel):
    """Send a private message to a user"""

    model_config = ConfigDict(populate_by_name=True, title="Send Message")

    operation: Literal["send_private_message"] = Field(
        default="send_private_message",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Send Private Message",
        },
        title="Send Private Message",
    )
    to: str = Field(
        ..., title="Recipient", description="Username to send message to (without u/)"
    )
    subject: str = Field(..., title="Subject", description="Message subject")
    text: str = Field(
        ...,
        title="Message",
        description="Message body (Markdown supported)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class RedditGetInboxConfig(BaseModel):
    """Get the authenticated user's inbox messages"""

    model_config = ConfigDict(populate_by_name=True, title="Get Inbox")

    operation: Literal["get_inbox_messages"] = Field(
        default="get_inbox_messages",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Get Inbox Messages",
        },
        title="Get Inbox Messages",
    )
    where: Optional[Literal["inbox", "unread", "messages", "sent", "mentions"]] = Field(
        default="inbox", title="Type", description="Type of messages to retrieve"
    )
    limit: Optional[int] = Field(
        default=25, title="Limit", description="Number of messages to return (max 100)"
    )


class RedditGetUserPostsConfig(BaseModel):
    """Get posts by a specific user"""

    model_config = ConfigDict(populate_by_name=True, title="Get User Posts")

    operation: Literal["get_user_posts"] = Field(
        default="get_user_posts",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get User Posts",
        },
        title="Get User Posts",
    )
    username: str = Field(
        ..., title="Username", description="Reddit username (without u/)"
    )
    sort: Optional[Literal["hot", "new", "top", "controversial"]] = Field(
        default="new",
        title="Sort",
        description="How to sort posts",
        json_schema_extra={
            "enum": ["hot", "new", "top", "controversial"],
            "enumNames": ["Hot", "New", "Top", "Controversial"],
            "x-enum-searchable": True,
        },
    )
    time: Optional[Literal["hour", "day", "week", "month", "year", "all"]] = Field(
        default="all",
        title="Time Period",
        description="Time period for top/controversial sorting",
        json_schema_extra={
            **TIME_PERIOD_SCHEMA_EXTRA,
            "ui:show-if": {"field": "sort", "containsAny": ["top", "controversial"]},
        },
    )
    limit: Optional[int] = Field(
        default=25, title="Limit", description="Number of posts to return (max 100)"
    )


class RedditGetUserCommentsConfig(BaseModel):
    """Get comments by a specific user"""

    model_config = ConfigDict(populate_by_name=True, title="Get User Comments")

    operation: Literal["get_user_comments"] = Field(
        default="get_user_comments",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get User Comments",
        },
        title="Get User Comments",
    )
    username: str = Field(
        ..., title="Username", description="Reddit username (without u/)"
    )
    sort: Optional[Literal["hot", "new", "top", "controversial"]] = Field(
        default="new",
        title="Sort",
        description="How to sort comments",
        json_schema_extra={
            "enum": ["hot", "new", "top", "controversial"],
            "enumNames": ["Hot", "New", "Top", "Controversial"],
            "x-enum-searchable": True,
        },
    )
    time: Optional[Literal["hour", "day", "week", "month", "year", "all"]] = Field(
        default="all",
        title="Time Period",
        description="Time period for top/controversial sorting",
        json_schema_extra={
            **TIME_PERIOD_SCHEMA_EXTRA,
            "ui:show-if": {"field": "sort", "containsAny": ["top", "controversial"]},
        },
    )
    limit: Optional[int] = Field(
        default=25, title="Limit", description="Number of comments to return (max 100)"
    )


class RedditSaveConfig(BaseModel):
    """Save or unsave a post or comment"""

    model_config = ConfigDict(populate_by_name=True, title="Save")

    operation: Literal["save_post_or_comment"] = Field(
        default="save_post_or_comment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Save Post or Comment",
        },
        title="Save Post or Comment",
    )
    thing_id: str = Field(
        ...,
        title="Thing ID",
        description="Full ID of post (t3_xxx) or comment (t1_xxx)",
    )
    unsave: Optional[bool] = Field(
        default=False,
        title="Unsave",
        description="Set to true to unsave instead of save",
    )


class RedditSubscribeConfig(BaseModel):
    """Subscribe or unsubscribe from a subreddit"""

    model_config = ConfigDict(populate_by_name=True, title="Subscribe")

    operation: Literal["subscribe_to_subreddit"] = Field(
        default="subscribe_to_subreddit",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Subreddit",
            "x-is-trigger": False,
            "x-display-name": "Subscribe to Subreddit",
        },
        title="Subscribe to Subreddit",
    )
    subreddit: str = Field(
        ..., title="Subreddit", description="Subreddit name (without r/)"
    )
    unsubscribe: Optional[bool] = Field(
        default=False,
        title="Unsubscribe",
        description="Set to true to unsubscribe instead of subscribe",
    )


# ============================================================================
# Additional User Operations
# ============================================================================


class RedditGetUserSavedConfig(BaseModel):
    """Get a user's saved posts and comments"""

    model_config = ConfigDict(populate_by_name=True, title="Get User Saved")

    operation: Literal["get_user_saved_posts_and_comments"] = Field(
        default="get_user_saved_posts_and_comments",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get User Saved Posts and Comments",
        },
        title="Get User Saved Posts and Comments",
    )
    username: Optional[str] = Field(
        default=None,
        title="Username",
        description="Username to get saved items for (leave empty for yourself)",
    )
    limit: Optional[int] = Field(
        default=25, title="Limit", description="Number of items to return (max 100)"
    )


class RedditGetTrophiesConfig(BaseModel):
    """Get a user's trophies/awards"""

    model_config = ConfigDict(populate_by_name=True, title="Get Trophies")

    operation: Literal["get_user_trophies"] = Field(
        default="get_user_trophies",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get User Trophies",
        },
        title="Get User Trophies",
    )
    username: Optional[str] = Field(
        default=None,
        title="Username",
        description="Username to get trophies for (leave empty for yourself)",
    )


class RedditBlockUserConfig(BaseModel):
    """Block a user"""

    model_config = ConfigDict(populate_by_name=True, title="Block User")

    operation: Literal["block_user"] = Field(
        default="block_user",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Block User",
        },
        title="Block User",
    )
    username: str = Field(
        ..., title="Username", description="Username to block (without u/)"
    )


class RedditGetFriendsConfig(BaseModel):
    """Get the authenticated user's friends list"""

    model_config = ConfigDict(populate_by_name=True, title="Get Friends")

    operation: Literal["get_friends_list"] = Field(
        default="get_friends_list",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get Friends List",
        },
        title="Get Friends List",
    )


# ============================================================================
# Additional Post Operations
# ============================================================================


class RedditHideConfig(BaseModel):
    """Hide a post from your feed"""

    model_config = ConfigDict(populate_by_name=True, title="Hide")

    operation: Literal["hide_post_from_feed"] = Field(
        default="hide_post_from_feed",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Hide Post from Feed",
        },
        title="Hide Post from Feed",
    )
    thing_id: str = Field(
        ..., title="Thing ID", description="Full ID of post (t3_xxx) to hide"
    )
    unhide: Optional[bool] = Field(
        default=False,
        title="Unhide",
        description="Set to true to unhide instead of hide",
    )


class RedditReportConfig(BaseModel):
    """Report a post or comment"""

    model_config = ConfigDict(populate_by_name=True, title="Report")

    operation: Literal["report_post_or_comment"] = Field(
        default="report_post_or_comment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Report Post or Comment",
        },
        title="Report Post or Comment",
    )
    thing_id: str = Field(
        ...,
        title="Thing ID",
        description="Full ID of post (t3_xxx) or comment (t1_xxx) to report",
    )
    reason: str = Field(..., title="Reason", description="Reason for reporting")


class RedditCrosspostConfig(BaseModel):
    """Crosspost a post to another subreddit"""

    model_config = ConfigDict(populate_by_name=True, title="Crosspost")

    operation: Literal["crosspost_to_subreddit"] = Field(
        default="crosspost_to_subreddit",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Crosspost to Subreddit",
        },
        title="Crosspost to Subreddit",
    )
    thing_id: str = Field(
        ...,
        title="Original Post ID",
        description="Full ID of post (t3_xxx) to crosspost",
    )
    subreddit: str = Field(
        ...,
        title="Target Subreddit",
        description="Subreddit to crosspost to (without r/)",
    )
    title: str = Field(..., title="Title", description="Title for the crosspost")


class RedditGetDuplicatesConfig(BaseModel):
    """Get duplicate posts (crossposts and reposts)"""

    model_config = ConfigDict(populate_by_name=True, title="Get Duplicates")

    operation: Literal["get_duplicate_posts"] = Field(
        default="get_duplicate_posts",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Get Duplicate Posts",
        },
        title="Get Duplicate Posts",
    )
    post_id: str = Field(
        ..., title="Post ID", description="Post ID to find duplicates of"
    )
    limit: Optional[int] = Field(
        default=25,
        title="Limit",
        description="Number of duplicates to return (max 100)",
    )


# ============================================================================
# Flair Operations
# ============================================================================


class RedditGetLinkFlairConfig(BaseModel):
    """Get available link flair options for a subreddit"""

    model_config = ConfigDict(populate_by_name=True, title="Get Link Flair")

    operation: Literal["get_subreddit_link_flair_options"] = Field(
        default="get_subreddit_link_flair_options",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Subreddit",
            "x-is-trigger": False,
            "x-display-name": "Get Subreddit Link Flair Options",
        },
        title="Get Subreddit Link Flair Options",
    )
    subreddit: str = Field(
        ...,
        title="Subreddit",
        description="Subreddit to get flair options from (without r/)",
    )


class RedditSetLinkFlairConfig(BaseModel):
    """Set flair on a post"""

    model_config = ConfigDict(populate_by_name=True, title="Set Link Flair")

    operation: Literal["set_post_link_flair"] = Field(
        default="set_post_link_flair",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Set Post Link Flair",
        },
        title="Set Post Link Flair",
    )
    thing_id: str = Field(
        ..., title="Post ID", description="Full ID of post (t3_xxx) to set flair on"
    )
    flair_template_id: Optional[str] = Field(
        default=None,
        title="Flair Template ID",
        description="ID of the flair template to use",
    )
    text: Optional[str] = Field(
        default=None, title="Flair Text", description="Custom flair text (if allowed)"
    )


# ============================================================================
# Subreddit Rules & Search
# ============================================================================


class RedditGetSubredditRulesConfig(BaseModel):
    """Get rules for a subreddit"""

    model_config = ConfigDict(populate_by_name=True, title="Get Subreddit Rules")

    operation: Literal["get_subreddit_rules"] = Field(
        default="get_subreddit_rules",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Subreddit",
            "x-is-trigger": False,
            "x-display-name": "Get Subreddit Rules",
        },
        title="Get Subreddit Rules",
    )
    subreddit: str = Field(
        ..., title="Subreddit", description="Subreddit to get rules from (without r/)"
    )


class RedditSearchSubredditsConfig(BaseModel):
    """Search for subreddits by name"""

    model_config = ConfigDict(populate_by_name=True, title="Search Subreddits")

    operation: Literal["search_subreddits"] = Field(
        default="search_subreddits",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Subreddit",
            "x-is-trigger": False,
            "x-display-name": "Search Subreddits",
        },
        title="Search Subreddits",
    )
    query: str = Field(
        ..., title="Search Query", description="Search query for subreddit names"
    )
    limit: Optional[int] = Field(
        default=25, title="Limit", description="Number of results to return (max 100)"
    )
    include_over_18: Optional[bool] = Field(
        default=False,
        title="Include NSFW",
        description="Include NSFW subreddits in results",
    )


# ============================================================================
# Multireddit Operations
# ============================================================================


class RedditGetMultiredditConfig(BaseModel):
    """Get a specific multireddit"""

    model_config = ConfigDict(populate_by_name=True, title="Get Multireddit")

    operation: Literal["get_multireddit"] = Field(
        default="get_multireddit",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Multireddit",
            "x-is-trigger": False,
            "x-display-name": "Get Multireddit",
        },
        title="Get Multireddit",
    )
    username: str = Field(
        ..., title="Username", description="Owner of the multireddit (without u/)"
    )
    multiname: str = Field(
        ..., title="Multireddit Name", description="Name of the multireddit"
    )


class RedditGetMyMultiredditsConfig(BaseModel):
    """Get the authenticated user's multireddits"""

    model_config = ConfigDict(populate_by_name=True, title="Get My Multireddits")

    operation: Literal["get_my_multireddits"] = Field(
        default="get_my_multireddits",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Multireddit",
            "x-is-trigger": False,
            "x-display-name": "Get My Multireddits",
        },
        title="Get My Multireddits",
    )


class RedditGetMultiredditPostsConfig(BaseModel):
    """Get posts from a multireddit"""

    model_config = ConfigDict(populate_by_name=True, title="Get Multireddit Posts")

    operation: Literal["get_multireddit_posts"] = Field(
        default="get_multireddit_posts",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Multireddit",
            "x-is-trigger": False,
            "x-display-name": "Get Multireddit Posts",
        },
        title="Get Multireddit Posts",
    )
    username: str = Field(
        ..., title="Username", description="Owner of the multireddit (without u/)"
    )
    multiname: str = Field(
        ..., title="Multireddit Name", description="Name of the multireddit"
    )
    sort: Optional[Literal["hot", "new", "top", "rising", "controversial"]] = Field(
        default="hot", title="Sort", description="How to sort posts"
    )
    limit: Optional[int] = Field(
        default=25, title="Limit", description="Number of posts to return (max 100)"
    )


# ============================================================================
# Message Operations
# ============================================================================


class RedditMarkMessagesReadConfig(BaseModel):
    """Mark messages as read"""

    model_config = ConfigDict(populate_by_name=True, title="Mark Messages Read")

    operation: Literal["mark_messages_as_read"] = Field(
        default="mark_messages_as_read",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Mark Messages As Read",
        },
        title="Mark Messages As Read",
    )
    thing_ids: str = Field(
        ...,
        title="Message IDs",
        description="Comma-separated list of message IDs (t4_xxx) to mark as read",
    )


class RedditDeleteMessageConfig(BaseModel):
    """Delete a message"""

    model_config = ConfigDict(populate_by_name=True, title="Delete Message")

    operation: Literal["delete_message"] = Field(
        default="delete_message",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Delete Message",
        },
        title="Delete Message",
    )
    thing_id: str = Field(
        ..., title="Message ID", description="Full ID of message (t4_xxx) to delete"
    )


class RedditReplyMessageConfig(BaseModel):
    """Reply to a message"""

    model_config = ConfigDict(populate_by_name=True, title="Reply to Message")

    operation: Literal["reply_to_message"] = Field(
        default="reply_to_message",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Reply to Message",
        },
        title="Reply to Message",
    )
    thing_id: str = Field(
        ..., title="Message ID", description="Full ID of message (t4_xxx) to reply to"
    )
    text: str = Field(
        ...,
        title="Reply Text",
        description="Reply message body (Markdown supported)",
        json_schema_extra={"ui:widget": "textarea"},
    )


# ============================================================================
# Award Operations
# ============================================================================


class RedditGiveAwardConfig(BaseModel):
    """Give an award to a post or comment"""

    model_config = ConfigDict(populate_by_name=True, title="Give Award")

    operation: Literal["give_award_to_post_or_comment"] = Field(
        default="give_award_to_post_or_comment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Give Award to Post or Comment",
        },
        title="Give Award to Post or Comment",
    )
    thing_id: str = Field(
        ...,
        title="Thing ID",
        description="Full ID of post (t3_xxx) or comment (t1_xxx) to award",
    )
    gild_type: Optional[str] = Field(
        default="gid_2",
        title="Award Type",
        description="Type of award to give (gid_1=silver, gid_2=gold, gid_3=platinum)",
    )
    is_anonymous: Optional[bool] = Field(
        default=False, title="Anonymous", description="Give award anonymously"
    )


# ============================================================================
# Additional User Operations
# ============================================================================


class RedditGetKarmaConfig(BaseModel):
    """Get karma breakdown by subreddit"""

    model_config = ConfigDict(populate_by_name=True, title="Get Karma")

    operation: Literal["get_karma_breakdown"] = Field(
        default="get_karma_breakdown",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get Karma Breakdown",
        },
        title="Get Karma Breakdown",
    )


class RedditGetPreferencesConfig(BaseModel):
    """Get the authenticated user's preferences"""

    model_config = ConfigDict(populate_by_name=True, title="Get Preferences")

    operation: Literal["get_authenticated_user_preferences"] = Field(
        default="get_authenticated_user_preferences",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get Authenticated User Preferences",
        },
        title="Get Authenticated User Preferences",
    )


class RedditCheckUsernameConfig(BaseModel):
    """Check if a username is available"""

    model_config = ConfigDict(populate_by_name=True, title="Check Username")

    operation: Literal["check_username_availability"] = Field(
        default="check_username_availability",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Check Username Availability",
        },
        title="Check Username Availability",
    )
    username: str = Field(
        ..., title="Username", description="Username to check availability for"
    )


class RedditReportUserConfig(BaseModel):
    """Report a user"""

    model_config = ConfigDict(populate_by_name=True, title="Report User")

    operation: Literal["report_user"] = Field(
        default="report_user",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Report User",
        },
        title="Report User",
    )
    username: str = Field(
        ..., title="Username", description="Username to report (without u/)"
    )
    reason: str = Field(..., title="Reason", description="Reason for reporting")


# ============================================================================
# Additional Subreddit Operations
# ============================================================================


class RedditGetSubredditModeratorsConfig(BaseModel):
    """Get moderators of a subreddit"""

    model_config = ConfigDict(populate_by_name=True, title="Get Subreddit Moderators")

    operation: Literal["get_subreddit_moderators"] = Field(
        default="get_subreddit_moderators",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Subreddit",
            "x-is-trigger": False,
            "x-display-name": "Get Subreddit Moderators",
        },
        title="Get Subreddit Moderators",
    )
    subreddit: str = Field(
        ..., title="Subreddit", description="Subreddit name (without r/)"
    )


class RedditGetRandomSubredditConfig(BaseModel):
    """Get a random subreddit"""

    model_config = ConfigDict(populate_by_name=True, title="Get Random Subreddit")

    operation: Literal["get_random_subreddit"] = Field(
        default="get_random_subreddit",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Subreddit",
            "x-is-trigger": False,
            "x-display-name": "Get Random Subreddit",
        },
        title="Get Random Subreddit",
    )
    nsfw: Optional[bool] = Field(
        default=False, title="Include NSFW", description="Include NSFW subreddits"
    )


class RedditGetPopularSubredditsConfig(BaseModel):
    """Get popular subreddits"""

    model_config = ConfigDict(populate_by_name=True, title="Get Popular Subreddits")

    operation: Literal["get_popular_subreddits"] = Field(
        default="get_popular_subreddits",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Subreddit",
            "x-is-trigger": False,
            "x-display-name": "Get Popular Subreddits",
        },
        title="Get Popular Subreddits",
    )
    limit: Optional[int] = Field(
        default=25,
        title="Limit",
        description="Number of subreddits to return (max 100)",
    )


class RedditGetNewSubredditsConfig(BaseModel):
    """Get new subreddits"""

    model_config = ConfigDict(populate_by_name=True, title="Get New Subreddits")

    operation: Literal["get_new_subreddits"] = Field(
        default="get_new_subreddits",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Subreddit",
            "x-is-trigger": False,
            "x-display-name": "Get New Subreddits",
        },
        title="Get New Subreddits",
    )
    limit: Optional[int] = Field(
        default=25,
        title="Limit",
        description="Number of subreddits to return (max 100)",
    )


# ============================================================================
# Post Moderation Operations
# ============================================================================


class RedditMarkNsfwConfig(BaseModel):
    """Mark or unmark a post as NSFW"""

    model_config = ConfigDict(populate_by_name=True, title="Mark NSFW")

    operation: Literal["mark_post_as_nsfw"] = Field(
        default="mark_post_as_nsfw",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Mark Post As Nsfw",
        },
        title="Mark Post As Nsfw",
    )
    thing_id: str = Field(
        ..., title="Post ID", description="Full ID of post (t3_xxx) to mark"
    )
    unmark: Optional[bool] = Field(
        default=False, title="Unmark", description="Set to true to unmark NSFW"
    )


class RedditMarkSpoilerConfig(BaseModel):
    """Mark or unmark a post as spoiler"""

    model_config = ConfigDict(populate_by_name=True, title="Mark Spoiler")

    operation: Literal["mark_post_as_spoiler"] = Field(
        default="mark_post_as_spoiler",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Mark Post As Spoiler",
        },
        title="Mark Post As Spoiler",
    )
    thing_id: str = Field(
        ..., title="Post ID", description="Full ID of post (t3_xxx) to mark"
    )
    unmark: Optional[bool] = Field(
        default=False, title="Unmark", description="Set to true to unmark spoiler"
    )


class RedditGetRandomSubmissionConfig(BaseModel):
    """Get a random submission from a subreddit"""

    model_config = ConfigDict(populate_by_name=True, title="Get Random Submission")

    operation: Literal["get_random_submission"] = Field(
        default="get_random_submission",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Get Random Submission",
        },
        title="Get Random Submission",
    )
    subreddit: str = Field(
        ...,
        title="Subreddit",
        description="Subreddit to get random post from (without r/)",
    )


# ============================================================================
# Listing Operations (Front Page & Feeds)
# ============================================================================


class RedditGetBestConfig(BaseModel):
    """Get best posts (personalized front page)"""

    model_config = ConfigDict(populate_by_name=True, title="Get Best")

    operation: Literal["get_best_posts"] = Field(
        default="get_best_posts",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Get Best Posts",
        },
        title="Get Best Posts",
    )
    limit: Optional[int] = Field(
        default=25, title="Limit", description="Number of posts to return (max 100)"
    )
    time: Optional[Literal["hour", "day", "week", "month", "year", "all"]] = Field(
        default="day", title="Time Period", description="Time period filter"
    )


class RedditGetGildedConfig(BaseModel):
    """Get gilded (awarded) content"""

    model_config = ConfigDict(populate_by_name=True, title="Get Gilded")

    operation: Literal["get_gilded_content"] = Field(
        default="get_gilded_content",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Get Gilded Content",
        },
        title="Get Gilded Content",
    )
    subreddit: Optional[str] = Field(
        default=None,
        title="Subreddit",
        description="Subreddit name (leave empty for all)",
    )
    limit: Optional[int] = Field(
        default=25, title="Limit", description="Number of items to return (max 100)"
    )


# ============================================================================
# Additional Message Operations
# ============================================================================


class RedditMarkAllMessagesReadConfig(BaseModel):
    """Mark all messages as read"""

    model_config = ConfigDict(populate_by_name=True, title="Mark All Messages Read")

    operation: Literal["mark_all_messages_as_read"] = Field(
        default="mark_all_messages_as_read",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Mark All Messages As Read",
        },
        title="Mark All Messages As Read",
    )


class RedditUnreadMessageConfig(BaseModel):
    """Mark a message as unread"""

    model_config = ConfigDict(populate_by_name=True, title="Unread Message")

    operation: Literal["mark_messages_as_unread"] = Field(
        default="mark_messages_as_unread",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Mark Messages As Unread",
        },
        title="Mark Messages As Unread",
    )
    thing_ids: str = Field(
        ...,
        title="Message IDs",
        description="Comma-separated list of message IDs (t4_xxx) to mark as unread",
    )


# ============================================================================
# User Flair Operations
# ============================================================================


class RedditGetUserFlairConfig(BaseModel):
    """Get user flair options for a subreddit"""

    model_config = ConfigDict(populate_by_name=True, title="Get User Flair")

    operation: Literal["get_user_flair_options"] = Field(
        default="get_user_flair_options",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get User Flair Options",
        },
        title="Get User Flair Options",
    )
    subreddit: str = Field(
        ...,
        title="Subreddit",
        description="Subreddit to get flair options from (without r/)",
    )


class RedditSetUserFlairConfig(BaseModel):
    """Set user flair in a subreddit"""

    model_config = ConfigDict(populate_by_name=True, title="Set User Flair")

    operation: Literal["set_user_flair_in_subreddit"] = Field(
        default="set_user_flair_in_subreddit",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Set User Flair in Subreddit",
        },
        title="Set User Flair in Subreddit",
    )
    subreddit: str = Field(
        ..., title="Subreddit", description="Subreddit to set flair in (without r/)"
    )
    flair_template_id: Optional[str] = Field(
        default=None,
        title="Flair Template ID",
        description="ID of the flair template to use",
    )
    text: Optional[str] = Field(
        default=None, title="Flair Text", description="Custom flair text (if allowed)"
    )


# ============================================================================
# Wiki Operations
# ============================================================================


class RedditGetWikiPagesConfig(BaseModel):
    """List all wiki pages in a subreddit"""

    model_config = ConfigDict(populate_by_name=True, title="Get Wiki Pages")

    operation: Literal["list_wiki_pages"] = Field(
        default="list_wiki_pages",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Wiki",
            "x-is-trigger": False,
            "x-display-name": "List Wiki Pages",
        },
        title="List Wiki Pages",
    )
    subreddit: str = Field(
        ..., title="Subreddit", description="Subreddit name (without r/)"
    )


class RedditGetWikiPageConfig(BaseModel):
    """Get a specific wiki page"""

    model_config = ConfigDict(populate_by_name=True, title="Get Wiki Page")

    operation: Literal["get_wiki_page"] = Field(
        default="get_wiki_page",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Wiki",
            "x-is-trigger": False,
            "x-display-name": "Get Wiki Page",
        },
        title="Get Wiki Page",
    )
    subreddit: str = Field(
        ..., title="Subreddit", description="Subreddit name (without r/)"
    )
    page: str = Field(
        ..., title="Page Name", description="Wiki page name (e.g., 'index', 'rules')"
    )


class RedditGetWikiRevisionsConfig(BaseModel):
    """Get wiki page revision history"""

    model_config = ConfigDict(populate_by_name=True, title="Get Wiki Revisions")

    operation: Literal["get_wiki_page_revisions"] = Field(
        default="get_wiki_page_revisions",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Wiki",
            "x-is-trigger": False,
            "x-display-name": "Get Wiki Page Revisions",
        },
        title="Get Wiki Page Revisions",
    )
    subreddit: str = Field(
        ..., title="Subreddit", description="Subreddit name (without r/)"
    )
    page: Optional[str] = Field(
        default=None,
        title="Page Name",
        description="Wiki page name (leave empty for all pages)",
    )
    limit: Optional[int] = Field(
        default=25, title="Limit", description="Number of revisions to return (max 100)"
    )


# ============================================================================
# Live Thread Operations
# ============================================================================


class RedditCreateLiveThreadConfig(BaseModel):
    """Create a new live thread"""

    model_config = ConfigDict(populate_by_name=True, title="Create Live Thread")

    operation: Literal["create_live_thread"] = Field(
        default="create_live_thread",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Live Thread",
            "x-is-trigger": False,
            "x-display-name": "Create Live Thread",
        },
        title="Create Live Thread",
    )
    title: str = Field(..., title="Title", description="Title of the live thread")
    description: Optional[str] = Field(
        default=None,
        title="Description",
        description="Description of the live thread (Markdown supported)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    nsfw: Optional[bool] = Field(
        default=False, title="NSFW", description="Mark as NSFW content"
    )


class RedditGetLiveThreadConfig(BaseModel):
    """Get live thread information"""

    model_config = ConfigDict(populate_by_name=True, title="Get Live Thread")

    operation: Literal["get_live_thread"] = Field(
        default="get_live_thread",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Live Thread",
            "x-is-trigger": False,
            "x-display-name": "Get Live Thread",
        },
        title="Get Live Thread",
    )
    thread_id: str = Field(..., title="Thread ID", description="Live thread ID")


class RedditGetLiveThreadUpdatesConfig(BaseModel):
    """Get updates from a live thread"""

    model_config = ConfigDict(populate_by_name=True, title="Get Live Thread Updates")

    operation: Literal["get_live_thread_updates"] = Field(
        default="get_live_thread_updates",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Live Thread",
            "x-is-trigger": False,
            "x-display-name": "Get Live Thread Updates",
        },
        title="Get Live Thread Updates",
    )
    thread_id: str = Field(..., title="Thread ID", description="Live thread ID")
    limit: Optional[int] = Field(
        default=25, title="Limit", description="Number of updates to return (max 100)"
    )


class RedditUpdateLiveThreadConfig(BaseModel):
    """Post an update to a live thread"""

    model_config = ConfigDict(populate_by_name=True, title="Update Live Thread")

    operation: Literal["post_live_thread_update"] = Field(
        default="post_live_thread_update",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Live Thread",
            "x-is-trigger": False,
            "x-display-name": "Post Live Thread Update",
        },
        title="Post Live Thread Update",
    )
    thread_id: str = Field(..., title="Thread ID", description="Live thread ID")
    body: str = Field(
        ...,
        title="Update Text",
        description="The update content (Markdown supported)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class RedditCloseLiveThreadConfig(BaseModel):
    """Close a live thread"""

    model_config = ConfigDict(populate_by_name=True, title="Close Live Thread")

    operation: Literal["close_live_thread"] = Field(
        default="close_live_thread",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Live Thread",
            "x-is-trigger": False,
            "x-display-name": "Close Live Thread",
        },
        title="Close Live Thread",
    )
    thread_id: str = Field(
        ..., title="Thread ID", description="Live thread ID to close"
    )


# ============================================================================
# Additional Multireddit Operations
# ============================================================================


class RedditCreateMultiredditConfig(BaseModel):
    """Create a new multireddit"""

    model_config = ConfigDict(populate_by_name=True, title="Create Multireddit")

    operation: Literal["create_multireddit"] = Field(
        default="create_multireddit",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Multireddit",
            "x-is-trigger": False,
            "x-display-name": "Create Multireddit",
        },
        title="Create Multireddit",
    )
    name: str = Field(..., title="Name", description="Name for the multireddit")
    description: Optional[str] = Field(
        default=None,
        title="Description",
        description="Description of the multireddit (Markdown supported)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    subreddits: str = Field(
        ...,
        title="Subreddits",
        description="Comma-separated list of subreddits to include",
    )
    visibility: Optional[Literal["private", "public", "hidden"]] = Field(
        default="private",
        title="Visibility",
        description="Visibility of the multireddit",
    )


class RedditDeleteMultiredditConfig(BaseModel):
    """Delete a multireddit"""

    model_config = ConfigDict(populate_by_name=True, title="Delete Multireddit")

    operation: Literal["delete_multireddit"] = Field(
        default="delete_multireddit",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Multireddit",
            "x-is-trigger": False,
            "x-display-name": "Delete Multireddit",
        },
        title="Delete Multireddit",
    )
    multiname: str = Field(
        ..., title="Multireddit Name", description="Name of the multireddit to delete"
    )


class RedditUpdateMultiredditConfig(BaseModel):
    """Update a multireddit"""

    model_config = ConfigDict(populate_by_name=True, title="Update Multireddit")

    operation: Literal["update_multireddit"] = Field(
        default="update_multireddit",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Multireddit",
            "x-is-trigger": False,
            "x-display-name": "Update Multireddit",
        },
        title="Update Multireddit",
    )
    multiname: str = Field(
        ..., title="Multireddit Name", description="Name of the multireddit to update"
    )
    description: Optional[str] = Field(
        default=None,
        title="Description",
        description="New description (Markdown supported)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    visibility: Optional[Literal["private", "public", "hidden"]] = Field(
        default=None, title="Visibility", description="New visibility setting"
    )


class RedditAddSubredditToMultiConfig(BaseModel):
    """Add a subreddit to a multireddit"""

    model_config = ConfigDict(populate_by_name=True, title="Add Subreddit to Multi")

    operation: Literal["add_subreddit_to_multireddit"] = Field(
        default="add_subreddit_to_multireddit",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Subreddit",
            "x-is-trigger": False,
            "x-display-name": "Add Subreddit to Multireddit",
        },
        title="Add Subreddit to Multireddit",
    )
    multiname: str = Field(
        ..., title="Multireddit Name", description="Name of the multireddit"
    )
    subreddit: str = Field(
        ..., title="Subreddit", description="Subreddit to add (without r/)"
    )


class RedditRemoveSubredditFromMultiConfig(BaseModel):
    """Remove a subreddit from a multireddit"""

    model_config = ConfigDict(
        populate_by_name=True, title="Remove Subreddit from Multi"
    )

    operation: Literal["remove_subreddit_from_multireddit"] = Field(
        default="remove_subreddit_from_multireddit",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Subreddit",
            "x-is-trigger": False,
            "x-display-name": "Remove Subreddit from Multireddit",
        },
        title="Remove Subreddit from Multireddit",
    )
    multiname: str = Field(
        ..., title="Multireddit Name", description="Name of the multireddit"
    )
    subreddit: str = Field(
        ..., title="Subreddit", description="Subreddit to remove (without r/)"
    )


# ============================================================================
# Miscellaneous Operations
# ============================================================================


class RedditGetSubredditCommentsConfig(BaseModel):
    """Get recent comments from a subreddit"""

    model_config = ConfigDict(populate_by_name=True, title="Get Subreddit Comments")

    operation: Literal["get_subreddit_comments"] = Field(
        default="get_subreddit_comments",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Subreddit",
            "x-is-trigger": False,
            "x-display-name": "Get Subreddit Comments",
        },
        title="Get Subreddit Comments",
    )
    subreddit: str = Field(
        ..., title="Subreddit", description="Subreddit name (without r/)"
    )
    limit: Optional[int] = Field(
        default=25, title="Limit", description="Number of comments to return (max 100)"
    )


# ============================================================================
# Additional API Operations (From official Reddit API docs)
# ============================================================================


class RedditGetInfoConfig(BaseModel):
    """Get info about things by fullname (batch query)"""

    model_config = ConfigDict(populate_by_name=True, title="Get Info")

    operation: Literal["get_info_by_fullname_batch"] = Field(
        default="get_info_by_fullname_batch",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Misc",
            "x-is-trigger": False,
            "x-display-name": "Get Info by Fullname Batch",
        },
        title="Get Info by Fullname Batch",
    )
    ids: str = Field(
        ...,
        title="IDs",
        description="Comma-separated list of fullnames (t1_, t2_, t3_, t4_, t5_, t6_)",
    )


class RedditGetMoreCommentsConfig(BaseModel):
    """Load more comments from a 'more' object"""

    model_config = ConfigDict(populate_by_name=True, title="Get More Comments")

    operation: Literal["load_more_comments"] = Field(
        default="load_more_comments",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Load More Comments",
        },
        title="Load More Comments",
    )
    link_id: str = Field(
        ..., title="Link ID", description="Fullname of the link (post) - t3_xxx"
    )
    children: str = Field(
        ...,
        title="Children",
        description="Comma-separated list of comment IDs to fetch",
    )
    sort: Optional[
        Literal["confidence", "top", "new", "controversial", "old", "qa"]
    ] = Field(default="confidence", title="Sort", description="How to sort comments")


class RedditLockConfig(BaseModel):
    """Lock a post or comment (moderator only)"""

    model_config = ConfigDict(populate_by_name=True, title="Lock")

    operation: Literal["lock_post_or_comment"] = Field(
        default="lock_post_or_comment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Lock Post or Comment",
        },
        title="Lock Post or Comment",
    )
    thing_id: str = Field(
        ...,
        title="Thing ID",
        description="Full ID of post (t3_xxx) or comment (t1_xxx) to lock",
    )
    unlock: Optional[bool] = Field(
        default=False,
        title="Unlock",
        description="Set to true to unlock instead of lock",
    )


class RedditApproveConfig(BaseModel):
    """Approve a post or comment (moderator only)"""

    model_config = ConfigDict(populate_by_name=True, title="Approve")

    operation: Literal["approve_post_or_comment"] = Field(
        default="approve_post_or_comment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Approve Post or Comment",
        },
        title="Approve Post or Comment",
    )
    thing_id: str = Field(
        ...,
        title="Thing ID",
        description="Full ID of post (t3_xxx) or comment (t1_xxx) to approve",
    )


class RedditRemoveConfig(BaseModel):
    """Remove a post or comment (moderator only)"""

    model_config = ConfigDict(populate_by_name=True, title="Remove")

    operation: Literal["remove_post_or_comment"] = Field(
        default="remove_post_or_comment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Remove Post or Comment",
        },
        title="Remove Post or Comment",
    )
    thing_id: str = Field(
        ...,
        title="Thing ID",
        description="Full ID of post (t3_xxx) or comment (t1_xxx) to remove",
    )
    spam: Optional[bool] = Field(
        default=False, title="Mark as Spam", description="Mark the item as spam"
    )


class RedditDistinguishConfig(BaseModel):
    """Distinguish a post or comment as moderator"""

    model_config = ConfigDict(populate_by_name=True, title="Distinguish")

    operation: Literal["distinguish_post_or_comment"] = Field(
        default="distinguish_post_or_comment",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Distinguish Post or Comment",
        },
        title="Distinguish Post or Comment",
    )
    thing_id: str = Field(
        ...,
        title="Thing ID",
        description="Full ID of post (t3_xxx) or comment (t1_xxx)",
    )
    how: Literal["yes", "no", "admin", "special"] = Field(
        default="yes",
        title="How",
        description="yes=mod, no=remove, admin=admin (admin only), special=special",
    )
    sticky: Optional[bool] = Field(
        default=False,
        title="Sticky",
        description="Make the comment sticky (top-level comments only)",
    )


class RedditStickyPostConfig(BaseModel):
    """Sticky or unsticky a post in a subreddit (moderator only)"""

    model_config = ConfigDict(populate_by_name=True, title="Sticky Post")

    operation: Literal["sticky_or_unsticky_post"] = Field(
        default="sticky_or_unsticky_post",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Sticky or Unsticky Post",
        },
        title="Sticky or Unsticky Post",
    )
    thing_id: str = Field(
        ..., title="Post ID", description="Full ID of post (t3_xxx) to sticky"
    )
    state: Optional[bool] = Field(
        default=True, title="Sticky", description="True to sticky, False to unsticky"
    )
    num: Optional[Literal[1, 2]] = Field(
        default=None, title="Slot", description="Sticky slot (1 or 2)"
    )


class RedditSetContestModeConfig(BaseModel):
    """Set or unset contest mode on a post (moderator only)"""

    model_config = ConfigDict(populate_by_name=True, title="Set Contest Mode")

    operation: Literal["set_post_contest_mode"] = Field(
        default="set_post_contest_mode",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Set Post Contest Mode",
        },
        title="Set Post Contest Mode",
    )
    thing_id: str = Field(..., title="Post ID", description="Full ID of post (t3_xxx)")
    state: Optional[bool] = Field(
        default=True,
        title="Enable",
        description="True to enable, False to disable contest mode",
    )


class RedditSetSuggestedSortConfig(BaseModel):
    """Set suggested sort for a post (moderator only)"""

    model_config = ConfigDict(populate_by_name=True, title="Set Suggested Sort")

    operation: Literal["set_post_suggested_sort"] = Field(
        default="set_post_suggested_sort",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Set Post Suggested Sort",
        },
        title="Set Post Suggested Sort",
    )
    thing_id: str = Field(..., title="Post ID", description="Full ID of post (t3_xxx)")
    sort: Optional[
        Literal[
            "confidence", "top", "new", "controversial", "old", "qa", "live", "blank"
        ]
    ] = Field(
        default="blank", title="Sort", description="Suggested sort (blank to clear)"
    )


class RedditSendRepliesConfig(BaseModel):
    """Enable or disable inbox replies for a post or comment"""

    model_config = ConfigDict(populate_by_name=True, title="Send Replies")

    operation: Literal["toggle_post_inbox_replies"] = Field(
        default="toggle_post_inbox_replies",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Toggle Post Inbox Replies",
        },
        title="Toggle Post Inbox Replies",
    )
    thing_id: str = Field(
        ...,
        title="Thing ID",
        description="Full ID of post (t3_xxx) or comment (t1_xxx)",
    )
    state: Optional[bool] = Field(
        default=True,
        title="Enable",
        description="True to enable, False to disable inbox replies",
    )


class RedditGetDefaultSubredditsConfig(BaseModel):
    """Get default subreddits"""

    model_config = ConfigDict(populate_by_name=True, title="Get Default Subreddits")

    operation: Literal["get_default_subreddits"] = Field(
        default="get_default_subreddits",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Subreddit",
            "x-is-trigger": False,
            "x-display-name": "Get Default Subreddits",
        },
        title="Get Default Subreddits",
    )
    limit: Optional[int] = Field(
        default=25,
        title="Limit",
        description="Number of subreddits to return (max 100)",
    )


class RedditGetBlockedUsersConfig(BaseModel):
    """Get the authenticated user's blocked users"""

    model_config = ConfigDict(populate_by_name=True, title="Get Blocked Users")

    operation: Literal["get_blocked_users"] = Field(
        default="get_blocked_users",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get Blocked Users",
        },
        title="Get Blocked Users",
    )


class RedditUnblockUserConfig(BaseModel):
    """Unblock a user"""

    model_config = ConfigDict(populate_by_name=True, title="Unblock User")

    operation: Literal["unblock_user"] = Field(
        default="unblock_user",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Unblock User",
        },
        title="Unblock User",
    )
    username: str = Field(
        ..., title="Username", description="Username to unblock (without u/)"
    )


class RedditGetSubredditTrafficConfig(BaseModel):
    """Get subreddit traffic statistics (moderator only)"""

    model_config = ConfigDict(populate_by_name=True, title="Get Subreddit Traffic")

    operation: Literal["get_subreddit_traffic_stats"] = Field(
        default="get_subreddit_traffic_stats",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Subreddit",
            "x-is-trigger": False,
            "x-display-name": "Get Subreddit Traffic Stats",
        },
        title="Get Subreddit Traffic Stats",
    )
    subreddit: str = Field(
        ..., title="Subreddit", description="Subreddit name (without r/)"
    )


class RedditIgnoreReportsConfig(BaseModel):
    """Ignore or unignore reports on a post or comment (moderator only)"""

    model_config = ConfigDict(populate_by_name=True, title="Ignore Reports")

    operation: Literal["ignore_reports_on_content"] = Field(
        default="ignore_reports_on_content",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Ignore Reports on Content",
        },
        title="Ignore Reports on Content",
    )
    thing_id: str = Field(
        ...,
        title="Thing ID",
        description="Full ID of post (t3_xxx) or comment (t1_xxx)",
    )
    unignore: Optional[bool] = Field(
        default=False, title="Unignore", description="Set to true to unignore reports"
    )


# Discriminated union uses 'operation' field to determine which config type to parse
RedditConfig = Annotated[
    Union[
        # User operations
        RedditGetMeConfig,
        RedditGetUserConfig,
        RedditGetUserPostsConfig,
        RedditGetUserCommentsConfig,
        RedditGetUserSavedConfig,
        RedditGetTrophiesConfig,
        RedditBlockUserConfig,
        RedditGetFriendsConfig,
        RedditGetKarmaConfig,
        RedditGetPreferencesConfig,
        RedditCheckUsernameConfig,
        RedditReportUserConfig,
        # Subreddit operations
        RedditGetSubredditPostsConfig,
        RedditGetSubredditInfoConfig,
        RedditGetSubredditRulesConfig,
        RedditGetMySubredditsConfig,
        RedditSubscribeConfig,
        RedditSearchSubredditsConfig,
        RedditGetSubredditModeratorsConfig,
        RedditGetRandomSubredditConfig,
        RedditGetPopularSubredditsConfig,
        RedditGetNewSubredditsConfig,
        RedditGetSubredditCommentsConfig,
        # Post operations
        RedditGetPostConfig,
        RedditGetPostCommentsConfig,
        RedditGetDuplicatesConfig,
        RedditSubmitTextPostConfig,
        RedditSubmitLinkPostConfig,
        RedditCrosspostConfig,
        RedditHideConfig,
        RedditReportConfig,
        RedditMarkNsfwConfig,
        RedditMarkSpoilerConfig,
        RedditGetRandomSubmissionConfig,
        # Comment operations
        RedditSubmitCommentConfig,
        # Common actions
        RedditVoteConfig,
        RedditEditConfig,
        RedditDeleteConfig,
        RedditSaveConfig,
        # Flair
        RedditGetLinkFlairConfig,
        RedditSetLinkFlairConfig,
        RedditGetUserFlairConfig,
        RedditSetUserFlairConfig,
        # Listings/Feeds
        RedditGetBestConfig,
        RedditGetGildedConfig,
        # Search
        RedditSearchConfig,
        # Multireddits
        RedditGetMultiredditConfig,
        RedditGetMyMultiredditsConfig,
        RedditGetMultiredditPostsConfig,
        RedditCreateMultiredditConfig,
        RedditDeleteMultiredditConfig,
        RedditUpdateMultiredditConfig,
        RedditAddSubredditToMultiConfig,
        RedditRemoveSubredditFromMultiConfig,
        # Messages
        RedditSendMessageConfig,
        RedditGetInboxConfig,
        RedditMarkMessagesReadConfig,
        RedditDeleteMessageConfig,
        RedditReplyMessageConfig,
        RedditMarkAllMessagesReadConfig,
        RedditUnreadMessageConfig,
        # Wiki
        RedditGetWikiPagesConfig,
        RedditGetWikiPageConfig,
        RedditGetWikiRevisionsConfig,
        # Live Threads
        RedditCreateLiveThreadConfig,
        RedditGetLiveThreadConfig,
        RedditGetLiveThreadUpdatesConfig,
        RedditUpdateLiveThreadConfig,
        RedditCloseLiveThreadConfig,
        # Awards
        RedditGiveAwardConfig,
        # Additional API operations
        RedditGetInfoConfig,
        RedditGetMoreCommentsConfig,
        RedditLockConfig,
        RedditApproveConfig,
        RedditRemoveConfig,
        RedditDistinguishConfig,
        RedditStickyPostConfig,
        RedditSetContestModeConfig,
        RedditSetSuggestedSortConfig,
        RedditSendRepliesConfig,
        RedditGetDefaultSubredditsConfig,
        RedditGetBlockedUsersConfig,
        RedditUnblockUserConfig,
        RedditGetSubredditTrafficConfig,
        RedditIgnoreReportsConfig,
    ],
    Discriminator("operation"),
]


class RedditNodeConfig(NodeConfig[RedditConfig, RedditCredential]):
    """Full configuration for Reddit node including credentials"""

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_public_feed_operation(cls, data: Any) -> Any:
        """Map the removed RSS alias onto the canonical subreddit-posts op."""
        if not isinstance(data, dict):
            return data

        config = data.get("config")
        if not isinstance(config, dict):
            return data

        if config.get("operation") == "get_subreddit_posts_via_rss":
            config["operation"] = "get_subreddit_posts"
        elif config.get("operation") == "get_subreddit_top_posts":
            config["operation"] = "get_subreddit_posts"
            config["sort"] = "top"
        elif config.get("operation") == "get_rising_posts":
            config["operation"] = "get_subreddit_posts"
            config["sort"] = "rising"
        elif config.get("operation") == "get_controversial_posts":
            config["operation"] = "get_subreddit_posts"
            config["sort"] = "controversial"

        return data


# ============================================================================
# Reddit Node Implementation
# ============================================================================


class RedditNode(WorkflowNode):
    """
    Reddit API automation node.

    Executes Reddit operations via the Reddit API for workflow automation.
    Supports multiple actions - user selects one in the config.
    """

    edit_examples = [
        "Submit a text post about Python tutorials to r/learnprogramming",
        "Search Reddit for posts about climate change in r/science",
        "Get top comments from a post about AI safety in the last week",
        "Post a comment replying to a discussion about machine learning",
        "Fetch public subreddit posts from r/python this month without Reddit credentials",
        "Vote on posts and comments in r/technology",
    ]

    scope_registry = REDDIT_SCOPES
    connection_evidence = ConnectionEvidence(
        operation="get_my_subscribed_subreddits",
        noun="subreddits",
        identity_operation="get_authenticated_user_info",
    )

    @classmethod
    def get_config_model(cls):
        return RedditNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute Reddit action via API."""
        logger.info(f"[RedditNode] Executing node {self.node_id}")

        node_config = self.config
        if not node_config or not isinstance(node_config, RedditNodeConfig):
            raise ValueError("RedditNode requires valid configuration")

        config = node_config.config
        credentials = node_config.credentials

        is_public_feed_operation = config.operation == "get_subreddit_posts"

        if not credentials and not is_public_feed_operation:
            raise ValueError(
                "[RedditNode] Credentials are required for this operation. "
                "Please connect your Reddit account in the node's credentials tab. "
                "(Public feed operations do not require credentials)"
            )

        # Route to appropriate handler based on config type
        action_handlers = {
            # User operations
            RedditGetMeConfig: self._get_me,
            RedditGetUserConfig: self._get_user,
            RedditGetUserPostsConfig: self._get_user_posts,
            RedditGetUserCommentsConfig: self._get_user_comments,
            RedditGetUserSavedConfig: self._get_user_saved,
            RedditGetTrophiesConfig: self._get_trophies,
            RedditBlockUserConfig: self._block_user,
            RedditGetFriendsConfig: self._get_friends,
            RedditGetKarmaConfig: self._get_karma,
            RedditGetPreferencesConfig: self._get_preferences,
            RedditCheckUsernameConfig: self._check_username,
            RedditReportUserConfig: self._report_user,
            # Subreddit operations
            RedditGetSubredditPostsConfig: self._get_subreddit_posts,
            RedditGetSubredditInfoConfig: self._get_subreddit_info,
            RedditGetSubredditRulesConfig: self._get_subreddit_rules,
            RedditGetMySubredditsConfig: self._get_my_subreddits,
            RedditSubscribeConfig: self._subscribe,
            RedditSearchSubredditsConfig: self._search_subreddits,
            RedditGetSubredditModeratorsConfig: self._get_subreddit_moderators,
            RedditGetRandomSubredditConfig: self._get_random_subreddit,
            RedditGetPopularSubredditsConfig: self._get_popular_subreddits,
            RedditGetNewSubredditsConfig: self._get_new_subreddits,
            RedditGetSubredditCommentsConfig: self._get_subreddit_comments,
            # Post operations
            RedditGetPostConfig: self._get_post,
            RedditGetPostCommentsConfig: self._get_post_comments,
            RedditGetDuplicatesConfig: self._get_duplicates,
            RedditSubmitTextPostConfig: self._submit_text_post,
            RedditSubmitLinkPostConfig: self._submit_link_post,
            RedditCrosspostConfig: self._crosspost,
            RedditHideConfig: self._hide,
            RedditReportConfig: self._report,
            RedditMarkNsfwConfig: self._mark_nsfw,
            RedditMarkSpoilerConfig: self._mark_spoiler,
            RedditGetRandomSubmissionConfig: self._get_random_submission,
            # Comment operations
            RedditSubmitCommentConfig: self._submit_comment,
            # Common actions
            RedditVoteConfig: self._vote,
            RedditEditConfig: self._edit,
            RedditDeleteConfig: self._delete,
            RedditSaveConfig: self._save,
            # Flair
            RedditGetLinkFlairConfig: self._get_link_flair,
            RedditSetLinkFlairConfig: self._set_link_flair,
            RedditGetUserFlairConfig: self._get_user_flair,
            RedditSetUserFlairConfig: self._set_user_flair,
            # Listings/Feeds
            RedditGetBestConfig: self._get_best,
            RedditGetGildedConfig: self._get_gilded,
            # Search
            RedditSearchConfig: self._search,
            # Multireddits
            RedditGetMultiredditConfig: self._get_multireddit,
            RedditGetMyMultiredditsConfig: self._get_my_multireddits,
            RedditGetMultiredditPostsConfig: self._get_multireddit_posts,
            RedditCreateMultiredditConfig: self._create_multireddit,
            RedditDeleteMultiredditConfig: self._delete_multireddit,
            RedditUpdateMultiredditConfig: self._update_multireddit,
            RedditAddSubredditToMultiConfig: self._add_subreddit_to_multi,
            RedditRemoveSubredditFromMultiConfig: self._remove_subreddit_from_multi,
            # Messages
            RedditSendMessageConfig: self._send_message,
            RedditGetInboxConfig: self._get_inbox,
            RedditMarkMessagesReadConfig: self._mark_messages_read,
            RedditDeleteMessageConfig: self._delete_message,
            RedditReplyMessageConfig: self._reply_message,
            RedditMarkAllMessagesReadConfig: self._mark_all_messages_read,
            RedditUnreadMessageConfig: self._unread_message,
            # Wiki
            RedditGetWikiPagesConfig: self._get_wiki_pages,
            RedditGetWikiPageConfig: self._get_wiki_page,
            RedditGetWikiRevisionsConfig: self._get_wiki_revisions,
            # Live Threads
            RedditCreateLiveThreadConfig: self._create_live_thread,
            RedditGetLiveThreadConfig: self._get_live_thread,
            RedditGetLiveThreadUpdatesConfig: self._get_live_thread_updates,
            RedditUpdateLiveThreadConfig: self._update_live_thread,
            RedditCloseLiveThreadConfig: self._close_live_thread,
            # Awards
            RedditGiveAwardConfig: self._give_award,
            # Additional API operations
            RedditGetInfoConfig: self._get_info,
            RedditGetMoreCommentsConfig: self._get_more_comments,
            RedditLockConfig: self._lock,
            RedditApproveConfig: self._approve,
            RedditRemoveConfig: self._remove,
            RedditDistinguishConfig: self._distinguish,
            RedditStickyPostConfig: self._sticky_post,
            RedditSetContestModeConfig: self._set_contest_mode,
            RedditSetSuggestedSortConfig: self._set_suggested_sort,
            RedditSendRepliesConfig: self._send_replies,
            RedditGetDefaultSubredditsConfig: self._get_default_subreddits,
            RedditGetBlockedUsersConfig: self._get_blocked_users,
            RedditUnblockUserConfig: self._unblock_user,
            RedditGetSubredditTrafficConfig: self._get_subreddit_traffic,
            RedditIgnoreReportsConfig: self._ignore_reports,
        }

        handler = action_handlers.get(type(config))
        if not handler:
            raise ValueError(f"Unknown config type: {type(config)}")

        return await handler(config, credentials)

    # Process-local script-token cache, isolated by every authority-bearing
    # credential field and refreshed before the provider expiry.
    _script_token_cache = OAuthTokenCache(refresh_skew_seconds=60)

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        """Refresh an expiring OAuth token at credential load (dropdowns,
        trigger registration). No-op for non-rotating credentials (API keys /
        offline / non-expiring tokens)."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.reddit_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token,
            provider="reddit",
        )

    async def _get_access_token(self, credentials: RedditCredential) -> str:
        """Get access token from credentials.

        For OAuth credentials: refresh the rotating token if expired (Reddit
        access tokens live ~1h), persist, and return the fresh one.
        For Script credentials: Fetches a new token using the Reddit API.
        """
        if isinstance(credentials, RedditOAuthCredential):
            from nodes.core.oauth_refresh import ensure_fresh_oauth_token
            from nodes.oauth.reddit_oauth import refresh_access_token
            
            cred_dict = credentials.model_dump()
            token = await ensure_fresh_oauth_token(
                credential_id=(self.node_data or {}).get("credential_id"),
                user_id=self.user_id,
                credential=cred_dict,
                refresh=refresh_access_token,
                provider="reddit",
            )
            # Mirror the refreshed tokens back onto the in-memory model.
            credentials.access_token = cred_dict["access_token"]
            credentials.expires_at = cred_dict.get("expires_at")
            if cred_dict.get("refresh_token"):
                credentials.refresh_token = cred_dict["refresh_token"]
            return token
        elif isinstance(credentials, RedditScriptCredential):
            return await self._fetch_script_token(credentials)
        else:
            raise ValueError(f"Unknown credential type: {type(credentials)}")

    async def _fetch_script_token(self, credentials: RedditScriptCredential) -> str:
        """Fetch an access token using script/password credentials.

        Reddit script apps use HTTP Basic Auth with client_id:client_secret
        and grant_type=password with the user's Reddit credentials.
        """
        token_url = "https://www.reddit.com/api/v1/access_token"
        cache_key = oauth_authority_digest(
            provider="reddit-script",
            token_url=token_url,
            grant_type="password",
            client_id=credentials.client_id,
            client_secret=credentials.client_secret,
            username=credentials.username,
            password=credentials.password,
        )
        cached = self._script_token_cache.get(cache_key, now=time.monotonic())
        if cached:
            return cached

        async with httpx.AsyncClient() as client:
            response = await client.post(
                token_url,
                auth=(credentials.client_id, credentials.client_secret),
                data={
                    "grant_type": "password",
                    "username": credentials.username,
                    "password": credentials.password,
                },
                headers={"User-Agent": USER_AGENT},
                timeout=30.0,
            )

            if response.status_code != 200:
                error_text = response.text
                logger.error(
                    f"[RedditNode] Token fetch failed: {response.status_code} - {error_text}"
                )
                raise ValueError(
                    f"Failed to authenticate with Reddit. "
                    f"Please verify your client_id, client_secret, username, and password. "
                    f"Error: {error_text}"
                )

            token_data = response.json()
            access_token = token_data.get("access_token")

            if not access_token:
                raise ValueError("Reddit API did not return an access token")

            self._script_token_cache.put(
                cache_key,
                access_token,
                expires_in=token_expiry_input(token_data),
                now=time.monotonic(),
            )
            logger.info(
                f"[RedditNode] Successfully obtained script token for {credentials.username}"
            )

            return access_token

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        credentials: RedditCredential,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        action_name: str = "request",
    ) -> Dict[str, Any]:
        """Make an authenticated Reddit API request with timing."""
        total_start = time.time()

        access_token = await self._get_access_token(credentials)
        headers = {
            "Authorization": f"Bearer {access_token}",
            "User-Agent": USER_AGENT,
        }

        url = f"{REDDIT_API_BASE}{endpoint}"

        # Filter out None params
        if params:
            params = {k: v for k, v in params.items() if v is not None}

        async with httpx.AsyncClient() as client:
            api_start = time.time()
            logger.info(f"[RedditNode] 🔌 {method} {endpoint}")

            response = await client.request(
                method, url, headers=headers, params=params, data=data, timeout=30.0
            )

            api_time = time.time() - api_start
            total_time = time.time() - total_start

            logger.info(
                f"[RedditNode] ✅ {action_name} completed: "
                f"status={response.status_code}, "
                f"api_time={api_time:.3f}s, "
                f"total_time={total_time:.3f}s"
            )

            if response.status_code >= 400:
                error_text = response.text
                logger.error(
                    f"[RedditNode] API error: {response.status_code} - {error_text}"
                )
                raise ValueError(
                    f"Reddit API error ({response.status_code}): {error_text}"
                )

            # Handle empty responses (some endpoints return nothing on success)
            if response.status_code == 204 or not response.text:
                return {"success": True}

            return response.json()

    def _normalize_thing_id(self, thing_id: str, prefix: str = "t3_") -> str:
        """Ensure thing ID has the correct prefix."""
        if thing_id.startswith("t1_") or thing_id.startswith("t3_"):
            return thing_id
        return f"{prefix}{thing_id}"

    # ========== User Operations ==========

    async def _get_me(
        self, config: RedditGetMeConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Get the authenticated user's information."""
        result = await self._make_request(
            "GET", "/api/v1/me", credentials, action_name="get_authenticated_user_info"
        )
        return {"user": result}

    async def _get_user(
        self, config: RedditGetUserConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Get information about a specific user."""
        result = await self._make_request(
            "GET", f"/user/{config.username}/about", credentials, action_name="get_user_info"
        )
        return {"user": result.get("data", result)}

    async def _get_user_posts(
        self, config: RedditGetUserPostsConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Get posts by a specific user."""
        params = {
            "sort": config.sort,
            "t": config.time,
            "limit": min(config.limit or 25, 100),
        }
        result = await self._make_request(
            "GET",
            f"/user/{config.username}/submitted",
            credentials,
            params=params,
            action_name="get_user_posts",
        )
        posts = [child["data"] for child in result.get("data", {}).get("children", [])]
        return {"posts": posts, "count": len(posts)}

    async def _get_user_comments(
        self, config: RedditGetUserCommentsConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Get comments by a specific user."""
        params = {
            "sort": config.sort,
            "t": config.time,
            "limit": min(config.limit or 25, 100),
        }
        result = await self._make_request(
            "GET",
            f"/user/{config.username}/comments",
            credentials,
            params=params,
            action_name="get_user_comments",
        )
        comments = [
            child["data"] for child in result.get("data", {}).get("children", [])
        ]
        return {"comments": comments, "count": len(comments)}

    # ========== Subreddit Operations ==========

    async def _get_subreddit_posts(self, config: RedditGetSubredditPostsConfig, credentials: RedditCredential) -> Dict[str, Any]:
        """Fetch subreddit posts from Reddit's public endpoints only."""
        return await self._fetch_public_subreddit_posts(
            subreddit=config.subreddit,
            sort=config.sort or "",
            time_period=config.time if config.sort in ["top", "controversial"] else None,
            limit=config.limit,
            fetch_comments=config.fetch_comments,
            use_proxy=config.use_proxy,
            content_mode=config.content_mode,
        )

    async def _get_subreddit_info(
        self, config: RedditGetSubredditInfoConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Get information about a subreddit."""
        result = await self._make_request(
            "GET",
            f"/r/{config.subreddit}/about",
            credentials,
            action_name="get_subreddit_info",
        )
        return {"subreddit": result.get("data", result)}

    async def _get_my_subreddits(
        self, config: RedditGetMySubredditsConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Get the authenticated user's subscribed subreddits."""
        params = {
            "limit": min(config.limit or 25, 100),
        }
        result = await self._make_request(
            "GET",
            f"/subreddits/mine/{config.where}",
            credentials,
            params=params,
            action_name="get_my_subscribed_subreddits",
        )
        subreddits = [
            child["data"] for child in result.get("data", {}).get("children", [])
        ]
        return {"subreddits": subreddits, "count": len(subreddits)}

    async def _subscribe(
        self, config: RedditSubscribeConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Subscribe or unsubscribe from a subreddit."""
        action = "unsub" if config.unsubscribe else "sub"
        data = {
            "action": action,
            "sr_name": config.subreddit,
        }
        await self._make_request(
            "POST", "/api/subscribe", credentials, data=data, action_name="subscribe_to_subreddit"
        )
        return {
            "success": True,
            "subreddit": config.subreddit,
            "action": "unsubscribed" if config.unsubscribe else "subscribed",
        }

    # ========== Post Operations ==========

    async def _get_post(
        self, config: RedditGetPostConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Get a specific post by ID."""
        post_id = config.post_id
        if post_id.startswith("t3_"):
            post_id = post_id[3:]

        result = await self._make_request(
            "GET",
            f"/api/info",
            credentials,
            params={"id": f"t3_{post_id}"},
            action_name="get_post",
        )
        posts = result.get("data", {}).get("children", [])
        if not posts:
            raise ValueError(f"Post not found: {config.post_id}")
        return {"post": posts[0]["data"]}

    async def _get_post_comments(
        self, config: RedditGetPostCommentsConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Get comments on a post."""
        post_id = config.post_id
        if post_id.startswith("t3_"):
            post_id = post_id[3:]

        params = {
            "sort": config.sort,
            "limit": min(config.limit or 25, 100),
        }
        result = await self._make_request(
            "GET",
            f"/comments/{post_id}",
            credentials,
            params=params,
            action_name="get_post_comments",
        )

        # Result is [post, comments]
        if isinstance(result, list) and len(result) > 1:
            post_data = (
                result[0]["data"]["children"][0]["data"]
                if result[0].get("data", {}).get("children")
                else {}
            )
            comments = [
                child["data"] for child in result[1].get("data", {}).get("children", [])
            ]
            return {"post": post_data, "comments": comments, "count": len(comments)}

        return {"comments": [], "count": 0}

    async def _submit_text_post(
        self, config: RedditSubmitTextPostConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Submit a text post to a subreddit."""
        data = {
            "kind": "self",
            "sr": config.subreddit,
            "title": config.title,
            "text": config.text,
            "nsfw": config.nsfw,
            "spoiler": config.spoiler,
            "api_type": "json",
        }
        result = await self._make_request(
            "POST",
            "/api/submit",
            credentials,
            data=data,
            action_name="submit_text_post",
        )
        json_data = result.get("json", {}).get("data", {})
        return {
            "success": True,
            "id": json_data.get("id"),
            "name": json_data.get("name"),
            "url": json_data.get("url"),
        }

    async def _submit_link_post(
        self, config: RedditSubmitLinkPostConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Submit a link post to a subreddit."""
        data = {
            "kind": "link",
            "sr": config.subreddit,
            "title": config.title,
            "url": config.url,
            "nsfw": config.nsfw,
            "spoiler": config.spoiler,
            "api_type": "json",
        }
        result = await self._make_request(
            "POST",
            "/api/submit",
            credentials,
            data=data,
            action_name="submit_link_post",
        )
        json_data = result.get("json", {}).get("data", {})
        return {
            "success": True,
            "id": json_data.get("id"),
            "name": json_data.get("name"),
            "url": json_data.get("url"),
        }

    # ========== Comment Operations ==========

    async def _submit_comment(
        self, config: RedditSubmitCommentConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Submit a comment on a post or reply to a comment."""
        thing_id = self._normalize_thing_id(config.thing_id, "t3_")
        data = {
            "thing_id": thing_id,
            "text": config.text,
            "api_type": "json",
        }
        result = await self._make_request(
            "POST", "/api/comment", credentials, data=data, action_name="submit_comment"
        )
        json_data = result.get("json", {}).get("data", {})
        things = json_data.get("things", [])
        comment_data = things[0]["data"] if things else {}
        return {
            "success": True,
            "id": comment_data.get("id"),
            "name": comment_data.get("name"),
        }

    # ========== Common Actions ==========

    async def _vote(
        self, config: RedditVoteConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Vote on a post or comment."""
        direction_map = {"up": 1, "down": -1, "none": 0}
        thing_id = self._normalize_thing_id(config.thing_id, "t3_")
        data = {
            "id": thing_id,
            "dir": direction_map[config.direction],
        }
        await self._make_request(
            "POST", "/api/vote", credentials, data=data, action_name="vote_on_post_or_comment"
        )
        return {"success": True, "thing_id": thing_id, "vote": config.direction}

    async def _edit(
        self, config: RedditEditConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Edit a post or comment."""
        thing_id = self._normalize_thing_id(config.thing_id, "t3_")
        data = {
            "thing_id": thing_id,
            "text": config.text,
            "api_type": "json",
        }
        result = await self._make_request(
            "POST", "/api/editusertext", credentials, data=data, action_name="edit_post_or_comment"
        )
        json_data = result.get("json", {}).get("data", {})
        things = json_data.get("things", [])
        edited_data = things[0]["data"] if things else {}
        return {
            "success": True,
            "id": edited_data.get("id"),
            "name": edited_data.get("name"),
        }

    async def _delete(
        self, config: RedditDeleteConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Delete a post or comment."""
        thing_id = self._normalize_thing_id(config.thing_id, "t3_")
        data = {"id": thing_id}
        await self._make_request(
            "POST", "/api/del", credentials, data=data, action_name="delete_post_or_comment"
        )
        return {"success": True, "thing_id": thing_id, "deleted": True}

    async def _save(
        self, config: RedditSaveConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Save or unsave a post or comment."""
        thing_id = self._normalize_thing_id(config.thing_id, "t3_")
        endpoint = "/api/unsave" if config.unsave else "/api/save"
        data = {"id": thing_id}
        await self._make_request(
            "POST", endpoint, credentials, data=data, action_name="save_post_or_comment"
        )
        return {
            "success": True,
            "thing_id": thing_id,
            "action": "unsaved" if config.unsave else "saved",
        }

    # ========== Search ==========

    async def _search(
        self, config: RedditSearchConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Search Reddit."""
        params = {
            "q": config.query,
            "sort": config.sort,
            "t": config.time,
            "type": config.type,
            "limit": min(config.limit or 25, 100),
        }
        if config.subreddit:
            params["restrict_sr"] = "true"
            endpoint = f"/r/{config.subreddit}/search"
        else:
            endpoint = "/search"

        result = await self._make_request(
            "GET", endpoint, credentials, params=params, action_name="search_reddit"
        )
        results = [
            child["data"] for child in result.get("data", {}).get("children", [])
        ]
        return {"results": results, "count": len(results), "query": config.query}

    # ========== Messages ==========

    async def _send_message(
        self, config: RedditSendMessageConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Send a private message to a user."""
        data = {
            "to": config.to,
            "subject": config.subject,
            "text": config.text,
            "api_type": "json",
        }
        result = await self._make_request(
            "POST", "/api/compose", credentials, data=data, action_name="send_private_message"
        )
        # Check for errors
        errors = result.get("json", {}).get("errors", [])
        if errors:
            raise ValueError(f"Failed to send message: {errors}")
        return {"success": True, "to": config.to, "subject": config.subject}

    async def _get_inbox(
        self, config: RedditGetInboxConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Get the authenticated user's inbox messages."""
        params = {
            "limit": min(config.limit or 25, 100),
        }
        result = await self._make_request(
            "GET",
            f"/message/{config.where}",
            credentials,
            params=params,
            action_name="get_inbox_messages",
        )
        messages = [
            child["data"] for child in result.get("data", {}).get("children", [])
        ]
        return {"messages": messages, "count": len(messages), "type": config.where}

    # ========== Additional User Operations ==========

    async def _get_user_saved(
        self, config: RedditGetUserSavedConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Get a user's saved posts and comments."""
        username = config.username or credentials.username or "me"
        params = {
            "limit": min(config.limit or 25, 100),
        }
        result = await self._make_request(
            "GET",
            f"/user/{username}/saved",
            credentials,
            params=params,
            action_name="get_user_saved_posts_and_comments",
        )
        items = [child["data"] for child in result.get("data", {}).get("children", [])]
        return {"items": items, "count": len(items)}

    async def _get_trophies(
        self, config: RedditGetTrophiesConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Get a user's trophies."""
        if config.username:
            endpoint = f"/user/{config.username}/trophies"
        else:
            endpoint = "/api/v1/me/trophies"
        result = await self._make_request(
            "GET", endpoint, credentials, action_name="get_user_trophies"
        )
        trophies = result.get("data", {}).get("trophies", [])
        return {
            "trophies": [t.get("data", t) for t in trophies],
            "count": len(trophies),
        }

    async def _block_user(
        self, config: RedditBlockUserConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Block a user."""
        data = {
            "name": config.username,
            "api_type": "json",
        }
        await self._make_request(
            "POST", "/api/block_user", credentials, data=data, action_name="block_user"
        )
        return {"success": True, "blocked": config.username}

    async def _get_friends(
        self, config: RedditGetFriendsConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Get the authenticated user's friends list."""
        result = await self._make_request(
            "GET", "/api/v1/me/friends", credentials, action_name="get_friends_list"
        )
        friends = result.get("data", {}).get("children", [])
        return {"friends": [f.get("name", f) for f in friends], "count": len(friends)}

    # ========== Additional Subreddit Operations ==========

    async def _get_subreddit_rules(
        self, config: RedditGetSubredditRulesConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Get rules for a subreddit."""
        result = await self._make_request(
            "GET",
            f"/r/{config.subreddit}/about/rules",
            credentials,
            action_name="get_subreddit_rules",
        )
        rules = result.get("rules", [])
        return {"rules": rules, "count": len(rules), "subreddit": config.subreddit}

    async def _search_subreddits(
        self, config: RedditSearchSubredditsConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Search for subreddits by name."""
        params = {
            "query": config.query,
            "limit": min(config.limit or 25, 100),
            "include_over_18": config.include_over_18,
        }
        result = await self._make_request(
            "GET",
            "/subreddits/search",
            credentials,
            params=params,
            action_name="search_subreddits",
        )
        subreddits = [
            child["data"] for child in result.get("data", {}).get("children", [])
        ]
        return {
            "subreddits": subreddits,
            "count": len(subreddits),
            "query": config.query,
        }

    # ========== Additional Post Operations ==========

    async def _get_duplicates(
        self, config: RedditGetDuplicatesConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Get duplicate posts (crossposts and reposts)."""
        post_id = config.post_id
        if post_id.startswith("t3_"):
            post_id = post_id[3:]
        params = {
            "limit": min(config.limit or 25, 100),
        }
        result = await self._make_request(
            "GET",
            f"/duplicates/{post_id}",
            credentials,
            params=params,
            action_name="get_duplicate_posts",
        )
        # Result is [original post listing, duplicates listing]
        if isinstance(result, list) and len(result) > 1:
            duplicates = [
                child["data"] for child in result[1].get("data", {}).get("children", [])
            ]
            return {"duplicates": duplicates, "count": len(duplicates)}
        return {"duplicates": [], "count": 0}

    async def _crosspost(
        self, config: RedditCrosspostConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Crosspost a post to another subreddit."""
        thing_id = self._normalize_thing_id(config.thing_id, "t3_")
        data = {
            "kind": "crosspost",
            "sr": config.subreddit,
            "title": config.title,
            "crosspost_fullname": thing_id,
            "api_type": "json",
        }
        result = await self._make_request(
            "POST", "/api/submit", credentials, data=data, action_name="crosspost_to_subreddit"
        )
        json_data = result.get("json", {}).get("data", {})
        return {
            "success": True,
            "id": json_data.get("id"),
            "name": json_data.get("name"),
            "url": json_data.get("url"),
            "crossposted_from": config.thing_id,
        }

    async def _hide(
        self, config: RedditHideConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Hide or unhide a post."""
        thing_id = self._normalize_thing_id(config.thing_id, "t3_")
        endpoint = "/api/unhide" if config.unhide else "/api/hide"
        data = {"id": thing_id}
        await self._make_request(
            "POST", endpoint, credentials, data=data, action_name="hide_post_from_feed"
        )
        return {
            "success": True,
            "thing_id": thing_id,
            "action": "unhidden" if config.unhide else "hidden",
        }

    async def _report(
        self, config: RedditReportConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Report a post or comment."""
        thing_id = self._normalize_thing_id(config.thing_id, "t3_")
        data = {
            "thing_id": thing_id,
            "reason": config.reason,
            "api_type": "json",
        }
        await self._make_request(
            "POST", "/api/report", credentials, data=data, action_name="report_post_or_comment"
        )
        return {"success": True, "thing_id": thing_id, "reason": config.reason}

    # ========== Flair Operations ==========

    async def _get_link_flair(
        self, config: RedditGetLinkFlairConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Get available link flair options for a subreddit."""
        result = await self._make_request(
            "GET",
            f"/r/{config.subreddit}/api/link_flair_v2",
            credentials,
            action_name="get_subreddit_link_flair_options",
        )
        # Result is a list of flair options
        flairs = result if isinstance(result, list) else []
        return {"flairs": flairs, "count": len(flairs), "subreddit": config.subreddit}

    async def _set_link_flair(
        self, config: RedditSetLinkFlairConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Set flair on a post."""
        thing_id = self._normalize_thing_id(config.thing_id, "t3_")
        data = {
            "link": thing_id,
            "api_type": "json",
        }
        if config.flair_template_id:
            data["flair_template_id"] = config.flair_template_id
        if config.text:
            data["text"] = config.text
        await self._make_request(
            "POST",
            "/api/selectflair",
            credentials,
            data=data,
            action_name="set_post_link_flair",
        )
        return {"success": True, "thing_id": thing_id}

    # ========== Multireddit Operations ==========

    async def _get_multireddit(
        self, config: RedditGetMultiredditConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Get a specific multireddit."""
        result = await self._make_request(
            "GET",
            f"/api/multi/user/{config.username}/m/{config.multiname}",
            credentials,
            action_name="get_multireddit",
        )
        return {"multireddit": result.get("data", result)}

    async def _get_my_multireddits(
        self, config: RedditGetMyMultiredditsConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Get the authenticated user's multireddits."""
        result = await self._make_request(
            "GET", "/api/multi/mine", credentials, action_name="get_my_multireddits"
        )
        multireddits = (
            [m.get("data", m) for m in result] if isinstance(result, list) else []
        )
        return {"multireddits": multireddits, "count": len(multireddits)}

    async def _get_multireddit_posts(
        self, config: RedditGetMultiredditPostsConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Get posts from a multireddit."""
        params = {
            "limit": min(config.limit or 25, 100),
        }
        result = await self._make_request(
            "GET",
            f"/user/{config.username}/m/{config.multiname}/{config.sort}",
            credentials,
            params=params,
            action_name="get_multireddit_posts",
        )
        posts = [child["data"] for child in result.get("data", {}).get("children", [])]
        return {"posts": posts, "count": len(posts)}

    # ========== Additional Message Operations ==========

    async def _mark_messages_read(
        self, config: RedditMarkMessagesReadConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Mark messages as read."""
        data = {
            "id": config.thing_ids,
        }
        await self._make_request(
            "POST",
            "/api/read_message",
            credentials,
            data=data,
            action_name="mark_messages_as_read",
        )
        return {"success": True, "marked_read": config.thing_ids.split(",")}

    async def _delete_message(
        self, config: RedditDeleteMessageConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Delete a message."""
        data = {"id": config.thing_id}
        await self._make_request(
            "POST", "/api/del_msg", credentials, data=data, action_name="delete_message"
        )
        return {"success": True, "deleted": config.thing_id}

    async def _reply_message(
        self, config: RedditReplyMessageConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Reply to a message."""
        data = {
            "thing_id": config.thing_id,
            "text": config.text,
            "api_type": "json",
        }
        result = await self._make_request(
            "POST", "/api/comment", credentials, data=data, action_name="reply_to_message"
        )
        json_data = result.get("json", {}).get("data", {})
        things = json_data.get("things", [])
        reply_data = things[0]["data"] if things else {}
        return {
            "success": True,
            "id": reply_data.get("id"),
            "name": reply_data.get("name"),
        }

    # ========== Award Operations ==========

    async def _give_award(
        self, config: RedditGiveAwardConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Give an award to a post or comment."""
        thing_id = self._normalize_thing_id(config.thing_id, "t3_")
        data = {
            "thing_id": thing_id,
            "gild_type": config.gild_type or "gid_2",
            "is_anonymous": config.is_anonymous,
            "api_type": "json",
        }
        result = await self._make_request(
            "POST",
            "/api/v1/gold/gild",
            credentials,
            data=data,
            action_name="give_award_to_post_or_comment",
        )
        return {"success": True, "thing_id": thing_id, "award_type": config.gild_type}

    # ========== Additional User Operations (New) ==========

    async def _get_karma(
        self, config: RedditGetKarmaConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Get karma breakdown by subreddit."""
        result = await self._make_request(
            "GET", "/api/v1/me/karma", credentials, action_name="get_karma_breakdown"
        )
        karma = result.get("data", [])
        return {"karma": karma, "count": len(karma)}

    async def _get_preferences(
        self, config: RedditGetPreferencesConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Get the authenticated user's preferences."""
        result = await self._make_request(
            "GET", "/api/v1/me/prefs", credentials, action_name="get_authenticated_user_preferences"
        )
        return {"preferences": result}

    async def _check_username(
        self, config: RedditCheckUsernameConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Check if a username is available."""
        params = {
            "user": config.username,
        }
        result = await self._make_request(
            "GET",
            "/api/username_available",
            credentials,
            params=params,
            action_name="check_username_availability",
        )
        # Result is a boolean
        return {"username": config.username, "available": result}

    async def _report_user(
        self, config: RedditReportUserConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Report a user."""
        data = {
            "user": config.username,
            "reason": config.reason,
        }
        await self._make_request(
            "POST",
            "/api/report_user",
            credentials,
            data=data,
            action_name="report_user",
        )
        return {"success": True, "reported": config.username, "reason": config.reason}

    # ========== Additional Subreddit Operations (New) ==========

    async def _get_subreddit_moderators(
        self, config: RedditGetSubredditModeratorsConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Get moderators of a subreddit."""
        result = await self._make_request(
            "GET",
            f"/r/{config.subreddit}/about/moderators",
            credentials,
            action_name="get_subreddit_moderators",
        )
        moderators = result.get("data", {}).get("children", [])
        return {
            "moderators": [m.get("name", m) for m in moderators],
            "count": len(moderators),
            "subreddit": config.subreddit,
        }

    async def _get_random_subreddit(
        self, config: RedditGetRandomSubredditConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Get a random subreddit."""
        endpoint = "/r/randnsfw" if config.nsfw else "/r/random"
        result = await self._make_request(
            "GET", endpoint, credentials, action_name="get_random_subreddit"
        )
        # Random redirects - extract subreddit info from response
        if isinstance(result, list) and len(result) > 0:
            posts = result[0].get("data", {}).get("children", [])
            if posts:
                subreddit = posts[0].get("data", {}).get("subreddit")
                return {"subreddit": subreddit, "posts": [p["data"] for p in posts]}
        return {"subreddit": None, "posts": []}

    async def _get_popular_subreddits(
        self, config: RedditGetPopularSubredditsConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Get popular subreddits."""
        params = {
            "limit": min(config.limit or 25, 100),
        }
        result = await self._make_request(
            "GET",
            "/subreddits/popular",
            credentials,
            params=params,
            action_name="get_popular_subreddits",
        )
        subreddits = [
            child["data"] for child in result.get("data", {}).get("children", [])
        ]
        return {"subreddits": subreddits, "count": len(subreddits)}

    async def _get_new_subreddits(
        self, config: RedditGetNewSubredditsConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Get new subreddits."""
        params = {
            "limit": min(config.limit or 25, 100),
        }
        result = await self._make_request(
            "GET",
            "/subreddits/new",
            credentials,
            params=params,
            action_name="get_new_subreddits",
        )
        subreddits = [
            child["data"] for child in result.get("data", {}).get("children", [])
        ]
        return {"subreddits": subreddits, "count": len(subreddits)}

    async def _get_subreddit_comments(
        self, config: RedditGetSubredditCommentsConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Get recent comments from a subreddit."""
        params = {
            "limit": min(config.limit or 25, 100),
        }
        result = await self._make_request(
            "GET",
            f"/r/{config.subreddit}/comments",
            credentials,
            params=params,
            action_name="get_subreddit_comments",
        )
        comments = [
            child["data"] for child in result.get("data", {}).get("children", [])
        ]
        return {
            "comments": comments,
            "count": len(comments),
            "subreddit": config.subreddit,
        }

    # ========== Post Moderation Operations (New) ==========

    async def _mark_nsfw(
        self, config: RedditMarkNsfwConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Mark or unmark a post as NSFW."""
        thing_id = self._normalize_thing_id(config.thing_id, "t3_")
        endpoint = "/api/unmarknsfw" if config.unmark else "/api/marknsfw"
        data = {"id": thing_id}
        await self._make_request(
            "POST", endpoint, credentials, data=data, action_name="mark_post_as_nsfw"
        )
        return {
            "success": True,
            "thing_id": thing_id,
            "action": "unmarked_nsfw" if config.unmark else "marked_nsfw",
        }

    async def _mark_spoiler(
        self, config: RedditMarkSpoilerConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Mark or unmark a post as spoiler."""
        thing_id = self._normalize_thing_id(config.thing_id, "t3_")
        endpoint = "/api/unspoiler" if config.unmark else "/api/spoiler"
        data = {"id": thing_id}
        await self._make_request(
            "POST", endpoint, credentials, data=data, action_name="mark_post_as_spoiler"
        )
        return {
            "success": True,
            "thing_id": thing_id,
            "action": "unmarked_spoiler" if config.unmark else "marked_spoiler",
        }

    async def _get_random_submission(
        self, config: RedditGetRandomSubmissionConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Get a random submission from a subreddit."""
        result = await self._make_request(
            "GET",
            f"/r/{config.subreddit}/random",
            credentials,
            action_name="get_random_submission",
        )
        # Random returns [post_listing, comments_listing]
        if isinstance(result, list) and len(result) > 0:
            posts = result[0].get("data", {}).get("children", [])
            if posts:
                return {"post": posts[0]["data"]}
        return {"post": None}

    # ========== User Flair Operations (New) ==========

    async def _get_user_flair(
        self, config: RedditGetUserFlairConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Get user flair options for a subreddit."""
        result = await self._make_request(
            "GET",
            f"/r/{config.subreddit}/api/user_flair_v2",
            credentials,
            action_name="get_user_flair_options",
        )
        flairs = result if isinstance(result, list) else []
        return {"flairs": flairs, "count": len(flairs), "subreddit": config.subreddit}

    async def _set_user_flair(
        self, config: RedditSetUserFlairConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Set user flair in a subreddit."""
        data = {
            "api_type": "json",
        }
        if config.flair_template_id:
            data["flair_template_id"] = config.flair_template_id
        if config.text:
            data["text"] = config.text
        await self._make_request(
            "POST",
            f"/r/{config.subreddit}/api/selectflair",
            credentials,
            data=data,
            action_name="set_user_flair_in_subreddit",
        )
        return {"success": True, "subreddit": config.subreddit}

    # ========== Listings/Feeds Operations (New) ==========

    async def _get_best(
        self, config: RedditGetBestConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Get best posts (personalized front page)."""
        params = {
            "t": config.time,
            "limit": min(config.limit or 25, 100),
        }
        result = await self._make_request(
            "GET", "/best", credentials, params=params, action_name="get_best_posts"
        )
        posts = [child["data"] for child in result.get("data", {}).get("children", [])]
        return {"posts": posts, "count": len(posts)}

    async def _get_gilded(
        self, config: RedditGetGildedConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Get gilded (awarded) content."""
        params = {
            "limit": min(config.limit or 25, 100),
        }
        if config.subreddit:
            endpoint = f"/r/{config.subreddit}/gilded"
        else:
            endpoint = "/gilded"
        result = await self._make_request(
            "GET", endpoint, credentials, params=params, action_name="get_gilded_content"
        )
        items = [child["data"] for child in result.get("data", {}).get("children", [])]
        return {"items": items, "count": len(items), "subreddit": config.subreddit}

    # ========== Additional Message Operations (New) ==========

    async def _mark_all_messages_read(
        self, config: RedditMarkAllMessagesReadConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Mark all messages as read."""
        await self._make_request(
            "POST",
            "/api/read_all_messages",
            credentials,
            action_name="mark_all_messages_as_read",
        )
        return {"success": True, "action": "marked_all_read"}

    async def _unread_message(
        self, config: RedditUnreadMessageConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Mark messages as unread."""
        data = {
            "id": config.thing_ids,
        }
        await self._make_request(
            "POST",
            "/api/unread_message",
            credentials,
            data=data,
            action_name="mark_messages_as_unread",
        )
        return {"success": True, "marked_unread": config.thing_ids.split(",")}

    # ========== Wiki Operations (New) ==========

    async def _get_wiki_pages(
        self, config: RedditGetWikiPagesConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """List all wiki pages in a subreddit."""
        result = await self._make_request(
            "GET",
            f"/r/{config.subreddit}/wiki/pages",
            credentials,
            action_name="list_wiki_pages",
        )
        pages = result.get("data", [])
        return {"pages": pages, "count": len(pages), "subreddit": config.subreddit}

    async def _get_wiki_page(
        self, config: RedditGetWikiPageConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Get a specific wiki page."""
        result = await self._make_request(
            "GET",
            f"/r/{config.subreddit}/wiki/{config.page}",
            credentials,
            action_name="get_wiki_page",
        )
        wiki_data = result.get("data", {})
        return {
            "content": wiki_data.get("content_md", ""),
            "content_html": wiki_data.get("content_html", ""),
            "revision_by": wiki_data.get("revision_by", {}).get("data", {}).get("name"),
            "revision_date": wiki_data.get("revision_date"),
            "subreddit": config.subreddit,
            "page": config.page,
        }

    async def _get_wiki_revisions(
        self, config: RedditGetWikiRevisionsConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Get wiki page revision history."""
        params = {
            "limit": min(config.limit or 25, 100),
        }
        if config.page:
            endpoint = f"/r/{config.subreddit}/wiki/revisions/{config.page}"
        else:
            endpoint = f"/r/{config.subreddit}/wiki/revisions"
        result = await self._make_request(
            "GET",
            endpoint,
            credentials,
            params=params,
            action_name="get_wiki_page_revisions",
        )
        revisions = [
            child["data"] if "data" in child else child
            for child in result.get("data", {}).get("children", [])
        ]
        return {
            "revisions": revisions,
            "count": len(revisions),
            "subreddit": config.subreddit,
            "page": config.page,
        }

    # ========== Live Thread Operations (New) ==========

    async def _create_live_thread(
        self, config: RedditCreateLiveThreadConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Create a new live thread."""
        data = {
            "title": config.title,
            "api_type": "json",
        }
        if config.description:
            data["description"] = config.description
        if config.nsfw:
            data["nsfw"] = config.nsfw
        result = await self._make_request(
            "POST",
            "/api/live/create",
            credentials,
            data=data,
            action_name="create_live_thread",
        )
        json_data = result.get("json", {}).get("data", {})
        return {
            "success": True,
            "id": json_data.get("id"),
            "title": config.title,
        }

    async def _get_live_thread(
        self, config: RedditGetLiveThreadConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Get live thread information."""
        result = await self._make_request(
            "GET",
            f"/live/{config.thread_id}/about",
            credentials,
            action_name="get_live_thread",
        )
        return {"thread": result.get("data", result)}

    async def _get_live_thread_updates(
        self, config: RedditGetLiveThreadUpdatesConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Get updates from a live thread."""
        params = {
            "limit": min(config.limit or 25, 100),
        }
        result = await self._make_request(
            "GET",
            f"/live/{config.thread_id}",
            credentials,
            params=params,
            action_name="get_live_thread_updates",
        )
        updates = [
            child["data"] for child in result.get("data", {}).get("children", [])
        ]
        return {
            "updates": updates,
            "count": len(updates),
            "thread_id": config.thread_id,
        }

    async def _update_live_thread(
        self, config: RedditUpdateLiveThreadConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Post an update to a live thread."""
        data = {
            "body": config.body,
            "api_type": "json",
        }
        result = await self._make_request(
            "POST",
            f"/api/live/{config.thread_id}/update",
            credentials,
            data=data,
            action_name="post_live_thread_update",
        )
        json_data = result.get("json", {}).get("data", {})
        return {
            "success": True,
            "id": json_data.get("name"),
            "thread_id": config.thread_id,
        }

    async def _close_live_thread(
        self, config: RedditCloseLiveThreadConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Close a live thread."""
        await self._make_request(
            "POST",
            f"/api/live/{config.thread_id}/close_thread",
            credentials,
            action_name="close_live_thread",
        )
        return {"success": True, "thread_id": config.thread_id, "action": "closed"}

    # ========== Additional Multireddit Operations (New) ==========

    async def _create_multireddit(
        self, config: RedditCreateMultiredditConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Create a new multireddit."""
        # Parse subreddits list
        subreddits = [s.strip() for s in config.subreddits.split(",")]
        model = {
            "display_name": config.name,
            "subreddits": [{"name": sr} for sr in subreddits],
            "visibility": config.visibility or "private",
        }
        if config.description:
            model["description_md"] = config.description

        data = {
            "model": str(model).replace("'", '"'),  # JSON string
        }
        result = await self._make_request(
            "POST",
            f"/api/multi/user/{credentials.username}/m/{config.name}",
            credentials,
            data=data,
            action_name="create_multireddit",
        )
        return {
            "success": True,
            "multireddit": result.get("data", result),
            "name": config.name,
        }

    async def _delete_multireddit(
        self, config: RedditDeleteMultiredditConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Delete a multireddit."""
        await self._make_request(
            "DELETE",
            f"/api/multi/user/{credentials.username}/m/{config.multiname}",
            credentials,
            action_name="delete_multireddit",
        )
        return {"success": True, "deleted": config.multiname}

    async def _update_multireddit(
        self, config: RedditUpdateMultiredditConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Update a multireddit."""
        model = {}
        if config.description:
            model["description_md"] = config.description
        if config.visibility:
            model["visibility"] = config.visibility

        data = {
            "model": str(model).replace("'", '"'),  # JSON string
        }
        result = await self._make_request(
            "PUT",
            f"/api/multi/user/{credentials.username}/m/{config.multiname}",
            credentials,
            data=data,
            action_name="update_multireddit",
        )
        return {
            "success": True,
            "multireddit": result.get("data", result),
        }

    async def _add_subreddit_to_multi(
        self, config: RedditAddSubredditToMultiConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Add a subreddit to a multireddit."""
        data = {
            "model": f'{{"name": "{config.subreddit}"}}',
        }
        await self._make_request(
            "PUT",
            f"/api/multi/user/{credentials.username}/m/{config.multiname}/r/{config.subreddit}",
            credentials,
            data=data,
            action_name="add_subreddit_to_multireddit",
        )
        return {
            "success": True,
            "multireddit": config.multiname,
            "added": config.subreddit,
        }

    async def _remove_subreddit_from_multi(
        self,
        config: RedditRemoveSubredditFromMultiConfig,
        credentials: RedditCredential,
    ) -> Dict[str, Any]:
        """Remove a subreddit from a multireddit."""
        await self._make_request(
            "DELETE",
            f"/api/multi/user/{credentials.username}/m/{config.multiname}/r/{config.subreddit}",
            credentials,
            action_name="remove_subreddit_from_multireddit",
        )
        return {
            "success": True,
            "multireddit": config.multiname,
            "removed": config.subreddit,
        }

    # ========== Additional API Operations (From official docs) ==========

    async def _get_info(
        self, config: RedditGetInfoConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Get info about things by fullname (batch query)."""
        params = {"id": config.ids}
        result = await self._make_request(
            "GET", "/api/info", credentials, params=params, action_name="get_info_by_fullname_batch"
        )
        items = [child["data"] for child in result.get("data", {}).get("children", [])]
        return {"items": items, "count": len(items)}

    async def _get_more_comments(
        self, config: RedditGetMoreCommentsConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Load more comments from a 'more' object."""
        data = {
            "link_id": config.link_id,
            "children": config.children,
            "sort": config.sort or "confidence",
            "api_type": "json",
        }
        result = await self._make_request(
            "POST",
            "/api/morechildren",
            credentials,
            data=data,
            action_name="load_more_comments",
        )
        json_data = result.get("json", {}).get("data", {})
        comments = json_data.get("things", [])
        return {"comments": comments, "count": len(comments)}

    async def _lock(
        self, config: RedditLockConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Lock or unlock a post or comment."""
        thing_id = self._normalize_thing_id(config.thing_id, "t3_")
        endpoint = "/api/unlock" if config.unlock else "/api/lock"
        data = {"id": thing_id}
        await self._make_request(
            "POST", endpoint, credentials, data=data, action_name="lock_post_or_comment"
        )
        return {
            "success": True,
            "thing_id": thing_id,
            "action": "unlocked" if config.unlock else "locked",
        }

    async def _approve(
        self, config: RedditApproveConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Approve a post or comment."""
        thing_id = self._normalize_thing_id(config.thing_id, "t3_")
        data = {"id": thing_id}
        await self._make_request(
            "POST", "/api/approve", credentials, data=data, action_name="approve_post_or_comment"
        )
        return {"success": True, "thing_id": thing_id, "action": "approved"}

    async def _remove(
        self, config: RedditRemoveConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Remove a post or comment."""
        thing_id = self._normalize_thing_id(config.thing_id, "t3_")
        data = {"id": thing_id, "spam": config.spam or False}
        await self._make_request(
            "POST", "/api/remove", credentials, data=data, action_name="remove_post_or_comment"
        )
        return {
            "success": True,
            "thing_id": thing_id,
            "action": "removed",
            "spam": config.spam,
        }

    async def _distinguish(
        self, config: RedditDistinguishConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Distinguish a post or comment as moderator."""
        thing_id = self._normalize_thing_id(config.thing_id, "t1_")
        data = {
            "id": thing_id,
            "how": config.how,
            "sticky": config.sticky or False,
            "api_type": "json",
        }
        result = await self._make_request(
            "POST",
            "/api/distinguish",
            credentials,
            data=data,
            action_name="distinguish_post_or_comment",
        )
        return {"success": True, "thing_id": thing_id, "how": config.how}

    async def _sticky_post(
        self, config: RedditStickyPostConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Sticky or unsticky a post."""
        thing_id = self._normalize_thing_id(config.thing_id, "t3_")
        data = {
            "id": thing_id,
            "state": config.state if config.state is not None else True,
            "api_type": "json",
        }
        if config.num:
            data["num"] = config.num
        await self._make_request(
            "POST",
            "/api/set_subreddit_sticky",
            credentials,
            data=data,
            action_name="sticky_or_unsticky_post",
        )
        return {
            "success": True,
            "thing_id": thing_id,
            "action": "stickied" if config.state else "unstickied",
        }

    async def _set_contest_mode(
        self, config: RedditSetContestModeConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Set or unset contest mode on a post."""
        thing_id = self._normalize_thing_id(config.thing_id, "t3_")
        data = {
            "id": thing_id,
            "state": config.state if config.state is not None else True,
            "api_type": "json",
        }
        await self._make_request(
            "POST",
            "/api/set_contest_mode",
            credentials,
            data=data,
            action_name="set_post_contest_mode",
        )
        return {"success": True, "thing_id": thing_id, "contest_mode": config.state}

    async def _set_suggested_sort(
        self, config: RedditSetSuggestedSortConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Set suggested sort for a post."""
        thing_id = self._normalize_thing_id(config.thing_id, "t3_")
        data = {
            "id": thing_id,
            "sort": config.sort or "blank",
            "api_type": "json",
        }
        await self._make_request(
            "POST",
            "/api/set_suggested_sort",
            credentials,
            data=data,
            action_name="set_post_suggested_sort",
        )
        return {"success": True, "thing_id": thing_id, "suggested_sort": config.sort}

    async def _send_replies(
        self, config: RedditSendRepliesConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Enable or disable inbox replies for a post or comment."""
        thing_id = self._normalize_thing_id(config.thing_id, "t3_")
        data = {
            "id": thing_id,
            "state": config.state if config.state is not None else True,
        }
        await self._make_request(
            "POST",
            "/api/sendreplies",
            credentials,
            data=data,
            action_name="toggle_post_inbox_replies",
        )
        return {"success": True, "thing_id": thing_id, "send_replies": config.state}

    async def _get_default_subreddits(
        self, config: RedditGetDefaultSubredditsConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Get default subreddits."""
        params = {"limit": min(config.limit or 25, 100)}
        result = await self._make_request(
            "GET",
            "/subreddits/default",
            credentials,
            params=params,
            action_name="get_default_subreddits",
        )
        subreddits = [
            child["data"] for child in result.get("data", {}).get("children", [])
        ]
        return {"subreddits": subreddits, "count": len(subreddits)}

    async def _get_blocked_users(
        self, config: RedditGetBlockedUsersConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Get the authenticated user's blocked users."""
        result = await self._make_request(
            "GET", "/api/v1/me/blocked", credentials, action_name="get_blocked_users"
        )
        blocked = result.get("data", {}).get("children", [])
        return {"blocked_users": blocked, "count": len(blocked)}

    async def _unblock_user(
        self, config: RedditUnblockUserConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Unblock a user."""
        # Get the user's ID first
        user_result = await self._make_request(
            "GET",
            f"/user/{config.username}/about",
            credentials,
            action_name="get_user_for_unblock",
        )
        user_id = user_result.get("data", {}).get("id")
        if not user_id:
            raise ValueError(f"User not found: {config.username}")

        data = {
            "name": config.username,
            "type": "enemy",
            "container": f"t2_{user_id}",
        }
        await self._make_request(
            "POST", "/api/unfriend", credentials, data=data, action_name="unblock_user"
        )
        return {"success": True, "unblocked": config.username}

    async def _get_subreddit_traffic(
        self, config: RedditGetSubredditTrafficConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Get subreddit traffic statistics."""
        result = await self._make_request(
            "GET",
            f"/r/{config.subreddit}/about/traffic",
            credentials,
            action_name="get_subreddit_traffic_stats",
        )
        return {
            "day": result.get("day", []),
            "hour": result.get("hour", []),
            "month": result.get("month", []),
            "subreddit": config.subreddit,
        }

    async def _ignore_reports(
        self, config: RedditIgnoreReportsConfig, credentials: RedditCredential
    ) -> Dict[str, Any]:
        """Ignore or unignore reports on a post or comment."""
        thing_id = self._normalize_thing_id(config.thing_id, "t3_")
        endpoint = "/api/unignore_reports" if config.unignore else "/api/ignore_reports"
        data = {"id": thing_id}
        await self._make_request(
            "POST", endpoint, credentials, data=data, action_name="ignore_reports_on_content"
        )
        return {
            "success": True,
            "thing_id": thing_id,
            "action": "unignored_reports" if config.unignore else "ignored_reports",
        }

    # ========== RSS Feed Operations (No authentication required) ==========

    async def _reddit_get(
        self,
        url: str,
        proxy_mode: str = "auto",
        timeout: float = 60.0,
    ) -> tuple[httpx.Response, bool]:
        """Make a GET request to Reddit with smart proxy fallback.

        Args:
            url: The Reddit URL to fetch
            proxy_mode: "auto" (direct first, proxy on 429), "always", or "never"
            timeout: Request timeout in seconds

        Returns:
            Tuple of (response, used_proxy) where used_proxy indicates if proxy was used
        """
        headers = {"User-Agent": USER_AGENT}
        proxy_url = _get_brightdata_proxy_url()

        if proxy_mode == "always" and proxy_url:
            # Always use proxy
            async with httpx.AsyncClient(
                proxy=proxy_url, verify=False
            ) as client:
                response = await client.get(url, headers=headers, timeout=timeout)
            return response, True

        # Try direct first (for "auto" and "never" modes)
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=timeout)

        # Reddit now often returns a 403 HTML "blocked by network security"
        # page instead of a 429. Treat that the same as a proxy-worthy block.
        body = response.text.lower() if response.status_code == 403 else ""
        should_retry_via_proxy = response.status_code == 429 or (
            response.status_code == 403
            and "blocked by network security" in body
        )

        # If blocked and auto mode, retry through proxy
        if (
            should_retry_via_proxy
            and proxy_mode == "auto"
            and proxy_url
        ):
            logger.info(
                f"[RedditNode] Reddit blocked direct access ({response.status_code}), retrying via proxy: {url[:80]}"
            )
            async with httpx.AsyncClient(
                proxy=proxy_url, verify=False
            ) as client:
                response = await client.get(url, headers=headers, timeout=timeout)
            return response, True

        return response, False

    async def _fetch_post_comments(
        self, post_id: str, subreddit: str, limit: int = 10, proxy_mode: str = "auto"
    ) -> List[Dict[str, Any]]:
        """Fetch top comments for a post via Reddit's public Atom comment feed.

        Args:
            post_id: Post ID (without t3_ prefix)
            subreddit: Subreddit name
            limit: Maximum number of comments to return
            proxy_mode: "auto", "always", or "never"

        Returns:
            List of comment data
        """
        try:
            url = f"https://www.reddit.com/r/{subreddit}/comments/{post_id}/.rss"

            response, _ = await self._reddit_get(url, proxy_mode=proxy_mode)

            if response.status_code != 200:
                logger.warning(
                    f"[RedditNode] Failed to fetch comments for post {post_id}: {response.status_code}"
                )
                return []

            return self._parse_comment_feed_entries(response.content, post_id, limit)

        except Exception as e:
            logger.warning(
                f"[RedditNode] Error fetching comments for post {post_id}: {str(e)}"
            )
            return []

    @staticmethod
    def _normalize_subreddit_name(subreddit: str) -> str:
        normalized = subreddit.strip()
        if normalized.startswith("r/"):
            normalized = normalized[2:]
        return normalized

    @classmethod
    def _build_public_subreddit_url(
        cls,
        subreddit: str,
        sort: str = "",
        time_period: Optional[str] = None,
    ) -> str:
        normalized_subreddit = cls._normalize_subreddit_name(subreddit)
        path = f"/r/{normalized_subreddit}/"
        if sort:
            path += f"{sort}/"

        params: Dict[str, str] = {}
        if time_period and sort in ["top", "controversial"]:
            params["t"] = time_period

        base_url = f"https://www.reddit.com{path}"
        return f"{base_url}?{urlencode(params)}" if params else base_url

    @staticmethod
    def _extract_post_id_from_reddit_url(url: str) -> str:
        match = re.search(r"/comments/([^/]+)/", url or "")
        return match.group(1) if match else ""

    @staticmethod
    def _brightdata_sort(sort: str) -> str:
        return {
            "new": "New",
            "top": "Top",
            "hot": "Hot",
            "rising": "Hot",
            "controversial": "Top",
        }.get((sort or "").lower(), "Hot")

    @staticmethod
    def _extract_brightdata_comment_id(url: str) -> str:
        parts = [part for part in (url or "").split("/") if part]
        if "comment" in parts:
            idx = parts.index("comment") + 1
            return parts[idx] if idx < len(parts) else ""
        return parts[-1] if parts else ""

    def _normalize_brightdata_comment(self, item: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "comment_id": self._extract_brightdata_comment_id(item.get("url", "")),
            "author": item.get("user_commenting") or "[deleted]",
            "body": item.get("comment") or "",
            "created_at": item.get("date_of_comment"),
            "score": item.get("num_upvotes", 0),
            "reply_count": item.get("num_replies", 0),
            "url": item.get("url", ""),
            "replies": item.get("replies") or [],
        }

    def _normalize_brightdata_post(
        self,
        item: Dict[str, Any],
        should_fetch_comments: bool,
    ) -> Optional[Dict[str, Any]]:
        if item.get("error_code") or item.get("error"):
            return None
        title = item.get("title") or ""
        url = item.get("url") or ""
        post_id = (item.get("post_id") or self._extract_post_id_from_reddit_url(url)).removeprefix("t3_")
        if not title or not post_id:
            return None

        post: Dict[str, Any] = {
            "title": title,
            "url": url,
            "author": item.get("user_posted") or "",
            "post_id": post_id,
            "subreddit": item.get("community_name") or "",
            "body": item.get("description") or item.get("description_markdown") or "",
            "content_html": item.get("description") or "",
            "published_at": item.get("date_posted"),
            "updated_at": item.get("timestamp"),
            "score": item.get("num_upvotes", 0),
            "num_comments": item.get("num_comments", 0),
            "tag": item.get("tag"),
            "photos": item.get("photos") or [],
            "videos": item.get("videos") or [],
            "community_url": item.get("community_url"),
            "community_description": item.get("community_description"),
            "community_members_num": item.get("community_members_num"),
            "related_posts": item.get("related_posts") or [],
        }

        if should_fetch_comments:
            comments = [
                self._normalize_brightdata_comment(comment)
                for comment in (item.get("comments") or [])[:PUBLIC_REDDIT_COMMENT_LIMIT]
            ]
            post["comments"] = comments
            post["comment_count"] = len(comments)
        return post

    async def _check_brightdata_credits_or_raise(self) -> None:
        if not self.user_id:
            raise ValueError("[RedditNode] No user context; cannot meter Bright Data usage")
        from billing.usage_tracker import usage_tracker
        await usage_tracker.enforce_credit_gate(
            self.user_id,
            organization_id=self.organization_id,
            sio=self.sio,
            sid=self.sid,
            user_resource=False,
            surface="brightdata",
        )

    @staticmethod
    def _brightdata_reddit_raw_cost(record_count: int) -> Decimal:
        configured_cost = os.environ.get("BRIGHTDATA_REDDIT_COST_PER_RECORD_USD")
        per_record = Decimal(configured_cost) if configured_cost else BRIGHTDATA_REDDIT_COST_PER_RECORD_USD
        return per_record * Decimal(str(max(record_count, 0)))

    async def _track_brightdata_reddit_usage(
        self,
        raw_cost: Decimal,
        item_count: int,
        snapshot_id: str,
        operation: str,
    ) -> None:
        if raw_cost <= 0:
            return
        if not self.user_id:
            logger.error("[RedditNode] No user_id; skipping Bright Data usage tracking")
            return

        from billing.markup import apply_brightdata_markup
        from billing.schema import UsageEventData
        from billing.usage_tracker import usage_tracker

        charged = apply_brightdata_markup(raw_cost)
        usage_event = UsageEventData(
            user_id=self.user_id,
            total_cost=charged,
            usage_type="api_usage",
            usage_subtype=f"reddit/{operation}",
            quantity=Decimal(str(item_count)),
            unit_type="requests",
            user_resource=False,
            organization_id=self.organization_id,
            metadata={
                "platform": "reddit",
                "provider": "brightdata",
                "dataset_id": BRIGHTDATA_REDDIT_POSTS_DATASET_ID,
                "operation": operation,
                "snapshot_id": snapshot_id,
                "items_returned": item_count,
                "raw_cost_usd": float(raw_cost),
                "charged_cost_usd": float(charged),
            },
        )
        try:
            await usage_tracker.track_usage_event(
                usage_event,
                sio=self.sio,
                sid=self.sid,
            )
        except Exception as exc:
            logger.error("[RedditNode] Failed to track Bright Data usage: %s", exc)

    async def _fetch_brightdata_snapshot(
        self,
        client: httpx.AsyncClient,
        snapshot_id: str,
        timeout_seconds: float,
    ) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            progress = await client.get(f"{BRIGHTDATA_DATASETS_API_BASE}/progress/{snapshot_id}")
            if progress.status_code >= 400:
                raise ValueError(f"Bright Data progress failed: {progress.text[:300]}")
            state = progress.json() or {}
            status = state.get("status")
            if status == "ready":
                snapshot = await client.get(
                    f"{BRIGHTDATA_DATASETS_API_BASE}/snapshot/{snapshot_id}",
                    params={"format": "json"},
                )
                if snapshot.status_code >= 400:
                    raise ValueError(f"Bright Data snapshot download failed: {snapshot.text[:300]}")
                data = snapshot.json()
                if not isinstance(data, list):
                    raise ValueError("Bright Data snapshot returned invalid data")
                return data, state
            if status in {"failed", "error", "canceled", "cancelled"}:
                raise ValueError(f"Bright Data snapshot failed: {state}")
            await asyncio.sleep(3)
        await client.post(f"{BRIGHTDATA_DATASETS_API_BASE}/snapshot/{snapshot_id}/cancel")
        raise TimeoutError(f"Bright Data snapshot {snapshot_id} did not finish in {timeout_seconds:.0f}s")

    async def _fetch_public_subreddit_posts_via_brightdata(
        self,
        subreddit: str,
        sort: str = "",
        limit: Optional[int] = 25,
        fetch_comments: Optional[str] = "false",
    ) -> Dict[str, Any]:
        token = _get_brightdata_api_token()
        if not token:
            raise RuntimeError("BRIGHTDATA_API_TOKEN is not configured")
        await self._check_brightdata_credits_or_raise()

        normalized_subreddit = self._normalize_subreddit_name(subreddit)
        requested_limit = min(limit or 25, 100)
        should_fetch_comments = fetch_comments and fetch_comments.lower() == "true"
        payload = {
            "input": [
                {
                    "url": f"https://www.reddit.com/r/{normalized_subreddit}/",
                    "sort_by": self._brightdata_sort(sort),
                }
            ]
        }
        params = {
            "dataset_id": BRIGHTDATA_REDDIT_POSTS_DATASET_ID,
            "type": "discover_new",
            "discover_by": "subreddit_url",
            "include_errors": "true",
            "format": "json",
            "limit_per_input": str(requested_limit),
        }
        timeout_seconds = float(
            os.environ.get(
                "BRIGHTDATA_REDDIT_SNAPSHOT_TIMEOUT_SECONDS",
                str(BRIGHTDATA_REDDIT_SNAPSHOT_TIMEOUT_SECONDS),
            )
        )

        total_start = time.time()
        async with httpx.AsyncClient(
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0),
        ) as client:
            response = await client.post(
                f"{BRIGHTDATA_DATASETS_API_BASE}/trigger",
                params=params,
                json=payload,
            )
            if response.status_code >= 400:
                raise ValueError(f"Bright Data trigger failed: {response.text[:500]}")
            snapshot_id = (response.json() or {}).get("snapshot_id")
            if not snapshot_id:
                raise ValueError(f"Bright Data did not return a snapshot id: {response.text[:300]}")
            items, progress_state = await self._fetch_brightdata_snapshot(client, snapshot_id, timeout_seconds)

        posts = [
            post
            for item in items
            if (post := self._normalize_brightdata_post(item, bool(should_fetch_comments)))
        ][:requested_limit]
        if not posts:
            raise ValueError("Bright Data returned no valid Reddit posts")

        logger.info(
            "[RedditNode] Bright Data Reddit scrape returned %s posts in %.2fs",
            len(posts),
            time.time() - total_start,
        )
        record_count = int(progress_state.get("records") or len(posts))
        await self._track_brightdata_reddit_usage(
            raw_cost=self._brightdata_reddit_raw_cost(record_count),
            item_count=len(posts),
            snapshot_id=snapshot_id,
            operation="get_subreddit_posts",
        )
        return {
            "posts": posts,
            "count": len(posts),
            "subreddit": subreddit,
            "source": "brightdata_reddit_scraper",
            "provider": "brightdata",
            "content_mode": "rich",
        }

    async def _attach_public_feed_comments(
        self,
        posts: List[Dict[str, Any]],
        subreddit: str,
        proxy_mode: str,
    ) -> None:
        """Attach public Atom-feed comments to posts concurrently."""
        normalized_subreddit = subreddit.strip()
        if normalized_subreddit.startswith("r/"):
            normalized_subreddit = normalized_subreddit[2:]

        semaphore = asyncio.Semaphore(PUBLIC_REDDIT_COMMENT_FETCH_CONCURRENCY)

        async def fetch_for_post(post: Dict[str, Any]) -> None:
            post_id = post.get("post_id")
            if not post_id:
                post["comments"] = []
                post["comment_count"] = 0
                return
            async with semaphore:
                comments = await self._fetch_post_comments(
                    post_id,
                    normalized_subreddit,
                    limit=PUBLIC_REDDIT_COMMENT_LIMIT,
                    proxy_mode=proxy_mode,
                )
            post["comments"] = comments
            post["comment_count"] = len(comments)

        await asyncio.gather(*(fetch_for_post(post) for post in posts))

    # XML namespaces used by Reddit RSS/Atom feeds
    _RSS_NS = {
        "content": "http://purl.org/rss/1.0/modules/content/",
        "atom": "http://www.w3.org/2005/Atom",
        "media": "http://search.yahoo.com/mrss/",
    }

    @staticmethod
    def _find_elem(
        item: ET.Element,
        atom_tag: str,
        ns: Dict[str, str],
        rss_tag: Optional[str] = None,
    ) -> Optional[ET.Element]:
        """Find an element trying Atom namespace first, then plain RSS tag.

        NOTE: Do NOT use `elem_a or elem_b` with ElementTree — an Element with
        no children evaluates as falsy, silently skipping valid matches.
        """
        elem = item.find(f"atom:{atom_tag}", ns)
        if elem is not None:
            return elem
        if rss_tag:
            return item.find(rss_tag)
        return item.find(atom_tag)

    def _parse_feed_entries(self, content: bytes) -> List[Dict[str, Any]]:
        """Parse RSS/Atom feed XML into a list of post dicts."""
        root = ET.fromstring(content)
        ns = self._RSS_NS

        # Try Atom format first (most common for Reddit), fall back to RSS
        items = root.findall(".//atom:entry", ns)
        if not items:
            items = root.findall(".//item")

        posts = []
        for item in items:
            post: Dict[str, Any] = {}

            # Title
            title_elem = self._find_elem(item, "title", ns)
            if title_elem is not None:
                post["title"] = title_elem.text or ""

            # URL — Atom uses href attr, RSS uses text
            link_elem = item.find("atom:link", ns)
            if link_elem is not None:
                post["url"] = link_elem.get("href") or ""
            else:
                link_elem = item.find("link")
                if link_elem is not None:
                    post["url"] = link_elem.text or ""

            # Author
            author_elem = self._find_elem(item, "author", ns)
            if author_elem is not None:
                name_elem = self._find_elem(author_elem, "name", ns)
                post["author"] = (
                    name_elem.text if name_elem is not None else author_elem.text
                ) or ""

            # Post ID from URL
            if post.get("url"):
                parts = post["url"].split("/")
                if "comments" in parts:
                    try:
                        post["post_id"] = parts[parts.index("comments") + 1]
                    except (ValueError, IndexError):
                        pass

            # Content HTML
            content_elem = self._find_elem(item, "content", ns, "content:encoded")
            if content_elem is not None:
                post["content_html"] = content_elem.text or ""
            else:
                summary_elem = self._find_elem(item, "summary", ns, "description")
                if summary_elem is not None:
                    post["content_html"] = summary_elem.text or ""

            # Category (subreddit)
            cat_elem = self._find_elem(item, "category", ns)
            if cat_elem is not None:
                post["subreddit"] = cat_elem.get("term") or cat_elem.text or ""

            # Timestamps
            for tag, key in [("updated", "updated_at"), ("published", "published_at")]:
                elem = self._find_elem(item, tag, ns)
                if elem is not None and elem.text:
                    post[key] = elem.text
            if "published_at" not in post:
                pubdate = item.find("pubDate")
                if pubdate is not None and pubdate.text:
                    post["published_at"] = pubdate.text

            if post.get("title"):
                posts.append(post)

        return posts

    @staticmethod
    def _strip_feed_html(content: str) -> str:
        """Convert feed HTML snippets into readable text."""
        text = html_lib.unescape(content or "")
        text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
        text = re.sub(r"<br\\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</p\\s*>", "\n\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)
        return text.strip()

    def _parse_comment_feed_entries(
        self,
        content: bytes,
        post_id: str,
        limit: int,
    ) -> List[Dict[str, Any]]:
        """Parse a Reddit post comment Atom feed into comment dicts."""
        root = ET.fromstring(content)
        ns = self._RSS_NS
        entries = root.findall(".//atom:entry", ns)
        comments: List[Dict[str, Any]] = []

        for entry in entries:
            link_elem = entry.find("atom:link", ns)
            href = link_elem.get("href") if link_elem is not None else ""
            if not href:
                continue

            parts = [part for part in href.split("/") if part]
            try:
                comment_idx = parts.index(post_id) + 2
            except ValueError:
                continue
            if comment_idx >= len(parts):
                # The first entry in the feed is the post itself, not a comment.
                continue

            author_elem = self._find_elem(entry, "author", ns)
            author_name = ""
            if author_elem is not None:
                name_elem = self._find_elem(author_elem, "name", ns)
                author_name = (
                    name_elem.text if name_elem is not None else author_elem.text
                ) or ""

            content_elem = self._find_elem(entry, "content", ns, "content:encoded")
            html_body = content_elem.text if content_elem is not None else ""
            if not html_body:
                summary_elem = self._find_elem(entry, "summary", ns, "description")
                html_body = summary_elem.text if summary_elem is not None else ""

            created_at = None
            for tag in ("updated", "published"):
                ts_elem = self._find_elem(entry, tag, ns)
                if ts_elem is not None and ts_elem.text:
                    created_at = ts_elem.text
                    break

            comments.append(
                {
                    "comment_id": parts[comment_idx],
                    "author": author_name or "[deleted]",
                    "body": self._strip_feed_html(html_body),
                    "body_html": html_body or "",
                    "created_at": created_at,
                    "url": href,
                }
            )
            if len(comments) >= limit:
                break

        return comments

    async def _fetch_page_with_retry(
        self,
        url: str,
        page_num: int,
        proxy_mode: str = "auto",
    ) -> tuple[httpx.Response, bool]:
        """Fetch a single page with retry on 5xx errors and smart proxy fallback.

        Returns:
            Tuple of (response, used_proxy)
        """
        used_proxy = False
        response = None
        for attempt in range(3):
            response, used_proxy = await self._reddit_get(url, proxy_mode=proxy_mode)
            if response.status_code < 500:
                return response, used_proxy
            logger.warning(
                f"[RedditNode] Page {page_num} returned {response.status_code}, "
                f"retry {attempt + 1}/2"
            )
            await asyncio.sleep(2)
        return response, used_proxy

    async def _fetch_rss_feed(
        self,
        subreddit: str,
        sort: str = "",
        time_param: Optional[str] = None,
        limit: Optional[int] = None,
        proxy_mode: str = "auto",
    ) -> Dict[str, Any]:
        """Fetch Reddit posts from Reddit's public Atom feed.

        The JSON listing endpoints are now aggressively blocked for anonymous
        access, while the public feed URLs remain accessible. This operation is
        intentionally a feed reader, so use the feed endpoint directly here.

        Args:
            subreddit: Subreddit name(s), supports multiple with +
            sort: Sort parameter (hot, new, top, rising, controversial)
            time_param: Time filter for top/controversial
            limit: Total number of posts to return (Reddit feed supports up to 100)
            proxy_mode: "auto" (direct first, proxy on block), "always", or "never"

        Returns:
            Dict with "posts" list and "proxy_stats" tracking proxy usage
        """
        # Normalize subreddit name
        subreddit = subreddit.strip()
        if subreddit.startswith("r/"):
            subreddit = subreddit[2:]

        # Build feed URL
        base_url = f"https://www.reddit.com/r/{subreddit}/"
        feed_path = f"{sort}.rss" if sort else ".rss"
        feed_url = base_url + feed_path

        params: Dict[str, Any] = {}
        if time_param and sort in ["top", "controversial"]:
            params["t"] = time_param

        requested_limit = limit or 25
        effective_limit = min(requested_limit, 100)
        params["limit"] = effective_limit

        total_start = time.time()
        request_count = 0

        # Proxy usage tracking
        proxy_requests = 0
        direct_requests = 0

        try:
            url = f"{feed_url}?{urlencode(params)}" if params else feed_url
            api_start = time.time()
            logger.info(
                f"[RedditNode] 🔌 Feed request ({proxy_mode} proxy) {url}"
            )

            response, used_proxy = await self._fetch_page_with_retry(
                url, 1, proxy_mode
            )
            request_count = 1

            if used_proxy:
                proxy_requests += 1
            else:
                direct_requests += 1

            logger.info(
                f"[RedditNode] ✅ Feed request: "
                f"status={response.status_code}, "
                f"proxy={'yes' if used_proxy else 'no'}, "
                f"time={time.time() - api_start:.3f}s"
            )

            if response.status_code >= 400:
                error_text = response.text
                logger.error(
                    f"[RedditNode] Feed fetch error: {response.status_code} - {error_text}"
                )
                raise ValueError(
                    f"Reddit feed error ({response.status_code}): {error_text}"
                )

            all_posts = self._parse_feed_entries(response.content)[:effective_limit]

            total_time = time.time() - total_start
            logger.info(
                f"[RedditNode] Fetched {len(all_posts)} posts across "
                f"{request_count} request(s) in {total_time:.3f}s "
                f"(direct={direct_requests}, proxy={proxy_requests})"
            )
            return {
                "posts": all_posts,
                "proxy_stats": {
                    "mode": proxy_mode,
                    "direct_requests": direct_requests,
                    "proxy_requests": proxy_requests,
                    "total_requests": direct_requests + proxy_requests,
                },
            }

        except Exception as e:
            logger.error(f"[RedditNode] Feed fetch failed: {str(e)}")
            raise ValueError(f"Failed to fetch Reddit feed: {str(e)}")

    async def _fetch_public_subreddit_posts(
        self,
        subreddit: str,
        sort: str = "",
        time_period: Optional[str] = None,
        limit: Optional[int] = 25,
        fetch_comments: Optional[str] = "false",
        use_proxy: Optional[str] = "auto",
        content_mode: Optional[str] = "fast",
    ) -> Dict[str, Any]:
        """Fetch public subreddit posts.

        Fast mode is RSS direct-first with proxy retry handled by _reddit_get.
        Rich mode explicitly uses Bright Data's Reddit scraper.
        """
        proxy_mode = use_proxy or "auto"
        should_fetch_comments = fetch_comments and fetch_comments.lower() == "true"
        normalized_content_mode = (content_mode or "fast").lower()

        def annotate_brightdata_result(result: Dict[str, Any]) -> Dict[str, Any]:
            if sort:
                result["sort"] = sort
            # Bright Data's discover-by-subreddit API only accepts a sort, so the
            # time period cannot be applied — say so instead of echoing it back.
            if sort in ["top", "controversial"] and time_period:
                result["note"] = (
                    f"Time period '{time_period}' is not supported in rich mode; "
                    f"results reflect Reddit's default '{sort}' view."
                )
            if should_fetch_comments:
                result["comments_fetched"] = True
            return result

        if normalized_content_mode == "rich":
            try:
                result = await self._fetch_public_subreddit_posts_via_brightdata(
                    subreddit=subreddit,
                    sort=sort,
                    limit=limit,
                    fetch_comments=fetch_comments,
                )
                return annotate_brightdata_result(result)
            except Exception as exc:
                logger.warning(
                    "[RedditNode] Rich Bright Data scrape failed, falling back to public feed: %s",
                    exc,
                )
                result = await self._fetch_public_feed_subreddit_posts(
                    subreddit=subreddit,
                    sort=sort,
                    time_period=time_period,
                    limit=limit,
                    should_fetch_comments=bool(should_fetch_comments),
                    proxy_mode=proxy_mode,
                )
                result["fallback_reason"] = "brightdata_failed"
                return result

        try:
            result = await self._fetch_public_feed_subreddit_posts(
                subreddit=subreddit,
                sort=sort,
                time_period=time_period,
                limit=limit,
                should_fetch_comments=bool(should_fetch_comments),
                proxy_mode=proxy_mode,
            )
            result["content_mode"] = "fast"
            return result
        except Exception as exc:
            logger.warning(
                "[RedditNode] Public feed scrape failed, falling back to Bright Data: %s",
                exc,
            )
            result = await self._fetch_public_subreddit_posts_via_brightdata(
                subreddit=subreddit,
                sort=sort,
                limit=limit,
                fetch_comments=fetch_comments,
            )
            annotate_brightdata_result(result)
            result["fallback_reason"] = "public_feed_failed"
            return result

    async def _fetch_public_feed_subreddit_posts(
        self,
        subreddit: str,
        sort: str,
        time_period: Optional[str],
        limit: Optional[int],
        should_fetch_comments: bool,
        proxy_mode: str,
    ) -> Dict[str, Any]:
        sort_param = sort if sort else ""
        feed_result = await self._fetch_rss_feed(
            subreddit,
            sort=sort_param,
            time_param=time_period if sort in ["top", "controversial"] else None,
            limit=limit,
            proxy_mode=proxy_mode,
        )

        posts = feed_result["posts"]
        proxy_stats = feed_result["proxy_stats"]

        # Optionally fetch comments for each post
        if should_fetch_comments:
            logger.info(f"[RedditNode] Fetching comments for {len(posts)} posts...")
            await self._attach_public_feed_comments(posts, subreddit, proxy_mode)

        result: Dict[str, Any] = {
            "posts": posts,
            "count": len(posts),
            "subreddit": subreddit,
            "source": "public_feed",
            "proxy": proxy_stats,
        }

        if sort:
            result["sort"] = sort

        if sort in ["top", "controversial"]:
            result["time_period"] = time_period

        if should_fetch_comments:
            result["comments_fetched"] = True

        return result
