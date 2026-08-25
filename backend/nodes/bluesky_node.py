"""
BlueSky (AT Protocol) automation node implementation.

Comprehensive integration with the AT Protocol and BlueSky API supporting 149 operations:
- Actor APIs: Profile management, search, preferences
- Feed APIs: Posts, timelines, quotes, likes, reposts
- Graph APIs: Followers, follows, blocks, mutes, lists, starter packs
- Bookmark APIs: Save and manage bookmarks
- Notification APIs: Read notifications, manage preferences
- Chat APIs: Direct messages and conversations
- Video APIs: Video upload and management
- Repo APIs: Repository operations
- Identity APIs: Handle and DID resolution

API Documentation: https://docs.bsky.app/docs/api/at-protocol-xrpc-api
"""

import time
import logging
from typing import Dict, Any, Optional, Union, Type, Literal, List, Annotated
from datetime import datetime, timezone
from pydantic import BaseModel, Field, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig

logger = logging.getLogger(__name__)

BLUESKY_API_BASE = "https://bsky.social/xrpc"


# ============================================================================
# Helper Functions
# ============================================================================


async def resolve_handle_to_did(handle: str) -> tuple[Optional[str], Optional[str]]:
    """
    Resolve a BlueSky handle to its DID.

    Args:
        handle: BlueSky handle (e.g., 'alice.bsky.social')

    Returns:
        Tuple of (did, error_message)
    """
    try:
        url = f"{BLUESKY_API_BASE}/com.atproto.identity.resolveHandle"
        params = {"handle": handle}

        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=10.0)

            if response.status_code != 200:
                error_data = (
                    response.json()
                    if response.headers.get("content-type", "").startswith(
                        "application/json"
                    )
                    else {}
                )
                return None, error_data.get(
                    "message", f"Failed to resolve handle: {response.text}"
                )

            data = response.json()
            did = data.get("did")

            if not did:
                return None, "Handle resolved but DID not found"

            return did, None

    except Exception as e:
        return None, f"Error resolving handle: {str(e)}"


async def fetch_post_cid(
    post_uri: str, access_token: str
) -> tuple[Optional[str], Optional[str]]:
    """
    Fetch the CID (Content Identifier) for a post given its URI.

    Args:
        post_uri: AT Protocol URI of the post
        access_token: JWT access token for authentication

    Returns:
        Tuple of (cid, error_message)
    """
    try:
        # Parse the URI to get repo, collection, and rkey
        uri_parts = post_uri.replace("at://", "").split("/")
        if len(uri_parts) < 3:
            return None, f"Invalid post URI format: {post_uri}"

        repo, collection, rkey = uri_parts[0], uri_parts[1], uri_parts[2]

        # Use getRecord to fetch the post and get its CID
        url = f"{BLUESKY_API_BASE}/com.atproto.repo.getRecord"
        params = {"repo": repo, "collection": collection, "rkey": rkey}
        headers = {"Authorization": f"Bearer {access_token}"}

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url, headers=headers, params=params, timeout=30.0
            )

            if response.status_code != 200:
                error_data = (
                    response.json()
                    if response.headers.get("content-type", "").startswith(
                        "application/json"
                    )
                    else {}
                )
                return None, error_data.get(
                    "message", f"Failed to fetch post: {response.text}"
                )

            data = response.json()
            cid = data.get("cid")

            if not cid:
                return None, "Post found but CID not available"

            return cid, None

    except Exception as e:
        return None, f"Error fetching CID: {str(e)}"


async def parse_bluesky_url_to_uri(
    url_or_uri: str, user_did: Optional[str] = None
) -> tuple[str, Optional[str]]:
    """
    Convert BlueSky web URL to AT Protocol URI with DID resolution.

    Handles formats:
    - AT URI: at://did:plc:xxx/app.bsky.feed.post/3mamyrzne372q
    - Web URL: https://bsky.app/profile/alice.bsky.social/post/example-post-id

    Args:
        url_or_uri: Either an AT URI or BlueSky web URL
        user_did: Optional DID to use if URL contains a handle

    Returns:
        Tuple of (at_uri, error_message)
    """
    # Already an AT URI
    if url_or_uri.startswith("at://"):
        return url_or_uri, None

    # Try to parse as BlueSky web URL
    if "bsky.app/profile/" in url_or_uri or "bsky.social/profile/" in url_or_uri:
        try:
            # Extract parts from URL
            # Format: https://bsky.app/profile/{handle}/post/{rkey}
            parts = url_or_uri.split("/")

            # Find 'profile' index
            profile_idx = None
            for i, part in enumerate(parts):
                if part == "profile":
                    profile_idx = i
                    break

            if profile_idx is None or len(parts) < profile_idx + 4:
                return url_or_uri, "Invalid BlueSky URL format"

            handle = parts[profile_idx + 1]
            post_type = parts[profile_idx + 2]  # 'post', 'lists', etc.
            rkey = parts[profile_idx + 3]

            # Map post type to collection
            collection_map = {
                "post": "app.bsky.feed.post",
                "lists": "app.bsky.graph.list",
            }
            collection = collection_map.get(post_type, f"app.bsky.{post_type}")

            # Resolve handle to DID
            did, error = await resolve_handle_to_did(handle)
            if error:
                return url_or_uri, f"Failed to resolve handle '{handle}': {error}"

            # Create AT URI with DID
            at_uri = f"at://{did}/{collection}/{rkey}"
            return at_uri, None

        except (IndexError, ValueError) as e:
            return url_or_uri, f"Failed to parse BlueSky URL: {str(e)}"

    # Return as-is with no error (might be valid URI format we don't recognize)
    return url_or_uri, None


# ============================================================================
# BlueSky Node Credential Schemas
# ============================================================================


class BlueSkyAppPasswordCredential(BaseModel):
    """BlueSky App Password credential (recommended for automation).

    Create an App Password from BlueSky settings for secure API access
    without exposing your main account password.
    """

    credential_type: Literal["bluesky_handle_password"] = Field(
        "bluesky_handle_password", json_schema_extra={"ui:hidden": True}
    )
    identifier: str = Field(
        ...,
        min_length=1,
        title="Handle or Email",
        description="Your BlueSky handle (e.g., user.bsky.social) or email address",
        json_schema_extra={"placeholder": "user.bsky.social"},
    )
    app_password: str = Field(
        ...,
        min_length=1,
        title="App Password",
        description="App Password from BlueSky settings (not your main password)",
        json_schema_extra={
            "ui:widget": "password",
            "placeholder": "xxxx-xxxx-xxxx-xxxx",
            "x-credential-url": "https://bsky.app/settings/app-passwords",
        },
    )


# BlueSky credential type - App Password only
BlueSkyCredential = BlueSkyAppPasswordCredential


# ============================================================================
# Post Operations (10 configs)
# ============================================================================


class BlueSkyCreatePostConfig(BaseModel):
    """Create a new post"""

    operation: Literal["create_post"] = Field(
        "create_post",
        json_schema_extra={
            "const": "create_post",
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Create Post",
        },
        title="Create Post",
    )
    text: str = Field(
        ...,
        min_length=1,
        max_length=300,
        title="Post Text",
        description="The text content of your post (max 300 characters)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    reply_to_uri: Optional[str] = Field(
        None, title="Reply To URI", description="Optional: AT URI of post to reply to"
    )
    reply_to_cid: Optional[str] = Field(
        None,
        title="Reply To CID",
        description="Optional: CID of the post being replied to",
    )


class BlueSkyDeletePostConfig(BaseModel):
    """Delete a post"""

    operation: Literal["delete_post"] = Field(
        "delete_post",
        json_schema_extra={
            "const": "delete_post",
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Delete Post",
        },
        title="Delete Post",
    )
    post_uri: str = Field(
        ...,
        min_length=1,
        title="Post URL or URI",
        description="BlueSky URL (https://bsky.app/profile/.../post/...) or AT URI (at://...)",
    )


class BlueSkyGetPostThreadConfig(BaseModel):
    """Get a post and its thread context"""

    operation: Literal["get_post_thread"] = Field(
        "get_post_thread",
        json_schema_extra={
            "const": "get_post_thread",
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Get Post Thread",
        },
        title="Get Post Thread",
    )
    post_uri: str = Field(
        ...,
        min_length=1,
        title="Post URL or URI",
        description="BlueSky URL (https://bsky.app/profile/.../post/...) or AT URI (at://...)",
    )
    depth: int = Field(
        6,
        ge=0,
        le=1000,
        title="Reply Depth",
        description="How many levels of replies to include",
    )


class BlueSkyGetPostsConfig(BaseModel):
    """Get multiple posts by their URIs"""

    operation: Literal["get_posts_by_uris"] = Field(
        "get_posts_by_uris",
        json_schema_extra={
            "const": "get_posts_by_uris",
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Get Posts by Uris",
        },
        title="Get Posts by Uris",
    )
    uris: List[str] = Field(
        ...,
        min_items=1,
        max_items=25,
        title="Post URIs",
        description="List of AT URIs to retrieve (max 25)",
    )


class BlueSkyLikePostConfig(BaseModel):
    """Like a post"""

    operation: Literal["like_post"] = Field(
        "like_post",
        json_schema_extra={
            "const": "like_post",
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Like Post",
        },
        title="Like Post",
    )
    post_uri: str = Field(
        ...,
        min_length=1,
        title="Post URL or URI",
        description="BlueSky URL (https://bsky.app/profile/.../post/...) or AT URI (at://...)",
    )
    post_cid: Optional[str] = Field(
        None,
        title="Post CID",
        description="CID of the post (will be fetched automatically if not provided)",
    )


class BlueSkyUnlikePostConfig(BaseModel):
    """Unlike a post (remove like)"""

    operation: Literal["unlike_post"] = Field(
        "unlike_post",
        json_schema_extra={
            "const": "unlike_post",
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Unlike Post",
        },
        title="Unlike Post",
    )
    post_uri: str = Field(
        ...,
        min_length=1,
        title="Post URL or URI",
        description="BlueSky URL (https://bsky.app/profile/.../post/...) or AT URI (at://...) of the post to unlike",
    )


class BlueSkyRepostConfig(BaseModel):
    """Repost a post"""

    operation: Literal["repost_post"] = Field(
        "repost_post",
        json_schema_extra={
            "const": "repost_post",
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Repost Post",
        },
        title="Repost Post",
    )
    post_uri: str = Field(
        ..., min_length=1, title="Post URI", description="AT URI of the post to repost"
    )
    post_cid: Optional[str] = Field(
        None,
        title="Post CID",
        description="CID of the post (will be fetched automatically if not provided)",
    )


class BlueSkyUnrepostConfig(BaseModel):
    """Remove a repost"""

    operation: Literal["remove_repost"] = Field(
        "remove_repost",
        json_schema_extra={
            "const": "remove_repost",
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Remove Repost",
        },
        title="Remove Repost",
    )
    post_uri: str = Field(
        ...,
        min_length=1,
        title="Post URL or URI",
        description="BlueSky URL (https://bsky.app/profile/.../post/...) or AT URI (at://...) of the post to unrepost",
    )


class BlueSkyGetLikesConfig(BaseModel):
    """Get users who liked a post"""

    operation: Literal["list_post_likers"] = Field(
        "list_post_likers",
        json_schema_extra={
            "const": "list_post_likers",
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "List Post Likers",
        },
        title="List Post Likers",
    )
    post_uri: str = Field(
        ...,
        min_length=1,
        title="Post URL or URI",
        description="BlueSky URL (https://bsky.app/profile/.../post/...) or AT URI (at://...)",
    )
    limit: int = Field(
        50,
        ge=1,
        le=100,
        title="Limit",
        description="Number of likes to retrieve (1-100)",
    )
    cursor: Optional[str] = Field(None, title="Cursor", description="Pagination cursor")


class BlueSkyGetRepostedByConfig(BaseModel):
    """Get users who reposted a post"""

    operation: Literal["list_post_reposters"] = Field(
        "list_post_reposters",
        json_schema_extra={
            "const": "list_post_reposters",
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "List Post Reposters",
        },
        title="List Post Reposters",
    )
    post_uri: str = Field(
        ...,
        min_length=1,
        title="Post URL or URI",
        description="BlueSky URL (https://bsky.app/profile/.../post/...) or AT URI (at://...)",
    )
    limit: int = Field(
        50,
        ge=1,
        le=100,
        title="Limit",
        description="Number of reposts to retrieve (1-100)",
    )
    cursor: Optional[str] = Field(None, title="Cursor", description="Pagination cursor")


class BlueSkyGetQuotesConfig(BaseModel):
    """Get posts that quote a specific post"""

    operation: Literal["list_post_quotes"] = Field(
        "list_post_quotes",
        json_schema_extra={
            "const": "list_post_quotes",
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "List Post Quotes",
        },
        title="List Post Quotes",
    )
    post_uri: str = Field(
        ...,
        min_length=1,
        title="Post URL or URI",
        description="BlueSky URL (https://bsky.app/profile/.../post/...) or AT URI (at://...)",
    )
    limit: int = Field(
        50,
        ge=1,
        le=100,
        title="Limit",
        description="Number of quotes to retrieve (1-100)",
    )
    cursor: Optional[str] = Field(None, title="Cursor", description="Pagination cursor")


class BlueSkySearchPostsConfig(BaseModel):
    """Search for posts"""

    operation: Literal["search_posts"] = Field(
        "search_posts",
        json_schema_extra={
            "const": "search_posts",
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Search Posts",
        },
        title="Search Posts",
    )
    query: str = Field(
        ..., min_length=1, title="Search Query", description="Search query string"
    )
    limit: int = Field(
        25, ge=1, le=100, title="Limit", description="Number of results (1-100)"
    )
    sort: Optional[str] = Field(
        "latest",
        title="Sort Order",
        description="Sort order for results",
        json_schema_extra={"enum": ["top", "latest"]},
    )
    cursor: Optional[str] = Field(None, title="Cursor", description="Pagination cursor")


# ============================================================================
# Feed Operations (8 configs)
# ============================================================================


class BlueSkyGetTimelineConfig(BaseModel):
    """Get the authenticated user's home timeline"""

    operation: Literal["get_home_timeline"] = Field(
        "get_home_timeline",
        json_schema_extra={
            "const": "get_home_timeline",
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Get Home Timeline",
        },
        title="Get Home Timeline",
    )
    limit: int = Field(
        50,
        ge=1,
        le=100,
        title="Limit",
        description="Number of posts to retrieve (1-100)",
    )
    cursor: Optional[str] = Field(None, title="Cursor", description="Pagination cursor")


class BlueSkyGetAuthorFeedConfig(BaseModel):
    """Get posts from a specific user's feed"""

    operation: Literal["get_author_feed"] = Field(
        "get_author_feed",
        json_schema_extra={
            "const": "get_author_feed",
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Get Author Feed",
        },
        title="Get Author Feed",
    )
    actor: str = Field(
        ...,
        min_length=1,
        title="Actor Handle or DID",
        description="Handle (e.g., user.bsky.social) or DID of the user",
    )
    limit: int = Field(
        50,
        ge=1,
        le=100,
        title="Limit",
        description="Number of posts to retrieve (1-100)",
    )
    filter: Optional[str] = Field(
        "posts_and_author_threads",
        title="Filter",
        description="Type of posts to include",
        json_schema_extra={
            "enum": [
                "posts_with_replies",
                "posts_no_replies",
                "posts_with_media",
                "posts_and_author_threads",
            ]
        },
    )
    cursor: Optional[str] = Field(None, title="Cursor", description="Pagination cursor")


class BlueSkyGetActorLikesConfig(BaseModel):
    """Get posts liked by an actor"""

    operation: Literal["list_actor_liked_posts"] = Field(
        "list_actor_liked_posts",
        json_schema_extra={
            "const": "list_actor_liked_posts",
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "List Actor Liked Posts",
        },
        title="List Actor Liked Posts",
    )
    actor: str = Field(..., min_length=1, title="Actor Handle or DID")
    limit: int = Field(
        50, ge=1, le=100, title="Limit", description="Number of liked posts (1-100)"
    )
    cursor: Optional[str] = Field(None, title="Cursor", description="Pagination cursor")


class BlueSkyGetFeedGeneratorConfig(BaseModel):
    """Get information about a feed generator"""

    operation: Literal["get_feed_generator"] = Field(
        "get_feed_generator",
        json_schema_extra={
            "const": "get_feed_generator",
            "ui:hidden": True,
            "x-category": "Feed",
            "x-is-trigger": False,
            "x-display-name": "Get Feed Generator",
        },
        title="Get Feed Generator",
    )
    feed_uri: str = Field(
        ..., min_length=1, title="Feed URI", description="AT URI of the feed generator"
    )


class BlueSkyGetActorFeedsConfig(BaseModel):
    """Get feed generators created by an actor"""

    operation: Literal["list_actor_feed_generators"] = Field(
        "list_actor_feed_generators",
        json_schema_extra={
            "const": "list_actor_feed_generators",
            "ui:hidden": True,
            "x-category": "Feed",
            "x-is-trigger": False,
            "x-display-name": "List Actor Feed Generators",
        },
        title="List Actor Feed Generators",
    )
    actor: str = Field(..., min_length=1, title="Actor Handle or DID")
    limit: int = Field(
        50, ge=1, le=100, title="Limit", description="Number of feeds (1-100)"
    )
    cursor: Optional[str] = Field(None, title="Cursor", description="Pagination cursor")


class BlueSkyGetSuggestedFeedsConfig(BaseModel):
    """Get suggested feed generators"""

    operation: Literal["list_suggested_feeds"] = Field(
        "list_suggested_feeds",
        json_schema_extra={
            "const": "list_suggested_feeds",
            "ui:hidden": True,
            "x-category": "Feed",
            "x-is-trigger": False,
            "x-display-name": "List Suggested Feeds",
        },
        title="List Suggested Feeds",
    )
    limit: int = Field(
        50, ge=1, le=100, title="Limit", description="Number of suggestions (1-100)"
    )
    cursor: Optional[str] = Field(None, title="Cursor", description="Pagination cursor")


class BlueSkyGetListFeedConfig(BaseModel):
    """Get posts from members of a list"""

    operation: Literal["get_list_member_feed"] = Field(
        "get_list_member_feed",
        json_schema_extra={
            "const": "get_list_member_feed",
            "ui:hidden": True,
            "x-category": "List",
            "x-is-trigger": False,
            "x-display-name": "Get List Member Feed",
        },
        title="Get List Member Feed",
    )
    list_uri: str = Field(
        ..., min_length=1, title="List URI", description="AT URI of the list"
    )
    limit: int = Field(
        50, ge=1, le=100, title="Limit", description="Number of posts (1-100)"
    )
    cursor: Optional[str] = Field(None, title="Cursor", description="Pagination cursor")


class BlueSkyGetFeedConfig(BaseModel):
    """Get posts from a custom feed"""

    operation: Literal["get_custom_feed_posts"] = Field(
        "get_custom_feed_posts",
        json_schema_extra={
            "const": "get_custom_feed_posts",
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Get Custom Feed Posts",
        },
        title="Get Custom Feed Posts",
    )
    feed_uri: str = Field(
        ..., min_length=1, title="Feed URI", description="AT URI of the feed"
    )
    limit: int = Field(
        50, ge=1, le=100, title="Limit", description="Number of posts (1-100)"
    )
    cursor: Optional[str] = Field(None, title="Cursor", description="Pagination cursor")


# ============================================================================
# Actor/Profile Operations (7 configs)
# ============================================================================


class BlueSkyGetProfileConfig(BaseModel):
    """Get a user's profile information"""

    operation: Literal["get_user_profile"] = Field(
        "get_user_profile",
        json_schema_extra={
            "const": "get_user_profile",
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get User Profile",
        },
        title="Get User Profile",
    )
    actor: str = Field(
        ...,
        min_length=1,
        title="Actor Handle or DID",
        description="Handle (e.g., user.bsky.social) or DID of the user",
    )


class BlueSkyGetProfilesConfig(BaseModel):
    """Get multiple user profiles at once"""

    operation: Literal["get_multiple_user_profiles"] = Field(
        "get_multiple_user_profiles",
        json_schema_extra={
            "const": "get_multiple_user_profiles",
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get Multiple User Profiles",
        },
        title="Get Multiple User Profiles",
    )
    actors: List[str] = Field(
        ...,
        min_items=1,
        max_items=25,
        title="Actor Handles or DIDs",
        description="List of handles or DIDs (max 25)",
    )


class BlueSkySearchActorsConfig(BaseModel):
    """Search for actors/users"""

    operation: Literal["search_actors"] = Field(
        "search_actors",
        json_schema_extra={
            "const": "search_actors",
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Search Actors",
        },
        title="Search Actors",
    )
    query: str = Field(
        ..., min_length=1, title="Search Query", description="Search term"
    )
    limit: int = Field(
        25, ge=1, le=100, title="Limit", description="Number of results (1-100)"
    )
    cursor: Optional[str] = Field(None, title="Cursor", description="Pagination cursor")


