"""
Google Drive workflow node implementation.
Enables file operations on Google Drive via OAuth credentials.

Supports 40 operations:
- File: list, get, download, upload, create_folder, copy, move, delete, update, search, export
- Trash: trash, restore, empty_trash
- Permissions: share, unshare, list_permissions, get_permission, update_permission
- Comments: create_comment, list_comments, get_comment, update_comment, delete_comment
- Replies: create_reply, list_replies, get_reply, update_reply, delete_reply
- Revisions: list_revisions, get_revision, update_revision, delete_revision
- Shared Drives: list_shared_drives, get_shared_drive, create_shared_drive, delete_shared_drive,
                 hide_shared_drive, unhide_shared_drive
- Account: get_about (storage quota and user info)
"""

import hmac
import secrets
import time
import base64
import logging
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, Union, Type, List, Annotated, Literal, ClassVar
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.watch_channels import (
    WatchChannelTriggerMixin,
    get_watch_channel,
    save_watch_channel,
    update_channel_subscription,
)
from nodes.oauth.google_oauth import is_token_expired, refresh_access_token
from nodes.oauth.google_token import ensure_fresh_google_token
from nodes.core.dynamic_options import require_credential_token
from nodes.scopes.google import GOOGLE_DRIVE_SCOPES

logger = logging.getLogger(__name__)

GOOGLE_DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
GOOGLE_UPLOAD_API_BASE = "https://www.googleapis.com/upload/drive/v3"
_FOLDER_MIME = "application/vnd.google-apps.folder"

# Watch channels are requested for 7 days; the renewal cron refreshes them well
# before expiry (it scans 12h ahead every 6h).
_DRIVE_CHANNEL_TTL = timedelta(days=7)


# ============================================================================
# Drive change-watch helpers (used by the trigger and the renewal job)
# ============================================================================


def _ms_to_datetime(ms_epoch: Optional[str]) -> datetime:
    """Convert a Google ms-since-epoch expiration string to a datetime."""
    if ms_epoch:
        try:
            return datetime.fromtimestamp(int(ms_epoch) / 1000, tz=timezone.utc)
        except (ValueError, TypeError):
            pass
    return datetime.now(timezone.utc) + _DRIVE_CHANNEL_TTL


async def drive_get_start_page_token(access_token: str) -> str:
    """Fetch the current Drive changes cursor (baseline for changes.list)."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{GOOGLE_DRIVE_API_BASE}/changes/startPageToken",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()
        return response.json()["startPageToken"]


async def drive_watch_changes(
    access_token: str,
    channel_id: str,
    webhook_url: str,
    channel_token: str,
    page_token: str,
) -> Dict[str, Any]:
    """Open a Drive changes watch channel. Returns the channel resource."""
    expiration_ms = int(
        (datetime.now(timezone.utc) + _DRIVE_CHANNEL_TTL).timestamp() * 1000
    )
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{GOOGLE_DRIVE_API_BASE}/changes/watch",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            params={"pageToken": page_token},
            json={
                "id": channel_id,
                "type": "web_hook",
                "address": webhook_url,
                "token": channel_token,
                "expiration": expiration_ms,
            },
        )
        response.raise_for_status()
        return response.json()


async def drive_stop_channel(
    access_token: str, channel_id: str, resource_id: str
) -> None:
    """Stop a Drive watch channel."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{GOOGLE_DRIVE_API_BASE}/channels/stop",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={"id": channel_id, "resourceId": resource_id},
        )
        if response.status_code not in (200, 204, 404):
            response.raise_for_status()


def _drive_item_icon(
    name: str, mime_type: str, *, is_root: bool = False
) -> Optional[str]:
    """Return the existing frontend SVG path for Google-native Drive items."""
    if is_root or mime_type == _FOLDER_MIME:
        return "/icons/drive.svg"

    google_mime_icons = {
        "application/vnd.google-apps.document": "/icons/google-docs.svg",
        "application/vnd.google-apps.spreadsheet": "/icons/sheets.svg",
        "application/vnd.google-apps.presentation": "/icons/google-slides.svg",
        "application/vnd.google-apps.form": "/icons/google-forms.svg",
    }
    if mime_type in google_mime_icons:
        return google_mime_icons[mime_type]

    return None


def _drive_item_emoji(mime_type: str) -> str:
    return "📁" if mime_type == _FOLDER_MIME else "📄"


def _drive_item_label(name: str, parent_name: Optional[str]) -> str:
    if parent_name:
        return f"{parent_name}  /  {name}"
    return name


