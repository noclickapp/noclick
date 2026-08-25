"""
Loops email marketing & lifecycle automation node.

Provides workflow integration with Loops (https://loops.so) for operations including:
- API key: test connection
- Contacts: create, update, find, delete, suppression status/removal, properties (create/list)
- Mailing lists: list
- Events: send
- Transactional: send email, list, get
- Campaigns: list, create, get, update
- Email messages: get, update
- Themes / components / audience segments: list
- Uploads: create image upload
- Dedicated sending IPs: list
- Trigger: receive outbound Loops webhook events (Svix HMAC-SHA256)

Authentication: API Key (Bearer token)
API Base URL: https://app.loops.so/api
Documentation: https://loops.so/docs/api-reference/intro
"""

import logging
import time
from typing import Dict, Any, Optional, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.media_resolver import resolve_media_input
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin
from utils.webhook_signatures import verify_svix
from utils.ssrf import guarded_async_client

logger = logging.getLogger(__name__)

LOOPS_API_BASE = "https://app.loops.so/api"


# ============================================================================
# Credential Schema
# ============================================================================


class LoopsAPIKeyCredential(BaseModel):
    """API Key credential for Loops."""

    credential_type: Literal["loops_api_key"] = Field(
        "loops_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description="Your Loops API key from Settings -> API -> Generate key. Passed as a Bearer token.",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={"x-credential-url": "https://app.loops.so/settings?page=api"}
    )


LoopsCredential = LoopsAPIKeyCredential


# ============================================================================
# Operation Configs
# ============================================================================


class LoopsTestApiKeyConfig(BaseModel):
    """Verify the API key is valid and return the team name."""

    operation: Literal["test_api_key"] = Field(
        "test_api_key",
        json_schema_extra={
            "const": "test_api_key",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Test API Key",
        },
        title="Test API Key",
    )


