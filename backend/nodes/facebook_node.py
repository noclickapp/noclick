"""
Facebook (Pages + Messenger) automation node.

Covers the Facebook Pages Graph API and the Messenger Platform — the Facebook
product surface. Instagram, WhatsApp, Threads, and Meta Ads/Marketing live in
their own nodes.

Coverage:
- Pages: page node read/update, feed/posts (publish, scheduled, read, edit,
  delete, attachments, shares), photos/albums, videos/live videos, comments
  (CRUD, hide, private replies), likes/reactions, page + post insights,
  management (roles/settings/tabs/blocked/events/ratings/tagged/conversations/
  call-to-actions), webhook subscriptions.
- Messenger: Send API (text/attachment/template/quick replies/sender actions/
  message tags), attachment upload, Messenger Profile (get started / persistent
  menu / greeting / ice breakers), user profile, handover protocol, custom labels.
- Generic escape hatch: arbitrary Graph request.
- Webhook triggers (per field): feed, mention, ratings, messages, message
  postbacks/reads/deliveries/reactions, messaging referrals, standby.

Authentication: Facebook Login OAuth (facebook_oauth — a user token from which
Page tokens are derived) or a manually supplied Page/user access token
(facebook_access_token), with optional appsecret_proof.

API Base URL: https://graph.facebook.com/v25.0
Docs: https://developers.facebook.com/docs/graph-api/reference/page
"""

import hashlib
import hmac
import json
import logging
import time
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model
from starlette.responses import PlainTextResponse

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.oauth.facebook_oauth import is_token_expired, refresh_access_token
from nodes.scopes.meta import FACEBOOK_SCOPES
from utils.ssrf import assert_exact_url_origin

logger = logging.getLogger(__name__)

GRAPH_API_VERSION = "v25.0"
FB_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"
FB_RUPLOAD_ORIGIN = "https://rupload.facebook.com"

FACEBOOK_OAUTH_SCOPES = [
    "public_profile",
    "email",
    "pages_show_list",
    "pages_read_engagement",
    "pages_read_user_content",
    "pages_manage_posts",
    "pages_manage_engagement",
    "pages_manage_metadata",
    "pages_messaging",
    "read_insights",
    # business_management deliberately NOT requested: no operation requires it
    # (scope-registry verified) and it is excluded from App Review — requesting
    # an unapproved permission fails the login dialog for public users.
    # NOTE: pages_user_locale / pages_user_gender / pages_user_timezone are NOT
    # login-dialog scopes — passing them in the OAuth `scope` param fails with
    # "Invalid Scope". They're granted at the app level via App Review (the
    # Messenger use case); the User Profile API returns those fields once
    # approved, so get_user_profile needs no login scope for them.
]


# ============================================================================
# Credentials
# ============================================================================


class FacebookOAuthCredential(BaseModel):
    """Facebook Login OAuth token (user token; Page tokens are derived from it)."""

    credential_type: Literal["facebook_oauth"] = Field(
        "facebook_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ..., title="Access Token", description="Long-lived Facebook user or Page access token",
        json_schema_extra={"ui:widget": "password"},
    )
    expires_at: Optional[str] = Field(None, title="Token Expiry", description="ISO 8601 expiry of the long-lived token")
    email: Optional[str] = Field(None, title="Account Email", description="Connected Facebook account email")
    facebook_user_id: Optional[str] = Field(None, title="Facebook User ID", description="Connected Facebook user ID")

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://developers.facebook.com/apps/",
            "x-credential-type": "oauth",
            "x-oauth-provider": "facebook_pages",
            # Hidden until Meta approves our OAuth app — existing OAuth credentials
            # still parse/execute; new connections use the access-token credential below.
            # The PostHog flag reveals it for allow-listed accounts (e.g. Meta reviewers)
            # so the live connect flow can be demoed/recorded before Advanced Access is granted.
            "x-credential-hidden": True,
            "x-credential-preview-flag": "meta-oauth-preview",
            "x-oauth-scopes": FACEBOOK_OAUTH_SCOPES,
        }
    )


class FacebookAccessTokenCredential(BaseModel):
    """Manually supplied Facebook Page or user access token (no OAuth popup)."""

    credential_type: Literal["facebook_access_token"] = Field(
        "facebook_access_token", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ..., title="Access Token", description="Facebook Page or user access token",
        json_schema_extra={"ui:widget": "password"},
    )
    expires_at: Optional[str] = Field(None, title="Token Expiry", description="ISO 8601 expiry, if the token expires")
    app_secret: Optional[str] = Field(
        None, title="App Secret (Optional)",
        description="App secret for appsecret_proof on apps that require secure server requests.",
        json_schema_extra={"ui:widget": "password"},
    )


FacebookCredential = Union[FacebookOAuthCredential, FacebookAccessTokenCredential]


# ============================================================================
# Request helper
# ============================================================================


def _appsecret_proof(access_token: str, app_secret: str) -> str:
    return hmac.new(app_secret.encode("utf-8"), access_token.encode("utf-8"), hashlib.sha256).hexdigest()


