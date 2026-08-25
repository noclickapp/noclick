"""
Google Calendar workflow node implementation.
Enables listing, creating, updating, and deleting calendar events via OAuth credentials.
"""

import hmac
import secrets
import time
import logging
import asyncio
from typing import Dict, Any, Optional, Union, Type, List, Literal, Annotated, ClassVar
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.dynamic_options import require_credential_token
from nodes.core.watch_channels import (
    WatchChannelTriggerMixin,
    get_watch_channel,
    save_watch_channel,
    update_channel_subscription,
)
from nodes.oauth.google_oauth import is_token_expired, refresh_access_token
from nodes.oauth.google_token import ensure_fresh_google_token
from nodes.scopes.google import GOOGLE_CALENDAR_SCOPES

logger = logging.getLogger(__name__)

GOOGLE_CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"

# Calendar watch channels are requested for 7 days; the renewal cron refreshes
# them well before expiry.
_CALENDAR_CHANNEL_TTL = timedelta(days=7)


def _calendar_ms_to_datetime(ms_epoch: Optional[str]) -> datetime:
    """Convert a Google ms-since-epoch expiration string to a datetime."""
    if ms_epoch:
        try:
            return datetime.fromtimestamp(int(ms_epoch) / 1000, tz=timezone.utc)
        except (ValueError, TypeError):
            pass
    return datetime.now(timezone.utc) + _CALENDAR_CHANNEL_TTL


async def calendar_get_sync_token(access_token: str, calendar_id: str) -> str:
    """Fetch a baseline sync token by exhausting an initial events.list."""
    sync_token = ""
    page_token = None
    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            params: Dict[str, Any] = {"maxResults": 250, "showDeleted": True}
            if page_token:
                params["pageToken"] = page_token
            response = await client.get(
                f"{GOOGLE_CALENDAR_API_BASE}/calendars/{calendar_id}/events",
                headers={"Authorization": f"Bearer {access_token}"},
                params=params,
            )
            response.raise_for_status()
            data = response.json()
            page_token = data.get("nextPageToken")
            if not page_token:
                sync_token = data.get("nextSyncToken", "")
                break
    return sync_token


async def calendar_watch_events(
    access_token: str,
    calendar_id: str,
    channel_id: str,
    webhook_url: str,
    channel_token: str,
) -> Dict[str, Any]:
    """Open a Calendar events watch channel. Returns the channel resource."""
    expiration_ms = int(
        (datetime.now(timezone.utc) + _CALENDAR_CHANNEL_TTL).timestamp() * 1000
    )
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{GOOGLE_CALENDAR_API_BASE}/calendars/{calendar_id}/events/watch",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={
                "id": channel_id,
                "type": "web_hook",
                "address": webhook_url,
                "token": channel_token,
                "expiration": expiration_ms,
            },
        )
        response.raise_for_status()
        return response.json()


