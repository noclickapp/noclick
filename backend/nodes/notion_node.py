"""
Notion API automation node.

Provides workflow integration with Notion for operations including:
- Search: Find pages and databases by title
- Database Operations: query, retrieve, create, update databases
- Page Operations: retrieve, create, update pages
- Block Operations: retrieve, list children, append children, update, delete blocks
- User Operations: list users, retrieve user, get current bot user
- Comment Operations: create, retrieve, list comments

Authentication: Internal Integration Token or OAuth 2.0
API Base URL: https://api.notion.com/v1
Documentation: https://developers.notion.com
Rate Limit: 3 requests per second average
"""

import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, ConfigDict, Discriminator, Field
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from utils.ssrf import guarded_async_client
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.oauth.notion_oauth import is_token_expired, refresh_access_token
from nodes.core.dynamic_options import require_credential_token
from nodes.scopes.notion import NOTION_SCOPES

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_API_VERSION = "2022-06-28"

# ============================================================================
# Credential Schema
# ============================================================================


class NotionIntegrationTokenCredential(BaseModel):
    """
    Internal Integration Token credential for Notion.

    Create an internal integration at: https://www.notion.so/my-integrations
    Then share the desired pages/databases with your integration.
    """

    credential_type: Literal["notion_integration_token"] = Field(
        "notion_integration_token", json_schema_extra={"ui:hidden": True}
    )
    integration_token: str = Field(
        ...,
        title="Internal Integration Token",
        description="Your Notion Internal Integration Token (starts with 'secret_')",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={"x-credential-url": "https://www.notion.so/my-integrations"}
    )


class NotionOAuthCredential(BaseModel):
    """
    OAuth 2.0 credential for Notion.
    Tokens are obtained via OAuth flow, not entered manually.

    Register OAuth app at: https://www.notion.so/my-integrations
    """

    credential_type: Literal["notion_oauth"] = Field(
        "notion_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ..., title="Access Token", description="OAuth 2.0 access token from Notion"
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
    workspace_id: Optional[str] = Field(
        None, title="Workspace ID", description="The Notion workspace ID"
    )
    workspace_name: Optional[str] = Field(
        None, title="Workspace Name", description="The Notion workspace name"
    )
    bot_id: Optional[str] = Field(
        None, title="Bot ID", description="The bot user ID for this integration"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "notion",
            "x-oauth-scopes": [],  # Notion uses page-level permissions, not scopes
        }
    )


# Union type for credentials - supports both Integration Token and OAuth
NotionCredential = Union[NotionOAuthCredential, NotionIntegrationTokenCredential]


# ============================================================================
# Search Operation Config
# ============================================================================


class NotionSearchConfig(BaseModel):
    """Search pages and databases by title"""

    operation: Literal["search_pages_and_databases"] = Field(
        "search_pages_and_databases",
        json_schema_extra={
            "const": "search_pages_and_databases",
            "ui:hidden": True,
            "x-category": "Workspace",
            "x-is-trigger": False,
            "x-display-name": "Search Pages and Databases",
            "x-keywords": [
                "search workspace",
                "find page by title",
                "search notion",
                "look up database",
                "global search",
                "find content",
            ],
        },
        title="Search Pages and Databases",
    )
    query: Optional[str] = Field(
        None,
        title="Search Query",
        description="Text to search for in page and database titles. Leave empty to list all accessible content.",
    )
    filter_type: Optional[str] = Field(
        None,
        title="Filter Type",
        description="Filter results by object type",
        json_schema_extra={"enum": ["page", "database"]},
    )
    sort_direction: Optional[str] = Field(
        "descending",
        title="Sort Direction",
        description="Sort by last edited time",
        json_schema_extra={"enum": ["ascending", "descending"]},
    )
    page_size: Optional[int] = Field(
        100,
        title="Page Size",
        description="Number of results per page (max 100)",
        ge=1,
        le=100,
    )
    start_cursor: Optional[str] = Field(
        None,
        title="Start Cursor",
        description="Pagination cursor from previous response",
    )


# ============================================================================
# Database Operation Configs
# ============================================================================


class NotionQueryDatabaseConfig(BaseModel):
    """Query a database to retrieve pages"""

    operation: Literal["query_notion_database"] = Field(
        "query_notion_database",
        json_schema_extra={
            "const": "query_notion_database",
            "ui:hidden": True,
            "x-category": "Database",
            "x-is-trigger": False,
            "x-display-name": "Query Notion Database",
            "x-keywords": [
                "query database rows",
                "get database pages",
                "filter database",
                "list database entries",
                "retrieve database items",
                "database query",
            ],
        },
        title="Query Notion Database",
    )
    database_id: str = Field(
        ...,
        title="Database",
        description="The ID of the database to query",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "database_id",
                "placeholder": "Select a database...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste database ID",
            },
            "x-resource-type": "notion_database",
        },
    )
    filter: Optional[str] = Field(
        None,
        title="Filter",
        description="JSON filter object for querying (see Notion docs for filter syntax)",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": '{"property": "Status", "select": {"equals": "Done"}}',
        },
    )
    sorts: Optional[str] = Field(
        None,
        title="Sorts",
        description="JSON array of sort objects",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": '[{"property": "Created", "direction": "descending"}]',
        },
    )
    page_size: Optional[int] = Field(
        100,
        title="Page Size",
        description="Number of results per page (max 100)",
        ge=1,
        le=100,
    )
    start_cursor: Optional[str] = Field(
        None,
        title="Start Cursor",
        description="Pagination cursor from previous response",
    )


class NotionRetrieveDatabaseConfig(BaseModel):
    """Retrieve a database's metadata and schema"""

    operation: Literal["fetch_database_metadata"] = Field(
        "fetch_database_metadata",
        json_schema_extra={
            "const": "fetch_database_metadata",
            "ui:hidden": True,
            "x-category": "Database",
            "x-is-trigger": False,
            "x-display-name": "Fetch Database Metadata",
            "x-keywords": [
                "get database schema",
                "database properties",
                "read database structure",
                "database columns",
                "retrieve schema",
            ],
        },
        title="Fetch Database Metadata",
    )
    database_id: str = Field(
        ...,
        title="Database",
        description="The ID of the database to retrieve",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "database_id",
                "placeholder": "Select a database...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste database ID",
            },
            "x-resource-type": "notion_database",
        },
    )


class NotionCreateDatabaseConfig(BaseModel):
    """Create a new database as a child of a page"""

    operation: Literal["create_page_database"] = Field(
        "create_page_database",
        json_schema_extra={
            "const": "create_page_database",
            "ui:hidden": True,
            "x-category": "Database",
            "x-is-trigger": False,
            "x-display-name": "Create Page Database",
            "x-keywords": [
                "create database",
                "new database",
                "add database under page",
                "make inline database",
                "create child database",
            ],
            "x-creates-resource": True,
            "x-resource-type": "notion_database",
            "x-resource-id-path": "data.id",
        },
        title="Create Page Database",
    )
    parent_page_id: str = Field(
        ...,
        title="Parent Page",
        description="The parent page for the new database",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "page_id",
                "placeholder": "Select a page...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste page ID",
            },
            "x-resource-type": "notion_page",
        },
    )
    title: str = Field(
        ..., title="Database Title", description="Title for the new database"
    )
    properties: str = Field(
        ...,
        title="Properties Schema",
        description="JSON object defining database properties/columns",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": '{"Name": {"title": {}}, "Status": {"select": {"options": [{"name": "To Do"}, {"name": "Done"}]}}}',
        },
    )


class NotionUpdateDatabaseConfig(BaseModel):
    """Update a database's title, description, or properties"""

    operation: Literal["update_database_metadata"] = Field(
        "update_database_metadata",
        json_schema_extra={
            "const": "update_database_metadata",
            "ui:hidden": True,
            "x-category": "Database",
            "x-is-trigger": False,
            "x-display-name": "Update Database Metadata",
            "x-keywords": [
                "rename database",
                "edit database schema",
                "change database title",
                "modify database properties",
                "update database columns",
            ],
        },
        title="Update Database Metadata",
    )
    database_id: str = Field(
        ...,
        title="Database",
        description="The ID of the database to update",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "database_id",
                "placeholder": "Select a database...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste database ID",
            },
            "x-resource-type": "notion_database",
        },
    )
    title: Optional[str] = Field(
        None, title="New Title", description="New title for the database"
    )
    description: Optional[str] = Field(
        None, title="Description", description="New description for the database"
    )
    properties: Optional[str] = Field(
        None,
        title="Properties Updates",
        description="JSON object with property updates",
        json_schema_extra={"ui:widget": "textarea"},
    )


