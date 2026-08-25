"""
Monday.com work-management automation node.

Provides workflow integration with monday.com (Platform GraphQL API) for
operations including:
- Boards: list, get, create, update, delete, archive, duplicate, add/remove
  users, add teams
- Items: list (paginated), get by id, query by column value, create, create
  subitem, update column value(s), move to group/board, archive, delete,
  duplicate; get subitems; get/create/edit/delete/like/unlike updates
- Groups & Columns: create, list, archive, duplicate, update, delete group;
  create, rename, delete column
- Docs: list, create, add/update/delete blocks
- Files: get assets by ID
- Folders: list, create, update, delete
- Workspaces: list, create, update, delete
- Teams: get, create, delete; add/remove users
- Users: list, get current user, notifications
- Webhooks: create, delete, list
- Webhook Trigger: fire when a board event (new item, column change, etc.) occurs

Authentication: Personal API token (V2) OR OAuth 2.0 — both passed as the
*bare* ``Authorization: <token>`` header (monday.com does NOT use a Bearer
prefix). The personal-token path is fully self-serve; the OAuth path needs a
backend OAuth handler (human follow-up — see PR notes).

API Base URL: https://api.monday.com/v2  (single GraphQL endpoint, all POST)
Documentation: https://developer.monday.com/api-reference

GOTCHA: monday.com returns HTTP 200 with an ``errors`` array on GraphQL and
rate-limit failures — the request helper inspects the JSON body, not just the
status code.
"""

import hashlib
import json
import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated

import httpx
from pydantic import BaseModel, Field, ConfigDict, Discriminator

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.scopes.monday import MONDAY_SCOPES
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin

logger = logging.getLogger(__name__)

MONDAY_API_BASE = "https://api.monday.com/v2"
# Pin the API version so monday's scheduled version rotations don't break us.
MONDAY_API_VERSION = "2025-04"

# Default webhook event subscribed to by the trigger. Monday webhooks register
# one event per webhook; "create_item" is the most common automation trigger.
DEFAULT_TRIGGER_EVENT = "create_item"


# ============================================================================
# Credential Schemas
# ============================================================================


class MondayOAuthCredential(BaseModel):
    """OAuth 2.0 credential for monday.com.

    Tokens are obtained via the monday OAuth flow (authorization_code), not
    entered manually. monday OAuth tokens do not expire (valid until the user
    uninstalls the app). The access token is sent as the *bare* Authorization
    header value — monday does NOT use a Bearer prefix.

    Register an app at: monday.com Developer Center -> create app ->
    Basic Information (client_id / client_secret) + OAuth tab (scopes / redirect).
    """

    credential_type: Literal["monday_oauth"] = Field(
        "monday_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ...,
        title="Access Token",
        description="monday.com OAuth access token (sent as bare Authorization).",
        json_schema_extra={"ui:widget": "password"},
    )
    refresh_token: Optional[str] = Field(None, title="Refresh Token")
    expires_at: Optional[str] = Field(None, title="Token Expiry")  # ISO 8601
    name: Optional[str] = Field(None, title="User Name")
    email: Optional[str] = Field(None, title="Account Email")

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "monday",
            "x-oauth-scopes": [
                "account:read",
                "boards:read",
                "boards:write",
                "docs:read",
                "docs:write",
                "workspaces:read",
                "workspaces:write",
                "users:read",
                "users:write",
                "teams:read",
                "teams:write",
                "updates:read",
                "updates:write",
                "notifications:write",
                "webhooks:read",
                "webhooks:write",
                "assets:read",
                "tags:read",
                "me:read",
            ],
            "x-oauth-supports-custom-client": True,
            "x-oauth-custom-client-help": (
                "Optionally bring your own monday.com OAuth app. Register one in the "
                "monday Developer Center, set its redirect URI to NoClick's monday "
                "callback, and paste its client ID and secret here. Leave blank to use "
                "NoClick's shared monday app."
            ),
            "x-credential-url": "https://monday.com/developers/apps",
        }
    )


class MondayApiTokenCredential(BaseModel):
    """Personal API token (V2) authentication for monday.com.

    Get your token at: profile picture -> Developers -> My Access Tokens
    (or, for admins, Administration -> Connections -> Personal API token).
    The token is sent as the *bare* Authorization header value (no Bearer prefix).
    """

    credential_type: Literal["monday_api_token"] = Field(
        "monday_api_token", json_schema_extra={"ui:hidden": True}
    )
    api_token: str = Field(
        ...,
        title="API Token",
        description="Your monday.com personal V2 API token from Developers -> My Access Tokens",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://monday.com/developers/v2/try-it-yourself"
        }
    )


# OAuth listed first (best UX once the handler ships); personal token is the
# fully working self-serve path today.
MondayCredential = Union[MondayOAuthCredential, MondayApiTokenCredential]


# ============================================================================
# Operation Configs
# ============================================================================


class MondayListBoardsConfig(BaseModel):
    """List boards in the account (name, columns, groups)."""

    operation: Literal["list_boards"] = Field(
        "list_boards",
        json_schema_extra={
            "const": "list_boards",
            "ui:hidden": True,
            "x-category": "Boards",
            "x-is-trigger": False,
            "x-display-name": "List Boards",
        },
        title="List Boards",
    )
    workspace_id: Optional[str] = Field(
        None, title="Workspace ID", description="Filter to a specific workspace (optional)",
        json_schema_extra={"ui:placeholder": "e.g. 1234567"},
    )
    limit: Optional[str] = Field(
        "25", title="Limit", description="Max number of boards to return (1-100)",
        json_schema_extra={"ui:placeholder": "e.g. 25"},
    )
    page: Optional[str] = Field(
        "1", title="Page", description="Page number for offset pagination (1-based)",
        json_schema_extra={"ui:placeholder": "e.g. 1"},
    )


class MondayGetBoardConfig(BaseModel):
    """Fetch a single board's metadata, columns, and groups by ID."""

    operation: Literal["get_board"] = Field(
        "get_board",
        json_schema_extra={
            "const": "get_board",
            "ui:hidden": True,
            "x-category": "Boards",
            "x-is-trigger": False,
            "x-display-name": "Get Board",
        },
        title="Get Board",
    )
    board_id: str = Field(
        ...,
        title="Board",
        description="The board to fetch",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "board_id",
                "placeholder": "Select a board...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a board ID",
            },
            "x-resource-type": "monday_board",
        },
    )


class MondayCreateBoardConfig(BaseModel):
    """Create a new board."""

    operation: Literal["create_board"] = Field(
        "create_board",
        json_schema_extra={
            "const": "create_board",
            "ui:hidden": True,
            "x-category": "Boards",
            "x-is-trigger": False,
            "x-display-name": "Create Board",
            "x-creates-resource": True,
            "x-resource-type": "monday_board",
            "x-resource-id-path": "data.create_board.id",
        },
        title="Create Board",
    )
    board_name: str = Field(..., title="Board Name", description="Name of the new board", json_schema_extra={"ui:placeholder": "e.g. My Board"})
    board_kind: str = Field(
        "public",
        title="Board Kind",
        description="Visibility of the board",
        json_schema_extra={
            "enum": ["public", "private", "share"],
            "enumNames": ["Public", "Private", "Shareable"],
            "x-enum-searchable": True,
        },
    )
    workspace_id: Optional[str] = Field(
        None, title="Workspace ID", description="Workspace to create the board in (optional)",
        json_schema_extra={"ui:placeholder": "e.g. 1234567"},
    )
    template_id: Optional[str] = Field(
        None, title="Template ID", description="Board template to base it on (optional)",
        json_schema_extra={"ui:placeholder": "e.g. 1234567"},
    )


class MondayListItemsConfig(BaseModel):
    """List items on a board (cursor-paginated, with column values)."""

    operation: Literal["list_items"] = Field(
        "list_items",
        json_schema_extra={
            "const": "list_items",
            "ui:hidden": True,
            "x-category": "Items",
            "x-is-trigger": False,
            "x-display-name": "List Items",
        },
        title="List Items",
    )
    board_id: str = Field(
        ...,
        title="Board",
        description="The board whose items to list",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "board_id",
                "placeholder": "Select a board...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a board ID",
            },
            "x-resource-type": "monday_board",
        },
    )
    limit: Optional[str] = Field(
        "25", title="Limit", description="Items per page (max 500)",
        json_schema_extra={"ui:placeholder": "e.g. 25"},
    )
    cursor: Optional[str] = Field(
        None, title="Cursor", description="Pagination cursor from a previous page (optional)",
        json_schema_extra={"ui:placeholder": "Paste cursor from previous response"},
    )


class MondayGetItemsConfig(BaseModel):
    """Fetch specific items by ID with their column values."""

    operation: Literal["get_items"] = Field(
        "get_items",
        json_schema_extra={
            "const": "get_items",
            "ui:hidden": True,
            "x-category": "Items",
            "x-is-trigger": False,
            "x-display-name": "Get Items By ID",
        },
        title="Get Items By ID",
    )
    item_ids: str = Field(
        ...,
        title="Item IDs",
        description="One or more item IDs, comma-separated",
        json_schema_extra={"ui:placeholder": "e.g. 123, 456, 789"},
    )


class MondayQueryItemsByColumnConfig(BaseModel):
    """Search/filter items on a board by a column value."""

    operation: Literal["query_items_by_column"] = Field(
        "query_items_by_column",
        json_schema_extra={
            "const": "query_items_by_column",
            "ui:hidden": True,
            "x-category": "Items",
            "x-is-trigger": False,
            "x-display-name": "Query Items By Column Value",
        },
        title="Query Items By Column Value",
    )
    board_id: str = Field(
        ...,
        title="Board",
        description="The board to search within",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "board_id",
                "placeholder": "Select a board...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a board ID",
            },
            "x-resource-type": "monday_board",
        },
    )
    column_id: str = Field(
        ..., title="Column ID", description="The column to filter on",
        json_schema_extra={"ui:placeholder": "e.g. status"},
    )
    column_values: str = Field(
        ...,
        title="Column Values",
        description="Value(s) to match, comma-separated",
        json_schema_extra={"ui:placeholder": 'e.g. {"status": {"label": "Done"}}'},
    )
    limit: Optional[str] = Field(
        "25", title="Limit", description="Items per page (max 500)",
        json_schema_extra={"ui:placeholder": "e.g. 25"},
    )


class MondayCreateItemConfig(BaseModel):
    """Create an item on a board."""

    operation: Literal["create_item"] = Field(
        "create_item",
        json_schema_extra={
            "const": "create_item",
            "ui:hidden": True,
            "x-category": "Items",
            "x-is-trigger": False,
            "x-display-name": "Create Item",
        },
        title="Create Item",
    )
    board_id: str = Field(
        ...,
        title="Board",
        description="The board to add the item to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "board_id",
                "placeholder": "Select a board...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a board ID",
            },
            "x-resource-type": "monday_board",
        },
    )
    item_name: str = Field(..., title="Item Name", description="Name of the new item", json_schema_extra={"ui:placeholder": "e.g. New Task"})
    group_id: Optional[str] = Field(
        None, title="Group ID", description="Group (section) to place the item in (optional)",
        json_schema_extra={"ui:placeholder": "e.g. topics"},
    )
    column_values: Optional[str] = Field(
        None,
        title="Column Values (JSON)",
        description='JSON map of column_id -> value, e.g. {"status":{"label":"Done"}}',
        json_schema_extra={"ui:widget": "textarea"},
    )
    create_labels_if_missing: Optional[str] = Field(
        "false",
        title="Create Labels If Missing",
        description="Create status/dropdown labels that don't yet exist",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class MondayCreateSubitemConfig(BaseModel):
    """Create a subitem under a parent item."""

    operation: Literal["create_subitem"] = Field(
        "create_subitem",
        json_schema_extra={
            "const": "create_subitem",
            "ui:hidden": True,
            "x-category": "Items",
            "x-is-trigger": False,
            "x-display-name": "Create Subitem",
        },
        title="Create Subitem",
    )
    parent_item_id: str = Field(
        ..., title="Parent Item ID", description="The item to create the subitem under",
        json_schema_extra={"ui:placeholder": "e.g. 1234567890"},
    )
    item_name: str = Field(..., title="Subitem Name", description="Name of the new subitem", json_schema_extra={"ui:placeholder": "e.g. New Task"})
    column_values: Optional[str] = Field(
        None,
        title="Column Values (JSON)",
        description="JSON map of column_id -> value for the subitem (optional)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class MondayChangeColumnValueConfig(BaseModel):
    """Change one column's value on an item (typed JSON value)."""

    operation: Literal["change_column_value"] = Field(
        "change_column_value",
        json_schema_extra={
            "const": "change_column_value",
            "ui:hidden": True,
            "x-category": "Items",
            "x-is-trigger": False,
            "x-display-name": "Update Item Column Value",
        },
        title="Update Item Column Value",
    )
    board_id: str = Field(
        ...,
        title="Board",
        description="The board the item belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "board_id",
                "placeholder": "Select a board...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a board ID",
            },
            "x-resource-type": "monday_board",
        },
    )
    item_id: str = Field(..., title="Item ID", description="The item to update", json_schema_extra={"ui:placeholder": "e.g. 1234567890"})
    column_id: str = Field(..., title="Column ID", description="The column to change", json_schema_extra={"ui:placeholder": "e.g. status"})
    value: str = Field(
        ...,
        title="Value (JSON)",
        description='Typed JSON value for the column, e.g. {"label":"Done"}',
        json_schema_extra={"ui:widget": "textarea", "ui:placeholder": 'e.g. {"status": {"label": "Done"}}'},
    )
    create_labels_if_missing: Optional[str] = Field(
        "false",
        title="Create Labels If Missing",
        description="Create status/dropdown labels that don't yet exist",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class MondayChangeMultipleColumnValuesConfig(BaseModel):
    """Change several columns at once via a JSON map."""

    operation: Literal["change_multiple_column_values"] = Field(
        "change_multiple_column_values",
        json_schema_extra={
            "const": "change_multiple_column_values",
            "ui:hidden": True,
            "x-category": "Items",
            "x-is-trigger": False,
            "x-display-name": "Update Multiple Column Values",
        },
        title="Update Multiple Column Values",
    )
    board_id: str = Field(
        ...,
        title="Board",
        description="The board the item belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "board_id",
                "placeholder": "Select a board...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a board ID",
            },
            "x-resource-type": "monday_board",
        },
    )
    item_id: str = Field(..., title="Item ID", description="The item to update", json_schema_extra={"ui:placeholder": "e.g. 1234567890"})
    column_values: str = Field(
        ...,
        title="Column Values (JSON)",
        description='JSON map of column_id -> value, e.g. {"status":{"label":"Done"}}',
        json_schema_extra={"ui:widget": "textarea", "ui:placeholder": 'e.g. {"status": {"label": "Done"}}'},
    )
    create_labels_if_missing: Optional[str] = Field(
        "false",
        title="Create Labels If Missing",
        description="Create status/dropdown labels that don't yet exist",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class MondayChangeSimpleColumnValueConfig(BaseModel):
    """Change a column using a plain string value (simple types)."""

    operation: Literal["change_simple_column_value"] = Field(
        "change_simple_column_value",
        json_schema_extra={
            "const": "change_simple_column_value",
            "ui:hidden": True,
            "x-category": "Items",
            "x-is-trigger": False,
            "x-display-name": "Update Simple Column Value",
        },
        title="Update Simple Column Value",
    )
    board_id: str = Field(
        ...,
        title="Board",
        description="The board the item belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "board_id",
                "placeholder": "Select a board...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a board ID",
            },
            "x-resource-type": "monday_board",
        },
    )
    item_id: str = Field(..., title="Item ID", description="The item to update", json_schema_extra={"ui:placeholder": "e.g. 1234567890"})
    column_id: str = Field(..., title="Column ID", description="The column to change", json_schema_extra={"ui:placeholder": "e.g. status"})
    value: str = Field(
        ..., title="Value", description="Plain string value for the column",
        json_schema_extra={"ui:placeholder": "e.g. Done"},
    )


