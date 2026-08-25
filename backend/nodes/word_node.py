"""
Word node for Microsoft Graph API - Complete Word document automation.

Supports Word document operations via Microsoft Graph API including document management,
content operations (download, PDF/HTML conversion), sharing, permissions, version control,
and search. Uses centralized Microsoft OAuth.

Research Source: Microsoft Graph OneDrive/DriveItem API v1.0 Documentation
Total Operations: 22 (across 5 categories)

Authentication: Microsoft OAuth 2.0 only (Microsoft Graph requires OAuth)

Note: Microsoft Graph doesn't provide direct Word content editing APIs (find/replace,
formatting, etc.). For content manipulation, documents must be downloaded, edited with
third-party libraries, and re-uploaded. This node focuses on document management and
file operations.
"""

from typing import Dict, Any, Literal, Optional, Tuple, Union, List, Annotated
from pydantic import BaseModel, ConfigDict, Discriminator, Field
from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.scopes.microsoft import WORD_SCOPES
from nodes.core.dynamic_options import load_paginated_options, require_credential_token
from utils.ssrf import assert_exact_url_origin, guarded_async_client
import httpx
import json
import logging
import base64
import mimetypes
from nodes.oauth.microsoft_oauth import refresh_access_token, is_token_expired

logger = logging.getLogger(__name__)

GRAPH_API_ORIGIN = "https://graph.microsoft.com"

# ============================================================================
# Credentials
# ============================================================================


class WordOAuthCredential(BaseModel):
    """
    Microsoft OAuth credential for Word (via Graph API).

    Uses centralized Microsoft OAuth - credentials are automatically created
    when users connect their Microsoft account through the OAuth flow.

    Scopes required:
    - Files.ReadWrite.All: Full OneDrive file access (includes Word documents)
    - User.Read: Get user profile info
    """

    credential_type: Literal["microsoft_word_oauth"] = Field(
        "microsoft_word_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(..., description="OAuth access token")
    refresh_token: str = Field(..., description="OAuth refresh token for token renewal")
    expires_at: str = Field(..., description="Token expiry timestamp (ISO 8601)")
    email: str = Field(..., description="Microsoft account email address")

    model_config = ConfigDict(json_schema_extra={
        "x-credential-type": "oauth",
        "x-oauth-provider": "microsoft",  # Uses centralized Microsoft OAuth
        "x-oauth-scopes": [
            "https://graph.microsoft.com/Files.ReadWrite.All",  # Full file access
            "https://graph.microsoft.com/User.Read",  # User profile
        ],
        "x-credential-url": "https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps/ApplicationsListBlade",
        "x-credential-instructions": "Connect your Microsoft account to access Word documents. Uses Microsoft Graph API with OAuth 2.0.",
    })


# ============================================================================
# Config Models - Document Management (8 operations)
# ============================================================================


class WordListDocumentsConfig(BaseModel):
    """List Word documents from OneDrive"""

    operation: Literal["list_onedrive_documents"] = Field(
        "list_onedrive_documents",
        json_schema_extra={
            "const": "list_onedrive_documents",
            "ui:hidden": True,
            "x-category": "Document",
            "x-is-trigger": False,
            "x-display-name": "List Onedrive Documents",
        },
        title="List Onedrive Documents",
    )
    folder_id: Optional[str] = Field(
        None,
        title="Folder ID",
        description="Folder to search in (leave empty for entire OneDrive)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "folder_id",
                "placeholder": "Select a folder...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste folder ID",
            },
            "x-resource-type": "word_folder",
        },
    )
    folder_path: Optional[str] = Field(
        None,
        title="Folder Path",
        description="Path to folder (e.g., /Documents). Used if folder_id is empty.",
        json_schema_extra={"ui:placeholder": "/Documents"},
    )
    search_query: Optional[str] = Field(
        None,
        title="Search Query",
        description="Filter documents by name (e.g., 'report')",
        json_schema_extra={"ui:placeholder": "report"},
    )
    max_results: int = Field(
        100,
        title="Max Results",
        description="Maximum number of documents to return (1-999)",
        ge=1,
        le=999,
    )


class WordGetDocumentConfig(BaseModel):
    """Get Word document metadata"""

    operation: Literal["fetch_document_metadata"] = Field(
        "fetch_document_metadata",
        json_schema_extra={
            "const": "fetch_document_metadata",
            "ui:hidden": True,
            "x-category": "Document",
            "x-is-trigger": False,
            "x-display-name": "Fetch Document Metadata",
        },
        title="Fetch Document Metadata",
    )
    document_id: Optional[str] = Field(
        None,
        title="Document ID",
        description="Word document ID (leave empty to use path)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "document_id",
                "placeholder": "Select a document...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste document ID",
            },
            "x-resource-type": "word_document",
        },
    )
    document_path: Optional[str] = Field(
        None,
        title="Document Path",
        description="Path to document (e.g., /Documents/report.docx). Used if document_id is empty.",
        json_schema_extra={"ui:placeholder": "/Documents/report.docx"},
    )


class WordCreateDocumentConfig(BaseModel):
    """Create a new blank Word document"""

    operation: Literal["create_blank_document"] = Field(
        "create_blank_document",
        json_schema_extra={
            "const": "create_blank_document",
            "ui:hidden": True,
            "x-category": "Document",
            "x-is-trigger": False,
            "x-display-name": "Create Blank Document",
            "x-creates-resource": True,
            "x-resource-type": "word_document",
            "x-resource-id-path": "id",
        },
        title="Create Blank Document",
    )
    folder_id: Optional[str] = Field(
        None,
        title="Folder ID",
        description="Folder to create document in (leave empty for root)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "folder_id",
                "placeholder": "Select a folder...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste folder ID",
            },
            "x-resource-type": "word_folder",
        },
    )
    folder_path: Optional[str] = Field(
        None,
        title="Folder Path",
        description="Path to folder (e.g., /Documents). Used if folder_id is empty.",
        json_schema_extra={"ui:placeholder": "/Documents"},
    )
    document_name: str = Field(
        ...,
        title="Document Name",
        description="Name for the new document (e.g., 'Report.docx')",
        json_schema_extra={"ui:placeholder": "Report.docx"},
    )
    initial_content: Optional[str] = Field(
        None,
        title="Initial Content",
        description="Optional initial text content for the document",
        json_schema_extra={"ui:widget": "code_editor"},
    )


