"""Planable Public API v1: one documented request per operation.

Contract: https://api.planable.io/api/v1/openapi.json (1.0.0).
Lists return one page, preserving provider pagination. Uploads are asynchronous;
no operation retries a write or polls for publication or processing completion.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import AnyHttpUrl, AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.planable.io/api/v1"


class PlanableTokenCredential(BaseModel):
    model_config = ConfigDict(title="Planable API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://api.planable.io/api/v1/openapi.json",
            "x-credential-instructions": "Paste a Planable API token without the Bearer prefix. New tokens require a Pro or Enterprise company; existing tokens continue to work regardless of plan. Use a token with write permission for create, update, approval and delete operations. Connection verification lists the workspaces this token can access.",
        })
    credential_type: Literal["planable_api_token"] = Field("planable_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=4096, title="API Token", repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API Token")
        if not value.isascii() or any(ord(ch) < 33 or ord(ch) == 127 for ch in value):
            raise ValueError("Paste the API token without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def resource_ids(cls, value, info):
        if info.field_name in {"id", "workspaceId", "pageId", "campaignId", "replyToCommentId", "levelId"} and value is not None:
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", value):
                raise ValueError("Use a single Planable resource ID")
        return value

    @model_validator(mode="after")
    def update_fields(self):
        if getattr(self, "operation", "").startswith("update_"):
            supplied = self.model_dump(exclude_unset=True)
            supplied = {key: value for key, value in supplied.items() if value is not None or (self.operation == "update_post" and key in {"scheduledAt", "firstComment", "campaignId"})}
            if not set(supplied) - {"operation", "id", "notify"}:
                raise ValueError("Provide at least one field to update")
        return self


class ListWorkspaces(_Input):
    """List workspaces."""
    operation: Literal["list_workspaces"] = Field("list_workspaces", title='List Workspaces', json_schema_extra={"ui:hidden": True})


class ListPages(_Input):
    """List pages."""
    operation: Literal["list_pages"] = Field("list_pages", title='List Pages', json_schema_extra={"ui:hidden": True})
    workspaceId: str | None = Field(None, title='Workspace ID', min_length=1)
    offset: int = Field(0, title='Offset', ge=0)
    limit: int = Field(20, title='Limit', ge=1, le=100)


class ListMembers(_Input):
    """List workspace members."""
    operation: Literal["list_members"] = Field("list_members", title='List Members', json_schema_extra={"ui:hidden": True})
    workspaceId: str = Field(..., title='Workspace ID', min_length=1)


class ListPosts(_Input):
    """List posts."""
    operation: Literal["list_posts"] = Field("list_posts", title='List Posts', json_schema_extra={"ui:hidden": True})
    workspaceId: str = Field(..., title='Workspace ID', min_length=1)
    pageId: str | None = Field(None, title='Page ID', min_length=1)
    campaignId: str | None = Field(None, title='Campaign ID')
    scheduledAfter: AwareDatetime | None = Field(None, title='Scheduled After')
    scheduledBefore: AwareDatetime | None = Field(None, title='Scheduled Before')
    createdAfter: AwareDatetime | None = Field(None, title='Created After')
    createdBefore: AwareDatetime | None = Field(None, title='Created Before')
    offset: int = Field(0, title='Offset', ge=0)
    limit: int = Field(20, title='Limit', ge=1, le=100)


class CreatePost(_Input):
    """Create a new post."""
    operation: Literal["create_post"] = Field("create_post", title='Create Post', json_schema_extra={"ui:hidden": True})
    workspaceId: str = Field(..., title='Workspace ID', min_length=1)
    pageId: str = Field(..., title='Page ID', min_length=1)
    text: str = Field('', title='Text', max_length=25000, description='Post text. When this contains a URL and media is omitted, Facebook, LinkedIn, and X posts get a link preview card. A failed preview fetch still creates the post without a card.')
    scheduledAt: AwareDatetime | None = Field(None, title='Scheduled At')
    labels: list[str] = Field([], title='Labels', description='Label ids, as returned by `GET /labels`.')
    media: list[AnyHttpUrl] = Field([], title='Media', max_length=20, description='Up to 20 public image or video URLs, each max 100MB. Files are downloaded server-side from the provided URLs.')
    teamOnly: bool | None = Field(None, title='Team Only')
    approved: bool | None = Field(None, title='Approved')
    publishAtScheduledDate: bool = Field(False, title='Publish At Scheduled Date')
    firstComment: str | None = Field(None, title='First Comment', max_length=8000, description='Comment published under the post right after it goes live. Only Facebook, Instagram and LinkedIn posts and reels support it, and the page must allow Planable to publish comments. A post whose page cannot take it is created without it, and its response has no firstComment. Grouped requests are rejected only when none of the target pages can take it.')
    internalNote: str | None = Field(None, title='Internal Note', max_length=8000)
    notify: bool = Field(False, title='Notify', description='Controls whether workspace members receive a post-added notification (email/in-app push). This is not an approval request — use POST /posts/{id}/request-approval to notify approvers.')
    campaignId: str | None = Field(None, title='Campaign ID')
    classification: Literal['post', 'reels'] = Field('post', title='Classification', description='Post format. `post` (default) creates a regular feed post. `reels` creates a Reel/Short/video on facebook, twitter, instagram, linkedin, youtube, tiktok, threads only — not on googleMyBusiness, pinterest, universal. Stories stay on POST /stories. Grouped `pageIds` must all support the classification. Reels accept one video file; extra URLs return 400 before create, non-video media return 400 after the post is created. Feed posts use the composer media max per page type; extra URLs return 400. Publishing still applies platform media rules (Reels usually need a video).')


class GetPost(_Input):
    """Get post detail."""
    operation: Literal["get_post"] = Field("get_post", title='Get Post', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., title='Resource ID', min_length=1)


class UpdatePost(_Input):
    """Update a post."""
    operation: Literal["update_post"] = Field("update_post", title='Update Post', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., title='Resource ID', min_length=1)
    text: str | None = Field(None, title='Text', max_length=25000, description='Replaces the post text. Pending suggestions highlighted in the old text are declined, except those still highlighted in another post of a synced group. See declinedSuggestionsCount in the response. When the new text contains a URL and the post has no media, Facebook, LinkedIn, and X posts get a link preview card. A failed preview fetch leaves the post without a card.')
    scheduledAt: AwareDatetime | None = Field(None, title='Scheduled At')
    labels: list[str] | None = Field(None, title='Labels', description='Label ids, as returned by `GET /labels`.')
    media: list[AnyHttpUrl] | None = Field(None, title='Media', max_length=20, description='Up to 20 public image or video URLs, each max 100MB. Files are downloaded server-side from the provided URLs.')
    teamOnly: bool | None = Field(None, title='Team Only')
    approved: bool | None = Field(None, title='Approved')
    firstComment: str | None = Field(None, title='First Comment', max_length=8000, description='Comment published under the post right after it goes live. Replaces the existing first comment; pass null or an empty string to remove it. Only Facebook, Instagram and LinkedIn posts and reels support it, and the page must allow Planable to publish comments. On synced groups it is also applied to the other unpublished posts in the group that meet both conditions; the rest are left unchanged.')
    publishAtScheduledDate: bool | None = Field(None, title='Publish At Scheduled Date')
    archived: bool | None = Field(None, title='Archived')
    campaignId: str | None = Field(None, title='Campaign ID')
    notify: bool | None = Field(None, title='Notify', description='When false, the edit activities created by this update do not trigger notifications (email/in-app push, Zapier). Modifies nothing by itself, so at least one other field must be provided.')


class DeletePost(_Input):
    """Delete a post."""
    operation: Literal["delete_post"] = Field("delete_post", title='Delete Post', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., title='Resource ID', min_length=1)


class CountPosts(_Input):
    """Get total posts count."""
    operation: Literal["count_posts"] = Field("count_posts", title='Count Posts', json_schema_extra={"ui:hidden": True})


class RequestApproval(_Input):
    """Send a post for approval."""
    operation: Literal["request_approval"] = Field("request_approval", title='Request Approval', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., title='Resource ID', min_length=1)
    approverIds: list[Annotated[str, Field(min_length=1)]] = Field(..., title='Approver IDs', min_length=1, max_length=100)
    levelId: str | None = Field(None, title='Level ID')
    note: str | None = Field(None, title='Note', max_length=2000)


class CreateShareLink(_Input):
    """Create a public share link."""
    operation: Literal["create_share_link"] = Field("create_share_link", title='Create Share Link', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., title='Resource ID', min_length=1)


class RevokeShareLink(_Input):
    """Revoke the public share link."""
    operation: Literal["revoke_share_link"] = Field("revoke_share_link", title='Revoke Share Link', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., title='Resource ID', min_length=1)


class ListComments(_Input):
    """List comments on a post."""
    operation: Literal["list_comments"] = Field("list_comments", title='List Comments', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., title='Resource ID', min_length=1)
    offset: int = Field(0, title='Offset', ge=0)
    limit: int = Field(20, title='Limit', ge=1, le=100)
    teamOnly: Literal['true', 'false'] | None = Field(None, title='Team Only')


class AddComment(_Input):
    """Add a comment to a post."""
    operation: Literal["add_comment"] = Field("add_comment", title='Add Comment', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., title='Resource ID', min_length=1)
    text: str = Field(..., title='Text', min_length=1)
    teamOnly: bool = Field(False, title='Team Only')
    replyToCommentId: str | None = Field(None, title='Reply To Comment ID', min_length=1)


class ListCampaigns(_Input):
    """List campaigns."""
    operation: Literal["list_campaigns"] = Field("list_campaigns", title='List Campaigns', json_schema_extra={"ui:hidden": True})
    workspaceId: str = Field(..., title='Workspace ID', min_length=1)
    status: Literal['active', 'archived', 'paused', 'planned', 'completed'] | None = Field(None, title='Status')
    offset: int = Field(0, title='Offset', ge=0)
    limit: int = Field(10, title='Limit', ge=1, le=100)


class CreateCampaign(_Input):
    """Create a campaign."""
    operation: Literal["create_campaign"] = Field("create_campaign", title='Create Campaign', json_schema_extra={"ui:hidden": True})
    workspaceId: str = Field(..., title='Workspace ID', min_length=1)
    name: str = Field(..., title='Name', min_length=1, max_length=80)
    status: Literal['active', 'archived', 'paused', 'planned', 'completed'] = Field('planned', title='Status')
    color: str | None = Field(None, title='Color')
    startedAt: AwareDatetime | None = Field(None, title='Started At')
    endedAt: AwareDatetime | None = Field(None, title='Ended At')
    description: str | None = Field(None, title='Description')


class GetCampaign(_Input):
    """Get campaign detail."""
    operation: Literal["get_campaign"] = Field("get_campaign", title='Get Campaign', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., title='Resource ID', min_length=1)


class UpdateCampaign(_Input):
    """Update a campaign."""
    operation: Literal["update_campaign"] = Field("update_campaign", title='Update Campaign', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., title='Resource ID', min_length=1)
    name: str | None = Field(None, title='Name', min_length=1, max_length=80)
    status: Literal['active', 'archived', 'paused', 'planned', 'completed'] | None = Field(None, title='Status')
    color: str | None = Field(None, title='Color')
    startedAt: AwareDatetime | None = Field(None, title='Started At')
    endedAt: AwareDatetime | None = Field(None, title='Ended At')
    description: str | None = Field(None, title='Description')


class DeleteCampaign(_Input):
    """Delete a campaign."""
    operation: Literal["delete_campaign"] = Field("delete_campaign", title='Delete Campaign', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., title='Resource ID', min_length=1)


class ListLabels(_Input):
    """List labels."""
    operation: Literal["list_labels"] = Field("list_labels", title='List Labels', json_schema_extra={"ui:hidden": True})
    workspaceId: str = Field(..., title='Workspace ID', min_length=1)


class CreateLabel(_Input):
    """Create a label."""
    operation: Literal["create_label"] = Field("create_label", title='Create Label', json_schema_extra={"ui:hidden": True})
    workspaceId: str = Field(..., title='Workspace ID', min_length=1)
    name: str = Field(..., title='Name', min_length=1, description='Label name. Required unless the deprecated `text` is sent.')
    color: Literal['pattens-blue', 'feta', 'pink-lace', 'pippin', 'peach-cream', 'fog', 'half-and-half', 'lime-flurish', 'snowy-mint', 'blue-chalk', 'mabel', 'silver-sand'] = Field(..., title='Color')


class ListMedia(_Input):
    """List media uploads."""
    operation: Literal["list_media"] = Field("list_media", title='List Media', json_schema_extra={"ui:hidden": True})
    workspaceId: str = Field(..., title='Workspace ID', min_length=1)
    deletable: Literal['true', 'false'] | None = Field(None, title='Deletable')
    offset: int = Field(0, title='Offset', ge=0)
    limit: int = Field(20, title='Limit', ge=1, le=100)


class UploadMedia(_Input):
    """Upload media from URLs."""
    operation: Literal["upload_media"] = Field("upload_media", title='Upload Media', json_schema_extra={"ui:hidden": True})
    workspaceId: str = Field(..., title='Workspace ID', min_length=1)
    mediaUrls: list[AnyHttpUrl] = Field(..., title='Media URLs', min_length=1, max_length=20, description='Array of 1 to 20 public image/video URLs to upload to the workspace media library. Each file max ~100MB.')


class GetMedia(_Input):
    """Get media upload."""
    operation: Literal["get_media"] = Field("get_media", title='Get Media', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., title='Resource ID', min_length=1)


class GetPostMetrics(_Input):
    """Get post metrics."""
    operation: Literal["get_post_metrics"] = Field("get_post_metrics", title='Get Post Metrics', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., title='Resource ID', min_length=1)


# Planable's own MCP server: agents get its tools through a person's Planable sign-in.
PlanableMcpCredential = mcp_credential("planable", "https://mcp.planable.io/mcp", app="Planable")
PlanableCredential = Union[PlanableTokenCredential, PlanableMcpCredential]


PlanableOperation = Annotated[Union[ListWorkspaces, ListPages, ListMembers, ListPosts, CreatePost, GetPost, UpdatePost, DeletePost, CountPosts, RequestApproval, CreateShareLink, RevokeShareLink, ListComments, AddComment, ListCampaigns, CreateCampaign, GetCampaign, UpdateCampaign, DeleteCampaign, ListLabels, CreateLabel, ListMedia, UploadMedia, GetMedia, GetPostMetrics], Field(discriminator="operation")]


class PlanableFullConfig(NodeConfig[PlanableOperation, PlanableCredential]):
    pass


ROUTES = {'list_workspaces': ('GET', '/workspaces', [], [], [200]),
 'list_pages': ('GET', '/pages', ['workspaceId', 'offset', 'limit'], [], [200]),
 'list_members': ('GET', '/members', ['workspaceId'], [], [200]),
 'list_posts': ('GET',
                '/posts',
                ['workspaceId',
                 'pageId',
                 'campaignId',
                 'scheduledAfter',
                 'scheduledBefore',
                 'createdAfter',
                 'createdBefore',
                 'offset',
                 'limit'],
                [],
                [200]),
 'create_post': ('POST',
                 '/posts',
                 [],
                 ['workspaceId',
                  'pageId',
                  'text',
                  'scheduledAt',
                  'labels',
                  'media',
                  'teamOnly',
                  'approved',
                  'publishAtScheduledDate',
                  'firstComment',
                  'internalNote',
                  'notify',
                  'campaignId',
                  'classification'],
                 [201]),
 'get_post': ('GET', '/posts/{id}', [], [], [200]),
 'update_post': ('PATCH',
                 '/posts/{id}',
                 [],
                 ['text',
                  'scheduledAt',
                  'labels',
                  'media',
                  'teamOnly',
                  'approved',
                  'firstComment',
                  'publishAtScheduledDate',
                  'archived',
                  'campaignId',
                  'notify'],
                 [200]),
 'delete_post': ('DELETE', '/posts/{id}', [], [], [204]),
 'count_posts': ('GET', '/posts/count', [], [], [200]),
 'request_approval': ('POST', '/posts/{id}/request-approval', [], ['approverIds', 'levelId', 'note'], [200]),
 'create_share_link': ('POST', '/posts/{id}/share', [], [], [200]),
 'revoke_share_link': ('DELETE', '/posts/{id}/share', [], [], [204]),
 'list_comments': ('GET', '/posts/{id}/comments', ['offset', 'limit', 'teamOnly'], [], [200]),
 'add_comment': ('POST', '/posts/{id}/comments', [], ['text', 'teamOnly', 'replyToCommentId'], [201]),
 'list_campaigns': ('GET', '/campaigns', ['workspaceId', 'status', 'offset', 'limit'], [], [200]),
 'create_campaign': ('POST',
                     '/campaigns',
                     [],
                     ['workspaceId', 'name', 'status', 'color', 'startedAt', 'endedAt', 'description'],
                     [201]),
 'get_campaign': ('GET', '/campaigns/{id}', [], [], [200]),
 'update_campaign': ('PATCH',
                     '/campaigns/{id}',
                     [],
                     ['name', 'status', 'color', 'startedAt', 'endedAt', 'description'],
                     [200]),
 'delete_campaign': ('DELETE', '/campaigns/{id}', [], [], [204]),
 'list_labels': ('GET', '/labels', ['workspaceId'], [], [200]),
 'create_label': ('POST', '/labels', [], ['workspaceId', 'name', 'color'], [201]),
 'list_media': ('GET', '/media', ['workspaceId', 'deletable', 'offset', 'limit'], [], [200]),
 'upload_media': ('POST', '/media', [], ['workspaceId', 'mediaUrls'], [202]),
 'get_media': ('GET', '/media/{id}', [], [], [200]),
 'get_post_metrics': ('GET', '/posts/{id}/metrics', [], [], [200])}


class PlanableNode(WorkflowNode):
    integration_type = "automation-planable"
    credential_provider_labels = {"planable": "Planable Account"}
    connection_evidence = ConnectionEvidence(noun="workspaces", operation="list_workspaces")

    @classmethod
    def get_config_model(cls):
        return PlanableFullConfig

    async def execute(self, input_data):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Planable API token")
        op = self.config.config
        method, path, query_fields, body_fields, successes = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True)
        if "{id}" in path:
            path = path.replace("{id}", quote(values["id"], safe=""))
        params = {key: values[key] for key in query_fields if key in values}
        supplied = op.model_dump(mode="json", exclude_unset=True)
        body = {key: supplied[key] for key in body_fields if key in supplied and supplied[key] is not None}
        if op.operation == "create_post":
            body.setdefault("notify", op.notify)
            body.setdefault("publishAtScheduledDate", op.publishAtScheduledDate)
        if op.operation == "update_post":
            for key in ("scheduledAt", "firstComment", "campaignId"):
                if key in supplied:
                    body[key] = supplied[key]
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path, params=params,
                    headers={"Authorization": "Bearer " + credential.api_token, "Accept": "application/json"},
                    **({"json": body} if body_fields else {}))
            if response.status_code not in successes:
                message = "Planable request failed"
                try:
                    error = response.json().get("error", {})
                    if isinstance(error, dict) and isinstance(error.get("message"), str):
                        message = error["message"]
                except (ValueError, AttributeError):
                    pass
                return {"status": "error", "http_status": response.status_code,
                    "error": message.replace(credential.api_token, "[redacted]")}
            if response.status_code == 204:
                return {"status": "success", "http_status": 204}
            payload = response.json()
            if not isinstance(payload, dict) or "error" in payload or not ("data" in payload or "posts" in payload):
                raise ValueError("Planable returned an unexpected response")
            # Preserve documented top-level posts/data and all provider metadata,
            # including partial outcomes; 202 is acceptance, not completion.
            result = {**payload, "status": "success", "http_status": response.status_code}
            pagination = payload.get("pagination")
            if isinstance(pagination, dict) and pagination.get("hasMore") is True:
                result["next_offset"] = pagination["offset"] + pagination["limit"]
            return result
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return {"status": "error", "error": "Planable request did not complete; inspect writes before retrying"}
