"""Uplisting's published API-key contract: fixed, single-request operations.

API reference: https://www.uplisting.io/developer
V2 writes additionally require a partner client ID. Calendar updates are queued.
"""
from __future__ import annotations

import base64
from datetime import date as Date
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://connect.uplisting.io"


class UplistingAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Uplisting API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.uplisting.io/connect/api",
            "x-credential-instructions": "Copy your API key from Uplisting Connect > API. Paste the raw key; NoClick encodes it for Basic authentication. V2 booking and custom attribute operations also require a partner client ID from Uplisting's API access form. Other operations need only the API key.",
        })
    credential_type: Literal["uplisting_api_key"] = Field("uplisting_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", json_schema_extra={"ui:widget": "password"})
    client_id: str | None = Field(None, title="Partner client ID", description="Only needed for V2 booking and custom attribute operations. Request from Uplisting's partner team.")

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        return clean_secret(value, field_name="API key", key=True)

    @field_validator("client_id", mode="before")
    @classmethod
    def client(cls, value):
        if value in (None, ""):
            return None
        if not isinstance(value, str) or not value.strip().isascii() or any(ord(c) < 32 or ord(c) == 127 for c in value.strip()):
            raise ValueError("Paste a valid partner client ID")
        return value.strip()


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class VerifyAccount(_Input):
    """Read the account name and UID to verify the API key."""
    operation: Literal["get_account"] = "get_account"


class ListProperties(_Input):
    """List account properties and their included related data."""
    operation: Literal["list_properties"] = "list_properties"


class GetProperty(_Input):
    """Read a single property and its related data."""
    operation: Literal["get_property"] = "get_property"
    property_id: str = Field(..., min_length=1, max_length=128)


class SearchAvailability(_Input):
    """Find available properties using the documented search criteria."""
    operation: Literal["search_availability"] = "search_availability"
    check_in: Date | None = None
    check_out: Date | None = None
    number_of_guests: int | None = Field(None, ge=1)
    min_price: int | None = Field(None, ge=0)
    max_price: int | None = Field(None, ge=0)
    city: str | None = None

    @model_validator(mode="after")
    def range(self):
        if self.check_in and self.check_out and self.check_out <= self.check_in:
            raise ValueError("Check-out must be after check-in")
        if self.min_price is not None and self.max_price is not None and self.min_price >= self.max_price:
            raise ValueError("Maximum price must exceed minimum price")
        return self


class GetCalendar(_Input):
    """Read one property's calendar, up to twelve months per request."""
    operation: Literal["get_calendar"] = "get_calendar"
    property_id: str = Field(..., min_length=1, max_length=128)
    from_date: Date | None = Field(None, description="Inclusive start date; defaults to today.")
    to_date: Date | None = Field(None, description="End date; at most twelve months per legacy request.")


class CalendarDay(_Input):
    date: Date | None = None
    from_date: Date | None = Field(None, description="Inclusive date range start.")
    to_date: Date | None = Field(None, description="Exclusive date range end.")
    available: StrictBool | None = None
    day_rate: float | None = Field(None, ge=0, allow_inf_nan=False)
    minimum_length_of_stay: int | None = Field(None, ge=1)
    closed_for_arrival: StrictBool | None = None
    closed_for_departure: StrictBool | None = None

    @model_validator(mode="after")
    def range(self):
        if self.date is not None:
            if self.from_date is not None or self.to_date is not None:
                raise ValueError("Choose a date or a date range")
        elif self.from_date is None or self.to_date is None or self.to_date <= self.from_date:
            raise ValueError("Provide a date or an increasing date range")
        if all(getattr(self, k) is None for k in ("available", "day_rate", "minimum_length_of_stay", "closed_for_arrival", "closed_for_departure")):
            raise ValueError("Provide a calendar change")
        return self


