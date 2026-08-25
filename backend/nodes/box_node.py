"""
Box content-management automation node.

Provides workflow integration with the Box Content API (v2.0) for operations including:
- Users: get current user, list enterprise users
- Folders: list items, get info, create, update, delete, copy, list trash
- Files: get info, upload, upload new version, update, delete, copy, download URL
- Sharing: create/update shared links on files and folders
- Collaboration: add, list, remove collaborators
- Comments: add a comment, list file comments
- Tasks: create a review/approval task
- Search: search content across the account
- Webhooks: create, list, delete; plus a webhook Trigger for file/folder events

Authentication: OAuth 2.0 (Authorization Code, user-delegated) OR a Box
Developer Token (short-lived, self-serve testing). Both pass
`Authorization: Bearer <token>`.

API Base URL: https://api.box.com/2.0  (uploads: https://upload.box.com/api/2.0)
Documentation: https://developer.box.com/reference/
"""

import base64
import hashlib
import hmac
import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin
from nodes.scopes.content_storage import BOX_SCOPES
from utils.ssrf import assert_exact_url_origin, guarded_async_client

logger = logging.getLogger(__name__)

BOX_API_BASE = "https://api.box.com/2.0"
BOX_UPLOAD_BASE = "https://upload.box.com/api/2.0"

# Box webhook V2 triggers, mapped to human-readable labels. Box delivers every
# subscribed trigger to the one webhook address, so the trigger config lets the
# user pick which of these arm the workflow: the selected set is passed to the
# webhook-create ``triggers`` array AND re-checked at runtime against the
# inbound payload's ``trigger`` field (filter_trigger_payload).
BOX_WEBHOOK_TRIGGER_LABELS = {
    "FILE.UPLOADED": "File uploaded",
    "FILE.PREVIEWED": "File previewed",
    "FILE.DOWNLOADED": "File downloaded",
    "FILE.TRASHED": "File trashed",
    "FILE.DELETED": "File permanently deleted",
    "FILE.RESTORED": "File restored from trash",
    "FILE.COPIED": "File copied",
    "FILE.MOVED": "File moved",
    "FILE.LOCKED": "File locked",
    "FILE.UNLOCKED": "File unlocked",
    "FILE.RENAMED": "File renamed",
    "COMMENT.CREATED": "Comment added",
    "COMMENT.UPDATED": "Comment updated",
    "COMMENT.DELETED": "Comment deleted",
    "TASK_ASSIGNMENT.CREATED": "Task assigned",
    "TASK_ASSIGNMENT.UPDATED": "Task assignment updated",
    "METADATA_INSTANCE.CREATED": "Metadata added",
    "METADATA_INSTANCE.UPDATED": "Metadata updated",
    "METADATA_INSTANCE.DELETED": "Metadata deleted",
    "COLLABORATION.CREATED": "Collaboration created",
    "COLLABORATION.ACCEPTED": "Collaboration accepted",
    "COLLABORATION.REJECTED": "Collaboration rejected",
    "COLLABORATION.REMOVED": "Collaboration removed",
    "COLLABORATION.UPDATED": "Collaboration updated",
    "SHARED_LINK.CREATED": "Shared link created",
    "SHARED_LINK.UPDATED": "Shared link updated",
    "SHARED_LINK.DELETED": "Shared link deleted",
    "FOLDER.CREATED": "Folder created",
    "FOLDER.RENAMED": "Folder renamed",
    "FOLDER.DOWNLOADED": "Folder downloaded",
    "FOLDER.TRASHED": "Folder trashed",
    "FOLDER.DELETED": "Folder permanently deleted",
    "FOLDER.RESTORED": "Folder restored from trash",
    "FOLDER.COPIED": "Folder copied",
    "FOLDER.MOVED": "Folder moved",
    "WEBHOOK.DELETED": "Webhook deleted",
}
BOX_WEBHOOK_TRIGGERS = list(BOX_WEBHOOK_TRIGGER_LABELS.keys())

# All OAuth scopes Box can grant; configured on the app in the Developer Console.
BOX_OAUTH_SCOPES = [
    "root_readwrite",
    "manage_managed_users",
    "manage_groups",
    "manage_webhook",
    "manage_enterprise_properties",
]


def _folder_dynamic_options(field_name: str) -> Dict[str, Any]:
    """x-dynamic-options for a folder-reference field (lists root subfolders)."""
    return {
        "x-dynamic-options": {
            "field_name": field_name,
            "placeholder": "Select a folder…",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste folder ID",
        },
        "x-resource-type": "box_folder",
    }


def _file_dynamic_options(field_name: str) -> Dict[str, Any]:
    """x-dynamic-options for a file-reference field (lists files in root folder)."""
    return {
        "x-dynamic-options": {
            "field_name": field_name,
            "placeholder": "Select a file…",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste file ID",
        },
        "x-resource-type": "box_file",
    }


# ============================================================================
# Credential Schema
# ============================================================================


class BoxOAuthCredential(BaseModel):
    """OAuth 2.0 (Authorization Code) credential for Box.

    Tokens are obtained via the OAuth flow, not entered manually. Box access
    tokens last ~60 minutes; refresh tokens are single-use and rotate on every
    refresh, so the newest refresh token must always be persisted.

    Register a Custom App ("User Authentication / OAuth 2.0") at:
    https://app.box.com/developers/console
    """

    credential_type: Literal["box_oauth"] = Field(
        "box_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(..., title="Access Token")
    refresh_token: Optional[str] = Field(None, title="Refresh Token")
    expires_at: Optional[str] = Field(None, title="Token Expiry")  # ISO 8601
    name: Optional[str] = Field(None, title="User Name")
    email: Optional[str] = Field(None, title="Account Email")
    webhook_signing_key: Optional[str] = Field(
        None,
        title="Webhook Primary Signing Key",
        description="Primary signature key from Box Developer Console → Webhooks → Manage signature keys. Required for webhook trigger signature verification.",
        json_schema_extra={"ui:widget": "password", "x-optional-custom": True},
    )
    webhook_signing_key_secondary: Optional[str] = Field(
        None,
        title="Webhook Secondary Signing Key",
        description="Secondary signature key (allows zero-downtime key rotation). Leave blank if you only have one key.",
        json_schema_extra={"ui:widget": "password", "x-optional-custom": True},
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "box",
            "x-oauth-scopes": BOX_OAUTH_SCOPES,
            "x-oauth-supports-custom-client": True,
            "x-oauth-custom-client-help": (
                "Optionally bring your own Box OAuth app. Create a Custom App "
                "('User Authentication / OAuth 2.0') at "
                "https://app.box.com/developers/console, set its redirect URI to "
                "NoClick's Box callback, and paste its client ID and secret here. "
                "Leave blank to use NoClick's shared Box app."
            ),
            "x-credential-url": "https://app.box.com/developers/console",
        }
    )


