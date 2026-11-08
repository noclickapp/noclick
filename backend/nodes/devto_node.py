"""DEV Community API v1: one published Forem operation per action.

Contract: https://developers.forem.com/redocusaurus/plugin-redoc-1.yaml (1.0.0).
Personal API keys are sent only to dev.to. Pages are explicit; writes never retry.
"""
from __future__ import annotations

import json
import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://dev.to"


class DevtoAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Devto API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://dev.to/settings/extensions",
            "x-credential-instructions": "In DEV Settings → Extensions, create a DEV API Key and paste the key alone. NoClick sends it only to dev.to and reads your profile to check the connection. The key can read and publish articles with your account's permissions.",
        })
    credential_type: Literal["devto_api_key"] = Field("devto_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def clean_key(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste your DEV API key")
        value = clean_secret(value, field_name="API key", key=True)
        if any(c.isspace() for c in value) or ":" in value:
            raise ValueError("Paste the API key alone, without a header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


ResourceID = Annotated[int, Field(gt=0, le=2147483647)]
Segment = Annotated[str, Field(min_length=1, max_length=300, pattern=r"^[A-Za-z0-9_-]+$")]
Text = Annotated[str, Field(min_length=1, max_length=100000)]


class _Page(_Input):
    page: int = Field(1, ge=1, description="Page number. Each run returns one page; increase page to continue.")
    per_page: int = Field(30, ge=1, le=1000, description="Maximum items on this page. An empty page ends pagination.")


class DevtoGetMeConfig(_Input):
    """Get me in DEV Community."""
    operation: Literal["get_me"] = Field("get_me", json_schema_extra={"ui:hidden": True})


class DevtoListArticlesConfig(_Page):
    """List articles in DEV Community."""
    operation: Literal["list_articles"] = Field("list_articles", json_schema_extra={"ui:hidden": True})
    tag: str | None = None
    tags: str | None = Field(None, description="Comma-separated tags, matching any.")
    tags_exclude: str | None = None
    username: str | None = None
    state: Literal["fresh", "rising", "all"] | None = None
    top: int | None = Field(None, ge=1)
    collection_id: ResourceID | None = None


class DevtoListLatestArticlesConfig(_Page):
    """List latest articles in DEV Community."""
    operation: Literal["list_latest_articles"] = Field("list_latest_articles", json_schema_extra={"ui:hidden": True})


class DevtoGetArticleConfig(_Input):
    """Get article in DEV Community."""
    operation: Literal["get_article"] = Field("get_article", json_schema_extra={"ui:hidden": True})
    article_id: ResourceID


class DevtoGetArticleByPathConfig(_Input):
    """Get article by path in DEV Community."""
    operation: Literal["get_article_by_path"] = Field("get_article_by_path", json_schema_extra={"ui:hidden": True})
    username: Segment
    slug: Segment


class DevtoListMyArticlesConfig(_Page):
    """List my articles in DEV Community."""
    operation: Literal["list_my_articles"] = Field("list_my_articles", json_schema_extra={"ui:hidden": True})


class DevtoListMyPublishedArticlesConfig(_Page):
    """List my published articles in DEV Community."""
    operation: Literal["list_my_published_articles"] = Field("list_my_published_articles", json_schema_extra={"ui:hidden": True})


class DevtoListMyUnpublishedArticlesConfig(_Page):
    """List my unpublished articles in DEV Community."""
    operation: Literal["list_my_unpublished_articles"] = Field("list_my_unpublished_articles", json_schema_extra={"ui:hidden": True})


class DevtoListAllMyArticlesConfig(_Page):
    """List all my articles in DEV Community."""
    operation: Literal["list_all_my_articles"] = Field("list_all_my_articles", json_schema_extra={"ui:hidden": True})


class DevtoCreateArticleConfig(_Input):
    """Create article in DEV Community."""
    operation: Literal["create_article"] = Field("create_article", json_schema_extra={"ui:hidden": True})
    title: Text
    body_markdown: Text = Field(..., json_schema_extra={"ui:widget": "textarea"})
    published: bool = Field(False, description="Set true to publish immediately; false creates a draft.")
    series: str | None = None
    main_image: str | None = None
    canonical_url: str | None = None
    description: str | None = None
    tags: str | None = Field(None, description="Comma-separated tags, as required by Forem API v1.")
    organization_id: ResourceID | None = None


class DevtoUpdateArticleConfig(_Input):
    """Update article in DEV Community."""
    operation: Literal["update_article"] = Field("update_article", json_schema_extra={"ui:hidden": True})
    article_id: ResourceID
    title: Text | None = None
    body_markdown: Text | None = Field(None, json_schema_extra={"ui:widget": "textarea"})
    published: bool | None = Field(None, description="True publishes; false saves as a draft. Omit to preserve.")
    series: str | None = None
    main_image: str | None = None
    canonical_url: str | None = None
    description: str | None = None
    tags: str | None = Field(None, description="Comma-separated tags.")
    organization_id: ResourceID | None = None

    @model_validator(mode="after")
    def changed(self):
        if not any(getattr(self, k) is not None for k in type(self).model_fields if k not in {"operation", "article_id"}):
            raise ValueError("Provide at least one article field to update")
        return self


class DevtoListCommentsConfig(_Page):
    """List comments in DEV Community."""
    operation: Literal["list_comments"] = Field("list_comments", json_schema_extra={"ui:hidden": True})
    a_id: str | None = Field(None, description="Article ID to fetch comments for.")
    p_id: str | None = Field(None, description="Podcast episode ID to fetch comments for.")


class DevtoGetCommentConfig(_Input):
    """Get comment in DEV Community."""
    operation: Literal["get_comment"] = Field("get_comment", json_schema_extra={"ui:hidden": True})
    comment_id: Segment = Field(..., description="Alphanumeric comment id_code, not its numeric database ID.")


class DevtoListTagsConfig(_Page):
    """List tags in DEV Community."""
    operation: Literal["list_tags"] = Field("list_tags", json_schema_extra={"ui:hidden": True})
    per_page: int = Field(10, ge=1, le=1000)


class DevtoListFollowedTagsConfig(_Input):
    """List followed tags in DEV Community."""
    operation: Literal["list_followed_tags"] = Field("list_followed_tags", json_schema_extra={"ui:hidden": True})


class DevtoListFollowersConfig(_Page):
    """List followers in DEV Community."""
    operation: Literal["list_followers"] = Field("list_followers", json_schema_extra={"ui:hidden": True})
    sort: Literal["created_at", "-created_at"] | None = None


class DevtoGetReadingListConfig(_Page):
    """Get reading list in DEV Community."""
    operation: Literal["get_reading_list"] = Field("get_reading_list", json_schema_extra={"ui:hidden": True})


class DevtoGetOrganizationConfig(_Input):
    """Get organization by its numeric ID in DEV Community."""
    operation: Literal["get_organization"] = Field("get_organization", json_schema_extra={"ui:hidden": True})
    organization_id: ResourceID


class DevtoListOrganizationArticlesConfig(_Page):
    """List organization articles in DEV Community."""
    operation: Literal["list_organization_articles"] = Field("list_organization_articles", json_schema_extra={"ui:hidden": True})
    organization_id_or_username: Segment


class DevtoGetUserConfig(_Input):
    """Get user in DEV Community."""
    operation: Literal["get_user"] = Field("get_user", json_schema_extra={"ui:hidden": True})
    user_id: Segment = Field(..., description="Numeric user ID or username, as documented by Forem API v1.")


DevtoOperation = Annotated[Union[
    DevtoGetMeConfig,
    DevtoListArticlesConfig,
    DevtoListLatestArticlesConfig,
    DevtoGetArticleConfig,
    DevtoGetArticleByPathConfig,
    DevtoListMyArticlesConfig,
    DevtoListMyPublishedArticlesConfig,
    DevtoListMyUnpublishedArticlesConfig,
    DevtoListAllMyArticlesConfig,
    DevtoCreateArticleConfig,
    DevtoUpdateArticleConfig,
    DevtoListCommentsConfig,
    DevtoGetCommentConfig,
    DevtoListTagsConfig,
    DevtoListFollowedTagsConfig,
    DevtoListFollowersConfig,
    DevtoGetReadingListConfig,
    DevtoGetOrganizationConfig,
    DevtoListOrganizationArticlesConfig,
    DevtoGetUserConfig,
], Field(discriminator="operation")]


class DevtoConfig(NodeConfig[DevtoOperation, DevtoAPIKeyCredential]):
    pass


ROUTES = {'get_me': ('GET', '/api/users/me', []),
 'list_articles': ('GET',
                   '/api/articles',
                   ['page',
                    'per_page',
                    'tag',
                    'tags',
                    'tags_exclude',
                    'username',
                    'state',
                    'top',
                    'collection_id']),
 'list_latest_articles': ('GET', '/api/articles/latest', ['page', 'per_page']),
 'get_article': ('GET', '/api/articles/{article_id}', []),
 'get_article_by_path': ('GET', '/api/articles/{username}/{slug}', []),
 'list_my_articles': ('GET', '/api/articles/me', ['page', 'per_page']),
 'list_my_published_articles': ('GET', '/api/articles/me/published', ['page', 'per_page']),
 'list_my_unpublished_articles': ('GET', '/api/articles/me/unpublished', ['page', 'per_page']),
 'list_all_my_articles': ('GET', '/api/articles/me/all', ['page', 'per_page']),
 'create_article': ('POST', '/api/articles', []),
 'update_article': ('PUT', '/api/articles/{article_id}', []),
 'list_comments': ('GET', '/api/comments', ['page', 'per_page', 'a_id', 'p_id']),
 'get_comment': ('GET', '/api/comments/{comment_id}', []),
 'list_tags': ('GET', '/api/tags', ['page', 'per_page']),
 'list_followed_tags': ('GET', '/api/follows/tags', []),
 'list_followers': ('GET', '/api/followers/users', ['page', 'per_page', 'sort']),
 'get_reading_list': ('GET', '/api/readinglist', ['page', 'per_page']),
 'get_organization': ('GET', '/api/organizations/{organization_id}', []),
 'list_organization_articles': ('GET',
                                '/api/organizations/{organization_id_or_username}/articles',
                                ['page', 'per_page']),
 'get_user': ('GET', '/api/users/{user_id}', [])}


class _ProviderError(ValueError):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value


class DevtoNode(WorkflowNode):
    integration_type = "automation-devto"
    connection_evidence = ConnectionEvidence(noun="DEV articles", operation="list_all_my_articles",
        label_keys=("title", "id"), identity_operation="get_me", identity_keys=("name", "username", "id"))

    @classmethod
    def get_config_model(cls):
        return DevtoConfig

    @classmethod
    async def _request(cls, credential, operation):
        method, route, query_fields = ROUTES[operation.operation]
        values = operation.model_dump(exclude_none=True, exclude={"operation"})
        path_fields = re.findall(r"{(\w+)}", route)
        path = route.format(**{key: quote(str(values.pop(key)), safe="") for key in path_fields})
        params = {key: values.pop(key) for key in query_fields if key in values}
        body = {"article": values} if method in {"POST", "PUT"} else None
        headers = {"api-key": credential.api_key, "Accept": "application/vnd.forem.api-v1+json",
                   "User-Agent": "NoClick (https://noclick.com)"}
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE + path, headers=headers, params=params, json=body)
        except httpx.RequestError:
            raise ValueError("DEV request did not complete; inspect your articles before retrying a write") from None
        if len(response.content) > 5000000:
            raise ValueError("DEV response exceeded the supported size")
        if not 200 <= response.status_code < 300:
            detail = response.text[:2000]
            raise _ProviderError(response.status_code, _redact(f"DEV HTTP {response.status_code}: {detail}", credential.api_key))
        # Article writes and comment detail have no response content schema in
        # the published contract. An empty acknowledgement remains a success.
        if not response.content:
            if method == "GET" and operation.operation != "get_comment":
                raise ValueError("DEV returned an empty response")
            return None, response.status_code
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("DEV did not return JSON; inspect your articles before retrying a write") from None
        if isinstance(payload, dict) and ("error" in payload or "errors" in payload):
            raise _ProviderError(response.status_code, _redact(json.dumps(payload)[:2000], credential.api_key))
        collection = operation.operation.startswith("list_") or operation.operation == "get_reading_list"
        if not isinstance(payload, list if collection else dict):
            raise ValueError("DEV returned an unexpected response shape")
        return _redact(payload, credential.api_key), response.status_code

    @classmethod
    async def validate_credential_access(cls, credential_data):
        credential = DevtoAPIKeyCredential.model_validate(credential_data)
        try:
            payload, _ = await cls._request(credential, DevtoGetMeConfig())
            name = payload.get("name") or payload.get("username")
            if not name or not payload.get("id"):
                raise ValueError("DEV account identity is unavailable")
        except _ProviderError as exc:
            return {"valid": False if exc.status in {401, 403} else None, "message": str(exc)}
        except (ValueError, httpx.HTTPError):
            return {"valid": None, "message": "DEV account access could not be verified"}
        return {"valid": True, "identity_verified": True, "message": "Connected to " + str(name)}

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect your DEV API key")
        payload, status = await self._request(self.config.credentials, self.config.config)
        output = {"status": "success", "operation": self.config.config.operation, "data": payload, "http_status": status}
        if isinstance(payload, list):
            output["page"] = getattr(self.config.config, "page", None)
            output["per_page"] = getattr(self.config.config, "per_page", None)
        await self.emit(output)
        return output
