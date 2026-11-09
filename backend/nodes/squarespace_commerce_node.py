"""Squarespace Commerce API-key operations, one published endpoint per action.

Contract: https://developers.squarespace.com/commerce-apis/latest/schema-processor-version-version-latest.json
Pages return the provider's pagination cursor without following nextPageUrl.
Writes are never retried automatically; 204 means acknowledged, not read back.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.squarespace.com"
CREDENTIAL_TYPE = "squarespace_commerce_api_key"


class SquarespaceCommerceAPIKey(BaseModel):
    model_config = ConfigDict(
        title="Squarespace Commerce API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developers.squarespace.com/commerce-apis/authentication-and-permissions",
            "x-credential-instructions": "In your Squarespace site's Settings > Advanced > Developer API Keys, generate a key. Enable Products, Inventory, Orders, Transactions and Profiles reads as needed, and Read and Write for Products, Inventory or Orders mutations. Paste only the key. Connection checks read the website profile; this does not verify every API permission. API availability depends on your Squarespace plan.",
        },
    )
    credential_type: Literal["squarespace_commerce_api_key"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste the Squarespace API key")
        value = clean_secret(value, field_name="API key", key=True)
        if any(c.isspace() for c in value) or value.lower().startswith("bearer"):
            raise ValueError("Paste only the API key without the Bearer prefix")
        return value


Id = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")]
Cursor = Annotated[str, Field(min_length=1, max_length=4096, pattern=r"^[^\s\x00-\x1f\x7f]+$")]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Page(Input):
    cursor: Cursor | None = Field(None, description="pagination.nextPageCursor from the previous response. Fetches one page only.")


class WindowPage(Page):
    modified_after: str | None = Field(None, description="ISO 8601 UTC timestamp, paired with modified_before; cannot combine with cursor.")
    modified_before: str | None = None

    @field_validator("modified_after", "modified_before")
    @classmethod
    def timestamp(cls, value):
        if value is not None:
            if not value.endswith("Z"):
                raise ValueError("Use an ISO 8601 UTC timestamp ending in Z")
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                raise ValueError("Use a valid ISO 8601 timestamp") from None
        return value

    @model_validator(mode="after")
    def window(self):
        if bool(self.modified_after) != bool(self.modified_before):
            raise ValueError("Supply both modified timestamps")
        if self.cursor and (self.modified_after or self.modified_before):
            raise ValueError("A cursor cannot be combined with modified timestamps")
        if self.modified_after and datetime.fromisoformat(self.modified_after.replace("Z", "+00:00")) >= datetime.fromisoformat(self.modified_before.replace("Z", "+00:00")):
            raise ValueError("modified_before must follow modified_after")
        return self


class GetWebsite(Input):
    operation: Literal["get_website"] = "get_website"


class ListProducts(WindowPage):
    operation: Literal["list_products"] = "list_products"
    query: str | None = Field(None, min_length=1, max_length=1000)
    product_type: Literal["PHYSICAL", "DIGITAL", "SERVICE", "GIFT_CARD"] | None = None


class GetProducts(Input):
    operation: Literal["get_products"] = "get_products"
    product_ids: list[Id] = Field(..., min_length=1, max_length=50, description="Up to 50 product IDs, returned in provider order.")


class DeleteProduct(Input):
    operation: Literal["delete_product"] = "delete_product"
    product_id: Id


class ListInventory(Page):
    operation: Literal["list_inventory"] = "list_inventory"


class GetInventory(Input):
    operation: Literal["get_inventory"] = "get_inventory"
    variant_ids: list[Id] = Field(..., min_length=1, max_length=50)


class AdjustInventory(Input):
    operation: Literal["adjust_inventory"] = "adjust_inventory"
    variant_id: Id
    adjustment: Literal["increment", "decrement", "set_finite", "set_unlimited"] = "set_finite"
    quantity: int = Field(0, ge=0, le=2147483647, strict=True)
    idempotency_key: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", description="Unique key for this logical stock change. Reuse the same key when checking/retrying an uncertain request; use a new key for a new change.")

    @model_validator(mode="after")
    def quantity_mode(self):
        if self.adjustment == "set_unlimited" and self.quantity != 0:
            raise ValueError("Unlimited stock does not take a quantity")
        return self


class ListOrders(WindowPage):
    operation: Literal["list_orders"] = "list_orders"
    customer_id: Id | None = None
    fulfillment_status: Literal["PENDING", "FULFILLED", "CANCELED"] | None = None
    payment_states: str | None = Field(None, pattern=r"^(NOT_CHARGED|AUTHORIZED|PAID|REFUNDED|PENDING|FAILED|REFUND_PENDING|REFUND_FAILED|PARTIALLY_PAID)(,(NOT_CHARGED|AUTHORIZED|PAID|REFUNDED|PENDING|FAILED|REFUND_PENDING|REFUND_FAILED|PARTIALLY_PAID))*$")

    @model_validator(mode="after")
    def cursor_only(self):
        if self.cursor and any((self.customer_id, self.fulfillment_status, self.payment_states)):
            raise ValueError("Order cursors cannot be combined with filters")
        return self


class GetOrder(Input):
    operation: Literal["get_order"] = "get_order"
    order_id: Id


class Shipment(Input):
    carrierName: str = Field(..., min_length=1, max_length=100, title="Carrier name")
    service: str = Field(..., min_length=1, max_length=100)
    shipDate: str = Field(..., title="Ship date", description="ISO 8601 UTC timestamp ending in Z.")
    trackingNumber: str = Field(..., min_length=1, max_length=100, title="Tracking number")
    trackingUrl: str | None = Field(None, max_length=2000, pattern=r"^https?://[^\s]+$", title="Tracking URL")

    @field_validator("shipDate")
    @classmethod
    def ship_date(cls, value):
        return WindowPage.timestamp(value)


class FulfillOrder(Input):
    operation: Literal["fulfill_order"] = "fulfill_order"
    order_id: Id
    shipments: list[Shipment] = Field(..., min_length=1, max_length=100)
    should_send_notification: StrictBool = Field(False, description="Ask Squarespace to email the customer about these shipments. Fulfillment is not automatically retried.")


class ListStorePages(Page):
    operation: Literal["list_store_pages"] = "list_store_pages"


class ListTransactions(WindowPage):
    operation: Literal["list_transactions"] = "list_transactions"
    order_id: Id | None = None


class GetTransactions(Input):
    operation: Literal["get_transactions"] = "get_transactions"
    transaction_ids: list[Id] = Field(..., min_length=1, max_length=50)


class ListProfiles(Page):
    operation: Literal["list_profiles"] = "list_profiles"
    sort_direction: Literal["asc", "dsc"] | None = None
    sort_field: Literal["createdOn", "id", "email", "lastName"] | None = None
    filter: str | None = Field(None, min_length=1, max_length=1000, description="Documented semicolon-separated isCustomer/hasAccount filter, or email filter. Email cannot combine with the other two.")
    email: str | None = Field(None, min_length=1, max_length=320)

    @model_validator(mode="after")
    def filters(self):
        if self.cursor and any((self.sort_direction, self.sort_field, self.filter, self.email)):
            raise ValueError("Profile cursors cannot be combined with filters or sorting")
        if self.email and self.filter:
            raise ValueError("Use either email or filter")
        return self


class GetProfiles(Input):
    operation: Literal["get_profiles"] = "get_profiles"
    profile_ids: list[Id] = Field(..., min_length=1, max_length=50)


Config = Annotated[Union[GetWebsite, ListProducts, GetProducts, DeleteProduct, ListInventory,
    GetInventory, AdjustInventory, ListOrders, GetOrder, FulfillOrder, ListStorePages,
    ListTransactions, GetTransactions, ListProfiles, GetProfiles], Field(discriminator="operation")]


class SquarespaceCommerceConfig(NodeConfig[Config, SquarespaceCommerceAPIKey]):
    pass


# Each action deliberately owns exactly one provider operation.
ROUTES = {
    "get_website": ("GET", "/1.0/authorization/website"),
    "list_products": ("GET", "/v2/commerce/products"),
    "get_products": ("GET", "/v2/commerce/products/{product_ids}"),
    "delete_product": ("DELETE", "/v2/commerce/products/{product_id}"),
    "list_inventory": ("GET", "/1.0/commerce/inventory"),
    "get_inventory": ("GET", "/1.0/commerce/inventory/{variant_ids}"),
    "adjust_inventory": ("POST", "/1.0/commerce/inventory/adjustments"),
    "list_orders": ("GET", "/1.0/commerce/orders"),
    "get_order": ("GET", "/1.0/commerce/orders/{order_id}"),
    "fulfill_order": ("POST", "/1.0/commerce/orders/{order_id}/fulfillments"),
    "list_store_pages": ("GET", "/1.0/commerce/store_pages"),
    "list_transactions": ("GET", "/1.0/commerce/transactions"),
    "get_transactions": ("GET", "/1.0/commerce/transactions/{transaction_ids}"),
    "list_profiles": ("GET", "/1.0/profiles"),
    "get_profiles": ("GET", "/1.0/profiles/{profile_ids}"),
}
QUERY_NAMES = {"cursor": "cursor", "modified_after": "modifiedAfter", "modified_before": "modifiedBefore",
    "query": "query", "product_type": "type", "customer_id": "customerId", "fulfillment_status": "fulfillmentStatus",
    "payment_states": "paymentStates", "order_id": "orderId", "sort_direction": "sortDirection",
    "sort_field": "sortField", "filter": "filter", "email": "email"}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {str(k).replace(secret, "[redacted]"): _redact(v, secret) for k, v in value.items()}
    return value


class SquarespaceCommerceNode(WorkflowNode):
    integration_type = "automation-squarespace-commerce"
    connection_evidence = ConnectionEvidence(noun="website", identity_operation="get_website", identity_keys=("title", "url", "id", "siteId"))

    @classmethod
    def get_config_model(cls):
        return SquarespaceCommerceConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Squarespace Commerce API key")
        op = self.config.config
        secret = self.config.credentials.api_key
        method, path = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True)
        for name in re.findall(r"\{(\w+)\}", path):
            value = values[name]
            path = path.replace("{" + name + "}", ",".join(value) if isinstance(value, list) else value)
        params = {target: values[source] for source, target in QUERY_NAMES.items() if source in values and (source != "order_id" or op.operation == "list_transactions")}
        headers = {"Authorization": "Bearer " + secret, "User-Agent": "NoClick Squarespace Commerce Integration", "Accept": "application/json"}
        body = None
        if isinstance(op, AdjustInventory):
            headers["Idempotency-Key"] = op.idempotency_key
            key = {"increment": "incrementOperations", "decrement": "decrementOperations", "set_finite": "setFiniteOperations", "set_unlimited": "setUnlimitedOperations"}[op.adjustment]
            body = {key: [op.variant_id] if op.adjustment == "set_unlimited" else [{"variantId": op.variant_id, "quantity": op.quantity}]}
        elif isinstance(op, FulfillOrder):
            body = {"shipments": [s.model_dump(exclude_none=True) for s in op.shipments], "shouldSendNotification": op.should_send_notification}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + path, params=params, headers=headers, **({"json": body} if body is not None else {}))
        except (httpx.HTTPError, TimeoutError):
            return {"status": "error", "success": False, "message": "Squarespace request did not complete. Inspect the account before retrying a write.", "write_outcome": "unknown" if method != "GET" else None}
        if not 200 <= response.status_code < 300:
            try:
                detail = response.json()
            except ValueError:
                detail = response.text[:2000]
            return _redact({"status": "error", "success": False, "http_status": response.status_code, "message": detail, "write_outcome": "unknown" if method != "GET" and response.status_code >= 500 else None}, secret)
        if response.status_code == 204:
            return {"status": "success", "success": True, "http_status": 204, "acknowledged": True, "readback_verified": False}
        try:
            data = response.json()
        except ValueError:
            raise ValueError("Squarespace returned an unexpected non-JSON response") from None
        if not isinstance(data, (dict, list)):
            raise ValueError("Squarespace returned an unexpected JSON shape")
        # Keep provider pagination, including hasNextPage and nextPageCursor.
        # nextPageUrl is metadata only; no response URL is ever requested.
        return _redact({"status": "success", "success": True, "http_status": response.status_code, "data": data}, secret)
