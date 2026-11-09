"""Hospitable Public API v2: fixed account, hosting and guest-service operations.

Contract: https://developer.hospitable.com/docs/public-api-docs
Lists return one page and preserve provider pagination metadata. Accepted writes
are reported as accepted, without implying delivery or calendar completion.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://public.api.hospitable.com/v2"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class HospitableTokenCredential(_Model):
    model_config = ConfigDict(title="Hospitable Personal Access Token", extra="forbid", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://developer.hospitable.com/docs/public-api-docs"})
    credential_type: Literal["hospitable_api_token"] = Field("hospitable_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="Personal Access Token", min_length=1, max_length=8192, repr=False,
        description="Paste your Hospitable personal access token with permissions for the operations you use. Omit the Bearer prefix.",
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Personal Access Token", key=True)
        if not value or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the token without the Bearer prefix or whitespace")
        return value


Identifier = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")]


class _Page(_Model):
    page: int = Field(1, ge=1, title="Page")
    per_page: int = Field(10, ge=1, le=100, title="Results per Page")


class _Property(_Model):
    property_id: Identifier = Field(..., title="Property ID", description="The property's UUID from List Properties.")


class _Reservation(_Model):
    reservation_id: Identifier = Field(..., title="Reservation ID", description="The reservation UUID. Get Reservation also accepts a reservation code.")


class _Inquiry(_Model):
    inquiry_id: Identifier = Field(..., title="Inquiry ID", description="The inquiry/conversation UUID.")


class _Task(_Model):
    task_id: UUID = Field(..., title="Task ID", description="The task UUID returned by List Tasks.")


class _PropertyFilter(_Page):
    properties: list[Identifier] = Field(..., min_length=1, max_length=999, title="Property IDs")


class GetUserConfig(_Model):
    """Read the account owner and billing profile associated with this token."""
    operation: Literal["get_user"] = Field("get_user", json_schema_extra={"ui:hidden": True})


class ListPropertiesConfig(_Page):
    operation: Literal["list_properties"] = Field("list_properties", json_schema_extra={"ui:hidden": True})
    include: Literal["listings", "owners"] | None = None


class GetPropertyConfig(_Property):
    operation: Literal["get_property"] = Field("get_property", json_schema_extra={"ui:hidden": True})
    include: Literal["listings", "owners"] | None = None


class GetCalendarConfig(_Property):
    operation: Literal["get_calendar"] = Field("get_calendar", json_schema_extra={"ui:hidden": True})
    start_date: date | None = None
    end_date: date | None = None


class CalendarPrice(_Model):
    amount: int = Field(..., description="Price in minor currency units, e.g. cents.")


class CalendarDate(_Model):
    date: date
    available: bool | None = None
    price: CalendarPrice | None = None
    min_stay: int | None = Field(None, ge=1)
    closed_for_checkout: bool | None = None
    closed_for_checkin: bool | None = None
    note: str | None = Field(None, max_length=512)


class UpdateCalendarConfig(_Property):
    """Submit calendar updates; HTTP 202 means accepted for processing."""
    operation: Literal["update_calendar"] = Field("update_calendar", json_schema_extra={"ui:hidden": True})
    dates: list[CalendarDate] = Field(..., min_length=1, max_length=60)
    note: str | None = Field(None, max_length=512)


class ListReservationsConfig(_PropertyFilter):
    operation: Literal["list_reservations"] = Field("list_reservations", json_schema_extra={"ui:hidden": True})
    start_date: date | None = None
    end_date: date | None = None
    date_query: Literal["checkin", "checkout", "booked_at"] = "checkin"
    include: str | None = Field(None, description="Comma-separated includes; each relationship may require additional token permissions.")
    platform_id: str | None = None
    conversation_id: str | None = Field(None, json_schema_extra={"format": "uuid"})
    statuses: list[Literal["request", "accepted", "cancelled", "not_accepted", "checkpoint"]] | None = None
    platforms: list[Literal["airbnb", "homeaway", "booking", "agoda", "ical", "manual", "direct"]] | None = None


class GuestCounts(_Model):
    adults: int = Field(..., ge=1)
    children: int | None = Field(None, ge=0)
    infants: int | None = Field(None, ge=0)
    pets: int | None = Field(None, ge=0)


class GuestInfo(_Model):
    first_name: str = Field(..., min_length=1)
    last_name: str = Field(..., min_length=1)
    email: EmailStr
    phone: str | None = None


class ReservationFinancials(_Model):
    accommodation: int = Field(..., description="Accommodation amount in minor currency units.")
    currency: str = Field(..., min_length=3, max_length=3, description="Currency, for example USD.")
    cleaning_fee: float | None = None
    pet_fee: float | None = None


class CreateReservationConfig(_Model):
    """Create a manual booking; dates must be available at the property."""
    operation: Literal["create_reservation"] = Field("create_reservation", json_schema_extra={"ui:hidden": True})
    property_id: Identifier
    guests: GuestCounts
    check_in: date
    check_out: date
    guest: GuestInfo
    financials: ReservationFinancials
    language: Literal["ar", "ca", "cs", "zh", "da", "nl", "en", "fi", "fr", "de", "el", "hu", "is", "id", "it", "ja", "ko", "ms", "no", "pl", "pt", "ru", "es", "sv", "ta", "th", "tr", "zh-Hant", "iw"]
    channel: str | None = None
    reservation_code: str | None = Field(None, max_length=50)
    notes: str | None = None


class GetReservationConfig(_Reservation):
    operation: Literal["get_reservation"] = Field("get_reservation", json_schema_extra={"ui:hidden": True})
    include: str | None = None


class CancelReservationConfig(_Reservation):
    """Cancel a manual reservation (provider restrictions apply)."""
    operation: Literal["cancel_reservation"] = Field("cancel_reservation", json_schema_extra={"ui:hidden": True})
    initiated_by: Literal["host", "guest"] = "host"


class ListReservationMessagesConfig(_Reservation):
    operation: Literal["list_reservation_messages"] = Field("list_reservation_messages", json_schema_extra={"ui:hidden": True})


class SendReservationMessageConfig(_Reservation):
    """Queue a plain-text guest message; accepted does not mean delivered."""
    operation: Literal["send_reservation_message"] = Field("send_reservation_message", json_schema_extra={"ui:hidden": True})
    body: str = Field(..., min_length=1, description="Plain text; HTML is unsupported.")
    sender_id: str | None = Field(None, description="Optional Airbnb co-host user ID.")


class ListInquiriesConfig(_PropertyFilter):
    operation: Literal["list_inquiries"] = Field("list_inquiries", json_schema_extra={"ui:hidden": True})
    include: str | None = None
    last_message_at: str | None = None


class GetInquiryConfig(_Inquiry):
    operation: Literal["get_inquiry"] = Field("get_inquiry", json_schema_extra={"ui:hidden": True})
    include: str | None = None


class SendInquiryMessageConfig(_Inquiry):
    operation: Literal["send_inquiry_message"] = Field("send_inquiry_message", json_schema_extra={"ui:hidden": True})
    body: str = Field(..., min_length=1, description="Plain text; HTML is unsupported.")
    sender_id: str | None = None


class ListTasksConfig(_PropertyFilter):
    operation: Literal["list_tasks"] = Field("list_tasks", json_schema_extra={"ui:hidden": True})
    start_date: date | None = None
    end_date: date | None = None
    include: Literal["marketplace"] | None = None
    reservation_uuid: str | None = Field(None, json_schema_extra={"format": "uuid"})
    teammate_uuid: str | None = Field(None, json_schema_extra={"format": "uuid"})


class _TaskChanges(_Model):
    start_date: datetime | None = None
    end_date: datetime | None = None
    teammate_uuid: str | None = Field(None, json_schema_extra={"format": "uuid"}, description="Set null to unassign an internal teammate.")
    note: str | None = Field(None, max_length=1000, description="Set null to clear the internal note.")
    send_task_reminder: bool | None = None
    reservation_uuid: str | None = Field(None, json_schema_extra={"format": "uuid"})


class CreateTaskConfig(_TaskChanges):
    operation: Literal["create_task"] = Field("create_task", json_schema_extra={"ui:hidden": True})
    property_id: Identifier
    task_type: Literal[1, 2, 3, 4, 5]
    start_date: datetime
    end_date: datetime


class GetTaskConfig(_Task):
    operation: Literal["get_task"] = Field("get_task", json_schema_extra={"ui:hidden": True})
    include: str | None = Field(None, description="Comma-separated: marketplace, checklist, photos.")


class UpdateTaskConfig(_Task, _TaskChanges):
    operation: Literal["update_task"] = Field("update_task", json_schema_extra={"ui:hidden": True})

    @model_validator(mode="after")
    def changes(self):
        if not self.model_fields_set - {"operation", "task_id"}:
            raise ValueError("Provide at least one task field to update")
        return self


class DeleteTaskConfig(_Task):
    operation: Literal["delete_task"] = Field("delete_task", json_schema_extra={"ui:hidden": True})


class ListTeammatesConfig(_Page):
    operation: Literal["list_teammates"] = Field("list_teammates", json_schema_extra={"ui:hidden": True})
    property_id: Identifier | None = None
    service_id: int | None = Field(None, ge=1, le=8)
    include: Literal["properties"] | None = None


class ListReviewsConfig(_Property, _Page):
    property_id: UUID = Field(..., title="Property ID")
    operation: Literal["list_reviews"] = Field("list_reviews", json_schema_extra={"ui:hidden": True})
    per_page: int = Field(10, ge=1, le=50)
    include: Literal["guest"] | None = None


class RespondReviewConfig(_Model):
    operation: Literal["respond_review"] = Field("respond_review", json_schema_extra={"ui:hidden": True})
    review_id: Identifier
    response: str = Field(..., min_length=1)


HospitableConfig = Annotated[Union[GetUserConfig, ListPropertiesConfig, GetPropertyConfig, GetCalendarConfig,
    UpdateCalendarConfig, ListReservationsConfig, CreateReservationConfig, GetReservationConfig,
    CancelReservationConfig, ListReservationMessagesConfig, SendReservationMessageConfig,
    ListInquiriesConfig, GetInquiryConfig, SendInquiryMessageConfig, ListTasksConfig, CreateTaskConfig,
    GetTaskConfig, UpdateTaskConfig, DeleteTaskConfig, ListTeammatesConfig, ListReviewsConfig,
    RespondReviewConfig], Field(discriminator="operation")]


class HospitableFullConfig(NodeConfig[HospitableConfig, HospitableTokenCredential]):
    pass


# method, contract path, config field used for its placeholder, query fields, success status
ROUTES = {
    "get_user": ("GET", "/user", None, (), 200),
    "list_properties": ("GET", "/properties", None, ("page", "per_page", "include"), 200),
    "get_property": ("GET", "/properties/{uuid}", "property_id", ("include",), 200),
    "get_calendar": ("GET", "/properties/{uuid}/calendar", "property_id", ("start_date", "end_date"), 200),
    "update_calendar": ("PUT", "/properties/{uuid}/calendar", "property_id", (), 202),
    "list_reservations": ("GET", "/reservations", None, ("page", "per_page", "properties", "start_date", "end_date", "date_query", "include", "platform_id", "conversation_id", "statuses", "platforms"), 200),
    "create_reservation": ("POST", "/reservations", None, (), 201),
    "get_reservation": ("GET", "/reservations/{identifier}", "reservation_id", ("include",), 200),
    "cancel_reservation": ("POST", "/reservations/{uuid}/cancel", "reservation_id", (), 200),
    "list_reservation_messages": ("GET", "/reservations/{uuid}/messages", "reservation_id", (), 200),
    "send_reservation_message": ("POST", "/reservations/{uuid}/messages", "reservation_id", (), 202),
    "list_inquiries": ("GET", "/inquiries", None, ("page", "per_page", "properties", "include", "last_message_at"), 200),
    "get_inquiry": ("GET", "/inquiries/{uuid}", "inquiry_id", ("include",), 200),
    "send_inquiry_message": ("POST", "/inquiries/{uuid}/messages", "inquiry_id", (), 202),
    "list_tasks": ("GET", "/tasks", None, ("page", "per_page", "properties", "start_date", "end_date", "include", "reservation_uuid", "teammate_uuid"), 200),
    "create_task": ("POST", "/tasks", None, (), 200),
    "get_task": ("GET", "/tasks/{id}", "task_id", ("include",), 200),
    "update_task": ("PATCH", "/tasks/{id}", "task_id", (), 200),
    "delete_task": ("DELETE", "/tasks/{id}", "task_id", (), 200),
    "list_teammates": ("GET", "/teammates", None, ("page", "per_page", "property_id", "service_id", "include"), 200),
    "list_reviews": ("GET", "/properties/{uuid}/reviews", "property_id", ("page", "per_page", "include"), 200),
    "respond_review": ("POST", "/reviews/{uuid}/respond", "review_id", (), 200),
}
QUERY_NAMES = {"properties": "properties[]", "statuses": "status[]", "platforms": "platforms[]"}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    return value


class HospitableNode(WorkflowNode):
    integration_type = "automation-hospitable"
    connection_evidence = ConnectionEvidence(noun="Hospitable account", identity_operation="get_user")

    @classmethod
    def get_config_model(cls):
        return HospitableFullConfig

    async def execute(self, inputs):
        if not isinstance(self.config, HospitableFullConfig) or not self.config.credentials:
            raise ValueError("Connect a Hospitable personal access token")
        cfg = self.config.config
        token = self.config.credentials.api_token
        method, path, path_field, query_fields, expected = ROUTES[cfg.operation]
        values = cfg.model_dump(mode="json", exclude_unset=True)
        # Pagination defaults are part of the request even when omitted in the UI.
        query_values = cfg.model_dump(mode="json", exclude_none=True)
        if path_field:
            path = re.sub(r"\{[^}]+\}", quote(str(getattr(cfg, path_field)), safe=""), path)
        params = [(QUERY_NAMES.get(k, k), item) for k in query_fields if k in query_values
            for item in (query_values[k] if isinstance(query_values[k], list) else [query_values[k]])]
        body = {k: v for k, v in values.items() if k not in {"operation", path_field, *query_fields}}
        # Cancellation has a meaningful default; other optional body fields retain omission/null semantics.
        if cfg.operation == "cancel_reservation":
            body["initiated_by"] = cfg.initiated_by
        result = {"operation": cfg.operation}
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE + path, params=params,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json", "Content-Type": "application/json"},
                **({"json": body} if method in {"POST", "PUT", "PATCH"} else {}))
        if response.status_code != expected:
            message = "Hospitable returned HTTP " + str(response.status_code)
            try:
                error = response.json()
                if isinstance(error, dict):
                    detail = error.get("message") or error.get("reason_phrase")
                    if isinstance(detail, str):
                        message = detail[:2000]
            except ValueError:
                pass
            return {**result, "status": "error", "http_status": response.status_code,
                "error": _redact(message, token)}
        if cfg.operation == "delete_task" and not response.content:
            payload = None
        else:
            if len(response.content) > 10_000_000:
                raise ValueError("Hospitable response exceeds the supported size")
            media = response.headers.get("content-type", "").split(";", 1)[0].lower()
            if media != "application/json" and not media.endswith("+json"):
                raise ValueError("Expected a JSON response from Hospitable")
            try:
                payload = response.json()
            except ValueError:
                raise ValueError("Hospitable returned invalid JSON") from None
            if not isinstance(payload, (dict, list)):
                raise ValueError("Hospitable returned an unexpected JSON shape")
            if isinstance(payload, dict) and (payload.get("errors") or payload.get("error")):
                return {**result, "status": "error", "error": "Hospitable returned an error envelope"}
        return {**result, "status": "success", "http_status": expected,
            "accepted": expected == 202, "data": _redact(payload, token)}