async def calendar_stop_channel(
    access_token: str, channel_id: str, resource_id: str
) -> None:
    """Stop a Calendar watch channel."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{GOOGLE_CALENDAR_API_BASE}/channels/stop",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={"id": channel_id, "resourceId": resource_id},
        )
        if response.status_code not in (200, 204, 404):
            response.raise_for_status()


async def calendar_list_changed_events(
    access_token: str, calendar_id: str, sync_token: str
) -> Dict[str, Any]:
    """List events changed since *sync_token*. Returns ``{events, sync_token,
    expired}`` — ``expired`` is True when the sync token is no longer valid."""
    events: List[Dict[str, Any]] = []
    page_token = None
    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            params: Dict[str, Any] = {"syncToken": sync_token, "showDeleted": True}
            if page_token:
                params["pageToken"] = page_token
            response = await client.get(
                f"{GOOGLE_CALENDAR_API_BASE}/calendars/{calendar_id}/events",
                headers={"Authorization": f"Bearer {access_token}"},
                params=params,
            )
            if response.status_code == 410:
                # Sync token expired — caller must re-baseline.
                return {"events": [], "sync_token": "", "expired": True}
            response.raise_for_status()
            data = response.json()
            events.extend(data.get("items", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                return {
                    "events": events,
                    "sync_token": data.get("nextSyncToken", sync_token),
                    "expired": False,
                }


# ============================================================================
# Google Calendar Node Credential Schema
# ============================================================================


class GoogleCalendarOAuthCredential(BaseModel):
    """
    OAuth credential for Google Calendar access.
    Tokens are obtained via OAuth flow, not entered manually.
    """

    credential_type: Literal["google_calendar_oauth"] = Field(
        "google_calendar_oauth", json_schema_extra={"ui:hidden": True}
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
            "x-oauth-scopes": ["https://www.googleapis.com/auth/calendar"],
        }
    )


# ============================================================================
# Google Calendar Node Configuration Models
# ============================================================================


class GoogleCalendarListEventsConfig(BaseModel):
    """Configuration for listing events from a calendar"""

    operation: Literal["list_calendar_events"] = Field(
        default="list_calendar_events",
        title="List Calendar Events",
        description="List events from calendar",
        json_schema_extra={
            "ui:hidden": True,
            "const": "list_calendar_events",
            "x-category": "Event",
            "x-is-trigger": False,
            "x-display-name": "List Calendar Events",
            "x-keywords": [
                "list events",
                "show my schedule",
                "upcoming meetings",
                "agenda",
                "whats on calendar",
                "events between dates",
            ],
        },
    )
    calendar_id: str = Field(
        ...,
        title="Calendar",
        description="Select a calendar to list events from",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "calendar_id",
                "placeholder": "Select a calendar...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter calendar ID (e.g., primary)",
            },
            "x-resource-type": "google_calendar",
        },
    )
    time_min: Optional[str] = Field(
        None,
        title="Start Time",
        description="Filter events starting from this time (ISO 8601 format, e.g., 2024-01-01T00:00:00Z)",
        json_schema_extra={"placeholder": "2024-01-01T00:00:00Z (optional)"},
    )
    time_max: Optional[str] = Field(
        None,
        title="End Time",
        description="Filter events ending before this time (ISO 8601 format)",
        json_schema_extra={"placeholder": "2024-12-31T23:59:59Z (optional)"},
    )
    max_results: Optional[int] = Field(
        50,
        title="Max Results",
        description="Maximum number of events to return (1-2500)",
        ge=1,
        le=2500,
    )
    search_query: Optional[str] = Field(
        None,
        title="Search Query",
        description="Free text search terms to filter events",
        json_schema_extra={"placeholder": "meeting, lunch, etc. (optional)"},
    )


class GoogleCalendarGetEventConfig(BaseModel):
    """Configuration for getting a single event"""

    operation: Literal["fetch_calendar_event"] = Field(
        default="fetch_calendar_event",
        title="Fetch Calendar Event",
        description="Get a specific event",
        json_schema_extra={
            "ui:hidden": True,
            "const": "fetch_calendar_event",
            "x-category": "Event",
            "x-is-trigger": False,
            "x-display-name": "Fetch Calendar Event",
            "x-keywords": [
                "get single event",
                "event details",
                "look up meeting",
                "one event by id",
                "open appointment",
            ],
        },
    )
    calendar_id: str = Field(
        ...,
        title="Calendar",
        description="Select a calendar",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "calendar_id",
                "placeholder": "Select a calendar...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter calendar ID (e.g., primary)",
            },
            "x-resource-type": "google_calendar",
        },
    )
    event_id: str = Field(
        ...,
        title="Event ID",
        description="The ID of the event to retrieve",
        json_schema_extra={"placeholder": "Event ID"},
    )


class GoogleCalendarCreateEventConfig(BaseModel):
    """Configuration for creating a new event"""

    operation: Literal["create_calendar_event"] = Field(
        default="create_calendar_event",
        title="Create Calendar Event",
        description="Create a new event",
        json_schema_extra={
            "ui:hidden": True,
            "const": "create_calendar_event",
            "x-category": "Event",
            "x-is-trigger": False,
            "x-display-name": "Create Calendar Event",
            "x-keywords": [
                "schedule meeting",
                "book appointment",
                "add event",
                "put on calendar",
                "new event",
                "invite attendees",
            ],
        },
    )
    calendar_id: str = Field(
        ...,
        title="Calendar",
        description="Select a calendar to create the event in",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "calendar_id",
                "placeholder": "Select a calendar...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter calendar ID (e.g., primary)",
            },
            "x-resource-type": "google_calendar",
        },
    )
    summary: str = Field(
        ...,
        title="Event Title",
        description="Title of the event",
        json_schema_extra={"placeholder": "Meeting with John"},
    )
    description: Optional[str] = Field(
        None,
        title="Description",
        description="Description or notes for the event",
        json_schema_extra={"ui:widget": "textarea", "placeholder": "Event details..."},
    )
    location: Optional[str] = Field(
        None,
        title="Location",
        description="Location of the event",
        json_schema_extra={"placeholder": "Conference Room A"},
    )
    start_time: str = Field(
        ...,
        title="Start Time",
        description="Event start time (ISO 8601 format, e.g., 2024-01-15T10:00:00-05:00)",
        json_schema_extra={"placeholder": "2024-01-15T10:00:00-05:00"},
    )
    end_time: str = Field(
        ...,
        title="End Time",
        description="Event end time (ISO 8601 format)",
        json_schema_extra={"placeholder": "2024-01-15T11:00:00-05:00"},
    )
    timezone: Optional[str] = Field(
        None,
        title="Timezone",
        description="Timezone for the event (e.g., America/New_York). Defaults to calendar timezone.",
        json_schema_extra={"placeholder": "America/New_York (optional)"},
    )
    attendees: Optional[str] = Field(
        None,
        title="Attendees",
        description="Comma-separated list of attendee email addresses",
        json_schema_extra={"placeholder": "john@example.com, jane@example.com"},
    )
    send_notifications: Optional[bool] = Field(
        True,
        title="Send Notifications",
        description="Whether to send notifications to attendees",
    )


class GoogleCalendarUpdateEventConfig(BaseModel):
    """Configuration for updating an existing event"""

    operation: Literal["update_calendar_event"] = Field(
        default="update_calendar_event",
        title="Update Calendar Event",
        description="Update an existing event",
        json_schema_extra={
            "ui:hidden": True,
            "const": "update_calendar_event",
            "x-category": "Event",
            "x-is-trigger": False,
            "x-display-name": "Update Calendar Event",
            "x-keywords": [
                "reschedule meeting",
                "edit event",
                "change event time",
                "move appointment",
                "modify meeting",
            ],
        },
    )
    calendar_id: str = Field(
        ...,
        title="Calendar",
        description="Select a calendar",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "calendar_id",
                "placeholder": "Select a calendar...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter calendar ID (e.g., primary)",
            },
            "x-resource-type": "google_calendar",
        },
    )
    event_id: str = Field(
        ...,
        title="Event ID",
        description="The ID of the event to update",
        json_schema_extra={"placeholder": "Event ID"},
    )
    summary: Optional[str] = Field(
        None,
        title="Event Title",
        description="New title for the event (leave empty to keep current)",
        json_schema_extra={"placeholder": "New title (optional)"},
    )
    description: Optional[str] = Field(
        None,
        title="Description",
        description="New description (leave empty to keep current)",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "New description (optional)",
        },
    )
    location: Optional[str] = Field(
        None,
        title="Location",
        description="New location (leave empty to keep current)",
        json_schema_extra={"placeholder": "New location (optional)"},
    )
    start_time: Optional[str] = Field(
        None,
        title="Start Time",
        description="New start time (ISO 8601 format, leave empty to keep current)",
        json_schema_extra={"placeholder": "2024-01-15T10:00:00-05:00 (optional)"},
    )
    end_time: Optional[str] = Field(
        None,
        title="End Time",
        description="New end time (ISO 8601 format, leave empty to keep current)",
        json_schema_extra={"placeholder": "2024-01-15T11:00:00-05:00 (optional)"},
    )
    timezone: Optional[str] = Field(
        None,
        title="Timezone",
        description="Timezone for the event times",
        json_schema_extra={"placeholder": "America/New_York (optional)"},
    )
    send_notifications: Optional[bool] = Field(
        True,
        title="Send Notifications",
        description="Whether to send notifications about the update",
    )


class GoogleCalendarDeleteEventConfig(BaseModel):
    """Configuration for deleting an event"""

    operation: Literal["delete_calendar_event"] = Field(
        default="delete_calendar_event",
        title="Delete Calendar Event",
        description="Delete an event",
        json_schema_extra={
            "ui:hidden": True,
            "const": "delete_calendar_event",
            "x-category": "Event",
            "x-is-trigger": False,
            "x-display-name": "Delete Calendar Event",
            "x-keywords": [
                "cancel meeting",
                "remove event",
                "delete appointment",
                "cancel calendar entry",
            ],
        },
    )
    calendar_id: str = Field(
        ...,
        title="Calendar",
        description="Select a calendar",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "calendar_id",
                "placeholder": "Select a calendar...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter calendar ID (e.g., primary)",
            },
            "x-resource-type": "google_calendar",
        },
    )
    event_id: str = Field(
        ...,
        title="Event ID",
        description="The ID of the event to delete",
        json_schema_extra={"placeholder": "Event ID"},
    )
    send_notifications: Optional[bool] = Field(
        True,
        title="Send Notifications",
        description="Whether to send cancellation notifications to attendees",
    )


class GoogleCalendarQuickAddConfig(BaseModel):
    """Configuration for creating an event from natural language text"""

    operation: Literal["create_event_from_text"] = Field(
        default="create_event_from_text",
        title="Create Event from Text",
        description="Create event from text",
        json_schema_extra={
            "ui:hidden": True,
            "const": "create_event_from_text",
            "x-category": "Event",
            "x-is-trigger": False,
            "x-display-name": "Create Event from Text",
            "x-keywords": [
                "quick add",
                "natural language event",
                "type to schedule",
                "smart add event",
                "parse text to event",
                "lunch tomorrow at noon",
            ],
        },
    )
    calendar_id: str = Field(
        ...,
        title="Calendar",
        description="Select a calendar to create the event in",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "calendar_id",
                "placeholder": "Select a calendar...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter calendar ID (e.g., primary)",
            },
            "x-resource-type": "google_calendar",
        },
    )
    text: str = Field(
        ...,
        title="Event Text",
        description="Natural language text describing the event (e.g., 'Meeting with John tomorrow at 3pm')",
        json_schema_extra={"placeholder": "Meeting with John tomorrow at 3pm"},
    )
    send_notifications: Optional[bool] = Field(
        True,
        title="Send Notifications",
        description="Whether to send notifications to attendees",
    )


class GoogleCalendarGetInstancesConfig(BaseModel):
    """Configuration for getting instances of a recurring event"""

    operation: Literal["fetch_recurring_event_instances"] = Field(
        default="fetch_recurring_event_instances",
        title="Fetch Recurring Event Instances",
        description="Get recurring event instances",
        json_schema_extra={
            "ui:hidden": True,
            "const": "fetch_recurring_event_instances",
            "x-category": "Event",
            "x-is-trigger": False,
            "x-display-name": "Fetch Recurring Event Instances",
            "x-keywords": [
                "recurring event instances",
                "repeating meeting occurrences",
                "series instances",
                "expand recurrence",
                "all occurrences",
            ],
        },
    )
    calendar_id: str = Field(
        ...,
        title="Calendar",
        description="Select a calendar",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "calendar_id",
                "placeholder": "Select a calendar...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter calendar ID (e.g., primary)",
            },
            "x-resource-type": "google_calendar",
        },
    )
    event_id: str = Field(
        ...,
        title="Event ID",
        description="The ID of the recurring event",
        json_schema_extra={"placeholder": "Recurring event ID"},
    )
    time_min: Optional[str] = Field(
        None,
        title="Start Time",
        description="Filter instances starting from this time (ISO 8601 format)",
        json_schema_extra={"placeholder": "2024-01-01T00:00:00Z (optional)"},
    )
    time_max: Optional[str] = Field(
        None,
        title="End Time",
        description="Filter instances ending before this time (ISO 8601 format)",
        json_schema_extra={"placeholder": "2024-12-31T23:59:59Z (optional)"},
    )
    max_results: Optional[int] = Field(
        50,
        title="Max Results",
        description="Maximum number of instances to return (1-2500)",
        ge=1,
        le=2500,
    )


class GoogleCalendarMoveEventConfig(BaseModel):
    """Configuration for moving an event to another calendar"""

    operation: Literal["move_event_to_calendar"] = Field(
        default="move_event_to_calendar",
        title="Move Event to Calendar",
        description="Move event to another calendar",
        json_schema_extra={
            "ui:hidden": True,
            "const": "move_event_to_calendar",
            "x-category": "Event",
            "x-is-trigger": False,
            "x-display-name": "Move Event to Calendar",
            "x-keywords": [
                "move event",
                "transfer to another calendar",
                "reassign event calendar",
                "switch event calendar",
            ],
        },
    )
    calendar_id: str = Field(
        ...,
        title="Source Calendar",
        description="Select the calendar containing the event",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "calendar_id",
                "placeholder": "Select source calendar...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter calendar ID (e.g., primary)",
            },
            "x-resource-type": "google_calendar",
        },
    )
    event_id: str = Field(
        ...,
        title="Event ID",
        description="The ID of the event to move",
        json_schema_extra={"placeholder": "Event ID"},
    )
    destination_calendar_id: str = Field(
        ...,
        title="Destination Calendar",
        description="Select the calendar to move the event to",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "destination_calendar_id",
                "placeholder": "Select destination calendar...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter destination calendar ID",
            },
            "x-resource-type": "google_calendar",
        },
    )
    send_notifications: Optional[bool] = Field(
        True,
        title="Send Notifications",
        description="Whether to send notifications about the move",
    )


class GoogleCalendarQueryFreebusyConfig(BaseModel):
    """Configuration for querying free/busy information"""

    operation: Literal["query_calendar_availability"] = Field(
        default="query_calendar_availability",
        title="Query Calendar Availability",
        description="Check availability",
        json_schema_extra={
            "ui:hidden": True,
            "const": "query_calendar_availability",
            "x-category": "Availability",
            "x-is-trigger": False,
            "x-display-name": "Query Calendar Availability",
            "x-keywords": [
                "check availability",
                "free busy",
                "when am i free",
                "find open slots",
                "busy times",
                "scheduling availability",
            ],
        },
    )
    calendar_ids: str = Field(
        ...,
        title="Calendar IDs",
        description="Comma-separated list of calendar IDs to check (e.g., 'primary, john@example.com')",
        json_schema_extra={"placeholder": "primary, colleague@example.com"},
    )
    time_min: str = Field(
        ...,
        title="Start Time",
        description="Start of the interval to query (ISO 8601 format)",
        json_schema_extra={"placeholder": "2024-01-15T09:00:00Z"},
    )
    time_max: str = Field(
        ...,
        title="End Time",
        description="End of the interval to query (ISO 8601 format)",
        json_schema_extra={"placeholder": "2024-01-15T18:00:00Z"},
    )


class GoogleCalendarListCalendarsConfig(BaseModel):
    """Configuration for listing all calendars"""

    operation: Literal["list_user_calendars"] = Field(
        default="list_user_calendars",
        title="List User Calendars",
        description="List all calendars",
        json_schema_extra={
            "ui:hidden": True,
            "const": "list_user_calendars",
            "x-category": "Calendar",
            "x-is-trigger": False,
            "x-display-name": "List User Calendars",
            "x-keywords": [
                "list calendars",
                "my calendars",
                "show all calendars",
                "calendar list",
            ],
        },
    )
    show_hidden: Optional[bool] = Field(
        False, title="Show Hidden", description="Whether to include hidden calendars"
    )
    show_deleted: Optional[bool] = Field(
        False, title="Show Deleted", description="Whether to include deleted calendars"
    )


class GoogleCalendarGetCalendarConfig(BaseModel):
    """Configuration for getting calendar metadata"""

    operation: Literal["fetch_calendar_metadata"] = Field(
        default="fetch_calendar_metadata",
        title="Fetch Calendar Metadata",
        description="Get calendar details",
        json_schema_extra={
            "ui:hidden": True,
            "const": "fetch_calendar_metadata",
            "x-category": "Calendar",
            "x-is-trigger": False,
            "x-display-name": "Fetch Calendar Metadata",
            "x-keywords": [
                "calendar details",
                "calendar timezone",
                "calendar info",
                "get calendar settings",
            ],
        },
    )
    calendar_id: str = Field(
        ...,
        title="Calendar",
        description="Select a calendar to get details for",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "calendar_id",
                "placeholder": "Select a calendar...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter calendar ID (e.g., primary)",
            },
            "x-resource-type": "google_calendar",
        },
    )


class GoogleCalendarCreateCalendarConfig(BaseModel):
    """Configuration for creating a new calendar"""

    operation: Literal["create_new_calendar"] = Field(
        default="create_new_calendar",
        title="Create New Calendar",
        description="Create a new calendar",
        json_schema_extra={
            "ui:hidden": True,
            "const": "create_new_calendar",
            "x-category": "Calendar",
            "x-is-trigger": False,
            "x-display-name": "Create New Calendar",
            "x-keywords": [
                "new calendar",
                "make a calendar",
                "add calendar",
                "create secondary calendar",
            ],
            "x-creates-resource": True,
            "x-resource-type": "google_calendar",
            "x-resource-id-path": "calendar.id",
        },
    )
    summary: str = Field(
        ...,
        title="Calendar Name",
        description="Name of the new calendar",
        json_schema_extra={"placeholder": "Work Projects"},
    )
    description: Optional[str] = Field(
        None,
        title="Description",
        description="Description of the calendar",
        json_schema_extra={
            "ui:widget": "textarea",
            "placeholder": "Calendar for tracking work projects...",
        },
    )
    timezone: Optional[str] = Field(
        None,
        title="Timezone",
        description="Timezone for the calendar (e.g., America/New_York)",
        json_schema_extra={"placeholder": "America/New_York (optional)"},
    )
    location: Optional[str] = Field(
        None,
        title="Location",
        description="Geographic location of the calendar",
        json_schema_extra={"placeholder": "New York, NY (optional)"},
    )


class GoogleCalendarClearCalendarConfig(BaseModel):
    """Configuration for clearing all events from a calendar"""

    operation: Literal["clear_calendar_events"] = Field(
        default="clear_calendar_events",
        title="Clear Calendar Events",
        description="Clear all events",
        json_schema_extra={
            "ui:hidden": True,
            "const": "clear_calendar_events",
            "x-category": "Calendar",
            "x-is-trigger": False,
            "x-display-name": "Clear Calendar Events",
            "x-keywords": [
                "empty calendar",
                "wipe all events",
                "clear schedule",
                "delete all events",
                "purge calendar",
            ],
        },
    )
    calendar_id: str = Field(
        ...,
        title="Calendar",
        description="Select a calendar to clear (WARNING: This deletes all events!)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "calendar_id",
                "placeholder": "Select a calendar...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or enter calendar ID",
            },
            "x-resource-type": "google_calendar",
        },
    )


class GoogleCalendarOnEventConfig(BaseModel):
    """Trigger: fires when events change on a Google Calendar."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["on_calendar_event"] = Field(
        "on_calendar_event",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Calendar Event",
            "x-keywords": [
                "when calendar changes",
                "on event change",
                "watch calendar",
                "calendar activity",
                "any event change",
            ],
        },
        title="On Calendar Event",
    )
    calendar_id: str = Field(
        "primary",
        title="Calendar",
        description="The calendar to watch ('primary' for the main calendar)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "calendar_id",
                "placeholder": "Select a calendar...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a calendar ID",
            },
            "x-resource-type": "google_calendar",
        },
    )
    webhook_id: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:copyable": True,
            "ui:loadValue": True,
        },
    )
    signing_secret: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    calendar_sync_token: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    relay_connected: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    is_production: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    trigger_registered: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    trigger_error: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )


