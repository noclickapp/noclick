"""
Luma (lu.ma) event-management automation node.

Provides workflow integration with the Luma public API for operations including:
- Account: get self (auth-test ping)
- Events: list, get, create, update, cancel, lookup
- Guests: list, get, add, update status, send invites
- Hosts: add, update, remove
- Ticket Types: list, create, update
- Coupons: create / list (event + calendar)
- Calendar: get, update, list admins, list contacts, import contacts, create event tag
- Webhooks: list, create
- Webhook Trigger: fire when a Luma event/guest/ticket changes

Authentication: API Key (calendar- or org-scoped) sent in the `x-luma-api-key`
header. Requires an active Luma Plus subscription on the calendar.

API Base URL: https://public-api.luma.com (paths are versioned per-endpoint:
most are `/v1/...`; webhook create is `/v2/...`).
Documentation: https://docs.luma.com/reference/getting-started-with-your-api
"""

import hashlib
from datetime import datetime
from urllib.parse import urlsplit
import hmac
import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator, AfterValidator, WithJsonSchema
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin

logger = logging.getLogger(__name__)

LUMA_API_BASE = "https://public-api.luma.com"


def _validate_event_time(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError("Use an ISO 8601 date-time with a timezone") from None
    if parsed.tzinfo is None:
        raise ValueError("Use an ISO 8601 date-time with a timezone")
    return value


def _validate_webhook_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError
        parsed.port
    except ValueError:
        raise ValueError("Use an absolute HTTP or HTTPS webhook URL") from None
    return value


LumaEventTime = Annotated[
    str, AfterValidator(_validate_event_time),
    WithJsonSchema({"type": "string", "format": "date-time"}),
]
LumaWebhookUrl = Annotated[
    str, AfterValidator(_validate_webhook_url),
    WithJsonSchema({"type": "string", "format": "uri"}),
]

# Event types the trigger subscribes to (Luma webhook event-type enum).
LUMA_TRIGGER_EVENT_TYPES = [
    "event.created",
    "event.updated",
    "event.canceled",
    "guest.registered",
    "guest.updated",
    "ticket.registered",
    "calendar.event.added",
    "calendar.person.subscribed",
]


# ============================================================================
# Credential Schema
# ============================================================================


class LumaApiKeyCredential(BaseModel):
    """API Key credential for Luma (calendar- or organization-scoped)."""

    credential_type: Literal["luma_api_key"] = Field(
        "luma_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description="Your Luma API key from Calendar -> Settings -> Developer -> API Keys (requires Luma Plus). Sent as the x-luma-api-key header.",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        title="Luma API Key",
        json_schema_extra={"x-credential-url": "https://luma.com/calendar/manage/api-keys"}
    )


LumaCredential = LumaApiKeyCredential


# ============================================================================
# Account Operation Configs
# ============================================================================


class LumaGetSelfConfig(BaseModel):
    """Return info about the authenticated user (also the auth-test ping)."""

    operation: Literal["get_self"] = Field(
        "get_self",
        json_schema_extra={
            "const": "get_self",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Get Self",
        },
        title="Get Self",
    )


# ============================================================================
# Event Operation Configs
# ============================================================================


class LumaListEventsConfig(BaseModel):
    """List events the calendar manages."""

    operation: Literal["list_events"] = Field(
        "list_events",
        json_schema_extra={
            "const": "list_events",
            "ui:hidden": True,
            "x-category": "Events",
            "x-is-trigger": False,
            "x-display-name": "List Events",
        },
        title="List Events",
    )
    after: Optional[str] = Field(
        None, title="After", description="ISO 8601 lower bound — only events starting after this time"
    )
    before: Optional[str] = Field(
        None, title="Before", description="ISO 8601 upper bound — only events starting before this time"
    )
    pagination_cursor: Optional[str] = Field(
        None, title="Pagination Cursor", description="Cursor from a previous response's next_cursor to fetch the next page"
    )
    pagination_limit: Optional[str] = Field(
        None, title="Page Size", description="Maximum number of events to return per page"
    )


class LumaGetEventConfig(BaseModel):
    """Return full details about an event you have manage access for."""

    operation: Literal["get_event"] = Field(
        "get_event",
        json_schema_extra={
            "const": "get_event",
            "ui:hidden": True,
            "x-category": "Events",
            "x-is-trigger": False,
            "x-display-name": "Get Event",
        },
        title="Get Event",
    )
    event_api_id: str = Field(
        ...,
        title="Event",
        description="The event API id (evt-...)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "event_api_id",
                "placeholder": "Select an event...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste event id (evt-...)",
            }
        },
    )


class LumaCreateEventConfig(BaseModel):
    """Create a new event on the calendar."""

    operation: Literal["create_event"] = Field(
        "create_event",
        json_schema_extra={
            "const": "create_event",
            "ui:hidden": True,
            "x-category": "Events",
            "x-is-trigger": False,
            "x-display-name": "Create Event",
        },
        title="Create Event",
    )
    name: str = Field(..., title="Name", description="Name / title of the event")
    start_at: LumaEventTime = Field(
        ..., title="Start Time", description="Event start time in ISO 8601 (e.g. 2026-07-01T18:00:00Z)"
    )
    timezone: str = Field(
        ..., title="Timezone", description="IANA timezone for the event (e.g. America/New_York)"
    )
    end_at: Optional[LumaEventTime] = Field(
        None, title="End Time", description="Event end time in ISO 8601 (optional)"
    )
    require_rsvp_approval: Optional[str] = Field(
        "false",
        title="Require RSVP Approval",
        description="Whether guests need host approval to register",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class LumaUpdateEventConfig(BaseModel):
    """Update an existing event's details."""

    operation: Literal["update_event"] = Field(
        "update_event",
        json_schema_extra={
            "const": "update_event",
            "ui:hidden": True,
            "x-category": "Events",
            "x-is-trigger": False,
            "x-display-name": "Update Event",
        },
        title="Update Event",
    )
    event_api_id: str = Field(
        ...,
        title="Event",
        description="The event API id (evt-...) to update",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "event_api_id",
                "placeholder": "Select an event...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste event id (evt-...)",
            }
        },
    )
    name: Optional[str] = Field(None, title="Name", description="New event name (optional)")
    start_at: Optional[LumaEventTime] = Field(
        None, title="Start Time", description="New start time in ISO 8601 (optional)"
    )
    end_at: Optional[LumaEventTime] = Field(
        None, title="End Time", description="New end time in ISO 8601 (optional)"
    )
    timezone: Optional[str] = Field(
        None, title="Timezone", description="New IANA timezone (optional)"
    )