async def drive_list_changes(access_token: str, page_token: str) -> Dict[str, Any]:
    """List Drive changes since *page_token*."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{GOOGLE_DRIVE_API_BASE}/changes",
            headers={"Authorization": f"Bearer {access_token}"},
            params={
                "pageToken": page_token,
                "pageSize": 100,
                "fields": "changes(fileId,removed,type,file(id,name,mimeType,createdTime,modifiedTime,trashed,parents)),"
                "nextPageToken,newStartPageToken",
            },
        )
        response.raise_for_status()
        return response.json()


# ============================================================================
# Google Drive Node Credential Schema
# ============================================================================


class GoogleDriveOAuthCredential(BaseModel):
    """
    OAuth credential for Google Drive access.
    Tokens are obtained via OAuth flow, not entered manually.
    """

    credential_type: Literal["google_drive_oauth"] = Field(
        "google_drive_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ..., title="Access Token", description="OAuth 2.0 access token from Google"
    )
    refresh_token: str = Field(
        ...,
        title="Refresh Token",
        description="OAuth 2.0 refresh token for automatic renewal",
    )
    expires_at: str = Field(
        ...,
        title="Token Expiry",
        description="ISO 8601 timestamp when access token expires",
    )
    email: str = Field(
        ...,
        title="Google Account",
        description="Email address of the connected Google account",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "google",
            "x-oauth-scopes": ["https://www.googleapis.com/auth/drive"],
        }
    )


# ============================================================================
# Google Drive Node Configuration Models
# ============================================================================


class GoogleDriveListConfig(BaseModel):
    """Configuration for listing files in Google Drive"""

    operation: Literal["list_files"] = Field(
        "list_files",
        title="List Files",
        description="List files from Google Drive",
        json_schema_extra={
            "ui:hidden": True,
            "const": "list_files",
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "List Files",
            "x-keywords": [
                "browse files",
                "list my files",
                "all files",
                "files in folder",
                "enumerate files",
            ],
        },
    )
    folder_id: Optional[str] = Field(
        None,
        title="Folder",
        description="Select a folder to list files from (leave empty for root)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "folder_id",
                "placeholder": "Select a folder (root if empty)...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste folder ID",
            },
            "x-resource-type": "google_drive_folder",
        },
    )
    query: Optional[str] = Field(
        None,
        title="Search Query",
        description="Search query (e.g., name contains 'report')",
        json_schema_extra={"placeholder": "name contains 'report'"},
    )
    page_size: int = Field(
        100,
        title="Page Size",
        description="Maximum number of files to return (1-1000)",
        ge=1,
        le=1000,
    )
    include_trashed: bool = Field(
        False, title="Include Trashed", description="Include files in trash"
    )


class GoogleDriveGetConfig(BaseModel):
    """Configuration for getting file metadata"""

    operation: Literal["get_file_metadata"] = Field(
        "get_file_metadata",
        title="Get File Metadata",
        description="Get file metadata",
        json_schema_extra={
            "ui:hidden": True,
            "const": "get_file_metadata",
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Get File Metadata",
            "x-keywords": [
                "file details",
                "file info",
                "file properties",
                "inspect file",
                "about this file",
            ],
        },
    )
    file_id: str = Field(
        ...,
        title="File",
        description="Select a file to get metadata for",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "file_id",
                "placeholder": "Select a file...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste file ID",
            },
            "x-resource-type": "google_drive_file",
        },
    )


class GoogleDriveDownloadConfig(BaseModel):
    """Configuration for downloading file content"""

    operation: Literal["download_file"] = Field(
        "download_file",
        title="Download File",
        description="Download file content",
        json_schema_extra={
            "ui:hidden": True,
            "const": "download_file",
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Download File",
            "x-keywords": [
                "save file locally",
                "get file content",
                "fetch file bytes",
                "grab file",
            ],
        },
    )
    file_id: str = Field(
        ...,
        title="File",
        description="Select a file to download",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "file_id",
                "placeholder": "Select a file...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste file ID",
            },
            "x-resource-type": "google_drive_file",
        },
    )
    export_format: Optional[str] = Field(
        None,
        title="Export Format",
        description="For Google Docs: pdf, docx, txt, html. For Sheets: xlsx, csv, pdf. Leave empty for binary files.",
        json_schema_extra={"placeholder": "pdf, docx, xlsx, csv, etc."},
    )


class GoogleDriveCreateFolderConfig(BaseModel):
    """Configuration for creating a folder"""

    operation: Literal["create_folder"] = Field(
        "create_folder",
        title="Create Folder",
        description="Create a new folder",
        json_schema_extra={
            "ui:hidden": True,
            "const": "create_folder",
            "x-category": "Folder",
            "x-is-trigger": False,
            "x-display-name": "Create Folder",
            "x-keywords": ["new folder", "make folder", "add folder", "make directory"],
            "x-creates-resource": True,
            "x-resource-type": "google_drive_folder",
            "x-resource-id-path": "folder.id",
        },
    )
    folder_name: str = Field(
        ..., title="Folder Name", description="Name for the new folder"
    )
    parent_folder_id: Optional[str] = Field(
        None,
        title="Parent Folder",
        description="Parent folder (leave empty for root)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "folder_id",
                "placeholder": "Select parent folder (root if empty)...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste folder ID",
            },
            "x-resource-type": "google_drive_folder",
        },
    )


class GoogleDriveUploadConfig(BaseModel):
    """Configuration for uploading a file"""

    operation: Literal["upload_file"] = Field(
        "upload_file",
        title="Upload File",
        description="Upload a file",
        json_schema_extra={
            "ui:hidden": True,
            "const": "upload_file",
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Upload File",
            "x-keywords": [
                "add new file",
                "put file",
                "save to drive",
                "send file to drive",
            ],
            "x-creates-resource": True,
            "x-resource-type": "google_drive_file",
            "x-resource-id-path": "file.id",
        },
    )
    file_name: str = Field(
        ...,
        title="File Name",
        description="Name for the uploaded file (including extension)",
    )
    content: str = Field(
        ...,
        title="Content",
        description="File content: plain text, or — for binary — a URL, an upstream file reference (e.g. {{http-1.response.url}}), a data: URI, or base64.",
        json_schema_extra={"ui:widget": "textarea"},
    )
    mime_type: Optional[str] = Field(
        None,
        title="MIME Type",
        description="File MIME type (auto-detected if not specified)",
        json_schema_extra={"placeholder": "text/plain, application/json, etc."},
    )
    parent_folder_id: Optional[str] = Field(
        None,
        title="Parent Folder",
        description="Folder to upload to (leave empty for root)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "folder_id",
                "placeholder": "Select folder (root if empty)...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste folder ID",
            },
            "x-resource-type": "google_drive_folder",
        },
    )
    is_base64: bool = Field(
        False,
        title="Base64 Encoded",
        description="Check if content is base64-encoded binary data",
    )


class GoogleDriveCopyConfig(BaseModel):
    """Configuration for copying a file"""

    operation: Literal["copy_file"] = Field(
        "copy_file",
        title="Copy File",
        description="Copy a file",
        json_schema_extra={
            "ui:hidden": True,
            "const": "copy_file",
            "x-category": "File",
            "x-creates-resource": True,
            "x-resource-type": "google_drive_file",
            "x-resource-id-path": "file.id",
            "x-is-trigger": False,
            "x-display-name": "Copy File",
            "x-keywords": ["duplicate file", "clone file", "make a copy"],
        },
    )
    file_id: str = Field(
        ...,
        title="File",
        description="Select a file to copy",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "file_id",
                "placeholder": "Select a file...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste file ID",
            },
            "x-resource-type": "google_drive_file",
        },
    )
    new_name: Optional[str] = Field(
        None,
        title="New Name",
        description="Name for the copy (optional, defaults to 'Copy of [original]')",
    )
    destination_folder_id: Optional[str] = Field(
        None,
        title="Destination Folder",
        description="Folder to copy to (leave empty for same location)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "folder_id",
                "placeholder": "Select destination folder...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste folder ID",
            },
            "x-resource-type": "google_drive_folder",
        },
    )


class GoogleDriveMoveConfig(BaseModel):
    """Configuration for moving a file"""

    operation: Literal["move_file"] = Field(
        "move_file",
        title="Move File",
        description="Move a file to another folder",
        json_schema_extra={
            "ui:hidden": True,
            "const": "move_file",
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Move File",
            "x-keywords": [
                "relocate file",
                "change file folder",
                "move to folder",
                "transfer file",
            ],
        },
    )
    file_id: str = Field(
        ...,
        title="File",
        description="Select a file to move",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "file_id",
                "placeholder": "Select a file...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste file ID",
            },
            "x-resource-type": "google_drive_file",
        },
    )
    destination_folder_id: str = Field(
        ...,
        title="Destination Folder",
        description="Folder to move file to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "folder_id",
                "placeholder": "Select destination folder...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste folder ID",
            },
            "x-resource-type": "google_drive_folder",
        },
    )


class GoogleDriveDeleteConfig(BaseModel):
    """Configuration for deleting a file"""

    operation: Literal["delete_file"] = Field(
        "delete_file",
        title="Delete File",
        description="Delete a file permanently",
        json_schema_extra={
            "ui:hidden": True,
            "const": "delete_file",
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Delete File",
            "x-keywords": [
                "permanently delete file",
                "erase file forever",
                "destroy file",
            ],
        },
    )
    file_id: str = Field(
        ...,
        title="File",
        description="Select a file to delete",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "file_id",
                "placeholder": "Select a file...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste file ID",
            },
            "x-resource-type": "google_drive_file",
        },
    )


class GoogleDriveShareConfig(BaseModel):
    """Configuration for sharing a file"""

    operation: Literal["share_file"] = Field(
        "share_file",
        title="Share File",
        description="Share a file with others",
        json_schema_extra={
            "ui:hidden": True,
            "const": "share_file",
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Share File",
            "x-keywords": [
                "grant access",
                "give permission",
                "add collaborator",
                "invite to file",
                "make shareable",
            ],
        },
    )
    file_id: str = Field(
        ...,
        title="File",
        description="Select a file to share",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "file_id",
                "placeholder": "Select a file...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste file ID",
            },
            "x-resource-type": "google_drive_file",
        },
    )
    share_type: str = Field(
        ...,
        title="Share Type",
        description="Who to share with",
        json_schema_extra={
            "enum": ["user", "group", "domain", "anyone"],
            "enumLabels": ["Specific User", "Group", "Domain", "Anyone with link"],
        },
    )
    email: Optional[str] = Field(
        None,
        title="Email Address",
        description="Email address for user/group sharing",
        json_schema_extra={"placeholder": "user@example.com"},
    )
    role: str = Field(
        "reader",
        title="Permission",
        description="Permission level to grant",
        json_schema_extra={
            "enum": ["reader", "commenter", "writer"],
            "enumLabels": ["Viewer", "Commenter", "Editor"],
        },
    )
    send_notification: bool = Field(
        True,
        title="Send Notification",
        description="Send email notification to the user",
    )


class GoogleDriveExportConfig(BaseModel):
    """Configuration for exporting Google Workspace documents"""

    operation: Literal["export_google_workspace_file"] = Field(
        "export_google_workspace_file",
        title="Export Google Workspace File",
        description="Export Google Docs/Sheets/Slides to other formats",
        json_schema_extra={
            "ui:hidden": True,
            "const": "export_google_workspace_file",
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Export Google Workspace File",
            "x-keywords": [
                "export doc",
                "convert google doc",
                "export as pdf",
                "save docs as",
                "convert workspace file",
            ],
        },
    )
    file_id: str = Field(
        ...,
        title="File",
        description="Select a Google Workspace file to export (Docs, Sheets, Slides only)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "exportable_file_id",
                "placeholder": "Select a Google Docs/Sheets/Slides file...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste file ID",
            },
            "x-resource-type": "google_drive_file",
        },
    )
    export_format: str = Field(
        ...,
        title="Export Format",
        description="Format to export the file as",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "export_format",
                "placeholder": "Select export format...",
                "searchable": False,
                "allow_custom": False,
            }
        },
    )


class GoogleDriveUpdateConfig(BaseModel):
    """Configuration for updating file metadata"""

    operation: Literal["update_file_metadata"] = Field(
        "update_file_metadata",
        title="Update File Metadata",
        description="Update file name or description",
        json_schema_extra={
            "ui:hidden": True,
            "const": "update_file_metadata",
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Update File Metadata",
            "x-keywords": [
                "rename file",
                "edit file properties",
                "change file name",
                "modify file info",
            ],
        },
    )
    file_id: str = Field(
        ...,
        title="File",
        description="Select a file to update",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "file_id",
                "placeholder": "Select a file...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste file ID",
            },
            "x-resource-type": "google_drive_file",
        },
    )
    new_name: Optional[str] = Field(
        None,
        title="New Name",
        description="New name for the file (leave empty to keep current)",
        json_schema_extra={"placeholder": "New file name"},
    )
    description: Optional[str] = Field(
        None,
        title="Description",
        description="New description for the file",
        json_schema_extra={"ui:widget": "textarea", "placeholder": "File description"},
    )
    starred: Optional[bool] = Field(
        None, title="Starred", description="Mark file as starred"
    )


class GoogleDriveTrashConfig(BaseModel):
    """Configuration for moving a file to trash"""

    operation: Literal["move_file_to_trash"] = Field(
        "move_file_to_trash",
        title="Move File to Trash",
        description="Move a file to trash",
        json_schema_extra={
            "ui:hidden": True,
            "const": "move_file_to_trash",
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Move File to Trash",
            "x-keywords": [
                "trash file",
                "send file to bin",
                "soft delete file",
                "recycle file",
            ],
        },
    )
    file_id: str = Field(
        ...,
        title="File",
        description="Select a file to move to trash",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "file_id",
                "placeholder": "Select a file...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste file ID",
            },
            "x-resource-type": "google_drive_file",
        },
    )


class GoogleDriveRestoreConfig(BaseModel):
    """Configuration for restoring a file from trash"""

    operation: Literal["restore_file_from_trash"] = Field(
        "restore_file_from_trash",
        title="Restore File from Trash",
        description="Restore a file from trash",
        json_schema_extra={
            "ui:hidden": True,
            "const": "restore_file_from_trash",
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Restore File from Trash",
            "x-keywords": [
                "untrash file",
                "recover file",
                "restore deleted file",
                "bring back file",
            ],
        },
    )
    file_id: str = Field(
        ...,
        title="File ID",
        description="ID of the trashed file to restore",
        json_schema_extra={"placeholder": "File ID from trash"},
    )


class GoogleDriveEmptyTrashConfig(BaseModel):
    """Configuration for emptying trash"""

    operation: Literal["empty_drive_trash"] = Field(
        "empty_drive_trash",
        title="Empty Drive Trash",
        description="Permanently delete all files in trash",
        json_schema_extra={
            "ui:hidden": True,
            "const": "empty_drive_trash",
            "x-category": "Drive",
            "x-is-trigger": False,
            "x-display-name": "Empty Drive Trash",
            "x-keywords": [
                "empty trash",
                "clear bin",
                "purge trash",
                "empty recycle bin",
            ],
        },
    )
    confirm: bool = Field(
        False,
        title="Confirm Empty Trash",
        description="Check to confirm permanently deleting all trashed files (cannot be undone)",
    )


class GoogleDriveUnshareConfig(BaseModel):
    """Configuration for removing file permissions"""

    operation: Literal["remove_file_permission"] = Field(
        "remove_file_permission",
        title="Remove File Permission",
        description="Remove sharing permissions from a file",
        json_schema_extra={
            "ui:hidden": True,
            "const": "remove_file_permission",
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Remove File Permission",
            "x-keywords": [
                "revoke access",
                "unshare file",
                "remove collaborator",
                "take away access",
            ],
        },
    )
    file_id: str = Field(
        ...,
        title="File",
        description="Select a file to unshare",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "file_id",
                "placeholder": "Select a file...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste file ID",
            },
            "x-resource-type": "google_drive_file",
        },
    )
    permission_id: Optional[str] = Field(
        None,
        title="Permission ID",
        description="Specific permission ID to remove (leave empty to remove all except owner)",
        json_schema_extra={"placeholder": "Permission ID (optional)"},
    )
    email: Optional[str] = Field(
        None,
        title="Email Address",
        description="Email of user to remove access (alternative to permission ID)",
        json_schema_extra={"placeholder": "user@example.com"},
    )


class GoogleDriveListPermissionsConfig(BaseModel):
    """Configuration for listing file permissions"""

    operation: Literal["list_file_permissions"] = Field(
        "list_file_permissions",
        title="List File Permissions",
        description="List who has access to a file",
        json_schema_extra={
            "ui:hidden": True,
            "const": "list_file_permissions",
            "x-category": "File Permission",
            "x-is-trigger": False,
            "x-display-name": "List File Permissions",
            "x-keywords": [
                "who has access",
                "list collaborators",
                "view sharing",
                "all permissions",
            ],
        },
    )
    file_id: str = Field(
        ...,
        title="File",
        description="Select a file to list permissions",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "file_id",
                "placeholder": "Select a file...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste file ID",
            },
            "x-resource-type": "google_drive_file",
        },
    )


class GoogleDriveSearchConfig(BaseModel):
    """Configuration for advanced file search"""

    operation: Literal["search_files"] = Field(
        "search_files",
        title="Search Files",
        description="Search files with advanced query",
        json_schema_extra={
            "ui:hidden": True,
            "const": "search_files",
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Search Files",
            "x-keywords": [
                "find files",
                "query files",
                "advanced file search",
                "look for files",
            ],
        },
    )
    query: str = Field(
        ...,
        title="Search Query",
        description="Search query (e.g., name contains 'report' and mimeType='application/pdf')",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "name contains 'report' and modifiedTime > '2024-01-01'",
        },
    )
    page_size: int = Field(
        100,
        title="Page Size",
        description="Maximum number of results (1-1000)",
        ge=1,
        le=1000,
    )
    order_by: Optional[str] = Field(
        "modifiedTime desc",
        title="Order By",
        description="Sort order for results",
        json_schema_extra={
            "enum": [
                "modifiedTime desc",
                "modifiedTime asc",
                "name",
                "name desc",
                "createdTime desc",
                "folder",
            ],
            "enumLabels": [
                "Modified (newest)",
                "Modified (oldest)",
                "Name (A-Z)",
                "Name (Z-A)",
                "Created (newest)",
                "Folders first",
            ],
        },
    )


class GoogleDriveCreateCommentConfig(BaseModel):
    """Configuration for creating a comment on a file"""

    operation: Literal["create_file_comment"] = Field(
        "create_file_comment",
        title="Create File Comment",
        description="Add a comment to a file",
        json_schema_extra={
            "ui:hidden": True,
            "const": "create_file_comment",
            "x-category": "File Comment",
            "x-is-trigger": False,
            "x-display-name": "Create File Comment",
            "x-keywords": [
                "add comment",
                "comment on file",
                "leave a note",
                "annotate file",
            ],
        },
    )
    file_id: str = Field(
        ...,
        title="File",
        description="Select a file to comment on",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "file_id",
                "placeholder": "Select a file...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste file ID",
            },
            "x-resource-type": "google_drive_file",
        },
    )
    content: str = Field(
        ...,
        title="Comment",
        description="Comment text",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "Enter your comment...",
        },
    )


class GoogleDriveListCommentsConfig(BaseModel):
    """Configuration for listing comments on a file"""

    operation: Literal["list_file_comments"] = Field(
        "list_file_comments",
        title="List File Comments",
        description="List all comments on a file",
        json_schema_extra={
            "ui:hidden": True,
            "const": "list_file_comments",
            "x-category": "File Comment",
            "x-is-trigger": False,
            "x-display-name": "List File Comments",
            "x-keywords": [
                "view comments",
                "all comments",
                "read file comments",
                "show annotations",
            ],
        },
    )
    file_id: str = Field(
        ...,
        title="File",
        description="Select a file to list comments",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "file_id",
                "placeholder": "Select a file...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste file ID",
            },
            "x-resource-type": "google_drive_file",
        },
    )
    include_deleted: bool = Field(
        False, title="Include Deleted", description="Include deleted comments"
    )


class GoogleDriveDeleteCommentConfig(BaseModel):
    """Configuration for deleting a comment"""

    operation: Literal["delete_file_comment"] = Field(
        "delete_file_comment",
        title="Delete File Comment",
        description="Delete a comment from a file",
        json_schema_extra={
            "ui:hidden": True,
            "const": "delete_file_comment",
            "x-category": "File Comment",
            "x-is-trigger": False,
            "x-display-name": "Delete File Comment",
            "x-keywords": ["remove comment", "erase comment", "drop comment"],
        },
    )
    file_id: str = Field(
        ...,
        title="File",
        description="Select a file",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "file_id",
                "placeholder": "Select a file...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste file ID",
            },
            "x-resource-type": "google_drive_file",
        },
    )
    comment_id: str = Field(
        ...,
        title="Comment ID",
        description="ID of the comment to delete",
        json_schema_extra={"placeholder": "Comment ID"},
    )


class GoogleDriveGetCommentConfig(BaseModel):
    """Configuration for getting a single comment"""

    operation: Literal["get_file_comment"] = Field(
        "get_file_comment",
        title="Get File Comment",
        description="Get a specific comment by ID",
        json_schema_extra={
            "ui:hidden": True,
            "const": "get_file_comment",
            "x-category": "File Comment",
            "x-is-trigger": False,
            "x-display-name": "Get File Comment",
            "x-keywords": [
                "read one comment",
                "view single comment",
                "fetch specific comment",
            ],
        },
    )
    file_id: str = Field(
        ...,
        title="File",
        description="Select a file",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "file_id",
                "placeholder": "Select a file...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste file ID",
            },
            "x-resource-type": "google_drive_file",
        },
    )
    comment_id: str = Field(
        ...,
        title="Comment ID",
        description="ID of the comment to retrieve",
        json_schema_extra={"placeholder": "Comment ID"},
    )


class GoogleDriveUpdateCommentConfig(BaseModel):
    """Configuration for updating a comment"""

    operation: Literal["update_file_comment"] = Field(
        "update_file_comment",
        title="Update File Comment",
        description="Update an existing comment",
        json_schema_extra={
            "ui:hidden": True,
            "const": "update_file_comment",
            "x-category": "File Comment",
            "x-is-trigger": False,
            "x-display-name": "Update File Comment",
            "x-keywords": ["edit comment", "change comment text", "modify comment"],
        },
    )
    file_id: str = Field(
        ...,
        title="File",
        description="Select a file",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "file_id",
                "placeholder": "Select a file...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste file ID",
            },
            "x-resource-type": "google_drive_file",
        },
    )
    comment_id: str = Field(
        ...,
        title="Comment ID",
        description="ID of the comment to update",
        json_schema_extra={"placeholder": "Comment ID"},
    )
    content: str = Field(
        ...,
        title="New Content",
        description="Updated comment text",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "Updated comment...",
        },
    )


class GoogleDriveCreateReplyConfig(BaseModel):
    """Configuration for creating a reply to a comment"""

    operation: Literal["create_comment_reply"] = Field(
        "create_comment_reply",
        title="Create Comment Reply",
        description="Add a reply to an existing comment",
        json_schema_extra={
            "ui:hidden": True,
            "const": "create_comment_reply",
            "x-category": "Comment Reply",
            "x-is-trigger": False,
            "x-display-name": "Create Comment Reply",
            "x-keywords": [
                "reply to comment",
                "respond to comment",
                "answer comment",
                "add reply",
            ],
        },
    )
    file_id: str = Field(
        ...,
        title="File",
        description="Select a file",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "file_id",
                "placeholder": "Select a file...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste file ID",
            },
            "x-resource-type": "google_drive_file",
        },
    )
    comment_id: str = Field(
        ...,
        title="Comment ID",
        description="ID of the comment to reply to",
        json_schema_extra={"placeholder": "Comment ID"},
    )
    content: str = Field(
        ...,
        title="Reply",
        description="Reply text",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "Enter your reply...",
        },
    )


class GoogleDriveListRepliesConfig(BaseModel):
    """Configuration for listing replies to a comment"""

    operation: Literal["list_comment_replies"] = Field(
        "list_comment_replies",
        title="List Comment Replies",
        description="List all replies to a comment",
        json_schema_extra={
            "ui:hidden": True,
            "const": "list_comment_replies",
            "x-category": "Comment Reply",
            "x-is-trigger": False,
            "x-display-name": "List Comment Replies",
            "x-keywords": [
                "view replies",
                "all replies",
                "read comment replies",
                "show responses",
            ],
        },
    )
    file_id: str = Field(
        ...,
        title="File",
        description="Select a file",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "file_id",
                "placeholder": "Select a file...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste file ID",
            },
            "x-resource-type": "google_drive_file",
        },
    )
    comment_id: str = Field(
        ...,
        title="Comment ID",
        description="ID of the comment",
        json_schema_extra={"placeholder": "Comment ID"},
    )


class GoogleDriveDeleteReplyConfig(BaseModel):
    """Configuration for deleting a reply"""

    operation: Literal["delete_comment_reply"] = Field(
        "delete_comment_reply",
        title="Delete Comment Reply",
        description="Delete a reply from a comment",
        json_schema_extra={
            "ui:hidden": True,
            "const": "delete_comment_reply",
            "x-category": "Comment Reply",
            "x-is-trigger": False,
            "x-display-name": "Delete Comment Reply",
            "x-keywords": ["remove reply", "erase reply", "drop reply"],
        },
    )
    file_id: str = Field(
        ...,
        title="File",
        description="Select a file",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "file_id",
                "placeholder": "Select a file...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste file ID",
            },
            "x-resource-type": "google_drive_file",
        },
    )
    comment_id: str = Field(
        ...,
        title="Comment ID",
        description="ID of the comment",
        json_schema_extra={"placeholder": "Comment ID"},
    )
    reply_id: str = Field(
        ...,
        title="Reply ID",
        description="ID of the reply to delete",
        json_schema_extra={"placeholder": "Reply ID"},
    )


class GoogleDriveListRevisionsConfig(BaseModel):
    """Configuration for listing file revisions"""

    operation: Literal["list_file_revisions"] = Field(
        "list_file_revisions",
        title="List File Revisions",
        description="List all versions of a file",
        json_schema_extra={
            "ui:hidden": True,
            "const": "list_file_revisions",
            "x-category": "File Revision",
            "x-is-trigger": False,
            "x-display-name": "List File Revisions",
            "x-keywords": [
                "version history",
                "file versions",
                "revision history",
                "all revisions",
            ],
        },
    )
    file_id: str = Field(
        ...,
        title="File",
        description="Select a file to list revisions",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "file_id",
                "placeholder": "Select a file...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste file ID",
            },
            "x-resource-type": "google_drive_file",
        },
    )


class GoogleDriveGetRevisionConfig(BaseModel):
    """Configuration for getting a specific revision"""

    operation: Literal["get_file_revision"] = Field(
        "get_file_revision",
        title="Get File Revision",
        description="Get a specific file revision",
        json_schema_extra={
            "ui:hidden": True,
            "const": "get_file_revision",
            "x-category": "File Revision",
            "x-is-trigger": False,
            "x-display-name": "Get File Revision",
            "x-keywords": [
                "view one version",
                "single revision",
                "specific version",
                "fetch revision",
            ],
        },
    )
    file_id: str = Field(
        ...,
        title="File",
        description="Select a file",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "file_id",
                "placeholder": "Select a file...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste file ID",
            },
            "x-resource-type": "google_drive_file",
        },
    )
    revision_id: str = Field(
        ...,
        title="Revision ID",
        description="ID of the revision",
        json_schema_extra={"placeholder": "Revision ID"},
    )


class GoogleDriveDeleteRevisionConfig(BaseModel):
    """Configuration for deleting a revision"""

    operation: Literal["delete_file_revision"] = Field(
        "delete_file_revision",
        title="Delete File Revision",
        description="Delete a specific file revision",
        json_schema_extra={
            "ui:hidden": True,
            "const": "delete_file_revision",
            "x-category": "File Revision",
            "x-is-trigger": False,
            "x-display-name": "Delete File Revision",
            "x-keywords": ["remove revision", "delete old version", "erase version"],
        },
    )
    file_id: str = Field(
        ...,
        title="File",
        description="Select a file",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "file_id",
                "placeholder": "Select a file...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste file ID",
            },
            "x-resource-type": "google_drive_file",
        },
    )
    revision_id: str = Field(
        ...,
        title="Revision ID",
        description="ID of the revision to delete",
        json_schema_extra={"placeholder": "Revision ID"},
    )


class GoogleDriveGetPermissionConfig(BaseModel):
    """Configuration for getting a specific permission"""

    operation: Literal["get_file_permission"] = Field(
        "get_file_permission",
        title="Get File Permission",
        description="Get details of a specific permission",
        json_schema_extra={
            "ui:hidden": True,
            "const": "get_file_permission",
            "x-category": "File Permission",
            "x-is-trigger": False,
            "x-display-name": "Get File Permission",
            "x-keywords": [
                "check one permission",
                "view single access",
                "specific collaborator access",
            ],
        },
    )
    file_id: str = Field(
        ...,
        title="File",
        description="Select a file",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "file_id",
                "placeholder": "Select a file...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste file ID",
            },
            "x-resource-type": "google_drive_file",
        },
    )
    permission_id: str = Field(
        ...,
        title="Permission ID",
        description="ID of the permission",
        json_schema_extra={"placeholder": "Permission ID"},
    )
    supports_all_drives: bool = Field(
        False,
        title="Supports All Drives",
        description="Include shared drives in the request",
    )


class GoogleDriveUpdatePermissionConfig(BaseModel):
    """Configuration for updating a permission"""

    operation: Literal["update_file_permission"] = Field(
        "update_file_permission",
        title="Update File Permission",
        description="Update a permission (change role)",
        json_schema_extra={
            "ui:hidden": True,
            "const": "update_file_permission",
            "x-category": "File Permission",
            "x-is-trigger": False,
            "x-display-name": "Update File Permission",
            "x-keywords": [
                "change access level",
                "edit permission role",
                "change collaborator role",
                "modify sharing",
            ],
        },
    )
    file_id: str = Field(
        ...,
        title="File",
        description="Select a file",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "file_id",
                "placeholder": "Select a file...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste file ID",
            },
            "x-resource-type": "google_drive_file",
        },
    )
    permission_id: str = Field(
        ...,
        title="Permission ID",
        description="ID of the permission to update",
        json_schema_extra={"placeholder": "Permission ID"},
    )
    role: str = Field(
        ...,
        title="New Role",
        description="New role for the permission",
        json_schema_extra={
            "enum": [
                "reader",
                "commenter",
                "writer",
                "fileOrganizer",
                "organizer",
                "owner",
            ],
            "enumLabels": [
                "Viewer",
                "Commenter",
                "Editor",
                "File Organizer",
                "Organizer",
                "Owner",
            ],
        },
    )
    supports_all_drives: bool = Field(
        False,
        title="Supports All Drives",
        description="Include shared drives in the request",
    )
    transfer_ownership: bool = Field(
        False,
        title="Transfer Ownership",
        description="Transfer ownership to the specified user (use with owner role)",
    )
    expiration_time: Optional[str] = Field(
        None,
        title="Expiration Time",
        description="Expiration time for the permission (ISO 8601 format)",
    )


class GoogleDriveGetReplyConfig(BaseModel):
    """Configuration for getting a specific reply"""

    operation: Literal["get_comment_reply"] = Field(
        "get_comment_reply",
        title="Get Comment Reply",
        description="Get a specific reply by ID",
        json_schema_extra={
            "ui:hidden": True,
            "const": "get_comment_reply",
            "x-category": "Comment Reply",
            "x-is-trigger": False,
            "x-display-name": "Get Comment Reply",
            "x-keywords": [
                "read one reply",
                "view single reply",
                "fetch specific reply",
            ],
        },
    )
    file_id: str = Field(
        ...,
        title="File",
        description="Select a file",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "file_id",
                "placeholder": "Select a file...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste file ID",
            },
            "x-resource-type": "google_drive_file",
        },
    )
    comment_id: str = Field(
        ...,
        title="Comment ID",
        description="ID of the comment",
        json_schema_extra={"placeholder": "Comment ID"},
    )
    reply_id: str = Field(
        ...,
        title="Reply ID",
        description="ID of the reply",
        json_schema_extra={"placeholder": "Reply ID"},
    )
    include_deleted: bool = Field(
        False,
        title="Include Deleted",
        description="Include deleted replies in the response",
    )


class GoogleDriveUpdateReplyConfig(BaseModel):
    """Configuration for updating a reply"""

    operation: Literal["update_comment_reply"] = Field(
        "update_comment_reply",
        title="Update Comment Reply",
        description="Update an existing reply",
        json_schema_extra={
            "ui:hidden": True,
            "const": "update_comment_reply",
            "x-category": "Comment Reply",
            "x-is-trigger": False,
            "x-display-name": "Update Comment Reply",
            "x-keywords": ["edit reply", "change reply text", "modify reply"],
        },
    )
    file_id: str = Field(
        ...,
        title="File",
        description="Select a file",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "file_id",
                "placeholder": "Select a file...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste file ID",
            },
            "x-resource-type": "google_drive_file",
        },
    )
    comment_id: str = Field(
        ...,
        title="Comment ID",
        description="ID of the comment",
        json_schema_extra={"placeholder": "Comment ID"},
    )
    reply_id: str = Field(
        ...,
        title="Reply ID",
        description="ID of the reply to update",
        json_schema_extra={"placeholder": "Reply ID"},
    )
    content: str = Field(
        ...,
        title="New Content",
        description="Updated reply text",
        json_schema_extra={"ui:widget": "textarea", "placeholder": "Updated reply..."},
    )


class GoogleDriveUpdateRevisionConfig(BaseModel):
    """Configuration for updating revision metadata"""

    operation: Literal["update_file_revision"] = Field(
        "update_file_revision",
        title="Update File Revision",
        description="Update revision metadata (keep forever, etc.)",
        json_schema_extra={
            "ui:hidden": True,
            "const": "update_file_revision",
            "x-category": "File Revision",
            "x-is-trigger": False,
            "x-display-name": "Update File Revision",
            "x-keywords": [
                "edit revision",
                "keep version forever",
                "pin revision",
                "modify version metadata",
            ],
        },
    )
    file_id: str = Field(
        ...,
        title="File",
        description="Select a file",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "file_id",
                "placeholder": "Select a file...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste file ID",
            },
            "x-resource-type": "google_drive_file",
        },
    )
    revision_id: str = Field(
        ...,
        title="Revision ID",
        description="ID of the revision",
        json_schema_extra={"placeholder": "Revision ID"},
    )
    keep_forever: Optional[bool] = Field(
        None,
        title="Keep Forever",
        description="Whether to keep this revision forever (prevents auto-deletion)",
    )
    publish_auto: Optional[bool] = Field(
        None, title="Auto Publish", description="Automatically publish new revisions"
    )
    published: Optional[bool] = Field(
        None, title="Published", description="Whether this revision is published"
    )


class GoogleDriveListSharedDrivesConfig(BaseModel):
    """Configuration for listing shared drives"""

    operation: Literal["list_shared_drives"] = Field(
        "list_shared_drives",
        title="List Shared Drives",
        description="List all shared drives accessible to the user",
        json_schema_extra={
            "ui:hidden": True,
            "const": "list_shared_drives",
            "x-category": "Shared Drive",
            "x-is-trigger": False,
            "x-display-name": "List Shared Drives",
            "x-keywords": [
                "browse team drives",
                "list team drives",
                "all shared drives",
                "my shared drives",
            ],
        },
    )
    page_size: int = Field(
        100,
        title="Page Size",
        description="Maximum number of shared drives to return",
        ge=1,
        le=100,
    )
    use_domain_admin_access: bool = Field(
        False,
        title="Use Domain Admin Access",
        description="Use domain administrator privileges",
    )


class GoogleDriveGetSharedDriveConfig(BaseModel):
    """Configuration for getting shared drive details"""

    operation: Literal["get_shared_drive"] = Field(
        "get_shared_drive",
        title="Get Shared Drive",
        description="Get details of a specific shared drive",
        json_schema_extra={
            "ui:hidden": True,
            "const": "get_shared_drive",
            "x-category": "Shared Drive",
            "x-is-trigger": False,
            "x-display-name": "Get Shared Drive",
            "x-keywords": [
                "team drive details",
                "shared drive info",
                "inspect team drive",
            ],
        },
    )
    drive_id: str = Field(
        ...,
        title="Shared Drive ID",
        description="ID of the shared drive",
        json_schema_extra={"placeholder": "Shared Drive ID"},
    )
    use_domain_admin_access: bool = Field(
        False,
        title="Use Domain Admin Access",
        description="Use domain administrator privileges",
    )


class GoogleDriveCreateSharedDriveConfig(BaseModel):
    """Configuration for creating a shared drive"""

    operation: Literal["create_shared_drive"] = Field(
        "create_shared_drive",
        title="Create Shared Drive",
        description="Create a new shared drive",
        json_schema_extra={
            "ui:hidden": True,
            "const": "create_shared_drive",
            "x-category": "Shared Drive",
            "x-is-trigger": False,
            "x-display-name": "Create Shared Drive",
            "x-keywords": ["new team drive", "make shared drive", "add team drive"],
        },
    )
    name: str = Field(..., title="Name", description="Name for the new shared drive")


class GoogleDriveDeleteSharedDriveConfig(BaseModel):
    """Configuration for deleting a shared drive"""

    operation: Literal["delete_shared_drive"] = Field(
        "delete_shared_drive",
        title="Delete Shared Drive",
        description="Delete a shared drive (must be empty)",
        json_schema_extra={
            "ui:hidden": True,
            "const": "delete_shared_drive",
            "x-category": "Shared Drive",
            "x-is-trigger": False,
            "x-display-name": "Delete Shared Drive",
            "x-keywords": [
                "remove team drive",
                "erase shared drive",
                "destroy team drive",
            ],
        },
    )
    drive_id: str = Field(
        ...,
        title="Shared Drive ID",
        description="ID of the shared drive to delete",
        json_schema_extra={"placeholder": "Shared Drive ID"},
    )
    use_domain_admin_access: bool = Field(
        False,
        title="Use Domain Admin Access",
        description="Use domain administrator privileges",
    )
    allow_item_deletion: bool = Field(
        False,
        title="Allow Item Deletion",
        description="Allow deleting drive even if it contains items",
    )


class GoogleDriveHideSharedDriveConfig(BaseModel):
    """Configuration for hiding a shared drive"""

    operation: Literal["hide_shared_drive"] = Field(
        "hide_shared_drive",
        title="Hide Shared Drive",
        description="Hide a shared drive from the default view",
        json_schema_extra={
            "ui:hidden": True,
            "const": "hide_shared_drive",
            "x-category": "Shared Drive",
            "x-is-trigger": False,
            "x-display-name": "Hide Shared Drive",
            "x-keywords": [
                "conceal team drive",
                "remove from sidebar",
                "stop showing drive",
            ],
        },
    )
    drive_id: str = Field(
        ...,
        title="Shared Drive ID",
        description="ID of the shared drive to hide",
        json_schema_extra={"placeholder": "Shared Drive ID"},
    )


class GoogleDriveUnhideSharedDriveConfig(BaseModel):
    """Configuration for unhiding a shared drive"""

    operation: Literal["unhide_shared_drive"] = Field(
        "unhide_shared_drive",
        title="Unhide Shared Drive",
        description="Unhide a shared drive (restore to default view)",
        json_schema_extra={
            "ui:hidden": True,
            "const": "unhide_shared_drive",
            "x-category": "Shared Drive",
            "x-is-trigger": False,
            "x-display-name": "Unhide Shared Drive",
            "x-keywords": [
                "show team drive again",
                "reveal hidden drive",
                "bring back drive",
            ],
        },
    )
    drive_id: str = Field(
        ...,
        title="Shared Drive ID",
        description="ID of the shared drive to unhide",
        json_schema_extra={"placeholder": "Shared Drive ID"},
    )


class GoogleDriveGetAboutConfig(BaseModel):
    """Configuration for getting Drive storage info"""

    operation: Literal["get_drive_storage_info"] = Field(
        "get_drive_storage_info",
        title="Get Drive Storage Info",
        description="Get storage quota and user info",
        json_schema_extra={
            "ui:hidden": True,
            "const": "get_drive_storage_info",
            "x-category": "Drive",
            "x-is-trigger": False,
            "x-display-name": "Get Drive Storage Info",
            "x-keywords": [
                "storage usage",
                "space left",
                "quota usage",
                "how much space",
                "disk quota",
            ],
        },
    )


class GoogleDriveOnChangeConfig(BaseModel):
    """Trigger: fires when files change in the connected Google Drive."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["on_drive_change"] = Field(
        "on_drive_change",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Drive Change",
            "x-keywords": [
                "when drive changes",
                "watch my drive",
                "on any change",
                "drive activity",
            ],
        },
        title="On Drive Change",
    )
    webhook_id: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:copyable": True,
            "ui:loadValue": True,
        },
    )
    signing_secret: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    drive_page_token: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    relay_connected: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    is_production: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    trigger_registered: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    trigger_error: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )


class GoogleDriveOnFileChangedConfig(BaseModel):
    """Trigger: fires when a file is created or modified in Google Drive."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["on_file_changed"] = Field(
        "on_file_changed",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On File Changed",
            "x-keywords": [
                "when new file",
                "on file created",
                "when file modified",
                "watch for file",
                "new file added",
            ],
        },
        title="On File Changed",
    )
    watch_target_id: Optional[str] = Field(
        None,
        title="Watch File or Folder",
        description="Select a file to monitor exactly, or a folder to monitor files within it and all descendant subfolders. Leave empty to watch the entire Drive.",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "watch_target_id",
                "placeholder": "Any file or folder in Drive",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste file/folder ID",
            }
        },
    )
    webhook_id: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:copyable": True,
            "ui:loadValue": True,
        },
    )
    signing_secret: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    drive_page_token: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    relay_connected: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    is_production: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    trigger_registered: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    trigger_error: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )


class GoogleDriveOnFileRemovedConfig(BaseModel):
    """Trigger: fires when a file is trashed or permanently deleted from Google Drive."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["on_file_removed"] = Field(
        "on_file_removed",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On File Removed",
            "x-keywords": [
                "when file trashed",
                "on file deleted",
                "when file gone",
                "watch deleted files",
            ],
        },
        title="On File Removed",
    )
    watch_target_id: Optional[str] = Field(
        None,
        title="Watch File or Folder",
        description="Select a file to monitor exactly, or a folder to monitor files within it and all descendant subfolders. Leave empty to watch the entire Drive.",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "watch_target_id",
                "placeholder": "Any file or folder in Drive",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste file/folder ID",
            }
        },
    )
    webhook_id: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:copyable": True,
            "ui:loadValue": True,
        },
    )
    signing_secret: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    drive_page_token: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    relay_connected: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    is_production: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    trigger_registered: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    trigger_error: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )


class GoogleDriveOnFolderChangedConfig(BaseModel):
    """Trigger: fires when a folder is created or modified in Google Drive."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["on_folder_changed"] = Field(
        "on_folder_changed",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Folder Changed",
            "x-keywords": [
                "when new folder",
                "on folder created",
                "when folder modified",
                "watch for folder",
            ],
        },
        title="On Folder Changed",
    )
    watch_parent_folder_id: Optional[str] = Field(
        None,
        title="Watch Folder",
        description="Only trigger for this folder and its descendant subfolders. Leave empty to watch all folders.",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "watch_parent_folder_id",
                "placeholder": "All folders (entire Drive)",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste folder ID",
            },
            "x-resource-type": "google_drive_folder",
        },
    )
    webhook_id: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:copyable": True,
            "ui:loadValue": True,
        },
    )
    signing_secret: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    drive_page_token: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    relay_connected: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    is_production: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    trigger_registered: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    trigger_error: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )


class GoogleDriveOnFolderRemovedConfig(BaseModel):
    """Trigger: fires when a folder is trashed or permanently deleted from Google Drive."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["on_folder_removed"] = Field(
        "on_folder_removed",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Folder Removed",
            "x-keywords": [
                "when folder trashed",
                "on folder deleted",
                "when folder gone",
                "watch deleted folders",
            ],
        },
        title="On Folder Removed",
    )
    watch_parent_folder_id: Optional[str] = Field(
        None,
        title="Watch Folder",
        description="Only trigger for this folder and its descendant subfolders. Leave empty to watch all folders.",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "watch_parent_folder_id",
                "placeholder": "All folders (entire Drive)",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste folder ID",
            },
            "x-resource-type": "google_drive_folder",
        },
    )
    webhook_id: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:copyable": True,
            "ui:loadValue": True,
        },
    )
    signing_secret: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    drive_page_token: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    relay_connected: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    is_production: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    trigger_registered: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    trigger_error: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )


# Discriminated union uses 'operation' field to determine which config type to parse
GoogleDriveConfig = Annotated[
    Union[
        # Trigger operations
        GoogleDriveOnChangeConfig,
        GoogleDriveOnFileChangedConfig,
        GoogleDriveOnFileRemovedConfig,
        GoogleDriveOnFolderChangedConfig,
        GoogleDriveOnFolderRemovedConfig,
        # File operations
        GoogleDriveListConfig,
        GoogleDriveGetConfig,
        GoogleDriveDownloadConfig,
        GoogleDriveCreateFolderConfig,
        GoogleDriveUploadConfig,
        GoogleDriveCopyConfig,
        GoogleDriveMoveConfig,
        GoogleDriveDeleteConfig,
        GoogleDriveUpdateConfig,
        GoogleDriveSearchConfig,
        GoogleDriveExportConfig,
        # Trash operations
        GoogleDriveTrashConfig,
        GoogleDriveRestoreConfig,
        GoogleDriveEmptyTrashConfig,
        # Permission operations
        GoogleDriveShareConfig,
        GoogleDriveUnshareConfig,
        GoogleDriveListPermissionsConfig,
        GoogleDriveGetPermissionConfig,
        GoogleDriveUpdatePermissionConfig,
        # Comment operations
        GoogleDriveCreateCommentConfig,
        GoogleDriveListCommentsConfig,
        GoogleDriveGetCommentConfig,
        GoogleDriveUpdateCommentConfig,
        GoogleDriveDeleteCommentConfig,
        # Reply operations
        GoogleDriveCreateReplyConfig,
        GoogleDriveListRepliesConfig,
        GoogleDriveGetReplyConfig,
        GoogleDriveUpdateReplyConfig,
        GoogleDriveDeleteReplyConfig,
        # Revision operations
        GoogleDriveListRevisionsConfig,
        GoogleDriveGetRevisionConfig,
        GoogleDriveUpdateRevisionConfig,
        GoogleDriveDeleteRevisionConfig,
        # Shared Drive operations
        GoogleDriveListSharedDrivesConfig,
        GoogleDriveGetSharedDriveConfig,
        GoogleDriveCreateSharedDriveConfig,
        GoogleDriveDeleteSharedDriveConfig,
        GoogleDriveHideSharedDriveConfig,
        GoogleDriveUnhideSharedDriveConfig,
        # Account operations
        GoogleDriveGetAboutConfig,
    ],
    Discriminator("operation"),
]


class GoogleDriveNodeConfig(NodeConfig[GoogleDriveConfig, GoogleDriveOAuthCredential]):
    """Full configuration for Google Drive node including credentials"""

    pass


# ============================================================================
# Google Drive Node Implementation
# ============================================================================

# MIME type mapping for Google Workspace exports
EXPORT_MIME_TYPES = {
    # Google Docs exports
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain",
    "html": "text/html",
    "odt": "application/vnd.oasis.opendocument.text",
    "rtf": "application/rtf",
    "epub": "application/epub+zip",
    # Google Sheets exports
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
    "ods": "application/vnd.oasis.opendocument.spreadsheet",
    "tsv": "text/tab-separated-values",
    # Google Slides exports
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "odp": "application/vnd.oasis.opendocument.presentation",
    # Google Drawings exports
    "png": "image/png",
    "jpeg": "image/jpeg",
    "svg": "image/svg+xml",
}

# Google Workspace MIME types that require export
GOOGLE_WORKSPACE_MIME_TYPES = {
    "application/vnd.google-apps.document",
    "application/vnd.google-apps.spreadsheet",
    "application/vnd.google-apps.presentation",
    "application/vnd.google-apps.drawing",
}


