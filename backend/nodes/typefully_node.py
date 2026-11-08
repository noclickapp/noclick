"""Manage Typefully social sets, drafts, media, tags, and posting queues.

Each operation makes one request to the published v2 API. Draft scheduling and
publish state are returned verbatim so callers can follow asynchronous publishing.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Union
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.typefully_operations import (
    DraftCreateRequest, DraftUpdateRequest, MediaUploadRequest, MediaUpdateRequest,
    QueueScheduleUpdateRequest, TagCreateRequest,
)
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.typefully.com"


class TypefullyAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Typefully API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://typefully.com/?settings=api",
            "x-credential-instructions": "In Typefully, open Settings, then API, and generate an API key. Paste the key here. It inherits your access to social sets and publishing permissions.",
        })
    credential_type: Literal["typefully_api_key"] = Field("typefully_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() for c in value):
            raise ValueError("Paste the API key without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    limit: int = Field(10, ge=1, le=50)
    offset: int = Field(0, ge=0, description="Number of items to skip. Use the response's next_offset for the next page.")


class _SocialSet(_Input):
    social_set_id: int = Field(..., description="Social set ID from List social sets.")


class _Draft(_SocialSet):
    draft_id: int = Field(..., description="Draft ID from List drafts or Create draft.")


class GetCurrentUser(_Input):
    operation: Literal["get_current_user"] = "get_current_user"


class ListSocialSets(_Page):
    operation: Literal["list_social_sets"] = "list_social_sets"


class GetSocialSet(_SocialSet):
    operation: Literal["get_social_set"] = "get_social_set"


class ListDrafts(_SocialSet, _Page):
    operation: Literal["list_drafts"] = "list_drafts"
    status: Literal["draft", "published", "scheduled", "planned", "error", "publishing"] | None = None
    tag: list[str] | None = Field(None, description="Filter by tag slugs. Each slug is sent as a repeated tag parameter.")
    order_by: Literal["created_at", "-created_at", "updated_at", "-updated_at", "scheduled_date", "-scheduled_date", "published_at", "-published_at"] = "-updated_at"


class CreateDraft(_SocialSet, DraftCreateRequest):
    operation: Literal["create_draft"] = "create_draft"


class GetDraft(_Draft):
    operation: Literal["get_draft"] = "get_draft"
    exclude_comment_markers: StrictBool = Field(False, description="Use false when editing the returned text to preserve comment anchors.")


class UpdateDraft(_Draft, DraftUpdateRequest):
    operation: Literal["update_draft"] = "update_draft"
    exclude_comment_markers: StrictBool = False


class DeleteDraft(_Draft):
    operation: Literal["delete_draft"] = "delete_draft"


class CreateMediaUpload(_SocialSet, MediaUploadRequest):
    operation: Literal["create_media_upload"] = Field("create_media_upload", description="Reserve a media ID and presigned upload URL. PUT file bytes to that URL separately within one hour, then poll Get media status.")


class _Media(_SocialSet):
    media_id: UUID


class GetMediaStatus(_Media):
    operation: Literal["get_media_status"] = "get_media_status"


class UpdateMedia(_Media, MediaUpdateRequest):
    operation: Literal["update_media"] = "update_media"


class ListTags(_SocialSet, _Page):
    operation: Literal["list_tags"] = "list_tags"


class CreateTag(_SocialSet, TagCreateRequest):
    operation: Literal["create_tag"] = "create_tag"


class GetQueueSchedule(_SocialSet):
    operation: Literal["get_queue_schedule"] = "get_queue_schedule"


class ReplaceQueueSchedule(_SocialSet, QueueScheduleUpdateRequest):
    operation: Literal["replace_queue_schedule"] = Field("replace_queue_schedule", description="Replace all posting rules in the social set's local timezone. An empty rules list clears the schedule.")


class GetQueue(_SocialSet):
    operation: Literal["get_queue"] = "get_queue"
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def ordered_dates(self):
        if self.end_date < self.start_date:
            raise ValueError("End date must be on or after start date")
        return self


class ResolveLinkedInOrganization(_SocialSet):
    operation: Literal["resolve_linkedin_organization"] = "resolve_linkedin_organization"
    organization_url: str = Field(..., description="Public LinkedIn company or school URL, e.g. https://www.linkedin.com/company/typefullycom")


TypefullyConfig = Annotated[Union[
    GetCurrentUser, ListSocialSets, GetSocialSet, ListDrafts, CreateDraft, GetDraft,
    UpdateDraft, DeleteDraft, CreateMediaUpload, GetMediaStatus, UpdateMedia,
    ListTags, CreateTag, GetQueueSchedule, ReplaceQueueSchedule, GetQueue,
    ResolveLinkedInOrganization,
], Field(discriminator="operation")]


class TypefullyFullConfig(NodeConfig[TypefullyConfig, TypefullyAPIKeyCredential]):
    pass


# One operation corresponds to one published METHOD /path, including the
# significant trailing slash on the social-set detail route.
ROUTES = {
    "get_current_user": ("GET", "/v2/me", (), None),
    "list_social_sets": ("GET", "/v2/social-sets", ("limit", "offset"), None),
    "get_social_set": ("GET", "/v2/social-sets/{social_set_id}/", (), None),
    "list_drafts": ("GET", "/v2/social-sets/{social_set_id}/drafts", ("limit", "offset", "status", "tag", "order_by"), None),
    "create_draft": ("POST", "/v2/social-sets/{social_set_id}/drafts", (), DraftCreateRequest),
    "get_draft": ("GET", "/v2/social-sets/{social_set_id}/drafts/{draft_id}", ("exclude_comment_markers",), None),
    "update_draft": ("PATCH", "/v2/social-sets/{social_set_id}/drafts/{draft_id}", ("exclude_comment_markers",), DraftUpdateRequest),
    "delete_draft": ("DELETE", "/v2/social-sets/{social_set_id}/drafts/{draft_id}", (), None),
    "create_media_upload": ("POST", "/v2/social-sets/{social_set_id}/media/upload", (), MediaUploadRequest),
    "get_media_status": ("GET", "/v2/social-sets/{social_set_id}/media/{media_id}", (), None),
    "update_media": ("PATCH", "/v2/social-sets/{social_set_id}/media/{media_id}", (), MediaUpdateRequest),
    "list_tags": ("GET", "/v2/social-sets/{social_set_id}/tags", ("limit", "offset"), None),
    "create_tag": ("POST", "/v2/social-sets/{social_set_id}/tags", (), TagCreateRequest),
    "get_queue_schedule": ("GET", "/v2/social-sets/{social_set_id}/queue/schedule", (), None),
    "replace_queue_schedule": ("PUT", "/v2/social-sets/{social_set_id}/queue/schedule", (), QueueScheduleUpdateRequest),
    "get_queue": ("GET", "/v2/social-sets/{social_set_id}/queue", ("start_date", "end_date"), None),
    "resolve_linkedin_organization": ("GET", "/v2/social-sets/{social_set_id}/linkedin/organizations/resolve", ("organization_url",), None),
}


class TypefullyNode(WorkflowNode):
    integration_type = "automation-typefully"
    connection_evidence = ConnectionEvidence(noun="Typefully account", identity_operation="get_current_user")

    @classmethod
    def get_config_model(cls):
        return TypefullyFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Typefully API key")
        op = self.config.config
        method, template, query_fields, payload_model = ROUTES[op.operation]
        values = op.model_dump(mode="json")
        path = template.format(**values)
        params = {k: values[k] for k in query_fields if values[k] is not None}
        params = {k: (str(v).lower() if isinstance(v, bool) else v) for k, v in params.items()}
        body = None
        if payload_model:
            supplied = op.model_dump(mode="json", exclude_unset=True)
            body = {k: v for k, v in supplied.items() if k in payload_model.model_fields}
        key = self.config.credentials.api_key
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path, params=params,
                    headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
                    **({"json": body} if body is not None else {}))
        except httpx.RequestError:
            raise ValueError("Typefully request could not be completed; inspect the draft before retrying a write") from None
        if not 200 <= response.status_code < 300:
            message = ""
            try:
                error = response.json()
                if isinstance(error, dict):
                    detail = error.get("error", error)
                    if isinstance(detail, dict):
                        message = str(detail.get("message", ""))
            except ValueError:
                pass
            message = message.replace(key, "[redacted]")[:1000]
            raise ValueError(f"Typefully HTTP {response.status_code}" + (": " + message if message else ""))
        if response.status_code == 204:
            return {"status": "success", "http_status": 204, "deleted": True, "draft_id": op.draft_id}
        try:
            data = response.json()
        except ValueError:
            raise ValueError("Typefully returned an invalid JSON response") from None
        if not isinstance(data, dict):
            raise ValueError("Typefully returned an unexpected response shape")
        if "error" in data or "errors" in data:
            raise ValueError("Typefully returned an error response")
        result = {"status": "success", "http_status": response.status_code, "data": data}
        if "results" in data:
            if not isinstance(data["results"], list):
                raise ValueError("Typefully returned an invalid results page")
            # Preserve provider pagination, without following returned URLs.
            limit, offset, count = (data.get(k) for k in ("limit", "offset", "count"))
            if not all(type(v) is int for v in (limit, offset, count)) or limit < 1 or offset < 0 or count < 0:
                raise ValueError("Typefully returned invalid pagination")
            result["next_offset"] = offset + limit if offset + limit < count else None
        return result