class MondayMoveItemToGroupConfig(BaseModel):
    """Move an item to a different group within the same board."""

    operation: Literal["move_item_to_group"] = Field(
        "move_item_to_group",
        json_schema_extra={
            "const": "move_item_to_group",
            "ui:hidden": True,
            "x-category": "Items",
            "x-is-trigger": False,
            "x-display-name": "Move Item To Group",
        },
        title="Move Item To Group",
    )
    item_id: str = Field(..., title="Item ID", description="The item to move", json_schema_extra={"ui:placeholder": "e.g. 1234567890"})
    group_id: str = Field(..., title="Group ID", description="Destination group", json_schema_extra={"ui:placeholder": "e.g. topics"})


class MondayMoveItemToBoardConfig(BaseModel):
    """Move an item to another board and group."""

    operation: Literal["move_item_to_board"] = Field(
        "move_item_to_board",
        json_schema_extra={
            "const": "move_item_to_board",
            "ui:hidden": True,
            "x-category": "Items",
            "x-is-trigger": False,
            "x-display-name": "Move Item To Board",
        },
        title="Move Item To Board",
    )
    item_id: str = Field(..., title="Item ID", description="The item to move", json_schema_extra={"ui:placeholder": "e.g. 1234567890"})
    board_id: str = Field(
        ...,
        title="Destination Board",
        description="The board to move the item to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "board_id",
                "placeholder": "Select a board...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a board ID",
            },
            "x-resource-type": "monday_board",
        },
    )
    group_id: str = Field(..., title="Destination Group ID", description="Group on the target board", json_schema_extra={"ui:placeholder": "e.g. topics"})


class MondayArchiveItemConfig(BaseModel):
    """Archive an item."""

    operation: Literal["archive_item"] = Field(
        "archive_item",
        json_schema_extra={
            "const": "archive_item",
            "ui:hidden": True,
            "x-category": "Items",
            "x-is-trigger": False,
            "x-display-name": "Archive Item",
        },
        title="Archive Item",
    )
    item_id: str = Field(..., title="Item ID", description="The item to archive", json_schema_extra={"ui:placeholder": "e.g. 1234567890"})


class MondayDeleteItemConfig(BaseModel):
    """Permanently delete an item."""

    operation: Literal["delete_item"] = Field(
        "delete_item",
        json_schema_extra={
            "const": "delete_item",
            "ui:hidden": True,
            "x-category": "Items",
            "x-is-trigger": False,
            "x-display-name": "Delete Item",
        },
        title="Delete Item",
    )
    item_id: str = Field(..., title="Item ID", description="The item to delete", json_schema_extra={"ui:placeholder": "e.g. 1234567890"})


class MondayDuplicateItemConfig(BaseModel):
    """Duplicate an existing item."""

    operation: Literal["duplicate_item"] = Field(
        "duplicate_item",
        json_schema_extra={
            "const": "duplicate_item",
            "ui:hidden": True,
            "x-category": "Items",
            "x-is-trigger": False,
            "x-display-name": "Duplicate Item",
        },
        title="Duplicate Item",
    )
    board_id: str = Field(
        ...,
        title="Board",
        description="The board the item belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "board_id",
                "placeholder": "Select a board...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a board ID",
            },
            "x-resource-type": "monday_board",
        },
    )
    item_id: str = Field(..., title="Item ID", description="The item to duplicate", json_schema_extra={"ui:placeholder": "e.g. 1234567890"})
    with_updates: Optional[str] = Field(
        "false",
        title="Include Updates",
        description="Copy the item's updates/comments too",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class MondayCreateGroupConfig(BaseModel):
    """Create a new group (section) on a board."""

    operation: Literal["create_group"] = Field(
        "create_group",
        json_schema_extra={
            "const": "create_group",
            "ui:hidden": True,
            "x-category": "Groups & Columns",
            "x-is-trigger": False,
            "x-display-name": "Create Group",
        },
        title="Create Group",
    )
    board_id: str = Field(
        ...,
        title="Board",
        description="The board to add the group to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "board_id",
                "placeholder": "Select a board...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a board ID",
            },
            "x-resource-type": "monday_board",
        },
    )
    group_name: str = Field(..., title="Group Name", description="Name of the new group", json_schema_extra={"ui:placeholder": "e.g. New Group"})


class MondayDeleteGroupConfig(BaseModel):
    """Delete a group from a board."""

    operation: Literal["delete_group"] = Field(
        "delete_group",
        json_schema_extra={
            "const": "delete_group",
            "ui:hidden": True,
            "x-category": "Groups & Columns",
            "x-is-trigger": False,
            "x-display-name": "Delete Group",
        },
        title="Delete Group",
    )
    board_id: str = Field(
        ...,
        title="Board",
        description="The board the group belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "board_id",
                "placeholder": "Select a board...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a board ID",
            },
            "x-resource-type": "monday_board",
        },
    )
    group_id: str = Field(..., title="Group ID", description="The group to delete", json_schema_extra={"ui:placeholder": "e.g. topics"})


class MondayCreateColumnConfig(BaseModel):
    """Add a column to a board."""

    operation: Literal["create_column"] = Field(
        "create_column",
        json_schema_extra={
            "const": "create_column",
            "ui:hidden": True,
            "x-category": "Groups & Columns",
            "x-is-trigger": False,
            "x-display-name": "Create Column",
        },
        title="Create Column",
    )
    board_id: str = Field(
        ...,
        title="Board",
        description="The board to add the column to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "board_id",
                "placeholder": "Select a board...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a board ID",
            },
            "x-resource-type": "monday_board",
        },
    )
    title: str = Field(..., title="Column Title", description="Title of the new column", json_schema_extra={"ui:placeholder": "e.g. My Column"})
    column_type: str = Field(
        "text",
        title="Column Type",
        description="Type of column to create",
        json_schema_extra={
            "enum": [
                "text",
                "long_text",
                "numbers",
                "status",
                "dropdown",
                "date",
                "people",
                "checkbox",
                "email",
                "phone",
                "link",
                "timeline",
                "rating",
                "tags",
            ],
            "x-enum-searchable": True,
        },
    )
    defaults: Optional[str] = Field(
        None,
        title="Defaults (JSON)",
        description="JSON defaults for the column (e.g. status labels), optional",
        json_schema_extra={"ui:widget": "textarea"},
    )


class MondayCreateUpdateConfig(BaseModel):
    """Post an update/comment on an item."""

    operation: Literal["create_update"] = Field(
        "create_update",
        json_schema_extra={
            "const": "create_update",
            "ui:hidden": True,
            "x-category": "Updates & Notifications",
            "x-is-trigger": False,
            "x-display-name": "Create Update (Comment)",
        },
        title="Create Update (Comment)",
    )
    item_id: str = Field(..., title="Item ID", description="The item to comment on", json_schema_extra={"ui:placeholder": "e.g. 1234567890"})
    body: str = Field(
        ...,
        title="Body",
        description="Update/comment text (supports HTML)",
        json_schema_extra={"ui:widget": "textarea", "ui:placeholder": "Enter text..."},
    )


class MondayCreateNotificationConfig(BaseModel):
    """Send an in-app notification to a user."""

    operation: Literal["create_notification"] = Field(
        "create_notification",
        json_schema_extra={
            "const": "create_notification",
            "ui:hidden": True,
            "x-category": "Updates & Notifications",
            "x-is-trigger": False,
            "x-display-name": "Create Notification",
        },
        title="Create Notification",
    )
    user_id: str = Field(..., title="User ID", description="Recipient user ID", json_schema_extra={"ui:placeholder": "e.g. 12345678"})
    target_id: str = Field(
        ..., title="Target ID", description="ID of the target entity (item/board)",
        json_schema_extra={"ui:placeholder": "e.g. 1234567890"},
    )
    target_type: str = Field(
        "Project",
        title="Target Type",
        description="Type of the target entity",
        json_schema_extra={
            "enum": ["Project", "Post"],
            "enumNames": ["Item/Board (Project)", "Update (Post)"],
            "x-enum-searchable": True,
        },
    )
    text: str = Field(..., title="Text", description="Notification text", json_schema_extra={"ui:placeholder": "Enter text..."})


class MondayListUsersConfig(BaseModel):
    """List account users."""

    operation: Literal["list_users"] = Field(
        "list_users",
        json_schema_extra={
            "const": "list_users",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "List Users",
        },
        title="List Users",
    )
    limit: Optional[str] = Field(
        "25", title="Limit", description="Max number of users to return",
        json_schema_extra={"ui:placeholder": "e.g. 25"},
    )
    emails: Optional[str] = Field(
        None, title="Emails", description="Filter to specific emails, comma-separated (optional)",
        json_schema_extra={"ui:placeholder": "e.g. user@example.com"},
    )


class MondayGetMeConfig(BaseModel):
    """Get the authenticated user's profile and account info."""

    operation: Literal["get_me"] = Field(
        "get_me",
        json_schema_extra={
            "const": "get_me",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Get Current User",
        },
        title="Get Current User",
    )


class MondayListWorkspacesConfig(BaseModel):
    """List workspaces in the account."""

    operation: Literal["list_workspaces"] = Field(
        "list_workspaces",
        json_schema_extra={
            "const": "list_workspaces",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "List Workspaces",
        },
        title="List Workspaces",
    )
    limit: Optional[str] = Field(
        "25", title="Limit", description="Max number of workspaces to return",
        json_schema_extra={"ui:placeholder": "e.g. 25"},
    )


class MondayCreateWebhookConfig(BaseModel):
    """Register a webhook on a board for an event type."""

    operation: Literal["create_webhook"] = Field(
        "create_webhook",
        json_schema_extra={
            "const": "create_webhook",
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-is-trigger": False,
            "x-display-name": "Create Webhook",
        },
        title="Create Webhook",
    )
    board_id: str = Field(
        ...,
        title="Board",
        description="The board to attach the webhook to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "board_id",
                "placeholder": "Select a board...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a board ID",
            },
            "x-resource-type": "monday_board",
        },
    )
    url: str = Field(..., title="URL", description="The subscriber URL to receive events", json_schema_extra={"ui:placeholder": "https://..."})
    event: str = Field(
        "create_item",
        title="Event",
        description="The board event to subscribe to",
        json_schema_extra={
            "enum": [
                "create_item",
                "change_column_value",
                "change_status_column_value",
                "change_specific_column_value",
                "change_name",
                "create_update",
                "edit_update",
                "delete_update",
                "item_archived",
                "item_deleted",
                "item_moved_to_group",
                "item_moved_to_any_group",
                "item_moved_to_specific_group",
                "item_restored",
                "create_subitem",
                "change_subitem_column_value",
                "change_subitem_name",
                "move_subitem",
                "subitem_archived",
                "subitem_deleted",
                "create_subitem_update",
                "create_column",
            ],
            "x-enum-searchable": True,
        },
    )


class MondayDeleteWebhookConfig(BaseModel):
    """Remove a webhook by ID."""

    operation: Literal["delete_webhook"] = Field(
        "delete_webhook",
        json_schema_extra={
            "const": "delete_webhook",
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-is-trigger": False,
            "x-display-name": "Delete Webhook",
        },
        title="Delete Webhook",
    )
    webhook_id: str = Field(..., title="Webhook ID", description="The webhook to delete", json_schema_extra={"ui:placeholder": "e.g. 1234567890"})


