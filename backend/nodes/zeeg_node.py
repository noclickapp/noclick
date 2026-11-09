"""Zeeg v2 scheduling, booking and internal-note automation using a pasted API token.

Each operation issues one documented request; responses retain provider fields and pagination.
Contract: https://developer.zeeg.me/openapi.yaml (2.0.0).
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class ZeegAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Zeeg API Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://app.zeeg.me/account/settings/api-access",
        "x-credential-instructions": "Create an API token in Zeeg Account Settings → API Access and paste it here. Enable events:read/write, event_types:read/write, schedules:read and notes:read/write for the operations you use. Availability needs timetable and booking needs booking; both require a paid Zeeg plan. The token is sent only to api.zeeg.me."
    })
    credential_type: Literal["zeeg_api_token"] = Field("zeeg_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., repr=False, title="API token", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value) or value.lower().startswith("bearer "):
            raise ValueError("Paste the token without the Bearer prefix or whitespace")
        if any(ord(c) > 126 or ord(c) < 33 for c in value):
            raise ValueError("Use a printable API token")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("event_id", "invitee_id", "page_id", "note_id", check_fields=False)
    @classmethod
    def identifier(cls, value):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,199}", value):
            raise ValueError("Paste a single Zeeg ID, not a URL")
        return value

    @field_validator("timeZone", check_fields=False)
    @classmethod
    def timezone(cls, value):
        if value is not None:
            try:
                ZoneInfo(value)
            except (ValueError, ZoneInfoNotFoundError):
                raise ValueError("Use an IANA time zone such as Europe/Paris") from None
        return value

    @field_validator("start", check_fields=False)
    @classmethod
    def clock(cls, value):
        if not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value):
            raise ValueError("Use HH:mm in 24-hour time")
        return value


class CheckConnection(Input):
    """Identify the token owner with the authenticated user's email."""
    operation: Literal["check_connection"] = "check_connection"


class Page(Input):
    count: int = Field(20, ge=1, le=100, description="Results per page. Pagination is returned unchanged; request the next page explicitly.")
    page: int = Field(1, ge=1)


class ListEvents(Page):
    """List one page of scheduled events (events:read or events:write)."""
    operation: Literal["list_events"] = "list_events"
    sort: Literal["asc", "desc"] = "asc"
    status: Literal["confirmed", "cancelled"] | None = None
    minStartTime: datetime | None = None
    maxStartTime: datetime | None = None
    scope: Literal["all"] | None = Field(None, description="all includes the whole workspace; omitted means events you participate in.")
    userSlug: str | None = None
    hostEmail: str | None = None
    inviteeEmail: str | None = None
    teamSlug: str | None = None
    keyword: str | None = None
    eventTypeId: str | None = None


class EventInput(Input):
    event_id: str = Field(..., title="Scheduled event ID", description="uuid from a scheduled event, including the zg- prefix.")


class GetEvent(EventInput):
    """Get one scheduled event."""
    operation: Literal["get_event"] = "get_event"


class CancelEvent(EventInput):
    """Cancel an event, notifying its invitees (events:write)."""
    operation: Literal["cancel_event"] = "cancel_event"
    cancellationReason: str | None = Field(None, max_length=512)


class RescheduleEvent(EventInput):
    """Move a booking to an available time (events:write); check availability first."""
    operation: Literal["reschedule_event"] = "reschedule_event"
    date: date
    start: str
    timeZone: str | None = None
    duration: int | None = Field(None, ge=1)
    reason: str | None = Field(None, max_length=512)


class InviteeInput(Input):
    invitee_id: str = Field(..., description="invitees[].uuid from the scheduled event, not the event ID.")


class CancelInvitee(InviteeInput):
    """Cancel just one invitee (events:write)."""
    operation: Literal["cancel_invitee"] = "cancel_invitee"
    cancellationReason: str | None = Field(None, max_length=512)