class LumaCancelEventConfig(BaseModel):
    """Cancel an event. Pair with the cancel-request token obtained from Luma."""

    operation: Literal["cancel_event"] = Field(
        "cancel_event",
        json_schema_extra={
            "const": "cancel_event",
            "ui:hidden": True,
            "x-category": "Events",
            "x-is-trigger": False,
            "x-display-name": "Cancel Event",
        },
        title="Cancel Event",
    )
    event_api_id: str = Field(
        ...,
        title="Event",
        description="The event API id (evt-...) to cancel",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "event_api_id",
                "placeholder": "Select an event...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste event id (evt-...)",
            }
        },
    )
    cancellation_token: str = Field(
        ...,
        title="Cancellation Token",
        description="Token from POST /v1/events/cancel/request, required by Luma to confirm cancellation",
    )


class LumaLookupEventConfig(BaseModel):
    """Check whether an event already exists on the calendar."""

    operation: Literal["lookup_event"] = Field(
        "lookup_event",
        json_schema_extra={
            "const": "lookup_event",
            "ui:hidden": True,
            "x-category": "Events",
            "x-is-trigger": False,
            "x-display-name": "Lookup Event",
        },
        title="Lookup Event",
    )
    platform: Optional[str] = Field(
        None, title="Platform", description="Platform to look up",
        json_schema_extra={"enum": ["external", "luma"]}
    )
    url: Optional[str] = Field(
        None, title="URL", description="Event URL to look up"
    )


# ============================================================================
# Guest Operation Configs
# ============================================================================


class LumaListGuestsConfig(BaseModel):
    """List guests who registered or were invited to an event."""

    operation: Literal["list_guests"] = Field(
        "list_guests",
        json_schema_extra={
            "const": "list_guests",
            "ui:hidden": True,
            "x-category": "Guests",
            "x-is-trigger": False,
            "x-display-name": "List Guests",
        },
        title="List Guests",
    )
    event_api_id: str = Field(
        ...,
        title="Event",
        description="The event API id (evt-...) to list guests for",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "event_api_id",
                "placeholder": "Select an event...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste event id (evt-...)",
            }
        },
    )
    approval_status: Optional[str] = Field(
        None,
        title="Approval Status",
        description="Filter by guest approval status",
        json_schema_extra={
            "enum": ["", "approved", "pending_approval", "declined", "invited"],
            "enumNames": ["Any", "Approved", "Pending Approval", "Declined", "Invited"],
            "x-enum-searchable": True,
        },
    )
    pagination_cursor: Optional[str] = Field(
        None, title="Pagination Cursor", description="Cursor from a previous response's next_cursor"
    )
    pagination_limit: Optional[str] = Field(
        None, title="Page Size", description="Maximum number of guests to return per page"
    )


class LumaGetGuestConfig(BaseModel):
    """Get detailed information for a single event guest."""

    operation: Literal["get_guest"] = Field(
        "get_guest",
        json_schema_extra={
            "const": "get_guest",
            "ui:hidden": True,
            "x-category": "Guests",
            "x-is-trigger": False,
            "x-display-name": "Get Guest",
        },
        title="Get Guest",
    )
    event_api_id: str = Field(
        ...,
        title="Event",
        description="The event API id (evt-...)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "event_api_id",
                "placeholder": "Select an event...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste event id (evt-...)",
            }
        },
    )
    email: Optional[str] = Field(
        None, title="Guest Email", description="Email of the guest to look up"
    )
    api_id: Optional[str] = Field(
        None, title="Guest API ID", description="The guest API id to look up (alternative to email)"
    )


class LumaAddGuestsConfig(BaseModel):
    """Add (register/invite) guests to an event."""

    operation: Literal["add_guests"] = Field(
        "add_guests",
        json_schema_extra={
            "const": "add_guests",
            "ui:hidden": True,
            "x-category": "Guests",
            "x-is-trigger": False,
            "x-display-name": "Add Guests",
        },
        title="Add Guests",
    )
    event_api_id: str = Field(
        ...,
        title="Event",
        description="The event API id (evt-...) to add guests to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "event_api_id",
                "placeholder": "Select an event...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste event id (evt-...)",
            }
        },
    )
    emails: str = Field(
        ...,
        title="Guest Emails",
        description="Guest email addresses to add, comma-separated",
    )


