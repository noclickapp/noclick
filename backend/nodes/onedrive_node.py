"""
OneDrive node for Microsoft Graph API - Complete file storage automation.

Supports all OneDrive operations via Microsoft Graph API including files, folders,
sharing, permissions, versions, thumbnails, and search. Uses centralized Microsoft OAuth.

Research Source: Microsoft Graph OneDrive API v1.0 Documentation
Total Operations: 37 (across 7 categories)

Authentication: Microsoft OAuth 2.0 only (no API keys - Microsoft Graph requires OAuth)
"""

from typing import Dict, Any, Literal, Optional, Tuple, Union, List, Annotated
from pydantic import BaseModel, ConfigDict, Discriminator, Field
from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.scopes.microsoft import ONEDRIVE_SCOPES
from nodes.core.dynamic_options import load_paginated_options, require_credential_token
from utils.ssrf import assert_exact_url_origin, guarded_async_client
import httpx
import json
import logging
import base64
from nodes.oauth.microsoft_oauth import refresh_access_token, is_token_expired

logger = logging.getLogger(__name__)

GRAPH_API_ORIGIN = "https://graph.microsoft.com"

# ============================================================================
# Credentials
# ============================================================================


class OneDriveOAuthCredential(BaseModel):
    """
    Microsoft OAuth credential for OneDrive (via Graph API).

    Uses centralized Microsoft OAuth - credentials are automatically created
    when users connect their Microsoft account through the OAuth flow.

    Scopes required:
    - Files.ReadWrite.All: Full OneDrive file access
    - User.Read: Get user profile info
    """

    credential_type: Literal["microsoft_onedrive_oauth"] = Field(
        "microsoft_onedrive_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(..., description="OAuth access token")
    refresh_token: str = Field(..., description="OAuth refresh token for token renewal")
    expires_at: str = Field(..., description="Token expiry timestamp (ISO 8601)")
    email: str = Field(..., description="Microsoft account email address")

    model_config = ConfigDict(json_schema_extra={
        "x-credential-type": "oauth",
        "x-oauth-provider": "microsoft",  # Uses centralized Microsoft OAuth
        "x-oauth-scopes": [
            "https://graph.microsoft.com/Files.ReadWrite.All",  # Full OneDrive access
            "https://graph.microsoft.com/User.Read",  # User profile
        ],
        "x-credential-url": "https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps/ApplicationsListBlade",
        "x-credential-instructions": "Connect your Microsoft account to access OneDrive files. Uses Microsoft Graph API with OAuth 2.0.",
    })


# ============================================================================
# Config Models - Core File Operations (10 operations)
# ============================================================================


class OneDriveGetItemConfig(BaseModel):
    """Get metadata for a file or folder"""

    operation: Literal["get_item_metadata"] = Field(
        "get_item_metadata",
        json_schema_extra={
            "const": "get_item_metadata",
            "ui:hidden": True,
            "x-category": "Item",
            "x-is-trigger": False,
            "x-display-name": "Get Item Metadata",
        },
        title="Get Item Metadata",
    )
    item_id: Optional[str] = Field(
        None,
        title="Item ID",
        description="File or folder ID (leave empty to use path)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "item_id",
                "placeholder": "Select an item...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste item ID",
            },
            "x-resource-type": "onedrive_item",
        },
    )
    item_path: Optional[str] = Field(
        None,
        title="Item Path",
        description="Path to file/folder (e.g., /Documents/report.pdf). Used if item_id is empty.",
        json_schema_extra={"ui:placeholder": "/Documents/report.pdf"},
    )


class OneDriveListChildrenConfig(BaseModel):
    """List contents of a folder"""

    operation: Literal["list_folder_contents"] = Field(
        "list_folder_contents",
        json_schema_extra={
            "const": "list_folder_contents",
            "ui:hidden": True,
            "x-category": "Folder",
            "x-is-trigger": False,
            "x-display-name": "List Folder Contents",
        },
        title="List Folder Contents",
    )
    folder_id: Optional[str] = Field(
        None,
        title="Folder ID",
        description="Folder ID (leave empty for root or to use path)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "folder_id",
                "placeholder": "Select a folder...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste folder ID",
            },
            "x-resource-type": "onedrive_folder",
        },
    )
    folder_path: Optional[str] = Field(
        None,
        title="Folder Path",
        description="Path to folder (e.g., /Documents). Used if folder_id is empty.",
        json_schema_extra={"ui:placeholder": "/Documents"},
    )
    top: int = Field(
        100,
        title="Max Results",
        description="Maximum number of items to return (1-999)",
        ge=1,
        le=999,
    )


class OneDriveUploadConfig(BaseModel):
    """Upload a file (for files up to 4MB)"""

    operation: Literal["upload_file"] = Field(
        "upload_file",
        json_schema_extra={
            "const": "upload_file",
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Upload File",
        },
        title="Upload File",
    )
    parent_folder_id: Optional[str] = Field(
        None,
        title="Parent Folder ID",
        description="Folder to upload to (leave empty for root or to use path)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "parent_folder_id",
                "placeholder": "Select a folder...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste folder ID",
            },
            "x-resource-type": "onedrive_folder",
        },
    )
    parent_folder_path: Optional[str] = Field(
        None,
        title="Parent Folder Path",
        description="Path to parent folder (e.g., /Documents). Used if parent_folder_id is empty.",
        json_schema_extra={"ui:placeholder": "/Documents"},
    )
    file_name: str = Field(
        ...,
        title="File Name",
        description="Name for the uploaded file",
        json_schema_extra={"ui:placeholder": "document.pdf"},
    )
    file_content: str = Field(
        ...,
        title="File Content",
        description="The file content to upload — plain text, or for binary files paste a URL, reference an upstream file (e.g. {{http-1.response.url}}), a data: URI, or base64.",
        json_schema_extra={"ui:widget": "code_editor"},
    )
    content_type: str = Field(
        "application/octet-stream",
        title="Content Type",
        description="MIME type of the file",
        json_schema_extra={
            "enum": [
                "application/pdf",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "application/json",
                "text/plain",
                "text/csv",
                "image/png",
                "image/jpeg",
                "application/octet-stream",
            ],
            "x-enum-searchable": True,
        },
    )


class OneDriveUploadSessionConfig(BaseModel):
    """Create upload session for large files (>4MB)"""

    operation: Literal["create_large_file_upload_session"] = Field(
        "create_large_file_upload_session",
        json_schema_extra={
            "const": "create_large_file_upload_session",
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Create Large File Upload Session",
        },
        title="Create Large File Upload Session",
    )
    parent_folder_id: Optional[str] = Field(
        None,
        title="Parent Folder ID",
        description="Folder to upload to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "parent_folder_id",
                "placeholder": "Select a folder...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste folder ID",
            },
            "x-resource-type": "onedrive_folder",
        },
    )
    parent_folder_path: Optional[str] = Field(
        None,
        title="Parent Folder Path",
        description="Path to parent folder",
        json_schema_extra={"ui:placeholder": "/Documents"},
    )
    file_name: str = Field(
        ..., title="File Name", description="Name for the uploaded file"
    )


class OneDriveDownloadConfig(BaseModel):
    """Download file content"""

    operation: Literal["download_item"] = Field(
        "download_item",
        json_schema_extra={
            "const": "download_item",
            "ui:hidden": True,
            "x-category": "Item",
            "x-is-trigger": False,
            "x-display-name": "Download Item",
        },
        title="Download Item",
    )
    item_id: Optional[str] = Field(
        None,
        title="Item ID",
        description="File ID to download",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "item_id",
                "placeholder": "Select a file...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste file ID",
            },
            "x-resource-type": "onedrive_item",
        },
    )
    item_path: Optional[str] = Field(
        None,
        title="Item Path",
        description="Path to file",
        json_schema_extra={"ui:placeholder": "/Documents/report.pdf"},
    )
    format: Optional[str] = Field(
        None,
        title="Download Format",
        description="Optional format for conversion (e.g., pdf for Office files)",
        json_schema_extra={
            "enum": ["pdf", "html", "jpg", "png"],
            "x-enum-searchable": True,
        },
    )


class OneDriveUpdateItemConfig(BaseModel):
    """Update file or folder metadata"""

    operation: Literal["update_item_metadata"] = Field(
        "update_item_metadata",
        json_schema_extra={
            "const": "update_item_metadata",
            "ui:hidden": True,
            "x-category": "Item",
            "x-is-trigger": False,
            "x-display-name": "Update Item Metadata",
        },
        title="Update Item Metadata",
    )
    item_id: str = Field(
        ...,
        title="Item ID",
        description="File or folder ID to update",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "item_id",
                "placeholder": "Select an item...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste item ID",
            },
            "x-resource-type": "onedrive_item",
        },
    )
    new_name: Optional[str] = Field(
        None,
        title="New Name",
        description="New name for the item (leave empty to keep current)",
    )
    description: Optional[str] = Field(
        None, title="Description", description="Item description"
    )