class WordUploadDocumentConfig(BaseModel):
    """Upload a Word document"""

    operation: Literal["upload_word_document"] = Field(
        "upload_word_document",
        json_schema_extra={
            "const": "upload_word_document",
            "ui:hidden": True,
            "x-category": "Document",
            "x-is-trigger": False,
            "x-display-name": "Upload Word Document",
            "x-creates-resource": True,
            "x-resource-type": "word_document",
            "x-resource-id-path": "id",
        },
        title="Upload Word Document",
    )
    folder_id: Optional[str] = Field(
        None,
        title="Folder ID",
        description="Folder to upload to (leave empty for root)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "folder_id",
                "placeholder": "Select a folder...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste folder ID",
            },
            "x-resource-type": "word_folder",
        },
    )
    folder_path: Optional[str] = Field(
        None,
        title="Folder Path",
        description="Path to folder (e.g., /Documents). Used if folder_id is empty.",
        json_schema_extra={"ui:placeholder": "/Documents"},
    )
    file_name: str = Field(
        ...,
        title="File Name",
        description="Name for the uploaded document (must end with .docx)",
        json_schema_extra={"ui:placeholder": "document.docx"},
    )
    file_content: str = Field(
        ...,
        title="File Content",
        description="Word document content (base64 encoded .docx file)",
        json_schema_extra={"ui:widget": "code_editor"},
    )


class WordCopyDocumentConfig(BaseModel):
    """Copy a Word document"""

    operation: Literal["copy_word_document"] = Field(
        "copy_word_document",
        json_schema_extra={
            "const": "copy_word_document",
            "ui:hidden": True,
            "x-category": "Document",
            "x-is-trigger": False,
            "x-display-name": "Copy Word Document",
        },
        title="Copy Word Document",
    )
    document_id: str = Field(
        ...,
        title="Document ID",
        description="Document to copy",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "document_id",
                "placeholder": "Select a document...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste document ID",
            },
            "x-resource-type": "word_document",
        },
    )
    destination_folder_id: Optional[str] = Field(
        None,
        title="Destination Folder ID",
        description="Folder to copy to (leave empty for same folder)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "destination_folder_id",
                "placeholder": "Select a folder...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste folder ID",
            },
            "x-resource-type": "word_folder",
        },
    )
    new_name: Optional[str] = Field(
        None,
        title="New Name",
        description="Name for the copy (leave empty to use 'Copy of <original>')",
        json_schema_extra={"ui:placeholder": "Copy of Report.docx"},
    )


class WordMoveDocumentConfig(BaseModel):
    """Move a Word document to a different folder"""

    operation: Literal["move_document_to_folder"] = Field(
        "move_document_to_folder",
        json_schema_extra={
            "const": "move_document_to_folder",
            "ui:hidden": True,
            "x-category": "Document",
            "x-is-trigger": False,
            "x-display-name": "Move Document to Folder",
        },
        title="Move Document to Folder",
    )
    document_id: str = Field(
        ...,
        title="Document ID",
        description="Document to move",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "document_id",
                "placeholder": "Select a document...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste document ID",
            },
            "x-resource-type": "word_document",
        },
    )
    destination_folder_id: str = Field(
        ...,
        title="Destination Folder ID",
        description="Folder to move to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "destination_folder_id",
                "placeholder": "Select a folder...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste folder ID",
            },
            "x-resource-type": "word_folder",
        },
    )


class WordRenameDocumentConfig(BaseModel):
    """Rename a Word document"""

    operation: Literal["rename_word_document"] = Field(
        "rename_word_document",
        json_schema_extra={
            "const": "rename_word_document",
            "ui:hidden": True,
            "x-category": "Document",
            "x-is-trigger": False,
            "x-display-name": "Rename Word Document",
        },
        title="Rename Word Document",
    )
    document_id: str = Field(
        ...,
        title="Document ID",
        description="Document to rename",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "document_id",
                "placeholder": "Select a document...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste document ID",
            },
            "x-resource-type": "word_document",
        },
    )
    new_name: str = Field(
        ...,
        title="New Name",
        description="New name for the document",
        json_schema_extra={"ui:placeholder": "New Report.docx"},
    )


class WordDeleteDocumentConfig(BaseModel):
    """Delete a Word document"""

    operation: Literal["delete_word_document"] = Field(
        "delete_word_document",
        json_schema_extra={
            "const": "delete_word_document",
            "ui:hidden": True,
            "x-category": "Document",
            "x-is-trigger": False,
            "x-display-name": "Delete Word Document",
        },
        title="Delete Word Document",
    )
    document_id: str = Field(
        ...,
        title="Document ID",
        description="Document to delete",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "document_id",
                "placeholder": "Select a document...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste document ID",
            },
            "x-resource-type": "word_document",
        },
    )
    permanent: bool = Field(
        False,
        title="Permanent Delete",
        description="If true, permanently delete (cannot be recovered). If false, move to recycle bin.",
    )


# ============================================================================
# Config Models - Content Operations (3 operations)
# ============================================================================


class WordDownloadDocumentConfig(BaseModel):
    """Download Word document content"""

    operation: Literal["download_document_content"] = Field(
        "download_document_content",
        json_schema_extra={
            "const": "download_document_content",
            "ui:hidden": True,
            "x-category": "Document",
            "x-is-trigger": False,
            "x-display-name": "Download Document Content",
        },
        title="Download Document Content",
    )
    document_id: str = Field(
        ...,
        title="Document ID",
        description="Document to download",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "document_id",
                "placeholder": "Select a document...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste document ID",
            },
            "x-resource-type": "word_document",
        },
    )
    return_format: str = Field(
        "base64",
        title="Return Format",
        description="How to return the content",
        json_schema_extra={
            "enum": ["base64", "download_url"],
            "enumNames": ["Base64 Encoded Content", "Download URL"],
            "x-enum-searchable": True,
        },
    )


class WordConvertToPDFConfig(BaseModel):
    """Convert Word document to PDF"""

    operation: Literal["convert_document_to_pdf"] = Field(
        "convert_document_to_pdf",
        json_schema_extra={
            "const": "convert_document_to_pdf",
            "ui:hidden": True,
            "x-category": "Document",
            "x-is-trigger": False,
            "x-display-name": "Convert Document to Pdf",
        },
        title="Convert Document to Pdf",
    )
    document_id: str = Field(
        ...,
        title="Document ID",
        description="Word document to convert",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "document_id",
                "placeholder": "Select a document...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste document ID",
            },
            "x-resource-type": "word_document",
        },
    )
    return_format: str = Field(
        "base64",
        title="Return Format",
        description="How to return the PDF",
        json_schema_extra={
            "enum": ["base64", "download_url"],
            "enumNames": ["Base64 Encoded PDF", "Download URL"],
            "x-enum-searchable": True,
        },
    )


