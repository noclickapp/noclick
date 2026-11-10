"""BigCommerce store automation using a pasted store-level API access token.

Each operation maps to one documented REST call. Orders use V2; catalog,
customers and location-aware inventory use V3. Inventory writes acknowledge an
asynchronous transaction, not completed stock changes. Webhooks are supported
by the provider but are outside this action node's scope.
Docs: https://docs.bigcommerce.com/developer/api-reference/rest/admin/overview
"""
import json
import re
import time
from typing import Annotated, Any, Literal, Optional, Union

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence


class BigCommerceAPITokenCredential(BaseModel):
    credential_type: Literal["bigcommerce_api_token"] = Field(
        "bigcommerce_api_token", json_schema_extra={"ui:hidden": True}
    )
    store_hash: str = Field(
        ...,
        title="Store Hash",
        description="The store hash from your API path: api.bigcommerce.com/stores/STORE_HASH/v3.",
    )
    access_token: str = Field(
        ...,
        min_length=1,
        title="Access Token",
        description="Paste the access token from your store-level API account.",
        json_schema_extra={"ui:widget": "password"},
    )
    model_config = ConfigDict(
        title="BigCommerce API Token",
        json_schema_extra={
            "x-credential-url": "https://docs.bigcommerce.com/developer/docs/overview/api-fundamentals/api-accounts",
            "x-credential-instructions": "In your BigCommerce control panel, open Settings → Store-level API accounts and create an API account. Copy its store hash and access token. Grant Orders, Products, Customers and Store Inventory modify permissions for write actions, or read-only for reads. Information & Settings read-only is needed for the store identity check.",
        },
    )

    @field_validator("store_hash")
    @classmethod
    def valid_store_hash(cls, value: str) -> str:
        value = value.strip()
        if not re.fullmatch(r"[a-z0-9]+", value):
            raise ValueError(
                "Paste only the store hash from the API path, without a URL or slashes."
            )
        return value


def _operation(name: str, category: str, label: str):
    return Field(
        name,
        title=label,
        json_schema_extra={
            "const": name,
            "ui:hidden": True,
            "x-category": category,
            "x-display-name": label,
            "x-is-trigger": False,
        },
    )


def _json_field(title: str, description: str):
    return Field(
        ...,
        title=title,
        description=description,
        json_schema_extra={"ui:widget": "code_editor", "ui:language": "json"},
    )


class BigCommercePageConfig(BaseModel):
    page: int = Field(
        1,
        ge=1,
        title="Page",
        description="Page to return. Run subsequent pages explicitly.",
    )
    limit: int = Field(
        50, ge=1, le=250, title="Limit", description="Maximum records per page (1–250)."
    )


class BigCommerceGetStoreConfig(BaseModel):
    operation: Literal["get_store"] = _operation(
        "get_store", "Store", "Get Store Information"
    )


class BigCommerceListOrdersConfig(BigCommercePageConfig):
    operation: Literal["list_orders"] = _operation(
        "list_orders", "Orders", "List Orders"
    )
    status_id: Optional[int] = Field(None, ge=0, title="Status ID")
    customer_id: Optional[int] = Field(None, ge=0, title="Customer ID")
    min_date_modified: Optional[str] = Field(
        None, title="Modified Since", description="ISO 8601 or RFC 2822 date."
    )


class BigCommerceGetOrderConfig(BaseModel):
    operation: Literal["get_order"] = _operation("get_order", "Orders", "Get Order")
    order_id: int = Field(..., ge=1, title="Order ID")


class BigCommerceCreateOrderConfig(BaseModel):
    operation: Literal["create_order"] = _operation(
        "create_order", "Orders", "Create Order"
    )
    order_json: str = _json_field(
        "Order (JSON)",
        "Order object with billing_address and products. Use documented V2 order fields.",
    )


class BigCommerceUpdateOrderConfig(BaseModel):
    operation: Literal["update_order"] = _operation(
        "update_order", "Orders", "Update Order"
    )
    order_id: int = Field(..., ge=1, title="Order ID")
    status_id: Optional[int] = Field(None, ge=0, title="Status ID")
    staff_notes: Optional[str] = Field(None, title="Staff Notes")
    customer_message: Optional[str] = Field(None, title="Customer Message")


class BigCommerceListOrderProductsConfig(BigCommercePageConfig):
    operation: Literal["list_order_products"] = _operation(
        "list_order_products", "Orders", "List Order Products"
    )
    order_id: int = Field(..., ge=1, title="Order ID")


