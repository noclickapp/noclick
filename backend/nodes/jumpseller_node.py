"""Jumpseller v1 store automation using merchant API credentials.

Contract: https://api.jumpseller.com/swagger.json, version 1.0.0.
Each operation issues one documented request; writes are never retried.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.jumpseller.com/v1"
CREDENTIAL_TYPE = "jumpseller_api_key"


class JumpsellerAPICredential(BaseModel):
    model_config = ConfigDict(title="Jumpseller API Login and Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://jumpseller.com/support/api/",
            "x-credential-instructions": "In your Jumpseller Admin Panel, open Account > Preferences > API and MCP. Copy the API Login, then use Show token and confirm your password to reveal the Auth Token. Both are required. NoClick sends them using HTTP Basic authentication only to api.jumpseller.com. Enable access to the resources your workflow uses."})
    credential_type: Literal["jumpseller_api_key"] = Field("jumpseller_api_key", json_schema_extra={"ui:hidden": True})
    login: str = Field(..., title="API Login", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})
    authtoken: str = Field(..., title="Auth Token", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("login", "authtoken", mode="before")
    @classmethod
    def secret(cls, value, info):
        value = clean_secret(value, field_name=info.field_name)
        if not isinstance(value, str) or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value) or ":" in value:
            raise ValueError("Paste the API credential without spaces, a colon or an Authorization prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, allow_inf_nan=False)


class _Page(_Input):
    page: int = Field(1, ge=1, le=1000000, title="Page", description="Page number starting at 1. Each execution reads one page.")
    limit: int = Field(50, ge=1, le=100, title="Page Size")


class _ProductID(_Input):
    product_id: int = Field(..., ge=1, le=2147483647, title="Product ID")


class _OrderID(_Input):
    order_id: int = Field(..., ge=1, le=2147483647, title="Order ID")


class _CustomerID(_Input):
    customer_id: int = Field(..., ge=1, le=2147483647, title="Customer ID")


class _CategoryID(_Input):
    category_id: int = Field(..., ge=1, le=2147483647, title="Category ID")


class _ProductFields(_Input):
    name: str | None = Field(None, min_length=1, max_length=500)
    description: str | None = Field(None, max_length=100000, json_schema_extra={"ui:widget": "textarea"})
    price: float | None = Field(None, ge=0)
    sku: str | None = Field(None, max_length=500)
    stock: int | None = Field(None, ge=0, le=2147483647)
    stock_unlimited: bool | None = None
    status: Literal["available", "not-available", "disabled"] | None = None
    brand: str | None = Field(None, max_length=500)
    featured: bool | None = None


class _CustomerFields(_Input):
    email: str | None = Field(None, min_length=3, max_length=254)
    phone: str | None = Field(None, max_length=100)
    status: Literal["approved", "pending", "disabled"] | None = None
    accepts_marketing: bool | None = Field(None, description="Changes the customer's marketing consent when supplied.")
    locale: str | None = Field(None, max_length=10)


class OrderLine(_Input):
    id: int = Field(..., ge=1, le=2147483647, title="Product ID")
    variant_id: int | None = Field(None, ge=1, le=2147483647)
    qty: int = Field(1, ge=1, le=2147483647)
    price: float | None = Field(None, ge=0)


class _NonemptyUpdate(_Input):
    @model_validator(mode="after")
    def changed_fields(self):
        changes = self.model_dump(exclude_none=True, exclude={"operation", "product_id", "customer_id", "order_id", "category_id"})
        if not changes:
            raise ValueError("Supply at least one field to update")
        return self


class GetStoreInfo(_Input):
    """Read store identity without exposing the webhook signing token."""
    operation: Literal["get_store_info"] = Field("get_store_info", title="Get Store Info", json_schema_extra={"ui:hidden": True, "x-operation-kind": "read"})


class ListProducts(_Page):
    operation: Literal["list_products"] = Field("list_products", title="List Products", json_schema_extra={"ui:hidden": True, "x-operation-kind": "read"})


class GetProduct(_ProductID):
    operation: Literal["get_product"] = Field("get_product", title="Get Product", json_schema_extra={"ui:hidden": True, "x-operation-kind": "read"})


class SearchProducts(_Page):
    operation: Literal["search_products"] = Field("search_products", title="Search Products", json_schema_extra={"ui:hidden": True, "x-operation-kind": "read"})
    query: str = Field(..., min_length=1, max_length=500)
    status: Literal["available", "not-available", "disabled", "featured"] | None = None


class CountProducts(_Input):
    operation: Literal["count_products"] = Field("count_products", title="Count Products", json_schema_extra={"ui:hidden": True, "x-operation-kind": "read"})


class CreateProduct(_ProductFields):
    operation: Literal["create_product"] = Field("create_product", title="Create Product", json_schema_extra={"ui:hidden": True, "x-operation-kind": "write"})
    name: str = Field(..., min_length=1, max_length=500)
    price: float = Field(..., ge=0)


class UpdateProduct(_ProductID, _ProductFields, _NonemptyUpdate):
    operation: Literal["update_product"] = Field("update_product", title="Update Product", json_schema_extra={"ui:hidden": True, "x-operation-kind": "write"})


class DeleteProduct(_ProductID):
    """Permanently delete the selected product."""
    operation: Literal["delete_product"] = Field("delete_product", title="Delete Product", json_schema_extra={"ui:hidden": True, "x-operation-kind": "write"})


class ListOrders(_Page):
    operation: Literal["list_orders"] = Field("list_orders", title="List Orders", json_schema_extra={"ui:hidden": True, "x-operation-kind": "read"})
    status_filters: str | None = Field(None, max_length=300, description="Comma-separated order statuses, for example paid,pending_payment.")


class GetOrder(_OrderID):
    operation: Literal["get_order"] = Field("get_order", title="Get Order", json_schema_extra={"ui:hidden": True, "x-operation-kind": "read"})


class SearchOrders(_Page):
    operation: Literal["search_orders"] = Field("search_orders", title="Search Orders", json_schema_extra={"ui:hidden": True, "x-operation-kind": "read"})
    query: str = Field(..., min_length=3, max_length=500)


class CreateOrder(_Input):
    operation: Literal["create_order"] = Field("create_order", title="Create Order", json_schema_extra={"ui:hidden": True, "x-operation-kind": "write"})
    customer_id: int = Field(..., ge=1, le=2147483647)
    products: list[OrderLine] = Field(..., min_length=1, max_length=100)
    status: Literal["Created", "Abandoned", "Canceled", "Pending Payment", "Paid"] = Field("Created", description="Order creation can change inventory and trigger store notifications.")
    shipping_method_name: str | None = Field(None, max_length=500)
    shipping_price: float | None = Field(None, ge=0)
    payment_method_name: str | None = Field(None, max_length=500)
    additional_information: str | None = Field(None, max_length=10000)


class UpdateOrder(_OrderID, _NonemptyUpdate):
    operation: Literal["update_order"] = Field("update_order", title="Update Order", json_schema_extra={"ui:hidden": True, "x-operation-kind": "write"})
    status: Literal["Abandoned", "Canceled", "Pending Payment", "Paid"] | None = Field(None, description="Status changes may trigger store notifications and inventory effects.")
    shipment_status: Literal["requested", "in_transit", "delivered", "failed", "pickup_available", "in_preparation"] | None = None
    tracking_number: str | None = Field(None, max_length=500)
    tracking_company: str | None = Field(None, max_length=500)
    tracking_url: str | None = Field(None, max_length=2000)
    additional_information: str | None = Field(None, max_length=10000)


class ListCustomers(_Page):
    operation: Literal["list_customers"] = Field("list_customers", title="List Customers", json_schema_extra={"ui:hidden": True, "x-operation-kind": "read"})


class GetCustomer(_CustomerID):
    operation: Literal["get_customer"] = Field("get_customer", title="Get Customer", json_schema_extra={"ui:hidden": True, "x-operation-kind": "read"})


class SearchCustomers(_Page):
    operation: Literal["search_customers"] = Field("search_customers", title="Search Customers", json_schema_extra={"ui:hidden": True, "x-operation-kind": "read"})
    query: str = Field(..., min_length=1, max_length=500)
    order: Literal["asc", "desc"] = "asc"


class CreateCustomer(_CustomerFields):
    operation: Literal["create_customer"] = Field("create_customer", title="Create Customer", json_schema_extra={"ui:hidden": True, "x-operation-kind": "write"})
    email: str = Field(..., min_length=3, max_length=254)


class UpdateCustomer(_CustomerID, _CustomerFields, _NonemptyUpdate):
    operation: Literal["update_customer"] = Field("update_customer", title="Update Customer", json_schema_extra={"ui:hidden": True, "x-operation-kind": "write"})


class ListCategories(_Input):
    operation: Literal["list_categories"] = Field("list_categories", title="List Categories", json_schema_extra={"ui:hidden": True, "x-operation-kind": "read"})


class GetCategory(_CategoryID):
    operation: Literal["get_category"] = Field("get_category", title="Get Category", json_schema_extra={"ui:hidden": True, "x-operation-kind": "read"})


class CreateCategory(_Input):
    operation: Literal["create_category"] = Field("create_category", title="Create Category", json_schema_extra={"ui:hidden": True, "x-operation-kind": "write"})
    name: str = Field(..., min_length=1, max_length=500)
    parent_id: int | None = Field(None, ge=1, le=2147483647)


class UpdateCategory(_CategoryID, _NonemptyUpdate):
    operation: Literal["update_category"] = Field("update_category", title="Update Category", json_schema_extra={"ui:hidden": True, "x-operation-kind": "write"})
    name: str | None = Field(None, min_length=1, max_length=500)
    description: str | None = Field(None, max_length=100000)
    parent_id: int | None = Field(None, ge=1, le=2147483647)
    permalink: str | None = Field(None, min_length=1, max_length=500)


class ListLocations(_Input):
    operation: Literal["list_locations"] = Field("list_locations", title="List Locations", json_schema_extra={"ui:hidden": True, "x-operation-kind": "read"})


class UpdateStock(_Input):
    operation: Literal["update_stock"] = Field("update_stock", title="Update Stock", json_schema_extra={"ui:hidden": True, "x-operation-kind": "write"})
    location_id: int = Field(..., ge=1, le=2147483647)
    product_id: int = Field(..., ge=1, le=2147483647)
    variant_id: int | None = Field(None, ge=1, le=2147483647)
    stock: int = Field(..., ge=0, le=2147483647)
    stock_unlimited: bool = Field(..., description="Whether this stock location has unlimited inventory.")


JumpsellerOperation = Annotated[Union[
    GetStoreInfo,
    ListProducts,
    GetProduct,
    SearchProducts,
    CountProducts,
    CreateProduct,
    UpdateProduct,
    DeleteProduct,
    ListOrders,
    GetOrder,
    SearchOrders,
    CreateOrder,
    UpdateOrder,
    ListCustomers,
    GetCustomer,
    SearchCustomers,
    CreateCustomer,
    UpdateCustomer,
    ListCategories,
    GetCategory,
    CreateCategory,
    UpdateCategory,
    ListLocations,
    UpdateStock
], Field(discriminator="operation")]


class JumpsellerFullConfig(NodeConfig[JumpsellerOperation, JumpsellerAPICredential]):
    pass


# Fixed routes: users cannot supply an origin, arbitrary path or HTTP method.
ROUTES = {
    "get_store_info": ("GET", "/store/info.json", "store"),
    "count_products": ("GET", "/products/count.json", "count"),
    "list_locations": ("GET", "/locations.json", "location"),
    "update_stock": ("PUT", "/products_locations.json", "message"),
}
ROUTES["list_products"] = ("GET", "/products.json", "product")
ROUTES["get_product"] = ("GET", "/products/{id}.json", "product")
ROUTES["search_products"] = ("GET", "/products/search.json", "product")
ROUTES["create_product"] = ("POST", "/products.json", "product")
ROUTES["update_product"] = ("PUT", "/products/{id}.json", "product")
ROUTES["delete_product"] = ("DELETE", "/products/{id}.json", "product")
ROUTES["list_orders"] = ("GET", "/orders.json", "order")
ROUTES["get_order"] = ("GET", "/orders/{id}.json", "order")
ROUTES["search_orders"] = ("GET", "/orders/search.json", "order")
ROUTES["create_order"] = ("POST", "/orders.json", "order")
ROUTES["update_order"] = ("PUT", "/orders/{id}.json", "order")
ROUTES["list_customers"] = ("GET", "/customers.json", "customer")
ROUTES["get_customer"] = ("GET", "/customers/{id}.json", "customer")
ROUTES["search_customers"] = ("GET", "/customers/search.json", "customer")
ROUTES["create_customer"] = ("POST", "/customers.json", "customer")
ROUTES["update_customer"] = ("PUT", "/customers/{id}.json", "customer")
ROUTES["list_categories"] = ("GET", "/categories.json", "category")
ROUTES["get_category"] = ("GET", "/categories/{id}.json", "category")
ROUTES["create_category"] = ("POST", "/categories.json", "category")
ROUTES["update_category"] = ("PUT", "/categories/{id}.json", "category")


def _sanitize(value, credentials):
    if isinstance(value, dict):
        return {k: _sanitize(v, credentials) for k, v in value.items()
                if k.lower() not in {"password", "hooks_token", "authtoken", "access_token", "refresh_token", "authorization"}}
    if isinstance(value, list):
        return [_sanitize(v, credentials) for v in value]
    if isinstance(value, str):
        for secret in (credentials.login, credentials.authtoken):
            value = value.replace(secret, "[redacted]")
    return value


def _record(raw, kind, expected=None):
    if not isinstance(raw, dict):
        raise ValueError("Jumpseller returned an invalid record")
    row = raw.get(kind)
    if not isinstance(row, dict):
        raise ValueError("Jumpseller returned an invalid resource envelope")
    if kind == "store":
        if not isinstance(row.get("name"), str) or not row["name"]:
            raise ValueError("Jumpseller returned no store name")
        return {k: row[k] for k in ("name", "code", "url", "currency", "country", "timezone", "email") if k in row}
    if type(row.get("id")) is not int or row["id"] < 1:
        raise ValueError("Jumpseller returned no resource ID")
    if expected is not None and row["id"] != expected:
        raise ValueError("Jumpseller returned a different resource")
    return row


class JumpsellerNode(WorkflowNode):
    integration_type = "automation-jumpseller"
    connection_evidence = ConnectionEvidence(noun="store", identity_operation="get_store_info")

    @classmethod
    def get_config_model(cls):
        return JumpsellerFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect Jumpseller API credentials")
        credential = self.config.credentials
        op = self.config.config
        action = op.operation
        method, path, kind = ROUTES[action]
        identifier = getattr(op, kind + "_id", None)
        if "{id}" in path:
            path = path.replace("{id}", str(identifier))
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        body = None
        params = {}
        if method == "GET":
            params = {k: v for k, v in values.items() if k != kind + "_id"}
            if action == "get_store_info":
                params = {"fields": "name,code,url,currency,country,timezone,email"}
        elif method != "DELETE":
            values.pop(kind + "_id", None)
            if action == "create_order":
                values["customer"] = {"id": values.pop("customer_id")}
            body = values if action == "update_stock" else {kind: values}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, params=params,
                    auth=httpx.BasicAuth(credential.login, credential.authtoken),
                    headers={"Accept": "application/json", "Content-Type": "application/json"},
                    **({"json": body} if body is not None else {}))
        except Exception:
            # A timed-out mutation may already have been applied. Never retry it.
            result = {"status": "error" if method == "GET" else "unknown", "success": False,
                      "message": "Jumpseller request could not be confirmed; inspect the store before retrying a write"}
        else:
            result = self._response(response, op, method, kind, identifier)
        result = _sanitize(result, credential)
        await self.emit(result)
        return result

    @staticmethod
    def _response(response, op, method, kind, identifier):
        status = response.status_code
        try:
            if len(response.content) > 5000000 or response.headers.get("content-type", "").split(";")[0].strip() != "application/json":
                raise ValueError("Jumpseller returned an unexpected response")
            payload = response.json()
            if status != 200:
                message = payload.get("message") if isinstance(payload, dict) else None
                return {"status": "unknown" if method != "GET" and status >= 500 else "error", "success": False,
                        "http_status": status, "message": message if isinstance(message, str) else "Jumpseller rejected the request"}
            if isinstance(payload, dict) and ("errors" in payload or "error" in payload):
                raise ValueError("Jumpseller returned an error envelope")
            out = {"status": "success", "success": True, "http_status": status}
            action = op.operation
            if kind in {"message", "count"} or method == "DELETE":
                key = "count" if kind == "count" else "message"
                value = payload.get(key) if isinstance(payload, dict) else None
                if (key == "count" and (type(value) is not int or value < 0)) or (key == "message" and not isinstance(value, str)):
                    raise ValueError("Jumpseller returned an invalid acknowledgement")
                return {**out, key: value}
            if action.startswith(("list_", "search_")):
                total = None
                if action in {"search_orders", "search_customers"}:
                    rows = payload.get(kind + "s") if isinstance(payload, dict) else None
                    total = payload.get("count") if isinstance(payload, dict) else None
                    if type(total) is not int or total < 0 or not isinstance(rows, list):
                        raise ValueError("Jumpseller returned an invalid search envelope")
                    items = [_record({kind: row}, kind) for row in rows]
                else:
                    if not isinstance(payload, list):
                        raise ValueError("Jumpseller returned an invalid list envelope")
                    items = [_record(row, kind) for row in payload]
                out["items"] = items
                if hasattr(op, "limit"):
                    if len(items) > op.limit:
                        raise ValueError("Jumpseller exceeded the requested page size")
                    has_more = op.page * op.limit < total if total is not None else len(items) == op.limit
                    out.update(page=op.page, limit=op.limit, has_more=has_more,
                               next_page=op.page + 1 if has_more else None)
                if total is not None:
                    out["count"] = total
                return out
            return {**out, "data": _record(payload, kind, identifier)}
        except Exception:
            return {"status": "error" if method == "GET" else "unknown", "success": False,
                    "http_status": status, "message": "Jumpseller response could not be verified; inspect the store before retrying a write"}