class OneDriveCreateFolderConfig(BaseModel):
    """Create a new folder"""

    operation: Literal["create_folder"] = Field(
        "create_folder",
        json_schema_extra={
            "const": "create_folder",
            "ui:hidden": True,
            "x-category": "Folder",
            "x-is-trigger": False,
            "x-display-name": "Create Folder",
            "x-creates-resource": True,
            "x-resource-type": "onedrive_folder",
            "x-resource-id-path": "data.id",
        },
        title="Create Folder",
    )
    parent_folder_id: Optional[str] = Field(
        None,
        title="Parent Folder ID",
        description="Parent folder (leave empty for root)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "parent_folder_id",
                "placeholder": "Select a folder...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste folder ID",
            },
            "x-resource-type": "onedrive_folder",
        },
    )
    parent_folder_path: Optional[str] = Field(
        None,
        title="Parent Folder Path",
        description="Path to parent folder",
        json_schema_extra={"ui:placeholder": "/Documents"},
    )
    folder_name: str = Field(
        ..., title="Folder Name", description="Name for the new folder"
    )


class OneDriveCopyConfig(BaseModel):
    """Copy a file or folder"""

    operation: Literal["copy_item"] = Field(
        "copy_item",
        json_schema_extra={
            "const": "copy_item",
            "ui:hidden": True,
            "x-category": "Item",
            "x-is-trigger": False,
            "x-display-name": "Copy Item",
        },
        title="Copy Item",
    )
    item_id: str = Field(
        ...,
        title="Item ID",
        description="File or folder to copy",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "item_id",
                "placeholder": "Select an item...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste item ID",
            },
            "x-resource-type": "onedrive_item",
        },
    )
    destination_folder_id: Optional[str] = Field(
        None,
        title="Destination Folder ID",
        description="Destination folder",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "destination_folder_id",
                "placeholder": "Select destination...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste folder ID",
            },
            "x-resource-type": "onedrive_folder",
        },
    )
    new_name: Optional[str] = Field(
        None,
        title="New Name",
        description="Name for the copy (leave empty to keep original name)",
    )


class OneDriveMoveConfig(BaseModel):
    """Move a file or folder"""

    operation: Literal["move_item"] = Field(
        "move_item",
        json_schema_extra={
            "const": "move_item",
            "ui:hidden": True,
            "x-category": "Item",
            "x-is-trigger": False,
            "x-display-name": "Move Item",
        },
        title="Move Item",
    )
    item_id: str = Field(
        ...,
        title="Item ID",
        description="File or folder to move",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "item_id",
                "placeholder": "Select an item...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste item ID",
            },
            "x-resource-type": "onedrive_item",
        },
    )
    destination_folder_id: str = Field(
        ...,
        title="Destination Folder ID",
        description="Destination folder",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "destination_folder_id",
                "placeholder": "Select destination...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste folder ID",
            },
            "x-resource-type": "onedrive_folder",
        },
    )


class OneDriveDeleteConfig(BaseModel):
    """Delete a file or folder (moves to recycle bin)"""

    operation: Literal["delete_item"] = Field(
        "delete_item",
        json_schema_extra={
            "const": "delete_item",
            "ui:hidden": True,
            "x-category": "Item",
            "x-is-trigger": False,
            "x-display-name": "Delete Item",
        },
        title="Delete Item",
    )
    item_id: str = Field(
        ...,
        title="Item ID",
        description="File or folder to delete",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "item_id",
                "placeholder": "Select an item...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste item ID",
            },
            "x-resource-type": "onedrive_item",
        },
    )


# ============================================================================
# Config Models - File Management (3 operations)
# ============================================================================


class OneDriveRestoreConfig(BaseModel):
    """Restore a deleted item from recycle bin"""

    operation: Literal["restore_item_from_recycle_bin"] = Field(
        "restore_item_from_recycle_bin",
        json_schema_extra={
            "const": "restore_item_from_recycle_bin",
            "ui:hidden": True,
            "x-category": "Item",
            "x-is-trigger": False,
            "x-display-name": "Restore Item from Recycle Bin",
        },
        title="Restore Item from Recycle Bin",
    )
    item_id: str = Field(
        ..., title="Item ID", description="ID of deleted item to restore"
    )
    parent_folder_id: Optional[str] = Field(
        None,
        title="Parent Folder ID",
        description="Where to restore the item (leave empty for original location)",
    )


class OneDrivePermanentlyDeleteConfig(BaseModel):
    """Permanently delete an item (cannot be recovered)"""

    operation: Literal["permanently_delete_item"] = Field(
        "permanently_delete_item",
        json_schema_extra={
            "const": "permanently_delete_item",
            "ui:hidden": True,
            "x-category": "Item",
            "x-is-trigger": False,
            "x-display-name": "Permanently Delete Item",
        },
        title="Permanently Delete Item",
    )
    item_id: str = Field(..., title="Item ID", description="Item to permanently delete")


class OneDriveGetDriveConfig(BaseModel):
    """Get drive information and quota"""

    operation: Literal["get_drive_info"] = Field(
        "get_drive_info",
        json_schema_extra={
            "const": "get_drive_info",
            "ui:hidden": True,
            "x-category": "Drive",
            "x-is-trigger": False,
            "x-display-name": "Get Drive Info",
        },
        title="Get Drive Info",
    )


# ============================================================================
# Config Models - Search & Discovery (2 operations)
# ============================================================================


class OneDriveSearchConfig(BaseModel):
    """Search for items in OneDrive"""

    operation: Literal["search_drive_items"] = Field(
        "search_drive_items",
        json_schema_extra={
            "const": "search_drive_items",
            "ui:hidden": True,
            "x-category": "Drive",
            "x-is-trigger": False,
            "x-display-name": "Search Drive Items",
        },
        title="Search Drive Items",
    )
    query: str = Field(
        ...,
        title="Search Query",
        description="Text to search for",
        json_schema_extra={"ui:placeholder": "quarterly report"},
    )
    top: int = Field(
        50,
        title="Max Results",
        description="Maximum number of results (1-999)",
        ge=1,
        le=999,
    )


class OneDriveDeltaConfig(BaseModel):
    """Track changes in OneDrive (delta query)"""

    operation: Literal["track_drive_changes"] = Field(
        "track_drive_changes",
        json_schema_extra={
            "const": "track_drive_changes",
            "ui:hidden": True,
            "x-category": "Drive",
            "x-is-trigger": False,
            "x-display-name": "Track Drive Changes",
        },
        title="Track Drive Changes",
    )
    folder_id: Optional[str] = Field(
        None,
        title="Folder ID",
        description="Folder to track changes in (leave empty for root)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "folder_id",
                "placeholder": "Select a folder...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste folder ID",
            },
            "x-resource-type": "onedrive_folder",
        },
    )
    delta_token: Optional[str] = Field(
        None,
        title="Delta Token",
        description="Token from previous delta query (leave empty for initial sync)",
    )


# ============================================================================
# Config Models - Sharing & Permissions (6 operations)
# ============================================================================


class OneDriveCreateLinkConfig(BaseModel):
    """Create a sharing link for an item"""

    operation: Literal["create_sharing_link"] = Field(
        "create_sharing_link",
        json_schema_extra={
            "const": "create_sharing_link",
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Create Sharing Link",
        },
        title="Create Sharing Link",
    )
    item_id: str = Field(
        ...,
        title="Item ID",
        description="File or folder to share",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "item_id",
                "placeholder": "Select an item...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste item ID",
            },
            "x-resource-type": "onedrive_item",
        },
    )
    link_type: str = Field(
        "view",
        title="Link Type",
        description="Type of sharing link",
        json_schema_extra={
            "enum": ["view", "edit", "embed"],
            "enumNames": ["View Only", "Can Edit", "Embed"],
            "x-enum-searchable": True,
        },
    )
    scope: str = Field(
        "anonymous",
        title="Scope",
        description="Who can access the link",
        json_schema_extra={
            "enum": ["anonymous", "organization"],
            "enumNames": ["Anyone with Link", "People in Organization"],
            "x-enum-searchable": True,
        },
    )


class OneDriveListPermissionsConfig(BaseModel):
    """List permissions for an item"""

    operation: Literal["list_item_permissions"] = Field(
        "list_item_permissions",
        json_schema_extra={
            "const": "list_item_permissions",
            "ui:hidden": True,
            "x-category": "Item",
            "x-is-trigger": False,
            "x-display-name": "List Item Permissions",
        },
        title="List Item Permissions",
    )
    item_id: str = Field(
        ...,
        title="Item ID",
        description="File or folder to list permissions for",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "item_id",
                "placeholder": "Select an item...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste item ID",
            },
            "x-resource-type": "onedrive_item",
        },
    )


