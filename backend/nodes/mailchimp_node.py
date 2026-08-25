"""
Mailchimp automation node for Marketing and Transactional APIs.

Provides comprehensive workflow integration with 384 operations:
- Marketing API v3.0: 289 operations across:
- Lists/Audiences: Complete list management, subscriber operations, segments, and contacts API
- Campaigns: Email campaign creation, sending, scheduling, feedback, and advanced actions
- Automations: Classic automation workflows, customer journeys, and email queue management
- E-commerce: Stores, products, orders, customers, carts, promo rules & codes, and line operations
- Reports: Campaign analytics, Facebook ads, landing pages, surveys, and performance metrics
- Templates: Email template management, folders, and default content
- File Manager: File and folder management with folder file listings
- Signup Forms: List signup form management and retrieval
- Landing Pages: Content management and publishing actions
- Surveys: Complete survey lifecycle, questions, answers, and responses
- Member Operations: Notes, events, activity tracking, goals, and activity feeds
- Connected Sites: Website integration and script verification
- Conversations: Message management and customer communication
- Verified Domains: Domain verification and management
- Batch Webhooks: Batch webhook operations
- Search: Campaign and member search capabilities
- Facebook Ads: Ad management and reporting
- Account: Account information, authorized apps, and API root access
- And many additional resource categories for comprehensive Mailchimp integration

- Transactional API (Mandrill): 95 operations across:
- Messages: Send, schedule, search, and manage transactional emails and SMS
- Templates: Create, update, and manage email templates with dynamic content
- Senders: Manage sender domains, verification, and sender reputation
- Subaccounts: Create and manage multiple subaccounts for organization
- IPs: IP address management, warmup, pools, and custom DNS
- Webhooks: Configure and manage webhook endpoints for event tracking
- Tags: Organize and analyze messages with custom tags
- URLs: Track and analyze URL clicks and manage tracking domains
- Metadata: Custom metadata fields for enhanced message tracking
- Inbound: Inbound email routing and processing
- Allowlists/Denylists: Manage email allowlists and denylists
- Exports: Export account data and activity history
- Users: Account information and API health checks

Supports API Key, OAuth 2.0, and Mandrill API Key authentication.

API Documentation:
- Marketing: https://mailchimp.com/developer/marketing/api/
- Transactional (Mandrill): https://mandrillapp.com/api/docs/
"""

import logging
import time
import hashlib
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from utils.ssrf import guarded_async_client, normalize_provider_subdomain
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.scopes.mailchimp import MAILCHIMP_SCOPES

logger = logging.getLogger(__name__)

# Base API URL - datacenter is extracted from API key
# Format: https://<dc>.api.mailchimp.com/3.0/
MAILCHIMP_API_VERSION = "3.0"

# ============================================================================
# Credential Schemas
# ============================================================================


class MailchimpAPIKeyCredential(BaseModel):
    """API Key credential for Mailchimp Marketing API.

    Get your API key at: https://mailchimp.com/help/about-api-keys/
    Navigate to: Profile → Extras → API Keys → Create A Key
    """

    credential_type: Literal["mailchimp_api_key"] = Field(
        "mailchimp_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description="Your Mailchimp API key (format: xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx-us1)",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(json_schema_extra={
        "x-credential-url": "https://mailchimp.com/help/about-api-keys/"
    })


class MailchimpOAuthCredential(BaseModel):
    """OAuth 2.0 credential for Mailchimp Marketing API.

    OAuth is more secure and recommended for production integrations.
    Register your OAuth app at: Account → Extras → API Keys → Register and Manage Your Apps

    Note: Mailchimp OAuth tokens do not expire unless revoked by the user.
    """

    credential_type: Literal["mailchimp_oauth"] = Field(
        "mailchimp_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(..., title="Access Token")
    server_prefix: Optional[str] = Field(
        None,
        title="Server Prefix",
        description="Mailchimp datacenter prefix, for example us16",
        json_schema_extra={"ui:hidden": True},
    )
    api_endpoint: Optional[str] = Field(
        None, title="API Endpoint", json_schema_extra={"ui:hidden": True}
    )
    login_url: Optional[str] = Field(
        None, title="Login URL", json_schema_extra={"ui:hidden": True}
    )
    account_id: Optional[str] = Field(
        None, title="Account ID", json_schema_extra={"ui:hidden": True}
    )
    account_name: Optional[str] = Field(
        None, title="Account Name", json_schema_extra={"ui:hidden": True}
    )
    # Mailchimp OAuth tokens don't expire, so no refresh_token or expires_at needed
    metadata: Optional[Dict[str, Any]] = Field(
        None,
        title="Metadata",
        description="Server prefix and account details from OAuth flow",
    )

    model_config = ConfigDict(json_schema_extra={
        "x-credential-type": "oauth",
        "x-oauth-provider": "mailchimp",
        "x-oauth-scopes": [
            # Mailchimp uses a single scope for Marketing API access
            "marketing:read",
            "marketing:write",
        ],
        "x-credential-url": "https://mailchimp.com/developer/marketing/guides/access-user-data-oauth-2/",
    })


class MailchimpMandrillCredential(BaseModel):
    """Mandrill API Key credential for Transactional API.

    Get your API key at: https://mandrillapp.com/settings
    Navigate to: Settings → SMTP & API Info → API Keys → New API Key
    """

    credential_type: Literal["mailchimp_mandrill"] = Field(
        "mailchimp_mandrill", json_schema_extra={"ui:hidden": True}
    )
    mandrill_api_key: str = Field(
        ...,
        title="Mandrill API Key",
        description="Your Mandrill API key",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(json_schema_extra={"x-credential-url": "https://mandrillapp.com/settings"})


# Support both authentication methods - OAuth shown first in UI
MailchimpCredential = Union[
    MailchimpOAuthCredential, MailchimpAPIKeyCredential, MailchimpMandrillCredential
]


# ============================================================================
# Helper function to get MD5 hash for subscriber operations
# ============================================================================


def get_subscriber_hash(email: str) -> str:
    """Convert email to lowercase MD5 hash as required by Mailchimp API."""
    return hashlib.md5(email.lower().encode()).hexdigest()


# ============================================================================
# Lists/Audiences Operations (Core audience management)
# ============================================================================


class MailchimpListListsConfig(BaseModel):
    """Get all lists/audiences in the account."""

    operation: Literal["list_all_lists"] = Field(
        "list_all_lists",
        json_schema_extra={
            "const": "list_all_lists",
            "ui:hidden": True,
            "x-category": "List",
            "x-is-trigger": False,
            "x-display-name": "List All Lists",
        },
        title="List All Lists",
    )
    count: int = Field(
        10,
        title="Count",
        description="Number of records to return (max 1000)",
        ge=1,
        le=1000,
    )
    offset: int = Field(
        0, title="Offset", description="Number of records to skip", ge=0
    )
    sort_field: Optional[str] = Field(
        None, title="Sort Field", description="Field to sort by (date_created)"
    )
    sort_dir: Optional[Literal["ASC", "DESC"]] = Field(None, title="Sort Direction")


class MailchimpGetListConfig(BaseModel):
    """Get information about a specific list."""

    operation: Literal["fetch_list"] = Field(
        "fetch_list",
        json_schema_extra={
            "const": "fetch_list",
            "ui:hidden": True,
            "x-category": "List",
            "x-is-trigger": False,
            "x-display-name": "Fetch List",
        },
        title="Fetch List",
    )
    list_id: str = Field(..., title="List ID", description="The unique ID for the list")
    include_total_contacts: bool = Field(
        False, title="Include Total Contacts", description="Include total contact count"
    )


class MailchimpCreateListConfig(BaseModel):
    """Create a new list/audience."""

    operation: Literal["create_list"] = Field(
        "create_list",
        json_schema_extra={
            "const": "create_list",
            "ui:hidden": True,
            "x-category": "List",
            "x-is-trigger": False,
            "x-display-name": "Create List",
        },
        title="Create List",
    )
    name: str = Field(..., title="List Name", description="The name of the list")
    company: str = Field(..., title="Company", description="Company name")
    address1: str = Field(..., title="Address Line 1")
    city: str = Field(..., title="City")
    state: str = Field(..., title="State/Province/Region")
    zip: str = Field(..., title="Postal/Zip Code")
    country: str = Field(
        ..., title="Country", description="Two-letter country code (US, GB, etc.)"
    )
    permission_reminder: str = Field(
        ...,
        title="Permission Reminder",
        description="Reminder of how they signed up (e.g., 'You signed up on our website')",
    )
    from_name: str = Field(..., title="From Name", description="Default sender name")
    from_email: str = Field(..., title="From Email", description="Default sender email")
    subject: str = Field(
        ..., title="Default Subject", description="Default email subject"
    )
    language: str = Field(
        "en", title="Language", description="Default language (en, es, fr, etc.)"
    )
    email_type_option: bool = Field(
        True,
        title="Email Type Option",
        description="Allow subscribers to choose HTML or text",
    )
    double_optin: bool = Field(
        False, title="Double Opt-In", description="Require double opt-in confirmation"
    )


class MailchimpUpdateListConfig(BaseModel):
    """Update settings for a list."""

    operation: Literal["update_list_settings"] = Field(
        "update_list_settings",
        json_schema_extra={
            "const": "update_list_settings",
            "ui:hidden": True,
            "x-category": "List",
            "x-is-trigger": False,
            "x-display-name": "Update List Settings",
        },
        title="Update List Settings",
    )
    list_id: str = Field(..., title="List ID")
    name: Optional[str] = Field(None, title="List Name")
    permission_reminder: Optional[str] = Field(None, title="Permission Reminder")
    from_name: Optional[str] = Field(None, title="From Name")
    from_email: Optional[str] = Field(None, title="From Email")
    subject: Optional[str] = Field(None, title="Default Subject")


class MailchimpDeleteListConfig(BaseModel):
    """Delete a list (archives it - does not permanently delete)."""

    operation: Literal["archive_list"] = Field(
        "archive_list",
        json_schema_extra={
            "const": "archive_list",
            "ui:hidden": True,
            "x-category": "List",
            "x-is-trigger": False,
            "x-display-name": "Archive List",
        },
        title="Archive List",
    )
    list_id: str = Field(..., title="List ID")


# ============================================================================
# List Members Operations (Subscriber management - most commonly used)
# ============================================================================


class MailchimpListMembersConfig(BaseModel):
    """Get members/subscribers in a list."""

    operation: Literal["list_list_members"] = Field(
        "list_list_members",
        json_schema_extra={
            "const": "list_list_members",
            "ui:hidden": True,
            "x-category": "Member",
            "x-is-trigger": False,
            "x-display-name": "List List Members",
        },
        title="List List Members",
    )
    list_id: str = Field(..., title="List ID")
    count: int = Field(10, title="Count", ge=1, le=1000)
    offset: int = Field(0, title="Offset", ge=0)
    status: Optional[
        Literal["subscribed", "unsubscribed", "cleaned", "pending"]
    ] = Field(None, title="Status Filter")


class MailchimpGetMemberConfig(BaseModel):
    """Get information about a specific list member."""

    operation: Literal["fetch_list_member"] = Field(
        "fetch_list_member",
        json_schema_extra={
            "const": "fetch_list_member",
            "ui:hidden": True,
            "x-category": "Member",
            "x-is-trigger": False,
            "x-display-name": "Fetch List Member",
        },
        title="Fetch List Member",
    )
    list_id: str = Field(..., title="List ID")
    email_address: str = Field(
        ..., title="Email Address", description="Member email address"
    )


class MailchimpAddMemberConfig(BaseModel):
    """Add a new member to a list."""

    operation: Literal["create_list_member"] = Field(
        "create_list_member",
        json_schema_extra={
            "const": "create_list_member",
            "ui:hidden": True,
            "x-category": "Member",
            "x-is-trigger": False,
            "x-display-name": "Create List Member",
        },
        title="Create List Member",
    )
    list_id: str = Field(..., title="List ID")
    email_address: str = Field(..., title="Email Address")
    status: Literal["subscribed", "unsubscribed", "cleaned", "pending"] = Field(
        "subscribed", title="Status", description="Subscription status"
    )
    merge_fields: Optional[Dict[str, Any]] = Field(
        None,
        title="Merge Fields",
        description='Custom fields (e.g., {"FNAME": "John", "LNAME": "Doe"})',
        json_schema_extra={"ui:widget": "textarea"},
    )
    interests: Optional[Dict[str, bool]] = Field(
        None,
        title="Interests",
        description='Interest group settings (e.g., {"interest_id": true})',
        json_schema_extra={"ui:widget": "textarea"},
    )
    language: Optional[str] = Field(None, title="Language Code")
    vip: bool = Field(False, title="VIP Status")


class MailchimpUpdateMemberConfig(BaseModel):
    """Update an existing list member."""

    operation: Literal["update_list_member"] = Field(
        "update_list_member",
        json_schema_extra={
            "const": "update_list_member",
            "ui:hidden": True,
            "x-category": "Member",
            "x-is-trigger": False,
            "x-display-name": "Update List Member",
        },
        title="Update List Member",
    )
    list_id: str = Field(..., title="List ID")
    email_address: str = Field(
        ..., title="Email Address", description="Current email of the member"
    )
    new_email_address: Optional[str] = Field(
        None, title="New Email Address", description="Update email if changing"
    )
    status: Optional[
        Literal["subscribed", "unsubscribed", "cleaned", "pending"]
    ] = Field(None, title="Status")
    merge_fields: Optional[Dict[str, Any]] = Field(
        None, title="Merge Fields", json_schema_extra={"ui:widget": "textarea"}
    )
    interests: Optional[Dict[str, bool]] = Field(
        None, title="Interests", json_schema_extra={"ui:widget": "textarea"}
    )
    language: Optional[str] = Field(None, title="Language Code")
    vip: Optional[bool] = Field(None, title="VIP Status")


class MailchimpAddOrUpdateMemberConfig(BaseModel):
    """Add or update a list member (upsert operation)."""

    operation: Literal["upsert_list_member"] = Field(
        "upsert_list_member",
        json_schema_extra={
            "const": "upsert_list_member",
            "ui:hidden": True,
            "x-category": "Member",
            "x-is-trigger": False,
            "x-display-name": "Upsert List Member",
        },
        title="Upsert List Member",
    )
    list_id: str = Field(..., title="List ID")
    email_address: str = Field(..., title="Email Address")
    status_if_new: Literal["subscribed", "unsubscribed", "cleaned", "pending"] = Field(
        "subscribed",
        title="Status If New",
        description="Status to use if this is a new subscriber",
    )
    merge_fields: Optional[Dict[str, Any]] = Field(
        None, title="Merge Fields", json_schema_extra={"ui:widget": "textarea"}
    )
    interests: Optional[Dict[str, bool]] = Field(
        None, title="Interests", json_schema_extra={"ui:widget": "textarea"}
    )
    language: Optional[str] = Field(None, title="Language Code")
    vip: bool = Field(False, title="VIP Status")


class MailchimpDeleteMemberConfig(BaseModel):
    """Archive a list member (soft delete)."""

    operation: Literal["archive_list_member"] = Field(
        "archive_list_member",
        json_schema_extra={
            "const": "archive_list_member",
            "ui:hidden": True,
            "x-category": "Member",
            "x-is-trigger": False,
            "x-display-name": "Archive List Member",
        },
        title="Archive List Member",
    )
    list_id: str = Field(..., title="List ID")
    email_address: str = Field(..., title="Email Address")


class MailchimpPermanentlyDeleteMemberConfig(BaseModel):
    """Permanently delete a list member (cannot be undone)."""

    operation: Literal["permanently_delete_list_member"] = Field(
        "permanently_delete_list_member",
        json_schema_extra={
            "const": "permanently_delete_list_member",
            "ui:hidden": True,
            "x-category": "Member",
            "x-is-trigger": False,
            "x-display-name": "Permanently Delete List Member",
        },
        title="Permanently Delete List Member",
    )
    list_id: str = Field(..., title="List ID")
    email_address: str = Field(
        ..., title="Email Address", description="WARNING: This cannot be undone"
    )


# ============================================================================
# Campaign Operations (Email campaign management)
# ============================================================================


class MailchimpListCampaignsConfig(BaseModel):
    """Get all campaigns."""

    operation: Literal["list_campaigns"] = Field(
        "list_campaigns",
        json_schema_extra={
            "const": "list_campaigns",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "List Campaigns",
        },
        title="List Campaigns",
    )
    count: int = Field(10, title="Count", ge=1, le=1000)
    offset: int = Field(0, title="Offset", ge=0)
    type: Optional[
        Literal["regular", "plaintext", "absplit", "rss", "variate"]
    ] = Field(None, title="Campaign Type")
    status: Optional[Literal["save", "paused", "schedule", "sending", "sent"]] = Field(
        None, title="Status Filter"
    )
    list_id: Optional[str] = Field(
        None, title="List ID Filter", description="Filter by list"
    )


class MailchimpGetCampaignConfig(BaseModel):
    """Get information about a specific campaign."""

    operation: Literal["fetch_campaign"] = Field(
        "fetch_campaign",
        json_schema_extra={
            "const": "fetch_campaign",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Fetch Campaign",
        },
        title="Fetch Campaign",
    )
    campaign_id: str = Field(..., title="Campaign ID")


class MailchimpCreateCampaignConfig(BaseModel):
    """Create a new email campaign."""

    operation: Literal["create_campaign"] = Field(
        "create_campaign",
        json_schema_extra={
            "const": "create_campaign",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Create Campaign",
        },
        title="Create Campaign",
    )
    type: Literal["regular", "plaintext", "absplit", "rss", "variate"] = Field(
        "regular", title="Campaign Type"
    )
    list_id: str = Field(..., title="List ID", description="List to send campaign to")
    subject_line: str = Field(..., title="Subject Line")
    from_name: str = Field(..., title="From Name")
    reply_to: str = Field(..., title="Reply-To Email")
    title: Optional[str] = Field(
        None, title="Campaign Title", description="Internal name for the campaign"
    )
    preview_text: Optional[str] = Field(
        None, title="Preview Text", description="Text shown in email preview"
    )


class MailchimpUpdateCampaignConfig(BaseModel):
    """Update campaign settings."""

    operation: Literal["update_campaign_settings"] = Field(
        "update_campaign_settings",
        json_schema_extra={
            "const": "update_campaign_settings",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Update Campaign Settings",
        },
        title="Update Campaign Settings",
    )
    campaign_id: str = Field(..., title="Campaign ID")
    subject_line: Optional[str] = Field(None, title="Subject Line")
    from_name: Optional[str] = Field(None, title="From Name")
    reply_to: Optional[str] = Field(None, title="Reply-To Email")
    title: Optional[str] = Field(None, title="Campaign Title")
    preview_text: Optional[str] = Field(None, title="Preview Text")


class MailchimpDeleteCampaignConfig(BaseModel):
    """Delete a campaign."""

    operation: Literal["delete_campaign"] = Field(
        "delete_campaign",
        json_schema_extra={
            "const": "delete_campaign",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Delete Campaign",
        },
        title="Delete Campaign",
    )
    campaign_id: str = Field(..., title="Campaign ID")


class MailchimpSendCampaignConfig(BaseModel):
    """Send a campaign immediately."""

    operation: Literal["send_campaign_immediately"] = Field(
        "send_campaign_immediately",
        json_schema_extra={
            "const": "send_campaign_immediately",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Send Campaign Immediately",
        },
        title="Send Campaign Immediately",
    )
    campaign_id: str = Field(
        ...,
        title="Campaign ID",
        description="Campaign must have content and pass send checklist",
    )


class MailchimpScheduleCampaignConfig(BaseModel):
    """Schedule a campaign for future delivery."""

    operation: Literal["schedule_campaign_for_delivery"] = Field(
        "schedule_campaign_for_delivery",
        json_schema_extra={
            "const": "schedule_campaign_for_delivery",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Schedule Campaign for Delivery",
        },
        title="Schedule Campaign for Delivery",
    )
    campaign_id: str = Field(..., title="Campaign ID")
    schedule_time: str = Field(
        ...,
        title="Schedule Time",
        description="ISO 8601 datetime (e.g., 2024-12-25T10:00:00Z)",
    )


class MailchimpUnscheduleCampaignConfig(BaseModel):
    """Unschedule a scheduled campaign."""

    operation: Literal["unschedule_campaign"] = Field(
        "unschedule_campaign",
        json_schema_extra={
            "const": "unschedule_campaign",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Unschedule Campaign",
        },
        title="Unschedule Campaign",
    )
    campaign_id: str = Field(..., title="Campaign ID")


class MailchimpSendTestEmailConfig(BaseModel):
    """Send a test email for a campaign."""

    operation: Literal["send_campaign_test_email"] = Field(
        "send_campaign_test_email",
        json_schema_extra={
            "const": "send_campaign_test_email",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Send Campaign Test Email",
        },
        title="Send Campaign Test Email",
    )
    campaign_id: str = Field(..., title="Campaign ID")
    test_emails: List[str] = Field(
        ...,
        title="Test Email Addresses",
        description="List of email addresses to send test to (max 5)",
        max_length=5,
    )
    send_type: Literal["html", "plaintext"] = Field("html", title="Email Format")


class MailchimpReplicateCampaignConfig(BaseModel):
    """Create a copy of a campaign."""

    operation: Literal["duplicate_campaign"] = Field(
        "duplicate_campaign",
        json_schema_extra={
            "const": "duplicate_campaign",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Duplicate Campaign",
        },
        title="Duplicate Campaign",
    )
    campaign_id: str = Field(..., title="Campaign ID")


# ============================================================================
# Campaign Content Operations
# ============================================================================


class MailchimpGetCampaignContentConfig(BaseModel):
    """Get the HTML and plain-text content for a campaign."""

    operation: Literal["fetch_campaign_content"] = Field(
        "fetch_campaign_content",
        json_schema_extra={
            "const": "fetch_campaign_content",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Fetch Campaign Content",
        },
        title="Fetch Campaign Content",
    )
    campaign_id: str = Field(..., title="Campaign ID")


class MailchimpSetCampaignContentConfig(BaseModel):
    """Set the content for a campaign."""

    operation: Literal["update_campaign_content"] = Field(
        "update_campaign_content",
        json_schema_extra={
            "const": "update_campaign_content",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Update Campaign Content",
        },
        title="Update Campaign Content",
    )
    campaign_id: str = Field(..., title="Campaign ID")
    html: Optional[str] = Field(
        None,
        title="HTML Content",
        description="Full HTML content of the email",
        json_schema_extra={"ui:widget": "textarea"},
    )
    plain_text: Optional[str] = Field(
        None, title="Plain Text Content", json_schema_extra={"ui:widget": "textarea"}
    )
    template_id: Optional[int] = Field(
        None, title="Template ID", description="Use a saved template"
    )


# ============================================================================
# AUTOMATION OPERATIONS - Classic Automations
# ============================================================================


class MailchimpListAutomationsConfig(BaseModel):
    """Get all classic automation workflows."""

    operation: Literal["list_automation_workflows"] = Field(
        "list_automation_workflows",
        json_schema_extra={
            "const": "list_automation_workflows",
            "ui:hidden": True,
            "x-category": "Automation",
            "x-is-trigger": False,
            "x-display-name": "List Automation Workflows",
        },
        title="List Automation Workflows",
    )
    count: int = Field(10, title="Count", ge=1, le=1000)
    offset: int = Field(0, title="Offset", ge=0)
    status: Optional[Literal["save", "paused", "sending"]] = Field(
        None, title="Status Filter"
    )


class MailchimpGetAutomationConfig(BaseModel):
    """Get information about a specific automation workflow."""

    operation: Literal["fetch_automation_workflow"] = Field(
        "fetch_automation_workflow",
        json_schema_extra={
            "const": "fetch_automation_workflow",
            "ui:hidden": True,
            "x-category": "Automation",
            "x-is-trigger": False,
            "x-display-name": "Fetch Automation Workflow",
        },
        title="Fetch Automation Workflow",
    )
    workflow_id: str = Field(..., title="Workflow ID")


class MailchimpPauseAutomationConfig(BaseModel):
    """Pause all emails in an automation workflow."""

    operation: Literal["pause_automation_workflow"] = Field(
        "pause_automation_workflow",
        json_schema_extra={
            "const": "pause_automation_workflow",
            "ui:hidden": True,
            "x-category": "Automation",
            "x-is-trigger": False,
            "x-display-name": "Pause Automation Workflow",
        },
        title="Pause Automation Workflow",
    )
    workflow_id: str = Field(..., title="Workflow ID")


class MailchimpStartAutomationConfig(BaseModel):
    """Start all emails in an automation workflow."""

    operation: Literal["start_automation_workflow"] = Field(
        "start_automation_workflow",
        json_schema_extra={
            "const": "start_automation_workflow",
            "ui:hidden": True,
            "x-category": "Automation",
            "x-is-trigger": False,
            "x-display-name": "Start Automation Workflow",
        },
        title="Start Automation Workflow",
    )
    workflow_id: str = Field(..., title="Workflow ID")


# ============================================================================
# TAGS OPERATIONS (3 operations)
# ============================================================================


class MailchimpGetMemberTagsConfig(BaseModel):
    """Get tags assigned to a list member."""

    operation: Literal["list_member_tags"] = Field(
        "list_member_tags",
        json_schema_extra={
            "const": "list_member_tags",
            "ui:hidden": True,
            "x-category": "Member",
            "x-is-trigger": False,
            "x-display-name": "List Member Tags",
        },
        title="List Member Tags",
    )
    list_id: str = Field(..., title="List ID")
    email_address: str = Field(
        ..., title="Email Address", description="Member email address"
    )
    count: int = Field(
        10, title="Count", description="Number of records to return", ge=1, le=1000
    )
    offset: int = Field(
        0, title="Offset", description="Number of records to skip", ge=0
    )


class MailchimpAddOrRemoveMemberTagsConfig(BaseModel):
    """Add or remove tags from a list member."""

    operation: Literal["update_member_tags"] = Field(
        "update_member_tags",
        json_schema_extra={
            "const": "update_member_tags",
            "ui:hidden": True,
            "x-category": "Member",
            "x-is-trigger": False,
            "x-display-name": "Update Member Tags",
        },
        title="Update Member Tags",
    )
    list_id: str = Field(..., title="List ID")
    email_address: str = Field(..., title="Email Address")
    tags: List[Dict[str, str]] = Field(
        ...,
        title="Tags",
        description="Array of tag objects with 'name' and 'status' (active/inactive). Example: [{'name': 'VIP', 'status': 'active'}]",
        json_schema_extra={"ui:widget": "textarea"},
    )


class MailchimpSearchTagsConfig(BaseModel):
    """Search for tags by name in a list."""

    operation: Literal["search_list_tags"] = Field(
        "search_list_tags",
        json_schema_extra={
            "const": "search_list_tags",
            "ui:hidden": True,
            "x-category": "Mandrill Tag",
            "x-is-trigger": False,
            "x-display-name": "Search List Tags",
        },
        title="Search List Tags",
    )
    list_id: str = Field(..., title="List ID")
    name: str = Field(..., title="Tag Name", description="Search query for tag name")


# ============================================================================
# SEGMENTS OPERATIONS (6 operations)
# ============================================================================


class MailchimpListSegmentsConfig(BaseModel):
    """Get all segments in a list."""

    operation: Literal["list_list_segments"] = Field(
        "list_list_segments",
        json_schema_extra={
            "const": "list_list_segments",
            "ui:hidden": True,
            "x-category": "Segment",
            "x-is-trigger": False,
            "x-display-name": "List List Segments",
        },
        title="List List Segments",
    )
    list_id: str = Field(..., title="List ID")
    count: int = Field(10, title="Count", ge=1, le=1000)
    offset: int = Field(0, title="Offset", ge=0)
    type: Optional[Literal["saved", "static", "fuzzy"]] = Field(
        None, title="Segment Type Filter"
    )


class MailchimpGetSegmentConfig(BaseModel):
    """Get information about a specific segment."""

    operation: Literal["fetch_list_segment"] = Field(
        "fetch_list_segment",
        json_schema_extra={
            "const": "fetch_list_segment",
            "ui:hidden": True,
            "x-category": "Segment",
            "x-is-trigger": False,
            "x-display-name": "Fetch List Segment",
        },
        title="Fetch List Segment",
    )
    list_id: str = Field(..., title="List ID")
    segment_id: str = Field(..., title="Segment ID")
    include_cleaned: bool = Field(
        False, title="Include Cleaned", description="Include cleaned members in count"
    )
    include_transactional: bool = Field(
        False,
        title="Include Transactional",
        description="Include transactional members",
    )
    include_unsubscribed: bool = Field(
        False, title="Include Unsubscribed", description="Include unsubscribed members"
    )


class MailchimpCreateSegmentConfig(BaseModel):
    """Create a new segment in a list."""

    operation: Literal["create_list_segment"] = Field(
        "create_list_segment",
        json_schema_extra={
            "const": "create_list_segment",
            "ui:hidden": True,
            "x-category": "Segment",
            "x-is-trigger": False,
            "x-display-name": "Create List Segment",
        },
        title="Create List Segment",
    )
    list_id: str = Field(..., title="List ID")
    name: str = Field(..., title="Segment Name")
    static_segment: Optional[List[str]] = Field(
        None,
        title="Static Segment",
        description="Array of email addresses for static segment",
        json_schema_extra={"ui:widget": "textarea"},
    )
    options: Optional[Dict[str, Any]] = Field(
        None,
        title="Segment Options",
        description="Conditions for saved/dynamic segment (see Mailchimp API docs)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class MailchimpUpdateSegmentConfig(BaseModel):
    """Update a segment."""

    operation: Literal["update_list_segment"] = Field(
        "update_list_segment",
        json_schema_extra={
            "const": "update_list_segment",
            "ui:hidden": True,
            "x-category": "Segment",
            "x-is-trigger": False,
            "x-display-name": "Update List Segment",
        },
        title="Update List Segment",
    )
    list_id: str = Field(..., title="List ID")
    segment_id: str = Field(..., title="Segment ID")
    name: Optional[str] = Field(None, title="Segment Name")
    static_segment: Optional[List[str]] = Field(
        None,
        title="Static Segment",
        description="Update email addresses for static segment",
        json_schema_extra={"ui:widget": "textarea"},
    )


class MailchimpDeleteSegmentConfig(BaseModel):
    """Delete a segment."""

    operation: Literal["delete_list_segment"] = Field(
        "delete_list_segment",
        json_schema_extra={
            "const": "delete_list_segment",
            "ui:hidden": True,
            "x-category": "Segment",
            "x-is-trigger": False,
            "x-display-name": "Delete List Segment",
        },
        title="Delete List Segment",
    )
    list_id: str = Field(..., title="List ID")
    segment_id: str = Field(..., title="Segment ID")


class MailchimpBatchAddRemoveSegmentMembersConfig(BaseModel):
    """Batch add or remove members from a static segment."""

    operation: Literal["update_segment_members_batch"] = Field(
        "update_segment_members_batch",
        json_schema_extra={
            "const": "update_segment_members_batch",
            "ui:hidden": True,
            "x-category": "Segment",
            "x-is-trigger": False,
            "x-display-name": "Update Segment Members Batch",
        },
        title="Update Segment Members Batch",
    )
    list_id: str = Field(..., title="List ID")
    segment_id: str = Field(
        ..., title="Segment ID", description="Must be a static segment"
    )
    members_to_add: Optional[List[str]] = Field(
        None,
        title="Members to Add",
        description="Array of email addresses to add",
        json_schema_extra={"ui:widget": "textarea"},
    )
    members_to_remove: Optional[List[str]] = Field(
        None,
        title="Members to Remove",
        description="Array of email addresses to remove",
        json_schema_extra={"ui:widget": "textarea"},
    )


# ============================================================================
# MERGE FIELDS OPERATIONS (5 operations)
# ============================================================================


class MailchimpListMergeFieldsConfig(BaseModel):
    """Get all merge fields for a list."""

    operation: Literal["list_merge_fields"] = Field(
        "list_merge_fields",
        json_schema_extra={
            "const": "list_merge_fields",
            "ui:hidden": True,
            "x-category": "Merge Field",
            "x-is-trigger": False,
            "x-display-name": "List Merge Fields",
        },
        title="List Merge Fields",
    )
    list_id: str = Field(..., title="List ID")
    count: int = Field(10, title="Count", ge=1, le=1000)
    offset: int = Field(0, title="Offset", ge=0)
    type: Optional[
        Literal[
            "text",
            "number",
            "address",
            "phone",
            "date",
            "url",
            "imageurl",
            "radio",
            "dropdown",
            "birthday",
            "zip",
        ]
    ] = Field(None, title="Field Type Filter")
    required: Optional[bool] = Field(
        None, title="Required Filter", description="Filter by required status"
    )


class MailchimpGetMergeFieldConfig(BaseModel):
    """Get information about a specific merge field."""

    operation: Literal["fetch_merge_field"] = Field(
        "fetch_merge_field",
        json_schema_extra={
            "const": "fetch_merge_field",
            "ui:hidden": True,
            "x-category": "Merge Field",
            "x-is-trigger": False,
            "x-display-name": "Fetch Merge Field",
        },
        title="Fetch Merge Field",
    )
    list_id: str = Field(..., title="List ID")
    merge_id: str = Field(..., title="Merge Field ID")


class MailchimpAddMergeFieldConfig(BaseModel):
    """Add a new merge field to a list."""

    operation: Literal["create_merge_field"] = Field(
        "create_merge_field",
        json_schema_extra={
            "const": "create_merge_field",
            "ui:hidden": True,
            "x-category": "Merge Field",
            "x-is-trigger": False,
            "x-display-name": "Create Merge Field",
        },
        title="Create Merge Field",
    )
    list_id: str = Field(..., title="List ID")
    name: str = Field(
        ..., title="Field Name", description="Display name (e.g., 'First Name')"
    )
    type: Literal[
        "text",
        "number",
        "address",
        "phone",
        "date",
        "url",
        "imageurl",
        "radio",
        "dropdown",
        "birthday",
        "zip",
    ] = Field(..., title="Field Type")
    tag: Optional[str] = Field(
        None,
        title="Merge Tag",
        description="Merge tag (e.g., 'FNAME'). Auto-generated if not provided",
    )
    required: bool = Field(
        False, title="Required", description="Is this field required?"
    )
    default_value: Optional[str] = Field(None, title="Default Value")
    public: bool = Field(True, title="Public", description="Show on signup forms")
    display_order: Optional[int] = Field(
        None, title="Display Order", description="Order in forms"
    )
    options: Optional[Dict[str, Any]] = Field(
        None,
        title="Field Options",
        description="Additional options (choices for dropdown/radio, etc.)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    helptext: Optional[str] = Field(
        None, title="Help Text", description="Help text shown on forms"
    )


class MailchimpUpdateMergeFieldConfig(BaseModel):
    """Update a merge field."""

    operation: Literal["update_merge_field"] = Field(
        "update_merge_field",
        json_schema_extra={
            "const": "update_merge_field",
            "ui:hidden": True,
            "x-category": "Merge Field",
            "x-is-trigger": False,
            "x-display-name": "Update Merge Field",
        },
        title="Update Merge Field",
    )
    list_id: str = Field(..., title="List ID")
    merge_id: str = Field(..., title="Merge Field ID")
    name: Optional[str] = Field(None, title="Field Name")
    tag: Optional[str] = Field(None, title="Merge Tag")
    required: Optional[bool] = Field(None, title="Required")
    default_value: Optional[str] = Field(None, title="Default Value")
    public: Optional[bool] = Field(None, title="Public")
    display_order: Optional[int] = Field(None, title="Display Order")
    options: Optional[Dict[str, Any]] = Field(
        None, title="Field Options", json_schema_extra={"ui:widget": "textarea"}
    )
    helptext: Optional[str] = Field(None, title="Help Text")


class MailchimpDeleteMergeFieldConfig(BaseModel):
    """Delete a merge field."""

    operation: Literal["delete_merge_field"] = Field(
        "delete_merge_field",
        json_schema_extra={
            "const": "delete_merge_field",
            "ui:hidden": True,
            "x-category": "Merge Field",
            "x-is-trigger": False,
            "x-display-name": "Delete Merge Field",
        },
        title="Delete Merge Field",
    )
    list_id: str = Field(..., title="List ID")
    merge_id: str = Field(..., title="Merge Field ID")


# ============================================================================
# INTEREST CATEGORIES OPERATIONS (5 operations)
# ============================================================================


class MailchimpListInterestCategoriesConfig(BaseModel):
    """Get all interest categories for a list."""

    operation: Literal["list_interest_categories"] = Field(
        "list_interest_categories",
        json_schema_extra={
            "const": "list_interest_categories",
            "ui:hidden": True,
            "x-category": "Interest",
            "x-is-trigger": False,
            "x-display-name": "List Interest Categories",
        },
        title="List Interest Categories",
    )
    list_id: str = Field(..., title="List ID")
    count: int = Field(10, title="Count", ge=1, le=1000)
    offset: int = Field(0, title="Offset", ge=0)
    type: Optional[Literal["checkboxes", "dropdown", "radio", "hidden"]] = Field(
        None, title="Category Type Filter"
    )


class MailchimpGetInterestCategoryConfig(BaseModel):
    """Get information about a specific interest category."""

    operation: Literal["fetch_interest_category"] = Field(
        "fetch_interest_category",
        json_schema_extra={
            "const": "fetch_interest_category",
            "ui:hidden": True,
            "x-category": "Interest",
            "x-is-trigger": False,
            "x-display-name": "Fetch Interest Category",
        },
        title="Fetch Interest Category",
    )
    list_id: str = Field(..., title="List ID")
    interest_category_id: str = Field(..., title="Interest Category ID")


class MailchimpCreateInterestCategoryConfig(BaseModel):
    """Create a new interest category."""

    operation: Literal["create_interest_category"] = Field(
        "create_interest_category",
        json_schema_extra={
            "const": "create_interest_category",
            "ui:hidden": True,
            "x-category": "Interest",
            "x-is-trigger": False,
            "x-display-name": "Create Interest Category",
        },
        title="Create Interest Category",
    )
    list_id: str = Field(..., title="List ID")
    title: str = Field(
        ..., title="Category Title", description="Display name (e.g., 'Interests')"
    )
    type: Literal["checkboxes", "dropdown", "radio", "hidden"] = Field(
        "checkboxes",
        title="Category Type",
        description="How interests are displayed in forms",
    )
    display_order: Optional[int] = Field(
        None, title="Display Order", description="Order in forms"
    )


class MailchimpUpdateInterestCategoryConfig(BaseModel):
    """Update an interest category."""

    operation: Literal["update_interest_category"] = Field(
        "update_interest_category",
        json_schema_extra={
            "const": "update_interest_category",
            "ui:hidden": True,
            "x-category": "Interest",
            "x-is-trigger": False,
            "x-display-name": "Update Interest Category",
        },
        title="Update Interest Category",
    )
    list_id: str = Field(..., title="List ID")
    interest_category_id: str = Field(..., title="Interest Category ID")
    title: Optional[str] = Field(None, title="Category Title")
    type: Optional[Literal["checkboxes", "dropdown", "radio", "hidden"]] = Field(
        None, title="Category Type"
    )
    display_order: Optional[int] = Field(None, title="Display Order")


class MailchimpDeleteInterestCategoryConfig(BaseModel):
    """Delete an interest category."""

    operation: Literal["delete_interest_category"] = Field(
        "delete_interest_category",
        json_schema_extra={
            "const": "delete_interest_category",
            "ui:hidden": True,
            "x-category": "Interest",
            "x-is-trigger": False,
            "x-display-name": "Delete Interest Category",
        },
        title="Delete Interest Category",
    )
    list_id: str = Field(..., title="List ID")
    interest_category_id: str = Field(..., title="Interest Category ID")


# ============================================================================
# INTERESTS OPERATIONS (5 operations)
# ============================================================================


class MailchimpListInterestsConfig(BaseModel):
    """Get all interests in an interest category."""

    operation: Literal["list_category_interests"] = Field(
        "list_category_interests",
        json_schema_extra={
            "const": "list_category_interests",
            "ui:hidden": True,
            "x-category": "Interest",
            "x-is-trigger": False,
            "x-display-name": "List Category Interests",
        },
        title="List Category Interests",
    )
    list_id: str = Field(..., title="List ID")
    interest_category_id: str = Field(..., title="Interest Category ID")
    count: int = Field(10, title="Count", ge=1, le=1000)
    offset: int = Field(0, title="Offset", ge=0)


class MailchimpGetInterestConfig(BaseModel):
    """Get information about a specific interest."""

    operation: Literal["fetch_category_interest"] = Field(
        "fetch_category_interest",
        json_schema_extra={
            "const": "fetch_category_interest",
            "ui:hidden": True,
            "x-category": "Interest",
            "x-is-trigger": False,
            "x-display-name": "Fetch Category Interest",
        },
        title="Fetch Category Interest",
    )
    list_id: str = Field(..., title="List ID")
    interest_category_id: str = Field(..., title="Interest Category ID")
    interest_id: str = Field(..., title="Interest ID")


class MailchimpCreateInterestConfig(BaseModel):
    """Create a new interest in an interest category."""

    operation: Literal["create_category_interest"] = Field(
        "create_category_interest",
        json_schema_extra={
            "const": "create_category_interest",
            "ui:hidden": True,
            "x-category": "Interest",
            "x-is-trigger": False,
            "x-display-name": "Create Category Interest",
        },
        title="Create Category Interest",
    )
    list_id: str = Field(..., title="List ID")
    interest_category_id: str = Field(..., title="Interest Category ID")
    name: str = Field(
        ..., title="Interest Name", description="Display name (e.g., 'Product Updates')"
    )
    display_order: Optional[int] = Field(
        None, title="Display Order", description="Order in forms"
    )


class MailchimpUpdateInterestConfig(BaseModel):
    """Update an interest."""

    operation: Literal["update_category_interest"] = Field(
        "update_category_interest",
        json_schema_extra={
            "const": "update_category_interest",
            "ui:hidden": True,
            "x-category": "Interest",
            "x-is-trigger": False,
            "x-display-name": "Update Category Interest",
        },
        title="Update Category Interest",
    )
    list_id: str = Field(..., title="List ID")
    interest_category_id: str = Field(..., title="Interest Category ID")
    interest_id: str = Field(..., title="Interest ID")
    name: Optional[str] = Field(None, title="Interest Name")
    display_order: Optional[int] = Field(None, title="Display Order")


class MailchimpDeleteInterestConfig(BaseModel):
    """Delete an interest."""

    operation: Literal["delete_category_interest"] = Field(
        "delete_category_interest",
        json_schema_extra={
            "const": "delete_category_interest",
            "ui:hidden": True,
            "x-category": "Interest",
            "x-is-trigger": False,
            "x-display-name": "Delete Category Interest",
        },
        title="Delete Category Interest",
    )
    list_id: str = Field(..., title="List ID")
    interest_category_id: str = Field(..., title="Interest Category ID")
    interest_id: str = Field(..., title="Interest ID")


# ============================================================================
# TEMPLATES OPERATIONS (5 operations)
# ============================================================================


class MailchimpListTemplatesConfig(BaseModel):
    """Get all templates in the account."""

    operation: Literal["list_email_templates"] = Field(
        "list_email_templates",
        json_schema_extra={
            "const": "list_email_templates",
            "ui:hidden": True,
            "x-category": "Template",
            "x-is-trigger": False,
            "x-display-name": "List Email Templates",
        },
        title="List Email Templates",
    )
    count: int = Field(10, title="Count", ge=1, le=1000)
    offset: int = Field(0, title="Offset", ge=0)
    type: Optional[Literal["user", "base", "gallery"]] = Field(
        None, title="Template Type Filter"
    )
    category: Optional[str] = Field(
        None, title="Category Filter", description="Filter by template category"
    )
    folder_id: Optional[str] = Field(
        None, title="Folder ID", description="Filter by folder"
    )
    sort_field: Optional[Literal["date_created", "date_edited", "name"]] = Field(
        None, title="Sort Field"
    )
    sort_dir: Optional[Literal["ASC", "DESC"]] = Field(None, title="Sort Direction")


class MailchimpGetTemplateConfig(BaseModel):
    """Get information about a specific template."""

    operation: Literal["fetch_email_template"] = Field(
        "fetch_email_template",
        json_schema_extra={
            "const": "fetch_email_template",
            "ui:hidden": True,
            "x-category": "Template",
            "x-is-trigger": False,
            "x-display-name": "Fetch Email Template",
        },
        title="Fetch Email Template",
    )
    template_id: str = Field(..., title="Template ID")


class MailchimpCreateTemplateConfig(BaseModel):
    """Create a new template."""

    operation: Literal["create_email_template"] = Field(
        "create_email_template",
        json_schema_extra={
            "const": "create_email_template",
            "ui:hidden": True,
            "x-category": "Template",
            "x-is-trigger": False,
            "x-display-name": "Create Email Template",
        },
        title="Create Email Template",
    )
    name: str = Field(..., title="Template Name")
    html: str = Field(
        ...,
        title="HTML Content",
        description="Full HTML content of the template",
        json_schema_extra={"ui:widget": "textarea"},
    )
    folder_id: Optional[str] = Field(
        None, title="Folder ID", description="Store in specific folder"
    )


class MailchimpUpdateTemplateConfig(BaseModel):
    """Update a template."""

    operation: Literal["update_email_template"] = Field(
        "update_email_template",
        json_schema_extra={
            "const": "update_email_template",
            "ui:hidden": True,
            "x-category": "Template",
            "x-is-trigger": False,
            "x-display-name": "Update Email Template",
        },
        title="Update Email Template",
    )
    template_id: str = Field(..., title="Template ID")
    name: Optional[str] = Field(None, title="Template Name")
    html: Optional[str] = Field(
        None, title="HTML Content", json_schema_extra={"ui:widget": "textarea"}
    )
    folder_id: Optional[str] = Field(None, title="Folder ID")


class MailchimpDeleteTemplateConfig(BaseModel):
    """Delete a template."""

    operation: Literal["delete_email_template"] = Field(
        "delete_email_template",
        json_schema_extra={
            "const": "delete_email_template",
            "ui:hidden": True,
            "x-category": "Template",
            "x-is-trigger": False,
            "x-display-name": "Delete Email Template",
        },
        title="Delete Email Template",
    )
    template_id: str = Field(..., title="Template ID")


# ============================================================================
# REPORTS OPERATIONS - Campaign Analytics (15+ operations)
# ============================================================================


class MailchimpListCampaignReportsConfig(BaseModel):
    """Get all campaign reports."""

    operation: Literal["list_campaign_reports"] = Field(
        "list_campaign_reports",
        json_schema_extra={
            "const": "list_campaign_reports",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "List Campaign Reports",
        },
        title="List Campaign Reports",
    )
    count: int = Field(
        10, title="Count", description="Number of records to return", ge=1, le=1000
    )
    offset: int = Field(
        0, title="Offset", description="Number of records to skip", ge=0
    )
    type: Optional[
        Literal["regular", "plaintext", "absplit", "rss", "variate"]
    ] = Field(None, title="Campaign Type Filter")
    before_send_time: Optional[str] = Field(
        None, title="Before Send Time", description="ISO 8601 datetime"
    )
    since_send_time: Optional[str] = Field(
        None, title="Since Send Time", description="ISO 8601 datetime"
    )


class MailchimpGetCampaignReportConfig(BaseModel):
    """Get report for a specific campaign."""

    operation: Literal["fetch_campaign_report"] = Field(
        "fetch_campaign_report",
        json_schema_extra={
            "const": "fetch_campaign_report",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Fetch Campaign Report",
        },
        title="Fetch Campaign Report",
    )
    campaign_id: str = Field(..., title="Campaign ID")


class MailchimpGetCampaignEmailActivityConfig(BaseModel):
    """Get email activity for a campaign."""

    operation: Literal["fetch_campaign_email_activity"] = Field(
        "fetch_campaign_email_activity",
        json_schema_extra={
            "const": "fetch_campaign_email_activity",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Fetch Campaign Email Activity",
        },
        title="Fetch Campaign Email Activity",
    )
    campaign_id: str = Field(..., title="Campaign ID")
    count: int = Field(10, title="Count", ge=1, le=1000)
    offset: int = Field(0, title="Offset", ge=0)
    since: Optional[str] = Field(
        None,
        title="Since",
        description="ISO 8601 datetime - only activity after this time",
    )


class MailchimpGetCampaignAbuseReportsConfig(BaseModel):
    """Get abuse reports for a campaign."""

    operation: Literal["list_campaign_abuse_reports"] = Field(
        "list_campaign_abuse_reports",
        json_schema_extra={
            "const": "list_campaign_abuse_reports",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "List Campaign Abuse Reports",
        },
        title="List Campaign Abuse Reports",
    )
    campaign_id: str = Field(..., title="Campaign ID")
    count: int = Field(10, title="Count", ge=1, le=1000)
    offset: int = Field(0, title="Offset", ge=0)


class MailchimpGetCampaignAbuseReportConfig(BaseModel):
    """Get a specific abuse report."""

    operation: Literal["fetch_campaign_abuse_report"] = Field(
        "fetch_campaign_abuse_report",
        json_schema_extra={
            "const": "fetch_campaign_abuse_report",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Fetch Campaign Abuse Report",
        },
        title="Fetch Campaign Abuse Report",
    )
    campaign_id: str = Field(..., title="Campaign ID")
    report_id: str = Field(..., title="Report ID")


class MailchimpGetCampaignClickDetailsConfig(BaseModel):
    """Get click details for a campaign."""

    operation: Literal["fetch_campaign_click_details"] = Field(
        "fetch_campaign_click_details",
        json_schema_extra={
            "const": "fetch_campaign_click_details",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Fetch Campaign Click Details",
        },
        title="Fetch Campaign Click Details",
    )
    campaign_id: str = Field(..., title="Campaign ID")
    count: int = Field(10, title="Count", ge=1, le=1000)
    offset: int = Field(0, title="Offset", ge=0)


class MailchimpGetCampaignClickDetailsForLinkConfig(BaseModel):
    """Get click details for a specific link."""

    operation: Literal["fetch_link_click_details"] = Field(
        "fetch_link_click_details",
        json_schema_extra={
            "const": "fetch_link_click_details",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Fetch Link Click Details",
        },
        title="Fetch Link Click Details",
    )
    campaign_id: str = Field(..., title="Campaign ID")
    link_id: str = Field(..., title="Link ID")
    count: int = Field(10, title="Count", ge=1, le=1000)
    offset: int = Field(0, title="Offset", ge=0)


class MailchimpGetCampaignClickDetailMembersConfig(BaseModel):
    """Get members who clicked a specific link."""

    operation: Literal["list_members_who_clicked_link"] = Field(
        "list_members_who_clicked_link",
        json_schema_extra={
            "const": "list_members_who_clicked_link",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "List Members Who Clicked Link",
        },
        title="List Members Who Clicked Link",
    )
    campaign_id: str = Field(..., title="Campaign ID")
    link_id: str = Field(..., title="Link ID")
    count: int = Field(10, title="Count", ge=1, le=1000)
    offset: int = Field(0, title="Offset", ge=0)


class MailchimpGetCampaignDomainPerformanceConfig(BaseModel):
    """Get domain performance stats for a campaign."""

    operation: Literal["fetch_campaign_domain_performance"] = Field(
        "fetch_campaign_domain_performance",
        json_schema_extra={
            "const": "fetch_campaign_domain_performance",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Fetch Campaign Domain Performance",
        },
        title="Fetch Campaign Domain Performance",
    )
    campaign_id: str = Field(..., title="Campaign ID")


class MailchimpGetCampaignEepURLActivityConfig(BaseModel):
    """Get EepURL activity for a campaign."""

    operation: Literal["fetch_campaign_eepurl_activity"] = Field(
        "fetch_campaign_eepurl_activity",
        json_schema_extra={
            "const": "fetch_campaign_eepurl_activity",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Fetch Campaign Eepurl Activity",
        },
        title="Fetch Campaign Eepurl Activity",
    )
    campaign_id: str = Field(..., title="Campaign ID")


class MailchimpGetCampaignLocationsConfig(BaseModel):
    """Get top locations for a campaign."""

    operation: Literal["fetch_campaign_top_locations"] = Field(
        "fetch_campaign_top_locations",
        json_schema_extra={
            "const": "fetch_campaign_top_locations",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Fetch Campaign Top Locations",
        },
        title="Fetch Campaign Top Locations",
    )
    campaign_id: str = Field(..., title="Campaign ID")
    count: int = Field(10, title="Count", ge=1, le=1000)
    offset: int = Field(0, title="Offset", ge=0)


class MailchimpGetCampaignSentToConfig(BaseModel):
    """Get list of subscribers a campaign was sent to."""

    operation: Literal["list_campaign_recipients"] = Field(
        "list_campaign_recipients",
        json_schema_extra={
            "const": "list_campaign_recipients",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "List Campaign Recipients",
        },
        title="List Campaign Recipients",
    )
    campaign_id: str = Field(..., title="Campaign ID")
    count: int = Field(10, title="Count", ge=1, le=1000)
    offset: int = Field(0, title="Offset", ge=0)


class MailchimpGetCampaignUnsubscribesConfig(BaseModel):
    """Get unsubscribed members from a campaign."""

    operation: Literal["list_campaign_unsubscribes"] = Field(
        "list_campaign_unsubscribes",
        json_schema_extra={
            "const": "list_campaign_unsubscribes",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "List Campaign Unsubscribes",
        },
        title="List Campaign Unsubscribes",
    )
    campaign_id: str = Field(..., title="Campaign ID")
    count: int = Field(10, title="Count", ge=1, le=1000)
    offset: int = Field(0, title="Offset", ge=0)


class MailchimpGetCampaignOpensConfig(BaseModel):
    """Get all opens for a campaign."""

    operation: Literal["fetch_campaign_opens"] = Field(
        "fetch_campaign_opens",
        json_schema_extra={
            "const": "fetch_campaign_opens",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Fetch Campaign Opens",
        },
        title="Fetch Campaign Opens",
    )
    campaign_id: str = Field(..., title="Campaign ID")
    count: int = Field(10, title="Count", ge=1, le=1000)
    offset: int = Field(0, title="Offset", ge=0)
    since: Optional[str] = Field(None, title="Since", description="ISO 8601 datetime")


class MailchimpGetMemberCampaignOpenConfig(BaseModel):
    """Get opens by a specific member."""

    operation: Literal["fetch_member_campaign_opens"] = Field(
        "fetch_member_campaign_opens",
        json_schema_extra={
            "const": "fetch_member_campaign_opens",
            "ui:hidden": True,
            "x-category": "Member",
            "x-is-trigger": False,
            "x-display-name": "Fetch Member Campaign Opens",
        },
        title="Fetch Member Campaign Opens",
    )
    campaign_id: str = Field(..., title="Campaign ID")
    email_address: str = Field(
        ..., title="Email Address", description="Member email address"
    )


# ============================================================================
# E-COMMERCE STORES OPERATIONS (5 operations)
# ============================================================================


class MailchimpListEcommerceStoresConfig(BaseModel):
    """Get all e-commerce stores."""

    operation: Literal["list_ecommerce_stores"] = Field(
        "list_ecommerce_stores",
        json_schema_extra={
            "const": "list_ecommerce_stores",
            "ui:hidden": True,
            "x-category": "E-commerce Store",
            "x-is-trigger": False,
            "x-display-name": "List Ecommerce Stores",
        },
        title="List Ecommerce Stores",
    )
    count: int = Field(10, title="Count", ge=1, le=1000)
    offset: int = Field(0, title="Offset", ge=0)


class MailchimpGetEcommerceStoreConfig(BaseModel):
    """Get information about a specific store."""

    operation: Literal["fetch_ecommerce_store"] = Field(
        "fetch_ecommerce_store",
        json_schema_extra={
            "const": "fetch_ecommerce_store",
            "ui:hidden": True,
            "x-category": "E-commerce Store",
            "x-is-trigger": False,
            "x-display-name": "Fetch Ecommerce Store",
        },
        title="Fetch Ecommerce Store",
    )
    store_id: str = Field(..., title="Store ID")


class MailchimpAddEcommerceStoreConfig(BaseModel):
    """Add a new e-commerce store."""

    operation: Literal["create_ecommerce_store"] = Field(
        "create_ecommerce_store",
        json_schema_extra={
            "const": "create_ecommerce_store",
            "ui:hidden": True,
            "x-category": "E-commerce Store",
            "x-is-trigger": False,
            "x-display-name": "Create Ecommerce Store",
        },
        title="Create Ecommerce Store",
    )
    id: str = Field(
        ..., title="Store ID", description="Unique identifier for the store"
    )
    list_id: str = Field(
        ..., title="List ID", description="List associated with the store"
    )
    name: str = Field(..., title="Store Name")
    currency_code: str = Field(
        ...,
        title="Currency Code",
        description="Three-letter ISO 4217 code (e.g., USD, EUR)",
    )
    domain: Optional[str] = Field(None, title="Domain", description="Store domain")
    email_address: Optional[str] = Field(
        None, title="Email Address", description="Store email"
    )
    phone: Optional[str] = Field(None, title="Phone", description="Store phone number")
    address: Optional[Dict[str, str]] = Field(
        None,
        title="Address",
        description="Store address object",
        json_schema_extra={"ui:widget": "textarea"},
    )


class MailchimpUpdateEcommerceStoreConfig(BaseModel):
    """Update an e-commerce store."""

    operation: Literal["update_ecommerce_store"] = Field(
        "update_ecommerce_store",
        json_schema_extra={
            "const": "update_ecommerce_store",
            "ui:hidden": True,
            "x-category": "E-commerce Store",
            "x-is-trigger": False,
            "x-display-name": "Update Ecommerce Store",
        },
        title="Update Ecommerce Store",
    )
    store_id: str = Field(..., title="Store ID")
    name: Optional[str] = Field(None, title="Store Name")
    currency_code: Optional[str] = Field(None, title="Currency Code")
    domain: Optional[str] = Field(None, title="Domain")
    email_address: Optional[str] = Field(None, title="Email Address")
    phone: Optional[str] = Field(None, title="Phone")


class MailchimpDeleteEcommerceStoreConfig(BaseModel):
    """Delete an e-commerce store."""

    operation: Literal["delete_ecommerce_store"] = Field(
        "delete_ecommerce_store",
        json_schema_extra={
            "const": "delete_ecommerce_store",
            "ui:hidden": True,
            "x-category": "E-commerce Store",
            "x-is-trigger": False,
            "x-display-name": "Delete Ecommerce Store",
        },
        title="Delete Ecommerce Store",
    )
    store_id: str = Field(..., title="Store ID")


# ============================================================================
# E-COMMERCE PRODUCTS OPERATIONS (9 operations)
# ============================================================================


class MailchimpListEcommerceProductsConfig(BaseModel):
    """Get all products in a store."""

    operation: Literal["list_ecommerce_products"] = Field(
        "list_ecommerce_products",
        json_schema_extra={
            "const": "list_ecommerce_products",
            "ui:hidden": True,
            "x-category": "E-commerce Product",
            "x-is-trigger": False,
            "x-display-name": "List Ecommerce Products",
        },
        title="List Ecommerce Products",
    )
    store_id: str = Field(..., title="Store ID")
    count: int = Field(10, title="Count", ge=1, le=1000)
    offset: int = Field(0, title="Offset", ge=0)


class MailchimpGetEcommerceProductConfig(BaseModel):
    """Get information about a specific product."""

    operation: Literal["fetch_ecommerce_product"] = Field(
        "fetch_ecommerce_product",
        json_schema_extra={
            "const": "fetch_ecommerce_product",
            "ui:hidden": True,
            "x-category": "E-commerce Product",
            "x-is-trigger": False,
            "x-display-name": "Fetch Ecommerce Product",
        },
        title="Fetch Ecommerce Product",
    )
    store_id: str = Field(..., title="Store ID")
    product_id: str = Field(..., title="Product ID")


class MailchimpAddEcommerceProductConfig(BaseModel):
    """Add a new product to a store."""

    operation: Literal["create_ecommerce_product"] = Field(
        "create_ecommerce_product",
        json_schema_extra={
            "const": "create_ecommerce_product",
            "ui:hidden": True,
            "x-category": "E-commerce Product",
            "x-is-trigger": False,
            "x-display-name": "Create Ecommerce Product",
        },
        title="Create Ecommerce Product",
    )
    store_id: str = Field(..., title="Store ID")
    id: str = Field(
        ..., title="Product ID", description="Unique identifier for the product"
    )
    title: str = Field(..., title="Product Title")
    description: Optional[str] = Field(None, title="Description")
    type: Optional[str] = Field(
        None, title="Product Type", description="e.g., physical, digital"
    )
    vendor: Optional[str] = Field(
        None, title="Vendor", description="Product vendor/brand"
    )
    url: Optional[str] = Field(None, title="Product URL")
    image_url: Optional[str] = Field(
        None,
        title="Image URL",
        description="The image to send — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}).",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": "image/*"},
    )
    published_at_foreign: Optional[str] = Field(
        None, title="Published At", description="ISO 8601 datetime"
    )
    variants: Optional[List[Dict[str, Any]]] = Field(
        None,
        title="Product Variants",
        description="Array of variant objects",
        json_schema_extra={"ui:widget": "textarea"},
    )


class MailchimpUpdateEcommerceProductConfig(BaseModel):
    """Update a product."""

    operation: Literal["update_ecommerce_product"] = Field(
        "update_ecommerce_product",
        json_schema_extra={
            "const": "update_ecommerce_product",
            "ui:hidden": True,
            "x-category": "E-commerce Product",
            "x-is-trigger": False,
            "x-display-name": "Update Ecommerce Product",
        },
        title="Update Ecommerce Product",
    )
    store_id: str = Field(..., title="Store ID")
    product_id: str = Field(..., title="Product ID")
    title: Optional[str] = Field(None, title="Product Title")
    description: Optional[str] = Field(None, title="Description")
    type: Optional[str] = Field(None, title="Product Type")
    vendor: Optional[str] = Field(None, title="Vendor")
    url: Optional[str] = Field(None, title="Product URL")
    image_url: Optional[str] = Field(
        None,
        title="Image URL",
        description="The image to send — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}).",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": "image/*"},
    )


class MailchimpDeleteEcommerceProductConfig(BaseModel):
    """Delete a product."""

    operation: Literal["delete_ecommerce_product"] = Field(
        "delete_ecommerce_product",
        json_schema_extra={
            "const": "delete_ecommerce_product",
            "ui:hidden": True,
            "x-category": "E-commerce Product",
            "x-is-trigger": False,
            "x-display-name": "Delete Ecommerce Product",
        },
        title="Delete Ecommerce Product",
    )
    store_id: str = Field(..., title="Store ID")
    product_id: str = Field(..., title="Product ID")


class MailchimpListEcommerceProductVariantsConfig(BaseModel):
    """Get all variants for a product."""

    operation: Literal["list_product_variants"] = Field(
        "list_product_variants",
        json_schema_extra={
            "const": "list_product_variants",
            "ui:hidden": True,
            "x-category": "E-commerce Product",
            "x-is-trigger": False,
            "x-display-name": "List Product Variants",
        },
        title="List Product Variants",
    )
    store_id: str = Field(..., title="Store ID")
    product_id: str = Field(..., title="Product ID")
    count: int = Field(10, title="Count", ge=1, le=1000)
    offset: int = Field(0, title="Offset", ge=0)


class MailchimpGetEcommerceProductVariantConfig(BaseModel):
    """Get information about a specific product variant."""

    operation: Literal["fetch_product_variant"] = Field(
        "fetch_product_variant",
        json_schema_extra={
            "const": "fetch_product_variant",
            "ui:hidden": True,
            "x-category": "E-commerce Product",
            "x-is-trigger": False,
            "x-display-name": "Fetch Product Variant",
        },
        title="Fetch Product Variant",
    )
    store_id: str = Field(..., title="Store ID")
    product_id: str = Field(..., title="Product ID")
    variant_id: str = Field(..., title="Variant ID")


class MailchimpAddEcommerceProductVariantConfig(BaseModel):
    """Add a new variant to a product."""

    operation: Literal["create_product_variant"] = Field(
        "create_product_variant",
        json_schema_extra={
            "const": "create_product_variant",
            "ui:hidden": True,
            "x-category": "E-commerce Product",
            "x-is-trigger": False,
            "x-display-name": "Create Product Variant",
        },
        title="Create Product Variant",
    )
    store_id: str = Field(..., title="Store ID")
    product_id: str = Field(..., title="Product ID")
    id: str = Field(..., title="Variant ID")
    title: str = Field(..., title="Variant Title")
    price: float = Field(..., title="Price", description="Variant price")
    sku: Optional[str] = Field(None, title="SKU")
    inventory_quantity: Optional[int] = Field(None, title="Inventory Quantity")
    image_url: Optional[str] = Field(
        None,
        title="Image URL",
        description="The image to send — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}).",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": "image/*"},
    )
    url: Optional[str] = Field(None, title="Variant URL")


class MailchimpUpdateEcommerceProductVariantConfig(BaseModel):
    """Update a product variant."""

    operation: Literal["update_product_variant"] = Field(
        "update_product_variant",
        json_schema_extra={
            "const": "update_product_variant",
            "ui:hidden": True,
            "x-category": "E-commerce Product",
            "x-is-trigger": False,
            "x-display-name": "Update Product Variant",
        },
        title="Update Product Variant",
    )
    store_id: str = Field(..., title="Store ID")
    product_id: str = Field(..., title="Product ID")
    variant_id: str = Field(..., title="Variant ID")
    title: Optional[str] = Field(None, title="Variant Title")
    price: Optional[float] = Field(None, title="Price")
    sku: Optional[str] = Field(None, title="SKU")
    inventory_quantity: Optional[int] = Field(None, title="Inventory Quantity")
    image_url: Optional[str] = Field(
        None,
        title="Image URL",
        description="The image to send — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}).",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": "image/*"},
    )


# ============================================================================
# E-COMMERCE ORDERS OPERATIONS (7 operations)
# ============================================================================


class MailchimpListEcommerceOrdersConfig(BaseModel):
    """Get all orders for a store."""

    operation: Literal["list_ecommerce_orders"] = Field(
        "list_ecommerce_orders",
        json_schema_extra={
            "const": "list_ecommerce_orders",
            "ui:hidden": True,
            "x-category": "E-commerce Order",
            "x-is-trigger": False,
            "x-display-name": "List Ecommerce Orders",
        },
        title="List Ecommerce Orders",
    )
    store_id: str = Field(..., title="Store ID")
    count: int = Field(10, title="Count", ge=1, le=1000)
    offset: int = Field(0, title="Offset", ge=0)
    customer_id: Optional[str] = Field(None, title="Customer ID Filter")
    has_outreach: Optional[bool] = Field(None, title="Has Outreach Filter")


class MailchimpGetEcommerceOrderConfig(BaseModel):
    """Get information about a specific order."""

    operation: Literal["fetch_ecommerce_order"] = Field(
        "fetch_ecommerce_order",
        json_schema_extra={
            "const": "fetch_ecommerce_order",
            "ui:hidden": True,
            "x-category": "E-commerce Order",
            "x-is-trigger": False,
            "x-display-name": "Fetch Ecommerce Order",
        },
        title="Fetch Ecommerce Order",
    )
    store_id: str = Field(..., title="Store ID")
    order_id: str = Field(..., title="Order ID")


class MailchimpAddEcommerceOrderConfig(BaseModel):
    """Add a new order to a store."""

    operation: Literal["create_ecommerce_order"] = Field(
        "create_ecommerce_order",
        json_schema_extra={
            "const": "create_ecommerce_order",
            "ui:hidden": True,
            "x-category": "E-commerce Order",
            "x-is-trigger": False,
            "x-display-name": "Create Ecommerce Order",
        },
        title="Create Ecommerce Order",
    )
    store_id: str = Field(..., title="Store ID")
    id: str = Field(..., title="Order ID")
    customer: Dict[str, Any] = Field(
        ...,
        title="Customer",
        description="Customer object with id and email_address",
        json_schema_extra={"ui:widget": "textarea"},
    )
    order_total: float = Field(
        ..., title="Order Total", description="Total order amount"
    )
    lines: List[Dict[str, Any]] = Field(
        ...,
        title="Order Lines",
        description="Array of line item objects",
        json_schema_extra={"ui:widget": "textarea"},
    )
    currency_code: Optional[str] = Field(
        None, title="Currency Code", description="Three-letter ISO 4217 code"
    )
    tax_total: Optional[float] = Field(None, title="Tax Total")
    shipping_total: Optional[float] = Field(None, title="Shipping Total")
    processed_at_foreign: Optional[str] = Field(
        None, title="Processed At", description="ISO 8601 datetime"
    )
    updated_at_foreign: Optional[str] = Field(
        None, title="Updated At", description="ISO 8601 datetime"
    )
    campaign_id: Optional[str] = Field(
        None, title="Campaign ID", description="Campaign that generated this order"
    )


class MailchimpUpdateEcommerceOrderConfig(BaseModel):
    """Update an order."""

    operation: Literal["update_ecommerce_order"] = Field(
        "update_ecommerce_order",
        json_schema_extra={
            "const": "update_ecommerce_order",
            "ui:hidden": True,
            "x-category": "E-commerce Order",
            "x-is-trigger": False,
            "x-display-name": "Update Ecommerce Order",
        },
        title="Update Ecommerce Order",
    )
    store_id: str = Field(..., title="Store ID")
    order_id: str = Field(..., title="Order ID")
    customer: Optional[Dict[str, Any]] = Field(
        None, title="Customer", json_schema_extra={"ui:widget": "textarea"}
    )
    order_total: Optional[float] = Field(None, title="Order Total")
    tax_total: Optional[float] = Field(None, title="Tax Total")
    shipping_total: Optional[float] = Field(None, title="Shipping Total")
    processed_at_foreign: Optional[str] = Field(None, title="Processed At")
    updated_at_foreign: Optional[str] = Field(None, title="Updated At")


class MailchimpDeleteEcommerceOrderConfig(BaseModel):
    """Delete an order."""

    operation: Literal["delete_ecommerce_order"] = Field(
        "delete_ecommerce_order",
        json_schema_extra={
            "const": "delete_ecommerce_order",
            "ui:hidden": True,
            "x-category": "E-commerce Order",
            "x-is-trigger": False,
            "x-display-name": "Delete Ecommerce Order",
        },
        title="Delete Ecommerce Order",
    )
    store_id: str = Field(..., title="Store ID")
    order_id: str = Field(..., title="Order ID")


class MailchimpListEcommerceOrderLinesConfig(BaseModel):
    """Get all line items for an order."""

    operation: Literal["list_order_line_items"] = Field(
        "list_order_line_items",
        json_schema_extra={
            "const": "list_order_line_items",
            "ui:hidden": True,
            "x-category": "E-commerce Order",
            "x-is-trigger": False,
            "x-display-name": "List Order Line Items",
        },
        title="List Order Line Items",
    )
    store_id: str = Field(..., title="Store ID")
    order_id: str = Field(..., title="Order ID")
    count: int = Field(10, title="Count", ge=1, le=1000)
    offset: int = Field(0, title="Offset", ge=0)


class MailchimpAddEcommerceOrderLineConfig(BaseModel):
    """Add a line item to an order."""

    operation: Literal["create_order_line_item"] = Field(
        "create_order_line_item",
        json_schema_extra={
            "const": "create_order_line_item",
            "ui:hidden": True,
            "x-category": "E-commerce Order",
            "x-is-trigger": False,
            "x-display-name": "Create Order Line Item",
        },
        title="Create Order Line Item",
    )
    store_id: str = Field(..., title="Store ID")
    order_id: str = Field(..., title="Order ID")
    id: str = Field(..., title="Line ID")
    product_id: str = Field(..., title="Product ID")
    product_variant_id: str = Field(..., title="Product Variant ID")
    quantity: int = Field(..., title="Quantity", ge=1)
    price: float = Field(..., title="Price", description="Price per item")


# ============================================================================
# E-COMMERCE CUSTOMERS OPERATIONS (6 operations)
# ============================================================================


class MailchimpListEcommerceCustomersConfig(BaseModel):
    """Get all customers for a store."""

    operation: Literal["list_ecommerce_customers"] = Field(
        "list_ecommerce_customers",
        json_schema_extra={
            "const": "list_ecommerce_customers",
            "ui:hidden": True,
            "x-category": "E-commerce Customer",
            "x-is-trigger": False,
            "x-display-name": "List Ecommerce Customers",
        },
        title="List Ecommerce Customers",
    )
    store_id: str = Field(..., title="Store ID")
    count: int = Field(10, title="Count", ge=1, le=1000)
    offset: int = Field(0, title="Offset", ge=0)
    email_address: Optional[str] = Field(None, title="Email Filter")


class MailchimpGetEcommerceCustomerConfig(BaseModel):
    """Get information about a specific customer."""

    operation: Literal["fetch_ecommerce_customer"] = Field(
        "fetch_ecommerce_customer",
        json_schema_extra={
            "const": "fetch_ecommerce_customer",
            "ui:hidden": True,
            "x-category": "E-commerce Customer",
            "x-is-trigger": False,
            "x-display-name": "Fetch Ecommerce Customer",
        },
        title="Fetch Ecommerce Customer",
    )
    store_id: str = Field(..., title="Store ID")
    customer_id: str = Field(..., title="Customer ID")


class MailchimpAddEcommerceCustomerConfig(BaseModel):
    """Add a new customer to a store."""

    operation: Literal["create_ecommerce_customer"] = Field(
        "create_ecommerce_customer",
        json_schema_extra={
            "const": "create_ecommerce_customer",
            "ui:hidden": True,
            "x-category": "E-commerce Customer",
            "x-is-trigger": False,
            "x-display-name": "Create Ecommerce Customer",
        },
        title="Create Ecommerce Customer",
    )
    store_id: str = Field(..., title="Store ID")
    id: str = Field(..., title="Customer ID")
    email_address: str = Field(..., title="Email Address")
    opt_in_status: bool = Field(
        ..., title="Opt-In Status", description="Marketing opt-in status"
    )
    company: Optional[str] = Field(None, title="Company")
    first_name: Optional[str] = Field(None, title="First Name")
    last_name: Optional[str] = Field(None, title="Last Name")
    address: Optional[Dict[str, str]] = Field(
        None, title="Address", json_schema_extra={"ui:widget": "textarea"}
    )


class MailchimpAddOrUpdateEcommerceCustomerConfig(BaseModel):
    """Add or update a customer (upsert)."""

    operation: Literal["upsert_ecommerce_customer"] = Field(
        "upsert_ecommerce_customer",
        json_schema_extra={
            "const": "upsert_ecommerce_customer",
            "ui:hidden": True,
            "x-category": "E-commerce Customer",
            "x-is-trigger": False,
            "x-display-name": "Upsert Ecommerce Customer",
        },
        title="Upsert Ecommerce Customer",
    )
    store_id: str = Field(..., title="Store ID")
    customer_id: str = Field(..., title="Customer ID")
    email_address: str = Field(..., title="Email Address")
    opt_in_status: bool = Field(..., title="Opt-In Status")
    company: Optional[str] = Field(None, title="Company")
    first_name: Optional[str] = Field(None, title="First Name")
    last_name: Optional[str] = Field(None, title="Last Name")
    address: Optional[Dict[str, str]] = Field(
        None, title="Address", json_schema_extra={"ui:widget": "textarea"}
    )


class MailchimpUpdateEcommerceCustomerConfig(BaseModel):
    """Update a customer."""

    operation: Literal["update_ecommerce_customer"] = Field(
        "update_ecommerce_customer",
        json_schema_extra={
            "const": "update_ecommerce_customer",
            "ui:hidden": True,
            "x-category": "E-commerce Customer",
            "x-is-trigger": False,
            "x-display-name": "Update Ecommerce Customer",
        },
        title="Update Ecommerce Customer",
    )
    store_id: str = Field(..., title="Store ID")
    customer_id: str = Field(..., title="Customer ID")
    email_address: Optional[str] = Field(None, title="Email Address")
    opt_in_status: Optional[bool] = Field(None, title="Opt-In Status")
    company: Optional[str] = Field(None, title="Company")
    first_name: Optional[str] = Field(None, title="First Name")
    last_name: Optional[str] = Field(None, title="Last Name")


class MailchimpDeleteEcommerceCustomerConfig(BaseModel):
    """Delete a customer."""

    operation: Literal["delete_ecommerce_customer"] = Field(
        "delete_ecommerce_customer",
        json_schema_extra={
            "const": "delete_ecommerce_customer",
            "ui:hidden": True,
            "x-category": "E-commerce Customer",
            "x-is-trigger": False,
            "x-display-name": "Delete Ecommerce Customer",
        },
        title="Delete Ecommerce Customer",
    )
    store_id: str = Field(..., title="Store ID")
    customer_id: str = Field(..., title="Customer ID")


# ============================================================================
# E-COMMERCE CARTS OPERATIONS (7 operations)
# ============================================================================


class MailchimpListEcommerceCartsConfig(BaseModel):
    """Get all carts for a store."""

    operation: Literal["list_ecommerce_carts"] = Field(
        "list_ecommerce_carts",
        json_schema_extra={
            "const": "list_ecommerce_carts",
            "ui:hidden": True,
            "x-category": "E-commerce Cart",
            "x-is-trigger": False,
            "x-display-name": "List Ecommerce Carts",
        },
        title="List Ecommerce Carts",
    )
    store_id: str = Field(..., title="Store ID")
    count: int = Field(10, title="Count", ge=1, le=1000)
    offset: int = Field(0, title="Offset", ge=0)


class MailchimpGetEcommerceCartConfig(BaseModel):
    """Get information about a specific cart."""

    operation: Literal["fetch_ecommerce_cart"] = Field(
        "fetch_ecommerce_cart",
        json_schema_extra={
            "const": "fetch_ecommerce_cart",
            "ui:hidden": True,
            "x-category": "E-commerce Cart",
            "x-is-trigger": False,
            "x-display-name": "Fetch Ecommerce Cart",
        },
        title="Fetch Ecommerce Cart",
    )
    store_id: str = Field(..., title="Store ID")
    cart_id: str = Field(..., title="Cart ID")


class MailchimpAddEcommerceCartConfig(BaseModel):
    """Add a new cart to a store."""

    operation: Literal["create_ecommerce_cart"] = Field(
        "create_ecommerce_cart",
        json_schema_extra={
            "const": "create_ecommerce_cart",
            "ui:hidden": True,
            "x-category": "E-commerce Cart",
            "x-is-trigger": False,
            "x-display-name": "Create Ecommerce Cart",
        },
        title="Create Ecommerce Cart",
    )
    store_id: str = Field(..., title="Store ID")
    id: str = Field(..., title="Cart ID")
    customer: Dict[str, Any] = Field(
        ...,
        title="Customer",
        description="Customer object with id and email_address",
        json_schema_extra={"ui:widget": "textarea"},
    )
    currency_code: str = Field(
        ..., title="Currency Code", description="Three-letter ISO 4217 code"
    )
    order_total: float = Field(..., title="Order Total")
    lines: List[Dict[str, Any]] = Field(
        ...,
        title="Cart Lines",
        description="Array of line item objects",
        json_schema_extra={"ui:widget": "textarea"},
    )
    checkout_url: Optional[str] = Field(None, title="Checkout URL")
    tax_total: Optional[float] = Field(None, title="Tax Total")


class MailchimpUpdateEcommerceCartConfig(BaseModel):
    """Update a cart."""

    operation: Literal["update_ecommerce_cart"] = Field(
        "update_ecommerce_cart",
        json_schema_extra={
            "const": "update_ecommerce_cart",
            "ui:hidden": True,
            "x-category": "E-commerce Cart",
            "x-is-trigger": False,
            "x-display-name": "Update Ecommerce Cart",
        },
        title="Update Ecommerce Cart",
    )
    store_id: str = Field(..., title="Store ID")
    cart_id: str = Field(..., title="Cart ID")
    customer: Optional[Dict[str, Any]] = Field(
        None, title="Customer", json_schema_extra={"ui:widget": "textarea"}
    )
    order_total: Optional[float] = Field(None, title="Order Total")
    checkout_url: Optional[str] = Field(None, title="Checkout URL")
    tax_total: Optional[float] = Field(None, title="Tax Total")


class MailchimpDeleteEcommerceCartConfig(BaseModel):
    """Delete a cart."""

    operation: Literal["delete_ecommerce_cart"] = Field(
        "delete_ecommerce_cart",
        json_schema_extra={
            "const": "delete_ecommerce_cart",
            "ui:hidden": True,
            "x-category": "E-commerce Cart",
            "x-is-trigger": False,
            "x-display-name": "Delete Ecommerce Cart",
        },
        title="Delete Ecommerce Cart",
    )
    store_id: str = Field(..., title="Store ID")
    cart_id: str = Field(..., title="Cart ID")


class MailchimpListEcommerceCartLinesConfig(BaseModel):
    """Get all line items for a cart."""

    operation: Literal["list_cart_line_items"] = Field(
        "list_cart_line_items",
        json_schema_extra={
            "const": "list_cart_line_items",
            "ui:hidden": True,
            "x-category": "E-commerce Cart",
            "x-is-trigger": False,
            "x-display-name": "List Cart Line Items",
        },
        title="List Cart Line Items",
    )
    store_id: str = Field(..., title="Store ID")
    cart_id: str = Field(..., title="Cart ID")
    count: int = Field(10, title="Count", ge=1, le=1000)
    offset: int = Field(0, title="Offset", ge=0)


class MailchimpAddEcommerceCartLineConfig(BaseModel):
    """Add a line item to a cart."""

    operation: Literal["create_cart_line_item"] = Field(
        "create_cart_line_item",
        json_schema_extra={
            "const": "create_cart_line_item",
            "ui:hidden": True,
            "x-category": "E-commerce Cart",
            "x-is-trigger": False,
            "x-display-name": "Create Cart Line Item",
        },
        title="Create Cart Line Item",
    )
    store_id: str = Field(..., title="Store ID")
    cart_id: str = Field(..., title="Cart ID")
    id: str = Field(..., title="Line ID")
    product_id: str = Field(..., title="Product ID")
    product_variant_id: str = Field(..., title="Product Variant ID")
    quantity: int = Field(..., title="Quantity", ge=1)
    price: float = Field(..., title="Price", description="Price per item")


# ============================================================================
# BATCH OPERATIONS (4 operations)
# ============================================================================


class MailchimpStartBatchOperationConfig(BaseModel):
    """Start a batch operation to run multiple API operations asynchronously."""

    operation: Literal["start_batch_operation"] = Field(
        "start_batch_operation",
        json_schema_extra={
            "const": "start_batch_operation",
            "ui:hidden": True,
            "x-category": "Batch",
            "x-is-trigger": False,
            "x-display-name": "Start Batch Operation",
        },
        title="Start Batch Operation",
    )
    operations: str = Field(
        ..., title="Operations", description="JSON array of operations to execute"
    )


class MailchimpListBatchesConfig(BaseModel):
    """Get a list of all batch operations."""

    operation: Literal["list_batch_operations"] = Field(
        "list_batch_operations",
        json_schema_extra={
            "const": "list_batch_operations",
            "ui:hidden": True,
            "x-category": "Batch",
            "x-is-trigger": False,
            "x-display-name": "List Batch Operations",
        },
        title="List Batch Operations",
    )
    count: int = Field(10, title="Count", ge=1, le=1000)
    offset: int = Field(0, title="Offset", ge=0)


class MailchimpGetBatchStatusConfig(BaseModel):
    """Get the status of a specific batch operation."""

    operation: Literal["fetch_batch_status"] = Field(
        "fetch_batch_status",
        json_schema_extra={
            "const": "fetch_batch_status",
            "ui:hidden": True,
            "x-category": "Batch",
            "x-is-trigger": False,
            "x-display-name": "Fetch Batch Status",
        },
        title="Fetch Batch Status",
    )
    batch_id: str = Field(..., title="Batch ID")


class MailchimpDeleteBatchConfig(BaseModel):
    """Stop and remove a batch request."""

    operation: Literal["cancel_batch_request"] = Field(
        "cancel_batch_request",
        json_schema_extra={
            "const": "cancel_batch_request",
            "ui:hidden": True,
            "x-category": "Batch",
            "x-is-trigger": False,
            "x-display-name": "Cancel Batch Request",
        },
        title="Cancel Batch Request",
    )
    batch_id: str = Field(..., title="Batch ID")


# ============================================================================
# WEBHOOK OPERATIONS (6 operations)
# ============================================================================


class MailchimpListWebhooksConfig(BaseModel):
    """Get all webhooks configured for a specific list."""

    operation: Literal["list_list_webhooks"] = Field(
        "list_list_webhooks",
        json_schema_extra={
            "const": "list_list_webhooks",
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "List List Webhooks",
        },
        title="List List Webhooks",
    )
    list_id: str = Field(..., title="List ID")


class MailchimpGetWebhookConfig(BaseModel):
    """Get information about a specific webhook."""

    operation: Literal["fetch_list_webhook"] = Field(
        "fetch_list_webhook",
        json_schema_extra={
            "const": "fetch_list_webhook",
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Fetch List Webhook",
        },
        title="Fetch List Webhook",
    )
    list_id: str = Field(..., title="List ID")
    webhook_id: str = Field(..., title="Webhook ID")


class MailchimpAddWebhookConfig(BaseModel):
    """Create a new webhook for a list."""

    operation: Literal["create_list_webhook"] = Field(
        "create_list_webhook",
        json_schema_extra={
            "const": "create_list_webhook",
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Create List Webhook",
        },
        title="Create List Webhook",
    )
    list_id: str = Field(..., title="List ID")
    url: str = Field(..., title="URL")
    events: str = Field(..., title="Events", description="JSON object of events")
    sources: str = Field(..., title="Sources", description="JSON object of sources")


class MailchimpUpdateWebhookConfig(BaseModel):
    """Update an existing webhook configuration."""

    operation: Literal["update_list_webhook"] = Field(
        "update_list_webhook",
        json_schema_extra={
            "const": "update_list_webhook",
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Update List Webhook",
        },
        title="Update List Webhook",
    )
    list_id: str = Field(..., title="List ID")
    webhook_id: str = Field(..., title="Webhook ID")
    url: Optional[str] = Field(None, title="URL")
    events: Optional[str] = Field(
        None, title="Events", description="JSON object of events"
    )
    sources: Optional[str] = Field(
        None, title="Sources", description="JSON object of sources"
    )


class MailchimpDeleteWebhookConfig(BaseModel):
    """Delete a webhook from a list."""

    operation: Literal["delete_list_webhook"] = Field(
        "delete_list_webhook",
        json_schema_extra={
            "const": "delete_list_webhook",
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Delete List Webhook",
        },
        title="Delete List Webhook",
    )
    list_id: str = Field(..., title="List ID")
    webhook_id: str = Field(..., title="Webhook ID")


# ============================================================================
# LANDING PAGES (5 operations)
# ============================================================================


class MailchimpListLandingPagesConfig(BaseModel):
    """Get all landing pages."""

    operation: Literal["list_landing_pages"] = Field(
        "list_landing_pages",
        json_schema_extra={
            "const": "list_landing_pages",
            "ui:hidden": True,
            "x-category": "Landing Page",
            "x-is-trigger": False,
            "x-display-name": "List Landing Pages",
        },
        title="List Landing Pages",
    )
    count: int = Field(10, title="Count", ge=1, le=1000)
    offset: int = Field(0, title="Offset", ge=0)


class MailchimpGetLandingPageConfig(BaseModel):
    """Get information about a specific landing page."""

    operation: Literal["fetch_landing_page"] = Field(
        "fetch_landing_page",
        json_schema_extra={
            "const": "fetch_landing_page",
            "ui:hidden": True,
            "x-category": "Landing Page",
            "x-is-trigger": False,
            "x-display-name": "Fetch Landing Page",
        },
        title="Fetch Landing Page",
    )
    page_id: str = Field(..., title="Page ID")


class MailchimpCreateLandingPageConfig(BaseModel):
    """Create a new landing page."""

    operation: Literal["create_landing_page"] = Field(
        "create_landing_page",
        json_schema_extra={
            "const": "create_landing_page",
            "ui:hidden": True,
            "x-category": "Landing Page",
            "x-is-trigger": False,
            "x-display-name": "Create Landing Page",
        },
        title="Create Landing Page",
    )
    type: str = Field(..., title="Type")
    title: str = Field(..., title="Title")
    list_id: str = Field(..., title="List ID")
    store_id: Optional[str] = Field(None, title="Store ID")
    description: Optional[str] = Field(None, title="Description")


class MailchimpUpdateLandingPageConfig(BaseModel):
    """Update a landing page."""

    operation: Literal["update_landing_page"] = Field(
        "update_landing_page",
        json_schema_extra={
            "const": "update_landing_page",
            "ui:hidden": True,
            "x-category": "Landing Page",
            "x-is-trigger": False,
            "x-display-name": "Update Landing Page",
        },
        title="Update Landing Page",
    )
    page_id: str = Field(..., title="Page ID")
    title: Optional[str] = Field(None, title="Title")
    description: Optional[str] = Field(None, title="Description")


class MailchimpDeleteLandingPageConfig(BaseModel):
    """Delete a landing page."""

    operation: Literal["delete_landing_page"] = Field(
        "delete_landing_page",
        json_schema_extra={
            "const": "delete_landing_page",
            "ui:hidden": True,
            "x-category": "Landing Page",
            "x-is-trigger": False,
            "x-display-name": "Delete Landing Page",
        },
        title="Delete Landing Page",
    )
    page_id: str = Field(..., title="Page ID")


# ============================================================================
# E-COMMERCE PRODUCT IMAGES (5 operations)
# ============================================================================


class MailchimpListProductImagesConfig(BaseModel):
    """Get all images for a product."""

    operation: Literal["list_product_images"] = Field(
        "list_product_images",
        json_schema_extra={
            "const": "list_product_images",
            "ui:hidden": True,
            "x-category": "E-commerce Product",
            "x-is-trigger": False,
            "x-display-name": "List Product Images",
        },
        title="List Product Images",
    )
    store_id: str = Field(..., title="Store ID")
    product_id: str = Field(..., title="Product ID")
    count: int = Field(10, title="Count", ge=1, le=1000)
    offset: int = Field(0, title="Offset", ge=0)


class MailchimpGetProductImageConfig(BaseModel):
    """Get information about a specific product image."""

    operation: Literal["fetch_product_image"] = Field(
        "fetch_product_image",
        json_schema_extra={
            "const": "fetch_product_image",
            "ui:hidden": True,
            "x-category": "E-commerce Product",
            "x-is-trigger": False,
            "x-display-name": "Fetch Product Image",
        },
        title="Fetch Product Image",
    )
    store_id: str = Field(..., title="Store ID")
    product_id: str = Field(..., title="Product ID")
    image_id: str = Field(..., title="Image ID")


class MailchimpAddProductImageConfig(BaseModel):
    """Add a new image to a product."""

    operation: Literal["add_product_image"] = Field(
        "add_product_image",
        json_schema_extra={
            "const": "add_product_image",
            "ui:hidden": True,
            "x-category": "E-commerce Product",
            "x-is-trigger": False,
            "x-display-name": "Add Product Image",
        },
        title="Add Product Image",
    )
    store_id: str = Field(..., title="Store ID")
    product_id: str = Field(..., title="Product ID")
    id: str = Field(..., title="Image ID")
    url: str = Field(
        ...,
        title="Image URL",
        description="The image to send — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}).",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": "image/*"},
    )
    variant_ids: str = Field(
        ..., title="Variant IDs", description="JSON array of variant IDs"
    )


class MailchimpUpdateProductImageConfig(BaseModel):
    """Update a product image."""

    operation: Literal["update_product_image"] = Field(
        "update_product_image",
        json_schema_extra={
            "const": "update_product_image",
            "ui:hidden": True,
            "x-category": "E-commerce Product",
            "x-is-trigger": False,
            "x-display-name": "Update Product Image",
        },
        title="Update Product Image",
    )
    store_id: str = Field(..., title="Store ID")
    product_id: str = Field(..., title="Product ID")
    image_id: str = Field(..., title="Image ID")
    url: Optional[str] = Field(
        None,
        title="Image URL",
        description="The image to send — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}).",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": "image/*"},
    )
    variant_ids: Optional[str] = Field(
        None, title="Variant IDs", description="JSON array"
    )


class MailchimpDeleteProductImageConfig(BaseModel):
    """Delete a product image."""

    operation: Literal["delete_product_image"] = Field(
        "delete_product_image",
        json_schema_extra={
            "const": "delete_product_image",
            "ui:hidden": True,
            "x-category": "E-commerce Product",
            "x-is-trigger": False,
            "x-display-name": "Delete Product Image",
        },
        title="Delete Product Image",
    )
    store_id: str = Field(..., title="Store ID")
    product_id: str = Field(..., title="Product ID")
    image_id: str = Field(..., title="Image ID")


# ============================================================================
# E-COMMERCE PROMO RULES (5 operations)
# ============================================================================


class MailchimpListPromoRulesConfig(BaseModel):
    """Get all promo rules for a store."""

    operation: Literal["list_promo_rules"] = Field(
        "list_promo_rules",
        json_schema_extra={
            "const": "list_promo_rules",
            "ui:hidden": True,
            "x-category": "Promo",
            "x-is-trigger": False,
            "x-display-name": "List Promo Rules",
        },
        title="List Promo Rules",
    )
    store_id: str = Field(..., title="Store ID")
    count: int = Field(10, title="Count", ge=1, le=1000)
    offset: int = Field(0, title="Offset", ge=0)


class MailchimpGetPromoRuleConfig(BaseModel):
    """Get information about a specific promo rule."""

    operation: Literal["fetch_promo_rule"] = Field(
        "fetch_promo_rule",
        json_schema_extra={
            "const": "fetch_promo_rule",
            "ui:hidden": True,
            "x-category": "Promo",
            "x-is-trigger": False,
            "x-display-name": "Fetch Promo Rule",
        },
        title="Fetch Promo Rule",
    )
    store_id: str = Field(..., title="Store ID")
    promo_rule_id: str = Field(..., title="Promo Rule ID")


class MailchimpAddPromoRuleConfig(BaseModel):
    """Create a new promo rule."""

    operation: Literal["create_promo_rule"] = Field(
        "create_promo_rule",
        json_schema_extra={
            "const": "create_promo_rule",
            "ui:hidden": True,
            "x-category": "Promo",
            "x-is-trigger": False,
            "x-display-name": "Create Promo Rule",
        },
        title="Create Promo Rule",
    )
    store_id: str = Field(..., title="Store ID")
    id: str = Field(..., title="Promo Rule ID")
    title: str = Field(..., title="Title")
    description: str = Field(..., title="Description")
    amount: float = Field(..., title="Amount")
    type: str = Field(..., title="Type", description="fixed or percentage")
    enabled: Optional[bool] = Field(None, title="Enabled")


class MailchimpUpdatePromoRuleConfig(BaseModel):
    """Update a promo rule."""

    operation: Literal["update_promo_rule"] = Field(
        "update_promo_rule",
        json_schema_extra={
            "const": "update_promo_rule",
            "ui:hidden": True,
            "x-category": "Promo",
            "x-is-trigger": False,
            "x-display-name": "Update Promo Rule",
        },
        title="Update Promo Rule",
    )
    store_id: str = Field(..., title="Store ID")
    promo_rule_id: str = Field(..., title="Promo Rule ID")
    title: Optional[str] = Field(None, title="Title")
    description: Optional[str] = Field(None, title="Description")
    amount: Optional[float] = Field(None, title="Amount")
    enabled: Optional[bool] = Field(None, title="Enabled")


class MailchimpDeletePromoRuleConfig(BaseModel):
    """Delete a promo rule."""

    operation: Literal["delete_promo_rule"] = Field(
        "delete_promo_rule",
        json_schema_extra={
            "const": "delete_promo_rule",
            "ui:hidden": True,
            "x-category": "Promo",
            "x-is-trigger": False,
            "x-display-name": "Delete Promo Rule",
        },
        title="Delete Promo Rule",
    )
    store_id: str = Field(..., title="Store ID")
    promo_rule_id: str = Field(..., title="Promo Rule ID")


# ============================================================================
# E-COMMERCE PROMO CODES (5 operations)
# ============================================================================


class MailchimpListPromoCodesConfig(BaseModel):
    """Get all promo codes for a promo rule."""

    operation: Literal["list_promo_codes"] = Field(
        "list_promo_codes",
        json_schema_extra={
            "const": "list_promo_codes",
            "ui:hidden": True,
            "x-category": "Promo",
            "x-is-trigger": False,
            "x-display-name": "List Promo Codes",
        },
        title="List Promo Codes",
    )
    store_id: str = Field(..., title="Store ID")
    promo_rule_id: str = Field(..., title="Promo Rule ID")
    count: int = Field(10, title="Count", ge=1, le=1000)
    offset: int = Field(0, title="Offset", ge=0)


class MailchimpGetPromoCodeConfig(BaseModel):
    """Get information about a specific promo code."""

    operation: Literal["fetch_promo_code"] = Field(
        "fetch_promo_code",
        json_schema_extra={
            "const": "fetch_promo_code",
            "ui:hidden": True,
            "x-category": "Promo",
            "x-is-trigger": False,
            "x-display-name": "Fetch Promo Code",
        },
        title="Fetch Promo Code",
    )
    store_id: str = Field(..., title="Store ID")
    promo_rule_id: str = Field(..., title="Promo Rule ID")
    promo_code_id: str = Field(..., title="Promo Code ID")


class MailchimpAddPromoCodeConfig(BaseModel):
    """Create a new promo code."""

    operation: Literal["create_promo_code"] = Field(
        "create_promo_code",
        json_schema_extra={
            "const": "create_promo_code",
            "ui:hidden": True,
            "x-category": "Promo",
            "x-is-trigger": False,
            "x-display-name": "Create Promo Code",
        },
        title="Create Promo Code",
    )
    store_id: str = Field(..., title="Store ID")
    promo_rule_id: str = Field(..., title="Promo Rule ID")
    id: str = Field(..., title="Promo Code ID")
    code: str = Field(..., title="Code")
    enabled: Optional[bool] = Field(None, title="Enabled")


class MailchimpUpdatePromoCodeConfig(BaseModel):
    """Update a promo code."""

    operation: Literal["update_promo_code"] = Field(
        "update_promo_code",
        json_schema_extra={
            "const": "update_promo_code",
            "ui:hidden": True,
            "x-category": "Promo",
            "x-is-trigger": False,
            "x-display-name": "Update Promo Code",
        },
        title="Update Promo Code",
    )
    store_id: str = Field(..., title="Store ID")
    promo_rule_id: str = Field(..., title="Promo Rule ID")
    promo_code_id: str = Field(..., title="Promo Code ID")
    code: Optional[str] = Field(None, title="Code")
    enabled: Optional[bool] = Field(None, title="Enabled")


class MailchimpDeletePromoCodeConfig(BaseModel):
    """Delete a promo code."""

    operation: Literal["delete_promo_code"] = Field(
        "delete_promo_code",
        json_schema_extra={
            "const": "delete_promo_code",
            "ui:hidden": True,
            "x-category": "Promo",
            "x-is-trigger": False,
            "x-display-name": "Delete Promo Code",
        },
        title="Delete Promo Code",
    )
    store_id: str = Field(..., title="Store ID")
    promo_rule_id: str = Field(..., title="Promo Rule ID")
    promo_code_id: str = Field(..., title="Promo Code ID")


# ============================================================================
# Signup Forms Operations
# ============================================================================


class MailchimpListSignupFormsConfig(BaseModel):
    """List all signup forms for a specific list."""

    operation: Literal["list_signup_forms"] = Field(
        "list_signup_forms",
        json_schema_extra={
            "const": "list_signup_forms",
            "ui:hidden": True,
            "x-category": "Signup Form",
            "x-is-trigger": False,
            "x-display-name": "List Signup Forms",
        },
        title="List Signup Forms",
    )
    list_id: str = Field(..., title="List ID")


class MailchimpCreateSignupFormConfig(BaseModel):
    """Create a signup form for a list."""

    operation: Literal["create_signup_form"] = Field(
        "create_signup_form",
        json_schema_extra={
            "const": "create_signup_form",
            "ui:hidden": True,
            "x-category": "Signup Form",
            "x-is-trigger": False,
            "x-display-name": "Create Signup Form",
        },
        title="Create Signup Form",
    )
    list_id: str = Field(..., title="List ID")
    header: Dict[str, Any] = Field(
        ..., title="Header", json_schema_extra={"ui:widget": "textarea"}
    )
    contents: List[Dict[str, Any]] = Field(
        ..., title="Contents", json_schema_extra={"ui:widget": "textarea"}
    )
    styles: Optional[Dict[str, Any]] = Field(
        None, title="Styles", json_schema_extra={"ui:widget": "textarea"}
    )


class MailchimpUpdateSignupFormConfig(BaseModel):
    """Update a signup form."""

    operation: Literal["update_signup_form"] = Field(
        "update_signup_form",
        json_schema_extra={
            "const": "update_signup_form",
            "ui:hidden": True,
            "x-category": "Signup Form",
            "x-is-trigger": False,
            "x-display-name": "Update Signup Form",
        },
        title="Update Signup Form",
    )
    list_id: str = Field(..., title="List ID")
    signup_form_id: str = Field(..., title="Signup Form ID")
    header: Optional[Dict[str, Any]] = Field(
        None, title="Header", json_schema_extra={"ui:widget": "textarea"}
    )
    contents: Optional[List[Dict[str, Any]]] = Field(
        None, title="Contents", json_schema_extra={"ui:widget": "textarea"}
    )
    styles: Optional[Dict[str, Any]] = Field(
        None, title="Styles", json_schema_extra={"ui:widget": "textarea"}
    )


# ============================================================================
# File Manager Folders Operations
# ============================================================================


class MailchimpListFileManagerFoldersConfig(BaseModel):
    """List all folders in the File Manager."""

    operation: Literal["list_file_folders"] = Field(
        "list_file_folders",
        json_schema_extra={
            "const": "list_file_folders",
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "List File Folders",
        },
        title="List File Folders",
    )
    count: int = Field(100, title="Count", ge=1, le=1000)
    offset: int = Field(0, title="Offset", ge=0)


class MailchimpGetFileManagerFolderConfig(BaseModel):
    """Get a specific File Manager folder."""

    operation: Literal["fetch_file_folder"] = Field(
        "fetch_file_folder",
        json_schema_extra={
            "const": "fetch_file_folder",
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Fetch File Folder",
        },
        title="Fetch File Folder",
    )
    folder_id: str = Field(..., title="Folder ID")


class MailchimpCreateFileManagerFolderConfig(BaseModel):
    """Create a new File Manager folder."""

    operation: Literal["create_file_folder"] = Field(
        "create_file_folder",
        json_schema_extra={
            "const": "create_file_folder",
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Create File Folder",
        },
        title="Create File Folder",
    )
    name: str = Field(..., title="Folder Name")


class MailchimpUpdateFileManagerFolderConfig(BaseModel):
    """Update a File Manager folder."""

    operation: Literal["update_file_folder"] = Field(
        "update_file_folder",
        json_schema_extra={
            "const": "update_file_folder",
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Update File Folder",
        },
        title="Update File Folder",
    )
    folder_id: str = Field(..., title="Folder ID")
    name: str = Field(..., title="Folder Name")


class MailchimpDeleteFileManagerFolderConfig(BaseModel):
    """Delete a File Manager folder."""

    operation: Literal["delete_file_folder"] = Field(
        "delete_file_folder",
        json_schema_extra={
            "const": "delete_file_folder",
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Delete File Folder",
        },
        title="Delete File Folder",
    )
    folder_id: str = Field(..., title="Folder ID")


# ============================================================================
# File Manager Files Operations
# ============================================================================


class MailchimpListFileManagerFilesConfig(BaseModel):
    """List all files in the File Manager."""

    operation: Literal["list_files"] = Field(
        "list_files",
        json_schema_extra={
            "const": "list_files",
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "List Files",
        },
        title="List Files",
    )
    count: int = Field(100, title="Count", ge=1, le=1000)
    offset: int = Field(0, title="Offset", ge=0)
    folder_id: Optional[str] = Field(None, title="Folder ID")


class MailchimpGetFileManagerFileConfig(BaseModel):
    """Get a specific File Manager file."""

    operation: Literal["fetch_file"] = Field(
        "fetch_file",
        json_schema_extra={
            "const": "fetch_file",
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Fetch File",
        },
        title="Fetch File",
    )
    file_id: str = Field(..., title="File ID")


class MailchimpUploadFileManagerFileConfig(BaseModel):
    """Upload a file to the File Manager."""

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
    name: str = Field(..., title="File Name")
    file_data: str = Field(
        ...,
        title="File Data (base64)",
        description="The file to send — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}).",
        json_schema_extra={"ui:widget": "media_upload"},
    )
    folder_id: Optional[str] = Field(None, title="Folder ID")


class MailchimpUpdateFileManagerFileConfig(BaseModel):
    """Update a File Manager file."""

    operation: Literal["update_file"] = Field(
        "update_file",
        json_schema_extra={
            "const": "update_file",
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Update File",
        },
        title="Update File",
    )
    file_id: str = Field(..., title="File ID")
    name: Optional[str] = Field(None, title="File Name")
    folder_id: Optional[str] = Field(None, title="Folder ID")


class MailchimpDeleteFileManagerFileConfig(BaseModel):
    """Delete a File Manager file."""

    operation: Literal["delete_file"] = Field(
        "delete_file",
        json_schema_extra={
            "const": "delete_file",
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "Delete File",
        },
        title="Delete File",
    )
    file_id: str = Field(..., title="File ID")


# ============================================================================
# Campaign Folders Operations
# ============================================================================


class MailchimpListCampaignFoldersConfig(BaseModel):
    """List all campaign folders."""

    operation: Literal["list_campaign_folders"] = Field(
        "list_campaign_folders",
        json_schema_extra={
            "const": "list_campaign_folders",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "List Campaign Folders",
        },
        title="List Campaign Folders",
    )
    count: int = Field(100, title="Count", ge=1, le=1000)
    offset: int = Field(0, title="Offset", ge=0)


class MailchimpGetCampaignFolderConfig(BaseModel):
    """Get a specific campaign folder."""

    operation: Literal["fetch_campaign_folder"] = Field(
        "fetch_campaign_folder",
        json_schema_extra={
            "const": "fetch_campaign_folder",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Fetch Campaign Folder",
        },
        title="Fetch Campaign Folder",
    )
    folder_id: str = Field(..., title="Folder ID")


class MailchimpCreateCampaignFolderConfig(BaseModel):
    """Create a campaign folder."""

    operation: Literal["create_campaign_folder"] = Field(
        "create_campaign_folder",
        json_schema_extra={
            "const": "create_campaign_folder",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Create Campaign Folder",
        },
        title="Create Campaign Folder",
    )
    name: str = Field(..., title="Folder Name")


class MailchimpUpdateCampaignFolderConfig(BaseModel):
    """Update a campaign folder."""

    operation: Literal["update_campaign_folder"] = Field(
        "update_campaign_folder",
        json_schema_extra={
            "const": "update_campaign_folder",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Update Campaign Folder",
        },
        title="Update Campaign Folder",
    )
    folder_id: str = Field(..., title="Folder ID")
    name: str = Field(..., title="Folder Name")


class MailchimpDeleteCampaignFolderConfig(BaseModel):
    """Delete a campaign folder."""

    operation: Literal["delete_campaign_folder"] = Field(
        "delete_campaign_folder",
        json_schema_extra={
            "const": "delete_campaign_folder",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Delete Campaign Folder",
        },
        title="Delete Campaign Folder",
    )
    folder_id: str = Field(..., title="Folder ID")


# ============================================================================
# Template Folders Operations
# ============================================================================


class MailchimpListTemplateFoldersConfig(BaseModel):
    """List all template folders."""

    operation: Literal["list_template_folders"] = Field(
        "list_template_folders",
        json_schema_extra={
            "const": "list_template_folders",
            "ui:hidden": True,
            "x-category": "Template",
            "x-is-trigger": False,
            "x-display-name": "List Template Folders",
        },
        title="List Template Folders",
    )
    count: int = Field(100, title="Count", ge=1, le=1000)
    offset: int = Field(0, title="Offset", ge=0)


class MailchimpGetTemplateFolderConfig(BaseModel):
    """Get a specific template folder."""

    operation: Literal["fetch_template_folder"] = Field(
        "fetch_template_folder",
        json_schema_extra={
            "const": "fetch_template_folder",
            "ui:hidden": True,
            "x-category": "Template",
            "x-is-trigger": False,
            "x-display-name": "Fetch Template Folder",
        },
        title="Fetch Template Folder",
    )
    folder_id: str = Field(..., title="Folder ID")


class MailchimpCreateTemplateFolderConfig(BaseModel):
    """Create a template folder."""

    operation: Literal["create_template_folder"] = Field(
        "create_template_folder",
        json_schema_extra={
            "const": "create_template_folder",
            "ui:hidden": True,
            "x-category": "Template",
            "x-is-trigger": False,
            "x-display-name": "Create Template Folder",
        },
        title="Create Template Folder",
    )
    name: str = Field(..., title="Folder Name")


class MailchimpUpdateTemplateFolderConfig(BaseModel):
    """Update a template folder."""

    operation: Literal["update_template_folder"] = Field(
        "update_template_folder",
        json_schema_extra={
            "const": "update_template_folder",
            "ui:hidden": True,
            "x-category": "Template",
            "x-is-trigger": False,
            "x-display-name": "Update Template Folder",
        },
        title="Update Template Folder",
    )
    folder_id: str = Field(..., title="Folder ID")
    name: str = Field(..., title="Folder Name")


class MailchimpDeleteTemplateFolderConfig(BaseModel):
    """Delete a template folder."""

    operation: Literal["delete_template_folder"] = Field(
        "delete_template_folder",
        json_schema_extra={
            "const": "delete_template_folder",
            "ui:hidden": True,
            "x-category": "Template",
            "x-is-trigger": False,
            "x-display-name": "Delete Template Folder",
        },
        title="Delete Template Folder",
    )
    folder_id: str = Field(..., title="Folder ID")


# ============================================================================
# Account/Root Operations
# ============================================================================


class MailchimpGetAccountInfoConfig(BaseModel):
    """Get account information."""

    operation: Literal["fetch_account_info"] = Field(
        "fetch_account_info",
        json_schema_extra={
            "const": "fetch_account_info",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Fetch Account Info",
        },
        title="Fetch Account Info",
    )


class MailchimpListAuthorizedAppsConfig(BaseModel):
    """List all authorized apps for the account."""

    operation: Literal["list_authorized_apps"] = Field(
        "list_authorized_apps",
        json_schema_extra={
            "const": "list_authorized_apps",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "List Authorized Apps",
        },
        title="List Authorized Apps",
    )
    count: int = Field(100, title="Count", ge=1, le=1000)
    offset: int = Field(0, title="Offset", ge=0)


class MailchimpGetAuthorizedAppConfig(BaseModel):
    """Get details about a specific authorized app."""

    operation: Literal["fetch_authorized_app"] = Field(
        "fetch_authorized_app",
        json_schema_extra={
            "const": "fetch_authorized_app",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Fetch Authorized App",
        },
        title="Fetch Authorized App",
    )
    app_id: str = Field(..., title="App ID")


class MailchimpDisconnectAuthorizedAppConfig(BaseModel):
    """Disconnect an authorized app."""

    operation: Literal["disconnect_authorized_app"] = Field(
        "disconnect_authorized_app",
        json_schema_extra={
            "const": "disconnect_authorized_app",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Disconnect Authorized App",
        },
        title="Disconnect Authorized App",
    )
    app_id: str = Field(..., title="App ID")


class MailchimpPingConfig(BaseModel):
    """Ping the Mailchimp API to verify connectivity."""

    operation: Literal["ping_api_connection"] = Field(
        "ping_api_connection",
        json_schema_extra={
            "const": "ping_api_connection",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Ping Api Connection",
        },
        title="Ping Api Connection",
    )


# ============================================================================
# Additional API Operations Config Classes (115 new endpoints)
# ============================================================================


class MailchimpGetRootConfig(BaseModel):
    """Get API root information."""

    operation: Literal["fetch_api_root_info"] = Field(
        "fetch_api_root_info",
        json_schema_extra={
            "const": "fetch_api_root_info",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Fetch Api Root Info",
        },
        title="Fetch Api Root Info",
    )


class MailchimpGetChimpChatterConfig(BaseModel):
    """Get recent activity feed (Chimp Chatter)."""

    operation: Literal["fetch_activity_feed"] = Field(
        "fetch_activity_feed",
        json_schema_extra={
            "const": "fetch_activity_feed",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Fetch Activity Feed",
        },
        title="Fetch Activity Feed",
    )
    count: int = Field(10, title="Number of records", ge=1, le=1000)


class MailchimpListAudiencesV2Config(BaseModel):
    """List all audiences (v2 contacts API)."""

    operation: Literal["list_audiences"] = Field(
        "list_audiences",
        json_schema_extra={
            "const": "list_audiences",
            "ui:hidden": True,
            "x-category": "Audience",
            "x-is-trigger": False,
            "x-display-name": "List Audiences",
        },
        title="List Audiences",
    )
    count: int = Field(10, title="Number of records", ge=1, le=1000)
    offset: int = Field(0, title="Number to skip", ge=0)


class MailchimpCreateAudienceV2Config(BaseModel):
    """Create a new audience (v2 contacts API)."""

    operation: Literal["create_audience"] = Field(
        "create_audience",
        json_schema_extra={
            "const": "create_audience",
            "ui:hidden": True,
            "x-category": "Audience",
            "x-is-trigger": False,
            "x-display-name": "Create Audience",
        },
        title="Create Audience",
    )
    name: str = Field(..., title="Audience name")
    permission_reminder: str = Field(..., title="Permission reminder")
    email_type_option: bool = Field(False, title="Email type option")
    contact: Dict[str, Any] = Field(..., title="Contact information")


class MailchimpGetAudienceV2Config(BaseModel):
    """Get information about a specific audience."""

    operation: Literal["fetch_audience"] = Field(
        "fetch_audience",
        json_schema_extra={
            "const": "fetch_audience",
            "ui:hidden": True,
            "x-category": "Audience",
            "x-is-trigger": False,
            "x-display-name": "Fetch Audience",
        },
        title="Fetch Audience",
    )
    list_id: str = Field(..., title="Audience/List ID")


class MailchimpUpdateAudienceV2Config(BaseModel):
    """Update settings for an audience."""

    operation: Literal["update_audience_settings"] = Field(
        "update_audience_settings",
        json_schema_extra={
            "const": "update_audience_settings",
            "ui:hidden": True,
            "x-category": "Audience",
            "x-is-trigger": False,
            "x-display-name": "Update Audience Settings",
        },
        title="Update Audience Settings",
    )
    list_id: str = Field(..., title="Audience/List ID")
    name: Optional[str] = Field(None, title="Updated audience name")


class MailchimpDeleteAudienceV2Config(BaseModel):
    """Delete an audience."""

    operation: Literal["delete_audience"] = Field(
        "delete_audience",
        json_schema_extra={
            "const": "delete_audience",
            "ui:hidden": True,
            "x-category": "Audience",
            "x-is-trigger": False,
            "x-display-name": "Delete Audience",
        },
        title="Delete Audience",
    )
    list_id: str = Field(..., title="Audience/List ID")


class MailchimpListContactsConfig(BaseModel):
    """List all contacts in an audience."""

    operation: Literal["list_audience_contacts"] = Field(
        "list_audience_contacts",
        json_schema_extra={
            "const": "list_audience_contacts",
            "ui:hidden": True,
            "x-category": "Member",
            "x-is-trigger": False,
            "x-display-name": "List Audience Contacts",
        },
        title="List Audience Contacts",
    )
    list_id: str = Field(..., title="Audience/List ID")
    count: int = Field(10, title="Number of records", ge=1, le=1000)
    offset: int = Field(0, title="Number to skip", ge=0)


class MailchimpCreateContactConfig(BaseModel):
    """Add a new contact to an audience."""

    operation: Literal["create_audience_contact"] = Field(
        "create_audience_contact",
        json_schema_extra={
            "const": "create_audience_contact",
            "ui:hidden": True,
            "x-category": "Member",
            "x-is-trigger": False,
            "x-display-name": "Create Audience Contact",
        },
        title="Create Audience Contact",
    )
    list_id: str = Field(..., title="Audience/List ID")
    email_address: str = Field(..., title="Contact email address")
    status: str = Field(..., title="Subscription status")


class MailchimpGetContactConfig(BaseModel):
    """Get information about a specific contact."""

    operation: Literal["fetch_audience_contact"] = Field(
        "fetch_audience_contact",
        json_schema_extra={
            "const": "fetch_audience_contact",
            "ui:hidden": True,
            "x-category": "Member",
            "x-is-trigger": False,
            "x-display-name": "Fetch Audience Contact",
        },
        title="Fetch Audience Contact",
    )
    list_id: str = Field(..., title="Audience/List ID")
    email_address: str = Field(..., title="Contact email address")


class MailchimpUpdateContactConfig(BaseModel):
    """Update a contact in an audience."""

    operation: Literal["update_audience_contact"] = Field(
        "update_audience_contact",
        json_schema_extra={
            "const": "update_audience_contact",
            "ui:hidden": True,
            "x-category": "Member",
            "x-is-trigger": False,
            "x-display-name": "Update Audience Contact",
        },
        title="Update Audience Contact",
    )
    list_id: str = Field(..., title="Audience/List ID")
    email_address: str = Field(..., title="Contact email address")
    status: Optional[str] = Field(None, title="Updated subscription status")


class MailchimpArchiveContactConfig(BaseModel):
    """Archive a contact in an audience."""

    operation: Literal["archive_list_contact"] = Field(
        "archive_list_contact",
        json_schema_extra={
            "const": "archive_list_contact",
            "ui:hidden": True,
            "x-category": "Member",
            "x-is-trigger": False,
            "x-display-name": "Archive List Contact",
        },
        title="Archive List Contact",
    )
    list_id: str = Field(..., title="Audience/List ID")
    email_address: str = Field(..., title="Contact email address")


class MailchimpForgetContactConfig(BaseModel):
    """Delete all personally identifiable information for a contact."""

    operation: Literal["permanently_delete_contact_data"] = Field(
        "permanently_delete_contact_data",
        json_schema_extra={
            "const": "permanently_delete_contact_data",
            "ui:hidden": True,
            "x-category": "Member",
            "x-is-trigger": False,
            "x-display-name": "Permanently Delete Contact Data",
        },
        title="Permanently Delete Contact Data",
    )
    list_id: str = Field(..., title="Audience/List ID")
    email_address: str = Field(..., title="Contact email address")


class MailchimpListAutomationEmailsConfig(BaseModel):
    """List all automation emails for a workflow."""

    operation: Literal["list_automation_emails"] = Field(
        "list_automation_emails",
        json_schema_extra={
            "const": "list_automation_emails",
            "ui:hidden": True,
            "x-category": "Automation",
            "x-is-trigger": False,
            "x-display-name": "List Automation Emails",
        },
        title="List Automation Emails",
    )
    workflow_id: str = Field(..., title="Automation workflow ID")


class MailchimpGetAutomationEmailConfig(BaseModel):
    """Get information about a specific automation email."""

    operation: Literal["fetch_automation_email"] = Field(
        "fetch_automation_email",
        json_schema_extra={
            "const": "fetch_automation_email",
            "ui:hidden": True,
            "x-category": "Automation",
            "x-is-trigger": False,
            "x-display-name": "Fetch Automation Email",
        },
        title="Fetch Automation Email",
    )
    workflow_id: str = Field(..., title="Automation workflow ID")
    email_id: str = Field(..., title="Automation email ID")


class MailchimpStartAutomationEmailConfig(BaseModel):
    """Start an automation email."""

    operation: Literal["start_automation_email"] = Field(
        "start_automation_email",
        json_schema_extra={
            "const": "start_automation_email",
            "ui:hidden": True,
            "x-category": "Automation",
            "x-is-trigger": False,
            "x-display-name": "Start Automation Email",
        },
        title="Start Automation Email",
    )
    workflow_id: str = Field(..., title="Automation workflow ID")
    email_id: str = Field(..., title="Automation email ID")


class MailchimpPauseAutomationEmailConfig(BaseModel):
    """Pause an automation email."""

    operation: Literal["pause_automation_email"] = Field(
        "pause_automation_email",
        json_schema_extra={
            "const": "pause_automation_email",
            "ui:hidden": True,
            "x-category": "Automation",
            "x-is-trigger": False,
            "x-display-name": "Pause Automation Email",
        },
        title="Pause Automation Email",
    )
    workflow_id: str = Field(..., title="Automation workflow ID")
    email_id: str = Field(..., title="Automation email ID")


class MailchimpListAutomationQueueConfig(BaseModel):
    """List all subscribers in automation email queue."""

    operation: Literal["list_automation_queue_members"] = Field(
        "list_automation_queue_members",
        json_schema_extra={
            "const": "list_automation_queue_members",
            "ui:hidden": True,
            "x-category": "Automation",
            "x-is-trigger": False,
            "x-display-name": "List Automation Queue Members",
        },
        title="List Automation Queue Members",
    )
    workflow_id: str = Field(..., title="Automation workflow ID")
    email_id: str = Field(..., title="Automation email ID")


class MailchimpGetAutomationQueueMemberConfig(BaseModel):
    """Get information about a specific subscriber in automation queue."""

    operation: Literal["fetch_automation_queue_member"] = Field(
        "fetch_automation_queue_member",
        json_schema_extra={
            "const": "fetch_automation_queue_member",
            "ui:hidden": True,
            "x-category": "Automation",
            "x-is-trigger": False,
            "x-display-name": "Fetch Automation Queue Member",
        },
        title="Fetch Automation Queue Member",
    )
    workflow_id: str = Field(..., title="Automation workflow ID")
    email_id: str = Field(..., title="Automation email ID")
    email_address: str = Field(..., title="Member email address")


class MailchimpListAutomationRemovedConfig(BaseModel):
    """List subscribers removed from automation workflow."""

    operation: Literal["list_automation_removed_members"] = Field(
        "list_automation_removed_members",
        json_schema_extra={
            "const": "list_automation_removed_members",
            "ui:hidden": True,
            "x-category": "Automation",
            "x-is-trigger": False,
            "x-display-name": "List Automation Removed Members",
        },
        title="List Automation Removed Members",
    )
    workflow_id: str = Field(..., title="Automation workflow ID")


class MailchimpGetAutomationRemovedConfig(BaseModel):
    """Get information about a removed subscriber."""

    operation: Literal["fetch_automation_removed_member"] = Field(
        "fetch_automation_removed_member",
        json_schema_extra={
            "const": "fetch_automation_removed_member",
            "ui:hidden": True,
            "x-category": "Automation",
            "x-is-trigger": False,
            "x-display-name": "Fetch Automation Removed Member",
        },
        title="Fetch Automation Removed Member",
    )
    workflow_id: str = Field(..., title="Automation workflow ID")
    email_address: str = Field(..., title="Member email address")


class MailchimpAddAutomationRemovedConfig(BaseModel):
    """Remove a subscriber from an automation workflow."""

    operation: Literal["remove_member_from_automation"] = Field(
        "remove_member_from_automation",
        json_schema_extra={
            "const": "remove_member_from_automation",
            "ui:hidden": True,
            "x-category": "Automation",
            "x-is-trigger": False,
            "x-display-name": "Remove Member from Automation",
        },
        title="Remove Member from Automation",
    )
    workflow_id: str = Field(..., title="Automation workflow ID")
    email_address: str = Field(..., title="Member email address")


class MailchimpListBatchWebhooksConfig(BaseModel):
    """List all batch webhooks."""

    operation: Literal["list_batch_webhooks"] = Field(
        "list_batch_webhooks",
        json_schema_extra={
            "const": "list_batch_webhooks",
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "List Batch Webhooks",
        },
        title="List Batch Webhooks",
    )
    count: int = Field(10, title="Number of records", ge=1, le=1000)
    offset: int = Field(0, title="Number to skip", ge=0)


class MailchimpCreateBatchWebhookConfig(BaseModel):
    """Create a new batch webhook."""

    operation: Literal["create_batch_webhook"] = Field(
        "create_batch_webhook",
        json_schema_extra={
            "const": "create_batch_webhook",
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Create Batch Webhook",
        },
        title="Create Batch Webhook",
    )
    url: str = Field(..., title="Webhook URL")


class MailchimpGetBatchWebhookConfig(BaseModel):
    """Get information about a specific batch webhook."""

    operation: Literal["fetch_batch_webhook"] = Field(
        "fetch_batch_webhook",
        json_schema_extra={
            "const": "fetch_batch_webhook",
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Fetch Batch Webhook",
        },
        title="Fetch Batch Webhook",
    )
    webhook_id: str = Field(..., title="Batch webhook ID")


class MailchimpDeleteBatchWebhookConfig(BaseModel):
    """Delete a batch webhook."""

    operation: Literal["delete_batch_webhook"] = Field(
        "delete_batch_webhook",
        json_schema_extra={
            "const": "delete_batch_webhook",
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Delete Batch Webhook",
        },
        title="Delete Batch Webhook",
    )
    webhook_id: str = Field(..., title="Batch webhook ID")


class MailchimpCancelSendCampaignConfig(BaseModel):
    """Cancel a scheduled campaign."""

    operation: Literal["cancel_campaign_send"] = Field(
        "cancel_campaign_send",
        json_schema_extra={
            "const": "cancel_campaign_send",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Cancel Campaign Send",
        },
        title="Cancel Campaign Send",
    )
    campaign_id: str = Field(..., title="Campaign ID")


class MailchimpPauseCampaignConfig(BaseModel):
    """Pause an RSS-Driven campaign."""

    operation: Literal["pause_rss_campaign"] = Field(
        "pause_rss_campaign",
        json_schema_extra={
            "const": "pause_rss_campaign",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Pause Rss Campaign",
        },
        title="Pause Rss Campaign",
    )
    campaign_id: str = Field(..., title="Campaign ID")


class MailchimpResumeCampaignConfig(BaseModel):
    """Resume an RSS-Driven campaign."""

    operation: Literal["resume_rss_campaign"] = Field(
        "resume_rss_campaign",
        json_schema_extra={
            "const": "resume_rss_campaign",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Resume Rss Campaign",
        },
        title="Resume Rss Campaign",
    )
    campaign_id: str = Field(..., title="Campaign ID")


class MailchimpCreateResendCampaignConfig(BaseModel):
    """Create a resend to non-openers."""

    operation: Literal["create_campaign_resend"] = Field(
        "create_campaign_resend",
        json_schema_extra={
            "const": "create_campaign_resend",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Create Campaign Resend",
        },
        title="Create Campaign Resend",
    )
    campaign_id: str = Field(..., title="Campaign ID")


class MailchimpListCampaignFeedbackConfig(BaseModel):
    """List feedback for a campaign."""

    operation: Literal["list_campaign_feedback"] = Field(
        "list_campaign_feedback",
        json_schema_extra={
            "const": "list_campaign_feedback",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "List Campaign Feedback",
        },
        title="List Campaign Feedback",
    )
    campaign_id: str = Field(..., title="Campaign ID")
    count: int = Field(10, title="Number of records", ge=1, le=1000)
    offset: int = Field(0, title="Number to skip", ge=0)


class MailchimpCreateCampaignFeedbackConfig(BaseModel):
    """Add feedback to a campaign."""

    operation: Literal["add_campaign_feedback"] = Field(
        "add_campaign_feedback",
        json_schema_extra={
            "const": "add_campaign_feedback",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Add Campaign Feedback",
        },
        title="Add Campaign Feedback",
    )
    campaign_id: str = Field(..., title="Campaign ID")
    message: str = Field(..., title="Feedback message")
    block_id: Optional[str] = Field(None, title="Block ID (optional)")


class MailchimpGetCampaignFeedbackConfig(BaseModel):
    """Get specific campaign feedback."""

    operation: Literal["fetch_campaign_feedback"] = Field(
        "fetch_campaign_feedback",
        json_schema_extra={
            "const": "fetch_campaign_feedback",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Fetch Campaign Feedback",
        },
        title="Fetch Campaign Feedback",
    )
    campaign_id: str = Field(..., title="Campaign ID")
    feedback_id: str = Field(..., title="Feedback ID")


class MailchimpDeleteCampaignFeedbackConfig(BaseModel):
    """Delete campaign feedback."""

    operation: Literal["delete_campaign_feedback"] = Field(
        "delete_campaign_feedback",
        json_schema_extra={
            "const": "delete_campaign_feedback",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Delete Campaign Feedback",
        },
        title="Delete Campaign Feedback",
    )
    campaign_id: str = Field(..., title="Campaign ID")
    feedback_id: str = Field(..., title="Feedback ID")


class MailchimpGetCampaignChecklistConfig(BaseModel):
    """Get send checklist for a campaign."""

    operation: Literal["fetch_campaign_checklist"] = Field(
        "fetch_campaign_checklist",
        json_schema_extra={
            "const": "fetch_campaign_checklist",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Fetch Campaign Checklist",
        },
        title="Fetch Campaign Checklist",
    )
    campaign_id: str = Field(..., title="Campaign ID")


class MailchimpListConnectedSitesConfig(BaseModel):
    """List all connected sites."""

    operation: Literal["list_connected_sites"] = Field(
        "list_connected_sites",
        json_schema_extra={
            "const": "list_connected_sites",
            "ui:hidden": True,
            "x-category": "Connected Site",
            "x-is-trigger": False,
            "x-display-name": "List Connected Sites",
        },
        title="List Connected Sites",
    )
    count: int = Field(10, title="Number of records", ge=1, le=1000)
    offset: int = Field(0, title="Number to skip", ge=0)


class MailchimpCreateConnectedSiteConfig(BaseModel):
    """Create a new connected site."""

    operation: Literal["create_connected_site"] = Field(
        "create_connected_site",
        json_schema_extra={
            "const": "create_connected_site",
            "ui:hidden": True,
            "x-category": "Connected Site",
            "x-is-trigger": False,
            "x-display-name": "Create Connected Site",
        },
        title="Create Connected Site",
    )
    foreign_id: str = Field(..., title="Unique identifier")
    domain: str = Field(..., title="Site domain")


class MailchimpGetConnectedSiteConfig(BaseModel):
    """Get information about a specific connected site."""

    operation: Literal["fetch_connected_site"] = Field(
        "fetch_connected_site",
        json_schema_extra={
            "const": "fetch_connected_site",
            "ui:hidden": True,
            "x-category": "Connected Site",
            "x-is-trigger": False,
            "x-display-name": "Fetch Connected Site",
        },
        title="Fetch Connected Site",
    )
    site_id: str = Field(..., title="Connected site ID")


class MailchimpUpdateConnectedSiteConfig(BaseModel):
    """Update a connected site."""

    operation: Literal["update_connected_site"] = Field(
        "update_connected_site",
        json_schema_extra={
            "const": "update_connected_site",
            "ui:hidden": True,
            "x-category": "Connected Site",
            "x-is-trigger": False,
            "x-display-name": "Update Connected Site",
        },
        title="Update Connected Site",
    )
    site_id: str = Field(..., title="Connected site ID")
    domain: Optional[str] = Field(None, title="Updated domain")


class MailchimpVerifyScriptInstallationConfig(BaseModel):
    """Verify connected site script installation."""

    operation: Literal["verify_connected_site_script"] = Field(
        "verify_connected_site_script",
        json_schema_extra={
            "const": "verify_connected_site_script",
            "ui:hidden": True,
            "x-category": "Connected Site",
            "x-is-trigger": False,
            "x-display-name": "Verify Connected Site Script",
        },
        title="Verify Connected Site Script",
    )
    site_id: str = Field(..., title="Connected site ID")


class MailchimpDeleteConnectedSiteConfig(BaseModel):
    """Delete a connected site."""

    operation: Literal["delete_connected_site"] = Field(
        "delete_connected_site",
        json_schema_extra={
            "const": "delete_connected_site",
            "ui:hidden": True,
            "x-category": "Connected Site",
            "x-is-trigger": False,
            "x-display-name": "Delete Connected Site",
        },
        title="Delete Connected Site",
    )
    site_id: str = Field(..., title="Connected site ID")


class MailchimpListConversationsConfig(BaseModel):
    """List all conversations."""

    operation: Literal["list_conversations"] = Field(
        "list_conversations",
        json_schema_extra={
            "const": "list_conversations",
            "ui:hidden": True,
            "x-category": "Conversation",
            "x-is-trigger": False,
            "x-display-name": "List Conversations",
        },
        title="List Conversations",
    )
    count: int = Field(10, title="Number of records", ge=1, le=1000)
    offset: int = Field(0, title="Number to skip", ge=0)


class MailchimpGetConversationConfig(BaseModel):
    """Get information about a specific conversation."""

    operation: Literal["fetch_conversation"] = Field(
        "fetch_conversation",
        json_schema_extra={
            "const": "fetch_conversation",
            "ui:hidden": True,
            "x-category": "Conversation",
            "x-is-trigger": False,
            "x-display-name": "Fetch Conversation",
        },
        title="Fetch Conversation",
    )
    conversation_id: str = Field(..., title="Conversation ID")


class MailchimpListConversationMessagesConfig(BaseModel):
    """List all messages in a conversation."""

    operation: Literal["list_conversation_messages"] = Field(
        "list_conversation_messages",
        json_schema_extra={
            "const": "list_conversation_messages",
            "ui:hidden": True,
            "x-category": "Conversation",
            "x-is-trigger": False,
            "x-display-name": "List Conversation Messages",
        },
        title="List Conversation Messages",
    )
    conversation_id: str = Field(..., title="Conversation ID")
    count: int = Field(10, title="Number of records", ge=1, le=1000)
    offset: int = Field(0, title="Number to skip", ge=0)


class MailchimpCreateConversationMessageConfig(BaseModel):
    """Add a message to a conversation."""

    operation: Literal["post_conversation_message"] = Field(
        "post_conversation_message",
        json_schema_extra={
            "const": "post_conversation_message",
            "ui:hidden": True,
            "x-category": "Conversation",
            "x-is-trigger": False,
            "x-display-name": "Post Conversation Message",
        },
        title="Post Conversation Message",
    )
    conversation_id: str = Field(..., title="Conversation ID")
    from_email: str = Field(..., title="From email address")
    read: bool = Field(False, title="Mark as read")


class MailchimpGetConversationMessageConfig(BaseModel):
    """Get a specific conversation message."""

    operation: Literal["fetch_conversation_message"] = Field(
        "fetch_conversation_message",
        json_schema_extra={
            "const": "fetch_conversation_message",
            "ui:hidden": True,
            "x-category": "Conversation",
            "x-is-trigger": False,
            "x-display-name": "Fetch Conversation Message",
        },
        title="Fetch Conversation Message",
    )
    conversation_id: str = Field(..., title="Conversation ID")
    message_id: str = Field(..., title="Message ID")


class MailchimpTriggerCustomerJourneyStepConfig(BaseModel):
    """Trigger a step in a customer journey."""

    operation: Literal["trigger_customer_journey_step"] = Field(
        "trigger_customer_journey_step",
        json_schema_extra={
            "const": "trigger_customer_journey_step",
            "ui:hidden": True,
            "x-category": "Member",
            "x-is-trigger": False,
            "x-display-name": "Trigger Customer Journey Step",
        },
        title="Trigger Customer Journey Step",
    )
    journey_id: str = Field(..., title="Customer journey ID")
    step_id: str = Field(..., title="Step ID")
    email_address: str = Field(..., title="Subscriber email")


class MailchimpListFolderFilesConfig(BaseModel):
    """List all files in a folder."""

    operation: Literal["list_files_in_folder"] = Field(
        "list_files_in_folder",
        json_schema_extra={
            "const": "list_files_in_folder",
            "ui:hidden": True,
            "x-category": "File",
            "x-is-trigger": False,
            "x-display-name": "List Files in Folder",
        },
        title="List Files in Folder",
    )
    folder_id: str = Field(..., title="Folder ID")
    count: int = Field(10, title="Number of records", ge=1, le=1000)
    offset: int = Field(0, title="Number to skip", ge=0)


class MailchimpGetLandingPageContentConfig(BaseModel):
    """Get landing page content."""

    operation: Literal["fetch_landing_page_content"] = Field(
        "fetch_landing_page_content",
        json_schema_extra={
            "const": "fetch_landing_page_content",
            "ui:hidden": True,
            "x-category": "Landing Page",
            "x-is-trigger": False,
            "x-display-name": "Fetch Landing Page Content",
        },
        title="Fetch Landing Page Content",
    )
    page_id: str = Field(..., title="Landing page ID")


class MailchimpUpdateLandingPageContentConfig(BaseModel):
    """Update landing page content."""

    operation: Literal["update_landing_page_html"] = Field(
        "update_landing_page_html",
        json_schema_extra={
            "const": "update_landing_page_html",
            "ui:hidden": True,
            "x-category": "Landing Page",
            "x-is-trigger": False,
            "x-display-name": "Update Landing Page Html",
        },
        title="Update Landing Page Html",
    )
    page_id: str = Field(..., title="Landing page ID")
    html: Optional[str] = Field(None, title="HTML content")


class MailchimpPublishLandingPageConfig(BaseModel):
    """Publish a landing page."""

    operation: Literal["publish_landing_page"] = Field(
        "publish_landing_page",
        json_schema_extra={
            "const": "publish_landing_page",
            "ui:hidden": True,
            "x-category": "Landing Page",
            "x-is-trigger": False,
            "x-display-name": "Publish Landing Page",
        },
        title="Publish Landing Page",
    )
    page_id: str = Field(..., title="Landing page ID")


class MailchimpUnpublishLandingPageConfig(BaseModel):
    """Unpublish a landing page."""

    operation: Literal["unpublish_landing_page"] = Field(
        "unpublish_landing_page",
        json_schema_extra={
            "const": "unpublish_landing_page",
            "ui:hidden": True,
            "x-category": "Landing Page",
            "x-is-trigger": False,
            "x-display-name": "Unpublish Landing Page",
        },
        title="Unpublish Landing Page",
    )
    page_id: str = Field(..., title="Landing page ID")


class MailchimpListAbuseReportsConfig(BaseModel):
    """Get abuse reports for a list."""

    operation: Literal["list_abuse_reports"] = Field(
        "list_abuse_reports",
        json_schema_extra={
            "const": "list_abuse_reports",
            "ui:hidden": True,
            "x-category": "Abuse Report",
            "x-is-trigger": False,
            "x-display-name": "List Abuse Reports",
        },
        title="List Abuse Reports",
    )
    list_id: str = Field(..., title="List ID")
    count: int = Field(10, title="Number of records", ge=1, le=1000)
    offset: int = Field(0, title="Number to skip", ge=0)


class MailchimpGetAbuseReportConfig(BaseModel):
    """Get a specific abuse report."""

    operation: Literal["fetch_abuse_report"] = Field(
        "fetch_abuse_report",
        json_schema_extra={
            "const": "fetch_abuse_report",
            "ui:hidden": True,
            "x-category": "Abuse Report",
            "x-is-trigger": False,
            "x-display-name": "Fetch Abuse Report",
        },
        title="Fetch Abuse Report",
    )
    list_id: str = Field(..., title="List ID")
    report_id: str = Field(..., title="Report ID")


class MailchimpGetListActivityConfig(BaseModel):
    """Get recent activity for a list."""

    operation: Literal["fetch_list_activity"] = Field(
        "fetch_list_activity",
        json_schema_extra={
            "const": "fetch_list_activity",
            "ui:hidden": True,
            "x-category": "List",
            "x-is-trigger": False,
            "x-display-name": "Fetch List Activity",
        },
        title="Fetch List Activity",
    )
    list_id: str = Field(..., title="List ID")


class MailchimpGetListClientsConfig(BaseModel):
    """Get top email clients for a list."""

    operation: Literal["fetch_list_email_clients"] = Field(
        "fetch_list_email_clients",
        json_schema_extra={
            "const": "fetch_list_email_clients",
            "ui:hidden": True,
            "x-category": "List",
            "x-is-trigger": False,
            "x-display-name": "Fetch List Email Clients",
        },
        title="Fetch List Email Clients",
    )
    list_id: str = Field(..., title="List ID")


class MailchimpListGrowthHistoryConfig(BaseModel):
    """Get growth history for a list."""

    operation: Literal["list_growth_history"] = Field(
        "list_growth_history",
        json_schema_extra={
            "const": "list_growth_history",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "List Growth History",
        },
        title="List Growth History",
    )
    list_id: str = Field(..., title="List ID")
    count: int = Field(10, title="Number of records", ge=1, le=1000)
    offset: int = Field(0, title="Number to skip", ge=0)


class MailchimpGetGrowthHistoryMonthConfig(BaseModel):
    """Get growth history for a specific month."""

    operation: Literal["fetch_growth_history_for_month"] = Field(
        "fetch_growth_history_for_month",
        json_schema_extra={
            "const": "fetch_growth_history_for_month",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Fetch Growth History for Month",
        },
        title="Fetch Growth History for Month",
    )
    list_id: str = Field(..., title="List ID")
    month: str = Field(..., title="Month (YYYY-MM)")


class MailchimpListSegmentMembersConfig(BaseModel):
    """List members in a segment."""

    operation: Literal["list_segment_members"] = Field(
        "list_segment_members",
        json_schema_extra={
            "const": "list_segment_members",
            "ui:hidden": True,
            "x-category": "Segment",
            "x-is-trigger": False,
            "x-display-name": "List Segment Members",
        },
        title="List Segment Members",
    )
    list_id: str = Field(..., title="List ID")
    segment_id: str = Field(..., title="Segment ID")
    count: int = Field(10, title="Number of records", ge=1, le=1000)
    offset: int = Field(0, title="Number to skip", ge=0)


class MailchimpCreateSegmentMemberConfig(BaseModel):
    """Add a member to a static segment."""

    operation: Literal["add_member_to_segment"] = Field(
        "add_member_to_segment",
        json_schema_extra={
            "const": "add_member_to_segment",
            "ui:hidden": True,
            "x-category": "Segment",
            "x-is-trigger": False,
            "x-display-name": "Add Member to Segment",
        },
        title="Add Member to Segment",
    )
    list_id: str = Field(..., title="List ID")
    segment_id: str = Field(..., title="Segment ID")
    email_address: str = Field(..., title="Member email address")


class MailchimpGetSegmentMemberConfig(BaseModel):
    """Get information about a segment member."""

    operation: Literal["fetch_segment_member"] = Field(
        "fetch_segment_member",
        json_schema_extra={
            "const": "fetch_segment_member",
            "ui:hidden": True,
            "x-category": "Segment",
            "x-is-trigger": False,
            "x-display-name": "Fetch Segment Member",
        },
        title="Fetch Segment Member",
    )
    list_id: str = Field(..., title="List ID")
    segment_id: str = Field(..., title="Segment ID")
    email_address: str = Field(..., title="Member email address")


class MailchimpDeleteSegmentMemberConfig(BaseModel):
    """Remove a member from a static segment."""

    operation: Literal["remove_member_from_segment"] = Field(
        "remove_member_from_segment",
        json_schema_extra={
            "const": "remove_member_from_segment",
            "ui:hidden": True,
            "x-category": "Segment",
            "x-is-trigger": False,
            "x-display-name": "Remove Member from Segment",
        },
        title="Remove Member from Segment",
    )
    list_id: str = Field(..., title="List ID")
    segment_id: str = Field(..., title="Segment ID")
    email_address: str = Field(..., title="Member email address")


class MailchimpGetMemberActivityConfig(BaseModel):
    """Get recent activity for a list member."""

    operation: Literal["fetch_member_activity"] = Field(
        "fetch_member_activity",
        json_schema_extra={
            "const": "fetch_member_activity",
            "ui:hidden": True,
            "x-category": "Member",
            "x-is-trigger": False,
            "x-display-name": "Fetch Member Activity",
        },
        title="Fetch Member Activity",
    )
    list_id: str = Field(..., title="List ID")
    email_address: str = Field(..., title="Member email address")


class MailchimpListMemberActivityFeedConfig(BaseModel):
    """Get activity feed for a list member."""

    operation: Literal["list_member_activity_feed"] = Field(
        "list_member_activity_feed",
        json_schema_extra={
            "const": "list_member_activity_feed",
            "ui:hidden": True,
            "x-category": "Member",
            "x-is-trigger": False,
            "x-display-name": "List Member Activity Feed",
        },
        title="List Member Activity Feed",
    )
    list_id: str = Field(..., title="List ID")
    email_address: str = Field(..., title="Member email address")
    count: int = Field(10, title="Number of records", ge=1, le=1000)
    offset: int = Field(0, title="Number to skip", ge=0)


class MailchimpGetMemberGoalsConfig(BaseModel):
    """Get goals for a list member."""

    operation: Literal["fetch_member_goals"] = Field(
        "fetch_member_goals",
        json_schema_extra={
            "const": "fetch_member_goals",
            "ui:hidden": True,
            "x-category": "Member",
            "x-is-trigger": False,
            "x-display-name": "Fetch Member Goals",
        },
        title="Fetch Member Goals",
    )
    list_id: str = Field(..., title="List ID")
    email_address: str = Field(..., title="Member email address")


class MailchimpListMemberNotesConfig(BaseModel):
    """Get notes for a list member."""

    operation: Literal["list_member_notes"] = Field(
        "list_member_notes",
        json_schema_extra={
            "const": "list_member_notes",
            "ui:hidden": True,
            "x-category": "Member",
            "x-is-trigger": False,
            "x-display-name": "List Member Notes",
        },
        title="List Member Notes",
    )
    list_id: str = Field(..., title="List ID")
    email_address: str = Field(..., title="Member email address")
    count: int = Field(10, title="Number of records", ge=1, le=1000)
    offset: int = Field(0, title="Number to skip", ge=0)


class MailchimpCreateMemberNoteConfig(BaseModel):
    """Add a note to a list member."""

    operation: Literal["add_member_note"] = Field(
        "add_member_note",
        json_schema_extra={
            "const": "add_member_note",
            "ui:hidden": True,
            "x-category": "Member",
            "x-is-trigger": False,
            "x-display-name": "Add Member Note",
        },
        title="Add Member Note",
    )
    list_id: str = Field(..., title="List ID")
    email_address: str = Field(..., title="Member email address")
    note: str = Field(..., title="Note content")


class MailchimpGetMemberNoteConfig(BaseModel):
    """Get a specific member note."""

    operation: Literal["fetch_member_note"] = Field(
        "fetch_member_note",
        json_schema_extra={
            "const": "fetch_member_note",
            "ui:hidden": True,
            "x-category": "Member",
            "x-is-trigger": False,
            "x-display-name": "Fetch Member Note",
        },
        title="Fetch Member Note",
    )
    list_id: str = Field(..., title="List ID")
    email_address: str = Field(..., title="Member email address")
    note_id: str = Field(..., title="Note ID")


class MailchimpUpdateMemberNoteConfig(BaseModel):
    """Update a member note."""

    operation: Literal["update_member_note"] = Field(
        "update_member_note",
        json_schema_extra={
            "const": "update_member_note",
            "ui:hidden": True,
            "x-category": "Member",
            "x-is-trigger": False,
            "x-display-name": "Update Member Note",
        },
        title="Update Member Note",
    )
    list_id: str = Field(..., title="List ID")
    email_address: str = Field(..., title="Member email address")
    note_id: str = Field(..., title="Note ID")
    note: str = Field(..., title="Updated note content")


class MailchimpDeleteMemberNoteConfig(BaseModel):
    """Delete a member note."""

    operation: Literal["delete_member_note"] = Field(
        "delete_member_note",
        json_schema_extra={
            "const": "delete_member_note",
            "ui:hidden": True,
            "x-category": "Member",
            "x-is-trigger": False,
            "x-display-name": "Delete Member Note",
        },
        title="Delete Member Note",
    )
    list_id: str = Field(..., title="List ID")
    email_address: str = Field(..., title="Member email address")
    note_id: str = Field(..., title="Note ID")


class MailchimpCreateMemberEventConfig(BaseModel):
    """Add an event for a list member."""

    operation: Literal["create_member_event"] = Field(
        "create_member_event",
        json_schema_extra={
            "const": "create_member_event",
            "ui:hidden": True,
            "x-category": "Member",
            "x-is-trigger": False,
            "x-display-name": "Create Member Event",
        },
        title="Create Member Event",
    )
    list_id: str = Field(..., title="List ID")
    email_address: str = Field(..., title="Member email address")
    name: str = Field(..., title="Event name")
    properties: Optional[Dict[str, Any]] = Field(None, title="Event properties (JSON)")


class MailchimpGetSignupFormsConfig(BaseModel):
    """Get signup forms for a list."""

    operation: Literal["fetch_signup_forms"] = Field(
        "fetch_signup_forms",
        json_schema_extra={
            "const": "fetch_signup_forms",
            "ui:hidden": True,
            "x-category": "Signup Form",
            "x-is-trigger": False,
            "x-display-name": "Fetch Signup Forms",
        },
        title="Fetch Signup Forms",
    )
    list_id: str = Field(..., title="List ID")


class MailchimpGetListLocationsConfig(BaseModel):
    """Get subscriber locations for a list."""

    operation: Literal["fetch_list_subscriber_locations"] = Field(
        "fetch_list_subscriber_locations",
        json_schema_extra={
            "const": "fetch_list_subscriber_locations",
            "ui:hidden": True,
            "x-category": "List",
            "x-is-trigger": False,
            "x-display-name": "Fetch List Subscriber Locations",
        },
        title="Fetch List Subscriber Locations",
    )
    list_id: str = Field(..., title="List ID")


class MailchimpListSurveysConfig(BaseModel):
    """List all surveys for a list."""

    operation: Literal["list_surveys"] = Field(
        "list_surveys",
        json_schema_extra={
            "const": "list_surveys",
            "ui:hidden": True,
            "x-category": "Survey",
            "x-is-trigger": False,
            "x-display-name": "List Surveys",
        },
        title="List Surveys",
    )
    list_id: str = Field(..., title="List ID")


class MailchimpCreateSurveyConfig(BaseModel):
    """Create a new survey."""

    operation: Literal["create_survey"] = Field(
        "create_survey",
        json_schema_extra={
            "const": "create_survey",
            "ui:hidden": True,
            "x-category": "Survey",
            "x-is-trigger": False,
            "x-display-name": "Create Survey",
        },
        title="Create Survey",
    )
    list_id: str = Field(..., title="List ID")
    title: str = Field(..., title="Survey title")


class MailchimpGetSurveyConfig(BaseModel):
    """Get information about a specific survey."""

    operation: Literal["fetch_survey"] = Field(
        "fetch_survey",
        json_schema_extra={
            "const": "fetch_survey",
            "ui:hidden": True,
            "x-category": "Survey",
            "x-is-trigger": False,
            "x-display-name": "Fetch Survey",
        },
        title="Fetch Survey",
    )
    list_id: str = Field(..., title="List ID")
    survey_id: str = Field(..., title="Survey ID")


class MailchimpUpdateSurveyConfig(BaseModel):
    """Update a survey."""

    operation: Literal["update_survey"] = Field(
        "update_survey",
        json_schema_extra={
            "const": "update_survey",
            "ui:hidden": True,
            "x-category": "Survey",
            "x-is-trigger": False,
            "x-display-name": "Update Survey",
        },
        title="Update Survey",
    )
    list_id: str = Field(..., title="List ID")
    survey_id: str = Field(..., title="Survey ID")
    title: Optional[str] = Field(None, title="Updated survey title")


class MailchimpPublishSurveyConfig(BaseModel):
    """Publish a survey."""

    operation: Literal["publish_survey"] = Field(
        "publish_survey",
        json_schema_extra={
            "const": "publish_survey",
            "ui:hidden": True,
            "x-category": "Survey",
            "x-is-trigger": False,
            "x-display-name": "Publish Survey",
        },
        title="Publish Survey",
    )
    list_id: str = Field(..., title="List ID")
    survey_id: str = Field(..., title="Survey ID")


class MailchimpUnpublishSurveyConfig(BaseModel):
    """Unpublish a survey."""

    operation: Literal["unpublish_survey"] = Field(
        "unpublish_survey",
        json_schema_extra={
            "const": "unpublish_survey",
            "ui:hidden": True,
            "x-category": "Survey",
            "x-is-trigger": False,
            "x-display-name": "Unpublish Survey",
        },
        title="Unpublish Survey",
    )
    list_id: str = Field(..., title="List ID")
    survey_id: str = Field(..., title="Survey ID")


class MailchimpCreateSurveyEmailConfig(BaseModel):
    """Send a survey email."""

    operation: Literal["send_survey_email"] = Field(
        "send_survey_email",
        json_schema_extra={
            "const": "send_survey_email",
            "ui:hidden": True,
            "x-category": "Survey",
            "x-is-trigger": False,
            "x-display-name": "Send Survey Email",
        },
        title="Send Survey Email",
    )
    list_id: str = Field(..., title="List ID")
    survey_id: str = Field(..., title="Survey ID")
    subject_line: Optional[str] = Field(None, title="Email subject")


class MailchimpDeleteSurveyConfig(BaseModel):
    """Delete a survey."""

    operation: Literal["delete_survey"] = Field(
        "delete_survey",
        json_schema_extra={
            "const": "delete_survey",
            "ui:hidden": True,
            "x-category": "Survey",
            "x-is-trigger": False,
            "x-display-name": "Delete Survey",
        },
        title="Delete Survey",
    )
    list_id: str = Field(..., title="List ID")
    survey_id: str = Field(..., title="Survey ID")


class MailchimpGetCampaignSubReportsConfig(BaseModel):
    """Get sub-reports for a campaign."""

    operation: Literal["fetch_campaign_subreports"] = Field(
        "fetch_campaign_subreports",
        json_schema_extra={
            "const": "fetch_campaign_subreports",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Fetch Campaign Subreports",
        },
        title="Fetch Campaign Subreports",
    )
    campaign_id: str = Field(..., title="Campaign ID")


class MailchimpGetCampaignAdviceConfig(BaseModel):
    """Get advice for improving a campaign."""

    operation: Literal["fetch_campaign_advice"] = Field(
        "fetch_campaign_advice",
        json_schema_extra={
            "const": "fetch_campaign_advice",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Fetch Campaign Advice",
        },
        title="Fetch Campaign Advice",
    )
    campaign_id: str = Field(..., title="Campaign ID")


class MailchimpGetEcommerceProductActivityReportConfig(BaseModel):
    """Get product activity report."""

    operation: Literal["fetch_product_activity_report"] = Field(
        "fetch_product_activity_report",
        json_schema_extra={
            "const": "fetch_product_activity_report",
            "ui:hidden": True,
            "x-category": "E-commerce Product",
            "x-is-trigger": False,
            "x-display-name": "Fetch Product Activity Report",
        },
        title="Fetch Product Activity Report",
    )
    campaign_id: str = Field(..., title="Campaign ID")


class MailchimpGetTemplateDefaultContentConfig(BaseModel):
    """Get default content for a template."""

    operation: Literal["fetch_template_default_content"] = Field(
        "fetch_template_default_content",
        json_schema_extra={
            "const": "fetch_template_default_content",
            "ui:hidden": True,
            "x-category": "Template",
            "x-is-trigger": False,
            "x-display-name": "Fetch Template Default Content",
        },
        title="Fetch Template Default Content",
    )
    template_id: str = Field(..., title="Template ID")


class MailchimpUpdateTemplateDefaultContentConfig(BaseModel):
    """Update default content for a template."""

    operation: Literal["update_template_default_content"] = Field(
        "update_template_default_content",
        json_schema_extra={
            "const": "update_template_default_content",
            "ui:hidden": True,
            "x-category": "Template",
            "x-is-trigger": False,
            "x-display-name": "Update Template Default Content",
        },
        title="Update Template Default Content",
    )
    template_id: str = Field(..., title="Template ID")
    sections: Optional[Dict[str, Any]] = Field(None, title="Template sections")


class MailchimpGetOrderLineConfig(BaseModel):
    """Get information about a specific order line."""

    operation: Literal["fetch_order_line_item"] = Field(
        "fetch_order_line_item",
        json_schema_extra={
            "const": "fetch_order_line_item",
            "ui:hidden": True,
            "x-category": "E-commerce Order",
            "x-is-trigger": False,
            "x-display-name": "Fetch Order Line Item",
        },
        title="Fetch Order Line Item",
    )
    store_id: str = Field(..., title="Store ID")
    order_id: str = Field(..., title="Order ID")
    line_id: str = Field(..., title="Line ID")


class MailchimpUpdateOrderLineConfig(BaseModel):
    """Update an order line."""

    operation: Literal["update_order_line_item"] = Field(
        "update_order_line_item",
        json_schema_extra={
            "const": "update_order_line_item",
            "ui:hidden": True,
            "x-category": "E-commerce Order",
            "x-is-trigger": False,
            "x-display-name": "Update Order Line Item",
        },
        title="Update Order Line Item",
    )
    store_id: str = Field(..., title="Store ID")
    order_id: str = Field(..., title="Order ID")
    line_id: str = Field(..., title="Line ID")
    quantity: Optional[int] = Field(None, title="Line quantity")


class MailchimpDeleteOrderLineConfig(BaseModel):
    """Delete an order line."""

    operation: Literal["delete_order_line_item"] = Field(
        "delete_order_line_item",
        json_schema_extra={
            "const": "delete_order_line_item",
            "ui:hidden": True,
            "x-category": "E-commerce Order",
            "x-is-trigger": False,
            "x-display-name": "Delete Order Line Item",
        },
        title="Delete Order Line Item",
    )
    store_id: str = Field(..., title="Store ID")
    order_id: str = Field(..., title="Order ID")
    line_id: str = Field(..., title="Line ID")


class MailchimpGetCartLineConfig(BaseModel):
    """Get information about a specific cart line."""

    operation: Literal["fetch_cart_line_item"] = Field(
        "fetch_cart_line_item",
        json_schema_extra={
            "const": "fetch_cart_line_item",
            "ui:hidden": True,
            "x-category": "E-commerce Cart",
            "x-is-trigger": False,
            "x-display-name": "Fetch Cart Line Item",
        },
        title="Fetch Cart Line Item",
    )
    store_id: str = Field(..., title="Store ID")
    cart_id: str = Field(..., title="Cart ID")
    line_id: str = Field(..., title="Line ID")


class MailchimpUpdateCartLineConfig(BaseModel):
    """Update a cart line."""

    operation: Literal["update_cart_line_item"] = Field(
        "update_cart_line_item",
        json_schema_extra={
            "const": "update_cart_line_item",
            "ui:hidden": True,
            "x-category": "E-commerce Cart",
            "x-is-trigger": False,
            "x-display-name": "Update Cart Line Item",
        },
        title="Update Cart Line Item",
    )
    store_id: str = Field(..., title="Store ID")
    cart_id: str = Field(..., title="Cart ID")
    line_id: str = Field(..., title="Line ID")
    quantity: Optional[int] = Field(None, title="Line quantity")


class MailchimpDeleteCartLineConfig(BaseModel):
    """Delete a cart line."""

    operation: Literal["delete_cart_line_item"] = Field(
        "delete_cart_line_item",
        json_schema_extra={
            "const": "delete_cart_line_item",
            "ui:hidden": True,
            "x-category": "E-commerce Cart",
            "x-is-trigger": False,
            "x-display-name": "Delete Cart Line Item",
        },
        title="Delete Cart Line Item",
    )
    store_id: str = Field(..., title="Store ID")
    cart_id: str = Field(..., title="Cart ID")
    line_id: str = Field(..., title="Line ID")


class MailchimpListAllEcommerceOrdersConfig(BaseModel):
    """List all orders across all stores."""

    operation: Literal["list_all_ecommerce_orders"] = Field(
        "list_all_ecommerce_orders",
        json_schema_extra={
            "const": "list_all_ecommerce_orders",
            "ui:hidden": True,
            "x-category": "E-commerce Order",
            "x-is-trigger": False,
            "x-display-name": "List All Ecommerce Orders",
        },
        title="List All Ecommerce Orders",
    )
    count: int = Field(10, title="Number of records", ge=1, le=1000)
    offset: int = Field(0, title="Number to skip", ge=0)


class MailchimpListFacebookAdsConfig(BaseModel):
    """List all Facebook ads."""

    operation: Literal["list_facebook_ads"] = Field(
        "list_facebook_ads",
        json_schema_extra={
            "const": "list_facebook_ads",
            "ui:hidden": True,
            "x-category": "Facebook Ad",
            "x-is-trigger": False,
            "x-display-name": "List Facebook Ads",
        },
        title="List Facebook Ads",
    )
    count: int = Field(10, title="Number of records", ge=1, le=1000)
    offset: int = Field(0, title="Number to skip", ge=0)


class MailchimpGetFacebookAdConfig(BaseModel):
    """Get information about a specific Facebook ad."""

    operation: Literal["fetch_facebook_ad"] = Field(
        "fetch_facebook_ad",
        json_schema_extra={
            "const": "fetch_facebook_ad",
            "ui:hidden": True,
            "x-category": "Facebook Ad",
            "x-is-trigger": False,
            "x-display-name": "Fetch Facebook Ad",
        },
        title="Fetch Facebook Ad",
    )
    ad_id: str = Field(..., title="Facebook ad ID")


class MailchimpSearchCampaignsConfig(BaseModel):
    """Search for campaigns."""

    operation: Literal["search_campaigns_by_name"] = Field(
        "search_campaigns_by_name",
        json_schema_extra={
            "const": "search_campaigns_by_name",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Search Campaigns by Name",
        },
        title="Search Campaigns by Name",
    )
    query: str = Field(..., title="Search query", description="Search query term")


class MailchimpSearchMembersConfig(BaseModel):
    """Search for list members."""

    operation: Literal["search_list_members"] = Field(
        "search_list_members",
        json_schema_extra={
            "const": "search_list_members",
            "ui:hidden": True,
            "x-category": "Member",
            "x-is-trigger": False,
            "x-display-name": "Search List Members",
        },
        title="Search List Members",
    )
    query: str = Field(..., title="Search query", description="Search query term")
    list_id: Optional[str] = Field(
        None, title="List ID (optional)", description="Filter to specific list"
    )


class MailchimpListFacebookAdReportsConfig(BaseModel):
    """List Facebook ad reports."""

    operation: Literal["list_facebook_ad_reports"] = Field(
        "list_facebook_ad_reports",
        json_schema_extra={
            "const": "list_facebook_ad_reports",
            "ui:hidden": True,
            "x-category": "Facebook Ad",
            "x-is-trigger": False,
            "x-display-name": "List Facebook Ad Reports",
        },
        title="List Facebook Ad Reports",
    )
    count: int = Field(10, title="Number of records", ge=1, le=1000)
    offset: int = Field(0, title="Number to skip", ge=0)


class MailchimpGetFacebookAdReportConfig(BaseModel):
    """Get a specific Facebook ad report."""

    operation: Literal["fetch_facebook_ad_report"] = Field(
        "fetch_facebook_ad_report",
        json_schema_extra={
            "const": "fetch_facebook_ad_report",
            "ui:hidden": True,
            "x-category": "Facebook Ad",
            "x-is-trigger": False,
            "x-display-name": "Fetch Facebook Ad Report",
        },
        title="Fetch Facebook Ad Report",
    )
    ad_id: str = Field(..., title="Facebook ad ID")


class MailchimpGetFacebookAdEcommerceActivityConfig(BaseModel):
    """Get e-commerce activity for a Facebook ad."""

    operation: Literal["fetch_facebook_ad_ecommerce_activity"] = Field(
        "fetch_facebook_ad_ecommerce_activity",
        json_schema_extra={
            "const": "fetch_facebook_ad_ecommerce_activity",
            "ui:hidden": True,
            "x-category": "Facebook Ad",
            "x-is-trigger": False,
            "x-display-name": "Fetch Facebook Ad Ecommerce Activity",
        },
        title="Fetch Facebook Ad Ecommerce Activity",
    )
    ad_id: str = Field(..., title="Facebook ad ID")


class MailchimpListLandingPageReportsConfig(BaseModel):
    """List landing page reports."""

    operation: Literal["list_landing_page_reports"] = Field(
        "list_landing_page_reports",
        json_schema_extra={
            "const": "list_landing_page_reports",
            "ui:hidden": True,
            "x-category": "Landing Page",
            "x-is-trigger": False,
            "x-display-name": "List Landing Page Reports",
        },
        title="List Landing Page Reports",
    )
    count: int = Field(10, title="Number of records", ge=1, le=1000)
    offset: int = Field(0, title="Number to skip", ge=0)


class MailchimpGetLandingPageReportConfig(BaseModel):
    """Get a specific landing page report."""

    operation: Literal["fetch_landing_page_report"] = Field(
        "fetch_landing_page_report",
        json_schema_extra={
            "const": "fetch_landing_page_report",
            "ui:hidden": True,
            "x-category": "Landing Page",
            "x-is-trigger": False,
            "x-display-name": "Fetch Landing Page Report",
        },
        title="Fetch Landing Page Report",
    )
    page_id: str = Field(..., title="Landing page ID")


class MailchimpListSurveyReportsConfig(BaseModel):
    """List survey reports."""

    operation: Literal["list_survey_reports"] = Field(
        "list_survey_reports",
        json_schema_extra={
            "const": "list_survey_reports",
            "ui:hidden": True,
            "x-category": "Survey",
            "x-is-trigger": False,
            "x-display-name": "List Survey Reports",
        },
        title="List Survey Reports",
    )


class MailchimpGetSurveyReportConfig(BaseModel):
    """Get a specific survey report."""

    operation: Literal["fetch_survey_report"] = Field(
        "fetch_survey_report",
        json_schema_extra={
            "const": "fetch_survey_report",
            "ui:hidden": True,
            "x-category": "Survey",
            "x-is-trigger": False,
            "x-display-name": "Fetch Survey Report",
        },
        title="Fetch Survey Report",
    )
    survey_id: str = Field(..., title="Survey ID")


class MailchimpListSurveyQuestionsConfig(BaseModel):
    """List all questions in a survey."""

    operation: Literal["list_survey_questions"] = Field(
        "list_survey_questions",
        json_schema_extra={
            "const": "list_survey_questions",
            "ui:hidden": True,
            "x-category": "Survey",
            "x-is-trigger": False,
            "x-display-name": "List Survey Questions",
        },
        title="List Survey Questions",
    )
    survey_id: str = Field(..., title="Survey ID")


class MailchimpGetSurveyQuestionConfig(BaseModel):
    """Get information about a specific survey question."""

    operation: Literal["fetch_survey_question"] = Field(
        "fetch_survey_question",
        json_schema_extra={
            "const": "fetch_survey_question",
            "ui:hidden": True,
            "x-category": "Survey",
            "x-is-trigger": False,
            "x-display-name": "Fetch Survey Question",
        },
        title="Fetch Survey Question",
    )
    survey_id: str = Field(..., title="Survey ID")
    question_id: str = Field(..., title="Question ID")


class MailchimpListSurveyAnswersConfig(BaseModel):
    """List all answers for a survey question."""

    operation: Literal["list_survey_question_answers"] = Field(
        "list_survey_question_answers",
        json_schema_extra={
            "const": "list_survey_question_answers",
            "ui:hidden": True,
            "x-category": "Survey",
            "x-is-trigger": False,
            "x-display-name": "List Survey Question Answers",
        },
        title="List Survey Question Answers",
    )
    survey_id: str = Field(..., title="Survey ID")
    question_id: str = Field(..., title="Question ID")


class MailchimpListSurveyResponsesConfig(BaseModel):
    """List all responses to a survey."""

    operation: Literal["list_survey_responses"] = Field(
        "list_survey_responses",
        json_schema_extra={
            "const": "list_survey_responses",
            "ui:hidden": True,
            "x-category": "Survey",
            "x-is-trigger": False,
            "x-display-name": "List Survey Responses",
        },
        title="List Survey Responses",
    )
    survey_id: str = Field(..., title="Survey ID")


class MailchimpGetSurveyResponseConfig(BaseModel):
    """Get a specific survey response."""

    operation: Literal["fetch_survey_response"] = Field(
        "fetch_survey_response",
        json_schema_extra={
            "const": "fetch_survey_response",
            "ui:hidden": True,
            "x-category": "Survey",
            "x-is-trigger": False,
            "x-display-name": "Fetch Survey Response",
        },
        title="Fetch Survey Response",
    )
    survey_id: str = Field(..., title="Survey ID")
    response_id: str = Field(..., title="Response ID")


class MailchimpListVerifiedDomainsConfig(BaseModel):
    """List all verified domains."""

    operation: Literal["list_verified_domains"] = Field(
        "list_verified_domains",
        json_schema_extra={
            "const": "list_verified_domains",
            "ui:hidden": True,
            "x-category": "Domain",
            "x-is-trigger": False,
            "x-display-name": "List Verified Domains",
        },
        title="List Verified Domains",
    )


class MailchimpCreateVerifiedDomainConfig(BaseModel):
    """Add a domain to verify."""

    operation: Literal["add_domain_for_verification"] = Field(
        "add_domain_for_verification",
        json_schema_extra={
            "const": "add_domain_for_verification",
            "ui:hidden": True,
            "x-category": "Domain",
            "x-is-trigger": False,
            "x-display-name": "Add Domain for Verification",
        },
        title="Add Domain for Verification",
    )
    domain: str = Field(..., title="Domain name")


class MailchimpGetVerifiedDomainConfig(BaseModel):
    """Get information about a verified domain."""

    operation: Literal["fetch_verified_domain"] = Field(
        "fetch_verified_domain",
        json_schema_extra={
            "const": "fetch_verified_domain",
            "ui:hidden": True,
            "x-category": "Domain",
            "x-is-trigger": False,
            "x-display-name": "Fetch Verified Domain",
        },
        title="Fetch Verified Domain",
    )
    domain_name: str = Field(..., title="Domain name")


class MailchimpUpdateVerifiedDomainConfig(BaseModel):
    """Update a verified domain."""

    operation: Literal["update_verified_domain"] = Field(
        "update_verified_domain",
        json_schema_extra={
            "const": "update_verified_domain",
            "ui:hidden": True,
            "x-category": "Domain",
            "x-is-trigger": False,
            "x-display-name": "Update Verified Domain",
        },
        title="Update Verified Domain",
    )
    domain_name: str = Field(..., title="Domain name")


class MailchimpDeleteVerifiedDomainConfig(BaseModel):
    """Delete a verified domain."""

    operation: Literal["delete_verified_domain"] = Field(
        "delete_verified_domain",
        json_schema_extra={
            "const": "delete_verified_domain",
            "ui:hidden": True,
            "x-category": "Domain",
            "x-is-trigger": False,
            "x-display-name": "Delete Verified Domain",
        },
        title="Delete Verified Domain",
    )
    domain_name: str = Field(..., title="Domain name")


class MailchimpVerifyDomainConfig(BaseModel):
    """Verify a domain for sending."""

    operation: Literal["verify_domain_for_sending"] = Field(
        "verify_domain_for_sending",
        json_schema_extra={
            "const": "verify_domain_for_sending",
            "ui:hidden": True,
            "x-category": "Domain",
            "x-is-trigger": False,
            "x-display-name": "Verify Domain for Sending",
        },
        title="Verify Domain for Sending",
    )
    domain_name: str = Field(..., title="Domain name")


# Account Exports
class MailchimpListAccountExportsConfig(BaseModel):
    """List account exports."""

    operation: Literal["list_account_exports"] = Field(
        "list_account_exports",
        json_schema_extra={
            "const": "list_account_exports",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "List Account Exports",
        },
        title="List Account Exports",
    )
    count: int = Field(10, title="Count", ge=1, le=1000)
    offset: int = Field(0, title="Offset", ge=0)


class MailchimpCreateAccountExportConfig(BaseModel):
    """Create a new account export."""

    operation: Literal["create_account_export"] = Field(
        "create_account_export",
        json_schema_extra={
            "const": "create_account_export",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Create Account Export",
        },
        title="Create Account Export",
    )
    include_stages: Optional[List[str]] = Field(
        None, title="Include stages", description="Stages to include in the export"
    )
    since_timestamp: Optional[str] = Field(
        None,
        title="Since timestamp",
        description="ISO 8601 timestamp to filter exports",
    )


class MailchimpGetAccountExportConfig(BaseModel):
    """Get information about a specific account export."""

    operation: Literal["fetch_account_export"] = Field(
        "fetch_account_export",
        json_schema_extra={
            "const": "fetch_account_export",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Fetch Account Export",
        },
        title="Fetch Account Export",
    )
    export_id: str = Field(..., title="Export ID")


# Automation Archive
class MailchimpArchiveAutomationConfig(BaseModel):
    """Archive an automation workflow."""

    operation: Literal["archive_automation_workflow"] = Field(
        "archive_automation_workflow",
        json_schema_extra={
            "const": "archive_automation_workflow",
            "ui:hidden": True,
            "x-category": "Automation",
            "x-is-trigger": False,
            "x-display-name": "Archive Automation Workflow",
        },
        title="Archive Automation Workflow",
    )
    workflow_id: str = Field(
        ...,
        title="Workflow ID",
        description="The unique ID for the Automation workflow",
    )


# Campaign Report Granular Member Operations
class MailchimpGetCampaignClickDetailMemberConfig(BaseModel):
    """Get click details for a specific subscriber on a specific link."""

    operation: Literal["fetch_campaign_click_details_for_member"] = Field(
        "fetch_campaign_click_details_for_member",
        json_schema_extra={
            "const": "fetch_campaign_click_details_for_member",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Fetch Campaign Click Details for Member",
        },
        title="Fetch Campaign Click Details for Member",
    )
    campaign_id: str = Field(..., title="Campaign ID")
    link_id: str = Field(..., title="Link ID")
    subscriber_hash: str = Field(
        ..., title="Subscriber Hash", description="MD5 hash of lowercase email"
    )


class MailchimpGetCampaignSentToMemberConfig(BaseModel):
    """Get information about a specific subscriber in a sent-to report."""

    operation: Literal["fetch_campaign_recipient_info"] = Field(
        "fetch_campaign_recipient_info",
        json_schema_extra={
            "const": "fetch_campaign_recipient_info",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Fetch Campaign Recipient Info",
        },
        title="Fetch Campaign Recipient Info",
    )
    campaign_id: str = Field(..., title="Campaign ID")
    subscriber_hash: str = Field(
        ..., title="Subscriber Hash", description="MD5 hash of lowercase email"
    )


class MailchimpGetCampaignUnsubscribedMemberConfig(BaseModel):
    """Get information about a specific unsubscribed member."""

    operation: Literal["fetch_campaign_unsubscribed_member"] = Field(
        "fetch_campaign_unsubscribed_member",
        json_schema_extra={
            "const": "fetch_campaign_unsubscribed_member",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Fetch Campaign Unsubscribed Member",
        },
        title="Fetch Campaign Unsubscribed Member",
    )
    campaign_id: str = Field(..., title="Campaign ID")
    subscriber_hash: str = Field(
        ..., title="Subscriber Hash", description="MD5 hash of lowercase email"
    )


# Conversation Message Operations
class MailchimpUpdateConversationMessageConfig(BaseModel):
    """Update a conversation message."""

    operation: Literal["update_conversation_message"] = Field(
        "update_conversation_message",
        json_schema_extra={
            "const": "update_conversation_message",
            "ui:hidden": True,
            "x-category": "Conversation",
            "x-is-trigger": False,
            "x-display-name": "Update Conversation Message",
        },
        title="Update Conversation Message",
    )
    conversation_id: str = Field(..., title="Conversation ID")
    message_id: str = Field(..., title="Message ID")
    read: bool = Field(..., title="Read", description="Mark message as read/unread")


class MailchimpDeleteConversationMessageConfig(BaseModel):
    """Delete a conversation message."""

    operation: Literal["delete_conversation_message"] = Field(
        "delete_conversation_message",
        json_schema_extra={
            "const": "delete_conversation_message",
            "ui:hidden": True,
            "x-category": "Conversation",
            "x-is-trigger": False,
            "x-display-name": "Delete Conversation Message",
        },
        title="Delete Conversation Message",
    )
    conversation_id: str = Field(..., title="Conversation ID")
    message_id: str = Field(..., title="Message ID")


# E-commerce Product Variant Delete
class MailchimpDeleteEcommerceProductVariantConfig(BaseModel):
    """Delete a product variant."""

    operation: Literal["delete_product_variant"] = Field(
        "delete_product_variant",
        json_schema_extra={
            "const": "delete_product_variant",
            "ui:hidden": True,
            "x-category": "E-commerce Product",
            "x-is-trigger": False,
            "x-display-name": "Delete Product Variant",
        },
        title="Delete Product Variant",
    )
    store_id: str = Field(..., title="Store ID")
    product_id: str = Field(..., title="Product ID")
    variant_id: str = Field(..., title="Variant ID")


# ============================================================================
# Mandrill/Transactional API Operations (95 total)
# ============================================================================


# Allowlists Operations (3)
class MailchimpMandrillAllowlistsAddConfig(BaseModel):
    """Add email to allowlist."""

    operation: Literal["add_email_to_allowlist"] = Field(
        "add_email_to_allowlist",
        json_schema_extra={
            "const": "add_email_to_allowlist",
            "ui:hidden": True,
            "x-category": "Mandrill Allowlist",
            "x-is-trigger": False,
            "x-display-name": "Add Email to Allowlist",
        },
        title="Add Email to Allowlist",
    )
    email: str = Field(..., title="Email", description="Email address to allowlist")
    comment: Optional[str] = Field(
        None, title="Comment", description="Optional comment"
    )


class MailchimpMandrillAllowlistsListConfig(BaseModel):
    """List allowlisted emails."""

    operation: Literal["list_allowlisted_emails"] = Field(
        "list_allowlisted_emails",
        json_schema_extra={
            "const": "list_allowlisted_emails",
            "ui:hidden": True,
            "x-category": "Mandrill Allowlist",
            "x-is-trigger": False,
            "x-display-name": "List Allowlisted Emails",
        },
        title="List Allowlisted Emails",
    )
    email: Optional[str] = Field(
        None, title="Email", description="Optional email filter"
    )


class MailchimpMandrillAllowlistsDeleteConfig(BaseModel):
    """Remove email from allowlist."""

    operation: Literal["remove_email_from_allowlist"] = Field(
        "remove_email_from_allowlist",
        json_schema_extra={
            "const": "remove_email_from_allowlist",
            "ui:hidden": True,
            "x-category": "Mandrill Allowlist",
            "x-is-trigger": False,
            "x-display-name": "Remove Email from Allowlist",
        },
        title="Remove Email from Allowlist",
    )
    email: str = Field(..., title="Email", description="Email address to remove")


# Exports Operations (6)
class MailchimpMandrillExportsInfoConfig(BaseModel):
    """View export info."""

    operation: Literal["fetch_export_info"] = Field(
        "fetch_export_info",
        json_schema_extra={
            "const": "fetch_export_info",
            "ui:hidden": True,
            "x-category": "Mandrill Export",
            "x-is-trigger": False,
            "x-display-name": "Fetch Export Info",
        },
        title="Fetch Export Info",
    )
    id: str = Field(..., title="ID", description="Export job identifier")


class MailchimpMandrillExportsListConfig(BaseModel):
    """List exports."""

    operation: Literal["list_exports"] = Field(
        "list_exports",
        json_schema_extra={
            "const": "list_exports",
            "ui:hidden": True,
            "x-category": "Mandrill Export",
            "x-is-trigger": False,
            "x-display-name": "List Exports",
        },
        title="List Exports",
    )


class MailchimpMandrillExportsRejectsConfig(BaseModel):
    """Export denylist."""

    operation: Literal["export_denylist"] = Field(
        "export_denylist",
        json_schema_extra={
            "const": "export_denylist",
            "ui:hidden": True,
            "x-category": "Mandrill Export",
            "x-is-trigger": False,
            "x-display-name": "Export Denylist",
        },
        title="Export Denylist",
    )
    notify_email: Optional[str] = Field(
        None, title="Notify Email", description="Email to notify when complete"
    )


class MailchimpMandrillExportsWhitelistConfig(BaseModel):
    """Export Allowlist."""

    operation: Literal["export_whitelist"] = Field(
        "export_whitelist",
        json_schema_extra={
            "const": "export_whitelist",
            "ui:hidden": True,
            "x-category": "Mandrill Export",
            "x-is-trigger": False,
            "x-display-name": "Export Whitelist",
        },
        title="Export Whitelist",
    )
    notify_email: Optional[str] = Field(
        None, title="Notify Email", description="Email to notify when complete"
    )


class MailchimpMandrillExportsAllowlistConfig(BaseModel):
    """Export Allowlist."""

    operation: Literal["export_allowlist"] = Field(
        "export_allowlist",
        json_schema_extra={
            "const": "export_allowlist",
            "ui:hidden": True,
            "x-category": "Mandrill Export",
            "x-is-trigger": False,
            "x-display-name": "Export Allowlist",
        },
        title="Export Allowlist",
    )
    notify_email: Optional[str] = Field(
        None, title="Notify Email", description="Email to notify when complete"
    )


class MailchimpMandrillExportsActivityConfig(BaseModel):
    """Export activity history."""

    operation: Literal["export_activity_history"] = Field(
        "export_activity_history",
        json_schema_extra={
            "const": "export_activity_history",
            "ui:hidden": True,
            "x-category": "Mandrill Export",
            "x-is-trigger": False,
            "x-display-name": "Export Activity History",
        },
        title="Export Activity History",
    )
    notify_email: Optional[str] = Field(
        None, title="Notify Email", description="Email to notify when complete"
    )
    date_from: Optional[str] = Field(
        None, title="Date From", description="Start date (YYYY-MM-DD)"
    )
    date_to: Optional[str] = Field(
        None, title="Date To", description="End date (YYYY-MM-DD)"
    )
    tags: Optional[List[str]] = Field(None, title="Tags", description="Filter by tags")
    senders: Optional[List[str]] = Field(
        None, title="Senders", description="Filter by senders"
    )
    states: Optional[List[str]] = Field(
        None, title="States", description="Filter by message states"
    )
    api_keys: Optional[List[str]] = Field(
        None, title="API Keys", description="Filter by API keys"
    )


# Inbound Operations (9)
class MailchimpMandrillInboundDomainsConfig(BaseModel):
    """List inbound domains."""

    operation: Literal["list_inbound_domains"] = Field(
        "list_inbound_domains",
        json_schema_extra={
            "const": "list_inbound_domains",
            "ui:hidden": True,
            "x-category": "Mandrill Inbound",
            "x-is-trigger": False,
            "x-display-name": "List Inbound Domains",
        },
        title="List Inbound Domains",
    )


class MailchimpMandrillInboundAddDomainConfig(BaseModel):
    """Add inbound domain."""

    operation: Literal["add_inbound_domain"] = Field(
        "add_inbound_domain",
        json_schema_extra={
            "const": "add_inbound_domain",
            "ui:hidden": True,
            "x-category": "Mandrill Inbound",
            "x-is-trigger": False,
            "x-display-name": "Add Inbound Domain",
        },
        title="Add Inbound Domain",
    )
    domain: str = Field(..., title="Domain", description="Domain name")


class MailchimpMandrillInboundCheckDomainConfig(BaseModel):
    """Check domain settings."""

    operation: Literal["verify_inbound_domain_settings"] = Field(
        "verify_inbound_domain_settings",
        json_schema_extra={
            "const": "verify_inbound_domain_settings",
            "ui:hidden": True,
            "x-category": "Mandrill Inbound",
            "x-is-trigger": False,
            "x-display-name": "Verify Inbound Domain Settings",
        },
        title="Verify Inbound Domain Settings",
    )
    domain: str = Field(..., title="Domain", description="Domain name")


class MailchimpMandrillInboundDeleteDomainConfig(BaseModel):
    """Delete inbound domain."""

    operation: Literal["delete_inbound_domain"] = Field(
        "delete_inbound_domain",
        json_schema_extra={
            "const": "delete_inbound_domain",
            "ui:hidden": True,
            "x-category": "Mandrill Inbound",
            "x-is-trigger": False,
            "x-display-name": "Delete Inbound Domain",
        },
        title="Delete Inbound Domain",
    )
    domain: str = Field(..., title="Domain", description="Domain name")


class MailchimpMandrillInboundRoutesConfig(BaseModel):
    """List mailbox routes."""

    operation: Literal["list_mailbox_routes"] = Field(
        "list_mailbox_routes",
        json_schema_extra={
            "const": "list_mailbox_routes",
            "ui:hidden": True,
            "x-category": "Mandrill Inbound",
            "x-is-trigger": False,
            "x-display-name": "List Mailbox Routes",
        },
        title="List Mailbox Routes",
    )
    domain: str = Field(..., title="Domain", description="Domain name")


class MailchimpMandrillInboundAddRouteConfig(BaseModel):
    """Add mailbox route."""

    operation: Literal["add_mailbox_route"] = Field(
        "add_mailbox_route",
        json_schema_extra={
            "const": "add_mailbox_route",
            "ui:hidden": True,
            "x-category": "Mandrill Inbound",
            "x-is-trigger": False,
            "x-display-name": "Add Mailbox Route",
        },
        title="Add Mailbox Route",
    )
    domain: str = Field(..., title="Domain", description="Domain name")
    pattern: str = Field(..., title="Pattern", description="Mailbox pattern")
    url: str = Field(..., title="URL", description="Webhook URL")


class MailchimpMandrillInboundUpdateRouteConfig(BaseModel):
    """Update mailbox route."""

    operation: Literal["update_mailbox_route"] = Field(
        "update_mailbox_route",
        json_schema_extra={
            "const": "update_mailbox_route",
            "ui:hidden": True,
            "x-category": "Mandrill Inbound",
            "x-is-trigger": False,
            "x-display-name": "Update Mailbox Route",
        },
        title="Update Mailbox Route",
    )
    id: str = Field(..., title="ID", description="Route ID")
    pattern: Optional[str] = Field(None, title="Pattern", description="Mailbox pattern")
    url: Optional[str] = Field(None, title="URL", description="Webhook URL")


class MailchimpMandrillInboundDeleteRouteConfig(BaseModel):
    """Delete mailbox route."""

    operation: Literal["delete_mailbox_route"] = Field(
        "delete_mailbox_route",
        json_schema_extra={
            "const": "delete_mailbox_route",
            "ui:hidden": True,
            "x-category": "Mandrill Inbound",
            "x-is-trigger": False,
            "x-display-name": "Delete Mailbox Route",
        },
        title="Delete Mailbox Route",
    )
    id: str = Field(..., title="ID", description="Route ID")


class MailchimpMandrillInboundSendRawConfig(BaseModel):
    """Send mime document."""

    operation: Literal["send_raw_mime_message"] = Field(
        "send_raw_mime_message",
        json_schema_extra={
            "const": "send_raw_mime_message",
            "ui:hidden": True,
            "x-category": "Mandrill Inbound",
            "x-is-trigger": False,
            "x-display-name": "Send Raw Mime Message",
        },
        title="Send Raw Mime Message",
    )
    raw_message: str = Field(..., title="Raw Message", description="Full MIME document")
    to: Optional[List[str]] = Field(None, title="To", description="Recipient addresses")
    mail_from: Optional[str] = Field(
        None, title="Mail From", description="Envelope sender"
    )
    helo: Optional[str] = Field(None, title="HELO", description="HELO string")
    client_address: Optional[str] = Field(
        None, title="Client Address", description="IP address"
    )


# IPs Operations (13)
class MailchimpMandrillIpsListConfig(BaseModel):
    """List ip addresses."""

    operation: Literal["list_ip_addresses"] = Field(
        "list_ip_addresses",
        json_schema_extra={
            "const": "list_ip_addresses",
            "ui:hidden": True,
            "x-category": "Mandrill IP",
            "x-is-trigger": False,
            "x-display-name": "List Ip Addresses",
        },
        title="List Ip Addresses",
    )


class MailchimpMandrillIpsInfoConfig(BaseModel):
    """Get ip info."""

    operation: Literal["fetch_ip_info"] = Field(
        "fetch_ip_info",
        json_schema_extra={
            "const": "fetch_ip_info",
            "ui:hidden": True,
            "x-category": "Mandrill IP",
            "x-is-trigger": False,
            "x-display-name": "Fetch Ip Info",
        },
        title="Fetch Ip Info",
    )
    ip: str = Field(..., title="IP", description="IP address")


class MailchimpMandrillIpsProvisionConfig(BaseModel):
    """Request additional ip."""

    operation: Literal["request_additional_ip"] = Field(
        "request_additional_ip",
        json_schema_extra={
            "const": "request_additional_ip",
            "ui:hidden": True,
            "x-category": "Mandrill IP",
            "x-is-trigger": False,
            "x-display-name": "Request Additional Ip",
        },
        title="Request Additional Ip",
    )
    warmup: Optional[bool] = Field(
        None, title="Warmup", description="Enable warmup mode"
    )
    pool: Optional[str] = Field(None, title="Pool", description="IP pool name")


class MailchimpMandrillIpsStartWarmupConfig(BaseModel):
    """Start ip warmup."""

    operation: Literal["start_ip_warmup"] = Field(
        "start_ip_warmup",
        json_schema_extra={
            "const": "start_ip_warmup",
            "ui:hidden": True,
            "x-category": "Mandrill IP",
            "x-is-trigger": False,
            "x-display-name": "Start Ip Warmup",
        },
        title="Start Ip Warmup",
    )
    ip: str = Field(..., title="IP", description="IP address")


class MailchimpMandrillIpsCancelWarmupConfig(BaseModel):
    """Cancel ip warmup."""

    operation: Literal["cancel_ip_warmup"] = Field(
        "cancel_ip_warmup",
        json_schema_extra={
            "const": "cancel_ip_warmup",
            "ui:hidden": True,
            "x-category": "Mandrill IP",
            "x-is-trigger": False,
            "x-display-name": "Cancel Ip Warmup",
        },
        title="Cancel Ip Warmup",
    )
    ip: str = Field(..., title="IP", description="IP address")


class MailchimpMandrillIpsSetPoolConfig(BaseModel):
    """Move ip to different pool."""

    operation: Literal["move_ip_to_pool"] = Field(
        "move_ip_to_pool",
        json_schema_extra={
            "const": "move_ip_to_pool",
            "ui:hidden": True,
            "x-category": "Mandrill IP",
            "x-is-trigger": False,
            "x-display-name": "Move Ip to Pool",
        },
        title="Move Ip to Pool",
    )
    ip: str = Field(..., title="IP", description="IP address")
    pool: str = Field(..., title="Pool", description="IP pool name")
    create_pool: Optional[bool] = Field(
        None, title="Create Pool", description="Create pool if missing"
    )


class MailchimpMandrillIpsDeleteConfig(BaseModel):
    """Delete ip address."""

    operation: Literal["delete_ip_address"] = Field(
        "delete_ip_address",
        json_schema_extra={
            "const": "delete_ip_address",
            "ui:hidden": True,
            "x-category": "Mandrill IP",
            "x-is-trigger": False,
            "x-display-name": "Delete Ip Address",
        },
        title="Delete Ip Address",
    )
    ip: str = Field(..., title="IP", description="IP address")


class MailchimpMandrillIpsListPoolsConfig(BaseModel):
    """List ip pools."""

    operation: Literal["list_ip_pools"] = Field(
        "list_ip_pools",
        json_schema_extra={
            "const": "list_ip_pools",
            "ui:hidden": True,
            "x-category": "Mandrill IP",
            "x-is-trigger": False,
            "x-display-name": "List Ip Pools",
        },
        title="List Ip Pools",
    )


class MailchimpMandrillIpsPoolInfoConfig(BaseModel):
    """Get ip pool info."""

    operation: Literal["fetch_ip_pool_info"] = Field(
        "fetch_ip_pool_info",
        json_schema_extra={
            "const": "fetch_ip_pool_info",
            "ui:hidden": True,
            "x-category": "Mandrill IP",
            "x-is-trigger": False,
            "x-display-name": "Fetch Ip Pool Info",
        },
        title="Fetch Ip Pool Info",
    )
    pool: str = Field(..., title="Pool", description="IP pool name")


class MailchimpMandrillIpsCreatePoolConfig(BaseModel):
    """Add ip pool."""

    operation: Literal["create_ip_pool"] = Field(
        "create_ip_pool",
        json_schema_extra={
            "const": "create_ip_pool",
            "ui:hidden": True,
            "x-category": "Mandrill IP",
            "x-is-trigger": False,
            "x-display-name": "Create Ip Pool",
        },
        title="Create Ip Pool",
    )
    pool: str = Field(..., title="Pool", description="IP pool name")


class MailchimpMandrillIpsDeletePoolConfig(BaseModel):
    """Delete ip pool."""

    operation: Literal["delete_ip_pool"] = Field(
        "delete_ip_pool",
        json_schema_extra={
            "const": "delete_ip_pool",
            "ui:hidden": True,
            "x-category": "Mandrill IP",
            "x-is-trigger": False,
            "x-display-name": "Delete Ip Pool",
        },
        title="Delete Ip Pool",
    )
    pool: str = Field(..., title="Pool", description="IP pool name")


class MailchimpMandrillIpsCheckCustomDnsConfig(BaseModel):
    """Test custom dns."""

    operation: Literal["test_ip_custom_dns"] = Field(
        "test_ip_custom_dns",
        json_schema_extra={
            "const": "test_ip_custom_dns",
            "ui:hidden": True,
            "x-category": "Mandrill IP",
            "x-is-trigger": False,
            "x-display-name": "Test Ip Custom Dns",
        },
        title="Test Ip Custom Dns",
    )
    ip: str = Field(..., title="IP", description="IP address")
    domain: str = Field(..., title="Domain", description="Domain name")


class MailchimpMandrillIpsSetCustomDnsConfig(BaseModel):
    """Set custom dns."""

    operation: Literal["set_ip_custom_dns"] = Field(
        "set_ip_custom_dns",
        json_schema_extra={
            "const": "set_ip_custom_dns",
            "ui:hidden": True,
            "x-category": "Mandrill IP",
            "x-is-trigger": False,
            "x-display-name": "Set Ip Custom Dns",
        },
        title="Set Ip Custom Dns",
    )
    ip: str = Field(..., title="IP", description="IP address")
    domain: str = Field(..., title="Domain", description="Domain name")


# Messages Operations (12)
class MailchimpMandrillMessagesSendSmsConfig(BaseModel):
    """Send SMS message."""

    operation: Literal["send_sms_message"] = Field(
        "send_sms_message",
        json_schema_extra={
            "const": "send_sms_message",
            "ui:hidden": True,
            "x-category": "Mandrill Message",
            "x-is-trigger": False,
            "x-display-name": "Send Sms Message",
        },
        title="Send Sms Message",
    )
    message: Dict[str, Any] = Field(
        ..., title="Message", description="SMS message details"
    )


class MailchimpMandrillMessagesSendConfig(BaseModel):
    """Send new message."""

    operation: Literal["send_message"] = Field(
        "send_message",
        json_schema_extra={
            "const": "send_message",
            "ui:hidden": True,
            "x-category": "Mandrill Message",
            "x-is-trigger": False,
            "x-display-name": "Send Message",
        },
        title="Send Message",
    )
    message: Dict[str, Any] = Field(..., title="Message", description="Message details")
    async_: Optional[bool] = Field(
        None, alias="async", title="Async", description="Enable async sending"
    )
    ip_pool: Optional[str] = Field(None, title="IP Pool", description="IP pool name")
    send_at: Optional[str] = Field(
        None, title="Send At", description="Schedule send time (YYYY-MM-DD HH:MM:SS)"
    )


class MailchimpMandrillMessagesSendTemplateConfig(BaseModel):
    """Send using message template."""

    operation: Literal["send_templated_message"] = Field(
        "send_templated_message",
        json_schema_extra={
            "const": "send_templated_message",
            "ui:hidden": True,
            "x-category": "Mandrill Message",
            "x-is-trigger": False,
            "x-display-name": "Send Templated Message",
        },
        title="Send Templated Message",
    )
    template_name: str = Field(..., title="Template Name", description="Template name")
    template_content: List[Dict[str, Any]] = Field(
        ..., title="Template Content", description="Template content"
    )
    message: Dict[str, Any] = Field(..., title="Message", description="Message details")
    async_: Optional[bool] = Field(
        None, alias="async", title="Async", description="Enable async sending"
    )
    ip_pool: Optional[str] = Field(None, title="IP Pool", description="IP pool name")
    send_at: Optional[str] = Field(
        None, title="Send At", description="Schedule send time (YYYY-MM-DD HH:MM:SS)"
    )


class MailchimpMandrillMessagesSearchConfig(BaseModel):
    """Search messages by date."""

    operation: Literal["search_messages_by_date"] = Field(
        "search_messages_by_date",
        json_schema_extra={
            "const": "search_messages_by_date",
            "ui:hidden": True,
            "x-category": "Mandrill Message",
            "x-is-trigger": False,
            "x-display-name": "Search Messages by Date",
        },
        title="Search Messages by Date",
    )
    query: Optional[str] = Field(None, title="Query", description="Search query")
    date_from: Optional[str] = Field(
        None, title="Date From", description="Start date (YYYY-MM-DD)"
    )
    date_to: Optional[str] = Field(
        None, title="Date To", description="End date (YYYY-MM-DD)"
    )
    tags: Optional[List[str]] = Field(None, title="Tags", description="Filter by tags")
    senders: Optional[List[str]] = Field(
        None, title="Senders", description="Filter by senders"
    )
    api_keys: Optional[List[str]] = Field(
        None, title="API Keys", description="Filter by API keys"
    )
    limit: Optional[int] = Field(None, title="Limit", description="Result limit")


class MailchimpMandrillMessagesSearchTimeSeriesConfig(BaseModel):
    """Search messages by hour."""

    operation: Literal["search_messages_by_hour"] = Field(
        "search_messages_by_hour",
        json_schema_extra={
            "const": "search_messages_by_hour",
            "ui:hidden": True,
            "x-category": "Mandrill Message",
            "x-is-trigger": False,
            "x-display-name": "Search Messages by Hour",
        },
        title="Search Messages by Hour",
    )
    query: Optional[str] = Field(None, title="Query", description="Search query")
    date_from: Optional[str] = Field(
        None, title="Date From", description="Start date (YYYY-MM-DD)"
    )
    date_to: Optional[str] = Field(
        None, title="Date To", description="End date (YYYY-MM-DD)"
    )
    tags: Optional[List[str]] = Field(None, title="Tags", description="Filter by tags")
    senders: Optional[List[str]] = Field(
        None, title="Senders", description="Filter by senders"
    )


class MailchimpMandrillMessagesInfoConfig(BaseModel):
    """Get message info."""

    operation: Literal["fetch_message_info"] = Field(
        "fetch_message_info",
        json_schema_extra={
            "const": "fetch_message_info",
            "ui:hidden": True,
            "x-category": "Mandrill Message",
            "x-is-trigger": False,
            "x-display-name": "Fetch Message Info",
        },
        title="Fetch Message Info",
    )
    id: str = Field(..., title="ID", description="Message ID")


class MailchimpMandrillMessagesContentConfig(BaseModel):
    """Get message content."""

    operation: Literal["fetch_message_content"] = Field(
        "fetch_message_content",
        json_schema_extra={
            "const": "fetch_message_content",
            "ui:hidden": True,
            "x-category": "Mandrill Message",
            "x-is-trigger": False,
            "x-display-name": "Fetch Message Content",
        },
        title="Fetch Message Content",
    )
    id: str = Field(..., title="ID", description="Message ID")


class MailchimpMandrillMessagesParseConfig(BaseModel):
    """Parse mime document."""

    operation: Literal["parse_mime_message"] = Field(
        "parse_mime_message",
        json_schema_extra={
            "const": "parse_mime_message",
            "ui:hidden": True,
            "x-category": "Mandrill Message",
            "x-is-trigger": False,
            "x-display-name": "Parse Mime Message",
        },
        title="Parse Mime Message",
    )
    raw_message: str = Field(..., title="Raw Message", description="Full MIME document")


class MailchimpMandrillMessagesSendRawConfig(BaseModel):
    """Send mime document."""

    operation: Literal["send_raw_mime_email"] = Field(
        "send_raw_mime_email",
        json_schema_extra={
            "const": "send_raw_mime_email",
            "ui:hidden": True,
            "x-category": "Mandrill Message",
            "x-is-trigger": False,
            "x-display-name": "Send Raw Mime Email",
        },
        title="Send Raw Mime Email",
    )
    raw_message: str = Field(..., title="Raw Message", description="Full MIME document")
    from_email: Optional[str] = Field(
        None, title="From Email", description="Sender email"
    )
    from_name: Optional[str] = Field(None, title="From Name", description="Sender name")
    to: Optional[List[str]] = Field(None, title="To", description="Recipient addresses")
    async_: Optional[bool] = Field(
        None, alias="async", title="Async", description="Enable async sending"
    )
    ip_pool: Optional[str] = Field(None, title="IP Pool", description="IP pool name")
    send_at: Optional[str] = Field(
        None, title="Send At", description="Schedule send time (YYYY-MM-DD HH:MM:SS)"
    )


class MailchimpMandrillMessagesListScheduledConfig(BaseModel):
    """List scheduled emails."""

    operation: Literal["list_scheduled_emails"] = Field(
        "list_scheduled_emails",
        json_schema_extra={
            "const": "list_scheduled_emails",
            "ui:hidden": True,
            "x-category": "Mandrill Message",
            "x-is-trigger": False,
            "x-display-name": "List Scheduled Emails",
        },
        title="List Scheduled Emails",
    )
    to: Optional[str] = Field(None, title="To", description="Filter by recipient")


class MailchimpMandrillMessagesCancelScheduledConfig(BaseModel):
    """Cancel scheduled email."""

    operation: Literal["cancel_scheduled_email"] = Field(
        "cancel_scheduled_email",
        json_schema_extra={
            "const": "cancel_scheduled_email",
            "ui:hidden": True,
            "x-category": "Mandrill Message",
            "x-is-trigger": False,
            "x-display-name": "Cancel Scheduled Email",
        },
        title="Cancel Scheduled Email",
    )
    id: str = Field(..., title="ID", description="Scheduled message ID")


class MailchimpMandrillMessagesRescheduleConfig(BaseModel):
    """Reschedule email."""

    operation: Literal["reschedule_scheduled_email"] = Field(
        "reschedule_scheduled_email",
        json_schema_extra={
            "const": "reschedule_scheduled_email",
            "ui:hidden": True,
            "x-category": "Mandrill Message",
            "x-is-trigger": False,
            "x-display-name": "Reschedule Scheduled Email",
        },
        title="Reschedule Scheduled Email",
    )
    id: str = Field(..., title="ID", description="Scheduled message ID")
    send_at: str = Field(
        ..., title="Send At", description="New send time (YYYY-MM-DD HH:MM:SS)"
    )


# Metadata Operations (4)
class MailchimpMandrillMetadataListConfig(BaseModel):
    """List metadata fields."""

    operation: Literal["list_metadata_fields"] = Field(
        "list_metadata_fields",
        json_schema_extra={
            "const": "list_metadata_fields",
            "ui:hidden": True,
            "x-category": "Mandrill Metadata",
            "x-is-trigger": False,
            "x-display-name": "List Metadata Fields",
        },
        title="List Metadata Fields",
    )


class MailchimpMandrillMetadataAddConfig(BaseModel):
    """Add metadata field."""

    operation: Literal["create_metadata_field"] = Field(
        "create_metadata_field",
        json_schema_extra={
            "const": "create_metadata_field",
            "ui:hidden": True,
            "x-category": "Mandrill Metadata",
            "x-is-trigger": False,
            "x-display-name": "Create Metadata Field",
        },
        title="Create Metadata Field",
    )
    name: str = Field(..., title="Name", description="Field name")
    view_template: Optional[str] = Field(
        None, title="View Template", description="Handlebars template"
    )


class MailchimpMandrillMetadataUpdateConfig(BaseModel):
    """Update metadata field."""

    operation: Literal["update_metadata_field"] = Field(
        "update_metadata_field",
        json_schema_extra={
            "const": "update_metadata_field",
            "ui:hidden": True,
            "x-category": "Mandrill Metadata",
            "x-is-trigger": False,
            "x-display-name": "Update Metadata Field",
        },
        title="Update Metadata Field",
    )
    name: str = Field(..., title="Name", description="Field name")
    view_template: str = Field(
        ..., title="View Template", description="Handlebars template"
    )


class MailchimpMandrillMetadataDeleteConfig(BaseModel):
    """Delete metadata field."""

    operation: Literal["delete_metadata_field"] = Field(
        "delete_metadata_field",
        json_schema_extra={
            "const": "delete_metadata_field",
            "ui:hidden": True,
            "x-category": "Mandrill Metadata",
            "x-is-trigger": False,
            "x-display-name": "Delete Metadata Field",
        },
        title="Delete Metadata Field",
    )
    name: str = Field(..., title="Name", description="Field name")


# Rejects Operations (3)
class MailchimpMandrillRejectsAddConfig(BaseModel):
    """Add email to denylist."""

    operation: Literal["add_email_to_denylist"] = Field(
        "add_email_to_denylist",
        json_schema_extra={
            "const": "add_email_to_denylist",
            "ui:hidden": True,
            "x-category": "Mandrill Denylist",
            "x-is-trigger": False,
            "x-display-name": "Add Email to Denylist",
        },
        title="Add Email to Denylist",
    )
    email: str = Field(..., title="Email", description="Email address to denylist")
    comment: Optional[str] = Field(
        None, title="Comment", description="Optional comment"
    )
    subaccount: Optional[str] = Field(
        None, title="Subaccount", description="Subaccount ID"
    )


class MailchimpMandrillRejectsListConfig(BaseModel):
    """List denylisted emails."""

    operation: Literal["list_denylisted_emails"] = Field(
        "list_denylisted_emails",
        json_schema_extra={
            "const": "list_denylisted_emails",
            "ui:hidden": True,
            "x-category": "Mandrill Denylist",
            "x-is-trigger": False,
            "x-display-name": "List Denylisted Emails",
        },
        title="List Denylisted Emails",
    )
    email: Optional[str] = Field(None, title="Email", description="Filter by email")
    include_expired: Optional[bool] = Field(
        None, title="Include Expired", description="Include expired entries"
    )
    subaccount: Optional[str] = Field(
        None, title="Subaccount", description="Subaccount ID"
    )


class MailchimpMandrillRejectsDeleteConfig(BaseModel):
    """Delete email from denylist."""

    operation: Literal["remove_email_from_denylist"] = Field(
        "remove_email_from_denylist",
        json_schema_extra={
            "const": "remove_email_from_denylist",
            "ui:hidden": True,
            "x-category": "Mandrill Denylist",
            "x-is-trigger": False,
            "x-display-name": "Remove Email from Denylist",
        },
        title="Remove Email from Denylist",
    )
    email: str = Field(..., title="Email", description="Email address to remove")
    subaccount: Optional[str] = Field(
        None, title="Subaccount", description="Subaccount ID"
    )


# Senders Operations (7)
class MailchimpMandrillSendersListConfig(BaseModel):
    """List account senders."""

    operation: Literal["list_account_senders"] = Field(
        "list_account_senders",
        json_schema_extra={
            "const": "list_account_senders",
            "ui:hidden": True,
            "x-category": "Mandrill Sender",
            "x-is-trigger": False,
            "x-display-name": "List Account Senders",
        },
        title="List Account Senders",
    )


class MailchimpMandrillSendersDomainsConfig(BaseModel):
    """List sender domains."""

    operation: Literal["list_sender_domains"] = Field(
        "list_sender_domains",
        json_schema_extra={
            "const": "list_sender_domains",
            "ui:hidden": True,
            "x-category": "Mandrill Sender",
            "x-is-trigger": False,
            "x-display-name": "List Sender Domains",
        },
        title="List Sender Domains",
    )


class MailchimpMandrillSendersAddDomainConfig(BaseModel):
    """Add sender domain."""

    operation: Literal["add_sender_domain"] = Field(
        "add_sender_domain",
        json_schema_extra={
            "const": "add_sender_domain",
            "ui:hidden": True,
            "x-category": "Mandrill Sender",
            "x-is-trigger": False,
            "x-display-name": "Add Sender Domain",
        },
        title="Add Sender Domain",
    )
    domain: str = Field(..., title="Domain", description="Domain name")


class MailchimpMandrillSendersCheckDomainConfig(BaseModel):
    """Check domain settings."""

    operation: Literal["verify_sender_domain_settings"] = Field(
        "verify_sender_domain_settings",
        json_schema_extra={
            "const": "verify_sender_domain_settings",
            "ui:hidden": True,
            "x-category": "Mandrill Sender",
            "x-is-trigger": False,
            "x-display-name": "Verify Sender Domain Settings",
        },
        title="Verify Sender Domain Settings",
    )
    domain: str = Field(..., title="Domain", description="Domain name")


class MailchimpMandrillSendersVerifyDomainConfig(BaseModel):
    """Verify domain."""

    operation: Literal["verify_sender_domain_for_sending"] = Field(
        "verify_sender_domain_for_sending",
        json_schema_extra={
            "const": "verify_sender_domain_for_sending",
            "ui:hidden": True,
            "x-category": "Mandrill Sender",
            "x-is-trigger": False,
            "x-display-name": "Verify Sender Domain for Sending",
        },
        title="Verify Sender Domain for Sending",
    )
    domain: str = Field(..., title="Domain", description="Domain name")
    mailbox: str = Field(..., title="Mailbox", description="Mailbox for verification")


class MailchimpMandrillSendersInfoConfig(BaseModel):
    """Get sender info."""

    operation: Literal["fetch_sender_info"] = Field(
        "fetch_sender_info",
        json_schema_extra={
            "const": "fetch_sender_info",
            "ui:hidden": True,
            "x-category": "Mandrill Sender",
            "x-is-trigger": False,
            "x-display-name": "Fetch Sender Info",
        },
        title="Fetch Sender Info",
    )
    address: str = Field(..., title="Address", description="Sender email address")


class MailchimpMandrillSendersTimeSeriesConfig(BaseModel):
    """View sender history."""

    operation: Literal["fetch_sender_history"] = Field(
        "fetch_sender_history",
        json_schema_extra={
            "const": "fetch_sender_history",
            "ui:hidden": True,
            "x-category": "Mandrill Sender",
            "x-is-trigger": False,
            "x-display-name": "Fetch Sender History",
        },
        title="Fetch Sender History",
    )
    address: str = Field(..., title="Address", description="Sender email address")


# Subaccounts Operations (7)
class MailchimpMandrillSubaccountsListConfig(BaseModel):
    """List subaccounts."""

    operation: Literal["list_subaccounts"] = Field(
        "list_subaccounts",
        json_schema_extra={
            "const": "list_subaccounts",
            "ui:hidden": True,
            "x-category": "Mandrill Subaccount",
            "x-is-trigger": False,
            "x-display-name": "List Subaccounts",
        },
        title="List Subaccounts",
    )
    q: Optional[str] = Field(None, title="Query", description="Search query")


class MailchimpMandrillSubaccountsAddConfig(BaseModel):
    """Add subaccount."""

    operation: Literal["create_subaccount"] = Field(
        "create_subaccount",
        json_schema_extra={
            "const": "create_subaccount",
            "ui:hidden": True,
            "x-category": "Mandrill Subaccount",
            "x-is-trigger": False,
            "x-display-name": "Create Subaccount",
        },
        title="Create Subaccount",
    )
    id: str = Field(..., title="ID", description="Subaccount ID")
    name: Optional[str] = Field(None, title="Name", description="Subaccount name")
    notes: Optional[str] = Field(None, title="Notes", description="Optional notes")
    custom_quota: Optional[int] = Field(
        None, title="Custom Quota", description="Custom hourly quota"
    )


class MailchimpMandrillSubaccountsInfoConfig(BaseModel):
    """Get subaccount info."""

    operation: Literal["fetch_subaccount_info"] = Field(
        "fetch_subaccount_info",
        json_schema_extra={
            "const": "fetch_subaccount_info",
            "ui:hidden": True,
            "x-category": "Mandrill Subaccount",
            "x-is-trigger": False,
            "x-display-name": "Fetch Subaccount Info",
        },
        title="Fetch Subaccount Info",
    )
    id: str = Field(..., title="ID", description="Subaccount ID")


class MailchimpMandrillSubaccountsUpdateConfig(BaseModel):
    """Update subaccount."""

    operation: Literal["update_subaccount"] = Field(
        "update_subaccount",
        json_schema_extra={
            "const": "update_subaccount",
            "ui:hidden": True,
            "x-category": "Mandrill Subaccount",
            "x-is-trigger": False,
            "x-display-name": "Update Subaccount",
        },
        title="Update Subaccount",
    )
    id: str = Field(..., title="ID", description="Subaccount ID")
    name: Optional[str] = Field(None, title="Name", description="Subaccount name")
    notes: Optional[str] = Field(None, title="Notes", description="Optional notes")
    custom_quota: Optional[int] = Field(
        None, title="Custom Quota", description="Custom hourly quota"
    )


class MailchimpMandrillSubaccountsDeleteConfig(BaseModel):
    """Delete subaccount."""

    operation: Literal["delete_subaccount"] = Field(
        "delete_subaccount",
        json_schema_extra={
            "const": "delete_subaccount",
            "ui:hidden": True,
            "x-category": "Mandrill Subaccount",
            "x-is-trigger": False,
            "x-display-name": "Delete Subaccount",
        },
        title="Delete Subaccount",
    )
    id: str = Field(..., title="ID", description="Subaccount ID")


class MailchimpMandrillSubaccountsPauseConfig(BaseModel):
    """Pause subaccount."""

    operation: Literal["pause_subaccount"] = Field(
        "pause_subaccount",
        json_schema_extra={
            "const": "pause_subaccount",
            "ui:hidden": True,
            "x-category": "Mandrill Subaccount",
            "x-is-trigger": False,
            "x-display-name": "Pause Subaccount",
        },
        title="Pause Subaccount",
    )
    id: str = Field(..., title="ID", description="Subaccount ID")


class MailchimpMandrillSubaccountsResumeConfig(BaseModel):
    """Resume subaccount."""

    operation: Literal["resume_subaccount"] = Field(
        "resume_subaccount",
        json_schema_extra={
            "const": "resume_subaccount",
            "ui:hidden": True,
            "x-category": "Mandrill Subaccount",
            "x-is-trigger": False,
            "x-display-name": "Resume Subaccount",
        },
        title="Resume Subaccount",
    )
    id: str = Field(..., title="ID", description="Subaccount ID")


# Tags Operations (5)
class MailchimpMandrillTagsListConfig(BaseModel):
    """List tags."""

    operation: Literal["list_tags"] = Field(
        "list_tags",
        json_schema_extra={
            "const": "list_tags",
            "ui:hidden": True,
            "x-category": "Mandrill Tag",
            "x-is-trigger": False,
            "x-display-name": "List Tags",
        },
        title="List Tags",
    )


class MailchimpMandrillTagsDeleteConfig(BaseModel):
    """Delete tag."""

    operation: Literal["delete_tag"] = Field(
        "delete_tag",
        json_schema_extra={
            "const": "delete_tag",
            "ui:hidden": True,
            "x-category": "Mandrill Tag",
            "x-is-trigger": False,
            "x-display-name": "Delete Tag",
        },
        title="Delete Tag",
    )
    tag: str = Field(..., title="Tag", description="Tag name")


class MailchimpMandrillTagsInfoConfig(BaseModel):
    """Get tag info."""

    operation: Literal["fetch_tag_info"] = Field(
        "fetch_tag_info",
        json_schema_extra={
            "const": "fetch_tag_info",
            "ui:hidden": True,
            "x-category": "Mandrill Tag",
            "x-is-trigger": False,
            "x-display-name": "Fetch Tag Info",
        },
        title="Fetch Tag Info",
    )
    tag: str = Field(..., title="Tag", description="Tag name")


class MailchimpMandrillTagsTimeSeriesConfig(BaseModel):
    """View tag history."""

    operation: Literal["fetch_tag_history"] = Field(
        "fetch_tag_history",
        json_schema_extra={
            "const": "fetch_tag_history",
            "ui:hidden": True,
            "x-category": "Mandrill Tag",
            "x-is-trigger": False,
            "x-display-name": "Fetch Tag History",
        },
        title="Fetch Tag History",
    )
    tag: str = Field(..., title="Tag", description="Tag name")


class MailchimpMandrillTagsAllTimeSeriesConfig(BaseModel):
    """View all tags history."""

    operation: Literal["fetch_all_tags_history"] = Field(
        "fetch_all_tags_history",
        json_schema_extra={
            "const": "fetch_all_tags_history",
            "ui:hidden": True,
            "x-category": "Mandrill Tag",
            "x-is-trigger": False,
            "x-display-name": "Fetch All Tags History",
        },
        title="Fetch All Tags History",
    )


# Templates Operations (8)
class MailchimpMandrillTemplatesAddConfig(BaseModel):
    """Add template."""

    operation: Literal["create_mandrill_template"] = Field(
        "create_mandrill_template",
        json_schema_extra={
            "const": "create_mandrill_template",
            "ui:hidden": True,
            "x-category": "Mandrill Template",
            "x-is-trigger": False,
            "x-display-name": "Create Mandrill Template",
        },
        title="Create Mandrill Template",
    )
    name: str = Field(..., title="Name", description="Template name")
    from_email: Optional[str] = Field(
        None, title="From Email", description="Default sender email"
    )
    from_name: Optional[str] = Field(
        None, title="From Name", description="Default sender name"
    )
    subject: Optional[str] = Field(None, title="Subject", description="Default subject")
    code: Optional[str] = Field(None, title="Code", description="HTML code")
    text: Optional[str] = Field(None, title="Text", description="Text content")
    publish: Optional[bool] = Field(
        None, title="Publish", description="Publish immediately"
    )
    labels: Optional[List[str]] = Field(
        None, title="Labels", description="Template labels"
    )


class MailchimpMandrillTemplatesInfoConfig(BaseModel):
    """Get template info."""

    operation: Literal["fetch_mandrill_template_info"] = Field(
        "fetch_mandrill_template_info",
        json_schema_extra={
            "const": "fetch_mandrill_template_info",
            "ui:hidden": True,
            "x-category": "Mandrill Template",
            "x-is-trigger": False,
            "x-display-name": "Fetch Mandrill Template Info",
        },
        title="Fetch Mandrill Template Info",
    )
    name: str = Field(..., title="Name", description="Template name")


class MailchimpMandrillTemplatesUpdateConfig(BaseModel):
    """Update template."""

    operation: Literal["update_mandrill_template"] = Field(
        "update_mandrill_template",
        json_schema_extra={
            "const": "update_mandrill_template",
            "ui:hidden": True,
            "x-category": "Mandrill Template",
            "x-is-trigger": False,
            "x-display-name": "Update Mandrill Template",
        },
        title="Update Mandrill Template",
    )
    name: str = Field(..., title="Name", description="Template name")
    from_email: Optional[str] = Field(
        None, title="From Email", description="Default sender email"
    )
    from_name: Optional[str] = Field(
        None, title="From Name", description="Default sender name"
    )
    subject: Optional[str] = Field(None, title="Subject", description="Default subject")
    code: Optional[str] = Field(None, title="Code", description="HTML code")
    text: Optional[str] = Field(None, title="Text", description="Text content")
    publish: Optional[bool] = Field(
        None, title="Publish", description="Publish immediately"
    )
    labels: Optional[List[str]] = Field(
        None, title="Labels", description="Template labels"
    )


class MailchimpMandrillTemplatesPublishConfig(BaseModel):
    """Publish template content."""

    operation: Literal["publish_mandrill_template"] = Field(
        "publish_mandrill_template",
        json_schema_extra={
            "const": "publish_mandrill_template",
            "ui:hidden": True,
            "x-category": "Mandrill Template",
            "x-is-trigger": False,
            "x-display-name": "Publish Mandrill Template",
        },
        title="Publish Mandrill Template",
    )
    name: str = Field(..., title="Name", description="Template name")


class MailchimpMandrillTemplatesDeleteConfig(BaseModel):
    """Delete template."""

    operation: Literal["delete_mandrill_template"] = Field(
        "delete_mandrill_template",
        json_schema_extra={
            "const": "delete_mandrill_template",
            "ui:hidden": True,
            "x-category": "Mandrill Template",
            "x-is-trigger": False,
            "x-display-name": "Delete Mandrill Template",
        },
        title="Delete Mandrill Template",
    )
    name: str = Field(..., title="Name", description="Template name")


class MailchimpMandrillTemplatesListConfig(BaseModel):
    """List templates."""

    operation: Literal["list_mandrill_templates"] = Field(
        "list_mandrill_templates",
        json_schema_extra={
            "const": "list_mandrill_templates",
            "ui:hidden": True,
            "x-category": "Mandrill Template",
            "x-is-trigger": False,
            "x-display-name": "List Mandrill Templates",
        },
        title="List Mandrill Templates",
    )
    label: Optional[str] = Field(None, title="Label", description="Filter by label")


class MailchimpMandrillTemplatesTimeSeriesConfig(BaseModel):
    """Get template history."""

    operation: Literal["fetch_mandrill_template_history"] = Field(
        "fetch_mandrill_template_history",
        json_schema_extra={
            "const": "fetch_mandrill_template_history",
            "ui:hidden": True,
            "x-category": "Mandrill Template",
            "x-is-trigger": False,
            "x-display-name": "Fetch Mandrill Template History",
        },
        title="Fetch Mandrill Template History",
    )
    name: str = Field(..., title="Name", description="Template name")


class MailchimpMandrillTemplatesRenderConfig(BaseModel):
    """Render html template."""

    operation: Literal["render_html_template"] = Field(
        "render_html_template",
        json_schema_extra={
            "const": "render_html_template",
            "ui:hidden": True,
            "x-category": "Mandrill Template",
            "x-is-trigger": False,
            "x-display-name": "Render Html Template",
        },
        title="Render Html Template",
    )
    template_name: str = Field(..., title="Template Name", description="Template name")
    template_content: List[Dict[str, Any]] = Field(
        ..., title="Template Content", description="Template content"
    )
    merge_vars: Optional[List[Dict[str, Any]]] = Field(
        None, title="Merge Vars", description="Merge variables"
    )


# URLs Operations (6)
class MailchimpMandrillUrlsListConfig(BaseModel):
    """List most clicked urls."""

    operation: Literal["list_most_clicked_urls"] = Field(
        "list_most_clicked_urls",
        json_schema_extra={
            "const": "list_most_clicked_urls",
            "ui:hidden": True,
            "x-category": "Mandrill URL",
            "x-is-trigger": False,
            "x-display-name": "List Most Clicked Urls",
        },
        title="List Most Clicked Urls",
    )


class MailchimpMandrillUrlsSearchConfig(BaseModel):
    """Search most clicked urls."""

    operation: Literal["search_most_clicked_urls"] = Field(
        "search_most_clicked_urls",
        json_schema_extra={
            "const": "search_most_clicked_urls",
            "ui:hidden": True,
            "x-category": "Mandrill URL",
            "x-is-trigger": False,
            "x-display-name": "Search Most Clicked Urls",
        },
        title="Search Most Clicked Urls",
    )
    q: str = Field(..., title="Query", description="Search query")


class MailchimpMandrillUrlsTimeSeriesConfig(BaseModel):
    """Get url history."""

    operation: Literal["fetch_url_history"] = Field(
        "fetch_url_history",
        json_schema_extra={
            "const": "fetch_url_history",
            "ui:hidden": True,
            "x-category": "Mandrill URL",
            "x-is-trigger": False,
            "x-display-name": "Fetch Url History",
        },
        title="Fetch Url History",
    )
    url: str = Field(..., title="URL", description="URL to analyze")


class MailchimpMandrillUrlsTrackingDomainsConfig(BaseModel):
    """List tracking domains."""

    operation: Literal["list_tracking_domains"] = Field(
        "list_tracking_domains",
        json_schema_extra={
            "const": "list_tracking_domains",
            "ui:hidden": True,
            "x-category": "Mandrill URL",
            "x-is-trigger": False,
            "x-display-name": "List Tracking Domains",
        },
        title="List Tracking Domains",
    )


class MailchimpMandrillUrlsAddTrackingDomainConfig(BaseModel):
    """Add tracking domains."""

    operation: Literal["add_tracking_domain"] = Field(
        "add_tracking_domain",
        json_schema_extra={
            "const": "add_tracking_domain",
            "ui:hidden": True,
            "x-category": "Mandrill URL",
            "x-is-trigger": False,
            "x-display-name": "Add Tracking Domain",
        },
        title="Add Tracking Domain",
    )
    domain: str = Field(..., title="Domain", description="Domain name")


class MailchimpMandrillUrlsCheckTrackingDomainConfig(BaseModel):
    """Check cname settings."""

    operation: Literal["verify_tracking_domain_cname"] = Field(
        "verify_tracking_domain_cname",
        json_schema_extra={
            "const": "verify_tracking_domain_cname",
            "ui:hidden": True,
            "x-category": "Mandrill URL",
            "x-is-trigger": False,
            "x-display-name": "Verify Tracking Domain Cname",
        },
        title="Verify Tracking Domain Cname",
    )
    domain: str = Field(..., title="Domain", description="Domain name")


# Users Operations (4)
class MailchimpMandrillUsersInfoConfig(BaseModel):
    """Get user info."""

    operation: Literal["fetch_user_info"] = Field(
        "fetch_user_info",
        json_schema_extra={
            "const": "fetch_user_info",
            "ui:hidden": True,
            "x-category": "Mandrill User",
            "x-is-trigger": False,
            "x-display-name": "Fetch User Info",
        },
        title="Fetch User Info",
    )


class MailchimpMandrillUsersPingConfig(BaseModel):
    """Ping."""

    operation: Literal["ping_mandrill_api"] = Field(
        "ping_mandrill_api",
        json_schema_extra={
            "const": "ping_mandrill_api",
            "ui:hidden": True,
            "x-category": "Mandrill User",
            "x-is-trigger": False,
            "x-display-name": "Ping Mandrill Api",
        },
        title="Ping Mandrill Api",
    )


class MailchimpMandrillUsersPing2Config(BaseModel):
    """Ping 2."""

    operation: Literal["ping_mandrill_api_v2"] = Field(
        "ping_mandrill_api_v2",
        json_schema_extra={
            "const": "ping_mandrill_api_v2",
            "ui:hidden": True,
            "x-category": "Mandrill User",
            "x-is-trigger": False,
            "x-display-name": "Ping Mandrill Api V2",
        },
        title="Ping Mandrill Api V2",
    )


class MailchimpMandrillUsersSendersConfig(BaseModel):
    """List account senders."""

    operation: Literal["list_api_account_senders"] = Field(
        "list_api_account_senders",
        json_schema_extra={
            "const": "list_api_account_senders",
            "ui:hidden": True,
            "x-category": "Mandrill User",
            "x-is-trigger": False,
            "x-display-name": "List Api Account Senders",
        },
        title="List Api Account Senders",
    )


# Webhooks Operations (5)
class MailchimpMandrillWebhooksListConfig(BaseModel):
    """List webhooks."""

    operation: Literal["list_mandrill_webhooks"] = Field(
        "list_mandrill_webhooks",
        json_schema_extra={
            "const": "list_mandrill_webhooks",
            "ui:hidden": True,
            "x-category": "Mandrill Webhook",
            "x-is-trigger": False,
            "x-display-name": "List Mandrill Webhooks",
        },
        title="List Mandrill Webhooks",
    )


class MailchimpMandrillWebhooksAddConfig(BaseModel):
    """Add webhook."""

    operation: Literal["create_mandrill_webhook"] = Field(
        "create_mandrill_webhook",
        json_schema_extra={
            "const": "create_mandrill_webhook",
            "ui:hidden": True,
            "x-category": "Mandrill Webhook",
            "x-is-trigger": False,
            "x-display-name": "Create Mandrill Webhook",
        },
        title="Create Mandrill Webhook",
    )
    url: str = Field(..., title="URL", description="Webhook URL")
    description: Optional[str] = Field(
        None, title="Description", description="Webhook description"
    )
    events: List[str] = Field(
        ..., title="Events", description="Event types to trigger on"
    )


class MailchimpMandrillWebhooksInfoConfig(BaseModel):
    """Get webhook info."""

    operation: Literal["fetch_mandrill_webhook_info"] = Field(
        "fetch_mandrill_webhook_info",
        json_schema_extra={
            "const": "fetch_mandrill_webhook_info",
            "ui:hidden": True,
            "x-category": "Mandrill Webhook",
            "x-is-trigger": False,
            "x-display-name": "Fetch Mandrill Webhook Info",
        },
        title="Fetch Mandrill Webhook Info",
    )
    id: int = Field(..., title="ID", description="Webhook ID")


class MailchimpMandrillWebhooksUpdateConfig(BaseModel):
    """Update webhook."""

    operation: Literal["update_mandrill_webhook"] = Field(
        "update_mandrill_webhook",
        json_schema_extra={
            "const": "update_mandrill_webhook",
            "ui:hidden": True,
            "x-category": "Mandrill Webhook",
            "x-is-trigger": False,
            "x-display-name": "Update Mandrill Webhook",
        },
        title="Update Mandrill Webhook",
    )
    id: int = Field(..., title="ID", description="Webhook ID")
    url: Optional[str] = Field(None, title="URL", description="Webhook URL")
    description: Optional[str] = Field(
        None, title="Description", description="Webhook description"
    )
    events: Optional[List[str]] = Field(
        None, title="Events", description="Event types to trigger on"
    )


class MailchimpMandrillWebhooksDeleteConfig(BaseModel):
    """Delete webhook."""

    operation: Literal["delete_mandrill_webhook"] = Field(
        "delete_mandrill_webhook",
        json_schema_extra={
            "const": "delete_mandrill_webhook",
            "ui:hidden": True,
            "x-category": "Mandrill Webhook",
            "x-is-trigger": False,
            "x-display-name": "Delete Mandrill Webhook",
        },
        title="Delete Mandrill Webhook",
    )
    id: int = Field(..., title="ID", description="Webhook ID")


# Whitelists Operations (3)
class MailchimpMandrillWhitelistsAddConfig(BaseModel):
    """Add email to allowlist."""

    operation: Literal["add_email_to_whitelist"] = Field(
        "add_email_to_whitelist",
        json_schema_extra={
            "const": "add_email_to_whitelist",
            "ui:hidden": True,
            "x-category": "Mandrill Whitelist",
            "x-is-trigger": False,
            "x-display-name": "Add Email to Whitelist",
        },
        title="Add Email to Whitelist",
    )
    email: str = Field(..., title="Email", description="Email address to allowlist")
    comment: Optional[str] = Field(
        None, title="Comment", description="Optional comment"
    )


class MailchimpMandrillWhitelistsListConfig(BaseModel):
    """List allowlisted emails."""

    operation: Literal["list_whitelisted_emails"] = Field(
        "list_whitelisted_emails",
        json_schema_extra={
            "const": "list_whitelisted_emails",
            "ui:hidden": True,
            "x-category": "Mandrill Whitelist",
            "x-is-trigger": False,
            "x-display-name": "List Whitelisted Emails",
        },
        title="List Whitelisted Emails",
    )
    email: Optional[str] = Field(
        None, title="Email", description="Optional email filter"
    )


class MailchimpMandrillWhitelistsDeleteConfig(BaseModel):
    """Remove email from allowlist."""

    operation: Literal["remove_email_from_whitelist"] = Field(
        "remove_email_from_whitelist",
        json_schema_extra={
            "const": "remove_email_from_whitelist",
            "ui:hidden": True,
            "x-category": "Mandrill Whitelist",
            "x-is-trigger": False,
            "x-display-name": "Remove Email from Whitelist",
        },
        title="Remove Email from Whitelist",
    )
    email: str = Field(..., title="Email", description="Email address to remove")


# Automation Email Queue POST
class MailchimpAddAutomationQueueMemberConfig(BaseModel):
    """Add a subscriber to an automation email queue."""

    operation: Literal["add_member_to_automation_queue"] = Field(
        "add_member_to_automation_queue",
        json_schema_extra={
            "const": "add_member_to_automation_queue",
            "ui:hidden": True,
            "x-category": "Automation",
            "x-is-trigger": False,
            "x-display-name": "Add Member to Automation Queue",
        },
        title="Add Member to Automation Queue",
    )
    workflow_id: str = Field(..., title="Workflow ID")
    workflow_email_id: str = Field(..., title="Workflow Email ID")
    email_address: str = Field(..., title="Email Address")


# ============================================================================
# Discriminated Union of All Operations
# ============================================================================

MailchimpConfig = Annotated[
    Union[
        # Lists/Audiences
        MailchimpListListsConfig,
        MailchimpGetListConfig,
        MailchimpCreateListConfig,
        MailchimpUpdateListConfig,
        MailchimpDeleteListConfig,
        # List Members
        MailchimpListMembersConfig,
        MailchimpGetMemberConfig,
        MailchimpAddMemberConfig,
        MailchimpUpdateMemberConfig,
        MailchimpAddOrUpdateMemberConfig,
        MailchimpDeleteMemberConfig,
        MailchimpPermanentlyDeleteMemberConfig,
        # Campaigns
        MailchimpListCampaignsConfig,
        MailchimpGetCampaignConfig,
        MailchimpCreateCampaignConfig,
        MailchimpUpdateCampaignConfig,
        MailchimpDeleteCampaignConfig,
        MailchimpSendCampaignConfig,
        MailchimpScheduleCampaignConfig,
        MailchimpUnscheduleCampaignConfig,
        MailchimpSendTestEmailConfig,
        MailchimpReplicateCampaignConfig,
        # Campaign Content
        MailchimpGetCampaignContentConfig,
        MailchimpSetCampaignContentConfig,
        # Automations
        MailchimpListAutomationsConfig,
        MailchimpGetAutomationConfig,
        MailchimpPauseAutomationConfig,
        MailchimpStartAutomationConfig,
        # Tags
        MailchimpGetMemberTagsConfig,
        MailchimpAddOrRemoveMemberTagsConfig,
        MailchimpSearchTagsConfig,
        # Segments
        MailchimpListSegmentsConfig,
        MailchimpGetSegmentConfig,
        MailchimpCreateSegmentConfig,
        MailchimpUpdateSegmentConfig,
        MailchimpDeleteSegmentConfig,
        MailchimpBatchAddRemoveSegmentMembersConfig,
        # Merge Fields
        MailchimpListMergeFieldsConfig,
        MailchimpGetMergeFieldConfig,
        MailchimpAddMergeFieldConfig,
        MailchimpUpdateMergeFieldConfig,
        MailchimpDeleteMergeFieldConfig,
        # Interest Categories
        MailchimpListInterestCategoriesConfig,
        MailchimpGetInterestCategoryConfig,
        MailchimpCreateInterestCategoryConfig,
        MailchimpUpdateInterestCategoryConfig,
        MailchimpDeleteInterestCategoryConfig,
        # Interests
        MailchimpListInterestsConfig,
        MailchimpGetInterestConfig,
        MailchimpCreateInterestConfig,
        MailchimpUpdateInterestConfig,
        MailchimpDeleteInterestConfig,
        # Templates
        MailchimpListTemplatesConfig,
        MailchimpGetTemplateConfig,
        MailchimpCreateTemplateConfig,
        MailchimpUpdateTemplateConfig,
        MailchimpDeleteTemplateConfig,
        # Reports
        MailchimpListCampaignReportsConfig,
        MailchimpGetCampaignReportConfig,
        MailchimpGetCampaignEmailActivityConfig,
        MailchimpGetCampaignAbuseReportsConfig,
        MailchimpGetCampaignAbuseReportConfig,
        MailchimpGetCampaignClickDetailsConfig,
        MailchimpGetCampaignClickDetailsForLinkConfig,
        MailchimpGetCampaignClickDetailMembersConfig,
        MailchimpGetCampaignDomainPerformanceConfig,
        MailchimpGetCampaignEepURLActivityConfig,
        MailchimpGetCampaignLocationsConfig,
        MailchimpGetCampaignSentToConfig,
        MailchimpGetCampaignUnsubscribesConfig,
        MailchimpGetCampaignOpensConfig,
        MailchimpGetMemberCampaignOpenConfig,
        # E-commerce Stores
        MailchimpListEcommerceStoresConfig,
        MailchimpGetEcommerceStoreConfig,
        MailchimpAddEcommerceStoreConfig,
        MailchimpUpdateEcommerceStoreConfig,
        MailchimpDeleteEcommerceStoreConfig,
        # E-commerce Products
        MailchimpListEcommerceProductsConfig,
        MailchimpGetEcommerceProductConfig,
        MailchimpAddEcommerceProductConfig,
        MailchimpUpdateEcommerceProductConfig,
        MailchimpDeleteEcommerceProductConfig,
        MailchimpListEcommerceProductVariantsConfig,
        MailchimpGetEcommerceProductVariantConfig,
        MailchimpAddEcommerceProductVariantConfig,
        MailchimpUpdateEcommerceProductVariantConfig,
        # E-commerce Orders
        MailchimpListEcommerceOrdersConfig,
        MailchimpGetEcommerceOrderConfig,
        MailchimpAddEcommerceOrderConfig,
        MailchimpUpdateEcommerceOrderConfig,
        MailchimpDeleteEcommerceOrderConfig,
        MailchimpListEcommerceOrderLinesConfig,
        MailchimpAddEcommerceOrderLineConfig,
        # E-commerce Customers
        MailchimpListEcommerceCustomersConfig,
        MailchimpGetEcommerceCustomerConfig,
        MailchimpAddEcommerceCustomerConfig,
        MailchimpAddOrUpdateEcommerceCustomerConfig,
        MailchimpUpdateEcommerceCustomerConfig,
        MailchimpDeleteEcommerceCustomerConfig,
        # E-commerce Carts
        MailchimpListEcommerceCartsConfig,
        MailchimpGetEcommerceCartConfig,
        MailchimpAddEcommerceCartConfig,
        MailchimpUpdateEcommerceCartConfig,
        MailchimpDeleteEcommerceCartConfig,
        MailchimpListEcommerceCartLinesConfig,
        MailchimpAddEcommerceCartLineConfig,
        # Batch Operations
        MailchimpStartBatchOperationConfig,
        MailchimpListBatchesConfig,
        MailchimpGetBatchStatusConfig,
        MailchimpDeleteBatchConfig,
        # Webhooks
        MailchimpListWebhooksConfig,
        MailchimpGetWebhookConfig,
        MailchimpAddWebhookConfig,
        MailchimpUpdateWebhookConfig,
        MailchimpDeleteWebhookConfig,
        # Landing Pages
        MailchimpListLandingPagesConfig,
        MailchimpGetLandingPageConfig,
        MailchimpCreateLandingPageConfig,
        MailchimpUpdateLandingPageConfig,
        MailchimpDeleteLandingPageConfig,
        # E-commerce Product Images
        MailchimpListProductImagesConfig,
        MailchimpGetProductImageConfig,
        MailchimpAddProductImageConfig,
        MailchimpUpdateProductImageConfig,
        MailchimpDeleteProductImageConfig,
        # E-commerce Promo Rules
        MailchimpListPromoRulesConfig,
        MailchimpGetPromoRuleConfig,
        MailchimpAddPromoRuleConfig,
        MailchimpUpdatePromoRuleConfig,
        MailchimpDeletePromoRuleConfig,
        # E-commerce Promo Codes
        MailchimpListPromoCodesConfig,
        MailchimpGetPromoCodeConfig,
        MailchimpAddPromoCodeConfig,
        MailchimpUpdatePromoCodeConfig,
        MailchimpDeletePromoCodeConfig,
        # Signup Forms
        MailchimpListSignupFormsConfig,
        MailchimpCreateSignupFormConfig,
        MailchimpUpdateSignupFormConfig,
        # File Manager Folders
        MailchimpListFileManagerFoldersConfig,
        MailchimpGetFileManagerFolderConfig,
        MailchimpCreateFileManagerFolderConfig,
        MailchimpUpdateFileManagerFolderConfig,
        MailchimpDeleteFileManagerFolderConfig,
        # File Manager Files
        MailchimpListFileManagerFilesConfig,
        MailchimpGetFileManagerFileConfig,
        MailchimpUploadFileManagerFileConfig,
        MailchimpUpdateFileManagerFileConfig,
        MailchimpDeleteFileManagerFileConfig,
        # Campaign Folders
        MailchimpListCampaignFoldersConfig,
        MailchimpGetCampaignFolderConfig,
        MailchimpCreateCampaignFolderConfig,
        MailchimpUpdateCampaignFolderConfig,
        MailchimpDeleteCampaignFolderConfig,
        # Template Folders
        MailchimpListTemplateFoldersConfig,
        MailchimpGetTemplateFolderConfig,
        MailchimpCreateTemplateFolderConfig,
        MailchimpUpdateTemplateFolderConfig,
        MailchimpDeleteTemplateFolderConfig,
        # Account/Root Operations
        MailchimpGetAccountInfoConfig,
        MailchimpListAuthorizedAppsConfig,
        MailchimpGetAuthorizedAppConfig,
        MailchimpDisconnectAuthorizedAppConfig,
        MailchimpPingConfig,
        # Additional 115 API Operations
        MailchimpGetRootConfig,
        MailchimpGetChimpChatterConfig,
        MailchimpListAudiencesV2Config,
        MailchimpCreateAudienceV2Config,
        MailchimpGetAudienceV2Config,
        MailchimpUpdateAudienceV2Config,
        MailchimpDeleteAudienceV2Config,
        MailchimpListContactsConfig,
        MailchimpCreateContactConfig,
        MailchimpGetContactConfig,
        MailchimpUpdateContactConfig,
        MailchimpArchiveContactConfig,
        MailchimpForgetContactConfig,
        MailchimpListAutomationEmailsConfig,
        MailchimpGetAutomationEmailConfig,
        MailchimpStartAutomationEmailConfig,
        MailchimpPauseAutomationEmailConfig,
        MailchimpListAutomationQueueConfig,
        MailchimpGetAutomationQueueMemberConfig,
        MailchimpListAutomationRemovedConfig,
        MailchimpGetAutomationRemovedConfig,
        MailchimpAddAutomationRemovedConfig,
        MailchimpListBatchWebhooksConfig,
        MailchimpCreateBatchWebhookConfig,
        MailchimpGetBatchWebhookConfig,
        MailchimpDeleteBatchWebhookConfig,
        MailchimpCancelSendCampaignConfig,
        MailchimpPauseCampaignConfig,
        MailchimpResumeCampaignConfig,
        MailchimpCreateResendCampaignConfig,
        MailchimpListCampaignFeedbackConfig,
        MailchimpCreateCampaignFeedbackConfig,
        MailchimpGetCampaignFeedbackConfig,
        MailchimpDeleteCampaignFeedbackConfig,
        MailchimpGetCampaignChecklistConfig,
        MailchimpListConnectedSitesConfig,
        MailchimpCreateConnectedSiteConfig,
        MailchimpGetConnectedSiteConfig,
        MailchimpUpdateConnectedSiteConfig,
        MailchimpVerifyScriptInstallationConfig,
        MailchimpDeleteConnectedSiteConfig,
        MailchimpListConversationsConfig,
        MailchimpGetConversationConfig,
        MailchimpListConversationMessagesConfig,
        MailchimpCreateConversationMessageConfig,
        MailchimpGetConversationMessageConfig,
        MailchimpTriggerCustomerJourneyStepConfig,
        MailchimpListFolderFilesConfig,
        MailchimpGetLandingPageContentConfig,
        MailchimpUpdateLandingPageContentConfig,
        MailchimpPublishLandingPageConfig,
        MailchimpUnpublishLandingPageConfig,
        MailchimpListAbuseReportsConfig,
        MailchimpGetAbuseReportConfig,
        MailchimpGetListActivityConfig,
        MailchimpGetListClientsConfig,
        MailchimpListGrowthHistoryConfig,
        MailchimpGetGrowthHistoryMonthConfig,
        MailchimpListSegmentMembersConfig,
        MailchimpCreateSegmentMemberConfig,
        MailchimpGetSegmentMemberConfig,
        MailchimpDeleteSegmentMemberConfig,
        MailchimpGetMemberActivityConfig,
        MailchimpListMemberActivityFeedConfig,
        MailchimpGetMemberGoalsConfig,
        MailchimpListMemberNotesConfig,
        MailchimpCreateMemberNoteConfig,
        MailchimpGetMemberNoteConfig,
        MailchimpUpdateMemberNoteConfig,
        MailchimpDeleteMemberNoteConfig,
        MailchimpCreateMemberEventConfig,
        MailchimpGetSignupFormsConfig,
        MailchimpGetListLocationsConfig,
        MailchimpListSurveysConfig,
        MailchimpCreateSurveyConfig,
        MailchimpGetSurveyConfig,
        MailchimpUpdateSurveyConfig,
        MailchimpPublishSurveyConfig,
        MailchimpUnpublishSurveyConfig,
        MailchimpCreateSurveyEmailConfig,
        MailchimpDeleteSurveyConfig,
        MailchimpGetCampaignSubReportsConfig,
        MailchimpGetCampaignAdviceConfig,
        MailchimpGetEcommerceProductActivityReportConfig,
        MailchimpGetTemplateDefaultContentConfig,
        MailchimpUpdateTemplateDefaultContentConfig,
        MailchimpGetOrderLineConfig,
        MailchimpUpdateOrderLineConfig,
        MailchimpDeleteOrderLineConfig,
        MailchimpGetCartLineConfig,
        MailchimpUpdateCartLineConfig,
        MailchimpDeleteCartLineConfig,
        MailchimpListAllEcommerceOrdersConfig,
        MailchimpListFacebookAdsConfig,
        MailchimpGetFacebookAdConfig,
        MailchimpSearchCampaignsConfig,
        MailchimpSearchMembersConfig,
        MailchimpListFacebookAdReportsConfig,
        MailchimpGetFacebookAdReportConfig,
        MailchimpGetFacebookAdEcommerceActivityConfig,
        MailchimpListLandingPageReportsConfig,
        MailchimpGetLandingPageReportConfig,
        MailchimpListSurveyReportsConfig,
        MailchimpGetSurveyReportConfig,
        MailchimpListSurveyQuestionsConfig,
        MailchimpGetSurveyQuestionConfig,
        MailchimpListSurveyAnswersConfig,
        MailchimpListSurveyResponsesConfig,
        MailchimpGetSurveyResponseConfig,
        MailchimpListVerifiedDomainsConfig,
        MailchimpCreateVerifiedDomainConfig,
        MailchimpGetVerifiedDomainConfig,
        MailchimpUpdateVerifiedDomainConfig,
        MailchimpDeleteVerifiedDomainConfig,
        MailchimpVerifyDomainConfig,
        # Account Exports
        MailchimpListAccountExportsConfig,
        MailchimpCreateAccountExportConfig,
        MailchimpGetAccountExportConfig,
        # Automation Archive
        MailchimpArchiveAutomationConfig,
        # Campaign Report Granular Operations
        MailchimpGetCampaignClickDetailMemberConfig,
        MailchimpGetCampaignSentToMemberConfig,
        MailchimpGetCampaignUnsubscribedMemberConfig,
        # Conversation Message Operations
        MailchimpUpdateConversationMessageConfig,
        MailchimpDeleteConversationMessageConfig,
        # E-commerce Product Variant Delete
        MailchimpDeleteEcommerceProductVariantConfig,
        # Automation Email Queue POST
        MailchimpAddAutomationQueueMemberConfig,
        # Mandrill/Transactional API Operations (95 total)
        # Allowlists (3)
        MailchimpMandrillAllowlistsAddConfig,
        MailchimpMandrillAllowlistsListConfig,
        MailchimpMandrillAllowlistsDeleteConfig,
        # Exports (6)
        MailchimpMandrillExportsInfoConfig,
        MailchimpMandrillExportsListConfig,
        MailchimpMandrillExportsRejectsConfig,
        MailchimpMandrillExportsWhitelistConfig,
        MailchimpMandrillExportsAllowlistConfig,
        MailchimpMandrillExportsActivityConfig,
        # Inbound (9)
        MailchimpMandrillInboundDomainsConfig,
        MailchimpMandrillInboundAddDomainConfig,
        MailchimpMandrillInboundCheckDomainConfig,
        MailchimpMandrillInboundDeleteDomainConfig,
        MailchimpMandrillInboundRoutesConfig,
        MailchimpMandrillInboundAddRouteConfig,
        MailchimpMandrillInboundUpdateRouteConfig,
        MailchimpMandrillInboundDeleteRouteConfig,
        MailchimpMandrillInboundSendRawConfig,
        # IPs (13)
        MailchimpMandrillIpsListConfig,
        MailchimpMandrillIpsInfoConfig,
        MailchimpMandrillIpsProvisionConfig,
        MailchimpMandrillIpsStartWarmupConfig,
        MailchimpMandrillIpsCancelWarmupConfig,
        MailchimpMandrillIpsSetPoolConfig,
        MailchimpMandrillIpsDeleteConfig,
        MailchimpMandrillIpsListPoolsConfig,
        MailchimpMandrillIpsPoolInfoConfig,
        MailchimpMandrillIpsCreatePoolConfig,
        MailchimpMandrillIpsDeletePoolConfig,
        MailchimpMandrillIpsCheckCustomDnsConfig,
        MailchimpMandrillIpsSetCustomDnsConfig,
        # Messages (12)
        MailchimpMandrillMessagesSendSmsConfig,
        MailchimpMandrillMessagesSendConfig,
        MailchimpMandrillMessagesSendTemplateConfig,
        MailchimpMandrillMessagesSearchConfig,
        MailchimpMandrillMessagesSearchTimeSeriesConfig,
        MailchimpMandrillMessagesInfoConfig,
        MailchimpMandrillMessagesContentConfig,
        MailchimpMandrillMessagesParseConfig,
        MailchimpMandrillMessagesSendRawConfig,
        MailchimpMandrillMessagesListScheduledConfig,
        MailchimpMandrillMessagesCancelScheduledConfig,
        MailchimpMandrillMessagesRescheduleConfig,
        # Metadata (4)
        MailchimpMandrillMetadataListConfig,
        MailchimpMandrillMetadataAddConfig,
        MailchimpMandrillMetadataUpdateConfig,
        MailchimpMandrillMetadataDeleteConfig,
        # Rejects (3)
        MailchimpMandrillRejectsAddConfig,
        MailchimpMandrillRejectsListConfig,
        MailchimpMandrillRejectsDeleteConfig,
        # Senders (7)
        MailchimpMandrillSendersListConfig,
        MailchimpMandrillSendersDomainsConfig,
        MailchimpMandrillSendersAddDomainConfig,
        MailchimpMandrillSendersCheckDomainConfig,
        MailchimpMandrillSendersVerifyDomainConfig,
        MailchimpMandrillSendersInfoConfig,
        MailchimpMandrillSendersTimeSeriesConfig,
        # Subaccounts (7)
        MailchimpMandrillSubaccountsListConfig,
        MailchimpMandrillSubaccountsAddConfig,
        MailchimpMandrillSubaccountsInfoConfig,
        MailchimpMandrillSubaccountsUpdateConfig,
        MailchimpMandrillSubaccountsDeleteConfig,
        MailchimpMandrillSubaccountsPauseConfig,
        MailchimpMandrillSubaccountsResumeConfig,
        # Tags (5)
        MailchimpMandrillTagsListConfig,
        MailchimpMandrillTagsDeleteConfig,
        MailchimpMandrillTagsInfoConfig,
        MailchimpMandrillTagsTimeSeriesConfig,
        MailchimpMandrillTagsAllTimeSeriesConfig,
        # Templates (8)
        MailchimpMandrillTemplatesAddConfig,
        MailchimpMandrillTemplatesInfoConfig,
        MailchimpMandrillTemplatesUpdateConfig,
        MailchimpMandrillTemplatesPublishConfig,
        MailchimpMandrillTemplatesDeleteConfig,
        MailchimpMandrillTemplatesListConfig,
        MailchimpMandrillTemplatesTimeSeriesConfig,
        MailchimpMandrillTemplatesRenderConfig,
        # URLs (6)
        MailchimpMandrillUrlsListConfig,
        MailchimpMandrillUrlsSearchConfig,
        MailchimpMandrillUrlsTimeSeriesConfig,
        MailchimpMandrillUrlsTrackingDomainsConfig,
        MailchimpMandrillUrlsAddTrackingDomainConfig,
        MailchimpMandrillUrlsCheckTrackingDomainConfig,
        # Users (4)
        MailchimpMandrillUsersInfoConfig,
        MailchimpMandrillUsersPingConfig,
        MailchimpMandrillUsersPing2Config,
        MailchimpMandrillUsersSendersConfig,
        # Webhooks (5)
        MailchimpMandrillWebhooksListConfig,
        MailchimpMandrillWebhooksAddConfig,
        MailchimpMandrillWebhooksInfoConfig,
        MailchimpMandrillWebhooksUpdateConfig,
        MailchimpMandrillWebhooksDeleteConfig,
        # Whitelists (3)
        MailchimpMandrillWhitelistsAddConfig,
        MailchimpMandrillWhitelistsListConfig,
        MailchimpMandrillWhitelistsDeleteConfig,
    ],
    Discriminator("operation"),
]


class MailchimpNodeConfig(NodeConfig[MailchimpConfig, MailchimpCredential]):
    """Full configuration for Mailchimp node including credentials."""

    pass


# ============================================================================
# Node Implementation
# ============================================================================


class MailchimpNode(WorkflowNode):
    """
    Mailchimp automation node for Marketing and Transactional APIs.

    Provides comprehensive integration with 384 operations:
    - Marketing API v3.0: 289 operations across 40+ resource categories
    - Transactional API (Mandrill): 95 operations across 15 resource categories
    """

    edit_examples = [
        "Add new subscribers to newsletter list with tags and segments",
        "Create and send email campaign to engaged members in US",
        "Update customer profile with purchase history and interests",
        "Add contacts to automated welcome email sequence",
        "Send transactional email with order confirmation and details",
        "Get campaign analytics including opens, clicks, conversions",
        "Remove unsubscribed users from all mailing lists",
    ]

    scope_registry = MAILCHIMP_SCOPES
    connection_evidence = ConnectionEvidence(
        operation="list_audiences",
        noun="audiences",
        identity_operation="fetch_user_info",
    )

    @classmethod
    def get_config_model(cls):
        return MailchimpNodeConfig

    def _get_api_base_url(self, credentials: MailchimpCredential) -> str:
        """Extract datacenter from credentials and construct base URL."""
        if isinstance(credentials, MailchimpAPIKeyCredential):
            # API key format: xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx-us1
            # Extract datacenter (e.g., 'us1') from after the dash
            parts = credentials.api_key.split("-")
            if len(parts) != 2:
                raise ValueError(
                    "Invalid API key format. Expected format: key-datacenter"
                )
            dc = normalize_provider_subdomain(
                parts[1],
                "api.mailchimp.com",
                field_name="Mailchimp datacenter",
            )
            return f"https://{dc}.api.mailchimp.com/{MAILCHIMP_API_VERSION}/"

        elif isinstance(credentials, MailchimpOAuthCredential):
            dc = credentials.server_prefix or (
                credentials.metadata or {}
            ).get("server_prefix")
            if not dc:
                raise ValueError("OAuth credentials missing server prefix")
            dc = normalize_provider_subdomain(
                dc,
                "api.mailchimp.com",
                field_name="Mailchimp server prefix",
            )
            return f"https://{dc}.api.mailchimp.com/{MAILCHIMP_API_VERSION}/"

        raise ValueError("Unknown credential type")

    def _get_auth_headers(self, credentials: MailchimpCredential) -> Dict[str, str]:
        """Get authentication headers based on credential type."""
        if isinstance(credentials, MailchimpAPIKeyCredential):
            # API Key uses HTTP Basic Auth with 'anystring' as username
            import base64

            auth_string = base64.b64encode(
                f"anystring:{credentials.api_key}".encode()
            ).decode()
            return {
                "Authorization": f"Basic {auth_string}",
                "Content-Type": "application/json",
            }

        elif isinstance(credentials, MailchimpOAuthCredential):
            # OAuth uses Bearer token
            return {
                "Authorization": f"Bearer {credentials.access_token}",
                "Content-Type": "application/json",
            }

        raise ValueError("Unknown credential type")

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the configured Mailchimp operation."""
        start_time = time.time()

        config = self.config.config
        credentials = self.config.credentials
        action = config.operation

        try:
            # Route to appropriate handler based on action
            if action == "list_all_lists":
                result = await self._handle_list_lists(config, credentials)
            elif action == "fetch_list":
                result = await self._handle_get_list(config, credentials)
            elif action == "create_list":
                result = await self._handle_create_list(config, credentials)
            elif action == "update_list_settings":
                result = await self._handle_update_list(config, credentials)
            elif action == "archive_list":
                result = await self._handle_delete_list(config, credentials)

            # List Members
            elif action == "list_list_members":
                result = await self._handle_list_members(config, credentials)
            elif action == "fetch_list_member":
                result = await self._handle_get_member(config, credentials)
            elif action == "create_list_member":
                result = await self._handle_add_member(config, credentials)
            elif action == "update_list_member":
                result = await self._handle_update_member(config, credentials)
            elif action == "upsert_list_member":
                result = await self._handle_add_or_update_member(config, credentials)
            elif action == "archive_list_member":
                result = await self._handle_delete_member(config, credentials)
            elif action == "permanently_delete_list_member":
                result = await self._handle_permanently_delete_member(
                    config, credentials
                )

            # Campaigns
            elif action == "list_campaigns":
                result = await self._handle_list_campaigns(config, credentials)
            elif action == "fetch_campaign":
                result = await self._handle_get_campaign(config, credentials)
            elif action == "create_campaign":
                result = await self._handle_create_campaign(config, credentials)
            elif action == "update_campaign_settings":
                result = await self._handle_update_campaign(config, credentials)
            elif action == "delete_campaign":
                result = await self._handle_delete_campaign(config, credentials)
            elif action == "send_campaign_immediately":
                result = await self._handle_send_campaign(config, credentials)
            elif action == "schedule_campaign_for_delivery":
                result = await self._handle_schedule_campaign(config, credentials)
            elif action == "unschedule_campaign":
                result = await self._handle_unschedule_campaign(config, credentials)
            elif action == "send_campaign_test_email":
                result = await self._handle_send_test_email(config, credentials)
            elif action == "duplicate_campaign":
                result = await self._handle_replicate_campaign(config, credentials)

            # Campaign Content
            elif action == "fetch_campaign_content":
                result = await self._handle_get_campaign_content(config, credentials)
            elif action == "update_campaign_content":
                result = await self._handle_set_campaign_content(config, credentials)

            # Automations
            elif action == "list_automation_workflows":
                result = await self._handle_list_automations(config, credentials)
            elif action == "fetch_automation_workflow":
                result = await self._handle_get_automation(config, credentials)
            elif action == "pause_automation_workflow":
                result = await self._handle_pause_automation(config, credentials)
            elif action == "start_automation_workflow":
                result = await self._handle_start_automation(config, credentials)

            # Tags
            elif action == "list_member_tags":
                result = await self._handle_get_member_tags(config, credentials)
            elif action == "update_member_tags":
                result = await self._handle_add_or_remove_member_tags(
                    config, credentials
                )
            elif action == "search_list_tags":
                result = await self._handle_search_tags(config, credentials)

            # Segments
            elif action == "list_list_segments":
                result = await self._handle_list_segments(config, credentials)
            elif action == "fetch_list_segment":
                result = await self._handle_get_segment(config, credentials)
            elif action == "create_list_segment":
                result = await self._handle_create_segment(config, credentials)
            elif action == "update_list_segment":
                result = await self._handle_update_segment(config, credentials)
            elif action == "delete_list_segment":
                result = await self._handle_delete_segment(config, credentials)
            elif action == "update_segment_members_batch":
                result = await self._handle_batch_add_remove_segment_members(
                    config, credentials
                )

            # Merge Fields
            elif action == "list_merge_fields":
                result = await self._handle_list_merge_fields(config, credentials)
            elif action == "fetch_merge_field":
                result = await self._handle_get_merge_field(config, credentials)
            elif action == "create_merge_field":
                result = await self._handle_add_merge_field(config, credentials)
            elif action == "update_merge_field":
                result = await self._handle_update_merge_field(config, credentials)
            elif action == "delete_merge_field":
                result = await self._handle_delete_merge_field(config, credentials)

            # Interest Categories
            elif action == "list_interest_categories":
                result = await self._handle_list_interest_categories(
                    config, credentials
                )
            elif action == "fetch_interest_category":
                result = await self._handle_get_interest_category(config, credentials)
            elif action == "create_interest_category":
                result = await self._handle_create_interest_category(
                    config, credentials
                )
            elif action == "update_interest_category":
                result = await self._handle_update_interest_category(
                    config, credentials
                )
            elif action == "delete_interest_category":
                result = await self._handle_delete_interest_category(
                    config, credentials
                )

            # Interests
            elif action == "list_category_interests":
                result = await self._handle_list_interests(config, credentials)
            elif action == "fetch_category_interest":
                result = await self._handle_get_interest(config, credentials)
            elif action == "create_category_interest":
                result = await self._handle_create_interest(config, credentials)
            elif action == "update_category_interest":
                result = await self._handle_update_interest(config, credentials)
            elif action == "delete_category_interest":
                result = await self._handle_delete_interest(config, credentials)

            # Templates
            elif action == "list_email_templates":
                result = await self._handle_list_templates(config, credentials)
            elif action == "fetch_email_template":
                result = await self._handle_get_template(config, credentials)
            elif action == "create_email_template":
                result = await self._handle_create_template(config, credentials)
            elif action == "update_email_template":
                result = await self._handle_update_template(config, credentials)
            elif action == "delete_email_template":
                result = await self._handle_delete_template(config, credentials)

            # Reports
            elif action == "list_campaign_reports":
                result = await self._handle_list_campaign_reports(config, credentials)
            elif action == "fetch_campaign_report":
                result = await self._handle_get_campaign_report(config, credentials)
            elif action == "fetch_campaign_email_activity":
                result = await self._handle_get_campaign_email_activity(
                    config, credentials
                )
            elif action == "list_campaign_abuse_reports":
                result = await self._handle_get_campaign_abuse_reports(
                    config, credentials
                )
            elif action == "fetch_campaign_abuse_report":
                result = await self._handle_get_campaign_abuse_report(
                    config, credentials
                )
            elif action == "fetch_campaign_click_details":
                result = await self._handle_get_campaign_click_details(
                    config, credentials
                )
            elif action == "fetch_link_click_details":
                result = await self._handle_get_campaign_click_details_for_link(
                    config, credentials
                )
            elif action == "list_members_who_clicked_link":
                result = await self._handle_get_campaign_click_detail_members(
                    config, credentials
                )
            elif action == "fetch_campaign_domain_performance":
                result = await self._handle_get_campaign_domain_performance(
                    config, credentials
                )
            elif action == "fetch_campaign_eepurl_activity":
                result = await self._handle_get_campaign_eepurl_activity(
                    config, credentials
                )
            elif action == "fetch_campaign_top_locations":
                result = await self._handle_get_campaign_locations(config, credentials)
            elif action == "list_campaign_recipients":
                result = await self._handle_get_campaign_sent_to(config, credentials)
            elif action == "list_campaign_unsubscribes":
                result = await self._handle_get_campaign_unsubscribes(
                    config, credentials
                )
            elif action == "fetch_campaign_opens":
                result = await self._handle_get_campaign_opens(config, credentials)
            elif action == "fetch_member_campaign_opens":
                result = await self._handle_get_member_campaign_open(
                    config, credentials
                )

            # E-commerce Stores
            elif action == "list_ecommerce_stores":
                result = await self._handle_list_ecommerce_stores(config, credentials)
            elif action == "fetch_ecommerce_store":
                result = await self._handle_get_ecommerce_store(config, credentials)
            elif action == "create_ecommerce_store":
                result = await self._handle_add_ecommerce_store(config, credentials)
            elif action == "update_ecommerce_store":
                result = await self._handle_update_ecommerce_store(config, credentials)
            elif action == "delete_ecommerce_store":
                result = await self._handle_delete_ecommerce_store(config, credentials)

            # E-commerce Products
            elif action == "list_ecommerce_products":
                result = await self._handle_list_ecommerce_products(config, credentials)
            elif action == "fetch_ecommerce_product":
                result = await self._handle_get_ecommerce_product(config, credentials)
            elif action == "create_ecommerce_product":
                result = await self._handle_add_ecommerce_product(config, credentials)
            elif action == "update_ecommerce_product":
                result = await self._handle_update_ecommerce_product(
                    config, credentials
                )
            elif action == "delete_ecommerce_product":
                result = await self._handle_delete_ecommerce_product(
                    config, credentials
                )
            elif action == "list_product_variants":
                result = await self._handle_list_ecommerce_product_variants(
                    config, credentials
                )
            elif action == "fetch_product_variant":
                result = await self._handle_get_ecommerce_product_variant(
                    config, credentials
                )
            elif action == "create_product_variant":
                result = await self._handle_add_ecommerce_product_variant(
                    config, credentials
                )
            elif action == "update_product_variant":
                result = await self._handle_update_ecommerce_product_variant(
                    config, credentials
                )

            # E-commerce Orders
            elif action == "list_ecommerce_orders":
                result = await self._handle_list_ecommerce_orders(config, credentials)
            elif action == "fetch_ecommerce_order":
                result = await self._handle_get_ecommerce_order(config, credentials)
            elif action == "create_ecommerce_order":
                result = await self._handle_add_ecommerce_order(config, credentials)
            elif action == "update_ecommerce_order":
                result = await self._handle_update_ecommerce_order(config, credentials)
            elif action == "delete_ecommerce_order":
                result = await self._handle_delete_ecommerce_order(config, credentials)
            elif action == "list_order_line_items":
                result = await self._handle_list_ecommerce_order_lines(
                    config, credentials
                )
            elif action == "create_order_line_item":
                result = await self._handle_add_ecommerce_order_line(
                    config, credentials
                )

            # E-commerce Customers
            elif action == "list_ecommerce_customers":
                result = await self._handle_list_ecommerce_customers(
                    config, credentials
                )
            elif action == "fetch_ecommerce_customer":
                result = await self._handle_get_ecommerce_customer(config, credentials)
            elif action == "create_ecommerce_customer":
                result = await self._handle_add_ecommerce_customer(config, credentials)
            elif action == "upsert_ecommerce_customer":
                result = await self._handle_add_or_update_ecommerce_customer(
                    config, credentials
                )
            elif action == "update_ecommerce_customer":
                result = await self._handle_update_ecommerce_customer(
                    config, credentials
                )
            elif action == "delete_ecommerce_customer":
                result = await self._handle_delete_ecommerce_customer(
                    config, credentials
                )

            # E-commerce Carts
            elif action == "list_ecommerce_carts":
                result = await self._handle_list_ecommerce_carts(config, credentials)
            elif action == "fetch_ecommerce_cart":
                result = await self._handle_get_ecommerce_cart(config, credentials)
            elif action == "create_ecommerce_cart":
                result = await self._handle_add_ecommerce_cart(config, credentials)
            elif action == "update_ecommerce_cart":
                result = await self._handle_update_ecommerce_cart(config, credentials)
            elif action == "delete_ecommerce_cart":
                result = await self._handle_delete_ecommerce_cart(config, credentials)
            elif action == "list_cart_line_items":
                result = await self._handle_list_ecommerce_cart_lines(
                    config, credentials
                )
            elif action == "create_cart_line_item":
                result = await self._handle_add_ecommerce_cart_line(config, credentials)

            # Batch Operations
            elif action == "start_batch_operation":
                result = await self._handle_start_batch_operation(config, credentials)
            elif action == "list_batch_operations":
                result = await self._handle_list_batches(config, credentials)
            elif action == "fetch_batch_status":
                result = await self._handle_get_batch_status(config, credentials)
            elif action == "cancel_batch_request":
                result = await self._handle_delete_batch(config, credentials)

            # Webhooks
            elif action == "list_list_webhooks":
                result = await self._handle_list_webhooks(config, credentials)
            elif action == "fetch_list_webhook":
                result = await self._handle_get_webhook(config, credentials)
            elif action == "create_list_webhook":
                result = await self._handle_add_webhook(config, credentials)
            elif action == "update_list_webhook":
                result = await self._handle_update_webhook(config, credentials)
            elif action == "delete_list_webhook":
                result = await self._handle_delete_webhook(config, credentials)

            # Landing Pages
            elif action == "list_landing_pages":
                result = await self._handle_list_landing_pages(config, credentials)
            elif action == "fetch_landing_page":
                result = await self._handle_get_landing_page(config, credentials)
            elif action == "create_landing_page":
                result = await self._handle_create_landing_page(config, credentials)
            elif action == "update_landing_page":
                result = await self._handle_update_landing_page(config, credentials)
            elif action == "delete_landing_page":
                result = await self._handle_delete_landing_page(config, credentials)

            # E-commerce Product Images
            elif action == "list_product_images":
                result = await self._handle_list_product_images(config, credentials)
            elif action == "fetch_product_image":
                result = await self._handle_get_product_image(config, credentials)
            elif action == "add_product_image":
                result = await self._handle_add_product_image(config, credentials)
            elif action == "update_product_image":
                result = await self._handle_update_product_image(config, credentials)
            elif action == "delete_product_image":
                result = await self._handle_delete_product_image(config, credentials)

            # E-commerce Promo Rules
            elif action == "list_promo_rules":
                result = await self._handle_list_promo_rules(config, credentials)
            elif action == "fetch_promo_rule":
                result = await self._handle_get_promo_rule(config, credentials)
            elif action == "create_promo_rule":
                result = await self._handle_add_promo_rule(config, credentials)
            elif action == "update_promo_rule":
                result = await self._handle_update_promo_rule(config, credentials)
            elif action == "delete_promo_rule":
                result = await self._handle_delete_promo_rule(config, credentials)

            # E-commerce Promo Codes
            elif action == "list_promo_codes":
                result = await self._handle_list_promo_codes(config, credentials)
            elif action == "fetch_promo_code":
                result = await self._handle_get_promo_code(config, credentials)
            elif action == "create_promo_code":
                result = await self._handle_add_promo_code(config, credentials)
            elif action == "update_promo_code":
                result = await self._handle_update_promo_code(config, credentials)
            elif action == "delete_promo_code":
                result = await self._handle_delete_promo_code(config, credentials)

            # Signup Forms
            elif action == "list_signup_forms":
                result = await self._handle_list_signup_forms(config, credentials)
            elif action == "create_signup_form":
                result = await self._handle_create_signup_form(config, credentials)
            elif action == "update_signup_form":
                result = await self._handle_update_signup_form(config, credentials)

            # File Manager Folders
            elif action == "list_file_folders":
                result = await self._handle_list_file_manager_folders(
                    config, credentials
                )
            elif action == "fetch_file_folder":
                result = await self._handle_get_file_manager_folder(config, credentials)
            elif action == "create_file_folder":
                result = await self._handle_create_file_manager_folder(
                    config, credentials
                )
            elif action == "update_file_folder":
                result = await self._handle_update_file_manager_folder(
                    config, credentials
                )
            elif action == "delete_file_folder":
                result = await self._handle_delete_file_manager_folder(
                    config, credentials
                )

            # File Manager Files
            elif action == "list_files":
                result = await self._handle_list_file_manager_files(config, credentials)
            elif action == "fetch_file":
                result = await self._handle_get_file_manager_file(config, credentials)
            elif action == "upload_file":
                result = await self._handle_upload_file_manager_file(
                    config, credentials
                )
            elif action == "update_file":
                result = await self._handle_update_file_manager_file(
                    config, credentials
                )
            elif action == "delete_file":
                result = await self._handle_delete_file_manager_file(
                    config, credentials
                )

            # Campaign Folders
            elif action == "list_campaign_folders":
                result = await self._handle_list_campaign_folders(config, credentials)
            elif action == "fetch_campaign_folder":
                result = await self._handle_get_campaign_folder(config, credentials)
            elif action == "create_campaign_folder":
                result = await self._handle_create_campaign_folder(config, credentials)
            elif action == "update_campaign_folder":
                result = await self._handle_update_campaign_folder(config, credentials)
            elif action == "delete_campaign_folder":
                result = await self._handle_delete_campaign_folder(config, credentials)

            # Template Folders
            elif action == "list_template_folders":
                result = await self._handle_list_template_folders(config, credentials)
            elif action == "fetch_template_folder":
                result = await self._handle_get_template_folder(config, credentials)
            elif action == "create_template_folder":
                result = await self._handle_create_template_folder(config, credentials)
            elif action == "update_template_folder":
                result = await self._handle_update_template_folder(config, credentials)
            elif action == "delete_template_folder":
                result = await self._handle_delete_template_folder(config, credentials)

            # Account/Root Operations
            elif action == "fetch_account_info":
                result = await self._handle_get_account_info(config, credentials)
            elif action == "list_authorized_apps":
                result = await self._handle_list_authorized_apps(config, credentials)
            elif action == "fetch_authorized_app":
                result = await self._handle_get_authorized_app(config, credentials)
            elif action == "disconnect_authorized_app":
                result = await self._handle_disconnect_authorized_app(
                    config, credentials
                )
            elif action == "ping_api_connection":
                result = await self._handle_ping(config, credentials)

            # Additional 115 API Operations
            elif action == "fetch_api_root_info":
                result = await self._handle_get_root(config, credentials)
            elif action == "fetch_activity_feed":
                result = await self._handle_get_chimp_chatter(config, credentials)
            elif action == "list_audiences":
                result = await self._handle_list_audiences_v2(config, credentials)
            elif action == "create_audience":
                result = await self._handle_create_audience_v2(config, credentials)
            elif action == "fetch_audience":
                result = await self._handle_get_audience_v2(config, credentials)
            elif action == "update_audience_settings":
                result = await self._handle_update_audience_v2(config, credentials)
            elif action == "delete_audience":
                result = await self._handle_delete_audience_v2(config, credentials)
            elif action == "list_audience_contacts":
                result = await self._handle_list_contacts(config, credentials)
            elif action == "create_audience_contact":
                result = await self._handle_create_contact(config, credentials)
            elif action == "fetch_audience_contact":
                result = await self._handle_get_contact(config, credentials)
            elif action == "update_audience_contact":
                result = await self._handle_update_contact(config, credentials)
            elif action == "archive_list_contact":
                result = await self._handle_archive_contact(config, credentials)
            elif action == "permanently_delete_contact_data":
                result = await self._handle_forget_contact(config, credentials)
            elif action == "list_automation_emails":
                result = await self._handle_list_automation_emails(config, credentials)
            elif action == "fetch_automation_email":
                result = await self._handle_get_automation_email(config, credentials)
            elif action == "start_automation_email":
                result = await self._handle_start_automation_email(config, credentials)
            elif action == "pause_automation_email":
                result = await self._handle_pause_automation_email(config, credentials)
            elif action == "list_automation_queue_members":
                result = await self._handle_list_automation_queue(config, credentials)
            elif action == "fetch_automation_queue_member":
                result = await self._handle_get_automation_queue_member(
                    config, credentials
                )
            elif action == "list_automation_removed_members":
                result = await self._handle_list_automation_removed(config, credentials)
            elif action == "fetch_automation_removed_member":
                result = await self._handle_get_automation_removed(config, credentials)
            elif action == "remove_member_from_automation":
                result = await self._handle_add_automation_removed(config, credentials)
            elif action == "list_batch_webhooks":
                result = await self._handle_list_batch_webhooks(config, credentials)
            elif action == "create_batch_webhook":
                result = await self._handle_create_batch_webhook(config, credentials)
            elif action == "fetch_batch_webhook":
                result = await self._handle_get_batch_webhook(config, credentials)
            elif action == "delete_batch_webhook":
                result = await self._handle_delete_batch_webhook(config, credentials)
            elif action == "cancel_campaign_send":
                result = await self._handle_cancel_send_campaign(config, credentials)
            elif action == "pause_rss_campaign":
                result = await self._handle_pause_campaign(config, credentials)
            elif action == "resume_rss_campaign":
                result = await self._handle_resume_campaign(config, credentials)
            elif action == "create_campaign_resend":
                result = await self._handle_create_resend_campaign(config, credentials)
            elif action == "list_campaign_feedback":
                result = await self._handle_list_campaign_feedback(config, credentials)
            elif action == "add_campaign_feedback":
                result = await self._handle_create_campaign_feedback(
                    config, credentials
                )
            elif action == "fetch_campaign_feedback":
                result = await self._handle_get_campaign_feedback(config, credentials)
            elif action == "delete_campaign_feedback":
                result = await self._handle_delete_campaign_feedback(
                    config, credentials
                )
            elif action == "fetch_campaign_checklist":
                result = await self._handle_get_campaign_checklist(config, credentials)
            elif action == "list_connected_sites":
                result = await self._handle_list_connected_sites(config, credentials)
            elif action == "create_connected_site":
                result = await self._handle_create_connected_site(config, credentials)
            elif action == "fetch_connected_site":
                result = await self._handle_get_connected_site(config, credentials)
            elif action == "update_connected_site":
                result = await self._handle_update_connected_site(config, credentials)
            elif action == "verify_connected_site_script":
                result = await self._handle_verify_script_installation(
                    config, credentials
                )
            elif action == "delete_connected_site":
                result = await self._handle_delete_connected_site(config, credentials)
            elif action == "list_conversations":
                result = await self._handle_list_conversations(config, credentials)
            elif action == "fetch_conversation":
                result = await self._handle_get_conversation(config, credentials)
            elif action == "list_conversation_messages":
                result = await self._handle_list_conversation_messages(
                    config, credentials
                )
            elif action == "post_conversation_message":
                result = await self._handle_create_conversation_message(
                    config, credentials
                )
            elif action == "fetch_conversation_message":
                result = await self._handle_get_conversation_message(
                    config, credentials
                )
            elif action == "trigger_customer_journey_step":
                result = await self._handle_trigger_customer_journey_step(
                    config, credentials
                )
            elif action == "list_files_in_folder":
                result = await self._handle_list_folder_files(config, credentials)
            elif action == "fetch_landing_page_content":
                result = await self._handle_get_landing_page_content(
                    config, credentials
                )
            elif action == "update_landing_page_html":
                result = await self._handle_update_landing_page_content(
                    config, credentials
                )
            elif action == "publish_landing_page":
                result = await self._handle_publish_landing_page(config, credentials)
            elif action == "unpublish_landing_page":
                result = await self._handle_unpublish_landing_page(config, credentials)
            elif action == "list_abuse_reports":
                result = await self._handle_list_abuse_reports(config, credentials)
            elif action == "fetch_abuse_report":
                result = await self._handle_get_abuse_report(config, credentials)
            elif action == "fetch_list_activity":
                result = await self._handle_get_list_activity(config, credentials)
            elif action == "fetch_list_email_clients":
                result = await self._handle_get_list_clients(config, credentials)
            elif action == "list_growth_history":
                result = await self._handle_list_growth_history(config, credentials)
            elif action == "fetch_growth_history_for_month":
                result = await self._handle_get_growth_history_month(
                    config, credentials
                )
            elif action == "list_segment_members":
                result = await self._handle_list_segment_members(config, credentials)
            elif action == "add_member_to_segment":
                result = await self._handle_create_segment_member(config, credentials)
            elif action == "fetch_segment_member":
                result = await self._handle_get_segment_member(config, credentials)
            elif action == "remove_member_from_segment":
                result = await self._handle_delete_segment_member(config, credentials)
            elif action == "fetch_member_activity":
                result = await self._handle_get_member_activity(config, credentials)
            elif action == "list_member_activity_feed":
                result = await self._handle_list_member_activity_feed(
                    config, credentials
                )
            elif action == "fetch_member_goals":
                result = await self._handle_get_member_goals(config, credentials)
            elif action == "list_member_notes":
                result = await self._handle_list_member_notes(config, credentials)
            elif action == "add_member_note":
                result = await self._handle_create_member_note(config, credentials)
            elif action == "fetch_member_note":
                result = await self._handle_get_member_note(config, credentials)
            elif action == "update_member_note":
                result = await self._handle_update_member_note(config, credentials)
            elif action == "delete_member_note":
                result = await self._handle_delete_member_note(config, credentials)
            elif action == "create_member_event":
                result = await self._handle_create_member_event(config, credentials)
            elif action == "fetch_signup_forms":
                result = await self._handle_get_signup_forms(config, credentials)
            elif action == "fetch_list_subscriber_locations":
                result = await self._handle_get_list_locations(config, credentials)
            elif action == "list_surveys":
                result = await self._handle_list_surveys(config, credentials)
            elif action == "create_survey":
                result = await self._handle_create_survey(config, credentials)
            elif action == "fetch_survey":
                result = await self._handle_get_survey(config, credentials)
            elif action == "update_survey":
                result = await self._handle_update_survey(config, credentials)
            elif action == "publish_survey":
                result = await self._handle_publish_survey(config, credentials)
            elif action == "unpublish_survey":
                result = await self._handle_unpublish_survey(config, credentials)
            elif action == "send_survey_email":
                result = await self._handle_create_survey_email(config, credentials)
            elif action == "delete_survey":
                result = await self._handle_delete_survey(config, credentials)
            elif action == "fetch_campaign_subreports":
                result = await self._handle_get_campaign_sub_reports(
                    config, credentials
                )
            elif action == "fetch_campaign_advice":
                result = await self._handle_get_campaign_advice(config, credentials)
            elif action == "fetch_product_activity_report":
                result = await self._handle_get_ecommerce_product_activity_report(
                    config, credentials
                )
            elif action == "fetch_template_default_content":
                result = await self._handle_get_template_default_content(
                    config, credentials
                )
            elif action == "update_template_default_content":
                result = await self._handle_update_template_default_content(
                    config, credentials
                )
            elif action == "fetch_order_line_item":
                result = await self._handle_get_order_line(config, credentials)
            elif action == "update_order_line_item":
                result = await self._handle_update_order_line(config, credentials)
            elif action == "delete_order_line_item":
                result = await self._handle_delete_order_line(config, credentials)
            elif action == "fetch_cart_line_item":
                result = await self._handle_get_cart_line(config, credentials)
            elif action == "update_cart_line_item":
                result = await self._handle_update_cart_line(config, credentials)
            elif action == "delete_cart_line_item":
                result = await self._handle_delete_cart_line(config, credentials)
            elif action == "list_all_ecommerce_orders":
                result = await self._handle_list_all_ecommerce_orders(
                    config, credentials
                )
            elif action == "list_facebook_ads":
                result = await self._handle_list_facebook_ads(config, credentials)
            elif action == "fetch_facebook_ad":
                result = await self._handle_get_facebook_ad(config, credentials)
            elif action == "search_campaigns_by_name":
                result = await self._handle_search_campaigns(config, credentials)
            elif action == "search_list_members":
                result = await self._handle_search_members(config, credentials)
            elif action == "list_facebook_ad_reports":
                result = await self._handle_list_facebook_ad_reports(
                    config, credentials
                )
            elif action == "fetch_facebook_ad_report":
                result = await self._handle_get_facebook_ad_report(config, credentials)
            elif action == "fetch_facebook_ad_ecommerce_activity":
                result = await self._handle_get_facebook_ad_ecommerce_activity(
                    config, credentials
                )
            elif action == "list_landing_page_reports":
                result = await self._handle_list_landing_page_reports(
                    config, credentials
                )
            elif action == "fetch_landing_page_report":
                result = await self._handle_get_landing_page_report(config, credentials)
            elif action == "list_survey_reports":
                result = await self._handle_list_survey_reports(config, credentials)
            elif action == "fetch_survey_report":
                result = await self._handle_get_survey_report(config, credentials)
            elif action == "list_survey_questions":
                result = await self._handle_list_survey_questions(config, credentials)
            elif action == "fetch_survey_question":
                result = await self._handle_get_survey_question(config, credentials)
            elif action == "list_survey_question_answers":
                result = await self._handle_list_survey_answers(config, credentials)
            elif action == "list_survey_responses":
                result = await self._handle_list_survey_responses(config, credentials)
            elif action == "fetch_survey_response":
                result = await self._handle_get_survey_response(config, credentials)
            elif action == "list_verified_domains":
                result = await self._handle_list_verified_domains(config, credentials)
            elif action == "add_domain_for_verification":
                result = await self._handle_create_verified_domain(config, credentials)
            elif action == "fetch_verified_domain":
                result = await self._handle_get_verified_domain(config, credentials)
            elif action == "update_verified_domain":
                result = await self._handle_update_verified_domain(config, credentials)
            elif action == "delete_verified_domain":
                result = await self._handle_delete_verified_domain(config, credentials)
            elif action == "verify_domain_for_sending":
                result = await self._handle_verify_domain(config, credentials)

            # Account Exports
            elif action == "list_account_exports":
                result = await self._handle_list_account_exports(config, credentials)
            elif action == "create_account_export":
                result = await self._handle_create_account_export(config, credentials)
            elif action == "fetch_account_export":
                result = await self._handle_get_account_export(config, credentials)

            # Automation Archive
            elif action == "archive_automation_workflow":
                result = await self._handle_archive_automation(config, credentials)

            # Campaign Report Granular Operations
            elif action == "fetch_campaign_click_details_for_member":
                result = await self._handle_get_campaign_click_detail_member(
                    config, credentials
                )
            elif action == "fetch_campaign_recipient_info":
                result = await self._handle_get_campaign_sent_to_member(
                    config, credentials
                )
            elif action == "fetch_campaign_unsubscribed_member":
                result = await self._handle_get_campaign_unsubscribed_member(
                    config, credentials
                )

            # Conversation Message Operations
            elif action == "update_conversation_message":
                result = await self._handle_update_conversation_message(
                    config, credentials
                )
            elif action == "delete_conversation_message":
                result = await self._handle_delete_conversation_message(
                    config, credentials
                )

            # E-commerce Product Variant Delete
            elif action == "delete_product_variant":
                result = await self._handle_delete_ecommerce_product_variant(
                    config, credentials
                )

            # Automation Email Queue POST
            elif action == "add_member_to_automation_queue":
                result = await self._handle_add_automation_queue_member(
                    config, credentials
                )

            # Mandrill/Transactional API Operations (95 total)
            # Allowlists (3)
            elif action == "add_email_to_allowlist":
                result = await self._handle_mandrill_allowlists_add(config, credentials)
            elif action == "list_allowlisted_emails":
                result = await self._handle_mandrill_allowlists_list(
                    config, credentials
                )
            elif action == "remove_email_from_allowlist":
                result = await self._handle_mandrill_allowlists_delete(
                    config, credentials
                )
            # Exports (6)
            elif action == "fetch_export_info":
                result = await self._handle_mandrill_exports_info(config, credentials)
            elif action == "list_exports":
                result = await self._handle_mandrill_exports_list(config, credentials)
            elif action == "export_denylist":
                result = await self._handle_mandrill_exports_rejects(
                    config, credentials
                )
            elif action == "export_whitelist":
                result = await self._handle_mandrill_exports_whitelist(
                    config, credentials
                )
            elif action == "export_allowlist":
                result = await self._handle_mandrill_exports_allowlist(
                    config, credentials
                )
            elif action == "export_activity_history":
                result = await self._handle_mandrill_exports_activity(
                    config, credentials
                )
            # Inbound (9)
            elif action == "list_inbound_domains":
                result = await self._handle_mandrill_inbound_domains(
                    config, credentials
                )
            elif action == "add_inbound_domain":
                result = await self._handle_mandrill_inbound_add_domain(
                    config, credentials
                )
            elif action == "verify_inbound_domain_settings":
                result = await self._handle_mandrill_inbound_check_domain(
                    config, credentials
                )
            elif action == "delete_inbound_domain":
                result = await self._handle_mandrill_inbound_delete_domain(
                    config, credentials
                )
            elif action == "list_mailbox_routes":
                result = await self._handle_mandrill_inbound_routes(config, credentials)
            elif action == "add_mailbox_route":
                result = await self._handle_mandrill_inbound_add_route(
                    config, credentials
                )
            elif action == "update_mailbox_route":
                result = await self._handle_mandrill_inbound_update_route(
                    config, credentials
                )
            elif action == "delete_mailbox_route":
                result = await self._handle_mandrill_inbound_delete_route(
                    config, credentials
                )
            elif action == "send_raw_mime_message":
                result = await self._handle_mandrill_inbound_send_raw(
                    config, credentials
                )
            # IPs (13)
            elif action == "list_ip_addresses":
                result = await self._handle_mandrill_ips_list(config, credentials)
            elif action == "fetch_ip_info":
                result = await self._handle_mandrill_ips_info(config, credentials)
            elif action == "request_additional_ip":
                result = await self._handle_mandrill_ips_provision(config, credentials)
            elif action == "start_ip_warmup":
                result = await self._handle_mandrill_ips_start_warmup(
                    config, credentials
                )
            elif action == "cancel_ip_warmup":
                result = await self._handle_mandrill_ips_cancel_warmup(
                    config, credentials
                )
            elif action == "move_ip_to_pool":
                result = await self._handle_mandrill_ips_set_pool(config, credentials)
            elif action == "delete_ip_address":
                result = await self._handle_mandrill_ips_delete(config, credentials)
            elif action == "list_ip_pools":
                result = await self._handle_mandrill_ips_list_pools(config, credentials)
            elif action == "fetch_ip_pool_info":
                result = await self._handle_mandrill_ips_pool_info(config, credentials)
            elif action == "create_ip_pool":
                result = await self._handle_mandrill_ips_create_pool(
                    config, credentials
                )
            elif action == "delete_ip_pool":
                result = await self._handle_mandrill_ips_delete_pool(
                    config, credentials
                )
            elif action == "test_ip_custom_dns":
                result = await self._handle_mandrill_ips_check_custom_dns(
                    config, credentials
                )
            elif action == "set_ip_custom_dns":
                result = await self._handle_mandrill_ips_set_custom_dns(
                    config, credentials
                )
            # Messages (12)
            elif action == "send_sms_message":
                result = await self._handle_mandrill_messages_send_sms(
                    config, credentials
                )
            elif action == "send_message":
                result = await self._handle_mandrill_messages_send(config, credentials)
            elif action == "send_templated_message":
                result = await self._handle_mandrill_messages_send_template(
                    config, credentials
                )
            elif action == "search_messages_by_date":
                result = await self._handle_mandrill_messages_search(
                    config, credentials
                )
            elif action == "search_messages_by_hour":
                result = await self._handle_mandrill_messages_search_time_series(
                    config, credentials
                )
            elif action == "fetch_message_info":
                result = await self._handle_mandrill_messages_info(config, credentials)
            elif action == "fetch_message_content":
                result = await self._handle_mandrill_messages_content(
                    config, credentials
                )
            elif action == "parse_mime_message":
                result = await self._handle_mandrill_messages_parse(config, credentials)
            elif action == "send_raw_mime_email":
                result = await self._handle_mandrill_messages_send_raw(
                    config, credentials
                )
            elif action == "list_scheduled_emails":
                result = await self._handle_mandrill_messages_list_scheduled(
                    config, credentials
                )
            elif action == "cancel_scheduled_email":
                result = await self._handle_mandrill_messages_cancel_scheduled(
                    config, credentials
                )
            elif action == "reschedule_scheduled_email":
                result = await self._handle_mandrill_messages_reschedule(
                    config, credentials
                )
            # Metadata (4)
            elif action == "list_metadata_fields":
                result = await self._handle_mandrill_metadata_list(config, credentials)
            elif action == "create_metadata_field":
                result = await self._handle_mandrill_metadata_add(config, credentials)
            elif action == "update_metadata_field":
                result = await self._handle_mandrill_metadata_update(
                    config, credentials
                )
            elif action == "delete_metadata_field":
                result = await self._handle_mandrill_metadata_delete(
                    config, credentials
                )
            # Rejects (3)
            elif action == "add_email_to_denylist":
                result = await self._handle_mandrill_rejects_add(config, credentials)
            elif action == "list_denylisted_emails":
                result = await self._handle_mandrill_rejects_list(config, credentials)
            elif action == "remove_email_from_denylist":
                result = await self._handle_mandrill_rejects_delete(config, credentials)
            # Senders (7)
            elif action == "list_account_senders":
                result = await self._handle_mandrill_senders_list(config, credentials)
            elif action == "list_sender_domains":
                result = await self._handle_mandrill_senders_domains(
                    config, credentials
                )
            elif action == "add_sender_domain":
                result = await self._handle_mandrill_senders_add_domain(
                    config, credentials
                )
            elif action == "verify_sender_domain_settings":
                result = await self._handle_mandrill_senders_check_domain(
                    config, credentials
                )
            elif action == "verify_sender_domain_for_sending":
                result = await self._handle_mandrill_senders_verify_domain(
                    config, credentials
                )
            elif action == "fetch_sender_info":
                result = await self._handle_mandrill_senders_info(config, credentials)
            elif action == "fetch_sender_history":
                result = await self._handle_mandrill_senders_time_series(
                    config, credentials
                )
            # Subaccounts (7)
            elif action == "list_subaccounts":
                result = await self._handle_mandrill_subaccounts_list(
                    config, credentials
                )
            elif action == "create_subaccount":
                result = await self._handle_mandrill_subaccounts_add(
                    config, credentials
                )
            elif action == "fetch_subaccount_info":
                result = await self._handle_mandrill_subaccounts_info(
                    config, credentials
                )
            elif action == "update_subaccount":
                result = await self._handle_mandrill_subaccounts_update(
                    config, credentials
                )
            elif action == "delete_subaccount":
                result = await self._handle_mandrill_subaccounts_delete(
                    config, credentials
                )
            elif action == "pause_subaccount":
                result = await self._handle_mandrill_subaccounts_pause(
                    config, credentials
                )
            elif action == "resume_subaccount":
                result = await self._handle_mandrill_subaccounts_resume(
                    config, credentials
                )
            # Tags (5)
            elif action == "list_tags":
                result = await self._handle_mandrill_tags_list(config, credentials)
            elif action == "delete_tag":
                result = await self._handle_mandrill_tags_delete(config, credentials)
            elif action == "fetch_tag_info":
                result = await self._handle_mandrill_tags_info(config, credentials)
            elif action == "fetch_tag_history":
                result = await self._handle_mandrill_tags_time_series(
                    config, credentials
                )
            elif action == "fetch_all_tags_history":
                result = await self._handle_mandrill_tags_all_time_series(
                    config, credentials
                )
            # Templates (8)
            elif action == "create_mandrill_template":
                result = await self._handle_mandrill_templates_add(config, credentials)
            elif action == "fetch_mandrill_template_info":
                result = await self._handle_mandrill_templates_info(config, credentials)
            elif action == "update_mandrill_template":
                result = await self._handle_mandrill_templates_update(
                    config, credentials
                )
            elif action == "publish_mandrill_template":
                result = await self._handle_mandrill_templates_publish(
                    config, credentials
                )
            elif action == "delete_mandrill_template":
                result = await self._handle_mandrill_templates_delete(
                    config, credentials
                )
            elif action == "list_mandrill_templates":
                result = await self._handle_mandrill_templates_list(config, credentials)
            elif action == "fetch_mandrill_template_history":
                result = await self._handle_mandrill_templates_time_series(
                    config, credentials
                )
            elif action == "render_html_template":
                result = await self._handle_mandrill_templates_render(
                    config, credentials
                )
            # URLs (6)
            elif action == "list_most_clicked_urls":
                result = await self._handle_mandrill_urls_list(config, credentials)
            elif action == "search_most_clicked_urls":
                result = await self._handle_mandrill_urls_search(config, credentials)
            elif action == "fetch_url_history":
                result = await self._handle_mandrill_urls_time_series(
                    config, credentials
                )
            elif action == "list_tracking_domains":
                result = await self._handle_mandrill_urls_tracking_domains(
                    config, credentials
                )
            elif action == "add_tracking_domain":
                result = await self._handle_mandrill_urls_add_tracking_domain(
                    config, credentials
                )
            elif action == "verify_tracking_domain_cname":
                result = await self._handle_mandrill_urls_check_tracking_domain(
                    config, credentials
                )
            # Users (4)
            elif action == "fetch_user_info":
                result = await self._handle_mandrill_users_info(config, credentials)
            elif action == "ping_mandrill_api":
                result = await self._handle_mandrill_users_ping(config, credentials)
            elif action == "ping_mandrill_api_v2":
                result = await self._handle_mandrill_users_ping2(config, credentials)
            elif action == "list_api_account_senders":
                result = await self._handle_mandrill_users_senders(config, credentials)
            # Webhooks (5)
            elif action == "list_mandrill_webhooks":
                result = await self._handle_mandrill_webhooks_list(config, credentials)
            elif action == "create_mandrill_webhook":
                result = await self._handle_mandrill_webhooks_add(config, credentials)
            elif action == "fetch_mandrill_webhook_info":
                result = await self._handle_mandrill_webhooks_info(config, credentials)
            elif action == "update_mandrill_webhook":
                result = await self._handle_mandrill_webhooks_update(
                    config, credentials
                )
            elif action == "delete_mandrill_webhook":
                result = await self._handle_mandrill_webhooks_delete(
                    config, credentials
                )
            # Whitelists (3)
            elif action == "add_email_to_whitelist":
                result = await self._handle_mandrill_whitelists_add(config, credentials)
            elif action == "list_whitelisted_emails":
                result = await self._handle_mandrill_whitelists_list(
                    config, credentials
                )
            elif action == "remove_email_from_whitelist":
                result = await self._handle_mandrill_whitelists_delete(
                    config, credentials
                )

            else:
                return {
                    "status": "error",
                    "action": action,
                    "error": f"Action '{action}' not yet implemented",
                    "timing_ms": {"total": int((time.time() - start_time) * 1000)},
                }

            # Add timing to successful result
            result["timing_ms"] = {"total": int((time.time() - start_time) * 1000)}
            return result

        except httpx.HTTPStatusError as e:
            error_detail = e.response.text
            return {
                "status": "error",
                "action": action,
                "error": f"Mailchimp API error: {str(e)}",
                "error_detail": error_detail,
                "status_code": e.response.status_code,
                "timing_ms": {"total": int((time.time() - start_time) * 1000)},
            }
        except Exception as e:
            logger.exception(f"Error in Mailchimp node action '{action}'")
            return {
                "status": "error",
                "action": action,
                "error": str(e),
                "error_type": type(e).__name__,
                "timing_ms": {"total": int((time.time() - start_time) * 1000)},
            }

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        credentials: MailchimpCredential,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        action_name: str = "request",
    ) -> Dict[str, Any]:
        """Make an authenticated request to the Mailchimp API."""
        request_start = time.time()

        base_url = self._get_api_base_url(credentials)
        headers = self._get_auth_headers(credentials)
        url = f"{base_url}{endpoint}"

        async with guarded_async_client(timeout=120.0) as client:
            response = await client.request(
                method=method, url=url, headers=headers, params=params, json=json_body
            )
            response.raise_for_status()

            request_time = int((time.time() - request_start) * 1000)

            # Handle empty responses (204 No Content)
            if response.status_code == 204:
                return {
                    "status": "success",
                    "action": action_name,
                    "message": "Operation completed successfully",
                    "timing_ms": {"api_request": request_time},
                }

            # Parse JSON response
            data = response.json()
            return {
                "status": "success",
                "action": action_name,
                "data": data,
                "timing_ms": {"api_request": request_time},
            }

    async def _make_mandrill_request(
        self,
        endpoint: str,
        config: BaseModel,
        credentials: MailchimpCredential,
        action_name: str,
    ) -> Dict[str, Any]:
        """Make an authenticated request to the Mandrill API."""
        if not isinstance(credentials, MailchimpMandrillCredential):
            raise ValueError("Mandrill operations require MailchimpMandrillCredential")

        request_start = time.time()
        base_url = "https://mandrillapp.com/api/1.0"
        url = f"{base_url}{endpoint}"

        # Build request body - include API key and all config fields
        body = {"key": credentials.mandrill_api_key}
        # Add all fields from config except 'action'
        for field_name, field_value in config.model_dump(exclude={"action"}).items():
            if field_value is not None:
                body[field_name] = field_value

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(url, json=body)
            response.raise_for_status()

            request_time = int((time.time() - request_start) * 1000)
            data = response.json()

            return {
                "status": "success",
                "action": action_name,
                "data": data,
                "timing_ms": {"api_request": request_time},
            }

    # ========================================================================
    # Handler Methods - Lists/Audiences
    # ========================================================================

    async def _handle_list_lists(
        self, config: MailchimpListListsConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get all lists/audiences."""
        params = {"count": config.count, "offset": config.offset}
        if config.sort_field:
            params["sort_field"] = config.sort_field
        if config.sort_dir:
            params["sort_dir"] = config.sort_dir

        result = await self._make_request(
            "GET", "lists", credentials, params=params, action_name="list_all_lists"
        )

        # Format for table display
        if result["status"] == "success" and "lists" in result["data"]:
            lists_data = result["data"]["lists"]
            formatted_lists = [
                {
                    "id": lst.get("id"),
                    "name": lst.get("name"),
                    "members": lst.get("stats", {}).get("member_count", 0),
                    "created": lst.get("date_created"),
                }
                for lst in lists_data
            ]
            result["data"]["lists_formatted"] = formatted_lists

        return result

    async def _handle_get_list(
        self, config: MailchimpGetListConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get a specific list."""
        endpoint = f"lists/{config.list_id}"
        params = {}
        if config.include_total_contacts:
            params["include_total_contacts"] = "true"

        return await self._make_request(
            "GET", endpoint, credentials, params=params, action_name="fetch_list"
        )

    async def _handle_create_list(
        self, config: MailchimpCreateListConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Create a new list."""
        body = {
            "name": config.name,
            "contact": {
                "company": config.company,
                "address1": config.address1,
                "city": config.city,
                "state": config.state,
                "zip": config.zip,
                "country": config.country,
            },
            "permission_reminder": config.permission_reminder,
            "campaign_defaults": {
                "from_name": config.from_name,
                "from_email": config.from_email,
                "subject": config.subject,
                "language": config.language,
            },
            "email_type_option": config.email_type_option,
            "double_optin": config.double_optin,
        }

        return await self._make_request(
            "POST", "lists", credentials, json_body=body, action_name="create_list"
        )

    async def _handle_update_list(
        self, config: MailchimpUpdateListConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Update a list."""
        endpoint = f"lists/{config.list_id}"
        body = {}

        if config.name:
            body["name"] = config.name
        if config.permission_reminder:
            body["permission_reminder"] = config.permission_reminder
        if config.from_name or config.from_email or config.subject:
            body["campaign_defaults"] = {}
            if config.from_name:
                body["campaign_defaults"]["from_name"] = config.from_name
            if config.from_email:
                body["campaign_defaults"]["from_email"] = config.from_email
            if config.subject:
                body["campaign_defaults"]["subject"] = config.subject

        return await self._make_request(
            "PATCH", endpoint, credentials, json_body=body, action_name="update_list_settings"
        )

    async def _handle_delete_list(
        self, config: MailchimpDeleteListConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Delete a list."""
        endpoint = f"lists/{config.list_id}"
        return await self._make_request(
            "DELETE", endpoint, credentials, action_name="archive_list"
        )

    # ========================================================================
    # Handler Methods - List Members
    # ========================================================================

    async def _handle_list_members(
        self, config: MailchimpListMembersConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get members in a list."""
        endpoint = f"lists/{config.list_id}/members"
        params = {"count": config.count, "offset": config.offset}
        if config.status:
            params["status"] = config.status

        result = await self._make_request(
            "GET", endpoint, credentials, params=params, action_name="list_list_members"
        )

        # Format for table display
        if result["status"] == "success" and "members" in result["data"]:
            members_data = result["data"]["members"]
            formatted_members = [
                {
                    "email": member.get("email_address"),
                    "status": member.get("status"),
                    "name": f"{member.get('merge_fields', {}).get('FNAME', '')} {member.get('merge_fields', {}).get('LNAME', '')}".strip()
                    or "N/A",
                    "subscribed": member.get("timestamp_opt"),
                }
                for member in members_data
            ]
            result["data"]["members_formatted"] = formatted_members

        return result

    async def _handle_get_member(
        self, config: MailchimpGetMemberConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get a specific member."""
        subscriber_hash = get_subscriber_hash(config.email_address)
        endpoint = f"lists/{config.list_id}/members/{subscriber_hash}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_list_member"
        )

    async def _handle_add_member(
        self, config: MailchimpAddMemberConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Add a new member to a list."""
        endpoint = f"lists/{config.list_id}/members"
        body = {"email_address": config.email_address, "status": config.status}

        if config.merge_fields:
            body["merge_fields"] = config.merge_fields
        if config.interests:
            body["interests"] = config.interests
        if config.language:
            body["language"] = config.language
        if config.vip:
            body["vip"] = config.vip

        return await self._make_request(
            "POST", endpoint, credentials, json_body=body, action_name="create_list_member"
        )

    async def _handle_update_member(
        self, config: MailchimpUpdateMemberConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Update a member."""
        subscriber_hash = get_subscriber_hash(config.email_address)
        endpoint = f"lists/{config.list_id}/members/{subscriber_hash}"
        body = {}

        if config.new_email_address:
            body["email_address"] = config.new_email_address
        if config.status:
            body["status"] = config.status
        if config.merge_fields:
            body["merge_fields"] = config.merge_fields
        if config.interests:
            body["interests"] = config.interests
        if config.language:
            body["language"] = config.language
        if config.vip is not None:
            body["vip"] = config.vip

        return await self._make_request(
            "PATCH", endpoint, credentials, json_body=body, action_name="update_list_member"
        )

    async def _handle_add_or_update_member(
        self, config: MailchimpAddOrUpdateMemberConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Add or update a member (upsert)."""
        subscriber_hash = get_subscriber_hash(config.email_address)
        endpoint = f"lists/{config.list_id}/members/{subscriber_hash}"
        body = {
            "email_address": config.email_address,
            "status_if_new": config.status_if_new,
        }

        if config.merge_fields:
            body["merge_fields"] = config.merge_fields
        if config.interests:
            body["interests"] = config.interests
        if config.language:
            body["language"] = config.language
        if config.vip:
            body["vip"] = config.vip

        return await self._make_request(
            "PUT",
            endpoint,
            credentials,
            json_body=body,
            action_name="upsert_list_member",
        )

    async def _handle_delete_member(
        self, config: MailchimpDeleteMemberConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Archive a member."""
        subscriber_hash = get_subscriber_hash(config.email_address)
        endpoint = f"lists/{config.list_id}/members/{subscriber_hash}"
        return await self._make_request(
            "DELETE", endpoint, credentials, action_name="archive_list_member"
        )

    async def _handle_permanently_delete_member(
        self,
        config: MailchimpPermanentlyDeleteMemberConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Permanently delete a member."""
        subscriber_hash = get_subscriber_hash(config.email_address)
        endpoint = (
            f"lists/{config.list_id}/members/{subscriber_hash}/actions/delete-permanent"
        )
        return await self._make_request(
            "POST", endpoint, credentials, action_name="permanently_delete_list_member"
        )

    # ========================================================================
    # Handler Methods - Campaigns
    # ========================================================================

    async def _handle_list_campaigns(
        self, config: MailchimpListCampaignsConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get all campaigns."""
        params = {"count": config.count, "offset": config.offset}
        if config.type:
            params["type"] = config.type
        if config.status:
            params["status"] = config.status
        if config.list_id:
            params["list_id"] = config.list_id

        result = await self._make_request(
            "GET", "campaigns", credentials, params=params, action_name="list_campaigns"
        )

        # Format for table display
        if result["status"] == "success" and "campaigns" in result["data"]:
            campaigns_data = result["data"]["campaigns"]
            formatted_campaigns = [
                {
                    "id": campaign.get("id"),
                    "type": campaign.get("type"),
                    "status": campaign.get("status"),
                    "subject": campaign.get("settings", {}).get("subject_line", "N/A"),
                    "emails_sent": campaign.get("emails_sent", 0),
                    "created": campaign.get("create_time"),
                }
                for campaign in campaigns_data
            ]
            result["data"]["campaigns_formatted"] = formatted_campaigns

        return result

    async def _handle_get_campaign(
        self, config: MailchimpGetCampaignConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get a specific campaign."""
        endpoint = f"campaigns/{config.campaign_id}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_campaign"
        )

    async def _handle_create_campaign(
        self, config: MailchimpCreateCampaignConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Create a new campaign."""
        body = {
            "type": config.type,
            "recipients": {"list_id": config.list_id},
            "settings": {
                "subject_line": config.subject_line,
                "from_name": config.from_name,
                "reply_to": config.reply_to,
            },
        }

        if config.title:
            body["settings"]["title"] = config.title
        if config.preview_text:
            body["settings"]["preview_text"] = config.preview_text

        return await self._make_request(
            "POST",
            "campaigns",
            credentials,
            json_body=body,
            action_name="create_campaign",
        )

    async def _handle_update_campaign(
        self, config: MailchimpUpdateCampaignConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Update a campaign."""
        endpoint = f"campaigns/{config.campaign_id}"
        body = {"settings": {}}

        if config.subject_line:
            body["settings"]["subject_line"] = config.subject_line
        if config.from_name:
            body["settings"]["from_name"] = config.from_name
        if config.reply_to:
            body["settings"]["reply_to"] = config.reply_to
        if config.title:
            body["settings"]["title"] = config.title
        if config.preview_text:
            body["settings"]["preview_text"] = config.preview_text

        return await self._make_request(
            "PATCH",
            endpoint,
            credentials,
            json_body=body,
            action_name="update_campaign_settings",
        )

    async def _handle_delete_campaign(
        self, config: MailchimpDeleteCampaignConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Delete a campaign."""
        endpoint = f"campaigns/{config.campaign_id}"
        return await self._make_request(
            "DELETE", endpoint, credentials, action_name="delete_campaign"
        )

    async def _handle_send_campaign(
        self, config: MailchimpSendCampaignConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Send a campaign."""
        endpoint = f"campaigns/{config.campaign_id}/actions/send"
        return await self._make_request(
            "POST", endpoint, credentials, action_name="send_campaign_immediately"
        )

    async def _handle_schedule_campaign(
        self, config: MailchimpScheduleCampaignConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Schedule a campaign."""
        endpoint = f"campaigns/{config.campaign_id}/actions/schedule"
        body = {"schedule_time": config.schedule_time}
        return await self._make_request(
            "POST",
            endpoint,
            credentials,
            json_body=body,
            action_name="schedule_campaign_for_delivery",
        )

    async def _handle_unschedule_campaign(
        self,
        config: MailchimpUnscheduleCampaignConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Unschedule a campaign."""
        endpoint = f"campaigns/{config.campaign_id}/actions/unschedule"
        return await self._make_request(
            "POST", endpoint, credentials, action_name="unschedule_campaign"
        )

    async def _handle_send_test_email(
        self, config: MailchimpSendTestEmailConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Send a test email."""
        endpoint = f"campaigns/{config.campaign_id}/actions/test"
        body = {"test_emails": config.test_emails, "send_type": config.send_type}
        return await self._make_request(
            "POST", endpoint, credentials, json_body=body, action_name="send_campaign_test_email"
        )

    async def _handle_replicate_campaign(
        self, config: MailchimpReplicateCampaignConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Replicate a campaign."""
        endpoint = f"campaigns/{config.campaign_id}/actions/replicate"
        return await self._make_request(
            "POST", endpoint, credentials, action_name="duplicate_campaign"
        )

    # ========================================================================
    # Handler Methods - Campaign Content
    # ========================================================================

    async def _handle_get_campaign_content(
        self,
        config: MailchimpGetCampaignContentConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get campaign content."""
        endpoint = f"campaigns/{config.campaign_id}/content"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_campaign_content"
        )

    async def _handle_set_campaign_content(
        self,
        config: MailchimpSetCampaignContentConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Set campaign content."""
        endpoint = f"campaigns/{config.campaign_id}/content"
        body = {}

        if config.html:
            body["html"] = config.html
        if config.plain_text:
            body["plain_text"] = config.plain_text
        if config.template_id:
            body["template"] = {"id": config.template_id}

        return await self._make_request(
            "PUT",
            endpoint,
            credentials,
            json_body=body,
            action_name="update_campaign_content",
        )

    # ========================================================================
    # Handler Methods - Automations
    # ========================================================================

    async def _handle_list_automations(
        self, config: MailchimpListAutomationsConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get all automations."""
        params = {"count": config.count, "offset": config.offset}
        if config.status:
            params["status"] = config.status

        result = await self._make_request(
            "GET",
            "automations",
            credentials,
            params=params,
            action_name="list_automation_workflows",
        )

        # Format for table display
        if result["status"] == "success" and "automations" in result["data"]:
            automations_data = result["data"]["automations"]
            formatted_automations = [
                {
                    "id": automation.get("id"),
                    "status": automation.get("status"),
                    "title": automation.get("settings", {}).get("title", "N/A"),
                    "emails_sent": automation.get("emails_sent", 0),
                    "created": automation.get("create_time"),
                }
                for automation in automations_data
            ]
            result["data"]["automations_formatted"] = formatted_automations

        return result

    async def _handle_get_automation(
        self, config: MailchimpGetAutomationConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get a specific automation."""
        endpoint = f"automations/{config.workflow_id}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_automation_workflow"
        )

    async def _handle_pause_automation(
        self, config: MailchimpPauseAutomationConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Pause an automation."""
        endpoint = f"automations/{config.workflow_id}/actions/pause-all-emails"
        return await self._make_request(
            "POST", endpoint, credentials, action_name="pause_automation_workflow"
        )

    async def _handle_start_automation(
        self, config: MailchimpStartAutomationConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Start an automation."""
        endpoint = f"automations/{config.workflow_id}/actions/start-all-emails"
        return await self._make_request(
            "POST", endpoint, credentials, action_name="start_automation_workflow"
        )

    # ========================================================================
    # Handler Methods - Tags
    # ========================================================================

    async def _handle_get_member_tags(
        self, config: MailchimpGetMemberTagsConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get tags assigned to a list member."""
        subscriber_hash = get_subscriber_hash(config.email_address)
        endpoint = f"lists/{config.list_id}/members/{subscriber_hash}/tags"
        params = {"count": config.count, "offset": config.offset}

        result = await self._make_request(
            "GET", endpoint, credentials, params=params, action_name="list_member_tags"
        )

        # Format for table display
        if result["status"] == "success" and "tags" in result["data"]:
            tags_data = result["data"]["tags"]
            formatted_tags = [
                {
                    "id": tag.get("id"),
                    "name": tag.get("name"),
                    "date_added": tag.get("date_added"),
                }
                for tag in tags_data
            ]
            result["data"]["tags_formatted"] = formatted_tags

        return result

    async def _handle_add_or_remove_member_tags(
        self,
        config: MailchimpAddOrRemoveMemberTagsConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Add or remove tags from a list member."""
        subscriber_hash = get_subscriber_hash(config.email_address)
        endpoint = f"lists/{config.list_id}/members/{subscriber_hash}/tags"
        body = {"tags": config.tags}

        return await self._make_request(
            "POST",
            endpoint,
            credentials,
            json_body=body,
            action_name="update_member_tags",
        )

    async def _handle_search_tags(
        self, config: MailchimpSearchTagsConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Search for tags by name."""
        endpoint = f"lists/{config.list_id}/tag-search"
        params = {"name": config.name}

        result = await self._make_request(
            "GET", endpoint, credentials, params=params, action_name="search_list_tags"
        )

        # Format for table display
        if result["status"] == "success" and "tags" in result["data"]:
            tags_data = result["data"]["tags"]
            formatted_tags = [
                {
                    "id": tag.get("id"),
                    "name": tag.get("name"),
                    "subscriber_count": tag.get("member_count", 0),
                }
                for tag in tags_data
            ]
            result["data"]["tags_formatted"] = formatted_tags

        return result

    # ========================================================================
    # Handler Methods - Segments
    # ========================================================================

    async def _handle_list_segments(
        self, config: MailchimpListSegmentsConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get all segments in a list."""
        endpoint = f"lists/{config.list_id}/segments"
        params = {"count": config.count, "offset": config.offset}
        if config.type:
            params["type"] = config.type

        result = await self._make_request(
            "GET", endpoint, credentials, params=params, action_name="list_list_segments"
        )

        # Format for table display
        if result["status"] == "success" and "segments" in result["data"]:
            segments_data = result["data"]["segments"]
            formatted_segments = [
                {
                    "id": segment.get("id"),
                    "name": segment.get("name"),
                    "type": segment.get("type"),
                    "member_count": segment.get("member_count", 0),
                    "created": segment.get("created_at"),
                }
                for segment in segments_data
            ]
            result["data"]["segments_formatted"] = formatted_segments

        return result

    async def _handle_get_segment(
        self, config: MailchimpGetSegmentConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get information about a specific segment."""
        endpoint = f"lists/{config.list_id}/segments/{config.segment_id}"
        params = {}
        if config.include_cleaned:
            params["include_cleaned"] = "true"
        if config.include_transactional:
            params["include_transactional"] = "true"
        if config.include_unsubscribed:
            params["include_unsubscribed"] = "true"

        return await self._make_request(
            "GET",
            endpoint,
            credentials,
            params=params if params else None,
            action_name="fetch_list_segment",
        )

    async def _handle_create_segment(
        self, config: MailchimpCreateSegmentConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Create a new segment."""
        endpoint = f"lists/{config.list_id}/segments"
        body = {"name": config.name}

        if config.static_segment:
            body["static_segment"] = config.static_segment
        if config.options:
            body["options"] = config.options

        return await self._make_request(
            "POST", endpoint, credentials, json_body=body, action_name="create_list_segment"
        )

    async def _handle_update_segment(
        self, config: MailchimpUpdateSegmentConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Update a segment."""
        endpoint = f"lists/{config.list_id}/segments/{config.segment_id}"
        body = {}

        if config.name:
            body["name"] = config.name
        if config.static_segment:
            body["static_segment"] = config.static_segment

        return await self._make_request(
            "PATCH", endpoint, credentials, json_body=body, action_name="update_list_segment"
        )

    async def _handle_delete_segment(
        self, config: MailchimpDeleteSegmentConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Delete a segment."""
        endpoint = f"lists/{config.list_id}/segments/{config.segment_id}"
        return await self._make_request(
            "DELETE", endpoint, credentials, action_name="delete_list_segment"
        )

    async def _handle_batch_add_remove_segment_members(
        self,
        config: MailchimpBatchAddRemoveSegmentMembersConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Batch add or remove members from a static segment."""
        endpoint = f"lists/{config.list_id}/segments/{config.segment_id}"
        body = {}

        if config.members_to_add:
            body["members_to_add"] = config.members_to_add
        if config.members_to_remove:
            body["members_to_remove"] = config.members_to_remove

        return await self._make_request(
            "POST",
            endpoint,
            credentials,
            json_body=body,
            action_name="update_segment_members_batch",
        )

    # ========================================================================
    # Handler Methods - Merge Fields
    # ========================================================================

    async def _handle_list_merge_fields(
        self, config: MailchimpListMergeFieldsConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get all merge fields for a list."""
        endpoint = f"lists/{config.list_id}/merge-fields"
        params = {"count": config.count, "offset": config.offset}
        if config.type:
            params["type"] = config.type
        if config.required is not None:
            params["required"] = str(config.required).lower()

        result = await self._make_request(
            "GET", endpoint, credentials, params=params, action_name="list_merge_fields"
        )

        # Format for table display
        if result["status"] == "success" and "merge_fields" in result["data"]:
            fields_data = result["data"]["merge_fields"]
            formatted_fields = [
                {
                    "merge_id": field.get("merge_id"),
                    "tag": field.get("tag"),
                    "name": field.get("name"),
                    "type": field.get("type"),
                    "required": field.get("required", False),
                }
                for field in fields_data
            ]
            result["data"]["merge_fields_formatted"] = formatted_fields

        return result

    async def _handle_get_merge_field(
        self, config: MailchimpGetMergeFieldConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get information about a specific merge field."""
        endpoint = f"lists/{config.list_id}/merge-fields/{config.merge_id}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_merge_field"
        )

    async def _handle_add_merge_field(
        self, config: MailchimpAddMergeFieldConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Add a new merge field to a list."""
        endpoint = f"lists/{config.list_id}/merge-fields"
        body = {
            "name": config.name,
            "type": config.type,
            "required": config.required,
            "public": config.public,
        }

        if config.tag:
            body["tag"] = config.tag
        if config.default_value:
            body["default_value"] = config.default_value
        if config.display_order is not None:
            body["display_order"] = config.display_order
        if config.options:
            body["options"] = config.options
        if config.helptext:
            body["helptext"] = config.helptext

        return await self._make_request(
            "POST", endpoint, credentials, json_body=body, action_name="create_merge_field"
        )

    async def _handle_update_merge_field(
        self, config: MailchimpUpdateMergeFieldConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Update a merge field."""
        endpoint = f"lists/{config.list_id}/merge-fields/{config.merge_id}"
        body = {}

        if config.name:
            body["name"] = config.name
        if config.tag:
            body["tag"] = config.tag
        if config.required is not None:
            body["required"] = config.required
        if config.default_value:
            body["default_value"] = config.default_value
        if config.public is not None:
            body["public"] = config.public
        if config.display_order is not None:
            body["display_order"] = config.display_order
        if config.options:
            body["options"] = config.options
        if config.helptext:
            body["helptext"] = config.helptext

        return await self._make_request(
            "PATCH",
            endpoint,
            credentials,
            json_body=body,
            action_name="update_merge_field",
        )

    async def _handle_delete_merge_field(
        self, config: MailchimpDeleteMergeFieldConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Delete a merge field."""
        endpoint = f"lists/{config.list_id}/merge-fields/{config.merge_id}"
        return await self._make_request(
            "DELETE", endpoint, credentials, action_name="delete_merge_field"
        )

    # ========================================================================
    # Handler Methods - Interest Categories
    # ========================================================================

    async def _handle_list_interest_categories(
        self,
        config: MailchimpListInterestCategoriesConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get all interest categories for a list."""
        endpoint = f"lists/{config.list_id}/interest-categories"
        params = {"count": config.count, "offset": config.offset}
        if config.type:
            params["type"] = config.type

        result = await self._make_request(
            "GET",
            endpoint,
            credentials,
            params=params,
            action_name="list_interest_categories",
        )

        # Format for table display
        if result["status"] == "success" and "categories" in result["data"]:
            categories_data = result["data"]["categories"]
            formatted_categories = [
                {
                    "id": category.get("id"),
                    "title": category.get("title"),
                    "type": category.get("type"),
                    "display_order": category.get("display_order", 0),
                }
                for category in categories_data
            ]
            result["data"]["categories_formatted"] = formatted_categories

        return result

    async def _handle_get_interest_category(
        self,
        config: MailchimpGetInterestCategoryConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get information about a specific interest category."""
        endpoint = (
            f"lists/{config.list_id}/interest-categories/{config.interest_category_id}"
        )
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_interest_category"
        )

    async def _handle_create_interest_category(
        self,
        config: MailchimpCreateInterestCategoryConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Create a new interest category."""
        endpoint = f"lists/{config.list_id}/interest-categories"
        body = {"title": config.title, "type": config.type}

        if config.display_order is not None:
            body["display_order"] = config.display_order

        return await self._make_request(
            "POST",
            endpoint,
            credentials,
            json_body=body,
            action_name="create_interest_category",
        )

    async def _handle_update_interest_category(
        self,
        config: MailchimpUpdateInterestCategoryConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Update an interest category."""
        endpoint = (
            f"lists/{config.list_id}/interest-categories/{config.interest_category_id}"
        )
        body = {}

        if config.title:
            body["title"] = config.title
        if config.type:
            body["type"] = config.type
        if config.display_order is not None:
            body["display_order"] = config.display_order

        return await self._make_request(
            "PATCH",
            endpoint,
            credentials,
            json_body=body,
            action_name="update_interest_category",
        )

    async def _handle_delete_interest_category(
        self,
        config: MailchimpDeleteInterestCategoryConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Delete an interest category."""
        endpoint = (
            f"lists/{config.list_id}/interest-categories/{config.interest_category_id}"
        )
        return await self._make_request(
            "DELETE", endpoint, credentials, action_name="delete_interest_category"
        )

    # ========================================================================
    # Handler Methods - Interests
    # ========================================================================

    async def _handle_list_interests(
        self, config: MailchimpListInterestsConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get all interests in an interest category."""
        endpoint = f"lists/{config.list_id}/interest-categories/{config.interest_category_id}/interests"
        params = {"count": config.count, "offset": config.offset}

        result = await self._make_request(
            "GET", endpoint, credentials, params=params, action_name="list_category_interests"
        )

        # Format for table display
        if result["status"] == "success" and "interests" in result["data"]:
            interests_data = result["data"]["interests"]
            formatted_interests = [
                {
                    "id": interest.get("id"),
                    "name": interest.get("name"),
                    "display_order": interest.get("display_order", 0),
                    "subscriber_count": interest.get("subscriber_count", 0),
                }
                for interest in interests_data
            ]
            result["data"]["interests_formatted"] = formatted_interests

        return result

    async def _handle_get_interest(
        self, config: MailchimpGetInterestConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get information about a specific interest."""
        endpoint = f"lists/{config.list_id}/interest-categories/{config.interest_category_id}/interests/{config.interest_id}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_category_interest"
        )

    async def _handle_create_interest(
        self, config: MailchimpCreateInterestConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Create a new interest in an interest category."""
        endpoint = f"lists/{config.list_id}/interest-categories/{config.interest_category_id}/interests"
        body = {"name": config.name}

        if config.display_order is not None:
            body["display_order"] = config.display_order

        return await self._make_request(
            "POST", endpoint, credentials, json_body=body, action_name="create_category_interest"
        )

    async def _handle_update_interest(
        self, config: MailchimpUpdateInterestConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Update an interest."""
        endpoint = f"lists/{config.list_id}/interest-categories/{config.interest_category_id}/interests/{config.interest_id}"
        body = {}

        if config.name:
            body["name"] = config.name
        if config.display_order is not None:
            body["display_order"] = config.display_order

        return await self._make_request(
            "PATCH",
            endpoint,
            credentials,
            json_body=body,
            action_name="update_category_interest",
        )

    async def _handle_delete_interest(
        self, config: MailchimpDeleteInterestConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Delete an interest."""
        endpoint = f"lists/{config.list_id}/interest-categories/{config.interest_category_id}/interests/{config.interest_id}"
        return await self._make_request(
            "DELETE", endpoint, credentials, action_name="delete_category_interest"
        )

    # ========================================================================
    # Handler Methods - Templates
    # ========================================================================

    async def _handle_list_templates(
        self, config: MailchimpListTemplatesConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get all templates."""
        params = {"count": config.count, "offset": config.offset}
        if config.type:
            params["type"] = config.type
        if config.category:
            params["category"] = config.category
        if config.folder_id:
            params["folder_id"] = config.folder_id
        if config.sort_field:
            params["sort_field"] = config.sort_field
        if config.sort_dir:
            params["sort_dir"] = config.sort_dir

        result = await self._make_request(
            "GET", "templates", credentials, params=params, action_name="list_email_templates"
        )

        # Format for table display
        if result["status"] == "success" and "templates" in result["data"]:
            templates_data = result["data"]["templates"]
            formatted_templates = [
                {
                    "id": template.get("id"),
                    "name": template.get("name"),
                    "type": template.get("type"),
                    "category": template.get("category", "N/A"),
                    "created": template.get("date_created"),
                }
                for template in templates_data
            ]
            result["data"]["templates_formatted"] = formatted_templates

        return result

    async def _handle_get_template(
        self, config: MailchimpGetTemplateConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get information about a specific template."""
        endpoint = f"templates/{config.template_id}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_email_template"
        )

    async def _handle_create_template(
        self, config: MailchimpCreateTemplateConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Create a new template."""
        body = {"name": config.name, "html": config.html}

        if config.folder_id:
            body["folder_id"] = config.folder_id

        return await self._make_request(
            "POST",
            "templates",
            credentials,
            json_body=body,
            action_name="create_email_template",
        )

    async def _handle_update_template(
        self, config: MailchimpUpdateTemplateConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Update a template."""
        endpoint = f"templates/{config.template_id}"
        body = {}

        if config.name:
            body["name"] = config.name
        if config.html:
            body["html"] = config.html
        if config.folder_id:
            body["folder_id"] = config.folder_id

        return await self._make_request(
            "PATCH",
            endpoint,
            credentials,
            json_body=body,
            action_name="update_email_template",
        )

    async def _handle_delete_template(
        self, config: MailchimpDeleteTemplateConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Delete a template."""
        endpoint = f"templates/{config.template_id}"
        return await self._make_request(
            "DELETE", endpoint, credentials, action_name="delete_email_template"
        )

    # ========================================================================
    # Handler Methods - Reports
    # ========================================================================

    async def _handle_list_campaign_reports(
        self,
        config: MailchimpListCampaignReportsConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get all campaign reports."""
        params = {"count": config.count, "offset": config.offset}
        if config.type:
            params["type"] = config.type
        if config.before_send_time:
            params["before_send_time"] = config.before_send_time
        if config.since_send_time:
            params["since_send_time"] = config.since_send_time

        result = await self._make_request(
            "GET",
            "reports",
            credentials,
            params=params,
            action_name="list_campaign_reports",
        )

        if result["status"] == "success" and "reports" in result["data"]:
            reports_data = result["data"]["reports"]
            formatted_reports = [
                {
                    "campaign_id": report.get("campaign_title"),
                    "subject": report.get("subject_line"),
                    "emails_sent": report.get("emails_sent", 0),
                    "open_rate": f"{report.get('open_rate', 0) * 100:.2f}%",
                    "click_rate": f"{report.get('click_rate', 0) * 100:.2f}%",
                    "send_time": report.get("send_time"),
                }
                for report in reports_data
            ]
            result["data"]["reports_formatted"] = formatted_reports

        return result

    async def _handle_get_campaign_report(
        self, config: MailchimpGetCampaignReportConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get report for a specific campaign."""
        endpoint = f"reports/{config.campaign_id}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_campaign_report"
        )

    async def _handle_get_campaign_email_activity(
        self,
        config: MailchimpGetCampaignEmailActivityConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get email activity for a campaign."""
        endpoint = f"reports/{config.campaign_id}/email-activity"
        params = {"count": config.count, "offset": config.offset}
        if config.since:
            params["since"] = config.since

        result = await self._make_request(
            "GET",
            endpoint,
            credentials,
            params=params,
            action_name="fetch_campaign_email_activity",
        )

        if result["status"] == "success" and "emails" in result["data"]:
            emails_data = result["data"]["emails"]
            formatted_emails = [
                {
                    "email_address": email.get("email_address"),
                    "action": email.get("action"),
                    "timestamp": email.get("timestamp"),
                    "ip": email.get("ip"),
                }
                for email in emails_data
            ]
            result["data"]["emails_formatted"] = formatted_emails

        return result

    async def _handle_get_campaign_abuse_reports(
        self,
        config: MailchimpGetCampaignAbuseReportsConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get abuse reports for a campaign."""
        endpoint = f"reports/{config.campaign_id}/abuse-reports"
        params = {"count": config.count, "offset": config.offset}

        result = await self._make_request(
            "GET",
            endpoint,
            credentials,
            params=params,
            action_name="list_campaign_abuse_reports",
        )

        if result["status"] == "success" and "abuse_reports" in result["data"]:
            reports_data = result["data"]["abuse_reports"]
            formatted_reports = [
                {
                    "id": report.get("id"),
                    "email_address": report.get("email_address"),
                    "date": report.get("date"),
                }
                for report in reports_data
            ]
            result["data"]["abuse_reports_formatted"] = formatted_reports

        return result

    async def _handle_get_campaign_abuse_report(
        self,
        config: MailchimpGetCampaignAbuseReportConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get a specific abuse report."""
        endpoint = f"reports/{config.campaign_id}/abuse-reports/{config.report_id}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_campaign_abuse_report"
        )

    async def _handle_get_campaign_click_details(
        self,
        config: MailchimpGetCampaignClickDetailsConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get click details for a campaign."""
        endpoint = f"reports/{config.campaign_id}/click-details"
        params = {"count": config.count, "offset": config.offset}

        result = await self._make_request(
            "GET",
            endpoint,
            credentials,
            params=params,
            action_name="fetch_campaign_click_details",
        )

        if result["status"] == "success" and "urls_clicked" in result["data"]:
            urls_data = result["data"]["urls_clicked"]
            formatted_urls = [
                {
                    "id": url.get("id"),
                    "url": url.get("url"),
                    "total_clicks": url.get("total_clicks", 0),
                    "unique_clicks": url.get("unique_clicks", 0),
                    "click_percentage": f"{url.get('click_percentage', 0):.2f}%",
                }
                for url in urls_data
            ]
            result["data"]["urls_clicked_formatted"] = formatted_urls

        return result

    async def _handle_get_campaign_click_details_for_link(
        self,
        config: MailchimpGetCampaignClickDetailsForLinkConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get click details for a specific link."""
        endpoint = f"reports/{config.campaign_id}/click-details/{config.link_id}"
        params = {"count": config.count, "offset": config.offset}
        return await self._make_request(
            "GET",
            endpoint,
            credentials,
            params=params,
            action_name="fetch_link_click_details",
        )

    async def _handle_get_campaign_click_detail_members(
        self,
        config: MailchimpGetCampaignClickDetailMembersConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get members who clicked a specific link."""
        endpoint = (
            f"reports/{config.campaign_id}/click-details/{config.link_id}/members"
        )
        params = {"count": config.count, "offset": config.offset}

        result = await self._make_request(
            "GET",
            endpoint,
            credentials,
            params=params,
            action_name="list_members_who_clicked_link",
        )

        if result["status"] == "success" and "members" in result["data"]:
            members_data = result["data"]["members"]
            formatted_members = [
                {
                    "email_address": member.get("email_address"),
                    "clicks": member.get("clicks", 0),
                    "last_click": member.get("last_click"),
                }
                for member in members_data
            ]
            result["data"]["members_formatted"] = formatted_members

        return result

    async def _handle_get_campaign_domain_performance(
        self,
        config: MailchimpGetCampaignDomainPerformanceConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get domain performance stats for a campaign."""
        endpoint = f"reports/{config.campaign_id}/domain-performance"
        result = await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_campaign_domain_performance"
        )

        if result["status"] == "success" and "domains" in result["data"]:
            domains_data = result["data"]["domains"]
            formatted_domains = [
                {
                    "domain": domain.get("domain"),
                    "emails_sent": domain.get("emails_sent", 0),
                    "bounces": domain.get("bounces", 0),
                    "opens": domain.get("opens", 0),
                    "clicks": domain.get("clicks", 0),
                }
                for domain in domains_data
            ]
            result["data"]["domains_formatted"] = formatted_domains

        return result

    async def _handle_get_campaign_eepurl_activity(
        self,
        config: MailchimpGetCampaignEepURLActivityConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get EepURL activity for a campaign."""
        endpoint = f"reports/{config.campaign_id}/eepurl"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_campaign_eepurl_activity"
        )

    async def _handle_get_campaign_locations(
        self,
        config: MailchimpGetCampaignLocationsConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get top locations for a campaign."""
        endpoint = f"reports/{config.campaign_id}/locations"
        params = {"count": config.count, "offset": config.offset}

        result = await self._make_request(
            "GET",
            endpoint,
            credentials,
            params=params,
            action_name="fetch_campaign_top_locations",
        )

        if result["status"] == "success" and "locations" in result["data"]:
            locations_data = result["data"]["locations"]
            formatted_locations = [
                {
                    "country": location.get("country"),
                    "region": location.get("region", "N/A"),
                    "opens": location.get("opens", 0),
                    "clicks": location.get("clicks", 0),
                }
                for location in locations_data
            ]
            result["data"]["locations_formatted"] = formatted_locations

        return result

    async def _handle_get_campaign_sent_to(
        self, config: MailchimpGetCampaignSentToConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get list of subscribers a campaign was sent to."""
        endpoint = f"reports/{config.campaign_id}/sent-to"
        params = {"count": config.count, "offset": config.offset}

        result = await self._make_request(
            "GET",
            endpoint,
            credentials,
            params=params,
            action_name="list_campaign_recipients",
        )

        if result["status"] == "success" and "sent_to" in result["data"]:
            sent_to_data = result["data"]["sent_to"]
            formatted_sent_to = [
                {
                    "email_address": member.get("email_address"),
                    "status": member.get("status"),
                    "open_count": member.get("open_count", 0),
                    "last_open": member.get("last_open"),
                }
                for member in sent_to_data
            ]
            result["data"]["sent_to_formatted"] = formatted_sent_to

        return result

    async def _handle_get_campaign_unsubscribes(
        self,
        config: MailchimpGetCampaignUnsubscribesConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get unsubscribed members from a campaign."""
        endpoint = f"reports/{config.campaign_id}/unsubscribed"
        params = {"count": config.count, "offset": config.offset}

        result = await self._make_request(
            "GET",
            endpoint,
            credentials,
            params=params,
            action_name="list_campaign_unsubscribes",
        )

        if result["status"] == "success" and "unsubscribes" in result["data"]:
            unsubscribes_data = result["data"]["unsubscribes"]
            formatted_unsubscribes = [
                {
                    "email_address": member.get("email_address"),
                    "timestamp": member.get("timestamp"),
                    "reason": member.get("reason", "N/A"),
                }
                for member in unsubscribes_data
            ]
            result["data"]["unsubscribes_formatted"] = formatted_unsubscribes

        return result

    async def _handle_get_campaign_opens(
        self, config: MailchimpGetCampaignOpensConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get all opens for a campaign."""
        endpoint = f"reports/{config.campaign_id}/open-details"
        params = {"count": config.count, "offset": config.offset}
        if config.since:
            params["since"] = config.since

        result = await self._make_request(
            "GET",
            endpoint,
            credentials,
            params=params,
            action_name="fetch_campaign_opens",
        )

        if result["status"] == "success" and "members" in result["data"]:
            members_data = result["data"]["members"]
            formatted_members = [
                {
                    "email_address": member.get("email_address"),
                    "opens_count": member.get("opens_count", 0),
                    "last_open": member.get("last_open"),
                }
                for member in members_data
            ]
            result["data"]["members_formatted"] = formatted_members

        return result

    async def _handle_get_member_campaign_open(
        self,
        config: MailchimpGetMemberCampaignOpenConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get opens by a specific member."""
        subscriber_hash = get_subscriber_hash(config.email_address)
        endpoint = f"reports/{config.campaign_id}/open-details/{subscriber_hash}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_member_campaign_opens"
        )

    # ========================================================================
    # Handler Methods - E-commerce Stores
    # ========================================================================

    async def _handle_list_ecommerce_stores(
        self,
        config: MailchimpListEcommerceStoresConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get all e-commerce stores."""
        params = {"count": config.count, "offset": config.offset}

        result = await self._make_request(
            "GET",
            "ecommerce/stores",
            credentials,
            params=params,
            action_name="list_ecommerce_stores",
        )

        if result["status"] == "success" and "stores" in result["data"]:
            stores_data = result["data"]["stores"]
            formatted_stores = [
                {
                    "id": store.get("id"),
                    "name": store.get("name"),
                    "domain": store.get("domain", "N/A"),
                    "currency_code": store.get("currency_code"),
                    "created_at": store.get("created_at"),
                }
                for store in stores_data
            ]
            result["data"]["stores_formatted"] = formatted_stores

        return result

    async def _handle_get_ecommerce_store(
        self, config: MailchimpGetEcommerceStoreConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get information about a specific store."""
        endpoint = f"ecommerce/stores/{config.store_id}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_ecommerce_store"
        )

    async def _handle_add_ecommerce_store(
        self, config: MailchimpAddEcommerceStoreConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Add a new e-commerce store."""
        body = {
            "id": config.id,
            "list_id": config.list_id,
            "name": config.name,
            "currency_code": config.currency_code,
        }

        if config.domain:
            body["domain"] = config.domain
        if config.email_address:
            body["email_address"] = config.email_address
        if config.phone:
            body["phone"] = config.phone
        if config.address:
            body["address"] = config.address

        return await self._make_request(
            "POST",
            "ecommerce/stores",
            credentials,
            json_body=body,
            action_name="create_ecommerce_store",
        )

    async def _handle_update_ecommerce_store(
        self,
        config: MailchimpUpdateEcommerceStoreConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Update an e-commerce store."""
        endpoint = f"ecommerce/stores/{config.store_id}"
        body = {}

        if config.name:
            body["name"] = config.name
        if config.currency_code:
            body["currency_code"] = config.currency_code
        if config.domain:
            body["domain"] = config.domain
        if config.email_address:
            body["email_address"] = config.email_address
        if config.phone:
            body["phone"] = config.phone

        return await self._make_request(
            "PATCH",
            endpoint,
            credentials,
            json_body=body,
            action_name="update_ecommerce_store",
        )

    async def _handle_delete_ecommerce_store(
        self,
        config: MailchimpDeleteEcommerceStoreConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Delete an e-commerce store."""
        endpoint = f"ecommerce/stores/{config.store_id}"
        return await self._make_request(
            "DELETE", endpoint, credentials, action_name="delete_ecommerce_store"
        )

    # ========================================================================
    # Handler Methods - E-commerce Products
    # ========================================================================

    async def _handle_list_ecommerce_products(
        self,
        config: MailchimpListEcommerceProductsConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get all products in a store."""
        endpoint = f"ecommerce/stores/{config.store_id}/products"
        params = {"count": config.count, "offset": config.offset}

        result = await self._make_request(
            "GET",
            endpoint,
            credentials,
            params=params,
            action_name="list_ecommerce_products",
        )

        if result["status"] == "success" and "products" in result["data"]:
            products_data = result["data"]["products"]
            formatted_products = [
                {
                    "id": product.get("id"),
                    "title": product.get("title"),
                    "type": product.get("type", "N/A"),
                    "vendor": product.get("vendor", "N/A"),
                    "variants_count": len(product.get("variants", [])),
                }
                for product in products_data
            ]
            result["data"]["products_formatted"] = formatted_products

        return result

    async def _handle_get_ecommerce_product(
        self,
        config: MailchimpGetEcommerceProductConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get information about a specific product."""
        endpoint = f"ecommerce/stores/{config.store_id}/products/{config.product_id}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_ecommerce_product"
        )

    async def _handle_add_ecommerce_product(
        self,
        config: MailchimpAddEcommerceProductConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Add a new product to a store."""
        endpoint = f"ecommerce/stores/{config.store_id}/products"
        body = {"id": config.id, "title": config.title}

        if config.description:
            body["description"] = config.description
        if config.type:
            body["type"] = config.type
        if config.vendor:
            body["vendor"] = config.vendor
        if config.url:
            body["url"] = config.url
        if config.image_url:
            body["image_url"] = config.image_url
        if config.published_at_foreign:
            body["published_at_foreign"] = config.published_at_foreign
        if config.variants:
            body["variants"] = config.variants

        return await self._make_request(
            "POST",
            endpoint,
            credentials,
            json_body=body,
            action_name="create_ecommerce_product",
        )

    async def _handle_update_ecommerce_product(
        self,
        config: MailchimpUpdateEcommerceProductConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Update a product."""
        endpoint = f"ecommerce/stores/{config.store_id}/products/{config.product_id}"
        body = {}

        if config.title:
            body["title"] = config.title
        if config.description:
            body["description"] = config.description
        if config.type:
            body["type"] = config.type
        if config.vendor:
            body["vendor"] = config.vendor
        if config.url:
            body["url"] = config.url
        if config.image_url:
            body["image_url"] = config.image_url

        return await self._make_request(
            "PATCH",
            endpoint,
            credentials,
            json_body=body,
            action_name="update_ecommerce_product",
        )

    async def _handle_delete_ecommerce_product(
        self,
        config: MailchimpDeleteEcommerceProductConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Delete a product."""
        endpoint = f"ecommerce/stores/{config.store_id}/products/{config.product_id}"
        return await self._make_request(
            "DELETE", endpoint, credentials, action_name="delete_ecommerce_product"
        )

    async def _handle_list_ecommerce_product_variants(
        self,
        config: MailchimpListEcommerceProductVariantsConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get all variants for a product."""
        endpoint = (
            f"ecommerce/stores/{config.store_id}/products/{config.product_id}/variants"
        )
        params = {"count": config.count, "offset": config.offset}

        result = await self._make_request(
            "GET",
            endpoint,
            credentials,
            params=params,
            action_name="list_product_variants",
        )

        if result["status"] == "success" and "variants" in result["data"]:
            variants_data = result["data"]["variants"]
            formatted_variants = [
                {
                    "id": variant.get("id"),
                    "title": variant.get("title"),
                    "price": variant.get("price"),
                    "sku": variant.get("sku", "N/A"),
                    "inventory_quantity": variant.get("inventory_quantity", 0),
                }
                for variant in variants_data
            ]
            result["data"]["variants_formatted"] = formatted_variants

        return result

    async def _handle_get_ecommerce_product_variant(
        self,
        config: MailchimpGetEcommerceProductVariantConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get information about a specific product variant."""
        endpoint = f"ecommerce/stores/{config.store_id}/products/{config.product_id}/variants/{config.variant_id}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_product_variant"
        )

    async def _handle_add_ecommerce_product_variant(
        self,
        config: MailchimpAddEcommerceProductVariantConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Add a new variant to a product."""
        endpoint = (
            f"ecommerce/stores/{config.store_id}/products/{config.product_id}/variants"
        )
        body = {"id": config.id, "title": config.title, "price": config.price}

        if config.sku:
            body["sku"] = config.sku
        if config.inventory_quantity is not None:
            body["inventory_quantity"] = config.inventory_quantity
        if config.image_url:
            body["image_url"] = config.image_url
        if config.url:
            body["url"] = config.url

        return await self._make_request(
            "POST",
            endpoint,
            credentials,
            json_body=body,
            action_name="create_product_variant",
        )

    async def _handle_update_ecommerce_product_variant(
        self,
        config: MailchimpUpdateEcommerceProductVariantConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Update a product variant."""
        endpoint = f"ecommerce/stores/{config.store_id}/products/{config.product_id}/variants/{config.variant_id}"
        body = {}

        if config.title:
            body["title"] = config.title
        if config.price is not None:
            body["price"] = config.price
        if config.sku:
            body["sku"] = config.sku
        if config.inventory_quantity is not None:
            body["inventory_quantity"] = config.inventory_quantity
        if config.image_url:
            body["image_url"] = config.image_url

        return await self._make_request(
            "PATCH",
            endpoint,
            credentials,
            json_body=body,
            action_name="update_product_variant",
        )

    # ========================================================================
    # Handler Methods - E-commerce Orders
    # ========================================================================

    async def _handle_list_ecommerce_orders(
        self,
        config: MailchimpListEcommerceOrdersConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get all orders for a store."""
        endpoint = f"ecommerce/stores/{config.store_id}/orders"
        params = {"count": config.count, "offset": config.offset}
        if config.customer_id:
            params["customer_id"] = config.customer_id
        if config.has_outreach is not None:
            params["has_outreach"] = str(config.has_outreach).lower()

        result = await self._make_request(
            "GET",
            endpoint,
            credentials,
            params=params,
            action_name="list_ecommerce_orders",
        )

        if result["status"] == "success" and "orders" in result["data"]:
            orders_data = result["data"]["orders"]
            formatted_orders = [
                {
                    "id": order.get("id"),
                    "customer_email": order.get("customer", {}).get(
                        "email_address", "N/A"
                    ),
                    "order_total": order.get("order_total"),
                    "currency_code": order.get("currency_code"),
                    "processed_at": order.get("processed_at_foreign"),
                }
                for order in orders_data
            ]
            result["data"]["orders_formatted"] = formatted_orders

        return result

    async def _handle_get_ecommerce_order(
        self, config: MailchimpGetEcommerceOrderConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get information about a specific order."""
        endpoint = f"ecommerce/stores/{config.store_id}/orders/{config.order_id}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_ecommerce_order"
        )

    async def _handle_add_ecommerce_order(
        self, config: MailchimpAddEcommerceOrderConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Add a new order to a store."""
        endpoint = f"ecommerce/stores/{config.store_id}/orders"
        body = {
            "id": config.id,
            "customer": config.customer,
            "order_total": config.order_total,
            "lines": config.lines,
        }

        if config.currency_code:
            body["currency_code"] = config.currency_code
        if config.tax_total is not None:
            body["tax_total"] = config.tax_total
        if config.shipping_total is not None:
            body["shipping_total"] = config.shipping_total
        if config.processed_at_foreign:
            body["processed_at_foreign"] = config.processed_at_foreign
        if config.updated_at_foreign:
            body["updated_at_foreign"] = config.updated_at_foreign
        if config.campaign_id:
            body["campaign_id"] = config.campaign_id

        return await self._make_request(
            "POST",
            endpoint,
            credentials,
            json_body=body,
            action_name="create_ecommerce_order",
        )

    async def _handle_update_ecommerce_order(
        self,
        config: MailchimpUpdateEcommerceOrderConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Update an order."""
        endpoint = f"ecommerce/stores/{config.store_id}/orders/{config.order_id}"
        body = {}

        if config.customer:
            body["customer"] = config.customer
        if config.order_total is not None:
            body["order_total"] = config.order_total
        if config.tax_total is not None:
            body["tax_total"] = config.tax_total
        if config.shipping_total is not None:
            body["shipping_total"] = config.shipping_total
        if config.processed_at_foreign:
            body["processed_at_foreign"] = config.processed_at_foreign
        if config.updated_at_foreign:
            body["updated_at_foreign"] = config.updated_at_foreign

        return await self._make_request(
            "PATCH",
            endpoint,
            credentials,
            json_body=body,
            action_name="update_ecommerce_order",
        )

    async def _handle_delete_ecommerce_order(
        self,
        config: MailchimpDeleteEcommerceOrderConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Delete an order."""
        endpoint = f"ecommerce/stores/{config.store_id}/orders/{config.order_id}"
        return await self._make_request(
            "DELETE", endpoint, credentials, action_name="delete_ecommerce_order"
        )

    async def _handle_list_ecommerce_order_lines(
        self,
        config: MailchimpListEcommerceOrderLinesConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get all line items for an order."""
        endpoint = f"ecommerce/stores/{config.store_id}/orders/{config.order_id}/lines"
        params = {"count": config.count, "offset": config.offset}

        result = await self._make_request(
            "GET",
            endpoint,
            credentials,
            params=params,
            action_name="list_order_line_items",
        )

        if result["status"] == "success" and "lines" in result["data"]:
            lines_data = result["data"]["lines"]
            formatted_lines = [
                {
                    "id": line.get("id"),
                    "product_id": line.get("product_id"),
                    "product_variant_id": line.get("product_variant_id"),
                    "quantity": line.get("quantity"),
                    "price": line.get("price"),
                }
                for line in lines_data
            ]
            result["data"]["lines_formatted"] = formatted_lines

        return result

    async def _handle_add_ecommerce_order_line(
        self,
        config: MailchimpAddEcommerceOrderLineConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Add a line item to an order."""
        endpoint = f"ecommerce/stores/{config.store_id}/orders/{config.order_id}/lines"
        body = {
            "id": config.id,
            "product_id": config.product_id,
            "product_variant_id": config.product_variant_id,
            "quantity": config.quantity,
            "price": config.price,
        }

        return await self._make_request(
            "POST",
            endpoint,
            credentials,
            json_body=body,
            action_name="create_order_line_item",
        )

    # ========================================================================
    # Handler Methods - E-commerce Customers
    # ========================================================================

    async def _handle_list_ecommerce_customers(
        self,
        config: MailchimpListEcommerceCustomersConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get all customers for a store."""
        endpoint = f"ecommerce/stores/{config.store_id}/customers"
        params = {"count": config.count, "offset": config.offset}
        if config.email_address:
            params["email_address"] = config.email_address

        result = await self._make_request(
            "GET",
            endpoint,
            credentials,
            params=params,
            action_name="list_ecommerce_customers",
        )

        if result["status"] == "success" and "customers" in result["data"]:
            customers_data = result["data"]["customers"]
            formatted_customers = [
                {
                    "id": customer.get("id"),
                    "email_address": customer.get("email_address"),
                    "opt_in_status": customer.get("opt_in_status"),
                    "first_name": customer.get("first_name", "N/A"),
                    "last_name": customer.get("last_name", "N/A"),
                    "orders_count": customer.get("orders_count", 0),
                }
                for customer in customers_data
            ]
            result["data"]["customers_formatted"] = formatted_customers

        return result

    async def _handle_get_ecommerce_customer(
        self,
        config: MailchimpGetEcommerceCustomerConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get information about a specific customer."""
        endpoint = f"ecommerce/stores/{config.store_id}/customers/{config.customer_id}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_ecommerce_customer"
        )

    async def _handle_add_ecommerce_customer(
        self,
        config: MailchimpAddEcommerceCustomerConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Add a new customer to a store."""
        endpoint = f"ecommerce/stores/{config.store_id}/customers"
        body = {
            "id": config.id,
            "email_address": config.email_address,
            "opt_in_status": config.opt_in_status,
        }

        if config.company:
            body["company"] = config.company
        if config.first_name:
            body["first_name"] = config.first_name
        if config.last_name:
            body["last_name"] = config.last_name
        if config.address:
            body["address"] = config.address

        return await self._make_request(
            "POST",
            endpoint,
            credentials,
            json_body=body,
            action_name="create_ecommerce_customer",
        )

    async def _handle_add_or_update_ecommerce_customer(
        self,
        config: MailchimpAddOrUpdateEcommerceCustomerConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Add or update a customer (upsert)."""
        endpoint = f"ecommerce/stores/{config.store_id}/customers/{config.customer_id}"
        body = {
            "id": config.customer_id,
            "email_address": config.email_address,
            "opt_in_status": config.opt_in_status,
        }

        if config.company:
            body["company"] = config.company
        if config.first_name:
            body["first_name"] = config.first_name
        if config.last_name:
            body["last_name"] = config.last_name
        if config.address:
            body["address"] = config.address

        return await self._make_request(
            "PUT",
            endpoint,
            credentials,
            json_body=body,
            action_name="upsert_ecommerce_customer",
        )

    async def _handle_update_ecommerce_customer(
        self,
        config: MailchimpUpdateEcommerceCustomerConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Update a customer."""
        endpoint = f"ecommerce/stores/{config.store_id}/customers/{config.customer_id}"
        body = {}

        if config.email_address:
            body["email_address"] = config.email_address
        if config.opt_in_status is not None:
            body["opt_in_status"] = config.opt_in_status
        if config.company:
            body["company"] = config.company
        if config.first_name:
            body["first_name"] = config.first_name
        if config.last_name:
            body["last_name"] = config.last_name

        return await self._make_request(
            "PATCH",
            endpoint,
            credentials,
            json_body=body,
            action_name="update_ecommerce_customer",
        )

    async def _handle_delete_ecommerce_customer(
        self,
        config: MailchimpDeleteEcommerceCustomerConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Delete a customer."""
        endpoint = f"ecommerce/stores/{config.store_id}/customers/{config.customer_id}"
        return await self._make_request(
            "DELETE", endpoint, credentials, action_name="delete_ecommerce_customer"
        )

    # ========================================================================
    # Handler Methods - E-commerce Carts
    # ========================================================================

    async def _handle_list_ecommerce_carts(
        self,
        config: MailchimpListEcommerceCartsConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get all carts for a store."""
        endpoint = f"ecommerce/stores/{config.store_id}/carts"
        params = {"count": config.count, "offset": config.offset}

        result = await self._make_request(
            "GET",
            endpoint,
            credentials,
            params=params,
            action_name="list_ecommerce_carts",
        )

        if result["status"] == "success" and "carts" in result["data"]:
            carts_data = result["data"]["carts"]
            formatted_carts = [
                {
                    "id": cart.get("id"),
                    "customer_email": cart.get("customer", {}).get(
                        "email_address", "N/A"
                    ),
                    "order_total": cart.get("order_total"),
                    "currency_code": cart.get("currency_code"),
                    "created_at": cart.get("created_at"),
                }
                for cart in carts_data
            ]
            result["data"]["carts_formatted"] = formatted_carts

        return result

    async def _handle_get_ecommerce_cart(
        self, config: MailchimpGetEcommerceCartConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get information about a specific cart."""
        endpoint = f"ecommerce/stores/{config.store_id}/carts/{config.cart_id}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_ecommerce_cart"
        )

    async def _handle_add_ecommerce_cart(
        self, config: MailchimpAddEcommerceCartConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Add a new cart to a store."""
        endpoint = f"ecommerce/stores/{config.store_id}/carts"
        body = {
            "id": config.id,
            "customer": config.customer,
            "currency_code": config.currency_code,
            "order_total": config.order_total,
            "lines": config.lines,
        }

        if config.checkout_url:
            body["checkout_url"] = config.checkout_url
        if config.tax_total is not None:
            body["tax_total"] = config.tax_total

        return await self._make_request(
            "POST",
            endpoint,
            credentials,
            json_body=body,
            action_name="create_ecommerce_cart",
        )

    async def _handle_update_ecommerce_cart(
        self,
        config: MailchimpUpdateEcommerceCartConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Update a cart."""
        endpoint = f"ecommerce/stores/{config.store_id}/carts/{config.cart_id}"
        body = {}

        if config.customer:
            body["customer"] = config.customer
        if config.order_total is not None:
            body["order_total"] = config.order_total
        if config.checkout_url:
            body["checkout_url"] = config.checkout_url
        if config.tax_total is not None:
            body["tax_total"] = config.tax_total

        return await self._make_request(
            "PATCH",
            endpoint,
            credentials,
            json_body=body,
            action_name="update_ecommerce_cart",
        )

    async def _handle_delete_ecommerce_cart(
        self,
        config: MailchimpDeleteEcommerceCartConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Delete a cart."""
        endpoint = f"ecommerce/stores/{config.store_id}/carts/{config.cart_id}"
        return await self._make_request(
            "DELETE", endpoint, credentials, action_name="delete_ecommerce_cart"
        )

    async def _handle_list_ecommerce_cart_lines(
        self,
        config: MailchimpListEcommerceCartLinesConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get all line items for a cart."""
        endpoint = f"ecommerce/stores/{config.store_id}/carts/{config.cart_id}/lines"
        params = {"count": config.count, "offset": config.offset}

        result = await self._make_request(
            "GET",
            endpoint,
            credentials,
            params=params,
            action_name="list_cart_line_items",
        )

        if result["status"] == "success" and "lines" in result["data"]:
            lines_data = result["data"]["lines"]
            formatted_lines = [
                {
                    "id": line.get("id"),
                    "product_id": line.get("product_id"),
                    "product_variant_id": line.get("product_variant_id"),
                    "quantity": line.get("quantity"),
                    "price": line.get("price"),
                }
                for line in lines_data
            ]
            result["data"]["lines_formatted"] = formatted_lines

        return result

    async def _handle_add_ecommerce_cart_line(
        self,
        config: MailchimpAddEcommerceCartLineConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Add a line item to a cart."""
        endpoint = f"ecommerce/stores/{config.store_id}/carts/{config.cart_id}/lines"
        body = {
            "id": config.id,
            "product_id": config.product_id,
            "product_variant_id": config.product_variant_id,
            "quantity": config.quantity,
            "price": config.price,
        }

        return await self._make_request(
            "POST",
            endpoint,
            credentials,
            json_body=body,
            action_name="create_cart_line_item",
        )

    # ========================================================================
    # Handler Methods - Batch Operations
    # ========================================================================

    async def _handle_start_batch_operation(
        self,
        config: MailchimpStartBatchOperationConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Start a batch operation to run multiple API operations asynchronously."""
        import json

        operations = json.loads(config.operations)
        body = {"operations": operations}
        return await self._make_request(
            "POST",
            "batches",
            credentials,
            json_body=body,
            action_name="start_batch_operation",
        )

    async def _handle_list_batches(
        self, config: MailchimpListBatchesConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get a list of all batch operations."""
        params = {"count": config.count, "offset": config.offset}
        result = await self._make_request(
            "GET", "batches", credentials, params=params, action_name="list_batch_operations"
        )

        if result["status"] == "success" and "batches" in result["data"]:
            batches_data = result["data"]["batches"]
            formatted_batches = [
                {
                    "id": batch.get("id"),
                    "status": batch.get("status"),
                    "total_operations": batch.get("total_operations", 0),
                    "finished_operations": batch.get("finished_operations", 0),
                    "submitted_at": batch.get("submitted_at"),
                }
                for batch in batches_data
            ]
            result["data"]["batches_formatted"] = formatted_batches

        return result

    async def _handle_get_batch_status(
        self, config: MailchimpGetBatchStatusConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get the status of a specific batch operation."""
        endpoint = f"batches/{config.batch_id}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_batch_status"
        )

    async def _handle_delete_batch(
        self, config: MailchimpDeleteBatchConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Stop and remove a batch request."""
        endpoint = f"batches/{config.batch_id}"
        return await self._make_request(
            "DELETE", endpoint, credentials, action_name="cancel_batch_request"
        )

    # ========================================================================
    # Handler Methods - Webhooks
    # ========================================================================

    async def _handle_list_webhooks(
        self, config: MailchimpListWebhooksConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get all webhooks configured for a specific list."""
        endpoint = f"lists/{config.list_id}/webhooks"
        result = await self._make_request(
            "GET", endpoint, credentials, action_name="list_list_webhooks"
        )

        if result["status"] == "success" and "webhooks" in result["data"]:
            webhooks_data = result["data"]["webhooks"]
            formatted_webhooks = [
                {
                    "id": webhook.get("id"),
                    "url": webhook.get("url"),
                    "events": ", ".join(
                        [k for k, v in webhook.get("events", {}).items() if v]
                    ),
                }
                for webhook in webhooks_data
            ]
            result["data"]["webhooks_formatted"] = formatted_webhooks

        return result

    async def _handle_get_webhook(
        self, config: MailchimpGetWebhookConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get information about a specific webhook."""
        endpoint = f"lists/{config.list_id}/webhooks/{config.webhook_id}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_list_webhook"
        )

    async def _handle_add_webhook(
        self, config: MailchimpAddWebhookConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Create a new webhook for a list."""
        import json

        endpoint = f"lists/{config.list_id}/webhooks"
        body = {
            "url": config.url,
            "events": json.loads(config.events),
            "sources": json.loads(config.sources),
        }
        return await self._make_request(
            "POST", endpoint, credentials, json_body=body, action_name="create_list_webhook"
        )

    async def _handle_update_webhook(
        self, config: MailchimpUpdateWebhookConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Update an existing webhook configuration."""
        import json

        endpoint = f"lists/{config.list_id}/webhooks/{config.webhook_id}"
        body = {}

        if config.url:
            body["url"] = config.url
        if config.events:
            body["events"] = json.loads(config.events)
        if config.sources:
            body["sources"] = json.loads(config.sources)

        return await self._make_request(
            "PATCH", endpoint, credentials, json_body=body, action_name="update_list_webhook"
        )

    async def _handle_delete_webhook(
        self, config: MailchimpDeleteWebhookConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Delete a webhook from a list."""
        endpoint = f"lists/{config.list_id}/webhooks/{config.webhook_id}"
        return await self._make_request(
            "DELETE", endpoint, credentials, action_name="delete_list_webhook"
        )

    # ========================================================================
    # Handler Methods - Landing Pages
    # ========================================================================

    async def _handle_list_landing_pages(
        self, config: MailchimpListLandingPagesConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get all landing pages."""
        params = {"count": config.count, "offset": config.offset}
        result = await self._make_request(
            "GET",
            "landing-pages",
            credentials,
            params=params,
            action_name="list_landing_pages",
        )

        if result["status"] == "success" and "landing_pages" in result["data"]:
            pages_data = result["data"]["landing_pages"]
            formatted_pages = [
                {
                    "id": page.get("id"),
                    "name": page.get("name"),
                    "title": page.get("title"),
                    "status": page.get("status"),
                    "url": page.get("url"),
                }
                for page in pages_data
            ]
            result["data"]["landing_pages_formatted"] = formatted_pages

        return result

    async def _handle_get_landing_page(
        self, config: MailchimpGetLandingPageConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get information about a specific landing page."""
        endpoint = f"landing-pages/{config.page_id}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_landing_page"
        )

    async def _handle_create_landing_page(
        self, config: MailchimpCreateLandingPageConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Create a new landing page."""
        body = {"type": config.type, "title": config.title, "list_id": config.list_id}

        if config.store_id:
            body["store_id"] = config.store_id
        if config.description:
            body["description"] = config.description

        return await self._make_request(
            "POST",
            "landing-pages",
            credentials,
            json_body=body,
            action_name="create_landing_page",
        )

    async def _handle_update_landing_page(
        self, config: MailchimpUpdateLandingPageConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Update a landing page."""
        endpoint = f"landing-pages/{config.page_id}"
        body = {}

        if config.title:
            body["title"] = config.title
        if config.description:
            body["description"] = config.description

        return await self._make_request(
            "PATCH",
            endpoint,
            credentials,
            json_body=body,
            action_name="update_landing_page",
        )

    async def _handle_delete_landing_page(
        self, config: MailchimpDeleteLandingPageConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Delete a landing page."""
        endpoint = f"landing-pages/{config.page_id}"
        return await self._make_request(
            "DELETE", endpoint, credentials, action_name="delete_landing_page"
        )

    # ========================================================================
    # Handler Methods - E-commerce Product Images
    # ========================================================================

    async def _handle_list_product_images(
        self, config: MailchimpListProductImagesConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get all images for a product."""
        endpoint = (
            f"ecommerce/stores/{config.store_id}/products/{config.product_id}/images"
        )
        params = {"count": config.count, "offset": config.offset}
        result = await self._make_request(
            "GET",
            endpoint,
            credentials,
            params=params,
            action_name="list_product_images",
        )

        if result["status"] == "success" and "images" in result["data"]:
            images_data = result["data"]["images"]
            formatted_images = [
                {
                    "id": image.get("id"),
                    "url": image.get("url"),
                    "variant_ids": ", ".join(image.get("variant_ids", [])),
                }
                for image in images_data
            ]
            result["data"]["images_formatted"] = formatted_images

        return result

    async def _handle_get_product_image(
        self, config: MailchimpGetProductImageConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get information about a specific product image."""
        endpoint = f"ecommerce/stores/{config.store_id}/products/{config.product_id}/images/{config.image_id}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_product_image"
        )

    async def _handle_add_product_image(
        self, config: MailchimpAddProductImageConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Add a new image to a product."""
        import json

        endpoint = (
            f"ecommerce/stores/{config.store_id}/products/{config.product_id}/images"
        )
        body = {
            "id": config.id,
            "url": config.url,
            "variant_ids": json.loads(config.variant_ids),
        }
        return await self._make_request(
            "POST",
            endpoint,
            credentials,
            json_body=body,
            action_name="add_product_image",
        )

    async def _handle_update_product_image(
        self,
        config: MailchimpUpdateProductImageConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Update a product image."""
        import json

        endpoint = f"ecommerce/stores/{config.store_id}/products/{config.product_id}/images/{config.image_id}"
        body = {}

        if config.url:
            body["url"] = config.url
        if config.variant_ids:
            body["variant_ids"] = json.loads(config.variant_ids)

        return await self._make_request(
            "PATCH",
            endpoint,
            credentials,
            json_body=body,
            action_name="update_product_image",
        )

    async def _handle_delete_product_image(
        self,
        config: MailchimpDeleteProductImageConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Delete a product image."""
        endpoint = f"ecommerce/stores/{config.store_id}/products/{config.product_id}/images/{config.image_id}"
        return await self._make_request(
            "DELETE", endpoint, credentials, action_name="delete_product_image"
        )

    # ========================================================================
    # Handler Methods - E-commerce Promo Rules
    # ========================================================================

    async def _handle_list_promo_rules(
        self, config: MailchimpListPromoRulesConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get all promo rules for a store."""
        endpoint = f"ecommerce/stores/{config.store_id}/promo-rules"
        params = {"count": config.count, "offset": config.offset}
        result = await self._make_request(
            "GET", endpoint, credentials, params=params, action_name="list_promo_rules"
        )

        if result["status"] == "success" and "promo_rules" in result["data"]:
            rules_data = result["data"]["promo_rules"]
            formatted_rules = [
                {
                    "id": rule.get("id"),
                    "title": rule.get("title"),
                    "amount": rule.get("amount"),
                    "type": rule.get("type"),
                    "enabled": rule.get("enabled"),
                }
                for rule in rules_data
            ]
            result["data"]["promo_rules_formatted"] = formatted_rules

        return result

    async def _handle_get_promo_rule(
        self, config: MailchimpGetPromoRuleConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get information about a specific promo rule."""
        endpoint = (
            f"ecommerce/stores/{config.store_id}/promo-rules/{config.promo_rule_id}"
        )
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_promo_rule"
        )

    async def _handle_add_promo_rule(
        self, config: MailchimpAddPromoRuleConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Create a new promo rule."""
        endpoint = f"ecommerce/stores/{config.store_id}/promo-rules"
        body = {
            "id": config.id,
            "title": config.title,
            "description": config.description,
            "amount": config.amount,
            "type": config.type,
        }

        if config.enabled is not None:
            body["enabled"] = config.enabled

        return await self._make_request(
            "POST", endpoint, credentials, json_body=body, action_name="create_promo_rule"
        )

    async def _handle_update_promo_rule(
        self, config: MailchimpUpdatePromoRuleConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Update a promo rule."""
        endpoint = (
            f"ecommerce/stores/{config.store_id}/promo-rules/{config.promo_rule_id}"
        )
        body = {}

        if config.title:
            body["title"] = config.title
        if config.description:
            body["description"] = config.description
        if config.amount is not None:
            body["amount"] = config.amount
        if config.enabled is not None:
            body["enabled"] = config.enabled

        return await self._make_request(
            "PATCH",
            endpoint,
            credentials,
            json_body=body,
            action_name="update_promo_rule",
        )

    async def _handle_delete_promo_rule(
        self, config: MailchimpDeletePromoRuleConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Delete a promo rule."""
        endpoint = (
            f"ecommerce/stores/{config.store_id}/promo-rules/{config.promo_rule_id}"
        )
        return await self._make_request(
            "DELETE", endpoint, credentials, action_name="delete_promo_rule"
        )

    # ========================================================================
    # Handler Methods - E-commerce Promo Codes
    # ========================================================================

    async def _handle_list_promo_codes(
        self, config: MailchimpListPromoCodesConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get all promo codes for a promo rule."""
        endpoint = f"ecommerce/stores/{config.store_id}/promo-rules/{config.promo_rule_id}/promo-codes"
        params = {"count": config.count, "offset": config.offset}
        result = await self._make_request(
            "GET", endpoint, credentials, params=params, action_name="list_promo_codes"
        )

        if result["status"] == "success" and "promo_codes" in result["data"]:
            codes_data = result["data"]["promo_codes"]
            formatted_codes = [
                {
                    "id": code.get("id"),
                    "code": code.get("code"),
                    "enabled": code.get("enabled"),
                }
                for code in codes_data
            ]
            result["data"]["promo_codes_formatted"] = formatted_codes

        return result

    async def _handle_get_promo_code(
        self, config: MailchimpGetPromoCodeConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get information about a specific promo code."""
        endpoint = f"ecommerce/stores/{config.store_id}/promo-rules/{config.promo_rule_id}/promo-codes/{config.promo_code_id}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_promo_code"
        )

    async def _handle_add_promo_code(
        self, config: MailchimpAddPromoCodeConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Create a new promo code."""
        endpoint = f"ecommerce/stores/{config.store_id}/promo-rules/{config.promo_rule_id}/promo-codes"
        body = {"id": config.id, "code": config.code}

        if config.enabled is not None:
            body["enabled"] = config.enabled

        return await self._make_request(
            "POST", endpoint, credentials, json_body=body, action_name="create_promo_code"
        )

    async def _handle_update_promo_code(
        self, config: MailchimpUpdatePromoCodeConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Update a promo code."""
        endpoint = f"ecommerce/stores/{config.store_id}/promo-rules/{config.promo_rule_id}/promo-codes/{config.promo_code_id}"
        body = {}

        if config.code:
            body["code"] = config.code
        if config.enabled is not None:
            body["enabled"] = config.enabled

        return await self._make_request(
            "PATCH",
            endpoint,
            credentials,
            json_body=body,
            action_name="update_promo_code",
        )

    async def _handle_delete_promo_code(
        self, config: MailchimpDeletePromoCodeConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Delete a promo code."""
        endpoint = f"ecommerce/stores/{config.store_id}/promo-rules/{config.promo_rule_id}/promo-codes/{config.promo_code_id}"
        return await self._make_request(
            "DELETE", endpoint, credentials, action_name="delete_promo_code"
        )

    # ============================================================================
    # Signup Forms Handlers
    # ============================================================================

    async def _handle_list_signup_forms(
        self, config: MailchimpListSignupFormsConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """List all signup forms for a list."""
        endpoint = f"lists/{config.list_id}/signup-forms"
        result = await self._make_request(
            "GET", endpoint, credentials, action_name="list_signup_forms"
        )

        # Format for table display
        if result["status"] == "success" and "signup_forms" in result["data"]:
            forms_data = result["data"]["signup_forms"]
            formatted_forms = [
                {
                    "id": form.get("id"),
                    "type": form.get("signup_form_type"),
                    "list_id": form.get("list_id"),
                    "status": form.get("status"),
                }
                for form in forms_data
            ]
            result["data"]["signup_forms_formatted"] = formatted_forms

        return result

    async def _handle_create_signup_form(
        self, config: MailchimpCreateSignupFormConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Create a signup form for a list."""
        endpoint = f"lists/{config.list_id}/signup-forms"
        body = {"header": config.header, "contents": config.contents}

        if config.styles:
            body["styles"] = config.styles

        return await self._make_request(
            "POST",
            endpoint,
            credentials,
            json_body=body,
            action_name="create_signup_form",
        )

    async def _handle_update_signup_form(
        self, config: MailchimpUpdateSignupFormConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Update a signup form."""
        endpoint = f"lists/{config.list_id}/signup-forms/{config.signup_form_id}"
        body = {}

        if config.header:
            body["header"] = config.header
        if config.contents:
            body["contents"] = config.contents
        if config.styles:
            body["styles"] = config.styles

        return await self._make_request(
            "PATCH",
            endpoint,
            credentials,
            json_body=body,
            action_name="update_signup_form",
        )

    # ============================================================================
    # File Manager Folders Handlers
    # ============================================================================

    async def _handle_list_file_manager_folders(
        self,
        config: MailchimpListFileManagerFoldersConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """List all folders in the File Manager."""
        endpoint = "file-manager/folders"
        params = {"count": config.count, "offset": config.offset}
        result = await self._make_request(
            "GET",
            endpoint,
            credentials,
            params=params,
            action_name="list_file_folders",
        )

        # Format for table display
        if result["status"] == "success" and "folders" in result["data"]:
            folders_data = result["data"]["folders"]
            formatted_folders = [
                {
                    "id": folder.get("id"),
                    "name": folder.get("name"),
                    "file_count": folder.get("file_count", 0),
                    "created": folder.get("created_at"),
                }
                for folder in folders_data
            ]
            result["data"]["folders_formatted"] = formatted_folders

        return result

    async def _handle_get_file_manager_folder(
        self,
        config: MailchimpGetFileManagerFolderConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get a specific File Manager folder."""
        endpoint = f"file-manager/folders/{config.folder_id}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_file_folder"
        )

    async def _handle_create_file_manager_folder(
        self,
        config: MailchimpCreateFileManagerFolderConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Create a new File Manager folder."""
        endpoint = "file-manager/folders"
        body = {"name": config.name}
        return await self._make_request(
            "POST",
            endpoint,
            credentials,
            json_body=body,
            action_name="create_file_folder",
        )

    async def _handle_update_file_manager_folder(
        self,
        config: MailchimpUpdateFileManagerFolderConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Update a File Manager folder."""
        endpoint = f"file-manager/folders/{config.folder_id}"
        body = {"name": config.name}
        return await self._make_request(
            "PATCH",
            endpoint,
            credentials,
            json_body=body,
            action_name="update_file_folder",
        )

    async def _handle_delete_file_manager_folder(
        self,
        config: MailchimpDeleteFileManagerFolderConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Delete a File Manager folder."""
        endpoint = f"file-manager/folders/{config.folder_id}"
        return await self._make_request(
            "DELETE", endpoint, credentials, action_name="delete_file_folder"
        )

    # ============================================================================
    # File Manager Files Handlers
    # ============================================================================

    async def _handle_list_file_manager_files(
        self,
        config: MailchimpListFileManagerFilesConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """List all files in the File Manager."""
        endpoint = "file-manager/files"
        params = {"count": config.count, "offset": config.offset}

        if config.folder_id:
            params["folder_id"] = config.folder_id

        result = await self._make_request(
            "GET",
            endpoint,
            credentials,
            params=params,
            action_name="list_files",
        )

        # Format for table display
        if result["status"] == "success" and "files" in result["data"]:
            files_data = result["data"]["files"]
            formatted_files = [
                {
                    "id": file.get("id"),
                    "name": file.get("name"),
                    "type": file.get("type"),
                    "size": file.get("size"),
                    "created": file.get("created_at"),
                }
                for file in files_data
            ]
            result["data"]["files_formatted"] = formatted_files

        return result

    async def _handle_get_file_manager_file(
        self,
        config: MailchimpGetFileManagerFileConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get a specific File Manager file."""
        endpoint = f"file-manager/files/{config.file_id}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_file"
        )

    async def _handle_upload_file_manager_file(
        self,
        config: MailchimpUploadFileManagerFileConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Upload a file to the File Manager."""
        from nodes.core.media_resolver import resolve_media_input

        resolved = await resolve_media_input(
            config.file_data, default_mime="application/octet-stream"
        )
        endpoint = "file-manager/files"
        body = {"name": config.name, "file_data": resolved.base64}

        if config.folder_id:
            body["folder_id"] = config.folder_id

        return await self._make_request(
            "POST",
            endpoint,
            credentials,
            json_body=body,
            action_name="upload_file",
        )

    async def _handle_update_file_manager_file(
        self,
        config: MailchimpUpdateFileManagerFileConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Update a File Manager file."""
        endpoint = f"file-manager/files/{config.file_id}"
        body = {}

        if config.name:
            body["name"] = config.name
        if config.folder_id:
            body["folder_id"] = config.folder_id

        return await self._make_request(
            "PATCH",
            endpoint,
            credentials,
            json_body=body,
            action_name="update_file",
        )

    async def _handle_delete_file_manager_file(
        self,
        config: MailchimpDeleteFileManagerFileConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Delete a File Manager file."""
        endpoint = f"file-manager/files/{config.file_id}"
        return await self._make_request(
            "DELETE", endpoint, credentials, action_name="delete_file"
        )

    # ============================================================================
    # Campaign Folders Handlers
    # ============================================================================

    async def _handle_list_campaign_folders(
        self,
        config: MailchimpListCampaignFoldersConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """List all campaign folders."""
        endpoint = "campaign-folders"
        params = {"count": config.count, "offset": config.offset}
        result = await self._make_request(
            "GET",
            endpoint,
            credentials,
            params=params,
            action_name="list_campaign_folders",
        )

        # Format for table display
        if result["status"] == "success" and "folders" in result["data"]:
            folders_data = result["data"]["folders"]
            formatted_folders = [
                {
                    "id": folder.get("id"),
                    "name": folder.get("name"),
                    "count": folder.get("count", 0),
                }
                for folder in folders_data
            ]
            result["data"]["folders_formatted"] = formatted_folders

        return result

    async def _handle_get_campaign_folder(
        self, config: MailchimpGetCampaignFolderConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get a specific campaign folder."""
        endpoint = f"campaign-folders/{config.folder_id}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_campaign_folder"
        )

    async def _handle_create_campaign_folder(
        self,
        config: MailchimpCreateCampaignFolderConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Create a campaign folder."""
        endpoint = "campaign-folders"
        body = {"name": config.name}
        return await self._make_request(
            "POST",
            endpoint,
            credentials,
            json_body=body,
            action_name="create_campaign_folder",
        )

    async def _handle_update_campaign_folder(
        self,
        config: MailchimpUpdateCampaignFolderConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Update a campaign folder."""
        endpoint = f"campaign-folders/{config.folder_id}"
        body = {"name": config.name}
        return await self._make_request(
            "PATCH",
            endpoint,
            credentials,
            json_body=body,
            action_name="update_campaign_folder",
        )

    async def _handle_delete_campaign_folder(
        self,
        config: MailchimpDeleteCampaignFolderConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Delete a campaign folder."""
        endpoint = f"campaign-folders/{config.folder_id}"
        return await self._make_request(
            "DELETE", endpoint, credentials, action_name="delete_campaign_folder"
        )

    # ============================================================================
    # Template Folders Handlers
    # ============================================================================

    async def _handle_list_template_folders(
        self,
        config: MailchimpListTemplateFoldersConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """List all template folders."""
        endpoint = "template-folders"
        params = {"count": config.count, "offset": config.offset}
        result = await self._make_request(
            "GET",
            endpoint,
            credentials,
            params=params,
            action_name="list_template_folders",
        )

        # Format for table display
        if result["status"] == "success" and "folders" in result["data"]:
            folders_data = result["data"]["folders"]
            formatted_folders = [
                {
                    "id": folder.get("id"),
                    "name": folder.get("name"),
                    "count": folder.get("count", 0),
                }
                for folder in folders_data
            ]
            result["data"]["folders_formatted"] = formatted_folders

        return result

    async def _handle_get_template_folder(
        self, config: MailchimpGetTemplateFolderConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get a specific template folder."""
        endpoint = f"template-folders/{config.folder_id}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_template_folder"
        )

    async def _handle_create_template_folder(
        self,
        config: MailchimpCreateTemplateFolderConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Create a template folder."""
        endpoint = "template-folders"
        body = {"name": config.name}
        return await self._make_request(
            "POST",
            endpoint,
            credentials,
            json_body=body,
            action_name="create_template_folder",
        )

    async def _handle_update_template_folder(
        self,
        config: MailchimpUpdateTemplateFolderConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Update a template folder."""
        endpoint = f"template-folders/{config.folder_id}"
        body = {"name": config.name}
        return await self._make_request(
            "PATCH",
            endpoint,
            credentials,
            json_body=body,
            action_name="update_template_folder",
        )

    async def _handle_delete_template_folder(
        self,
        config: MailchimpDeleteTemplateFolderConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Delete a template folder."""
        endpoint = f"template-folders/{config.folder_id}"
        return await self._make_request(
            "DELETE", endpoint, credentials, action_name="delete_template_folder"
        )

    # ============================================================================
    # Account/Root Operations Handlers
    # ============================================================================

    async def _handle_get_account_info(
        self, config: MailchimpGetAccountInfoConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get account information."""
        endpoint = ""
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_account_info"
        )

    async def _handle_list_authorized_apps(
        self,
        config: MailchimpListAuthorizedAppsConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """List all authorized apps."""
        endpoint = "authorized-apps"
        params = {"count": config.count, "offset": config.offset}
        result = await self._make_request(
            "GET",
            endpoint,
            credentials,
            params=params,
            action_name="list_authorized_apps",
        )

        # Format for table display
        if result["status"] == "success" and "apps" in result["data"]:
            apps_data = result["data"]["apps"]
            formatted_apps = [
                {
                    "id": app.get("id"),
                    "name": app.get("name"),
                    "description": app.get("description"),
                    "users": app.get("users"),
                }
                for app in apps_data
            ]
            result["data"]["apps_formatted"] = formatted_apps

        return result

    async def _handle_get_authorized_app(
        self, config: MailchimpGetAuthorizedAppConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get details about a specific authorized app."""
        endpoint = f"authorized-apps/{config.app_id}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_authorized_app"
        )

    async def _handle_disconnect_authorized_app(
        self,
        config: MailchimpDisconnectAuthorizedAppConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Disconnect an authorized app."""
        endpoint = f"authorized-apps/{config.app_id}"
        return await self._make_request(
            "DELETE", endpoint, credentials, action_name="disconnect_authorized_app"
        )

    async def _handle_ping(
        self, config: MailchimpPingConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Ping the Mailchimp API."""
        endpoint = "ping"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="ping_api_connection"
        )

    # ============================================================================
    # Additional API Operations Handlers (115 new endpoints)
    # ============================================================================

    async def _handle_get_root(
        self, config: MailchimpGetRootConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get API root information."""
        endpoint = ""
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_api_root_info"
        )

    async def _handle_get_chimp_chatter(
        self, config: MailchimpGetChimpChatterConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get recent activity feed (Chimp Chatter)."""
        endpoint = "activity-feed/chimp-chatter"
        params = {}
        if hasattr(config, "count"):
            params["count"] = config.count
        return await self._make_request(
            "GET", endpoint, credentials, params=params, action_name="fetch_activity_feed"
        )

    async def _handle_list_audiences_v2(
        self, config: MailchimpListAudiencesV2Config, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """List all audiences (v2 contacts API)."""
        endpoint = "lists"
        params = {}
        if hasattr(config, "count"):
            params["count"] = config.count
        if hasattr(config, "offset"):
            params["offset"] = config.offset
        return await self._make_request(
            "GET", endpoint, credentials, params=params, action_name="list_audiences"
        )

    async def _handle_create_audience_v2(
        self, config: MailchimpCreateAudienceV2Config, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Create a new audience (v2 contacts API)."""
        endpoint = "lists"
        body = {}
        if hasattr(config, "name") and config.name is not None:
            body["name"] = config.name
        if (
            hasattr(config, "permission_reminder")
            and config.permission_reminder is not None
        ):
            body["permission_reminder"] = config.permission_reminder
        if (
            hasattr(config, "email_type_option")
            and config.email_type_option is not None
        ):
            body["email_type_option"] = config.email_type_option
        if hasattr(config, "contact") and config.contact is not None:
            body["contact"] = config.contact
        return await self._make_request(
            "POST",
            endpoint,
            credentials,
            json_body=body,
            action_name="create_audience",
        )

    async def _handle_get_audience_v2(
        self, config: MailchimpGetAudienceV2Config, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get information about a specific audience."""
        endpoint = f"lists/{config.list_id}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_audience"
        )

    async def _handle_update_audience_v2(
        self, config: MailchimpUpdateAudienceV2Config, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Update settings for an audience."""
        endpoint = f"lists/{config.list_id}"
        body = {}
        if hasattr(config, "name") and config.name is not None:
            body["name"] = config.name
        return await self._make_request(
            "PATCH",
            endpoint,
            credentials,
            json_body=body,
            action_name="update_audience_settings",
        )

    async def _handle_delete_audience_v2(
        self, config: MailchimpDeleteAudienceV2Config, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Delete an audience."""
        endpoint = f"lists/{config.list_id}"
        return await self._make_request(
            "DELETE", endpoint, credentials, action_name="delete_audience"
        )

    async def _handle_list_contacts(
        self, config: MailchimpListContactsConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """List all contacts in an audience."""
        endpoint = f"lists/{config.list_id}/members"
        params = {}
        if hasattr(config, "count"):
            params["count"] = config.count
        if hasattr(config, "offset"):
            params["offset"] = config.offset
        return await self._make_request(
            "GET", endpoint, credentials, params=params, action_name="list_audience_contacts"
        )

    async def _handle_create_contact(
        self, config: MailchimpCreateContactConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Add a new contact to an audience."""
        endpoint = f"lists/{config.list_id}/members"
        body = {}
        if hasattr(config, "status") and config.status is not None:
            body["status"] = config.status
        return await self._make_request(
            "POST", endpoint, credentials, json_body=body, action_name="create_audience_contact"
        )

    async def _handle_get_contact(
        self, config: MailchimpGetContactConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get information about a specific contact."""
        subscriber_hash = get_subscriber_hash(config.email_address)
        endpoint = f"lists/{config.list_id}/members/{subscriber_hash}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_audience_contact"
        )

    async def _handle_update_contact(
        self, config: MailchimpUpdateContactConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Update a contact in an audience."""
        subscriber_hash = get_subscriber_hash(config.email_address)
        endpoint = f"lists/{config.list_id}/members/{subscriber_hash}"
        body = {}
        if hasattr(config, "status") and config.status is not None:
            body["status"] = config.status
        return await self._make_request(
            "PATCH", endpoint, credentials, json_body=body, action_name="update_audience_contact"
        )

    async def _handle_archive_contact(
        self, config: MailchimpArchiveContactConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Archive a contact in an audience."""
        subscriber_hash = get_subscriber_hash(config.email_address)
        endpoint = f"lists/{config.list_id}/members/{subscriber_hash}"
        return await self._make_request(
            "DELETE", endpoint, credentials, action_name="archive_list_contact"
        )

    async def _handle_forget_contact(
        self, config: MailchimpForgetContactConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Delete all personally identifiable information for a contact."""
        subscriber_hash = get_subscriber_hash(config.email_address)
        endpoint = (
            f"lists/{config.list_id}/members/{subscriber_hash}/actions/delete-permanent"
        )
        return await self._make_request(
            "POST", endpoint, credentials, action_name="permanently_delete_contact_data"
        )

    async def _handle_list_automation_emails(
        self,
        config: MailchimpListAutomationEmailsConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """List all automation emails for a workflow."""
        endpoint = f"automations/{config.workflow_id}/emails"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="list_automation_emails"
        )

    async def _handle_get_automation_email(
        self,
        config: MailchimpGetAutomationEmailConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get information about a specific automation email."""
        endpoint = f"automations/{config.workflow_id}/emails/{config.email_id}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_automation_email"
        )

    async def _handle_start_automation_email(
        self,
        config: MailchimpStartAutomationEmailConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Start an automation email."""
        endpoint = (
            f"automations/{config.workflow_id}/emails/{config.email_id}/actions/start"
        )
        return await self._make_request(
            "POST", endpoint, credentials, action_name="start_automation_email"
        )

    async def _handle_pause_automation_email(
        self,
        config: MailchimpPauseAutomationEmailConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Pause an automation email."""
        endpoint = (
            f"automations/{config.workflow_id}/emails/{config.email_id}/actions/pause"
        )
        return await self._make_request(
            "POST", endpoint, credentials, action_name="pause_automation_email"
        )

    async def _handle_list_automation_queue(
        self,
        config: MailchimpListAutomationQueueConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """List all subscribers in automation email queue."""
        endpoint = f"automations/{config.workflow_id}/emails/{config.email_id}/queue"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="list_automation_queue_members"
        )

    async def _handle_get_automation_queue_member(
        self,
        config: MailchimpGetAutomationQueueMemberConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get information about a specific subscriber in automation queue."""
        subscriber_hash = get_subscriber_hash(config.email_address)
        endpoint = f"automations/{config.workflow_id}/emails/{config.email_id}/queue/{subscriber_hash}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_automation_queue_member"
        )

    async def _handle_list_automation_removed(
        self,
        config: MailchimpListAutomationRemovedConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """List subscribers removed from automation workflow."""
        endpoint = f"automations/{config.workflow_id}/removed-subscribers"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="list_automation_removed_members"
        )

    async def _handle_get_automation_removed(
        self,
        config: MailchimpGetAutomationRemovedConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get information about a removed subscriber."""
        subscriber_hash = get_subscriber_hash(config.email_address)
        endpoint = (
            f"automations/{config.workflow_id}/removed-subscribers/{subscriber_hash}"
        )
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_automation_removed_member"
        )

    async def _handle_add_automation_removed(
        self,
        config: MailchimpAddAutomationRemovedConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Remove a subscriber from an automation workflow."""
        endpoint = f"automations/{config.workflow_id}/removed-subscribers"
        return await self._make_request(
            "POST", endpoint, credentials, action_name="remove_member_from_automation"
        )

    async def _handle_list_batch_webhooks(
        self, config: MailchimpListBatchWebhooksConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """List all batch webhooks."""
        endpoint = "batch-webhooks"
        params = {}
        if hasattr(config, "count"):
            params["count"] = config.count
        if hasattr(config, "offset"):
            params["offset"] = config.offset
        return await self._make_request(
            "GET",
            endpoint,
            credentials,
            params=params,
            action_name="list_batch_webhooks",
        )

    async def _handle_create_batch_webhook(
        self,
        config: MailchimpCreateBatchWebhookConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Create a new batch webhook."""
        endpoint = "batch-webhooks"
        body = {}
        if hasattr(config, "url") and config.url is not None:
            body["url"] = config.url
        return await self._make_request(
            "POST",
            endpoint,
            credentials,
            json_body=body,
            action_name="create_batch_webhook",
        )

    async def _handle_get_batch_webhook(
        self, config: MailchimpGetBatchWebhookConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get information about a specific batch webhook."""
        endpoint = f"batch-webhooks/{config.webhook_id}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_batch_webhook"
        )

    async def _handle_delete_batch_webhook(
        self,
        config: MailchimpDeleteBatchWebhookConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Delete a batch webhook."""
        endpoint = f"batch-webhooks/{config.webhook_id}"
        return await self._make_request(
            "DELETE", endpoint, credentials, action_name="delete_batch_webhook"
        )

    async def _handle_cancel_send_campaign(
        self,
        config: MailchimpCancelSendCampaignConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Cancel a scheduled campaign."""
        endpoint = f"campaigns/{config.campaign_id}/actions/cancel-send"
        return await self._make_request(
            "POST", endpoint, credentials, action_name="cancel_campaign_send"
        )

    async def _handle_pause_campaign(
        self, config: MailchimpPauseCampaignConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Pause an RSS-Driven campaign."""
        endpoint = f"campaigns/{config.campaign_id}/actions/pause"
        return await self._make_request(
            "POST", endpoint, credentials, action_name="pause_rss_campaign"
        )

    async def _handle_resume_campaign(
        self, config: MailchimpResumeCampaignConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Resume an RSS-Driven campaign."""
        endpoint = f"campaigns/{config.campaign_id}/actions/resume"
        return await self._make_request(
            "POST", endpoint, credentials, action_name="resume_rss_campaign"
        )

    async def _handle_create_resend_campaign(
        self,
        config: MailchimpCreateResendCampaignConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Create a resend to non-openers."""
        endpoint = f"campaigns/{config.campaign_id}/actions/create-resend"
        return await self._make_request(
            "POST", endpoint, credentials, action_name="create_campaign_resend"
        )

    async def _handle_list_campaign_feedback(
        self,
        config: MailchimpListCampaignFeedbackConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """List feedback for a campaign."""
        endpoint = f"campaigns/{config.campaign_id}/feedback"
        params = {}
        if hasattr(config, "count"):
            params["count"] = config.count
        if hasattr(config, "offset"):
            params["offset"] = config.offset
        return await self._make_request(
            "GET",
            endpoint,
            credentials,
            params=params,
            action_name="list_campaign_feedback",
        )

    async def _handle_create_campaign_feedback(
        self,
        config: MailchimpCreateCampaignFeedbackConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Add feedback to a campaign."""
        endpoint = f"campaigns/{config.campaign_id}/feedback"
        body = {}
        if hasattr(config, "message") and config.message is not None:
            body["message"] = config.message
        if hasattr(config, "block_id") and config.block_id is not None:
            body["block_id"] = config.block_id
        return await self._make_request(
            "POST",
            endpoint,
            credentials,
            json_body=body,
            action_name="add_campaign_feedback",
        )

    async def _handle_get_campaign_feedback(
        self,
        config: MailchimpGetCampaignFeedbackConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get specific campaign feedback."""
        endpoint = f"campaigns/{config.campaign_id}/feedback/{config.feedback_id}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_campaign_feedback"
        )

    async def _handle_delete_campaign_feedback(
        self,
        config: MailchimpDeleteCampaignFeedbackConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Delete campaign feedback."""
        endpoint = f"campaigns/{config.campaign_id}/feedback/{config.feedback_id}"
        return await self._make_request(
            "DELETE", endpoint, credentials, action_name="delete_campaign_feedback"
        )

    async def _handle_get_campaign_checklist(
        self,
        config: MailchimpGetCampaignChecklistConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get send checklist for a campaign."""
        endpoint = f"campaigns/{config.campaign_id}/send-checklist"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_campaign_checklist"
        )

    async def _handle_list_connected_sites(
        self,
        config: MailchimpListConnectedSitesConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """List all connected sites."""
        endpoint = "connected-sites"
        params = {}
        if hasattr(config, "count"):
            params["count"] = config.count
        if hasattr(config, "offset"):
            params["offset"] = config.offset
        return await self._make_request(
            "GET",
            endpoint,
            credentials,
            params=params,
            action_name="list_connected_sites",
        )

    async def _handle_create_connected_site(
        self,
        config: MailchimpCreateConnectedSiteConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Create a new connected site."""
        endpoint = "connected-sites"
        body = {}
        if hasattr(config, "foreign_id") and config.foreign_id is not None:
            body["foreign_id"] = config.foreign_id
        if hasattr(config, "domain") and config.domain is not None:
            body["domain"] = config.domain
        return await self._make_request(
            "POST",
            endpoint,
            credentials,
            json_body=body,
            action_name="create_connected_site",
        )

    async def _handle_get_connected_site(
        self, config: MailchimpGetConnectedSiteConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get information about a specific connected site."""
        endpoint = f"connected-sites/{config.site_id}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_connected_site"
        )

    async def _handle_update_connected_site(
        self,
        config: MailchimpUpdateConnectedSiteConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Update a connected site."""
        endpoint = f"connected-sites/{config.site_id}"
        body = {}
        if hasattr(config, "domain") and config.domain is not None:
            body["domain"] = config.domain
        return await self._make_request(
            "PATCH",
            endpoint,
            credentials,
            json_body=body,
            action_name="update_connected_site",
        )

    async def _handle_verify_script_installation(
        self,
        config: MailchimpVerifyScriptInstallationConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Verify connected site script installation."""
        endpoint = (
            f"connected-sites/{config.site_id}/actions/verify-script-installation"
        )
        return await self._make_request(
            "POST", endpoint, credentials, action_name="verify_connected_site_script"
        )

    async def _handle_delete_connected_site(
        self,
        config: MailchimpDeleteConnectedSiteConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Delete a connected site."""
        endpoint = f"connected-sites/{config.site_id}"
        return await self._make_request(
            "DELETE", endpoint, credentials, action_name="delete_connected_site"
        )

    async def _handle_list_conversations(
        self, config: MailchimpListConversationsConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """List all conversations."""
        endpoint = "conversations"
        params = {}
        if hasattr(config, "count"):
            params["count"] = config.count
        if hasattr(config, "offset"):
            params["offset"] = config.offset
        return await self._make_request(
            "GET",
            endpoint,
            credentials,
            params=params,
            action_name="list_conversations",
        )

    async def _handle_get_conversation(
        self, config: MailchimpGetConversationConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get information about a specific conversation."""
        endpoint = f"conversations/{config.conversation_id}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_conversation"
        )

    async def _handle_list_conversation_messages(
        self,
        config: MailchimpListConversationMessagesConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """List all messages in a conversation."""
        endpoint = f"conversations/{config.conversation_id}/messages"
        params = {}
        if hasattr(config, "count"):
            params["count"] = config.count
        if hasattr(config, "offset"):
            params["offset"] = config.offset
        return await self._make_request(
            "GET",
            endpoint,
            credentials,
            params=params,
            action_name="list_conversation_messages",
        )

    async def _handle_create_conversation_message(
        self,
        config: MailchimpCreateConversationMessageConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Add a message to a conversation."""
        endpoint = f"conversations/{config.conversation_id}/messages"
        body = {}
        if hasattr(config, "from_email") and config.from_email is not None:
            body["from_email"] = config.from_email
        if hasattr(config, "read") and config.read is not None:
            body["read"] = config.read
        return await self._make_request(
            "POST",
            endpoint,
            credentials,
            json_body=body,
            action_name="post_conversation_message",
        )

    async def _handle_get_conversation_message(
        self,
        config: MailchimpGetConversationMessageConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get a specific conversation message."""
        endpoint = (
            f"conversations/{config.conversation_id}/messages/{config.message_id}"
        )
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_conversation_message"
        )

    async def _handle_trigger_customer_journey_step(
        self,
        config: MailchimpTriggerCustomerJourneyStepConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Trigger a step in a customer journey."""
        endpoint = f"customer-journeys/journeys/{config.journey_id}/steps/{config.step_id}/actions/trigger"
        return await self._make_request(
            "POST", endpoint, credentials, action_name="trigger_customer_journey_step"
        )

    async def _handle_list_folder_files(
        self, config: MailchimpListFolderFilesConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """List all files in a folder."""
        endpoint = f"file-manager/folders/{config.folder_id}/files"
        params = {}
        if hasattr(config, "count"):
            params["count"] = config.count
        if hasattr(config, "offset"):
            params["offset"] = config.offset
        return await self._make_request(
            "GET", endpoint, credentials, params=params, action_name="list_files_in_folder"
        )

    async def _handle_get_landing_page_content(
        self,
        config: MailchimpGetLandingPageContentConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get landing page content."""
        endpoint = f"landing-pages/{config.page_id}/content"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_landing_page_content"
        )

    async def _handle_update_landing_page_content(
        self,
        config: MailchimpUpdateLandingPageContentConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Update landing page content."""
        endpoint = f"landing-pages/{config.page_id}/content"
        body = {}
        if hasattr(config, "html") and config.html is not None:
            body["html"] = config.html
        return await self._make_request(
            "POST",
            endpoint,
            credentials,
            json_body=body,
            action_name="update_landing_page_html",
        )

    async def _handle_publish_landing_page(
        self,
        config: MailchimpPublishLandingPageConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Publish a landing page."""
        endpoint = f"landing-pages/{config.page_id}/actions/publish"
        return await self._make_request(
            "POST", endpoint, credentials, action_name="publish_landing_page"
        )

    async def _handle_unpublish_landing_page(
        self,
        config: MailchimpUnpublishLandingPageConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Unpublish a landing page."""
        endpoint = f"landing-pages/{config.page_id}/actions/unpublish"
        return await self._make_request(
            "POST", endpoint, credentials, action_name="unpublish_landing_page"
        )

    async def _handle_list_abuse_reports(
        self, config: MailchimpListAbuseReportsConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get abuse reports for a list."""
        endpoint = f"lists/{config.list_id}/abuse-reports"
        params = {}
        if hasattr(config, "count"):
            params["count"] = config.count
        if hasattr(config, "offset"):
            params["offset"] = config.offset
        return await self._make_request(
            "GET",
            endpoint,
            credentials,
            params=params,
            action_name="list_abuse_reports",
        )

    async def _handle_get_abuse_report(
        self, config: MailchimpGetAbuseReportConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get a specific abuse report."""
        endpoint = f"lists/{config.list_id}/abuse-reports/{config.report_id}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_abuse_report"
        )

    async def _handle_get_list_activity(
        self, config: MailchimpGetListActivityConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get recent activity for a list."""
        endpoint = f"lists/{config.list_id}/activity"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_list_activity"
        )

    async def _handle_get_list_clients(
        self, config: MailchimpGetListClientsConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get top email clients for a list."""
        endpoint = f"lists/{config.list_id}/clients"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_list_email_clients"
        )

    async def _handle_list_growth_history(
        self, config: MailchimpListGrowthHistoryConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get growth history for a list."""
        endpoint = f"lists/{config.list_id}/growth-history"
        params = {}
        if hasattr(config, "count"):
            params["count"] = config.count
        if hasattr(config, "offset"):
            params["offset"] = config.offset
        return await self._make_request(
            "GET",
            endpoint,
            credentials,
            params=params,
            action_name="list_growth_history",
        )

    async def _handle_get_growth_history_month(
        self,
        config: MailchimpGetGrowthHistoryMonthConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get growth history for a specific month."""
        endpoint = f"lists/{config.list_id}/growth-history/{config.month}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_growth_history_for_month"
        )

    async def _handle_list_segment_members(
        self,
        config: MailchimpListSegmentMembersConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """List members in a segment."""
        endpoint = f"lists/{config.list_id}/segments/{config.segment_id}/members"
        params = {}
        if hasattr(config, "count"):
            params["count"] = config.count
        if hasattr(config, "offset"):
            params["offset"] = config.offset
        return await self._make_request(
            "GET",
            endpoint,
            credentials,
            params=params,
            action_name="list_segment_members",
        )

    async def _handle_create_segment_member(
        self,
        config: MailchimpCreateSegmentMemberConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Add a member to a static segment."""
        endpoint = f"lists/{config.list_id}/segments/{config.segment_id}/members"
        return await self._make_request(
            "POST", endpoint, credentials, action_name="add_member_to_segment"
        )

    async def _handle_get_segment_member(
        self, config: MailchimpGetSegmentMemberConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get information about a segment member."""
        subscriber_hash = get_subscriber_hash(config.email_address)
        endpoint = f"lists/{config.list_id}/segments/{config.segment_id}/members/{subscriber_hash}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_segment_member"
        )

    async def _handle_delete_segment_member(
        self,
        config: MailchimpDeleteSegmentMemberConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Remove a member from a static segment."""
        subscriber_hash = get_subscriber_hash(config.email_address)
        endpoint = f"lists/{config.list_id}/segments/{config.segment_id}/members/{subscriber_hash}"
        return await self._make_request(
            "DELETE", endpoint, credentials, action_name="remove_member_from_segment"
        )

    async def _handle_get_member_activity(
        self, config: MailchimpGetMemberActivityConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get recent activity for a list member."""
        subscriber_hash = get_subscriber_hash(config.email_address)
        endpoint = f"lists/{config.list_id}/members/{subscriber_hash}/activity"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_member_activity"
        )

    async def _handle_list_member_activity_feed(
        self,
        config: MailchimpListMemberActivityFeedConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get activity feed for a list member."""
        subscriber_hash = get_subscriber_hash(config.email_address)
        endpoint = f"lists/{config.list_id}/members/{subscriber_hash}/activity-feed"
        params = {}
        if hasattr(config, "count"):
            params["count"] = config.count
        if hasattr(config, "offset"):
            params["offset"] = config.offset
        return await self._make_request(
            "GET",
            endpoint,
            credentials,
            params=params,
            action_name="list_member_activity_feed",
        )

    async def _handle_get_member_goals(
        self, config: MailchimpGetMemberGoalsConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get goals for a list member."""
        subscriber_hash = get_subscriber_hash(config.email_address)
        endpoint = f"lists/{config.list_id}/members/{subscriber_hash}/goals"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_member_goals"
        )

    async def _handle_list_member_notes(
        self, config: MailchimpListMemberNotesConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get notes for a list member."""
        subscriber_hash = get_subscriber_hash(config.email_address)
        endpoint = f"lists/{config.list_id}/members/{subscriber_hash}/notes"
        params = {}
        if hasattr(config, "count"):
            params["count"] = config.count
        if hasattr(config, "offset"):
            params["offset"] = config.offset
        return await self._make_request(
            "GET", endpoint, credentials, params=params, action_name="list_member_notes"
        )

    async def _handle_create_member_note(
        self, config: MailchimpCreateMemberNoteConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Add a note to a list member."""
        subscriber_hash = get_subscriber_hash(config.email_address)
        endpoint = f"lists/{config.list_id}/members/{subscriber_hash}/notes"
        body = {}
        if hasattr(config, "note") and config.note is not None:
            body["note"] = config.note
        return await self._make_request(
            "POST",
            endpoint,
            credentials,
            json_body=body,
            action_name="add_member_note",
        )

    async def _handle_get_member_note(
        self, config: MailchimpGetMemberNoteConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get a specific member note."""
        subscriber_hash = get_subscriber_hash(config.email_address)
        endpoint = (
            f"lists/{config.list_id}/members/{subscriber_hash}/notes/{config.note_id}"
        )
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_member_note"
        )

    async def _handle_update_member_note(
        self, config: MailchimpUpdateMemberNoteConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Update a member note."""
        subscriber_hash = get_subscriber_hash(config.email_address)
        endpoint = (
            f"lists/{config.list_id}/members/{subscriber_hash}/notes/{config.note_id}"
        )
        body = {}
        if hasattr(config, "note") and config.note is not None:
            body["note"] = config.note
        return await self._make_request(
            "PATCH",
            endpoint,
            credentials,
            json_body=body,
            action_name="update_member_note",
        )

    async def _handle_delete_member_note(
        self, config: MailchimpDeleteMemberNoteConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Delete a member note."""
        subscriber_hash = get_subscriber_hash(config.email_address)
        endpoint = (
            f"lists/{config.list_id}/members/{subscriber_hash}/notes/{config.note_id}"
        )
        return await self._make_request(
            "DELETE", endpoint, credentials, action_name="delete_member_note"
        )

    async def _handle_create_member_event(
        self, config: MailchimpCreateMemberEventConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Add an event for a list member."""
        subscriber_hash = get_subscriber_hash(config.email_address)
        endpoint = f"lists/{config.list_id}/members/{subscriber_hash}/events"
        body = {}
        if hasattr(config, "name") and config.name is not None:
            body["name"] = config.name
        if hasattr(config, "properties") and config.properties is not None:
            body["properties"] = config.properties
        return await self._make_request(
            "POST",
            endpoint,
            credentials,
            json_body=body,
            action_name="create_member_event",
        )

    async def _handle_get_signup_forms(
        self, config: MailchimpGetSignupFormsConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get signup forms for a list."""
        endpoint = f"lists/{config.list_id}/signup-forms"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_signup_forms"
        )

    async def _handle_get_list_locations(
        self, config: MailchimpGetListLocationsConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get subscriber locations for a list."""
        endpoint = f"lists/{config.list_id}/locations"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_list_subscriber_locations"
        )

    async def _handle_list_surveys(
        self, config: MailchimpListSurveysConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """List all surveys for a list."""
        endpoint = f"lists/{config.list_id}/surveys"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="list_surveys"
        )

    async def _handle_create_survey(
        self, config: MailchimpCreateSurveyConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Create a new survey."""
        endpoint = f"lists/{config.list_id}/surveys"
        body = {}
        if hasattr(config, "title") and config.title is not None:
            body["title"] = config.title
        return await self._make_request(
            "POST", endpoint, credentials, json_body=body, action_name="create_survey"
        )

    async def _handle_get_survey(
        self, config: MailchimpGetSurveyConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get information about a specific survey."""
        endpoint = f"lists/{config.list_id}/surveys/{config.survey_id}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_survey"
        )

    async def _handle_update_survey(
        self, config: MailchimpUpdateSurveyConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Update a survey."""
        endpoint = f"lists/{config.list_id}/surveys/{config.survey_id}"
        body = {}
        if hasattr(config, "title") and config.title is not None:
            body["title"] = config.title
        return await self._make_request(
            "PATCH", endpoint, credentials, json_body=body, action_name="update_survey"
        )

    async def _handle_publish_survey(
        self, config: MailchimpPublishSurveyConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Publish a survey."""
        endpoint = f"lists/{config.list_id}/surveys/{config.survey_id}/actions/publish"
        return await self._make_request(
            "POST", endpoint, credentials, action_name="publish_survey"
        )

    async def _handle_unpublish_survey(
        self, config: MailchimpUnpublishSurveyConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Unpublish a survey."""
        endpoint = (
            f"lists/{config.list_id}/surveys/{config.survey_id}/actions/unpublish"
        )
        return await self._make_request(
            "POST", endpoint, credentials, action_name="unpublish_survey"
        )

    async def _handle_create_survey_email(
        self, config: MailchimpCreateSurveyEmailConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Send a survey email."""
        endpoint = (
            f"lists/{config.list_id}/surveys/{config.survey_id}/actions/create-email"
        )
        body = {}
        if hasattr(config, "subject_line") and config.subject_line is not None:
            body["subject_line"] = config.subject_line
        return await self._make_request(
            "POST",
            endpoint,
            credentials,
            json_body=body,
            action_name="send_survey_email",
        )

    async def _handle_delete_survey(
        self, config: MailchimpDeleteSurveyConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Delete a survey."""
        endpoint = f"lists/{config.list_id}/surveys/{config.survey_id}"
        return await self._make_request(
            "DELETE", endpoint, credentials, action_name="delete_survey"
        )

    async def _handle_get_campaign_sub_reports(
        self,
        config: MailchimpGetCampaignSubReportsConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get sub-reports for a campaign."""
        endpoint = f"reports/{config.campaign_id}/sub-reports"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_campaign_subreports"
        )

    async def _handle_get_campaign_advice(
        self, config: MailchimpGetCampaignAdviceConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get advice for improving a campaign."""
        endpoint = f"campaigns/{config.campaign_id}/advice"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_campaign_advice"
        )

    async def _handle_get_ecommerce_product_activity_report(
        self,
        config: MailchimpGetEcommerceProductActivityReportConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get product activity report."""
        endpoint = f"reports/{config.campaign_id}/ecommerce-product-activity"
        return await self._make_request(
            "GET",
            endpoint,
            credentials,
            action_name="fetch_product_activity_report",
        )

    async def _handle_get_template_default_content(
        self,
        config: MailchimpGetTemplateDefaultContentConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get default content for a template."""
        endpoint = f"templates/{config.template_id}/default-content"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_template_default_content"
        )

    async def _handle_update_template_default_content(
        self,
        config: MailchimpUpdateTemplateDefaultContentConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Update default content for a template."""
        endpoint = f"templates/{config.template_id}/default-content"
        body = {}
        if hasattr(config, "sections") and config.sections is not None:
            body["sections"] = config.sections
        return await self._make_request(
            "PUT",
            endpoint,
            credentials,
            json_body=body,
            action_name="update_template_default_content",
        )

    async def _handle_get_order_line(
        self, config: MailchimpGetOrderLineConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get information about a specific order line."""
        endpoint = f"ecommerce/stores/{config.store_id}/orders/{config.order_id}/lines/{config.line_id}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_order_line_item"
        )

    async def _handle_update_order_line(
        self, config: MailchimpUpdateOrderLineConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Update an order line."""
        endpoint = f"ecommerce/stores/{config.store_id}/orders/{config.order_id}/lines/{config.line_id}"
        body = {}
        if hasattr(config, "quantity") and config.quantity is not None:
            body["quantity"] = config.quantity
        return await self._make_request(
            "PATCH",
            endpoint,
            credentials,
            json_body=body,
            action_name="update_order_line_item",
        )

    async def _handle_delete_order_line(
        self, config: MailchimpDeleteOrderLineConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Delete an order line."""
        endpoint = f"ecommerce/stores/{config.store_id}/orders/{config.order_id}/lines/{config.line_id}"
        return await self._make_request(
            "DELETE", endpoint, credentials, action_name="delete_order_line_item"
        )

    async def _handle_get_cart_line(
        self, config: MailchimpGetCartLineConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get information about a specific cart line."""
        endpoint = f"ecommerce/stores/{config.store_id}/carts/{config.cart_id}/lines/{config.line_id}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_cart_line_item"
        )

    async def _handle_update_cart_line(
        self, config: MailchimpUpdateCartLineConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Update a cart line."""
        endpoint = f"ecommerce/stores/{config.store_id}/carts/{config.cart_id}/lines/{config.line_id}"
        body = {}
        if hasattr(config, "quantity") and config.quantity is not None:
            body["quantity"] = config.quantity
        return await self._make_request(
            "PATCH",
            endpoint,
            credentials,
            json_body=body,
            action_name="update_cart_line_item",
        )

    async def _handle_delete_cart_line(
        self, config: MailchimpDeleteCartLineConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Delete a cart line."""
        endpoint = f"ecommerce/stores/{config.store_id}/carts/{config.cart_id}/lines/{config.line_id}"
        return await self._make_request(
            "DELETE", endpoint, credentials, action_name="delete_cart_line_item"
        )

    async def _handle_list_all_ecommerce_orders(
        self,
        config: MailchimpListAllEcommerceOrdersConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """List all orders across all stores."""
        endpoint = "ecommerce/orders"
        params = {}
        if hasattr(config, "count"):
            params["count"] = config.count
        if hasattr(config, "offset"):
            params["offset"] = config.offset
        return await self._make_request(
            "GET",
            endpoint,
            credentials,
            params=params,
            action_name="list_all_ecommerce_orders",
        )

    async def _handle_list_facebook_ads(
        self, config: MailchimpListFacebookAdsConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """List all Facebook ads."""
        endpoint = "facebook-ads"
        params = {}
        if hasattr(config, "count"):
            params["count"] = config.count
        if hasattr(config, "offset"):
            params["offset"] = config.offset
        return await self._make_request(
            "GET", endpoint, credentials, params=params, action_name="list_facebook_ads"
        )

    async def _handle_get_facebook_ad(
        self, config: MailchimpGetFacebookAdConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get information about a specific Facebook ad."""
        endpoint = f"facebook-ads/{config.ad_id}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_facebook_ad"
        )

    async def _handle_search_campaigns(
        self, config: MailchimpSearchCampaignsConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Search for campaigns."""
        endpoint = "search-campaigns"
        params = {}
        if hasattr(config, "query"):
            params["query"] = config.query
        return await self._make_request(
            "GET", endpoint, credentials, params=params, action_name="search_campaigns_by_name"
        )

    async def _handle_search_members(
        self, config: MailchimpSearchMembersConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Search for list members."""
        endpoint = "search-members"
        params = {"query": config.query}
        if config.list_id:
            params["list_id"] = config.list_id
        return await self._make_request(
            "GET", endpoint, credentials, params=params, action_name="search_list_members"
        )

    async def _handle_list_facebook_ad_reports(
        self,
        config: MailchimpListFacebookAdReportsConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """List Facebook ad reports."""
        endpoint = "reports/facebook-ads"
        params = {}
        if hasattr(config, "count"):
            params["count"] = config.count
        if hasattr(config, "offset"):
            params["offset"] = config.offset
        return await self._make_request(
            "GET",
            endpoint,
            credentials,
            params=params,
            action_name="list_facebook_ad_reports",
        )

    async def _handle_get_facebook_ad_report(
        self,
        config: MailchimpGetFacebookAdReportConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get a specific Facebook ad report."""
        endpoint = f"reports/facebook-ads/{config.ad_id}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_facebook_ad_report"
        )

    async def _handle_get_facebook_ad_ecommerce_activity(
        self,
        config: MailchimpGetFacebookAdEcommerceActivityConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get e-commerce activity for a Facebook ad."""
        endpoint = f"reports/facebook-ads/{config.ad_id}/ecommerce-product-activity"
        return await self._make_request(
            "GET",
            endpoint,
            credentials,
            action_name="fetch_facebook_ad_ecommerce_activity",
        )

    async def _handle_list_landing_page_reports(
        self,
        config: MailchimpListLandingPageReportsConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """List landing page reports."""
        endpoint = "reports/landing-pages"
        params = {}
        if hasattr(config, "count"):
            params["count"] = config.count
        if hasattr(config, "offset"):
            params["offset"] = config.offset
        return await self._make_request(
            "GET",
            endpoint,
            credentials,
            params=params,
            action_name="list_landing_page_reports",
        )

    async def _handle_get_landing_page_report(
        self,
        config: MailchimpGetLandingPageReportConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get a specific landing page report."""
        endpoint = f"reports/landing-pages/{config.page_id}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_landing_page_report"
        )

    async def _handle_list_survey_reports(
        self, config: MailchimpListSurveyReportsConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """List survey reports."""
        endpoint = "reporting/surveys"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="list_survey_reports"
        )

    async def _handle_get_survey_report(
        self, config: MailchimpGetSurveyReportConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get a specific survey report."""
        endpoint = f"reporting/surveys/{config.survey_id}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_survey_report"
        )

    async def _handle_list_survey_questions(
        self,
        config: MailchimpListSurveyQuestionsConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """List all questions in a survey."""
        endpoint = f"reporting/surveys/{config.survey_id}/questions"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="list_survey_questions"
        )

    async def _handle_get_survey_question(
        self, config: MailchimpGetSurveyQuestionConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get information about a specific survey question."""
        endpoint = (
            f"reporting/surveys/{config.survey_id}/questions/{config.question_id}"
        )
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_survey_question"
        )

    async def _handle_list_survey_answers(
        self, config: MailchimpListSurveyAnswersConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """List all answers for a survey question."""
        endpoint = f"reporting/surveys/{config.survey_id}/questions/{config.question_id}/answers"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="list_survey_question_answers"
        )

    async def _handle_list_survey_responses(
        self,
        config: MailchimpListSurveyResponsesConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """List all responses to a survey."""
        endpoint = f"reporting/surveys/{config.survey_id}/responses"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="list_survey_responses"
        )

    async def _handle_get_survey_response(
        self, config: MailchimpGetSurveyResponseConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get a specific survey response."""
        endpoint = (
            f"reporting/surveys/{config.survey_id}/responses/{config.response_id}"
        )
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_survey_response"
        )

    async def _handle_list_verified_domains(
        self,
        config: MailchimpListVerifiedDomainsConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """List all verified domains."""
        endpoint = "verified-domains"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="list_verified_domains"
        )

    async def _handle_create_verified_domain(
        self,
        config: MailchimpCreateVerifiedDomainConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Add a domain to verify."""
        endpoint = "verified-domains"
        body = {}
        if hasattr(config, "domain") and config.domain is not None:
            body["domain"] = config.domain
        return await self._make_request(
            "POST",
            endpoint,
            credentials,
            json_body=body,
            action_name="add_domain_for_verification",
        )

    async def _handle_get_verified_domain(
        self, config: MailchimpGetVerifiedDomainConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get information about a verified domain."""
        endpoint = f"verified-domains/{config.domain_name}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_verified_domain"
        )

    async def _handle_update_verified_domain(
        self,
        config: MailchimpUpdateVerifiedDomainConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Update a verified domain."""
        endpoint = f"verified-domains/{config.domain_name}"
        return await self._make_request(
            "PUT", endpoint, credentials, action_name="update_verified_domain"
        )

    async def _handle_delete_verified_domain(
        self,
        config: MailchimpDeleteVerifiedDomainConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Delete a verified domain."""
        endpoint = f"verified-domains/{config.domain_name}"
        return await self._make_request(
            "DELETE", endpoint, credentials, action_name="delete_verified_domain"
        )

    async def _handle_verify_domain(
        self, config: MailchimpVerifyDomainConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Verify a domain for sending."""
        endpoint = f"verified-domains/{config.domain_name}/actions/verify"
        return await self._make_request(
            "POST", endpoint, credentials, action_name="verify_domain_for_sending"
        )

    # ============================================================================
    # Account Exports Handlers
    # ============================================================================

    async def _handle_list_account_exports(
        self,
        config: MailchimpListAccountExportsConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """List account exports."""
        endpoint = "account-exports"
        params = {"count": config.count, "offset": config.offset}
        return await self._make_request(
            "GET",
            endpoint,
            credentials,
            params=params,
            action_name="list_account_exports",
        )

    async def _handle_create_account_export(
        self,
        config: MailchimpCreateAccountExportConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Create a new account export."""
        endpoint = "account-exports"
        body = {}
        if config.include_stages:
            body["include_stages"] = config.include_stages
        if config.since_timestamp:
            body["since_timestamp"] = config.since_timestamp
        return await self._make_request(
            "POST",
            endpoint,
            credentials,
            json_body=body,
            action_name="create_account_export",
        )

    async def _handle_get_account_export(
        self, config: MailchimpGetAccountExportConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get information about a specific account export."""
        endpoint = f"account-exports/{config.export_id}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_account_export"
        )

    # ============================================================================
    # Automation Archive Handler
    # ============================================================================

    async def _handle_archive_automation(
        self, config: MailchimpArchiveAutomationConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Archive an automation workflow."""
        endpoint = f"automations/{config.workflow_id}/actions/archive"
        return await self._make_request(
            "POST", endpoint, credentials, action_name="archive_automation_workflow"
        )

    # ============================================================================
    # Campaign Report Granular Member Handlers
    # ============================================================================

    async def _handle_get_campaign_click_detail_member(
        self,
        config: MailchimpGetCampaignClickDetailMemberConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get click details for a specific subscriber on a specific link."""
        endpoint = f"reports/{config.campaign_id}/click-details/{config.link_id}/members/{config.subscriber_hash}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_campaign_click_details_for_member"
        )

    async def _handle_get_campaign_sent_to_member(
        self,
        config: MailchimpGetCampaignSentToMemberConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get information about a specific subscriber in a sent-to report."""
        endpoint = f"reports/{config.campaign_id}/sent-to/{config.subscriber_hash}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_campaign_recipient_info"
        )

    async def _handle_get_campaign_unsubscribed_member(
        self,
        config: MailchimpGetCampaignUnsubscribedMemberConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get information about a specific unsubscribed member."""
        endpoint = f"reports/{config.campaign_id}/unsubscribed/{config.subscriber_hash}"
        return await self._make_request(
            "GET", endpoint, credentials, action_name="fetch_campaign_unsubscribed_member"
        )

    # ============================================================================
    # Conversation Message Handlers
    # ============================================================================

    async def _handle_update_conversation_message(
        self,
        config: MailchimpUpdateConversationMessageConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Update a conversation message."""
        endpoint = (
            f"conversations/{config.conversation_id}/messages/{config.message_id}"
        )
        body = {"read": config.read}
        return await self._make_request(
            "PATCH",
            endpoint,
            credentials,
            json_body=body,
            action_name="update_conversation_message",
        )

    async def _handle_delete_conversation_message(
        self,
        config: MailchimpDeleteConversationMessageConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Delete a conversation message."""
        endpoint = (
            f"conversations/{config.conversation_id}/messages/{config.message_id}"
        )
        return await self._make_request(
            "DELETE", endpoint, credentials, action_name="delete_conversation_message"
        )

    # ============================================================================
    # E-commerce Product Variant Delete Handler
    # ============================================================================

    async def _handle_delete_ecommerce_product_variant(
        self,
        config: MailchimpDeleteEcommerceProductVariantConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Delete a product variant."""
        endpoint = f"ecommerce/stores/{config.store_id}/products/{config.product_id}/variants/{config.variant_id}"
        return await self._make_request(
            "DELETE",
            endpoint,
            credentials,
            action_name="delete_product_variant",
        )

    # ============================================================================
    # Automation Email Queue POST Handler
    # ============================================================================

    async def _handle_add_automation_queue_member(
        self,
        config: MailchimpAddAutomationQueueMemberConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Add a subscriber to an automation email queue."""
        endpoint = (
            f"automations/{config.workflow_id}/emails/{config.workflow_email_id}/queue"
        )
        body = {"email_address": config.email_address}
        return await self._make_request(
            "POST",
            endpoint,
            credentials,
            json_body=body,
            action_name="add_member_to_automation_queue",
        )

    # ============================================================================
    # Mandrill/Transactional API Handlers (95 operations)
    # ============================================================================

    # Allowlists (3)
    async def _handle_mandrill_allowlists_add(
        self,
        config: MailchimpMandrillAllowlistsAddConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Add email to allowlist."""
        return await self._make_mandrill_request(
            "/allowlists/add", config, credentials, "add_email_to_allowlist"
        )

    async def _handle_mandrill_allowlists_list(
        self,
        config: MailchimpMandrillAllowlistsListConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """List allowlisted emails."""
        return await self._make_mandrill_request(
            "/allowlists/list", config, credentials, "list_allowlisted_emails"
        )

    async def _handle_mandrill_allowlists_delete(
        self,
        config: MailchimpMandrillAllowlistsDeleteConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Remove email from allowlist."""
        return await self._make_mandrill_request(
            "/allowlists/delete", config, credentials, "remove_email_from_allowlist"
        )

    # Exports (6)
    async def _handle_mandrill_exports_info(
        self,
        config: MailchimpMandrillExportsInfoConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """View export info."""
        return await self._make_mandrill_request(
            "/exports/info", config, credentials, "fetch_export_info"
        )

    async def _handle_mandrill_exports_list(
        self,
        config: MailchimpMandrillExportsListConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """List exports."""
        return await self._make_mandrill_request(
            "/exports/list", config, credentials, "list_exports"
        )

    async def _handle_mandrill_exports_rejects(
        self,
        config: MailchimpMandrillExportsRejectsConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Export denylist."""
        return await self._make_mandrill_request(
            "/exports/rejects", config, credentials, "export_denylist"
        )

    async def _handle_mandrill_exports_whitelist(
        self,
        config: MailchimpMandrillExportsWhitelistConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Export Allowlist."""
        return await self._make_mandrill_request(
            "/exports/whitelist", config, credentials, "export_whitelist"
        )

    async def _handle_mandrill_exports_allowlist(
        self,
        config: MailchimpMandrillExportsAllowlistConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Export Allowlist."""
        return await self._make_mandrill_request(
            "/exports/allowlist", config, credentials, "export_allowlist"
        )

    async def _handle_mandrill_exports_activity(
        self,
        config: MailchimpMandrillExportsActivityConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Export activity history."""
        return await self._make_mandrill_request(
            "/exports/activity", config, credentials, "export_activity_history"
        )

    # Inbound (9)
    async def _handle_mandrill_inbound_domains(
        self,
        config: MailchimpMandrillInboundDomainsConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """List inbound domains."""
        return await self._make_mandrill_request(
            "/inbound/domains", config, credentials, "list_inbound_domains"
        )

    async def _handle_mandrill_inbound_add_domain(
        self,
        config: MailchimpMandrillInboundAddDomainConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Add inbound domain."""
        return await self._make_mandrill_request(
            "/inbound/add-domain", config, credentials, "add_inbound_domain"
        )

    async def _handle_mandrill_inbound_check_domain(
        self,
        config: MailchimpMandrillInboundCheckDomainConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Check domain settings."""
        return await self._make_mandrill_request(
            "/inbound/check-domain",
            config,
            credentials,
            "verify_inbound_domain_settings",
        )

    async def _handle_mandrill_inbound_delete_domain(
        self,
        config: MailchimpMandrillInboundDeleteDomainConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Delete inbound domain."""
        return await self._make_mandrill_request(
            "/inbound/delete-domain",
            config,
            credentials,
            "delete_inbound_domain",
        )

    async def _handle_mandrill_inbound_routes(
        self,
        config: MailchimpMandrillInboundRoutesConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """List mailbox routes."""
        return await self._make_mandrill_request(
            "/inbound/routes", config, credentials, "list_mailbox_routes"
        )

    async def _handle_mandrill_inbound_add_route(
        self,
        config: MailchimpMandrillInboundAddRouteConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Add mailbox route."""
        return await self._make_mandrill_request(
            "/inbound/add-route", config, credentials, "add_mailbox_route"
        )

    async def _handle_mandrill_inbound_update_route(
        self,
        config: MailchimpMandrillInboundUpdateRouteConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Update mailbox route."""
        return await self._make_mandrill_request(
            "/inbound/update-route",
            config,
            credentials,
            "update_mailbox_route",
        )

    async def _handle_mandrill_inbound_delete_route(
        self,
        config: MailchimpMandrillInboundDeleteRouteConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Delete mailbox route."""
        return await self._make_mandrill_request(
            "/inbound/delete-route",
            config,
            credentials,
            "delete_mailbox_route",
        )

    async def _handle_mandrill_inbound_send_raw(
        self,
        config: MailchimpMandrillInboundSendRawConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Send mime document."""
        return await self._make_mandrill_request(
            "/inbound/send-raw", config, credentials, "send_raw_mime_message"
        )

    # IPs (13)
    async def _handle_mandrill_ips_list(
        self, config: MailchimpMandrillIpsListConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """List ip addresses."""
        return await self._make_mandrill_request(
            "/ips/list", config, credentials, "list_ip_addresses"
        )

    async def _handle_mandrill_ips_info(
        self, config: MailchimpMandrillIpsInfoConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get ip info."""
        return await self._make_mandrill_request(
            "/ips/info", config, credentials, "fetch_ip_info"
        )

    async def _handle_mandrill_ips_provision(
        self,
        config: MailchimpMandrillIpsProvisionConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Request additional ip."""
        return await self._make_mandrill_request(
            "/ips/provision", config, credentials, "request_additional_ip"
        )

    async def _handle_mandrill_ips_start_warmup(
        self,
        config: MailchimpMandrillIpsStartWarmupConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Start ip warmup."""
        return await self._make_mandrill_request(
            "/ips/start-warmup", config, credentials, "start_ip_warmup"
        )

    async def _handle_mandrill_ips_cancel_warmup(
        self,
        config: MailchimpMandrillIpsCancelWarmupConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Cancel ip warmup."""
        return await self._make_mandrill_request(
            "/ips/cancel-warmup", config, credentials, "cancel_ip_warmup"
        )

    async def _handle_mandrill_ips_set_pool(
        self,
        config: MailchimpMandrillIpsSetPoolConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Move ip to different pool."""
        return await self._make_mandrill_request(
            "/ips/set-pool", config, credentials, "move_ip_to_pool"
        )

    async def _handle_mandrill_ips_delete(
        self, config: MailchimpMandrillIpsDeleteConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Delete ip address."""
        return await self._make_mandrill_request(
            "/ips/delete", config, credentials, "delete_ip_address"
        )

    async def _handle_mandrill_ips_list_pools(
        self,
        config: MailchimpMandrillIpsListPoolsConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """List ip pools."""
        return await self._make_mandrill_request(
            "/ips/list-pools", config, credentials, "list_ip_pools"
        )

    async def _handle_mandrill_ips_pool_info(
        self,
        config: MailchimpMandrillIpsPoolInfoConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get ip pool info."""
        return await self._make_mandrill_request(
            "/ips/pool-info", config, credentials, "fetch_ip_pool_info"
        )

    async def _handle_mandrill_ips_create_pool(
        self,
        config: MailchimpMandrillIpsCreatePoolConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Add ip pool."""
        return await self._make_mandrill_request(
            "/ips/create-pool", config, credentials, "create_ip_pool"
        )

    async def _handle_mandrill_ips_delete_pool(
        self,
        config: MailchimpMandrillIpsDeletePoolConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Delete ip pool."""
        return await self._make_mandrill_request(
            "/ips/delete-pool", config, credentials, "delete_ip_pool"
        )

    async def _handle_mandrill_ips_check_custom_dns(
        self,
        config: MailchimpMandrillIpsCheckCustomDnsConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Test custom dns."""
        return await self._make_mandrill_request(
            "/ips/check-custom-dns",
            config,
            credentials,
            "test_ip_custom_dns",
        )

    async def _handle_mandrill_ips_set_custom_dns(
        self,
        config: MailchimpMandrillIpsSetCustomDnsConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Set custom dns."""
        return await self._make_mandrill_request(
            "/ips/set-custom-dns", config, credentials, "set_ip_custom_dns"
        )

    # Messages (12)
    async def _handle_mandrill_messages_send_sms(
        self,
        config: MailchimpMandrillMessagesSendSmsConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Send SMS message."""
        return await self._make_mandrill_request(
            "/messages/send-sms", config, credentials, "send_sms_message"
        )

    async def _handle_mandrill_messages_send(
        self,
        config: MailchimpMandrillMessagesSendConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Send new message."""
        return await self._make_mandrill_request(
            "/messages/send", config, credentials, "send_message"
        )

    async def _handle_mandrill_messages_send_template(
        self,
        config: MailchimpMandrillMessagesSendTemplateConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Send using message template."""
        return await self._make_mandrill_request(
            "/messages/send-template",
            config,
            credentials,
            "send_templated_message",
        )

    async def _handle_mandrill_messages_search(
        self,
        config: MailchimpMandrillMessagesSearchConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Search messages by date."""
        return await self._make_mandrill_request(
            "/messages/search", config, credentials, "search_messages_by_date"
        )

    async def _handle_mandrill_messages_search_time_series(
        self,
        config: MailchimpMandrillMessagesSearchTimeSeriesConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Search messages by hour."""
        return await self._make_mandrill_request(
            "/messages/search-time-series",
            config,
            credentials,
            "search_messages_by_hour",
        )

    async def _handle_mandrill_messages_info(
        self,
        config: MailchimpMandrillMessagesInfoConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get message info."""
        return await self._make_mandrill_request(
            "/messages/info", config, credentials, "fetch_message_info"
        )

    async def _handle_mandrill_messages_content(
        self,
        config: MailchimpMandrillMessagesContentConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get message content."""
        return await self._make_mandrill_request(
            "/messages/content", config, credentials, "fetch_message_content"
        )

    async def _handle_mandrill_messages_parse(
        self,
        config: MailchimpMandrillMessagesParseConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Parse mime document."""
        return await self._make_mandrill_request(
            "/messages/parse", config, credentials, "parse_mime_message"
        )

    async def _handle_mandrill_messages_send_raw(
        self,
        config: MailchimpMandrillMessagesSendRawConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Send mime document."""
        return await self._make_mandrill_request(
            "/messages/send-raw", config, credentials, "send_raw_mime_email"
        )

    async def _handle_mandrill_messages_list_scheduled(
        self,
        config: MailchimpMandrillMessagesListScheduledConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """List scheduled emails."""
        return await self._make_mandrill_request(
            "/messages/list-scheduled",
            config,
            credentials,
            "list_scheduled_emails",
        )

    async def _handle_mandrill_messages_cancel_scheduled(
        self,
        config: MailchimpMandrillMessagesCancelScheduledConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Cancel scheduled email."""
        return await self._make_mandrill_request(
            "/messages/cancel-scheduled",
            config,
            credentials,
            "cancel_scheduled_email",
        )

    async def _handle_mandrill_messages_reschedule(
        self,
        config: MailchimpMandrillMessagesRescheduleConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Reschedule email."""
        return await self._make_mandrill_request(
            "/messages/reschedule", config, credentials, "reschedule_scheduled_email"
        )

    # Metadata (4)
    async def _handle_mandrill_metadata_list(
        self,
        config: MailchimpMandrillMetadataListConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """List metadata fields."""
        return await self._make_mandrill_request(
            "/metadata/list", config, credentials, "list_metadata_fields"
        )

    async def _handle_mandrill_metadata_add(
        self,
        config: MailchimpMandrillMetadataAddConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Add metadata field."""
        return await self._make_mandrill_request(
            "/metadata/add", config, credentials, "create_metadata_field"
        )

    async def _handle_mandrill_metadata_update(
        self,
        config: MailchimpMandrillMetadataUpdateConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Update metadata field."""
        return await self._make_mandrill_request(
            "/metadata/update", config, credentials, "update_metadata_field"
        )

    async def _handle_mandrill_metadata_delete(
        self,
        config: MailchimpMandrillMetadataDeleteConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Delete metadata field."""
        return await self._make_mandrill_request(
            "/metadata/delete", config, credentials, "delete_metadata_field"
        )

    # Rejects (3)
    async def _handle_mandrill_rejects_add(
        self,
        config: MailchimpMandrillRejectsAddConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Add email to denylist."""
        return await self._make_mandrill_request(
            "/rejects/add", config, credentials, "add_email_to_denylist"
        )

    async def _handle_mandrill_rejects_list(
        self,
        config: MailchimpMandrillRejectsListConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """List denylisted emails."""
        return await self._make_mandrill_request(
            "/rejects/list", config, credentials, "list_denylisted_emails"
        )

    async def _handle_mandrill_rejects_delete(
        self,
        config: MailchimpMandrillRejectsDeleteConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Delete email from denylist."""
        return await self._make_mandrill_request(
            "/rejects/delete", config, credentials, "remove_email_from_denylist"
        )

    # Senders (7)
    async def _handle_mandrill_senders_list(
        self,
        config: MailchimpMandrillSendersListConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """List account senders."""
        return await self._make_mandrill_request(
            "/senders/list", config, credentials, "list_account_senders"
        )

    async def _handle_mandrill_senders_domains(
        self,
        config: MailchimpMandrillSendersDomainsConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """List sender domains."""
        return await self._make_mandrill_request(
            "/senders/domains", config, credentials, "list_sender_domains"
        )

    async def _handle_mandrill_senders_add_domain(
        self,
        config: MailchimpMandrillSendersAddDomainConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Add sender domain."""
        return await self._make_mandrill_request(
            "/senders/add-domain", config, credentials, "add_sender_domain"
        )

    async def _handle_mandrill_senders_check_domain(
        self,
        config: MailchimpMandrillSendersCheckDomainConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Check domain settings."""
        return await self._make_mandrill_request(
            "/senders/check-domain",
            config,
            credentials,
            "verify_sender_domain_settings",
        )

    async def _handle_mandrill_senders_verify_domain(
        self,
        config: MailchimpMandrillSendersVerifyDomainConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Verify domain."""
        return await self._make_mandrill_request(
            "/senders/verify-domain",
            config,
            credentials,
            "verify_sender_domain_for_sending",
        )

    async def _handle_mandrill_senders_info(
        self,
        config: MailchimpMandrillSendersInfoConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get sender info."""
        return await self._make_mandrill_request(
            "/senders/info", config, credentials, "fetch_sender_info"
        )

    async def _handle_mandrill_senders_time_series(
        self,
        config: MailchimpMandrillSendersTimeSeriesConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """View sender history."""
        return await self._make_mandrill_request(
            "/senders/time-series", config, credentials, "fetch_sender_history"
        )

    # Subaccounts (7)
    async def _handle_mandrill_subaccounts_list(
        self,
        config: MailchimpMandrillSubaccountsListConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """List subaccounts."""
        return await self._make_mandrill_request(
            "/subaccounts/list", config, credentials, "list_subaccounts"
        )

    async def _handle_mandrill_subaccounts_add(
        self,
        config: MailchimpMandrillSubaccountsAddConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Add subaccount."""
        return await self._make_mandrill_request(
            "/subaccounts/add", config, credentials, "create_subaccount"
        )

    async def _handle_mandrill_subaccounts_info(
        self,
        config: MailchimpMandrillSubaccountsInfoConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get subaccount info."""
        return await self._make_mandrill_request(
            "/subaccounts/info", config, credentials, "fetch_subaccount_info"
        )

    async def _handle_mandrill_subaccounts_update(
        self,
        config: MailchimpMandrillSubaccountsUpdateConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Update subaccount."""
        return await self._make_mandrill_request(
            "/subaccounts/update", config, credentials, "update_subaccount"
        )

    async def _handle_mandrill_subaccounts_delete(
        self,
        config: MailchimpMandrillSubaccountsDeleteConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Delete subaccount."""
        return await self._make_mandrill_request(
            "/subaccounts/delete", config, credentials, "delete_subaccount"
        )

    async def _handle_mandrill_subaccounts_pause(
        self,
        config: MailchimpMandrillSubaccountsPauseConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Pause subaccount."""
        return await self._make_mandrill_request(
            "/subaccounts/pause", config, credentials, "pause_subaccount"
        )

    async def _handle_mandrill_subaccounts_resume(
        self,
        config: MailchimpMandrillSubaccountsResumeConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Resume subaccount."""
        return await self._make_mandrill_request(
            "/subaccounts/resume", config, credentials, "resume_subaccount"
        )

    # Tags (5)
    async def _handle_mandrill_tags_list(
        self, config: MailchimpMandrillTagsListConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """List tags."""
        return await self._make_mandrill_request(
            "/tags/list", config, credentials, "list_tags"
        )

    async def _handle_mandrill_tags_delete(
        self,
        config: MailchimpMandrillTagsDeleteConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Delete tag."""
        return await self._make_mandrill_request(
            "/tags/delete", config, credentials, "delete_tag"
        )

    async def _handle_mandrill_tags_info(
        self, config: MailchimpMandrillTagsInfoConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get tag info."""
        return await self._make_mandrill_request(
            "/tags/info", config, credentials, "fetch_tag_info"
        )

    async def _handle_mandrill_tags_time_series(
        self,
        config: MailchimpMandrillTagsTimeSeriesConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """View tag history."""
        return await self._make_mandrill_request(
            "/tags/time-series", config, credentials, "fetch_tag_history"
        )

    async def _handle_mandrill_tags_all_time_series(
        self,
        config: MailchimpMandrillTagsAllTimeSeriesConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """View all tags history."""
        return await self._make_mandrill_request(
            "/tags/all-time-series",
            config,
            credentials,
            "fetch_all_tags_history",
        )

    # Templates (8)
    async def _handle_mandrill_templates_add(
        self,
        config: MailchimpMandrillTemplatesAddConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Add template."""
        return await self._make_mandrill_request(
            "/templates/add", config, credentials, "create_mandrill_template"
        )

    async def _handle_mandrill_templates_info(
        self,
        config: MailchimpMandrillTemplatesInfoConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get template info."""
        return await self._make_mandrill_request(
            "/templates/info", config, credentials, "fetch_mandrill_template_info"
        )

    async def _handle_mandrill_templates_update(
        self,
        config: MailchimpMandrillTemplatesUpdateConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Update template."""
        return await self._make_mandrill_request(
            "/templates/update", config, credentials, "update_mandrill_template"
        )

    async def _handle_mandrill_templates_publish(
        self,
        config: MailchimpMandrillTemplatesPublishConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Publish template content."""
        return await self._make_mandrill_request(
            "/templates/publish", config, credentials, "publish_mandrill_template"
        )

    async def _handle_mandrill_templates_delete(
        self,
        config: MailchimpMandrillTemplatesDeleteConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Delete template."""
        return await self._make_mandrill_request(
            "/templates/delete", config, credentials, "delete_mandrill_template"
        )

    async def _handle_mandrill_templates_list(
        self,
        config: MailchimpMandrillTemplatesListConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """List templates."""
        return await self._make_mandrill_request(
            "/templates/list", config, credentials, "list_mandrill_templates"
        )

    async def _handle_mandrill_templates_time_series(
        self,
        config: MailchimpMandrillTemplatesTimeSeriesConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get template history."""
        return await self._make_mandrill_request(
            "/templates/time-series",
            config,
            credentials,
            "fetch_mandrill_template_history",
        )

    async def _handle_mandrill_templates_render(
        self,
        config: MailchimpMandrillTemplatesRenderConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Render html template."""
        return await self._make_mandrill_request(
            "/templates/render", config, credentials, "render_html_template"
        )

    # URLs (6)
    async def _handle_mandrill_urls_list(
        self, config: MailchimpMandrillUrlsListConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """List most clicked urls."""
        return await self._make_mandrill_request(
            "/urls/list", config, credentials, "list_most_clicked_urls"
        )

    async def _handle_mandrill_urls_search(
        self,
        config: MailchimpMandrillUrlsSearchConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Search most clicked urls."""
        return await self._make_mandrill_request(
            "/urls/search", config, credentials, "search_most_clicked_urls"
        )

    async def _handle_mandrill_urls_time_series(
        self,
        config: MailchimpMandrillUrlsTimeSeriesConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get url history."""
        return await self._make_mandrill_request(
            "/urls/time-series", config, credentials, "fetch_url_history"
        )

    async def _handle_mandrill_urls_tracking_domains(
        self,
        config: MailchimpMandrillUrlsTrackingDomainsConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """List tracking domains."""
        return await self._make_mandrill_request(
            "/urls/tracking-domains",
            config,
            credentials,
            "list_tracking_domains",
        )

    async def _handle_mandrill_urls_add_tracking_domain(
        self,
        config: MailchimpMandrillUrlsAddTrackingDomainConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Add tracking domains."""
        return await self._make_mandrill_request(
            "/urls/add-tracking-domain",
            config,
            credentials,
            "add_tracking_domain",
        )

    async def _handle_mandrill_urls_check_tracking_domain(
        self,
        config: MailchimpMandrillUrlsCheckTrackingDomainConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Check cname settings."""
        return await self._make_mandrill_request(
            "/urls/check-tracking-domain",
            config,
            credentials,
            "verify_tracking_domain_cname",
        )

    # Users (4)
    async def _handle_mandrill_users_info(
        self, config: MailchimpMandrillUsersInfoConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Get user info."""
        return await self._make_mandrill_request(
            "/users/info", config, credentials, "fetch_user_info"
        )

    async def _handle_mandrill_users_ping(
        self, config: MailchimpMandrillUsersPingConfig, credentials: MailchimpCredential
    ) -> Dict[str, Any]:
        """Ping."""
        return await self._make_mandrill_request(
            "/users/ping", config, credentials, "ping_mandrill_api"
        )

    async def _handle_mandrill_users_ping2(
        self,
        config: MailchimpMandrillUsersPing2Config,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Ping 2."""
        return await self._make_mandrill_request(
            "/users/ping2", config, credentials, "ping_mandrill_api_v2"
        )

    async def _handle_mandrill_users_senders(
        self,
        config: MailchimpMandrillUsersSendersConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """List account senders."""
        return await self._make_mandrill_request(
            "/users/senders", config, credentials, "list_api_account_senders"
        )

    # Webhooks (5)
    async def _handle_mandrill_webhooks_list(
        self,
        config: MailchimpMandrillWebhooksListConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """List webhooks."""
        return await self._make_mandrill_request(
            "/webhooks/list", config, credentials, "list_mandrill_webhooks"
        )

    async def _handle_mandrill_webhooks_add(
        self,
        config: MailchimpMandrillWebhooksAddConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Add webhook."""
        return await self._make_mandrill_request(
            "/webhooks/add", config, credentials, "create_mandrill_webhook"
        )

    async def _handle_mandrill_webhooks_info(
        self,
        config: MailchimpMandrillWebhooksInfoConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Get webhook info."""
        return await self._make_mandrill_request(
            "/webhooks/info", config, credentials, "fetch_mandrill_webhook_info"
        )

    async def _handle_mandrill_webhooks_update(
        self,
        config: MailchimpMandrillWebhooksUpdateConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Update webhook."""
        return await self._make_mandrill_request(
            "/webhooks/update", config, credentials, "update_mandrill_webhook"
        )

    async def _handle_mandrill_webhooks_delete(
        self,
        config: MailchimpMandrillWebhooksDeleteConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Delete webhook."""
        return await self._make_mandrill_request(
            "/webhooks/delete", config, credentials, "delete_mandrill_webhook"
        )

    # Whitelists (3)
    async def _handle_mandrill_whitelists_add(
        self,
        config: MailchimpMandrillWhitelistsAddConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Add email to allowlist."""
        return await self._make_mandrill_request(
            "/whitelists/add", config, credentials, "add_email_to_whitelist"
        )

    async def _handle_mandrill_whitelists_list(
        self,
        config: MailchimpMandrillWhitelistsListConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """List allowlisted emails."""
        return await self._make_mandrill_request(
            "/whitelists/list", config, credentials, "list_whitelisted_emails"
        )

    async def _handle_mandrill_whitelists_delete(
        self,
        config: MailchimpMandrillWhitelistsDeleteConfig,
        credentials: MailchimpCredential,
    ) -> Dict[str, Any]:
        """Remove email from allowlist."""
        return await self._make_mandrill_request(
            "/whitelists/delete", config, credentials, "remove_email_from_whitelist"
        )