async def _fb_request(
    access_token: str,
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
    app_secret: Optional[str] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Authenticated Graph API request → structured result. Reads use query
    params; writes use form-encoded data. Bearer token auth + optional
    appsecret_proof."""
    url = f"{FB_API_BASE}{endpoint}"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {k: v for k, v in (params or {}).items() if v not in (None, "")}
    if app_secret:
        params["appsecret_proof"] = _appsecret_proof(access_token, app_secret)
    if not params:
        params = None
    if data:
        data = {k: v for k, v in data.items() if v not in (None, "")}

    start = time.time()
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.request(method=method, url=url, headers=headers, params=params, data=data)
            api_ms = round((time.time() - start) * 1000, 2)
            if response.status_code >= 400:
                try:
                    err = response.json()
                    eo = err.get("error", {})
                    message = eo.get("message") if isinstance(eo, dict) else err.get("message", str(err))
                except Exception:
                    message = response.text
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[FacebookNode] API error ({action_name}): {message}")
                return {"status": "error", "action": action_name, "error": message,
                        "status_code": response.status_code, "timing_ms": {"api_request": api_ms}}
            payload: Any = {"success": True} if response.status_code == 204 else (
                response.json() if response.content else {"success": True})
            return {"status": "success", "action": action_name, "data": payload,
                    "status_code": response.status_code, "timing_ms": {"api_request": api_ms}}
        except httpx.TimeoutException:
            return {"status": "error", "action": action_name, "error": "Request timed out",
                    "status_code": 408, "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)}}
        except Exception as e:
            msg = str(e).encode("ascii", errors="replace").decode("ascii")
            logger.error(f"[FacebookNode] Request failed ({action_name}): {msg}")
            return {"status": "error", "action": action_name, "error": msg,
                    "status_code": 500, "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)}}


def _parse_json_field(raw: Optional[str], label: str) -> Any:
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except Exception as e:
        raise ValueError(f"{label} must be valid JSON: {e}")


OPERATION_CONFIGS: List[type] = []
OPERATION_HANDLERS: Dict[str, Any] = {}

# Shared dynamic-options spec for Page-id fields (backed by /me/accounts).
_PAGE_DYNAMIC = {
    "x-dynamic-options": {
        "field_name": "page_id",
        "placeholder": "Select a Page...",
        "searchable": True,
        "allow_custom": True,
        "custom_placeholder": "Or paste a Page ID",
    }
}


def _reg(cfg: type, op: str, handler) -> None:
    OPERATION_CONFIGS.append(cfg)
    OPERATION_HANDLERS[op] = handler


# ============================================================================
# Account / profile
# ============================================================================


class FbGetMeConfig(BaseModel):
    """Get the authenticated user's basic profile."""
    operation: Literal["get_me"] = Field("get_me", json_schema_extra={
        "const": "get_me", "x-category": "Account",
        "x-is-trigger": False, "x-display-name": "Get My Profile"}, title="Get My Profile")
    fields: str = Field("id,name,email", title="Fields", description="Comma-separated profile fields.")


async def _get_me(c, token, secret):
    return await _fb_request(token, "GET", "/me", params={"fields": c.fields}, app_secret=secret, action_name="get_me")


class FbListPagesConfig(BaseModel):
    """List the Facebook Pages the user manages (with Page access tokens)."""
    operation: Literal["list_pages"] = Field("list_pages", json_schema_extra={
        "const": "list_pages", "x-category": "Account",
        "x-is-trigger": False, "x-display-name": "List My Pages"}, title="List My Pages")
    fields: str = Field("id,name,access_token,category,tasks", title="Fields", description="Comma-separated Page fields.")


async def _list_pages(c, token, secret):
    return await _fb_request(token, "GET", "/me/accounts", params={"fields": c.fields}, app_secret=secret, action_name="list_pages")


# --- Page access token resolution --------------------------------------------
# Page-scoped Graph endpoints (feed/insights/comments/messages/webhooks/…) require
# a PAGE access token, not the connected user's token. The stored credential holds
# the USER token; we exchange it for the per-Page token via /me/accounts and use
# that for page-scoped ops. Without this every Page WRITE/insights/messaging call
# fails with "(#210) A page access token is required" / "(#190) must be called
# with a Page Access Token" even though the correct scopes are granted.

# Object ops that act on a Page-owned object (no page_id field of their own).
_PAGE_SCOPED_OBJECT_OPS = {
    "get_post", "update_post", "delete_post", "get_post_attachments", "post_insights",
    "read_comments", "create_comment", "update_comment", "delete_comment", "hide_comment",
    "get_reactions", "like_object", "unlike_object",
    # keyed by recipient PSID — no page_id field, resolve via the single
    # managed Page (page id isn't recoverable from that id format).
    "get_user_profile",
}


async def _resolve_page_token_map(user_token: str, secret: Optional[str]) -> Dict[str, str]:
    """Return {page_id: page_access_token} for the user's managed Pages.

    Best-effort: returns {} if the token can't list Pages (e.g. the credential is
    already a Page token), so callers cleanly fall back to the provided token.
    """
    try:
        res = await _fb_request(user_token, "GET", "/me/accounts",
                                params={"fields": "id,access_token"}, app_secret=secret,
                                action_name="_resolve_page_tokens")
        data = res.get("data")
        rows = data.get("data") if isinstance(data, dict) else (data if isinstance(data, list) else [])
        return {r["id"]: r["access_token"] for r in (rows or []) if r.get("id") and r.get("access_token")}
    except Exception:
        return {}


def _target_page_id(op) -> Optional[str]:
    """The Page id a page-scoped op targets: its page_id, else the page prefix of
    its post_id/object_id (Page object ids are '{page_id}_{...}')."""
    pid = getattr(op, "page_id", None)
    if pid:
        return pid
    for attr in ("post_id", "object_id"):
        v = getattr(op, attr, None)
        if isinstance(v, str) and "_" in v:
            return v.split("_", 1)[0]
    return None


async def _token_for_op(op, user_token: str, secret: Optional[str]) -> str:
    """Page token for page-scoped ops (falls back to the user token when the Page
    can't be resolved — e.g. single-Page comment ops, or a Page-token credential)."""
    is_page_scoped = getattr(op, "page_id", None) is not None or op.operation in _PAGE_SCOPED_OBJECT_OPS
    if not is_page_scoped:
        return user_token
    page_map = await _resolve_page_token_map(user_token, secret)
    if not page_map:
        return user_token
    target = _target_page_id(op)
    if target and target in page_map:
        return page_map[target]
    if len(page_map) == 1:                       # only one managed Page → unambiguous
        return next(iter(page_map.values()))
    return user_token


_reg(FbGetMeConfig, "get_me", _get_me)
_reg(FbListPagesConfig, "list_pages", _list_pages)


# ============================================================================
# Page node
# ============================================================================


class FbGetPageConfig(BaseModel):
    """Get a Page's fields/details."""
    operation: Literal["get_page"] = Field("get_page", json_schema_extra={
        "const": "get_page", "x-category": "Pages",
        "x-is-trigger": False, "x-display-name": "Get Page"}, title="Get Page")
    page_id: str = Field(..., title="Page", description="The Page ID.", json_schema_extra=_PAGE_DYNAMIC)
    fields: str = Field("id,name,about,category,fan_count,link,phone,website,emails,location",
                        title="Fields", description="Comma-separated Page fields to return.")


async def _get_page(c, token, secret):
    return await _fb_request(token, "GET", f"/{c.page_id}", params={"fields": c.fields}, app_secret=secret, action_name="get_page")


class FbUpdatePageConfig(BaseModel):
    """Update a Page's settings/metadata (about, phone, website, hours, etc.)."""
    operation: Literal["update_page"] = Field("update_page", json_schema_extra={
        "const": "update_page", "x-category": "Pages",
        "x-is-trigger": False, "x-display-name": "Update Page"}, title="Update Page")
    page_id: str = Field(..., title="Page", description="The Page ID.", json_schema_extra=_PAGE_DYNAMIC)
    fields_json: str = Field("{}", title="Fields (JSON)",
                             description='Fields to update, e.g. {"about":"...","phone":"...","website":"..."}.',
                             json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _update_page(c, token, secret):
    body = _parse_json_field(c.fields_json, "Fields") or {}
    return await _fb_request(token, "POST", f"/{c.page_id}", data=body, app_secret=secret, action_name="update_page")


_reg(FbGetPageConfig, "get_page", _get_page)
_reg(FbUpdatePageConfig, "update_page", _update_page)


# ============================================================================
# Feed / posts
# ============================================================================


class FbPublishPostConfig(BaseModel):
    """Publish (or schedule) a post to a Page's feed."""
    operation: Literal["publish_post"] = Field("publish_post", json_schema_extra={
        "const": "publish_post", "x-category": "Posts",
        "x-is-trigger": False, "x-display-name": "Publish Post"}, title="Publish Post")
    page_id: str = Field(..., title="Page", description="The Page ID.", json_schema_extra=_PAGE_DYNAMIC)
    message: Optional[str] = Field(None, title="Message", description="Post text.")
    link: Optional[str] = Field(None, title="Link", description="URL to attach (with link preview).")
    scheduled_publish_time: Optional[str] = Field(
        None, title="Scheduled Time", description="Unix timestamp to schedule; sets published=false.")
    body_json: str = Field("{}", title="Additional Fields (JSON)",
                           description="Extra feed fields (place, tags, targeting, child_attachments).",
                           json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _publish_post(c, token, secret):
    data = {"message": c.message, "link": c.link}
    if c.scheduled_publish_time:
        data["published"] = "false"
        data["scheduled_publish_time"] = c.scheduled_publish_time
    data.update(_parse_json_field(c.body_json, "Additional Fields") or {})
    return await _fb_request(token, "POST", f"/{c.page_id}/feed", data=data, app_secret=secret, action_name="publish_post")


class FbReadFeedConfig(BaseModel):
    """Read a Page's feed (posts, statuses, links)."""
    operation: Literal["read_feed"] = Field("read_feed", json_schema_extra={
        "const": "read_feed", "x-category": "Posts",
        "x-is-trigger": False, "x-display-name": "Read Feed"}, title="Read Feed")
    page_id: str = Field(..., title="Page", description="The Page ID.", json_schema_extra=_PAGE_DYNAMIC)
    fields: str = Field("id,message,created_time,permalink_url,from", title="Fields", description="Comma-separated fields.")
    limit: Optional[str] = Field("25", title="Limit", description="Max posts per page.")
    since: Optional[str] = Field(None, title="Since", description="Start date (Unix or YYYY-MM-DD).")
    until: Optional[str] = Field(None, title="Until", description="End date (Unix or YYYY-MM-DD).")


async def _read_feed(c, token, secret):
    return await _fb_request(token, "GET", f"/{c.page_id}/feed", params={
        "fields": c.fields, "limit": c.limit, "since": c.since, "until": c.until}, app_secret=secret, action_name="read_feed")


class FbListPostsConfig(BaseModel):
    """List a Page's own published posts."""
    operation: Literal["list_posts"] = Field("list_posts", json_schema_extra={
        "const": "list_posts", "x-category": "Posts",
        "x-is-trigger": False, "x-display-name": "List Posts"}, title="List Posts")
    page_id: str = Field(..., title="Page", description="The Page ID.", json_schema_extra=_PAGE_DYNAMIC)
    fields: str = Field("id,message,created_time,permalink_url", title="Fields", description="Comma-separated fields.")
    limit: Optional[str] = Field("25", title="Limit", description="Max posts per page.")


async def _list_posts(c, token, secret):
    return await _fb_request(token, "GET", f"/{c.page_id}/posts", params={"fields": c.fields, "limit": c.limit},
                             app_secret=secret, action_name="list_posts")


class FbGetPostConfig(BaseModel):
    """Get a single post."""
    operation: Literal["get_post"] = Field("get_post", json_schema_extra={
        "const": "get_post", "x-category": "Posts",
        "x-is-trigger": False, "x-display-name": "Get Post"}, title="Get Post")
    post_id: str = Field(..., title="Post ID", description="The post ID (e.g. {page-id}_{post-id}).")
    fields: str = Field("id,message,created_time,permalink_url,attachments,shares", title="Fields",
                        description="Comma-separated fields.")


async def _get_post(c, token, secret):
    return await _fb_request(token, "GET", f"/{c.post_id}", params={"fields": c.fields}, app_secret=secret, action_name="get_post")


class FbUpdatePostConfig(BaseModel):
    """Edit a post's message."""
    operation: Literal["update_post"] = Field("update_post", json_schema_extra={
        "const": "update_post", "x-category": "Posts",
        "x-is-trigger": False, "x-display-name": "Update Post"}, title="Update Post")
    post_id: str = Field(..., title="Post ID", description="The post ID to edit.")
    message: str = Field(..., title="Message", description="New post text.")


async def _update_post(c, token, secret):
    return await _fb_request(token, "POST", f"/{c.post_id}", data={"message": c.message}, app_secret=secret, action_name="update_post")


class FbDeletePostConfig(BaseModel):
    """Delete a post."""
    operation: Literal["delete_post"] = Field("delete_post", json_schema_extra={
        "const": "delete_post", "x-category": "Posts",
        "x-is-trigger": False, "x-display-name": "Delete Post"}, title="Delete Post")
    post_id: str = Field(..., title="Post ID", description="The post ID to delete.")


async def _delete_post(c, token, secret):
    return await _fb_request(token, "DELETE", f"/{c.post_id}", app_secret=secret, action_name="delete_post")


class FbPostAttachmentsConfig(BaseModel):
    """Get a post's attachments (media/links)."""
    operation: Literal["get_post_attachments"] = Field("get_post_attachments", json_schema_extra={
        "const": "get_post_attachments", "x-category": "Posts",
        "x-is-trigger": False, "x-display-name": "Get Post Attachments"}, title="Get Post Attachments")
    post_id: str = Field(..., title="Post ID", description="The post ID.")


async def _get_post_attachments(c, token, secret):
    return await _fb_request(token, "GET", f"/{c.post_id}/attachments", app_secret=secret, action_name="get_post_attachments")


_reg(FbPublishPostConfig, "publish_post", _publish_post)
_reg(FbReadFeedConfig, "read_feed", _read_feed)
_reg(FbListPostsConfig, "list_posts", _list_posts)
_reg(FbGetPostConfig, "get_post", _get_post)
_reg(FbUpdatePostConfig, "update_post", _update_post)
_reg(FbDeletePostConfig, "delete_post", _delete_post)
_reg(FbPostAttachmentsConfig, "get_post_attachments", _get_post_attachments)


# ============================================================================
# Photos / albums / videos
# ============================================================================


class FbUploadPhotoConfig(BaseModel):
    """Upload a photo to a Page (by URL)."""
    operation: Literal["upload_photo"] = Field("upload_photo", json_schema_extra={
        "const": "upload_photo", "x-category": "Media",
        "x-is-trigger": False, "x-display-name": "Upload Photo"}, title="Upload Photo")
    page_id: str = Field(..., title="Page", description="The Page ID.", json_schema_extra=_PAGE_DYNAMIC)
    url: str = Field(..., title="Image URL", description="Publicly reachable image URL.")
    caption: Optional[str] = Field(None, title="Caption", description="Photo caption.")
    published: Optional[str] = Field("true", title="Published",
                                     json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
                                     description="Publish now, or upload unpublished for later attachment.")


async def _upload_photo(c, token, secret):
    return await _fb_request(token, "POST", f"/{c.page_id}/photos",
                             data={"url": c.url, "caption": c.caption, "published": c.published},
                             app_secret=secret, action_name="upload_photo")


class FbListAlbumsConfig(BaseModel):
    """List a Page's photo albums."""
    operation: Literal["list_albums"] = Field("list_albums", json_schema_extra={
        "const": "list_albums", "x-category": "Media",
        "x-is-trigger": False, "x-display-name": "List Albums"}, title="List Albums")
    page_id: str = Field(..., title="Page", description="The Page ID.", json_schema_extra=_PAGE_DYNAMIC)
    fields: str = Field("id,name,count,created_time", title="Fields", description="Comma-separated album fields.")


async def _list_albums(c, token, secret):
    return await _fb_request(token, "GET", f"/{c.page_id}/albums", params={"fields": c.fields}, app_secret=secret, action_name="list_albums")


class FbUploadVideoConfig(BaseModel):
    """Upload a video to a Page (by URL)."""
    operation: Literal["upload_video"] = Field("upload_video", json_schema_extra={
        "const": "upload_video", "x-category": "Media",
        "x-is-trigger": False, "x-display-name": "Upload Video"}, title="Upload Video")
    page_id: str = Field(..., title="Page", description="The Page ID.", json_schema_extra=_PAGE_DYNAMIC)
    file_url: str = Field(..., title="Video URL", description="Publicly reachable video URL.")
    title: Optional[str] = Field(None, title="Title", description="Video title.")
    description: Optional[str] = Field(None, title="Description", description="Video description.")


async def _upload_video(c, token, secret):
    return await _fb_request(token, "POST", f"/{c.page_id}/videos",
                             data={"file_url": c.file_url, "title": c.title, "description": c.description},
                             app_secret=secret, action_name="upload_video")


class FbListVideosConfig(BaseModel):
    """List a Page's videos."""
    operation: Literal["list_videos"] = Field("list_videos", json_schema_extra={
        "const": "list_videos", "x-category": "Media",
        "x-is-trigger": False, "x-display-name": "List Videos"}, title="List Videos")
    page_id: str = Field(..., title="Page", description="The Page ID.", json_schema_extra=_PAGE_DYNAMIC)
    fields: str = Field("id,title,description,created_time,permalink_url", title="Fields", description="Comma-separated fields.")
    limit: Optional[str] = Field("25", title="Limit", description="Max videos per page.")


async def _list_videos(c, token, secret):
    return await _fb_request(token, "GET", f"/{c.page_id}/videos", params={"fields": c.fields, "limit": c.limit},
                             app_secret=secret, action_name="list_videos")


_reg(FbUploadPhotoConfig, "upload_photo", _upload_photo)
_reg(FbListAlbumsConfig, "list_albums", _list_albums)
_reg(FbUploadVideoConfig, "upload_video", _upload_video)
_reg(FbListVideosConfig, "list_videos", _list_videos)


# ============================================================================
# Reels
# ============================================================================


async def _hosted_upload_to_url(access_token: str, upload_url: str, file_url: str, action_name: str) -> Dict[str, Any]:
    """Resumable-upload the hosted `file_url` to a Graph rupload URL (header-based
    file transfer). Used by the Reels + video Stories publish flows."""
    # ``upload_url`` is opaque provider response data. Validate its parsed
    # origin before attaching the Page token so a compromised/malformed Graph
    # response cannot turn this into credential egress or private-network SSRF.
    assert_exact_url_origin(upload_url, FB_RUPLOAD_ORIGIN)
    headers = {"Authorization": f"OAuth {access_token}", "file_url": file_url}
    start = time.time()
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            response = await client.post(upload_url, headers=headers)
            api_ms = round((time.time() - start) * 1000, 2)
            if response.status_code >= 400:
                try:
                    err = response.json()
                    eo = err.get("error", {})
                    message = eo.get("message") if isinstance(eo, dict) else err.get("message", str(err))
                except Exception:
                    message = response.text
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                return {"status": "error", "action": action_name, "error": message,
                        "status_code": response.status_code, "timing_ms": {"api_request": api_ms}}
            payload: Any = response.json() if response.content else {"success": True}
            return {"status": "success", "action": action_name, "data": payload,
                    "status_code": response.status_code, "timing_ms": {"api_request": api_ms}}
        except httpx.TimeoutException:
            return {"status": "error", "action": action_name, "error": "Upload timed out",
                    "status_code": 408, "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)}}
        except Exception as e:
            msg = str(e).encode("ascii", errors="replace").decode("ascii")
            return {"status": "error", "action": action_name, "error": msg,
                    "status_code": 500, "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)}}


class FbPublishReelConfig(BaseModel):
    """Publish a Reel to a Page from a hosted video URL (resumable start → upload → finish)."""
    operation: Literal["publish_reel"] = Field("publish_reel", json_schema_extra={
        "const": "publish_reel", "x-category": "Media",
        "x-is-trigger": False, "x-display-name": "Publish Reel"}, title="Publish Reel")
    page_id: str = Field(..., title="Page", description="The Page ID.", json_schema_extra=_PAGE_DYNAMIC)
    file_url: str = Field(..., title="Video URL", description="Publicly reachable video URL to publish as a Reel.")
    description: Optional[str] = Field(None, title="Description", description="Reel caption/description.")


async def _publish_reel(c, token, secret):
    started = await _fb_request(token, "POST", f"/{c.page_id}/video_reels",
                                data={"upload_phase": "start"}, app_secret=secret, action_name="publish_reel")
    if started.get("status") != "success":
        return started
    started_data = started.get("data") or {}
    video_id = started_data.get("video_id")
    upload_url = started_data.get("upload_url")
    if not video_id or not upload_url:
        return {"status": "error", "action": "publish_reel",
                "error": "Reels start phase did not return video_id/upload_url", "data": started_data}
    uploaded = await _hosted_upload_to_url(token, upload_url, c.file_url, "publish_reel")
    if uploaded.get("status") != "success":
        return uploaded
    return await _fb_request(token, "POST", f"/{c.page_id}/video_reels",
                             data={"upload_phase": "finish", "video_id": video_id,
                                   "video_state": "PUBLISHED", "description": c.description},
                             app_secret=secret, action_name="publish_reel")


class FbListReelsConfig(BaseModel):
    """List a Page's Reels."""
    operation: Literal["list_reels"] = Field("list_reels", json_schema_extra={
        "const": "list_reels", "x-category": "Media",
        "x-is-trigger": False, "x-display-name": "List Reels"}, title="List Reels")
    page_id: str = Field(..., title="Page", description="The Page ID.", json_schema_extra=_PAGE_DYNAMIC)
    fields: str = Field("id,title,description,created_time,permalink_url", title="Fields", description="Comma-separated fields.")
    limit: Optional[str] = Field("25", title="Limit", description="Max reels per page.")


async def _list_reels(c, token, secret):
    return await _fb_request(token, "GET", f"/{c.page_id}/video_reels", params={"fields": c.fields, "limit": c.limit},
                             app_secret=secret, action_name="list_reels")


_reg(FbPublishReelConfig, "publish_reel", _publish_reel)
_reg(FbListReelsConfig, "list_reels", _list_reels)


# ============================================================================
# Live video
# ============================================================================


# NOTE: create_live_video / end_live_video were removed: the Live Video API
# feature is excluded from App Review (Facebook's go-live eligibility requires
# a 100+ follower Page, so the flow cannot be demoed or used), and shipping
# ops that fail for every user is worse than not offering them. Re-add when
# the feature is approved on a qualifying Page.


# ============================================================================
# Stories
# ============================================================================


class FbPublishPhotoStoryConfig(BaseModel):
    """Publish a photo Story to a Page (upload unpublished photo → create story)."""
    operation: Literal["publish_photo_story"] = Field("publish_photo_story", json_schema_extra={
        "const": "publish_photo_story", "x-category": "Media",
        "x-is-trigger": False, "x-display-name": "Publish Photo Story"}, title="Publish Photo Story")
    page_id: str = Field(..., title="Page", description="The Page ID.", json_schema_extra=_PAGE_DYNAMIC)
    url: str = Field(..., title="Image URL", description="Publicly reachable image URL to publish as a Story.")


async def _publish_photo_story(c, token, secret):
    uploaded = await _fb_request(token, "POST", f"/{c.page_id}/photos",
                                 data={"url": c.url, "published": "false"},
                                 app_secret=secret, action_name="publish_photo_story")
    if uploaded.get("status") != "success":
        return uploaded
    photo_id = (uploaded.get("data") or {}).get("id")
    if not photo_id:
        return {"status": "error", "action": "publish_photo_story",
                "error": "Unpublished photo upload did not return a photo id", "data": uploaded.get("data")}
    return await _fb_request(token, "POST", f"/{c.page_id}/photo_stories",
                             data={"photo_id": photo_id}, app_secret=secret, action_name="publish_photo_story")


class FbPublishVideoStoryConfig(BaseModel):
    """Publish a video Story to a Page from a hosted video URL (resumable start → upload → finish)."""
    operation: Literal["publish_video_story"] = Field("publish_video_story", json_schema_extra={
        "const": "publish_video_story", "x-category": "Media",
        "x-is-trigger": False, "x-display-name": "Publish Video Story"}, title="Publish Video Story")
    page_id: str = Field(..., title="Page", description="The Page ID.", json_schema_extra=_PAGE_DYNAMIC)
    file_url: str = Field(..., title="Video URL", description="Publicly reachable video URL to publish as a Story.")


async def _publish_video_story(c, token, secret):
    started = await _fb_request(token, "POST", f"/{c.page_id}/video_stories",
                                data={"upload_phase": "start"}, app_secret=secret, action_name="publish_video_story")
    if started.get("status") != "success":
        return started
    started_data = started.get("data") or {}
    video_id = started_data.get("video_id")
    upload_url = started_data.get("upload_url")
    if not video_id or not upload_url:
        return {"status": "error", "action": "publish_video_story",
                "error": "Video story start phase did not return video_id/upload_url", "data": started_data}
    uploaded = await _hosted_upload_to_url(token, upload_url, c.file_url, "publish_video_story")
    if uploaded.get("status") != "success":
        return uploaded
    return await _fb_request(token, "POST", f"/{c.page_id}/video_stories",
                             data={"upload_phase": "finish", "video_id": video_id},
                             app_secret=secret, action_name="publish_video_story")


_reg(FbPublishPhotoStoryConfig, "publish_photo_story", _publish_photo_story)
_reg(FbPublishVideoStoryConfig, "publish_video_story", _publish_video_story)


# ============================================================================
# Comments / reactions
# ============================================================================


class FbReadCommentsConfig(BaseModel):
    """Read comments on a post/photo/video."""
    operation: Literal["read_comments"] = Field("read_comments", json_schema_extra={
        "const": "read_comments", "x-category": "Engagement",
        "x-is-trigger": False, "x-display-name": "Read Comments"}, title="Read Comments")
    object_id: str = Field(..., title="Object ID", description="The post/photo/video/comment ID.")
    fields: str = Field("id,message,from,created_time,like_count,comment_count", title="Fields", description="Comma-separated fields.")
    limit: Optional[str] = Field("25", title="Limit", description="Max comments per page.")


async def _read_comments(c, token, secret):
    return await _fb_request(token, "GET", f"/{c.object_id}/comments", params={"fields": c.fields, "limit": c.limit},
                             app_secret=secret, action_name="read_comments")


class FbCreateCommentConfig(BaseModel):
    """Comment on a post/photo/video (or reply to a comment)."""
    operation: Literal["create_comment"] = Field("create_comment", json_schema_extra={
        "const": "create_comment", "x-category": "Engagement",
        "x-is-trigger": False, "x-display-name": "Create Comment"}, title="Create Comment")
    object_id: str = Field(..., title="Object ID", description="The object (or parent comment) ID.")
    message: Optional[str] = Field(None, title="Message", description="Comment text.")
    attachment_url: Optional[str] = Field(None, title="Attachment URL", description="Optional image URL to attach.")


async def _create_comment(c, token, secret):
    return await _fb_request(token, "POST", f"/{c.object_id}/comments",
                             data={"message": c.message, "attachment_url": c.attachment_url},
                             app_secret=secret, action_name="create_comment")


class FbUpdateCommentConfig(BaseModel):
    """Edit a comment."""
    operation: Literal["update_comment"] = Field("update_comment", json_schema_extra={
        "const": "update_comment", "x-category": "Engagement",
        "x-is-trigger": False, "x-display-name": "Update Comment"}, title="Update Comment")
    comment_id: str = Field(..., title="Comment ID", description="The comment ID.")
    message: str = Field(..., title="Message", description="New comment text.")


async def _update_comment(c, token, secret):
    return await _fb_request(token, "POST", f"/{c.comment_id}", data={"message": c.message}, app_secret=secret, action_name="update_comment")


class FbDeleteCommentConfig(BaseModel):
    """Delete a comment."""
    operation: Literal["delete_comment"] = Field("delete_comment", json_schema_extra={
        "const": "delete_comment", "x-category": "Engagement",
        "x-is-trigger": False, "x-display-name": "Delete Comment"}, title="Delete Comment")
    comment_id: str = Field(..., title="Comment ID", description="The comment ID.")


async def _delete_comment(c, token, secret):
    return await _fb_request(token, "DELETE", f"/{c.comment_id}", app_secret=secret, action_name="delete_comment")


class FbHideCommentConfig(BaseModel):
    """Hide or unhide a comment."""
    operation: Literal["hide_comment"] = Field("hide_comment", json_schema_extra={
        "const": "hide_comment", "x-category": "Engagement",
        "x-is-trigger": False, "x-display-name": "Hide / Unhide Comment"}, title="Hide / Unhide Comment")
    comment_id: str = Field(..., title="Comment ID", description="The comment ID.")
    hide: str = Field("true", title="Hide", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
                      description="'true' to hide, 'false' to unhide.")


async def _hide_comment(c, token, secret):
    return await _fb_request(token, "POST", f"/{c.comment_id}", data={"is_hidden": c.hide}, app_secret=secret, action_name="hide_comment")


class FbPrivateReplyConfig(BaseModel):
    """Send a private (Messenger) reply to a comment."""
    operation: Literal["private_reply"] = Field("private_reply", json_schema_extra={
        "const": "private_reply", "x-category": "Engagement",
        "x-is-trigger": False, "x-display-name": "Private Reply to Comment"}, title="Private Reply to Comment")
    page_id: str = Field(..., title="Page", description="The Page ID.", json_schema_extra=_PAGE_DYNAMIC)
    comment_id: str = Field(..., title="Comment ID", description="The comment to reply to privately.")
    message: str = Field(..., title="Message", description="The private reply text.")


async def _private_reply(c, token, secret):
    body = {"recipient": json.dumps({"comment_id": c.comment_id}), "message": json.dumps({"text": c.message})}
    return await _fb_request(token, "POST", f"/{c.page_id}/messages", data=body, app_secret=secret, action_name="private_reply")


class FbLikeObjectConfig(BaseModel):
    """Like an object (post/comment) as the Page."""
    operation: Literal["like_object"] = Field("like_object", json_schema_extra={
        "const": "like_object", "x-category": "Engagement",
        "x-is-trigger": False, "x-display-name": "Like Object"}, title="Like Object")
    object_id: str = Field(..., title="Object ID", description="The post/comment ID to like.")


async def _like_object(c, token, secret):
    return await _fb_request(token, "POST", f"/{c.object_id}/likes", app_secret=secret, action_name="like_object")


class FbUnlikeObjectConfig(BaseModel):
    """Remove the Page's like from an object."""
    operation: Literal["unlike_object"] = Field("unlike_object", json_schema_extra={
        "const": "unlike_object", "x-category": "Engagement",
        "x-is-trigger": False, "x-display-name": "Unlike Object"}, title="Unlike Object")
    object_id: str = Field(..., title="Object ID", description="The post/comment ID to unlike.")


async def _unlike_object(c, token, secret):
    return await _fb_request(token, "DELETE", f"/{c.object_id}/likes", app_secret=secret, action_name="unlike_object")


class FbGetReactionsConfig(BaseModel):
    """Get reactions on a post/comment."""
    operation: Literal["get_reactions"] = Field("get_reactions", json_schema_extra={
        "const": "get_reactions", "x-category": "Engagement",
        "x-is-trigger": False, "x-display-name": "Get Reactions"}, title="Get Reactions")
    object_id: str = Field(..., title="Object ID", description="The post/comment ID.")
    type: Optional[str] = Field(None, title="Type", description="Filter by reaction type.",
                                json_schema_extra={"enum": ["LIKE", "LOVE", "WOW", "HAHA", "SAD", "ANGRY", "CARE"], "x-enum-searchable": True})
    limit: Optional[str] = Field("25", title="Limit", description="Max reactions per page.")


async def _get_reactions(c, token, secret):
    return await _fb_request(token, "GET", f"/{c.object_id}/reactions", params={"type": c.type, "limit": c.limit},
                             app_secret=secret, action_name="get_reactions")


_reg(FbReadCommentsConfig, "read_comments", _read_comments)
_reg(FbCreateCommentConfig, "create_comment", _create_comment)
_reg(FbUpdateCommentConfig, "update_comment", _update_comment)
_reg(FbDeleteCommentConfig, "delete_comment", _delete_comment)
_reg(FbHideCommentConfig, "hide_comment", _hide_comment)
_reg(FbPrivateReplyConfig, "private_reply", _private_reply)
_reg(FbLikeObjectConfig, "like_object", _like_object)
_reg(FbUnlikeObjectConfig, "unlike_object", _unlike_object)
_reg(FbGetReactionsConfig, "get_reactions", _get_reactions)


# ============================================================================
# Insights
# ============================================================================


class FbPageInsightsConfig(BaseModel):
    """Get Page-level insights."""
    operation: Literal["page_insights"] = Field("page_insights", json_schema_extra={
        "const": "page_insights", "x-category": "Insights",
        "x-is-trigger": False, "x-display-name": "Page Insights"}, title="Page Insights")
    page_id: str = Field(..., title="Page", description="The Page ID.", json_schema_extra=_PAGE_DYNAMIC)
    metric: str = Field("page_post_engagements,page_views_total,page_follows", title="Metric",
                        description="Comma-separated Page metrics (Graph v25 removed page_impressions/page_fans).")
    period: Optional[str] = Field("day", title="Period", json_schema_extra={
        "enum": ["day", "week", "days_28", "month", "lifetime"], "x-enum-searchable": True},
        description="Aggregation period.")
    since: Optional[str] = Field(None, title="Since", description="Start date (Unix or YYYY-MM-DD).")
    until: Optional[str] = Field(None, title="Until", description="End date (Unix or YYYY-MM-DD).")


async def _page_insights(c, token, secret):
    return await _fb_request(token, "GET", f"/{c.page_id}/insights", params={
        "metric": c.metric, "period": c.period, "since": c.since, "until": c.until},
        app_secret=secret, action_name="page_insights")


class FbPostInsightsConfig(BaseModel):
    """Get post-level insights."""
    operation: Literal["post_insights"] = Field("post_insights", json_schema_extra={
        "const": "post_insights", "x-category": "Insights",
        "x-is-trigger": False, "x-display-name": "Post Insights"}, title="Post Insights")
    post_id: str = Field(..., title="Post ID", description="The post ID.")
    metric: str = Field("post_clicks,post_reactions_by_type_total,post_activity_by_action_type", title="Metric",
                        description="Comma-separated post metrics (Graph v25 removed post_impressions/post_engaged_users).")


async def _post_insights(c, token, secret):
    return await _fb_request(token, "GET", f"/{c.post_id}/insights", params={"metric": c.metric},
                             app_secret=secret, action_name="post_insights")


_reg(FbPageInsightsConfig, "page_insights", _page_insights)
_reg(FbPostInsightsConfig, "post_insights", _post_insights)


# ============================================================================
# Page management edges (read-only lists + subscriptions)
# ============================================================================


def _make_page_edge_op(op: str, edge: str, display: str, category: str = "Pages"):
    """Factory for GET /{page-id}/{edge} list operations."""
    cfg = create_model(
        f"Fb_{op}_Config", __base__=BaseModel,
        operation=(Literal[op], Field(op, json_schema_extra={
            "const": op, "x-category": category,
            "x-is-trigger": False, "x-display-name": display}, title=display)),
        page_id=(str, Field(..., title="Page", description="The Page ID.", json_schema_extra=_PAGE_DYNAMIC)),
        fields=(Optional[str], Field(None, title="Fields", description="Comma-separated fields (optional).")),
        limit=(Optional[str], Field("25", title="Limit", description="Max items per page.")),
    )

    async def handler(c, token, secret):
        return await _fb_request(token, "GET", f"/{c.page_id}/{edge}",
                                 params={"fields": c.fields, "limit": c.limit}, app_secret=secret, action_name=op)

    return cfg, handler


for _op, _edge, _disp in [
    ("get_roles", "roles", "Get Page Roles"),
    ("get_settings", "settings", "Get Page Settings"),
    ("get_blocked", "blocked", "Get Blocked Users"),
    ("get_events", "events", "Get Page Events"),
    ("get_ratings", "ratings", "Get Page Ratings"),
    ("get_tagged", "tagged", "Get Tagged Content"),
    ("get_conversations", "conversations", "Get Conversations (Inbox)"),
    ("list_live_videos", "live_videos", "List Live Videos"),
    ("list_page_subscriptions", "subscribed_apps", "List Webhook Subscriptions"),
]:
    _c, _h = _make_page_edge_op(_op, _edge, _disp)
    _reg(_c, _op, _h)


class FbSubscribeWebhooksConfig(BaseModel):
    """Subscribe the app to a Page's webhook fields."""
    operation: Literal["subscribe_page_webhooks"] = Field("subscribe_page_webhooks", json_schema_extra={
        "const": "subscribe_page_webhooks", "x-category": "Pages",
        "x-is-trigger": False, "x-display-name": "Subscribe Page Webhooks"}, title="Subscribe Page Webhooks")
    page_id: str = Field(..., title="Page", description="The Page ID.", json_schema_extra=_PAGE_DYNAMIC)
    subscribed_fields: str = Field(
        "feed,messages,messaging_postbacks,mention,ratings", title="Subscribed Fields",
        description="Comma-separated webhook fields to subscribe to.")


async def _subscribe_page_webhooks(c, token, secret):
    return await _fb_request(token, "POST", f"/{c.page_id}/subscribed_apps",
                             data={"subscribed_fields": c.subscribed_fields}, app_secret=secret, action_name="subscribe_page_webhooks")


class FbUnsubscribeWebhooksConfig(BaseModel):
    """Unsubscribe the app from a Page's webhooks."""
    operation: Literal["unsubscribe_page_webhooks"] = Field("unsubscribe_page_webhooks", json_schema_extra={
        "const": "unsubscribe_page_webhooks", "x-category": "Pages",
        "x-is-trigger": False, "x-display-name": "Unsubscribe Page Webhooks"}, title="Unsubscribe Page Webhooks")
    page_id: str = Field(..., title="Page", description="The Page ID.", json_schema_extra=_PAGE_DYNAMIC)


async def _unsubscribe_page_webhooks(c, token, secret):
    return await _fb_request(token, "DELETE", f"/{c.page_id}/subscribed_apps", app_secret=secret, action_name="unsubscribe_page_webhooks")


_reg(FbSubscribeWebhooksConfig, "subscribe_page_webhooks", _subscribe_page_webhooks)
_reg(FbUnsubscribeWebhooksConfig, "unsubscribe_page_webhooks", _unsubscribe_page_webhooks)


# ============================================================================
# Messenger Platform
# ============================================================================


class FbSendMessageConfig(BaseModel):
    """Send a Messenger message (text or raw message object) to a recipient."""
    operation: Literal["send_message"] = Field("send_message", json_schema_extra={
        "const": "send_message", "x-category": "Messenger",
        "x-is-trigger": False, "x-display-name": "Send Message"}, title="Send Message")
    page_id: str = Field(..., title="Page", description="The Page ID.", json_schema_extra=_PAGE_DYNAMIC)
    recipient_id: str = Field(..., title="Recipient PSID", description="The recipient's Page-scoped ID (PSID).")
    text: Optional[str] = Field(None, title="Text", description="Message text (leave blank if using Message JSON).")
    message_json: str = Field("{}", title="Message JSON",
                              description='Full message object (attachment/template/quick_replies). Overrides Text if set.',
                              json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    messaging_type: Optional[str] = Field("RESPONSE", title="Messaging Type", json_schema_extra={
        "enum": ["RESPONSE", "UPDATE", "MESSAGE_TAG"], "x-enum-searchable": True},
        description="Messaging type; MESSAGE_TAG requires a Tag.")
    tag: Optional[str] = Field(None, title="Message Tag", description="Message tag (required for MESSAGE_TAG).",
                               json_schema_extra={"enum": ["CONFIRMED_EVENT_UPDATE", "POST_PURCHASE_UPDATE", "ACCOUNT_UPDATE", "HUMAN_AGENT"], "x-enum-searchable": True})


async def _send_message(c, token, secret):
    msg = _parse_json_field(c.message_json, "Message JSON") or {}
    if not msg and c.text:
        msg = {"text": c.text}
    data = {"recipient": json.dumps({"id": c.recipient_id}), "message": json.dumps(msg),
            "messaging_type": c.messaging_type, "tag": c.tag}
    return await _fb_request(token, "POST", f"/{c.page_id}/messages", data=data, app_secret=secret, action_name="send_message")


class FbSendAttachmentConfig(BaseModel):
    """Send a media attachment (image/audio/video/file) by URL over Messenger."""
    operation: Literal["send_attachment"] = Field("send_attachment", json_schema_extra={
        "const": "send_attachment", "x-category": "Messenger",
        "x-is-trigger": False, "x-display-name": "Send Attachment"}, title="Send Attachment")
    page_id: str = Field(..., title="Page", description="The Page ID.", json_schema_extra=_PAGE_DYNAMIC)
    recipient_id: str = Field(..., title="Recipient PSID", description="The recipient's PSID.")
    attachment_type: str = Field("image", title="Type", json_schema_extra={
        "enum": ["image", "audio", "video", "file"], "x-enum-searchable": True}, description="Attachment media type.")
    url: str = Field(..., title="URL", description="Publicly reachable media URL.")
    is_reusable: Optional[str] = Field("false", title="Reusable",
                                       json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
                                       description="Cache for reuse via attachment_id.")


async def _send_attachment(c, token, secret):
    msg = {"attachment": {"type": c.attachment_type, "payload": {"url": c.url, "is_reusable": c.is_reusable == "true"}}}
    data = {"recipient": json.dumps({"id": c.recipient_id}), "message": json.dumps(msg)}
    return await _fb_request(token, "POST", f"/{c.page_id}/messages", data=data, app_secret=secret, action_name="send_attachment")


class FbSenderActionConfig(BaseModel):
    """Send a sender action (typing indicator / mark seen)."""
    operation: Literal["send_sender_action"] = Field("send_sender_action", json_schema_extra={
        "const": "send_sender_action", "x-category": "Messenger",
        "x-is-trigger": False, "x-display-name": "Send Sender Action"}, title="Send Sender Action")
    page_id: str = Field(..., title="Page", description="The Page ID.", json_schema_extra=_PAGE_DYNAMIC)
    recipient_id: str = Field(..., title="Recipient PSID", description="The recipient's PSID.")
    sender_action: str = Field("typing_on", title="Action", json_schema_extra={
        "enum": ["typing_on", "typing_off", "mark_seen"], "x-enum-searchable": True}, description="The sender action.")


async def _send_sender_action(c, token, secret):
    data = {"recipient": json.dumps({"id": c.recipient_id}), "sender_action": c.sender_action}
    return await _fb_request(token, "POST", f"/{c.page_id}/messages", data=data, app_secret=secret, action_name="send_sender_action")


class FbUploadMessageAttachmentConfig(BaseModel):
    """Upload a reusable Messenger attachment; returns an attachment_id."""
    operation: Literal["upload_message_attachment"] = Field("upload_message_attachment", json_schema_extra={
        "const": "upload_message_attachment", "x-category": "Messenger",
        "x-is-trigger": False, "x-display-name": "Upload Message Attachment"}, title="Upload Message Attachment")
    page_id: str = Field(..., title="Page", description="The Page ID.", json_schema_extra=_PAGE_DYNAMIC)
    attachment_type: str = Field("image", title="Type", json_schema_extra={
        "enum": ["image", "audio", "video", "file"], "x-enum-searchable": True}, description="Attachment media type.")
    url: str = Field(..., title="URL", description="Publicly reachable media URL.")


async def _upload_message_attachment(c, token, secret):
    msg = {"attachment": {"type": c.attachment_type, "payload": {"url": c.url, "is_reusable": True}}}
    return await _fb_request(token, "POST", f"/{c.page_id}/message_attachments", data={"message": json.dumps(msg)},
                             app_secret=secret, action_name="upload_message_attachment")


class FbGetUserProfileConfig(BaseModel):
    """Get a Messenger user's profile by PSID."""
    operation: Literal["get_user_profile"] = Field("get_user_profile", json_schema_extra={
        "const": "get_user_profile", "x-category": "Messenger",
        "x-is-trigger": False, "x-display-name": "Get User Profile"}, title="Get User Profile")
    psid: str = Field(..., title="PSID", description="The user's Page-scoped ID.")
    fields: str = Field("first_name,last_name,profile_pic,locale,timezone", title="Fields", description="Comma-separated profile fields.")


async def _get_user_profile(c, token, secret):
    return await _fb_request(token, "GET", f"/{c.psid}", params={"fields": c.fields}, app_secret=secret, action_name="get_user_profile")


class FbSetMessengerProfileConfig(BaseModel):
    """Set the Messenger Profile (get started / persistent menu / greeting / ice breakers)."""
    operation: Literal["set_messenger_profile"] = Field("set_messenger_profile", json_schema_extra={
        "const": "set_messenger_profile", "x-category": "Messenger",
        "x-is-trigger": False, "x-display-name": "Set Messenger Profile"}, title="Set Messenger Profile")
    page_id: str = Field(..., title="Page", description="The Page ID.", json_schema_extra=_PAGE_DYNAMIC)
    profile_json: str = Field("{}", title="Profile JSON",
                              description='e.g. {"get_started":{"payload":"START"},"persistent_menu":[...],"greeting":[...]}.',
                              json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


async def _set_messenger_profile(c, token, secret):
    body = _parse_json_field(c.profile_json, "Profile JSON") or {}
    return await _fb_request(token, "POST", f"/{c.page_id}/messenger_profile", data={k: json.dumps(v) for k, v in body.items()},
                             app_secret=secret, action_name="set_messenger_profile")


class FbGetMessengerProfileConfig(BaseModel):
    """Get the current Messenger Profile fields."""
    operation: Literal["get_messenger_profile"] = Field("get_messenger_profile", json_schema_extra={
        "const": "get_messenger_profile", "x-category": "Messenger",
        "x-is-trigger": False, "x-display-name": "Get Messenger Profile"}, title="Get Messenger Profile")
    page_id: str = Field(..., title="Page", description="The Page ID.", json_schema_extra=_PAGE_DYNAMIC)
    fields: str = Field("get_started,persistent_menu,greeting,ice_breakers", title="Fields", description="Comma-separated profile fields.")


async def _get_messenger_profile(c, token, secret):
    return await _fb_request(token, "GET", f"/{c.page_id}/messenger_profile", params={"fields": c.fields},
                             app_secret=secret, action_name="get_messenger_profile")


class FbHandoverConfig(BaseModel):
    """Handover Protocol: pass / take / request thread control."""
    operation: Literal["thread_control"] = Field("thread_control", json_schema_extra={
        "const": "thread_control", "x-category": "Messenger",
        "x-is-trigger": False, "x-display-name": "Thread Control (Handover)"}, title="Thread Control (Handover)")
    page_id: str = Field(..., title="Page", description="The Page ID.", json_schema_extra=_PAGE_DYNAMIC)
    action: str = Field("pass_thread_control", title="Action", json_schema_extra={
        "enum": ["pass_thread_control", "take_thread_control", "request_thread_control"], "x-enum-searchable": True},
        description="The handover action.")
    recipient_id: str = Field(..., title="Recipient PSID", description="The conversation's PSID.")
    target_app_id: Optional[str] = Field(None, title="Target App ID", description="App to pass control to (for pass_thread_control).")
    metadata: Optional[str] = Field(None, title="Metadata", description="Optional metadata string.")


async def _thread_control(c, token, secret):
    data = {"recipient": json.dumps({"id": c.recipient_id}), "target_app_id": c.target_app_id, "metadata": c.metadata}
    return await _fb_request(token, "POST", f"/{c.page_id}/{c.action}", data=data, app_secret=secret, action_name="thread_control")


_reg(FbSendMessageConfig, "send_message", _send_message)
_reg(FbSendAttachmentConfig, "send_attachment", _send_attachment)
_reg(FbSenderActionConfig, "send_sender_action", _send_sender_action)
_reg(FbUploadMessageAttachmentConfig, "upload_message_attachment", _upload_message_attachment)
_reg(FbGetUserProfileConfig, "get_user_profile", _get_user_profile)
_reg(FbSetMessengerProfileConfig, "set_messenger_profile", _set_messenger_profile)
_reg(FbGetMessengerProfileConfig, "get_messenger_profile", _get_messenger_profile)
_reg(FbHandoverConfig, "thread_control", _thread_control)


# ============================================================================
# Generic escape hatch
# ============================================================================


class FbReadObjectConfig(BaseModel):
    """Read any Graph object by ID."""
    operation: Literal["read_object"] = Field("read_object", json_schema_extra={
        "const": "read_object", "x-category": "Advanced",
        "x-is-trigger": False, "x-display-name": "Read Object"}, title="Read Object")
    object_id: str = Field(..., title="Object ID", description="Any Graph object ID.")
    fields: Optional[str] = Field(None, title="Fields", description="Comma-separated fields (optional).")


async def _read_object(c, token, secret):
    return await _fb_request(token, "GET", f"/{c.object_id}", params={"fields": c.fields}, app_secret=secret, action_name="read_object")


class FbGraphRequestConfig(BaseModel):
    """Make an arbitrary Graph API request (escape hatch)."""
    operation: Literal["graph_request"] = Field("graph_request", json_schema_extra={
        "const": "graph_request", "x-category": "Advanced",
        "x-is-trigger": False, "x-display-name": "Custom Graph Request"}, title="Custom Graph Request")
    endpoint: str = Field(..., title="Endpoint", description="Path after the version, e.g. /me/accounts.")
    method: str = Field("GET", title="Method", json_schema_extra={"enum": ["GET", "POST", "DELETE"], "x-enum-searchable": True},
                        description="HTTP method.")
    params_json: str = Field("{}", title="Query Params (JSON)", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
                             description="Query parameters as a JSON object.")
    data_json: str = Field("{}", title="Body (JSON)", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
                           description="Form body as a JSON object.")


async def _graph_request(c, token, secret):
    endpoint = c.endpoint if c.endpoint.startswith("/") else f"/{c.endpoint}"
    params = _parse_json_field(c.params_json, "Query Params") or {}
    data = _parse_json_field(c.data_json, "Body") or {}
    return await _fb_request(token, c.method, endpoint, params=params or None, data=data or None,
                             app_secret=secret, action_name="graph_request")


_reg(FbReadObjectConfig, "read_object", _read_object)
_reg(FbGraphRequestConfig, "graph_request", _graph_request)


# ============================================================================
# Webhook triggers (per field)
# ============================================================================

FB_WEBHOOK_FIELDS = [
    ("feed", "On Feed Activity"),
    ("mention", "On Page Mention"),
    ("ratings", "On New Rating"),
    ("messages", "On Message"),
    ("messaging_postbacks", "On Postback"),
    ("messaging_referrals", "On Referral"),
    ("message_reactions", "On Message Reaction"),
    ("message_deliveries", "On Message Delivered"),
    ("message_reads", "On Message Read"),
    ("standby", "On Standby (Handover)"),
]


class _FbWebhookTrigger(BaseModel):
    webhook_url: Optional[str] = Field(None, title="Callback URL",
                                       description="Paste this into your Meta app's webhook config.",
                                       json_schema_extra={"ui:widget": "webhook", "ui:copyable": True})
    verify_token: Optional[str] = Field(None, title="Verify Token", description="Token Meta echoes during the subscription handshake.")
    app_secret: Optional[str] = Field(None, title="App Secret", description="App secret for X-Hub-Signature-256 verification.",
                                      json_schema_extra={"ui:widget": "password"})


def _fb_field_op(field: str) -> str:
    return "on_" + field


def _make_fb_trigger(op: str, field: str, display: str) -> type:
    return create_model(f"FbTrigger_{op}", __base__=_FbWebhookTrigger,
        operation=(Literal[op], Field(op, json_schema_extra={
            "const": op, "x-category": "Triggers", "x-is-trigger": True,
            "x-webhook-field": field, "x-display-name": display}, title=display)))


FB_TRIGGER_SPECS = [(_fb_field_op(f), f, d) for f, d in FB_WEBHOOK_FIELDS]
FB_TRIGGER_SPECS.append(("on_any_facebook_event", "*", "On Any Facebook Event"))
FB_TRIGGER_EVENT = {op: field for op, field, _ in FB_TRIGGER_SPECS}
FB_TRIGGER_CONFIGS = {op: _make_fb_trigger(op, field, disp) for op, field, disp in FB_TRIGGER_SPECS}


# ============================================================================
# Config union + node
# ============================================================================


def _dedup_ops(configs: List[type]) -> List[type]:
    by_op: Dict[str, type] = {}
    for cfg in configs:
        by_op[cfg.model_fields["operation"].default] = cfg
    return list(by_op.values())


FacebookConfig = Annotated[
    Union[tuple([*FB_TRIGGER_CONFIGS.values(), *_dedup_ops(OPERATION_CONFIGS)])],  # type: ignore[misc]
    Discriminator("operation"),
]


class FacebookNodeConfig(NodeConfig[FacebookConfig, FacebookCredential]):
    pass


class FacebookNode(WorkflowNode):
    """Facebook (Pages + Messenger) automation node."""

    edit_examples = [
        "Publish a post to my Facebook Page",
        "Reply to a comment on my Page",
        "Send a Messenger message to a user",
        "Pull my Page's insights",
        "Trigger a workflow when someone messages my Page",
    ]

    scope_registry = FACEBOOK_SCOPES
    connection_evidence = ConnectionEvidence(
        field="page_id",
        noun="Pages",
    )

    @classmethod
    def get_config_model(cls):
        return FacebookNodeConfig

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
    def _payload_fields(payload: Dict[str, Any]) -> List[str]:
        if not isinstance(payload, dict):
            return []
        fields: List[str] = []
        for entry in payload.get("entry") or []:
            if not isinstance(entry, dict):
                continue
            for change in entry.get("changes") or []:
                if isinstance(change, dict) and change.get("field"):
                    fields.append(str(change["field"]))
            if entry.get("messaging"):
                for m in entry.get("messaging") or []:
                    if not isinstance(m, dict):
                        continue
                    if "message" in m:
                        fields.append("messages")
                    if "postback" in m:
                        fields.append("messaging_postbacks")
                    if "delivery" in m:
                        fields.append("message_deliveries")
                    if "read" in m:
                        fields.append("message_reads")
                    if "reaction" in m:
                        fields.append("message_reactions")
                    if "referral" in m:
                        fields.append("messaging_referrals")
            if entry.get("standby"):
                fields.append("standby")
        seen: set = set()
        return [f for f in fields if not (f in seen or seen.add(f))]

    @classmethod
    def filter_trigger_payload(cls, payload: Dict[str, Any], config: Dict[str, Any]) -> bool:
        field = FB_TRIGGER_EVENT.get((config or {}).get("operation"), "*")
        if field == "*":
            return True
        found = cls._payload_fields(payload)
        if not found:
            return True
        return field in found

    @classmethod
    def resolve_agent_event(cls, output: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Messenger message/postback → the agent's user turn keyed on the
        sender PSID (one conversation per Messenger user). The PSID doubles as
        the reply id the send tools (send_message/send_attachment/…) accept as
        ``recipient_id``. Only Page/Messenger deliveries (``object == "page"``)
        are unwrapped — Instagram (``object == "instagram"``) and non-messaging
        deliveries (feed/mention/ratings/…) fall through to raw JSON."""
        if not isinstance(output, dict) or output.get("object") != "page":
            return super().resolve_agent_event(output)
        try:
            events = [m for entry in output["entry"]
                      for m in (entry.get("messaging") or []) if isinstance(m, dict)]
            # Skip echoes (the Page's own outbound sends) so the agent never mis-addresses itself.
            event = next(m for m in events if (m.get("message") or m.get("postback"))
                         and not (m.get("message") or {}).get("is_echo"))
        except (KeyError, IndexError, TypeError, StopIteration):
            return super().resolve_agent_event(output)
        psid = str((event.get("sender") or {}).get("id") or "").strip()
        if not psid:
            return super().resolve_agent_event(output)
        # The Page that received the message is the send ops' required page_id.
        page_id = str((event.get("recipient") or {}).get("id") or "").strip()
        postback = event.get("postback")
        if postback:
            label = postback.get("title") or postback.get("payload") or "[postback]"
            body = f"tapped a button: {label}"
        else:
            body = (event.get("message") or {}).get("text") or "[non-text message]"
        reply = f"To reply, call a send tool with recipient_id={psid}"
        reply += f" and page_id={page_id}." if page_id else "."
        return {
            "text": f"Facebook Messenger message from PSID {psid}:\n{body}\n\n{reply}",
            "conversation_key": psid,
        }

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        if not credential_data or credential_data.get("credential_type") != "facebook_oauth":
            return credential_data
        from nodes.core.oauth_refresh import freshen_oauth_credential
        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token, is_expired=is_token_expired,
            refresh_token_key="access_token", provider="facebook")

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        # Signature matches the workflow_handler / MCP caller convention: the
        # already-loaded-and-freshened credential dict is passed as credential_data
        # (the old user_id/config_data/credential_ids signature raised
        # "unexpected keyword argument 'credential_data'" and broke the Page dropdown).
        if field_name != "page_id":
            return {"options": []}
        access_token = (credential_data or {}).get("access_token")
        if not access_token:
            return {"options": []}
        result = await _fb_request(access_token, "GET", "/me/accounts", params={"fields": "id,name"}, action_name="list_pages")
        if result.get("status") != "success":
            return {"options": []}
        items = (result.get("data") or {}).get("data", []) if isinstance(result.get("data"), dict) else []
        options = [{"label": str(it.get("name") or it.get("id")), "value": str(it.get("id"))}
                   for it in items if isinstance(it, dict) and it.get("id")]
        return {"options": options}

    async def _resolve(self, credentials: FacebookCredential):
        """Return (access_token, app_secret), refreshing an expiring OAuth token."""
        app_secret = getattr(credentials, "app_secret", None)
        expires_at = getattr(credentials, "expires_at", None)
        if not expires_at or not isinstance(credentials, FacebookOAuthCredential):
            return credentials.access_token, app_secret
        if not is_token_expired(expires_at):
            return credentials.access_token, app_secret
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        cred_dict = credentials.model_dump()
        await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"), user_id=self.user_id,
            credential=cred_dict, refresh=refresh_access_token, is_expired=is_token_expired,
            refresh_token_key="access_token", provider="facebook", caller_path="execute")
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        return credentials.access_token, app_secret

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, FacebookNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        if isinstance(op, tuple(FB_TRIGGER_CONFIGS.values())):
            return {"status": "success", "action": op.operation,
                    "data": {**inputs, "webhook_url": op.webhook_url},
                    "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)}}

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Connect your Facebook account.")
        access_token, app_secret = await self._resolve(credentials)

        handler = OPERATION_HANDLERS.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")
        # Page-scoped ops need the Page access token, not the user token.
        op_token = await _token_for_op(op, access_token, app_secret)
        result = await handler(op, op_token, app_secret)
        result["timing_ms"] = {**result.get("timing_ms", {}), "total": round((time.time() - start_time) * 1000, 2)}
        return result