class GoogleCalendarOnEventActiveConfig(BaseModel):
    """Trigger: fires when a calendar event is created or updated."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["on_event_active"] = Field(
        "on_event_active",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Event Created or Updated",
        },
        title="On Event Created or Updated",
    )
    calendar_id: str = Field(
        "primary",
        title="Calendar",
        description="The calendar to watch ('primary' for the main calendar)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "calendar_id",
                "placeholder": "Select a calendar...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a calendar ID",
            },
            "x-resource-type": "google_calendar",
        },
    )
    webhook_id: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:copyable": True,
            "ui:loadValue": True,
        },
    )
    signing_secret: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    calendar_sync_token: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    relay_connected: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    is_production: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    trigger_registered: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    trigger_error: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )


class GoogleCalendarOnEventCancelledConfig(BaseModel):
    """Trigger: fires when a calendar event is cancelled or deleted."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["on_event_cancelled"] = Field(
        "on_event_cancelled",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Event Cancelled",
            "x-keywords": [
                "when event cancelled",
                "on event deleted",
                "watch for cancellations",
                "meeting cancelled",
                "event removed",
            ],
        },
        title="On Event Cancelled",
    )
    calendar_id: str = Field(
        "primary",
        title="Calendar",
        description="The calendar to watch ('primary' for the main calendar)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "calendar_id",
                "placeholder": "Select a calendar...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a calendar ID",
            },
            "x-resource-type": "google_calendar",
        },
    )
    webhook_id: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:copyable": True,
            "ui:loadValue": True,
        },
    )
    signing_secret: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    calendar_sync_token: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    relay_connected: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    is_production: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    trigger_registered: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    trigger_error: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )


def _hidden_calendar_fields() -> dict:
    """Shared hidden fields for all granular calendar trigger configs."""
    return {
        "webhook_id": None,
        "webhook_url": None,
        "signing_secret": None,
        "calendar_sync_token": None,
        "relay_connected": None,
        "is_production": None,
        "trigger_registered": None,
        "trigger_error": None,
    }


class GoogleCalendarOnEventCreatedConfig(BaseModel):
    """Trigger: fires when a new calendar event is created."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["on_event_created"] = Field(
        "on_event_created",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Event Created",
            "x-keywords": [
                "when new event",
                "on event scheduled",
                "watch for new meetings",
                "new appointment added",
                "event booked",
            ],
        },
        title="On Event Created",
    )
    calendar_id: str = Field(
        "primary",
        title="Calendar",
        description="The calendar to watch ('primary' for the main calendar)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "calendar_id",
                "placeholder": "Select a calendar...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a calendar ID",
            },
            "x-resource-type": "google_calendar",
        },
    )
    webhook_id: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:copyable": True,
            "ui:loadValue": True,
        },
    )
    signing_secret: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    calendar_sync_token: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    relay_connected: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    is_production: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    trigger_registered: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    trigger_error: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )


class GoogleCalendarOnEventUpdatedConfig(BaseModel):
    """Trigger: fires when an existing calendar event is modified."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["on_event_updated"] = Field(
        "on_event_updated",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Event Updated",
            "x-keywords": [
                "when event changed",
                "on event rescheduled",
                "watch for edits",
                "meeting moved",
                "event time changed",
            ],
        },
        title="On Event Updated",
    )
    calendar_id: str = Field(
        "primary",
        title="Calendar",
        description="The calendar to watch ('primary' for the main calendar)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "calendar_id",
                "placeholder": "Select a calendar...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a calendar ID",
            },
            "x-resource-type": "google_calendar",
        },
    )
    webhook_id: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:copyable": True,
            "ui:loadValue": True,
        },
    )
    signing_secret: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    calendar_sync_token: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    relay_connected: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    is_production: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    trigger_registered: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    trigger_error: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )


class GoogleCalendarOnEventTentativeConfig(BaseModel):
    """Trigger: fires when a calendar event is tentatively accepted."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["on_event_tentative"] = Field(
        "on_event_tentative",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Event Tentative",
            "x-keywords": [
                "when tentatively accepted",
                "maybe rsvp",
                "on tentative response",
                "watch tentative",
                "event maybe",
            ],
        },
        title="On Event Tentative",
    )
    calendar_id: str = Field(
        "primary",
        title="Calendar",
        description="The calendar to watch ('primary' for the main calendar)",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "calendar_id",
                "placeholder": "Select a calendar...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a calendar ID",
            },
            "x-resource-type": "google_calendar",
        },
    )
    webhook_id: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:copyable": True,
            "ui:loadValue": True,
        },
    )
    signing_secret: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    calendar_sync_token: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    relay_connected: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    is_production: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    trigger_registered: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    trigger_error: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )


# Union of all config types for oneOf schema
GoogleCalendarConfig = Annotated[
    Union[
        GoogleCalendarOnEventConfig,
        GoogleCalendarOnEventActiveConfig,
        GoogleCalendarOnEventCancelledConfig,
        GoogleCalendarOnEventCreatedConfig,
        GoogleCalendarOnEventUpdatedConfig,
        GoogleCalendarOnEventTentativeConfig,
        GoogleCalendarListEventsConfig,
        GoogleCalendarGetEventConfig,
        GoogleCalendarCreateEventConfig,
        GoogleCalendarUpdateEventConfig,
        GoogleCalendarDeleteEventConfig,
        GoogleCalendarQuickAddConfig,
        GoogleCalendarGetInstancesConfig,
        GoogleCalendarMoveEventConfig,
        GoogleCalendarQueryFreebusyConfig,
        GoogleCalendarListCalendarsConfig,
        GoogleCalendarGetCalendarConfig,
        GoogleCalendarCreateCalendarConfig,
        GoogleCalendarClearCalendarConfig,
    ],
    Discriminator("operation"),
]


class GoogleCalendarNodeConfig(
    NodeConfig[GoogleCalendarConfig, GoogleCalendarOAuthCredential]
):
    """Full configuration for Google Calendar node including credentials"""

    pass


# ============================================================================
# Google Calendar Node Implementation
# ============================================================================


class GoogleCalendarNode(WatchChannelTriggerMixin, WorkflowNode):
    """
    Google Calendar workflow node for managing calendar events.
    """

    _trigger_locks: ClassVar[Dict[tuple[str, str], asyncio.Lock]] = {}
    _trigger_operations: ClassVar[frozenset[str]] = frozenset(
        {
            "on_calendar_event",
            "on_event_active",
            "on_event_cancelled",
            "on_event_created",
            "on_event_updated",
            "on_event_tentative",
        }
    )

    edit_examples = [
        "Schedule a team standup on the #engineering calendar for 9am tomorrow",
        "Check availability for the next 2 weeks across all team member calendars",
        "Create a recurring weekly sync with product leads for the next quarter",
        "Move all meetings from the old calendar to the new shared project calendar",
        "Get all events in December and export to a CSV with attendee lists",
        'Quick-add "Client demo at 3pm" using natural language on main calendar',
        "Update the next 5 all-hands meetings with new conference room details",
    ]

    @classmethod
    def get_config_schema(cls) -> Dict[str, Any]:
        schema = super().get_config_schema()

        # Keep the legacy `on_event_active` operation runnable for already-saved
        # workflows, but remove it from the generated schema so the frontend
        # action picker only shows the non-overlapping trigger set.
        legacy_ref = "#/$defs/GoogleCalendarOnEventActiveConfig"
        config_schema = (schema.get("properties") or {}).get("config") or {}
        discriminator = config_schema.get("discriminator") or {}
        mapping = discriminator.get("mapping")
        if isinstance(mapping, dict):
            mapping.pop("on_event_active", None)

        one_of = config_schema.get("oneOf")
        if isinstance(one_of, list):
            config_schema["oneOf"] = [
                option
                for option in one_of
                if not (isinstance(option, dict) and option.get("$ref") == legacy_ref)
            ]

        defs = schema.get("$defs")
        if isinstance(defs, dict):
            defs.pop("GoogleCalendarOnEventActiveConfig", None)

        return schema

    @classmethod
    def should_propagate_output(
        cls, output: Dict[str, Any], config: Dict[str, Any]
    ) -> bool:
        operation = (config or {}).get("operation")
        if operation in cls._trigger_operations:
            return bool((output or {}).get("event_count"))
        return True

    @classmethod
    def _get_trigger_lock(
        cls, workflow_id: Optional[str], node_id: Optional[str]
    ) -> asyncio.Lock:
        key = (workflow_id or "", node_id or "")
        lock = cls._trigger_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            cls._trigger_locks[key] = lock
        return lock

    def _get_google_trigger_metadata(
        self,
    ) -> tuple[Optional[int], Optional[str], Optional[str]]:
        payload = (self.node_data or {}).get("_triggerPayload") or {}
        webhook_meta = payload.get("_webhook") or {}
        headers = webhook_meta.get("headers") or {}
        raw_number = headers.get("x-goog-message-number")
        message_number: Optional[int] = None
        if raw_number is not None:
            try:
                message_number = int(raw_number)
            except (TypeError, ValueError):
                logger.warning(
                    f"[GoogleCalendarNode] Invalid x-goog-message-number for node {self.node_id}: {raw_number!r}"
                )
        resource_id = headers.get("x-goog-resource-id")
        channel_id = headers.get("x-goog-channel-id")
        return message_number, resource_id, channel_id

    scope_registry = GOOGLE_CALENDAR_SCOPES
    connection_evidence = ConnectionEvidence(
        field="calendar_id",
        noun="calendars",
    )

    @classmethod
    def get_config_model(cls) -> Optional[Union[Type, type]]:
        """Get Pydantic config model for Google Calendar node"""
        return GoogleCalendarNodeConfig

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Load dynamic options for a field.

        Args:
            field_name: Name of the field needing options (e.g., "calendar_id")
            credential_data: Decrypted OAuth credential data
            context: Additional context
            page_token: Optional pagination token for paginated results
            search: Optional search term to filter results

        Returns:
            List of option dicts with 'value' and 'label' keys
        """
        logger.info(
            f"[GoogleCalendarNode] load_field_options called: field={field_name}"
        )
        if field_name == "calendar_id" or field_name == "destination_calendar_id":
            return await cls._list_calendars(credential_data, search=search)
        return []

    @classmethod
    async def _list_calendars(
        cls, credential_data: Dict[str, Any], search: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        List all calendars accessible to the user.
        """
        access_token = require_credential_token(
            credential_data.get("access_token"),
            "Connect a Google account to load calendars",
        )

        url = f"{GOOGLE_CALENDAR_API_BASE}/users/me/calendarList"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {access_token}"},
                )

                if response.status_code != 200:
                    error_data = response.json()
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                    raise ValueError(f"Google Calendar API error: {error_msg}")

                data = response.json()
                calendars = data.get("items", [])

                options = []
                for calendar in calendars:
                    # Use 'primary' for the user's primary calendar
                    cal_id = calendar.get("id", "")
                    summary = calendar.get("summary", cal_id)
                    is_primary = calendar.get("primary", False)

                    options.append(
                        {
                            "value": cal_id,
                            "label": f"{summary} (Primary)" if is_primary else summary,
                            "metadata": {
                                "primary": is_primary,
                                "accessRole": calendar.get("accessRole"),
                                "backgroundColor": calendar.get("backgroundColor"),
                            },
                        }
                    )

                # Sort to put primary calendar first
                options.sort(
                    key=lambda x: (not x["metadata"].get("primary", False), x["label"])
                )

                logger.info(f"[GoogleCalendarNode] Found {len(options)} calendars")
                return options

        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"Failed to load Google Calendar options: {e}") from e

    # ========================================================================
    # Watch-channel trigger (on_calendar_event)
    # ========================================================================

    async def _trigger_on_calendar_event(self, config, credentials) -> Dict[str, Any]:
        """Fetch calendar events changed since the stored sync token."""
        async with self._get_trigger_lock(self.workflow_id, self.node_id):
            state = await self._load_node_state()
            sync_token = state.get("sync_token") or getattr(
                config, "calendar_sync_token", None
            )
            calendar_id = getattr(config, "calendar_id", "primary") or "primary"
            if not sync_token:
                return {
                    "message": (
                        "This trigger fires when events change on the calendar. "
                        "Save the workflow to activate it."
                    ),
                    "events": [],
                    "event_count": 0,
                }

            (
                message_number,
                resource_id,
                channel_id,
            ) = self._get_google_trigger_metadata()
            last_message_number = state.get("last_google_message_number")
            try:
                last_message_number = (
                    int(last_message_number)
                    if last_message_number is not None
                    else None
                )
            except (TypeError, ValueError):
                last_message_number = None
            last_channel_id = state.get("last_google_channel_id")
            # Dedup within a CHANNEL only: x-goog-message-number restarts per
            # channel, so a re-registered channel's low numbers must not be
            # judged "stale" against the previous channel's high-water mark.
            if (
                message_number is not None
                and channel_id
                and last_channel_id == channel_id
                and last_message_number is not None
                and message_number <= last_message_number
            ):
                logger.info(
                    f"[GoogleCalendarNode] Skipping duplicate/stale Calendar wake-up for node {self.node_id}: "
                    f"message_number={message_number}, last_message_number={last_message_number}"
                )
                return {
                    "events": [],
                    "event_count": 0,
                    "deduped": True,
                }

            if not credentials:
                raise ValueError(
                    f"[GoogleCalendarNode] Google Calendar credentials are required but not provided. "
                    f"Please connect a Google account in the node's credentials tab."
                )


            cred_dict = credentials.model_dump()
            credential_id = (self.node_data or {}).get("credential_id")
            access_token = await ensure_fresh_google_token(
                None,
                credential_id,
                self.user_id,
                cred_dict,
            )

            result = await calendar_list_changed_events(
                access_token, calendar_id, sync_token
            )
            if result["expired"]:
                # Sync token expired — re-baseline and report no changes this round.
                fresh_token = await calendar_get_sync_token(access_token, calendar_id)
                new_state = dict(state)
                new_state["sync_token"] = fresh_token
                if message_number is not None:
                    new_state["last_google_message_number"] = message_number
                if resource_id:
                    new_state["last_google_resource_id"] = resource_id
                if channel_id:
                    new_state["last_google_channel_id"] = channel_id
                await self._save_node_state(new_state)
                return {"events": [], "event_count": 0, "resynced": True}

            events = result["events"]

            # Filter events based on the selected trigger operation.
            operation = getattr(config, "operation", "on_calendar_event")
            if operation == "on_event_active":
                events = [e for e in events if e.get("status") != "cancelled"]
            elif operation == "on_event_cancelled":
                events = [e for e in events if e.get("status") == "cancelled"]
            elif operation == "on_event_tentative":
                events = [e for e in events if e.get("status") == "tentativelyAccepted"]
            elif operation in ("on_event_created", "on_event_updated"):
                # Only consider non-cancelled events, then distinguish by comparing
                # the `created` and `updated` RFC3339 timestamps.
                # A brand-new event has created ≈ updated (within 10 seconds).
                from dateutil.parser import isoparse

                def _ts_diff(event: dict) -> float:
                    """Return |updated - created| in seconds, or -1 if unparseable."""
                    try:
                        c = isoparse(event["created"])
                        u = isoparse(event["updated"])
                        return abs((u - c).total_seconds())
                    except Exception:
                        return -1.0

                active = [e for e in events if e.get("status") != "cancelled"]
                if operation == "on_event_created":
                    events = [e for e in active if _ts_diff(e) <= 10]
                else:
                    events = [e for e in active if _ts_diff(e) > 10]

            new_state = dict(state)
            new_state["sync_token"] = result["sync_token"]
            if message_number is not None:
                new_state["last_google_message_number"] = message_number
            if resource_id:
                new_state["last_google_resource_id"] = resource_id
            if channel_id:
                new_state["last_google_channel_id"] = channel_id
            await self._save_node_state(new_state)
            return {"events": events, "event_count": len(events)}

    @classmethod
    async def _register_watch_channel(
        cls,
        *,
        pool,
        user_id,
        workflow_id,
        node_id,
        webhook_id,
        webhook_url,
        credential,
        credential_id,
        config,
    ) -> Dict[str, Any]:
        access_token = await ensure_fresh_google_token(
            pool, credential_id, user_id, credential
        )

        # Stop a stale channel from a previous registration so re-saving the
        # workflow doesn't leak channels or cause duplicate notifications.
        existing = await get_watch_channel(pool, workflow_id, node_id)
        if existing and existing.get("channel_id") and existing.get("resource_id"):
            try:
                await calendar_stop_channel(
                    access_token, existing["channel_id"], existing["resource_id"]
                )
            except Exception as e:
                logger.warning(
                    f"[GoogleCalendarNode] Could not stop stale watch channel: {e}"
                )

        calendar_id = (config or {}).get("calendar_id") or "primary"
        channel_id = str(uuid4())
        channel_token = (config or {}).get("signing_secret") or secrets.token_hex(32)
        sync_token = await calendar_get_sync_token(access_token, calendar_id)
        watch = await calendar_watch_events(
            access_token, calendar_id, channel_id, webhook_url, channel_token
        )
        await save_watch_channel(
            pool,
            webhook_id=webhook_id,
            user_id=user_id,
            workflow_id=workflow_id,
            node_id=node_id,
            provider="google_calendar",
            credential_id=credential_id,
            channel_id=channel_id,
            resource_id=watch.get("resourceId"),
            channel_token=channel_token,
            expires_at=_calendar_ms_to_datetime(watch.get("expiration")),
            watched_resource=calendar_id,
        )
        return {"signing_secret": channel_token, "calendar_sync_token": sync_token}

    @classmethod
    async def _stop_watch_channel(
        cls, *, pool, workflow_id, node_id, credential, config, channel_row
    ) -> None:
        if not credential:
            return
        cred_id = channel_row.get("credential_id")
        row_user = channel_row.get("user_id")
        access_token = await ensure_fresh_google_token(
            pool,
            str(cred_id) if cred_id else None,
            str(row_user) if row_user else None,
            credential,
        )
        if channel_row.get("channel_id") and channel_row.get("resource_id"):
            await calendar_stop_channel(
                access_token, channel_row["channel_id"], channel_row["resource_id"]
            )

    @classmethod
    async def renew_watch_channel(cls, pool, channel_row: Dict[str, Any]) -> None:
        """Re-subscribe an expiring Calendar watch channel (called by the cron)."""
        from utils.credential_loader import load_credential
        from utils.webhook_tunnel import get_webhook_url

        user_id = str(channel_row["user_id"])
        cred_id = channel_row.get("credential_id")
        credential_id = str(cred_id) if cred_id else None
        credential = await load_credential(pool, user_id, credential_id)
        if not credential:
            logger.warning(
                f"[GoogleCalendarNode] Cannot renew channel {channel_row.get('id')}: "
                f"credential unavailable"
            )
            return

        access_token = await ensure_fresh_google_token(
            pool, credential_id, user_id, credential
        )
        calendar_id = channel_row.get("watched_resource") or "primary"
        webhook_url = get_webhook_url(str(channel_row["webhook_id"]))
        new_channel_id = str(uuid4())
        watch = await calendar_watch_events(
            access_token,
            calendar_id,
            new_channel_id,
            webhook_url,
            channel_row["channel_token"],
        )

        if channel_row.get("channel_id") and channel_row.get("resource_id"):
            try:
                await calendar_stop_channel(
                    access_token,
                    channel_row["channel_id"],
                    channel_row["resource_id"],
                )
            except Exception as e:
                logger.warning(f"[GoogleCalendarNode] Could not stop old channel: {e}")

        await update_channel_subscription(
            pool,
            channel_row["id"],
            channel_id=new_channel_id,
            resource_id=watch.get("resourceId"),
            expires_at=_calendar_ms_to_datetime(watch.get("expiration")),
        )

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        """Calendar notifications are wake-up signals — run execute() to fetch."""
        return None

    @classmethod
    def verify_webhook_signature(
        cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]
    ) -> bool:
        """Verify the ``X-Goog-Channel-Token`` echoed by Google."""
        token = (config or {}).get("signing_secret")
        if not token:
            return False
        return hmac.compare_digest(token, headers.get("x-goog-channel-token", ""))

    @classmethod
    def handle_webhook_handshake(cls, body: bytes, headers: Dict[str, str], config=None):
        """Acknowledge Google's initial ``sync`` message without firing a run."""
        if headers.get("x-goog-resource-state") == "sync":
            return {}
        return None

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute Google Calendar operation.

        Args:
            inputs: Output data from upstream nodes

        Returns:
            Dict containing Google Calendar operation results
        """
        logger.info(f"[GoogleCalendarNode] Executing node {self.node_id}")

        node_config = self.config
        if not node_config:
            raise ValueError(
                f"[GoogleCalendarNode] Configuration is required but not provided for node {self.node_id}"
            )

        if not isinstance(node_config, GoogleCalendarNodeConfig):
            raise ValueError(
                f"[GoogleCalendarNode] Invalid config type: {type(node_config)}, expected GoogleCalendarNodeConfig"
            )

        config = node_config.config
        credentials = node_config.credentials

        # Trigger operations — fetch changed events since the stored sync token
        if isinstance(
            config,
            (
                GoogleCalendarOnEventConfig,
                GoogleCalendarOnEventActiveConfig,
                GoogleCalendarOnEventCancelledConfig,
                GoogleCalendarOnEventCreatedConfig,
                GoogleCalendarOnEventUpdatedConfig,
                GoogleCalendarOnEventTentativeConfig,
            ),
        ):
            output = await self._trigger_on_calendar_event(config, credentials)
            await self.emit(output)
            return output

        if not credentials:
            raise ValueError(
                f"[GoogleCalendarNode] Google Calendar credentials are required but not provided. "
                f"Please connect a Google account in the node's credentials tab."
            )

        access_token = await self._ensure_fresh_token(credentials)

        # Execute operation based on config type
        if isinstance(config, GoogleCalendarListEventsConfig):
            output = await self._list_events(config, access_token)
        elif isinstance(config, GoogleCalendarGetEventConfig):
            output = await self._get_event(config, access_token)
        elif isinstance(config, GoogleCalendarCreateEventConfig):
            output = await self._create_event(config, access_token)
        elif isinstance(config, GoogleCalendarUpdateEventConfig):
            output = await self._update_event(config, access_token)
        elif isinstance(config, GoogleCalendarDeleteEventConfig):
            output = await self._delete_event(config, access_token)
        elif isinstance(config, GoogleCalendarQuickAddConfig):
            output = await self._quick_add(config, access_token)
        elif isinstance(config, GoogleCalendarGetInstancesConfig):
            output = await self._get_instances(config, access_token)
        elif isinstance(config, GoogleCalendarMoveEventConfig):
            output = await self._move_event(config, access_token)
        elif isinstance(config, GoogleCalendarQueryFreebusyConfig):
            output = await self._query_freebusy(config, access_token)
        elif isinstance(config, GoogleCalendarListCalendarsConfig):
            output = await self._list_calendars_op(config, access_token)
        elif isinstance(config, GoogleCalendarGetCalendarConfig):
            output = await self._get_calendar(config, access_token)
        elif isinstance(config, GoogleCalendarCreateCalendarConfig):
            output = await self._create_calendar(config, access_token)
        elif isinstance(config, GoogleCalendarClearCalendarConfig):
            output = await self._clear_calendar(config, access_token)
        else:
            raise ValueError(f"Unexpected config type: {type(config)}")

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

    async def _ensure_fresh_token(
        self, credentials: GoogleCalendarOAuthCredential
    ) -> str:
        """Return a valid Google Calendar access token, refreshing + persisting if expired."""
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

    async def _list_events(
        self, config: GoogleCalendarListEventsConfig, access_token: str
    ) -> Dict[str, Any]:
        """List events from a calendar."""
        logger.info(
            f"[GoogleCalendarNode] Listing events from calendar {config.calendar_id}"
        )

        url = f"{GOOGLE_CALENDAR_API_BASE}/calendars/{config.calendar_id}/events"
        params: Dict[str, Any] = {
            "singleEvents": True,
            "orderBy": "startTime",
        }

        if config.time_min:
            params["timeMin"] = config.time_min
        if config.time_max:
            params["timeMax"] = config.time_max
        if config.max_results:
            params["maxResults"] = config.max_results
        if config.search_query:
            params["q"] = config.search_query

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}, params=params
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleCalendarNode] List events failed: {error_msg}")
                raise ValueError(f"Google Calendar API error: {error_msg}")

            data = response.json()
            events = data.get("items", [])

            # Simplify event data for output
            simplified_events = []
            for event in events:
                simplified_events.append(
                    {
                        "id": event.get("id"),
                        "summary": event.get("summary"),
                        "description": event.get("description"),
                        "location": event.get("location"),
                        "start": event.get("start"),
                        "end": event.get("end"),
                        "status": event.get("status"),
                        "htmlLink": event.get("htmlLink"),
                        "creator": event.get("creator"),
                        "organizer": event.get("organizer"),
                        "attendees": event.get("attendees", []),
                    }
                )

            output = {
                "type": "google_calendar",
                "operation": "list_calendar_events",
                "calendar_id": config.calendar_id,
                "event_count": len(simplified_events),
                "events": simplified_events,
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[GoogleCalendarNode] Listed {len(simplified_events)} events")
            return output

    async def _get_event(
        self, config: GoogleCalendarGetEventConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get a single event by ID."""
        logger.info(f"[GoogleCalendarNode] Getting event {config.event_id}")

        url = f"{GOOGLE_CALENDAR_API_BASE}/calendars/{config.calendar_id}/events/{config.event_id}"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleCalendarNode] Get event failed: {error_msg}")
                raise ValueError(f"Google Calendar API error: {error_msg}")

            event = response.json()

            output = {
                "type": "google_calendar",
                "operation": "fetch_calendar_event",
                "calendar_id": config.calendar_id,
                "event": {
                    "id": event.get("id"),
                    "summary": event.get("summary"),
                    "description": event.get("description"),
                    "location": event.get("location"),
                    "start": event.get("start"),
                    "end": event.get("end"),
                    "status": event.get("status"),
                    "htmlLink": event.get("htmlLink"),
                    "creator": event.get("creator"),
                    "organizer": event.get("organizer"),
                    "attendees": event.get("attendees", []),
                    "recurrence": event.get("recurrence"),
                    "reminders": event.get("reminders"),
                },
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[GoogleCalendarNode] Retrieved event: {event.get('summary')}")
            return output

    async def _create_event(
        self, config: GoogleCalendarCreateEventConfig, access_token: str
    ) -> Dict[str, Any]:
        """Create a new event."""
        logger.info(f"[GoogleCalendarNode] Creating event: {config.summary}")

        url = f"{GOOGLE_CALENDAR_API_BASE}/calendars/{config.calendar_id}/events"

        # Build event body
        event_body: Dict[str, Any] = {
            "summary": config.summary,
            "start": {"dateTime": config.start_time},
            "end": {"dateTime": config.end_time},
        }

        if config.timezone:
            event_body["start"]["timeZone"] = config.timezone
            event_body["end"]["timeZone"] = config.timezone

        if config.description:
            event_body["description"] = config.description

        if config.location:
            event_body["location"] = config.location

        if config.attendees:
            attendee_emails = [
                email.strip() for email in config.attendees.split(",") if email.strip()
            ]
            event_body["attendees"] = [{"email": email} for email in attendee_emails]

        params = {}
        if config.send_notifications is not None:
            params["sendUpdates"] = "all" if config.send_notifications else "none"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                params=params,
                json=event_body,
            )

            if response.status_code not in (200, 201):
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleCalendarNode] Create event failed: {error_msg}")
                raise ValueError(f"Google Calendar API error: {error_msg}")

            event = response.json()

            output = {
                "type": "google_calendar",
                "operation": "create_calendar_event",
                "calendar_id": config.calendar_id,
                "event_id": event.get("id"),
                "event": {
                    "id": event.get("id"),
                    "summary": event.get("summary"),
                    "description": event.get("description"),
                    "location": event.get("location"),
                    "start": event.get("start"),
                    "end": event.get("end"),
                    "htmlLink": event.get("htmlLink"),
                    "status": event.get("status"),
                },
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[GoogleCalendarNode] Created event: {event.get('id')}")
            return output

    async def _update_event(
        self, config: GoogleCalendarUpdateEventConfig, access_token: str
    ) -> Dict[str, Any]:
        """Update an existing event."""
        logger.info(f"[GoogleCalendarNode] Updating event {config.event_id}")

        # First, get the existing event
        get_url = f"{GOOGLE_CALENDAR_API_BASE}/calendars/{config.calendar_id}/events/{config.event_id}"

        async with httpx.AsyncClient() as client:
            get_response = await client.get(
                get_url,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if get_response.status_code != 200:
                error_data = get_response.json()
                error_msg = error_data.get("error", {}).get(
                    "message", get_response.text
                )
                logger.error(
                    f"[GoogleCalendarNode] Get event for update failed: {error_msg}"
                )
                raise ValueError(f"Google Calendar API error: {error_msg}")

            existing_event = get_response.json()

            # Update only provided fields
            if config.summary:
                existing_event["summary"] = config.summary
            if config.description is not None:
                existing_event["description"] = config.description
            if config.location is not None:
                existing_event["location"] = config.location

            if config.start_time:
                existing_event["start"] = {"dateTime": config.start_time}
                if config.timezone:
                    existing_event["start"]["timeZone"] = config.timezone

            if config.end_time:
                existing_event["end"] = {"dateTime": config.end_time}
                if config.timezone:
                    existing_event["end"]["timeZone"] = config.timezone

            params = {}
            if config.send_notifications is not None:
                params["sendUpdates"] = "all" if config.send_notifications else "none"

            update_url = f"{GOOGLE_CALENDAR_API_BASE}/calendars/{config.calendar_id}/events/{config.event_id}"

            response = await client.put(
                update_url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                params=params,
                json=existing_event,
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleCalendarNode] Update event failed: {error_msg}")
                raise ValueError(f"Google Calendar API error: {error_msg}")

            event = response.json()

            output = {
                "type": "google_calendar",
                "operation": "update_calendar_event",
                "calendar_id": config.calendar_id,
                "event_id": event.get("id"),
                "event": {
                    "id": event.get("id"),
                    "summary": event.get("summary"),
                    "description": event.get("description"),
                    "location": event.get("location"),
                    "start": event.get("start"),
                    "end": event.get("end"),
                    "htmlLink": event.get("htmlLink"),
                    "status": event.get("status"),
                },
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[GoogleCalendarNode] Updated event: {event.get('id')}")
            return output

    async def _delete_event(
        self, config: GoogleCalendarDeleteEventConfig, access_token: str
    ) -> Dict[str, Any]:
        """Delete an event."""
        logger.info(f"[GoogleCalendarNode] Deleting event {config.event_id}")

        url = f"{GOOGLE_CALENDAR_API_BASE}/calendars/{config.calendar_id}/events/{config.event_id}"

        params = {}
        if config.send_notifications is not None:
            params["sendUpdates"] = "all" if config.send_notifications else "none"

        async with httpx.AsyncClient() as client:
            response = await client.delete(
                url, headers={"Authorization": f"Bearer {access_token}"}, params=params
            )

            # 204 No Content is success for delete
            if response.status_code not in (200, 204):
                error_data = response.json() if response.text else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleCalendarNode] Delete event failed: {error_msg}")
                raise ValueError(f"Google Calendar API error: {error_msg}")

            output = {
                "type": "google_calendar",
                "operation": "delete_calendar_event",
                "calendar_id": config.calendar_id,
                "event_id": config.event_id,
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[GoogleCalendarNode] Deleted event: {config.event_id}")
            return output

    async def _quick_add(
        self, config: GoogleCalendarQuickAddConfig, access_token: str
    ) -> Dict[str, Any]:
        """Create an event from natural language text using quickAdd API."""
        logger.info(f"[GoogleCalendarNode] Quick adding event: {config.text}")

        url = (
            f"{GOOGLE_CALENDAR_API_BASE}/calendars/{config.calendar_id}/events/quickAdd"
        )

        params = {"text": config.text}
        if config.send_notifications is not None:
            params["sendUpdates"] = "all" if config.send_notifications else "none"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url, headers={"Authorization": f"Bearer {access_token}"}, params=params
            )

            if response.status_code not in (200, 201):
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleCalendarNode] Quick add failed: {error_msg}")
                raise ValueError(f"Google Calendar API error: {error_msg}")

            event = response.json()

            output = {
                "type": "google_calendar",
                "operation": "create_event_from_text",
                "calendar_id": config.calendar_id,
                "input_text": config.text,
                "event_id": event.get("id"),
                "event": {
                    "id": event.get("id"),
                    "summary": event.get("summary"),
                    "description": event.get("description"),
                    "location": event.get("location"),
                    "start": event.get("start"),
                    "end": event.get("end"),
                    "htmlLink": event.get("htmlLink"),
                    "status": event.get("status"),
                },
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[GoogleCalendarNode] Quick added event: {event.get('id')}")
            return output

    async def _get_instances(
        self, config: GoogleCalendarGetInstancesConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get instances of a recurring event."""
        logger.info(
            f"[GoogleCalendarNode] Getting instances of event {config.event_id}"
        )

        url = f"{GOOGLE_CALENDAR_API_BASE}/calendars/{config.calendar_id}/events/{config.event_id}/instances"

        params: Dict[str, Any] = {}
        if config.time_min:
            params["timeMin"] = config.time_min
        if config.time_max:
            params["timeMax"] = config.time_max
        if config.max_results:
            params["maxResults"] = config.max_results

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}, params=params
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleCalendarNode] Get instances failed: {error_msg}")
                raise ValueError(f"Google Calendar API error: {error_msg}")

            data = response.json()
            instances = data.get("items", [])

            simplified_instances = []
            for instance in instances:
                simplified_instances.append(
                    {
                        "id": instance.get("id"),
                        "recurringEventId": instance.get("recurringEventId"),
                        "summary": instance.get("summary"),
                        "description": instance.get("description"),
                        "location": instance.get("location"),
                        "start": instance.get("start"),
                        "end": instance.get("end"),
                        "status": instance.get("status"),
                        "htmlLink": instance.get("htmlLink"),
                    }
                )

            output = {
                "type": "google_calendar",
                "operation": "fetch_recurring_event_instances",
                "calendar_id": config.calendar_id,
                "recurring_event_id": config.event_id,
                "instance_count": len(simplified_instances),
                "instances": simplified_instances,
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(
                f"[GoogleCalendarNode] Found {len(simplified_instances)} instances"
            )
            return output

    async def _move_event(
        self, config: GoogleCalendarMoveEventConfig, access_token: str
    ) -> Dict[str, Any]:
        """Move an event to another calendar."""
        logger.info(
            f"[GoogleCalendarNode] Moving event {config.event_id} to {config.destination_calendar_id}"
        )

        url = f"{GOOGLE_CALENDAR_API_BASE}/calendars/{config.calendar_id}/events/{config.event_id}/move"

        params = {"destination": config.destination_calendar_id}
        if config.send_notifications is not None:
            params["sendUpdates"] = "all" if config.send_notifications else "none"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url, headers={"Authorization": f"Bearer {access_token}"}, params=params
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleCalendarNode] Move event failed: {error_msg}")
                raise ValueError(f"Google Calendar API error: {error_msg}")

            event = response.json()

            output = {
                "type": "google_calendar",
                "operation": "move_event_to_calendar",
                "source_calendar_id": config.calendar_id,
                "destination_calendar_id": config.destination_calendar_id,
                "event_id": event.get("id"),
                "event": {
                    "id": event.get("id"),
                    "summary": event.get("summary"),
                    "description": event.get("description"),
                    "location": event.get("location"),
                    "start": event.get("start"),
                    "end": event.get("end"),
                    "htmlLink": event.get("htmlLink"),
                    "status": event.get("status"),
                },
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[GoogleCalendarNode] Moved event: {event.get('id')}")
            return output

    async def _query_freebusy(
        self, config: GoogleCalendarQueryFreebusyConfig, access_token: str
    ) -> Dict[str, Any]:
        """Query free/busy information for calendars."""
        calendar_ids = [
            cid.strip() for cid in config.calendar_ids.split(",") if cid.strip()
        ]
        logger.info(
            f"[GoogleCalendarNode] Querying freebusy for {len(calendar_ids)} calendars"
        )

        url = f"{GOOGLE_CALENDAR_API_BASE}/freeBusy"

        request_body = {
            "timeMin": config.time_min,
            "timeMax": config.time_max,
            "items": [{"id": cid} for cid in calendar_ids],
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=request_body,
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleCalendarNode] Freebusy query failed: {error_msg}")
                raise ValueError(f"Google Calendar API error: {error_msg}")

            data = response.json()

            # Process calendars response
            calendars_result = {}
            for cal_id, cal_data in data.get("calendars", {}).items():
                calendars_result[cal_id] = {
                    "busy": cal_data.get("busy", []),
                    "errors": cal_data.get("errors", []),
                }

            output = {
                "type": "google_calendar",
                "operation": "query_calendar_availability",
                "time_min": config.time_min,
                "time_max": config.time_max,
                "calendars": calendars_result,
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(
                f"[GoogleCalendarNode] Freebusy query completed for {len(calendars_result)} calendars"
            )
            return output

    async def _list_calendars_op(
        self, config: GoogleCalendarListCalendarsConfig, access_token: str
    ) -> Dict[str, Any]:
        """List all calendars accessible to the user (as a workflow operation)."""
        logger.info(f"[GoogleCalendarNode] Listing calendars (operation)")

        url = f"{GOOGLE_CALENDAR_API_BASE}/users/me/calendarList"

        params: Dict[str, Any] = {}
        if config.show_hidden:
            params["showHidden"] = True
        if config.show_deleted:
            params["showDeleted"] = True

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}, params=params
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleCalendarNode] List calendars failed: {error_msg}")
                raise ValueError(f"Google Calendar API error: {error_msg}")

            data = response.json()
            calendars = data.get("items", [])

            simplified_calendars = []
            for cal in calendars:
                simplified_calendars.append(
                    {
                        "id": cal.get("id"),
                        "summary": cal.get("summary"),
                        "description": cal.get("description"),
                        "location": cal.get("location"),
                        "timeZone": cal.get("timeZone"),
                        "primary": cal.get("primary", False),
                        "accessRole": cal.get("accessRole"),
                        "backgroundColor": cal.get("backgroundColor"),
                        "foregroundColor": cal.get("foregroundColor"),
                        "selected": cal.get("selected"),
                        "hidden": cal.get("hidden"),
                        "deleted": cal.get("deleted"),
                    }
                )

            output = {
                "type": "google_calendar",
                "operation": "list_user_calendars",
                "calendar_count": len(simplified_calendars),
                "calendars": simplified_calendars,
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(
                f"[GoogleCalendarNode] Listed {len(simplified_calendars)} calendars"
            )
            return output

    async def _get_calendar(
        self, config: GoogleCalendarGetCalendarConfig, access_token: str
    ) -> Dict[str, Any]:
        """Get metadata for a specific calendar."""
        logger.info(f"[GoogleCalendarNode] Getting calendar {config.calendar_id}")

        url = f"{GOOGLE_CALENDAR_API_BASE}/calendars/{config.calendar_id}"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleCalendarNode] Get calendar failed: {error_msg}")
                raise ValueError(f"Google Calendar API error: {error_msg}")

            cal = response.json()

            output = {
                "type": "google_calendar",
                "operation": "fetch_calendar_metadata",
                "calendar": {
                    "id": cal.get("id"),
                    "summary": cal.get("summary"),
                    "description": cal.get("description"),
                    "location": cal.get("location"),
                    "timeZone": cal.get("timeZone"),
                    "conferenceProperties": cal.get("conferenceProperties"),
                },
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[GoogleCalendarNode] Got calendar: {cal.get('summary')}")
            return output

    async def _create_calendar(
        self, config: GoogleCalendarCreateCalendarConfig, access_token: str
    ) -> Dict[str, Any]:
        """Create a new calendar."""
        logger.info(f"[GoogleCalendarNode] Creating calendar: {config.summary}")

        url = f"{GOOGLE_CALENDAR_API_BASE}/calendars"

        calendar_body: Dict[str, Any] = {
            "summary": config.summary,
        }

        if config.description:
            calendar_body["description"] = config.description
        if config.timezone:
            calendar_body["timeZone"] = config.timezone
        if config.location:
            calendar_body["location"] = config.location

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=calendar_body,
            )

            if response.status_code not in (200, 201):
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(
                    f"[GoogleCalendarNode] Create calendar failed: {error_msg}"
                )
                raise ValueError(f"Google Calendar API error: {error_msg}")

            cal = response.json()

            output = {
                "type": "google_calendar",
                "operation": "create_new_calendar",
                "calendar_id": cal.get("id"),
                "calendar": {
                    "id": cal.get("id"),
                    "summary": cal.get("summary"),
                    "description": cal.get("description"),
                    "location": cal.get("location"),
                    "timeZone": cal.get("timeZone"),
                },
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[GoogleCalendarNode] Created calendar: {cal.get('id')}")
            return output

    async def _clear_calendar(
        self, config: GoogleCalendarClearCalendarConfig, access_token: str
    ) -> Dict[str, Any]:
        """Clear all events from a calendar."""
        logger.info(f"[GoogleCalendarNode] Clearing calendar {config.calendar_id}")

        url = f"{GOOGLE_CALENDAR_API_BASE}/calendars/{config.calendar_id}/clear"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            # 204 No Content is success for clear
            if response.status_code not in (200, 204):
                error_data = response.json() if response.text else {}
                error_msg = error_data.get("error", {}).get("message", response.text)
                logger.error(f"[GoogleCalendarNode] Clear calendar failed: {error_msg}")
                raise ValueError(f"Google Calendar API error: {error_msg}")

            output = {
                "type": "google_calendar",
                "operation": "clear_calendar_events",
                "calendar_id": config.calendar_id,
                "timestamp": time.time(),
                "status": "success",
            }

            logger.info(f"[GoogleCalendarNode] Cleared calendar: {config.calendar_id}")
            return output
