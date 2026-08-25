"""
TikTok Open Platform automation node.

Provides workflow integration with TikTok via OAuth 2.0 (Authorization Code flow):
  - User Info: get authenticated user's profile and statistics
  - Video Reading: list user's videos, query specific videos by ID
  - Content Publishing: publish video from URL, check publish status

API Base URL: https://open.tiktokapis.com
Documentation: https://developers.tiktok.com/doc/overview

Note on Content Publishing:
  - upload_video_to_creator_inbox: /v2/post/publish/inbox/video/init/ (PULL_FROM_URL).
    The video lands as a draft in the creator's inbox for review. Requires video.upload.
  - direct_post_video: /v2/post/publish/video/init/ via FILE_UPLOAD — the bytes are
    uploaded straight to TikTok (chunked) and published to the profile. Requires the
    video.publish scope. Privacy level is the creator's choice (an account's settings
    may restrict the allowed set; query creator info to confirm).
  - direct_post_photo: /v2/post/publish/content/init/ photo carousel (PULL_FROM_URL).
  - query_creator_info: /v2/post/publish/creator_info/query/ — privacy options + limits,
    queried before a direct post.

Total Operations: 8
"""

import logging
import time
from typing import Any, Dict, Literal, Optional, Union, Annotated

from pydantic import BaseModel, ConfigDict, Discriminator, Field
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.oauth.tiktok_oauth import is_token_expired, refresh_access_token
from nodes.scopes.tiktok import TIKTOK_SCOPES
from utils.ssrf import assert_url_allowed, guarded_async_client

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

TIKTOK_API_BASE = "https://open.tiktokapis.com"

# Default video fields for list/query
DEFAULT_VIDEO_FIELDS = (
    "id,create_time,cover_image_url,share_url,video_description,"
    "duration,height,width,title,like_count,comment_count,share_count,view_count"
)

# Default user fields
DEFAULT_USER_FIELDS = (
    "open_id,union_id,avatar_url,display_name,bio_description,profile_deep_link,"
    "username,is_verified,follower_count,following_count,likes_count,video_count"
)


# ============================================================================
# Credential Schema
# ============================================================================


class TikTokOAuthCredential(BaseModel):
    """
    OAuth 2.0 credential for TikTok Open Platform.
    Tokens are obtained via TikTok OAuth flow, not entered manually.

    Register your app at: https://developers.tiktok.com/
    Access tokens expire in 24 hours; refresh tokens rotate on each refresh.
    """

    credential_type: Literal["tiktok_oauth"] = Field(
        "tiktok_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ...,
        title="Access Token",
        description="OAuth 2.0 access token (expires in 24 hours)",
    )
    refresh_token: Optional[str] = Field(
        None,
        title="Refresh Token",
        description="Long-lived refresh token for renewing access",
    )
    expires_at: Optional[str] = Field(
        None,
        title="Token Expiry",
        description="ISO 8601 timestamp when access token expires",
    )
    refresh_expires_at: Optional[str] = Field(
        None,
        title="Refresh Token Expiry",
        description="ISO 8601 timestamp when refresh token expires",
    )
    open_id: Optional[str] = Field(
        None,
        title="Open ID",
        description="The authenticated user's unique TikTok ID for this app",
    )
    display_name: Optional[str] = Field(
        None,
        title="Display Name",
        description="The authenticated user's TikTok display name",
    )
    avatar_url: Optional[str] = Field(
        None,
        title="Avatar URL",
        description="URL of the authenticated user's profile picture",
    )

    model_config = ConfigDict(json_schema_extra={
        "x-credential-type": "oauth",
        "x-oauth-provider": "tiktok",
        "x-credential-url": "https://developers.tiktok.com/",
        "x-credential-instructions": (
            "Connect your TikTok account via OAuth. You need a TikTok developer app "
            "with TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET configured."
        ),
        "x-oauth-scopes": [
            "user.info.basic",
            "user.info.profile",
            "user.info.stats",
            "video.list",
            "video.upload",
            "video.publish",
        ],
    })