class LumaUpdateGuestStatusConfig(BaseModel):
    """Approve, decline, or otherwise change a guest's status."""

    operation: Literal["update_guest_status"] = Field(
        "update_guest_status",
        json_schema_extra={
            "const": "update_guest_status",
            "ui:hidden": True,
            "x-category": "Guests",
            "x-is-trigger": False,
            "x-display-name": "Update Guest Status",
        },
        title="Update Guest Status",
    )
    event_api_id: str = Field(
        ...,
        title="Event",
        description="The event API id (evt-...)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "event_api_id",
                "placeholder": "Select an event...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste event id (evt-...)",
            }
        },
    )
    guest_api_id: str = Field(
        ..., title="Guest API ID", description="The guest API id to update"
    )
    status: str = Field(
        ...,
        title="Status",
        description="New status for the guest",
        json_schema_extra={
            "enum": ["approved", "declined", "pending_approval", "waitlist"],
            "enumNames": ["Approved", "Declined", "Pending Approval", "Waitlist"],
            "x-enum-searchable": True,
        },
    )


class LumaSendInvitesConfig(BaseModel):
    """Send invitation emails to event guests."""

    operation: Literal["send_invites"] = Field(
        "send_invites",
        json_schema_extra={
            "const": "send_invites",
            "ui:hidden": True,
            "x-category": "Guests",
            "x-is-trigger": False,
            "x-display-name": "Send Invites",
        },
        title="Send Invites",
    )
    event_api_id: str = Field(
        ...,
        title="Event",
        description="The event API id (evt-...) whose guests to invite",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "event_api_id",
                "placeholder": "Select an event...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste event id (evt-...)",
            }
        },
    )
    emails: str = Field(
        ...,
        title="Guest Emails",
        description="Guest email addresses to invite, comma-separated",
    )


# ============================================================================
# Host Operation Configs
# ============================================================================


class LumaAddHostConfig(BaseModel):
    """Add a host to an event."""

    operation: Literal["add_host"] = Field(
        "add_host",
        json_schema_extra={
            "const": "add_host",
            "ui:hidden": True,
            "x-category": "Hosts",
            "x-is-trigger": False,
            "x-display-name": "Add Host",
        },
        title="Add Host",
    )
    event_api_id: str = Field(
        ...,
        title="Event",
        description="The event API id (evt-...)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "event_api_id",
                "placeholder": "Select an event...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste event id (evt-...)",
            }
        },
    )
    email: str = Field(..., title="Host Email", description="Email of the host to add")
    access_level: Optional[str] = Field(
        None,
        title="Access Level",
        description="Host access level / permissions",
        json_schema_extra={
            "enum": ["", "manager", "check-in", "none"],
            "enumNames": ["Default", "Manager", "Check-in", "None"],
            "x-enum-searchable": True,
        },
    )


class LumaUpdateHostConfig(BaseModel):
    """Update a host's permissions or visibility."""

    operation: Literal["update_host"] = Field(
        "update_host",
        json_schema_extra={
            "const": "update_host",
            "ui:hidden": True,
            "x-category": "Hosts",
            "x-is-trigger": False,
            "x-display-name": "Update Host",
        },
        title="Update Host",
    )
    event_api_id: str = Field(
        ...,
        title="Event",
        description="The event API id (evt-...)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "event_api_id",
                "placeholder": "Select an event...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste event id (evt-...)",
            }
        },
    )
    email: str = Field(..., title="Host Email", description="Email of the host to update")
    access_level: Optional[str] = Field(
        None,
        title="Access Level",
        description="New host access level / permissions",
        json_schema_extra={
            "enum": ["", "manager", "check-in", "none"],
            "enumNames": ["Unchanged", "Manager", "Check-in", "None"],
            "x-enum-searchable": True,
        },
    )


class LumaRemoveHostConfig(BaseModel):
    """Remove a host from an event."""

    operation: Literal["remove_host"] = Field(
        "remove_host",
        json_schema_extra={
            "const": "remove_host",
            "ui:hidden": True,
            "x-category": "Hosts",
            "x-is-trigger": False,
            "x-display-name": "Remove Host",
        },
        title="Remove Host",
    )
    event_api_id: str = Field(
        ...,
        title="Event",
        description="The event API id (evt-...)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "event_api_id",
                "placeholder": "Select an event...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste event id (evt-...)",
            }
        },
    )
    email: str = Field(..., title="Host Email", description="Email of the host to remove")


# ============================================================================
# Ticket Type Operation Configs
# ============================================================================


class LumaListTicketTypesConfig(BaseModel):
    """List all ticket types for an event."""

    operation: Literal["list_ticket_types"] = Field(
        "list_ticket_types",
        json_schema_extra={
            "const": "list_ticket_types",
            "ui:hidden": True,
            "x-category": "Ticket Types",
            "x-is-trigger": False,
            "x-display-name": "List Ticket Types",
        },
        title="List Ticket Types",
    )
    event_api_id: str = Field(
        ...,
        title="Event",
        description="The event API id (evt-...)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "event_api_id",
                "placeholder": "Select an event...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste event id (evt-...)",
            }
        },
    )


class LumaCreateTicketTypeConfig(BaseModel):
    """Create a new ticket type for an event."""

    operation: Literal["create_ticket_type"] = Field(
        "create_ticket_type",
        json_schema_extra={
            "const": "create_ticket_type",
            "ui:hidden": True,
            "x-category": "Ticket Types",
            "x-is-trigger": False,
            "x-display-name": "Create Ticket Type",
        },
        title="Create Ticket Type",
    )
    event_api_id: str = Field(
        ...,
        title="Event",
        description="The event API id (evt-...)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "event_api_id",
                "placeholder": "Select an event...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste event id (evt-...)",
            }
        },
    )
    name: str = Field(..., title="Name", description="Name of the ticket type")
    cents: Optional[str] = Field(
        None, title="Price (cents)", description="Ticket price in cents (omit for a free ticket)"
    )
    currency: Optional[str] = Field(
        None, title="Currency", description="ISO 4217 currency code (e.g. USD), required if priced"
    )
    max_capacity: Optional[str] = Field(
        None, title="Max Capacity", description="Maximum number of tickets of this type (optional)"
    )