class BigCommerceCreateShipmentConfig(BaseModel):
    operation: Literal["create_shipment"] = _operation(
        "create_shipment", "Orders", "Create Shipment"
    )
    order_id: int = Field(..., ge=1, title="Order ID")
    order_address_id: int = Field(..., ge=1, title="Order Address ID")
    items_json: str = _json_field(
        "Shipment Items (JSON)",
        "Array of order_product_id and quantity objects, using IDs from List Order Products.",
    )
    tracking_number: Optional[str] = Field(None, title="Tracking Number")
    shipping_provider: Optional[str] = Field(
        None,
        title="Shipping Provider",
        description="Provider code, such as usps, ups or fedex.",
    )


class BigCommerceListProductsConfig(BigCommercePageConfig):
    operation: Literal["list_products"] = _operation(
        "list_products", "Products", "List Products"
    )
    name: Optional[str] = Field(None, title="Name")
    sku: Optional[str] = Field(None, title="SKU")
    is_visible: Optional[bool] = Field(None, title="Visible")


class BigCommerceGetProductConfig(BaseModel):
    operation: Literal["get_product"] = _operation(
        "get_product", "Products", "Get Product"
    )
    product_id: int = Field(..., ge=1, title="Product ID")


class BigCommerceCreateProductConfig(BaseModel):
    operation: Literal["create_product"] = _operation(
        "create_product", "Products", "Create Product"
    )
    name: str = Field(..., min_length=1, max_length=250, title="Name")
    type: Literal["physical", "digital"] = Field("physical", title="Product Type")
    weight: float = Field(
        ..., ge=0, title="Weight", description="Weight in the store's configured units."
    )
    price: float = Field(
        ..., ge=0, title="Price", description="Price in the store's default currency."
    )
    sku: Optional[str] = Field(None, max_length=255, title="SKU")
    description: Optional[str] = Field(
        None, title="Description", description="Product description; HTML is supported."
    )
    categories_json: str = Field(
        "[]",
        title="Category IDs (JSON)",
        description="Array of category IDs. Required for stores using the V2 product experience.",
        json_schema_extra={"ui:widget": "code_editor", "ui:language": "json"},
    )
    is_visible: Optional[bool] = Field(None, title="Visible")


class BigCommerceUpdateProductConfig(BaseModel):
    operation: Literal["update_product"] = _operation(
        "update_product", "Products", "Update Product"
    )
    type: Literal["physical", "digital"] = Field(..., title="Product Type")
    product_id: int = Field(..., ge=1, title="Product ID")
    name: str = Field(..., min_length=1, max_length=250, title="Name")
    price: float = Field(..., ge=0, title="Price")
    weight: float = Field(..., ge=0, title="Weight")
    sku: Optional[str] = Field(None, max_length=255, title="SKU")
    description: Optional[str] = Field(None, title="Description")
    is_visible: Optional[bool] = Field(None, title="Visible")


class BigCommerceDeleteProductConfig(BaseModel):
    operation: Literal["delete_product"] = _operation(
        "delete_product", "Products", "Delete Product"
    )
    product_id: int = Field(..., ge=1, title="Product ID")


class BigCommerceListCustomersConfig(BigCommercePageConfig):
    operation: Literal["list_customers"] = _operation(
        "list_customers", "Customers", "List Customers"
    )
    email: Optional[str] = Field(None, title="Email", description="Exact email filter.")
    customer_ids: Optional[str] = Field(
        None, title="Customer IDs", description="Comma-separated IDs."
    )


class BigCommerceCreateCustomersConfig(BaseModel):
    operation: Literal["create_customers"] = _operation(
        "create_customers", "Customers", "Create Customers"
    )
    customers_json: str = _json_field(
        "Customers (JSON)",
        "Array of up to 10 customer objects. Each needs email, first_name and last_name.",
    )


class BigCommerceUpdateCustomersConfig(BaseModel):
    operation: Literal["update_customers"] = _operation(
        "update_customers", "Customers", "Update Customers"
    )
    customers_json: str = _json_field(
        "Customers (JSON)",
        "Array of up to 10 customer updates. Each must include id and fields to change.",
    )


class BigCommerceDeleteCustomersConfig(BaseModel):
    operation: Literal["delete_customers"] = _operation(
        "delete_customers", "Customers", "Delete Customers"
    )
    customer_ids: str = Field(
        ...,
        min_length=1,
        title="Customer IDs",
        description="Comma-separated customer IDs to delete.",
    )


