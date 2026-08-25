"""
Threads (by Meta) automation node.

Integrates the Threads API (https://graph.threads.net/v1.0) — a self-contained
surface distinct from the Facebook/Instagram Graph API. Threads uses its own
OAuth flow and app-scoped user access tokens (see nodes/oauth/threads_oauth.py);
a Facebook/Instagram Graph token does NOT work here and vice versa.

Coverage:
- Publishing: text / image / video / carousel containers, replies, quotes,
  publish, container status, delete, publishing-limit quota.
- Reading: a post, a user's posts, ghost posts, carousel children.
- Replies & moderation: replies, full conversation, the user's own replies,
  hide/unhide, reply approvals (pending replies).
- Insights: per-post and account/user insights (incl. follower demographics).
- Profile & discovery: own profile, public profile lookup + public posts.
- Search: keyword search. Mentions. Location search + lookup.
- Generic escape hatch: an arbitrary Threads Graph request.
- Webhook triggers (per topic): replies, mentions, publish, delete.

Authentication: Threads OAuth 2.0 (threads_oauth credential) or a manually
supplied Threads user access token (threads_access_token credential).

API Base URL: https://graph.threads.net/v1.0
Docs: https://developers.facebook.com/docs/threads
"""

import hashlib
import hmac
import json
import logging
import time
from typing import Any, Dict, List, Literal, Optional, Union

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model
from starlette.responses import PlainTextResponse
from typing import Annotated

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.oauth.threads_oauth import is_token_expired, refresh_access_token
from nodes.scopes.meta import THREADS_SCOPES

logger = logging.getLogger(__name__)

THREADS_API_VERSION = "v1.0"
THREADS_API_BASE = f"https://graph.threads.net/{THREADS_API_VERSION}"

# Full Threads OAuth scope set the node's operations can touch.
THREADS_OAUTH_SCOPES = [
    "threads_basic",
    "threads_content_publish",
    "threads_read_replies",
    "threads_manage_replies",
    "threads_manage_insights",
    "threads_manage_mentions",
    "threads_keyword_search",
    "threads_location_tagging",
    "threads_delete",
    "threads_profile_discovery",
]


# ============================================================================
# Credential Schemas
# ============================================================================


class ThreadsOAuthCredential(BaseModel):
    """OAuth 2.0 long-lived Threads user access token (via Threads Login)."""

    credential_type: Literal["threads_oauth"] = Field(
        "threads_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ...,
        title="Access Token",
        description="Long-lived Threads user access token",
        json_schema_extra={"ui:widget": "password"},
    )
    expires_at: Optional[str] = Field(
        None, title="Token Expiry", description="ISO 8601 timestamp when the token expires"
    )
    threads_user_id: Optional[str] = Field(
        None, title="Threads User ID", description="Connected Threads user ID"
    )
    username: Optional[str] = Field(None, title="Username", description="Connected Threads username")

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://developers.facebook.com/apps/",
            "x-credential-type": "oauth",
            "x-oauth-provider": "threads",
            # Hidden until Meta approves our OAuth app — existing OAuth credentials
            # still parse/execute; new connections use the access-token credential.
            # PostHog flag reveals it for allow-listed accounts (e.g. Meta reviewers).
            "x-credential-hidden": True,
            "x-credential-preview-flag": "meta-oauth-preview",
            "x-oauth-scopes": THREADS_OAUTH_SCOPES,
        }
    )


class ThreadsAccessTokenCredential(BaseModel):
    """Manually supplied Threads user access token (no OAuth popup)."""

    credential_type: Literal["threads_access_token"] = Field(
        "threads_access_token", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ...,
        title="Access Token",
        description="Threads user access token from the Graph API Explorer / your own OAuth",
        json_schema_extra={"ui:widget": "password"},
    )
    expires_at: Optional[str] = Field(
        None, title="Token Expiry", description="ISO 8601 expiry, if the token expires"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://developers.facebook.com/docs/threads/get-started",
        }
    )


ThreadsCredential = Union[ThreadsOAuthCredential, ThreadsAccessTokenCredential]


# ============================================================================
# Request helper
# ============================================================================