class MondayListWebhooksConfig(BaseModel):
    """List all webhooks registered on a board."""

    operation: Literal["list_webhooks"] = Field(
        "list_webhooks",
        json_schema_extra={
            "const": "list_webhooks",
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-is-trigger": False,
            "x-display-name": "List Webhooks",
        },
        title="List Webhooks",
    )
    board_id: str = Field(
        ...,
        title="Board",
        description="The board whose webhooks to list",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "board_id",
                "placeholder": "Select a board...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a board ID",
            },
            "x-resource-type": "monday_board",
        },
    )


# ============================================================================
# Board extended configs
# ============================================================================


class MondayUpdateBoardConfig(BaseModel):
    """Update a board's name, description, or communication settings."""

    operation: Literal["update_board"] = Field(
        "update_board",
        json_schema_extra={
            "const": "update_board",
            "ui:hidden": True,
            "x-category": "Boards",
            "x-is-trigger": False,
            "x-display-name": "Update Board",
        },
        title="Update Board",
    )
    board_id: str = Field(
        ...,
        title="Board",
        description="The board to update",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "board_id",
                "placeholder": "Select a board...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a board ID",
            },
            "x-resource-type": "monday_board",
        },
    )
    board_attribute: str = Field(
        "name",
        title="Attribute",
        description="Which board attribute to update",
        json_schema_extra={
            "enum": ["name", "description", "communication"],
            "enumNames": ["Name", "Description", "Communication (JSON)"],
            "x-enum-searchable": True,
        },
    )
    new_value: str = Field(..., title="New Value", description="The new value for the attribute", json_schema_extra={"ui:placeholder": "e.g. New Name"})


class MondayDeleteBoardConfig(BaseModel):
    """Permanently delete a board."""

    operation: Literal["delete_board"] = Field(
        "delete_board",
        json_schema_extra={
            "const": "delete_board",
            "ui:hidden": True,
            "x-category": "Boards",
            "x-is-trigger": False,
            "x-display-name": "Delete Board",
        },
        title="Delete Board",
    )
    board_id: str = Field(
        ...,
        title="Board",
        description="The board to delete",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "board_id",
                "placeholder": "Select a board...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a board ID",
            },
            "x-resource-type": "monday_board",
        },
    )


class MondayArchiveBoardConfig(BaseModel):
    """Archive a board."""

    operation: Literal["archive_board"] = Field(
        "archive_board",
        json_schema_extra={
            "const": "archive_board",
            "ui:hidden": True,
            "x-category": "Boards",
            "x-is-trigger": False,
            "x-display-name": "Archive Board",
        },
        title="Archive Board",
    )
    board_id: str = Field(
        ...,
        title="Board",
        description="The board to archive",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "board_id",
                "placeholder": "Select a board...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a board ID",
            },
            "x-resource-type": "monday_board",
        },
    )


class MondayDuplicateBoardConfig(BaseModel):
    """Duplicate a board (structure only, with items, or with items and updates)."""

    operation: Literal["duplicate_board"] = Field(
        "duplicate_board",
        json_schema_extra={
            "const": "duplicate_board",
            "ui:hidden": True,
            "x-category": "Boards",
            "x-is-trigger": False,
            "x-display-name": "Duplicate Board",
        },
        title="Duplicate Board",
    )
    board_id: str = Field(
        ...,
        title="Board",
        description="The board to duplicate",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "board_id",
                "placeholder": "Select a board...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a board ID",
            },
            "x-resource-type": "monday_board",
        },
    )
    duplicate_type: str = Field(
        "duplicate_board_with_structure",
        title="Duplicate Type",
        description="What to include in the duplicate",
        json_schema_extra={
            "enum": [
                "duplicate_board_with_structure",
                "duplicate_board_with_pulses",
                "duplicate_board_with_pulses_and_updates",
            ],
            "enumNames": [
                "Structure only (groups & columns)",
                "With items",
                "With items and updates",
            ],
            "x-enum-searchable": True,
        },
    )
    board_name: Optional[str] = Field(
        None, title="New Board Name", description="Name of the duplicated board (optional)",
        json_schema_extra={"ui:placeholder": "e.g. My Board"},
    )
    workspace_id: Optional[str] = Field(
        None, title="Workspace ID", description="Destination workspace (optional)",
        json_schema_extra={"ui:placeholder": "e.g. 1234567"},
    )


# ============================================================================
# Group extended configs
# ============================================================================


class MondayListGroupsConfig(BaseModel):
    """List all groups on a board."""

    operation: Literal["list_groups"] = Field(
        "list_groups",
        json_schema_extra={
            "const": "list_groups",
            "ui:hidden": True,
            "x-category": "Groups & Columns",
            "x-is-trigger": False,
            "x-display-name": "List Groups",
        },
        title="List Groups",
    )
    board_id: str = Field(
        ...,
        title="Board",
        description="The board whose groups to list",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "board_id",
                "placeholder": "Select a board...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a board ID",
            },
            "x-resource-type": "monday_board",
        },
    )


class MondayArchiveGroupConfig(BaseModel):
    """Archive a group and all its items."""

    operation: Literal["archive_group"] = Field(
        "archive_group",
        json_schema_extra={
            "const": "archive_group",
            "ui:hidden": True,
            "x-category": "Groups & Columns",
            "x-is-trigger": False,
            "x-display-name": "Archive Group",
        },
        title="Archive Group",
    )
    board_id: str = Field(
        ...,
        title="Board",
        description="The board the group belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "board_id",
                "placeholder": "Select a board...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a board ID",
            },
            "x-resource-type": "monday_board",
        },
    )
    group_id: str = Field(..., title="Group ID", description="The group to archive", json_schema_extra={"ui:placeholder": "e.g. topics"})


class MondayDuplicateGroupConfig(BaseModel):
    """Duplicate a group and all its items."""

    operation: Literal["duplicate_group"] = Field(
        "duplicate_group",
        json_schema_extra={
            "const": "duplicate_group",
            "ui:hidden": True,
            "x-category": "Groups & Columns",
            "x-is-trigger": False,
            "x-display-name": "Duplicate Group",
        },
        title="Duplicate Group",
    )
    board_id: str = Field(
        ...,
        title="Board",
        description="The board the group belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "board_id",
                "placeholder": "Select a board...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a board ID",
            },
            "x-resource-type": "monday_board",
        },
    )
    group_id: str = Field(..., title="Group ID", description="The group to duplicate", json_schema_extra={"ui:placeholder": "e.g. topics"})
    group_title: Optional[str] = Field(
        None, title="New Group Title", description="Title for the duplicated group (optional)",
        json_schema_extra={"ui:placeholder": "e.g. New Group"},
    )
    add_to_top: Optional[str] = Field(
        "false",
        title="Add To Top",
        description="Place the duplicate at the top of the board",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class MondayUpdateGroupConfig(BaseModel):
    """Rename or recolor a group."""

    operation: Literal["update_group"] = Field(
        "update_group",
        json_schema_extra={
            "const": "update_group",
            "ui:hidden": True,
            "x-category": "Groups & Columns",
            "x-is-trigger": False,
            "x-display-name": "Update Group",
        },
        title="Update Group",
    )
    board_id: str = Field(
        ...,
        title="Board",
        description="The board the group belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "board_id",
                "placeholder": "Select a board...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a board ID",
            },
            "x-resource-type": "monday_board",
        },
    )
    group_id: str = Field(..., title="Group ID", description="The group to update", json_schema_extra={"ui:placeholder": "e.g. topics"})
    group_attribute: str = Field(
        "title",
        title="Attribute",
        description="Which group attribute to update",
        json_schema_extra={
            "enum": ["title", "color"],
            "enumNames": ["Title", "Color (hex)"],
            "x-enum-searchable": True,
        },
    )
    new_value: str = Field(
        ...,
        title="New Value",
        description='New value for the attribute (e.g. "My Group" or "#FF5733" for color)',
        json_schema_extra={"ui:placeholder": "e.g. New Name"},
    )


# ============================================================================
# Column extended configs
# ============================================================================


class MondayDeleteColumnConfig(BaseModel):
    """Permanently delete a column from a board."""

    operation: Literal["delete_column"] = Field(
        "delete_column",
        json_schema_extra={
            "const": "delete_column",
            "ui:hidden": True,
            "x-category": "Groups & Columns",
            "x-is-trigger": False,
            "x-display-name": "Delete Column",
        },
        title="Delete Column",
    )
    board_id: str = Field(
        ...,
        title="Board",
        description="The board the column belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "board_id",
                "placeholder": "Select a board...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a board ID",
            },
            "x-resource-type": "monday_board",
        },
    )
    column_id: str = Field(..., title="Column ID", description="The column to delete", json_schema_extra={"ui:placeholder": "e.g. status"})


class MondayRenameColumnConfig(BaseModel):
    """Rename a column on a board."""

    operation: Literal["rename_column"] = Field(
        "rename_column",
        json_schema_extra={
            "const": "rename_column",
            "ui:hidden": True,
            "x-category": "Groups & Columns",
            "x-is-trigger": False,
            "x-display-name": "Rename Column",
        },
        title="Rename Column",
    )
    board_id: str = Field(
        ...,
        title="Board",
        description="The board the column belongs to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "board_id",
                "placeholder": "Select a board...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a board ID",
            },
            "x-resource-type": "monday_board",
        },
    )
    column_id: str = Field(..., title="Column ID", description="The column to rename", json_schema_extra={"ui:placeholder": "e.g. status"})
    title: str = Field(..., title="New Title", description="New title for the column", json_schema_extra={"ui:placeholder": "e.g. My Column"})


# ============================================================================
# Item extended configs
# ============================================================================


class MondayGetSubitemsConfig(BaseModel):
    """Get all subitems of a parent item."""

    operation: Literal["get_subitems"] = Field(
        "get_subitems",
        json_schema_extra={
            "const": "get_subitems",
            "ui:hidden": True,
            "x-category": "Items",
            "x-is-trigger": False,
            "x-display-name": "Get Subitems",
        },
        title="Get Subitems",
    )
    item_id: str = Field(..., title="Item ID", description="The parent item whose subitems to fetch", json_schema_extra={"ui:placeholder": "e.g. 1234567890"})


class MondayClearItemUpdatesConfig(BaseModel):
    """Clear all updates/comments from an item."""

    operation: Literal["clear_item_updates"] = Field(
        "clear_item_updates",
        json_schema_extra={
            "const": "clear_item_updates",
            "ui:hidden": True,
            "x-category": "Items",
            "x-is-trigger": False,
            "x-display-name": "Clear Item Updates",
        },
        title="Clear Item Updates",
    )
    item_id: str = Field(..., title="Item ID", description="The item whose updates to clear", json_schema_extra={"ui:placeholder": "e.g. 1234567890"})


# ============================================================================
# Updates & Comments extended configs
# ============================================================================


class MondayGetUpdatesConfig(BaseModel):
    """Get updates/comments on an item."""

    operation: Literal["get_updates"] = Field(
        "get_updates",
        json_schema_extra={
            "const": "get_updates",
            "ui:hidden": True,
            "x-category": "Updates & Notifications",
            "x-is-trigger": False,
            "x-display-name": "Get Item Updates",
        },
        title="Get Item Updates",
    )
    item_id: str = Field(..., title="Item ID", description="The item whose updates to fetch", json_schema_extra={"ui:placeholder": "e.g. 1234567890"})
    limit: Optional[str] = Field(
        "25", title="Limit", description="Max number of updates to return (max 100)",
        json_schema_extra={"ui:placeholder": "e.g. 25"},
    )


class MondayDeleteUpdateConfig(BaseModel):
    """Delete an update/comment."""

    operation: Literal["delete_update"] = Field(
        "delete_update",
        json_schema_extra={
            "const": "delete_update",
            "ui:hidden": True,
            "x-category": "Updates & Notifications",
            "x-is-trigger": False,
            "x-display-name": "Delete Update",
        },
        title="Delete Update",
    )
    update_id: str = Field(..., title="Update ID", description="The update to delete", json_schema_extra={"ui:placeholder": "e.g. 1234567890"})


class MondayEditUpdateConfig(BaseModel):
    """Edit an existing update/comment."""

    operation: Literal["edit_update"] = Field(
        "edit_update",
        json_schema_extra={
            "const": "edit_update",
            "ui:hidden": True,
            "x-category": "Updates & Notifications",
            "x-is-trigger": False,
            "x-display-name": "Edit Update",
        },
        title="Edit Update",
    )
    update_id: str = Field(..., title="Update ID", description="The update to edit", json_schema_extra={"ui:placeholder": "e.g. 1234567890"})
    body: str = Field(
        ...,
        title="Body",
        description="New content for the update (supports HTML)",
        json_schema_extra={"ui:widget": "textarea", "ui:placeholder": "Enter text..."},
    )


class MondayLikeUpdateConfig(BaseModel):
    """Like an update/comment."""

    operation: Literal["like_update"] = Field(
        "like_update",
        json_schema_extra={
            "const": "like_update",
            "ui:hidden": True,
            "x-category": "Updates & Notifications",
            "x-is-trigger": False,
            "x-display-name": "Like Update",
        },
        title="Like Update",
    )
    update_id: str = Field(..., title="Update ID", description="The update to like", json_schema_extra={"ui:placeholder": "e.g. 1234567890"})


# ============================================================================
# Tags configs
# ============================================================================