class MarkNoShow(InviteeInput):
    """Mark an invitee as a no-show (events:write)."""
    operation: Literal["mark_no_show"] = "mark_no_show"


class UndoNoShow(InviteeInput):
    """Withdraw a no-show marking (events:write)."""
    operation: Literal["undo_no_show"] = "undo_no_show"


class ListSchedulingPages(Page):
    """List scheduling pages (event_types:read or event_types:write)."""
    operation: Literal["list_scheduling_pages"] = "list_scheduling_pages"
    userSlug: str | None = None
    email: str | None = None
    publicId: str | None = None

    @model_validator(mode="after")
    def one_owner(self):
        if sum(v is not None for v in (self.userSlug, self.email, self.publicId)) > 1:
            raise ValueError("Choose only one owner filter")
        return self


class SchedulingPageInput(Input):
    page_id: str = Field(..., description="uuid returned by List scheduling pages.")


class GetSchedulingPage(SchedulingPageInput):
    """Get scheduling-page details and booking requirements."""
    operation: Literal["get_scheduling_page"] = "get_scheduling_page"


class DuplicateSchedulingPage(SchedulingPageInput):
    """Create a new inactive copy; every execution creates another copy (event_types:write)."""
    operation: Literal["duplicate_scheduling_page"] = "duplicate_scheduling_page"


class ToggleSchedulingPage(SchedulingPageInput):
    """Toggle active/inactive status; each execution reverses it (event_types:write)."""
    operation: Literal["toggle_scheduling_page"] = "toggle_scheduling_page"


class GetQuestions(SchedulingPageInput):
    """Read booking-form questions, including required question IDs."""
    operation: Literal["get_questions"] = "get_questions"


class GetAvailability(SchedulingPageInput):
    """Read available booking slots (timetable scope and a paid Zeeg plan)."""
    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "paid", "x-tier-label": "Zeeg paid plan"})
    operation: Literal["get_availability"] = "get_availability"
    startDate: date
    endDate: date
    timeZone: str = "UTC"
    duration: int | None = Field(None, ge=1)
    hostEmail: str | None = None
    hostSlug: str | None = None
    seats: int | None = Field(None, ge=1)
    locationKey: str | None = None

    @model_validator(mode="after")
    def ordered(self):
        if self.endDate < self.startDate:
            raise ValueError("End date must not precede start date")
        return self


class LocationOptions(Input):
    address: str | None = None
    details: str | None = None
    callType: str | None = None


class QuestionAnswer(Input):
    question_id: int
    answer: str | list[str]


class CreateBooking(Input):
    """Book a scheduling page (booking scope, paid plan). Check availability and required questions first; each execution creates a booking."""
    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "paid", "x-tier-label": "Zeeg paid plan"})
    operation: Literal["create_booking"] = "create_booking"
    eventTypeId: str = Field(..., min_length=1, description="ID returned by List scheduling pages.")
    date: date
    start: str
    name: str = Field(..., min_length=1)
    email: str = Field(..., min_length=1)
    timeZone: str
    duration: int | None = Field(None, ge=1)
    phone: str | None = None
    guests: list[str] | None = None
    location: Literal["IN_PERSON", "PHONE_CALL", "CUSTOM", "GOOGLE_MEET", "MICROSOFT_TEAMS", "MICROSOFT_SKYPE", "ZOOM", "WEBEX", "DEMODESK", "ALFAVIEW", "WHATSAPP", "WHEREBY", "JITSI"] | None = Field(None, description="Required if the page offers locations; use one it offers.")
    locationOptions: LocationOptions | None = None
    locationKey: str | None = None
    question_answers: list[QuestionAnswer] | None = None
    customQueryParams: dict[str, str] | None = None
    hostEmail: str | None = None
    hostSlug: str | None = None

    @model_validator(mode="after")
    def location_fields(self):
        if self.location == "PHONE_CALL" and (not self.phone or not self.locationOptions or not self.locationOptions.callType):
            raise ValueError("Phone meetings require phone and locationOptions.callType")
        if self.location == "IN_PERSON" and (not self.locationOptions or not self.locationOptions.address or not self.locationOptions.details):
            raise ValueError("In-person meetings require locationOptions.address and details")
        return self


