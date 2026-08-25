"""
WordPress REST API automation node.

Provides comprehensive workflow integration with WordPress for operations including:
- Content Operations: posts, pages, media (CRUD + revisions)
- User Management: users, comments (CRUD)
- Taxonomy Operations: categories, tags, custom taxonomies (CRUD)
- Site Management: settings, post types, statuses
- Block Editor: blocks, block types, block rendering
- Search: unified search across content types

Authentication: Application Passwords (self-hosted), WordPress.com OAuth, or Basic Auth
API Base URL: https://yoursite.com/wp-json/wp/v2 (self-hosted) or https://public-api.wordpress.com/wp/v2/sites/{site_id} (WordPress.com)
Documentation: https://developer.wordpress.org/rest-api/reference/
Rate Limit: Varies by hosting provider
"""

import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, ConfigDict, Discriminator, Field
import httpx
import base64
from urllib.parse import urlsplit

from nodes.core.base import WorkflowNode, NodeConfig
from utils.ssrf import guarded_async_client
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.oauth.wordpress_oauth import is_token_expired, refresh_access_token
from nodes.scopes.wordpress import WORDPRESS_SCOPES

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

WORDPRESS_COM_API_BASE = "https://public-api.wordpress.com/wp/v2/sites"

# ============================================================================
# Credential Schema
# ============================================================================


class WordPressApplicationPasswordCredential(BaseModel):
    """
    Application Password credential for self-hosted WordPress.

    Create Application Passwords in WordPress admin: Users → Profile → Application Passwords
    Requires WordPress 5.6+ and HTTPS.
    """

    credential_type: Literal["wordpress_application_password"] = Field(
        "wordpress_application_password", json_schema_extra={"ui:hidden": True}
    )
    site_url: str = Field(
        ...,
        title="WordPress Site URL",
        description="Your WordPress site URL (e.g., https://example.com)",
        json_schema_extra={"placeholder": "https://example.com"},
    )
    username: str = Field(
        ..., title="WordPress Username", description="Your WordPress username"
    )
    application_password: str = Field(
        ...,
        title="Application Password",
        description="Application Password created in WordPress",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(json_schema_extra={
        "x-credential-url": "https://wordpress.org/support/article/application-passwords/",
        "x-credential-instructions": "Go to Users → Your Profile → Application Passwords in WordPress admin",
    })


class WordPressBasicAuthCredential(BaseModel):
    """
    Basic Authentication credential for WordPress.

    Note: Requires Basic Auth plugin for WordPress.
    Not recommended for production use.
    """

    credential_type: Literal["wordpress_basic_auth"] = Field(
        "wordpress_basic_auth", json_schema_extra={"ui:hidden": True}
    )
    site_url: str = Field(
        ...,
        title="WordPress Site URL",
        description="Your WordPress site URL (e.g., https://example.com)",
        json_schema_extra={"placeholder": "https://example.com"},
    )
    username: str = Field(
        ..., title="WordPress Username", description="Your WordPress username"
    )
    password: str = Field(
        ...,
        title="WordPress Password",
        description="Your WordPress password",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(json_schema_extra={
        "x-credential-url": "https://github.com/WP-API/Basic-Auth",
        "x-credential-instructions": "Install Basic-Auth plugin (not recommended for production)",
    })


class WordPressOAuthCredential(BaseModel):
    """
    OAuth 2.0 credential for WordPress.com sites.
    Tokens are obtained via OAuth flow, not entered manually.

    Register OAuth app at: https://developer.wordpress.com/apps/
    """

    credential_type: Literal["wordpress_oauth"] = Field(
        "wordpress_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ...,
        title="Access Token",
        description="OAuth 2.0 access token from WordPress.com",
    )
    refresh_token: Optional[str] = Field(
        None,
        title="Refresh Token",
        description="OAuth 2.0 refresh token for automatic renewal",
    )
    expires_at: Optional[str] = Field(
        None,
        title="Token Expiry",
        description="ISO 8601 timestamp when access token expires",
    )
    site_id: str = Field(
        ...,
        title="WordPress.com Site ID",
        description="WordPress.com site ID or domain",
    )
    email: Optional[str] = Field(
        None,
        title="Account Email",
        description="Email address of the connected WordPress.com account",
    )

    model_config = ConfigDict(json_schema_extra={
        "x-credential-type": "oauth",
        "x-oauth-provider": "wordpress",
        "x-oauth-scopes": ["global"],  # WordPress.com uses global scope by default
        "x-oauth-supports-custom-client": True,
        "x-oauth-custom-client-help": "Register your OAuth app at https://developer.wordpress.com/apps/",
    })


# Union type for credentials - supports all three authentication methods
# OAuth shown first (best UX), then Application Password, then Basic Auth
WordPressCredential = Union[
    WordPressOAuthCredential,
    WordPressApplicationPasswordCredential,
    WordPressBasicAuthCredential,
]


# ============================================================================
# Post Operation Configs
# ============================================================================


class WordPressListPostsConfig(BaseModel):
    """List posts with filtering, sorting, and pagination"""

    operation: Literal["list_posts"] = Field(
        "list_posts",
        json_schema_extra={
            "const": "list_posts",
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "List Posts",
        },
        title="List Posts",
    )
    context: Optional[str] = Field(
        "view",
        title="Context",
        description="Scope of response",
        json_schema_extra={"enum": ["view", "embed", "edit"]},
    )
    page: Optional[int] = Field(
        1, title="Page", description="Page number for pagination", ge=1
    )
    per_page: Optional[int] = Field(
        10,
        title="Per Page",
        description="Number of posts per page (max 100)",
        ge=1,
        le=100,
    )
    search: Optional[str] = Field(
        None, title="Search", description="Search term to filter posts"
    )
    after: Optional[str] = Field(
        None,
        title="After Date",
        description="Posts published after this date (ISO 8601)",
    )
    before: Optional[str] = Field(
        None,
        title="Before Date",
        description="Posts published before this date (ISO 8601)",
    )
    author: Optional[int] = Field(
        None, title="Author ID", description="Filter by author ID"
    )
    categories: Optional[str] = Field(
        None, title="Categories", description="Comma-separated category IDs"
    )
    tags: Optional[str] = Field(
        None, title="Tags", description="Comma-separated tag IDs"
    )
    status: Optional[str] = Field(
        "publish",
        title="Status",
        description="Post status",
        json_schema_extra={
            "enum": ["publish", "future", "draft", "pending", "private", "trash", "any"]
        },
    )
    order: Optional[str] = Field(
        "desc",
        title="Order",
        description="Sort order",
        json_schema_extra={"enum": ["asc", "desc"]},
    )
    orderby: Optional[str] = Field(
        "date",
        title="Order By",
        description="Sort field",
        json_schema_extra={
            "enum": [
                "author",
                "date",
                "id",
                "include",
                "modified",
                "parent",
                "relevance",
                "slug",
                "title",
            ]
        },
    )


class WordPressGetPostConfig(BaseModel):
    """Get a single post by ID"""

    operation: Literal["get_post"] = Field(
        "get_post",
        json_schema_extra={
            "const": "get_post",
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Get Post",
        },
        title="Get Post",
    )
    post_id: int = Field(
        ..., title="Post ID", description="The ID of the post to retrieve"
    )
    context: Optional[str] = Field(
        "view",
        title="Context",
        description="Scope of response",
        json_schema_extra={"enum": ["view", "embed", "edit"]},
    )
    password: Optional[str] = Field(
        None,
        title="Password",
        description="Password for password-protected post",
        json_schema_extra={"ui:widget": "password"},
    )


class WordPressCreatePostConfig(BaseModel):
    """Create a new post"""

    operation: Literal["create_post"] = Field(
        "create_post",
        json_schema_extra={
            "const": "create_post",
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Create Post",
        },
        title="Create Post",
    )
    title: str = Field(..., title="Title", description="Post title")
    content: str = Field(
        ...,
        title="Content",
        description="Post content (HTML or blocks)",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 10},
    )
    status: Optional[str] = Field(
        "draft",
        title="Status",
        description="Post status",
        json_schema_extra={
            "enum": ["publish", "future", "draft", "pending", "private"]
        },
    )
    excerpt: Optional[str] = Field(
        None,
        title="Excerpt",
        description="Post excerpt",
        json_schema_extra={"ui:widget": "textarea"},
    )
    author: Optional[int] = Field(None, title="Author ID", description="Author user ID")
    featured_media: Optional[int] = Field(
        None, title="Featured Media ID", description="Featured image media ID"
    )
    categories: Optional[List[int]] = Field(
        None, title="Categories", description="Array of category IDs"
    )
    tags: Optional[List[int]] = Field(
        None, title="Tags", description="Array of tag IDs"
    )
    slug: Optional[str] = Field(None, title="Slug", description="URL slug for the post")
    date: Optional[str] = Field(
        None, title="Publish Date", description="Publication date (ISO 8601)"
    )
    comment_status: Optional[str] = Field(
        None,
        title="Comment Status",
        description="Allow comments",
        json_schema_extra={"enum": ["open", "closed"]},
    )
    ping_status: Optional[str] = Field(
        None,
        title="Ping Status",
        description="Allow pingbacks",
        json_schema_extra={"enum": ["open", "closed"]},
    )
    format: Optional[str] = Field(
        None,
        title="Post Format",
        description="Post format",
        json_schema_extra={
            "enum": [
                "standard",
                "aside",
                "chat",
                "gallery",
                "link",
                "image",
                "quote",
                "status",
                "video",
                "audio",
            ]
        },
    )
    sticky: Optional[bool] = Field(
        None, title="Sticky", description="Mark as sticky post"
    )


class WordPressUpdatePostConfig(BaseModel):
    """Update an existing post"""

    operation: Literal["update_post"] = Field(
        "update_post",
        json_schema_extra={
            "const": "update_post",
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Update Post",
        },
        title="Update Post",
    )
    post_id: int = Field(
        ..., title="Post ID", description="The ID of the post to update"
    )
    title: Optional[str] = Field(None, title="Title", description="Post title")
    content: Optional[str] = Field(
        None,
        title="Content",
        description="Post content",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 10},
    )
    status: Optional[str] = Field(
        None,
        title="Status",
        description="Post status",
        json_schema_extra={
            "enum": ["publish", "future", "draft", "pending", "private"]
        },
    )
    excerpt: Optional[str] = Field(
        None,
        title="Excerpt",
        description="Post excerpt",
        json_schema_extra={"ui:widget": "textarea"},
    )
    author: Optional[int] = Field(None, title="Author ID", description="Author user ID")
    featured_media: Optional[int] = Field(
        None, title="Featured Media ID", description="Featured image media ID"
    )
    categories: Optional[List[int]] = Field(
        None, title="Categories", description="Array of category IDs"
    )
    tags: Optional[List[int]] = Field(
        None, title="Tags", description="Array of tag IDs"
    )
    slug: Optional[str] = Field(None, title="Slug", description="URL slug for the post")
    comment_status: Optional[str] = Field(
        None,
        title="Comment Status",
        description="Allow comments",
        json_schema_extra={"enum": ["open", "closed"]},
    )
    ping_status: Optional[str] = Field(
        None,
        title="Ping Status",
        description="Allow pingbacks",
        json_schema_extra={"enum": ["open", "closed"]},
    )
    format: Optional[str] = Field(
        None,
        title="Post Format",
        description="Post format",
        json_schema_extra={
            "enum": [
                "standard",
                "aside",
                "chat",
                "gallery",
                "link",
                "image",
                "quote",
                "status",
                "video",
                "audio",
            ]
        },
    )
    sticky: Optional[bool] = Field(
        None, title="Sticky", description="Mark as sticky post"
    )