# ============================================================================
# User Operations
# ============================================================================


class TikTokGetUserInfoConfig(BaseModel):
    """Get the authenticated user's TikTok profile and statistics"""

    operation: Literal["get_authenticated_user_info"] = Field(
        "get_authenticated_user_info",
        json_schema_extra={
            "const": "get_authenticated_user_info",
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get Authenticated User Info",
        },
        title="Get Authenticated User Info",
    )
    fields: Optional[str] = Field(
        DEFAULT_USER_FIELDS,
        title="Fields",
        description=(
            "Comma-separated fields to retrieve. "
            "Stats fields (follower_count, following_count, etc.) require user.info.stats scope."
        ),
    )


# ============================================================================
# Video Reading Operations
# ============================================================================


class TikTokListVideosConfig(BaseModel):
    """List the authenticated user's recent public videos"""

    operation: Literal["list_user_public_videos"] = Field(
        "list_user_public_videos",
        json_schema_extra={
            "const": "list_user_public_videos",
            "ui:hidden": True,
            "x-category": "Video",
            "x-is-trigger": False,
            "x-display-name": "List User Public Videos",
        },
        title="List User Public Videos",
    )
    fields: Optional[str] = Field(
        DEFAULT_VIDEO_FIELDS,
        title="Fields",
        description="Comma-separated fields to retrieve for each video",
    )
    max_count: Optional[int] = Field(
        20,
        title="Max Count",
        description="Maximum number of videos to return (1–20)",
        ge=1,
        le=20,
    )
    cursor: Optional[int] = Field(
        None,
        title="Cursor",
        description="Pagination cursor from a previous response to get the next page",
    )


class TikTokQueryVideosConfig(BaseModel):
    """Query specific videos by ID to retrieve their metrics and details"""

    operation: Literal["query_video_metrics_by_id"] = Field(
        "query_video_metrics_by_id",
        json_schema_extra={
            "const": "query_video_metrics_by_id",
            "ui:hidden": True,
            "x-category": "Video",
            "x-is-trigger": False,
            "x-display-name": "Query Video Metrics by Id",
        },
        title="Query Video Metrics by Id",
    )
    video_ids: str = Field(
        ...,
        title="Video IDs",
        description="Comma-separated list of video IDs to query (up to 20)",
    )
    fields: Optional[str] = Field(
        DEFAULT_VIDEO_FIELDS,
        title="Fields",
        description="Comma-separated fields to retrieve for each video",
    )


# ============================================================================
# Content Publishing Operations
# ============================================================================


