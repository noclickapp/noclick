"""
Cal.com scheduling automation node.

Provides workflow integration with Cal.com (v2 REST API) for operations including:
- Bookings: list, get, create, cancel, reschedule
- Event Types: list, get
- Availability: get available slots
- Schedules: list
- Profile: get current user
- Webhook Trigger: fire on user-selected Cal.com events (booking created /
  rescheduled / cancelled / requested / paid, meeting started / ended, recording
  ready, form submitted, and more — or all events)

Authentication: API Key (Bearer token)
API Base URL: https://api.cal.com/v2
Documentation: https://cal.com/docs/api-reference/v2/introduction

Every v2 request requires a `cal-api-version` header that pins the endpoint
contract to a dated version; the date differs per endpoint family, so each
handler passes the version its endpoint expects.
"""

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
from nodes.scopes.scheduling import CAL_COM_SCOPES

logger = logging.getLogger(__name__)

CALCOM_API_BASE = "https://api.cal.com/v2"

# Per-endpoint-family cal-api-version dates (Cal.com pins each family separately).
API_VERSION_BOOKINGS = "2024-08-13"
API_VERSION_BOOKING_ACTIONS = "2026-02-25"  # confirm/decline/mark-absent/recordings
API_VERSION_SLOTS = "2024-09-04"
API_VERSION_EVENT_TYPES = "2024-06-14"
API_VERSION_SCHEDULES = "2024-06-11"
API_VERSION_WEBHOOKS = "2024-06-11"
API_VERSION_DEFAULT = "2024-08-13"

# Cal.com webhook trigger event types the node exposes for selection.
# Identifiers are the exact strings Cal.com sends in the `triggerEvent` field of
# the webhook payload and accepts in the `triggers` array of POST /webhooks.
# See https://cal.com/docs/developing/guides/automation/webhooks
CALCOM_TRIGGER_EVENTS: List[str] = [
    "BOOKING_CREATED",
    "BOOKING_RESCHEDULED",
    "BOOKING_CANCELLED",
    "BOOKING_REQUESTED",
    "BOOKING_REJECTED",
    "BOOKING_PAYMENT_INITIATED",
    "BOOKING_PAID",
    "BOOKING_NO_SHOW_UPDATED",
    "MEETING_STARTED",
    "MEETING_ENDED",
    "RECORDING_READY",
    "RECORDING_TRANSCRIPTION_GENERATED",
    "INSTANT_MEETING",
    "FORM_SUBMITTED",
    "FORM_SUBMITTED_NO_EVENT",
    "OOO_CREATED",
]

# Human-readable labels shown in the event-type dropdown (parallel to the list above).
CALCOM_TRIGGER_EVENT_LABELS: List[str] = [
    "Booking created",
    "Booking rescheduled",
    "Booking cancelled",
    "Booking requested (needs confirmation)",
    "Booking rejected",
    "Booking payment initiated",
    "Booking paid",
    "Booking no-show updated",
    "Meeting started",
    "Meeting ended",
    "Recording ready",
    "Recording transcription generated",
    "Instant meeting",
    "Form submitted",
    "Form submitted (no booking)",
    "Out-of-office created",
]

# Sentinel that subscribes to every event Cal.com can deliver.
CALCOM_ALL_EVENTS = "*"


# ============================================================================
# Credential Schema
# ============================================================================


class CalComOAuthCredential(BaseModel):
    """OAuth 2.0 credential for Cal.com.

    Tokens are obtained via the OAuth flow, not entered manually. Cal.com access
    tokens expire after 30 minutes and are refreshed via the stored refresh
    token. The access token is a drop-in Bearer replacement for the API key.

    Create an OAuth client at: https://app.cal.com/settings/developer/oauth-clients
    """

    credential_type: Literal["cal_com_oauth"] = Field(
        "cal_com_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(..., title="Access Token")
    refresh_token: Optional[str] = Field(None, title="Refresh Token")
    expires_at: Optional[str] = Field(None, title="Token Expiry")  # ISO 8601
    name: Optional[str] = Field(None, title="User Name")
    email: Optional[str] = Field(None, title="Account Email")

    model_config = ConfigDict(json_schema_extra={
        "x-credential-type": "oauth",
        "x-oauth-provider": "calcom",
        "x-oauth-scopes": [
            "BOOKING_READ",
            "BOOKING_WRITE",
            "EVENT_TYPE_READ",
            "EVENT_TYPE_WRITE",
            "SCHEDULE_READ",
            "SCHEDULE_WRITE",
            "PROFILE_READ",
            "PROFILE_WRITE",
            "WEBHOOK_READ",
            "WEBHOOK_WRITE",
        ],
    })


class CalComApiKeyCredential(BaseModel):
    """API Key credential for Cal.com."""

    credential_type: Literal["cal_com_api_key"] = Field(
        "cal_com_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description="Your Cal.com API key (starts with cal_) from Settings -> Developer -> API Keys",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={"x-credential-url": "https://app.cal.com/settings/developer/api-keys"}
    )


# Union type - OAuth shown first in UI (best UX), API key as alternative.
CalComCredential = Union[CalComOAuthCredential, CalComApiKeyCredential]


def _credential_bearer_token(credential: Any) -> Optional[str]:
    """Resolve the Bearer token from a Cal.com credential (model or dict).

    OAuth access tokens and API keys are both sent as ``Authorization: Bearer``
    on v2 endpoints, so callers treat them uniformly.
    """
    if credential is None:
        return None
    if isinstance(credential, dict):
        return credential.get("access_token") or credential.get("api_key")
    return getattr(credential, "access_token", None) or getattr(credential, "api_key", None)


# ============================================================================
# Operation Configs
# ============================================================================


class CalComListBookingsConfig(BaseModel):
    """List bookings, optionally filtered by status, attendee, or date range."""

    operation: Literal["list_bookings"] = Field(
        "list_bookings",
        json_schema_extra={
            "const": "list_bookings",
            "ui:hidden": True,
            "x-category": "Bookings",
            "x-is-trigger": False,
            "x-display-name": "List Bookings",
        },
        title="List Bookings",
    )
    status: Optional[str] = Field(
        None,
        title="Status",
        description="Filter by status",
        json_schema_extra={
            "enum": ["", "upcoming", "recurring", "past", "cancelled", "unconfirmed"],
            "enumNames": ["Any", "Upcoming", "Recurring", "Past", "Cancelled", "Unconfirmed"],
            "x-enum-searchable": True,
        },
    )
    attendee_email: Optional[str] = Field(
        None, title="Attendee Email", description="Filter to bookings with this attendee email"
    )
    after_start: Optional[str] = Field(
        None,
        title="Starts After",
        description="Lower bound for booking start. ISO 8601 / RFC 3339: YYYY-MM-DDTHH:MM:SSZ (Z = UTC), e.g. 2026-07-01T00:00:00Z",
        json_schema_extra={"ui:widget": "datetime", "ui:placeholder": "2026-07-01T00:00:00Z"},
    )
    before_end: Optional[str] = Field(
        None,
        title="Ends Before",
        description="Upper bound for booking end. ISO 8601 / RFC 3339: YYYY-MM-DDTHH:MM:SSZ (Z = UTC), e.g. 2026-07-08T00:00:00Z",
        json_schema_extra={"ui:widget": "datetime", "ui:placeholder": "2026-07-08T00:00:00Z"},
    )
    take: Optional[str] = Field(
        "50", title="Limit", description="Max number of bookings to return (1-100)"
    )


class CalComGetBookingConfig(BaseModel):
    """Retrieve a single booking by its UID."""

    operation: Literal["get_booking"] = Field(
        "get_booking",
        json_schema_extra={
            "const": "get_booking",
            "ui:hidden": True,
            "x-category": "Bookings",
            "x-is-trigger": False,
            "x-display-name": "Get Booking",
        },
        title="Get Booking",
    )
    booking_uid: str = Field(
        ..., title="Booking UID", description="The UID of the booking to retrieve"
    )


class CalComCreateBookingConfig(BaseModel):
    """Book a slot for an event type."""

    operation: Literal["create_booking"] = Field(
        "create_booking",
        json_schema_extra={
            "const": "create_booking",
            "ui:hidden": True,
            "x-category": "Bookings",
            "x-is-trigger": False,
            "x-display-name": "Create Booking",
        },
        title="Create Booking",
    )
    event_type_id: str = Field(
        ...,
        title="Event Type",
        description="The event type to book",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "event_type_id",
                "placeholder": "Select an event type...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste event type ID",
            },
            "x-resource-type": "cal_com_event_type",
        },
    )
    start: str = Field(
        ...,
        title="Start Time",
        description="Booking start time. ISO 8601 / RFC 3339: YYYY-MM-DDTHH:MM:SSZ (Z = UTC), e.g. 2026-07-01T10:00:00Z",
        json_schema_extra={"ui:widget": "datetime", "ui:placeholder": "2026-07-01T10:00:00Z"},
    )
    attendee_name: str = Field(..., title="Attendee Name", description="Name of the attendee")
    attendee_email: str = Field(..., title="Attendee Email", description="Email of the attendee")
    attendee_timezone: str = Field(
        "UTC", title="Attendee Timezone", description="IANA timezone (e.g. America/New_York)"
    )
    guests: Optional[str] = Field(
        None, title="Guests", description="Additional guest emails, comma-separated"
    )
    notes: Optional[str] = Field(
        None,
        title="Notes",
        description="Booking notes / additional information",
        json_schema_extra={"ui:widget": "textarea"},
    )


