"""Checkfront Management API v4.0, using manually supplied token pairs.

Contract: https://storage.googleapis.com/cf-apiv4-docs-bucket/v4.0-Management.json
Each operation sends exactly one documented API request. Lists return a single
page; no provider-supplied URL is followed and writes are never retried.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client, normalize_provider_https_origin

CREDENTIAL_TYPE = "checkfront_api_key"
DOCS = "https://storage.googleapis.com/cf-apiv4-docs-bucket/v4.0-Management.json"


def _origin(value):
    if not isinstance(value, str):
        raise ValueError("Paste the Checkfront tenant HTTPS origin")
    host = urlsplit(value if "://" in value else "https://" + value).hostname or ""
    domain = next((d for d in ("manage.na1.bookingplatform.app", "manage.eu1.bookingplatform.app") if host.endswith("." + d)), "checkfront.com")
    return normalize_provider_https_origin(value, domain, field_name="Checkfront tenant URL")


class CheckfrontAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Checkfront API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://api.checkfront.com/overview/connecting.html",
            "x-credential-instructions": "In Checkfront, open Manage > Developer and create a token-pair application. Paste its API key and API secret, plus your tenant URL (for example https://your-company.checkfront.com). Migrated accounts can use their manage.na1.bookingplatform.app or manage.eu1.bookingplatform.app URL. API access requires an eligible paid account. The pair is sent using HTTP Basic authentication. Use a credential with permission for the selected operations."})
    credential_type: Literal["checkfront_api_key"] = Field("checkfront_api_key", json_schema_extra={"ui:hidden": True})
    tenant_url: str = Field(..., title="Tenant URL", description="Your Checkfront HTTPS origin, without /api/4.0.")
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})
    api_secret: str = Field(..., title="API secret", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})
    _tenant = field_validator("tenant_url", mode="before")(_origin)

    @field_validator("api_key", "api_secret", mode="before")
    @classmethod
    def secret(cls, value):
        value = clean_secret(value, field_name="API key or secret")
        if not value.isascii() or any(c.isspace() for c in value) or ":" in value:
            raise ValueError("Paste the API key or secret without a header, spaces or colon")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    limit: int = Field(50, ge=1, le=250, description="Maximum results in this page. Use next_offset to continue.")
    offset: int = Field(0, ge=0, le=10_000_000)


class _Booking(_Input):
    booking_code: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$", description="Booking code, for example ABCD-010115.")


class _Customer(_Input):
    customer_id: int = Field(..., ge=1)


class ListBookings(_Page):
    """Search bookings by contact, creation time or travel dates; returns one page."""
    operation: Literal["list_bookings"] = "list_bookings"
    search: str | None = Field(None, max_length=1000)
    customer_id: int | None = Field(None, ge=1)
    start_min: str | None = Field(None, description="Inclusive ISO 8601 date-time.")
    start_max: str | None = Field(None, description="ISO 8601 date-time upper bound.")
    created_min: str | None = Field(None, description="ISO 8601 date-time lower bound.")
    created_max: str | None = Field(None, description="ISO 8601 date-time upper bound.")

    @field_validator("start_min", "start_max", "created_min", "created_max")
    @classmethod
    def date_time(cls, value):
        if value is not None:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("Include a timezone in the ISO 8601 date-time")
        return value


class GetBooking(_Booking):
    operation: Literal["get_booking"] = "get_booking"


class CustomerFields(_Input):
    customer_first_name: str | None = None
    customer_last_name: str | None = None
    customer_email: str | None = None
    customer_address: str | None = None
    customer_city: str | None = None
    customer_country: str | None = Field(None, min_length=2, max_length=2)
    customer_region: str | None = None
    customer_postal_zip: str | None = None
    customer_phone: str | None = None
    customer_email_optin: StrictBool | None = None

    @model_validator(mode="after")
    def nonempty(self):
        if not self.model_fields_set:
            raise ValueError("Supply at least one customer field")
        if any(getattr(self, name) is None for name in self.model_fields_set):
            raise ValueError("Standard customer fields cannot be null; omit fields to retain their values")
        return self


class UpdateBooking(_Booking):
    """Update the booking's customer/contact fields, partner or language."""
    operation: Literal["update_booking"] = "update_booking"
    customer_id: int | None = Field(None, ge=1)
    partner_id: int | None = Field(None, ge=1)
    language: str | None = Field(None, min_length=1, max_length=32)
    fields: CustomerFields | None = None

    @model_validator(mode="after")
    def nonempty(self):
        if not any(getattr(self, n) is not None for n in ("customer_id", "partner_id", "language", "fields")):
            raise ValueError("Supply a booking field to update")
        return self