class MondayGetTagsConfig(BaseModel):
    """Get account-level tags."""

    operation: Literal["get_tags"] = Field(
        "get_tags",
        json_schema_extra={
            "const": "get_tags",
            "ui:hidden": True,
            "x-category": "Tags",
            "x-is-trigger": False,
            "x-display-name": "Get Tags",
        },
        title="Get Tags",
    )
    tag_ids: Optional[str] = Field(
        None,
        title="Tag IDs",
        description="Comma-separated tag IDs to filter (optional — omit to list all)",
        json_schema_extra={"ui:placeholder": "e.g. 123, 456"},
    )


class MondayCreateTagConfig(BaseModel):
    """Create or get an existing account-level tag."""

    operation: Literal["create_or_get_tag"] = Field(
        "create_or_get_tag",
        json_schema_extra={
            "const": "create_or_get_tag",
            "ui:hidden": True,
            "x-category": "Tags",
            "x-is-trigger": False,
            "x-display-name": "Create or Get Tag",
        },
        title="Create or Get Tag",
    )
    tag_name: str = Field(..., title="Tag Name", description="Name of the tag to create or retrieve", json_schema_extra={"ui:placeholder": "e.g. My Tag"})
    board_id: Optional[str] = Field(
        None,
        title="Board",
        description="The board to associate the tag with",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "board_id",
                "placeholder": "Select a board...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a board ID",
            },
            "x-resource-type": "monday_board",
        },
    )


# ============================================================================
# Teams configs
# ============================================================================


class MondayGetTeamsConfig(BaseModel):
    """List teams in the account."""

    operation: Literal["get_teams"] = Field(
        "get_teams",
        json_schema_extra={
            "const": "get_teams",
            "ui:hidden": True,
            "x-category": "Teams",
            "x-is-trigger": False,
            "x-display-name": "Get Teams",
        },
        title="Get Teams",
    )
    team_ids: Optional[str] = Field(
        None,
        title="Team IDs",
        description="Comma-separated team IDs to filter (optional — omit to list all)",
        json_schema_extra={"ui:placeholder": "e.g. 123, 456"},
    )


class MondayAddUsersToTeamConfig(BaseModel):
    """Add users to a team."""

    operation: Literal["add_users_to_team"] = Field(
        "add_users_to_team",
        json_schema_extra={
            "const": "add_users_to_team",
            "ui:hidden": True,
            "x-category": "Teams",
            "x-is-trigger": False,
            "x-display-name": "Add Users To Team",
        },
        title="Add Users To Team",
    )
    team_id: str = Field(..., title="Team ID", description="The team to add users to", json_schema_extra={"ui:placeholder": "e.g. 123456"})
    user_ids: str = Field(
        ..., title="User IDs", description="Comma-separated user IDs to add to the team",
        json_schema_extra={"ui:placeholder": "e.g. 123, 456"},
    )


class MondayRemoveUsersFromTeamConfig(BaseModel):
    """Remove users from a team."""

    operation: Literal["remove_users_from_team"] = Field(
        "remove_users_from_team",
        json_schema_extra={
            "const": "remove_users_from_team",
            "ui:hidden": True,
            "x-category": "Teams",
            "x-is-trigger": False,
            "x-display-name": "Remove Users From Team",
        },
        title="Remove Users From Team",
    )
    team_id: str = Field(..., title="Team ID", description="The team to remove users from", json_schema_extra={"ui:placeholder": "e.g. 123456"})
    user_ids: str = Field(
        ..., title="User IDs", description="Comma-separated user IDs to remove from the team",
        json_schema_extra={"ui:placeholder": "e.g. 123, 456"},
    )


# ============================================================================
# Webhook Trigger Config
# ============================================================================


class MondayGetDocsConfig(BaseModel):
    """List monday.com Docs, optionally filtered by workspace or specific doc IDs."""

    operation: Literal["get_docs"] = Field(
        "get_docs",
        json_schema_extra={"const": "get_docs", "ui:hidden": True, "x-category": "Docs"},
        title="Get Docs",
    )
    workspace_ids: Optional[str] = Field(
        None, title="Workspace IDs (comma-separated)", description="Filter docs by workspace IDs",
        json_schema_extra={"ui:placeholder": "e.g. 1234567"},
    )
    doc_ids: Optional[str] = Field(
        None, title="Doc IDs (comma-separated)", description="Fetch specific docs by ID",
        json_schema_extra={"ui:placeholder": "e.g. 1234567890"},
    )
    limit: Optional[str] = Field("25", title="Limit", description="Maximum results", json_schema_extra={"ui:placeholder": "e.g. 25"})
    page: Optional[str] = Field("1", title="Page", description="Page number for pagination", json_schema_extra={"ui:placeholder": "e.g. 1"})


class MondayCreateDocConfig(BaseModel):
    """Create a new monday.com Doc in a workspace."""

    operation: Literal["create_doc"] = Field(
        "create_doc",
        json_schema_extra={"const": "create_doc", "ui:hidden": True, "x-category": "Docs"},
        title="Create Doc",
    )
    workspace_id: str = Field(..., title="Workspace ID", description="Create the doc in this workspace", json_schema_extra={"ui:placeholder": "e.g. 1234567"})
    doc_name: str = Field("Untitled Doc", title="Doc Name", description="Name of the new doc", json_schema_extra={"ui:placeholder": "e.g. My Title"})
    doc_kind: str = Field(
        "public",
        title="Kind",
        json_schema_extra={"enum": ["public", "private"], "x-enum-searchable": True},
    )


class MondayCreateDocBlockConfig(BaseModel):
    """Add a content block to a monday.com Doc."""

    operation: Literal["create_doc_block"] = Field(
        "create_doc_block",
        json_schema_extra={"const": "create_doc_block", "ui:hidden": True, "x-category": "Docs"},
        title="Create Doc Block",
    )
    doc_id: str = Field(..., title="Doc ID", description="The doc to add the block to", json_schema_extra={"ui:placeholder": "e.g. 1234567890"})
    block_type: str = Field(
        "normal_text",
        title="Block Type",
        json_schema_extra={
            "enum": [
                "normal_text", "large_title", "medium_title", "small_title",
                "bulleted_list", "numbered_list", "check_list", "quote",
                "code", "divider", "notice_box", "image", "video",
            ],
            "x-enum-searchable": True,
        },
    )
    content: str = Field(
        ..., title="Content (JSON)", description='Block content as JSON, e.g. {"deltaFormat": [{"insert": "Hello"}]}',
        json_schema_extra={"ui:placeholder": "Enter content..."},
    )
    after_block_id: Optional[str] = Field(
        None, title="After Block ID", description="Insert after this block ID (default: end of doc)",
        json_schema_extra={"ui:placeholder": "e.g. block_id"},
    )


class MondayUpdateDocBlockConfig(BaseModel):
    """Update the content of an existing monday.com Doc block."""

    operation: Literal["update_doc_block"] = Field(
        "update_doc_block",
        json_schema_extra={"const": "update_doc_block", "ui:hidden": True, "x-category": "Docs"},
        title="Update Doc Block",
    )
    block_id: str = Field(..., title="Block ID", description="The block to update", json_schema_extra={"ui:placeholder": "e.g. block_id"})
    content: str = Field(
        ..., title="Content (JSON)", description='New block content as JSON, e.g. {"deltaFormat": [{"insert": "Updated"}]}',
        json_schema_extra={"ui:placeholder": "Enter content..."},
    )


class MondayDeleteDocBlockConfig(BaseModel):
    """Delete a block from a monday.com Doc."""

    operation: Literal["delete_doc_block"] = Field(
        "delete_doc_block",
        json_schema_extra={"const": "delete_doc_block", "ui:hidden": True, "x-category": "Docs"},
        title="Delete Doc Block",
    )
    block_id: str = Field(..., title="Block ID", description="The block to delete", json_schema_extra={"ui:placeholder": "e.g. block_id"})


class MondayGetAssetsConfig(BaseModel):
    """Get file assets (attachments) by their IDs."""

    operation: Literal["get_assets"] = Field(
        "get_assets",
        json_schema_extra={"const": "get_assets", "ui:hidden": True, "x-category": "Files"},
        title="Get Assets",
    )
    asset_ids: str = Field(
        ..., title="Asset IDs (comma-separated)", description="IDs of assets to fetch",
        json_schema_extra={"ui:placeholder": "e.g. 123, 456"},
    )


class MondayCreateWorkspaceConfig(BaseModel):
    """Create a new monday.com workspace."""

    operation: Literal["create_workspace"] = Field(
        "create_workspace",
        json_schema_extra={"const": "create_workspace", "ui:hidden": True, "x-category": "Workspaces"},
        title="Create Workspace",
    )
    name: str = Field(..., title="Name", description="Workspace name", json_schema_extra={"ui:placeholder": "e.g. My Board"})
    kind: str = Field(
        "open",
        title="Kind",
        json_schema_extra={"enum": ["open", "closed"], "x-enum-searchable": True},
    )
    description: Optional[str] = Field(None, title="Description", json_schema_extra={"ui:placeholder": "e.g. This board tracks..."})


class MondayUpdateWorkspaceConfig(BaseModel):
    """Update a monday.com workspace's name, kind, or description."""

    operation: Literal["update_workspace"] = Field(
        "update_workspace",
        json_schema_extra={"const": "update_workspace", "ui:hidden": True, "x-category": "Workspaces"},
        title="Update Workspace",
    )
    workspace_id: str = Field(..., title="Workspace ID", json_schema_extra={"ui:placeholder": "e.g. 1234567"})
    name: Optional[str] = Field(None, title="New Name", json_schema_extra={"ui:placeholder": "e.g. New Name"})
    description: Optional[str] = Field(None, title="New Description", json_schema_extra={"ui:placeholder": "e.g. This board tracks..."})
    kind: Optional[str] = Field(
        None,
        title="Kind",
        json_schema_extra={"enum": ["", "open", "closed"], "x-enum-searchable": True},
    )


class MondayDeleteWorkspaceConfig(BaseModel):
    """Permanently delete a monday.com workspace."""

    operation: Literal["delete_workspace"] = Field(
        "delete_workspace",
        json_schema_extra={"const": "delete_workspace", "ui:hidden": True, "x-category": "Workspaces"},
        title="Delete Workspace",
    )
    workspace_id: str = Field(..., title="Workspace ID", json_schema_extra={"ui:placeholder": "e.g. 1234567"})


class MondayAddUsersToBoardConfig(BaseModel):
    """Subscribe users to a board as subscribers or owners."""

    operation: Literal["add_users_to_board"] = Field(
        "add_users_to_board",
        json_schema_extra={"const": "add_users_to_board", "ui:hidden": True, "x-category": "Boards"},
        title="Add Users to Board",
    )
    board_id: str = Field(
        ...,
        title="Board",
        description="The board to add users to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "board_id",
                "placeholder": "Select a board...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a board ID",
            },
            "x-resource-type": "monday_board",
        },
    )
    user_ids: str = Field(..., title="User IDs (comma-separated)", json_schema_extra={"ui:placeholder": "e.g. 123, 456"})
    kind: str = Field(
        "subscriber",
        title="Role",
        json_schema_extra={"enum": ["subscriber", "owner"], "x-enum-searchable": True},
    )


class MondayRemoveUsersFromBoardConfig(BaseModel):
    """Remove subscribers from a board."""

    operation: Literal["remove_users_from_board"] = Field(
        "remove_users_from_board",
        json_schema_extra={"const": "remove_users_from_board", "ui:hidden": True, "x-category": "Boards"},
        title="Remove Users from Board",
    )
    board_id: str = Field(
        ...,
        title="Board",
        description="The board to remove users from",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "board_id",
                "placeholder": "Select a board...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a board ID",
            },
            "x-resource-type": "monday_board",
        },
    )
    user_ids: str = Field(..., title="User IDs (comma-separated)", json_schema_extra={"ui:placeholder": "e.g. 123, 456"})


class MondayAddTeamsToBoardConfig(BaseModel):
    """Add teams as subscribers to a board."""

    operation: Literal["add_teams_to_board"] = Field(
        "add_teams_to_board",
        json_schema_extra={"const": "add_teams_to_board", "ui:hidden": True, "x-category": "Boards"},
        title="Add Teams to Board",
    )
    board_id: str = Field(
        ...,
        title="Board",
        description="The board to add teams to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "board_id",
                "placeholder": "Select a board...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a board ID",
            },
            "x-resource-type": "monday_board",
        },
    )
    team_ids: str = Field(..., title="Team IDs (comma-separated)", json_schema_extra={"ui:placeholder": "e.g. 123, 456"})
    kind: str = Field(
        "subscriber",
        title="Role",
        json_schema_extra={"enum": ["subscriber", "owner"], "x-enum-searchable": True},
    )


class MondayListFoldersConfig(BaseModel):
    """List folders in a workspace."""

    operation: Literal["list_folders"] = Field(
        "list_folders",
        json_schema_extra={"const": "list_folders", "ui:hidden": True, "x-category": "Folders"},
        title="List Folders",
    )
    workspace_ids: Optional[str] = Field(
        None, title="Workspace IDs (comma-separated)", description="Filter by workspace",
        json_schema_extra={"ui:placeholder": "e.g. 1234567"},
    )
    limit: Optional[str] = Field("25", title="Limit", json_schema_extra={"ui:placeholder": "e.g. 25"})
    page: Optional[str] = Field("1", title="Page", json_schema_extra={"ui:placeholder": "e.g. 1"})