class WordPressDeletePostConfig(BaseModel):
    """Delete a post"""

    operation: Literal["delete_post"] = Field(
        "delete_post",
        json_schema_extra={
            "const": "delete_post",
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Delete Post",
        },
        title="Delete Post",
    )
    post_id: int = Field(
        ..., title="Post ID", description="The ID of the post to delete"
    )
    force: Optional[bool] = Field(
        False, title="Force Delete", description="Permanently delete (bypass trash)"
    )


# ============================================================================
# Page Operation Configs
# ============================================================================


class WordPressListPagesConfig(BaseModel):
    """List pages with filtering and pagination"""

    operation: Literal["list_pages"] = Field(
        "list_pages",
        json_schema_extra={
            "const": "list_pages",
            "ui:hidden": True,
            "x-category": "Page",
            "x-is-trigger": False,
            "x-display-name": "List Pages",
        },
        title="List Pages",
    )
    context: Optional[str] = Field(
        "view",
        title="Context",
        description="Scope of response",
        json_schema_extra={"enum": ["view", "embed", "edit"]},
    )
    page: Optional[int] = Field(
        1, title="Page", description="Page number for pagination", ge=1
    )
    per_page: Optional[int] = Field(
        10,
        title="Per Page",
        description="Number of pages per page (max 100)",
        ge=1,
        le=100,
    )
    search: Optional[str] = Field(
        None, title="Search", description="Search term to filter pages"
    )
    status: Optional[str] = Field(
        "publish",
        title="Status",
        description="Page status",
        json_schema_extra={
            "enum": ["publish", "future", "draft", "pending", "private", "trash", "any"]
        },
    )
    order: Optional[str] = Field(
        "desc",
        title="Order",
        description="Sort order",
        json_schema_extra={"enum": ["asc", "desc"]},
    )
    orderby: Optional[str] = Field(
        "date",
        title="Order By",
        description="Sort field",
        json_schema_extra={
            "enum": [
                "author",
                "date",
                "id",
                "include",
                "modified",
                "parent",
                "relevance",
                "slug",
                "title",
                "menu_order",
            ]
        },
    )
    parent: Optional[int] = Field(
        None, title="Parent ID", description="Filter by parent page ID"
    )


class WordPressGetPageConfig(BaseModel):
    """Get a single page by ID"""

    operation: Literal["get_page"] = Field(
        "get_page",
        json_schema_extra={
            "const": "get_page",
            "ui:hidden": True,
            "x-category": "Page",
            "x-is-trigger": False,
            "x-display-name": "Get Page",
        },
        title="Get Page",
    )
    page_id: int = Field(
        ..., title="Page ID", description="The ID of the page to retrieve"
    )
    context: Optional[str] = Field(
        "view",
        title="Context",
        description="Scope of response",
        json_schema_extra={"enum": ["view", "embed", "edit"]},
    )


class WordPressCreatePageConfig(BaseModel):
    """Create a new page"""

    operation: Literal["create_page"] = Field(
        "create_page",
        json_schema_extra={
            "const": "create_page",
            "ui:hidden": True,
            "x-category": "Page",
            "x-is-trigger": False,
            "x-display-name": "Create Page",
        },
        title="Create Page",
    )
    title: str = Field(..., title="Title", description="Page title")
    content: str = Field(
        ...,
        title="Content",
        description="Page content",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 10},
    )
    status: Optional[str] = Field(
        "draft",
        title="Status",
        description="Page status",
        json_schema_extra={
            "enum": ["publish", "future", "draft", "pending", "private"]
        },
    )
    parent: Optional[int] = Field(
        None, title="Parent Page ID", description="Parent page ID"
    )
    slug: Optional[str] = Field(None, title="Slug", description="URL slug for the page")
    menu_order: Optional[int] = Field(
        None, title="Menu Order", description="Order in page list"
    )
    featured_media: Optional[int] = Field(
        None, title="Featured Media ID", description="Featured image media ID"
    )
    author: Optional[int] = Field(None, title="Author ID", description="Author user ID")
    excerpt: Optional[str] = Field(
        None,
        title="Excerpt",
        description="Page excerpt",
        json_schema_extra={"ui:widget": "textarea"},
    )
    comment_status: Optional[str] = Field(
        None,
        title="Comment Status",
        description="Allow comments",
        json_schema_extra={"enum": ["open", "closed"]},
    )
    template: Optional[str] = Field(
        None, title="Page Template", description="Page template filename"
    )


class WordPressUpdatePageConfig(BaseModel):
    """Update an existing page"""

    operation: Literal["update_page"] = Field(
        "update_page",
        json_schema_extra={
            "const": "update_page",
            "ui:hidden": True,
            "x-category": "Page",
            "x-is-trigger": False,
            "x-display-name": "Update Page",
        },
        title="Update Page",
    )
    page_id: int = Field(
        ..., title="Page ID", description="The ID of the page to update"
    )
    title: Optional[str] = Field(None, title="Title", description="Page title")
    content: Optional[str] = Field(
        None,
        title="Content",
        description="Page content",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 10},
    )
    status: Optional[str] = Field(
        None,
        title="Status",
        description="Page status",
        json_schema_extra={
            "enum": ["publish", "future", "draft", "pending", "private"]
        },
    )
    parent: Optional[int] = Field(
        None, title="Parent Page ID", description="Parent page ID"
    )
    slug: Optional[str] = Field(None, title="Slug", description="URL slug for the page")
    menu_order: Optional[int] = Field(
        None, title="Menu Order", description="Order in page list"
    )
    featured_media: Optional[int] = Field(
        None, title="Featured Media ID", description="Featured image media ID"
    )


class WordPressDeletePageConfig(BaseModel):
    """Delete a page"""

    operation: Literal["delete_page"] = Field(
        "delete_page",
        json_schema_extra={
            "const": "delete_page",
            "ui:hidden": True,
            "x-category": "Page",
            "x-is-trigger": False,
            "x-display-name": "Delete Page",
        },
        title="Delete Page",
    )
    page_id: int = Field(
        ..., title="Page ID", description="The ID of the page to delete"
    )
    force: Optional[bool] = Field(
        False, title="Force Delete", description="Permanently delete (bypass trash)"
    )


# ============================================================================
# Media Operation Configs
# ============================================================================


class WordPressListMediaConfig(BaseModel):
    """List media items"""

    operation: Literal["list_media_items"] = Field(
        "list_media_items",
        json_schema_extra={
            "const": "list_media_items",
            "ui:hidden": True,
            "x-category": "Media",
            "x-is-trigger": False,
            "x-display-name": "List Media Items",
        },
        title="List Media Items",
    )
    context: Optional[str] = Field(
        "view",
        title="Context",
        description="Scope of response",
        json_schema_extra={"enum": ["view", "embed", "edit"]},
    )
    page: Optional[int] = Field(
        1, title="Page", description="Page number for pagination", ge=1
    )
    per_page: Optional[int] = Field(
        10,
        title="Per Page",
        description="Number of items per page (max 100)",
        ge=1,
        le=100,
    )
    search: Optional[str] = Field(
        None, title="Search", description="Search term to filter media"
    )
    media_type: Optional[str] = Field(
        None,
        title="Media Type",
        description="Filter by media type",
        json_schema_extra={"enum": ["image", "video", "audio", "application"]},
    )
    mime_type: Optional[str] = Field(
        None, title="MIME Type", description="Filter by MIME type"
    )


class WordPressGetMediaConfig(BaseModel):
    """Get a single media item by ID"""

    operation: Literal["get_media_item"] = Field(
        "get_media_item",
        json_schema_extra={
            "const": "get_media_item",
            "ui:hidden": True,
            "x-category": "Media",
            "x-is-trigger": False,
            "x-display-name": "Get Media Item",
        },
        title="Get Media Item",
    )
    media_id: int = Field(
        ..., title="Media ID", description="The ID of the media item to retrieve"
    )


class WordPressUploadMediaConfig(BaseModel):
    """Upload a new media file"""

    operation: Literal["upload_media_file"] = Field(
        "upload_media_file",
        json_schema_extra={
            "const": "upload_media_file",
            "ui:hidden": True,
            "x-category": "Media",
            "x-is-trigger": False,
            "x-display-name": "Upload Media File",
        },
        title="Upload Media File",
    )
    file_url: str = Field(
        ...,
        title="File URL",
        description="The file to upload to the media library — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}).",
        json_schema_extra={"ui:widget": "media_upload"},
    )
    title: Optional[str] = Field(None, title="Title", description="Media title")
    caption: Optional[str] = Field(
        None,
        title="Caption",
        description="Media caption",
        json_schema_extra={"ui:widget": "textarea"},
    )
    alt_text: Optional[str] = Field(
        None, title="Alt Text", description="Alternative text for accessibility"
    )
    description: Optional[str] = Field(
        None,
        title="Description",
        description="Media description",
        json_schema_extra={"ui:widget": "textarea"},
    )
    post_id: Optional[int] = Field(
        None, title="Post ID", description="Attach media to this post ID"
    )


