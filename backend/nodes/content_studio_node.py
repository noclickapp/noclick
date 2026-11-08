"""ContentStudio v1 publishing and workspace operations with a pasted API key.

Each action sends one request to the provider's published contract. List actions
return a single page and retain the provider's pagination fields.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.contentstudio.io"
ResourceID = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")]
Color = Annotated[str, Field(pattern=r"^color_([1-9]|1[0-9]|20)$")]


class ContentStudioAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Content Studio API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.contentstudio.io/articles/contentstudio-api-f955a6ab",
            "x-credential-instructions": "In ContentStudio, open the API module, generate an API key on the API tab, and paste it here. NoClick sends it in the X-API-Key header and reads your workspaces to check the connection.",
        })
    credential_type: Literal["content_studio_api_key"] = Field("content_studio_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096,
        repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste the API key as text")
        value = clean_secret(value, field_name="API key", key=True)
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header or prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    page: int = Field(1, ge=1, description="Page number. List actions return one page at a time.")
    per_page: int = Field(10, ge=1, le=100)


class _Workspace(_Input):
    workspace_id: ResourceID


class _WorkspacePage(_Page, _Workspace):
    search: str | None = Field(None, max_length=255)


class GetMe(_Input):
    operation: Literal["get_me"] = "get_me"


class ListWorkspaces(_Page):
    operation: Literal["list_workspaces"] = "list_workspaces"


class ListAccounts(_WorkspacePage):
    operation: Literal["list_accounts"] = "list_accounts"
    platform: Literal["facebook", "twitter", "linkedin", "pinterest", "instagram", "gmb", "youtube", "tiktok", "tumblr", "threads", "bluesky", "telegram"] | None = None


class ListPosts(_Page, _Workspace):
    operation: Literal["list_posts"] = "list_posts"
    status: list[Literal["draft", "scheduled", "published", "failed", "rejected", "under_review", "missed_review", "partially_failed", "in_progress", "processing", "notification_sent", "notification_declined"]] | None = Field(None, max_length=12)
    date_from: date | None = None
    date_to: date | None = None
    labels: list[ResourceID] | None = Field(None, max_length=100)
    campaigns: list[ResourceID] | None = Field(None, max_length=100)
    content_category: list[ResourceID] | None = Field(None, max_length=100)
    created_by: list[ResourceID] | None = Field(None, max_length=100)
    approval_assigned_to: list[ResourceID] | None = Field(None, max_length=100)
    approval_requested_by: list[ResourceID] | None = Field(None, max_length=100)
    comment_status: Literal["resolved", "unresolved", "all"] | None = None

    @model_validator(mode="after")
    def dates(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("End date must be on or after start date")
        return self


class _PostID(_Workspace):
    post_id: ResourceID


class GetPost(_PostID):
    operation: Literal["get_post"] = "get_post"


class _PostBody(_Workspace):
    text: str = Field(..., min_length=1, max_length=5000, description="The complete common post caption.")
    accounts: list[ResourceID] = Field(..., min_length=1, max_length=100, description="Social account IDs from List Accounts.")
    publish_type: Literal["draft", "scheduled", "queued", "content_category"] = Field("draft", description="Draft saves without publishing. Scheduled requires a timestamp.")
    scheduled_at: datetime | None = Field(None, description="Required for scheduled posts; include the timezone.")

    @model_validator(mode="after")
    def schedule(self):
        if self.publish_type == "scheduled" and self.scheduled_at is None:
            raise ValueError("Scheduled posts require scheduled_at")
        if self.scheduled_at is not None and (self.scheduled_at.tzinfo is None or self.scheduled_at.utcoffset() is None):
            raise ValueError("Include a timezone in scheduled_at")
        return self


class CreatePost(_PostBody):
    """Create a draft, scheduled or queued post with optional library media."""
    operation: Literal["create_post"] = "create_post"
    media_ids: list[ResourceID] | None = Field(None, max_length=10, description="Existing content library IDs from List Media.")
    labels: list[ResourceID] | None = Field(None, max_length=20)
    campaign_id: ResourceID | None = None
    content_category_id: ResourceID | None = None
    post_type: Literal["feed", "feed+reel", "reel", "story", "feed+story", "feed+reel+story", "reel+story", "video", "shorts"] | None = None

    @model_validator(mode="after")
    def category(self):
        if self.publish_type == "content_category" and self.content_category_id is None:
            raise ValueError("Content category publishing requires content_category_id")
        return self


class UpdatePost(_PostBody, _PostID):
    """Replace a post's text, accounts and scheduling; supply all three."""
    operation: Literal["update_post"] = "update_post"
    # The update contract has no content_category_id field.
    publish_type: Literal["draft", "scheduled", "queued"] = "draft"