class _GuestAction(_Booking):
    guest_activity_ids: list[Annotated[int, Field(ge=1)]] | None = Field(None, min_length=1, max_length=250,
        description="Guest activity slot IDs; omit to apply to all guests in this booking.")


class CheckInBooking(_GuestAction):
    operation: Literal["checkin_booking"] = "checkin_booking"


class CheckOutBooking(_GuestAction):
    operation: Literal["checkout_booking"] = "checkout_booking"


class ResetBookingCheckIn(_GuestAction):
    operation: Literal["reset_booking_checkin"] = "reset_booking_checkin"


class ChangeBookingStatus(_Booking):
    """Change status; notifications, payment creation and overbooking are explicit switches."""
    operation: Literal["change_booking_status"] = "change_booking_status"
    status_id: str = Field(..., min_length=1, max_length=100, description="Status ID from list_statuses, such as PAID.")
    send_notifications: StrictBool = Field(False, description="Send the provider's configured status email notifications.")
    apply_payment: StrictBool = Field(False, description="Create a POS transaction for the balance when setting PAID.")
    allow_overbooking: StrictBool = Field(False, description="Allow inventory overbooking when setting a locked status.")


class ListBookingNotes(_Booking, _Page):
    operation: Literal["list_booking_notes"] = "list_booking_notes"


class _Note(_Booking):
    note_id: int = Field(..., ge=1)


class GetBookingNote(_Note):
    operation: Literal["get_booking_note"] = "get_booking_note"


class CreateBookingNote(_Booking):
    operation: Literal["create_booking_note"] = "create_booking_note"
    body: str = Field(..., min_length=1, max_length=100000, description="Note content.")
    public: StrictBool = Field(False, description="Show this note on customer-visible invoices.")


class UpdateBookingNote(_Note):
    operation: Literal["update_booking_note"] = "update_booking_note"
    body: str = Field(..., min_length=1, max_length=100000)
    public: StrictBool | None = Field(None, description="Omit to retain current invoice visibility.")


class DeleteBookingNote(_Note):
    operation: Literal["delete_booking_note"] = "delete_booking_note"


class ListCustomers(_Page):
    operation: Literal["list_customers"] = "list_customers"
    email: str | None = Field(None, max_length=1000)
    first_name: str | None = Field(None, max_length=1000)
    last_name: str | None = Field(None, max_length=1000)
    status: Literal["active", "archived", "blocked"] = "active"


class GetCustomer(_Customer):
    operation: Literal["get_customer"] = "get_customer"


class CreateCustomer(_Input):
    operation: Literal["create_customer"] = "create_customer"
    fields: CustomerFields
    language: str | None = Field(None, min_length=1, max_length=32)


class UpdateCustomer(_Customer):
    operation: Literal["update_customer"] = "update_customer"
    fields: CustomerFields
    language: str | None = Field(None, min_length=1, max_length=32)


class ArchiveCustomer(_Customer):
    """Archive the customer profile; does not claim permanent deletion."""
    operation: Literal["archive_customer"] = "archive_customer"


class ListCustomerBookings(_Customer, _Page):
    operation: Literal["list_customer_bookings"] = "list_customer_bookings"


class ListProducts(_Page):
    operation: Literal["list_products"] = "list_products"
    search: str | None = Field(None, max_length=1000)
    status: Literal["active", "draft", "archived", "unarchived", "all"] = "active"