class WordConvertToHTMLConfig(BaseModel):
    """Convert Word document to HTML"""

    operation: Literal["convert_document_to_html"] = Field(
        "convert_document_to_html",
        json_schema_extra={
            "const": "convert_document_to_html",
            "ui:hidden": True,
            "x-category": "Document",
            "x-is-trigger": False,
            "x-display-name": "Convert Document to Html",
        },
        title="Convert Document to Html",
    )
    document_id: str = Field(
        ...,
        title="Document ID",
        description="Word document to convert",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "document_id",
                "placeholder": "Select a document...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste document ID",
            },
            "x-resource-type": "word_document",
        },
    )
    return_format: str = Field(
        "content",
        title="Return Format",
        description="How to return the HTML",
        json_schema_extra={
            "enum": ["content", "download_url"],
            "enumNames": ["HTML Content", "Download URL"],
            "x-enum-searchable": True,
        },
    )


# ============================================================================
# Config Models - Sharing & Permissions (5 operations)
# ============================================================================


class WordCreateSharingLinkConfig(BaseModel):
    """Create a sharing link for a Word document"""

    operation: Literal["create_document_sharing_link"] = Field(
        "create_document_sharing_link",
        json_schema_extra={
            "const": "create_document_sharing_link",
            "ui:hidden": True,
            "x-category": "Document Permission",
            "x-is-trigger": False,
            "x-display-name": "Create Document Sharing Link",
        },
        title="Create Document Sharing Link",
    )
    document_id: str = Field(
        ...,
        title="Document ID",
        description="Document to share",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "document_id",
                "placeholder": "Select a document...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste document ID",
            },
            "x-resource-type": "word_document",
        },
    )
    link_type: str = Field(
        "view",
        title="Link Type",
        description="Type of sharing link to create",
        json_schema_extra={
            "enum": ["view", "edit", "embed"],
            "enumNames": ["View Only", "Edit", "Embed"],
            "x-enum-searchable": True,
        },
    )
    scope: str = Field(
        "anonymous",
        title="Scope",
        description="Who can access the link",
        json_schema_extra={
            "enum": ["anonymous", "organization"],
            "enumNames": ["Anyone with the link", "People in my organization"],
            "x-enum-searchable": True,
        },
    )
    expiration_datetime: Optional[str] = Field(
        None,
        title="Expiration Date",
        description="When the link expires (ISO 8601 format, e.g., 2024-12-31T23:59:59Z)",
        json_schema_extra={"ui:placeholder": "2024-12-31T23:59:59Z"},
    )


class WordListPermissionsConfig(BaseModel):
    """List permissions for a Word document"""

    operation: Literal["list_document_permissions"] = Field(
        "list_document_permissions",
        json_schema_extra={
            "const": "list_document_permissions",
            "ui:hidden": True,
            "x-category": "Document Permission",
            "x-is-trigger": False,
            "x-display-name": "List Document Permissions",
        },
        title="List Document Permissions",
    )
    document_id: str = Field(
        ...,
        title="Document ID",
        description="Document to list permissions for",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "document_id",
                "placeholder": "Select a document...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste document ID",
            },
            "x-resource-type": "word_document",
        },
    )


class WordAddPermissionConfig(BaseModel):
    """Share a Word document with a user or group"""

    operation: Literal["share_document_with_user"] = Field(
        "share_document_with_user",
        json_schema_extra={
            "const": "share_document_with_user",
            "ui:hidden": True,
            "x-category": "Document Permission",
            "x-is-trigger": False,
            "x-display-name": "Share Document with User",
        },
        title="Share Document with User",
    )
    document_id: str = Field(
        ...,
        title="Document ID",
        description="Document to share",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "document_id",
                "placeholder": "Select a document...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste document ID",
            },
            "x-resource-type": "word_document",
        },
    )
    recipient_email: str = Field(
        ...,
        title="Recipient Email",
        description="Email address of the person to share with",
        json_schema_extra={"ui:placeholder": "user@example.com"},
    )
    role: str = Field(
        "read",
        title="Permission Role",
        description="Access level to grant",
        json_schema_extra={
            "enum": ["read", "write"],
            "enumNames": ["Read (View Only)", "Write (Can Edit)"],
            "x-enum-searchable": True,
        },
    )
    send_notification: bool = Field(
        True,
        title="Send Email Notification",
        description="Send email notification to recipient",
    )
    message: Optional[str] = Field(
        None,
        title="Message",
        description="Optional message to include in notification email",
        json_schema_extra={"ui:widget": "code_editor", "ui:rows": 3},
    )


class WordUpdatePermissionConfig(BaseModel):
    """Update permission level for a user"""

    operation: Literal["update_document_permission_level"] = Field(
        "update_document_permission_level",
        json_schema_extra={
            "const": "update_document_permission_level",
            "ui:hidden": True,
            "x-category": "Document Permission",
            "x-is-trigger": False,
            "x-display-name": "Update Document Permission Level",
        },
        title="Update Document Permission Level",
    )
    document_id: str = Field(
        ...,
        title="Document ID",
        description="Document to update permissions for",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "document_id",
                "placeholder": "Select a document...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste document ID",
            },
            "x-resource-type": "word_document",
        },
    )
    permission_id: str = Field(
        ...,
        title="Permission ID",
        description="ID of the permission to update (from list_permissions)",
        json_schema_extra={"ui:placeholder": "aTowIy5mfG1lbWJlcnNoaXB8..."},
    )
    new_role: str = Field(
        ...,
        title="New Permission Role",
        description="New access level",
        json_schema_extra={
            "enum": ["read", "write"],
            "enumNames": ["Read (View Only)", "Write (Can Edit)"],
            "x-enum-searchable": True,
        },
    )


class WordRemovePermissionConfig(BaseModel):
    """Remove a sharing permission"""

    operation: Literal["remove_document_sharing_permission"] = Field(
        "remove_document_sharing_permission",
        json_schema_extra={
            "const": "remove_document_sharing_permission",
            "ui:hidden": True,
            "x-category": "Document Permission",
            "x-is-trigger": False,
            "x-display-name": "Remove Document Sharing Permission",
        },
        title="Remove Document Sharing Permission",
    )
    document_id: str = Field(
        ...,
        title="Document ID",
        description="Document to remove permissions from",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "document_id",
                "placeholder": "Select a document...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste document ID",
            },
            "x-resource-type": "word_document",
        },
    )
    permission_id: str = Field(
        ...,
        title="Permission ID",
        description="ID of the permission to remove (from list_permissions)",
        json_schema_extra={"ui:placeholder": "aTowIy5mfG1lbWJlcnNoaXB8..."},
    )