class BlueSkySearchActorsTypeaheadConfig(BaseModel):
    """Typeahead search for actors (for autocomplete)"""

    operation: Literal["search_actors_typeahead"] = Field(
        "search_actors_typeahead",
        json_schema_extra={
            "const": "search_actors_typeahead",
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Search Actors Typeahead",
        },
        title="Search Actors Typeahead",
    )
    query: str = Field(
        ..., min_length=1, title="Search Query", description="Partial search term"
    )
    limit: int = Field(
        10, ge=1, le=100, title="Limit", description="Number of results (1-100)"
    )


class BlueSkyGetSuggestionsConfig(BaseModel):
    """Get suggested accounts to follow"""

    operation: Literal["list_suggested_accounts"] = Field(
        "list_suggested_accounts",
        json_schema_extra={
            "const": "list_suggested_accounts",
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "List Suggested Accounts",
        },
        title="List Suggested Accounts",
    )
    limit: int = Field(
        50, ge=1, le=100, title="Limit", description="Number of suggestions (1-100)"
    )
    cursor: Optional[str] = Field(None, title="Cursor", description="Pagination cursor")


class BlueSkyGetPreferencesConfig(BaseModel):
    """Get user preferences"""

    operation: Literal["get_user_preferences"] = Field(
        "get_user_preferences",
        json_schema_extra={
            "const": "get_user_preferences",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Get User Preferences",
        },
        title="Get User Preferences",
    )


class BlueSkyPutPreferencesConfig(BaseModel):
    """Update user preferences"""

    operation: Literal["update_user_preferences"] = Field(
        "update_user_preferences",
        json_schema_extra={
            "const": "update_user_preferences",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Update User Preferences",
        },
        title="Update User Preferences",
    )
    preferences: Dict[str, Any] = Field(
        ..., title="Preferences", description="Preferences object to update"
    )


# ============================================================================
# Graph/Social Operations (15 configs)
# ============================================================================


class BlueSkyFollowUserConfig(BaseModel):
    """Follow a user"""

    operation: Literal["follow_user"] = Field(
        "follow_user",
        json_schema_extra={
            "const": "follow_user",
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Follow User",
        },
        title="Follow User",
    )
    subject_did: str = Field(
        ..., min_length=1, title="User DID", description="DID of the user to follow"
    )


class BlueSkyUnfollowUserConfig(BaseModel):
    """Unfollow a user"""

    operation: Literal["unfollow_user"] = Field(
        "unfollow_user",
        json_schema_extra={
            "const": "unfollow_user",
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Unfollow User",
        },
        title="Unfollow User",
    )
    follow_uri: str = Field(
        ...,
        min_length=1,
        title="Follow URI",
        description="AT URI of the follow record to delete",
    )


class BlueSkyGetFollowersConfig(BaseModel):
    """Get an actor's followers"""

    operation: Literal["list_actor_followers"] = Field(
        "list_actor_followers",
        json_schema_extra={
            "const": "list_actor_followers",
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "List Actor Followers",
        },
        title="List Actor Followers",
    )
    actor: str = Field(..., min_length=1, title="Actor Handle or DID")
    limit: int = Field(
        50, ge=1, le=100, title="Limit", description="Number of followers (1-100)"
    )
    cursor: Optional[str] = Field(None, title="Cursor", description="Pagination cursor")


class BlueSkyGetFollowsConfig(BaseModel):
    """Get accounts that an actor follows"""

    operation: Literal["list_actor_follows"] = Field(
        "list_actor_follows",
        json_schema_extra={
            "const": "list_actor_follows",
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "List Actor Follows",
        },
        title="List Actor Follows",
    )
    actor: str = Field(..., min_length=1, title="Actor Handle or DID")
    limit: int = Field(
        50, ge=1, le=100, title="Limit", description="Number of follows (1-100)"
    )
    cursor: Optional[str] = Field(None, title="Cursor", description="Pagination cursor")


class BlueSkyBlockUserConfig(BaseModel):
    """Block a user"""

    operation: Literal["block_user"] = Field(
        "block_user",
        json_schema_extra={
            "const": "block_user",
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Block User",
        },
        title="Block User",
    )
    subject_did: str = Field(
        ..., min_length=1, title="User DID", description="DID of the user to block"
    )


class BlueSkyUnblockUserConfig(BaseModel):
    """Unblock a user"""

    operation: Literal["unblock_user"] = Field(
        "unblock_user",
        json_schema_extra={
            "const": "unblock_user",
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Unblock User",
        },
        title="Unblock User",
    )
    block_uri: str = Field(
        ...,
        min_length=1,
        title="Block URI",
        description="AT URI of the block record to delete",
    )


class BlueSkyGetBlocksConfig(BaseModel):
    """Get blocked accounts"""

    operation: Literal["list_blocked_accounts"] = Field(
        "list_blocked_accounts",
        json_schema_extra={
            "const": "list_blocked_accounts",
            "ui:hidden": True,
            "x-category": "Block",
            "x-is-trigger": False,
            "x-display-name": "List Blocked Accounts",
        },
        title="List Blocked Accounts",
    )
    limit: int = Field(
        50, ge=1, le=100, title="Limit", description="Number of blocks (1-100)"
    )
    cursor: Optional[str] = Field(None, title="Cursor", description="Pagination cursor")


class BlueSkyMuteActorConfig(BaseModel):
    """Mute an actor"""

    operation: Literal["mute_actor"] = Field(
        "mute_actor",
        json_schema_extra={
            "const": "mute_actor",
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Mute Actor",
        },
        title="Mute Actor",
    )
    actor: str = Field(..., min_length=1, title="Actor Handle or DID")


class BlueSkyUnmuteActorConfig(BaseModel):
    """Unmute an actor"""

    operation: Literal["unmute_actor"] = Field(
        "unmute_actor",
        json_schema_extra={
            "const": "unmute_actor",
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Unmute Actor",
        },
        title="Unmute Actor",
    )
    actor: str = Field(..., min_length=1, title="Actor Handle or DID")


class BlueSkyGetMutesConfig(BaseModel):
    """Get muted accounts"""

    operation: Literal["list_muted_accounts"] = Field(
        "list_muted_accounts",
        json_schema_extra={
            "const": "list_muted_accounts",
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "List Muted Accounts",
        },
        title="List Muted Accounts",
    )
    limit: int = Field(
        50, ge=1, le=100, title="Limit", description="Number of mutes (1-100)"
    )
    cursor: Optional[str] = Field(None, title="Cursor", description="Pagination cursor")


class BlueSkyMuteThreadConfig(BaseModel):
    """Mute a thread"""

    operation: Literal["mute_thread"] = Field(
        "mute_thread",
        json_schema_extra={
            "const": "mute_thread",
            "ui:hidden": True,
            "x-category": "Thread",
            "x-is-trigger": False,
            "x-display-name": "Mute Thread",
        },
        title="Mute Thread",
    )
    root_uri: str = Field(
        ...,
        min_length=1,
        title="Root Post URI",
        description="AT URI of the thread root",
    )


class BlueSkyUnmuteThreadConfig(BaseModel):
    """Unmute a thread"""

    operation: Literal["unmute_thread"] = Field(
        "unmute_thread",
        json_schema_extra={
            "const": "unmute_thread",
            "ui:hidden": True,
            "x-category": "Thread",
            "x-is-trigger": False,
            "x-display-name": "Unmute Thread",
        },
        title="Unmute Thread",
    )
    root_uri: str = Field(
        ...,
        min_length=1,
        title="Root Post URI",
        description="AT URI of the thread root",
    )


class BlueSkyGetListConfig(BaseModel):
    """Get a list and its members"""

    operation: Literal["get_list_with_members"] = Field(
        "get_list_with_members",
        json_schema_extra={
            "const": "get_list_with_members",
            "ui:hidden": True,
            "x-category": "List",
            "x-is-trigger": False,
            "x-display-name": "Get List with Members",
        },
        title="Get List with Members",
    )
    list_uri: str = Field(
        ..., min_length=1, title="List URI", description="AT URI of the list"
    )
    limit: int = Field(
        50, ge=1, le=100, title="Limit", description="Number of members (1-100)"
    )
    cursor: Optional[str] = Field(None, title="Cursor", description="Pagination cursor")


class BlueSkyGetListsConfig(BaseModel):
    """Get lists created by an actor"""

    operation: Literal["list_actor_lists"] = Field(
        "list_actor_lists",
        json_schema_extra={
            "const": "list_actor_lists",
            "ui:hidden": True,
            "x-category": "List",
            "x-is-trigger": False,
            "x-display-name": "List Actor Lists",
        },
        title="List Actor Lists",
    )
    actor: str = Field(..., min_length=1, title="Actor Handle or DID")
    limit: int = Field(
        50, ge=1, le=100, title="Limit", description="Number of lists (1-100)"
    )
    cursor: Optional[str] = Field(None, title="Cursor", description="Pagination cursor")


class BlueSkyGetRelationshipsConfig(BaseModel):
    """Get relationships between actors"""

    operation: Literal["get_actor_relationships"] = Field(
        "get_actor_relationships",
        json_schema_extra={
            "const": "get_actor_relationships",
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get Actor Relationships",
        },
        title="Get Actor Relationships",
    )
    actor: str = Field(
        ..., min_length=1, title="Actor Handle or DID", description="Primary actor"
    )
    others: List[str] = Field(
        ...,
        min_items=1,
        max_items=30,
        title="Other Actors",
        description="List of other actors to check relationships with (max 30)",
    )


# ============================================================================
# Bookmark Operations (3 configs)
# ============================================================================


class BlueSkyCreateBookmarkConfig(BaseModel):
    """Save a post to bookmarks"""

    operation: Literal["create_post_bookmark"] = Field(
        "create_post_bookmark",
        json_schema_extra={
            "const": "create_post_bookmark",
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Create Post Bookmark",
        },
        title="Create Post Bookmark",
    )
    post_uri: str = Field(
        ...,
        min_length=1,
        title="Post URI",
        description="AT URI of the post to bookmark",
    )
    post_cid: Optional[str] = Field(
        None,
        title="Post CID",
        description="CID of the post (will be fetched automatically if not provided)",
    )


class BlueSkyDeleteBookmarkConfig(BaseModel):
    """Remove a bookmark"""

    operation: Literal["delete_post_bookmark"] = Field(
        "delete_post_bookmark",
        json_schema_extra={
            "const": "delete_post_bookmark",
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Delete Post Bookmark",
        },
        title="Delete Post Bookmark",
    )
    post_uri: str = Field(
        ...,
        min_length=1,
        title="Post URL or URI",
        description="BlueSky URL (https://bsky.app/profile/.../post/...) or AT URI (at://...) of the post to remove bookmark from",
    )


class BlueSkyGetBookmarksConfig(BaseModel):
    """Get user's bookmarks"""

    operation: Literal["list_bookmarks"] = Field(
        "list_bookmarks",
        json_schema_extra={
            "const": "list_bookmarks",
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "List Bookmarks",
        },
        title="List Bookmarks",
    )
    limit: int = Field(
        50, ge=1, le=100, title="Limit", description="Number of bookmarks (1-100)"
    )
    cursor: Optional[str] = Field(None, title="Cursor", description="Pagination cursor")


# ============================================================================
# Notification Operations (8 configs)
# ============================================================================


class BlueSkyListNotificationsConfig(BaseModel):
    """List notifications for the authenticated user"""

    operation: Literal["list_notifications"] = Field(
        "list_notifications",
        json_schema_extra={
            "const": "list_notifications",
            "ui:hidden": True,
            "x-category": "Notification",
            "x-is-trigger": False,
            "x-display-name": "List Notifications",
        },
        title="List Notifications",
    )
    limit: int = Field(
        50, ge=1, le=100, title="Limit", description="Number of notifications (1-100)"
    )
    cursor: Optional[str] = Field(None, title="Cursor", description="Pagination cursor")
    seen_at: Optional[str] = Field(
        None, title="Seen At", description="ISO timestamp for filtering"
    )


class BlueSkyGetUnreadCountConfig(BaseModel):
    """Get count of unread notifications"""

    operation: Literal["get_unread_notification_count"] = Field(
        "get_unread_notification_count",
        json_schema_extra={
            "const": "get_unread_notification_count",
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Get Unread Notification Count",
        },
        title="Get Unread Notification Count",
    )
    seen_at: Optional[str] = Field(
        None, title="Seen At", description="ISO timestamp for filtering"
    )


class BlueSkyUpdateSeenConfig(BaseModel):
    """Mark notifications as seen"""

    operation: Literal["mark_notifications_as_seen"] = Field(
        "mark_notifications_as_seen",
        json_schema_extra={
            "const": "mark_notifications_as_seen",
            "ui:hidden": True,
            "x-category": "Notification",
            "x-is-trigger": False,
            "x-display-name": "Mark Notifications As Seen",
        },
        title="Mark Notifications As Seen",
    )
    seen_at: str = Field(
        ..., title="Seen At", description="ISO timestamp to mark as seen up to"
    )


class BlueSkyRegisterPushConfig(BaseModel):
    """Register device for push notifications"""

    operation: Literal["register_push_notifications"] = Field(
        "register_push_notifications",
        json_schema_extra={
            "const": "register_push_notifications",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Register Push Notifications",
        },
        title="Register Push Notifications",
    )
    service_did: str = Field(
        ..., title="Service DID", description="DID of the push service"
    )
    token: str = Field(..., title="Push Token", description="Device push token")
    platform: str = Field(
        ...,
        title="Platform",
        description="Platform (ios, android, web)",
        json_schema_extra={"enum": ["ios", "android", "web"]},
    )
    app_id: str = Field(..., title="App ID", description="Application identifier")


class BlueSkyUnregisterPushConfig(BaseModel):
    """Unregister device from push notifications"""

    operation: Literal["unregister_push_notifications"] = Field(
        "unregister_push_notifications",
        json_schema_extra={
            "const": "unregister_push_notifications",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Unregister Push Notifications",
        },
        title="Unregister Push Notifications",
    )
    service_did: str = Field(
        ..., title="Service DID", description="DID of the push service"
    )
    token: str = Field(..., title="Push Token", description="Device push token")


class BlueSkyGetNotificationPreferencesConfig(BaseModel):
    """Get notification preferences"""

    operation: Literal["get_notification_preferences"] = Field(
        "get_notification_preferences",
        json_schema_extra={
            "const": "get_notification_preferences",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Get Notification Preferences",
        },
        title="Get Notification Preferences",
    )


class BlueSkyPutNotificationPreferencesConfig(BaseModel):
    """Update notification preferences"""

    operation: Literal["update_notification_preferences"] = Field(
        "update_notification_preferences",
        json_schema_extra={
            "const": "update_notification_preferences",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Update Notification Preferences",
        },
        title="Update Notification Preferences",
    )
    preferences: Dict[str, Any] = Field(
        ..., title="Preferences", description="Notification preferences object"
    )


class BlueSkyListActivitySubscriptionsConfig(BaseModel):
    """List activity notification subscriptions"""

    operation: Literal["list_activity_subscriptions"] = Field(
        "list_activity_subscriptions",
        json_schema_extra={
            "const": "list_activity_subscriptions",
            "ui:hidden": True,
            "x-category": "Activity Subscription",
            "x-is-trigger": False,
            "x-display-name": "List Activity Subscriptions",
        },
        title="List Activity Subscriptions",
    )


# ============================================================================
# Chat/Conversation Operations (12 configs)
# ============================================================================


class BlueSkyListConversationsConfig(BaseModel):
    """List user's chat conversations"""

    operation: Literal["list_user_conversations"] = Field(
        "list_user_conversations",
        json_schema_extra={
            "const": "list_user_conversations",
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "List User Conversations",
        },
        title="List User Conversations",
    )
    limit: int = Field(
        50, ge=1, le=100, title="Limit", description="Number of conversations (1-100)"
    )
    cursor: Optional[str] = Field(None, title="Cursor", description="Pagination cursor")


class BlueSkyGetConversationConfig(BaseModel):
    """Get a specific conversation"""

    operation: Literal["get_conversation"] = Field(
        "get_conversation",
        json_schema_extra={
            "const": "get_conversation",
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Get Conversation",
        },
        title="Get Conversation",
    )
    convo_id: str = Field(
        ..., min_length=1, title="Conversation ID", description="ID of the conversation"
    )


class BlueSkyGetConversationForMembersConfig(BaseModel):
    """Get conversation with specific members"""

    operation: Literal["get_conversation_with_members"] = Field(
        "get_conversation_with_members",
        json_schema_extra={
            "const": "get_conversation_with_members",
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Get Conversation with Members",
        },
        title="Get Conversation with Members",
    )
    members: List[str] = Field(
        ...,
        min_items=1,
        max_items=10,
        title="Member DIDs",
        description="List of member DIDs (max 10)",
    )


class BlueSkyGetMessagesConfig(BaseModel):
    """Get messages from a conversation"""

    operation: Literal["list_conversation_messages"] = Field(
        "list_conversation_messages",
        json_schema_extra={
            "const": "list_conversation_messages",
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "List Conversation Messages",
        },
        title="List Conversation Messages",
    )
    convo_id: str = Field(..., min_length=1, title="Conversation ID")
    limit: int = Field(
        50, ge=1, le=100, title="Limit", description="Number of messages (1-100)"
    )
    cursor: Optional[str] = Field(None, title="Cursor", description="Pagination cursor")


class BlueSkySendMessageConfig(BaseModel):
    """Send a message in a conversation"""

    operation: Literal["send_message_in_conversation"] = Field(
        "send_message_in_conversation",
        json_schema_extra={
            "const": "send_message_in_conversation",
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Send Message in Conversation",
        },
        title="Send Message in Conversation",
    )
    convo_id: str = Field(..., min_length=1, title="Conversation ID")
    text: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        title="Message Text",
        description="Message content (max 10,000 characters)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class BlueSkyDeleteMessageConfig(BaseModel):
    """Delete a message (for self only)"""

    operation: Literal["delete_message_for_self"] = Field(
        "delete_message_for_self",
        json_schema_extra={
            "const": "delete_message_for_self",
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Delete Message for Self",
        },
        title="Delete Message for Self",
    )
    convo_id: str = Field(..., min_length=1, title="Conversation ID")
    message_id: str = Field(..., min_length=1, title="Message ID")


class BlueSkyLeaveConversationConfig(BaseModel):
    """Leave a conversation"""

    operation: Literal["leave_conversation"] = Field(
        "leave_conversation",
        json_schema_extra={
            "const": "leave_conversation",
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Leave Conversation",
        },
        title="Leave Conversation",
    )
    convo_id: str = Field(..., min_length=1, title="Conversation ID")


class BlueSkyMuteConversationConfig(BaseModel):
    """Mute a conversation"""

    operation: Literal["mute_conversation"] = Field(
        "mute_conversation",
        json_schema_extra={
            "const": "mute_conversation",
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Mute Conversation",
        },
        title="Mute Conversation",
    )
    convo_id: str = Field(..., min_length=1, title="Conversation ID")


class BlueSkyUnmuteConversationConfig(BaseModel):
    """Unmute a conversation"""

    operation: Literal["unmute_conversation"] = Field(
        "unmute_conversation",
        json_schema_extra={
            "const": "unmute_conversation",
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Unmute Conversation",
        },
        title="Unmute Conversation",
    )
    convo_id: str = Field(..., min_length=1, title="Conversation ID")


class BlueSkyUpdateConversationReadConfig(BaseModel):
    """Mark conversation as read"""

    operation: Literal["mark_conversation_read"] = Field(
        "mark_conversation_read",
        json_schema_extra={
            "const": "mark_conversation_read",
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Mark Conversation Read",
        },
        title="Mark Conversation Read",
    )
    convo_id: str = Field(..., min_length=1, title="Conversation ID")
    message_id: Optional[str] = Field(
        None, title="Message ID", description="Mark read up to this message"
    )


class BlueSkyAcceptConversationConfig(BaseModel):
    """Accept a conversation request"""

    operation: Literal["accept_conversation_request"] = Field(
        "accept_conversation_request",
        json_schema_extra={
            "const": "accept_conversation_request",
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Accept Conversation Request",
        },
        title="Accept Conversation Request",
    )
    convo_id: str = Field(..., min_length=1, title="Conversation ID")


class BlueSkyAddMessageReactionConfig(BaseModel):
    """Add a reaction to a message"""

    operation: Literal["add_reaction_to_message"] = Field(
        "add_reaction_to_message",
        json_schema_extra={
            "const": "add_reaction_to_message",
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Add Reaction to Message",
        },
        title="Add Reaction to Message",
    )
    convo_id: str = Field(..., min_length=1, title="Conversation ID")
    message_id: str = Field(..., min_length=1, title="Message ID")
    reaction: str = Field(
        ...,
        min_length=1,
        max_length=10,
        title="Reaction",
        description="Emoji or reaction string",
    )


# ============================================================================
# Video Operations (3 configs)
# ============================================================================


