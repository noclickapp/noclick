"""TidyCal REST API v1: personal-token scheduling, contacts and account reads.

Contract: https://tidycal.com/developer/docs/ (version 1.0).
Each operation makes one request; page controls preserve provider pagination.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Annotated, Literal, Union
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://tidycal.com/api"


class TidyCalPersonalToken(BaseModel):
    model_config = ConfigDict(title="TidyCal Personal Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://tidycal.com/integrations/advanced",
            "x-credential-instructions": "In TidyCal, open Integrations → Advanced → Manage API keys → Personal tokens. Create a personal access token and paste it here. The REST API is available on every plan. Use a personal token for the REST API; MCP connection tokens cannot access it.",
        })
    credential_type: Literal["tidycal_personal_token"] = Field("tidycal_personal_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="Personal access token", min_length=1, max_length=4096,
        repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Personal access token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the token without the Bearer prefix")
        return value


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def check_value(cls, value, info):
        if value is None:
            return value
        if info.field_name in {"from_date", "to", "start_date", "end_date"}:
            try:
                date.fromisoformat(value)
            except (ValueError, TypeError):
                raise ValueError("Use a date in YYYY-MM-DD format") from None
        if info.field_name in {"starts_at", "ends_at"}:
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                raise ValueError("Use an ISO 8601 date and time") from None
        if info.field_name == "email" and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Use an email address")
        if info.field_name == "timezone":
            try:
                ZoneInfo(value)
            except (ValueError, ZoneInfoNotFoundError):
                raise ValueError("Use an IANA timezone, for example America/Los_Angeles") from None
        return value

    @model_validator(mode="after")
    def range_order(self):
        start, end = getattr(self, "starts_at", None), getattr(self, "ends_at", None)
        if start and end:
            a = datetime.fromisoformat(start.replace("Z", "+00:00"))
            b = datetime.fromisoformat(end.replace("Z", "+00:00"))
            if a.tzinfo is None: a = a.replace(tzinfo=timezone.utc)
            if b.tzinfo is None: b = b.replace(tzinfo=timezone.utc)
            if b < a or (self.operation == "list_booking_type_timeslots" and (b-a).total_seconds() > 90*86400):
                raise ValueError("End must follow start; timeslot ranges may span at most 90 days")
        return self


class BookingAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    booking_type_question_id: int = Field(..., ge=1)
    answer: str | list[str]


class GetAccountConfig(_Operation):
    """Account information."""
    operation: Literal["get_account"] = Field("get_account", json_schema_extra={"ui:hidden": True})


class ListBookingsConfig(_Operation):
    """List bookings."""
    operation: Literal["list_bookings"] = Field("list_bookings", json_schema_extra={"ui:hidden": True})
    starts_at: str | None = Field(None, json_schema_extra={"format": "date-time"})
    ends_at: str | None = Field(None, json_schema_extra={"format": "date-time"})
    cancelled: bool | None = Field(None)
    page: int | None = Field(1, ge=1, strict=True)
    include_teams: bool | None = Field(None)
    order_by: Literal['id asc', 'id desc', 'starts_at asc', 'starts_at desc', 'ends_at asc', 'ends_at desc', 'created_at asc', 'created_at desc', 'updated_at asc', 'updated_at desc', 'cancelled_at asc', 'cancelled_at desc'] | None = Field(None)


class GetBookingConfig(_Operation):
    """Get booking."""
    operation: Literal["get_booking"] = Field("get_booking", json_schema_extra={"ui:hidden": True})
    booking_id: int = Field(..., ge=1, strict=True)


class CancelBookingConfig(_Operation):
    """Cancel booking."""
    operation: Literal["cancel_booking"] = Field("cancel_booking", json_schema_extra={"ui:hidden": True})
    booking_id: int = Field(..., ge=1, strict=True)
    reason: str | None = Field(None, description='Optional reason for cancellation')
    notify: bool | None = Field(None, description='Email the booker and the host about the cancellation. Send false to cancel without any notification.')


class RescheduleBookingConfig(_Operation):
    """Reschedule booking."""
    operation: Literal["reschedule_booking"] = Field("reschedule_booking", json_schema_extra={"ui:hidden": True})
    booking_id: int = Field(..., ge=1, strict=True)
    starts_at: str = Field(..., json_schema_extra={"format": "date-time"}, description='New start time, ISO 8601. A value without a UTC offset is read as UTC. Use /booking-types/{bookingType}/timeslots to find open slots.')
    notify: bool | None = Field(None, description="Send the TidyCal reschedule (or re-approval) emails and notifications. When false, TidyCal sends nothing, but the host's calendar provider (Google Calendar invite updates) and meeting provider (Zoom, Microsoft Teams) may still notify the booker of the new time.")


class ListBookingReschedulesConfig(_Operation):
    """List rescheduled bookings."""
    operation: Literal["list_booking_reschedules"] = Field("list_booking_reschedules", json_schema_extra={"ui:hidden": True})
    page: int | None = Field(1, ge=1, strict=True)


class AddBookingGuestConfig(_Operation):
    """Add guest to booking."""
    operation: Literal["add_booking_guest"] = Field("add_booking_guest", json_schema_extra={"ui:hidden": True})
    booking_id: int = Field(..., ge=1, strict=True)
    name: str = Field(..., max_length=80, description="Guest's name")
    email: str = Field(..., max_length=191, description="Guest's email address. Must not already be the booker or a guest on this booking.", json_schema_extra={"format": "email"})


class ListBookingTypesConfig(_Operation):
    """List booking types."""
    operation: Literal["list_booking_types"] = Field("list_booking_types", json_schema_extra={"ui:hidden": True})
    page: int | None = Field(1, ge=1, strict=True)


class CreateBookingTypeConfig(_Operation):
    """Create booking type."""
    operation: Literal["create_booking_type"] = Field("create_booking_type", json_schema_extra={"ui:hidden": True})
    title: str = Field(..., max_length=191)
    description: str = Field(...)
    duration_minutes: int = Field(..., ge=1, strict=True)
    url_slug: str = Field(..., max_length=191)
    padding_minutes: int | None = Field(None, ge=0, strict=True)
    latest_availability_days: int | None = Field(None, ge=0, le=36500, strict=True)
    private: bool | None = Field(None)
    max_bookings: int | None = Field(None, ge=1, strict=True)
    max_guest_invites_per_booker: int | None = Field(None, ge=0, le=10, strict=True)
    display_seats_remaining: bool | None = Field(None)
    booking_availability_interval_minutes: int | None = Field(None, ge=15, le=1440, strict=True, description='If omitted, defaults to 30 for meetings of at least 30 minutes owned by new signups assigned to the new-booking-type-interval treatment; otherwise 15. Explicit values are preserved.')
    price: float | None = Field(None, ge=0, le=99999999.99, description="Price for the booking type. Set to 0 for free booking types. How many decimal places are accepted depends on the currency: a currency with no sub-unit (JPY, KRW, CLP, VND and the other zero-decimal currencies) takes whole amounts only, every other currency takes at most 2. Trailing zeros are notation rather than precision, so 2200.00 is a valid JPY price. The currency judged is the one sent in `currency_code`, or your account currency when that is omitted. A price below Stripe's minimum charge for the currency (0.50 USD, for example) is refused on Stripe and TidyCal Payments, and a currency PayPal doesn't list is refused on PayPal. A recurring session or subscription plan price is held to the minimum the recurring charge uses, which is higher in some currencies (50 INR, for example).")
    payment_platform: Literal['stripe', 'paypal', 'tidycal', 'razorpay'] | None = Field(None, description='Payment platform to use. The platform must be connected in your account Integrations settings. When price > 0 and this is omitted on a new booking type, or a free one whose platform cannot take the charge, your connected platform is used: the one your paid booking types are on if you have moved off TidyCal Payments, otherwise TidyCal Payments, then Stripe, then Razorpay, then PayPal. Recurring booking types and subscription plans need Stripe, and any other platform returns 422. If none is connected the request returns 422 and asks you to connect Stripe.')
    currency_code: str | None = Field(None, description='ISO 4217 currency code (e.g. USD, EUR, GBP). Defaults to your account currency.')
    booking_threshold: int | None = Field(None, ge=0, le=15000, strict=True, description='Minimum notice required before a booking, in minutes. Omit for the default of 120 (2 hours); set to 0 for no minimum notice.')


class ListBookingTypeQuestionsConfig(_Operation):
    """List booking type questions."""
    operation: Literal["list_booking_type_questions"] = Field("list_booking_type_questions", json_schema_extra={"ui:hidden": True})
    booking_type_id: int = Field(..., ge=1, strict=True)


class GetBookingTypeConfig(_Operation):
    """Get booking type."""
    operation: Literal["get_booking_type"] = Field("get_booking_type", json_schema_extra={"ui:hidden": True})
    booking_type_id: int = Field(..., ge=1, strict=True)


class UpdateBookingTypeConfig(_Operation):
    """Update booking type."""
    operation: Literal["update_booking_type"] = Field("update_booking_type", json_schema_extra={"ui:hidden": True})
    booking_type_id: int = Field(..., ge=1, strict=True)
    title: str | None = Field(None, max_length=191)
    description: str | None = Field(None)
    duration_minutes: int | None = Field(None, ge=1, strict=True)
    url_slug: str | None = Field(None, max_length=191)
    padding_minutes: int | None = Field(None, ge=0, strict=True)
    latest_availability_days: int | None = Field(None, ge=0, le=36500, strict=True)
    private: bool | None = Field(None)
    max_bookings: int | None = Field(None, ge=1, strict=True)
    max_guest_invites_per_booker: int | None = Field(None, ge=0, le=10, strict=True)
    display_seats_remaining: bool | None = Field(None)
    booking_availability_interval_minutes: int | None = Field(None, ge=15, le=1440, strict=True, description='If omitted, defaults to 30 for meetings of at least 30 minutes owned by new signups assigned to the new-booking-type-interval treatment; otherwise 15. Explicit values are preserved.')
    price: float | None = Field(None, ge=0, le=99999999.99, description="Price for the booking type. Set to 0 for free booking types. How many decimal places are accepted depends on the currency: a currency with no sub-unit (JPY, KRW, CLP, VND and the other zero-decimal currencies) takes whole amounts only, every other currency takes at most 2. Trailing zeros are notation rather than precision, so 2200.00 is a valid JPY price. The currency judged is the one sent in `currency_code`, or your account currency when that is omitted. A price below Stripe's minimum charge for the currency (0.50 USD, for example) is refused on Stripe and TidyCal Payments, and a currency PayPal doesn't list is refused on PayPal. A recurring session or subscription plan price is held to the minimum the recurring charge uses, which is higher in some currencies (50 INR, for example).")
    payment_platform: Literal['stripe', 'paypal', 'tidycal', 'razorpay'] | None = Field(None, description='Payment platform to use. The platform must be connected in your account Integrations settings. When price > 0 and this is omitted on a new booking type, or a free one whose platform cannot take the charge, your connected platform is used: the one your paid booking types are on if you have moved off TidyCal Payments, otherwise TidyCal Payments, then Stripe, then Razorpay, then PayPal. Recurring booking types and subscription plans need Stripe, and any other platform returns 422. If none is connected the request returns 422 and asks you to connect Stripe.')
    currency_code: str | None = Field(None, description='ISO 4217 currency code (e.g. USD, EUR, GBP). Defaults to your account currency.')
    booking_threshold: int | None = Field(None, ge=0, le=15000, strict=True, description='Minimum notice required before a booking, in minutes. Omit for the default of 120 (2 hours); set to 0 for no minimum notice.')


class DisableBookingTypeConfig(_Operation):
    """Disable booking type."""
    operation: Literal["disable_booking_type"] = Field("disable_booking_type", json_schema_extra={"ui:hidden": True})
    booking_type_id: int = Field(..., ge=1, strict=True)


class EnableBookingTypeConfig(_Operation):
    """Enable booking type."""
    operation: Literal["enable_booking_type"] = Field("enable_booking_type", json_schema_extra={"ui:hidden": True})
    booking_type_id: int = Field(..., ge=1, strict=True)


class ListBookingTypeTimeslotsConfig(_Operation):
    """List available timeslots."""
    operation: Literal["list_booking_type_timeslots"] = Field("list_booking_type_timeslots", json_schema_extra={"ui:hidden": True})
    booking_type_id: int = Field(..., ge=1, strict=True)
    starts_at: str = Field(..., json_schema_extra={"format": "date-time"})
    ends_at: str = Field(..., json_schema_extra={"format": "date-time"})


class CreateBookingConfig(_Operation):
    """Create booking."""
    operation: Literal["create_booking"] = Field("create_booking", json_schema_extra={"ui:hidden": True})
    booking_type_id: int = Field(..., ge=1, strict=True)
    starts_at: str = Field(..., json_schema_extra={"format": "date-time"}, description='The start time of the booking in UTC. Required for single bookings. Ignored if `bookings` array is provided.')
    name: str = Field(..., max_length=191, description='Name of the person making the booking')
    email: str = Field(..., max_length=191, description='Email of the person making the booking', json_schema_extra={"format": "email"})
    timezone: str = Field(..., max_length=191, description='The timezone of the booking')
    booking_questions: list[BookingAnswer] | None = Field(None, description='Answers to booking type questions')
    coupon_code: str | None = Field(None, max_length=191, description="One of the host's coupon codes (case-insensitive). Required to book a priced\nbooking type, and it must bring the price to 0. Ignored for a free booking type.\n")
    # Single-session bookings; use a returned timeslot for starts_at.


class ListContactsConfig(_Operation):
    """List contacts."""
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})
    search: str | None = Field(None, max_length=255)
    page: int | None = Field(1, ge=1, strict=True)


class CreateContactConfig(_Operation):
    """Create contact."""
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={"ui:hidden": True})
    name: str = Field(...)
    email: str = Field(..., json_schema_extra={"format": "email"})
    timezone: str | None = Field(None)


class GetContactConfig(_Operation):
    """Get contact."""
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})
    contact_id: int = Field(..., ge=1, strict=True)


class UpdateContactConfig(_Operation):
    """Update contact."""
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"ui:hidden": True})
    contact_id: int = Field(..., ge=1, strict=True)
    name: str | None = Field(None)
    email: str | None = Field(None, json_schema_extra={"format": "email"})
    timezone: str | None = Field(None)
    phone_number: str | None = Field(None)


class ListTeamsConfig(_Operation):
    """List teams."""
    operation: Literal["list_teams"] = Field("list_teams", json_schema_extra={"ui:hidden": True})
    page: int | None = Field(1, ge=1, strict=True)


class GetTeamConfig(_Operation):
    """Get team."""
    operation: Literal["get_team"] = Field("get_team", json_schema_extra={"ui:hidden": True})
    team_id: int = Field(..., ge=1, strict=True)


class ListTeamBookingsConfig(_Operation):
    """List team bookings."""
    operation: Literal["list_team_bookings"] = Field("list_team_bookings", json_schema_extra={"ui:hidden": True})
    team_id: int = Field(..., ge=1, strict=True)
    page: int | None = Field(1, ge=1, strict=True)
    start_date: str | None = Field(None, json_schema_extra={"format": "date"})
    end_date: str | None = Field(None, json_schema_extra={"format": "date"})
    email: str | None = Field(None, json_schema_extra={"format": "email"})
    host_id: int | None = Field(None, strict=True)
    cancelled: bool | None = Field(None)


class ListPaymentsConfig(_Operation):
    """List payments."""
    operation: Literal["list_payments"] = Field("list_payments", json_schema_extra={"ui:hidden": True})
    status: Literal['pending', 'completed', 'failed'] | None = Field(None)
    from_date: str | None = Field(None, alias="from", json_schema_extra={"format": "date"})
    to: str | None = Field(None, json_schema_extra={"format": "date"})
    page: int | None = Field(1, ge=1, strict=True)


class ListAvailabilitySchedulesConfig(_Operation):
    """List availability schedules."""
    operation: Literal["list_availability_schedules"] = Field("list_availability_schedules", json_schema_extra={"ui:hidden": True})


TidyCalOperation = Annotated[Union[
    GetAccountConfig,
    ListBookingsConfig,
    GetBookingConfig,
    CancelBookingConfig,
    RescheduleBookingConfig,
    ListBookingReschedulesConfig,
    AddBookingGuestConfig,
    ListBookingTypesConfig,
    CreateBookingTypeConfig,
    ListBookingTypeQuestionsConfig,
    GetBookingTypeConfig,
    UpdateBookingTypeConfig,
    DisableBookingTypeConfig,
    EnableBookingTypeConfig,
    ListBookingTypeTimeslotsConfig,
    CreateBookingConfig,
    ListContactsConfig,
    CreateContactConfig,
    GetContactConfig,
    UpdateContactConfig,
    ListTeamsConfig,
    GetTeamConfig,
    ListTeamBookingsConfig,
    ListPaymentsConfig,
    ListAvailabilitySchedulesConfig
], Field(discriminator="operation")]


class TidyCalConfig(NodeConfig[TidyCalOperation, TidyCalPersonalToken]):
    pass


ROUTES = {'get_account': ('GET', '/me', [], [], [], False),
 'list_bookings': ('GET',
                   '/bookings',
                   [],
                   ['starts_at', 'ends_at', 'cancelled', 'page', 'include_teams', 'order_by'],
                   [],
                   False),
 'get_booking': ('GET', '/bookings/{booking}', [('booking_id', 'booking')], [], [], False),
 'cancel_booking': ('PATCH',
                    '/bookings/{booking}/cancel',
                    [('booking_id', 'booking')],
                    [],
                    ['reason', 'notify'],
                    True),
 'reschedule_booking': ('PATCH',
                        '/bookings/{booking}/reschedule',
                        [('booking_id', 'booking')],
                        [],
                        ['starts_at', 'notify'],
                        True),
 'list_booking_reschedules': ('GET', '/booking-reschedules', [], ['page'], [], False),
 'add_booking_guest': ('POST',
                       '/bookings/{booking}/guests',
                       [('booking_id', 'booking')],
                       [],
                       ['name', 'email'],
                       True),
 'list_booking_types': ('GET', '/booking-types', [], ['page'], [], False),
 'create_booking_type': ('POST',
                         '/booking-types',
                         [],
                         [],
                         ['title',
                          'description',
                          'duration_minutes',
                          'url_slug',
                          'padding_minutes',
                          'latest_availability_days',
                          'private',
                          'max_bookings',
                          'max_guest_invites_per_booker',
                          'display_seats_remaining',
                          'booking_availability_interval_minutes',
                          'price',
                          'payment_platform',
                          'currency_code',
                          'booking_threshold'],
                         True),
 'list_booking_type_questions': ('GET',
                                 '/booking-types/{bookingType}/questions',
                                 [('booking_type_id', 'bookingType')],
                                 [],
                                 [],
                                 False),
 'get_booking_type': ('GET',
                      '/booking-types/{bookingType}',
                      [('booking_type_id', 'bookingType')],
                      [],
                      [],
                      False),
 'update_booking_type': ('PATCH',
                         '/booking-types/{bookingType}',
                         [('booking_type_id', 'bookingType')],
                         [],
                         ['title',
                          'description',
                          'duration_minutes',
                          'url_slug',
                          'padding_minutes',
                          'latest_availability_days',
                          'private',
                          'max_bookings',
                          'max_guest_invites_per_booker',
                          'display_seats_remaining',
                          'booking_availability_interval_minutes',
                          'price',
                          'payment_platform',
                          'currency_code',
                          'booking_threshold'],
                         True),
 'disable_booking_type': ('POST',
                          '/booking-types/{bookingType}/disable',
                          [('booking_type_id', 'bookingType')],
                          [],
                          [],
                          False),
 'enable_booking_type': ('POST',
                         '/booking-types/{bookingType}/enable',
                         [('booking_type_id', 'bookingType')],
                         [],
                         [],
                         False),
 'list_booking_type_timeslots': ('GET',
                                 '/booking-types/{bookingType}/timeslots',
                                 [('booking_type_id', 'bookingType')],
                                 ['starts_at', 'ends_at'],
                                 [],
                                 False),
 'create_booking': ('POST',
                    '/booking-types/{bookingType}/bookings',
                    [('booking_type_id', 'bookingType')],
                    [],
                    ['starts_at', 'name', 'email', 'timezone', 'booking_questions', 'coupon_code'],
                    True),
 'list_contacts': ('GET', '/contacts', [], ['search', 'page'], [], False),
 'create_contact': ('POST', '/contacts', [], [], ['name', 'email', 'timezone'], True),
 'get_contact': ('GET', '/contacts/{contact}', [('contact_id', 'contact')], [], [], False),
 'update_contact': ('PATCH',
                    '/contacts/{contact}',
                    [('contact_id', 'contact')],
                    [],
                    ['name', 'email', 'timezone', 'phone_number'],
                    True),
 'list_teams': ('GET', '/teams', [], ['page'], [], False),
 'get_team': ('GET', '/teams/{team}', [('team_id', 'team')], [], [], False),
 'list_team_bookings': ('GET',
                        '/teams/{team}/bookings',
                        [('team_id', 'team')],
                        ['page', 'start_date', 'end_date', 'email', 'host_id', 'cancelled'],
                        [],
                        False),
 'list_payments': ('GET', '/payments', [], ['status', 'from', 'to', 'page'], [], False),
 'list_availability_schedules': ('GET', '/availability-schedules', [], [], [], False)}


class TidyCalNode(WorkflowNode):
    integration_type = "automation-tidycal"
    connection_evidence = ConnectionEvidence(noun="TidyCal account", identity_operation="get_account")

    @classmethod
    def get_config_model(cls):
        return TidyCalConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a TidyCal personal access token")
        op = self.config.config
        token = self.config.credentials.api_token
        method, path, path_fields, query_fields, body_fields, has_body = ROUTES[op.operation]
        values = op.model_dump(by_alias=True)
        for field, placeholder in path_fields:
            path = path.replace("{" + placeholder + "}", str(values[field]))
        params = {k: (str(values[k]).lower() if isinstance(values[k], bool) else values[k])
                  for k in query_fields if values[k] is not None}
        body = {k: values[k] for k in body_fields if values[k] is not None}
        if op.operation.startswith("update_") and not body:
            raise ValueError("Supply at least one field to update")
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, params=params,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                    **({"json": body} if has_body else {}))
        except httpx.HTTPError:
            # Writes are never retried: a transport failure may follow a committed change.
            raise ValueError("TidyCal request did not complete; check the account before retrying a write") from None
        if response.status_code >= 300:
            try:
                message = response.json().get("message", "TidyCal rejected the request")
            except (ValueError, AttributeError):
                message = "TidyCal rejected the request"
            output = {"status": "error", "status_code": response.status_code,
                      "message": str(message).replace(token, "[redacted]"),
                      "retry_after": response.headers.get("Retry-After")}
        elif response.status_code == 204 and method != "GET":
            output = {"status": "success", "data": None}
        else:
            try:
                payload = response.json()
            except ValueError:
                raise ValueError("Expected a JSON response from TidyCal") from None
            if not isinstance(payload, (dict, list)):
                raise ValueError("Expected a TidyCal JSON object or list")
            if isinstance(payload, dict) and ("errors" in payload or payload.get("success") is False):
                raise ValueError("TidyCal returned an error envelope")
            if op.operation == "get_account" and (not isinstance(payload, dict)
                    or not isinstance(payload.get("name"), str) or not payload["name"].strip()
                    or not isinstance(payload.get("email"), str) or not payload["email"].strip()):
                raise ValueError("TidyCal did not return a recognizable account")
            # Preserve both pagination envelopes (top-level and links/meta), including nulls.
            output = {**payload, "status": "success"} if isinstance(payload, dict) else {"status": "success", "data": payload}
        await self.emit(output)
        return output