class CalComCancelBookingConfig(BaseModel):
    """Cancel an existing booking."""

    operation: Literal["cancel_booking"] = Field(
        "cancel_booking",
        json_schema_extra={
            "const": "cancel_booking",
            "ui:hidden": True,
            "x-category": "Bookings",
            "x-is-trigger": False,
            "x-display-name": "Cancel Booking",
        },
        title="Cancel Booking",
    )
    booking_uid: str = Field(..., title="Booking UID", description="UID of the booking to cancel")
    cancellation_reason: Optional[str] = Field(
        None, title="Reason", description="Optional cancellation reason"
    )


class CalComRescheduleBookingConfig(BaseModel):
    """Reschedule a booking to a new start time."""

    operation: Literal["reschedule_booking"] = Field(
        "reschedule_booking",
        json_schema_extra={
            "const": "reschedule_booking",
            "ui:hidden": True,
            "x-category": "Bookings",
            "x-is-trigger": False,
            "x-display-name": "Reschedule Booking",
        },
        title="Reschedule Booking",
    )
    booking_uid: str = Field(
        ..., title="Booking UID", description="UID of the booking to reschedule"
    )
    start: str = Field(
        ...,
        title="New Start Time",
        description="New start time. ISO 8601 / RFC 3339: YYYY-MM-DDTHH:MM:SSZ (Z = UTC), e.g. 2026-07-01T10:00:00Z",
        json_schema_extra={"ui:widget": "datetime", "ui:placeholder": "2026-07-01T10:00:00Z"},
    )
    reschedule_reason: Optional[str] = Field(
        None, title="Reason", description="Optional reschedule reason"
    )


class CalComListEventTypesConfig(BaseModel):
    """List event types for the authenticated user."""

    operation: Literal["list_event_types"] = Field(
        "list_event_types",
        json_schema_extra={
            "const": "list_event_types",
            "ui:hidden": True,
            "x-category": "Event Types",
            "x-is-trigger": False,
            "x-display-name": "List Event Types",
        },
        title="List Event Types",
    )
    username: Optional[str] = Field(
        None, title="Username", description="Filter to a specific Cal.com username (optional)"
    )


class CalComGetEventTypeConfig(BaseModel):
    """Retrieve a single event type by ID."""

    operation: Literal["get_event_type"] = Field(
        "get_event_type",
        json_schema_extra={
            "const": "get_event_type",
            "ui:hidden": True,
            "x-category": "Event Types",
            "x-is-trigger": False,
            "x-display-name": "Get Event Type",
        },
        title="Get Event Type",
    )
    event_type_id: str = Field(
        ...,
        title="Event Type",
        description="The event type to retrieve",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "event_type_id",
                "placeholder": "Select an event type...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste event type ID",
            },
            "x-resource-type": "cal_com_event_type",
        },
    )


class CalComGetSlotsConfig(BaseModel):
    """Get available booking slots for an event type within a date range."""

    operation: Literal["get_slots"] = Field(
        "get_slots",
        json_schema_extra={
            "const": "get_slots",
            "ui:hidden": True,
            "x-category": "Availability",
            "x-is-trigger": False,
            "x-display-name": "Get Available Slots",
        },
        title="Get Available Slots",
    )
    event_type_id: str = Field(
        ...,
        title="Event Type",
        description="The event type to check availability for",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "event_type_id",
                "placeholder": "Select an event type...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste event type ID",
            },
            "x-resource-type": "cal_com_event_type",
        },
    )
    start: str = Field(
        ...,
        title="Range Start",
        description="Start of the availability window. ISO 8601 / RFC 3339: YYYY-MM-DDTHH:MM:SSZ (Z = UTC), e.g. 2026-07-01T00:00:00Z",
        json_schema_extra={"ui:widget": "datetime", "ui:placeholder": "2026-07-01T00:00:00Z"},
    )
    end: str = Field(
        ...,
        title="Range End",
        description="End of the availability window. ISO 8601 / RFC 3339: YYYY-MM-DDTHH:MM:SSZ (Z = UTC), e.g. 2026-07-08T00:00:00Z",
        json_schema_extra={"ui:widget": "datetime", "ui:placeholder": "2026-07-08T00:00:00Z"},
    )
    timezone: str = Field(
        "UTC",
        title="Timezone",
        description="IANA timezone for the returned slots, e.g. UTC or America/New_York",
        json_schema_extra={"ui:placeholder": "UTC"},
    )


