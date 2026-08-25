"""
Confluence Cloud REST API automation node.

Provides workflow integration with Confluence Cloud for operations including:
- Pages: list, get, create, update, delete, list in space, list children, versions, ancestors
- Blog posts: list, get, create, update, delete
- Spaces: list, get, create, list space labels
- Comments: list/create/update/delete footer & inline comments (pages + blog posts)
- Attachments: list, get, upload, delete
- Labels: list page labels, add label, remove label
- Content properties: list, create, update, delete
- Tasks: list, get, update status
- Search: CQL search (content + general), get current user

Authentication:
- Basic auth (Atlassian account email + API token) — the simplest fully working
  self-serve path. Calls go to https://<your-domain>.atlassian.net/wiki/...
- OAuth 2.0 (3LO) via Atlassian — credential model included; calls route through
  https://api.atlassian.com/ex/confluence/{cloudid}/wiki/...

API base (v2): /wiki/api/v2  ·  API base (v1, for CQL search / current-user /
attachment upload / add-label / remove-label): /wiki/rest/api

Documentation: https://developer.atlassian.com/cloud/confluence/rest/v2/intro/
"""

import base64
import logging
import time
import uuid as uuid_module
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from utils.ssrf import guarded_async_client, normalize_provider_subdomain
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.scopes.confluence import CONFLUENCE_SCOPES
from nodes.cron_trigger_node import (
    ScheduleConfig,
    schedule_to_cron,
    schedule_to_interval_ms,
)

logger = logging.getLogger(__name__)

# Default Confluence body representation for create/update operations.
DEFAULT_BODY_FORMAT = "storage"


# ============================================================================
# Credential Schemas
# ============================================================================

# Classic OAuth 2.0 (3LO) scopes covering all node operations, plus offline_access
# so Atlassian returns a (rotating) refresh token.
CONFLUENCE_OAUTH_SCOPES = [
    # Classic scopes — required for v1 endpoints (CQL search, add/remove label,
    # upload attachment, get current user) which still live on /wiki/rest/api.
    "read:confluence-content.all",
    "read:confluence-content.summary",
    "write:confluence-content",
    "read:confluence-space.summary",
    "write:confluence-space",
    "write:confluence-file",
    "readonly:content.attachment:confluence",
    "read:confluence-props",
    "write:confluence-props",
    "search:confluence",
    "read:confluence-user",
    "read:confluence-groups",
    # Granular scopes — required for Confluence REST API v2 (/wiki/api/v2).
    # The v2 API does NOT accept classic scopes; both sets must be requested.
    "read:space:confluence",
    "write:space:confluence",
    "read:page:confluence",
    "write:page:confluence",
    "delete:page:confluence",
    "read:blogpost:confluence",
    "write:blogpost:confluence",
    "delete:blogpost:confluence",
    "read:comment:confluence",
    "write:comment:confluence",
    "delete:comment:confluence",
    "read:attachment:confluence",
    "write:attachment:confluence",
    "delete:attachment:confluence",
    "read:label:confluence",
    "write:label:confluence",
    "read:content-details:confluence",
    "write:content-details:confluence",
    "delete:content-details:confluence",
    "read:user:confluence",
    "read:group:confluence",
    "read:inlinetask:confluence",
    "write:inlinetask:confluence",
    "read:task:confluence",
    "write:task:confluence",
    "offline_access",
]


class ConfluenceOAuthCredential(BaseModel):
    """OAuth 2.0 (3LO) credential for Confluence Cloud.

    Tokens are obtained via the Atlassian OAuth flow, not entered manually.
    Register an app at https://developer.atlassian.com/console/myapps/
    """

    credential_type: Literal["confluence_oauth"] = Field(
        "confluence_oauth", json_schema_extra={"ui:hidden": True}
    )
    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "atlassian",
            "x-oauth-scopes": CONFLUENCE_OAUTH_SCOPES,
        }
    )

    access_token: str = Field(..., title="Access Token")
    refresh_token: str = Field(..., title="Refresh Token")
    expires_at: str = Field(..., title="Token Expiry")  # ISO 8601
    cloud_id: str = Field(
        ..., title="Cloud ID", description="Atlassian Cloud ID for API requests"
    )
    email: Optional[str] = Field(None, title="Account Email")
    site_name: Optional[str] = Field(
        None, title="Site Name", description="Confluence site name for display"
    )
    site_url: Optional[str] = Field(
        None, title="Site URL", description="Confluence site URL for display"
    )
    scope: Optional[str] = Field(
        None,
        title="Granted Scopes",
        description="OAuth scopes currently granted to this Confluence credential",
    )


class ConfluenceApiTokenCredential(BaseModel):
    """Basic-auth credential for Confluence Cloud (Atlassian email + API token).

    Create an API token at https://id.atlassian.com/manage-profile/security/api-tokens
    """

    credential_type: Literal["confluence_api_token"] = Field(
        "confluence_api_token", json_schema_extra={"ui:hidden": True}
    )
    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://id.atlassian.com/manage-profile/security/api-tokens"
        }
    )

    email: str = Field(
        ...,
        title="Email",
        description="Email address associated with your Atlassian account",
    )
    api_token: str = Field(
        ...,
        title="API Token",
        description="Your Atlassian API token",
        json_schema_extra={"ui:widget": "password"},
    )
    domain: str = Field(
        ...,
        title="Confluence Domain",
        description="Your Confluence Cloud domain (e.g., yourcompany.atlassian.net)",
        json_schema_extra={"placeholder": "yourcompany.atlassian.net"},
    )


# Union — OAuth shown first in the UI (better UX). The OAuth app-handler for the
# confluence_oauth credential type is a human follow-up; Basic auth works today.
ConfluenceCredential = Union[ConfluenceOAuthCredential, ConfluenceApiTokenCredential]


# ============================================================================
# Operation Configs
# ============================================================================


# --- Pages ---


class ConfluenceListPagesConfig(BaseModel):
    """List pages, optionally filtered by space, status, or title."""

    operation: Literal["list_pages"] = Field(
        "list_pages",
        json_schema_extra={
            "const": "list_pages",
            "ui:hidden": True,
            "x-category": "Pages",
            "x-is-trigger": False,
            "x-display-name": "List Pages",
        },
        title="List Pages",
    )
    space_id: Optional[str] = Field(
        None,
        title="Space",
        description="Filter to a single space",
        json_schema_extra={
            "x-resource-type": "confluence_space",
            "x-dynamic-options": {
                "field_name": "space_id",
                "placeholder": "Select a space...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a space ID",
            }
        },
    )
    status: Optional[str] = Field(
        None,
        title="Status",
        description="Filter by page status",
        json_schema_extra={
            "enum": ["", "current", "archived", "deleted", "trashed"],
            "enumNames": ["Any", "Current", "Archived", "Deleted", "Trashed"],
            "x-enum-searchable": True,
        },
    )
    title: Optional[str] = Field(
        None, title="Title", description="Filter to pages with this exact title"
    )
    limit: Optional[str] = Field(
        "25", title="Limit", description="Max number of pages to return (1-250)"
    )


class ConfluenceGetPageConfig(BaseModel):
    """Get a single page by ID, optionally including its body."""

    operation: Literal["get_page"] = Field(
        "get_page",
        json_schema_extra={
            "const": "get_page",
            "ui:hidden": True,
            "x-category": "Pages",
            "x-is-trigger": False,
            "x-display-name": "Get Page",
        },
        title="Get Page",
    )
    page_id: str = Field(..., title="Page ID", description="The numeric ID of the page")
    body_format: Optional[str] = Field(
        "storage",
        title="Body Format",
        description="Representation to return the page body in",
        json_schema_extra={
            "enum": ["storage", "atlas_doc_format", "view", ""],
            "enumNames": ["Storage (XHTML)", "Atlas Doc Format (ADF)", "View (HTML)", "None"],
            "x-enum-searchable": True,
        },
    )


class ConfluenceCreatePageConfig(BaseModel):
    """Create a page in a space."""

    operation: Literal["create_page"] = Field(
        "create_page",
        json_schema_extra={
            "const": "create_page",
            "ui:hidden": True,
            "x-category": "Pages",
            "x-is-trigger": False,
            "x-display-name": "Create Page",
        },
        title="Create Page",
    )
    space_id: str = Field(
        ...,
        title="Space",
        description="The space to create the page in",
        json_schema_extra={
            "x-resource-type": "confluence_space",
            "x-dynamic-options": {
                "field_name": "space_id",
                "placeholder": "Select a space...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a space ID",
            }
        },
    )
    title: str = Field(..., title="Title", description="The page title")
    body: Optional[str] = Field(
        None,
        title="Body",
        description="Page body content (Confluence storage XHTML by default)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    parent_id: Optional[str] = Field(
        None, title="Parent Page ID", description="Create as a child of this page"
    )
    status: Optional[str] = Field(
        "current",
        title="Status",
        description="Initial page status",
        json_schema_extra={
            "enum": ["current", "draft"],
            "enumNames": ["Current (published)", "Draft"],
            "x-enum-searchable": True,
        },
    )
    representation: Optional[str] = Field(
        "storage",
        title="Body Representation",
        description="Format of the supplied body",
        json_schema_extra={
            "enum": ["storage", "atlas_doc_format", "wiki"],
            "enumNames": ["Storage (XHTML)", "Atlas Doc Format (ADF)", "Wiki markup"],
            "x-enum-searchable": True,
        },
    )


class ConfluenceUpdatePageConfig(BaseModel):
    """Update a page. Requires the new version number (current + 1)."""

    operation: Literal["update_page"] = Field(
        "update_page",
        json_schema_extra={
            "const": "update_page",
            "ui:hidden": True,
            "x-category": "Pages",
            "x-is-trigger": False,
            "x-display-name": "Update Page",
        },
        title="Update Page",
    )
    page_id: str = Field(..., title="Page ID", description="The ID of the page to update")
    version_number: str = Field(
        ...,
        title="New Version Number",
        description="The page's current version number plus one",
    )
    title: str = Field(..., title="Title", description="The page title (required by the API)")
    body: Optional[str] = Field(
        None,
        title="Body",
        description="Updated page body content",
        json_schema_extra={"ui:widget": "textarea"},
    )
    status: Optional[str] = Field(
        "current",
        title="Status",
        description="Page status",
        json_schema_extra={
            "enum": ["current", "draft", "archived"],
            "enumNames": ["Current", "Draft", "Archived"],
            "x-enum-searchable": True,
        },
    )
    representation: Optional[str] = Field(
        "storage",
        title="Body Representation",
        description="Format of the supplied body",
        json_schema_extra={
            "enum": ["storage", "atlas_doc_format", "wiki"],
            "enumNames": ["Storage (XHTML)", "Atlas Doc Format (ADF)", "Wiki markup"],
            "x-enum-searchable": True,
        },
    )
    version_message: Optional[str] = Field(
        None, title="Version Message", description="Optional note describing this change"
    )


