"""
Dropbox Node - Comprehensive file storage and sharing automation.

Provides access to Dropbox API v2 including:
- File operations (upload, download, list, search, metadata)
- Large file uploads via upload sessions (up to 350GB)
- Folder management (create, list, delete)
- Sharing (links, shared folders, permissions)
- Account information and space usage
- File requests automation

Supports OAuth 2.0 with refresh tokens and PKCE flow.
"""

import logging
import os
import base64
from typing import Dict, Any, Optional, Union, Type, List, Annotated, Literal
from pydantic import BaseModel, Field, ConfigDict, Discriminator
from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
import httpx
from nodes.scopes.content_storage import DROPBOX_SCOPES

logger = logging.getLogger(__name__)


# ============================================================================
# Credential Schemas
# ============================================================================


class DropboxOAuthCredential(BaseModel):
    """OAuth 2.0 credential for Dropbox.

    Tokens are obtained via OAuth flow, not entered manually.
    Supports both short-lived and long-lived (refresh token) access.

    Register OAuth app at: https://www.dropbox.com/developers/apps
    """

    credential_type: Literal["dropbox_oauth"] = Field(
        "dropbox_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(..., title="Access Token")
    refresh_token: Optional[str] = Field(None, title="Refresh Token")
    expires_at: Optional[str] = Field(None, title="Token Expiry")  # ISO 8601
    account_id: Optional[str] = Field(None, title="Account ID")
    email: Optional[str] = Field(None, title="Account Email")

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "dropbox",
            "x-oauth-scopes": [
                "account_info.read",
                "files.metadata.read",
                "files.metadata.write",
                "files.content.read",
                "files.content.write",
                "sharing.read",
                "sharing.write",
                "file_requests.read",
                "file_requests.write",
            ],
        }
    )


# Only OAuth for Dropbox (no API keys or PATs - OAuth is the standard)
DropboxCredential = DropboxOAuthCredential


# ============================================================================
# Operation Configs - Files API
# ============================================================================


class DropboxUploadFileConfig(BaseModel):
    """Upload a file to Dropbox (max 150 MB)."""

    operation: Literal["upload_file"] = Field(
        default="upload_file",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Upload File",
        },
        title="Upload File",
    )
    local_file_path: str = Field(
        ...,
        title="Local File Path",
        description="Path to the file to upload",
        json_schema_extra={"placeholder": "/path/to/local/file.txt"},
    )
    dropbox_path: str = Field(
        ...,
        title="Dropbox Destination Path",
        description="Where to save the file in Dropbox (e.g., /Documents/file.txt)",
        json_schema_extra={"placeholder": "/Documents/file.txt"},
    )
    mode: str = Field(
        "add",
        title="Write Mode",
        description="How to handle existing files",
        json_schema_extra={
            "enum": ["add", "overwrite", "update"],
            "enumNames": ["Add (fail if exists)", "Overwrite", "Update if exists"],
        },
    )
    autorename: bool = Field(
        False,
        title="Auto-rename if conflict",
        description="Automatically rename if file exists",
    )
    mute: bool = Field(
        False,
        title="Mute notifications",
        description="Don't notify users about this change",
    )


class DropboxUploadLargeFileConfig(BaseModel):
    """Upload large files (150 MB to 350 GB) using upload sessions."""

    operation: Literal["upload_large_file_with_sessions"] = Field(
        default="upload_large_file_with_sessions",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Upload Large File with Sessions",
        },
        title="Upload Large File with Sessions",
    )
    local_file_path: str = Field(
        ...,
        title="Local File Path",
        description="Path to the large file to upload",
        json_schema_extra={"placeholder": "/path/to/large_file.zip"},
    )
    dropbox_path: str = Field(
        ...,
        title="Dropbox Destination Path",
        description="Where to save the file in Dropbox",
        json_schema_extra={"placeholder": "/Backups/large_file.zip"},
    )
    chunk_size_mb: int = Field(
        4,
        title="Chunk Size (MB)",
        description="Size of each upload chunk (recommended: 4 MB multiples)",
        ge=1,
        le=150,
    )
    mode: str = Field(
        "add",
        title="Write Mode",
        json_schema_extra={"enum": ["add", "overwrite", "update"]},
    )


class DropboxDownloadFileConfig(BaseModel):
    """Download a file from Dropbox."""

    operation: Literal["download_file"] = Field(
        default="download_file",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Download File",
        },
        title="Download File",
    )
    dropbox_path: str = Field(
        ...,
        title="Dropbox File Path",
        description="Path to the file in Dropbox to download",
        json_schema_extra={"placeholder": "/Documents/report.pdf"},
    )
    local_file_path: str = Field(
        ...,
        title="Local Destination Path",
        description="Where to save the downloaded file",
        json_schema_extra={"placeholder": "/path/to/save/report.pdf"},
    )


class DropboxListFolderConfig(BaseModel):
    """List contents of a Dropbox folder."""

    operation: Literal["list_folder_contents"] = Field(
        default="list_folder_contents",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Folder",
            "x-is-trigger": False,
            "x-display-name": "List Folder Contents",
        },
        title="List Folder Contents",
    )
    path: str = Field(
        "",
        title="Folder Path",
        description="Path to folder (empty string for root)",
        json_schema_extra={"placeholder": "/Documents"},
    )
    recursive: bool = Field(
        False, title="Recursive", description="List all files and folders recursively"
    )
    include_deleted: bool = Field(
        False,
        title="Include Deleted Files",
        description="Include deleted files and folders",
    )
    include_media_info: bool = Field(
        False,
        title="Include Media Info",
        description="Include photo and video metadata",
    )
    limit: int = Field(
        2000,
        title="Max Results",
        description="Maximum number of results (max 2000)",
        ge=1,
        le=2000,
    )


class DropboxCreateFolderConfig(BaseModel):
    """Create a new folder in Dropbox."""

    operation: Literal["create_folder"] = Field(
        default="create_folder",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Folder",
            "x-is-trigger": False,
            "x-display-name": "Create Folder",
        },
        title="Create Folder",
    )
    path: str = Field(
        ...,
        title="Folder Path",
        description="Path for the new folder",
        json_schema_extra={"placeholder": "/Projects/New Project"},
    )
    autorename: bool = Field(
        False,
        title="Auto-rename if exists",
        description="Automatically rename if folder already exists",
    )


class DropboxDeleteConfig(BaseModel):
    """Delete a file or folder from Dropbox."""

    operation: Literal["delete_file_or_folder"] = Field(
        default="delete_file_or_folder",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Delete File or Folder",
        },
        title="Delete File or Folder",
    )
    path: str = Field(
        ...,
        title="Path to Delete",
        description="Path to file or folder to delete",
        json_schema_extra={"placeholder": "/Documents/old_file.txt"},
    )


class DropboxCopyConfig(BaseModel):
    """Copy a file or folder to another location."""

    operation: Literal["copy_file_or_folder"] = Field(
        default="copy_file_or_folder",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Copy File or Folder",
        },
        title="Copy File or Folder",
    )
    from_path: str = Field(
        ...,
        title="Source Path",
        description="Path to copy from",
        json_schema_extra={"placeholder": "/Documents/file.txt"},
    )
    to_path: str = Field(
        ...,
        title="Destination Path",
        description="Path to copy to",
        json_schema_extra={"placeholder": "/Backups/file.txt"},
    )
    allow_shared_folder: bool = Field(
        False,
        title="Allow Shared Folder",
        description="Allow copying from shared folders",
    )
    autorename: bool = Field(False, title="Auto-rename if exists")


class DropboxMoveConfig(BaseModel):
    """Move a file or folder to another location."""

    operation: Literal["move_file_or_folder"] = Field(
        default="move_file_or_folder",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Move File or Folder",
        },
        title="Move File or Folder",
    )
    from_path: str = Field(
        ...,
        title="Source Path",
        description="Path to move from",
        json_schema_extra={"placeholder": "/Documents/file.txt"},
    )
    to_path: str = Field(
        ...,
        title="Destination Path",
        description="Path to move to",
        json_schema_extra={"placeholder": "/Archives/file.txt"},
    )
    allow_shared_folder: bool = Field(False, title="Allow Shared Folder")
    autorename: bool = Field(False, title="Auto-rename if exists")


class DropboxSearchConfig(BaseModel):
    """Search for files and folders in Dropbox."""

    operation: Literal["search_files_and_folders"] = Field(
        default="search_files_and_folders",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Search Files and Folders",
        },
        title="Search Files and Folders",
    )
    query: str = Field(
        ...,
        title="Search Query",
        description="Text to search for",
        json_schema_extra={"placeholder": "meeting notes"},
    )
    path: str = Field(
        "",
        title="Search Path",
        description="Folder to search in (empty for entire Dropbox)",
        json_schema_extra={"placeholder": "/Documents"},
    )
    max_results: int = Field(
        100,
        title="Max Results",
        description="Maximum number of results to return",
        ge=1,
        le=1000,
    )
    file_extensions: Optional[str] = Field(
        None,
        title="File Extensions",
        description="Filter by file extensions (comma-separated, e.g., pdf,docx)",
        json_schema_extra={"placeholder": "pdf,docx,txt"},
    )


class DropboxGetMetadataConfig(BaseModel):
    """Get metadata for a file or folder."""

    operation: Literal["get_file_or_folder_metadata"] = Field(
        default="get_file_or_folder_metadata",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Get File or Folder Metadata",
        },
        title="Get File or Folder Metadata",
    )
    path: str = Field(
        ...,
        title="Path",
        description="Path to file or folder",
        json_schema_extra={"placeholder": "/Documents/file.txt"},
    )
    include_media_info: bool = Field(
        False,
        title="Include Media Info",
        description="Include photo and video metadata",
    )


class DropboxGetTemporaryLinkConfig(BaseModel):
    """Create a temporary direct link to download a file."""

    operation: Literal["get_temporary_download_link"] = Field(
        default="get_temporary_download_link",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Get Temporary Download Link",
        },
        title="Get Temporary Download Link",
    )
    path: str = Field(
        ...,
        title="File Path",
        description="Path to the file",
        json_schema_extra={"placeholder": "/Documents/file.pdf"},
    )


