"""Commerce Layer Core API 8.2.0: bounded JSON:API reads and typed writes.

Contract: https://data.commercelayer.app/schemas/openapi.json
Bearer tokens: https://docs.commercelayer.io/core/authentication/client-credentials
Each operation sends exactly one request; mutations are never retried automatically.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import parse_qs, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

NODE_TYPE = "automation-commerce-layer"
MEDIA = "application/vnd.api+json"
ResourceID = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]
Text = Annotated[str, Field(min_length=1, max_length=1000)]


class CommerceLayerAccessToken(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, title="Commerce Layer Access Token",
        json_schema_extra={
            "x-credential-url": "https://docs.commercelayer.io/core/authentication/client-credentials",
            "x-credential-instructions": "Paste an existing integration access token and your organization slug. Obtain the token using your integration API credentials and the documented client_credentials grant. Integration tokens expire (the documented example lasts 7200 seconds); replace an expired token here. NoClick does not obtain or refresh tokens. Your integration role must permit the operations you use. Listing SKUs verifies catalog read access, not every write permission.",
        })
    credential_type: Literal["commerce_layer_access_token"] = Field("commerce_layer_access_token", json_schema_extra={"ui:hidden": True})
    organization_slug: str = Field(..., min_length=1, max_length=63, title="Organization slug", description="The subdomain in https://yourdomain.commercelayer.io; paste the slug or organization URL.")
    access_token: str = Field(..., min_length=1, max_length=8192, title="Access token", json_schema_extra={"ui:widget": "password"})

    @field_validator("organization_slug", mode="before")
    @classmethod
    def slug(cls, value):
        if not isinstance(value, str):
            raise ValueError("Enter your Commerce Layer organization slug")
        value = value.strip().lower()
        if "://" in value or ".commercelayer.io" in value:
            parts = urlsplit(value if "://" in value else "https://" + value)
            if parts.scheme != "https" or parts.username or parts.password or parts.port or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.commercelayer\.io", parts.netloc):
                raise ValueError("Use your organization's HTTPS Commerce Layer URL")
            value = parts.netloc.removesuffix(".commercelayer.io")
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", value) or value in {"auth", "api", "www", "docs"}:
            raise ValueError("Use your organization subdomain, not a shared Commerce Layer host")
        return value

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste your access token")
        value = clean_secret(value, field_name="Access token", key=True)
        if not value or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste the token without a Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    page_number: int = Field(1, ge=1, le=100000, description="Explicit page to fetch. Use next_page_number from the previous result.")
    page_size: int = Field(10, ge=1, le=25, description="Commerce Layer allows at most 25 resources per page.")


class ListOrdersConfig(_Page):
    """Fetch one page of orders."""
    operation: Literal["list_orders"] = Field("list_orders", json_schema_extra={"ui:hidden": True})

class GetOrderConfig(_Input):
    """Retrieve one order by ID."""
    operation: Literal["get_order"] = Field("get_order", json_schema_extra={"ui:hidden": True})
    order_id: ResourceID

class ListCustomersConfig(_Page):
    """Fetch one page of customers."""
    operation: Literal["list_customers"] = Field("list_customers", json_schema_extra={"ui:hidden": True})

class GetCustomerConfig(_Input):
    """Retrieve one customer by ID."""
    operation: Literal["get_customer"] = Field("get_customer", json_schema_extra={"ui:hidden": True})
    customer_id: ResourceID

class ListSkusConfig(_Page):
    """Fetch one page of skus."""
    operation: Literal["list_skus"] = Field("list_skus", json_schema_extra={"ui:hidden": True})

class GetSkuConfig(_Input):
    """Retrieve one sku by ID."""
    operation: Literal["get_sku"] = Field("get_sku", json_schema_extra={"ui:hidden": True})
    sku_id: ResourceID

class ListPricesConfig(_Page):
    """Fetch one page of prices."""
    operation: Literal["list_prices"] = Field("list_prices", json_schema_extra={"ui:hidden": True})

class GetPriceConfig(_Input):
    """Retrieve one price by ID."""
    operation: Literal["get_price"] = Field("get_price", json_schema_extra={"ui:hidden": True})
    price_id: ResourceID

class ListStockItemsConfig(_Page):
    """Fetch one page of stock items."""
    operation: Literal["list_stock_items"] = Field("list_stock_items", json_schema_extra={"ui:hidden": True})

class GetStockItemConfig(_Input):
    """Retrieve one stock item by ID."""
    operation: Literal["get_stock_item"] = Field("get_stock_item", json_schema_extra={"ui:hidden": True})
    stock_item_id: ResourceID

class ListShipmentsConfig(_Page):
    """Fetch one page of shipments."""
    operation: Literal["list_shipments"] = Field("list_shipments", json_schema_extra={"ui:hidden": True})

class GetShipmentConfig(_Input):
    """Retrieve one shipment by ID."""
    operation: Literal["get_shipment"] = Field("get_shipment", json_schema_extra={"ui:hidden": True})
    shipment_id: ResourceID

class CreateOrderConfig(_Input):
    """Create an order in an explicit market; this does not place it."""
    operation: Literal["create_order"] = Field("create_order", json_schema_extra={"ui:hidden": True})
    market_id: ResourceID
    customer_email: Text | None = None
    language_code: str | None = Field(None, min_length=2, max_length=2)
    reference: Text | None = None

class UpdateOrderConfig(_Input):
    """Update order reference and optional customer email or coupon."""
    operation: Literal["update_order"] = Field("update_order", json_schema_extra={"ui:hidden": True})
    order_id: ResourceID
    reference: Text
    customer_email: Text | None = None
    coupon_code: Text | None = None

class CreateCustomerConfig(_Input):
    """Create a customer by email."""
    operation: Literal["create_customer"] = Field("create_customer", json_schema_extra={"ui:hidden": True})
    email: Text
    reference: Text | None = None

class UpdateCustomerConfig(_Input):
    """Update a customer email and optional external reference."""
    operation: Literal["update_customer"] = Field("update_customer", json_schema_extra={"ui:hidden": True})
    customer_id: ResourceID
    email: Text
    reference: Text | None = None

class CreateSkuConfig(_Input):
    """Create a shippable SKU with an explicit shipping category."""
    operation: Literal["create_sku"] = Field("create_sku", json_schema_extra={"ui:hidden": True})
    code: Text
    name: Text
    shipping_category_id: ResourceID
    description: str | None = Field(None, max_length=10000)

class UpdateSkuConfig(_Input):
    """Update the name and optional description of a SKU."""
    operation: Literal["update_sku"] = Field("update_sku", json_schema_extra={"ui:hidden": True})
    sku_id: ResourceID
    name: Text
    description: str | None = Field(None, max_length=10000)

class CreatePriceConfig(_Input):
    """Create a SKU price in an explicit price list, in minor currency units."""
    operation: Literal["create_price"] = Field("create_price", json_schema_extra={"ui:hidden": True})
    sku_id: ResourceID
    price_list_id: ResourceID
    amount_cents: int = Field(..., ge=0)

class UpdatePriceConfig(_Input):
    """Replace a price amount in minor currency units."""
    operation: Literal["update_price"] = Field("update_price", json_schema_extra={"ui:hidden": True})
    price_id: ResourceID
    amount_cents: int = Field(..., ge=0)

class UpdateStockItemConfig(_Input):
    """Set absolute stock quantity, not a delta; concurrent updates may overwrite it."""
    operation: Literal["update_stock_item"] = Field("update_stock_item", json_schema_extra={"ui:hidden": True})
    stock_item_id: ResourceID
    quantity: int = Field(..., ge=0)

class ListLineItemsConfig(_Page):
    """Fetch one page of line items."""
    operation: Literal["list_line_items"] = Field("list_line_items", json_schema_extra={"ui:hidden": True})

class CreateLineItemConfig(_Input):
    """Add a SKU to an order by code and quantity."""
    operation: Literal["create_line_item"] = Field("create_line_item", json_schema_extra={"ui:hidden": True})
    order_id: ResourceID
    sku_code: Text
    quantity: int = Field(..., ge=1)

class UpdateLineItemConfig(_Input):
    """Replace a line item quantity."""
    operation: Literal["update_line_item"] = Field("update_line_item", json_schema_extra={"ui:hidden": True})
    line_item_id: ResourceID
    quantity: int = Field(..., ge=1)

class DeleteLineItemConfig(_Input):
    """Remove a line item from its order."""
    operation: Literal["delete_line_item"] = Field("delete_line_item", json_schema_extra={"ui:hidden": True})
    line_item_id: ResourceID

CommerceLayerConfig = Annotated[Union[
    ListOrdersConfig,
    GetOrderConfig,
    ListCustomersConfig,
    GetCustomerConfig,
    ListSkusConfig,
    GetSkuConfig,
    ListPricesConfig,
    GetPriceConfig,
    ListStockItemsConfig,
    GetStockItemConfig,
    ListShipmentsConfig,
    GetShipmentConfig,
    CreateOrderConfig,
    UpdateOrderConfig,
    CreateCustomerConfig,
    UpdateCustomerConfig,
    CreateSkuConfig,
    UpdateSkuConfig,
    CreatePriceConfig,
    UpdatePriceConfig,
    UpdateStockItemConfig,
    ListLineItemsConfig,
    CreateLineItemConfig,
    UpdateLineItemConfig,
    DeleteLineItemConfig
], Field(discriminator="operation")]


class CommerceLayerFullConfig(NodeConfig[CommerceLayerConfig, CommerceLayerAccessToken]):
    model_config = ConfigDict(hide_input_in_errors=True)


# Fixed method/path catalog. Each value is one operation in the pinned contract.
OPERATIONS = {
    "list_orders": ("GET", "orders"),
    "get_order": ("GET", "orders"),
    "list_customers": ("GET", "customers"),
    "get_customer": ("GET", "customers"),
    "list_skus": ("GET", "skus"),
    "get_sku": ("GET", "skus"),
    "list_prices": ("GET", "prices"),
    "get_price": ("GET", "prices"),
    "list_stock_items": ("GET", "stock_items"),
    "get_stock_item": ("GET", "stock_items"),
    "list_shipments": ("GET", "shipments"),
    "get_shipment": ("GET", "shipments"),
    "create_order": ("POST", "orders"),
    "update_order": ("PATCH", "orders"),
    "create_customer": ("POST", "customers"),
    "update_customer": ("PATCH", "customers"),
    "create_sku": ("POST", "skus"),
    "update_sku": ("PATCH", "skus"),
    "create_price": ("POST", "prices"),
    "update_price": ("PATCH", "prices"),
    "update_stock_item": ("PATCH", "stock_items"),
    "list_line_items": ("GET", "line_items"),
    "create_line_item": ("POST", "line_items"),
    "update_line_item": ("PATCH", "line_items"),
    "delete_line_item": ("DELETE", "line_items"),
}

ATTRIBUTES = {
    "orders": ("number", "status", "payment_status", "fulfillment_status", "customer_email", "language_code", "reference", "reference_origin", "currency_code", "subtotal_amount_cents", "total_amount_cents", "placed_at", "created_at", "updated_at"),
    "customers": ("email", "reference", "reference_origin", "created_at", "updated_at"),
    "skus": ("code", "name", "description", "image_url", "do_not_ship", "do_not_track", "reference", "created_at", "updated_at"),
    "prices": ("sku_code", "amount_cents", "compare_at_amount_cents", "currency_code", "reference", "created_at", "updated_at"),
    "stock_items": ("sku_code", "quantity", "reference", "created_at", "updated_at"),
    "shipments": ("number", "status", "tracking_number", "tracking_status", "tracking_url", "shipped_at", "delivered_at", "reference", "created_at", "updated_at"),
    "line_items": ("sku_code", "name", "quantity", "unit_amount_cents", "total_amount_cents", "reference", "created_at", "updated_at"),
}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, dict):
        return {k: _redact(v, token) for k, v in value.items()}
    return value


def _record(raw, kind):
    if not isinstance(raw, dict) or raw.get("type") != kind or not isinstance(raw.get("id"), str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", raw["id"]) or not isinstance(raw.get("attributes"), dict):
        raise ValueError("Commerce Layer returned an unexpected resource")
    # Exclude passwords, JWTs and unrelated fields from customer/order responses.
    return {"id": raw["id"], "type": kind, **{k: v for k, v in raw["attributes"].items() if k in ATTRIBUTES[kind]}}


def _body(op, kind):
    fields = op.model_dump(exclude_none=True, exclude={"operation"})
    data = {"type": kind, "attributes": {k: v for k, v in fields.items() if not k.endswith("_id")}}
    if op.operation.startswith("update_"):
        data["id"] = fields[op.operation.removeprefix("update_") + "_id"]
    relations = {
        "create_order": {"market": "markets"},
        "create_sku": {"shipping_category": "shipping_categories"},
        "create_price": {"sku": "skus", "price_list": "price_lists"},
        "create_line_item": {"order": "orders"},
    }.get(op.operation, {})
    if relations:
        data["relationships"] = {name: {"data": {"type": resource, "id": fields[name + "_id"]}} for name, resource in relations.items()}
    return {"data": data}


class CommerceLayerNode(WorkflowNode):
    integration_type = "automation-commerce-layer"
    connection_evidence = ConnectionEvidence(noun="SKUs", operation="list_skus", label_keys=("name", "code", "id"))

    @classmethod
    def get_config_model(cls):
        return CommerceLayerFullConfig

    @staticmethod
    def _check_credential_family(data):
        raw = data.get("credentials") if isinstance(data, dict) else None
        if isinstance(raw, dict) and raw.get("credential_type", "commerce_layer_access_token") != "commerce_layer_access_token":
            raise ValueError("Attach a Commerce Layer access token")

    @classmethod
    def parse_config(cls, config_data):
        cls._check_credential_family(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            cls._check_credential_family(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(config_data)

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Commerce Layer access token")
        credential = self.config.credentials
        op = self.config.config
        method, kind = OPERATIONS[op.operation]
        identifier = None
        if method in {"PATCH", "DELETE"} or op.operation.startswith("get_"):
            singular = op.operation.split("_", 1)[1]
            identifier = getattr(op, singular + "_id")
        route = "/api/" + kind + ("/" + identifier if identifier else "")
        origin = "https://" + credential.organization_slug + ".commercelayer.io"
        params = {"page[number]": op.page_number, "page[size]": op.page_size} if isinstance(op, _Page) else None
        kwargs = {"params": params} if params else {}
        if method in {"POST", "PATCH"}:
            kwargs["json"] = _body(op, kind)
        headers = {"Authorization": "Bearer " + credential.access_token, "Accept": MEDIA}
        if "json" in kwargs:
            headers["Content-Type"] = MEDIA
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, origin + route, headers=headers, **kwargs)
        except httpx.RequestError:
            raise ValueError("Commerce Layer request failed; a write may have completed. Inspect before retrying.") from None
        expected = 204 if method == "DELETE" else 201 if method == "POST" else 200
        if response.status_code != expected:
            # Keep the provider's rejection text for the shared connection verdict.
            message = "Commerce Layer returned HTTP " + str(response.status_code)
            try:
                errors = response.json().get("errors", [])
                if isinstance(errors, list):
                    details = [str(e.get("detail") or e.get("title"))[:1000] for e in errors[:5] if isinstance(e, dict) and (e.get("detail") or e.get("title"))]
                    if details:
                        message += ": " + "; ".join(details)
            except (ValueError, AttributeError):
                pass
            raise ValueError(_redact(message, credential.access_token))
        result = {"status": "success", "operation": op.operation, "http_status": response.status_code}
        if method == "DELETE":
            result.update(deleted_id=identifier, deletion_acknowledged=True)
        else:
            if len(response.content) > 5_000_000 or response.headers.get("Content-Type", "").split(";", 1)[0].lower() not in {MEDIA, "application/json"}:
                raise ValueError("Commerce Layer returned an unexpected JSON response; inspect any write before retrying")
            try:
                payload = response.json()
            except ValueError:
                raise ValueError("Commerce Layer returned invalid JSON; inspect any write before retrying") from None
            if not isinstance(payload, dict) or "errors" in payload:
                raise ValueError("Commerce Layer did not confirm the operation")
            if isinstance(op, _Page):
                rows = payload.get("data")
                if not isinstance(rows, list) or len(rows) > op.page_size:
                    raise ValueError("Commerce Layer returned an unexpected page")
                result["items"] = [_record(row, kind) for row in rows]
                result.update(self._pagination(payload, origin, route, op))
            else:
                result["item"] = _record(payload.get("data"), kind)
                if identifier is not None and result["item"]["id"] != identifier:
                    raise ValueError("Commerce Layer returned a different resource; inspect any write before retrying")
        result = _redact(result, credential.access_token)
        await self.emit(result)
        return result

    @staticmethod
    def _pagination(payload, origin, route, op):
        # The published schema omits pagination metadata. Do not claim completeness
        # when neither documented links nor meta are present.
        links = payload.get("links")
        meta = payload.get("meta")
        known = isinstance(links, dict) or (isinstance(meta, dict) and type(meta.get("page_count")) is int)
        next_page = None
        if isinstance(links, dict) and links.get("next"):
            link = links["next"]
            if not isinstance(link, str):
                raise ValueError("Commerce Layer returned an invalid pagination link")
            parts = urlsplit(link)
            query = parse_qs(parts.query, keep_blank_values=True)
            if (parts.scheme and parts.scheme != "https") or (parts.netloc and parts.netloc != urlsplit(origin).netloc) or parts.path != route or parts.fragment or set(query) != {"page[number]", "page[size]"} or query["page[size]"] != [str(op.page_size)] or query["page[number]"] != [str(op.page_number + 1)]:
                raise ValueError("Commerce Layer pagination changed the request boundary")
            next_page = op.page_number + 1
        elif not isinstance(links, dict) and isinstance(meta, dict) and type(meta.get("page_count")) is int and meta["page_count"] > op.page_number:
            next_page = op.page_number + 1
        return {"page_number": op.page_number, "page_size": op.page_size,
                "pagination_known": known, "has_more": next_page is not None if known else None,
                "next_page_number": next_page, "complete": known and next_page is None}