class GoogleDriveNode(WatchChannelTriggerMixin, WorkflowNode):
    """
    Google Drive workflow node for file operations.
    """

    _trigger_locks: ClassVar[Dict[tuple[str, str], asyncio.Lock]] = {}
    _trigger_operations: ClassVar[frozenset[str]] = frozenset(
        {
            "on_drive_change",
            "on_file_changed",
            "on_file_removed",
            "on_folder_changed",
            "on_folder_removed",
        }
    )

    edit_examples = [
        "Upload the latest sales report PDF to the Q4 Reports folder",
        "Download all invoice files from archive and save locally with timestamps",
        'Create a new shared folder called "Project Gamma" with team access',
        "Delete old backup files from 2024 and restore important files from trash",
        "Copy the template document to create 5 new project folders with permissions",
        "Share the monthly budget sheet with finance@company.com with editor access",
        "Move all media files from temp to the Assets folder and update comments",
    ]

    @classmethod
    def should_propagate_output(
        cls, output: Dict[str, Any], config: Dict[str, Any]
    ) -> bool:
        operation = (config or {}).get("operation")
        if operation in cls._trigger_operations:
            return bool((output or {}).get("change_count"))
        return True

    @classmethod
    def _get_trigger_lock(
        cls, workflow_id: Optional[str], node_id: Optional[str]
    ) -> asyncio.Lock:
        key = (workflow_id or "", node_id or "")
        lock = cls._trigger_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            cls._trigger_locks[key] = lock
        return lock

    def _get_google_trigger_metadata(
        self,
    ) -> tuple[Optional[int], Optional[str], Optional[str]]:
        payload = (self.node_data or {}).get("_triggerPayload") or {}
        webhook_meta = payload.get("_webhook") or {}
        headers = webhook_meta.get("headers") or {}
        raw_number = headers.get("x-goog-message-number")
        message_number: Optional[int] = None
        if raw_number is not None:
            try:
                message_number = int(raw_number)
            except (TypeError, ValueError):
                logger.warning(
                    f"[GoogleDriveNode] Invalid x-goog-message-number for node {self.node_id}: {raw_number!r}"
                )
        resource_id = headers.get("x-goog-resource-id")
        channel_id = headers.get("x-goog-channel-id")
        return message_number, resource_id, channel_id

    scope_registry = GOOGLE_DRIVE_SCOPES
    connection_evidence = ConnectionEvidence(
        field="file_id",
        noun="files",
    )

    @classmethod
    def get_config_model(cls) -> Optional[Union[Type, type]]:
        """Get Pydantic config model for Google Drive node"""
        return GoogleDriveNodeConfig

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

        Returns a dict with:
            - options: List of option dicts
            - next_page_token: Token for next page (None if no more pages)
        """
        logger.info(
            f"[GoogleDriveNode] load_field_options called: field={field_name}, page_token={page_token}, search={search!r}"
        )

        if field_name in ("folder_id", "watch_parent_folder_id"):
            return await cls._list_folders(credential_data, page_token, search=search)
        elif field_name == "file_id":
            return await cls._list_files(credential_data, page_token, search=search)
        elif field_name == "watch_target_id":
            return await cls._list_files(
                credential_data,
                page_token,
                search=search,
                include_root_option=True,
            )
        elif field_name == "exportable_file_id":
            return await cls._list_exportable_files(
                credential_data, page_token, search=search
            )
        elif field_name == "export_format":
            return cls._get_export_formats(search=search)
        return {"options": [], "next_page_token": None}

    @classmethod
    async def _list_folders(
        cls,
        credential_data: Dict[str, Any],
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List folders accessible to the user with pagination support."""
        access_token = require_credential_token(
            await cls._get_valid_token(credential_data),
            "Connect a Google account to load folders",
        )

        q_clauses = [
            "mimeType='application/vnd.google-apps.folder'",
            "trashed=false",
        ]
        if search:
            escaped = search.replace("\\", "\\\\").replace("'", "\\'")
            q_clauses.append(f"name contains '{escaped}'")

        url = f"{GOOGLE_DRIVE_API_BASE}/files"
        params = {
            "q": " and ".join(q_clauses),
            "fields": "files(id,name,modifiedTime,parents),nextPageToken",
            "orderBy": "modifiedTime desc",
            "pageSize": 50,  # Smaller page size for pagination
        }
        if page_token:
            params["pageToken"] = page_token

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {access_token}"},
                    params=params,
                )

                if response.status_code != 200:
                    raise ValueError(
                        f"Google Drive API error ({response.status_code}): {response.text}"
                    )

                data = response.json()
                files = data.get("files", [])
                next_page_token = data.get("nextPageToken")
                parent_names = await cls._lookup_drive_item_names(
                    access_token,
                    [
                        parent_id
                        for file in files
                        for parent_id in (file.get("parents") or [])[:1]
                        if parent_id
                    ],
                )

                # Only include Root option on first page
                options = []
                if not page_token and cls._should_include_my_drive_option(search):
                    options.append(
                        {
                            "value": "",
                            "label": "My Drive",
                            "metadata": {
                                "mimeType": _FOLDER_MIME,
                                "isRoot": True,
                                "icon": _drive_item_icon(
                                    "My Drive", _FOLDER_MIME, is_root=True
                                ),
                                "emoji": _drive_item_emoji(_FOLDER_MIME),
                            },
                        }
                    )

                for file in files:
                    parent_id = (file.get("parents") or [None])[0]
                    parent_name = parent_names.get(parent_id)
                    label = _drive_item_label(file["name"], parent_name)
                    options.append(
                        {
                            "value": file["id"],
                            "label": label,
                            "metadata": {
                                "icon": _drive_item_icon(file["name"], _FOLDER_MIME),
                                "emoji": _drive_item_emoji(_FOLDER_MIME),
                                "modifiedTime": file.get("modifiedTime"),
                                "parents": file.get("parents", []),
                                "parentName": parent_name,
                                "mimeType": _FOLDER_MIME,
                            },
                        }
                    )

                logger.info(
                    f"[GoogleDriveNode] Found {len(options)} folders, has_more={next_page_token is not None}"
                )
                return {"options": options, "next_page_token": next_page_token}

        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"Failed to load Google Drive folders: {e}") from e

    @classmethod
    async def _list_files(
        cls,
        credential_data: Dict[str, Any],
        page_token: Optional[str] = None,
        search: Optional[str] = None,
        *,
        include_folders: bool = True,
        include_root_option: bool = False,
    ) -> Dict[str, Any]:
        """List files accessible to the user with pagination support."""
        access_token = require_credential_token(
            await cls._get_valid_token(credential_data),
            "Connect a Google account to load files",
        )

        q_clauses = ["trashed=false"]
        if not include_folders:
            q_clauses.append(f"mimeType!='{_FOLDER_MIME}'")
        if search:
            escaped = search.replace("\\", "\\\\").replace("'", "\\'")
            q_clauses.append(f"name contains '{escaped}'")

        url = f"{GOOGLE_DRIVE_API_BASE}/files"
        params = {
            "q": " and ".join(q_clauses),
            "fields": "files(id,name,mimeType,modifiedTime,size,parents),nextPageToken",
            "orderBy": "modifiedTime desc",
            "pageSize": 50,  # Smaller page size for pagination
        }
        if page_token:
            params["pageToken"] = page_token

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {access_token}"},
                    params=params,
                )

                if response.status_code != 200:
                    raise ValueError(
                        f"Google Drive API error ({response.status_code}): {response.text}"
                    )

                data = response.json()
                files = data.get("files", [])
                next_page_token = data.get("nextPageToken")
                parent_names = await cls._lookup_drive_item_names(
                    access_token,
                    [
                        parent_id
                        for file in files
                        for parent_id in (file.get("parents") or [])[:1]
                        if parent_id
                    ],
                )

                options = []
                if (
                    include_root_option
                    and include_folders
                    and not page_token
                    and cls._should_include_my_drive_option(search)
                ):
                    options.append(
                        {
                            "value": "",
                            "label": "My Drive",
                            "metadata": {
                                "mimeType": _FOLDER_MIME,
                                "isRoot": True,
                                "icon": _drive_item_icon(
                                    "My Drive", _FOLDER_MIME, is_root=True
                                ),
                                "emoji": _drive_item_emoji(_FOLDER_MIME),
                            },
                        }
                    )
                for file in files:
                    mime_type = file.get("mimeType", "")
                    parent_id = (file.get("parents") or [None])[0]
                    parent_name = parent_names.get(parent_id)
                    label = _drive_item_label(file["name"], parent_name)
                    options.append(
                        {
                            "value": file["id"],
                            "label": label,
                            "metadata": {
                                "icon": _drive_item_icon(file["name"], mime_type),
                                "emoji": _drive_item_emoji(mime_type),
                                "mimeType": mime_type,
                                "modifiedTime": file.get("modifiedTime"),
                                "size": file.get("size"),
                                "parents": file.get("parents", []),
                                "parentName": parent_name,
                            },
                        }
                    )

                logger.info(
                    f"[GoogleDriveNode] Found {len(options)} files, has_more={next_page_token is not None}"
                )
                return {"options": options, "next_page_token": next_page_token}

        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"Failed to load Google Drive files: {e}") from e

    @classmethod
    def _should_include_my_drive_option(cls, search: Optional[str]) -> bool:
        """Return whether the synthetic My Drive option should appear for this search."""
        if not search:
            return True
        normalized = search.strip().lower()
        if not normalized:
            return True
        return normalized in "my drive" or normalized in "root"

    @classmethod
    async def _lookup_drive_item_names(
        cls,
        access_token: str,
        item_ids: List[str],
    ) -> Dict[str, str]:
        """Resolve item IDs to names so dropdown labels can show parent context."""
        unique_ids = sorted({item_id for item_id in item_ids if item_id})
        if not unique_ids:
            return {}

        async def _fetch_name(
            client: httpx.AsyncClient, item_id: str
        ) -> tuple[str, str]:
            response = await client.get(
                f"{GOOGLE_DRIVE_API_BASE}/files/{item_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"fields": "id,name"},
            )
            if response.status_code != 200:
                logger.warning(
                    f"[GoogleDriveNode] Could not resolve Drive item name for {item_id}: {response.text}"
                )
                return item_id, ""
            data = response.json()
            return item_id, data.get("name", "")

        async with httpx.AsyncClient() as client:
            resolved = await asyncio.gather(
                *[_fetch_name(client, item_id) for item_id in unique_ids]
            )
        return {item_id: name for item_id, name in resolved if name}

    @classmethod
    async def _get_drive_item_metadata(
        cls,
        client: httpx.AsyncClient,
        access_token: str,
        item_id: str,
        metadata_cache: Dict[str, Optional[Dict[str, Any]]],
    ) -> Optional[Dict[str, Any]]:
        if item_id in metadata_cache:
            return metadata_cache[item_id]

        response = await client.get(
            f"{GOOGLE_DRIVE_API_BASE}/files/{item_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"fields": "id,name,mimeType,parents"},
        )
        if response.status_code != 200:
            logger.warning(
                f"[GoogleDriveNode] Could not resolve Drive metadata for {item_id}: {response.text}"
            )
            metadata_cache[item_id] = None
            return None

        metadata = response.json()
        metadata_cache[item_id] = metadata
        return metadata

    @classmethod
    async def _item_is_in_folder_tree(
        cls,
        client: httpx.AsyncClient,
        access_token: str,
        item_id: str,
        folder_id: str,
        metadata_cache: Dict[str, Optional[Dict[str, Any]]],
        membership_cache: Dict[tuple[str, str], bool],
        *,
        initial_parents: Optional[List[str]] = None,
    ) -> bool:
        cache_key = (item_id, folder_id)
        if cache_key in membership_cache:
            return membership_cache[cache_key]

        if item_id == folder_id:
            membership_cache[cache_key] = True
            return True

        parents = initial_parents
        if parents is None:
            metadata = await cls._get_drive_item_metadata(
                client, access_token, item_id, metadata_cache
            )
            parents = list((metadata or {}).get("parents") or [])

        if folder_id in parents:
            membership_cache[cache_key] = True
            return True

        for parent_id in parents:
            if not parent_id:
                continue
            if await cls._item_is_in_folder_tree(
                client,
                access_token,
                parent_id,
                folder_id,
                metadata_cache,
                membership_cache,
            ):
                membership_cache[cache_key] = True
                return True

        membership_cache[cache_key] = False
        return False

    @classmethod
    async def _list_exportable_files(
        cls,
        credential_data: Dict[str, Any],
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List only Google Workspace files that can be exported (Docs, Sheets, Slides, Drawings)."""
        access_token = require_credential_token(
            await cls._get_valid_token(credential_data),
            "Connect a Google account to load files",
        )

        # Google Workspace mimeTypes that support export
        exportable_mimetypes = [
            "application/vnd.google-apps.document",  # Google Docs
            "application/vnd.google-apps.spreadsheet",  # Google Sheets
            "application/vnd.google-apps.presentation",  # Google Slides
            "application/vnd.google-apps.drawing",  # Google Drawings
        ]

        # Build query for exportable files
        mimetype_conditions = " or ".join(
            [f"mimeType='{mt}'" for mt in exportable_mimetypes]
        )
        query = f"({mimetype_conditions}) and trashed=false"
        if search:
            escaped = search.replace("\\", "\\\\").replace("'", "\\'")
            query = f"{query} and name contains '{escaped}'"

        url = f"{GOOGLE_DRIVE_API_BASE}/files"
        params = {
            "q": query,
            "fields": "files(id,name,mimeType,modifiedTime),nextPageToken",
            "orderBy": "modifiedTime desc",
            "pageSize": 50,
        }
        if page_token:
            params["pageToken"] = page_token

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {access_token}"},
                    params=params,
                )

                if response.status_code != 200:
                    raise ValueError(
                        f"Google Drive API error ({response.status_code}): {response.text}"
                    )

                data = response.json()
                files = data.get("files", [])
                next_page_token = data.get("nextPageToken")

                # Map mimeType to friendly names
                options = []
                for file in files:
                    mime_type = file.get("mimeType", "")
                    options.append(
                        {
                            "value": file["id"],
                            "label": file["name"],
                            "metadata": {
                                "icon": _drive_item_icon(file["name"], mime_type),
                                "emoji": _drive_item_emoji(mime_type),
                                "mimeType": mime_type,
                                "modifiedTime": file.get("modifiedTime"),
                            },
                        }
                    )

                logger.info(f"[GoogleDriveNode] Found {len(options)} exportable files")
                return {"options": options, "next_page_token": next_page_token}

        except ValueError:
            raise
        except Exception as e:
            raise ValueError(
                f"Failed to load Google Drive exportable files: {e}"
            ) from e

    @classmethod
    def _get_export_formats(cls, search: Optional[str] = None) -> Dict[str, Any]:
        """Return available export formats as static options."""
        options = [
            {
                "value": "pdf",
                "label": "PDF",
                "metadata": {"description": "Portable Document Format"},
            },
            {
                "value": "docx",
                "label": "Word (DOCX)",
                "metadata": {"description": "Microsoft Word document"},
            },
            {
                "value": "txt",
                "label": "Plain Text",
                "metadata": {"description": "Plain text file"},
            },
            {
                "value": "rtf",
                "label": "Rich Text (RTF)",
                "metadata": {"description": "Rich Text Format"},
            },
            {
                "value": "odt",
                "label": "OpenDocument Text",
                "metadata": {"description": "OpenDocument text"},
            },
            {
                "value": "html",
                "label": "HTML",
                "metadata": {"description": "Web page format"},
            },
            {
                "value": "xlsx",
                "label": "Excel (XLSX)",
                "metadata": {"description": "Microsoft Excel spreadsheet"},
            },
            {
                "value": "csv",
                "label": "CSV",
                "metadata": {"description": "Comma-separated values"},
            },
            {
                "value": "ods",
                "label": "OpenDocument Spreadsheet",
                "metadata": {"description": "OpenDocument spreadsheet"},
            },
            {
                "value": "pptx",
                "label": "PowerPoint (PPTX)",
                "metadata": {"description": "Microsoft PowerPoint"},
            },
            {
                "value": "odp",
                "label": "OpenDocument Presentation",
                "metadata": {"description": "OpenDocument presentation"},
            },
        ]
        return {"options": options, "next_page_token": None}

    @classmethod
    async def _get_valid_token(cls, credential_data: Dict[str, Any]) -> Optional[str]:
        """Get a valid access token, refreshing if needed."""
        access_token = credential_data.get("access_token")
        if not access_token:
            logger.error("[GoogleDriveNode] No access token in credential data")
            return None

        return access_token

    # ========================================================================
    # Watch-channel trigger (on_drive_change)
    # ========================================================================

    async def _trigger_on_drive_change(self, config, credentials) -> Dict[str, Any]:
        """Fetch Drive changes since the stored cursor (runs when the watch
        channel wakes the node, or on a manual editor run)."""
        async with self._get_trigger_lock(self.workflow_id, self.node_id):
            state = await self._load_node_state()
            cursor = state.get("page_token") or getattr(
                config, "drive_page_token", None
            )
            if not cursor:
                return {
                    "message": (
                        "This trigger fires when files change in Google Drive. "
                        "Save the workflow to activate it."
                    ),
                    "changes": [],
                    "change_count": 0,
                }

            (
                message_number,
                resource_id,
                channel_id,
            ) = self._get_google_trigger_metadata()
            last_message_number = state.get("last_google_message_number")
            try:
                last_message_number = (
                    int(last_message_number)
                    if last_message_number is not None
                    else None
                )
            except (TypeError, ValueError):
                last_message_number = None
            last_channel_id = state.get("last_google_channel_id")
            # Dedup within a CHANNEL only: x-goog-message-number restarts per
            # channel, so a re-registered channel's low numbers must not be
            # judged "stale" against the previous channel's high-water mark.
            if (
                message_number is not None
                and channel_id
                and last_channel_id == channel_id
                and last_message_number is not None
                and message_number <= last_message_number
            ):
                logger.info(
                    f"[GoogleDriveNode] Skipping duplicate/stale Drive wake-up for node {self.node_id}: "
                    f"message_number={message_number}, last_message_number={last_message_number}"
                )
                return {
                    "changes": [],
                    "change_count": 0,
                    "deduped": True,
                }

            if not credentials:
                raise ValueError(
                    "[GoogleDriveNode] Google Drive credentials are required. "
                    "Please connect a Google account in the node's credentials tab."
                )


            cred_dict = credentials.model_dump()
            credential_id = (self.node_data or {}).get("credential_id")
            access_token = await ensure_fresh_google_token(
                None,
                credential_id,
                self.user_id,
                cred_dict,
            )

            changes: List[Dict[str, Any]] = []
            page_token = cursor
            new_cursor = cursor
            while page_token:
                result = await drive_list_changes(access_token, page_token)
                changes.extend(result.get("changes", []))
                if result.get("nextPageToken"):
                    page_token = result["nextPageToken"]
                else:
                    new_cursor = result.get("newStartPageToken", page_token)
                    break

            # Filter changes based on the selected trigger operation.
            operation = getattr(config, "operation", "on_drive_change")
            _FOLDER_MIME = "application/vnd.google-apps.folder"
            if operation == "on_file_changed":
                changes = [
                    c
                    for c in changes
                    if not c.get("removed")
                    and not (c.get("file") or {}).get("trashed", False)
                    and (c.get("file") or {}).get("mimeType") != _FOLDER_MIME
                ]
            elif operation == "on_file_removed":
                changes = [
                    c
                    for c in changes
                    if (
                        c.get("removed")
                        and (
                            (c.get("file") or {}).get("mimeType") != _FOLDER_MIME
                            or not c.get("file")
                        )
                    )
                    or (
                        (c.get("file") or {}).get("trashed", False)
                        and (c.get("file") or {}).get("mimeType") != _FOLDER_MIME
                    )
                ]
            elif operation == "on_folder_changed":
                changes = [
                    c
                    for c in changes
                    if (c.get("file") or {}).get("mimeType") == _FOLDER_MIME
                    and not c.get("removed")
                    and not (c.get("file") or {}).get("trashed", False)
                ]
            elif operation == "on_folder_removed":
                changes = [
                    c
                    for c in changes
                    if (
                        # Trashed folder — mimeType visible in file metadata
                        (c.get("file") or {}).get("mimeType") == _FOLDER_MIME
                        and (
                            c.get("removed")
                            or (c.get("file") or {}).get("trashed", False)
                        )
                    )
                    or (
                        # Permanently deleted item — no file metadata, type unknowable; include
                        c.get("removed")
                        and not c.get("file")
                    )
                ]

            watch_parent = getattr(config, "watch_parent_folder_id", None) or ""
            watch_target = getattr(config, "watch_target_id", None) or ""
            scope = watch_target or watch_parent
            if scope:
                metadata_cache: Dict[str, Optional[Dict[str, Any]]] = {}
                membership_cache: Dict[tuple[str, str], bool] = {}
                async with httpx.AsyncClient(timeout=30.0) as client:
                    exact_file_target = ""
                    folder_target = ""
                    if watch_target:
                        target_meta = await self._get_drive_item_metadata(
                            client, access_token, watch_target, metadata_cache
                        )
                        if target_meta is None:
                            # Metadata fetch failed — default to folder scope so changes
                            # are not silently dropped when the API is temporarily unavailable.
                            logger.warning(
                                f"[GoogleDriveNode] Could not resolve metadata for watch_target_id={watch_target!r}; "
                                f"treating as folder scope."
                            )
                            folder_target = watch_target
                        elif target_meta.get("mimeType") == _FOLDER_MIME:
                            folder_target = watch_target
                        else:
                            exact_file_target = watch_target
                    else:
                        folder_target = watch_parent

                    if exact_file_target:
                        changes = [
                            c for c in changes if c.get("fileId") == exact_file_target
                        ]
                    elif folder_target:
                        scoped: List[Dict[str, Any]] = []
                        for c in changes:
                            file_id = c.get("fileId") or ""
                            file_meta = c.get("file") or {}
                            parents = list(file_meta.get("parents") or [])
                            if not file_id:
                                continue
                            if not file_meta and c.get("removed"):
                                if file_id == folder_target and operation in (
                                    "on_folder_removed",
                                ):
                                    scoped.append(c)
                                continue
                            if await self._item_is_in_folder_tree(
                                client,
                                access_token,
                                file_id,
                                folder_target,
                                metadata_cache,
                                membership_cache,
                                initial_parents=parents,
                            ):
                                scoped.append(c)
                        changes = scoped

            new_state = dict(state)
            new_state["page_token"] = new_cursor
            if message_number is not None:
                new_state["last_google_message_number"] = message_number
            if resource_id:
                new_state["last_google_resource_id"] = resource_id
            if channel_id:
                new_state["last_google_channel_id"] = channel_id
            await self._save_node_state(new_state)
            return {"changes": changes, "change_count": len(changes)}

    @classmethod
    async def _register_watch_channel(
        cls,
        *,
        pool,
        user_id,
        workflow_id,
        node_id,
        webhook_id,
        webhook_url,
        credential,
        credential_id,
        config,
    ) -> Dict[str, Any]:
        access_token = await ensure_fresh_google_token(
            pool, credential_id, user_id, credential
        )

        # Stop a stale channel from a previous registration so re-saving the
        # workflow doesn't leak channels or cause duplicate notifications.
        existing = await get_watch_channel(pool, workflow_id, node_id)
        if existing and existing.get("channel_id") and existing.get("resource_id"):
            try:
                await drive_stop_channel(
                    access_token, existing["channel_id"], existing["resource_id"]
                )
            except Exception as e:
                logger.warning(
                    f"[GoogleDriveNode] Could not stop stale watch channel: {e}"
                )

        channel_id = str(uuid4())
        channel_token = (config or {}).get("signing_secret") or secrets.token_hex(32)
        start_page_token = await drive_get_start_page_token(access_token)
        watch = await drive_watch_changes(
            access_token, channel_id, webhook_url, channel_token, start_page_token
        )
        await save_watch_channel(
            pool,
            webhook_id=webhook_id,
            user_id=user_id,
            workflow_id=workflow_id,
            node_id=node_id,
            provider="google_drive",
            credential_id=credential_id,
            channel_id=channel_id,
            resource_id=watch.get("resourceId"),
            channel_token=channel_token,
            expires_at=_ms_to_datetime(watch.get("expiration")),
        )
        return {"signing_secret": channel_token, "drive_page_token": start_page_token}

    @classmethod
    async def _stop_watch_channel(
        cls, *, pool, workflow_id, node_id, credential, config, channel_row
    ) -> None:
        if not credential:
            return
        cred_id = channel_row.get("credential_id")
        row_user = channel_row.get("user_id")
        access_token = await ensure_fresh_google_token(
            pool,
            str(cred_id) if cred_id else None,
            str(row_user) if row_user else None,
            credential,
        )
        if channel_row.get("channel_id") and channel_row.get("resource_id"):
            await drive_stop_channel(
                access_token, channel_row["channel_id"], channel_row["resource_id"]
            )

    @classmethod
    async def renew_watch_channel(cls, pool, channel_row: Dict[str, Any]) -> None:
        """Re-subscribe an expiring Drive watch channel (called by the cron)."""
        from utils.credential_loader import load_credential
        from utils.webhook_tunnel import get_webhook_url

        user_id = str(channel_row["user_id"])
        cred_id = channel_row.get("credential_id")
        credential_id = str(cred_id) if cred_id else None
        credential = await load_credential(pool, user_id, credential_id)
        if not credential:
            logger.warning(
                f"[GoogleDriveNode] Cannot renew channel {channel_row.get('id')}: "
                f"credential unavailable"
            )
            return

        access_token = await ensure_fresh_google_token(
            pool, credential_id, user_id, credential
        )
        webhook_url = get_webhook_url(str(channel_row["webhook_id"]))
        new_channel_id = str(uuid4())
        start_page_token = await drive_get_start_page_token(access_token)
        watch = await drive_watch_changes(
            access_token,
            new_channel_id,
            webhook_url,
            channel_row["channel_token"],
            start_page_token,
        )

        if channel_row.get("channel_id") and channel_row.get("resource_id"):
            try:
                await drive_stop_channel(
                    access_token,
                    channel_row["channel_id"],
                    channel_row["resource_id"],
                )
            except Exception as e:
                logger.warning(f"[GoogleDriveNode] Could not stop old channel: {e}")

        await update_channel_subscription(
            pool,
            channel_row["id"],
            channel_id=new_channel_id,
            resource_id=watch.get("resourceId"),
            expires_at=_ms_to_datetime(watch.get("expiration")),
        )

        # Advance the node's state cursor to match the new watch channel's start
        # position so the trigger doesn't re-process already-seen changes on its
        # first fire after renewal.
        workflow_id = channel_row.get("workflow_id")
        node_id = channel_row.get("node_id")
        if workflow_id and node_id:
            import uuid as _uuid

            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO workflow_node_state (workflow_id, node_id, state, updated_at)
                    VALUES ($1, $2, jsonb_build_object('page_token', $3::text), NOW())
                    ON CONFLICT (workflow_id, node_id) DO UPDATE
                    SET state = jsonb_set(
                        COALESCE(workflow_node_state.state, '{}'::jsonb),
                        '{page_token}',
                        to_jsonb($3::text),
                        true
                    ),
                    updated_at = NOW()
                    """,
                    _uuid.UUID(str(workflow_id)),
                    str(node_id),
                    start_page_token,
                )

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        """Drive notifications are wake-up signals — run execute() to fetch."""
        return None

    @classmethod
    def verify_webhook_signature(
        cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]
    ) -> bool:
        """Verify the ``X-Goog-Channel-Token`` echoed by Google."""
        token = (config or {}).get("signing_secret")
        if not token:
            return False
        return hmac.compare_digest(token, headers.get("x-goog-channel-token", ""))

    @classmethod
    def handle_webhook_handshake(cls, body: bytes, headers: Dict[str, str], config=None):
        """Acknowledge Google's initial ``sync`` message without firing a run."""
        if headers.get("x-goog-resource-state") == "sync":
            return {}
        return None

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute Google Drive operation."""
        logger.info(f"[GoogleDriveNode] Executing node {self.node_id}")

        node_config = self.config
        if not node_config:
            raise ValueError(
                f"[GoogleDriveNode] Configuration is required for node {self.node_id}"
            )

        if not isinstance(node_config, GoogleDriveNodeConfig):
            raise ValueError(
                f"[GoogleDriveNode] Invalid config type: {type(node_config)}"
            )

        config = node_config.config
        credentials = node_config.credentials

        # Trigger operations — fetch changes since the stored cursor
        if isinstance(
            config,
            (
                GoogleDriveOnChangeConfig,
                GoogleDriveOnFileChangedConfig,
                GoogleDriveOnFileRemovedConfig,
                GoogleDriveOnFolderChangedConfig,
                GoogleDriveOnFolderRemovedConfig,
            ),
        ):
            return await self._trigger_on_drive_change(config, credentials)

        if not credentials:
            raise ValueError(
                "[GoogleDriveNode] Google Drive credentials are required. "
                "Please connect a Google account in the node's credentials tab."
            )

        access_token = await self._ensure_fresh_token(credentials)

        # Execute operation based on config type
        if isinstance(config, GoogleDriveListConfig):
            output = await self._list_files_op(config, access_token)
        elif isinstance(config, GoogleDriveGetConfig):
            output = await self._get_file(config, access_token)
        elif isinstance(config, GoogleDriveDownloadConfig):
            output = await self._download_file(config, access_token)
        elif isinstance(config, GoogleDriveCreateFolderConfig):
            output = await self._create_folder(config, access_token)
        elif isinstance(config, GoogleDriveUploadConfig):
            output = await self._upload_file(config, access_token, inputs)
        elif isinstance(config, GoogleDriveCopyConfig):
            output = await self._copy_file(config, access_token)
        elif isinstance(config, GoogleDriveMoveConfig):
            output = await self._move_file(config, access_token)
        elif isinstance(config, GoogleDriveDeleteConfig):
            output = await self._delete_file(config, access_token)
        elif isinstance(config, GoogleDriveShareConfig):
            output = await self._share_file(config, access_token)
        elif isinstance(config, GoogleDriveExportConfig):
            output = await self._export_file(config, access_token)
        elif isinstance(config, GoogleDriveUpdateConfig):
            output = await self._update_file(config, access_token)
        elif isinstance(config, GoogleDriveTrashConfig):
            output = await self._trash_file(config, access_token)
        elif isinstance(config, GoogleDriveRestoreConfig):
            output = await self._restore_file(config, access_token)
        elif isinstance(config, GoogleDriveEmptyTrashConfig):
            output = await self._empty_trash(config, access_token)
        elif isinstance(config, GoogleDriveUnshareConfig):
            output = await self._unshare_file(config, access_token)
        elif isinstance(config, GoogleDriveListPermissionsConfig):
            output = await self._list_permissions(config, access_token)
        elif isinstance(config, GoogleDriveSearchConfig):
            output = await self._search_files(config, access_token)
        elif isinstance(config, GoogleDriveCreateCommentConfig):
            output = await self._create_comment(config, access_token)
        elif isinstance(config, GoogleDriveListCommentsConfig):
            output = await self._list_comments(config, access_token)
        elif isinstance(config, GoogleDriveDeleteCommentConfig):
            output = await self._delete_comment(config, access_token)
        elif isinstance(config, GoogleDriveGetCommentConfig):
            output = await self._get_comment(config, access_token)
        elif isinstance(config, GoogleDriveUpdateCommentConfig):
            output = await self._update_comment(config, access_token)
        elif isinstance(config, GoogleDriveCreateReplyConfig):
            output = await self._create_reply(config, access_token)
        elif isinstance(config, GoogleDriveListRepliesConfig):
            output = await self._list_replies(config, access_token)
        elif isinstance(config, GoogleDriveDeleteReplyConfig):
            output = await self._delete_reply(config, access_token)
        elif isinstance(config, GoogleDriveListRevisionsConfig):
            output = await self._list_revisions(config, access_token)
        elif isinstance(config, GoogleDriveGetRevisionConfig):
            output = await self._get_revision(config, access_token)
        elif isinstance(config, GoogleDriveDeleteRevisionConfig):
            output = await self._delete_revision(config, access_token)
        elif isinstance(config, GoogleDriveGetAboutConfig):
            output = await self._get_about(access_token)
        elif isinstance(config, GoogleDriveGetPermissionConfig):
            output = await self._get_permission(config, access_token)
        elif isinstance(config, GoogleDriveUpdatePermissionConfig):
            output = await self._update_permission(config, access_token)
        elif isinstance(config, GoogleDriveGetReplyConfig):
            output = await self._get_reply(config, access_token)
        elif isinstance(config, GoogleDriveUpdateReplyConfig):
            output = await self._update_reply(config, access_token)
        elif isinstance(config, GoogleDriveUpdateRevisionConfig):
            output = await self._update_revision(config, access_token)
        elif isinstance(config, GoogleDriveListSharedDrivesConfig):
            output = await self._list_shared_drives(config, access_token)
        elif isinstance(config, GoogleDriveGetSharedDriveConfig):
            output = await self._get_shared_drive(config, access_token)
        elif isinstance(config, GoogleDriveCreateSharedDriveConfig):
            output = await self._create_shared_drive(config, access_token)
        elif isinstance(config, GoogleDriveDeleteSharedDriveConfig):
            output = await self._delete_shared_drive(config, access_token)
        elif isinstance(config, GoogleDriveHideSharedDriveConfig):
            output = await self._hide_shared_drive(config, access_token)
        elif isinstance(config, GoogleDriveUnhideSharedDriveConfig):
            output = await self._unhide_shared_drive(config, access_token)
        else:
            raise ValueError(f"Unknown operation: {type(config)}")

        await self.emit(output)
        return output

    @classmethod
    async def freshen_credential(
        cls, credential_data, *, pool=None, user_id=None, credential_id=None
    ):
        """Refresh an expiring OAuth token at credential load (dropdowns,
        trigger registration). No-op for non-rotating credentials (API keys /
        offline / non-expiring tokens)."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.google_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data,
            pool=pool,
            user_id=user_id,
            credential_id=credential_id,
            refresh=refresh_access_token,
            provider="google",
        )

    async def _ensure_fresh_token(self, credentials: GoogleDriveOAuthCredential) -> str:
        """Return a valid Google Drive access token, refreshing + persisting if expired."""
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.google_oauth import refresh_access_token

        cred_dict = credentials.model_dump()
        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=cred_dict,
            refresh=refresh_access_token,
            provider="google",
        )
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        if cred_dict.get("refresh_token"):
            credentials.refresh_token = cred_dict["refresh_token"]
        return token

    async def _list_files_op(
        self, config: GoogleDriveListConfig, access_token: str
    ) -> Dict[str, Any]:
        """List files in Google Drive."""
        logger.info(
            f"[GoogleDriveNode] Listing files in folder: {config.folder_id or 'root'}"
        )

        # Build query
        query_parts = []
        if config.folder_id:
            query_parts.append(f"'{config.folder_id}' in parents")
        if not config.include_trashed:
            query_parts.append("trashed=false")
        if config.query:
            query_parts.append(config.query)

        params = {
            "fields": "files(id,name,mimeType,modifiedTime,size,webViewLink,createdTime,owners,parents)",
            "orderBy": "modifiedTime desc",
            "pageSize": config.page_size,
        }
        if query_parts:
            params["q"] = " and ".join(query_parts)

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{GOOGLE_DRIVE_API_BASE}/files",
                headers={"Authorization": f"Bearer {access_token}"},
                params=params,
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Drive API error: {error_msg}")

            data = response.json()
            files = data.get("files", [])

            return {
                "type": "google_drive",
                "operation": "list_files",
                "folder_id": config.folder_id,
                "file_count": len(files),
                "files": files,
                "timestamp": time.time(),
                "status": "success",
            }

    async def _get_file(
        self, config: GoogleDriveGetConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get file metadata."""
        logger.info(f"[GoogleDriveNode] Getting file: {config.file_id}")

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{GOOGLE_DRIVE_API_BASE}/files/{config.file_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                params={
                    "fields": "id,name,mimeType,modifiedTime,size,webViewLink,createdTime,owners,parents,description,starred,trashed"
                },
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Drive API error: {error_msg}")

            file_data = response.json()

            return {
                "type": "google_drive",
                "operation": "get_file_metadata",
                "file_id": config.file_id,
                "file": file_data,
                "timestamp": time.time(),
                "status": "success",
            }

    async def _download_file(
        self, config: GoogleDriveDownloadConfig, access_token: str
    ) -> Dict[str, Any]:
        """Download file content."""
        logger.info(f"[GoogleDriveNode] Downloading file: {config.file_id}")

        async with httpx.AsyncClient() as client:
            # First get file metadata to check MIME type
            metadata_response = await client.get(
                f"{GOOGLE_DRIVE_API_BASE}/files/{config.file_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"fields": "id,name,mimeType,size"},
            )

            if metadata_response.status_code != 200:
                error_data = metadata_response.json()
                error_msg = error_data.get("error", {}).get(
                    "message", metadata_response.text
                )
                raise ValueError(f"Google Drive API error: {error_msg}")

            metadata = metadata_response.json()
            mime_type = metadata.get("mimeType", "")

            # Determine if we need to export (Google Workspace files)
            if mime_type in GOOGLE_WORKSPACE_MIME_TYPES:
                # Export Google Workspace file
                export_format = config.export_format or "pdf"
                export_mime = EXPORT_MIME_TYPES.get(export_format.lower())
                if not export_mime:
                    raise ValueError(f"Unsupported export format: {export_format}")

                response = await client.get(
                    f"{GOOGLE_DRIVE_API_BASE}/files/{config.file_id}/export",
                    headers={"Authorization": f"Bearer {access_token}"},
                    params={"mimeType": export_mime},
                )
            else:
                # Download binary file
                response = await client.get(
                    f"{GOOGLE_DRIVE_API_BASE}/files/{config.file_id}",
                    headers={"Authorization": f"Bearer {access_token}"},
                    params={"alt": "media"},
                )

            if response.status_code != 200:
                raise ValueError(f"Download failed with status {response.status_code}")

            content = response.content
            content_type = response.headers.get("content-type", "")

            # Try to decode as text, otherwise return base64
            try:
                if (
                    "text" in content_type
                    or "json" in content_type
                    or "xml" in content_type
                ):
                    text_content = content.decode("utf-8")
                    return {
                        "type": "google_drive",
                        "operation": "download_file",
                        "file_id": config.file_id,
                        "file_name": metadata.get("name"),
                        "content": text_content,
                        "content_type": content_type,
                        "encoding": "text",
                        "size": len(content),
                        "timestamp": time.time(),
                        "status": "success",
                    }
            except UnicodeDecodeError:
                pass

            # Binary content: hand the bytes to the resolver as a marker.
            from nodes.core.binary_output import BinaryOutput

            file_name = metadata.get("name") or "download"
            return {
                "type": "google_drive",
                "operation": "download_file",
                "file_id": config.file_id,
                "file_name": file_name,
                "content": BinaryOutput(
                    data=content,
                    content_type=content_type or "application/octet-stream",
                    filename=file_name,
                ),
                "content_type": content_type,
                "timestamp": time.time(),
                "status": "success",
            }

    async def _create_folder(
        self, config: GoogleDriveCreateFolderConfig, access_token: str
    ) -> Dict[str, Any]:
        """Create a new folder."""
        logger.info(f"[GoogleDriveNode] Creating folder: {config.folder_name}")

        metadata = {
            "name": config.folder_name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        if config.parent_folder_id:
            metadata["parents"] = [config.parent_folder_id]

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{GOOGLE_DRIVE_API_BASE}/files",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=metadata,
            )

            if response.status_code not in (200, 201):
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Drive API error: {error_msg}")

            folder_data = response.json()

            return {
                "type": "google_drive",
                "operation": "create_folder",
                "folder_id": folder_data.get("id"),
                "folder_name": folder_data.get("name"),
                "folder": folder_data,
                "timestamp": time.time(),
                "status": "success",
            }

    async def _upload_file(
        self, config: GoogleDriveUploadConfig, access_token: str, inputs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Upload a file to Google Drive."""
        logger.info(f"[GoogleDriveNode] Uploading file: {config.file_name}")

        # Get content
        content = config.content
        resolved_mime = None

        # A media reference (resource_id from an upstream download/upload, a URL,
        # or a data: URI) resolves to the file's bytes. Plain text / base64
        # content keeps the existing path so text files still work.
        from nodes.core.media_resolver import looks_like_media_ref, resolve_media_input

        if looks_like_media_ref(content):
            resolved = await resolve_media_input(content)
            content_bytes = resolved.data
            resolved_mime = resolved.mime_type
            logger.info(
                f"[GoogleDriveNode] Resolved media input to {len(content_bytes)} bytes ({resolved_mime})"
            )
        else:
            # Auto-detect base64 (e.g. legacy HTTP binary downloads) vs plain text.
            is_base64 = config.is_base64
            if not is_base64 and isinstance(content, str) and len(content) > 1000:
                try:
                    base64.b64decode(content, validate=True)
                    is_base64 = True
                    logger.info(
                        f"[GoogleDriveNode] Auto-detected base64-encoded content ({len(content)} chars)"
                    )
                except Exception:
                    pass
            if is_base64:
                try:
                    content_bytes = base64.b64decode(content)
                except Exception as e:
                    raise ValueError(f"Invalid base64 content: {e}")
            else:
                content_bytes = content.encode("utf-8")

        # Determine MIME type
        mime_type = config.mime_type or resolved_mime or self._guess_mime_type(config.file_name)

        # Prepare metadata
        metadata = {"name": config.file_name}
        if config.parent_folder_id:
            metadata["parents"] = [config.parent_folder_id]

        # Use multipart upload
        # Set longer timeout for large file uploads (e.g., videos)
        timeout = httpx.Timeout(300.0, connect=60.0)  # 5 min total, 1 min connect

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                # Create the file with metadata
                boundary = "===============multipart_boundary==============="

                body_parts = [
                    f"--{boundary}",
                    "Content-Type: application/json; charset=UTF-8",
                    "",
                    str(metadata).replace("'", '"'),
                    f"--{boundary}",
                    f"Content-Type: {mime_type}",
                    "",
                ]
                body_prefix = "\r\n".join(body_parts) + "\r\n"
                body_suffix = f"\r\n--{boundary}--"

                full_body = (
                    body_prefix.encode("utf-8")
                    + content_bytes
                    + body_suffix.encode("utf-8")
                )

                logger.info(
                    f"[GoogleDriveNode] Uploading {len(content_bytes)} bytes to Google Drive..."
                )
                response = await client.post(
                    f"{GOOGLE_UPLOAD_API_BASE}/files",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": f"multipart/related; boundary={boundary}",
                    },
                    params={"uploadType": "multipart"},
                    content=full_body,
                )
                logger.info(
                    f"[GoogleDriveNode] Upload complete, status: {response.status_code}"
                )

                if response.status_code not in (200, 201):
                    try:
                        error_data = response.json()
                        error_msg = error_data.get("error", {}).get(
                            "message", response.text
                        )
                    except Exception:
                        error_msg = response.text
                    logger.error(
                        f"[GoogleDriveNode] Google Drive API error: {error_msg}"
                    )
                    raise ValueError(f"Google Drive API error: {error_msg}")

                file_data = response.json()

                return {
                    "type": "google_drive",
                    "operation": "upload_file",
                    "file_id": file_data.get("id"),
                    "file_name": file_data.get("name"),
                    "mime_type": file_data.get("mimeType"),
                    "size": len(content_bytes),
                    "file": file_data,
                    "timestamp": time.time(),
                    "status": "success",
                }
        except httpx.TimeoutException as e:
            logger.error(
                f"[GoogleDriveNode] Upload timed out after {timeout.timeout}s: {e}"
            )
            raise ValueError(
                f"Upload timed out. File size: {len(content_bytes)} bytes. Try increasing timeout or using smaller files."
            )
        except httpx.RequestError as e:
            logger.error(f"[GoogleDriveNode] Network error during upload: {e}")
            raise ValueError(f"Network error during upload: {str(e)}")
        except Exception as e:
            logger.error(
                f"[GoogleDriveNode] Unexpected error during upload: {type(e).__name__}: {e}"
            )
            raise

    def _guess_mime_type(self, filename: str) -> str:
        """Guess MIME type from filename extension."""
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        mime_map = {
            "txt": "text/plain",
            "html": "text/html",
            "css": "text/css",
            "js": "application/javascript",
            "json": "application/json",
            "xml": "application/xml",
            "csv": "text/csv",
            "pdf": "application/pdf",
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "gif": "image/gif",
            "svg": "image/svg+xml",
            "zip": "application/zip",
            "doc": "application/msword",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "xls": "application/vnd.ms-excel",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "ppt": "application/vnd.ms-powerpoint",
            "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "mp3": "audio/mpeg",
            "mp4": "video/mp4",
            "wav": "audio/wav",
        }
        return mime_map.get(ext, "application/octet-stream")

    async def _copy_file(
        self, config: GoogleDriveCopyConfig, access_token: str
    ) -> Dict[str, Any]:
        """Copy a file."""
        logger.info(f"[GoogleDriveNode] Copying file: {config.file_id}")

        metadata = {}
        if config.new_name:
            metadata["name"] = config.new_name
        if config.destination_folder_id:
            metadata["parents"] = [config.destination_folder_id]

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{GOOGLE_DRIVE_API_BASE}/files/{config.file_id}/copy",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=metadata if metadata else None,
            )

            if response.status_code not in (200, 201):
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Drive API error: {error_msg}")

            file_data = response.json()

            return {
                "type": "google_drive",
                "operation": "copy_file",
                "original_file_id": config.file_id,
                "new_file_id": file_data.get("id"),
                "new_file_name": file_data.get("name"),
                "file": file_data,
                "timestamp": time.time(),
                "status": "success",
            }

    async def _move_file(
        self, config: GoogleDriveMoveConfig, access_token: str
    ) -> Dict[str, Any]:
        """Move a file to another folder."""
        logger.info(f"[GoogleDriveNode] Moving file: {config.file_id}")

        async with httpx.AsyncClient() as client:
            # First get current parents
            metadata_response = await client.get(
                f"{GOOGLE_DRIVE_API_BASE}/files/{config.file_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"fields": "id,name,parents"},
            )

            if metadata_response.status_code != 200:
                error_data = metadata_response.json()
                error_msg = error_data.get("error", {}).get(
                    "message", metadata_response.text
                )
                raise ValueError(f"Google Drive API error: {error_msg}")

            metadata = metadata_response.json()
            current_parents = metadata.get("parents", [])

            # Move by updating parents
            response = await client.patch(
                f"{GOOGLE_DRIVE_API_BASE}/files/{config.file_id}",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                params={
                    "addParents": config.destination_folder_id,
                    "removeParents": ",".join(current_parents),
                    "fields": "id,name,parents",
                },
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Drive API error: {error_msg}")

            file_data = response.json()

            return {
                "type": "google_drive",
                "operation": "move_file",
                "file_id": config.file_id,
                "file_name": file_data.get("name"),
                "from_folders": current_parents,
                "to_folder": config.destination_folder_id,
                "file": file_data,
                "timestamp": time.time(),
                "status": "success",
            }

    async def _delete_file(
        self, config: GoogleDriveDeleteConfig, access_token: str
    ) -> Dict[str, Any]:
        """Delete a file permanently."""
        logger.info(f"[GoogleDriveNode] Deleting file: {config.file_id}")

        async with httpx.AsyncClient() as client:
            # First get file name for response
            metadata_response = await client.get(
                f"{GOOGLE_DRIVE_API_BASE}/files/{config.file_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"fields": "id,name"},
            )

            file_name = "Unknown"
            if metadata_response.status_code == 200:
                file_name = metadata_response.json().get("name", "Unknown")

            # Delete the file
            response = await client.delete(
                f"{GOOGLE_DRIVE_API_BASE}/files/{config.file_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code not in (200, 204):
                error_data = response.json() if response.content else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Drive API error: {error_msg}")

            return {
                "type": "google_drive",
                "operation": "delete_file",
                "file_id": config.file_id,
                "file_name": file_name,
                "timestamp": time.time(),
                "status": "success",
            }

    async def _share_file(
        self, config: GoogleDriveShareConfig, access_token: str
    ) -> Dict[str, Any]:
        """Share a file with others."""
        logger.info(f"[GoogleDriveNode] Sharing file: {config.file_id}")

        permission = {"type": config.share_type, "role": config.role}

        if config.share_type in ("user", "group") and config.email:
            permission["emailAddress"] = config.email

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{GOOGLE_DRIVE_API_BASE}/files/{config.file_id}/permissions",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                params={"sendNotificationEmail": str(config.send_notification).lower()},
                json=permission,
            )

            if response.status_code not in (200, 201):
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Drive API error: {error_msg}")

            permission_data = response.json()

            # Get web view link
            file_response = await client.get(
                f"{GOOGLE_DRIVE_API_BASE}/files/{config.file_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"fields": "id,name,webViewLink"},
            )

            web_link = None
            file_name = None
            if file_response.status_code == 200:
                file_data = file_response.json()
                web_link = file_data.get("webViewLink")
                file_name = file_data.get("name")

            return {
                "type": "google_drive",
                "operation": "share_file",
                "file_id": config.file_id,
                "file_name": file_name,
                "share_type": config.share_type,
                "role": config.role,
                "email": config.email,
                "web_link": web_link,
                "permission": permission_data,
                "timestamp": time.time(),
                "status": "success",
            }

    # =========================================================================
    # New Operations
    # =========================================================================

    async def _export_file(
        self, config: GoogleDriveExportConfig, access_token: str
    ) -> Dict[str, Any]:
        """Export a Google Workspace document to another format."""
        logger.info(
            f"[GoogleDriveNode] Exporting file: {config.file_id} as {config.export_format}"
        )

        # Map export format to MIME type
        format_mime_map = {
            "pdf": "application/pdf",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "txt": "text/plain",
            "rtf": "application/rtf",
            "odt": "application/vnd.oasis.opendocument.text",
            "html": "text/html",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "csv": "text/csv",
            "ods": "application/vnd.oasis.opendocument.spreadsheet",
            "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "odp": "application/vnd.oasis.opendocument.presentation",
        }

        mime_type = format_mime_map.get(config.export_format)
        if not mime_type:
            raise ValueError(f"Unsupported export format: {config.export_format}")

        async with httpx.AsyncClient() as client:
            # Get file metadata first
            meta_response = await client.get(
                f"{GOOGLE_DRIVE_API_BASE}/files/{config.file_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"fields": "id,name,mimeType"},
            )

            if meta_response.status_code != 200:
                raise ValueError(f"Failed to get file metadata: {meta_response.text}")

            metadata = meta_response.json()

            # Export the file
            response = await client.get(
                f"{GOOGLE_DRIVE_API_BASE}/files/{config.file_id}/export",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"mimeType": mime_type},
            )

            if response.status_code != 200:
                error_data = (
                    response.json()
                    if response.headers.get("content-type", "").startswith(
                        "application/json"
                    )
                    else {}
                )
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Export failed: {error_msg}")

            content = response.content

            # Exported bytes are always binary: hand them to the resolver.
            from nodes.core.binary_output import BinaryOutput

            base_name = metadata.get("name") or config.file_id
            export_filename = f"{base_name}.{config.export_format}"
            return {
                "type": "google_drive",
                "operation": "export_google_workspace_file",
                "file_id": config.file_id,
                "file_name": metadata.get("name"),
                "original_mime_type": metadata.get("mimeType"),
                "export_format": config.export_format,
                "export_mime_type": mime_type,
                "content": BinaryOutput(
                    data=content,
                    content_type=mime_type,
                    filename=export_filename,
                ),
                "timestamp": time.time(),
                "status": "success",
            }

    async def _update_file(
        self, config: GoogleDriveUpdateConfig, access_token: str
    ) -> Dict[str, Any]:
        """Update file metadata (name, description, starred)."""
        logger.info(f"[GoogleDriveNode] Updating file: {config.file_id}")

        metadata = {}
        if config.new_name:
            metadata["name"] = config.new_name
        if config.description is not None:
            metadata["description"] = config.description
        if config.starred is not None:
            metadata["starred"] = config.starred

        if not metadata:
            raise ValueError(
                "At least one field (name, description, or starred) must be provided"
            )

        async with httpx.AsyncClient() as client:
            response = await client.patch(
                f"{GOOGLE_DRIVE_API_BASE}/files/{config.file_id}",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=metadata,
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Drive API error: {error_msg}")

            file_data = response.json()

            return {
                "type": "google_drive",
                "operation": "update_file_metadata",
                "file_id": file_data.get("id"),
                "file_name": file_data.get("name"),
                "file": file_data,
                "timestamp": time.time(),
                "status": "success",
            }

    async def _trash_file(
        self, config: GoogleDriveTrashConfig, access_token: str
    ) -> Dict[str, Any]:
        """Move a file to trash."""
        logger.info(f"[GoogleDriveNode] Trashing file: {config.file_id}")

        async with httpx.AsyncClient() as client:
            response = await client.patch(
                f"{GOOGLE_DRIVE_API_BASE}/files/{config.file_id}",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={"trashed": True},
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Drive API error: {error_msg}")

            file_data = response.json()

            return {
                "type": "google_drive",
                "operation": "move_file_to_trash",
                "file_id": file_data.get("id"),
                "file_name": file_data.get("name"),
                "trashed": True,
                "timestamp": time.time(),
                "status": "success",
            }

    async def _restore_file(
        self, config: GoogleDriveRestoreConfig, access_token: str
    ) -> Dict[str, Any]:
        """Restore a file from trash."""
        logger.info(f"[GoogleDriveNode] Restoring file: {config.file_id}")

        async with httpx.AsyncClient() as client:
            response = await client.patch(
                f"{GOOGLE_DRIVE_API_BASE}/files/{config.file_id}",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={"trashed": False},
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Drive API error: {error_msg}")

            file_data = response.json()

            return {
                "type": "google_drive",
                "operation": "restore_file_from_trash",
                "file_id": file_data.get("id"),
                "file_name": file_data.get("name"),
                "trashed": False,
                "timestamp": time.time(),
                "status": "success",
            }

    async def _empty_trash(
        self, config: GoogleDriveEmptyTrashConfig, access_token: str
    ) -> Dict[str, Any]:
        """Permanently delete all files in trash."""
        logger.info("[GoogleDriveNode] Emptying trash")

        if not config.confirm:
            raise ValueError(
                "You must confirm this action by checking the confirmation box"
            )

        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{GOOGLE_DRIVE_API_BASE}/files/trash",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code not in (200, 204):
                error_data = response.json() if response.content else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Drive API error: {error_msg}")

            return {
                "type": "google_drive",
                "operation": "empty_drive_trash",
                "timestamp": time.time(),
                "status": "success",
            }

    async def _unshare_file(
        self, config: GoogleDriveUnshareConfig, access_token: str
    ) -> Dict[str, Any]:
        """Remove sharing permissions from a file."""
        logger.info(f"[GoogleDriveNode] Unsharing file: {config.file_id}")

        async with httpx.AsyncClient() as client:
            removed_permissions = []

            if config.permission_id:
                # Remove specific permission
                response = await client.delete(
                    f"{GOOGLE_DRIVE_API_BASE}/files/{config.file_id}/permissions/{config.permission_id}",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if response.status_code not in (200, 204):
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Failed to remove permission: {error_msg}")
                removed_permissions.append(config.permission_id)

            elif config.email:
                # Find and remove permission by email
                list_response = await client.get(
                    f"{GOOGLE_DRIVE_API_BASE}/files/{config.file_id}/permissions",
                    headers={"Authorization": f"Bearer {access_token}"},
                    params={"fields": "permissions(id,emailAddress,role,type)"},
                )

                if list_response.status_code != 200:
                    raise ValueError(
                        f"Failed to list permissions: {list_response.text}"
                    )

                permissions = list_response.json().get("permissions", [])
                for perm in permissions:
                    if perm.get("emailAddress", "").lower() == config.email.lower():
                        del_response = await client.delete(
                            f"{GOOGLE_DRIVE_API_BASE}/files/{config.file_id}/permissions/{perm['id']}",
                            headers={"Authorization": f"Bearer {access_token}"},
                        )
                        if del_response.status_code in (200, 204):
                            removed_permissions.append(perm["id"])

            else:
                # Remove all non-owner permissions
                list_response = await client.get(
                    f"{GOOGLE_DRIVE_API_BASE}/files/{config.file_id}/permissions",
                    headers={"Authorization": f"Bearer {access_token}"},
                    params={"fields": "permissions(id,role,type)"},
                )

                if list_response.status_code != 200:
                    raise ValueError(
                        f"Failed to list permissions: {list_response.text}"
                    )

                permissions = list_response.json().get("permissions", [])
                for perm in permissions:
                    if perm.get("role") != "owner":
                        del_response = await client.delete(
                            f"{GOOGLE_DRIVE_API_BASE}/files/{config.file_id}/permissions/{perm['id']}",
                            headers={"Authorization": f"Bearer {access_token}"},
                        )
                        if del_response.status_code in (200, 204):
                            removed_permissions.append(perm["id"])

            return {
                "type": "google_drive",
                "operation": "remove_file_permission",
                "file_id": config.file_id,
                "removed_permissions": removed_permissions,
                "removed_count": len(removed_permissions),
                "timestamp": time.time(),
                "status": "success",
            }

    async def _list_permissions(
        self, config: GoogleDriveListPermissionsConfig, access_token: str
    ) -> Dict[str, Any]:
        """List all permissions on a file."""
        logger.info(f"[GoogleDriveNode] Listing permissions for file: {config.file_id}")

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{GOOGLE_DRIVE_API_BASE}/files/{config.file_id}/permissions",
                headers={"Authorization": f"Bearer {access_token}"},
                params={
                    "fields": "permissions(id,type,role,emailAddress,displayName,domain,expirationTime)"
                },
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Drive API error: {error_msg}")

            data = response.json()
            permissions = data.get("permissions", [])

            return {
                "type": "google_drive",
                "operation": "list_file_permissions",
                "file_id": config.file_id,
                "permissions": permissions,
                "permission_count": len(permissions),
                "timestamp": time.time(),
                "status": "success",
            }

    async def _search_files(
        self, config: GoogleDriveSearchConfig, access_token: str
    ) -> Dict[str, Any]:
        """Search files with advanced query."""
        logger.info(f"[GoogleDriveNode] Searching files with query: {config.query}")

        async with httpx.AsyncClient() as client:
            params = {
                "q": config.query,
                "pageSize": config.page_size,
                "fields": "files(id,name,mimeType,size,createdTime,modifiedTime,parents,webViewLink,iconLink)",
            }
            if config.order_by:
                params["orderBy"] = config.order_by

            response = await client.get(
                f"{GOOGLE_DRIVE_API_BASE}/files",
                headers={"Authorization": f"Bearer {access_token}"},
                params=params,
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Drive API error: {error_msg}")

            data = response.json()
            files = data.get("files", [])

            return {
                "type": "google_drive",
                "operation": "search_files",
                "query": config.query,
                "files": files,
                "file_count": len(files),
                "timestamp": time.time(),
                "status": "success",
            }

    async def _create_comment(
        self, config: GoogleDriveCreateCommentConfig, access_token: str
    ) -> Dict[str, Any]:
        """Create a comment on a file."""
        logger.info(f"[GoogleDriveNode] Creating comment on file: {config.file_id}")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{GOOGLE_DRIVE_API_BASE}/files/{config.file_id}/comments",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                params={"fields": "id,content,author,createdTime,modifiedTime"},
                json={"content": config.content},
            )

            if response.status_code not in (200, 201):
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Drive API error: {error_msg}")

            comment_data = response.json()

            return {
                "type": "google_drive",
                "operation": "create_file_comment",
                "file_id": config.file_id,
                "comment": comment_data,
                "comment_id": comment_data.get("id"),
                "timestamp": time.time(),
                "status": "success",
            }

    async def _list_comments(
        self, config: GoogleDriveListCommentsConfig, access_token: str
    ) -> Dict[str, Any]:
        """List all comments on a file."""
        logger.info(f"[GoogleDriveNode] Listing comments on file: {config.file_id}")

        async with httpx.AsyncClient() as client:
            params = {
                "fields": "comments(id,content,author,createdTime,modifiedTime,resolved,deleted,replies)",
            }
            if config.include_deleted:
                params["includeDeleted"] = "true"

            response = await client.get(
                f"{GOOGLE_DRIVE_API_BASE}/files/{config.file_id}/comments",
                headers={"Authorization": f"Bearer {access_token}"},
                params=params,
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Drive API error: {error_msg}")

            data = response.json()
            comments = data.get("comments", [])

            return {
                "type": "google_drive",
                "operation": "list_file_comments",
                "file_id": config.file_id,
                "comments": comments,
                "comment_count": len(comments),
                "timestamp": time.time(),
                "status": "success",
            }

    async def _delete_comment(
        self, config: GoogleDriveDeleteCommentConfig, access_token: str
    ) -> Dict[str, Any]:
        """Delete a comment from a file."""
        logger.info(
            f"[GoogleDriveNode] Deleting comment {config.comment_id} from file: {config.file_id}"
        )

        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{GOOGLE_DRIVE_API_BASE}/files/{config.file_id}/comments/{config.comment_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code not in (200, 204):
                error_data = response.json() if response.content else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Drive API error: {error_msg}")

            return {
                "type": "google_drive",
                "operation": "delete_file_comment",
                "file_id": config.file_id,
                "comment_id": config.comment_id,
                "timestamp": time.time(),
                "status": "success",
            }

    async def _list_revisions(
        self, config: GoogleDriveListRevisionsConfig, access_token: str
    ) -> Dict[str, Any]:
        """List all revisions of a file."""
        logger.info(f"[GoogleDriveNode] Listing revisions for file: {config.file_id}")

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{GOOGLE_DRIVE_API_BASE}/files/{config.file_id}/revisions",
                headers={"Authorization": f"Bearer {access_token}"},
                params={
                    "fields": "revisions(id,mimeType,modifiedTime,keepForever,size,originalFilename,lastModifyingUser)"
                },
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Drive API error: {error_msg}")

            data = response.json()
            revisions = data.get("revisions", [])

            return {
                "type": "google_drive",
                "operation": "list_file_revisions",
                "file_id": config.file_id,
                "revisions": revisions,
                "revision_count": len(revisions),
                "timestamp": time.time(),
                "status": "success",
            }

    async def _get_about(self, access_token: str) -> Dict[str, Any]:
        """Get Drive storage info and user details."""
        logger.info("[GoogleDriveNode] Getting Drive about info")

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{GOOGLE_DRIVE_API_BASE}/about",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"fields": "user,storageQuota,kind"},
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Drive API error: {error_msg}")

            data = response.json()
            storage_quota = data.get("storageQuota", {})
            user = data.get("user", {})

            # Calculate usage percentage
            limit = int(storage_quota.get("limit", 0))
            usage = int(storage_quota.get("usage", 0))
            usage_percent = (usage / limit * 100) if limit > 0 else 0

            return {
                "type": "google_drive",
                "operation": "get_drive_storage_info",
                "user": {
                    "email": user.get("emailAddress"),
                    "name": user.get("displayName"),
                    "photo": user.get("photoLink"),
                },
                "storage": {
                    "limit": limit,
                    "usage": usage,
                    "usage_in_drive": int(storage_quota.get("usageInDrive", 0)),
                    "usage_in_trash": int(storage_quota.get("usageInDriveTrash", 0)),
                    "usage_percent": round(usage_percent, 2),
                    "limit_formatted": self._format_bytes(limit),
                    "usage_formatted": self._format_bytes(usage),
                },
                "timestamp": time.time(),
                "status": "success",
            }

    @staticmethod
    def _format_bytes(bytes_value: int) -> str:
        """Format bytes to human-readable string."""
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if bytes_value < 1024:
                return f"{bytes_value:.2f} {unit}"
            bytes_value /= 1024
        return f"{bytes_value:.2f} PB"

    async def _get_comment(
        self, config: GoogleDriveGetCommentConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get a specific comment by ID."""
        logger.info(f"[GoogleDriveNode] Getting comment {config.comment_id}")

        url = f"{GOOGLE_DRIVE_API_BASE}/files/{config.file_id}/comments/{config.comment_id}"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                params={
                    "fields": "id,content,author,createdTime,modifiedTime,resolved,replies"
                },
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Drive API error: {error_msg}")

            comment = response.json()
            return {
                "type": "google_drive",
                "operation": "get_file_comment",
                "file_id": config.file_id,
                "comment": comment,
                "timestamp": time.time(),
                "status": "success",
            }

    async def _update_comment(
        self, config: GoogleDriveUpdateCommentConfig, access_token: str
    ) -> Dict[str, Any]:
        """Update an existing comment."""
        logger.info(f"[GoogleDriveNode] Updating comment {config.comment_id}")

        url = f"{GOOGLE_DRIVE_API_BASE}/files/{config.file_id}/comments/{config.comment_id}"

        async with httpx.AsyncClient() as client:
            response = await client.patch(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={"content": config.content},
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Drive API error: {error_msg}")

            comment = response.json()
            return {
                "type": "google_drive",
                "operation": "update_file_comment",
                "file_id": config.file_id,
                "comment_id": config.comment_id,
                "comment": comment,
                "timestamp": time.time(),
                "status": "success",
            }

    async def _create_reply(
        self, config: GoogleDriveCreateReplyConfig, access_token: str
    ) -> Dict[str, Any]:
        """Create a reply to a comment."""
        logger.info(f"[GoogleDriveNode] Creating reply to comment {config.comment_id}")

        url = f"{GOOGLE_DRIVE_API_BASE}/files/{config.file_id}/comments/{config.comment_id}/replies"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={"content": config.content},
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Drive API error: {error_msg}")

            reply = response.json()
            return {
                "type": "google_drive",
                "operation": "create_comment_reply",
                "file_id": config.file_id,
                "comment_id": config.comment_id,
                "reply": reply,
                "timestamp": time.time(),
                "status": "success",
            }

    async def _list_replies(
        self, config: GoogleDriveListRepliesConfig, access_token: str
    ) -> Dict[str, Any]:
        """List all replies to a comment."""
        logger.info(f"[GoogleDriveNode] Listing replies to comment {config.comment_id}")

        url = f"{GOOGLE_DRIVE_API_BASE}/files/{config.file_id}/comments/{config.comment_id}/replies"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                params={
                    "fields": "replies(id,content,author,createdTime,modifiedTime)"
                },
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Drive API error: {error_msg}")

            data = response.json()
            return {
                "type": "google_drive",
                "operation": "list_comment_replies",
                "file_id": config.file_id,
                "comment_id": config.comment_id,
                "replies": data.get("replies", []),
                "reply_count": len(data.get("replies", [])),
                "timestamp": time.time(),
                "status": "success",
            }

    async def _delete_reply(
        self, config: GoogleDriveDeleteReplyConfig, access_token: str
    ) -> Dict[str, Any]:
        """Delete a reply from a comment."""
        logger.info(f"[GoogleDriveNode] Deleting reply {config.reply_id}")

        url = f"{GOOGLE_DRIVE_API_BASE}/files/{config.file_id}/comments/{config.comment_id}/replies/{config.reply_id}"

        async with httpx.AsyncClient() as client:
            response = await client.delete(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code not in [200, 204]:
                error_data = response.json() if response.text else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Drive API error: {error_msg}")

            return {
                "type": "google_drive",
                "operation": "delete_comment_reply",
                "file_id": config.file_id,
                "comment_id": config.comment_id,
                "reply_id": config.reply_id,
                "timestamp": time.time(),
                "status": "success",
            }

    async def _get_revision(
        self, config: GoogleDriveGetRevisionConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get a specific file revision."""
        logger.info(f"[GoogleDriveNode] Getting revision {config.revision_id}")

        url = f"{GOOGLE_DRIVE_API_BASE}/files/{config.file_id}/revisions/{config.revision_id}"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                params={
                    "fields": "id,mimeType,modifiedTime,keepForever,published,originalFilename,size"
                },
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Drive API error: {error_msg}")

            revision = response.json()
            return {
                "type": "google_drive",
                "operation": "get_file_revision",
                "file_id": config.file_id,
                "revision": revision,
                "timestamp": time.time(),
                "status": "success",
            }

    async def _delete_revision(
        self, config: GoogleDriveDeleteRevisionConfig, access_token: str
    ) -> Dict[str, Any]:
        """Delete a specific file revision."""
        logger.info(f"[GoogleDriveNode] Deleting revision {config.revision_id}")

        url = f"{GOOGLE_DRIVE_API_BASE}/files/{config.file_id}/revisions/{config.revision_id}"

        async with httpx.AsyncClient() as client:
            response = await client.delete(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code not in [200, 204]:
                error_data = response.json() if response.text else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Drive API error: {error_msg}")

            return {
                "type": "google_drive",
                "operation": "delete_file_revision",
                "file_id": config.file_id,
                "revision_id": config.revision_id,
                "timestamp": time.time(),
                "status": "success",
            }

    async def _get_permission(
        self, config: GoogleDriveGetPermissionConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get a specific permission for a file."""
        logger.info(
            f"[GoogleDriveNode] Getting permission {config.permission_id} for file {config.file_id}"
        )

        url = f"{GOOGLE_DRIVE_API_BASE}/files/{config.file_id}/permissions/{config.permission_id}"
        params = {
            "fields": "id,type,role,emailAddress,displayName,domain,expirationTime,deleted,allowFileDiscovery"
        }
        if config.supports_all_drives:
            params["supportsAllDrives"] = "true"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}, params=params
            )

            if response.status_code != 200:
                error_data = response.json() if response.text else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Drive API error: {error_msg}")

            permission = response.json()
            return {
                "type": "google_drive",
                "operation": "get_file_permission",
                "file_id": config.file_id,
                "permission": permission,
                "timestamp": time.time(),
                "status": "success",
            }

    async def _update_permission(
        self, config: GoogleDriveUpdatePermissionConfig, access_token: str
    ) -> Dict[str, Any]:
        """Update a permission's role."""
        logger.info(
            f"[GoogleDriveNode] Updating permission {config.permission_id} for file {config.file_id}"
        )

        url = f"{GOOGLE_DRIVE_API_BASE}/files/{config.file_id}/permissions/{config.permission_id}"
        params = {"fields": "id,type,role,emailAddress,displayName"}
        if config.supports_all_drives:
            params["supportsAllDrives"] = "true"
        if config.transfer_ownership:
            params["transferOwnership"] = "true"

        body = {"role": config.role}
        if config.expiration_time:
            body["expirationTime"] = config.expiration_time

        async with httpx.AsyncClient() as client:
            response = await client.patch(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                params=params,
                json=body,
            )

            if response.status_code != 200:
                error_data = response.json() if response.text else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Drive API error: {error_msg}")

            permission = response.json()
            return {
                "type": "google_drive",
                "operation": "update_file_permission",
                "file_id": config.file_id,
                "permission": permission,
                "timestamp": time.time(),
                "status": "success",
            }

    async def _get_reply(
        self, config: GoogleDriveGetReplyConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get a specific reply to a comment."""
        logger.info(f"[GoogleDriveNode] Getting reply {config.reply_id}")

        url = f"{GOOGLE_DRIVE_API_BASE}/files/{config.file_id}/comments/{config.comment_id}/replies/{config.reply_id}"
        params = {
            "fields": "id,content,createdTime,modifiedTime,author,deleted,htmlContent,action"
        }
        if config.include_deleted:
            params["includeDeleted"] = "true"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}, params=params
            )

            if response.status_code != 200:
                error_data = response.json() if response.text else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Drive API error: {error_msg}")

            reply = response.json()
            return {
                "type": "google_drive",
                "operation": "get_comment_reply",
                "file_id": config.file_id,
                "comment_id": config.comment_id,
                "reply": reply,
                "timestamp": time.time(),
                "status": "success",
            }

    async def _update_reply(
        self, config: GoogleDriveUpdateReplyConfig, access_token: str
    ) -> Dict[str, Any]:
        """Update a reply to a comment."""
        logger.info(f"[GoogleDriveNode] Updating reply {config.reply_id}")

        url = f"{GOOGLE_DRIVE_API_BASE}/files/{config.file_id}/comments/{config.comment_id}/replies/{config.reply_id}"

        async with httpx.AsyncClient() as client:
            response = await client.patch(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                params={"fields": "id,content,createdTime,modifiedTime,author"},
                json={"content": config.content},
            )

            if response.status_code != 200:
                error_data = response.json() if response.text else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Drive API error: {error_msg}")

            reply = response.json()
            return {
                "type": "google_drive",
                "operation": "update_comment_reply",
                "file_id": config.file_id,
                "comment_id": config.comment_id,
                "reply": reply,
                "timestamp": time.time(),
                "status": "success",
            }

    async def _update_revision(
        self, config: GoogleDriveUpdateRevisionConfig, access_token: str
    ) -> Dict[str, Any]:
        """Update a file revision's metadata."""
        logger.info(f"[GoogleDriveNode] Updating revision {config.revision_id}")

        url = f"{GOOGLE_DRIVE_API_BASE}/files/{config.file_id}/revisions/{config.revision_id}"

        body = {}
        if config.keep_forever is not None:
            body["keepForever"] = config.keep_forever
        if config.publish_auto is not None:
            body["publishAuto"] = config.publish_auto
        if config.published is not None:
            body["published"] = config.published

        async with httpx.AsyncClient() as client:
            response = await client.patch(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                params={
                    "fields": "id,mimeType,modifiedTime,keepForever,published,publishAuto,publishedLink,size"
                },
                json=body,
            )

            if response.status_code != 200:
                error_data = response.json() if response.text else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Drive API error: {error_msg}")

            revision = response.json()
            return {
                "type": "google_drive",
                "operation": "update_file_revision",
                "file_id": config.file_id,
                "revision": revision,
                "timestamp": time.time(),
                "status": "success",
            }

    async def _list_shared_drives(
        self, config: GoogleDriveListSharedDrivesConfig, access_token: str
    ) -> Dict[str, Any]:
        """List shared drives."""
        logger.info("[GoogleDriveNode] Listing shared drives")

        params = {
            "pageSize": min(config.page_size, 100),
            "fields": "nextPageToken,drives(id,name,createdTime,hidden,restrictions,backgroundImageFile,colorRgb,themeId)",
        }
        if config.use_domain_admin_access:
            params["useDomainAdminAccess"] = "true"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{GOOGLE_DRIVE_API_BASE}/drives",
                headers={"Authorization": f"Bearer {access_token}"},
                params=params,
            )

            if response.status_code != 200:
                error_data = response.json() if response.text else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Drive API error: {error_msg}")

            data = response.json()
            return {
                "type": "google_drive",
                "operation": "list_shared_drives",
                "drives": data.get("drives", []),
                "next_page_token": data.get("nextPageToken"),
                "timestamp": time.time(),
                "status": "success",
            }

    async def _get_shared_drive(
        self, config: GoogleDriveGetSharedDriveConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get a shared drive's details."""
        logger.info(f"[GoogleDriveNode] Getting shared drive {config.drive_id}")

        params = {
            "fields": "id,name,createdTime,hidden,restrictions,backgroundImageFile,colorRgb,themeId,capabilities"
        }
        if config.use_domain_admin_access:
            params["useDomainAdminAccess"] = "true"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{GOOGLE_DRIVE_API_BASE}/drives/{config.drive_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                params=params,
            )

            if response.status_code != 200:
                error_data = response.json() if response.text else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Drive API error: {error_msg}")

            drive = response.json()
            return {
                "type": "google_drive",
                "operation": "get_shared_drive",
                "drive": drive,
                "timestamp": time.time(),
                "status": "success",
            }

    async def _create_shared_drive(
        self, config: GoogleDriveCreateSharedDriveConfig, access_token: str
    ) -> Dict[str, Any]:
        """Create a new shared drive."""
        import uuid

        logger.info(f"[GoogleDriveNode] Creating shared drive: {config.name}")

        # requestId is required to ensure idempotency
        request_id = str(uuid.uuid4())

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{GOOGLE_DRIVE_API_BASE}/drives",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                params={"requestId": request_id},
                json={"name": config.name},
            )

            if response.status_code not in [200, 201]:
                error_data = response.json() if response.text else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Drive API error: {error_msg}")

            drive = response.json()
            return {
                "type": "google_drive",
                "operation": "create_shared_drive",
                "drive": drive,
                "timestamp": time.time(),
                "status": "success",
            }

    async def _delete_shared_drive(
        self, config: GoogleDriveDeleteSharedDriveConfig, access_token: str
    ) -> Dict[str, Any]:
        """Delete a shared drive."""
        logger.info(f"[GoogleDriveNode] Deleting shared drive {config.drive_id}")

        params = {}
        if config.use_domain_admin_access:
            params["useDomainAdminAccess"] = "true"
        if config.allow_item_deletion:
            params["allowItemDeletion"] = "true"

        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{GOOGLE_DRIVE_API_BASE}/drives/{config.drive_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                params=params if params else None,
            )

            if response.status_code not in [200, 204]:
                error_data = response.json() if response.text else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Drive API error: {error_msg}")

            return {
                "type": "google_drive",
                "operation": "delete_shared_drive",
                "drive_id": config.drive_id,
                "timestamp": time.time(),
                "status": "success",
            }

    async def _hide_shared_drive(
        self, config: GoogleDriveHideSharedDriveConfig, access_token: str
    ) -> Dict[str, Any]:
        """Hide a shared drive from default view."""
        logger.info(f"[GoogleDriveNode] Hiding shared drive {config.drive_id}")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{GOOGLE_DRIVE_API_BASE}/drives/{config.drive_id}/hide",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                error_data = response.json() if response.text else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Drive API error: {error_msg}")

            drive = response.json()
            return {
                "type": "google_drive",
                "operation": "hide_shared_drive",
                "drive": drive,
                "timestamp": time.time(),
                "status": "success",
            }

    async def _unhide_shared_drive(
        self, config: GoogleDriveUnhideSharedDriveConfig, access_token: str
    ) -> Dict[str, Any]:
        """Unhide a shared drive."""
        logger.info(f"[GoogleDriveNode] Unhiding shared drive {config.drive_id}")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{GOOGLE_DRIVE_API_BASE}/drives/{config.drive_id}/unhide",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                error_data = response.json() if response.text else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                raise ValueError(f"Google Drive API error: {error_msg}")

            drive = response.json()
            return {
                "type": "google_drive",
                "operation": "unhide_shared_drive",
                "drive": drive,
                "timestamp": time.time(),
                "status": "success",
            }
