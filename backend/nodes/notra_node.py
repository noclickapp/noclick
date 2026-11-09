"""Notra v1 content automation with a pasted account or organization API key.

Each operation maps to one published endpoint. Pagination and async job state
are returned unchanged; mutations are never retried automatically.
Contract: https://api.usenotra.com/openapi.json (1.0.0).
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.usenotra.com"


def resource_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value):
        raise ValueError("Use a single Notra resource ID or workspace slug")
    return value


ResourceID = Annotated[str, BeforeValidator(resource_id)]


class NotraAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Notra API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.usenotra.com/docs/api/authentication",
            "x-credential-instructions": "Paste your Notra account or organization API key. Account keys can select a workspace with its ID or slug; this is required when you belong to multiple workspaces. Organization keys can select only their own workspace. NoClick sends the key only to api.usenotra.com. Grant access to the operations you use; connecting reads your authenticated workspace context.",
        })
    credential_type: Literal["notra_api_key"] = Field("notra_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=8192, repr=False, title="API Key", json_schema_extra={"ui:widget": "password"})
    organization_id: ResourceID | None = Field(None, title="Workspace ID or slug", description="Required for account keys belonging to multiple workspaces. Sent as X-Notra-Organization-Id.")

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or re.search(r"[\s\x00-\x1f\x7f]", value):
            raise ValueError("Paste only the API key, without the Bearer prefix")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Empty(Input):
    pass


class PostID(Input):
    post_id: ResourceID


class BrandID(Input):
    brand_identity_id: ResourceID


class SiteID(Input):
    site_id: ResourceID


class ListPosts(Input):
    limit: int = Field(10, ge=1, le=100)
    page: int = Field(1, ge=1)
    sort: Literal["asc", "desc"] = "desc"
    status: str | None = Field(None, description="Comma-separated draft,published. Provider defaults to published posts only.")
    contentType: str | None = Field(None, description="Comma-separated content types.")
    brandIdentityId: str | None = Field(None, description="Comma-separated brand identity IDs.")


class CreatePost(Input):
    title: str = Field(..., min_length=1, max_length=120)
    contentType: Literal["blog_post", "changelog", "linkedin_post", "twitter_post"]
    slug: str | None = Field(None, min_length=1, max_length=160)
    markdown: str | None = Field(None, max_length=100000)
    status: Literal["draft", "published"] = "draft"

    @model_validator(mode="after")
    def slug_kind(self):
        if self.slug is not None and self.contentType not in {"blog_post", "changelog"}:
            raise ValueError("Slugs are accepted only for blog posts and changelogs")
        return self


class UpdatePost(PostID):
    title: str | None = Field(None, min_length=1, max_length=120)
    slug: str | None = Field(None, min_length=1, max_length=160, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    markdown: str | None = Field(None, min_length=1, max_length=100000)
    status: Literal["draft", "published"] | None = None

    @model_validator(mode="after")
    def changes(self):
        if all(getattr(self, k) is None for k in ("title", "slug", "markdown", "status")):
            raise ValueError("Supply at least one post change")
        return self


class GeneratePost(Input):
    contentType: Literal["changelog", "blog_post", "linkedin_post", "twitter_post", "image"]
    lookbackWindow: Literal["current_day", "yesterday", "last_7_days", "last_14_days", "last_30_days"] = "last_7_days"
    brandIdentityId: str | None = Field(None, min_length=1)
    brief: str | None = Field(None, min_length=1, max_length=4000, description="Topic and angle; facts come from connected sources. Omitted source selectors use all connected GitHub integrations.")
    timezone: str | None = Field(None, min_length=1, max_length=100)


class GenerationID(Input):
    job_id: ResourceID


class SchedulePost(PostID):
    scheduledAt: str = Field(..., description="ISO 8601 timestamp with timezone, at most a year ahead. Up to five minutes in the past publishes immediately.")
    timeZone: str = Field("UTC", max_length=100, description="IANA timezone for display and emails. Publishes in Notra; external destinations are not selected by this operation.")

    @field_validator("scheduledAt")
    @classmethod
    def timestamp(cls, value):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None: raise ValueError()
        except ValueError:
            raise ValueError("Use an ISO 8601 timestamp including timezone") from None
        return value

    @field_validator("timeZone")
    @classmethod
    def zone(cls, value):
        try: ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError): raise ValueError("Use an IANA timezone") from None
        return value


class UpdateBrand(BrandID):
    name: str | None = Field(None, min_length=1, max_length=120)
    toneProfile: Literal["Conversational", "Professional", "Casual", "Formal"] | None = None
    customTone: str | None = Field(None, max_length=1000)
    customInstructions: str | None = Field(None, max_length=4000)
    isDefault: Literal[True] | None = Field(None, description="Only true is accepted to select the organization's default brand.")

    @model_validator(mode="after")
    def changes(self):
        if all(getattr(self, k) is None for k in ("name", "toneProfile", "customTone", "customInstructions", "isDefault")):
            raise ValueError("Supply at least one brand identity change")
        return self


class PublishPost(SiteID):
    postId: ResourceID = Field(..., description="Blog post or changelog. Opens or updates a repository pull request; the site goes live after merge.")


class NotraListWorkspacesConfig(Empty):
    operation: Literal["list_workspaces"] = Field("list_workspaces", json_schema_extra={"ui:hidden": True})


class NotraListPostsConfig(ListPosts):
    operation: Literal["list_posts"] = Field("list_posts", json_schema_extra={"ui:hidden": True})


class NotraGetPostConfig(PostID):
    operation: Literal["get_post"] = Field("get_post", json_schema_extra={"ui:hidden": True})


class NotraCreatePostConfig(CreatePost):
    operation: Literal["create_post"] = Field("create_post", json_schema_extra={"ui:hidden": True})


class NotraUpdatePostConfig(UpdatePost):
    operation: Literal["update_post"] = Field("update_post", json_schema_extra={"ui:hidden": True})


class NotraDeletePostConfig(PostID):
    operation: Literal["delete_post"] = Field("delete_post", json_schema_extra={"ui:hidden": True})


class NotraListPostAuthorsConfig(Empty):
    operation: Literal["list_post_authors"] = Field("list_post_authors", json_schema_extra={"ui:hidden": True})


class NotraGeneratePostConfig(GeneratePost):
    operation: Literal["generate_post"] = Field("generate_post", json_schema_extra={"ui:hidden": True})


class NotraGetPostGenerationConfig(GenerationID):
    operation: Literal["get_post_generation"] = Field("get_post_generation", json_schema_extra={"ui:hidden": True})


class NotraGetPostScheduleConfig(PostID):
    operation: Literal["get_post_schedule"] = Field("get_post_schedule", json_schema_extra={"ui:hidden": True})


class NotraSchedulePostConfig(SchedulePost):
    operation: Literal["schedule_post"] = Field("schedule_post", json_schema_extra={"ui:hidden": True})


class NotraCancelPostScheduleConfig(PostID):
    operation: Literal["cancel_post_schedule"] = Field("cancel_post_schedule", json_schema_extra={"ui:hidden": True})


class NotraListBrandIdentitiesConfig(Empty):
    operation: Literal["list_brand_identities"] = Field("list_brand_identities", json_schema_extra={"ui:hidden": True})


class NotraGetBrandIdentityConfig(BrandID):
    operation: Literal["get_brand_identity"] = Field("get_brand_identity", json_schema_extra={"ui:hidden": True})


class NotraUpdateBrandIdentityConfig(UpdateBrand):
    operation: Literal["update_brand_identity"] = Field("update_brand_identity", json_schema_extra={"ui:hidden": True})


class NotraDeleteBrandIdentityConfig(BrandID):
    operation: Literal["delete_brand_identity"] = Field("delete_brand_identity", json_schema_extra={"ui:hidden": True})


class NotraListIntegrationsConfig(Empty):
    operation: Literal["list_integrations"] = Field("list_integrations", json_schema_extra={"ui:hidden": True})


class NotraListSitesConfig(Empty):
    operation: Literal["list_sites"] = Field("list_sites", json_schema_extra={"ui:hidden": True})


class NotraGetSiteConfig(SiteID):
    operation: Literal["get_site"] = Field("get_site", json_schema_extra={"ui:hidden": True})


class NotraPublishPostToSiteConfig(PublishPost):
    operation: Literal["publish_post_to_site"] = Field("publish_post_to_site", json_schema_extra={"ui:hidden": True})


NotraConfig = Annotated[Union[
    NotraListWorkspacesConfig,
    NotraListPostsConfig,
    NotraGetPostConfig,
    NotraCreatePostConfig,
    NotraUpdatePostConfig,
    NotraDeletePostConfig,
    NotraListPostAuthorsConfig,
    NotraGeneratePostConfig,
    NotraGetPostGenerationConfig,
    NotraGetPostScheduleConfig,
    NotraSchedulePostConfig,
    NotraCancelPostScheduleConfig,
    NotraListBrandIdentitiesConfig,
    NotraGetBrandIdentityConfig,
    NotraUpdateBrandIdentityConfig,
    NotraDeleteBrandIdentityConfig,
    NotraListIntegrationsConfig,
    NotraListSitesConfig,
    NotraGetSiteConfig,
    NotraPublishPostToSiteConfig
], Field(discriminator="operation")]


class NotraFullConfig(NodeConfig[NotraConfig, NotraAPIKeyCredential]):
    pass


ROUTES = {'list_workspaces': ('GET', '/v1/me/workspaces'), 'list_posts': ('GET', '/v1/posts'), 'get_post': ('GET', '/v1/posts/{post_id}'), 'create_post': ('POST', '/v1/posts'), 'update_post': ('PATCH', '/v1/posts/{post_id}'), 'delete_post': ('DELETE', '/v1/posts/{post_id}'), 'list_post_authors': ('GET', '/v1/posts/authors'), 'generate_post': ('POST', '/v1/posts/generate'), 'get_post_generation': ('GET', '/v1/posts/generate/{job_id}'), 'get_post_schedule': ('GET', '/v1/posts/{post_id}/schedule'), 'schedule_post': ('POST', '/v1/posts/{post_id}/schedule'), 'cancel_post_schedule': ('DELETE', '/v1/posts/{post_id}/schedule'), 'list_brand_identities': ('GET', '/v1/brand-identities'), 'get_brand_identity': ('GET', '/v1/brand-identities/{brand_identity_id}'), 'update_brand_identity': ('PATCH', '/v1/brand-identities/{brand_identity_id}'), 'delete_brand_identity': ('DELETE', '/v1/brand-identities/{brand_identity_id}'), 'list_integrations': ('GET', '/v1/integrations'), 'list_sites': ('GET', '/v1/sites'), 'get_site': ('GET', '/v1/sites/{site_id}'), 'publish_post_to_site': ('POST', '/v1/sites/{site_id}/publications')}


class NotraNode(WorkflowNode):
    integration_type = "automation-notra"
    connection_evidence = ConnectionEvidence(operation="list_workspaces", noun="workspaces", label_keys=("name", "slug", "id"))

    @classmethod
    def get_config_model(cls):
        return NotraFullConfig

    @staticmethod
    def _check_family(data):
        raw = data.get("credentials")
        if isinstance(raw, dict) and raw.get("credential_type", "notra_api_key") != "notra_api_key":
            raise ValueError("Attach a Notra API key credential")

    @classmethod
    def parse_config(cls, config_data):
        cls._check_family(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            cls._check_family(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(config_data)

    async def execute(self, inputs):
        config, credential = self.config.config, self.config.credentials
        if credential is None:
            raise ValueError("Connect a Notra API key")
        operation = config.operation
        method, path = ROUTES[operation]
        values = config.model_dump(exclude={"operation"}, exclude_none=True)
        for key in list(values):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(resource_id(values.pop(key)), safe=""))
        headers = {"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"}
        if credential.organization_id:
            headers["X-Notra-Organization-Id"] = credential.organization_id
        kwargs = {"params": values} if method == "GET" else {"json": values} if method in {"POST", "PATCH"} else {}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, headers=headers, **kwargs)
        except httpx.RequestError:
            raise ValueError("Notra could not be reached; request outcome is unknown. Check before retrying writes.") from None
        if not 200 <= response.status_code < 300:
            message = "Notra request failed"
            try:
                body = response.json()
                detail = body.get("error") or body.get("message")
                if isinstance(detail, str): message = detail.replace(credential.api_key, "[redacted]")[:1000]
            except (ValueError, AttributeError):
                pass
            raise ValueError(f"Notra HTTP {response.status_code}: {message}")
        if len(response.content) > 10_000_000:
            raise ValueError("Notra response exceeds the supported size")
        if "json" not in response.headers.get("content-type", "").lower():
            raise ValueError("Notra returned an unexpected content type")
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Notra returned invalid JSON") from None
        if not isinstance(payload, dict) or "error" in payload or "errors" in payload:
            raise ValueError("Notra returned an invalid response or error envelope")
        expected = {
            "list_workspaces": "workspaces", "list_posts": "posts", "get_post": "post",
            "create_post": "post", "update_post": "post", "delete_post": "id",
            "list_post_authors": "authors", "generate_post": "job", "get_post_generation": "job",
            "get_post_schedule": "schedule", "schedule_post": "schedule", "cancel_post_schedule": "canceled",
            "list_brand_identities": "brandIdentities", "get_brand_identity": "brandIdentity",
            "update_brand_identity": "brandIdentity", "delete_brand_identity": "id",
            "list_integrations": "github", "list_sites": "sites", "get_site": "site",
            "publish_post_to_site": "pullRequestUrl",
        }[operation]
        if expected not in payload:
            raise ValueError("Notra response is missing its documented envelope")
        if operation.startswith("list_") and not isinstance(payload[expected], list):
            raise ValueError("Notra returned an invalid list envelope")
        # Provider fields (including pagination, job state and publication operation)
        # remain under data so none can override execution metadata.
        return {"status": "success", "operation": operation, "http_status": response.status_code, "data": payload}