class ConfluenceDeletePageConfig(BaseModel):
    """Trash (or permanently purge) a page."""

    operation: Literal["delete_page"] = Field(
        "delete_page",
        json_schema_extra={
            "const": "delete_page",
            "ui:hidden": True,
            "x-category": "Pages",
            "x-is-trigger": False,
            "x-display-name": "Delete Page",
        },
        title="Delete Page",
    )
    page_id: str = Field(..., title="Page ID", description="The ID of the page to delete")
    purge: Optional[str] = Field(
        "false",
        title="Purge Permanently",
        description="Permanently delete (only works on already-trashed pages)",
        json_schema_extra={
            "enum": ["false", "true"],
            "enumNames": ["No (move to trash)", "Yes (purge permanently)"],
            "x-enum-searchable": True,
        },
    )


class ConfluenceListPagesInSpaceConfig(BaseModel):
    """List all pages within a given space."""

    operation: Literal["list_pages_in_space"] = Field(
        "list_pages_in_space",
        json_schema_extra={
            "const": "list_pages_in_space",
            "ui:hidden": True,
            "x-category": "Pages",
            "x-is-trigger": False,
            "x-display-name": "List Pages in Space",
        },
        title="List Pages in Space",
    )
    space_id: str = Field(
        ...,
        title="Space",
        description="The space whose pages to list",
        json_schema_extra={
            "x-resource-type": "confluence_space",
            "x-dynamic-options": {
                "field_name": "space_id",
                "placeholder": "Select a space...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a space ID",
            }
        },
    )
    status: Optional[str] = Field(
        None,
        title="Status",
        description="Filter by page status",
        json_schema_extra={
            "enum": ["", "current", "archived", "trashed"],
            "enumNames": ["Any", "Current", "Archived", "Trashed"],
            "x-enum-searchable": True,
        },
    )
    limit: Optional[str] = Field(
        "25", title="Limit", description="Max number of pages to return (1-250)"
    )


class ConfluenceListChildPagesConfig(BaseModel):
    """List the direct child pages of a page."""

    operation: Literal["list_child_pages"] = Field(
        "list_child_pages",
        json_schema_extra={
            "const": "list_child_pages",
            "ui:hidden": True,
            "x-category": "Pages",
            "x-is-trigger": False,
            "x-display-name": "List Child Pages",
        },
        title="List Child Pages",
    )
    page_id: str = Field(..., title="Page ID", description="The parent page ID")
    limit: Optional[str] = Field(
        "25", title="Limit", description="Max number of children to return (1-250)"
    )


class ConfluenceGetPageVersionsConfig(BaseModel):
    """List the version history of a page."""

    operation: Literal["get_page_versions"] = Field(
        "get_page_versions",
        json_schema_extra={
            "const": "get_page_versions",
            "ui:hidden": True,
            "x-category": "Pages",
            "x-is-trigger": False,
            "x-display-name": "Get Page Versions",
        },
        title="Get Page Versions",
    )
    page_id: str = Field(..., title="Page ID", description="The page whose versions to list")
    limit: Optional[str] = Field(
        "25", title="Limit", description="Max number of versions to return (1-250)"
    )


# --- Blog Posts ---


class ConfluenceListBlogPostsConfig(BaseModel):
    """List blog posts, optionally filtered by space or status."""

    operation: Literal["list_blog_posts"] = Field(
        "list_blog_posts",
        json_schema_extra={
            "const": "list_blog_posts",
            "ui:hidden": True,
            "x-category": "Blog Posts",
            "x-is-trigger": False,
            "x-display-name": "List Blog Posts",
        },
        title="List Blog Posts",
    )
    space_id: Optional[str] = Field(
        None,
        title="Space",
        description="Filter to a single space",
        json_schema_extra={
            "x-resource-type": "confluence_space",
            "x-dynamic-options": {
                "field_name": "space_id",
                "placeholder": "Select a space...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a space ID",
            }
        },
    )
    status: Optional[str] = Field(
        None,
        title="Status",
        description="Filter by blog post status",
        json_schema_extra={
            "enum": ["", "current", "archived", "trashed", "deleted"],
            "enumNames": ["Any", "Current", "Archived", "Trashed", "Deleted"],
            "x-enum-searchable": True,
        },
    )
    limit: Optional[str] = Field(
        "25", title="Limit", description="Max number of blog posts to return (1-250)"
    )


class ConfluenceGetBlogPostConfig(BaseModel):
    """Get a single blog post by ID, optionally including its body."""

    operation: Literal["get_blog_post"] = Field(
        "get_blog_post",
        json_schema_extra={
            "const": "get_blog_post",
            "ui:hidden": True,
            "x-category": "Blog Posts",
            "x-is-trigger": False,
            "x-display-name": "Get Blog Post",
        },
        title="Get Blog Post",
    )
    blog_post_id: str = Field(
        ..., title="Blog Post ID", description="The numeric ID of the blog post"
    )
    body_format: Optional[str] = Field(
        "storage",
        title="Body Format",
        description="Representation to return the body in",
        json_schema_extra={
            "enum": ["storage", "atlas_doc_format", "view", ""],
            "enumNames": ["Storage (XHTML)", "Atlas Doc Format (ADF)", "View (HTML)", "None"],
            "x-enum-searchable": True,
        },
    )


class ConfluenceCreateBlogPostConfig(BaseModel):
    """Create a blog post in a space."""

    operation: Literal["create_blog_post"] = Field(
        "create_blog_post",
        json_schema_extra={
            "const": "create_blog_post",
            "ui:hidden": True,
            "x-category": "Blog Posts",
            "x-is-trigger": False,
            "x-display-name": "Create Blog Post",
        },
        title="Create Blog Post",
    )
    space_id: str = Field(
        ...,
        title="Space",
        description="The space to create the blog post in",
        json_schema_extra={
            "x-resource-type": "confluence_space",
            "x-dynamic-options": {
                "field_name": "space_id",
                "placeholder": "Select a space...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a space ID",
            }
        },
    )
    title: str = Field(..., title="Title", description="The blog post title")
    body: Optional[str] = Field(
        None,
        title="Body",
        description="Blog post body content",
        json_schema_extra={"ui:widget": "textarea"},
    )
    status: Optional[str] = Field(
        "current",
        title="Status",
        description="Initial status",
        json_schema_extra={
            "enum": ["current", "draft"],
            "enumNames": ["Current (published)", "Draft"],
            "x-enum-searchable": True,
        },
    )
    representation: Optional[str] = Field(
        "storage",
        title="Body Representation",
        description="Format of the supplied body",
        json_schema_extra={
            "enum": ["storage", "atlas_doc_format", "wiki"],
            "enumNames": ["Storage (XHTML)", "Atlas Doc Format (ADF)", "Wiki markup"],
            "x-enum-searchable": True,
        },
    )


class ConfluenceUpdateBlogPostConfig(BaseModel):
    """Update a blog post. Requires the new version number (current + 1)."""

    operation: Literal["update_blog_post"] = Field(
        "update_blog_post",
        json_schema_extra={
            "const": "update_blog_post",
            "ui:hidden": True,
            "x-category": "Blog Posts",
            "x-is-trigger": False,
            "x-display-name": "Update Blog Post",
        },
        title="Update Blog Post",
    )
    blog_post_id: str = Field(
        ..., title="Blog Post ID", description="The ID of the blog post to update"
    )
    version_number: str = Field(
        ...,
        title="New Version Number",
        description="The current version number plus one",
    )
    title: str = Field(..., title="Title", description="The blog post title")
    body: Optional[str] = Field(
        None,
        title="Body",
        description="Updated blog post body content",
        json_schema_extra={"ui:widget": "textarea"},
    )
    status: Optional[str] = Field(
        "current",
        title="Status",
        description="Status",
        json_schema_extra={
            "enum": ["current", "draft", "archived"],
            "enumNames": ["Current", "Draft", "Archived"],
            "x-enum-searchable": True,
        },
    )
    representation: Optional[str] = Field(
        "storage",
        title="Body Representation",
        description="Format of the supplied body",
        json_schema_extra={
            "enum": ["storage", "atlas_doc_format", "wiki"],
            "enumNames": ["Storage (XHTML)", "Atlas Doc Format (ADF)", "Wiki markup"],
            "x-enum-searchable": True,
        },
    )


class ConfluenceDeleteBlogPostConfig(BaseModel):
    """Delete a blog post."""

    operation: Literal["delete_blog_post"] = Field(
        "delete_blog_post",
        json_schema_extra={
            "const": "delete_blog_post",
            "ui:hidden": True,
            "x-category": "Blog Posts",
            "x-is-trigger": False,
            "x-display-name": "Delete Blog Post",
        },
        title="Delete Blog Post",
    )
    blog_post_id: str = Field(
        ..., title="Blog Post ID", description="The ID of the blog post to delete"
    )
    purge: Optional[str] = Field(
        "false",
        title="Purge Permanently",
        description="Permanently delete (only works on already-trashed posts)",
        json_schema_extra={
            "enum": ["false", "true"],
            "enumNames": ["No (move to trash)", "Yes (purge permanently)"],
            "x-enum-searchable": True,
        },
    )


# --- Spaces ---


class ConfluenceListSpacesConfig(BaseModel):
    """List spaces, optionally filtered by key, type, or status."""

    operation: Literal["list_spaces"] = Field(
        "list_spaces",
        json_schema_extra={
            "const": "list_spaces",
            "ui:hidden": True,
            "x-category": "Spaces",
            "x-is-trigger": False,
            "x-display-name": "List Spaces",
        },
        title="List Spaces",
    )
    keys: Optional[str] = Field(
        None, title="Keys", description="Filter to these space keys, comma-separated"
    )
    type: Optional[str] = Field(
        None,
        title="Type",
        description="Filter by space type",
        json_schema_extra={
            "enum": ["", "global", "personal", "collaboration", "knowledge_base"],
            "enumNames": ["Any", "Global", "Personal", "Collaboration", "Knowledge Base"],
            "x-enum-searchable": True,
        },
    )
    status: Optional[str] = Field(
        None,
        title="Status",
        description="Filter by space status",
        json_schema_extra={
            "enum": ["", "current", "archived"],
            "enumNames": ["Any", "Current", "Archived"],
            "x-enum-searchable": True,
        },
    )
    limit: Optional[str] = Field(
        "25", title="Limit", description="Max number of spaces to return (1-250)"
    )


class ConfluenceGetSpaceConfig(BaseModel):
    """Get a single space by ID."""

    operation: Literal["get_space"] = Field(
        "get_space",
        json_schema_extra={
            "const": "get_space",
            "ui:hidden": True,
            "x-category": "Spaces",
            "x-is-trigger": False,
            "x-display-name": "Get Space",
        },
        title="Get Space",
    )
    space_id: str = Field(
        ...,
        title="Space",
        description="The space to retrieve",
        json_schema_extra={
            "x-resource-type": "confluence_space",
            "x-dynamic-options": {
                "field_name": "space_id",
                "placeholder": "Select a space...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a space ID",
            }
        },
    )