class CalComListSchedulesConfig(BaseModel):
    """List availability schedules for the authenticated user."""

    operation: Literal["list_schedules"] = Field(
        "list_schedules",
        json_schema_extra={
            "const": "list_schedules",
            "ui:hidden": True,
            "x-category": "Schedules",
            "x-is-trigger": False,
            "x-display-name": "List Schedules",
        },
        title="List Schedules",
    )


class CalComGetMeConfig(BaseModel):
    """Retrieve the authenticated user's profile."""

    operation: Literal["get_me"] = Field(
        "get_me",
        json_schema_extra={
            "const": "get_me",
            "ui:hidden": True,
            "x-category": "Profile",
            "x-is-trigger": False,
            "x-display-name": "Get My Profile",
        },
        title="Get My Profile",
    )


# --- Booking actions (cal-api-version 2026-02-25) ---------------------------


class CalComConfirmBookingConfig(BaseModel):
    """Confirm a booking that requires host confirmation."""

    operation: Literal["confirm_booking"] = Field(
        "confirm_booking",
        json_schema_extra={"const": "confirm_booking", "ui:hidden": True, "x-category": "Bookings",
                           "x-is-trigger": False, "x-display-name": "Confirm Booking"},
        title="Confirm Booking",
    )
    booking_uid: str = Field(..., title="Booking UID", description="UID of the booking to confirm")


class CalComDeclineBookingConfig(BaseModel):
    """Decline a booking that requires host confirmation."""

    operation: Literal["decline_booking"] = Field(
        "decline_booking",
        json_schema_extra={"const": "decline_booking", "ui:hidden": True, "x-category": "Bookings",
                           "x-is-trigger": False, "x-display-name": "Decline Booking"},
        title="Decline Booking",
    )
    booking_uid: str = Field(..., title="Booking UID", description="UID of the booking to decline")
    reason: Optional[str] = Field(None, title="Reason", description="Optional reason for declining")