class WordPressUpdateMediaConfig(BaseModel):
    """Update media metadata"""

    operation: Literal["update_media_metadata"] = Field(
        "update_media_metadata",
        json_schema_extra={
            "const": "update_media_metadata",
            "ui:hidden": True,
            "x-category": "Media",
            "x-is-trigger": False,
            "x-display-name": "Update Media Metadata",
        },
        title="Update Media Metadata",
    )
    media_id: int = Field(
        ..., title="Media ID", description="The ID of the media item to update"
    )
    title: Optional[str] = Field(None, title="Title", description="Media title")
    caption: Optional[str] = Field(
        None,
        title="Caption",
        description="Media caption",
        json_schema_extra={"ui:widget": "textarea"},
    )
    alt_text: Optional[str] = Field(
        None, title="Alt Text", description="Alternative text for accessibility"
    )
    description: Optional[str] = Field(
        None,
        title="Description",
        description="Media description",
        json_schema_extra={"ui:widget": "textarea"},
    )


class WordPressDeleteMediaConfig(BaseModel):
    """Delete a media item"""

    operation: Literal["delete_media_item"] = Field(
        "delete_media_item",
        json_schema_extra={
            "const": "delete_media_item",
            "ui:hidden": True,
            "x-category": "Media",
            "x-is-trigger": False,
            "x-display-name": "Delete Media Item",
        },
        title="Delete Media Item",
    )
    media_id: int = Field(
        ..., title="Media ID", description="The ID of the media item to delete"
    )
    force: Optional[bool] = Field(
        False, title="Force Delete", description="Permanently delete (bypass trash)"
    )


# ============================================================================
# User Operation Configs
# ============================================================================


class WordPressListUsersConfig(BaseModel):
    """List users"""

    operation: Literal["list_users"] = Field(
        "list_users",
        json_schema_extra={
            "const": "list_users",
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "List Users",
        },
        title="List Users",
    )
    context: Optional[str] = Field(
        "view",
        title="Context",
        description="Scope of response",
        json_schema_extra={"enum": ["view", "embed", "edit"]},
    )
    page: Optional[int] = Field(
        1, title="Page", description="Page number for pagination", ge=1
    )
    per_page: Optional[int] = Field(
        10,
        title="Per Page",
        description="Number of users per page (max 100)",
        ge=1,
        le=100,
    )
    search: Optional[str] = Field(
        None, title="Search", description="Search term to filter users"
    )
    roles: Optional[str] = Field(
        None, title="Roles", description="Comma-separated list of roles"
    )
    order: Optional[str] = Field(
        "asc",
        title="Order",
        description="Sort order",
        json_schema_extra={"enum": ["asc", "desc"]},
    )
    orderby: Optional[str] = Field(
        "name",
        title="Order By",
        description="Sort field",
        json_schema_extra={
            "enum": ["id", "include", "name", "registered_date", "slug", "email", "url"]
        },
    )


class WordPressGetUserConfig(BaseModel):
    """Get a single user by ID"""

    operation: Literal["get_user"] = Field(
        "get_user",
        json_schema_extra={
            "const": "get_user",
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Get User",
        },
        title="Get User",
    )
    user_id: int = Field(
        ..., title="User ID", description="The ID of the user to retrieve"
    )
    context: Optional[str] = Field(
        "view",
        title="Context",
        description="Scope of response",
        json_schema_extra={"enum": ["view", "embed", "edit"]},
    )


class WordPressCreateUserConfig(BaseModel):
    """Create a new user"""

    operation: Literal["create_user"] = Field(
        "create_user",
        json_schema_extra={
            "const": "create_user",
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Create User",
        },
        title="Create User",
    )
    username: str = Field(..., title="Username", description="Login name for the user")
    email: str = Field(..., title="Email", description="Email address")
    password: str = Field(
        ...,
        title="Password",
        description="Password for the user",
        json_schema_extra={"ui:widget": "password"},
    )
    first_name: Optional[str] = Field(
        None, title="First Name", description="User first name"
    )
    last_name: Optional[str] = Field(
        None, title="Last Name", description="User last name"
    )
    url: Optional[str] = Field(
        None, title="Website URL", description="User website URL"
    )
    description: Optional[str] = Field(
        None,
        title="Bio/Description",
        description="User biographical info",
        json_schema_extra={"ui:widget": "textarea"},
    )
    roles: Optional[List[str]] = Field(
        None, title="Roles", description="User roles array"
    )


class WordPressUpdateUserConfig(BaseModel):
    """Update an existing user"""

    operation: Literal["update_user"] = Field(
        "update_user",
        json_schema_extra={
            "const": "update_user",
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Update User",
        },
        title="Update User",
    )
    user_id: int = Field(
        ..., title="User ID", description="The ID of the user to update"
    )
    email: Optional[str] = Field(None, title="Email", description="Email address")
    first_name: Optional[str] = Field(
        None, title="First Name", description="User first name"
    )
    last_name: Optional[str] = Field(
        None, title="Last Name", description="User last name"
    )
    url: Optional[str] = Field(
        None, title="Website URL", description="User website URL"
    )
    description: Optional[str] = Field(
        None,
        title="Bio/Description",
        description="User biographical info",
        json_schema_extra={"ui:widget": "textarea"},
    )
    roles: Optional[List[str]] = Field(
        None, title="Roles", description="User roles array"
    )


class WordPressDeleteUserConfig(BaseModel):
    """Delete a user"""

    operation: Literal["delete_user"] = Field(
        "delete_user",
        json_schema_extra={
            "const": "delete_user",
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Delete User",
        },
        title="Delete User",
    )
    user_id: int = Field(
        ..., title="User ID", description="The ID of the user to delete"
    )
    reassign: Optional[int] = Field(
        None, title="Reassign To User ID", description="Reassign posts to this user ID"
    )
    force: Optional[bool] = Field(
        True, title="Force Delete", description="Required to be true for user deletion"
    )


# ============================================================================
# Comment Operation Configs
# ============================================================================


class WordPressListCommentsConfig(BaseModel):
    """List comments"""

    operation: Literal["list_comments"] = Field(
        "list_comments",
        json_schema_extra={
            "const": "list_comments",
            "ui:hidden": True,
            "x-category": "Comment",
            "x-is-trigger": False,
            "x-display-name": "List Comments",
        },
        title="List Comments",
    )
    context: Optional[str] = Field(
        "view",
        title="Context",
        description="Scope of response",
        json_schema_extra={"enum": ["view", "embed", "edit"]},
    )
    page: Optional[int] = Field(
        1, title="Page", description="Page number for pagination", ge=1
    )
    per_page: Optional[int] = Field(
        10,
        title="Per Page",
        description="Number of comments per page (max 100)",
        ge=1,
        le=100,
    )
    search: Optional[str] = Field(
        None, title="Search", description="Search term to filter comments"
    )
    post_id: Optional[int] = Field(
        None, title="Post ID", description="Filter by post ID"
    )
    parent: Optional[int] = Field(
        None, title="Parent Comment ID", description="Filter by parent comment ID"
    )
    author: Optional[int] = Field(
        None, title="Author ID", description="Filter by author user ID"
    )
    status: Optional[str] = Field(
        "approve",
        title="Status",
        description="Comment status",
        json_schema_extra={"enum": ["hold", "approve", "spam", "trash", "all"]},
    )
    order: Optional[str] = Field(
        "desc",
        title="Order",
        description="Sort order",
        json_schema_extra={"enum": ["asc", "desc"]},
    )
    orderby: Optional[str] = Field(
        "date_gmt",
        title="Order By",
        description="Sort field",
        json_schema_extra={
            "enum": ["date", "date_gmt", "id", "include", "post", "parent", "type"]
        },
    )


class WordPressGetCommentConfig(BaseModel):
    """Get a single comment by ID"""

    operation: Literal["get_comment"] = Field(
        "get_comment",
        json_schema_extra={
            "const": "get_comment",
            "ui:hidden": True,
            "x-category": "Comment",
            "x-is-trigger": False,
            "x-display-name": "Get Comment",
        },
        title="Get Comment",
    )
    comment_id: int = Field(
        ..., title="Comment ID", description="The ID of the comment to retrieve"
    )
    context: Optional[str] = Field(
        "view",
        title="Context",
        description="Scope of response",
        json_schema_extra={"enum": ["view", "embed", "edit"]},
    )


class WordPressCreateCommentConfig(BaseModel):
    """Create a new comment"""

    operation: Literal["create_post_comment"] = Field(
        "create_post_comment",
        json_schema_extra={
            "const": "create_post_comment",
            "ui:hidden": True,
            "x-category": "Comment",
            "x-is-trigger": False,
            "x-display-name": "Create Post Comment",
        },
        title="Create Post Comment",
    )
    post_id: int = Field(..., title="Post ID", description="Post ID to comment on")
    content: str = Field(
        ...,
        title="Content",
        description="Comment content",
        json_schema_extra={"ui:widget": "textarea"},
    )
    author_name: Optional[str] = Field(
        None, title="Author Name", description="Comment author name"
    )
    author_email: Optional[str] = Field(
        None, title="Author Email", description="Comment author email"
    )
    author_url: Optional[str] = Field(
        None, title="Author URL", description="Comment author URL"
    )
    parent: Optional[int] = Field(
        None, title="Parent Comment ID", description="Parent comment ID for replies"
    )
    status: Optional[str] = Field(
        None,
        title="Status",
        description="Comment status",
        json_schema_extra={"enum": ["hold", "approve", "spam", "trash"]},
    )


