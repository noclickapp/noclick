"""
Mailgun email automation node.

Provides workflow integration with the Mailgun REST API for operations including:
- Messages: send message, send MIME, get stored message
- Analytics: list events, query logs, get metrics
- Domains: list, create, get, verify, delete
- Mailing Lists: list, create, list members, add member, bulk add, delete member
- Templates: list, create, get, create version
- Routes: list, create, delete
- Webhooks: list, create, delete
- Suppressions: list bounces, add unsubscribes
- Validation: validate email address
- Triggers: granular per-event webhooks (accepted, delivered, opened, clicked,
  unsubscribed, spam complaint, hard/soft bounce) + an inbound-email trigger that
  forwards received mail via a Mailgun route. All signatures are HMAC-verified.

Authentication: API key via HTTP Basic Auth (username `api`, password = API key).
Mailgun does not support OAuth 2.0.
API Base URL: https://api.mailgun.net (US) / https://api.eu.mailgun.net (EU).
Path prefix differs per resource: /v3 (messages/lists/routes/suppressions/
templates/domain-webhooks; domain delete), /v4 (domains list/create/get/verify,
validation), /v1 (logs/metrics).
Documentation: https://documentation.mailgun.com/docs/mailgun/api-reference/
"""

import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Dict, Any, Optional, List, Literal, Tuple, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator, field_validator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase

logger = logging.getLogger(__name__)

MAILGUN_API_BASE_US = "https://api.mailgun.net"
MAILGUN_API_BASE_EU = "https://api.eu.mailgun.net"

# Event types Mailgun can POST to a webhook URL.
WEBHOOK_TRIGGER_EVENTS = [
    "accepted",
    "delivered",
    "opened",
    "clicked",
    "unsubscribed",
    "complained",
    "permanent_fail",
    "temporary_fail",
]


# ============================================================================
# Credential Schema
# ============================================================================


class MailgunApiKeyCredential(BaseModel):
    """API Key credential for Mailgun (HTTP Basic Auth, username `api`)."""

    credential_type: Literal["mailgun_api_key"] = Field(
        "mailgun_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="Private API Key",
        description="Your Mailgun Private API key from Account Settings -> API Keys",
        json_schema_extra={"ui:widget": "password"},
    )
    region: str = Field(
        "us",
        title="Region",
        description="Mailgun account region. EU accounts must select EU.",
        json_schema_extra={
            "enum": ["us", "eu"],
            "enumNames": ["US (api.mailgun.net)", "EU (api.eu.mailgun.net)"],
            "x-enum-searchable": True,
        },
    )
    webhook_signing_key: Optional[str] = Field(
        None,
        title="Webhook Signing Key",
        description="HTTP webhook signing key (Account Settings -> Webhooks) used to verify inbound event signatures",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://app.mailgun.com/app/account/security/api_keys"
        }
    )


MailgunCredential = MailgunApiKeyCredential


# ============================================================================
# Operation Configs
# ============================================================================


class MailgunSendMessageConfig(BaseModel):
    """Send an email message through a sending domain."""

    operation: Literal["send_message"] = Field(
        "send_message",
        json_schema_extra={
            "const": "send_message",
            "ui:hidden": True,
            "x-category": "Messages",
            "x-is-trigger": False,
            "x-display-name": "Send Message",
        },
        title="Send Message",
    )
    domain: str = Field(
        ...,
        title="Sending Domain",
        description="The verified sending domain (e.g. mg.example.com)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "domain",
                "placeholder": "Select a domain...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a domain name",
            },
            "x-resource-type": "mailgun_domain",
        },
    )
    from_address: str = Field(
        ...,
        title="From",
        description='Sender address, optionally with a name: "Excited User <mailgun@example.com>"',
    )
    to: str = Field(
        ...,
        title="To",
        description="Recipient address(es), comma-separated",
    )
    subject: str = Field(..., title="Subject", description="Email subject line")
    text: Optional[str] = Field(
        None,
        title="Plain Text Body",
        description="Plain text version of the message body",
        json_schema_extra={"ui:widget": "textarea"},
    )
    html: Optional[str] = Field(
        None,
        title="HTML Body",
        description="HTML version of the message body",
        json_schema_extra={"ui:widget": "textarea"},
    )
    cc: Optional[str] = Field(None, title="CC", description="CC recipients, comma-separated")
    bcc: Optional[str] = Field(None, title="BCC", description="BCC recipients, comma-separated")
    template: Optional[str] = Field(
        None, title="Template", description="Name of a stored template to render"
    )
    variables: Optional[str] = Field(
        None,
        title="Template Variables",
        description='JSON object of variables for the template (e.g. {"name": "Ada"})',
        json_schema_extra={"ui:widget": "textarea"},
    )
    attachments: List[str] = Field(
        default_factory=list,
        title="Attachments",
        description="Files to attach: workflow resource ids or URLs (max 10MB per file, 20MB total)",
        json_schema_extra={"ui:widget": "list", "placeholder": "{{node.resource_id}}"},
    )

    @field_validator("attachments", mode="before")
    @classmethod
    def filter_attachments(cls, v: Any) -> list:
        if not isinstance(v, list):
            return []
        return [a for a in v if isinstance(a, str) and a.strip()]


class MailgunSendMimeConfig(BaseModel):
    """Send a pre-built raw MIME (RFC 2822) message."""

    operation: Literal["send_mime"] = Field(
        "send_mime",
        json_schema_extra={
            "const": "send_mime",
            "ui:hidden": True,
            "x-category": "Messages",
            "x-is-trigger": False,
            "x-display-name": "Send MIME Message",
        },
        title="Send MIME Message",
    )
    domain: str = Field(..., title="Sending Domain", description="The verified sending domain")
    to: str = Field(..., title="To", description="Recipient address(es), comma-separated")
    message: str = Field(
        ...,
        title="MIME Message",
        description="The full raw MIME (RFC 2822) message body",
        json_schema_extra={"ui:widget": "textarea"},
    )