class DeletePost(_PostID):
    """Remove a post from ContentStudio, optionally also from social platforms."""
    operation: Literal["delete_post"] = "delete_post"
    delete_from_social: bool = Field(False, strict=True, description="Also attempt to delete the published social posts. Mixed results are returned per account.")
    account_ids: list[ResourceID] | None = Field(None, max_length=100)


class _CreateNamed(_Workspace):
    name: str = Field(..., min_length=1, max_length=100)
    color: Color = Field(..., description="Provider palette token: color_1 through color_20.")


class _UpdateNamed(_Workspace):
    name: str | None = Field(None, min_length=1, max_length=100)
    color: Color | None = None

    @model_validator(mode="after")
    def changed(self):
        if not any(getattr(self, field, None) is not None for field in ("name", "color", "accounts", "allowed_member_ids")):
            raise ValueError("Supply at least one field to update")
        return self


class _LabelID(_Workspace):
    label_id: ResourceID


class ListLabels(_WorkspacePage):
    operation: Literal["list_labels"] = "list_labels"


class CreateLabel(_CreateNamed):
    operation: Literal["create_label"] = "create_label"


class UpdateLabel(_UpdateNamed, _LabelID):
    operation: Literal["update_label"] = "update_label"


class DeleteLabel(_LabelID):
    operation: Literal["delete_label"] = "delete_label"


class _CampaignID(_Workspace):
    campaign_id: ResourceID


class ListCampaigns(_WorkspacePage):
    operation: Literal["list_campaigns"] = "list_campaigns"


class CreateCampaign(_CreateNamed):
    operation: Literal["create_campaign"] = "create_campaign"


class UpdateCampaign(_UpdateNamed, _CampaignID):
    operation: Literal["update_campaign"] = "update_campaign"


class DeleteCampaign(_CampaignID):
    operation: Literal["delete_campaign"] = "delete_campaign"


class _CategoryID(_Workspace):
    category_id: ResourceID


class _CategoryAccounts(_Workspace):
    accounts: list[ResourceID] | None = Field(None, max_length=100, description="Social account IDs. On update, replaces the full list.")
    allowed_member_ids: list[ResourceID] | None = Field(None, max_length=100, description="Restrict visibility to these workspace members.")


class ListContentCategories(_WorkspacePage):
    operation: Literal["list_content_categories"] = "list_content_categories"


class GetContentCategory(_CategoryID):
    operation: Literal["get_content_category"] = "get_content_category"


class CreateContentCategory(_CreateNamed, _CategoryAccounts):
    operation: Literal["create_content_category"] = "create_content_category"


class UpdateContentCategory(_UpdateNamed, _CategoryAccounts, _CategoryID):
    operation: Literal["update_content_category"] = "update_content_category"


class DeleteContentCategory(_CategoryID):
    operation: Literal["delete_content_category"] = "delete_content_category"


class ListMedia(_WorkspacePage):
    operation: Literal["list_media"] = "list_media"
    type: Literal["images", "videos"] | None = None
    sort: Literal["recent", "oldest", "size", "a2z", "z2a"] | None = None
    archived: bool | None = Field(None, strict=True)
    folder_id: ResourceID | None = None


class ListTeamMembers(_WorkspacePage):
    operation: Literal["list_team_members"] = "list_team_members"


class GetLimits(_Workspace):
    operation: Literal["get_limits"] = "get_limits"


ContentStudioConfig = Annotated[Union[
    GetMe, ListWorkspaces, ListAccounts, ListPosts, GetPost, CreatePost, UpdatePost,
    DeletePost, ListLabels, CreateLabel, UpdateLabel, DeleteLabel, ListCampaigns,
    CreateCampaign, UpdateCampaign, DeleteCampaign, ListContentCategories,
    GetContentCategory, CreateContentCategory, UpdateContentCategory,
    DeleteContentCategory, ListMedia, ListTeamMembers, GetLimits,
], Field(discriminator="operation")]


