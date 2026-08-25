"""
Gmail workflow node implementation.
Enables full Gmail API access via Google OAuth credentials.

Supports 28 operations across 6 categories:
- Messages: send, read, get_message, delete_message, trash_message, untrash_message, modify_message, reply, forward
- Drafts: create_draft, list_drafts, get_draft, update_draft, delete_draft, send_draft
- Labels: list_labels, create_label, get_label, update_label, delete_label
- Threads: list_threads, get_thread, trash_thread, untrash_thread, modify_thread, delete_thread
- Profile: get_profile
- Trigger: trigger (polls for new emails on a schedule via webhook)
"""

import time
import base64
import logging
from typing import Dict, Any, Optional, Union, Type, List, Literal, Annotated
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from email.mime.application import MIMEApplication
from urllib.parse import urlparse
from pydantic import BaseModel, ConfigDict, Discriminator, Field, field_validator
import httpx

import uuid as uuid_module

from nodes.core.base import WorkflowNode, NodeConfig
from utils.ssrf import guarded_async_client
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.schedule_registration import CronScheduleTriggerMixin
from nodes.oauth.google_oauth import is_token_expired, refresh_access_token
from nodes.core.dynamic_options import require_credential_token
from utils.email_body import ensure_html_body
from nodes.cron_trigger_node import (
    ScheduleConfig,
    schedule_to_cron,
    schedule_to_interval_ms,
)
from nodes.scopes.google_cloud import GMAIL_SCOPES

logger = logging.getLogger(__name__)

GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"

# The trigger's catch-up scan pages until it crosses the watermark. Use a large
# fixed page size (independent of any user "max results" cap) and bound the page
# count, so a burst of new mail is caught in one tick without an unbounded scan.
# Practical ceiling before truncation: _GMAIL_TRIGGER_PAGE_SIZE * _GMAIL_MAX_TRIGGER_PAGES.
_GMAIL_TRIGGER_PAGE_SIZE = 100
_GMAIL_MAX_TRIGGER_PAGES = 5


def _gmail_internal_ms(detail: Dict[str, Any]) -> int:
    """Arrival time (ms since epoch) of a fetched Gmail message; 0 if absent."""
    try:
        return int(detail.get("internal_date") or 0)
    except (TypeError, ValueError):
        return 0


# ============================================================================
# Gmail Node Credential Schema
# ============================================================================


class GmailOAuthCredential(BaseModel):
    """
    OAuth credential for Gmail access.
    Tokens are obtained via OAuth flow, not entered manually.
    """

    credential_type: Literal["google_gmail_oauth"] = Field(
        "google_gmail_oauth", json_schema_extra={"ui:hidden": True}
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
            "x-oauth-scopes": [
                "https://www.googleapis.com/auth/gmail.modify",
                "https://www.googleapis.com/auth/gmail.compose",
                "https://www.googleapis.com/auth/gmail.labels",
                "https://www.googleapis.com/auth/gmail.settings.basic",
            ],
        }
    )


# ============================================================================
# Gmail Node Configuration Models - Messages
# ============================================================================


def _normalize_recipient_list(v: Any) -> Any:
    """Comma-string → list (legacy), and drop entries that are None or
    empty/whitespace — an optional recipient whose expression resolved empty
    must be omitted, not sent to Gmail as an invalid header. A whole-value
    None means "unset" (the execution path cleans "" to None) → empty list.
    Non-string junk is kept for Pydantic to report as a type error."""
    if v is None:
        return []
    if isinstance(v, str):
        return [a.strip() for a in v.split(",") if a.strip()] if v.strip() else []
    if isinstance(v, list):
        out = []
        for a in v:
            if a is None:
                continue
            if isinstance(a, str):
                if a.strip():
                    out.append(a.strip())
            else:
                out.append(a)
        return out
    return v


