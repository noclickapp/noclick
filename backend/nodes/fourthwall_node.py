"""Fourthwall shop Platform API: one documented HTTP operation per action.

Shop API users use Basic authentication as documented at
https://docs.fourthwall.com/guides/authentication. Lists return one provider page;
page, size and all provider pagination metadata remain available to workflows.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.fourthwall.com"


class FourthwallAPICredential(BaseModel):
    model_config = ConfigDict(
        title="Fourthwall API User",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://my-shop.fourthwall.com/admin/dashboard/settings/for-developers",
            "x-credential-instructions": "As a Fourthwall Super Admin, open Settings → For developers → Open API → Create API User. Paste the generated username and password. These shop credentials grant full API access to your shop.",
        },
    )
    credential_type: Literal["fourthwall_api"] = Field(
        "fourthwall_api", json_schema_extra={"ui:hidden": True}
    )
    username: str = Field(..., min_length=1, title="API username")
    password: str = Field(
        ...,
        min_length=1,
        title="API password",
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("username", "password", mode="before")
    @classmethod
    def valid_secret(cls, value, info):
        value = clean_secret(value, field_name=info.field_name)
        if any(ord(c) < 32 or ord(c) == 127 for c in value) or (
            info.field_name == "username" and ":" in value
        ):
            raise ValueError(
                "Paste the API credential without controls or a Basic header"
            )
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class FourthwallGetCurrentShopConfig(_Input):
    """Get current shop."""

    operation: Literal["get_current_shop"] = Field(
        "get_current_shop", json_schema_extra={"ui:hidden": True}
    )


class FourthwallListOrdersConfig(_Input):
    """Get all orders."""

    operation: Literal["list_orders"] = Field(
        "list_orders", json_schema_extra={"ui:hidden": True}
    )
    page: int = Field(0, ge=0)
    size: int = Field(20, ge=1, le=100)
    email: str | None = Field(None)
    createdAt_gt: datetime | None = Field(None)
    createdAt_lt: datetime | None = Field(None)
    updatedAt_gt: datetime | None = Field(None)
    updatedAt_lt: datetime | None = Field(None)
    status: list[
        Literal[
            "CONFIRMED",
            "PARTIALLY_IN_PRODUCTION",
            "IN_PRODUCTION",
            "PARTIALLY_SHIPPED",
            "SHIPPED",
            "PARTIALLY_DELIVERED",
            "DELIVERED",
            "CANCELLED",
            "COMPLETED",
        ]
    ] | None = Field(None)


class FourthwallGetOrderConfig(_Input):
    """Get order by id."""

    operation: Literal["get_order"] = Field(
        "get_order", json_schema_extra={"ui:hidden": True}
    )
    orderId: str = Field(..., min_length=1)

    @field_validator("orderId")
    @classmethod
    def resource_id(cls, value):
        if value in {".", ".."} or any(ord(c) < 32 for c in value) or len(value) > 512:
            raise ValueError("Use a Fourthwall resource ID or collection slug")
        return value


class FourthwallGetOrderByFriendlyIdConfig(_Input):
    """Get order by friendly id."""

    operation: Literal["get_order_by_friendly_id"] = Field(
        "get_order_by_friendly_id", json_schema_extra={"ui:hidden": True}
    )
    friendlyId: str = Field(..., min_length=1)

    @field_validator("friendlyId")
    @classmethod
    def resource_id(cls, value):
        if value in {".", ".."} or any(ord(c) < 32 for c in value) or len(value) > 512:
            raise ValueError("Use a Fourthwall resource ID or collection slug")
        return value


class FourthwallListProductsConfig(_Input):
    """Get all products (offers)."""

    operation: Literal["list_products"] = Field(
        "list_products", json_schema_extra={"ui:hidden": True}
    )
    page: int = Field(0, ge=0)
    size: int = Field(20, ge=1, le=100)
    search: str | None = Field(None)


class FourthwallGetProductConfig(_Input):
    """Get product (offer) by id."""

    operation: Literal["get_product"] = Field(
        "get_product", json_schema_extra={"ui:hidden": True}
    )
    productId: str = Field(..., min_length=1)

    @field_validator("productId")
    @classmethod
    def resource_id(cls, value):
        if value in {".", ".."} or any(ord(c) < 32 for c in value) or len(value) > 512:
            raise ValueError("Use a Fourthwall resource ID or collection slug")
        return value


class FourthwallGetProductInventoryConfig(_Input):
    """Get product (offer) inventory by id."""

    operation: Literal["get_product_inventory"] = Field(
        "get_product_inventory", json_schema_extra={"ui:hidden": True}
    )
    productId: str = Field(..., min_length=1)

    @field_validator("productId")
    @classmethod
    def resource_id(cls, value):
        if value in {".", ".."} or any(ord(c) < 32 for c in value) or len(value) > 512:
            raise ValueError("Use a Fourthwall resource ID or collection slug")
        return value


class FourthwallUpdateProductStateConfig(_Input):
    """Update product (offer) lifecycle state."""

    operation: Literal["update_product_state"] = Field(
        "update_product_state", json_schema_extra={"ui:hidden": True}
    )
    productId: str = Field(..., min_length=1)
    state: Literal["PUBLIC", "HIDDEN"] = Field(
        ...,
        min_length=1,
        description="Target lifecycle state. `PUBLIC` makes the product visible on the storefront; `HIDDEN` keeps it unlisted. The sold-out (`available`) flag is preserved across the transition — use `PUT /products/{productId}/availability` to flip it.",
    )

    @field_validator("productId")
    @classmethod
    def resource_id(cls, value):
        if value in {".", ".."} or any(ord(c) < 32 for c in value) or len(value) > 512:
            raise ValueError("Use a Fourthwall resource ID or collection slug")
        return value


class FourthwallUpdateProductAvailabilityConfig(_Input):
    """Update product (offer) availability by id."""

    operation: Literal["update_product_availability"] = Field(
        "update_product_availability", json_schema_extra={"ui:hidden": True}
    )
    productId: str = Field(..., min_length=1)
    available: bool = Field(...)

    @field_validator("productId")
    @classmethod
    def resource_id(cls, value):
        if value in {".", ".."} or any(ord(c) < 32 for c in value) or len(value) > 512:
            raise ValueError("Use a Fourthwall resource ID or collection slug")
        return value


class FourthwallArchiveProductConfig(_Input):
    """Archive a product (offer)."""

    operation: Literal["archive_product"] = Field(
        "archive_product", json_schema_extra={"ui:hidden": True}
    )
    productId: str = Field(..., min_length=1)

    @field_validator("productId")
    @classmethod
    def resource_id(cls, value):
        if value in {".", ".."} or any(ord(c) < 32 for c in value) or len(value) > 512:
            raise ValueError("Use a Fourthwall resource ID or collection slug")
        return value


class FourthwallListCollectionsConfig(_Input):
    """Get all collections."""

    operation: Literal["list_collections"] = Field(
        "list_collections", json_schema_extra={"ui:hidden": True}
    )
    page: int = Field(0, ge=0)
    size: int = Field(20, ge=1, le=100)
    search: str | None = Field(None)


class FourthwallGetCollectionConfig(_Input):
    """Get collection by ID or slug."""

    operation: Literal["get_collection"] = Field(
        "get_collection", json_schema_extra={"ui:hidden": True}
    )
    collectionIdOrSlug: str = Field(..., min_length=1)

    @field_validator("collectionIdOrSlug")
    @classmethod
    def resource_id(cls, value):
        if value in {".", ".."} or any(ord(c) < 32 for c in value) or len(value) > 512:
            raise ValueError("Use a Fourthwall resource ID or collection slug")
        return value


class FourthwallCreateCollectionConfig(_Input):
    """Create a new collection."""

    operation: Literal["create_collection"] = Field(
        "create_collection", json_schema_extra={"ui:hidden": True}
    )
    name: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    offerIds: list[UUID] = Field(
        ...,
        description="Full list of product UUIDs. Replaces the collection contents; an empty list clears it.",
    )


class FourthwallUpdateCollectionConfig(_Input):
    """Update a collection."""

    operation: Literal["update_collection"] = Field(
        "update_collection", json_schema_extra={"ui:hidden": True}
    )
    collectionId: str = Field(..., min_length=1)
    name: str | None = Field(None)
    description: str | None = Field(None)
    offerIds: list[UUID] | None = Field(
        None,
        description="Full list of product UUIDs. Replaces the collection contents; an empty list clears it.",
    )

    @field_validator("collectionId")
    @classmethod
    def resource_id(cls, value):
        if value in {".", ".."} or any(ord(c) < 32 for c in value) or len(value) > 512:
            raise ValueError("Use a Fourthwall resource ID or collection slug")
        return value


class FourthwallGetCollectionProductsConfig(_Input):
    """Get products in a collection."""

    operation: Literal["get_collection_products"] = Field(
        "get_collection_products", json_schema_extra={"ui:hidden": True}
    )
    collectionId: str = Field(..., min_length=1)
    page: int = Field(0, ge=0)
    size: int = Field(20, ge=1, le=100)
    status: Literal[
        "PUBLIC", "AVAILABLE", "SOLD_OUT", "HIDDEN", "ARCHIVED"
    ] | None = Field(None, description="Filter for product status in a collection")

    @field_validator("collectionId")
    @classmethod
    def resource_id(cls, value):
        if value in {".", ".."} or any(ord(c) < 32 for c in value) or len(value) > 512:
            raise ValueError("Use a Fourthwall resource ID or collection slug")
        return value


class FourthwallUpdateCollectionProductsConfig(_Input):
    """Set collection products."""

    operation: Literal["update_collection_products"] = Field(
        "update_collection_products", json_schema_extra={"ui:hidden": True}
    )
    collectionId: str = Field(..., min_length=1)
    offerIds: list[UUID] = Field(
        ...,
        description="Full list of product UUIDs. Replaces the collection contents; an empty list clears it.",
    )

    @field_validator("collectionId")
    @classmethod
    def resource_id(cls, value):
        if value in {".", ".."} or any(ord(c) < 32 for c in value) or len(value) > 512:
            raise ValueError("Use a Fourthwall resource ID or collection slug")
        return value


class FourthwallUpdateCollectionAvailabilityConfig(_Input):
    """Update collection availability."""

    operation: Literal["update_collection_availability"] = Field(
        "update_collection_availability", json_schema_extra={"ui:hidden": True}
    )
    collectionId: str = Field(..., min_length=1)
    available: bool = Field(...)

    @field_validator("collectionId")
    @classmethod
    def resource_id(cls, value):
        if value in {".", ".."} or any(ord(c) < 32 for c in value) or len(value) > 512:
            raise ValueError("Use a Fourthwall resource ID or collection slug")
        return value


class FourthwallListPromotionsConfig(_Input):
    """Get all promotions."""

    operation: Literal["list_promotions"] = Field(
        "list_promotions", json_schema_extra={"ui:hidden": True}
    )
    page: int = Field(0, ge=0)
    size: int = Field(20, ge=1, le=100)
    codes: list[str] | None = Field(None)


class FourthwallGetPromotionConfig(_Input):
    """Get a promotion by id."""

    operation: Literal["get_promotion"] = Field(
        "get_promotion", json_schema_extra={"ui:hidden": True}
    )
    promotionId: str = Field(..., min_length=1)

    @field_validator("promotionId")
    @classmethod
    def resource_id(cls, value):
        if value in {".", ".."} or any(ord(c) < 32 for c in value) or len(value) > 512:
            raise ValueError("Use a Fourthwall resource ID or collection slug")
        return value


class FourthwallListEntriesConfig(_Input):
    """Get all mailing list entries."""

    operation: Literal["list_entries"] = Field(
        "list_entries", json_schema_extra={"ui:hidden": True}
    )
    page: int = Field(0, ge=0)
    size: int = Field(20, ge=1, le=100)


class FourthwallListDonationsConfig(_Input):
    """Get all donations."""

    operation: Literal["list_donations"] = Field(
        "list_donations", json_schema_extra={"ui:hidden": True}
    )
    page: int = Field(0, ge=0)
    size: int = Field(20, ge=1, le=100)


class FourthwallGetDonationConfig(_Input):
    """Get donation by id."""

    operation: Literal["get_donation"] = Field(
        "get_donation", json_schema_extra={"ui:hidden": True}
    )
    donationId: str = Field(..., min_length=1)

    @field_validator("donationId")
    @classmethod
    def resource_id(cls, value):
        if value in {".", ".."} or any(ord(c) < 32 for c in value) or len(value) > 512:
            raise ValueError("Use a Fourthwall resource ID or collection slug")
        return value


class FourthwallListMembersConfig(_Input):
    """List members."""

    operation: Literal["list_members"] = Field(
        "list_members", json_schema_extra={"ui:hidden": True}
    )
    page: int = Field(0, ge=0)
    size: int = Field(20, ge=1, le=100)


class FourthwallGetMemberConfig(_Input):
    """Get member."""

    operation: Literal["get_member"] = Field(
        "get_member", json_schema_extra={"ui:hidden": True}
    )
    id: str = Field(..., min_length=1)

    @field_validator("id")
    @classmethod
    def resource_id(cls, value):
        if value in {".", ".."} or any(ord(c) < 32 for c in value) or len(value) > 512:
            raise ValueError("Use a Fourthwall resource ID or collection slug")
        return value


class FourthwallListTiersConfig(_Input):
    """List membership tiers."""

    operation: Literal["list_tiers"] = Field(
        "list_tiers", json_schema_extra={"ui:hidden": True}
    )


FourthwallConfig = Annotated[
    Union[
        FourthwallGetCurrentShopConfig,
        FourthwallListOrdersConfig,
        FourthwallGetOrderConfig,
        FourthwallGetOrderByFriendlyIdConfig,
        FourthwallListProductsConfig,
        FourthwallGetProductConfig,
        FourthwallGetProductInventoryConfig,
        FourthwallUpdateProductStateConfig,
        FourthwallUpdateProductAvailabilityConfig,
        FourthwallArchiveProductConfig,
        FourthwallListCollectionsConfig,
        FourthwallGetCollectionConfig,
        FourthwallCreateCollectionConfig,
        FourthwallUpdateCollectionConfig,
        FourthwallGetCollectionProductsConfig,
        FourthwallUpdateCollectionProductsConfig,
        FourthwallUpdateCollectionAvailabilityConfig,
        FourthwallListPromotionsConfig,
        FourthwallGetPromotionConfig,
        FourthwallListEntriesConfig,
        FourthwallListDonationsConfig,
        FourthwallGetDonationConfig,
        FourthwallListMembersConfig,
        FourthwallGetMemberConfig,
        FourthwallListTiersConfig,
    ],
    Field(discriminator="operation"),
]


class FourthwallFullConfig(NodeConfig[FourthwallConfig, FourthwallAPICredential]):
    pass


ROUTES = {
    "get_current_shop": {
        "method": "GET",
        "path": "/open-api/v1.0/shops/current",
        "path_fields": {},
        "query_fields": {},
        "body_fields": [],
        "expected": 200,
    },
    "list_orders": {
        "method": "GET",
        "path": "/open-api/v1.0/order",
        "path_fields": {},
        "query_fields": {
            "page": "page",
            "size": "size",
            "email": "email",
            "createdAt_gt": "createdAt[gt]",
            "createdAt_lt": "createdAt[lt]",
            "updatedAt_gt": "updatedAt[gt]",
            "updatedAt_lt": "updatedAt[lt]",
            "status": "status",
        },
        "body_fields": [],
        "expected": 200,
    },
    "get_order": {
        "method": "GET",
        "path": "/open-api/v1.0/order/{orderId}",
        "path_fields": {"orderId": "orderId"},
        "query_fields": {},
        "body_fields": [],
        "expected": 200,
    },
    "get_order_by_friendly_id": {
        "method": "GET",
        "path": "/open-api/v1.0/order/by-friendly-id/{friendlyId}",
        "path_fields": {"friendlyId": "friendlyId"},
        "query_fields": {},
        "body_fields": [],
        "expected": 200,
    },
    "list_products": {
        "method": "GET",
        "path": "/open-api/v1.0/products",
        "path_fields": {},
        "query_fields": {"page": "page", "size": "size", "search": "search"},
        "body_fields": [],
        "expected": 200,
    },
    "get_product": {
        "method": "GET",
        "path": "/open-api/v1.0/products/{productId}",
        "path_fields": {"productId": "productId"},
        "query_fields": {},
        "body_fields": [],
        "expected": 200,
    },
    "get_product_inventory": {
        "method": "GET",
        "path": "/open-api/v1.0/products/{productId}/inventory",
        "path_fields": {"productId": "productId"},
        "query_fields": {},
        "body_fields": [],
        "expected": 200,
    },
    "update_product_state": {
        "method": "PUT",
        "path": "/open-api/v1.0/products/{productId}/state",
        "path_fields": {"productId": "productId"},
        "query_fields": {},
        "body_fields": ["state"],
        "expected": 200,
    },
    "update_product_availability": {
        "method": "PUT",
        "path": "/open-api/v1.0/products/{productId}/availability",
        "path_fields": {"productId": "productId"},
        "query_fields": {},
        "body_fields": ["available"],
        "expected": 200,
    },
    "archive_product": {
        "method": "DELETE",
        "path": "/open-api/v1.0/products/{productId}",
        "path_fields": {"productId": "productId"},
        "query_fields": {},
        "body_fields": [],
        "expected": 204,
    },
    "list_collections": {
        "method": "GET",
        "path": "/open-api/v1.0/collections",
        "path_fields": {},
        "query_fields": {"page": "page", "size": "size", "search": "search"},
        "body_fields": [],
        "expected": 200,
    },
    "get_collection": {
        "method": "GET",
        "path": "/open-api/v1.0/collections/{collectionIdOrSlug}",
        "path_fields": {"collectionIdOrSlug": "collectionIdOrSlug"},
        "query_fields": {},
        "body_fields": [],
        "expected": 200,
    },
    "create_collection": {
        "method": "POST",
        "path": "/open-api/v1.0/collections",
        "path_fields": {},
        "query_fields": {},
        "body_fields": ["name", "description", "offerIds"],
        "expected": 200,
    },
    "update_collection": {
        "method": "PUT",
        "path": "/open-api/v1.0/collections/{collectionId}",
        "path_fields": {"collectionId": "collectionId"},
        "query_fields": {},
        "body_fields": ["name", "description", "offerIds"],
        "expected": 200,
    },
    "get_collection_products": {
        "method": "GET",
        "path": "/open-api/v1.0/collections/{collectionId}/products",
        "path_fields": {"collectionId": "collectionId"},
        "query_fields": {"page": "page", "size": "size", "status": "status"},
        "body_fields": [],
        "expected": 200,
    },
    "update_collection_products": {
        "method": "PUT",
        "path": "/open-api/v1.0/collections/{collectionId}/products",
        "path_fields": {"collectionId": "collectionId"},
        "query_fields": {},
        "body_fields": ["offerIds"],
        "expected": 200,
    },
    "update_collection_availability": {
        "method": "PUT",
        "path": "/open-api/v1.0/collections/{collectionId}/availability",
        "path_fields": {"collectionId": "collectionId"},
        "query_fields": {},
        "body_fields": ["available"],
        "expected": 200,
    },
    "list_promotions": {
        "method": "GET",
        "path": "/open-api/v1.0/promotions",
        "path_fields": {},
        "query_fields": {"page": "page", "size": "size", "codes": "codes"},
        "body_fields": [],
        "expected": 200,
    },
    "get_promotion": {
        "method": "GET",
        "path": "/open-api/v1.0/promotions/{promotionId}",
        "path_fields": {"promotionId": "promotionId"},
        "query_fields": {},
        "body_fields": [],
        "expected": 200,
    },
    "list_entries": {
        "method": "GET",
        "path": "/open-api/v1.0/mailing-list-entries",
        "path_fields": {},
        "query_fields": {"page": "page", "size": "size"},
        "body_fields": [],
        "expected": 200,
    },
    "list_donations": {
        "method": "GET",
        "path": "/open-api/v1.0/donations",
        "path_fields": {},
        "query_fields": {"page": "page", "size": "size"},
        "body_fields": [],
        "expected": 200,
    },
    "get_donation": {
        "method": "GET",
        "path": "/open-api/v1.0/donations/{donationId}",
        "path_fields": {"donationId": "donationId"},
        "query_fields": {},
        "body_fields": [],
        "expected": 200,
    },
    "list_members": {
        "method": "GET",
        "path": "/open-api/v1.0/memberships/members",
        "path_fields": {},
        "query_fields": {"page": "page", "size": "size"},
        "body_fields": [],
        "expected": 200,
    },
    "get_member": {
        "method": "GET",
        "path": "/open-api/v1.0/memberships/members/{id}",
        "path_fields": {"id": "id"},
        "query_fields": {},
        "body_fields": [],
        "expected": 200,
    },
    "list_tiers": {
        "method": "GET",
        "path": "/open-api/v1.0/memberships/tiers",
        "path_fields": {},
        "query_fields": {},
        "body_fields": [],
        "expected": 200,
    },
}


class FourthwallNode(WorkflowNode):
    integration_type = "automation-fourthwall"
    connection_evidence = ConnectionEvidence(
        noun="shop", identity_operation="get_current_shop"
    )

    @classmethod
    def get_config_model(cls):
        return FourthwallFullConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect Fourthwall API credentials")
        config = self.config.config
        route = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True)
        path = route["path"]
        for field, parameter in route["path_fields"].items():
            path = path.replace("{" + parameter + "}", quote(values[field], safe=""))
        params = {
            wire: values[field]
            for field, wire in route["query_fields"].items()
            if field in values
        }
        body = {
            field: values[field] for field in route["body_fields"] if field in values
        }
        kwargs = {"params": params}
        if route["body_fields"]:
            kwargs["json"] = body
        try:
            async with guarded_async_client(
                timeout=30, follow_redirects=False, trust_env=False
            ) as client:
                response = await client.request(
                    route["method"],
                    BASE_URL + path,
                    auth=httpx.BasicAuth(credential.username, credential.password),
                    headers={"Accept": "application/json"},
                    **kwargs,
                )
            if response.status_code != route["expected"]:
                # Preserve the provider's rejection text for the shared connect verdict.
                message = response.text[:2000]
                for secret in (credential.username, credential.password):
                    message = message.replace(secret, "[redacted]")
                return {
                    "status": "error",
                    "status_code": response.status_code,
                    "error": message or "Fourthwall request failed",
                }
            if response.status_code == 204:
                return {"status": "success", "data": None, "status_code": 204}
            payload = response.json()
            if not isinstance(payload, (dict, list)):
                raise ValueError("Expected a Fourthwall JSON object or array")
            if isinstance(payload, dict) and (
                payload.get("error") or payload.get("errors")
            ):
                raise ValueError("Fourthwall returned an error envelope")
            return {"status": "success", "data": payload}
        except httpx.RequestError:
            return {"status": "error", "error": "Fourthwall request could not complete"}