# ============================================================================
# Config Models - Version Control (3 operations)
# ============================================================================


class WordListVersionsConfig(BaseModel):
    """List version history for a Word document"""

    operation: Literal["list_document_version_history"] = Field(
        "list_document_version_history",
        json_schema_extra={
            "const": "list_document_version_history",
            "ui:hidden": True,
            "x-category": "Document Version",
            "x-is-trigger": False,
            "x-display-name": "List Document Version History",
        },
        title="List Document Version History",
    )
    document_id: str = Field(
        ...,
        title="Document ID",
        description="Document to list versions for",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "document_id",
                "placeholder": "Select a document...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste document ID",
            },
            "x-resource-type": "word_document",
        },
    )


class WordGetVersionConfig(BaseModel):
    """Get details of a specific document version"""

    operation: Literal["fetch_document_version"] = Field(
        "fetch_document_version",
        json_schema_extra={
            "const": "fetch_document_version",
            "ui:hidden": True,
            "x-category": "Document Version",
            "x-is-trigger": False,
            "x-display-name": "Fetch Document Version",
        },
        title="Fetch Document Version",
    )
    document_id: str = Field(
        ...,
        title="Document ID",
        description="Document ID",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "document_id",
                "placeholder": "Select a document...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste document ID",
            },
            "x-resource-type": "word_document",
        },
    )
    version_id: str = Field(
        ...,
        title="Version ID",
        description="Version ID (from list_versions)",
        json_schema_extra={"ui:placeholder": "1.0"},
    )
    return_format: str = Field(
        "metadata",
        title="Return Format",
        description="What to return",
        json_schema_extra={
            "enum": ["metadata", "content_base64", "download_url"],
            "enumNames": ["Metadata Only", "Base64 Content", "Download URL"],
            "x-enum-searchable": True,
        },
    )


class WordRestoreVersionConfig(BaseModel):
    """Restore a previous version of a Word document"""

    operation: Literal["restore_document_to_previous_version"] = Field(
        "restore_document_to_previous_version",
        json_schema_extra={
            "const": "restore_document_to_previous_version",
            "ui:hidden": True,
            "x-category": "Document Version",
            "x-is-trigger": False,
            "x-display-name": "Restore Document to Previous Version",
        },
        title="Restore Document to Previous Version",
    )
    document_id: str = Field(
        ...,
        title="Document ID",
        description="Document to restore",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "document_id",
                "placeholder": "Select a document...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste document ID",
            },
            "x-resource-type": "word_document",
        },
    )
    version_id: str = Field(
        ...,
        title="Version ID",
        description="Version to restore (from list_versions)",
        json_schema_extra={"ui:placeholder": "1.0"},
    )


# ============================================================================
# Config Models - Advanced Operations (3 operations)
# ============================================================================


class WordGetPreviewLinkConfig(BaseModel):
    """Get an embeddable preview link for a Word document"""

    operation: Literal["fetch_document_preview_link"] = Field(
        "fetch_document_preview_link",
        json_schema_extra={
            "const": "fetch_document_preview_link",
            "ui:hidden": True,
            "x-category": "Document",
            "x-is-trigger": False,
            "x-display-name": "Fetch Document Preview Link",
        },
        title="Fetch Document Preview Link",
    )
    document_id: str = Field(
        ...,
        title="Document ID",
        description="Document to preview",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "document_id",
                "placeholder": "Select a document...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste document ID",
            },
            "x-resource-type": "word_document",
        },
    )
    allow_edit: bool = Field(
        False,
        title="Allow Editing",
        description="If true, preview link allows editing (requires write permission)",
    )


class WordGetThumbnailConfig(BaseModel):
    """Get a thumbnail image of a Word document"""

    operation: Literal["fetch_document_thumbnail"] = Field(
        "fetch_document_thumbnail",
        json_schema_extra={
            "const": "fetch_document_thumbnail",
            "ui:hidden": True,
            "x-category": "Document",
            "x-is-trigger": False,
            "x-display-name": "Fetch Document Thumbnail",
        },
        title="Fetch Document Thumbnail",
    )
    document_id: str = Field(
        ...,
        title="Document ID",
        description="Document to get thumbnail for",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "document_id",
                "placeholder": "Select a document...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste document ID",
            },
            "x-resource-type": "word_document",
        },
    )
    size: str = Field(
        "medium",
        title="Thumbnail Size",
        description="Size of the thumbnail",
        json_schema_extra={
            "enum": ["small", "medium", "large"],
            "enumNames": ["Small (96x96)", "Medium (176x176)", "Large (800x800)"],
            "x-enum-searchable": True,
        },
    )
    return_format: str = Field(
        "base64",
        title="Return Format",
        description="How to return the thumbnail",
        json_schema_extra={
            "enum": ["base64", "url"],
            "enumNames": ["Base64 Encoded Image", "Image URL"],
            "x-enum-searchable": True,
        },
    )


class WordSearchDocumentsConfig(BaseModel):
    """Search for Word documents across OneDrive"""

    operation: Literal["search_onedrive_documents"] = Field(
        "search_onedrive_documents",
        json_schema_extra={
            "const": "search_onedrive_documents",
            "ui:hidden": True,
            "x-category": "Document",
            "x-is-trigger": False,
            "x-display-name": "Search Onedrive Documents",
        },
        title="Search Onedrive Documents",
    )
    query: str = Field(
        ...,
        title="Search Query",
        description="Text to search for (searches file names and content)",
        json_schema_extra={"ui:placeholder": "quarterly report"},
    )
    folder_id: Optional[str] = Field(
        None,
        title="Folder ID",
        description="Limit search to specific folder (leave empty for entire OneDrive)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "folder_id",
                "placeholder": "Select a folder...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste folder ID",
            },
            "x-resource-type": "word_folder",
        },
    )
    max_results: int = Field(
        100,
        title="Max Results",
        description="Maximum number of results to return (1-999)",
        ge=1,
        le=999,
    )


# ============================================================================
# Union Config
# ============================================================================