class WordPressUpdateCommentConfig(BaseModel):
    """Update an existing comment"""

    operation: Literal["update_comment"] = Field(
        "update_comment",
        json_schema_extra={
            "const": "update_comment",
            "ui:hidden": True,
            "x-category": "Comment",
            "x-is-trigger": False,
            "x-display-name": "Update Comment",
        },
        title="Update Comment",
    )
    comment_id: int = Field(
        ..., title="Comment ID", description="The ID of the comment to update"
    )
    content: Optional[str] = Field(
        None,
        title="Content",
        description="Comment content",
        json_schema_extra={"ui:widget": "textarea"},
    )
    status: Optional[str] = Field(
        None,
        title="Status",
        description="Comment status",
        json_schema_extra={"enum": ["hold", "approve", "spam", "trash"]},
    )
    author_name: Optional[str] = Field(
        None, title="Author Name", description="Comment author name"
    )
    author_email: Optional[str] = Field(
        None, title="Author Email", description="Comment author email"
    )
    author_url: Optional[str] = Field(
        None, title="Author URL", description="Comment author URL"
    )


class WordPressDeleteCommentConfig(BaseModel):
    """Delete a comment"""

    operation: Literal["delete_comment"] = Field(
        "delete_comment",
        json_schema_extra={
            "const": "delete_comment",
            "ui:hidden": True,
            "x-category": "Comment",
            "x-is-trigger": False,
            "x-display-name": "Delete Comment",
        },
        title="Delete Comment",
    )
    comment_id: int = Field(
        ..., title="Comment ID", description="The ID of the comment to delete"
    )
    force: Optional[bool] = Field(
        False, title="Force Delete", description="Permanently delete (bypass trash)"
    )


# ============================================================================
# Category Operation Configs
# ============================================================================


class WordPressListCategoriesConfig(BaseModel):
    """List categories"""

    operation: Literal["list_categories"] = Field(
        "list_categories",
        json_schema_extra={
            "const": "list_categories",
            "ui:hidden": True,
            "x-category": "Category",
            "x-is-trigger": False,
            "x-display-name": "List Categories",
        },
        title="List Categories",
    )
    context: Optional[str] = Field(
        "view",
        title="Context",
        description="Scope of response",
        json_schema_extra={"enum": ["view", "embed", "edit"]},
    )
    page: Optional[int] = Field(
        1, title="Page", description="Page number for pagination", ge=1
    )
    per_page: Optional[int] = Field(
        100,
        title="Per Page",
        description="Number of categories per page (max 100)",
        ge=1,
        le=100,
    )
    search: Optional[str] = Field(
        None, title="Search", description="Search term to filter categories"
    )
    hide_empty: Optional[bool] = Field(
        None, title="Hide Empty", description="Hide categories with no posts"
    )
    parent: Optional[int] = Field(
        None, title="Parent Category ID", description="Filter by parent category ID"
    )
    order: Optional[str] = Field(
        "asc",
        title="Order",
        description="Sort order",
        json_schema_extra={"enum": ["asc", "desc"]},
    )
    orderby: Optional[str] = Field(
        "name",
        title="Order By",
        description="Sort field",
        json_schema_extra={
            "enum": [
                "id",
                "include",
                "name",
                "slug",
                "term_group",
                "description",
                "count",
            ]
        },
    )


class WordPressGetCategoryConfig(BaseModel):
    """Get a single category by ID"""

    operation: Literal["get_category"] = Field(
        "get_category",
        json_schema_extra={
            "const": "get_category",
            "ui:hidden": True,
            "x-category": "Category",
            "x-is-trigger": False,
            "x-display-name": "Get Category",
        },
        title="Get Category",
    )
    category_id: int = Field(
        ..., title="Category ID", description="The ID of the category to retrieve"
    )
    context: Optional[str] = Field(
        "view",
        title="Context",
        description="Scope of response",
        json_schema_extra={"enum": ["view", "embed", "edit"]},
    )


class WordPressCreateCategoryConfig(BaseModel):
    """Create a new category"""

    operation: Literal["create_category"] = Field(
        "create_category",
        json_schema_extra={
            "const": "create_category",
            "ui:hidden": True,
            "x-category": "Category",
            "x-is-trigger": False,
            "x-display-name": "Create Category",
        },
        title="Create Category",
    )
    name: str = Field(..., title="Name", description="Category name")
    description: Optional[str] = Field(
        None,
        title="Description",
        description="Category description",
        json_schema_extra={"ui:widget": "textarea"},
    )
    slug: Optional[str] = Field(
        None, title="Slug", description="URL slug for the category"
    )
    parent: Optional[int] = Field(
        None, title="Parent Category ID", description="Parent category ID"
    )


class WordPressUpdateCategoryConfig(BaseModel):
    """Update an existing category"""

    operation: Literal["update_category"] = Field(
        "update_category",
        json_schema_extra={
            "const": "update_category",
            "ui:hidden": True,
            "x-category": "Category",
            "x-is-trigger": False,
            "x-display-name": "Update Category",
        },
        title="Update Category",
    )
    category_id: int = Field(
        ..., title="Category ID", description="The ID of the category to update"
    )
    name: Optional[str] = Field(None, title="Name", description="Category name")
    description: Optional[str] = Field(
        None,
        title="Description",
        description="Category description",
        json_schema_extra={"ui:widget": "textarea"},
    )
    slug: Optional[str] = Field(
        None, title="Slug", description="URL slug for the category"
    )
    parent: Optional[int] = Field(
        None, title="Parent Category ID", description="Parent category ID"
    )


class WordPressDeleteCategoryConfig(BaseModel):
    """Delete a category"""

    operation: Literal["delete_category"] = Field(
        "delete_category",
        json_schema_extra={
            "const": "delete_category",
            "ui:hidden": True,
            "x-category": "Category",
            "x-is-trigger": False,
            "x-display-name": "Delete Category",
        },
        title="Delete Category",
    )
    category_id: int = Field(
        ..., title="Category ID", description="The ID of the category to delete"
    )
    force: Optional[bool] = Field(
        False, title="Force Delete", description="Permanently delete"
    )


# ============================================================================
# Tag Operation Configs
# ============================================================================


class WordPressListTagsConfig(BaseModel):
    """List tags"""

    operation: Literal["list_tags"] = Field(
        "list_tags",
        json_schema_extra={
            "const": "list_tags",
            "ui:hidden": True,
            "x-category": "Tag",
            "x-is-trigger": False,
            "x-display-name": "List Tags",
        },
        title="List Tags",
    )
    context: Optional[str] = Field(
        "view",
        title="Context",
        description="Scope of response",
        json_schema_extra={"enum": ["view", "embed", "edit"]},
    )
    page: Optional[int] = Field(
        1, title="Page", description="Page number for pagination", ge=1
    )
    per_page: Optional[int] = Field(
        100,
        title="Per Page",
        description="Number of tags per page (max 100)",
        ge=1,
        le=100,
    )
    search: Optional[str] = Field(
        None, title="Search", description="Search term to filter tags"
    )
    hide_empty: Optional[bool] = Field(
        None, title="Hide Empty", description="Hide tags with no posts"
    )
    order: Optional[str] = Field(
        "asc",
        title="Order",
        description="Sort order",
        json_schema_extra={"enum": ["asc", "desc"]},
    )
    orderby: Optional[str] = Field(
        "name",
        title="Order By",
        description="Sort field",
        json_schema_extra={
            "enum": [
                "id",
                "include",
                "name",
                "slug",
                "term_group",
                "description",
                "count",
            ]
        },
    )


class WordPressGetTagConfig(BaseModel):
    """Get a single tag by ID"""

    operation: Literal["get_tag"] = Field(
        "get_tag",
        json_schema_extra={
            "const": "get_tag",
            "ui:hidden": True,
            "x-category": "Tag",
            "x-is-trigger": False,
            "x-display-name": "Get Tag",
        },
        title="Get Tag",
    )
    tag_id: int = Field(
        ..., title="Tag ID", description="The ID of the tag to retrieve"
    )
    context: Optional[str] = Field(
        "view",
        title="Context",
        description="Scope of response",
        json_schema_extra={"enum": ["view", "embed", "edit"]},
    )


class WordPressCreateTagConfig(BaseModel):
    """Create a new tag"""

    operation: Literal["create_tag"] = Field(
        "create_tag",
        json_schema_extra={
            "const": "create_tag",
            "ui:hidden": True,
            "x-category": "Tag",
            "x-is-trigger": False,
            "x-display-name": "Create Tag",
        },
        title="Create Tag",
    )
    name: str = Field(..., title="Name", description="Tag name")
    description: Optional[str] = Field(
        None,
        title="Description",
        description="Tag description",
        json_schema_extra={"ui:widget": "textarea"},
    )
    slug: Optional[str] = Field(None, title="Slug", description="URL slug for the tag")


class WordPressUpdateTagConfig(BaseModel):
    """Update an existing tag"""

    operation: Literal["update_tag"] = Field(
        "update_tag",
        json_schema_extra={
            "const": "update_tag",
            "ui:hidden": True,
            "x-category": "Tag",
            "x-is-trigger": False,
            "x-display-name": "Update Tag",
        },
        title="Update Tag",
    )
    tag_id: int = Field(..., title="Tag ID", description="The ID of the tag to update")
    name: Optional[str] = Field(None, title="Name", description="Tag name")
    description: Optional[str] = Field(
        None,
        title="Description",
        description="Tag description",
        json_schema_extra={"ui:widget": "textarea"},
    )
    slug: Optional[str] = Field(None, title="Slug", description="URL slug for the tag")


class WordPressDeleteTagConfig(BaseModel):
    """Delete a tag"""

    operation: Literal["delete_tag"] = Field(
        "delete_tag",
        json_schema_extra={
            "const": "delete_tag",
            "ui:hidden": True,
            "x-category": "Tag",
            "x-is-trigger": False,
            "x-display-name": "Delete Tag",
        },
        title="Delete Tag",
    )
    tag_id: int = Field(..., title="Tag ID", description="The ID of the tag to delete")
    force: Optional[bool] = Field(
        False, title="Force Delete", description="Permanently delete"
    )


# ============================================================================
# Search Config
# ============================================================================