class MailgunGetStoredMessageConfig(BaseModel):
    """Retrieve a stored / inbound message by its storage key."""

    operation: Literal["get_stored_message"] = Field(
        "get_stored_message",
        json_schema_extra={
            "const": "get_stored_message",
            "ui:hidden": True,
            "x-category": "Messages",
            "x-is-trigger": False,
            "x-display-name": "Get Stored Message",
        },
        title="Get Stored Message",
    )
    domain: str = Field(..., title="Domain", description="The domain the message belongs to")
    storage_key: str = Field(
        ..., title="Storage Key", description="The storage key identifying the stored message"
    )


class MailgunListEventsConfig(BaseModel):
    """Query message events (accepted, delivered, opened, failed, ...)."""

    operation: Literal["list_events"] = Field(
        "list_events",
        json_schema_extra={
            "const": "list_events",
            "ui:hidden": True,
            "x-category": "Analytics",
            "x-is-trigger": False,
            "x-display-name": "List Events",
        },
        title="List Events",
    )
    domain: str = Field(..., title="Domain", description="The sending domain to query events for")
    event: Optional[str] = Field(
        None,
        title="Event Type",
        description="Filter to a single event type (e.g. delivered, failed)",
        json_schema_extra={
            "enum": ["", *WEBHOOK_TRIGGER_EVENTS, "failed", "stored", "rejected"],
            "x-enum-searchable": True,
        },
    )
    limit: Optional[str] = Field(
        "100", title="Limit", description="Max number of events to return (1-300)"
    )


class MailgunQueryLogsConfig(BaseModel):
    """Query the newer Logs/analytics API for message activity."""

    operation: Literal["query_logs"] = Field(
        "query_logs",
        json_schema_extra={
            "const": "query_logs",
            "ui:hidden": True,
            "x-category": "Analytics",
            "x-is-trigger": False,
            "x-display-name": "Query Logs",
        },
        title="Query Logs",
    )
    start: str = Field(
        ..., title="Start", description="Start of the time window (RFC 2822 or Unix timestamp)"
    )
    end: str = Field(
        ..., title="End", description="End of the time window (RFC 2822 or Unix timestamp)"
    )
    filter_json: Optional[str] = Field(
        None,
        title="Filter (JSON)",
        description='Optional JSON filter object passed through to the Logs API',
        json_schema_extra={"ui:widget": "textarea"},
    )


class MailgunGetMetricsConfig(BaseModel):
    """Retrieve aggregated sending analytics (Metrics API)."""

    operation: Literal["get_metrics"] = Field(
        "get_metrics",
        json_schema_extra={
            "const": "get_metrics",
            "ui:hidden": True,
            "x-category": "Analytics",
            "x-is-trigger": False,
            "x-display-name": "Get Metrics",
        },
        title="Get Metrics",
    )
    start: str = Field(
        ..., title="Start", description="Start of the time window (RFC 2822 or Unix timestamp)"
    )
    end: str = Field(
        ..., title="End", description="End of the time window (RFC 2822 or Unix timestamp)"
    )
    metrics_json: Optional[str] = Field(
        None,
        title="Metrics (JSON)",
        description='JSON array of metric names to aggregate (e.g. ["delivered_count","opened_count"])',
        json_schema_extra={"ui:widget": "textarea"},
    )


class MailgunListDomainsConfig(BaseModel):
    """List sending domains."""

    operation: Literal["list_domains"] = Field(
        "list_domains",
        json_schema_extra={
            "const": "list_domains",
            "ui:hidden": True,
            "x-category": "Domains",
            "x-is-trigger": False,
            "x-display-name": "List Domains",
        },
        title="List Domains",
    )
    limit: Optional[str] = Field(
        "100", title="Limit", description="Max number of domains to return"
    )


class MailgunCreateDomainConfig(BaseModel):
    """Add a new sending domain."""

    operation: Literal["create_domain"] = Field(
        "create_domain",
        json_schema_extra={
            "const": "create_domain",
            "ui:hidden": True,
            "x-category": "Domains",
            "x-is-trigger": False,
            "x-display-name": "Create Domain",
            "x-creates-resource": True,
            "x-resource-type": "mailgun_domain",
            "x-resource-id-path": "data.domain.name",
        },
        title="Create Domain",
    )
    name: str = Field(..., title="Domain Name", description="The domain to add (e.g. mg.example.com)")


class MailgunGetDomainConfig(BaseModel):
    """Get details and DNS records for a domain."""

    operation: Literal["get_domain"] = Field(
        "get_domain",
        json_schema_extra={
            "const": "get_domain",
            "ui:hidden": True,
            "x-category": "Domains",
            "x-is-trigger": False,
            "x-display-name": "Get Domain",
        },
        title="Get Domain",
    )
    name: str = Field(
        ...,
        title="Domain Name",
        description="The domain to retrieve",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "name",
                "placeholder": "Select a domain...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a domain name",
            },
            "x-resource-type": "mailgun_domain",
        },
    )


class MailgunVerifyDomainConfig(BaseModel):
    """Trigger / check DNS verification for a domain."""

    operation: Literal["verify_domain"] = Field(
        "verify_domain",
        json_schema_extra={
            "const": "verify_domain",
            "ui:hidden": True,
            "x-category": "Domains",
            "x-is-trigger": False,
            "x-display-name": "Verify Domain",
        },
        title="Verify Domain",
    )
    name: str = Field(..., title="Domain Name", description="The domain to verify")


class MailgunDeleteDomainConfig(BaseModel):
    """Remove a sending domain."""

    operation: Literal["delete_domain"] = Field(
        "delete_domain",
        json_schema_extra={
            "const": "delete_domain",
            "ui:hidden": True,
            "x-category": "Domains",
            "x-is-trigger": False,
            "x-display-name": "Delete Domain",
        },
        title="Delete Domain",
    )
    name: str = Field(..., title="Domain Name", description="The domain to delete")


class MailgunListMailingListsConfig(BaseModel):
    """List all mailing lists."""

    operation: Literal["list_mailing_lists"] = Field(
        "list_mailing_lists",
        json_schema_extra={
            "const": "list_mailing_lists",
            "ui:hidden": True,
            "x-category": "Mailing Lists",
            "x-is-trigger": False,
            "x-display-name": "List Mailing Lists",
        },
        title="List Mailing Lists",
    )
    limit: Optional[str] = Field("100", title="Limit", description="Max number of lists to return")