class LumaUpdateTicketTypeConfig(BaseModel):
    """Update an existing ticket type configuration."""

    operation: Literal["update_ticket_type"] = Field(
        "update_ticket_type",
        json_schema_extra={
            "const": "update_ticket_type",
            "ui:hidden": True,
            "x-category": "Ticket Types",
            "x-is-trigger": False,
            "x-display-name": "Update Ticket Type",
        },
        title="Update Ticket Type",
    )
    event_api_id: str = Field(
        ...,
        title="Event",
        description="The event API id (evt-...)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "event_api_id",
                "placeholder": "Select an event...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste event id (evt-...)",
            }
        },
    )
    ticket_type_api_id: str = Field(
        ..., title="Ticket Type API ID", description="The ticket type API id to update"
    )
    name: Optional[str] = Field(None, title="Name", description="New ticket type name (optional)")
    cents: Optional[str] = Field(
        None, title="Price (cents)", description="New ticket price in cents (optional)"
    )
    max_capacity: Optional[str] = Field(
        None, title="Max Capacity", description="New maximum capacity (optional)"
    )


# ============================================================================
# Coupon Operation Configs
# ============================================================================


class LumaCreateEventCouponConfig(BaseModel):
    """Create a coupon applied when a guest registers for the event."""

    operation: Literal["create_event_coupon"] = Field(
        "create_event_coupon",
        json_schema_extra={
            "const": "create_event_coupon",
            "ui:hidden": True,
            "x-category": "Coupons",
            "x-is-trigger": False,
            "x-display-name": "Create Event Coupon",
        },
        title="Create Event Coupon",
    )
    event_api_id: str = Field(
        ...,
        title="Event",
        description="The event API id (evt-...)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "event_api_id",
                "placeholder": "Select an event...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste event id (evt-...)",
            }
        },
    )
    name: Optional[str] = Field(None, title="Name", description="Local label; not sent to Luma")
    code: str = Field(..., title="Code", description="Coupon code guests enter at registration")
    discount_type: str = Field(
        ...,
        title="Discount Type",
        description="Whether the discount is a percentage or a fixed amount",
        json_schema_extra={
            "enum": ["percent", "amount"],
            "enumNames": ["Percentage", "Fixed Amount"],
            "x-enum-searchable": True,
        },
    )
    discount_value: str = Field(
        ...,
        title="Discount Value",
        description="Discount amount — a percentage (0-100) or amount in cents depending on type",
    )
    currency: str = Field("usd", title="Currency", description="Currency code for a fixed amount discount, e.g. usd")


class LumaListEventCouponsConfig(BaseModel):
    """List all coupons created for an event."""

    operation: Literal["list_event_coupons"] = Field(
        "list_event_coupons",
        json_schema_extra={
            "const": "list_event_coupons",
            "ui:hidden": True,
            "x-category": "Coupons",
            "x-is-trigger": False,
            "x-display-name": "List Event Coupons",
        },
        title="List Event Coupons",
    )
    event_api_id: str = Field(
        ...,
        title="Event",
        description="The event API id (evt-...)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "event_api_id",
                "placeholder": "Select an event...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste event id (evt-...)",
            }
        },
    )


class LumaCreateCalendarCouponConfig(BaseModel):
    """Create a coupon usable on any event in the calendar."""

    operation: Literal["create_calendar_coupon"] = Field(
        "create_calendar_coupon",
        json_schema_extra={
            "const": "create_calendar_coupon",
            "ui:hidden": True,
            "x-category": "Coupons",
            "x-is-trigger": False,
            "x-display-name": "Create Calendar Coupon",
        },
        title="Create Calendar Coupon",
    )
    name: Optional[str] = Field(None, title="Name", description="Local label; not sent to Luma")
    code: str = Field(..., title="Code", description="Coupon code guests enter at registration")
    discount_type: str = Field(
        ...,
        title="Discount Type",
        description="Whether the discount is a percentage or a fixed amount",
        json_schema_extra={
            "enum": ["percent", "amount"],
            "enumNames": ["Percentage", "Fixed Amount"],
            "x-enum-searchable": True,
        },
    )
    discount_value: str = Field(
        ...,
        title="Discount Value",
        description="Discount amount — a percentage (0-100) or amount in cents depending on type",
    )
    currency: str = Field("usd", title="Currency", description="Currency code for a fixed amount discount, e.g. usd")


class LumaListCalendarCouponsConfig(BaseModel):
    """List all coupons created for the calendar."""

    operation: Literal["list_calendar_coupons"] = Field(
        "list_calendar_coupons",
        json_schema_extra={
            "const": "list_calendar_coupons",
            "ui:hidden": True,
            "x-category": "Coupons",
            "x-is-trigger": False,
            "x-display-name": "List Calendar Coupons",
        },
        title="List Calendar Coupons",
    )


# ============================================================================
# Calendar Operation Configs
# ============================================================================


class LumaGetCalendarConfig(BaseModel):
    """Get calendar information/settings."""

    operation: Literal["get_calendar"] = Field(
        "get_calendar",
        json_schema_extra={
            "const": "get_calendar",
            "ui:hidden": True,
            "x-category": "Calendar",
            "x-is-trigger": False,
            "x-display-name": "Get Calendar",
        },
        title="Get Calendar",
    )