class WordPressSearchConfig(BaseModel):
    """Search across all content types"""

    operation: Literal["search_content"] = Field(
        "search_content",
        json_schema_extra={
            "const": "search_content",
            "ui:hidden": True,
            "x-category": "Post",
            "x-is-trigger": False,
            "x-display-name": "Search Content",
        },
        title="Search Content",
    )
    search_term: str = Field(..., title="Search Term", description="Search query")
    context: Optional[str] = Field(
        "view",
        title="Context",
        description="Scope of response",
        json_schema_extra={"enum": ["view", "embed"]},
    )
    page: Optional[int] = Field(
        1, title="Page", description="Page number for pagination", ge=1
    )
    per_page: Optional[int] = Field(
        10,
        title="Per Page",
        description="Number of results per page (max 100)",
        ge=1,
        le=100,
    )
    search_type: Optional[str] = Field(
        None,
        title="Type",
        description="Filter by content type",
        json_schema_extra={"enum": ["post", "page", "attachment"]},
    )
    subtype: Optional[str] = Field(
        None,
        title="Subtype",
        description="Filter by subtype (post type or attachment MIME type)",
    )


# ============================================================================
# Settings Config
# ============================================================================


class WordPressGetSettingsConfig(BaseModel):
    """Get site settings"""

    operation: Literal["get_site_settings"] = Field(
        "get_site_settings",
        json_schema_extra={
            "const": "get_site_settings",
            "ui:hidden": True,
            "x-category": "Site Settings",
            "x-is-trigger": False,
            "x-display-name": "Get Site Settings",
        },
        title="Get Site Settings",
    )


class WordPressUpdateSettingsConfig(BaseModel):
    """Update site settings"""

    operation: Literal["update_site_settings"] = Field(
        "update_site_settings",
        json_schema_extra={
            "const": "update_site_settings",
            "ui:hidden": True,
            "x-category": "Site Settings",
            "x-is-trigger": False,
            "x-display-name": "Update Site Settings",
        },
        title="Update Site Settings",
    )
    title: Optional[str] = Field(None, title="Site Title", description="Site title")
    description: Optional[str] = Field(
        None, title="Site Tagline", description="Site tagline/description"
    )
    timezone: Optional[str] = Field(
        None, title="Timezone", description="Timezone (e.g., America/New_York)"
    )
    date_format: Optional[str] = Field(
        None, title="Date Format", description="Date format string"
    )
    time_format: Optional[str] = Field(
        None, title="Time Format", description="Time format string"
    )
    start_of_week: Optional[int] = Field(
        None,
        title="Start of Week",
        description="Day number (0=Sunday, 6=Saturday)",
        ge=0,
        le=6,
    )
    language: Optional[str] = Field(
        None, title="Language", description="Site language code"
    )
    use_smilies: Optional[bool] = Field(
        None,
        title="Convert Emoticons",
        description="Convert text emoticons to graphics",
    )
    default_category: Optional[int] = Field(
        None, title="Default Category", description="Default post category ID"
    )
    default_post_format: Optional[str] = Field(
        None, title="Default Post Format", description="Default post format"
    )
    posts_per_page: Optional[int] = Field(
        None,
        title="Posts Per Page",
        description="Number of posts to show per page",
        ge=1,
    )


# ============================================================================
# Discriminated Union
# ============================================================================

WordPressConfig = Annotated[
    Union[
        # Post operations (5)
        WordPressListPostsConfig,
        WordPressGetPostConfig,
        WordPressCreatePostConfig,
        WordPressUpdatePostConfig,
        WordPressDeletePostConfig,
        # Page operations (5)
        WordPressListPagesConfig,
        WordPressGetPageConfig,
        WordPressCreatePageConfig,
        WordPressUpdatePageConfig,
        WordPressDeletePageConfig,
        # Media operations (5)
        WordPressListMediaConfig,
        WordPressGetMediaConfig,
        WordPressUploadMediaConfig,
        WordPressUpdateMediaConfig,
        WordPressDeleteMediaConfig,
        # User operations (5)
        WordPressListUsersConfig,
        WordPressGetUserConfig,
        WordPressCreateUserConfig,
        WordPressUpdateUserConfig,
        WordPressDeleteUserConfig,
        # Comment operations (5)
        WordPressListCommentsConfig,
        WordPressGetCommentConfig,
        WordPressCreateCommentConfig,
        WordPressUpdateCommentConfig,
        WordPressDeleteCommentConfig,
        # Category operations (5)
        WordPressListCategoriesConfig,
        WordPressGetCategoryConfig,
        WordPressCreateCategoryConfig,
        WordPressUpdateCategoryConfig,
        WordPressDeleteCategoryConfig,
        # Tag operations (5)
        WordPressListTagsConfig,
        WordPressGetTagConfig,
        WordPressCreateTagConfig,
        WordPressUpdateTagConfig,
        WordPressDeleteTagConfig,
        # Search operation (1)
        WordPressSearchConfig,
        # Settings operations (2)
        WordPressGetSettingsConfig,
        WordPressUpdateSettingsConfig,
    ],
    Discriminator("operation"),
]


# ============================================================================
# Full Node Configuration
# ============================================================================


class WordPressNodeConfig(NodeConfig[WordPressConfig, WordPressCredential]):
    """Full configuration for WordPress node including credentials"""

    pass


# ============================================================================
# Node Implementation
# ============================================================================