class DropboxListRevisionsConfig(BaseModel):
    """List revision history for a file."""

    operation: Literal["list_file_revisions"] = Field(
        default="list_file_revisions",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "List File Revisions",
        },
        title="List File Revisions",
    )
    path: str = Field(
        ..., title="File Path", json_schema_extra={"placeholder": "/Documents/file.txt"}
    )
    limit: int = Field(
        100,
        title="Max Revisions",
        description="Maximum number of revisions to return",
        ge=1,
        le=100,
    )


class DropboxRestoreConfig(BaseModel):
    """Restore a file to a previous revision."""

    operation: Literal["restore_file_to_revision"] = Field(
        default="restore_file_to_revision",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Restore File to Revision",
        },
        title="Restore File to Revision",
    )
    path: str = Field(
        ..., title="File Path", json_schema_extra={"placeholder": "/Documents/file.txt"}
    )
    rev: str = Field(
        ...,
        title="Revision ID",
        description="Revision ID to restore to",
        json_schema_extra={"placeholder": "a1c10ce0dd78"},
    )


class DropboxDownloadZipConfig(BaseModel):
    """Download a folder as a ZIP archive."""

    operation: Literal["download_folder_as_zip"] = Field(
        default="download_folder_as_zip",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Folder",
            "x-is-trigger": False,
            "x-display-name": "Download Folder As Zip",
        },
        title="Download Folder As Zip",
    )
    path: str = Field(
        ...,
        title="Folder Path",
        description="Path to folder to download as ZIP",
        json_schema_extra={"placeholder": "/Documents/Project"},
    )
    local_save_path: str = Field(
        ...,
        title="Local Save Path",
        description="Where to save the ZIP file",
        json_schema_extra={"placeholder": "/path/to/save/archive.zip"},
    )


class DropboxGetThumbnailConfig(BaseModel):
    """Get thumbnail for an image file."""

    operation: Literal["get_file_thumbnail"] = Field(
        default="get_file_thumbnail",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Get File Thumbnail",
        },
        title="Get File Thumbnail",
    )
    path: str = Field(
        ...,
        title="Image File Path",
        description="Path to image file",
        json_schema_extra={"placeholder": "/Photos/image.jpg"},
    )
    format: str = Field(
        "jpeg",
        title="Thumbnail Format",
        json_schema_extra={"enum": ["jpeg", "png"], "enumNames": ["JPEG", "PNG"]},
    )
    size: str = Field(
        "w64h64",
        title="Thumbnail Size",
        json_schema_extra={
            "enum": [
                "w32h32",
                "w64h64",
                "w128h128",
                "w256h256",
                "w480h320",
                "w640h480",
                "w960h640",
                "w1024h768",
                "w2048h1536",
            ],
            "enumNames": [
                "32x32",
                "64x64",
                "128x128",
                "256x256",
                "480x320",
                "640x480",
                "960x640",
                "1024x768",
                "2048x1536",
            ],
        },
    )
    local_save_path: str = Field(
        ...,
        title="Save Thumbnail To",
        description="Where to save the thumbnail",
        json_schema_extra={"placeholder": "/path/to/thumbnail.jpg"},
    )


class DropboxSaveUrlConfig(BaseModel):
    """Save a URL's content directly to Dropbox."""

    operation: Literal["save_url_to_dropbox"] = Field(
        default="save_url_to_dropbox",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Save Url to Dropbox",
        },
        title="Save Url to Dropbox",
    )
    url: str = Field(
        ...,
        title="URL",
        description="URL to save",
        json_schema_extra={"placeholder": "https://example.com/file.pdf"},
    )
    path: str = Field(
        ...,
        title="Dropbox Save Path",
        description="Where to save the file",
        json_schema_extra={"placeholder": "/Downloads/file.pdf"},
    )


class DropboxGetFileRequestConfig(BaseModel):
    """Get details of a file request."""

    operation: Literal["get_file_request"] = Field(
        default="get_file_request",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File Request",
            "x-is-trigger": False,
            "x-display-name": "Get File Request",
        },
        title="Get File Request",
    )
    file_request_id: str = Field(
        ...,
        title="File Request ID",
        json_schema_extra={"placeholder": "oaCAVmEyrqYnkZX9955Y"},
    )


class DropboxUpdateFileRequestConfig(BaseModel):
    """Update a file request."""

    operation: Literal["update_file_request"] = Field(
        default="update_file_request",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File Request",
            "x-is-trigger": False,
            "x-display-name": "Update File Request",
        },
        title="Update File Request",
    )
    file_request_id: str = Field(
        ...,
        title="File Request ID",
        json_schema_extra={"placeholder": "oaCAVmEyrqYnkZX9955Y"},
    )
    title: Optional[str] = Field(
        None, title="New Title", description="Update the title (optional)"
    )
    deadline: Optional[str] = Field(
        None,
        title="New Deadline",
        description="Update deadline (ISO 8601)",
        json_schema_extra={"placeholder": "2025-12-31T23:59:59Z"},
    )
    open: Optional[bool] = Field(None, title="Open/Close Request")


class DropboxDeleteFileRequestConfig(BaseModel):
    """Delete a file request."""

    operation: Literal["delete_file_request"] = Field(
        default="delete_file_request",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File Request",
            "x-is-trigger": False,
            "x-display-name": "Delete File Request",
        },
        title="Delete File Request",
    )
    file_request_id: str = Field(
        ...,
        title="File Request ID",
        json_schema_extra={"placeholder": "oaCAVmEyrqYnkZX9955Y"},
    )


# ============================================================================
# Operation Configs - Sharing API
# ============================================================================


class DropboxCreateSharedLinkConfig(BaseModel):
    """Create a shared link for a file or folder."""

    operation: Literal["create_shared_link"] = Field(
        default="create_shared_link",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File Sharing",
            "x-is-trigger": False,
            "x-display-name": "Create Shared Link",
        },
        title="Create Shared Link",
    )
    path: str = Field(
        ...,
        title="Path",
        description="Path to file or folder to share",
        json_schema_extra={"placeholder": "/Documents/report.pdf"},
    )
    password: Optional[str] = Field(
        None,
        title="Password Protection",
        description="Optional password to protect the link",
        json_schema_extra={"ui:widget": "password"},
    )
    expires: Optional[str] = Field(
        None,
        title="Expiration Date",
        description="When the link should expire (ISO 8601 format)",
        json_schema_extra={"placeholder": "2025-12-31T23:59:59Z"},
    )
    audience: str = Field(
        "public",
        title="Link Audience",
        description="Who can access the link",
        json_schema_extra={
            "enum": ["public", "team", "no_one"],
            "enumNames": [
                "Public (anyone with link)",
                "Team only",
                "No one (password only)",
            ],
        },
    )


class DropboxListSharedLinksConfig(BaseModel):
    """List all shared links."""

    operation: Literal["list_shared_links"] = Field(
        default="list_shared_links",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File Sharing",
            "x-is-trigger": False,
            "x-display-name": "List Shared Links",
        },
        title="List Shared Links",
    )
    path: Optional[str] = Field(
        None,
        title="Filter by Path",
        description="Only show links for this path (optional)",
        json_schema_extra={"placeholder": "/Documents"},
    )
    direct_only: bool = Field(
        False,
        title="Direct Links Only",
        description="Only show direct links (not inherited)",
    )


class DropboxRevokeSharedLinkConfig(BaseModel):
    """Revoke a shared link."""

    operation: Literal["revoke_shared_link"] = Field(
        default="revoke_shared_link",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File Sharing",
            "x-is-trigger": False,
            "x-display-name": "Revoke Shared Link",
        },
        title="Revoke Shared Link",
    )
    url: str = Field(
        ...,
        title="Shared Link URL",
        description="The shared link URL to revoke",
        json_schema_extra={"placeholder": "https://www.dropbox.com/s/..."},
    )


class DropboxShareFolderConfig(BaseModel):
    """Share a folder with specific users."""

    operation: Literal["share_folder_with_members"] = Field(
        default="share_folder_with_members",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Shared Folder",
            "x-is-trigger": False,
            "x-display-name": "Share Folder with Members",
        },
        title="Share Folder with Members",
    )
    path: str = Field(
        ...,
        title="Folder Path",
        description="Path to folder to share",
        json_schema_extra={"placeholder": "/Projects/Team Project"},
    )
    member_emails: str = Field(
        ...,
        title="Member Emails",
        description="Comma-separated list of email addresses to share with",
        json_schema_extra={"placeholder": "user1@example.com, user2@example.com"},
    )
    access_level: str = Field(
        "viewer",
        title="Access Level",
        description="Permission level for members",
        json_schema_extra={
            "enum": ["viewer", "editor", "owner"],
            "enumNames": [
                "Viewer (can view)",
                "Editor (can edit)",
                "Owner (full control)",
            ],
        },
    )
    send_notification: bool = Field(
        True, title="Send Notification", description="Notify members via email"
    )


class DropboxListFolderMembersConfig(BaseModel):
    """List all members of a shared folder."""

    operation: Literal["list_shared_folder_members"] = Field(
        default="list_shared_folder_members",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Shared Folder",
            "x-is-trigger": False,
            "x-display-name": "List Shared Folder Members",
        },
        title="List Shared Folder Members",
    )
    shared_folder_id: str = Field(
        ..., title="Shared Folder ID", json_schema_extra={"placeholder": "84528192421"}
    )


class DropboxAddFolderMemberConfig(BaseModel):
    """Add members to an existing shared folder."""

    operation: Literal["add_members_to_shared_folder"] = Field(
        default="add_members_to_shared_folder",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Shared Folder",
            "x-is-trigger": False,
            "x-display-name": "Add Members to Shared Folder",
        },
        title="Add Members to Shared Folder",
    )
    shared_folder_id: str = Field(
        ..., title="Shared Folder ID", json_schema_extra={"placeholder": "84528192421"}
    )
    member_emails: str = Field(
        ...,
        title="Member Emails",
        description="Comma-separated emails",
        json_schema_extra={"placeholder": "user1@example.com, user2@example.com"},
    )
    access_level: str = Field(
        "viewer",
        title="Access Level",
        json_schema_extra={
            "enum": ["viewer", "editor"],
            "enumNames": ["Viewer", "Editor"],
        },
    )


