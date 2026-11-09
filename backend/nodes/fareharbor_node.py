"""FareHarbor External API v1: fixed, single-request booking operations.

Contract: https://developer.fareharbor.com/api/external/v1/FareHarbor-External-API.yaml/api-reference
API access requires FareHarbor-issued application and user keys.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Union
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://fareharbor.com/api/external/v1"


class FareHarborAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="FareHarbor API Keys",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developer.fareharbor.com/api/external/v1/",
            "x-credential-instructions": "Paste the application key and user key issued by FareHarbor, and the company shortname from your FareHarbor dashboard URL. API access must be enabled by FareHarbor. These keys are sent only to fareharbor.com.",
        },
    )
    credential_type: Literal["fareharbor_api_key"] = Field(
        "fareharbor_api_key", json_schema_extra={"ui:hidden": True}
    )
    app_key: str = Field(
        ...,
        title="Application key",
        min_length=1,
        max_length=4096,
        json_schema_extra={"ui:widget": "password"},
    )
    user_key: str = Field(
        ...,
        title="User key",
        min_length=1,
        max_length=4096,
        json_schema_extra={"ui:widget": "password"},
    )
    company_shortname: str = Field(
        ...,
        title="Company shortname",
        pattern=r"^[a-zA-Z0-9_-]+$",
        min_length=1,
        max_length=128,
        description="Company shortname in your FareHarbor dashboard URL, for example hawaiianadventures.",
    )

    @field_validator("app_key", "user_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the key without a header or whitespace")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Contact(Input):
    name: str = Field(..., min_length=1)
    email: str = Field(..., min_length=1)
    phone: str = Field(..., min_length=1)


class CustomFieldValue(Input):
    custom_field: StrictInt = Field(..., gt=0)
    value: str | StrictBool | StrictInt | float = Field(
        ...,
        description="String, yes/no boolean or extended-option PK, as required by this custom field.",
    )


class Customer(Input):
    customer_type_rate: StrictInt = Field(
        ...,
        gt=0,
        description="Customer type rate PK returned by the selected availability.",
    )
    custom_field_values: list[CustomFieldValue] | None = None


class BookingData(Input):
    contact: Contact
    customers: list[Customer] = Field(..., min_length=1)
    custom_field_values: list[CustomFieldValue] | None = None
    note: str | None = Field(None, max_length=10000)
    external_id: str | None = Field(None, max_length=128)
    voucher_number: str | None = Field(None, max_length=128)
    amount_paid: StrictInt | None = Field(
        None,
        ge=0,
        description="Amount already collected in minor currency units; omitted uses FareHarbor's default. Explicit null creates full payment.",
    )
    agent: StrictInt | None = Field(None, gt=0)
    agent_name: str | None = Field(None, max_length=128)
    desk: StrictInt | None = Field(None, gt=0)
    desk_name: str | None = Field(None, max_length=128)
    lodging: StrictInt | None = Field(None, gt=0)
    rebooking: UUID | None = None
    orderize_booking: UUID | None = None


class ValidationCustomer(Input):
    customer_type_rate: StrictInt = Field(..., gt=0)


class ValidationCustomFieldValue(Input):
    custom_field: StrictInt = Field(..., gt=0)
    value: str = Field(..., max_length=2048)


class ValidationData(Input):
    contact: Contact
    customers: list[ValidationCustomer] = Field(..., min_length=1)
    custom_field_values: list[ValidationCustomFieldValue] | None = None
    external_id: str | None = None
    note: str | None = None
    voucher_number: str | None = None


class BookingNote(Input):
    note: str = Field(
        ...,
        description="Complete replacement booking note, including an empty string to clear it.",
    )


class CustomerFieldUpdate(Input):
    value: str | StrictBool | StrictInt | float | None = Field(...)


class ResourceUpdate(Input):
    resource_pk: StrictInt = Field(..., gt=0)


class BookingCheckin(Input):
    checkin_status: str | StrictInt | None = Field(
        "auto", description="auto, unchanged, a status PK, or explicit null to reset."
    )
    customer: StrictInt | None = Field(
        None, gt=0, description="Customer PK; null checks in all customers."
    )


class QRCheckin(Input):
    qr_code: str = Field(
        ...,
        min_length=1,
        description="Customer QR code data (a FareHarbor check-in URL); sent as data, never fetched by NoClick.",
    )
    is_whole_booking: StrictBool
    checkin_status: str | StrictInt | None = "auto"


class CrewMember(Input):
    username: str = Field(..., min_length=1)
    role: str | None = None
    note: str | None = None


class FareHarborGetCompanyConfig(Input):
    """Read the connected company."""

    operation: Literal["get_company"] = Field(
        "get_company", json_schema_extra={"ui:hidden": True}
    )


class FareHarborListUsersConfig(Input):
    """List company users."""

    operation: Literal["list_users"] = Field(
        "list_users", json_schema_extra={"ui:hidden": True}
    )


class FareHarborCheckinQrCodeConfig(Input):
    """Check in a customer or booking using QR code data."""

    operation: Literal["checkin_qr_code"] = Field(
        "checkin_qr_code", json_schema_extra={"ui:hidden": True}
    )
    body: QRCheckin


class FareHarborListCheckinStatusesConfig(Input):
    """List company check-in statuses."""

    operation: Literal["list_checkin_statuses"] = Field(
        "list_checkin_statuses", json_schema_extra={"ui:hidden": True}
    )


class FareHarborListLodgingsConfig(Input):
    """List company lodgings."""

    operation: Literal["list_lodgings"] = Field(
        "list_lodgings", json_schema_extra={"ui:hidden": True}
    )


class FareHarborListAvailabilityLodgingsConfig(Input):
    """List lodgings for an availability."""

    operation: Literal["list_availability_lodgings"] = Field(
        "list_availability_lodgings", json_schema_extra={"ui:hidden": True}
    )
    availability_pk: StrictInt = Field(..., gt=0)


class FareHarborListItemsConfig(Input):
    """List bookable items."""

    operation: Literal["list_items"] = Field(
        "list_items", json_schema_extra={"ui:hidden": True}
    )
    require_future_availabilities: Literal["yes", "no"] | None = None
    detailed: Literal["yes", "no"] | None = None
    optimized: Literal["yes", "no"] | None = None


class FareHarborGetItemConfig(Input):
    """Read an item."""

    operation: Literal["get_item"] = Field(
        "get_item", json_schema_extra={"ui:hidden": True}
    )
    item_pk: StrictInt = Field(..., gt=0)
    detailed: Literal["yes", "no"] | None = None


class FareHarborGetAvailabilityConfig(Input):
    """Read an availability and its customer type rates."""

    operation: Literal["get_availability"] = Field(
        "get_availability", json_schema_extra={"ui:hidden": True}
    )
    availability_pk: StrictInt = Field(..., gt=0)
    detailed: Literal["yes", "no"] | None = None


class FareHarborListAvailabilitiesByDateConfig(Input):
    """List minimal availabilities on a company-local date."""

    operation: Literal["list_availabilities_by_date"] = Field(
        "list_availabilities_by_date", json_schema_extra={"ui:hidden": True}
    )
    item_pk: StrictInt = Field(..., gt=0)
    activity_date: date = Field(...)
    detailed: Literal["yes", "no"] | None = None
    bookable_only: Literal["yes", "no"] | None = None
    custom_fields_summary: Literal["yes", "no"] | None = None


class FareHarborListAvailabilitiesByDateRangeConfig(Input):
    """List minimal availabilities in a company-local date range."""

    operation: Literal["list_availabilities_by_date_range"] = Field(
        "list_availabilities_by_date_range", json_schema_extra={"ui:hidden": True}
    )
    item_pk: StrictInt = Field(..., gt=0)
    start_date: date = Field(...)
    end_date: date = Field(...)
    detailed: Literal["yes", "no"] | None = None
    bookable_only: Literal["yes", "no"] | None = None
    custom_fields_summary: Literal["yes", "no"] | None = None

    @model_validator(mode="after")
    def date_order(self):
        if self.end_date < self.start_date:
            raise ValueError("End date must be on or after start date")
        return self


class FareHarborListBookingsConfig(Input):
    """List bookings for an availability."""

    operation: Literal["list_bookings"] = Field(
        "list_bookings", json_schema_extra={"ui:hidden": True}
    )
    availability_pk: StrictInt = Field(..., gt=0)


class FareHarborCreateBookingConfig(Input):
    """Create a booking. FareHarbor may send customer notifications; inspect failures before retrying."""

    operation: Literal["create_booking"] = Field(
        "create_booking", json_schema_extra={"ui:hidden": True}
    )
    availability_pk: StrictInt = Field(..., gt=0)
    body: BookingData


class FareHarborValidateBookingConfig(Input):
    """Validate booking data without creating a booking."""

    operation: Literal["validate_booking"] = Field(
        "validate_booking", json_schema_extra={"ui:hidden": True}
    )
    availability_pk: StrictInt = Field(..., gt=0)
    body: ValidationData


class FareHarborGetBookingConfig(Input):
    """Read a booking by UUID."""

    operation: Literal["get_booking"] = Field(
        "get_booking", json_schema_extra={"ui:hidden": True}
    )
    booking_uuid: UUID = Field(...)
    with_payments: Literal["yes", "no"] | None = None


class FareHarborCancelBookingConfig(Input):
    """Cancel a booking using FareHarbor cancellation rules."""

    operation: Literal["cancel_booking"] = Field(
        "cancel_booking", json_schema_extra={"ui:hidden": True}
    )
    booking_uuid: UUID = Field(...)
    with_payments: Literal["yes", "no"] | None = None


class FareHarborUpdateBookingNoteConfig(Input):
    """Replace a booking note."""

    operation: Literal["update_booking_note"] = Field(
        "update_booking_note", json_schema_extra={"ui:hidden": True}
    )
    booking_uuid: UUID = Field(...)
    body: BookingNote


class FareHarborUpdateCustomerCustomFieldValueConfig(Input):
    """Update an existing customer custom field value."""

    operation: Literal["update_customer_custom_field_value"] = Field(
        "update_customer_custom_field_value", json_schema_extra={"ui:hidden": True}
    )
    booking_uuid: UUID = Field(...)
    custom_field_value_pk: StrictInt = Field(..., gt=0)
    body: CustomerFieldUpdate


class FareHarborUpdateResourceUseConfig(Input):
    """Assign a resource to an existing booking resource use."""

    operation: Literal["update_resource_use"] = Field(
        "update_resource_use", json_schema_extra={"ui:hidden": True}
    )
    booking_uuid: UUID = Field(...)
    resource_use_pk: StrictInt = Field(..., gt=0)
    body: ResourceUpdate


class FareHarborCheckinBookingConfig(Input):
    """Set or reset check-in status for a booking or customer."""

    operation: Literal["checkin_booking"] = Field(
        "checkin_booking", json_schema_extra={"ui:hidden": True}
    )
    booking_uuid: UUID = Field(...)
    body: BookingCheckin


class FareHarborListBookingsByCreateDateConfig(Input):
    """List minimal bookings created on a company-local date."""

    operation: Literal["list_bookings_by_create_date"] = Field(
        "list_bookings_by_create_date", json_schema_extra={"ui:hidden": True}
    )
    activity_date: date = Field(...)


class FareHarborListCrewMembersConfig(Input):
    """List crew assigned to an availability."""

    operation: Literal["list_crew_members"] = Field(
        "list_crew_members", json_schema_extra={"ui:hidden": True}
    )
    availability_pk: StrictInt = Field(..., gt=0)


class FareHarborCreateCrewMemberConfig(Input):
    """Assign a company user to an availability crew."""

    operation: Literal["create_crew_member"] = Field(
        "create_crew_member", json_schema_extra={"ui:hidden": True}
    )
    availability_pk: StrictInt = Field(..., gt=0)
    body: CrewMember


class FareHarborListRolesConfig(Input):
    """List company crew roles."""

    operation: Literal["list_roles"] = Field(
        "list_roles", json_schema_extra={"ui:hidden": True}
    )


FareHarborConfig = Annotated[
    Union[
        FareHarborGetCompanyConfig,
        FareHarborListUsersConfig,
        FareHarborCheckinQrCodeConfig,
        FareHarborListCheckinStatusesConfig,
        FareHarborListLodgingsConfig,
        FareHarborListAvailabilityLodgingsConfig,
        FareHarborListItemsConfig,
        FareHarborGetItemConfig,
        FareHarborGetAvailabilityConfig,
        FareHarborListAvailabilitiesByDateConfig,
        FareHarborListAvailabilitiesByDateRangeConfig,
        FareHarborListBookingsConfig,
        FareHarborCreateBookingConfig,
        FareHarborValidateBookingConfig,
        FareHarborGetBookingConfig,
        FareHarborCancelBookingConfig,
        FareHarborUpdateBookingNoteConfig,
        FareHarborUpdateCustomerCustomFieldValueConfig,
        FareHarborUpdateResourceUseConfig,
        FareHarborCheckinBookingConfig,
        FareHarborListBookingsByCreateDateConfig,
        FareHarborListCrewMembersConfig,
        FareHarborCreateCrewMemberConfig,
        FareHarborListRolesConfig,
    ],
    Field(discriminator="operation"),
]


class FareHarborFullConfig(NodeConfig[FareHarborConfig, FareHarborAPIKeyCredential]):
    pass


OPERATIONS = {
    "get_company": ("GET", "/companies/{company}/", []),
    "list_users": ("GET", "/companies/{company}/users/", []),
    "checkin_qr_code": ("PUT", "/companies/{company}/checkin/", []),
    "list_checkin_statuses": ("GET", "/companies/{company}/checkin-statuses/", []),
    "list_lodgings": ("GET", "/companies/{company}/lodgings/", []),
    "list_availability_lodgings": (
        "GET",
        "/companies/{company}/availabilities/{availability_pk}/lodgings/",
        [],
    ),
    "list_items": (
        "GET",
        "/companies/{company}/items/",
        ["require_future_availabilities", "detailed", "optimized"],
    ),
    "get_item": ("GET", "/companies/{company}/items/{item_pk}/", ["detailed"]),
    "get_availability": (
        "GET",
        "/companies/{company}/availabilities/{availability_pk}/",
        ["detailed"],
    ),
    "list_availabilities_by_date": (
        "GET",
        "/companies/{company}/items/{item_pk}/minimal/availabilities/date/{activity_date}/",
        ["detailed", "bookable_only", "custom_fields_summary"],
    ),
    "list_availabilities_by_date_range": (
        "GET",
        "/companies/{company}/items/{item_pk}/minimal/availabilities/date-range/{start_date}/{end_date}/",
        ["detailed", "bookable_only", "custom_fields_summary"],
    ),
    "list_bookings": (
        "GET",
        "/companies/{company}/availabilities/{availability_pk}/bookings/",
        [],
    ),
    "create_booking": (
        "POST",
        "/companies/{company}/availabilities/{availability_pk}/bookings/",
        [],
    ),
    "validate_booking": (
        "POST",
        "/companies/{company}/availabilities/{availability_pk}/bookings/validate/",
        [],
    ),
    "get_booking": (
        "GET",
        "/companies/{company}/bookings/{booking_uuid}/",
        ["with_payments"],
    ),
    "cancel_booking": (
        "DELETE",
        "/companies/{company}/bookings/{booking_uuid}/",
        ["with_payments"],
    ),
    "update_booking_note": (
        "PUT",
        "/companies/{company}/bookings/{booking_uuid}/note/",
        [],
    ),
    "update_customer_custom_field_value": (
        "PUT",
        "/companies/{company}/bookings/{booking_uuid}/customer-custom-field-values/{custom_field_value_pk}/",
        [],
    ),
    "update_resource_use": (
        "PATCH",
        "/companies/{company}/bookings/{booking_uuid}/resource-uses/{resource_use_pk}/",
        [],
    ),
    "checkin_booking": (
        "PUT",
        "/companies/{company}/bookings/{booking_uuid}/checkin/",
        [],
    ),
    "list_bookings_by_create_date": (
        "GET",
        "/companies/{company}/minimal/bookings-by-create-date/{activity_date}/",
        [],
    ),
    "list_crew_members": (
        "GET",
        "/companies/{company}/availabilities/{availability_pk}/crew-members/",
        [],
    ),
    "create_crew_member": (
        "POST",
        "/companies/{company}/availabilities/{availability_pk}/crew-members/",
        [],
    ),
    "list_roles": ("GET", "/companies/{company}/roles/", []),
}


RESPONSE_SHAPES = {
    "get_company": ("company", dict),
    "list_users": ("users", list),
    "checkin_qr_code": ("booking", dict),
    "list_checkin_statuses": ("checkin_statuses", list),
    "list_lodgings": ("lodgings", list),
    "list_availability_lodgings": ("lodgings", list),
    "list_items": ("items", list),
    "get_item": ("item", dict),
    "get_availability": ("availability", dict),
    "list_availabilities_by_date": ("availabilities", list),
    "list_availabilities_by_date_range": ("availabilities", list),
    "list_bookings": ("bookings", list),
    "create_booking": ("booking", dict),
    "validate_booking": ("is_bookable", bool),
    "get_booking": ("booking", dict),
    "cancel_booking": ("booking", dict),
    "update_booking_note": ("booking", dict),
    "update_customer_custom_field_value": ("custom_field_value", dict),
    "update_resource_use": ("booking", dict),
    "checkin_booking": ("booking", dict),
    "list_bookings_by_create_date": ("bookings", list),
    "list_crew_members": ("crew_members", list),
    "create_crew_member": ("crew_member", dict),
    "list_roles": ("roles", list),
}


class FareHarborNode(WorkflowNode):
    integration_type = "automation-fareharbor"
    connection_evidence = ConnectionEvidence(
        identity_operation="get_company", noun="company"
    )

    @classmethod
    def get_config_model(cls):
        return FareHarborFullConfig

    async def execute(self, inputs):
        if (
            not isinstance(self.config, FareHarborFullConfig)
            or not self.config.credentials
        ):
            raise ValueError("Connect FareHarbor API keys first")
        credential = self.config.credentials
        config = self.config.config
        method, template, query_fields = OPERATIONS[config.operation]
        values = config.model_dump(mode="json")
        path = template.format(company=credential.company_shortname, **values)
        params = {
            name: values[name] for name in query_fields if values[name] is not None
        }
        kwargs = {
            "params": params,
            "headers": {
                "X-FareHarbor-API-App": credential.app_key,
                "X-FareHarbor-API-User": credential.user_key,
                "Accept": "application/json",
            },
        }
        if hasattr(config, "body"):
            # Preserve explicit nulls (check-in reset and amount_paid semantics).
            kwargs["json"] = config.body.model_dump(mode="json", exclude_unset=True)
        async with guarded_async_client(
            timeout=30.0, follow_redirects=False, trust_env=False
        ) as client:
            response = await client.request(method, BASE + path, **kwargs)
        if response.status_code != 200:
            message = "FareHarbor request failed; check account permissions and request data before retrying."
            try:
                failure = response.json()
                if isinstance(failure, dict) and isinstance(
                    failure.get("message"), str
                ):
                    message = failure["message"]
            except (ValueError, UnicodeDecodeError):
                pass
            # Retain provider rejection text for connection evidence, redacting keys.
            for secret in (credential.app_key, credential.user_key):
                message = message.replace(secret, "[redacted]")
            return {
                "status": "error",
                "http_status": response.status_code,
                "message": message,
                "operation": config.operation,
            }
        try:
            data = response.json()
        except (ValueError, UnicodeDecodeError):
            raise ValueError("FareHarbor returned an invalid JSON response") from None
        if (
            not isinstance(data, dict)
            or config.operation != "validate_booking"
            and ("error" in data or "code" in data and "message" in data)
        ):
            raise ValueError(
                "FareHarbor returned an unexpected response or error envelope"
            )
        response_key, response_type = RESPONSE_SHAPES[config.operation]
        if response_key not in data or type(data[response_key]) is not response_type:
            raise ValueError(
                "FareHarbor response is missing the expected operation result"
            )
        if config.operation == "get_company" and not isinstance(
            data["company"].get("name"), str
        ):
            raise ValueError("FareHarbor company response is missing its name")
        # Each operation is one provider call. No implicit pagination or retries.
        return {"status": "success", "operation": config.operation, "data": data}
