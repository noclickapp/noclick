"""Regiondo v1 operations, pinned to provider contract 1.26.02.23.

HMAC protocol: https://github.com/regiondo-dev/api/blob/master/clientExample.php
All operations send the contract's query parameters, including mutations.
One page per list call; writes are never automatically retried.
"""
from datetime import date as Date
import hashlib
import hmac
import time
from typing import Annotated, Literal, Union
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.regiondo.com/v1"


class RegiondoAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Regiondo API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-type": "api_key",
        "x-credential-url": "https://sandbox-api.regiondo.com/docs/",
        "x-credential-instructions": "Paste the public and private API keys from your Regiondo account. Requests are HMAC-SHA256 signed and sent only to api.regiondo.com. Supplier and partner operations require the corresponding account access. Connection checks list your account's active holds; an empty list proves API access but cannot name the account.",
    })
    credential_type: Literal["regiondo_api_key"] = Field("regiondo_api_key", json_schema_extra={"ui:hidden": True})
    public_key: str = Field(..., min_length=1, max_length=4096, title="Public API key", repr=False, json_schema_extra={"ui:widget": "password"})
    private_key: str = Field(..., min_length=1, max_length=4096, title="Private API key", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("public_key", "private_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without whitespace or a header")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Page(Input):
    limit: int = Field(100, ge=1, le=250, description="Number of results in this page (maximum 250).")
    offset: int = Field(0, ge=0, description="Start offset. Use next_offset until it is null.")


class ListProducts(Page):
    """Search products with explicit active and category filters."""
    operation: Literal["list_products"] = "list_products"
    active_only: Literal["true", "false"] = "true"
    kwd: str | None = None
    category_id: str | None = None
    tag: str | None = None
    product_ids: str | None = None


class GetProduct(Input):
    """Get the full details of a product."""
    operation: Literal["get_product"] = "get_product"
    productId: int = Field(..., gt=0, title="Product ID")


class ListVariations(Input):
    """List price categories for a product."""
    operation: Literal["list_variations"] = "list_variations"
    productId: int = Field(..., gt=0, title="Product ID")


class GetAvailability(Input):
    """Read available dates and times for a price category."""
    operation: Literal["get_availability"] = "get_availability"
    variationId: int = Field(..., gt=0, title="Variation ID")
    dt_from: Date
    dt_to: Date
    show_soldout: Literal["true", "false"] = "false"

    @model_validator(mode="after")
    def dates(self):
        if self.dt_to < self.dt_from:
            raise ValueError("End date must be on or after start date")
        return self


class ListAvailableOptions(Input):
    """List ticket options for a price category, optionally for a date."""
    operation: Literal["list_available_options"] = "list_available_options"
    variationId: int = Field(..., gt=0, title="Variation ID")
    date: Date | None = None


class BookingPage(Page):
    booking_key: str | None = None
    date_range: str | None = Field(None, description="Comma-separated start,end dates, e.g. 2015-01-01,2015-02-01.")
    date_range_by: Literal["date_bought", "date_of_event"] | None = None
    product_ids: str | None = None
    order_ids: str | None = None
    resource_ids: str | None = None
    status: Literal["sent", "booked", "approved", "reserved", "canceled", "rejected", "processing"] | None = None
    type: Literal["offline_reservation", "booking", "voucher", "redeem", "offline_reservation,booking,voucher,redeem"] | None = None


class ListSupplierBookings(BookingPage):
    """Sync one page of the supplier account's bookings."""
    operation: Literal["list_supplier_bookings"] = "list_supplier_bookings"


class ListPartnerBookings(BookingPage):
    """Sync one page of the partner account's bookings."""
    operation: Literal["list_partner_bookings"] = "list_partner_bookings"


class ListSupplierCustomers(Page):
    """Sync one page of the supplier CRM customers."""
    operation: Literal["list_supplier_customers"] = "list_supplier_customers"


class ListPartnerCustomers(Page):
    """Sync one page of the partner CRM customers."""
    operation: Literal["list_partner_customers"] = "list_partner_customers"


class ListResources(Page):
    """List supplier resources for booking assignment."""
    operation: Literal["list_resources"] = "list_resources"


class ListTags(Page):
    """List this supplier's custom product categories."""
    operation: Literal["list_tags"] = "list_tags"


class ListSoldItems(Page):
    """Export the supplier's sold ticket details."""
    operation: Literal["list_sold_items"] = "list_sold_items"
    order_number: str | None = None
    date_range: str | None = None
    product_ids: str | None = None


class ListHolds(Input):
    """List the active holds accessible to this API key."""
    operation: Literal["list_holds"] = "list_holds"


class GetBooking(Input):
    """Get a booking or permanent reservation by booking key."""
    operation: Literal["get_booking"] = "get_booking"
    booking_key: str = Field(..., min_length=1, max_length=512)


class GetPurchase(Input):
    """Get purchase details and ticket processing status."""
    operation: Literal["get_purchase"] = "get_purchase"
    order_number: str = Field(..., min_length=1, max_length=512)


class ProlongHold(Input):
    """Extend an existing hold; the provider decides whether it can be extended."""
    operation: Literal["prolong_hold"] = "prolong_hold"
    reservation_code: str = Field(..., min_length=1, max_length=512)
    reserve_minutes: int = Field(20, gt=0)


class ReleaseHold(Input):
    """Remove an existing hold, releasing its reserved capacity."""
    operation: Literal["release_hold"] = "release_hold"
    reservation_code: str = Field(..., min_length=1, max_length=512)


class CancelTickets(Input):
    """Cancel API-booked tickets. Regiondo does not refund or notify the customer; the supplier is notified."""
    operation: Literal["cancel_tickets"] = "cancel_tickets"
    reference_ids: str = Field(..., min_length=1, max_length=4096, description="Comma-separated ticket reference IDs. Only bookings placed through the API can be canceled; this does not refund or email the customer.")


RegiondoOperation = Annotated[Union[ListProducts, GetProduct, ListVariations, GetAvailability,
    ListAvailableOptions, ListSupplierBookings, ListPartnerBookings, ListSupplierCustomers,
    ListPartnerCustomers, ListResources, ListTags, ListSoldItems, ListHolds, GetBooking,
    GetPurchase, ProlongHold, ReleaseHold, CancelTickets], Field(discriminator="operation")]


class RegiondoNodeConfig(NodeConfig[RegiondoOperation, RegiondoAPIKeyCredential]):
    pass


ROUTES = {
    "list_products": ("GET", "/products"),
    "get_product": ("GET", "/products/{productId}"),
    "list_variations": ("GET", "/products/variations/{productId}"),
    "get_availability": ("GET", "/products/availabilities/{variationId}"),
    "list_available_options": ("GET", "/products/availoptions/{variationId}"),
    "list_supplier_bookings": ("GET", "/supplier/bookings"),
    "list_partner_bookings": ("GET", "/partner/bookings"),
    "list_supplier_customers": ("GET", "/supplier/crmcustomers"),
    "list_partner_customers": ("GET", "/partner/crmcustomers"),
    "list_resources": ("GET", "/supplier/resources"),
    "list_tags": ("GET", "/tags"),
    "list_sold_items": ("GET", "/supplier/solditemslist"),
    "list_holds": ("GET", "/checkout/hold"),
    "get_booking": ("GET", "/checkout/booking"),
    "get_purchase": ("GET", "/checkout/purchase"),
    "prolong_hold": ("PUT", "/checkout/hold"),
    "release_hold": ("DELETE", "/checkout/hold"),
    "cancel_tickets": ("POST", "/checkout/cancel"),
}
LISTS = {"list_products", "list_variations", "list_supplier_bookings", "list_partner_bookings",
    "list_supplier_customers", "list_partner_customers", "list_resources", "list_tags", "list_sold_items", "list_holds"}


def _redact(value, credential):
    if isinstance(value, str):
        for secret in (credential.public_key, credential.private_key):
            value = value.replace(secret, "[redacted]")
    elif isinstance(value, list):
        return [_redact(item, credential) for item in value]
    elif isinstance(value, dict):
        return {key: _redact(item, credential) for key, item in value.items()}
    return value


class RegiondoNode(WorkflowNode):
    integration_type = "automation-regiondo"
    connection_evidence = ConnectionEvidence(noun="active holds", operation="list_holds", label_keys=("reservation_code",))

    @classmethod
    def get_config_model(cls):
        return RegiondoNodeConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Regiondo API key pair")
        credential = self.config.credentials
        operation = self.config.config
        values = operation.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        method, path = ROUTES[operation.operation]
        for key in ("productId", "variationId"):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", str(values.pop(key)))
        # PHP http_build_query uses RFC1738 encoding; sign exactly the bytes sent.
        query = urlencode(values, safe="", encoding="utf-8").replace("~", "%7E")
        timestamp = str(int(time.time()))
        digest = hmac.new(credential.private_key.encode(),
            (timestamp + credential.public_key + query).encode(), hashlib.sha256).hexdigest()
        headers = {"X-API-ID": credential.public_key, "X-API-TIME": timestamp,
            "X-API-HASH": digest, "Accept": "application/json"}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False) as client:
                url = httpx.URL(BASE + path).copy_with(query=query.encode("ascii"))
                response = await client.request(method, url, headers=headers)
        except httpx.TransportError:
            raise ValueError("Regiondo request did not complete; inspect the account before retrying a write") from None
        try:
            payload = response.json()
        except ValueError:
            raise ValueError(f"Regiondo returned HTTP {response.status_code} without JSON") from None
        error = isinstance(payload, dict) and (payload.get("result") == "error" or
            ("code" in payload and "message" in payload) or payload.get("error"))
        if response.status_code != 200 or error:
            detail = payload.get("message") or payload.get("error") or payload if isinstance(payload, dict) else payload
            raise ValueError(_redact(f"Regiondo HTTP {response.status_code}: {detail}", credential))
        expected = list if operation.operation in LISTS else dict
        if not isinstance(payload, expected):
            raise ValueError("Regiondo returned an unexpected response shape")
        output = {"status": "success", "data": _redact(payload, credential)}
        if isinstance(operation, Page):
            output["next_offset"] = operation.offset + operation.limit if len(payload) == operation.limit else None
        await self.emit(output)
        return output