class ListSchedules(Page):
    """List a user's availability schedules (schedules:read or schedules:write)."""
    operation: Literal["list_schedules"] = "list_schedules"
    email: str
    includeSchedulingPages: StrictBool = False


class GetDefaultSchedule(Input):
    """Get a user's default availability schedule."""
    operation: Literal["get_default_schedule"] = "get_default_schedule"
    email: str
    includeSchedulingPages: StrictBool = False


class ListNotes(EventInput):
    """List internal notes attached to an event (notes:read or notes:write)."""
    operation: Literal["list_notes"] = "list_notes"


class NoteInput(Input):
    note_id: str = Field(..., description="Numeric ID or short uuid of the note.")


class GetNote(NoteInput):
    """Read one internal note."""
    operation: Literal["get_note"] = "get_note"


class CreateNote(EventInput):
    """Attach an internal note to an event (notes:write); each execution creates a note."""
    operation: Literal["create_note"] = "create_note"
    note: str = Field(..., min_length=1, max_length=500)


class UpdateNote(NoteInput):
    """Replace an internal note's content (notes:write)."""
    operation: Literal["update_note"] = "update_note"
    note: str = Field(..., min_length=1, max_length=500)


class DeleteNote(NoteInput):
    """Permanently delete a note (notes:write)."""
    operation: Literal["delete_note"] = "delete_note"


class CreateSchedulingPage(Input):
    """Create a one-on-one page with Zeeg's default 30-minute duration (event_types:write)."""
    operation: Literal["create_scheduling_page"] = "create_scheduling_page"
    title: str = Field(..., min_length=1, max_length=100)
    slug: str | None = None
    description: str | None = Field(None, max_length=4000)
    isActive: StrictBool = Field(False, description="Create inactive by default; activate when the page is ready.")


class UpdateSchedulingPage(SchedulingPageInput):
    """Edit page title, description or language (event_types:write). Omitted fields retain their values."""
    operation: Literal["update_scheduling_page"] = "update_scheduling_page"
    title: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=4000)
    language: Literal["en", "de", "de-du", "nl", "fi", "es", "fr", "pl", "da", "sv", "it"] | None = None

    @model_validator(mode="after")
    def changes(self):
        if any(getattr(self, key) is None for key in self.model_fields_set.intersection({"title", "language"})):
            raise ValueError("Title and language cannot be null")
        if not self.model_fields_set.intersection({"title", "description", "language"}):
            raise ValueError("Provide a field to update")
        return self


ZeegConfig = Annotated[Union[CheckConnection, ListEvents, GetEvent, CancelEvent, RescheduleEvent,
    CancelInvitee, MarkNoShow, UndoNoShow, ListSchedulingPages, GetSchedulingPage,
    DuplicateSchedulingPage, ToggleSchedulingPage, GetQuestions, GetAvailability, CreateBooking,
    ListSchedules, GetDefaultSchedule, ListNotes, GetNote, CreateNote, UpdateNote, DeleteNote,
    CreateSchedulingPage, UpdateSchedulingPage], Field(discriminator="operation")]


class ZeegFullConfig(NodeConfig[ZeegConfig, ZeegAPITokenCredential]):
    pass


