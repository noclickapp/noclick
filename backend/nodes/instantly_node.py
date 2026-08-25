"""
Instantly email automation node.

Provides workflow integration with Instantly for operations including:
- Account Operations: list, get, create, pause, resume, delete email accounts
- Campaign Operations: list, get, create, update, delete, activate, pause, search campaigns
- Lead Operations: list, get, create, update, delete, bulk add, move leads
- Lead List Operations: list, get, create, update, delete lead lists
- Email Operations: list, get, reply, count unread, mark thread read
- Analytics: campaign analytics, daily analytics, warmup analytics
- Webhook Trigger: receive events (reply_received, positive_reply, etc.)

Authentication: API Key (Bearer token)
API Base URL: https://api.instantly.ai/api/v2
Documentation: https://developer.instantly.ai
"""

import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig

logger = logging.getLogger(__name__)

INSTANTLY_API_BASE = "https://api.instantly.ai/api/v2"

# ============================================================================
# Credential Schema
# ============================================================================


class InstantlyAPIKeyCredential(BaseModel):
    """API Key credential for Instantly."""

    credential_type: Literal["instantly_api_key"] = Field(
        "instantly_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description="Your Instantly API key from Settings > Integrations",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(json_schema_extra={
        "x-credential-url": "https://app.instantly.ai/app/settings/integrations"
    })


InstantlyCredential = InstantlyAPIKeyCredential

# ============================================================================
# Account Operation Configs
# ============================================================================


class InstantlyListAccountsConfig(BaseModel):
    """List email accounts in your workspace."""

    operation: Literal["list_email_accounts"] = Field(
        "list_email_accounts",
        json_schema_extra={
            "const": "list_email_accounts",
            "ui:hidden": True,
            "x-category": "Email Account",
            "x-is-trigger": False,
            "x-display-name": "List Email Accounts",
        },
        title="List Email Accounts",
    )
    limit: Optional[str] = Field(
        "10", title="Limit", description="Number of accounts to return (max 100)"
    )
    starting_after: Optional[str] = Field(
        None,
        title="Starting After",
        description="Pagination cursor from previous response",
    )
    search: Optional[str] = Field(
        None, title="Search", description="Filter by email domain"
    )


class InstantlyGetAccountConfig(BaseModel):
    """Get details of a specific email account."""

    operation: Literal["get_email_account"] = Field(
        "get_email_account",
        json_schema_extra={
            "const": "get_email_account",
            "ui:hidden": True,
            "x-category": "Email Account",
            "x-is-trigger": False,
            "x-display-name": "Get Email Account",
        },
        title="Get Email Account",
    )
    email: str = Field(
        ..., title="Email", description="The email address of the account"
    )


class InstantlyCreateAccountConfig(BaseModel):
    """Add a new email account to your workspace."""

    operation: Literal["create_email_account"] = Field(
        "create_email_account",
        json_schema_extra={
            "const": "create_email_account",
            "ui:hidden": True,
            "x-category": "Email Account",
            "x-is-trigger": False,
            "x-display-name": "Create Email Account",
        },
        title="Create Email Account",
    )
    email: str = Field(..., title="Email", description="Email address for the account")
    first_name: str = Field(..., title="First Name", description="Sender first name")
    last_name: str = Field(..., title="Last Name", description="Sender last name")
    provider_code: str = Field(
        "1",
        title="Provider",
        description="Email provider type",
        json_schema_extra={
            "enum": ["1", "2", "3", "4", "8"],
            "enumNames": ["Custom IMAP/SMTP", "Google", "Microsoft", "AWS", "AirMail"],
            "x-enum-searchable": True,
        },
    )
    daily_limit: Optional[str] = Field(
        None, title="Daily Limit", description="Max emails per day"
    )


class InstantlyPauseAccountConfig(BaseModel):
    """Pause an email account."""

    operation: Literal["pause_email_account"] = Field(
        "pause_email_account",
        json_schema_extra={
            "const": "pause_email_account",
            "ui:hidden": True,
            "x-category": "Email Account",
            "x-is-trigger": False,
            "x-display-name": "Pause Email Account",
        },
        title="Pause Email Account",
    )
    email: str = Field(
        ..., title="Email", description="The email address of the account to pause"
    )


class InstantlyResumeAccountConfig(BaseModel):
    """Resume a paused email account."""

    operation: Literal["resume_email_account"] = Field(
        "resume_email_account",
        json_schema_extra={
            "const": "resume_email_account",
            "ui:hidden": True,
            "x-category": "Email Account",
            "x-is-trigger": False,
            "x-display-name": "Resume Email Account",
        },
        title="Resume Email Account",
    )
    email: str = Field(
        ..., title="Email", description="The email address of the account to resume"
    )


class InstantlyDeleteAccountConfig(BaseModel):
    """Delete an email account from your workspace."""

    operation: Literal["delete_email_account"] = Field(
        "delete_email_account",
        json_schema_extra={
            "const": "delete_email_account",
            "ui:hidden": True,
            "x-category": "Email Account",
            "x-is-trigger": False,
            "x-display-name": "Delete Email Account",
        },
        title="Delete Email Account",
    )
    email: str = Field(
        ..., title="Email", description="The email address of the account to delete"
    )


# ============================================================================
# Campaign Operation Configs
# ============================================================================


class InstantlyListCampaignsConfig(BaseModel):
    """List campaigns in your workspace."""

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
    limit: Optional[str] = Field(
        "10", title="Limit", description="Number of campaigns to return (max 100)"
    )
    starting_after: Optional[str] = Field(
        None,
        title="Starting After",
        description="Pagination cursor from previous response",
    )
    search: Optional[str] = Field(
        None, title="Search", description="Filter by campaign name"
    )


class InstantlyGetCampaignConfig(BaseModel):
    """Get details of a specific campaign."""

    operation: Literal["get_campaign"] = Field(
        "get_campaign",
        json_schema_extra={
            "const": "get_campaign",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Get Campaign",
        },
        title="Get Campaign",
    )
    campaign_id: str = Field(..., title="Campaign ID", description="The campaign UUID")


class InstantlyCreateCampaignConfig(BaseModel):
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
    name: str = Field(
        ..., title="Campaign Name", description="Name for the new campaign"
    )