class DropboxRemoveFolderMemberConfig(BaseModel):
    """Remove a member from a shared folder."""

    operation: Literal["remove_shared_folder_member"] = Field(
        default="remove_shared_folder_member",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Shared Folder",
            "x-is-trigger": False,
            "x-display-name": "Remove Shared Folder Member",
        },
        title="Remove Shared Folder Member",
    )
    shared_folder_id: str = Field(
        ..., title="Shared Folder ID", json_schema_extra={"placeholder": "84528192421"}
    )
    member_email: str = Field(
        ..., title="Member Email", json_schema_extra={"placeholder": "user@example.com"}
    )
    leave_a_copy: bool = Field(False, title="Leave a Copy for Member")


class DropboxUpdateFolderMemberConfig(BaseModel):
    """Update a member's access level in a shared folder."""

    operation: Literal["update_shared_folder_member_access"] = Field(
        default="update_shared_folder_member_access",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Shared Folder",
            "x-is-trigger": False,
            "x-display-name": "Update Shared Folder Member Access",
        },
        title="Update Shared Folder Member Access",
    )
    shared_folder_id: str = Field(
        ..., title="Shared Folder ID", json_schema_extra={"placeholder": "84528192421"}
    )
    member_email: str = Field(
        ..., title="Member Email", json_schema_extra={"placeholder": "user@example.com"}
    )
    access_level: str = Field(
        ...,
        title="New Access Level",
        json_schema_extra={
            "enum": ["viewer", "editor"],
            "enumNames": ["Viewer", "Editor"],
        },
    )


class DropboxMountFolderConfig(BaseModel):
    """Mount a shared folder to your Dropbox."""

    operation: Literal["mount_shared_folder"] = Field(
        default="mount_shared_folder",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Shared Folder",
            "x-is-trigger": False,
            "x-display-name": "Mount Shared Folder",
        },
        title="Mount Shared Folder",
    )
    shared_folder_id: str = Field(
        ..., title="Shared Folder ID", json_schema_extra={"placeholder": "84528192421"}
    )


class DropboxUnmountFolderConfig(BaseModel):
    """Unmount a shared folder from your Dropbox."""

    operation: Literal["unmount_shared_folder"] = Field(
        default="unmount_shared_folder",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Shared Folder",
            "x-is-trigger": False,
            "x-display-name": "Unmount Shared Folder",
        },
        title="Unmount Shared Folder",
    )
    shared_folder_id: str = Field(
        ..., title="Shared Folder ID", json_schema_extra={"placeholder": "84528192421"}
    )


class DropboxUnshareFolderConfig(BaseModel):
    """Stop sharing a folder."""

    operation: Literal["unshare_folder"] = Field(
        default="unshare_folder",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Shared Folder",
            "x-is-trigger": False,
            "x-display-name": "Unshare Folder",
        },
        title="Unshare Folder",
    )
    shared_folder_id: str = Field(
        ..., title="Shared Folder ID", json_schema_extra={"placeholder": "84528192421"}
    )
    leave_a_copy: bool = Field(
        False, title="Leave a Copy", description="Keep a copy for current user"
    )


class DropboxGetFolderMetadataConfig(BaseModel):
    """Get metadata for a shared folder."""

    operation: Literal["get_shared_folder_metadata"] = Field(
        default="get_shared_folder_metadata",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Shared Folder",
            "x-is-trigger": False,
            "x-display-name": "Get Shared Folder Metadata",
        },
        title="Get Shared Folder Metadata",
    )
    shared_folder_id: str = Field(
        ..., title="Shared Folder ID", json_schema_extra={"placeholder": "84528192421"}
    )


class DropboxAddFileMemberConfig(BaseModel):
    """Share a file with specific users."""

    operation: Literal["share_file_with_members"] = Field(
        default="share_file_with_members",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File Sharing",
            "x-is-trigger": False,
            "x-display-name": "Share File with Members",
        },
        title="Share File with Members",
    )
    file_path: str = Field(
        ...,
        title="File Path",
        description="Path to file to share",
        json_schema_extra={"placeholder": "/Documents/report.pdf"},
    )
    member_emails: str = Field(
        ...,
        title="Member Emails",
        description="Comma-separated emails",
        json_schema_extra={"placeholder": "user1@example.com, user2@example.com"},
    )
    access_level: str = Field(
        "viewer",
        title="Access Level",
        json_schema_extra={
            "enum": ["viewer", "editor"],
            "enumNames": ["Viewer", "Editor"],
        },
    )


class DropboxRemoveFileMemberConfig(BaseModel):
    """Remove a member's access to a shared file."""

    operation: Literal["remove_file_member"] = Field(
        default="remove_file_member",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File Sharing",
            "x-is-trigger": False,
            "x-display-name": "Remove File Member",
        },
        title="Remove File Member",
    )
    file_id: str = Field(
        ...,
        title="File ID",
        json_schema_extra={"placeholder": "id:a4ayc_80_OEAAAAAAAAAXw"},
    )
    member_email: str = Field(
        ..., title="Member Email", json_schema_extra={"placeholder": "user@example.com"}
    )


class DropboxListFileMembersConfig(BaseModel):
    """List all members who have access to a file."""

    operation: Literal["list_file_members"] = Field(
        default="list_file_members",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File Sharing",
            "x-is-trigger": False,
            "x-display-name": "List File Members",
        },
        title="List File Members",
    )
    file_id: str = Field(
        ...,
        title="File ID",
        json_schema_extra={"placeholder": "id:a4ayc_80_OEAAAAAAAAAXw"},
    )


# ============================================================================
# Operation Configs - Account API
# ============================================================================


class DropboxGetAccountInfoConfig(BaseModel):
    """Get current account information."""

    operation: Literal["get_account_info"] = Field(
        default="get_account_info",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Get Account Info",
        },
        title="Get Account Info",
    )


class DropboxGetSpaceUsageConfig(BaseModel):
    """Get account space usage and quota."""

    operation: Literal["get_account_space_usage"] = Field(
        default="get_account_space_usage",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Get Account Space Usage",
        },
        title="Get Account Space Usage",
    )


# ============================================================================
# Operation Configs - File Requests API
# ============================================================================


class DropboxCreateFileRequestConfig(BaseModel):
    """Create a file request to collect files from others."""

    operation: Literal["create_file_request"] = Field(
        default="create_file_request",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File Request",
            "x-is-trigger": False,
            "x-display-name": "Create File Request",
        },
        title="Create File Request",
    )
    title: str = Field(
        ...,
        title="Request Title",
        description="Title for the file request",
        json_schema_extra={"placeholder": "Submit your documents"},
    )
    destination: str = Field(
        ...,
        title="Destination Folder",
        description="Where uploaded files will be saved",
        json_schema_extra={"placeholder": "/File Requests/Documents"},
    )
    deadline: Optional[str] = Field(
        None,
        title="Deadline",
        description="Deadline for file submission (ISO 8601)",
        json_schema_extra={"placeholder": "2025-12-31T23:59:59Z"},
    )
    open: bool = Field(True, title="Open Request", description="Allow file submissions")


class DropboxListFileRequestsConfig(BaseModel):
    """List all file requests."""

    operation: Literal["list_file_requests"] = Field(
        default="list_file_requests",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File Request",
            "x-is-trigger": False,
            "x-display-name": "List File Requests",
        },
        title="List File Requests",
    )


class DropboxCountFileRequestsConfig(BaseModel):
    """Get count of file requests."""

    operation: Literal["count_file_requests"] = Field(
        default="count_file_requests",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File Request",
            "x-is-trigger": False,
            "x-display-name": "Count File Requests",
        },
        title="Count File Requests",
    )


# ============================================================================
# Operation Configs - File Properties API (Custom Metadata)
# ============================================================================


class DropboxAddPropertiesConfig(BaseModel):
    """Add custom properties to a file."""

    operation: Literal["add_custom_properties_to_file"] = Field(
        default="add_custom_properties_to_file",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File Sharing",
            "x-is-trigger": False,
            "x-display-name": "Add Custom Properties to File",
        },
        title="Add Custom Properties to File",
    )
    path: str = Field(
        ..., title="File Path", json_schema_extra={"placeholder": "/Documents/file.pdf"}
    )
    property_groups: str = Field(
        ...,
        title="Properties (JSON)",
        description="JSON object of custom properties",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": '{"project_id": "123", "status": "active"}',
        },
    )


class DropboxUpdatePropertiesConfig(BaseModel):
    """Update custom properties on a file."""

    operation: Literal["update_custom_properties"] = Field(
        default="update_custom_properties",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File Sharing",
            "x-is-trigger": False,
            "x-display-name": "Update Custom Properties",
        },
        title="Update Custom Properties",
    )
    path: str = Field(
        ..., title="File Path", json_schema_extra={"placeholder": "/Documents/file.pdf"}
    )
    property_groups: str = Field(
        ...,
        title="Updated Properties (JSON)",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": '{"status": "completed"}',
        },
    )


class DropboxRemovePropertiesConfig(BaseModel):
    """Remove custom properties from a file."""

    operation: Literal["remove_custom_properties"] = Field(
        default="remove_custom_properties",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "File Sharing",
            "x-is-trigger": False,
            "x-display-name": "Remove Custom Properties",
        },
        title="Remove Custom Properties",
    )
    path: str = Field(
        ..., title="File Path", json_schema_extra={"placeholder": "/Documents/file.pdf"}
    )
    property_template_id: str = Field(
        ...,
        title="Property Template ID",
        json_schema_extra={"placeholder": "ptid:1a5n2i6d3OYEAAAAAAAAAYa"},
    )


# ============================================================================
# Union Config
# ============================================================================