async def _threads_request(
    access_token: str,
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated Threads API request and return a structured result.

    Threads does not use appsecret_proof; the bearer access token alone
    authenticates. Reads take query params; writes take form-encoded data.
    """
    url = f"{THREADS_API_BASE}{endpoint}"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {k: v for k, v in (params or {}).items() if v not in (None, "")}
    if not params:
        params = None
    if data:
        data = {k: v for k, v in data.items() if v not in (None, "")}

    start = time.time()
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.request(
                method=method, url=url, headers=headers, params=params, data=data
            )
            api_ms = round((time.time() - start) * 1000, 2)
            if response.status_code >= 400:
                try:
                    err = response.json()
                    error_obj = err.get("error", {})
                    message = (
                        error_obj.get("message")
                        if isinstance(error_obj, dict)
                        else err.get("message", str(err))
                    )
                except Exception:
                    message = response.text
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[ThreadsNode] API error ({action_name}): {message}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": message,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }
            if response.status_code == 204:
                payload: Any = {"success": True}
            else:
                try:
                    payload = response.json()
                except Exception:
                    payload = {"raw": response.text}
            return {
                "status": "success",
                "action": action_name,
                "data": payload,
                "status_code": response.status_code,
                "timing_ms": {"api_request": api_ms},
            }
        except httpx.TimeoutException:
            return {
                "status": "error",
                "action": action_name,
                "error": "Request timed out",
                "status_code": 408,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }
        except Exception as e:
            msg = str(e).encode("ascii", errors="replace").decode("ascii")
            logger.error(f"[ThreadsNode] Request failed ({action_name}): {msg}")
            return {
                "status": "error",
                "action": action_name,
                "error": msg,
                "status_code": 500,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }


def _parse_json_field(raw: Optional[str], label: str) -> Any:
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except Exception as e:
        raise ValueError(f"{label} must be valid JSON: {e}")


# Shared dynamic-options spec for fields that reference one of the user's posts.
# Backed by GET /me/threads (see ThreadsNode.load_field_options), with a
# custom-input escape hatch to paste an ID directly.
_MEDIA_DYNAMIC = {
    "x-dynamic-options": {
        "field_name": "media_id",
        "placeholder": "Select one of your posts...",
        "searchable": True,
        "allow_custom": True,
        "custom_placeholder": "Or paste a Threads post ID",
    }
}

# Registries populated below (append-only, one entry per operation).
OPERATION_CONFIGS: List[type] = []
OPERATION_HANDLERS: Dict[str, Any] = {}


def _uid(config) -> str:
    """Resolve the Threads user id path segment ('me' unless overridden)."""
    return (getattr(config, "user_id", None) or "me")


# ============================================================================
# Profile & discovery
# ============================================================================


class ThreadsGetMeConfig(BaseModel):
    """Get the authenticated Threads user's profile."""
    operation: Literal["get_me"] = Field(
        "get_me",
        json_schema_extra={"const": "get_me", "ui:hidden": True,
                           "x-category": "Profile", "x-is-trigger": False,
                           "x-display-name": "Get My Profile"},
        title="Get My Profile",
    )
    fields: str = Field(
        "id,username,name,threads_profile_picture_url,threads_biography,is_verified",
        title="Fields", description="Comma-separated profile fields to return.",
    )


async def _get_me(c, token) -> Dict[str, Any]:
    return await _threads_request(token, "GET", "/me", params={"fields": c.fields},
                                  action_name="get_me")


class ThreadsLookupProfileConfig(BaseModel):
    """Look up a public Threads profile by username (>=100 followers)."""
    operation: Literal["lookup_profile"] = Field(
        "lookup_profile",
        json_schema_extra={"const": "lookup_profile", "ui:hidden": True,
                           "x-category": "Profile", "x-is-trigger": False,
                           "x-display-name": "Look Up Public Profile"},
        title="Look Up Public Profile",
    )
    username: str = Field(..., title="Username", description="Exact Threads username to look up.")
    fields: str = Field(
        "username,name,profile_picture_url,biography,follower_count,likes_count,is_verified",
        title="Fields", description="Comma-separated public profile fields.",
    )


async def _lookup_profile(c, token) -> Dict[str, Any]:
    return await _threads_request(token, "GET", "/profile_lookup",
                                  params={"username": c.username, "fields": c.fields},
                                  action_name="lookup_profile")


class ThreadsPublicPostsConfig(BaseModel):
    """List a public Threads profile's posts by username (>=100 followers)."""
    operation: Literal["list_public_posts"] = Field(
        "list_public_posts",
        json_schema_extra={"const": "list_public_posts", "ui:hidden": True,
                           "x-category": "Profile", "x-is-trigger": False,
                           "x-display-name": "List Public Profile Posts"},
        title="List Public Profile Posts",
    )
    username: str = Field(..., title="Username", description="Exact Threads username.")
    fields: str = Field("id,text,permalink,timestamp,media_type", title="Fields", description="Comma-separated fields to return.")
    since: Optional[str] = Field(None, title="Since", description="Start date (YYYY-MM-DD or Unix).")
    until: Optional[str] = Field(None, title="Until", description="End date (YYYY-MM-DD or Unix).")
    limit: Optional[str] = Field("25", title="Limit", description="Max posts per page.")


async def _list_public_posts(c, token) -> Dict[str, Any]:
    return await _threads_request(token, "GET", "/profile_posts", params={
        "username": c.username, "fields": c.fields,
        "since": c.since, "until": c.until, "limit": c.limit,
    }, action_name="list_public_posts")


OPERATION_CONFIGS += [ThreadsGetMeConfig, ThreadsLookupProfileConfig, ThreadsPublicPostsConfig]
OPERATION_HANDLERS.update({
    "get_me": _get_me,
    "lookup_profile": _lookup_profile,
    "list_public_posts": _list_public_posts,
})


# ============================================================================
# Publishing
# ============================================================================


class ThreadsCreatePostConfig(BaseModel):
    """Create a Threads media container (step 1 of publishing)."""
    operation: Literal["create_post"] = Field(
        "create_post",
        json_schema_extra={"const": "create_post", "ui:hidden": True,
                           "x-category": "Publishing", "x-is-trigger": False,
                           "x-display-name": "Create Post Container"},
        title="Create Post Container",
    )
    user_id: str = Field("me", title="Threads User", description="Threads user ID, or 'me'.")
    media_type: str = Field(
        "TEXT", title="Media Type", description="Type of post to create.",
        json_schema_extra={"enum": ["TEXT", "IMAGE", "VIDEO", "CAROUSEL"], "x-enum-searchable": True},
    )
    text: Optional[str] = Field(None, title="Text", description="Post text (<=500 chars). Required for TEXT.")
    image_url: Optional[str] = Field(None, title="Image URL", description="Publicly reachable image URL (IMAGE).")
    video_url: Optional[str] = Field(None, title="Video URL", description="Publicly reachable video URL (VIDEO).")
    is_carousel_item: Optional[str] = Field(
        None, title="Is Carousel Item", description="Set to 'true' when creating a carousel child item.",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )
    children: Optional[str] = Field(None, title="Children", description="Comma-separated child container IDs (CAROUSEL, 2-20).")
    reply_to_id: Optional[str] = Field(None, title="Reply To ID", description="Post ID being replied to.")
    quote_post_id: Optional[str] = Field(None, title="Quote Post ID", description="Post ID to quote.")
    reply_control: Optional[str] = Field(
        None, title="Reply Control", description="Who can reply.",
        json_schema_extra={"enum": ["everyone", "accounts_you_follow", "mentioned_only", "parent_post_author_only", "followers_only"], "x-enum-searchable": True},
    )
    link_attachment: Optional[str] = Field(None, title="Link Attachment", description="URL to attach to a text post.")
    alt_text: Optional[str] = Field(None, title="Alt Text", description="Accessibility text (<=1000 chars).")
    location_id: Optional[str] = Field(None, title="Location ID", description="Location ID to tag (needs location tagging scope).")
    topic_tag: Optional[str] = Field(None, title="Topic Tag", description="Single topic tag (no periods/ampersands).")
    allowlisted_country_codes: Optional[str] = Field(None, title="Allowlisted Country Codes", description="Comma-separated ISO country codes to geo-restrict.")
    body_json: str = Field("{}", title="Additional Fields (JSON)", description="Extra container fields merged into the request (poll_attachment, etc.).",
                           json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _create_post(c, token) -> Dict[str, Any]:
    data = {
        "media_type": c.media_type, "text": c.text,
        "image_url": c.image_url, "video_url": c.video_url,
        "is_carousel_item": c.is_carousel_item, "children": c.children,
        "reply_to_id": c.reply_to_id, "quote_post_id": c.quote_post_id,
        "reply_control": c.reply_control, "link_attachment": c.link_attachment,
        "alt_text": c.alt_text, "location_id": c.location_id, "topic_tag": c.topic_tag,
        "allowlisted_country_codes": c.allowlisted_country_codes,
    }
    extra = _parse_json_field(c.body_json, "Additional Fields") or {}
    data.update(extra)
    return await _threads_request(token, "POST", f"/{_uid(c)}/threads", data=data,
                                  action_name="create_post")


class ThreadsPublishPostConfig(BaseModel):
    """Publish a previously-created Threads media container (step 2)."""
    operation: Literal["publish_post"] = Field(
        "publish_post",
        json_schema_extra={"const": "publish_post", "ui:hidden": True,
                           "x-category": "Publishing", "x-is-trigger": False,
                           "x-display-name": "Publish Post"},
        title="Publish Post",
    )
    user_id: str = Field("me", title="Threads User", description="Threads user ID, or 'me'.")
    creation_id: str = Field(..., title="Creation ID", description="The container ID returned by Create Post Container.")


async def _publish_post(c, token) -> Dict[str, Any]:
    return await _threads_request(token, "POST", f"/{_uid(c)}/threads_publish",
                                  data={"creation_id": c.creation_id}, action_name="publish_post")


class ThreadsContainerStatusConfig(BaseModel):
    """Check the processing status of a media container before publishing."""
    operation: Literal["get_container_status"] = Field(
        "get_container_status",
        json_schema_extra={"const": "get_container_status", "ui:hidden": True,
                           "x-category": "Publishing", "x-is-trigger": False,
                           "x-display-name": "Get Container Status"},
        title="Get Container Status",
    )
    creation_id: str = Field(..., title="Creation ID", description="The media container ID.")
    fields: str = Field("status,error_message", title="Fields", description="Comma-separated fields to return.")


async def _get_container_status(c, token) -> Dict[str, Any]:
    return await _threads_request(token, "GET", f"/{c.creation_id}", params={"fields": c.fields},
                                  action_name="get_container_status")


class ThreadsDeletePostConfig(BaseModel):
    """Delete one of the authenticated user's own Threads posts."""
    operation: Literal["delete_post"] = Field(
        "delete_post",
        json_schema_extra={"const": "delete_post", "ui:hidden": True,
                           "x-category": "Publishing", "x-is-trigger": False,
                           "x-display-name": "Delete Post"},
        title="Delete Post",
    )
    media_id: str = Field(..., title="Media ID", description="The Threads post ID to delete.", json_schema_extra=_MEDIA_DYNAMIC)


async def _delete_post(c, token) -> Dict[str, Any]:
    return await _threads_request(token, "DELETE", f"/{c.media_id}", action_name="delete_post")


class ThreadsPublishingLimitConfig(BaseModel):
    """Get the user's remaining publishing / reply / delete quota (per 24h)."""
    operation: Literal["get_publishing_limit"] = Field(
        "get_publishing_limit",
        json_schema_extra={"const": "get_publishing_limit", "ui:hidden": True,
                           "x-category": "Publishing", "x-is-trigger": False,
                           "x-display-name": "Get Publishing Limit"},
        title="Get Publishing Limit",
    )
    user_id: str = Field("me", title="Threads User", description="Threads user ID, or 'me'.")
    fields: str = Field(
        "quota_usage,config,reply_quota_usage,reply_config,delete_quota_usage,delete_config",
        title="Fields", description="Comma-separated fields to return.",
    )


async def _get_publishing_limit(c, token) -> Dict[str, Any]:
    return await _threads_request(token, "GET", f"/{_uid(c)}/threads_publishing_limit",
                                  params={"fields": c.fields}, action_name="get_publishing_limit")


OPERATION_CONFIGS += [ThreadsCreatePostConfig, ThreadsPublishPostConfig,
                      ThreadsContainerStatusConfig, ThreadsDeletePostConfig,
                      ThreadsPublishingLimitConfig]
OPERATION_HANDLERS.update({
    "create_post": _create_post,
    "publish_post": _publish_post,
    "get_container_status": _get_container_status,
    "delete_post": _delete_post,
    "get_publishing_limit": _get_publishing_limit,
})


# ============================================================================
# Reading posts
# ============================================================================

_MEDIA_FIELDS = ("id,media_product_type,media_type,media_url,permalink,owner,username,"
                 "text,timestamp,shortcode,thumbnail_url,children,is_quote_post,has_replies,"
                 "is_reply,reply_audience,alt_text,link_attachment_url,quoted_post,reposted_post")


class ThreadsGetPostConfig(BaseModel):
    """Get a single Threads post (media object) by ID."""
    operation: Literal["get_post"] = Field(
        "get_post",
        json_schema_extra={"const": "get_post", "ui:hidden": True,
                           "x-category": "Posts", "x-is-trigger": False,
                           "x-display-name": "Get Post"},
        title="Get Post",
    )
    media_id: str = Field(..., title="Media ID", description="The Threads post ID.", json_schema_extra=_MEDIA_DYNAMIC)
    fields: str = Field(_MEDIA_FIELDS, title="Fields", description="Comma-separated media fields.")


async def _get_post(c, token) -> Dict[str, Any]:
    return await _threads_request(token, "GET", f"/{c.media_id}", params={"fields": c.fields},
                                  action_name="get_post")


class ThreadsListPostsConfig(BaseModel):
    """List the authenticated user's Threads posts."""
    operation: Literal["list_posts"] = Field(
        "list_posts",
        json_schema_extra={"const": "list_posts", "ui:hidden": True,
                           "x-category": "Posts", "x-is-trigger": False,
                           "x-display-name": "List My Posts"},
        title="List My Posts",
    )
    user_id: str = Field("me", title="Threads User", description="Threads user ID, or 'me'.")
    fields: str = Field(_MEDIA_FIELDS, title="Fields", description="Comma-separated fields to return.")
    since: Optional[str] = Field(None, title="Since", description="Start date (YYYY-MM-DD or Unix).")
    until: Optional[str] = Field(None, title="Until", description="End date (YYYY-MM-DD or Unix).")
    limit: Optional[str] = Field("25", title="Limit", description="Max results per page (1-100).")
    before: Optional[str] = Field(None, title="Before Cursor", description="Pagination cursor for the previous page.")
    after: Optional[str] = Field(None, title="After Cursor", description="Pagination cursor for the next page.")


async def _list_posts(c, token) -> Dict[str, Any]:
    return await _threads_request(token, "GET", f"/{_uid(c)}/threads", params={
        "fields": c.fields, "since": c.since, "until": c.until,
        "limit": c.limit, "before": c.before, "after": c.after,
    }, action_name="list_posts")


class ThreadsGhostPostsConfig(BaseModel):
    """List the authenticated user's ghost (ephemeral) posts."""
    operation: Literal["list_ghost_posts"] = Field(
        "list_ghost_posts",
        json_schema_extra={"const": "list_ghost_posts", "ui:hidden": True,
                           "x-category": "Posts", "x-is-trigger": False,
                           "x-display-name": "List Ghost Posts"},
        title="List Ghost Posts",
    )
    user_id: str = Field("me", title="Threads User", description="Threads user ID, or 'me'.")
    fields: str = Field(_MEDIA_FIELDS, title="Fields", description="Comma-separated fields to return.")
    since: Optional[str] = Field(None, title="Since", description="Start date (YYYY-MM-DD or Unix timestamp).")
    until: Optional[str] = Field(None, title="Until", description="End date (YYYY-MM-DD or Unix timestamp).")
    limit: Optional[str] = Field("25", title="Limit", description="Max results per page (1-100).")


async def _list_ghost_posts(c, token) -> Dict[str, Any]:
    return await _threads_request(token, "GET", f"/{_uid(c)}/ghost_posts", params={
        "fields": c.fields, "since": c.since, "until": c.until, "limit": c.limit,
    }, action_name="list_ghost_posts")


OPERATION_CONFIGS += [ThreadsGetPostConfig, ThreadsListPostsConfig, ThreadsGhostPostsConfig]
OPERATION_HANDLERS.update({
    "get_post": _get_post,
    "list_posts": _list_posts,
    "list_ghost_posts": _list_ghost_posts,
})


# ============================================================================
# Replies, conversations & moderation
# ============================================================================

_REPLY_FIELDS = ("id,text,username,permalink,timestamp,media_type,media_url,shortcode,"
                 "has_replies,root_post,replied_to,is_reply,is_reply_owned_by_me,hide_status,reply_audience")


class ThreadsGetRepliesConfig(BaseModel):
    """Get the top-level replies to a Threads post."""
    operation: Literal["get_replies"] = Field(
        "get_replies",
        json_schema_extra={"const": "get_replies", "ui:hidden": True,
                           "x-category": "Replies", "x-is-trigger": False,
                           "x-display-name": "Get Replies"},
        title="Get Replies",
    )
    media_id: str = Field(..., title="Media ID", description="The post ID whose replies to list.", json_schema_extra=_MEDIA_DYNAMIC)
    fields: str = Field(_REPLY_FIELDS, title="Fields", description="Comma-separated fields to return.")
    reverse: Optional[str] = Field(None, title="Reverse", description="'true' for reverse-chronological.",
                                   json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


async def _get_replies(c, token) -> Dict[str, Any]:
    return await _threads_request(token, "GET", f"/{c.media_id}/replies",
                                  params={"fields": c.fields, "reverse": c.reverse},
                                  action_name="get_replies")


class ThreadsConversationConfig(BaseModel):
    """Get the full (flattened, nested) conversation for a Threads post."""
    operation: Literal["get_conversation"] = Field(
        "get_conversation",
        json_schema_extra={"const": "get_conversation", "ui:hidden": True,
                           "x-category": "Replies", "x-is-trigger": False,
                           "x-display-name": "Get Conversation"},
        title="Get Conversation",
    )
    media_id: str = Field(..., title="Media ID", description="The root post ID.", json_schema_extra=_MEDIA_DYNAMIC)
    fields: str = Field(_REPLY_FIELDS, title="Fields", description="Comma-separated fields to return.")
    reverse: Optional[str] = Field(None, title="Reverse", description="Set to 'true' for reverse-chronological order.",
                                   json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


async def _get_conversation(c, token) -> Dict[str, Any]:
    return await _threads_request(token, "GET", f"/{c.media_id}/conversation",
                                  params={"fields": c.fields, "reverse": c.reverse},
                                  action_name="get_conversation")


class ThreadsMyRepliesConfig(BaseModel):
    """List replies authored by the authenticated user."""
    operation: Literal["list_my_replies"] = Field(
        "list_my_replies",
        json_schema_extra={"const": "list_my_replies", "ui:hidden": True,
                           "x-category": "Replies", "x-is-trigger": False,
                           "x-display-name": "List My Replies"},
        title="List My Replies",
    )
    user_id: str = Field("me", title="Threads User", description="Threads user ID, or 'me'.")
    fields: str = Field(_REPLY_FIELDS, title="Fields", description="Comma-separated fields to return.")
    since: Optional[str] = Field(None, title="Since", description="Start date (YYYY-MM-DD or Unix timestamp).")
    until: Optional[str] = Field(None, title="Until", description="End date (YYYY-MM-DD or Unix timestamp).")
    limit: Optional[str] = Field("25", title="Limit", description="Max results per page (1-100).")


async def _list_my_replies(c, token) -> Dict[str, Any]:
    return await _threads_request(token, "GET", f"/{_uid(c)}/replies", params={
        "fields": c.fields, "since": c.since, "until": c.until, "limit": c.limit,
    }, action_name="list_my_replies")


class ThreadsHideReplyConfig(BaseModel):
    """Hide or unhide a reply on one of the user's posts."""
    operation: Literal["hide_reply"] = Field(
        "hide_reply",
        json_schema_extra={"const": "hide_reply", "ui:hidden": True,
                           "x-category": "Replies", "x-is-trigger": False,
                           "x-display-name": "Hide / Unhide Reply"},
        title="Hide / Unhide Reply",
    )
    reply_id: str = Field(..., title="Reply ID", description="The reply ID to hide/unhide.")
    hide: str = Field("true", title="Hide", description="'true' to hide, 'false' to unhide.",
                      json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


async def _hide_reply(c, token) -> Dict[str, Any]:
    return await _threads_request(token, "POST", f"/{c.reply_id}/manage_reply",
                                  data={"hide": c.hide}, action_name="hide_reply")


class ThreadsPendingRepliesConfig(BaseModel):
    """List pending (approval-gated) replies on the user's posts."""
    operation: Literal["get_pending_replies"] = Field(
        "get_pending_replies",
        json_schema_extra={"const": "get_pending_replies", "ui:hidden": True,
                           "x-category": "Replies", "x-is-trigger": False,
                           "x-display-name": "Get Pending Replies"},
        title="Get Pending Replies",
    )
    media_id: str = Field(..., title="Media ID", description="The post ID whose pending replies to list.", json_schema_extra=_MEDIA_DYNAMIC)
    approval_status: Optional[str] = Field(
        None, title="Approval Status", description="Filter by status.",
        json_schema_extra={"enum": ["pending", "ignored"], "x-enum-searchable": True},
    )
    fields: str = Field(_REPLY_FIELDS + ",reply_approval_status", title="Fields", description="Comma-separated fields to return.")
    reverse: Optional[str] = Field(None, title="Reverse", description="Set to 'true' for reverse-chronological order.",
                                   json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


async def _get_pending_replies(c, token) -> Dict[str, Any]:
    return await _threads_request(token, "GET", f"/{c.media_id}/pending_replies", params={
        "approval_status": c.approval_status, "fields": c.fields, "reverse": c.reverse,
    }, action_name="get_pending_replies")


class ThreadsManagePendingReplyConfig(BaseModel):
    """Approve or ignore a pending reply."""
    operation: Literal["manage_pending_reply"] = Field(
        "manage_pending_reply",
        json_schema_extra={"const": "manage_pending_reply", "ui:hidden": True,
                           "x-category": "Replies", "x-is-trigger": False,
                           "x-display-name": "Approve / Ignore Pending Reply"},
        title="Approve / Ignore Pending Reply",
    )
    reply_id: str = Field(..., title="Reply ID", description="The pending reply ID.")
    approve: str = Field("true", title="Approve", description="'true' to approve, 'false' to ignore.",
                         json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


async def _manage_pending_reply(c, token) -> Dict[str, Any]:
    return await _threads_request(token, "POST", f"/{c.reply_id}/manage_pending_reply",
                                  data={"approve": c.approve}, action_name="manage_pending_reply")


OPERATION_CONFIGS += [ThreadsGetRepliesConfig, ThreadsConversationConfig, ThreadsMyRepliesConfig,
                      ThreadsHideReplyConfig, ThreadsPendingRepliesConfig, ThreadsManagePendingReplyConfig]
OPERATION_HANDLERS.update({
    "get_replies": _get_replies,
    "get_conversation": _get_conversation,
    "list_my_replies": _list_my_replies,
    "hide_reply": _hide_reply,
    "get_pending_replies": _get_pending_replies,
    "manage_pending_reply": _manage_pending_reply,
})


# ============================================================================
# Insights
# ============================================================================


class ThreadsPostInsightsConfig(BaseModel):
    """Get insights for a single Threads post."""
    operation: Literal["post_insights"] = Field(
        "post_insights",
        json_schema_extra={"const": "post_insights", "ui:hidden": True,
                           "x-category": "Insights", "x-is-trigger": False,
                           "x-display-name": "Post Insights"},
        title="Post Insights",
    )
    media_id: str = Field(..., title="Media ID", description="The post ID.", json_schema_extra=_MEDIA_DYNAMIC)
    metric: str = Field("views,likes,replies,reposts,quotes,shares", title="Metric",
                        description="Comma-separated metrics.")


async def _post_insights(c, token) -> Dict[str, Any]:
    return await _threads_request(token, "GET", f"/{c.media_id}/insights",
                                  params={"metric": c.metric}, action_name="post_insights")


class ThreadsAccountInsightsConfig(BaseModel):
    """Get account/user-level Threads insights."""
    operation: Literal["account_insights"] = Field(
        "account_insights",
        json_schema_extra={"const": "account_insights", "ui:hidden": True,
                           "x-category": "Insights", "x-is-trigger": False,
                           "x-display-name": "Account Insights"},
        title="Account Insights",
    )
    user_id: str = Field("me", title="Threads User", description="Threads user ID, or 'me'.")
    metric: str = Field("views,likes,replies,reposts,quotes,followers_count", title="Metric",
                        description="Comma-separated metrics.")
    since: Optional[str] = Field(None, title="Since", description="Unix timestamp (>= 1712991600).")
    until: Optional[str] = Field(None, title="Until", description="Unix timestamp.")
    breakdown: Optional[str] = Field(
        None, title="Breakdown", description="Required for follower_demographics.",
        json_schema_extra={"enum": ["country", "city", "age", "gender"], "x-enum-searchable": True},
    )


async def _account_insights(c, token) -> Dict[str, Any]:
    return await _threads_request(token, "GET", f"/{_uid(c)}/threads_insights", params={
        "metric": c.metric, "since": c.since, "until": c.until, "breakdown": c.breakdown,
    }, action_name="account_insights")


OPERATION_CONFIGS += [ThreadsPostInsightsConfig, ThreadsAccountInsightsConfig]
OPERATION_HANDLERS.update({
    "post_insights": _post_insights,
    "account_insights": _account_insights,
})


# ============================================================================
# Search, mentions & location
# ============================================================================


class ThreadsKeywordSearchConfig(BaseModel):
    """Search public Threads posts by keyword or tag."""
    operation: Literal["keyword_search"] = Field(
        "keyword_search",
        json_schema_extra={"const": "keyword_search", "ui:hidden": True,
                           "x-category": "Discovery", "x-is-trigger": False,
                           "x-display-name": "Keyword Search"},
        title="Keyword Search",
    )
    q: str = Field(..., title="Query", description="Search keyword or tag.")
    search_type: Optional[str] = Field(
        None, title="Search Type", description="Ranking of results.", json_schema_extra={"enum": ["TOP", "RECENT"], "x-enum-searchable": True})
    search_mode: Optional[str] = Field(
        None, title="Search Mode", description="Search by keyword or by hashtag.", json_schema_extra={"enum": ["KEYWORD", "TAG"], "x-enum-searchable": True})
    media_type: Optional[str] = Field(
        None, title="Media Type", description="Filter results by media type.", json_schema_extra={"enum": ["TEXT", "IMAGE", "VIDEO"], "x-enum-searchable": True})
    author_username: Optional[str] = Field(None, title="Author Username", description="Filter to posts by this exact username.")
    since: Optional[str] = Field(None, title="Since", description="Start date (YYYY-MM-DD or Unix timestamp).")
    until: Optional[str] = Field(None, title="Until", description="End date (YYYY-MM-DD or Unix timestamp).")
    limit: Optional[str] = Field("25", title="Limit", description="1-100.")
    fields: str = Field("id,text,username,permalink,timestamp,media_type", title="Fields", description="Comma-separated fields to return.")


async def _keyword_search(c, token) -> Dict[str, Any]:
    return await _threads_request(token, "GET", "/keyword_search", params={
        "q": c.q, "search_type": c.search_type, "search_mode": c.search_mode,
        "media_type": c.media_type, "author_username": c.author_username,
        "since": c.since, "until": c.until, "limit": c.limit, "fields": c.fields,
    }, action_name="keyword_search")


class ThreadsMentionsConfig(BaseModel):
    """List public Threads posts that mention the authenticated user."""
    operation: Literal["get_mentions"] = Field(
        "get_mentions",
        json_schema_extra={"const": "get_mentions", "ui:hidden": True,
                           "x-category": "Discovery", "x-is-trigger": False,
                           "x-display-name": "Get Mentions"},
        title="Get Mentions",
    )
    user_id: str = Field("me", title="Threads User", description="Threads user ID, or 'me'.")
    fields: str = Field("id,text,username,permalink,timestamp,media_type", title="Fields", description="Comma-separated fields to return.")
    since: Optional[str] = Field(None, title="Since", description="Start date (YYYY-MM-DD or Unix timestamp).")
    until: Optional[str] = Field(None, title="Until", description="End date (YYYY-MM-DD or Unix timestamp).")
    limit: Optional[str] = Field("25", title="Limit", description="Max results per page (1-100).")


async def _get_mentions(c, token) -> Dict[str, Any]:
    return await _threads_request(token, "GET", f"/{_uid(c)}/mentions", params={
        "fields": c.fields, "since": c.since, "until": c.until, "limit": c.limit,
    }, action_name="get_mentions")


class ThreadsLocationSearchConfig(BaseModel):
    """Search for a location to tag on a post."""
    operation: Literal["location_search"] = Field(
        "location_search",
        json_schema_extra={"const": "location_search", "ui:hidden": True,
                           "x-category": "Discovery", "x-is-trigger": False,
                           "x-display-name": "Location Search"},
        title="Location Search",
    )
    q: Optional[str] = Field(None, title="Query", description="Location search text.")
    latitude: Optional[str] = Field(None, title="Latitude", description="Latitude to bias the location search.")
    longitude: Optional[str] = Field(None, title="Longitude", description="Longitude to bias the location search.")
    fields: str = Field("id,name,address,city,country,latitude,longitude", title="Fields", description="Comma-separated fields to return.")


async def _location_search(c, token) -> Dict[str, Any]:
    return await _threads_request(token, "GET", "/location_search", params={
        "q": c.q, "latitude": c.latitude, "longitude": c.longitude, "fields": c.fields,
    }, action_name="location_search")


class ThreadsGetLocationConfig(BaseModel):
    """Get a Threads location object by ID."""
    operation: Literal["get_location"] = Field(
        "get_location",
        json_schema_extra={"const": "get_location", "ui:hidden": True,
                           "x-category": "Discovery", "x-is-trigger": False,
                           "x-display-name": "Get Location"},
        title="Get Location",
    )
    location_id: str = Field(..., title="Location ID", description="The Threads location object ID.")
    fields: str = Field("id,name,address,city,country,latitude,longitude,postal_code", title="Fields", description="Comma-separated fields to return.")


async def _get_location(c, token) -> Dict[str, Any]:
    return await _threads_request(token, "GET", f"/{c.location_id}", params={"fields": c.fields},
                                  action_name="get_location")


OPERATION_CONFIGS += [ThreadsKeywordSearchConfig, ThreadsMentionsConfig,
                      ThreadsLocationSearchConfig, ThreadsGetLocationConfig]
OPERATION_HANDLERS.update({
    "keyword_search": _keyword_search,
    "get_mentions": _get_mentions,
    "location_search": _location_search,
    "get_location": _get_location,
})


# ============================================================================
# Generic escape hatch
# ============================================================================


class ThreadsRequestConfig(BaseModel):
    """Make an arbitrary Threads Graph API request (escape hatch)."""
    operation: Literal["threads_request"] = Field(
        "threads_request",
        json_schema_extra={"const": "threads_request", "ui:hidden": True,
                           "x-category": "Advanced", "x-is-trigger": False,
                           "x-display-name": "Custom Threads Request"},
        title="Custom Threads Request",
    )
    endpoint: str = Field(..., title="Endpoint", description="Path after the version, e.g. /me/threads.")
    method: str = Field("GET", title="Method", description="HTTP method for the request.",
                        json_schema_extra={"enum": ["GET", "POST", "DELETE"], "x-enum-searchable": True})
    params_json: str = Field("{}", title="Query Params (JSON)", description="Query parameters as a JSON object, e.g. {\"limit\": 5}.",
                             json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    data_json: str = Field("{}", title="Body (JSON)", description="Request body as a JSON object.",
                           json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _threads_custom_request(c, token) -> Dict[str, Any]:
    endpoint = c.endpoint if c.endpoint.startswith("/") else f"/{c.endpoint}"
    params = _parse_json_field(c.params_json, "Query Params") or {}
    data = _parse_json_field(c.data_json, "Body") or {}
    return await _threads_request(token, c.method, endpoint, params=params or None,
                                  data=data or None, action_name="threads_request")


OPERATION_CONFIGS += [ThreadsRequestConfig]
OPERATION_HANDLERS.update({"threads_request": _threads_custom_request})


# ============================================================================
# Webhook triggers (per topic)
# ============================================================================

# Threads webhook topics (field -> display).
THREADS_WEBHOOK_TOPICS = [
    ("replies", "On Reply"),
    ("mentions", "On Mention"),
    ("publish", "On Publish"),
    ("delete", "On Delete"),
]


class _ThreadsWebhookTrigger(BaseModel):
    """Base config for Threads webhook triggers."""
    webhook_url: Optional[str] = Field(
        None, title="Callback URL", description="Paste this into your app's Threads webhook config.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True},
    )
    verify_token: Optional[str] = Field(
        None, title="Verify Token", description="Token Meta echoes during the subscription handshake.")
    app_secret: Optional[str] = Field(
        None, title="App Secret", description="Threads app secret for X-Hub-Signature-256 verification.",
        json_schema_extra={"ui:widget": "password"})


def _threads_topic_op(topic: str) -> str:
    return "on_" + topic


def _make_threads_trigger(op: str, topic: str, display: str) -> type:
    return create_model(
        f"ThreadsTrigger_{op}",
        __base__=_ThreadsWebhookTrigger,
        operation=(Literal[op], Field(
            op, json_schema_extra={"const": op, "ui:hidden": True,
                                   "x-category": "Triggers", "x-is-trigger": True,
                                   "x-webhook-topic": topic, "x-display-name": display},
            title=display)),
    )


THREADS_TRIGGER_SPECS = [(_threads_topic_op(t), t, d) for t, d in THREADS_WEBHOOK_TOPICS]
THREADS_TRIGGER_SPECS.append(("on_any_threads_event", "*", "On Any Threads Event"))
THREADS_TRIGGER_EVENT = {op: topic for op, topic, _ in THREADS_TRIGGER_SPECS}
THREADS_TRIGGER_CONFIGS = {op: _make_threads_trigger(op, topic, disp) for op, topic, disp in THREADS_TRIGGER_SPECS}


# ============================================================================
# Config union
# ============================================================================


def _dedup_ops(configs: List[type]) -> List[type]:
    """Keep the LAST config registered per operation literal."""
    by_op: Dict[str, type] = {}
    for cfg in configs:
        op = cfg.model_fields["operation"].default
        by_op[op] = cfg
    return list(by_op.values())


ThreadsConfig = Annotated[
    Union[tuple(  # type: ignore[misc]
        [*THREADS_TRIGGER_CONFIGS.values(), *_dedup_ops(OPERATION_CONFIGS)]
    )],
    Discriminator("operation"),
]


class ThreadsNodeConfig(NodeConfig[ThreadsConfig, ThreadsCredential]):
    pass


# ============================================================================
# Node
# ============================================================================


class ThreadsNode(WorkflowNode):
    """Threads (by Meta) automation node."""

    edit_examples = [
        "Publish a text post to Threads",
        "Reply to a Threads post",
        "Pull the insights for my latest Threads post",
        "Search Threads for a keyword",
        "Trigger a workflow when someone replies to my Threads post",
    ]

    scope_registry = THREADS_SCOPES
    connection_evidence = ConnectionEvidence(
        field="media_id",
        noun="posts",
    )

    @classmethod
    def get_config_model(cls):
        return ThreadsNodeConfig

    # -- webhook mechanics -------------------------------------------------
    @classmethod
    def verify_webhook_signature(cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]) -> bool:
        sig = headers.get("x-hub-signature-256") or headers.get("X-Hub-Signature-256")
        app_secret = (config or {}).get("app_secret")
        if not app_secret:
            return sig is None or (sig.startswith("sha256=") and len(sig) > len("sha256="))
        if not sig or not sig.startswith("sha256="):
            return False
        expected = hmac.new(str(app_secret).encode("utf-8"), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig[len("sha256="):], expected)

    @classmethod
    def handle_webhook_handshake(cls, body: bytes, headers: Dict[str, str], config: Optional[Dict[str, Any]] = None):
        query = headers.get("__query_params__") or {}
        if headers.get("__method__") != "GET" or not isinstance(query, dict):
            return None
        if query.get("hub.mode") != "subscribe":
            return None
        expected_token = (config or {}).get("verify_token")
        if expected_token and query.get("hub.verify_token") != expected_token:
            return None
        challenge = query.get("hub.challenge")
        if challenge is None:
            return None
        return PlainTextResponse(content=str(challenge), status_code=200)

    @staticmethod
    def _payload_topics(payload: Dict[str, Any]) -> List[str]:
        """Extract the Threads webhook topic(s) from a delivery."""
        if not isinstance(payload, dict):
            return []
        topics: List[str] = []
        top = payload.get("topic") or payload.get("field")
        if top:
            topics.append(str(top))
        for entry in payload.get("entry") or []:
            if not isinstance(entry, dict):
                continue
            for change in entry.get("changes") or []:
                if isinstance(change, dict) and change.get("field"):
                    topics.append(str(change["field"]))
        seen: set = set()
        return [t for t in topics if not (t in seen or seen.add(t))]

    @classmethod
    def filter_trigger_payload(cls, payload: Dict[str, Any], config: Dict[str, Any]) -> bool:
        topic = THREADS_TRIGGER_EVENT.get((config or {}).get("operation"), "*")
        if topic == "*":
            return True
        topics = cls._payload_topics(payload)
        if not topics:
            return True
        return topic in topics

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        if not credential_data or credential_data.get("credential_type") != "threads_oauth":
            return credential_data
        from nodes.core.oauth_refresh import freshen_oauth_credential
        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token, is_expired=is_token_expired,
            refresh_token_key="access_token", provider="threads",
        )

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context=None,
        page_token=None,
        search=None,
    ) -> Dict[str, Any]:
        """Populate the media_id dropdown from the user's recent Threads posts.

        Caller convention: the pre-loaded/freshened credential dict is passed as
        credential_data (the old user_id/config_data/credential_ids signature
        raised "unexpected keyword argument 'credential_data'" and broke the dropdown).
        """
        if field_name != "media_id":
            return {"options": []}
        access_token = (credential_data or {}).get("access_token")
        if not access_token:
            return {"options": []}

        result = await _threads_request(
            access_token, "GET", "/me/threads",
            params={"fields": "id,text,media_type,timestamp", "limit": "25"},
            action_name="list_posts",
        )
        if result.get("status") != "success":
            return {"options": []}
        data = result.get("data") or {}
        items = data.get("data", []) if isinstance(data, dict) else []
        options = []
        for item in items:
            if not isinstance(item, dict):
                continue
            value = item.get("id")
            text = (item.get("text") or "").strip().replace("\n", " ")
            label = (text[:60] + "…") if len(text) > 60 else (text or item.get("media_type") or str(value))
            if value is not None:
                options.append({"label": f"{label}", "value": str(value)})
        return {"options": options}

    async def _get_access_token(self, credentials: ThreadsCredential) -> str:
        expires_at = getattr(credentials, "expires_at", None)
        if not expires_at or not isinstance(credentials, ThreadsOAuthCredential):
            return credentials.access_token
        if not is_token_expired(expires_at):
            return credentials.access_token
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        cred_dict = credentials.model_dump()
        await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id, credential=cred_dict,
            refresh=refresh_access_token, is_expired=is_token_expired,
            refresh_token_key="access_token", provider="threads",
        )
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        return credentials.access_token

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, ThreadsNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        if isinstance(op, tuple(THREADS_TRIGGER_CONFIGS.values())):
            return {
                "status": "success",
                "action": op.operation,
                "data": {**inputs, "webhook_url": op.webhook_url},
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Connect your Threads account.")
        access_token = await self._get_access_token(credentials)

        handler = OPERATION_HANDLERS.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")
        result = await handler(op, access_token)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result
