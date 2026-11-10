"""DropInBlog v2 raw API. Contract: https://dev.dropinblog.com/reference/api-reference.

Public tokens read a blog; private tokens create/update posts. Each operation
uses exactly one documented endpoint. Polls enumerate all pages before recording
seen IDs, so a partial/failed scan cannot consume an event.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin


class DropInBlogAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Dropinblog API Keys",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.dropinblog.com/me/apikeys",
            "x-credential-instructions": "Copy your blog ID and public API key from DropInBlog. Add a private API key to create or update posts. Reads and connection verification use the public key; the private key is checked when you write a post.",
        },
    )
    credential_type: Literal["dropinblog_api_key"] = Field(
        "dropinblog_api_key", json_schema_extra={"ui:hidden": True}
    )
    blog_id: str = Field(..., min_length=1, max_length=200, title="Blog ID")
    public_api_key: str = Field(
        ...,
        min_length=1,
        title="Public API key",
        json_schema_extra={"ui:widget": "password"},
    )
    private_api_key: str | None = Field(
        None, title="Private API key", json_schema_extra={"ui:widget": "password"}
    )

    @field_validator("public_api_key", "private_api_key", mode="before")
    @classmethod
    def key(cls, value):
        if value is None:
            return None
        value = clean_secret(value, field_name="API key", key=True)
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a Bearer prefix or spaces")
        return value

    @field_validator("blog_id")
    @classmethod
    def blog(cls, value):
        value = value.strip()
        if not value or value in {".", ".."} or any(c in value for c in "/?#\\"):
            raise ValueError("Paste the blog ID, not a URL")
        return value


class _Input(BaseModel):
    pass


class DropInBlogFAQ(BaseModel):
    question: str
    answer: str


class DropInBlogPostsCreateConfig(_Input):
    """Create a post."""

    operation: Literal["create_post"] = Field(
        "create_post",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Create a post",
            "x-category": "Posts",
        },
    )
    title: str = Field(
        ..., title="Title", min_length=1, description="Title for your post."
    )
    content: str = Field(
        ..., title="Content", min_length=1, description="Content for your post in HTML."
    )
    slug: str | None = Field(
        None,
        title="Slug",
        description="URL friendly identifier for the post. If omitted, it automatically defaults to the post’s title.",
    )
    seo_title: str | None = Field(
        None,
        title="Seo title",
        description="SEO title for your post. If not set it will default to the title.",
    )
    seo_description: str | None = Field(
        None, title="Seo description", description="SEO description for your post."
    )
    keyword: str | None = Field(
        None, title="Keyword", description="SEO keyword for your post."
    )
    secondary_keywords: str | None = Field(
        None,
        title="Secondary keywords",
        description="Secondary SEO keyword list. Separate each keyword with a comma.",
    )
    canonical_url: str | None = Field(
        None,
        title="Canonical url",
        description="Canonical URL for your post. Use this when the post is republished content, so search engines credit the original article. Must be a valid URL.",
    )
    noindex: bool | None = Field(
        None,
        title="Noindex",
        description="Set to `true` to ask search engines not to index this post. Adds a noindex robots meta tag to the post page.",
    )
    excerpt: str | None = Field(
        None,
        title="Excerpt",
        description="Custom summary for your post, shown in post lists and RSS. If not set, the summary is generated automatically from the beginning of the content. Returned as `summary` in responses.",
    )
    published_at: datetime | None = Field(
        None,
        title="Published at",
        description="Published date and time for your post. If set the post will be published. If not set the post will be put in draft.",
    )
    visibility: Literal["public", "private"] | None = Field(None, title="Visibility")
    featured_image: str | None = Field(
        None, title="Featured image", description="Featured image URL for your post."
    )
    featured_image_alt: str | None = Field(
        None,
        title="Featured image alt",
        description="Featured image alt text for the featured image.",
    )
    category_ids: list[int] | None = Field(
        None, title="Category ids", description="Category IDs to attach to your post."
    )
    author_id: int | None = Field(
        None,
        title="Author id",
        ge=1,
        le=2147483647,
        description="Author ID to attach to your post.",
    )
    faqs: list[DropInBlogFAQ] | None = Field(
        None, title="Faqs", description="FAQs to attach to your post."
    )
    enable_toc: bool | None = Field(
        None,
        title="Enable toc",
        description="Generates a Table of Contents from H2/H3 headings and prepends it to the content.",
    )


class DropInBlogPostsListConfig(_Input):
    """Lists all posts."""

    operation: Literal["list_posts"] = Field(
        "list_posts",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Lists all posts",
            "x-category": "Posts",
        },
    )
    statuses: str | None = Field(
        None,
        title="Statuses",
        description="Post status filter (draft, published, scheduled) with a comma separated list. Defaults to published.",
    )
    visibilities: str | None = Field(
        None,
        title="Visibilities",
        description="Post status visibility (public, private) with a comma separated list. Defaults to public.",
    )
    page: int | None = Field(
        None,
        title="Page",
        ge=1,
        le=2147483647,
        description="The current page of pagination.",
    )
    limit: int | None = Field(
        None,
        title="Limit",
        ge=1,
        le=2147483647,
        description="The number of posts to returns. Defaults to posts per page in settings.",
    )
    category_ids: str | None = Field(
        None,
        title="Category ids",
        description="Filter by specific category with a comma separated list of category IDs.",
    )
    category_slugs: str | None = Field(
        None,
        title="Category slugs",
        description="Filter by specific category with a comma separated list of category slugs.",
    )
    author_ids: str | None = Field(
        None,
        title="Author ids",
        description="Filter by specific author with a comma separated list of author IDs.",
    )
    author_slugs: str | None = Field(
        None,
        title="Author slugs",
        description="Filter by specific author with a comma separated list of author slugs.",
    )
    post_ids: str | None = Field(
        None,
        title="Post ids",
        description="Filter by specific post with a comma separated list of post IDs.",
    )
    post_slugs: str | None = Field(
        None,
        title="Post slugs",
        description="Filter by specific post with a comma separated list of post slugs.",
    )
    published_at_start: date | None = Field(
        None,
        title="Published at start",
        description="Filter by posts published on or after this date (YYYY-MM-DD).",
    )
    published_at_end: date | None = Field(
        None,
        title="Published at end",
        description="Filter by posts published on or before this date (YYYY-MM-DD).",
    )
    modified_at_start: date | None = Field(
        None,
        title="Modified at start",
        description="Filter by posts modified on or after this date (YYYY-MM-DD).",
    )
    modified_at_end: date | None = Field(
        None,
        title="Modified at end",
        description="Filter by posts modified on or before this date (YYYY-MM-DD).",
    )


class DropInBlogCategoriesListConfig(_Input):
    """List all categories."""

    operation: Literal["list_categories"] = Field(
        "list_categories",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "List all categories",
            "x-category": "Categories",
        },
    )
    exclude_without_published_post: Literal[0, 1] | None = Field(
        None,
        title="Exclude without published post",
        description="Exclude categories that do not have a published post. Set to 1 to exclude.",
    )
    exclude_private: Literal[0, 1] | None = Field(
        None,
        title="Exclude private",
        description="Exclude private categories. Set to 1 to exclude.",
    )


class DropInBlogAuthorsListConfig(_Input):
    """List all authors."""

    operation: Literal["list_authors"] = Field(
        "list_authors",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "List all authors",
            "x-category": "Authors",
        },
    )
    exclude_without_published_post: Literal[0, 1] | None = Field(
        None,
        title="Exclude without published post",
        description="Exclude authors that do not have a published post. Set to 1 to exclude.",
    )


class DropInBlogPostsRetrieveConfig(_Input):
    """Retrieve a post."""

    operation: Literal["get_post"] = Field(
        "get_post",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Retrieve a post",
            "x-category": "Posts",
        },
    )
    id: int = Field(
        ..., title="Id", ge=1, le=2147483647, description="The ID of your post."
    )


class DropInBlogPostsUpdateConfig(_Input):
    """Update a post."""

    operation: Literal["update_post"] = Field(
        "update_post",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Update a post",
            "x-category": "Posts",
        },
    )
    id: int = Field(
        ..., title="Id", ge=1, le=2147483647, description="The ID of your post."
    )
    title: str | None = Field(None, title="Title", description="Title for your post.")
    slug: str | None = Field(
        None,
        title="Slug",
        description="Slug for your post. Warning: Changing the slug will change the URL of this post. Any existing links to the old URL may no longer work.",
    )
    content: str | None = Field(
        None, title="Content", description="Content for your post in HTML."
    )
    seo_title: str | None = Field(
        None,
        title="Seo title",
        description="SEO title for your post. If not set it will default to the title.",
    )
    seo_description: str | None = Field(
        None, title="Seo description", description="SEO description for your post."
    )
    keyword: str | None = Field(
        None, title="Keyword", description="SEO keyword for your post."
    )
    canonical_url: str | None = Field(
        None,
        title="Canonical url",
        description="Canonical URL for your post. Send an empty value to remove a previously set canonical URL.",
    )
    noindex: bool | None = Field(
        None,
        title="Noindex",
        description="Set to `true` to ask search engines not to index this post. Set to `false` to remove the noindex flag.",
    )
    excerpt: str | None = Field(
        None,
        title="Excerpt",
        description="Custom summary for your post, shown in post lists and RSS. Send an empty value to revert to the automatically generated summary. Returned as `summary` in responses.",
    )
    published_at: date | None = Field(
        None,
        title="Published at",
        description="Published date and time for your post. If set the post will be published. If not set the post will be put in draft.",
    )
    featured_image: str | None = Field(
        None, title="Featured image", description="Featured image URL for your post."
    )
    featured_image_alt: str | None = Field(
        None,
        title="Featured image alt",
        description="Featured image alt text for the featured image.",
    )
    category_ids: list[int] | None = Field(
        None, title="Category ids", description="Category IDs to attach to your post."
    )
    author_id: int | None = Field(
        None,
        title="Author id",
        ge=1,
        le=2147483647,
        description="Author ID to attach to your post.",
    )
    clear_excerpt: bool = Field(
        False,
        title="Clear custom excerpt",
        description="Send an empty excerpt to restore the automatic summary.",
    )
    clear_canonical_url: bool = Field(
        False,
        title="Clear canonical URL",
        description="Send an empty canonical URL to remove it.",
    )


class DropInBlogPostsSearchConfig(_Input):
    """Search posts."""

    operation: Literal["search_posts"] = Field(
        "search_posts",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Search posts",
            "x-category": "Posts",
        },
    )
    search: str = Field(
        ..., title="Search", min_length=1, description="The search string."
    )
    statuses: str | None = Field(
        None,
        title="Statuses",
        description="Post status filter (draft, published, scheduled) with a comma separated list. Defaults to published.",
    )
    page: int | None = Field(
        None,
        title="Page",
        ge=1,
        le=2147483647,
        description="The current page of pagination.",
    )
    limit: int | None = Field(
        None,
        title="Limit",
        ge=1,
        le=2147483647,
        description="The number of posts to returns. Defaults to posts per page in settings.",
    )


class DropInBlogPostsRetrieveBySlugConfig(_Input):
    """Retrieve a post by slug."""

    operation: Literal["get_post_by_slug"] = Field(
        "get_post_by_slug",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Retrieve a post by slug",
            "x-category": "Posts",
        },
    )
    slug: str = Field(
        ..., title="Slug", min_length=1, description="The slug of your post."
    )


class DropInBlogPostsUpdateBySlugConfig(_Input):
    """Update a post by slug."""

    operation: Literal["update_post_by_slug"] = Field(
        "update_post_by_slug",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Update a post by slug",
            "x-category": "Posts",
        },
    )
    post_slug: str = Field(
        ..., title="Post slug", min_length=1, description="The slug of your post."
    )
    title: str | None = Field(None, title="Title", description="Title for your post.")
    slug: str | None = Field(
        None,
        title="Slug",
        description="Slug for your post. Warning: Changing the slug will change the URL of this post. Any existing links to the old URL may no longer work.",
    )
    content: str | None = Field(
        None, title="Content", description="Content for your post in HTML."
    )
    seo_title: str | None = Field(
        None,
        title="Seo title",
        description="SEO title for your post. If not set it will default to the title.",
    )
    seo_description: str | None = Field(
        None, title="Seo description", description="SEO description for your post."
    )
    keyword: str | None = Field(
        None, title="Keyword", description="SEO keyword for your post."
    )
    canonical_url: str | None = Field(
        None,
        title="Canonical url",
        description="Canonical URL for your post. Send an empty value to remove a previously set canonical URL.",
    )
    noindex: bool | None = Field(
        None,
        title="Noindex",
        description="Set to `true` to ask search engines not to index this post. Set to `false` to remove the noindex flag.",
    )
    excerpt: str | None = Field(
        None,
        title="Excerpt",
        description="Custom summary for your post, shown in post lists and RSS. Send an empty value to revert to the automatically generated summary. Returned as `summary` in responses.",
    )
    published_at: date | None = Field(
        None,
        title="Published at",
        description="Published date and time for your post. If set the post will be published. If not set the post will be put in draft.",
    )
    featured_image: str | None = Field(
        None, title="Featured image", description="Featured image URL for your post."
    )
    featured_image_alt: str | None = Field(
        None,
        title="Featured image alt",
        description="Featured image alt text for the featured image.",
    )
    category_ids: list[int] | None = Field(
        None, title="Category ids", description="Category IDs to attach to your post."
    )
    author_id: int | None = Field(
        None,
        title="Author id",
        ge=1,
        le=2147483647,
        description="Author ID to attach to your post.",
    )
    clear_excerpt: bool = Field(
        False,
        title="Clear custom excerpt",
        description="Send an empty excerpt to restore the automatic summary.",
    )
    clear_canonical_url: bool = Field(
        False,
        title="Clear canonical URL",
        description="Send an empty canonical URL to remove it.",
    )


class DropInBlogCategoriesRetrieveConfig(_Input):
    """Retrieve a category."""

    operation: Literal["get_category"] = Field(
        "get_category",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Retrieve a category",
            "x-category": "Categories",
        },
    )
    id: int = Field(
        ..., title="Id", ge=1, le=2147483647, description="The ID of your category."
    )


class DropInBlogCategoriesRetrieveBySlugConfig(_Input):
    """Retrieve a category by slug."""

    operation: Literal["get_category_by_slug"] = Field(
        "get_category_by_slug",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Retrieve a category by slug",
            "x-category": "Categories",
        },
    )
    slug: str = Field(
        ..., title="Slug", min_length=1, description="The slug of your category."
    )


class DropInBlogAuthorsRetrieveConfig(_Input):
    """Retrieve an author."""

    operation: Literal["get_author"] = Field(
        "get_author",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Retrieve an author",
            "x-category": "Authors",
        },
    )
    id: int = Field(
        ..., title="Id", ge=1, le=2147483647, description="The ID of your author."
    )


class DropInBlogAuthorsRetrieveBySlugConfig(_Input):
    """Retrieve an author by slug."""

    operation: Literal["get_author_by_slug"] = Field(
        "get_author_by_slug",
        json_schema_extra={
            "ui:hidden": True,
            "x-display-name": "Retrieve an author by slug",
            "x-category": "Authors",
        },
    )
    slug: str = Field(
        ..., title="Slug", min_length=1, description="The slug of your author."
    )


class DropInBlogOnNewPostConfig(PollTriggerConfigBase):
    """Watch newly published posts; first scan establishes a baseline."""

    operation: Literal["on_new_post"] = Field(
        "on_new_post",
        json_schema_extra={
            "ui:hidden": True,
            "x-is-trigger": True,
            "x-display-name": "On New Published Post",
            "x-category": "Triggers",
        },
    )
    published_at_start: date | None = Field(
        None,
        title="Published on or after",
        description="Optional fixed start date to limit the monitored history.",
    )


class DropInBlogOnUpdatedPostConfig(PollTriggerConfigBase):
    """Watch new or changed published posts by ID and updatedAtIso8601."""

    operation: Literal["on_updated_post"] = Field(
        "on_updated_post",
        json_schema_extra={
            "ui:hidden": True,
            "x-is-trigger": True,
            "x-display-name": "On New or Updated Published Post",
            "x-category": "Triggers",
        },
    )
    modified_at_start: date | None = Field(
        None,
        title="Modified on or after",
        description="Optional fixed start date to limit the monitored history.",
    )


OPERATIONS = {
    "create_post": {
        "method": "POST",
        "path": "/v2/blog/{blog_id}/posts",
        "path_fields": [],
        "query": [],
        "body": [
            "title",
            "content",
            "slug",
            "seo_title",
            "seo_description",
            "keyword",
            "secondary_keywords",
            "canonical_url",
            "noindex",
            "excerpt",
            "published_at",
            "visibility",
            "featured_image",
            "featured_image_alt",
            "category_ids",
            "author_id",
            "faqs",
            "enable_toc",
        ],
        "contract_operation": "posts-create",
    },
    "list_posts": {
        "method": "GET",
        "path": "/v2/blog/{blog_id}/posts",
        "path_fields": [],
        "query": [
            "statuses",
            "visibilities",
            "page",
            "limit",
            "category_ids",
            "category_slugs",
            "author_ids",
            "author_slugs",
            "post_ids",
            "post_slugs",
            "published_at_start",
            "published_at_end",
            "modified_at_start",
            "modified_at_end",
        ],
        "body": [],
        "contract_operation": "posts-list",
    },
    "list_categories": {
        "method": "GET",
        "path": "/v2/blog/{blog_id}/categories",
        "path_fields": [],
        "query": ["exclude_without_published_post", "exclude_private"],
        "body": [],
        "contract_operation": "categories-list",
    },
    "list_authors": {
        "method": "GET",
        "path": "/v2/blog/{blog_id}/authors",
        "path_fields": [],
        "query": ["exclude_without_published_post"],
        "body": [],
        "contract_operation": "authors-list",
    },
    "get_post": {
        "method": "GET",
        "path": "/v2/blog/{blog_id}/posts/{id}",
        "path_fields": ["id"],
        "query": [],
        "body": [],
        "contract_operation": "posts-retrieve",
    },
    "update_post": {
        "method": "PATCH",
        "path": "/v2/blog/{blog_id}/posts/{id}",
        "path_fields": ["id"],
        "query": [],
        "body": [
            "title",
            "slug",
            "content",
            "seo_title",
            "seo_description",
            "keyword",
            "canonical_url",
            "noindex",
            "excerpt",
            "published_at",
            "featured_image",
            "featured_image_alt",
            "category_ids",
            "author_id",
        ],
        "contract_operation": "posts-update",
    },
    "search_posts": {
        "method": "GET",
        "path": "/v2/blog/{blog_id}/posts/search",
        "path_fields": [],
        "query": ["search", "statuses", "page", "limit"],
        "body": [],
        "contract_operation": "posts-search",
    },
    "get_post_by_slug": {
        "method": "GET",
        "path": "/v2/blog/{blog_id}/posts/slug/{slug}",
        "path_fields": ["slug"],
        "query": [],
        "body": [],
        "contract_operation": "posts-retrieve-by-slug",
    },
    "update_post_by_slug": {
        "method": "PATCH",
        "path": "/v2/blog/{blog_id}/posts/slug/{post_slug}",
        "path_fields": ["post_slug"],
        "query": [],
        "body": [
            "title",
            "slug",
            "content",
            "seo_title",
            "seo_description",
            "keyword",
            "canonical_url",
            "noindex",
            "excerpt",
            "published_at",
            "featured_image",
            "featured_image_alt",
            "category_ids",
            "author_id",
        ],
        "contract_operation": "posts-update-by-slug",
    },
    "get_category": {
        "method": "GET",
        "path": "/v2/blog/{blog_id}/categories/{id}",
        "path_fields": ["id"],
        "query": [],
        "body": [],
        "contract_operation": "categories-retrieve",
    },
    "get_category_by_slug": {
        "method": "GET",
        "path": "/v2/blog/{blog_id}/categories/slug/{slug}",
        "path_fields": ["slug"],
        "query": [],
        "body": [],
        "contract_operation": "categories-retrieve-by-slug",
    },
    "get_author": {
        "method": "GET",
        "path": "/v2/blog/{blog_id}/authors/{id}",
        "path_fields": ["id"],
        "query": [],
        "body": [],
        "contract_operation": "authors-retrieve",
    },
    "get_author_by_slug": {
        "method": "GET",
        "path": "/v2/blog/{blog_id}/authors/slug/{slug}",
        "path_fields": ["slug"],
        "query": [],
        "body": [],
        "contract_operation": "authors-retrieve-by-slug",
    },
}

DropInBlogConfig = Annotated[
    Union[
        DropInBlogPostsCreateConfig,
        DropInBlogPostsListConfig,
        DropInBlogCategoriesListConfig,
        DropInBlogAuthorsListConfig,
        DropInBlogPostsRetrieveConfig,
        DropInBlogPostsUpdateConfig,
        DropInBlogPostsSearchConfig,
        DropInBlogPostsRetrieveBySlugConfig,
        DropInBlogPostsUpdateBySlugConfig,
        DropInBlogCategoriesRetrieveConfig,
        DropInBlogCategoriesRetrieveBySlugConfig,
        DropInBlogAuthorsRetrieveConfig,
        DropInBlogAuthorsRetrieveBySlugConfig,
        DropInBlogOnNewPostConfig,
        DropInBlogOnUpdatedPostConfig,
    ],
    Field(discriminator="operation"),
]


class DropInBlogNodeConfig(NodeConfig[DropInBlogConfig, DropInBlogAPIKeyCredential]):
    pass


class DropInBlogNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-dropinblog"
    credential_provider_labels = {"dropinblog": "DropInBlog"}
    connection_evidence = ConnectionEvidence(
        operation="list_categories", noun="blog categories"
    )

    @classmethod
    def get_config_model(cls):
        return DropInBlogNodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        key = (
            credential.public_api_key if method == "GET" else credential.private_api_key
        )
        if not key:
            raise ValueError(
                "Add a DropInBlog private API key to create or update posts"
            )
        path = path.replace("{blog_id}", quote(credential.blog_id, safe=""))
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(
                method,
                "https://api.dropinblog.com" + path,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Accept": "application/json",
                },
                params=params,
                json=body,
            )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            try:
                error = response.json()
            except ValueError:
                error = {}
            message = error.get("message") if isinstance(error, dict) else None
            if isinstance(message, str) and message:
                raise httpx.HTTPStatusError(
                    f"DropInBlog HTTP {response.status_code}: {message}",
                    request=response.request,
                    response=response,
                ) from None
            raise
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError("DropInBlog returned an unexpected response")
        if result.get("success") is False:
            raise ValueError(result.get("message") or "DropInBlog rejected the request")
        if not isinstance(result.get("data"), dict):
            raise ValueError("DropInBlog response is missing data")
        return result

    async def _poll(self, credential, config):
        posts = []
        filters = config.model_dump(
            mode="json",
            exclude_none=True,
            include={"published_at_start", "modified_at_start"},
        )
        for page in range(1, 21):
            result = await self._request(
                credential,
                "GET",
                "/v2/blog/{blog_id}/posts",
                params={**filters, "page": page, "limit": 100},
            )
            data = result["data"]
            batch = data.get("posts")
            if not isinstance(batch, list) or any(
                not isinstance(p, dict) or not isinstance(p.get("id"), int)
                for p in batch
            ):
                raise ValueError("DropInBlog returned invalid posts")
            if config.operation == "on_updated_post" and any(
                not p.get("updatedAtIso8601") for p in batch
            ):
                raise ValueError(
                    "DropInBlog returned a post without an update timestamp"
                )
            posts.extend(batch)
            pagination = data.get("pagination")
            if (
                not isinstance(pagination, dict)
                or type(pagination.get("last_page")) is not int
            ):
                raise ValueError("DropInBlog response is missing pagination")
            if page >= pagination["last_page"]:
                break
        else:
            raise ValueError(
                "More than 2,000 posts match this poll; choose a later start date"
            )
        updated = config.operation == "on_updated_post"
        fresh = await self._filter_unseen(
            posts,
            lambda post: str(post["id"])
            + (":" + post["updatedAtIso8601"] if updated else ""),
        )
        return {"posts": fresh, "new_post_count": len(fresh)}

    @classmethod
    def should_propagate_output(cls, output, config):
        if config.get("operation") in {"on_new_post", "on_updated_post"}:
            return bool(output.get("new_post_count"))
        return True

    @classmethod
    def resolve_agent_event(cls, output):
        posts = output.get("posts") if isinstance(output, dict) else None
        if not isinstance(posts, list):
            return super().resolve_agent_event(output)
        if not posts:
            return None
        lines = []
        for post in posts[:10]:
            author = post.get("author") or {}
            lines.append(
                f"{post.get('title') or 'Untitled post'} — {author.get('name') or 'Unknown author'} "
                f"(post ID {post.get('id')}, slug {post.get('slug')})\n"
                f"{post.get('url') or ''}\n{str(post.get('summary') or '')[:1000]}"
            )
        return {
            "text": f"DropInBlog: {len(posts)} new or updated published post(s).\n"
            + "\n\n".join(lines),
            "conversation_key": None,
            "title": "DropInBlog post updates",
        }

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect your DropInBlog API keys")
        config = self.config.config
        if isinstance(
            config, (DropInBlogOnNewPostConfig, DropInBlogOnUpdatedPostConfig)
        ):
            return await self._poll(credential, config)
        spec = OPERATIONS[config.operation]
        values = config.model_dump(
            mode="json", exclude_none=True, exclude={"operation"}
        )
        path = spec["path"]
        for field in spec["path_fields"]:
            value = str(values[field])
            if value in {".", ".."}:
                raise ValueError("Use a resource slug, not a path traversal segment")
            path = path.replace("{" + field + "}", quote(value, safe=""))
        body = {field: values[field] for field in spec["body"] if field in values}
        if spec["method"] == "PATCH":
            if values.get("clear_excerpt"):
                body["excerpt"] = ""
            if values.get("clear_canonical_url"):
                body["canonical_url"] = ""
        if spec["method"] == "PATCH" and not body:
            raise ValueError("Choose at least one post field to update")
        params = {field: values[field] for field in spec["query"] if field in values}
        return await self._request(
            credential, spec["method"], path, params=params, body=body or None
        )
