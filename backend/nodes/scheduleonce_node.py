"""Scheduleonce (OnceHub v2) booking and contact automation.

Each operation uses one published endpoint and a manually supplied API key.
Lists return one provider page and never follow links or retry writes.
"""
from __future__ import annotations

from datetime import date, datetime
import re
from typing import Annotated, Literal, Union
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE_URL = "https://api.oncehub.com/v2"


class ScheduleonceAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Scheduleonce API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://help.oncehub.com/developers/overview/authentication/",
            "x-credential-instructions": "In OnceHub, open Account Integrations, then APIs & Webhooks. Create and copy an API key, then paste it below. NoClick reads your account's users to check the connection.",
        })
    credential_type: Literal["scheduleonce_api_key"] = Field("scheduleonce_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def remove_editor_metadata(cls, value):
        if isinstance(value, dict):
            return {k: v for k, v in value.items() if k != "credentialIds" and not k.endswith("__label")}
        return value

    @field_validator("*", mode="after")
    @classmethod
    def validate_values(cls, value, info):
        if value is None:
            return value
        if info.field_name in {"id", "before", "after", "new_host"}:
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}", value) or value in {".", ".."}:
                raise ValueError("Use a single OnceHub resource ID")
        if info.field_name.endswith(("_gt", "_lt")):
            date.fromisoformat(value)
        if info.field_name in {"start_time", "end_time"}:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.utcoffset() is None:
                raise ValueError("Include a timezone in the timestamp")
        if info.field_name == "guest_time_zone":
            try:
                ZoneInfo(value)
            except Exception:
                raise ValueError("Use an IANA timezone") from None
        return value

    @model_validator(mode="after")
    def validate_relationships(self):
        if getattr(self, "before", None) and getattr(self, "after", None):
            raise ValueError("Use either before or after, not both")
        start, end = getattr(self, "start_time", None), getattr(self, "end_time", None)
        if start and end:
            delta = datetime.fromisoformat(end.replace("Z", "+00:00")) - datetime.fromisoformat(start.replace("Z", "+00:00"))
            if not 0 < delta.total_seconds() <= 30 * 86400:
                raise ValueError("Availability end must be after start and within 30 days")
        if getattr(self, "operation", None) == "update_contact":
            if not self.model_dump(exclude={"operation", "id"}, exclude_none=True):
                raise ValueError("Provide at least one contact field to update")
        return self


class _Page(_Input):
    limit: int = Field(10, ge=1, le=100, description="Maximum records on this page. Use next_after to request the next page.")
    before: str | None = None
    after: str | None = None


class GuestForm(_Input):
    name: str = Field(..., min_length=1)
    email: str = Field(..., min_length=1)
    phone: str | None = None


class BookingLocation(_Input):
    type: Literal["physical", "virtual", "virtual_static", "guest_phone", "in_person_by_guest"]
    value: str | None = None


class ReassignLocation(_Input):
    type: Literal["virtual"] = "virtual"
    value: Literal["google_meet", "microsoft_teams", "webex", "gotomeeting", "zoom"]


class LinkSettings(_Input):
    host: str | None = None
    co_hosts: str | None = None
    duration_minutes: int | None = Field(None, ge=1)
    skip: list[str] | None = None


class UtmParams(_Input):
    source: str | None = None
    medium: str | None = None
    campaign: str | None = None
    term: str | None = None
    content: str | None = None


class CustomField(_Input):
    name: str
    value: str | int | float | bool | list | dict | None = None


class CheckConnectionConfig(_Input):
    """Validate API key."""
    operation: Literal["check_connection"] = Field("check_connection", json_schema_extra={"ui:hidden": True})


class ListBookingsConfig(_Page):
    """List all bookings."""
    operation: Literal["list_bookings"] = Field("list_bookings", json_schema_extra={"ui:hidden": True})
    status: str | None = Field(None, max_length=2000)
    owner: str | None = Field(None, max_length=2000)
    contact: str | None = Field(None, max_length=2000)
    booking_page: str | None = Field(None, max_length=2000)
    master_page: str | None = Field(None, max_length=2000)
    event_type: str | None = Field(None, max_length=2000)
    creation_time_gt: str | None = Field(None, max_length=2000, alias='creation_time.gt')
    creation_time_lt: str | None = Field(None, max_length=2000, alias='creation_time.lt')
    starting_time_gt: str | None = Field(None, max_length=2000, alias='starting_time.gt')
    starting_time_lt: str | None = Field(None, max_length=2000, alias='starting_time.lt')
    last_updated_time_gt: str | None = Field(None, max_length=2000, alias='last_updated_time.gt')
    last_updated_time_lt: str | None = Field(None, max_length=2000, alias='last_updated_time.lt')
    expand: str | None = Field(None, max_length=2000)
    booking_calendar: str | None = Field(None, max_length=2000)
    host: str | None = Field(None, max_length=2000)