class TikTokPublishVideoConfig(BaseModel):
    """Upload a video to TikTok creator inbox as a draft via PULL_FROM_URL (requires video.upload scope).
    The creator receives an inbox notification and can review/edit before posting.
    To publish straight to the profile instead, use the Direct Post Video operation.
    """

    operation: Literal["upload_video_to_creator_inbox"] = Field(
        "upload_video_to_creator_inbox",
        json_schema_extra={
            "const": "upload_video_to_creator_inbox",
            "ui:hidden": True,
            "x-category": "Video",
            "x-is-trigger": False,
            "x-display-name": "Upload Video to Creator Inbox",
        },
        title="Upload Video to Creator Inbox",
    )
    video_url: str = Field(
        ...,
        title="Video URL",
        description=(
            "The video to send — upload a file, paste a URL, or reference an upstream "
            "file (e.g. {{http-1.response.url}}). MP4 recommended, max 64 MB. "
            "Must be publicly accessible by TikTok's servers."
        ),
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": "video/*"},
    )
    title: Optional[str] = Field(
        None,
        title="Title / Caption",
        description="Video title or caption (max 150 characters)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class TikTokCheckPublishStatusConfig(BaseModel):
    """Check the status of a pending or completed video publish operation"""

    operation: Literal["check_video_publish_status"] = Field(
        "check_video_publish_status",
        json_schema_extra={
            "const": "check_video_publish_status",
            "ui:hidden": True,
            "x-category": "Video",
            "x-is-trigger": False,
            "x-display-name": "Check Video Publish Status",
        },
        title="Check Video Publish Status",
    )
    publish_id: str = Field(
        ...,
        title="Publish ID",
        description="The publish_id returned by the publish_video operation",
    )


# Privacy levels accepted by TikTok's direct-post endpoints. A creator's account
# settings can restrict the allowed set — query creator info to confirm per account.
_PRIVACY_LEVELS = ["PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "SELF_ONLY"]
_PRIVACY_LABELS = ["Public", "Friends (mutual follow)", "Followers only", "Only me (private)"]
_YES_NO = {"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True}


class TikTokQueryCreatorInfoConfig(BaseModel):
    """Query the creator's posting options before a direct post (privacy options,
    interaction toggles, max video duration). Requires video.publish scope."""

    operation: Literal["query_creator_info"] = Field(
        "query_creator_info",
        json_schema_extra={
            "const": "query_creator_info",
            "ui:hidden": True,
            "x-category": "Video",
            "x-is-trigger": False,
            "x-display-name": "Query Creator Info",
        },
        title="Query Creator Info",
    )


class TikTokDirectPostVideoConfig(BaseModel):
    """Publish a video directly to the creator's TikTok profile via FILE_UPLOAD
    (the bytes are uploaded straight to TikTok, no public URL needed). Requires
    the video.publish scope."""

    operation: Literal["direct_post_video"] = Field(
        "direct_post_video",
        json_schema_extra={
            "const": "direct_post_video",
            "ui:hidden": True,
            "x-category": "Video",
            "x-is-trigger": False,
            "x-display-name": "Direct Post Video",
        },
        title="Direct Post Video",
    )
    video_url: str = Field(
        ...,
        title="Video",
        description=(
            "The video to post — upload a file, paste a URL, or reference an upstream "
            "file (e.g. {{http-1.response.url}}). The bytes are uploaded directly to "
            "TikTok (MP4 recommended, max 64 MB)."
        ),
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": "video/*"},
    )
    title: Optional[str] = Field(
        None,
        title="Caption",
        description="Video caption (max 2200 characters). Hashtags and @mentions are supported.",
        json_schema_extra={"ui:widget": "textarea"},
    )
    privacy_level: str = Field(
        "PUBLIC_TO_EVERYONE",
        title="Privacy Level",
        description="Who can see the post. The creator's account settings can restrict which levels are allowed — use Query Creator Info to confirm the available options for an account.",
        json_schema_extra={
            "enum": _PRIVACY_LEVELS,
            "enumNames": _PRIVACY_LABELS,
            "x-enum-searchable": True,
        },
    )
    disable_comment: str = Field(
        "false", title="Disable Comments", json_schema_extra=_YES_NO
    )
    disable_duet: str = Field("false", title="Disable Duet", json_schema_extra=_YES_NO)
    disable_stitch: str = Field(
        "false", title="Disable Stitch", json_schema_extra=_YES_NO
    )
    video_cover_timestamp_ms: Optional[int] = Field(
        None,
        title="Cover Frame (ms)",
        description="Timestamp in milliseconds of the frame to use as the cover image.",
    )


class TikTokDirectPostPhotoConfig(BaseModel):
    """Publish a photo carousel directly to the creator's TikTok profile. Photos
    are pulled by TikTok from public URLs. Requires video.publish scope."""

    operation: Literal["direct_post_photo"] = Field(
        "direct_post_photo",
        json_schema_extra={
            "const": "direct_post_photo",
            "ui:hidden": True,
            "x-category": "Photo",
            "x-is-trigger": False,
            "x-display-name": "Direct Post Photo",
        },
        title="Direct Post Photo",
    )
    photo_urls: str = Field(
        ...,
        title="Photo URLs",
        description=(
            "Comma-separated public image URLs in carousel order (up to 10). JPEG or WebP only "
            "(TikTok rejects PNG). Each must be reachable by TikTok — use the upload button on "
            "another node or {{http-1.response.url}} to host images."
        ),
    )
    title: Optional[str] = Field(
        None, title="Title", description="Photo post title (max 90 characters)"
    )
    description: Optional[str] = Field(
        None,
        title="Description",
        description="Photo post description / caption (max 4000 characters)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    privacy_level: str = Field(
        "PUBLIC_TO_EVERYONE",
        title="Privacy Level",
        description="Who can see the post. The creator's account settings can restrict which levels are allowed — use Query Creator Info to confirm the available options for an account.",
        json_schema_extra={
            "enum": _PRIVACY_LEVELS,
            "enumNames": _PRIVACY_LABELS,
            "x-enum-searchable": True,
        },
    )
    photo_cover_index: int = Field(
        0, title="Cover Photo Index", description="Zero-based index of the photo to use as the cover."
    )
    disable_comment: str = Field(
        "false", title="Disable Comments", json_schema_extra=_YES_NO
    )
    auto_add_music: str = Field(
        "true", title="Auto-add Music", json_schema_extra=_YES_NO
    )


# ============================================================================
# Discriminated Union
# ============================================================================

TikTokConfig = Annotated[
    Union[
        TikTokGetUserInfoConfig,
        TikTokListVideosConfig,
        TikTokQueryVideosConfig,
        TikTokPublishVideoConfig,
        TikTokCheckPublishStatusConfig,
        TikTokQueryCreatorInfoConfig,
        TikTokDirectPostVideoConfig,
        TikTokDirectPostPhotoConfig,
    ],
    Discriminator("operation"),
]


# ============================================================================
# Full Node Configuration
# ============================================================================


class TikTokNodeConfig(NodeConfig[TikTokConfig, TikTokOAuthCredential]):
    """Full configuration for TikTok node including credentials"""

    pass


# ============================================================================
# Node Implementation
# ============================================================================


class TikTokNode(WorkflowNode):
    """TikTok Open Platform automation node."""

    edit_examples = [
        "Get authenticated user profile with follower and video count stats",
        "List last 20 videos and retrieve view/engagement metrics per video",
        "Query specific videos by ID to track performance over time",
        "Upload video to creator inbox as draft for review before posting",
        "Check publish status of pending video upload to inbox",
        "Fetch user stats and recent video performance for analytics",
        "Get video list with cursor for pagination and load next batch",
        "Query creator info for allowed privacy levels before a direct post",
        "Direct post a video to the profile by uploading the file to TikTok",
        "Direct post a photo carousel to the profile from public image URLs",
    ]

    scope_registry = TIKTOK_SCOPES
    connection_evidence = ConnectionEvidence(
        noun="account",
        identity_operation="get_authenticated_user_info",
    )

    @classmethod
    def get_config_model(cls):
        """Return the Pydantic model for node configuration."""
        return TikTokNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the configured TikTok operation.

        Args:
            inputs: Output data from upstream nodes

        Returns:
            Dict with operation results including status, action, data, and timing
        """
        start_time = time.time()

        config = self.config
        if not config or not isinstance(config, TikTokNodeConfig):
            raise ValueError("Valid configuration is required")

        credentials = config.credentials
        if not credentials:
            raise ValueError(
                "Credentials are required. Connect your TikTok account via OAuth."
            )

        access_token = await self._get_access_token(credentials)
        op_config = config.config
        action = op_config.operation

        handlers = {
            "get_authenticated_user_info": self._handle_get_user_info,
            "list_user_public_videos": self._handle_list_videos,
            "query_video_metrics_by_id": self._handle_query_videos,
            "upload_video_to_creator_inbox": self._handle_publish_video,
            "check_video_publish_status": self._handle_check_publish_status,
            "query_creator_info": self._handle_query_creator_info,
            "direct_post_video": self._handle_direct_post_video,
            "direct_post_photo": self._handle_direct_post_photo,
        }

        handler = handlers.get(action)
        if not handler:
            raise ValueError(f"Unknown action: {action}")

        result = await handler(op_config, access_token)

        total_time = (time.time() - start_time) * 1000
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round(total_time, 2),
        }

        return result

    # =========================================================================
    # HTTP Request Helper
    # =========================================================================

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        """Refresh an expiring OAuth token at credential load (dropdowns,
        trigger registration). No-op for non-rotating credentials (API keys /
        offline / non-expiring tokens)."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.tiktok_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token,
            provider="tiktok",
        )

    async def _get_access_token(self, credentials: TikTokOAuthCredential) -> str:
        """
        Get a valid access token, refreshing if expired.

        TikTok tokens expire every 24 hours. This method checks expiry with a
        60-minute buffer and refreshes automatically if a refresh_token is available.
        """
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        
        cred_dict = credentials.model_dump()

        async def _refresh(refresh_token: str):
            # TikTok rotates refresh tokens and also issues a fresh
            # refresh_expires_at, which the shared helper doesn't carry — stamp
            # it into the credential dict so it persists with the rest.
            tokens = await refresh_access_token(refresh_token)
            if tokens.refresh_expires_at:
                cred_dict["refresh_expires_at"] = tokens.refresh_expires_at
            return tokens

        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=cred_dict,
            refresh=_refresh,
            provider="tiktok",
        )
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        if cred_dict.get("refresh_token"):
            credentials.refresh_token = cred_dict["refresh_token"]
        if cred_dict.get("refresh_expires_at"):
            credentials.refresh_expires_at = cred_dict["refresh_expires_at"]
        return token

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        access_token: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        action_name: str = "request",
    ) -> Dict[str, Any]:
        """
        Make an authenticated HTTP request to the TikTok Open Platform API.

        Args:
            method: HTTP method (GET, POST)
            endpoint: Full path starting with /v2/ (e.g. /v2/user/info/)
            access_token: Pre-resolved Bearer token (user OAuth or client credentials)
            params: Query string parameters
            json_body: JSON request body
            action_name: Operation name for response metadata

        Returns:
            Dict with status, action, data, status_code, and timing_ms
        """
        url = f"{TIKTOK_API_BASE}{endpoint}"

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        # Remove None values from params
        if params:
            params = {k: v for k, v in params.items() if v is not None}

        start_time = time.time()

        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=json_body,
                )

                api_time = (time.time() - start_time) * 1000

                if response.status_code >= 400:
                    error_code = None
                    log_id = None
                    try:
                        error_data = response.json()
                        # TikTok envelope: {"error": {"code", "message", "log_id"}}.
                        # The code is the authoritative classifier (e.g.
                        # unaudited_client_can_only_post_to_private_accounts,
                        # url_ownership_unverified); log_id is what TikTok support
                        # needs. The human message alone is often a generic
                        # "review our guidelines" link, so surface all three.
                        err = error_data.get("error", {}) if isinstance(error_data, dict) else {}
                        error_code = err.get("code")
                        log_id = err.get("log_id")
                        error_message = (
                            err.get("message")
                            or error_data.get("message")
                            or response.text
                        )
                    except Exception:
                        error_message = response.text

                    logger.error(
                        f"[TikTokNode] API error ({response.status_code}) "
                        f"code={error_code} log_id={log_id}: {error_message}"
                    )
                    return {
                        "status": "error",
                        "action": action_name,
                        "error": error_message,
                        "error_code": error_code,
                        "log_id": log_id,
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
                logger.exception(f"[TikTokNode] Request failed: {e}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": str(e),
                    "status_code": 500,
                    "timing_ms": {
                        "api_request": round((time.time() - start_time) * 1000, 2)
                    },
                }

    # =========================================================================
    # User Operations
    # =========================================================================

    async def _handle_get_user_info(
        self,
        config: TikTokGetUserInfoConfig,
        access_token: str,
    ) -> Dict[str, Any]:
        """Get the authenticated user's TikTok profile and statistics."""
        return await self._make_request(
            method="GET",
            endpoint="/v2/user/info/",
            access_token=access_token,
            params={"fields": config.fields},
            action_name="get_authenticated_user_info",
        )

    # =========================================================================
    # Video Reading Operations
    # =========================================================================

    async def _handle_list_videos(
        self,
        config: TikTokListVideosConfig,
        access_token: str,
    ) -> Dict[str, Any]:
        """List the authenticated user's recent public videos."""
        # TikTok /v2/video/list/ requires POST with fields as query param and body for pagination
        body: Dict[str, Any] = {"max_count": config.max_count}
        if config.cursor is not None:
            body["cursor"] = config.cursor
        return await self._make_request(
            method="POST",
            endpoint="/v2/video/list/",
            access_token=access_token,
            params={"fields": config.fields},
            json_body=body,
            action_name="list_user_public_videos",
        )

    async def _handle_query_videos(
        self,
        config: TikTokQueryVideosConfig,
        access_token: str,
    ) -> Dict[str, Any]:
        """Query specific videos by ID."""
        video_ids = [vid.strip() for vid in config.video_ids.split(",") if vid.strip()]
        return await self._make_request(
            method="POST",
            endpoint="/v2/video/query/",
            access_token=access_token,
            params={"fields": config.fields},
            json_body={"filters": {"video_ids": video_ids}},
            action_name="query_video_metrics_by_id",
        )

    # =========================================================================
    # Content Publishing Operations
    # =========================================================================

    async def _handle_publish_video(
        self,
        config: TikTokPublishVideoConfig,
        access_token: str,
    ) -> Dict[str, Any]:
        """Upload a video to TikTok creator inbox as a draft via PULL_FROM_URL.
        Uses /v2/post/publish/inbox/video/init/ which requires video.upload scope.
        The creator receives an inbox notification to review and publish the draft."""
        post_info: Dict[str, Any] = {}
        if config.title:
            post_info["title"] = config.title

        body: Dict[str, Any] = {
            "source_info": {
                "source": "PULL_FROM_URL",
                "video_url": config.video_url,
            },
        }
        if post_info:
            body["post_info"] = post_info

        return await self._make_request(
            method="POST",
            endpoint="/v2/post/publish/inbox/video/init/",
            access_token=access_token,
            json_body=body,
            action_name="upload_video_to_creator_inbox",
        )

    async def _handle_check_publish_status(
        self,
        config: TikTokCheckPublishStatusConfig,
        access_token: str,
    ) -> Dict[str, Any]:
        """Check the status of a pending or completed video publish."""
        return await self._make_request(
            method="POST",
            endpoint="/v2/post/publish/status/fetch/",
            access_token=access_token,
            json_body={"publish_id": config.publish_id},
            action_name="check_video_publish_status",
        )

    async def _handle_query_creator_info(
        self,
        config: TikTokQueryCreatorInfoConfig,
        access_token: str,
    ) -> Dict[str, Any]:
        """Query the creator's posting options (privacy levels, interaction
        toggles, max duration) — required context before a direct post."""
        return await self._make_request(
            method="POST",
            endpoint="/v2/post/publish/creator_info/query/",
            access_token=access_token,
            action_name="query_creator_info",
        )

    async def _handle_direct_post_video(
        self,
        config: TikTokDirectPostVideoConfig,
        access_token: str,
    ) -> Dict[str, Any]:
        """Publish a video directly to the profile via FILE_UPLOAD: resolve the
        source to bytes, initialize the post, then upload the bytes in chunks."""
        from nodes.core.media_resolver import resolve_media_input

        resolved = await resolve_media_input(config.video_url, default_mime="video/mp4")
        video_bytes = resolved.data
        mime_type = resolved.mime_type or "video/mp4"
        video_size = len(video_bytes)

        # TikTok accepts a single chunk up to 64 MB; larger videos are split into
        # 10 MB chunks with the final chunk absorbing the remainder.
        max_single = 64 * 1024 * 1024
        if video_size <= max_single:
            chunk_size = video_size
            total_chunk_count = 1
        else:
            chunk_size = 10 * 1024 * 1024
            total_chunk_count = video_size // chunk_size

        post_info: Dict[str, Any] = {
            "privacy_level": config.privacy_level,
            "disable_comment": config.disable_comment == "true",
            "disable_duet": config.disable_duet == "true",
            "disable_stitch": config.disable_stitch == "true",
        }
        if config.title:
            post_info["title"] = config.title
        if config.video_cover_timestamp_ms is not None:
            post_info["video_cover_timestamp_ms"] = config.video_cover_timestamp_ms

        init = await self._make_request(
            method="POST",
            endpoint="/v2/post/publish/video/init/",
            access_token=access_token,
            json_body={
                "post_info": post_info,
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": video_size,
                    "chunk_size": chunk_size,
                    "total_chunk_count": total_chunk_count,
                },
            },
            action_name="direct_post_video",
        )
        if init.get("status") != "success":
            return init

        init_data = init["data"].get("data", {})
        publish_id = init_data.get("publish_id")
        upload_url = init_data.get("upload_url")
        if not upload_url:
            return {
                "status": "error",
                "action": "direct_post_video",
                "error": f"TikTok did not return an upload URL: {init['data']}",
                "status_code": 502,
            }

        upload = await self._upload_file_chunks(
            upload_url, video_bytes, mime_type, chunk_size, total_chunk_count
        )

        return {
            "status": "success",
            "action": "direct_post_video",
            "publish_id": publish_id,
            "data": init["data"],
            "upload": upload,
            "status_code": init.get("status_code", 200),
        }

    async def _handle_direct_post_photo(
        self,
        config: TikTokDirectPostPhotoConfig,
        access_token: str,
    ) -> Dict[str, Any]:
        """Publish a photo carousel directly to the profile. TikTok pulls each
        image from its public URL (PULL_FROM_URL)."""
        photo_images = [u.strip() for u in config.photo_urls.split(",") if u.strip()]
        if not photo_images:
            raise ValueError("At least one photo URL is required")

        post_info: Dict[str, Any] = {
            "privacy_level": config.privacy_level,
            "disable_comment": config.disable_comment == "true",
            "auto_add_music": config.auto_add_music == "true",
        }
        if config.title:
            post_info["title"] = config.title
        if config.description:
            post_info["description"] = config.description

        return await self._make_request(
            method="POST",
            endpoint="/v2/post/publish/content/init/",
            access_token=access_token,
            json_body={
                "post_info": post_info,
                "source_info": {
                    "source": "PULL_FROM_URL",
                    "photo_cover_index": config.photo_cover_index,
                    "photo_images": photo_images,
                },
                "post_mode": "DIRECT_POST",
                "media_type": "PHOTO",
            },
            action_name="direct_post_photo",
        )

    async def _upload_file_chunks(
        self,
        upload_url: str,
        data: bytes,
        mime_type: str,
        chunk_size: int,
        total_chunk_count: int,
    ) -> Dict[str, Any]:
        """PUT the video bytes to TikTok's returned upload URL in chunks, with the
        Content-Range each chunk covers. Raises on any non-2xx chunk response."""
        video_size = len(data)
        await assert_url_allowed(upload_url)
        async with guarded_async_client(timeout=300.0) as client:
            for i in range(total_chunk_count):
                start = i * chunk_size
                # The final chunk absorbs any remainder beyond the even split.
                end = video_size - 1 if i == total_chunk_count - 1 else start + chunk_size - 1
                chunk = data[start : end + 1]
                response = await client.put(
                    upload_url,
                    headers={
                        "Content-Type": mime_type,
                        "Content-Length": str(len(chunk)),
                        "Content-Range": f"bytes {start}-{end}/{video_size}",
                    },
                    content=chunk,
                )
                if response.status_code not in (200, 201, 206):
                    raise ValueError(
                        f"TikTok chunk upload failed ({response.status_code}): {response.text}"
                    )
        return {"chunks_uploaded": total_chunk_count, "bytes_uploaded": video_size}
