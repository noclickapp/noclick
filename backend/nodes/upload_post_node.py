"""Publish and manage Upload Post content using a person-supplied API key.

Each operation makes one documented API request. Media uploads accept public
HTTPS URLs; Upload Post fetches the media, and asynchronous results remain intact.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.upload-post.com/api"


class UploadPostAPIKeyCredential(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, title="Upload Post API Key",
        json_schema_extra={
            "x-credential-url": "https://app.upload-post.com/",
            "x-credential-instructions": "Copy your API key from the Upload Post dashboard and paste it here. Connect your social accounts in Upload Post before publishing."
        })
    credential_type: Literal["upload_post_api_key"] = Field("upload_post_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not isinstance(value, str) or any(c.isspace() or ord(c) < 32 or ord(c) > 126 for c in value):
            raise ValueError("Paste the API key without the Apikey prefix")
        return value


class QueueSlot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hour: int = Field(..., ge=0, le=23)
    minute: int = Field(..., ge=0, le=59)


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="after")
    def semantics(self):
        if getattr(self, "scheduled_date", None) and getattr(self, "add_to_queue", False):
            raise ValueError("Choose a scheduled date or add to queue")
        date = getattr(self, "scheduled_date", None)
        if date:
            try:
                parsed = datetime.fromisoformat(date.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=ZoneInfo(getattr(self, "timezone", None) or "UTC"))
                now = datetime.now(timezone.utc)
                if not now < parsed <= now + timedelta(days=365):
                    raise ValueError()
            except (ValueError, TypeError, KeyError):
                raise ValueError("Schedule within the next 365 days using an ISO-8601 date") from None
        tz = getattr(self, "timezone", None)
        if tz:
            try: ZoneInfo(tz)
            except (KeyError, ValueError): raise ValueError("Use an IANA timezone") from None
        for field in ("video", "document"):
            value = getattr(self, field, None)
            if value:
                parsed = urlsplit(value)
                if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
                    raise ValueError("Supply a public HTTPS media URL")
        if getattr(self, "operation", None) == "get_media" and self.platform == "linkedin" and self.cursor:
            raise ValueError("LinkedIn does not support a media cursor")
        if getattr(self, "operation", None) == "get_analytics" and "facebook" in self.platforms.split(",") and not self.page_id:
            raise ValueError("Facebook analytics requires page_id")
        if self.operation in {"get_upload_status", "retry_post"} and not (self.request_id or self.job_id):
            raise ValueError("Provide request_id or job_id")
        if self.operation == "get_comments" and not (self.post_id or self.post_url):
            raise ValueError("Provide post_id or post_url")
        for field in ("job_id", "username", "profile_username"):
            value = getattr(self, field, None)
            if value and (value in {".", ".."} or any(ord(c) < 32 for c in value)):
                raise ValueError("Use a single resource identifier without controls or dot segments")
        if getattr(self, "operation", None) == "rename_profile" and self.display_name and any(c in self.display_name for c in "\r\n"):
            raise ValueError("Display names cannot contain line breaks")
        return self


class UploadPostUploadVideoConfig(_Input):
    """Upload video."""
    operation: Literal['upload_video'] = Field('upload_video', json_schema_extra={"ui:hidden": True})
    user: str = Field(..., min_length=1, description='User profile identifier.')
    platforms: list[Literal['tiktok', 'instagram', 'linkedin', 'youtube', 'facebook', 'x', 'threads', 'pinterest', 'bluesky', 'reddit', 'google_business', 'discord', 'telegram']] = Field(..., min_length=1, description='Platform(s) to upload to.')
    video: str = Field(..., min_length=1, description='The video file to upload (binary file) or a public video URL.')
    title: str = Field(..., min_length=1, description='Default title/caption of the video. Required for YouTube and Reddit; optional for all other platforms. Platform-specific titles override this.')
    description: str | None = Field(None, description='Optional extended text used on LinkedIn commentary, Facebook descriptions, YouTube descriptions, and Pinterest notes. Ignored elsewhere.')
    scheduled_date: str | None = Field(None, description="ISO-8601 date/time to schedule publishing (e.g., '2025-12-31T23:45:00Z'). Must be in the future (≤365 days). Omit for immediate upload. Cannot be used with `add_to_queue`.")
    timezone: str | None = Field(None, description="IANA timezone identifier (e.g., 'Europe/Madrid', 'America/New_York'). If provided, `scheduled_date` is interpreted in this timezone. Defaults to UTC.")
    async_upload: bool | None = Field(None, description='If true, returns immediately with a `request_id` and processes in the background. If false but upload takes >59s, automatically switches to async.')
    add_to_queue: bool | None = Field(None, description='If true, automatically schedules the post to the next available queue slot. Cannot be used with `scheduled_date`.')
    first_comment: str | None = Field(None, description='Automatically post a first comment after publishing. Supported on Instagram, Facebook, Threads, Bluesky, Reddit, X, YouTube, and LinkedIn.')
    privacy_level: Literal['PUBLIC_TO_EVERYONE', 'MUTUAL_FOLLOW_FRIENDS', 'FOLLOWER_OF_CREATOR', 'SELF_ONLY'] | None = Field(None)
    visibility: Literal['PUBLIC', 'CONNECTIONS', 'LOGGED_IN', 'CONTAINER'] | None = Field(None)
    target_linkedin_page_id: str | None = Field(None, description='[LinkedIn] LinkedIn page ID to upload to an organization page.')
    privacyStatus: Literal['public', 'unlisted', 'private'] | None = Field(None)
    facebook_page_id: str | None = Field(None, description='[Facebook] Facebook Page ID where the video will be posted. Required for Facebook. Auto-detected if only one page is connected.')
    pinterest_board_id: str | None = Field(None, description='[Pinterest] Pinterest board ID to publish to. Required when platform includes pinterest.')


class UploadPostUploadTextConfig(_Input):
    """Upload text post."""
    operation: Literal['upload_text'] = Field('upload_text', json_schema_extra={"ui:hidden": True})
    user: str = Field(..., min_length=1, description='User profile identifier.')
    platforms: list[Literal['linkedin', 'x', 'facebook', 'threads', 'reddit', 'bluesky', 'google_business', 'discord', 'telegram']] = Field(..., min_length=1, description='Platform(s) to upload to.')
    title: str = Field(..., min_length=1, description='Default text content for the post.')
    description: str | None = Field(None, description='Optional extended body used on Reddit (becomes post text). Ignored elsewhere.')
    scheduled_date: str | None = Field(None, description='ISO-8601 date/time to schedule publishing. Cannot be used with `add_to_queue`.')
    timezone: str | None = Field(None, description='IANA timezone identifier. Defaults to UTC.')
    async_upload: bool | None = Field(None, description='If true, returns immediately with a `request_id`.')
    add_to_queue: bool | None = Field(None, description='If true, schedules to next queue slot.')
    first_comment: str | None = Field(None, description='Automatically post a first comment after publishing.')
    target_linkedin_page_id: str | None = Field(None, description='[LinkedIn] LinkedIn page ID to post to an organization page.')
    facebook_page_id: str | None = Field(None, description='[Facebook] Facebook Page ID. Required when platform includes facebook. Auto-detected if only one page is connected.')


class UploadPostUploadDocumentConfig(_Input):
    """Upload document."""
    operation: Literal['upload_document'] = Field('upload_document', json_schema_extra={"ui:hidden": True})
    user: str = Field(..., min_length=1, description='User profile identifier.')
    platforms: list[Literal['linkedin']] = Field(..., min_length=1, description='Must be ["linkedin"]. Only LinkedIn supports document uploads.')
    document: str = Field(..., min_length=1, description='The document file (PDF, PPT, PPTX, DOC, DOCX) or a public URL. Max 100MB, 300 pages.')
    title: str = Field(..., min_length=1, description='Document title displayed on the post.')
    description: str | None = Field(None, description='Post commentary/text that appears above the document.')
    visibility: Literal['PUBLIC', 'CONNECTIONS', 'LOGGED_IN', 'CONTAINER'] | None = Field(None)
    target_linkedin_page_id: str | None = Field(None, description='LinkedIn page ID to post to a company page instead of personal profile.')


class UploadPostGetUploadStatusConfig(_Input):
    """Get upload status."""
    operation: Literal['get_upload_status'] = Field('get_upload_status', json_schema_extra={"ui:hidden": True})
    request_id: str | None = Field(None, min_length=1, description='The request identifier returned by upload endpoints when `async_upload=true`.')
    job_id: str | None = Field(None, description='The job identifier returned by scheduled posts (with `scheduled_date`).')


class UploadPostGetUploadHistoryConfig(_Input):
    """Get upload history."""
    operation: Literal['get_upload_history'] = Field('get_upload_history', json_schema_extra={"ui:hidden": True})
    page: int | None = Field(None, ge=1, description='Page number (starts at 1).')
    limit: Literal[10, 20, 50, 100] | None = Field(None, description='Number of items per page.')


class UploadPostListScheduledPostsConfig(_Input):
    """List scheduled posts."""
    operation: Literal['list_scheduled_posts'] = Field('list_scheduled_posts', json_schema_extra={"ui:hidden": True})


class UploadPostGetScheduledPostConfig(_Input):
    """Get a scheduled post."""
    operation: Literal['get_scheduled_post'] = Field('get_scheduled_post', json_schema_extra={"ui:hidden": True})
    job_id: str = Field(..., min_length=1, description='The unique job identifier.')


class UploadPostEditScheduledPostConfig(_Input):
    """Edit a scheduled post."""
    operation: Literal['edit_scheduled_post'] = Field('edit_scheduled_post', json_schema_extra={"ui:hidden": True})
    job_id: str = Field(..., min_length=1, description='The unique job identifier.')
    scheduled_date: str | None = Field(None, description='New ISO-8601 date/time in UTC. Must be in the future and within 1 year.')
    title: str | None = Field(None, description='New post title/caption, applied to every platform of the post.')
    caption: str | None = Field(None, description='New caption/description, applied to every platform of the post.')
    timezone: str | None = Field(None, description='IANA timezone; when set, scheduled_date is read in it.')
    remove_cover: bool | None = Field(None, description='Remove the stored cover image.')


class UploadPostCancelScheduledPostConfig(_Input):
    """Cancel a scheduled post."""
    operation: Literal['cancel_scheduled_post'] = Field('cancel_scheduled_post', json_schema_extra={"ui:hidden": True})
    job_id: str = Field(..., min_length=1, description='The unique job identifier.')


class UploadPostGetQueueSettingsConfig(_Input):
    """Get queue settings."""
    operation: Literal['get_queue_settings'] = Field('get_queue_settings', json_schema_extra={"ui:hidden": True})
    profile_username: str = Field(..., min_length=1, description='The profile username.')


class UploadPostUpdateQueueSettingsConfig(_Input):
    """Update queue settings."""
    operation: Literal['update_queue_settings'] = Field('update_queue_settings', json_schema_extra={"ui:hidden": True})
    profile_username: str = Field(..., min_length=1, description='The profile to update settings for.')
    timezone: str | None = Field(None, description="IANA timezone (e.g., 'Europe/London').")
    slots: list[QueueSlot] | None = Field(None, max_length=24, description='Array of slot objects. Max 24 slots.')
    days_of_week: list[Annotated[int, Field(ge=0, le=6)]] | None = Field(None, description='Active days: 0=Monday, 1=Tuesday, ..., 6=Sunday.')


class UploadPostGetQueuePreviewConfig(_Input):
    """Preview queue slots."""
    operation: Literal['get_queue_preview'] = Field('get_queue_preview', json_schema_extra={"ui:hidden": True})
    profile_username: str = Field(..., min_length=1, description='The profile username.')
    count: int | None = Field(None, le=50, description='Number of slots to return.')


class UploadPostGetNextQueueSlotConfig(_Input):
    """Get next available queue slot."""
    operation: Literal['get_next_queue_slot'] = Field('get_next_queue_slot', json_schema_extra={"ui:hidden": True})
    profile_username: str = Field(..., min_length=1, description='The profile username.')


class UploadPostGetAnalyticsConfig(_Input):
    """Get analytics."""
    operation: Literal['get_analytics'] = Field('get_analytics', json_schema_extra={"ui:hidden": True})
    profile_username: str = Field(..., min_length=1, description='The unique username of the profile.')
    platforms: str = Field(..., min_length=1, description='Comma-separated list of platforms: instagram, tiktok, linkedin, facebook, x, youtube, threads, pinterest, reddit, bluesky.')
    page_id: str | None = Field(None, description='Required for Facebook analytics. The Facebook Page ID.')
    page_urn: str | None = Field(None, description="LinkedIn only. Organization/company page URN or numeric ID to fetch analytics for. LinkedIn analytics are available only for organization/company pages you administer — personal profiles are not supported, because LinkedIn's API does not expose member-level analytics. If omitted, the first administered organization page is used.")


class UploadPostGetFacebookPagesConfig(_Input):
    """Get Facebook pages."""
    operation: Literal['get_facebook_pages'] = Field('get_facebook_pages', json_schema_extra={"ui:hidden": True})
    profile: str | None = Field(None, description='Profile username. If not specified, returns all pages for your account.')


class UploadPostGetLinkedinPagesConfig(_Input):
    """Get LinkedIn pages."""
    operation: Literal['get_linkedin_pages'] = Field('get_linkedin_pages', json_schema_extra={"ui:hidden": True})
    profile: str | None = Field(None, description='Profile username. If omitted, returns pages from all connected LinkedIn accounts.')


class UploadPostGetPinterestBoardsConfig(_Input):
    """Get Pinterest boards."""
    operation: Literal['get_pinterest_boards'] = Field('get_pinterest_boards', json_schema_extra={"ui:hidden": True})
    profile: str | None = Field(None, description='Profile username. If omitted, uses the first connected Pinterest account.')


class UploadPostGetCurrentUserConfig(_Input):
    """Get current user."""
    operation: Literal['get_current_user'] = Field('get_current_user', json_schema_extra={"ui:hidden": True})


class UploadPostCreateProfileConfig(_Input):
    """Create user profile."""
    operation: Literal['create_profile'] = Field('create_profile', json_schema_extra={"ui:hidden": True})
    username: str = Field(..., min_length=1, description='A unique identifier for the user on your platform. It is the `user` value of every API call and cannot be changed later.')
    display_name: str | None = Field(None, max_length=100, description='Optional label shown in the dashboard instead of the username. Can be changed later with PATCH /uploadposts/users/{username}.')


class UploadPostListProfilesConfig(_Input):
    """List user profiles."""
    operation: Literal['list_profiles'] = Field('list_profiles', json_schema_extra={"ui:hidden": True})


class UploadPostGetProfileConfig(_Input):
    """Get a specific user profile."""
    operation: Literal['get_profile'] = Field('get_profile', json_schema_extra={"ui:hidden": True})
    username: str = Field(..., min_length=1, description='The username of the profile to retrieve.')


class UploadPostRenameProfileConfig(_Input):
    """Rename a user profile."""
    operation: Literal['rename_profile'] = Field('rename_profile', json_schema_extra={"ui:hidden": True})
    username: str = Field(..., min_length=1, description='The username of the profile to rename. It is not changed.')
    display_name: str | None = Field(..., max_length=100, description='New label. Trimmed; no line breaks. Empty string or null clears it.')


class UploadPostGetMediaConfig(_Input):
    """Get media list."""
    operation: Literal['get_media'] = Field('get_media', json_schema_extra={"ui:hidden": True})
    platform: Literal['instagram', 'tiktok', 'youtube', 'linkedin', 'facebook', 'x', 'threads', 'pinterest', 'bluesky', 'reddit'] = Field(..., min_length=1, description='The platform to retrieve media from.')
    user: str = Field(..., min_length=1, description='Profile username as configured in Upload-Post.')
    page_urn: str | None = Field(None, description="LinkedIn only. Selects which LinkedIn page to fetch posts from. Accepts a numeric organization ID (e.g., 12345), a full URN (e.g., urn:li:organization:12345), or 'me' to force the connected member's personal profile. If omitted, accounts connected as an organization admin auto-resolve to their first administered organization; otherwise the personal profile is used.")
    limit: int | None = Field(None, ge=1, le=100, description="Number of media items to return. Defaults to 25 and is clamped to 1-100, then capped again by the platform's own maximum page size: Instagram/Facebook/Threads/Bluesky/X/Pinterest/Reddit/LinkedIn 100, YouTube 50, TikTok 20.")
    cursor: str | None = Field(None, description='Opaque next-page token. Pass back exactly the value returned in pagination.next_cursor by the previous response. Not supported on LinkedIn, Discord and Telegram: sending a cursor for those platforms returns 400 with a message naming the platform.')


class UploadPostGetCommentsConfig(_Input):
    """List post comments (multi-platform)."""
    operation: Literal['get_comments'] = Field('get_comments', json_schema_extra={"ui:hidden": True})
    platform: Literal['instagram', 'facebook', 'youtube', 'linkedin', 'tiktok'] | None = Field(None, description="Platform to list comments from. Defaults to 'instagram'.")
    user: str = Field(..., min_length=1, description='Profile username as configured in Upload-Post.')
    post_id: str | None = Field(None, min_length=1, description='Post identifier. YouTube = the video ID; LinkedIn = the post URN (urn:li:ugcPost:...); Instagram = numeric media ID. Use post_id or post_url (one is required).')
    post_url: str | None = Field(None, description='Full post URL. Alternative to post_id.')
    limit: int | None = Field(None, ge=1, description='Maximum comments to return per page.')
    after: str | None = Field(None, description='Pagination cursor returned in `pagination.next_cursor` of the previous response. Pass it back to fetch the next page.')
    comment_id: str | None = Field(None, description="TikTok only. Returns the replies hanging off this comment instead of the post's top-level comments - the same question narrowed to a parent, not a separate URL. post_id is still required. TikTok indexes a newly created comment asynchronously: listing within ~10 seconds of writing one returns a list without it.")


class UploadPostRetryPostConfig(_Input):
    """Retry a failed upload."""
    operation: Literal['retry_post'] = Field('retry_post', json_schema_extra={"ui:hidden": True})
    request_id: str | None = Field(None, min_length=1, description='The request_id returned by the original async upload. Provide request_id or job_id.')
    job_id: str | None = Field(None, description='The scheduled job ID. Alternative to request_id.')


# Upload Post's own MCP server: agents get its tools through a person's Upload Post sign-in.
UploadPostMcpCredential = mcp_credential("upload_post", "https://mcp.upload-post.com/mcp", app="Upload Post")
UploadPostCredential = Union[UploadPostAPIKeyCredential, UploadPostMcpCredential]


UploadPostConfig = Annotated[Union[
    UploadPostUploadVideoConfig,
    UploadPostUploadTextConfig,
    UploadPostUploadDocumentConfig,
    UploadPostGetUploadStatusConfig,
    UploadPostGetUploadHistoryConfig,
    UploadPostListScheduledPostsConfig,
    UploadPostGetScheduledPostConfig,
    UploadPostEditScheduledPostConfig,
    UploadPostCancelScheduledPostConfig,
    UploadPostGetQueueSettingsConfig,
    UploadPostUpdateQueueSettingsConfig,
    UploadPostGetQueuePreviewConfig,
    UploadPostGetNextQueueSlotConfig,
    UploadPostGetAnalyticsConfig,
    UploadPostGetFacebookPagesConfig,
    UploadPostGetLinkedinPagesConfig,
    UploadPostGetPinterestBoardsConfig,
    UploadPostGetCurrentUserConfig,
    UploadPostCreateProfileConfig,
    UploadPostListProfilesConfig,
    UploadPostGetProfileConfig,
    UploadPostRenameProfileConfig,
    UploadPostGetMediaConfig,
    UploadPostGetCommentsConfig,
    UploadPostRetryPostConfig
], Field(discriminator="operation")]


class UploadPostFullConfig(NodeConfig[UploadPostConfig, UploadPostCredential]):
    pass


OPERATIONS = {'upload_video': {'method': 'POST',
                  'path': '/upload',
                  'path_fields': [],
                  'query_fields': [],
                  'body_fields': ['user',
                                  'platform[]',
                                  'video',
                                  'title',
                                  'description',
                                  'scheduled_date',
                                  'timezone',
                                  'async_upload',
                                  'add_to_queue',
                                  'first_comment',
                                  'privacy_level',
                                  'visibility',
                                  'target_linkedin_page_id',
                                  'privacyStatus',
                                  'facebook_page_id',
                                  'pinterest_board_id'],
                  'multipart': True},
 'upload_text': {'method': 'POST',
                 'path': '/upload_text',
                 'path_fields': [],
                 'query_fields': [],
                 'body_fields': ['user',
                                 'platform[]',
                                 'title',
                                 'description',
                                 'scheduled_date',
                                 'timezone',
                                 'async_upload',
                                 'add_to_queue',
                                 'first_comment',
                                 'target_linkedin_page_id',
                                 'facebook_page_id'],
                 'multipart': True},
 'upload_document': {'method': 'POST',
                     'path': '/upload_document',
                     'path_fields': [],
                     'query_fields': [],
                     'body_fields': ['user',
                                     'platform[]',
                                     'document',
                                     'title',
                                     'description',
                                     'visibility',
                                     'target_linkedin_page_id'],
                     'multipart': True},
 'get_upload_status': {'method': 'GET',
                       'path': '/uploadposts/status',
                       'path_fields': [],
                       'query_fields': ['request_id', 'job_id'],
                       'body_fields': [],
                       'multipart': False},
 'get_upload_history': {'method': 'GET',
                        'path': '/uploadposts/history',
                        'path_fields': [],
                        'query_fields': ['page', 'limit'],
                        'body_fields': [],
                        'multipart': False},
 'list_scheduled_posts': {'method': 'GET',
                          'path': '/uploadposts/schedule',
                          'path_fields': [],
                          'query_fields': [],
                          'body_fields': [],
                          'multipart': False},
 'get_scheduled_post': {'method': 'GET',
                        'path': '/uploadposts/schedule/{job_id}',
                        'path_fields': ['job_id'],
                        'query_fields': [],
                        'body_fields': [],
                        'multipart': False},
 'edit_scheduled_post': {'method': 'PATCH',
                         'path': '/uploadposts/schedule/{job_id}',
                         'path_fields': ['job_id'],
                         'query_fields': [],
                         'body_fields': ['scheduled_date', 'title', 'caption', 'timezone', 'remove_cover'],
                         'multipart': False},
 'cancel_scheduled_post': {'method': 'DELETE',
                           'path': '/uploadposts/schedule/{job_id}',
                           'path_fields': ['job_id'],
                           'query_fields': [],
                           'body_fields': [],
                           'multipart': False},
 'get_queue_settings': {'method': 'GET',
                        'path': '/uploadposts/queue/settings',
                        'path_fields': [],
                        'query_fields': ['profile_username'],
                        'body_fields': [],
                        'multipart': False},
 'update_queue_settings': {'method': 'POST',
                           'path': '/uploadposts/queue/settings',
                           'path_fields': [],
                           'query_fields': [],
                           'body_fields': ['profile_username', 'timezone', 'slots', 'days_of_week'],
                           'multipart': False},
 'get_queue_preview': {'method': 'GET',
                       'path': '/uploadposts/queue/preview',
                       'path_fields': [],
                       'query_fields': ['profile_username', 'count'],
                       'body_fields': [],
                       'multipart': False},
 'get_next_queue_slot': {'method': 'GET',
                         'path': '/uploadposts/queue/next-slot',
                         'path_fields': [],
                         'query_fields': ['profile_username'],
                         'body_fields': [],
                         'multipart': False},
 'get_analytics': {'method': 'GET',
                   'path': '/analytics/{profile_username}',
                   'path_fields': ['profile_username'],
                   'query_fields': ['platforms', 'page_id', 'page_urn'],
                   'body_fields': [],
                   'multipart': False},
 'get_facebook_pages': {'method': 'GET',
                        'path': '/uploadposts/facebook/pages',
                        'path_fields': [],
                        'query_fields': ['profile'],
                        'body_fields': [],
                        'multipart': False},
 'get_linkedin_pages': {'method': 'GET',
                        'path': '/uploadposts/linkedin/pages',
                        'path_fields': [],
                        'query_fields': ['profile'],
                        'body_fields': [],
                        'multipart': False},
 'get_pinterest_boards': {'method': 'GET',
                          'path': '/uploadposts/pinterest/boards',
                          'path_fields': [],
                          'query_fields': ['profile'],
                          'body_fields': [],
                          'multipart': False},
 'get_current_user': {'method': 'GET',
                      'path': '/uploadposts/me',
                      'path_fields': [],
                      'query_fields': [],
                      'body_fields': [],
                      'multipart': False},
 'create_profile': {'method': 'POST',
                    'path': '/uploadposts/users',
                    'path_fields': [],
                    'query_fields': [],
                    'body_fields': ['username', 'display_name'],
                    'multipart': False},
 'list_profiles': {'method': 'GET',
                   'path': '/uploadposts/users',
                   'path_fields': [],
                   'query_fields': [],
                   'body_fields': [],
                   'multipart': False},
 'get_profile': {'method': 'GET',
                 'path': '/uploadposts/users/{username}',
                 'path_fields': ['username'],
                 'query_fields': [],
                 'body_fields': [],
                 'multipart': False},
 'rename_profile': {'method': 'PATCH',
                    'path': '/uploadposts/users/{username}',
                    'path_fields': ['username'],
                    'query_fields': [],
                    'body_fields': ['display_name'],
                    'multipart': False},
 'get_media': {'method': 'GET',
               'path': '/uploadposts/media',
               'path_fields': [],
               'query_fields': ['platform', 'user', 'page_urn', 'limit', 'cursor'],
               'body_fields': [],
               'multipart': False},
 'get_comments': {'method': 'GET',
                  'path': '/uploadposts/comments',
                  'path_fields': [],
                  'query_fields': ['platform', 'user', 'post_id', 'post_url', 'limit', 'after', 'comment_id'],
                  'body_fields': [],
                  'multipart': False},
 'retry_post': {'method': 'POST',
                'path': '/uploadposts/posts/retry',
                'path_fields': [],
                'query_fields': [],
                'body_fields': ['request_id', 'job_id'],
                'multipart': False}}


class UploadPostNode(WorkflowNode):
    integration_type = "automation-upload-post"
    credential_provider_labels = {"upload_post": "Upload Post Account"}
    connection_evidence = ConnectionEvidence(noun="Upload Post account", identity_operation="get_current_user")

    @classmethod
    def get_config_model(cls):
        return UploadPostFullConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect an Upload Post API key")
        config = self.config.config
        route = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True)
        path = route["path"]
        for key in route["path_fields"]:
            path = path.replace("{" + key + "}", quote(str(values[key]), safe=""))
        params = {key: values[key] for key in route["query_fields"] if key in values}
        body = {}
        for key in route["body_fields"]:
            source = "platforms" if key == "platform[]" else key
            if source in values:
                body[key] = values[source]
        if config.operation == "rename_profile":
            body["display_name"] = config.display_name
        kwargs = {"params": params, "headers": {"Authorization": "Apikey " + credential.api_key, "Accept": "application/json"}}
        if route["multipart"]:
            parts = []
            for key, value in body.items():
                for item in value if isinstance(value, list) else [value]:
                    text = json.dumps(item) if isinstance(item, bool) else str(item)
                    parts.append((key, (None, text)))
            kwargs["files"] = parts
        elif route["body_fields"]:
            kwargs["json"] = body
        async with guarded_async_client(timeout=90, follow_redirects=False, trust_env=False) as client:
            response = await client.request(route["method"], BASE_URL + path, **kwargs)
        if not 200 <= response.status_code < 300:
            # Keep the provider's refusal verbatim so connection evidence can explain it.
            raise ValueError(f"Upload Post HTTP {response.status_code}: {response.text[:1000].replace(credential.api_key, '[redacted]')}")
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError("Upload Post returned an unexpected JSON response")
        if result.get("success") is False or result.get("error"):
            raise ValueError("Upload Post: " + str(result.get("error") or result.get("message") or "Request failed").replace(credential.api_key, "[redacted]"))
        await self.emit(result)
        return result
