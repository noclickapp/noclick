"""Magento 2 catalog, customer and sales operations against the Adobe 2.4.8 REST contract.

Every operation makes one bounded request to the merchant's HTTPS REST root.
Pasted admin tokens are supported without storing passwords or requesting sign-ins.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

AUTH_DOCS = "https://developer.adobe.com/commerce/webapi/get-started/authentication/gs-authentication-token"


def _rest_root(value):
    if not isinstance(value, str):
        raise ValueError("Paste the store HTTPS REST root ending in /rest/<store code>")
    value = value.strip().rstrip("/")
    try:
        url = urlsplit(value)
        if (url.scheme != "https" or not url.hostname or url.username is not None
                or url.password is not None or url.port not in (None, 443)
                or url.query or url.fragment or not value.isascii()
                or not re.fullmatch(r"[A-Za-z0-9.-]+", url.hostname)
                or "." not in url.hostname or url.hostname.endswith(".")
                or not re.fullmatch(r"(?:/[A-Za-z0-9_-]+)*/rest/[A-Za-z0-9_]+", url.path)):
            raise ValueError()
    except ValueError:
        raise ValueError("Use the public HTTPS REST root, for example https://shop.example.com/rest/default; omit credentials, query and fragment") from None
    return "https://" + url.hostname.lower() + url.path


class MagentoV2TokenCredential(BaseModel):
    model_config = ConfigDict(title="Magento Access Token", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": AUTH_DOCS,
            "x-credential-instructions": "Paste the store REST root and an existing admin access token authorized for your operations. Admin tokens normally expire after four hours; replace expired tokens manually. Customer tokens cannot access these admin endpoints. An integration access token works only when the store already permits standalone bearer tokens. NoClick does not change that setting or request tokens. This connects Magento Open Source / Adobe Commerce on-premises or PaaS, not Adobe Commerce as a Cloud Service."})
    credential_type: Literal["magento_v2_access_token"] = Field("magento_v2_access_token", json_schema_extra={"ui:hidden": True})
    api_base_url: str = Field(..., title="Store REST root", description="Full HTTPS root including store code, for example https://shop.example.com/rest/default. Include a subdirectory if Magento is installed in one.")
    access_token: str = Field(..., min_length=1, max_length=8192, title="Access token", repr=False,
        description="Paste the token itself, without Authorization or Bearer.", json_schema_extra={"ui:widget": "password"})
    _base = field_validator("api_base_url", mode="before")(_rest_root)

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access token", key=True)
        if not value or not re.fullmatch(r"[A-Za-z0-9._~+/=-]+", value):
            raise ValueError("Paste the access token without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    page_size: int = Field(50, ge=1, le=100, description="Maximum results per page; no automatic fetching of later pages.")
    current_page: int = Field(1, ge=1, le=1000000, description="One-based page number; use next_page from the previous result.")
    filter_field: str | None = Field(None, min_length=1, max_length=100, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", description="One search filter, for example sku, email, status or updated_at.")
    filter_value: str | None = Field(None, max_length=1000)
    condition_type: Literal["eq", "neq", "like", "gt", "gteq", "lt", "lteq", "in", "nin"] = "eq"
    sort_field: str | None = Field(None, min_length=1, max_length=100, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    sort_direction: Literal["ASC", "DESC"] = "ASC"

    @model_validator(mode="after")
    def filter_pair(self):
        if (self.filter_field is None) != (self.filter_value is None):
            raise ValueError("Supply both a filter field and a filter value")
        return self


class _Sku(_Input):
    sku: str = Field(..., min_length=1, max_length=64, description="Exact product SKU; it is percent-encoded as one path component.")

    @field_validator("sku")
    @classmethod
    def sku_value(cls, value):
        if value in {".", ".."} or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Use a product SKU without control characters or dot segments")
        return value


class _ProductWrite(_Sku):
    name: str | None = Field(None, min_length=1, max_length=255)
    price: float | None = Field(None, ge=0, allow_inf_nan=False)
    status: Literal[1, 2] | None = Field(None, description="1 enabled, 2 disabled.")
    visibility: Literal[1, 2, 3, 4] | None = Field(None, description="1 not visible, 2 catalog, 3 search, 4 catalog and search.")
    weight: float | None = Field(None, ge=0, allow_inf_nan=False)


class CreateProduct(_ProductWrite):
    """Create a simple product with the store's required attribute set."""
    operation: Literal["create_product"] = Field("create_product", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=255)
    price: float = Field(..., ge=0, allow_inf_nan=False)
    attribute_set_id: int = Field(..., ge=1, description="Existing attribute set ID in this store.")
    status: Literal[1, 2] = 2
    visibility: Literal[1, 2, 3, 4] = 4