class BlueSkyUploadVideoConfig(BaseModel):
    """Upload a video"""

    operation: Literal["upload_video"] = Field(
        "upload_video",
        json_schema_extra={
            "const": "upload_video",
            "ui:hidden": True,
            "x-category": "Video",
            "x-is-trigger": False,
            "x-display-name": "Upload Video",
        },
        title="Upload Video",
    )
    video_data: str = Field(
        ...,
        title="Video",
        description="The video to send — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}).",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": "video/*"},
    )
    mime_type: str = Field(
        ..., title="MIME Type", description="Video MIME type (e.g., video/mp4)"
    )


class BlueSkyGetVideoJobStatusConfig(BaseModel):
    """Get video processing job status"""

    operation: Literal["get_video_job_status"] = Field(
        "get_video_job_status",
        json_schema_extra={
            "const": "get_video_job_status",
            "ui:hidden": True,
            "x-category": "Video",
            "x-is-trigger": False,
            "x-display-name": "Get Video Job Status",
        },
        title="Get Video Job Status",
    )
    job_id: str = Field(
        ..., min_length=1, title="Job ID", description="Video processing job ID"
    )


class BlueSkyGetUploadLimitsConfig(BaseModel):
    """Get video upload limits for the account"""

    operation: Literal["get_video_upload_limits"] = Field(
        "get_video_upload_limits",
        json_schema_extra={
            "const": "get_video_upload_limits",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Get Video Upload Limits",
        },
        title="Get Video Upload Limits",
    )


# ============================================================================
# Repository Operations (8 configs)
# ============================================================================


class BlueSkyCreateRecordConfig(BaseModel):
    """Create a record in the repository"""

    operation: Literal["create_repository_record"] = Field(
        "create_repository_record",
        json_schema_extra={
            "const": "create_repository_record",
            "ui:hidden": True,
            "x-category": "Record",
            "x-is-trigger": False,
            "x-display-name": "Create Repository Record",
        },
        title="Create Repository Record",
    )
    collection: str = Field(
        ...,
        min_length=1,
        title="Collection",
        description="Collection name (e.g., app.bsky.feed.post)",
    )
    record: Dict[str, Any] = Field(
        ..., title="Record", description="Record data as JSON object"
    )
    rkey: Optional[str] = Field(
        None,
        title="Record Key",
        description="Optional record key (auto-generated if not provided)",
    )


class BlueSkyPutRecordConfig(BaseModel):
    """Create or update a record"""

    operation: Literal["create_or_update_record"] = Field(
        "create_or_update_record",
        json_schema_extra={
            "const": "create_or_update_record",
            "ui:hidden": True,
            "x-category": "Record",
            "x-is-trigger": False,
            "x-display-name": "Create or Update Record",
        },
        title="Create or Update Record",
    )
    collection: str = Field(..., min_length=1, title="Collection")
    rkey: str = Field(..., min_length=1, title="Record Key")
    record: Dict[str, Any] = Field(..., title="Record", description="Record data")
    swap_commit: Optional[str] = Field(
        None, title="Swap Commit", description="CID for optimistic concurrency"
    )


class BlueSkyDeleteRecordConfig(BaseModel):
    """Delete a record from the repository"""

    operation: Literal["delete_repository_record"] = Field(
        "delete_repository_record",
        json_schema_extra={
            "const": "delete_repository_record",
            "ui:hidden": True,
            "x-category": "Record",
            "x-is-trigger": False,
            "x-display-name": "Delete Repository Record",
        },
        title="Delete Repository Record",
    )
    collection: str = Field(..., min_length=1, title="Collection")
    rkey: str = Field(..., min_length=1, title="Record Key")
    swap_commit: Optional[str] = Field(
        None, title="Swap Commit", description="CID for optimistic concurrency"
    )


class BlueSkyGetRecordConfig(BaseModel):
    """Get a specific record"""

    operation: Literal["get_repository_record"] = Field(
        "get_repository_record",
        json_schema_extra={
            "const": "get_repository_record",
            "ui:hidden": True,
            "x-category": "Record",
            "x-is-trigger": False,
            "x-display-name": "Get Repository Record",
        },
        title="Get Repository Record",
    )
    repo: str = Field(
        ..., min_length=1, title="Repository", description="Repository DID or handle"
    )
    collection: str = Field(..., min_length=1, title="Collection")
    rkey: str = Field(..., min_length=1, title="Record Key")
    cid: Optional[str] = Field(None, title="CID", description="Specific version CID")


class BlueSkyListRecordsConfig(BaseModel):
    """List records in a collection"""

    operation: Literal["list_repository_records"] = Field(
        "list_repository_records",
        json_schema_extra={
            "const": "list_repository_records",
            "ui:hidden": True,
            "x-category": "Record",
            "x-is-trigger": False,
            "x-display-name": "List Repository Records",
        },
        title="List Repository Records",
    )
    repo: str = Field(
        ..., min_length=1, title="Repository", description="Repository DID or handle"
    )
    collection: str = Field(..., min_length=1, title="Collection")
    limit: int = Field(
        50, ge=1, le=100, title="Limit", description="Number of records (1-100)"
    )
    cursor: Optional[str] = Field(None, title="Cursor", description="Pagination cursor")


class BlueSkyUploadBlobConfig(BaseModel):
    """Upload a blob to the repository"""

    operation: Literal["upload_blob_to_repository"] = Field(
        "upload_blob_to_repository",
        json_schema_extra={
            "const": "upload_blob_to_repository",
            "ui:hidden": True,
            "x-category": "Blob",
            "x-is-trigger": False,
            "x-display-name": "Upload Blob to Repository",
        },
        title="Upload Blob to Repository",
    )
    blob_data: str = Field(
        ...,
        title="Blob",
        description="The blob to send — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}).",
        json_schema_extra={"ui:widget": "media_upload"},
    )
    mime_type: str = Field(..., title="MIME Type", description="MIME type of the blob")


class BlueSkyDescribeRepoConfig(BaseModel):
    """Get repository description and metadata"""

    operation: Literal["describe_repository"] = Field(
        "describe_repository",
        json_schema_extra={
            "const": "describe_repository",
            "ui:hidden": True,
            "x-category": "Repository",
            "x-is-trigger": False,
            "x-display-name": "Describe Repository",
        },
        title="Describe Repository",
    )
    repo: str = Field(
        ..., min_length=1, title="Repository", description="Repository DID or handle"
    )


class BlueSkyApplyWritesConfig(BaseModel):
    """Apply multiple write operations atomically"""

    operation: Literal["apply_writes_atomically"] = Field(
        "apply_writes_atomically",
        json_schema_extra={
            "const": "apply_writes_atomically",
            "ui:hidden": True,
            "x-category": "Record",
            "x-is-trigger": False,
            "x-display-name": "Apply Writes Atomically",
        },
        title="Apply Writes Atomically",
    )
    writes: List[Dict[str, Any]] = Field(
        ...,
        min_items=1,
        title="Writes",
        description="List of write operations (create, update, delete)",
    )
    swap_commit: Optional[str] = Field(
        None, title="Swap Commit", description="CID for optimistic concurrency"
    )


# ============================================================================
# Identity Operations (5 configs)
# ============================================================================


class BlueSkyResolveHandleConfig(BaseModel):
    """Resolve a handle to a DID"""

    operation: Literal["resolve_handle_to_did"] = Field(
        "resolve_handle_to_did",
        json_schema_extra={
            "const": "resolve_handle_to_did",
            "ui:hidden": True,
            "x-category": "Repository",
            "x-is-trigger": False,
            "x-display-name": "Resolve Handle to Did",
        },
        title="Resolve Handle to Did",
    )
    handle: str = Field(
        ...,
        min_length=1,
        title="Handle",
        description="Handle to resolve (e.g., user.bsky.social)",
    )


class BlueSkyResolveDidConfig(BaseModel):
    """Resolve a DID to get DID document"""

    operation: Literal["resolve_did_to_document"] = Field(
        "resolve_did_to_document",
        json_schema_extra={
            "const": "resolve_did_to_document",
            "ui:hidden": True,
            "x-category": "Repository",
            "x-is-trigger": False,
            "x-display-name": "Resolve Did to Document",
        },
        title="Resolve Did to Document",
    )
    did: str = Field(..., min_length=1, title="DID", description="DID to resolve")


class BlueSkyUpdateHandleConfig(BaseModel):
    """Update account handle"""

    operation: Literal["update_account_handle"] = Field(
        "update_account_handle",
        json_schema_extra={
            "const": "update_account_handle",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Update Account Handle",
        },
        title="Update Account Handle",
    )
    handle: str = Field(
        ..., min_length=1, title="New Handle", description="New handle for the account"
    )


class BlueSkyGetRecommendedDidCredentialsConfig(BaseModel):
    """Get recommended DID credential providers"""

    operation: Literal["get_recommended_did_credentials"] = Field(
        "get_recommended_did_credentials",
        json_schema_extra={
            "const": "get_recommended_did_credentials",
            "ui:hidden": True,
            "x-category": "Credentials",
            "x-is-trigger": False,
            "x-display-name": "Get Recommended Did Credentials",
        },
        title="Get Recommended Did Credentials",
    )


class BlueSkyResolveIdentityConfig(BaseModel):
    """Resolve complete identity (handle + DID)"""

    operation: Literal["resolve_complete_identity"] = Field(
        "resolve_complete_identity",
        json_schema_extra={
            "const": "resolve_complete_identity",
            "ui:hidden": True,
            "x-category": "Repository",
            "x-is-trigger": False,
            "x-display-name": "Resolve Complete Identity",
        },
        title="Resolve Complete Identity",
    )
    identifier: str = Field(
        ..., min_length=1, title="Identifier", description="Handle or DID to resolve"
    )


# ============================================================================
# Age Assurance Operations (3 configs)
# ============================================================================


class BlueSkyBeginAgeAssuranceConfig(BaseModel):
    """Start age assurance process"""

    operation: Literal["begin_age_assurance"] = Field(
        "begin_age_assurance",
        json_schema_extra={
            "const": "begin_age_assurance",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Begin Age Assurance",
        },
        title="Begin Age Assurance",
    )


class BlueSkyGetAgeAssuranceConfigConfig(BaseModel):
    """Retrieve age assurance configuration"""

    operation: Literal["get_age_assurance_config"] = Field(
        "get_age_assurance_config",
        json_schema_extra={
            "const": "get_age_assurance_config",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Get Age Assurance Config",
        },
        title="Get Age Assurance Config",
    )


class BlueSkyGetAgeAssuranceStateConfig(BaseModel):
    """Check age assurance status"""

    operation: Literal["get_age_assurance_state"] = Field(
        "get_age_assurance_state",
        json_schema_extra={
            "const": "get_age_assurance_state",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Get Age Assurance State",
        },
        title="Get Age Assurance State",
    )


# ============================================================================
# Additional Feed Operations (5 configs)
# ============================================================================


class BlueSkyDescribeFeedGeneratorConfig(BaseModel):
    """Get feed generator metadata"""

    operation: Literal["describe_feed_generator"] = Field(
        "describe_feed_generator",
        json_schema_extra={
            "const": "describe_feed_generator",
            "ui:hidden": True,
            "x-category": "Feed",
            "x-is-trigger": False,
            "x-display-name": "Describe Feed Generator",
        },
        title="Describe Feed Generator",
    )
    feed_uri: str = Field(
        ..., min_length=1, title="Feed URI", description="AT URI of the feed generator"
    )


class BlueSkyGetFeedGeneratorsConfig(BaseModel):
    """Get multiple feed generators"""

    operation: Literal["get_multiple_feed_generators"] = Field(
        "get_multiple_feed_generators",
        json_schema_extra={
            "const": "get_multiple_feed_generators",
            "ui:hidden": True,
            "x-category": "Feed",
            "x-is-trigger": False,
            "x-display-name": "Get Multiple Feed Generators",
        },
        title="Get Multiple Feed Generators",
    )
    feeds: List[str] = Field(
        ...,
        min_items=1,
        max_items=25,
        title="Feed URIs",
        description="List of feed URIs to retrieve (max 25)",
    )


class BlueSkyGetFeedSkeletonConfig(BaseModel):
    """Retrieve feed skeleton structure"""

    operation: Literal["get_feed_skeleton"] = Field(
        "get_feed_skeleton",
        json_schema_extra={
            "const": "get_feed_skeleton",
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Get Feed Skeleton",
        },
        title="Get Feed Skeleton",
    )
    feed_uri: str = Field(..., min_length=1, title="Feed URI")
    limit: int = Field(
        50, ge=1, le=100, title="Limit", description="Number of items (1-100)"
    )
    cursor: Optional[str] = Field(None, title="Cursor", description="Pagination cursor")


class BlueSkySendInteractionsConfig(BaseModel):
    """Report user interactions"""

    operation: Literal["send_user_interactions"] = Field(
        "send_user_interactions",
        json_schema_extra={
            "const": "send_user_interactions",
            "ui:hidden": True,
            "x-category": "Interactions",
            "x-is-trigger": False,
            "x-display-name": "Send User Interactions",
        },
        title="Send User Interactions",
    )
    interactions: List[Dict[str, Any]] = Field(
        ..., min_items=1, title="Interactions", description="List of interaction events"
    )


# ============================================================================
# Additional Graph Operations (10 configs)
# ============================================================================


class BlueSkyGetActorStarterPacksConfig(BaseModel):
    """Get starter packs created by user"""

    operation: Literal["list_actor_starter_packs"] = Field(
        "list_actor_starter_packs",
        json_schema_extra={
            "const": "list_actor_starter_packs",
            "ui:hidden": True,
            "x-category": "Starter Pack",
            "x-is-trigger": False,
            "x-display-name": "List Actor Starter Packs",
        },
        title="List Actor Starter Packs",
    )
    actor: str = Field(..., min_length=1, title="Actor Handle or DID")
    limit: int = Field(50, ge=1, le=100, title="Limit")
    cursor: Optional[str] = Field(None, title="Cursor")


class BlueSkyGetKnownFollowersConfig(BaseModel):
    """Get mutual followers"""

    operation: Literal["list_mutual_followers"] = Field(
        "list_mutual_followers",
        json_schema_extra={
            "const": "list_mutual_followers",
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "List Mutual Followers",
        },
        title="List Mutual Followers",
    )
    actor: str = Field(..., min_length=1, title="Actor Handle or DID")
    limit: int = Field(50, ge=1, le=100, title="Limit")
    cursor: Optional[str] = Field(None, title="Cursor")


class BlueSkyGetListBlocksConfig(BaseModel):
    """Get blocked lists"""

    operation: Literal["list_blocked_lists"] = Field(
        "list_blocked_lists",
        json_schema_extra={
            "const": "list_blocked_lists",
            "ui:hidden": True,
            "x-category": "List",
            "x-is-trigger": False,
            "x-display-name": "List Blocked Lists",
        },
        title="List Blocked Lists",
    )
    limit: int = Field(50, ge=1, le=100, title="Limit")
    cursor: Optional[str] = Field(None, title="Cursor")


class BlueSkyGetListMutesConfig(BaseModel):
    """Get muted lists"""

    operation: Literal["list_muted_lists"] = Field(
        "list_muted_lists",
        json_schema_extra={
            "const": "list_muted_lists",
            "ui:hidden": True,
            "x-category": "List",
            "x-is-trigger": False,
            "x-display-name": "List Muted Lists",
        },
        title="List Muted Lists",
    )
    limit: int = Field(50, ge=1, le=100, title="Limit")
    cursor: Optional[str] = Field(None, title="Cursor")


class BlueSkyGetListsWithMembershipConfig(BaseModel):
    """Get lists containing user"""

    operation: Literal["list_actor_membership_lists"] = Field(
        "list_actor_membership_lists",
        json_schema_extra={
            "const": "list_actor_membership_lists",
            "ui:hidden": True,
            "x-category": "List",
            "x-is-trigger": False,
            "x-display-name": "List Actor Membership Lists",
        },
        title="List Actor Membership Lists",
    )
    actor: str = Field(..., min_length=1, title="Actor Handle or DID")
    limit: int = Field(50, ge=1, le=100, title="Limit")
    cursor: Optional[str] = Field(None, title="Cursor")


class BlueSkyGetStarterPackConfig(BaseModel):
    """Get starter pack details"""

    operation: Literal["get_starter_pack"] = Field(
        "get_starter_pack",
        json_schema_extra={
            "const": "get_starter_pack",
            "ui:hidden": True,
            "x-category": "Starter Pack",
            "x-is-trigger": False,
            "x-display-name": "Get Starter Pack",
        },
        title="Get Starter Pack",
    )
    starter_pack_uri: str = Field(..., min_length=1, title="Starter Pack URI")


class BlueSkyGetStarterPacksWithMembershipConfig(BaseModel):
    """Get starter packs user belongs to"""

    operation: Literal["list_starter_packs_with_membership"] = Field(
        "list_starter_packs_with_membership",
        json_schema_extra={
            "const": "list_starter_packs_with_membership",
            "ui:hidden": True,
            "x-category": "Starter Pack",
            "x-is-trigger": False,
            "x-display-name": "List Starter Packs with Membership",
        },
        title="List Starter Packs with Membership",
    )
    actor: str = Field(..., min_length=1, title="Actor Handle or DID")
    limit: int = Field(50, ge=1, le=100, title="Limit")
    cursor: Optional[str] = Field(None, title="Cursor")


class BlueSkyGetStarterPacksConfig(BaseModel):
    """Get starter packs"""

    operation: Literal["get_multiple_starter_packs"] = Field(
        "get_multiple_starter_packs",
        json_schema_extra={
            "const": "get_multiple_starter_packs",
            "ui:hidden": True,
            "x-category": "Starter Pack",
            "x-is-trigger": False,
            "x-display-name": "Get Multiple Starter Packs",
        },
        title="Get Multiple Starter Packs",
    )
    uris: List[str] = Field(..., min_items=1, max_items=25, title="Starter Pack URIs")


class BlueSkyGetSuggestedFollowsByActorConfig(BaseModel):
    """Get follow suggestions"""

    operation: Literal["list_suggested_follows_by_actor"] = Field(
        "list_suggested_follows_by_actor",
        json_schema_extra={
            "const": "list_suggested_follows_by_actor",
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "List Suggested Follows by Actor",
        },
        title="List Suggested Follows by Actor",
    )
    actor: str = Field(..., min_length=1, title="Actor Handle or DID")


class BlueSkyMuteActorListConfig(BaseModel):
    """Mute entire list"""

    operation: Literal["mute_list"] = Field(
        "mute_list",
        json_schema_extra={
            "const": "mute_list",
            "ui:hidden": True,
            "x-category": "List",
            "x-is-trigger": False,
            "x-display-name": "Mute List",
        },
        title="Mute List",
    )
    list_uri: str = Field(..., min_length=1, title="List URI")


class BlueSkyUnmuteActorListConfig(BaseModel):
    """Unmute list"""

    operation: Literal["unmute_list"] = Field(
        "unmute_list",
        json_schema_extra={
            "const": "unmute_list",
            "ui:hidden": True,
            "x-category": "List",
            "x-is-trigger": False,
            "x-display-name": "Unmute List",
        },
        title="Unmute List",
    )
    list_uri: str = Field(..., min_length=1, title="List URI")


class BlueSkySearchStarterPacksConfig(BaseModel):
    """Search starter packs"""

    operation: Literal["search_starter_packs"] = Field(
        "search_starter_packs",
        json_schema_extra={
            "const": "search_starter_packs",
            "ui:hidden": True,
            "x-category": "Starter Pack",
            "x-is-trigger": False,
            "x-display-name": "Search Starter Packs",
        },
        title="Search Starter Packs",
    )
    query: str = Field(..., min_length=1, title="Search Query")
    limit: int = Field(25, ge=1, le=100, title="Limit")
    cursor: Optional[str] = Field(None, title="Cursor")


# ============================================================================
# Labeler Operations (1 config)
# ============================================================================


class BlueSkyGetLabelerServicesConfig(BaseModel):
    """Retrieve labeling services"""

    operation: Literal["get_labeler_services"] = Field(
        "get_labeler_services",
        json_schema_extra={
            "const": "get_labeler_services",
            "ui:hidden": True,
            "x-category": "Labeler",
            "x-is-trigger": False,
            "x-display-name": "Get Labeler Services",
        },
        title="Get Labeler Services",
    )
    dids: List[str] = Field(
        ...,
        min_items=1,
        max_items=25,
        title="Service DIDs",
        description="List of labeler service DIDs (max 25)",
    )


# ============================================================================
# Additional Chat Operations (6 configs)
# ============================================================================


class BlueSkyRemoveMessageReactionConfig(BaseModel):
    """Remove message reaction"""

    operation: Literal["remove_reaction_from_message"] = Field(
        "remove_reaction_from_message",
        json_schema_extra={
            "const": "remove_reaction_from_message",
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Remove Reaction from Message",
        },
        title="Remove Reaction from Message",
    )
    convo_id: str = Field(..., min_length=1, title="Conversation ID")
    message_id: str = Field(..., min_length=1, title="Message ID")
    reaction: str = Field(..., min_length=1, title="Reaction")


class BlueSkySendMessageBatchConfig(BaseModel):
    """Send multiple messages"""

    operation: Literal["send_message_batch"] = Field(
        "send_message_batch",
        json_schema_extra={
            "const": "send_message_batch",
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Send Message Batch",
        },
        title="Send Message Batch",
    )
    messages: List[Dict[str, Any]] = Field(
        ...,
        min_items=1,
        max_items=100,
        title="Messages",
        description="Batch of messages to send (max 100)",
    )


class BlueSkyGetConversationLogConfig(BaseModel):
    """Get conversation event log"""

    operation: Literal["get_conversation_event_log"] = Field(
        "get_conversation_event_log",
        json_schema_extra={
            "const": "get_conversation_event_log",
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Get Conversation Event Log",
        },
        title="Get Conversation Event Log",
    )
    cursor: Optional[str] = Field(None, title="Cursor")


class BlueSkyGetConvoAvailabilityConfig(BaseModel):
    """Check if conversation possible"""

    operation: Literal["check_conversation_availability"] = Field(
        "check_conversation_availability",
        json_schema_extra={
            "const": "check_conversation_availability",
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Check Conversation Availability",
        },
        title="Check Conversation Availability",
    )
    actor: str = Field(..., min_length=1, title="Actor Handle or DID")


class BlueSkyUpdateAllReadConfig(BaseModel):
    """Mark all messages read"""

    operation: Literal["mark_all_messages_read"] = Field(
        "mark_all_messages_read",
        json_schema_extra={
            "const": "mark_all_messages_read",
            "ui:hidden": True,
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Mark All Messages Read",
        },
        title="Mark All Messages Read",
    )


class BlueSkyDeleteChatAccountConfig(BaseModel):
    """Delete chat account"""

    operation: Literal["delete_chat_account"] = Field(
        "delete_chat_account",
        json_schema_extra={
            "const": "delete_chat_account",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Delete Chat Account",
        },
        title="Delete Chat Account",
    )


# ============================================================================
# Server Operations (26 configs)
# ============================================================================


class BlueSkyActivateAccountConfig(BaseModel):
    """Reactivate deactivated account"""

    operation: Literal["activate_account"] = Field(
        "activate_account",
        json_schema_extra={
            "const": "activate_account",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Activate Account",
        },
        title="Activate Account",
    )


class BlueSkyCheckAccountStatusConfig(BaseModel):
    """Verify account status"""

    operation: Literal["check_account_status"] = Field(
        "check_account_status",
        json_schema_extra={
            "const": "check_account_status",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Check Account Status",
        },
        title="Check Account Status",
    )


class BlueSkyConfirmEmailConfig(BaseModel):
    """Confirm email address"""

    operation: Literal["confirm_email"] = Field(
        "confirm_email",
        json_schema_extra={
            "const": "confirm_email",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Confirm Email",
        },
        title="Confirm Email",
    )
    token: str = Field(..., min_length=1, title="Confirmation Token")
    email: str = Field(..., min_length=1, title="Email Address")


class BlueSkyCreateAppPasswordConfig(BaseModel):
    """Generate application password"""

    operation: Literal["create_app_password"] = Field(
        "create_app_password",
        json_schema_extra={
            "const": "create_app_password",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Create App Password",
        },
        title="Create App Password",
    )
    name: str = Field(..., min_length=1, title="App Password Name")


class BlueSkyCreateInviteCodeConfig(BaseModel):
    """Generate invite code"""

    operation: Literal["create_invite_code"] = Field(
        "create_invite_code",
        json_schema_extra={
            "const": "create_invite_code",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Create Invite Code",
        },
        title="Create Invite Code",
    )
    use_count: int = Field(1, ge=1, title="Number of Uses")


class BlueSkyCreateInviteCodesConfig(BaseModel):
    """Generate multiple invite codes"""

    operation: Literal["create_multiple_invite_codes"] = Field(
        "create_multiple_invite_codes",
        json_schema_extra={
            "const": "create_multiple_invite_codes",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Create Multiple Invite Codes",
        },
        title="Create Multiple Invite Codes",
    )
    code_count: int = Field(..., ge=1, le=100, title="Number of Codes")
    use_count: int = Field(1, ge=1, title="Uses Per Code")


class BlueSkyDeactivateAccountConfig(BaseModel):
    """Temporarily disable account"""

    operation: Literal["deactivate_account"] = Field(
        "deactivate_account",
        json_schema_extra={
            "const": "deactivate_account",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Deactivate Account",
        },
        title="Deactivate Account",
    )


class BlueSkyDeleteAccountConfig(BaseModel):
    """Permanently remove account"""

    operation: Literal["delete_account"] = Field(
        "delete_account",
        json_schema_extra={
            "const": "delete_account",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Delete Account",
        },
        title="Delete Account",
    )
    password: str = Field(
        ...,
        min_length=1,
        title="Account Password",
        json_schema_extra={"ui:widget": "password"},
    )
    token: str = Field(..., min_length=1, title="Deletion Token")


class BlueSkyDeleteSessionConfig(BaseModel):
    """Logout/end session"""

    operation: Literal["delete_session_logout"] = Field(
        "delete_session_logout",
        json_schema_extra={
            "const": "delete_session_logout",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Delete Session Logout",
        },
        title="Delete Session Logout",
    )


class BlueSkyDescribeServerConfig(BaseModel):
    """Get server information"""

    operation: Literal["describe_server"] = Field(
        "describe_server",
        json_schema_extra={
            "const": "describe_server",
            "ui:hidden": True,
            "x-category": "Server",
            "x-is-trigger": False,
            "x-display-name": "Describe Server",
        },
        title="Describe Server",
    )


class BlueSkyGetAccountInviteCodesConfig(BaseModel):
    """Retrieve generated codes"""

    operation: Literal["list_account_invite_codes"] = Field(
        "list_account_invite_codes",
        json_schema_extra={
            "const": "list_account_invite_codes",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "List Account Invite Codes",
        },
        title="List Account Invite Codes",
    )


class BlueSkyGetServiceAuthConfig(BaseModel):
    """Get service authentication"""

    operation: Literal["get_service_auth_token"] = Field(
        "get_service_auth_token",
        json_schema_extra={
            "const": "get_service_auth_token",
            "ui:hidden": True,
            "x-category": "Service Auth",
            "x-is-trigger": False,
            "x-display-name": "Get Service Auth Token",
        },
        title="Get Service Auth Token",
    )
    aud: str = Field(..., min_length=1, title="Audience DID")


class BlueSkyGetSessionConfig(BaseModel):
    """Verify active session"""

    operation: Literal["get_active_session"] = Field(
        "get_active_session",
        json_schema_extra={
            "const": "get_active_session",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Get Active Session",
        },
        title="Get Active Session",
    )


class BlueSkyListAppPasswordsConfig(BaseModel):
    """List application passwords"""

    operation: Literal["list_app_passwords"] = Field(
        "list_app_passwords",
        json_schema_extra={
            "const": "list_app_passwords",
            "ui:hidden": True,
            "x-category": "App Password",
            "x-is-trigger": False,
            "x-display-name": "List App Passwords",
        },
        title="List App Passwords",
    )


class BlueSkyRefreshSessionConfig(BaseModel):
    """Refresh session credentials"""

    operation: Literal["refresh_session"] = Field(
        "refresh_session",
        json_schema_extra={
            "const": "refresh_session",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Refresh Session",
        },
        title="Refresh Session",
    )


class BlueSkyRequestAccountDeleteConfig(BaseModel):
    """Initiate account deletion"""

    operation: Literal["request_account_deletion"] = Field(
        "request_account_deletion",
        json_schema_extra={
            "const": "request_account_deletion",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Request Account Deletion",
        },
        title="Request Account Deletion",
    )


class BlueSkyRequestEmailConfirmationConfig(BaseModel):
    """Request verification email"""

    operation: Literal["request_email_confirmation"] = Field(
        "request_email_confirmation",
        json_schema_extra={
            "const": "request_email_confirmation",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Request Email Confirmation",
        },
        title="Request Email Confirmation",
    )


class BlueSkyRequestEmailUpdateConfig(BaseModel):
    """Request email change"""

    operation: Literal["request_email_update"] = Field(
        "request_email_update",
        json_schema_extra={
            "const": "request_email_update",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Request Email Update",
        },
        title="Request Email Update",
    )
    email: str = Field(..., min_length=1, title="New Email Address")


class BlueSkyRequestPasswordResetConfig(BaseModel):
    """Initiate password reset"""

    operation: Literal["request_password_reset"] = Field(
        "request_password_reset",
        json_schema_extra={
            "const": "request_password_reset",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Request Password Reset",
        },
        title="Request Password Reset",
    )
    email: str = Field(..., min_length=1, title="Email Address")


class BlueSkyReserveSigningKeyConfig(BaseModel):
    """Reserve signing key"""

    operation: Literal["reserve_signing_key"] = Field(
        "reserve_signing_key",
        json_schema_extra={
            "const": "reserve_signing_key",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Reserve Signing Key",
        },
        title="Reserve Signing Key",
    )
    did: Optional[str] = Field(None, title="DID")


class BlueSkyResetPasswordConfig(BaseModel):
    """Complete password reset"""

    operation: Literal["reset_password"] = Field(
        "reset_password",
        json_schema_extra={
            "const": "reset_password",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Reset Password",
        },
        title="Reset Password",
    )
    token: str = Field(..., min_length=1, title="Reset Token")
    password: str = Field(
        ...,
        min_length=8,
        title="New Password",
        json_schema_extra={"ui:widget": "password"},
    )


class BlueSkyRevokeAppPasswordConfig(BaseModel):
    """Remove application password"""

    operation: Literal["revoke_app_password"] = Field(
        "revoke_app_password",
        json_schema_extra={
            "const": "revoke_app_password",
            "ui:hidden": True,
            "x-category": "App Password",
            "x-is-trigger": False,
            "x-display-name": "Revoke App Password",
        },
        title="Revoke App Password",
    )
    name: str = Field(..., min_length=1, title="App Password Name")


class BlueSkyUpdateEmailConfig(BaseModel):
    """Update account email"""

    operation: Literal["update_account_email"] = Field(
        "update_account_email",
        json_schema_extra={
            "const": "update_account_email",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Update Account Email",
        },
        title="Update Account Email",
    )
    email: str = Field(..., min_length=1, title="New Email")
    token: str = Field(..., min_length=1, title="Verification Token")


# ============================================================================
# Label & Moderation Operations (2 configs)
# ============================================================================


class BlueSkyQueryLabelsConfig(BaseModel):
    """Query content labels"""

    operation: Literal["query_content_labels"] = Field(
        "query_content_labels",
        json_schema_extra={
            "const": "query_content_labels",
            "ui:hidden": True,
            "x-category": "Labeler",
            "x-is-trigger": False,
            "x-display-name": "Query Content Labels",
        },
        title="Query Content Labels",
    )
    uri_patterns: List[str] = Field(..., min_items=1, title="URI Patterns")
    sources: Optional[List[str]] = Field(None, title="Label Sources")
    limit: int = Field(50, ge=1, le=100, title="Limit")
    cursor: Optional[str] = Field(None, title="Cursor")


class BlueSkyCreateModerationReportConfig(BaseModel):
    """Submit moderation report"""

    operation: Literal["create_moderation_report"] = Field(
        "create_moderation_report",
        json_schema_extra={
            "const": "create_moderation_report",
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Create Moderation Report",
        },
        title="Create Moderation Report",
    )
    reason_type: str = Field(..., title="Reason Type")
    subject: Dict[str, Any] = Field(
        ..., title="Subject", description="Subject being reported"
    )
    reason: Optional[str] = Field(
        None, title="Reason", description="Additional context"
    )


# ============================================================================
# Discriminated Union of All Configs (149 operations)
# ============================================================================

BlueSkyConfig = Annotated[
    Union[
        # Post Operations (12)
        BlueSkyCreatePostConfig,
        BlueSkyDeletePostConfig,
        BlueSkyGetPostThreadConfig,
        BlueSkyGetPostsConfig,
        BlueSkyLikePostConfig,
        BlueSkyUnlikePostConfig,
        BlueSkyRepostConfig,
        BlueSkyUnrepostConfig,
        BlueSkyGetLikesConfig,
        BlueSkyGetRepostedByConfig,
        BlueSkyGetQuotesConfig,
        BlueSkySearchPostsConfig,
        # Feed Operations (8)
        BlueSkyGetTimelineConfig,
        BlueSkyGetAuthorFeedConfig,
        BlueSkyGetActorLikesConfig,
        BlueSkyGetFeedGeneratorConfig,
        BlueSkyGetActorFeedsConfig,
        BlueSkyGetSuggestedFeedsConfig,
        BlueSkyGetListFeedConfig,
        BlueSkyGetFeedConfig,
        # Actor/Profile Operations (7)
        BlueSkyGetProfileConfig,
        BlueSkyGetProfilesConfig,
        BlueSkySearchActorsConfig,
        BlueSkySearchActorsTypeaheadConfig,
        BlueSkyGetSuggestionsConfig,
        BlueSkyGetPreferencesConfig,
        BlueSkyPutPreferencesConfig,
        # Graph/Social Operations (15)
        BlueSkyFollowUserConfig,
        BlueSkyUnfollowUserConfig,
        BlueSkyGetFollowersConfig,
        BlueSkyGetFollowsConfig,
        BlueSkyBlockUserConfig,
        BlueSkyUnblockUserConfig,
        BlueSkyGetBlocksConfig,
        BlueSkyMuteActorConfig,
        BlueSkyUnmuteActorConfig,
        BlueSkyGetMutesConfig,
        BlueSkyMuteThreadConfig,
        BlueSkyUnmuteThreadConfig,
        BlueSkyGetListConfig,
        BlueSkyGetListsConfig,
        BlueSkyGetRelationshipsConfig,
        # Bookmark Operations (3)
        BlueSkyCreateBookmarkConfig,
        BlueSkyDeleteBookmarkConfig,
        BlueSkyGetBookmarksConfig,
        # Notification Operations (8)
        BlueSkyListNotificationsConfig,
        BlueSkyGetUnreadCountConfig,
        BlueSkyUpdateSeenConfig,
        BlueSkyRegisterPushConfig,
        BlueSkyUnregisterPushConfig,
        BlueSkyGetNotificationPreferencesConfig,
        BlueSkyPutNotificationPreferencesConfig,
        BlueSkyListActivitySubscriptionsConfig,
        # Chat Operations (12)
        BlueSkyListConversationsConfig,
        BlueSkyGetConversationConfig,
        BlueSkyGetConversationForMembersConfig,
        BlueSkyGetMessagesConfig,
        BlueSkySendMessageConfig,
        BlueSkyDeleteMessageConfig,
        BlueSkyLeaveConversationConfig,
        BlueSkyMuteConversationConfig,
        BlueSkyUnmuteConversationConfig,
        BlueSkyUpdateConversationReadConfig,
        BlueSkyAcceptConversationConfig,
        BlueSkyAddMessageReactionConfig,
        # Video Operations (3)
        BlueSkyUploadVideoConfig,
        BlueSkyGetVideoJobStatusConfig,
        BlueSkyGetUploadLimitsConfig,
        # Repository Operations (8)
        BlueSkyCreateRecordConfig,
        BlueSkyPutRecordConfig,
        BlueSkyDeleteRecordConfig,
        BlueSkyGetRecordConfig,
        BlueSkyListRecordsConfig,
        BlueSkyUploadBlobConfig,
        BlueSkyDescribeRepoConfig,
        BlueSkyApplyWritesConfig,
        # Identity Operations (5)
        BlueSkyResolveHandleConfig,
        BlueSkyResolveDidConfig,
        BlueSkyUpdateHandleConfig,
        BlueSkyGetRecommendedDidCredentialsConfig,
        BlueSkyResolveIdentityConfig,
        # Age Assurance Operations (3)
        BlueSkyBeginAgeAssuranceConfig,
        BlueSkyGetAgeAssuranceConfigConfig,
        BlueSkyGetAgeAssuranceStateConfig,
        # Additional Feed Operations (4)
        BlueSkyDescribeFeedGeneratorConfig,
        BlueSkyGetFeedGeneratorsConfig,
        BlueSkyGetFeedSkeletonConfig,
        BlueSkySendInteractionsConfig,
        # Additional Graph Operations (13)
        BlueSkyGetActorStarterPacksConfig,
        BlueSkyGetKnownFollowersConfig,
        BlueSkyGetListBlocksConfig,
        BlueSkyGetListMutesConfig,
        BlueSkyGetListsWithMembershipConfig,
        BlueSkyGetStarterPackConfig,
        BlueSkyGetStarterPacksWithMembershipConfig,
        BlueSkyGetStarterPacksConfig,
        BlueSkyGetSuggestedFollowsByActorConfig,
        BlueSkyMuteActorListConfig,
        BlueSkyUnmuteActorListConfig,
        BlueSkySearchStarterPacksConfig,
        # Labeler Operations (1)
        BlueSkyGetLabelerServicesConfig,
        # Additional Chat Operations (6)
        BlueSkyRemoveMessageReactionConfig,
        BlueSkySendMessageBatchConfig,
        BlueSkyGetConversationLogConfig,
        BlueSkyGetConvoAvailabilityConfig,
        BlueSkyUpdateAllReadConfig,
        BlueSkyDeleteChatAccountConfig,
        # Server Operations (25)
        BlueSkyActivateAccountConfig,
        BlueSkyCheckAccountStatusConfig,
        BlueSkyConfirmEmailConfig,
        BlueSkyCreateAppPasswordConfig,
        BlueSkyCreateInviteCodeConfig,
        BlueSkyCreateInviteCodesConfig,
        BlueSkyDeactivateAccountConfig,
        BlueSkyDeleteAccountConfig,
        BlueSkyDeleteSessionConfig,
        BlueSkyDescribeServerConfig,
        BlueSkyGetAccountInviteCodesConfig,
        BlueSkyGetServiceAuthConfig,
        BlueSkyGetSessionConfig,
        BlueSkyListAppPasswordsConfig,
        BlueSkyRefreshSessionConfig,
        BlueSkyRequestAccountDeleteConfig,
        BlueSkyRequestEmailConfirmationConfig,
        BlueSkyRequestEmailUpdateConfig,
        BlueSkyRequestPasswordResetConfig,
        BlueSkyReserveSigningKeyConfig,
        BlueSkyResetPasswordConfig,
        BlueSkyRevokeAppPasswordConfig,
        BlueSkyUpdateEmailConfig,
        # Label & Moderation Operations (2)
        BlueSkyQueryLabelsConfig,
        BlueSkyCreateModerationReportConfig,
    ],
    Discriminator("operation"),
]


class BlueSkyNodeConfig(NodeConfig[BlueSkyConfig, BlueSkyCredential]):
    """Full configuration for BlueSky node including credentials"""

    pass


# ============================================================================
# BlueSky Node Implementation
# ============================================================================


class BlueSkyNode(WorkflowNode):
    """
    BlueSky (AT Protocol) automation node.

    Comprehensive integration supporting 149 operations across:
    - Posts: Create, delete, like, repost, search, quotes
    - Feeds: Timeline, author feed, custom feeds, lists
    - Profiles: Get profiles, search actors, preferences
    - Social Graph: Follow, block, mute, relationships
    - Bookmarks: Save and manage bookmarks
    - Notifications: List, read, push registration
    - Chat: Conversations and direct messages
    - Video: Upload and processing
    - Repository: Low-level record operations
    - Identity: Handle and DID resolution

    API Docs: https://docs.bsky.app/docs/api/at-protocol-xrpc-api
    """

    edit_examples = [
        "Create a post with an image and tag @user123 in the text",
        'Search for posts about "climate" with engagement filter',
        'Follow a user and add them to "Interesting People" list',
        "Like and repost a post by @alice in one workflow",
        "Get notifications and mark conversations as read",
        "Mute a thread and send a direct message about the topic",
        "Block a user and report for harassment with description",
    ]

    @classmethod
    def get_config_model(cls) -> Optional[Union[Type, type]]:
        """Get Pydantic config model for BlueSky node"""
        return BlueSkyNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute BlueSky automation.

        Args:
            inputs: Output data from upstream nodes

        Returns:
            Dict containing BlueSky operation results
        """
        logger.info(f"[BlueSkyNode] Executing node {self.node_id}")
        start_time = time.time()

        # Get config - required for this node
        node_config = self.config
        if not node_config:
            raise ValueError(
                f"[BlueSkyNode] Configuration is required but not provided for node {self.node_id}"
            )

        if not isinstance(node_config, BlueSkyNodeConfig):
            raise ValueError(
                f"[BlueSkyNode] Invalid config type: {type(node_config)}, expected BlueSkyNodeConfig"
            )

        # Extract the actual config and credentials
        config = node_config.config
        credentials = node_config.credentials
        action = config.operation

        # Operations that don't require authentication
        unauthenticated_operations = ["describe_server"]

        # For unauthenticated operations, skip session creation
        if action in unauthenticated_operations:
            access_token = None
            did = None
        else:
            # Require credentials for authenticated operations
            if not credentials:
                raise ValueError(
                    "[BlueSkyNode] BlueSky credentials are required. "
                    "Please add your BlueSky App Password in the credentials tab."
                )

            # Create authenticated session
            session = await self._create_session(credentials)
            access_token = session["accessJwt"]
            did = session["did"]

        # Route to appropriate handler based on action type

        # Post Operations
        if action == "create_post":
            output = await self._create_post(config, access_token, did)
        elif action == "delete_post":
            output = await self._delete_post(config, access_token)
        elif action == "get_post_thread":
            output = await self._get_post_thread(config, access_token)
        elif action == "get_posts_by_uris":
            output = await self._get_posts(config, access_token)
        elif action == "like_post":
            output = await self._like_post(config, access_token, did)
        elif action == "unlike_post":
            output = await self._unlike_post(config, access_token, did)
        elif action == "repost_post":
            output = await self._repost(config, access_token, did)
        elif action == "remove_repost":
            output = await self._unrepost(config, access_token, did)
        elif action == "list_post_likers":
            output = await self._get_likes(config, access_token)
        elif action == "list_post_reposters":
            output = await self._get_reposted_by(config, access_token)
        elif action == "list_post_quotes":
            output = await self._get_quotes(config, access_token)
        elif action == "search_posts":
            output = await self._search_posts(config, access_token)

        # Feed Operations
        elif action == "get_home_timeline":
            output = await self._get_timeline(config, access_token)
        elif action == "get_author_feed":
            output = await self._get_author_feed(config, access_token)
        elif action == "list_actor_liked_posts":
            output = await self._get_actor_likes(config, access_token)
        elif action == "get_feed_generator":
            output = await self._get_feed_generator(config, access_token)
        elif action == "list_actor_feed_generators":
            output = await self._get_actor_feeds(config, access_token)
        elif action == "list_suggested_feeds":
            output = await self._get_suggested_feeds(config, access_token)
        elif action == "get_list_member_feed":
            output = await self._get_list_feed(config, access_token)
        elif action == "get_custom_feed_posts":
            output = await self._get_feed(config, access_token)

        # Actor/Profile Operations
        elif action == "get_user_profile":
            output = await self._get_profile(config, access_token)
        elif action == "get_multiple_user_profiles":
            output = await self._get_profiles(config, access_token)
        elif action == "search_actors":
            output = await self._search_actors(config, access_token)
        elif action == "search_actors_typeahead":
            output = await self._search_actors_typeahead(config, access_token)
        elif action == "list_suggested_accounts":
            output = await self._get_suggestions(config, access_token)
        elif action == "get_user_preferences":
            output = await self._get_preferences(config, access_token)
        elif action == "update_user_preferences":
            output = await self._put_preferences(config, access_token)

        # Graph/Social Operations
        elif action == "follow_user":
            output = await self._follow_user(config, access_token, did)
        elif action == "unfollow_user":
            output = await self._unfollow_user(config, access_token)
        elif action == "list_actor_followers":
            output = await self._get_followers(config, access_token)
        elif action == "list_actor_follows":
            output = await self._get_follows(config, access_token)
        elif action == "block_user":
            output = await self._block_user(config, access_token, did)
        elif action == "unblock_user":
            output = await self._unblock_user(config, access_token)
        elif action == "list_blocked_accounts":
            output = await self._get_blocks(config, access_token)
        elif action == "mute_actor":
            output = await self._mute_actor(config, access_token)
        elif action == "unmute_actor":
            output = await self._unmute_actor(config, access_token)
        elif action == "list_muted_accounts":
            output = await self._get_mutes(config, access_token)
        elif action == "mute_thread":
            output = await self._mute_thread(config, access_token)
        elif action == "unmute_thread":
            output = await self._unmute_thread(config, access_token)
        elif action == "get_list_with_members":
            output = await self._get_list(config, access_token)
        elif action == "list_actor_lists":
            output = await self._get_lists(config, access_token)
        elif action == "get_actor_relationships":
            output = await self._get_relationships(config, access_token)

        # Bookmark Operations
        elif action == "create_post_bookmark":
            output = await self._create_bookmark(config, access_token, did)
        elif action == "delete_post_bookmark":
            output = await self._delete_bookmark(config, access_token, did)
        elif action == "list_bookmarks":
            output = await self._get_bookmarks(config, access_token)

        # Notification Operations
        elif action == "list_notifications":
            output = await self._list_notifications(config, access_token)
        elif action == "get_unread_notification_count":
            output = await self._get_unread_count(config, access_token)
        elif action == "mark_notifications_as_seen":
            output = await self._update_seen(config, access_token)
        elif action == "register_push_notifications":
            output = await self._register_push(config, access_token)
        elif action == "unregister_push_notifications":
            output = await self._unregister_push(config, access_token)
        elif action == "get_notification_preferences":
            output = await self._get_notification_preferences(config, access_token)
        elif action == "update_notification_preferences":
            output = await self._put_notification_preferences(config, access_token)
        elif action == "list_activity_subscriptions":
            output = await self._list_activity_subscriptions(config, access_token)

        # Chat Operations
        elif action == "list_user_conversations":
            output = await self._list_conversations(config, access_token)
        elif action == "get_conversation":
            output = await self._get_conversation(config, access_token)
        elif action == "get_conversation_with_members":
            output = await self._get_conversation_for_members(config, access_token)
        elif action == "list_conversation_messages":
            output = await self._get_messages(config, access_token)
        elif action == "send_message_in_conversation":
            output = await self._send_message(config, access_token)
        elif action == "delete_message_for_self":
            output = await self._delete_message(config, access_token)
        elif action == "leave_conversation":
            output = await self._leave_conversation(config, access_token)
        elif action == "mute_conversation":
            output = await self._mute_conversation(config, access_token)
        elif action == "unmute_conversation":
            output = await self._unmute_conversation(config, access_token)
        elif action == "mark_conversation_read":
            output = await self._update_conversation_read(config, access_token)
        elif action == "accept_conversation_request":
            output = await self._accept_conversation(config, access_token)
        elif action == "add_reaction_to_message":
            output = await self._add_message_reaction(config, access_token)

        # Video Operations
        elif action == "upload_video":
            output = await self._upload_video(config, access_token)
        elif action == "get_video_job_status":
            output = await self._get_video_job_status(config, access_token)
        elif action == "get_video_upload_limits":
            output = await self._get_upload_limits(config, access_token)

        # Repository Operations
        elif action == "create_repository_record":
            output = await self._create_record(config, access_token, did)
        elif action == "create_or_update_record":
            output = await self._put_record(config, access_token, did)
        elif action == "delete_repository_record":
            output = await self._delete_record(config, access_token, did)
        elif action == "get_repository_record":
            output = await self._get_record(config, access_token)
        elif action == "list_repository_records":
            output = await self._list_records(config, access_token)
        elif action == "upload_blob_to_repository":
            output = await self._upload_blob(config, access_token)
        elif action == "describe_repository":
            output = await self._describe_repo(config, access_token)
        elif action == "apply_writes_atomically":
            output = await self._apply_writes(config, access_token, did)

        # Identity Operations
        elif action == "resolve_handle_to_did":
            output = await self._resolve_handle(config, access_token)
        elif action == "resolve_did_to_document":
            output = await self._resolve_did(config, access_token)
        elif action == "update_account_handle":
            output = await self._update_handle(config, access_token)
        elif action == "get_recommended_did_credentials":
            output = await self._get_recommended_did_credentials(config, access_token)
        elif action == "resolve_complete_identity":
            output = await self._resolve_identity(config, access_token)

        # Age Assurance Operations
        elif action == "begin_age_assurance":
            output = await self._begin_age_assurance(config, access_token)
        elif action == "get_age_assurance_config":
            output = await self._get_age_assurance_config(config, access_token)
        elif action == "get_age_assurance_state":
            output = await self._get_age_assurance_state(config, access_token)

        # Additional Feed Operations
        elif action == "describe_feed_generator":
            output = await self._describe_feed_generator(config, access_token)
        elif action == "get_multiple_feed_generators":
            output = await self._get_feed_generators(config, access_token)
        elif action == "get_feed_skeleton":
            output = await self._get_feed_skeleton(config, access_token)
        elif action == "send_user_interactions":
            output = await self._send_interactions(config, access_token)

        # Additional Graph Operations
        elif action == "list_actor_starter_packs":
            output = await self._get_actor_starter_packs(config, access_token)
        elif action == "list_mutual_followers":
            output = await self._get_known_followers(config, access_token)
        elif action == "list_blocked_lists":
            output = await self._get_list_blocks(config, access_token)
        elif action == "list_muted_lists":
            output = await self._get_list_mutes(config, access_token)
        elif action == "list_actor_membership_lists":
            output = await self._get_lists_with_membership(config, access_token)
        elif action == "get_starter_pack":
            output = await self._get_starter_pack(config, access_token)
        elif action == "list_starter_packs_with_membership":
            output = await self._get_starter_packs_with_membership(config, access_token)
        elif action == "get_multiple_starter_packs":
            output = await self._get_starter_packs(config, access_token)
        elif action == "list_suggested_follows_by_actor":
            output = await self._get_suggested_follows_by_actor(config, access_token)
        elif action == "mute_list":
            output = await self._mute_actor_list(config, access_token)
        elif action == "unmute_list":
            output = await self._unmute_actor_list(config, access_token)
        elif action == "search_starter_packs":
            output = await self._search_starter_packs(config, access_token)

        # Labeler Operations
        elif action == "get_labeler_services":
            output = await self._get_labeler_services(config, access_token)

        # Additional Chat Operations
        elif action == "remove_reaction_from_message":
            output = await self._remove_message_reaction(config, access_token)
        elif action == "send_message_batch":
            output = await self._send_message_batch(config, access_token)
        elif action == "get_conversation_event_log":
            output = await self._get_conversation_log(config, access_token)
        elif action == "check_conversation_availability":
            output = await self._get_convo_availability(config, access_token)
        elif action == "mark_all_messages_read":
            output = await self._update_all_read(config, access_token)
        elif action == "delete_chat_account":
            output = await self._delete_chat_account(config, access_token)

        # Server Operations
        elif action == "activate_account":
            output = await self._activate_account(config, access_token)
        elif action == "check_account_status":
            output = await self._check_account_status(config, access_token)
        elif action == "confirm_email":
            output = await self._confirm_email(config, access_token)
        elif action == "create_app_password":
            output = await self._create_app_password(config, access_token)
        elif action == "create_invite_code":
            output = await self._create_invite_code(config, access_token)
        elif action == "create_multiple_invite_codes":
            output = await self._create_invite_codes(config, access_token)
        elif action == "deactivate_account":
            output = await self._deactivate_account(config, access_token)
        elif action == "delete_account":
            output = await self._delete_account(config, access_token)
        elif action == "delete_session_logout":
            output = await self._delete_session(config, access_token)
        elif action == "describe_server":
            output = await self._describe_server(config)
        elif action == "list_account_invite_codes":
            output = await self._get_account_invite_codes(config, access_token)
        elif action == "get_service_auth_token":
            output = await self._get_service_auth(config, access_token)
        elif action == "get_active_session":
            output = await self._get_session(config, access_token)
        elif action == "list_app_passwords":
            output = await self._list_app_passwords(config, access_token)
        elif action == "refresh_session":
            output = await self._refresh_session(config, access_token)
        elif action == "request_account_deletion":
            output = await self._request_account_delete(config, access_token)
        elif action == "request_email_confirmation":
            output = await self._request_email_confirmation(config, access_token)
        elif action == "request_email_update":
            output = await self._request_email_update(config, access_token)
        elif action == "request_password_reset":
            output = await self._request_password_reset(config, access_token)
        elif action == "reserve_signing_key":
            output = await self._reserve_signing_key(config, access_token)
        elif action == "reset_password":
            output = await self._reset_password(config, access_token)
        elif action == "revoke_app_password":
            output = await self._revoke_app_password(config, access_token)
        elif action == "update_account_email":
            output = await self._update_email(config, access_token)

        # Label & Moderation Operations
        elif action == "query_content_labels":
            output = await self._query_labels(config, access_token)
        elif action == "create_moderation_report":
            output = await self._create_moderation_report(config, access_token)

        else:
            raise ValueError(f"Unknown action: {action}")

        # Add timing info
        output["timing_ms"] = int((time.time() - start_time) * 1000)

        # Emit output to frontend
        await self.emit(output)

        return output

    async def _create_session(self, credentials: BlueSkyCredential) -> Dict[str, Any]:
        """Create an authenticated session with BlueSky using App Password."""
        url = f"{BLUESKY_API_BASE}/com.atproto.server.createSession"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json={
                    "identifier": credentials.identifier,
                    "password": credentials.app_password,
                },
                timeout=30.0,
            )

            if response.status_code != 200:
                error_data = (
                    response.json()
                    if response.headers.get("content-type", "").startswith(
                        "application/json"
                    )
                    else {}
                )
                error_msg = error_data.get("message", response.text)
                logger.error(f"[BlueSkyNode] Authentication failed: {error_msg}")
                raise ValueError(f"BlueSky authentication failed: {error_msg}")

            return response.json()

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        access_token: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        action_name: str = "request",
    ) -> Dict[str, Any]:
        """
        Make a request to the BlueSky API (optionally authenticated).

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint (e.g., 'app.bsky.actor.getProfile')
            access_token: JWT access token (optional for public endpoints)
            params: Query parameters
            json_body: JSON request body
            action_name: Action name for response

        Returns:
            Response dict with status, data, and metadata
        """
        url = f"{BLUESKY_API_BASE}/{endpoint}"
        headers = {}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"

        api_start = time.time()

        async with httpx.AsyncClient() as client:
            if method.upper() == "GET":
                response = await client.get(
                    url, headers=headers, params=params, timeout=30.0
                )
            elif method.upper() == "POST":
                response = await client.post(
                    url, headers=headers, json=json_body, params=params, timeout=30.0
                )
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            api_time = int((time.time() - api_start) * 1000)

            if response.status_code not in [200, 201]:
                error_data = (
                    response.json()
                    if response.headers.get("content-type", "").startswith(
                        "application/json"
                    )
                    else {}
                )
                error_msg = error_data.get("message", response.text)
                logger.error(f"[BlueSkyNode] {action_name} failed: {error_msg}")
                return {
                    "type": "bluesky",
                    "action": action_name,
                    "status": "error",
                    "error": error_msg,
                    "status_code": response.status_code,
                    "timestamp": time.time(),
                    "timing_ms": {"api_request": api_time},
                }

            data = (
                response.json()
                if response.headers.get("content-type", "").startswith(
                    "application/json"
                )
                else {}
            )

            return {
                "type": "bluesky",
                "action": action_name,
                "status": "success",
                "data": data,
                "timestamp": time.time(),
                "timing_ms": {"api_request": api_time},
            }

    # ========================================================================
    # Post Operation Handlers
    # ========================================================================

    async def _create_post(
        self, config: BlueSkyCreatePostConfig, access_token: str, did: str
    ) -> Dict[str, Any]:
        """Create a new post on BlueSky."""
        record = {
            "$type": "app.bsky.feed.post",
            "text": config.text,
            "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

        if config.reply_to_uri and config.reply_to_cid:
            record["reply"] = {
                "root": {"uri": config.reply_to_uri, "cid": config.reply_to_cid},
                "parent": {"uri": config.reply_to_uri, "cid": config.reply_to_cid},
            }

        body = {"repo": did, "collection": "app.bsky.feed.post", "record": record}

        result = await self._make_request(
            "POST",
            "com.atproto.repo.createRecord",
            access_token,
            json_body=body,
            action_name="create_post",
        )

        if result["status"] == "success":
            result["uri"] = result["data"].get("uri")
            result["cid"] = result["data"].get("cid")
            result["text"] = config.text

        return result

    async def _delete_post(
        self, config: BlueSkyDeletePostConfig, access_token: str
    ) -> Dict[str, Any]:
        """Delete a post on BlueSky."""
        # Convert BlueSky web URL to AT URI if needed
        at_uri, error = await parse_bluesky_url_to_uri(config.post_uri)
        if error:
            return {
                "type": "bluesky",
                "action": "delete_post",
                "status": "error",
                "error": error,
                "timestamp": time.time(),
            }

        uri_parts = at_uri.replace("at://", "").split("/")
        if len(uri_parts) < 3:
            return {
                "type": "bluesky",
                "action": "delete_post",
                "status": "error",
                "error": f"Invalid post URI format: {at_uri}",
                "timestamp": time.time(),
            }

        repo, collection, rkey = uri_parts[0], uri_parts[1], uri_parts[2]

        body = {"repo": repo, "collection": collection, "rkey": rkey}
        result = await self._make_request(
            "POST",
            "com.atproto.repo.deleteRecord",
            access_token,
            json_body=body,
            action_name="delete_post",
        )

        if result["status"] == "success":
            result["deleted_uri"] = at_uri
            result["original_input"] = config.post_uri

        return result

    async def _get_post_thread(
        self, config: BlueSkyGetPostThreadConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get a post and its thread context."""
        # Convert BlueSky web URL to AT URI if needed
        at_uri, error = await parse_bluesky_url_to_uri(config.post_uri)
        if error:
            return {
                "type": "bluesky",
                "action": "get_post_thread",
                "status": "error",
                "error": error,
                "timestamp": time.time(),
            }

        params = {"uri": at_uri, "depth": config.depth}
        result = await self._make_request(
            "GET",
            "app.bsky.feed.getPostThread",
            access_token,
            params=params,
            action_name="get_post_thread",
        )

        if result["status"] == "success":
            thread = result["data"].get("thread", {})
            post = thread.get("post", {})
            result["post"] = self._simplify_post(post)
            result["replies"] = [
                self._simplify_post(r.get("post", {}))
                for r in thread.get("replies", [])
            ]
            result["reply_count"] = len(result["replies"])

        return result

    async def _get_posts(
        self, config: BlueSkyGetPostsConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get multiple posts by URIs."""
        # Convert all BlueSky web URLs to AT URIs if needed
        at_uris = []
        for uri in config.uris:
            at_uri, error = await parse_bluesky_url_to_uri(uri)
            if error:
                return {
                    "type": "bluesky",
                    "action": "get_posts_by_uris",
                    "status": "error",
                    "error": f"Failed to parse URI '{uri}': {error}",
                    "timestamp": time.time(),
                }
            at_uris.append(at_uri)

        params = {"uris": at_uris}
        result = await self._make_request(
            "GET",
            "app.bsky.feed.getPosts",
            access_token,
            params=params,
            action_name="get_posts_by_uris",
        )

        if result["status"] == "success":
            result["posts"] = [
                self._simplify_post(p) for p in result["data"].get("posts", [])
            ]
            result["count"] = len(result["posts"])

        return result

    async def _like_post(
        self, config: BlueSkyLikePostConfig, access_token: str, did: str
    ) -> Dict[str, Any]:
        """Like a post on BlueSky."""
        # Convert BlueSky web URL to AT URI if needed
        at_uri, error = await parse_bluesky_url_to_uri(config.post_uri)
        if error:
            return {
                "type": "bluesky",
                "action": "like_post",
                "status": "error",
                "error": error,
                "timestamp": time.time(),
            }

        # Fetch CID if not provided
        post_cid = config.post_cid
        if not post_cid:
            post_cid, error = await fetch_post_cid(at_uri, access_token)
            if error:
                return {
                    "type": "bluesky",
                    "action": "like_post",
                    "status": "error",
                    "error": f"Failed to fetch post CID: {error}",
                    "timestamp": time.time(),
                }

        record = {
            "$type": "app.bsky.feed.like",
            "subject": {"uri": at_uri, "cid": post_cid},
            "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

        body = {"repo": did, "collection": "app.bsky.feed.like", "record": record}
        result = await self._make_request(
            "POST",
            "com.atproto.repo.createRecord",
            access_token,
            json_body=body,
            action_name="like_post",
        )

        if result["status"] == "success":
            result["like_uri"] = result["data"].get("uri")
            result["liked_post_uri"] = at_uri
            result["original_input"] = config.post_uri

        return result

    async def _unlike_post(
        self, config: BlueSkyUnlikePostConfig, access_token: str, did: str
    ) -> Dict[str, Any]:
        """Remove a like by finding the like record for a post."""
        # Convert BlueSky web URL to AT URI if needed
        post_uri, error = await parse_bluesky_url_to_uri(config.post_uri)
        if error:
            return {
                "type": "bluesky",
                "action": "unlike_post",
                "status": "error",
                "error": error,
                "timestamp": time.time(),
            }

        # Find the like record by listing the user's likes and searching for this post
        # List records in the user's like collection
        params = {"repo": did, "collection": "app.bsky.feed.like", "limit": 100}

        list_result = await self._make_request(
            "GET",
            "com.atproto.repo.listRecords",
            access_token,
            params=params,
            action_name="list_likes",
        )

        if list_result["status"] != "success":
            return {
                "type": "bluesky",
                "action": "unlike_post",
                "status": "error",
                "error": f"Failed to list likes: {list_result.get('error', 'Unknown error')}",
                "timestamp": time.time(),
            }

        # Find the like record for this specific post
        like_uri = None
        for record in list_result["data"].get("records", []):
            subject = record.get("value", {}).get("subject", {})
            if subject.get("uri") == post_uri:
                like_uri = record.get("uri")
                break

        if not like_uri:
            return {
                "type": "bluesky",
                "action": "unlike_post",
                "status": "error",
                "error": f"No like found for post: {post_uri}. You may not have liked this post.",
                "timestamp": time.time(),
            }

        # Delete the like record
        uri_parts = like_uri.replace("at://", "").split("/")
        if len(uri_parts) < 3:
            return {
                "type": "bluesky",
                "action": "unlike_post",
                "status": "error",
                "error": f"Invalid like URI format: {like_uri}",
                "timestamp": time.time(),
            }

        body = {"repo": uri_parts[0], "collection": uri_parts[1], "rkey": uri_parts[2]}
        result = await self._make_request(
            "POST",
            "com.atproto.repo.deleteRecord",
            access_token,
            json_body=body,
            action_name="unlike_post",
        )

        if result.get("status") == "success":
            result["original_input"] = config.post_uri
            result["unliked_post_uri"] = post_uri
            result["deleted_like_uri"] = like_uri

        return result

    async def _repost(
        self, config: BlueSkyRepostConfig, access_token: str, did: str
    ) -> Dict[str, Any]:
        """Repost a post on BlueSky."""
        # Convert BlueSky web URL to AT URI if needed
        at_uri, error = await parse_bluesky_url_to_uri(config.post_uri)
        if error:
            return {
                "type": "bluesky",
                "action": "repost_post",
                "status": "error",
                "error": error,
                "timestamp": time.time(),
            }

        # Fetch CID if not provided
        post_cid = config.post_cid
        if not post_cid:
            post_cid, error = await fetch_post_cid(at_uri, access_token)
            if error:
                return {
                    "type": "bluesky",
                    "action": "repost_post",
                    "status": "error",
                    "error": f"Failed to fetch post CID: {error}",
                    "timestamp": time.time(),
                }

        record = {
            "$type": "app.bsky.feed.repost",
            "subject": {"uri": at_uri, "cid": post_cid},
            "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

        body = {"repo": did, "collection": "app.bsky.feed.repost", "record": record}
        result = await self._make_request(
            "POST",
            "com.atproto.repo.createRecord",
            access_token,
            json_body=body,
            action_name="repost_post",
        )

        if result["status"] == "success":
            result["repost_uri"] = result["data"].get("uri")
            result["reposted_post_uri"] = at_uri
            result["original_input"] = config.post_uri

        return result

    async def _unrepost(
        self, config: BlueSkyUnrepostConfig, access_token: str, did: str
    ) -> Dict[str, Any]:
        """Remove a repost by finding the repost record for a post."""
        # Convert BlueSky web URL to AT URI if needed
        post_uri, error = await parse_bluesky_url_to_uri(config.post_uri)
        if error:
            return {
                "type": "bluesky",
                "action": "remove_repost",
                "status": "error",
                "error": error,
                "timestamp": time.time(),
            }

        # Find the repost record by listing the user's reposts and searching for this post
        params = {"repo": did, "collection": "app.bsky.feed.repost", "limit": 100}

        list_result = await self._make_request(
            "GET",
            "com.atproto.repo.listRecords",
            access_token,
            params=params,
            action_name="list_reposts",
        )

        if list_result["status"] != "success":
            return {
                "type": "bluesky",
                "action": "remove_repost",
                "status": "error",
                "error": f"Failed to list reposts: {list_result.get('error', 'Unknown error')}",
                "timestamp": time.time(),
            }

        # Find the repost record for this specific post
        repost_uri = None
        for record in list_result["data"].get("records", []):
            subject = record.get("value", {}).get("subject", {})
            if subject.get("uri") == post_uri:
                repost_uri = record.get("uri")
                break

        if not repost_uri:
            return {
                "type": "bluesky",
                "action": "remove_repost",
                "status": "error",
                "error": f"No repost found for post: {post_uri}. You may not have reposted this post.",
                "timestamp": time.time(),
            }

        # Delete the repost record
        uri_parts = repost_uri.replace("at://", "").split("/")
        if len(uri_parts) < 3:
            return {
                "type": "bluesky",
                "action": "remove_repost",
                "status": "error",
                "error": f"Invalid repost URI format: {repost_uri}",
                "timestamp": time.time(),
            }

        body = {"repo": uri_parts[0], "collection": uri_parts[1], "rkey": uri_parts[2]}
        result = await self._make_request(
            "POST",
            "com.atproto.repo.deleteRecord",
            access_token,
            json_body=body,
            action_name="remove_repost",
        )

        if result.get("status") == "success":
            result["original_input"] = config.post_uri
            result["unreposted_post_uri"] = post_uri
            result["deleted_repost_uri"] = repost_uri

        return result

    async def _get_likes(
        self, config: BlueSkyGetLikesConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get users who liked a post."""
        # Convert BlueSky web URL to AT URI if needed
        at_uri, error = await parse_bluesky_url_to_uri(config.post_uri)
        if error:
            return {
                "type": "bluesky",
                "action": "list_post_likers",
                "status": "error",
                "error": error,
                "timestamp": time.time(),
            }

        params = {"uri": at_uri, "limit": config.limit}
        if config.cursor:
            params["cursor"] = config.cursor

        result = await self._make_request(
            "GET",
            "app.bsky.feed.getLikes",
            access_token,
            params=params,
            action_name="list_post_likers",
        )

        if result["status"] == "success":
            result["likes"] = result["data"].get("likes", [])
            result["cursor"] = result["data"].get("cursor")
            result["count"] = len(result["likes"])

        return result

    async def _get_reposted_by(
        self, config: BlueSkyGetRepostedByConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get users who reposted a post."""
        # Convert BlueSky web URL to AT URI if needed
        at_uri, error = await parse_bluesky_url_to_uri(config.post_uri)
        if error:
            return {
                "type": "bluesky",
                "action": "list_post_reposters",
                "status": "error",
                "error": error,
                "timestamp": time.time(),
            }

        params = {"uri": at_uri, "limit": config.limit}
        if config.cursor:
            params["cursor"] = config.cursor

        result = await self._make_request(
            "GET",
            "app.bsky.feed.getRepostedBy",
            access_token,
            params=params,
            action_name="list_post_reposters",
        )

        if result["status"] == "success":
            result["reposted_by"] = result["data"].get("repostedBy", [])
            result["cursor"] = result["data"].get("cursor")
            result["count"] = len(result["reposted_by"])

        return result

    async def _get_quotes(
        self, config: BlueSkyGetQuotesConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get posts that quote a specific post."""
        # Convert BlueSky web URL to AT URI if needed
        at_uri, error = await parse_bluesky_url_to_uri(config.post_uri)
        if error:
            return {
                "type": "bluesky",
                "action": "list_post_quotes",
                "status": "error",
                "error": error,
                "timestamp": time.time(),
            }

        params = {"uri": at_uri, "limit": config.limit}
        if config.cursor:
            params["cursor"] = config.cursor

        result = await self._make_request(
            "GET",
            "app.bsky.feed.getQuotes",
            access_token,
            params=params,
            action_name="list_post_quotes",
        )

        if result["status"] == "success":
            result["posts"] = [
                self._simplify_post(p) for p in result["data"].get("posts", [])
            ]
            result["cursor"] = result["data"].get("cursor")
            result["count"] = len(result["posts"])

        return result

    async def _search_posts(
        self, config: BlueSkySearchPostsConfig, access_token: str
    ) -> Dict[str, Any]:
        """Search for posts on BlueSky."""
        params = {"q": config.query, "limit": config.limit}
        if config.sort:
            params["sort"] = config.sort
        if config.cursor:
            params["cursor"] = config.cursor

        result = await self._make_request(
            "GET",
            "app.bsky.feed.searchPosts",
            access_token,
            params=params,
            action_name="search_posts",
        )

        if result["status"] == "success":
            result["posts"] = [
                self._simplify_post(p) for p in result["data"].get("posts", [])
            ]
            result["cursor"] = result["data"].get("cursor")
            result["count"] = len(result["posts"])
            result["query"] = config.query

        return result

    # ========================================================================
    # Feed Operation Handlers
    # ========================================================================

    async def _get_timeline(
        self, config: BlueSkyGetTimelineConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get the authenticated user's home timeline."""
        params = {"limit": config.limit}
        if config.cursor:
            params["cursor"] = config.cursor

        result = await self._make_request(
            "GET",
            "app.bsky.feed.getTimeline",
            access_token,
            params=params,
            action_name="get_home_timeline",
        )

        if result["status"] == "success":
            result["posts"] = [
                self._simplify_post(item.get("post", {}))
                for item in result["data"].get("feed", [])
            ]
            result["cursor"] = result["data"].get("cursor")
            result["count"] = len(result["posts"])

        return result

    async def _get_author_feed(
        self, config: BlueSkyGetAuthorFeedConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get posts from a specific user's feed."""
        params = {"actor": config.actor, "limit": config.limit}
        if config.filter:
            params["filter"] = config.filter
        if config.cursor:
            params["cursor"] = config.cursor

        result = await self._make_request(
            "GET",
            "app.bsky.feed.getAuthorFeed",
            access_token,
            params=params,
            action_name="get_author_feed",
        )

        if result["status"] == "success":
            result["posts"] = [
                self._simplify_post(item.get("post", {}))
                for item in result["data"].get("feed", [])
            ]
            result["cursor"] = result["data"].get("cursor")
            result["actor"] = config.actor
            result["count"] = len(result["posts"])

        return result

    async def _get_actor_likes(
        self, config: BlueSkyGetActorLikesConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get posts liked by an actor."""
        params = {"actor": config.actor, "limit": config.limit}
        if config.cursor:
            params["cursor"] = config.cursor

        result = await self._make_request(
            "GET",
            "app.bsky.feed.getActorLikes",
            access_token,
            params=params,
            action_name="list_actor_liked_posts",
        )

        if result["status"] == "success":
            result["posts"] = [
                self._simplify_post(item.get("post", {}))
                for item in result["data"].get("feed", [])
            ]
            result["cursor"] = result["data"].get("cursor")
            result["actor"] = config.actor
            result["count"] = len(result["posts"])

        return result

    async def _get_feed_generator(
        self, config: BlueSkyGetFeedGeneratorConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get information about a feed generator."""
        params = {"feed": config.feed_uri}
        return await self._make_request(
            "GET",
            "app.bsky.feed.getFeedGenerator",
            access_token,
            params=params,
            action_name="get_feed_generator",
        )

    async def _get_actor_feeds(
        self, config: BlueSkyGetActorFeedsConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get feed generators created by an actor."""
        params = {"actor": config.actor, "limit": config.limit}
        if config.cursor:
            params["cursor"] = config.cursor

        result = await self._make_request(
            "GET",
            "app.bsky.feed.getActorFeeds",
            access_token,
            params=params,
            action_name="list_actor_feed_generators",
        )

        if result["status"] == "success":
            result["feeds"] = result["data"].get("feeds", [])
            result["cursor"] = result["data"].get("cursor")
            result["count"] = len(result["feeds"])

        return result

    async def _get_suggested_feeds(
        self, config: BlueSkyGetSuggestedFeedsConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get suggested feed generators."""
        params = {"limit": config.limit}
        if config.cursor:
            params["cursor"] = config.cursor

        result = await self._make_request(
            "GET",
            "app.bsky.feed.getSuggestedFeeds",
            access_token,
            params=params,
            action_name="list_suggested_feeds",
        )

        if result["status"] == "success":
            result["feeds"] = result["data"].get("feeds", [])
            result["cursor"] = result["data"].get("cursor")
            result["count"] = len(result["feeds"])

        return result

    async def _get_list_feed(
        self, config: BlueSkyGetListFeedConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get posts from members of a list."""
        params = {"list": config.list_uri, "limit": config.limit}
        if config.cursor:
            params["cursor"] = config.cursor

        result = await self._make_request(
            "GET",
            "app.bsky.feed.getListFeed",
            access_token,
            params=params,
            action_name="get_list_member_feed",
        )

        if result["status"] == "success":
            result["posts"] = [
                self._simplify_post(item.get("post", {}))
                for item in result["data"].get("feed", [])
            ]
            result["cursor"] = result["data"].get("cursor")
            result["count"] = len(result["posts"])

        return result

    async def _get_feed(
        self, config: BlueSkyGetFeedConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get posts from a custom feed."""
        params = {"feed": config.feed_uri, "limit": config.limit}
        if config.cursor:
            params["cursor"] = config.cursor

        result = await self._make_request(
            "GET",
            "app.bsky.feed.getFeed",
            access_token,
            params=params,
            action_name="get_custom_feed_posts",
        )

        if result["status"] == "success":
            result["posts"] = [
                self._simplify_post(item.get("post", {}))
                for item in result["data"].get("feed", [])
            ]
            result["cursor"] = result["data"].get("cursor")
            result["count"] = len(result["posts"])

        return result

    # ========================================================================
    # Actor/Profile Operation Handlers
    # ========================================================================

    async def _get_profile(
        self, config: BlueSkyGetProfileConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get a user's profile information."""
        params = {"actor": config.actor}
        result = await self._make_request(
            "GET",
            "app.bsky.actor.getProfile",
            access_token,
            params=params,
            action_name="get_user_profile",
        )

        if result["status"] == "success":
            profile = result["data"]
            result.update(
                {
                    "did": profile.get("did"),
                    "handle": profile.get("handle"),
                    "display_name": profile.get("displayName"),
                    "description": profile.get("description"),
                    "avatar": profile.get("avatar"),
                    "followers_count": profile.get("followersCount"),
                    "follows_count": profile.get("followsCount"),
                    "posts_count": profile.get("postsCount"),
                    "indexed_at": profile.get("indexedAt"),
                }
            )

        return result

    async def _get_profiles(
        self, config: BlueSkyGetProfilesConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get multiple user profiles at once."""
        params = {"actors": config.actors}
        result = await self._make_request(
            "GET",
            "app.bsky.actor.getProfiles",
            access_token,
            params=params,
            action_name="get_multiple_user_profiles",
        )

        if result["status"] == "success":
            result["profiles"] = result["data"].get("profiles", [])
            result["count"] = len(result["profiles"])

        return result

    async def _search_actors(
        self, config: BlueSkySearchActorsConfig, access_token: str
    ) -> Dict[str, Any]:
        """Search for actors/users."""
        params = {"q": config.query, "limit": config.limit}
        if config.cursor:
            params["cursor"] = config.cursor

        result = await self._make_request(
            "GET",
            "app.bsky.actor.searchActors",
            access_token,
            params=params,
            action_name="search_actors",
        )

        if result["status"] == "success":
            result["actors"] = result["data"].get("actors", [])
            result["cursor"] = result["data"].get("cursor")
            result["count"] = len(result["actors"])
            result["query"] = config.query

        return result

    async def _search_actors_typeahead(
        self, config: BlueSkySearchActorsTypeaheadConfig, access_token: str
    ) -> Dict[str, Any]:
        """Typeahead search for actors."""
        params = {"q": config.query, "limit": config.limit}
        result = await self._make_request(
            "GET",
            "app.bsky.actor.searchActorsTypeahead",
            access_token,
            params=params,
            action_name="search_actors_typeahead",
        )

        if result["status"] == "success":
            result["actors"] = result["data"].get("actors", [])
            result["count"] = len(result["actors"])

        return result

    async def _get_suggestions(
        self, config: BlueSkyGetSuggestionsConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get suggested accounts to follow."""
        params = {"limit": config.limit}
        if config.cursor:
            params["cursor"] = config.cursor

        result = await self._make_request(
            "GET",
            "app.bsky.actor.getSuggestions",
            access_token,
            params=params,
            action_name="list_suggested_accounts",
        )

        if result["status"] == "success":
            result["actors"] = result["data"].get("actors", [])
            result["cursor"] = result["data"].get("cursor")
            result["count"] = len(result["actors"])

        return result

    async def _get_preferences(
        self, config: BlueSkyGetPreferencesConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get user preferences."""
        return await self._make_request(
            "GET",
            "app.bsky.actor.getPreferences",
            access_token,
            action_name="get_user_preferences",
        )

    async def _put_preferences(
        self, config: BlueSkyPutPreferencesConfig, access_token: str
    ) -> Dict[str, Any]:
        """Update user preferences."""
        return await self._make_request(
            "POST",
            "app.bsky.actor.putPreferences",
            access_token,
            json_body={"preferences": config.preferences},
            action_name="update_user_preferences",
        )

    # ========================================================================
    # Graph/Social Operation Handlers
    # ========================================================================

    async def _follow_user(
        self, config: BlueSkyFollowUserConfig, access_token: str, did: str
    ) -> Dict[str, Any]:
        """Follow a user on BlueSky."""
        record = {
            "$type": "app.bsky.graph.follow",
            "subject": config.subject_did,
            "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

        body = {"repo": did, "collection": "app.bsky.graph.follow", "record": record}
        result = await self._make_request(
            "POST",
            "com.atproto.repo.createRecord",
            access_token,
            json_body=body,
            action_name="follow_user",
        )

        if result["status"] == "success":
            result["follow_uri"] = result["data"].get("uri")
            result["followed_did"] = config.subject_did

        return result

    async def _unfollow_user(
        self, config: BlueSkyUnfollowUserConfig, access_token: str
    ) -> Dict[str, Any]:
        """Unfollow a user."""
        uri_parts = config.follow_uri.replace("at://", "").split("/")
        if len(uri_parts) < 3:
            return {
                "type": "bluesky",
                "action": "unfollow_user",
                "status": "error",
                "error": f"Invalid follow URI: {config.follow_uri}",
                "timestamp": time.time(),
            }

        body = {"repo": uri_parts[0], "collection": uri_parts[1], "rkey": uri_parts[2]}
        return await self._make_request(
            "POST",
            "com.atproto.repo.deleteRecord",
            access_token,
            json_body=body,
            action_name="unfollow_user",
        )

    async def _get_followers(
        self, config: BlueSkyGetFollowersConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get an actor's followers."""
        params = {"actor": config.actor, "limit": config.limit}
        if config.cursor:
            params["cursor"] = config.cursor

        result = await self._make_request(
            "GET",
            "app.bsky.graph.getFollowers",
            access_token,
            params=params,
            action_name="list_actor_followers",
        )

        if result["status"] == "success":
            result["followers"] = result["data"].get("followers", [])
            result["cursor"] = result["data"].get("cursor")
            result["count"] = len(result["followers"])

        return result

    async def _get_follows(
        self, config: BlueSkyGetFollowsConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get accounts that an actor follows."""
        params = {"actor": config.actor, "limit": config.limit}
        if config.cursor:
            params["cursor"] = config.cursor

        result = await self._make_request(
            "GET",
            "app.bsky.graph.getFollows",
            access_token,
            params=params,
            action_name="list_actor_follows",
        )

        if result["status"] == "success":
            result["follows"] = result["data"].get("follows", [])
            result["cursor"] = result["data"].get("cursor")
            result["count"] = len(result["follows"])

        return result

    async def _block_user(
        self, config: BlueSkyBlockUserConfig, access_token: str, did: str
    ) -> Dict[str, Any]:
        """Block a user."""
        record = {
            "$type": "app.bsky.graph.block",
            "subject": config.subject_did,
            "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

        body = {"repo": did, "collection": "app.bsky.graph.block", "record": record}
        result = await self._make_request(
            "POST",
            "com.atproto.repo.createRecord",
            access_token,
            json_body=body,
            action_name="block_user",
        )

        if result["status"] == "success":
            result["block_uri"] = result["data"].get("uri")
            result["blocked_did"] = config.subject_did

        return result

    async def _unblock_user(
        self, config: BlueSkyUnblockUserConfig, access_token: str
    ) -> Dict[str, Any]:
        """Unblock a user."""
        uri_parts = config.block_uri.replace("at://", "").split("/")
        if len(uri_parts) < 3:
            return {
                "type": "bluesky",
                "action": "unblock_user",
                "status": "error",
                "error": f"Invalid block URI: {config.block_uri}",
                "timestamp": time.time(),
            }

        body = {"repo": uri_parts[0], "collection": uri_parts[1], "rkey": uri_parts[2]}
        return await self._make_request(
            "POST",
            "com.atproto.repo.deleteRecord",
            access_token,
            json_body=body,
            action_name="unblock_user",
        )

    async def _get_blocks(
        self, config: BlueSkyGetBlocksConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get blocked accounts."""
        params = {"limit": config.limit}
        if config.cursor:
            params["cursor"] = config.cursor

        result = await self._make_request(
            "GET",
            "app.bsky.graph.getBlocks",
            access_token,
            params=params,
            action_name="list_blocked_accounts",
        )

        if result["status"] == "success":
            result["blocks"] = result["data"].get("blocks", [])
            result["cursor"] = result["data"].get("cursor")
            result["count"] = len(result["blocks"])

        return result

    async def _mute_actor(
        self, config: BlueSkyMuteActorConfig, access_token: str
    ) -> Dict[str, Any]:
        """Mute an actor."""
        body = {"actor": config.actor}
        return await self._make_request(
            "POST",
            "app.bsky.graph.muteActor",
            access_token,
            json_body=body,
            action_name="mute_actor",
        )

    async def _unmute_actor(
        self, config: BlueSkyUnmuteActorConfig, access_token: str
    ) -> Dict[str, Any]:
        """Unmute an actor."""
        body = {"actor": config.actor}
        return await self._make_request(
            "POST",
            "app.bsky.graph.unmuteActor",
            access_token,
            json_body=body,
            action_name="unmute_actor",
        )

    async def _get_mutes(
        self, config: BlueSkyGetMutesConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get muted accounts."""
        params = {"limit": config.limit}
        if config.cursor:
            params["cursor"] = config.cursor

        result = await self._make_request(
            "GET",
            "app.bsky.graph.getMutes",
            access_token,
            params=params,
            action_name="list_muted_accounts",
        )

        if result["status"] == "success":
            result["mutes"] = result["data"].get("mutes", [])
            result["cursor"] = result["data"].get("cursor")
            result["count"] = len(result["mutes"])

        return result

    async def _mute_thread(
        self, config: BlueSkyMuteThreadConfig, access_token: str
    ) -> Dict[str, Any]:
        """Mute a thread."""
        body = {"root": config.root_uri}
        return await self._make_request(
            "POST",
            "app.bsky.graph.muteThread",
            access_token,
            json_body=body,
            action_name="mute_thread",
        )

    async def _unmute_thread(
        self, config: BlueSkyUnmuteThreadConfig, access_token: str
    ) -> Dict[str, Any]:
        """Unmute a thread."""
        body = {"root": config.root_uri}
        return await self._make_request(
            "POST",
            "app.bsky.graph.unmuteThread",
            access_token,
            json_body=body,
            action_name="unmute_thread",
        )

    async def _get_list(
        self, config: BlueSkyGetListConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get a list and its members."""
        params = {"list": config.list_uri, "limit": config.limit}
        if config.cursor:
            params["cursor"] = config.cursor

        result = await self._make_request(
            "GET",
            "app.bsky.graph.getList",
            access_token,
            params=params,
            action_name="get_list_with_members",
        )

        if result["status"] == "success":
            result["list_info"] = result["data"].get("list", {})
            result["items"] = result["data"].get("items", [])
            result["cursor"] = result["data"].get("cursor")
            result["count"] = len(result["items"])

        return result

    async def _get_lists(
        self, config: BlueSkyGetListsConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get lists created by an actor."""
        params = {"actor": config.actor, "limit": config.limit}
        if config.cursor:
            params["cursor"] = config.cursor

        result = await self._make_request(
            "GET",
            "app.bsky.graph.getLists",
            access_token,
            params=params,
            action_name="list_actor_lists",
        )

        if result["status"] == "success":
            result["lists"] = result["data"].get("lists", [])
            result["cursor"] = result["data"].get("cursor")
            result["count"] = len(result["lists"])

        return result

    async def _get_relationships(
        self, config: BlueSkyGetRelationshipsConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get relationships between actors."""
        params = {"actor": config.actor, "others": config.others}
        result = await self._make_request(
            "GET",
            "app.bsky.graph.getRelationships",
            access_token,
            params=params,
            action_name="get_actor_relationships",
        )

        if result["status"] == "success":
            result["relationships"] = result["data"].get("relationships", [])
            result["count"] = len(result["relationships"])

        return result

    # ========================================================================
    # Bookmark Operation Handlers
    # ========================================================================

    async def _create_bookmark(
        self, config: BlueSkyCreateBookmarkConfig, access_token: str, did: str
    ) -> Dict[str, Any]:
        """Save a post to bookmarks."""
        # Convert BlueSky web URL to AT URI if needed
        at_uri, error = await parse_bluesky_url_to_uri(config.post_uri)
        if error:
            return {
                "type": "bluesky",
                "action": "create_post_bookmark",
                "status": "error",
                "error": error,
                "timestamp": time.time(),
            }

        # Fetch CID if not provided
        post_cid = config.post_cid
        if not post_cid:
            post_cid, error = await fetch_post_cid(at_uri, access_token)
            if error:
                return {
                    "type": "bluesky",
                    "action": "create_post_bookmark",
                    "status": "error",
                    "error": f"Failed to fetch post CID: {error}",
                    "timestamp": time.time(),
                }

        record = {
            "$type": "app.bsky.bookmark.create",
            "subject": {"uri": at_uri, "cid": post_cid},
            "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

        body = {"repo": did, "collection": "app.bsky.bookmark", "record": record}
        result = await self._make_request(
            "POST",
            "com.atproto.repo.createRecord",
            access_token,
            json_body=body,
            action_name="create_post_bookmark",
        )

        if result["status"] == "success":
            result["bookmark_uri"] = result["data"].get("uri")
            result["bookmarked_post_uri"] = at_uri
            result["original_input"] = config.post_uri

        return result

    async def _delete_bookmark(
        self, config: BlueSkyDeleteBookmarkConfig, access_token: str, did: str
    ) -> Dict[str, Any]:
        """Remove a bookmark by finding the bookmark record for a post."""
        # Convert BlueSky web URL to AT URI if needed
        post_uri, error = await parse_bluesky_url_to_uri(config.post_uri)
        if error:
            return {
                "type": "bluesky",
                "action": "delete_post_bookmark",
                "status": "error",
                "error": error,
                "timestamp": time.time(),
            }

        # Find the bookmark record by listing the user's bookmarks
        params = {"repo": did, "collection": "app.bsky.actor.bookmark", "limit": 100}
        list_result = await self._make_request(
            "GET",
            "com.atproto.repo.listRecords",
            access_token,
            params=params,
            action_name="list_bookmarks",
        )

        if list_result["status"] != "success":
            return {
                "type": "bluesky",
                "action": "delete_post_bookmark",
                "status": "error",
                "error": f"Failed to list bookmarks: {list_result.get('error', 'Unknown error')}",
                "timestamp": time.time(),
            }

        # Find the bookmark record for this specific post
        bookmark_uri = None
        for record in list_result["data"].get("records", []):
            subject = record.get("value", {}).get("subject", {})
            if subject.get("uri") == post_uri:
                bookmark_uri = record.get("uri")
                break

        if not bookmark_uri:
            return {
                "type": "bluesky",
                "action": "delete_post_bookmark",
                "status": "error",
                "error": f"No bookmark found for post: {post_uri}. You may not have bookmarked this post.",
                "timestamp": time.time(),
            }

        # Delete the bookmark record (not the post!)
        uri_parts = bookmark_uri.replace("at://", "").split("/")
        if len(uri_parts) < 3:
            return {
                "type": "bluesky",
                "action": "delete_post_bookmark",
                "status": "error",
                "error": f"Invalid bookmark URI format: {bookmark_uri}",
                "timestamp": time.time(),
            }

        body = {"repo": uri_parts[0], "collection": uri_parts[1], "rkey": uri_parts[2]}
        result = await self._make_request(
            "POST",
            "com.atproto.repo.deleteRecord",
            access_token,
            json_body=body,
            action_name="delete_post_bookmark",
        )

        if result.get("status") == "success":
            result["original_input"] = config.post_uri
            result["deleted_bookmark_uri"] = bookmark_uri
            result["post_uri"] = post_uri

        return result

    async def _get_bookmarks(
        self, config: BlueSkyGetBookmarksConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get user's bookmarks."""
        params = {"limit": config.limit}
        if config.cursor:
            params["cursor"] = config.cursor

        result = await self._make_request(
            "GET",
            "app.bsky.bookmark.getBookmarks",
            access_token,
            params=params,
            action_name="list_bookmarks",
        )

        if result["status"] == "success":
            result["bookmarks"] = result["data"].get("bookmarks", [])
            result["cursor"] = result["data"].get("cursor")
            result["count"] = len(result["bookmarks"])

        return result

    # ========================================================================
    # Notification Operation Handlers
    # ========================================================================

    async def _list_notifications(
        self, config: BlueSkyListNotificationsConfig, access_token: str
    ) -> Dict[str, Any]:
        """List notifications for the authenticated user."""
        params = {"limit": config.limit}
        if config.cursor:
            params["cursor"] = config.cursor
        if config.seen_at:
            params["seenAt"] = config.seen_at

        result = await self._make_request(
            "GET",
            "app.bsky.notification.listNotifications",
            access_token,
            params=params,
            action_name="list_notifications",
        )

        if result["status"] == "success":
            result["notifications"] = result["data"].get("notifications", [])
            result["cursor"] = result["data"].get("cursor")
            result["count"] = len(result["notifications"])

        return result

    async def _get_unread_count(
        self, config: BlueSkyGetUnreadCountConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get count of unread notifications."""
        params = {}
        if config.seen_at:
            params["seenAt"] = config.seen_at

        result = await self._make_request(
            "GET",
            "app.bsky.notification.getUnreadCount",
            access_token,
            params=params,
            action_name="get_unread_notification_count",
        )

        if result["status"] == "success":
            result["count"] = result["data"].get("count", 0)

        return result

    async def _update_seen(
        self, config: BlueSkyUpdateSeenConfig, access_token: str
    ) -> Dict[str, Any]:
        """Mark notifications as seen."""
        body = {"seenAt": config.seen_at}
        return await self._make_request(
            "POST",
            "app.bsky.notification.updateSeen",
            access_token,
            json_body=body,
            action_name="mark_notifications_as_seen",
        )

    async def _register_push(
        self, config: BlueSkyRegisterPushConfig, access_token: str
    ) -> Dict[str, Any]:
        """Register device for push notifications."""
        body = {
            "serviceDid": config.service_did,
            "token": config.token,
            "platform": config.platform,
            "appId": config.app_id,
        }
        return await self._make_request(
            "POST",
            "app.bsky.notification.registerPush",
            access_token,
            json_body=body,
            action_name="register_push_notifications",
        )

    async def _unregister_push(
        self, config: BlueSkyUnregisterPushConfig, access_token: str
    ) -> Dict[str, Any]:
        """Unregister device from push notifications."""
        body = {"serviceDid": config.service_did, "token": config.token}
        return await self._make_request(
            "POST",
            "app.bsky.notification.unregisterPush",
            access_token,
            json_body=body,
            action_name="unregister_push_notifications",
        )

    async def _get_notification_preferences(
        self, config: BlueSkyGetNotificationPreferencesConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get notification preferences."""
        return await self._make_request(
            "GET",
            "app.bsky.notification.getPreferences",
            access_token,
            action_name="get_notification_preferences",
        )

    async def _put_notification_preferences(
        self, config: BlueSkyPutNotificationPreferencesConfig, access_token: str
    ) -> Dict[str, Any]:
        """Update notification preferences."""
        return await self._make_request(
            "POST",
            "app.bsky.notification.putPreferences",
            access_token,
            json_body={"preferences": config.preferences},
            action_name="update_notification_preferences",
        )

    async def _list_activity_subscriptions(
        self, config: BlueSkyListActivitySubscriptionsConfig, access_token: str
    ) -> Dict[str, Any]:
        """List activity notification subscriptions."""
        return await self._make_request(
            "GET",
            "app.bsky.notification.listActivitySubscriptions",
            access_token,
            action_name="list_activity_subscriptions",
        )

    # ========================================================================
    # Chat Operation Handlers
    # ========================================================================

    async def _list_conversations(
        self, config: BlueSkyListConversationsConfig, access_token: str
    ) -> Dict[str, Any]:
        """List user's chat conversations."""
        params = {"limit": config.limit}
        if config.cursor:
            params["cursor"] = config.cursor

        result = await self._make_request(
            "GET",
            "chat.bsky.convo.listConvos",
            access_token,
            params=params,
            action_name="list_user_conversations",
        )

        if result["status"] == "success":
            result["conversations"] = result["data"].get("convos", [])
            result["cursor"] = result["data"].get("cursor")
            result["count"] = len(result["conversations"])

        return result

    async def _get_conversation(
        self, config: BlueSkyGetConversationConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get a specific conversation."""
        params = {"convoId": config.convo_id}
        return await self._make_request(
            "GET",
            "chat.bsky.convo.getConvo",
            access_token,
            params=params,
            action_name="get_conversation",
        )

    async def _get_conversation_for_members(
        self, config: BlueSkyGetConversationForMembersConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get conversation with specific members."""
        params = {"members": config.members}
        return await self._make_request(
            "GET",
            "chat.bsky.convo.getConvoForMembers",
            access_token,
            params=params,
            action_name="get_conversation_with_members",
        )

    async def _get_messages(
        self, config: BlueSkyGetMessagesConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get messages from a conversation."""
        params = {"convoId": config.convo_id, "limit": config.limit}
        if config.cursor:
            params["cursor"] = config.cursor

        result = await self._make_request(
            "GET",
            "chat.bsky.convo.getMessages",
            access_token,
            params=params,
            action_name="list_conversation_messages",
        )

        if result["status"] == "success":
            result["messages"] = result["data"].get("messages", [])
            result["cursor"] = result["data"].get("cursor")
            result["count"] = len(result["messages"])

        return result

    async def _send_message(
        self, config: BlueSkySendMessageConfig, access_token: str
    ) -> Dict[str, Any]:
        """Send a message in a conversation."""
        body = {"convoId": config.convo_id, "message": {"text": config.text}}
        return await self._make_request(
            "POST",
            "chat.bsky.convo.sendMessage",
            access_token,
            json_body=body,
            action_name="send_message_in_conversation",
        )

    async def _delete_message(
        self, config: BlueSkyDeleteMessageConfig, access_token: str
    ) -> Dict[str, Any]:
        """Delete a message (for self only)."""
        body = {"convoId": config.convo_id, "messageId": config.message_id}
        return await self._make_request(
            "POST",
            "chat.bsky.convo.deleteMessageForSelf",
            access_token,
            json_body=body,
            action_name="delete_message_for_self",
        )

    async def _leave_conversation(
        self, config: BlueSkyLeaveConversationConfig, access_token: str
    ) -> Dict[str, Any]:
        """Leave a conversation."""
        body = {"convoId": config.convo_id}
        return await self._make_request(
            "POST",
            "chat.bsky.convo.leaveConvo",
            access_token,
            json_body=body,
            action_name="leave_conversation",
        )

    async def _mute_conversation(
        self, config: BlueSkyMuteConversationConfig, access_token: str
    ) -> Dict[str, Any]:
        """Mute a conversation."""
        body = {"convoId": config.convo_id}
        return await self._make_request(
            "POST",
            "chat.bsky.convo.muteConvo",
            access_token,
            json_body=body,
            action_name="mute_conversation",
        )

    async def _unmute_conversation(
        self, config: BlueSkyUnmuteConversationConfig, access_token: str
    ) -> Dict[str, Any]:
        """Unmute a conversation."""
        body = {"convoId": config.convo_id}
        return await self._make_request(
            "POST",
            "chat.bsky.convo.unmuteConvo",
            access_token,
            json_body=body,
            action_name="unmute_conversation",
        )

    async def _update_conversation_read(
        self, config: BlueSkyUpdateConversationReadConfig, access_token: str
    ) -> Dict[str, Any]:
        """Mark conversation as read."""
        body = {"convoId": config.convo_id}
        if config.message_id:
            body["messageId"] = config.message_id
        return await self._make_request(
            "POST",
            "chat.bsky.convo.updateRead",
            access_token,
            json_body=body,
            action_name="mark_conversation_read",
        )

    async def _accept_conversation(
        self, config: BlueSkyAcceptConversationConfig, access_token: str
    ) -> Dict[str, Any]:
        """Accept a conversation request."""
        body = {"convoId": config.convo_id}
        return await self._make_request(
            "POST",
            "chat.bsky.convo.acceptConvo",
            access_token,
            json_body=body,
            action_name="accept_conversation_request",
        )

    async def _add_message_reaction(
        self, config: BlueSkyAddMessageReactionConfig, access_token: str
    ) -> Dict[str, Any]:
        """Add a reaction to a message."""
        body = {
            "convoId": config.convo_id,
            "messageId": config.message_id,
            "reaction": config.reaction,
        }
        return await self._make_request(
            "POST",
            "chat.bsky.convo.addReaction",
            access_token,
            json_body=body,
            action_name="add_reaction_to_message",
        )

    # ========================================================================
    # Video Operation Handlers
    # ========================================================================

    async def _upload_video(
        self, config: BlueSkyUploadVideoConfig, access_token: str
    ) -> Dict[str, Any]:
        """Upload a video to BlueSky."""
        from nodes.core.media_resolver import resolve_media_input

        resolved = await resolve_media_input(
            config.video_data, default_mime=config.mime_type
        )
        video_bytes = resolved.data

        url = f"{BLUESKY_API_BASE}/app.bsky.video.uploadVideo"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": config.mime_type,
        }

        api_start = time.time()

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url, headers=headers, content=video_bytes, timeout=120.0
            )

            api_time = int((time.time() - api_start) * 1000)

            if response.status_code not in [200, 201]:
                error_data = (
                    response.json()
                    if response.headers.get("content-type", "").startswith(
                        "application/json"
                    )
                    else {}
                )
                return {
                    "type": "bluesky",
                    "action": "upload_video",
                    "status": "error",
                    "error": error_data.get("message", response.text),
                    "status_code": response.status_code,
                    "timestamp": time.time(),
                    "timing_ms": {"api_request": api_time},
                }

            data = (
                response.json()
                if response.headers.get("content-type", "").startswith(
                    "application/json"
                )
                else {}
            )

            return {
                "type": "bluesky",
                "action": "upload_video",
                "status": "success",
                "data": data,
                "job_id": data.get("jobId"),
                "timestamp": time.time(),
                "timing_ms": {"api_request": api_time},
            }

    async def _get_video_job_status(
        self, config: BlueSkyGetVideoJobStatusConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get video processing job status."""
        params = {"jobId": config.job_id}
        return await self._make_request(
            "GET",
            "app.bsky.video.getJobStatus",
            access_token,
            params=params,
            action_name="get_video_job_status",
        )

    async def _get_upload_limits(
        self, config: BlueSkyGetUploadLimitsConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get video upload limits for the account."""
        return await self._make_request(
            "GET",
            "app.bsky.video.getUploadLimits",
            access_token,
            action_name="get_video_upload_limits",
        )

    # ========================================================================
    # Repository Operation Handlers
    # ========================================================================

    async def _create_record(
        self, config: BlueSkyCreateRecordConfig, access_token: str, did: str
    ) -> Dict[str, Any]:
        """Create a record in the repository."""
        body = {"repo": did, "collection": config.collection, "record": config.record}
        if config.rkey:
            body["rkey"] = config.rkey

        return await self._make_request(
            "POST",
            "com.atproto.repo.createRecord",
            access_token,
            json_body=body,
            action_name="create_repository_record",
        )

    async def _put_record(
        self, config: BlueSkyPutRecordConfig, access_token: str, did: str
    ) -> Dict[str, Any]:
        """Create or update a record."""
        body = {
            "repo": did,
            "collection": config.collection,
            "rkey": config.rkey,
            "record": config.record,
        }
        if config.swap_commit:
            body["swapCommit"] = config.swap_commit

        return await self._make_request(
            "POST",
            "com.atproto.repo.putRecord",
            access_token,
            json_body=body,
            action_name="create_or_update_record",
        )

    async def _delete_record(
        self, config: BlueSkyDeleteRecordConfig, access_token: str, did: str
    ) -> Dict[str, Any]:
        """Delete a record from the repository."""
        body = {"repo": did, "collection": config.collection, "rkey": config.rkey}
        if config.swap_commit:
            body["swapCommit"] = config.swap_commit

        return await self._make_request(
            "POST",
            "com.atproto.repo.deleteRecord",
            access_token,
            json_body=body,
            action_name="delete_repository_record",
        )

    async def _get_record(
        self, config: BlueSkyGetRecordConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get a specific record."""
        params = {
            "repo": config.repo,
            "collection": config.collection,
            "rkey": config.rkey,
        }
        if config.cid:
            params["cid"] = config.cid

        return await self._make_request(
            "GET",
            "com.atproto.repo.getRecord",
            access_token,
            params=params,
            action_name="get_repository_record",
        )

    async def _list_records(
        self, config: BlueSkyListRecordsConfig, access_token: str
    ) -> Dict[str, Any]:
        """List records in a collection."""
        params = {
            "repo": config.repo,
            "collection": config.collection,
            "limit": config.limit,
        }
        if config.cursor:
            params["cursor"] = config.cursor

        result = await self._make_request(
            "GET",
            "com.atproto.repo.listRecords",
            access_token,
            params=params,
            action_name="list_repository_records",
        )

        if result["status"] == "success":
            result["records"] = result["data"].get("records", [])
            result["cursor"] = result["data"].get("cursor")
            result["count"] = len(result["records"])

        return result

    async def _upload_blob(
        self, config: BlueSkyUploadBlobConfig, access_token: str
    ) -> Dict[str, Any]:
        """Upload a blob to the repository."""
        from nodes.core.media_resolver import resolve_media_input

        resolved = await resolve_media_input(
            config.blob_data, default_mime=config.mime_type
        )
        blob_bytes = resolved.data

        url = f"{BLUESKY_API_BASE}/com.atproto.repo.uploadBlob"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": config.mime_type,
        }

        api_start = time.time()

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url, headers=headers, content=blob_bytes, timeout=60.0
            )

            api_time = int((time.time() - api_start) * 1000)

            if response.status_code not in [200, 201]:
                error_data = (
                    response.json()
                    if response.headers.get("content-type", "").startswith(
                        "application/json"
                    )
                    else {}
                )
                return {
                    "type": "bluesky",
                    "action": "upload_blob_to_repository",
                    "status": "error",
                    "error": error_data.get("message", response.text),
                    "status_code": response.status_code,
                    "timestamp": time.time(),
                    "timing_ms": {"api_request": api_time},
                }

            data = (
                response.json()
                if response.headers.get("content-type", "").startswith(
                    "application/json"
                )
                else {}
            )

            return {
                "type": "bluesky",
                "action": "upload_blob_to_repository",
                "status": "success",
                "data": data,
                "blob": data.get("blob"),
                "timestamp": time.time(),
                "timing_ms": {"api_request": api_time},
            }

    async def _describe_repo(
        self, config: BlueSkyDescribeRepoConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get repository description and metadata."""
        params = {"repo": config.repo}
        return await self._make_request(
            "GET",
            "com.atproto.repo.describeRepo",
            access_token,
            params=params,
            action_name="describe_repository",
        )

    async def _apply_writes(
        self, config: BlueSkyApplyWritesConfig, access_token: str, did: str
    ) -> Dict[str, Any]:
        """Apply multiple write operations atomically."""
        body = {"repo": did, "writes": config.writes}
        if config.swap_commit:
            body["swapCommit"] = config.swap_commit

        return await self._make_request(
            "POST",
            "com.atproto.repo.applyWrites",
            access_token,
            json_body=body,
            action_name="apply_writes_atomically",
        )

    # ========================================================================
    # Identity Operation Handlers
    # ========================================================================

    async def _resolve_handle(
        self, config: BlueSkyResolveHandleConfig, access_token: str
    ) -> Dict[str, Any]:
        """Resolve a handle to a DID."""
        params = {"handle": config.handle}
        return await self._make_request(
            "GET",
            "com.atproto.identity.resolveHandle",
            access_token,
            params=params,
            action_name="resolve_handle_to_did",
        )

    async def _resolve_did(
        self, config: BlueSkyResolveDidConfig, access_token: str
    ) -> Dict[str, Any]:
        """Resolve a DID to get DID document."""
        params = {"did": config.did}
        return await self._make_request(
            "GET",
            "com.atproto.identity.resolveDid",
            access_token,
            params=params,
            action_name="resolve_did_to_document",
        )

    async def _update_handle(
        self, config: BlueSkyUpdateHandleConfig, access_token: str
    ) -> Dict[str, Any]:
        """Update account handle."""
        body = {"handle": config.handle}
        return await self._make_request(
            "POST",
            "com.atproto.identity.updateHandle",
            access_token,
            json_body=body,
            action_name="update_account_handle",
        )

    async def _get_recommended_did_credentials(
        self, config: BlueSkyGetRecommendedDidCredentialsConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get recommended DID credential providers."""
        return await self._make_request(
            "GET",
            "com.atproto.identity.getRecommendedDidCredentials",
            access_token,
            action_name="get_recommended_did_credentials",
        )

    async def _resolve_identity(
        self, config: BlueSkyResolveIdentityConfig, access_token: str
    ) -> Dict[str, Any]:
        """Resolve complete identity (handle + DID)."""
        params = {"identifier": config.identifier}
        return await self._make_request(
            "GET",
            "com.atproto.identity.resolveIdentity",
            access_token,
            params=params,
            action_name="resolve_complete_identity",
        )

    # ========================================================================
    # Helper Methods
    # ========================================================================

    def _simplify_post(self, post: Dict[str, Any]) -> Dict[str, Any]:
        """Simplify post data for output."""
        author = post.get("author", {})
        record = post.get("record", {})

        return {
            "uri": post.get("uri"),
            "cid": post.get("cid"),
            "author_handle": author.get("handle"),
            "author_display_name": author.get("displayName"),
            "text": record.get("text"),
            "created_at": record.get("createdAt"),
            "like_count": post.get("likeCount", 0),
            "repost_count": post.get("repostCount", 0),
            "reply_count": post.get("replyCount", 0),
        }

    # ========================================================================
    # Age Assurance Operation Handlers (Stub implementations)
    # ========================================================================

    async def _begin_age_assurance(self, config, access_token: str) -> Dict[str, Any]:
        """Start age assurance process"""
        return await self._make_request(
            "POST",
            "app.bsky.ageassurance.begin",
            access_token,
            action_name="begin_age_assurance",
        )

    async def _get_age_assurance_config(
        self, config, access_token: str
    ) -> Dict[str, Any]:
        """Retrieve age assurance configuration"""
        return await self._make_request(
            "GET",
            "app.bsky.ageassurance.getConfig",
            access_token,
            action_name="get_age_assurance_config",
        )

    async def _get_age_assurance_state(
        self, config, access_token: str
    ) -> Dict[str, Any]:
        """Check age assurance status"""
        return await self._make_request(
            "GET",
            "app.bsky.ageassurance.getState",
            access_token,
            action_name="get_age_assurance_state",
        )

    # ========================================================================
    # Additional Feed Operation Handlers
    # ========================================================================

    async def _describe_feed_generator(
        self, config, access_token: str
    ) -> Dict[str, Any]:
        """Get feed generator metadata"""
        return await self._make_request(
            "GET",
            "app.bsky.feed.describeFeedGenerator",
            access_token,
            params={"feed": config.feed_uri},
            action_name="describe_feed_generator",
        )

    async def _get_feed_generators(self, config, access_token: str) -> Dict[str, Any]:
        """Get multiple feed generators"""
        return await self._make_request(
            "GET",
            "app.bsky.feed.getFeedGenerators",
            access_token,
            params={"feeds": config.feeds},
            action_name="get_multiple_feed_generators",
        )

    async def _get_feed_skeleton(self, config, access_token: str) -> Dict[str, Any]:
        """Retrieve feed skeleton structure"""
        params = {"feed": config.feed_uri, "limit": config.limit}
        if config.cursor:
            params["cursor"] = config.cursor
        return await self._make_request(
            "GET",
            "app.bsky.feed.getFeedSkeleton",
            access_token,
            params=params,
            action_name="get_feed_skeleton",
        )

    async def _send_interactions(self, config, access_token: str) -> Dict[str, Any]:
        """Report user interactions"""
        return await self._make_request(
            "POST",
            "app.bsky.feed.sendInteractions",
            access_token,
            json_body={"interactions": config.interactions},
            action_name="send_user_interactions",
        )

    # ========================================================================
    # Additional Graph Operation Handlers
    # ========================================================================

    async def _get_actor_starter_packs(
        self, config, access_token: str
    ) -> Dict[str, Any]:
        """Get starter packs created by user"""
        params = {"actor": config.actor, "limit": config.limit}
        if config.cursor:
            params["cursor"] = config.cursor
        return await self._make_request(
            "GET",
            "app.bsky.graph.getActorStarterPacks",
            access_token,
            params=params,
            action_name="list_actor_starter_packs",
        )

    async def _get_known_followers(self, config, access_token: str) -> Dict[str, Any]:
        """Get mutual followers"""
        params = {"actor": config.actor, "limit": config.limit}
        if config.cursor:
            params["cursor"] = config.cursor
        return await self._make_request(
            "GET",
            "app.bsky.graph.getKnownFollowers",
            access_token,
            params=params,
            action_name="list_mutual_followers",
        )

    async def _get_list_blocks(self, config, access_token: str) -> Dict[str, Any]:
        """Get blocked lists"""
        params = {"limit": config.limit}
        if config.cursor:
            params["cursor"] = config.cursor
        return await self._make_request(
            "GET",
            "app.bsky.graph.getListBlocks",
            access_token,
            params=params,
            action_name="list_blocked_lists",
        )

    async def _get_list_mutes(self, config, access_token: str) -> Dict[str, Any]:
        """Get muted lists"""
        params = {"limit": config.limit}
        if config.cursor:
            params["cursor"] = config.cursor
        return await self._make_request(
            "GET",
            "app.bsky.graph.getListMutes",
            access_token,
            params=params,
            action_name="list_muted_lists",
        )

    async def _get_lists_with_membership(
        self, config, access_token: str
    ) -> Dict[str, Any]:
        """Get lists containing user"""
        params = {"actor": config.actor, "limit": config.limit}
        if config.cursor:
            params["cursor"] = config.cursor
        return await self._make_request(
            "GET",
            "app.bsky.graph.getListsWithMembership",
            access_token,
            params=params,
            action_name="list_actor_membership_lists",
        )

    async def _get_starter_pack(self, config, access_token: str) -> Dict[str, Any]:
        """Get starter pack details"""
        return await self._make_request(
            "GET",
            "app.bsky.graph.getStarterPack",
            access_token,
            params={"starterPack": config.starter_pack_uri},
            action_name="get_starter_pack",
        )

    async def _get_starter_packs_with_membership(
        self, config, access_token: str
    ) -> Dict[str, Any]:
        """Get starter packs user belongs to"""
        params = {"actor": config.actor, "limit": config.limit}
        if config.cursor:
            params["cursor"] = config.cursor
        return await self._make_request(
            "GET",
            "app.bsky.graph.getStarterPacksWithMembership",
            access_token,
            params=params,
            action_name="list_starter_packs_with_membership",
        )

    async def _get_starter_packs(self, config, access_token: str) -> Dict[str, Any]:
        """Get starter packs"""
        return await self._make_request(
            "GET",
            "app.bsky.graph.getStarterPacks",
            access_token,
            params={"uris": config.uris},
            action_name="get_multiple_starter_packs",
        )

    async def _get_suggested_follows_by_actor(
        self, config, access_token: str
    ) -> Dict[str, Any]:
        """Get follow suggestions"""
        return await self._make_request(
            "GET",
            "app.bsky.graph.getSuggestedFollowsByActor",
            access_token,
            params={"actor": config.actor},
            action_name="list_suggested_follows_by_actor",
        )

    async def _mute_actor_list(self, config, access_token: str) -> Dict[str, Any]:
        """Mute entire list"""
        return await self._make_request(
            "POST",
            "app.bsky.graph.muteActorList",
            access_token,
            json_body={"list": config.list_uri},
            action_name="mute_list",
        )

    async def _unmute_actor_list(self, config, access_token: str) -> Dict[str, Any]:
        """Unmute list"""
        return await self._make_request(
            "POST",
            "app.bsky.graph.unmuteActorList",
            access_token,
            json_body={"list": config.list_uri},
            action_name="unmute_list",
        )

    async def _search_starter_packs(self, config, access_token: str) -> Dict[str, Any]:
        """Search starter packs"""
        params = {"q": config.query, "limit": config.limit}
        if config.cursor:
            params["cursor"] = config.cursor
        return await self._make_request(
            "GET",
            "app.bsky.graph.searchStarterPacks",
            access_token,
            params=params,
            action_name="search_starter_packs",
        )

    # ========================================================================
    # Labeler Operation Handlers
    # ========================================================================

    async def _get_labeler_services(self, config, access_token: str) -> Dict[str, Any]:
        """Retrieve labeling services"""
        return await self._make_request(
            "GET",
            "app.bsky.labeler.getServices",
            access_token,
            params={"dids": config.dids},
            action_name="get_labeler_services",
        )

    # ========================================================================
    # Additional Chat Operation Handlers
    # ========================================================================

    async def _remove_message_reaction(
        self, config, access_token: str
    ) -> Dict[str, Any]:
        """Remove message reaction"""
        body = {
            "convoId": config.convo_id,
            "messageId": config.message_id,
            "reaction": config.reaction,
        }
        return await self._make_request(
            "POST",
            "chat.bsky.convo.removeReaction",
            access_token,
            json_body=body,
            action_name="remove_reaction_from_message",
        )

    async def _send_message_batch(self, config, access_token: str) -> Dict[str, Any]:
        """Send multiple messages"""
        return await self._make_request(
            "POST",
            "chat.bsky.convo.sendMessageBatch",
            access_token,
            json_body={"messages": config.messages},
            action_name="send_message_batch",
        )

    async def _get_conversation_log(self, config, access_token: str) -> Dict[str, Any]:
        """Get conversation event log"""
        params = {}
        if config.cursor:
            params["cursor"] = config.cursor
        return await self._make_request(
            "GET",
            "chat.bsky.convo.getLog",
            access_token,
            params=params,
            action_name="get_conversation_event_log",
        )

    async def _get_convo_availability(
        self, config, access_token: str
    ) -> Dict[str, Any]:
        """Check if conversation possible"""
        return await self._make_request(
            "GET",
            "chat.bsky.convo.getConvoAvailability",
            access_token,
            params={"actor": config.actor},
            action_name="check_conversation_availability",
        )

    async def _update_all_read(self, config, access_token: str) -> Dict[str, Any]:
        """Mark all messages read"""
        return await self._make_request(
            "POST",
            "chat.bsky.convo.updateAllRead",
            access_token,
            action_name="mark_all_messages_read",
        )

    async def _delete_chat_account(self, config, access_token: str) -> Dict[str, Any]:
        """Delete chat account"""
        return await self._make_request(
            "POST",
            "chat.bsky.actor.deleteAccount",
            access_token,
            action_name="delete_chat_account",
        )

    # ========================================================================
    # Server Operation Handlers
    # ========================================================================

    async def _activate_account(self, config, access_token: str) -> Dict[str, Any]:
        """Reactivate deactivated account"""
        return await self._make_request(
            "POST",
            "com.atproto.server.activateAccount",
            access_token,
            action_name="activate_account",
        )

    async def _check_account_status(self, config, access_token: str) -> Dict[str, Any]:
        """Verify account status"""
        return await self._make_request(
            "GET",
            "com.atproto.server.checkAccountStatus",
            access_token,
            action_name="check_account_status",
        )

    async def _confirm_email(self, config, access_token: str) -> Dict[str, Any]:
        """Confirm email address"""
        return await self._make_request(
            "POST",
            "com.atproto.server.confirmEmail",
            access_token,
            json_body={"token": config.token, "email": config.email},
            action_name="confirm_email",
        )

    async def _create_app_password(self, config, access_token: str) -> Dict[str, Any]:
        """Generate application password"""
        return await self._make_request(
            "POST",
            "com.atproto.server.createAppPassword",
            access_token,
            json_body={"name": config.name},
            action_name="create_app_password",
        )

    async def _create_invite_code(self, config, access_token: str) -> Dict[str, Any]:
        """Generate invite code"""
        return await self._make_request(
            "POST",
            "com.atproto.server.createInviteCode",
            access_token,
            json_body={"useCount": config.use_count},
            action_name="create_invite_code",
        )

    async def _create_invite_codes(self, config, access_token: str) -> Dict[str, Any]:
        """Generate multiple invite codes"""
        return await self._make_request(
            "POST",
            "com.atproto.server.createInviteCodes",
            access_token,
            json_body={"codeCount": config.code_count, "useCount": config.use_count},
            action_name="create_multiple_invite_codes",
        )

    async def _deactivate_account(self, config, access_token: str) -> Dict[str, Any]:
        """Temporarily disable account"""
        return await self._make_request(
            "POST",
            "com.atproto.server.deactivateAccount",
            access_token,
            action_name="deactivate_account",
        )

    async def _delete_account(self, config, access_token: str) -> Dict[str, Any]:
        """Permanently remove account"""
        return await self._make_request(
            "POST",
            "com.atproto.server.deleteAccount",
            access_token,
            json_body={"password": config.password, "token": config.token},
            action_name="delete_account",
        )

    async def _delete_session(self, config, access_token: str) -> Dict[str, Any]:
        """Logout/end session"""
        return await self._make_request(
            "POST",
            "com.atproto.server.deleteSession",
            access_token,
            action_name="delete_session_logout",
        )

    async def _describe_server(self, config) -> Dict[str, Any]:
        """Get server information"""
        return await self._make_request(
            "GET",
            "com.atproto.server.describeServer",
            access_token=None,
            action_name="describe_server",
        )

    async def _get_account_invite_codes(
        self, config, access_token: str
    ) -> Dict[str, Any]:
        """Retrieve generated codes"""
        return await self._make_request(
            "GET",
            "com.atproto.server.getAccountInviteCodes",
            access_token,
            action_name="list_account_invite_codes",
        )

    async def _get_service_auth(self, config, access_token: str) -> Dict[str, Any]:
        """Get service authentication"""
        return await self._make_request(
            "GET",
            "com.atproto.server.getServiceAuth",
            access_token,
            params={"aud": config.aud},
            action_name="get_service_auth_token",
        )

    async def _get_session(self, config, access_token: str) -> Dict[str, Any]:
        """Verify active session"""
        return await self._make_request(
            "GET",
            "com.atproto.server.getSession",
            access_token,
            action_name="get_active_session",
        )

    async def _list_app_passwords(self, config, access_token: str) -> Dict[str, Any]:
        """List application passwords"""
        return await self._make_request(
            "GET",
            "com.atproto.server.listAppPasswords",
            access_token,
            action_name="list_app_passwords",
        )

    async def _refresh_session(self, config, access_token: str) -> Dict[str, Any]:
        """Refresh session credentials"""
        return await self._make_request(
            "POST",
            "com.atproto.server.refreshSession",
            access_token,
            action_name="refresh_session",
        )

    async def _request_account_delete(
        self, config, access_token: str
    ) -> Dict[str, Any]:
        """Initiate account deletion"""
        return await self._make_request(
            "POST",
            "com.atproto.server.requestAccountDelete",
            access_token,
            action_name="request_account_deletion",
        )

    async def _request_email_confirmation(
        self, config, access_token: str
    ) -> Dict[str, Any]:
        """Request verification email"""
        return await self._make_request(
            "POST",
            "com.atproto.server.requestEmailConfirmation",
            access_token,
            action_name="request_email_confirmation",
        )

    async def _request_email_update(self, config, access_token: str) -> Dict[str, Any]:
        """Request email change"""
        return await self._make_request(
            "POST",
            "com.atproto.server.requestEmailUpdate",
            access_token,
            json_body={"email": config.email},
            action_name="request_email_update",
        )

    async def _request_password_reset(
        self, config, access_token: str
    ) -> Dict[str, Any]:
        """Initiate password reset"""
        return await self._make_request(
            "POST",
            "com.atproto.server.requestPasswordReset",
            access_token,
            json_body={"email": config.email},
            action_name="request_password_reset",
        )

    async def _reserve_signing_key(self, config, access_token: str) -> Dict[str, Any]:
        """Reserve signing key"""
        body = {}
        if config.did:
            body["did"] = config.did
        return await self._make_request(
            "POST",
            "com.atproto.server.reserveSigningKey",
            access_token,
            json_body=body,
            action_name="reserve_signing_key",
        )

    async def _reset_password(self, config, access_token: str) -> Dict[str, Any]:
        """Complete password reset"""
        return await self._make_request(
            "POST",
            "com.atproto.server.resetPassword",
            access_token,
            json_body={"token": config.token, "password": config.password},
            action_name="reset_password",
        )

    async def _revoke_app_password(self, config, access_token: str) -> Dict[str, Any]:
        """Remove application password"""
        return await self._make_request(
            "POST",
            "com.atproto.server.revokeAppPassword",
            access_token,
            json_body={"name": config.name},
            action_name="revoke_app_password",
        )

    async def _update_email(self, config, access_token: str) -> Dict[str, Any]:
        """Update account email"""
        return await self._make_request(
            "POST",
            "com.atproto.server.updateEmail",
            access_token,
            json_body={"email": config.email, "token": config.token},
            action_name="update_account_email",
        )

    # ========================================================================
    # Label & Moderation Operation Handlers
    # ========================================================================

    async def _query_labels(self, config, access_token: str) -> Dict[str, Any]:
        """Query content labels"""
        params = {"uriPatterns": config.uri_patterns, "limit": config.limit}
        if config.sources:
            params["sources"] = config.sources
        if config.cursor:
            params["cursor"] = config.cursor
        return await self._make_request(
            "GET",
            "com.atproto.label.queryLabels",
            access_token,
            params=params,
            action_name="query_content_labels",
        )

    async def _create_moderation_report(
        self, config, access_token: str
    ) -> Dict[str, Any]:
        """Submit moderation report"""
        body = {"reasonType": config.reason_type, "subject": config.subject}
        if config.reason:
            body["reason"] = config.reason
        return await self._make_request(
            "POST",
            "com.atproto.moderation.createReport",
            access_token,
            json_body=body,
            action_name="create_moderation_report",
        )