class WordPressNode(WorkflowNode):
    """
    WordPress automation node.

    Executes WordPress REST API operations for workflow automation.
    Supports 43 operations across posts, pages, media, users, comments, categories, tags, search, and settings.
    """

    edit_examples = [
        "Publish a blog post with featured image and categories",
        "Upload product photo to media library with description",
        "Create new user account with subscriber role",
        "Search posts matching keyword and get featured images",
        "Update about page content and publish",
        "Delete spam comments and approve pending reviews",
        "Create product category with description and slug",
    ]

    scope_registry = WORDPRESS_SCOPES
    # Their own post titles, not categories — a fresh WordPress has exactly one
    # category, "Uncategorized".
    connection_evidence = ConnectionEvidence(
        operation="list_posts",
        noun="posts",
    )

    @classmethod
    def get_config_model(cls):
        """Return the Pydantic model for node configuration."""
        return WordPressNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        """Refresh an expiring OAuth token at credential load (dropdowns,
        trigger registration). No-op for non-rotating credentials (API keys /
        offline / non-expiring tokens)."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.wordpress_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token,
            provider="wordpress",
        )

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the configured operation.

        Args:
            inputs: Output data from upstream nodes

        Returns:
            Dict with operation results including status, action, data, and timing
        """
        start_time = time.time()

        # Validate configuration
        config = self.config
        if not config or not isinstance(config, WordPressNodeConfig):
            raise ValueError("Valid configuration is required")

        # Validate credentials
        credentials = config.credentials
        if not credentials:
            raise ValueError(
                "Credentials are required. Connect your WordPress account in the credentials tab."
            )

        # Get the specific operation config
        op_config = config.config

        # Route to appropriate handler based on action
        handlers = {
            # Post operations
            "list_posts": self._handle_list_posts,
            "get_post": self._handle_get_post,
            "create_post": self._handle_create_post,
            "update_post": self._handle_update_post,
            "delete_post": self._handle_delete_post,
            # Page operations
            "list_pages": self._handle_list_pages,
            "get_page": self._handle_get_page,
            "create_page": self._handle_create_page,
            "update_page": self._handle_update_page,
            "delete_page": self._handle_delete_page,
            # Media operations
            "list_media_items": self._handle_list_media,
            "get_media_item": self._handle_get_media,
            "upload_media_file": self._handle_upload_media,
            "update_media_metadata": self._handle_update_media,
            "delete_media_item": self._handle_delete_media,
            # User operations
            "list_users": self._handle_list_users,
            "get_user": self._handle_get_user,
            "create_user": self._handle_create_user,
            "update_user": self._handle_update_user,
            "delete_user": self._handle_delete_user,
            # Comment operations
            "list_comments": self._handle_list_comments,
            "get_comment": self._handle_get_comment,
            "create_post_comment": self._handle_create_comment,
            "update_comment": self._handle_update_comment,
            "delete_comment": self._handle_delete_comment,
            # Category operations
            "list_categories": self._handle_list_categories,
            "get_category": self._handle_get_category,
            "create_category": self._handle_create_category,
            "update_category": self._handle_update_category,
            "delete_category": self._handle_delete_category,
            # Tag operations
            "list_tags": self._handle_list_tags,
            "get_tag": self._handle_get_tag,
            "create_tag": self._handle_create_tag,
            "update_tag": self._handle_update_tag,
            "delete_tag": self._handle_delete_tag,
            # Search operation
            "search_content": self._handle_search,
            # Settings operations
            "get_site_settings": self._handle_get_settings,
            "update_site_settings": self._handle_update_settings,
        }

        action = op_config.operation
        handler = handlers.get(action)

        if not handler:
            raise ValueError(f"Unknown action: {action}")

        # Execute the handler
        result = await handler(op_config, credentials)

        # Add timing information
        total_time = (time.time() - start_time) * 1000
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round(total_time, 2),
        }

        return result

    # =========================================================================
    # HTTP Request Helper
    # =========================================================================

    def _get_api_base_url(self, credentials: WordPressCredential) -> str:
        """
        Get the API base URL based on credential type.

        Args:
            credentials: WordPress credentials

        Returns:
            Base URL for API requests
        """
        if isinstance(credentials, WordPressOAuthCredential):
            # WordPress.com API
            # Clean site_id: remove protocol if present (handle legacy stored credentials)
            site_id = credentials.site_id
            if site_id and isinstance(site_id, str):
                site_id = (
                    site_id.replace("https://", "").replace("http://", "").rstrip("/")
                )
            return f"{WORDPRESS_COM_API_BASE}/{site_id}"
        elif isinstance(
            credentials,
            (WordPressApplicationPasswordCredential, WordPressBasicAuthCredential),
        ):
            # Check if this is a WordPress.com site (which requires OAuth)
            site_url = credentials.site_url.rstrip("/")
            # Compare the parsed hostname, not an arbitrary URL substring:
            # ``wordpress.com.attacker.example`` is self-hosted and must not
            # be mistaken for a WordPress.com origin.
            hostname = (urlsplit(site_url).hostname or "").lower().rstrip(".")
            if hostname == "wordpress.com" or hostname.endswith(".wordpress.com"):
                raise ValueError(
                    f"WordPress.com hosted sites require OAuth authentication. "
                    f"Application Passwords only work with self-hosted WordPress. "
                    f"Please use OAuth credentials for {site_url}"
                )
            # Self-hosted WordPress
            return f"{site_url}/wp-json/wp/v2"
        else:
            raise ValueError(f"Unknown credential type: {type(credentials)}")

    async def _get_auth_headers(
        self, credentials: WordPressCredential
    ) -> Dict[str, str]:
        """
        Get authentication headers based on credential type.

        Args:
            credentials: WordPress credentials

        Returns:
            Dict of HTTP headers for authentication
        """
        if isinstance(credentials, WordPressOAuthCredential):
            # OAuth token for WordPress.com — refresh + persist via shared helper
            from nodes.core.oauth_refresh import ensure_fresh_oauth_token
            
            cred_dict = credentials.model_dump()
            access_token = await ensure_fresh_oauth_token(
                credential_id=(self.node_data or {}).get("credential_id"),
                user_id=self.user_id,
                credential=cred_dict,
                refresh=refresh_access_token,
                provider="wordpress",
            )
            credentials.access_token = cred_dict["access_token"]
            credentials.expires_at = cred_dict.get("expires_at")
            if cred_dict.get("refresh_token"):
                credentials.refresh_token = cred_dict["refresh_token"]

            return {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }

        elif isinstance(credentials, WordPressApplicationPasswordCredential):
            # Application Password (Basic Auth)
            auth_string = f"{credentials.username}:{credentials.application_password}"
            auth_bytes = auth_string.encode("utf-8")
            auth_b64 = base64.b64encode(auth_bytes).decode("utf-8")

            return {
                "Authorization": f"Basic {auth_b64}",
                "Content-Type": "application/json",
            }

        elif isinstance(credentials, WordPressBasicAuthCredential):
            # Basic Auth
            auth_string = f"{credentials.username}:{credentials.password}"
            auth_bytes = auth_string.encode("utf-8")
            auth_b64 = base64.b64encode(auth_bytes).decode("utf-8")

            return {
                "Authorization": f"Basic {auth_b64}",
                "Content-Type": "application/json",
            }

        else:
            raise ValueError(f"Unknown credential type: {type(credentials)}")

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        credentials: WordPressCredential,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        action_name: str = "request",
    ) -> Dict[str, Any]:
        """
        Make an HTTP request to the WordPress API.

        Args:
            method: HTTP method (GET, POST, PUT, PATCH, DELETE)
            endpoint: API endpoint (without base URL)
            credentials: API credentials
            params: Query parameters
            json_body: JSON request body
            action_name: Name of the action (for response metadata)

        Returns:
            Dict with status, action, data, status_code, and timing
        """
        base_url = self._get_api_base_url(credentials)
        url = f"{base_url}{endpoint}"

        headers = await self._get_auth_headers(credentials)

        # Clean params (remove None values)
        if params:
            params = {k: v for k, v in params.items() if v is not None}

        start_time = time.time()

        async with guarded_async_client(timeout=30.0) as client:
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=json_body,
                )

                api_time = (time.time() - start_time) * 1000

                if response.status_code >= 400:
                    error_text = response.text
                    try:
                        error_data = response.json()
                        error_message = error_data.get(
                            "message", error_data.get("error", str(error_data))
                        )
                    except Exception:
                        error_message = error_text

                    logger.error(f"[WordPressNode] API error: {error_message}")
                    return {
                        "status": "error",
                        "action": action_name,
                        "error": error_message,
                        "status_code": response.status_code,
                        "timing_ms": {"api_request": round(api_time, 2)},
                    }

                # Parse response
                if response.status_code == 204:  # No content
                    data = {"success": True}
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
                    "timing_ms": {"api_request": round(api_time, 2)},
                }

            except httpx.TimeoutException:
                return {
                    "status": "error",
                    "action": action_name,
                    "error": "Request timed out",
                    "status_code": 408,
                    "timing_ms": {
                        "api_request": round((time.time() - start_time) * 1000, 2)
                    },
                }
            except Exception as e:
                logger.exception(f"[WordPressNode] Request failed: {e}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": str(e),
                    "status_code": 500,
                    "timing_ms": {
                        "api_request": round((time.time() - start_time) * 1000, 2)
                    },
                }

    # =========================================================================
    # Post Operation Handlers
    # =========================================================================

    async def _handle_list_posts(
        self, config: WordPressListPostsConfig, credentials: WordPressCredential
    ) -> Dict[str, Any]:
        """List posts with filtering and pagination."""
        params = {}

        if config.context:
            params["context"] = config.context
        if config.page:
            params["page"] = config.page
        if config.per_page:
            params["per_page"] = config.per_page
        if config.search:
            params["search"] = config.search
        if config.after:
            params["after"] = config.after
        if config.before:
            params["before"] = config.before
        if config.author:
            params["author"] = config.author
        if config.categories:
            params["categories"] = config.categories
        if config.tags:
            params["tags"] = config.tags
        if config.status:
            params["status"] = config.status
        if config.order:
            params["order"] = config.order
        if config.orderby:
            params["orderby"] = config.orderby

        return await self._make_request(
            method="GET",
            endpoint="/posts",
            credentials=credentials,
            params=params,
            action_name="list_posts",
        )

    async def _handle_get_post(
        self, config: WordPressGetPostConfig, credentials: WordPressCredential
    ) -> Dict[str, Any]:
        """Get a single post by ID."""
        params = {}

        if config.context:
            params["context"] = config.context
        if config.password:
            params["password"] = config.password

        return await self._make_request(
            method="GET",
            endpoint=f"/posts/{config.post_id}",
            credentials=credentials,
            params=params,
            action_name="get_post",
        )

    async def _handle_create_post(
        self, config: WordPressCreatePostConfig, credentials: WordPressCredential
    ) -> Dict[str, Any]:
        """Create a new post."""
        body: Dict[str, Any] = {
            "title": config.title,
            "content": config.content,
        }

        if config.status:
            body["status"] = config.status
        if config.excerpt:
            body["excerpt"] = config.excerpt
        if config.author:
            body["author"] = config.author
        if config.featured_media:
            body["featured_media"] = config.featured_media
        if config.categories:
            body["categories"] = config.categories
        if config.tags:
            body["tags"] = config.tags
        if config.slug:
            body["slug"] = config.slug
        if config.date:
            body["date"] = config.date
        if config.comment_status:
            body["comment_status"] = config.comment_status
        if config.ping_status:
            body["ping_status"] = config.ping_status
        if config.format:
            body["format"] = config.format
        if config.sticky is not None:
            body["sticky"] = config.sticky

        return await self._make_request(
            method="POST",
            endpoint="/posts",
            credentials=credentials,
            json_body=body,
            action_name="create_post",
        )

    async def _handle_update_post(
        self, config: WordPressUpdatePostConfig, credentials: WordPressCredential
    ) -> Dict[str, Any]:
        """Update an existing post."""
        body: Dict[str, Any] = {}

        if config.title is not None:
            body["title"] = config.title
        if config.content is not None:
            body["content"] = config.content
        if config.status is not None:
            body["status"] = config.status
        if config.excerpt is not None:
            body["excerpt"] = config.excerpt
        if config.author is not None:
            body["author"] = config.author
        if config.featured_media is not None:
            body["featured_media"] = config.featured_media
        if config.categories is not None:
            body["categories"] = config.categories
        if config.tags is not None:
            body["tags"] = config.tags
        if config.slug is not None:
            body["slug"] = config.slug
        if config.comment_status is not None:
            body["comment_status"] = config.comment_status
        if config.ping_status is not None:
            body["ping_status"] = config.ping_status
        if config.format is not None:
            body["format"] = config.format
        if config.sticky is not None:
            body["sticky"] = config.sticky

        return await self._make_request(
            method="POST",
            endpoint=f"/posts/{config.post_id}",
            credentials=credentials,
            json_body=body,
            action_name="update_post",
        )

    async def _handle_delete_post(
        self, config: WordPressDeletePostConfig, credentials: WordPressCredential
    ) -> Dict[str, Any]:
        """Delete a post."""
        params = {}
        if config.force:
            params["force"] = "true"

        return await self._make_request(
            method="DELETE",
            endpoint=f"/posts/{config.post_id}",
            credentials=credentials,
            params=params,
            action_name="delete_post",
        )

    # =========================================================================
    # Page Operation Handlers
    # =========================================================================

    async def _handle_list_pages(
        self, config: WordPressListPagesConfig, credentials: WordPressCredential
    ) -> Dict[str, Any]:
        """List pages with filtering and pagination."""
        params = {}

        if config.context:
            params["context"] = config.context
        if config.page:
            params["page"] = config.page
        if config.per_page:
            params["per_page"] = config.per_page
        if config.search:
            params["search"] = config.search
        if config.status:
            params["status"] = config.status
        if config.order:
            params["order"] = config.order
        if config.orderby:
            params["orderby"] = config.orderby
        if config.parent is not None:
            params["parent"] = config.parent

        return await self._make_request(
            method="GET",
            endpoint="/pages",
            credentials=credentials,
            params=params,
            action_name="list_pages",
        )

    async def _handle_get_page(
        self, config: WordPressGetPageConfig, credentials: WordPressCredential
    ) -> Dict[str, Any]:
        """Get a single page by ID."""
        params = {}

        if config.context:
            params["context"] = config.context

        return await self._make_request(
            method="GET",
            endpoint=f"/pages/{config.page_id}",
            credentials=credentials,
            params=params,
            action_name="get_page",
        )

    async def _handle_create_page(
        self, config: WordPressCreatePageConfig, credentials: WordPressCredential
    ) -> Dict[str, Any]:
        """Create a new page."""
        body: Dict[str, Any] = {
            "title": config.title,
            "content": config.content,
        }

        if config.status:
            body["status"] = config.status
        if config.parent is not None:
            body["parent"] = config.parent
        if config.slug:
            body["slug"] = config.slug
        if config.menu_order is not None:
            body["menu_order"] = config.menu_order
        if config.featured_media:
            body["featured_media"] = config.featured_media
        if config.author:
            body["author"] = config.author
        if config.excerpt:
            body["excerpt"] = config.excerpt
        if config.comment_status:
            body["comment_status"] = config.comment_status
        if config.template:
            body["template"] = config.template

        return await self._make_request(
            method="POST",
            endpoint="/pages",
            credentials=credentials,
            json_body=body,
            action_name="create_page",
        )

    async def _handle_update_page(
        self, config: WordPressUpdatePageConfig, credentials: WordPressCredential
    ) -> Dict[str, Any]:
        """Update an existing page."""
        body: Dict[str, Any] = {}

        if config.title is not None:
            body["title"] = config.title
        if config.content is not None:
            body["content"] = config.content
        if config.status is not None:
            body["status"] = config.status
        if config.parent is not None:
            body["parent"] = config.parent
        if config.slug is not None:
            body["slug"] = config.slug
        if config.menu_order is not None:
            body["menu_order"] = config.menu_order
        if config.featured_media is not None:
            body["featured_media"] = config.featured_media

        return await self._make_request(
            method="POST",
            endpoint=f"/pages/{config.page_id}",
            credentials=credentials,
            json_body=body,
            action_name="update_page",
        )

    async def _handle_delete_page(
        self, config: WordPressDeletePageConfig, credentials: WordPressCredential
    ) -> Dict[str, Any]:
        """Delete a page."""
        params = {}
        if config.force:
            params["force"] = "true"

        return await self._make_request(
            method="DELETE",
            endpoint=f"/pages/{config.page_id}",
            credentials=credentials,
            params=params,
            action_name="delete_page",
        )

    # =========================================================================
    # Media Operation Handlers
    # =========================================================================

    async def _handle_list_media(
        self, config: WordPressListMediaConfig, credentials: WordPressCredential
    ) -> Dict[str, Any]:
        """List media items."""
        params = {}

        if config.context:
            params["context"] = config.context
        if config.page:
            params["page"] = config.page
        if config.per_page:
            params["per_page"] = config.per_page
        if config.search:
            params["search"] = config.search
        if config.media_type:
            params["media_type"] = config.media_type
        if config.mime_type:
            params["mime_type"] = config.mime_type

        return await self._make_request(
            method="GET",
            endpoint="/media",
            credentials=credentials,
            params=params,
            action_name="list_media_items",
        )

    async def _handle_get_media(
        self, config: WordPressGetMediaConfig, credentials: WordPressCredential
    ) -> Dict[str, Any]:
        """Get a single media item by ID."""
        return await self._make_request(
            method="GET",
            endpoint=f"/media/{config.media_id}",
            credentials=credentials,
            action_name="get_media_item",
        )

    async def _handle_upload_media(
        self, config: WordPressUploadMediaConfig, credentials: WordPressCredential
    ) -> Dict[str, Any]:
        """Upload a new media file."""
        # Resolve the field to bytes (accepts a public URL, data: URI, raw
        # base64, or an internal resource UUID; SSRF-guarded).
        from nodes.core.media_resolver import resolve_media_input

        try:
            resolved = await resolve_media_input(config.file_url)
            file_content = resolved.data
            filename = resolved.filename or "upload"
            upload_content_type = resolved.mime_type or "application/octet-stream"
        except Exception as e:
            return {
                "status": "error",
                "action": "upload_media_file",
                "error": f"Failed to resolve file: {str(e)}",
                "status_code": 500,
                "timing_ms": {"api_request": 0},
            }

        # Prepare upload request
        base_url = self._get_api_base_url(credentials)
        url = f"{base_url}/media"

        headers = await self._get_auth_headers(credentials)
        # Remove default Content-Type — will be set based on upload method
        headers.pop("Content-Type", None)

        # Add metadata as headers
        if config.title:
            headers["X-WP-Title"] = config.title
        if config.caption:
            headers["X-WP-Caption"] = config.caption
        if config.alt_text:
            headers["X-WP-Alt-Text"] = config.alt_text
        if config.description:
            headers["X-WP-Description"] = config.description
        if config.post_id:
            headers["X-WP-Post-ID"] = str(config.post_id)

        logger.info(
            f"[WordPressNode] Uploading media: filename={filename}, content_type={upload_content_type}, size={len(file_content)} bytes"
        )

        # WordPress REST API: raw byte upload with Content-Type and Content-Disposition
        headers["Content-Type"] = upload_content_type
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'

        start_time = time.time()

        async with guarded_async_client(timeout=60.0) as client:
            try:
                response = await client.post(
                    url,
                    headers=headers,
                    content=file_content,
                )

                api_time = (time.time() - start_time) * 1000

                if response.status_code >= 400:
                    error_text = response.text
                    try:
                        error_data = response.json()
                        error_message = error_data.get("message", str(error_data))
                    except Exception:
                        error_message = error_text

                    logger.error(f"[WordPressNode] Media upload error: {error_message}")
                    return {
                        "status": "error",
                        "action": "upload_media_file",
                        "error": error_message,
                        "status_code": response.status_code,
                        "timing_ms": {"api_request": round(api_time, 2)},
                    }

                data = response.json()
                return {
                    "status": "success",
                    "action": "upload_media_file",
                    "data": data,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": round(api_time, 2)},
                }

            except Exception as e:
                logger.exception(f"[WordPressNode] Media upload failed: {e}")
                return {
                    "status": "error",
                    "action": "upload_media_file",
                    "error": str(e),
                    "status_code": 500,
                    "timing_ms": {
                        "api_request": round((time.time() - start_time) * 1000, 2)
                    },
                }

    async def _handle_update_media(
        self, config: WordPressUpdateMediaConfig, credentials: WordPressCredential
    ) -> Dict[str, Any]:
        """Update media metadata."""
        body: Dict[str, Any] = {}

        if config.title is not None:
            body["title"] = config.title
        if config.caption is not None:
            body["caption"] = config.caption
        if config.alt_text is not None:
            body["alt_text"] = config.alt_text
        if config.description is not None:
            body["description"] = config.description

        return await self._make_request(
            method="POST",
            endpoint=f"/media/{config.media_id}",
            credentials=credentials,
            json_body=body,
            action_name="update_media_metadata",
        )

    async def _handle_delete_media(
        self, config: WordPressDeleteMediaConfig, credentials: WordPressCredential
    ) -> Dict[str, Any]:
        """Delete a media item."""
        params = {}
        if config.force:
            params["force"] = "true"

        return await self._make_request(
            method="DELETE",
            endpoint=f"/media/{config.media_id}",
            credentials=credentials,
            params=params,
            action_name="delete_media_item",
        )

    # =========================================================================
    # User Operation Handlers
    # =========================================================================

    async def _handle_list_users(
        self, config: WordPressListUsersConfig, credentials: WordPressCredential
    ) -> Dict[str, Any]:
        """List users."""
        params = {}

        if config.context:
            params["context"] = config.context
        if config.page:
            params["page"] = config.page
        if config.per_page:
            params["per_page"] = config.per_page
        if config.search:
            params["search"] = config.search
        if config.roles:
            params["roles"] = config.roles
        if config.order:
            params["order"] = config.order
        if config.orderby:
            params["orderby"] = config.orderby

        return await self._make_request(
            method="GET",
            endpoint="/users",
            credentials=credentials,
            params=params,
            action_name="list_users",
        )

    async def _handle_get_user(
        self, config: WordPressGetUserConfig, credentials: WordPressCredential
    ) -> Dict[str, Any]:
        """Get a single user by ID."""
        params = {}

        if config.context:
            params["context"] = config.context

        return await self._make_request(
            method="GET",
            endpoint=f"/users/{config.user_id}",
            credentials=credentials,
            params=params,
            action_name="get_user",
        )

    async def _handle_create_user(
        self, config: WordPressCreateUserConfig, credentials: WordPressCredential
    ) -> Dict[str, Any]:
        """Create a new user."""
        body: Dict[str, Any] = {
            "username": config.username,
            "email": config.email,
            "password": config.password,
        }

        if config.first_name:
            body["first_name"] = config.first_name
        if config.last_name:
            body["last_name"] = config.last_name
        if config.url:
            body["url"] = config.url
        if config.description:
            body["description"] = config.description
        if config.roles:
            body["roles"] = config.roles

        return await self._make_request(
            method="POST",
            endpoint="/users",
            credentials=credentials,
            json_body=body,
            action_name="create_user",
        )

    async def _handle_update_user(
        self, config: WordPressUpdateUserConfig, credentials: WordPressCredential
    ) -> Dict[str, Any]:
        """Update an existing user."""
        body: Dict[str, Any] = {}

        if config.email is not None:
            body["email"] = config.email
        if config.first_name is not None:
            body["first_name"] = config.first_name
        if config.last_name is not None:
            body["last_name"] = config.last_name
        if config.url is not None:
            body["url"] = config.url
        if config.description is not None:
            body["description"] = config.description
        if config.roles is not None:
            body["roles"] = config.roles

        return await self._make_request(
            method="POST",
            endpoint=f"/users/{config.user_id}",
            credentials=credentials,
            json_body=body,
            action_name="update_user",
        )

    async def _handle_delete_user(
        self, config: WordPressDeleteUserConfig, credentials: WordPressCredential
    ) -> Dict[str, Any]:
        """Delete a user."""
        params = {}
        if config.force:
            params["force"] = "true"
        if config.reassign is not None:
            params["reassign"] = str(config.reassign)

        return await self._make_request(
            method="DELETE",
            endpoint=f"/users/{config.user_id}",
            credentials=credentials,
            params=params,
            action_name="delete_user",
        )

    # =========================================================================
    # Comment Operation Handlers
    # =========================================================================

    async def _handle_list_comments(
        self, config: WordPressListCommentsConfig, credentials: WordPressCredential
    ) -> Dict[str, Any]:
        """List comments."""
        params = {}

        if config.context:
            params["context"] = config.context
        if config.page:
            params["page"] = config.page
        if config.per_page:
            params["per_page"] = config.per_page
        if config.search:
            params["search"] = config.search
        if config.post_id is not None:
            params["post"] = config.post_id
        if config.parent is not None:
            params["parent"] = config.parent
        if config.author is not None:
            params["author"] = config.author
        if config.status:
            params["status"] = config.status
        if config.order:
            params["order"] = config.order
        if config.orderby:
            params["orderby"] = config.orderby

        return await self._make_request(
            method="GET",
            endpoint="/comments",
            credentials=credentials,
            params=params,
            action_name="list_comments",
        )

    async def _handle_get_comment(
        self, config: WordPressGetCommentConfig, credentials: WordPressCredential
    ) -> Dict[str, Any]:
        """Get a single comment by ID."""
        params = {}

        if config.context:
            params["context"] = config.context

        return await self._make_request(
            method="GET",
            endpoint=f"/comments/{config.comment_id}",
            credentials=credentials,
            params=params,
            action_name="get_comment",
        )

    async def _handle_create_comment(
        self, config: WordPressCreateCommentConfig, credentials: WordPressCredential
    ) -> Dict[str, Any]:
        """Create a new comment."""
        body: Dict[str, Any] = {
            "post": config.post_id,
            "content": config.content,
        }

        if config.author_name:
            body["author_name"] = config.author_name
        if config.author_email:
            body["author_email"] = config.author_email
        if config.author_url:
            body["author_url"] = config.author_url
        if config.parent is not None:
            body["parent"] = config.parent
        if config.status:
            body["status"] = config.status

        return await self._make_request(
            method="POST",
            endpoint="/comments",
            credentials=credentials,
            json_body=body,
            action_name="create_post_comment",
        )

    async def _handle_update_comment(
        self, config: WordPressUpdateCommentConfig, credentials: WordPressCredential
    ) -> Dict[str, Any]:
        """Update an existing comment."""
        body: Dict[str, Any] = {}

        if config.content is not None:
            body["content"] = config.content
        if config.status is not None:
            body["status"] = config.status
        if config.author_name is not None:
            body["author_name"] = config.author_name
        if config.author_email is not None:
            body["author_email"] = config.author_email
        if config.author_url is not None:
            body["author_url"] = config.author_url

        return await self._make_request(
            method="POST",
            endpoint=f"/comments/{config.comment_id}",
            credentials=credentials,
            json_body=body,
            action_name="update_comment",
        )

    async def _handle_delete_comment(
        self, config: WordPressDeleteCommentConfig, credentials: WordPressCredential
    ) -> Dict[str, Any]:
        """Delete a comment."""
        params = {}
        if config.force:
            params["force"] = "true"

        return await self._make_request(
            method="DELETE",
            endpoint=f"/comments/{config.comment_id}",
            credentials=credentials,
            params=params,
            action_name="delete_comment",
        )

    # =========================================================================
    # Category Operation Handlers
    # =========================================================================

    async def _handle_list_categories(
        self, config: WordPressListCategoriesConfig, credentials: WordPressCredential
    ) -> Dict[str, Any]:
        """List categories."""
        params = {}

        if config.context:
            params["context"] = config.context
        if config.page:
            params["page"] = config.page
        if config.per_page:
            params["per_page"] = config.per_page
        if config.search:
            params["search"] = config.search
        if config.hide_empty is not None:
            params["hide_empty"] = config.hide_empty
        if config.parent is not None:
            params["parent"] = config.parent
        if config.order:
            params["order"] = config.order
        if config.orderby:
            params["orderby"] = config.orderby

        return await self._make_request(
            method="GET",
            endpoint="/categories",
            credentials=credentials,
            params=params,
            action_name="list_categories",
        )

    async def _handle_get_category(
        self, config: WordPressGetCategoryConfig, credentials: WordPressCredential
    ) -> Dict[str, Any]:
        """Get a single category by ID."""
        params = {}

        if config.context:
            params["context"] = config.context

        return await self._make_request(
            method="GET",
            endpoint=f"/categories/{config.category_id}",
            credentials=credentials,
            params=params,
            action_name="get_category",
        )

    async def _handle_create_category(
        self, config: WordPressCreateCategoryConfig, credentials: WordPressCredential
    ) -> Dict[str, Any]:
        """Create a new category."""
        body: Dict[str, Any] = {
            "name": config.name,
        }

        if config.description:
            body["description"] = config.description
        if config.slug:
            body["slug"] = config.slug
        if config.parent is not None:
            body["parent"] = config.parent

        return await self._make_request(
            method="POST",
            endpoint="/categories",
            credentials=credentials,
            json_body=body,
            action_name="create_category",
        )

    async def _handle_update_category(
        self, config: WordPressUpdateCategoryConfig, credentials: WordPressCredential
    ) -> Dict[str, Any]:
        """Update an existing category."""
        body: Dict[str, Any] = {}

        if config.name is not None:
            body["name"] = config.name
        if config.description is not None:
            body["description"] = config.description
        if config.slug is not None:
            body["slug"] = config.slug
        if config.parent is not None:
            body["parent"] = config.parent

        return await self._make_request(
            method="POST",
            endpoint=f"/categories/{config.category_id}",
            credentials=credentials,
            json_body=body,
            action_name="update_category",
        )

    async def _handle_delete_category(
        self, config: WordPressDeleteCategoryConfig, credentials: WordPressCredential
    ) -> Dict[str, Any]:
        """Delete a category."""
        params = {}
        if config.force:
            params["force"] = "true"

        return await self._make_request(
            method="DELETE",
            endpoint=f"/categories/{config.category_id}",
            credentials=credentials,
            params=params,
            action_name="delete_category",
        )

    # =========================================================================
    # Tag Operation Handlers
    # =========================================================================

    async def _handle_list_tags(
        self, config: WordPressListTagsConfig, credentials: WordPressCredential
    ) -> Dict[str, Any]:
        """List tags."""
        params = {}

        if config.context:
            params["context"] = config.context
        if config.page:
            params["page"] = config.page
        if config.per_page:
            params["per_page"] = config.per_page
        if config.search:
            params["search"] = config.search
        if config.hide_empty is not None:
            params["hide_empty"] = config.hide_empty
        if config.order:
            params["order"] = config.order
        if config.orderby:
            params["orderby"] = config.orderby

        return await self._make_request(
            method="GET",
            endpoint="/tags",
            credentials=credentials,
            params=params,
            action_name="list_tags",
        )

    async def _handle_get_tag(
        self, config: WordPressGetTagConfig, credentials: WordPressCredential
    ) -> Dict[str, Any]:
        """Get a single tag by ID."""
        params = {}

        if config.context:
            params["context"] = config.context

        return await self._make_request(
            method="GET",
            endpoint=f"/tags/{config.tag_id}",
            credentials=credentials,
            params=params,
            action_name="get_tag",
        )

    async def _handle_create_tag(
        self, config: WordPressCreateTagConfig, credentials: WordPressCredential
    ) -> Dict[str, Any]:
        """Create a new tag."""
        body: Dict[str, Any] = {
            "name": config.name,
        }

        if config.description:
            body["description"] = config.description
        if config.slug:
            body["slug"] = config.slug

        return await self._make_request(
            method="POST",
            endpoint="/tags",
            credentials=credentials,
            json_body=body,
            action_name="create_tag",
        )

    async def _handle_update_tag(
        self, config: WordPressUpdateTagConfig, credentials: WordPressCredential
    ) -> Dict[str, Any]:
        """Update an existing tag."""
        body: Dict[str, Any] = {}

        if config.name is not None:
            body["name"] = config.name
        if config.description is not None:
            body["description"] = config.description
        if config.slug is not None:
            body["slug"] = config.slug

        return await self._make_request(
            method="POST",
            endpoint=f"/tags/{config.tag_id}",
            credentials=credentials,
            json_body=body,
            action_name="update_tag",
        )

    async def _handle_delete_tag(
        self, config: WordPressDeleteTagConfig, credentials: WordPressCredential
    ) -> Dict[str, Any]:
        """Delete a tag."""
        params = {}
        if config.force:
            params["force"] = "true"

        return await self._make_request(
            method="DELETE",
            endpoint=f"/tags/{config.tag_id}",
            credentials=credentials,
            params=params,
            action_name="delete_tag",
        )

    # =========================================================================
    # Search Handler
    # =========================================================================

    async def _handle_search(
        self, config: WordPressSearchConfig, credentials: WordPressCredential
    ) -> Dict[str, Any]:
        """Search across all content types."""
        params = {"search": config.search_term}

        if config.context:
            params["context"] = config.context
        if config.page:
            params["page"] = config.page
        if config.per_page:
            params["per_page"] = config.per_page
        if config.search_type:
            params["type"] = config.search_type
        if config.subtype:
            params["subtype"] = config.subtype

        return await self._make_request(
            method="GET",
            endpoint="/search",
            credentials=credentials,
            params=params,
            action_name="search_content",
        )

    # =========================================================================
    # Settings Handlers
    # =========================================================================

    async def _handle_get_settings(
        self, config: WordPressGetSettingsConfig, credentials: WordPressCredential
    ) -> Dict[str, Any]:
        """Get site settings."""
        return await self._make_request(
            method="GET",
            endpoint="/settings",
            credentials=credentials,
            action_name="get_site_settings",
        )

    async def _handle_update_settings(
        self, config: WordPressUpdateSettingsConfig, credentials: WordPressCredential
    ) -> Dict[str, Any]:
        """Update site settings."""
        body: Dict[str, Any] = {}

        if config.title is not None:
            body["title"] = config.title
        if config.description is not None:
            body["description"] = config.description
        if config.timezone is not None:
            body["timezone"] = config.timezone
        if config.date_format is not None:
            body["date_format"] = config.date_format
        if config.time_format is not None:
            body["time_format"] = config.time_format
        if config.start_of_week is not None:
            body["start_of_week"] = config.start_of_week
        if config.language is not None:
            body["language"] = config.language
        if config.use_smilies is not None:
            body["use_smilies"] = config.use_smilies
        if config.default_category is not None:
            body["default_category"] = config.default_category
        if config.default_post_format is not None:
            body["default_post_format"] = config.default_post_format
        if config.posts_per_page is not None:
            body["posts_per_page"] = config.posts_per_page

        return await self._make_request(
            method="POST",
            endpoint="/settings",
            credentials=credentials,
            json_body=body,
            action_name="update_site_settings",
        )
