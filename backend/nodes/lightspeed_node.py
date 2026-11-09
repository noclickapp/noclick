"""Lightspeed Retail X-Series, pinned to the provider's 2026-10 API.

Token setup: https://x-series-support.lightspeedhq.com/hc/en-us/articles/25534105904027
Endpoint contract: https://x-series-api.lightspeedhq.com/openapi/api-2026-10.yaml
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.scopes.lightspeed import LIGHTSPEED_SCOPES
from utils.ssrf import guarded_async_client


class LightspeedTokenCredential(BaseModel):
    model_config = ConfigDict(
        title="Lightspeed API Token",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developers.retail.lightspeed.app/",
            "x-credential-instructions": "For Retail X-Series on the Plus plan, paste a private app token from Developer Portal > Organizations > Edit application > Generate New Token, after the store admin approves the app. Legacy personal tokens from Setup > Personal tokens also work where available. New accounts use private apps. Enter only your store domain prefix, for example mystore from mystore.retail.lightspeed.app. Grant the scopes needed for your operations, including outlets:read to verify the connection. Tokens are sent only to that store; NoClick does not refresh them. Replace expired or revoked tokens here.",
        },
    )
    credential_type: Literal["lightspeed_api_token"] = Field(
        "lightspeed_api_token", json_schema_extra={"ui:hidden": True}
    )
    domain_prefix: str = Field(
        ...,
        min_length=1,
        max_length=63,
        title="Store domain prefix",
        description="The store subdomain before .retail.lightspeed.app, without a URL.",
    )
    api_token: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        title="API token",
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("domain_prefix", mode="before")
    @classmethod
    def domain(cls, value):
        if not isinstance(value, str):
            raise ValueError("Enter your store domain prefix")
        value = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", value):
            raise ValueError(
                "Enter only the store prefix before .retail.lightspeed.app"
            )
        return value

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token", key=True)
        if not value or any(ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the token alone, without spaces or a Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def identifiers(cls, value, info):
        if value is not None and info.field_name.endswith("_id"):
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
                raise ValueError("Use one Lightspeed resource ID")
        return value


class GetRetailerConfig(_Input):
    """Get information about this retailer."""

    operation: Literal["get_retailer"] = Field(
        "get_retailer", json_schema_extra={"ui:hidden": True}
    )


class ListCustomersConfig(_Input):
    """List customers."""

    operation: Literal["list_customers"] = Field(
        "list_customers", json_schema_extra={"ui:hidden": True}
    )
    after: Optional[int] = Field(
        None, ge=0, description="Version cursor, not an offset"
    )
    before: Optional[int] = Field(
        None, ge=0, description="Version cursor, not an offset"
    )
    page_size: int = Field(
        100,
        ge=1,
        le=1000,
        description="One page only. Continue using the returned version.max as after.",
    )
    deleted: Optional[bool] = None


class GetCustomerConfig(_Input):
    """Get a single customer."""

    operation: Literal["get_customer"] = Field(
        "get_customer", json_schema_extra={"ui:hidden": True}
    )
    customer_id: str = Field(
        ..., min_length=1, max_length=128, description="Lightspeed resource ID"
    )


class CreateCustomerConfig(_Input):
    """Create a new customer."""

    operation: Literal["create_customer"] = Field(
        "create_customer", json_schema_extra={"ui:hidden": True}
    )
    first_name: str = Field(..., min_length=1, max_length=255)
    last_name: str = Field(..., min_length=1, max_length=255)
    email: Optional[str] = Field(None, max_length=2000)
    phone: Optional[str] = Field(None, max_length=2000)
    mobile: Optional[str] = Field(None, max_length=2000)
    company_name: Optional[str] = Field(None, max_length=2000)
    customer_code: Optional[str] = Field(None, max_length=2000)
    customer_group_id: Optional[str] = Field(None, max_length=2000)
    note: Optional[str] = Field(None, max_length=2000)
    do_not_email: Optional[bool] = None
    enable_promotional_sms: Optional[bool] = None


class UpdateCustomerConfig(_Input):
    """Update a customer."""

    operation: Literal["update_customer"] = Field(
        "update_customer", json_schema_extra={"ui:hidden": True}
    )
    customer_id: str = Field(
        ..., min_length=1, max_length=128, description="Lightspeed resource ID"
    )
    first_name: str = Field(..., min_length=1, max_length=255)
    last_name: str = Field(..., min_length=1, max_length=255)
    email: Optional[str] = Field(None, max_length=2000)
    phone: Optional[str] = Field(None, max_length=2000)
    mobile: Optional[str] = Field(None, max_length=2000)
    company_name: Optional[str] = Field(None, max_length=2000)
    customer_code: Optional[str] = Field(None, max_length=2000)
    customer_group_id: Optional[str] = Field(None, max_length=2000)
    note: Optional[str] = Field(None, max_length=2000)
    do_not_email: Optional[bool] = None
    enable_promotional_sms: Optional[bool] = None


class ListProductsConfig(_Input):
    """List products."""

    operation: Literal["list_products"] = Field(
        "list_products", json_schema_extra={"ui:hidden": True}
    )
    after: Optional[int] = Field(
        None, ge=0, description="Version cursor, not an offset"
    )
    page_size: int = Field(
        100,
        ge=1,
        le=1000,
        description="One page only. Continue using the returned version.max as after.",
    )
    sku: Optional[str] = Field(None, max_length=255)


class GetProductConfig(_Input):
    """Get product by ID."""

    operation: Literal["get_product"] = Field(
        "get_product", json_schema_extra={"ui:hidden": True}
    )
    product_id: str = Field(
        ..., min_length=1, max_length=128, description="Lightspeed resource ID"
    )


class ListSalesConfig(_Input):
    """List Sales."""

    operation: Literal["list_sales"] = Field(
        "list_sales", json_schema_extra={"ui:hidden": True}
    )
    after: Optional[int] = Field(
        None, ge=0, description="Version cursor, not an offset"
    )
    before: Optional[int] = Field(
        None, ge=0, description="Version cursor, not an offset"
    )
    page_size: int = Field(
        100,
        ge=1,
        le=1000,
        description="One page only. Continue using the returned version.max as after.",
    )


class GetSaleConfig(_Input):
    """Get a single sale."""

    operation: Literal["get_sale"] = Field(
        "get_sale", json_schema_extra={"ui:hidden": True}
    )
    sale_id: str = Field(
        ..., min_length=1, max_length=128, description="Lightspeed resource ID"
    )


class ListProductInventoryConfig(_Input):
    """List inventory records for a single product."""

    operation: Literal["list_product_inventory"] = Field(
        "list_product_inventory", json_schema_extra={"ui:hidden": True}
    )
    product_id: str = Field(
        ..., min_length=1, max_length=128, description="Lightspeed resource ID"
    )
    after: Optional[int] = Field(
        None, ge=0, description="Version cursor, not an offset"
    )
    before: Optional[int] = Field(
        None, ge=0, description="Version cursor, not an offset"
    )
    page_size: int = Field(
        100,
        ge=1,
        le=1000,
        description="One page only. Continue using the returned version.max as after.",
    )
    variants: Optional[bool] = None
    include_deleted: Optional[bool] = None
    order_direction: Optional[Literal["asc", "desc"]] = None


class ListOutletsConfig(_Input):
    """List outlets."""

    operation: Literal["list_outlets"] = Field(
        "list_outlets", json_schema_extra={"ui:hidden": True}
    )
    after: Optional[int] = Field(
        None, ge=0, description="Version cursor, not an offset"
    )
    before: Optional[int] = Field(
        None, ge=0, description="Version cursor, not an offset"
    )
    page_size: int = Field(
        100,
        ge=1,
        le=1000,
        description="One page only. Continue using the returned version.max as after.",
    )
    deleted: Optional[bool] = None


class GetOutletConfig(_Input):
    """Get a single outlet."""

    operation: Literal["get_outlet"] = Field(
        "get_outlet", json_schema_extra={"ui:hidden": True}
    )
    outlet_id: str = Field(
        ..., min_length=1, max_length=128, description="Lightspeed resource ID"
    )


class ListRegistersConfig(_Input):
    """List registers."""

    operation: Literal["list_registers"] = Field(
        "list_registers", json_schema_extra={"ui:hidden": True}
    )
    after: Optional[int] = Field(
        None, ge=0, description="Version cursor, not an offset"
    )
    before: Optional[int] = Field(
        None, ge=0, description="Version cursor, not an offset"
    )
    deleted: Optional[bool] = None
    page_size: int = Field(
        100,
        ge=1,
        le=1000,
        description="One page only. Continue using the returned version.max as after.",
    )


class GetRegisterConfig(_Input):
    """Get a single register."""

    operation: Literal["get_register"] = Field(
        "get_register", json_schema_extra={"ui:hidden": True}
    )
    register_id: str = Field(
        ..., min_length=1, max_length=128, description="Lightspeed resource ID"
    )


class ListBrandsConfig(_Input):
    """List brands."""

    operation: Literal["list_brands"] = Field(
        "list_brands", json_schema_extra={"ui:hidden": True}
    )
    after: Optional[int] = Field(
        None, ge=0, description="Version cursor, not an offset"
    )
    before: Optional[int] = Field(
        None, ge=0, description="Version cursor, not an offset"
    )
    page_size: int = Field(
        100,
        ge=1,
        le=1000,
        description="One page only. Continue using the returned version.max as after.",
    )
    deleted: Optional[bool] = None


class GetBrandConfig(_Input):
    """Get a single brand."""

    operation: Literal["get_brand"] = Field(
        "get_brand", json_schema_extra={"ui:hidden": True}
    )
    brand_id: str = Field(
        ..., min_length=1, max_length=128, description="Lightspeed resource ID"
    )


class CreateBrandConfig(_Input):
    """Create brand."""

    operation: Literal["create_brand"] = Field(
        "create_brand", json_schema_extra={"ui:hidden": True}
    )
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=4000)


class UpdateBrandConfig(_Input):
    """Update a single brand."""

    operation: Literal["update_brand"] = Field(
        "update_brand", json_schema_extra={"ui:hidden": True}
    )
    brand_id: str = Field(
        ..., min_length=1, max_length=128, description="Lightspeed resource ID"
    )
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=4000)


class ListSuppliersConfig(_Input):
    """List suppliers."""

    operation: Literal["list_suppliers"] = Field(
        "list_suppliers", json_schema_extra={"ui:hidden": True}
    )
    after: Optional[int] = Field(
        None, ge=0, description="Version cursor, not an offset"
    )
    before: Optional[int] = Field(
        None, ge=0, description="Version cursor, not an offset"
    )
    page_size: int = Field(
        100,
        ge=1,
        le=1000,
        description="One page only. Continue using the returned version.max as after.",
    )
    deleted: Optional[bool] = None


class GetSupplierConfig(_Input):
    """Get a single supplier."""

    operation: Literal["get_supplier"] = Field(
        "get_supplier", json_schema_extra={"ui:hidden": True}
    )
    supplier_id: str = Field(
        ..., min_length=1, max_length=128, description="Lightspeed resource ID"
    )


class CreateSupplierConfig(_Input):
    """Create new supplier."""

    operation: Literal["create_supplier"] = Field(
        "create_supplier", json_schema_extra={"ui:hidden": True}
    )
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=4000)

    contact_email: Optional[str] = Field(None, max_length=255)
    contact_phone: Optional[str] = Field(None, max_length=255)


class ListCustomerGroupsConfig(_Input):
    """List customer groups."""

    operation: Literal["list_customer_groups"] = Field(
        "list_customer_groups", json_schema_extra={"ui:hidden": True}
    )
    after: Optional[int] = Field(
        None, ge=0, description="Version cursor, not an offset"
    )
    before: Optional[int] = Field(
        None, ge=0, description="Version cursor, not an offset"
    )
    page_size: int = Field(
        100,
        ge=1,
        le=1000,
        description="One page only. Continue using the returned version.max as after.",
    )
    deleted: Optional[bool] = None


class ListTaxesConfig(_Input):
    """List taxes."""

    operation: Literal["list_taxes"] = Field(
        "list_taxes", json_schema_extra={"ui:hidden": True}
    )
    after: Optional[int] = Field(
        None, ge=0, description="Version cursor, not an offset"
    )
    before: Optional[int] = Field(
        None, ge=0, description="Version cursor, not an offset"
    )
    page_size: int = Field(
        100,
        ge=1,
        le=1000,
        description="One page only. Continue using the returned version.max as after.",
    )


LightspeedOperation = Annotated[
    Union[
        GetRetailerConfig,
        ListCustomersConfig,
        GetCustomerConfig,
        CreateCustomerConfig,
        UpdateCustomerConfig,
        ListProductsConfig,
        GetProductConfig,
        ListSalesConfig,
        GetSaleConfig,
        ListProductInventoryConfig,
        ListOutletsConfig,
        GetOutletConfig,
        ListRegistersConfig,
        GetRegisterConfig,
        ListBrandsConfig,
        GetBrandConfig,
        CreateBrandConfig,
        UpdateBrandConfig,
        ListSuppliersConfig,
        GetSupplierConfig,
        CreateSupplierConfig,
        ListCustomerGroupsConfig,
        ListTaxesConfig,
    ],
    Field(discriminator="operation"),
]


class LightspeedConfig(NodeConfig[LightspeedOperation, LightspeedTokenCredential]):
    pass


ROUTES = {
    "get_retailer": ("GET", "/retailer", [], []),
    "list_customers": (
        "GET",
        "/customers",
        [
            ("after", "after", "query"),
            ("before", "before", "query"),
            ("page_size", "page_size", "query"),
            ("deleted", "deleted", "query"),
        ],
        [],
    ),
    "get_customer": ("GET", "/customers/{id}", [("id", "customer_id", "path")], []),
    "create_customer": (
        "POST",
        "/customers",
        [],
        [
            "first_name",
            "last_name",
            "email",
            "phone",
            "mobile",
            "company_name",
            "customer_code",
            "customer_group_id",
            "note",
            "do_not_email",
            "enable_promotional_sms",
        ],
    ),
    "update_customer": (
        "PUT",
        "/customers/{id}",
        [("id", "customer_id", "path")],
        [
            "first_name",
            "last_name",
            "email",
            "phone",
            "mobile",
            "company_name",
            "customer_code",
            "customer_group_id",
            "note",
            "do_not_email",
            "enable_promotional_sms",
        ],
    ),
    "list_products": (
        "GET",
        "/products",
        [
            ("after", "after", "query"),
            ("page_size", "page_size", "query"),
            ("sku", "sku", "query"),
        ],
        [],
    ),
    "get_product": ("GET", "/products/{id}", [("id", "product_id", "path")], []),
    "list_sales": (
        "GET",
        "/sales",
        [
            ("after", "after", "query"),
            ("before", "before", "query"),
            ("page_size", "page_size", "query"),
        ],
        [],
    ),
    "get_sale": ("GET", "/sales/{id}", [("id", "sale_id", "path")], []),
    "list_product_inventory": (
        "GET",
        "/inventory/{product_id}",
        [
            ("product_id", "product_id", "path"),
            ("after", "after", "query"),
            ("before", "before", "query"),
            ("page_size", "page_size", "query"),
            ("variants", "variants", "query"),
            ("include_deleted", "include_deleted", "query"),
            ("order_direction", "order_direction", "query"),
        ],
        [],
    ),
    "list_outlets": (
        "GET",
        "/outlets",
        [
            ("after", "after", "query"),
            ("before", "before", "query"),
            ("page_size", "page_size", "query"),
            ("deleted", "deleted", "query"),
        ],
        [],
    ),
    "get_outlet": ("GET", "/outlets/{id}", [("id", "outlet_id", "path")], []),
    "list_registers": (
        "GET",
        "/registers",
        [
            ("after", "after", "query"),
            ("before", "before", "query"),
            ("deleted", "deleted", "query"),
            ("page_size", "page_size", "query"),
        ],
        [],
    ),
    "get_register": ("GET", "/registers/{id}", [("id", "register_id", "path")], []),
    "list_brands": (
        "GET",
        "/brands",
        [
            ("after", "after", "query"),
            ("before", "before", "query"),
            ("page_size", "page_size", "query"),
            ("deleted", "deleted", "query"),
        ],
        [],
    ),
    "get_brand": ("GET", "/brands/{brand_id}", [("brand_id", "brand_id", "path")], []),
    "create_brand": ("POST", "/brands", [], ["name", "description"]),
    "update_brand": (
        "PUT",
        "/brands/{brand_id}",
        [("brand_id", "brand_id", "path")],
        ["name", "description"],
    ),
    "list_suppliers": (
        "GET",
        "/suppliers",
        [
            ("after", "after", "query"),
            ("before", "before", "query"),
            ("page_size", "page_size", "query"),
            ("deleted", "deleted", "query"),
        ],
        [],
    ),
    "get_supplier": (
        "GET",
        "/suppliers/{supplier_id}",
        [("supplier_id", "supplier_id", "path")],
        [],
    ),
    "create_supplier": ("POST", "/suppliers", [], ["name", "description"]),
    "list_customer_groups": (
        "GET",
        "/customer_groups",
        [
            ("after", "after", "query"),
            ("before", "before", "query"),
            ("page_size", "page_size", "query"),
            ("deleted", "deleted", "query"),
        ],
        [],
    ),
    "list_taxes": (
        "GET",
        "/taxes",
        [
            ("after", "after", "query"),
            ("before", "before", "query"),
            ("page_size", "page_size", "query"),
        ],
        [],
    ),
}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, dict):
        return {_redact(k, token): _redact(v, token) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    return value


class LightspeedNode(WorkflowNode):
    integration_type = "automation-lightspeed"
    scope_registry = LIGHTSPEED_SCOPES
    connection_evidence = ConnectionEvidence(
        noun="outlets", operation="list_outlets", identity_operation="get_retailer"
    )

    @classmethod
    def get_config_model(cls):
        return LightspeedConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect your Lightspeed store and API token")
        config = self.config.config
        credential = self.config.credentials
        method, path, fields, body_fields = ROUTES[config.operation]
        params = {}
        for wire, field, location in fields:
            value = getattr(config, field)
            if location == "path":
                path = path.replace("{" + wire + "}", quote(value, safe=""))
            elif value is not None:
                params[wire] = value
        body = {
            field: getattr(config, field)
            for field in body_fields
            if getattr(config, field) is not None
        }
        if config.operation == "create_supplier":
            contact = {
                key: value
                for key, value in (
                    ("email", config.contact_email),
                    ("phone", config.contact_phone),
                )
                if value is not None
            }
            body["contact"] = contact or None
        url = (
            f"https://{credential.domain_prefix}.retail.lightspeed.app/api/2026-10"
            + path
        )
        headers = {
            "Authorization": "Bearer " + credential.api_token,
            "Accept": "application/json",
        }
        try:
            async with guarded_async_client(
                timeout=30.0, follow_redirects=False, trust_env=False
            ) as client:
                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    **({"json": body} if body_fields else {}),
                )
            if not 200 <= response.status_code < 300:
                # Preserve provider rejection text for the manual-connect verdict.
                return {
                    "status": "error",
                    "error": _redact(response.text[:2000], credential.api_token),
                    "status_code": response.status_code,
                }
            media = (
                response.headers.get("content-type", "")
                .split(";", 1)[0]
                .strip()
                .lower()
            )
            if media != "application/json":
                raise ValueError("Lightspeed returned an unexpected content type")
            payload = response.json()
            if not isinstance(payload, (dict, list)):
                raise ValueError("Lightspeed returned an unexpected JSON shape")
            if isinstance(payload, dict) and (
                payload.get("error") or payload.get("errors")
            ):
                return {
                    "status": "error",
                    "error": _redact(payload, credential.api_token),
                    "status_code": response.status_code,
                }
            # Inventory is a bare array; other endpoints retain their envelope and version cursor.
            output = {"data": payload} if isinstance(payload, list) else payload
            return {
                **_redact(output, credential.api_token),
                "status": "success",
                "action": config.operation,
            }
        except httpx.RequestError:
            return {
                "status": "error",
                "error": "Lightspeed request did not complete. Inspect the store before retrying a write.",
            }