class BigCommerceListInventoryConfig(BigCommercePageConfig):
    operation: Literal["list_inventory"] = _operation(
        "list_inventory", "Inventory", "List Inventory"
    )
    sku: Optional[str] = Field(None, title="SKUs", description="Comma-separated SKUs.")
    variant_id: Optional[int] = Field(None, ge=1, title="Variant ID")
    location_id: Optional[int] = Field(None, ge=1, title="Location ID")


class BigCommerceListLocationInventoryConfig(BigCommercePageConfig):
    operation: Literal["list_location_inventory"] = _operation(
        "list_location_inventory", "Inventory", "List Location Inventory"
    )
    location_id: int = Field(..., ge=1, title="Location ID")
    sku: Optional[str] = Field(None, title="SKUs", description="Comma-separated SKUs.")


class BigCommerceSetInventoryConfig(BaseModel):
    operation: Literal["set_inventory"] = _operation(
        "set_inventory", "Inventory", "Set Inventory"
    )
    items_json: str = _json_field(
        "Inventory Items (JSON)",
        "Up to 2,000 items, each with location_id, quantity and exactly one of sku, variant_id or product_id. Sets absolute stock; returns a transaction ID while updates process.",
    )
    reason: Optional[str] = Field(None, title="Reason")


class BigCommerceAdjustInventoryConfig(BaseModel):
    operation: Literal["adjust_inventory"] = _operation(
        "adjust_inventory", "Inventory", "Adjust Inventory"
    )
    items_json: str = _json_field(
        "Inventory Items (JSON)",
        "Up to 2,000 items, each with location_id, quantity and exactly one of sku, variant_id or product_id. Quantity is a signed change; returns an asynchronous transaction ID.",
    )
    reason: Optional[str] = Field(None, title="Reason")


BigCommerceConfig = Annotated[
    Union[
        BigCommerceGetStoreConfig,
        BigCommerceListOrdersConfig,
        BigCommerceGetOrderConfig,
        BigCommerceCreateOrderConfig,
        BigCommerceUpdateOrderConfig,
        BigCommerceListOrderProductsConfig,
        BigCommerceCreateShipmentConfig,
        BigCommerceListProductsConfig,
        BigCommerceGetProductConfig,
        BigCommerceCreateProductConfig,
        BigCommerceUpdateProductConfig,
        BigCommerceDeleteProductConfig,
        BigCommerceListCustomersConfig,
        BigCommerceCreateCustomersConfig,
        BigCommerceUpdateCustomersConfig,
        BigCommerceDeleteCustomersConfig,
        BigCommerceListInventoryConfig,
        BigCommerceListLocationInventoryConfig,
        BigCommerceSetInventoryConfig,
        BigCommerceAdjustInventoryConfig,
    ],
    Discriminator("operation"),
]


class BigCommerceNodeConfig(
    NodeConfig[BigCommerceConfig, BigCommerceAPITokenCredential]
):
    pass


def _json(value: str, kind: type, label: str) -> Any:
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{label} must be valid JSON") from exc
    if not isinstance(parsed, kind) or not parsed:
        raise ValueError(f"{label} must be a non-empty JSON {kind.__name__}")
    if kind is list and not all(isinstance(item, dict) for item in parsed):
        raise ValueError(f"{label} must contain objects")
    return parsed