class MondayCreateFolderConfig(BaseModel):
    """Create a folder in a workspace to organize boards."""

    operation: Literal["create_folder"] = Field(
        "create_folder",
        json_schema_extra={"const": "create_folder", "ui:hidden": True, "x-category": "Folders"},
        title="Create Folder",
    )
    name: str = Field(..., title="Folder Name", json_schema_extra={"ui:placeholder": "e.g. My Board"})
    workspace_id: Optional[str] = Field(None, title="Workspace ID", json_schema_extra={"ui:placeholder": "e.g. 1234567"})
    parent_folder_id: Optional[str] = Field(None, title="Parent Folder ID", description="Nest inside this folder", json_schema_extra={"ui:placeholder": "e.g. 1234567"})


class MondayUpdateFolderConfig(BaseModel):
    """Rename or move a folder."""

    operation: Literal["update_folder"] = Field(
        "update_folder",
        json_schema_extra={"const": "update_folder", "ui:hidden": True, "x-category": "Folders"},
        title="Update Folder",
    )
    folder_id: str = Field(..., title="Folder ID", json_schema_extra={"ui:placeholder": "e.g. 1234567"})
    name: Optional[str] = Field(None, title="New Name", json_schema_extra={"ui:placeholder": "e.g. New Name"})
    parent_folder_id: Optional[str] = Field(None, title="New Parent Folder ID", json_schema_extra={"ui:placeholder": "e.g. 1234567"})


class MondayDeleteFolderConfig(BaseModel):
    """Delete a folder."""

    operation: Literal["delete_folder"] = Field(
        "delete_folder",
        json_schema_extra={"const": "delete_folder", "ui:hidden": True, "x-category": "Folders"},
        title="Delete Folder",
    )
    folder_id: str = Field(..., title="Folder ID", json_schema_extra={"ui:placeholder": "e.g. 1234567"})


class MondayCreateTeamConfig(BaseModel):
    """Create a new team in the account."""

    operation: Literal["create_team"] = Field(
        "create_team",
        json_schema_extra={"const": "create_team", "ui:hidden": True, "x-category": "Teams"},
        title="Create Team",
    )
    name: str = Field(..., title="Team Name", json_schema_extra={"ui:placeholder": "e.g. My Board"})
    subscriber_ids: Optional[str] = Field(
        None, title="Member User IDs (comma-separated)", description="Initial team members",
        json_schema_extra={"ui:placeholder": "e.g. 123, 456"},
    )
    is_guest_team: Optional[str] = Field(
        "false",
        title="Guest Team",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )


class MondayDeleteTeamConfig(BaseModel):
    """Delete a team from the account."""

    operation: Literal["delete_team"] = Field(
        "delete_team",
        json_schema_extra={"const": "delete_team", "ui:hidden": True, "x-category": "Teams"},
        title="Delete Team",
    )
    team_id: str = Field(..., title="Team ID", json_schema_extra={"ui:placeholder": "e.g. 123456"})


class MondayUnlikeUpdateConfig(BaseModel):
    """Remove a like from an update (comment)."""

    operation: Literal["unlike_update"] = Field(
        "unlike_update",
        json_schema_extra={"const": "unlike_update", "ui:hidden": True, "x-category": "Updates"},
        title="Unlike Update",
    )
    update_id: str = Field(..., title="Update ID", description="The update to unlike", json_schema_extra={"ui:placeholder": "e.g. 1234567890"})