class MailgunCreateMailingListConfig(BaseModel):
    """Create a new mailing list."""

    operation: Literal["create_mailing_list"] = Field(
        "create_mailing_list",
        json_schema_extra={
            "const": "create_mailing_list",
            "ui:hidden": True,
            "x-category": "Mailing Lists",
            "x-is-trigger": False,
            "x-display-name": "Create Mailing List",
        },
        title="Create Mailing List",
    )
    address: str = Field(
        ..., title="List Address", description="Email address for the list (e.g. team@example.com)"
    )
    name: Optional[str] = Field(None, title="Name", description="Display name for the list")
    description: Optional[str] = Field(
        None, title="Description", description="Optional description of the list"
    )


class MailgunListMembersConfig(BaseModel):
    """List members of a mailing list."""

    operation: Literal["list_members"] = Field(
        "list_members",
        json_schema_extra={
            "const": "list_members",
            "ui:hidden": True,
            "x-category": "Mailing Lists",
            "x-is-trigger": False,
            "x-display-name": "List Members",
        },
        title="List Members",
    )
    list_address: str = Field(
        ..., title="List Address", description="The mailing list address to list members of"
    )
    limit: Optional[str] = Field("100", title="Limit", description="Max number of members to return")


class MailgunAddMemberConfig(BaseModel):
    """Add a single member to a mailing list."""

    operation: Literal["add_member"] = Field(
        "add_member",
        json_schema_extra={
            "const": "add_member",
            "ui:hidden": True,
            "x-category": "Mailing Lists",
            "x-is-trigger": False,
            "x-display-name": "Add Member",
        },
        title="Add Member",
    )
    list_address: str = Field(
        ..., title="List Address", description="The mailing list to add the member to"
    )
    address: str = Field(..., title="Member Address", description="The member's email address")
    name: Optional[str] = Field(None, title="Name", description="The member's name")
    vars_json: Optional[str] = Field(
        None,
        title="Variables (JSON)",
        description='JSON object of member variables (e.g. {"plan": "pro"})',
        json_schema_extra={"ui:widget": "textarea"},
    )
    subscribed: str = Field(
        "yes",
        title="Subscribed",
        description="Whether the member is subscribed",
        json_schema_extra={
            "enum": ["yes", "no"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class MailgunBulkAddMembersConfig(BaseModel):
    """Add up to 1000 members to a mailing list in one call."""

    operation: Literal["bulk_add_members"] = Field(
        "bulk_add_members",
        json_schema_extra={
            "const": "bulk_add_members",
            "ui:hidden": True,
            "x-category": "Mailing Lists",
            "x-is-trigger": False,
            "x-display-name": "Bulk Add Members",
        },
        title="Bulk Add Members",
    )
    list_address: str = Field(
        ..., title="List Address", description="The mailing list to add members to"
    )
    members_json: str = Field(
        ...,
        title="Members (JSON)",
        description='JSON array of member objects (e.g. [{"address":"a@x.com","name":"A"}])',
        json_schema_extra={"ui:widget": "textarea"},
    )
    upsert: str = Field(
        "no",
        title="Upsert",
        description="Update existing members instead of erroring on duplicates",
        json_schema_extra={
            "enum": ["yes", "no"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class MailgunDeleteMemberConfig(BaseModel):
    """Remove a member from a mailing list."""

    operation: Literal["delete_member"] = Field(
        "delete_member",
        json_schema_extra={
            "const": "delete_member",
            "ui:hidden": True,
            "x-category": "Mailing Lists",
            "x-is-trigger": False,
            "x-display-name": "Delete Member",
        },
        title="Delete Member",
    )
    list_address: str = Field(
        ..., title="List Address", description="The mailing list to remove the member from"
    )
    member_address: str = Field(
        ..., title="Member Address", description="The member email address to remove"
    )


class MailgunListTemplatesConfig(BaseModel):
    """List stored account-level templates."""

    operation: Literal["list_templates"] = Field(
        "list_templates",
        json_schema_extra={
            "const": "list_templates",
            "ui:hidden": True,
            "x-category": "Templates",
            "x-is-trigger": False,
            "x-display-name": "List Templates",
        },
        title="List Templates",
    )
    domain: str = Field(..., title="Domain", description="The domain the templates belong to")
    limit: Optional[str] = Field("100", title="Limit", description="Max number of templates to return")


class MailgunCreateTemplateConfig(BaseModel):
    """Store a new reusable email template."""

    operation: Literal["create_template"] = Field(
        "create_template",
        json_schema_extra={
            "const": "create_template",
            "ui:hidden": True,
            "x-category": "Templates",
            "x-is-trigger": False,
            "x-display-name": "Create Template",
        },
        title="Create Template",
    )
    domain: str = Field(..., title="Domain", description="The domain to store the template under")
    name: str = Field(..., title="Template Name", description="Unique name for the template")
    template: str = Field(
        ...,
        title="Template Content",
        description="The template HTML/handlebars content",
        json_schema_extra={"ui:widget": "textarea"},
    )
    description: Optional[str] = Field(
        None, title="Description", description="Optional template description"
    )


class MailgunGetTemplateConfig(BaseModel):
    """Retrieve a template and its versions."""

    operation: Literal["get_template"] = Field(
        "get_template",
        json_schema_extra={
            "const": "get_template",
            "ui:hidden": True,
            "x-category": "Templates",
            "x-is-trigger": False,
            "x-display-name": "Get Template",
        },
        title="Get Template",
    )
    domain: str = Field(..., title="Domain", description="The domain the template belongs to")
    template_name: str = Field(..., title="Template Name", description="The template to retrieve")


class MailgunCreateTemplateVersionConfig(BaseModel):
    """Add a new version to an existing template."""

    operation: Literal["create_template_version"] = Field(
        "create_template_version",
        json_schema_extra={
            "const": "create_template_version",
            "ui:hidden": True,
            "x-category": "Templates",
            "x-is-trigger": False,
            "x-display-name": "Create Template Version",
        },
        title="Create Template Version",
    )
    domain: str = Field(..., title="Domain", description="The domain the template belongs to")
    template_name: str = Field(..., title="Template Name", description="The template to add a version to")
    tag: str = Field(..., title="Version Tag", description="A tag identifying this version (e.g. v2)")
    template: str = Field(
        ...,
        title="Template Content",
        description="The template content for this version",
        json_schema_extra={"ui:widget": "textarea"},
    )
    active: str = Field(
        "yes",
        title="Active",
        description="Make this the active version",
        json_schema_extra={
            "enum": ["yes", "no"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class MailgunListRoutesConfig(BaseModel):
    """List inbound-email routing rules."""

    operation: Literal["list_routes"] = Field(
        "list_routes",
        json_schema_extra={
            "const": "list_routes",
            "ui:hidden": True,
            "x-category": "Routes",
            "x-is-trigger": False,
            "x-display-name": "List Routes",
        },
        title="List Routes",
    )
    limit: Optional[str] = Field("100", title="Limit", description="Max number of routes to return")


class MailgunCreateRouteConfig(BaseModel):
    """Create an inbound route (match expression -> action)."""

    operation: Literal["create_route"] = Field(
        "create_route",
        json_schema_extra={
            "const": "create_route",
            "ui:hidden": True,
            "x-category": "Routes",
            "x-is-trigger": False,
            "x-display-name": "Create Route",
        },
        title="Create Route",
    )
    expression: str = Field(
        ...,
        title="Match Expression",
        description='Match filter (e.g. match_recipient(".*@example.com"))',
    )
    action: str = Field(
        ...,
        title="Action",
        description='Action(s) to take, comma-separated (e.g. forward("https://...")), stop())',
    )
    priority: Optional[str] = Field(
        "0", title="Priority", description="Route priority (lower runs first)"
    )
    description: Optional[str] = Field(
        None, title="Description", description="Optional route description"
    )


class MailgunDeleteRouteConfig(BaseModel):
    """Delete an inbound route."""

    operation: Literal["delete_route"] = Field(
        "delete_route",
        json_schema_extra={
            "const": "delete_route",
            "ui:hidden": True,
            "x-category": "Routes",
            "x-is-trigger": False,
            "x-display-name": "Delete Route",
        },
        title="Delete Route",
    )
    route_id: str = Field(..., title="Route ID", description="The ID of the route to delete")


class MailgunListWebhooksConfig(BaseModel):
    """List configured event webhooks for a domain."""

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
    domain: str = Field(..., title="Domain", description="The domain to list webhooks for")


class MailgunListBouncesConfig(BaseModel):
    """List suppressed bounce addresses."""

    operation: Literal["list_bounces"] = Field(
        "list_bounces",
        json_schema_extra={
            "const": "list_bounces",
            "ui:hidden": True,
            "x-category": "Suppressions",
            "x-is-trigger": False,
            "x-display-name": "List Bounces",
        },
        title="List Bounces",
    )
    domain: str = Field(..., title="Domain", description="The domain to list bounces for")
    limit: Optional[str] = Field("100", title="Limit", description="Max number of bounces to return")


class MailgunAddUnsubscribesConfig(BaseModel):
    """Add an unsubscribe record to the suppression list."""

    operation: Literal["add_unsubscribe"] = Field(
        "add_unsubscribe",
        json_schema_extra={
            "const": "add_unsubscribe",
            "ui:hidden": True,
            "x-category": "Suppressions",
            "x-is-trigger": False,
            "x-display-name": "Add Unsubscribe",
        },
        title="Add Unsubscribe",
    )
    domain: str = Field(..., title="Domain", description="The domain to add the unsubscribe to")
    address: str = Field(..., title="Address", description="The email address to unsubscribe")
    tag: Optional[str] = Field(
        "*", title="Tag", description="Tag to unsubscribe from (* = all)"
    )


class MailgunValidateAddressConfig(BaseModel):
    """Validate a single email address (deliverability, risk, role flags)."""

    operation: Literal["validate_address"] = Field(
        "validate_address",
        json_schema_extra={
            "const": "validate_address",
            "ui:hidden": True,
            "x-category": "Validation",
            "x-is-trigger": False,
            "x-display-name": "Validate Email Address",
        },
        title="Validate Email Address",
    )
    address: str = Field(..., title="Email Address", description="The email address to validate")


# ============================================================================
# Webhook Trigger Config
# ============================================================================


# Each granular event trigger maps to one Mailgun webhook event id.
_EVENT_TRIGGER_MAP = {
    "on_accepted": "accepted",
    "on_delivered": "delivered",
    "on_opened": "opened",
    "on_clicked": "clicked",
    "on_unsubscribed": "unsubscribed",
    "on_spam_complaint": "complained",
    "on_hard_bounce": "permanent_fail",
    "on_soft_bounce": "temporary_fail",
}
INBOUND_TRIGGER_OP = "on_inbound_email"
TRIGGER_OPS = set(_EVENT_TRIGGER_MAP) | {INBOUND_TRIGGER_OP}


def _trigger_op_field(op: str, display: str):
    return Field(
        op,
        json_schema_extra={
            "const": op,
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": display,
        },
        title=display,
    )


class _MailgunTriggerBase(WebhookTriggerConfigBase):
    """Shared fields for every Mailgun trigger (event webhooks + inbound route).
    Webhook lifecycle fields are inherited from WebhookTriggerConfigBase."""

    domain: str = Field(
        ...,
        title="Domain",
        description="The domain to receive events / inbound mail for",
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="Mailgun posts here. Registered automatically when you connect credentials.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True},
    )


class MailgunOnAcceptedConfig(_MailgunTriggerBase):
    """Fire when Mailgun accepts a message for delivery."""
    operation: Literal["on_accepted"] = _trigger_op_field("on_accepted", "On Email Accepted")


class MailgunOnDeliveredConfig(_MailgunTriggerBase):
    """Fire when a message is delivered to the recipient's server."""
    operation: Literal["on_delivered"] = _trigger_op_field("on_delivered", "On Email Delivered")


class MailgunOnOpenedConfig(_MailgunTriggerBase):
    """Fire when a recipient opens a message (open tracking required)."""
    operation: Literal["on_opened"] = _trigger_op_field("on_opened", "On Email Opened")


class MailgunOnClickedConfig(_MailgunTriggerBase):
    """Fire when a recipient clicks a tracked link (click tracking required)."""
    operation: Literal["on_clicked"] = _trigger_op_field("on_clicked", "On Email Clicked")


class MailgunOnUnsubscribedConfig(_MailgunTriggerBase):
    """Fire when a recipient unsubscribes."""
    operation: Literal["on_unsubscribed"] = _trigger_op_field("on_unsubscribed", "On Unsubscribe")


class MailgunOnSpamComplaintConfig(_MailgunTriggerBase):
    """Fire when a recipient marks a message as spam."""
    operation: Literal["on_spam_complaint"] = _trigger_op_field("on_spam_complaint", "On Spam Complaint")


class MailgunOnHardBounceConfig(_MailgunTriggerBase):
    """Fire on a permanent failure / hard bounce."""
    operation: Literal["on_hard_bounce"] = _trigger_op_field("on_hard_bounce", "On Hard Bounce")


class MailgunOnSoftBounceConfig(_MailgunTriggerBase):
    """Fire on a temporary failure / soft bounce (deferred)."""
    operation: Literal["on_soft_bounce"] = _trigger_op_field("on_soft_bounce", "On Soft Bounce")


class MailgunOnInboundEmailConfig(_MailgunTriggerBase):
    """Fire when an email is RECEIVED at the domain (via a Mailgun route forward).

    Registers an account-level route ``match_recipient(".*@{domain}")`` →
    ``forward(webhook_url)`` so Mailgun POSTs the parsed inbound message here.
    """
    operation: Literal["on_inbound_email"] = _trigger_op_field("on_inbound_email", "On Inbound Email")


# ============================================================================
# Discriminated Union
# ============================================================================


MailgunConfig = Annotated[
    Union[
        MailgunSendMessageConfig,
        MailgunSendMimeConfig,
        MailgunGetStoredMessageConfig,
        MailgunListEventsConfig,
        MailgunQueryLogsConfig,
        MailgunGetMetricsConfig,
        MailgunListDomainsConfig,
        MailgunCreateDomainConfig,
        MailgunGetDomainConfig,
        MailgunVerifyDomainConfig,
        MailgunDeleteDomainConfig,
        MailgunListMailingListsConfig,
        MailgunCreateMailingListConfig,
        MailgunListMembersConfig,
        MailgunAddMemberConfig,
        MailgunBulkAddMembersConfig,
        MailgunDeleteMemberConfig,
        MailgunListTemplatesConfig,
        MailgunCreateTemplateConfig,
        MailgunGetTemplateConfig,
        MailgunCreateTemplateVersionConfig,
        MailgunListRoutesConfig,
        MailgunCreateRouteConfig,
        MailgunDeleteRouteConfig,
        MailgunListWebhooksConfig,
        MailgunListBouncesConfig,
        MailgunAddUnsubscribesConfig,
        MailgunValidateAddressConfig,
        MailgunOnAcceptedConfig,
        MailgunOnDeliveredConfig,
        MailgunOnOpenedConfig,
        MailgunOnClickedConfig,
        MailgunOnUnsubscribedConfig,
        MailgunOnSpamComplaintConfig,
        MailgunOnHardBounceConfig,
        MailgunOnSoftBounceConfig,
        MailgunOnInboundEmailConfig,
    ],
    Discriminator("operation"),
]


class MailgunNodeConfig(NodeConfig[MailgunConfig, MailgunCredential]):
    """Full configuration for the Mailgun node including credentials."""

    pass


# ============================================================================
# Helpers
# ============================================================================


def _base_url(region: Optional[str]) -> str:
    return MAILGUN_API_BASE_EU if (region or "us").lower() == "eu" else MAILGUN_API_BASE_US


def _comma_list(value: Optional[str]) -> Optional[List[str]]:
    if not value:
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return parts or None


def _parse_json(value: Optional[str], field: str) -> Any:
    if value is None or value == "":
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {field}: {e}")


def _multipart_text_field(body: bytes, content_type: str, name: str) -> Optional[str]:
    """Best-effort extraction of a plain-text multipart/form-data field value."""
    import re

    m = re.search(r'boundary=(?:"([^"]+)"|([^;]+))', content_type or "")
    if not m:
        return None
    boundary = (m.group(1) or m.group(2)).strip()
    target = b'name="' + name.encode() + b'"'
    for part in body.split(b"--" + boundary.encode()):
        if target not in part:
            continue
        idx = part.find(b"\r\n\r\n")
        off = 4
        if idx == -1:
            idx = part.find(b"\n\n")
            off = 2
        if idx != -1:
            return part[idx + off:].strip(b"\r\n-").decode("utf-8", "replace").strip()
    return None


def _extract_inbound_signature(body: bytes, headers: Dict[str, str]):
    """Pull (timestamp, token, signature) from an inbound route-forward POST.

    Unlike the JSON event webhooks (which nest these in a ``signature`` object),
    inbound route forwards deliver them as FLAT form fields — urlencoded for
    plain mail, multipart/form-data when the message has attachments.
    """
    content_type = ""
    for k, v in (headers or {}).items():
        if k.lower() == "content-type":
            content_type = v or ""
            break
    fields = ("timestamp", "token", "signature")
    if "multipart/form-data" in content_type.lower():
        vals = {f: _multipart_text_field(body, content_type, f) for f in fields}
    else:
        from urllib.parse import parse_qs

        try:
            parsed = parse_qs(body.decode("utf-8", "replace"))
        except Exception:
            parsed = {}
        vals = {f: (parsed.get(f, [None])[0]) for f in fields}
    return vals["timestamp"], vals["token"], vals["signature"]


async def _mailgun_request(
    api_key: str,
    region: Optional[str],
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    files: Optional[Union[Dict[str, Any], List[Tuple[str, Any]]]] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated Mailgun request (HTTP Basic Auth) and return a structured result.

    Pass ``files`` to force a multipart/form-data request (required by the
    ``/messages.mime`` endpoint, which expects the raw MIME as a file part).
    A list of ``(name, file_tuple)`` pairs allows repeated part names
    (``attachment`` file parts on ``/messages``).
    """
    url = f"{_base_url(region)}{endpoint}"
    token = base64.b64encode(f"api:{api_key}".encode()).decode()
    headers = {"Authorization": f"Basic {token}"}

    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}
    if data:
        data = {k: v for k, v in data.items() if v not in (None, "")}
    if json_body:
        json_body = {k: v for k, v in json_body.items() if v is not None}

    start = time.time()
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.request(
                method=method, url=url, headers=headers, params=params, data=data, json=json_body, files=files
            )
            api_ms = round((time.time() - start) * 1000, 2)
            if response.status_code >= 400:
                try:
                    err = response.json()
                    message = err.get("message") or err.get("Error") or err.get("error") or str(err)
                except Exception:
                    message = response.text
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[MailgunNode] API error ({action_name}): {message}")
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
            logger.error(f"[MailgunNode] Request failed ({action_name}): {msg}")
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


class MailgunNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """Mailgun email automation node."""

    edit_examples = [
        "Send a transactional email through my Mailgun domain",
        "Validate an email address before adding it to a list",
        "Add a new subscriber to a Mailgun mailing list",
        "Get delivery metrics for the last 7 days",
        "Trigger a workflow whenever an email is delivered or bounces",
    ]

    @classmethod
    def get_config_model(cls):
        return MailgunNodeConfig

    # ------------------------------------------------------------------
    # Dynamic options (sending domains)
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
        if field_name not in ("domain", "name"):
            return {"options": []}
        api_key = (credential_data or {}).get("api_key")
        region = (credential_data or {}).get("region")
        if not api_key:
            return {"options": []}
        result = await _mailgun_request(
            api_key, region, "GET", "/v4/domains", params={"limit": 1000},
            action_name="list_domains",
        )
        if result.get("status") != "success":
            return {"options": []}
        data = result.get("data") or {}
        items = data.get("items") if isinstance(data, dict) else data
        options = []
        for d in items or []:
            if not isinstance(d, dict):
                continue
            name = d.get("name")
            if name:
                state = d.get("state")
                label = f"{name} ({state})" if state else name
                options.append({"label": label, "value": name})
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
            "domain": (config or {}).get("domain"),
        }

    @classmethod
    async def _register_external_webhook(
        cls, *, webhook_url: str, credential: Dict[str, Any], config: Dict[str, Any], node_id: str
    ) -> Optional[Dict[str, Any]]:
        api_key = credential.get("api_key")
        region = credential.get("region")
        if not api_key:
            raise ValueError("A Mailgun API key is required to register the trigger")
        domain = (config or {}).get("domain")
        if not domain:
            raise ValueError("A sending domain is required to register the trigger")
        operation = (config or {}).get("operation")
        # Mailgun signs all webhooks / route forwards with the account signing key.
        signing = credential.get("webhook_signing_key")

        if operation == INBOUND_TRIGGER_OP:
            # Inbound mail: create an account-level route forwarding to the URL.
            result = await _mailgun_request(
                api_key, region, "POST", "/v3/routes",
                data={
                    "expression": f'match_recipient(".*@{domain}")',
                    "action": f'forward("{webhook_url}")',
                    "description": f"NoClick inbound trigger ({node_id})",
                    "priority": "0",
                },
                action_name="register_route",
            )
            if result.get("status") != "success":
                raise ValueError(f"Mailgun route registration failed: {result.get('error')}")
            route = (result.get("data") or {}).get("route") or {}
            return {"external_webhook_id": route.get("id"), "signing_secret": signing}

        event = _EVENT_TRIGGER_MAP.get(operation)
        if not event:
            raise ValueError(f"Unknown Mailgun trigger operation: {operation}")
        result = await _mailgun_request(
            api_key, region, "POST", f"/v3/domains/{domain}/webhooks",
            data={"id": event, "url": webhook_url},
            action_name="register_webhook",
        )
        if result.get("status") != "success":
            raise ValueError(f"Mailgun webhook registration failed: {result.get('error')}")
        return {"external_webhook_id": event, "signing_secret": signing}

    @classmethod
    async def _unregister_external_webhook(
        cls, *, credential: Optional[Dict[str, Any]], config: Dict[str, Any], node_id: str
    ) -> None:
        api_key = (credential or {}).get("api_key")
        region = (credential or {}).get("region")
        if not api_key:
            return
        operation = (config or {}).get("operation")
        ext = (config or {}).get("external_webhook_id")
        if operation == INBOUND_TRIGGER_OP:
            if ext:
                await _mailgun_request(
                    api_key, region, "DELETE", f"/v3/routes/{ext}", action_name="unregister_route",
                )
            return
        domain = (config or {}).get("domain")
        event = ext or _EVENT_TRIGGER_MAP.get(operation)
        if not domain or not event:
            return
        await _mailgun_request(
            api_key, region, "DELETE", f"/v3/domains/{domain}/webhooks/{event}",
            action_name="unregister_webhook",
        )

    @classmethod
    def verify_webhook_signature(
        cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]
    ) -> bool:
        """Verify Mailgun's HMAC-SHA256(timestamp + token) signature.

        Event webhooks (2.0) deliver a JSON body with a nested ``signature``
        object; inbound route forwards deliver ``timestamp``/``token``/
        ``signature`` as flat form fields — the HMAC is identical, only the
        parsing differs.
        """
        secret = (config or {}).get("signing_secret")
        if not secret:
            return True  # no signing key stored — accept (trigger not yet armed)
        if (config or {}).get("operation") == INBOUND_TRIGGER_OP:
            timestamp, token, signature = _extract_inbound_signature(body, headers)
        else:
            try:
                payload = json.loads(body)
            except Exception:
                return False
            sig = payload.get("signature") if isinstance(payload, dict) else None
            if not isinstance(sig, dict):
                return False
            timestamp, token, signature = sig.get("timestamp"), sig.get("token"), sig.get("signature")
        if not (timestamp and token and signature):
            return False
        expected = hmac.new(
            secret.encode(), f"{timestamp}{token}".encode(), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, MailgunNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        if isinstance(op, _MailgunTriggerBase):
            return {
                "status": "success",
                "action": op.operation,
                "data": {**inputs, "webhook_url": op.webhook_url},
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your Mailgun API key.")
        api_key = credentials.api_key
        region = credentials.region

        handlers = {
            "send_message": self._send_message,
            "send_mime": self._send_mime,
            "get_stored_message": self._get_stored_message,
            "list_events": self._list_events,
            "query_logs": self._query_logs,
            "get_metrics": self._get_metrics,
            "list_domains": self._list_domains,
            "create_domain": self._create_domain,
            "get_domain": self._get_domain,
            "verify_domain": self._verify_domain,
            "delete_domain": self._delete_domain,
            "list_mailing_lists": self._list_mailing_lists,
            "create_mailing_list": self._create_mailing_list,
            "list_members": self._list_members,
            "add_member": self._add_member,
            "bulk_add_members": self._bulk_add_members,
            "delete_member": self._delete_member,
            "list_templates": self._list_templates,
            "create_template": self._create_template,
            "get_template": self._get_template,
            "create_template_version": self._create_template_version,
            "list_routes": self._list_routes,
            "create_route": self._create_route,
            "delete_route": self._delete_route,
            "list_webhooks": self._list_webhooks,
            "list_bounces": self._list_bounces,
            "add_unsubscribe": self._add_unsubscribe,
            "validate_address": self._validate_address,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(op, api_key, region)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # Handlers — Messages
    # ------------------------------------------------------------------
    async def _send_message(self, c: MailgunSendMessageConfig, api_key, region) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "from": c.from_address,
            "to": _comma_list(c.to),
            "subject": c.subject,
            "text": c.text,
            "html": c.html,
            "cc": _comma_list(c.cc),
            "bcc": _comma_list(c.bcc),
            "template": c.template,
        }
        variables = _parse_json(c.variables, "Template Variables")
        if variables is not None:
            data["h:X-Mailgun-Variables"] = json.dumps(variables)
        files = None
        if c.attachments:
            from nodes.core.media_resolver import resolve_attachments

            files = [
                ("attachment", (media.filename, media.data, media.mime_type))
                for media in await resolve_attachments(c.attachments)
            ] or None
        return await _mailgun_request(
            api_key, region, "POST", f"/v3/{c.domain}/messages", data=data,
            files=files, action_name="send_message",
        )

    async def _send_mime(self, c: MailgunSendMimeConfig, api_key, region) -> Dict[str, Any]:
        # /messages.mime requires multipart/form-data with the raw MIME as a file part.
        return await _mailgun_request(
            api_key, region, "POST", f"/v3/{c.domain}/messages.mime",
            data={"to": _comma_list(c.to)},
            files={"message": ("message.mime", c.message.encode(), "message/rfc822")},
            action_name="send_mime",
        )

    async def _get_stored_message(self, c: MailgunGetStoredMessageConfig, api_key, region) -> Dict[str, Any]:
        return await _mailgun_request(
            api_key, region, "GET", f"/v3/domains/{c.domain}/messages/{c.storage_key}",
            action_name="get_stored_message",
        )

    # ------------------------------------------------------------------
    # Handlers — Analytics
    # ------------------------------------------------------------------
    async def _list_events(self, c: MailgunListEventsConfig, api_key, region) -> Dict[str, Any]:
        params = {"event": c.event or None, "limit": c.limit}
        return await _mailgun_request(
            api_key, region, "GET", f"/v3/{c.domain}/events", params=params,
            action_name="list_events",
        )

    async def _query_logs(self, c: MailgunQueryLogsConfig, api_key, region) -> Dict[str, Any]:
        body: Dict[str, Any] = {"start": c.start, "end": c.end}
        flt = _parse_json(c.filter_json, "Filter (JSON)")
        if flt is not None:
            body["filter"] = flt
        return await _mailgun_request(
            api_key, region, "POST", "/v1/analytics/logs", json_body=body,
            action_name="query_logs",
        )

    async def _get_metrics(self, c: MailgunGetMetricsConfig, api_key, region) -> Dict[str, Any]:
        body: Dict[str, Any] = {"start": c.start, "end": c.end}
        metrics = _parse_json(c.metrics_json, "Metrics (JSON)")
        if metrics is not None:
            body["metrics"] = metrics
        return await _mailgun_request(
            api_key, region, "POST", "/v1/analytics/metrics", json_body=body,
            action_name="get_metrics",
        )

    # ------------------------------------------------------------------
    # Handlers — Domains
    # ------------------------------------------------------------------
    async def _list_domains(self, c: MailgunListDomainsConfig, api_key, region) -> Dict[str, Any]:
        return await _mailgun_request(
            api_key, region, "GET", "/v4/domains", params={"limit": c.limit},
            action_name="list_domains",
        )

    async def _create_domain(self, c: MailgunCreateDomainConfig, api_key, region) -> Dict[str, Any]:
        return await _mailgun_request(
            api_key, region, "POST", "/v4/domains", data={"name": c.name},
            action_name="create_domain",
        )

    async def _get_domain(self, c: MailgunGetDomainConfig, api_key, region) -> Dict[str, Any]:
        return await _mailgun_request(
            api_key, region, "GET", f"/v4/domains/{c.name}", action_name="get_domain",
        )

    async def _verify_domain(self, c: MailgunVerifyDomainConfig, api_key, region) -> Dict[str, Any]:
        return await _mailgun_request(
            api_key, region, "PUT", f"/v4/domains/{c.name}/verify", action_name="verify_domain",
        )

    async def _delete_domain(self, c: MailgunDeleteDomainConfig, api_key, region) -> Dict[str, Any]:
        return await _mailgun_request(
            api_key, region, "DELETE", f"/v3/domains/{c.name}", action_name="delete_domain",
        )

    # ------------------------------------------------------------------
    # Handlers — Mailing Lists
    # ------------------------------------------------------------------
    async def _list_mailing_lists(self, c: MailgunListMailingListsConfig, api_key, region) -> Dict[str, Any]:
        return await _mailgun_request(
            api_key, region, "GET", "/v3/lists/pages", params={"limit": c.limit},
            action_name="list_mailing_lists",
        )

    async def _create_mailing_list(self, c: MailgunCreateMailingListConfig, api_key, region) -> Dict[str, Any]:
        return await _mailgun_request(
            api_key, region, "POST", "/v3/lists",
            data={"address": c.address, "name": c.name, "description": c.description},
            action_name="create_mailing_list",
        )

    async def _list_members(self, c: MailgunListMembersConfig, api_key, region) -> Dict[str, Any]:
        return await _mailgun_request(
            api_key, region, "GET", f"/v3/lists/{c.list_address}/members/pages",
            params={"limit": c.limit}, action_name="list_members",
        )

    async def _add_member(self, c: MailgunAddMemberConfig, api_key, region) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "address": c.address,
            "name": c.name,
            "subscribed": c.subscribed,
        }
        vars_obj = _parse_json(c.vars_json, "Variables (JSON)")
        if vars_obj is not None:
            data["vars"] = json.dumps(vars_obj)
        return await _mailgun_request(
            api_key, region, "POST", f"/v3/lists/{c.list_address}/members", data=data,
            action_name="add_member",
        )

    async def _bulk_add_members(self, c: MailgunBulkAddMembersConfig, api_key, region) -> Dict[str, Any]:
        members = _parse_json(c.members_json, "Members (JSON)")
        return await _mailgun_request(
            api_key, region, "POST", f"/v3/lists/{c.list_address}/members.json",
            data={"members": json.dumps(members), "upsert": c.upsert},
            action_name="bulk_add_members",
        )

    async def _delete_member(self, c: MailgunDeleteMemberConfig, api_key, region) -> Dict[str, Any]:
        return await _mailgun_request(
            api_key, region, "DELETE",
            f"/v3/lists/{c.list_address}/members/{c.member_address}",
            action_name="delete_member",
        )

    # ------------------------------------------------------------------
    # Handlers — Templates
    # ------------------------------------------------------------------
    async def _list_templates(self, c: MailgunListTemplatesConfig, api_key, region) -> Dict[str, Any]:
        return await _mailgun_request(
            api_key, region, "GET", f"/v3/{c.domain}/templates", params={"limit": c.limit},
            action_name="list_templates",
        )

    async def _create_template(self, c: MailgunCreateTemplateConfig, api_key, region) -> Dict[str, Any]:
        return await _mailgun_request(
            api_key, region, "POST", f"/v3/{c.domain}/templates",
            data={"name": c.name, "template": c.template, "description": c.description},
            action_name="create_template",
        )

    async def _get_template(self, c: MailgunGetTemplateConfig, api_key, region) -> Dict[str, Any]:
        return await _mailgun_request(
            api_key, region, "GET", f"/v3/{c.domain}/templates/{c.template_name}",
            action_name="get_template",
        )

    async def _create_template_version(self, c: MailgunCreateTemplateVersionConfig, api_key, region) -> Dict[str, Any]:
        return await _mailgun_request(
            api_key, region, "POST", f"/v3/{c.domain}/templates/{c.template_name}/versions",
            data={"tag": c.tag, "template": c.template, "active": c.active},
            action_name="create_template_version",
        )

    # ------------------------------------------------------------------
    # Handlers — Routes
    # ------------------------------------------------------------------
    async def _list_routes(self, c: MailgunListRoutesConfig, api_key, region) -> Dict[str, Any]:
        return await _mailgun_request(
            api_key, region, "GET", "/v3/routes", params={"limit": c.limit},
            action_name="list_routes",
        )

    async def _create_route(self, c: MailgunCreateRouteConfig, api_key, region) -> Dict[str, Any]:
        data = {
            "expression": c.expression,
            "action": _comma_list(c.action),
            "priority": c.priority,
            "description": c.description,
        }
        return await _mailgun_request(
            api_key, region, "POST", "/v3/routes", data=data, action_name="create_route",
        )

    async def _delete_route(self, c: MailgunDeleteRouteConfig, api_key, region) -> Dict[str, Any]:
        return await _mailgun_request(
            api_key, region, "DELETE", f"/v3/routes/{c.route_id}", action_name="delete_route",
        )

    # ------------------------------------------------------------------
    # Handlers — Webhooks
    # ------------------------------------------------------------------
    async def _list_webhooks(self, c: MailgunListWebhooksConfig, api_key, region) -> Dict[str, Any]:
        return await _mailgun_request(
            api_key, region, "GET", f"/v3/domains/{c.domain}/webhooks",
            action_name="list_webhooks",
        )

    # ------------------------------------------------------------------
    # Handlers — Suppressions
    # ------------------------------------------------------------------
    async def _list_bounces(self, c: MailgunListBouncesConfig, api_key, region) -> Dict[str, Any]:
        return await _mailgun_request(
            api_key, region, "GET", f"/v3/{c.domain}/bounces", params={"limit": c.limit},
            action_name="list_bounces",
        )

    async def _add_unsubscribe(self, c: MailgunAddUnsubscribesConfig, api_key, region) -> Dict[str, Any]:
        return await _mailgun_request(
            api_key, region, "POST", f"/v3/{c.domain}/unsubscribes",
            data={"address": c.address, "tag": c.tag},
            action_name="add_unsubscribe",
        )

    # ------------------------------------------------------------------
    # Handlers — Validation
    # ------------------------------------------------------------------
    async def _validate_address(self, c: MailgunValidateAddressConfig, api_key, region) -> Dict[str, Any]:
        return await _mailgun_request(
            api_key, region, "GET", "/v4/address/validate", params={"address": c.address},
            action_name="validate_address",
        )