class ConfluenceListSpaceLabelsConfig(BaseModel):
    """List labels applied to a space."""

    operation: Literal["list_space_labels"] = Field(
        "list_space_labels",
        json_schema_extra={
            "const": "list_space_labels",
            "ui:hidden": True,
            "x-category": "Spaces",
            "x-is-trigger": False,
            "x-display-name": "List Space Labels",
        },
        title="List Space Labels",
    )
    space_id: str = Field(
        ...,
        title="Space",
        description="The space whose labels to list",
        json_schema_extra={
            "x-resource-type": "confluence_space",
            "x-dynamic-options": {
                "field_name": "space_id",
                "placeholder": "Select a space...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a space ID",
            }
        },
    )
    limit: Optional[str] = Field(
        "25", title="Limit", description="Max number of labels to return (1-250)"
    )


# --- Comments ---


class ConfluenceListFooterCommentsConfig(BaseModel):
    """List footer comments on a page."""

    operation: Literal["list_footer_comments"] = Field(
        "list_footer_comments",
        json_schema_extra={
            "const": "list_footer_comments",
            "ui:hidden": True,
            "x-category": "Comments",
            "x-is-trigger": False,
            "x-display-name": "List Footer Comments",
        },
        title="List Footer Comments",
    )
    page_id: str = Field(..., title="Page ID", description="The page whose footer comments to list")
    limit: Optional[str] = Field(
        "25", title="Limit", description="Max number of comments to return (1-250)"
    )


class ConfluenceCreateFooterCommentConfig(BaseModel):
    """Add a footer comment to a page or blog post."""

    operation: Literal["create_footer_comment"] = Field(
        "create_footer_comment",
        json_schema_extra={
            "const": "create_footer_comment",
            "ui:hidden": True,
            "x-category": "Comments",
            "x-is-trigger": False,
            "x-display-name": "Create Footer Comment",
        },
        title="Create Footer Comment",
    )
    page_id: Optional[str] = Field(
        None, title="Page ID", description="The page to comment on (or use Blog Post ID)"
    )
    blog_post_id: Optional[str] = Field(
        None, title="Blog Post ID", description="The blog post to comment on (or use Page ID)"
    )
    body: str = Field(
        ...,
        title="Comment Body",
        description="The comment content",
        json_schema_extra={"ui:widget": "textarea"},
    )
    representation: Optional[str] = Field(
        "storage",
        title="Body Representation",
        description="Format of the supplied body",
        json_schema_extra={
            "enum": ["storage", "atlas_doc_format", "wiki"],
            "enumNames": ["Storage (XHTML)", "Atlas Doc Format (ADF)", "Wiki markup"],
            "x-enum-searchable": True,
        },
    )


class ConfluenceListInlineCommentsConfig(BaseModel):
    """List inline (highlight) comments on a page."""

    operation: Literal["list_inline_comments"] = Field(
        "list_inline_comments",
        json_schema_extra={
            "const": "list_inline_comments",
            "ui:hidden": True,
            "x-category": "Comments",
            "x-is-trigger": False,
            "x-display-name": "List Inline Comments",
        },
        title="List Inline Comments",
    )
    page_id: str = Field(..., title="Page ID", description="The page whose inline comments to list")
    limit: Optional[str] = Field(
        "25", title="Limit", description="Max number of comments to return (1-250)"
    )


class ConfluenceCreateInlineCommentConfig(BaseModel):
    """Create an inline comment anchored to selected text on a page or blog post."""

    operation: Literal["create_inline_comment"] = Field(
        "create_inline_comment",
        json_schema_extra={
            "const": "create_inline_comment",
            "ui:hidden": True,
            "x-category": "Comments",
            "x-is-trigger": False,
            "x-display-name": "Create Inline Comment",
        },
        title="Create Inline Comment",
    )
    page_id: Optional[str] = Field(
        None, title="Page ID", description="The page to comment on (or use Blog Post ID)"
    )
    blog_post_id: Optional[str] = Field(
        None, title="Blog Post ID", description="The blog post to comment on (or use Page ID)"
    )
    body: str = Field(
        ...,
        title="Comment Body",
        description="The comment content",
        json_schema_extra={"ui:widget": "textarea"},
    )
    selection_text: str = Field(
        ...,
        title="Highlighted Text",
        description="The exact text the inline comment anchors to",
    )
    match_index: Optional[str] = Field(
        "0",
        title="Match Index",
        description=(
            "Which occurrence of the highlighted text to anchor to when it appears "
            "more than once (0 = first occurrence)"
        ),
    )
    representation: Optional[str] = Field(
        "storage",
        title="Body Representation",
        description="Format of the supplied body",
        json_schema_extra={
            "enum": ["storage", "atlas_doc_format", "wiki"],
            "enumNames": ["Storage (XHTML)", "Atlas Doc Format (ADF)", "Wiki markup"],
            "x-enum-searchable": True,
        },
    )


# --- Attachments ---


class ConfluenceListAttachmentsConfig(BaseModel):
    """List attachments on a page."""

    operation: Literal["list_attachments"] = Field(
        "list_attachments",
        json_schema_extra={
            "const": "list_attachments",
            "ui:hidden": True,
            "x-category": "Attachments",
            "x-is-trigger": False,
            "x-display-name": "List Attachments",
        },
        title="List Attachments",
    )
    page_id: str = Field(..., title="Page ID", description="The page whose attachments to list")
    limit: Optional[str] = Field(
        "25", title="Limit", description="Max number of attachments to return (1-250)"
    )


class ConfluenceGetAttachmentConfig(BaseModel):
    """Get attachment metadata, including its download link."""

    operation: Literal["get_attachment"] = Field(
        "get_attachment",
        json_schema_extra={
            "const": "get_attachment",
            "ui:hidden": True,
            "x-category": "Attachments",
            "x-is-trigger": False,
            "x-display-name": "Get Attachment",
        },
        title="Get Attachment",
    )
    attachment_id: str = Field(
        ..., title="Attachment ID", description="The ID of the attachment"
    )


# --- Labels ---


class ConfluenceListPageLabelsConfig(BaseModel):
    """List labels attached to a page."""

    operation: Literal["list_page_labels"] = Field(
        "list_page_labels",
        json_schema_extra={
            "const": "list_page_labels",
            "ui:hidden": True,
            "x-category": "Labels",
            "x-is-trigger": False,
            "x-display-name": "List Page Labels",
        },
        title="List Page Labels",
    )
    page_id: str = Field(..., title="Page ID", description="The page whose labels to list")
    limit: Optional[str] = Field(
        "25", title="Limit", description="Max number of labels to return (1-250)"
    )


class ConfluenceAddLabelConfig(BaseModel):
    """Add a label to content (page or blog post). Uses the v1 API."""

    operation: Literal["add_label"] = Field(
        "add_label",
        json_schema_extra={
            "const": "add_label",
            "ui:hidden": True,
            "x-category": "Labels",
            "x-is-trigger": False,
            "x-display-name": "Add Label",
        },
        title="Add Label",
    )
    content_id: str = Field(
        ..., title="Content ID", description="The page or blog post ID to label"
    )
    label: str = Field(..., title="Label", description="The label name to add")
    prefix: Optional[str] = Field(
        "global",
        title="Prefix",
        description="Label prefix namespace",
        json_schema_extra={
            "enum": ["global", "my", "team"],
            "enumNames": ["Global", "My (personal)", "Team"],
            "x-enum-searchable": True,
        },
    )


# --- Content Properties ---


class ConfluenceListContentPropertiesConfig(BaseModel):
    """List custom content properties (key/value metadata) on a page."""

    operation: Literal["list_content_properties"] = Field(
        "list_content_properties",
        json_schema_extra={
            "const": "list_content_properties",
            "ui:hidden": True,
            "x-category": "Properties",
            "x-is-trigger": False,
            "x-display-name": "List Content Properties",
        },
        title="List Content Properties",
    )
    page_id: str = Field(..., title="Page ID", description="The page whose properties to list")
    limit: Optional[str] = Field(
        "25", title="Limit", description="Max number of properties to return (1-250)"
    )


class ConfluenceCreateContentPropertyConfig(BaseModel):
    """Set a custom content property on a page."""

    operation: Literal["create_content_property"] = Field(
        "create_content_property",
        json_schema_extra={
            "const": "create_content_property",
            "ui:hidden": True,
            "x-category": "Properties",
            "x-is-trigger": False,
            "x-display-name": "Create Content Property",
        },
        title="Create Content Property",
    )
    page_id: str = Field(..., title="Page ID", description="The page to set the property on")
    property_key: str = Field(
        ..., title="Property Key", description="The property key (name)"
    )
    property_value: str = Field(
        ...,
        title="Property Value",
        description="The property value as a JSON literal (e.g. \"text\", 42, {\"a\":1})",
        json_schema_extra={"ui:widget": "textarea"},
    )


# --- Search & User ---


class ConfluenceSearchConfig(BaseModel):
    """Full-text / structured search via CQL (v1). Returns search results."""

    operation: Literal["search"] = Field(
        "search",
        json_schema_extra={
            "const": "search",
            "ui:hidden": True,
            "x-category": "Search",
            "x-is-trigger": False,
            "x-display-name": "Search (CQL)",
        },
        title="Search (CQL)",
    )
    cql: str = Field(
        ...,
        title="CQL Query",
        description='Confluence Query Language (e.g. type=page AND space=DEV AND text~"release notes")',
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": 'type=page AND text~"release notes"',
        },
    )
    limit: Optional[str] = Field(
        "25", title="Limit", description="Max number of results to return (1-100)"
    )


class ConfluenceSearchContentConfig(BaseModel):
    """CQL search returning content objects only (v1)."""

    operation: Literal["search_content"] = Field(
        "search_content",
        json_schema_extra={
            "const": "search_content",
            "ui:hidden": True,
            "x-category": "Search",
            "x-is-trigger": False,
            "x-display-name": "Search Content (CQL)",
        },
        title="Search Content (CQL)",
    )
    cql: str = Field(
        ...,
        title="CQL Query",
        description='Confluence Query Language (e.g. type=page AND space=DEV)',
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "type=page AND space=DEV",
        },
    )
    limit: Optional[str] = Field(
        "25", title="Limit", description="Max number of results to return (1-100)"
    )


class ConfluenceGetCurrentUserConfig(BaseModel):
    """Get the authenticated user's account info (v1)."""

    operation: Literal["get_current_user"] = Field(
        "get_current_user",
        json_schema_extra={
            "const": "get_current_user",
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get Current User",
        },
        title="Get Current User",
    )


# --- Trigger ---