class MondayBoardEventTriggerConfig(BaseModel):
    """Fire the workflow when a board event occurs (new item, column change, etc.)."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["on_board_event"] = Field(
        "on_board_event",
        json_schema_extra={
            "const": "on_board_event",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Board Event",
        },
        title="On Board Event",
    )
    board_id: str = Field(
        ...,
        title="Board",
        description="The board to watch for events",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "board_id",
                "placeholder": "Select a board...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a board ID",
            },
            "x-resource-type": "monday_board",
        },
    )
    event: str = Field(
        "create_item",
        title="Event",
        description="The board event to trigger on",
        json_schema_extra={
            "enum": [
                "create_item",
                "change_column_value",
                "change_status_column_value",
                "change_specific_column_value",
                "change_name",
                "create_update",
                "edit_update",
                "delete_update",
                "item_archived",
                "item_deleted",
                "item_moved_to_group",
                "item_moved_to_any_group",
                "item_moved_to_specific_group",
                "item_restored",
                "create_subitem",
                "change_subitem_column_value",
                "change_subitem_name",
                "move_subitem",
                "subitem_archived",
                "subitem_deleted",
                "create_subitem_update",
                "create_column",
            ],
            "x-enum-searchable": True,
        },
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="monday.com posts board events here. Registered automatically when you connect credentials.",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:copyable": True,
            "ui:loadValue": True,
        },
    )
    webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    external_webhook_id: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    signing_secret: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    relay_connected: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    is_production: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    trigger_registered: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    trigger_error: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})


# ============================================================================
# Discriminated Union
# ============================================================================


MondayConfig = Annotated[
    Union[
        # Boards
        MondayListBoardsConfig,
        MondayGetBoardConfig,
        MondayCreateBoardConfig,
        MondayUpdateBoardConfig,
        MondayDeleteBoardConfig,
        MondayArchiveBoardConfig,
        MondayDuplicateBoardConfig,
        # Items
        MondayListItemsConfig,
        MondayGetItemsConfig,
        MondayQueryItemsByColumnConfig,
        MondayCreateItemConfig,
        MondayCreateSubitemConfig,
        MondayChangeColumnValueConfig,
        MondayChangeMultipleColumnValuesConfig,
        MondayChangeSimpleColumnValueConfig,
        MondayMoveItemToGroupConfig,
        MondayMoveItemToBoardConfig,
        MondayArchiveItemConfig,
        MondayDeleteItemConfig,
        MondayDuplicateItemConfig,
        MondayGetSubitemsConfig,
        MondayClearItemUpdatesConfig,
        # Groups & Columns
        MondayCreateGroupConfig,
        MondayDeleteGroupConfig,
        MondayListGroupsConfig,
        MondayArchiveGroupConfig,
        MondayDuplicateGroupConfig,
        MondayUpdateGroupConfig,
        MondayCreateColumnConfig,
        MondayDeleteColumnConfig,
        MondayRenameColumnConfig,
        # Updates & Notifications
        MondayCreateUpdateConfig,
        MondayCreateNotificationConfig,
        MondayGetUpdatesConfig,
        MondayDeleteUpdateConfig,
        MondayEditUpdateConfig,
        MondayLikeUpdateConfig,
        # Tags
        MondayGetTagsConfig,
        MondayCreateTagConfig,
        # Teams
        MondayGetTeamsConfig,
        MondayAddUsersToTeamConfig,
        MondayRemoveUsersFromTeamConfig,
        MondayCreateTeamConfig,
        MondayDeleteTeamConfig,
        # Account
        MondayListUsersConfig,
        MondayGetMeConfig,
        MondayListWorkspacesConfig,
        MondayCreateWorkspaceConfig,
        MondayUpdateWorkspaceConfig,
        MondayDeleteWorkspaceConfig,
        # Boards membership
        MondayAddUsersToBoardConfig,
        MondayRemoveUsersFromBoardConfig,
        MondayAddTeamsToBoardConfig,
        # Folders
        MondayListFoldersConfig,
        MondayCreateFolderConfig,
        MondayUpdateFolderConfig,
        MondayDeleteFolderConfig,
        # Docs
        MondayGetDocsConfig,
        MondayCreateDocConfig,
        MondayCreateDocBlockConfig,
        MondayUpdateDocBlockConfig,
        MondayDeleteDocBlockConfig,
        # Assets
        MondayGetAssetsConfig,
        # Updates (extended)
        MondayUnlikeUpdateConfig,
        # Webhooks
        MondayCreateWebhookConfig,
        MondayDeleteWebhookConfig,
        MondayListWebhooksConfig,
        # Trigger
        MondayBoardEventTriggerConfig,
    ],
    Discriminator("operation"),
]


class MondayNodeConfig(NodeConfig[MondayConfig, MondayCredential]):
    """Full configuration for the monday.com node including credentials."""

    pass


# ============================================================================
# Helpers
# ============================================================================


def _comma_list(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [p.strip() for p in value.split(",") if p.strip()]


def _to_int_list(value: Optional[str]) -> List[int]:
    return [int(p) for p in _comma_list(value) if p.lstrip("-").isdigit()]


def _credential_auth_token(credential: Dict[str, Any]) -> Optional[str]:
    """Extract the bare Authorization token from a decrypted credential dict.

    monday.com sends both personal tokens and OAuth access tokens as the raw
    Authorization header value (NO ``Bearer`` prefix).
    """
    credential = credential or {}
    return credential.get("api_token") or credential.get("access_token")


async def _monday_graphql(
    auth_token: str,
    query: str,
    variables: Optional[Dict[str, Any]],
    action_name: str = "request",
) -> Dict[str, Any]:
    """Execute a monday.com GraphQL request and return a structured result.

    monday returns HTTP 200 with an ``errors`` array on GraphQL / rate-limit
    failures, so this inspects the JSON body rather than relying on status code.
    """
    headers = {
        "Authorization": auth_token,  # bare token — monday does NOT use Bearer
        "Content-Type": "application/json",
        "API-Version": MONDAY_API_VERSION,
    }
    body = {"query": query, "variables": variables or {}}

    start = time.time()
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.request(
                method="POST", url=MONDAY_API_BASE, headers=headers, json=body
            )
            api_ms = round((time.time() - start) * 1000, 2)

            if response.status_code >= 400:
                message = response.text
                logger.error(f"[MondayNode] HTTP error ({action_name}): {message}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": message,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }

            try:
                payload = response.json()
            except Exception:
                return {
                    "status": "error",
                    "action": action_name,
                    "error": response.text,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }

            # monday surfaces GraphQL + rate-limit failures in the body.
            errors = payload.get("errors") if isinstance(payload, dict) else None
            error_msg = payload.get("error_message") if isinstance(payload, dict) else None
            if errors or error_msg:
                message = errors if errors else error_msg
                if isinstance(message, list):
                    message = "; ".join(
                        e.get("message", str(e)) if isinstance(e, dict) else str(e)
                        for e in message
                    )
                logger.error(f"[MondayNode] GraphQL error ({action_name}): {message}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": message,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }

            data = payload.get("data", payload) if isinstance(payload, dict) else payload
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
            logger.error(f"[MondayNode] Request failed ({action_name}): {msg}")
            return {
                "status": "error",
                "action": action_name,
                "error": msg,
                "status_code": 500,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }


# ============================================================================
# Node Implementation
# ============================================================================


class MondayNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """monday.com work-management automation node."""

    edit_examples = [
        "List all boards in my account",
        "Create an item on the Tasks board with a status of Working on it",
        "Update the status column of an item when a deal closes",
        "Post a comment on an item when a workflow finishes",
        "Trigger a workflow whenever a new item is created on a board",
    ]

    scope_registry = MONDAY_SCOPES
    connection_evidence = ConnectionEvidence(
        field="board_id",
        noun="boards",
    )

    @classmethod
    def get_config_model(cls):
        return MondayNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        """Refresh an expiring monday OAuth token at credential load (dropdowns,
        trigger registration). No-op for personal API tokens (no refresh_token)
        and for non-expiring monday OAuth tokens that carry no refresh_token."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.monday_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token,
            provider="monday",
        )

    # ------------------------------------------------------------------
    # Dynamic options (boards)
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
        if field_name != "board_id":
            return {"options": []}
        auth_token = _credential_auth_token(credential_data or {})
        if not auth_token:
            return {"options": []}

        query = "query { boards (limit: 100) { id name } }"
        result = await _monday_graphql(auth_token, query, {}, action_name="list_boards")
        if result.get("status") != "success":
            return {"options": []}
        boards = ((result.get("data") or {}).get("boards")) or []
        options = []
        for board in boards:
            if not isinstance(board, dict):
                continue
            board_id = board.get("id")
            name = board.get("name") or f"Board {board_id}"
            if board_id is not None:
                options.append({"label": str(name), "value": str(board_id)})
        return {"options": options}

    # ------------------------------------------------------------------
    # Webhook trigger registration
    # ------------------------------------------------------------------
    @classmethod
    def registration_fingerprint_fields(cls, config):
        # Config fields the provider-side registration depends on — feed the
        # reconciler's fingerprint so edits here re-register (declarative:
        # the node never sequences teardown/re-register).
        return {
            "board_id": (config or {}).get("board_id"),
            "event": (config or {}).get("event"),
        }

    @classmethod
    async def _register_external_webhook(
        cls, *, webhook_url: str, credential: Dict[str, Any], config: Dict[str, Any], node_id: str
    ) -> Optional[Dict[str, Any]]:
        auth_token = _credential_auth_token(credential)
        if not auth_token:
            raise ValueError("A monday.com API token is required to register the trigger")
        board_id = (config or {}).get("board_id")
        if not board_id:
            raise ValueError("A board must be selected to register the trigger")
        event = (config or {}).get("event") or DEFAULT_TRIGGER_EVENT

        query = (
            "mutation ($boardId: ID!, $url: String!, $event: WebhookEventType!) {"
            " create_webhook (board_id: $boardId, url: $url, event: $event) { id board_id }"
            " }"
        )
        variables = {"boardId": str(board_id), "url": webhook_url, "event": event}
        result = await _monday_graphql(
            auth_token, query, variables, action_name="register_webhook"
        )
        if result.get("status") != "success":
            raise ValueError(f"monday.com webhook registration failed: {result.get('error')}")
        webhook = ((result.get("data") or {}).get("create_webhook")) or {}
        external_id = webhook.get("id")
        # monday's webhook handshake echoes a challenge; it does not sign payloads,
        # so we derive a per-node secret used only as a soft token if monday ever
        # adds signing. Today verify_webhook_signature accepts the challenge flow.
        secret = hashlib.sha256(f"{node_id}:{webhook_url}".encode()).hexdigest()[:32]
        return {
            "external_webhook_id": str(external_id) if external_id else None,
            "signing_secret": secret,
        }

    @classmethod
    async def _unregister_external_webhook(
        cls, *, credential: Optional[Dict[str, Any]], config: Dict[str, Any], node_id: str
    ) -> None:
        external_id = (config or {}).get("external_webhook_id")
        auth_token = _credential_auth_token(credential or {})
        if not external_id or not auth_token:
            return
        query = "mutation ($id: ID!) { delete_webhook (id: $id) { id } }"
        await _monday_graphql(
            auth_token, query, {"id": str(external_id)}, action_name="unregister_webhook"
        )

    @classmethod
    def handle_webhook_handshake(
        cls, body: bytes, headers: Dict[str, str],
        config: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Echo monday.com's one-off challenge on webhook registration.

        When monday first calls the webhook URL it sends {"challenge": "<token>"}
        and expects exactly {"challenge": "<token>"} back before persisting the
        subscription.  Any other body falls through to normal workflow dispatch.
        """
        try:
            data = json.loads(body) if body else {}
        except (json.JSONDecodeError, ValueError):
            return None
        challenge = data.get("challenge")
        if challenge is not None:
            return {"challenge": challenge}
        return None

    @classmethod
    def verify_webhook_signature(
        cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]
    ) -> bool:
        """monday.com does not sign webhook payloads — event payloads are accepted as-is."""
        return True

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, MondayNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        if isinstance(op, MondayBoardEventTriggerConfig):
            return {
                "status": "success",
                "action": "on_board_event",
                "data": {**inputs, "webhook_url": op.webhook_url},
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your monday.com API token.")
        auth_token = (
            credentials.api_token
            if isinstance(credentials, MondayApiTokenCredential)
            else credentials.access_token
        )

        handlers = {
            # Boards
            "list_boards": self._list_boards,
            "get_board": self._get_board,
            "create_board": self._create_board,
            "update_board": self._update_board,
            "delete_board": self._delete_board,
            "archive_board": self._archive_board,
            "duplicate_board": self._duplicate_board,
            # Items
            "list_items": self._list_items,
            "get_items": self._get_items,
            "query_items_by_column": self._query_items_by_column,
            "create_item": self._create_item,
            "create_subitem": self._create_subitem,
            "change_column_value": self._change_column_value,
            "change_multiple_column_values": self._change_multiple_column_values,
            "change_simple_column_value": self._change_simple_column_value,
            "move_item_to_group": self._move_item_to_group,
            "move_item_to_board": self._move_item_to_board,
            "archive_item": self._archive_item,
            "delete_item": self._delete_item,
            "duplicate_item": self._duplicate_item,
            "get_subitems": self._get_subitems,
            "clear_item_updates": self._clear_item_updates,
            # Groups & Columns
            "create_group": self._create_group,
            "delete_group": self._delete_group,
            "list_groups": self._list_groups,
            "archive_group": self._archive_group,
            "duplicate_group": self._duplicate_group,
            "update_group": self._update_group,
            "create_column": self._create_column,
            "delete_column": self._delete_column,
            "rename_column": self._rename_column,
            # Updates & Notifications
            "create_update": self._create_update,
            "create_notification": self._create_notification,
            "get_updates": self._get_updates,
            "delete_update": self._delete_update,
            "edit_update": self._edit_update,
            "like_update": self._like_update,
            # Tags
            "get_tags": self._get_tags,
            "create_or_get_tag": self._create_or_get_tag,
            # Teams
            "get_teams": self._get_teams,
            "add_users_to_team": self._add_users_to_team,
            "remove_users_from_team": self._remove_users_from_team,
            # Account
            "list_users": self._list_users,
            "get_me": self._get_me,
            "list_workspaces": self._list_workspaces,
            # Webhooks
            "create_webhook": self._create_webhook,
            "delete_webhook": self._delete_webhook,
            "list_webhooks": self._list_webhooks,
            # Teams (extended)
            "create_team": self._create_team,
            "delete_team": self._delete_team,
            # Workspaces (extended)
            "create_workspace": self._create_workspace,
            "update_workspace": self._update_workspace,
            "delete_workspace": self._delete_workspace,
            # Board membership
            "add_users_to_board": self._add_users_to_board,
            "remove_users_from_board": self._remove_users_from_board,
            "add_teams_to_board": self._add_teams_to_board,
            # Folders
            "list_folders": self._list_folders,
            "create_folder": self._create_folder,
            "update_folder": self._update_folder,
            "delete_folder": self._delete_folder,
            # Docs
            "get_docs": self._get_docs,
            "create_doc": self._create_doc,
            "create_doc_block": self._create_doc_block,
            "update_doc_block": self._update_doc_block,
            "delete_doc_block": self._delete_doc_block,
            # Assets
            "get_assets": self._get_assets,
            # Updates (extended)
            "unlike_update": self._unlike_update,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(op, auth_token)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # Board handlers
    # ------------------------------------------------------------------
    async def _list_boards(self, c: MondayListBoardsConfig, auth: str) -> Dict[str, Any]:
        query = (
            "query ($limit: Int, $page: Int, $workspaceIds: [ID!]) {"
            " boards (limit: $limit, page: $page, workspace_ids: $workspaceIds) {"
            " id name board_kind state workspace_id"
            " groups { id title } columns { id title type } } }"
        )
        variables = {
            "limit": int(c.limit) if c.limit and str(c.limit).isdigit() else 25,
            "page": int(c.page) if c.page and str(c.page).isdigit() else 1,
            "workspaceIds": [c.workspace_id] if c.workspace_id else None,
        }
        return await _monday_graphql(auth, query, variables, action_name="list_boards")

    async def _get_board(self, c: MondayGetBoardConfig, auth: str) -> Dict[str, Any]:
        query = (
            "query ($ids: [ID!]) { boards (ids: $ids) {"
            " id name board_kind description state"
            " groups { id title color } columns { id title type settings_str } } }"
        )
        return await _monday_graphql(
            auth, query, {"ids": [c.board_id]}, action_name="get_board"
        )

    async def _create_board(self, c: MondayCreateBoardConfig, auth: str) -> Dict[str, Any]:
        query = (
            "mutation ($name: String!, $kind: BoardKind!, $workspaceId: ID, $templateId: ID) {"
            " create_board (board_name: $name, board_kind: $kind, workspace_id: $workspaceId,"
            " template_id: $templateId) { id name } }"
        )
        variables = {
            "name": c.board_name,
            "kind": c.board_kind,
            "workspaceId": c.workspace_id or None,
            "templateId": c.template_id or None,
        }
        return await _monday_graphql(auth, query, variables, action_name="create_board")

    # ------------------------------------------------------------------
    # Item handlers
    # ------------------------------------------------------------------
    async def _list_items(self, c: MondayListItemsConfig, auth: str) -> Dict[str, Any]:
        query = (
            "query ($ids: [ID!], $limit: Int, $cursor: String) {"
            " boards (ids: $ids) { items_page (limit: $limit, cursor: $cursor) {"
            " cursor items { id name group { id title } column_values { id text value } } } } }"
        )
        variables = {
            "ids": [c.board_id],
            "limit": int(c.limit) if c.limit and str(c.limit).isdigit() else 25,
            "cursor": c.cursor or None,
        }
        return await _monday_graphql(auth, query, variables, action_name="list_items")

    async def _get_items(self, c: MondayGetItemsConfig, auth: str) -> Dict[str, Any]:
        query = (
            "query ($ids: [ID!]) { items (ids: $ids) {"
            " id name state board { id name } group { id title }"
            " column_values { id text value type } } }"
        )
        return await _monday_graphql(
            auth, query, {"ids": _comma_list(c.item_ids)}, action_name="get_items"
        )

    async def _query_items_by_column(
        self, c: MondayQueryItemsByColumnConfig, auth: str
    ) -> Dict[str, Any]:
        query = (
            "query ($boardId: ID!, $columns: [ItemsPageByColumnValuesQuery!], $limit: Int) {"
            " items_page_by_column_values (board_id: $boardId, columns: $columns, limit: $limit) {"
            " cursor items { id name column_values { id text value } } } }"
        )
        variables = {
            "boardId": c.board_id,
            "columns": [
                {"column_id": c.column_id, "column_values": _comma_list(c.column_values)}
            ],
            "limit": int(c.limit) if c.limit and str(c.limit).isdigit() else 25,
        }
        return await _monday_graphql(
            auth, query, variables, action_name="query_items_by_column"
        )

    async def _create_item(self, c: MondayCreateItemConfig, auth: str) -> Dict[str, Any]:
        query = (
            "mutation ($boardId: ID!, $groupId: String, $itemName: String!,"
            " $columnValues: JSON, $createLabels: Boolean) {"
            " create_item (board_id: $boardId, group_id: $groupId, item_name: $itemName,"
            " column_values: $columnValues, create_labels_if_missing: $createLabels)"
            " { id name } }"
        )
        variables = {
            "boardId": c.board_id,
            "groupId": c.group_id or None,
            "itemName": c.item_name,
            "columnValues": c.column_values or None,
            "createLabels": c.create_labels_if_missing == "true",
        }
        return await _monday_graphql(auth, query, variables, action_name="create_item")

    async def _create_subitem(self, c: MondayCreateSubitemConfig, auth: str) -> Dict[str, Any]:
        query = (
            "mutation ($parentItemId: ID!, $itemName: String!, $columnValues: JSON) {"
            " create_subitem (parent_item_id: $parentItemId, item_name: $itemName,"
            " column_values: $columnValues) { id name } }"
        )
        variables = {
            "parentItemId": c.parent_item_id,
            "itemName": c.item_name,
            "columnValues": c.column_values or None,
        }
        return await _monday_graphql(auth, query, variables, action_name="create_subitem")

    async def _change_column_value(
        self, c: MondayChangeColumnValueConfig, auth: str
    ) -> Dict[str, Any]:
        query = (
            "mutation ($boardId: ID!, $itemId: ID!, $columnId: String!, $value: JSON!,"
            " $createLabels: Boolean) {"
            " change_column_value (board_id: $boardId, item_id: $itemId, column_id: $columnId,"
            " value: $value, create_labels_if_missing: $createLabels) { id } }"
        )
        variables = {
            "boardId": c.board_id,
            "itemId": c.item_id,
            "columnId": c.column_id,
            "value": c.value,
            "createLabels": c.create_labels_if_missing == "true",
        }
        return await _monday_graphql(auth, query, variables, action_name="change_column_value")

    async def _change_multiple_column_values(
        self, c: MondayChangeMultipleColumnValuesConfig, auth: str
    ) -> Dict[str, Any]:
        query = (
            "mutation ($boardId: ID!, $itemId: ID!, $columnValues: JSON!, $createLabels: Boolean) {"
            " change_multiple_column_values (board_id: $boardId, item_id: $itemId,"
            " column_values: $columnValues, create_labels_if_missing: $createLabels) { id } }"
        )
        variables = {
            "boardId": c.board_id,
            "itemId": c.item_id,
            "columnValues": c.column_values,
            "createLabels": c.create_labels_if_missing == "true",
        }
        return await _monday_graphql(
            auth, query, variables, action_name="change_multiple_column_values"
        )

    async def _change_simple_column_value(
        self, c: MondayChangeSimpleColumnValueConfig, auth: str
    ) -> Dict[str, Any]:
        query = (
            "mutation ($boardId: ID!, $itemId: ID!, $columnId: String!, $value: String) {"
            " change_simple_column_value (board_id: $boardId, item_id: $itemId,"
            " column_id: $columnId, value: $value) { id } }"
        )
        variables = {
            "boardId": c.board_id,
            "itemId": c.item_id,
            "columnId": c.column_id,
            "value": c.value,
        }
        return await _monday_graphql(
            auth, query, variables, action_name="change_simple_column_value"
        )

    async def _move_item_to_group(
        self, c: MondayMoveItemToGroupConfig, auth: str
    ) -> Dict[str, Any]:
        query = (
            "mutation ($itemId: ID!, $groupId: String!) {"
            " move_item_to_group (item_id: $itemId, group_id: $groupId) { id } }"
        )
        return await _monday_graphql(
            auth, query, {"itemId": c.item_id, "groupId": c.group_id},
            action_name="move_item_to_group",
        )

    async def _move_item_to_board(
        self, c: MondayMoveItemToBoardConfig, auth: str
    ) -> Dict[str, Any]:
        query = (
            "mutation ($boardId: ID!, $groupId: ID!, $itemId: ID!) {"
            " move_item_to_board (board_id: $boardId, group_id: $groupId, item_id: $itemId)"
            " { id } }"
        )
        variables = {"boardId": c.board_id, "groupId": c.group_id, "itemId": c.item_id}
        return await _monday_graphql(
            auth, query, variables, action_name="move_item_to_board"
        )

    async def _archive_item(self, c: MondayArchiveItemConfig, auth: str) -> Dict[str, Any]:
        query = "mutation ($itemId: ID!) { archive_item (item_id: $itemId) { id } }"
        return await _monday_graphql(
            auth, query, {"itemId": c.item_id}, action_name="archive_item"
        )

    async def _delete_item(self, c: MondayDeleteItemConfig, auth: str) -> Dict[str, Any]:
        query = "mutation ($itemId: ID!) { delete_item (item_id: $itemId) { id } }"
        return await _monday_graphql(
            auth, query, {"itemId": c.item_id}, action_name="delete_item"
        )

    async def _duplicate_item(self, c: MondayDuplicateItemConfig, auth: str) -> Dict[str, Any]:
        query = (
            "mutation ($boardId: ID!, $itemId: ID!, $withUpdates: Boolean) {"
            " duplicate_item (board_id: $boardId, item_id: $itemId,"
            " with_updates: $withUpdates) { id name } }"
        )
        variables = {
            "boardId": c.board_id,
            "itemId": c.item_id,
            "withUpdates": c.with_updates == "true",
        }
        return await _monday_graphql(auth, query, variables, action_name="duplicate_item")

    # ------------------------------------------------------------------
    # Group & column handlers
    # ------------------------------------------------------------------
    async def _create_group(self, c: MondayCreateGroupConfig, auth: str) -> Dict[str, Any]:
        query = (
            "mutation ($boardId: ID!, $groupName: String!) {"
            " create_group (board_id: $boardId, group_name: $groupName) { id title } }"
        )
        return await _monday_graphql(
            auth, query, {"boardId": c.board_id, "groupName": c.group_name},
            action_name="create_group",
        )

    async def _delete_group(self, c: MondayDeleteGroupConfig, auth: str) -> Dict[str, Any]:
        query = (
            "mutation ($boardId: ID!, $groupId: String!) {"
            " delete_group (board_id: $boardId, group_id: $groupId) { id } }"
        )
        return await _monday_graphql(
            auth, query, {"boardId": c.board_id, "groupId": c.group_id},
            action_name="delete_group",
        )

    async def _create_column(self, c: MondayCreateColumnConfig, auth: str) -> Dict[str, Any]:
        query = (
            "mutation ($boardId: ID!, $title: String!, $columnType: ColumnType!, $defaults: JSON) {"
            " create_column (board_id: $boardId, title: $title, column_type: $columnType,"
            " defaults: $defaults) { id title type } }"
        )
        variables = {
            "boardId": c.board_id,
            "title": c.title,
            "columnType": c.column_type,
            "defaults": c.defaults or None,
        }
        return await _monday_graphql(auth, query, variables, action_name="create_column")

    # ------------------------------------------------------------------
    # Updates & notifications
    # ------------------------------------------------------------------
    async def _create_update(self, c: MondayCreateUpdateConfig, auth: str) -> Dict[str, Any]:
        query = (
            "mutation ($itemId: ID!, $body: String!) {"
            " create_update (item_id: $itemId, body: $body) { id body } }"
        )
        return await _monday_graphql(
            auth, query, {"itemId": c.item_id, "body": c.body}, action_name="create_update"
        )

    async def _create_notification(
        self, c: MondayCreateNotificationConfig, auth: str
    ) -> Dict[str, Any]:
        query = (
            "mutation ($userId: ID!, $targetId: ID!, $targetType: NotificationTargetType!,"
            " $text: String!) {"
            " create_notification (user_id: $userId, target_id: $targetId,"
            " target_type: $targetType, text: $text) { id text } }"
        )
        variables = {
            "userId": c.user_id,
            "targetId": c.target_id,
            "targetType": c.target_type,
            "text": c.text,
        }
        return await _monday_graphql(
            auth, query, variables, action_name="create_notification"
        )

    # ------------------------------------------------------------------
    # Account handlers
    # ------------------------------------------------------------------
    async def _list_users(self, c: MondayListUsersConfig, auth: str) -> Dict[str, Any]:
        query = (
            "query ($limit: Int, $emails: [String]) {"
            " users (limit: $limit, emails: $emails) {"
            " id name email enabled is_admin is_guest } }"
        )
        variables = {
            "limit": int(c.limit) if c.limit and str(c.limit).isdigit() else 25,
            "emails": _comma_list(c.emails) or None,
        }
        return await _monday_graphql(auth, query, variables, action_name="list_users")

    async def _get_me(self, c: MondayGetMeConfig, auth: str) -> Dict[str, Any]:
        query = (
            "query { me { id name email is_admin"
            " account { id name slug tier } } }"
        )
        return await _monday_graphql(auth, query, {}, action_name="get_me")

    async def _list_workspaces(
        self, c: MondayListWorkspacesConfig, auth: str
    ) -> Dict[str, Any]:
        query = (
            "query ($limit: Int) { workspaces (limit: $limit) {"
            " id name kind description } }"
        )
        variables = {"limit": int(c.limit) if c.limit and str(c.limit).isdigit() else 25}
        return await _monday_graphql(auth, query, variables, action_name="list_workspaces")

    # ------------------------------------------------------------------
    # Webhook handlers
    # ------------------------------------------------------------------
    async def _create_webhook(self, c: MondayCreateWebhookConfig, auth: str) -> Dict[str, Any]:
        query = (
            "mutation ($boardId: ID!, $url: String!, $event: WebhookEventType!) {"
            " create_webhook (board_id: $boardId, url: $url, event: $event)"
            " { id board_id } }"
        )
        variables = {"boardId": c.board_id, "url": c.url, "event": c.event}
        return await _monday_graphql(auth, query, variables, action_name="create_webhook")

    async def _delete_webhook(self, c: MondayDeleteWebhookConfig, auth: str) -> Dict[str, Any]:
        query = "mutation ($id: ID!) { delete_webhook (id: $id) { id board_id } }"
        return await _monday_graphql(
            auth, query, {"id": c.webhook_id}, action_name="delete_webhook"
        )

    async def _list_webhooks(self, c: MondayListWebhooksConfig, auth: str) -> Dict[str, Any]:
        # Monday 2025-04: Webhook type has id, board_id, event, config (url was removed)
        query = (
            "query ($boardId: ID!) { webhooks (board_id: $boardId) { id board_id event config } }"
        )
        return await _monday_graphql(auth, query, {"boardId": c.board_id}, action_name="list_webhooks")

    # ------------------------------------------------------------------
    # Board extended handlers
    # ------------------------------------------------------------------
    async def _update_board(self, c: MondayUpdateBoardConfig, auth: str) -> Dict[str, Any]:
        # update_board returns a JSON scalar — no subfield selection allowed
        query = (
            "mutation ($boardId: ID!, $attr: BoardAttributes!, $val: String!) {"
            " update_board (board_id: $boardId, board_attribute: $attr, new_value: $val) }"
        )
        return await _monday_graphql(
            auth, query,
            {"boardId": c.board_id, "attr": c.board_attribute, "val": c.new_value},
            action_name="update_board",
        )

    async def _delete_board(self, c: MondayDeleteBoardConfig, auth: str) -> Dict[str, Any]:
        query = "mutation ($boardId: ID!) { delete_board (board_id: $boardId) { id } }"
        return await _monday_graphql(
            auth, query, {"boardId": c.board_id}, action_name="delete_board"
        )

    async def _archive_board(self, c: MondayArchiveBoardConfig, auth: str) -> Dict[str, Any]:
        query = "mutation ($boardId: ID!) { archive_board (board_id: $boardId) { id } }"
        return await _monday_graphql(
            auth, query, {"boardId": c.board_id}, action_name="archive_board"
        )

    async def _duplicate_board(self, c: MondayDuplicateBoardConfig, auth: str) -> Dict[str, Any]:
        query = (
            "mutation ($boardId: ID!, $type: DuplicateBoardType!, $name: String, $workspaceId: ID) {"
            " duplicate_board (board_id: $boardId, duplicate_type: $type, board_name: $name,"
            " workspace_id: $workspaceId) { board { id name } } }"
        )
        variables = {
            "boardId": c.board_id,
            "type": c.duplicate_type,
            "name": c.board_name or None,
            "workspaceId": c.workspace_id or None,
        }
        return await _monday_graphql(auth, query, variables, action_name="duplicate_board")

    # ------------------------------------------------------------------
    # Group extended handlers
    # ------------------------------------------------------------------
    async def _list_groups(self, c: MondayListGroupsConfig, auth: str) -> Dict[str, Any]:
        query = (
            "query ($ids: [ID!]) {"
            " boards (ids: $ids) { id name groups { id title color archived } } }"
        )
        return await _monday_graphql(auth, query, {"ids": [c.board_id]}, action_name="list_groups")

    async def _archive_group(self, c: MondayArchiveGroupConfig, auth: str) -> Dict[str, Any]:
        query = (
            "mutation ($boardId: ID!, $groupId: String!) {"
            " archive_group (board_id: $boardId, group_id: $groupId) { id } }"
        )
        return await _monday_graphql(
            auth, query,
            {"boardId": c.board_id, "groupId": c.group_id},
            action_name="archive_group",
        )

    async def _duplicate_group(self, c: MondayDuplicateGroupConfig, auth: str) -> Dict[str, Any]:
        query = (
            "mutation ($boardId: ID!, $groupId: String!, $addToTop: Boolean, $title: String) {"
            " duplicate_group (board_id: $boardId, group_id: $groupId,"
            " add_to_top: $addToTop, group_title: $title) { id title } }"
        )
        variables = {
            "boardId": c.board_id,
            "groupId": c.group_id,
            "addToTop": c.add_to_top == "true",
            "title": c.group_title or None,
        }
        return await _monday_graphql(auth, query, variables, action_name="duplicate_group")

    async def _update_group(self, c: MondayUpdateGroupConfig, auth: str) -> Dict[str, Any]:
        query = (
            "mutation ($boardId: ID!, $groupId: String!, $attr: GroupAttributes!, $val: String!) {"
            " update_group (board_id: $boardId, group_id: $groupId,"
            " group_attribute: $attr, new_value: $val) { id } }"
        )
        variables = {
            "boardId": c.board_id,
            "groupId": c.group_id,
            "attr": c.group_attribute,
            "val": c.new_value,
        }
        return await _monday_graphql(auth, query, variables, action_name="update_group")

    # ------------------------------------------------------------------
    # Column extended handlers
    # ------------------------------------------------------------------
    async def _delete_column(self, c: MondayDeleteColumnConfig, auth: str) -> Dict[str, Any]:
        query = (
            "mutation ($boardId: ID!, $columnId: String!) {"
            " delete_column (board_id: $boardId, column_id: $columnId) { id } }"
        )
        return await _monday_graphql(
            auth, query,
            {"boardId": c.board_id, "columnId": c.column_id},
            action_name="delete_column",
        )

    async def _rename_column(self, c: MondayRenameColumnConfig, auth: str) -> Dict[str, Any]:
        query = (
            "mutation ($boardId: ID!, $columnId: String!, $title: String!) {"
            " change_column_title (board_id: $boardId, column_id: $columnId, title: $title)"
            " { id title } }"
        )
        return await _monday_graphql(
            auth, query,
            {"boardId": c.board_id, "columnId": c.column_id, "title": c.title},
            action_name="rename_column",
        )

    # ------------------------------------------------------------------
    # Item extended handlers
    # ------------------------------------------------------------------
    async def _get_subitems(self, c: MondayGetSubitemsConfig, auth: str) -> Dict[str, Any]:
        query = (
            "query ($ids: [ID!]) { items (ids: $ids) {"
            " id name subitems { id name column_values { id text value } } } }"
        )
        return await _monday_graphql(
            auth, query, {"ids": [c.item_id]}, action_name="get_subitems"
        )

    async def _clear_item_updates(
        self, c: MondayClearItemUpdatesConfig, auth: str
    ) -> Dict[str, Any]:
        query = "mutation ($itemId: ID!) { clear_item_updates (item_id: $itemId) { id } }"
        return await _monday_graphql(
            auth, query, {"itemId": c.item_id}, action_name="clear_item_updates"
        )

    # ------------------------------------------------------------------
    # Updates extended handlers
    # ------------------------------------------------------------------
    async def _get_updates(self, c: MondayGetUpdatesConfig, auth: str) -> Dict[str, Any]:
        query = (
            "query ($ids: [ID!], $limit: Int) { items (ids: $ids) {"
            " id name updates (limit: $limit) {"
            " id body text_body created_at creator { id name } } } }"
        )
        variables = {
            "ids": [c.item_id],
            "limit": int(c.limit) if c.limit and str(c.limit).isdigit() else 25,
        }
        return await _monday_graphql(auth, query, variables, action_name="get_updates")

    async def _delete_update(self, c: MondayDeleteUpdateConfig, auth: str) -> Dict[str, Any]:
        query = "mutation ($id: ID!) { delete_update (id: $id) { id } }"
        return await _monday_graphql(
            auth, query, {"id": c.update_id}, action_name="delete_update"
        )

    async def _edit_update(self, c: MondayEditUpdateConfig, auth: str) -> Dict[str, Any]:
        query = (
            "mutation ($id: ID!, $body: String!) { edit_update (id: $id, body: $body) { id body } }"
        )
        return await _monday_graphql(
            auth, query, {"id": c.update_id, "body": c.body}, action_name="edit_update"
        )

    async def _like_update(self, c: MondayLikeUpdateConfig, auth: str) -> Dict[str, Any]:
        query = "mutation ($updateId: ID!) { like_update (update_id: $updateId) { id } }"
        return await _monday_graphql(
            auth, query, {"updateId": c.update_id}, action_name="like_update"
        )

    # ------------------------------------------------------------------
    # Tags handlers
    # ------------------------------------------------------------------
    async def _get_tags(self, c: MondayGetTagsConfig, auth: str) -> Dict[str, Any]:
        # Monday 2025-04: tags ids use [ID!] (string), not [Int]
        ids = _comma_list(c.tag_ids) if c.tag_ids else None
        query = "query ($ids: [ID!]) { tags (ids: $ids) { id name color } }"
        return await _monday_graphql(auth, query, {"ids": ids or None}, action_name="get_tags")

    async def _create_or_get_tag(self, c: MondayCreateTagConfig, auth: str) -> Dict[str, Any]:
        # Monday 2025-04: board_id is ID type (string), not Int
        query = (
            "mutation ($tagName: String!, $boardId: ID) {"
            " create_or_get_tag (tag_name: $tagName, board_id: $boardId) { id name color } }"
        )
        return await _monday_graphql(
            auth, query,
            {"tagName": c.tag_name, "boardId": c.board_id or None},
            action_name="create_or_get_tag",
        )

    # ------------------------------------------------------------------
    # Teams handlers
    # ------------------------------------------------------------------
    async def _get_teams(self, c: MondayGetTeamsConfig, auth: str) -> Dict[str, Any]:
        ids = _comma_list(c.team_ids) if c.team_ids else None
        query = (
            "query ($ids: [ID!]) { teams (ids: $ids) {"
            " id name picture_url users { id name email } } }"
        )
        return await _monday_graphql(auth, query, {"ids": ids or None}, action_name="get_teams")

    async def _add_users_to_team(
        self, c: MondayAddUsersToTeamConfig, auth: str
    ) -> Dict[str, Any]:
        query = (
            "mutation ($teamId: ID!, $userIds: [ID!]!) {"
            " add_users_to_team (team_id: $teamId, user_ids: $userIds)"
            " { successful_users { id name } failed_users { id name } } }"
        )
        return await _monday_graphql(
            auth, query,
            {"teamId": c.team_id, "userIds": _comma_list(c.user_ids)},
            action_name="add_users_to_team",
        )

    async def _remove_users_from_team(
        self, c: MondayRemoveUsersFromTeamConfig, auth: str
    ) -> Dict[str, Any]:
        query = (
            "mutation ($teamId: ID!, $userIds: [ID!]!) {"
            " remove_users_from_team (team_id: $teamId, user_ids: $userIds)"
            " { successful_users { id name } failed_users { id name } } }"
        )
        return await _monday_graphql(
            auth, query,
            {"teamId": c.team_id, "userIds": _comma_list(c.user_ids)},
            action_name="remove_users_from_team",
        )

    async def _create_team(self, c: MondayCreateTeamConfig, auth: str) -> Dict[str, Any]:
        # allow_empty_team option required when no subscriber_ids provided
        query = (
            "mutation ($input: CreateTeamAttributesInput!, $options: CreateTeamOptionsInput) {"
            " create_team (input: $input, options: $options) { id name } }"
        )
        input_obj: Dict[str, Any] = {"name": c.name}
        if c.subscriber_ids:
            input_obj["subscriber_ids"] = _comma_list(c.subscriber_ids)
        if c.is_guest_team == "true":
            input_obj["is_guest_team"] = True
        options = None if c.subscriber_ids else {"allow_empty_team": True}
        return await _monday_graphql(
            auth, query, {"input": input_obj, "options": options}, action_name="create_team"
        )

    async def _delete_team(self, c: MondayDeleteTeamConfig, auth: str) -> Dict[str, Any]:
        query = "mutation ($teamId: ID!) { delete_team (team_id: $teamId) { id } }"
        return await _monday_graphql(
            auth, query, {"teamId": c.team_id}, action_name="delete_team"
        )

    # ------------------------------------------------------------------
    # Workspace extended handlers
    # ------------------------------------------------------------------
    async def _create_workspace(
        self, c: MondayCreateWorkspaceConfig, auth: str
    ) -> Dict[str, Any]:
        query = (
            "mutation ($name: String!, $kind: WorkspaceKind!, $desc: String) {"
            " create_workspace (name: $name, kind: $kind, description: $desc)"
            " { id name kind description } }"
        )
        variables = {"name": c.name, "kind": c.kind, "desc": c.description or None}
        return await _monday_graphql(auth, query, variables, action_name="create_workspace")

    async def _update_workspace(
        self, c: MondayUpdateWorkspaceConfig, auth: str
    ) -> Dict[str, Any]:
        attrs: Dict[str, Any] = {}
        if c.name:
            attrs["name"] = c.name
        if c.description:
            attrs["description"] = c.description
        if c.kind:
            attrs["kind"] = c.kind
        query = (
            "mutation ($id: ID, $attrs: UpdateWorkspaceAttributesInput!) {"
            " update_workspace (id: $id, attributes: $attrs) { id name kind description } }"
        )
        return await _monday_graphql(
            auth, query, {"id": c.workspace_id, "attrs": attrs}, action_name="update_workspace"
        )

    async def _delete_workspace(
        self, c: MondayDeleteWorkspaceConfig, auth: str
    ) -> Dict[str, Any]:
        query = "mutation ($workspaceId: ID!) { delete_workspace (workspace_id: $workspaceId) { id } }"
        return await _monday_graphql(
            auth, query, {"workspaceId": c.workspace_id}, action_name="delete_workspace"
        )

    # ------------------------------------------------------------------
    # Board membership handlers
    # ------------------------------------------------------------------
    async def _add_users_to_board(
        self, c: MondayAddUsersToBoardConfig, auth: str
    ) -> Dict[str, Any]:
        query = (
            "mutation ($boardId: ID!, $userIds: [ID!]!, $kind: BoardSubscriberKind) {"
            " add_users_to_board (board_id: $boardId, user_ids: $userIds, kind: $kind)"
            " { id name email } }"
        )
        return await _monday_graphql(
            auth, query,
            {"boardId": c.board_id, "userIds": _comma_list(c.user_ids), "kind": c.kind},
            action_name="add_users_to_board",
        )

    async def _remove_users_from_board(
        self, c: MondayRemoveUsersFromBoardConfig, auth: str
    ) -> Dict[str, Any]:
        query = (
            "mutation ($boardId: ID!, $userIds: [ID!]!) {"
            " delete_subscribers_from_board (board_id: $boardId, user_ids: $userIds)"
            " { id } }"
        )
        return await _monday_graphql(
            auth, query,
            {"boardId": c.board_id, "userIds": _comma_list(c.user_ids)},
            action_name="remove_users_from_board",
        )

    async def _add_teams_to_board(
        self, c: MondayAddTeamsToBoardConfig, auth: str
    ) -> Dict[str, Any]:
        query = (
            "mutation ($boardId: ID!, $teamIds: [ID!]!, $kind: BoardSubscriberKind) {"
            " add_teams_to_board (board_id: $boardId, team_ids: $teamIds, kind: $kind)"
            " { id } }"
        )
        return await _monday_graphql(
            auth, query,
            {"boardId": c.board_id, "teamIds": _comma_list(c.team_ids), "kind": c.kind},
            action_name="add_teams_to_board",
        )

    # ------------------------------------------------------------------
    # Folder handlers
    # ------------------------------------------------------------------
    async def _list_folders(self, c: MondayListFoldersConfig, auth: str) -> Dict[str, Any]:
        query = (
            "query ($workspaceIds: [ID], $limit: Int, $page: Int) {"
            " folders (workspace_ids: $workspaceIds, limit: $limit, page: $page)"
            " { id name color workspace { id name } } }"
        )
        variables = {
            "workspaceIds": _comma_list(c.workspace_ids) or None,
            "limit": int(c.limit) if c.limit and str(c.limit).isdigit() else 25,
            "page": int(c.page) if c.page and str(c.page).isdigit() else 1,
        }
        return await _monday_graphql(auth, query, variables, action_name="list_folders")

    async def _create_folder(self, c: MondayCreateFolderConfig, auth: str) -> Dict[str, Any]:
        query = (
            "mutation ($name: String!, $workspaceId: ID, $parentFolderId: ID) {"
            " create_folder (name: $name, workspace_id: $workspaceId,"
            " parent_folder_id: $parentFolderId) { id name } }"
        )
        variables = {
            "name": c.name,
            "workspaceId": c.workspace_id or None,
            "parentFolderId": c.parent_folder_id or None,
        }
        return await _monday_graphql(auth, query, variables, action_name="create_folder")

    async def _update_folder(self, c: MondayUpdateFolderConfig, auth: str) -> Dict[str, Any]:
        query = (
            "mutation ($folderId: ID!, $name: String, $parentFolderId: ID) {"
            " update_folder (folder_id: $folderId, name: $name,"
            " parent_folder_id: $parentFolderId) { id name } }"
        )
        variables = {
            "folderId": c.folder_id,
            "name": c.name or None,
            "parentFolderId": c.parent_folder_id or None,
        }
        return await _monday_graphql(auth, query, variables, action_name="update_folder")

    async def _delete_folder(self, c: MondayDeleteFolderConfig, auth: str) -> Dict[str, Any]:
        query = "mutation ($folderId: ID!) { delete_folder (folder_id: $folderId) { id } }"
        return await _monday_graphql(
            auth, query, {"folderId": c.folder_id}, action_name="delete_folder"
        )

    # ------------------------------------------------------------------
    # Docs handlers
    # ------------------------------------------------------------------
    async def _get_docs(self, c: MondayGetDocsConfig, auth: str) -> Dict[str, Any]:
        # Monday 2025-04: ids and workspace_ids use [ID!] not [ID]
        # Monday 2025-04: Document type uses "name" (not "title")
        query = (
            "query ($ids: [ID!], $workspaceIds: [ID!], $limit: Int, $page: Int) {"
            " docs (ids: $ids, workspace_ids: $workspaceIds, limit: $limit, page: $page)"
            " { id name doc_kind created_at workspace_id } }"
        )
        variables = {
            "ids": _comma_list(c.doc_ids) or None,
            "workspaceIds": _comma_list(c.workspace_ids) or None,
            "limit": int(c.limit) if c.limit and str(c.limit).isdigit() else 25,
            "page": int(c.page) if c.page and str(c.page).isdigit() else 1,
        }
        return await _monday_graphql(auth, query, variables, action_name="get_docs")

    async def _create_doc(self, c: MondayCreateDocConfig, auth: str) -> Dict[str, Any]:
        # CreateDocWorkspaceInput requires name, workspace_id, and optional kind (BoardKind)
        # Monday 2025-04: Document returns "name" not "title"
        query = (
            "mutation ($location: CreateDocInput!) {"
            " create_doc (location: $location) { id name } }"
        )
        location = {
            "workspace": {
                "workspace_id": c.workspace_id,
                "name": c.doc_name,
                "kind": c.doc_kind,
            }
        }
        # Monday 2025-04: Document returns "name" not "title"
        return await _monday_graphql(auth, query, {"location": location}, action_name="create_doc")

    async def _create_doc_block(
        self, c: MondayCreateDocBlockConfig, auth: str
    ) -> Dict[str, Any]:
        # Monday 2025-04: content JSON scalar expects a *stringified* JSON
        # (a JSON string, not a dict). Normalise: if user passes a plain string
        # treat it as text; if they pass a JSON object stringify it.
        try:
            parsed = json.loads(c.content)
            if isinstance(parsed, dict):
                content_str = c.content  # already a valid JSON string
            else:
                content_str = json.dumps({"deltaFormat": [{"insert": str(c.content)}]})
        except (json.JSONDecodeError, ValueError):
            content_str = json.dumps({"deltaFormat": [{"insert": c.content}]})
        query = (
            "mutation ($docId: ID!, $type: DocBlockContentType!, $content: JSON!,"
            " $afterBlockId: String) {"
            " create_doc_block (doc_id: $docId, type: $type, content: $content,"
            " after_block_id: $afterBlockId) { id type content } }"
        )
        variables = {
            "docId": c.doc_id,
            "type": c.block_type,
            "content": content_str,
            "afterBlockId": c.after_block_id or None,
        }
        return await _monday_graphql(auth, query, variables, action_name="create_doc_block")

    async def _update_doc_block(
        self, c: MondayUpdateDocBlockConfig, auth: str
    ) -> Dict[str, Any]:
        # Same string-not-dict convention as create_doc_block
        try:
            parsed = json.loads(c.content)
            content_str = c.content if isinstance(parsed, dict) else json.dumps({"deltaFormat": [{"insert": str(c.content)}]})
        except (json.JSONDecodeError, ValueError):
            content_str = json.dumps({"deltaFormat": [{"insert": c.content}]})
        query = (
            "mutation ($blockId: String!, $content: JSON!) {"
            " update_doc_block (block_id: $blockId, content: $content) { id content } }"
        )
        return await _monday_graphql(
            auth, query,
            {"blockId": c.block_id, "content": content_str},
            action_name="update_doc_block",
        )

    async def _delete_doc_block(
        self, c: MondayDeleteDocBlockConfig, auth: str
    ) -> Dict[str, Any]:
        query = "mutation ($blockId: String!) { delete_doc_block (block_id: $blockId) { id } }"
        return await _monday_graphql(
            auth, query, {"blockId": c.block_id}, action_name="delete_doc_block"
        )

    # ------------------------------------------------------------------
    # Assets handlers
    # ------------------------------------------------------------------
    async def _get_assets(self, c: MondayGetAssetsConfig, auth: str) -> Dict[str, Any]:
        query = (
            "query ($ids: [ID!]!) { assets (ids: $ids)"
            " { id name url public_url file_extension file_size created_at"
            " uploaded_by { id name } } }"
        )
        return await _monday_graphql(
            auth, query, {"ids": _comma_list(c.asset_ids)}, action_name="get_assets"
        )

    # ------------------------------------------------------------------
    # Updates extended handlers
    # ------------------------------------------------------------------
    async def _unlike_update(self, c: MondayUnlikeUpdateConfig, auth: str) -> Dict[str, Any]:
        query = "mutation ($updateId: ID!) { unlike_update (update_id: $updateId) { id } }"
        return await _monday_graphql(
            auth, query, {"updateId": c.update_id}, action_name="unlike_update"
        )