WordConfig = Annotated[
    Union[
        # Document Management (8)
        WordListDocumentsConfig,
        WordGetDocumentConfig,
        WordCreateDocumentConfig,
        WordUploadDocumentConfig,
        WordCopyDocumentConfig,
        WordMoveDocumentConfig,
        WordRenameDocumentConfig,
        WordDeleteDocumentConfig,
        # Content Operations (3)
        WordDownloadDocumentConfig,
        WordConvertToPDFConfig,
        WordConvertToHTMLConfig,
        # Sharing & Permissions (5)
        WordCreateSharingLinkConfig,
        WordListPermissionsConfig,
        WordAddPermissionConfig,
        WordUpdatePermissionConfig,
        WordRemovePermissionConfig,
        # Version Control (3)
        WordListVersionsConfig,
        WordGetVersionConfig,
        WordRestoreVersionConfig,
        # Advanced Operations (3)
        WordGetPreviewLinkConfig,
        WordGetThumbnailConfig,
        WordSearchDocumentsConfig,
    ],
    Discriminator("operation"),
]

# ============================================================================
# Node Implementation
# ============================================================================


class WordNodeConfig(NodeConfig[WordConfig, WordOAuthCredential]):
    """Configuration for Word node with centralized Microsoft OAuth"""

    pass