DropboxConfig = Annotated[
    Union[
        # Files operations (17 total)
        DropboxUploadFileConfig,
        DropboxUploadLargeFileConfig,
        DropboxDownloadFileConfig,
        DropboxListFolderConfig,
        DropboxCreateFolderConfig,
        DropboxDeleteConfig,
        DropboxCopyConfig,
        DropboxMoveConfig,
        DropboxSearchConfig,
        DropboxGetMetadataConfig,
        DropboxGetTemporaryLinkConfig,
        DropboxListRevisionsConfig,
        DropboxRestoreConfig,
        DropboxDownloadZipConfig,
        DropboxGetThumbnailConfig,
        DropboxSaveUrlConfig,
        # Sharing operations (15 total)
        DropboxCreateSharedLinkConfig,
        DropboxListSharedLinksConfig,
        DropboxRevokeSharedLinkConfig,
        DropboxShareFolderConfig,
        DropboxListFolderMembersConfig,
        DropboxAddFolderMemberConfig,
        DropboxRemoveFolderMemberConfig,
        DropboxUpdateFolderMemberConfig,
        DropboxMountFolderConfig,
        DropboxUnmountFolderConfig,
        DropboxUnshareFolderConfig,
        DropboxGetFolderMetadataConfig,
        DropboxAddFileMemberConfig,
        DropboxRemoveFileMemberConfig,
        DropboxListFileMembersConfig,
        # Account operations (2 total)
        DropboxGetAccountInfoConfig,
        DropboxGetSpaceUsageConfig,
        # File requests (6 total)
        DropboxCreateFileRequestConfig,
        DropboxListFileRequestsConfig,
        DropboxGetFileRequestConfig,
        DropboxUpdateFileRequestConfig,
        DropboxDeleteFileRequestConfig,
        DropboxCountFileRequestsConfig,
        # File properties (3 total)
        DropboxAddPropertiesConfig,
        DropboxUpdatePropertiesConfig,
        DropboxRemovePropertiesConfig,
    ],
    Discriminator("operation"),
]


# ============================================================================
# Full Node Config
# ============================================================================


class DropboxNodeConfig(NodeConfig[DropboxConfig, DropboxCredential]):
    """Complete Dropbox node configuration."""

    pass


# ============================================================================
# Node Implementation
# ============================================================================