class InstantlyUpdateCampaignConfig(BaseModel):
    """Update an existing campaign."""

    operation: Literal["update_campaign"] = Field(
        "update_campaign",
        json_schema_extra={
            "const": "update_campaign",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Update Campaign",
        },
        title="Update Campaign",
    )
    campaign_id: str = Field(..., title="Campaign ID", description="The campaign UUID")
    name: Optional[str] = Field(None, title="Name", description="New campaign name")


class InstantlyDeleteCampaignConfig(BaseModel):
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
    campaign_id: str = Field(
        ..., title="Campaign ID", description="The campaign UUID to delete"
    )


class InstantlyActivateCampaignConfig(BaseModel):
    """Activate (start/resume) a campaign."""

    operation: Literal["activate_campaign"] = Field(
        "activate_campaign",
        json_schema_extra={
            "const": "activate_campaign",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Activate Campaign",
        },
        title="Activate Campaign",
    )
    campaign_id: str = Field(
        ..., title="Campaign ID", description="The campaign UUID to activate"
    )


class InstantlyPauseCampaignConfig(BaseModel):
    """Pause (stop) a running campaign."""

    operation: Literal["pause_campaign"] = Field(
        "pause_campaign",
        json_schema_extra={
            "const": "pause_campaign",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Pause Campaign",
        },
        title="Pause Campaign",
    )
    campaign_id: str = Field(
        ..., title="Campaign ID", description="The campaign UUID to pause"
    )


class InstantlySearchCampaignsByContactConfig(BaseModel):
    """Search campaigns by lead email address."""

    operation: Literal["search_campaigns_by_contact_email"] = Field(
        "search_campaigns_by_contact_email",
        json_schema_extra={
            "const": "search_campaigns_by_contact_email",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Search Campaigns by Contact Email",
        },
        title="Search Campaigns by Contact Email",
    )
    email: str = Field(
        ..., title="Lead Email", description="Email address of the lead to search for"
    )


# ============================================================================
# Lead Operation Configs
# ============================================================================


class InstantlyListLeadsConfig(BaseModel):
    """List leads with optional filters."""

    operation: Literal["list_leads"] = Field(
        "list_leads",
        json_schema_extra={
            "const": "list_leads",
            "ui:hidden": True,
            "x-category": "Lead",
            "x-is-trigger": False,
            "x-display-name": "List Leads",
        },
        title="List Leads",
    )
    campaign_id: Optional[str] = Field(
        None, title="Campaign ID", description="Filter by campaign UUID"
    )
    list_id: Optional[str] = Field(
        None, title="List ID", description="Filter by lead list UUID"
    )
    limit: Optional[str] = Field(
        "10", title="Limit", description="Number of leads to return"
    )
    starting_after: Optional[str] = Field(
        None, title="Starting After", description="Lead ID for cursor-based pagination"
    )
    email: Optional[str] = Field(
        None, title="Email Filter", description="Filter by exact email address"
    )


class InstantlyGetLeadConfig(BaseModel):
    """Get details of a specific lead."""

    operation: Literal["get_lead"] = Field(
        "get_lead",
        json_schema_extra={
            "const": "get_lead",
            "ui:hidden": True,
            "x-category": "Lead",
            "x-is-trigger": False,
            "x-display-name": "Get Lead",
        },
        title="Get Lead",
    )
    lead_id: str = Field(..., title="Lead ID", description="The lead UUID")


class InstantlyCreateLeadConfig(BaseModel):
    """Create a new lead."""

    operation: Literal["create_lead"] = Field(
        "create_lead",
        json_schema_extra={
            "const": "create_lead",
            "ui:hidden": True,
            "x-category": "Lead",
            "x-is-trigger": False,
            "x-display-name": "Create Lead",
        },
        title="Create Lead",
    )
    email: str = Field(..., title="Email", description="Lead email address")
    first_name: Optional[str] = Field(
        None, title="First Name", description="Lead first name"
    )
    last_name: Optional[str] = Field(
        None, title="Last Name", description="Lead last name"
    )
    company_name: Optional[str] = Field(
        None, title="Company", description="Lead company name"
    )
    website: Optional[str] = Field(
        None, title="Website", description="Lead website URL"
    )
    phone: Optional[str] = Field(None, title="Phone", description="Lead phone number")
    campaign: Optional[str] = Field(
        None, title="Campaign ID", description="Campaign UUID to add lead to"
    )
    list_id: Optional[str] = Field(
        None, title="List ID", description="Lead list UUID to add lead to"
    )


class InstantlyUpdateLeadConfig(BaseModel):
    """Update an existing lead."""

    operation: Literal["update_lead"] = Field(
        "update_lead",
        json_schema_extra={
            "const": "update_lead",
            "ui:hidden": True,
            "x-category": "Lead",
            "x-is-trigger": False,
            "x-display-name": "Update Lead",
        },
        title="Update Lead",
    )
    lead_id: str = Field(..., title="Lead ID", description="The lead UUID")
    first_name: Optional[str] = Field(
        None, title="First Name", description="New first name"
    )
    last_name: Optional[str] = Field(
        None, title="Last Name", description="New last name"
    )
    company_name: Optional[str] = Field(
        None, title="Company", description="New company name"
    )
    website: Optional[str] = Field(None, title="Website", description="New website URL")
    phone: Optional[str] = Field(None, title="Phone", description="New phone number")


class InstantlyDeleteLeadConfig(BaseModel):
    """Delete a lead."""

    operation: Literal["delete_lead"] = Field(
        "delete_lead",
        json_schema_extra={
            "const": "delete_lead",
            "ui:hidden": True,
            "x-category": "Lead",
            "x-is-trigger": False,
            "x-display-name": "Delete Lead",
        },
        title="Delete Lead",
    )
    lead_id: str = Field(..., title="Lead ID", description="The lead UUID to delete")


class InstantlyBulkAddLeadsConfig(BaseModel):
    """Add up to 1000 leads to a campaign or list."""

    operation: Literal["bulk_add_leads_to_campaign"] = Field(
        "bulk_add_leads_to_campaign",
        json_schema_extra={
            "const": "bulk_add_leads_to_campaign",
            "ui:hidden": True,
            "x-category": "Lead",
            "x-is-trigger": False,
            "x-display-name": "Bulk Add Leads to Campaign",
        },
        title="Bulk Add Leads to Campaign",
    )
    leads: str = Field(
        ...,
        title="Leads (JSON)",
        description='JSON array of lead objects, e.g. [{"email": "a@b.com", "first_name": "John"}]',
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )
    campaign_id: Optional[str] = Field(
        None, title="Campaign ID", description="Campaign UUID to add leads to"
    )
    list_id: Optional[str] = Field(
        None, title="List ID", description="Lead list UUID to add leads to"
    )


