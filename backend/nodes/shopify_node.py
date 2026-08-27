"""
Shopify Admin REST API automation node.

Provides workflow integration with Shopify for e-commerce operations including:
- Product Operations: list, get, create, update, delete, count products
- Order Operations: list, get, create, update, delete, cancel, close, open, count orders
- Customer Operations: list, get, create, update, delete, search, count customers, get orders
- Inventory Operations: list, adjust, set, connect, delete inventory levels
- Fulfillment Operations: list, get, create, update, complete, cancel fulfillments
- Collection Operations: list, get, create, update, delete collections, add products
- Location Operations: list, get locations
- Shop Operations: get shop information
- Metafield Operations: list, get, create, update, delete metafields
- Webhook Operations: list, get, create, update, delete webhooks
- Price Rule/Discount Operations: manage price rules and discount codes
- Gift Card Operations: list, get, create, update, disable gift cards

Authentication: Access Token (from custom app in Shopify admin)
API Base URL: https://{store}.myshopify.com/admin/api/2024-01
Documentation: https://shopify.dev/docs/api/admin-rest
Rate Limit: 40 requests per minute (2/sec replenishment), 10x for Plus stores
"""

import logging
import os
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, ConfigDict, Field, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin
from nodes.scopes.shopify import SHOPIFY_SCOPES
from utils.ssrf import normalize_provider_subdomain
from utils.webhook_signatures import verify_hmac_sha256_base64

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

SHOPIFY_API_VERSION = os.environ.get("SHOPIFY_API_VERSION", "2025-01")


# ============================================================================
# Webhook trigger helpers
# ============================================================================


def _shopify_api_base(store_name: str) -> str:
    """Admin API base URL for a store."""
    store = normalize_provider_subdomain(
        store_name, "myshopify.com", field_name="Shopify store name"
    )
    return f"https://{store}.myshopify.com/admin/api/{SHOPIFY_API_VERSION}"


async def register_shopify_webhook(
    store_name: str, access_token: str, topic: str, webhook_url: str
) -> int:
    """Create a Shopify webhook subscription and return its numeric id."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{_shopify_api_base(store_name)}/webhooks.json",
            headers={
                "X-Shopify-Access-Token": access_token,
                "Content-Type": "application/json",
            },
            json={
                "webhook": {"topic": topic, "address": webhook_url, "format": "json"}
            },
        )
        response.raise_for_status()
        return response.json()["webhook"]["id"]


async def unregister_shopify_webhook(
    store_name: str, access_token: str, webhook_id: int
) -> None:
    """Delete a Shopify webhook. A missing webhook (404) is treated as done."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.delete(
            f"{_shopify_api_base(store_name)}/webhooks/{webhook_id}.json",
            headers={"X-Shopify-Access-Token": access_token},
        )
        if response.status_code not in (200, 204, 404):
            response.raise_for_status()


# ============================================================================
# Credential Schema
# ============================================================================


class ShopifyOAuthCredential(BaseModel):
    """
    OAuth 2.0 credential for Shopify Admin API. Tokens are obtained via OAuth flow.

    OAuth app setup: https://shopify.dev/docs/apps/build/authentication-authorization
    """

    credential_type: Literal["shopify_oauth"] = Field(
        "shopify_oauth", json_schema_extra={"ui:hidden": True}
    )
    store_name: str = Field(
        ...,
        title="Store Name",
        description="Your Shopify store name (the part before .myshopify.com)",
    )
    access_token: str = Field(..., title="Access Token")
    refresh_token: Optional[str] = Field(None, title="Refresh Token")
    expires_at: Optional[str] = Field(
        None, title="Token Expiry"
    )  # ISO 8601 (if using expiring tokens)
    shop_owner: Optional[str] = Field(None, title="Shop Owner")
    email: Optional[str] = Field(None, title="Account Email")
    api_secret_key: Optional[str] = Field(
        None,
        title="API Secret Key",
        description="App API secret key — required to verify webhook trigger signatures",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "shopify",
            "x-oauth-supports-custom-client": True,  # Allow users to bring their own OAuth app
            "x-oauth-redirect-uri": "/api/auth/shopify/callback",
            "x-oauth-custom-client-help": "Add the redirect URI above in your Shopify app settings at: https://partners.shopify.com/organizations/YOUR_ORG_ID/apps/YOUR_APP_ID/edit",
            "x-oauth-scopes": [
                "read_products",
                "write_products",
                "read_orders",
                "write_orders",
                "read_customers",
                "write_customers",
                "read_inventory",
                "write_inventory",
                "read_fulfillments",
                "write_fulfillments",
                "read_shipping",
                "write_shipping",
                "read_locations",
                "read_merchant_managed_fulfillment_orders",
                "write_merchant_managed_fulfillment_orders",
                "read_assigned_fulfillment_orders",
                "write_assigned_fulfillment_orders",
                "read_third_party_fulfillment_orders",
                "write_third_party_fulfillment_orders",
                "read_content",
                "write_content",
            ],
        }
    )


class ShopifyAccessTokenCredential(BaseModel):
    """
    Access Token credential for Shopify Admin API.

    Only for custom apps created in the store admin before January 2026 —
    Shopify no longer issues permanent Admin API tokens for new apps. New
    stores should use the OAuth method (optionally with their own app).
    """

    credential_type: Literal["shopify_access_token"] = Field(
        "shopify_access_token", json_schema_extra={"ui:hidden": True}
    )
    store_name: str = Field(
        ...,
        title="Store Name",
        description="Your Shopify store name (the part before .myshopify.com)",
    )
    access_token: str = Field(
        ...,
        title="Access Token",
        description="Admin API access token from your custom app",
        json_schema_extra={"ui:widget": "password"},
    )
    api_secret_key: Optional[str] = Field(
        None,
        title="API Secret Key",
        description="App API secret key — required to verify webhook trigger signatures",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://admin.shopify.com/store/{your-store}/settings/apps/development"
        }
    )


# Union type - OAuth shown first in UI
ShopifyCredential = Union[ShopifyOAuthCredential, ShopifyAccessTokenCredential]


# ============================================================================
# Product Operation Configs
# ============================================================================


class ShopifyListProductsConfig(BaseModel):
    """List products from the store with pagination and filtering"""

    operation: Literal["list_products"] = Field(
        "list_products",
        json_schema_extra={
            "const": "list_products",
            "ui:hidden": True,
            "x-category": "Product",
            "x-is-trigger": False,
            "x-display-name": "List Products",
            "x-keywords": [
                "browse catalog",
                "all store items",
                "product catalog",
                "paginate products",
                "filter products",
            ],
        },
        title="List Products",
    )
    limit: Optional[int] = Field(
        50,
        title="Limit",
        description="Number of products to return (max 250)",
        ge=1,
        le=250,
    )
    since_id: Optional[str] = Field(
        None,
        title="Since ID",
        description="Return products after this ID for pagination",
    )
    collection_id: Optional[str] = Field(
        None, title="Collection ID", description="Filter products by collection"
    )
    product_type: Optional[str] = Field(
        None, title="Product Type", description="Filter by product type"
    )
    vendor: Optional[str] = Field(
        None, title="Vendor", description="Filter by vendor name"
    )
    status: Optional[str] = Field(
        None,
        title="Status",
        description="Filter by product status",
        json_schema_extra={"enum": ["active", "archived", "draft"]},
    )
    fields: Optional[str] = Field(
        None, title="Fields", description="Comma-separated list of fields to include"
    )


class ShopifyGetProductConfig(BaseModel):
    """Get a single product by ID"""

    operation: Literal["get_product_by_id"] = Field(
        "get_product_by_id",
        json_schema_extra={
            "const": "get_product_by_id",
            "ui:hidden": True,
            "x-category": "Product",
            "x-is-trigger": False,
            "x-display-name": "Get Product by Id",
            "x-keywords": [
                "single product details",
                "one product",
                "product by handle",
                "fetch specific item",
            ],
        },
        title="Get Product by Id",
    )
    product_id: str = Field(
        ..., title="Product ID", description="The ID of the product to retrieve"
    )
    fields: Optional[str] = Field(
        None, title="Fields", description="Comma-separated list of fields to include"
    )


class ShopifyCreateProductConfig(BaseModel):
    """Create a new product"""

    operation: Literal["create_product"] = Field(
        "create_product",
        json_schema_extra={
            "const": "create_product",
            "ui:hidden": True,
            "x-category": "Product",
            "x-is-trigger": False,
            "x-display-name": "Create Product",
            "x-keywords": [
                "add new product",
                "list new item",
                "publish product",
                "add catalog item",
            ],
        },
        title="Create Product",
    )
    title: str = Field(..., title="Title", description="Product title")
    body_html: Optional[str] = Field(
        None,
        title="Description (HTML)",
        description="Product description in HTML format",
        json_schema_extra={"ui:widget": "textarea"},
    )
    vendor: Optional[str] = Field(
        None, title="Vendor", description="Product vendor name"
    )
    product_type: Optional[str] = Field(
        None, title="Product Type", description="Product type/category"
    )
    tags: Optional[str] = Field(
        None, title="Tags", description="Comma-separated list of tags"
    )
    status: Optional[str] = Field(
        "draft",
        title="Status",
        description="Product status",
        json_schema_extra={"enum": ["active", "archived", "draft"]},
    )
    variants: Optional[List[Dict[str, Any]]] = Field(
        None,
        title="Variants",
        description="Product variants array [{price, sku, inventory_quantity, ...}]",
    )
    options: Optional[List[Dict[str, Any]]] = Field(
        None,
        title="Options",
        description="Product options array [{name, values: [...]}]",
    )
    images: Optional[List[Dict[str, Any]]] = Field(
        None, title="Images", description="Product images array [{src, alt, ...}]"
    )


class ShopifyUpdateProductConfig(BaseModel):
    """Update an existing product"""

    operation: Literal["update_product"] = Field(
        "update_product",
        json_schema_extra={
            "const": "update_product",
            "ui:hidden": True,
            "x-category": "Product",
            "x-is-trigger": False,
            "x-display-name": "Update Product",
            "x-keywords": [
                "edit product details",
                "change product price",
                "modify item",
                "edit listing",
            ],
        },
        title="Update Product",
    )
    product_id: str = Field(
        ..., title="Product ID", description="The ID of the product to update"
    )
    title: Optional[str] = Field(None, title="Title", description="Product title")
    body_html: Optional[str] = Field(
        None,
        title="Description (HTML)",
        description="Product description in HTML format",
        json_schema_extra={"ui:widget": "textarea"},
    )
    vendor: Optional[str] = Field(
        None, title="Vendor", description="Product vendor name"
    )
    product_type: Optional[str] = Field(
        None, title="Product Type", description="Product type/category"
    )
    tags: Optional[str] = Field(
        None, title="Tags", description="Comma-separated list of tags"
    )
    status: Optional[str] = Field(
        None,
        title="Status",
        description="Product status",
        json_schema_extra={"enum": ["active", "archived", "draft"]},
    )


class ShopifyDeleteProductConfig(BaseModel):
    """Delete a product"""

    operation: Literal["delete_product"] = Field(
        "delete_product",
        json_schema_extra={
            "const": "delete_product",
            "ui:hidden": True,
            "x-category": "Product",
            "x-is-trigger": False,
            "x-display-name": "Delete Product",
            "x-keywords": [
                "remove product",
                "unlist item",
                "delete catalog entry",
                "remove listing",
            ],
        },
        title="Delete Product",
    )
    product_id: str = Field(
        ..., title="Product ID", description="The ID of the product to delete"
    )


class ShopifyCountProductsConfig(BaseModel):
    """Get the count of products"""

    operation: Literal["count_products"] = Field(
        "count_products",
        json_schema_extra={
            "const": "count_products",
            "ui:hidden": True,
            "x-category": "Product",
            "x-is-trigger": False,
            "x-display-name": "Count Products",
            "x-keywords": [
                "how many products",
                "total products",
                "product total",
                "number of items",
            ],
        },
        title="Count Products",
    )
    collection_id: Optional[str] = Field(
        None,
        title="Collection ID",
        description="Count products in a specific collection",
    )
    product_type: Optional[str] = Field(
        None, title="Product Type", description="Count products of a specific type"
    )
    vendor: Optional[str] = Field(
        None, title="Vendor", description="Count products from a specific vendor"
    )


# ============================================================================
# Product Variant Operation Configs
# ============================================================================


class ShopifyListProductVariantsConfig(BaseModel):
    """List all variants for a product"""

    operation: Literal["list_product_variants"] = Field(
        "list_product_variants",
        json_schema_extra={
            "const": "list_product_variants",
            "ui:hidden": True,
            "x-category": "Product",
            "x-is-trigger": False,
            "x-display-name": "List Product Variants",
            "x-keywords": [
                "browse variants",
                "product options",
                "size color variants",
                "sku variants",
            ],
        },
        title="List Product Variants",
    )
    product_id: str = Field(
        ..., title="Product ID", description="The ID of the product"
    )
    limit: Optional[int] = Field(
        50,
        title="Limit",
        description="Number of variants to return (max 250)",
        ge=1,
        le=250,
    )
    since_id: Optional[str] = Field(
        None,
        title="Since ID",
        description="Return variants after this ID for pagination",
    )
    fields: Optional[str] = Field(
        None, title="Fields", description="Comma-separated list of fields to include"
    )


class ShopifyGetProductVariantConfig(BaseModel):
    """Get a single product variant by ID"""

    operation: Literal["get_product_variant_by_id"] = Field(
        "get_product_variant_by_id",
        json_schema_extra={
            "const": "get_product_variant_by_id",
            "ui:hidden": True,
            "x-category": "Product",
            "x-is-trigger": False,
            "x-display-name": "Get Product Variant by Id",
            "x-keywords": [
                "single variant details",
                "one variant",
                "specific sku",
                "variant by id",
            ],
        },
        title="Get Product Variant by Id",
    )
    variant_id: str = Field(
        ..., title="Variant ID", description="The ID of the variant to retrieve"
    )
    fields: Optional[str] = Field(
        None, title="Fields", description="Comma-separated list of fields to include"
    )


class ShopifyCreateProductVariantConfig(BaseModel):
    """Create a new product variant"""

    operation: Literal["create_product_variant"] = Field(
        "create_product_variant",
        json_schema_extra={
            "const": "create_product_variant",
            "ui:hidden": True,
            "x-category": "Product",
            "x-is-trigger": False,
            "x-display-name": "Create Product Variant",
            "x-keywords": [
                "add variant",
                "new size option",
                "add sku",
                "new product option",
            ],
        },
        title="Create Product Variant",
    )
    product_id: str = Field(
        ..., title="Product ID", description="The ID of the product"
    )
    option1: Optional[str] = Field(
        None,
        title="Option 1",
        description="First option value (e.g., 'Small' for Size)",
    )
    option2: Optional[str] = Field(
        None,
        title="Option 2",
        description="Second option value (e.g., 'Red' for Color)",
    )
    option3: Optional[str] = Field(
        None, title="Option 3", description="Third option value"
    )
    price: Optional[str] = Field(None, title="Price", description="Variant price")
    sku: Optional[str] = Field(
        None, title="SKU", description="Stock keeping unit identifier"
    )
    inventory_quantity: Optional[int] = Field(
        None, title="Inventory Quantity", description="Inventory quantity"
    )
    barcode: Optional[str] = Field(
        None, title="Barcode", description="Barcode, UPC, or ISBN number"
    )
    weight: Optional[float] = Field(
        None, title="Weight", description="Weight of the variant"
    )
    weight_unit: Optional[str] = Field(
        None,
        title="Weight Unit",
        description="Unit of measurement for weight",
        json_schema_extra={"enum": ["g", "kg", "oz", "lb"]},
    )


class ShopifyUpdateProductVariantConfig(BaseModel):
    """Update an existing product variant"""

    operation: Literal["update_product_variant"] = Field(
        "update_product_variant",
        json_schema_extra={
            "const": "update_product_variant",
            "ui:hidden": True,
            "x-category": "Product",
            "x-is-trigger": False,
            "x-display-name": "Update Product Variant",
            "x-keywords": [
                "edit variant",
                "change variant price",
                "modify sku",
                "update option",
            ],
        },
        title="Update Product Variant",
    )
    variant_id: str = Field(
        ..., title="Variant ID", description="The ID of the variant to update"
    )
    option1: Optional[str] = Field(
        None, title="Option 1", description="First option value"
    )
    option2: Optional[str] = Field(
        None, title="Option 2", description="Second option value"
    )
    option3: Optional[str] = Field(
        None, title="Option 3", description="Third option value"
    )
    price: Optional[str] = Field(None, title="Price", description="Variant price")
    sku: Optional[str] = Field(
        None, title="SKU", description="Stock keeping unit identifier"
    )
    inventory_quantity: Optional[int] = Field(
        None, title="Inventory Quantity", description="Inventory quantity"
    )
    barcode: Optional[str] = Field(
        None, title="Barcode", description="Barcode, UPC, or ISBN number"
    )
    weight: Optional[float] = Field(
        None, title="Weight", description="Weight of the variant"
    )


class ShopifyDeleteProductVariantConfig(BaseModel):
    """Delete a product variant"""

    operation: Literal["delete_product_variant"] = Field(
        "delete_product_variant",
        json_schema_extra={
            "const": "delete_product_variant",
            "ui:hidden": True,
            "x-category": "Product",
            "x-is-trigger": False,
            "x-display-name": "Delete Product Variant",
            "x-keywords": ["remove variant", "delete sku", "remove product option"],
        },
        title="Delete Product Variant",
    )
    product_id: str = Field(
        ..., title="Product ID", description="The ID of the product"
    )
    variant_id: str = Field(
        ..., title="Variant ID", description="The ID of the variant to delete"
    )


class ShopifyCountProductVariantsConfig(BaseModel):
    """Get the count of variants for a product"""

    operation: Literal["count_product_variants"] = Field(
        "count_product_variants",
        json_schema_extra={
            "const": "count_product_variants",
            "ui:hidden": True,
            "x-category": "Product",
            "x-is-trigger": False,
            "x-display-name": "Count Product Variants",
            "x-keywords": [
                "how many variants",
                "total variants",
                "variant total",
                "number of skus",
            ],
        },
        title="Count Product Variants",
    )
    product_id: str = Field(
        ..., title="Product ID", description="The ID of the product"
    )


# ============================================================================
# Product Image Operation Configs
# ============================================================================


class ShopifyListProductImagesConfig(BaseModel):
    """List all images for a product"""

    operation: Literal["list_product_images"] = Field(
        "list_product_images",
        json_schema_extra={
            "const": "list_product_images",
            "ui:hidden": True,
            "x-category": "Product",
            "x-is-trigger": False,
            "x-display-name": "List Product Images",
            "x-keywords": [
                "browse product photos",
                "all item images",
                "product gallery",
                "product media",
            ],
        },
        title="List Product Images",
    )
    product_id: str = Field(
        ..., title="Product ID", description="The ID of the product"
    )
    since_id: Optional[str] = Field(
        None, title="Since ID", description="Return images after this ID for pagination"
    )
    fields: Optional[str] = Field(
        None, title="Fields", description="Comma-separated list of fields to include"
    )


class ShopifyGetProductImageConfig(BaseModel):
    """Get a single product image by ID"""

    operation: Literal["get_product_image_by_id"] = Field(
        "get_product_image_by_id",
        json_schema_extra={
            "const": "get_product_image_by_id",
            "ui:hidden": True,
            "x-category": "Product",
            "x-is-trigger": False,
            "x-display-name": "Get Product Image by Id",
            "x-keywords": [
                "single product photo",
                "one product image",
                "specific item image",
            ],
        },
        title="Get Product Image by Id",
    )
    product_id: str = Field(
        ..., title="Product ID", description="The ID of the product"
    )
    image_id: str = Field(
        ..., title="Image ID", description="The ID of the image to retrieve"
    )
    fields: Optional[str] = Field(
        None, title="Fields", description="Comma-separated list of fields to include"
    )


class ShopifyCreateProductImageConfig(BaseModel):
    """Create a new product image"""

    operation: Literal["create_product_image"] = Field(
        "create_product_image",
        json_schema_extra={
            "const": "create_product_image",
            "ui:hidden": True,
            "x-category": "Product",
            "x-is-trigger": False,
            "x-display-name": "Create Product Image",
            "x-keywords": [
                "add product photo",
                "upload item image",
                "attach product picture",
            ],
        },
        title="Create Product Image",
    )
    product_id: str = Field(
        ..., title="Product ID", description="The ID of the product"
    )
    src: Optional[str] = Field(
        None,
        title="Image URL",
        description="The image to send — upload a file, paste a URL, or reference an upstream file (e.g. {{http-1.response.url}}). Shopify will download and host it.",
        json_schema_extra={"ui:widget": "media_upload", "ui:accept": "image/*"},
    )
    attachment: Optional[str] = Field(
        None,
        title="Image Attachment",
        description="Base64-encoded image data",
        json_schema_extra={"ui:widget": "textarea"},
    )
    alt: Optional[str] = Field(
        None, title="Alt Text", description="Alt text for the image"
    )
    position: Optional[int] = Field(
        None, title="Position", description="Position in the image list (1-indexed)"
    )
    variant_ids: Optional[List[str]] = Field(
        None,
        title="Variant IDs",
        description="Array of variant IDs to associate with this image",
    )


class ShopifyDeleteProductImageConfig(BaseModel):
    """Delete a product image"""

    operation: Literal["delete_product_image"] = Field(
        "delete_product_image",
        json_schema_extra={
            "const": "delete_product_image",
            "ui:hidden": True,
            "x-category": "Product",
            "x-is-trigger": False,
            "x-display-name": "Delete Product Image",
            "x-keywords": [
                "remove product photo",
                "delete item image",
                "remove product picture",
            ],
        },
        title="Delete Product Image",
    )
    product_id: str = Field(
        ..., title="Product ID", description="The ID of the product"
    )
    image_id: str = Field(
        ..., title="Image ID", description="The ID of the image to delete"
    )


# ============================================================================
# Order Operation Configs
# ============================================================================


class ShopifyListOrdersConfig(BaseModel):
    """List orders from the store with pagination and filtering"""

    operation: Literal["list_orders"] = Field(
        "list_orders",
        json_schema_extra={
            "const": "list_orders",
            "ui:hidden": True,
            "x-category": "Order",
            "x-is-trigger": False,
            "x-display-name": "List Orders",
            "x-keywords": [
                "browse sales",
                "all orders",
                "recent purchases",
                "paginate orders",
                "filter orders",
            ],
        },
        title="List Orders",
    )
    limit: Optional[int] = Field(
        50,
        title="Limit",
        description="Number of orders to return (max 250)",
        ge=1,
        le=250,
    )
    since_id: Optional[str] = Field(
        None, title="Since ID", description="Return orders after this ID for pagination"
    )
    status: Optional[str] = Field(
        "any",
        title="Status",
        description="Filter by order status",
        json_schema_extra={"enum": ["open", "closed", "cancelled", "any"]},
    )
    financial_status: Optional[str] = Field(
        None,
        title="Financial Status",
        description="Filter by financial status",
        json_schema_extra={
            "enum": [
                "authorized",
                "pending",
                "paid",
                "partially_paid",
                "refunded",
                "voided",
                "partially_refunded",
                "any",
                "unpaid",
            ]
        },
    )
    fulfillment_status: Optional[str] = Field(
        None,
        title="Fulfillment Status",
        description="Filter by fulfillment status",
        json_schema_extra={
            "enum": ["shipped", "partial", "unshipped", "any", "unfulfilled"]
        },
    )
    created_at_min: Optional[str] = Field(
        None,
        title="Created After",
        description="Show orders created after date (ISO 8601 format)",
    )
    created_at_max: Optional[str] = Field(
        None,
        title="Created Before",
        description="Show orders created before date (ISO 8601 format)",
    )
    fields: Optional[str] = Field(
        None, title="Fields", description="Comma-separated list of fields to include"
    )


