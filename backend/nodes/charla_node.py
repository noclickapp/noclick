"""Charla Public API v1: property contacts, conversations and knowledge base.

Contract: https://app.charla.com/swagger/v1/swagger.json
Each operation performs one request; pagination cursors are returned unchanged.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.charla.com/v1"


class CharlaAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Charla API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.charla.com/swagger/index.html",
            "x-credential-instructions": "In Charla, open your property settings and copy the API key from the Integration tab. Paste the key here. Each property has its own key; NoClick sends it in the X-Api-Key header.",
        })
    credential_type: Literal["charla_api_key"] = Field("charla_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the Charla API key")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CharlaCheckConnectionConfig(_Input):
    """Read the first page of this property's contacts to verify the key."""
    operation: Literal["check_connection"] = "check_connection"


class CharlaListContactsConfig(_Input):
    """Read one page of contacts, newest modifications first (25 per page)."""
    operation: Literal["list_contacts"] = "list_contacts"
    cursor: int | None = Field(None, ge=0, le=9223372036854775807,
        description="Integer next_cursor from the previous contacts page. Omit for the first page.")


class CharlaGetContactConfig(_Input):
    """Read a contact by its UUID."""
    operation: Literal["get_contact"] = "get_contact"
    id: UUID = Field(..., title="Contact ID")


class CharlaCustomAttribute(_Input):
    name: str | None = None
    value: str | None = None
    external_id: str | None = None


class CharlaSaveContactConfig(_Input):
    """Save or update a contact. Omitted fields are not sent."""
    operation: Literal["save_contact"] = "save_contact"
    id: UUID | None = Field(None, title="Contact ID", description="Existing contact UUID when updating.")
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    country_code: str | None = Field(None, description="Country code in ISO 3166-1.")
    location: str | None = None
    ip: str | None = None
    platform: str | None = None
    browser_language: str | None = None
    tags: str | None = Field(None, description="Comma-separated tags already added to your organization.")
    custom_attributes: list[CharlaCustomAttribute] | None = None


class CharlaListConversationsConfig(_Input):
    """Read conversations grouped per visitor, newest message first (25 per page)."""
    operation: Literal["list_conversations"] = "list_conversations"
    cursor: int | None = Field(None, ge=0, le=9223372036854775807,
        description="Integer next_cursor from the previous conversations page.")


class CharlaGetArticleConfig(_Input):
    """Read a knowledge base article."""
    operation: Literal["get_article"] = "get_article"
    id: int = Field(..., title="Article ID", ge=1, le=2147483647)


class CharlaListArticlesConfig(_Input):
    """Read one page of articles, newest creation first (25 per page)."""
    operation: Literal["list_articles"] = "list_articles"
    cursor: str | None = Field(None, description="Opaque next_cursor returned by the previous articles page.")


class CharlaArticleCategory(_Input):
    id: int = Field(..., ge=1, le=2147483647, description="Existing category ID from List Categories.")


class CharlaSaveArticleConfig(_Input):
    """Save or update an article; chatbot training follows your Charla AI settings."""
    operation: Literal["save_article"] = "save_article"
    id: int = Field(0, ge=0, le=2147483647, description="0 creates an article; use an existing ID to update.")
    title: str = Field(..., min_length=1)
    slug: str | None = None
    description: str | None = None
    article: str = Field(..., description="Article HTML content.", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "html"})
    categories: list[CharlaArticleCategory] = Field(..., min_length=1)
    status: Literal["Draft", "Published"] = "Draft"
    visibility: Literal["Private", "Public"] = "Private"


class CharlaDeleteArticleConfig(_Input):
    """Permanently delete a knowledge base article by ID."""
    operation: Literal["delete_article"] = "delete_article"
    id: int = Field(..., title="Article ID", ge=1, le=2147483647)


class CharlaListCategoriesConfig(_Input):
    """Read all knowledge base categories for this property."""
    operation: Literal["list_categories"] = "list_categories"


CharlaConfig = Annotated[Union[
    CharlaCheckConnectionConfig, CharlaListContactsConfig, CharlaGetContactConfig,
    CharlaSaveContactConfig, CharlaListConversationsConfig, CharlaGetArticleConfig,
    CharlaListArticlesConfig, CharlaSaveArticleConfig, CharlaDeleteArticleConfig,
    CharlaListCategoriesConfig,
], Field(discriminator="operation")]


class CharlaFullConfig(NodeConfig[CharlaConfig, CharlaAPIKeyCredential]):
    pass


class CharlaNode(WorkflowNode):
    integration_type = "automation-charla"
    connection_evidence = ConnectionEvidence(noun="Charla contacts", operation="list_contacts")

    @classmethod
    def get_config_model(cls):
        return CharlaFullConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Charla API key")
        operation = config.operation
        routes = {
            "check_connection": ("GET", "/contacts"),
            "list_contacts": ("GET", "/contacts"),
            "get_contact": ("GET", "/contacts/{id}"),
            "save_contact": ("POST", "/contacts"),
            "list_conversations": ("GET", "/conversations"),
            "get_article": ("GET", "/kb/articles/{id}"),
            "list_articles": ("GET", "/kb/articles"),
            "save_article": ("POST", "/kb/articles"),
            "delete_article": ("DELETE", "/kb/article/{id}"),
            "list_categories": ("GET", "/kb/categories"),
        }
        method, path = routes[operation]
        if "{id}" in path:
            path = path.format(id=config.id)
        params = {}
        if getattr(config, "cursor", None) is not None:
            params["cursor"] = config.cursor
        kwargs = {"params": params}
        if method == "POST":
            kwargs["json"] = config.model_dump(mode="json", exclude={"operation"}, exclude_none=True)
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"X-Api-Key": credential.api_key, "Accept": "application/json"}, **kwargs)
        if response.status_code != 200:
            # Keep provider rejection text for connection evidence; never expose a key.
            detail = response.text[:2000].replace(credential.api_key, "[redacted]")
            raise ValueError(f"Charla HTTP {response.status_code}: {detail}")
        if operation == "delete_article":
            return {"status": "success", "deleted": True, "id": config.id}
        body = response.json()
        if operation in {"list_contacts", "list_conversations", "list_articles", "check_connection"}:
            if not isinstance(body, dict) or not isinstance(body.get("data"), (list, type(None))) or not isinstance(body.get("paging"), dict):
                raise ValueError("Unexpected Charla page response")
            return {"status": "success", "data": body.get("data") or [], "paging": body["paging"]}
        if operation == "list_categories":
            if not isinstance(body, list):
                raise ValueError("Unexpected Charla categories response")
        elif not isinstance(body, dict) or any(k in body for k in ("error", "errors")):
            raise ValueError("Unexpected Charla resource response")
        return {"status": "success", "data": body}