class InstantlyMoveLeadConfig(BaseModel):
    """Move leads to a different campaign or list."""

    operation: Literal["move_leads_to_campaign"] = Field(
        "move_leads_to_campaign",
        json_schema_extra={
            "const": "move_leads_to_campaign",
            "ui:hidden": True,
            "x-category": "Lead",
            "x-is-trigger": False,
            "x-display-name": "Move Leads to Campaign",
        },
        title="Move Leads to Campaign",
    )
    lead_ids: str = Field(
        ..., title="Lead IDs", description="Comma-separated lead UUIDs to move"
    )
    to_campaign_id: Optional[str] = Field(
        None, title="To Campaign ID", description="Target campaign UUID"
    )
    to_list_id: Optional[str] = Field(
        None, title="To List ID", description="Target lead list UUID"
    )


# ============================================================================
# Lead List Operation Configs
# ============================================================================


class InstantlyListLeadListsConfig(BaseModel):
    """List all lead lists."""

    operation: Literal["list_lead_lists"] = Field(
        "list_lead_lists",
        json_schema_extra={
            "const": "list_lead_lists",
            "ui:hidden": True,
            "x-category": "Lead List",
            "x-is-trigger": False,
            "x-display-name": "List Lead Lists",
        },
        title="List Lead Lists",
    )
    limit: Optional[str] = Field(
        "10", title="Limit", description="Number of lists to return (max 100)"
    )
    starting_after: Optional[str] = Field(
        None,
        title="Starting After",
        description="Pagination cursor from previous response",
    )


class InstantlyGetLeadListConfig(BaseModel):
    """Get details of a specific lead list."""

    operation: Literal["get_lead_list"] = Field(
        "get_lead_list",
        json_schema_extra={
            "const": "get_lead_list",
            "ui:hidden": True,
            "x-category": "Lead List",
            "x-is-trigger": False,
            "x-display-name": "Get Lead List",
        },
        title="Get Lead List",
    )
    list_id: str = Field(..., title="List ID", description="The lead list UUID")


class InstantlyCreateLeadListConfig(BaseModel):
    """Create a new lead list."""

    operation: Literal["create_lead_list"] = Field(
        "create_lead_list",
        json_schema_extra={
            "const": "create_lead_list",
            "ui:hidden": True,
            "x-category": "Lead List",
            "x-is-trigger": False,
            "x-display-name": "Create Lead List",
        },
        title="Create Lead List",
    )
    name: str = Field(..., title="Name", description="Name for the new lead list")


class InstantlyUpdateLeadListConfig(BaseModel):
    """Update an existing lead list."""

    operation: Literal["update_lead_list"] = Field(
        "update_lead_list",
        json_schema_extra={
            "const": "update_lead_list",
            "ui:hidden": True,
            "x-category": "Lead List",
            "x-is-trigger": False,
            "x-display-name": "Update Lead List",
        },
        title="Update Lead List",
    )
    list_id: str = Field(..., title="List ID", description="The lead list UUID")
    name: str = Field(..., title="Name", description="New name for the lead list")


class InstantlyDeleteLeadListConfig(BaseModel):
    """Delete a lead list."""

    operation: Literal["delete_lead_list"] = Field(
        "delete_lead_list",
        json_schema_extra={
            "const": "delete_lead_list",
            "ui:hidden": True,
            "x-category": "Lead List",
            "x-is-trigger": False,
            "x-display-name": "Delete Lead List",
        },
        title="Delete Lead List",
    )
    list_id: str = Field(
        ..., title="List ID", description="The lead list UUID to delete"
    )


# ============================================================================
# Email Operation Configs
# ============================================================================


class InstantlyListEmailsConfig(BaseModel):
    """List emails with optional filters."""

    operation: Literal["list_emails"] = Field(
        "list_emails",
        json_schema_extra={
            "const": "list_emails",
            "ui:hidden": True,
            "x-category": "Email",
            "x-is-trigger": False,
            "x-display-name": "List Emails",
        },
        title="List Emails",
    )
    campaign_id: Optional[str] = Field(
        None, title="Campaign ID", description="Filter by campaign UUID"
    )
    lead_email: Optional[str] = Field(
        None, title="Lead Email", description="Filter by lead email address"
    )
    limit: Optional[str] = Field(
        "10",
        title="Limit",
        description="Number of emails to return (max 20/min rate limit)",
    )


class InstantlyGetEmailConfig(BaseModel):
    """Get details of a specific email."""

    operation: Literal["get_email"] = Field(
        "get_email",
        json_schema_extra={
            "const": "get_email",
            "ui:hidden": True,
            "x-category": "Email",
            "x-is-trigger": False,
            "x-display-name": "Get Email",
        },
        title="Get Email",
    )
    email_id: str = Field(..., title="Email ID", description="The email UUID")


class InstantlyReplyToEmailConfig(BaseModel):
    """Reply to an email thread."""

    operation: Literal["reply_to_email"] = Field(
        "reply_to_email",
        json_schema_extra={
            "const": "reply_to_email",
            "ui:hidden": True,
            "x-category": "Email",
            "x-is-trigger": False,
            "x-display-name": "Reply to Email",
        },
        title="Reply to Email",
    )
    reply_to_uuid: str = Field(
        ..., title="Email UUID", description="The email UUID to reply to"
    )
    eaccount: str = Field(
        ..., title="Sender Account", description="Sender email account (must be active)"
    )
    subject: str = Field(..., title="Subject", description="Reply subject line")
    body: str = Field(
        ...,
        title="Body",
        description="Reply body (HTML supported)",
        json_schema_extra={"ui:rows": 4},
    )
    cc: Optional[str] = Field(
        None, title="CC", description="CC email addresses (comma-separated)"
    )
    bcc: Optional[str] = Field(
        None, title="BCC", description="BCC email addresses (comma-separated)"
    )


class InstantlyCountUnreadEmailsConfig(BaseModel):
    """Count unread emails in your inbox."""

    operation: Literal["count_unread_emails"] = Field(
        "count_unread_emails",
        json_schema_extra={
            "const": "count_unread_emails",
            "ui:hidden": True,
            "x-category": "Email",
            "x-is-trigger": False,
            "x-display-name": "Count Unread Emails",
        },
        title="Count Unread Emails",
    )