class OneDriveAddPermissionConfig(BaseModel):
    """Grant permission to a user or group"""

    operation: Literal["grant_item_permission"] = Field(
        "grant_item_permission",
        json_schema_extra={
            "const": "grant_item_permission",
            "ui:hidden": True,
            "x-category": "Item",
            "x-is-trigger": False,
            "x-display-name": "Grant Item Permission",
        },
        title="Grant Item Permission",
    )
    item_id: str = Field(
        ...,
        title="Item ID",
        description="File or folder to share",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "item_id",
                "placeholder": "Select an item...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste item ID",
            },
            "x-resource-type": "onedrive_item",
        },
    )
    recipient_email: str = Field(
        ...,
        title="Recipient Email",
        description="Email address of the person to share with",
    )
    role: str = Field(
        "read",
        title="Role",
        description="Permission level",
        json_schema_extra={
            "enum": ["read", "write", "owner"],
            "enumNames": ["Can View", "Can Edit", "Owner"],
            "x-enum-searchable": True,
        },
    )
    send_invitation: bool = Field(
        True,
        title="Send Email Invitation",
        description="Send an email notification to the recipient",
    )


class OneDriveUpdatePermissionConfig(BaseModel):
    """Update an existing permission"""

    operation: Literal["update_item_permission"] = Field(
        "update_item_permission",
        json_schema_extra={
            "const": "update_item_permission",
            "ui:hidden": True,
            "x-category": "Item",
            "x-is-trigger": False,
            "x-display-name": "Update Item Permission",
        },
        title="Update Item Permission",
    )
    item_id: str = Field(
        ...,
        title="Item ID",
        description="File or folder",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "item_id",
                "placeholder": "Select an item...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste item ID",
            },
            "x-resource-type": "onedrive_item",
        },
    )
    permission_id: str = Field(
        ..., title="Permission ID", description="ID of the permission to update"
    )
    new_role: str = Field(
        ...,
        title="New Role",
        description="New permission level",
        json_schema_extra={
            "enum": ["read", "write", "owner"],
            "enumNames": ["Can View", "Can Edit", "Owner"],
            "x-enum-searchable": True,
        },
    )


class OneDriveDeletePermissionConfig(BaseModel):
    """Remove a permission"""

    operation: Literal["delete_item_permission"] = Field(
        "delete_item_permission",
        json_schema_extra={
            "const": "delete_item_permission",
            "ui:hidden": True,
            "x-category": "Item",
            "x-is-trigger": False,
            "x-display-name": "Delete Item Permission",
        },
        title="Delete Item Permission",
    )
    item_id: str = Field(
        ...,
        title="Item ID",
        description="File or folder",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "item_id",
                "placeholder": "Select an item...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste item ID",
            },
            "x-resource-type": "onedrive_item",
        },
    )
    permission_id: str = Field(
        ..., title="Permission ID", description="ID of the permission to remove"
    )


class OneDriveSendInviteConfig(BaseModel):
    """Send a sharing invitation"""

    operation: Literal["send_sharing_invitation"] = Field(
        "send_sharing_invitation",
        json_schema_extra={
            "const": "send_sharing_invitation",
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Send Sharing Invitation",
        },
        title="Send Sharing Invitation",
    )
    item_id: str = Field(
        ...,
        title="Item ID",
        description="File or folder to share",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "item_id",
                "placeholder": "Select an item...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste item ID",
            },
            "x-resource-type": "onedrive_item",
        },
    )
    recipient_email: str = Field(
        ..., title="Recipient Email", description="Email address to send invitation to"
    )
    message: Optional[str] = Field(
        None,
        title="Message",
        description="Optional message to include in the invitation",
    )
    require_sign_in: bool = Field(
        True, title="Require Sign In", description="Recipient must sign in to access"
    )


# ============================================================================
# Config Models - Versions (3 operations)
# ============================================================================


class OneDriveListVersionsConfig(BaseModel):
    """List all versions of a file"""

    operation: Literal["list_file_versions"] = Field(
        "list_file_versions",
        json_schema_extra={
            "const": "list_file_versions",
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "List File Versions",
        },
        title="List File Versions",
    )
    item_id: str = Field(
        ...,
        title="Item ID",
        description="File to get versions for",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "item_id",
                "placeholder": "Select a file...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste file ID",
            },
            "x-resource-type": "onedrive_item",
        },
    )


class OneDriveGetVersionConfig(BaseModel):
    """Get a specific version of a file"""

    operation: Literal["get_file_version"] = Field(
        "get_file_version",
        json_schema_extra={
            "const": "get_file_version",
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Get File Version",
        },
        title="Get File Version",
    )
    item_id: str = Field(
        ...,
        title="Item ID",
        description="File ID",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "item_id",
                "placeholder": "Select a file...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste file ID",
            },
            "x-resource-type": "onedrive_item",
        },
    )
    version_id: str = Field(
        ..., title="Version ID", description="ID of the version to retrieve"
    )


class OneDriveRestoreVersionConfig(BaseModel):
    """Restore a file to a previous version"""

    operation: Literal["restore_file_version"] = Field(
        "restore_file_version",
        json_schema_extra={
            "const": "restore_file_version",
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Restore File Version",
        },
        title="Restore File Version",
    )
    item_id: str = Field(
        ...,
        title="Item ID",
        description="File to restore",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "item_id",
                "placeholder": "Select a file...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste file ID",
            },
            "x-resource-type": "onedrive_item",
        },
    )
    version_id: str = Field(
        ..., title="Version ID", description="Version to restore to"
    )


# ============================================================================
# Config Models - Thumbnails (2 operations)
# ============================================================================


class OneDriveListThumbnailsConfig(BaseModel):
    """Get thumbnail images for a file"""

    operation: Literal["list_item_thumbnails"] = Field(
        "list_item_thumbnails",
        json_schema_extra={
            "const": "list_item_thumbnails",
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "List Item Thumbnails",
        },
        title="List Item Thumbnails",
    )
    item_id: str = Field(
        ...,
        title="Item ID",
        description="File to get thumbnails for",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "item_id",
                "placeholder": "Select a file...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste file ID",
            },
            "x-resource-type": "onedrive_item",
        },
    )


class OneDriveGetThumbnailConfig(BaseModel):
    """Get a specific thumbnail size"""

    operation: Literal["get_item_thumbnail"] = Field(
        "get_item_thumbnail",
        json_schema_extra={
            "const": "get_item_thumbnail",
            "ui:hidden": True,
            "x-category": "Item",
            "x-is-trigger": False,
            "x-display-name": "Get Item Thumbnail",
        },
        title="Get Item Thumbnail",
    )
    item_id: str = Field(
        ...,
        title="Item ID",
        description="File to get thumbnail for",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "item_id",
                "placeholder": "Select a file...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste file ID",
            },
            "x-resource-type": "onedrive_item",
        },
    )
    size: str = Field(
        "medium",
        title="Thumbnail Size",
        description="Size of thumbnail to retrieve",
        json_schema_extra={
            "enum": ["small", "medium", "large"],
            "enumNames": ["Small (96x96)", "Medium (176x176)", "Large (800x800)"],
            "x-enum-searchable": True,
        },
    )


# ============================================================================
# Config Models - Advanced Features (6 operations)
# ============================================================================


class OneDrivePreviewConfig(BaseModel):
    """Get a preview URL for a file"""

    operation: Literal["get_item_preview_url"] = Field(
        "get_item_preview_url",
        json_schema_extra={
            "const": "get_item_preview_url",
            "ui:hidden": True,
            "x-category": "Item",
            "x-is-trigger": False,
            "x-display-name": "Get Item Preview Url",
        },
        title="Get Item Preview Url",
    )
    item_id: str = Field(
        ...,
        title="Item ID",
        description="File to preview",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "item_id",
                "placeholder": "Select a file...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste file ID",
            },
            "x-resource-type": "onedrive_item",
        },
    )
    viewer: str = Field(
        "office",
        title="Viewer Type",
        description="Type of preview viewer",
        json_schema_extra={"enum": ["office", "onedrive"], "x-enum-searchable": True},
    )


class OneDriveGetContentStreamConfig(BaseModel):
    """Get download stream URL for a file"""

    operation: Literal["get_item_download_stream"] = Field(
        "get_item_download_stream",
        json_schema_extra={
            "const": "get_item_download_stream",
            "ui:hidden": True,
            "x-category": "Item",
            "x-is-trigger": False,
            "x-display-name": "Get Item Download Stream",
        },
        title="Get Item Download Stream",
    )
    item_id: str = Field(
        ...,
        title="Item ID",
        description="File to get download URL for",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "item_id",
                "placeholder": "Select a file...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste file ID",
            },
            "x-resource-type": "onedrive_item",
        },
    )


class OneDriveCheckOutConfig(BaseModel):
    """Check out a file (lock for editing)"""

    operation: Literal["check_out_file"] = Field(
        "check_out_file",
        json_schema_extra={
            "const": "check_out_file",
            "ui:hidden": True,
            "x-category": "Item",
            "x-is-trigger": False,
            "x-display-name": "Check Out File",
        },
        title="Check Out File",
    )
    item_id: str = Field(
        ...,
        title="Item ID",
        description="File to check out",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "item_id",
                "placeholder": "Select a file...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste file ID",
            },
            "x-resource-type": "onedrive_item",
        },
    )