class GetBookingConfig(_Input):
    """Get a single booking."""
    operation: Literal["get_booking"] = Field("get_booking", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, max_length=200)


class CancelBookingConfig(_Input):
    """Cancel a booking."""
    operation: Literal["cancel_booking"] = Field("cancel_booking", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, max_length=200)
    cancellation_reason: str | None = Field(None)
    send_cancellation_email: StrictBool | None = Field(None)


class RequestRescheduleConfig(_Input):
    """Request a reschedule."""
    operation: Literal["request_reschedule"] = Field("request_reschedule", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, max_length=200)
    reschedule_reason: str | None = Field(None)


class ReassignBookingConfig(_Input):
    """Reassign a booking."""
    operation: Literal["reassign_booking"] = Field("reassign_booking", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, max_length=200)
    new_host: str = Field(...)
    location: ReassignLocation | None = Field(None)


class MarkNoShowConfig(_Input):
    """Set a booking as no-show."""
    operation: Literal["mark_no_show"] = Field("mark_no_show", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, max_length=200)


class ListBookingCalendarsConfig(_Page):
    """List all booking calendars."""
    operation: Literal["list_booking_calendars"] = Field("list_booking_calendars", json_schema_extra={"ui:hidden": True})
    host: str | None = Field(None, max_length=2000)


class GetBookingCalendarConfig(_Input):
    """Get a single booking calendar."""
    operation: Literal["get_booking_calendar"] = Field("get_booking_calendar", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, max_length=200)


class GetTimeSlotsConfig(_Input):
    """Get available time slots for a booking calendar."""
    operation: Literal["get_time_slots"] = Field("get_time_slots", json_schema_extra={"ui:hidden": True})
    start_time: str | None = Field(None, max_length=2000)
    end_time: str | None = Field(None, max_length=2000)
    id: str = Field(..., min_length=1, max_length=200)


class ScheduleBookingConfig(_Input):
    """Book a time slot."""
    operation: Literal["schedule_booking"] = Field("schedule_booking", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, max_length=200)
    start_time: str = Field(...)
    guest_time_zone: str = Field(...)
    booking_form: GuestForm = Field(...)
    location: BookingLocation | None = Field(None)


class CreateOneTimeLinkConfig(_Input):
    """Create a one-time link."""
    operation: Literal["create_one_time_link"] = Field("create_one_time_link", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, max_length=200)
    hide_url_params: StrictBool | None = Field(None)
    booking_form: GuestForm | None = Field(None)
    utm_params: UtmParams | None = Field(None)
    booking_settings: LinkSettings | None = Field(None)


class ListBookingPagesConfig(_Page):
    """List all booking pages."""
    operation: Literal["list_booking_pages"] = Field("list_booking_pages", json_schema_extra={"ui:hidden": True})
    master_page: str | None = Field(None, max_length=2000)
    event_type: str | None = Field(None, max_length=2000)
    user: str | None = Field(None, max_length=2000)


class GetBookingPageConfig(_Input):
    """Get a single booking page."""
    operation: Literal["get_booking_page"] = Field("get_booking_page", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, max_length=200)


class ListEventTypesConfig(_Page):
    """List all event types."""
    operation: Literal["list_event_types"] = Field("list_event_types", json_schema_extra={"ui:hidden": True})


class GetEventTypeConfig(_Input):
    """Get a single event type."""
    operation: Literal["get_event_type"] = Field("get_event_type", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, max_length=200)


class ListUsersConfig(_Page):
    """List all users."""
    operation: Literal["list_users"] = Field("list_users", json_schema_extra={"ui:hidden": True})
    email: str | None = Field(None, max_length=2000)


class GetUserConfig(_Input):
    """Get a single user."""
    operation: Literal["get_user"] = Field("get_user", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, max_length=200)


class ListContactsConfig(_Page):
    """List all contacts."""
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})
    email: str | None = Field(None, max_length=2000)
    creation_time_lt: str | None = Field(None, max_length=2000, alias='creation_time.lt')
    last_updated_time_gt: str | None = Field(None, max_length=2000, alias='last_updated_time.gt')
    last_updated_time_lt: str | None = Field(None, max_length=2000, alias='last_updated_time.lt')
    creation_time_gt: str | None = Field(None, max_length=2000, alias='creation_time.gt')