class InstantlyMarkThreadReadConfig(BaseModel):
    """Mark an email thread as read."""

    operation: Literal["mark_email_thread_as_read"] = Field(
        "mark_email_thread_as_read",
        json_schema_extra={
            "const": "mark_email_thread_as_read",
            "ui:hidden": True,
            "x-category": "Email",
            "x-is-trigger": False,
            "x-display-name": "Mark Email Thread As Read",
        },
        title="Mark Email Thread As Read",
    )
    thread_id: str = Field(
        ..., title="Thread ID", description="The email thread UUID to mark as read"
    )


# ============================================================================
# Analytics Operation Configs
# ============================================================================


class InstantlyGetCampaignAnalyticsConfig(BaseModel):
    """Get analytics for a campaign."""

    operation: Literal["get_campaign_analytics"] = Field(
        "get_campaign_analytics",
        json_schema_extra={
            "const": "get_campaign_analytics",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Get Campaign Analytics",
        },
        title="Get Campaign Analytics",
    )
    campaign_id: str = Field(..., title="Campaign ID", description="The campaign UUID")
    start_date: Optional[str] = Field(
        None, title="Start Date", description="Start date (YYYY-MM-DD)"
    )
    end_date: Optional[str] = Field(
        None, title="End Date", description="End date (YYYY-MM-DD)"
    )


class InstantlyGetDailyCampaignAnalyticsConfig(BaseModel):
    """Get daily campaign analytics across all campaigns."""

    operation: Literal["get_daily_campaign_analytics"] = Field(
        "get_daily_campaign_analytics",
        json_schema_extra={
            "const": "get_daily_campaign_analytics",
            "ui:hidden": True,
            "x-category": "Campaign",
            "x-is-trigger": False,
            "x-display-name": "Get Daily Campaign Analytics",
        },
        title="Get Daily Campaign Analytics",
    )
    campaign_id: Optional[str] = Field(
        None, title="Campaign ID", description="Filter by campaign UUID"
    )
    start_date: Optional[str] = Field(
        None, title="Start Date", description="Start date (YYYY-MM-DD)"
    )
    end_date: Optional[str] = Field(
        None, title="End Date", description="End date (YYYY-MM-DD)"
    )


class InstantlyGetWarmupAnalyticsConfig(BaseModel):
    """Get warmup analytics for an email account."""

    operation: Literal["get_account_warmup_analytics"] = Field(
        "get_account_warmup_analytics",
        json_schema_extra={
            "const": "get_account_warmup_analytics",
            "ui:hidden": True,
            "x-category": "Analytics",
            "x-is-trigger": False,
            "x-display-name": "Get Account Warmup Analytics",
        },
        title="Get Account Warmup Analytics",
    )
    email: str = Field(
        ..., title="Email", description="The email address of the account"
    )
    start_date: Optional[str] = Field(
        None, title="Start Date", description="Start date (YYYY-MM-DD)"
    )
    end_date: Optional[str] = Field(
        None, title="End Date", description="End date (YYYY-MM-DD)"
    )


# ============================================================================
# Webhook Trigger Config
# ============================================================================


