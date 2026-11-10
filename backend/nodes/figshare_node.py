"""Figshare v2 articles and collections, using a personal token.

Contract: https://docs.figshare.com/swagger.json (version 2.0).
Auth: https://docs.figshare.com/#description_api_auth.
Polls baseline the first run and watch up to the newest 1,000 records per interval.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.figshare.com/v2"


class FigsharePersonalTokenCredential(BaseModel):
    model_config = ConfigDict(title="Figshare Personal Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://figshare.com/account/applications",
            "x-credential-instructions": "Create a personal token in your Figshare account's Applications page and paste it here. It grants access to your account; NoClick verifies it by reading your account information.",
        })
    credential_type: Literal["figshare_personal_token"] = Field("figshare_personal_token", json_schema_extra={"ui:hidden": True})
    personal_token: str = Field(..., title="Personal token", min_length=1, max_length=4096,
        repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("personal_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Personal token")
        if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the personal token without the Authorization header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


class _Page(_Input):
    page: int = Field(1, ge=1, le=5000)
    page_size: int = Field(100, ge=1, le=1000)


class _Article(_Input):
    article_id: int = Field(..., ge=1)


class _Collection(_Input):
    collection_id: int = Field(..., ge=1)


class FigshareAuthor(_Input):
    id: int | None = Field(None, ge=1)
    name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    orcid_id: str | None = None


class _Metadata(_Input):
    title: str | None = Field(None, min_length=3, max_length=1000)
    description: str | None = Field(None, max_length=20000)
    tags: list[str] | None = None
    categories: list[int] | None = None
    authors: list[FigshareAuthor] | None = None
    references: list[str] | None = None


class _ArticleMetadata(_Metadata):
    defined_type: Literal["figure", "online resource", "preprint", "book", "conference contribution", "media", "dataset", "poster", "journal contribution", "presentation", "thesis", "software"] | None = None
    license: int | None = None
    is_metadata_record: bool | None = None
    metadata_reason: str | None = None


class _PublicArticles(_Page):
    order: Literal["published_date", "created_date", "modified_date", "views", "shares", "downloads", "cites"] = "modified_date"
    order_direction: Literal["asc", "desc"] = "desc"
    institution: int | None = None
    group: int | None = None
    modified_since: str | None = Field(None, description="Figshare date filter, for example 2017-05-18.")
    published_since: str | None = None
    doi: str | None = None


class FigshareGetAccountConfig(_Input):
    operation: Literal["get_account"] = Field("get_account", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Account"})


class FigshareListPublicArticlesConfig(_PublicArticles):
    operation: Literal["list_public_articles"] = Field("list_public_articles", json_schema_extra={"ui:hidden": True, "x-display-name": "List Public Articles"})


class FigshareSearchPublicArticlesConfig(_Input):
    operation: Literal["search_public_articles"] = Field("search_public_articles", json_schema_extra={"ui:hidden": True, "x-display-name": "Search Public Articles"})
    search_for: str = Field(..., min_length=1)
    limit: int = Field(100, ge=1, le=1000)
    offset: int = Field(0, ge=0, le=5000)
    order: Literal["published_date", "created_date", "modified_date", "views", "shares", "downloads", "cites"] = "modified_date"
    order_direction: Literal["asc", "desc"] = "desc"


class FigshareGetPublicArticleConfig(_Article):
    operation: Literal["get_public_article"] = Field("get_public_article", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Public Article"})


class FigshareListArticleVersionsConfig(_Article):
    operation: Literal["list_article_versions"] = Field("list_article_versions", json_schema_extra={"ui:hidden": True, "x-display-name": "List Article Versions"})


class FigshareListPublicArticleFilesConfig(_Article):
    operation: Literal["list_public_article_files"] = Field("list_public_article_files", json_schema_extra={"ui:hidden": True, "x-display-name": "List Public Article Files"})


class FigshareListArticlesConfig(_Page):
    operation: Literal["list_articles"] = Field("list_articles", json_schema_extra={"ui:hidden": True, "x-display-name": "List Articles"})


class FigshareGetArticleConfig(_Article):
    operation: Literal["get_article"] = Field("get_article", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Article"})


class FigshareCreateArticleConfig(_ArticleMetadata):
    operation: Literal["create_article"] = Field("create_article", json_schema_extra={"ui:hidden": True, "x-display-name": "Create Article"})
    title: str = Field(..., min_length=3, max_length=1000)


class FigshareUpdateArticleConfig(_Article, _ArticleMetadata):
    operation: Literal["update_article"] = Field("update_article", json_schema_extra={"ui:hidden": True, "x-display-name": "Update Article"})


class FigshareDeleteArticleConfig(_Article):
    operation: Literal["delete_article"] = Field("delete_article", json_schema_extra={"ui:hidden": True, "x-display-name": "Delete Article"})


class FigsharePublishArticleConfig(_Article):
    operation: Literal["publish_article"] = Field("publish_article", json_schema_extra={"ui:hidden": True, "x-display-name": "Publish Article"})


class FigshareReserveArticleDoiConfig(_Article):
    operation: Literal["reserve_article_doi"] = Field("reserve_article_doi", json_schema_extra={"ui:hidden": True, "x-display-name": "Reserve Article Doi"})


class FigshareListArticleFilesConfig(_Article):
    operation: Literal["list_article_files"] = Field("list_article_files", json_schema_extra={"ui:hidden": True, "x-display-name": "List Article Files"})


class FigshareListCollectionsConfig(_Page):
    operation: Literal["list_collections"] = Field("list_collections", json_schema_extra={"ui:hidden": True, "x-display-name": "List Collections"})
    order: Literal["published_date", "modified_date", "views", "shares", "cites"] = "modified_date"
    order_direction: Literal["asc", "desc"] = "desc"


class FigshareGetCollectionConfig(_Collection):
    operation: Literal["get_collection"] = Field("get_collection", json_schema_extra={"ui:hidden": True, "x-display-name": "Get Collection"})


class FigshareCreateCollectionConfig(_Metadata):
    operation: Literal["create_collection"] = Field("create_collection", json_schema_extra={"ui:hidden": True, "x-display-name": "Create Collection"})
    title: str = Field(..., min_length=3, max_length=1000)
    articles: list[int] | None = None
    fields: dict | None = Field(None, description="For institutions with item-type metadata: authoritative metadata keyed by field name, including title.")


class FigshareUpdateCollectionConfig(_Collection, _Metadata):
    operation: Literal["update_collection"] = Field("update_collection", json_schema_extra={"ui:hidden": True, "x-display-name": "Update Collection"})
    articles: list[int] | None = None
    fields: dict | None = Field(None, description="For institutions with item-type metadata, keys to update including title or description.")


class FigshareDeleteCollectionConfig(_Collection):
    operation: Literal["delete_collection"] = Field("delete_collection", json_schema_extra={"ui:hidden": True, "x-display-name": "Delete Collection"})


class FigshareListCollectionArticlesConfig(_Collection, _Page):
    operation: Literal["list_collection_articles"] = Field("list_collection_articles", json_schema_extra={"ui:hidden": True, "x-display-name": "List Collection Articles"})


class FigshareAddCollectionArticlesConfig(_Collection):
    operation: Literal["add_collection_articles"] = Field("add_collection_articles", json_schema_extra={"ui:hidden": True, "x-display-name": "Add Collection Articles"})
    articles: list[int] = Field(..., min_length=1)


class FigshareOnPublicArticleUpdatedConfig(PollTriggerConfigBase):
    operation: Literal["on_public_article_updated"] = Field("on_public_article_updated", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-display-name": "On Public Article Updated"})
    institution: int | None = None
    group: int | None = None
    modified_since: str | None = Field(None, description="Optional Figshare modified_since date filter.")

class FigshareOnNewCollectionConfig(PollTriggerConfigBase):
    operation: Literal["on_new_collection"] = Field("on_new_collection", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-display-name": "On New Collection"})

FigshareConfig = Annotated[Union[FigshareGetAccountConfig, FigshareListPublicArticlesConfig, FigshareSearchPublicArticlesConfig, FigshareGetPublicArticleConfig, FigshareListArticleVersionsConfig, FigshareListPublicArticleFilesConfig, FigshareListArticlesConfig, FigshareGetArticleConfig, FigshareCreateArticleConfig, FigshareUpdateArticleConfig, FigshareDeleteArticleConfig, FigsharePublishArticleConfig, FigshareReserveArticleDoiConfig, FigshareListArticleFilesConfig, FigshareListCollectionsConfig, FigshareGetCollectionConfig, FigshareCreateCollectionConfig, FigshareUpdateCollectionConfig, FigshareDeleteCollectionConfig, FigshareListCollectionArticlesConfig, FigshareAddCollectionArticlesConfig, FigshareOnPublicArticleUpdatedConfig, FigshareOnNewCollectionConfig], Field(discriminator="operation")]

class FigshareNodeConfig(NodeConfig[FigshareConfig, FigsharePersonalTokenCredential]):
    pass

PAGE_QUERY = ('page', 'page_size')
METADATA_FIELDS = ('title', 'description', 'tags', 'categories', 'authors', 'references')
ARTICLE_FIELDS = METADATA_FIELDS + ('defined_type', 'license', 'is_metadata_record', 'metadata_reason')

OPERATIONS = {
    "get_account": ("GET", "/account", (), ()),
    "list_public_articles": ("GET", "/articles", ('page', 'page_size', 'order', 'order_direction', 'institution', 'group', 'modified_since', 'published_since', 'doi'), ()),
    "search_public_articles": ("POST", "/articles/search", (), ('search_for', 'limit', 'offset', 'order', 'order_direction')),
    "get_public_article": ("GET", "/articles/{article_id}", (), ()),
    "list_article_versions": ("GET", "/articles/{article_id}/versions", (), ()),
    "list_public_article_files": ("GET", "/articles/{article_id}/files", (), ()),
    "list_articles": ("GET", "/account/articles", PAGE_QUERY, ()),
    "get_article": ("GET", "/account/articles/{article_id}", (), ()),
    "create_article": ("POST", "/account/articles", (), ARTICLE_FIELDS),
    "update_article": ("PUT", "/account/articles/{article_id}", (), ARTICLE_FIELDS),
    "delete_article": ("DELETE", "/account/articles/{article_id}", (), ()),
    "publish_article": ("POST", "/account/articles/{article_id}/publish", (), ()),
    "reserve_article_doi": ("POST", "/account/articles/{article_id}/reserve_doi", (), ()),
    "list_article_files": ("GET", "/account/articles/{article_id}/files", (), ()),
    "list_collections": ("GET", "/account/collections", ('page', 'page_size', 'order', 'order_direction'), ()),
    "get_collection": ("GET", "/account/collections/{collection_id}", (), ()),
    "create_collection": ("POST", "/account/collections", (), ('title', 'description', 'tags', 'categories', 'authors', 'references', 'articles', 'fields')),
    "update_collection": ("PATCH", "/account/collections/{collection_id}", (), ('title', 'description', 'tags', 'categories', 'authors', 'references', 'articles', 'fields')),
    "delete_collection": ("DELETE", "/account/collections/{collection_id}", (), ()),
    "list_collection_articles": ("GET", "/account/collections/{collection_id}/articles", PAGE_QUERY, ()),
    "add_collection_articles": ("POST", "/account/collections/{collection_id}/articles", (), ('articles',)),
}


class FigshareNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-figshare"
    connection_evidence = ConnectionEvidence(noun="Figshare account", identity_operation="get_account", identity_keys=("email", "first_name", "id"))
    edit_examples = ["Create a Figshare dataset", "Update article metadata", "Add articles to a collection", "Watch for updated research articles"]

    @classmethod
    def get_config_model(cls):
        return FigshareNodeConfig

    async def _request(self, method, path, *, params=None, body=None):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Figshare personal token")
        async with guarded_async_client(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"Authorization": "token " + credential.personal_token, "Accept": "application/json"},
                params=params, json=body)
        if not 200 <= response.status_code < 300:
            # Preserve provider rejection wording for the connection evidence seam.
            detail = response.text.replace(credential.personal_token, "[redacted]")[:1000]
            raise ValueError(f"Figshare API {response.status_code}: {detail}")
        if not response.content:
            return {"ok": True}
        return response.json()

    async def execute(self, inputs):
        config = self.config.config
        name = config.operation
        values = config.model_dump(exclude_none=True, mode="json")
        if name in ("on_public_article_updated", "on_new_collection"):
            path = "/articles" if name == "on_public_article_updated" else "/account/collections"
            params = {"order": "modified_date", "order_direction": "desc", "page_size": 1000, "page": 1}
            if name == "on_public_article_updated":
                params.update({key: values[key] for key in ("institution", "group", "modified_since") if key in values})
            rows = await self._request("GET", path, params=params)
            if not isinstance(rows, list) or any(not isinstance(row, dict) or not row.get("id") for row in rows):
                raise ValueError("Figshare poll must return an array of identified records")
            fresh = await self._filter_unseen(rows,
                lambda row: str(row["id"]) + (":" + str(row.get("modified_date") or row.get("created_date") or "") if name == "on_public_article_updated" else ""))
            return {"items": fresh, "count": len(fresh), "operation": name}
        method, template, query_fields, body_fields = OPERATIONS[name]
        path = template.format(**values)
        params = {key: values[key] for key in query_fields if key in values}
        body = {key: values[key] for key in body_fields if key in values} if body_fields else None
        data = await self._request(method, path, params=params, body=body)
        return {"data": data}

    @classmethod
    def should_propagate_output(cls, output, config):
        if config.get("operation") in ("on_public_article_updated", "on_new_collection"):
            return bool(output.get("count"))
        return True

    @classmethod
    def resolve_agent_event(cls, output):
        items = output.get("items") if isinstance(output, dict) else None
        if not isinstance(items, list):
            return super().resolve_agent_event(output)
        if not items:
            return None
        is_article = output.get("operation") == "on_public_article_updated"
        lines = []
        for row in items[:20]:
            detail = f"; modified {row.get('modified_date') or row.get('created_date') or 'unknown'}; {row.get('url_public_html') or row.get('url') or ''}" if is_article else f"; {row.get('url') or ''}"
            lines.append(f"- {row.get('title') or 'Untitled research record'} (id {row['id']}){detail}")
        kind = "new or updated public articles" if is_article else "new account collections"
        return {"text": f"Figshare: {len(items)} {kind}:\n" + "\n".join(lines), "conversation_key": None}
