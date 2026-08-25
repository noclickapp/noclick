"""
Outlook workflow node implementation.
Comprehensive Microsoft 365 integration for Mail, Calendar, and Contacts.
Supports 90 operations across all Outlook services via Microsoft Graph API.
Uses Microsoft OAuth for authentication.

Operations:
- Mail: 38 operations (send, read, reply, forward, drafts, folders, attachments, rules, categories, MIME)
- Calendar: 41 operations — events (CRUD, invitations, forward, reminders, instances,
  attachments), calendars (CRUD, calendarView, delta), calendar groups (CRUD),
  sharing permissions (CRUD + allowed roles), free/busy + meeting times, reminder
  view, and an "on calendar event change" Graph change-notification webhook trigger
- Contacts: 10 operations (contacts CRUD, contact folders)
"""

import base64
import hashlib
import time
import logging
from typing import Dict, Any, Optional, Union, Type, List, Literal, Annotated
from pydantic import BaseModel, ConfigDict, Discriminator, Field, field_validator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.scopes.microsoft import OUTLOOK_SCOPES
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin
from nodes.oauth.microsoft_oauth import is_token_expired, refresh_access_token
from utils.email_body import ensure_html_body

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"

# Graph calendar-event change-notification subscriptions expire; renew well
# within the ~3-day (4230 min) cap. The trigger's webhook is the wake signal.
SUBSCRIPTION_LIFETIME_MINUTES = 4230

# Outbound attachment caps (Graph rejects >150MB total; we cap far lower).
OUTBOUND_ATTACHMENT_MAX_BYTES = 10 * 1024 * 1024
OUTBOUND_ATTACHMENT_TOTAL_BYTES = 20 * 1024 * 1024


async def _graph_call(
    access_token: str,
    method: str,
    path: str,
    *,
    json_body: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Shared Microsoft Graph request for the calendar operations. Returns the
    parsed JSON body ({} for 204/empty). Raises ValueError on a non-2xx status,
    matching this node's existing error convention."""
    url = f"{GRAPH_API_BASE}{path}"
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.request(
            method, url, headers=headers, json=json_body, params=params
        )
    if response.status_code >= 400:
        err = (response.json() if response.content else {}).get("error", {})
        msg = err.get("message", response.text) if isinstance(err, dict) else response.text
        raise ValueError(f"Microsoft Graph API error: {msg}")
    if response.status_code == 204 or not response.content:
        return {}
    try:
        return response.json()
    except Exception:
        return {"raw": response.text}


# ============================================================================
# Outlook Node Credential Schema
# ============================================================================


class OutlookOAuthCredential(BaseModel):
    """
    OAuth credential for Outlook/Microsoft Graph access.
    Tokens are obtained via OAuth flow, not entered manually.
    """

    credential_type: Literal["microsoft_outlook_oauth"] = Field(
        "microsoft_outlook_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ..., title="Access Token", description="OAuth 2.0 access token from Microsoft"
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
        title="Microsoft Account",
        description="Email address of the connected Microsoft account",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "microsoft",
            "x-oauth-scopes": [
                # Mail permissions
                "https://graph.microsoft.com/Mail.Send",
                "https://graph.microsoft.com/Mail.Read",
                "https://graph.microsoft.com/Mail.ReadWrite",
                "https://graph.microsoft.com/MailboxSettings.ReadWrite",
                # Calendar permissions
                "https://graph.microsoft.com/Calendars.Read",
                "https://graph.microsoft.com/Calendars.ReadWrite",
                "https://graph.microsoft.com/Calendars.ReadWrite.Shared",
                # Contacts permissions
                "https://graph.microsoft.com/Contacts.Read",
                "https://graph.microsoft.com/Contacts.ReadWrite",
                # User and offline access
                "https://graph.microsoft.com/User.Read",
                "offline_access",
            ],
        }
    )


# ============================================================================
# Outlook Node Configuration Models
# ============================================================================


class OutlookSendConfig(BaseModel):
    """Configuration for sending an email"""

    operation: Literal["send_email_message"] = Field(
        default="send_email_message",
        title="Send Email Message",
        description="Send an email",
        json_schema_extra={
            "ui:hidden": True,
            "const": "send_email_message",
            "x-category": "Email Message",
            "x-is-trigger": False,
            "x-display-name": "Send Email Message",
            "x-keywords": [
                "compose email",
                "email someone",
                "write email",
                "send mail",
                "new message",
            ],
        },
    )
    to: str = Field(
        ...,
        title="To",
        description="Recipient email address(es), comma-separated for multiple",
        json_schema_extra={"placeholder": "recipient@example.com"},
    )
    subject: str = Field(
        ...,
        title="Subject",
        description="Email subject line",
        json_schema_extra={"placeholder": "Enter subject..."},
    )
    body: str = Field(
        ...,
        title="Body",
        description="Email body content (HTML supported)",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "Enter email body...",
        },
    )
    body_type: str = Field(
        "HTML",
        title="Body Type",
        description="Content type of the email body",
        json_schema_extra={"ui:hidden": True},
    )
    cc: Optional[str] = Field(
        None,
        title="CC",
        description="CC recipients (comma-separated)",
        json_schema_extra={"placeholder": "cc@example.com (optional)"},
    )
    bcc: Optional[str] = Field(
        None,
        title="BCC",
        description="BCC recipients (comma-separated)",
        json_schema_extra={"placeholder": "bcc@example.com (optional)"},
    )
    save_to_sent: bool = Field(
        True,
        title="Save to Sent Items",
        description="Save a copy of the sent email to Sent Items folder",
    )
    attachments: List[str] = Field(
        default_factory=list,
        title="Attachments",
        description="Files to attach: workflow resource IDs or URLs (10MB per file, 20MB total)",
        json_schema_extra={"ui:widget": "list", "placeholder": "{{node.resource_id}}"},
    )

    @field_validator("attachments", mode="before")
    @classmethod
    def filter_attachments(cls, v: Any) -> list:
        if not isinstance(v, list):
            return []
        return [a for a in v if isinstance(a, str) and a.strip()]


class OutlookReadConfig(BaseModel):
    """Configuration for reading emails from inbox"""

    operation: Literal["read_inbox_emails"] = Field(
        default="read_inbox_emails",
        title="Read Inbox Emails",
        description="Read emails from inbox",
        json_schema_extra={
            "ui:hidden": True,
            "const": "read_inbox_emails",
            "x-category": "Email Message",
            "x-is-trigger": False,
            "x-display-name": "Read Inbox Emails",
            "x-keywords": [
                "check inbox",
                "read emails",
                "list inbox messages",
                "incoming mail",
                "browse inbox",
            ],
        },
    )
    folder: str = Field(
        "inbox",
        title="Folder",
        description="Mail folder to read from",
        json_schema_extra={
            "enum": [
                "inbox",
                "drafts",
                "sentitems",
                "deleteditems",
                "junkemail",
                "archive",
            ],
            "enumNames": [
                "Inbox",
                "Drafts",
                "Sent Items",
                "Deleted Items",
                "Junk Email",
                "Archive",
            ],
            "x-enum-searchable": True,
        },
    )
    filter_query: Optional[str] = Field(
        None,
        title="Filter",
        description="OData filter query. Examples: isRead eq false, importance eq 'high', hasAttachments eq true",
        json_schema_extra={"placeholder": "e.g. isRead eq false"},
    )
    search_query: Optional[str] = Field(
        None,
        title="Search",
        description="Search query to find emails (searches subject, body, sender)",
        json_schema_extra={"placeholder": "Search term (optional)"},
    )
    max_results: int = Field(
        10,
        title="Max Results",
        description="Maximum number of emails to retrieve (1-50)",
        ge=1,
        le=50,
    )
    include_body: str = Field(
        "true",
        title="Include Body",
        description="Include email body content in results",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    order_by: Optional[str] = Field(
        "receivedDateTime desc",
        title="Order By",
        description="Sort order for results",
        json_schema_extra={
            "enum": [
                "receivedDateTime desc",
                "receivedDateTime asc",
                "subject asc",
                "subject desc",
                "",
            ],
            "enumNames": [
                "Newest First",
                "Oldest First",
                "Subject A-Z",
                "Subject Z-A",
                "Default (no sort)",
            ],
            "x-enum-searchable": True,
        },
    )


class OutlookReplyConfig(BaseModel):
    """Configuration for replying to an email"""

    operation: Literal["reply_to_email_message"] = Field(
        default="reply_to_email_message",
        title="Reply to Email Message",
        description="Reply to an email",
        json_schema_extra={
            "ui:hidden": True,
            "const": "reply_to_email_message",
            "x-category": "Email Message",
            "x-is-trigger": False,
            "x-display-name": "Reply to Email Message",
            "x-keywords": [
                "reply to email",
                "respond to sender",
                "send reply",
                "answer email",
            ],
        },
    )
    message_id: str = Field(
        ...,
        title="Message ID",
        description="ID of the message to reply to",
        json_schema_extra={"placeholder": "Message ID from previous read operation"},
    )
    body: str = Field(
        ...,
        title="Reply Body",
        description="Reply message content (HTML supported)",
        json_schema_extra={"ui:widget": "textarea", "placeholder": "Enter reply..."},
    )
    reply_all: bool = Field(
        False,
        title="Reply All",
        description="Reply to all recipients instead of just the sender",
    )


class OutlookForwardConfig(BaseModel):
    """Configuration for forwarding an email"""

    operation: Literal["forward_email_message"] = Field(
        default="forward_email_message",
        title="Forward Email Message",
        description="Forward an email",
        json_schema_extra={
            "ui:hidden": True,
            "const": "forward_email_message",
            "x-category": "Email Message",
            "x-is-trigger": False,
            "x-display-name": "Forward Email Message",
            "x-keywords": [
                "forward email",
                "forward message",
                "pass along email",
                "send forward",
            ],
        },
    )
    message_id: str = Field(
        ...,
        title="Message ID",
        description="ID of the message to forward",
        json_schema_extra={"placeholder": "Message ID from previous read operation"},
    )
    to: str = Field(
        ...,
        title="Forward To",
        description="Recipient email address(es), comma-separated for multiple",
        json_schema_extra={"placeholder": "recipient@example.com"},
    )
    comment: Optional[str] = Field(
        None,
        title="Comment",
        description="Optional message to include with the forwarded email",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "Optional comment...",
        },
    )


class OutlookGetMessageConfig(BaseModel):
    """Configuration for getting a specific email by ID"""

    operation: Literal["get_email_message"] = Field(
        default="get_email_message",
        title="Get Email Message",
        description="Get a specific email by ID",
        json_schema_extra={
            "ui:hidden": True,
            "const": "get_email_message",
            "x-category": "Email Message",
            "x-is-trigger": False,
            "x-display-name": "Get Email Message",
            "x-keywords": [
                "open email",
                "fetch email by id",
                "single email",
                "read one message",
                "email details",
            ],
        },
    )
    message_id: str = Field(
        ...,
        title="Message ID",
        description="ID of the message to retrieve",
        json_schema_extra={"placeholder": "Message ID from previous read operation"},
    )
    include_attachments: bool = Field(
        False,
        title="Include Attachments",
        description="Include attachment metadata in the response",
    )


class OutlookMarkReadConfig(BaseModel):
    """Configuration for marking an email as read or unread"""

    operation: Literal["mark_email_as_read_unread"] = Field(
        default="mark_email_as_read_unread",
        title="Mark Email As Read Unread",
        description="Mark an email as read or unread",
        json_schema_extra={
            "ui:hidden": True,
            "const": "mark_email_as_read_unread",
            "x-category": "Email Message",
            "x-is-trigger": False,
            "x-display-name": "Mark Email As Read Unread",
            "x-keywords": [
                "mark as read",
                "mark unread",
                "flag as seen",
                "mark message read",
            ],
        },
    )
    message_id: str = Field(
        ...,
        title="Message ID",
        description="ID of the message to mark",
        json_schema_extra={"placeholder": "Message ID from previous read operation"},
    )
    is_read: bool = Field(
        True,
        title="Mark as Read",
        description="True to mark as read, False to mark as unread",
    )


class OutlookDeleteConfig(BaseModel):
    """Configuration for deleting an email"""

    operation: Literal["delete_email_message"] = Field(
        default="delete_email_message",
        title="Delete Email Message",
        description="Delete an email",
        json_schema_extra={
            "ui:hidden": True,
            "const": "delete_email_message",
            "x-category": "Email Message",
            "x-is-trigger": False,
            "x-display-name": "Delete Email Message",
            "x-keywords": [
                "delete email",
                "trash email",
                "remove message",
                "discard email",
            ],
        },
    )
    message_id: str = Field(
        ...,
        title="Message ID",
        description="ID of the message to delete",
        json_schema_extra={"placeholder": "Message ID from previous read operation"},
    )
    permanent: bool = Field(
        False,
        title="Permanent Delete",
        description="Permanently delete instead of moving to Deleted Items",
    )


class OutlookMoveConfig(BaseModel):
    """Configuration for moving an email to a different folder"""

    operation: Literal["move_email_to_folder"] = Field(
        default="move_email_to_folder",
        title="Move Email to Folder",
        description="Move an email to a different folder",
        json_schema_extra={
            "ui:hidden": True,
            "const": "move_email_to_folder",
            "x-category": "Email Message",
            "x-is-trigger": False,
            "x-display-name": "Move Email to Folder",
            "x-keywords": [
                "move email",
                "file email",
                "move to folder",
                "relocate message",
                "sort into folder",
            ],
        },
    )
    message_id: str = Field(
        ...,
        title="Message ID",
        description="ID of the message to move",
        json_schema_extra={"placeholder": "Message ID from previous read operation"},
    )
    destination_folder: str = Field(
        ...,
        title="Destination Folder",
        description="Folder to move the message to",
        json_schema_extra={
            "enum": [
                "inbox",
                "drafts",
                "sentitems",
                "deleteditems",
                "junkemail",
                "archive",
            ]
        },
    )


class OutlookCreateDraftConfig(BaseModel):
    """Configuration for creating an email draft"""

    operation: Literal["create_email_draft"] = Field(
        default="create_email_draft",
        title="Create Email Draft",
        description="Create an email draft",
        json_schema_extra={
            "ui:hidden": True,
            "const": "create_email_draft",
            "x-category": "Email Message",
            "x-is-trigger": False,
            "x-display-name": "Create Email Draft",
            "x-keywords": [
                "save draft",
                "draft email",
                "compose draft",
                "new draft message",
                "write draft",
            ],
        },
    )
    to: str = Field(
        ...,
        title="To",
        description="Recipient email address(es), comma-separated for multiple",
        json_schema_extra={"placeholder": "recipient@example.com"},
    )
    subject: str = Field(
        ...,
        title="Subject",
        description="Email subject line",
        json_schema_extra={"placeholder": "Enter subject..."},
    )
    body: str = Field(
        ...,
        title="Body",
        description="Email body content (HTML supported)",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "Enter email body...",
        },
    )
    cc: Optional[str] = Field(
        None,
        title="CC",
        description="CC recipients (comma-separated)",
        json_schema_extra={"placeholder": "cc@example.com (optional)"},
    )
    bcc: Optional[str] = Field(
        None,
        title="BCC",
        description="BCC recipients (comma-separated)",
        json_schema_extra={"placeholder": "bcc@example.com (optional)"},
    )
    attachments: List[str] = Field(
        default_factory=list,
        title="Attachments",
        description="Files to attach: workflow resource IDs or URLs (10MB per file, 20MB total)",
        json_schema_extra={"ui:widget": "list", "placeholder": "{{node.resource_id}}"},
    )

    @field_validator("attachments", mode="before")
    @classmethod
    def filter_attachments(cls, v: Any) -> list:
        if not isinstance(v, list):
            return []
        return [a for a in v if isinstance(a, str) and a.strip()]


class OutlookListFoldersConfig(BaseModel):
    """Configuration for listing mail folders"""

    operation: Literal["list_mail_folders"] = Field(
        default="list_mail_folders",
        title="List Mail Folders",
        description="List all mail folders",
        json_schema_extra={
            "ui:hidden": True,
            "const": "list_mail_folders",
            "x-category": "Mail Folder",
            "x-is-trigger": False,
            "x-display-name": "List Mail Folders",
            "x-keywords": [
                "list folders",
                "mailbox folders",
                "show mail folders",
                "browse folders",
            ],
        },
    )
    include_child_folders: bool = Field(
        False,
        title="Include Child Folders",
        description="Include nested/child folders in the response",
    )


class OutlookCreateFolderConfig(BaseModel):
    """Configuration for creating a new mail folder"""

    operation: Literal["create_mail_folder"] = Field(
        default="create_mail_folder",
        title="Create Mail Folder",
        description="Create a new mail folder",
        json_schema_extra={
            "ui:hidden": True,
            "const": "create_mail_folder",
            "x-category": "Mail Folder",
            "x-is-trigger": False,
            "x-display-name": "Create Mail Folder",
            "x-keywords": [
                "new folder",
                "make mail folder",
                "add folder",
                "create mailbox folder",
            ],
        },
    )
    folder_name: str = Field(
        ...,
        title="Folder Name",
        description="Name for the new folder",
        json_schema_extra={"placeholder": "My New Folder"},
    )
    parent_folder: str = Field(
        "inbox",
        title="Parent Folder",
        description="Parent folder to create the new folder in",
        json_schema_extra={
            "enum": [
                "inbox",
                "drafts",
                "sentitems",
                "deleteditems",
                "junkemail",
                "archive",
                "msgfolderroot",
            ]
        },
    )


class OutlookGetAttachmentsConfig(BaseModel):
    """Configuration for getting attachments from an email"""

    operation: Literal["get_email_attachments"] = Field(
        default="get_email_attachments",
        title="Get Email Attachments",
        description="Get attachments from an email",
        json_schema_extra={
            "ui:hidden": True,
            "const": "get_email_attachments",
            "x-category": "Email Message",
            "x-is-trigger": False,
            "x-display-name": "Get Email Attachments",
            "x-keywords": [
                "download attachments",
                "fetch attachments",
                "email files",
                "get message attachments",
            ],
        },
    )
    message_id: str = Field(
        ...,
        title="Message ID",
        description="ID of the message to get attachments from",
        json_schema_extra={"placeholder": "Message ID from previous read operation"},
    )
    include_content: bool = Field(
        False,
        title="Include Content",
        description="Include the actual attachment content (base64 encoded)",
    )
    extract_text: str = Field(
        "false",
        title="Extract Text",
        description="Extract readable text from document attachments instead of returning raw base64",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    allow_ai_ocr: str = Field(
        "true",
        title="Allow AI OCR",
        description="OCR scanned PDFs with a vision model when there is no text layer (billed per page)",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class OutlookGetMailboxSettingsConfig(BaseModel):
    """Configuration for getting mailbox settings"""

    operation: Literal["get_mailbox_settings"] = Field(
        default="get_mailbox_settings",
        title="Get Mailbox Settings",
        description="Get mailbox settings (auto-reply, timezone, etc.)",
        json_schema_extra={
            "ui:hidden": True,
            "const": "get_mailbox_settings",
            "x-category": "Mailbox",
            "x-is-trigger": False,
            "x-display-name": "Get Mailbox Settings",
            "x-keywords": [
                "mailbox settings",
                "account preferences",
                "mail config",
                "inbox settings",
                "timezone language",
            ],
        },
    )


class OutlookUpdateAutoReplyConfig(BaseModel):
    """Configuration for updating auto-reply settings"""

    operation: Literal["update_auto_reply_settings"] = Field(
        default="update_auto_reply_settings",
        title="Update Auto Reply Settings",
        description="Update auto-reply (out of office) settings",
        json_schema_extra={
            "ui:hidden": True,
            "const": "update_auto_reply_settings",
            "x-category": "Mailbox",
            "x-is-trigger": False,
            "x-display-name": "Update Auto Reply Settings",
            "x-keywords": [
                "out of office",
                "vacation responder",
                "automatic reply",
                "ooo message",
                "set away message",
                "auto responder",
            ],
        },
    )
    enabled: bool = Field(
        True, title="Enable Auto-Reply", description="Enable or disable auto-reply"
    )
    internal_message: Optional[str] = Field(
        None,
        title="Internal Message",
        description="Auto-reply message for people within your organization",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "I am currently out of office...",
        },
    )
    external_message: Optional[str] = Field(
        None,
        title="External Message",
        description="Auto-reply message for people outside your organization",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "I am currently out of office...",
        },
    )
    external_audience: str = Field(
        "all",
        title="External Audience",
        description="Who outside the organization receives auto-replies",
        json_schema_extra={"enum": ["none", "contactsOnly", "all"]},
    )
    start_date: Optional[str] = Field(
        None,
        title="Start Date",
        description="Start date/time for auto-reply (ISO 8601 format)",
        json_schema_extra={"placeholder": "2024-01-01T00:00:00Z (optional)"},
    )
    end_date: Optional[str] = Field(
        None,
        title="End Date",
        description="End date/time for auto-reply (ISO 8601 format)",
        json_schema_extra={"placeholder": "2024-01-15T00:00:00Z (optional)"},
    )


# ============================================================================
# MAIL OPERATIONS - Advanced Message Operations
# ============================================================================


class OutlookCopyMessageConfig(BaseModel):
    """Configuration for copying a message to another folder"""

    operation: Literal["copy_message_to_folder"] = Field(
        default="copy_message_to_folder",
        json_schema_extra={
            "const": "copy_message_to_folder",
            "ui:hidden": True,
            "x-category": "Email Message",
            "x-is-trigger": False,
            "x-display-name": "Copy Message to Folder",
            "x-keywords": [
                "copy email",
                "duplicate message",
                "copy to folder",
                "copy message",
            ],
        },
        title="Copy Message to Folder",
    )
    message_id: str = Field(
        ...,
        title="Message ID",
        description="ID of the message to copy",
        json_schema_extra={"placeholder": "Message ID from previous operation"},
    )
    destination_folder: str = Field(
        ...,
        title="Destination Folder",
        description="Folder to copy the message to",
        json_schema_extra={
            "enum": [
                "inbox",
                "drafts",
                "sentitems",
                "deleteditems",
                "junkemail",
                "archive",
            ]
        },
    )