class CreateContactConfig(_Input):
    """Add a new contact."""
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={"ui:hidden": True})
    owner: str | None = Field(None)
    status: Literal['Qualified', 'Sales qualified', 'Marketing qualified', 'Disqualified'] | None = Field(None)
    city: str | None = Field(None)
    company_size: str | None = Field(None)
    company: str | None = Field(None)
    country: str | None = Field(None)
    email: str | None = Field(None)
    employees: int | None = Field(None)
    first_name: str = Field(...)
    has_consent: StrictBool | None = Field(None)
    job_title: str | None = Field(None)
    last_name: str = Field(...)
    mobile_phone: str | None = Field(None)
    phone: str | None = Field(None)
    post_code: str | None = Field(None)
    salutation: str | None = Field(None)
    state: str | None = Field(None)
    street_address: str | None = Field(None)
    terms_of_sevice: StrictBool | None = Field(None)
    timezone: str | None = Field(None)
    custom_fields: list[CustomField] | None = Field(None)


class GetContactConfig(_Input):
    """Get a single contact."""
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, max_length=200)


class UpdateContactConfig(_Input):
    """Update a contact."""
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, max_length=200)
    first_name: str | None = Field(None)
    last_name: str | None = Field(None)
    owner: str | None = Field(None)
    status: Literal['Qualified', 'Sales qualified', 'Marketing qualified', 'Disqualified'] | None = Field(None)
    city: str | None = Field(None)
    company_size: str | None = Field(None)
    company: str | None = Field(None)
    country: str | None = Field(None)
    employees: int | None = Field(None)
    has_consent: StrictBool | None = Field(None)
    job_title: str | None = Field(None)
    phone: str | None = Field(None)
    post_code: str | None = Field(None)
    salutation: str | None = Field(None)
    state: str | None = Field(None)
    street_address: str | None = Field(None)
    terms_of_sevice: StrictBool | None = Field(None)
    timezone: str | None = Field(None)
    custom_fields: list[CustomField] | None = Field(None)


class DeleteContactConfig(_Input):
    """Delete a contact."""
    operation: Literal["delete_contact"] = Field("delete_contact", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, max_length=200)


class ListTeamsConfig(_Page):
    """List all teams."""
    operation: Literal["list_teams"] = Field("list_teams", json_schema_extra={"ui:hidden": True})
    user: str | None = Field(None, max_length=2000)


class GetTeamConfig(_Input):
    """Get a single team."""
    operation: Literal["get_team"] = Field("get_team", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, max_length=200)


ScheduleonceOperation = Annotated[Union[
    CheckConnectionConfig,
    ListBookingsConfig,
    GetBookingConfig,
    CancelBookingConfig,
    RequestRescheduleConfig,
    ReassignBookingConfig,
    MarkNoShowConfig,
    ListBookingCalendarsConfig,
    GetBookingCalendarConfig,
    GetTimeSlotsConfig,
    ScheduleBookingConfig,
    CreateOneTimeLinkConfig,
    ListBookingPagesConfig,
    GetBookingPageConfig,
    ListEventTypesConfig,
    GetEventTypeConfig,
    ListUsersConfig,
    GetUserConfig,
    ListContactsConfig,
    CreateContactConfig,
    GetContactConfig,
    UpdateContactConfig,
    DeleteContactConfig,
    ListTeamsConfig,
    GetTeamConfig
], Field(discriminator="operation")]


