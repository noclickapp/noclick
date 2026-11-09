"""Aryeo v1 API operations, pinned to the published 2021-06-17 contract.

Personal access tokens are created in the group's developer settings.
Each operation performs exactly one request; pagination is returned for callers.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.aryeo.com/v1"
API_VERSION = "2021-06-17"


class AryeoAPITokenCredential(BaseModel):
    model_config = ConfigDict(
        title="Aryeo API Token",
        extra="ignore",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.aryeo.com/",
            "x-credential-instructions": "In Aryeo, open your group's developer settings and generate a personal access token. Paste only the token, without the Bearer prefix. NoClick reads your listings to check the connection. The token's user and current group determine which records you can access.",
        },
    )
    credential_type: Literal["aryeo_api_token"] = Field(
        "aryeo_api_token", json_schema_extra={"ui:hidden": True}
    )
    api_token: str = Field(
        ...,
        title="API token",
        min_length=1,
        max_length=8192,
        repr=False,
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if not value.isascii() or any(
            c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value
        ):
            raise ValueError("Paste only the API token, without a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def valid_values(cls, value, info):
        name = info.field_name
        if value is None:
            return value
        if name.endswith("_id") or name.endswith("_ids"):
            for item in value if isinstance(value, list) else [value]:
                if str(UUID(item)) != item.lower():
                    raise ValueError("Use a canonical Aryeo UUID")
        if name in {
            "start_at",
            "end_at",
            "filter_start_at",
            "filter_end_at",
            "filter_start_at_gte",
            "filter_start_at_lte",
        }:
            if datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
                raise ValueError("Use an ISO 8601 timestamp with a timezone offset")
        return value

    @model_validator(mode="after")
    def time_order(self):
        for start, end in (
            ("start_at", "end_at"),
            ("filter_start_at", "filter_end_at"),
            ("filter_start_at_gte", "filter_start_at_lte"),
        ):
            a, b = getattr(self, start, None), getattr(self, end, None)
            if (
                a
                and b
                and datetime.fromisoformat(a.replace("Z", "+00:00"))
                >= datetime.fromisoformat(b.replace("Z", "+00:00"))
            ):
                raise ValueError("The end time must follow the start time")
        return self


class AryeoListAppointments(_Input):
    "List all appointments. By default, returns a list of appointments that have been scheduled and have not been canceled"

    operation: Literal["list_appointments"] = Field(
        "list_appointments", json_schema_extra={"ui:hidden": True}
    )
    include: str | None = Field(None, max_length=255)
    filter_tense: Literal["PAST", "UPCOMING"] | None = Field(
        None, min_length=1, max_length=100
    )
    filter_start_at_gte: str | None = Field(None, min_length=1, max_length=100)
    filter_start_at_lte: str | None = Field(None, min_length=1, max_length=100)
    filter_user_ids: list[str] | None = Field(None)
    sort: str | None = Field(None, min_length=1, max_length=100)
    per_page: str = Field("25", max_length=5, pattern=r"[1-9][0-9]{0,4}")
    page: str = Field("1", max_length=5, pattern=r"[1-9][0-9]{0,4}")


class AryeoCancelAppointment(_Input):
    "Cancel an appointment. The appointments order's customer can be optionally notified of this change."

    operation: Literal["cancel_appointment"] = Field(
        "cancel_appointment", json_schema_extra={"ui:hidden": True}
    )
    appointment_id: str = Field(..., max_length=255, min_length=36)
    notify_customer: bool = Field(
        False,
        description="Sends a notification to the appointment's order's customer that the appointment was canceled.",
    )


class AryeoRescheduleAppointment(_Input):
    "Reschedule an appointment. The appointments order's customer can be optionally notified of this change."

    operation: Literal["reschedule_appointment"] = Field(
        "reschedule_appointment", json_schema_extra={"ui:hidden": True}
    )
    appointment_id: str = Field(..., max_length=255, min_length=36)
    start_at: str = Field(
        ...,
        max_length=255,
        description="The new date and time (ISO 8601 format) when the appointment is set to start.",
    )
    end_at: str = Field(
        ...,
        max_length=255,
        description="The new date and time (ISO 8601 format) when the appointment is set to end.",
    )
    notify_customer: bool = Field(
        False,
        description="Send a notification to the appointment's order's customer that the appointment was rescheduled.",
    )


class AryeoListListings(_Input):
    "Lists all listings available to a group."

    operation: Literal["list_listings"] = Field(
        "list_listings", json_schema_extra={"ui:hidden": True}
    )
    include: str | None = Field(None, max_length=255)
    filter_search: str | None = Field(None, min_length=1, max_length=255)
    filter_address: str | None = Field(None, min_length=1, max_length=255)
    filter_list_agent: str | None = Field(None, min_length=1, max_length=255)
    filter_status: Literal[
        "DRAFT",
        "COMING_SOON",
        "FOR_LEASE",
        "FOR_SALE",
        "PENDING_SALE",
        "PENDING_LEASE",
        "SOLD",
        "LEASED",
        "OFF_MARKET",
        "null",
    ] | None = Field(None, min_length=1, max_length=100)
    filter_active: bool | None = Field(None)
    filter_price_gte: float | None = Field(None)
    filter_price_lte: float | None = Field(None)
    filter_square_feet_gte: float | None = Field(None)
    filter_square_feet_lte: float | None = Field(None)
    filter_bedrooms_gte: int | None = Field(None)
    filter_bedrooms_lte: int | None = Field(None)
    filter_bathrooms_gte: float | None = Field(None)
    filter_bathrooms_lte: float | None = Field(None)
    sort: str | None = Field(None, min_length=1, max_length=100)
    per_page: str = Field("25", max_length=5, pattern=r"[1-9][0-9]{0,4}")
    page: str = Field("1", max_length=5, pattern=r"[1-9][0-9]{0,4}")


class AryeoGetListing(_Input):
    "Retrieves the details of a listing with the given ID."

    operation: Literal["get_listing"] = Field(
        "get_listing", json_schema_extra={"ui:hidden": True}
    )
    listing_id: str = Field(..., min_length=36, max_length=36)
    include: str | None = Field(None, max_length=255)


class AryeoListProducts(_Input):
    "List all products of a group."

    operation: Literal["list_products"] = Field(
        "list_products", json_schema_extra={"ui:hidden": True}
    )
    sort: str | None = Field(None, min_length=1, max_length=100)
    per_page: str = Field("25", max_length=5, pattern=r"[1-9][0-9]{0,4}")
    page: str = Field("1", max_length=5, pattern=r"[1-9][0-9]{0,4}")
    filter_search: str | None = Field(None, max_length=255)
    filter_include_inactive: bool | None = Field(None)
    filter_category_ids: list[str] | None = Field(None)
    filter_type: str | None = Field(None, max_length=255)


class AryeoListOrders(_Input):
    "Lists all orders of a group."

    operation: Literal["list_orders"] = Field(
        "list_orders", json_schema_extra={"ui:hidden": True}
    )
    sort: str | None = Field(None, min_length=1, max_length=100)
    per_page: str = Field("25", max_length=5, pattern=r"[1-9][0-9]{0,4}")
    page: str = Field("1", max_length=5, pattern=r"[1-9][0-9]{0,4}")


class AryeoCreateOrder(_Input):
    "Create an order."

    operation: Literal["create_order"] = Field(
        "create_order", json_schema_extra={"ui:hidden": True}
    )
    fulfillment_status: Literal["FULFILLED", "UNFULFILLED"] | None = Field(
        None,
        max_length=255,
        description='The fulfillment status of the order. Defaults to "UNFULFILLED".',
    )
    internal_notes: str | None = Field(
        None,
        max_length=2550,
        description="Internal notes that will be attached to the order. Viewable only by the team.",
    )
    address_id: str | None = Field(
        None,
        min_length=36,
        max_length=36,
        description="ID of the address to associate with the order. UUID Version 4.",
    )
    customer_id: str | None = Field(
        None,
        min_length=36,
        max_length=36,
        description="ID of the customer to associate with the order. UUID Version 4.",
    )
    notify: bool = Field(
        False,
        description="Indicates if the customer and creator notifications should be sent when creating the order. Requires an address and customer to be set in order for the notifications to be sent.",
    )
    lock_download_for_payment: bool | None = Field(
        None,
        description="Indicates if the downloads for the attached listing should be locked while there is an outstanding balance on the order.",
    )
    allow_payments_before_fulfillment: bool | None = Field(
        None,
        description="Indicates if the order will allow payments from the customer before the order is marked as fulfilled.",
    )


class AryeoGetOrder(_Input):
    "Retrieves the details of an order with the given ID."

    operation: Literal["get_order"] = Field(
        "get_order", json_schema_extra={"ui:hidden": True}
    )
    order_id: str = Field(..., min_length=36, max_length=36)
    include: str | None = Field(None, max_length=255)


class AryeoListAvailableDates(_Input):
    "Fetch available calendar days for scheduling or rescheduling an appointment. Availability can be retrieved using a specific start & end date range, or using a timeframe. When using a timeframe, the page parameter can be used to flip through weeks, months, etc."

    operation: Literal["list_available_dates"] = Field(
        "list_available_dates", json_schema_extra={"ui:hidden": True}
    )
    filter_user_ids: list[str] | None = Field(None)
    filter_appointment_id: str | None = Field(None, min_length=1, max_length=100)
    filter_start_at: str | None = Field(None, min_length=1, max_length=100)
    filter_end_at: str | None = Field(None, min_length=1, max_length=100)
    duration: int | None = Field(None, ge=1, le=360)
    interval: int | None = Field(None, ge=1, le=360)
    page: int = Field(1, ge=1, le=99999)
    per_page: int = Field(25, ge=1, le=99999)


class AryeoListAvailableTimeslots(_Input):
    "Fetch available timeslots for scheduling or rescheduling an appointment. Timeslots can be retrieved using a specific start & end date range, or using a timeframe. When using a timeframe, the page parameter can be used to flip through days or weeks."

    operation: Literal["list_available_timeslots"] = Field(
        "list_available_timeslots", json_schema_extra={"ui:hidden": True}
    )
    filter_user_ids: list[str] | None = Field(None)
    filter_appointment_id: str | None = Field(None, min_length=1, max_length=100)
    filter_start_at: str | None = Field(None, min_length=1, max_length=100)
    filter_end_at: str | None = Field(None, min_length=1, max_length=100)
    duration: int | None = Field(None, ge=1, le=360)
    interval: int | None = Field(None, ge=1, le=360)
    page: int = Field(1, ge=1, le=99999)
    per_page: int = Field(25, ge=1, le=99999)


class AryeoListUnconfirmedAppointments(_Input):
    "List all unconfirmed appointments. These are appointments that have not been scheduled."

    operation: Literal["list_unconfirmed_appointments"] = Field(
        "list_unconfirmed_appointments", json_schema_extra={"ui:hidden": True}
    )
    include: str | None = Field(None, max_length=255)
    filter_user_ids: list[str] | None = Field(None)
    sort: str | None = Field(None, min_length=1, max_length=100)
    per_page: str = Field("25", max_length=5, pattern=r"[1-9][0-9]{0,4}")
    page: str = Field("1", max_length=5, pattern=r"[1-9][0-9]{0,4}")


class AryeoGetUnconfirmedAppointment(_Input):
    "Retrieves the details of an unconfirmed appointment with the given ID."

    operation: Literal["get_unconfirmed_appointment"] = Field(
        "get_unconfirmed_appointment", json_schema_extra={"ui:hidden": True}
    )
    unconfirmed_appointment_id: str = Field(..., max_length=255, min_length=36)
    include: str | None = Field(None, max_length=255)


class AryeoListVendors(_Input):
    "Lists all vendors available to a group."

    operation: Literal["list_vendors"] = Field(
        "list_vendors", json_schema_extra={"ui:hidden": True}
    )
    include: str | None = Field(None, max_length=255)


class AryeoGetVendor(_Input):
    "Retrieves the details of a vendor with the given ID."

    operation: Literal["get_vendor"] = Field(
        "get_vendor", json_schema_extra={"ui:hidden": True}
    )
    vendor_id: str = Field(..., min_length=36, max_length=36)
    include: str | None = Field(None, max_length=255)


AryeoConfig = Annotated[
    Union[
        AryeoListAppointments,
        AryeoCancelAppointment,
        AryeoRescheduleAppointment,
        AryeoListListings,
        AryeoGetListing,
        AryeoListProducts,
        AryeoListOrders,
        AryeoCreateOrder,
        AryeoGetOrder,
        AryeoListAvailableDates,
        AryeoListAvailableTimeslots,
        AryeoListUnconfirmedAppointments,
        AryeoGetUnconfirmedAppointment,
        AryeoListVendors,
        AryeoGetVendor,
    ],
    Field(discriminator="operation"),
]


class AryeoFullConfig(NodeConfig[AryeoConfig, AryeoAPITokenCredential]):
    pass


ROUTES = {
    "list_appointments": ("GET", "/appointments"),
    "cancel_appointment": ("PUT", "/appointments/{appointment_id}/cancel"),
    "reschedule_appointment": ("PUT", "/appointments/{appointment_id}/reschedule"),
    "list_listings": ("GET", "/listings"),
    "get_listing": ("GET", "/listings/{listing_id}"),
    "list_products": ("GET", "/products"),
    "list_orders": ("GET", "/orders"),
    "create_order": ("POST", "/orders"),
    "get_order": ("GET", "/orders/{order_id}"),
    "list_available_dates": ("GET", "/scheduling/available-dates"),
    "list_available_timeslots": ("GET", "/scheduling/available-timeslots"),
    "list_unconfirmed_appointments": ("GET", "/unconfirmed-appointments"),
    "get_unconfirmed_appointment": (
        "GET",
        "/unconfirmed-appointments/{unconfirmed_appointment_id}",
    ),
    "list_vendors": ("GET", "/vendors"),
    "get_vendor": ("GET", "/vendors/{vendor_id}"),
}

QUERY_FIELDS = {
    "list_appointments": {
        "include": "include",
        "filter_tense": "filter[tense]",
        "filter_start_at_gte": "filter[start_at_gte]",
        "filter_start_at_lte": "filter[start_at_lte]",
        "filter_user_ids": "filter[user_ids]",
        "sort": "sort",
        "per_page": "per_page",
        "page": "page",
    },
    "cancel_appointment": {"appointment_id": "appointment_id"},
    "reschedule_appointment": {"appointment_id": "appointment_id"},
    "list_listings": {
        "include": "include",
        "filter_search": "filter[search]",
        "filter_address": "filter[address]",
        "filter_list_agent": "filter[list_agent]",
        "filter_status": "filter[status]",
        "filter_active": "filter[active]",
        "filter_price_gte": "filter[price_gte]",
        "filter_price_lte": "filter[price_lte]",
        "filter_square_feet_gte": "filter[square_feet_gte]",
        "filter_square_feet_lte": "filter[square_feet_lte]",
        "filter_bedrooms_gte": "filter[bedrooms_gte]",
        "filter_bedrooms_lte": "filter[bedrooms_lte]",
        "filter_bathrooms_gte": "filter[bathrooms_gte]",
        "filter_bathrooms_lte": "filter[bathrooms_lte]",
        "sort": "sort",
        "per_page": "per_page",
        "page": "page",
    },
    "get_listing": {"listing_id": "listing_id", "include": "include"},
    "list_products": {
        "sort": "sort",
        "per_page": "per_page",
        "page": "page",
        "filter_search": "filter[search]",
        "filter_include_inactive": "filter[include_inactive]",
        "filter_category_ids": "filter[category_ids]",
        "filter_type": "filter[type]",
    },
    "list_orders": {"sort": "sort", "per_page": "per_page", "page": "page"},
    "create_order": {},
    "get_order": {"order_id": "order_id", "include": "include"},
    "list_available_dates": {
        "filter_user_ids": "filter[user_ids]",
        "filter_appointment_id": "filter[appointment_id]",
        "filter_start_at": "filter[start_at]",
        "filter_end_at": "filter[end_at]",
        "duration": "duration",
        "interval": "interval",
        "page": "page",
        "per_page": "per_page",
    },
    "list_available_timeslots": {
        "filter_user_ids": "filter[user_ids]",
        "filter_appointment_id": "filter[appointment_id]",
        "filter_start_at": "filter[start_at]",
        "filter_end_at": "filter[end_at]",
        "duration": "duration",
        "interval": "interval",
        "page": "page",
        "per_page": "per_page",
    },
    "list_unconfirmed_appointments": {
        "include": "include",
        "filter_user_ids": "filter[user_ids]",
        "sort": "sort",
        "per_page": "per_page",
        "page": "page",
    },
    "get_unconfirmed_appointment": {
        "unconfirmed_appointment_id": "unconfirmed_appointment_id",
        "include": "include",
    },
    "list_vendors": {"include": "include"},
    "get_vendor": {"vendor_id": "vendor_id", "include": "include"},
}


class AryeoNode(WorkflowNode):
    integration_type = "automation-aryeo"
    connection_evidence = ConnectionEvidence(
        noun="listings", operation="list_listings", label_keys=("mls_number", "id")
    )

    @classmethod
    def get_config_model(cls):
        return AryeoFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect an Aryeo API token")
        op = self.config.config
        method, path = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        for name in list(values):
            placeholder = "{" + name + "}"
            if placeholder in path:
                path = path.replace(placeholder, values.pop(name))
        kwargs = {}
        if method == "GET":
            # OpenAPI form/explode arrays use repeated query keys. No links are followed.
            kwargs["params"] = [
                (
                    QUERY_FIELDS[op.operation][name],
                    str(item).lower() if isinstance(item, bool) else str(item),
                )
                for name, value in values.items()
                for item in (value if isinstance(value, list) else [value])
            ]
        else:
            kwargs["json"] = values
        token = self.config.credentials.api_token
        async with guarded_async_client(
            timeout=30, follow_redirects=False, trust_env=False
        ) as client:
            response = await client.request(
                method,
                BASE_URL + path,
                headers={
                    "Authorization": "Bearer " + token,
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Aryeo-Version": API_VERSION,
                },
                **kwargs,
            )
        expected = 201 if op.operation == "create_order" else 200
        if response.status_code != expected:
            return {
                "status": "error",
                "http_status": response.status_code,
                "error": response.text.replace(token, "[redacted]")[:2000],
            }
        if len(response.content) > 10_000_000:
            raise ValueError("Aryeo returned an oversized response")
        body = response.json()
        if not isinstance(body, dict) or body.get("status") != "success":
            raise ValueError("Aryeo did not return a successful resource envelope")
        data = body.get("data")
        collection = op.operation.startswith("list_")
        if data is not None and not isinstance(data, list if collection else dict):
            raise ValueError("Aryeo returned an unexpected resource shape")
        # Preserve provider data and page metadata; callers advance page explicitly.
        return {
            "status": "success",
            "data": data,
            **{key: body[key] for key in ("meta", "links") if key in body},
        }