class ContentStudioFullConfig(NodeConfig[ContentStudioConfig, ContentStudioAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


ROUTES = {
    "get_me": ("GET", "/api/v1/me"),
    "list_workspaces": ("GET", "/api/v1/workspaces"),
    "list_accounts": ("GET", "/api/v1/workspaces/{workspace_id}/accounts"),
    "list_posts": ("GET", "/api/v1/workspaces/{workspace_id}/posts"),
    "get_post": ("GET", "/api/v1/workspaces/{workspace_id}/posts/{post_id}"),
    "create_post": ("POST", "/api/v1/workspaces/{workspace_id}/posts"),
    "update_post": ("PUT", "/api/v1/workspaces/{workspace_id}/posts/{post_id}"),
    "delete_post": ("DELETE", "/api/v1/workspaces/{workspace_id}/posts/{post_id}"),
    "list_labels": ("GET", "/api/v1/workspaces/{workspace_id}/labels"),
    "create_label": ("POST", "/api/v1/workspaces/{workspace_id}/labels"),
    "update_label": ("PUT", "/api/v1/workspaces/{workspace_id}/labels/{label_id}"),
    "delete_label": ("DELETE", "/api/v1/workspaces/{workspace_id}/labels/{label_id}"),
    "list_campaigns": ("GET", "/api/v1/workspaces/{workspace_id}/campaigns"),
    "create_campaign": ("POST", "/api/v1/workspaces/{workspace_id}/campaigns"),
    "update_campaign": ("PUT", "/api/v1/workspaces/{workspace_id}/campaigns/{campaign_id}"),
    "delete_campaign": ("DELETE", "/api/v1/workspaces/{workspace_id}/campaigns/{campaign_id}"),
    "list_content_categories": ("GET", "/api/v1/workspaces/{workspace_id}/content-categories"),
    "get_content_category": ("GET", "/api/v1/workspaces/{workspace_id}/content-categories/{category_id}"),
    "create_content_category": ("POST", "/api/v1/workspaces/{workspace_id}/content-categories"),
    "update_content_category": ("PUT", "/api/v1/workspaces/{workspace_id}/content-categories/{category_id}"),
    "delete_content_category": ("DELETE", "/api/v1/workspaces/{workspace_id}/content-categories/{category_id}"),
    "list_media": ("GET", "/api/v1/workspaces/{workspace_id}/media"),
    "list_team_members": ("GET", "/api/v1/workspaces/{workspace_id}/team-members"),
    "get_limits": ("GET", "/api/v1/workspaces/{workspace_id}/limits"),
}


def _redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    if isinstance(value, dict):
        return {_redact(name, key): _redact(item, key) for name, item in value.items()}
    return value


class ContentStudioNode(WorkflowNode):
    integration_type = "automation-content-studio"
    connection_evidence = ConnectionEvidence(noun="ContentStudio workspaces", operation="list_workspaces", identity_operation="get_me", identity_keys=("full_name", "email", "id"))

    @classmethod
    def get_config_model(cls):
        return ContentStudioFullConfig

    async def execute(self, inputs):
        if not isinstance(self.config, ContentStudioFullConfig) or not self.config.credentials:
            raise ValueError("Attach a Content Studio API key")
        config = self.config.config
        key = self.config.credentials.api_key
        method, template = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        path_fields = re.findall(r"\{(\w+)\}", template)
        path = template.format(**{field: values.pop(field) for field in path_fields})
        kwargs = {}
        if method == "GET":
            # The posts API uses literal bracketed array query names.
            kwargs["params"] = {(name + "[]" if isinstance(value, list) else name): value for name, value in values.items()}
        elif config.operation in {"create_post", "update_post"}:
            content = {"text": values.pop("text")}
            if "media_ids" in values:
                content["media"] = {"media_ids": values.pop("media_ids")}
            scheduling = {"publish_type": values.pop("publish_type")}
            if "scheduled_at" in values:
                scheduling["scheduled_at"] = values.pop("scheduled_at")
            kwargs["json"] = {"content": content, "scheduling": scheduling, **values}
        elif values:
            kwargs["json"] = values
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"X-API-Key": key, "Accept": "application/json"}, **kwargs)
        except httpx.HTTPError:
            message = "ContentStudio request could not be completed"
            if method != "GET":
                message += "; write outcome is unknown, inspect ContentStudio before retrying"
            raise ValueError(message) from None
        if len(response.content) > 10_000_000:
            raise ValueError("ContentStudio response exceeds the size limit")
        if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise ValueError("Expected a JSON response from ContentStudio")
        try:
            body = response.json()
        except ValueError:
            raise ValueError("ContentStudio returned invalid JSON") from None
        if not isinstance(body, dict):
            raise ValueError("ContentStudio returned an invalid response envelope")
        if not 200 <= response.status_code < 300 or body.get("status") is False or body.get("errors") or body.get("error"):
            return _redact({"status": "error", "http_status": response.status_code,
                "error": body.get("message") or body.get("error") or "ContentStudio rejected the request",
                **{name: body[name] for name in ("errors", "error_code", "retry_after") if name in body}}, key)
        if body.get("status") is not True:
            raise ValueError("ContentStudio did not confirm the operation")
        if method != "DELETE" and not isinstance(body.get("data"), list if config.operation.startswith("list_") else dict):
            raise ValueError("ContentStudio response data has an unexpected shape")
        # Preserve warnings, pagination and 207 per-account outcomes verbatim.
        return _redact({**body, "status": "success", "operation": config.operation,
            "http_status": response.status_code}, key)