class ShopifyGetOrderConfig(BaseModel):
    """Get a single order by ID"""

    operation: Literal["get_order_by_id"] = Field(
        "get_order_by_id",
        json_schema_extra={
            "const": "get_order_by_id",
            "ui:hidden": True,
            "x-category": "Order",
            "x-is-trigger": False,
            "x-display-name": "Get Order by Id",
            "x-keywords": [
                "single order details",
                "one order",
                "specific purchase",
                "order by number",
            ],
        },
        title="Get Order by Id",
    )
    order_id: str = Field(
        ..., title="Order ID", description="The ID of the order to retrieve"
    )
    fields: Optional[str] = Field(
        None, title="Fields", description="Comma-separated list of fields to include"
    )


class ShopifyCreateOrderConfig(BaseModel):
    """Create a new order"""

    operation: Literal["create_order"] = Field(
        "create_order",
        json_schema_extra={
            "const": "create_order",
            "ui:hidden": True,
            "x-category": "Order",
            "x-is-trigger": False,
            "x-display-name": "Create Order",
            "x-keywords": ["add new order", "place manual order", "new sale entry"],
        },
        title="Create Order",
    )
    line_items: List[Dict[str, Any]] = Field(
        ...,
        title="Line Items",
        description="Array of line items [{variant_id, quantity} or {title, price, quantity}]",
    )
    customer: Optional[Dict[str, Any]] = Field(
        None,
        title="Customer",
        description="Customer object {id} or {email, first_name, last_name}",
    )
    email: Optional[str] = Field(
        None, title="Email", description="Customer email address"
    )
    shipping_address: Optional[Dict[str, Any]] = Field(
        None,
        title="Shipping Address",
        description="Shipping address object {address1, city, province, country, zip, ...}",
    )
    billing_address: Optional[Dict[str, Any]] = Field(
        None,
        title="Billing Address",
        description="Billing address object {address1, city, province, country, zip, ...}",
    )
    financial_status: Optional[str] = Field(
        None,
        title="Financial Status",
        description="Order financial status",
        json_schema_extra={
            "enum": [
                "pending",
                "authorized",
                "partially_paid",
                "paid",
                "partially_refunded",
                "refunded",
                "voided",
            ]
        },
    )
    send_receipt: Optional[bool] = Field(
        False,
        title="Send Receipt",
        description="Whether to send an order confirmation email",
    )
    send_fulfillment_receipt: Optional[bool] = Field(
        False,
        title="Send Fulfillment Receipt",
        description="Whether to send a shipping confirmation email",
    )
    note: Optional[str] = Field(
        None,
        title="Note",
        description="Order note",
        json_schema_extra={"ui:widget": "textarea"},
    )
    tags: Optional[str] = Field(
        None, title="Tags", description="Comma-separated list of tags"
    )


class ShopifyUpdateOrderConfig(BaseModel):
    """Update an existing order"""

    operation: Literal["update_order"] = Field(
        "update_order",
        json_schema_extra={
            "const": "update_order",
            "ui:hidden": True,
            "x-category": "Order",
            "x-is-trigger": False,
            "x-display-name": "Update Order",
            "x-keywords": [
                "edit order details",
                "change order note",
                "modify purchase",
                "update sale",
            ],
        },
        title="Update Order",
    )
    order_id: str = Field(
        ..., title="Order ID", description="The ID of the order to update"
    )
    note: Optional[str] = Field(
        None,
        title="Note",
        description="Order note",
        json_schema_extra={"ui:widget": "textarea"},
    )
    tags: Optional[str] = Field(
        None, title="Tags", description="Comma-separated list of tags"
    )
    email: Optional[str] = Field(
        None, title="Email", description="Customer email address"
    )
    shipping_address: Optional[Dict[str, Any]] = Field(
        None, title="Shipping Address", description="Updated shipping address"
    )


class ShopifyDeleteOrderConfig(BaseModel):
    """Delete an order"""

    operation: Literal["delete_order"] = Field(
        "delete_order",
        json_schema_extra={
            "const": "delete_order",
            "ui:hidden": True,
            "x-category": "Order",
            "x-is-trigger": False,
            "x-display-name": "Delete Order",
            "x-keywords": ["remove order", "delete purchase record", "erase order"],
        },
        title="Delete Order",
    )
    order_id: str = Field(
        ..., title="Order ID", description="The ID of the order to delete"
    )


class ShopifyCancelOrderConfig(BaseModel):
    """Cancel an order"""

    operation: Literal["cancel_order"] = Field(
        "cancel_order",
        json_schema_extra={
            "const": "cancel_order",
            "ui:hidden": True,
            "x-category": "Order",
            "x-is-trigger": False,
            "x-display-name": "Cancel Order",
            "x-keywords": [
                "void order",
                "cancel purchase",
                "abort sale",
                "cancel this order",
            ],
        },
        title="Cancel Order",
    )
    order_id: str = Field(
        ..., title="Order ID", description="The ID of the order to cancel"
    )
    reason: Optional[str] = Field(
        None,
        title="Cancel Reason",
        description="Reason for cancellation",
        json_schema_extra={
            "enum": ["customer", "fraud", "inventory", "declined", "other"]
        },
    )
    email: Optional[bool] = Field(
        True,
        title="Send Email",
        description="Whether to send a cancellation email to the customer",
    )
    restock: Optional[bool] = Field(
        True,
        title="Restock Items",
        description="Whether to restock the order's line items",
    )


class ShopifyCloseOrderConfig(BaseModel):
    """Close an order"""

    operation: Literal["close_order"] = Field(
        "close_order",
        json_schema_extra={
            "const": "close_order",
            "ui:hidden": True,
            "x-category": "Order",
            "x-is-trigger": False,
            "x-display-name": "Close Order",
            "x-keywords": [
                "mark order done",
                "archive order",
                "finalize order",
                "close this sale",
            ],
        },
        title="Close Order",
    )
    order_id: str = Field(
        ..., title="Order ID", description="The ID of the order to close"
    )


class ShopifyOpenOrderConfig(BaseModel):
    """Reopen a closed order"""

    operation: Literal["reopen_closed_order"] = Field(
        "reopen_closed_order",
        json_schema_extra={
            "const": "reopen_closed_order",
            "ui:hidden": True,
            "x-category": "Order",
            "x-is-trigger": False,
            "x-display-name": "Reopen Closed Order",
            "x-keywords": [
                "reopen order",
                "unarchive order",
                "restore closed order",
                "reactivate order",
            ],
        },
        title="Reopen Closed Order",
    )
    order_id: str = Field(
        ..., title="Order ID", description="The ID of the order to reopen"
    )


class ShopifyCountOrdersConfig(BaseModel):
    """Get the count of orders"""

    operation: Literal["count_orders"] = Field(
        "count_orders",
        json_schema_extra={
            "const": "count_orders",
            "ui:hidden": True,
            "x-category": "Order",
            "x-is-trigger": False,
            "x-display-name": "Count Orders",
            "x-keywords": [
                "how many orders",
                "total orders",
                "order total",
                "number of sales",
            ],
        },
        title="Count Orders",
    )
    status: Optional[str] = Field(
        "any",
        title="Status",
        description="Count orders with this status",
        json_schema_extra={"enum": ["open", "closed", "cancelled", "any"]},
    )
    financial_status: Optional[str] = Field(
        None,
        title="Financial Status",
        description="Count orders with this financial status",
    )
    fulfillment_status: Optional[str] = Field(
        None,
        title="Fulfillment Status",
        description="Count orders with this fulfillment status",
    )


# ============================================================================
# Refund Operation Configs
# ============================================================================


class ShopifyListRefundsConfig(BaseModel):
    """List all refunds for an order"""

    operation: Literal["list_order_refunds"] = Field(
        "list_order_refunds",
        json_schema_extra={
            "const": "list_order_refunds",
            "ui:hidden": True,
            "x-category": "Order",
            "x-is-trigger": False,
            "x-display-name": "List Order Refunds",
            "x-keywords": [
                "browse refunds",
                "order refund history",
                "all refunds",
                "returns for order",
            ],
        },
        title="List Order Refunds",
    )
    order_id: str = Field(..., title="Order ID", description="The ID of the order")
    fields: Optional[str] = Field(
        None, title="Fields", description="Comma-separated list of fields to include"
    )


class ShopifyGetRefundConfig(BaseModel):
    """Get a single refund by ID"""

    operation: Literal["get_order_refund_by_id"] = Field(
        "get_order_refund_by_id",
        json_schema_extra={
            "const": "get_order_refund_by_id",
            "ui:hidden": True,
            "x-category": "Order",
            "x-is-trigger": False,
            "x-display-name": "Get Order Refund by Id",
            "x-keywords": ["single refund details", "one refund", "specific return"],
        },
        title="Get Order Refund by Id",
    )
    order_id: str = Field(..., title="Order ID", description="The ID of the order")
    refund_id: str = Field(
        ..., title="Refund ID", description="The ID of the refund to retrieve"
    )
    fields: Optional[str] = Field(
        None, title="Fields", description="Comma-separated list of fields to include"
    )


class ShopifyCreateRefundConfig(BaseModel):
    """Create a refund for an order"""

    operation: Literal["create_order_refund"] = Field(
        "create_order_refund",
        json_schema_extra={
            "const": "create_order_refund",
            "ui:hidden": True,
            "x-category": "Order",
            "x-is-trigger": False,
            "x-display-name": "Create Order Refund",
            "x-keywords": [
                "issue refund",
                "refund order",
                "process return",
                "give money back",
            ],
        },
        title="Create Order Refund",
    )
    order_id: str = Field(
        ..., title="Order ID", description="The ID of the order to refund"
    )
    refund_line_items: Optional[List[Dict[str, Any]]] = Field(
        None,
        title="Refund Line Items",
        description="Array of line items to refund [{line_item_id, quantity, restock_type}]",
    )
    shipping: Optional[Dict[str, Any]] = Field(
        None,
        title="Shipping Refund",
        description="Shipping refund details {full_refund: true} or {amount: '10.00'}",
    )
    transactions: Optional[List[Dict[str, Any]]] = Field(
        None,
        title="Transactions",
        description="Array of transactions for the refund [{parent_id, amount, kind, gateway}]",
    )
    currency: Optional[str] = Field(
        None,
        title="Currency",
        description="Three-letter currency code (e.g., USD, EUR)",
    )
    notify: Optional[bool] = Field(
        False,
        title="Send Notification",
        description="Whether to send a refund notification to the customer",
    )
    note: Optional[str] = Field(
        None, title="Note", description="Optional note for the refund"
    )


class ShopifyCalculateRefundConfig(BaseModel):
    """Calculate refund transactions for an order"""

    operation: Literal["calculate_order_refund"] = Field(
        "calculate_order_refund",
        json_schema_extra={
            "const": "calculate_order_refund",
            "ui:hidden": True,
            "x-category": "Order",
            "x-is-trigger": False,
            "x-display-name": "Calculate Order Refund",
            "x-keywords": [
                "preview refund amount",
                "estimate refund",
                "calculate refund total",
                "refund suggestion",
                "compute refund",
            ],
        },
        title="Calculate Order Refund",
    )
    order_id: str = Field(..., title="Order ID", description="The ID of the order")
    refund_line_items: Optional[List[Dict[str, Any]]] = Field(
        None,
        title="Refund Line Items",
        description="Array of line items to refund [{line_item_id, quantity, restock_type}]",
    )
    shipping: Optional[Dict[str, Any]] = Field(
        None,
        title="Shipping Refund",
        description="Shipping refund details {full_refund: true} or {amount: '10.00'}",
    )
    currency: Optional[str] = Field(
        None, title="Currency", description="Three-letter currency code"
    )


# ============================================================================
# Transaction Operation Configs
# ============================================================================


class ShopifyListTransactionsConfig(BaseModel):
    """List all transactions for an order"""

    operation: Literal["list_order_transactions"] = Field(
        "list_order_transactions",
        json_schema_extra={
            "const": "list_order_transactions",
            "ui:hidden": True,
            "x-category": "Order",
            "x-is-trigger": False,
            "x-display-name": "List Order Transactions",
            "x-keywords": [
                "order payments list",
                "transactions on order",
                "captures and authorizations",
                "money movements",
                "payment history",
            ],
        },
        title="List Order Transactions",
    )
    order_id: str = Field(..., title="Order ID", description="The ID of the order")
    since_id: Optional[str] = Field(
        None,
        title="Since ID",
        description="Return transactions after this ID for pagination",
    )
    fields: Optional[str] = Field(
        None, title="Fields", description="Comma-separated list of fields to include"
    )


class ShopifyGetTransactionConfig(BaseModel):
    """Get a single transaction by ID"""

    operation: Literal["get_order_transaction_by_id"] = Field(
        "get_order_transaction_by_id",
        json_schema_extra={
            "const": "get_order_transaction_by_id",
            "ui:hidden": True,
            "x-category": "Order",
            "x-is-trigger": False,
            "x-display-name": "Get Order Transaction by Id",
            "x-keywords": [
                "single transaction",
                "one payment record",
                "transaction details",
                "specific capture",
            ],
        },
        title="Get Order Transaction by Id",
    )
    order_id: str = Field(..., title="Order ID", description="The ID of the order")
    transaction_id: str = Field(
        ..., title="Transaction ID", description="The ID of the transaction to retrieve"
    )
    fields: Optional[str] = Field(
        None, title="Fields", description="Comma-separated list of fields to include"
    )


class ShopifyCreateTransactionConfig(BaseModel):
    """Create a transaction for an order"""

    operation: Literal["create_order_transaction"] = Field(
        "create_order_transaction",
        json_schema_extra={
            "const": "create_order_transaction",
            "ui:hidden": True,
            "x-category": "Order",
            "x-is-trigger": False,
            "x-display-name": "Create Order Transaction",
            "x-keywords": [
                "capture payment",
                "void transaction",
                "record authorization",
                "add transaction",
                "process payment",
            ],
        },
        title="Create Order Transaction",
    )
    order_id: str = Field(..., title="Order ID", description="The ID of the order")
    kind: str = Field(
        ...,
        title="Transaction Kind",
        description="Type of transaction",
        json_schema_extra={
            "enum": ["authorization", "capture", "sale", "void", "refund"]
        },
    )
    amount: Optional[str] = Field(
        None, title="Amount", description="Amount of money for the transaction"
    )
    currency: Optional[str] = Field(
        None, title="Currency", description="Three-letter currency code"
    )
    gateway: Optional[str] = Field(
        None, title="Gateway", description="Payment gateway used"
    )
    parent_id: Optional[str] = Field(
        None,
        title="Parent Transaction ID",
        description="ID of the parent authorization transaction",
    )
    test: Optional[bool] = Field(
        None, title="Test Mode", description="Whether this is a test transaction"
    )


class ShopifyCountTransactionsConfig(BaseModel):
    """Get the count of transactions for an order"""

    operation: Literal["count_order_transactions"] = Field(
        "count_order_transactions",
        json_schema_extra={
            "const": "count_order_transactions",
            "ui:hidden": True,
            "x-category": "Order",
            "x-is-trigger": False,
            "x-display-name": "Count Order Transactions",
            "x-keywords": [
                "how many transactions",
                "number of payments",
                "transaction total count",
            ],
        },
        title="Count Order Transactions",
    )
    order_id: str = Field(..., title="Order ID", description="The ID of the order")


# ============================================================================
# Customer Operation Configs
# ============================================================================


class ShopifyListCustomersConfig(BaseModel):
    """List customers from the store with pagination and filtering"""

    operation: Literal["list_customers"] = Field(
        "list_customers",
        json_schema_extra={
            "const": "list_customers",
            "ui:hidden": True,
            "x-category": "Customer",
            "x-is-trigger": False,
            "x-display-name": "List Customers",
            "x-keywords": [
                "browse customers",
                "shoppers list",
                "buyers",
                "store customers",
            ],
        },
        title="List Customers",
    )
    limit: Optional[int] = Field(
        50,
        title="Limit",
        description="Number of customers to return (max 250)",
        ge=1,
        le=250,
    )
    since_id: Optional[str] = Field(
        None,
        title="Since ID",
        description="Return customers after this ID for pagination",
    )
    created_at_min: Optional[str] = Field(
        None,
        title="Created After",
        description="Show customers created after date (ISO 8601 format)",
    )
    created_at_max: Optional[str] = Field(
        None,
        title="Created Before",
        description="Show customers created before date (ISO 8601 format)",
    )
    updated_at_min: Optional[str] = Field(
        None,
        title="Updated After",
        description="Show customers updated after date (ISO 8601 format)",
    )
    updated_at_max: Optional[str] = Field(
        None,
        title="Updated Before",
        description="Show customers updated before date (ISO 8601 format)",
    )
    fields: Optional[str] = Field(
        None, title="Fields", description="Comma-separated list of fields to include"
    )


class ShopifyGetCustomerConfig(BaseModel):
    """Get a single customer by ID"""

    operation: Literal["get_customer_by_id"] = Field(
        "get_customer_by_id",
        json_schema_extra={
            "const": "get_customer_by_id",
            "ui:hidden": True,
            "x-category": "Customer",
            "x-is-trigger": False,
            "x-display-name": "Get Customer by Id",
            "x-keywords": [
                "single customer",
                "one shopper",
                "customer details",
                "buyer profile",
            ],
        },
        title="Get Customer by Id",
    )
    customer_id: str = Field(
        ..., title="Customer ID", description="The ID of the customer to retrieve"
    )
    fields: Optional[str] = Field(
        None, title="Fields", description="Comma-separated list of fields to include"
    )


class ShopifyCreateCustomerConfig(BaseModel):
    """Create a new customer"""

    operation: Literal["create_customer"] = Field(
        "create_customer",
        json_schema_extra={
            "const": "create_customer",
            "ui:hidden": True,
            "x-category": "Customer",
            "x-is-trigger": False,
            "x-display-name": "Create Customer",
            "x-keywords": ["add new customer", "register shopper", "new buyer"],
        },
        title="Create Customer",
    )
    email: str = Field(..., title="Email", description="Customer email address")
    first_name: Optional[str] = Field(
        None, title="First Name", description="Customer's first name"
    )
    last_name: Optional[str] = Field(
        None, title="Last Name", description="Customer's last name"
    )
    phone: Optional[str] = Field(
        None, title="Phone", description="Customer's phone number"
    )
    verified_email: Optional[bool] = Field(
        True, title="Verified Email", description="Whether the email is verified"
    )
    addresses: Optional[List[Dict[str, Any]]] = Field(
        None,
        title="Addresses",
        description="Customer addresses array [{address1, city, province, country, zip, ...}]",
    )
    tags: Optional[str] = Field(
        None, title="Tags", description="Comma-separated list of tags"
    )
    note: Optional[str] = Field(
        None,
        title="Note",
        description="Note about the customer",
        json_schema_extra={"ui:widget": "textarea"},
    )
    send_email_welcome: Optional[bool] = Field(
        False, title="Send Welcome Email", description="Whether to send a welcome email"
    )
    send_email_invite: Optional[bool] = Field(
        False,
        title="Send Invite Email",
        description="Whether to send an account invite email",
    )


class ShopifyUpdateCustomerConfig(BaseModel):
    """Update an existing customer"""

    operation: Literal["update_customer"] = Field(
        "update_customer",
        json_schema_extra={
            "const": "update_customer",
            "ui:hidden": True,
            "x-category": "Customer",
            "x-is-trigger": False,
            "x-display-name": "Update Customer",
            "x-keywords": [
                "edit customer details",
                "change buyer info",
                "modify shopper",
            ],
        },
        title="Update Customer",
    )
    customer_id: str = Field(
        ..., title="Customer ID", description="The ID of the customer to update"
    )
    email: Optional[str] = Field(
        None, title="Email", description="Customer email address"
    )
    first_name: Optional[str] = Field(
        None, title="First Name", description="Customer's first name"
    )
    last_name: Optional[str] = Field(
        None, title="Last Name", description="Customer's last name"
    )
    phone: Optional[str] = Field(
        None, title="Phone", description="Customer's phone number"
    )
    tags: Optional[str] = Field(
        None, title="Tags", description="Comma-separated list of tags"
    )
    note: Optional[str] = Field(
        None,
        title="Note",
        description="Note about the customer",
        json_schema_extra={"ui:widget": "textarea"},
    )


class ShopifyDeleteCustomerConfig(BaseModel):
    """Delete a customer"""

    operation: Literal["delete_customer"] = Field(
        "delete_customer",
        json_schema_extra={
            "const": "delete_customer",
            "ui:hidden": True,
            "x-category": "Customer",
            "x-is-trigger": False,
            "x-display-name": "Delete Customer",
            "x-keywords": ["remove customer", "erase shopper", "delete buyer"],
        },
        title="Delete Customer",
    )
    customer_id: str = Field(
        ..., title="Customer ID", description="The ID of the customer to delete"
    )


class ShopifySearchCustomersConfig(BaseModel):
    """Search for customers"""

    operation: Literal["search_customers"] = Field(
        "search_customers",
        json_schema_extra={
            "const": "search_customers",
            "ui:hidden": True,
            "x-category": "Customer",
            "x-is-trigger": False,
            "x-display-name": "Search Customers",
            "x-keywords": [
                "find customer by email",
                "lookup shopper",
                "query buyers",
                "filter customers",
            ],
        },
        title="Search Customers",
    )
    query: str = Field(
        ...,
        title="Query",
        description="Search query (e.g., 'email:test@example.com' or 'first_name:John')",
    )
    limit: Optional[int] = Field(
        50,
        title="Limit",
        description="Number of results to return (max 250)",
        ge=1,
        le=250,
    )
    fields: Optional[str] = Field(
        None, title="Fields", description="Comma-separated list of fields to include"
    )


class ShopifyCountCustomersConfig(BaseModel):
    """Get the count of customers"""

    operation: Literal["count_customers"] = Field(
        "count_customers",
        json_schema_extra={
            "const": "count_customers",
            "ui:hidden": True,
            "x-category": "Customer",
            "x-is-trigger": False,
            "x-display-name": "Count Customers",
            "x-keywords": [
                "how many customers",
                "number of shoppers",
                "customer total",
            ],
        },
        title="Count Customers",
    )


class ShopifyGetCustomerOrdersConfig(BaseModel):
    """Get orders for a specific customer"""

    operation: Literal["get_customer_orders"] = Field(
        "get_customer_orders",
        json_schema_extra={
            "const": "get_customer_orders",
            "ui:hidden": True,
            "x-category": "Order",
            "x-is-trigger": False,
            "x-display-name": "Get Customer Orders",
            "x-keywords": [
                "orders by customer",
                "shopper purchase history",
                "buyer orders",
                "customer order history",
            ],
        },
        title="Get Customer Orders",
    )
    customer_id: str = Field(
        ..., title="Customer ID", description="The ID of the customer"
    )
    status: Optional[str] = Field(
        "any",
        title="Status",
        description="Filter by order status",
        json_schema_extra={"enum": ["open", "closed", "cancelled", "any"]},
    )


