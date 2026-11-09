"""SureCart secret-key commerce operations against the published v1 API.

Each action makes one documented request. Lists expose page controls and the
provider pagination envelope so callers can continue without hidden fan-out.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.surecart.com"


class SureCartAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="SureCart API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.surecart.com/",
            "x-credential-instructions": "In your SureCart dashboard, copy a secret API key and paste it here. Public keys only support public endpoints and cannot run these actions. NoClick sends this key as a bearer token to api.surecart.com.",
        })
    credential_type: Literal["surecart_api_key"] = Field("surecart_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="Secret API key", min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        value = clean_secret(value, field_name="Secret API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the secret API key without a Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def bounded_ids(cls, value, info):
        if info.field_name.endswith("_id") and value is not None:
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
                raise ValueError("Use a single SureCart resource ID")
        return value


class _List(_Input):
    page: int = Field(1, ge=1, description="Page to return. Increment to continue through the collection.")
    limit: int = Field(20, ge=1, le=100, description="Number of items on this page (1–100).")


class SureCartGetAccountConfig(_Input):
    """Get account."""
    operation: Literal["get_account"] = Field("get_account", json_schema_extra={"ui:hidden": True})


class SureCartListCustomersConfig(_List):
    """List customers."""
    operation: Literal["list_customers"] = Field("list_customers", json_schema_extra={"ui:hidden": True})
    email: str | None = Field(None, max_length=1000)
    query: str | None = Field(None, max_length=1000)
    live_mode: bool | None = None


class SureCartGetCustomerConfig(_Input):
    """Get customer."""
    operation: Literal["get_customer"] = Field("get_customer", json_schema_extra={"ui:hidden": True})
    customer_id: str


class SureCartCreateCustomerConfig(_Input):
    """Create customer."""
    operation: Literal["create_customer"] = Field("create_customer", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=3, max_length=320)
    first_name: str | None = Field(None, max_length=1000)
    last_name: str | None = Field(None, max_length=1000)
    name: str | None = Field(None, max_length=1000)
    phone: str | None = Field(None, max_length=1000)
    live_mode: bool | None = None
    unsubscribed: bool | None = None


class SureCartUpdateCustomerConfig(_Input):
    """Update customer."""
    operation: Literal["update_customer"] = Field("update_customer", json_schema_extra={"ui:hidden": True})
    customer_id: str
    email: str | None = Field(None, max_length=1000)
    first_name: str | None = Field(None, max_length=1000)
    last_name: str | None = Field(None, max_length=1000)
    name: str | None = Field(None, max_length=1000)
    phone: str | None = Field(None, max_length=1000)
    live_mode: bool | None = None
    unsubscribed: bool | None = None


class SureCartListProductsConfig(_List):
    """List products."""
    operation: Literal["list_products"] = Field("list_products", json_schema_extra={"ui:hidden": True})
    query: str | None = Field(None, max_length=1000)
    archived: bool | None = None


class SureCartGetProductConfig(_Input):
    """Get product."""
    operation: Literal["get_product"] = Field("get_product", json_schema_extra={"ui:hidden": True})
    product_id: str


class SureCartCreateProductConfig(_Input):
    """Create product."""
    operation: Literal["create_product"] = Field("create_product", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=1000)
    description: str | None = Field(None, max_length=100000)
    sku: str | None = Field(None, max_length=1000)
    status: Literal["draft", "published"] | None = None
    archived: bool | None = None
    recurring: bool | None = None
    shipping_enabled: bool | None = None
    stock_enabled: bool | None = None
    stock_adjustment: int | None = None


class SureCartUpdateProductConfig(_Input):
    """Update product."""
    operation: Literal["update_product"] = Field("update_product", json_schema_extra={"ui:hidden": True})
    product_id: str
    name: str | None = Field(None, max_length=1000)
    description: str | None = Field(None, max_length=100000)
    sku: str | None = Field(None, max_length=1000)
    status: Literal["draft", "published"] | None = None
    archived: bool | None = None
    recurring: bool | None = None
    shipping_enabled: bool | None = None
    stock_enabled: bool | None = None
    stock_adjustment: int | None = None


class SureCartListOrdersConfig(_List):
    """List orders."""
    operation: Literal["list_orders"] = Field("list_orders", json_schema_extra={"ui:hidden": True})
    query: str | None = Field(None, max_length=1000)
    customer_id: str | None = None
    live_mode: bool | None = None


class SureCartGetOrderConfig(_Input):
    """Get order."""
    operation: Literal["get_order"] = Field("get_order", json_schema_extra={"ui:hidden": True})
    order_id: str


class SureCartListPurchasesConfig(_List):
    """List purchases."""
    operation: Literal["list_purchases"] = Field("list_purchases", json_schema_extra={"ui:hidden": True})
    customer_id: str | None = None
    product_id: str | None = None
    revoked: bool | None = None
    live_mode: bool | None = None


class SureCartGetPurchaseConfig(_Input):
    """Get purchase."""
    operation: Literal["get_purchase"] = Field("get_purchase", json_schema_extra={"ui:hidden": True})
    purchase_id: str


class SureCartCreatePurchaseConfig(_Input):
    """Grant a purchase to a customer using a price. This grants product access; it does not collect payment."""
    operation: Literal["create_purchase"] = Field("create_purchase", json_schema_extra={"ui:hidden": True})
    customer_id: str
    price_id: str
    quantity: int = Field(1, ge=1)


class SureCartRevokePurchaseConfig(_Input):
    """Revoke the selected purchase and its product access."""
    operation: Literal["revoke_purchase"] = Field("revoke_purchase", json_schema_extra={"ui:hidden": True})
    purchase_id: str


class SureCartInvokePurchaseConfig(_Input):
    """Restore access by invoking the selected purchase."""
    operation: Literal["invoke_purchase"] = Field("invoke_purchase", json_schema_extra={"ui:hidden": True})
    purchase_id: str


class SureCartListSubscriptionsConfig(_List):
    """List subscriptions."""
    operation: Literal["list_subscriptions"] = Field("list_subscriptions", json_schema_extra={"ui:hidden": True})
    query: str | None = Field(None, max_length=1000)
    customer_id: str | None = None
    cancel_at_period_end: bool | None = None


class SureCartGetSubscriptionConfig(_Input):
    """Get subscription."""
    operation: Literal["get_subscription"] = Field("get_subscription", json_schema_extra={"ui:hidden": True})
    subscription_id: str


class SureCartCancelSubscriptionConfig(_Input):
    """Cancel or pause a subscription. A restore time pauses it until that time."""
    operation: Literal["cancel_subscription"] = Field("cancel_subscription", json_schema_extra={"ui:hidden": True})
    subscription_id: str
    cancel_behavior: Literal["immediate", "pending"] | None = Field(None, description="Immediate cancellation or cancellation at period end. Omit to use the store protocol.")
    restore_at: int | None = Field(None, ge=0, description="Unix time to restore automatically, pausing the subscription until then.")


class SureCartRestoreSubscriptionConfig(_Input):
    """Restore a canceled or paused subscription; billing follows the store protocol."""
    operation: Literal["restore_subscription"] = Field("restore_subscription", json_schema_extra={"ui:hidden": True})
    subscription_id: str


class SureCartListCouponsConfig(_List):
    """List coupons."""
    operation: Literal["list_coupons"] = Field("list_coupons", json_schema_extra={"ui:hidden": True})
    query: str | None = Field(None, max_length=1000)
    archived: bool | None = None


class SureCartGetCouponConfig(_Input):
    """Get coupon."""
    operation: Literal["get_coupon"] = Field("get_coupon", json_schema_extra={"ui:hidden": True})
    coupon_id: str


class SureCartCreateCouponConfig(_Input):
    """Create a percentage discount coupon. A repeating coupon requires a duration in months."""
    operation: Literal["create_coupon"] = Field("create_coupon", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=1000)
    percent_off: float = Field(..., gt=0, le=100, allow_inf_nan=False)
    duration: Literal["once", "forever", "repeating"] = "once"
    duration_in_months: int | None = Field(None, ge=1)
    max_redemptions: int | None = Field(None, ge=1)

    @model_validator(mode="after")
    def repeating_months(self):
        if self.duration == "repeating" and self.duration_in_months is None:
            raise ValueError("Repeating coupons need duration_in_months")
        return self


class SureCartListPricesConfig(_List):
    """List prices."""
    operation: Literal["list_prices"] = Field("list_prices", json_schema_extra={"ui:hidden": True})
    product_id: str | None = None
    archived: bool | None = None


class SureCartGetPriceConfig(_Input):
    """Get price."""
    operation: Literal["get_price"] = Field("get_price", json_schema_extra={"ui:hidden": True})
    price_id: str


SureCartConfig = Annotated[Union[
    SureCartGetAccountConfig,
    SureCartListCustomersConfig,
    SureCartGetCustomerConfig,
    SureCartCreateCustomerConfig,
    SureCartUpdateCustomerConfig,
    SureCartListProductsConfig,
    SureCartGetProductConfig,
    SureCartCreateProductConfig,
    SureCartUpdateProductConfig,
    SureCartListOrdersConfig,
    SureCartGetOrderConfig,
    SureCartListPurchasesConfig,
    SureCartGetPurchaseConfig,
    SureCartCreatePurchaseConfig,
    SureCartRevokePurchaseConfig,
    SureCartInvokePurchaseConfig,
    SureCartListSubscriptionsConfig,
    SureCartGetSubscriptionConfig,
    SureCartCancelSubscriptionConfig,
    SureCartRestoreSubscriptionConfig,
    SureCartListCouponsConfig,
    SureCartGetCouponConfig,
    SureCartCreateCouponConfig,
    SureCartListPricesConfig,
    SureCartGetPriceConfig
], Field(discriminator="operation")]


class SureCartFullConfig(NodeConfig[SureCartConfig, SureCartAPIKeyCredential]):
    pass


ROUTES = {'get_account': ('GET', '/v1/account', None, {}),
 'list_customers': ('GET', '/v1/customers', None, {}),
 'get_customer': ('GET', '/v1/customers/{customer_id}', None, {}),
 'create_customer': ('POST', '/v1/customers', 'customer', {}),
 'update_customer': ('PATCH', '/v1/customers/{customer_id}', 'customer', {}),
 'list_products': ('GET', '/v1/products', None, {}),
 'get_product': ('GET', '/v1/products/{product_id}', None, {}),
 'create_product': ('POST', '/v1/products', 'product', {}),
 'update_product': ('PATCH', '/v1/products/{product_id}', 'product', {}),
 'list_orders': ('GET', '/v1/orders', None, {'customer_id': 'customer_ids[]'}),
 'get_order': ('GET', '/v1/orders/{order_id}', None, {}),
 'list_purchases': ('GET',
                    '/v1/purchases',
                    None,
                    {'customer_id': 'customer_ids[]', 'product_id': 'product_ids[]'}),
 'get_purchase': ('GET', '/v1/purchases/{purchase_id}', None, {}),
 'create_purchase': ('POST',
                     '/v1/purchases',
                     'purchase',
                     {'customer_id': 'customer', 'price_id': 'price'}),
 'revoke_purchase': ('PATCH', '/v1/purchases/{purchase_id}/revoke', None, {}),
 'invoke_purchase': ('PATCH', '/v1/purchases/{purchase_id}/invoke', None, {}),
 'list_subscriptions': ('GET', '/v1/subscriptions', None, {'customer_id': 'customer_ids[]'}),
 'get_subscription': ('GET', '/v1/subscriptions/{subscription_id}', None, {}),
 'cancel_subscription': ('PATCH',
                         '/v1/subscriptions/{subscription_id}/cancel',
                         'subscription',
                         {'cancel_behavior': 'cancel_behavior'}),
 'restore_subscription': ('PATCH', '/v1/subscriptions/{subscription_id}/restore', None, {}),
 'list_coupons': ('GET', '/v1/coupons', None, {}),
 'get_coupon': ('GET', '/v1/coupons/{coupon_id}', None, {}),
 'create_coupon': ('POST', '/v1/coupons', 'coupon', {}),
 'list_prices': ('GET', '/v1/prices', None, {'product_id': 'product_ids[]'}),
 'get_price': ('GET', '/v1/prices/{price_id}', None, {})}


class SureCartNode(WorkflowNode):
    integration_type = "automation-surecart"
    connection_evidence = ConnectionEvidence(
        noun="products", operation="list_products", identity_operation="get_account")

    @classmethod
    def get_config_model(cls):
        return SureCartFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a SureCart secret API key")
        cfg = self.config.config
        method, template, wrapper, mapping = ROUTES[cfg.operation]
        values = cfg.model_dump(exclude_none=True, exclude={"operation"})
        path = template
        for name in re.findall(r"\{([^}]+)\}", template):
            path = path.replace("{" + name + "}", quote(values.pop(name), safe=""))
        params = {}
        body = None
        if cfg.operation == "cancel_subscription":
            behavior = values.pop("cancel_behavior", None)
            if behavior is not None:
                params["cancel_behavior"] = behavior
        values = {mapping.get(k, k): v for k, v in values.items()}
        if wrapper:
            body = {wrapper: values}
        else:
            params.update(values)
        params = {k: str(v).lower() if isinstance(v, bool) else v for k, v in params.items()}
        key = self.config.credentials.api_key
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path,
                headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
                params=params, **({"json": body} if body is not None else {}))
        if response.is_error or response.is_redirect:
            # Keep the provider's rejection visible to the shared connection seam.
            message = response.text[:2000].replace(key, "[redacted]") or f"SureCart returned HTTP {response.status_code}"
            return {"status": "error", "status_code": response.status_code, "error": message}
        data = response.json()
        if not isinstance(data, dict) or data.get("errors") or data.get("error"):
            raise ValueError("SureCart returned an unexpected response")
        if cfg.operation.startswith("list_"):
            items, pagination = data.get("data"), data.get("pagination")
            if not isinstance(items, list) or not isinstance(pagination, dict):
                raise ValueError("SureCart list response needs data and pagination")
            return {"status": "success", "items": items, "pagination": pagination}
        return {"status": "success", "item": data}