class UpdateProduct(_ProductWrite):
    """Update selected product fields; omitted fields are not sent."""
    operation: Literal["update_product"] = Field("update_product", json_schema_extra={"ui:hidden": True})

    @model_validator(mode="after")
    def change(self):
        if all(getattr(self, k) is None for k in ("name", "price", "status", "visibility", "weight")):
            raise ValueError("Supply at least one product field to update")
        return self


class _CustomerWrite(_Input):
    email: str = Field(..., min_length=3, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    firstname: str = Field(..., min_length=1, max_length=255)
    lastname: str = Field(..., min_length=1, max_length=255)
    website_id: int = Field(..., ge=0, description="Existing customer website ID in this store.")
    store_id: int | None = Field(None, ge=0)
    group_id: int | None = Field(None, ge=0)


class CreateCustomer(_CustomerWrite):
    """Create a customer without a password; Magento may send its account email."""
    operation: Literal["create_customer"] = Field("create_customer", json_schema_extra={"ui:hidden": True})


class UpdateCustomer(_CustomerWrite):
    """Save customer identity fields; email and names are required by Magento."""
    operation: Literal["update_customer"] = Field("update_customer", json_schema_extra={"ui:hidden": True})
    customer_id: int = Field(..., ge=1)


class _Order(_Input):
    order_id: int = Field(..., ge=1, description="Internal entity ID, not the displayed increment/order number.")


class AddOrderComment(_Order):
    """Add order history with explicit customer-notification and storefront visibility choices."""
    operation: Literal["add_order_comment"] = Field("add_order_comment", json_schema_extra={"ui:hidden": True})
    comment: str = Field(..., min_length=1, max_length=10000)
    notify_customer: StrictBool = False
    visible_on_front: StrictBool = False


class GetCategoryTree(_Input):
    """Read the category tree to a bounded depth."""
    operation: Literal["get_category_tree"] = Field("get_category_tree", json_schema_extra={"ui:hidden": True})
    root_category_id: int | None = Field(None, ge=1)
    depth: int = Field(3, ge=1, le=10)


class GetCategory(_Input):
    """Read a category by its internal ID."""
    operation: Literal["get_category"] = Field("get_category", json_schema_extra={"ui:hidden": True})
    category_id: int = Field(..., ge=1)


class ListProducts(_Page):
    """List products using the matching Magento REST endpoint."""
    operation: Literal["list_products"] = Field("list_products", json_schema_extra={"ui:hidden": True})


class GetProduct(_Sku):
    """Get product using the matching Magento REST endpoint."""
    operation: Literal["get_product"] = Field("get_product", json_schema_extra={"ui:hidden": True})


class DeleteProduct(_Sku):
    """Delete product using the matching Magento REST endpoint."""
    operation: Literal["delete_product"] = Field("delete_product", json_schema_extra={"ui:hidden": True})


class ListCustomers(_Page):
    """List customers using the matching Magento REST endpoint."""
    operation: Literal["list_customers"] = Field("list_customers", json_schema_extra={"ui:hidden": True})


class GetCustomer(_Input):
    """Get customer using the matching Magento REST endpoint."""
    operation: Literal["get_customer"] = Field("get_customer", json_schema_extra={"ui:hidden": True})
    customer_id: int = Field(..., ge=1)


class ListOrders(_Page):
    """List orders using the matching Magento REST endpoint."""
    operation: Literal["list_orders"] = Field("list_orders", json_schema_extra={"ui:hidden": True})


class GetOrder(_Order):
    """Get order using the matching Magento REST endpoint."""
    operation: Literal["get_order"] = Field("get_order", json_schema_extra={"ui:hidden": True})


class CancelOrder(_Order):
    """Cancel order using the matching Magento REST endpoint."""
    operation: Literal["cancel_order"] = Field("cancel_order", json_schema_extra={"ui:hidden": True})


class HoldOrder(_Order):
    """Hold order using the matching Magento REST endpoint."""
    operation: Literal["hold_order"] = Field("hold_order", json_schema_extra={"ui:hidden": True})


class UnholdOrder(_Order):
    """Unhold order using the matching Magento REST endpoint."""
    operation: Literal["unhold_order"] = Field("unhold_order", json_schema_extra={"ui:hidden": True})


class ListOrderComments(_Order):
    """List order comments using the matching Magento REST endpoint."""
    operation: Literal["list_order_comments"] = Field("list_order_comments", json_schema_extra={"ui:hidden": True})


class ListInvoices(_Page):
    """List invoices using the matching Magento REST endpoint."""
    operation: Literal["list_invoices"] = Field("list_invoices", json_schema_extra={"ui:hidden": True})


class GetInvoice(_Input):
    """Get invoice using the matching Magento REST endpoint."""
    operation: Literal["get_invoice"] = Field("get_invoice", json_schema_extra={"ui:hidden": True})
    invoice_id: int = Field(..., ge=1)


class ListShipments(_Page):
    """List shipments using the matching Magento REST endpoint."""
    operation: Literal["list_shipments"] = Field("list_shipments", json_schema_extra={"ui:hidden": True})


class GetShipment(_Input):
    """Get shipment using the matching Magento REST endpoint."""
    operation: Literal["get_shipment"] = Field("get_shipment", json_schema_extra={"ui:hidden": True})
    shipment_id: int = Field(..., ge=1)


class GetStockItem(_Sku):
    """Get stock item using the matching Magento REST endpoint."""
    operation: Literal["get_stock_item"] = Field("get_stock_item", json_schema_extra={"ui:hidden": True})


MagentoV2Operation = Annotated[Union[CreateProduct, UpdateProduct, CreateCustomer, UpdateCustomer, AddOrderComment, GetCategoryTree, GetCategory, ListProducts, GetProduct, DeleteProduct, ListCustomers, GetCustomer, ListOrders, GetOrder, CancelOrder, HoldOrder, UnholdOrder, ListOrderComments, ListInvoices, GetInvoice, ListShipments, GetShipment, GetStockItem], Field(discriminator="operation")]


class MagentoV2NodeConfig(NodeConfig[MagentoV2Operation, MagentoV2TokenCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, dict):
        return {_redact(k, token): _redact(v, token) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    return value


class MagentoV2Node(WorkflowNode):
    integration_type = "automation-magento-v2"
    connection_evidence = ConnectionEvidence(noun="products", operation="list_products", label_keys=("name", "sku", "id"))

    @classmethod
    def get_config_model(cls):
        return MagentoV2NodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Magento 2.X store access token")
        op = self.config.config
        credential = self.config.credentials
        method, route, params, body, kind = self._request(op)
        # Do not follow redirects: the merchant token must stay at the configured root.
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                kwargs = {"headers": {"Authorization": "Bearer " + credential.access_token, "Accept": "application/json"}, "params": params}
                if body is not None:
                    kwargs["json"] = body
                response = await client.request(method, credential.api_base_url + route, **kwargs)
        except Exception:
            raise ValueError("Magento request could not complete; inspect the store before retrying a write") from None
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Magento returned a non-JSON response; check the store REST root before retrying") from None
        if response.status_code >= 300 or (isinstance(payload, dict) and "message" in payload and "parameters" in payload):
            message = payload.get("message", "Magento rejected the request") if isinstance(payload, dict) else "Magento rejected the request"
            output = {"status": "error", "success": False, "http_status": response.status_code, "message": str(message)}
        else:
            output = self._output(op, payload, kind)
            output.setdefault("status", "success")
            output.setdefault("success", True)
            output["http_status"] = response.status_code
        output = _redact(output, credential.access_token)
        await self.emit(output)
        return output

    @staticmethod
    def _request(op):
        action = op.operation
        params, body = {}, None
        kind = "object"
        if action in {"list_products", "list_customers", "list_orders", "list_invoices", "list_shipments"}:
            route = {"list_products": "/V1/products", "list_customers": "/V1/customers/search", "list_orders": "/V1/orders", "list_invoices": "/V1/invoices", "list_shipments": "/V1/shipments"}[action]
            params = {"searchCriteria[pageSize]": op.page_size, "searchCriteria[currentPage]": op.current_page}
            if op.filter_field is not None:
                prefix = "searchCriteria[filterGroups][0][filters][0]"
                params.update({prefix + "[field]": op.filter_field, prefix + "[value]": op.filter_value, prefix + "[conditionType]": op.condition_type})
            if op.sort_field is not None:
                params.update({"searchCriteria[sortOrders][0][field]": op.sort_field, "searchCriteria[sortOrders][0][direction]": op.sort_direction})
            return "GET", route, params, None, "page"
        if action in {"get_product", "delete_product", "get_stock_item", "create_product", "update_product"}:
            sku = quote(op.sku, safe="")
            route = "/V1/stockItems/" + sku if action == "get_stock_item" else "/V1/products" + ("" if action == "create_product" else "/" + sku)
            if action in {"create_product", "update_product"}:
                product = op.model_dump(exclude={"operation"}, exclude_none=True)
                if action == "create_product":
                    product["type_id"] = "simple"
                body = {"product": product}
            method = {"create_product": "POST", "update_product": "PUT", "delete_product": "DELETE"}.get(action, "GET")
            return method, route, params, body, "boolean" if action == "delete_product" else kind
        if action in {"get_customer", "create_customer", "update_customer"}:
            identifier = getattr(op, "customer_id", None)
            route = "/V1/customers" + ("/" + str(identifier) if identifier is not None else "")
            if action != "get_customer":
                customer = op.model_dump(exclude={"operation", "customer_id"}, exclude_none=True)
                if identifier is not None:
                    customer["id"] = identifier
                body = {"customer": customer}
            return {"create_customer": "POST", "update_customer": "PUT"}.get(action, "GET"), route, params, body, kind
        if isinstance(op, _Order):
            route = "/V1/orders/" + str(op.order_id)
            suffix = {"cancel_order": "/cancel", "hold_order": "/hold", "unhold_order": "/unhold", "add_order_comment": "/comments", "list_order_comments": "/comments"}.get(action, "")
            if action == "add_order_comment":
                body = {"statusHistory": {"comment": op.comment, "parent_id": op.order_id, "is_customer_notified": int(op.notify_customer), "is_visible_on_front": int(op.visible_on_front)}}
            write = action in {"cancel_order", "hold_order", "unhold_order", "add_order_comment"}
            return "POST" if write else "GET", route + suffix, params, body, "boolean" if write else "collection" if action == "list_order_comments" else kind
        if action in {"get_invoice", "get_shipment"}:
            route = "/V1/invoices/" + str(op.invoice_id) if action == "get_invoice" else "/V1/shipment/" + str(op.shipment_id)
            return "GET", route, params, None, kind
        if action == "get_category_tree":
            params["depth"] = op.depth
            if op.root_category_id is not None:
                params["rootCategoryId"] = op.root_category_id
            return "GET", "/V1/categories", params, None, kind
        if action == "get_category":
            return "GET", "/V1/categories/" + str(op.category_id), params, None, kind
        raise ValueError("Unsupported Magento operation")

    @staticmethod
    def _output(op, payload, kind):
        if kind == "boolean":
            if type(payload) is not bool:
                raise ValueError("Magento acknowledgement must be a boolean; inspect before retrying")
            return {"data": payload, "acknowledged": payload, "operation": op.operation, "success": payload, "status": "success" if payload else "error"}
        if not isinstance(payload, dict):
            raise ValueError("Magento returned an unexpected object response")
        if kind in {"page", "collection"}:
            rows = payload.get("items")
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ValueError("Magento returned an unexpected search results envelope")
            output = {"data": payload}
            if kind == "page":
                total = payload.get("total_count")
                if type(total) is not int or total < 0:
                    raise ValueError("Magento search results are missing total_count")
                more = bool(rows) and op.current_page * op.page_size < total
                output["pagination"] = {"current_page": op.current_page, "page_size": op.page_size, "total_count": total, "has_more": more, "next_page": op.current_page + 1 if more else None}
            return output
        return {"data": payload}