class OutlookUpdateMessageConfig(BaseModel):
    """Configuration for updating message properties"""

    operation: Literal["update_email_message_properties"] = Field(
        default="update_email_message_properties",
        json_schema_extra={
            "const": "update_email_message_properties",
            "ui:hidden": True,
            "x-category": "Email Message",
            "x-is-trigger": False,
            "x-display-name": "Update Email Message Properties",
            "x-keywords": [
                "edit email properties",
                "change message flags",
                "update importance",
                "set email category",
                "edit message metadata",
            ],
        },
        title="Update Email Message Properties",
    )
    message_id: str = Field(
        ...,
        title="Message ID",
        description="ID of the message to update",
        json_schema_extra={"placeholder": "Message ID from previous operation"},
    )
    subject: Optional[str] = Field(
        None,
        title="Subject",
        description="Update the email subject",
        json_schema_extra={"placeholder": "New subject (optional)"},
    )
    importance: Optional[str] = Field(
        None,
        title="Importance",
        description="Set message importance level",
        json_schema_extra={"enum": ["low", "normal", "high"]},
    )
    categories: Optional[str] = Field(
        None,
        title="Categories",
        description="Comma-separated category names",
        json_schema_extra={"placeholder": "Red category, Blue category (optional)"},
    )
    is_read: Optional[bool] = Field(
        None, title="Is Read", description="Mark as read or unread"
    )


class OutlookSendDraftConfig(BaseModel):
    """Configuration for sending an existing draft"""

    operation: Literal["send_email_draft"] = Field(
        default="send_email_draft",
        json_schema_extra={
            "const": "send_email_draft",
            "ui:hidden": True,
            "x-category": "Email Message",
            "x-is-trigger": False,
            "x-display-name": "Send Email Draft",
            "x-keywords": [
                "send saved draft",
                "send existing draft",
                "ship draft",
                "dispatch draft",
            ],
        },
        title="Send Email Draft",
    )
    message_id: str = Field(
        ...,
        title="Draft ID",
        description="ID of the draft message to send",
        json_schema_extra={"placeholder": "Draft ID from create_draft operation"},
    )


class OutlookCreateReplyDraftConfig(BaseModel):
    """Configuration for creating a reply draft"""

    operation: Literal["create_reply_draft"] = Field(
        default="create_reply_draft",
        json_schema_extra={
            "const": "create_reply_draft",
            "ui:hidden": True,
            "x-category": "Email Message",
            "x-is-trigger": False,
            "x-display-name": "Create Reply Draft",
            "x-keywords": [
                "draft a reply",
                "save reply draft",
                "prepare reply",
                "reply draft",
            ],
        },
        title="Create Reply Draft",
    )
    message_id: str = Field(
        ...,
        title="Message ID",
        description="ID of the message to reply to",
        json_schema_extra={"placeholder": "Message ID from previous operation"},
    )


class OutlookCreateReplyAllDraftConfig(BaseModel):
    """Configuration for creating a reply-all draft"""

    operation: Literal["create_reply_all_draft"] = Field(
        default="create_reply_all_draft",
        json_schema_extra={
            "const": "create_reply_all_draft",
            "ui:hidden": True,
            "x-category": "Email Message",
            "x-is-trigger": False,
            "x-display-name": "Create Reply All Draft",
            "x-keywords": [
                "reply all draft",
                "draft reply to all",
                "respond to everyone draft",
                "reply everyone",
            ],
        },
        title="Create Reply All Draft",
    )
    message_id: str = Field(
        ...,
        title="Message ID",
        description="ID of the message to reply all to",
        json_schema_extra={"placeholder": "Message ID from previous operation"},
    )


class OutlookCreateForwardDraftConfig(BaseModel):
    """Configuration for creating a forward draft"""

    operation: Literal["create_forward_draft"] = Field(
        default="create_forward_draft",
        json_schema_extra={
            "const": "create_forward_draft",
            "ui:hidden": True,
            "x-category": "Email Message",
            "x-is-trigger": False,
            "x-display-name": "Create Forward Draft",
            "x-keywords": [
                "draft a forward",
                "save forward draft",
                "prepare forward",
                "forward draft",
            ],
        },
        title="Create Forward Draft",
    )
    message_id: str = Field(
        ...,
        title="Message ID",
        description="ID of the message to forward",
        json_schema_extra={"placeholder": "Message ID from previous operation"},
    )


# ============================================================================
# MAIL OPERATIONS - Attachment Operations
# ============================================================================


class OutlookAddAttachmentConfig(BaseModel):
    """Configuration for adding an attachment to a message"""

    operation: Literal["add_attachment_to_message"] = Field(
        default="add_attachment_to_message",
        json_schema_extra={
            "const": "add_attachment_to_message",
            "ui:hidden": True,
            "x-category": "Email Message",
            "x-is-trigger": False,
            "x-display-name": "Add Attachment to Message",
            "x-keywords": [
                "attach file",
                "add attachment",
                "include file",
                "attach document to email",
            ],
        },
        title="Add Attachment to Message",
    )
    message_id: str = Field(
        ...,
        title="Message ID",
        description="ID of the message to add attachment to",
        json_schema_extra={"placeholder": "Message ID (usually a draft)"},
    )
    file_name: str = Field(
        ...,
        title="File Name",
        description="Name of the attachment file",
        json_schema_extra={"placeholder": "document.pdf"},
    )
    content_base64: str = Field(
        ...,
        title="File Content (Base64)",
        description="Base64-encoded file content",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "Base64-encoded file data...",
        },
    )
    content_type: str = Field(
        "application/octet-stream",
        title="Content Type",
        description="MIME type of the attachment",
        json_schema_extra={"placeholder": "application/pdf"},
    )


class OutlookDeleteAttachmentConfig(BaseModel):
    """Configuration for deleting an attachment"""

    operation: Literal["delete_attachment_from_message"] = Field(
        default="delete_attachment_from_message",
        json_schema_extra={
            "const": "delete_attachment_from_message",
            "ui:hidden": True,
            "x-category": "Email Message",
            "x-is-trigger": False,
            "x-display-name": "Delete Attachment from Message",
            "x-keywords": [
                "remove attachment",
                "detach file",
                "delete email attachment",
                "strip attachment",
            ],
        },
        title="Delete Attachment from Message",
    )
    message_id: str = Field(
        ...,
        title="Message ID",
        description="ID of the message containing the attachment",
        json_schema_extra={"placeholder": "Message ID"},
    )
    attachment_id: str = Field(
        ...,
        title="Attachment ID",
        description="ID of the attachment to delete",
        json_schema_extra={"placeholder": "Attachment ID from get_attachments"},
    )


# ============================================================================
# MAIL OPERATIONS - Folder Operations
# ============================================================================


class OutlookUpdateFolderConfig(BaseModel):
    """Configuration for updating a folder"""

    operation: Literal["update_mail_folder"] = Field(
        default="update_mail_folder",
        json_schema_extra={
            "const": "update_mail_folder",
            "ui:hidden": True,
            "x-category": "Mail Folder",
            "x-is-trigger": False,
            "x-display-name": "Update Mail Folder",
            "x-keywords": [
                "rename folder",
                "edit folder",
                "change folder name",
                "modify mail folder",
            ],
        },
        title="Update Mail Folder",
    )
    folder_id: str = Field(
        ...,
        title="Folder ID",
        description="ID of the folder to update",
        json_schema_extra={"placeholder": "Folder ID from list_folders"},
    )
    display_name: str = Field(
        ...,
        title="New Name",
        description="New display name for the folder",
        json_schema_extra={"placeholder": "New Folder Name"},
    )


class OutlookDeleteFolderConfig(BaseModel):
    """Configuration for deleting a folder"""

    operation: Literal["delete_mail_folder"] = Field(
        default="delete_mail_folder",
        json_schema_extra={
            "const": "delete_mail_folder",
            "ui:hidden": True,
            "x-category": "Mail Folder",
            "x-is-trigger": False,
            "x-display-name": "Delete Mail Folder",
            "x-keywords": ["remove folder", "trash folder", "delete mail folder"],
        },
        title="Delete Mail Folder",
    )
    folder_id: str = Field(
        ...,
        title="Folder ID",
        description="ID of the folder to delete",
        json_schema_extra={"placeholder": "Folder ID from list_folders"},
    )


class OutlookMoveFolderConfig(BaseModel):
    """Configuration for moving a folder"""

    operation: Literal["move_mail_folder"] = Field(
        default="move_mail_folder",
        json_schema_extra={
            "const": "move_mail_folder",
            "ui:hidden": True,
            "x-category": "Mail Folder",
            "x-is-trigger": False,
            "x-display-name": "Move Mail Folder",
            "x-keywords": [
                "move folder",
                "nest folder",
                "relocate folder",
                "move mailbox folder",
            ],
        },
        title="Move Mail Folder",
    )
    folder_id: str = Field(
        ...,
        title="Folder ID",
        description="ID of the folder to move",
        json_schema_extra={"placeholder": "Folder ID from list_folders"},
    )
    destination_folder_id: str = Field(
        ...,
        title="Destination Folder ID",
        description="ID of the destination parent folder",
        json_schema_extra={"placeholder": "Parent folder ID"},
    )


class OutlookCopyFolderConfig(BaseModel):
    """Configuration for copying a folder"""

    operation: Literal["copy_mail_folder"] = Field(
        default="copy_mail_folder",
        json_schema_extra={
            "const": "copy_mail_folder",
            "ui:hidden": True,
            "x-category": "Mail Folder",
            "x-is-trigger": False,
            "x-display-name": "Copy Mail Folder",
            "x-keywords": ["copy folder", "duplicate folder", "clone mail folder"],
        },
        title="Copy Mail Folder",
    )
    folder_id: str = Field(
        ...,
        title="Folder ID",
        description="ID of the folder to copy",
        json_schema_extra={"placeholder": "Folder ID from list_folders"},
    )
    destination_folder_id: str = Field(
        ...,
        title="Destination Folder ID",
        description="ID of the destination parent folder",
        json_schema_extra={"placeholder": "Parent folder ID"},
    )


# ============================================================================
# MAIL OPERATIONS - Message Rules
# ============================================================================


class OutlookListMessageRulesConfig(BaseModel):
    """Configuration for listing inbox rules"""

    operation: Literal["list_inbox_rules"] = Field(
        default="list_inbox_rules",
        json_schema_extra={
            "const": "list_inbox_rules",
            "ui:hidden": True,
            "x-category": "Inbox Rule",
            "x-is-trigger": False,
            "x-display-name": "List Inbox Rules",
            "x-keywords": [
                "list rules",
                "show filters",
                "mail rules",
                "inbox filters",
                "automation rules",
            ],
        },
        title="List Inbox Rules",
    )


class OutlookGetMessageRuleConfig(BaseModel):
    """Configuration for getting a specific rule"""

    operation: Literal["get_inbox_rule"] = Field(
        default="get_inbox_rule",
        json_schema_extra={
            "const": "get_inbox_rule",
            "ui:hidden": True,
            "x-category": "Inbox Rule",
            "x-is-trigger": False,
            "x-display-name": "Get Inbox Rule",
            "x-keywords": [
                "open rule",
                "single inbox rule",
                "rule details",
                "fetch one filter",
            ],
        },
        title="Get Inbox Rule",
    )
    rule_id: str = Field(
        ...,
        title="Rule ID",
        description="ID of the rule to retrieve",
        json_schema_extra={"placeholder": "Rule ID from list_message_rules"},
    )


class OutlookCreateMessageRuleConfig(BaseModel):
    """Configuration for creating an inbox rule"""

    operation: Literal["create_inbox_rule"] = Field(
        default="create_inbox_rule",
        json_schema_extra={
            "const": "create_inbox_rule",
            "ui:hidden": True,
            "x-category": "Inbox Rule",
            "x-is-trigger": False,
            "x-display-name": "Create Inbox Rule",
            "x-keywords": [
                "new rule",
                "make filter",
                "add inbox rule",
                "create mail filter",
                "auto sort rule",
            ],
        },
        title="Create Inbox Rule",
    )
    display_name: str = Field(
        ...,
        title="Rule Name",
        description="Display name for the rule",
        json_schema_extra={"placeholder": "Move emails from sender..."},
    )
    conditions: str = Field(
        ...,
        title="Conditions (JSON)",
        description="JSON object defining rule conditions",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": '{"fromAddresses": [{"emailAddress": {"address": "sender@example.com"}}]}',
        },
    )
    actions: str = Field(
        ...,
        title="Actions (JSON)",
        description="JSON object defining rule actions",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": '{"moveToFolder": "inbox"}',
        },
    )


class OutlookUpdateMessageRuleConfig(BaseModel):
    """Configuration for updating an inbox rule"""

    operation: Literal["update_inbox_rule"] = Field(
        default="update_inbox_rule",
        json_schema_extra={
            "const": "update_inbox_rule",
            "ui:hidden": True,
            "x-category": "Inbox Rule",
            "x-is-trigger": False,
            "x-display-name": "Update Inbox Rule",
            "x-keywords": [
                "edit rule",
                "change filter",
                "modify inbox rule",
                "update mail filter",
            ],
        },
        title="Update Inbox Rule",
    )
    rule_id: str = Field(
        ...,
        title="Rule ID",
        description="ID of the rule to update",
        json_schema_extra={"placeholder": "Rule ID from list_message_rules"},
    )
    display_name: Optional[str] = Field(
        None,
        title="Rule Name",
        description="New display name for the rule",
        json_schema_extra={"placeholder": "New rule name (optional)"},
    )
    conditions: Optional[str] = Field(
        None,
        title="Conditions (JSON)",
        description="JSON object defining rule conditions",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "New conditions JSON (optional)",
        },
    )
    actions: Optional[str] = Field(
        None,
        title="Actions (JSON)",
        description="JSON object defining rule actions",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "New actions JSON (optional)",
        },
    )


class OutlookDeleteMessageRuleConfig(BaseModel):
    """Configuration for deleting an inbox rule"""

    operation: Literal["delete_inbox_rule"] = Field(
        default="delete_inbox_rule",
        json_schema_extra={
            "const": "delete_inbox_rule",
            "ui:hidden": True,
            "x-category": "Inbox Rule",
            "x-is-trigger": False,
            "x-display-name": "Delete Inbox Rule",
            "x-keywords": ["remove rule", "delete filter", "trash inbox rule"],
        },
        title="Delete Inbox Rule",
    )
    rule_id: str = Field(
        ...,
        title="Rule ID",
        description="ID of the rule to delete",
        json_schema_extra={"placeholder": "Rule ID from list_message_rules"},
    )


# ============================================================================
# MAIL OPERATIONS - Categories
# ============================================================================


class OutlookListCategoriesConfig(BaseModel):
    """Configuration for listing master categories"""

    operation: Literal["list_message_categories"] = Field(
        default="list_message_categories",
        json_schema_extra={
            "const": "list_message_categories",
            "ui:hidden": True,
            "x-category": "Message Category",
            "x-is-trigger": False,
            "x-display-name": "List Message Categories",
            "x-keywords": [
                "list categories",
                "show color categories",
                "master categories",
                "browse categories",
                "tags list",
            ],
        },
        title="List Message Categories",
    )


class OutlookGetCategoryConfig(BaseModel):
    """Configuration for getting a specific category"""

    operation: Literal["get_message_category"] = Field(
        default="get_message_category",
        json_schema_extra={
            "const": "get_message_category",
            "ui:hidden": True,
            "x-category": "Message Category",
            "x-is-trigger": False,
            "x-display-name": "Get Message Category",
            "x-keywords": [
                "open category",
                "single category",
                "category details",
                "fetch one tag",
            ],
        },
        title="Get Message Category",
    )
    category_id: str = Field(
        ...,
        title="Category ID",
        description="ID of the category to retrieve",
        json_schema_extra={"placeholder": "Category ID from list_categories"},
    )


class OutlookCreateCategoryConfig(BaseModel):
    """Configuration for creating a category"""

    operation: Literal["create_message_category"] = Field(
        default="create_message_category",
        json_schema_extra={
            "const": "create_message_category",
            "ui:hidden": True,
            "x-category": "Message Category",
            "x-is-trigger": False,
            "x-display-name": "Create Message Category",
            "x-keywords": [
                "new category",
                "add color category",
                "make tag",
                "create label color",
            ],
        },
        title="Create Message Category",
    )
    display_name: str = Field(
        ...,
        title="Category Name",
        description="Display name for the category",
        json_schema_extra={"placeholder": "My Category"},
    )
    color: str = Field(
        "preset0",
        title="Color",
        description="Color preset for the category",
        json_schema_extra={
            "enum": [
                "preset0",
                "preset1",
                "preset2",
                "preset3",
                "preset4",
                "preset5",
                "preset6",
                "preset7",
                "preset8",
                "preset9",
                "preset10",
                "preset11",
                "preset12",
                "preset13",
                "preset14",
                "preset15",
                "preset16",
                "preset17",
                "preset18",
                "preset19",
                "preset20",
                "preset21",
                "preset22",
                "preset23",
                "preset24",
            ]
        },
    )


class OutlookUpdateCategoryConfig(BaseModel):
    """Configuration for updating a category"""

    operation: Literal["update_message_category"] = Field(
        default="update_message_category",
        json_schema_extra={
            "const": "update_message_category",
            "ui:hidden": True,
            "x-category": "Message Category",
            "x-is-trigger": False,
            "x-display-name": "Update Message Category",
            "x-keywords": [
                "edit category",
                "rename category",
                "change category color",
                "modify tag",
            ],
        },
        title="Update Message Category",
    )
    category_id: str = Field(
        ...,
        title="Category ID",
        description="ID of the category to update",
        json_schema_extra={"placeholder": "Category ID from list_categories"},
    )
    color: str = Field(
        ...,
        title="Color",
        description="New color preset for the category",
        json_schema_extra={
            "enum": [
                "preset0",
                "preset1",
                "preset2",
                "preset3",
                "preset4",
                "preset5",
                "preset6",
                "preset7",
                "preset8",
                "preset9",
                "preset10",
                "preset11",
                "preset12",
                "preset13",
                "preset14",
                "preset15",
                "preset16",
                "preset17",
                "preset18",
                "preset19",
                "preset20",
                "preset21",
                "preset22",
                "preset23",
                "preset24",
            ]
        },
    )


class OutlookDeleteCategoryConfig(BaseModel):
    """Configuration for deleting a category"""

    operation: Literal["delete_message_category"] = Field(
        default="delete_message_category",
        json_schema_extra={
            "const": "delete_message_category",
            "ui:hidden": True,
            "x-category": "Message Category",
            "x-is-trigger": False,
            "x-display-name": "Delete Message Category",
            "x-keywords": ["remove category", "delete color category", "trash tag"],
        },
        title="Delete Message Category",
    )
    category_id: str = Field(
        ...,
        title="Category ID",
        description="ID of the category to delete",
        json_schema_extra={"placeholder": "Category ID from list_categories"},
    )


# ============================================================================
# MAIL OPERATIONS - MIME Operations
# ============================================================================


class OutlookGetMimeContentConfig(BaseModel):
    """Configuration for getting MIME content"""

    operation: Literal["get_email_mime_content"] = Field(
        default="get_email_mime_content",
        json_schema_extra={
            "const": "get_email_mime_content",
            "ui:hidden": True,
            "x-category": "Email Message",
            "x-is-trigger": False,
            "x-display-name": "Get Email Mime Content",
            "x-keywords": [
                "raw email",
                "download eml",
                "mime content",
                "export email source",
                "get raw mime",
            ],
        },
        title="Get Email Mime Content",
    )
    message_id: str = Field(
        ...,
        title="Message ID",
        description="ID of the message to get MIME content from",
        json_schema_extra={"placeholder": "Message ID"},
    )


class OutlookSendMimeConfig(BaseModel):
    """Configuration for sending MIME message"""

    operation: Literal["send_mime_message"] = Field(
        default="send_mime_message",
        json_schema_extra={
            "const": "send_mime_message",
            "ui:hidden": True,
            "x-category": "Email Message",
            "x-is-trigger": False,
            "x-display-name": "Send Mime Message",
            "x-keywords": [
                "send raw email",
                "send eml",
                "deliver mime",
                "send mime content",
            ],
        },
        title="Send Mime Message",
    )
    mime_content: str = Field(
        ...,
        title="MIME Content",
        description="RFC822 MIME formatted message",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "MIME formatted email message...",
        },
    )


# ============================================================================
# CALENDAR OPERATIONS
# ============================================================================


class OutlookListEventsConfig(BaseModel):
    """Configuration for listing calendar events"""

    operation: Literal["list_calendar_events"] = Field(
        default="list_calendar_events",
        json_schema_extra={
            "const": "list_calendar_events",
            "ui:hidden": True,
            "x-category": "Calendar Event",
            "x-is-trigger": False,
            "x-display-name": "List Calendar Events",
            "x-keywords": [
                "list events",
                "view calendar",
                "show appointments",
                "upcoming meetings",
                "agenda",
                "my schedule",
            ],
        },
        title="List Calendar Events",
    )
    filter_query: Optional[str] = Field(
        None,
        title="Filter",
        description="OData filter query",
        json_schema_extra={"placeholder": "start/dateTime ge '2024-01-01' (optional)"},
    )
    order_by: Optional[str] = Field(
        "start/dateTime",
        title="Order By",
        description="Sort order for results",
        json_schema_extra={
            "enum": [
                "start/dateTime",
                "start/dateTime desc",
                "subject",
                "subject desc",
                "",
            ],
            "enumNames": [
                "Start Date (ascending)",
                "Start Date (descending)",
                "Subject A-Z",
                "Subject Z-A",
                "Default (no sort)",
            ],
            "x-enum-searchable": True,
        },
    )
    max_results: int = Field(
        10,
        title="Max Results",
        description="Maximum number of events to retrieve (1-50)",
        ge=1,
        le=50,
    )


class OutlookCreateEventConfig(BaseModel):
    """Configuration for creating a calendar event"""

    operation: Literal["create_calendar_event"] = Field(
        default="create_calendar_event",
        json_schema_extra={
            "const": "create_calendar_event",
            "ui:hidden": True,
            "x-category": "Calendar Event",
            "x-is-trigger": False,
            "x-display-name": "Create Calendar Event",
            "x-keywords": [
                "new event",
                "schedule meeting",
                "book appointment",
                "add event",
                "create meeting",
            ],
        },
        title="Create Calendar Event",
    )
    subject: str = Field(
        ...,
        title="Subject",
        description="Event title",
        json_schema_extra={"placeholder": "Team Meeting"},
    )
    start_datetime: str = Field(
        ...,
        title="Start Date/Time",
        description="Event start in ISO 8601 format",
        json_schema_extra={"placeholder": "2024-01-01T10:00:00"},
    )
    end_datetime: str = Field(
        ...,
        title="End Date/Time",
        description="Event end in ISO 8601 format",
        json_schema_extra={"placeholder": "2024-01-01T11:00:00"},
    )
    timezone: str = Field(
        "UTC",
        title="Timezone",
        description="Timezone for the event times",
        json_schema_extra={"placeholder": "UTC"},
    )
    location: Optional[str] = Field(
        None,
        title="Location",
        description="Event location",
        json_schema_extra={"placeholder": "Conference Room A (optional)"},
    )
    body: Optional[str] = Field(
        None,
        title="Body",
        description="Event description",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "Event details (optional)",
        },
    )
    attendees: Optional[str] = Field(
        None,
        title="Attendees",
        description="Comma-separated email addresses",
        json_schema_extra={
            "placeholder": "user1@example.com, user2@example.com (optional)"
        },
    )
    is_online_meeting: bool = Field(
        False, title="Online Meeting", description="Create as Teams online meeting"
    )