class ConfluenceOnNewContentConfig(BaseModel):
    """Poll-based trigger: fire when new pages/blogposts/comments are created.

    Confluence has no general inbound webhook for REST/Basic-auth clients, so we
    poll the v1 CQL search (``type IN (page, blogpost, comment) order by created
    desc``) on a schedule and emit only content created since the last poll,
    deduped on the most-recent content id.
    """

    operation: Literal["on_new_content"] = Field(
        "on_new_content",
        json_schema_extra={
            "const": "on_new_content",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On New Content",
        },
        title="On New Content",
    )
    space_id: Optional[str] = Field(
        None,
        title="Space",
        description="Only watch a single space (optional; watches all spaces if blank)",
        json_schema_extra={
            "x-resource-type": "confluence_space",
            "x-dynamic-options": {
                "field_name": "space_id",
                "placeholder": "Select a space...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or type a numeric space ID",
            }
        },
    )
    content_type: str = Field(
        "page",
        title="Content Type",
        description="Which kind of newly-created content to watch",
        json_schema_extra={
            "enum": ["page", "blogpost", "comment", "all"],
            "enumNames": ["Pages", "Blog posts", "Comments", "Any (page/blogpost/comment)"],
            "x-enum-searchable": True,
        },
    )
    schedule: Optional[ScheduleConfig] = Field(
        default=ScheduleConfig(frequency="minutes", interval=5),
        title="Check Frequency",
        description="How often to check for new content",
        json_schema_extra={
            "ui:widget": "schedule",
            "x-exclude-frequencies": ["seconds"],
        },
    )
    max_results: str = Field(
        "25",
        title="Max Items",
        description="Maximum number of new items to fetch per check (1-100)",
        json_schema_extra={"ui:hidden": True},
    )
    # Cursor: id of the newest item seen on the previous poll (dedup boundary).
    last_seen_id: Optional[str] = Field(
        default=None,
        json_schema_extra={"ui:hidden": True},
    )
    last_polled_at: Optional[str] = Field(
        default=None,
        json_schema_extra={"ui:hidden": True},
    )
    # Hidden internal fields for webhook/schedule management.
    webhook_id: Optional[str] = Field(
        default=None,
        json_schema_extra={"ui:hidden": True},
    )
    webhook_url: Optional[str] = Field(
        default=None,
        json_schema_extra={"ui:hidden": True, "ui:loadValue": True, "ui:copyable": True},
    )
    schedule_id: Optional[str] = Field(
        default=None,
        json_schema_extra={"ui:hidden": True},
    )
    next_run: Optional[str] = Field(
        default=None,
        title="Next Check",
        json_schema_extra={"ui:widget": "nextRun"},
    )
    interval_ms: Optional[int] = Field(
        default=None,
        json_schema_extra={"ui:hidden": True},
    )
    is_active: Optional[bool] = Field(
        default=True,
        json_schema_extra={"ui:hidden": True},
    )


# --- Comment updates/deletes ---


class ConfluenceUpdateFooterCommentConfig(BaseModel):
    """Update the body of a footer comment."""

    operation: Literal["update_footer_comment"] = Field(
        "update_footer_comment",
        json_schema_extra={
            "const": "update_footer_comment",
            "ui:hidden": True,
            "x-category": "Comments",
            "x-is-trigger": False,
            "x-display-name": "Update Footer Comment",
        },
        title="Update Footer Comment",
    )
    comment_id: str = Field(..., title="Comment ID", description="The ID of the footer comment to update")
    version_number: str = Field(..., title="New Version Number", description="Current version + 1")
    body: str = Field(
        ...,
        title="Body",
        description="Updated comment body",
        json_schema_extra={"ui:widget": "textarea"},
    )
    representation: Optional[str] = Field(
        "storage",
        title="Body Representation",
        json_schema_extra={
            "enum": ["storage", "atlas_doc_format", "wiki"],
            "enumNames": ["Storage (XHTML)", "Atlas Doc Format (ADF)", "Wiki markup"],
            "x-enum-searchable": True,
        },
    )


class ConfluenceDeleteFooterCommentConfig(BaseModel):
    """Delete a footer comment."""

    operation: Literal["delete_footer_comment"] = Field(
        "delete_footer_comment",
        json_schema_extra={
            "const": "delete_footer_comment",
            "ui:hidden": True,
            "x-category": "Comments",
            "x-is-trigger": False,
            "x-display-name": "Delete Footer Comment",
        },
        title="Delete Footer Comment",
    )
    comment_id: str = Field(..., title="Comment ID", description="The ID of the footer comment to delete")


class ConfluenceUpdateInlineCommentConfig(BaseModel):
    """Update the body of an inline comment."""

    operation: Literal["update_inline_comment"] = Field(
        "update_inline_comment",
        json_schema_extra={
            "const": "update_inline_comment",
            "ui:hidden": True,
            "x-category": "Comments",
            "x-is-trigger": False,
            "x-display-name": "Update Inline Comment",
        },
        title="Update Inline Comment",
    )
    comment_id: str = Field(..., title="Comment ID", description="The ID of the inline comment to update")
    version_number: str = Field(..., title="New Version Number", description="Current version + 1")
    body: str = Field(
        ...,
        title="Body",
        description="Updated comment body",
        json_schema_extra={"ui:widget": "textarea"},
    )
    representation: Optional[str] = Field(
        "storage",
        title="Body Representation",
        json_schema_extra={
            "enum": ["storage", "atlas_doc_format", "wiki"],
            "enumNames": ["Storage (XHTML)", "Atlas Doc Format (ADF)", "Wiki markup"],
            "x-enum-searchable": True,
        },
    )


class ConfluenceDeleteInlineCommentConfig(BaseModel):
    """Delete an inline comment."""

    operation: Literal["delete_inline_comment"] = Field(
        "delete_inline_comment",
        json_schema_extra={
            "const": "delete_inline_comment",
            "ui:hidden": True,
            "x-category": "Comments",
            "x-is-trigger": False,
            "x-display-name": "Delete Inline Comment",
        },
        title="Delete Inline Comment",
    )
    comment_id: str = Field(..., title="Comment ID", description="The ID of the inline comment to delete")


class ConfluenceListBlogPostFooterCommentsConfig(BaseModel):
    """List footer comments on a blog post."""

    operation: Literal["list_blog_post_footer_comments"] = Field(
        "list_blog_post_footer_comments",
        json_schema_extra={
            "const": "list_blog_post_footer_comments",
            "ui:hidden": True,
            "x-category": "Comments",
            "x-is-trigger": False,
            "x-display-name": "List Blog Post Footer Comments",
        },
        title="List Blog Post Footer Comments",
    )
    blog_post_id: str = Field(..., title="Blog Post ID", description="The blog post whose footer comments to list")
    limit: Optional[str] = Field("25", title="Limit", description="Max number of comments to return (1-250)")


class ConfluenceListBlogPostInlineCommentsConfig(BaseModel):
    """List inline comments on a blog post."""

    operation: Literal["list_blog_post_inline_comments"] = Field(
        "list_blog_post_inline_comments",
        json_schema_extra={
            "const": "list_blog_post_inline_comments",
            "ui:hidden": True,
            "x-category": "Comments",
            "x-is-trigger": False,
            "x-display-name": "List Blog Post Inline Comments",
        },
        title="List Blog Post Inline Comments",
    )
    blog_post_id: str = Field(..., title="Blog Post ID", description="The blog post whose inline comments to list")
    limit: Optional[str] = Field("25", title="Limit", description="Max number of comments to return (1-250)")


# --- Attachment upload/delete ---


class ConfluenceUploadAttachmentConfig(BaseModel):
    """Upload a file as an attachment to a page (v1 multipart API)."""

    operation: Literal["upload_attachment"] = Field(
        "upload_attachment",
        json_schema_extra={
            "const": "upload_attachment",
            "ui:hidden": True,
            "x-category": "Attachments",
            "x-is-trigger": False,
            "x-display-name": "Upload Attachment",
        },
        title="Upload Attachment",
    )
    page_id: str = Field(..., title="Page ID", description="The page to attach the file to")
    filename: str = Field(..., title="Filename", description="Name of the file (e.g. report.pdf)")
    file_content_base64: str = Field(
        ...,
        title="File Content (base64)",
        description="Base64-encoded file content",
        json_schema_extra={"ui:widget": "textarea"},
    )
    mime_type: Optional[str] = Field(
        "application/octet-stream",
        title="MIME Type",
        description="Content type of the file (e.g. application/pdf, image/png)",
    )
    comment: Optional[str] = Field(
        None, title="Comment", description="Optional version comment for the attachment"
    )


class ConfluenceDeleteAttachmentConfig(BaseModel):
    """Delete an attachment."""

    operation: Literal["delete_attachment"] = Field(
        "delete_attachment",
        json_schema_extra={
            "const": "delete_attachment",
            "ui:hidden": True,
            "x-category": "Attachments",
            "x-is-trigger": False,
            "x-display-name": "Delete Attachment",
        },
        title="Delete Attachment",
    )
    attachment_id: str = Field(..., title="Attachment ID", description="The ID of the attachment to delete")


# --- Label remove ---


class ConfluenceRemoveLabelConfig(BaseModel):
    """Remove a label from content (page or blog post). Uses the v1 API."""

    operation: Literal["remove_label"] = Field(
        "remove_label",
        json_schema_extra={
            "const": "remove_label",
            "ui:hidden": True,
            "x-category": "Labels",
            "x-is-trigger": False,
            "x-display-name": "Remove Label",
        },
        title="Remove Label",
    )
    content_id: str = Field(..., title="Content ID", description="The page or blog post ID")
    label: str = Field(..., title="Label", description="The label name to remove")


# --- Content property update/delete ---


class ConfluenceUpdateContentPropertyConfig(BaseModel):
    """Update an existing content property on a page (requires the property ID and current version)."""

    operation: Literal["update_content_property"] = Field(
        "update_content_property",
        json_schema_extra={
            "const": "update_content_property",
            "ui:hidden": True,
            "x-category": "Properties",
            "x-is-trigger": False,
            "x-display-name": "Update Content Property",
        },
        title="Update Content Property",
    )
    page_id: str = Field(..., title="Page ID", description="The page that owns the property")
    property_id: str = Field(..., title="Property ID", description="The numeric property ID to update")
    property_key: str = Field(..., title="Property Key", description="The property key (name)")
    property_value: str = Field(
        ...,
        title="Property Value",
        description='The new property value as a JSON literal (e.g. "text", 42, {"a":1})',
        json_schema_extra={"ui:widget": "textarea"},
    )
    version_number: str = Field(
        ..., title="Version Number", description="Current version + 1"
    )


class ConfluenceDeleteContentPropertyConfig(BaseModel):
    """Delete a content property from a page."""

    operation: Literal["delete_content_property"] = Field(
        "delete_content_property",
        json_schema_extra={
            "const": "delete_content_property",
            "ui:hidden": True,
            "x-category": "Properties",
            "x-is-trigger": False,
            "x-display-name": "Delete Content Property",
        },
        title="Delete Content Property",
    )
    page_id: str = Field(..., title="Page ID", description="The page that owns the property")
    property_id: str = Field(..., title="Property ID", description="The numeric property ID to delete")


# --- Tasks ---