# ============================================================================
# Page Operation Configs
# ============================================================================


class NotionRetrievePageConfig(BaseModel):
    """Retrieve a page's properties"""

    operation: Literal["fetch_page_properties"] = Field(
        "fetch_page_properties",
        json_schema_extra={
            "const": "fetch_page_properties",
            "ui:hidden": True,
            "x-category": "Page",
            "x-is-trigger": False,
            "x-display-name": "Fetch Page Properties",
            "x-keywords": [
                "get page properties",
                "read page fields",
                "retrieve page metadata",
                "page property values",
            ],
        },
        title="Fetch Page Properties",
    )
    page_id: str = Field(
        ...,
        title="Page",
        description="The page to retrieve",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "page_id",
                "placeholder": "Select a page...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste page ID",
            },
            "x-resource-type": "notion_page",
        },
    )


class NotionCreatePageConfig(BaseModel):
    """Create a new page in a database or as a child of another page"""

    operation: Literal["create_notion_page"] = Field(
        "create_notion_page",
        json_schema_extra={
            "const": "create_notion_page",
            "ui:hidden": True,
            "x-category": "Page",
            "x-is-trigger": False,
            "x-display-name": "Create Notion Page",
            "x-keywords": [
                "create page",
                "new page",
                "add page to database",
                "make subpage",
                "new note",
                "add doc",
            ],
        },
        title="Create Notion Page",
    )
    parent_type: str = Field(
        "database_id",
        title="Parent Type",
        description="Type of parent",
        json_schema_extra={"enum": ["database_id", "page_id"]},
    )
    parent_id: str = Field(
        ...,
        title="Parent Page/Database",
        description="The parent page or database for the new page",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "page_id",
                "placeholder": "Select a page...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste page/database ID",
            },
        },
    )
    properties: str = Field(
        ...,
        title="Properties",
        description="JSON object with page properties (required for database pages)",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": '{"Name": {"title": [{"text": {"content": "New Page"}}]}}',
        },
    )
    children: Optional[str] = Field(
        None,
        title="Content Blocks",
        description="JSON array of block objects for page content",
        json_schema_extra={"ui:widget": "textarea"},
    )
    icon: Optional[str] = Field(
        None, title="Icon", description="Emoji icon for the page (e.g., '📝')"
    )
    cover: Optional[str] = Field(
        None,
        title="Cover",
        description="The cover image to send — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}).",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": "image/*"},
    )


class NotionUpdatePageConfig(BaseModel):
    """Update a page's properties, icon, or cover"""

    operation: Literal["update_page_properties"] = Field(
        "update_page_properties",
        json_schema_extra={
            "const": "update_page_properties",
            "ui:hidden": True,
            "x-category": "Page",
            "x-is-trigger": False,
            "x-display-name": "Update Page Properties",
            "x-keywords": [
                "edit page properties",
                "set page icon",
                "change page cover",
                "update page fields",
                "modify page metadata",
            ],
        },
        title="Update Page Properties",
    )
    page_id: str = Field(
        ...,
        title="Page",
        description="The page to update",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "page_id",
                "placeholder": "Select a page...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste page ID",
            },
            "x-resource-type": "notion_page",
        },
    )
    properties: Optional[str] = Field(
        None,
        title="Properties",
        description="JSON object with property updates",
        json_schema_extra={"ui:widget": "textarea"},
    )
    archived: Optional[bool] = Field(
        None, title="Archive Page", description="Set to true to move page to trash"
    )
    icon: Optional[str] = Field(
        None, title="Icon", description="Emoji icon for the page"
    )
    cover: Optional[str] = Field(
        None,
        title="Cover",
        description="The cover image to send — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}).",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": "image/*"},
    )


# ============================================================================
# Block Operation Configs
# ============================================================================


class NotionRetrieveBlockConfig(BaseModel):
    """Retrieve a block"""

    operation: Literal["fetch_notion_block"] = Field(
        "fetch_notion_block",
        json_schema_extra={
            "const": "fetch_notion_block",
            "ui:hidden": True,
            "x-category": "Block",
            "x-is-trigger": False,
            "x-display-name": "Fetch Notion Block",
            "x-keywords": ["get block", "read single block", "retrieve block by id"],
        },
        title="Fetch Notion Block",
    )
    block_id: str = Field(
        ..., title="Block ID", description="The ID of the block to retrieve"
    )


class NotionRetrieveBlockChildrenConfig(BaseModel):
    """Retrieve a block's children"""

    operation: Literal["fetch_block_children"] = Field(
        "fetch_block_children",
        json_schema_extra={
            "const": "fetch_block_children",
            "ui:hidden": True,
            "x-category": "Block",
            "x-is-trigger": False,
            "x-display-name": "Fetch Block Children",
            "x-keywords": [
                "get block children",
                "read page content",
                "list child blocks",
                "retrieve nested blocks",
                "read page body",
            ],
        },
        title="Fetch Block Children",
    )
    block_id: str = Field(
        ...,
        title="Block/Page",
        description="The block or page to get children from",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "page_id",
                "placeholder": "Select a page...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste block/page ID",
            },
        },
    )
    page_size: Optional[int] = Field(
        100,
        title="Page Size",
        description="Number of blocks per page (max 100)",
        ge=1,
        le=100,
    )
    start_cursor: Optional[str] = Field(
        None,
        title="Start Cursor",
        description="Pagination cursor from previous response",
    )


class NotionAppendBlockChildrenConfig(BaseModel):
    """Append new children blocks to a parent block"""

    operation: Literal["append_children_to_block"] = Field(
        "append_children_to_block",
        json_schema_extra={
            "const": "append_children_to_block",
            "ui:hidden": True,
            "x-category": "Block",
            "x-is-trigger": False,
            "x-display-name": "Append Children to Block",
            "x-keywords": [
                "add content to page",
                "append blocks",
                "insert paragraph",
                "add block to page",
                "write to page",
                "add text",
            ],
        },
        title="Append Children to Block",
    )
    block_id: str = Field(
        ...,
        title="Block/Page",
        description="The parent block or page to append children to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "page_id",
                "placeholder": "Select a page...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste block/page ID",
            },
        },
    )
    children: str = Field(
        ...,
        title="Children Blocks",
        description="JSON array of block objects to append",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": '[{"type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": "Hello World"}}]}}]',
        },
    )
    after: Optional[str] = Field(
        None, title="After Block ID", description="Append after this specific block ID"
    )


class NotionUpdateBlockConfig(BaseModel):
    """Update a block's content"""

    operation: Literal["update_block_content"] = Field(
        "update_block_content",
        json_schema_extra={
            "const": "update_block_content",
            "ui:hidden": True,
            "x-category": "Block",
            "x-is-trigger": False,
            "x-display-name": "Update Block Content",
            "x-keywords": [
                "edit block",
                "change block text",
                "modify block content",
                "rewrite block",
            ],
        },
        title="Update Block Content",
    )
    block_id: str = Field(
        ..., title="Block ID", description="The ID of the block to update"
    )
    block_type: str = Field(
        ...,
        title="Block Type",
        description="The type of block (paragraph, heading_1, to_do, etc.)",
    )
    content: str = Field(
        ...,
        title="Block Content",
        description="JSON object with the block type's content",
        json_schema_extra={"ui:widget": "textarea"},
    )
    archived: Optional[bool] = Field(
        None,
        title="Archive Block",
        description="Set to true to archive/delete the block",
    )


class NotionDeleteBlockConfig(BaseModel):
    """Delete (archive) a block"""

    operation: Literal["delete_notion_block"] = Field(
        "delete_notion_block",
        json_schema_extra={
            "const": "delete_notion_block",
            "ui:hidden": True,
            "x-category": "Block",
            "x-is-trigger": False,
            "x-display-name": "Delete Notion Block",
            "x-keywords": [
                "delete block",
                "archive block",
                "remove block",
                "trash block",
            ],
        },
        title="Delete Notion Block",
    )
    block_id: str = Field(
        ..., title="Block ID", description="The ID of the block to delete"
    )


# ============================================================================
# User Operation Configs
# ============================================================================


class NotionListUsersConfig(BaseModel):
    """List all users in the workspace"""

    operation: Literal["list_workspace_users"] = Field(
        "list_workspace_users",
        json_schema_extra={
            "const": "list_workspace_users",
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "List Workspace Users",
            "x-keywords": [
                "list members",
                "get all users",
                "workspace people",
                "list teammates",
            ],
        },
        title="List Workspace Users",
    )
    page_size: Optional[int] = Field(
        100,
        title="Page Size",
        description="Number of users per page (max 100)",
        ge=1,
        le=100,
    )
    start_cursor: Optional[str] = Field(
        None,
        title="Start Cursor",
        description="Pagination cursor from previous response",
    )


class NotionRetrieveUserConfig(BaseModel):
    """Retrieve a user by ID"""

    operation: Literal["fetch_workspace_user"] = Field(
        "fetch_workspace_user",
        json_schema_extra={
            "const": "fetch_workspace_user",
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Fetch Workspace User",
            "x-keywords": [
                "get user by id",
                "retrieve member",
                "look up person",
                "fetch teammate",
            ],
        },
        title="Fetch Workspace User",
    )
    user_id: str = Field(
        ...,
        title="User",
        description="The workspace user to retrieve",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "user_id",
                "placeholder": "Select a user...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste user ID",
            },
        },
    )


class NotionRetrieveBotUserConfig(BaseModel):
    """Retrieve the bot user for the current integration"""

    operation: Literal["fetch_bot_integration_user"] = Field(
        "fetch_bot_integration_user",
        json_schema_extra={
            "const": "fetch_bot_integration_user",
            "ui:hidden": True,
            "x-category": "User",
            "x-is-trigger": False,
            "x-display-name": "Fetch Bot Integration User",
            "x-keywords": [
                "get bot user",
                "integration identity",
                "whoami",
                "current bot",
                "my integration",
            ],
        },
        title="Fetch Bot Integration User",
    )


# ============================================================================
# Comment Operation Configs
# ============================================================================


class NotionCreateCommentConfig(BaseModel):
    """Create a comment on a page or in an existing discussion thread"""

    operation: Literal["create_page_comment"] = Field(
        "create_page_comment",
        json_schema_extra={
            "const": "create_page_comment",
            "ui:hidden": True,
            "x-category": "Comment",
            "x-is-trigger": False,
            "x-display-name": "Create Page Comment",
            "x-keywords": [
                "add comment",
                "comment on page",
                "reply in discussion",
                "post comment",
                "leave a note",
            ],
        },
        title="Create Page Comment",
    )
    parent_type: str = Field(
        "page_id",
        title="Parent Type",
        description="Type of parent to comment on",
        json_schema_extra={"enum": ["page_id", "discussion_id"]},
    )
    parent_id: str = Field(
        ...,
        title="Parent Page/Discussion",
        description="The page or discussion thread to comment on",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "page_id",
                "placeholder": "Select a page...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste page/discussion ID",
            },
        },
    )
    rich_text: str = Field(
        ...,
        title="Comment Content",
        description="JSON array of rich text objects for the comment content",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": '[{"type": "text", "text": {"content": "This is a comment"}}]',
        },
    )


class NotionRetrieveCommentConfig(BaseModel):
    """Retrieve a comment by its ID"""

    operation: Literal["fetch_page_comment"] = Field(
        "fetch_page_comment",
        json_schema_extra={
            "const": "fetch_page_comment",
            "ui:hidden": True,
            "x-category": "Comment",
            "x-is-trigger": False,
            "x-display-name": "Fetch Page Comment",
            "x-keywords": [
                "get comment",
                "retrieve comment by id",
                "read single comment",
            ],
        },
        title="Fetch Page Comment",
    )
    comment_id: str = Field(
        ..., title="Comment ID", description="The ID of the comment to retrieve"
    )


class NotionListCommentsConfig(BaseModel):
    """List comments on a block or page"""

    operation: Literal["list_block_comments"] = Field(
        "list_block_comments",
        json_schema_extra={
            "const": "list_block_comments",
            "ui:hidden": True,
            "x-category": "Comment",
            "x-is-trigger": False,
            "x-display-name": "List Block Comments",
            "x-keywords": [
                "list comments",
                "get page comments",
                "read comment thread",
                "comments on block",
            ],
        },
        title="List Block Comments",
    )
    block_id: str = Field(
        ...,
        title="Block/Page",
        description="The block or page to list comments from",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "page_id",
                "placeholder": "Select a page...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste block/page ID",
            },
        },
    )
    page_size: Optional[int] = Field(
        100,
        title="Page Size",
        description="Number of comments per page (max 100)",
        ge=1,
        le=100,
    )
    start_cursor: Optional[str] = Field(
        None,
        title="Start Cursor",
        description="Pagination cursor from previous response",
    )


class NotionUpdateCommentConfig(BaseModel):
    """Update a comment's rich text content"""

    operation: Literal["update_page_comment"] = Field(
        "update_page_comment",
        json_schema_extra={
            "const": "update_page_comment",
            "ui:hidden": True,
            "x-category": "Comment",
            "x-is-trigger": False,
            "x-display-name": "Update Page Comment",
            "x-keywords": [
                "edit comment",
                "change comment text",
                "modify comment",
                "update discussion reply",
            ],
        },
        title="Update Page Comment",
    )
    comment_id: str = Field(
        ..., title="Comment ID", description="The ID of the comment to update"
    )
    rich_text: str = Field(
        ...,
        title="New Content",
        description="JSON array of rich text objects for the updated comment",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": '[{"type": "text", "text": {"content": "Updated comment text"}}]',
        },
    )


class NotionDeleteCommentConfig(BaseModel):
    """Delete a comment"""

    operation: Literal["delete_page_comment"] = Field(
        "delete_page_comment",
        json_schema_extra={
            "const": "delete_page_comment",
            "ui:hidden": True,
            "x-category": "Comment",
            "x-is-trigger": False,
            "x-display-name": "Delete Page Comment",
            "x-keywords": [
                "delete comment",
                "remove comment",
                "erase comment",
                "trash comment",
            ],
        },
        title="Delete Page Comment",
    )
    comment_id: str = Field(
        ..., title="Comment ID", description="The ID of the comment to delete"
    )


# ============================================================================
# Page Property Operation Configs
# ============================================================================


class NotionRetrievePagePropertyConfig(BaseModel):
    """Retrieve a single property value from a page"""

    operation: Literal["fetch_page_property"] = Field(
        "fetch_page_property",
        json_schema_extra={
            "const": "fetch_page_property",
            "ui:hidden": True,
            "x-category": "Page",
            "x-is-trigger": False,
            "x-display-name": "Fetch Page Property",
            "x-keywords": [
                "get page property value",
                "read single property",
                "retrieve property item",
                "page field value",
            ],
        },
        title="Fetch Page Property",
    )
    page_id: str = Field(
        ...,
        title="Page",
        description="The page to retrieve a property from",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "page_id",
                "placeholder": "Select a page...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste page ID",
            },
            "x-resource-type": "notion_page",
        },
    )
    property_id: str = Field(
        ...,
        title="Property ID or Name",
        description="The ID or name of the property to retrieve",
    )
    page_size: Optional[int] = Field(
        None,
        title="Page Size",
        description="For paginated properties (rollup, relation, people, rich_text, title). Max 100.",
        ge=1,
        le=100,
    )
    start_cursor: Optional[str] = Field(
        None,
        title="Start Cursor",
        description="Pagination cursor for paginated properties",
    )


# ============================================================================
# View Operation Configs
# ============================================================================


class NotionListViewsConfig(BaseModel):
    """List all views for a database"""

    operation: Literal["list_database_views"] = Field(
        "list_database_views",
        json_schema_extra={
            "const": "list_database_views",
            "ui:hidden": True,
            "x-category": "View",
            "x-is-trigger": False,
            "x-display-name": "List Database Views",
            "x-keywords": [
                "list views",
                "get database views",
                "show views",
                "list table views",
                "board gallery calendar view",
            ],
        },
        title="List Database Views",
    )
    database_id: str = Field(
        ...,
        title="Database",
        description="The database to list views for",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "database_id",
                "placeholder": "Select a database...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste database ID",
            },
            "x-resource-type": "notion_database",
        },
    )
    page_size: Optional[int] = Field(
        100,
        title="Page Size",
        description="Number of views per page (max 100)",
        ge=1,
        le=100,
    )
    start_cursor: Optional[str] = Field(
        None, title="Start Cursor", description="Pagination cursor"
    )


class NotionRetrieveViewConfig(BaseModel):
    """Retrieve a specific database view"""

    operation: Literal["fetch_database_view"] = Field(
        "fetch_database_view",
        json_schema_extra={
            "const": "fetch_database_view",
            "ui:hidden": True,
            "x-category": "View",
            "x-is-trigger": False,
            "x-display-name": "Fetch Database View",
            "x-keywords": [
                "get view by id",
                "retrieve view config",
                "read view filters",
                "fetch specific view",
            ],
        },
        title="Fetch Database View",
    )
    view_id: str = Field(
        ..., title="View ID", description="The ID of the view to retrieve"
    )


class NotionUpdateViewConfig(BaseModel):
    """Update a database view's name or layout"""

    operation: Literal["update_database_view"] = Field(
        "update_database_view",
        json_schema_extra={
            "const": "update_database_view",
            "ui:hidden": True,
            "x-category": "View",
            "x-is-trigger": False,
            "x-display-name": "Update Database View",
            "x-keywords": [
                "rename view",
                "edit view layout",
                "change view name",
                "modify view filters",
                "update board view",
            ],
        },
        title="Update Database View",
    )
    view_id: str = Field(
        ..., title="View ID", description="The ID of the view to update"
    )
    name: Optional[str] = Field(
        None, title="Name", description="New name for the view"
    )
    layout: Optional[str] = Field(
        None,
        title="Layout Type",
        description="View layout type",
        json_schema_extra={
            "enum": ["table", "board", "gallery", "list", "calendar", "timeline"]
        },
    )
    filters: Optional[str] = Field(
        None,
        title="Filters",
        description="JSON object with filter configuration",
        json_schema_extra={"ui:widget": "textarea"},
    )
    sorts: Optional[str] = Field(
        None,
        title="Sorts",
        description="JSON array of sort configurations",
        json_schema_extra={"ui:widget": "textarea"},
    )


# ============================================================================
# File Upload / Async Task Configs
# ============================================================================


class NotionCreateFileUploadConfig(BaseModel):
    """Initiate a file upload and get an upload URL"""

    operation: Literal["create_file_upload"] = Field(
        "create_file_upload",
        json_schema_extra={
            "const": "create_file_upload",
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Create File Upload",
            "x-keywords": [
                "upload file to notion",
                "attach file",
                "file upload initiate",
                "create file object",
                "upload attachment",
            ],
        },
        title="Create File Upload",
    )
    filename: str = Field(
        ...,
        title="Filename",
        description="Name of the file including extension (e.g. report.pdf)",
    )
    content_type: str = Field(
        ...,
        title="Content Type",
        description="MIME type of the file (e.g. application/pdf, image/png)",
        json_schema_extra={
            "placeholder": "application/pdf",
        },
    )
    file_url: Optional[str] = Field(
        None,
        title="File URL",
        description="If provided, the file will be downloaded from this URL and uploaded to Notion",
    )
    parent_page_id: Optional[str] = Field(
        None,
        title="Parent Page",
        description="Optional page to associate the file with",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "page_id",
                "placeholder": "Select a page...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste page ID",
            },
            "x-resource-type": "notion_page",
        },
    )


class NotionGetAsyncTaskConfig(BaseModel):
    """Get the status of an asynchronous Notion task"""

    operation: Literal["get_async_task_status"] = Field(
        "get_async_task_status",
        json_schema_extra={
            "const": "get_async_task_status",
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Get Async Task Status",
            "x-keywords": [
                "check task status",
                "get async task",
                "poll task",
                "async operation status",
                "file upload status",
            ],
        },
        title="Get Async Task Status",
    )
    task_id: str = Field(
        ..., title="Task ID", description="The ID of the async task to check"
    )


# ============================================================================
# Additional Poll Trigger Configs
# ============================================================================


class NotionOnPageCreatedConfig(PollTriggerConfigBase):
    """Trigger: fires when new pages are created in the workspace."""

    operation: Literal["on_page_created"] = Field(
        "on_page_created",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Page Created",
            "x-keywords": [
                "when new page created",
                "on new notion page",
                "watch for new pages",
                "trigger on page creation",
                "new page added",
            ],
        },
        title="On Page Created",
    )
    query: Optional[str] = Field(
        None,
        title="Search Query",
        description="Optional title filter — only fire for pages matching this query",
    )


class NotionOnPageUpdatedConfig(PollTriggerConfigBase):
    """Trigger: fires when existing pages are updated."""

    operation: Literal["on_page_updated"] = Field(
        "on_page_updated",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Page Updated",
            "x-keywords": [
                "when page edited",
                "on page change",
                "watch page updates",
                "trigger on page edit",
                "page modified",
            ],
        },
        title="On Page Updated",
    )
    query: Optional[str] = Field(
        None,
        title="Search Query",
        description="Optional title filter — only fire for pages matching this query",
    )


class NotionOnCommentCreatedConfig(PollTriggerConfigBase):
    """Trigger: fires when new comments appear on a specific block or page."""

    operation: Literal["on_comment_created"] = Field(
        "on_comment_created",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Comment Created",
            "x-keywords": [
                "when new comment",
                "on comment added",
                "watch page comments",
                "trigger on comment",
                "new discussion reply",
            ],
        },
        title="On Comment Created",
    )
    block_id: str = Field(
        ...,
        title="Block/Page",
        description="The block or page to watch for new comments",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "page_id",
                "placeholder": "Select a page...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste block/page ID",
            },
        },
    )


class NotionOnDatabaseCreatedConfig(PollTriggerConfigBase):
    """Trigger: fires when new databases are created in the workspace."""

    operation: Literal["on_database_created"] = Field(
        "on_database_created",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Database Created",
            "x-keywords": [
                "when new database created",
                "on database added",
                "watch for new databases",
                "trigger on database creation",
                "new notion database",
            ],
        },
        title="On Database Created",
    )
    query: Optional[str] = Field(
        None,
        title="Search Query",
        description="Optional title filter — only fire for databases matching this query",
    )


# ============================================================================
# Discriminated Union
# ============================================================================


class NotionOnDatabaseItemConfig(PollTriggerConfigBase):
    """Trigger: polls a Notion database and fires for new or updated items."""

    operation: Literal["on_database_item"] = Field(
        "on_database_item",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Database Item",
            "x-keywords": [
                "when new database item",
                "on page added",
                "watch notion database",
                "new row in database",
                "database item updated",
                "trigger on notion",
            ],
        },
        title="On Database Item",
    )
    database_id: str = Field(
        ...,
        title="Database",
        description="The Notion database to watch",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "database_id",
                "placeholder": "Select a database...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a database ID",
            },
            "x-resource-type": "notion_database",
        },
    )


NotionConfig = Annotated[
    Union[
        # Triggers (5)
        NotionOnDatabaseItemConfig,
        NotionOnPageCreatedConfig,
        NotionOnPageUpdatedConfig,
        NotionOnCommentCreatedConfig,
        NotionOnDatabaseCreatedConfig,
        # Search (1)
        NotionSearchConfig,
        # Database operations (4)
        NotionQueryDatabaseConfig,
        NotionRetrieveDatabaseConfig,
        NotionCreateDatabaseConfig,
        NotionUpdateDatabaseConfig,
        # Page operations (4)
        NotionRetrievePageConfig,
        NotionRetrievePagePropertyConfig,
        NotionCreatePageConfig,
        NotionUpdatePageConfig,
        # Block operations (5)
        NotionRetrieveBlockConfig,
        NotionRetrieveBlockChildrenConfig,
        NotionAppendBlockChildrenConfig,
        NotionUpdateBlockConfig,
        NotionDeleteBlockConfig,
        # User operations (3)
        NotionListUsersConfig,
        NotionRetrieveUserConfig,
        NotionRetrieveBotUserConfig,
        # Comment operations (5)
        NotionCreateCommentConfig,
        NotionRetrieveCommentConfig,
        NotionListCommentsConfig,
        NotionUpdateCommentConfig,
        NotionDeleteCommentConfig,
        # View operations (3)
        NotionListViewsConfig,
        NotionRetrieveViewConfig,
        NotionUpdateViewConfig,
        # File / async task (2)
        NotionCreateFileUploadConfig,
        NotionGetAsyncTaskConfig,
    ],
    Discriminator("operation"),
]


# ============================================================================
# Full Node Configuration
# ============================================================================


class NotionNodeConfig(NodeConfig[NotionConfig, NotionCredential]):
    """Full configuration for Notion node including credentials"""

    pass


# ============================================================================
# Node Implementation
# ============================================================================


class NotionNode(ScheduledPollTriggerMixin, WorkflowNode):
    """
    Notion automation node.

    Executes Notion API operations for workflow automation.
    Supports 32 operations across search, databases, pages, blocks, users,
    comments, views, file uploads, async tasks, and 5 poll triggers.
    """

    edit_examples = [
        "Create page in projects database with title and due date",
        "Query database for status=Done and archive all matched pages",
        "Search for meeting notes by title and append attendees list",
        "Append paragraph block with formatted text to page content",
        "Create comment on page and mention team members @user",
        "Update database properties and retrieve all custom field values",
        "List all comments on ticket page and create follow-up task",
    ]

    scope_registry = NOTION_SCOPES
    connection_evidence = ConnectionEvidence(
        field="page_id",
        noun="pages",
    )

    @classmethod
    def get_config_model(cls):
        """Return the Pydantic model for node configuration."""
        return NotionNodeConfig

    async def _trigger_on_database_item(self, config, credentials) -> Dict[str, Any]:
        """Poll a database and emit items new or updated since the last poll.

        Dedup keys combine the page id with ``last_edited_time`` so an edit to
        an existing item fires the trigger again.
        """
        body = {
            "sorts": [{"timestamp": "last_edited_time", "direction": "descending"}],
            "page_size": 100,
        }
        result = await self._make_request(
            "POST",
            f"/databases/{config.database_id}/query",
            credentials,
            json_body=body,
            action_name="on_database_item",
        )
        if result.get("status") == "error":
            raise ValueError(
                f"Notion database query failed: "
                f"{result.get('error') or result.get('data')}"
            )
        pages = (result.get("data") or {}).get("results", [])

        def _item_id(page):
            pid = page.get("id")
            return f"{pid}:{page.get('last_edited_time', '')}" if pid else None

        new_items = await self._filter_unseen(pages, _item_id)
        return {"items": new_items, "new_item_count": len(new_items)}

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Load dynamic options for dropdown fields.

        Args:
            field_name: Name of the field needing options
            credential_data: Decrypted credential data
            context: Additional context
            page_token: Cursor for paginated results (passed through to Notion search)
            search: Search term — passed to Notion search's native ``query`` param
                    so results narrow upstream rather than client-side post-filter.

        Returns:
            List of option dicts with 'value' and 'label' keys
        """
        if field_name == "database_id":
            return await cls._list_databases(credential_data, search=search)
        if field_name == "page_id":
            return await cls._list_pages(credential_data, search=search)
        if field_name == "user_id":
            return await cls._list_users_options(credential_data)
        return []

    @classmethod
    async def _list_databases(
        cls,
        credential_data: Dict[str, Any],
        search: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List accessible databases for the dropdown.

        ``search`` is forwarded to Notion's ``/v1/search`` ``query`` parameter
        so the upstream result set is narrowed by the user-typed text. Without
        this, only databases in the first 100 results are findable.
        """
        access_token = require_credential_token(
            credential_data.get("access_token")
            or credential_data.get("integration_token"),
            "Connect a Notion account to load databases",
        )

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Notion-Version": NOTION_API_VERSION,
        }

        body: Dict[str, Any] = {
            "filter": {"property": "object", "value": "database"},
            "page_size": 100,
        }
        if search:
            body["query"] = search

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Use search endpoint to find all databases
                response = await client.post(
                    f"{NOTION_API_BASE}/search",
                    headers=headers,
                    json=body,
                )

                if response.status_code != 200:
                    raise ValueError(f"Notion API error: {response.text}")

                data = response.json()
                results = data.get("results", [])

                options = []
                for db in results:
                    db_id = db.get("id", "")
                    # Extract title from title property
                    title_prop = db.get("title", [])
                    title = ""
                    if title_prop and len(title_prop) > 0:
                        title = title_prop[0].get("plain_text", "")

                    if not title:
                        title = f"Untitled Database ({db_id[:8]}...)"

                    options.append(
                        {
                            "value": db_id,
                            "label": title,
                            "metadata": {
                                "url": db.get("url"),
                                "created_time": db.get("created_time"),
                                "last_edited_time": db.get("last_edited_time"),
                            },
                        }
                    )

                logger.info(f"[NotionNode] Found {len(options)} databases")
                return options

        except ValueError:
            raise
        except Exception as e:
            logger.error(f"[NotionNode] Error listing databases: {e}")
            raise ValueError(f"Failed to load Notion options: {e}") from e

    @classmethod
    async def _list_pages(
        cls,
        credential_data: Dict[str, Any],
        search: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List accessible pages for the dropdown."""
        access_token = require_credential_token(
            credential_data.get("access_token")
            or credential_data.get("integration_token"),
            "Connect a Notion account to load pages",
        )

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Notion-Version": NOTION_API_VERSION,
        }

        body: Dict[str, Any] = {
            "filter": {"property": "object", "value": "page"},
            "page_size": 100,
        }
        if search:
            body["query"] = search

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{NOTION_API_BASE}/search",
                    headers=headers,
                    json=body,
                )

                if response.status_code != 200:
                    raise ValueError(f"Notion API error: {response.text}")

                data = response.json()
                results = data.get("results", [])

                options = []
                for page in results:
                    page_id = page.get("id", "")
                    props = page.get("properties", {})
                    title = ""
                    for prop in props.values():
                        if prop.get("type") == "title":
                            rich = prop.get("title", [])
                            if rich:
                                title = "".join(
                                    t.get("plain_text", "") for t in rich
                                )
                            break
                    if not title:
                        title = f"Untitled Page ({page_id[:8]}...)"

                    options.append(
                        {
                            "value": page_id,
                            "label": title,
                            "metadata": {
                                "url": page.get("url"),
                                "last_edited_time": page.get("last_edited_time"),
                            },
                        }
                    )

                logger.info(f"[NotionNode] Found {len(options)} pages")
                return options

        except ValueError:
            raise
        except Exception as e:
            logger.error(f"[NotionNode] Error listing pages: {e}")
            raise ValueError(f"Failed to load Notion page options: {e}") from e

    @classmethod
    async def _list_users_options(
        cls,
        credential_data: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """List workspace users for the dropdown."""
        access_token = require_credential_token(
            credential_data.get("access_token")
            or credential_data.get("integration_token"),
            "Connect a Notion account to load users",
        )

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Notion-Version": NOTION_API_VERSION,
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{NOTION_API_BASE}/users",
                    headers=headers,
                    params={"page_size": 100},
                )

                if response.status_code != 200:
                    raise ValueError(f"Notion API error: {response.text}")

                data = response.json()
                results = data.get("results", [])

                options = []
                for user in results:
                    user_id = user.get("id", "")
                    name = user.get("name") or f"User ({user_id[:8]}...)"
                    options.append(
                        {
                            "value": user_id,
                            "label": name,
                            "metadata": {
                                "type": user.get("type"),
                                "avatar_url": user.get("avatar_url"),
                            },
                        }
                    )

                logger.info(f"[NotionNode] Found {len(options)} users")
                return options

        except ValueError:
            raise
        except Exception as e:
            logger.error(f"[NotionNode] Error listing users: {e}")
            raise ValueError(f"Failed to load Notion user options: {e}") from e

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the configured operation.

        Args:
            inputs: Output data from upstream nodes

        Returns:
            Dict with operation results
        """
        start_time = time.time()

        # Validate configuration
        config = self.config
        if not config or not isinstance(config, NotionNodeConfig):
            raise ValueError("Valid configuration is required")

        # Validate credentials
        credentials = config.credentials
        if not credentials:
            raise ValueError(
                "Credentials are required. Add your Notion Integration Token or connect via OAuth."
            )

        # Get the specific operation config
        op_config = config.config

        # Route to appropriate handler
        handlers = {
            # Triggers
            "on_database_item": self._trigger_on_database_item,
            "on_page_created": self._trigger_on_page_created,
            "on_page_updated": self._trigger_on_page_updated,
            "on_comment_created": self._trigger_on_comment_created,
            "on_database_created": self._trigger_on_database_created,
            # Search
            "search_pages_and_databases": self._handle_search,
            # Database operations
            "query_notion_database": self._handle_query_database,
            "fetch_database_metadata": self._handle_retrieve_database,
            "create_page_database": self._handle_create_database,
            "update_database_metadata": self._handle_update_database,
            # Page operations
            "fetch_page_properties": self._handle_retrieve_page,
            "fetch_page_property": self._handle_retrieve_page_property,
            "create_notion_page": self._handle_create_page,
            "update_page_properties": self._handle_update_page,
            # Block operations
            "fetch_notion_block": self._handle_retrieve_block,
            "fetch_block_children": self._handle_retrieve_block_children,
            "append_children_to_block": self._handle_append_block_children,
            "update_block_content": self._handle_update_block,
            "delete_notion_block": self._handle_delete_block,
            # User operations
            "list_workspace_users": self._handle_list_users,
            "fetch_workspace_user": self._handle_retrieve_user,
            "fetch_bot_integration_user": self._handle_retrieve_bot_user,
            # Comment operations
            "create_page_comment": self._handle_create_comment,
            "fetch_page_comment": self._handle_retrieve_comment,
            "list_block_comments": self._handle_list_comments,
            "update_page_comment": self._handle_update_comment,
            "delete_page_comment": self._handle_delete_comment,
            # View operations
            "list_database_views": self._handle_list_views,
            "fetch_database_view": self._handle_retrieve_view,
            "update_database_view": self._handle_update_view,
            # File / async task
            "create_file_upload": self._handle_create_file_upload,
            "get_async_task_status": self._handle_get_async_task,
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

    @classmethod
    async def freshen_credential(
        cls, credential_data, *, pool=None, user_id=None, credential_id=None
    ):
        """Refresh an expiring OAuth token at credential load (dropdowns,
        trigger registration). No-op for non-rotating credentials (API keys /
        offline / non-expiring tokens)."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.notion_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data,
            pool=pool,
            user_id=user_id,
            credential_id=credential_id,
            refresh=refresh_access_token,
            provider="notion",
        )

    # =========================================================================
    # HTTP Request Helper
    # =========================================================================

    async def _get_access_token(self, credentials: NotionCredential) -> str:
        """Get access token from credentials, refreshing if needed."""
        if isinstance(credentials, NotionIntegrationTokenCredential):
            return credentials.integration_token
        elif isinstance(credentials, NotionOAuthCredential):
            from nodes.core.oauth_refresh import ensure_fresh_oauth_token
            
            cred_dict = credentials.model_dump()
            token = await ensure_fresh_oauth_token(
                credential_id=(self.node_data or {}).get("credential_id"),
                user_id=self.user_id,
                credential=cred_dict,
                refresh=refresh_access_token,
                provider="notion",
            )
            credentials.access_token = cred_dict["access_token"]
            credentials.expires_at = cred_dict.get("expires_at")
            if cred_dict.get("refresh_token"):
                credentials.refresh_token = cred_dict["refresh_token"]
            return token
        else:
            raise ValueError(f"Unknown credential type: {type(credentials)}")

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        credentials: NotionCredential,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        action_name: str = "request",
        api_version: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Make an HTTP request to the Notion API."""
        url = f"{NOTION_API_BASE}{endpoint}"

        access_token = await self._get_access_token(credentials)

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Notion-Version": api_version or NOTION_API_VERSION,
        }

        # Clean params
        if params:
            params = {k: v for k, v in params.items() if v is not None}

        start_time = time.time()

        async with httpx.AsyncClient(timeout=30.0) as client:
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
                    try:
                        error_data = response.json()
                        error_message = error_data.get("message", str(error_data))
                    except Exception:
                        error_message = response.text

                    logger.error(f"[NotionNode] API error: {error_message}")
                    return {
                        "status": "error",
                        "action": action_name,
                        "error": error_message,
                        "status_code": response.status_code,
                        "timing_ms": {"api_request": round(api_time, 2)},
                    }

                # Parse response
                if response.status_code == 204:
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
                logger.exception(f"[NotionNode] Request failed: {e}")
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
    # Search Handler
    # =========================================================================

    async def _handle_search(
        self, config: NotionSearchConfig, credentials: NotionCredential
    ) -> Dict[str, Any]:
        """Search pages and databases."""
        body: Dict[str, Any] = {}

        if config.query:
            body["query"] = config.query
        if config.filter_type:
            body["filter"] = {"property": "object", "value": config.filter_type}
        if config.sort_direction:
            body["sort"] = {
                "direction": config.sort_direction,
                "timestamp": "last_edited_time",
            }
        if config.page_size:
            body["page_size"] = config.page_size
        if config.start_cursor:
            body["start_cursor"] = config.start_cursor

        return await self._make_request(
            method="POST",
            endpoint="/search",
            credentials=credentials,
            json_body=body,
            action_name="search_pages_and_databases",
        )

    # =========================================================================
    # Database Handlers
    # =========================================================================

    async def _handle_query_database(
        self, config: NotionQueryDatabaseConfig, credentials: NotionCredential
    ) -> Dict[str, Any]:
        """Query a database."""
        import json as json_module

        body: Dict[str, Any] = {}

        if config.filter:
            try:
                body["filter"] = json_module.loads(config.filter)
            except json_module.JSONDecodeError as e:
                return {
                    "status": "error",
                    "action": "query_notion_database",
                    "error": f"Invalid filter JSON: {e}",
                    "status_code": 400,
                }

        if config.sorts:
            try:
                body["sorts"] = json_module.loads(config.sorts)
            except json_module.JSONDecodeError as e:
                return {
                    "status": "error",
                    "action": "query_notion_database",
                    "error": f"Invalid sorts JSON: {e}",
                    "status_code": 400,
                }

        if config.page_size:
            body["page_size"] = config.page_size
        if config.start_cursor:
            body["start_cursor"] = config.start_cursor

        return await self._make_request(
            method="POST",
            endpoint=f"/databases/{config.database_id}/query",
            credentials=credentials,
            json_body=body,
            action_name="query_notion_database",
        )

    async def _handle_retrieve_database(
        self, config: NotionRetrieveDatabaseConfig, credentials: NotionCredential
    ) -> Dict[str, Any]:
        """Retrieve a database."""
        return await self._make_request(
            method="GET",
            endpoint=f"/databases/{config.database_id}",
            credentials=credentials,
            action_name="fetch_database_metadata",
        )

    async def _handle_create_database(
        self, config: NotionCreateDatabaseConfig, credentials: NotionCredential
    ) -> Dict[str, Any]:
        """Create a database."""
        import json as json_module

        try:
            properties = json_module.loads(config.properties)
        except json_module.JSONDecodeError as e:
            return {
                "status": "error",
                "action": "create_page_database",
                "error": f"Invalid properties JSON: {e}",
                "status_code": 400,
            }

        body = {
            "parent": {"type": "page_id", "page_id": config.parent_page_id},
            "title": [{"type": "text", "text": {"content": config.title}}],
            "properties": properties,
        }

        return await self._make_request(
            method="POST",
            endpoint="/databases",
            credentials=credentials,
            json_body=body,
            action_name="create_page_database",
        )

    async def _handle_update_database(
        self, config: NotionUpdateDatabaseConfig, credentials: NotionCredential
    ) -> Dict[str, Any]:
        """Update a database."""
        import json as json_module

        body: Dict[str, Any] = {}

        if config.title:
            body["title"] = [{"type": "text", "text": {"content": config.title}}]
        if config.description:
            body["description"] = [
                {"type": "text", "text": {"content": config.description}}
            ]
        if config.properties:
            try:
                body["properties"] = json_module.loads(config.properties)
            except json_module.JSONDecodeError as e:
                return {
                    "status": "error",
                    "action": "update_database_metadata",
                    "error": f"Invalid properties JSON: {e}",
                    "status_code": 400,
                }

        return await self._make_request(
            method="PATCH",
            endpoint=f"/databases/{config.database_id}",
            credentials=credentials,
            json_body=body,
            action_name="update_database_metadata",
        )

    # =========================================================================
    # Page Handlers
    # =========================================================================

    async def _handle_retrieve_page(
        self, config: NotionRetrievePageConfig, credentials: NotionCredential
    ) -> Dict[str, Any]:
        """Retrieve a page."""
        return await self._make_request(
            method="GET",
            endpoint=f"/pages/{config.page_id}",
            credentials=credentials,
            action_name="fetch_page_properties",
        )

    async def _handle_create_page(
        self, config: NotionCreatePageConfig, credentials: NotionCredential
    ) -> Dict[str, Any]:
        """Create a page."""
        import json as json_module

        try:
            properties = json_module.loads(config.properties)
        except json_module.JSONDecodeError as e:
            return {
                "status": "error",
                "action": "create_notion_page",
                "error": f"Invalid properties JSON: {e}",
                "status_code": 400,
            }

        body: Dict[str, Any] = {
            "parent": {config.parent_type: config.parent_id},
            "properties": properties,
        }

        if config.children:
            try:
                body["children"] = json_module.loads(config.children)
            except json_module.JSONDecodeError as e:
                return {
                    "status": "error",
                    "action": "create_notion_page",
                    "error": f"Invalid children JSON: {e}",
                    "status_code": 400,
                }

        if config.icon:
            body["icon"] = {"type": "emoji", "emoji": config.icon}
        if config.cover:
            body["cover"] = {"type": "external", "external": {"url": config.cover}}

        return await self._make_request(
            method="POST",
            endpoint="/pages",
            credentials=credentials,
            json_body=body,
            action_name="create_notion_page",
        )

    async def _handle_update_page(
        self, config: NotionUpdatePageConfig, credentials: NotionCredential
    ) -> Dict[str, Any]:
        """Update a page."""
        import json as json_module

        body: Dict[str, Any] = {}

        if config.properties:
            try:
                body["properties"] = json_module.loads(config.properties)
            except json_module.JSONDecodeError as e:
                return {
                    "status": "error",
                    "action": "update_page_properties",
                    "error": f"Invalid properties JSON: {e}",
                    "status_code": 400,
                }

        if config.archived is not None:
            body["archived"] = config.archived
        if config.icon:
            body["icon"] = {"type": "emoji", "emoji": config.icon}
        if config.cover:
            body["cover"] = {"type": "external", "external": {"url": config.cover}}

        return await self._make_request(
            method="PATCH",
            endpoint=f"/pages/{config.page_id}",
            credentials=credentials,
            json_body=body,
            action_name="update_page_properties",
        )

    # =========================================================================
    # Block Handlers
    # =========================================================================

    async def _handle_retrieve_block(
        self, config: NotionRetrieveBlockConfig, credentials: NotionCredential
    ) -> Dict[str, Any]:
        """Retrieve a block."""
        return await self._make_request(
            method="GET",
            endpoint=f"/blocks/{config.block_id}",
            credentials=credentials,
            action_name="fetch_notion_block",
        )

    async def _handle_retrieve_block_children(
        self, config: NotionRetrieveBlockChildrenConfig, credentials: NotionCredential
    ) -> Dict[str, Any]:
        """Retrieve block children."""
        params: Dict[str, Any] = {}
        if config.page_size:
            params["page_size"] = config.page_size
        if config.start_cursor:
            params["start_cursor"] = config.start_cursor

        return await self._make_request(
            method="GET",
            endpoint=f"/blocks/{config.block_id}/children",
            credentials=credentials,
            params=params if params else None,
            action_name="fetch_block_children",
        )

    async def _handle_append_block_children(
        self, config: NotionAppendBlockChildrenConfig, credentials: NotionCredential
    ) -> Dict[str, Any]:
        """Append block children."""
        import json as json_module

        try:
            children = json_module.loads(config.children)
        except json_module.JSONDecodeError as e:
            return {
                "status": "error",
                "action": "append_children_to_block",
                "error": f"Invalid children JSON: {e}",
                "status_code": 400,
            }

        body: Dict[str, Any] = {"children": children}
        if config.after:
            body["after"] = config.after

        return await self._make_request(
            method="PATCH",
            endpoint=f"/blocks/{config.block_id}/children",
            credentials=credentials,
            json_body=body,
            action_name="append_children_to_block",
        )

    async def _handle_update_block(
        self, config: NotionUpdateBlockConfig, credentials: NotionCredential
    ) -> Dict[str, Any]:
        """Update a block."""
        import json as json_module

        try:
            content = json_module.loads(config.content)
        except json_module.JSONDecodeError as e:
            return {
                "status": "error",
                "action": "update_block_content",
                "error": f"Invalid content JSON: {e}",
                "status_code": 400,
            }

        body: Dict[str, Any] = {config.block_type: content}
        if config.archived is not None:
            body["archived"] = config.archived

        return await self._make_request(
            method="PATCH",
            endpoint=f"/blocks/{config.block_id}",
            credentials=credentials,
            json_body=body,
            action_name="update_block_content",
        )

    async def _handle_delete_block(
        self, config: NotionDeleteBlockConfig, credentials: NotionCredential
    ) -> Dict[str, Any]:
        """Delete a block."""
        return await self._make_request(
            method="DELETE",
            endpoint=f"/blocks/{config.block_id}",
            credentials=credentials,
            action_name="delete_notion_block",
        )

    # =========================================================================
    # User Handlers
    # =========================================================================

    async def _handle_list_users(
        self, config: NotionListUsersConfig, credentials: NotionCredential
    ) -> Dict[str, Any]:
        """List all users."""
        params: Dict[str, Any] = {}
        if config.page_size:
            params["page_size"] = config.page_size
        if config.start_cursor:
            params["start_cursor"] = config.start_cursor

        return await self._make_request(
            method="GET",
            endpoint="/users",
            credentials=credentials,
            params=params if params else None,
            action_name="list_workspace_users",
        )

    async def _handle_retrieve_user(
        self, config: NotionRetrieveUserConfig, credentials: NotionCredential
    ) -> Dict[str, Any]:
        """Retrieve a user."""
        return await self._make_request(
            method="GET",
            endpoint=f"/users/{config.user_id}",
            credentials=credentials,
            action_name="fetch_workspace_user",
        )

    async def _handle_retrieve_bot_user(
        self, config: NotionRetrieveBotUserConfig, credentials: NotionCredential
    ) -> Dict[str, Any]:
        """Retrieve the bot user."""
        return await self._make_request(
            method="GET",
            endpoint="/users/me",
            credentials=credentials,
            action_name="fetch_bot_integration_user",
        )

    # =========================================================================
    # Comment Operation Handlers
    # =========================================================================

    async def _handle_create_comment(
        self, config: NotionCreateCommentConfig, credentials: NotionCredential
    ) -> Dict[str, Any]:
        """Create a comment on a page or discussion thread."""
        import json

        # Build request body
        json_body = {
            "parent": {config.parent_type: config.parent_id},
            "rich_text": json.loads(config.rich_text),
        }

        return await self._make_request(
            method="POST",
            endpoint="/comments",
            credentials=credentials,
            json_body=json_body,
            action_name="create_page_comment",
        )

    async def _handle_retrieve_comment(
        self, config: NotionRetrieveCommentConfig, credentials: NotionCredential
    ) -> Dict[str, Any]:
        """Retrieve a comment by ID."""
        return await self._make_request(
            method="GET",
            endpoint=f"/comments/{config.comment_id}",
            credentials=credentials,
            action_name="fetch_page_comment",
        )

    async def _handle_list_comments(
        self, config: NotionListCommentsConfig, credentials: NotionCredential
    ) -> Dict[str, Any]:
        """List comments on a block or page."""
        params = {"block_id": config.block_id}
        if config.page_size:
            params["page_size"] = config.page_size
        if config.start_cursor:
            params["start_cursor"] = config.start_cursor

        return await self._make_request(
            method="GET",
            endpoint="/comments",
            credentials=credentials,
            params=params,
            action_name="list_block_comments",
        )

    async def _handle_update_comment(
        self, config: NotionUpdateCommentConfig, credentials: NotionCredential
    ) -> Dict[str, Any]:
        """Update a comment's rich text."""
        import json

        try:
            rich_text = json.loads(config.rich_text)
        except json.JSONDecodeError as e:
            return {
                "status": "error",
                "action": "update_page_comment",
                "error": f"Invalid rich_text JSON: {e}",
                "status_code": 400,
            }

        return await self._make_request(
            method="PATCH",
            endpoint=f"/comments/{config.comment_id}",
            credentials=credentials,
            json_body={"rich_text": rich_text},
            action_name="update_page_comment",
        )

    async def _handle_delete_comment(
        self, config: NotionDeleteCommentConfig, credentials: NotionCredential
    ) -> Dict[str, Any]:
        """Delete a comment."""
        return await self._make_request(
            method="DELETE",
            endpoint=f"/comments/{config.comment_id}",
            credentials=credentials,
            action_name="delete_page_comment",
        )

    # =========================================================================
    # Page Property Handler
    # =========================================================================

    async def _handle_retrieve_page_property(
        self, config: NotionRetrievePagePropertyConfig, credentials: NotionCredential
    ) -> Dict[str, Any]:
        """Retrieve a single property item from a page."""
        params: Dict[str, Any] = {}
        if config.page_size:
            params["page_size"] = config.page_size
        if config.start_cursor:
            params["start_cursor"] = config.start_cursor

        return await self._make_request(
            method="GET",
            endpoint=f"/pages/{config.page_id}/properties/{config.property_id}",
            credentials=credentials,
            params=params if params else None,
            action_name="fetch_page_property",
        )

    # =========================================================================
    # View Handlers
    # =========================================================================

    async def _handle_list_views(
        self, config: NotionListViewsConfig, credentials: NotionCredential
    ) -> Dict[str, Any]:
        """List views for a database."""
        params: Dict[str, Any] = {"database_id": config.database_id}
        if config.page_size:
            params["page_size"] = config.page_size
        if config.start_cursor:
            params["start_cursor"] = config.start_cursor

        return await self._make_request(
            method="GET",
            endpoint="/views",
            credentials=credentials,
            params=params,
            action_name="list_database_views",
        )

    async def _handle_retrieve_view(
        self, config: NotionRetrieveViewConfig, credentials: NotionCredential
    ) -> Dict[str, Any]:
        """Retrieve a single database view."""
        return await self._make_request(
            method="GET",
            endpoint=f"/views/{config.view_id}",
            credentials=credentials,
            action_name="fetch_database_view",
        )

    async def _handle_update_view(
        self, config: NotionUpdateViewConfig, credentials: NotionCredential
    ) -> Dict[str, Any]:
        """Update a database view."""
        import json as json_module

        body: Dict[str, Any] = {}
        if config.name:
            body["name"] = config.name
        if config.layout:
            body["layout"] = config.layout
        if config.filters:
            try:
                body["filters"] = json_module.loads(config.filters)
            except json_module.JSONDecodeError as e:
                return {
                    "status": "error",
                    "action": "update_database_view",
                    "error": f"Invalid filters JSON: {e}",
                    "status_code": 400,
                }
        if config.sorts:
            try:
                body["sorts"] = json_module.loads(config.sorts)
            except json_module.JSONDecodeError as e:
                return {
                    "status": "error",
                    "action": "update_database_view",
                    "error": f"Invalid sorts JSON: {e}",
                    "status_code": 400,
                }

        return await self._make_request(
            method="PATCH",
            endpoint=f"/views/{config.view_id}",
            credentials=credentials,
            json_body=body,
            action_name="update_database_view",
        )

    # =========================================================================
    # File Upload / Async Task Handlers
    # =========================================================================

    async def _handle_create_file_upload(
        self, config: NotionCreateFileUploadConfig, credentials: NotionCredential
    ) -> Dict[str, Any]:
        """Initiate a Notion file upload.

        Creates a file upload object and, if a file_url is provided, downloads
        the file and sends the bytes to Notion's upload endpoint, then confirms.
        """
        body: Dict[str, Any] = {
            "filename": config.filename,
            "content_type": config.content_type,
        }
        if config.parent_page_id:
            body["parent"] = {"type": "page_id", "page_id": config.parent_page_id}

        # Step 1: Create the upload object (requires API v2025-09-03+)
        init_result = await self._make_request(
            method="POST",
            endpoint="/files",
            credentials=credentials,
            json_body=body,
            action_name="create_file_upload",
            api_version="2025-09-03",
        )
        if init_result.get("status") == "error":
            return init_result

        file_data = init_result.get("data", {})
        upload_url = file_data.get("upload_url")
        file_id = file_data.get("id")

        if not config.file_url or not upload_url:
            return init_result

        # Step 2: Download the source file and PUT to Notion's upload URL
        try:
            async with guarded_async_client(timeout=60.0) as client:
                dl = await client.get(config.file_url)
                if dl.status_code >= 400:
                    return {
                        "status": "error",
                        "action": "create_file_upload",
                        "error": f"Failed to download file from URL: HTTP {dl.status_code}",
                        "status_code": dl.status_code,
                    }
                file_bytes = dl.content

                up = await client.put(
                    upload_url,
                    content=file_bytes,
                    headers={"Content-Type": config.content_type},
                )
                if up.status_code >= 400:
                    return {
                        "status": "error",
                        "action": "create_file_upload",
                        "error": f"Upload to Notion failed: {up.text}",
                        "status_code": up.status_code,
                    }
        except Exception as e:
            return {
                "status": "error",
                "action": "create_file_upload",
                "error": f"File upload error: {e}",
                "status_code": 500,
            }

        # Step 3: Confirm the upload
        confirm = await self._make_request(
            method="PATCH",
            endpoint=f"/files/{file_id}/confirm",
            credentials=credentials,
            json_body={},
            action_name="create_file_upload",
            api_version="2025-09-03",
        )
        return confirm

    async def _handle_get_async_task(
        self, config: NotionGetAsyncTaskConfig, credentials: NotionCredential
    ) -> Dict[str, Any]:
        """Get the status of an async task (e.g., file export).

        Requires API version 2025-09-03 or later.
        """
        return await self._make_request(
            method="GET",
            endpoint=f"/async_tasks/{config.task_id}",
            credentials=credentials,
            action_name="get_async_task_status",
            api_version="2025-09-03",
        )

    # =========================================================================
    # New Poll Trigger Handlers
    # =========================================================================

    async def _trigger_on_page_created(self, config, credentials) -> Dict[str, Any]:
        """Poll search for newly created pages since the last poll.

        Notion search only supports sorting by ``last_edited_time``, so we sort
        by that and dedup by page ``id`` alone — once a page id is seen it never
        fires again, which is the correct semantics for a "created" trigger.
        """
        body: Dict[str, Any] = {
            "filter": {"property": "object", "value": "page"},
            "sort": {"direction": "descending", "timestamp": "last_edited_time"},
            "page_size": 100,
        }
        if config.query:
            body["query"] = config.query

        result = await self._make_request(
            "POST", "/search", credentials, json_body=body, action_name="on_page_created"
        )
        if result.get("status") == "error":
            raise ValueError(
                f"Notion search failed: {result.get('error') or result.get('data')}"
            )
        pages = (result.get("data") or {}).get("results", [])

        # Dedup by id only — each page fires exactly once (on first sight)
        new_items = await self._filter_unseen(pages, lambda p: p.get("id"))
        return {"items": new_items, "new_item_count": len(new_items)}

    async def _trigger_on_page_updated(self, config, credentials) -> Dict[str, Any]:
        """Poll search for pages modified since the last poll.

        Dedup key includes last_edited_time so any edit to a page fires again.
        """
        body: Dict[str, Any] = {
            "filter": {"property": "object", "value": "page"},
            "sort": {"direction": "descending", "timestamp": "last_edited_time"},
            "page_size": 100,
        }
        if config.query:
            body["query"] = config.query

        result = await self._make_request(
            "POST", "/search", credentials, json_body=body, action_name="on_page_updated"
        )
        if result.get("status") == "error":
            raise ValueError(
                f"Notion search failed: {result.get('error') or result.get('data')}"
            )
        pages = (result.get("data") or {}).get("results", [])

        def _item_id(page):
            pid = page.get("id")
            return f"{pid}:{page.get('last_edited_time', '')}" if pid else None

        new_items = await self._filter_unseen(pages, _item_id)
        return {"items": new_items, "new_item_count": len(new_items)}

    async def _trigger_on_comment_created(self, config, credentials) -> Dict[str, Any]:
        """Poll for new comments on a block or page."""
        params: Dict[str, Any] = {"block_id": config.block_id, "page_size": 100}

        result = await self._make_request(
            "GET",
            "/comments",
            credentials,
            params=params,
            action_name="on_comment_created",
        )
        if result.get("status") == "error":
            raise ValueError(
                f"Notion comments fetch failed: {result.get('error') or result.get('data')}"
            )
        comments = (result.get("data") or {}).get("results", [])

        def _item_id(comment):
            cid = comment.get("id")
            return f"{cid}:{comment.get('created_time', '')}" if cid else None

        new_items = await self._filter_unseen(comments, _item_id)
        return {"items": new_items, "new_item_count": len(new_items)}

    async def _trigger_on_database_created(self, config, credentials) -> Dict[str, Any]:
        """Poll search for newly created databases since the last poll.

        Dedup by database ``id`` only — fires exactly once per new database.
        """
        body: Dict[str, Any] = {
            "filter": {"property": "object", "value": "database"},
            "sort": {"direction": "descending", "timestamp": "last_edited_time"},
            "page_size": 100,
        }
        if config.query:
            body["query"] = config.query

        result = await self._make_request(
            "POST",
            "/search",
            credentials,
            json_body=body,
            action_name="on_database_created",
        )
        if result.get("status") == "error":
            raise ValueError(
                f"Notion search failed: {result.get('error') or result.get('data')}"
            )
        databases = (result.get("data") or {}).get("results", [])

        # Dedup by id only — each database fires exactly once (on first sight)
        new_items = await self._filter_unseen(databases, lambda db: db.get("id"))
        return {"items": new_items, "new_item_count": len(new_items)}