class OutlookGetEventConfig(BaseModel):
    """Configuration for getting a calendar event"""

    operation: Literal["get_calendar_event"] = Field(
        default="get_calendar_event",
        json_schema_extra={
            "const": "get_calendar_event",
            "ui:hidden": True,
            "x-category": "Calendar Event",
            "x-is-trigger": False,
            "x-display-name": "Get Calendar Event",
            "x-keywords": [
                "open event",
                "single event",
                "event details",
                "meeting details",
                "fetch one appointment",
            ],
        },
        title="Get Calendar Event",
    )
    event_id: str = Field(
        ...,
        title="Event ID",
        description="ID of the event to retrieve",
        json_schema_extra={"placeholder": "Event ID from list_events"},
    )


class OutlookUpdateEventConfig(BaseModel):
    """Configuration for updating a calendar event"""

    operation: Literal["update_calendar_event"] = Field(
        default="update_calendar_event",
        json_schema_extra={
            "const": "update_calendar_event",
            "ui:hidden": True,
            "x-category": "Calendar Event",
            "x-is-trigger": False,
            "x-display-name": "Update Calendar Event",
            "x-keywords": [
                "edit event",
                "reschedule meeting",
                "change appointment",
                "modify event",
                "update meeting",
            ],
        },
        title="Update Calendar Event",
    )
    event_id: str = Field(
        ...,
        title="Event ID",
        description="ID of the event to update",
        json_schema_extra={"placeholder": "Event ID from list_events"},
    )
    subject: Optional[str] = Field(
        None,
        title="Subject",
        description="New event title",
        json_schema_extra={"placeholder": "Updated Meeting Title (optional)"},
    )
    start_datetime: Optional[str] = Field(
        None,
        title="Start Date/Time",
        description="New start in ISO 8601 format",
        json_schema_extra={"placeholder": "2024-01-01T10:00:00 (optional)"},
    )
    end_datetime: Optional[str] = Field(
        None,
        title="End Date/Time",
        description="New end in ISO 8601 format",
        json_schema_extra={"placeholder": "2024-01-01T11:00:00 (optional)"},
    )
    location: Optional[str] = Field(
        None,
        title="Location",
        description="New event location",
        json_schema_extra={"placeholder": "New location (optional)"},
    )


class OutlookDeleteEventConfig(BaseModel):
    """Configuration for deleting a calendar event"""

    operation: Literal["delete_calendar_event"] = Field(
        default="delete_calendar_event",
        json_schema_extra={
            "const": "delete_calendar_event",
            "ui:hidden": True,
            "x-category": "Calendar Event",
            "x-is-trigger": False,
            "x-display-name": "Delete Calendar Event",
            "x-keywords": [
                "delete event",
                "remove meeting",
                "trash appointment",
                "delete meeting",
            ],
        },
        title="Delete Calendar Event",
    )
    event_id: str = Field(
        ...,
        title="Event ID",
        description="ID of the event to delete",
        json_schema_extra={"placeholder": "Event ID from list_events"},
    )


class OutlookCancelEventConfig(BaseModel):
    """Configuration for canceling a calendar event"""

    operation: Literal["cancel_calendar_event"] = Field(
        default="cancel_calendar_event",
        json_schema_extra={
            "const": "cancel_calendar_event",
            "ui:hidden": True,
            "x-category": "Calendar Event",
            "x-is-trigger": False,
            "x-display-name": "Cancel Calendar Event",
            "x-keywords": [
                "cancel meeting",
                "cancel event",
                "call off meeting",
                "notify cancellation",
            ],
        },
        title="Cancel Calendar Event",
    )
    event_id: str = Field(
        ...,
        title="Event ID",
        description="ID of the event to cancel",
        json_schema_extra={"placeholder": "Event ID from list_events"},
    )
    comment: Optional[str] = Field(
        None,
        title="Comment",
        description="Cancellation message to attendees",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "Event cancelled due to... (optional)",
        },
    )


class OutlookAcceptEventConfig(BaseModel):
    """Configuration for accepting an event invitation"""

    operation: Literal["accept_calendar_event_invitation"] = Field(
        default="accept_calendar_event_invitation",
        json_schema_extra={
            "const": "accept_calendar_event_invitation",
            "ui:hidden": True,
            "x-category": "Calendar Event",
            "x-is-trigger": False,
            "x-display-name": "Accept Calendar Event Invitation",
            "x-keywords": [
                "accept invite",
                "accept meeting",
                "say yes",
                "rsvp yes",
                "confirm attendance",
            ],
        },
        title="Accept Calendar Event Invitation",
    )
    event_id: str = Field(
        ...,
        title="Event ID",
        description="ID of the event to accept",
        json_schema_extra={"placeholder": "Event ID from list_events"},
    )
    comment: Optional[str] = Field(
        None,
        title="Comment",
        description="Optional comment to organizer",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "Looking forward to it! (optional)",
        },
    )
    send_response: bool = Field(
        True, title="Send Response", description="Send acceptance response to organizer"
    )


class OutlookDeclineEventConfig(BaseModel):
    """Configuration for declining an event invitation"""

    operation: Literal["decline_calendar_event_invitation"] = Field(
        default="decline_calendar_event_invitation",
        json_schema_extra={
            "const": "decline_calendar_event_invitation",
            "ui:hidden": True,
            "x-category": "Calendar Event",
            "x-is-trigger": False,
            "x-display-name": "Decline Calendar Event Invitation",
            "x-keywords": [
                "decline invite",
                "decline meeting",
                "say no",
                "rsvp no",
                "reject invitation",
            ],
        },
        title="Decline Calendar Event Invitation",
    )
    event_id: str = Field(
        ...,
        title="Event ID",
        description="ID of the event to decline",
        json_schema_extra={"placeholder": "Event ID from list_events"},
    )
    comment: Optional[str] = Field(
        None,
        title="Comment",
        description="Optional comment to organizer",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "Unable to attend... (optional)",
        },
    )
    send_response: bool = Field(
        True, title="Send Response", description="Send decline response to organizer"
    )


class OutlookTentativelyAcceptEventConfig(BaseModel):
    """Configuration for tentatively accepting an event invitation"""

    operation: Literal["tentatively_accept_calendar_event_invitation"] = Field(
        default="tentatively_accept_calendar_event_invitation",
        json_schema_extra={
            "const": "tentatively_accept_calendar_event_invitation",
            "ui:hidden": True,
            "x-category": "Calendar Event",
            "x-is-trigger": False,
            "x-display-name": "Tentatively Accept Calendar Event Invitation",
            "x-keywords": [
                "tentative rsvp",
                "maybe attending",
                "tentatively accept",
                "rsvp maybe",
                "provisional accept",
            ],
        },
        title="Tentatively Accept Calendar Event Invitation",
    )
    event_id: str = Field(
        ...,
        title="Event ID",
        description="ID of the event to tentatively accept",
        json_schema_extra={"placeholder": "Event ID from list_events"},
    )
    comment: Optional[str] = Field(
        None,
        title="Comment",
        description="Optional comment to organizer",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "Will try to attend... (optional)",
        },
    )
    send_response: bool = Field(
        True, title="Send Response", description="Send tentative response to organizer"
    )


class OutlookDismissReminderConfig(BaseModel):
    """Configuration for dismissing an event reminder"""

    operation: Literal["dismiss_event_reminder"] = Field(
        default="dismiss_event_reminder",
        json_schema_extra={
            "const": "dismiss_event_reminder",
            "ui:hidden": True,
            "x-category": "Calendar Event",
            "x-is-trigger": False,
            "x-display-name": "Dismiss Event Reminder",
            "x-keywords": [
                "dismiss reminder",
                "clear alert",
                "dismiss notification",
                "acknowledge reminder",
            ],
        },
        title="Dismiss Event Reminder",
    )
    event_id: str = Field(
        ...,
        title="Event ID",
        description="ID of the event to dismiss reminder for",
        json_schema_extra={"placeholder": "Event ID from list_events"},
    )


class OutlookSnoozeReminderConfig(BaseModel):
    """Configuration for snoozing an event reminder"""

    operation: Literal["snooze_event_reminder"] = Field(
        default="snooze_event_reminder",
        json_schema_extra={
            "const": "snooze_event_reminder",
            "ui:hidden": True,
            "x-category": "Calendar Event",
            "x-is-trigger": False,
            "x-display-name": "Snooze Event Reminder",
            "x-keywords": [
                "snooze reminder",
                "remind later",
                "postpone alert",
                "delay reminder",
            ],
        },
        title="Snooze Event Reminder",
    )
    event_id: str = Field(
        ...,
        title="Event ID",
        description="ID of the event to snooze reminder for",
        json_schema_extra={"placeholder": "Event ID from list_events"},
    )
    new_reminder_time: str = Field(
        ...,
        title="New Reminder Time",
        description="New reminder time in ISO 8601 format",
        json_schema_extra={"placeholder": "2024-01-01T09:00:00"},
    )


class OutlookFindMeetingTimesConfig(BaseModel):
    """Configuration for finding available meeting times"""

    operation: Literal["find_available_meeting_times"] = Field(
        default="find_available_meeting_times",
        json_schema_extra={
            "const": "find_available_meeting_times",
            "ui:hidden": True,
            "x-category": "Calendar Event",
            "x-is-trigger": False,
            "x-display-name": "Find Available Meeting Times",
            "x-keywords": [
                "find meeting time",
                "suggest times",
                "find open slot",
                "schedule suggestions",
                "best time to meet",
            ],
        },
        title="Find Available Meeting Times",
    )
    attendees: str = Field(
        ...,
        title="Attendees",
        description="Comma-separated email addresses of required attendees",
        json_schema_extra={"placeholder": "user1@example.com, user2@example.com"},
    )
    meeting_duration: int = Field(
        60,
        title="Meeting Duration (minutes)",
        description="Duration of the meeting in minutes",
        ge=15,
        le=480,
    )
    start_time: str = Field(
        ...,
        title="Start Time",
        description="Earliest possible meeting time (ISO 8601)",
        json_schema_extra={"placeholder": "2024-01-01T09:00:00"},
    )
    end_time: str = Field(
        ...,
        title="End Time",
        description="Latest possible meeting time (ISO 8601)",
        json_schema_extra={"placeholder": "2024-01-01T17:00:00"},
    )


class OutlookGetScheduleConfig(BaseModel):
    """Configuration for getting free/busy schedule"""

    operation: Literal["get_free_busy_schedule"] = Field(
        default="get_free_busy_schedule",
        json_schema_extra={
            "const": "get_free_busy_schedule",
            "ui:hidden": True,
            "x-category": "Calendar Event",
            "x-is-trigger": False,
            "x-display-name": "Get Free Busy Schedule",
            "x-keywords": [
                "free busy schedule",
                "availability slots",
                "when is someone busy",
                "check person availability",
                "busy times",
                "schedule availability",
            ],
        },
        title="Get Free Busy Schedule",
    )
    schedules: str = Field(
        ...,
        title="Email Addresses",
        description="Comma-separated email addresses to get schedules for",
        json_schema_extra={"placeholder": "user1@example.com, user2@example.com"},
    )
    start_time: str = Field(
        ...,
        title="Start Time",
        description="Schedule start time (ISO 8601)",
        json_schema_extra={"placeholder": "2024-01-01T00:00:00"},
    )
    end_time: str = Field(
        ...,
        title="End Time",
        description="Schedule end time (ISO 8601)",
        json_schema_extra={"placeholder": "2024-01-02T00:00:00"},
    )


class OutlookListEventInstancesConfig(BaseModel):
    """Configuration for listing recurring event instances"""

    operation: Literal["list_recurring_event_instances"] = Field(
        default="list_recurring_event_instances",
        json_schema_extra={
            "const": "list_recurring_event_instances",
            "ui:hidden": True,
            "x-category": "Calendar Event",
            "x-is-trigger": False,
            "x-display-name": "List Recurring Event Instances",
            "x-keywords": [
                "recurring event instances",
                "repeating event occurrences",
                "series instances",
                "expand recurring series",
                "single occurrences",
            ],
        },
        title="List Recurring Event Instances",
    )
    event_id: str = Field(
        ...,
        title="Event ID",
        description="ID of the recurring event",
        json_schema_extra={"placeholder": "Recurring event ID"},
    )
    start_datetime: str = Field(
        ...,
        title="Start Date/Time",
        description="Start of time range (ISO 8601)",
        json_schema_extra={"placeholder": "2024-01-01T00:00:00"},
    )
    end_datetime: str = Field(
        ...,
        title="End Date/Time",
        description="End of time range (ISO 8601)",
        json_schema_extra={"placeholder": "2024-12-31T23:59:59"},
    )


class OutlookListCalendarsConfig(BaseModel):
    """Configuration for listing calendars"""

    operation: Literal["list_calendars"] = Field(
        default="list_calendars",
        json_schema_extra={
            "const": "list_calendars",
            "ui:hidden": True,
            "x-category": "Calendar",
            "x-is-trigger": False,
            "x-display-name": "List Calendars",
            "x-keywords": [
                "my calendars",
                "all calendars",
                "available calendars",
                "which calendars",
            ],
        },
        title="List Calendars",
    )


class OutlookListCalendarGroupsConfig(BaseModel):
    """Configuration for listing calendar groups"""

    operation: Literal["list_calendar_groups"] = Field(
        default="list_calendar_groups",
        json_schema_extra={
            "const": "list_calendar_groups",
            "ui:hidden": True,
            "x-category": "Calendar",
            "x-is-trigger": False,
            "x-display-name": "List Calendar Groups",
            "x-keywords": [
                "calendar groups",
                "grouped calendars",
                "calendar collections",
                "calendar folders",
            ],
        },
        title="List Calendar Groups",
    )


class OutlookGetRoomListsConfig(BaseModel):
    """Configuration for getting room lists"""

    operation: Literal["get_available_room_lists"] = Field(
        default="get_available_room_lists",
        json_schema_extra={
            "const": "get_available_room_lists",
            "ui:hidden": True,
            "x-category": "Room",
            "x-is-trigger": False,
            "x-display-name": "Get Available Room Lists",
            "x-keywords": [
                "meeting rooms",
                "room lists",
                "conference rooms",
                "bookable rooms",
                "available locations",
            ],
        },
        title="Get Available Room Lists",
    )


# ============================================================================
# CONTACTS OPERATIONS
# ============================================================================


class OutlookListContactsConfig(BaseModel):
    """Configuration for listing contacts"""

    operation: Literal["list_contacts"] = Field(
        default="list_contacts",
        json_schema_extra={
            "const": "list_contacts",
            "ui:hidden": True,
            "x-category": "Contact",
            "x-is-trigger": False,
            "x-display-name": "List Contacts",
            "x-keywords": [
                "address book",
                "my contacts",
                "people directory",
                "saved contacts",
            ],
        },
        title="List Contacts",
    )
    filter_query: Optional[str] = Field(
        None,
        title="Filter",
        description="OData filter query",
        json_schema_extra={"placeholder": "givenName eq 'John' (optional)"},
    )
    order_by: Optional[str] = Field(
        "displayName",
        title="Order By",
        description="Sort order for results",
        json_schema_extra={
            "enum": ["displayName", "displayName desc", "givenName", "surname", ""],
            "enumNames": [
                "Display Name A-Z",
                "Display Name Z-A",
                "Given Name",
                "Surname",
                "Default (no sort)",
            ],
            "x-enum-searchable": True,
        },
    )
    max_results: int = Field(
        10,
        title="Max Results",
        description="Maximum number of contacts to retrieve (1-50)",
        ge=1,
        le=50,
    )


class OutlookCreateContactConfig(BaseModel):
    """Configuration for creating a contact"""

    operation: Literal["create_contact_person"] = Field(
        default="create_contact_person",
        json_schema_extra={
            "const": "create_contact_person",
            "ui:hidden": True,
            "x-category": "Contact",
            "x-is-trigger": False,
            "x-display-name": "Create Contact Person",
            "x-keywords": [
                "add contact",
                "new contact",
                "save contact",
                "add person",
                "add to address book",
                "create contact",
            ],
        },
        title="Create Contact Person",
    )
    given_name: str = Field(
        ...,
        title="First Name",
        description="Contact's first name",
        json_schema_extra={"placeholder": "John"},
    )
    surname: str = Field(
        ...,
        title="Last Name",
        description="Contact's last name",
        json_schema_extra={"placeholder": "Doe"},
    )
    email_address: Optional[str] = Field(
        None,
        title="Email Address",
        description="Contact's email address",
        json_schema_extra={"placeholder": "john.doe@example.com (optional)"},
    )
    business_phone: Optional[str] = Field(
        None,
        title="Business Phone",
        description="Contact's business phone number",
        json_schema_extra={"placeholder": "+1-555-0123 (optional)"},
    )
    mobile_phone: Optional[str] = Field(
        None,
        title="Mobile Phone",
        description="Contact's mobile phone number",
        json_schema_extra={"placeholder": "+1-555-0124 (optional)"},
    )
    home_phone: Optional[str] = Field(
        None,
        title="Home Phone",
        description="Contact's home phone number",
        json_schema_extra={"placeholder": "+1-555-0125 (optional)"},
    )
    job_title: Optional[str] = Field(
        None,
        title="Job Title",
        description="Contact's job title",
        json_schema_extra={"placeholder": "Software Engineer (optional)"},
    )
    company_name: Optional[str] = Field(
        None,
        title="Company",
        description="Contact's company name",
        json_schema_extra={"placeholder": "Acme Corp (optional)"},
    )


class OutlookGetContactConfig(BaseModel):
    """Configuration for getting a contact"""

    operation: Literal["get_contact_person"] = Field(
        default="get_contact_person",
        json_schema_extra={
            "const": "get_contact_person",
            "ui:hidden": True,
            "x-category": "Contact",
            "x-is-trigger": False,
            "x-display-name": "Get Contact Person",
            "x-keywords": [
                "view contact",
                "contact details",
                "open contact",
                "fetch contact",
                "person info",
                "lookup contact",
            ],
        },
        title="Get Contact Person",
    )
    contact_id: str = Field(
        ...,
        title="Contact ID",
        description="ID of the contact to retrieve",
        json_schema_extra={"placeholder": "Contact ID from list_contacts"},
    )


class OutlookUpdateContactConfig(BaseModel):
    """Configuration for updating a contact"""

    operation: Literal["update_contact_person"] = Field(
        default="update_contact_person",
        json_schema_extra={
            "const": "update_contact_person",
            "ui:hidden": True,
            "x-category": "Contact",
            "x-is-trigger": False,
            "x-display-name": "Update Contact Person",
            "x-keywords": [
                "edit contact",
                "change contact",
                "update phone number",
                "edit contact details",
                "modify contact",
            ],
        },
        title="Update Contact Person",
    )
    contact_id: str = Field(
        ...,
        title="Contact ID",
        description="ID of the contact to update",
        json_schema_extra={"placeholder": "Contact ID from list_contacts"},
    )
    given_name: Optional[str] = Field(
        None,
        title="First Name",
        description="New first name",
        json_schema_extra={"placeholder": "John (optional)"},
    )
    surname: Optional[str] = Field(
        None,
        title="Last Name",
        description="New last name",
        json_schema_extra={"placeholder": "Doe (optional)"},
    )
    email_address: Optional[str] = Field(
        None,
        title="Email Address",
        description="New email address",
        json_schema_extra={"placeholder": "john.doe@example.com (optional)"},
    )
    mobile_phone: Optional[str] = Field(
        None,
        title="Mobile Phone",
        description="New mobile phone number",
        json_schema_extra={"placeholder": "+1-555-0124 (optional)"},
    )


class OutlookDeleteContactConfig(BaseModel):
    """Configuration for deleting a contact"""

    operation: Literal["delete_contact_person"] = Field(
        default="delete_contact_person",
        json_schema_extra={
            "const": "delete_contact_person",
            "ui:hidden": True,
            "x-category": "Contact",
            "x-is-trigger": False,
            "x-display-name": "Delete Contact Person",
            "x-keywords": [
                "remove contact",
                "delete contact",
                "erase person",
                "remove from address book",
            ],
        },
        title="Delete Contact Person",
    )
    contact_id: str = Field(
        ...,
        title="Contact ID",
        description="ID of the contact to delete",
        json_schema_extra={"placeholder": "Contact ID from list_contacts"},
    )


class OutlookListContactFoldersConfig(BaseModel):
    """Configuration for listing contact folders"""

    operation: Literal["list_contact_folders"] = Field(
        default="list_contact_folders",
        json_schema_extra={
            "const": "list_contact_folders",
            "ui:hidden": True,
            "x-category": "Contact Folder",
            "x-is-trigger": False,
            "x-display-name": "List Contact Folders",
            "x-keywords": [
                "address book folders",
                "contact groups",
                "view contact folders",
                "all contact folders",
                "browse contact folders",
            ],
        },
        title="List Contact Folders",
    )


class OutlookCreateContactFolderConfig(BaseModel):
    """Configuration for creating a contact folder"""

    operation: Literal["create_contact_folder"] = Field(
        default="create_contact_folder",
        json_schema_extra={
            "const": "create_contact_folder",
            "ui:hidden": True,
            "x-category": "Contact Folder",
            "x-is-trigger": False,
            "x-display-name": "Create Contact Folder",
            "x-keywords": [
                "new contact folder",
                "add contact group",
                "make address book",
                "create contact folder",
            ],
        },
        title="Create Contact Folder",
    )
    display_name: str = Field(
        ...,
        title="Folder Name",
        description="Name for the contact folder",
        json_schema_extra={"placeholder": "My Contacts"},
    )
    parent_folder_id: Optional[str] = Field(
        None,
        title="Parent Folder ID",
        description="ID of parent folder (optional, defaults to root)",
        json_schema_extra={"placeholder": "Parent folder ID (optional)"},
    )