class ConfluenceListTasksConfig(BaseModel):
    """List inline tasks (checkboxes) across the site or filtered by space/page."""

    operation: Literal["list_tasks"] = Field(
        "list_tasks",
        json_schema_extra={
            "const": "list_tasks",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "List Tasks",
        },
        title="List Tasks",
    )
    page_id: Optional[str] = Field(None, title="Page ID", description="Filter to tasks on this page")
    space_id: Optional[str] = Field(
        None,
        title="Space",
        description="Filter to tasks in this space",
        json_schema_extra={
            "x-resource-type": "confluence_space",
            "x-dynamic-options": {
                "field_name": "space_id",
                "placeholder": "Select a space...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a space ID",
            }
        },
    )
    status: Optional[str] = Field(
        None,
        title="Status",
        description="Filter by task status",
        json_schema_extra={
            "enum": ["", "incomplete", "complete"],
            "enumNames": ["Any", "Incomplete", "Complete"],
            "x-enum-searchable": True,
        },
    )
    limit: Optional[str] = Field("25", title="Limit", description="Max number of tasks to return (1-250)")


class ConfluenceGetTaskConfig(BaseModel):
    """Get a single inline task by ID."""

    operation: Literal["get_task"] = Field(
        "get_task",
        json_schema_extra={
            "const": "get_task",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Get Task",
        },
        title="Get Task",
    )
    task_id: str = Field(..., title="Task ID", description="The numeric ID of the task")


class ConfluenceUpdateTaskConfig(BaseModel):
    """Update an inline task (e.g., mark as complete or incomplete)."""

    operation: Literal["update_task"] = Field(
        "update_task",
        json_schema_extra={
            "const": "update_task",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Update Task",
        },
        title="Update Task",
    )
    task_id: str = Field(..., title="Task ID", description="The numeric ID of the task to update")
    status: str = Field(
        "complete",
        title="Status",
        description="New task status",
        json_schema_extra={
            "enum": ["complete", "incomplete"],
            "enumNames": ["Complete", "Incomplete"],
            "x-enum-searchable": True,
        },
    )


# --- Spaces create ---


class ConfluenceCreateSpaceConfig(BaseModel):
    """Create a new Confluence space."""

    operation: Literal["create_space"] = Field(
        "create_space",
        json_schema_extra={
            "const": "create_space",
            "ui:hidden": True,
            "x-category": "Spaces",
            "x-is-trigger": False,
            "x-display-name": "Create Space",
            "x-creates-resource": True,
            "x-resource-type": "confluence_space",
            "x-resource-id-path": "data.id",
        },
        title="Create Space",
    )
    name: str = Field(..., title="Name", description="The space name")
    key: str = Field(
        ...,
        title="Key",
        description="Unique space key (alphanumeric, e.g. MYPROJECT)",
    )
    description: Optional[str] = Field(
        None,
        title="Description",
        description="Optional space description",
        json_schema_extra={"ui:widget": "textarea"},
    )


# --- Page ancestors ---


class ConfluenceGetPageAncestorsConfig(BaseModel):
    """Get the ancestor pages (breadcrumb path) of a page."""

    operation: Literal["get_page_ancestors"] = Field(
        "get_page_ancestors",
        json_schema_extra={
            "const": "get_page_ancestors",
            "ui:hidden": True,
            "x-category": "Pages",
            "x-is-trigger": False,
            "x-display-name": "Get Page Ancestors",
        },
        title="Get Page Ancestors",
    )
    page_id: str = Field(..., title="Page ID", description="The page whose ancestor chain to retrieve")
    limit: Optional[str] = Field("25", title="Limit", description="Max number of ancestors to return (1-250)")


# ============================================================================
# Discriminated Union
# ============================================================================


ConfluenceConfig = Annotated[
    Union[
        ConfluenceListPagesConfig,
        ConfluenceGetPageConfig,
        ConfluenceCreatePageConfig,
        ConfluenceUpdatePageConfig,
        ConfluenceDeletePageConfig,
        ConfluenceListPagesInSpaceConfig,
        ConfluenceListChildPagesConfig,
        ConfluenceGetPageVersionsConfig,
        ConfluenceGetPageAncestorsConfig,
        ConfluenceListBlogPostsConfig,
        ConfluenceGetBlogPostConfig,
        ConfluenceCreateBlogPostConfig,
        ConfluenceUpdateBlogPostConfig,
        ConfluenceDeleteBlogPostConfig,
        ConfluenceListSpacesConfig,
        ConfluenceGetSpaceConfig,
        ConfluenceCreateSpaceConfig,
        ConfluenceListSpaceLabelsConfig,
        ConfluenceListFooterCommentsConfig,
        ConfluenceCreateFooterCommentConfig,
        ConfluenceUpdateFooterCommentConfig,
        ConfluenceDeleteFooterCommentConfig,
        ConfluenceListBlogPostFooterCommentsConfig,
        ConfluenceListInlineCommentsConfig,
        ConfluenceCreateInlineCommentConfig,
        ConfluenceUpdateInlineCommentConfig,
        ConfluenceDeleteInlineCommentConfig,
        ConfluenceListBlogPostInlineCommentsConfig,
        ConfluenceListAttachmentsConfig,
        ConfluenceGetAttachmentConfig,
        ConfluenceUploadAttachmentConfig,
        ConfluenceDeleteAttachmentConfig,
        ConfluenceListPageLabelsConfig,
        ConfluenceAddLabelConfig,
        ConfluenceRemoveLabelConfig,
        ConfluenceListContentPropertiesConfig,
        ConfluenceCreateContentPropertyConfig,
        ConfluenceUpdateContentPropertyConfig,
        ConfluenceDeleteContentPropertyConfig,
        ConfluenceListTasksConfig,
        ConfluenceGetTaskConfig,
        ConfluenceUpdateTaskConfig,
        ConfluenceSearchConfig,
        ConfluenceSearchContentConfig,
        ConfluenceGetCurrentUserConfig,
        ConfluenceOnNewContentConfig,
    ],
    Discriminator("operation"),
]


class ConfluenceNodeConfig(NodeConfig[ConfluenceConfig, ConfluenceCredential]):
    """Full configuration for the Confluence node including credentials."""

    pass


# ============================================================================
# Helpers
# ============================================================================


def _comma_list(value: Optional[str]) -> Optional[List[str]]:
    if not value:
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return parts or None


def _coerce_property_value(raw: str) -> Any:
    """Parse a content-property value string as JSON, falling back to the raw string."""
    import json

    try:
        return json.loads(raw)
    except Exception:
        return raw


def _is_oauth_credential(credential: Any) -> bool:
    return isinstance(credential, ConfluenceOAuthCredential)


def _wiki_base(credential: ConfluenceCredential) -> str:
    """Return the Confluence ``/wiki`` base URL for the given credential.

    OAuth calls route through api.atlassian.com/ex/confluence/{cloudid}; Basic
    auth calls go straight to the site's atlassian.net domain.
    """
    if isinstance(credential, ConfluenceOAuthCredential):
        return f"https://api.atlassian.com/ex/confluence/{credential.cloud_id}/wiki"
    tenant = normalize_provider_subdomain(
        credential.domain,
        "atlassian.net",
        field_name="Confluence domain",
    )
    return f"https://{tenant}.atlassian.net/wiki"


def _auth_headers(credential: ConfluenceCredential) -> Dict[str, str]:
    """Build auth + content headers based on the credential type."""
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if isinstance(credential, ConfluenceOAuthCredential):
        headers["Authorization"] = f"Bearer {credential.access_token}"
    else:
        auth = f"{credential.email}:{credential.api_token}"
        headers["Authorization"] = f"Basic {base64.b64encode(auth.encode()).decode()}"
    return headers