# ============================================================================
# Customer Address Operation Configs
# ============================================================================


class ShopifyListCustomerAddressesConfig(BaseModel):
    """List all addresses for a customer"""

    operation: Literal["list_customer_addresses"] = Field(
        "list_customer_addresses",
        json_schema_extra={
            "const": "list_customer_addresses",
            "ui:hidden": True,
            "x-category": "Customer",
            "x-is-trigger": False,
            "x-display-name": "List Customer Addresses",
            "x-keywords": [
                "customer shipping addresses",
                "buyer address book",
                "shopper addresses",
            ],
        },
        title="List Customer Addresses",
    )
    customer_id: str = Field(
        ..., title="Customer ID", description="The ID of the customer"
    )


class ShopifyGetCustomerAddressConfig(BaseModel):
    """Get a single customer address by ID"""

    operation: Literal["get_customer_address_by_id"] = Field(
        "get_customer_address_by_id",
        json_schema_extra={
            "const": "get_customer_address_by_id",
            "ui:hidden": True,
            "x-category": "Customer",
            "x-is-trigger": False,
            "x-display-name": "Get Customer Address by Id",
            "x-keywords": [
                "single customer address",
                "one shipping address",
                "specific buyer address",
            ],
        },
        title="Get Customer Address by Id",
    )
    customer_id: str = Field(
        ..., title="Customer ID", description="The ID of the customer"
    )
    address_id: str = Field(
        ..., title="Address ID", description="The ID of the address to retrieve"
    )


class ShopifyCreateCustomerAddressConfig(BaseModel):
    """Create a new address for a customer"""

    operation: Literal["create_customer_address"] = Field(
        "create_customer_address",
        json_schema_extra={
            "const": "create_customer_address",
            "ui:hidden": True,
            "x-category": "Customer",
            "x-is-trigger": False,
            "x-display-name": "Create Customer Address",
            "x-keywords": [
                "add customer address",
                "new shipping address",
                "register buyer address",
            ],
        },
        title="Create Customer Address",
    )
    customer_id: str = Field(
        ..., title="Customer ID", description="The ID of the customer"
    )
    address1: Optional[str] = Field(
        None, title="Address Line 1", description="Street address line 1"
    )
    address2: Optional[str] = Field(
        None, title="Address Line 2", description="Street address line 2"
    )
    city: Optional[str] = Field(None, title="City", description="City name")
    province: Optional[str] = Field(
        None, title="Province/State", description="Province or state name"
    )
    country: Optional[str] = Field(None, title="Country", description="Country name")
    zip: Optional[str] = Field(
        None, title="Zip/Postal Code", description="ZIP or postal code"
    )
    phone: Optional[str] = Field(None, title="Phone", description="Phone number")
    name: Optional[str] = Field(
        None, title="Name", description="Full name for this address"
    )
    company: Optional[str] = Field(None, title="Company", description="Company name")
    first_name: Optional[str] = Field(
        None, title="First Name", description="First name"
    )
    last_name: Optional[str] = Field(None, title="Last Name", description="Last name")


class ShopifyUpdateCustomerAddressConfig(BaseModel):
    """Update an existing customer address"""

    operation: Literal["update_customer_address"] = Field(
        "update_customer_address",
        json_schema_extra={
            "const": "update_customer_address",
            "ui:hidden": True,
            "x-category": "Customer",
            "x-is-trigger": False,
            "x-display-name": "Update Customer Address",
            "x-keywords": [
                "edit customer address",
                "change shipping address",
                "modify buyer address",
            ],
        },
        title="Update Customer Address",
    )
    customer_id: str = Field(
        ..., title="Customer ID", description="The ID of the customer"
    )
    address_id: str = Field(
        ..., title="Address ID", description="The ID of the address to update"
    )
    address1: Optional[str] = Field(
        None, title="Address Line 1", description="Street address line 1"
    )
    address2: Optional[str] = Field(
        None, title="Address Line 2", description="Street address line 2"
    )
    city: Optional[str] = Field(None, title="City", description="City name")
    province: Optional[str] = Field(
        None, title="Province/State", description="Province or state name"
    )
    country: Optional[str] = Field(None, title="Country", description="Country name")
    zip: Optional[str] = Field(
        None, title="Zip/Postal Code", description="ZIP or postal code"
    )
    phone: Optional[str] = Field(None, title="Phone", description="Phone number")
    name: Optional[str] = Field(
        None, title="Name", description="Full name for this address"
    )
    company: Optional[str] = Field(None, title="Company", description="Company name")
    first_name: Optional[str] = Field(
        None, title="First Name", description="First name"
    )
    last_name: Optional[str] = Field(None, title="Last Name", description="Last name")


class ShopifyDeleteCustomerAddressConfig(BaseModel):
    """Delete a customer address"""

    operation: Literal["delete_customer_address"] = Field(
        "delete_customer_address",
        json_schema_extra={
            "const": "delete_customer_address",
            "ui:hidden": True,
            "x-category": "Customer",
            "x-is-trigger": False,
            "x-display-name": "Delete Customer Address",
            "x-keywords": [
                "remove customer address",
                "erase shipping address",
                "delete buyer address",
            ],
        },
        title="Delete Customer Address",
    )
    customer_id: str = Field(
        ..., title="Customer ID", description="The ID of the customer"
    )
    address_id: str = Field(
        ..., title="Address ID", description="The ID of the address to delete"
    )


class ShopifySetDefaultCustomerAddressConfig(BaseModel):
    """Set a customer address as the default"""

    operation: Literal["set_default_customer_address"] = Field(
        "set_default_customer_address",
        json_schema_extra={
            "const": "set_default_customer_address",
            "ui:hidden": True,
            "x-category": "Customer",
            "x-is-trigger": False,
            "x-display-name": "Set Default Customer Address",
            "x-keywords": [
                "mark address default",
                "primary shipping address",
                "make address default",
                "default billing address",
            ],
        },
        title="Set Default Customer Address",
    )
    customer_id: str = Field(
        ..., title="Customer ID", description="The ID of the customer"
    )
    address_id: str = Field(
        ..., title="Address ID", description="The ID of the address to set as default"
    )


# ============================================================================
# Inventory Operation Configs
# ============================================================================


class ShopifyListInventoryLevelsConfig(BaseModel):
    """List inventory levels for items or locations"""

    operation: Literal["list_inventory_levels"] = Field(
        "list_inventory_levels",
        json_schema_extra={
            "const": "list_inventory_levels",
            "ui:hidden": True,
            "x-category": "Inventory",
            "x-is-trigger": False,
            "x-display-name": "List Inventory Levels",
            "x-keywords": [
                "stock levels",
                "available quantity",
                "on hand inventory",
                "stock on hand",
            ],
        },
        title="List Inventory Levels",
    )
    inventory_item_ids: Optional[str] = Field(
        None,
        title="Inventory Item IDs",
        description="Comma-separated inventory item IDs (max 50)",
    )
    location_ids: Optional[str] = Field(
        None, title="Location IDs", description="Comma-separated location IDs (max 50)"
    )
    limit: Optional[int] = Field(
        50,
        title="Limit",
        description="Number of results to return (max 250)",
        ge=1,
        le=250,
    )


class ShopifyAdjustInventoryLevelConfig(BaseModel):
    """Adjust the inventory level of an item at a location"""

    operation: Literal["adjust_inventory_level_at_location"] = Field(
        "adjust_inventory_level_at_location",
        json_schema_extra={
            "const": "adjust_inventory_level_at_location",
            "ui:hidden": True,
            "x-category": "Inventory",
            "x-is-trigger": False,
            "x-display-name": "Adjust Inventory Level at Location",
            "x-keywords": [
                "increment stock",
                "decrement quantity",
                "change stock by amount",
                "restock delta",
                "adjust available",
            ],
        },
        title="Adjust Inventory Level at Location",
    )
    inventory_item_id: str = Field(
        ..., title="Inventory Item ID", description="The ID of the inventory item"
    )
    location_id: str = Field(
        ..., title="Location ID", description="The ID of the location"
    )
    available_adjustment: int = Field(
        ...,
        title="Adjustment",
        description="The quantity to adjust by (positive or negative)",
    )


class ShopifySetInventoryLevelConfig(BaseModel):
    """Set the inventory level of an item at a location"""

    operation: Literal["set_inventory_level_at_location"] = Field(
        "set_inventory_level_at_location",
        json_schema_extra={
            "const": "set_inventory_level_at_location",
            "ui:hidden": True,
            "x-category": "Inventory",
            "x-is-trigger": False,
            "x-display-name": "Set Inventory Level at Location",
            "x-keywords": [
                "set stock count",
                "override quantity",
                "fixed inventory value",
                "set available stock",
            ],
        },
        title="Set Inventory Level at Location",
    )
    inventory_item_id: str = Field(
        ..., title="Inventory Item ID", description="The ID of the inventory item"
    )
    location_id: str = Field(
        ..., title="Location ID", description="The ID of the location"
    )
    available: int = Field(
        ..., title="Available Quantity", description="The quantity to set"
    )
    disconnect_if_necessary: Optional[bool] = Field(
        False,
        title="Disconnect If Necessary",
        description="Whether to disconnect from other locations if needed",
    )


class ShopifyConnectInventoryLevelConfig(BaseModel):
    """Connect an inventory item to a location"""

    operation: Literal["connect_inventory_item_to_location"] = Field(
        "connect_inventory_item_to_location",
        json_schema_extra={
            "const": "connect_inventory_item_to_location",
            "ui:hidden": True,
            "x-category": "Inventory",
            "x-is-trigger": False,
            "x-display-name": "Connect Inventory Item to Location",
            "x-keywords": [
                "link item to location",
                "enable stock tracking",
                "attach inventory item",
                "stock at warehouse",
            ],
        },
        title="Connect Inventory Item to Location",
    )
    inventory_item_id: str = Field(
        ..., title="Inventory Item ID", description="The ID of the inventory item"
    )
    location_id: str = Field(
        ..., title="Location ID", description="The ID of the location to connect to"
    )
    relocate_if_necessary: Optional[bool] = Field(
        False,
        title="Relocate If Necessary",
        description="Whether to relocate inventory from previous locations",
    )


class ShopifyDeleteInventoryLevelConfig(BaseModel):
    """Delete an inventory level (disconnect item from location)"""

    operation: Literal["delete_inventory_level"] = Field(
        "delete_inventory_level",
        json_schema_extra={
            "const": "delete_inventory_level",
            "ui:hidden": True,
            "x-category": "Inventory",
            "x-is-trigger": False,
            "x-display-name": "Delete Inventory Level",
            "x-keywords": [
                "disconnect item from location",
                "remove stock tracking",
                "unlink inventory",
            ],
        },
        title="Delete Inventory Level",
    )
    inventory_item_id: str = Field(
        ..., title="Inventory Item ID", description="The ID of the inventory item"
    )
    location_id: str = Field(
        ...,
        title="Location ID",
        description="The ID of the location to disconnect from",
    )


# ============================================================================
# Fulfillment Operation Configs
# ============================================================================


class ShopifyListFulfillmentsConfig(BaseModel):
    """List fulfillments for an order"""

    operation: Literal["list_order_fulfillments"] = Field(
        "list_order_fulfillments",
        json_schema_extra={
            "const": "list_order_fulfillments",
            "ui:hidden": True,
            "x-category": "Fulfillment",
            "x-is-trigger": False,
            "x-display-name": "List Order Fulfillments",
            "x-keywords": [
                "shipments for order",
                "fulfillment list",
                "order shipping records",
            ],
        },
        title="List Order Fulfillments",
    )
    order_id: str = Field(..., title="Order ID", description="The ID of the order")


class ShopifyGetFulfillmentConfig(BaseModel):
    """Get a single fulfillment"""

    operation: Literal["get_order_fulfillment"] = Field(
        "get_order_fulfillment",
        json_schema_extra={
            "const": "get_order_fulfillment",
            "ui:hidden": True,
            "x-category": "Fulfillment",
            "x-is-trigger": False,
            "x-display-name": "Get Order Fulfillment",
            "x-keywords": ["single fulfillment", "one shipment", "fulfillment details"],
        },
        title="Get Order Fulfillment",
    )
    order_id: str = Field(..., title="Order ID", description="The ID of the order")
    fulfillment_id: str = Field(
        ..., title="Fulfillment ID", description="The ID of the fulfillment"
    )


class ShopifyCreateFulfillmentConfig(BaseModel):
    """Create a fulfillment for an order"""

    operation: Literal["create_order_fulfillment"] = Field(
        "create_order_fulfillment",
        json_schema_extra={
            "const": "create_order_fulfillment",
            "ui:hidden": True,
            "x-category": "Fulfillment",
            "x-is-trigger": False,
            "x-display-name": "Create Order Fulfillment",
            "x-keywords": [
                "fulfill order",
                "ship order",
                "mark shipped",
                "create shipment",
                "dispatch order",
            ],
        },
        title="Create Order Fulfillment",
    )
    order_id: str = Field(..., title="Order ID", description="The ID of the order")
    location_id: Optional[str] = Field(
        None, title="Location ID", description="The ID of the location"
    )
    tracking_number: Optional[str] = Field(
        None, title="Tracking Number", description="Shipment tracking number"
    )
    tracking_urls: Optional[List[str]] = Field(
        None, title="Tracking URLs", description="List of tracking URLs"
    )
    notify_customer: Optional[bool] = Field(
        True, title="Notify Customer", description="Send a shipping notification email"
    )
    line_items: Optional[List[Dict[str, Any]]] = Field(
        None, title="Line Items", description="Line items to fulfill [{id, quantity}]"
    )


class ShopifyUpdateFulfillmentConfig(BaseModel):
    """Update a fulfillment"""

    operation: Literal["update_order_fulfillment"] = Field(
        "update_order_fulfillment",
        json_schema_extra={
            "const": "update_order_fulfillment",
            "ui:hidden": True,
            "x-category": "Fulfillment",
            "x-is-trigger": False,
            "x-display-name": "Update Order Fulfillment",
            "x-keywords": [
                "edit fulfillment",
                "update tracking number",
                "change shipment",
            ],
        },
        title="Update Order Fulfillment",
    )
    order_id: str = Field(..., title="Order ID", description="The ID of the order")
    fulfillment_id: str = Field(
        ..., title="Fulfillment ID", description="The ID of the fulfillment"
    )
    tracking_number: Optional[str] = Field(
        None, title="Tracking Number", description="Shipment tracking number"
    )
    tracking_urls: Optional[List[str]] = Field(
        None, title="Tracking URLs", description="List of tracking URLs"
    )
    notify_customer: Optional[bool] = Field(
        False, title="Notify Customer", description="Send a shipping notification email"
    )


class ShopifyCompleteFulfillmentConfig(BaseModel):
    """Mark a fulfillment as complete"""

    operation: Literal["complete_order_fulfillment"] = Field(
        "complete_order_fulfillment",
        json_schema_extra={
            "const": "complete_order_fulfillment",
            "ui:hidden": True,
            "x-category": "Fulfillment",
            "x-is-trigger": False,
            "x-display-name": "Complete Order Fulfillment",
            "x-keywords": [
                "mark fulfillment complete",
                "finish shipment",
                "complete shipping",
            ],
        },
        title="Complete Order Fulfillment",
    )
    order_id: str = Field(..., title="Order ID", description="The ID of the order")
    fulfillment_id: str = Field(
        ..., title="Fulfillment ID", description="The ID of the fulfillment"
    )


class ShopifyCancelFulfillmentConfig(BaseModel):
    """Cancel a fulfillment"""

    operation: Literal["cancel_order_fulfillment"] = Field(
        "cancel_order_fulfillment",
        json_schema_extra={
            "const": "cancel_order_fulfillment",
            "ui:hidden": True,
            "x-category": "Fulfillment",
            "x-is-trigger": False,
            "x-display-name": "Cancel Order Fulfillment",
            "x-keywords": ["cancel shipment", "undo fulfillment", "void shipping"],
        },
        title="Cancel Order Fulfillment",
    )
    order_id: str = Field(..., title="Order ID", description="The ID of the order")
    fulfillment_id: str = Field(
        ..., title="Fulfillment ID", description="The ID of the fulfillment"
    )


# ============================================================================
# Collection Operation Configs
# ============================================================================


class ShopifyListCollectionsConfig(BaseModel):
    """List collections (custom collections)"""

    operation: Literal["list_collections"] = Field(
        "list_collections",
        json_schema_extra={
            "const": "list_collections",
            "ui:hidden": True,
            "x-category": "Collection",
            "x-is-trigger": False,
            "x-display-name": "List Collections",
            "x-keywords": [
                "browse collections",
                "product groups",
                "store collections",
                "category list",
            ],
        },
        title="List Collections",
    )
    limit: Optional[int] = Field(
        50,
        title="Limit",
        description="Number of collections to return (max 250)",
        ge=1,
        le=250,
    )
    since_id: Optional[str] = Field(
        None, title="Since ID", description="Return collections after this ID"
    )
    title: Optional[str] = Field(
        None, title="Title", description="Filter by collection title"
    )


class ShopifyGetCollectionConfig(BaseModel):
    """Get a single collection"""

    operation: Literal["get_collection_by_id"] = Field(
        "get_collection_by_id",
        json_schema_extra={
            "const": "get_collection_by_id",
            "ui:hidden": True,
            "x-category": "Collection",
            "x-is-trigger": False,
            "x-display-name": "Get Collection by Id",
            "x-keywords": [
                "single collection",
                "one product group",
                "collection details",
            ],
        },
        title="Get Collection by Id",
    )
    collection_id: str = Field(
        ..., title="Collection ID", description="The ID of the collection"
    )


class ShopifyCreateCollectionConfig(BaseModel):
    """Create a new collection"""

    operation: Literal["create_collection"] = Field(
        "create_collection",
        json_schema_extra={
            "const": "create_collection",
            "ui:hidden": True,
            "x-category": "Collection",
            "x-is-trigger": False,
            "x-display-name": "Create Collection",
            "x-keywords": ["add collection", "new product group", "make category"],
        },
        title="Create Collection",
    )
    title: str = Field(..., title="Title", description="Collection title")
    body_html: Optional[str] = Field(
        None,
        title="Description (HTML)",
        description="Collection description",
        json_schema_extra={"ui:widget": "textarea"},
    )
    image: Optional[Dict[str, Any]] = Field(
        None, title="Image", description="Collection image {src, alt}"
    )
    published: Optional[bool] = Field(
        True, title="Published", description="Whether the collection is published"
    )


class ShopifyUpdateCollectionConfig(BaseModel):
    """Update a collection"""

    operation: Literal["update_collection"] = Field(
        "update_collection",
        json_schema_extra={
            "const": "update_collection",
            "ui:hidden": True,
            "x-category": "Collection",
            "x-is-trigger": False,
            "x-display-name": "Update Collection",
            "x-keywords": [
                "edit collection",
                "change product group",
                "modify category",
            ],
        },
        title="Update Collection",
    )
    collection_id: str = Field(
        ..., title="Collection ID", description="The ID of the collection"
    )
    title: Optional[str] = Field(None, title="Title", description="Collection title")
    body_html: Optional[str] = Field(
        None,
        title="Description (HTML)",
        description="Collection description",
        json_schema_extra={"ui:widget": "textarea"},
    )
    image: Optional[Dict[str, Any]] = Field(
        None, title="Image", description="Collection image {src, alt}"
    )


class ShopifyDeleteCollectionConfig(BaseModel):
    """Delete a collection"""

    operation: Literal["delete_collection"] = Field(
        "delete_collection",
        json_schema_extra={
            "const": "delete_collection",
            "ui:hidden": True,
            "x-category": "Collection",
            "x-is-trigger": False,
            "x-display-name": "Delete Collection",
            "x-keywords": [
                "remove collection",
                "erase product group",
                "delete category",
            ],
        },
        title="Delete Collection",
    )
    collection_id: str = Field(
        ..., title="Collection ID", description="The ID of the collection to delete"
    )


class ShopifyAddProductToCollectionConfig(BaseModel):
    """Add a product to a collection"""

    operation: Literal["add_product_to_collection"] = Field(
        "add_product_to_collection",
        json_schema_extra={
            "const": "add_product_to_collection",
            "ui:hidden": True,
            "x-category": "Product",
            "x-is-trigger": False,
            "x-display-name": "Add Product to Collection",
            "x-keywords": [
                "add to collection",
                "put product in collection",
                "assign product collection",
                "categorize product",
            ],
        },
        title="Add Product to Collection",
    )
    collection_id: str = Field(
        ..., title="Collection ID", description="The ID of the collection"
    )
    product_id: str = Field(
        ..., title="Product ID", description="The ID of the product to add"
    )


# ============================================================================
# Location Operation Configs
# ============================================================================


class ShopifyListLocationsConfig(BaseModel):
    """List all locations"""

    operation: Literal["list_all_locations"] = Field(
        "list_all_locations",
        json_schema_extra={
            "const": "list_all_locations",
            "ui:hidden": True,
            "x-category": "Location",
            "x-is-trigger": False,
            "x-display-name": "List All Locations",
            "x-keywords": [
                "store locations",
                "warehouse list",
                "fulfillment locations",
            ],
        },
        title="List All Locations",
    )


class ShopifyGetLocationConfig(BaseModel):
    """Get a single location"""

    operation: Literal["get_location_by_id"] = Field(
        "get_location_by_id",
        json_schema_extra={
            "const": "get_location_by_id",
            "ui:hidden": True,
            "x-category": "Location",
            "x-is-trigger": False,
            "x-display-name": "Get Location by Id",
            "x-keywords": ["location details", "single location", "warehouse info"],
        },
        title="Get Location by Id",
    )
    location_id: str = Field(
        ..., title="Location ID", description="The ID of the location"
    )


# ============================================================================
# Shop Operation Configs
# ============================================================================


class ShopifyGetShopConfig(BaseModel):
    """Get shop information"""

    operation: Literal["get_shop_information"] = Field(
        "get_shop_information",
        json_schema_extra={
            "const": "get_shop_information",
            "ui:hidden": True,
            "x-category": "Shop",
            "x-is-trigger": False,
            "x-display-name": "Get Shop Information",
            "x-keywords": [
                "store info",
                "shop details",
                "store settings",
                "shop profile",
            ],
        },
        title="Get Shop Information",
    )


# ============================================================================
# Metafield Operation Configs
# ============================================================================


class ShopifyListMetafieldsConfig(BaseModel):
    """List metafields for a resource"""

    operation: Literal["list_metafields"] = Field(
        "list_metafields",
        json_schema_extra={
            "const": "list_metafields",
            "ui:hidden": True,
            "x-category": "Metafield",
            "x-is-trigger": False,
            "x-display-name": "List Metafields",
            "x-keywords": ["custom fields", "metadata list", "extra fields"],
        },
        title="List Metafields",
    )
    resource: str = Field(
        ...,
        title="Resource Type",
        description="Resource type (product, variant, customer, order, etc.)",
    )
    resource_id: Optional[str] = Field(
        None,
        title="Resource ID",
        description="ID of the resource (omit for shop-level metafields)",
    )