class UpdateCalendar(_Input):
    """Queue calendar changes; acceptance does not mean they have been applied."""
    operation: Literal["update_calendar"] = "update_calendar"
    property_id: str = Field(..., min_length=1, max_length=128)
    days: list[CalendarDay] = Field(..., min_length=1, max_length=1000)
    notification_url: str | None = Field(None, pattern=r"^https://[^\s]+$", description="Optional HTTPS endpoint for asynchronous results.")


class ListHooks(_Input):
    """Read registered webhook subscriptions."""
    operation: Literal["list_hooks"] = "list_hooks"


class CreateHook(_Input):
    """Register a webhook; retain its returned secret to verify deliveries."""
    operation: Literal["create_hook"] = "create_hook"
    target_url: str = Field(..., pattern=r"^https://[^\s]+$")
    event: Literal["booking_created", "booking_updated", "booking_removed", "booking_cancelled", "booking_request_approved", "booking_request_declined", "property_created", "property_updated", "property_removed", "prices_changed", "restrictions_changed", "availability_changed", "message_created", "payment_status_changed", "payment_refunded", "review_created"]


class DeleteHook(_Input):
    """Unsubscribe a webhook by its ID."""
    operation: Literal["delete_hook"] = "delete_hook"
    hook_id: str = Field(..., min_length=1, max_length=128)


class RotateHookSecret(_Input):
    """Rotate a webhook's signing secret; update the receiver immediately."""
    operation: Literal["rotate_hook_secret"] = "rotate_hook_secret"
    hook_id: str = Field(..., min_length=1, max_length=128)


class ListCustomBookingAttributes(_Input):
    """List writable booking attribute definitions (requires partner client ID)."""
    operation: Literal["list_custom_booking_attributes"] = "list_custom_booking_attributes"


class CreateCustomBookingAttribute(_Input):
    """Create a namespaced attribute; Uplisting must configure the partner prefix."""
    operation: Literal["create_custom_booking_attribute"] = "create_custom_booking_attribute"
    name: str = Field(..., pattern=r"^[a-z][a-z0-9]*_[a-z0-9_]+$")
    description: str


class UpdateBookingAttributes(_Input):
    """Set writable custom booking attributes (requires partner client ID)."""
    operation: Literal["update_booking_attributes"] = "update_booking_attributes"
    booking_id: str = Field(..., min_length=1, max_length=128)
    attributes: dict[str, str | int | float | bool] = Field(..., min_length=1, description="Only keys returned by List custom booking attributes.")


class CreateBooking(_Input):
    """Create a confirmed booking (requires partner client ID)."""
    operation: Literal["create_booking"] = "create_booking"
    property_id: str = Field(..., min_length=1, max_length=128)
    check_in: Date
    check_out: Date
    guest_name: str | None = None
    guest_email: str | None = None
    guest_phone: str | None = None
    number_of_guests: int | None = Field(None, ge=1)

    @model_validator(mode="after")
    def range(self):
        if self.check_out <= self.check_in:
            raise ValueError("Check-out must be after check-in")
        return self


UplistingOperation = Annotated[Union[VerifyAccount, ListProperties, GetProperty, SearchAvailability,
    GetCalendar, UpdateCalendar, ListHooks, CreateHook, DeleteHook, RotateHookSecret,
    ListCustomBookingAttributes, CreateCustomBookingAttribute, UpdateBookingAttributes, CreateBooking], Field(discriminator="operation")]


class UplistingFullConfig(NodeConfig[UplistingOperation, UplistingAPIKeyCredential]):
    pass