async def _confluence_request(
    credential: ConfluenceCredential,
    method: str,
    endpoint: str,
    *,
    api: str = "v2",
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Union[Dict[str, Any], List[Any]]] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated Confluence request and return a structured result.

    ``api`` selects the surface: ``"v2"`` (``/wiki/api/v2``) or ``"v1"``
    (``/wiki/rest/api``) — CQL search, attachment upload, add-label and
    current-user still live on v1.
    """
    base = _wiki_base(credential)
    prefix = "/api/v2" if api == "v2" else "/rest/api"
    url = f"{base}{prefix}{endpoint}"
    headers = _auth_headers(credential)

    if isinstance(json_body, dict):
        json_body = {k: v for k, v in json_body.items() if v is not None}
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}

    start = time.time()
    async with guarded_async_client(timeout=30.0) as client:
        try:
            response = await client.request(
                method=method, url=url, headers=headers, params=params, json=json_body
            )
            api_ms = round((time.time() - start) * 1000, 2)
            if response.status_code >= 400:
                try:
                    err = response.json()
                    errors = err.get("errors") if isinstance(err, dict) else None
                    if isinstance(errors, list) and errors:
                        message = errors[0].get("title") or errors[0].get("detail") or str(errors[0])
                    else:
                        message = err.get("message") if isinstance(err, dict) else str(err)
                    if not message:
                        message = response.text
                except Exception:
                    message = response.text
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[ConfluenceNode] API error ({action_name}): {message}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": message,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }
            if response.status_code == 204:
                data: Any = {"success": True}
            else:
                try:
                    data = response.json()
                except Exception:
                    data = {"raw": response.text}
            return {
                "status": "success",
                "action": action_name,
                "data": data,
                "status_code": response.status_code,
                "timing_ms": {"api_request": api_ms},
            }
        except httpx.TimeoutException:
            return {
                "status": "error",
                "action": action_name,
                "error": "Request timed out",
                "status_code": 408,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }
        except Exception as e:
            msg = str(e).encode("ascii", errors="replace").decode("ascii")
            logger.error(f"[ConfluenceNode] Request failed ({action_name}): {msg}")
            return {
                "status": "error",
                "action": action_name,
                "error": msg,
                "status_code": 500,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }


def _body_payload(body: Optional[str], representation: Optional[str]) -> Optional[Dict[str, Any]]:
    """Build a v2 body object {representation, value} or None when no body given."""
    if body is None:
        return None
    return {"representation": representation or DEFAULT_BODY_FORMAT, "value": body}


def _safe_int(value: Any, field_name: str) -> int:
    """Coerce a value to int, raising a user-facing ValueError on bad input."""
    try:
        return int(value)
    except (ValueError, TypeError):
        raise ValueError(f"'{field_name}' must be a whole number, got {value!r}")


# ============================================================================
# Node Implementation
# ============================================================================


class ConfluenceNode(WorkflowNode):
    """Confluence Cloud REST API automation node."""

    edit_examples = [
        "Create a Confluence page in the DEV space with release notes",
        "Search Confluence for pages mentioning 'onboarding'",
        "Add a footer comment to a page when a ticket is closed",
        "List all pages in the Engineering space",
        "Update a page body and bump its version",
    ]

    scope_registry = CONFLUENCE_SCOPES
    connection_evidence = ConnectionEvidence(
        field="space_id",
        noun="spaces",
    )

    @classmethod
    def get_config_model(cls):
        return ConfluenceNodeConfig

    @classmethod
    def resolve_trigger_payload(
        cls, payload: Dict[str, Any], config: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """The Confluence trigger is poll-based: the webhook is a wake-up signal,
        not data. Return None so execute() runs and actually polls the API."""
        if config.get("operation") == "on_new_content":
            return None
        return payload

    def trigger_produced_no_event(self, output: Dict[str, Any]) -> bool:
        """A scheduled poll that found no new content → skip downstream. Dedup is
        via the node-state break-cursor, so emptiness is read off ``new_count``.
        See ``WorkflowNode`` for the seam."""
        return (
            isinstance(output, dict)
            and output.get("operation") == "on_new_content"
            and not output.get("new_count")
        )

    @classmethod
    async def load_field_value(
        cls,
        field_name: str,
        user_id: str,
        workflow_id: uuid_module.UUID,
        node_id: str,
        pool,
        context: Optional[Dict[str, Any]] = None,
        credential_ids: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Provision the webhook + polling schedule for the trigger operation."""
        from utils.webhook_manager import WebhookManager
        from utils.cron_scheduler_client import (
            create_schedule,
            update_schedule,
            is_cron_scheduler_enabled,
        )

        if field_name != "webhook_url":
            return {"value": None}

        webhook_data = await WebhookManager.get_or_create_webhook(
            pool=pool,
            user_id=user_id,
            workflow_id=workflow_id,
            node_id=node_id,
        )
        webhook_id = webhook_data.get("webhook_id")
        webhook_url = webhook_data.get("webhook_url")

        schedule = {"frequency": "minutes", "interval": 5}
        if context and context.get("schedule"):
            schedule = context["schedule"]
        cron_expression = schedule_to_cron(schedule)
        interval_ms = schedule_to_interval_ms(schedule)
        logger.info(
            f"[ConfluenceNode] Trigger schedule {schedule} -> cron: {cron_expression}"
        )

        existing_schedule_id = context.get("schedule_id") if context else None
        schedule_id = existing_schedule_id
        next_run = None

        if is_cron_scheduler_enabled() and webhook_url:
            if existing_schedule_id:
                result = await update_schedule(
                    schedule_id=existing_schedule_id,
                    cron_expression=cron_expression,
                )
                if result.get("success"):
                    next_run = result.get("next_run")
                elif "error" in result:
                    logger.warning(f"Failed to update schedule: {result['error']}")
                    existing_schedule_id = None

            if not existing_schedule_id:
                result = await create_schedule(
                    user_id=user_id,
                    workflow_id=str(workflow_id),
                    node_id=node_id,
                    cron_expression=cron_expression,
                    webhook_url=webhook_url,
                    payload={"source": "confluence_trigger", "node_id": node_id},
                )
                if "id" in result:
                    schedule_id = result["id"]
                    next_run = result.get("next_run")
                elif "error" in result:
                    logger.warning(f"Failed to create schedule: {result['error']}")

        return {
            "values": {
                "webhook_id": webhook_id,
                "webhook_url": webhook_url,
                "schedule_id": schedule_id,
                "next_run": next_run,
                "interval_ms": interval_ms,
                "is_active": True,
            }
        }

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        """Refresh an expiring OAuth token at credential load (dropdowns / triggers)."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.atlassian_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token, provider="atlassian",
        )

    # ------------------------------------------------------------------
    # Dynamic options (spaces)
    # ------------------------------------------------------------------
    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        if field_name != "space_id":
            return {"options": []}
        if not credential_data:
            return {"options": []}

        credential = cls._credential_from_dict(credential_data)
        result = await _confluence_request(
            credential, "GET", "/spaces", params={"limit": "100"}, action_name="list_spaces"
        )
        if result.get("status") != "success":
            return {"options": []}
        data = result.get("data") or {}
        spaces = data.get("results", []) if isinstance(data, dict) else []
        options = []
        for sp in spaces:
            if not isinstance(sp, dict):
                continue
            sid = sp.get("id")
            key = sp.get("key")
            name = sp.get("name") or key or f"Space {sid}"
            label = f"{name} ({key})" if key else str(name)
            value = str(sid) if sid is not None else None
            if value is not None:
                options.append({"label": label, "value": value})
        # Apply search filter if provided
        if search:
            s = search.lower()
            options = [o for o in options if s in o["label"].lower() or s in o["value"].lower()]
        return {"options": options}

    @staticmethod
    def _credential_from_dict(cred_dict: Dict[str, Any]) -> ConfluenceCredential:
        """Rehydrate a decrypted credential dict into the right Pydantic model."""
        if cred_dict.get("credential_type") == "confluence_oauth" or "access_token" in cred_dict:
            return ConfluenceOAuthCredential(**cred_dict)
        return ConfluenceApiTokenCredential(**cred_dict)

    # ------------------------------------------------------------------
    # OAuth token refresh
    # ------------------------------------------------------------------
    async def _ensure_fresh_token(
        self, credentials: ConfluenceOAuthCredential
    ) -> ConfluenceOAuthCredential:
        """Refresh the OAuth access token if expired, persisting the rotation."""
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.atlassian_oauth import refresh_access_token
        
        credential_id = (self.node_data or {}).get("credential_id")
        cred_dict = credentials.model_dump()
        await ensure_fresh_oauth_token(
            credential_id=credential_id,
            user_id=self.user_id,
            credential=cred_dict,
            refresh=refresh_access_token,
            provider="atlassian",
        )
        return ConfluenceOAuthCredential(
            access_token=cred_dict["access_token"],
            refresh_token=cred_dict.get("refresh_token") or credentials.refresh_token,
            expires_at=cred_dict.get("expires_at") or credentials.expires_at,
            cloud_id=credentials.cloud_id,
            email=credentials.email,
            site_name=credentials.site_name,
            site_url=cred_dict.get("site_url") or credentials.site_url,
            scope=cred_dict.get("scope") or credentials.scope,
        )

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, ConfluenceNodeConfig):
            raise ValueError("Valid configuration is required")

        credentials = config.credentials
        if not credentials:
            raise ValueError(
                "Credentials are required. Connect a Confluence account in the credentials tab."
            )

        if isinstance(credentials, ConfluenceOAuthCredential):
            credentials = await self._ensure_fresh_token(credentials)

        op = config.config
        handlers = {
            "list_pages": self._list_pages,
            "get_page": self._get_page,
            "create_page": self._create_page,
            "update_page": self._update_page,
            "delete_page": self._delete_page,
            "list_pages_in_space": self._list_pages_in_space,
            "list_child_pages": self._list_child_pages,
            "get_page_versions": self._get_page_versions,
            "get_page_ancestors": self._get_page_ancestors,
            "list_blog_posts": self._list_blog_posts,
            "get_blog_post": self._get_blog_post,
            "create_blog_post": self._create_blog_post,
            "update_blog_post": self._update_blog_post,
            "delete_blog_post": self._delete_blog_post,
            "list_spaces": self._list_spaces,
            "get_space": self._get_space,
            "create_space": self._create_space,
            "list_space_labels": self._list_space_labels,
            "list_footer_comments": self._list_footer_comments,
            "create_footer_comment": self._create_footer_comment,
            "update_footer_comment": self._update_footer_comment,
            "delete_footer_comment": self._delete_footer_comment,
            "list_blog_post_footer_comments": self._list_blog_post_footer_comments,
            "list_inline_comments": self._list_inline_comments,
            "create_inline_comment": self._create_inline_comment,
            "update_inline_comment": self._update_inline_comment,
            "delete_inline_comment": self._delete_inline_comment,
            "list_blog_post_inline_comments": self._list_blog_post_inline_comments,
            "list_attachments": self._list_attachments,
            "get_attachment": self._get_attachment,
            "upload_attachment": self._upload_attachment,
            "delete_attachment": self._delete_attachment,
            "list_page_labels": self._list_page_labels,
            "add_label": self._add_label,
            "remove_label": self._remove_label,
            "list_content_properties": self._list_content_properties,
            "create_content_property": self._create_content_property,
            "update_content_property": self._update_content_property,
            "delete_content_property": self._delete_content_property,
            "list_tasks": self._list_tasks,
            "get_task": self._get_task,
            "update_task": self._update_task,
            "search": self._search,
            "search_content": self._search_content,
            "get_current_user": self._get_current_user,
            "on_new_content": self._poll_new_content,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        try:
            result = await handler(op, credentials)
        except ValueError as e:
            msg = str(e).encode("ascii", errors="replace").decode("ascii")
            logger.error(f"[ConfluenceNode] Invalid input ({op.operation}): {msg}")
            return {
                "status": "error",
                "action": op.operation,
                "error": msg,
                "status_code": 400,
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # Page handlers
    # ------------------------------------------------------------------
    async def _list_pages(self, c: ConfluenceListPagesConfig, cred) -> Dict[str, Any]:
        params = {
            "space-id": c.space_id,
            "status": c.status or None,
            "title": c.title,
            "limit": c.limit,
        }
        return await _confluence_request(
            cred, "GET", "/pages", params=params, action_name="list_pages"
        )

    async def _get_page(self, c: ConfluenceGetPageConfig, cred) -> Dict[str, Any]:
        params = {"body-format": c.body_format or None}
        return await _confluence_request(
            cred, "GET", f"/pages/{c.page_id}", params=params, action_name="get_page"
        )

    async def _create_page(self, c: ConfluenceCreatePageConfig, cred) -> Dict[str, Any]:
        body = {
            "spaceId": c.space_id,
            "title": c.title,
            "parentId": c.parent_id,
            "status": c.status or "current",
            "body": _body_payload(c.body, c.representation),
        }
        return await _confluence_request(
            cred, "POST", "/pages", json_body=body, action_name="create_page"
        )

    async def _update_page(self, c: ConfluenceUpdatePageConfig, cred) -> Dict[str, Any]:
        body = {
            "id": c.page_id,
            "status": c.status or "current",
            "title": c.title,
            "body": _body_payload(c.body, c.representation),
            "version": {
                "number": _safe_int(c.version_number, "version_number"),
                "message": c.version_message,
            },
        }
        return await _confluence_request(
            cred, "PUT", f"/pages/{c.page_id}", json_body=body, action_name="update_page"
        )

    async def _delete_page(self, c: ConfluenceDeletePageConfig, cred) -> Dict[str, Any]:
        params = {"purge": "true"} if c.purge == "true" else None
        return await _confluence_request(
            cred, "DELETE", f"/pages/{c.page_id}", params=params, action_name="delete_page"
        )

    async def _list_pages_in_space(
        self, c: ConfluenceListPagesInSpaceConfig, cred
    ) -> Dict[str, Any]:
        params = {"status": c.status or None, "limit": c.limit}
        return await _confluence_request(
            cred, "GET", f"/spaces/{c.space_id}/pages", params=params,
            action_name="list_pages_in_space",
        )

    async def _list_child_pages(
        self, c: ConfluenceListChildPagesConfig, cred
    ) -> Dict[str, Any]:
        return await _confluence_request(
            cred, "GET", f"/pages/{c.page_id}/children", params={"limit": c.limit},
            action_name="list_child_pages",
        )

    async def _get_page_versions(
        self, c: ConfluenceGetPageVersionsConfig, cred
    ) -> Dict[str, Any]:
        return await _confluence_request(
            cred, "GET", f"/pages/{c.page_id}/versions", params={"limit": c.limit},
            action_name="get_page_versions",
        )

    # ------------------------------------------------------------------
    # Blog post handlers
    # ------------------------------------------------------------------
    async def _list_blog_posts(self, c: ConfluenceListBlogPostsConfig, cred) -> Dict[str, Any]:
        params = {"space-id": c.space_id, "status": c.status or None, "limit": c.limit}
        return await _confluence_request(
            cred, "GET", "/blogposts", params=params, action_name="list_blog_posts"
        )

    async def _get_blog_post(self, c: ConfluenceGetBlogPostConfig, cred) -> Dict[str, Any]:
        params = {"body-format": c.body_format or None}
        return await _confluence_request(
            cred, "GET", f"/blogposts/{c.blog_post_id}", params=params,
            action_name="get_blog_post",
        )

    async def _create_blog_post(self, c: ConfluenceCreateBlogPostConfig, cred) -> Dict[str, Any]:
        body = {
            "spaceId": c.space_id,
            "title": c.title,
            "status": c.status or "current",
            "body": _body_payload(c.body, c.representation),
        }
        return await _confluence_request(
            cred, "POST", "/blogposts", json_body=body, action_name="create_blog_post"
        )

    async def _update_blog_post(self, c: ConfluenceUpdateBlogPostConfig, cred) -> Dict[str, Any]:
        body = {
            "id": c.blog_post_id,
            "status": c.status or "current",
            "title": c.title,
            "body": _body_payload(c.body, c.representation),
            "version": {"number": _safe_int(c.version_number, "version_number")},
        }
        return await _confluence_request(
            cred, "PUT", f"/blogposts/{c.blog_post_id}", json_body=body,
            action_name="update_blog_post",
        )

    async def _delete_blog_post(self, c: ConfluenceDeleteBlogPostConfig, cred) -> Dict[str, Any]:
        params = {"purge": "true"} if c.purge == "true" else None
        return await _confluence_request(
            cred, "DELETE", f"/blogposts/{c.blog_post_id}", params=params,
            action_name="delete_blog_post",
        )

    # ------------------------------------------------------------------
    # Space handlers
    # ------------------------------------------------------------------
    async def _list_spaces(self, c: ConfluenceListSpacesConfig, cred) -> Dict[str, Any]:
        params = {
            "keys": _comma_list(c.keys),
            "type": c.type or None,
            "status": c.status or None,
            "limit": c.limit,
        }
        return await _confluence_request(
            cred, "GET", "/spaces", params=params, action_name="list_spaces"
        )

    async def _get_space(self, c: ConfluenceGetSpaceConfig, cred) -> Dict[str, Any]:
        return await _confluence_request(
            cred, "GET", f"/spaces/{c.space_id}", action_name="get_space"
        )

    async def _list_space_labels(self, c: ConfluenceListSpaceLabelsConfig, cred) -> Dict[str, Any]:
        return await _confluence_request(
            cred, "GET", f"/spaces/{c.space_id}/labels", params={"limit": c.limit},
            action_name="list_space_labels",
        )

    # ------------------------------------------------------------------
    # Comment handlers
    # ------------------------------------------------------------------
    async def _list_footer_comments(
        self, c: ConfluenceListFooterCommentsConfig, cred
    ) -> Dict[str, Any]:
        return await _confluence_request(
            cred, "GET", f"/pages/{c.page_id}/footer-comments", params={"limit": c.limit},
            action_name="list_footer_comments",
        )

    async def _create_footer_comment(
        self, c: ConfluenceCreateFooterCommentConfig, cred
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {"body": _body_payload(c.body, c.representation)}
        if c.page_id:
            body["pageId"] = c.page_id
        if c.blog_post_id:
            body["blogPostId"] = c.blog_post_id
        return await _confluence_request(
            cred, "POST", "/footer-comments", json_body=body,
            action_name="create_footer_comment",
        )

    async def _list_inline_comments(
        self, c: ConfluenceListInlineCommentsConfig, cred
    ) -> Dict[str, Any]:
        return await _confluence_request(
            cred, "GET", f"/pages/{c.page_id}/inline-comments", params={"limit": c.limit},
            action_name="list_inline_comments",
        )

    async def _create_inline_comment(
        self, c: ConfluenceCreateInlineCommentConfig, cred
    ) -> Dict[str, Any]:
        # Atlassian REQUIRES textSelectionMatchCount + textSelectionMatchIndex.
        # Fetch the target body, count occurrences of the anchor text for the
        # match count, and let the caller pick which occurrence via match_index.
        match_index = _safe_int(c.match_index or "0", "match_index")
        if c.blog_post_id:
            target = await _confluence_request(
                cred, "GET", f"/blogposts/{c.blog_post_id}",
                params={"body-format": "storage"},
                action_name="create_inline_comment",
            )
        else:
            target = await _confluence_request(
                cred, "GET", f"/pages/{c.page_id}",
                params={"body-format": "storage"},
                action_name="create_inline_comment",
            )
        if target.get("status") != "success":
            return target

        body_value = (
            ((((target.get("data") or {}).get("body") or {}).get("storage") or {}).get("value"))
            or ""
        )
        match_count = body_value.count(c.selection_text)
        if match_count == 0:
            return {
                "status": "error",
                "action": "create_inline_comment",
                "error": (
                    f"Highlighted text {c.selection_text!r} was not found in the target "
                    "body; an inline comment must anchor to text that exists on the page."
                ),
                "status_code": 400,
            }
        if match_index < 0 or match_index >= match_count:
            return {
                "status": "error",
                "action": "create_inline_comment",
                "error": (
                    f"'match_index' {match_index} is out of range; the highlighted text "
                    f"appears {match_count} time(s) (valid indices 0-{match_count - 1})."
                ),
                "status_code": 400,
            }

        body: Dict[str, Any] = {
            "body": _body_payload(c.body, c.representation),
            "inlineCommentProperties": {
                "textSelection": c.selection_text,
                "textSelectionMatchCount": match_count,
                "textSelectionMatchIndex": match_index,
            },
        }
        if c.page_id:
            body["pageId"] = c.page_id
        if c.blog_post_id:
            body["blogPostId"] = c.blog_post_id
        return await _confluence_request(
            cred, "POST", "/inline-comments", json_body=body,
            action_name="create_inline_comment",
        )

    # ------------------------------------------------------------------
    # Attachment handlers
    # ------------------------------------------------------------------
    async def _list_attachments(self, c: ConfluenceListAttachmentsConfig, cred) -> Dict[str, Any]:
        return await _confluence_request(
            cred, "GET", f"/pages/{c.page_id}/attachments", params={"limit": c.limit},
            action_name="list_attachments",
        )

    async def _get_attachment(self, c: ConfluenceGetAttachmentConfig, cred) -> Dict[str, Any]:
        return await _confluence_request(
            cred, "GET", f"/attachments/{c.attachment_id}", action_name="get_attachment"
        )

    # ------------------------------------------------------------------
    # Label handlers
    # ------------------------------------------------------------------
    async def _list_page_labels(self, c: ConfluenceListPageLabelsConfig, cred) -> Dict[str, Any]:
        return await _confluence_request(
            cred, "GET", f"/pages/{c.page_id}/labels", params={"limit": c.limit},
            action_name="list_page_labels",
        )

    async def _add_label(self, c: ConfluenceAddLabelConfig, cred) -> Dict[str, Any]:
        # Add-label only exists on the v1 API.
        body = [{"prefix": c.prefix or "global", "name": c.label}]
        return await _confluence_request(
            cred, "POST", f"/content/{c.content_id}/label", api="v1",
            json_body=body, action_name="add_label",
        )

    # ------------------------------------------------------------------
    # Content property handlers
    # ------------------------------------------------------------------
    async def _list_content_properties(
        self, c: ConfluenceListContentPropertiesConfig, cred
    ) -> Dict[str, Any]:
        return await _confluence_request(
            cred, "GET", f"/pages/{c.page_id}/properties", params={"limit": c.limit},
            action_name="list_content_properties",
        )

    async def _create_content_property(
        self, c: ConfluenceCreateContentPropertyConfig, cred
    ) -> Dict[str, Any]:
        body = {"key": c.property_key, "value": _coerce_property_value(c.property_value)}
        return await _confluence_request(
            cred, "POST", f"/pages/{c.page_id}/properties", json_body=body,
            action_name="create_content_property",
        )

    # ------------------------------------------------------------------
    # Search & user handlers (v1)
    # ------------------------------------------------------------------
    async def _search(self, c: ConfluenceSearchConfig, cred) -> Dict[str, Any]:
        params = {"cql": c.cql, "limit": c.limit}
        return await _confluence_request(
            cred, "GET", "/search", api="v1", params=params, action_name="search"
        )

    async def _search_content(self, c: ConfluenceSearchContentConfig, cred) -> Dict[str, Any]:
        params = {"cql": c.cql, "limit": c.limit}
        return await _confluence_request(
            cred, "GET", "/content/search", api="v1", params=params,
            action_name="search_content",
        )

    async def _get_current_user(self, c: ConfluenceGetCurrentUserConfig, cred) -> Dict[str, Any]:
        return await _confluence_request(
            cred, "GET", "/user/current", api="v1", action_name="get_current_user"
        )

    # ------------------------------------------------------------------
    # Trigger handler (poll-based)
    # ------------------------------------------------------------------
    async def _poll_new_content(
        self, c: ConfluenceOnNewContentConfig, cred
    ) -> Dict[str, Any]:
        """Poll v2 pages/blogposts (sorted by created desc) for new content.

        Uses the v2 REST endpoints because the v1 CQL search index has significant
        lag (60+ seconds) for newly created content, making it unreliable as a
        trigger source.  The v2 endpoints return newly created items immediately.
        """
        import asyncio as _asyncio

        limit = c.max_results or "25"
        want_pages = c.content_type in ("page", "all")
        want_blogs = c.content_type in ("blogpost", "all")

        space_params: Dict[str, str] = {"sort": "-created-date", "limit": limit}
        if c.space_id:
            space_params["space-id"] = c.space_id

        # Fetch pages and/or blog posts concurrently.
        fetch_tasks = []
        if want_pages:
            fetch_tasks.append(_confluence_request(
                cred, "GET", "/pages", params=space_params, action_name="on_new_content"
            ))
        if want_blogs:
            fetch_tasks.append(_confluence_request(
                cred, "GET", "/blogposts", params=space_params, action_name="on_new_content"
            ))

        if not fetch_tasks:
            fetch_tasks.append(_confluence_request(
                cred, "GET", "/pages", params=space_params, action_name="on_new_content"
            ))

        raw_results = await _asyncio.gather(*fetch_tasks)

        # Merge and re-sort by id descending (proxy for creation order since IDs
        # are monotonically increasing within an Atlassian Cloud instance).
        all_items: List[Dict[str, Any]] = []
        for r in raw_results:
            if r.get("status") == "success":
                all_items.extend((r.get("data") or {}).get("results", []))
            else:
                return {**r, "operation": "on_new_content"}

        all_items.sort(key=lambda x: int(x.get("id", 0)), reverse=True)

        def _item_id(item: Dict[str, Any]) -> Optional[str]:
            v = item.get("id")
            return str(v) if v is not None else None

        def mutator(state):
            # The break-cursor lives in NODE STATE — config isn't persisted across
            # poll runs, so a config-held cursor stayed None forever and the
            # trigger baselined (emitted nothing) on every tick, never firing.
            is_first_poll = "last_seen_id" not in state
            last_seen_id = state.get("last_seen_id")

            fresh: List[Dict[str, Any]] = []
            for item in all_items:
                cid = _item_id(item)
                if last_seen_id is not None and cid == last_seen_id:
                    break
                fresh.append(item)

            newest_id = _item_id(all_items[0]) if all_items else last_seen_id
            if is_first_poll:
                if newest_id is None:
                    return None, ([], None, True)  # nothing to baseline yet
                # Baseline: record the newest id, emit nothing.
                return {"last_seen_id": newest_id}, ([], newest_id, True)
            if newest_id != last_seen_id:
                return {"last_seen_id": newest_id}, (fresh, newest_id, False)
            return None, (fresh, newest_id, False)  # nothing new → no write

        emitted, newest_id, first_poll = await self._update_node_state(
            mutator, skip_result=([], None, False)
        )

        return {
            "status": "success",
            "action": "on_new_content",
            "operation": "on_new_content",
            "content_type": c.content_type,
            "space_id": c.space_id,
            "new_count": len(emitted),
            "items": emitted,
            "last_seen_id": newest_id,
            "last_polled_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "first_poll": first_poll,
        }

    # ------------------------------------------------------------------
    # New page handlers
    # ------------------------------------------------------------------
    async def _get_page_ancestors(
        self, c: ConfluenceGetPageAncestorsConfig, cred
    ) -> Dict[str, Any]:
        # The dedicated /pages/{id}/ancestors endpoint requires a scope
        # (read:hierarchical-content:confluence) that Atlassian's app console
        # may not surface. Walk the parentId chain via /pages/{id} instead —
        # those calls only need read:page:confluence which is already granted.
        import time as _time
        limit = min(_safe_int(c.limit or "25", "limit"), 50)
        ancestors: list = []
        current_id: Optional[str] = c.page_id
        visited: set = set()
        start = _time.time()

        while current_id and len(ancestors) < limit:
            if current_id in visited:
                break
            visited.add(current_id)
            result = await _confluence_request(
                cred, "GET", f"/pages/{current_id}", action_name="get_page_ancestors"
            )
            if result.get("status") != "success":
                if ancestors:
                    break
                return result
            page = result.get("data") or {}
            parent_id = page.get("parentId")
            if not parent_id:
                break
            ancestors.append({
                "id": parent_id,
                "type": page.get("parentType", "page"),
            })
            current_id = parent_id

        ancestors.reverse()  # root first, matching Confluence convention
        return {
            "status": "success",
            "action": "get_page_ancestors",
            "data": {"results": ancestors},
            "timing_ms": {"total": round((_time.time() - start) * 1000, 2)},
        }

    # ------------------------------------------------------------------
    # New comment handlers
    # ------------------------------------------------------------------
    async def _update_footer_comment(
        self, c: ConfluenceUpdateFooterCommentConfig, cred
    ) -> Dict[str, Any]:
        body = {
            "version": {"number": _safe_int(c.version_number, "version_number")},
            "body": _body_payload(c.body, c.representation),
        }
        return await _confluence_request(
            cred, "PUT", f"/footer-comments/{c.comment_id}", json_body=body,
            action_name="update_footer_comment",
        )

    async def _delete_footer_comment(
        self, c: ConfluenceDeleteFooterCommentConfig, cred
    ) -> Dict[str, Any]:
        return await _confluence_request(
            cred, "DELETE", f"/footer-comments/{c.comment_id}",
            action_name="delete_footer_comment",
        )

    async def _update_inline_comment(
        self, c: ConfluenceUpdateInlineCommentConfig, cred
    ) -> Dict[str, Any]:
        body = {
            "version": {"number": _safe_int(c.version_number, "version_number")},
            "body": _body_payload(c.body, c.representation),
        }
        return await _confluence_request(
            cred, "PUT", f"/inline-comments/{c.comment_id}", json_body=body,
            action_name="update_inline_comment",
        )

    async def _delete_inline_comment(
        self, c: ConfluenceDeleteInlineCommentConfig, cred
    ) -> Dict[str, Any]:
        return await _confluence_request(
            cred, "DELETE", f"/inline-comments/{c.comment_id}",
            action_name="delete_inline_comment",
        )

    async def _list_blog_post_footer_comments(
        self, c: ConfluenceListBlogPostFooterCommentsConfig, cred
    ) -> Dict[str, Any]:
        return await _confluence_request(
            cred, "GET", f"/blogposts/{c.blog_post_id}/footer-comments",
            params={"limit": c.limit},
            action_name="list_blog_post_footer_comments",
        )

    async def _list_blog_post_inline_comments(
        self, c: ConfluenceListBlogPostInlineCommentsConfig, cred
    ) -> Dict[str, Any]:
        return await _confluence_request(
            cred, "GET", f"/blogposts/{c.blog_post_id}/inline-comments",
            params={"limit": c.limit},
            action_name="list_blog_post_inline_comments",
        )

    # ------------------------------------------------------------------
    # New attachment handlers
    # ------------------------------------------------------------------
    async def _upload_attachment(
        self, c: ConfluenceUploadAttachmentConfig, cred
    ) -> Dict[str, Any]:
        """Upload a file attachment to a page via the v1 multipart API."""
        import base64 as _b64
        base = _wiki_base(cred)
        url = f"{base}/rest/api/content/{c.page_id}/child/attachment"
        headers = _auth_headers(cred)
        # Required to bypass Confluence's XSRF token check for REST uploads.
        headers["X-Atlassian-Token"] = "no-check"
        # Remove Content-Type so httpx sets multipart boundary automatically.
        headers.pop("Content-Type", None)

        try:
            file_bytes = _b64.b64decode(c.file_content_base64)
        except Exception as e:
            return {
                "status": "error",
                "action": "upload_attachment",
                "error": f"Invalid base64 content: {e}",
                "status_code": 400,
                "timing_ms": {"api_request": 0},
            }

        mime_type = c.mime_type or "application/octet-stream"
        files = {"file": (c.filename, file_bytes, mime_type)}
        data = {}
        if c.comment:
            data["comment"] = c.comment

        start = time.time()
        async with guarded_async_client(timeout=60.0) as client:
            try:
                response = await client.post(url, headers=headers, files=files, data=data)
                api_ms = round((time.time() - start) * 1000, 2)
                if response.status_code >= 400:
                    try:
                        err = response.json()
                        message = err.get("message") or response.text
                    except Exception:
                        message = response.text
                    return {
                        "status": "error",
                        "action": "upload_attachment",
                        "error": str(message),
                        "status_code": response.status_code,
                        "timing_ms": {"api_request": api_ms},
                    }
                try:
                    data_resp = response.json()
                except Exception:
                    data_resp = {"raw": response.text}
                return {
                    "status": "success",
                    "action": "upload_attachment",
                    "data": data_resp,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }
            except httpx.TimeoutException:
                return {
                    "status": "error",
                    "action": "upload_attachment",
                    "error": "Request timed out",
                    "status_code": 408,
                    "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
                }
            except Exception as e:
                msg = str(e).encode("ascii", errors="replace").decode("ascii")
                return {
                    "status": "error",
                    "action": "upload_attachment",
                    "error": msg,
                    "status_code": 500,
                    "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
                }

    async def _delete_attachment(
        self, c: ConfluenceDeleteAttachmentConfig, cred
    ) -> Dict[str, Any]:
        return await _confluence_request(
            cred, "DELETE", f"/attachments/{c.attachment_id}",
            action_name="delete_attachment",
        )

    # ------------------------------------------------------------------
    # New label handlers
    # ------------------------------------------------------------------
    async def _remove_label(self, c: ConfluenceRemoveLabelConfig, cred) -> Dict[str, Any]:
        params = {"name": c.label}
        return await _confluence_request(
            cred, "DELETE", f"/content/{c.content_id}/label", api="v1",
            params=params, action_name="remove_label",
        )

    # ------------------------------------------------------------------
    # New content property handlers
    # ------------------------------------------------------------------
    async def _update_content_property(
        self, c: ConfluenceUpdateContentPropertyConfig, cred
    ) -> Dict[str, Any]:
        body = {
            "key": c.property_key,
            "value": _coerce_property_value(c.property_value),
            "version": {"number": _safe_int(c.version_number, "version_number")},
        }
        return await _confluence_request(
            cred, "PUT", f"/pages/{c.page_id}/properties/{c.property_id}",
            json_body=body, action_name="update_content_property",
        )

    async def _delete_content_property(
        self, c: ConfluenceDeleteContentPropertyConfig, cred
    ) -> Dict[str, Any]:
        return await _confluence_request(
            cred, "DELETE", f"/pages/{c.page_id}/properties/{c.property_id}",
            action_name="delete_content_property",
        )

    # ------------------------------------------------------------------
    # Task handlers
    # ------------------------------------------------------------------
    async def _list_tasks(self, c: ConfluenceListTasksConfig, cred) -> Dict[str, Any]:
        params: Dict[str, Any] = {"limit": c.limit}
        if c.page_id:
            params["pageId"] = c.page_id
        if c.space_id:
            params["spaceId"] = c.space_id
        if c.status:
            params["status"] = c.status
        return await _confluence_request(
            cred, "GET", "/tasks", params=params, action_name="list_tasks"
        )

    async def _get_task(self, c: ConfluenceGetTaskConfig, cred) -> Dict[str, Any]:
        return await _confluence_request(
            cred, "GET", f"/tasks/{c.task_id}", action_name="get_task"
        )

    async def _update_task(self, c: ConfluenceUpdateTaskConfig, cred) -> Dict[str, Any]:
        body = {"status": c.status}
        return await _confluence_request(
            cred, "PUT", f"/tasks/{c.task_id}", json_body=body, action_name="update_task"
        )

    # ------------------------------------------------------------------
    # New space handlers
    # ------------------------------------------------------------------
    async def _create_space(self, c: ConfluenceCreateSpaceConfig, cred) -> Dict[str, Any]:
        body: Dict[str, Any] = {"name": c.name, "key": c.key}
        if c.description:
            body["description"] = {
                "representation": "plain",
                "value": c.description,
            }
        return await _confluence_request(
            cred, "POST", "/spaces", json_body=body, action_name="create_space"
        )