class OneDriveCheckInConfig(BaseModel):
    """Check in a file (unlock and save)"""

    operation: Literal["check_in_file"] = Field(
        "check_in_file",
        json_schema_extra={
            "const": "check_in_file",
            "ui:hidden": True,
            "x-category": "Item",
            "x-is-trigger": False,
            "x-display-name": "Check in File",
        },
        title="Check in File",
    )
    item_id: str = Field(
        ...,
        title="Item ID",
        description="File to check in",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "item_id",
                "placeholder": "Select a file...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste file ID",
            },
            "x-resource-type": "onedrive_item",
        },
    )
    comment: Optional[str] = Field(
        None, title="Check-in Comment", description="Optional comment about the changes"
    )


class OneDriveDiscardCheckoutConfig(BaseModel):
    """Discard checkout (unlock without saving)"""

    operation: Literal["discard_file_checkout"] = Field(
        "discard_file_checkout",
        json_schema_extra={
            "const": "discard_file_checkout",
            "ui:hidden": True,
            "x-category": "Item",
            "x-is-trigger": False,
            "x-display-name": "Discard File Checkout",
        },
        title="Discard File Checkout",
    )
    item_id: str = Field(
        ...,
        title="Item ID",
        description="File to discard checkout for",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "item_id",
                "placeholder": "Select a file...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste file ID",
            },
            "x-resource-type": "onedrive_item",
        },
    )


class OneDriveGetAnalyticsConfig(BaseModel):
    """Get analytics for a file"""

    operation: Literal["get_item_analytics"] = Field(
        "get_item_analytics",
        json_schema_extra={
            "const": "get_item_analytics",
            "ui:hidden": True,
            "x-category": "Item",
            "x-is-trigger": False,
            "x-display-name": "Get Item Analytics",
        },
        title="Get Item Analytics",
    )
    item_id: str = Field(
        ...,
        title="Item ID",
        description="File to get analytics for",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "item_id",
                "placeholder": "Select a file...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste file ID",
            },
            "x-resource-type": "onedrive_item",
        },
    )


# ============================================================================
# Config Models - Special Items (4 operations)
# ============================================================================


class OneDriveGetSpecialFolderConfig(BaseModel):
    """Access special folders (Documents, Photos, etc.)"""

    operation: Literal["get_special_folder"] = Field(
        "get_special_folder",
        json_schema_extra={
            "const": "get_special_folder",
            "ui:hidden": True,
            "x-category": "Folder",
            "x-is-trigger": False,
            "x-display-name": "Get Special Folder",
        },
        title="Get Special Folder",
    )
    folder_name: str = Field(
        ...,
        title="Special Folder",
        description="Name of the special folder to access",
        json_schema_extra={
            "enum": ["documents", "photos", "cameraroll", "approot", "music"],
            "enumNames": ["Documents", "Photos", "Camera Roll", "App Root", "Music"],
            "x-enum-searchable": True,
        },
    )


class OneDriveListSharedWithMeConfig(BaseModel):
    """List items shared with the user"""

    operation: Literal["list_shared_items"] = Field(
        "list_shared_items",
        json_schema_extra={
            "const": "list_shared_items",
            "ui:hidden": True,
            "x-category": "Drive",
            "x-is-trigger": False,
            "x-display-name": "List Shared Items",
        },
        title="List Shared Items",
    )
    top: int = Field(
        50,
        title="Max Results",
        description="Maximum number of items to return",
        ge=1,
        le=999,
    )


class OneDriveListRecentConfig(BaseModel):
    """List recently accessed items"""

    operation: Literal["list_recent_items"] = Field(
        "list_recent_items",
        json_schema_extra={
            "const": "list_recent_items",
            "ui:hidden": True,
            "x-category": "Drive",
            "x-is-trigger": False,
            "x-display-name": "List Recent Items",
        },
        title="List Recent Items",
    )
    top: int = Field(
        20,
        title="Max Results",
        description="Maximum number of items to return",
        ge=1,
        le=999,
    )


class OneDriveFollowConfig(BaseModel):
    """Follow an item for updates"""

    operation: Literal["follow_item"] = Field(
        "follow_item",
        json_schema_extra={
            "const": "follow_item",
            "ui:hidden": True,
            "x-category": "Item",
            "x-is-trigger": False,
            "x-display-name": "Follow Item",
        },
        title="Follow Item",
    )
    item_id: str = Field(
        ...,
        title="Item ID",
        description="File or folder to follow",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "item_id",
                "placeholder": "Select an item...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste item ID",
            },
            "x-resource-type": "onedrive_item",
        },
    )


class OneDriveUnfollowConfig(BaseModel):
    """Unfollow an item"""

    operation: Literal["unfollow_item"] = Field(
        "unfollow_item",
        json_schema_extra={
            "const": "unfollow_item",
            "ui:hidden": True,
            "x-category": "Item",
            "x-is-trigger": False,
            "x-display-name": "Unfollow Item",
        },
        title="Unfollow Item",
    )
    item_id: str = Field(
        ...,
        title="Item ID",
        description="File or folder to unfollow",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "item_id",
                "placeholder": "Select an item...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste item ID",
            },
            "x-resource-type": "onedrive_item",
        },
    )


# ============================================================================
# Union Config Type with Discriminator
# ============================================================================

OneDriveConfig = Annotated[
    Union[
        # Core File Operations (10)
        OneDriveGetItemConfig,
        OneDriveListChildrenConfig,
        OneDriveUploadConfig,
        OneDriveUploadSessionConfig,
        OneDriveDownloadConfig,
        OneDriveUpdateItemConfig,
        OneDriveCreateFolderConfig,
        OneDriveCopyConfig,
        OneDriveMoveConfig,
        OneDriveDeleteConfig,
        # File Management (3)
        OneDriveRestoreConfig,
        OneDrivePermanentlyDeleteConfig,
        OneDriveGetDriveConfig,
        # Search & Discovery (2)
        OneDriveSearchConfig,
        OneDriveDeltaConfig,
        # Sharing & Permissions (6)
        OneDriveCreateLinkConfig,
        OneDriveListPermissionsConfig,
        OneDriveAddPermissionConfig,
        OneDriveUpdatePermissionConfig,
        OneDriveDeletePermissionConfig,
        OneDriveSendInviteConfig,
        # Versions (3)
        OneDriveListVersionsConfig,
        OneDriveGetVersionConfig,
        OneDriveRestoreVersionConfig,
        # Thumbnails (2)
        OneDriveListThumbnailsConfig,
        OneDriveGetThumbnailConfig,
        # Advanced Features (6)
        OneDrivePreviewConfig,
        OneDriveGetContentStreamConfig,
        OneDriveCheckOutConfig,
        OneDriveCheckInConfig,
        OneDriveDiscardCheckoutConfig,
        OneDriveGetAnalyticsConfig,
        # Special Items (4)
        OneDriveGetSpecialFolderConfig,
        OneDriveListSharedWithMeConfig,
        OneDriveListRecentConfig,
        OneDriveFollowConfig,
        OneDriveUnfollowConfig,
    ],
    Discriminator("operation"),
]


class OneDriveNodeConfig(NodeConfig[OneDriveConfig, OneDriveOAuthCredential]):
    """Full configuration for OneDrive node including credentials."""

    pass


# ============================================================================
# OneDrive Node Implementation
# ============================================================================