class ScheduleonceNodeConfig(NodeConfig[ScheduleonceOperation, ScheduleonceAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


# Fixed endpoint table: query and body fields are independently allowlisted.
ROUTES = {'check_connection': ('GET', '/test', [], []),
 'list_bookings': ('GET',
                   '/bookings',
                   ['status',
                    'owner',
                    'contact',
                    'booking_page',
                    'master_page',
                    'event_type',
                    'creation_time.gt',
                    'creation_time.lt',
                    'starting_time.gt',
                    'starting_time.lt',
                    'last_updated_time.gt',
                    'last_updated_time.lt',
                    'expand',
                    'before',
                    'after',
                    'limit',
                    'booking_calendar',
                    'host'],
                   []),
 'get_booking': ('GET', '/bookings/{id}', [], []),
 'cancel_booking': ('POST', '/bookings/{id}/cancel', [], ['cancellation_reason', 'send_cancellation_email']),
 'request_reschedule': ('POST', '/bookings/{id}/request-reschedule', [], ['reschedule_reason']),
 'reassign_booking': ('POST', '/bookings/{id}/reassign', [], ['new_host', 'location']),
 'mark_no_show': ('POST', '/bookings/{id}/no-show', [], []),
 'list_booking_calendars': ('GET', '/booking-calendars', ['host', 'before', 'after', 'limit'], []),
 'get_booking_calendar': ('GET', '/booking-calendars/{id}', [], []),
 'get_time_slots': ('GET', '/booking-calendars/{id}/time-slots', ['start_time', 'end_time'], []),
 'schedule_booking': ('POST',
                      '/booking-calendars/{id}/schedule',
                      [],
                      ['start_time', 'guest_time_zone', 'booking_form', 'location']),
 'create_one_time_link': ('POST',
                          '/booking-calendars/{id}/one-time-links',
                          [],
                          ['hide_url_params', 'booking_form', 'utm_params', 'booking_settings']),
 'list_booking_pages': ('GET',
                        '/booking-pages',
                        ['master_page', 'event_type', 'user', 'before', 'after', 'limit'],
                        []),
 'get_booking_page': ('GET', '/booking-pages/{id}', [], []),
 'list_event_types': ('GET', '/event-types', ['before', 'after', 'limit'], []),
 'get_event_type': ('GET', '/event-types/{id}', [], []),
 'list_users': ('GET', '/users', ['email', 'before', 'after', 'limit'], []),
 'get_user': ('GET', '/users/{id}', [], []),
 'list_contacts': ('GET',
                   '/contacts',
                   ['email',
                    'creation_time.lt',
                    'last_updated_time.gt',
                    'last_updated_time.lt',
                    'creation_time.gt',
                    'before',
                    'after',
                    'limit'],
                   []),
 'create_contact': ('POST',
                    '/contacts',
                    [],
                    ['owner',
                     'status',
                     'city',
                     'company_size',
                     'company',
                     'country',
                     'email',
                     'employees',
                     'first_name',
                     'has_consent',
                     'job_title',
                     'last_name',
                     'mobile_phone',
                     'phone',
                     'post_code',
                     'salutation',
                     'state',
                     'street_address',
                     'terms_of_sevice',
                     'timezone',
                     'custom_fields']),
 'get_contact': ('GET', '/contacts/{id}', [], []),
 'update_contact': ('PATCH',
                    '/contacts/{id}',
                    [],
                    ['first_name',
                     'last_name',
                     'owner',
                     'status',
                     'city',
                     'company_size',
                     'company',
                     'country',
                     'employees',
                     'has_consent',
                     'job_title',
                     'phone',
                     'post_code',
                     'salutation',
                     'state',
                     'street_address',
                     'terms_of_sevice',
                     'timezone',
                     'custom_fields']),
 'delete_contact': ('DELETE', '/contacts/{id}', [], []),
 'list_teams': ('GET', '/teams', ['user', 'before', 'after', 'limit'], []),
 'get_team': ('GET', '/teams/{id}', [], [])}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, dict):
        return {_redact(k, token): _redact(v, token) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    return value


class ScheduleonceNode(WorkflowNode):
    integration_type = "automation-scheduleonce"
    connection_evidence = ConnectionEvidence(noun="users", operation="list_users", label_keys=("email", "first_name", "id"))

    @classmethod
    def get_config_model(cls):
        return ScheduleonceNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Scheduleonce API key")
        op = self.config.config
        method, path, query_fields, body_fields = ROUTES[op.operation]
        values = op.model_dump(mode="json", by_alias=True, exclude_none=True)
        if "{id}" in path:
            path = path.replace("{id}", quote(op.id, safe=""))
        params = {k: values[k] for k in query_fields if k in values}
        body = {k: values[k] for k in body_fields if k in values} if body_fields else None
        token = self.config.credentials.api_key
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"API-Key": token, "Accept": "application/json"},
                    params=params, json=body)
        except httpx.RequestError:
            raise ValueError("Scheduleonce request could not be completed; check write status before retrying") from None
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Scheduleonce returned an unexpected non-JSON response") from None
        # Provider messages remain verbatim apart from removing our own secret.
        payload = _redact(payload, token)
        if response.status_code >= 300 or (isinstance(payload, dict) and (str(payload.get("type", "")).endswith("_error") or "error" in payload)):
            message = payload.get("message", "Scheduleonce rejected the request") if isinstance(payload, dict) else "Scheduleonce rejected the request"
            raise ValueError(f"Scheduleonce HTTP {response.status_code}: {message}")
        if not isinstance(payload, (dict, list)):
            raise ValueError("Scheduleonce returned an unexpected response shape")
        result = {"status": "success", "data": payload}
        if op.operation.startswith("list_"):
            rows = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(rows, list) or type(payload.get("has_more")) is not bool:
                raise ValueError("Scheduleonce returned an invalid list page")
            if payload["has_more"] and (not rows or not isinstance(rows[-1], dict) or not isinstance(rows[-1].get("id"), str)):
                raise ValueError("Scheduleonce returned no cursor for the next page")
            result = {"status": "success", **payload,
                "next_after": rows[-1]["id"] if payload["has_more"] else None}
        await self.emit(result)
        return result
