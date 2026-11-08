"""Inblog API v1: blog content and lead-capture automation.

Contract: https://inblog.ai/openapi.json (1.0.0). Each operation makes one
request; lists return one explicit page and preserve JSON:API metadata.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode, runtime_config_view
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://inblog.ai/api/v1"


class InblogAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Inblog API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://inblog.ai/dashboard",
            "x-credential-instructions": "In Inblog, open Settings → API Keys and create a key for your blog. Select the scopes needed by your operations: posts:read/write/delete, tags:read/write/delete, authors:read, blogs:read, redirects:read/write, forms:read and form_responses:read. Paste the key only. NoClick checks the connected blog with GET /me; that check does not prove every operation's permissions.",
        })
    credential_type: Literal["inblog_api_key"] = Field("inblog_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    page: int = Field(1, ge=1, description="Page number; fetch subsequent pages explicitly.")
    limit: int = Field(10, ge=1, le=100, description="Maximum items per page.")


class _PostFields(_Input):
    title: str | None = Field(None, min_length=1, max_length=200)
    slug: str | None = Field(None, min_length=1, pattern=r"^[a-z0-9-]+$")
    description: str | None = Field(None, max_length=160)
    content_html: str | None = Field(None, description="Inblog TipTap HTML. Send the full content when updating.")
    published: bool | None = Field(None, description="Publish immediately when true; unpublish when false.")
    meta_title: str | None = Field(None, max_length=60)
    meta_description: str | None = Field(None, max_length=160)


class GetMe(_Input):
    """Read the API key’s connected blog and granted scopes."""
    operation: Literal["get_me"] = Field("get_me", json_schema_extra={"ui:hidden": True})


class ListPosts(_Page):
    """List posts."""
    operation: Literal["list_posts"] = Field("list_posts", json_schema_extra={"ui:hidden": True})
    slug: str | None = None
    published: bool | None = None
    sort: Literal["published_at", "created_at", "updated_at", "title"] = "created_at"
    order: Literal["asc", "desc"] = "desc"


class GetPost(_Input):
    """Get post."""
    operation: Literal["get_post"] = Field("get_post", json_schema_extra={"ui:hidden": True})
    post_id: int = Field(..., ge=1)


class CreatePost(_PostFields):
    """Create post."""
    operation: Literal["create_post"] = Field("create_post", json_schema_extra={"ui:hidden": True})
    title: str = Field(..., min_length=1, max_length=200)
    slug: str = Field(..., min_length=1, pattern=r"^[a-z0-9-]+$")
    published: bool = Field(False, description="Create a draft by default; true publishes immediately.")


class UpdatePost(_PostFields):
    """Update post."""
    operation: Literal["update_post"] = Field("update_post", json_schema_extra={"ui:hidden": True})
    post_id: int = Field(..., ge=1)

    @model_validator(mode="after")
    def changed(self):
        if not self.model_fields_set.intersection(_PostFields.model_fields):
            raise ValueError("Provide at least one post field to update")
        return self


class DeletePost(_Input):
    """Permanently delete a post."""
    operation: Literal["delete_post"] = Field("delete_post", json_schema_extra={"ui:hidden": True})
    post_id: int = Field(..., ge=1)


class PublishPost(_Input):
    """Publish post."""
    operation: Literal["publish_post"] = Field("publish_post", json_schema_extra={"ui:hidden": True})
    post_id: int = Field(..., ge=1)
    action: Literal["publish", "unpublish", "schedule"] = "publish"
    scheduled_at: str | None = Field(None, description="ISO 8601 timestamp with timezone; required for schedule.", json_schema_extra={"format": "date-time"})

    @model_validator(mode="after")
    def schedule(self):
        from datetime import datetime
        if self.action == "schedule" and self.scheduled_at is None:
            raise ValueError("A scheduled publication requires scheduled_at")
        if self.scheduled_at is not None:
            try:
                value = datetime.fromisoformat(self.scheduled_at.replace("Z", "+00:00"))
            except ValueError:
                raise ValueError("Use an ISO 8601 timestamp") from None
            if value.tzinfo is None:
                raise ValueError("Include a timezone in scheduled_at")
        return self


class ListTags(_Input):
    """List tags."""
    operation: Literal["list_tags"] = Field("list_tags", json_schema_extra={"ui:hidden": True})


class GetTag(_Input):
    """Get tag."""
    operation: Literal["get_tag"] = Field("get_tag", json_schema_extra={"ui:hidden": True})
    tag_id: int = Field(..., ge=1)


class CreateTag(_Input):
    """Create tag."""
    operation: Literal["create_tag"] = Field("create_tag", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=50)
    slug: str = Field(..., min_length=1, pattern=r"^[a-z0-9-]+$")


class UpdateTag(_Input):
    """Update tag."""
    operation: Literal["update_tag"] = Field("update_tag", json_schema_extra={"ui:hidden": True})
    tag_id: int = Field(..., ge=1)
    name: str | None = Field(None, min_length=1, max_length=50)
    slug: str | None = Field(None, min_length=1, pattern=r"^[a-z0-9-]+$")

    @model_validator(mode="after")
    def changed(self):
        if self.name is None and self.slug is None:
            raise ValueError("Provide a tag name or slug to update")
        return self


class DeleteTag(_Input):
    """Permanently delete a tag."""
    operation: Literal["delete_tag"] = Field("delete_tag", json_schema_extra={"ui:hidden": True})
    tag_id: int = Field(..., ge=1)


class ListAuthors(_Page):
    """List authors."""
    operation: Literal["list_authors"] = Field("list_authors", json_schema_extra={"ui:hidden": True})
    assignable: bool | None = Field(None, description="Include verified members who can be assigned as authors.")


class GetAuthor(_Input):
    """Get author."""
    operation: Literal["get_author"] = Field("get_author", json_schema_extra={"ui:hidden": True})
    author_id: str = Field(..., description="Author UUID from List Authors.", json_schema_extra={"format": "uuid"})

    @field_validator("author_id")
    @classmethod
    def author(cls, value):
        return str(UUID(value))


class GetBlog(_Input):
    """Read the blog connected to the API key."""
    operation: Literal["get_blog"] = Field("get_blog", json_schema_extra={"ui:hidden": True})


class ListRedirects(_Page):
    """List redirects."""
    operation: Literal["list_redirects"] = Field("list_redirects", json_schema_extra={"ui:hidden": True})


class GetRedirect(_Input):
    """Get redirect."""
    operation: Literal["get_redirect"] = Field("get_redirect", json_schema_extra={"ui:hidden": True})
    redirect_id: str = Field(..., min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_-][A-Za-z0-9_.-]*$")


class CreateRedirect(_Input):
    """Create redirect."""
    operation: Literal["create_redirect"] = Field("create_redirect", json_schema_extra={"ui:hidden": True})
    from_path: str = Field(..., min_length=1, description="Source path to redirect from.")
    to_path: str = Field(..., min_length=1, description="Target path to redirect to.")
    redirect_type: Literal[307, 308] = 307


class UpdateRedirect(_Input):
    """Update redirect."""
    operation: Literal["update_redirect"] = Field("update_redirect", json_schema_extra={"ui:hidden": True})
    redirect_id: str = Field(..., min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_-][A-Za-z0-9_.-]*$")
    from_path: str | None = Field(None, min_length=1)
    to_path: str | None = Field(None, min_length=1)
    redirect_type: Literal[307, 308] | None = None

    @model_validator(mode="after")
    def changed(self):
        if self.from_path is None and self.to_path is None and self.redirect_type is None:
            raise ValueError("Provide at least one redirect field to update")
        return self


class DeleteRedirect(_Input):
    """Permanently delete a redirect rule."""
    operation: Literal["delete_redirect"] = Field("delete_redirect", json_schema_extra={"ui:hidden": True})
    redirect_id: str = Field(..., min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_-][A-Za-z0-9_.-]*$")


class ListForms(_Page):
    """List forms."""
    operation: Literal["list_forms"] = Field("list_forms", json_schema_extra={"ui:hidden": True})


class GetForm(_Input):
    """Get form."""
    operation: Literal["get_form"] = Field("get_form", json_schema_extra={"ui:hidden": True})
    form_id: int = Field(..., ge=1)


class ListFormResponses(_Page):
    """List form responses."""
    operation: Literal["list_form_responses"] = Field("list_form_responses", json_schema_extra={"ui:hidden": True})
    form_id: int | None = Field(None, ge=1)


class GetFormResponse(_Input):
    """Get form response."""
    operation: Literal["get_form_response"] = Field("get_form_response", json_schema_extra={"ui:hidden": True})
    response_id: int = Field(..., ge=1)


InblogOperation = Annotated[Union[
    GetMe,
    ListPosts,
    GetPost,
    CreatePost,
    UpdatePost,
    DeletePost,
    PublishPost,
    ListTags,
    GetTag,
    CreateTag,
    UpdateTag,
    DeleteTag,
    ListAuthors,
    GetAuthor,
    GetBlog,
    ListRedirects,
    GetRedirect,
    CreateRedirect,
    UpdateRedirect,
    DeleteRedirect,
    ListForms,
    GetForm,
    ListFormResponses,
    GetFormResponse
], Field(discriminator="operation")]


class InblogConfig(NodeConfig[InblogOperation, InblogAPIKeyCredential]):
    pass


ROUTES = {'get_me': ('GET', '/me'),
 'list_posts': ('GET', '/posts'),
 'get_post': ('GET', '/posts/{post_id}'),
 'create_post': ('POST', '/posts'),
 'update_post': ('PATCH', '/posts/{post_id}'),
 'delete_post': ('DELETE', '/posts/{post_id}'),
 'publish_post': ('PATCH', '/posts/{post_id}/publish'),
 'list_tags': ('GET', '/tags'),
 'get_tag': ('GET', '/tags/{tag_id}'),
 'create_tag': ('POST', '/tags'),
 'update_tag': ('PATCH', '/tags/{tag_id}'),
 'delete_tag': ('DELETE', '/tags/{tag_id}'),
 'list_authors': ('GET', '/authors'),
 'get_author': ('GET', '/authors/{author_id}'),
 'get_blog': ('GET', '/blogs/me'),
 'list_redirects': ('GET', '/redirects'),
 'get_redirect': ('GET', '/redirects/{redirect_id}'),
 'create_redirect': ('POST', '/redirects'),
 'update_redirect': ('PATCH', '/redirects/{redirect_id}'),
 'delete_redirect': ('DELETE', '/redirects/{redirect_id}'),
 'list_forms': ('GET', '/forms'),
 'get_form': ('GET', '/forms/{form_id}'),
 'list_form_responses': ('GET', '/form-responses'),
 'get_form_response': ('GET', '/form-responses/{response_id}')}


class InblogNode(WorkflowNode):
    integration_type = "automation-inblog"
    connection_evidence = ConnectionEvidence(noun="connected blog", identity_operation="get_me",
        identity_keys=("subdomain", "blog_id"))
    edit_examples = ["Create a draft blog post", "Publish this post", "List form responses", "Create a URL redirect"]

    @classmethod
    def get_config_model(cls):
        return InblogConfig

    @classmethod
    def parse_config(cls, config_data):
        # The typed-in credential model and the runtime configuration share the
        # platform's canonical view (including unset/default handling).
        return TypeAdapter(InblogConfig).validate_python(runtime_config_view(config_data, InblogConfig))

    @staticmethod
    def _request_parts(op):
        method, template = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        path = template
        for key in list(values):
            if "{" + key + "}" in template:
                path = path.replace("{" + key + "}", quote(str(values.pop(key)), safe=""))
        params, body = {}, None
        if method == "GET":
            aliases = {"slug": "filter[slug]", "published": "filter[published]", "assignable": "filter[assignable]"}
            params = {aliases.get(k, k): str(v).lower() if isinstance(v, bool) else v for k, v in values.items()}
        elif method != "DELETE":
            kind = "publish_action" if isinstance(op, PublishPost) else "posts" if isinstance(op, _PostFields) else "tags" if isinstance(op, (CreateTag, UpdateTag)) else "redirects"
            body = {"jsonapi": {"version": "1.0"}, "data": {"type": kind, "attributes": values}}
            if isinstance(op, UpdateRedirect):
                body["data"]["id"] = op.redirect_id
        return method, path, params, body

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an Inblog API key")
        op = self.config.config
        token = self.config.credentials.api_key
        method, path, params, body = self._request_parts(op)
        headers = {"Authorization": "Bearer " + token, "Accept": "application/vnd.api+json"}
        if body is not None:
            headers["Content-Type"] = "application/vnd.api+json"
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path, headers=headers, params=params, json=body)
        except httpx.RequestError:
            raise ValueError("Inblog request could not be completed; inspect write results before retrying") from None
        if not 200 <= response.status_code < 300:
            # Keep provider rejection details for the manual-connect seam while
            # removing the supplied secret if a server reflects it.
            message = response.text.replace(token, "[redacted]")[:2000]
            raise ValueError(f"Inblog HTTP {response.status_code}: {message}")
        if response.status_code == 204:
            result = {"status": "success", "http_status": 204, "deleted": True}
        else:
            try:
                payload = response.json()
            except ValueError:
                raise ValueError("Inblog returned a non-JSON response") from None
            if not isinstance(payload, dict) or "errors" in payload or "data" not in payload:
                raise ValueError("Inblog returned an invalid JSON:API response")
            result = {"status": "success", "http_status": response.status_code, **payload}
            if isinstance(op, GetMe) and isinstance(payload["data"], dict):
                # Surface the account-specific evidence beside the untouched
                # resource envelope for the shared connection renderer.
                attrs = payload["data"].get("attributes", {})
                if isinstance(attrs, dict):
                    result.update({k: attrs[k] for k in ("subdomain", "blog_id") if k in attrs})
        await self.emit(result)
        return result