class GetProduct(_Input):
    operation: Literal["get_product"] = "get_product"
    product_id: int = Field(..., ge=1)


class ListCategories(_Page):
    operation: Literal["list_categories"] = "list_categories"


class ListStatuses(_Page):
    operation: Literal["list_statuses"] = "list_statuses"


class GetCompany(_Input):
    operation: Literal["get_company"] = "get_company"


class ListBookingTransactions(_Booking, _Page):
    operation: Literal["list_booking_transactions"] = "list_booking_transactions"


class ListBookingGuests(_Booking, _Page):
    operation: Literal["list_booking_guests"] = "list_booking_guests"


CheckfrontOperation = Annotated[Union[
    ListBookings, GetBooking, UpdateBooking, CheckInBooking, CheckOutBooking,
    ResetBookingCheckIn, ChangeBookingStatus, ListBookingNotes, GetBookingNote,
    CreateBookingNote, UpdateBookingNote, DeleteBookingNote, ListCustomers,
    GetCustomer, CreateCustomer, UpdateCustomer, ArchiveCustomer, ListCustomerBookings,
    ListProducts, GetProduct, ListCategories, ListStatuses, GetCompany,
    ListBookingTransactions, ListBookingGuests,
], Field(discriminator="operation")]


class CheckfrontConfig(NodeConfig[CheckfrontOperation, CheckfrontAPIKeyCredential]):
    pass


# Method and path are fixed by operation, never supplied by workflow input.
ROUTES = {
    "list_bookings": ("GET", "/bookings"),
    "get_booking": ("GET", "/bookings/{booking_code}"),
    "update_booking": ("PATCH", "/bookings/{booking_code}"),
    "checkin_booking": ("POST", "/bookings/{booking_code}/checkin"),
    "checkout_booking": ("POST", "/bookings/{booking_code}/checkout"),
    "reset_booking_checkin": ("POST", "/bookings/{booking_code}/checkin-reset"),
    "change_booking_status": ("POST", "/bookings/{booking_code}/changeStatus"),
    "list_booking_notes": ("GET", "/bookings/{booking_code}/notes/"),
    "get_booking_note": ("GET", "/bookings/{booking_code}/notes/{note_id}"),
    "create_booking_note": ("POST", "/bookings/{booking_code}/notes"),
    "update_booking_note": ("PATCH", "/bookings/{booking_code}/notes/{note_id}"),
    "delete_booking_note": ("DELETE", "/bookings/{booking_code}/notes/{note_id}"),
    "list_customers": ("GET", "/customers/"),
    "get_customer": ("GET", "/customers/{customer_id}"),
    "create_customer": ("POST", "/customers"),
    "update_customer": ("PATCH", "/customers/{customer_id}"),
    "archive_customer": ("DELETE", "/customers/{customer_id}"),
    "list_customer_bookings": ("GET", "/customers/{customer_id}/bookings"),
    "list_products": ("GET", "/products"),
    "get_product": ("GET", "/products/{product_id}"),
    "list_categories": ("GET", "/categories"),
    "list_statuses": ("GET", "/statuses"),
    "get_company": ("GET", "/company"),
    "list_booking_transactions": ("GET", "/bookings/{booking_code}/transactions"),
    "list_booking_guests": ("GET", "/bookings/{booking_code}/guests/"),
}
WIRE_NAMES = {"customer_id": "customerId", "partner_id": "partnerId", "status_id": "statusId",
    "send_notifications": "sendNotifications", "apply_payment": "applyPayment", "allow_overbooking": "allowOverbooking",
    "start_min": "startMin", "start_max": "startMax", "created_min": "createdMin", "created_max": "createdMax",
    "first_name": "firstName", "last_name": "lastName"}


def _redact(value, credential):
    if isinstance(value, dict):
        return {k: _redact(v, credential) for k, v in value.items()
            if k.lower() not in {"cfx", "gcfx", "password", "access_token", "refresh_token", "api_key", "api_secret", "authorization"}}
    if isinstance(value, list):
        return [_redact(v, credential) for v in value]
    if isinstance(value, str):
        # Include the Basic payload, in case an upstream error echoes it.
        auth = httpx.BasicAuth(credential.api_key, credential.api_secret)._auth_header
        for secret in (auth, auth.removeprefix("Basic "), credential.api_key, credential.api_secret):
            value = value.replace(secret, "[redacted]")
    return value