def _ids(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    parts = [p.strip() for p in value.split(",")]
    if not parts or any(
        not p.isascii() or not p.isdecimal() or int(p) < 1 for p in parts
    ):
        raise ValueError("IDs must be positive integers separated by commas")
    return ",".join(parts)


def _fields(config: BaseModel, *names: str) -> dict:
    return {
        name: getattr(config, name)
        for name in names
        if getattr(config, name) is not None
    }


class BigCommerceNode(WorkflowNode):
    integration_type = "automation-bigcommerce"
    credential_provider_labels = {"bigcommerce": "Bigcommerce Account"}
    connection_evidence = ConnectionEvidence(
        operation="list_products",
        operation_arguments={"limit": 5},
        noun="products",
        identity_operation="get_store",
        identity_keys=("name", "domain"),
    )
    edit_examples = [
        "List orders awaiting fulfillment",
        "Create a product in BigCommerce",
        "Update customer details",
        "Set stock at a warehouse location",
    ]

    @classmethod
    def get_config_model(cls):
        return BigCommerceNodeConfig

    async def execute(self, inputs: dict) -> dict:
        started = time.monotonic()
        config = self.config
        if not isinstance(config, BigCommerceNodeConfig) or not config.credentials:
            raise ValueError("Connect your BigCommerce API token first")
        c = config.config
        credential = config.credentials
        op = c.operation
        method, path, params, body = "GET", "", {}, None
        if isinstance(c, BigCommercePageConfig):
            params = {"page": c.page, "limit": c.limit}
        if op == "get_store":
            path = "/v2/store"
        elif op == "list_orders":
            path = "/v2/orders"
            params.update(_fields(c, "status_id", "customer_id", "min_date_modified"))
        elif op == "get_order":
            path = f"/v2/orders/{c.order_id}"
        elif op == "create_order":
            method, path = "POST", "/v2/orders"
            body = _json(c.order_json, dict, "Order")
            if not body.get("billing_address") or not body.get("products"):
                raise ValueError("Order needs billing_address and products")
        elif op == "update_order":
            method, path = "PUT", f"/v2/orders/{c.order_id}"
            body = _fields(c, "status_id", "staff_notes", "customer_message")
            if not body:
                raise ValueError("Supply at least one order field to update")
        elif op == "list_order_products":
            path = f"/v2/orders/{c.order_id}/products"
        elif op == "create_shipment":
            method, path = "POST", f"/v2/orders/{c.order_id}/shipments"
            items = _json(c.items_json, list, "Shipment items")
            if any(
                not isinstance(i.get("order_product_id"), int)
                or not isinstance(i.get("quantity"), int)
                or i["order_product_id"] < 1
                or i["quantity"] < 1
                for i in items
            ):
                raise ValueError(
                    "Shipment items need positive order_product_id and quantity"
                )
            body = {
                **_fields(
                    c, "order_address_id", "tracking_number", "shipping_provider"
                ),
                "items": items,
            }
        elif op == "list_products":
            path = "/v3/catalog/products"
            params.update(_fields(c, "name", "sku", "is_visible"))
        elif op == "get_product":
            path = f"/v3/catalog/products/{c.product_id}"
        elif op == "create_product":
            method, path = "POST", "/v3/catalog/products"
            body = _fields(
                c, "name", "type", "weight", "price", "sku", "description", "is_visible"
            )
            try:
                categories = json.loads(c.categories_json)
            except ValueError as exc:
                raise ValueError(
                    "Category IDs must be a JSON array of integers"
                ) from exc
            if not isinstance(categories, list) or any(
                type(i) is not int or i < 0 for i in categories
            ):
                raise ValueError("Category IDs must be a JSON array of integers")
            body["categories"] = categories
        elif op == "update_product":
            method, path = "PUT", f"/v3/catalog/products/{c.product_id}"
            body = _fields(
                c, "name", "type", "price", "weight", "sku", "description", "is_visible"
            )
            if not body:
                raise ValueError("Supply at least one product field to update")
        elif op == "delete_product":
            method, path = "DELETE", f"/v3/catalog/products/{c.product_id}"
        elif op == "list_customers":
            path = "/v3/customers"
            params.update({"email:in": c.email, "id:in": _ids(c.customer_ids)})
        elif op in ("create_customers", "update_customers"):
            method, path = (
                "POST" if op == "create_customers" else "PUT"
            ), "/v3/customers"
            body = _json(c.customers_json, list, "Customers")
            if len(body) > 10:
                raise ValueError("Send at most 10 customers per request")
            required = (
                ("email", "first_name", "last_name")
                if op == "create_customers"
                else ("id",)
            )
            if any(any(not item.get(key) for key in required) for item in body):
                raise ValueError("Customers need " + ", ".join(required))
        elif op == "delete_customers":
            method, path = "DELETE", "/v3/customers"
            params = {"id:in": _ids(c.customer_ids)}
        elif op == "list_inventory":
            path = "/v3/inventory/items"
            params.update(
                {
                    "sku:in": c.sku,
                    "variant_id:in": c.variant_id,
                    "location_id:in": c.location_id,
                }
            )
        elif op == "list_location_inventory":
            path = f"/v3/inventory/locations/{c.location_id}/items"
            params.update({"sku:in": c.sku})
        elif op in ("set_inventory", "adjust_inventory"):
            absolute = op == "set_inventory"
            method = "PUT" if absolute else "POST"
            path = "/v3/inventory/adjustments/" + (
                "absolute" if absolute else "relative"
            )
            items = _json(c.items_json, list, "Inventory items")
            if len(items) > 2000:
                raise ValueError("Send at most 2,000 inventory items per request")
            for item in items:
                if (
                    type(item.get("location_id")) is not int
                    or item["location_id"] < 1
                    or type(item.get("quantity")) is not int
                ):
                    raise ValueError(
                        "Inventory items need a positive location_id and integer quantity"
                    )
                if absolute and item["quantity"] < 0:
                    raise ValueError("Absolute quantity must be zero or greater")
                if (
                    sum(bool(item.get(k)) for k in ("sku", "variant_id", "product_id"))
                    != 1
                ):
                    raise ValueError(
                        "Identify each inventory item by exactly one of sku, variant_id or product_id"
                    )
            body = {"items": items, **_fields(c, "reason")}
        else:
            raise ValueError(f"Unknown BigCommerce operation: {op}")
        # Fixed provider host and validated path segments keep typed credentials
        # from redirecting a token to an arbitrary endpoint.
        url = f"https://api.bigcommerce.com/stores/{credential.store_hash}{path}"
        headers = {
            "X-Auth-Token": credential.access_token,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        params = {
            k: (str(v).lower() if isinstance(v, bool) else v)
            for k, v in params.items()
            if v is not None
        }
        result = {"action": op}
        request_started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.request(
                    method, url, headers=headers, params=params, json=body
                )
            result["status_code"] = response.status_code
            if not 200 <= response.status_code < 300:
                # Never return headers or raw text: either may echo credentials.
                message = (
                    f"BigCommerce API request failed (HTTP {response.status_code})"
                )
                try:
                    error = response.json()
                    if isinstance(error, list) and error:
                        error = error[0]
                    if isinstance(error, dict):
                        detail = error.get("title") or error.get("message")
                        if isinstance(detail, str):
                            message = detail.replace(
                                credential.access_token, "[redacted]"
                            )
                except ValueError:
                    pass
                result.update(status="error", error=message)
            elif response.status_code == 204:
                result.update(status="success", data={"success": True})
            else:
                try:
                    data = response.json()
                except ValueError:
                    data = None
                valid = isinstance(data, (dict, list))
                if isinstance(data, dict) and (
                    data.get("success") is False
                    or data.get("status") in ("error", "failed")
                    or "errors" in data
                    or "error" in data
                ):
                    valid = False
                # Evidence must reject a generic 200 page/error, and accept empty
                # product lists so the store identity probe can supply the name.
                if op in (
                    "list_products",
                    "list_customers",
                    "create_customers",
                    "update_customers",
                    "list_inventory",
                    "list_location_inventory",
                ):
                    valid = (
                        valid
                        and isinstance(data, dict)
                        and isinstance(data.get("data"), list)
                    )
                if op in ("get_product", "create_product", "update_product"):
                    valid = (
                        valid
                        and isinstance(data, dict)
                        and isinstance(data.get("data"), dict)
                        and isinstance(data["data"].get("id"), int)
                    )
                if op in ("set_inventory", "adjust_inventory"):
                    valid = (
                        valid
                        and isinstance(data, dict)
                        and isinstance(data.get("transaction_id"), str)
                        and bool(data["transaction_id"])
                    )
                if op in ("list_orders", "list_order_products"):
                    valid = valid and isinstance(data, list)
                if op in (
                    "get_order",
                    "create_order",
                    "update_order",
                    "create_shipment",
                ):
                    valid = (
                        valid
                        and isinstance(data, dict)
                        and isinstance(data.get("id"), int)
                    )
                if op == "get_store":
                    valid = (
                        valid
                        and isinstance(data, dict)
                        and isinstance(data.get("name"), str)
                        and bool(data["name"].strip())
                        and isinstance(data.get("id"), str)
                        and bool(data["id"])
                    )
                if not valid:
                    result.update(
                        status="error",
                        error="BigCommerce returned an invalid JSON response",
                    )
                else:
                    result.update(status="success", data=data)
        except httpx.TimeoutException:
            result.update(
                status="error", error="BigCommerce request timed out", status_code=408
            )
        except httpx.HTTPError:
            result.update(status="error", error="Could not reach the BigCommerce API")
        result["timing_ms"] = {
            "api_request": round((time.monotonic() - request_started) * 1000, 2),
            "total": round((time.monotonic() - started) * 1000, 2),
        }
        return result