class ShopifyGetMetafieldConfig(BaseModel):
    """Get a single metafield"""

    operation: Literal["get_metafield_by_id"] = Field(
        "get_metafield_by_id",
        json_schema_extra={
            "const": "get_metafield_by_id",
            "ui:hidden": True,
            "x-category": "Metafield",
            "x-is-trigger": False,
            "x-display-name": "Get Metafield by Id",
            "x-keywords": ["metafield details", "single custom field"],
        },
        title="Get Metafield by Id",
    )
    metafield_id: str = Field(
        ..., title="Metafield ID", description="The ID of the metafield"
    )


class ShopifyCreateMetafieldConfig(BaseModel):
    """Create a metafield"""

    operation: Literal["create_metafield"] = Field(
        "create_metafield",
        json_schema_extra={
            "const": "create_metafield",
            "ui:hidden": True,
            "x-category": "Metafield",
            "x-is-trigger": False,
            "x-display-name": "Create Metafield",
            "x-keywords": ["new metafield", "add custom field", "add metadata"],
        },
        title="Create Metafield",
    )
    resource: str = Field(
        ...,
        title="Resource Type",
        description="Resource type (product, variant, customer, order, etc.)",
    )
    resource_id: Optional[str] = Field(
        None,
        title="Resource ID",
        description="ID of the resource (omit for shop-level metafields)",
    )
    namespace: str = Field(
        ..., title="Namespace", description="Container for a set of metafields"
    )
    key: str = Field(..., title="Key", description="Unique identifier within namespace")
    value: str = Field(..., title="Value", description="Metafield value")
    type: str = Field(
        ...,
        title="Type",
        description="Value type (single_line_text_field, integer, json_string, etc.)",
    )


class ShopifyUpdateMetafieldConfig(BaseModel):
    """Update a metafield"""

    operation: Literal["update_metafield"] = Field(
        "update_metafield",
        json_schema_extra={
            "const": "update_metafield",
            "ui:hidden": True,
            "x-category": "Metafield",
            "x-is-trigger": False,
            "x-display-name": "Update Metafield",
            "x-keywords": ["edit metafield", "change custom field", "modify metadata"],
        },
        title="Update Metafield",
    )
    metafield_id: str = Field(
        ..., title="Metafield ID", description="The ID of the metafield"
    )
    value: str = Field(..., title="Value", description="New metafield value")
    type: Optional[str] = Field(
        None,
        title="Type",
        description="Value type (single_line_text_field, integer, json_string, etc.)",
    )


class ShopifyDeleteMetafieldConfig(BaseModel):
    """Delete a metafield"""

    operation: Literal["delete_metafield"] = Field(
        "delete_metafield",
        json_schema_extra={
            "const": "delete_metafield",
            "ui:hidden": True,
            "x-category": "Metafield",
            "x-is-trigger": False,
            "x-display-name": "Delete Metafield",
            "x-keywords": [
                "remove metafield",
                "delete custom field",
                "remove metadata",
            ],
        },
        title="Delete Metafield",
    )
    metafield_id: str = Field(
        ..., title="Metafield ID", description="The ID of the metafield to delete"
    )


# ============================================================================
# Webhook Operation Configs
# ============================================================================


class ShopifyListWebhooksConfig(BaseModel):
    """List webhooks"""

    operation: Literal["list_webhooks"] = Field(
        "list_webhooks",
        json_schema_extra={
            "const": "list_webhooks",
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "List Webhooks",
            "x-keywords": ["event subscriptions", "registered hooks", "list webhooks"],
        },
        title="List Webhooks",
    )


class ShopifyGetWebhookConfig(BaseModel):
    """Get a single webhook"""

    operation: Literal["get_webhook_by_id"] = Field(
        "get_webhook_by_id",
        json_schema_extra={
            "const": "get_webhook_by_id",
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Get Webhook by Id",
            "x-keywords": ["webhook details", "single webhook"],
        },
        title="Get Webhook by Id",
    )
    webhook_id: str = Field(
        ..., title="Webhook ID", description="The ID of the webhook"
    )


class ShopifyCreateWebhookConfig(BaseModel):
    """Create a webhook"""

    operation: Literal["create_webhook"] = Field(
        "create_webhook",
        json_schema_extra={
            "const": "create_webhook",
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Create Webhook",
            "x-keywords": ["new webhook", "subscribe event", "register hook"],
        },
        title="Create Webhook",
    )
    topic: str = Field(
        ...,
        title="Topic",
        description="Event topic (e.g., orders/create, products/update)",
    )
    address: str = Field(
        ..., title="Address", description="URL where webhook will send data"
    )
    format: Optional[str] = Field(
        "json",
        title="Format",
        description="Data format",
        json_schema_extra={"enum": ["json", "xml"]},
    )


class ShopifyUpdateWebhookConfig(BaseModel):
    """Update a webhook"""

    operation: Literal["update_webhook"] = Field(
        "update_webhook",
        json_schema_extra={
            "const": "update_webhook",
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Update Webhook",
            "x-keywords": ["edit webhook", "change webhook endpoint"],
        },
        title="Update Webhook",
    )
    webhook_id: str = Field(
        ..., title="Webhook ID", description="The ID of the webhook"
    )
    address: Optional[str] = Field(
        None, title="Address", description="URL where webhook will send data"
    )
    topic: Optional[str] = Field(None, title="Topic", description="Event topic")


class ShopifyDeleteWebhookConfig(BaseModel):
    """Delete a webhook"""

    operation: Literal["delete_webhook"] = Field(
        "delete_webhook",
        json_schema_extra={
            "const": "delete_webhook",
            "ui:hidden": True,
            "x-category": "Webhook",
            "x-is-trigger": False,
            "x-display-name": "Delete Webhook",
            "x-keywords": ["remove webhook", "unsubscribe event", "delete hook"],
        },
        title="Delete Webhook",
    )
    webhook_id: str = Field(
        ..., title="Webhook ID", description="The ID of the webhook to delete"
    )


# ============================================================================
# Price Rule / Discount Operation Configs
# ============================================================================


class ShopifyListPriceRulesConfig(BaseModel):
    """List price rules"""

    operation: Literal["list_price_rules"] = Field(
        "list_price_rules",
        json_schema_extra={
            "const": "list_price_rules",
            "ui:hidden": True,
            "x-category": "Price Rule",
            "x-is-trigger": False,
            "x-display-name": "List Price Rules",
            "x-keywords": ["discount rules", "promotions list", "list price rules"],
        },
        title="List Price Rules",
    )
    limit: Optional[int] = Field(
        50,
        title="Limit",
        description="Number of price rules to return (max 250)",
        ge=1,
        le=250,
    )


class ShopifyGetPriceRuleConfig(BaseModel):
    """Get a single price rule"""

    operation: Literal["get_price_rule_by_id"] = Field(
        "get_price_rule_by_id",
        json_schema_extra={
            "const": "get_price_rule_by_id",
            "ui:hidden": True,
            "x-category": "Price Rule",
            "x-is-trigger": False,
            "x-display-name": "Get Price Rule by Id",
            "x-keywords": ["price rule details", "single discount rule"],
        },
        title="Get Price Rule by Id",
    )
    price_rule_id: str = Field(
        ..., title="Price Rule ID", description="The ID of the price rule"
    )


class ShopifyCreatePriceRuleConfig(BaseModel):
    """Create a price rule"""

    operation: Literal["create_price_rule"] = Field(
        "create_price_rule",
        json_schema_extra={
            "const": "create_price_rule",
            "ui:hidden": True,
            "x-category": "Price Rule",
            "x-is-trigger": False,
            "x-display-name": "Create Price Rule",
            "x-keywords": ["new price rule", "add discount rule", "create promotion"],
        },
        title="Create Price Rule",
    )
    title: str = Field(..., title="Title", description="Price rule title")
    target_type: str = Field(
        ...,
        title="Target Type",
        description="What the discount applies to",
        json_schema_extra={"enum": ["line_item", "shipping_line"]},
    )
    target_selection: str = Field(
        ...,
        title="Target Selection",
        description="Which items are discounted",
        json_schema_extra={"enum": ["all", "entitled"]},
    )
    allocation_method: str = Field(
        ...,
        title="Allocation Method",
        description="How discount is distributed",
        json_schema_extra={"enum": ["across", "each"]},
    )
    value_type: str = Field(
        ...,
        title="Value Type",
        description="Type of discount",
        json_schema_extra={"enum": ["fixed_amount", "percentage"]},
    )
    value: str = Field(
        ...,
        title="Value",
        description="Discount value (e.g., -10.0 for $10 off or -15.0 for 15% off)",
    )
    customer_selection: str = Field(
        ...,
        title="Customer Selection",
        description="Which customers can use this",
        json_schema_extra={"enum": ["all", "prerequisite"]},
    )
    starts_at: Optional[str] = Field(
        None,
        title="Starts At",
        description="When the price rule becomes active (ISO 8601)",
    )
    ends_at: Optional[str] = Field(
        None, title="Ends At", description="When the price rule expires (ISO 8601)"
    )


class ShopifyUpdatePriceRuleConfig(BaseModel):
    """Update a price rule"""

    operation: Literal["update_price_rule"] = Field(
        "update_price_rule",
        json_schema_extra={
            "const": "update_price_rule",
            "ui:hidden": True,
            "x-category": "Price Rule",
            "x-is-trigger": False,
            "x-display-name": "Update Price Rule",
            "x-keywords": ["edit price rule", "change discount rule"],
        },
        title="Update Price Rule",
    )
    price_rule_id: str = Field(
        ..., title="Price Rule ID", description="The ID of the price rule"
    )
    title: Optional[str] = Field(None, title="Title", description="Price rule title")
    value: Optional[str] = Field(None, title="Value", description="Discount value")
    starts_at: Optional[str] = Field(
        None,
        title="Starts At",
        description="When the price rule becomes active (ISO 8601)",
    )
    ends_at: Optional[str] = Field(
        None, title="Ends At", description="When the price rule expires (ISO 8601)"
    )


class ShopifyDeletePriceRuleConfig(BaseModel):
    """Delete a price rule"""

    operation: Literal["delete_price_rule"] = Field(
        "delete_price_rule",
        json_schema_extra={
            "const": "delete_price_rule",
            "ui:hidden": True,
            "x-category": "Price Rule",
            "x-is-trigger": False,
            "x-display-name": "Delete Price Rule",
            "x-keywords": ["remove price rule", "delete discount rule"],
        },
        title="Delete Price Rule",
    )
    price_rule_id: str = Field(
        ..., title="Price Rule ID", description="The ID of the price rule to delete"
    )


class ShopifyListDiscountCodesConfig(BaseModel):
    """List discount codes for a price rule"""

    operation: Literal["list_discount_codes"] = Field(
        "list_discount_codes",
        json_schema_extra={
            "const": "list_discount_codes",
            "ui:hidden": True,
            "x-category": "Discount Code",
            "x-is-trigger": False,
            "x-display-name": "List Discount Codes",
            "x-keywords": ["coupon codes", "promo codes", "list discount codes"],
        },
        title="List Discount Codes",
    )
    price_rule_id: str = Field(
        ..., title="Price Rule ID", description="The ID of the price rule"
    )


class ShopifyCreateDiscountCodeConfig(BaseModel):
    """Create a discount code for a price rule"""

    operation: Literal["create_discount_code"] = Field(
        "create_discount_code",
        json_schema_extra={
            "const": "create_discount_code",
            "ui:hidden": True,
            "x-category": "Discount Code",
            "x-is-trigger": False,
            "x-display-name": "Create Discount Code",
            "x-keywords": ["new discount code", "add coupon", "create promo code"],
        },
        title="Create Discount Code",
    )
    price_rule_id: str = Field(
        ..., title="Price Rule ID", description="The ID of the price rule"
    )
    code: str = Field(..., title="Code", description="The discount code")


class ShopifyDeleteDiscountCodeConfig(BaseModel):
    """Delete a discount code"""

    operation: Literal["delete_discount_code"] = Field(
        "delete_discount_code",
        json_schema_extra={
            "const": "delete_discount_code",
            "ui:hidden": True,
            "x-category": "Discount Code",
            "x-is-trigger": False,
            "x-display-name": "Delete Discount Code",
            "x-keywords": [
                "remove discount code",
                "delete coupon",
                "remove promo code",
            ],
        },
        title="Delete Discount Code",
    )
    price_rule_id: str = Field(
        ..., title="Price Rule ID", description="The ID of the price rule"
    )
    discount_code_id: str = Field(
        ...,
        title="Discount Code ID",
        description="The ID of the discount code to delete",
    )


# ============================================================================
# Gift Card Operation Configs
# ============================================================================


class ShopifyListGiftCardsConfig(BaseModel):
    """List gift cards"""

    operation: Literal["list_gift_cards"] = Field(
        "list_gift_cards",
        json_schema_extra={
            "const": "list_gift_cards",
            "ui:hidden": True,
            "x-category": "Gift Card",
            "x-is-trigger": False,
            "x-display-name": "List Gift Cards",
            "x-keywords": ["gift card list", "store credit", "list gift cards"],
        },
        title="List Gift Cards",
    )
    limit: Optional[int] = Field(
        50,
        title="Limit",
        description="Number of gift cards to return (max 250)",
        ge=1,
        le=250,
    )
    status: Optional[str] = Field(
        None,
        title="Status",
        description="Filter by status",
        json_schema_extra={"enum": ["enabled", "disabled"]},
    )


class ShopifyGetGiftCardConfig(BaseModel):
    """Get a single gift card"""

    operation: Literal["get_gift_card_by_id"] = Field(
        "get_gift_card_by_id",
        json_schema_extra={
            "const": "get_gift_card_by_id",
            "ui:hidden": True,
            "x-category": "Gift Card",
            "x-is-trigger": False,
            "x-display-name": "Get Gift Card by Id",
            "x-keywords": ["gift card details", "single gift card"],
        },
        title="Get Gift Card by Id",
    )
    gift_card_id: str = Field(
        ..., title="Gift Card ID", description="The ID of the gift card"
    )


class ShopifyCreateGiftCardConfig(BaseModel):
    """Create a gift card"""

    operation: Literal["create_gift_card"] = Field(
        "create_gift_card",
        json_schema_extra={
            "const": "create_gift_card",
            "ui:hidden": True,
            "x-category": "Gift Card",
            "x-is-trigger": False,
            "x-display-name": "Create Gift Card",
            "x-keywords": ["new gift card", "issue gift card", "add store credit"],
        },
        title="Create Gift Card",
    )
    initial_value: str = Field(
        ..., title="Initial Value", description="Initial balance (e.g., 25.00)"
    )
    code: Optional[str] = Field(
        None,
        title="Code",
        description="Gift card code (auto-generated if not provided)",
    )
    note: Optional[str] = Field(
        None,
        title="Note",
        description="Note about the gift card",
        json_schema_extra={"ui:widget": "textarea"},
    )


class ShopifyUpdateGiftCardConfig(BaseModel):
    """Update a gift card"""

    operation: Literal["update_gift_card"] = Field(
        "update_gift_card",
        json_schema_extra={
            "const": "update_gift_card",
            "ui:hidden": True,
            "x-category": "Gift Card",
            "x-is-trigger": False,
            "x-display-name": "Update Gift Card",
            "x-keywords": ["edit gift card", "change gift card"],
        },
        title="Update Gift Card",
    )
    gift_card_id: str = Field(
        ..., title="Gift Card ID", description="The ID of the gift card"
    )
    note: Optional[str] = Field(
        None,
        title="Note",
        description="Note about the gift card",
        json_schema_extra={"ui:widget": "textarea"},
    )
    expires_on: Optional[str] = Field(
        None, title="Expires On", description="Expiry date (ISO 8601)"
    )


class ShopifyDisableGiftCardConfig(BaseModel):
    """Disable a gift card"""

    operation: Literal["disable_gift_card"] = Field(
        "disable_gift_card",
        json_schema_extra={
            "const": "disable_gift_card",
            "ui:hidden": True,
            "x-category": "Gift Card",
            "x-is-trigger": False,
            "x-display-name": "Disable Gift Card",
            "x-keywords": [
                "deactivate gift card",
                "cancel gift card",
                "void gift card",
            ],
        },
        title="Disable Gift Card",
    )
    gift_card_id: str = Field(
        ..., title="Gift Card ID", description="The ID of the gift card to disable"
    )


# ============================================================================
# GraphQL Operation Configs
# ============================================================================


class ShopifyGraphQLQueryConfig(BaseModel):
    """Execute a custom GraphQL query (provides 100% API coverage)"""

    operation: Literal["execute_custom_graphql_query"] = Field(
        "execute_custom_graphql_query",
        json_schema_extra={
            "const": "execute_custom_graphql_query",
            "ui:hidden": True,
            "x-category": "GraphQL",
            "x-is-trigger": False,
            "x-display-name": "Execute Custom Graphql Query",
            "x-keywords": [
                "graphql query",
                "custom query",
                "raw graphql read",
                "gql query",
            ],
        },
        title="Execute Custom Graphql Query",
    )
    query: str = Field(
        ...,
        title="GraphQL Query",
        description="GraphQL query string (supports any Shopify GraphQL Admin API query)",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 10},
    )
    variables: Optional[Dict[str, Any]] = Field(
        None, title="Variables", description="GraphQL variables as JSON object"
    )


class ShopifyGraphQLMutationConfig(BaseModel):
    """Execute a custom GraphQL mutation (provides 100% API coverage)"""

    operation: Literal["execute_custom_graphql_mutation"] = Field(
        "execute_custom_graphql_mutation",
        json_schema_extra={
            "const": "execute_custom_graphql_mutation",
            "ui:hidden": True,
            "x-category": "GraphQL",
            "x-is-trigger": False,
            "x-display-name": "Execute Custom Graphql Mutation",
            "x-keywords": [
                "graphql mutation",
                "custom mutation",
                "raw graphql write",
                "gql mutation",
            ],
        },
        title="Execute Custom Graphql Mutation",
    )
    mutation: str = Field(
        ...,
        title="GraphQL Mutation",
        description="GraphQL mutation string (supports any Shopify GraphQL Admin API mutation)",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 10},
    )
    variables: Optional[Dict[str, Any]] = Field(
        None, title="Variables", description="GraphQL variables as JSON object"
    )


# Pre-built GraphQL operations for common use cases


class ShopifyGraphQLProductsQueryConfig(BaseModel):
    """Query products using GraphQL (more powerful than REST)"""

    operation: Literal["query_products_with_graphql"] = Field(
        "query_products_with_graphql",
        json_schema_extra={
            "const": "query_products_with_graphql",
            "ui:hidden": True,
            "x-category": "Product",
            "x-is-trigger": False,
            "x-display-name": "Query Products with Graphql",
            "x-keywords": [
                "graphql products",
                "products gql",
                "advanced product query",
            ],
        },
        title="Query Products with Graphql",
    )
    first: Optional[int] = Field(
        50,
        title="Number of Products",
        description="Number of products to return (max 250)",
        ge=1,
        le=250,
    )
    query_filter: Optional[str] = Field(
        None,
        title="Search Query",
        description="Search query (e.g., 'title:shoes' or 'vendor:Nike')",
    )
    after: Optional[str] = Field(
        None, title="After Cursor", description="Pagination cursor for next page"
    )


class ShopifyGraphQLProductCreateConfig(BaseModel):
    """Create a product using GraphQL"""

    operation: Literal["create_product_with_graphql"] = Field(
        "create_product_with_graphql",
        json_schema_extra={
            "const": "create_product_with_graphql",
            "ui:hidden": True,
            "x-category": "Product",
            "x-is-trigger": False,
            "x-display-name": "Create Product with Graphql",
            "x-keywords": ["graphql create product", "new product gql"],
        },
        title="Create Product with Graphql",
    )
    title: str = Field(..., title="Product Title", description="Product title")
    description_html: Optional[str] = Field(
        None,
        title="Description (HTML)",
        description="Product description in HTML",
        json_schema_extra={"ui:widget": "textarea"},
    )
    vendor: Optional[str] = Field(None, title="Vendor", description="Product vendor")
    product_type: Optional[str] = Field(
        None, title="Product Type", description="Product type/category"
    )
    tags: Optional[List[str]] = Field(None, title="Tags", description="Array of tags")
    status: Optional[str] = Field(
        "DRAFT",
        title="Status",
        description="Product status",
        json_schema_extra={"enum": ["ACTIVE", "ARCHIVED", "DRAFT"]},
    )


class ShopifyGraphQLProductUpdateConfig(BaseModel):
    """Update a product using GraphQL"""

    operation: Literal["update_product_with_graphql"] = Field(
        "update_product_with_graphql",
        json_schema_extra={
            "const": "update_product_with_graphql",
            "ui:hidden": True,
            "x-category": "Product",
            "x-is-trigger": False,
            "x-display-name": "Update Product with Graphql",
            "x-keywords": ["graphql update product", "edit product gql"],
        },
        title="Update Product with Graphql",
    )
    product_id: str = Field(
        ...,
        title="Product ID",
        description="GraphQL global ID of the product (gid://shopify/Product/...)",
    )
    title: Optional[str] = Field(
        None, title="Product Title", description="Product title"
    )
    description_html: Optional[str] = Field(
        None,
        title="Description (HTML)",
        description="Product description in HTML",
        json_schema_extra={"ui:widget": "textarea"},
    )
    vendor: Optional[str] = Field(None, title="Vendor", description="Product vendor")
    product_type: Optional[str] = Field(
        None, title="Product Type", description="Product type/category"
    )
    tags: Optional[List[str]] = Field(None, title="Tags", description="Array of tags")
    status: Optional[str] = Field(
        None,
        title="Status",
        description="Product status",
        json_schema_extra={"enum": ["ACTIVE", "ARCHIVED", "DRAFT"]},
    )


class ShopifyGraphQLOrdersQueryConfig(BaseModel):
    """Query orders using GraphQL"""

    operation: Literal["query_orders_with_graphql"] = Field(
        "query_orders_with_graphql",
        json_schema_extra={
            "const": "query_orders_with_graphql",
            "ui:hidden": True,
            "x-category": "Order",
            "x-is-trigger": False,
            "x-display-name": "Query Orders with Graphql",
            "x-keywords": ["graphql orders", "orders gql", "advanced order query"],
        },
        title="Query Orders with Graphql",
    )
    first: Optional[int] = Field(
        50,
        title="Number of Orders",
        description="Number of orders to return (max 250)",
        ge=1,
        le=250,
    )
    query_filter: Optional[str] = Field(
        None,
        title="Search Query",
        description="Search query (e.g., 'status:OPEN' or 'email:customer@example.com')",
    )
    after: Optional[str] = Field(
        None, title="After Cursor", description="Pagination cursor for next page"
    )