class OutlookGetContactFolderConfig(BaseModel):
    """Configuration for getting a contact folder"""

    operation: Literal["get_contact_folder"] = Field(
        default="get_contact_folder",
        json_schema_extra={
            "const": "get_contact_folder",
            "ui:hidden": True,
            "x-category": "Contact Folder",
            "x-is-trigger": False,
            "x-display-name": "Get Contact Folder",
            "x-keywords": [
                "view contact folder",
                "open contact group",
                "contact folder details",
                "fetch contact folder",
            ],
        },
        title="Get Contact Folder",
    )
    folder_id: str = Field(
        ...,
        title="Folder ID",
        description="ID of the contact folder to retrieve",
        json_schema_extra={"placeholder": "Folder ID from list_contact_folders"},
    )


class OutlookUpdateContactFolderConfig(BaseModel):
    """Configuration for updating a contact folder"""

    operation: Literal["update_contact_folder"] = Field(
        default="update_contact_folder",
        json_schema_extra={
            "const": "update_contact_folder",
            "ui:hidden": True,
            "x-category": "Contact Folder",
            "x-is-trigger": False,
            "x-display-name": "Update Contact Folder",
            "x-keywords": [
                "rename contact folder",
                "edit contact group",
                "change contact folder",
                "modify contact folder",
            ],
        },
        title="Update Contact Folder",
    )
    folder_id: str = Field(
        ...,
        title="Folder ID",
        description="ID of the contact folder to update",
        json_schema_extra={"placeholder": "Folder ID from list_contact_folders"},
    )
    display_name: str = Field(
        ...,
        title="New Name",
        description="New name for the contact folder",
        json_schema_extra={"placeholder": "Updated Folder Name"},
    )


class OutlookDeleteContactFolderConfig(BaseModel):
    """Configuration for deleting a contact folder"""

    operation: Literal["delete_contact_folder"] = Field(
        default="delete_contact_folder",
        json_schema_extra={
            "const": "delete_contact_folder",
            "ui:hidden": True,
            "x-category": "Contact Folder",
            "x-is-trigger": False,
            "x-display-name": "Delete Contact Folder",
            "x-keywords": [
                "remove contact folder",
                "delete contact group",
                "erase address book",
                "delete contact folder",
            ],
        },
        title="Delete Contact Folder",
    )
    folder_id: str = Field(
        ...,
        title="Folder ID",
        description="ID of the contact folder to delete",
        json_schema_extra={"placeholder": "Folder ID from list_contact_folders"},
    )


# ============================================================================
# Additional Calendar operation configs (calendar/group CRUD, calendarView,
# forward, attachments, delta, sharing permissions, reminder view, trigger)
# ============================================================================


def _cal_op(op: str, display: str, *, creates: Optional[str] = None, id_path: Optional[str] = None) -> Any:
    extra: Dict[str, Any] = {
        "const": op,
        "ui:hidden": True,
        "x-category": "Calendar",
        "x-is-trigger": False,
        "x-display-name": display,
    }
    if creates:
        extra["x-creates-resource"] = True
        extra["x-resource-type"] = creates
        extra["x-resource-id-path"] = id_path
    return Field(default=op, json_schema_extra=extra, title=display)


def _cal_id_field(description: str = "The calendar") -> Any:
    return Field(
        ...,
        title="Calendar",
        description=description,
        json_schema_extra={
            "x-resource-type": "outlook_calendar",
            "x-dynamic-options": {
                "field_name": "calendar_id",
                "placeholder": "Select a calendar...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste calendar ID",
            }
        },
    )


class OutlookGetCalendarConfig(BaseModel):
    operation: Literal["get_calendar"] = _cal_op("get_calendar", "Get Calendar")
    calendar_id: str = _cal_id_field("The calendar to retrieve")


class OutlookCreateCalendarConfig(BaseModel):
    operation: Literal["create_calendar"] = _cal_op("create_calendar", "Create Calendar", creates="outlook_calendar", id_path="calendar.id")
    name: str = Field(..., title="Name", description="Name of the new calendar")
    color: Optional[str] = Field(None, title="Color", description="Calendar color (e.g. auto, lightBlue)")


class OutlookUpdateCalendarConfig(BaseModel):
    operation: Literal["update_calendar"] = _cal_op("update_calendar", "Update Calendar")
    calendar_id: str = _cal_id_field("The calendar to update")
    name: Optional[str] = Field(None, title="Name", description="New calendar name")
    color: Optional[str] = Field(None, title="Color", description="New calendar color")


class OutlookDeleteCalendarConfig(BaseModel):
    operation: Literal["delete_calendar"] = _cal_op("delete_calendar", "Delete Calendar")
    calendar_id: str = _cal_id_field("The calendar to delete")


class OutlookCalendarViewConfig(BaseModel):
    operation: Literal["get_calendar_view"] = _cal_op("get_calendar_view", "Get Calendar View")
    start_date_time: str = Field(..., title="Start", description="Window start, ISO 8601")
    end_date_time: str = Field(..., title="End", description="Window end, ISO 8601")
    calendar_id: Optional[str] = Field(None, title="Calendar", description="Calendar to view (default: primary)")
    top: Optional[str] = Field(None, title="Max Results", description="Max events to return")


class OutlookForwardCalendarEventConfig(BaseModel):
    operation: Literal["forward_calendar_event"] = _cal_op("forward_calendar_event", "Forward Calendar Event")
    event_id: str = Field(..., title="Event ID", description="The event to forward")
    to_recipients: str = Field(..., title="To", description="Comma-separated recipient email addresses")
    comment: Optional[str] = Field(None, title="Comment", description="Optional forwarding comment")


class OutlookListEventAttachmentsConfig(BaseModel):
    operation: Literal["list_event_attachments"] = _cal_op("list_event_attachments", "List Event Attachments")
    event_id: str = Field(..., title="Event ID", description="The event whose attachments to list")


class OutlookAddEventAttachmentConfig(BaseModel):
    operation: Literal["add_event_attachment"] = _cal_op("add_event_attachment", "Add Event Attachment")
    event_id: str = Field(..., title="Event ID", description="The event to attach to")
    name: str = Field(..., title="File Name", description="Attachment file name")
    content_bytes: str = Field(..., title="Content (base64)", description="Base64-encoded file bytes (<3 MB)",
                               json_schema_extra={"ui:widget": "textarea"})
    content_type: Optional[str] = Field(None, title="Content Type", description="MIME type, e.g. application/pdf")


class OutlookGetEventAttachmentConfig(BaseModel):
    operation: Literal["get_event_attachment"] = _cal_op("get_event_attachment", "Get Event Attachment")
    event_id: str = Field(..., title="Event ID", description="The event that owns the attachment")
    attachment_id: str = Field(..., title="Attachment ID", description="The attachment ID")


class OutlookDeleteEventAttachmentConfig(BaseModel):
    operation: Literal["delete_event_attachment"] = _cal_op("delete_event_attachment", "Delete Event Attachment")
    event_id: str = Field(..., title="Event ID", description="The event that owns the attachment")
    attachment_id: str = Field(..., title="Attachment ID", description="The attachment ID to delete")


class OutlookCalendarViewDeltaConfig(BaseModel):
    operation: Literal["get_calendar_view_delta"] = _cal_op("get_calendar_view_delta", "Get Calendar View Delta")
    start_date_time: str = Field(..., title="Start", description="Window start, ISO 8601")
    end_date_time: str = Field(..., title="End", description="Window end, ISO 8601")
    delta_token: Optional[str] = Field(None, title="Delta Link/Token", description="A prior @odata.deltaLink or $deltatoken to resume from")


class OutlookCreateCalendarGroupConfig(BaseModel):
    operation: Literal["create_calendar_group"] = _cal_op("create_calendar_group", "Create Calendar Group")
    name: str = Field(..., title="Name", description="Name of the new calendar group")


class OutlookGetCalendarGroupConfig(BaseModel):
    operation: Literal["get_calendar_group"] = _cal_op("get_calendar_group", "Get Calendar Group")
    group_id: str = Field(..., title="Group ID", description="The calendar group ID")


class OutlookUpdateCalendarGroupConfig(BaseModel):
    operation: Literal["update_calendar_group"] = _cal_op("update_calendar_group", "Update Calendar Group")
    group_id: str = Field(..., title="Group ID", description="The calendar group ID")
    name: str = Field(..., title="Name", description="New calendar group name")


class OutlookDeleteCalendarGroupConfig(BaseModel):
    operation: Literal["delete_calendar_group"] = _cal_op("delete_calendar_group", "Delete Calendar Group")
    group_id: str = Field(..., title="Group ID", description="The calendar group ID")


class OutlookListCalendarsInGroupConfig(BaseModel):
    operation: Literal["list_calendars_in_group"] = _cal_op("list_calendars_in_group", "List Calendars In Group")
    group_id: str = Field(..., title="Group ID", description="The calendar group ID")


class OutlookCreateCalendarInGroupConfig(BaseModel):
    operation: Literal["create_calendar_in_group"] = _cal_op("create_calendar_in_group", "Create Calendar In Group")
    group_id: str = Field(..., title="Group ID", description="The calendar group ID")
    name: str = Field(..., title="Name", description="Name of the new calendar")


class OutlookListCalendarPermissionsConfig(BaseModel):
    operation: Literal["list_calendar_permissions"] = _cal_op("list_calendar_permissions", "List Calendar Permissions")
    calendar_id: str = _cal_id_field("The calendar whose sharing permissions to list")


class OutlookGetCalendarPermissionConfig(BaseModel):
    operation: Literal["get_calendar_permission"] = _cal_op("get_calendar_permission", "Get Calendar Permission")
    calendar_id: str = _cal_id_field("The calendar that owns the permission")
    permission_id: str = Field(..., title="Permission ID", description="The calendarPermission ID")


class OutlookCreateCalendarPermissionConfig(BaseModel):
    operation: Literal["create_calendar_permission"] = _cal_op("create_calendar_permission", "Create Calendar Permission")
    calendar_id: str = _cal_id_field("The calendar to share")
    resource: str = Field(..., title="Permission JSON",
                          description='calendarPermission body, e.g. {"emailAddress":{"address":"x@y.com"},"role":"read","allowedRoles":["read"]}',
                          json_schema_extra={"ui:widget": "textarea"})


class OutlookUpdateCalendarPermissionConfig(BaseModel):
    operation: Literal["update_calendar_permission"] = _cal_op("update_calendar_permission", "Update Calendar Permission")
    calendar_id: str = _cal_id_field("The calendar that owns the permission")
    permission_id: str = Field(..., title="Permission ID", description="The calendarPermission ID")
    role: str = Field(..., title="Role",
                      description="freeBusyRead, limitedRead, read, write, delegateWithoutPrivateEventAccess, delegateWithPrivateEventAccess")


class OutlookDeleteCalendarPermissionConfig(BaseModel):
    operation: Literal["delete_calendar_permission"] = _cal_op("delete_calendar_permission", "Delete Calendar Permission")
    calendar_id: str = _cal_id_field("The calendar that owns the permission")
    permission_id: str = Field(..., title="Permission ID", description="The calendarPermission ID to remove")


class OutlookAllowedSharingRolesConfig(BaseModel):
    operation: Literal["allowed_calendar_sharing_roles"] = _cal_op("allowed_calendar_sharing_roles", "Allowed Calendar Sharing Roles")
    calendar_id: str = _cal_id_field("The calendar to check")
    user_email: str = Field(..., title="User Email", description="SMTP address of the recipient")


class OutlookReminderViewConfig(BaseModel):
    operation: Literal["reminder_view"] = _cal_op("reminder_view", "Reminder View")
    start_date_time: str = Field(..., title="Start", description="Window start, ISO 8601")
    end_date_time: str = Field(..., title="End", description="Window end, ISO 8601")


def _cal_trigger_op(op: str, display: str) -> Any:
    return Field(
        default=op,
        json_schema_extra={
            "const": op,
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": display,
        },
        title=display,
    )


def _mail_trigger_op(op: str, display: str) -> Any:
    return Field(
        default=op,
        json_schema_extra={
            "const": op,
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": display,
        },
        title=display,
    )


# changeType a calendar-event subscription requests, per trigger operation.
CALENDAR_TRIGGER_CHANGE_TYPES = {
    "on_calendar_event_created": "created",
    "on_calendar_event_updated": "updated",
    "on_calendar_event_deleted": "deleted",
    "on_calendar_event_change": "created,updated,deleted",
}


class _OutlookCalendarEventTrigger(BaseModel):
    """Shared fields for the per-change-type calendar event triggers. Each
    subclass fixes a single Graph change type; all register one Graph
    change-notification subscription scoped to the chosen calendar."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    calendar_id: Optional[str] = Field(
        None, title="Calendar", description="Watch a specific calendar (default: primary)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "calendar_id", "placeholder": "Select a calendar...",
                "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste calendar ID",
            }
        },
    )
    webhook_url: Optional[str] = Field(
        default=None, title="Webhook URL",
        description="Microsoft Graph posts change notifications here. Registered automatically when you connect credentials.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True},
    )
    webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    external_webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    signing_secret: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    relay_connected: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    is_production: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    trigger_registered: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    trigger_error: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})


class OutlookOnCalendarEventCreatedConfig(_OutlookCalendarEventTrigger):
    """Fire when a calendar event is created."""

    operation: Literal["on_calendar_event_created"] = _cal_trigger_op(
        "on_calendar_event_created", "On Calendar Event Created"
    )


class OutlookOnCalendarEventUpdatedConfig(_OutlookCalendarEventTrigger):
    """Fire when a calendar event is updated."""

    operation: Literal["on_calendar_event_updated"] = _cal_trigger_op(
        "on_calendar_event_updated", "On Calendar Event Updated"
    )


class OutlookOnCalendarEventDeletedConfig(_OutlookCalendarEventTrigger):
    """Fire when a calendar event is deleted."""

    operation: Literal["on_calendar_event_deleted"] = _cal_trigger_op(
        "on_calendar_event_deleted", "On Calendar Event Deleted"
    )


class OutlookOnCalendarEventChangeConfig(_OutlookCalendarEventTrigger):
    """Fire on any calendar event change (created / updated / deleted)."""

    operation: Literal["on_calendar_event_change"] = _cal_trigger_op(
        "on_calendar_event_change", "On Calendar Event Change (Any)"
    )


# changeType for mail-message subscriptions, per trigger operation.
MAIL_TRIGGER_CHANGE_TYPES = {
    "on_email_received": "created",
    "on_email_updated": "updated",
    "on_email_deleted": "deleted",
    "on_email_change": "created,updated,deleted",
}

# Well-known folder display names → Graph folder id (used when no dynamic folder is picked)
WELL_KNOWN_MAIL_FOLDERS = {
    "inbox": "inbox",
    "sent": "sentitems",
    "drafts": "drafts",
    "deleted": "deleteditems",
    "junk": "junkemail",
    "archive": "archive",
}


class _OutlookMailTrigger(BaseModel):
    """Shared fields for email change-notification triggers.
    Each subclass fixes a single Graph change type; all register one
    Graph subscription scoped to an optional mail folder."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    folder_id: Optional[str] = Field(
        None,
        title="Mail Folder",
        description="Watch a specific folder (default: Inbox). Accepts a well-known name (inbox, sentitems, drafts…) or a folder ID.",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "mail_folder_id",
                "placeholder": "Select a folder...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste folder ID",
            }
        },
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="Microsoft Graph posts change notifications here. Registered automatically when you connect credentials.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True},
    )
    webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    external_webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    signing_secret: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    relay_connected: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    is_production: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    trigger_registered: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    trigger_error: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})


class OutlookOnEmailReceivedConfig(_OutlookMailTrigger):
    """Fire when a new email arrives in the watched folder."""

    operation: Literal["on_email_received"] = _mail_trigger_op(
        "on_email_received", "On Email Received"
    )


class OutlookOnEmailUpdatedConfig(_OutlookMailTrigger):
    """Fire when an email is updated (read/unread, flag, category, etc.)."""

    operation: Literal["on_email_updated"] = _mail_trigger_op(
        "on_email_updated", "On Email Updated"
    )


class OutlookOnEmailDeletedConfig(_OutlookMailTrigger):
    """Fire when an email is deleted or moved to Deleted Items."""

    operation: Literal["on_email_deleted"] = _mail_trigger_op(
        "on_email_deleted", "On Email Deleted"
    )


class OutlookOnEmailChangeConfig(_OutlookMailTrigger):
    """Fire on any email change in the watched folder (received / updated / deleted)."""

    operation: Literal["on_email_change"] = _mail_trigger_op(
        "on_email_change", "On Email Change (Any)"
    )


# Union of all config types for oneOf schema
OutlookConfig = Annotated[
    Union[
        # Original mail operations
        OutlookSendConfig,
        OutlookReadConfig,
        OutlookReplyConfig,
        OutlookForwardConfig,
        OutlookGetMessageConfig,
        OutlookMarkReadConfig,
        OutlookDeleteConfig,
        OutlookMoveConfig,
        OutlookCreateDraftConfig,
        OutlookListFoldersConfig,
        OutlookCreateFolderConfig,
        OutlookGetAttachmentsConfig,
        OutlookGetMailboxSettingsConfig,
        OutlookUpdateAutoReplyConfig,
        # Advanced message operations
        OutlookCopyMessageConfig,
        OutlookUpdateMessageConfig,
        OutlookSendDraftConfig,
        OutlookCreateReplyDraftConfig,
        OutlookCreateReplyAllDraftConfig,
        OutlookCreateForwardDraftConfig,
        # Attachment operations
        OutlookAddAttachmentConfig,
        OutlookDeleteAttachmentConfig,
        # Folder operations
        OutlookUpdateFolderConfig,
        OutlookDeleteFolderConfig,
        OutlookMoveFolderConfig,
        OutlookCopyFolderConfig,
        # Message rules
        OutlookListMessageRulesConfig,
        OutlookGetMessageRuleConfig,
        OutlookCreateMessageRuleConfig,
        OutlookUpdateMessageRuleConfig,
        OutlookDeleteMessageRuleConfig,
        # Categories
        OutlookListCategoriesConfig,
        OutlookGetCategoryConfig,
        OutlookCreateCategoryConfig,
        OutlookUpdateCategoryConfig,
        OutlookDeleteCategoryConfig,
        # MIME operations
        OutlookGetMimeContentConfig,
        OutlookSendMimeConfig,
        # Calendar operations
        OutlookListEventsConfig,
        OutlookCreateEventConfig,
        OutlookGetEventConfig,
        OutlookUpdateEventConfig,
        OutlookDeleteEventConfig,
        OutlookCancelEventConfig,
        OutlookAcceptEventConfig,
        OutlookDeclineEventConfig,
        OutlookTentativelyAcceptEventConfig,
        OutlookDismissReminderConfig,
        OutlookSnoozeReminderConfig,
        OutlookFindMeetingTimesConfig,
        OutlookGetScheduleConfig,
        OutlookListEventInstancesConfig,
        OutlookListCalendarsConfig,
        OutlookListCalendarGroupsConfig,
        OutlookGetRoomListsConfig,
        # Contacts operations
        OutlookListContactsConfig,
        OutlookCreateContactConfig,
        OutlookGetContactConfig,
        OutlookUpdateContactConfig,
        OutlookDeleteContactConfig,
        OutlookListContactFoldersConfig,
        OutlookCreateContactFolderConfig,
        OutlookGetContactFolderConfig,
        OutlookUpdateContactFolderConfig,
        OutlookDeleteContactFolderConfig,
        # Additional calendar coverage
        OutlookGetCalendarConfig,
        OutlookCreateCalendarConfig,
        OutlookUpdateCalendarConfig,
        OutlookDeleteCalendarConfig,
        OutlookCalendarViewConfig,
        OutlookForwardCalendarEventConfig,
        OutlookListEventAttachmentsConfig,
        OutlookAddEventAttachmentConfig,
        OutlookGetEventAttachmentConfig,
        OutlookDeleteEventAttachmentConfig,
        OutlookCalendarViewDeltaConfig,
        OutlookCreateCalendarGroupConfig,
        OutlookGetCalendarGroupConfig,
        OutlookUpdateCalendarGroupConfig,
        OutlookDeleteCalendarGroupConfig,
        OutlookListCalendarsInGroupConfig,
        OutlookCreateCalendarInGroupConfig,
        OutlookListCalendarPermissionsConfig,
        OutlookGetCalendarPermissionConfig,
        OutlookCreateCalendarPermissionConfig,
        OutlookUpdateCalendarPermissionConfig,
        OutlookDeleteCalendarPermissionConfig,
        OutlookAllowedSharingRolesConfig,
        OutlookReminderViewConfig,
        OutlookOnCalendarEventCreatedConfig,
        OutlookOnCalendarEventUpdatedConfig,
        OutlookOnCalendarEventDeletedConfig,
        OutlookOnCalendarEventChangeConfig,
        # Mail triggers
        OutlookOnEmailReceivedConfig,
        OutlookOnEmailUpdatedConfig,
        OutlookOnEmailDeletedConfig,
        OutlookOnEmailChangeConfig,
    ],
    Discriminator("operation"),
]


class OutlookNodeConfig(NodeConfig[OutlookConfig, OutlookOAuthCredential]):
    """Full configuration for Outlook node including credentials"""

    pass


# ============================================================================
# Outlook Node Implementation
# ============================================================================


class OutlookMailNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """
    Outlook Mail workflow node for sending, reading, replying, and forwarding emails.
    Uses Microsoft Graph API for all operations.
    """

    # Not mail folders — Inbox/Sent/Drafts are identical for every mailbox.
    connection_evidence = ConnectionEvidence(
        operation="list_contacts",
        noun="contacts",
        identity_operation="get_mailbox_settings",
    )

    edit_examples = [
        "Send an email to customer@acme.com with project proposal attachment",
        "Read unread emails from the inbox and extract subject and sender",
        "Reply all to a meeting scheduling email with updated availability",
        "Forward urgent messages marked high priority to team@company.com",
        "Create a calendar event for the Q4 planning meeting at 2 PM",
        'Search for emails containing "invoice" in the Finance folder',
        "Move marketing campaign emails to the Campaigns folder",
    ]

    #: OAuth scope requirements per operation (nodes/scopes/microsoft.py).
    scope_registry = OUTLOOK_SCOPES

    @classmethod
    def get_config_model(cls) -> Optional[Union[Type, type]]:
        """Get Pydantic config model for Outlook node"""
        return OutlookNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute Outlook operation.

        Args:
            inputs: Output data from upstream nodes

        Returns:
            Dict containing Outlook operation results
        """
        logger.info(f"[OutlookMailNode] Executing node {self.node_id}")
        start_time = time.time()

        # Get config - required for this node
        node_config = self.config
        if not node_config:
            raise ValueError(
                f"[OutlookMailNode] Configuration is required but not provided for node {self.node_id}"
            )

        if not isinstance(node_config, OutlookNodeConfig):
            raise ValueError(
                f"[OutlookMailNode] Invalid config type: {type(node_config)}, expected OutlookNodeConfig"
            )

        # Extract the actual config and credentials
        config = node_config.config
        credentials = node_config.credentials

        # Webhook triggers: the Graph change notification arrives as inputs;
        # pass it through without an API call or token.
        if isinstance(config, (_OutlookCalendarEventTrigger, _OutlookMailTrigger)):
            return {
                "type": "outlook",
                "operation": config.operation,
                "data": {**inputs, "webhook_url": config.webhook_url},
                "status": "success",
                "timing_ms": round((time.time() - start_time) * 1000, 2),
            }

        # Validate credentials are provided
        if not credentials:
            raise ValueError(
                f"[OutlookMailNode] Microsoft credentials are required but not provided. "
                f"Please connect a Microsoft account in the node's credentials tab."
            )

        # Ensure token is fresh before making API calls
        access_token = await self._ensure_fresh_token(credentials)

        # Execute operation based on config type
        # Original mail operations
        if isinstance(config, OutlookSendConfig):
            output = await self._send_email(
                config, access_token, credentials.email, inputs
            )
        elif isinstance(config, OutlookReadConfig):
            output = await self._read_emails(config, access_token)
        elif isinstance(config, OutlookReplyConfig):
            output = await self._reply_to_email(config, access_token, inputs)
        elif isinstance(config, OutlookForwardConfig):
            output = await self._forward_email(config, access_token, inputs)
        elif isinstance(config, OutlookGetMessageConfig):
            output = await self._get_message(config, access_token)
        elif isinstance(config, OutlookMarkReadConfig):
            output = await self._mark_read(config, access_token)
        elif isinstance(config, OutlookDeleteConfig):
            output = await self._delete_message(config, access_token)
        elif isinstance(config, OutlookMoveConfig):
            output = await self._move_message(config, access_token)
        elif isinstance(config, OutlookCreateDraftConfig):
            output = await self._create_draft(config, access_token, inputs)
        elif isinstance(config, OutlookListFoldersConfig):
            output = await self._list_folders(config, access_token)
        elif isinstance(config, OutlookCreateFolderConfig):
            output = await self._create_folder(config, access_token)
        elif isinstance(config, OutlookGetAttachmentsConfig):
            output = await self._get_attachments(config, access_token)
        elif isinstance(config, OutlookGetMailboxSettingsConfig):
            output = await self._get_mailbox_settings(access_token)
        elif isinstance(config, OutlookUpdateAutoReplyConfig):
            output = await self._update_auto_reply(config, access_token)
        # Advanced message operations
        elif isinstance(config, OutlookCopyMessageConfig):
            output = await self._copy_message(config, access_token)
        elif isinstance(config, OutlookUpdateMessageConfig):
            output = await self._update_message(config, access_token, inputs)
        elif isinstance(config, OutlookSendDraftConfig):
            output = await self._send_draft(config, access_token)
        elif isinstance(config, OutlookCreateReplyDraftConfig):
            output = await self._create_reply_draft(config, access_token)
        elif isinstance(config, OutlookCreateReplyAllDraftConfig):
            output = await self._create_reply_all_draft(config, access_token)
        elif isinstance(config, OutlookCreateForwardDraftConfig):
            output = await self._create_forward_draft(config, access_token)
        # Attachment operations
        elif isinstance(config, OutlookAddAttachmentConfig):
            output = await self._add_attachment(config, access_token, inputs)
        elif isinstance(config, OutlookDeleteAttachmentConfig):
            output = await self._delete_attachment(config, access_token)
        # Folder operations
        elif isinstance(config, OutlookUpdateFolderConfig):
            output = await self._update_folder(config, access_token)
        elif isinstance(config, OutlookDeleteFolderConfig):
            output = await self._delete_folder(config, access_token)
        elif isinstance(config, OutlookMoveFolderConfig):
            output = await self._move_folder(config, access_token)
        elif isinstance(config, OutlookCopyFolderConfig):
            output = await self._copy_folder(config, access_token)
        # Message rules
        elif isinstance(config, OutlookListMessageRulesConfig):
            output = await self._list_message_rules(access_token)
        elif isinstance(config, OutlookGetMessageRuleConfig):
            output = await self._get_message_rule(config, access_token)
        elif isinstance(config, OutlookCreateMessageRuleConfig):
            output = await self._create_message_rule(config, access_token)
        elif isinstance(config, OutlookUpdateMessageRuleConfig):
            output = await self._update_message_rule(config, access_token)
        elif isinstance(config, OutlookDeleteMessageRuleConfig):
            output = await self._delete_message_rule(config, access_token)
        # Categories
        elif isinstance(config, OutlookListCategoriesConfig):
            output = await self._list_categories(access_token)
        elif isinstance(config, OutlookGetCategoryConfig):
            output = await self._get_category(config, access_token)
        elif isinstance(config, OutlookCreateCategoryConfig):
            output = await self._create_category(config, access_token)
        elif isinstance(config, OutlookUpdateCategoryConfig):
            output = await self._update_category(config, access_token)
        elif isinstance(config, OutlookDeleteCategoryConfig):
            output = await self._delete_category(config, access_token)
        # MIME operations
        elif isinstance(config, OutlookGetMimeContentConfig):
            output = await self._get_mime_content(config, access_token)
        elif isinstance(config, OutlookSendMimeConfig):
            output = await self._send_mime(config, access_token, inputs)
        # Calendar operations
        elif isinstance(config, OutlookListEventsConfig):
            output = await self._list_events(config, access_token)
        elif isinstance(config, OutlookCreateEventConfig):
            output = await self._create_event(config, access_token, inputs)
        elif isinstance(config, OutlookGetEventConfig):
            output = await self._get_event(config, access_token)
        elif isinstance(config, OutlookUpdateEventConfig):
            output = await self._update_event(config, access_token, inputs)
        elif isinstance(config, OutlookDeleteEventConfig):
            output = await self._delete_event(config, access_token)
        elif isinstance(config, OutlookCancelEventConfig):
            output = await self._cancel_event(config, access_token, inputs)
        elif isinstance(config, OutlookAcceptEventConfig):
            output = await self._accept_event(config, access_token, inputs)
        elif isinstance(config, OutlookDeclineEventConfig):
            output = await self._decline_event(config, access_token, inputs)
        elif isinstance(config, OutlookTentativelyAcceptEventConfig):
            output = await self._tentatively_accept_event(config, access_token, inputs)
        elif isinstance(config, OutlookDismissReminderConfig):
            output = await self._dismiss_reminder(config, access_token)
        elif isinstance(config, OutlookSnoozeReminderConfig):
            output = await self._snooze_reminder(config, access_token)
        elif isinstance(config, OutlookFindMeetingTimesConfig):
            output = await self._find_meeting_times(config, access_token, inputs)
        elif isinstance(config, OutlookGetScheduleConfig):
            output = await self._get_schedule(config, access_token, inputs)
        elif isinstance(config, OutlookListEventInstancesConfig):
            output = await self._list_event_instances(config, access_token)
        elif isinstance(config, OutlookListCalendarsConfig):
            output = await self._list_calendars(access_token)
        elif isinstance(config, OutlookListCalendarGroupsConfig):
            output = await self._list_calendar_groups(access_token)
        elif isinstance(config, OutlookGetRoomListsConfig):
            output = await self._get_room_lists(access_token)
        # Contacts operations
        elif isinstance(config, OutlookListContactsConfig):
            output = await self._list_contacts(config, access_token)
        elif isinstance(config, OutlookCreateContactConfig):
            output = await self._create_contact(config, access_token, inputs)
        elif isinstance(config, OutlookGetContactConfig):
            output = await self._get_contact(config, access_token)
        elif isinstance(config, OutlookUpdateContactConfig):
            output = await self._update_contact(config, access_token, inputs)
        elif isinstance(config, OutlookDeleteContactConfig):
            output = await self._delete_contact(config, access_token)
        elif isinstance(config, OutlookListContactFoldersConfig):
            output = await self._list_contact_folders(access_token)
        elif isinstance(config, OutlookCreateContactFolderConfig):
            output = await self._create_contact_folder(config, access_token)
        elif isinstance(config, OutlookGetContactFolderConfig):
            output = await self._get_contact_folder(config, access_token)
        elif isinstance(config, OutlookUpdateContactFolderConfig):
            output = await self._update_contact_folder(config, access_token)
        elif isinstance(config, OutlookDeleteContactFolderConfig):
            output = await self._delete_contact_folder(config, access_token)
        elif config.operation in self._EXTRA_CALENDAR_HANDLERS:
            output = await self._EXTRA_CALENDAR_HANDLERS[config.operation](self, config, access_token)
        else:
            raise ValueError(f"Unexpected config type: {type(config)}")

        # Add timing info
        output["timing_ms"] = round((time.time() - start_time) * 1000, 2)

        # Emit output to frontend
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
        from nodes.oauth.microsoft_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data,
            pool=pool,
            user_id=user_id,
            credential_id=credential_id,
            refresh=refresh_access_token,
            provider="microsoft",
        )

    async def _ensure_fresh_token(self, credentials: OutlookOAuthCredential) -> str:
        """Return a valid Outlook access token, refreshing + persisting if expired."""
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

    @staticmethod
    def _build_odata_url(base_url: str, params: Dict[str, Any]) -> str:
        """
        Build a URL with OData query parameters, preserving literal $ in param names.

        httpx encodes $ as %24 when params are passed via the params dict,
        which causes Microsoft Graph API to ignore OData query parameters
        like $top, $select, $filter, $orderby, $expand, and $search.

        This method builds the query string manually to avoid that encoding.

        Args:
            base_url: The base API URL (without query string)
            params: Dict of query parameter names to values

        Returns:
            Full URL string with properly formatted query string
        """
        if not params:
            return base_url
        from urllib.parse import quote

        safe_chars = "@:!$&'()*+,;=-._~/"
        parts = []
        for key, value in params.items():
            parts.append(f"{key}={quote(str(value), safe=safe_chars)}")
        return f"{base_url}?{'&'.join(parts)}"

    def _parse_recipients(self, recipients_str: str) -> List[Dict[str, Any]]:
        """
        Parse comma-separated email addresses into Microsoft Graph format.

        Args:
            recipients_str: Comma-separated email addresses

        Returns:
            List of recipient objects in Graph API format
        """
        recipients = []
        for email in recipients_str.split(","):
            email = email.strip()
            if email:
                recipients.append({"emailAddress": {"address": email}})
        return recipients

    async def _build_outbound_attachments(
        self, refs: List[str]
    ) -> List[Dict[str, Any]]:
        """Resolve resource IDs/URLs into Graph fileAttachment objects.
        Raises ValueError past the per-file / per-message size caps."""
        from nodes.core.media_resolver import resolve_media_input

        parts: List[Dict[str, Any]] = []
        total = 0
        for ref in refs:
            media = await resolve_media_input(
                ref, max_bytes=OUTBOUND_ATTACHMENT_MAX_BYTES
            )
            total += len(media.data)
            if total > OUTBOUND_ATTACHMENT_TOTAL_BYTES:
                raise ValueError(
                    f"Attachments exceed the "
                    f"{OUTBOUND_ATTACHMENT_TOTAL_BYTES // (1024 * 1024)}MB total limit."
                )
            parts.append(
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": media.filename,
                    "contentType": media.mime_type,
                    "contentBytes": media.base64,
                }
            )
        return parts

    async def _send_email(
        self,
        config: OutlookSendConfig,
        access_token: str,
        from_email: str,
        inputs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Send an email via Microsoft Graph API.

        Args:
            config: Send configuration
            access_token: Valid OAuth access token
            from_email: Sender's email address
            inputs: Input data from upstream nodes

        Returns:
            Dict containing send results
        """
        logger.info(f"[OutlookMailNode] Sending email to {config.to}")

        # Resolve template variables if needed
        is_html = config.body_type.lower() != "text"
        body = self._resolve_template(config.body, inputs)
        if is_html:
            body = ensure_html_body(body)
        body = await self._brand_email_body(body, html=is_html)
        subject = self._resolve_template(config.subject, inputs)
        to = self._resolve_template(config.to, inputs)

        # Build message payload
        message = {
            "subject": subject,
            "body": {"contentType": config.body_type, "content": body},
            "toRecipients": self._parse_recipients(to),
        }

        if config.cc:
            message["ccRecipients"] = self._parse_recipients(config.cc)
        if config.bcc:
            message["bccRecipients"] = self._parse_recipients(config.bcc)
        if config.attachments:
            message["attachments"] = await self._build_outbound_attachments(
                config.attachments
            )

        payload = {"message": message, "saveToSentItems": config.save_to_sent}

        url = f"{GRAPH_API_BASE}/me/sendMail"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

            if response.status_code not in [200, 202]:
                error_data = response.json() if response.content else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[OutlookMailNode] Send failed: {error_msg}")
                raise ValueError(f"Microsoft Graph API error: {error_msg}")

            output = {
                "type": "outlook",
                "operation": "send_email_message",
                "to": to,
                "subject": subject,
                "from": from_email,
                "saved_to_sent": config.save_to_sent,
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[OutlookMailNode] Email sent successfully to {to}")
            return output

    async def _read_emails(
        self, config: OutlookReadConfig, access_token: str
    ) -> Dict[str, Any]:
        """
        Read emails from specified folder via Microsoft Graph API.

        Args:
            config: Read configuration
            access_token: Valid OAuth access token

        Returns:
            Dict containing email list
        """
        logger.info(f"[OutlookMailNode] Reading emails from {config.folder}")

        # Build URL and parameters
        url = f"{GRAPH_API_BASE}/me/mailFolders/{config.folder}/messages"

        include_body = config.include_body == "true"

        params = {
            "$top": config.max_results,
        }

        # Add orderby if provided (user can select "Default" to omit)
        if config.order_by:
            params["$orderby"] = config.order_by

        # Add filter if provided
        if config.filter_query:
            params["$filter"] = config.filter_query

        # Add search if provided
        if config.search_query:
            params["$search"] = f'"{config.search_query}"'

        # Select fields to retrieve
        fields = [
            "id",
            "subject",
            "from",
            "toRecipients",
            "ccRecipients",
            "receivedDateTime",
            "isRead",
            "importance",
            "hasAttachments",
        ]
        if include_body:
            fields.extend(["body", "bodyPreview"])

        params["$select"] = ",".join(fields)

        request_url = self._build_odata_url(url, params)

        async with httpx.AsyncClient() as client:
            response = await client.get(
                request_url,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                error_data = response.json() if response.content else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[OutlookMailNode] Read failed: {error_msg}")
                raise ValueError(f"Microsoft Graph API error: {error_msg}")

            data = response.json()
            messages = data.get("value", [])

            # Format messages for output
            emails = []
            for msg in messages:
                email = {
                    "id": msg.get("id"),
                    "subject": msg.get("subject", ""),
                    "from": msg.get("from", {})
                    .get("emailAddress", {})
                    .get("address", ""),
                    "from_name": msg.get("from", {})
                    .get("emailAddress", {})
                    .get("name", ""),
                    "to": [
                        r.get("emailAddress", {}).get("address", "")
                        for r in msg.get("toRecipients", [])
                    ],
                    "cc": [
                        r.get("emailAddress", {}).get("address", "")
                        for r in msg.get("ccRecipients", [])
                    ],
                    "received_at": msg.get("receivedDateTime"),
                    "is_read": msg.get("isRead", False),
                    "importance": msg.get("importance", "normal"),
                    "has_attachments": msg.get("hasAttachments", False),
                    "preview": msg.get("bodyPreview", ""),
                }
                if include_body:
                    email["body"] = msg.get("body", {}).get("content", "")
                    email["body_type"] = msg.get("body", {}).get("contentType", "text")
                emails.append(email)

            output = {
                "type": "outlook",
                "operation": "read_inbox_emails",
                "folder": config.folder,
                "filter": config.filter_query,
                "search": config.search_query,
                "email_count": len(emails),
                "emails": emails,
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(
                f"[OutlookMailNode] Retrieved {len(emails)} emails from {config.folder}"
            )
            return output

    async def _reply_to_email(
        self, config: OutlookReplyConfig, access_token: str, inputs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Reply to an email via Microsoft Graph API.

        Args:
            config: Reply configuration
            access_token: Valid OAuth access token
            inputs: Input data from upstream nodes

        Returns:
            Dict containing reply results
        """
        logger.info(f"[OutlookMailNode] Replying to message {config.message_id}")

        # Graph injects `comment` into the HTML reply body.
        body = await self._brand_email_body(
            ensure_html_body(self._resolve_template(config.body, inputs))
        )

        endpoint = "replyAll" if config.reply_all else "reply"
        url = f"{GRAPH_API_BASE}/me/messages/{config.message_id}/{endpoint}"

        payload = {"comment": body}

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

            if response.status_code not in [200, 202]:
                error_data = response.json() if response.content else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[OutlookMailNode] Reply failed: {error_msg}")
                raise ValueError(f"Microsoft Graph API error: {error_msg}")

            output = {
                "type": "outlook",
                "operation": "reply_to_email_message",
                "message_id": config.message_id,
                "reply_all": config.reply_all,
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[OutlookMailNode] Reply sent successfully")
            return output

    async def _forward_email(
        self, config: OutlookForwardConfig, access_token: str, inputs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Forward an email via Microsoft Graph API.

        Args:
            config: Forward configuration
            access_token: Valid OAuth access token
            inputs: Input data from upstream nodes

        Returns:
            Dict containing forward results
        """
        logger.info(
            f"[OutlookMailNode] Forwarding message {config.message_id} to {config.to}"
        )

        to = self._resolve_template(config.to, inputs)

        url = f"{GRAPH_API_BASE}/me/messages/{config.message_id}/forward"

        payload = {"toRecipients": self._parse_recipients(to)}

        comment = await self._brand_email_body(
            ensure_html_body(self._resolve_template(config.comment, inputs))
            if config.comment
            else ""
        )
        if comment:
            payload["comment"] = comment

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

            if response.status_code not in [200, 202]:
                error_data = response.json() if response.content else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[OutlookMailNode] Forward failed: {error_msg}")
                raise ValueError(f"Microsoft Graph API error: {error_msg}")

            output = {
                "type": "outlook",
                "operation": "forward_email_message",
                "message_id": config.message_id,
                "forwarded_to": to,
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[OutlookMailNode] Email forwarded successfully to {to}")
            return output

    def _resolve_template(self, template: str, inputs: Dict[str, Any]) -> str:
        """
        Resolve template variables in strings.
        Supports {{input.node_id.field}} syntax.

        Args:
            template: String with potential template variables
            inputs: Input data from upstream nodes

        Returns:
            Resolved string
        """
        import re

        def replace_match(match):
            ref_path = match.group(1).strip()
            parts = ref_path.split(".")

            if len(parts) >= 2 and parts[0] == "input":
                node_id = parts[1]
                field_path = parts[2:] if len(parts) > 2 else []

                if node_id in inputs:
                    data = inputs[node_id]
                    for field in field_path:
                        if isinstance(data, dict) and field in data:
                            data = data[field]
                        else:
                            return match.group(0)  # Return original if path invalid
                    return str(data) if not isinstance(data, str) else data

            return match.group(0)  # Return original if not valid reference

        return re.sub(r"\{\{([^}]+)\}\}", replace_match, template)

    # ============================================================================
    # New Operation Methods
    # ============================================================================

    async def _get_message(
        self, config: OutlookGetMessageConfig, access_token: str
    ) -> Dict[str, Any]:
        """
        Get a specific email message by ID via Microsoft Graph API.

        Args:
            config: Get message configuration
            access_token: Valid OAuth access token

        Returns:
            Dict containing the email message
        """
        logger.info(f"[OutlookMailNode] Getting message {config.message_id}")

        url = f"{GRAPH_API_BASE}/me/messages/{config.message_id}"

        # Attachments are listed separately ($select-limited) instead of
        # $expand, which would pull full contentBytes for every attachment.
        request_url = self._build_odata_url(url, {})

        async with httpx.AsyncClient() as client:
            response = await client.get(
                request_url,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                error_data = response.json() if response.content else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[OutlookMailNode] Get message failed: {error_msg}")
                raise ValueError(f"Microsoft Graph API error: {error_msg}")

            msg = response.json()

            email = {
                "id": msg.get("id"),
                "subject": msg.get("subject", ""),
                "from": msg.get("from", {}).get("emailAddress", {}).get("address", ""),
                "from_name": msg.get("from", {})
                .get("emailAddress", {})
                .get("name", ""),
                "to": [
                    r.get("emailAddress", {}).get("address", "")
                    for r in msg.get("toRecipients", [])
                ],
                "cc": [
                    r.get("emailAddress", {}).get("address", "")
                    for r in msg.get("ccRecipients", [])
                ],
                "received_at": msg.get("receivedDateTime"),
                "sent_at": msg.get("sentDateTime"),
                "is_read": msg.get("isRead", False),
                "importance": msg.get("importance", "normal"),
                "has_attachments": msg.get("hasAttachments", False),
                "body": msg.get("body", {}).get("content", ""),
                "body_type": msg.get("body", {}).get("contentType", "text"),
                "preview": msg.get("bodyPreview", ""),
                "conversation_id": msg.get("conversationId"),
                "parent_folder_id": msg.get("parentFolderId"),
            }

            if msg.get("hasAttachments"):
                # Natural surfacing: small text-layer documents inline their
                # extracted text so agents read them without another call.
                # Free CPU path only — AI OCR stays behind the explicit
                # get_email_attachments op (where it is gated + billed).
                from utils.content_extraction import (
                    attachment_record,
                    inline_enrich_attachments,
                )

                list_url = self._build_odata_url(
                    f"{url}/attachments",
                    {"$select": "id,name,contentType,size,isInline"},
                )
                list_response = await client.get(
                    list_url,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if list_response.status_code != 200:
                    error_data = (
                        list_response.json() if list_response.content else {}
                    )
                    error_msg = error_data.get("error", {}).get(
                        "message", list_response.text
                    )
                    logger.error(
                        f"[OutlookMailNode] List attachments failed: {error_msg}"
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                records = [
                    {
                        "id": att.get("id"),
                        "name": att.get("name"),
                        "content_type": att.get("contentType"),
                        "size": att.get("size"),
                        "is_inline": att.get("isInline", False),
                        **attachment_record(
                            filename=att.get("name") or "",
                            mime_type=att.get("contentType") or "",
                            size_bytes=att.get("size"),
                            source="outlook",
                            attachment_id=att.get("id"),
                        ),
                    }
                    for att in list_response.json().get("value", [])
                ]

                async def fetch_bytes(rec: Dict[str, Any]) -> bytes:
                    att = await _graph_call(
                        access_token,
                        "GET",
                        f"/me/messages/{config.message_id}/attachments/{rec['attachment_id']}",
                    )
                    content_b64 = att.get("contentBytes")
                    if not content_b64:
                        raise ValueError(
                            f"Attachment '{rec['filename']}' has no downloadable content."
                        )
                    return base64.b64decode(content_b64)

                email["attachments"] = await inline_enrich_attachments(
                    records, fetch_bytes
                )

            output = {
                "type": "outlook",
                "operation": "get_email_message",
                "email": email,
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[OutlookMailNode] Retrieved message {config.message_id}")
            return output

    async def _mark_read(
        self, config: OutlookMarkReadConfig, access_token: str
    ) -> Dict[str, Any]:
        """
        Mark an email as read or unread via Microsoft Graph API.

        Args:
            config: Mark read configuration
            access_token: Valid OAuth access token

        Returns:
            Dict containing the result
        """
        status_text = "read" if config.is_read else "unread"
        logger.info(
            f"[OutlookMailNode] Marking message {config.message_id} as {status_text}"
        )

        url = f"{GRAPH_API_BASE}/me/messages/{config.message_id}"

        payload = {"isRead": config.is_read}

        async with httpx.AsyncClient() as client:
            response = await client.patch(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

            if response.status_code != 200:
                error_data = response.json() if response.content else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(
                    f"[OutlookMailNode] Mark {status_text} failed: {error_msg}"
                )
                raise ValueError(f"Microsoft Graph API error: {error_msg}")

            output = {
                "type": "outlook",
                "operation": "mark_email_as_read_unread",
                "message_id": config.message_id,
                "is_read": config.is_read,
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[OutlookMailNode] Message marked as {status_text}")
            return output

    async def _delete_message(
        self, config: OutlookDeleteConfig, access_token: str
    ) -> Dict[str, Any]:
        """
        Delete an email via Microsoft Graph API.

        Args:
            config: Delete configuration
            access_token: Valid OAuth access token

        Returns:
            Dict containing the result
        """
        logger.info(
            f"[OutlookMailNode] Deleting message {config.message_id} (permanent={config.permanent})"
        )

        if config.permanent:
            # Permanently delete the message
            url = f"{GRAPH_API_BASE}/me/messages/{config.message_id}"
            async with httpx.AsyncClient() as client:
                response = await client.delete(
                    url, headers={"Authorization": f"Bearer {access_token}"}
                )

                if response.status_code != 204:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    logger.error(f"[OutlookMailNode] Delete failed: {error_msg}")
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")
        else:
            # Move to deleted items folder
            url = f"{GRAPH_API_BASE}/me/messages/{config.message_id}/move"
            payload = {"destinationId": "deleteditems"}
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )

                if response.status_code not in [200, 201]:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    logger.error(f"[OutlookMailNode] Delete failed: {error_msg}")
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

        output = {
            "type": "outlook",
            "operation": "delete_email_message",
            "message_id": config.message_id,
            "permanent": config.permanent,
            "timestamp": time.time(),
            "status": "success",
        }

        logger.info(f"[OutlookMailNode] Message deleted successfully")
        return output

    async def _move_message(
        self, config: OutlookMoveConfig, access_token: str
    ) -> Dict[str, Any]:
        """
        Move an email to a different folder via Microsoft Graph API.

        Args:
            config: Move configuration
            access_token: Valid OAuth access token

        Returns:
            Dict containing the result
        """
        logger.info(
            f"[OutlookMailNode] Moving message {config.message_id} to {config.destination_folder}"
        )

        url = f"{GRAPH_API_BASE}/me/messages/{config.message_id}/move"

        payload = {"destinationId": config.destination_folder}

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

            if response.status_code not in [200, 201]:
                error_data = response.json() if response.content else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[OutlookMailNode] Move failed: {error_msg}")
                raise ValueError(f"Microsoft Graph API error: {error_msg}")

            moved_msg = response.json()

            output = {
                "type": "outlook",
                "operation": "move_email_to_folder",
                "message_id": config.message_id,
                "new_message_id": moved_msg.get("id"),
                "destination_folder": config.destination_folder,
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(
                f"[OutlookMailNode] Message moved to {config.destination_folder}"
            )
            return output

    async def _create_draft(
        self,
        config: OutlookCreateDraftConfig,
        access_token: str,
        inputs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Create an email draft via Microsoft Graph API.

        Args:
            config: Create draft configuration
            access_token: Valid OAuth access token
            inputs: Input data from upstream nodes

        Returns:
            Dict containing the draft message info
        """
        to = self._resolve_template(config.to, inputs)
        subject = self._resolve_template(config.subject, inputs)
        body = ensure_html_body(self._resolve_template(config.body, inputs))

        logger.info(f"[OutlookMailNode] Creating draft email to {to}")

        url = f"{GRAPH_API_BASE}/me/messages"

        payload = {
            "subject": subject,
            "body": {"contentType": "HTML", "content": body},
            "toRecipients": self._parse_recipients(to),
        }

        if config.cc:
            cc = self._resolve_template(config.cc, inputs)
            payload["ccRecipients"] = self._parse_recipients(cc)

        if config.bcc:
            bcc = self._resolve_template(config.bcc, inputs)
            payload["bccRecipients"] = self._parse_recipients(bcc)

        if config.attachments:
            payload["attachments"] = await self._build_outbound_attachments(
                config.attachments
            )

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

            if response.status_code not in [200, 201]:
                error_data = response.json() if response.content else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[OutlookMailNode] Create draft failed: {error_msg}")
                raise ValueError(f"Microsoft Graph API error: {error_msg}")

            draft = response.json()

            output = {
                "type": "outlook",
                "operation": "create_email_draft",
                "draft_id": draft.get("id"),
                "subject": subject,
                "to": to,
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[OutlookMailNode] Draft created with ID {draft.get('id')}")
            return output

    async def _list_folders(
        self, config: OutlookListFoldersConfig, access_token: str
    ) -> Dict[str, Any]:
        """
        List mail folders via Microsoft Graph API.

        Args:
            config: List folders configuration
            access_token: Valid OAuth access token

        Returns:
            Dict containing the folder list
        """
        logger.info(f"[OutlookMailNode] Listing mail folders")

        url = f"{GRAPH_API_BASE}/me/mailFolders"

        params = {
            "$select": "id,displayName,parentFolderId,childFolderCount,totalItemCount,unreadItemCount"
        }

        if config.include_child_folders:
            params["$expand"] = "childFolders"

        request_url = self._build_odata_url(url, params)

        async with httpx.AsyncClient() as client:
            response = await client.get(
                request_url,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                error_data = response.json() if response.content else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[OutlookMailNode] List folders failed: {error_msg}")
                raise ValueError(f"Microsoft Graph API error: {error_msg}")

            data = response.json()
            folders_data = data.get("value", [])

            def format_folder(folder):
                formatted = {
                    "id": folder.get("id"),
                    "name": folder.get("displayName"),
                    "parent_folder_id": folder.get("parentFolderId"),
                    "child_folder_count": folder.get("childFolderCount", 0),
                    "total_item_count": folder.get("totalItemCount", 0),
                    "unread_item_count": folder.get("unreadItemCount", 0),
                }
                if "childFolders" in folder:
                    formatted["child_folders"] = [
                        format_folder(cf) for cf in folder.get("childFolders", [])
                    ]
                return formatted

            folders = [format_folder(f) for f in folders_data]

            output = {
                "type": "outlook",
                "operation": "list_mail_folders",
                "folder_count": len(folders),
                "folders": folders,
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[OutlookMailNode] Retrieved {len(folders)} folders")
            return output

    async def _create_folder(
        self, config: OutlookCreateFolderConfig, access_token: str
    ) -> Dict[str, Any]:
        """
        Create a new mail folder via Microsoft Graph API.

        Args:
            config: Create folder configuration
            access_token: Valid OAuth access token

        Returns:
            Dict containing the new folder info
        """
        logger.info(
            f"[OutlookMailNode] Creating folder '{config.folder_name}' in {config.parent_folder}"
        )

        # Use msgfolderroot for root-level folders, otherwise use the folder name
        if config.parent_folder == "msgfolderroot":
            url = f"{GRAPH_API_BASE}/me/mailFolders"
        else:
            url = f"{GRAPH_API_BASE}/me/mailFolders/{config.parent_folder}/childFolders"

        payload = {"displayName": config.folder_name}

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

            if response.status_code not in [200, 201]:
                error_data = response.json() if response.content else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[OutlookMailNode] Create folder failed: {error_msg}")
                raise ValueError(f"Microsoft Graph API error: {error_msg}")

            folder = response.json()

            output = {
                "type": "outlook",
                "operation": "create_mail_folder",
                "folder_id": folder.get("id"),
                "folder_name": folder.get("displayName"),
                "parent_folder": config.parent_folder,
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[OutlookMailNode] Folder created with ID {folder.get('id')}")
            return output

    async def _get_attachments(
        self, config: OutlookGetAttachmentsConfig, access_token: str
    ) -> Dict[str, Any]:
        """
        Get attachments from an email via Microsoft Graph API.

        Args:
            config: Get attachments configuration
            access_token: Valid OAuth access token

        Returns:
            Dict containing the attachments
        """
        from utils.content_extraction import (
            BillingContext,
            attachment_record,
            extract_content,
        )

        logger.info(
            f"[OutlookMailNode] Getting attachments for message {config.message_id}"
        )

        url = f"{GRAPH_API_BASE}/me/messages/{config.message_id}/attachments"
        extract = config.extract_text == "true"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                error_data = response.json() if response.content else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[OutlookMailNode] Get attachments failed: {error_msg}")
                raise ValueError(f"Microsoft Graph API error: {error_msg}")

            data = response.json()
            attachments_data = data.get("value", [])

            attachments = []
            for att in attachments_data:
                attachment = {
                    "id": att.get("id"),
                    "name": att.get("name"),
                    "content_type": att.get("contentType"),
                    "size": att.get("size"),
                    "is_inline": att.get("isInline", False),
                    "attachment_type": att.get("@odata.type", "").replace(
                        "#microsoft.graph.", ""
                    ),
                    **attachment_record(
                        filename=att.get("name") or "",
                        mime_type=att.get("contentType") or "",
                        size_bytes=att.get("size"),
                        source="outlook",
                        attachment_id=att.get("id"),
                    ),
                }
                if extract:
                    # Extract mode never emits content_base64 — raw base64 is
                    # token-toxic for agents; a failed extraction keeps the
                    # metadata plus a note instead of failing the batch.
                    content_b64 = att.get("contentBytes")
                    if not content_b64:
                        attachment["note"] = (
                            f"Attachment '{attachment['filename']}' has no "
                            "downloadable content."
                        )
                    else:
                        try:
                            content = await extract_content(
                                base64.b64decode(content_b64),
                                mime_type=attachment["mime_type"],
                                filename=attachment["filename"],
                                allow_ai=config.allow_ai_ocr == "true",
                                billing=BillingContext(
                                    user_id=self.user_id,
                                    organization_id=self.organization_id,
                                    workflow_id=str(self.workflow_id)
                                    if self.workflow_id
                                    else None,
                                    node_id=self.node_id,
                                    sio=self.sio,
                                    sid=self.sid,
                                ),
                            )
                            attachment.update(
                                {
                                    "text": content.text,
                                    "extraction_method": content.method,
                                    "pages": content.pages,
                                }
                            )
                        except Exception as e:
                            attachment["note"] = str(e)
                elif config.include_content and "contentBytes" in att:
                    attachment["content_base64"] = att.get("contentBytes")
                attachments.append(attachment)

            output = {
                "type": "outlook",
                "operation": "get_email_attachments",
                "message_id": config.message_id,
                "attachment_count": len(attachments),
                "attachments": attachments,
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[OutlookMailNode] Retrieved {len(attachments)} attachments")
            return output

    async def _get_mailbox_settings(self, access_token: str) -> Dict[str, Any]:
        """
        Get mailbox settings via Microsoft Graph API.

        Args:
            access_token: Valid OAuth access token

        Returns:
            Dict containing mailbox settings
        """
        logger.info(f"[OutlookMailNode] Getting mailbox settings")

        url = f"{GRAPH_API_BASE}/me/mailboxSettings"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                error_data = response.json() if response.content else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(
                    f"[OutlookMailNode] Get mailbox settings failed: {error_msg}"
                )
                raise ValueError(f"Microsoft Graph API error: {error_msg}")

            settings = response.json()

            auto_reply = settings.get("automaticRepliesSetting", {})

            output = {
                "type": "outlook",
                "operation": "get_mailbox_settings",
                "settings": {
                    "timezone": settings.get("timeZone"),
                    "language": settings.get("language", {}).get("locale"),
                    "date_format": settings.get("dateFormat"),
                    "time_format": settings.get("timeFormat"),
                    "archive_folder": settings.get("archiveFolder"),
                    "auto_reply": {
                        "status": auto_reply.get("status"),
                        "external_audience": auto_reply.get("externalAudience"),
                        "internal_message": auto_reply.get("internalReplyMessage"),
                        "external_message": auto_reply.get("externalReplyMessage"),
                        "scheduled_start": auto_reply.get(
                            "scheduledStartDateTime", {}
                        ).get("dateTime"),
                        "scheduled_end": auto_reply.get("scheduledEndDateTime", {}).get(
                            "dateTime"
                        ),
                    },
                },
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[OutlookMailNode] Retrieved mailbox settings")
            return output

    async def _update_auto_reply(
        self, config: OutlookUpdateAutoReplyConfig, access_token: str
    ) -> Dict[str, Any]:
        """
        Update auto-reply (out of office) settings via Microsoft Graph API.

        Args:
            config: Update auto-reply configuration
            access_token: Valid OAuth access token

        Returns:
            Dict containing the result
        """
        logger.info(
            f"[OutlookMailNode] Updating auto-reply settings (enabled={config.enabled})"
        )

        url = f"{GRAPH_API_BASE}/me/mailboxSettings"

        auto_reply_setting = {
            "status": "alwaysEnabled" if config.enabled else "disabled",
            "externalAudience": config.external_audience,
        }

        if config.internal_message:
            auto_reply_setting["internalReplyMessage"] = config.internal_message

        if config.external_message:
            auto_reply_setting["externalReplyMessage"] = config.external_message

        # If scheduled dates are provided, use scheduled status
        if config.start_date and config.end_date and config.enabled:
            auto_reply_setting["status"] = "scheduled"
            auto_reply_setting["scheduledStartDateTime"] = {
                "dateTime": config.start_date,
                "timeZone": "UTC",
            }
            auto_reply_setting["scheduledEndDateTime"] = {
                "dateTime": config.end_date,
                "timeZone": "UTC",
            }

        payload = {"automaticRepliesSetting": auto_reply_setting}

        async with httpx.AsyncClient() as client:
            response = await client.patch(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

            if response.status_code != 200:
                error_data = response.json() if response.content else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[OutlookMailNode] Update auto-reply failed: {error_msg}")
                raise ValueError(f"Microsoft Graph API error: {error_msg}")

            output = {
                "type": "outlook",
                "operation": "update_auto_reply_settings",
                "enabled": config.enabled,
                "external_audience": config.external_audience,
                "scheduled": config.start_date is not None
                and config.end_date is not None,
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[OutlookMailNode] Auto-reply settings updated")
            return output

    # ============================================================================
    # NEW MAIL OPERATIONS - Advanced Message Operations
    # ============================================================================

    async def _copy_message(
        self, config: OutlookCopyMessageConfig, access_token: str
    ) -> Dict[str, Any]:
        """Copy a message to another folder"""
        logger.info(
            f"[OutlookMailNode] Copying message {config.message_id} to {config.destination_folder}"
        )

        url = f"{GRAPH_API_BASE}/me/messages/{config.message_id}/copy"
        payload = {"destinationId": config.destination_folder}

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )

                if response.status_code not in [200, 201]:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                copied_msg = response.json()

                return {
                    "type": "outlook",
                    "operation": "copy_message_to_folder",
                    "message_id": config.message_id,
                    "copied_message_id": copied_msg.get("id"),
                    "destination_folder": config.destination_folder,
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] Copy message failed: {e}")
            raise

    async def _update_message(
        self,
        config: OutlookUpdateMessageConfig,
        access_token: str,
        inputs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Update message properties"""
        logger.info(f"[OutlookMailNode] Updating message {config.message_id}")

        url = f"{GRAPH_API_BASE}/me/messages/{config.message_id}"
        payload = {}

        if config.subject:
            payload["subject"] = self._resolve_template(config.subject, inputs)
        if config.importance:
            payload["importance"] = config.importance
        if config.categories:
            payload["categories"] = [c.strip() for c in config.categories.split(",")]
        if config.is_read is not None:
            payload["isRead"] = config.is_read

        try:
            async with httpx.AsyncClient() as client:
                response = await client.patch(
                    url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )

                if response.status_code != 200:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                return {
                    "type": "outlook",
                    "operation": "update_email_message_properties",
                    "message_id": config.message_id,
                    "subject": config.subject if config.subject else None,
                    "importance": config.importance if config.importance else None,
                    "categories": [c.strip() for c in config.categories.split(",")]
                    if config.categories
                    else None,
                    "is_read": config.is_read,
                    "updated_fields": list(payload.keys()),
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] Update message failed: {e}")
            raise

    async def _send_draft(
        self, config: OutlookSendDraftConfig, access_token: str
    ) -> Dict[str, Any]:
        """Send an existing draft"""
        logger.info(f"[OutlookMailNode] Sending draft {config.message_id}")

        url = f"{GRAPH_API_BASE}/me/messages/{config.message_id}/send"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url, headers={"Authorization": f"Bearer {access_token}"}
                )

                if response.status_code not in [200, 202]:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                return {
                    "type": "outlook",
                    "operation": "send_email_draft",
                    "message_id": config.message_id,
                    "draft_id": config.message_id,
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] Send draft failed: {e}")
            raise

    async def _create_reply_draft(
        self, config: OutlookCreateReplyDraftConfig, access_token: str
    ) -> Dict[str, Any]:
        """Create a reply draft"""
        logger.info(f"[OutlookMailNode] Creating reply draft for {config.message_id}")

        url = f"{GRAPH_API_BASE}/me/messages/{config.message_id}/createReply"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url, headers={"Authorization": f"Bearer {access_token}"}
                )

                if response.status_code not in [200, 201]:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                draft = response.json()

                return {
                    "type": "outlook",
                    "operation": "create_reply_draft",
                    "original_message_id": config.message_id,
                    "draft_id": draft.get("id"),
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] Create reply draft failed: {e}")
            raise

    async def _create_reply_all_draft(
        self, config: OutlookCreateReplyAllDraftConfig, access_token: str
    ) -> Dict[str, Any]:
        """Create a reply-all draft"""
        logger.info(
            f"[OutlookMailNode] Creating reply-all draft for {config.message_id}"
        )

        url = f"{GRAPH_API_BASE}/me/messages/{config.message_id}/createReplyAll"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url, headers={"Authorization": f"Bearer {access_token}"}
                )

                if response.status_code not in [200, 201]:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                draft = response.json()

                return {
                    "type": "outlook",
                    "operation": "create_reply_all_draft",
                    "original_message_id": config.message_id,
                    "draft_id": draft.get("id"),
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] Create reply-all draft failed: {e}")
            raise

    async def _create_forward_draft(
        self, config: OutlookCreateForwardDraftConfig, access_token: str
    ) -> Dict[str, Any]:
        """Create a forward draft"""
        logger.info(f"[OutlookMailNode] Creating forward draft for {config.message_id}")

        url = f"{GRAPH_API_BASE}/me/messages/{config.message_id}/createForward"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url, headers={"Authorization": f"Bearer {access_token}"}
                )

                if response.status_code not in [200, 201]:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                draft = response.json()

                return {
                    "type": "outlook",
                    "operation": "create_forward_draft",
                    "original_message_id": config.message_id,
                    "draft_id": draft.get("id"),
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] Create forward draft failed: {e}")
            raise

    # ============================================================================
    # NEW MAIL OPERATIONS - Attachment Operations
    # ============================================================================

    async def _add_attachment(
        self,
        config: OutlookAddAttachmentConfig,
        access_token: str,
        inputs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Add attachment to a message"""
        logger.info(
            f"[OutlookMailNode] Adding attachment {config.file_name} to message {config.message_id}"
        )

        url = f"{GRAPH_API_BASE}/me/messages/{config.message_id}/attachments"

        content_base64 = self._resolve_template(config.content_base64, inputs)
        file_name = self._resolve_template(config.file_name, inputs)

        payload = {
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": file_name,
            "contentBytes": content_base64,
            "contentType": config.content_type,
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )

                if response.status_code not in [200, 201]:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                attachment = response.json()

                return {
                    "type": "outlook",
                    "operation": "add_attachment_to_message",
                    "message_id": config.message_id,
                    "attachment_id": attachment.get("id"),
                    "file_name": file_name,
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] Add attachment failed: {e}")
            raise

    async def _delete_attachment(
        self, config: OutlookDeleteAttachmentConfig, access_token: str
    ) -> Dict[str, Any]:
        """Delete an attachment"""
        logger.info(
            f"[OutlookMailNode] Deleting attachment {config.attachment_id} from message {config.message_id}"
        )

        url = f"{GRAPH_API_BASE}/me/messages/{config.message_id}/attachments/{config.attachment_id}"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.delete(
                    url, headers={"Authorization": f"Bearer {access_token}"}
                )

                if response.status_code != 204:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                return {
                    "type": "outlook",
                    "operation": "delete_attachment_from_message",
                    "message_id": config.message_id,
                    "attachment_id": config.attachment_id,
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] Delete attachment failed: {e}")
            raise

    # ============================================================================
    # NEW MAIL OPERATIONS - Folder Operations
    # ============================================================================

    async def _update_folder(
        self, config: OutlookUpdateFolderConfig, access_token: str
    ) -> Dict[str, Any]:
        """Update a folder"""
        logger.info(f"[OutlookMailNode] Updating folder {config.folder_id}")

        url = f"{GRAPH_API_BASE}/me/mailFolders/{config.folder_id}"
        payload = {"displayName": config.display_name}

        try:
            async with httpx.AsyncClient() as client:
                response = await client.patch(
                    url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )

                if response.status_code != 200:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                return {
                    "type": "outlook",
                    "operation": "update_mail_folder",
                    "folder_id": config.folder_id,
                    "folder_name": config.display_name,
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] Update folder failed: {e}")
            raise

    async def _delete_folder(
        self, config: OutlookDeleteFolderConfig, access_token: str
    ) -> Dict[str, Any]:
        """Delete a folder"""
        logger.info(f"[OutlookMailNode] Deleting folder {config.folder_id}")

        url = f"{GRAPH_API_BASE}/me/mailFolders/{config.folder_id}"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.delete(
                    url, headers={"Authorization": f"Bearer {access_token}"}
                )

                if response.status_code != 204:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                return {
                    "type": "outlook",
                    "operation": "delete_mail_folder",
                    "folder_id": config.folder_id,
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] Delete folder failed: {e}")
            raise

    async def _move_folder(
        self, config: OutlookMoveFolderConfig, access_token: str
    ) -> Dict[str, Any]:
        """Move a folder"""
        logger.info(
            f"[OutlookMailNode] Moving folder {config.folder_id} to {config.destination_folder_id}"
        )

        url = f"{GRAPH_API_BASE}/me/mailFolders/{config.folder_id}/move"
        payload = {"destinationId": config.destination_folder_id}

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )

                if response.status_code not in [200, 201]:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                moved_folder = response.json()

                return {
                    "type": "outlook",
                    "operation": "move_mail_folder",
                    "folder_id": config.folder_id,
                    "new_folder_id": moved_folder.get("id"),
                    "destination_folder_id": config.destination_folder_id,
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] Move folder failed: {e}")
            raise

    async def _copy_folder(
        self, config: OutlookCopyFolderConfig, access_token: str
    ) -> Dict[str, Any]:
        """Copy a folder"""
        logger.info(
            f"[OutlookMailNode] Copying folder {config.folder_id} to {config.destination_folder_id}"
        )

        url = f"{GRAPH_API_BASE}/me/mailFolders/{config.folder_id}/copy"
        payload = {"destinationId": config.destination_folder_id}

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )

                if response.status_code not in [200, 201]:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                copied_folder = response.json()

                return {
                    "type": "outlook",
                    "operation": "copy_mail_folder",
                    "folder_id": config.folder_id,
                    "copied_folder_id": copied_folder.get("id"),
                    "destination_folder_id": config.destination_folder_id,
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] Copy folder failed: {e}")
            raise

    # ============================================================================
    # NEW MAIL OPERATIONS - Message Rules
    # ============================================================================

    async def _list_message_rules(self, access_token: str) -> Dict[str, Any]:
        """List inbox rules"""
        logger.info(f"[OutlookMailNode] Listing message rules")

        url = f"{GRAPH_API_BASE}/me/mailFolders/inbox/messageRules"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url, headers={"Authorization": f"Bearer {access_token}"}
                )

                if response.status_code != 200:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                data = response.json()
                rules = data.get("value", [])

                return {
                    "type": "outlook",
                    "operation": "list_inbox_rules",
                    "rule_count": len(rules),
                    "rules": rules,
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] List message rules failed: {e}")
            raise

    async def _get_message_rule(
        self, config: OutlookGetMessageRuleConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get a specific rule"""
        logger.info(f"[OutlookMailNode] Getting message rule {config.rule_id}")

        url = f"{GRAPH_API_BASE}/me/mailFolders/inbox/messageRules/{config.rule_id}"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url, headers={"Authorization": f"Bearer {access_token}"}
                )

                if response.status_code != 200:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                rule = response.json()

                return {
                    "type": "outlook",
                    "operation": "get_inbox_rule",
                    "rule": rule,
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] Get message rule failed: {e}")
            raise

    async def _create_message_rule(
        self, config: OutlookCreateMessageRuleConfig, access_token: str
    ) -> Dict[str, Any]:
        """Create an inbox rule"""
        import json

        logger.info(f"[OutlookMailNode] Creating message rule '{config.display_name}'")

        url = f"{GRAPH_API_BASE}/me/mailFolders/inbox/messageRules"

        try:
            conditions = json.loads(config.conditions)
            actions = json.loads(config.actions)

            payload = {
                "displayName": config.display_name,
                "conditions": conditions,
                "actions": actions,
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )

                if response.status_code not in [200, 201]:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                rule = response.json()

                return {
                    "type": "outlook",
                    "operation": "create_inbox_rule",
                    "rule_id": rule.get("id"),
                    "rule_name": config.display_name,
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] Create message rule failed: {e}")
            raise

    async def _update_message_rule(
        self, config: OutlookUpdateMessageRuleConfig, access_token: str
    ) -> Dict[str, Any]:
        """Update an inbox rule"""
        import json

        logger.info(f"[OutlookMailNode] Updating message rule {config.rule_id}")

        url = f"{GRAPH_API_BASE}/me/mailFolders/inbox/messageRules/{config.rule_id}"
        payload = {}

        if config.display_name:
            payload["displayName"] = config.display_name
        if config.conditions:
            payload["conditions"] = json.loads(config.conditions)
        if config.actions:
            payload["actions"] = json.loads(config.actions)

        try:
            async with httpx.AsyncClient() as client:
                response = await client.patch(
                    url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )

                if response.status_code != 200:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                return {
                    "type": "outlook",
                    "operation": "update_inbox_rule",
                    "rule_id": config.rule_id,
                    "updated_fields": list(payload.keys()),
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] Update message rule failed: {e}")
            raise

    async def _delete_message_rule(
        self, config: OutlookDeleteMessageRuleConfig, access_token: str
    ) -> Dict[str, Any]:
        """Delete an inbox rule"""
        logger.info(f"[OutlookMailNode] Deleting message rule {config.rule_id}")

        url = f"{GRAPH_API_BASE}/me/mailFolders/inbox/messageRules/{config.rule_id}"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.delete(
                    url, headers={"Authorization": f"Bearer {access_token}"}
                )

                if response.status_code != 204:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                return {
                    "type": "outlook",
                    "operation": "delete_inbox_rule",
                    "rule_id": config.rule_id,
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] Delete message rule failed: {e}")
            raise

    # ============================================================================
    # NEW MAIL OPERATIONS - Categories
    # ============================================================================

    async def _list_categories(self, access_token: str) -> Dict[str, Any]:
        """List master categories"""
        logger.info(f"[OutlookMailNode] Listing categories")

        url = f"{GRAPH_API_BASE}/me/outlook/masterCategories"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url, headers={"Authorization": f"Bearer {access_token}"}
                )

                if response.status_code != 200:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                data = response.json()
                categories = data.get("value", [])

                return {
                    "type": "outlook",
                    "operation": "list_message_categories",
                    "category_count": len(categories),
                    "categories": categories,
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] List categories failed: {e}")
            raise

    async def _get_category(
        self, config: OutlookGetCategoryConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get a specific category"""
        logger.info(f"[OutlookMailNode] Getting category {config.category_id}")

        url = f"{GRAPH_API_BASE}/me/outlook/masterCategories/{config.category_id}"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url, headers={"Authorization": f"Bearer {access_token}"}
                )

                if response.status_code != 200:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                category = response.json()

                return {
                    "type": "outlook",
                    "operation": "get_message_category",
                    "category": category,
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] Get category failed: {e}")
            raise

    async def _create_category(
        self, config: OutlookCreateCategoryConfig, access_token: str
    ) -> Dict[str, Any]:
        """Create a category"""
        logger.info(f"[OutlookMailNode] Creating category '{config.display_name}'")

        url = f"{GRAPH_API_BASE}/me/outlook/masterCategories"
        payload = {"displayName": config.display_name, "color": config.color}

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )

                if response.status_code not in [200, 201]:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                category = response.json()

                return {
                    "type": "outlook",
                    "operation": "create_message_category",
                    "category_id": category.get("id"),
                    "category_name": config.display_name,
                    "color": config.color,
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] Create category failed: {e}")
            raise

    async def _update_category(
        self, config: OutlookUpdateCategoryConfig, access_token: str
    ) -> Dict[str, Any]:
        """Update a category"""
        logger.info(f"[OutlookMailNode] Updating category {config.category_id}")

        url = f"{GRAPH_API_BASE}/me/outlook/masterCategories/{config.category_id}"
        payload = {"color": config.color}

        try:
            async with httpx.AsyncClient() as client:
                response = await client.patch(
                    url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )

                if response.status_code != 200:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                return {
                    "type": "outlook",
                    "operation": "update_message_category",
                    "category_id": config.category_id,
                    "new_color": config.color,
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] Update category failed: {e}")
            raise

    async def _delete_category(
        self, config: OutlookDeleteCategoryConfig, access_token: str
    ) -> Dict[str, Any]:
        """Delete a category"""
        logger.info(f"[OutlookMailNode] Deleting category {config.category_id}")

        url = f"{GRAPH_API_BASE}/me/outlook/masterCategories/{config.category_id}"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.delete(
                    url, headers={"Authorization": f"Bearer {access_token}"}
                )

                if response.status_code != 204:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                return {
                    "type": "outlook",
                    "operation": "delete_message_category",
                    "category_id": config.category_id,
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] Delete category failed: {e}")
            raise

    # ============================================================================
    # NEW MAIL OPERATIONS - MIME Operations
    # ============================================================================

    async def _get_mime_content(
        self, config: OutlookGetMimeContentConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get MIME content of a message"""
        logger.info(
            f"[OutlookMailNode] Getting MIME content for message {config.message_id}"
        )

        url = f"{GRAPH_API_BASE}/me/messages/{config.message_id}/$value"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "message/rfc822",
                    },
                )

                if response.status_code != 200:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                mime_content = response.text

                return {
                    "type": "outlook",
                    "operation": "get_email_mime_content",
                    "message_id": config.message_id,
                    "mime_content": mime_content,
                    "mime_length": len(mime_content),
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] Get MIME content failed: {e}")
            raise

    async def _send_mime(
        self, config: OutlookSendMimeConfig, access_token: str, inputs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Send a MIME formatted message"""
        logger.info(f"[OutlookMailNode] Sending MIME message")

        url = f"{GRAPH_API_BASE}/me/sendMail"

        mime_content = self._resolve_template(config.mime_content, inputs)

        payload = {
            "message": {
                "@odata.type": "#microsoft.graph.message",
                "mimeContent": mime_content,
            }
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )

                if response.status_code not in [200, 202]:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                return {
                    "type": "outlook",
                    "operation": "send_mime_message",
                    "mime_length": len(mime_content),
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] Send MIME failed: {e}")
            raise

    # ============================================================================
    # NEW CALENDAR OPERATIONS
    # ============================================================================

    async def _list_events(
        self, config: OutlookListEventsConfig, access_token: str
    ) -> Dict[str, Any]:
        """List calendar events"""
        logger.info(f"[OutlookMailNode] Listing calendar events")

        url = f"{GRAPH_API_BASE}/me/calendar/events"

        params = {
            "$top": config.max_results,
        }

        if config.order_by:
            params["$orderby"] = config.order_by

        if config.filter_query:
            params["$filter"] = config.filter_query

        request_url = self._build_odata_url(url, params)

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    request_url,
                    headers={"Authorization": f"Bearer {access_token}"},
                )

                if response.status_code != 200:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                data = response.json()
                events = data.get("value", [])

                return {
                    "type": "outlook",
                    "operation": "list_calendar_events",
                    "event_count": len(events),
                    "events": events,
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] List events failed: {e}")
            raise

    async def _create_event(
        self,
        config: OutlookCreateEventConfig,
        access_token: str,
        inputs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create a calendar event"""
        subject = self._resolve_template(config.subject, inputs)
        logger.info(f"[OutlookMailNode] Creating calendar event '{subject}'")

        url = f"{GRAPH_API_BASE}/me/calendar/events"

        payload = {
            "subject": subject,
            "start": {"dateTime": config.start_datetime, "timeZone": config.timezone},
            "end": {"dateTime": config.end_datetime, "timeZone": config.timezone},
        }

        if config.location:
            payload["location"] = {
                "displayName": self._resolve_template(config.location, inputs)
            }

        if config.body:
            payload["body"] = {
                "contentType": "HTML",
                "content": ensure_html_body(
                    self._resolve_template(config.body, inputs)
                ),
            }

        if config.attendees:
            attendees_list = []
            for email in config.attendees.split(","):
                email = email.strip()
                if email:
                    attendees_list.append(
                        {"emailAddress": {"address": email}, "type": "required"}
                    )
            payload["attendees"] = attendees_list

        if config.is_online_meeting:
            payload["isOnlineMeeting"] = True

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )

                if response.status_code not in [200, 201]:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                event = response.json()

                return {
                    "type": "outlook",
                    "operation": "create_calendar_event",
                    "event_id": event.get("id"),
                    "subject": subject,
                    "start": config.start_datetime,
                    "end": config.end_datetime,
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] Create event failed: {e}")
            raise

    async def _get_event(
        self, config: OutlookGetEventConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get a calendar event"""
        logger.info(f"[OutlookMailNode] Getting event {config.event_id}")

        url = f"{GRAPH_API_BASE}/me/events/{config.event_id}"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url, headers={"Authorization": f"Bearer {access_token}"}
                )

                if response.status_code != 200:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                event = response.json()

                return {
                    "type": "outlook",
                    "operation": "get_calendar_event",
                    "event": event,
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] Get event failed: {e}")
            raise

    async def _update_event(
        self,
        config: OutlookUpdateEventConfig,
        access_token: str,
        inputs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Update a calendar event"""
        logger.info(f"[OutlookMailNode] Updating event {config.event_id}")

        url = f"{GRAPH_API_BASE}/me/events/{config.event_id}"
        payload = {}

        if config.subject:
            payload["subject"] = self._resolve_template(config.subject, inputs)
        if config.start_datetime:
            payload["start"] = {"dateTime": config.start_datetime, "timeZone": "UTC"}
        if config.end_datetime:
            payload["end"] = {"dateTime": config.end_datetime, "timeZone": "UTC"}
        if config.location:
            payload["location"] = {
                "displayName": self._resolve_template(config.location, inputs)
            }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.patch(
                    url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )

                if response.status_code != 200:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                return {
                    "type": "outlook",
                    "operation": "update_calendar_event",
                    "event_id": config.event_id,
                    "updated_fields": list(payload.keys()),
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] Update event failed: {e}")
            raise

    async def _delete_event(
        self, config: OutlookDeleteEventConfig, access_token: str
    ) -> Dict[str, Any]:
        """Delete a calendar event"""
        logger.info(f"[OutlookMailNode] Deleting event {config.event_id}")

        url = f"{GRAPH_API_BASE}/me/events/{config.event_id}"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.delete(
                    url, headers={"Authorization": f"Bearer {access_token}"}
                )

                if response.status_code != 204:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                return {
                    "type": "outlook",
                    "operation": "delete_calendar_event",
                    "event_id": config.event_id,
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] Delete event failed: {e}")
            raise

    async def _cancel_event(
        self,
        config: OutlookCancelEventConfig,
        access_token: str,
        inputs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Cancel a calendar event"""
        logger.info(f"[OutlookMailNode] Canceling event {config.event_id}")

        url = f"{GRAPH_API_BASE}/me/events/{config.event_id}/cancel"

        payload = {}
        if config.comment:
            payload["comment"] = self._resolve_template(config.comment, inputs)

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )

                if response.status_code not in [200, 202]:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                return {
                    "type": "outlook",
                    "operation": "cancel_calendar_event",
                    "event_id": config.event_id,
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] Cancel event failed: {e}")
            raise

    async def _accept_event(
        self,
        config: OutlookAcceptEventConfig,
        access_token: str,
        inputs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Accept an event invitation"""
        logger.info(f"[OutlookMailNode] Accepting event {config.event_id}")

        url = f"{GRAPH_API_BASE}/me/events/{config.event_id}/accept"

        payload = {"sendResponse": config.send_response}
        if config.comment:
            payload["comment"] = self._resolve_template(config.comment, inputs)

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )

                if response.status_code not in [200, 202]:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                return {
                    "type": "outlook",
                    "operation": "accept_calendar_event_invitation",
                    "event_id": config.event_id,
                    "send_response": config.send_response,
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] Accept event failed: {e}")
            raise

    async def _decline_event(
        self,
        config: OutlookDeclineEventConfig,
        access_token: str,
        inputs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Decline an event invitation"""
        logger.info(f"[OutlookMailNode] Declining event {config.event_id}")

        url = f"{GRAPH_API_BASE}/me/events/{config.event_id}/decline"

        payload = {"sendResponse": config.send_response}
        if config.comment:
            payload["comment"] = self._resolve_template(config.comment, inputs)

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )

                if response.status_code not in [200, 202]:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                return {
                    "type": "outlook",
                    "operation": "decline_calendar_event_invitation",
                    "event_id": config.event_id,
                    "send_response": config.send_response,
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] Decline event failed: {e}")
            raise

    async def _tentatively_accept_event(
        self,
        config: OutlookTentativelyAcceptEventConfig,
        access_token: str,
        inputs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Tentatively accept an event invitation"""
        logger.info(f"[OutlookMailNode] Tentatively accepting event {config.event_id}")

        url = f"{GRAPH_API_BASE}/me/events/{config.event_id}/tentativelyAccept"

        payload = {"sendResponse": config.send_response}
        if config.comment:
            payload["comment"] = self._resolve_template(config.comment, inputs)

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )

                if response.status_code not in [200, 202]:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                return {
                    "type": "outlook",
                    "operation": "tentatively_accept_calendar_event_invitation",
                    "event_id": config.event_id,
                    "send_response": config.send_response,
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] Tentatively accept event failed: {e}")
            raise

    async def _dismiss_reminder(
        self, config: OutlookDismissReminderConfig, access_token: str
    ) -> Dict[str, Any]:
        """Dismiss an event reminder"""
        logger.info(
            f"[OutlookMailNode] Dismissing reminder for event {config.event_id}"
        )

        url = f"{GRAPH_API_BASE}/me/events/{config.event_id}/dismissReminder"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url, headers={"Authorization": f"Bearer {access_token}"}
                )

                if response.status_code not in [200, 202]:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                return {
                    "type": "outlook",
                    "operation": "dismiss_event_reminder",
                    "event_id": config.event_id,
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] Dismiss reminder failed: {e}")
            raise

    async def _snooze_reminder(
        self, config: OutlookSnoozeReminderConfig, access_token: str
    ) -> Dict[str, Any]:
        """Snooze an event reminder"""
        logger.info(f"[OutlookMailNode] Snoozing reminder for event {config.event_id}")

        url = f"{GRAPH_API_BASE}/me/events/{config.event_id}/snoozeReminder"

        payload = {
            "newReminderTime": {"dateTime": config.new_reminder_time, "timeZone": "UTC"}
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )

                if response.status_code not in [200, 202]:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                return {
                    "type": "outlook",
                    "operation": "snooze_event_reminder",
                    "event_id": config.event_id,
                    "new_reminder_time": config.new_reminder_time,
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] Snooze reminder failed: {e}")
            raise

    async def _find_meeting_times(
        self,
        config: OutlookFindMeetingTimesConfig,
        access_token: str,
        inputs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Find available meeting times"""
        logger.info(f"[OutlookMailNode] Finding meeting times")

        url = f"{GRAPH_API_BASE}/me/findMeetingTimes"

        attendees = self._resolve_template(config.attendees, inputs)
        attendees_list = []
        for email in attendees.split(","):
            email = email.strip()
            if email:
                attendees_list.append(
                    {"emailAddress": {"address": email}, "type": "required"}
                )

        payload = {
            "attendees": attendees_list,
            "timeConstraint": {
                "timeslots": [
                    {
                        "start": {"dateTime": config.start_time, "timeZone": "UTC"},
                        "end": {"dateTime": config.end_time, "timeZone": "UTC"},
                    }
                ]
            },
            "meetingDuration": f"PT{config.meeting_duration}M",
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )

                if response.status_code != 200:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                data = response.json()

                return {
                    "type": "outlook",
                    "operation": "find_available_meeting_times",
                    "meeting_suggestions": data.get("meetingTimeSuggestions", []),
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] Find meeting times failed: {e}")
            raise

    async def _get_schedule(
        self,
        config: OutlookGetScheduleConfig,
        access_token: str,
        inputs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Get free/busy schedule"""
        logger.info(f"[OutlookMailNode] Getting schedules")

        url = f"{GRAPH_API_BASE}/me/calendar/getSchedule"

        schedules = self._resolve_template(config.schedules, inputs)
        schedules_list = [s.strip() for s in schedules.split(",")]

        payload = {
            "schedules": schedules_list,
            "startTime": {"dateTime": config.start_time, "timeZone": "UTC"},
            "endTime": {"dateTime": config.end_time, "timeZone": "UTC"},
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )

                if response.status_code != 200:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                data = response.json()

                return {
                    "type": "outlook",
                    "operation": "get_free_busy_schedule",
                    "schedules": data.get("value", []),
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] Get schedule failed: {e}")
            raise

    async def _list_event_instances(
        self, config: OutlookListEventInstancesConfig, access_token: str
    ) -> Dict[str, Any]:
        """List recurring event instances"""
        logger.info(f"[OutlookMailNode] Listing event instances for {config.event_id}")

        url = f"{GRAPH_API_BASE}/me/events/{config.event_id}/instances"

        params = {
            "startDateTime": config.start_datetime,
            "endDateTime": config.end_datetime,
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {access_token}"},
                    params=params,
                )

                if response.status_code != 200:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                data = response.json()
                instances = data.get("value", [])

                return {
                    "type": "outlook",
                    "operation": "list_recurring_event_instances",
                    "event_id": config.event_id,
                    "instance_count": len(instances),
                    "instances": instances,
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] List event instances failed: {e}")
            raise

    async def _list_calendars(self, access_token: str) -> Dict[str, Any]:
        """List calendars"""
        logger.info(f"[OutlookMailNode] Listing calendars")

        url = f"{GRAPH_API_BASE}/me/calendars"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url, headers={"Authorization": f"Bearer {access_token}"}
                )

                if response.status_code != 200:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                data = response.json()
                calendars = data.get("value", [])

                return {
                    "type": "outlook",
                    "operation": "list_calendars",
                    "calendar_count": len(calendars),
                    "calendars": calendars,
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] List calendars failed: {e}")
            raise

    async def _list_calendar_groups(self, access_token: str) -> Dict[str, Any]:
        """List calendar groups"""
        logger.info(f"[OutlookMailNode] Listing calendar groups")

        url = f"{GRAPH_API_BASE}/me/calendarGroups"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url, headers={"Authorization": f"Bearer {access_token}"}
                )

                if response.status_code != 200:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                data = response.json()
                groups = data.get("value", [])

                return {
                    "type": "outlook",
                    "operation": "list_calendar_groups",
                    "group_count": len(groups),
                    "groups": groups,
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] List calendar groups failed: {e}")
            raise

    async def _get_room_lists(self, access_token: str) -> Dict[str, Any]:
        """Get room lists"""
        logger.info(f"[OutlookMailNode] Getting room lists")

        url = f"{GRAPH_API_BASE}/places/microsoft.graph.roomList"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url, headers={"Authorization": f"Bearer {access_token}"}
                )

                if response.status_code != 200:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                data = response.json()
                room_lists = data.get("value", [])

                return {
                    "type": "outlook",
                    "operation": "get_available_room_lists",
                    "room_list_count": len(room_lists),
                    "room_lists": room_lists,
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] Get room lists failed: {e}")
            raise

    # ============================================================================
    # NEW CONTACTS OPERATIONS
    # ============================================================================

    async def _list_contacts(
        self, config: OutlookListContactsConfig, access_token: str
    ) -> Dict[str, Any]:
        """List contacts"""
        logger.info(f"[OutlookMailNode] Listing contacts")

        url = f"{GRAPH_API_BASE}/me/contacts"

        params = {
            "$top": config.max_results,
        }

        if config.order_by:
            params["$orderby"] = config.order_by

        if config.filter_query:
            params["$filter"] = config.filter_query

        request_url = self._build_odata_url(url, params)

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    request_url,
                    headers={"Authorization": f"Bearer {access_token}"},
                )

                if response.status_code != 200:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                data = response.json()
                contacts = data.get("value", [])

                return {
                    "type": "outlook",
                    "operation": "list_contacts",
                    "contact_count": len(contacts),
                    "contacts": contacts,
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] List contacts failed: {e}")
            raise

    async def _create_contact(
        self,
        config: OutlookCreateContactConfig,
        access_token: str,
        inputs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create a contact"""
        given_name = self._resolve_template(config.given_name, inputs)
        surname = self._resolve_template(config.surname, inputs)
        logger.info(f"[OutlookMailNode] Creating contact {given_name} {surname}")

        url = f"{GRAPH_API_BASE}/me/contacts"

        payload = {"givenName": given_name, "surname": surname}

        if config.email_address:
            payload["emailAddresses"] = [
                {"address": self._resolve_template(config.email_address, inputs)}
            ]

        if config.business_phone:
            payload["businessPhones"] = [
                self._resolve_template(config.business_phone, inputs)
            ]

        if config.mobile_phone:
            payload["mobilePhone"] = self._resolve_template(config.mobile_phone, inputs)

        if config.home_phone:
            payload["homePhones"] = [self._resolve_template(config.home_phone, inputs)]

        if config.job_title:
            payload["jobTitle"] = self._resolve_template(config.job_title, inputs)

        if config.company_name:
            payload["companyName"] = self._resolve_template(config.company_name, inputs)

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )

                if response.status_code not in [200, 201]:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                contact = response.json()

                return {
                    "type": "outlook",
                    "operation": "create_contact_person",
                    "contact_id": contact.get("id"),
                    "given_name": given_name,
                    "surname": surname,
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] Create contact failed: {e}")
            raise

    async def _get_contact(
        self, config: OutlookGetContactConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get a contact"""
        logger.info(f"[OutlookMailNode] Getting contact {config.contact_id}")

        url = f"{GRAPH_API_BASE}/me/contacts/{config.contact_id}"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url, headers={"Authorization": f"Bearer {access_token}"}
                )

                if response.status_code != 200:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                contact = response.json()

                return {
                    "type": "outlook",
                    "operation": "get_contact_person",
                    "contact": contact,
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] Get contact failed: {e}")
            raise

    async def _update_contact(
        self,
        config: OutlookUpdateContactConfig,
        access_token: str,
        inputs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Update a contact"""
        logger.info(f"[OutlookMailNode] Updating contact {config.contact_id}")

        url = f"{GRAPH_API_BASE}/me/contacts/{config.contact_id}"
        payload = {}

        if config.given_name:
            payload["givenName"] = self._resolve_template(config.given_name, inputs)
        if config.surname:
            payload["surname"] = self._resolve_template(config.surname, inputs)
        if config.email_address:
            payload["emailAddresses"] = [
                {"address": self._resolve_template(config.email_address, inputs)}
            ]
        if config.mobile_phone:
            payload["mobilePhone"] = self._resolve_template(config.mobile_phone, inputs)

        try:
            async with httpx.AsyncClient() as client:
                response = await client.patch(
                    url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )

                if response.status_code != 200:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                return {
                    "type": "outlook",
                    "operation": "update_contact_person",
                    "contact_id": config.contact_id,
                    "updated_fields": list(payload.keys()),
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] Update contact failed: {e}")
            raise

    async def _delete_contact(
        self, config: OutlookDeleteContactConfig, access_token: str
    ) -> Dict[str, Any]:
        """Delete a contact"""
        logger.info(f"[OutlookMailNode] Deleting contact {config.contact_id}")

        url = f"{GRAPH_API_BASE}/me/contacts/{config.contact_id}"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.delete(
                    url, headers={"Authorization": f"Bearer {access_token}"}
                )

                if response.status_code != 204:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                return {
                    "type": "outlook",
                    "operation": "delete_contact_person",
                    "contact_id": config.contact_id,
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] Delete contact failed: {e}")
            raise

    async def _list_contact_folders(self, access_token: str) -> Dict[str, Any]:
        """List contact folders"""
        logger.info(f"[OutlookMailNode] Listing contact folders")

        url = f"{GRAPH_API_BASE}/me/contactFolders"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url, headers={"Authorization": f"Bearer {access_token}"}
                )

                if response.status_code != 200:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                data = response.json()
                folders = data.get("value", [])

                return {
                    "type": "outlook",
                    "operation": "list_contact_folders",
                    "folder_count": len(folders),
                    "folders": folders,
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] List contact folders failed: {e}")
            raise

    async def _create_contact_folder(
        self, config: OutlookCreateContactFolderConfig, access_token: str
    ) -> Dict[str, Any]:
        """Create a contact folder"""
        logger.info(
            f"[OutlookMailNode] Creating contact folder '{config.display_name}'"
        )

        if config.parent_folder_id:
            url = f"{GRAPH_API_BASE}/me/contactFolders/{config.parent_folder_id}/childFolders"
        else:
            url = f"{GRAPH_API_BASE}/me/contactFolders"

        payload = {"displayName": config.display_name}

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )

                if response.status_code not in [200, 201]:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                folder = response.json()

                return {
                    "type": "outlook",
                    "operation": "create_contact_folder",
                    "folder_id": folder.get("id"),
                    "folder_name": config.display_name,
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] Create contact folder failed: {e}")
            raise

    async def _get_contact_folder(
        self, config: OutlookGetContactFolderConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get a contact folder"""
        logger.info(f"[OutlookMailNode] Getting contact folder {config.folder_id}")

        url = f"{GRAPH_API_BASE}/me/contactFolders/{config.folder_id}"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url, headers={"Authorization": f"Bearer {access_token}"}
                )

                if response.status_code != 200:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                folder = response.json()

                return {
                    "type": "outlook",
                    "operation": "get_contact_folder",
                    "folder": folder,
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] Get contact folder failed: {e}")
            raise

    async def _update_contact_folder(
        self, config: OutlookUpdateContactFolderConfig, access_token: str
    ) -> Dict[str, Any]:
        """Update a contact folder"""
        logger.info(f"[OutlookMailNode] Updating contact folder {config.folder_id}")

        url = f"{GRAPH_API_BASE}/me/contactFolders/{config.folder_id}"
        payload = {"displayName": config.display_name}

        try:
            async with httpx.AsyncClient() as client:
                response = await client.patch(
                    url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )

                if response.status_code != 200:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                return {
                    "type": "outlook",
                    "operation": "update_contact_folder",
                    "folder_id": config.folder_id,
                    "new_name": config.display_name,
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] Update contact folder failed: {e}")
            raise

    async def _delete_contact_folder(
        self, config: OutlookDeleteContactFolderConfig, access_token: str
    ) -> Dict[str, Any]:
        """Delete a contact folder"""
        logger.info(f"[OutlookMailNode] Deleting contact folder {config.folder_id}")

        url = f"{GRAPH_API_BASE}/me/contactFolders/{config.folder_id}"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.delete(
                    url, headers={"Authorization": f"Bearer {access_token}"}
                )

                if response.status_code != 204:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Microsoft Graph API error: {error_msg}")

                return {
                    "type": "outlook",
                    "operation": "delete_contact_folder",
                    "folder_id": config.folder_id,
                    "timestamp": time.time(),
                    "status": "success",
                }
        except Exception as e:
            logger.error(f"[OutlookMailNode] Delete contact folder failed: {e}")
            raise

    # ======================================================================
    # Additional Calendar handlers (calendar/group CRUD, calendarView,
    # forward, attachments, delta, sharing permissions, reminder view)
    # ======================================================================
    def _ok(self, operation: str, **fields) -> Dict[str, Any]:
        return {"type": "outlook", "operation": operation, "timestamp": time.time(),
                "status": "success", **fields}

    async def _get_calendar(self, c, token: str) -> Dict[str, Any]:
        data = await _graph_call(token, "GET", f"/me/calendars/{c.calendar_id}")
        return self._ok("get_calendar", calendar=data)

    async def _create_calendar(self, c, token: str) -> Dict[str, Any]:
        body = {"name": c.name}
        if c.color:
            body["color"] = c.color
        data = await _graph_call(token, "POST", "/me/calendars", json_body=body)
        return self._ok("create_calendar", calendar=data)

    async def _update_calendar(self, c, token: str) -> Dict[str, Any]:
        body = {}
        if c.name is not None:
            body["name"] = c.name
        if c.color is not None:
            body["color"] = c.color
        data = await _graph_call(token, "PATCH", f"/me/calendars/{c.calendar_id}", json_body=body)
        return self._ok("update_calendar", calendar=data)

    async def _delete_calendar(self, c, token: str) -> Dict[str, Any]:
        await _graph_call(token, "DELETE", f"/me/calendars/{c.calendar_id}")
        return self._ok("delete_calendar", calendar_id=c.calendar_id)

    async def _get_calendar_view(self, c, token: str) -> Dict[str, Any]:
        base = f"/me/calendars/{c.calendar_id}/calendarView" if c.calendar_id else "/me/calendarView"
        params = {"startDateTime": c.start_date_time, "endDateTime": c.end_date_time, "$top": c.top}
        data = await _graph_call(token, "GET", base, params=params)
        events = data.get("value", [])
        return self._ok("get_calendar_view", events=events, event_count=len(events))

    async def _forward_calendar_event(self, c, token: str) -> Dict[str, Any]:
        recipients = [{"emailAddress": {"address": a.strip()}}
                      for a in (c.to_recipients or "").split(",") if a.strip()]
        body = {"ToRecipients": recipients, "Comment": c.comment or ""}
        await _graph_call(token, "POST", f"/me/events/{c.event_id}/forward", json_body=body)
        return self._ok("forward_calendar_event", event_id=c.event_id)

    async def _list_event_attachments(self, c, token: str) -> Dict[str, Any]:
        data = await _graph_call(token, "GET", f"/me/events/{c.event_id}/attachments")
        atts = data.get("value", [])
        return self._ok("list_event_attachments", attachments=atts, attachment_count=len(atts))

    async def _add_event_attachment(self, c, token: str) -> Dict[str, Any]:
        body = {"@odata.type": "#microsoft.graph.fileAttachment", "name": c.name,
                "contentBytes": c.content_bytes}
        if c.content_type:
            body["contentType"] = c.content_type
        data = await _graph_call(token, "POST", f"/me/events/{c.event_id}/attachments", json_body=body)
        return self._ok("add_event_attachment", attachment=data)

    async def _get_event_attachment(self, c, token: str) -> Dict[str, Any]:
        data = await _graph_call(token, "GET", f"/me/events/{c.event_id}/attachments/{c.attachment_id}")
        return self._ok("get_event_attachment", attachment=data)

    async def _delete_event_attachment(self, c, token: str) -> Dict[str, Any]:
        await _graph_call(token, "DELETE", f"/me/events/{c.event_id}/attachments/{c.attachment_id}")
        return self._ok("delete_event_attachment", attachment_id=c.attachment_id)

    async def _get_calendar_view_delta(self, c, token: str) -> Dict[str, Any]:
        if c.delta_token and c.delta_token.startswith("http"):
            # Resume from a full @odata.deltaLink URL.
            path = c.delta_token[len(GRAPH_API_BASE):] if c.delta_token.startswith(GRAPH_API_BASE) else c.delta_token
            data = await _graph_call(token, "GET", path)
        else:
            params = {"startDateTime": c.start_date_time, "endDateTime": c.end_date_time}
            if c.delta_token:
                params["$deltatoken"] = c.delta_token
            data = await _graph_call(token, "GET", "/me/calendarView/delta", params=params)
        events = data.get("value", [])
        return self._ok("get_calendar_view_delta", events=events, event_count=len(events),
                        delta_link=data.get("@odata.deltaLink"), next_link=data.get("@odata.nextLink"))

    async def _create_calendar_group(self, c, token: str) -> Dict[str, Any]:
        data = await _graph_call(token, "POST", "/me/calendarGroups", json_body={"name": c.name})
        return self._ok("create_calendar_group", calendar_group=data)

    async def _get_calendar_group(self, c, token: str) -> Dict[str, Any]:
        data = await _graph_call(token, "GET", f"/me/calendarGroups/{c.group_id}")
        return self._ok("get_calendar_group", calendar_group=data)

    async def _update_calendar_group(self, c, token: str) -> Dict[str, Any]:
        data = await _graph_call(token, "PATCH", f"/me/calendarGroups/{c.group_id}", json_body={"name": c.name})
        return self._ok("update_calendar_group", calendar_group=data)

    async def _delete_calendar_group(self, c, token: str) -> Dict[str, Any]:
        await _graph_call(token, "DELETE", f"/me/calendarGroups/{c.group_id}")
        return self._ok("delete_calendar_group", group_id=c.group_id)

    async def _list_calendars_in_group(self, c, token: str) -> Dict[str, Any]:
        data = await _graph_call(token, "GET", f"/me/calendarGroups/{c.group_id}/calendars")
        cals = data.get("value", [])
        return self._ok("list_calendars_in_group", calendars=cals, calendar_count=len(cals))

    async def _create_calendar_in_group(self, c, token: str) -> Dict[str, Any]:
        data = await _graph_call(token, "POST", f"/me/calendarGroups/{c.group_id}/calendars",
                                 json_body={"name": c.name})
        return self._ok("create_calendar_in_group", calendar=data)

    async def _list_calendar_permissions(self, c, token: str) -> Dict[str, Any]:
        data = await _graph_call(token, "GET", f"/me/calendars/{c.calendar_id}/calendarPermissions")
        perms = data.get("value", [])
        return self._ok("list_calendar_permissions", permissions=perms, permission_count=len(perms))

    async def _get_calendar_permission(self, c, token: str) -> Dict[str, Any]:
        data = await _graph_call(token, "GET",
                                 f"/me/calendars/{c.calendar_id}/calendarPermissions/{c.permission_id}")
        return self._ok("get_calendar_permission", permission=data)

    async def _create_calendar_permission(self, c, token: str) -> Dict[str, Any]:
        import json as _json
        try:
            body = _json.loads(c.resource)
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid Permission JSON: {e}")
        data = await _graph_call(token, "POST", f"/me/calendars/{c.calendar_id}/calendarPermissions", json_body=body)
        return self._ok("create_calendar_permission", permission=data)

    async def _update_calendar_permission(self, c, token: str) -> Dict[str, Any]:
        data = await _graph_call(token, "PATCH",
                                 f"/me/calendars/{c.calendar_id}/calendarPermissions/{c.permission_id}",
                                 json_body={"role": c.role})
        return self._ok("update_calendar_permission", permission=data)

    async def _delete_calendar_permission(self, c, token: str) -> Dict[str, Any]:
        await _graph_call(token, "DELETE",
                          f"/me/calendars/{c.calendar_id}/calendarPermissions/{c.permission_id}")
        return self._ok("delete_calendar_permission", permission_id=c.permission_id)

    async def _allowed_calendar_sharing_roles(self, c, token: str) -> Dict[str, Any]:
        from urllib.parse import quote
        user = quote(c.user_email, safe="")
        data = await _graph_call(token, "GET",
                                 f"/me/calendars/{c.calendar_id}/allowedCalendarSharingRoles(User='{user}')")
        return self._ok("allowed_calendar_sharing_roles", value=data.get("value", []))

    async def _reminder_view(self, c, token: str) -> Dict[str, Any]:
        from urllib.parse import quote
        start = quote(c.start_date_time, safe="")
        end = quote(c.end_date_time, safe="")
        data = await _graph_call(token, "GET",
                                 f"/me/reminderView(startDateTime='{start}',endDateTime='{end}')")
        reminders = data.get("value", [])
        return self._ok("reminder_view", reminders=reminders, reminder_count=len(reminders))

    _EXTRA_CALENDAR_HANDLERS = {
        "get_calendar": _get_calendar,
        "create_calendar": _create_calendar,
        "update_calendar": _update_calendar,
        "delete_calendar": _delete_calendar,
        "get_calendar_view": _get_calendar_view,
        "forward_calendar_event": _forward_calendar_event,
        "list_event_attachments": _list_event_attachments,
        "add_event_attachment": _add_event_attachment,
        "get_event_attachment": _get_event_attachment,
        "delete_event_attachment": _delete_event_attachment,
        "get_calendar_view_delta": _get_calendar_view_delta,
        "create_calendar_group": _create_calendar_group,
        "get_calendar_group": _get_calendar_group,
        "update_calendar_group": _update_calendar_group,
        "delete_calendar_group": _delete_calendar_group,
        "list_calendars_in_group": _list_calendars_in_group,
        "create_calendar_in_group": _create_calendar_in_group,
        "list_calendar_permissions": _list_calendar_permissions,
        "get_calendar_permission": _get_calendar_permission,
        "create_calendar_permission": _create_calendar_permission,
        "update_calendar_permission": _update_calendar_permission,
        "delete_calendar_permission": _delete_calendar_permission,
        "allowed_calendar_sharing_roles": _allowed_calendar_sharing_roles,
        "reminder_view": _reminder_view,
    }

    # ======================================================================
    # Dynamic options (calendar dropdown)
    # ======================================================================
    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Populate calendar and mail-folder dropdowns."""
        access_token = (credential_data or {}).get("access_token")
        if not access_token:
            return {"options": []}

        if field_name == "calendar_id":
            try:
                data = await _graph_call(access_token, "GET", "/me/calendars", params={"$top": "100"})
            except Exception:
                return {"options": []}
            options = []
            for cal in data.get("value", []) or []:
                if isinstance(cal, dict) and cal.get("id"):
                    options.append({"label": str(cal.get("name") or cal["id"]), "value": str(cal["id"])})
            return {"options": options}

        if field_name == "mail_folder_id":
            try:
                data = await _graph_call(access_token, "GET", "/me/mailFolders", params={"$top": "100"})
            except Exception:
                return {"options": []}
            options = []
            for folder in data.get("value", []) or []:
                if isinstance(folder, dict) and folder.get("id"):
                    label = str(folder.get("displayName") or folder["id"])
                    options.append({"label": label, "value": str(folder["id"])})
            return {"options": options}

        return {"options": []}

    # ======================================================================
    # Calendar-event change-notification webhook trigger
    # ======================================================================
    @classmethod
    def registration_fingerprint_fields(cls, config):
        # Config fields the provider-side registration depends on — feed the
        # reconciler's fingerprint so edits here re-register (declarative:
        # the node never sequences teardown/re-register).
        return {
            "folder_id": (config or {}).get("folder_id"),
            "calendar_id": (config or {}).get("calendar_id"),
        }

    @classmethod
    async def _register_external_webhook(
        cls, *, webhook_url: str, credential: Dict[str, Any], config: Dict[str, Any], node_id: str
    ) -> Optional[Dict[str, Any]]:
        from datetime import datetime, timedelta, timezone as _tz

        access_token = (credential or {}).get("access_token")
        if not access_token:
            raise ValueError("A connected Microsoft account is required to register the trigger")
        cfg = config or {}
        operation = cfg.get("operation", "")

        if operation in MAIL_TRIGGER_CHANGE_TYPES:
            folder_id = cfg.get("folder_id") or "inbox"
            resource = f"/me/mailFolders/{folder_id}/messages"
            change_type = MAIL_TRIGGER_CHANGE_TYPES[operation]
        else:
            calendar_id = cfg.get("calendar_id")
            resource = f"/me/calendars/{calendar_id}/events" if calendar_id else "/me/events"
            change_type = CALENDAR_TRIGGER_CHANGE_TYPES.get(operation, "created,updated,deleted")

        secret = hashlib.sha256(f"{node_id}:{webhook_url}".encode()).hexdigest()[:32]
        expiration = (datetime.now(_tz.utc) + timedelta(minutes=SUBSCRIPTION_LIFETIME_MINUTES)).isoformat()
        data = await _graph_call(
            access_token, "POST", "/subscriptions",
            json_body={
                "changeType": change_type,
                "notificationUrl": webhook_url,
                "resource": resource,
                "expirationDateTime": expiration,
                "clientState": secret,
            },
        )
        return {"external_webhook_id": str(data.get("id")) if data.get("id") else None,
                "signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(
        cls, *, credential: Dict[str, Any], config: Dict[str, Any], node_id: str
    ) -> None:
        external_id = (config or {}).get("external_webhook_id")
        access_token = (credential or {}).get("access_token")
        if not external_id or not access_token:
            return
        try:
            await _graph_call(access_token, "DELETE", f"/subscriptions/{external_id}")
        except Exception as e:
            logger.warning(f"[OutlookMailNode] Failed to delete Graph subscription: {e}")

    @classmethod
    def verify_webhook_signature(cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]) -> bool:
        """Graph echoes the registered clientState in each notification payload."""
        import json as _json
        secret = (config or {}).get("signing_secret")
        if not secret:
            return True
        try:
            payload = _json.loads(body.decode("utf-8"))
        except Exception:
            return False
        notifications = payload.get("value", [])
        if not isinstance(notifications, list) or not notifications:
            return False
        return all(n.get("clientState") == secret for n in notifications)