class GmailSendConfig(BaseModel):
    """Configuration for sending an email"""

    operation: Literal["send_email_message"] = Field(
        "send_email_message",
        title="Send Email Message",
        description="Send an email",
        json_schema_extra={
            "ui:hidden": True,
            "const": "send_email_message",
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Send Email Message",
            "x-keywords": [
                "compose email",
                "email someone",
                "send mail",
                "write email",
                "shoot an email",
                "send new message",
            ],
        },
    )
    to: List[str] = Field(
        ...,
        min_length=1,
        title="To",
        description="Recipient email address(es)",
        json_schema_extra={"ui:widget": "list", "placeholder": "recipient@example.com"},
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
    cc: List[str] = Field(
        default_factory=list,
        title="CC",
        description="CC recipients",
        json_schema_extra={"ui:widget": "list", "placeholder": "cc@example.com"},
    )
    bcc: List[str] = Field(
        default_factory=list,
        title="BCC",
        description="BCC recipients",
        json_schema_extra={"ui:widget": "list", "placeholder": "bcc@example.com"},
    )
    inline_images: List[str] = Field(
        default_factory=list,
        title="Inline Images",
        description="Image URLs to embed directly in the email. Images are downloaded and attached, preventing URL expiration.",
        json_schema_extra={"ui:widget": "list", "placeholder": "{{node.image_url}}"},
    )
    attachments: List[str] = Field(
        default_factory=list,
        title="Attachments",
        description="Files to attach: workflow resource ids or URLs (max 10MB per file, 20MB total).",
        json_schema_extra={"ui:widget": "list", "placeholder": "{{node.resource_id}}"},
    )

    @field_validator("to", "cc", "bcc", mode="before")
    @classmethod
    def normalize_recipients(cls, v: Any) -> Any:
        """Accept comma-separated string for backward compatibility; drop
        empty/None entries (expression resolved to nothing)."""
        return _normalize_recipient_list(v)

    @field_validator("inline_images", "attachments", mode="before")
    @classmethod
    def filter_media_lists(cls, v: Any) -> list:
        if not isinstance(v, list):
            return []
        return [url for url in v if isinstance(url, str) and url.strip()]


class GmailReadConfig(BaseModel):
    """Configuration for reading emails from inbox"""

    operation: Literal["fetch_emails_from_inbox"] = Field(
        "fetch_emails_from_inbox",
        title="Fetch Emails from Inbox",
        description="Read emails from inbox",
        json_schema_extra={
            "ui:hidden": True,
            "const": "fetch_emails_from_inbox",
            "x-category": "Inbox",
            "x-is-trigger": False,
            "x-display-name": "Fetch Emails from Inbox",
            "x-keywords": [
                "check inbox",
                "read inbox",
                "unread emails",
                "search emails",
                "inbox messages",
                "scan mailbox",
            ],
        },
    )
    query: Optional[str] = Field(
        None,
        title="Search Query",
        description="Gmail search query (e.g., 'from:someone@example.com', 'is:unread', 'subject:hello')",
        json_schema_extra={"placeholder": "is:unread (optional)"},
    )
    max_results: int = Field(
        10,
        title="Max Results",
        description="Maximum number of emails to retrieve (1-500)",
        ge=1,
        le=500,
    )
    include_body: bool = Field(
        True, title="Include Body", description="Include email body content in results"
    )
    label_ids: Optional[str] = Field(
        None,
        title="Label IDs",
        description="Filter by label IDs (comma-separated, e.g., 'INBOX,UNREAD')",
        json_schema_extra={"placeholder": "INBOX,UNREAD (optional)"},
    )
    page_token: Optional[str] = Field(
        None,
        title="Page Token",
        description="Token for fetching the next page of results (from previous response)",
        json_schema_extra={"placeholder": "Leave empty for first page"},
    )


class GmailGetMessageConfig(BaseModel):
    """Configuration for getting a specific message"""

    operation: Literal["fetch_email_message"] = Field(
        "fetch_email_message",
        title="Fetch Email Message",
        description="Get a specific email by ID",
        json_schema_extra={
            "ui:hidden": True,
            "const": "fetch_email_message",
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Fetch Email Message",
            "x-keywords": [
                "open email",
                "read this email",
                "get message by id",
                "single message",
                "email contents",
                "view one message",
            ],
        },
    )
    message_id: str = Field(
        ...,
        title="Message ID",
        description="The ID of the message to retrieve",
        json_schema_extra={"placeholder": "Enter message ID..."},
    )
    format: str = Field(
        "full",
        title="Format",
        description="The format to return the message in",
        json_schema_extra={
            "enum": ["minimal", "full", "raw", "metadata"],
            "enumNames": ["Minimal", "Full", "Raw", "Metadata Only"],
        },
    )


class GmailGetAttachmentConfig(BaseModel):
    """Configuration for fetching a message attachment"""

    operation: Literal["fetch_email_attachment"] = Field(
        "fetch_email_attachment",
        title="Fetch Email Attachment",
        description="Download a message attachment and extract its content",
        json_schema_extra={
            "ui:hidden": True,
            "const": "fetch_email_attachment",
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Fetch Email Attachment",
            "x-keywords": [
                "attachment",
                "download attachment",
                "read pdf",
                "attached file",
                "invoice pdf",
                "document in email",
            ],
        },
    )
    message_id: str = Field(
        ...,
        title="Message ID",
        description="The ID of the message containing the attachment",
        json_schema_extra={"placeholder": "Enter message ID..."},
    )
    attachment_id: str = Field(
        "",
        title="Attachment ID",
        description="Attachment ID from the message's attachments list (or select by filename below)",
        json_schema_extra={"placeholder": "Enter attachment ID..."},
    )
    filename: str = Field(
        "",
        title="Filename",
        description="Select the attachment by filename instead of ID",
    )
    mode: str = Field(
        "extract_text",
        title="Mode",
        description="Extract readable text, or save the raw file as a workflow resource",
        json_schema_extra={
            "enum": ["extract_text", "save_as_resource"],
            "enumNames": ["Extract Text", "Save as Resource"],
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


class GmailDeleteMessageConfig(BaseModel):
    """Configuration for permanently deleting a message"""

    operation: Literal["permanently_delete_message"] = Field(
        "permanently_delete_message",
        title="Permanently Delete Message",
        description="Permanently delete a message (cannot be undone)",
        json_schema_extra={
            "ui:hidden": True,
            "const": "permanently_delete_message",
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Permanently Delete Message",
            "x-keywords": [
                "delete forever",
                "purge message",
                "hard delete email",
                "wipe message",
                "destroy email",
            ],
        },
    )
    message_id: str = Field(
        ...,
        title="Message ID",
        description="The ID of the message to delete permanently",
        json_schema_extra={"placeholder": "Enter message ID..."},
    )


class GmailTrashMessageConfig(BaseModel):
    """Configuration for moving a message to trash"""

    operation: Literal["move_message_to_trash"] = Field(
        "move_message_to_trash",
        title="Move Message to Trash",
        description="Move a message to trash",
        json_schema_extra={
            "ui:hidden": True,
            "const": "move_message_to_trash",
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Move Message to Trash",
            "x-keywords": [
                "trash email",
                "bin message",
                "discard email",
                "throw away message",
                "delete to trash",
            ],
        },
    )
    message_id: str = Field(
        ...,
        title="Message ID",
        description="The ID of the message to move to trash",
        json_schema_extra={"placeholder": "Enter message ID..."},
    )


class GmailUntrashMessageConfig(BaseModel):
    """Configuration for removing a message from trash"""

    operation: Literal["restore_message_from_trash"] = Field(
        "restore_message_from_trash",
        title="Restore Message from Trash",
        description="Remove a message from trash",
        json_schema_extra={
            "ui:hidden": True,
            "const": "restore_message_from_trash",
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Restore Message from Trash",
            "x-keywords": [
                "untrash email",
                "recover message",
                "restore email",
                "undelete message",
                "bring back email",
            ],
        },
    )
    message_id: str = Field(
        ...,
        title="Message ID",
        description="The ID of the message to restore from trash",
        json_schema_extra={"placeholder": "Enter message ID..."},
    )


class GmailModifyMessageConfig(BaseModel):
    """Configuration for modifying message labels"""

    operation: Literal["update_message_labels"] = Field(
        "update_message_labels",
        title="Update Message Labels",
        description="Add or remove labels from a message",
        json_schema_extra={
            "ui:hidden": True,
            "const": "update_message_labels",
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Update Message Labels",
            "x-keywords": [
                "label email",
                "tag message",
                "mark as read",
                "archive email",
                "star email",
                "apply label",
            ],
        },
    )
    message_id: str = Field(
        ...,
        title="Message ID",
        description="The ID of the message to modify",
        json_schema_extra={"placeholder": "Enter message ID..."},
    )
    add_label_ids: Optional[str] = Field(
        None,
        title="Add Labels",
        description="Label IDs to add (comma-separated, e.g., 'STARRED,IMPORTANT')",
        json_schema_extra={"placeholder": "STARRED,IMPORTANT"},
    )
    remove_label_ids: Optional[str] = Field(
        None,
        title="Remove Labels",
        description="Label IDs to remove (comma-separated, e.g., 'UNREAD,INBOX')",
        json_schema_extra={"placeholder": "UNREAD"},
    )


class GmailReplyConfig(BaseModel):
    """Configuration for replying to an email"""

    operation: Literal["reply_to_email_message"] = Field(
        "reply_to_email_message",
        title="Reply to Email Message",
        description="Reply to an email",
        json_schema_extra={
            "ui:hidden": True,
            "const": "reply_to_email_message",
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Reply to Email Message",
            "x-keywords": [
                "reply email",
                "respond to mail",
                "answer email",
                "send reply",
                "write back",
            ],
        },
    )
    message_id: str = Field(
        ...,
        title="Message ID",
        description="The ID of the message to reply to",
        json_schema_extra={"placeholder": "Enter message ID..."},
    )
    body: str = Field(
        ...,
        title="Reply Body",
        description="Reply body content (HTML supported)",
        json_schema_extra={"ui:widget": "textarea", "placeholder": "Enter reply..."},
    )
    reply_all: bool = Field(
        False,
        title="Reply All",
        description="Reply to all recipients instead of just the sender",
    )
    inline_images: List[str] = Field(
        default_factory=list,
        title="Inline Images",
        description="Image URLs to embed directly in the email. Images are downloaded and attached, preventing URL expiration.",
        json_schema_extra={"ui:widget": "list", "placeholder": "{{node.image_url}}"},
    )
    attachments: List[str] = Field(
        default_factory=list,
        title="Attachments",
        description="Files to attach: workflow resource ids or URLs (max 10MB per file, 20MB total).",
        json_schema_extra={"ui:widget": "list", "placeholder": "{{node.resource_id}}"},
    )

    @field_validator("inline_images", "attachments", mode="before")
    @classmethod
    def filter_media_lists(cls, v: Any) -> list:
        if not isinstance(v, list):
            return []
        return [url for url in v if isinstance(url, str) and url.strip()]


class GmailForwardConfig(BaseModel):
    """Configuration for forwarding an email"""

    operation: Literal["forward_email_message"] = Field(
        "forward_email_message",
        title="Forward Email Message",
        description="Forward an email",
        json_schema_extra={
            "ui:hidden": True,
            "const": "forward_email_message",
            "x-category": "Message",
            "x-is-trigger": False,
            "x-display-name": "Forward Email Message",
            "x-keywords": [
                "forward email",
                "send along",
                "pass on email",
                "fwd message",
                "forward to someone",
            ],
        },
    )
    message_id: str = Field(
        ...,
        title="Message ID",
        description="The ID of the message to forward",
        json_schema_extra={"placeholder": "Enter message ID..."},
    )
    to: List[str] = Field(
        ...,
        min_length=1,
        title="Forward To",
        description="Email address(es) to forward to",
        json_schema_extra={"ui:widget": "list", "placeholder": "recipient@example.com"},
    )

    @field_validator("to", mode="before")
    @classmethod
    def normalize_recipients(cls, v: Any) -> Any:
        return _normalize_recipient_list(v)

    additional_message: Optional[str] = Field(
        None,
        title="Additional Message",
        description="Optional message to include before forwarded content",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "Add a message (optional)...",
        },
    )
    inline_images: List[str] = Field(
        default_factory=list,
        title="Inline Images",
        description="Image URLs to embed directly in the email. Images are downloaded and attached, preventing URL expiration.",
        json_schema_extra={"ui:widget": "list", "placeholder": "{{node.image_url}}"},
    )
    attachments: List[str] = Field(
        default_factory=list,
        title="Attachments",
        description="Files to attach: workflow resource ids or URLs (max 10MB per file, 20MB total).",
        json_schema_extra={"ui:widget": "list", "placeholder": "{{node.resource_id}}"},
    )

    @field_validator("inline_images", "attachments", mode="before")
    @classmethod
    def filter_media_lists(cls, v: Any) -> list:
        if not isinstance(v, list):
            return []
        return [url for url in v if isinstance(url, str) and url.strip()]


# ============================================================================
# Gmail Node Configuration Models - Drafts
# ============================================================================


class GmailCreateDraftConfig(BaseModel):
    """Configuration for creating a draft"""

    operation: Literal["create_email_draft"] = Field(
        "create_email_draft",
        title="Create Email Draft",
        description="Create a draft email",
        json_schema_extra={
            "ui:hidden": True,
            "const": "create_email_draft",
            "x-category": "Draft",
            "x-is-trigger": False,
            "x-display-name": "Create Email Draft",
            "x-keywords": [
                "save draft",
                "draft email",
                "new draft",
                "compose draft",
                "start draft",
            ],
        },
    )
    to: List[str] = Field(
        ...,
        min_length=1,
        title="To",
        description="Recipient email address(es)",
        json_schema_extra={"ui:widget": "list", "placeholder": "recipient@example.com"},
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
    cc: List[str] = Field(
        default_factory=list,
        title="CC",
        description="CC recipients",
        json_schema_extra={"ui:widget": "list", "placeholder": "cc@example.com"},
    )
    bcc: List[str] = Field(
        default_factory=list,
        title="BCC",
        description="BCC recipients",
        json_schema_extra={"ui:widget": "list", "placeholder": "bcc@example.com"},
    )
    inline_images: List[str] = Field(
        default_factory=list,
        title="Inline Images",
        description="Image URLs to embed directly in the email. Images are downloaded and attached, preventing URL expiration.",
        json_schema_extra={"ui:widget": "list", "placeholder": "{{node.image_url}}"},
    )
    attachments: List[str] = Field(
        default_factory=list,
        title="Attachments",
        description="Files to attach: workflow resource ids or URLs (max 10MB per file, 20MB total).",
        json_schema_extra={"ui:widget": "list", "placeholder": "{{node.resource_id}}"},
    )

    @field_validator("to", "cc", "bcc", mode="before")
    @classmethod
    def normalize_recipients(cls, v: Any) -> Any:
        return _normalize_recipient_list(v)

    @field_validator("inline_images", "attachments", mode="before")
    @classmethod
    def filter_media_lists(cls, v: Any) -> list:
        if not isinstance(v, list):
            return []
        return [url for url in v if isinstance(url, str) and url.strip()]


class GmailListDraftsConfig(BaseModel):
    """Configuration for listing drafts"""

    operation: Literal["list_email_drafts"] = Field(
        "list_email_drafts",
        title="List Email Drafts",
        description="List all draft emails",
        json_schema_extra={
            "ui:hidden": True,
            "const": "list_email_drafts",
            "x-category": "Draft",
            "x-is-trigger": False,
            "x-display-name": "List Email Drafts",
            "x-keywords": [
                "show drafts",
                "all drafts",
                "my drafts",
                "unsent emails",
                "view drafts",
            ],
        },
    )
    max_results: int = Field(
        10,
        title="Max Results",
        description="Maximum number of drafts to retrieve (1-500)",
        ge=1,
        le=500,
    )
    query: Optional[str] = Field(
        None,
        title="Search Query",
        description="Optional search query to filter drafts",
        json_schema_extra={"placeholder": "subject:report (optional)"},
    )
    page_token: Optional[str] = Field(
        None,
        title="Page Token",
        description="Token for fetching the next page of results",
        json_schema_extra={"placeholder": "Leave empty for first page"},
    )


class GmailGetDraftConfig(BaseModel):
    """Configuration for getting a specific draft"""

    operation: Literal["fetch_email_draft"] = Field(
        "fetch_email_draft",
        title="Fetch Email Draft",
        description="Get a specific draft by ID",
        json_schema_extra={
            "ui:hidden": True,
            "const": "fetch_email_draft",
            "x-category": "Draft",
            "x-is-trigger": False,
            "x-display-name": "Fetch Email Draft",
            "x-keywords": [
                "open draft",
                "get one draft",
                "single draft",
                "draft contents",
                "view draft",
            ],
        },
    )
    draft_id: str = Field(
        ...,
        title="Draft ID",
        description="The ID of the draft to retrieve",
        json_schema_extra={"placeholder": "Enter draft ID..."},
    )


class GmailUpdateDraftConfig(BaseModel):
    """Configuration for updating a draft"""

    operation: Literal["update_email_draft"] = Field(
        "update_email_draft",
        title="Update Email Draft",
        description="Update an existing draft",
        json_schema_extra={
            "ui:hidden": True,
            "const": "update_email_draft",
            "x-category": "Draft",
            "x-is-trigger": False,
            "x-display-name": "Update Email Draft",
            "x-keywords": [
                "edit draft",
                "modify draft",
                "change draft",
                "revise draft",
                "rewrite draft",
            ],
        },
    )
    draft_id: str = Field(
        ...,
        title="Draft ID",
        description="The ID of the draft to update",
        json_schema_extra={"placeholder": "Enter draft ID..."},
    )
    to: str = Field(
        ...,
        title="To",
        description="Recipient email address(es)",
        json_schema_extra={"placeholder": "recipient@example.com"},
    )
    subject: str = Field(..., title="Subject", description="Email subject line")
    body: str = Field(
        ...,
        title="Body",
        description="Email body content (HTML supported)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    cc: Optional[str] = Field(None, title="CC")
    bcc: Optional[str] = Field(None, title="BCC")


class GmailDeleteDraftConfig(BaseModel):
    """Configuration for deleting a draft"""

    operation: Literal["delete_email_draft"] = Field(
        "delete_email_draft",
        title="Delete Email Draft",
        description="Delete a draft",
        json_schema_extra={
            "ui:hidden": True,
            "const": "delete_email_draft",
            "x-category": "Draft",
            "x-is-trigger": False,
            "x-display-name": "Delete Email Draft",
            "x-keywords": [
                "discard draft",
                "remove draft",
                "trash draft",
                "throw away draft",
            ],
        },
    )
    draft_id: str = Field(
        ...,
        title="Draft ID",
        description="The ID of the draft to delete",
        json_schema_extra={"placeholder": "Enter draft ID..."},
    )


class GmailSendDraftConfig(BaseModel):
    """Configuration for sending a draft"""

    operation: Literal["send_email_draft"] = Field(
        "send_email_draft",
        title="Send Email Draft",
        description="Send an existing draft",
        json_schema_extra={
            "ui:hidden": True,
            "const": "send_email_draft",
            "x-category": "Draft",
            "x-is-trigger": False,
            "x-display-name": "Send Email Draft",
            "x-keywords": [
                "send draft",
                "send saved draft",
                "dispatch draft",
                "mail the draft",
                "send unsent email",
            ],
        },
    )
    draft_id: str = Field(
        ...,
        title="Draft ID",
        description="The ID of the draft to send",
        json_schema_extra={"placeholder": "Enter draft ID..."},
    )


# ============================================================================
# Gmail Node Configuration Models - Labels
# ============================================================================


class GmailListLabelsConfig(BaseModel):
    """Configuration for listing all labels"""

    operation: Literal["list_email_labels"] = Field(
        "list_email_labels",
        title="List Email Labels",
        description="List all labels in the mailbox",
        json_schema_extra={
            "ui:hidden": True,
            "const": "list_email_labels",
            "x-category": "Label",
            "x-is-trigger": False,
            "x-display-name": "List Email Labels",
            "x-keywords": [
                "show labels",
                "all labels",
                "my labels",
                "list tags",
                "view folders",
            ],
        },
    )


class GmailCreateLabelConfig(BaseModel):
    """Configuration for creating a label"""

    operation: Literal["create_email_label"] = Field(
        "create_email_label",
        title="Create Email Label",
        description="Create a new label",
        json_schema_extra={
            "ui:hidden": True,
            "const": "create_email_label",
            "x-category": "Label",
            "x-is-trigger": False,
            "x-display-name": "Create Email Label",
            "x-keywords": ["new label", "make label", "add tag", "create folder"],
        },
    )
    name: str = Field(
        ...,
        title="Label Name",
        description="Name for the new label",
        json_schema_extra={"placeholder": "My Label"},
    )
    label_list_visibility: str = Field(
        "labelShow",
        title="List Visibility",
        description="Visibility in label list",
        json_schema_extra={
            "enum": ["labelShow", "labelShowIfUnread", "labelHide"],
            "enumNames": ["Show", "Show if Unread", "Hide"],
        },
    )
    message_list_visibility: str = Field(
        "show",
        title="Message Visibility",
        description="Visibility in message list",
        json_schema_extra={"enum": ["show", "hide"], "enumNames": ["Show", "Hide"]},
    )
    background_color: Optional[str] = Field(
        None,
        title="Background Color",
        description="Background color hex code (e.g., #4285f4)",
        json_schema_extra={"placeholder": "#4285f4"},
    )
    text_color: Optional[str] = Field(
        None,
        title="Text Color",
        description="Text color hex code (e.g., #ffffff)",
        json_schema_extra={"placeholder": "#ffffff"},
    )


class GmailGetLabelConfig(BaseModel):
    """Configuration for getting a label"""

    operation: Literal["fetch_email_label"] = Field(
        "fetch_email_label",
        title="Fetch Email Label",
        description="Get details of a specific label",
        json_schema_extra={
            "ui:hidden": True,
            "const": "fetch_email_label",
            "x-category": "Label",
            "x-is-trigger": False,
            "x-display-name": "Fetch Email Label",
            "x-keywords": [
                "open label",
                "get one label",
                "single label",
                "label details",
            ],
        },
    )
    label_id: str = Field(
        ...,
        title="Label ID",
        description="The ID of the label to retrieve",
        json_schema_extra={"placeholder": "Label_123 or INBOX"},
    )


class GmailUpdateLabelConfig(BaseModel):
    """Configuration for updating a label"""

    operation: Literal["update_email_label"] = Field(
        "update_email_label",
        title="Update Email Label",
        description="Update an existing label",
        json_schema_extra={
            "ui:hidden": True,
            "const": "update_email_label",
            "x-category": "Label",
            "x-is-trigger": False,
            "x-display-name": "Update Email Label",
            "x-keywords": ["rename label", "edit label", "modify tag", "recolor label"],
        },
    )
    label_id: str = Field(
        ...,
        title="Label ID",
        description="The ID of the label to update",
        json_schema_extra={"placeholder": "Label_123"},
    )
    name: Optional[str] = Field(
        None,
        title="New Name",
        description="New name for the label",
        json_schema_extra={"placeholder": "New Label Name"},
    )
    label_list_visibility: Optional[str] = Field(
        None,
        title="List Visibility",
        description="Visibility in label list",
        json_schema_extra={
            "enum": ["labelShow", "labelShowIfUnread", "labelHide"],
            "enumNames": ["Show", "Show if Unread", "Hide"],
        },
    )
    message_list_visibility: Optional[str] = Field(
        None,
        title="Message Visibility",
        description="Visibility in message list",
        json_schema_extra={"enum": ["show", "hide"], "enumNames": ["Show", "Hide"]},
    )
    background_color: Optional[str] = Field(
        None, title="Background Color", description="Background color hex code"
    )
    text_color: Optional[str] = Field(
        None, title="Text Color", description="Text color hex code"
    )


class GmailDeleteLabelConfig(BaseModel):
    """Configuration for deleting a label"""

    operation: Literal["delete_email_label"] = Field(
        "delete_email_label",
        title="Delete Email Label",
        description="Delete a label",
        json_schema_extra={
            "ui:hidden": True,
            "const": "delete_email_label",
            "x-category": "Label",
            "x-is-trigger": False,
            "x-display-name": "Delete Email Label",
            "x-keywords": ["remove label", "delete tag", "drop label", "trash label"],
        },
    )
    label_id: str = Field(
        ...,
        title="Label ID",
        description="The ID of the label to delete",
        json_schema_extra={"placeholder": "Label_123"},
    )


# ============================================================================
# Gmail Node Configuration Models - Threads
# ============================================================================


class GmailListThreadsConfig(BaseModel):
    """Configuration for listing threads"""

    operation: Literal["list_email_threads"] = Field(
        "list_email_threads",
        title="List Email Threads",
        description="List email threads",
        json_schema_extra={
            "ui:hidden": True,
            "const": "list_email_threads",
            "x-category": "Thread",
            "x-is-trigger": False,
            "x-display-name": "List Email Threads",
            "x-keywords": [
                "show threads",
                "all conversations",
                "email threads",
                "list conversations",
            ],
        },
    )
    query: Optional[str] = Field(
        None,
        title="Search Query",
        description="Gmail search query to filter threads",
        json_schema_extra={"placeholder": "is:unread (optional)"},
    )
    max_results: int = Field(
        10,
        title="Max Results",
        description="Maximum number of threads to retrieve (1-500)",
        ge=1,
        le=500,
    )
    label_ids: Optional[str] = Field(
        None,
        title="Label IDs",
        description="Filter by label IDs (comma-separated)",
        json_schema_extra={"placeholder": "INBOX,UNREAD"},
    )
    page_token: Optional[str] = Field(
        None,
        title="Page Token",
        description="Token for fetching the next page of results",
        json_schema_extra={"placeholder": "Leave empty for first page"},
    )


class GmailGetThreadConfig(BaseModel):
    """Configuration for getting a specific thread"""

    operation: Literal["fetch_email_thread"] = Field(
        "fetch_email_thread",
        title="Fetch Email Thread",
        description="Get a specific email thread",
        json_schema_extra={
            "ui:hidden": True,
            "const": "fetch_email_thread",
            "x-category": "Thread",
            "x-is-trigger": False,
            "x-display-name": "Fetch Email Thread",
            "x-keywords": [
                "open thread",
                "get one thread",
                "single conversation",
                "thread messages",
                "view conversation",
            ],
        },
    )
    thread_id: str = Field(
        ...,
        title="Thread ID",
        description="The ID of the thread to retrieve",
        json_schema_extra={"placeholder": "Enter thread ID..."},
    )
    format: str = Field(
        "full",
        title="Format",
        description="The format to return messages in",
        json_schema_extra={
            "enum": ["minimal", "full", "metadata"],
            "enumNames": ["Minimal", "Full", "Metadata Only"],
        },
    )


class GmailTrashThreadConfig(BaseModel):
    """Configuration for moving a thread to trash"""

    operation: Literal["move_thread_to_trash"] = Field(
        "move_thread_to_trash",
        title="Move Thread to Trash",
        description="Move an entire thread to trash",
        json_schema_extra={
            "ui:hidden": True,
            "const": "move_thread_to_trash",
            "x-category": "Thread",
            "x-is-trigger": False,
            "x-display-name": "Move Thread to Trash",
            "x-keywords": [
                "trash thread",
                "bin conversation",
                "discard thread",
                "delete conversation",
            ],
        },
    )
    thread_id: str = Field(
        ...,
        title="Thread ID",
        description="The ID of the thread to trash",
        json_schema_extra={"placeholder": "Enter thread ID..."},
    )


class GmailUntrashThreadConfig(BaseModel):
    """Configuration for restoring a thread from trash"""

    operation: Literal["restore_thread_from_trash"] = Field(
        "restore_thread_from_trash",
        title="Restore Thread from Trash",
        description="Restore a thread from trash",
        json_schema_extra={
            "ui:hidden": True,
            "const": "restore_thread_from_trash",
            "x-category": "Thread",
            "x-is-trigger": False,
            "x-display-name": "Restore Thread from Trash",
            "x-keywords": [
                "untrash thread",
                "recover conversation",
                "restore thread",
                "undelete conversation",
            ],
        },
    )
    thread_id: str = Field(
        ...,
        title="Thread ID",
        description="The ID of the thread to restore",
        json_schema_extra={"placeholder": "Enter thread ID..."},
    )


class GmailModifyThreadConfig(BaseModel):
    """Configuration for modifying thread labels"""

    operation: Literal["update_thread_labels"] = Field(
        "update_thread_labels",
        title="Update Thread Labels",
        description="Add or remove labels from a thread",
        json_schema_extra={
            "ui:hidden": True,
            "const": "update_thread_labels",
            "x-category": "Thread",
            "x-is-trigger": False,
            "x-display-name": "Update Thread Labels",
            "x-keywords": [
                "label thread",
                "tag conversation",
                "archive thread",
                "mark thread read",
                "apply label to thread",
            ],
        },
    )
    thread_id: str = Field(
        ...,
        title="Thread ID",
        description="The ID of the thread to modify",
        json_schema_extra={"placeholder": "Enter thread ID..."},
    )
    add_label_ids: Optional[str] = Field(
        None,
        title="Add Labels",
        description="Label IDs to add (comma-separated)",
        json_schema_extra={"placeholder": "STARRED,IMPORTANT"},
    )
    remove_label_ids: Optional[str] = Field(
        None,
        title="Remove Labels",
        description="Label IDs to remove (comma-separated)",
        json_schema_extra={"placeholder": "UNREAD"},
    )


class GmailDeleteThreadConfig(BaseModel):
    """Configuration for permanently deleting a thread"""

    operation: Literal["permanently_delete_thread"] = Field(
        "permanently_delete_thread",
        title="Permanently Delete Thread",
        description="Permanently delete a thread (cannot be undone)",
        json_schema_extra={
            "ui:hidden": True,
            "const": "permanently_delete_thread",
            "x-category": "Thread",
            "x-is-trigger": False,
            "x-display-name": "Permanently Delete Thread",
            "x-keywords": [
                "delete thread forever",
                "purge conversation",
                "hard delete thread",
                "wipe conversation",
            ],
        },
    )
    thread_id: str = Field(
        ...,
        title="Thread ID",
        description="The ID of the thread to delete permanently",
        json_schema_extra={"placeholder": "Enter thread ID..."},
    )


# ============================================================================
# Gmail Node Configuration Models - Profile
# ============================================================================


class GmailGetProfileConfig(BaseModel):
    """Configuration for getting user profile"""

    operation: Literal["fetch_user_profile"] = Field(
        "fetch_user_profile",
        title="Fetch User Profile",
        description="Get the current user's Gmail profile",
        json_schema_extra={
            "ui:hidden": True,
            "const": "fetch_user_profile",
            "x-category": "Profile",
            "x-is-trigger": False,
            "x-display-name": "Fetch User Profile",
            "x-keywords": [
                "my account",
                "mailbox info",
                "email address",
                "account details",
                "whoami",
            ],
        },
    )


# ============================================================================
# Gmail Node Configuration Models - Trigger
# ============================================================================


class GmailTriggerListenConfig(BaseModel):
    """Configuration for the Gmail trigger operation (polls for new emails on a schedule)."""

    operation: Literal["poll_for_new_emails"] = Field(
        "poll_for_new_emails",
        title="Poll for New Emails",
        description="Trigger workflow on new emails",
        json_schema_extra={
            "ui:hidden": True,
            "const": "poll_for_new_emails",
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "Poll for New Emails",
            "x-keywords": [
                "when new email",
                "on email received",
                "watch inbox",
                "new mail arrives",
                "incoming email",
                "email trigger",
            ],
        },
    )
    query: str = Field(
        "",
        title="Search Query",
        description=(
            "Optional Gmail search to narrow which new emails trigger the "
            "workflow (e.g. 'from:boss@company.com', 'subject:urgent', "
            "'is:unread'). Leave empty to fire on every new inbox email, "
            "including replies. New emails are detected by arrival time, so no "
            "filter is needed to avoid re-triggering on old mail."
        ),
        json_schema_extra={"placeholder": "from:boss@company.com"},
    )
    schedule: Optional[ScheduleConfig] = Field(
        default=ScheduleConfig(frequency="minutes", interval=5),
        title="Check Frequency",
        description="How often to check for new emails",
        json_schema_extra={
            "ui:widget": "schedule",
            "x-exclude-frequencies": ["seconds"],
        },
    )
    # Operational fields with sensible defaults (hidden from config UI)
    # Deprecated: the trigger no longer caps emitted emails (it fires for every
    # new arrival). The catch-up scan uses a fixed internal page size instead.
    # Kept for backward compatibility with saved configs; not rendered or read.
    max_results: int = Field(
        10,
        title="Max Emails",
        description="Deprecated — the trigger fires for every new email; this is no longer used.",
        ge=1,
        le=500,
        json_schema_extra={"ui:hidden": True},
    )
    mark_as_read: str = Field(
        "false",
        title="Mark as Read",
        description=(
            "Optionally mark triggered emails as read. Dedup no longer depends "
            "on this — new emails are tracked by arrival time — so leave it off "
            "to avoid mutating the mailbox."
        ),
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    label_ids: Optional[str] = Field(
        None,
        title="Label IDs",
        description="Comma-separated label IDs to filter (e.g., 'INBOX,IMPORTANT')",
        json_schema_extra={"ui:hidden": True},
    )
    include_body: str = Field(
        "true",
        title="Include Body",
        description="Whether to include the full email body",
        json_schema_extra={"ui:hidden": True},
    )
    # Hidden internal fields for webhook/schedule management
    webhook_id: Optional[str] = Field(
        default=None,
        json_schema_extra={"ui:hidden": True},
    )
    webhook_url: Optional[str] = Field(
        default=None,
        json_schema_extra={"ui:hidden": True, "ui:loadValue": True},
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
    last_run: Optional[str] = Field(
        default=None,
        json_schema_extra={"ui:widget": "readonly", "ui:hidden": True},
    )
    is_active: Optional[bool] = Field(
        default=True,
        json_schema_extra={"ui:hidden": True},
    )


# ============================================================================
# Discriminated Union of All Config Types
# ============================================================================

GmailConfig = Annotated[
    Union[
        # Messages
        GmailSendConfig,
        GmailReadConfig,
        GmailGetMessageConfig,
        GmailGetAttachmentConfig,
        GmailDeleteMessageConfig,
        GmailTrashMessageConfig,
        GmailUntrashMessageConfig,
        GmailModifyMessageConfig,
        GmailReplyConfig,
        GmailForwardConfig,
        # Drafts
        GmailCreateDraftConfig,
        GmailListDraftsConfig,
        GmailGetDraftConfig,
        GmailUpdateDraftConfig,
        GmailDeleteDraftConfig,
        GmailSendDraftConfig,
        # Labels
        GmailListLabelsConfig,
        GmailCreateLabelConfig,
        GmailGetLabelConfig,
        GmailUpdateLabelConfig,
        GmailDeleteLabelConfig,
        # Threads
        GmailListThreadsConfig,
        GmailGetThreadConfig,
        GmailTrashThreadConfig,
        GmailUntrashThreadConfig,
        GmailModifyThreadConfig,
        GmailDeleteThreadConfig,
        # Profile
        GmailGetProfileConfig,
        # Trigger
        GmailTriggerListenConfig,
    ],
    Discriminator("operation"),
]


class GmailNodeConfig(NodeConfig[GmailConfig, GmailOAuthCredential]):
    """Full configuration for Gmail node including credentials"""

    pass


# ============================================================================
# Gmail Node Implementation
# ============================================================================


class GmailNode(CronScheduleTriggerMixin, WorkflowNode):
    """
    Gmail workflow node for full Gmail API access.
    Supports 27 operations across messages, drafts, labels, threads, and profile.
    """

    schedule_trigger_operations = ("poll_for_new_emails",)
    schedule_source = "gmail_trigger"

    edit_examples = [
        "Send meeting notes to the team with project status and next steps",
        "Read all unread emails from managers and create a summary report",
        "Create a draft reply with template for customer inquiries from support",
        "Delete spam emails and move important client messages to VIP label",
        "Forward the invoice from billing@vendor.com to accounting team",
        "Get email threads from the Contracts label and extract all attachments",
        'Create a new label "Q2 Reviews" and organize employee feedback emails',
    ]

    @classmethod
    def resolve_trigger_payload(
        cls, payload: Dict[str, Any], config: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Gmail trigger is poll-based: the webhook is a wake-up signal, not data.
        Return None so execute() runs and actually polls the Gmail API."""
        if config.get("operation") == "poll_for_new_emails":
            return None
        return payload

    scope_registry = GMAIL_SCOPES

    # Recent senders, NOT labels: a Gmail label list is INBOX/SENT/SPAM/CATEGORY_*
    # for every account on earth, so it proves nothing. Who has written to you
    # lately is unmistakably your own inbox. Senders rather than subjects keeps
    # the content off a screen someone may be sharing while setting this up.
    connection_evidence = ConnectionEvidence(
        operation="fetch_emails_from_inbox",
        # Headers only, five rows: bodies are slow enough to blow the evidence
        # timeout and are none of this probe's business.
        operation_arguments={"max_results": 8, "include_body": False},
        noun="recent senders",
        label_keys=("from", "sender", "from_email"),
        identity_operation="fetch_user_profile",
    )

    @classmethod
    def get_config_model(cls) -> Optional[Union[Type, type]]:
        """Get Pydantic config model for Gmail node"""
        return GmailNodeConfig

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
        Load dynamic options for fields.

        Currently supports loading labels for label selection fields.
        """
        logger.info(f"[GmailNode] load_field_options called: field={field_name}")

        if field_name in ["label_ids", "add_label_ids", "remove_label_ids"]:
            return await cls._list_label_options(credential_data, search=search)

        return {"options": [], "next_page_token": None}

    # load_field_value (webhook + schedule registration) is inherited from
    # CronScheduleTriggerMixin — it converges through reconcile_node.

    @classmethod
    async def _list_label_options(
        cls, credential_data: Dict[str, Any], search: Optional[str] = None
    ) -> Dict[str, Any]:
        """List labels as dropdown options."""
        access_token = require_credential_token(
            credential_data.get("access_token"),
            "Connect a Gmail account to load labels",
        )

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{GMAIL_API_BASE}/labels",
                    headers={"Authorization": f"Bearer {access_token}"},
                )

                if response.status_code != 200:
                    raise ValueError(
                        f"Gmail API error ({response.status_code}): {response.text}"
                    )

                data = response.json()
                labels = data.get("labels", [])

                options = [
                    {"value": label["id"], "label": label["name"]} for label in labels
                ]

                return {"options": options, "next_page_token": None}
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"[GmailNode] Error listing labels: {e}")
            raise ValueError(f"Failed to load Gmail label options: {e}") from e

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute Gmail operation."""
        logger.info(f"[GmailNode] Executing node {self.node_id}")

        node_config = self.config
        if not node_config:
            raise ValueError(f"[GmailNode] Configuration is required")

        if not isinstance(node_config, GmailNodeConfig):
            raise ValueError(f"[GmailNode] Invalid config type: {type(node_config)}")

        config = node_config.config
        credentials = node_config.credentials

        if not credentials:
            raise ValueError("[GmailNode] Gmail credentials are required")

        access_token = await self._ensure_fresh_token(credentials)

        # Route to appropriate handler based on operation
        operation = config.operation

        # Message operations
        if operation == "send_email_message":
            output = await self._send_email(
                config, access_token, credentials.email, inputs
            )
        elif operation == "fetch_emails_from_inbox":
            output = await self._read_emails(config, access_token)
        elif operation == "fetch_email_message":
            output = await self._get_message(config, access_token)
        elif operation == "fetch_email_attachment":
            output = await self._get_attachment(config, access_token)
        elif operation == "permanently_delete_message":
            output = await self._delete_message(config, access_token)
        elif operation == "move_message_to_trash":
            output = await self._trash_message(config, access_token)
        elif operation == "restore_message_from_trash":
            output = await self._untrash_message(config, access_token)
        elif operation == "update_message_labels":
            output = await self._modify_message(config, access_token)
        elif operation == "reply_to_email_message":
            output = await self._reply_to_message(
                config, access_token, credentials.email
            )
        elif operation == "forward_email_message":
            output = await self._forward_message(
                config, access_token, credentials.email
            )
        # Draft operations
        elif operation == "create_email_draft":
            output = await self._create_draft(config, access_token, credentials.email)
        elif operation == "list_email_drafts":
            output = await self._list_drafts(config, access_token)
        elif operation == "fetch_email_draft":
            output = await self._get_draft(config, access_token)
        elif operation == "update_email_draft":
            output = await self._update_draft(config, access_token, credentials.email)
        elif operation == "delete_email_draft":
            output = await self._delete_draft(config, access_token)
        elif operation == "send_email_draft":
            output = await self._send_draft(config, access_token)
        # Label operations
        elif operation == "list_email_labels":
            output = await self._list_labels(access_token)
        elif operation == "create_email_label":
            output = await self._create_label(config, access_token)
        elif operation == "fetch_email_label":
            output = await self._get_label(config, access_token)
        elif operation == "update_email_label":
            output = await self._update_label(config, access_token)
        elif operation == "delete_email_label":
            output = await self._delete_label(config, access_token)
        # Thread operations
        elif operation == "list_email_threads":
            output = await self._list_threads(config, access_token)
        elif operation == "fetch_email_thread":
            output = await self._get_thread(config, access_token)
        elif operation == "move_thread_to_trash":
            output = await self._trash_thread(config, access_token)
        elif operation == "restore_thread_from_trash":
            output = await self._untrash_thread(config, access_token)
        elif operation == "update_thread_labels":
            output = await self._modify_thread(config, access_token)
        elif operation == "permanently_delete_thread":
            output = await self._delete_thread(config, access_token)
        # Profile
        elif operation == "fetch_user_profile":
            output = await self._get_profile(access_token)
        # Trigger
        elif operation == "poll_for_new_emails":
            output = await self._trigger_emails(config, access_token)
        else:
            raise ValueError(f"Unknown operation: {operation}")

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

    async def _ensure_fresh_token(self, credentials: GmailOAuthCredential) -> str:
        """Return a valid Gmail access token, refreshing + persisting if expired."""
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

    # ========================================================================
    # Message Operations
    # ========================================================================

    @staticmethod
    def _join_recipients(recipients: List[str]) -> str:
        """Join a list of email addresses into a comma-separated header string."""
        return ", ".join(recipients)

    @staticmethod
    def _validate_recipients(**fields: List[str]) -> None:
        """Sanity-check every recipient across all fields BEFORE calling the
        API, reporting ALL bad entries in one error. Gmail rejects headers
        serially (Invalid To, then Cc, then Bcc) — which cost a user three
        separate test cycles (2026-07-05)."""
        bad: List[str] = []
        for field_name, entries in fields.items():
            for entry in entries or []:
                s = str(entry).strip()
                # Accept "Name <addr@domain>" or bare "addr@domain".
                addr = s.rsplit("<", 1)[-1].rstrip(">").strip()
                local, sep, domain = addr.partition("@")
                if "{{" in s or not (sep and local and domain):
                    bad.append(f"{field_name}: {entry!r}")
        if bad:
            raise ValueError(
                "Invalid recipient address(es) — " + "; ".join(bad) +
                ". Each entry must be (or resolve to) an email address."
            )

    @staticmethod
    def _extract_r2_key(url: str) -> Optional[str]:
        """Extract R2 object key from a presigned R2 URL, or return None."""
        parsed = urlparse(url)
        if ".r2.cloudflarestorage.com" not in (parsed.hostname or ""):
            return None
        # Path is /<bucket>/<key...> — strip leading slash and bucket name
        parts = parsed.path.lstrip("/").split("/", 1)
        return parts[1] if len(parts) > 1 else None

    async def _fetch_image(self, url: str) -> tuple[bytes, str]:
        """Fetch image bytes from a URL. Uses direct R2 download for R2 URLs."""
        from utils.r2_cloudflare import download_from_r2
        import asyncio

        r2_key = self._extract_r2_key(url)
        if r2_key:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None, download_from_r2, "workflow-resources", r2_key
            )

        async with guarded_async_client(timeout=30) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "image/png")
            return resp.content, content_type

    async def _build_mime_message(
        self,
        body: str,
        inline_images: List[str],
        attachments: Optional[List[str]] = None,
    ) -> MIMEMultipart:
        """Build a MIME message with optional CID-embedded inline images and
        file attachments (resource ids / URLs)."""
        image_parts: list[MIMEImage] = []
        for url in inline_images:
            if not url or not url.strip():
                continue
            try:
                image_bytes, content_type = await self._fetch_image(url)
                cid = uuid_module.uuid4().hex
                # Replace URL only in src="" attributes, preserving it in HTML comments
                import re

                body = re.sub(
                    r'src="' + re.escape(url) + r'"', f'src="cid:{cid}"', body
                )
                # Determine subtype from content_type (e.g. "image/png" -> "png")
                subtype = content_type.split("/")[-1].split(";")[0].strip()
                img_part = MIMEImage(image_bytes, _subtype=subtype)
                img_part.add_header("Content-ID", f"<{cid}>")
                img_part.add_header("Content-Disposition", "inline")
                image_parts.append(img_part)
            except Exception as e:
                logger.warning(f"[GmailNode] Failed to fetch inline image {url}: {e}")

        if image_parts:
            # Build multipart/related with alternative + inline images
            content = MIMEMultipart("related")
            alternative = MIMEMultipart("alternative")
            alternative.attach(MIMEText(body, "html"))
            content.attach(alternative)
            for img_part in image_parts:
                content.attach(img_part)
        else:
            content = MIMEMultipart("alternative")
            content.attach(MIMEText(body, "html"))

        attachment_parts: list[MIMEApplication] = []
        if attachments:
            from nodes.core.media_resolver import resolve_attachments

            for media in await resolve_attachments(attachments):
                subtype = (
                    media.mime_type.split("/")[-1]
                    if media.mime_type.startswith("application/")
                    else "octet-stream"
                )
                part = MIMEApplication(media.data, _subtype=subtype)
                part.add_header(
                    "Content-Disposition", "attachment", filename=media.filename
                )
                attachment_parts.append(part)
        if not attachment_parts:
            return content

        mixed = MIMEMultipart("mixed")
        mixed.attach(content)
        for part in attachment_parts:
            mixed.attach(part)
        return mixed

    async def _send_email(
        self,
        config: GmailSendConfig,
        access_token: str,
        from_email: str,
        inputs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Send an email via Gmail API."""
        logger.info(f"[GmailNode] Sending email to {config.to}")

        body = await self._brand_email_body(
            ensure_html_body(self._resolve_template(config.body, inputs))
        )
        subject = self._resolve_template(config.subject, inputs)

        self._validate_recipients(to=config.to, cc=config.cc, bcc=config.bcc)
        message = await self._build_mime_message(
            body, config.inline_images, config.attachments
        )
        message["To"] = self._join_recipients(config.to)
        message["From"] = from_email
        message["Subject"] = subject

        if config.cc:
            message["Cc"] = self._join_recipients(config.cc)
        if config.bcc:
            message["Bcc"] = self._join_recipients(config.bcc)

        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{GMAIL_API_BASE}/messages/send",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={"raw": raw_message},
            )

            if response.status_code != 200:
                error_msg = (
                    response.json().get("error", {}).get("message", response.text)
                )
                raise ValueError(f"Gmail API error: {error_msg}")

            data = response.json()
            return {
                "type": "gmail",
                "operation": "send_email_message",
                "message_id": data.get("id"),
                "thread_id": data.get("threadId"),
                "to": config.to,
                "subject": subject,
                "timestamp": time.time(),
                "status": "success",
            }

    async def _read_emails(
        self, config: GmailReadConfig, access_token: str
    ) -> Dict[str, Any]:
        """Read emails from Gmail inbox with pagination support."""
        logger.info(f"[GmailNode] Reading emails with query: {config.query}")

        params = {"maxResults": config.max_results}
        if config.query:
            params["q"] = config.query
        if config.label_ids:
            params["labelIds"] = [l.strip() for l in config.label_ids.split(",")]
        if config.page_token:
            params["pageToken"] = config.page_token

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{GMAIL_API_BASE}/messages",
                headers={"Authorization": f"Bearer {access_token}"},
                params=params,
            )

            if response.status_code != 200:
                error_msg = (
                    response.json().get("error", {}).get("message", response.text)
                )
                raise ValueError(f"Gmail API error: {error_msg}")

            data = response.json()
            message_refs = data.get("messages", [])
            next_page_token = data.get("nextPageToken")

            emails = []
            for msg_ref in message_refs:
                msg_detail = await self._fetch_message_detail(
                    client, access_token, msg_ref["id"], config.include_body
                )
                emails.append(msg_detail)

            return {
                "type": "gmail",
                "operation": "fetch_emails_from_inbox",
                "query": config.query,
                "email_count": len(emails),
                "emails": emails,
                "next_page_token": next_page_token,
                "has_more": next_page_token is not None,
                "timestamp": time.time(),
                "status": "success",
            }

    async def _get_message(
        self, config: GmailGetMessageConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get a specific message by ID."""
        logger.info(f"[GmailNode] Getting message {config.message_id}")

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{GMAIL_API_BASE}/messages/{config.message_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"format": config.format},
            )

            if response.status_code != 200:
                error_msg = (
                    response.json().get("error", {}).get("message", response.text)
                )
                raise ValueError(f"Gmail API error: {error_msg}")

            data = response.json()

            # Parse message data
            result = {
                "type": "gmail",
                "operation": "fetch_email_message",
                "message_id": data.get("id"),
                "thread_id": data.get("threadId"),
                "labels": data.get("labelIds", []),
                "snippet": data.get("snippet"),
                "timestamp": time.time(),
                "status": "success",
            }

            # Extract headers if available
            headers = {}
            for header in data.get("payload", {}).get("headers", []):
                name = header.get("name", "").lower()
                if name in ["from", "to", "subject", "date", "cc", "bcc"]:
                    headers[name] = header.get("value", "")

            result["headers"] = headers

            # Extract body if full format
            if config.format == "full":
                payload = data.get("payload", {})
                result["body"] = self._extract_body(payload)
                attachments = self._extract_attachment_meta(payload)
                if attachments:
                    # Natural surfacing: small text-layer documents inline their
                    # extracted text so agents read them without another call.
                    # Free CPU path only — AI OCR stays behind the explicit
                    # fetch_email_attachment op (where it is gated + billed).
                    from utils.content_extraction import inline_enrich_attachments

                    async def fetch_bytes(rec: Dict[str, Any]) -> bytes:
                        return await self._fetch_attachment_bytes(
                            client, access_token, config.message_id, rec["attachment_id"]
                        )

                    result["attachments"] = await inline_enrich_attachments(
                        attachments, fetch_bytes
                    )

            return result

    async def _get_attachment(
        self, config: GmailGetAttachmentConfig, access_token: str
    ) -> Dict[str, Any]:
        """Download one attachment; extract its text or save it as a resource."""
        from utils.content_extraction import BillingContext, extract_content

        if not config.attachment_id and not config.filename:
            raise ValueError("Provide attachment_id or filename to select the attachment.")

        async with httpx.AsyncClient() as client:
            # Re-read the message for the authoritative part list — the
            # attachments.get endpoint returns bytes with no filename/mime.
            response = await client.get(
                f"{GMAIL_API_BASE}/messages/{config.message_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"format": "full"},
            )
            if response.status_code != 200:
                error_msg = response.json().get("error", {}).get("message", response.text)
                raise ValueError(f"Gmail API error: {error_msg}")

            candidates = self._extract_attachment_meta(response.json().get("payload", {}))
            target = next(
                (
                    a for a in candidates
                    if (config.attachment_id and a["attachment_id"] == config.attachment_id)
                    or (not config.attachment_id and a["filename"] == config.filename)
                ),
                None,
            )
            if target is None:
                available = ", ".join(a["filename"] for a in candidates) or "none"
                raise ValueError(
                    f"No matching attachment on message {config.message_id}. Available: {available}"
                )

            data = await self._fetch_attachment_bytes(
                client, access_token, config.message_id, target["attachment_id"]
            )

        result = {
            "type": "gmail",
            "operation": "fetch_email_attachment",
            "message_id": config.message_id,
            "filename": target["filename"],
            "mime_type": target["mime_type"],
            "size_bytes": len(data),
            "timestamp": time.time(),
            "status": "success",
        }

        if config.mode == "save_as_resource":
            from utils.resource_store import create_resource_from_bytes

            result["resource"] = await create_resource_from_bytes(
                user_id=self.user_id,
                workflow_id=str(self.workflow_id),
                node_id=self.node_id,
                organization_id=self.organization_id,
                body=data,
                content_type=target["mime_type"] or "application/octet-stream",
                filename=target["filename"],
                metadata={"source": "gmail_attachment", "message_id": config.message_id},
            )
            return result

        content = await extract_content(
            data,
            mime_type=target["mime_type"],
            filename=target["filename"],
            allow_ai=config.allow_ai_ocr == "true",
            billing=BillingContext(
                user_id=self.user_id,
                organization_id=self.organization_id,
                workflow_id=str(self.workflow_id) if self.workflow_id else None,
                node_id=self.node_id,
                sio=self.sio,
                sid=self.sid,
            ),
        )
        result.update({
            "text": content.text,
            "extraction_method": content.method,
            "pages": content.pages,
        })
        if content.cost_charged is not None:
            result["ocr_pages_billed"] = content.pages
        return result

    async def _delete_message(
        self, config: GmailDeleteMessageConfig, access_token: str
    ) -> Dict[str, Any]:
        """Permanently delete a message."""
        logger.info(f"[GmailNode] Deleting message {config.message_id}")

        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{GMAIL_API_BASE}/messages/{config.message_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 204:
                error_msg = (
                    response.json().get("error", {}).get("message", response.text)
                    if response.text
                    else "Unknown error"
                )
                raise ValueError(f"Gmail API error: {error_msg}")

            return {
                "type": "gmail",
                "operation": "permanently_delete_message",
                "message_id": config.message_id,
                "timestamp": time.time(),
                "status": "success",
            }

    async def _trash_message(
        self, config: GmailTrashMessageConfig, access_token: str
    ) -> Dict[str, Any]:
        """Move a message to trash."""
        logger.info(f"[GmailNode] Trashing message {config.message_id}")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{GMAIL_API_BASE}/messages/{config.message_id}/trash",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                error_msg = (
                    response.json().get("error", {}).get("message", response.text)
                )
                raise ValueError(f"Gmail API error: {error_msg}")

            data = response.json()
            return {
                "type": "gmail",
                "operation": "move_message_to_trash",
                "message_id": data.get("id"),
                "labels": data.get("labelIds", []),
                "timestamp": time.time(),
                "status": "success",
            }

    async def _untrash_message(
        self, config: GmailUntrashMessageConfig, access_token: str
    ) -> Dict[str, Any]:
        """Remove a message from trash."""
        logger.info(f"[GmailNode] Untrashing message {config.message_id}")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{GMAIL_API_BASE}/messages/{config.message_id}/untrash",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                error_msg = (
                    response.json().get("error", {}).get("message", response.text)
                )
                raise ValueError(f"Gmail API error: {error_msg}")

            data = response.json()
            return {
                "type": "gmail",
                "operation": "restore_message_from_trash",
                "message_id": data.get("id"),
                "labels": data.get("labelIds", []),
                "timestamp": time.time(),
                "status": "success",
            }

    async def _modify_message(
        self, config: GmailModifyMessageConfig, access_token: str
    ) -> Dict[str, Any]:
        """Modify labels on a message."""
        logger.info(f"[GmailNode] Modifying message {config.message_id}")

        body = {}
        if config.add_label_ids:
            body["addLabelIds"] = [l.strip() for l in config.add_label_ids.split(",")]
        if config.remove_label_ids:
            body["removeLabelIds"] = [
                l.strip() for l in config.remove_label_ids.split(",")
            ]

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{GMAIL_API_BASE}/messages/{config.message_id}/modify",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=body,
            )

            if response.status_code != 200:
                error_msg = (
                    response.json().get("error", {}).get("message", response.text)
                )
                raise ValueError(f"Gmail API error: {error_msg}")

            data = response.json()
            return {
                "type": "gmail",
                "operation": "update_message_labels",
                "message_id": data.get("id"),
                "labels": data.get("labelIds", []),
                "timestamp": time.time(),
                "status": "success",
            }

    async def _reply_to_message(
        self, config: GmailReplyConfig, access_token: str, from_email: str
    ) -> Dict[str, Any]:
        """Reply to a message."""
        logger.info(f"[GmailNode] Replying to message {config.message_id}")

        # First get the original message to extract headers
        async with httpx.AsyncClient() as client:
            orig_response = await client.get(
                f"{GMAIL_API_BASE}/messages/{config.message_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                params={
                    "format": "metadata",
                    "metadataHeaders": ["From", "To", "Cc", "Subject", "Message-ID"],
                },
            )

            if orig_response.status_code != 200:
                error_msg = (
                    orig_response.json()
                    .get("error", {})
                    .get("message", orig_response.text)
                )
                raise ValueError(f"Gmail API error: {error_msg}")

            orig_data = orig_response.json()
            thread_id = orig_data.get("threadId")

            # Extract original headers
            orig_headers = {}
            for header in orig_data.get("payload", {}).get("headers", []):
                orig_headers[header.get("name", "")] = header.get("value", "")

            # Build reply
            reply_body = await self._brand_email_body(ensure_html_body(config.body))
            message = await self._build_mime_message(
                reply_body, config.inline_images, config.attachments
            )
            message["From"] = from_email

            if config.reply_all:
                # Reply to sender and all recipients
                to_list = [orig_headers.get("From", "")]
                if orig_headers.get("To"):
                    to_list.extend(
                        [t.strip() for t in orig_headers.get("To", "").split(",")]
                    )
                # Remove self from recipients
                to_list = [t for t in to_list if from_email not in t]
                message["To"] = ", ".join(to_list)
                if orig_headers.get("Cc"):
                    message["Cc"] = orig_headers.get("Cc")
            else:
                message["To"] = orig_headers.get("From", "")

            # Set subject with Re: prefix if not already present
            orig_subject = orig_headers.get("Subject", "")
            if not orig_subject.lower().startswith("re:"):
                message["Subject"] = f"Re: {orig_subject}"
            else:
                message["Subject"] = orig_subject

            # Set threading headers
            message["In-Reply-To"] = orig_headers.get("Message-ID", "")
            message["References"] = orig_headers.get("Message-ID", "")

            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

            # Send reply
            response = await client.post(
                f"{GMAIL_API_BASE}/messages/send",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={"raw": raw_message, "threadId": thread_id},
            )

            if response.status_code != 200:
                error_msg = (
                    response.json().get("error", {}).get("message", response.text)
                )
                raise ValueError(f"Gmail API error: {error_msg}")

            data = response.json()
            return {
                "type": "gmail",
                "operation": "reply_to_email_message",
                "message_id": data.get("id"),
                "thread_id": data.get("threadId"),
                "in_reply_to": config.message_id,
                "timestamp": time.time(),
                "status": "success",
            }

    async def _forward_message(
        self, config: GmailForwardConfig, access_token: str, from_email: str
    ) -> Dict[str, Any]:
        """Forward a message."""
        logger.info(f"[GmailNode] Forwarding message {config.message_id}")

        # Get the original message
        async with httpx.AsyncClient() as client:
            orig_response = await client.get(
                f"{GMAIL_API_BASE}/messages/{config.message_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"format": "full"},
            )

            if orig_response.status_code != 200:
                error_msg = (
                    orig_response.json()
                    .get("error", {})
                    .get("message", orig_response.text)
                )
                raise ValueError(f"Gmail API error: {error_msg}")

            orig_data = orig_response.json()

            # Extract original headers and body
            orig_headers = {}
            for header in orig_data.get("payload", {}).get("headers", []):
                orig_headers[header.get("name", "")] = header.get("value", "")

            orig_body = self._extract_body(orig_data.get("payload", {}))

            # Build forwarded body
            forward_header = f"""
<br><br>---------- Forwarded message ---------<br>
From: {orig_headers.get('From', '')}<br>
Date: {orig_headers.get('Date', '')}<br>
Subject: {orig_headers.get('Subject', '')}<br>
To: {orig_headers.get('To', '')}<br>
<br>
"""

            # Footer rides the composed comment, above the forwarded block.
            comment = await self._brand_email_body(
                ensure_html_body(config.additional_message or "")
            )
            body = comment + forward_header + orig_body

            # Build forwarded message
            self._validate_recipients(to=config.to)
            message = await self._build_mime_message(
                body, config.inline_images, config.attachments
            )
            message["From"] = from_email
            message["To"] = self._join_recipients(config.to)

            # Set subject with Fwd: prefix
            orig_subject = orig_headers.get("Subject", "")
            if not orig_subject.lower().startswith("fwd:"):
                message["Subject"] = f"Fwd: {orig_subject}"
            else:
                message["Subject"] = orig_subject

            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

            # Send forwarded message
            response = await client.post(
                f"{GMAIL_API_BASE}/messages/send",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={"raw": raw_message},
            )

            if response.status_code != 200:
                error_msg = (
                    response.json().get("error", {}).get("message", response.text)
                )
                raise ValueError(f"Gmail API error: {error_msg}")

            data = response.json()
            return {
                "type": "gmail",
                "operation": "forward_email_message",
                "message_id": data.get("id"),
                "thread_id": data.get("threadId"),
                "forwarded_from": config.message_id,
                "to": config.to,
                "timestamp": time.time(),
                "status": "success",
            }

    # ========================================================================
    # Draft Operations
    # ========================================================================

    async def _create_draft(
        self, config: GmailCreateDraftConfig, access_token: str, from_email: str
    ) -> Dict[str, Any]:
        """Create a draft email."""
        logger.info(f"[GmailNode] Creating draft to {config.to}")

        self._validate_recipients(to=config.to, cc=config.cc, bcc=config.bcc)
        message = await self._build_mime_message(
            ensure_html_body(config.body), config.inline_images, config.attachments
        )
        message["To"] = self._join_recipients(config.to)
        message["From"] = from_email
        message["Subject"] = config.subject

        if config.cc:
            message["Cc"] = self._join_recipients(config.cc)
        if config.bcc:
            message["Bcc"] = self._join_recipients(config.bcc)

        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{GMAIL_API_BASE}/drafts",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={"message": {"raw": raw_message}},
            )

            if response.status_code != 200:
                error_msg = (
                    response.json().get("error", {}).get("message", response.text)
                )
                raise ValueError(f"Gmail API error: {error_msg}")

            data = response.json()
            return {
                "type": "gmail",
                "operation": "create_email_draft",
                "draft_id": data.get("id"),
                "message_id": data.get("message", {}).get("id"),
                "to": config.to,
                "subject": config.subject,
                "timestamp": time.time(),
                "status": "success",
            }

    async def _list_drafts(
        self, config: GmailListDraftsConfig, access_token: str
    ) -> Dict[str, Any]:
        """List all drafts with pagination support."""
        logger.info("[GmailNode] Listing drafts")

        params = {"maxResults": config.max_results}
        if config.query:
            params["q"] = config.query
        if config.page_token:
            params["pageToken"] = config.page_token

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{GMAIL_API_BASE}/drafts",
                headers={"Authorization": f"Bearer {access_token}"},
                params=params,
            )

            if response.status_code != 200:
                error_msg = (
                    response.json().get("error", {}).get("message", response.text)
                )
                raise ValueError(f"Gmail API error: {error_msg}")

            data = response.json()
            drafts = data.get("drafts", [])
            next_page_token = data.get("nextPageToken")

            return {
                "type": "gmail",
                "operation": "list_email_drafts",
                "draft_count": len(drafts),
                "drafts": drafts,
                "next_page_token": next_page_token,
                "has_more": next_page_token is not None,
                "timestamp": time.time(),
                "status": "success",
            }

    async def _get_draft(
        self, config: GmailGetDraftConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get a specific draft."""
        logger.info(f"[GmailNode] Getting draft {config.draft_id}")

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{GMAIL_API_BASE}/drafts/{config.draft_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"format": "full"},
            )

            if response.status_code != 200:
                error_msg = (
                    response.json().get("error", {}).get("message", response.text)
                )
                raise ValueError(f"Gmail API error: {error_msg}")

            data = response.json()
            message = data.get("message", {})

            # Extract headers
            headers = {}
            for header in message.get("payload", {}).get("headers", []):
                name = header.get("name", "").lower()
                if name in ["from", "to", "subject", "date", "cc", "bcc"]:
                    headers[name] = header.get("value", "")

            return {
                "type": "gmail",
                "operation": "fetch_email_draft",
                "draft_id": data.get("id"),
                "message_id": message.get("id"),
                "headers": headers,
                "snippet": message.get("snippet"),
                "body": self._extract_body(message.get("payload", {})),
                "timestamp": time.time(),
                "status": "success",
            }

    async def _update_draft(
        self, config: GmailUpdateDraftConfig, access_token: str, from_email: str
    ) -> Dict[str, Any]:
        """Update an existing draft."""
        logger.info(f"[GmailNode] Updating draft {config.draft_id}")

        message = await self._build_mime_message(ensure_html_body(config.body), [])
        message["To"] = config.to
        message["From"] = from_email
        message["Subject"] = config.subject

        if config.cc:
            message["Cc"] = config.cc
        if config.bcc:
            message["Bcc"] = config.bcc

        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

        async with httpx.AsyncClient() as client:
            response = await client.put(
                f"{GMAIL_API_BASE}/drafts/{config.draft_id}",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={"message": {"raw": raw_message}},
            )

            if response.status_code != 200:
                error_msg = (
                    response.json().get("error", {}).get("message", response.text)
                )
                raise ValueError(f"Gmail API error: {error_msg}")

            data = response.json()
            return {
                "type": "gmail",
                "operation": "update_email_draft",
                "draft_id": data.get("id"),
                "message_id": data.get("message", {}).get("id"),
                "timestamp": time.time(),
                "status": "success",
            }

    async def _delete_draft(
        self, config: GmailDeleteDraftConfig, access_token: str
    ) -> Dict[str, Any]:
        """Delete a draft."""
        logger.info(f"[GmailNode] Deleting draft {config.draft_id}")

        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{GMAIL_API_BASE}/drafts/{config.draft_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 204:
                error_msg = (
                    response.json().get("error", {}).get("message", response.text)
                    if response.text
                    else "Unknown error"
                )
                raise ValueError(f"Gmail API error: {error_msg}")

            return {
                "type": "gmail",
                "operation": "delete_email_draft",
                "draft_id": config.draft_id,
                "timestamp": time.time(),
                "status": "success",
            }

    async def _send_draft(
        self, config: GmailSendDraftConfig, access_token: str
    ) -> Dict[str, Any]:
        """Send an existing draft."""
        logger.info(f"[GmailNode] Sending draft {config.draft_id}")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{GMAIL_API_BASE}/drafts/send",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={"id": config.draft_id},
            )

            if response.status_code != 200:
                error_msg = (
                    response.json().get("error", {}).get("message", response.text)
                )
                raise ValueError(f"Gmail API error: {error_msg}")

            data = response.json()
            return {
                "type": "gmail",
                "operation": "send_email_draft",
                "message_id": data.get("id"),
                "thread_id": data.get("threadId"),
                "draft_id": config.draft_id,
                "timestamp": time.time(),
                "status": "success",
            }

    # ========================================================================
    # Label Operations
    # ========================================================================

    async def _list_labels(self, access_token: str) -> Dict[str, Any]:
        """List all labels."""
        logger.info("[GmailNode] Listing labels")

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{GMAIL_API_BASE}/labels",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                error_msg = (
                    response.json().get("error", {}).get("message", response.text)
                )
                raise ValueError(f"Gmail API error: {error_msg}")

            data = response.json()
            labels = data.get("labels", [])

            return {
                "type": "gmail",
                "operation": "list_email_labels",
                "label_count": len(labels),
                "labels": labels,
                "timestamp": time.time(),
                "status": "success",
            }

    async def _create_label(
        self, config: GmailCreateLabelConfig, access_token: str
    ) -> Dict[str, Any]:
        """Create a new label."""
        logger.info(f"[GmailNode] Creating label: {config.name}")

        body = {
            "name": config.name,
            "labelListVisibility": config.label_list_visibility,
            "messageListVisibility": config.message_list_visibility,
        }

        if config.background_color and config.text_color:
            body["color"] = {
                "backgroundColor": config.background_color,
                "textColor": config.text_color,
            }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{GMAIL_API_BASE}/labels",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=body,
            )

            if response.status_code != 200:
                error_msg = (
                    response.json().get("error", {}).get("message", response.text)
                )
                raise ValueError(f"Gmail API error: {error_msg}")

            data = response.json()
            return {
                "type": "gmail",
                "operation": "create_email_label",
                "label_id": data.get("id"),
                "name": data.get("name"),
                "timestamp": time.time(),
                "status": "success",
            }

    async def _get_label(
        self, config: GmailGetLabelConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get a specific label."""
        logger.info(f"[GmailNode] Getting label {config.label_id}")

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{GMAIL_API_BASE}/labels/{config.label_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                error_msg = (
                    response.json().get("error", {}).get("message", response.text)
                )
                raise ValueError(f"Gmail API error: {error_msg}")

            data = response.json()
            return {
                "type": "gmail",
                "operation": "fetch_email_label",
                "label_id": data.get("id"),
                "name": data.get("name"),
                "type": data.get("type"),
                "messages_total": data.get("messagesTotal"),
                "messages_unread": data.get("messagesUnread"),
                "threads_total": data.get("threadsTotal"),
                "threads_unread": data.get("threadsUnread"),
                "timestamp": time.time(),
                "status": "success",
            }

    async def _update_label(
        self, config: GmailUpdateLabelConfig, access_token: str
    ) -> Dict[str, Any]:
        """Update an existing label."""
        logger.info(f"[GmailNode] Updating label {config.label_id}")

        body = {"id": config.label_id}
        if config.name:
            body["name"] = config.name
        if config.label_list_visibility:
            body["labelListVisibility"] = config.label_list_visibility
        if config.message_list_visibility:
            body["messageListVisibility"] = config.message_list_visibility
        if config.background_color and config.text_color:
            body["color"] = {
                "backgroundColor": config.background_color,
                "textColor": config.text_color,
            }

        async with httpx.AsyncClient() as client:
            response = await client.patch(
                f"{GMAIL_API_BASE}/labels/{config.label_id}",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=body,
            )

            if response.status_code != 200:
                error_msg = (
                    response.json().get("error", {}).get("message", response.text)
                )
                raise ValueError(f"Gmail API error: {error_msg}")

            data = response.json()
            return {
                "type": "gmail",
                "operation": "update_email_label",
                "label_id": data.get("id"),
                "name": data.get("name"),
                "timestamp": time.time(),
                "status": "success",
            }

    async def _delete_label(
        self, config: GmailDeleteLabelConfig, access_token: str
    ) -> Dict[str, Any]:
        """Delete a label."""
        logger.info(f"[GmailNode] Deleting label {config.label_id}")

        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{GMAIL_API_BASE}/labels/{config.label_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 204:
                error_msg = (
                    response.json().get("error", {}).get("message", response.text)
                    if response.text
                    else "Unknown error"
                )
                raise ValueError(f"Gmail API error: {error_msg}")

            return {
                "type": "gmail",
                "operation": "delete_email_label",
                "label_id": config.label_id,
                "timestamp": time.time(),
                "status": "success",
            }

    # ========================================================================
    # Thread Operations
    # ========================================================================

    async def _list_threads(
        self, config: GmailListThreadsConfig, access_token: str
    ) -> Dict[str, Any]:
        """List email threads with pagination support."""
        logger.info("[GmailNode] Listing threads")

        params = {"maxResults": config.max_results}
        if config.query:
            params["q"] = config.query
        if config.label_ids:
            params["labelIds"] = [l.strip() for l in config.label_ids.split(",")]
        if config.page_token:
            params["pageToken"] = config.page_token

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{GMAIL_API_BASE}/threads",
                headers={"Authorization": f"Bearer {access_token}"},
                params=params,
            )

            if response.status_code != 200:
                error_msg = (
                    response.json().get("error", {}).get("message", response.text)
                )
                raise ValueError(f"Gmail API error: {error_msg}")

            data = response.json()
            threads = data.get("threads", [])
            next_page_token = data.get("nextPageToken")

            return {
                "type": "gmail",
                "operation": "list_email_threads",
                "thread_count": len(threads),
                "threads": threads,
                "next_page_token": next_page_token,
                "has_more": next_page_token is not None,
                "timestamp": time.time(),
                "status": "success",
            }

    async def _get_thread(
        self, config: GmailGetThreadConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get a specific thread."""
        logger.info(f"[GmailNode] Getting thread {config.thread_id}")

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{GMAIL_API_BASE}/threads/{config.thread_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"format": config.format},
            )

            if response.status_code != 200:
                error_msg = (
                    response.json().get("error", {}).get("message", response.text)
                )
                raise ValueError(f"Gmail API error: {error_msg}")

            data = response.json()
            messages = data.get("messages", [])

            # Parse messages if full format
            parsed_messages = []
            if config.format == "full":
                for msg in messages:
                    headers = {}
                    for header in msg.get("payload", {}).get("headers", []):
                        name = header.get("name", "").lower()
                        if name in ["from", "to", "subject", "date"]:
                            headers[name] = header.get("value", "")

                    parsed_messages.append(
                        {
                            "id": msg.get("id"),
                            "snippet": msg.get("snippet"),
                            "headers": headers,
                            "body": self._extract_body(msg.get("payload", {})),
                        }
                    )
            else:
                parsed_messages = messages

            return {
                "type": "gmail",
                "operation": "fetch_email_thread",
                "thread_id": data.get("id"),
                "message_count": len(messages),
                "messages": parsed_messages,
                "timestamp": time.time(),
                "status": "success",
            }

    async def _trash_thread(
        self, config: GmailTrashThreadConfig, access_token: str
    ) -> Dict[str, Any]:
        """Move a thread to trash."""
        logger.info(f"[GmailNode] Trashing thread {config.thread_id}")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{GMAIL_API_BASE}/threads/{config.thread_id}/trash",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                error_msg = (
                    response.json().get("error", {}).get("message", response.text)
                )
                raise ValueError(f"Gmail API error: {error_msg}")

            data = response.json()
            return {
                "type": "gmail",
                "operation": "move_thread_to_trash",
                "thread_id": data.get("id"),
                "timestamp": time.time(),
                "status": "success",
            }

    async def _untrash_thread(
        self, config: GmailUntrashThreadConfig, access_token: str
    ) -> Dict[str, Any]:
        """Restore a thread from trash."""
        logger.info(f"[GmailNode] Untrashing thread {config.thread_id}")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{GMAIL_API_BASE}/threads/{config.thread_id}/untrash",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                error_msg = (
                    response.json().get("error", {}).get("message", response.text)
                )
                raise ValueError(f"Gmail API error: {error_msg}")

            data = response.json()
            return {
                "type": "gmail",
                "operation": "restore_thread_from_trash",
                "thread_id": data.get("id"),
                "timestamp": time.time(),
                "status": "success",
            }

    async def _modify_thread(
        self, config: GmailModifyThreadConfig, access_token: str
    ) -> Dict[str, Any]:
        """Modify labels on a thread."""
        logger.info(f"[GmailNode] Modifying thread {config.thread_id}")

        body = {}
        if config.add_label_ids:
            body["addLabelIds"] = [l.strip() for l in config.add_label_ids.split(",")]
        if config.remove_label_ids:
            body["removeLabelIds"] = [
                l.strip() for l in config.remove_label_ids.split(",")
            ]

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{GMAIL_API_BASE}/threads/{config.thread_id}/modify",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=body,
            )

            if response.status_code != 200:
                error_msg = (
                    response.json().get("error", {}).get("message", response.text)
                )
                raise ValueError(f"Gmail API error: {error_msg}")

            data = response.json()
            return {
                "type": "gmail",
                "operation": "update_thread_labels",
                "thread_id": data.get("id"),
                "timestamp": time.time(),
                "status": "success",
            }

    async def _delete_thread(
        self, config: GmailDeleteThreadConfig, access_token: str
    ) -> Dict[str, Any]:
        """Permanently delete a thread."""
        logger.info(f"[GmailNode] Deleting thread {config.thread_id}")

        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{GMAIL_API_BASE}/threads/{config.thread_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 204:
                error_msg = (
                    response.json().get("error", {}).get("message", response.text)
                    if response.text
                    else "Unknown error"
                )
                raise ValueError(f"Gmail API error: {error_msg}")

            return {
                "type": "gmail",
                "operation": "permanently_delete_thread",
                "thread_id": config.thread_id,
                "timestamp": time.time(),
                "status": "success",
            }

    # ========================================================================
    # Profile Operations
    # ========================================================================

    async def _get_profile(self, access_token: str) -> Dict[str, Any]:
        """Get user's Gmail profile."""
        logger.info("[GmailNode] Getting profile")

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{GMAIL_API_BASE}/profile",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                error_msg = (
                    response.json().get("error", {}).get("message", response.text)
                )
                raise ValueError(f"Gmail API error: {error_msg}")

            data = response.json()
            return {
                "type": "gmail",
                "operation": "fetch_user_profile",
                "email_address": data.get("emailAddress"),
                "messages_total": data.get("messagesTotal"),
                "threads_total": data.get("threadsTotal"),
                "history_id": data.get("historyId"),
                "timestamp": time.time(),
                "status": "success",
            }

    # ========================================================================
    # Trigger Operations
    # ========================================================================

    def trigger_produced_no_event(self, output: Dict[str, Any]) -> bool:
        """No emails arrived since the last poll → skip downstream. Gmail dedups
        by ``internalDate`` high-water-mark, so an empty ``emails`` list means
        nothing new this tick. See ``WorkflowNode`` for the seam.
        """
        return (
            isinstance(output, dict)
            and output.get("operation") == "poll_for_new_emails"
            and not output.get("emails")
        )

    def trigger_emitted_event(self, output):
        """Fresh emails emitted → executor stamps _pollFired so a wired agent
        receives them on any run source."""
        return (
            isinstance(output, dict)
            and output.get("operation") == "poll_for_new_emails"
            and bool(output.get("emails"))
        )

    def _empty_trigger_output(self, config: GmailTriggerListenConfig) -> Dict[str, Any]:
        """The no-event trigger result (nothing new, or a skipped tick)."""
        return {
            "type": "gmail",
            "operation": "poll_for_new_emails",
            "status": "triggered",
            "email_count": 0,
            "emails": [],
            "query": config.query,
            "timestamp": time.time(),
        }

    async def _trigger_emails(
        self, config: GmailTriggerListenConfig, access_token: str
    ) -> Dict[str, Any]:
        """Emit emails that ARRIVED since the last poll — new messages and
        replies alike.

        Dedup is by Gmail's ``internalDate`` (arrival time), persisted as a
        high-water-mark in node state. The first poll *baselines*: it records
        the current newest arrival and emits nothing, so enabling the trigger
        never drains an existing backlog of old mail. Every subsequent poll
        emits messages strictly newer than the mark, sorted oldest-first, then
        advances the mark. Because the mark is per-MESSAGE (not per-thread), a
        reply landing in an old thread has a fresh ``internalDate`` and fires
        just like a brand-new email — that's what makes replies trigger too.

        ``mark_as_read`` is an optional side-action, NOT the dedup mechanism, so
        the trigger no longer mutates the mailbox just to avoid re-firing.
        """
        logger.info(
            f"[GmailNode] Trigger: checking for new emails (query={config.query!r})"
        )
        include_body = config.include_body == "true"

        # Load the watermark up front so the scan pages back only as far as it.
        # A transient state-read failure skips this tick cleanly (retry next).
        try:
            state = await self._load_node_state()
        except Exception as e:
            logger.warning(
                f"[GmailNode] Trigger {self.node_id}: state read failed, "
                f"skipping this tick: {e}"
            )
            self._poll_emitted_count = 0
            return self._empty_trigger_output(config)
        last_internal = state.get("last_internal_date")  # int ms, or None on first poll
        is_first_poll = last_internal is None

        base_params: Dict[str, Any] = {"maxResults": _GMAIL_TRIGGER_PAGE_SIZE}
        # On later polls, bound the scan to arrivals since the watermark via an
        # `after:` search term (second-granular — the mutator does the exact-ms
        # and same-ms boundary-id filtering). This keeps the normal poll cheap
        # (only the gap is fetched) and makes truncation rare. Default scope is
        # the inbox (new mail + replies land there; the user's own sent mail
        # does not), narrowed further by an optional user query.
        q_parts = []
        query = config.query.strip() if config.query else ""
        if query:
            q_parts.append(query)
        if not is_first_poll:
            q_parts.append(f"after:{last_internal // 1000}")
        if q_parts:
            base_params["q"] = " ".join(q_parts)
        if config.label_ids:
            base_params["labelIds"] = [l.strip() for l in config.label_ids.split(",")]
        elif not query:
            base_params["labelIds"] = ["INBOX"]

        details: List[Dict[str, Any]] = []
        truncated = False
        async with httpx.AsyncClient() as client:
            page_token: Optional[str] = None
            pages = 0
            done = False
            while not done:
                params = dict(base_params)
                if page_token:
                    params["pageToken"] = page_token
                response = await client.get(
                    f"{GMAIL_API_BASE}/messages",
                    headers={"Authorization": f"Bearer {access_token}"},
                    params=params,
                )
                if response.status_code != 200:
                    error_msg = (
                        response.json().get("error", {}).get("message", response.text)
                    )
                    raise ValueError(f"Gmail API error: {error_msg}")
                data = response.json()

                for msg_ref in data.get("messages", []):
                    detail = await self._fetch_message_detail(
                        client, access_token, msg_ref["id"], include_body
                    )
                    if not detail:
                        continue
                    details.append(detail)
                    # Baseline needs only the newest arrival; a single page of
                    # most-recent-first results already yields it.
                    if is_first_poll:
                        done = True
                        break

                # The `after:` term already bounds the scan to the watermark's
                # second onward, so page through the whole (small) window rather
                # than stopping at the first boundary message — that guarantees
                # the mutator sees EVERY message sharing the watermark ms, which
                # same-ms boundary dedup depends on.
                page_token = data.get("nextPageToken")
                pages += 1
                if done or not page_token:
                    break
                if pages >= _GMAIL_MAX_TRIGGER_PAGES:
                    truncated = True
                    break

        if truncated:
            # More new mail than one tick can scan. The watermark advances to the
            # newest, so the OLDEST unseen emails this cycle are DROPPED (a scalar
            # high-water-mark can't mark the newest seen without marking the gap
            # below it seen too). Rare given the `after:` bound; surface it.
            logger.warning(
                f"[GmailNode] Trigger {self.node_id}: more than "
                f"{_GMAIL_TRIGGER_PAGE_SIZE * _GMAIL_MAX_TRIGGER_PAGES} new emails "
                f"since the last poll — the oldest unseen ones this cycle are "
                f"dropped. Poll more frequently or narrow the query."
            )

        def mutator(st):
            last = st.get("last_internal_date")
            # Message ids seen at exactly the watermark ms, so a genuinely-new
            # message that shares that ms isn't mistaken for the already-emitted
            # boundary message (and vice-versa).
            boundary = set(st.get("last_internal_ids", []))

            def _at_newest(newest_ms):
                return [d["id"] for d in details if _gmail_internal_ms(d) == newest_ms]

            if last is None:
                # Baseline: record the newest arrival, emit nothing.
                newest = max((_gmail_internal_ms(d) for d in details), default=0)
                if newest == 0:
                    # Empty inbox (or no usable internalDate) — stay UNBASELINED
                    # so the next non-empty poll baselines properly, rather than
                    # storing 0 and issuing `after:0` (a full-mailbox scan) forever.
                    return None, []
                return {"last_internal_date": newest, "last_internal_ids": _at_newest(newest)}, []

            fresh = [
                d for d in details
                if _gmail_internal_ms(d) > last
                or (_gmail_internal_ms(d) == last and d["id"] not in boundary)
            ]
            if not fresh:
                return None, []
            fresh.sort(key=_gmail_internal_ms)  # oldest-first delivery
            newest = max(_gmail_internal_ms(d) for d in details)
            return {"last_internal_date": newest, "last_internal_ids": _at_newest(newest)}, fresh

        emails = await self._update_node_state(mutator, skip_result=[])

        if config.mark_as_read == "true" and emails:
            await self._mark_as_read(access_token, [e["id"] for e in emails])

        self._poll_emitted_count = len(emails)
        return {
            "type": "gmail",
            "operation": "poll_for_new_emails",
            "status": "triggered",
            "email_count": len(emails),
            "emails": emails,
            "query": config.query,
            "timestamp": time.time(),
        }

    async def _mark_as_read(self, access_token: str, message_ids: List[str]) -> None:
        """Mark messages as read by removing the UNREAD label."""
        async with httpx.AsyncClient() as client:
            for msg_id in message_ids:
                try:
                    await client.post(
                        f"{GMAIL_API_BASE}/messages/{msg_id}/modify",
                        headers={
                            "Authorization": f"Bearer {access_token}",
                            "Content-Type": "application/json",
                        },
                        json={"removeLabelIds": ["UNREAD"]},
                    )
                except Exception as e:
                    logger.warning(f"[GmailNode] Failed to mark {msg_id} as read: {e}")

    # ========================================================================
    # Helper Methods
    # ========================================================================

    async def _fetch_message_detail(
        self,
        client: httpx.AsyncClient,
        access_token: str,
        message_id: str,
        include_body: bool,
    ) -> Dict[str, Any]:
        """Fetch full details of a message."""
        url = f"{GMAIL_API_BASE}/messages/{message_id}"
        params = {"format": "full" if include_body else "metadata"}

        response = await client.get(
            url, headers={"Authorization": f"Bearer {access_token}"}, params=params
        )

        if response.status_code != 200:
            error_msg = response.json().get("error", {}).get("message", response.text)
            raise ValueError(
                f"Gmail API error fetching message {message_id}: {error_msg}"
            )

        data = response.json()

        headers = {}
        for header in data.get("payload", {}).get("headers", []):
            name = header.get("name", "").lower()
            if name in ["from", "to", "subject", "date", "cc", "bcc"]:
                headers[name] = header.get("value", "")

        result = {
            "id": data.get("id"),
            "thread_id": data.get("threadId"),
            # Gmail's internalDate (ms since epoch, as a string) is the arrival
            # timestamp — the watermark the trigger dedups on.
            "internal_date": data.get("internalDate"),
            "snippet": data.get("snippet"),
            "from": headers.get("from", ""),
            "to": headers.get("to", ""),
            "subject": headers.get("subject", ""),
            "date": headers.get("date", ""),
            "labels": data.get("labelIds", []),
        }

        if include_body:
            payload = data.get("payload", {})
            result["body"] = self._extract_body(payload)
            result["reply_text"] = self._strip_quoted_content(result["body"])
            # Bulk path: metadata only (never inline content) — a 20-email fetch
            # must not explode the output; fetch_email_attachment gets the text.
            attachments = self._extract_attachment_meta(payload)
            if attachments:
                result["attachments"] = attachments

        return result

    def _extract_attachment_meta(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Attachment parts (filename + attachmentId) anywhere in the MIME tree."""
        from utils.content_extraction import attachment_record

        found: List[Dict[str, Any]] = []

        def walk(part: Dict[str, Any]) -> None:
            body = part.get("body", {})
            if part.get("filename") and body.get("attachmentId"):
                found.append(attachment_record(
                    filename=part["filename"],
                    mime_type=part.get("mimeType", ""),
                    size_bytes=body.get("size"),
                    source="gmail",
                    attachment_id=body["attachmentId"],
                ))
            for child in part.get("parts", []):
                walk(child)

        walk(payload)
        return found

    async def _fetch_attachment_bytes(
        self, client: httpx.AsyncClient, access_token: str, message_id: str, attachment_id: str
    ) -> bytes:
        response = await client.get(
            f"{GMAIL_API_BASE}/messages/{message_id}/attachments/{attachment_id}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if response.status_code != 200:
            error_msg = response.json().get("error", {}).get("message", response.text)
            raise ValueError(f"Gmail API error fetching attachment: {error_msg}")
        return base64.urlsafe_b64decode(response.json()["data"])

    def _extract_body(self, payload: Dict[str, Any]) -> str:
        """Extract email body from payload."""
        body = ""

        body_data = payload.get("body", {}).get("data")
        if body_data:
            try:
                body = base64.urlsafe_b64decode(body_data).decode("utf-8")
            except Exception:
                pass

        parts = payload.get("parts", [])
        for part in parts:
            mime_type = part.get("mimeType", "")

            if mime_type == "text/html":
                data = part.get("body", {}).get("data")
                if data:
                    try:
                        body = base64.urlsafe_b64decode(data).decode("utf-8")
                        break
                    except Exception:
                        pass
            elif mime_type == "text/plain" and not body:
                data = part.get("body", {}).get("data")
                if data:
                    try:
                        body = base64.urlsafe_b64decode(data).decode("utf-8")
                    except Exception:
                        pass

            if part.get("parts"):
                nested_body = self._extract_body(part)
                if nested_body:
                    body = nested_body

        return body

    def _strip_quoted_content(self, body: str) -> str:
        """Extract just the reply text from an email body, stripping quoted original content."""
        if not body:
            return ""

        import re

        # HTML body — strip Gmail/Outlook quoted sections
        if "<" in body and ">" in body:
            # Gmail: <div class="gmail_quote">...</div>
            cleaned = re.split(r'<div\s+class=["\']gmail_quote["\']', body, maxsplit=1)[
                0
            ]
            # Gmail alternate: <div class="gmail_extra">
            cleaned = re.split(
                r'<div\s+class=["\']gmail_extra["\']', cleaned, maxsplit=1
            )[0]
            # Outlook: <div id="appendonsend">
            cleaned = re.split(
                r'<div\s+id=["\']appendonsend["\']', cleaned, maxsplit=1
            )[0]
            # Outlook: <div id="divRplyFwdMsg">
            cleaned = re.split(
                r'<div\s+id=["\']divRplyFwdMsg["\']', cleaned, maxsplit=1
            )[0]
            # Generic blockquote (common in replies)
            cleaned = re.split(
                r'<blockquote[^>]*class=["\']gmail_quote["\']', cleaned, maxsplit=1
            )[0]
            # Strip HTML tags and normalize whitespace
            text = re.sub(r"<br\s*/?>", "\n", cleaned)
            text = re.sub(r"<[^>]+>", "", text)
            text = re.sub(r"\n{3,}", "\n\n", text).strip()
            # Decode HTML entities
            import html

            text = html.unescape(text)
            return text

        # Plain text — strip "On ... wrote:" quoted blocks
        lines = body.split("\n")
        result_lines = []
        for line in lines:
            # Stop at "On ... wrote:" line (Gmail plain text quote marker)
            if re.match(r"^On .+ wrote:\s*$", line):
                break
            # Stop at lines starting with ">" (quoted text)
            if line.startswith(">"):
                break
            # Stop at "-----Original Message-----" (Outlook)
            if "-----Original Message-----" in line:
                break
            # Stop at "From: " header block (forwarded/quoted)
            if re.match(r"^From:\s+", line):
                break
            result_lines.append(line)

        return "\n".join(result_lines).strip()

    def _resolve_template(self, template: str, inputs: Dict[str, Any]) -> str:
        """Resolve template variables in strings."""
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
                            return match.group(0)
                    return str(data) if not isinstance(data, str) else data

            return match.group(0)

        return re.sub(r"\{\{([^}]+)\}\}", replace_match, template)
