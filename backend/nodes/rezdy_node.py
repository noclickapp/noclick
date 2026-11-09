"""Rezdy Supplier API v1 operations, authenticated with a manually supplied API key.

Contract: https://developers.rezdy.com/rezdyapi/swagger-supplier.json
Each operation makes exactly one API call. Writes are never retried automatically.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote
from datetime import datetime
import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client, SSRFError


class RezdyAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Rezdy API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developers.rezdy.com/rezdyapi/",
            "x-credential-instructions": "In Rezdy, open Integrations > Rezdy API and request an API key. Paste the key here. NoClick sends it in the apiKey header to api.rezdy.com. Your plan and key permissions determine which operations are available.",
        })
    credential_type: Literal["rezdy_api_key"] = Field("rezdy_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without whitespace or a header prefix")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("startTimeLocal", "endTimeLocal", check_fields=False)
    @classmethod
    def local_time(cls, value):
        if value is not None:
            try:
                parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
                if parsed.strftime("%Y-%m-%d %H:%M:%S") != value:
                    raise ValueError()
            except (ValueError, TypeError):
                raise ValueError("Use supplier local time in yyyy-MM-dd HH:mm:ss format") from None
        return value

    @field_validator("productCode", "orderNumber", "voucherCode", mode="before", check_fields=False)
    @classmethod
    def safe_identifiers(cls, value):
        for item in value if isinstance(value, list) else [value]:
            if not isinstance(item, str) or not item.strip() or item in {".", ".."} or any(ord(c) < 32 for c in item):
                raise ValueError("Use a Rezdy resource code without path traversal or control characters")
        return value


class Page(Input):
    limit: int = Field(100, ge=1, le=100, description="Maximum results on this page.")
    offset: int = Field(0, ge=0, le=2147483647, description="Offset for this page; pass next_offset to continue.")


class Customer(Input):
    firstName: str = Field(..., min_length=1)
    lastName: str | None = None
    email: str | None = None
    phone: str | None = None
    mobile: str | None = None
    companyName: str | None = None
    addressLine: str | None = None
    city: str | None = None
    state: str | None = None
    postCode: str | None = None
    countryCode: str | None = None


class Quantity(Input):
    value: int = Field(..., ge=1)
    optionLabel: str | None = Field(None, description="Required for products with multiple price options.")


class BookingItem(Input):
    productCode: str = Field(..., min_length=1)
    quantities: list[Quantity] = Field(..., min_length=1)
    startTimeLocal: str | None = Field(None, description="Supplier local time, yyyy-MM-dd HH:mm:ss; required for dated products.")
    startTime: AwareDatetime | None = Field(None, description="ISO 8601 session start time, as an alternative to startTimeLocal.")


class BookingPayload(Input):
    items: list[BookingItem] = Field(..., min_length=1, description="Complete booking items, including session and price-option quantities.")
    customer: Customer | None = None
    internalNotes: str | None = None
    resellerReference: str | None = None
    resellerComments: str | None = None


class CreateBookingPayload(BookingPayload):
    comments: str | None = None
    sendNotifications: bool = Field(False, description="Send Rezdy's booking notification emails.")


class ListProducts(Page):
    """List products."""
    operation: Literal["list_products"] = Field("list_products", json_schema_extra={"ui:hidden": True})
    search: str | None = None

class GetProduct(Input):
    """Get product."""
    operation: Literal["get_product"] = Field("get_product", json_schema_extra={"ui:hidden": True})
    productCode: str = Field(..., min_length=1)

class ListBookings(Page):
    """List bookings."""
    operation: Literal["list_bookings"] = Field("list_bookings", json_schema_extra={"ui:hidden": True})
    orderStatus: Literal["PROCESSING", "NEW", "ON_HOLD", "PENDING_SUPPLIER", "PENDING_CUSTOMER", "CONFIRMED", "CANCELLED", "ABANDONED_CART"] | None = None
    productCode: list[str] | None = None
    minTourStartTime: AwareDatetime | None = None
    maxTourStartTime: AwareDatetime | None = None
    minDateCreated: AwareDatetime | None = None
    maxDateCreated: AwareDatetime | None = None
    updatedSince: AwareDatetime | None = None
    resellerReference: str | None = None
    role: Literal["RESELLER", "SUPPLIER", "ALL"] | None = None

class GetBooking(Input):
    """Get booking."""
    operation: Literal["get_booking"] = Field("get_booking", json_schema_extra={"ui:hidden": True})
    orderNumber: str = Field(..., min_length=1)

class CreateBooking(Input):
    """Create booking."""
    operation: Literal["create_booking"] = Field("create_booking", json_schema_extra={"ui:hidden": True})
    booking: CreateBookingPayload = Field(..., description="Creates a booking and may affect inventory and payment workflows. Inspect uncertain results before retrying.")

class QuoteBooking(Input):
    """Quote booking."""
    operation: Literal["quote_booking"] = Field("quote_booking", json_schema_extra={"ui:hidden": True})
    booking: BookingPayload

class UpdateBooking(Input):
    """Update booking."""
    operation: Literal["update_booking"] = Field("update_booking", json_schema_extra={"ui:hidden": True})
    orderNumber: str = Field(..., min_length=1)
    booking: BookingPayload = Field(..., description="Supply the complete items required by Rezdy, plus the fields to update.")

class CancelBooking(Input):
    """Cancel booking."""
    operation: Literal["cancel_booking"] = Field("cancel_booking", json_schema_extra={"ui:hidden": True})
    orderNumber: str = Field(..., min_length=1)
    sendNotifications: bool = Field(False, description="Send the cancellation notification email.")

class ListCustomers(Page):
    """List customers."""
    operation: Literal["list_customers"] = Field("list_customers", json_schema_extra={"ui:hidden": True})
    search: str | None = None

class GetCustomer(Input):
    """Get customer."""
    operation: Literal["get_customer"] = Field("get_customer", json_schema_extra={"ui:hidden": True})
    customerId: int = Field(..., ge=1)

class CreateCustomer(Input):
    """Create customer."""
    operation: Literal["create_customer"] = Field("create_customer", json_schema_extra={"ui:hidden": True})
    customer: Customer

class DeleteCustomer(Input):
    """Delete customer."""
    operation: Literal["delete_customer"] = Field("delete_customer", json_schema_extra={"ui:hidden": True})
    customerId: int = Field(..., ge=1)

class SearchAvailability(Page):
    """Search availability."""
    operation: Literal["search_availability"] = Field("search_availability", json_schema_extra={"ui:hidden": True})
    productCode: list[str] = Field(..., min_length=1)
    startTimeLocal: str = Field(..., description="Start of range in supplier local time, yyyy-MM-dd HH:mm:ss.")
    endTimeLocal: str = Field(..., description="End of range in supplier local time, yyyy-MM-dd HH:mm:ss.")
    minAvailability: int | None = Field(None, ge=0)

class ListCategories(Page):
    """List categories."""
    operation: Literal["list_categories"] = Field("list_categories", json_schema_extra={"ui:hidden": True})
    search: str | None = None
    visible: bool | None = None

class GetCategory(Input):
    """Get category."""
    operation: Literal["get_category"] = Field("get_category", json_schema_extra={"ui:hidden": True})
    categoryId: int = Field(..., ge=1)

class ListCategoryProducts(Page):
    """List category products."""
    operation: Literal["list_category_products"] = Field("list_category_products", json_schema_extra={"ui:hidden": True})
    categoryId: int = Field(..., ge=1)

class ListResources(Page):
    """List resources."""
    operation: Literal["list_resources"] = Field("list_resources", json_schema_extra={"ui:hidden": True})

class ListVouchers(Page):
    """List vouchers."""
    operation: Literal["list_vouchers"] = Field("list_vouchers", json_schema_extra={"ui:hidden": True})
    search: str | None = None

class GetVoucher(Input):
    """Get voucher."""
    operation: Literal["get_voucher"] = Field("get_voucher", json_schema_extra={"ui:hidden": True})
    voucherCode: str = Field(..., min_length=1)

class ListProductPickups(Page):
    """List product pickups."""
    operation: Literal["list_product_pickups"] = Field("list_product_pickups", json_schema_extra={"ui:hidden": True})
    productCode: str = Field(..., min_length=1)

class ListRates(Input):
    """List rates."""
    operation: Literal["list_rates"] = Field("list_rates", json_schema_extra={"ui:hidden": True})
    rateName: str | None = None
    productCode: str | None = None


RezdyConfig = Annotated[Union[
    ListProducts,
    GetProduct,
    ListBookings,
    GetBooking,
    CreateBooking,
    QuoteBooking,
    UpdateBooking,
    CancelBooking,
    ListCustomers,
    GetCustomer,
    CreateCustomer,
    DeleteCustomer,
    SearchAvailability,
    ListCategories,
    GetCategory,
    ListCategoryProducts,
    ListResources,
    ListVouchers,
    GetVoucher,
    ListProductPickups,
    ListRates
], Field(discriminator="operation")]


class RezdyFullConfig(NodeConfig[RezdyConfig, RezdyAPIKeyCredential]):
    pass


ROUTES = {
    "list_products": ('GET', '/v1/products', 'products'),
    "get_product": ('GET', '/v1/products/{productCode}', 'product'),
    "list_bookings": ('GET', '/v1/bookings', 'bookings'),
    "get_booking": ('GET', '/v1/bookings/{orderNumber}', 'booking'),
    "create_booking": ('POST', '/v1/bookings', 'booking'),
    "quote_booking": ('POST', '/v1/bookings/quote', 'booking'),
    "update_booking": ('PUT', '/v1/bookings/{orderNumber}', 'booking'),
    "cancel_booking": ('DELETE', '/v1/bookings/{orderNumber}', 'booking'),
    "list_customers": ('GET', '/v1/customers', 'customers'),
    "get_customer": ('GET', '/v1/customers/{customerId}', 'customer'),
    "create_customer": ('POST', '/v1/customers', 'customer'),
    "delete_customer": ('DELETE', '/v1/customers/{customerId}', None),
    "search_availability": ('GET', '/v1/availability', 'sessions'),
    "list_categories": ('GET', '/v1/categories', 'categories'),
    "get_category": ('GET', '/v1/categories/{categoryId}', 'category'),
    "list_category_products": ('GET', '/v1/categories/{categoryId}/products', 'products'),
    "list_resources": ('GET', '/v1/resources', 'resources'),
    "list_vouchers": ('GET', '/v1/vouchers', 'vouchers'),
    "get_voucher": ('GET', '/v1/vouchers/{voucherCode}', 'voucher'),
    "list_product_pickups": ('GET', '/v1/products/{productCode}/pickups', 'pickupLocations'),
    "list_rates": ('GET', '/v1/rates/search', 'rates'),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {k: _redact(v, secret) for k, v in value.items() if k.lower() not in {"apikey", "api_key"}}
    return value


class RezdyNode(WorkflowNode):
    integration_type = "automation-rezdy"
    connection_evidence = ConnectionEvidence(noun="Rezdy categories", operation="list_categories")

    @classmethod
    def get_config_model(cls):
        return RezdyFullConfig

    async def execute(self, inputs):
        if not isinstance(self.config, RezdyFullConfig) or self.config.credentials is None:
            raise ValueError("Supply a Rezdy API key")
        op = self.config.config
        key = self.config.credentials.api_key
        method, path, result_key = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for field in ("productCode", "orderNumber", "customerId", "categoryId", "voucherCode"):
            if "{" + field + "}" in path:
                path = path.replace("{" + field + "}", quote(str(values.pop(field)), safe=""))
        body = values.pop("booking", values.pop("customer", None)) if method in {"POST", "PUT"} else None
        # Repeated query keys are Rezdy's documented array serialization.
        params = [(k, str(item).lower() if isinstance(item, bool) else item)
            for k, value in values.items() for item in (value if isinstance(value, list) else [value])]
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False) as client:
                response = await client.request(method, "https://api.rezdy.com" + path,
                    headers={"apiKey": key, "Accept": "application/json", "Content-Type": "application/json; charset=UTF-8"},
                    params=params, **({"json": body} if body is not None else {}))
            payload = response.json()
            status = payload.get("requestStatus") if isinstance(payload, dict) else None
            if not isinstance(status, dict) or type(status.get("success")) is not bool:
                raise ValueError("Rezdy returned an unexpected response")
            if status["success"] is False:
                error = status.get("error", {})
                message = error.get("errorMessage") if isinstance(error, dict) else None
                return {"status": "error", "http_status": response.status_code,
                    "error": _redact(message or "Rezdy rejected the request", key)}
            if not 200 <= response.status_code < 300:
                return {"status": "error", "http_status": response.status_code, "error": "Rezdy did not accept the request"}
            data = payload.get(result_key) if result_key else None
            paged = isinstance(op, Page)
            if result_key and not isinstance(data, list if paged or op.operation == "list_rates" else dict):
                raise ValueError("Rezdy response is missing the requested data")
            output = {"status": "success", "http_status": response.status_code, "data": _redact(payload, key)}
            if isinstance(data, list):
                output["items"] = _redact(data, key)
            if paged:
                output["next_offset"] = op.offset + len(data) if len(data) == op.limit else None
                output["has_more"] = len(data) == op.limit
            return output
        except (ValueError, httpx.HTTPError, SSRFError):
            return {"status": "error", "error": "Rezdy request could not be confirmed. Inspect the account before retrying a write."}
