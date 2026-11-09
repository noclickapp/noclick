"""Katana manufacturing and inventory workflows using a person's API key.

Routes and request fields follow Katana's pinned public OpenAPI contract.
Pagination and signed sales-order deliveries follow its official developer docs.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, Json, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase

BASE_URL = "https://api.katanamrp.com/v1"


class KatanaMRPAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Katana API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://developer.katanamrp.com/reference/api-authentication",
        "x-credential-instructions": "In Katana, go to Settings > API and add an API key. Paste the key here without the Bearer prefix. NoClick sends it to api.katanamrp.com to access your Katana account.",
    })
    credential_type: Literal["katana_mrp_api_key"] = Field("katana_mrp_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})


    @field_validator("api_key", mode="before")
    @classmethod
    def clean_api_key(cls, value):
        value = clean_secret(value, field_name="API Key", key=True)
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the Katana API key, without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Page(_Input):
    page: int = Field(1, ge=1, title="Page", description="One-based page number; Katana returns one page per run.")
    limit: int = Field(50, ge=1, le=250, title="Page Size")


class _ID(_Input):
    id: int = Field(..., ge=1, le=2147483647, title="Katana ID")


class KatanaMRPGetUserInfoConfig(_Input):
    operation: Literal["get_user_info"] = "get_user_info"


class KatanaMRPListLocationsConfig(_Page):
    operation: Literal["list_locations"] = "list_locations"
    name: str | None = None


class KatanaMRPListInventoryConfig(_Page):
    operation: Literal["list_inventory"] = "list_inventory"
    location_id: int | None = Field(None, ge=1, le=2147483647)
    include_archived: bool | None = None


class KatanaMRPListProductsConfig(_Page):
    operation: Literal["list_products"] = "list_products"
    name: str | None = None
    category_name: str | None = None
    is_sellable: bool | None = None
    is_producible: bool | None = None


class KatanaMRPGetProductConfig(_ID):
    operation: Literal["get_product"] = "get_product"


class KatanaMRPListMaterialsConfig(_Page):
    operation: Literal["list_materials"] = "list_materials"
    name: str | None = None
    category_name: str | None = None


class KatanaMRPListVariantsConfig(_Page):
    operation: Literal["list_variants"] = "list_variants"
    product_id: int | None = Field(None, ge=1, le=2147483647)
    material_id: int | None = Field(None, ge=1, le=2147483647)
    type: Literal["product", "material"] | None = None


class KatanaMRPGetVariantConfig(_ID):
    operation: Literal["get_variant"] = "get_variant"


class KatanaMRPUpdateVariantConfig(_ID):
    operation: Literal["update_variant"] = "update_variant"
    sku: str | None = Field(None, min_length=1)
    sales_price: float | None = Field(None, ge=0, le=100000000000)
    purchase_price: float | None = Field(None, ge=0, le=100000000000)
    lead_time: float | None = Field(None, ge=0, le=2147483647)
    minimum_order_quantity: float | None = Field(None, ge=0, le=2147483647)


class KatanaMRPListCustomersConfig(_Page):
    operation: Literal["list_customers"] = "list_customers"
    name: str | None = None
    email: str | None = None
    company: str | None = None


class _CustomerFields(_Input):
    name: str | None = Field(None, min_length=1)
    first_name: str | None = Field(None, min_length=1)
    last_name: str | None = Field(None, min_length=1)
    company: str | None = Field(None, min_length=1)
    email: str | None = Field(None, min_length=1)
    phone: str | None = Field(None, min_length=1)
    currency: str | None = Field(None, min_length=1)
    comment: str | None = Field(None, min_length=1)


class KatanaMRPCreateCustomerConfig(_CustomerFields):
    operation: Literal["create_customer"] = "create_customer"
    name: str = Field(..., min_length=1)


class KatanaMRPUpdateCustomerConfig(_CustomerFields, _ID):
    operation: Literal["update_customer"] = "update_customer"


class KatanaMRPListSuppliersConfig(_Page):
    operation: Literal["list_suppliers"] = "list_suppliers"
    name: str | None = None
    email: str | None = None


class KatanaMRPCreateSupplierConfig(_Input):
    operation: Literal["create_supplier"] = "create_supplier"
    name: str = Field(..., min_length=1)
    email: str | None = Field(None, min_length=1)
    phone: str | None = Field(None, min_length=1, max_length=30)
    currency: str | None = Field(None, min_length=1)
    comment: str | None = Field(None, min_length=1)


class KatanaMRPListSalesOrdersConfig(_Page):
    operation: Literal["list_sales_orders"] = "list_sales_orders"
    order_no: str | None = None
    customer_id: int | None = Field(None, ge=1, le=2147483647)
    status: Literal["PENDING", "NOT_SHIPPED", "READY_FOR_FULFILLMENT", "PACKED", "DELIVERED"] | None = None


class KatanaMRPGetSalesOrderConfig(_ID):
    operation: Literal["get_sales_order"] = "get_sales_order"


class KatanaMRPSalesOrderRow(_Input):
    variant_id: int = Field(..., ge=1, le=2147483647)
    quantity: float = Field(..., ge=0, le=100000000000000000)
    price_per_unit: float | None = Field(None, ge=0, le=1000000000000000000)
    tax_rate_id: int | None = Field(None, ge=1, le=2147483647)
    location_id: int | None = Field(None, ge=1, le=2147483647)


class KatanaMRPCreateSalesOrderConfig(_Input):
    operation: Literal["create_sales_order"] = "create_sales_order"
    customer_id: int = Field(..., ge=0, le=2147483647)
    sales_order_rows: Json[Annotated[list[KatanaMRPSalesOrderRow], Field(min_length=1)]] = Field(
        ..., title="Sales Order Rows (JSON)", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    order_no: str | None = Field(None, min_length=1)
    location_id: int | None = Field(None, ge=0, le=2147483647)
    status: Literal["PENDING", "NOT_SHIPPED"] | None = None
    currency: str | None = None
    delivery_date: str | None = None
    additional_info: str | None = None


class KatanaMRPUpdateSalesOrderConfig(_ID):
    operation: Literal["update_sales_order"] = "update_sales_order"
    status: Literal["PENDING", "NOT_SHIPPED", "READY_FOR_FULFILLMENT", "PACKED", "DELIVERED"] | None = None
    order_no: str | None = Field(None, min_length=1)
    delivery_date: str | None = None
    tracking_number: str | None = Field(None, min_length=1, max_length=256)
    tracking_number_url: str | None = Field(None, min_length=1, max_length=2048)
    additional_info: str | None = None


class KatanaMRPListPurchaseOrdersConfig(_Page):
    operation: Literal["list_purchase_orders"] = "list_purchase_orders"
    order_no: str | None = None
    supplier_id: int | None = Field(None, ge=1, le=2147483647)
    status: Literal["DRAFT", "NOT_RECEIVED", "PARTIALLY_RECEIVED", "RECEIVED"] | None = None


class KatanaMRPPurchaseOrderRow(_Input):
    variant_id: int = Field(..., ge=1, le=2147483647)
    quantity: float = Field(..., ge=0, le=100000000000000000)
    price_per_unit: float = Field(..., ge=0, le=100000000000000000)
    tax_rate_id: int | None = Field(None, ge=1, le=2147483647)


class KatanaMRPCreatePurchaseOrderConfig(_Input):
    operation: Literal["create_purchase_order"] = "create_purchase_order"
    supplier_id: int = Field(..., ge=1, le=2147483647)
    location_id: int = Field(..., ge=1, le=2147483647)
    purchase_order_rows: Json[Annotated[list[KatanaMRPPurchaseOrderRow], Field(min_length=1)]] = Field(
        ..., title="Purchase Order Rows (JSON)", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    order_no: str | None = Field(None, min_length=1)
    currency: str | None = Field(None, min_length=1)
    status: Literal["DRAFT", "NOT_RECEIVED"] | None = None
    expected_arrival_date: str | None = Field(None, json_schema_extra={"format": "date"})
    additional_info: str | None = None


class KatanaMRPListManufacturingOrdersConfig(_Page):
    operation: Literal["list_manufacturing_orders"] = "list_manufacturing_orders"
    order_no: str | None = None
    status: Literal["NOT_STARTED", "BLOCKED", "IN_PROGRESS", "PARTIALLY_COMPLETED", "DONE"] | None = None
    location_id: int | None = Field(None, ge=1, le=2147483647)


class KatanaMRPCreateManufacturingOrderConfig(_Input):
    operation: Literal["create_manufacturing_order"] = "create_manufacturing_order"
    variant_id: int = Field(..., ge=1, le=2147483647)
    planned_quantity: float = Field(..., ge=0.00001, le=1000000000000000)
    location_id: int = Field(..., ge=1, le=2147483647)
    order_no: str | None = Field(None, min_length=1)
    production_deadline_date: str | None = Field(None, min_length=1)
    additional_info: str | None = Field(None, min_length=1)


class KatanaMRPUpdateManufacturingOrderConfig(_ID):
    operation: Literal["update_manufacturing_order"] = "update_manufacturing_order"
    status: Literal["NOT_STARTED", "BLOCKED", "IN_PROGRESS", "PARTIALLY_COMPLETED", "DONE"] | None = None
    planned_quantity: float | None = Field(None, ge=0.00001, le=1000000000000000)
    actual_quantity: float | None = Field(None, ge=0, le=1000000000000000)
    production_deadline_date: str | None = Field(None, min_length=1)
    additional_info: str | None = Field(None, min_length=1)


class KatanaMRPOnSalesOrderDeliveredConfig(WebhookTriggerConfigBase):
    """The provider publishes a concrete delivery payload for this event."""
    operation: Literal["on_sales_order_delivered"] = Field("on_sales_order_delivered", json_schema_extra={
        "x-is-trigger": True, "x-display-name": "On Sales Order Delivered", "x-category": "Triggers", "ui:hidden": True})
    webhook_url: str | None = Field(None, title="Webhook URL", json_schema_extra={
        "ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    model: type[BaseModel]


OPERATIONS = {
    "get_user_info": Operation("GET", "/user_info", KatanaMRPGetUserInfoConfig),
    "list_locations": Operation("GET", "/locations", KatanaMRPListLocationsConfig),
    "list_inventory": Operation("GET", "/inventory", KatanaMRPListInventoryConfig),
    "list_products": Operation("GET", "/products", KatanaMRPListProductsConfig),
    "get_product": Operation("GET", "/products/{id}", KatanaMRPGetProductConfig),
    "list_materials": Operation("GET", "/materials", KatanaMRPListMaterialsConfig),
    "list_variants": Operation("GET", "/variants", KatanaMRPListVariantsConfig),
    "get_variant": Operation("GET", "/variants/{id}", KatanaMRPGetVariantConfig),
    "update_variant": Operation("PATCH", "/variants/{id}", KatanaMRPUpdateVariantConfig),
    "list_customers": Operation("GET", "/customers", KatanaMRPListCustomersConfig),
    "create_customer": Operation("POST", "/customers", KatanaMRPCreateCustomerConfig),
    "update_customer": Operation("PATCH", "/customers/{id}", KatanaMRPUpdateCustomerConfig),
    "list_suppliers": Operation("GET", "/suppliers", KatanaMRPListSuppliersConfig),
    "create_supplier": Operation("POST", "/suppliers", KatanaMRPCreateSupplierConfig),
    "list_sales_orders": Operation("GET", "/sales_orders", KatanaMRPListSalesOrdersConfig),
    "get_sales_order": Operation("GET", "/sales_orders/{id}", KatanaMRPGetSalesOrderConfig),
    "create_sales_order": Operation("POST", "/sales_orders", KatanaMRPCreateSalesOrderConfig),
    "update_sales_order": Operation("PATCH", "/sales_orders/{id}", KatanaMRPUpdateSalesOrderConfig),
    "list_purchase_orders": Operation("GET", "/purchase_orders", KatanaMRPListPurchaseOrdersConfig),
    "create_purchase_order": Operation("POST", "/purchase_orders", KatanaMRPCreatePurchaseOrderConfig),
    "list_manufacturing_orders": Operation("GET", "/manufacturing_orders", KatanaMRPListManufacturingOrdersConfig),
    "create_manufacturing_order": Operation("POST", "/manufacturing_orders", KatanaMRPCreateManufacturingOrderConfig),
    "update_manufacturing_order": Operation("PATCH", "/manufacturing_orders/{id}", KatanaMRPUpdateManufacturingOrderConfig),
}

KatanaMRPConfig = Annotated[Union[tuple(spec.model for spec in OPERATIONS.values()) +
    (KatanaMRPOnSalesOrderDeliveredConfig,)], Field(discriminator="operation")]


class KatanaMRPNodeConfig(NodeConfig[KatanaMRPConfig, KatanaMRPAPIKeyCredential]):
    pass


class KatanaMRPNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-katana-mrp"
    connection_evidence = ConnectionEvidence(operation="list_customers", noun="customers", identity_operation="get_user_info")

    @classmethod
    def get_config_model(cls):
        return KatanaMRPNodeConfig

    @staticmethod
    async def _request(api_key: str, method: str, path: str, *, params=None, body=None):
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path, params=params, json=body,
                headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"})
        if not 200 <= response.status_code < 300:
            raise httpx.HTTPStatusError(
                f"Katana API error {response.status_code}: {response.text[:2000]}",
                request=response.request, response=response)
        return response.json() if response.content else {}

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, KatanaMRPNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect a Katana API key")
        config = self.config.config
        if isinstance(config, KatanaMRPOnSalesOrderDeliveredConfig):
            return {"status": "no_event", "message": "Waiting for a signed Katana sales order delivery."}
        spec = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path = spec.path
        if "{id}" in path:
            path = path.replace("{id}", str(values.pop("id")))
        if spec.method == "PATCH" and not values:
            raise ValueError("Supply at least one field to update")
        data = await self._request(self.config.credentials.api_key, spec.method, path,
            params=values if spec.method == "GET" else None,
            body=values if spec.method in {"POST", "PATCH"} else None)
        return {"status": "success", "operation": config.operation, "data": data}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        data = await cls._request(credential["api_key"], "POST", "/webhooks", body={
            "url": webhook_url, "subscribed_events": ["sales_order.delivered"]})
        if not isinstance(data, dict) or not data.get("id") or not data.get("token"):
            raise ValueError("Katana did not return a webhook ID and secret token")
        return {"external_webhook_id": str(data["id"]), "signing_secret": data["token"]}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        webhook_id = (config or {}).get("external_webhook_id")
        if webhook_id is None:
            return
        # Katana webhook IDs are integers; reject arbitrary path fragments.
        if not str(webhook_id).isdigit() or int(webhook_id) < 1:
            raise ValueError("Invalid Katana webhook ID")
        await cls._request(credential["api_key"], "DELETE", f"/webhooks/{int(webhook_id)}")

    @classmethod
    def verify_webhook_signature(cls, body: bytes, headers: dict[str, str], config: dict[str, Any]) -> bool:
        secret = (config or {}).get("signing_secret")
        signature = next((v for k, v in headers.items() if k.lower() == "x-sha2-signature"), "")
        if not isinstance(secret, str) or not secret or not isinstance(signature, str):
            return False
        try:
            received = bytes.fromhex(signature)
        except ValueError:
            return False
        expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
        return hmac.compare_digest(received, expected)

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return payload.get("action") == "sales_order.delivered" and payload.get("resource_type") == "sales_order"

    @classmethod
    def resolve_agent_event(cls, output):
        order = output.get("object")
        if output.get("action") != "sales_order.delivered" or not isinstance(order, dict) or not order.get("id"):
            return None
        order_id = order["id"]
        return {
            "text": f"Katana reports sales order {order_id} delivered.\nStatus: {order.get('status')}\n"
                    f"Resource: {order.get('href')}\nWebhook: {output.get('webhook_id')}\n"
                    f"Use get_sales_order or update_sales_order with id={order_id} to act.",
            "title": f"Sales order {order_id} delivered", "conversation_key": str(order_id),
        }