class CalComMarkNoShowConfig(BaseModel):
    """Mark the host and/or attendees as absent (no-show) for a booking."""

    operation: Literal["mark_no_show"] = Field(
        "mark_no_show",
        json_schema_extra={"const": "mark_no_show", "ui:hidden": True, "x-category": "Bookings",
                           "x-is-trigger": False, "x-display-name": "Mark No-Show"},
        title="Mark No-Show",
    )
    booking_uid: str = Field(..., title="Booking UID", description="UID of the booking")
    host_absent: Optional[str] = Field(
        "false", title="Host Absent", description="Mark the host as absent",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    attendees_json: Optional[str] = Field(
        None, title="Attendees (JSON)",
        description='Optional JSON array marking attendees absent, e.g. [{"email":"a@x.com","absent":true}]',
        json_schema_extra={"ui:widget": "textarea"},
    )


class CalComGetRecordingsConfig(BaseModel):
    """Get the Cal Video recordings for a booking."""

    operation: Literal["get_recordings"] = Field(
        "get_recordings",
        json_schema_extra={"const": "get_recordings", "ui:hidden": True, "x-category": "Bookings",
                           "x-is-trigger": False, "x-display-name": "Get Recordings"},
        title="Get Recordings",
    )
    booking_uid: str = Field(..., title="Booking UID", description="UID of the booking")


# --- Event type writes ------------------------------------------------------


class CalComCreateEventTypeConfig(BaseModel):
    """Create a new event type."""

    operation: Literal["create_event_type"] = Field(
        "create_event_type",
        json_schema_extra={"const": "create_event_type", "ui:hidden": True, "x-category": "Event Types",
                           "x-is-trigger": False, "x-display-name": "Create Event Type",
                           "x-creates-resource": True, "x-resource-type": "cal_com_event_type",
                           "x-resource-id-path": "data.id"},
        title="Create Event Type",
    )
    title: str = Field(..., title="Title", description="Event type title")
    slug: str = Field(..., title="Slug", description="URL slug (e.g. 30min)")
    length_minutes: str = Field(..., title="Length (minutes)", description="Duration in minutes",
                                json_schema_extra={"ui:placeholder": "30"})
    description: Optional[str] = Field(None, title="Description", json_schema_extra={"ui:widget": "textarea"})
    advanced_json: Optional[str] = Field(
        None, title="Advanced Options (JSON)",
        description='Optional JSON object merged into the request, e.g. {"locations":[{"type":"integration","integration":"cal-video"}],"hidden":false}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class CalComUpdateEventTypeConfig(BaseModel):
    """Update an existing event type (only the fields you set change)."""

    operation: Literal["update_event_type"] = Field(
        "update_event_type",
        json_schema_extra={"const": "update_event_type", "ui:hidden": True, "x-category": "Event Types",
                           "x-is-trigger": False, "x-display-name": "Update Event Type"},
        title="Update Event Type",
    )
    event_type_id: str = Field(
        ..., title="Event Type", description="The event type to update",
        json_schema_extra={"x-dynamic-options": {"field_name": "event_type_id", "placeholder": "Select an event type...",
                                                  "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste event type ID"},
                           "x-resource-type": "cal_com_event_type"},
    )
    title: Optional[str] = Field(None, title="Title")
    slug: Optional[str] = Field(None, title="Slug")
    length_minutes: Optional[str] = Field(None, title="Length (minutes)")
    description: Optional[str] = Field(None, title="Description", json_schema_extra={"ui:widget": "textarea"})
    hidden: Optional[str] = Field(
        None, title="Hidden", description="Hide this event type from your booking page",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    advanced_json: Optional[str] = Field(
        None, title="Advanced Options (JSON)", description="Optional JSON object merged into the update request",
        json_schema_extra={"ui:widget": "textarea"},
    )


class CalComDeleteEventTypeConfig(BaseModel):
    """Delete an event type."""

    operation: Literal["delete_event_type"] = Field(
        "delete_event_type",
        json_schema_extra={"const": "delete_event_type", "ui:hidden": True, "x-category": "Event Types",
                           "x-is-trigger": False, "x-display-name": "Delete Event Type"},
        title="Delete Event Type",
    )
    event_type_id: str = Field(
        ..., title="Event Type", description="The event type to delete",
        json_schema_extra={"x-dynamic-options": {"field_name": "event_type_id", "placeholder": "Select an event type...",
                                                  "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste event type ID"},
                           "x-resource-type": "cal_com_event_type"},
    )


# --- Schedule reads & writes ------------------------------------------------


class CalComGetScheduleConfig(BaseModel):
    """Retrieve a single availability schedule by ID."""

    operation: Literal["get_schedule"] = Field(
        "get_schedule",
        json_schema_extra={"const": "get_schedule", "ui:hidden": True, "x-category": "Schedules",
                           "x-is-trigger": False, "x-display-name": "Get Schedule"},
        title="Get Schedule",
    )
    schedule_id: str = Field(..., title="Schedule ID", description="The schedule to retrieve")


class CalComCreateScheduleConfig(BaseModel):
    """Create an availability schedule."""

    operation: Literal["create_schedule"] = Field(
        "create_schedule",
        json_schema_extra={"const": "create_schedule", "ui:hidden": True, "x-category": "Schedules",
                           "x-is-trigger": False, "x-display-name": "Create Schedule"},
        title="Create Schedule",
    )
    name: str = Field(..., title="Name", description="Schedule name")
    timezone: str = Field("UTC", title="Timezone", description="IANA timezone, e.g. America/New_York")
    is_default: str = Field(
        "false", title="Set as Default", description="Make this the default schedule",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    availability_json: str = Field(
        ..., title="Availability (JSON)",
        description='JSON array of weekly availability, e.g. [{"days":["Monday","Tuesday"],"startTime":"09:00","endTime":"17:00"}]',
        json_schema_extra={"ui:widget": "textarea"},
    )
    overrides_json: Optional[str] = Field(
        None, title="Date Overrides (JSON)",
        description='Optional JSON array, e.g. [{"date":"2026-12-25","startTime":"00:00","endTime":"00:00"}]',
        json_schema_extra={"ui:widget": "textarea"},
    )


class CalComUpdateScheduleConfig(BaseModel):
    """Update an availability schedule (only the fields you set change)."""

    operation: Literal["update_schedule"] = Field(
        "update_schedule",
        json_schema_extra={"const": "update_schedule", "ui:hidden": True, "x-category": "Schedules",
                           "x-is-trigger": False, "x-display-name": "Update Schedule"},
        title="Update Schedule",
    )
    schedule_id: str = Field(..., title="Schedule ID", description="The schedule to update")
    name: Optional[str] = Field(None, title="Name")
    timezone: Optional[str] = Field(None, title="Timezone", description="IANA timezone")
    is_default: Optional[str] = Field(
        None, title="Set as Default",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    availability_json: Optional[str] = Field(
        None, title="Availability (JSON)", description="Optional JSON array (replaces weekly availability)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    overrides_json: Optional[str] = Field(
        None, title="Date Overrides (JSON)", description="Optional JSON array of date overrides",
        json_schema_extra={"ui:widget": "textarea"},
    )


class CalComDeleteScheduleConfig(BaseModel):
    """Delete an availability schedule."""

    operation: Literal["delete_schedule"] = Field(
        "delete_schedule",
        json_schema_extra={"const": "delete_schedule", "ui:hidden": True, "x-category": "Schedules",
                           "x-is-trigger": False, "x-display-name": "Delete Schedule"},
        title="Delete Schedule",
    )
    schedule_id: str = Field(..., title="Schedule ID", description="The schedule to delete")


# --- Out of office (/v2/me/ooo) ---------------------------------------------


class CalComListOOOConfig(BaseModel):
    """List your out-of-office entries."""

    operation: Literal["list_ooo"] = Field(
        "list_ooo",
        json_schema_extra={"const": "list_ooo", "ui:hidden": True, "x-category": "Out of Office",
                           "x-is-trigger": False, "x-display-name": "List Out-of-Office"},
        title="List Out-of-Office",
    )
    take: Optional[str] = Field("50", title="Limit", description="Max entries to return")


class CalComCreateOOOConfig(BaseModel):
    """Create an out-of-office entry."""

    operation: Literal["create_ooo"] = Field(
        "create_ooo",
        json_schema_extra={"const": "create_ooo", "ui:hidden": True, "x-category": "Out of Office",
                           "x-is-trigger": False, "x-display-name": "Create Out-of-Office"},
        title="Create Out-of-Office",
    )
    start: str = Field(
        ..., title="Start", description="Start datetime. ISO 8601 UTC: YYYY-MM-DDTHH:MM:SSZ",
        json_schema_extra={"ui:widget": "datetime", "ui:placeholder": "2026-07-01T00:00:00Z"},
    )
    end: str = Field(
        ..., title="End", description="End datetime. ISO 8601 UTC: YYYY-MM-DDTHH:MM:SSZ",
        json_schema_extra={"ui:widget": "datetime", "ui:placeholder": "2026-07-08T00:00:00Z"},
    )
    reason: Optional[str] = Field(
        None, title="Reason",
        json_schema_extra={"enum": ["unspecified", "vacation", "travel", "sick", "public_holiday"],
                           "enumNames": ["Unspecified", "Vacation", "Travel", "Sick", "Public holiday"],
                           "x-enum-searchable": True},
    )
    notes: Optional[str] = Field(None, title="Notes", json_schema_extra={"ui:widget": "textarea"})
    to_user_id: Optional[str] = Field(None, title="Covering User ID", description="Optional user id covering for you")


class CalComDeleteOOOConfig(BaseModel):
    """Delete an out-of-office entry."""

    operation: Literal["delete_ooo"] = Field(
        "delete_ooo",
        json_schema_extra={"const": "delete_ooo", "ui:hidden": True, "x-category": "Out of Office",
                           "x-is-trigger": False, "x-display-name": "Delete Out-of-Office"},
        title="Delete Out-of-Office",
    )
    ooo_id: str = Field(..., title="Entry ID", description="The out-of-office entry id to delete")


# --- Profile write & utility ------------------------------------------------


class CalComUpdateMeConfig(BaseModel):
    """Update the authenticated user's profile (only the fields you set change)."""

    operation: Literal["update_me"] = Field(
        "update_me",
        json_schema_extra={"const": "update_me", "ui:hidden": True, "x-category": "Profile",
                           "x-is-trigger": False, "x-display-name": "Update My Profile"},
        title="Update My Profile",
    )
    name: Optional[str] = Field(None, title="Name")
    email: Optional[str] = Field(None, title="Email")
    timezone: Optional[str] = Field(None, title="Timezone", description="IANA timezone")
    bio: Optional[str] = Field(None, title="Bio", json_schema_extra={"ui:widget": "textarea"})
    advanced_json: Optional[str] = Field(
        None, title="Advanced Options (JSON)",
        description='Optional JSON object merged into the request, e.g. {"weekStart":"Monday","timeFormat":24}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class CalComListWebhooksConfig(BaseModel):
    """List the webhooks registered on your account."""

    operation: Literal["list_webhooks"] = Field(
        "list_webhooks",
        json_schema_extra={"const": "list_webhooks", "ui:hidden": True, "x-category": "Webhooks",
                           "x-is-trigger": False, "x-display-name": "List Webhooks"},
        title="List Webhooks",
    )
    take: Optional[str] = Field("50", title="Limit", description="Max webhooks to return (1-250)")


class CalComReserveSlotConfig(BaseModel):
    """Reserve (hold) a slot for an event type before confirming a booking."""

    operation: Literal["reserve_slot"] = Field(
        "reserve_slot",
        json_schema_extra={"const": "reserve_slot", "ui:hidden": True, "x-category": "Availability",
                           "x-is-trigger": False, "x-display-name": "Reserve Slot"},
        title="Reserve Slot",
    )
    event_type_id: str = Field(
        ..., title="Event Type", description="The event type to reserve a slot for",
        json_schema_extra={"x-dynamic-options": {"field_name": "event_type_id", "placeholder": "Select an event type...",
                                                  "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste event type ID"},
                           "x-resource-type": "cal_com_event_type"},
    )
    slot_start: str = Field(
        ..., title="Slot Start", description="Slot start datetime. ISO 8601 UTC: YYYY-MM-DDTHH:MM:SSZ",
        json_schema_extra={"ui:widget": "datetime", "ui:placeholder": "2026-07-01T10:00:00Z"},
    )
    reservation_duration: Optional[str] = Field(
        None, title="Hold Duration (minutes)", description="How long to hold the slot (default 5)",
    )


# ============================================================================
# Webhook Trigger Config
# ============================================================================


class CalComBookingTriggerConfig(BaseModel):
    """Fire the workflow when a Cal.com webhook event occurs.

    The ``event_types`` field selects which of Cal.com's webhook triggers fire
    this workflow. Cal.com delivers each subscribed event to the webhook URL and
    tags it with a ``triggerEvent`` field; only the selected events run the flow.
    """

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["on_booking_event"] = Field(
        "on_booking_event",
        json_schema_extra={
            "const": "on_booking_event",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Booking Event",
        },
        title="On Booking Event",
    )
    event_types: str = Field(
        CALCOM_ALL_EVENTS,
        title="Trigger Events",
        description=(
            "Which Cal.com event(s) fire this workflow. Choose 'All booking events' "
            "to fire on every event, or pick a specific one. To fire on several "
            "specific events, enter their identifiers comma-separated "
            "(e.g. BOOKING_CREATED,BOOKING_CANCELLED). "
            "Available events: "
            "BOOKING_CREATED (a booking is scheduled), "
            "BOOKING_RESCHEDULED (a booking is moved to a new time), "
            "BOOKING_CANCELLED (a booking is cancelled), "
            "BOOKING_REQUESTED (a booking needs host confirmation), "
            "BOOKING_REJECTED (the host declines a pending booking), "
            "BOOKING_PAYMENT_INITIATED (payment processing begins), "
            "BOOKING_PAID (payment completes), "
            "BOOKING_NO_SHOW_UPDATED (attendee no-show status changes), "
            "MEETING_STARTED (scheduled start time reached), "
            "MEETING_ENDED (scheduled end time reached), "
            "RECORDING_READY (a meeting recording is available), "
            "RECORDING_TRANSCRIPTION_GENERATED (a recording transcription completes), "
            "INSTANT_MEETING (an instant meeting is initiated), "
            "FORM_SUBMITTED (a routing form is completed), "
            "FORM_SUBMITTED_NO_EVENT (a form is submitted with no booking), "
            "OOO_CREATED (an out-of-office entry is created)."
        ),
        json_schema_extra={
            "enum": [CALCOM_ALL_EVENTS, *CALCOM_TRIGGER_EVENTS],
            "enumNames": ["All booking events", *CALCOM_TRIGGER_EVENT_LABELS],
            "x-enum-searchable": True,
        },
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="Cal.com posts booking events here. Registered automatically when you connect credentials.",
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


CalComConfig = Annotated[
    Union[
        CalComListBookingsConfig,
        CalComGetBookingConfig,
        CalComCreateBookingConfig,
        CalComCancelBookingConfig,
        CalComRescheduleBookingConfig,
        CalComListEventTypesConfig,
        CalComGetEventTypeConfig,
        CalComGetSlotsConfig,
        CalComListSchedulesConfig,
        CalComGetMeConfig,
        CalComConfirmBookingConfig,
        CalComDeclineBookingConfig,
        CalComMarkNoShowConfig,
        CalComGetRecordingsConfig,
        CalComCreateEventTypeConfig,
        CalComUpdateEventTypeConfig,
        CalComDeleteEventTypeConfig,
        CalComGetScheduleConfig,
        CalComCreateScheduleConfig,
        CalComUpdateScheduleConfig,
        CalComDeleteScheduleConfig,
        CalComListOOOConfig,
        CalComCreateOOOConfig,
        CalComDeleteOOOConfig,
        CalComUpdateMeConfig,
        CalComListWebhooksConfig,
        CalComReserveSlotConfig,
        CalComBookingTriggerConfig,
    ],
    Discriminator("operation"),
]


class CalComNodeConfig(NodeConfig[CalComConfig, CalComCredential]):
    """Full configuration for the Cal.com node including credentials."""

    pass


# ============================================================================
# Node Implementation
# ============================================================================


def _parse_json_field(value: Optional[str], field_label: str) -> Any:
    """Parse an optional JSON string config field (for complex array/object bodies
    like schedule availability or event-type booking fields). Returns None for
    empty input; raises ValueError with a clear message on malformed JSON."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str):
        return value
    import json
    try:
        return json.loads(value)
    except json.JSONDecodeError as e:
        raise ValueError(f"{field_label} must be valid JSON: {e}")


def _comma_list(value: Optional[str]) -> Optional[List[str]]:
    if not value:
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return parts or None


def _selected_trigger_events(config: Optional[Dict[str, Any]]) -> List[str]:
    """Resolve the trigger config's ``event_types`` field to the concrete list of
    Cal.com event identifiers to subscribe to. ``"*"``, empty, or an unrecognized
    value means all events (the safe default — never silently subscribe to none)."""
    raw = (config or {}).get("event_types")
    if not raw or raw == CALCOM_ALL_EVENTS:
        return list(CALCOM_TRIGGER_EVENTS)
    chosen = [e.strip().upper() for e in str(raw).split(",") if e.strip()]
    valid = [e for e in chosen if e in CALCOM_TRIGGER_EVENTS]
    return valid or list(CALCOM_TRIGGER_EVENTS)


async def _calcom_request(
    api_key: str,
    method: str,
    endpoint: str,
    api_version: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated Cal.com v2 request and return a structured result."""
    url = f"{CALCOM_API_BASE}{endpoint}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "cal-api-version": api_version,
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
                    message = err.get("error", {})
                    message = message.get("message") if isinstance(message, dict) else err.get("message", str(err))
                except Exception:
                    message = response.text
                logger.error(f"[CalComNode] API error ({action_name}): {message}")
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
                    payload = response.json()
                    # Cal.com v2 wraps results in {status, data}
                    data = payload.get("data", payload) if isinstance(payload, dict) else payload
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
            logger.error(f"[CalComNode] Request failed ({action_name}): {msg}")
            return {
                "status": "error",
                "action": action_name,
                "error": msg,
                "status_code": 500,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }


class CalComNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """Cal.com scheduling automation node."""

    edit_examples = [
        "List all upcoming bookings",
        "Create a booking for a discovery call event type",
        "Cancel a booking when a deal is lost",
        "Get available slots for next week",
        "Trigger a workflow whenever a new booking is created",
    ]

    scope_registry = CAL_COM_SCOPES
    connection_evidence = ConnectionEvidence(
        field="event_type_id",
        noun="event types",
    )
    @classmethod
    def get_config_model(cls):
        return CalComNodeConfig

    # ------------------------------------------------------------------
    # Dynamic options (event types)
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
        """Load dynamic options for the event_type_id dropdown.

        The dynamic-options handler loads + freshens the credential before
        calling, so we read the (already-fresh) Bearer token straight off
        ``credential_data`` — works for both OAuth and API-key credentials.
        """
        if field_name != "event_type_id":
            return {"options": []}
        api_key = _credential_bearer_token(credential_data)
        if not api_key:
            return {"options": []}
        result = await _calcom_request(
            api_key, "GET", "/event-types", API_VERSION_EVENT_TYPES, action_name="list_event_types"
        )
        if result.get("status") != "success":
            return {"options": []}
        data = result.get("data") or []
        if isinstance(data, dict):
            if data.get("eventTypeGroups"):
                event_types = [
                    et for g in data["eventTypeGroups"] for et in (g.get("eventTypes") or [])
                ]
            else:
                event_types = data.get("event_types") or data.get("eventTypes") or []
        else:
            event_types = data
        options = []
        for et in event_types:
            if not isinstance(et, dict):
                continue
            et_id = et.get("id")
            title = et.get("title") or et.get("slug") or f"Event {et_id}"
            length = et.get("lengthInMinutes") or et.get("length")
            label = f"{title} ({length} min)" if length else str(title)
            if et_id is not None:
                options.append({"label": label, "value": str(et_id)})
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
            "event_types": (config or {}).get("event_types"),
        }

    @classmethod
    async def _register_external_webhook(
        cls, *, webhook_url: str, credential: Dict[str, Any], config: Dict[str, Any], node_id: str
    ) -> Optional[Dict[str, Any]]:
        api_key = _credential_bearer_token(credential)
        if not api_key:
            raise ValueError("Cal.com credentials are required to register the trigger")
        secret = hashlib.sha256(f"{node_id}:{webhook_url}".encode()).hexdigest()[:32]
        triggers = _selected_trigger_events(config)
        result = await _calcom_request(
            api_key,
            "POST",
            "/webhooks",
            API_VERSION_WEBHOOKS,
            json_body={
                "subscriberUrl": webhook_url,
                "triggers": triggers,
                "active": True,
                "secret": secret,
            },
            action_name="register_webhook",
        )
        if result.get("status") != "success":
            raise ValueError(f"Cal.com webhook registration failed: {result.get('error')}")
        data = result.get("data") or {}
        external_id = data.get("id") if isinstance(data, dict) else None
        return {"external_webhook_id": str(external_id) if external_id else None, "signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(
        cls, *, credential: Optional[Dict[str, Any]], config: Dict[str, Any], node_id: str
    ) -> None:
        external_id = (config or {}).get("external_webhook_id")
        api_key = _credential_bearer_token(credential)
        if not external_id or not api_key:
            return
        await _calcom_request(
            api_key, "DELETE", f"/webhooks/{external_id}", API_VERSION_WEBHOOKS,
            action_name="unregister_webhook",
        )

    @classmethod
    def verify_webhook_signature(
        cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]
    ) -> bool:
        secret = (config or {}).get("signing_secret")
        if not secret:
            return True  # no secret stored — accept (trigger not yet armed)
        sent = headers.get("x-cal-signature-256") or headers.get("x-cal-signature")
        if not sent:
            return False
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, sent)

    @classmethod
    def filter_trigger_payload(cls, payload: Dict[str, Any], config: Dict[str, Any]) -> bool:
        """Skip webhook deliveries whose event isn't in the selected ``event_types``.

        Cal.com filters per subscription via the ``triggers`` array, but this is a
        belt-and-braces runtime guard: it also catches stale subscriptions (e.g. the
        selection changed after registration) by checking the inbound ``triggerEvent``.
        """
        if (config or {}).get("operation") != "on_booking_event":
            return True
        raw = (config or {}).get("event_types")
        if not raw or raw == CALCOM_ALL_EVENTS:
            return True
        selected = _selected_trigger_events(config)
        incoming = (payload or {}).get("triggerEvent")
        if not incoming:
            return True  # no event tag (e.g. manual/test POST) — don't drop
        return str(incoming).upper() in selected

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, CalComNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        if isinstance(op, CalComBookingTriggerConfig):
            return {
                "status": "success",
                "action": "on_booking_event",
                "data": {
                    **inputs,
                    "webhook_url": op.webhook_url,
                    "subscribed_events": _selected_trigger_events({"event_types": op.event_types}),
                },
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Connect Cal.com via OAuth or add your API key.")
        await self._ensure_fresh_token(credentials)
        api_key = _credential_bearer_token(credentials)

        handlers = {
            "list_bookings": self._list_bookings,
            "get_booking": self._get_booking,
            "create_booking": self._create_booking,
            "cancel_booking": self._cancel_booking,
            "reschedule_booking": self._reschedule_booking,
            "list_event_types": self._list_event_types,
            "get_event_type": self._get_event_type,
            "get_slots": self._get_slots,
            "list_schedules": self._list_schedules,
            "get_me": self._get_me,
            "confirm_booking": self._confirm_booking,
            "decline_booking": self._decline_booking,
            "mark_no_show": self._mark_no_show,
            "get_recordings": self._get_recordings,
            "create_event_type": self._create_event_type,
            "update_event_type": self._update_event_type,
            "delete_event_type": self._delete_event_type,
            "get_schedule": self._get_schedule,
            "create_schedule": self._create_schedule,
            "update_schedule": self._update_schedule,
            "delete_schedule": self._delete_schedule,
            "list_ooo": self._list_ooo,
            "create_ooo": self._create_ooo,
            "delete_ooo": self._delete_ooo,
            "update_me": self._update_me,
            "list_webhooks": self._list_webhooks,
            "reserve_slot": self._reserve_slot,
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
    async def _list_bookings(self, c: CalComListBookingsConfig, api_key: str) -> Dict[str, Any]:
        params = {
            "status": c.status or None,
            "attendeeEmail": c.attendee_email,
            "afterStart": c.after_start,
            "beforeEnd": c.before_end,
            "take": c.take,
        }
        return await _calcom_request(
            api_key, "GET", "/bookings", API_VERSION_BOOKINGS, params=params, action_name="list_bookings"
        )

    async def _get_booking(self, c: CalComGetBookingConfig, api_key: str) -> Dict[str, Any]:
        return await _calcom_request(
            api_key, "GET", f"/bookings/{c.booking_uid}", API_VERSION_BOOKINGS, action_name="get_booking"
        )

    async def _create_booking(self, c: CalComCreateBookingConfig, api_key: str) -> Dict[str, Any]:
        body = {
            "eventTypeId": int(c.event_type_id) if str(c.event_type_id).isdigit() else c.event_type_id,
            "start": c.start,
            "attendee": {
                "name": c.attendee_name,
                "email": c.attendee_email,
                "timeZone": c.attendee_timezone,
            },
            "guests": _comma_list(c.guests),
            "bookingFieldsResponses": {"notes": c.notes} if c.notes else None,
        }
        return await _calcom_request(
            api_key, "POST", "/bookings", API_VERSION_BOOKINGS, json_body=body, action_name="create_booking"
        )

    async def _cancel_booking(self, c: CalComCancelBookingConfig, api_key: str) -> Dict[str, Any]:
        return await _calcom_request(
            api_key, "POST", f"/bookings/{c.booking_uid}/cancel", API_VERSION_BOOKINGS,
            json_body={"cancellationReason": c.cancellation_reason}, action_name="cancel_booking"
        )

    async def _reschedule_booking(self, c: CalComRescheduleBookingConfig, api_key: str) -> Dict[str, Any]:
        return await _calcom_request(
            api_key, "POST", f"/bookings/{c.booking_uid}/reschedule", API_VERSION_BOOKINGS,
            json_body={"start": c.start, "reschedulingReason": c.reschedule_reason},
            action_name="reschedule_booking",
        )

    async def _list_event_types(self, c: CalComListEventTypesConfig, api_key: str) -> Dict[str, Any]:
        return await _calcom_request(
            api_key, "GET", "/event-types", API_VERSION_EVENT_TYPES,
            params={"username": c.username}, action_name="list_event_types"
        )

    async def _get_event_type(self, c: CalComGetEventTypeConfig, api_key: str) -> Dict[str, Any]:
        return await _calcom_request(
            api_key, "GET", f"/event-types/{c.event_type_id}", API_VERSION_EVENT_TYPES,
            action_name="get_event_type"
        )

    async def _get_slots(self, c: CalComGetSlotsConfig, api_key: str) -> Dict[str, Any]:
        params = {
            "eventTypeId": c.event_type_id,
            "start": c.start,
            "end": c.end,
            "timeZone": c.timezone,
        }
        return await _calcom_request(
            api_key, "GET", "/slots", API_VERSION_SLOTS, params=params, action_name="get_slots"
        )

    async def _list_schedules(self, c: CalComListSchedulesConfig, api_key: str) -> Dict[str, Any]:
        return await _calcom_request(
            api_key, "GET", "/schedules", API_VERSION_SCHEDULES, action_name="list_schedules"
        )

    async def _get_me(self, c: CalComGetMeConfig, api_key: str) -> Dict[str, Any]:
        return await _calcom_request(
            api_key, "GET", "/me", API_VERSION_DEFAULT, action_name="get_me"
        )

    # --- Booking actions ---
    async def _confirm_booking(self, c: CalComConfirmBookingConfig, api_key: str) -> Dict[str, Any]:
        return await _calcom_request(
            api_key, "POST", f"/bookings/{c.booking_uid}/confirm", API_VERSION_BOOKING_ACTIONS,
            action_name="confirm_booking",
        )

    async def _decline_booking(self, c: CalComDeclineBookingConfig, api_key: str) -> Dict[str, Any]:
        return await _calcom_request(
            api_key, "POST", f"/bookings/{c.booking_uid}/decline", API_VERSION_BOOKING_ACTIONS,
            json_body={"reason": c.reason}, action_name="decline_booking",
        )

    async def _mark_no_show(self, c: CalComMarkNoShowConfig, api_key: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        if c.host_absent == "true":
            body["host"] = True
        attendees = _parse_json_field(c.attendees_json, "Attendees")
        if attendees is not None:
            body["attendees"] = attendees
        return await _calcom_request(
            api_key, "POST", f"/bookings/{c.booking_uid}/mark-absent", API_VERSION_BOOKING_ACTIONS,
            json_body=body or None, action_name="mark_no_show",
        )

    async def _get_recordings(self, c: CalComGetRecordingsConfig, api_key: str) -> Dict[str, Any]:
        return await _calcom_request(
            api_key, "GET", f"/bookings/{c.booking_uid}/recordings", API_VERSION_BOOKING_ACTIONS,
            action_name="get_recordings",
        )

    # --- Event type writes ---
    async def _create_event_type(self, c: CalComCreateEventTypeConfig, api_key: str) -> Dict[str, Any]:
        body = {
            "title": c.title,
            "slug": c.slug,
            "lengthInMinutes": int(c.length_minutes) if str(c.length_minutes).isdigit() else c.length_minutes,
            "description": c.description,
        }
        extra = _parse_json_field(c.advanced_json, "Advanced Options")
        if isinstance(extra, dict):
            body.update(extra)
        return await _calcom_request(
            api_key, "POST", "/event-types", API_VERSION_EVENT_TYPES, json_body=body,
            action_name="create_event_type",
        )

    async def _update_event_type(self, c: CalComUpdateEventTypeConfig, api_key: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "title": c.title,
            "slug": c.slug,
            "description": c.description,
        }
        if c.length_minutes:
            body["lengthInMinutes"] = int(c.length_minutes) if str(c.length_minutes).isdigit() else c.length_minutes
        if c.hidden is not None:
            body["hidden"] = c.hidden == "true"
        extra = _parse_json_field(c.advanced_json, "Advanced Options")
        if isinstance(extra, dict):
            body.update(extra)
        return await _calcom_request(
            api_key, "PATCH", f"/event-types/{c.event_type_id}", API_VERSION_EVENT_TYPES,
            json_body=body, action_name="update_event_type",
        )

    async def _delete_event_type(self, c: CalComDeleteEventTypeConfig, api_key: str) -> Dict[str, Any]:
        return await _calcom_request(
            api_key, "DELETE", f"/event-types/{c.event_type_id}", API_VERSION_EVENT_TYPES,
            action_name="delete_event_type",
        )

    # --- Schedule reads & writes ---
    async def _get_schedule(self, c: CalComGetScheduleConfig, api_key: str) -> Dict[str, Any]:
        return await _calcom_request(
            api_key, "GET", f"/schedules/{c.schedule_id}", API_VERSION_SCHEDULES, action_name="get_schedule",
        )

    async def _create_schedule(self, c: CalComCreateScheduleConfig, api_key: str) -> Dict[str, Any]:
        body = {
            "name": c.name,
            "timeZone": c.timezone,
            "isDefault": c.is_default == "true",
            "availability": _parse_json_field(c.availability_json, "Availability"),
        }
        overrides = _parse_json_field(c.overrides_json, "Date Overrides")
        if overrides is not None:
            body["overrides"] = overrides
        return await _calcom_request(
            api_key, "POST", "/schedules", API_VERSION_SCHEDULES, json_body=body, action_name="create_schedule",
        )

    async def _update_schedule(self, c: CalComUpdateScheduleConfig, api_key: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {"name": c.name, "timeZone": c.timezone}
        if c.is_default is not None:
            body["isDefault"] = c.is_default == "true"
        availability = _parse_json_field(c.availability_json, "Availability")
        if availability is not None:
            body["availability"] = availability
        overrides = _parse_json_field(c.overrides_json, "Date Overrides")
        if overrides is not None:
            body["overrides"] = overrides
        return await _calcom_request(
            api_key, "PATCH", f"/schedules/{c.schedule_id}", API_VERSION_SCHEDULES,
            json_body=body, action_name="update_schedule",
        )

    async def _delete_schedule(self, c: CalComDeleteScheduleConfig, api_key: str) -> Dict[str, Any]:
        return await _calcom_request(
            api_key, "DELETE", f"/schedules/{c.schedule_id}", API_VERSION_SCHEDULES, action_name="delete_schedule",
        )

    # --- Out of office ---
    async def _list_ooo(self, c: CalComListOOOConfig, api_key: str) -> Dict[str, Any]:
        return await _calcom_request(
            api_key, "GET", "/me/ooo", API_VERSION_DEFAULT, params={"take": c.take}, action_name="list_ooo",
        )

    async def _create_ooo(self, c: CalComCreateOOOConfig, api_key: str) -> Dict[str, Any]:
        body = {
            "start": c.start,
            "end": c.end,
            "reason": c.reason,
            "notes": c.notes,
            "toUserId": int(c.to_user_id) if c.to_user_id and str(c.to_user_id).isdigit() else None,
        }
        return await _calcom_request(
            api_key, "POST", "/me/ooo", API_VERSION_DEFAULT, json_body=body, action_name="create_ooo",
        )

    async def _delete_ooo(self, c: CalComDeleteOOOConfig, api_key: str) -> Dict[str, Any]:
        return await _calcom_request(
            api_key, "DELETE", f"/me/ooo/{c.ooo_id}", API_VERSION_DEFAULT, action_name="delete_ooo",
        )

    # --- Profile write & utility ---
    async def _update_me(self, c: CalComUpdateMeConfig, api_key: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "name": c.name,
            "email": c.email,
            "timeZone": c.timezone,
            "bio": c.bio,
        }
        extra = _parse_json_field(c.advanced_json, "Advanced Options")
        if isinstance(extra, dict):
            body.update(extra)
        return await _calcom_request(
            api_key, "PATCH", "/me", API_VERSION_DEFAULT, json_body=body, action_name="update_me",
        )

    async def _list_webhooks(self, c: CalComListWebhooksConfig, api_key: str) -> Dict[str, Any]:
        return await _calcom_request(
            api_key, "GET", "/webhooks", API_VERSION_WEBHOOKS, params={"take": c.take}, action_name="list_webhooks",
        )

    async def _reserve_slot(self, c: CalComReserveSlotConfig, api_key: str) -> Dict[str, Any]:
        body = {
            "eventTypeId": int(c.event_type_id) if str(c.event_type_id).isdigit() else c.event_type_id,
            "slotStart": c.slot_start,
            "reservationDuration": int(c.reservation_duration) if c.reservation_duration and str(c.reservation_duration).isdigit() else None,
        }
        return await _calcom_request(
            api_key, "POST", "/slots/reservations", API_VERSION_SLOTS, json_body=body, action_name="reserve_slot",
        )

    # ------------------------------------------------------------------
    # OAuth token freshness
    # ------------------------------------------------------------------
    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        """Refresh an expiring Cal.com OAuth token at credential load (dropdowns,
        trigger registration). No-op for non-rotating API keys."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.calcom_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token,
            provider="calcom",
        )

    async def _ensure_fresh_token(self, credentials: CalComCredential) -> None:
        """Refresh an expired Cal.com OAuth token in place. API keys are left
        untouched (they don't expire)."""
        if not isinstance(credentials, CalComOAuthCredential):
            return

        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.calcom_oauth import refresh_access_token
        
        cred_dict = credentials.model_dump()
        await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=cred_dict,
            refresh=refresh_access_token,
            provider="calcom",
            caller_path="execute",
        )
        credentials.access_token = cred_dict["access_token"]
        credentials.expires_at = cred_dict.get("expires_at")
        if cred_dict.get("refresh_token"):
            credentials.refresh_token = cred_dict["refresh_token"]