class BoxDeveloperTokenCredential(BaseModel):
    """Box Developer Token credential (Bearer token, self-serve).

    A Developer Token is generated by hand in the Box Developer Console and is
    valid for ~60 minutes — ideal for testing without a full OAuth app, passed
    the same way as an OAuth access token (`Authorization: Bearer <token>`).
    """

    credential_type: Literal["box_developer_token"] = Field(
        "box_developer_token", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ...,
        title="Developer Token",
        description="Box Developer Token from your app's Configuration tab in the Developer Console (valid ~60 min)",
        json_schema_extra={"ui:widget": "password"},
    )
    webhook_signing_key: Optional[str] = Field(
        None,
        title="Webhook Primary Signing Key",
        description="Primary signature key from Box Developer Console → Webhooks → Manage signature keys. Required for webhook trigger signature verification.",
        json_schema_extra={"ui:widget": "password", "x-optional-custom": True},
    )
    webhook_signing_key_secondary: Optional[str] = Field(
        None,
        title="Webhook Secondary Signing Key",
        description="Secondary signature key (allows zero-downtime key rotation). Leave blank if you only have one key.",
        json_schema_extra={"ui:widget": "password", "x-optional-custom": True},
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://app.box.com/developers/console",
        }
    )


# OAuth shown first in UI (best UX); Developer Token as the self-serve alternative.
BoxCredential = Union[BoxOAuthCredential, BoxDeveloperTokenCredential]


# ============================================================================
# Operation Configs
# ============================================================================


class BoxGetMeConfig(BaseModel):
    """Retrieve the authenticated user's profile."""

    operation: Literal["get_me"] = Field(
        "get_me",
        json_schema_extra={
            "const": "get_me",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "Get Current User",
        },
        title="Get Current User",
    )


class BoxListUsersConfig(BaseModel):
    """List managed users in the enterprise (admin / server auth)."""

    operation: Literal["list_users"] = Field(
        "list_users",
        json_schema_extra={
            "const": "list_users",
            "ui:hidden": True,
            "x-category": "Users",
            "x-is-trigger": False,
            "x-display-name": "List Enterprise Users",
        },
        title="List Enterprise Users",
    )
    filter_term: Optional[str] = Field(
        None, title="Filter Term", description="Filter users whose name or login contains this text"
    )
    limit: Optional[str] = Field(
        "100", title="Limit", description="Max number of users to return (1-1000)"
    )


class BoxListFolderItemsConfig(BaseModel):
    """List files, folders, and web links inside a folder."""

    operation: Literal["list_folder_items"] = Field(
        "list_folder_items",
        json_schema_extra={
            "const": "list_folder_items",
            "ui:hidden": True,
            "x-category": "Folders",
            "x-is-trigger": False,
            "x-display-name": "List Folder Items",
        },
        title="List Folder Items",
    )
    folder_id: str = Field(
        "0",
        title="Folder ID",
        description="ID of the folder to list (use 0 for the root 'All Files' folder)",
        json_schema_extra=_folder_dynamic_options("folder_id"),
    )
    limit: Optional[str] = Field(
        "100", title="Limit", description="Max number of items to return (1-1000)"
    )
    offset: Optional[str] = Field(
        None, title="Offset", description="Offset for pagination (0-based)"
    )


class BoxGetFolderConfig(BaseModel):
    """Retrieve metadata for a folder."""

    operation: Literal["get_folder"] = Field(
        "get_folder",
        json_schema_extra={
            "const": "get_folder",
            "ui:hidden": True,
            "x-category": "Folders",
            "x-is-trigger": False,
            "x-display-name": "Get Folder Info",
        },
        title="Get Folder Info",
    )
    folder_id: str = Field(
        ...,
        title="Folder ID",
        description="ID of the folder",
        json_schema_extra=_folder_dynamic_options("folder_id"),
    )


class BoxCreateFolderConfig(BaseModel):
    """Create a new folder under a parent."""

    operation: Literal["create_folder"] = Field(
        "create_folder",
        json_schema_extra={
            "const": "create_folder",
            "ui:hidden": True,
            "x-category": "Folders",
            "x-is-trigger": False,
            "x-display-name": "Create Folder",
            "x-creates-resource": True,
            "x-resource-type": "box_folder",
            "x-resource-id-path": "data.id",
        },
        title="Create Folder",
    )
    name: str = Field(..., title="Name", description="Name for the new folder")
    parent_id: str = Field(
        "0",
        title="Parent Folder ID",
        description="ID of the parent folder (use 0 for root)",
        json_schema_extra=_folder_dynamic_options("parent_id"),
    )


class BoxUpdateFolderConfig(BaseModel):
    """Rename, move, or change folder properties."""

    operation: Literal["update_folder"] = Field(
        "update_folder",
        json_schema_extra={
            "const": "update_folder",
            "ui:hidden": True,
            "x-category": "Folders",
            "x-is-trigger": False,
            "x-display-name": "Update Folder",
        },
        title="Update Folder",
    )
    folder_id: str = Field(
        ...,
        title="Folder ID",
        description="ID of the folder to update",
        json_schema_extra=_folder_dynamic_options("folder_id"),
    )
    name: Optional[str] = Field(None, title="New Name", description="New folder name")
    description: Optional[str] = Field(
        None, title="Description", description="New folder description"
    )
    parent_id: Optional[str] = Field(
        None,
        title="New Parent Folder ID",
        description="Move the folder under this parent ID",
        json_schema_extra=_folder_dynamic_options("parent_id"),
    )