class InstantlyReceiveWebhookConfig(BaseModel):
    """Receive webhook events from Instantly (e.g. reply_received, positive_reply)."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["receive_webhook_events"] = Field(
        "receive_webhook_events",
        json_schema_extra={
            "const": "receive_webhook_events",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "Receive Webhook Events",
        },
        title="Receive Webhook Events",
    )
    event_type: str = Field(
        "reply_received",
        title="Event Type",
        description="The type of Instantly event to subscribe to",
        json_schema_extra={
            "enum": [
                "reply_received",
                "email_sent",
                "email_opened",
                "link_clicked",
                "lead_unsubscribed",
                "lead_interested",
                "lead_not_interested",
                "lead_wrong_person",
                "lead_meeting_booked",
                "lead_meeting_completed",
                "lead_out_of_office",
                "lead_closed",
            ],
            "enumNames": [
                "Reply Received",
                "Email Sent",
                "Email Opened",
                "Link Clicked",
                "Lead Unsubscribed",
                "Lead Interested",
                "Lead Not Interested",
                "Lead Wrong Person",
                "Lead Meeting Booked",
                "Lead Meeting Completed",
                "Lead Out of Office",
                "Lead Closed",
            ],
            "x-enum-searchable": True,
        },
    )
    webhook_id: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="Auto-generated URL registered with Instantly",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:copyable": True,
            "ui:loadValue": True,
        },
    )
    relay_connected: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    is_production: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    instantly_webhook_id: Optional[str] = Field(
        default=None,
        description="The webhook ID on Instantly's side",
        json_schema_extra={"ui:hidden": True},
    )


# ============================================================================
# Discriminated Union
# ============================================================================


InstantlyConfig = Annotated[
    Union[
        # Accounts
        InstantlyListAccountsConfig,
        InstantlyGetAccountConfig,
        InstantlyCreateAccountConfig,
        InstantlyPauseAccountConfig,
        InstantlyResumeAccountConfig,
        InstantlyDeleteAccountConfig,
        # Campaigns
        InstantlyListCampaignsConfig,
        InstantlyGetCampaignConfig,
        InstantlyCreateCampaignConfig,
        InstantlyUpdateCampaignConfig,
        InstantlyDeleteCampaignConfig,
        InstantlyActivateCampaignConfig,
        InstantlyPauseCampaignConfig,
        InstantlySearchCampaignsByContactConfig,
        # Leads
        InstantlyListLeadsConfig,
        InstantlyGetLeadConfig,
        InstantlyCreateLeadConfig,
        InstantlyUpdateLeadConfig,
        InstantlyDeleteLeadConfig,
        InstantlyBulkAddLeadsConfig,
        InstantlyMoveLeadConfig,
        # Lead Lists
        InstantlyListLeadListsConfig,
        InstantlyGetLeadListConfig,
        InstantlyCreateLeadListConfig,
        InstantlyUpdateLeadListConfig,
        InstantlyDeleteLeadListConfig,
        # Emails
        InstantlyListEmailsConfig,
        InstantlyGetEmailConfig,
        InstantlyReplyToEmailConfig,
        InstantlyCountUnreadEmailsConfig,
        InstantlyMarkThreadReadConfig,
        # Analytics
        InstantlyGetCampaignAnalyticsConfig,
        InstantlyGetDailyCampaignAnalyticsConfig,
        InstantlyGetWarmupAnalyticsConfig,
        # Webhook
        InstantlyReceiveWebhookConfig,
    ],
    Discriminator("operation"),
]


class InstantlyNodeConfig(NodeConfig[InstantlyConfig, InstantlyCredential]):
    """Full configuration for Instantly node including credentials."""

    pass


# ============================================================================
# Webhook Lifecycle Helpers
# ============================================================================


async def delete_instantly_webhook(
    api_key: str, instantly_webhook_id: str
) -> Dict[str, Any]:
    """
    Delete a webhook from Instantly's API.

    Args:
        api_key: Instantly API key
        instantly_webhook_id: The webhook ID on Instantly's side

    Returns:
        Dict with success status
    """
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.delete(
                f"{INSTANTLY_API_BASE}/webhooks/{instantly_webhook_id}",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if resp.status_code < 400:
                logger.info(
                    f"[InstantlyNode] Deleted webhook from Instantly: {instantly_webhook_id}"
                )
                return {"success": True}
            else:
                logger.warning(
                    f"[InstantlyNode] Failed to delete Instantly webhook {instantly_webhook_id}: {resp.text}"
                )
                return {"success": False, "error": resp.text}
    except Exception as e:
        logger.error(f"[InstantlyNode] Error deleting Instantly webhook: {e}")
        return {"success": False, "error": str(e)}


async def register_instantly_webhook(
    api_key: str, webhook_url: str, event_type: str
) -> Dict[str, Any]:
    """
    Register a webhook URL with Instantly's API.

    Args:
        api_key: Instantly API key
        webhook_url: Our internal webhook URL to register
        event_type: Instantly event type (e.g. reply_received)

    Returns:
        Dict with instantly_webhook_id on success
    """
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{INSTANTLY_API_BASE}/webhooks",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "webhook_url": webhook_url,
                    "event_type": event_type,
                },
            )
            if resp.status_code < 400:
                resp_data = resp.json()
                instantly_webhook_id = resp_data.get("id")
                logger.info(
                    f"[InstantlyNode] Registered webhook with Instantly: {instantly_webhook_id}"
                )
                return {"success": True, "instantly_webhook_id": instantly_webhook_id}
            else:
                logger.warning(
                    f"[InstantlyNode] Failed to register webhook with Instantly: {resp.text}"
                )
                return {"success": False, "error": resp.text}
    except Exception as e:
        logger.error(f"[InstantlyNode] Error registering Instantly webhook: {e}")
        return {"success": False, "error": str(e)}


async def cleanup_instantly_webhook(
    pool,
    workflow_id: str,
    node_id: str,
    api_key: Optional[str] = None,
    instantly_webhook_id: Optional[str] = None,
) -> bool:
    """
    Clean up an Instantly trigger webhook.

    Deletes the webhook from Instantly's API (if credentials available),
    then deletes our internal webhook record.

    Args:
        pool: Database connection pool
        workflow_id: Workflow UUID string
        node_id: Node ID in the workflow
        api_key: Optional API key — if provided, will unregister from Instantly
        instantly_webhook_id: Optional Instantly-side webhook ID to delete

    Returns:
        True if cleanup succeeded
    """
    from utils.webhook_manager import WebhookManager

    # Step 1: Unregister from Instantly if we have the credentials
    if api_key and instantly_webhook_id:
        await delete_instantly_webhook(api_key, instantly_webhook_id)

    # Step 2: Delete our internal webhook
    return await WebhookManager.delete_webhook(pool, workflow_id, node_id)


# ============================================================================
# Node Implementation
# ============================================================================


class InstantlyNode(WorkflowNode):
    """
    Instantly email automation node.

    Executes Instantly API operations for workflow automation.
    Supports 35 operations across accounts, campaigns, leads, emails,
    analytics, and webhook triggers.
    """

    edit_examples = [
        "Create campaign with 3-step sequence and add 500 leads from CSV",
        "Activate campaign targeting leads with name matching pattern",
        "Count unread emails in inbox and mark customer reply threads read",
        "List leads with status contacted and move to different campaign",
        "Get campaign analytics for last 30 days (opens, clicks, replies)",
        "Create new email account and enable warmup with daily limits",
        "Search for specific contact email across all campaigns",
    ]

    @classmethod
    def get_config_model(cls):
        return InstantlyNodeConfig

    @classmethod
    async def cleanup_external_webhook(
        cls, pool, workflow_id, node_id, config, credentials=None
    ):
        api_key = credentials.get("api_key") if credentials else None
        instantly_webhook_id = config.get("instantly_webhook_id")
        if api_key and instantly_webhook_id:
            await delete_instantly_webhook(api_key, instantly_webhook_id)

    @classmethod
    async def load_field_value(
        cls,
        field_name: str,
        user_id: str,
        workflow_id: UUID,
        node_id: str,
        pool,
        context: Optional[Dict[str, Any]] = None,
        credential_ids: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Load webhook URL for the receive_webhook operation.

        Creates our internal webhook URL and registers it with Instantly's API.
        """
        if field_name != "webhook_url":
            return {"value": None}

        from utils.webhook_manager import WebhookManager

        # Create our internal webhook URL
        webhook_data = await WebhookManager.get_or_create_webhook(
            pool=pool,
            user_id=user_id,
            workflow_id=workflow_id,
            node_id=node_id,
        )

        result = {
            "webhook_id": webhook_data.get("webhook_id"),
            "webhook_url": webhook_data.get("webhook_url"),
            "relay_connected": webhook_data.get("relay_connected"),
            "is_production": webhook_data.get("is_production"),
        }

        # Try to register the webhook URL with Instantly's API
        credential_id = None
        if credential_ids:
            credential_id = credential_ids.get("instantly_api_key")

        if credential_id and webhook_data.get("webhook_url"):
            try:
                from utils.encryption import get_encryption
                from repositories.credentials import credential_access_predicate
                from repositories.organization import PRIMARY_ORG_SQL

                async with pool.acquire() as conn:
                    org_row = await conn.fetchrow(PRIMARY_ORG_SQL, user_id)
                    org_id = str(org_row["organization_id"]) if org_row else None

                    row = await conn.fetchrow(
                        f"""
                        SELECT c.credential
                        FROM credentials c
                        WHERE c.id = $1
                          AND {credential_access_predicate()}
                        """,
                        credential_id,
                        user_id,
                        org_id,
                    )

                if row:
                    encryption = get_encryption()
                    credential_data = encryption.decrypt_credential(row["credential"])
                    api_key = credential_data.get("api_key")

                    if api_key:
                        # Get the event type from node context
                        event_type = "reply_received"
                        old_instantly_webhook_id = None
                        if context and context.get("config"):
                            event_type = context["config"].get(
                                "event_type", "reply_received"
                            )
                            old_instantly_webhook_id = context["config"].get(
                                "instantly_webhook_id"
                            )

                        # Delete old Instantly webhook before re-registering
                        if old_instantly_webhook_id:
                            await delete_instantly_webhook(
                                api_key, old_instantly_webhook_id
                            )

                        # Register webhook with Instantly
                        reg_result = await register_instantly_webhook(
                            api_key, webhook_data["webhook_url"], event_type
                        )
                        if reg_result.get("success"):
                            result["instantly_webhook_id"] = reg_result[
                                "instantly_webhook_id"
                            ]
            except Exception as e:
                logger.warning(
                    f"[InstantlyNode] Could not register webhook with Instantly: {e}"
                )

        return {"values": result}

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()

        config = self.config
        if not config or not isinstance(config, InstantlyNodeConfig):
            raise ValueError("Valid configuration is required")

        op_config = config.config

        # Webhook trigger mode — re-register webhook and pass through payload
        if isinstance(op_config, InstantlyReceiveWebhookConfig):
            credentials = config.credentials
            registration_info = {}

            # When executed manually, re-register the webhook with Instantly
            if credentials and credentials.api_key and op_config.webhook_url:
                # Delete old webhook if it exists
                if op_config.instantly_webhook_id:
                    await delete_instantly_webhook(
                        credentials.api_key, op_config.instantly_webhook_id
                    )

                # Re-register with current credentials and event type
                reg_result = await register_instantly_webhook(
                    credentials.api_key,
                    op_config.webhook_url,
                    op_config.event_type,
                )
                if reg_result.get("success"):
                    registration_info["instantly_webhook_id"] = reg_result[
                        "instantly_webhook_id"
                    ]
                    registration_info["registered"] = True
                else:
                    registration_info["registered"] = False
                    registration_info["error"] = reg_result.get("error")

            return {
                "status": "success",
                "action": "receive_webhook_events",
                "data": {
                    **inputs,
                    "webhook_url": op_config.webhook_url,
                    "event_type": op_config.event_type,
                    **registration_info,
                },
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your Instantly API key.")

        handlers = {
            # Accounts
            "list_email_accounts": self._handle_list_accounts,
            "get_email_account": self._handle_get_account,
            "create_email_account": self._handle_create_account,
            "pause_email_account": self._handle_pause_account,
            "resume_email_account": self._handle_resume_account,
            "delete_email_account": self._handle_delete_account,
            # Campaigns
            "list_campaigns": self._handle_list_campaigns,
            "get_campaign": self._handle_get_campaign,
            "create_campaign": self._handle_create_campaign,
            "update_campaign": self._handle_update_campaign,
            "delete_campaign": self._handle_delete_campaign,
            "activate_campaign": self._handle_activate_campaign,
            "pause_campaign": self._handle_pause_campaign,
            "search_campaigns_by_contact_email": self._handle_search_campaigns_by_contact,
            # Leads
            "list_leads": self._handle_list_leads,
            "get_lead": self._handle_get_lead,
            "create_lead": self._handle_create_lead,
            "update_lead": self._handle_update_lead,
            "delete_lead": self._handle_delete_lead,
            "bulk_add_leads_to_campaign": self._handle_bulk_add_leads,
            "move_leads_to_campaign": self._handle_move_lead,
            # Lead Lists
            "list_lead_lists": self._handle_list_lead_lists,
            "get_lead_list": self._handle_get_lead_list,
            "create_lead_list": self._handle_create_lead_list,
            "update_lead_list": self._handle_update_lead_list,
            "delete_lead_list": self._handle_delete_lead_list,
            # Emails
            "list_emails": self._handle_list_emails,
            "get_email": self._handle_get_email,
            "reply_to_email": self._handle_reply_to_email,
            "count_unread_emails": self._handle_count_unread_emails,
            "mark_email_thread_as_read": self._handle_mark_thread_read,
            # Analytics
            "get_campaign_analytics": self._handle_get_campaign_analytics,
            "get_daily_campaign_analytics": self._handle_get_daily_campaign_analytics,
            "get_account_warmup_analytics": self._handle_get_warmup_analytics,
        }

        action = op_config.operation
        handler = handlers.get(action)
        if not handler:
            raise ValueError(f"Unknown action: {action}")

        result = await handler(op_config, credentials)

        total_time = (time.time() - start_time) * 1000
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round(total_time, 2),
        }
        return result

    # =========================================================================
    # HTTP Request Helper
    # =========================================================================

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        credentials: InstantlyCredential,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        action_name: str = "request",
    ) -> Dict[str, Any]:
        url = f"{INSTANTLY_API_BASE}{endpoint}"
        headers = {
            "Authorization": f"Bearer {credentials.api_key}",
            "Content-Type": "application/json",
        }

        if params:
            params = {k: v for k, v in params.items() if v is not None}
        if json_body:
            json_body = {k: v for k, v in json_body.items() if v is not None}

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
                    error_text = response.text
                    try:
                        error_data = response.json()
                        error_message = error_data.get(
                            "message", error_data.get("error", str(error_data))
                        )
                    except Exception:
                        error_message = error_text
                    # Sanitize for ASCII-safe logging/serialization
                    if isinstance(error_message, str):
                        error_message = error_message.encode(
                            "ascii", errors="replace"
                        ).decode("ascii")

                    logger.error(
                        f"[InstantlyNode] API error ({action_name}): {error_message}"
                    )
                    return {
                        "status": "error",
                        "action": action_name,
                        "error": error_message,
                        "status_code": response.status_code,
                        "timing_ms": {"api_request": round(api_time, 2)},
                    }

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
                # Ensure error message is ASCII-safe to prevent encoding issues in logging/serialization
                error_msg = str(e).encode("ascii", errors="replace").decode("ascii")
                logger.error(
                    f"[InstantlyNode] Request failed ({action_name}): {error_msg}"
                )
                return {
                    "status": "error",
                    "action": action_name,
                    "error": error_msg,
                    "status_code": 500,
                    "timing_ms": {
                        "api_request": round((time.time() - start_time) * 1000, 2)
                    },
                }

    # =========================================================================
    # Account Handlers
    # =========================================================================

    async def _handle_list_accounts(
        self, config: InstantlyListAccountsConfig, credentials
    ) -> Dict[str, Any]:
        return await self._make_request(
            "GET",
            "/accounts",
            credentials,
            params={
                "limit": config.limit,
                "starting_after": config.starting_after,
                "search": config.search,
            },
            action_name="list_email_accounts",
        )

    async def _handle_get_account(
        self, config: InstantlyGetAccountConfig, credentials
    ) -> Dict[str, Any]:
        return await self._make_request(
            "GET", f"/accounts/{config.email}", credentials, action_name="get_email_account"
        )

    async def _handle_create_account(
        self, config: InstantlyCreateAccountConfig, credentials
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "email": config.email,
            "first_name": config.first_name,
            "last_name": config.last_name,
            "provider_code": int(config.provider_code),
        }
        if config.daily_limit:
            body["daily_limit"] = int(config.daily_limit)
        return await self._make_request(
            "POST",
            "/accounts",
            credentials,
            json_body=body,
            action_name="create_email_account",
        )

    async def _handle_pause_account(
        self, config: InstantlyPauseAccountConfig, credentials
    ) -> Dict[str, Any]:
        return await self._make_request(
            "POST",
            f"/accounts/{config.email}/pause",
            credentials,
            action_name="pause_email_account",
        )

    async def _handle_resume_account(
        self, config: InstantlyResumeAccountConfig, credentials
    ) -> Dict[str, Any]:
        return await self._make_request(
            "POST",
            f"/accounts/{config.email}/resume",
            credentials,
            action_name="resume_email_account",
        )

    async def _handle_delete_account(
        self, config: InstantlyDeleteAccountConfig, credentials
    ) -> Dict[str, Any]:
        return await self._make_request(
            "DELETE",
            f"/accounts/{config.email}",
            credentials,
            action_name="delete_email_account",
        )

    # =========================================================================
    # Campaign Handlers
    # =========================================================================

    async def _handle_list_campaigns(
        self, config: InstantlyListCampaignsConfig, credentials
    ) -> Dict[str, Any]:
        return await self._make_request(
            "GET",
            "/campaigns",
            credentials,
            params={
                "limit": config.limit,
                "starting_after": config.starting_after,
                "search": config.search,
            },
            action_name="list_campaigns",
        )

    async def _handle_get_campaign(
        self, config: InstantlyGetCampaignConfig, credentials
    ) -> Dict[str, Any]:
        return await self._make_request(
            "GET",
            f"/campaigns/{config.campaign_id}",
            credentials,
            action_name="get_campaign",
        )

    async def _handle_create_campaign(
        self, config: InstantlyCreateCampaignConfig, credentials
    ) -> Dict[str, Any]:
        return await self._make_request(
            "POST",
            "/campaigns",
            credentials,
            json_body={
                "name": config.name,
            },
            action_name="create_campaign",
        )

    async def _handle_update_campaign(
        self, config: InstantlyUpdateCampaignConfig, credentials
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        if config.name is not None:
            body["name"] = config.name
        return await self._make_request(
            "PATCH",
            f"/campaigns/{config.campaign_id}",
            credentials,
            json_body=body,
            action_name="update_campaign",
        )

    async def _handle_delete_campaign(
        self, config: InstantlyDeleteCampaignConfig, credentials
    ) -> Dict[str, Any]:
        return await self._make_request(
            "DELETE",
            f"/campaigns/{config.campaign_id}",
            credentials,
            action_name="delete_campaign",
        )

    async def _handle_activate_campaign(
        self, config: InstantlyActivateCampaignConfig, credentials
    ) -> Dict[str, Any]:
        return await self._make_request(
            "POST",
            f"/campaigns/{config.campaign_id}/activate",
            credentials,
            action_name="activate_campaign",
        )

    async def _handle_pause_campaign(
        self, config: InstantlyPauseCampaignConfig, credentials
    ) -> Dict[str, Any]:
        return await self._make_request(
            "POST",
            f"/campaigns/{config.campaign_id}/stop",
            credentials,
            action_name="pause_campaign",
        )

    async def _handle_search_campaigns_by_contact(
        self, config: InstantlySearchCampaignsByContactConfig, credentials
    ) -> Dict[str, Any]:
        return await self._make_request(
            "GET",
            "/campaigns/search-by-lead-email",
            credentials,
            params={
                "email": config.email,
            },
            action_name="search_campaigns_by_contact_email",
        )

    # =========================================================================
    # Lead Handlers
    # =========================================================================

    async def _handle_list_leads(
        self, config: InstantlyListLeadsConfig, credentials
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        if config.campaign_id:
            body["campaign_id"] = config.campaign_id
        if config.list_id:
            body["list_id"] = config.list_id
        if config.limit:
            body["limit"] = int(config.limit)
        if config.starting_after:
            body["starting_after"] = config.starting_after
        if config.email:
            body["email"] = config.email
        return await self._make_request(
            "POST", "/leads/list", credentials, json_body=body, action_name="list_leads"
        )

    async def _handle_get_lead(
        self, config: InstantlyGetLeadConfig, credentials
    ) -> Dict[str, Any]:
        return await self._make_request(
            "GET", f"/leads/{config.lead_id}", credentials, action_name="get_lead"
        )

    async def _handle_create_lead(
        self, config: InstantlyCreateLeadConfig, credentials
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {"email": config.email}
        if config.first_name:
            body["first_name"] = config.first_name
        if config.last_name:
            body["last_name"] = config.last_name
        if config.company_name:
            body["company_name"] = config.company_name
        if config.website:
            body["website"] = config.website
        if config.phone:
            body["phone"] = config.phone
        if config.campaign:
            body["campaign"] = config.campaign
        if config.list_id:
            body["list_id"] = config.list_id
        return await self._make_request(
            "POST", "/leads", credentials, json_body=body, action_name="create_lead"
        )

    async def _handle_update_lead(
        self, config: InstantlyUpdateLeadConfig, credentials
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        if config.first_name is not None:
            body["first_name"] = config.first_name
        if config.last_name is not None:
            body["last_name"] = config.last_name
        if config.company_name is not None:
            body["company_name"] = config.company_name
        if config.website is not None:
            body["website"] = config.website
        if config.phone is not None:
            body["phone"] = config.phone
        return await self._make_request(
            "PATCH",
            f"/leads/{config.lead_id}",
            credentials,
            json_body=body,
            action_name="update_lead",
        )

    async def _handle_delete_lead(
        self, config: InstantlyDeleteLeadConfig, credentials
    ) -> Dict[str, Any]:
        return await self._make_request(
            "DELETE", f"/leads/{config.lead_id}", credentials, action_name="delete_lead"
        )

    async def _handle_bulk_add_leads(
        self, config: InstantlyBulkAddLeadsConfig, credentials
    ) -> Dict[str, Any]:
        import json

        try:
            leads_data = json.loads(config.leads)
        except json.JSONDecodeError as e:
            return {
                "status": "error",
                "action": "bulk_add_leads_to_campaign",
                "error": f"Invalid JSON for leads: {e}",
                "status_code": 400,
                "timing_ms": {},
            }
        body: Dict[str, Any] = {"leads": leads_data}
        if config.campaign_id:
            body["campaign_id"] = config.campaign_id
        if config.list_id:
            body["list_id"] = config.list_id
        return await self._make_request(
            "POST",
            "/leads/add",
            credentials,
            json_body=body,
            action_name="bulk_add_leads_to_campaign",
        )

    async def _handle_move_lead(
        self, config: InstantlyMoveLeadConfig, credentials
    ) -> Dict[str, Any]:
        ids = [lid.strip() for lid in config.lead_ids.split(",") if lid.strip()]
        body: Dict[str, Any] = {"ids": ids}
        if config.to_campaign_id:
            body["to_campaign_id"] = config.to_campaign_id
        if config.to_list_id:
            body["to_list_id"] = config.to_list_id
        return await self._make_request(
            "POST", "/leads/move", credentials, json_body=body, action_name="move_leads_to_campaign"
        )

    # =========================================================================
    # Lead List Handlers
    # =========================================================================

    async def _handle_list_lead_lists(
        self, config: InstantlyListLeadListsConfig, credentials
    ) -> Dict[str, Any]:
        return await self._make_request(
            "GET",
            "/lead-lists",
            credentials,
            params={
                "limit": config.limit,
                "starting_after": config.starting_after,
            },
            action_name="list_lead_lists",
        )

    async def _handle_get_lead_list(
        self, config: InstantlyGetLeadListConfig, credentials
    ) -> Dict[str, Any]:
        return await self._make_request(
            "GET",
            f"/lead-lists/{config.list_id}",
            credentials,
            action_name="get_lead_list",
        )

    async def _handle_create_lead_list(
        self, config: InstantlyCreateLeadListConfig, credentials
    ) -> Dict[str, Any]:
        return await self._make_request(
            "POST",
            "/lead-lists",
            credentials,
            json_body={
                "name": config.name,
            },
            action_name="create_lead_list",
        )

    async def _handle_update_lead_list(
        self, config: InstantlyUpdateLeadListConfig, credentials
    ) -> Dict[str, Any]:
        return await self._make_request(
            "PATCH",
            f"/lead-lists/{config.list_id}",
            credentials,
            json_body={
                "name": config.name,
            },
            action_name="update_lead_list",
        )

    async def _handle_delete_lead_list(
        self, config: InstantlyDeleteLeadListConfig, credentials
    ) -> Dict[str, Any]:
        return await self._make_request(
            "DELETE",
            f"/lead-lists/{config.list_id}",
            credentials,
            action_name="delete_lead_list",
        )

    # =========================================================================
    # Email Handlers
    # =========================================================================

    async def _handle_list_emails(
        self, config: InstantlyListEmailsConfig, credentials
    ) -> Dict[str, Any]:
        return await self._make_request(
            "GET",
            "/emails",
            credentials,
            params={
                "campaign_id": config.campaign_id,
                "lead_email": config.lead_email,
                "limit": config.limit,
            },
            action_name="list_emails",
        )

    async def _handle_get_email(
        self, config: InstantlyGetEmailConfig, credentials
    ) -> Dict[str, Any]:
        return await self._make_request(
            "GET", f"/emails/{config.email_id}", credentials, action_name="get_email"
        )

    async def _handle_reply_to_email(
        self, config: InstantlyReplyToEmailConfig, credentials
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "reply_to_uuid": config.reply_to_uuid,
            "eaccount": config.eaccount,
            "subject": config.subject,
            "body": {"html": config.body},
        }
        if config.cc:
            body["cc_address_email_list"] = config.cc
        if config.bcc:
            body["bcc_address_email_list"] = config.bcc
        return await self._make_request(
            "POST",
            "/emails/reply",
            credentials,
            json_body=body,
            action_name="reply_to_email",
        )

    async def _handle_count_unread_emails(
        self, config: InstantlyCountUnreadEmailsConfig, credentials
    ) -> Dict[str, Any]:
        return await self._make_request(
            "GET",
            "/emails/unread-count",
            credentials,
            action_name="count_unread_emails",
        )

    async def _handle_mark_thread_read(
        self, config: InstantlyMarkThreadReadConfig, credentials
    ) -> Dict[str, Any]:
        return await self._make_request(
            "POST",
            "/emails/thread/mark-read",
            credentials,
            json_body={
                "thread_id": config.thread_id,
            },
            action_name="mark_email_thread_as_read",
        )

    # =========================================================================
    # Analytics Handlers
    # =========================================================================

    async def _handle_get_campaign_analytics(
        self, config: InstantlyGetCampaignAnalyticsConfig, credentials
    ) -> Dict[str, Any]:
        return await self._make_request(
            "GET",
            f"/campaigns/{config.campaign_id}/analytics",
            credentials,
            params={
                "start_date": config.start_date,
                "end_date": config.end_date,
            },
            action_name="get_campaign_analytics",
        )

    async def _handle_get_daily_campaign_analytics(
        self, config: InstantlyGetDailyCampaignAnalyticsConfig, credentials
    ) -> Dict[str, Any]:
        return await self._make_request(
            "GET",
            "/campaigns/analytics/daily",
            credentials,
            params={
                "campaign_id": config.campaign_id,
                "start_date": config.start_date,
                "end_date": config.end_date,
            },
            action_name="get_daily_campaign_analytics",
        )

    async def _handle_get_warmup_analytics(
        self, config: InstantlyGetWarmupAnalyticsConfig, credentials
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {"email": config.email}
        if config.start_date:
            body["start_date"] = config.start_date
        if config.end_date:
            body["end_date"] = config.end_date
        return await self._make_request(
            "POST",
            "/warmup/analytics",
            credentials,
            json_body=body,
            action_name="get_account_warmup_analytics",
        )