class LumaUpdateCalendarConfig(BaseModel):
    """Update a calendar's settings."""

    operation: Literal["update_calendar"] = Field(
        "update_calendar",
        json_schema_extra={
            "const": "update_calendar",
            "ui:hidden": True,
            "x-category": "Calendar",
            "x-is-trigger": False,
            "x-display-name": "Update Calendar",
        },
        title="Update Calendar",
    )
    calendar_id: str = Field(..., title="Calendar ID", description="Calendar ID (cal-...) to update")
    name: Optional[str] = Field(None, title="Name", description="New calendar name (optional)")
    description: Optional[str] = Field(
        None,
        title="Description",
        description="New calendar description (optional)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class LumaListCalendarAdminsConfig(BaseModel):
    """List all admins for the calendar."""

    operation: Literal["list_calendar_admins"] = Field(
        "list_calendar_admins",
        json_schema_extra={
            "const": "list_calendar_admins",
            "ui:hidden": True,
            "x-category": "Calendar",
            "x-is-trigger": False,
            "x-display-name": "List Calendar Admins",
        },
        title="List Calendar Admins",
    )


class LumaListContactsConfig(BaseModel):
    """List calendar contacts (cursor-paginated)."""

    operation: Literal["list_contacts"] = Field(
        "list_contacts",
        json_schema_extra={
            "const": "list_contacts",
            "ui:hidden": True,
            "x-category": "Calendar",
            "x-is-trigger": False,
            "x-display-name": "List Contacts",
        },
        title="List Contacts",
    )
    pagination_cursor: Optional[str] = Field(
        None, title="Pagination Cursor", description="Cursor from a previous response's next_cursor"
    )
    pagination_limit: Optional[str] = Field(
        None, title="Page Size", description="Maximum number of contacts to return per page"
    )


class LumaImportContactsConfig(BaseModel):
    """Import contacts to the calendar so they can be invited to events."""

    operation: Literal["import_contacts"] = Field(
        "import_contacts",
        json_schema_extra={
            "const": "import_contacts",
            "ui:hidden": True,
            "x-category": "Calendar",
            "x-is-trigger": False,
            "x-display-name": "Import Contacts",
        },
        title="Import Contacts",
    )
    emails: str = Field(
        ...,
        title="Contact Emails",
        description="Contact email addresses to import, comma-separated",
    )


class LumaCreateEventTagConfig(BaseModel):
    """Create an event tag on the calendar."""

    operation: Literal["create_event_tag"] = Field(
        "create_event_tag",
        json_schema_extra={
            "const": "create_event_tag",
            "ui:hidden": True,
            "x-category": "Calendar",
            "x-is-trigger": False,
            "x-display-name": "Create Event Tag",
        },
        title="Create Event Tag",
    )
    name: str = Field(..., title="Name", description="Name of the event tag to create")


# ============================================================================
# Webhook Operation Configs
# ============================================================================


class LumaListWebhooksConfig(BaseModel):
    """List all webhook endpoints registered for the calendar."""

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


class LumaCreateWebhookConfig(BaseModel):
    """Register a webhook endpoint to receive event notifications."""

    operation: Literal["create_webhook"] = Field(
        "create_webhook",
        json_schema_extra={
            "const": "create_webhook",
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-is-trigger": False,
            "x-display-name": "Create Webhook",
        },
        title="Create Webhook",
    )
    url: LumaWebhookUrl = Field(..., title="URL", description="The absolute HTTP or HTTPS endpoint URL Luma will POST events to")
    event_types: str = Field(
        "*",
        title="Event Types",
        description="Comma-separated event types to subscribe to, or * for all (e.g. event.created, guest.registered)",
    )


# ============================================================================
# Webhook Trigger Config
# ============================================================================


class LumaWebhookTriggerConfig(BaseModel):
    """Fire the workflow when a Luma event, guest, or ticket changes."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["on_luma_event"] = Field(
        "on_luma_event",
        json_schema_extra={
            "const": "on_luma_event",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Luma Event",
        },
        title="On Luma Event",
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="Luma posts events here. Registered automatically when you connect credentials.",
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
    relay_connected: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    is_production: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    trigger_registered: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    trigger_error: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})


# ============================================================================
# Discriminated Union
# ============================================================================


LumaConfig = Annotated[
    Union[
        LumaGetSelfConfig,
        LumaListEventsConfig,
        LumaGetEventConfig,
        LumaCreateEventConfig,
        LumaUpdateEventConfig,
        LumaCancelEventConfig,
        LumaLookupEventConfig,
        LumaListGuestsConfig,
        LumaGetGuestConfig,
        LumaAddGuestsConfig,
        LumaUpdateGuestStatusConfig,
        LumaSendInvitesConfig,
        LumaAddHostConfig,
        LumaUpdateHostConfig,
        LumaRemoveHostConfig,
        LumaListTicketTypesConfig,
        LumaCreateTicketTypeConfig,
        LumaUpdateTicketTypeConfig,
        LumaCreateEventCouponConfig,
        LumaListEventCouponsConfig,
        LumaCreateCalendarCouponConfig,
        LumaListCalendarCouponsConfig,
        LumaGetCalendarConfig,
        LumaUpdateCalendarConfig,
        LumaListCalendarAdminsConfig,
        LumaListContactsConfig,
        LumaImportContactsConfig,
        LumaCreateEventTagConfig,
        LumaListWebhooksConfig,
        LumaCreateWebhookConfig,
        LumaWebhookTriggerConfig,
    ],
    Discriminator("operation"),
]


class LumaNodeConfig(NodeConfig[LumaConfig, LumaCredential]):
    """Full configuration for the Luma node including credentials."""

    pass


# ============================================================================
# Helpers
# ============================================================================


def _comma_list(value: Optional[str]) -> Optional[List[str]]:
    if not value:
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return parts or None


def _maybe_int(value: Optional[str]) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coupon_discount(discount_type: str, value: str, currency: str) -> Dict[str, Any]:
    amount = float(value)
    if discount_type == "percent":
        if not 0 <= amount <= 100:
            raise ValueError("Percentage discount must be between 0 and 100")
        return {"discount_type": "percent", "percent_off": amount}
    if discount_type == "amount":
        if amount < 0:
            raise ValueError("Amount discount must be nonnegative")
        return {"discount_type": "amount", "cents_off": amount, "currency": currency.lower()}
    raise ValueError("Discount type must be percent or amount")


async def _luma_request(
    api_key: str,
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated Luma request and return a structured result.

    The endpoint includes the version prefix (e.g. ``/v1/...`` or ``/v2/...``).
    """
    url = f"{LUMA_API_BASE}{endpoint}"
    headers = {
        "x-luma-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
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
                    if isinstance(err, dict):
                        message = err.get("message") or err.get("error") or str(err)
                    else:
                        message = str(err)
                except Exception:
                    message = response.text
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[LumaNode] API error ({action_name}): {message}")
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
            logger.error(f"[LumaNode] Request failed ({action_name}): {msg}")
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


class LumaNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """Luma (lu.ma) event-management automation node."""

    integration_type = "automation-luma"

    edit_examples = [
        "List all upcoming Luma events",
        "Create a Luma event for next Friday at 6pm",
        "Add a guest to a Luma event and send them an invite",
        "Approve a pending guest's registration",
        "Trigger a workflow whenever someone registers for a Luma event",
    ]

    @classmethod
    def get_config_model(cls):
        return LumaNodeConfig

    # ------------------------------------------------------------------
    # Dynamic options (events)
    # ------------------------------------------------------------------
    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        user_id: str,
        config_data: Dict[str, Any],
        credential_ids: Optional[Dict[str, str]] = None,
        pool=None,
    ) -> Dict[str, Any]:
        if field_name != "event_api_id":
            return {"options": []}
        from utils.credential_loader import load_credential

        credential_id = next((cid for cid in (credential_ids or {}).values() if cid), None)
        credential = await load_credential(pool, user_id, credential_id) if credential_id else None
        if not credential:
            return {"options": []}
        api_key = credential.get("api_key")
        result = await _luma_request(
            api_key, "GET", "/v1/calendars/events/list", action_name="list_events"
        )
        if result.get("status") != "success":
            return {"options": []}
        data = result.get("data") or {}
        entries = data.get("entries") if isinstance(data, dict) else None
        if entries is None:
            entries = data if isinstance(data, list) else []
        options = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            event = entry.get("event") if isinstance(entry.get("event"), dict) else entry
            event_id = event.get("api_id") or event.get("id")
            name = event.get("name") or f"Event {event_id}"
            if event_id:
                options.append({"label": str(name), "value": str(event_id)})
        return {"options": options}

    # ------------------------------------------------------------------
    # Webhook trigger registration
    # ------------------------------------------------------------------
    @classmethod
    async def _register_external_webhook(
        cls, *, webhook_url: str, credential: Dict[str, Any], config: Dict[str, Any], node_id: str
    ) -> Optional[Dict[str, Any]]:
        api_key = credential.get("api_key")
        if not api_key:
            raise ValueError("A Luma API key is required to register the trigger")
        secret = hashlib.sha256(f"{node_id}:{webhook_url}".encode()).hexdigest()[:32]
        result = await _luma_request(
            api_key,
            "POST",
            "/v2/webhooks/create",
            json_body={
                "url": webhook_url,
                "event_types": LUMA_TRIGGER_EVENT_TYPES,
            },
            action_name="register_webhook",
        )
        if result.get("status") != "success":
            raise ValueError(f"Luma webhook registration failed: {result.get('error')}")
        data = result.get("data") or {}
        external_id = None
        if isinstance(data, dict):
            external_id = data.get("api_id") or data.get("id") or (
                (data.get("webhook") or {}).get("api_id") if isinstance(data.get("webhook"), dict) else None
            )
        return {
            "external_webhook_id": str(external_id) if external_id else None,
            "signing_secret": secret,
        }

    @classmethod
    async def _unregister_external_webhook(
        cls, *, credential: Optional[Dict[str, Any]], config: Dict[str, Any], node_id: str
    ) -> None:
        external_id = (config or {}).get("external_webhook_id")
        api_key = (credential or {}).get("api_key")
        if not external_id or not api_key:
            return
        await _luma_request(
            api_key,
            "POST",
            "/v1/webhooks/delete",
            json_body={"api_id": external_id},
            action_name="unregister_webhook",
        )

    @classmethod
    def verify_webhook_signature(
        cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]
    ) -> bool:
        secret = (config or {}).get("signing_secret")
        if not secret:
            return True  # no secret stored — accept (trigger not yet armed)
        sent = headers.get("luma-signature") or headers.get("x-luma-signature")
        if not sent:
            return False
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, sent)

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, LumaNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        if isinstance(op, LumaWebhookTriggerConfig):
            return {
                "status": "success",
                "action": "on_luma_event",
                "data": {**inputs, "webhook_url": op.webhook_url},
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your Luma API key.")
        api_key = credentials.api_key

        handlers = {
            "get_self": self._get_self,
            "list_events": self._list_events,
            "get_event": self._get_event,
            "create_event": self._create_event,
            "update_event": self._update_event,
            "cancel_event": self._cancel_event,
            "lookup_event": self._lookup_event,
            "list_guests": self._list_guests,
            "get_guest": self._get_guest,
            "add_guests": self._add_guests,
            "update_guest_status": self._update_guest_status,
            "send_invites": self._send_invites,
            "add_host": self._add_host,
            "update_host": self._update_host,
            "remove_host": self._remove_host,
            "list_ticket_types": self._list_ticket_types,
            "create_ticket_type": self._create_ticket_type,
            "update_ticket_type": self._update_ticket_type,
            "create_event_coupon": self._create_event_coupon,
            "list_event_coupons": self._list_event_coupons,
            "create_calendar_coupon": self._create_calendar_coupon,
            "list_calendar_coupons": self._list_calendar_coupons,
            "get_calendar": self._get_calendar,
            "update_calendar": self._update_calendar,
            "list_calendar_admins": self._list_calendar_admins,
            "list_contacts": self._list_contacts,
            "import_contacts": self._import_contacts,
            "create_event_tag": self._create_event_tag,
            "list_webhooks": self._list_webhooks,
            "create_webhook": self._create_webhook,
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
    # Account handlers
    # ------------------------------------------------------------------
    async def _get_self(self, c: LumaGetSelfConfig, api_key: str) -> Dict[str, Any]:
        return await _luma_request(
            api_key, "GET", "/v1/users/get-self", action_name="get_self"
        )

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------
    async def _list_events(self, c: LumaListEventsConfig, api_key: str) -> Dict[str, Any]:
        params = {
            "after": c.after,
            "before": c.before,
            "pagination_cursor": c.pagination_cursor,
            "pagination_limit": c.pagination_limit,
        }
        return await _luma_request(
            api_key, "GET", "/v1/calendars/events/list", params=params, action_name="list_events"
        )

    async def _get_event(self, c: LumaGetEventConfig, api_key: str) -> Dict[str, Any]:
        return await _luma_request(
            api_key, "GET", "/v1/events/get", params={"event_id": c.event_api_id},
            action_name="get_event",
        )

    async def _create_event(self, c: LumaCreateEventConfig, api_key: str) -> Dict[str, Any]:
        body = {
            "name": c.name,
            "start_at": c.start_at,
            "end_at": c.end_at,
            "timezone": c.timezone,
            "ticket_types": [{
                "name": "Standard",
                "type": "free",
                "require_approval": c.require_rsvp_approval == "true",
            }],
        }
        return await _luma_request(
            api_key, "POST", "/v1/events/create", json_body=body, action_name="create_event"
        )

    async def _update_event(self, c: LumaUpdateEventConfig, api_key: str) -> Dict[str, Any]:
        body = {
            "event_id": c.event_api_id,
            "name": c.name,
            "start_at": c.start_at,
            "end_at": c.end_at,
            "timezone": c.timezone,
        }
        return await _luma_request(
            api_key, "POST", "/v1/events/update", json_body=body, action_name="update_event"
        )

    async def _cancel_event(self, c: LumaCancelEventConfig, api_key: str) -> Dict[str, Any]:
        body = {
            "event_id": c.event_api_id,
            "cancellation_token": c.cancellation_token,
        }
        return await _luma_request(
            api_key, "POST", "/v1/events/cancel", json_body=body, action_name="cancel_event"
        )

    async def _lookup_event(self, c: LumaLookupEventConfig, api_key: str) -> Dict[str, Any]:
        params = {"platform": c.platform, "url": c.url}
        return await _luma_request(
            api_key, "GET", "/v1/calendars/events/lookup", params=params, action_name="lookup_event"
        )

    # ------------------------------------------------------------------
    # Guest handlers
    # ------------------------------------------------------------------
    async def _list_guests(self, c: LumaListGuestsConfig, api_key: str) -> Dict[str, Any]:
        params = {
            "event_id": c.event_api_id,
            "approval_status": c.approval_status or None,
            "pagination_cursor": c.pagination_cursor,
            "pagination_limit": c.pagination_limit,
        }
        return await _luma_request(
            api_key, "GET", "/v1/events/guests/list", params=params, action_name="list_guests"
        )

    async def _get_guest(self, c: LumaGetGuestConfig, api_key: str) -> Dict[str, Any]:
        params = {
            "event_id": c.event_api_id,
            "id": c.api_id or c.email,
        }
        return await _luma_request(
            api_key, "GET", "/v1/events/guests/get", params=params, action_name="get_guest"
        )

    async def _add_guests(self, c: LumaAddGuestsConfig, api_key: str) -> Dict[str, Any]:
        guests = [{"email": e} for e in (_comma_list(c.emails) or [])]
        body = {"event_id": c.event_api_id, "guests": guests}
        return await _luma_request(
            api_key, "POST", "/v1/events/guests/add", json_body=body, action_name="add_guests"
        )

    async def _update_guest_status(
        self, c: LumaUpdateGuestStatusConfig, api_key: str
    ) -> Dict[str, Any]:
        body = {
            "event_id": c.event_api_id,
            "guest_id": c.guest_api_id,
            "status": c.status,
        }
        return await _luma_request(
            api_key, "POST", "/v1/events/guests/update-status", json_body=body,
            action_name="update_guest_status",
        )

    async def _send_invites(self, c: LumaSendInvitesConfig, api_key: str) -> Dict[str, Any]:
        body = {
            "event_id": c.event_api_id,
            "guests": [{"email": e} for e in (_comma_list(c.emails) or [])],
        }
        return await _luma_request(
            api_key, "POST", "/v1/events/guests/send-invites", json_body=body,
            action_name="send_invites",
        )

    # ------------------------------------------------------------------
    # Host handlers
    # ------------------------------------------------------------------
    async def _add_host(self, c: LumaAddHostConfig, api_key: str) -> Dict[str, Any]:
        body = {
            "event_id": c.event_api_id,
            "email": c.email,
            "access_level": c.access_level or None,
        }
        return await _luma_request(
            api_key, "POST", "/v1/events/hosts/add", json_body=body, action_name="add_host"
        )

    async def _update_host(self, c: LumaUpdateHostConfig, api_key: str) -> Dict[str, Any]:
        body = {
            "event_id": c.event_api_id,
            "email": c.email,
            "access_level": c.access_level or None,
        }
        return await _luma_request(
            api_key, "POST", "/v1/events/hosts/update", json_body=body, action_name="update_host"
        )

    async def _remove_host(self, c: LumaRemoveHostConfig, api_key: str) -> Dict[str, Any]:
        body = {"event_id": c.event_api_id, "email": c.email}
        return await _luma_request(
            api_key, "POST", "/v1/events/hosts/remove", json_body=body, action_name="remove_host"
        )

    # ------------------------------------------------------------------
    # Ticket type handlers
    # ------------------------------------------------------------------
    async def _list_ticket_types(
        self, c: LumaListTicketTypesConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _luma_request(
            api_key, "GET", "/v1/events/ticket-types/list",
            params={"event_id": c.event_api_id}, action_name="list_ticket_types",
        )

    async def _create_ticket_type(
        self, c: LumaCreateTicketTypeConfig, api_key: str
    ) -> Dict[str, Any]:
        body = {
            "event_id": c.event_api_id,
            "name": c.name,
            "type": "paid" if c.cents not in (None, "") else "free",
            "cents": _maybe_int(c.cents),
            "currency": c.currency.lower() if c.currency else None,
            "max_capacity": _maybe_int(c.max_capacity),
        }
        return await _luma_request(
            api_key, "POST", "/v1/events/ticket-types/create", json_body=body,
            action_name="create_ticket_type",
        )

    async def _update_ticket_type(
        self, c: LumaUpdateTicketTypeConfig, api_key: str
    ) -> Dict[str, Any]:
        body = {
            "event_ticket_type_id": c.ticket_type_api_id,
            "name": c.name,
            "cents": _maybe_int(c.cents),
            "max_capacity": _maybe_int(c.max_capacity),
        }
        return await _luma_request(
            api_key, "POST", "/v1/events/ticket-types/update", json_body=body,
            action_name="update_ticket_type",
        )

    # ------------------------------------------------------------------
    # Coupon handlers
    # ------------------------------------------------------------------
    async def _create_event_coupon(
        self, c: LumaCreateEventCouponConfig, api_key: str
    ) -> Dict[str, Any]:
        body = {
            "event_id": c.event_api_id,
            "code": c.code,
            "discount": _coupon_discount(c.discount_type, c.discount_value, c.currency),
        }
        return await _luma_request(
            api_key, "POST", "/v1/events/coupons/create", json_body=body,
            action_name="create_event_coupon",
        )

    async def _list_event_coupons(
        self, c: LumaListEventCouponsConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _luma_request(
            api_key, "GET", "/v1/events/coupons/list",
            params={"event_id": c.event_api_id}, action_name="list_event_coupons",
        )

    async def _create_calendar_coupon(
        self, c: LumaCreateCalendarCouponConfig, api_key: str
    ) -> Dict[str, Any]:
        body = {
            "code": c.code,
            "discount": _coupon_discount(c.discount_type, c.discount_value, c.currency),
        }
        return await _luma_request(
            api_key, "POST", "/v1/calendars/coupons/create", json_body=body,
            action_name="create_calendar_coupon",
        )

    async def _list_calendar_coupons(
        self, c: LumaListCalendarCouponsConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _luma_request(
            api_key, "GET", "/v1/calendars/coupons/list", action_name="list_calendar_coupons"
        )

    # ------------------------------------------------------------------
    # Calendar handlers
    # ------------------------------------------------------------------
    async def _get_calendar(self, c: LumaGetCalendarConfig, api_key: str) -> Dict[str, Any]:
        return await _luma_request(
            api_key, "GET", "/v1/calendars/get", action_name="get_calendar"
        )

    async def _update_calendar(self, c: LumaUpdateCalendarConfig, api_key: str) -> Dict[str, Any]:
        body = {"calendar_id": c.calendar_id, "name": c.name, "description": c.description}
        return await _luma_request(
            api_key, "POST", "/v1/calendars/update", json_body=body, action_name="update_calendar"
        )

    async def _list_calendar_admins(
        self, c: LumaListCalendarAdminsConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _luma_request(
            api_key, "GET", "/v1/calendars/admins/list", action_name="list_calendar_admins"
        )

    async def _list_contacts(self, c: LumaListContactsConfig, api_key: str) -> Dict[str, Any]:
        params = {
            "pagination_cursor": c.pagination_cursor,
            "pagination_limit": c.pagination_limit,
        }
        return await _luma_request(
            api_key, "GET", "/v1/calendars/contacts/list", params=params, action_name="list_contacts"
        )

    async def _import_contacts(self, c: LumaImportContactsConfig, api_key: str) -> Dict[str, Any]:
        body = {"contacts": [{"email": e} for e in (_comma_list(c.emails) or [])]}
        return await _luma_request(
            api_key, "POST", "/v1/calendars/contacts/import", json_body=body,
            action_name="import_contacts",
        )

    async def _create_event_tag(self, c: LumaCreateEventTagConfig, api_key: str) -> Dict[str, Any]:
        return await _luma_request(
            api_key, "POST", "/v1/calendars/event-tags/create", json_body={"name": c.name},
            action_name="create_event_tag",
        )

    # ------------------------------------------------------------------
    # Webhook handlers
    # ------------------------------------------------------------------
    async def _list_webhooks(self, c: LumaListWebhooksConfig, api_key: str) -> Dict[str, Any]:
        return await _luma_request(
            api_key, "GET", "/v1/webhooks/list", action_name="list_webhooks"
        )

    async def _create_webhook(self, c: LumaCreateWebhookConfig, api_key: str) -> Dict[str, Any]:
        event_types = _comma_list(c.event_types) or ["*"]
        body = {"url": c.url, "event_types": event_types}
        return await _luma_request(
            api_key, "POST", "/v2/webhooks/create", json_body=body, action_name="create_webhook"
        )