class LoopsCreateContactConfig(BaseModel):
    """Add a new contact (by email) to the audience."""

    operation: Literal["create_contact"] = Field(
        "create_contact",
        json_schema_extra={
            "const": "create_contact",
            "ui:hidden": True,
            "x-category": "Contacts",
            "x-is-trigger": False,
            "x-display-name": "Create Contact",
        },
        title="Create Contact",
    )
    email: str = Field(..., title="Email", description="The contact's email address")
    first_name: Optional[str] = Field(None, title="First Name", description="Contact's first name")
    last_name: Optional[str] = Field(None, title="Last Name", description="Contact's last name")
    user_id: Optional[str] = Field(
        None, title="User ID", description="Your own unique identifier for this contact"
    )
    subscribed: Optional[str] = Field(
        "true",
        title="Subscribed",
        description="Whether the contact is subscribed to email",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    mailing_list_id: Optional[str] = Field(
        None,
        title="Mailing List",
        description="Subscribe the contact to this mailing list",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "mailing_list_id",
                "placeholder": "Select a mailing list...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a mailing list ID",
            },
            "x-resource-type": "loops_mailing_list",
        },
    )
    properties: Optional[str] = Field(
        None,
        title="Custom Properties (JSON)",
        description='Additional contact properties as a JSON object, e.g. {"plan": "pro"}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class LoopsUpdateContactConfig(BaseModel):
    """Update an existing contact's properties (upserts if not found)."""

    operation: Literal["update_contact"] = Field(
        "update_contact",
        json_schema_extra={
            "const": "update_contact",
            "ui:hidden": True,
            "x-category": "Contacts",
            "x-is-trigger": False,
            "x-display-name": "Update Contact",
        },
        title="Update Contact",
    )
    email: str = Field(..., title="Email", description="The contact's email address (used to match)")
    first_name: Optional[str] = Field(None, title="First Name", description="Contact's first name")
    last_name: Optional[str] = Field(None, title="Last Name", description="Contact's last name")
    user_id: Optional[str] = Field(
        None, title="User ID", description="Your own unique identifier for this contact"
    )
    subscribed: Optional[str] = Field(
        None,
        title="Subscribed",
        description="Whether the contact is subscribed to email",
        json_schema_extra={
            "enum": ["", "true", "false"],
            "enumNames": ["No change", "Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    mailing_list_id: Optional[str] = Field(
        None,
        title="Mailing List",
        description="Subscribe the contact to this mailing list",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "mailing_list_id",
                "placeholder": "Select a mailing list...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a mailing list ID",
            },
            "x-resource-type": "loops_mailing_list",
        },
    )
    properties: Optional[str] = Field(
        None,
        title="Custom Properties (JSON)",
        description='Additional contact properties as a JSON object, e.g. {"plan": "pro"}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class LoopsFindContactConfig(BaseModel):
    """Look up a contact by email or userId."""

    operation: Literal["find_contact"] = Field(
        "find_contact",
        json_schema_extra={
            "const": "find_contact",
            "ui:hidden": True,
            "x-category": "Contacts",
            "x-is-trigger": False,
            "x-display-name": "Find Contact",
        },
        title="Find Contact",
    )
    email: Optional[str] = Field(None, title="Email", description="Find a contact by email")
    user_id: Optional[str] = Field(None, title="User ID", description="Find a contact by userId")


class LoopsDeleteContactConfig(BaseModel):
    """Remove a contact from the audience by email or userId."""

    operation: Literal["delete_contact"] = Field(
        "delete_contact",
        json_schema_extra={
            "const": "delete_contact",
            "ui:hidden": True,
            "x-category": "Contacts",
            "x-is-trigger": False,
            "x-display-name": "Delete Contact",
        },
        title="Delete Contact",
    )
    email: Optional[str] = Field(None, title="Email", description="Delete the contact with this email")
    user_id: Optional[str] = Field(None, title="User ID", description="Delete the contact with this userId")


class LoopsGetSuppressionConfig(BaseModel):
    """Check whether a contact is suppressed and the removal quota."""

    operation: Literal["get_suppression"] = Field(
        "get_suppression",
        json_schema_extra={
            "const": "get_suppression",
            "ui:hidden": True,
            "x-category": "Contacts",
            "x-is-trigger": False,
            "x-display-name": "Get Suppression Status",
        },
        title="Get Suppression Status",
    )
    email: str = Field(..., title="Email", description="The contact's email address to check")


class LoopsRemoveSuppressionConfig(BaseModel):
    """Restore (un-suppress) a previously suppressed contact."""

    operation: Literal["remove_suppression"] = Field(
        "remove_suppression",
        json_schema_extra={
            "const": "remove_suppression",
            "ui:hidden": True,
            "x-category": "Contacts",
            "x-is-trigger": False,
            "x-display-name": "Remove Suppression",
        },
        title="Remove Suppression",
    )
    email: str = Field(..., title="Email", description="The contact's email address to un-suppress")


class LoopsCreateContactPropertyConfig(BaseModel):
    """Define a new custom contact property."""

    operation: Literal["create_contact_property"] = Field(
        "create_contact_property",
        json_schema_extra={
            "const": "create_contact_property",
            "ui:hidden": True,
            "x-category": "Contact Properties",
            "x-is-trigger": False,
            "x-display-name": "Create Contact Property",
        },
        title="Create Contact Property",
    )
    name: str = Field(..., title="Name", description="The name of the new property")
    property_type: str = Field(
        ...,
        title="Type",
        description="The data type of the property",
        json_schema_extra={
            "enum": ["string", "number", "boolean", "date"],
            "enumNames": ["String", "Number", "Boolean", "Date"],
            "x-enum-searchable": True,
        },
    )


class LoopsListContactPropertiesConfig(BaseModel):
    """List all contact properties for the team."""

    operation: Literal["list_contact_properties"] = Field(
        "list_contact_properties",
        json_schema_extra={
            "const": "list_contact_properties",
            "ui:hidden": True,
            "x-category": "Contact Properties",
            "x-is-trigger": False,
            "x-display-name": "List Contact Properties",
        },
        title="List Contact Properties",
    )
    list_filter: Optional[str] = Field(
        None,
        title="Filter",
        description="Filter by property origin",
        json_schema_extra={
            "enum": ["", "all", "custom"],
            "enumNames": ["All", "All", "Custom only"],
            "x-enum-searchable": True,
        },
    )


class LoopsListMailingListsConfig(BaseModel):
    """Retrieve the account's mailing lists."""

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


class LoopsSendEventConfig(BaseModel):
    """Send an event for a contact to trigger event-based loops."""

    operation: Literal["send_event"] = Field(
        "send_event",
        json_schema_extra={
            "const": "send_event",
            "ui:hidden": True,
            "x-category": "Events",
            "x-is-trigger": False,
            "x-display-name": "Send Event",
        },
        title="Send Event",
    )
    event_name: str = Field(..., title="Event Name", description="The name of the event to fire")
    email: Optional[str] = Field(None, title="Email", description="The contact's email (or use User ID)")
    user_id: Optional[str] = Field(None, title="User ID", description="The contact's userId (or use Email)")
    event_properties: Optional[str] = Field(
        None,
        title="Event Properties (JSON)",
        description='Event properties as a JSON object, e.g. {"plan": "pro"}',
        json_schema_extra={"ui:widget": "textarea"},
    )
    contact_properties: Optional[str] = Field(
        None,
        title="Contact Properties (JSON)",
        description="Contact properties to set alongside the event, as a JSON object",
        json_schema_extra={"ui:widget": "textarea"},
    )


class LoopsSendTransactionalConfig(BaseModel):
    """Send a published transactional email to a contact."""

    operation: Literal["send_transactional"] = Field(
        "send_transactional",
        json_schema_extra={
            "const": "send_transactional",
            "ui:hidden": True,
            "x-category": "Transactional",
            "x-is-trigger": False,
            "x-display-name": "Send Transactional Email",
        },
        title="Send Transactional Email",
    )
    transactional_id: str = Field(
        ...,
        title="Transactional Email",
        description="The transactional email to send (must be published)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "transactional_id",
                "placeholder": "Select a transactional email...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a transactional ID",
            },
            "x-resource-type": "loops_transactional",
        },
    )
    email: str = Field(..., title="Email", description="The recipient's email address")
    data_variables: Optional[str] = Field(
        None,
        title="Data Variables (JSON)",
        description='Template data variables as a JSON object, e.g. {"name": "Ada"}',
        json_schema_extra={"ui:widget": "textarea"},
    )
    add_to_audience: Optional[str] = Field(
        "false",
        title="Add to Audience",
        description="Add the recipient as a contact if they don't exist",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class LoopsListTransactionalConfig(BaseModel):
    """List transactional emails (paginated)."""

    operation: Literal["list_transactional"] = Field(
        "list_transactional",
        json_schema_extra={
            "const": "list_transactional",
            "ui:hidden": True,
            "x-category": "Transactional",
            "x-is-trigger": False,
            "x-display-name": "List Transactional Emails",
        },
        title="List Transactional Emails",
    )
    per_page: Optional[str] = Field(
        "20", title="Per Page", description="Number of results per page (max 50)"
    )
    cursor: Optional[str] = Field(None, title="Cursor", description="Pagination cursor from a prior response")


class LoopsGetTransactionalConfig(BaseModel):
    """Retrieve a single transactional email by id."""

    operation: Literal["get_transactional"] = Field(
        "get_transactional",
        json_schema_extra={
            "const": "get_transactional",
            "ui:hidden": True,
            "x-category": "Transactional",
            "x-is-trigger": False,
            "x-display-name": "Get Transactional Email",
        },
        title="Get Transactional Email",
    )
    transactional_id: str = Field(
        ..., title="Transactional ID", description="The id of the transactional email to retrieve"
    )


class LoopsListCampaignsConfig(BaseModel):
    """List campaigns (paginated)."""

    operation: Literal["list_campaigns"] = Field(
        "list_campaigns",
        json_schema_extra={
            "const": "list_campaigns",
            "ui:hidden": True,
            "x-category": "Campaigns",
            "x-is-trigger": False,
            "x-display-name": "List Campaigns",
        },
        title="List Campaigns",
    )
    per_page: Optional[str] = Field(
        "20", title="Per Page", description="Number of results per page (max 50)"
    )
    cursor: Optional[str] = Field(None, title="Cursor", description="Pagination cursor from a prior response")


class LoopsCreateCampaignConfig(BaseModel):
    """Create a new draft campaign."""

    operation: Literal["create_campaign"] = Field(
        "create_campaign",
        json_schema_extra={
            "const": "create_campaign",
            "ui:hidden": True,
            "x-category": "Campaigns",
            "x-is-trigger": False,
            "x-display-name": "Create Campaign",
        },
        title="Create Campaign",
    )
    name: str = Field(..., title="Name", description="The name of the campaign")
    subject: Optional[str] = Field(None, title="Subject", description="The email subject line")
    from_name: Optional[str] = Field(None, title="From Name", description="The sender display name")


class LoopsGetCampaignConfig(BaseModel):
    """Retrieve a single campaign by id."""

    operation: Literal["get_campaign"] = Field(
        "get_campaign",
        json_schema_extra={
            "const": "get_campaign",
            "ui:hidden": True,
            "x-category": "Campaigns",
            "x-is-trigger": False,
            "x-display-name": "Get Campaign",
        },
        title="Get Campaign",
    )
    campaign_id: str = Field(..., title="Campaign ID", description="The id of the campaign to retrieve")


class LoopsUpdateCampaignConfig(BaseModel):
    """Update a draft campaign's details."""

    operation: Literal["update_campaign"] = Field(
        "update_campaign",
        json_schema_extra={
            "const": "update_campaign",
            "ui:hidden": True,
            "x-category": "Campaigns",
            "x-is-trigger": False,
            "x-display-name": "Update Campaign",
        },
        title="Update Campaign",
    )
    campaign_id: str = Field(..., title="Campaign ID", description="The id of the campaign to update")
    name: Optional[str] = Field(None, title="Name", description="The campaign name")
    subject: Optional[str] = Field(None, title="Subject", description="The email subject line")
    from_name: Optional[str] = Field(None, title="From Name", description="The sender display name")


class LoopsGetEmailMessageConfig(BaseModel):
    """Retrieve an email message (campaign content) with compiled output."""

    operation: Literal["get_email_message"] = Field(
        "get_email_message",
        json_schema_extra={
            "const": "get_email_message",
            "ui:hidden": True,
            "x-category": "Email Messages",
            "x-is-trigger": False,
            "x-display-name": "Get Email Message",
        },
        title="Get Email Message",
    )
    email_message_id: str = Field(
        ..., title="Email Message ID", description="The id of the email message to retrieve"
    )


class LoopsUpdateEmailMessageConfig(BaseModel):
    """Update subject, sender, preview text, or content of an email message."""

    operation: Literal["update_email_message"] = Field(
        "update_email_message",
        json_schema_extra={
            "const": "update_email_message",
            "ui:hidden": True,
            "x-category": "Email Messages",
            "x-is-trigger": False,
            "x-display-name": "Update Email Message",
        },
        title="Update Email Message",
    )
    email_message_id: str = Field(
        ..., title="Email Message ID", description="The id of the email message to update"
    )
    subject: Optional[str] = Field(None, title="Subject", description="The email subject line")
    from_name: Optional[str] = Field(None, title="From Name", description="The sender display name")
    preview_text: Optional[str] = Field(None, title="Preview Text", description="The email preview text")
    content: Optional[str] = Field(
        None,
        title="Content (JSON)",
        description="The email content as a JSON object",
        json_schema_extra={"ui:widget": "textarea"},
    )


class LoopsListThemesConfig(BaseModel):
    """List email themes (paginated)."""

    operation: Literal["list_themes"] = Field(
        "list_themes",
        json_schema_extra={
            "const": "list_themes",
            "ui:hidden": True,
            "x-category": "Design",
            "x-is-trigger": False,
            "x-display-name": "List Themes",
        },
        title="List Themes",
    )
    per_page: Optional[str] = Field(
        "20", title="Per Page", description="Number of results per page (max 50)"
    )
    cursor: Optional[str] = Field(None, title="Cursor", description="Pagination cursor from a prior response")


class LoopsListComponentsConfig(BaseModel):
    """List reusable email components (paginated)."""

    operation: Literal["list_components"] = Field(
        "list_components",
        json_schema_extra={
            "const": "list_components",
            "ui:hidden": True,
            "x-category": "Design",
            "x-is-trigger": False,
            "x-display-name": "List Components",
        },
        title="List Components",
    )
    per_page: Optional[str] = Field(
        "20", title="Per Page", description="Number of results per page (max 50)"
    )
    cursor: Optional[str] = Field(None, title="Cursor", description="Pagination cursor from a prior response")


class LoopsListAudienceSegmentsConfig(BaseModel):
    """List audience segments (paginated)."""

    operation: Literal["list_audience_segments"] = Field(
        "list_audience_segments",
        json_schema_extra={
            "const": "list_audience_segments",
            "ui:hidden": True,
            "x-category": "Audience",
            "x-is-trigger": False,
            "x-display-name": "List Audience Segments",
        },
        title="List Audience Segments",
    )
    per_page: Optional[str] = Field(
        "20", title="Per Page", description="Number of results per page (max 50)"
    )
    cursor: Optional[str] = Field(None, title="Cursor", description="Pagination cursor from a prior response")


class LoopsCreateUploadConfig(BaseModel):
    """Upload an image asset to Loops via the platform upload component."""

    operation: Literal["create_upload"] = Field(
        "create_upload",
        json_schema_extra={
            "const": "create_upload",
            "ui:hidden": True,
            "x-category": "Uploads",
            "x-is-trigger": False,
            "x-display-name": "Upload Image",
        },
        title="Upload Image",
    )
    image: Optional[str] = Field(
        None,
        title="Image",
        description="Image file to upload to Loops (JPEG, PNG, or WebP)",
        json_schema_extra={"ui:widget": "veo_image_upload"},
    )


class LoopsCompleteUploadConfig(BaseModel):
    """Finalize a previously initiated upload and get the public URL."""

    operation: Literal["complete_upload"] = Field(
        "complete_upload",
        json_schema_extra={
            "const": "complete_upload",
            "ui:hidden": True,
            "x-category": "Uploads",
            "x-is-trigger": False,
            "x-display-name": "Complete Upload",
        },
        title="Complete Upload",
    )
    upload_id: str = Field(..., title="Upload ID", description="The upload ID returned by Create Image Upload")


class LoopsSendEmailMessagePreviewConfig(BaseModel):
    """Send a preview of an email message to one or more addresses."""

    operation: Literal["send_email_message_preview"] = Field(
        "send_email_message_preview",
        json_schema_extra={
            "const": "send_email_message_preview",
            "ui:hidden": True,
            "x-category": "Email Messages",
            "x-is-trigger": False,
            "x-display-name": "Send Email Message Preview",
        },
        title="Send Email Message Preview",
    )
    email_message_id: str = Field(
        ..., title="Email Message ID", description="The id of the email message to preview"
    )
    emails: str = Field(
        ...,
        title="Preview Recipients (JSON array)",
        description='Email addresses to send the preview to, as a JSON array, e.g. ["you@example.com"]',
        json_schema_extra={"ui:widget": "textarea"},
    )
    data_variables: Optional[str] = Field(
        None,
        title="Data Variables (JSON)",
        description="Template data variables for the preview, as a JSON object",
        json_schema_extra={"ui:widget": "textarea"},
    )


class LoopsCreateTransactionalEmailConfig(BaseModel):
    """Create a new transactional email template."""

    operation: Literal["create_transactional_email"] = Field(
        "create_transactional_email",
        json_schema_extra={
            "const": "create_transactional_email",
            "ui:hidden": True,
            "x-category": "Transactional",
            "x-is-trigger": False,
            "x-display-name": "Create Transactional Email",
            "x-creates-resource": True,
            "x-resource-type": "loops_transactional",
            "x-resource-id-path": "data.id",
        },
        title="Create Transactional Email",
    )
    name: str = Field(..., title="Name", description="The name of the transactional email")
    group_id: Optional[str] = Field(None, title="Group ID", description="Assign to a transactional group")


class LoopsUpdateTransactionalEmailConfig(BaseModel):
    """Update an existing transactional email template's name or group."""

    operation: Literal["update_transactional_email"] = Field(
        "update_transactional_email",
        json_schema_extra={
            "const": "update_transactional_email",
            "ui:hidden": True,
            "x-category": "Transactional",
            "x-is-trigger": False,
            "x-display-name": "Update Transactional Email",
        },
        title="Update Transactional Email",
    )
    transactional_id: str = Field(..., title="Transactional ID", description="The id of the transactional email to update")
    name: Optional[str] = Field(None, title="Name", description="The transactional email name")
    group_id: Optional[str] = Field(None, title="Group ID", description="Assign to a transactional group")


class LoopsEnsureTransactionalEmailDraftConfig(BaseModel):
    """Ensure a transactional email is in draft state (revert from published if needed)."""

    operation: Literal["ensure_transactional_email_draft"] = Field(
        "ensure_transactional_email_draft",
        json_schema_extra={
            "const": "ensure_transactional_email_draft",
            "ui:hidden": True,
            "x-category": "Transactional",
            "x-is-trigger": False,
            "x-display-name": "Ensure Transactional Email Draft",
        },
        title="Ensure Transactional Email Draft",
    )
    transactional_id: str = Field(..., title="Transactional ID", description="The id of the transactional email")


class LoopsPublishTransactionalEmailConfig(BaseModel):
    """Publish a transactional email template so it can be sent."""

    operation: Literal["publish_transactional_email"] = Field(
        "publish_transactional_email",
        json_schema_extra={
            "const": "publish_transactional_email",
            "ui:hidden": True,
            "x-category": "Transactional",
            "x-is-trigger": False,
            "x-display-name": "Publish Transactional Email",
        },
        title="Publish Transactional Email",
    )
    transactional_id: str = Field(..., title="Transactional ID", description="The id of the transactional email to publish")


class LoopsListCampaignGroupsConfig(BaseModel):
    """List campaign groups (paginated)."""

    operation: Literal["list_campaign_groups"] = Field(
        "list_campaign_groups",
        json_schema_extra={
            "const": "list_campaign_groups",
            "ui:hidden": True,
            "x-category": "Campaign Groups",
            "x-is-trigger": False,
            "x-display-name": "List Campaign Groups",
        },
        title="List Campaign Groups",
    )
    per_page: Optional[str] = Field("20", title="Per Page", description="Number of results per page (max 50)")
    cursor: Optional[str] = Field(None, title="Cursor", description="Pagination cursor from a prior response")


class LoopsGetCampaignGroupConfig(BaseModel):
    """Retrieve a single campaign group by id."""

    operation: Literal["get_campaign_group"] = Field(
        "get_campaign_group",
        json_schema_extra={
            "const": "get_campaign_group",
            "ui:hidden": True,
            "x-category": "Campaign Groups",
            "x-is-trigger": False,
            "x-display-name": "Get Campaign Group",
        },
        title="Get Campaign Group",
    )
    group_id: str = Field(..., title="Group ID", description="The id of the campaign group to retrieve")


class LoopsCreateCampaignGroupConfig(BaseModel):
    """Create a new campaign group."""

    operation: Literal["create_campaign_group"] = Field(
        "create_campaign_group",
        json_schema_extra={
            "const": "create_campaign_group",
            "ui:hidden": True,
            "x-category": "Campaign Groups",
            "x-is-trigger": False,
            "x-display-name": "Create Campaign Group",
        },
        title="Create Campaign Group",
    )
    name: str = Field(..., title="Name", description="The name of the campaign group")


class LoopsUpdateCampaignGroupConfig(BaseModel):
    """Update an existing campaign group."""

    operation: Literal["update_campaign_group"] = Field(
        "update_campaign_group",
        json_schema_extra={
            "const": "update_campaign_group",
            "ui:hidden": True,
            "x-category": "Campaign Groups",
            "x-is-trigger": False,
            "x-display-name": "Update Campaign Group",
        },
        title="Update Campaign Group",
    )
    group_id: str = Field(..., title="Group ID", description="The id of the campaign group to update")
    name: str = Field(..., title="Name", description="The new name for the campaign group")


class LoopsListTransactionalGroupsConfig(BaseModel):
    """List transactional groups (paginated)."""

    operation: Literal["list_transactional_groups"] = Field(
        "list_transactional_groups",
        json_schema_extra={
            "const": "list_transactional_groups",
            "ui:hidden": True,
            "x-category": "Transactional Groups",
            "x-is-trigger": False,
            "x-display-name": "List Transactional Groups",
        },
        title="List Transactional Groups",
    )
    per_page: Optional[str] = Field("20", title="Per Page", description="Number of results per page (max 50)")
    cursor: Optional[str] = Field(None, title="Cursor", description="Pagination cursor from a prior response")


class LoopsGetTransactionalGroupConfig(BaseModel):
    """Retrieve a single transactional group by id."""

    operation: Literal["get_transactional_group"] = Field(
        "get_transactional_group",
        json_schema_extra={
            "const": "get_transactional_group",
            "ui:hidden": True,
            "x-category": "Transactional Groups",
            "x-is-trigger": False,
            "x-display-name": "Get Transactional Group",
        },
        title="Get Transactional Group",
    )
    group_id: str = Field(..., title="Group ID", description="The id of the transactional group to retrieve")


class LoopsCreateTransactionalGroupConfig(BaseModel):
    """Create a new transactional group."""

    operation: Literal["create_transactional_group"] = Field(
        "create_transactional_group",
        json_schema_extra={
            "const": "create_transactional_group",
            "ui:hidden": True,
            "x-category": "Transactional Groups",
            "x-is-trigger": False,
            "x-display-name": "Create Transactional Group",
        },
        title="Create Transactional Group",
    )
    name: str = Field(..., title="Name", description="The name of the transactional group")


class LoopsUpdateTransactionalGroupConfig(BaseModel):
    """Update an existing transactional group."""

    operation: Literal["update_transactional_group"] = Field(
        "update_transactional_group",
        json_schema_extra={
            "const": "update_transactional_group",
            "ui:hidden": True,
            "x-category": "Transactional Groups",
            "x-is-trigger": False,
            "x-display-name": "Update Transactional Group",
        },
        title="Update Transactional Group",
    )
    group_id: str = Field(..., title="Group ID", description="The id of the transactional group to update")
    name: str = Field(..., title="Name", description="The new name for the transactional group")


class LoopsGetThemeConfig(BaseModel):
    """Retrieve a single email theme by id."""

    operation: Literal["get_theme"] = Field(
        "get_theme",
        json_schema_extra={
            "const": "get_theme",
            "ui:hidden": True,
            "x-category": "Design",
            "x-is-trigger": False,
            "x-display-name": "Get Theme",
        },
        title="Get Theme",
    )
    theme_id: str = Field(..., title="Theme ID", description="The id of the theme to retrieve")


class LoopsGetComponentConfig(BaseModel):
    """Retrieve a single reusable email component by id."""

    operation: Literal["get_component"] = Field(
        "get_component",
        json_schema_extra={
            "const": "get_component",
            "ui:hidden": True,
            "x-category": "Design",
            "x-is-trigger": False,
            "x-display-name": "Get Component",
        },
        title="Get Component",
    )
    component_id: str = Field(..., title="Component ID", description="The id of the component to retrieve")


class LoopsGetAudienceSegmentConfig(BaseModel):
    """Retrieve a single audience segment by id."""

    operation: Literal["get_audience_segment"] = Field(
        "get_audience_segment",
        json_schema_extra={
            "const": "get_audience_segment",
            "ui:hidden": True,
            "x-category": "Audience",
            "x-is-trigger": False,
            "x-display-name": "Get Audience Segment",
        },
        title="Get Audience Segment",
    )
    segment_id: str = Field(..., title="Segment ID", description="The id of the audience segment to retrieve")


class LoopsListWorkflowsConfig(BaseModel):
    """List automation workflows (alpha, paginated)."""

    operation: Literal["list_workflows"] = Field(
        "list_workflows",
        json_schema_extra={
            "const": "list_workflows",
            "ui:hidden": True,
            "x-category": "Workflows",
            "x-is-trigger": False,
            "x-display-name": "List Workflows",
        },
        title="List Workflows",
    )
    per_page: Optional[str] = Field("20", title="Per Page", description="Number of results per page (max 50)")
    cursor: Optional[str] = Field(None, title="Cursor", description="Pagination cursor from a prior response")


class LoopsGetWorkflowConfig(BaseModel):
    """Retrieve a single automation workflow by id (alpha)."""

    operation: Literal["get_workflow"] = Field(
        "get_workflow",
        json_schema_extra={
            "const": "get_workflow",
            "ui:hidden": True,
            "x-category": "Workflows",
            "x-is-trigger": False,
            "x-display-name": "Get Workflow",
        },
        title="Get Workflow",
    )
    workflow_id: str = Field(..., title="Workflow ID", description="The id of the automation workflow")


class LoopsGetWorkflowNodeConfig(BaseModel):
    """Retrieve a single node inside an automation workflow (alpha)."""

    operation: Literal["get_workflow_node"] = Field(
        "get_workflow_node",
        json_schema_extra={
            "const": "get_workflow_node",
            "ui:hidden": True,
            "x-category": "Workflows",
            "x-is-trigger": False,
            "x-display-name": "Get Workflow Node",
        },
        title="Get Workflow Node",
    )
    workflow_id: str = Field(..., title="Workflow ID", description="The id of the parent workflow")
    node_id: str = Field(..., title="Node ID", description="The id of the node within the workflow")


class LoopsListSendingIpsConfig(BaseModel):
    """Retrieve the team's dedicated sending IP addresses."""

    operation: Literal["list_sending_ips"] = Field(
        "list_sending_ips",
        json_schema_extra={
            "const": "list_sending_ips",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "List Dedicated Sending IPs",
        },
        title="List Dedicated Sending IPs",
    )


class LoopsWebhookTriggerConfig(BaseModel):
    """Receive outbound webhook events from Loops (Settings → Webhooks in the Loops dashboard)."""

    operation: Literal["on_loops_event"] = Field(
        "on_loops_event",
        json_schema_extra={
            "const": "on_loops_event",
            "ui:hidden": True,
            "x-category": "Triggers",
            "x-is-trigger": True,
            "x-display-name": "On Loops Event",
        },
        title="On Loops Event",
    )
    webhook_url: Optional[str] = Field(
        None,
        title="Webhook URL",
        description=(
            "Copy this URL and paste it in Loops dashboard → Settings → Webhooks. "
            "Then enter the Signing Secret shown by Loops below."
        ),
        json_schema_extra={"ui:widget": "webhook", "ui:placeholder": "Auto-generated"},
    )
    signing_secret: Optional[str] = Field(
        None,
        title="Signing Secret",
        description="Signing secret from Loops dashboard → Settings → Webhooks.",
        json_schema_extra={"ui:widget": "password", "ui:placeholder": "whsec_..."},
    )
    event_type: Optional[Literal[
        "contact.created",
        "contact.unsubscribed",
        "contact.deleted",
        "contact.mailingList.subscribed",
        "contact.mailingList.unsubscribed",
        "campaign.email.sent",
        "loop.email.sent",
        "transactional.email.sent",
        "email.delivered",
        "email.softBounced",
        "email.hardBounced",
        "email.opened",
        "email.clicked",
        "email.unsubscribed",
        "email.resubscribed",
        "email.spamReported",
        "testing.testEvent",
    ]] = Field(
        None,
        title="Event Type Filter",
        description="Only process events of this type. Leave empty to receive all events.",
        json_schema_extra={"x-enum-searchable": True},
    )
    # Hidden system fields managed by ExternalWebhookTriggerMixin
    trigger_registered: Optional[bool] = Field(None, json_schema_extra={"ui:hidden": True})
    trigger_error: Optional[str] = Field(None, json_schema_extra={"ui:hidden": True})
    external_webhook_id: Optional[str] = Field(None, json_schema_extra={"ui:hidden": True})
    webhook_id: Optional[str] = Field(None, json_schema_extra={"ui:hidden": True})
    is_production: Optional[bool] = Field(None, json_schema_extra={"ui:hidden": True})
    relay_connected: Optional[bool] = Field(None, json_schema_extra={"ui:hidden": True})


# ============================================================================
# Discriminated Union
# ============================================================================


LoopsConfig = Annotated[
    Union[
        LoopsTestApiKeyConfig,
        LoopsCreateContactConfig,
        LoopsUpdateContactConfig,
        LoopsFindContactConfig,
        LoopsDeleteContactConfig,
        LoopsGetSuppressionConfig,
        LoopsRemoveSuppressionConfig,
        LoopsCreateContactPropertyConfig,
        LoopsListContactPropertiesConfig,
        LoopsListMailingListsConfig,
        LoopsSendEventConfig,
        LoopsSendTransactionalConfig,
        LoopsListTransactionalConfig,
        LoopsGetTransactionalConfig,
        LoopsCreateTransactionalEmailConfig,
        LoopsUpdateTransactionalEmailConfig,
        LoopsEnsureTransactionalEmailDraftConfig,
        LoopsPublishTransactionalEmailConfig,
        LoopsListCampaignsConfig,
        LoopsCreateCampaignConfig,
        LoopsGetCampaignConfig,
        LoopsUpdateCampaignConfig,
        LoopsListCampaignGroupsConfig,
        LoopsGetCampaignGroupConfig,
        LoopsCreateCampaignGroupConfig,
        LoopsUpdateCampaignGroupConfig,
        LoopsListTransactionalGroupsConfig,
        LoopsGetTransactionalGroupConfig,
        LoopsCreateTransactionalGroupConfig,
        LoopsUpdateTransactionalGroupConfig,
        LoopsGetEmailMessageConfig,
        LoopsUpdateEmailMessageConfig,
        LoopsSendEmailMessagePreviewConfig,
        LoopsListThemesConfig,
        LoopsGetThemeConfig,
        LoopsListComponentsConfig,
        LoopsGetComponentConfig,
        LoopsListAudienceSegmentsConfig,
        LoopsGetAudienceSegmentConfig,
        LoopsCreateUploadConfig,
        LoopsCompleteUploadConfig,
        LoopsListWorkflowsConfig,
        LoopsGetWorkflowConfig,
        LoopsGetWorkflowNodeConfig,
        LoopsListSendingIpsConfig,
        LoopsWebhookTriggerConfig,
    ],
    Discriminator("operation"),
]


class LoopsNodeConfig(NodeConfig[LoopsConfig, LoopsCredential]):
    """Full configuration for the Loops node including credentials."""

    pass


# ============================================================================
# Helpers
# ============================================================================


def _parse_json_object(value: Optional[str], field_label: str) -> Optional[Dict[str, Any]]:
    """Parse a JSON-object string field; raise on invalid input (no silent fallback)."""
    if value is None or value.strip() == "":
        return None
    import json

    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError(f"{field_label} must be a JSON object")
    return parsed


async def _loops_request(
    api_key: str,
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated Loops request and return a structured result."""
    url = f"{LOOPS_API_BASE}{endpoint}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if json_body:
        json_body = {k: v for k, v in json_body.items() if v is not None}
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}

    start = time.time()
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.request(
                method=method, url=url, headers=headers, params=params, json=json_body
            )
            api_ms = round((time.time() - start) * 1000, 2)
            if response.status_code >= 400:
                try:
                    err = response.json()
                    message = (
                        err.get("message")
                        or err.get("error")
                        or err.get("errors")
                        or str(err)
                    )
                except Exception:
                    message = response.text
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[LoopsNode] API error ({action_name}): {message}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": message,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }
            if response.status_code == 204:
                data: Any = {"success": True}
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
            logger.error(f"[LoopsNode] Request failed ({action_name}): {msg}")
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


class LoopsNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """Loops email marketing & lifecycle automation node."""

    edit_examples = [
        "Add a new contact to Loops when a user signs up",
        "Send a 'trial_started' event to Loops to fire a lifecycle email",
        "Send a transactional password-reset email through Loops",
        "Find a Loops contact by email to check their subscription status",
        "Create a draft Loops campaign for a product launch",
    ]

    @classmethod
    def get_config_model(cls):
        return LoopsNodeConfig

    # ------------------------------------------------------------------
    # Dynamic options
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # ExternalWebhookTriggerMixin — dashboard-only registration
    # ------------------------------------------------------------------

    @classmethod
    async def _register_external_webhook(
        cls,
        *,
        webhook_url: str,
        credential: Optional[Dict[str, Any]],
        config: Dict[str, Any],
        node_id: str,
    ) -> Optional[Dict[str, Any]]:
        signing_secret = (config or {}).get("signing_secret")
        if not signing_secret:
            raise ValueError(
                "Paste the URL above into Loops dashboard → Settings → Webhooks, "
                "then enter the Signing Secret shown by Loops into the field below."
            )
        return {"external_webhook_id": "loops-manual", "signing_secret": signing_secret}

    @classmethod
    async def _unregister_external_webhook(
        cls,
        *,
        credential: Optional[Dict[str, Any]],
        config: Dict[str, Any],
        node_id: str,
    ) -> None:
        logger.info(
            "[LoopsNode] No API to deregister Loops webhooks. "
            "Remove the webhook URL from Loops dashboard → Settings → Webhooks."
        )

    @classmethod
    def verify_webhook_signature(
        cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]
    ) -> bool:
        secret = (config or {}).get("signing_secret", "")
        wh_id = headers.get("webhook-id") or headers.get("Webhook-Id", "")
        ts = headers.get("webhook-timestamp") or headers.get("Webhook-Timestamp", "")
        sig = headers.get("webhook-signature") or headers.get("Webhook-Signature", "")
        return verify_svix(body, wh_id, ts, sig, secret)

    # ------------------------------------------------------------------
    # Dynamic options
    # ------------------------------------------------------------------

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        if field_name not in ("mailing_list_id", "transactional_id"):
            return {"options": []}
        api_key = (credential_data or {}).get("api_key")
        if not api_key:
            return {"options": []}

        if field_name == "mailing_list_id":
            result = await _loops_request(
                api_key, "GET", "/v1/lists", action_name="list_mailing_lists"
            )
            if result.get("status") != "success":
                return {"options": []}
            data = result.get("data") or []
            lists = data if isinstance(data, list) else data.get("data") or data.get("lists") or []
            options = []
            for ml in lists:
                if not isinstance(ml, dict):
                    continue
                ml_id = ml.get("id")
                name = ml.get("name") or f"List {ml_id}"
                if ml_id is not None:
                    options.append({"label": str(name), "value": str(ml_id)})
            return {"options": options}

        # transactional_id
        result = await _loops_request(
            api_key,
            "GET",
            "/v1/transactional-emails",
            params={"perPage": 50},
            action_name="list_transactional",
        )
        if result.get("status") != "success":
            return {"options": []}
        data = result.get("data") or {}
        emails = data if isinstance(data, list) else (data.get("data") or [])
        options = []
        for te in emails:
            if not isinstance(te, dict):
                continue
            te_id = te.get("id")
            name = te.get("name") or te.get("subject") or f"Email {te_id}"
            if te_id is not None:
                options.append({"label": str(name), "value": str(te_id)})
        return {"options": options}

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, LoopsNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        # Trigger operation — pass through the inbound webhook payload
        if isinstance(op, LoopsWebhookTriggerConfig):
            event_name = inputs.get("eventName") or "unknown"
            if op.event_type and event_name != op.event_type:
                return {
                    "status": "skipped",
                    "action": "on_loops_event",
                    "message": f"Event '{event_name}' did not match filter '{op.event_type}'",
                }
            return {"status": "success", "action": "on_loops_event", "data": inputs}

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your Loops API key.")
        api_key = credentials.api_key

        handlers = {
            "test_api_key": self._test_api_key,
            "create_contact": self._create_contact,
            "update_contact": self._update_contact,
            "find_contact": self._find_contact,
            "delete_contact": self._delete_contact,
            "get_suppression": self._get_suppression,
            "remove_suppression": self._remove_suppression,
            "create_contact_property": self._create_contact_property,
            "list_contact_properties": self._list_contact_properties,
            "list_mailing_lists": self._list_mailing_lists,
            "send_event": self._send_event,
            "send_transactional": self._send_transactional,
            "list_transactional": self._list_transactional,
            "get_transactional": self._get_transactional,
            "create_transactional_email": self._create_transactional_email,
            "update_transactional_email": self._update_transactional_email,
            "ensure_transactional_email_draft": self._ensure_transactional_email_draft,
            "publish_transactional_email": self._publish_transactional_email,
            "list_campaigns": self._list_campaigns,
            "create_campaign": self._create_campaign,
            "get_campaign": self._get_campaign,
            "update_campaign": self._update_campaign,
            "list_campaign_groups": self._list_campaign_groups,
            "get_campaign_group": self._get_campaign_group,
            "create_campaign_group": self._create_campaign_group,
            "update_campaign_group": self._update_campaign_group,
            "list_transactional_groups": self._list_transactional_groups,
            "get_transactional_group": self._get_transactional_group,
            "create_transactional_group": self._create_transactional_group,
            "update_transactional_group": self._update_transactional_group,
            "get_email_message": self._get_email_message,
            "update_email_message": self._update_email_message,
            "send_email_message_preview": self._send_email_message_preview,
            "list_themes": self._list_themes,
            "get_theme": self._get_theme,
            "list_components": self._list_components,
            "get_component": self._get_component,
            "list_audience_segments": self._list_audience_segments,
            "get_audience_segment": self._get_audience_segment,
            "create_upload": self._create_upload,
            "complete_upload": self._complete_upload,
            "list_workflows": self._list_workflows,
            "get_workflow": self._get_workflow,
            "get_workflow_node": self._get_workflow_node,
            "list_sending_ips": self._list_sending_ips,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(op, api_key)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------
    async def _test_api_key(self, c: LoopsTestApiKeyConfig, api_key: str) -> Dict[str, Any]:
        return await _loops_request(api_key, "GET", "/v1/api-key", action_name="test_api_key")

    async def _create_contact(self, c: LoopsCreateContactConfig, api_key: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "email": c.email,
            "firstName": c.first_name,
            "lastName": c.last_name,
            "userId": c.user_id,
            "subscribed": c.subscribed == "true" if c.subscribed else None,
        }
        if c.mailing_list_id:
            body["mailingLists"] = {c.mailing_list_id: True}
        props = _parse_json_object(c.properties, "Custom Properties")
        if props:
            body.update(props)
        return await _loops_request(
            api_key, "POST", "/v1/contacts/create", json_body=body, action_name="create_contact"
        )

    async def _update_contact(self, c: LoopsUpdateContactConfig, api_key: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "email": c.email,
            "firstName": c.first_name,
            "lastName": c.last_name,
            "userId": c.user_id,
            "subscribed": (c.subscribed == "true") if c.subscribed else None,
        }
        if c.mailing_list_id:
            body["mailingLists"] = {c.mailing_list_id: True}
        props = _parse_json_object(c.properties, "Custom Properties")
        if props:
            body.update(props)
        return await _loops_request(
            api_key, "PUT", "/v1/contacts/update", json_body=body, action_name="update_contact"
        )

    async def _find_contact(self, c: LoopsFindContactConfig, api_key: str) -> Dict[str, Any]:
        params = {"email": c.email, "userId": c.user_id}
        return await _loops_request(
            api_key, "GET", "/v1/contacts/find", params=params, action_name="find_contact"
        )

    async def _delete_contact(self, c: LoopsDeleteContactConfig, api_key: str) -> Dict[str, Any]:
        body = {"email": c.email, "userId": c.user_id}
        return await _loops_request(
            api_key, "POST", "/v1/contacts/delete", json_body=body, action_name="delete_contact"
        )

    async def _get_suppression(self, c: LoopsGetSuppressionConfig, api_key: str) -> Dict[str, Any]:
        return await _loops_request(
            api_key, "GET", "/v1/contacts/suppression", params={"email": c.email},
            action_name="get_suppression",
        )

    async def _remove_suppression(self, c: LoopsRemoveSuppressionConfig, api_key: str) -> Dict[str, Any]:
        return await _loops_request(
            api_key, "DELETE", "/v1/contacts/suppression", params={"email": c.email},
            action_name="remove_suppression",
        )

    async def _create_contact_property(
        self, c: LoopsCreateContactPropertyConfig, api_key: str
    ) -> Dict[str, Any]:
        body = {"name": c.name, "type": c.property_type}
        return await _loops_request(
            api_key, "POST", "/v1/contacts/properties", json_body=body,
            action_name="create_contact_property",
        )

    async def _list_contact_properties(
        self, c: LoopsListContactPropertiesConfig, api_key: str
    ) -> Dict[str, Any]:
        params = {"list": c.list_filter or None}
        return await _loops_request(
            api_key, "GET", "/v1/contacts/properties", params=params,
            action_name="list_contact_properties",
        )

    async def _list_mailing_lists(self, c: LoopsListMailingListsConfig, api_key: str) -> Dict[str, Any]:
        return await _loops_request(api_key, "GET", "/v1/lists", action_name="list_mailing_lists")

    async def _send_event(self, c: LoopsSendEventConfig, api_key: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "eventName": c.event_name,
            "email": c.email,
            "userId": c.user_id,
            "eventProperties": _parse_json_object(c.event_properties, "Event Properties"),
            "contactProperties": _parse_json_object(c.contact_properties, "Contact Properties"),
        }
        return await _loops_request(
            api_key, "POST", "/v1/events/send", json_body=body, action_name="send_event"
        )

    async def _send_transactional(self, c: LoopsSendTransactionalConfig, api_key: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "transactionalId": c.transactional_id,
            "email": c.email,
            "dataVariables": _parse_json_object(c.data_variables, "Data Variables"),
            "addToAudience": c.add_to_audience == "true" if c.add_to_audience else None,
        }
        return await _loops_request(
            api_key, "POST", "/v1/transactional", json_body=body, action_name="send_transactional"
        )

    async def _list_transactional(self, c: LoopsListTransactionalConfig, api_key: str) -> Dict[str, Any]:
        params = {"perPage": c.per_page, "cursor": c.cursor}
        return await _loops_request(
            api_key, "GET", "/v1/transactional-emails", params=params,
            action_name="list_transactional",
        )

    async def _get_transactional(self, c: LoopsGetTransactionalConfig, api_key: str) -> Dict[str, Any]:
        return await _loops_request(
            api_key, "GET", f"/v1/transactional-emails/{c.transactional_id}",
            action_name="get_transactional",
        )

    async def _list_campaigns(self, c: LoopsListCampaignsConfig, api_key: str) -> Dict[str, Any]:
        params = {"perPage": c.per_page, "cursor": c.cursor}
        return await _loops_request(
            api_key, "GET", "/v1/campaigns", params=params, action_name="list_campaigns"
        )

    async def _create_campaign(self, c: LoopsCreateCampaignConfig, api_key: str) -> Dict[str, Any]:
        body = {"name": c.name, "subject": c.subject, "fromName": c.from_name}
        return await _loops_request(
            api_key, "POST", "/v1/campaigns", json_body=body, action_name="create_campaign"
        )

    async def _get_campaign(self, c: LoopsGetCampaignConfig, api_key: str) -> Dict[str, Any]:
        return await _loops_request(
            api_key, "GET", f"/v1/campaigns/{c.campaign_id}", action_name="get_campaign"
        )

    async def _update_campaign(self, c: LoopsUpdateCampaignConfig, api_key: str) -> Dict[str, Any]:
        body = {"name": c.name, "subject": c.subject, "fromName": c.from_name}
        return await _loops_request(
            api_key, "POST", f"/v1/campaigns/{c.campaign_id}", json_body=body,
            action_name="update_campaign",
        )

    async def _get_email_message(self, c: LoopsGetEmailMessageConfig, api_key: str) -> Dict[str, Any]:
        return await _loops_request(
            api_key, "GET", f"/v1/email-messages/{c.email_message_id}",
            action_name="get_email_message",
        )

    async def _update_email_message(
        self, c: LoopsUpdateEmailMessageConfig, api_key: str
    ) -> Dict[str, Any]:
        body = {
            "subject": c.subject,
            "fromName": c.from_name,
            "previewText": c.preview_text,
            "content": _parse_json_object(c.content, "Content"),
        }
        return await _loops_request(
            api_key, "POST", f"/v1/email-messages/{c.email_message_id}", json_body=body,
            action_name="update_email_message",
        )

    async def _list_themes(self, c: LoopsListThemesConfig, api_key: str) -> Dict[str, Any]:
        params = {"perPage": c.per_page, "cursor": c.cursor}
        return await _loops_request(
            api_key, "GET", "/v1/themes", params=params, action_name="list_themes"
        )

    async def _list_components(self, c: LoopsListComponentsConfig, api_key: str) -> Dict[str, Any]:
        params = {"perPage": c.per_page, "cursor": c.cursor}
        return await _loops_request(
            api_key, "GET", "/v1/components", params=params, action_name="list_components"
        )

    async def _list_audience_segments(
        self, c: LoopsListAudienceSegmentsConfig, api_key: str
    ) -> Dict[str, Any]:
        params = {"perPage": c.per_page, "cursor": c.cursor}
        return await _loops_request(
            api_key, "GET", "/v1/audience-segments", params=params,
            action_name="list_audience_segments",
        )

    async def _create_upload(self, c: LoopsCreateUploadConfig, api_key: str) -> Dict[str, Any]:
        if not c.image:
            raise ValueError("Image is required for upload")
        # The shared resolver scopes resource UUIDs to this workflow and uses a
        # DNS-pinned client for URL/presigned downloads. A copied UUID from a
        # different workflow is not an ambient file capability.
        resolved = await resolve_media_input(
            c.image,
            workflow_id=self.workflow_id,
            default_mime="image/jpeg",
        )
        file_bytes = resolved.data
        content_type = resolved.mime_type
        # Step 1: Get Loops presigned upload URL (contentLength required, not fileName)
        init_result = await _loops_request(
            api_key, "POST", "/v1/uploads",
            json_body={"contentLength": len(file_bytes), "contentType": content_type},
            action_name="create_upload_init",
        )
        if init_result.get("status") != "success":
            return init_result
        upload_data = init_result.get("data", {})
        presigned_url = upload_data.get("presignedUrl")
        # Loops returns emailAssetId as the asset identifier
        asset_id = upload_data.get("emailAssetId") or upload_data.get("id")
        if not presigned_url or not asset_id:
            return {
                "status": "error",
                "action": "create_upload",
                "error": "Loops did not return a presignedUrl or emailAssetId",
                "data": upload_data,
            }
        # Step 2: PUT file bytes to Loops presigned S3 URL
        async with guarded_async_client(timeout=120.0) as client:
            put_resp = await client.put(
                presigned_url,
                content=file_bytes,
                headers={"Content-Type": content_type},
            )
            if put_resp.status_code >= 400:
                return {
                    "status": "error",
                    "action": "create_upload_put",
                    "error": f"PUT to presigned URL failed with status {put_resp.status_code}",
                }
        # Step 3: Complete the upload
        complete_result = await _loops_request(
            api_key, "POST", f"/v1/uploads/{asset_id}/complete",
            action_name="create_upload_complete",
        )
        if complete_result.get("status") != "success":
            return complete_result
        return {
            "status": "success",
            "action": "create_upload",
            "data": complete_result.get("data", {}),
            "asset_id": asset_id,
        }

    async def _complete_upload(self, c: LoopsCompleteUploadConfig, api_key: str) -> Dict[str, Any]:
        return await _loops_request(
            api_key, "POST", f"/v1/uploads/{c.upload_id}/complete",
            action_name="complete_upload",
        )

    async def _send_email_message_preview(
        self, c: LoopsSendEmailMessagePreviewConfig, api_key: str
    ) -> Dict[str, Any]:
        import json
        try:
            emails_list = json.loads(c.emails)
            if not isinstance(emails_list, list):
                raise ValueError("emails must be a JSON array")
        except (json.JSONDecodeError, ValueError) as e:
            raise ValueError(f"Preview Recipients: {e}")
        body: Dict[str, Any] = {
            "emails": emails_list,
            "dataVariables": _parse_json_object(c.data_variables, "Data Variables"),
        }
        return await _loops_request(
            api_key, "POST", f"/v1/email-messages/{c.email_message_id}/preview",
            json_body=body, action_name="send_email_message_preview",
        )

    async def _create_transactional_email(
        self, c: LoopsCreateTransactionalEmailConfig, api_key: str
    ) -> Dict[str, Any]:
        body = {
            "name": c.name,
            "transactionalGroupId": c.group_id,
        }
        return await _loops_request(
            api_key, "POST", "/v1/transactional-emails",
            json_body=body, action_name="create_transactional_email",
        )

    async def _update_transactional_email(
        self, c: LoopsUpdateTransactionalEmailConfig, api_key: str
    ) -> Dict[str, Any]:
        body = {
            "name": c.name,
            "transactionalGroupId": c.group_id,
        }
        return await _loops_request(
            api_key, "POST", f"/v1/transactional-emails/{c.transactional_id}",
            json_body=body, action_name="update_transactional_email",
        )

    async def _ensure_transactional_email_draft(
        self, c: LoopsEnsureTransactionalEmailDraftConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _loops_request(
            api_key, "POST", f"/v1/transactional-emails/{c.transactional_id}/draft",
            action_name="ensure_transactional_email_draft",
        )

    async def _publish_transactional_email(
        self, c: LoopsPublishTransactionalEmailConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _loops_request(
            api_key, "POST", f"/v1/transactional-emails/{c.transactional_id}/publish",
            action_name="publish_transactional_email",
        )

    async def _list_campaign_groups(self, c: LoopsListCampaignGroupsConfig, api_key: str) -> Dict[str, Any]:
        params = {"perPage": c.per_page, "cursor": c.cursor}
        return await _loops_request(
            api_key, "GET", "/v1/campaign-groups", params=params, action_name="list_campaign_groups"
        )

    async def _get_campaign_group(self, c: LoopsGetCampaignGroupConfig, api_key: str) -> Dict[str, Any]:
        return await _loops_request(
            api_key, "GET", f"/v1/campaign-groups/{c.group_id}", action_name="get_campaign_group"
        )

    async def _create_campaign_group(self, c: LoopsCreateCampaignGroupConfig, api_key: str) -> Dict[str, Any]:
        return await _loops_request(
            api_key, "POST", "/v1/campaign-groups",
            json_body={"name": c.name}, action_name="create_campaign_group",
        )

    async def _update_campaign_group(self, c: LoopsUpdateCampaignGroupConfig, api_key: str) -> Dict[str, Any]:
        return await _loops_request(
            api_key, "POST", f"/v1/campaign-groups/{c.group_id}",
            json_body={"name": c.name}, action_name="update_campaign_group",
        )

    async def _list_transactional_groups(
        self, c: LoopsListTransactionalGroupsConfig, api_key: str
    ) -> Dict[str, Any]:
        params = {"perPage": c.per_page, "cursor": c.cursor}
        return await _loops_request(
            api_key, "GET", "/v1/transactional-groups", params=params,
            action_name="list_transactional_groups",
        )

    async def _get_transactional_group(
        self, c: LoopsGetTransactionalGroupConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _loops_request(
            api_key, "GET", f"/v1/transactional-groups/{c.group_id}",
            action_name="get_transactional_group",
        )

    async def _create_transactional_group(
        self, c: LoopsCreateTransactionalGroupConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _loops_request(
            api_key, "POST", "/v1/transactional-groups",
            json_body={"name": c.name}, action_name="create_transactional_group",
        )

    async def _update_transactional_group(
        self, c: LoopsUpdateTransactionalGroupConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _loops_request(
            api_key, "POST", f"/v1/transactional-groups/{c.group_id}",
            json_body={"name": c.name}, action_name="update_transactional_group",
        )

    async def _get_theme(self, c: LoopsGetThemeConfig, api_key: str) -> Dict[str, Any]:
        return await _loops_request(
            api_key, "GET", f"/v1/themes/{c.theme_id}", action_name="get_theme"
        )

    async def _get_component(self, c: LoopsGetComponentConfig, api_key: str) -> Dict[str, Any]:
        return await _loops_request(
            api_key, "GET", f"/v1/components/{c.component_id}", action_name="get_component"
        )

    async def _get_audience_segment(self, c: LoopsGetAudienceSegmentConfig, api_key: str) -> Dict[str, Any]:
        return await _loops_request(
            api_key, "GET", f"/v1/audience-segments/{c.segment_id}",
            action_name="get_audience_segment",
        )

    async def _list_workflows(self, c: LoopsListWorkflowsConfig, api_key: str) -> Dict[str, Any]:
        params = {"perPage": c.per_page, "cursor": c.cursor}
        return await _loops_request(
            api_key, "GET", "/v1/workflows", params=params, action_name="list_workflows"
        )

    async def _get_workflow(self, c: LoopsGetWorkflowConfig, api_key: str) -> Dict[str, Any]:
        return await _loops_request(
            api_key, "GET", f"/v1/workflows/{c.workflow_id}", action_name="get_workflow"
        )

    async def _get_workflow_node(self, c: LoopsGetWorkflowNodeConfig, api_key: str) -> Dict[str, Any]:
        return await _loops_request(
            api_key, "GET", f"/v1/workflows/{c.workflow_id}/nodes/{c.node_id}",
            action_name="get_workflow_node",
        )

    async def _list_sending_ips(self, c: LoopsListSendingIpsConfig, api_key: str) -> Dict[str, Any]:
        return await _loops_request(
            api_key, "GET", "/v1/dedicated-sending-ips", action_name="list_sending_ips"
        )