class DropboxNode(WorkflowNode):
    """Dropbox workflow node - comprehensive file storage automation."""

    edit_examples = [
        "Upload daily sales report to /Reports/Q4 and share read-only link",
        "Create backup folder, delete old files over 90 days, list remaining",
        "Search for invoices and create shared folder for accountant review",
        "Download all CSV files from /Data, batch rename with timestamp",
        "Move completed projects to /Archive and revoke team share access",
        "Create /Client-Files folder and generate 30-day expiring share link",
        "Copy template folder to /Templates/[ProjectName] and update metadata",
    ]

    # Dropbox API endpoints
    API_BASE = "https://api.dropboxapi.com/2"
    CONTENT_BASE = "https://content.dropboxapi.com/2"

    scope_registry = DROPBOX_SCOPES
    connection_evidence = ConnectionEvidence(
        noun="account",
        identity_operation="get_account_info",
    )
    @classmethod
    def get_config_model(cls) -> Optional[Type]:
        return DropboxNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute Dropbox operation."""
        config = self.config
        if not config or not isinstance(config, DropboxNodeConfig):
            raise ValueError("Configuration required")

        credentials = config.credentials
        if not credentials:
            raise ValueError(
                "Dropbox credentials required. Connect your Dropbox account in the credentials tab."
            )

        # Get fresh access token (refresh if needed)
        access_token = await self._ensure_fresh_token(credentials)

        # Route to operation handler
        op_config = config.config
        operation = op_config.operation

        # Files operations
        if operation == "upload_file":
            return await self._upload_file(op_config, access_token)
        elif operation == "upload_large_file_with_sessions":
            return await self._upload_large_file(op_config, access_token)
        elif operation == "download_file":
            return await self._download_file(op_config, access_token)
        elif operation == "list_folder_contents":
            return await self._list_folder(op_config, access_token)
        elif operation == "create_folder":
            return await self._create_folder(op_config, access_token)
        elif operation == "delete_file_or_folder":
            return await self._delete(op_config, access_token)
        elif operation == "copy_file_or_folder":
            return await self._copy(op_config, access_token)
        elif operation == "move_file_or_folder":
            return await self._move(op_config, access_token)
        elif operation == "search_files_and_folders":
            return await self._search(op_config, access_token)
        elif operation == "get_file_or_folder_metadata":
            return await self._get_metadata(op_config, access_token)
        # Sharing operations
        elif operation == "create_shared_link":
            return await self._create_shared_link(op_config, access_token)
        elif operation == "list_shared_links":
            return await self._list_shared_links(op_config, access_token)
        elif operation == "revoke_shared_link":
            return await self._revoke_shared_link(op_config, access_token)
        elif operation == "share_folder_with_members":
            return await self._share_folder(op_config, access_token)
        # Account operations
        elif operation == "get_account_info":
            return await self._get_account_info(op_config, access_token)
        elif operation == "get_account_space_usage":
            return await self._get_space_usage(op_config, access_token)
        # File requests
        elif operation == "create_file_request":
            return await self._create_file_request(op_config, access_token)
        elif operation == "list_file_requests":
            return await self._list_file_requests(op_config, access_token)
        elif operation == "get_temporary_download_link":
            return await self._get_temporary_link(op_config, access_token)
        elif operation == "list_file_revisions":
            return await self._list_revisions(op_config, access_token)
        elif operation == "restore_file_to_revision":
            return await self._restore(op_config, access_token)
        elif operation == "list_shared_folder_members":
            return await self._list_folder_members(op_config, access_token)
        elif operation == "add_members_to_shared_folder":
            return await self._add_folder_member(op_config, access_token)
        elif operation == "remove_shared_folder_member":
            return await self._remove_folder_member(op_config, access_token)
        elif operation == "get_file_request":
            return await self._get_file_request(op_config, access_token)
        elif operation == "update_file_request":
            return await self._update_file_request(op_config, access_token)
        elif operation == "delete_file_request":
            return await self._delete_file_request(op_config, access_token)

        elif operation == "download_folder_as_zip":
            return await self._download_zip(op_config, access_token)
        elif operation == "get_file_thumbnail":
            return await self._get_thumbnail(op_config, access_token)
        elif operation == "save_url_to_dropbox":
            return await self._save_url(op_config, access_token)
        elif operation == "update_shared_folder_member_access":
            return await self._update_folder_member(op_config, access_token)
        elif operation == "mount_shared_folder":
            return await self._mount_folder(op_config, access_token)
        elif operation == "unmount_shared_folder":
            return await self._unmount_folder(op_config, access_token)
        elif operation == "unshare_folder":
            return await self._unshare_folder(op_config, access_token)
        elif operation == "get_shared_folder_metadata":
            return await self._get_folder_metadata(op_config, access_token)
        elif operation == "share_file_with_members":
            return await self._add_file_member(op_config, access_token)
        elif operation == "remove_file_member":
            return await self._remove_file_member(op_config, access_token)
        elif operation == "list_file_members":
            return await self._list_file_members(op_config, access_token)
        elif operation == "count_file_requests":
            return await self._count_file_requests(op_config, access_token)
        elif operation == "add_custom_properties_to_file":
            return await self._add_properties(op_config, access_token)
        elif operation == "update_custom_properties":
            return await self._update_properties(op_config, access_token)
        elif operation == "remove_custom_properties":
            return await self._remove_properties(op_config, access_token)

        raise ValueError(f"Unknown operation: {operation}")

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        """Refresh an expiring OAuth token at credential load (dropdowns,
        trigger registration). No-op for non-rotating credentials (API keys /
        offline / non-expiring tokens)."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.dropbox_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token,
            provider="dropbox",
        )

    async def _ensure_fresh_token(self, credentials: DropboxOAuthCredential) -> str:
        """Return a valid Dropbox access token, refreshing + persisting if expired.

        Dropbox access tokens are short-lived (~4h); the long-lived refresh
        token is exchanged via the shared OAuth refresh helper.
        """
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.dropbox_oauth import refresh_access_token
        
        cred_dict = credentials.model_dump()
        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=cred_dict,
            refresh=refresh_access_token,
            provider="dropbox",
        )
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        if cred_dict.get("refresh_token"):
            credentials.refresh_token = cred_dict["refresh_token"]
        return token

    # ========================================================================
    # Files Operations
    # ========================================================================

    async def _upload_file(
        self, config: DropboxUploadFileConfig, token: str
    ) -> Dict[str, Any]:
        """Upload a file to Dropbox (max 150 MB)."""
        try:
            # Read file
            with open(config.local_file_path, "rb") as f:
                file_content = f.read()

            # Check file size
            file_size = len(file_content)
            if file_size > 150 * 1024 * 1024:  # 150 MB
                raise ValueError(
                    f"File too large ({file_size / 1024 / 1024:.1f} MB). "
                    "Use 'upload_large_file_with_sessions' operation for files over 150 MB."
                )

            # Prepare API request
            url = f"{self.CONTENT_BASE}/files/upload"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/octet-stream",
                "Dropbox-API-Arg": self._json_dumps(
                    {
                        "path": config.dropbox_path,
                        "mode": config.mode,
                        "autorename": config.autorename,
                        "mute": config.mute,
                    }
                ),
            }

            async with httpx.AsyncClient(timeout=300.0) as client:
                response = await client.post(url, headers=headers, content=file_content)
                response.raise_for_status()
                result = response.json()

            return {
                "status": "success",
                "message": f"File uploaded successfully to {config.dropbox_path}",
                "file": {
                    "name": result.get("name"),
                    "path_display": result.get("path_display"),
                    "id": result.get("id"),
                    "size": result.get("size"),
                    "server_modified": result.get("server_modified"),
                    "content_hash": result.get("content_hash"),
                },
            }

        except FileNotFoundError:
            raise ValueError(f"Local file not found: {config.local_file_path}")
        except httpx.HTTPStatusError as e:
            error_msg = await self._parse_error_response(e.response)
            raise ValueError(f"Dropbox API error: {error_msg}")
        except Exception as e:
            raise ValueError(f"Upload failed: {str(e)}")

    async def _upload_large_file(
        self, config: DropboxUploadLargeFileConfig, token: str
    ) -> Dict[str, Any]:
        """Upload large file using upload sessions (150 MB to 350 GB)."""
        try:
            file_size = os.path.getsize(config.local_file_path)
            chunk_size = config.chunk_size_mb * 1024 * 1024  # Convert MB to bytes

            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/octet-stream",
            }

            session_id = None
            offset = 0

            async with httpx.AsyncClient(timeout=300.0) as client:
                with open(config.local_file_path, "rb") as f:
                    # Start upload session with first chunk
                    chunk = f.read(chunk_size)
                    url = f"{self.CONTENT_BASE}/files/upload_session/start"
                    response = await client.post(url, headers=headers, content=chunk)
                    response.raise_for_status()
                    session_id = response.json()["session_id"]
                    offset = len(chunk)

                    # Upload remaining chunks
                    while offset < file_size:
                        chunk = f.read(chunk_size)

                        if offset + len(chunk) < file_size:
                            # Append chunk
                            url = f"{self.CONTENT_BASE}/files/upload_session/append_v2"
                            headers["Dropbox-API-Arg"] = self._json_dumps(
                                {"cursor": {"session_id": session_id, "offset": offset}}
                            )
                            response = await client.post(
                                url, headers=headers, content=chunk
                            )
                            response.raise_for_status()
                            offset += len(chunk)
                        else:
                            # Final chunk - finish session
                            url = f"{self.CONTENT_BASE}/files/upload_session/finish"
                            headers["Dropbox-API-Arg"] = self._json_dumps(
                                {
                                    "cursor": {
                                        "session_id": session_id,
                                        "offset": offset,
                                    },
                                    "commit": {
                                        "path": config.dropbox_path,
                                        "mode": config.mode,
                                    },
                                }
                            )
                            response = await client.post(
                                url, headers=headers, content=chunk
                            )
                            response.raise_for_status()
                            result = response.json()
                            offset += len(chunk)

            return {
                "status": "success",
                "message": f"Large file uploaded successfully ({file_size / 1024 / 1024:.1f} MB)",
                "file": {
                    "name": result.get("name"),
                    "path_display": result.get("path_display"),
                    "id": result.get("id"),
                    "size": result.get("size"),
                    "server_modified": result.get("server_modified"),
                },
            }

        except FileNotFoundError:
            raise ValueError(f"Local file not found: {config.local_file_path}")
        except httpx.HTTPStatusError as e:
            error_msg = await self._parse_error_response(e.response)
            raise ValueError(f"Dropbox API error: {error_msg}")
        except Exception as e:
            raise ValueError(f"Large file upload failed: {str(e)}")

    async def _download_file(
        self, config: DropboxDownloadFileConfig, token: str
    ) -> Dict[str, Any]:
        """Download a file from Dropbox."""
        try:
            url = f"{self.CONTENT_BASE}/files/download"
            headers = {
                "Authorization": f"Bearer {token}",
                "Dropbox-API-Arg": self._json_dumps({"path": config.dropbox_path}),
            }

            async with httpx.AsyncClient(timeout=300.0) as client:
                response = await client.post(url, headers=headers)
                response.raise_for_status()

                # Save file
                with open(config.local_file_path, "wb") as f:
                    f.write(response.content)

                # Get metadata from response header
                metadata_header = response.headers.get("Dropbox-API-Result", "{}")
                import json

                metadata = json.loads(metadata_header)

            return {
                "status": "success",
                "message": f"File downloaded to {config.local_file_path}",
                "file": {
                    "name": metadata.get("name"),
                    "size": metadata.get("size"),
                    "local_path": config.local_file_path,
                },
            }

        except httpx.HTTPStatusError as e:
            error_msg = await self._parse_error_response(e.response)
            raise ValueError(f"Dropbox API error: {error_msg}")
        except Exception as e:
            raise ValueError(f"Download failed: {str(e)}")

    async def _list_folder(
        self, config: DropboxListFolderConfig, token: str
    ) -> Dict[str, Any]:
        """List contents of a Dropbox folder."""
        try:
            url = f"{self.API_BASE}/files/list_folder"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            payload = {
                "path": config.path,
                "recursive": config.recursive,
                "include_deleted": config.include_deleted,
                "include_media_info": config.include_media_info,
                "limit": config.limit,
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()

            # Format entries
            entries = []
            for entry in result.get("entries", []):
                tag = entry.get(".tag")
                entry_data = {
                    "type": tag,
                    "name": entry.get("name"),
                    "path_display": entry.get("path_display"),
                    "id": entry.get("id"),
                }
                if tag == "file":
                    entry_data.update(
                        {
                            "size": entry.get("size"),
                            "server_modified": entry.get("server_modified"),
                            "content_hash": entry.get("content_hash"),
                        }
                    )
                entries.append(entry_data)

            return {
                "status": "success",
                "entries": entries,
                "count": len(entries),
                "has_more": result.get("has_more", False),
                "cursor": result.get("cursor"),
            }

        except httpx.HTTPStatusError as e:
            error_msg = await self._parse_error_response(e.response)
            raise ValueError(f"Dropbox API error: {error_msg}")
        except Exception as e:
            raise ValueError(f"List folder failed: {str(e)}")

    async def _create_folder(
        self, config: DropboxCreateFolderConfig, token: str
    ) -> Dict[str, Any]:
        """Create a new folder."""
        try:
            url = f"{self.API_BASE}/files/create_folder_v2"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            payload = {
                "path": config.path,
                "autorename": config.autorename,
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()

            metadata = result.get("metadata", {})
            return {
                "status": "success",
                "message": f"Folder created: {config.path}",
                "folder": {
                    "name": metadata.get("name"),
                    "path_display": metadata.get("path_display"),
                    "id": metadata.get("id"),
                },
            }

        except httpx.HTTPStatusError as e:
            error_msg = await self._parse_error_response(e.response)
            raise ValueError(f"Dropbox API error: {error_msg}")
        except Exception as e:
            raise ValueError(f"Create folder failed: {str(e)}")

    async def _delete(self, config: DropboxDeleteConfig, token: str) -> Dict[str, Any]:
        """Delete a file or folder."""
        try:
            url = f"{self.API_BASE}/files/delete_v2"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            payload = {"path": config.path}

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()

            metadata = result.get("metadata", {})
            return {
                "status": "success",
                "message": f"Deleted: {config.path}",
                "deleted": {
                    "name": metadata.get("name"),
                    "path_display": metadata.get("path_display"),
                },
            }

        except httpx.HTTPStatusError as e:
            error_msg = await self._parse_error_response(e.response)
            raise ValueError(f"Dropbox API error: {error_msg}")
        except Exception as e:
            raise ValueError(f"Delete failed: {str(e)}")

    async def _copy(self, config: DropboxCopyConfig, token: str) -> Dict[str, Any]:
        """Copy a file or folder."""
        try:
            url = f"{self.API_BASE}/files/copy_v2"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            payload = {
                "from_path": config.from_path,
                "to_path": config.to_path,
                "allow_shared_folder": config.allow_shared_folder,
                "autorename": config.autorename,
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()

            metadata = result.get("metadata", {})
            return {
                "status": "success",
                "message": f"Copied from {config.from_path} to {config.to_path}",
                "file": {
                    "name": metadata.get("name"),
                    "path_display": metadata.get("path_display"),
                    "id": metadata.get("id"),
                },
            }

        except httpx.HTTPStatusError as e:
            error_msg = await self._parse_error_response(e.response)
            raise ValueError(f"Dropbox API error: {error_msg}")
        except Exception as e:
            raise ValueError(f"Copy failed: {str(e)}")

    async def _move(self, config: DropboxMoveConfig, token: str) -> Dict[str, Any]:
        """Move a file or folder."""
        try:
            url = f"{self.API_BASE}/files/move_v2"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            payload = {
                "from_path": config.from_path,
                "to_path": config.to_path,
                "allow_shared_folder": config.allow_shared_folder,
                "autorename": config.autorename,
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()

            metadata = result.get("metadata", {})
            return {
                "status": "success",
                "message": f"Moved from {config.from_path} to {config.to_path}",
                "file": {
                    "name": metadata.get("name"),
                    "path_display": metadata.get("path_display"),
                    "id": metadata.get("id"),
                },
            }

        except httpx.HTTPStatusError as e:
            error_msg = await self._parse_error_response(e.response)
            raise ValueError(f"Dropbox API error: {error_msg}")
        except Exception as e:
            raise ValueError(f"Move failed: {str(e)}")

    async def _search(self, config: DropboxSearchConfig, token: str) -> Dict[str, Any]:
        """Search for files and folders."""
        try:
            url = f"{self.API_BASE}/files/search_v2"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }

            # Build search options
            options = {}
            if config.path:
                options["path"] = config.path
            if config.max_results:
                options["max_results"] = config.max_results
            if config.file_extensions:
                extensions = [ext.strip() for ext in config.file_extensions.split(",")]
                options["file_extensions"] = extensions

            payload = {
                "query": config.query,
                "options": options if options else None,
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()

            # Format matches
            matches = []
            for match in result.get("matches", []):
                metadata = match.get("metadata", {}).get("metadata", {})
                tag = metadata.get(".tag")
                match_data = {
                    "type": tag,
                    "name": metadata.get("name"),
                    "path_display": metadata.get("path_display"),
                    "id": metadata.get("id"),
                }
                if tag == "file":
                    match_data.update(
                        {
                            "size": metadata.get("size"),
                            "server_modified": metadata.get("server_modified"),
                        }
                    )
                matches.append(match_data)

            return {
                "status": "success",
                "matches": matches,
                "count": len(matches),
                "has_more": result.get("has_more", False),
            }

        except httpx.HTTPStatusError as e:
            error_msg = await self._parse_error_response(e.response)
            raise ValueError(f"Dropbox API error: {error_msg}")
        except Exception as e:
            raise ValueError(f"Search failed: {str(e)}")

    async def _get_metadata(
        self, config: DropboxGetMetadataConfig, token: str
    ) -> Dict[str, Any]:
        """Get metadata for a file or folder."""
        try:
            url = f"{self.API_BASE}/files/get_metadata"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            payload = {
                "path": config.path,
                "include_media_info": config.include_media_info,
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()

            tag = result.get(".tag")
            metadata = {
                "type": tag,
                "name": result.get("name"),
                "path_display": result.get("path_display"),
                "id": result.get("id"),
            }

            if tag == "file":
                metadata.update(
                    {
                        "size": result.get("size"),
                        "server_modified": result.get("server_modified"),
                        "client_modified": result.get("client_modified"),
                        "content_hash": result.get("content_hash"),
                    }
                )
                if config.include_media_info and "media_info" in result:
                    metadata["media_info"] = result["media_info"]

            return {"status": "success", "metadata": metadata}

        except httpx.HTTPStatusError as e:
            error_msg = await self._parse_error_response(e.response)
            raise ValueError(f"Dropbox API error: {error_msg}")
        except Exception as e:
            raise ValueError(f"Get metadata failed: {str(e)}")

    # ========================================================================
    # Sharing Operations
    # ========================================================================

    async def _create_shared_link(
        self, config: DropboxCreateSharedLinkConfig, token: str
    ) -> Dict[str, Any]:
        """Create a shared link."""
        try:
            url = f"{self.API_BASE}/sharing/create_shared_link_with_settings"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }

            # Build settings
            settings = {}
            if config.password:
                settings["link_password"] = config.password
            if config.expires:
                settings["expires"] = config.expires
            settings["requested_visibility"] = config.audience

            payload = {
                "path": config.path,
                "settings": settings,
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()

            return {
                "status": "success",
                "message": "Shared link created",
                "link": {
                    "url": result.get("url"),
                    "name": result.get("name"),
                    "path_lower": result.get("path_lower"),
                    "visibility": result.get("link_permissions", {})
                    .get("resolved_visibility", {})
                    .get(".tag"),
                    "expires": result.get("expires"),
                },
            }

        except httpx.HTTPStatusError as e:
            error_msg = await self._parse_error_response(e.response)
            raise ValueError(f"Dropbox API error: {error_msg}")
        except Exception as e:
            raise ValueError(f"Create shared link failed: {str(e)}")

    async def _list_shared_links(
        self, config: DropboxListSharedLinksConfig, token: str
    ) -> Dict[str, Any]:
        """List shared links."""
        try:
            url = f"{self.API_BASE}/sharing/list_shared_links"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }

            payload = {}
            if config.path:
                payload["path"] = config.path
            if config.direct_only:
                payload["direct_only"] = True

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()

            links = []
            for link in result.get("links", []):
                links.append(
                    {
                        "url": link.get("url"),
                        "name": link.get("name"),
                        "path_lower": link.get("path_lower"),
                        "id": link.get("id"),
                    }
                )

            return {
                "status": "success",
                "links": links,
                "count": len(links),
                "has_more": result.get("has_more", False),
            }

        except httpx.HTTPStatusError as e:
            error_msg = await self._parse_error_response(e.response)
            raise ValueError(f"Dropbox API error: {error_msg}")
        except Exception as e:
            raise ValueError(f"List shared links failed: {str(e)}")

    async def _revoke_shared_link(
        self, config: DropboxRevokeSharedLinkConfig, token: str
    ) -> Dict[str, Any]:
        """Revoke a shared link."""
        try:
            url = f"{self.API_BASE}/sharing/revoke_shared_link"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            payload = {"url": config.url}

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()

            return {
                "status": "success",
                "message": f"Shared link revoked: {config.url}",
            }

        except httpx.HTTPStatusError as e:
            error_msg = await self._parse_error_response(e.response)
            raise ValueError(f"Dropbox API error: {error_msg}")
        except Exception as e:
            raise ValueError(f"Revoke shared link failed: {str(e)}")

    async def _share_folder(
        self, config: DropboxShareFolderConfig, token: str
    ) -> Dict[str, Any]:
        """Share a folder with users."""
        try:
            # First, share the folder
            url = f"{self.API_BASE}/sharing/share_folder"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            payload = {
                "path": config.path,
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()

                shared_folder_id = result.get("shared_folder_id")

                # Add members
                emails = [email.strip() for email in config.member_emails.split(",")]
                members = []
                for email in emails:
                    members.append(
                        {
                            "member": {".tag": "email", "email": email},
                            "access_level": {".tag": config.access_level},
                        }
                    )

                url = f"{self.API_BASE}/sharing/add_folder_member"
                payload = {
                    "shared_folder_id": shared_folder_id,
                    "members": members,
                    "quiet": not config.send_notification,
                }

                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()

            return {
                "status": "success",
                "message": f"Folder shared with {len(emails)} member(s)",
                "shared_folder_id": shared_folder_id,
                "members_added": emails,
            }

        except httpx.HTTPStatusError as e:
            error_msg = await self._parse_error_response(e.response)
            raise ValueError(f"Dropbox API error: {error_msg}")
        except Exception as e:
            raise ValueError(f"Share folder failed: {str(e)}")

    # ========================================================================
    # Account Operations
    # ========================================================================

    async def _get_account_info(
        self, config: DropboxGetAccountInfoConfig, token: str
    ) -> Dict[str, Any]:
        """Get current account information."""
        try:
            url = f"{self.API_BASE}/users/get_current_account"
            headers = {
                "Authorization": f"Bearer {token}",
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers)
                response.raise_for_status()
                result = response.json()

            return {
                "status": "success",
                "account": {
                    "account_id": result.get("account_id"),
                    "name": {
                        "display_name": result.get("name", {}).get("display_name"),
                        "given_name": result.get("name", {}).get("given_name"),
                        "surname": result.get("name", {}).get("surname"),
                    },
                    "email": result.get("email"),
                    "email_verified": result.get("email_verified"),
                    "disabled": result.get("disabled"),
                    "country": result.get("country"),
                    "locale": result.get("locale"),
                    "account_type": result.get("account_type", {}).get(".tag"),
                },
            }

        except httpx.HTTPStatusError as e:
            error_msg = await self._parse_error_response(e.response)
            raise ValueError(f"Dropbox API error: {error_msg}")
        except Exception as e:
            raise ValueError(f"Get account info failed: {str(e)}")

    async def _get_space_usage(
        self, config: DropboxGetSpaceUsageConfig, token: str
    ) -> Dict[str, Any]:
        """Get account space usage."""
        try:
            url = f"{self.API_BASE}/users/get_space_usage"
            headers = {
                "Authorization": f"Bearer {token}",
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers)
                response.raise_for_status()
                result = response.json()

            used = result.get("used", 0)
            allocation = result.get("allocation", {})
            allocated = allocation.get("allocated", 0)

            return {
                "status": "success",
                "space": {
                    "used_bytes": used,
                    "used_mb": round(used / 1024 / 1024, 2),
                    "used_gb": round(used / 1024 / 1024 / 1024, 2),
                    "allocated_bytes": allocated,
                    "allocated_mb": round(allocated / 1024 / 1024, 2),
                    "allocated_gb": round(allocated / 1024 / 1024 / 1024, 2),
                    "percent_used": round((used / allocated * 100), 2)
                    if allocated > 0
                    else 0,
                    "allocation_type": allocation.get(".tag"),
                },
            }

        except httpx.HTTPStatusError as e:
            error_msg = await self._parse_error_response(e.response)
            raise ValueError(f"Dropbox API error: {error_msg}")
        except Exception as e:
            raise ValueError(f"Get space usage failed: {str(e)}")

    # ========================================================================
    # File Requests Operations
    # ========================================================================

    async def _create_file_request(
        self, config: DropboxCreateFileRequestConfig, token: str
    ) -> Dict[str, Any]:
        """Create a file request."""
        try:
            url = f"{self.API_BASE}/file_requests/create"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }

            payload = {
                "title": config.title,
                "destination": config.destination,
                "open": config.open,
            }
            if config.deadline:
                payload["deadline"] = {"deadline": config.deadline}

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()

            return {
                "status": "success",
                "message": "File request created",
                "file_request": {
                    "id": result.get("id"),
                    "url": result.get("url"),
                    "title": result.get("title"),
                    "destination": result.get("destination"),
                    "is_open": result.get("is_open"),
                    "file_count": result.get("file_count"),
                },
            }

        except httpx.HTTPStatusError as e:
            error_msg = await self._parse_error_response(e.response)
            raise ValueError(f"Dropbox API error: {error_msg}")
        except Exception as e:
            raise ValueError(f"Create file request failed: {str(e)}")

    async def _list_file_requests(
        self, config: DropboxListFileRequestsConfig, token: str
    ) -> Dict[str, Any]:
        """List all file requests."""
        try:
            url = f"{self.API_BASE}/file_requests/list_v2"
            headers = {
                "Authorization": f"Bearer {token}",
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers)
                response.raise_for_status()
                result = response.json()

            file_requests = []
            for fr in result.get("file_requests", []):
                file_requests.append(
                    {
                        "id": fr.get("id"),
                        "url": fr.get("url"),
                        "title": fr.get("title"),
                        "destination": fr.get("destination"),
                        "is_open": fr.get("is_open"),
                        "file_count": fr.get("file_count"),
                    }
                )

            return {
                "status": "success",
                "file_requests": file_requests,
                "count": len(file_requests),
            }

        except httpx.HTTPStatusError as e:
            error_msg = await self._parse_error_response(e.response)
            raise ValueError(f"Dropbox API error: {error_msg}")
        except Exception as e:
            raise ValueError(f"List file requests failed: {str(e)}")

    # ========================================================================
    # Additional Files Operations
    # ========================================================================

    async def _get_temporary_link(
        self, config: DropboxGetTemporaryLinkConfig, token: str
    ) -> Dict[str, Any]:
        """Get a temporary download link for a file."""
        try:
            url = f"{self.API_BASE}/files/get_temporary_link"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            payload = {"path": config.path}

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()

            return {
                "status": "success",
                "link": result.get("link"),
                "metadata": {
                    "name": result.get("metadata", {}).get("name"),
                    "path_display": result.get("metadata", {}).get("path_display"),
                    "size": result.get("metadata", {}).get("size"),
                },
            }

        except httpx.HTTPStatusError as e:
            error_msg = await self._parse_error_response(e.response)
            raise ValueError(f"Dropbox API error: {error_msg}")
        except Exception as e:
            raise ValueError(f"Get temporary link failed: {str(e)}")

    async def _list_revisions(
        self, config: DropboxListRevisionsConfig, token: str
    ) -> Dict[str, Any]:
        """List file revisions."""
        try:
            url = f"{self.API_BASE}/files/list_revisions"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            payload = {
                "path": config.path,
                "limit": config.limit,
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()

            revisions = []
            for rev in result.get("entries", []):
                revisions.append(
                    {
                        "rev": rev.get("rev"),
                        "size": rev.get("size"),
                        "server_modified": rev.get("server_modified"),
                        "client_modified": rev.get("client_modified"),
                    }
                )

            return {
                "status": "success",
                "revisions": revisions,
                "count": len(revisions),
            }

        except httpx.HTTPStatusError as e:
            error_msg = await self._parse_error_response(e.response)
            raise ValueError(f"Dropbox API error: {error_msg}")
        except Exception as e:
            raise ValueError(f"List revisions failed: {str(e)}")

    async def _restore(
        self, config: DropboxRestoreConfig, token: str
    ) -> Dict[str, Any]:
        """Restore a file to a previous revision."""
        try:
            url = f"{self.API_BASE}/files/restore"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            payload = {
                "path": config.path,
                "rev": config.rev,
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()

            return {
                "status": "success",
                "message": f"File restored to revision {config.rev}",
                "file": {
                    "name": result.get("name"),
                    "path_display": result.get("path_display"),
                    "rev": result.get("rev"),
                    "size": result.get("size"),
                },
            }

        except httpx.HTTPStatusError as e:
            error_msg = await self._parse_error_response(e.response)
            raise ValueError(f"Dropbox API error: {error_msg}")
        except Exception as e:
            raise ValueError(f"Restore failed: {str(e)}")

    # ========================================================================
    # Additional Sharing Operations
    # ========================================================================

    async def _list_folder_members(
        self, config: DropboxListFolderMembersConfig, token: str
    ) -> Dict[str, Any]:
        """List members of a shared folder."""
        try:
            url = f"{self.API_BASE}/sharing/list_folder_members"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            payload = {"shared_folder_id": config.shared_folder_id}

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()

            users = []
            for user in result.get("users", []):
                users.append(
                    {
                        "email": user.get("user", {}).get("email"),
                        "display_name": user.get("user", {}).get("display_name"),
                        "access_level": user.get("access_type", {}).get(".tag"),
                    }
                )

            return {
                "status": "success",
                "members": users,
                "count": len(users),
            }

        except httpx.HTTPStatusError as e:
            error_msg = await self._parse_error_response(e.response)
            raise ValueError(f"Dropbox API error: {error_msg}")
        except Exception as e:
            raise ValueError(f"List folder members failed: {str(e)}")

    async def _add_folder_member(
        self, config: DropboxAddFolderMemberConfig, token: str
    ) -> Dict[str, Any]:
        """Add members to a shared folder."""
        try:
            emails = [email.strip() for email in config.member_emails.split(",")]
            members = []
            for email in emails:
                members.append(
                    {
                        "member": {".tag": "email", "email": email},
                        "access_level": {".tag": config.access_level},
                    }
                )

            url = f"{self.API_BASE}/sharing/add_folder_member"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            payload = {
                "shared_folder_id": config.shared_folder_id,
                "members": members,
                "quiet": False,
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()

            return {
                "status": "success",
                "message": f"Added {len(emails)} member(s) to shared folder",
                "members_added": emails,
            }

        except httpx.HTTPStatusError as e:
            error_msg = await self._parse_error_response(e.response)
            raise ValueError(f"Dropbox API error: {error_msg}")
        except Exception as e:
            raise ValueError(f"Add folder member failed: {str(e)}")

    async def _remove_folder_member(
        self, config: DropboxRemoveFolderMemberConfig, token: str
    ) -> Dict[str, Any]:
        """Remove a member from a shared folder."""
        try:
            url = f"{self.API_BASE}/sharing/remove_folder_member"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            payload = {
                "shared_folder_id": config.shared_folder_id,
                "member": {".tag": "email", "email": config.member_email},
                "leave_a_copy": config.leave_a_copy,
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()

            return {
                "status": "success",
                "message": f"Removed {config.member_email} from shared folder",
            }

        except httpx.HTTPStatusError as e:
            error_msg = await self._parse_error_response(e.response)
            raise ValueError(f"Dropbox API error: {error_msg}")
        except Exception as e:
            raise ValueError(f"Remove folder member failed: {str(e)}")

    # ========================================================================
    # Additional File Requests Operations
    # ========================================================================

    async def _get_file_request(
        self, config: DropboxGetFileRequestConfig, token: str
    ) -> Dict[str, Any]:
        """Get details of a file request."""
        try:
            url = f"{self.API_BASE}/file_requests/get"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            payload = {"id": config.file_request_id}

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()

            return {
                "status": "success",
                "file_request": {
                    "id": result.get("id"),
                    "url": result.get("url"),
                    "title": result.get("title"),
                    "destination": result.get("destination"),
                    "is_open": result.get("is_open"),
                    "file_count": result.get("file_count"),
                },
            }

        except httpx.HTTPStatusError as e:
            error_msg = await self._parse_error_response(e.response)
            raise ValueError(f"Dropbox API error: {error_msg}")
        except Exception as e:
            raise ValueError(f"Get file request failed: {str(e)}")

    async def _update_file_request(
        self, config: DropboxUpdateFileRequestConfig, token: str
    ) -> Dict[str, Any]:
        """Update a file request."""
        try:
            url = f"{self.API_BASE}/file_requests/update"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }

            payload = {"id": config.file_request_id}
            if config.title is not None:
                payload["title"] = config.title
            if config.deadline is not None:
                payload["deadline"] = {"deadline": config.deadline}
            if config.open is not None:
                payload["open"] = config.open

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()

            return {
                "status": "success",
                "message": "File request updated",
                "file_request": {
                    "id": result.get("id"),
                    "url": result.get("url"),
                    "title": result.get("title"),
                    "is_open": result.get("is_open"),
                },
            }

        except httpx.HTTPStatusError as e:
            error_msg = await self._parse_error_response(e.response)
            raise ValueError(f"Dropbox API error: {error_msg}")
        except Exception as e:
            raise ValueError(f"Update file request failed: {str(e)}")

    async def _delete_file_request(
        self, config: DropboxDeleteFileRequestConfig, token: str
    ) -> Dict[str, Any]:
        """Delete a file request."""
        try:
            url = f"{self.API_BASE}/file_requests/delete"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            payload = {"ids": [config.file_request_id]}

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()

            return {
                "status": "success",
                "message": f"File request {config.file_request_id} deleted",
            }

        except httpx.HTTPStatusError as e:
            error_msg = await self._parse_error_response(e.response)
            raise ValueError(f"Dropbox API error: {error_msg}")
        except Exception as e:
            raise ValueError(f"Delete file request failed: {str(e)}")

    # ========================================================================
    # Additional Files Operations - Extended
    # ========================================================================

    async def _download_zip(
        self, config: DropboxDownloadZipConfig, token: str
    ) -> Dict[str, Any]:
        """Download a folder as a ZIP archive."""
        try:
            url = f"{self.CONTENT_BASE}/files/download_zip"
            headers = {
                "Authorization": f"Bearer {token}",
                "Dropbox-API-Arg": self._json_dumps({"path": config.path}),
            }

            async with httpx.AsyncClient(
                timeout=600.0
            ) as client:  # Longer timeout for ZIP
                response = await client.post(url, headers=headers)
                response.raise_for_status()

                # Save ZIP file
                with open(config.local_save_path, "wb") as f:
                    f.write(response.content)

                # Get metadata from response header
                import json

                metadata_header = response.headers.get("Dropbox-API-Result", "{}")
                metadata = json.loads(metadata_header)

            return {
                "status": "success",
                "message": f"Folder downloaded as ZIP to {config.local_save_path}",
                "zip": {
                    "name": metadata.get("metadata", {}).get("name"),
                    "local_path": config.local_save_path,
                    "size": len(response.content),
                },
            }

        except httpx.HTTPStatusError as e:
            error_msg = await self._parse_error_response(e.response)
            raise ValueError(f"Dropbox API error: {error_msg}")
        except Exception as e:
            raise ValueError(f"Download ZIP failed: {str(e)}")

    async def _get_thumbnail(
        self, config: DropboxGetThumbnailConfig, token: str
    ) -> Dict[str, Any]:
        """Get thumbnail for an image file."""
        try:
            url = f"{self.CONTENT_BASE}/files/get_thumbnail_v2"
            headers = {
                "Authorization": f"Bearer {token}",
                "Dropbox-API-Arg": self._json_dumps(
                    {
                        "resource": {".tag": "path", "path": config.path},
                        "format": {".tag": config.format},
                        "size": {".tag": config.size},
                    }
                ),
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers)
                response.raise_for_status()

                # Save thumbnail
                with open(config.local_save_path, "wb") as f:
                    f.write(response.content)

            return {
                "status": "success",
                "message": f"Thumbnail saved to {config.local_save_path}",
                "thumbnail": {
                    "local_path": config.local_save_path,
                    "format": config.format,
                    "size": config.size,
                },
            }

        except httpx.HTTPStatusError as e:
            error_msg = await self._parse_error_response(e.response)
            raise ValueError(f"Dropbox API error: {error_msg}")
        except Exception as e:
            raise ValueError(f"Get thumbnail failed: {str(e)}")

    async def _save_url(
        self, config: DropboxSaveUrlConfig, token: str
    ) -> Dict[str, Any]:
        """Save a URL's content directly to Dropbox."""
        try:
            url = f"{self.API_BASE}/files/save_url"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            payload = {
                "path": config.path,
                "url": config.url,
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()

            # Result contains async_job_id - need to check status
            async_job_id = result.get("async_job_id")
            if async_job_id:
                return {
                    "status": "success",
                    "message": f"URL save initiated for {config.url}",
                    "async_job_id": async_job_id,
                    "note": "URL is being downloaded by Dropbox. Check job status for completion.",
                }
            else:
                # Immediate completion
                return {
                    "status": "success",
                    "message": f"URL saved to {config.path}",
                    "file": result,
                }

        except httpx.HTTPStatusError as e:
            error_msg = await self._parse_error_response(e.response)
            raise ValueError(f"Dropbox API error: {error_msg}")
        except Exception as e:
            raise ValueError(f"Save URL failed: {str(e)}")

    # ========================================================================
    # Additional Sharing Operations - Extended
    # ========================================================================

    async def _update_folder_member(
        self, config: DropboxUpdateFolderMemberConfig, token: str
    ) -> Dict[str, Any]:
        """Update a member's access level in a shared folder."""
        try:
            url = f"{self.API_BASE}/sharing/update_folder_member"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            payload = {
                "shared_folder_id": config.shared_folder_id,
                "member": {".tag": "email", "email": config.member_email},
                "access_level": {".tag": config.access_level},
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()

            return {
                "status": "success",
                "message": f"Updated {config.member_email} access to {config.access_level}",
            }

        except httpx.HTTPStatusError as e:
            error_msg = await self._parse_error_response(e.response)
            raise ValueError(f"Dropbox API error: {error_msg}")
        except Exception as e:
            raise ValueError(f"Update folder member failed: {str(e)}")

    async def _mount_folder(
        self, config: DropboxMountFolderConfig, token: str
    ) -> Dict[str, Any]:
        """Mount a shared folder to your Dropbox."""
        try:
            url = f"{self.API_BASE}/sharing/mount_folder"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            payload = {"shared_folder_id": config.shared_folder_id}

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()

            return {
                "status": "success",
                "message": f"Shared folder mounted",
                "folder": {
                    "name": result.get("name"),
                    "path_lower": result.get("path_lower"),
                    "shared_folder_id": result.get("shared_folder_id"),
                },
            }

        except httpx.HTTPStatusError as e:
            error_msg = await self._parse_error_response(e.response)
            raise ValueError(f"Dropbox API error: {error_msg}")
        except Exception as e:
            raise ValueError(f"Mount folder failed: {str(e)}")

    async def _unmount_folder(
        self, config: DropboxUnmountFolderConfig, token: str
    ) -> Dict[str, Any]:
        """Unmount a shared folder from your Dropbox."""
        try:
            url = f"{self.API_BASE}/sharing/unmount_folder"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            payload = {"shared_folder_id": config.shared_folder_id}

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()

            return {
                "status": "success",
                "message": f"Shared folder unmounted: {config.shared_folder_id}",
            }

        except httpx.HTTPStatusError as e:
            error_msg = await self._parse_error_response(e.response)
            raise ValueError(f"Dropbox API error: {error_msg}")
        except Exception as e:
            raise ValueError(f"Unmount folder failed: {str(e)}")

    async def _unshare_folder(
        self, config: DropboxUnshareFolderConfig, token: str
    ) -> Dict[str, Any]:
        """Stop sharing a folder."""
        try:
            url = f"{self.API_BASE}/sharing/unshare_folder"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            payload = {
                "shared_folder_id": config.shared_folder_id,
                "leave_a_copy": config.leave_a_copy,
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()

            return {
                "status": "success",
                "message": f"Folder unshared: {config.shared_folder_id}",
            }

        except httpx.HTTPStatusError as e:
            error_msg = await self._parse_error_response(e.response)
            raise ValueError(f"Dropbox API error: {error_msg}")
        except Exception as e:
            raise ValueError(f"Unshare folder failed: {str(e)}")

    async def _get_folder_metadata(
        self, config: DropboxGetFolderMetadataConfig, token: str
    ) -> Dict[str, Any]:
        """Get metadata for a shared folder."""
        try:
            url = f"{self.API_BASE}/sharing/get_folder_metadata"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            payload = {"shared_folder_id": config.shared_folder_id}

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()

            return {
                "status": "success",
                "metadata": {
                    "shared_folder_id": result.get("shared_folder_id"),
                    "name": result.get("name"),
                    "path_lower": result.get("path_lower"),
                    "access_type": result.get("access_type", {}).get(".tag"),
                    "is_team_folder": result.get("is_team_folder"),
                    "policy": result.get("policy"),
                },
            }

        except httpx.HTTPStatusError as e:
            error_msg = await self._parse_error_response(e.response)
            raise ValueError(f"Dropbox API error: {error_msg}")
        except Exception as e:
            raise ValueError(f"Get folder metadata failed: {str(e)}")

    async def _add_file_member(
        self, config: DropboxAddFileMemberConfig, token: str
    ) -> Dict[str, Any]:
        """Share a file with specific users."""
        try:
            emails = [email.strip() for email in config.member_emails.split(",")]
            members = []
            for email in emails:
                members.append(
                    {
                        "member": {".tag": "email", "email": email},
                        "access_level": {".tag": config.access_level},
                    }
                )

            url = f"{self.API_BASE}/sharing/add_file_member"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            payload = {
                "file": config.file_path,
                "members": members,
                "quiet": False,
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()

            return {
                "status": "success",
                "message": f"Shared file with {len(emails)} member(s)",
                "members_added": emails,
            }

        except httpx.HTTPStatusError as e:
            error_msg = await self._parse_error_response(e.response)
            raise ValueError(f"Dropbox API error: {error_msg}")
        except Exception as e:
            raise ValueError(f"Add file member failed: {str(e)}")

    async def _remove_file_member(
        self, config: DropboxRemoveFileMemberConfig, token: str
    ) -> Dict[str, Any]:
        """Remove a member's access to a shared file."""
        try:
            url = f"{self.API_BASE}/sharing/remove_file_member_2"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            payload = {
                "file": config.file_id,
                "member": {".tag": "email", "email": config.member_email},
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()

            return {
                "status": "success",
                "message": f"Removed {config.member_email} from file",
            }

        except httpx.HTTPStatusError as e:
            error_msg = await self._parse_error_response(e.response)
            raise ValueError(f"Dropbox API error: {error_msg}")
        except Exception as e:
            raise ValueError(f"Remove file member failed: {str(e)}")

    async def _list_file_members(
        self, config: DropboxListFileMembersConfig, token: str
    ) -> Dict[str, Any]:
        """List all members who have access to a file."""
        try:
            url = f"{self.API_BASE}/sharing/list_file_members"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            payload = {"file": config.file_id}

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()

            users = []
            for user in result.get("users", []):
                users.append(
                    {
                        "email": user.get("user", {}).get("email"),
                        "display_name": user.get("user", {}).get("display_name"),
                        "access_level": user.get("access_level", {}).get(".tag"),
                    }
                )

            return {
                "status": "success",
                "members": users,
                "count": len(users),
            }

        except httpx.HTTPStatusError as e:
            error_msg = await self._parse_error_response(e.response)
            raise ValueError(f"Dropbox API error: {error_msg}")
        except Exception as e:
            raise ValueError(f"List file members failed: {str(e)}")

    # ========================================================================
    # Additional File Requests Operations - Extended
    # ========================================================================

    async def _count_file_requests(
        self, config: DropboxCountFileRequestsConfig, token: str
    ) -> Dict[str, Any]:
        """Get count of file requests."""
        try:
            url = f"{self.API_BASE}/file_requests/count"
            headers = {
                "Authorization": f"Bearer {token}",
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers)
                response.raise_for_status()
                result = response.json()

            return {
                "status": "success",
                "file_request_count": result.get("file_request_count", 0),
            }

        except httpx.HTTPStatusError as e:
            error_msg = await self._parse_error_response(e.response)
            raise ValueError(f"Dropbox API error: {error_msg}")
        except Exception as e:
            raise ValueError(f"Count file requests failed: {str(e)}")

    # ========================================================================
    # File Properties Operations (Custom Metadata)
    # ========================================================================

    async def _add_properties(
        self, config: DropboxAddPropertiesConfig, token: str
    ) -> Dict[str, Any]:
        """Add custom properties to a file."""
        try:
            import json

            property_groups = json.loads(config.property_groups)

            url = f"{self.API_BASE}/file_properties/properties/add"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            payload = {
                "path": config.path,
                "property_groups": [property_groups],
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()

            return {
                "status": "success",
                "message": f"Properties added to {config.path}",
            }

        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in property_groups: {str(e)}")
        except httpx.HTTPStatusError as e:
            error_msg = await self._parse_error_response(e.response)
            raise ValueError(f"Dropbox API error: {error_msg}")
        except Exception as e:
            raise ValueError(f"Add properties failed: {str(e)}")

    async def _update_properties(
        self, config: DropboxUpdatePropertiesConfig, token: str
    ) -> Dict[str, Any]:
        """Update custom properties on a file."""
        try:
            import json

            property_groups = json.loads(config.property_groups)

            url = f"{self.API_BASE}/file_properties/properties/update"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            payload = {
                "path": config.path,
                "update_property_groups": [property_groups],
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()

            return {
                "status": "success",
                "message": f"Properties updated on {config.path}",
            }

        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in property_groups: {str(e)}")
        except httpx.HTTPStatusError as e:
            error_msg = await self._parse_error_response(e.response)
            raise ValueError(f"Dropbox API error: {error_msg}")
        except Exception as e:
            raise ValueError(f"Update properties failed: {str(e)}")

    async def _remove_properties(
        self, config: DropboxRemovePropertiesConfig, token: str
    ) -> Dict[str, Any]:
        """Remove custom properties from a file."""
        try:
            url = f"{self.API_BASE}/file_properties/properties/remove"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            payload = {
                "path": config.path,
                "property_template_ids": [config.property_template_id],
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()

            return {
                "status": "success",
                "message": f"Properties removed from {config.path}",
            }

        except httpx.HTTPStatusError as e:
            error_msg = await self._parse_error_response(e.response)
            raise ValueError(f"Dropbox API error: {error_msg}")
        except Exception as e:
            raise ValueError(f"Remove properties failed: {str(e)}")

            # ========================================================================

    # Utility Methods
    # ========================================================================

    def _json_dumps(self, obj: Dict[str, Any]) -> str:
        """JSON dumps with compact formatting."""
        import json

        return json.dumps(obj, separators=(",", ":"))

    async def _parse_error_response(self, response: httpx.Response) -> str:
        """Parse error response from Dropbox API."""
        try:
            error_data = response.json()
            error_summary = error_data.get("error_summary", "Unknown error")
            error = error_data.get("error", {})

            # Try to get a more specific error message
            if isinstance(error, dict):
                tag = error.get(".tag", "")
                if tag:
                    return f"{error_summary} ({tag})"

            return error_summary
        except:
            return f"HTTP {response.status_code}: {response.text[:200]}"