class OneDriveNode(WorkflowNode):
    """
    OneDrive workflow automation node.

    Comprehensive Microsoft OneDrive integration via Graph API supporting:
    - Core file operations (upload, download, copy, move, delete)
    - File management (restore, permanent delete, drive info)
    - Search and change tracking (search, delta queries)
    - Sharing and permissions (links, permissions, invitations)
    - Version control (list, get, restore versions)
    - Thumbnails (list and retrieve)
    - Advanced features (preview, checkout, analytics)
    - Special items (special folders, shared items, recent files, following)

    Total Operations: 37
    Authentication: Microsoft OAuth 2.0
    """

    edit_examples = [
        "Upload the monthly report PDF to the Finance folder",
        "Search OneDrive for all files modified in the last 7 days",
        "Copy the template.xlsx file to Shared Documents with new name",
        "Move archived invoices to the Archive folder and clean up",
        "Create a sharing link to the Q4 budget spreadsheet for the team",
        "Restore the accidentally deleted presentation from version history",
        "List all items in the root folder and sort by modification date",
    ]

    #: OAuth scope requirements per operation (nodes/scopes/microsoft.py).
    scope_registry = ONEDRIVE_SCOPES
    connection_evidence = ConnectionEvidence(
        field="folder_id",
        noun="folders",
    )

    @classmethod
    def get_config_model(cls):
        return OneDriveNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        """Refresh an expiring OAuth token at credential load (dropdowns,
        trigger registration). No-op for non-rotating credentials (API keys /
        offline / non-expiring tokens)."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.microsoft_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token,
            provider="microsoft",
        )

    async def _ensure_fresh_token(
        self, credentials: OneDriveOAuthCredential
    ) -> str:
        """Return a valid OneDrive access token, refreshing + persisting if expired."""
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.microsoft_oauth import refresh_access_token
        
        cred_dict = credentials.model_dump()
        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=cred_dict,
            refresh=refresh_access_token,
            provider="microsoft",
        )
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        if cred_dict.get("refresh_token"):
            credentials.refresh_token = cred_dict["refresh_token"]
        return token

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the OneDrive operation based on action"""
        if not self.config.credentials:
            raise ValueError("OneDrive credentials required")

        # Handle token refresh if needed
        access_token = await self._ensure_fresh_token(self.config.credentials)
        action = self.config.config.operation

        # Route to appropriate handler
        handlers = {
            # Core File Operations
            "get_item_metadata": self._get_item,
            "list_folder_contents": self._list_children,
            "upload_file": self._upload,
            "create_large_file_upload_session": self._upload_session,
            "download_item": self._download,
            "update_item_metadata": self._update_item,
            "create_folder": self._create_folder,
            "copy_item": self._copy,
            "move_item": self._move,
            "delete_item": self._delete,
            # File Management
            "restore_item_from_recycle_bin": self._restore,
            "permanently_delete_item": self._permanently_delete,
            "get_drive_info": self._get_drive,
            # Search & Discovery
            "search_drive_items": self._search,
            "track_drive_changes": self._delta,
            # Sharing & Permissions
            "create_sharing_link": self._create_link,
            "list_item_permissions": self._list_permissions,
            "grant_item_permission": self._add_permission,
            "update_item_permission": self._update_permission,
            "delete_item_permission": self._delete_permission,
            "send_sharing_invitation": self._send_invite,
            # Versions
            "list_file_versions": self._list_versions,
            "get_file_version": self._get_version,
            "restore_file_version": self._restore_version,
            # Thumbnails
            "list_item_thumbnails": self._list_thumbnails,
            "get_item_thumbnail": self._get_thumbnail,
            # Advanced Features
            "get_item_preview_url": self._preview,
            "get_item_download_stream": self._get_content_stream,
            "check_out_file": self._check_out,
            "check_in_file": self._check_in,
            "discard_file_checkout": self._discard_checkout,
            "get_item_analytics": self._get_analytics,
            # Special Items
            "get_special_folder": self._get_special_folder,
            "list_shared_items": self._list_shared_with_me,
            "list_recent_items": self._list_recent,
            "follow_item": self._follow,
            "unfollow_item": self._unfollow,
        }

        handler = handlers.get(action)
        if not handler:
            return {
                "status": "error",
                "action": action,
                "message": f"Unknown OneDrive action: {action}",
            }

        return await handler(self.config.config, access_token)

    # ========================================================================
    # Core File Operations (10 operations)
    # ========================================================================

    async def _get_item(
        self, config: OneDriveGetItemConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get metadata for a file or folder"""
        async with httpx.AsyncClient() as client:
            # Build URL based on ID or path
            if config.item_id:
                url = (
                    f"https://graph.microsoft.com/v1.0/me/drive/items/{config.item_id}"
                )
            elif config.item_path:
                # Remove leading slash if present
                path = config.item_path.lstrip("/")
                url = f"https://graph.microsoft.com/v1.0/me/drive/root:/{path}"
            else:
                # Get root folder
                url = "https://graph.microsoft.com/v1.0/me/drive/root"

            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                return {
                    "status": "error",
                    "action": "get_item_metadata",
                    "message": f"Failed to get item: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            return {
                "status": "success",
                "action": "get_item_metadata",
                "data": {
                    "id": data.get("id"),
                    "name": data.get("name"),
                    "size": data.get("size"),
                    "created_at": data.get("createdDateTime"),
                    "modified_at": data.get("lastModifiedDateTime"),
                    "type": "folder" if "folder" in data else "file",
                    "mime_type": data.get("file", {}).get("mimeType"),
                    "web_url": data.get("webUrl"),
                    "download_url": data.get("@microsoft.graph.downloadUrl"),
                    "parent_id": data.get("parentReference", {}).get("id"),
                    "full_metadata": data,
                },
            }

    async def _list_children(
        self, config: OneDriveListChildrenConfig, access_token: str
    ) -> Dict[str, Any]:
        """List contents of a folder"""
        async with httpx.AsyncClient() as client:
            # Build URL based on ID or path
            if config.folder_id:
                url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.folder_id}/children"
            elif config.folder_path:
                path = config.folder_path.lstrip("/")
                url = (
                    f"https://graph.microsoft.com/v1.0/me/drive/root:/{path}:/children"
                )
            else:
                # List root folder
                url = "https://graph.microsoft.com/v1.0/me/drive/root/children"

            params = {"$top": config.top}

            response = await client.get(
                url, params=params, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                return {
                    "status": "error",
                    "action": "list_folder_contents",
                    "message": f"Failed to list children: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            items = []
            for item in data.get("value", []):
                items.append(
                    {
                        "id": item.get("id"),
                        "name": item.get("name"),
                        "size": item.get("size"),
                        "type": "folder" if "folder" in item else "file",
                        "mime_type": item.get("file", {}).get("mimeType"),
                        "created_at": item.get("createdDateTime"),
                        "modified_at": item.get("lastModifiedDateTime"),
                        "web_url": item.get("webUrl"),
                    }
                )

            return {
                "status": "success",
                "action": "list_folder_contents",
                "data": {
                    "count": len(items),
                    "items": items,
                    "next_link": data.get("@odata.nextLink"),
                },
            }

    async def _upload(
        self, config: OneDriveUploadConfig, access_token: str
    ) -> Dict[str, Any]:
        """Upload a file (for files up to 4MB)"""
        async with httpx.AsyncClient() as client:
            # Build URL based on parent ID or path
            if config.parent_folder_id:
                url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.parent_folder_id}:/{config.file_name}:/content"
            elif config.parent_folder_path:
                path = config.parent_folder_path.lstrip("/")
                url = f"https://graph.microsoft.com/v1.0/me/drive/root:/{path}/{config.file_name}:/content"
            else:
                # Upload to root
                url = f"https://graph.microsoft.com/v1.0/me/drive/root:/{config.file_name}:/content"

            # A media reference (resource_id from an upstream download/upload, a
            # URL, or a data: URI) resolves to the file's bytes; plain text /
            # base64 keeps the existing path so text uploads still work.
            from nodes.core.media_resolver import looks_like_media_ref, resolve_media_input

            content_type = config.content_type
            if looks_like_media_ref(config.file_content):
                resolved = await resolve_media_input(
                    config.file_content, default_mime=config.content_type
                )
                content = resolved.data
                content_type = resolved.mime_type
            else:
                try:
                    content = base64.b64decode(config.file_content)
                except Exception:
                    content = config.file_content.encode("utf-8")

            response = await client.put(
                url,
                content=content,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": content_type,
                },
            )

            if response.status_code not in [200, 201]:
                return {
                    "status": "error",
                    "action": "upload_file",
                    "message": f"Failed to upload file: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            return {
                "status": "success",
                "action": "upload_file",
                "data": {
                    "id": data.get("id"),
                    "name": data.get("name"),
                    "size": data.get("size"),
                    "web_url": data.get("webUrl"),
                    "download_url": data.get("@microsoft.graph.downloadUrl"),
                },
            }

    async def _upload_session(
        self, config: OneDriveUploadSessionConfig, access_token: str
    ) -> Dict[str, Any]:
        """Create upload session for large files"""
        async with httpx.AsyncClient() as client:
            # Build URL
            if config.parent_folder_id:
                url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.parent_folder_id}:/{config.file_name}:/createUploadSession"
            elif config.parent_folder_path:
                path = config.parent_folder_path.lstrip("/")
                url = f"https://graph.microsoft.com/v1.0/me/drive/root:/{path}/{config.file_name}:/createUploadSession"
            else:
                url = f"https://graph.microsoft.com/v1.0/me/drive/root:/{config.file_name}:/createUploadSession"

            response = await client.post(
                url,
                json={"item": {"@microsoft.graph.conflictBehavior": "rename"}},
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code not in [200, 201]:
                return {
                    "status": "error",
                    "action": "create_large_file_upload_session",
                    "message": f"Failed to create upload session: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            return {
                "status": "success",
                "action": "create_large_file_upload_session",
                "data": {
                    "upload_url": data.get("uploadUrl"),
                    "expiration_datetime": data.get("expirationDateTime"),
                    "next_expected_ranges": data.get("nextExpectedRanges", []),
                },
            }

    async def _download(
        self, config: OneDriveDownloadConfig, access_token: str
    ) -> Dict[str, Any]:
        """Download file content"""
        async with guarded_async_client() as client:
            # Build URL
            if config.item_id:
                url = (
                    f"https://graph.microsoft.com/v1.0/me/drive/items/{config.item_id}"
                )
            elif config.item_path:
                path = config.item_path.lstrip("/")
                url = f"https://graph.microsoft.com/v1.0/me/drive/root:/{path}"
            else:
                return {
                    "status": "error",
                    "action": "download_item",
                    "message": "Either item_id or item_path must be provided",
                }

            # Add format parameter if specified
            if config.format:
                url += f"/content?format={config.format}"
            else:
                url += "/content"

            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                follow_redirects=True,
            )

            if response.status_code != 200:
                return {
                    "status": "error",
                    "action": "download_item",
                    "message": f"Failed to download file: {response.text}",
                    "status_code": response.status_code,
                }

            from nodes.core.binary_output import BinaryOutput

            content_type = (
                response.headers.get("content-type") or "application/octet-stream"
            )
            if config.item_path:
                filename = config.item_path.rstrip("/").split("/")[-1] or "download"
            else:
                filename = config.item_id or "download"
            if config.format:
                filename = f"{filename.rsplit('.', 1)[0]}.{config.format}"

            return {
                "status": "success",
                "action": "download_item",
                "data": {
                    "content": BinaryOutput(
                        data=response.content,
                        content_type=content_type,
                        filename=filename,
                    ),
                },
            }

    async def _update_item(
        self, config: OneDriveUpdateItemConfig, access_token: str
    ) -> Dict[str, Any]:
        """Update file or folder metadata"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.item_id}"

            update_data = {}
            if config.new_name:
                update_data["name"] = config.new_name
            if config.description is not None:
                update_data["description"] = config.description

            if not update_data:
                return {
                    "status": "error",
                    "action": "update_item_metadata",
                    "message": "No updates provided",
                }

            response = await client.patch(
                url,
                json=update_data,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                return {
                    "status": "error",
                    "action": "update_item_metadata",
                    "message": f"Failed to update item: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            return {
                "status": "success",
                "action": "update_item_metadata",
                "data": {
                    "id": data.get("id"),
                    "name": data.get("name"),
                    "description": data.get("description"),
                    "modified_at": data.get("lastModifiedDateTime"),
                },
            }

    async def _create_folder(
        self, config: OneDriveCreateFolderConfig, access_token: str
    ) -> Dict[str, Any]:
        """Create a new folder"""
        async with httpx.AsyncClient() as client:
            # Build URL
            if config.parent_folder_id:
                url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.parent_folder_id}/children"
            elif config.parent_folder_path:
                path = config.parent_folder_path.lstrip("/")
                url = (
                    f"https://graph.microsoft.com/v1.0/me/drive/root:/{path}:/children"
                )
            else:
                url = "https://graph.microsoft.com/v1.0/me/drive/root/children"

            response = await client.post(
                url,
                json={
                    "name": config.folder_name,
                    "folder": {},
                    "@microsoft.graph.conflictBehavior": "rename",
                },
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code not in [200, 201]:
                return {
                    "status": "error",
                    "action": "create_folder",
                    "message": f"Failed to create folder: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            return {
                "status": "success",
                "action": "create_folder",
                "data": {
                    "id": data.get("id"),
                    "name": data.get("name"),
                    "web_url": data.get("webUrl"),
                    "created_at": data.get("createdDateTime"),
                },
            }

    async def _copy(
        self, config: OneDriveCopyConfig, access_token: str
    ) -> Dict[str, Any]:
        """Copy a file or folder"""
        async with httpx.AsyncClient(timeout=30.0) as client:
            url = (
                f"https://graph.microsoft.com/v1.0/me/drive/items/{config.item_id}/copy"
            )

            copy_data = {}
            if config.destination_folder_id:
                copy_data["parentReference"] = {"id": config.destination_folder_id}
            if config.new_name:
                copy_data["name"] = config.new_name

            response = await client.post(
                url, json=copy_data, headers={"Authorization": f"Bearer {access_token}"}
            )

            # Copy is asynchronous, returns 202 Accepted with Location header
            if response.status_code not in [200, 201, 202]:
                return {
                    "status": "error",
                    "action": "copy_item",
                    "message": f"Failed to copy item: {response.text}",
                    "status_code": response.status_code,
                }

            monitor_url = response.headers.get("Location")

            return {
                "status": "success",
                "action": "copy_item",
                "data": {
                    "message": "Copy operation started",
                    "monitor_url": monitor_url,
                    "note": "Copy is asynchronous. Use monitor_url to check progress.",
                },
            }

    async def _move(
        self, config: OneDriveMoveConfig, access_token: str
    ) -> Dict[str, Any]:
        """Move a file or folder"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.item_id}"

            response = await client.patch(
                url,
                json={"parentReference": {"id": config.destination_folder_id}},
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                return {
                    "status": "error",
                    "action": "move_item",
                    "message": f"Failed to move item: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            return {
                "status": "success",
                "action": "move_item",
                "data": {
                    "id": data.get("id"),
                    "name": data.get("name"),
                    "parent_id": data.get("parentReference", {}).get("id"),
                    "web_url": data.get("webUrl"),
                },
            }

    async def _delete(
        self, config: OneDriveDeleteConfig, access_token: str
    ) -> Dict[str, Any]:
        """Delete a file or folder (moves to recycle bin)"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.item_id}"

            response = await client.delete(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 204:
                return {
                    "status": "error",
                    "action": "delete_item",
                    "message": f"Failed to delete item: {response.text}",
                    "status_code": response.status_code,
                }

            return {
                "status": "success",
                "action": "delete_item",
                "message": "Item moved to recycle bin",
            }

    # ========================================================================
    # File Management (3 operations)
    # ========================================================================

    async def _restore(
        self, config: OneDriveRestoreConfig, access_token: str
    ) -> Dict[str, Any]:
        """Restore a deleted item from recycle bin"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.item_id}/restore"

            restore_data = {}
            if config.parent_folder_id:
                restore_data["parentReference"] = {"id": config.parent_folder_id}

            response = await client.post(
                url,
                json=restore_data,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code not in [200, 201]:
                return {
                    "status": "error",
                    "action": "restore_item_from_recycle_bin",
                    "message": f"Failed to restore item: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            return {
                "status": "success",
                "action": "restore_item_from_recycle_bin",
                "data": {
                    "id": data.get("id"),
                    "name": data.get("name"),
                    "web_url": data.get("webUrl"),
                },
            }

    async def _permanently_delete(
        self, config: OneDrivePermanentlyDeleteConfig, access_token: str
    ) -> Dict[str, Any]:
        """Permanently delete an item"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.item_id}/permanentDelete"

            response = await client.post(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 204:
                return {
                    "status": "error",
                    "action": "permanently_delete_item",
                    "message": f"Failed to permanently delete item: {response.text}",
                    "status_code": response.status_code,
                }

            return {
                "status": "success",
                "action": "permanently_delete_item",
                "message": "Item permanently deleted",
            }

    async def _get_drive(
        self, config: OneDriveGetDriveConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get drive information and quota"""
        async with httpx.AsyncClient() as client:
            url = "https://graph.microsoft.com/v1.0/me/drive"

            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                return {
                    "status": "error",
                    "action": "get_drive_info",
                    "message": f"Failed to get drive info: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            quota = data.get("quota", {})

            return {
                "status": "success",
                "action": "get_drive_info",
                "data": {
                    "id": data.get("id"),
                    "drive_type": data.get("driveType"),
                    "owner": data.get("owner", {}).get("user", {}).get("displayName"),
                    "quota": {
                        "total": quota.get("total"),
                        "used": quota.get("used"),
                        "remaining": quota.get("remaining"),
                        "deleted": quota.get("deleted"),
                        "state": quota.get("state"),
                    },
                },
            }

    # ========================================================================
    # Search & Discovery (2 operations)
    # ========================================================================

    async def _search(
        self, config: OneDriveSearchConfig, access_token: str
    ) -> Dict[str, Any]:
        """Search for items in OneDrive"""
        async with httpx.AsyncClient() as client:
            url = "https://graph.microsoft.com/v1.0/me/drive/root/search(q='{query}')"
            url = url.format(query=config.query)

            params = {"$top": config.top}

            response = await client.get(
                url, params=params, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                return {
                    "status": "error",
                    "action": "search_drive_items",
                    "message": f"Failed to search: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            items = []
            for item in data.get("value", []):
                items.append(
                    {
                        "id": item.get("id"),
                        "name": item.get("name"),
                        "type": "folder" if "folder" in item else "file",
                        "path": item.get("parentReference", {}).get("path"),
                        "web_url": item.get("webUrl"),
                        "size": item.get("size"),
                        "modified_at": item.get("lastModifiedDateTime"),
                    }
                )

            return {
                "status": "success",
                "action": "search_drive_items",
                "data": {"count": len(items), "items": items},
            }

    async def _delta(
        self, config: OneDriveDeltaConfig, access_token: str
    ) -> Dict[str, Any]:
        """Track changes in OneDrive"""
        async with httpx.AsyncClient() as client:
            # Build URL
            if config.delta_token:
                # Continue from previous sync
                url = config.delta_token
            elif config.folder_id:
                url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.folder_id}/delta"
            else:
                url = "https://graph.microsoft.com/v1.0/me/drive/root/delta"

            # delta_token is an opaque, fully-qualified Graph URL. Keep the
            # OAuth bearer on the one provider origin that issued it.
            assert_exact_url_origin(url, GRAPH_API_ORIGIN)

            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                return {
                    "status": "error",
                    "action": "track_drive_changes",
                    "message": f"Failed to get delta: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            changes = []
            for item in data.get("value", []):
                change = {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "type": "folder" if "folder" in item else "file",
                    "deleted": "deleted" in item,
                }
                if not change["deleted"]:
                    change["modified_at"] = item.get("lastModifiedDateTime")
                    change["size"] = item.get("size")
                changes.append(change)

            return {
                "status": "success",
                "action": "track_drive_changes",
                "data": {
                    "changes": changes,
                    "delta_link": data.get("@odata.deltaLink"),
                    "next_link": data.get("@odata.nextLink"),
                },
            }

    # ========================================================================
    # Sharing & Permissions (6 operations)
    # ========================================================================

    async def _create_link(
        self, config: OneDriveCreateLinkConfig, access_token: str
    ) -> Dict[str, Any]:
        """Create a sharing link"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.item_id}/createLink"

            response = await client.post(
                url,
                json={"type": config.link_type, "scope": config.scope},
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code not in [200, 201]:
                return {
                    "status": "error",
                    "action": "create_sharing_link",
                    "message": f"Failed to create link: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            return {
                "status": "success",
                "action": "create_sharing_link",
                "data": {
                    "link_url": data.get("link", {}).get("webUrl"),
                    "type": data.get("link", {}).get("type"),
                    "scope": data.get("link", {}).get("scope"),
                    "permission_id": data.get("id"),
                },
            }

    async def _list_permissions(
        self, config: OneDriveListPermissionsConfig, access_token: str
    ) -> Dict[str, Any]:
        """List permissions for an item"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.item_id}/permissions"

            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                return {
                    "status": "error",
                    "action": "list_item_permissions",
                    "message": f"Failed to list permissions: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            permissions = []
            for perm in data.get("value", []):
                permissions.append(
                    {
                        "id": perm.get("id"),
                        "roles": perm.get("roles", []),
                        "link_type": perm.get("link", {}).get("type"),
                        "granted_to": perm.get("grantedTo", {})
                        .get("user", {})
                        .get("email"),
                        "granted_to_v2": perm.get("grantedToV2", {})
                        .get("user", {})
                        .get("email"),
                    }
                )

            return {
                "status": "success",
                "action": "list_item_permissions",
                "data": {"count": len(permissions), "permissions": permissions},
            }

    async def _add_permission(
        self, config: OneDriveAddPermissionConfig, access_token: str
    ) -> Dict[str, Any]:
        """Grant permission to a user"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.item_id}/invite"

            response = await client.post(
                url,
                json={
                    "requireSignIn": True,
                    "sendInvitation": config.send_invitation,
                    "roles": [config.role],
                    "recipients": [{"email": config.recipient_email}],
                },
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code not in [200, 201]:
                return {
                    "status": "error",
                    "action": "grant_item_permission",
                    "message": f"Failed to add permission: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            return {
                "status": "success",
                "action": "grant_item_permission",
                "data": {
                    "permission_id": data.get("value", [{}])[0].get("id"),
                    "roles": data.get("value", [{}])[0].get("roles", []),
                    "invitation_sent": config.send_invitation,
                },
            }

    async def _update_permission(
        self, config: OneDriveUpdatePermissionConfig, access_token: str
    ) -> Dict[str, Any]:
        """Update an existing permission"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.item_id}/permissions/{config.permission_id}"

            response = await client.patch(
                url,
                json={"roles": [config.new_role]},
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                return {
                    "status": "error",
                    "action": "update_item_permission",
                    "message": f"Failed to update permission: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            return {
                "status": "success",
                "action": "update_item_permission",
                "data": {
                    "permission_id": data.get("id"),
                    "roles": data.get("roles", []),
                },
            }

    async def _delete_permission(
        self, config: OneDriveDeletePermissionConfig, access_token: str
    ) -> Dict[str, Any]:
        """Remove a permission"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.item_id}/permissions/{config.permission_id}"

            response = await client.delete(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 204:
                return {
                    "status": "error",
                    "action": "delete_item_permission",
                    "message": f"Failed to delete permission: {response.text}",
                    "status_code": response.status_code,
                }

            return {
                "status": "success",
                "action": "delete_item_permission",
                "message": "Permission removed successfully",
            }

    async def _send_invite(
        self, config: OneDriveSendInviteConfig, access_token: str
    ) -> Dict[str, Any]:
        """Send a sharing invitation"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.item_id}/invite"

            invite_data = {
                "requireSignIn": config.require_sign_in,
                "sendInvitation": True,
                "roles": ["read"],
                "recipients": [{"email": config.recipient_email}],
            }
            if config.message:
                invite_data["message"] = config.message

            response = await client.post(
                url,
                json=invite_data,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code not in [200, 201]:
                return {
                    "status": "error",
                    "action": "send_sharing_invitation",
                    "message": f"Failed to send invitation: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            return {
                "status": "success",
                "action": "send_sharing_invitation",
                "data": {
                    "invitation_sent": True,
                    "recipient": config.recipient_email,
                    "permission_id": data.get("value", [{}])[0].get("id"),
                },
            }

    # ========================================================================
    # Versions (3 operations)
    # ========================================================================

    async def _list_versions(
        self, config: OneDriveListVersionsConfig, access_token: str
    ) -> Dict[str, Any]:
        """List all versions of a file"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.item_id}/versions"

            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                return {
                    "status": "error",
                    "action": "list_file_versions",
                    "message": f"Failed to list versions: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            versions = []
            for version in data.get("value", []):
                versions.append(
                    {
                        "id": version.get("id"),
                        "last_modified_at": version.get("lastModifiedDateTime"),
                        "size": version.get("size"),
                    }
                )

            return {
                "status": "success",
                "action": "list_file_versions",
                "data": {"count": len(versions), "versions": versions},
            }

    async def _get_version(
        self, config: OneDriveGetVersionConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get a specific version of a file"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.item_id}/versions/{config.version_id}"

            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                return {
                    "status": "error",
                    "action": "get_file_version",
                    "message": f"Failed to get version: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            return {
                "status": "success",
                "action": "get_file_version",
                "data": {
                    "id": data.get("id"),
                    "last_modified_at": data.get("lastModifiedDateTime"),
                    "size": data.get("size"),
                },
            }

    async def _restore_version(
        self, config: OneDriveRestoreVersionConfig, access_token: str
    ) -> Dict[str, Any]:
        """Restore a file to a previous version"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.item_id}/versions/{config.version_id}/restoreVersion"

            response = await client.post(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code not in [200, 201, 204]:
                return {
                    "status": "error",
                    "action": "restore_file_version",
                    "message": f"Failed to restore version: {response.text}",
                    "status_code": response.status_code,
                }

            return {
                "status": "success",
                "action": "restore_file_version",
                "message": "Version restored successfully",
            }

    # ========================================================================
    # Thumbnails (2 operations)
    # ========================================================================

    async def _list_thumbnails(
        self, config: OneDriveListThumbnailsConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get thumbnail images for a file"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.item_id}/thumbnails"

            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                return {
                    "status": "error",
                    "action": "list_item_thumbnails",
                    "message": f"Failed to list thumbnails: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            thumbnails = []
            for thumb_set in data.get("value", []):
                thumbnails.append(
                    {
                        "id": thumb_set.get("id"),
                        "small": thumb_set.get("small", {}).get("url"),
                        "medium": thumb_set.get("medium", {}).get("url"),
                        "large": thumb_set.get("large", {}).get("url"),
                    }
                )

            return {
                "status": "success",
                "action": "list_item_thumbnails",
                "data": {"thumbnails": thumbnails},
            }

    async def _get_thumbnail(
        self, config: OneDriveGetThumbnailConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get a specific thumbnail size"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.item_id}/thumbnails/0/{config.size}"

            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                return {
                    "status": "error",
                    "action": "get_item_thumbnail",
                    "message": f"Failed to get thumbnail: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            return {
                "status": "success",
                "action": "get_item_thumbnail",
                "data": {
                    "url": data.get("url"),
                    "width": data.get("width"),
                    "height": data.get("height"),
                },
            }

    # ========================================================================
    # Advanced Features (6 operations)
    # ========================================================================

    async def _preview(
        self, config: OneDrivePreviewConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get a preview URL for a file"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.item_id}/preview"

            response = await client.post(
                url,
                json={"viewer": config.viewer},
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code not in [200, 201]:
                return {
                    "status": "error",
                    "action": "get_item_preview_url",
                    "message": f"Failed to get preview: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            return {
                "status": "success",
                "action": "get_item_preview_url",
                "data": {
                    "preview_url": data.get("getUrl"),
                    "post_url": data.get("postUrl"),
                    "post_parameters": data.get("postParameters"),
                },
            }

    async def _get_content_stream(
        self, config: OneDriveGetContentStreamConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get download stream URL"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.item_id}"

            response = await client.get(
                url,
                params={"$select": "@microsoft.graph.downloadUrl"},
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                return {
                    "status": "error",
                    "action": "get_item_download_stream",
                    "message": f"Failed to get download URL: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            return {
                "status": "success",
                "action": "get_item_download_stream",
                "data": {
                    "download_url": data.get("@microsoft.graph.downloadUrl"),
                    "note": "URL expires after a short time",
                },
            }

    async def _check_out(
        self, config: OneDriveCheckOutConfig, access_token: str
    ) -> Dict[str, Any]:
        """Check out a file"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.item_id}/checkout"

            response = await client.post(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code not in [200, 201, 204]:
                return {
                    "status": "error",
                    "action": "check_out_file",
                    "message": f"Failed to check out file: {response.text}",
                    "status_code": response.status_code,
                }

            return {
                "status": "success",
                "action": "check_out_file",
                "message": "File checked out successfully",
            }

    async def _check_in(
        self, config: OneDriveCheckInConfig, access_token: str
    ) -> Dict[str, Any]:
        """Check in a file"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.item_id}/checkin"

            checkin_data = {}
            if config.comment:
                checkin_data["comment"] = config.comment

            response = await client.post(
                url,
                json=checkin_data,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code not in [200, 201, 204]:
                return {
                    "status": "error",
                    "action": "check_in_file",
                    "message": f"Failed to check in file: {response.text}",
                    "status_code": response.status_code,
                }

            return {
                "status": "success",
                "action": "check_in_file",
                "message": "File checked in successfully",
            }

    async def _discard_checkout(
        self, config: OneDriveDiscardCheckoutConfig, access_token: str
    ) -> Dict[str, Any]:
        """Discard checkout"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.item_id}/discardCheckout"

            response = await client.post(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code not in [200, 201, 204]:
                return {
                    "status": "error",
                    "action": "discard_file_checkout",
                    "message": f"Failed to discard checkout: {response.text}",
                    "status_code": response.status_code,
                }

            return {
                "status": "success",
                "action": "discard_file_checkout",
                "message": "Checkout discarded successfully",
            }

    async def _get_analytics(
        self, config: OneDriveGetAnalyticsConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get analytics for a file"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.item_id}/analytics"

            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                return {
                    "status": "error",
                    "action": "get_item_analytics",
                    "message": f"Failed to get analytics: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            return {
                "status": "success",
                "action": "get_item_analytics",
                "data": {
                    "item_activity_stats": data.get("itemActivityStats", []),
                    "all_time": data.get("allTime"),
                    "last_seven_days": data.get("lastSevenDays"),
                },
            }

    # ========================================================================
    # Special Items (4 operations)
    # ========================================================================

    async def _get_special_folder(
        self, config: OneDriveGetSpecialFolderConfig, access_token: str
    ) -> Dict[str, Any]:
        """Access special folders"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/special/{config.folder_name}"

            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                return {
                    "status": "error",
                    "action": "get_special_folder",
                    "message": f"Failed to get special folder: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            return {
                "status": "success",
                "action": "get_special_folder",
                "data": {
                    "id": data.get("id"),
                    "name": data.get("name"),
                    "web_url": data.get("webUrl"),
                },
            }

    async def _list_shared_with_me(
        self, config: OneDriveListSharedWithMeConfig, access_token: str
    ) -> Dict[str, Any]:
        """List items shared with the user"""
        async with httpx.AsyncClient() as client:
            url = "https://graph.microsoft.com/v1.0/me/drive/sharedWithMe"

            params = {"$top": config.top}

            response = await client.get(
                url, params=params, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                return {
                    "status": "error",
                    "action": "list_shared_items",
                    "message": f"Failed to list shared items: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            items = []
            for item in data.get("value", []):
                items.append(
                    {
                        "id": item.get("id"),
                        "name": item.get("name"),
                        "type": "folder" if "folder" in item else "file",
                        "shared_by": item.get("remoteItem", {})
                        .get("shared", {})
                        .get("sharedBy", {})
                        .get("user", {})
                        .get("displayName"),
                        "web_url": item.get("webUrl"),
                    }
                )

            return {
                "status": "success",
                "action": "list_shared_items",
                "data": {"count": len(items), "items": items},
            }

    async def _list_recent(
        self, config: OneDriveListRecentConfig, access_token: str
    ) -> Dict[str, Any]:
        """List recently accessed items"""
        async with httpx.AsyncClient() as client:
            url = "https://graph.microsoft.com/v1.0/me/drive/recent"

            params = {"$top": config.top}

            response = await client.get(
                url, params=params, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                return {
                    "status": "error",
                    "action": "list_recent_items",
                    "message": f"Failed to list recent items: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            items = []
            for item in data.get("value", []):
                items.append(
                    {
                        "id": item.get("id"),
                        "name": item.get("name"),
                        "type": "folder" if "folder" in item else "file",
                        "last_accessed_at": item.get("lastModifiedDateTime"),
                        "web_url": item.get("webUrl"),
                    }
                )

            return {
                "status": "success",
                "action": "list_recent_items",
                "data": {"count": len(items), "items": items},
            }

    async def _follow(
        self, config: OneDriveFollowConfig, access_token: str
    ) -> Dict[str, Any]:
        """Follow an item"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.item_id}/follow"

            response = await client.post(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code not in [200, 201]:
                return {
                    "status": "error",
                    "action": "follow_item",
                    "message": f"Failed to follow item: {response.text}",
                    "status_code": response.status_code,
                }

            data = response.json()
            return {
                "status": "success",
                "action": "follow_item",
                "data": {
                    "id": data.get("id"),
                    "name": data.get("name"),
                    "following": True,
                },
            }

    async def _unfollow(
        self, config: OneDriveUnfollowConfig, access_token: str
    ) -> Dict[str, Any]:
        """Unfollow an item"""
        async with httpx.AsyncClient() as client:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{config.item_id}/unfollow"

            response = await client.post(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code not in [200, 201, 204]:
                return {
                    "status": "error",
                    "action": "unfollow_item",
                    "message": f"Failed to unfollow item: {response.text}",
                    "status_code": response.status_code,
                }

            return {
                "status": "success",
                "action": "unfollow_item",
                "message": "Item unfollowed successfully",
            }

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Load dynamic options for a field with pagination support.

        This is called by the workflow handler when the frontend needs
        to populate dropdowns (e.g., list of files/folders from OneDrive).

        Args:
            field_name: Name of the field needing options (e.g., "item_id", "folder_id")
            credential_data: Decrypted OAuth credential data
            context: Additional context for filtering
            page_token: Optional token for pagination
            search: Optional case-insensitive substring filter applied to option labels/values

        Returns:
            Dict with 'options' (list of option dicts) and 'next_page_token' (optional)
        """
        logger.info(
            f"[OneDriveNode] load_field_options called: field={field_name}, page_token={page_token}"
        )

        # All OneDrive dynamic fields essentially list items
        # Some filter to folders only, others show all items
        if field_name in ["item_id", "source_id", "dest_parent_folder_id"]:
            # List all files and folders
            return await cls._list_items(
                credential_data, page_token, folders_only=False, search=search
            )
        elif field_name in ["folder_id", "parent_folder_id"]:
            # List folders only
            return await cls._list_items(
                credential_data, page_token, folders_only=True, search=search
            )

        return {"options": [], "next_page_token": None}

    @classmethod
    async def _list_items(
        cls,
        credential_data: Dict[str, Any],
        page_token: Optional[str] = None,
        folders_only: bool = False,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List items (files / folders) from OneDrive root.

        Microsoft Graph's ``/me/drive/root/children`` has no native search,
        so search mode delegates to :func:`load_paginated_options` for
        paginate-and-filter via ``$skiptoken``.
        """
        access_token = require_credential_token(
            credential_data.get("access_token"),
            "Connect a Microsoft account to load OneDrive files and folders",
        )

        url = "https://graph.microsoft.com/v1.0/me/drive/root/children"

        async def fetch_page(
            cursor: Optional[str],
        ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
            params: Dict[str, Any] = {
                "$top": 100,
                "$orderby": "lastModifiedDateTime desc",
                "$select": "id,name,folder,file,size,lastModifiedDateTime",
            }
            if cursor:
                params["$skiptoken"] = cursor

            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {access_token}"},
                    params=params,
                )

            if response.status_code != 200:
                error_data = response.json() if response.text else {}
                error_msg = error_data.get("error", {}).get(
                    "message", response.text
                )
                raise ValueError(
                    f"Microsoft Graph API error ({response.status_code}): {error_msg}"
                )

            data = response.json()
            items = data.get("value", [])
            options = []
            for item in items:
                is_folder = "folder" in item
                if folders_only and not is_folder:
                    continue
                options.append(
                    {
                        "value": item.get("id"),
                        "label": item.get("name"),
                        "description": "📁 Folder"
                        if is_folder
                        else f"📄 File ({item.get('size', 0)} bytes)",
                        "metadata": {
                            "is_folder": is_folder,
                            "size": item.get("size"),
                            "last_modified": item.get("lastModifiedDateTime"),
                        },
                    }
                )

            next_link = data.get("@odata.nextLink")
            next_cursor = None
            if next_link:
                from urllib.parse import urlparse, parse_qs

                parsed = urlparse(next_link)
                query_params = parse_qs(parsed.query)
                if "$skiptoken" in query_params:
                    next_cursor = query_params["$skiptoken"][0]
            return options, next_cursor

        return await load_paginated_options(
            fetch_page,
            page_token=page_token,
            search=search,
            log_label=f"OneDriveNode._list_items(folders_only={folders_only})",
        )
