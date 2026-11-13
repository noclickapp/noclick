"""Bulkpublish publishing and reporting operations using a personal API key.

Each operation makes one documented API request. Responses retain provider
pagination and metric-support metadata so callers can interpret them correctly.
"""
from __future__ import annotations

import json

from datetime import date, datetime
from typing import Annotated, Literal, Union
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://app.bulkpublish.com"
ID_ARRAY = r"^\[\s*[1-9][0-9]*(?:\s*,\s*[1-9][0-9]*)*\s*\]$"
OPTIONAL_ID_ARRAY = r"^\[\s*(?:[1-9][0-9]*(?:\s*,\s*[1-9][0-9]*)*)?\s*\]$"


class BulkpublishAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Bulkpublish API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://app.bulkpublish.com/developer",
        "x-credential-instructions": "Create an API key in Bulkpublish Settings > API Keys and paste it here without the Bearer prefix. Requests use the permissions of the member who owns the key.",
    })
    credential_type: Literal["bulkpublish_api_key"] = Field("bulkpublish_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, repr=False,
                         json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    page: int = Field(1, ge=1, description="Page number. This operation returns one page; increment to read the next.")
    limit: int = Field(20, ge=1, le=500)


class _Post(_Input):
    post_id: PositiveInt = Field(..., title="Post ID")


class _Channel(_Input):
    channel_id: PositiveInt = Field(..., title="Channel ID")


class _Media(_Input):
    media_id: PositiveInt = Field(..., title="Media ID")


class _Label(_Input):
    label_id: PositiveInt = Field(..., title="Label ID")


class _Schedule(_Input):
    schedule_id: PositiveInt = Field(..., title="Schedule ID")


# BulkPublish's own MCP server: agents get its tools through a person's BulkPublish sign-in.
BulkpublishMcpCredential = mcp_credential("bulkpublish", "https://mcp.bulkpublish.com/", app="BulkPublish")
BulkpublishCredential = Union[BulkpublishAPIKeyCredential, BulkpublishMcpCredential]


def _timezone(value):
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("Use an IANA timezone such as UTC") from None
    return value


class ListPosts(_Page):
    """Read one page of posts, with optional status, channel and text filters."""
    operation: Literal["list_posts"] = "list_posts"
    status: Literal["draft", "scheduled", "publishing", "published", "processing", "failed", "partial"] | None = None
    channel_id: PositiveInt | None = None
    search: str | None = Field(None, max_length=1000)
    from_date: date | None = None
    to_date: date | None = None
    order: Literal["asc", "desc"] = "desc"


class GetPost(_Post):
    operation: Literal["get_post"] = "get_post"


class _PostContent(_Input):
    content: str = Field(..., max_length=63206, json_schema_extra={"ui:widget": "textarea"})
    media_ids: str | None = Field(None, max_length=2000, pattern=OPTIONAL_ID_ARRAY, description="JSON array of existing media IDs, e.g. [12,15]. Use [] to remove media.", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    label_ids: str | None = Field(None, max_length=2000, pattern=OPTIONAL_ID_ARRAY, description="JSON array of label IDs; [] clears labels.", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    status: Literal["draft", "scheduled"] = "draft"
    scheduled_at: datetime | None = Field(None, description="Future time with timezone, required when scheduling.")

    @field_validator("scheduled_at")
    @classmethod
    def aware_time(cls, value):
        if value is not None and value.utcoffset() is None:
            raise ValueError("Include a timezone in the scheduled time")
        return value


class CreatePost(_PostContent):
    """Create a text or media post as a draft, or schedule it for later."""
    operation: Literal["create_post"] = "create_post"
    channel_ids: str = Field(..., max_length=2000, pattern=ID_ARRAY, description="JSON array of target channel IDs, e.g. [12,15].", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    timezone: str = Field("UTC", description="IANA timezone")
    _tz = field_validator("timezone")(_timezone)

    @model_validator(mode="after")
    def schedule_time(self):
        if self.status == "scheduled" and self.scheduled_at is None:
            raise ValueError("A scheduled post requires scheduled_at")
        if not self.content.strip() and not (self.media_ids and json.loads(self.media_ids)):
            raise ValueError("Provide post text or uploaded media IDs")
        return self


class UpdatePost(_Post, _PostContent):
    """Replace post text and optionally its media, labels and scheduling state."""
    operation: Literal["update_post"] = "update_post"
    content: str | None = Field(None, max_length=63206, json_schema_extra={"ui:widget": "textarea"})
    status: Literal["draft", "scheduled"] | None = None
    if_unmodified_since: datetime | None = Field(None, description="Optional updatedAt precondition from the last read; preserve milliseconds.")


class DeletePost(_Post):
    operation: Literal["delete_post"] = "delete_post"


class PublishPost(_Post):
    """Start publishing immediately; acceptance does not mean every channel is published."""
    operation: Literal["publish_post"] = "publish_post"


class RetryPost(_Post):
    """Retry failed platforms. Opting into unconfirmed platforms can duplicate a post."""
    operation: Literal["retry_post"] = "retry_post"
    republish: bool = Field(False, description="Also retry unconfirmed platforms; this can create duplicate posts.")


class GetPostMetrics(_Post):
    """Read stored platform metrics, retaining supportedMetrics and metricsSupported."""
    operation: Literal["get_post_metrics"] = "get_post_metrics"


class ListChannels(_Input):
    operation: Literal["list_channels"] = "list_channels"
    active: bool = Field(True, description="False includes up to 100 disconnected channels as well as active ones.")


class GetChannel(_Channel):
    operation: Literal["get_channel"] = "get_channel"


class GetChannelHealth(_Channel):
    operation: Literal["get_channel_health"] = "get_channel_health"


class ListMedia(_Page):
    operation: Literal["list_media"] = "list_media"
    search: str | None = Field(None, max_length=1000)
    media_type: Literal["image", "video", "document"] | None = None


class GetMedia(_Media):
    operation: Literal["get_media"] = "get_media"


class DeleteMedia(_Media):
    operation: Literal["delete_media"] = "delete_media"


class UpdateMedia(_Media):
    """Set a media file's alternative text, or clear it with null."""
    operation: Literal["update_media"] = "update_media"
    alt_text: str | None = Field(..., max_length=1000)


class _Analytics(_Input):
    from_date: date = Field(..., title="Start date")
    to_date: date = Field(..., title="End date")
    timezone: str = "UTC"
    channel_ids: str | None = Field(None, pattern=r"^[0-9]+(,[0-9]+)*$", description="Comma-separated channel IDs.")
    _tz = field_validator("timezone")(_timezone)

    @model_validator(mode="after")
    def ordered_dates(self):
        if self.to_date < self.from_date:
            raise ValueError("End date must not precede start date")
        return self


class GetAnalyticsSummary(_Analytics):
    operation: Literal["get_analytics_summary"] = "get_analytics_summary"


class GetAnalyticsEngagement(_Analytics):
    operation: Literal["get_analytics_engagement"] = "get_analytics_engagement"


class ListLabels(_Input):
    operation: Literal["list_labels"] = "list_labels"
    label_type: Literal["post", "media"] | None = None


class _LabelContent(_Input):
    name: str = Field(..., min_length=1, max_length=100)
    color: str | None = Field(None, pattern=r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

    @field_validator("name")
    @classmethod
    def nonempty_name(cls, value):
        if not value.strip():
            raise ValueError("Label name must not be blank")
        return value.strip()


class CreateLabel(_LabelContent):
    operation: Literal["create_label"] = "create_label"
    label_type: Literal["post", "media"] = "post"


class UpdateLabel(_Label, _LabelContent):
    operation: Literal["update_label"] = "update_label"


class DeleteLabel(_Label):
    operation: Literal["delete_label"] = "delete_label"


class ListSchedules(_Input):
    operation: Literal["list_schedules"] = "list_schedules"


class CreateSchedule(_Input):
    """Create a recurring schedule; posts materialize only when it runs."""
    operation: Literal["create_schedule"] = "create_schedule"
    name: str = Field(..., min_length=1, max_length=500)
    frequency: Literal["daily", "weekly", "biweekly", "monthly"] = "daily"
    time_of_day: str = Field(..., pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
    timezone: str = "UTC"
    channel_ids: str = Field(..., max_length=2000, pattern=ID_ARRAY, description="JSON array of target channel IDs, e.g. [12,15].", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    content_template: str = Field(..., min_length=1, max_length=63206, json_schema_extra={"ui:widget": "textarea"})
    day_of_week: int | None = Field(None, ge=0, le=6)
    day_of_month: int | None = Field(None, ge=1, le=31)
    is_active: bool = True
    require_approval: bool = False
    _tz = field_validator("timezone")(_timezone)

    @model_validator(mode="after")
    def frequency_day(self):
        if self.frequency in {"weekly", "biweekly"} and self.day_of_week is None:
            raise ValueError("Weekly schedules need day_of_week (0=Sunday)")
        if self.frequency == "monthly" and self.day_of_month is None:
            raise ValueError("Monthly schedules need day_of_month")
        return self


class GetSchedule(_Schedule):
    operation: Literal["get_schedule"] = "get_schedule"


class DeleteSchedule(_Schedule):
    operation: Literal["delete_schedule"] = "delete_schedule"


Operation = Annotated[Union[
    ListPosts, GetPost, CreatePost, UpdatePost, DeletePost, PublishPost, RetryPost,
    GetPostMetrics, ListChannels, GetChannel, GetChannelHealth, ListMedia, GetMedia,
    DeleteMedia, UpdateMedia, GetAnalyticsSummary, GetAnalyticsEngagement,
    ListLabels, CreateLabel, UpdateLabel, DeleteLabel, ListSchedules, CreateSchedule,
    GetSchedule, DeleteSchedule,
], Field(discriminator="operation")]


class BulkpublishNodeConfig(NodeConfig[Operation, BulkpublishCredential]):
    pass


# Explicit one-to-one routes: never accept a URL, method or arbitrary body from config.
ROUTES = {
    "list_posts": ("GET", "/api/posts"), "get_post": ("GET", "/api/posts/{post_id}"),
    "create_post": ("POST", "/api/posts"), "update_post": ("PUT", "/api/posts/{post_id}"),
    "delete_post": ("DELETE", "/api/posts/{post_id}"),
    "publish_post": ("POST", "/api/posts/{post_id}/publish"),
    "retry_post": ("POST", "/api/posts/{post_id}/retry"),
    "get_post_metrics": ("GET", "/api/posts/{post_id}/metrics"),
    "list_channels": ("GET", "/api/channels"), "get_channel": ("GET", "/api/channels/{channel_id}"),
    "get_channel_health": ("GET", "/api/channels/{channel_id}/health"),
    "list_media": ("GET", "/api/media"), "get_media": ("GET", "/api/media/{media_id}"),
    "delete_media": ("DELETE", "/api/media/{media_id}"), "update_media": ("PATCH", "/api/media/{media_id}"),
    "get_analytics_summary": ("GET", "/api/analytics/summary"),
    "get_analytics_engagement": ("GET", "/api/analytics/engagement"),
    "list_labels": ("GET", "/api/labels"), "create_label": ("POST", "/api/labels"),
    "update_label": ("PUT", "/api/labels/{label_id}"), "delete_label": ("DELETE", "/api/labels/{label_id}"),
    "list_schedules": ("GET", "/api/schedules"), "create_schedule": ("POST", "/api/schedules"),
    "get_schedule": ("GET", "/api/schedules/{schedule_id}"), "delete_schedule": ("DELETE", "/api/schedules/{schedule_id}"),
}
WIRE_NAMES = {
    "channel_id": "channelId", "media_ids": "mediaFiles", "label_ids": "labels",
    "scheduled_at": "scheduledAt", "from_date": "from", "to_date": "to",
    "media_type": "type", "label_type": "type", "alt_text": "altText",
    "if_unmodified_since": "ifUnmodifiedSince", "channel_ids": "channelIds",
    "time_of_day": "timeOfDay", "content_template": "contentTemplate",
    "day_of_week": "dayOfWeek", "day_of_month": "dayOfMonth", "is_active": "isActive",
    "require_approval": "requireApproval",
}


def _redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[redacted]")
    if isinstance(value, dict):
        return {k: _redact(v, key) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, key) for v in value]
    return value


class BulkpublishNode(WorkflowNode):
    integration_type = "automation-bulkpublish"
    credential_provider_labels = {"bulkpublish": "BulkPublish Account"}
    connection_evidence = ConnectionEvidence(noun="channels", operation="list_channels", label_keys=("accountName", "name", "id"))

    @classmethod
    def get_config_model(cls):
        return BulkpublishNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Bulkpublish API key")
        op = self.config.config
        method, template = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        path = template
        for name in ("post_id", "channel_id", "media_id", "label_id", "schedule_id"):
            if "{" + name + "}" in path:
                path = path.replace("{" + name + "}", str(values.pop(name)))
        for name in ("media_ids", "label_ids"):
            if name in values:
                values[name] = json.loads(values[name])
        if isinstance(op, (CreatePost, CreateSchedule)):
            values["channel_ids"] = json.loads(values["channel_ids"])
        wire = {WIRE_NAMES.get(k, k): v for k, v in values.items()}
        if isinstance(op, CreatePost):
            wire["channels"] = [{"channelId": n} for n in wire.pop("channelIds")]
        if isinstance(op, _Analytics):
            wire["tz"] = wire.pop("timezone")
        if isinstance(op, UpdateMedia):
            wire["altText"] = op.alt_text  # Explicit null clears alt text.
        key = self.config.credentials.api_key
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
                **({"params": wire} if method == "GET" else {"json": wire} if wire else {}))
        if len(response.content) > 10_000_000:
            raise ValueError("Bulkpublish response exceeds 10 MB")
        if response.is_redirect:
            raise ValueError("Bulkpublish returned an unexpected redirect")
        if not response.content or response.status_code == 204:
            body = None
        else:
            try:
                body = response.json()
            except ValueError:
                if response.is_success:
                    raise ValueError("Bulkpublish returned a non-JSON success response") from None
                body = response.text
            body = _redact(body, key)
        if not response.is_success or isinstance(body, dict) and (body.get("error") or body.get("success") is False):
            return {"status": "error", "http_status": response.status_code, "error": body}
        output = {"status": "success", "http_status": response.status_code, "data": body}
        if isinstance(op, ListChannels):
            if not isinstance(body, dict) or not isinstance(body.get("channels"), list):
                raise ValueError("Bulkpublish channel response is missing channels")
            output["items"] = body["channels"]
        await self.emit(output)
        return output