class WordNode(WorkflowNode):
    """
    Word document automation via Microsoft Graph API.

    Supports 22 operations across 5 categories:
    - Document Management: list, get, create, upload, copy, move, rename, delete
    - Content Operations: download, convert to PDF, convert to HTML
    - Sharing & Permissions: create link, list/add/update/remove permissions
    - Version Control: list versions, get version, restore version
    - Advanced: preview link, thumbnail, search
    """

    edit_examples = [
        "Convert the annual report Word document to PDF for distribution",
        "Create a shareable link to the contract document for legal review",
        "Search for all policy documents modified after January 2024",
        "List version history and restore the previous draft before edits",
        "Download the presentation template and upload to shared folder",
        "Move completed proposals to the Archived Proposals folder",
        "Generate a thumbnail for the team handbook cover page",
    ]

    name = "word"
    display_name = "Microsoft Word"
    config_model = WordNodeConfig

    GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"

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

    async def _ensure_fresh_token(self, credentials: WordOAuthCredential) -> str:
        """Return a valid Word access token, refreshing + persisting if expired."""
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

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute Word operation based on config"""
        try:
            # Refresh token if needed
            access_token = await self._ensure_fresh_token(self.config.credentials)

            # Route to appropriate handler based on action
            action = self.config.config.operation

            # Document Management
            if action == "list_onedrive_documents":
                return await self._list_documents(self.config.config, access_token)
            elif action == "fetch_document_metadata":
                return await self._get_document(self.config.config, access_token)
            elif action == "create_blank_document":
                return await self._create_document(self.config.config, access_token)
            elif action == "upload_word_document":
                return await self._upload_document(self.config.config, access_token)
            elif action == "copy_word_document":
                return await self._copy_document(self.config.config, access_token)
            elif action == "move_document_to_folder":
                return await self._move_document(self.config.config, access_token)
            elif action == "rename_word_document":
                return await self._rename_document(self.config.config, access_token)
            elif action == "delete_word_document":
                return await self._delete_document(self.config.config, access_token)

            # Content Operations
            elif action == "download_document_content":
                return await self._download_document(self.config.config, access_token)
            elif action == "convert_document_to_pdf":
                return await self._convert_to_pdf(self.config.config, access_token)
            elif action == "convert_document_to_html":
                return await self._convert_to_html(self.config.config, access_token)

            # Sharing & Permissions
            elif action == "create_document_sharing_link":
                return await self._create_sharing_link(self.config.config, access_token)
            elif action == "list_document_permissions":
                return await self._list_permissions(self.config.config, access_token)
            elif action == "share_document_with_user":
                return await self._add_permission(self.config.config, access_token)
            elif action == "update_document_permission_level":
                return await self._update_permission(self.config.config, access_token)
            elif action == "remove_document_sharing_permission":
                return await self._remove_permission(self.config.config, access_token)

            # Version Control
            elif action == "list_document_version_history":
                return await self._list_versions(self.config.config, access_token)
            elif action == "fetch_document_version":
                return await self._get_version(self.config.config, access_token)
            elif action == "restore_document_to_previous_version":
                return await self._restore_version(self.config.config, access_token)

            # Advanced Operations
            elif action == "fetch_document_preview_link":
                return await self._get_preview_link(self.config.config, access_token)
            elif action == "fetch_document_thumbnail":
                return await self._get_thumbnail(self.config.config, access_token)
            elif action == "search_onedrive_documents":
                return await self._search_documents(self.config.config, access_token)

            else:
                raise ValueError(f"Unknown action: {action}")

        except Exception as e:
            logger.error(f"Word node error: {e}", exc_info=True)
            raise

    # ========================================================================
    # Helper Methods
    # ========================================================================

    def _get_headers(self, access_token: str) -> Dict[str, str]:
        """Get headers for Graph API requests"""
        return {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

    def _build_item_path(self, item_id: Optional[str], item_path: Optional[str]) -> str:
        """Build the Graph API path for an item (by ID or path)"""
        if item_id:
            return f"/me/drive/items/{item_id}"
        elif item_path:
            # Ensure path starts with /
            if not item_path.startswith("/"):
                item_path = "/" + item_path
            return f"/me/drive/root:{item_path}"
        else:
            raise ValueError("Either item_id or item_path must be provided")

    def _is_word_file(self, name: str) -> bool:
        """Check if file is a Word document"""
        word_extensions = [".docx", ".doc"]
        return any(name.lower().endswith(ext) for ext in word_extensions)

    async def _make_request(
        self, method: str, url: str, headers: Dict[str, str], **kwargs
    ) -> httpx.Response:
        """Make HTTP request with error handling"""
        assert_exact_url_origin(url, GRAPH_API_ORIGIN)
        async with httpx.AsyncClient() as client:
            response = await client.request(method, url, headers=headers, **kwargs)

            if response.status_code >= 400:
                error_detail = response.text
                try:
                    error_json = response.json()
                    error_detail = error_json.get("error", {}).get(
                        "message", error_detail
                    )
                except:
                    pass

                raise Exception(
                    f"Graph API error ({response.status_code}): {error_detail}"
                )

            return response

    # ========================================================================
    # Document Management Operations
    # ========================================================================

    async def _list_documents(
        self, config: WordListDocumentsConfig, access_token: str
    ) -> Dict[str, Any]:
        """List Word documents from OneDrive"""
        headers = self._get_headers(access_token)

        # Build base URL
        if config.folder_id:
            base_url = (
                f"{self.GRAPH_API_BASE}/me/drive/items/{config.folder_id}/children"
            )
        elif config.folder_path:
            folder_path = (
                config.folder_path
                if config.folder_path.startswith("/")
                else "/" + config.folder_path
            )
            base_url = f"{self.GRAPH_API_BASE}/me/drive/root:{folder_path}:/children"
        else:
            base_url = f"{self.GRAPH_API_BASE}/me/drive/root/children"

        # Add query parameters
        params = {"$top": str(config.max_results)}

        response = await self._make_request("GET", base_url, headers, params=params)
        data = response.json()

        # Filter for Word documents only
        all_items = data.get("value", [])
        word_docs = [
            item
            for item in all_items
            if not item.get("folder") and self._is_word_file(item.get("name", ""))
        ]

        # Further filter by search query if provided
        if config.search_query:
            query_lower = config.search_query.lower()
            word_docs = [
                doc for doc in word_docs if query_lower in doc.get("name", "").lower()
            ]

        return {
            "documents": word_docs,
            "count": len(word_docs),
            "has_more": "@odata.nextLink" in data,
        }

    async def _get_document(
        self, config: WordGetDocumentConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get Word document metadata"""
        headers = self._get_headers(access_token)
        item_path = self._build_item_path(config.document_id, config.document_path)
        url = f"{self.GRAPH_API_BASE}{item_path}"

        response = await self._make_request("GET", url, headers)
        return response.json()

    async def _create_document(
        self, config: WordCreateDocumentConfig, access_token: str
    ) -> Dict[str, Any]:
        """Create a new blank Word document"""
        headers = self._get_headers(access_token)

        # Ensure file name ends with .docx
        file_name = config.document_name
        if not file_name.lower().endswith(".docx"):
            file_name = f"{file_name}.docx"

        # Build parent path
        if config.folder_id:
            parent_path = f"/me/drive/items/{config.folder_id}"
        elif config.folder_path:
            folder_path = (
                config.folder_path
                if config.folder_path.startswith("/")
                else "/" + config.folder_path
            )
            parent_path = f"/me/drive/root:{folder_path}"
        else:
            parent_path = "/me/drive/root"

        # Create minimal Word document content
        # For simplicity, we'll create a blank file or with initial text
        if config.initial_content:
            # Create a simple text file and upload it
            # Note: This won't be a proper .docx but will work for basic text
            content = config.initial_content.encode("utf-8")
        else:
            # Empty content
            content = b""

        # Upload the file
        upload_url = f"{self.GRAPH_API_BASE}{parent_path}:/{file_name}:/content"
        upload_headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }

        response = await self._make_request(
            "PUT", upload_url, upload_headers, content=content
        )
        return response.json()

    async def _upload_document(
        self, config: WordUploadDocumentConfig, access_token: str
    ) -> Dict[str, Any]:
        """Upload a Word document"""
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }

        # Ensure file name ends with .docx
        file_name = config.file_name
        if not file_name.lower().endswith(".docx") and not file_name.lower().endswith(
            ".doc"
        ):
            file_name = f"{file_name}.docx"

        # Build parent path
        if config.folder_id:
            parent_path = f"/me/drive/items/{config.folder_id}"
        elif config.folder_path:
            folder_path = (
                config.folder_path
                if config.folder_path.startswith("/")
                else "/" + config.folder_path
            )
            parent_path = f"/me/drive/root:{folder_path}"
        else:
            parent_path = "/me/drive/root"

        # Decode base64 content
        try:
            content = base64.b64decode(config.file_content)
        except Exception as e:
            raise ValueError(f"Invalid base64 content: {e}")

        # Upload
        upload_url = f"{self.GRAPH_API_BASE}{parent_path}:/{file_name}:/content"
        response = await self._make_request("PUT", upload_url, headers, content=content)
        return response.json()

    async def _copy_document(
        self, config: WordCopyDocumentConfig, access_token: str
    ) -> Dict[str, Any]:
        """Copy a Word document"""
        headers = self._get_headers(access_token)
        url = f"{self.GRAPH_API_BASE}/me/drive/items/{config.document_id}/copy"

        body = {}
        if config.destination_folder_id:
            body["parentReference"] = {"id": config.destination_folder_id}
        if config.new_name:
            body["name"] = config.new_name

        response = await self._make_request("POST", url, headers, json=body)

        # Copy operation is async, returns 202 Accepted with monitor URL
        if response.status_code == 202:
            monitor_url = response.headers.get("Location")
            return {
                "status": "copying",
                "monitor_url": monitor_url,
                "message": "Copy operation started. Poll the monitor_url to check status.",
            }

        return response.json()

    async def _move_document(
        self, config: WordMoveDocumentConfig, access_token: str
    ) -> Dict[str, Any]:
        """Move a Word document"""
        headers = self._get_headers(access_token)
        url = f"{self.GRAPH_API_BASE}/me/drive/items/{config.document_id}"

        body = {"parentReference": {"id": config.destination_folder_id}}

        response = await self._make_request("PATCH", url, headers, json=body)
        return response.json()

    async def _rename_document(
        self, config: WordRenameDocumentConfig, access_token: str
    ) -> Dict[str, Any]:
        """Rename a Word document"""
        headers = self._get_headers(access_token)
        url = f"{self.GRAPH_API_BASE}/me/drive/items/{config.document_id}"

        body = {"name": config.new_name}

        response = await self._make_request("PATCH", url, headers, json=body)
        return response.json()

    async def _delete_document(
        self, config: WordDeleteDocumentConfig, access_token: str
    ) -> Dict[str, Any]:
        """Delete a Word document"""
        headers = self._get_headers(access_token)

        if config.permanent:
            # Permanent delete
            url = f"{self.GRAPH_API_BASE}/me/drive/items/{config.document_id}/permanentDelete"
            response = await self._make_request("POST", url, headers)
        else:
            # Move to recycle bin
            url = f"{self.GRAPH_API_BASE}/me/drive/items/{config.document_id}"
            response = await self._make_request("DELETE", url, headers)

        return {"status": "deleted", "document_id": config.document_id}

    # ========================================================================
    # Content Operations
    # ========================================================================

    async def _download_document(
        self, config: WordDownloadDocumentConfig, access_token: str
    ) -> Dict[str, Any]:
        """Download Word document content"""
        headers = self._get_headers(access_token)
        url = f"{self.GRAPH_API_BASE}/me/drive/items/{config.document_id}/content"

        if config.return_format == "download_url":
            # Get download URL without downloading
            metadata_url = f"{self.GRAPH_API_BASE}/me/drive/items/{config.document_id}"
            response = await self._make_request("GET", metadata_url, headers)
            data = response.json()
            return {
                "download_url": data.get("@microsoft.graph.downloadUrl"),
                "name": data.get("name"),
                "size": data.get("size"),
            }
        else:
            # Download the .docx file
            from nodes.core.binary_output import BinaryOutput

            response = await self._make_request("GET", url, headers)
            return {
                "content": BinaryOutput(
                    data=response.content,
                    content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    filename=f"{config.document_id}.docx",
                )
            }

    async def _convert_to_pdf(
        self, config: WordConvertToPDFConfig, access_token: str
    ) -> Dict[str, Any]:
        """Convert Word document to PDF"""
        from nodes.core.binary_output import BinaryOutput

        headers = self._get_headers(access_token)
        url = f"{self.GRAPH_API_BASE}/me/drive/items/{config.document_id}/content?format=pdf"

        # Graph API doesn't expose a PDF download URL without converting, so both
        # return_format branches download the rendered PDF bytes.
        response = await self._make_request("GET", url, headers)
        return {
            "pdf": BinaryOutput(
                data=response.content,
                content_type="application/pdf",
                filename=f"{config.document_id}.pdf",
                metadata={"note": "PDF generated from Word document"},
            )
        }

    async def _convert_to_html(
        self, config: WordConvertToHTMLConfig, access_token: str
    ) -> Dict[str, Any]:
        """Convert Word document to HTML"""
        headers = self._get_headers(access_token)
        url = f"{self.GRAPH_API_BASE}/me/drive/items/{config.document_id}/content?format=html"

        response = await self._make_request("GET", url, headers)

        if config.return_format == "content":
            # Inline HTML the user reads/templates — leave as text.
            return {"html_content": response.text, "size": len(response.content)}
        else:
            # download_url: deliver the rendered HTML as a downloadable .html file.
            from nodes.core.binary_output import BinaryOutput

            return {
                "html": BinaryOutput(
                    data=response.content,
                    content_type="text/html",
                    filename=f"{config.document_id}.html",
                    metadata={"note": "HTML generated from Word document"},
                )
            }

    # ========================================================================
    # Sharing & Permissions Operations
    # ========================================================================

    async def _create_sharing_link(
        self, config: WordCreateSharingLinkConfig, access_token: str
    ) -> Dict[str, Any]:
        """Create a sharing link"""
        headers = self._get_headers(access_token)
        url = f"{self.GRAPH_API_BASE}/me/drive/items/{config.document_id}/createLink"

        body = {"type": config.link_type, "scope": config.scope}

        if config.expiration_datetime:
            body["expirationDateTime"] = config.expiration_datetime

        response = await self._make_request("POST", url, headers, json=body)
        return response.json()

    async def _list_permissions(
        self, config: WordListPermissionsConfig, access_token: str
    ) -> Dict[str, Any]:
        """List permissions for a document"""
        headers = self._get_headers(access_token)
        url = f"{self.GRAPH_API_BASE}/me/drive/items/{config.document_id}/permissions"

        response = await self._make_request("GET", url, headers)
        return response.json()

    async def _add_permission(
        self, config: WordAddPermissionConfig, access_token: str
    ) -> Dict[str, Any]:
        """Share document with a user"""
        headers = self._get_headers(access_token)
        url = f"{self.GRAPH_API_BASE}/me/drive/items/{config.document_id}/invite"

        body = {
            "recipients": [{"email": config.recipient_email}],
            "message": config.message or "",
            "requireSignIn": True,
            "sendInvitation": config.send_notification,
            "roles": [config.role],
        }

        response = await self._make_request("POST", url, headers, json=body)
        return response.json()

    async def _update_permission(
        self, config: WordUpdatePermissionConfig, access_token: str
    ) -> Dict[str, Any]:
        """Update permission level"""
        headers = self._get_headers(access_token)
        url = f"{self.GRAPH_API_BASE}/me/drive/items/{config.document_id}/permissions/{config.permission_id}"

        body = {"roles": [config.new_role]}

        response = await self._make_request("PATCH", url, headers, json=body)
        return response.json()

    async def _remove_permission(
        self, config: WordRemovePermissionConfig, access_token: str
    ) -> Dict[str, Any]:
        """Remove a permission"""
        headers = self._get_headers(access_token)
        url = f"{self.GRAPH_API_BASE}/me/drive/items/{config.document_id}/permissions/{config.permission_id}"

        response = await self._make_request("DELETE", url, headers)
        return {"status": "removed", "permission_id": config.permission_id}

    # ========================================================================
    # Version Control Operations
    # ========================================================================

    async def _list_versions(
        self, config: WordListVersionsConfig, access_token: str
    ) -> Dict[str, Any]:
        """List document version history"""
        headers = self._get_headers(access_token)
        url = f"{self.GRAPH_API_BASE}/me/drive/items/{config.document_id}/versions"

        response = await self._make_request("GET", url, headers)
        return response.json()

    async def _get_version(
        self, config: WordGetVersionConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get specific version details"""
        headers = self._get_headers(access_token)

        if config.return_format == "metadata":
            url = f"{self.GRAPH_API_BASE}/me/drive/items/{config.document_id}/versions/{config.version_id}"
            response = await self._make_request("GET", url, headers)
            return response.json()
        else:
            # Download version content
            url = f"{self.GRAPH_API_BASE}/me/drive/items/{config.document_id}/versions/{config.version_id}/content"
            response = await self._make_request("GET", url, headers)

            if config.return_format == "content_base64":
                from nodes.core.binary_output import BinaryOutput

                return {
                    "content": BinaryOutput(
                        data=response.content,
                        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        filename=f"{config.document_id}-{config.version_id}.docx",
                        metadata={"version_id": config.version_id},
                    )
                }
            else:  # download_url
                # Graph API redirects to download URL
                return {
                    "download_url": str(response.url),
                    "version_id": config.version_id,
                }

    async def _restore_version(
        self, config: WordRestoreVersionConfig, access_token: str
    ) -> Dict[str, Any]:
        """Restore a previous version"""
        headers = self._get_headers(access_token)
        url = f"{self.GRAPH_API_BASE}/me/drive/items/{config.document_id}/versions/{config.version_id}/restoreVersion"

        response = await self._make_request("POST", url, headers)
        return response.json()

    # ========================================================================
    # Advanced Operations
    # ========================================================================

    async def _get_preview_link(
        self, config: WordGetPreviewLinkConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get embeddable preview link"""
        headers = self._get_headers(access_token)
        url = f"{self.GRAPH_API_BASE}/me/drive/items/{config.document_id}/preview"

        body = {}
        if config.allow_edit:
            body["viewer"] = "edit"

        response = await self._make_request(
            "POST", url, headers, json=body if body else None
        )
        return response.json()

    async def _get_thumbnail(
        self, config: WordGetThumbnailConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get document thumbnail"""
        headers = self._get_headers(access_token)
        url = f"{self.GRAPH_API_BASE}/me/drive/items/{config.document_id}/thumbnails"

        response = await self._make_request("GET", url, headers)
        data = response.json()

        # Get the requested size
        thumbnails = data.get("value", [])
        if not thumbnails:
            raise Exception("No thumbnails available for this document")

        thumbnail_set = thumbnails[0]
        thumbnail_data = thumbnail_set.get(config.size)

        if not thumbnail_data:
            raise Exception(f"Thumbnail size '{config.size}' not available")

        if config.return_format == "url":
            return {
                "thumbnail_url": thumbnail_data.get("url"),
                "width": thumbnail_data.get("width"),
                "height": thumbnail_data.get("height"),
            }
        else:
            # Download the thumbnail image.
            from nodes.core.binary_output import BinaryOutput

            thumb_url = thumbnail_data.get("url")
            if not isinstance(thumb_url, str) or not thumb_url:
                raise ValueError("Microsoft Graph did not return a thumbnail URL")
            async with guarded_async_client() as client:
                thumb_response = await client.get(thumb_url)
                thumb_response.raise_for_status()
                content_type = (
                    thumb_response.headers.get("content-type") or "image/jpeg"
                )
                ext = mimetypes.guess_extension(content_type.split(";")[0]) or ".jpg"
                return {
                    "thumbnail": BinaryOutput(
                        data=thumb_response.content,
                        content_type=content_type,
                        filename=f"{config.document_id}-thumbnail{ext}",
                        metadata={
                            "width": thumbnail_data.get("width"),
                            "height": thumbnail_data.get("height"),
                        },
                    )
                }

    async def _search_documents(
        self, config: WordSearchDocumentsConfig, access_token: str
    ) -> Dict[str, Any]:
        """Search for Word documents"""
        headers = self._get_headers(access_token)

        # Build search URL
        if config.folder_id:
            base_url = f"{self.GRAPH_API_BASE}/me/drive/items/{config.folder_id}/search(q='{config.query}')"
        else:
            base_url = f"{self.GRAPH_API_BASE}/me/drive/root/search(q='{config.query}')"

        params = {"$top": str(config.max_results)}

        response = await self._make_request("GET", base_url, headers, params=params)
        data = response.json()

        # Filter for Word documents only
        all_items = data.get("value", [])
        word_docs = [
            item
            for item in all_items
            if not item.get("folder") and self._is_word_file(item.get("name", ""))
        ]

        return {"documents": word_docs, "count": len(word_docs), "query": config.query}

    # ========================================================================
    # Dynamic Options (for dropdown population)
    # ========================================================================

    #: OAuth scope requirements per operation (nodes/scopes/microsoft.py).
    scope_registry = WORD_SCOPES
    connection_evidence = ConnectionEvidence(
        field="document_id",
        noun="documents",
    )

    @classmethod
    def get_config_model(cls):
        return WordNodeConfig

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Load dynamic options for dropdowns (documents and folders).

        Microsoft Graph's ``/me/drive`` children endpoints have no native
        name search, so both branches delegate to
        :func:`load_paginated_options` which paginates with ``@odata.nextLink``
        and applies the shared substring filter.
        """
        access_token = require_credential_token(
            credential_data.get("access_token"),
            "Connect a Microsoft account to load Word documents and folders",
        )
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        if field_name == "document_id":
            folder_id = (context or {}).get("folder_id")
            base_url = (
                f"{cls.GRAPH_API_BASE}/me/drive/items/{folder_id}/children"
                if folder_id
                else f"{cls.GRAPH_API_BASE}/me/drive/root/children"
            )
            return await load_paginated_options(
                lambda cursor: cls._graph_fetch_page(
                    base_url,
                    headers,
                    cursor,
                    item_to_option=cls._word_doc_to_option,
                ),
                page_token=page_token,
                search=search,
                log_label="WordNode.load_field_options(document_id)",
            )
        elif field_name in ("folder_id", "destination_folder_id"):
            base_url = f"{cls.GRAPH_API_BASE}/me/drive/root/children"
            return await load_paginated_options(
                lambda cursor: cls._graph_fetch_page(
                    base_url,
                    headers,
                    cursor,
                    item_to_option=cls._word_folder_to_option,
                ),
                page_token=page_token,
                search=search,
                log_label=f"WordNode.load_field_options({field_name})",
            )
        else:
            return {"options": [], "next_page_token": None}

    @staticmethod
    def _word_doc_to_option(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Map a Graph drive item to a document option, or None to skip."""
        if item.get("folder"):
            return None
        name = item.get("name", "")
        if not (name.lower().endswith(".docx") or name.lower().endswith(".doc")):
            return None
        return {
            "value": item["id"],
            "label": name,
            "description": f"Modified: {item.get('lastModifiedDateTime', 'Unknown')}",
        }

    @staticmethod
    def _word_folder_to_option(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Map a Graph drive item to a folder option, or None to skip."""
        if not item.get("folder"):
            return None
        return {
            "value": item["id"],
            "label": item.get("name", ""),
            "description": f"Items: {item.get('folder', {}).get('childCount', 0)}",
        }

    @classmethod
    async def _graph_fetch_page(
        cls,
        base_url: str,
        headers: Dict[str, str],
        cursor: Optional[str],
        *,
        item_to_option,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """Fetch one Graph drive-children page; returns (options, next_url).

        Microsoft Graph encodes the next-page state in ``@odata.nextLink``
        (a fully-qualified URL with the cursor query baked in), so the
        cursor we hand back IS the next URL — first-page request uses
        ``base_url`` with ``$top``, later pages just hit the link verbatim.
        """
        url = cursor or base_url
        assert_exact_url_origin(url, GRAPH_API_ORIGIN)
        params = None if cursor else {"$top": "100"}
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
        options: List[Dict[str, Any]] = []
        for item in data.get("value", []) or []:
            opt = item_to_option(item)
            if opt is not None:
                options.append(opt)
        return options, data.get("@odata.nextLink")