class CheckfrontNode(WorkflowNode):
    integration_type = "automation-checkfront"
    connection_evidence = ConnectionEvidence(noun="products", operation="list_products", label_keys=("name", "sku", "id"))
    edit_examples = ["Find bookings created today", "Add a private note to this booking", "Create a customer profile"]

    @classmethod
    def get_config_model(cls):
        return CheckfrontConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Checkfront API key and secret")
        cred = self.config.credentials
        op = self.config.config
        method, template = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True)
        path_fields = re.findall(r"\{(\w+)\}", template)
        path = template.format(**{k: quote(str(values[k]), safe="") for k in path_fields})
        payload = {WIRE_NAMES.get(k, k): v for k, v in values.items() if k not in {"operation", *path_fields}}
        if isinstance(op, _GuestAction):
            payload = {"guests": [{"guestActivityId": i} for i in op.guest_activity_ids]} if op.guest_activity_ids is not None else {}
        # Send only the nested fields a person supplied; preserve false opt-ins.
        if isinstance(op, (CreateCustomer, UpdateCustomer, UpdateBooking)) and op.fields is not None:
            payload["fields"] = op.fields.model_dump(exclude_unset=True)
        kwargs = {"params": payload} if method == "GET" else {"json": payload} if method != "DELETE" else {}
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, cred.tenant_url + "/api/4.0" + path,
                    auth=httpx.BasicAuth(cred.api_key, cred.api_secret), headers={"Accept": "application/json"}, **kwargs)
            if not 200 <= response.status_code < 300:
                text = response.text[:4000]
                if 300 <= response.status_code < 400:
                    text = "Checkfront redirected this request. Paste the current tenant URL from your account into the credential."
                output = {"status": "error", "http_status": response.status_code, "message": text,
                    "write_outcome": "unverified" if method != "GET" and response.status_code >= 500 else None}
            elif isinstance(op, (UpdateCustomer, ArchiveCustomer)):
                # The contract declares no response body for these endpoints.
                output = {"status": "success", "http_status": response.status_code, "acknowledged": True,
                    "customer_id": op.customer_id, "effect_verified": False}
            else:
                if len(response.content) > 8_000_000:
                    raise ValueError("Checkfront response exceeds the supported size")
                body = response.json()
                if not isinstance(body, dict) or "error" in body or "errors" in body or "data" not in body:
                    raise ValueError("Checkfront did not return the documented data envelope")
                data = body["data"]
                listing = op.operation.startswith("list_")
                if not isinstance(data, list if listing else dict):
                    raise ValueError("Checkfront returned an unexpected resource shape")
                output = {"status": "success", "data": data, "http_status": response.status_code}
                if method != "GET":
                    output.update(acknowledged=True, effect_verified=False)
                if listing:
                    records = body.get("meta", {}).get("records")
                    # Return provider pagination metadata without trusting/following its URLs.
                    output["pagination"] = records
                    output["next_offset"] = None
                    output["has_more"] = None
                    if isinstance(records, dict) and all(type(records.get(k)) is int for k in ("total", "offset", "limit")):
                        offset, limit, total = (records[k] for k in ("offset", "limit", "total"))
                        if offset < 0 or limit <= 0 or total < offset + len(data) or offset != op.offset:
                            raise ValueError("Checkfront returned inconsistent pagination metadata")
                        output["has_more"] = offset + limit < total
                        output["next_offset"] = offset + limit if output["has_more"] else None
        except (httpx.TransportError, ValueError) as exc:
            output = {"status": "error", "message": "Checkfront request could not be verified: " + (str(exc) if isinstance(exc, ValueError) else type(exc).__name__),
                "write_outcome": "unverified" if method != "GET" else None}
        output = _redact(output, cred)
        await self.emit(output)
        return output