# operation -> HTTP method, fixed route template, local path parameter.
ROUTES = {
    "check_connection": ("GET", "/whoami", None),
    "list_events": ("GET", "/scheduled-events", None),
    "get_event": ("GET", "/scheduled-events/{id}", "event_id"),
    "cancel_event": ("PUT", "/scheduled-events/{id}/cancel", "event_id"),
    "reschedule_event": ("PUT", "/scheduled-events/{id}/reschedule", "event_id"),
    "cancel_invitee": ("PUT", "/scheduled-invitees/{id}/cancel", "invitee_id"),
    "mark_no_show": ("POST", "/scheduled-invitees/{id}/no-show", "invitee_id"),
    "undo_no_show": ("DELETE", "/scheduled-invitees/{id}/no-show", "invitee_id"),
    "list_scheduling_pages": ("GET", "/event-types", None),
    "get_scheduling_page": ("GET", "/event-types/{id}", "page_id"),
    "duplicate_scheduling_page": ("POST", "/event-types/{id}/duplicate", "page_id"),
    "toggle_scheduling_page": ("PUT", "/event-types/{id}/status", "page_id"),
    "get_questions": ("GET", "/event-types/{id}/questions", "page_id"),
    "get_availability": ("GET", "/event-types/{id}/availability", "page_id"),
    "create_booking": ("POST", "/event", None),
    "list_schedules": ("GET", "/schedules", None),
    "get_default_schedule": ("GET", "/schedules/default", None),
    "list_notes": ("GET", "/notes/event/{id}", "event_id"),
    "get_note": ("GET", "/notes/{id}", "note_id"),
    "create_note": ("POST", "/notes", None),
    "update_note": ("PUT", "/notes/{id}", "note_id"),
    "delete_note": ("DELETE", "/notes/{id}", "note_id"),
    "create_scheduling_page": ("POST", "/event-types", None),
    "update_scheduling_page": ("PATCH", "/event-types/{id}", "page_id"),
}


class ZeegNode(WorkflowNode):
    integration_type = "automation-zeeg"
    connection_evidence = ConnectionEvidence(noun="Zeeg account", identity_operation="check_connection")

    @classmethod
    def get_config_model(cls):
        return ZeegFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Zeeg API token")
        config = self.config.config
        method, path, id_field = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        if id_field:
            path = path.format(id=quote(values.pop(id_field), safe=""))
        if config.operation == "create_note":
            values["uuid"] = values.pop("event_id")
            values["relation"] = "event"
        if config.operation == "create_scheduling_page":
            values["type"] = "ONE_ON_ONE"
        if config.operation == "update_scheduling_page":
            # Explicit null clears description; omitted fields keep their old value.
            values = config.model_dump(mode="json", exclude_unset=True, exclude={"operation", "page_id"})
        kwargs = {"params": {k: (str(v).lower() if isinstance(v, bool) else v) for k, v in values.items()}} if method == "GET" else ({"json": values} if values else {})
        token = self.config.credentials.api_token
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, "https://api.zeeg.me/v2" + path,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json"}, **kwargs)
        if not 200 <= response.status_code < 300:
            # Preserve a provider's rejection message for manual connection evidence.
            # Only the message is surfaced, bounded and with the supplied token removed.
            message = ""
            try:
                error = response.json()
                if isinstance(error, dict):
                    detail = error.get("error")
                    message = error.get("message") or (detail.get("message") if isinstance(detail, dict) else detail)
            except (ValueError, UnicodeError):
                pass
            message = message.replace(token, "[redacted]")[:1000] if isinstance(message, str) else ""
            raise ValueError(f"Zeeg request failed (HTTP {response.status_code})" + (": " + message if message else ""))
        if response.status_code == 204:
            return {"status": "success", "operation": config.operation, "http_status": 204, "acknowledged": True}
        if len(response.content) > 5_000_000 or response.headers.get("content-type", "").split(";")[0].strip() != "application/json":
            raise ValueError("Zeeg returned an unexpected response")
        body = response.json()
        if not isinstance(body, dict) or body.get("success") is False or body.get("error") or body.get("errors"):
            raise ValueError("Zeeg did not confirm the request")
        if config.operation == "check_connection" and (not isinstance(body.get("email"), str) or "@" not in body["email"]):
            raise ValueError("Zeeg returned no account identity")
        return {**body, "status": "success", "operation": config.operation, "http_status": response.status_code}