class BoxDeleteFolderConfig(BaseModel):
    """Delete a folder (moves it to the trash)."""

    operation: Literal["delete_folder"] = Field(
        "delete_folder",
        json_schema_extra={
            "const": "delete_folder",
            "ui:hidden": True,
            "x-category": "Folders",
            "x-is-trigger": False,
            "x-display-name": "Delete Folder",
        },
        title="Delete Folder",
    )
    folder_id: str = Field(
        ...,
        title="Folder ID",
        description="ID of the folder to delete",
        json_schema_extra=_folder_dynamic_options("folder_id"),
    )
    recursive: str = Field(
        "true",
        title="Recursive",
        description="Delete the folder even if it is not empty",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class BoxCopyFolderConfig(BaseModel):
    """Copy a folder (and its contents) into a destination parent."""

    operation: Literal["copy_folder"] = Field(
        "copy_folder",
        json_schema_extra={
            "const": "copy_folder",
            "ui:hidden": True,
            "x-category": "Folders",
            "x-is-trigger": False,
            "x-display-name": "Copy Folder",
        },
        title="Copy Folder",
    )
    folder_id: str = Field(
        ...,
        title="Folder ID",
        description="ID of the folder to copy",
        json_schema_extra=_folder_dynamic_options("folder_id"),
    )
    parent_id: str = Field(
        ...,
        title="Destination Parent ID",
        description="ID of the destination parent folder",
        json_schema_extra=_folder_dynamic_options("parent_id"),
    )
    name: Optional[str] = Field(
        None, title="New Name", description="Optional new name for the copied folder"
    )


class BoxListTrashConfig(BaseModel):
    """List items currently in the trash."""

    operation: Literal["list_trash"] = Field(
        "list_trash",
        json_schema_extra={
            "const": "list_trash",
            "ui:hidden": True,
            "x-category": "Folders",
            "x-is-trigger": False,
            "x-display-name": "List Trashed Items",
        },
        title="List Trashed Items",
    )
    limit: Optional[str] = Field(
        "100", title="Limit", description="Max number of trashed items to return (1-1000)"
    )


class BoxGetFileConfig(BaseModel):
    """Retrieve file metadata."""

    operation: Literal["get_file"] = Field(
        "get_file",
        json_schema_extra={
            "const": "get_file",
            "ui:hidden": True,
            "x-category": "Files",
            "x-is-trigger": False,
            "x-display-name": "Get File Info",
        },
        title="Get File Info",
    )
    file_id: str = Field(..., title="File ID", description="ID of the file", json_schema_extra=_file_dynamic_options("file_id"))


class BoxGetDownloadUrlConfig(BaseModel):
    """Get a download URL for a file (follows Box's 302 redirect)."""

    operation: Literal["get_download_url"] = Field(
        "get_download_url",
        json_schema_extra={
            "const": "get_download_url",
            "ui:hidden": True,
            "x-category": "Files",
            "x-is-trigger": False,
            "x-display-name": "Get File Download URL",
        },
        title="Get File Download URL",
    )
    file_id: str = Field(..., title="File ID", description="ID of the file to download", json_schema_extra=_file_dynamic_options("file_id"))


class BoxUploadFileConfig(BaseModel):
    """Upload a new file from inline text content into a folder."""

    operation: Literal["upload_file"] = Field(
        "upload_file",
        json_schema_extra={
            "const": "upload_file",
            "ui:hidden": True,
            "x-category": "Files",
            "x-is-trigger": False,
            "x-display-name": "Upload File",
        },
        title="Upload File",
    )
    name: str = Field(..., title="File Name", description="Name for the uploaded file (e.g. notes.txt)")
    parent_id: str = Field(
        "0",
        title="Parent Folder ID",
        description="ID of the destination folder (0 for root)",
        json_schema_extra=_folder_dynamic_options("parent_id"),
    )
    content: str = Field(
        ...,
        title="Content",
        description="Text content to upload as the file body",
        json_schema_extra={"ui:widget": "textarea"},
    )


class BoxUploadVersionConfig(BaseModel):
    """Upload a new version of an existing file from inline text content."""

    operation: Literal["upload_version"] = Field(
        "upload_version",
        json_schema_extra={
            "const": "upload_version",
            "ui:hidden": True,
            "x-category": "Files",
            "x-is-trigger": False,
            "x-display-name": "Upload New Version",
        },
        title="Upload New Version",
    )
    file_id: str = Field(..., title="File ID", description="ID of the file to add a version to", json_schema_extra=_file_dynamic_options("file_id"))
    content: str = Field(
        ...,
        title="Content",
        description="New text content for the file version",
        json_schema_extra={"ui:widget": "textarea"},
    )


class BoxUpdateFileConfig(BaseModel):
    """Rename, move, or change a file's description."""

    operation: Literal["update_file"] = Field(
        "update_file",
        json_schema_extra={
            "const": "update_file",
            "ui:hidden": True,
            "x-category": "Files",
            "x-is-trigger": False,
            "x-display-name": "Update File",
        },
        title="Update File",
    )
    file_id: str = Field(..., title="File ID", description="ID of the file to update", json_schema_extra=_file_dynamic_options("file_id"))
    name: Optional[str] = Field(None, title="New Name", description="New file name")
    description: Optional[str] = Field(
        None, title="Description", description="New file description"
    )
    parent_id: Optional[str] = Field(
        None,
        title="New Parent Folder ID",
        description="Move the file under this parent ID",
        json_schema_extra=_folder_dynamic_options("parent_id"),
    )


class BoxDeleteFileConfig(BaseModel):
    """Move a file to the trash."""

    operation: Literal["delete_file"] = Field(
        "delete_file",
        json_schema_extra={
            "const": "delete_file",
            "ui:hidden": True,
            "x-category": "Files",
            "x-is-trigger": False,
            "x-display-name": "Delete File",
        },
        title="Delete File",
    )
    file_id: str = Field(..., title="File ID", description="ID of the file to delete", json_schema_extra=_file_dynamic_options("file_id"))


class BoxCopyFileConfig(BaseModel):
    """Copy a file into a destination folder."""

    operation: Literal["copy_file"] = Field(
        "copy_file",
        json_schema_extra={
            "const": "copy_file",
            "ui:hidden": True,
            "x-category": "Files",
            "x-is-trigger": False,
            "x-display-name": "Copy File",
        },
        title="Copy File",
    )
    file_id: str = Field(..., title="File ID", description="ID of the file to copy", json_schema_extra=_file_dynamic_options("file_id"))
    parent_id: str = Field(
        ...,
        title="Destination Folder ID",
        description="ID of the destination folder",
        json_schema_extra=_folder_dynamic_options("parent_id"),
    )
    name: Optional[str] = Field(
        None, title="New Name", description="Optional new name for the copied file"
    )


class BoxCreateFileSharedLinkConfig(BaseModel):
    """Create or update a public shared link on a file."""

    operation: Literal["create_file_shared_link"] = Field(
        "create_file_shared_link",
        json_schema_extra={
            "const": "create_file_shared_link",
            "ui:hidden": True,
            "x-category": "Sharing",
            "x-is-trigger": False,
            "x-display-name": "Create File Shared Link",
        },
        title="Create File Shared Link",
    )
    file_id: str = Field(..., title="File ID", description="ID of the file to share", json_schema_extra=_file_dynamic_options("file_id"))
    access: str = Field(
        "open",
        title="Access",
        description="Who can access the shared link",
        json_schema_extra={
            "enum": ["open", "company", "collaborators"],
            "enumNames": ["Anyone with the link", "People in your company", "Collaborators only"],
            "x-enum-searchable": True,
        },
    )


class BoxCreateFolderSharedLinkConfig(BaseModel):
    """Create or update a shared link on a folder."""

    operation: Literal["create_folder_shared_link"] = Field(
        "create_folder_shared_link",
        json_schema_extra={
            "const": "create_folder_shared_link",
            "ui:hidden": True,
            "x-category": "Sharing",
            "x-is-trigger": False,
            "x-display-name": "Create Folder Shared Link",
        },
        title="Create Folder Shared Link",
    )
    folder_id: str = Field(
        ...,
        title="Folder ID",
        description="ID of the folder to share",
        json_schema_extra=_folder_dynamic_options("folder_id"),
    )
    access: str = Field(
        "open",
        title="Access",
        description="Who can access the shared link",
        json_schema_extra={
            "enum": ["open", "company", "collaborators"],
            "enumNames": ["Anyone with the link", "People in your company", "Collaborators only"],
            "x-enum-searchable": True,
        },
    )


class BoxSearchConfig(BaseModel):
    """Search files, folders, and web links by query."""

    operation: Literal["search"] = Field(
        "search",
        json_schema_extra={
            "const": "search",
            "ui:hidden": True,
            "x-category": "Search",
            "x-is-trigger": False,
            "x-display-name": "Search Content",
        },
        title="Search Content",
    )
    query: str = Field(..., title="Query", description="Search keywords")
    type: Optional[str] = Field(
        None,
        title="Type",
        description="Restrict results to a single item type",
        json_schema_extra={
            "enum": ["", "file", "folder", "web_link"],
            "enumNames": ["Any", "Files", "Folders", "Web Links"],
            "x-enum-searchable": True,
        },
    )
    ancestor_folder_ids: Optional[str] = Field(
        None,
        title="Ancestor Folder IDs",
        description="Limit the search to these folder IDs, comma-separated",
    )
    limit: Optional[str] = Field(
        "30", title="Limit", description="Max number of results (1-200)"
    )


class BoxAddCollaborationConfig(BaseModel):
    """Share a file or folder with a user at a given role."""

    operation: Literal["add_collaboration"] = Field(
        "add_collaboration",
        json_schema_extra={
            "const": "add_collaboration",
            "ui:hidden": True,
            "x-category": "Collaboration",
            "x-is-trigger": False,
            "x-display-name": "Add Collaboration",
        },
        title="Add Collaboration",
    )
    item_type: str = Field(
        "folder",
        title="Item Type",
        description="Whether you are sharing a file or a folder",
        json_schema_extra={
            "enum": ["folder", "file"],
            "enumNames": ["Folder", "File"],
            "x-enum-searchable": True,
        },
    )
    item_id: str = Field(..., title="Item ID", description="ID of the file or folder to share")
    login: str = Field(
        ..., title="Collaborator Email", description="Email (login) of the user to add as a collaborator"
    )
    role: str = Field(
        "viewer",
        title="Role",
        description="Permission level granted to the collaborator",
        json_schema_extra={
            "enum": ["editor", "viewer", "previewer", "uploader", "co-owner", "viewer uploader", "previewer uploader"],
            "x-enum-searchable": True,
        },
    )


class BoxListCollaborationsConfig(BaseModel):
    """List collaborators on a folder or file."""

    operation: Literal["list_collaborations"] = Field(
        "list_collaborations",
        json_schema_extra={
            "const": "list_collaborations",
            "ui:hidden": True,
            "x-category": "Collaboration",
            "x-is-trigger": False,
            "x-display-name": "List Collaborations",
        },
        title="List Collaborations",
    )
    item_type: str = Field(
        "folder",
        title="Item Type",
        description="Whether to list collaborators on a file or folder",
        json_schema_extra={
            "enum": ["folder", "file"],
            "enumNames": ["Folder", "File"],
            "x-enum-searchable": True,
        },
    )
    item_id: str = Field(..., title="Item ID", description="ID of the file or folder")


class BoxRemoveCollaborationConfig(BaseModel):
    """Remove a collaborator."""

    operation: Literal["remove_collaboration"] = Field(
        "remove_collaboration",
        json_schema_extra={
            "const": "remove_collaboration",
            "ui:hidden": True,
            "x-category": "Collaboration",
            "x-is-trigger": False,
            "x-display-name": "Remove Collaboration",
        },
        title="Remove Collaboration",
    )
    collaboration_id: str = Field(
        ..., title="Collaboration ID", description="ID of the collaboration to remove"
    )


class BoxAddCommentConfig(BaseModel):
    """Add a comment to a file."""

    operation: Literal["add_comment"] = Field(
        "add_comment",
        json_schema_extra={
            "const": "add_comment",
            "ui:hidden": True,
            "x-category": "Comments",
            "x-is-trigger": False,
            "x-display-name": "Add Comment",
        },
        title="Add Comment",
    )
    file_id: str = Field(..., title="File ID", description="ID of the file to comment on", json_schema_extra=_file_dynamic_options("file_id"))
    message: str = Field(
        ...,
        title="Message",
        description="The comment text",
        json_schema_extra={"ui:widget": "textarea"},
    )


class BoxListCommentsConfig(BaseModel):
    """List comments on a file."""

    operation: Literal["list_comments"] = Field(
        "list_comments",
        json_schema_extra={
            "const": "list_comments",
            "ui:hidden": True,
            "x-category": "Comments",
            "x-is-trigger": False,
            "x-display-name": "List File Comments",
        },
        title="List File Comments",
    )
    file_id: str = Field(..., title="File ID", description="ID of the file", json_schema_extra=_file_dynamic_options("file_id"))


class BoxCreateTaskConfig(BaseModel):
    """Create a review or approval task on a file."""

    operation: Literal["create_task"] = Field(
        "create_task",
        json_schema_extra={
            "const": "create_task",
            "ui:hidden": True,
            "x-category": "Tasks",
            "x-is-trigger": False,
            "x-display-name": "Create Task",
        },
        title="Create Task",
    )
    file_id: str = Field(..., title="File ID", description="ID of the file the task is on", json_schema_extra=_file_dynamic_options("file_id"))
    message: Optional[str] = Field(
        None, title="Message", description="Instructions shown to the assignee"
    )
    action: str = Field(
        "review",
        title="Action",
        description="The type of task",
        json_schema_extra={
            "enum": ["review", "complete"],
            "enumNames": ["Review", "Complete"],
            "x-enum-searchable": True,
        },
    )


class BoxCreateWebhookConfig(BaseModel):
    """Register a webhook on a file or folder (manual, not the trigger)."""

    operation: Literal["create_webhook"] = Field(
        "create_webhook",
        json_schema_extra={
            "const": "create_webhook",
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-is-trigger": False,
            "x-display-name": "Create Webhook",
            "x-creates-resource": True,
            "x-resource-type": "box_webhook",
            "x-resource-id-path": "data.id",
        },
        title="Create Webhook",
    )
    target_type: str = Field(
        "folder",
        title="Target Type",
        description="Whether the webhook attaches to a file or folder",
        json_schema_extra={
            "enum": ["folder", "file"],
            "enumNames": ["Folder", "File"],
            "x-enum-searchable": True,
        },
    )
    target_id: str = Field(
        ...,
        title="Target ID",
        description="ID of the file or folder",
        json_schema_extra=_folder_dynamic_options("target_id"),
    )
    address: str = Field(..., title="Address", description="URL Box should POST events to")
    triggers: str = Field(
        "FILE.UPLOADED",
        title="Triggers",
        description="Comma-separated event names (e.g. FILE.UPLOADED,FILE.DELETED)",
    )


class BoxListWebhooksConfig(BaseModel):
    """List all webhooks created by the app for the user."""

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
    limit: Optional[str] = Field(
        "100", title="Limit", description="Max number of webhooks to return"
    )


class BoxDeleteWebhookConfig(BaseModel):
    """Delete a webhook."""

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
    webhook_id: str = Field(
        ...,
        title="Webhook ID",
        description="ID of the webhook to delete",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "webhook_id",
                "placeholder": "Select a webhook…",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste webhook ID",
            },
            "x-resource-type": "box_webhook",
        },
    )