class ShopifyGraphQLDraftOrderCreateConfig(BaseModel):
    """Create a draft order using GraphQL"""

    operation: Literal["create_draft_order_with_graphql"] = Field(
        "create_draft_order_with_graphql",
        json_schema_extra={
            "const": "create_draft_order_with_graphql",
            "ui:hidden": True,
            "x-category": "GraphQL",
            "x-is-trigger": False,
            "x-display-name": "Create Draft Order with Graphql",
            "x-keywords": ["draft order", "graphql draft order", "new draft order"],
        },
        title="Create Draft Order with Graphql",
    )
    line_items: List[Dict[str, Any]] = Field(
        ...,
        title="Line Items",
        description="Array of line items [{variantId, quantity}]",
    )
    customer_id: Optional[str] = Field(
        None, title="Customer ID", description="GraphQL global ID of the customer"
    )
    email: Optional[str] = Field(
        None, title="Customer Email", description="Customer email address"
    )
    shipping_address: Optional[Dict[str, Any]] = Field(
        None, title="Shipping Address", description="Shipping address object"
    )
    note: Optional[str] = Field(
        None, title="Note", description="Note for the draft order"
    )


class ShopifyGraphQLCustomersQueryConfig(BaseModel):
    """Query customers using GraphQL"""

    operation: Literal["query_customers_with_graphql"] = Field(
        "query_customers_with_graphql",
        json_schema_extra={
            "const": "query_customers_with_graphql",
            "ui:hidden": True,
            "x-category": "Customer",
            "x-is-trigger": False,
            "x-display-name": "Query Customers with Graphql",
            "x-keywords": [
                "graphql customers",
                "customers gql",
                "advanced customer query",
            ],
        },
        title="Query Customers with Graphql",
    )
    first: Optional[int] = Field(
        50,
        title="Number of Customers",
        description="Number of customers to return (max 250)",
        ge=1,
        le=250,
    )
    query_filter: Optional[str] = Field(
        None,
        title="Search Query",
        description="Search query (e.g., 'email:customer@example.com' or 'tag:VIP')",
    )
    after: Optional[str] = Field(
        None, title="After Cursor", description="Pagination cursor for next page"
    )


class ShopifyGraphQLCustomerCreateConfig(BaseModel):
    """Create a customer using GraphQL"""

    operation: Literal["create_customer_with_graphql"] = Field(
        "create_customer_with_graphql",
        json_schema_extra={
            "const": "create_customer_with_graphql",
            "ui:hidden": True,
            "x-category": "Customer",
            "x-is-trigger": False,
            "x-display-name": "Create Customer with Graphql",
            "x-keywords": [
                "graphql customer",
                "customer mutation",
                "gql add customer",
                "new shopper graphql",
            ],
        },
        title="Create Customer with Graphql",
    )
    email: Optional[str] = Field(
        None, title="Email", description="Customer email address"
    )
    phone: Optional[str] = Field(
        None, title="Phone", description="Customer phone number"
    )
    first_name: Optional[str] = Field(
        None, title="First Name", description="Customer first name"
    )
    last_name: Optional[str] = Field(
        None, title="Last Name", description="Customer last name"
    )
    tags: Optional[List[str]] = Field(
        None, title="Tags", description="Array of customer tags"
    )
    note: Optional[str] = Field(
        None, title="Note", description="Note about the customer"
    )


class ShopifyGraphQLInventoryQueryConfig(BaseModel):
    """Query inventory levels using GraphQL"""

    operation: Literal["query_inventory_with_graphql"] = Field(
        "query_inventory_with_graphql",
        json_schema_extra={
            "const": "query_inventory_with_graphql",
            "ui:hidden": True,
            "x-category": "Inventory",
            "x-is-trigger": False,
            "x-display-name": "Query Inventory with Graphql",
            "x-keywords": [
                "graphql inventory",
                "inventory query",
                "stock levels graphql",
                "gql on hand",
            ],
        },
        title="Query Inventory with Graphql",
    )
    location_id: Optional[str] = Field(
        None, title="Location ID", description="GraphQL global ID of the location"
    )
    product_id: Optional[str] = Field(
        None, title="Product ID", description="GraphQL global ID of the product"
    )
    first: Optional[int] = Field(
        50,
        title="Number of Items",
        description="Number of inventory items to return",
        ge=1,
        le=250,
    )


class ShopifyGraphQLCollectionsQueryConfig(BaseModel):
    """Query collections using GraphQL"""

    operation: Literal["query_collections_with_graphql"] = Field(
        "query_collections_with_graphql",
        json_schema_extra={
            "const": "query_collections_with_graphql",
            "ui:hidden": True,
            "x-category": "Collection",
            "x-is-trigger": False,
            "x-display-name": "Query Collections with Graphql",
            "x-keywords": [
                "graphql collections",
                "collection query",
                "gql collections",
                "smart collection graphql",
                "catalog graphql",
            ],
        },
        title="Query Collections with Graphql",
    )
    first: Optional[int] = Field(
        50,
        title="Number of Collections",
        description="Number of collections to return (max 250)",
        ge=1,
        le=250,
    )
    query_filter: Optional[str] = Field(
        None, title="Search Query", description="Search query (e.g., 'title:sale')"
    )
    after: Optional[str] = Field(
        None, title="After Cursor", description="Pagination cursor for next page"
    )


class ShopifyGraphQLFulfillmentOrdersQueryConfig(BaseModel):
    """Query fulfillment orders using GraphQL"""

    operation: Literal["query_fulfillment_orders_with_graphql"] = Field(
        "query_fulfillment_orders_with_graphql",
        json_schema_extra={
            "const": "query_fulfillment_orders_with_graphql",
            "ui:hidden": True,
            "x-category": "Fulfillment",
            "x-is-trigger": False,
            "x-display-name": "Query Fulfillment Orders with Graphql",
            "x-keywords": [
                "graphql fulfillment orders",
                "fulfillment order query",
                "gql fulfillments",
                "shipment orders graphql",
                "pick pack graphql",
            ],
        },
        title="Query Fulfillment Orders with Graphql",
    )
    order_id: Optional[str] = Field(
        None, title="Order ID", description="GraphQL global ID of the order"
    )
    first: Optional[int] = Field(
        50,
        title="Number of Fulfillment Orders",
        description="Number to return (max 250)",
        ge=1,
        le=250,
    )


class ShopifyGraphQLShopQueryConfig(BaseModel):
    """Get shop information using GraphQL"""

    operation: Literal["get_shop_with_graphql"] = Field(
        "get_shop_with_graphql",
        json_schema_extra={
            "const": "get_shop_with_graphql",
            "ui:hidden": True,
            "x-category": "Shop",
            "x-is-trigger": False,
            "x-display-name": "Get Shop with Graphql",
            "x-keywords": [
                "graphql shop info",
                "store details graphql",
                "gql shop",
                "shop settings graphql",
                "merchant graphql",
            ],
        },
        title="Get Shop with Graphql",
    )


# ============================================================================
# Trigger operation config
# ============================================================================


def _shopify_trigger_field(value: str, display: str, keywords: Optional[list] = None):
    """Build the hidden `operation` discriminator Field for a Shopify trigger."""
    extra = {
        "const": value,
        "ui:hidden": True,
        "x-category": None,
        "x-is-trigger": True,
        "x-display-name": display,
    }
    if keywords:
        extra["x-keywords"] = keywords
    return Field(value, json_schema_extra=extra, title=display)


class _ShopifyEventTriggerBase(BaseModel):
    """Shared fields for Shopify per-event triggers.

    Each per-event trigger op is a separate operation (On Order Created, etc.)
    so the user picks the specific trigger rather than a generic topic field;
    the Shopify topic is resolved from the operation via ``_trigger_event_map``.
    """

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    webhook_id: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:copyable": True,
            "ui:loadValue": True,
        },
    )
    signing_secret: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    external_webhook_id: Optional[int] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    relay_connected: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    is_production: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    trigger_registered: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    trigger_error: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )


class ShopifyOnOrderCreatedConfig(_ShopifyEventTriggerBase):
    """Trigger: fires when a new order is created in the store."""

    operation: Literal["on_order_created"] = _shopify_trigger_field(
        "on_order_created",
        "On Order Created",
        keywords=[
            "when new order",
            "on order placed",
            "new sale received",
            "incoming purchase",
            "order placed trigger",
        ],
    )


class ShopifyOnOrderPaidConfig(_ShopifyEventTriggerBase):
    """Trigger: fires when an order is paid."""

    operation: Literal["on_order_paid"] = _shopify_trigger_field(
        "on_order_paid",
        "On Order Paid",
        keywords=[
            "when order paid",
            "on payment received",
            "order payment captured",
            "checkout paid",
        ],
    )


class ShopifyOnOrderFulfilledConfig(_ShopifyEventTriggerBase):
    """Trigger: fires when an order is fulfilled."""

    operation: Literal["on_order_fulfilled"] = _shopify_trigger_field(
        "on_order_fulfilled",
        "On Order Fulfilled",
        keywords=[
            "when order fulfilled",
            "on order shipped",
            "order shipment trigger",
            "order marked fulfilled",
        ],
    )


class ShopifyOnOrderCancelledConfig(_ShopifyEventTriggerBase):
    """Trigger: fires when an order is cancelled."""

    operation: Literal["on_order_cancelled"] = _shopify_trigger_field(
        "on_order_cancelled",
        "On Order Cancelled",
        keywords=[
            "when order cancelled",
            "on order canceled",
            "order voided trigger",
            "cancelled sale",
        ],
    )


class ShopifyOnProductCreatedConfig(_ShopifyEventTriggerBase):
    """Trigger: fires when a new product is created in the store."""

    operation: Literal["on_product_created"] = _shopify_trigger_field(
        "on_product_created",
        "On Product Created",
        keywords=[
            "when new product",
            "on product added",
            "new item listed",
            "product added trigger",
        ],
    )


class ShopifyOnProductUpdatedConfig(_ShopifyEventTriggerBase):
    """Trigger: fires when a product is updated."""

    operation: Literal["on_product_updated"] = _shopify_trigger_field(
        "on_product_updated",
        "On Product Updated",
        keywords=[
            "when product changed",
            "on product edited",
            "product price changed",
            "product detail updated",
        ],
    )


class ShopifyOnCustomerCreatedConfig(_ShopifyEventTriggerBase):
    """Trigger: fires when a new customer is created in the store."""

    operation: Literal["on_customer_created"] = _shopify_trigger_field(
        "on_customer_created",
        "On Customer Created",
        keywords=[
            "when new customer",
            "on customer signup",
            "new shopper registered",
            "buyer created trigger",
        ],
    )


# ============================================================================
# Discriminated Union
# ============================================================================

class ShopifyListBlogsConfig(BaseModel):
    """List the store's blogs"""

    operation: Literal["list_blogs"] = Field(
        "list_blogs",
        json_schema_extra={
            "const": "list_blogs",
            "ui:hidden": True,
            "x-category": "Blog",
            "x-is-trigger": False,
            "x-display-name": "List Blogs",
            "x-keywords": ["store blogs", "blog list", "content blogs"],
        },
        title="List Blogs",
    )
    limit: Optional[int] = Field(
        50, title="Limit", description="Number of blogs to return (max 250)", ge=1, le=250
    )
    since_id: Optional[str] = Field(
        None, title="Since ID", description="Return blogs after this ID"
    )


class ShopifyListBlogArticlesConfig(BaseModel):
    """List articles in a blog"""

    operation: Literal["list_blog_articles"] = Field(
        "list_blog_articles",
        json_schema_extra={
            "const": "list_blog_articles",
            "ui:hidden": True,
            "x-category": "Blog",
            "x-is-trigger": False,
            "x-display-name": "List Blog Articles",
            "x-keywords": ["blog posts", "articles", "published posts", "blog content"],
        },
        title="List Blog Articles",
    )
    blog_id: str = Field(
        ..., title="Blog ID", description="ID of the blog (use List Blogs to find it)"
    )
    limit: Optional[int] = Field(
        50, title="Limit", description="Number of articles to return (max 250)", ge=1, le=250
    )
    since_id: Optional[str] = Field(
        None, title="Since ID", description="Return articles after this ID"
    )
    tag: Optional[str] = Field(None, title="Tag", description="Filter by tag")
    published_status: Optional[str] = Field(
        None,
        title="Published Status",
        description="Filter by publication state",
        json_schema_extra={"enum": ["published", "unpublished", "any"]},
    )


class ShopifyGetBlogArticleConfig(BaseModel):
    """Get a single blog article"""

    operation: Literal["get_blog_article_by_id"] = Field(
        "get_blog_article_by_id",
        json_schema_extra={
            "const": "get_blog_article_by_id",
            "ui:hidden": True,
            "x-category": "Blog",
            "x-is-trigger": False,
            "x-display-name": "Get Blog Article by Id",
            "x-keywords": ["single article", "blog post details", "read article"],
        },
        title="Get Blog Article by Id",
    )
    blog_id: str = Field(..., title="Blog ID", description="ID of the blog")
    article_id: str = Field(..., title="Article ID", description="ID of the article")


class ShopifyCreateBlogArticleConfig(BaseModel):
    """Create a blog article"""

    operation: Literal["create_blog_article"] = Field(
        "create_blog_article",
        json_schema_extra={
            "const": "create_blog_article",
            "ui:hidden": True,
            "x-category": "Blog",
            "x-is-trigger": False,
            "x-display-name": "Create Blog Article",
            "x-keywords": [
                "publish blog post",
                "write article",
                "post to blog",
                "new blog post",
            ],
        },
        title="Create Blog Article",
    )
    blog_id: str = Field(
        ..., title="Blog ID", description="ID of the blog (use List Blogs to find it)"
    )
    title: str = Field(..., title="Title", description="Article title")
    body_html: str = Field(
        ..., title="Body HTML", description="Full article body as HTML"
    )
    author: Optional[str] = Field(None, title="Author", description="Author name")
    tags: Optional[str] = Field(
        None, title="Tags", description="Comma-separated list of tags"
    )
    summary_html: Optional[str] = Field(
        None, title="Summary HTML", description="Excerpt shown on the blog index page"
    )
    published: str = Field(
        "true",
        title="Published",
        description="Publish immediately, or save as hidden draft",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Published", "Hidden"],
            "x-enum-searchable": True,
        },
    )
    image_src: Optional[str] = Field(
        None, title="Image URL", description="Featured image URL"
    )
    image_alt: Optional[str] = Field(
        None, title="Image Alt Text", description="Featured image alt text"
    )


class ShopifyUpdateBlogArticleConfig(BaseModel):
    """Update a blog article"""

    operation: Literal["update_blog_article"] = Field(
        "update_blog_article",
        json_schema_extra={
            "const": "update_blog_article",
            "ui:hidden": True,
            "x-category": "Blog",
            "x-is-trigger": False,
            "x-display-name": "Update Blog Article",
            "x-keywords": ["edit article", "revise blog post", "unpublish article"],
        },
        title="Update Blog Article",
    )
    blog_id: str = Field(..., title="Blog ID", description="ID of the blog")
    article_id: str = Field(..., title="Article ID", description="ID of the article")
    title: Optional[str] = Field(None, title="Title", description="New article title")
    body_html: Optional[str] = Field(
        None, title="Body HTML", description="New article body as HTML"
    )
    author: Optional[str] = Field(None, title="Author", description="Author name")
    tags: Optional[str] = Field(
        None, title="Tags", description="Comma-separated list of tags"
    )
    summary_html: Optional[str] = Field(
        None, title="Summary HTML", description="Excerpt shown on the blog index page"
    )
    published: Optional[str] = Field(
        None,
        title="Published",
        description="Change publication state (leave empty to keep current)",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Published", "Hidden"],
            "x-enum-searchable": True,
        },
    )
    image_src: Optional[str] = Field(
        None, title="Image URL", description="Featured image URL"
    )
    image_alt: Optional[str] = Field(
        None, title="Image Alt Text", description="Featured image alt text"
    )


class ShopifyDeleteBlogArticleConfig(BaseModel):
    """Delete a blog article"""

    operation: Literal["delete_blog_article"] = Field(
        "delete_blog_article",
        json_schema_extra={
            "const": "delete_blog_article",
            "ui:hidden": True,
            "x-category": "Blog",
            "x-is-trigger": False,
            "x-display-name": "Delete Blog Article",
            "x-keywords": ["remove article", "delete blog post"],
        },
        title="Delete Blog Article",
    )
    blog_id: str = Field(..., title="Blog ID", description="ID of the blog")
    article_id: str = Field(..., title="Article ID", description="ID of the article")


ShopifyConfig = Annotated[
    Union[
        # Trigger operations
        ShopifyOnOrderCreatedConfig,
        ShopifyOnOrderPaidConfig,
        ShopifyOnOrderFulfilledConfig,
        ShopifyOnOrderCancelledConfig,
        ShopifyOnProductCreatedConfig,
        ShopifyOnProductUpdatedConfig,
        ShopifyOnCustomerCreatedConfig,
        # Product operations (6)
        ShopifyListProductsConfig,
        ShopifyGetProductConfig,
        ShopifyCreateProductConfig,
        ShopifyUpdateProductConfig,
        ShopifyDeleteProductConfig,
        ShopifyCountProductsConfig,
        # Product Variant operations (6)
        ShopifyListProductVariantsConfig,
        ShopifyGetProductVariantConfig,
        ShopifyCreateProductVariantConfig,
        ShopifyUpdateProductVariantConfig,
        ShopifyDeleteProductVariantConfig,
        ShopifyCountProductVariantsConfig,
        # Product Image operations (4)
        ShopifyListProductImagesConfig,
        ShopifyGetProductImageConfig,
        ShopifyCreateProductImageConfig,
        ShopifyDeleteProductImageConfig,
        # Order operations (9)
        ShopifyListOrdersConfig,
        ShopifyGetOrderConfig,
        ShopifyCreateOrderConfig,
        ShopifyUpdateOrderConfig,
        ShopifyDeleteOrderConfig,
        ShopifyCancelOrderConfig,
        ShopifyCloseOrderConfig,
        ShopifyOpenOrderConfig,
        ShopifyCountOrdersConfig,
        # Refund operations (4)
        ShopifyListRefundsConfig,
        ShopifyGetRefundConfig,
        ShopifyCreateRefundConfig,
        ShopifyCalculateRefundConfig,
        # Transaction operations (4)
        ShopifyListTransactionsConfig,
        ShopifyGetTransactionConfig,
        ShopifyCreateTransactionConfig,
        ShopifyCountTransactionsConfig,
        # Customer operations (8)
        ShopifyListCustomersConfig,
        ShopifyGetCustomerConfig,
        ShopifyCreateCustomerConfig,
        ShopifyUpdateCustomerConfig,
        ShopifyDeleteCustomerConfig,
        ShopifySearchCustomersConfig,
        ShopifyCountCustomersConfig,
        ShopifyGetCustomerOrdersConfig,
        # Customer Address operations (6)
        ShopifyListCustomerAddressesConfig,
        ShopifyGetCustomerAddressConfig,
        ShopifyCreateCustomerAddressConfig,
        ShopifyUpdateCustomerAddressConfig,
        ShopifyDeleteCustomerAddressConfig,
        ShopifySetDefaultCustomerAddressConfig,
        # Inventory operations (5)
        ShopifyListInventoryLevelsConfig,
        ShopifyAdjustInventoryLevelConfig,
        ShopifySetInventoryLevelConfig,
        ShopifyConnectInventoryLevelConfig,
        ShopifyDeleteInventoryLevelConfig,
        # Fulfillment operations (6)
        ShopifyListFulfillmentsConfig,
        ShopifyGetFulfillmentConfig,
        ShopifyCreateFulfillmentConfig,
        ShopifyUpdateFulfillmentConfig,
        ShopifyCompleteFulfillmentConfig,
        ShopifyCancelFulfillmentConfig,
        # Collection operations (6)
        ShopifyListCollectionsConfig,
        ShopifyGetCollectionConfig,
        ShopifyCreateCollectionConfig,
        ShopifyUpdateCollectionConfig,
        ShopifyDeleteCollectionConfig,
        ShopifyAddProductToCollectionConfig,
        # Location operations (2)
        ShopifyListLocationsConfig,
        ShopifyGetLocationConfig,
        # Shop operations (1)
        ShopifyGetShopConfig,
        # Metafield operations (5)
        ShopifyListMetafieldsConfig,
        ShopifyGetMetafieldConfig,
        ShopifyCreateMetafieldConfig,
        ShopifyUpdateMetafieldConfig,
        ShopifyDeleteMetafieldConfig,
        # Webhook operations (5)
        ShopifyListWebhooksConfig,
        ShopifyGetWebhookConfig,
        ShopifyCreateWebhookConfig,
        ShopifyUpdateWebhookConfig,
        ShopifyDeleteWebhookConfig,
        # Price Rule / Discount operations (8)
        ShopifyListPriceRulesConfig,
        ShopifyGetPriceRuleConfig,
        ShopifyCreatePriceRuleConfig,
        ShopifyUpdatePriceRuleConfig,
        ShopifyDeletePriceRuleConfig,
        ShopifyListDiscountCodesConfig,
        ShopifyCreateDiscountCodeConfig,
        ShopifyDeleteDiscountCodeConfig,
        # Gift Card operations (5)
        ShopifyListGiftCardsConfig,
        ShopifyGetGiftCardConfig,
        ShopifyCreateGiftCardConfig,
        ShopifyUpdateGiftCardConfig,
        ShopifyDisableGiftCardConfig,
        # Blog operations (6)
        ShopifyListBlogsConfig,
        ShopifyListBlogArticlesConfig,
        ShopifyGetBlogArticleConfig,
        ShopifyCreateBlogArticleConfig,
        ShopifyUpdateBlogArticleConfig,
        ShopifyDeleteBlogArticleConfig,
        # GraphQL operations (13)
        ShopifyGraphQLQueryConfig,
        ShopifyGraphQLMutationConfig,
        ShopifyGraphQLProductsQueryConfig,
        ShopifyGraphQLProductCreateConfig,
        ShopifyGraphQLProductUpdateConfig,
        ShopifyGraphQLOrdersQueryConfig,
        ShopifyGraphQLDraftOrderCreateConfig,
        ShopifyGraphQLCustomersQueryConfig,
        ShopifyGraphQLCustomerCreateConfig,
        ShopifyGraphQLInventoryQueryConfig,
        ShopifyGraphQLCollectionsQueryConfig,
        ShopifyGraphQLFulfillmentOrdersQueryConfig,
        ShopifyGraphQLShopQueryConfig,
    ],
    Discriminator("operation"),
]


# ============================================================================
# Full Node Configuration
# ============================================================================


class ShopifyNodeConfig(NodeConfig[ShopifyConfig, ShopifyCredential]):
    """Full configuration for Shopify node including credentials"""

    pass


# ============================================================================
# Node Implementation
# ============================================================================


class ShopifyNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """
    Shopify Admin API automation node with REST and GraphQL support.

    Executes Shopify API operations for e-commerce workflow automation.

    **Total: 93 operations**
    - REST API (80 operations): Products, variants, images, orders, refunds, transactions, customers,
      addresses, inventory, fulfillments, collections, locations, shop, metafields, webhooks,
      price rules, discounts, gift cards
    - GraphQL API (13 operations): Generic query/mutation executors (100% API coverage) + pre-built
      operations for products, orders, customers, inventory, collections, and fulfillment orders

    **Authentication:** OAuth 2.0 or Admin API Access Token (supports custom OAuth apps)
    **API Versions:** REST (2024-01), GraphQL (2025-01)
    """

    edit_examples = [
        "List all products with SKU in inventory greater than 10",
        "Create new product with images, variants, and pricing",
        "Update order status to fulfilled and send customer notification",
        "Get all customers who made purchases over $500 last month",
        "Apply discount code to cart and calculate total with tax",
        "Manage inventory levels across 5 locations simultaneously",
        "Create fulfillment for order and track shipment status",
    ]

    scope_registry = SHOPIFY_SCOPES

    connection_evidence = ConnectionEvidence(
        operation="list_all_locations",
        noun="locations",
        identity_operation="get_shop_information",
    )

    _trigger_event_map = {
        "on_order_created": "orders/create",
        "on_order_paid": "orders/paid",
        "on_order_fulfilled": "orders/fulfilled",
        "on_order_cancelled": "orders/cancelled",
        "on_product_created": "products/create",
        "on_product_updated": "products/update",
        "on_customer_created": "customers/create",
    }

    @classmethod
    def get_config_model(cls):
        """Return the Pydantic model for node configuration."""
        return ShopifyNodeConfig

    # ========================================================================
    # Webhook Triggers (per-event)
    # ========================================================================

    async def _trigger_on_store_event(self, config, credentials) -> Dict[str, Any]:
        """Output when the trigger node is run manually from the editor.

        In a live workflow the node fires from a webhook delivery and outputs
        Shopify's event payload directly.
        """
        return {
            "message": (
                "This trigger fires when the subscribed store event occurs. "
                "It outputs the Shopify event payload."
            ),
            "topic": self._trigger_event_map.get(config.operation),
        }

    @classmethod
    async def _register_external_webhook(
        cls, *, webhook_url, credential, config, node_id
    ) -> Dict[str, Any]:
        topic = cls._trigger_event_map.get((config or {}).get("operation"))
        if not topic:
            raise ValueError("Set an event topic to activate this trigger")
        credential = credential or {}
        token = credential.get("access_token")
        store = credential.get("store_name")
        if not token or not store:
            raise ValueError(
                "Shopify credential is missing a store name or access token"
            )
        # Public-app OAuth credentials share the server-side app secret; custom
        # OAuth credentials retain their own encrypted secret on the credential.
        api_secret = credential.get("api_secret_key") or os.environ.get(
            "SHOPIFY_CLIENT_SECRET"
        )
        if not api_secret:
            raise ValueError(
                "Add the Shopify API secret key to your credential to verify "
                "webhook trigger signatures"
            )

        # Shopify's POST /webhooks is not idempotent — drop a stale webhook
        # from a previous registration before creating a fresh one.
        existing = (config or {}).get("external_webhook_id")
        if existing:
            try:
                await unregister_shopify_webhook(store, token, existing)
            except Exception as e:
                logger.warning(f"[ShopifyNode] Could not remove stale webhook: {e}")

        webhook_id = await register_shopify_webhook(store, token, topic, webhook_url)
        return {"signing_secret": api_secret, "external_webhook_id": webhook_id}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id) -> None:
        credential = credential or {}
        token = credential.get("access_token")
        store = credential.get("store_name")
        webhook_id = (config or {}).get("external_webhook_id")
        if not (token and store and webhook_id):
            return
        await unregister_shopify_webhook(store, token, webhook_id)

    @classmethod
    def verify_webhook_signature(
        cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]
    ) -> bool:
        """Verify Shopify's ``X-Shopify-Hmac-Sha256`` base64 HMAC header."""
        secret = (config or {}).get("signing_secret")
        if not secret:
            return False
        return verify_hmac_sha256_base64(
            body, secret, headers.get("x-shopify-hmac-sha256", "")
        )

    @classmethod
    async def freshen_credential(
        cls, credential_data, *, pool=None, user_id=None, credential_id=None
    ):
        """Refresh an expiring OAuth token at credential load (dropdowns,
        trigger registration). No-op for non-rotating credentials (API keys /
        offline / non-expiring tokens)."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.shopify_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data,
            pool=pool,
            user_id=user_id,
            credential_id=credential_id,
            refresh=refresh_access_token,
            provider="shopify",
        )

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the configured operation.

        Args:
            inputs: Output data from upstream nodes

        Returns:
            Dict with operation results including status, action, data, and timing
        """
        start_time = time.time()

        # Validate configuration
        config = self.config
        if not config or not isinstance(config, ShopifyNodeConfig):
            raise ValueError("Valid configuration is required")

        # Validate credentials
        credentials = config.credentials
        if not credentials:
            raise ValueError(
                "Credentials are required. Add your Shopify store name and access token."
            )

        # Get the specific operation config
        op_config = config.config

        # Route to appropriate handler based on action
        handlers = {
            # Trigger operations
            "on_order_created": self._trigger_on_store_event,
            "on_order_paid": self._trigger_on_store_event,
            "on_order_fulfilled": self._trigger_on_store_event,
            "on_order_cancelled": self._trigger_on_store_event,
            "on_product_created": self._trigger_on_store_event,
            "on_product_updated": self._trigger_on_store_event,
            "on_customer_created": self._trigger_on_store_event,
            # Product operations
            "list_products": self._handle_list_products,
            "get_product_by_id": self._handle_get_product,
            "create_product": self._handle_create_product,
            "update_product": self._handle_update_product,
            "delete_product": self._handle_delete_product,
            "count_products": self._handle_count_products,
            # Product Variant operations
            "list_product_variants": self._handle_list_product_variants,
            "get_product_variant_by_id": self._handle_get_product_variant,
            "create_product_variant": self._handle_create_product_variant,
            "update_product_variant": self._handle_update_product_variant,
            "delete_product_variant": self._handle_delete_product_variant,
            "count_product_variants": self._handle_count_product_variants,
            # Product Image operations
            "list_product_images": self._handle_list_product_images,
            "get_product_image_by_id": self._handle_get_product_image,
            "create_product_image": self._handle_create_product_image,
            "delete_product_image": self._handle_delete_product_image,
            # Order operations
            "list_orders": self._handle_list_orders,
            "get_order_by_id": self._handle_get_order,
            "create_order": self._handle_create_order,
            "update_order": self._handle_update_order,
            "delete_order": self._handle_delete_order,
            "cancel_order": self._handle_cancel_order,
            "close_order": self._handle_close_order,
            "reopen_closed_order": self._handle_open_order,
            "count_orders": self._handle_count_orders,
            # Refund operations
            "list_order_refunds": self._handle_list_refunds,
            "get_order_refund_by_id": self._handle_get_refund,
            "create_order_refund": self._handle_create_refund,
            "calculate_order_refund": self._handle_calculate_refund,
            # Transaction operations
            "list_order_transactions": self._handle_list_transactions,
            "get_order_transaction_by_id": self._handle_get_transaction,
            "create_order_transaction": self._handle_create_transaction,
            "count_order_transactions": self._handle_count_transactions,
            # Customer operations
            "list_customers": self._handle_list_customers,
            "get_customer_by_id": self._handle_get_customer,
            "create_customer": self._handle_create_customer,
            "update_customer": self._handle_update_customer,
            "delete_customer": self._handle_delete_customer,
            "search_customers": self._handle_search_customers,
            "count_customers": self._handle_count_customers,
            "get_customer_orders": self._handle_get_customer_orders,
            # Customer Address operations
            "list_customer_addresses": self._handle_list_customer_addresses,
            "get_customer_address_by_id": self._handle_get_customer_address,
            "create_customer_address": self._handle_create_customer_address,
            "update_customer_address": self._handle_update_customer_address,
            "delete_customer_address": self._handle_delete_customer_address,
            "set_default_customer_address": self._handle_set_default_customer_address,
            # Inventory operations
            "list_inventory_levels": self._handle_list_inventory_levels,
            "adjust_inventory_level_at_location": self._handle_adjust_inventory_level,
            "set_inventory_level_at_location": self._handle_set_inventory_level,
            "connect_inventory_item_to_location": self._handle_connect_inventory_level,
            "delete_inventory_level": self._handle_delete_inventory_level,
            # Fulfillment operations
            "list_order_fulfillments": self._handle_list_fulfillments,
            "get_order_fulfillment": self._handle_get_fulfillment,
            "create_order_fulfillment": self._handle_create_fulfillment,
            "update_order_fulfillment": self._handle_update_fulfillment,
            "complete_order_fulfillment": self._handle_complete_fulfillment,
            "cancel_order_fulfillment": self._handle_cancel_fulfillment,
            # Collection operations
            "list_collections": self._handle_list_collections,
            "get_collection_by_id": self._handle_get_collection,
            "create_collection": self._handle_create_collection,
            "update_collection": self._handle_update_collection,
            "delete_collection": self._handle_delete_collection,
            "add_product_to_collection": self._handle_add_product_to_collection,
            # Blog operations
            "list_blogs": self._handle_list_blogs,
            "list_blog_articles": self._handle_list_blog_articles,
            "get_blog_article_by_id": self._handle_get_blog_article,
            "create_blog_article": self._handle_create_blog_article,
            "update_blog_article": self._handle_update_blog_article,
            "delete_blog_article": self._handle_delete_blog_article,
            # Location operations
            "list_all_locations": self._handle_list_locations,
            "get_location_by_id": self._handle_get_location,
            # Shop operations
            "get_shop_information": self._handle_get_shop,
            # Metafield operations
            "list_metafields": self._handle_list_metafields,
            "get_metafield_by_id": self._handle_get_metafield,
            "create_metafield": self._handle_create_metafield,
            "update_metafield": self._handle_update_metafield,
            "delete_metafield": self._handle_delete_metafield,
            # Webhook operations
            "list_webhooks": self._handle_list_webhooks,
            "get_webhook_by_id": self._handle_get_webhook,
            "create_webhook": self._handle_create_webhook,
            "update_webhook": self._handle_update_webhook,
            "delete_webhook": self._handle_delete_webhook,
            # Price Rule / Discount operations
            "list_price_rules": self._handle_list_price_rules,
            "get_price_rule_by_id": self._handle_get_price_rule,
            "create_price_rule": self._handle_create_price_rule,
            "update_price_rule": self._handle_update_price_rule,
            "delete_price_rule": self._handle_delete_price_rule,
            "list_discount_codes": self._handle_list_discount_codes,
            "create_discount_code": self._handle_create_discount_code,
            "delete_discount_code": self._handle_delete_discount_code,
            # Gift Card operations
            "list_gift_cards": self._handle_list_gift_cards,
            "get_gift_card_by_id": self._handle_get_gift_card,
            "create_gift_card": self._handle_create_gift_card,
            "update_gift_card": self._handle_update_gift_card,
            "disable_gift_card": self._handle_disable_gift_card,
            # GraphQL operations
            "execute_custom_graphql_query": self._handle_graphql_query,
            "execute_custom_graphql_mutation": self._handle_graphql_mutation,
            "query_products_with_graphql": self._handle_graphql_products,
            "create_product_with_graphql": self._handle_graphql_product_create,
            "update_product_with_graphql": self._handle_graphql_product_update,
            "query_orders_with_graphql": self._handle_graphql_orders,
            "create_draft_order_with_graphql": self._handle_graphql_draft_order_create,
            "query_customers_with_graphql": self._handle_graphql_customers,
            "create_customer_with_graphql": self._handle_graphql_customer_create,
            "query_inventory_with_graphql": self._handle_graphql_inventory,
            "query_collections_with_graphql": self._handle_graphql_collections,
            "query_fulfillment_orders_with_graphql": self._handle_graphql_fulfillment_orders,
            "get_shop_with_graphql": self._handle_graphql_shop,
        }

        action = op_config.operation
        handler = handlers.get(action)

        if not handler:
            raise ValueError(f"Unknown action: {action}")

        # Execute the handler.  Every Shopify call gets a payload-free durable
        # access record, including calls made by ordinary workflows (agent tool
        # calls have a second, agent-scoped record at their dispatcher).  This
        # provides auditable access without copying protected customer data into
        # observability storage.
        from utils.tool_call_log import record_tool_call

        try:
            result = await handler(op_config, credentials)
        except Exception:
            record_tool_call(
                user_id=self.user_id,
                workflow_id=str(self.workflow_id) if self.workflow_id else None,
                execution_id=self.execution_id,
                conversation_id=self.conversation_id,
                agent_node_id=None,
                provider_node_id=self.node_id,
                credential_id=self.node_data.get("credential_id"),
                tool_name=f"shopify.{action}",
                tool_type="integration_node",
                operation=action,
                arguments=None,
                result_status="error",
                error="Shopify operation failed",
                result_preview=None,
            )
            raise

        record_tool_call(
            user_id=self.user_id,
            workflow_id=str(self.workflow_id) if self.workflow_id else None,
            execution_id=self.execution_id,
            conversation_id=self.conversation_id,
            agent_node_id=None,
            provider_node_id=self.node_id,
            credential_id=self.node_data.get("credential_id"),
            tool_name=f"shopify.{action}",
            tool_type="integration_node",
            operation=action,
            arguments=None,
            result_status=("error" if result.get("status") == "error" else "success"),
            error=("Shopify operation failed" if result.get("status") == "error" else None),
            result_preview=None,
        )

        # Add timing information
        total_time = (time.time() - start_time) * 1000
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round(total_time, 2),
        }

        return result

    # =========================================================================
    # HTTP Request Helper
    # =========================================================================

    def _get_api_base(self, credentials: ShopifyCredential) -> str:
        """Get the API base URL for the store."""
        return _shopify_api_base(credentials.store_name)

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        credentials: ShopifyCredential,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        action_name: str = "request",
    ) -> Dict[str, Any]:
        """
        Make an HTTP request to the Shopify Admin API.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint (without base URL)
            credentials: API credentials
            params: Query parameters
            json_body: JSON request body
            action_name: Name of the action (for response metadata)

        Returns:
            Dict with status, action, data, status_code, and timing
        """
        url = f"{self._get_api_base(credentials)}{endpoint}"

        headers = {
            "X-Shopify-Access-Token": credentials.access_token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        # Clean params (remove None values)
        if params:
            params = {k: v for k, v in params.items() if v is not None}

        start_time = time.time()

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=json_body,
                )

                api_time = (time.time() - start_time) * 1000

                if response.status_code >= 400:
                    error_text = response.text
                    try:
                        error_data = response.json()
                        # Shopify returns errors in various formats
                        if "errors" in error_data:
                            errors = error_data["errors"]
                            if isinstance(errors, dict):
                                error_message = "; ".join(
                                    f"{k}: {v}" for k, v in errors.items()
                                )
                            elif isinstance(errors, list):
                                error_message = "; ".join(str(e) for e in errors)
                            else:
                                error_message = str(errors)
                        elif "error" in error_data:
                            error_message = error_data["error"]
                        else:
                            error_message = error_text
                    except Exception:
                        error_message = error_text

                    logger.error(f"[ShopifyNode] API error: {error_message}")
                    return {
                        "status": "error",
                        "action": action_name,
                        "error": error_message,
                        "status_code": response.status_code,
                        "timing_ms": {"api_request": round(api_time, 2)},
                    }

                # Parse response
                if response.status_code == 204:  # No content
                    data = {"success": True}
                else:
                    try:
                        data = response.json()
                    except Exception:
                        data = {"raw": response.text}

                return {
                    "status": "success",
                    "action": action_name,
                    "data": data,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": round(api_time, 2)},
                }

            except httpx.TimeoutException:
                return {
                    "status": "error",
                    "action": action_name,
                    "error": "Request timed out",
                    "status_code": 408,
                    "timing_ms": {
                        "api_request": round((time.time() - start_time) * 1000, 2)
                    },
                }
            except Exception as e:
                logger.exception(f"[ShopifyNode] Request failed: {e}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": str(e),
                    "status_code": 500,
                    "timing_ms": {
                        "api_request": round((time.time() - start_time) * 1000, 2)
                    },
                }

    # =========================================================================
    # Product Operation Handlers
    # =========================================================================

    async def _handle_list_products(
        self, config: ShopifyListProductsConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """List products from the store."""
        params = {
            "limit": config.limit,
            "since_id": config.since_id,
            "collection_id": config.collection_id,
            "product_type": config.product_type,
            "vendor": config.vendor,
            "status": config.status,
            "fields": config.fields,
        }

        return await self._make_request(
            method="GET",
            endpoint="/products.json",
            credentials=credentials,
            params=params,
            action_name="list_products",
        )

    async def _handle_get_product(
        self, config: ShopifyGetProductConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Get a single product."""
        params = {"fields": config.fields} if config.fields else None

        return await self._make_request(
            method="GET",
            endpoint=f"/products/{config.product_id}.json",
            credentials=credentials,
            params=params,
            action_name="get_product_by_id",
        )

    async def _handle_create_product(
        self, config: ShopifyCreateProductConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Create a new product."""
        product: Dict[str, Any] = {"title": config.title}

        if config.body_html:
            product["body_html"] = config.body_html
        if config.vendor:
            product["vendor"] = config.vendor
        if config.product_type:
            product["product_type"] = config.product_type
        if config.tags:
            product["tags"] = config.tags
        if config.status:
            product["status"] = config.status
        if config.variants:
            product["variants"] = config.variants
        if config.options:
            product["options"] = config.options
        if config.images:
            product["images"] = config.images

        return await self._make_request(
            method="POST",
            endpoint="/products.json",
            credentials=credentials,
            json_body={"product": product},
            action_name="create_product",
        )

    async def _handle_update_product(
        self, config: ShopifyUpdateProductConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Update a product."""
        product: Dict[str, Any] = {}

        if config.title is not None:
            product["title"] = config.title
        if config.body_html is not None:
            product["body_html"] = config.body_html
        if config.vendor is not None:
            product["vendor"] = config.vendor
        if config.product_type is not None:
            product["product_type"] = config.product_type
        if config.tags is not None:
            product["tags"] = config.tags
        if config.status is not None:
            product["status"] = config.status

        return await self._make_request(
            method="PUT",
            endpoint=f"/products/{config.product_id}.json",
            credentials=credentials,
            json_body={"product": product},
            action_name="update_product",
        )

    async def _handle_delete_product(
        self, config: ShopifyDeleteProductConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Delete a product."""
        return await self._make_request(
            method="DELETE",
            endpoint=f"/products/{config.product_id}.json",
            credentials=credentials,
            action_name="delete_product",
        )

    async def _handle_count_products(
        self, config: ShopifyCountProductsConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Get product count."""
        params = {
            "collection_id": config.collection_id,
            "product_type": config.product_type,
            "vendor": config.vendor,
        }

        return await self._make_request(
            method="GET",
            endpoint="/products/count.json",
            credentials=credentials,
            params=params,
            action_name="count_products",
        )

    # =========================================================================
    # Order Operation Handlers
    # =========================================================================

    async def _handle_list_orders(
        self, config: ShopifyListOrdersConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """List orders from the store."""
        params = {
            "limit": config.limit,
            "since_id": config.since_id,
            "status": config.status,
            "financial_status": config.financial_status,
            "fulfillment_status": config.fulfillment_status,
            "created_at_min": config.created_at_min,
            "created_at_max": config.created_at_max,
            "fields": config.fields,
        }

        return await self._make_request(
            method="GET",
            endpoint="/orders.json",
            credentials=credentials,
            params=params,
            action_name="list_orders",
        )

    async def _handle_get_order(
        self, config: ShopifyGetOrderConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Get a single order."""
        params = {"fields": config.fields} if config.fields else None

        return await self._make_request(
            method="GET",
            endpoint=f"/orders/{config.order_id}.json",
            credentials=credentials,
            params=params,
            action_name="get_order_by_id",
        )

    async def _handle_create_order(
        self, config: ShopifyCreateOrderConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Create a new order."""
        order: Dict[str, Any] = {"line_items": config.line_items}

        if config.customer:
            order["customer"] = config.customer
        if config.email:
            order["email"] = config.email
        if config.shipping_address:
            order["shipping_address"] = config.shipping_address
        if config.billing_address:
            order["billing_address"] = config.billing_address
        if config.financial_status:
            order["financial_status"] = config.financial_status
        if config.send_receipt:
            order["send_receipt"] = config.send_receipt
        if config.send_fulfillment_receipt:
            order["send_fulfillment_receipt"] = config.send_fulfillment_receipt
        if config.note:
            order["note"] = config.note
        if config.tags:
            order["tags"] = config.tags

        return await self._make_request(
            method="POST",
            endpoint="/orders.json",
            credentials=credentials,
            json_body={"order": order},
            action_name="create_order",
        )

    async def _handle_update_order(
        self, config: ShopifyUpdateOrderConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Update an order."""
        order: Dict[str, Any] = {}

        if config.note is not None:
            order["note"] = config.note
        if config.tags is not None:
            order["tags"] = config.tags
        if config.email is not None:
            order["email"] = config.email
        if config.shipping_address is not None:
            order["shipping_address"] = config.shipping_address

        return await self._make_request(
            method="PUT",
            endpoint=f"/orders/{config.order_id}.json",
            credentials=credentials,
            json_body={"order": order},
            action_name="update_order",
        )

    async def _handle_delete_order(
        self, config: ShopifyDeleteOrderConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Delete an order."""
        return await self._make_request(
            method="DELETE",
            endpoint=f"/orders/{config.order_id}.json",
            credentials=credentials,
            action_name="delete_order",
        )

    async def _handle_cancel_order(
        self, config: ShopifyCancelOrderConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Cancel an order."""
        body: Dict[str, Any] = {}

        if config.reason:
            body["reason"] = config.reason
        if config.email is not None:
            body["email"] = config.email
        if config.restock is not None:
            body["restock"] = config.restock

        return await self._make_request(
            method="POST",
            endpoint=f"/orders/{config.order_id}/cancel.json",
            credentials=credentials,
            json_body=body if body else None,
            action_name="cancel_order",
        )

    async def _handle_close_order(
        self, config: ShopifyCloseOrderConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Close an order."""
        return await self._make_request(
            method="POST",
            endpoint=f"/orders/{config.order_id}/close.json",
            credentials=credentials,
            action_name="close_order",
        )

    async def _handle_open_order(
        self, config: ShopifyOpenOrderConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Reopen a closed order."""
        return await self._make_request(
            method="POST",
            endpoint=f"/orders/{config.order_id}/open.json",
            credentials=credentials,
            action_name="reopen_closed_order",
        )

    async def _handle_count_orders(
        self, config: ShopifyCountOrdersConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Get order count."""
        params = {
            "status": config.status,
            "financial_status": config.financial_status,
            "fulfillment_status": config.fulfillment_status,
        }

        return await self._make_request(
            method="GET",
            endpoint="/orders/count.json",
            credentials=credentials,
            params=params,
            action_name="count_orders",
        )

    # =========================================================================
    # Customer Operation Handlers
    # =========================================================================

    async def _handle_list_customers(
        self, config: ShopifyListCustomersConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """List customers from the store."""
        params = {
            "limit": config.limit,
            "since_id": config.since_id,
            "created_at_min": config.created_at_min,
            "created_at_max": config.created_at_max,
            "updated_at_min": config.updated_at_min,
            "updated_at_max": config.updated_at_max,
            "fields": config.fields,
        }

        return await self._make_request(
            method="GET",
            endpoint="/customers.json",
            credentials=credentials,
            params=params,
            action_name="list_customers",
        )

    async def _handle_get_customer(
        self, config: ShopifyGetCustomerConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Get a single customer."""
        params = {"fields": config.fields} if config.fields else None

        return await self._make_request(
            method="GET",
            endpoint=f"/customers/{config.customer_id}.json",
            credentials=credentials,
            params=params,
            action_name="get_customer_by_id",
        )

    async def _handle_create_customer(
        self, config: ShopifyCreateCustomerConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Create a new customer."""
        customer: Dict[str, Any] = {"email": config.email}

        if config.first_name:
            customer["first_name"] = config.first_name
        if config.last_name:
            customer["last_name"] = config.last_name
        if config.phone:
            customer["phone"] = config.phone
        if config.verified_email is not None:
            customer["verified_email"] = config.verified_email
        if config.addresses:
            customer["addresses"] = config.addresses
        if config.tags:
            customer["tags"] = config.tags
        if config.note:
            customer["note"] = config.note
        if config.send_email_welcome:
            customer["send_email_welcome"] = config.send_email_welcome
        if config.send_email_invite:
            customer["send_email_invite"] = config.send_email_invite

        return await self._make_request(
            method="POST",
            endpoint="/customers.json",
            credentials=credentials,
            json_body={"customer": customer},
            action_name="create_customer",
        )

    async def _handle_update_customer(
        self, config: ShopifyUpdateCustomerConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Update a customer."""
        customer: Dict[str, Any] = {}

        if config.email is not None:
            customer["email"] = config.email
        if config.first_name is not None:
            customer["first_name"] = config.first_name
        if config.last_name is not None:
            customer["last_name"] = config.last_name
        if config.phone is not None:
            customer["phone"] = config.phone
        if config.tags is not None:
            customer["tags"] = config.tags
        if config.note is not None:
            customer["note"] = config.note

        return await self._make_request(
            method="PUT",
            endpoint=f"/customers/{config.customer_id}.json",
            credentials=credentials,
            json_body={"customer": customer},
            action_name="update_customer",
        )

    async def _handle_delete_customer(
        self, config: ShopifyDeleteCustomerConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Delete a customer."""
        return await self._make_request(
            method="DELETE",
            endpoint=f"/customers/{config.customer_id}.json",
            credentials=credentials,
            action_name="delete_customer",
        )

    async def _handle_search_customers(
        self, config: ShopifySearchCustomersConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Search for customers."""
        params = {
            "query": config.query,
            "limit": config.limit,
            "fields": config.fields,
        }

        return await self._make_request(
            method="GET",
            endpoint="/customers/search.json",
            credentials=credentials,
            params=params,
            action_name="search_customers",
        )

    async def _handle_count_customers(
        self, config: ShopifyCountCustomersConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Get customer count."""
        return await self._make_request(
            method="GET",
            endpoint="/customers/count.json",
            credentials=credentials,
            action_name="count_customers",
        )

    async def _handle_get_customer_orders(
        self, config: ShopifyGetCustomerOrdersConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Get orders for a specific customer."""
        params = {"status": config.status}

        return await self._make_request(
            method="GET",
            endpoint=f"/customers/{config.customer_id}/orders.json",
            credentials=credentials,
            params=params,
            action_name="get_customer_orders",
        )

    # =========================================================================
    # Inventory Operation Handlers
    # =========================================================================

    async def _handle_list_inventory_levels(
        self, config: ShopifyListInventoryLevelsConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """List inventory levels."""
        params = {
            "inventory_item_ids": config.inventory_item_ids,
            "location_ids": config.location_ids,
            "limit": config.limit,
        }

        return await self._make_request(
            method="GET",
            endpoint="/inventory_levels.json",
            credentials=credentials,
            params=params,
            action_name="list_inventory_levels",
        )

    async def _handle_adjust_inventory_level(
        self, config: ShopifyAdjustInventoryLevelConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Adjust inventory level."""
        body = {
            "inventory_item_id": int(config.inventory_item_id),
            "location_id": int(config.location_id),
            "available_adjustment": config.available_adjustment,
        }

        return await self._make_request(
            method="POST",
            endpoint="/inventory_levels/adjust.json",
            credentials=credentials,
            json_body=body,
            action_name="adjust_inventory_level_at_location",
        )

    async def _handle_set_inventory_level(
        self, config: ShopifySetInventoryLevelConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Set inventory level."""
        body: Dict[str, Any] = {
            "inventory_item_id": int(config.inventory_item_id),
            "location_id": int(config.location_id),
            "available": config.available,
        }

        if config.disconnect_if_necessary:
            body["disconnect_if_necessary"] = config.disconnect_if_necessary

        return await self._make_request(
            method="POST",
            endpoint="/inventory_levels/set.json",
            credentials=credentials,
            json_body=body,
            action_name="set_inventory_level_at_location",
        )

    async def _handle_connect_inventory_level(
        self, config: ShopifyConnectInventoryLevelConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Connect inventory item to location."""
        body: Dict[str, Any] = {
            "inventory_item_id": int(config.inventory_item_id),
            "location_id": int(config.location_id),
        }

        if config.relocate_if_necessary:
            body["relocate_if_necessary"] = config.relocate_if_necessary

        return await self._make_request(
            method="POST",
            endpoint="/inventory_levels/connect.json",
            credentials=credentials,
            json_body=body,
            action_name="connect_inventory_item_to_location",
        )

    async def _handle_delete_inventory_level(
        self, config: ShopifyDeleteInventoryLevelConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Delete inventory level (disconnect item from location)."""
        params = {
            "inventory_item_id": config.inventory_item_id,
            "location_id": config.location_id,
        }

        return await self._make_request(
            method="DELETE",
            endpoint="/inventory_levels.json",
            credentials=credentials,
            params=params,
            action_name="delete_inventory_level",
        )

    # =========================================================================
    # Fulfillment Operation Handlers
    # =========================================================================

    async def _handle_list_fulfillments(
        self, config: ShopifyListFulfillmentsConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """List fulfillments for an order."""
        return await self._make_request(
            method="GET",
            endpoint=f"/orders/{config.order_id}/fulfillments.json",
            credentials=credentials,
            action_name="list_order_fulfillments",
        )

    async def _handle_get_fulfillment(
        self, config: ShopifyGetFulfillmentConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Get a single fulfillment."""
        return await self._make_request(
            method="GET",
            endpoint=f"/orders/{config.order_id}/fulfillments/{config.fulfillment_id}.json",
            credentials=credentials,
            action_name="get_order_fulfillment",
        )

    async def _handle_create_fulfillment(
        self, config: ShopifyCreateFulfillmentConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Create a fulfillment for an order."""
        fulfillment: Dict[str, Any] = {}

        if config.location_id:
            fulfillment["location_id"] = int(config.location_id)
        if config.tracking_number:
            fulfillment["tracking_number"] = config.tracking_number
        if config.tracking_urls:
            fulfillment["tracking_urls"] = config.tracking_urls
        if config.notify_customer is not None:
            fulfillment["notify_customer"] = config.notify_customer
        if config.line_items:
            fulfillment["line_items"] = config.line_items

        return await self._make_request(
            method="POST",
            endpoint=f"/orders/{config.order_id}/fulfillments.json",
            credentials=credentials,
            json_body={"fulfillment": fulfillment},
            action_name="create_order_fulfillment",
        )

    async def _handle_update_fulfillment(
        self, config: ShopifyUpdateFulfillmentConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Update a fulfillment."""
        fulfillment: Dict[str, Any] = {}

        if config.tracking_number is not None:
            fulfillment["tracking_number"] = config.tracking_number
        if config.tracking_urls is not None:
            fulfillment["tracking_urls"] = config.tracking_urls
        if config.notify_customer is not None:
            fulfillment["notify_customer"] = config.notify_customer

        return await self._make_request(
            method="PUT",
            endpoint=f"/orders/{config.order_id}/fulfillments/{config.fulfillment_id}.json",
            credentials=credentials,
            json_body={"fulfillment": fulfillment},
            action_name="update_order_fulfillment",
        )

    async def _handle_complete_fulfillment(
        self, config: ShopifyCompleteFulfillmentConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Mark a fulfillment as complete."""
        return await self._make_request(
            method="POST",
            endpoint=f"/orders/{config.order_id}/fulfillments/{config.fulfillment_id}/complete.json",
            credentials=credentials,
            action_name="complete_order_fulfillment",
        )

    async def _handle_cancel_fulfillment(
        self, config: ShopifyCancelFulfillmentConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Cancel a fulfillment."""
        return await self._make_request(
            method="POST",
            endpoint=f"/orders/{config.order_id}/fulfillments/{config.fulfillment_id}/cancel.json",
            credentials=credentials,
            action_name="cancel_order_fulfillment",
        )

    # =========================================================================
    # Collection Operation Handlers
    # =========================================================================

    async def _handle_list_collections(
        self, config: ShopifyListCollectionsConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """List collections (custom collections)."""
        params = {
            "limit": config.limit,
            "since_id": config.since_id,
            "title": config.title,
        }

        return await self._make_request(
            method="GET",
            endpoint="/custom_collections.json",
            credentials=credentials,
            params=params,
            action_name="list_collections",
        )

    async def _handle_get_collection(
        self, config: ShopifyGetCollectionConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Get a single collection."""
        return await self._make_request(
            method="GET",
            endpoint=f"/custom_collections/{config.collection_id}.json",
            credentials=credentials,
            action_name="get_collection_by_id",
        )

    async def _handle_list_blogs(
        self, config: ShopifyListBlogsConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """List the store's blogs."""
        return await self._make_request(
            method="GET",
            endpoint="/blogs.json",
            credentials=credentials,
            params={"limit": config.limit, "since_id": config.since_id},
            action_name="list_blogs",
        )

    async def _handle_list_blog_articles(
        self, config: ShopifyListBlogArticlesConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """List articles in a blog."""
        return await self._make_request(
            method="GET",
            endpoint=f"/blogs/{config.blog_id}/articles.json",
            credentials=credentials,
            params={
                "limit": config.limit,
                "since_id": config.since_id,
                "tag": config.tag,
                "published_status": config.published_status,
            },
            action_name="list_blog_articles",
        )

    async def _handle_get_blog_article(
        self, config: ShopifyGetBlogArticleConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Get a single blog article."""
        return await self._make_request(
            method="GET",
            endpoint=f"/blogs/{config.blog_id}/articles/{config.article_id}.json",
            credentials=credentials,
            action_name="get_blog_article_by_id",
        )

    @staticmethod
    def _article_body(config) -> Dict[str, Any]:
        """Article payload from a create/update config; None fields are omitted."""
        article: Dict[str, Any] = {}
        for key in ("title", "body_html", "author", "tags", "summary_html"):
            value = getattr(config, key)
            if value is not None:
                article[key] = value
        if config.published is not None:
            article["published"] = config.published == "true"
        if config.image_src:
            image: Dict[str, Any] = {"src": config.image_src}
            if config.image_alt:
                image["alt"] = config.image_alt
            article["image"] = image
        return article

    async def _handle_create_blog_article(
        self, config: ShopifyCreateBlogArticleConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Create a blog article."""
        return await self._make_request(
            method="POST",
            endpoint=f"/blogs/{config.blog_id}/articles.json",
            credentials=credentials,
            json_body={"article": self._article_body(config)},
            action_name="create_blog_article",
        )

    async def _handle_update_blog_article(
        self, config: ShopifyUpdateBlogArticleConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Update a blog article."""
        article = self._article_body(config)
        article["id"] = config.article_id
        return await self._make_request(
            method="PUT",
            endpoint=f"/blogs/{config.blog_id}/articles/{config.article_id}.json",
            credentials=credentials,
            json_body={"article": article},
            action_name="update_blog_article",
        )

    async def _handle_delete_blog_article(
        self, config: ShopifyDeleteBlogArticleConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Delete a blog article."""
        return await self._make_request(
            method="DELETE",
            endpoint=f"/blogs/{config.blog_id}/articles/{config.article_id}.json",
            credentials=credentials,
            action_name="delete_blog_article",
        )

    async def _handle_create_collection(
        self, config: ShopifyCreateCollectionConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Create a new collection."""
        collection: Dict[str, Any] = {"title": config.title}

        if config.body_html:
            collection["body_html"] = config.body_html
        if config.image:
            collection["image"] = config.image
        if config.published is not None:
            collection["published"] = config.published

        return await self._make_request(
            method="POST",
            endpoint="/custom_collections.json",
            credentials=credentials,
            json_body={"custom_collection": collection},
            action_name="create_collection",
        )

    async def _handle_update_collection(
        self, config: ShopifyUpdateCollectionConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Update a collection."""
        collection: Dict[str, Any] = {}

        if config.title is not None:
            collection["title"] = config.title
        if config.body_html is not None:
            collection["body_html"] = config.body_html
        if config.image is not None:
            collection["image"] = config.image

        return await self._make_request(
            method="PUT",
            endpoint=f"/custom_collections/{config.collection_id}.json",
            credentials=credentials,
            json_body={"custom_collection": collection},
            action_name="update_collection",
        )

    async def _handle_delete_collection(
        self, config: ShopifyDeleteCollectionConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Delete a collection."""
        return await self._make_request(
            method="DELETE",
            endpoint=f"/custom_collections/{config.collection_id}.json",
            credentials=credentials,
            action_name="delete_collection",
        )

    async def _handle_add_product_to_collection(
        self,
        config: ShopifyAddProductToCollectionConfig,
        credentials: ShopifyCredential,
    ) -> Dict[str, Any]:
        """Add a product to a collection."""
        collect = {
            "product_id": int(config.product_id),
            "collection_id": int(config.collection_id),
        }

        return await self._make_request(
            method="POST",
            endpoint="/collects.json",
            credentials=credentials,
            json_body={"collect": collect},
            action_name="add_product_to_collection",
        )

    # =========================================================================
    # Location Operation Handlers
    # =========================================================================

    async def _handle_list_locations(
        self, config: ShopifyListLocationsConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """List all locations."""
        return await self._make_request(
            method="GET",
            endpoint="/locations.json",
            credentials=credentials,
            action_name="list_all_locations",
        )

    async def _handle_get_location(
        self, config: ShopifyGetLocationConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Get a single location."""
        return await self._make_request(
            method="GET",
            endpoint=f"/locations/{config.location_id}.json",
            credentials=credentials,
            action_name="get_location_by_id",
        )

    # =========================================================================
    # Shop Operation Handlers
    # =========================================================================

    async def _handle_get_shop(
        self, config: ShopifyGetShopConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Get shop information."""
        return await self._make_request(
            method="GET",
            endpoint="/shop.json",
            credentials=credentials,
            action_name="get_shop_information",
        )

    # =========================================================================
    # Metafield Operation Handlers
    # =========================================================================

    async def _handle_list_metafields(
        self, config: ShopifyListMetafieldsConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """List metafields for a resource."""
        if config.resource_id:
            endpoint = f"/{config.resource}s/{config.resource_id}/metafields.json"
        else:
            endpoint = "/metafields.json"

        return await self._make_request(
            method="GET",
            endpoint=endpoint,
            credentials=credentials,
            action_name="list_metafields",
        )

    async def _handle_get_metafield(
        self, config: ShopifyGetMetafieldConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Get a single metafield."""
        return await self._make_request(
            method="GET",
            endpoint=f"/metafields/{config.metafield_id}.json",
            credentials=credentials,
            action_name="get_metafield_by_id",
        )

    async def _handle_create_metafield(
        self, config: ShopifyCreateMetafieldConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Create a metafield."""
        metafield = {
            "namespace": config.namespace,
            "key": config.key,
            "value": config.value,
            "type": config.type,
        }

        if config.resource_id:
            endpoint = f"/{config.resource}s/{config.resource_id}/metafields.json"
        else:
            endpoint = "/metafields.json"

        return await self._make_request(
            method="POST",
            endpoint=endpoint,
            credentials=credentials,
            json_body={"metafield": metafield},
            action_name="create_metafield",
        )

    async def _handle_update_metafield(
        self, config: ShopifyUpdateMetafieldConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Update a metafield."""
        metafield: Dict[str, Any] = {"value": config.value}

        if config.type:
            metafield["type"] = config.type

        return await self._make_request(
            method="PUT",
            endpoint=f"/metafields/{config.metafield_id}.json",
            credentials=credentials,
            json_body={"metafield": metafield},
            action_name="update_metafield",
        )

    async def _handle_delete_metafield(
        self, config: ShopifyDeleteMetafieldConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Delete a metafield."""
        return await self._make_request(
            method="DELETE",
            endpoint=f"/metafields/{config.metafield_id}.json",
            credentials=credentials,
            action_name="delete_metafield",
        )

    # =========================================================================
    # Webhook Operation Handlers
    # =========================================================================

    async def _handle_list_webhooks(
        self, config: ShopifyListWebhooksConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """List webhooks."""
        return await self._make_request(
            method="GET",
            endpoint="/webhooks.json",
            credentials=credentials,
            action_name="list_webhooks",
        )

    async def _handle_get_webhook(
        self, config: ShopifyGetWebhookConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Get a single webhook."""
        return await self._make_request(
            method="GET",
            endpoint=f"/webhooks/{config.webhook_id}.json",
            credentials=credentials,
            action_name="get_webhook_by_id",
        )

    async def _handle_create_webhook(
        self, config: ShopifyCreateWebhookConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Create a webhook."""
        webhook: Dict[str, Any] = {
            "topic": config.topic,
            "address": config.address,
            "format": config.format or "json",
        }

        return await self._make_request(
            method="POST",
            endpoint="/webhooks.json",
            credentials=credentials,
            json_body={"webhook": webhook},
            action_name="create_webhook",
        )

    async def _handle_update_webhook(
        self, config: ShopifyUpdateWebhookConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Update a webhook."""
        webhook: Dict[str, Any] = {}

        if config.address is not None:
            webhook["address"] = config.address
        if config.topic is not None:
            webhook["topic"] = config.topic

        return await self._make_request(
            method="PUT",
            endpoint=f"/webhooks/{config.webhook_id}.json",
            credentials=credentials,
            json_body={"webhook": webhook},
            action_name="update_webhook",
        )

    async def _handle_delete_webhook(
        self, config: ShopifyDeleteWebhookConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Delete a webhook."""
        return await self._make_request(
            method="DELETE",
            endpoint=f"/webhooks/{config.webhook_id}.json",
            credentials=credentials,
            action_name="delete_webhook",
        )

    # =========================================================================
    # Price Rule / Discount Operation Handlers
    # =========================================================================

    async def _handle_list_price_rules(
        self, config: ShopifyListPriceRulesConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """List price rules."""
        params = {"limit": config.limit}

        return await self._make_request(
            method="GET",
            endpoint="/price_rules.json",
            credentials=credentials,
            params=params,
            action_name="list_price_rules",
        )

    async def _handle_get_price_rule(
        self, config: ShopifyGetPriceRuleConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Get a single price rule."""
        return await self._make_request(
            method="GET",
            endpoint=f"/price_rules/{config.price_rule_id}.json",
            credentials=credentials,
            action_name="get_price_rule_by_id",
        )

    async def _handle_create_price_rule(
        self, config: ShopifyCreatePriceRuleConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Create a price rule."""
        price_rule: Dict[str, Any] = {
            "title": config.title,
            "target_type": config.target_type,
            "target_selection": config.target_selection,
            "allocation_method": config.allocation_method,
            "value_type": config.value_type,
            "value": config.value,
            "customer_selection": config.customer_selection,
        }

        if config.starts_at:
            price_rule["starts_at"] = config.starts_at
        if config.ends_at:
            price_rule["ends_at"] = config.ends_at

        return await self._make_request(
            method="POST",
            endpoint="/price_rules.json",
            credentials=credentials,
            json_body={"price_rule": price_rule},
            action_name="create_price_rule",
        )

    async def _handle_update_price_rule(
        self, config: ShopifyUpdatePriceRuleConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Update a price rule."""
        price_rule: Dict[str, Any] = {}

        if config.title is not None:
            price_rule["title"] = config.title
        if config.value is not None:
            price_rule["value"] = config.value
        if config.starts_at is not None:
            price_rule["starts_at"] = config.starts_at
        if config.ends_at is not None:
            price_rule["ends_at"] = config.ends_at

        return await self._make_request(
            method="PUT",
            endpoint=f"/price_rules/{config.price_rule_id}.json",
            credentials=credentials,
            json_body={"price_rule": price_rule},
            action_name="update_price_rule",
        )

    async def _handle_delete_price_rule(
        self, config: ShopifyDeletePriceRuleConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Delete a price rule."""
        return await self._make_request(
            method="DELETE",
            endpoint=f"/price_rules/{config.price_rule_id}.json",
            credentials=credentials,
            action_name="delete_price_rule",
        )

    async def _handle_list_discount_codes(
        self, config: ShopifyListDiscountCodesConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """List discount codes for a price rule."""
        return await self._make_request(
            method="GET",
            endpoint=f"/price_rules/{config.price_rule_id}/discount_codes.json",
            credentials=credentials,
            action_name="list_discount_codes",
        )

    async def _handle_create_discount_code(
        self, config: ShopifyCreateDiscountCodeConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Create a discount code for a price rule."""
        discount_code = {"code": config.code}

        return await self._make_request(
            method="POST",
            endpoint=f"/price_rules/{config.price_rule_id}/discount_codes.json",
            credentials=credentials,
            json_body={"discount_code": discount_code},
            action_name="create_discount_code",
        )

    async def _handle_delete_discount_code(
        self, config: ShopifyDeleteDiscountCodeConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Delete a discount code."""
        return await self._make_request(
            method="DELETE",
            endpoint=f"/price_rules/{config.price_rule_id}/discount_codes/{config.discount_code_id}.json",
            credentials=credentials,
            action_name="delete_discount_code",
        )

    # =========================================================================
    # Gift Card Operation Handlers
    # =========================================================================

    async def _handle_list_gift_cards(
        self, config: ShopifyListGiftCardsConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """List gift cards."""
        params = {
            "limit": config.limit,
            "status": config.status,
        }

        return await self._make_request(
            method="GET",
            endpoint="/gift_cards.json",
            credentials=credentials,
            params=params,
            action_name="list_gift_cards",
        )

    async def _handle_get_gift_card(
        self, config: ShopifyGetGiftCardConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Get a single gift card."""
        return await self._make_request(
            method="GET",
            endpoint=f"/gift_cards/{config.gift_card_id}.json",
            credentials=credentials,
            action_name="get_gift_card_by_id",
        )

    async def _handle_create_gift_card(
        self, config: ShopifyCreateGiftCardConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Create a gift card."""
        gift_card: Dict[str, Any] = {"initial_value": config.initial_value}

        if config.code:
            gift_card["code"] = config.code
        if config.note:
            gift_card["note"] = config.note

        return await self._make_request(
            method="POST",
            endpoint="/gift_cards.json",
            credentials=credentials,
            json_body={"gift_card": gift_card},
            action_name="create_gift_card",
        )

    async def _handle_update_gift_card(
        self, config: ShopifyUpdateGiftCardConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Update a gift card."""
        gift_card: Dict[str, Any] = {}

        if config.note is not None:
            gift_card["note"] = config.note
        if config.expires_on is not None:
            gift_card["expires_on"] = config.expires_on

        return await self._make_request(
            method="PUT",
            endpoint=f"/gift_cards/{config.gift_card_id}.json",
            credentials=credentials,
            json_body={"gift_card": gift_card},
            action_name="update_gift_card",
        )

    async def _handle_disable_gift_card(
        self, config: ShopifyDisableGiftCardConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Disable a gift card."""
        return await self._make_request(
            method="POST",
            endpoint=f"/gift_cards/{config.gift_card_id}/disable.json",
            credentials=credentials,
            action_name="disable_gift_card",
        )

    # =========================================================================
    # Product Variant Operation Handlers
    # =========================================================================

    async def _handle_list_product_variants(
        self, config: ShopifyListProductVariantsConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """List all variants for a product."""
        params = {
            "limit": config.limit,
            "since_id": config.since_id,
            "fields": config.fields,
        }

        return await self._make_request(
            method="GET",
            endpoint=f"/products/{config.product_id}/variants.json",
            credentials=credentials,
            params=params,
            action_name="list_product_variants",
        )

    async def _handle_get_product_variant(
        self, config: ShopifyGetProductVariantConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Get a single product variant."""
        params = {"fields": config.fields} if config.fields else None

        return await self._make_request(
            method="GET",
            endpoint=f"/variants/{config.variant_id}.json",
            credentials=credentials,
            params=params,
            action_name="get_product_variant_by_id",
        )

    async def _handle_create_product_variant(
        self, config: ShopifyCreateProductVariantConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Create a new product variant."""
        variant: Dict[str, Any] = {}

        if config.option1:
            variant["option1"] = config.option1
        if config.option2:
            variant["option2"] = config.option2
        if config.option3:
            variant["option3"] = config.option3
        if config.price is not None:
            variant["price"] = config.price
        if config.sku:
            variant["sku"] = config.sku
        if config.barcode:
            variant["barcode"] = config.barcode
        if config.inventory_quantity is not None:
            variant["inventory_quantity"] = config.inventory_quantity
        if config.weight is not None:
            variant["weight"] = config.weight
        if config.weight_unit:
            variant["weight_unit"] = config.weight_unit

        return await self._make_request(
            method="POST",
            endpoint=f"/products/{config.product_id}/variants.json",
            credentials=credentials,
            json_body={"variant": variant},
            action_name="create_product_variant",
        )

    async def _handle_update_product_variant(
        self, config: ShopifyUpdateProductVariantConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Update a product variant."""
        variant: Dict[str, Any] = {}

        if config.price is not None:
            variant["price"] = config.price
        if config.sku is not None:
            variant["sku"] = config.sku
        if config.barcode is not None:
            variant["barcode"] = config.barcode
        if config.inventory_quantity is not None:
            variant["inventory_quantity"] = config.inventory_quantity
        if config.weight is not None:
            variant["weight"] = config.weight

        return await self._make_request(
            method="PUT",
            endpoint=f"/variants/{config.variant_id}.json",
            credentials=credentials,
            json_body={"variant": variant},
            action_name="update_product_variant",
        )

    async def _handle_delete_product_variant(
        self, config: ShopifyDeleteProductVariantConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Delete a product variant."""
        return await self._make_request(
            method="DELETE",
            endpoint=f"/products/{config.product_id}/variants/{config.variant_id}.json",
            credentials=credentials,
            action_name="delete_product_variant",
        )

    async def _handle_count_product_variants(
        self, config: ShopifyCountProductVariantsConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Count product variants."""
        return await self._make_request(
            method="GET",
            endpoint=f"/products/{config.product_id}/variants/count.json",
            credentials=credentials,
            action_name="count_product_variants",
        )

    # =========================================================================
    # Product Image Operation Handlers
    # =========================================================================

    async def _handle_list_product_images(
        self, config: ShopifyListProductImagesConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """List all images for a product."""
        params = {
            "since_id": config.since_id,
            "fields": config.fields,
        }

        return await self._make_request(
            method="GET",
            endpoint=f"/products/{config.product_id}/images.json",
            credentials=credentials,
            params=params,
            action_name="list_product_images",
        )

    async def _handle_get_product_image(
        self, config: ShopifyGetProductImageConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Get a single product image."""
        params = {"fields": config.fields} if config.fields else None

        return await self._make_request(
            method="GET",
            endpoint=f"/products/{config.product_id}/images/{config.image_id}.json",
            credentials=credentials,
            params=params,
            action_name="get_product_image_by_id",
        )

    async def _handle_create_product_image(
        self, config: ShopifyCreateProductImageConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Create a new product image."""
        image: Dict[str, Any] = {}

        if config.src:
            image["src"] = config.src
        if config.attachment:
            image["attachment"] = config.attachment
        if config.position is not None:
            image["position"] = config.position
        if config.alt:
            image["alt"] = config.alt

        return await self._make_request(
            method="POST",
            endpoint=f"/products/{config.product_id}/images.json",
            credentials=credentials,
            json_body={"image": image},
            action_name="create_product_image",
        )

    async def _handle_delete_product_image(
        self, config: ShopifyDeleteProductImageConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Delete a product image."""
        return await self._make_request(
            method="DELETE",
            endpoint=f"/products/{config.product_id}/images/{config.image_id}.json",
            credentials=credentials,
            action_name="delete_product_image",
        )

    # =========================================================================
    # Refund Operation Handlers
    # =========================================================================

    async def _handle_list_refunds(
        self, config: ShopifyListRefundsConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """List all refunds for an order."""
        params = {"fields": config.fields} if config.fields else None

        return await self._make_request(
            method="GET",
            endpoint=f"/orders/{config.order_id}/refunds.json",
            credentials=credentials,
            params=params,
            action_name="list_order_refunds",
        )

    async def _handle_get_refund(
        self, config: ShopifyGetRefundConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Get a single refund."""
        params = {"fields": config.fields} if config.fields else None

        return await self._make_request(
            method="GET",
            endpoint=f"/orders/{config.order_id}/refunds/{config.refund_id}.json",
            credentials=credentials,
            params=params,
            action_name="get_order_refund_by_id",
        )

    async def _handle_create_refund(
        self, config: ShopifyCreateRefundConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Create a refund for an order."""
        refund: Dict[str, Any] = {}

        if config.refund_line_items:
            refund["refund_line_items"] = config.refund_line_items
        if config.shipping:
            refund["shipping"] = config.shipping
        if config.note:
            refund["note"] = config.note
        if config.notify is not None:
            refund["notify"] = config.notify

        return await self._make_request(
            method="POST",
            endpoint=f"/orders/{config.order_id}/refunds.json",
            credentials=credentials,
            json_body={"refund": refund},
            action_name="create_order_refund",
        )

    async def _handle_calculate_refund(
        self, config: ShopifyCalculateRefundConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Calculate a refund for an order."""
        refund: Dict[str, Any] = {}

        if config.refund_line_items:
            refund["refund_line_items"] = config.refund_line_items
        if config.shipping:
            refund["shipping"] = config.shipping

        return await self._make_request(
            method="POST",
            endpoint=f"/orders/{config.order_id}/refunds/calculate.json",
            credentials=credentials,
            json_body={"refund": refund},
            action_name="calculate_order_refund",
        )

    # =========================================================================
    # Transaction Operation Handlers
    # =========================================================================

    async def _handle_list_transactions(
        self, config: ShopifyListTransactionsConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """List all transactions for an order."""
        params = {
            "since_id": config.since_id,
            "fields": config.fields,
        }

        return await self._make_request(
            method="GET",
            endpoint=f"/orders/{config.order_id}/transactions.json",
            credentials=credentials,
            params=params,
            action_name="list_order_transactions",
        )

    async def _handle_get_transaction(
        self, config: ShopifyGetTransactionConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Get a single transaction."""
        params = {"fields": config.fields} if config.fields else None

        return await self._make_request(
            method="GET",
            endpoint=f"/orders/{config.order_id}/transactions/{config.transaction_id}.json",
            credentials=credentials,
            params=params,
            action_name="get_order_transaction_by_id",
        )

    async def _handle_create_transaction(
        self, config: ShopifyCreateTransactionConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Create a transaction for an order."""
        transaction: Dict[str, Any] = {"kind": config.kind}

        if config.amount is not None:
            transaction["amount"] = config.amount
        if config.currency:
            transaction["currency"] = config.currency
        if config.test is not None:
            transaction["test"] = config.test

        return await self._make_request(
            method="POST",
            endpoint=f"/orders/{config.order_id}/transactions.json",
            credentials=credentials,
            json_body={"transaction": transaction},
            action_name="create_order_transaction",
        )

    async def _handle_count_transactions(
        self, config: ShopifyCountTransactionsConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Count transactions for an order."""
        return await self._make_request(
            method="GET",
            endpoint=f"/orders/{config.order_id}/transactions/count.json",
            credentials=credentials,
            action_name="count_order_transactions",
        )

    # =========================================================================
    # Customer Address Operation Handlers
    # =========================================================================

    async def _handle_list_customer_addresses(
        self, config: ShopifyListCustomerAddressesConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """List all addresses for a customer."""
        return await self._make_request(
            method="GET",
            endpoint=f"/customers/{config.customer_id}/addresses.json",
            credentials=credentials,
            action_name="list_customer_addresses",
        )

    async def _handle_get_customer_address(
        self, config: ShopifyGetCustomerAddressConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Get a single customer address."""
        return await self._make_request(
            method="GET",
            endpoint=f"/customers/{config.customer_id}/addresses/{config.address_id}.json",
            credentials=credentials,
            action_name="get_customer_address_by_id",
        )

    async def _handle_create_customer_address(
        self, config: ShopifyCreateCustomerAddressConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Create a new address for a customer."""
        address: Dict[str, Any] = {}

        if config.address1:
            address["address1"] = config.address1
        if config.address2:
            address["address2"] = config.address2
        if config.city:
            address["city"] = config.city
        if config.province:
            address["province"] = config.province
        if config.country:
            address["country"] = config.country
        if config.zip_code:
            address["zip"] = config.zip_code
        if config.phone:
            address["phone"] = config.phone
        if config.first_name:
            address["first_name"] = config.first_name
        if config.last_name:
            address["last_name"] = config.last_name
        if config.company:
            address["company"] = config.company

        return await self._make_request(
            method="POST",
            endpoint=f"/customers/{config.customer_id}/addresses.json",
            credentials=credentials,
            json_body={"address": address},
            action_name="create_customer_address",
        )

    async def _handle_update_customer_address(
        self, config: ShopifyUpdateCustomerAddressConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Update a customer address."""
        address: Dict[str, Any] = {}

        if config.address1 is not None:
            address["address1"] = config.address1
        if config.address2 is not None:
            address["address2"] = config.address2
        if config.city is not None:
            address["city"] = config.city
        if config.province is not None:
            address["province"] = config.province
        if config.country is not None:
            address["country"] = config.country
        if config.zip_code is not None:
            address["zip"] = config.zip_code
        if config.phone is not None:
            address["phone"] = config.phone

        return await self._make_request(
            method="PUT",
            endpoint=f"/customers/{config.customer_id}/addresses/{config.address_id}.json",
            credentials=credentials,
            json_body={"address": address},
            action_name="update_customer_address",
        )

    async def _handle_delete_customer_address(
        self, config: ShopifyDeleteCustomerAddressConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Delete a customer address."""
        return await self._make_request(
            method="DELETE",
            endpoint=f"/customers/{config.customer_id}/addresses/{config.address_id}.json",
            credentials=credentials,
            action_name="delete_customer_address",
        )

    async def _handle_set_default_customer_address(
        self,
        config: ShopifySetDefaultCustomerAddressConfig,
        credentials: ShopifyCredential,
    ) -> Dict[str, Any]:
        """Set a customer address as the default."""
        return await self._make_request(
            method="PUT",
            endpoint=f"/customers/{config.customer_id}/addresses/{config.address_id}/default.json",
            credentials=credentials,
            action_name="set_default_customer_address",
        )

    # =========================================================================
    # GraphQL Helper
    # =========================================================================

    def _get_graphql_url(self, credentials: ShopifyCredential) -> str:
        """Get the GraphQL API URL for the store."""
        store = normalize_provider_subdomain(
            credentials.store_name,
            "myshopify.com",
            field_name="Shopify store name",
        )
        # Use latest GraphQL API version (2025-01)
        return f"https://{store}.myshopify.com/admin/api/2025-01/graphql.json"

    async def _make_graphql_request(
        self,
        query: str,
        credentials: ShopifyCredential,
        variables: Optional[Dict[str, Any]] = None,
        action_name: str = "graphql_request",
    ) -> Dict[str, Any]:
        """
        Make a GraphQL request to the Shopify Admin API.

        Args:
            query: GraphQL query or mutation string
            credentials: API credentials
            variables: GraphQL variables
            action_name: Name of the action (for response metadata)

        Returns:
            Dict with status, action, data, and timing
        """
        url = self._get_graphql_url(credentials)

        headers = {
            "X-Shopify-Access-Token": credentials.access_token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        body = {"query": query}
        if variables:
            body["variables"] = variables

        start_time = time.time()

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(url=url, headers=headers, json=body)

                api_time = (time.time() - start_time) * 1000

                if response.status_code >= 400:
                    error_text = response.text
                    logger.error(f"[ShopifyNode] GraphQL HTTP error: {error_text}")
                    return {
                        "status": "error",
                        "action": action_name,
                        "error": error_text,
                        "status_code": response.status_code,
                        "timing_ms": {"api_request": round(api_time, 2)},
                    }

                # Parse GraphQL response
                try:
                    result = response.json()
                except Exception:
                    return {
                        "status": "error",
                        "action": action_name,
                        "error": "Failed to parse GraphQL response",
                        "status_code": response.status_code,
                        "timing_ms": {"api_request": round(api_time, 2)},
                    }

                # Check for GraphQL errors
                if "errors" in result:
                    errors = result["errors"]
                    error_messages = [e.get("message", str(e)) for e in errors]
                    error_str = "; ".join(error_messages)
                    logger.error(f"[ShopifyNode] GraphQL errors: {error_str}")
                    return {
                        "status": "error",
                        "action": action_name,
                        "error": error_str,
                        "graphql_errors": errors,
                        "status_code": response.status_code,
                        "timing_ms": {"api_request": round(api_time, 2)},
                    }

                return {
                    "status": "success",
                    "action": action_name,
                    "data": result.get("data", {}),
                    "extensions": result.get("extensions", {}),
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": round(api_time, 2)},
                }

            except httpx.TimeoutException:
                return {
                    "status": "error",
                    "action": action_name,
                    "error": "Request timed out",
                    "status_code": 408,
                    "timing_ms": {
                        "api_request": round((time.time() - start_time) * 1000, 2)
                    },
                }
            except Exception as e:
                logger.exception(f"[ShopifyNode] GraphQL request failed: {e}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": str(e),
                    "status_code": 500,
                    "timing_ms": {
                        "api_request": round((time.time() - start_time) * 1000, 2)
                    },
                }

    # =========================================================================
    # GraphQL Operation Handlers
    # =========================================================================

    async def _handle_graphql_query(
        self, config: ShopifyGraphQLQueryConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Execute a custom GraphQL query (100% API coverage)."""
        return await self._make_graphql_request(
            query=config.query,
            credentials=credentials,
            variables=config.variables,
            action_name="execute_custom_graphql_query",
        )

    async def _handle_graphql_mutation(
        self, config: ShopifyGraphQLMutationConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Execute a custom GraphQL mutation (100% API coverage)."""
        return await self._make_graphql_request(
            query=config.mutation,
            credentials=credentials,
            variables=config.variables,
            action_name="execute_custom_graphql_mutation",
        )

    async def _handle_graphql_products(
        self, config: ShopifyGraphQLProductsQueryConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Query products using GraphQL."""
        query = """
        query getProducts($first: Int, $query: String) {
            products(first: $first, query: $query) {
                edges {
                    node {
                        id
                        title
                        description
                        vendor
                        productType
                        tags
                        status
                        createdAt
                        updatedAt
                        variants(first: 10) {
                            edges {
                                node {
                                    id
                                    title
                                    price
                                    sku
                                    inventoryQuantity
                                }
                            }
                        }
                        images(first: 5) {
                            edges {
                                node {
                                    id
                                    url
                                    altText
                                }
                            }
                        }
                    }
                }
            }
        }
        """

        variables = {
            "first": config.first,
            "query": config.query,
        }

        return await self._make_graphql_request(
            query=query,
            credentials=credentials,
            variables=variables,
            action_name="query_products_with_graphql",
        )

    async def _handle_graphql_product_create(
        self, config: ShopifyGraphQLProductCreateConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Create a product using GraphQL."""
        mutation = """
        mutation productCreate($input: ProductInput!) {
            productCreate(input: $input) {
                product {
                    id
                    title
                    description
                    vendor
                    productType
                    tags
                    status
                }
                userErrors {
                    field
                    message
                }
            }
        }
        """

        return await self._make_graphql_request(
            query=mutation,
            credentials=credentials,
            variables={"input": config.input},
            action_name="create_product_with_graphql",
        )

    async def _handle_graphql_product_update(
        self, config: ShopifyGraphQLProductUpdateConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Update a product using GraphQL."""
        mutation = """
        mutation productUpdate($input: ProductInput!) {
            productUpdate(input: $input) {
                product {
                    id
                    title
                    description
                    vendor
                    productType
                    tags
                    status
                }
                userErrors {
                    field
                    message
                }
            }
        }
        """

        return await self._make_graphql_request(
            query=mutation,
            credentials=credentials,
            variables={"input": config.input},
            action_name="update_product_with_graphql",
        )

    async def _handle_graphql_orders(
        self, config: ShopifyGraphQLOrdersQueryConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Query orders using GraphQL."""
        query = """
        query getOrders($first: Int, $query: String) {
            orders(first: $first, query: $query) {
                edges {
                    node {
                        id
                        name
                        email
                        createdAt
                        displayFinancialStatus
                        displayFulfillmentStatus
                        totalPriceSet {
                            shopMoney {
                                amount
                                currencyCode
                            }
                        }
                        customer {
                            id
                            displayName
                            email
                        }
                        lineItems(first: 10) {
                            edges {
                                node {
                                    id
                                    title
                                    quantity
                                    variant {
                                        id
                                        title
                                        price
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        """

        variables = {
            "first": config.first,
            "query": config.query,
        }

        return await self._make_graphql_request(
            query=query,
            credentials=credentials,
            variables=variables,
            action_name="query_orders_with_graphql",
        )

    async def _handle_graphql_draft_order_create(
        self,
        config: ShopifyGraphQLDraftOrderCreateConfig,
        credentials: ShopifyCredential,
    ) -> Dict[str, Any]:
        """Create a draft order using GraphQL."""
        mutation = """
        mutation draftOrderCreate($input: DraftOrderInput!) {
            draftOrderCreate(input: $input) {
                draftOrder {
                    id
                    name
                    createdAt
                    totalPrice
                }
                userErrors {
                    field
                    message
                }
            }
        }
        """

        return await self._make_graphql_request(
            query=mutation,
            credentials=credentials,
            variables={"input": config.input},
            action_name="create_draft_order_with_graphql",
        )

    async def _handle_graphql_customers(
        self, config: ShopifyGraphQLCustomersQueryConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Query customers using GraphQL."""
        query = """
        query getCustomers($first: Int, $query: String) {
            customers(first: $first, query: $query) {
                edges {
                    node {
                        id
                        displayName
                        email
                        phone
                        createdAt
                        updatedAt
                        addresses(first: 5) {
                            address1
                            address2
                            city
                            province
                            country
                            zip
                        }
                        orders(first: 5) {
                            edges {
                                node {
                                    id
                                    name
                                    totalPriceSet {
                                        shopMoney {
                                            amount
                                            currencyCode
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        """

        variables = {
            "first": config.first,
            "query": config.query,
        }

        return await self._make_graphql_request(
            query=query,
            credentials=credentials,
            variables=variables,
            action_name="query_customers_with_graphql",
        )

    async def _handle_graphql_customer_create(
        self, config: ShopifyGraphQLCustomerCreateConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Create a customer using GraphQL."""
        mutation = """
        mutation customerCreate($input: CustomerInput!) {
            customerCreate(input: $input) {
                customer {
                    id
                    displayName
                    email
                    phone
                }
                userErrors {
                    field
                    message
                }
            }
        }
        """

        return await self._make_graphql_request(
            query=mutation,
            credentials=credentials,
            variables={"input": config.input},
            action_name="create_customer_with_graphql",
        )

    async def _handle_graphql_inventory(
        self, config: ShopifyGraphQLInventoryQueryConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Query inventory using GraphQL."""
        query = """
        query getInventoryItems($first: Int, $query: String) {
            inventoryItems(first: $first, query: $query) {
                edges {
                    node {
                        id
                        sku
                        tracked
                        inventoryLevels(first: 10) {
                            edges {
                                node {
                                    id
                                    available
                                    location {
                                        id
                                        name
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        """

        variables = {
            "first": config.first,
            "query": config.query,
        }

        return await self._make_graphql_request(
            query=query,
            credentials=credentials,
            variables=variables,
            action_name="query_inventory_with_graphql",
        )

    async def _handle_graphql_collections(
        self,
        config: ShopifyGraphQLCollectionsQueryConfig,
        credentials: ShopifyCredential,
    ) -> Dict[str, Any]:
        """Query collections using GraphQL."""
        query = """
        query getCollections($first: Int, $query: String) {
            collections(first: $first, query: $query) {
                edges {
                    node {
                        id
                        title
                        description
                        handle
                        productsCount
                        products(first: 10) {
                            edges {
                                node {
                                    id
                                    title
                                }
                            }
                        }
                    }
                }
            }
        }
        """

        variables = {
            "first": config.first,
            "query": config.query,
        }

        return await self._make_graphql_request(
            query=query,
            credentials=credentials,
            variables=variables,
            action_name="query_collections_with_graphql",
        )

    async def _handle_graphql_fulfillment_orders(
        self,
        config: ShopifyGraphQLFulfillmentOrdersQueryConfig,
        credentials: ShopifyCredential,
    ) -> Dict[str, Any]:
        """Query fulfillment orders using GraphQL."""
        query = """
        query getFulfillmentOrders($first: Int, $query: String) {
            fulfillmentOrders(first: $first, query: $query) {
                edges {
                    node {
                        id
                        status
                        createdAt
                        updatedAt
                        assignedLocation {
                            location {
                                id
                                name
                            }
                        }
                        lineItems(first: 10) {
                            edges {
                                node {
                                    id
                                    remainingQuantity
                                    lineItem {
                                        id
                                        name
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        """

        variables = {
            "first": config.first,
            "query": config.query,
        }

        return await self._make_graphql_request(
            query=query,
            credentials=credentials,
            variables=variables,
            action_name="query_fulfillment_orders_with_graphql",
        )

    async def _handle_graphql_shop(
        self, config: ShopifyGraphQLShopQueryConfig, credentials: ShopifyCredential
    ) -> Dict[str, Any]:
        """Get shop information using GraphQL."""
        query = """
        query {
            shop {
                id
                name
                email
                myshopifyDomain
                plan {
                    displayName
                }
                currencyCode
                timezoneAbbreviation
                primaryDomain {
                    url
                    host
                }
            }
        }
        """

        return await self._make_graphql_request(
            query=query, credentials=credentials, action_name="get_shop_with_graphql"
        )