# Every workflow operation maps to exactly one published contract operation.
ROUTES = {
    "get_account": ("GET", "/users/me"),
    "list_properties": ("GET", "/properties"),
    "get_property": ("GET", "/properties/{property_id}"),
    "search_availability": ("GET", "/availability"),
    "get_calendar": ("GET", "/calendar/{property_id}"),
    "update_calendar": ("POST", "/calendar/{property_id}"),
    "list_hooks": ("GET", "/hooks"),
    "create_hook": ("POST", "/hooks"),
    "delete_hook": ("DELETE", "/hooks/{hook_id}"),
    "rotate_hook_secret": ("POST", "/hooks/{hook_id}/rotate_secret"),
    "list_custom_booking_attributes": ("GET", "/v2/custom_booking_attributes"),
    "create_custom_booking_attribute": ("POST", "/v2/custom_booking_attributes"),
    "update_booking_attributes": ("PATCH", "/v2/bookings/{booking_id}"),
    "create_booking": ("POST", "/v2/bookings"),
}


class UplistingNode(WorkflowNode):
    integration_type = "automation-uplisting"
    connection_evidence = ConnectionEvidence(noun="properties", operation="list_properties",
        identity_operation="get_account", label_keys=("name", "id"))

    @classmethod
    def get_config_model(cls):
        return UplistingFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an Uplisting API key")
        op = self.config.config
        credential = self.config.credentials
        method, path = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for field in ("property_id", "hook_id", "booking_id"):
            placeholder = "{" + field + "}"
            if placeholder in path:
                identifier = values.pop(field)
                if identifier in {".", ".."}:
                    raise ValueError("Use a valid Uplisting resource ID")
                path = path.replace(placeholder, quote(identifier, safe=""))
        headers = {"Authorization": "Basic " + base64.b64encode(credential.api_key.encode()).decode(),
            "Accept": "application/json", "Content-Type": "application/json"}
        if path.startswith("/v2/"):
            if not credential.client_id:
                raise ValueError("This V2 operation requires an Uplisting partner client ID")
            headers["X-Uplisting-Client-Id"] = credential.client_id
        body = None
        params = None
        if isinstance(op, GetCalendar):
            params = {k.replace("_date", ""): v for k, v in values.items()}
        elif method == "GET":
            params = values
        elif isinstance(op, UpdateCalendar):
            days = [{k.replace("_date", ""): v for k, v in day.items()} for day in values.pop("days")]
            body = {**values, "calendar": {"days": days}}
        elif isinstance(op, CreateBooking):
            property_id = values.pop("property_id")
            body = {"data": {"attributes": values, "relationships": {"property": {"data": {"type": "properties", "id": property_id}}}}}
        elif isinstance(op, CreateCustomBookingAttribute):
            body = {"data": {"attributes": values}}
        elif isinstance(op, UpdateBookingAttributes):
            body = {"data": values}
        elif isinstance(op, CreateHook):
            body = values
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path, params=params, json=body, headers=headers)
        if not 200 <= response.status_code < 300:
            # Preserve the provider's refusal without reflecting the supplied key.
            message = response.text[:2000].replace(credential.api_key, "[redacted]").replace(headers["Authorization"], "[redacted]")
            raise ValueError(f"Uplisting HTTP {response.status_code}: {message}")
        if response.status_code == 204 or not response.content:
            payload = {}
        else:
            payload = response.json()
            if not isinstance(payload, (dict, list)) or isinstance(payload, dict) and (payload.get("errors") or payload.get("error")):
                raise ValueError("Uplisting returned an error or unexpected response")
        output = {"status": "success", "http_status": response.status_code, "response": payload}
        if isinstance(op, UpdateCalendar):
            output["queued"] = True
            output["applied"] = False
        if isinstance(op, ListProperties):
            rows = payload.get("data", []) if isinstance(payload, dict) else payload
            if not isinstance(rows, list):
                raise ValueError("Uplisting properties response is not a list")
            output["items"] = [{"id": row.get("id"), "name": row.get("attributes", {}).get("name", str(row.get("id", "")))} for row in rows if isinstance(row, dict)]
        if isinstance(op, VerifyAccount):
            if not isinstance(payload, dict) or not payload.get("uid") or not payload.get("name"):
                raise ValueError("Uplisting account identity is missing")
            output.update(name=payload["name"], uid=payload["uid"])
        await self.emit(output)
        return output