# ============================================================================
# Webhook Trigger Config
# ============================================================================


class BoxWebhookTriggerConfig(BaseModel):
    """Fire the workflow when a Box file/folder event occurs (FILE.UPLOADED, etc.)."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["on_box_event"] = Field(
        "on_box_event",
        json_schema_extra={
            "const": "on_box_event",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On File or Folder Event",
        },
        title="On File or Folder Event",
    )
    target_type: str = Field(
        "folder",
        title="Target Type",
        description="Whether to watch a file or a folder for events",
        json_schema_extra={
            "enum": ["folder", "file"],
            "enumNames": ["Folder", "File"],
            "x-enum-searchable": True,
        },
    )
    target_id: str = Field(
        "0",
        title="Target ID",
        description="ID of the file or folder to watch (use 0 for the root folder)",
        json_schema_extra=_folder_dynamic_options("target_id"),
    )
    event_types: str = Field(
        "FILE.UPLOADED",
        title="Trigger On Events",
        description=(
            "Comma-separated Box events that fire the workflow. Box delivers all "
            "subscribed events to one URL, so only the selected events run the "
            "workflow; the rest are skipped. Leave blank to fire on every event. "
            "Available: "
            + ", ".join(f"{k} ({v})" for k, v in BOX_WEBHOOK_TRIGGER_LABELS.items())
        ),
        json_schema_extra={
            "enum": BOX_WEBHOOK_TRIGGERS,
            "enumNames": list(BOX_WEBHOOK_TRIGGER_LABELS.values()),
            "x-enum-searchable": True,
            "ui:placeholder": "FILE.UPLOADED,FOLDER.CREATED (blank = all events)",
        },
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="Box posts events here. Registered automatically when you connect credentials.",
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
    signing_secret_secondary: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    relay_connected: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    is_production: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    trigger_registered: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    trigger_error: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})


# ============================================================================
# Discriminated Union
# ============================================================================


BoxConfig = Annotated[
    Union[
        BoxGetMeConfig,
        BoxListUsersConfig,
        BoxListFolderItemsConfig,
        BoxGetFolderConfig,
        BoxCreateFolderConfig,
        BoxUpdateFolderConfig,
        BoxDeleteFolderConfig,
        BoxCopyFolderConfig,
        BoxListTrashConfig,
        BoxGetFileConfig,
        BoxGetDownloadUrlConfig,
        BoxUploadFileConfig,
        BoxUploadVersionConfig,
        BoxUpdateFileConfig,
        BoxDeleteFileConfig,
        BoxCopyFileConfig,
        BoxCreateFileSharedLinkConfig,
        BoxCreateFolderSharedLinkConfig,
        BoxSearchConfig,
        BoxAddCollaborationConfig,
        BoxListCollaborationsConfig,
        BoxRemoveCollaborationConfig,
        BoxAddCommentConfig,
        BoxListCommentsConfig,
        BoxCreateTaskConfig,
        BoxCreateWebhookConfig,
        BoxListWebhooksConfig,
        BoxDeleteWebhookConfig,
        BoxWebhookTriggerConfig,
    ],
    Discriminator("operation"),
]


class BoxNodeConfig(NodeConfig[BoxConfig, BoxCredential]):
    """Full configuration for the Box node including credentials."""

    pass


# ============================================================================
# HTTP helper
# ============================================================================


def _comma_list(value: Optional[str]) -> Optional[List[str]]:
    if not value:
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return parts or None


async def _box_request(
    access_token: str,
    method: str,
    endpoint: str,
    *,
    base: str = BOX_API_BASE,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    files: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
    follow_redirects: bool = True,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated Box API request and return a structured result."""
    allowed_origins = {
        BOX_API_BASE: "https://api.box.com",
        BOX_UPLOAD_BASE: "https://upload.box.com",
    }
    allowed_origin = allowed_origins.get(base)
    if allowed_origin is None:
        raise ValueError("Box requests must use a code-owned API base")
    url = f"{base}{endpoint}"
    assert_exact_url_origin(url, allowed_origin)
    headers = {"Authorization": f"Bearer {access_token}"}
    if json_body is not None:
        headers["Content-Type"] = "application/json"
        json_body = {k: v for k, v in json_body.items() if v is not None}
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}

    start = time.time()
    async with guarded_async_client(
        timeout=30.0, follow_redirects=follow_redirects
    ) as client:
        try:
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json_body,
                files=files,
                data=data,
            )
            api_ms = round((time.time() - start) * 1000, 2)
            if response.status_code >= 400:
                try:
                    err = response.json()
                    message = err.get("message") or err.get("error_description") or str(err)
                except Exception:
                    message = response.text
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[BoxNode] API error ({action_name}): {message}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": message,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }
            if response.status_code == 204:
                payload: Any = {"success": True}
            else:
                try:
                    payload = response.json()
                except Exception:
                    payload = {"raw": response.text}
            return {
                "status": "success",
                "action": action_name,
                "data": payload,
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
            logger.error(f"[BoxNode] Request failed ({action_name}): {msg}")
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


class BoxNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """Box content-management automation node."""

    edit_examples = [
        "List the files in my root Box folder",
        "Upload a text file to a Box folder",
        "Create a public shared link for a Box file",
        "Search Box for documents matching a keyword",
        "Add a teammate as an editor on a Box folder",
        "Trigger a workflow whenever a file is uploaded to a Box folder",
    ]

    scope_registry = BOX_SCOPES
    connection_evidence = ConnectionEvidence(
        field="folder_id",
        noun="folders",
    )
    @classmethod
    def get_config_model(cls):
        return BoxNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        """Refresh an expiring Box OAuth token at credential load (dropdowns,
        trigger registration). No-op for Developer Tokens (which carry no
        refresh_token). Box's refresh tokens are single-use and rotate, so the
        freshen choke point CAS-persists the rotated token under lock."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.box_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token,
            provider="box",
        )

    async def _ensure_fresh_token(self, credentials: "BoxCredential") -> None:
        """Refresh an expired Box OAuth token in place before an API call.
        Developer Tokens carry no refresh_token and are left untouched."""
        if not isinstance(credentials, BoxOAuthCredential):
            return

        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.box_oauth import refresh_access_token
        
        cred_dict = credentials.model_dump()
        await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=cred_dict,
            refresh=refresh_access_token,
            provider="box",
            caller_path="execute",
        )
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        if cred_dict.get("refresh_token"):
            credentials.refresh_token = cred_dict["refresh_token"]

    @staticmethod
    def _token_from_credential(credential: Dict[str, Any]) -> Optional[str]:
        """Box uses a Bearer token for both OAuth and Developer Token auth."""
        return (credential or {}).get("access_token")

    # ------------------------------------------------------------------
    # Dynamic options (folders, webhooks)
    # ------------------------------------------------------------------
    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        if field_name not in ("folder_id", "parent_id", "target_id", "webhook_id", "file_id"):
            return {"options": []}
        access_token = cls._token_from_credential(credential_data or {})
        if not access_token:
            return {"options": []}

        if field_name == "webhook_id":
            return await cls._load_webhook_options(access_token)
        if field_name == "file_id":
            return await cls._load_file_options(access_token, search=search)
        return await cls._load_folder_options(access_token)

    @classmethod
    async def _load_folder_options(cls, access_token: str) -> Dict[str, Any]:
        result = await _box_request(
            access_token,
            "GET",
            "/folders/0/items",
            params={"limit": "1000", "fields": "id,name,type"},
            action_name="list_folder_options",
        )
        if result.get("status") != "success":
            return {"options": []}
        entries = (result.get("data") or {}).get("entries") or []
        options = [{"label": "All Files (root)", "value": "0"}]
        for entry in entries:
            if isinstance(entry, dict) and entry.get("type") == "folder":
                options.append({"label": entry.get("name") or entry.get("id"), "value": str(entry.get("id"))})
        return {"options": options}

    @classmethod
    async def _load_file_options(cls, access_token: str, search: Optional[str] = None) -> Dict[str, Any]:
        if search:
            result = await _box_request(
                access_token,
                "GET",
                "/search",
                params={"query": search, "type": "file", "limit": "100", "fields": "id,name,type"},
                action_name="search_file_options",
            )
            entries = (result.get("data") or {}).get("entries") or []
        else:
            result = await _box_request(
                access_token,
                "GET",
                "/folders/0/items",
                params={"limit": "500", "fields": "id,name,type"},
                action_name="list_file_options",
            )
            entries = (result.get("data") or {}).get("entries") or []
        if result.get("status") != "success":
            return {"options": []}
        options = []
        for entry in entries:
            if isinstance(entry, dict) and entry.get("type") == "file":
                options.append({"label": entry.get("name") or entry.get("id"), "value": str(entry.get("id"))})
        return {"options": options}

    @classmethod
    async def _load_webhook_options(cls, access_token: str) -> Dict[str, Any]:
        result = await _box_request(
            access_token,
            "GET",
            "/webhooks",
            params={"limit": "1000"},
            action_name="list_webhook_options",
        )
        if result.get("status") != "success":
            return {"options": []}
        entries = (result.get("data") or {}).get("entries") or []
        options = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            wid = entry.get("id")
            target = entry.get("target") or {}
            label = f"{target.get('type', 'item')} {target.get('id', '?')} → webhook {wid}"
            options.append({"label": label, "value": str(wid)})
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
            "target_type": (config or {}).get("target_type"),
            "target_id": (config or {}).get("target_id"),
            "event_types": (config or {}).get("event_types"),
        }

    @classmethod
    async def _register_external_webhook(
        cls, *, webhook_url: str, credential: Dict[str, Any], config: Dict[str, Any], node_id: str
    ) -> Optional[Dict[str, Any]]:
        access_token = cls._token_from_credential(credential)
        if not access_token:
            raise ValueError("A Box access token is required to register the trigger")
        target_type = (config or {}).get("target_type") or "folder"
        target_id = str((config or {}).get("target_id") or "0")
        # Subscribe only to the events the user picked; blank means all events.
        triggers = _comma_list((config or {}).get("event_types")) or BOX_WEBHOOK_TRIGGERS
        result = await _box_request(
            access_token,
            "POST",
            "/webhooks",
            json_body={
                "target": {"id": target_id, "type": target_type},
                "address": webhook_url,
                "triggers": triggers,
            },
            action_name="register_webhook",
        )
        if result.get("status") != "success":
            raise ValueError(f"Box webhook registration failed: {result.get('error')}")
        data = result.get("data") or {}
        external_id = data.get("id")
        return {
            "external_webhook_id": str(external_id) if external_id else None,
            "signing_secret": credential.get("webhook_signing_key"),
            "signing_secret_secondary": credential.get("webhook_signing_key_secondary"),
        }

    @classmethod
    async def _unregister_external_webhook(
        cls, *, credential: Optional[Dict[str, Any]], config: Dict[str, Any], node_id: str
    ) -> None:
        external_id = (config or {}).get("external_webhook_id")
        access_token = cls._token_from_credential(credential or {})
        if not external_id or not access_token:
            return
        await _box_request(
            access_token,
            "DELETE",
            f"/webhooks/{external_id}",
            action_name="unregister_webhook",
        )

    @classmethod
    def verify_webhook_signature(
        cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]
    ) -> bool:
        """Verify Box's BOX-SIGNATURE-PRIMARY / -SECONDARY HMAC-SHA256 (base64).

        Box signs ``body + BOX-DELIVERY-TIMESTAMP`` with BOTH the primary key
        (→ BOX-SIGNATURE-PRIMARY header) and the secondary key (→
        BOX-SIGNATURE-SECONDARY header). We check each key against its own
        header; accept if either pair validates. When no keys are stored we
        accept (trigger not yet armed for verification).
        """
        cfg = config or {}
        primary_key = cfg.get("signing_secret")
        secondary_key = cfg.get("signing_secret_secondary")
        if not primary_key and not secondary_key:
            return True  # trigger not yet armed with verifiable keys
        timestamp = headers.get("box-delivery-timestamp", "")
        if not timestamp:
            return False
        # Box mandates rejecting deliveries older than 10 minutes (replay guard).
        try:
            from datetime import datetime, timezone, timedelta
            delivered = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - delivered > timedelta(minutes=10):
                return False
        except (ValueError, TypeError):
            return False
        message = body + timestamp.encode()

        def _check(key: Optional[str], header_val: Optional[str]) -> bool:
            if not key or not header_val:
                return False
            expected = base64.b64encode(
                hmac.new(key.encode(), message, hashlib.sha256).digest()
            ).decode()
            return hmac.compare_digest(expected, header_val)

        return _check(primary_key, headers.get("box-signature-primary")) or _check(
            secondary_key, headers.get("box-signature-secondary")
        )

    @classmethod
    def filter_trigger_payload(cls, payload: Dict[str, Any], config: Dict[str, Any]) -> bool:
        """Run the workflow only for the events the user selected.

        Box delivers every subscribed trigger to the same webhook URL, so we
        re-check the inbound ``trigger`` field against ``event_types`` and skip
        deliveries that weren't selected. A blank selection fires on all events.
        """
        selected = _comma_list((config or {}).get("event_types"))
        if not selected:
            return True
        return (payload or {}).get("trigger") in selected

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, BoxNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        if isinstance(op, BoxWebhookTriggerConfig):
            return {
                "status": "success",
                "action": "on_box_event",
                "data": {**inputs, "webhook_url": op.webhook_url},
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Connect your Box account or add a Developer Token.")
        await self._ensure_fresh_token(credentials)
        access_token = credentials.access_token

        handlers = {
            "get_me": self._get_me,
            "list_users": self._list_users,
            "list_folder_items": self._list_folder_items,
            "get_folder": self._get_folder,
            "create_folder": self._create_folder,
            "update_folder": self._update_folder,
            "delete_folder": self._delete_folder,
            "copy_folder": self._copy_folder,
            "list_trash": self._list_trash,
            "get_file": self._get_file,
            "get_download_url": self._get_download_url,
            "upload_file": self._upload_file,
            "upload_version": self._upload_version,
            "update_file": self._update_file,
            "delete_file": self._delete_file,
            "copy_file": self._copy_file,
            "create_file_shared_link": self._create_file_shared_link,
            "create_folder_shared_link": self._create_folder_shared_link,
            "search": self._search,
            "add_collaboration": self._add_collaboration,
            "list_collaborations": self._list_collaborations,
            "remove_collaboration": self._remove_collaboration,
            "add_comment": self._add_comment,
            "list_comments": self._list_comments,
            "create_task": self._create_task,
            "create_webhook": self._create_webhook,
            "list_webhooks": self._list_webhooks,
            "delete_webhook": self._delete_webhook,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(op, access_token)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # Handlers — Users
    # ------------------------------------------------------------------
    async def _get_me(self, c: BoxGetMeConfig, token: str) -> Dict[str, Any]:
        return await _box_request(token, "GET", "/users/me", action_name="get_me")

    async def _list_users(self, c: BoxListUsersConfig, token: str) -> Dict[str, Any]:
        params = {"filter_term": c.filter_term, "limit": c.limit}
        return await _box_request(token, "GET", "/users", params=params, action_name="list_users")

    # ------------------------------------------------------------------
    # Handlers — Folders
    # ------------------------------------------------------------------
    async def _list_folder_items(self, c: BoxListFolderItemsConfig, token: str) -> Dict[str, Any]:
        params = {"limit": c.limit, "offset": c.offset}
        return await _box_request(
            token, "GET", f"/folders/{c.folder_id}/items", params=params, action_name="list_folder_items"
        )

    async def _get_folder(self, c: BoxGetFolderConfig, token: str) -> Dict[str, Any]:
        return await _box_request(token, "GET", f"/folders/{c.folder_id}", action_name="get_folder")

    async def _create_folder(self, c: BoxCreateFolderConfig, token: str) -> Dict[str, Any]:
        body = {"name": c.name, "parent": {"id": c.parent_id}}
        return await _box_request(token, "POST", "/folders", json_body=body, action_name="create_folder")

    async def _update_folder(self, c: BoxUpdateFolderConfig, token: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {"name": c.name, "description": c.description}
        if c.parent_id:
            body["parent"] = {"id": c.parent_id}
        return await _box_request(
            token, "PUT", f"/folders/{c.folder_id}", json_body=body, action_name="update_folder"
        )

    async def _delete_folder(self, c: BoxDeleteFolderConfig, token: str) -> Dict[str, Any]:
        return await _box_request(
            token, "DELETE", f"/folders/{c.folder_id}",
            params={"recursive": c.recursive}, action_name="delete_folder"
        )

    async def _copy_folder(self, c: BoxCopyFolderConfig, token: str) -> Dict[str, Any]:
        body = {"parent": {"id": c.parent_id}, "name": c.name}
        return await _box_request(
            token, "POST", f"/folders/{c.folder_id}/copy", json_body=body, action_name="copy_folder"
        )

    async def _list_trash(self, c: BoxListTrashConfig, token: str) -> Dict[str, Any]:
        return await _box_request(
            token, "GET", "/folders/trash/items", params={"limit": c.limit}, action_name="list_trash"
        )

    # ------------------------------------------------------------------
    # Handlers — Files
    # ------------------------------------------------------------------
    async def _get_file(self, c: BoxGetFileConfig, token: str) -> Dict[str, Any]:
        return await _box_request(token, "GET", f"/files/{c.file_id}", action_name="get_file")

    async def _get_download_url(self, c: BoxGetDownloadUrlConfig, token: str) -> Dict[str, Any]:
        # Box returns the file location via the Location header on a 302; ask for
        # the redirect target without following it so we surface the signed URL.
        result = await _box_request(
            token, "GET", f"/files/{c.file_id}", action_name="get_download_url"
        )
        if result.get("status") == "success":
            file_id = (result.get("data") or {}).get("id") or c.file_id
            result["data"] = {
                "download_url": f"{BOX_API_BASE}/files/{file_id}/content",
                "file": result.get("data"),
            }
        return result

    async def _upload_file(self, c: BoxUploadFileConfig, token: str) -> Dict[str, Any]:
        import json as _json

        attributes = _json.dumps({"name": c.name, "parent": {"id": c.parent_id}})
        files = {
            "attributes": (None, attributes, "application/json"),
            "file": (c.name, c.content.encode("utf-8"), "application/octet-stream"),
        }
        return await _box_request(
            token, "POST", "/files/content", base=BOX_UPLOAD_BASE, files=files, action_name="upload_file"
        )

    async def _upload_version(self, c: BoxUploadVersionConfig, token: str) -> Dict[str, Any]:
        files = {
            "file": ("version", c.content.encode("utf-8"), "application/octet-stream"),
        }
        return await _box_request(
            token, "POST", f"/files/{c.file_id}/content", base=BOX_UPLOAD_BASE, files=files,
            action_name="upload_version"
        )

    async def _update_file(self, c: BoxUpdateFileConfig, token: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {"name": c.name, "description": c.description}
        if c.parent_id:
            body["parent"] = {"id": c.parent_id}
        return await _box_request(
            token, "PUT", f"/files/{c.file_id}", json_body=body, action_name="update_file"
        )

    async def _delete_file(self, c: BoxDeleteFileConfig, token: str) -> Dict[str, Any]:
        return await _box_request(token, "DELETE", f"/files/{c.file_id}", action_name="delete_file")

    async def _copy_file(self, c: BoxCopyFileConfig, token: str) -> Dict[str, Any]:
        body = {"parent": {"id": c.parent_id}, "name": c.name}
        return await _box_request(
            token, "POST", f"/files/{c.file_id}/copy", json_body=body, action_name="copy_file"
        )

    # ------------------------------------------------------------------
    # Handlers — Sharing
    # ------------------------------------------------------------------
    async def _create_file_shared_link(self, c: BoxCreateFileSharedLinkConfig, token: str) -> Dict[str, Any]:
        body = {"shared_link": {"access": c.access}}
        return await _box_request(
            token, "PUT", f"/files/{c.file_id}", params={"fields": "shared_link"},
            json_body=body, action_name="create_file_shared_link"
        )

    async def _create_folder_shared_link(self, c: BoxCreateFolderSharedLinkConfig, token: str) -> Dict[str, Any]:
        body = {"shared_link": {"access": c.access}}
        return await _box_request(
            token, "PUT", f"/folders/{c.folder_id}", params={"fields": "shared_link"},
            json_body=body, action_name="create_folder_shared_link"
        )

    # ------------------------------------------------------------------
    # Handlers — Search
    # ------------------------------------------------------------------
    async def _search(self, c: BoxSearchConfig, token: str) -> Dict[str, Any]:
        params = {
            "query": c.query,
            "type": c.type or None,
            "ancestor_folder_ids": c.ancestor_folder_ids,
            "limit": c.limit,
        }
        return await _box_request(token, "GET", "/search", params=params, action_name="search")

    # ------------------------------------------------------------------
    # Handlers — Collaboration
    # ------------------------------------------------------------------
    async def _add_collaboration(self, c: BoxAddCollaborationConfig, token: str) -> Dict[str, Any]:
        body = {
            "item": {"id": c.item_id, "type": c.item_type},
            "accessible_by": {"type": "user", "login": c.login},
            "role": c.role,
        }
        return await _box_request(
            token, "POST", "/collaborations", json_body=body, action_name="add_collaboration"
        )

    async def _list_collaborations(self, c: BoxListCollaborationsConfig, token: str) -> Dict[str, Any]:
        endpoint = f"/folders/{c.item_id}/collaborations" if c.item_type == "folder" else f"/files/{c.item_id}/collaborations"
        return await _box_request(token, "GET", endpoint, action_name="list_collaborations")

    async def _remove_collaboration(self, c: BoxRemoveCollaborationConfig, token: str) -> Dict[str, Any]:
        return await _box_request(
            token, "DELETE", f"/collaborations/{c.collaboration_id}", action_name="remove_collaboration"
        )

    # ------------------------------------------------------------------
    # Handlers — Comments
    # ------------------------------------------------------------------
    async def _add_comment(self, c: BoxAddCommentConfig, token: str) -> Dict[str, Any]:
        body = {"item": {"id": c.file_id, "type": "file"}, "message": c.message}
        return await _box_request(token, "POST", "/comments", json_body=body, action_name="add_comment")

    async def _list_comments(self, c: BoxListCommentsConfig, token: str) -> Dict[str, Any]:
        return await _box_request(
            token, "GET", f"/files/{c.file_id}/comments", action_name="list_comments"
        )

    # ------------------------------------------------------------------
    # Handlers — Tasks
    # ------------------------------------------------------------------
    async def _create_task(self, c: BoxCreateTaskConfig, token: str) -> Dict[str, Any]:
        body = {
            "item": {"id": c.file_id, "type": "file"},
            "message": c.message,
            "action": c.action,
        }
        return await _box_request(token, "POST", "/tasks", json_body=body, action_name="create_task")

    # ------------------------------------------------------------------
    # Handlers — Webhooks
    # ------------------------------------------------------------------
    async def _create_webhook(self, c: BoxCreateWebhookConfig, token: str) -> Dict[str, Any]:
        body = {
            "target": {"id": c.target_id, "type": c.target_type},
            "address": c.address,
            "triggers": _comma_list(c.triggers) or ["FILE.UPLOADED"],
        }
        return await _box_request(token, "POST", "/webhooks", json_body=body, action_name="create_webhook")

    async def _list_webhooks(self, c: BoxListWebhooksConfig, token: str) -> Dict[str, Any]:
        return await _box_request(
            token, "GET", "/webhooks", params={"limit": c.limit}, action_name="list_webhooks"
        )

    async def _delete_webhook(self, c: BoxDeleteWebhookConfig, token: str) -> Dict[str, Any]:
        return await _box_request(
            token, "DELETE", f"/webhooks/{c.webhook_id}", action_name="delete_webhook"
        )
