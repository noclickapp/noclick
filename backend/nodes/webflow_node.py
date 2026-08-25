"""
Webflow CMS / site automation node.

Provides workflow integration with the Webflow Data API (v2) for operations
including:
- Sites: list, get, publish, custom domains
- Pages: list, get/update metadata, get/update content (DOM)
- Components: list, get/update content (DOM), get/update properties
- Collections: list, get, create, delete; fields create/update/delete
- CMS Items: staged + live list/get/create/update/delete, bulk create, publish
- Forms: list, get schema, list submissions (by form + by site), get/modify/delete submission
- Assets: list/get/create/update/delete + asset folders
- Ecommerce: products (list/get/create/update) + SKUs (create/update) + inventory
  (get/update), orders (list/get/update/fulfill/unfulfill/refund), settings
- Comments: list threads, get thread, list replies
- Custom Code: register hosted/inline scripts, list registered, apply/remove on site + page
- Webhooks: list, get, create, remove
- Token: get authorized user, introspect
- Webhook Trigger: fire when a Webflow event occurs (form submission, site
  publish, CMS item changes, ecommerce events, etc.)

Note: the Users / Memberships API was removed by Webflow on 2026-01-29, so it is
intentionally not implemented.

Authentication: OAuth 2.0 (authorization_code; long-lived non-expiring tokens)
or a Bearer API token (Site Token / Workspace Token). Both are sent as the same
`Authorization: Bearer <token>` header.
API Base URL: https://api.webflow.com/v2
Documentation: https://developers.webflow.com/data/reference/rest-introduction
"""

import hashlib
import hmac
import json
import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator, create_model
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin
from nodes.scopes.webflow import WEBFLOW_SCOPES

logger = logging.getLogger(__name__)

WEBFLOW_API_BASE = "https://api.webflow.com/v2"

# Webhook trigger types Webflow can register via POST /sites/{site_id}/webhooks.
WEBFLOW_TRIGGER_TYPES = [
    "form_submission",
    "site_publish",
    "page_created",
    "page_metadata_updated",
    "page_deleted",
    "collection_item_created",
    "collection_item_changed",
    "collection_item_deleted",
    "collection_item_published",
    "collection_item_unpublished",
    "ecomm_new_order",
    "ecomm_order_changed",
    "ecomm_inventory_changed",
    "comment_created",
]

# (operation/triggerType, display name, description) for the one-trigger-per-event
# decomposition. The operation discriminator IS the Webflow triggerType, so webhook
# registration derives the triggerType straight from the selected operation.
WEBFLOW_TRIGGER_SPECS: List[tuple] = [
    ("form_submission", "On Form Submission", "Fires when a form is submitted on the site."),
    ("site_publish", "On Site Publish", "Fires when the site is published."),
    ("page_created", "On Page Created", "Fires when a page is created."),
    ("page_metadata_updated", "On Page Metadata Updated", "Fires when a page's metadata (SEO/slug/OG) changes."),
    ("page_deleted", "On Page Deleted", "Fires when a page is deleted."),
    ("collection_item_created", "On Collection Item Created", "Fires when a CMS collection item is created."),
    ("collection_item_changed", "On Collection Item Changed", "Fires when a CMS collection item is updated."),
    ("collection_item_deleted", "On Collection Item Deleted", "Fires when a CMS collection item is deleted."),
    ("collection_item_published", "On Collection Item Published", "Fires when a CMS collection item is published live."),
    ("collection_item_unpublished", "On Collection Item Unpublished", "Fires when a CMS collection item is unpublished."),
    ("ecomm_new_order", "On New Order", "Fires when a new ecommerce order is placed."),
    ("ecomm_order_changed", "On Order Changed", "Fires when an ecommerce order changes."),
    ("ecomm_inventory_changed", "On Inventory Changed", "Fires when ecommerce inventory changes."),
    ("comment_created", "On Comment Created", "Fires when a comment is created on the site."),
]


# ============================================================================
# Credential Schema
# ============================================================================


class WebflowApiTokenCredential(BaseModel):
    """API token credential for Webflow (Site Token or Workspace Token)."""

    credential_type: Literal["webflow_api_token"] = Field(
        "webflow_api_token", json_schema_extra={"ui:hidden": True}
    )
    api_token: str = Field(
        ...,
        title="API Token",
        description=(
            "A Webflow Site Token or Workspace Token. Generate a Site Token in "
            "Site Settings -> Apps & Integrations -> API access -> Generate API token."
        ),
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-url": "https://developers.webflow.com/data/reference/authentication"
        }
    )


class WebflowOAuthCredential(BaseModel):
    """OAuth 2.0 credential for Webflow (authorization_code flow).

    Tokens are obtained via the OAuth flow, not entered manually. Webflow OAuth
    access tokens are long-lived and non-expiring — there is no refresh flow, so
    refresh_token / expires_at are always empty (kept only for a uniform
    credential shape). Reconnect the account if a token is revoked.

    Register an OAuth app at: https://developers.webflow.com/data/docs/register-an-app
    """

    credential_type: Literal["webflow_oauth"] = Field(
        "webflow_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ...,
        title="Access Token",
        description="Webflow OAuth access token (Bearer).",
        json_schema_extra={"ui:widget": "password"},
    )
    refresh_token: Optional[str] = Field(None, title="Refresh Token")
    expires_at: Optional[str] = Field(None, title="Token Expiry")  # ISO 8601 (always None)
    name: Optional[str] = Field(None, title="User Name")
    email: Optional[str] = Field(None, title="Account Email")

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "webflow",
            "x-oauth-scopes": [
                "sites:read",
                "sites:write",
                "pages:read",
                "pages:write",
                "cms:read",
                "cms:write",
                "custom_code:read",
                "custom_code:write",
                "forms:read",
                "forms:write",
                "ecommerce:read",
                "ecommerce:write",
                "assets:read",
                "assets:write",
                "components:read",
                "components:write",
                "comments:read",
                "comments:write",
                "site_config:read",
                "site_config:write",
                "site_activity:read",
                "workspace:read",
                "workspace:write",
                "authorized_user:read",
            ],
            "x-oauth-supports-custom-client": True,
            "x-oauth-custom-client-help": (
                "Optionally bring your own Webflow OAuth app. Register one at "
                "https://developers.webflow.com/data/docs/register-an-app, set its "
                "redirect URI to NoClick's Webflow callback, and paste its client ID "
                "and secret here. Leave blank to use NoClick's shared Webflow app."
            ),
            "x-credential-url": "https://developers.webflow.com/data/docs/register-an-app",
        }
    )


WebflowCredential = Union[WebflowOAuthCredential, WebflowApiTokenCredential]


def _extract_token(credential: Optional[Dict[str, Any]]) -> Optional[str]:
    """Pull the bearer token from a Webflow credential dict, supporting both the
    OAuth credential (``access_token``) and the API-token credential
    (``api_token``)."""
    if not credential:
        return None
    return credential.get("access_token") or credential.get("api_token")


# ============================================================================
# Operation Configs — Sites
# ============================================================================


def _site_id_field(title: str = "Site") -> Any:
    return Field(
        ...,
        title=title,
        description="The Webflow site to operate on",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "site_id",
                "placeholder": "Select a site...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste site ID",
            }
        },
    )


def _collection_id_field() -> Any:
    return Field(
        ...,
        title="Collection ID",
        description="The CMS collection ID",
    )


def _order_id_field(description: str) -> Any:
    return Field(
        ...,
        title="Order ID",
        description=description,
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "order_id",
                "placeholder": "Select an order...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste order ID",
                "depends_on": "site_id",
            }
        },
    )


class WebflowListSitesConfig(BaseModel):
    """List all sites the token can access."""

    operation: Literal["list_sites"] = Field(
        "list_sites",
        json_schema_extra={
            "const": "list_sites",
            "ui:hidden": True,
            "x-category": "Sites",
            "x-is-trigger": False,
            "x-display-name": "List Sites",
        },
        title="List Sites",
    )


class WebflowGetSiteConfig(BaseModel):
    """Get details and metadata for a single site."""

    operation: Literal["get_site"] = Field(
        "get_site",
        json_schema_extra={
            "const": "get_site",
            "ui:hidden": True,
            "x-category": "Sites",
            "x-is-trigger": False,
            "x-display-name": "Get Site",
        },
        title="Get Site",
    )
    site_id: str = _site_id_field()


class WebflowPublishSiteConfig(BaseModel):
    """Publish a site to its domains (max 1 successful publish/min)."""

    operation: Literal["publish_site"] = Field(
        "publish_site",
        json_schema_extra={
            "const": "publish_site",
            "ui:hidden": True,
            "x-category": "Sites",
            "x-is-trigger": False,
            "x-display-name": "Publish Site",
        },
        title="Publish Site",
    )
    site_id: str = _site_id_field()
    publish_to_webflow_subdomain: str = Field(
        "true",
        title="Publish to Webflow Subdomain",
        description="Publish to the *.webflow.io staging domain",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    custom_domains: Optional[str] = Field(
        None,
        title="Custom Domain IDs",
        description="Comma-separated custom domain IDs to publish to (optional)",
    )


# ============================================================================
# Operation Configs — Pages
# ============================================================================


class WebflowListPagesConfig(BaseModel):
    """List all static pages on a site."""

    operation: Literal["list_pages"] = Field(
        "list_pages",
        json_schema_extra={
            "const": "list_pages",
            "ui:hidden": True,
            "x-category": "Pages",
            "x-is-trigger": False,
            "x-display-name": "List Pages",
        },
        title="List Pages",
    )
    site_id: str = _site_id_field()


class WebflowGetPageContentConfig(BaseModel):
    """Get a page's static (DOM) text content."""

    operation: Literal["get_page_content"] = Field(
        "get_page_content",
        json_schema_extra={
            "const": "get_page_content",
            "ui:hidden": True,
            "x-category": "Pages",
            "x-is-trigger": False,
            "x-display-name": "Get Page Content",
        },
        title="Get Page Content",
    )
    page_id: str = Field(..., title="Page ID", description="The page to read DOM content from")


class WebflowUpdatePageContentConfig(BaseModel):
    """Update a page's static text content (DOM nodes)."""

    operation: Literal["update_page_content"] = Field(
        "update_page_content",
        json_schema_extra={
            "const": "update_page_content",
            "ui:hidden": True,
            "x-category": "Pages",
            "x-is-trigger": False,
            "x-display-name": "Update Page Content",
        },
        title="Update Page Content",
    )
    page_id: str = Field(..., title="Page ID", description="The page to update DOM content on")
    nodes_json: str = Field(
        ...,
        title="DOM Nodes (JSON)",
        description='JSON array of DOM node updates, e.g. [{"nodeId":"...","text":"New text"}]',
        json_schema_extra={"ui:widget": "textarea"},
    )


# ============================================================================
# Operation Configs — Collections
# ============================================================================


class WebflowListCollectionsConfig(BaseModel):
    """List CMS collections on a site."""

    operation: Literal["list_collections"] = Field(
        "list_collections",
        json_schema_extra={
            "const": "list_collections",
            "ui:hidden": True,
            "x-category": "Collections",
            "x-is-trigger": False,
            "x-display-name": "List Collections",
        },
        title="List Collections",
    )
    site_id: str = _site_id_field()


class WebflowGetCollectionConfig(BaseModel):
    """Get a CMS collection's schema and fields."""

    operation: Literal["get_collection"] = Field(
        "get_collection",
        json_schema_extra={
            "const": "get_collection",
            "ui:hidden": True,
            "x-category": "Collections",
            "x-is-trigger": False,
            "x-display-name": "Get Collection Details",
        },
        title="Get Collection Details",
    )
    collection_id: str = _collection_id_field()


class WebflowCreateCollectionConfig(BaseModel):
    """Create a new CMS collection on a site."""

    operation: Literal["create_collection"] = Field(
        "create_collection",
        json_schema_extra={
            "const": "create_collection",
            "ui:hidden": True,
            "x-category": "Collections",
            "x-is-trigger": False,
            "x-display-name": "Create Collection",
        },
        title="Create Collection",
    )
    site_id: str = _site_id_field()
    display_name: str = Field(
        ..., title="Display Name", description="Human-readable name of the collection"
    )
    singular_name: str = Field(
        ..., title="Singular Name", description="Singular label for a single item"
    )
    slug: Optional[str] = Field(
        None, title="Slug", description="URL slug for the collection (optional)"
    )


class WebflowCreateCollectionFieldConfig(BaseModel):
    """Add a field to a CMS collection."""

    operation: Literal["create_collection_field"] = Field(
        "create_collection_field",
        json_schema_extra={
            "const": "create_collection_field",
            "ui:hidden": True,
            "x-category": "Collections",
            "x-is-trigger": False,
            "x-display-name": "Create Collection Field",
        },
        title="Create Collection Field",
    )
    collection_id: str = _collection_id_field()
    field_type: str = Field(
        ...,
        title="Field Type",
        description="The type of field to create",
        json_schema_extra={
            "enum": [
                "PlainText",
                "RichText",
                "Image",
                "MultiImage",
                "Video",
                "Link",
                "Email",
                "Phone",
                "Number",
                "DateTime",
                "Switch",
                "Color",
                "Option",
                "File",
                "Reference",
                "MultiReference",
            ],
            "x-enum-searchable": True,
        },
    )
    display_name: str = Field(
        ..., title="Display Name", description="Human-readable name of the field"
    )
    is_required: str = Field(
        "false",
        title="Required",
        description="Whether the field is required",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


# ============================================================================
# Operation Configs — CMS Items
# ============================================================================


class WebflowListItemsConfig(BaseModel):
    """List (staged) items in a CMS collection."""

    operation: Literal["list_items"] = Field(
        "list_items",
        json_schema_extra={
            "const": "list_items",
            "ui:hidden": True,
            "x-category": "CMS Items",
            "x-is-trigger": False,
            "x-display-name": "List Collection Items",
        },
        title="List Collection Items",
    )
    collection_id: str = _collection_id_field()
    limit: Optional[str] = Field(
        "100", title="Limit", description="Max items to return (1-100)"
    )
    offset: Optional[str] = Field(
        None, title="Offset", description="Number of items to skip for pagination"
    )


class WebflowGetItemConfig(BaseModel):
    """Get a single CMS item."""

    operation: Literal["get_item"] = Field(
        "get_item",
        json_schema_extra={
            "const": "get_item",
            "ui:hidden": True,
            "x-category": "CMS Items",
            "x-is-trigger": False,
            "x-display-name": "Get Collection Item",
        },
        title="Get Collection Item",
    )
    collection_id: str = _collection_id_field()
    item_id: str = Field(..., title="Item ID", description="The CMS item ID to retrieve")


class WebflowCreateItemConfig(BaseModel):
    """Create one or more staged CMS items."""

    operation: Literal["create_item"] = Field(
        "create_item",
        json_schema_extra={
            "const": "create_item",
            "ui:hidden": True,
            "x-category": "CMS Items",
            "x-is-trigger": False,
            "x-display-name": "Create Collection Item",
        },
        title="Create Collection Item",
    )
    collection_id: str = _collection_id_field()
    field_data_json: str = Field(
        ...,
        title="Field Data (JSON)",
        description=(
            'Item field values as JSON, e.g. {"name":"My Item","slug":"my-item"}. '
            "Include at least name and slug."
        ),
        json_schema_extra={"ui:widget": "textarea"},
    )
    is_archived: str = Field(
        "false",
        title="Archived",
        description="Create the item in an archived state",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )
    is_draft: str = Field(
        "false",
        title="Draft",
        description="Create the item in a draft state",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class WebflowCreateLiveItemConfig(BaseModel):
    """Create CMS item(s) directly on the live site."""

    operation: Literal["create_live_item"] = Field(
        "create_live_item",
        json_schema_extra={
            "const": "create_live_item",
            "ui:hidden": True,
            "x-category": "CMS Items",
            "x-is-trigger": False,
            "x-display-name": "Create Live Item",
        },
        title="Create Live Item",
    )
    collection_id: str = _collection_id_field()
    field_data_json: str = Field(
        ...,
        title="Field Data (JSON)",
        description='Item field values as JSON, e.g. {"name":"My Item","slug":"my-item"}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class WebflowUpdateItemConfig(BaseModel):
    """Update a staged CMS item."""

    operation: Literal["update_item"] = Field(
        "update_item",
        json_schema_extra={
            "const": "update_item",
            "ui:hidden": True,
            "x-category": "CMS Items",
            "x-is-trigger": False,
            "x-display-name": "Update Collection Item",
        },
        title="Update Collection Item",
    )
    collection_id: str = _collection_id_field()
    item_id: str = Field(..., title="Item ID", description="The CMS item ID to update")
    field_data_json: str = Field(
        ...,
        title="Field Data (JSON)",
        description='Updated field values as JSON, e.g. {"name":"New name"}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class WebflowDeleteItemConfig(BaseModel):
    """Delete a staged CMS item."""

    operation: Literal["delete_item"] = Field(
        "delete_item",
        json_schema_extra={
            "const": "delete_item",
            "ui:hidden": True,
            "x-category": "CMS Items",
            "x-is-trigger": False,
            "x-display-name": "Delete Collection Item",
        },
        title="Delete Collection Item",
    )
    collection_id: str = _collection_id_field()
    item_id: str = Field(..., title="Item ID", description="The CMS item ID to delete")


class WebflowPublishItemsConfig(BaseModel):
    """Publish staged CMS items to the live site."""

    operation: Literal["publish_items"] = Field(
        "publish_items",
        json_schema_extra={
            "const": "publish_items",
            "ui:hidden": True,
            "x-category": "CMS Items",
            "x-is-trigger": False,
            "x-display-name": "Publish Collection Items",
        },
        title="Publish Collection Items",
    )
    collection_id: str = _collection_id_field()
    item_ids: str = Field(
        ...,
        title="Item IDs",
        description="Comma-separated CMS item IDs to publish",
    )


# ============================================================================
# Operation Configs — Forms
# ============================================================================


class WebflowListFormsConfig(BaseModel):
    """List forms on a site."""

    operation: Literal["list_forms"] = Field(
        "list_forms",
        json_schema_extra={
            "const": "list_forms",
            "ui:hidden": True,
            "x-category": "Forms",
            "x-is-trigger": False,
            "x-display-name": "List Forms",
        },
        title="List Forms",
    )
    site_id: str = _site_id_field()


class WebflowGetFormConfig(BaseModel):
    """Get a form's field schema."""

    operation: Literal["get_form"] = Field(
        "get_form",
        json_schema_extra={
            "const": "get_form",
            "ui:hidden": True,
            "x-category": "Forms",
            "x-is-trigger": False,
            "x-display-name": "Get Form Schema",
        },
        title="Get Form Schema",
    )
    form_id: str = Field(..., title="Form ID", description="The form ID to retrieve")


class WebflowListFormSubmissionsConfig(BaseModel):
    """List submissions for a form."""

    operation: Literal["list_form_submissions"] = Field(
        "list_form_submissions",
        json_schema_extra={
            "const": "list_form_submissions",
            "ui:hidden": True,
            "x-category": "Forms",
            "x-is-trigger": False,
            "x-display-name": "List Form Submissions",
        },
        title="List Form Submissions",
    )
    site_id: str = _site_id_field()
    form_id: str = Field(
        ...,
        title="Form ID",
        description="The form whose submissions to list",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "form_id",
                "placeholder": "Select a form...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste form ID",
                "depends_on": "site_id",
            }
        },
    )
    limit: Optional[str] = Field(
        "100", title="Limit", description="Max submissions to return (1-100)"
    )


class WebflowGetFormSubmissionConfig(BaseModel):
    """Get a single form submission."""

    operation: Literal["get_form_submission"] = Field(
        "get_form_submission",
        json_schema_extra={
            "const": "get_form_submission",
            "ui:hidden": True,
            "x-category": "Forms",
            "x-is-trigger": False,
            "x-display-name": "Get Form Submission",
        },
        title="Get Form Submission",
    )
    site_id: str = _site_id_field()
    form_submission_id: str = Field(
        ..., title="Submission ID", description="The form submission ID to retrieve"
    )


# ============================================================================
# Operation Configs — Assets
# ============================================================================


class WebflowListAssetsConfig(BaseModel):
    """List a site's assets."""

    operation: Literal["list_assets"] = Field(
        "list_assets",
        json_schema_extra={
            "const": "list_assets",
            "ui:hidden": True,
            "x-category": "Assets",
            "x-is-trigger": False,
            "x-display-name": "List Assets",
        },
        title="List Assets",
    )
    site_id: str = _site_id_field()


# ============================================================================
# Operation Configs — Ecommerce
# ============================================================================


class WebflowListProductsConfig(BaseModel):
    """List ecommerce products and SKUs."""

    operation: Literal["list_products"] = Field(
        "list_products",
        json_schema_extra={
            "const": "list_products",
            "ui:hidden": True,
            "x-category": "Ecommerce",
            "x-is-trigger": False,
            "x-display-name": "List Products & SKUs",
        },
        title="List Products & SKUs",
    )
    site_id: str = _site_id_field()


class WebflowCreateProductConfig(BaseModel):
    """Create an ecommerce product and its default SKU."""

    operation: Literal["create_product"] = Field(
        "create_product",
        json_schema_extra={
            "const": "create_product",
            "ui:hidden": True,
            "x-category": "Ecommerce",
            "x-is-trigger": False,
            "x-display-name": "Create Product & SKU",
        },
        title="Create Product & SKU",
    )
    site_id: str = _site_id_field()
    product_field_data_json: str = Field(
        ...,
        title="Product Field Data (JSON)",
        description='Product field values as JSON, e.g. {"name":"T-Shirt","slug":"t-shirt"}',
        json_schema_extra={"ui:widget": "textarea"},
    )
    sku_field_data_json: str = Field(
        ...,
        title="SKU Field Data (JSON)",
        description='Default SKU field values as JSON, e.g. {"name":"Default","price":{"value":1000,"unit":"USD"}}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class WebflowListOrdersConfig(BaseModel):
    """List ecommerce orders."""

    operation: Literal["list_orders"] = Field(
        "list_orders",
        json_schema_extra={
            "const": "list_orders",
            "ui:hidden": True,
            "x-category": "Ecommerce",
            "x-is-trigger": False,
            "x-display-name": "List Orders",
        },
        title="List Orders",
    )
    site_id: str = _site_id_field()


class WebflowGetOrderConfig(BaseModel):
    """Get a single ecommerce order."""

    operation: Literal["get_order"] = Field(
        "get_order",
        json_schema_extra={
            "const": "get_order",
            "ui:hidden": True,
            "x-category": "Ecommerce",
            "x-is-trigger": False,
            "x-display-name": "Get Order",
        },
        title="Get Order",
    )
    site_id: str = _site_id_field()
    order_id: str = _order_id_field("The ecommerce order ID")


class WebflowFulfillOrderConfig(BaseModel):
    """Mark an ecommerce order as fulfilled."""

    operation: Literal["fulfill_order"] = Field(
        "fulfill_order",
        json_schema_extra={
            "const": "fulfill_order",
            "ui:hidden": True,
            "x-category": "Ecommerce",
            "x-is-trigger": False,
            "x-display-name": "Fulfill Order",
        },
        title="Fulfill Order",
    )
    site_id: str = _site_id_field()
    order_id: str = _order_id_field("The ecommerce order ID to fulfill")
    send_order_fulfilled_email: str = Field(
        "false",
        title="Send Fulfillment Email",
        description="Send the order-fulfilled email to the customer",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class WebflowListInventoryConfig(BaseModel):
    """Get inventory for a SKU."""

    operation: Literal["list_inventory"] = Field(
        "list_inventory",
        json_schema_extra={
            "const": "list_inventory",
            "ui:hidden": True,
            "x-category": "Ecommerce",
            "x-is-trigger": False,
            "x-display-name": "List Inventory",
        },
        title="List Inventory",
    )
    collection_id: str = Field(
        ..., title="SKU Collection ID", description="The SKU collection ID"
    )
    sku_id: str = Field(..., title="SKU ID", description="The SKU item ID")


# ============================================================================
# Operation Configs — Comments
# ============================================================================


class WebflowListCommentThreadsConfig(BaseModel):
    """List page-design comment threads."""

    operation: Literal["list_comment_threads"] = Field(
        "list_comment_threads",
        json_schema_extra={
            "const": "list_comment_threads",
            "ui:hidden": True,
            "x-category": "Comments",
            "x-is-trigger": False,
            "x-display-name": "List Comment Threads",
        },
        title="List Comment Threads",
    )
    site_id: str = _site_id_field()


# ============================================================================
# Operation Configs — Webhooks
# ============================================================================


class WebflowListWebhooksConfig(BaseModel):
    """List registered webhooks for a site."""

    operation: Literal["list_webhooks"] = Field(
        "list_webhooks",
        json_schema_extra={
            "const": "list_webhooks",
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-is-trigger": False,
            "x-display-name": "List Webhooks",
        },
        title="List Webhooks",
    )
    site_id: str = _site_id_field()


class WebflowCreateWebhookConfig(BaseModel):
    """Register a webhook (triggerType + url) for a site."""

    operation: Literal["create_webhook"] = Field(
        "create_webhook",
        json_schema_extra={
            "const": "create_webhook",
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-is-trigger": False,
            "x-display-name": "Create Webhook",
        },
        title="Create Webhook",
    )
    site_id: str = _site_id_field()
    trigger_type: str = Field(
        ...,
        title="Trigger Type",
        description="The Webflow event that fires this webhook",
        json_schema_extra={
            "enum": WEBFLOW_TRIGGER_TYPES,
            "x-enum-searchable": True,
        },
    )
    url: str = Field(..., title="Subscriber URL", description="URL Webflow will POST events to")


class WebflowRemoveWebhookConfig(BaseModel):
    """Delete a registered webhook."""

    operation: Literal["remove_webhook"] = Field(
        "remove_webhook",
        json_schema_extra={
            "const": "remove_webhook",
            "ui:hidden": True,
            "x-category": "Webhooks",
            "x-is-trigger": False,
            "x-display-name": "Remove Webhook",
        },
        title="Remove Webhook",
    )
    webhook_id: str = Field(..., title="Webhook ID", description="The webhook ID to delete")


# ============================================================================
# Operation Configs — Token
# ============================================================================


class WebflowGetAuthorizedUserConfig(BaseModel):
    """Get info about the user who authorized the token."""

    operation: Literal["get_authorized_user"] = Field(
        "get_authorized_user",
        json_schema_extra={
            "const": "get_authorized_user",
            "ui:hidden": True,
            "x-category": "Token",
            "x-is-trigger": False,
            "x-display-name": "Get Authorized User",
        },
        title="Get Authorized User",
    )


def _json_field(title: str, desc: str) -> Any:
    return Field(..., title=title, description=desc, json_schema_extra={"ui:widget": "textarea"})


def _yn(title: str, desc: str, default: str = "false") -> Any:
    return Field(default, title=title, description=desc, json_schema_extra={
        "enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True})


def _op(name: str, category: str, display: str) -> Any:
    return Field(name, title=display, json_schema_extra={
        "const": name, "ui:hidden": True, "x-category": category,
        "x-is-trigger": False, "x-display-name": display})


# --- Sites (extra) ---
class WebflowGetCustomDomainsConfig(BaseModel):
    """List a site's custom domains (IDs used when publishing)."""
    operation: Literal["get_custom_domains"] = _op("get_custom_domains", "Sites", "Get Custom Domains")
    site_id: str = _site_id_field()


# --- Pages (metadata) ---
class WebflowGetPageMetadataConfig(BaseModel):
    """Get a page's metadata (SEO, Open Graph, slug, draft state)."""
    operation: Literal["get_page_metadata"] = _op("get_page_metadata", "Pages", "Get Page Metadata")
    page_id: str = Field(..., title="Page ID", description="The page to read metadata from")


class WebflowUpdatePageMetadataConfig(BaseModel):
    """Update a page's metadata (title, slug, SEO, Open Graph)."""
    operation: Literal["update_page_metadata"] = _op("update_page_metadata", "Pages", "Update Page Metadata")
    page_id: str = Field(..., title="Page ID", description="The page to update")
    metadata_json: str = _json_field("Metadata (JSON)", 'e.g. {"title":"Home","seo":{"title":"...","description":"..."}}')


# --- Components ---
class WebflowListComponentsConfig(BaseModel):
    """List a site's components."""
    operation: Literal["list_components"] = _op("list_components", "Components", "List Components")
    site_id: str = _site_id_field()


class WebflowGetComponentContentConfig(BaseModel):
    """Get a component's content (DOM node tree)."""
    operation: Literal["get_component_content"] = _op("get_component_content", "Components", "Get Component Content")
    site_id: str = _site_id_field()
    component_id: str = Field(..., title="Component ID", description="The component ID")


class WebflowUpdateComponentContentConfig(BaseModel):
    """Update a component's static content (DOM nodes)."""
    operation: Literal["update_component_content"] = _op("update_component_content", "Components", "Update Component Content")
    site_id: str = _site_id_field()
    component_id: str = Field(..., title="Component ID", description="The component ID")
    nodes_json: str = _json_field("DOM Nodes (JSON)", 'JSON array of node updates')


class WebflowGetComponentPropertiesConfig(BaseModel):
    """Get a component's properties."""
    operation: Literal["get_component_properties"] = _op("get_component_properties", "Components", "Get Component Properties")
    site_id: str = _site_id_field()
    component_id: str = Field(..., title="Component ID", description="The component ID")


class WebflowUpdateComponentPropertiesConfig(BaseModel):
    """Update a component's properties."""
    operation: Literal["update_component_properties"] = _op("update_component_properties", "Components", "Update Component Properties")
    site_id: str = _site_id_field()
    component_id: str = Field(..., title="Component ID", description="The component ID")
    properties_json: str = _json_field("Properties (JSON)", 'JSON array of property overrides')


# --- Collections (extra) ---
class WebflowDeleteCollectionConfig(BaseModel):
    """Delete a CMS collection."""
    operation: Literal["delete_collection"] = _op("delete_collection", "Collections", "Delete Collection")
    collection_id: str = _collection_id_field()


class WebflowUpdateCollectionFieldConfig(BaseModel):
    """Update a collection field's display name / required / help text (type is immutable)."""
    operation: Literal["update_collection_field"] = _op("update_collection_field", "Collections", "Update Collection Field")
    collection_id: str = _collection_id_field()
    field_id: str = Field(..., title="Field ID", description="The field to update")
    display_name: Optional[str] = Field(None, title="Display Name", description="New display name")
    is_required: Optional[str] = Field(None, title="Required", description="Whether the field is required",
        json_schema_extra={"enum": ["", "true", "false"], "enumNames": ["Unchanged", "Yes", "No"], "x-enum-searchable": True})
    help_text: Optional[str] = Field(None, title="Help Text", description="Help text shown in the editor")


class WebflowDeleteCollectionFieldConfig(BaseModel):
    """Delete a field from a collection."""
    operation: Literal["delete_collection_field"] = _op("delete_collection_field", "Collections", "Delete Collection Field")
    collection_id: str = _collection_id_field()
    field_id: str = Field(..., title="Field ID", description="The field to delete")


# --- CMS Items (live + bulk) ---
class WebflowListLiveItemsConfig(BaseModel):
    """List published (live) items in a collection."""
    operation: Literal["list_live_items"] = _op("list_live_items", "CMS Items", "List Live Items")
    collection_id: str = _collection_id_field()
    limit: Optional[str] = Field("100", title="Limit", description="Max items (1-100)")
    offset: Optional[str] = Field(None, title="Offset", description="Items to skip")


class WebflowGetLiveItemConfig(BaseModel):
    """Get a single published (live) CMS item."""
    operation: Literal["get_live_item"] = _op("get_live_item", "CMS Items", "Get Live Item")
    collection_id: str = _collection_id_field()
    item_id: str = Field(..., title="Item ID", description="The live item ID")


class WebflowUpdateLiveItemConfig(BaseModel):
    """Update a published (live) CMS item."""
    operation: Literal["update_live_item"] = _op("update_live_item", "CMS Items", "Update Live Item")
    collection_id: str = _collection_id_field()
    item_id: str = Field(..., title="Item ID", description="The live item ID")
    field_data_json: str = _json_field("Field Data (JSON)", 'Updated field values, e.g. {"name":"New"}')


class WebflowDeleteLiveItemConfig(BaseModel):
    """Unpublish (delete-live) a CMS item from the live site."""
    operation: Literal["delete_live_item"] = _op("delete_live_item", "CMS Items", "Unpublish Live Item")
    collection_id: str = _collection_id_field()
    item_id: str = Field(..., title="Item ID", description="The live item ID to unpublish")


class WebflowCreateBulkItemsConfig(BaseModel):
    """Create multiple CMS items at once (up to 100, multi-locale)."""
    operation: Literal["create_bulk_items"] = _op("create_bulk_items", "CMS Items", "Create Items (Bulk)")
    collection_id: str = _collection_id_field()
    items_json: str = _json_field("Items (JSON)", 'JSON array of item objects with fieldData')


# --- Ecommerce (extra) ---
class WebflowGetProductConfig(BaseModel):
    """Get a product and its SKUs."""
    operation: Literal["get_product"] = _op("get_product", "Ecommerce", "Get Product")
    site_id: str = _site_id_field()
    product_id: str = Field(..., title="Product ID", description="The product ID")


class WebflowUpdateProductConfig(BaseModel):
    """Update a product's field data."""
    operation: Literal["update_product"] = _op("update_product", "Ecommerce", "Update Product")
    site_id: str = _site_id_field()
    product_id: str = Field(..., title="Product ID", description="The product ID")
    product_field_data_json: str = _json_field("Product Field Data (JSON)", 'e.g. {"name":"New name"}')


class WebflowCreateSkusConfig(BaseModel):
    """Create additional SKUs for a product."""
    operation: Literal["create_skus"] = _op("create_skus", "Ecommerce", "Create SKUs")
    site_id: str = _site_id_field()
    product_id: str = Field(..., title="Product ID", description="The product to add SKUs to")
    skus_json: str = _json_field("SKUs (JSON)", 'JSON array of SKU objects with fieldData')


class WebflowUpdateSkuConfig(BaseModel):
    """Update a single SKU."""
    operation: Literal["update_sku"] = _op("update_sku", "Ecommerce", "Update SKU")
    site_id: str = _site_id_field()
    product_id: str = Field(..., title="Product ID", description="The product ID")
    sku_id: str = Field(..., title="SKU ID", description="The SKU ID")
    sku_field_data_json: str = _json_field("SKU Field Data (JSON)", 'e.g. {"price":{"value":1500,"unit":"USD"}}')


class WebflowUpdateInventoryConfig(BaseModel):
    """Update inventory for a SKU."""
    operation: Literal["update_inventory"] = _op("update_inventory", "Ecommerce", "Update Inventory")
    collection_id: str = Field(..., title="SKU Collection ID", description="The SKU collection ID")
    sku_id: str = Field(..., title="SKU ID", description="The SKU item ID")
    inventory_json: str = _json_field("Inventory (JSON)", 'e.g. {"inventoryType":"finite","quantity":10} or {"updateQuantity":-1}')


class WebflowGetEcommerceSettingsConfig(BaseModel):
    """Get a site's ecommerce settings (default currency, etc.)."""
    operation: Literal["get_ecommerce_settings"] = _op("get_ecommerce_settings", "Ecommerce", "Get Ecommerce Settings")
    site_id: str = _site_id_field()


class WebflowUpdateOrderConfig(BaseModel):
    """Update an order (comment, shipping provider/tracking)."""
    operation: Literal["update_order"] = _op("update_order", "Ecommerce", "Update Order")
    site_id: str = _site_id_field()
    order_id: str = _order_id_field("The order ID to update")
    order_json: str = _json_field("Order Fields (JSON)", 'e.g. {"comment":"...","shippingTracking":"..."}')


class WebflowUnfulfillOrderConfig(BaseModel):
    """Mark an order as unfulfilled."""
    operation: Literal["unfulfill_order"] = _op("unfulfill_order", "Ecommerce", "Unfulfill Order")
    site_id: str = _site_id_field()
    order_id: str = _order_id_field("The order ID to unfulfill")


class WebflowRefundOrderConfig(BaseModel):
    """Refund an order."""
    operation: Literal["refund_order"] = _op("refund_order", "Ecommerce", "Refund Order")
    site_id: str = _site_id_field()
    order_id: str = _order_id_field("The order ID to refund")
    reason: str = Field("requested", title="Reason", description="Refund reason",
        json_schema_extra={"enum": ["requested", "duplicate", "fraudulent"], "x-enum-searchable": True})


# --- Forms (extra) ---
class WebflowListSiteFormSubmissionsConfig(BaseModel):
    """List all form submissions across a site."""
    operation: Literal["list_site_form_submissions"] = _op("list_site_form_submissions", "Forms", "List Site Form Submissions")
    site_id: str = _site_id_field()
    limit: Optional[str] = Field("100", title="Limit", description="Max submissions (1-100)")
    offset: Optional[str] = Field(None, title="Offset", description="Submissions to skip")


class WebflowModifySubmissionConfig(BaseModel):
    """Modify a form submission (hidden fields only)."""
    operation: Literal["modify_submission"] = _op("modify_submission", "Forms", "Modify Submission")
    form_submission_id: str = Field(..., title="Submission ID", description="The submission to modify")
    data_json: str = _json_field("Data (JSON)", 'Hidden field updates, e.g. {"formSubmissionData":{"key":"value"}}')


class WebflowDeleteSubmissionConfig(BaseModel):
    """Delete a form submission."""
    operation: Literal["delete_submission"] = _op("delete_submission", "Forms", "Delete Submission")
    form_submission_id: str = Field(..., title="Submission ID", description="The submission to delete")


# --- Assets ---
class WebflowGetAssetConfig(BaseModel):
    """Get a single asset's metadata."""
    operation: Literal["get_asset"] = _op("get_asset", "Assets", "Get Asset")
    asset_id: str = Field(..., title="Asset ID", description="The asset ID")


class WebflowCreateAssetConfig(BaseModel):
    """Create an asset (step 1: returns a presigned S3 upload URL to POST bytes to)."""
    operation: Literal["create_asset"] = _op("create_asset", "Assets", "Create Asset (Get Upload URL)")
    site_id: str = _site_id_field()
    file_name: str = Field(..., title="File Name", description="The asset file name (e.g. logo.png)")
    file_hash: str = Field(..., title="File Hash (MD5)", description="MD5 hash of the file contents")
    parent_folder: Optional[str] = Field(None, title="Parent Folder ID", description="Asset folder to upload into (optional)")


class WebflowUpdateAssetConfig(BaseModel):
    """Update an asset's display name / alt text."""
    operation: Literal["update_asset"] = _op("update_asset", "Assets", "Update Asset")
    asset_id: str = Field(..., title="Asset ID", description="The asset ID")
    display_name: Optional[str] = Field(None, title="Display Name", description="New display name")
    alt_text: Optional[str] = Field(None, title="Alt Text", description="New alt text")


class WebflowDeleteAssetConfig(BaseModel):
    """Delete an asset."""
    operation: Literal["delete_asset"] = _op("delete_asset", "Assets", "Delete Asset")
    asset_id: str = Field(..., title="Asset ID", description="The asset ID to delete")


class WebflowListAssetFoldersConfig(BaseModel):
    """List a site's asset folders."""
    operation: Literal["list_asset_folders"] = _op("list_asset_folders", "Assets", "List Asset Folders")
    site_id: str = _site_id_field()


class WebflowGetAssetFolderConfig(BaseModel):
    """Get a single asset folder."""
    operation: Literal["get_asset_folder"] = _op("get_asset_folder", "Assets", "Get Asset Folder")
    asset_folder_id: str = Field(..., title="Asset Folder ID", description="The asset folder ID")


class WebflowCreateAssetFolderConfig(BaseModel):
    """Create an asset folder."""
    operation: Literal["create_asset_folder"] = _op("create_asset_folder", "Assets", "Create Asset Folder")
    site_id: str = _site_id_field()
    display_name: str = Field(..., title="Display Name", description="Folder name")
    parent_folder: Optional[str] = Field(None, title="Parent Folder ID", description="Parent folder (optional)")


# --- Comments (extra) ---
class WebflowGetCommentThreadConfig(BaseModel):
    """Get a single comment thread."""
    operation: Literal["get_comment_thread"] = _op("get_comment_thread", "Comments", "Get Comment Thread")
    site_id: str = _site_id_field()
    comment_thread_id: str = Field(..., title="Thread ID", description="The comment thread ID")


class WebflowListCommentRepliesConfig(BaseModel):
    """List replies in a comment thread."""
    operation: Literal["list_comment_replies"] = _op("list_comment_replies", "Comments", "List Comment Replies")
    site_id: str = _site_id_field()
    comment_thread_id: str = Field(..., title="Thread ID", description="The comment thread ID")


# --- Webhooks (extra) + Token introspect ---
class WebflowGetWebhookConfig(BaseModel):
    """Get a single registered webhook."""
    operation: Literal["get_webhook"] = _op("get_webhook", "Webhooks", "Get Webhook")
    webhook_id: str = Field(..., title="Webhook ID", description="The webhook ID")


class WebflowIntrospectTokenConfig(BaseModel):
    """Introspect the token — scopes, rate limit, authorized sites/workspaces."""
    operation: Literal["introspect_token"] = _op("introspect_token", "Token", "Introspect Token")


# --- Custom Code (OAuth App tokens only) ---
class WebflowRegisterHostedScriptConfig(BaseModel):
    """Register a hosted custom-code script to the site's library."""
    operation: Literal["register_hosted_script"] = _op("register_hosted_script", "Custom Code", "Register Hosted Script")
    site_id: str = _site_id_field()
    script_json: str = _json_field("Script (JSON)", 'e.g. {"hostedLocation":"https://...","integrityHash":"sha384-...","version":"1.0.0"}')


class WebflowRegisterInlineScriptConfig(BaseModel):
    """Register an inline custom-code script (<=2000 chars) to the site's library."""
    operation: Literal["register_inline_script"] = _op("register_inline_script", "Custom Code", "Register Inline Script")
    site_id: str = _site_id_field()
    script_json: str = _json_field("Script (JSON)", 'e.g. {"sourceCode":"console.log(1)","version":"1.0.0","displayName":"My Script"}')


class WebflowListRegisteredScriptsConfig(BaseModel):
    """List custom-code scripts registered to a site."""
    operation: Literal["list_registered_scripts"] = _op("list_registered_scripts", "Custom Code", "List Registered Scripts")
    site_id: str = _site_id_field()


class WebflowGetSiteCustomCodeConfig(BaseModel):
    """Get the scripts applied to a site."""
    operation: Literal["get_site_custom_code"] = _op("get_site_custom_code", "Custom Code", "Get Site Custom Code")
    site_id: str = _site_id_field()


class WebflowApplySiteCustomCodeConfig(BaseModel):
    """Apply scripts to a site (full-array upsert)."""
    operation: Literal["apply_site_custom_code"] = _op("apply_site_custom_code", "Custom Code", "Apply Site Custom Code")
    site_id: str = _site_id_field()
    scripts_json: str = _json_field("Scripts (JSON)", 'e.g. {"scripts":[{"id":"...","location":"header","version":"1.0.0"}]}')


class WebflowRemoveSiteCustomCodeConfig(BaseModel):
    """Remove all scripts applied to a site."""
    operation: Literal["remove_site_custom_code"] = _op("remove_site_custom_code", "Custom Code", "Remove Site Custom Code")
    site_id: str = _site_id_field()


class WebflowGetPageCustomCodeConfig(BaseModel):
    """Get the scripts applied to a page."""
    operation: Literal["get_page_custom_code"] = _op("get_page_custom_code", "Custom Code", "Get Page Custom Code")
    page_id: str = Field(..., title="Page ID", description="The page ID")


class WebflowApplyPageCustomCodeConfig(BaseModel):
    """Apply scripts to a page (full-array upsert)."""
    operation: Literal["apply_page_custom_code"] = _op("apply_page_custom_code", "Custom Code", "Apply Page Custom Code")
    page_id: str = Field(..., title="Page ID", description="The page ID")
    scripts_json: str = _json_field("Scripts (JSON)", 'e.g. {"scripts":[{"id":"...","location":"header","version":"1.0.0"}]}')


class WebflowRemovePageCustomCodeConfig(BaseModel):
    """Remove all scripts applied to a page."""
    operation: Literal["remove_page_custom_code"] = _op("remove_page_custom_code", "Custom Code", "Remove Page Custom Code")
    page_id: str = Field(..., title="Page ID", description="The page ID")


# ============================================================================
# Webhook Trigger Config
# ============================================================================


class _WebflowWebhookTrigger(BaseModel):
    """Base for Webflow per-event webhook triggers. Each concrete trigger registers
    one Webflow webhook whose triggerType is the subclass's operation discriminator."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    site_id: str = _site_id_field()
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="Webflow posts events here. Registered automatically when you connect credentials.",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:copyable": True,
            "ui:loadValue": True,
        },
    )
    webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    external_webhook_id: Optional[str] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    signing_secret: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    relay_connected: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    is_production: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    trigger_registered: Optional[bool] = Field(
        default=None, json_schema_extra={"ui:hidden": True}
    )
    trigger_error: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})


def _make_webflow_trigger(operation: str, display: str, description: str) -> type:
    return create_model(
        f"Webflow{''.join(p.capitalize() for p in operation.split('_'))}Trigger",
        __base__=_WebflowWebhookTrigger,
        __doc__=description,
        operation=(
            Literal[operation],
            Field(
                operation,
                title=display,
                description=description,
                json_schema_extra={
                    "const": operation,
                    "ui:hidden": True,
                    "x-category": "Triggers",
                    "x-is-trigger": True,
                    "x-display-name": display,
                },
            ),
        ),
    )


# op -> concrete trigger config class (one operation per Webflow event type).
WEBFLOW_TRIGGER_CONFIGS: Dict[str, type] = {
    op: _make_webflow_trigger(op, display, desc)
    for op, display, desc in WEBFLOW_TRIGGER_SPECS
}


# ============================================================================
# Discriminated Union
# ============================================================================


WebflowConfig = Annotated[
    Union[
        WebflowListSitesConfig,
        WebflowGetSiteConfig,
        WebflowPublishSiteConfig,
        WebflowListPagesConfig,
        WebflowGetPageContentConfig,
        WebflowUpdatePageContentConfig,
        WebflowListCollectionsConfig,
        WebflowGetCollectionConfig,
        WebflowCreateCollectionConfig,
        WebflowCreateCollectionFieldConfig,
        WebflowListItemsConfig,
        WebflowGetItemConfig,
        WebflowCreateItemConfig,
        WebflowCreateLiveItemConfig,
        WebflowUpdateItemConfig,
        WebflowDeleteItemConfig,
        WebflowPublishItemsConfig,
        WebflowListFormsConfig,
        WebflowGetFormConfig,
        WebflowListFormSubmissionsConfig,
        WebflowGetFormSubmissionConfig,
        WebflowListAssetsConfig,
        WebflowListProductsConfig,
        WebflowCreateProductConfig,
        WebflowListOrdersConfig,
        WebflowGetOrderConfig,
        WebflowFulfillOrderConfig,
        WebflowListInventoryConfig,
        WebflowListCommentThreadsConfig,
        WebflowListWebhooksConfig,
        WebflowCreateWebhookConfig,
        WebflowRemoveWebhookConfig,
        WebflowGetAuthorizedUserConfig,
        WebflowGetCustomDomainsConfig,
        WebflowGetPageMetadataConfig,
        WebflowUpdatePageMetadataConfig,
        WebflowListComponentsConfig,
        WebflowGetComponentContentConfig,
        WebflowUpdateComponentContentConfig,
        WebflowGetComponentPropertiesConfig,
        WebflowUpdateComponentPropertiesConfig,
        WebflowDeleteCollectionConfig,
        WebflowUpdateCollectionFieldConfig,
        WebflowDeleteCollectionFieldConfig,
        WebflowListLiveItemsConfig,
        WebflowGetLiveItemConfig,
        WebflowUpdateLiveItemConfig,
        WebflowDeleteLiveItemConfig,
        WebflowCreateBulkItemsConfig,
        WebflowGetProductConfig,
        WebflowUpdateProductConfig,
        WebflowCreateSkusConfig,
        WebflowUpdateSkuConfig,
        WebflowUpdateInventoryConfig,
        WebflowGetEcommerceSettingsConfig,
        WebflowUpdateOrderConfig,
        WebflowUnfulfillOrderConfig,
        WebflowRefundOrderConfig,
        WebflowListSiteFormSubmissionsConfig,
        WebflowModifySubmissionConfig,
        WebflowDeleteSubmissionConfig,
        WebflowGetAssetConfig,
        WebflowCreateAssetConfig,
        WebflowUpdateAssetConfig,
        WebflowDeleteAssetConfig,
        WebflowListAssetFoldersConfig,
        WebflowGetAssetFolderConfig,
        WebflowCreateAssetFolderConfig,
        WebflowGetCommentThreadConfig,
        WebflowListCommentRepliesConfig,
        WebflowGetWebhookConfig,
        WebflowIntrospectTokenConfig,
        WebflowRegisterHostedScriptConfig,
        WebflowRegisterInlineScriptConfig,
        WebflowListRegisteredScriptsConfig,
        WebflowGetSiteCustomCodeConfig,
        WebflowApplySiteCustomCodeConfig,
        WebflowRemoveSiteCustomCodeConfig,
        WebflowGetPageCustomCodeConfig,
        WebflowApplyPageCustomCodeConfig,
        WebflowRemovePageCustomCodeConfig,
        *WEBFLOW_TRIGGER_CONFIGS.values(),
    ],
    Discriminator("operation"),
]


class WebflowNodeConfig(NodeConfig[WebflowConfig, WebflowCredential]):
    """Full configuration for the Webflow node including credentials."""

    pass


# ============================================================================
# HTTP Request Helper
# ============================================================================


def _comma_list(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [p.strip() for p in value.split(",") if p.strip()]


def _parse_json_obj(value: str, field_label: str) -> Any:
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError) as e:
        raise ValueError(f"{field_label} must be valid JSON: {e}")


async def _webflow_request(
    api_token: str,
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated Webflow Data API v2 request, return a structured result."""
    url = f"{WEBFLOW_API_BASE}{endpoint}"
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}

    start = time.time()
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.request(
                method=method, url=url, headers=headers, params=params, json=json_body
            )
            api_ms = round((time.time() - start) * 1000, 2)
            if response.status_code >= 400:
                try:
                    err = response.json()
                    message = (
                        err.get("message")
                        or err.get("msg")
                        or err.get("error")
                        or str(err)
                    )
                except Exception:
                    message = response.text
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[WebflowNode] API error ({action_name}): {message}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": message,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }
            if response.status_code == 204:
                data: Any = {"success": True}
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
                "timing_ms": {"api_request": api_ms},
            }
        except httpx.TimeoutException:
            return {
                "status": "error",
                "action": action_name,
                "error": "Request timed out",
                "status_code": 408,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }
        except Exception as e:
            msg = str(e).encode("ascii", errors="replace").decode("ascii")
            logger.error(f"[WebflowNode] Request failed ({action_name}): {msg}")
            return {
                "status": "error",
                "action": action_name,
                "error": msg,
                "status_code": 500,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }


# ============================================================================
# Node Implementation
# ============================================================================


class WebflowNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """Webflow CMS / site automation node."""

    edit_examples = [
        "List all sites in my Webflow workspace",
        "Create a new CMS item in a blog collection",
        "Publish staged CMS items to the live site",
        "List submissions for a contact form",
        "Trigger a workflow whenever a Webflow form is submitted",
    ]

    scope_registry = WEBFLOW_SCOPES
    connection_evidence = ConnectionEvidence(
        field="site_id",
        noun="sites",
    )

    @classmethod
    def get_config_model(cls):
        return WebflowNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        """Refresh an expiring Webflow OAuth token at credential load (dropdowns,
        trigger registration). Webflow tokens are non-expiring and carry no
        refresh_token, so the shared choke point short-circuits to a no-op; the
        override exists to satisfy the rotating-OAuth structural guard and to
        stay uniform with other OAuth nodes."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.webflow_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token,
            provider="webflow",
        )

    # ------------------------------------------------------------------
    # Dynamic options (sites)
    # ------------------------------------------------------------------
    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Load dropdown options. ``credential_data`` arrives already decrypted
        from the handler (supports both the OAuth and API-token credential)."""
        if field_name not in ("site_id", "form_id", "order_id"):
            return {"options": []}
        api_token = _extract_token(credential_data)
        if not api_token:
            return {"options": []}

        if field_name == "site_id":
            return await cls._load_site_options(api_token)

        # form_id / order_id both depend on a chosen site_id.
        site_id = cls._depends_value(context, "site_id")
        if not site_id:
            return {"options": []}
        if field_name == "form_id":
            return await cls._load_form_options(api_token, site_id)
        return await cls._load_order_options(api_token, site_id)

    @staticmethod
    def _depends_value(config_data: Dict[str, Any], key: str) -> Optional[str]:
        """Read a parent field value, tolerating a ``config``-nested shape."""
        config_data = config_data or {}
        nested = config_data.get("config")
        if isinstance(nested, dict) and nested.get(key):
            return nested.get(key)
        return config_data.get(key)

    @classmethod
    async def _load_site_options(cls, api_token: str) -> Dict[str, Any]:
        result = await _webflow_request(api_token, "GET", "/sites", action_name="list_sites")
        if result.get("status") != "success":
            return {"options": []}
        data = result.get("data") or {}
        sites = data.get("sites") if isinstance(data, dict) else data
        options = []
        for site in sites or []:
            if not isinstance(site, dict):
                continue
            site_id = site.get("id")
            name = site.get("displayName") or site.get("shortName") or site_id
            if site_id:
                options.append({"label": str(name), "value": str(site_id)})
        return {"options": options}

    @classmethod
    async def _load_form_options(cls, api_token: str, site_id: str) -> Dict[str, Any]:
        result = await _webflow_request(
            api_token, "GET", f"/sites/{site_id}/forms", action_name="list_forms"
        )
        if result.get("status") != "success":
            return {"options": []}
        data = result.get("data") or {}
        forms = data.get("forms") if isinstance(data, dict) else data
        options = []
        for form in forms or []:
            if not isinstance(form, dict):
                continue
            form_id = form.get("id")
            name = form.get("displayName") or form_id
            if form_id:
                options.append({"label": str(name), "value": str(form_id)})
        return {"options": options}

    @classmethod
    async def _load_order_options(cls, api_token: str, site_id: str) -> Dict[str, Any]:
        result = await _webflow_request(
            api_token, "GET", f"/sites/{site_id}/orders", action_name="list_orders"
        )
        if result.get("status") != "success":
            return {"options": []}
        data = result.get("data") or {}
        orders = data.get("orders") if isinstance(data, dict) else data
        options = []
        for order in orders or []:
            if not isinstance(order, dict):
                continue
            order_id = order.get("orderId") or order.get("id")
            if not order_id:
                continue
            customer = (order.get("customerInfo") or {}).get("fullName")
            status = order.get("status")
            label = order_id
            if customer:
                label = f"{order_id} - {customer}"
            elif status:
                label = f"{order_id} ({status})"
            options.append({"label": str(label), "value": str(order_id)})
        return {"options": options}

    # ------------------------------------------------------------------
    # Webhook trigger registration
    # ------------------------------------------------------------------
    @classmethod
    def registration_fingerprint_fields(cls, config):
        # Config fields the provider-side registration depends on — feed the
        # reconciler's fingerprint so edits here re-register (declarative:
        # the node never sequences teardown/re-register).
        return {
            "site_id": (config or {}).get("site_id"),
        }

    @classmethod
    async def _register_external_webhook(
        cls, *, webhook_url: str, credential: Dict[str, Any], config: Dict[str, Any], node_id: str
    ) -> Optional[Dict[str, Any]]:
        api_token = _extract_token(credential)
        if not api_token:
            raise ValueError("A Webflow credential is required to register the trigger")
        site_id = (config or {}).get("site_id")
        if not site_id:
            raise ValueError("A site must be selected to register the trigger")
        trigger_type = (config or {}).get("operation")
        if trigger_type not in WEBFLOW_TRIGGER_TYPES:
            raise ValueError(f"Unsupported Webflow trigger operation: {trigger_type!r}")
        secret = hashlib.sha256(f"{node_id}:{webhook_url}".encode()).hexdigest()[:32]
        result = await _webflow_request(
            api_token,
            "POST",
            f"/sites/{site_id}/webhooks",
            json_body={
                "triggerType": trigger_type,
                "url": webhook_url,
            },
            action_name="register_webhook",
        )
        if result.get("status") != "success":
            raise ValueError(f"Webflow webhook registration failed: {result.get('error')}")
        data = result.get("data") or {}
        external_id = data.get("id") if isinstance(data, dict) else None
        return {
            "external_webhook_id": str(external_id) if external_id else None,
            "signing_secret": secret,
        }

    @classmethod
    async def _unregister_external_webhook(
        cls, *, credential: Optional[Dict[str, Any]], config: Dict[str, Any], node_id: str
    ) -> None:
        external_id = (config or {}).get("external_webhook_id")
        api_token = _extract_token(credential)
        if not external_id or not api_token:
            return
        await _webflow_request(
            api_token,
            "DELETE",
            f"/webhooks/{external_id}",
            action_name="unregister_webhook",
        )

    @classmethod
    def verify_webhook_signature(
        cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]
    ) -> bool:
        """Verify a Webflow webhook signature.

        OAuth-app webhooks are signed with x-webflow-signature (HMAC-SHA256 over
        `timestamp:body` using the app client secret) plus x-webflow-timestamp.
        Site-Token webhooks created here are unsigned, so accept when no secret
        is configured.
        """
        secret = (config or {}).get("client_secret")
        if not secret:
            return True
        sent = headers.get("x-webflow-signature")
        timestamp = headers.get("x-webflow-timestamp")
        if not sent or not timestamp:
            return False
        message = f"{timestamp}:{body.decode('utf-8', errors='replace')}".encode()
        expected = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, sent)

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, WebflowNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        if isinstance(op, _WebflowWebhookTrigger):
            return {
                "status": "success",
                "action": op.operation,
                "data": {**inputs, "webhook_url": op.webhook_url},
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        credentials = config.credentials
        if not credentials:
            raise ValueError(
                "Credentials are required. Connect a Webflow account or add a Webflow API token."
            )
        api_token = _extract_token(credentials.model_dump())
        if not api_token:
            raise ValueError(
                "Credentials are required. Connect a Webflow account or add a Webflow API token."
            )

        handlers = {
            "list_sites": self._list_sites,
            "get_site": self._get_site,
            "publish_site": self._publish_site,
            "list_pages": self._list_pages,
            "get_page_content": self._get_page_content,
            "update_page_content": self._update_page_content,
            "list_collections": self._list_collections,
            "get_collection": self._get_collection,
            "create_collection": self._create_collection,
            "create_collection_field": self._create_collection_field,
            "list_items": self._list_items,
            "get_item": self._get_item,
            "create_item": self._create_item,
            "create_live_item": self._create_live_item,
            "update_item": self._update_item,
            "delete_item": self._delete_item,
            "publish_items": self._publish_items,
            "list_forms": self._list_forms,
            "get_form": self._get_form,
            "list_form_submissions": self._list_form_submissions,
            "get_form_submission": self._get_form_submission,
            "list_assets": self._list_assets,
            "list_products": self._list_products,
            "create_product": self._create_product,
            "list_orders": self._list_orders,
            "get_order": self._get_order,
            "fulfill_order": self._fulfill_order,
            "list_inventory": self._list_inventory,
            "list_comment_threads": self._list_comment_threads,
            "list_webhooks": self._list_webhooks,
            "create_webhook": self._create_webhook,
            "remove_webhook": self._remove_webhook,
            "get_authorized_user": self._get_authorized_user,
            "get_custom_domains": self._get_custom_domains,
            "get_page_metadata": self._get_page_metadata,
            "update_page_metadata": self._update_page_metadata,
            "list_components": self._list_components,
            "get_component_content": self._get_component_content,
            "update_component_content": self._update_component_content,
            "get_component_properties": self._get_component_properties,
            "update_component_properties": self._update_component_properties,
            "delete_collection": self._delete_collection,
            "update_collection_field": self._update_collection_field,
            "delete_collection_field": self._delete_collection_field,
            "list_live_items": self._list_live_items,
            "get_live_item": self._get_live_item,
            "update_live_item": self._update_live_item,
            "delete_live_item": self._delete_live_item,
            "create_bulk_items": self._create_bulk_items,
            "get_product": self._get_product,
            "update_product": self._update_product,
            "create_skus": self._create_skus,
            "update_sku": self._update_sku,
            "update_inventory": self._update_inventory,
            "get_ecommerce_settings": self._get_ecommerce_settings,
            "update_order": self._update_order,
            "unfulfill_order": self._unfulfill_order,
            "refund_order": self._refund_order,
            "list_site_form_submissions": self._list_site_form_submissions,
            "modify_submission": self._modify_submission,
            "delete_submission": self._delete_submission,
            "get_asset": self._get_asset,
            "create_asset": self._create_asset,
            "update_asset": self._update_asset,
            "delete_asset": self._delete_asset,
            "list_asset_folders": self._list_asset_folders,
            "get_asset_folder": self._get_asset_folder,
            "create_asset_folder": self._create_asset_folder,
            "get_comment_thread": self._get_comment_thread,
            "list_comment_replies": self._list_comment_replies,
            "get_webhook": self._get_webhook,
            "introspect_token": self._introspect_token,
            "register_hosted_script": self._register_hosted_script,
            "register_inline_script": self._register_inline_script,
            "list_registered_scripts": self._list_registered_scripts,
            "get_site_custom_code": self._get_site_custom_code,
            "apply_site_custom_code": self._apply_site_custom_code,
            "remove_site_custom_code": self._remove_site_custom_code,
            "get_page_custom_code": self._get_page_custom_code,
            "apply_page_custom_code": self._apply_page_custom_code,
            "remove_page_custom_code": self._remove_page_custom_code,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(op, api_token)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # Handlers — Sites
    # ------------------------------------------------------------------
    async def _list_sites(self, c: WebflowListSitesConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(t, "GET", "/sites", action_name="list_sites")

    async def _get_site(self, c: WebflowGetSiteConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(
            t, "GET", f"/sites/{c.site_id}", action_name="get_site"
        )

    async def _publish_site(self, c: WebflowPublishSiteConfig, t: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "publishToWebflowSubdomain": c.publish_to_webflow_subdomain == "true",
        }
        domains = _comma_list(c.custom_domains)
        if domains:
            body["customDomains"] = domains
        return await _webflow_request(
            t, "POST", f"/sites/{c.site_id}/publish", json_body=body, action_name="publish_site"
        )

    # ------------------------------------------------------------------
    # Handlers — Pages
    # ------------------------------------------------------------------
    async def _list_pages(self, c: WebflowListPagesConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(
            t, "GET", f"/sites/{c.site_id}/pages", action_name="list_pages"
        )

    async def _get_page_content(self, c: WebflowGetPageContentConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(
            t, "GET", f"/pages/{c.page_id}/dom", action_name="get_page_content"
        )

    async def _update_page_content(
        self, c: WebflowUpdatePageContentConfig, t: str
    ) -> Dict[str, Any]:
        nodes = _parse_json_obj(c.nodes_json, "DOM Nodes")
        return await _webflow_request(
            t,
            "POST",
            f"/pages/{c.page_id}/dom",
            json_body={"nodes": nodes},
            action_name="update_page_content",
        )

    # ------------------------------------------------------------------
    # Handlers — Collections
    # ------------------------------------------------------------------
    async def _list_collections(self, c: WebflowListCollectionsConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(
            t, "GET", f"/sites/{c.site_id}/collections", action_name="list_collections"
        )

    async def _get_collection(self, c: WebflowGetCollectionConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(
            t, "GET", f"/collections/{c.collection_id}", action_name="get_collection"
        )

    async def _create_collection(self, c: WebflowCreateCollectionConfig, t: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "displayName": c.display_name,
            "singularName": c.singular_name,
        }
        if c.slug:
            body["slug"] = c.slug
        return await _webflow_request(
            t,
            "POST",
            f"/sites/{c.site_id}/collections",
            json_body=body,
            action_name="create_collection",
        )

    async def _create_collection_field(
        self, c: WebflowCreateCollectionFieldConfig, t: str
    ) -> Dict[str, Any]:
        body = {
            "type": c.field_type,
            "displayName": c.display_name,
            "isRequired": c.is_required == "true",
        }
        return await _webflow_request(
            t,
            "POST",
            f"/collections/{c.collection_id}/fields",
            json_body=body,
            action_name="create_collection_field",
        )

    # ------------------------------------------------------------------
    # Handlers — CMS Items
    # ------------------------------------------------------------------
    async def _list_items(self, c: WebflowListItemsConfig, t: str) -> Dict[str, Any]:
        params = {"limit": c.limit, "offset": c.offset}
        return await _webflow_request(
            t,
            "GET",
            f"/collections/{c.collection_id}/items",
            params=params,
            action_name="list_items",
        )

    async def _get_item(self, c: WebflowGetItemConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(
            t,
            "GET",
            f"/collections/{c.collection_id}/items/{c.item_id}",
            action_name="get_item",
        )

    async def _create_item(self, c: WebflowCreateItemConfig, t: str) -> Dict[str, Any]:
        field_data = _parse_json_obj(c.field_data_json, "Field Data")
        body = {
            "isArchived": c.is_archived == "true",
            "isDraft": c.is_draft == "true",
            "fieldData": field_data,
        }
        return await _webflow_request(
            t,
            "POST",
            f"/collections/{c.collection_id}/items",
            json_body=body,
            action_name="create_item",
        )

    async def _create_live_item(self, c: WebflowCreateLiveItemConfig, t: str) -> Dict[str, Any]:
        field_data = _parse_json_obj(c.field_data_json, "Field Data")
        body = {"fieldData": field_data}
        return await _webflow_request(
            t,
            "POST",
            f"/collections/{c.collection_id}/items/live",
            json_body=body,
            action_name="create_live_item",
        )

    async def _update_item(self, c: WebflowUpdateItemConfig, t: str) -> Dict[str, Any]:
        field_data = _parse_json_obj(c.field_data_json, "Field Data")
        body = {"id": c.item_id, "fieldData": field_data}
        return await _webflow_request(
            t,
            "PATCH",
            f"/collections/{c.collection_id}/items",
            json_body={"items": [body]},
            action_name="update_item",
        )

    async def _delete_item(self, c: WebflowDeleteItemConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(
            t,
            "DELETE",
            f"/collections/{c.collection_id}/items",
            json_body={"items": [{"id": c.item_id}]},
            action_name="delete_item",
        )

    async def _publish_items(self, c: WebflowPublishItemsConfig, t: str) -> Dict[str, Any]:
        item_ids = _comma_list(c.item_ids)
        return await _webflow_request(
            t,
            "POST",
            f"/collections/{c.collection_id}/items/publish",
            json_body={"itemIds": item_ids},
            action_name="publish_items",
        )

    # ------------------------------------------------------------------
    # Handlers — Forms
    # ------------------------------------------------------------------
    async def _list_forms(self, c: WebflowListFormsConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(
            t, "GET", f"/sites/{c.site_id}/forms", action_name="list_forms"
        )

    async def _get_form(self, c: WebflowGetFormConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(
            t, "GET", f"/forms/{c.form_id}", action_name="get_form"
        )

    async def _list_form_submissions(
        self, c: WebflowListFormSubmissionsConfig, t: str
    ) -> Dict[str, Any]:
        return await _webflow_request(
            t,
            "GET",
            f"/sites/{c.site_id}/forms/{c.form_id}/submissions",
            params={"limit": c.limit},
            action_name="list_form_submissions",
        )

    async def _get_form_submission(
        self, c: WebflowGetFormSubmissionConfig, t: str
    ) -> Dict[str, Any]:
        return await _webflow_request(
            t,
            "GET",
            f"/sites/{c.site_id}/form_submissions/{c.form_submission_id}",
            action_name="get_form_submission",
        )

    # ------------------------------------------------------------------
    # Handlers — Assets
    # ------------------------------------------------------------------
    async def _list_assets(self, c: WebflowListAssetsConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(
            t, "GET", f"/sites/{c.site_id}/assets", action_name="list_assets"
        )

    # ------------------------------------------------------------------
    # Handlers — Ecommerce
    # ------------------------------------------------------------------
    async def _list_products(self, c: WebflowListProductsConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(
            t, "GET", f"/sites/{c.site_id}/products", action_name="list_products"
        )

    async def _create_product(self, c: WebflowCreateProductConfig, t: str) -> Dict[str, Any]:
        product = _parse_json_obj(c.product_field_data_json, "Product Field Data")
        sku = _parse_json_obj(c.sku_field_data_json, "SKU Field Data")
        body = {
            "publishStatus": "staging",
            "product": {"fieldData": product},
            "sku": {"fieldData": sku},
        }
        return await _webflow_request(
            t,
            "POST",
            f"/sites/{c.site_id}/products",
            json_body=body,
            action_name="create_product",
        )

    async def _list_orders(self, c: WebflowListOrdersConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(
            t, "GET", f"/sites/{c.site_id}/orders", action_name="list_orders"
        )

    async def _get_order(self, c: WebflowGetOrderConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(
            t, "GET", f"/sites/{c.site_id}/orders/{c.order_id}", action_name="get_order"
        )

    async def _fulfill_order(self, c: WebflowFulfillOrderConfig, t: str) -> Dict[str, Any]:
        body = {"sendOrderFulfilledEmail": c.send_order_fulfilled_email == "true"}
        return await _webflow_request(
            t,
            "POST",
            f"/sites/{c.site_id}/orders/{c.order_id}/fulfill",
            json_body=body,
            action_name="fulfill_order",
        )

    async def _list_inventory(self, c: WebflowListInventoryConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(
            t,
            "GET",
            f"/collections/{c.collection_id}/items/{c.sku_id}/inventory",
            action_name="list_inventory",
        )

    # ------------------------------------------------------------------
    # Handlers — Comments
    # ------------------------------------------------------------------
    async def _list_comment_threads(
        self, c: WebflowListCommentThreadsConfig, t: str
    ) -> Dict[str, Any]:
        return await _webflow_request(
            t, "GET", f"/sites/{c.site_id}/comments", action_name="list_comment_threads"
        )

    # ------------------------------------------------------------------
    # Handlers — Webhooks
    # ------------------------------------------------------------------
    async def _list_webhooks(self, c: WebflowListWebhooksConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(
            t, "GET", f"/sites/{c.site_id}/webhooks", action_name="list_webhooks"
        )

    async def _create_webhook(self, c: WebflowCreateWebhookConfig, t: str) -> Dict[str, Any]:
        body = {"triggerType": c.trigger_type, "url": c.url}
        return await _webflow_request(
            t,
            "POST",
            f"/sites/{c.site_id}/webhooks",
            json_body=body,
            action_name="create_webhook",
        )

    async def _remove_webhook(self, c: WebflowRemoveWebhookConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(
            t, "DELETE", f"/webhooks/{c.webhook_id}", action_name="remove_webhook"
        )

    # ------------------------------------------------------------------
    # Handlers — Token
    # ------------------------------------------------------------------
    async def _get_authorized_user(
        self, c: WebflowGetAuthorizedUserConfig, t: str
    ) -> Dict[str, Any]:
        return await _webflow_request(
            t, "GET", "/token/authorized_by", action_name="get_authorized_user"
        )

    # ------------------------------------------------------------------
    # Handlers — Sites / Pages / Components (extra)
    # ------------------------------------------------------------------
    async def _get_custom_domains(self, c: WebflowGetCustomDomainsConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(t, "GET", f"/sites/{c.site_id}/custom_domains", action_name="get_custom_domains")

    async def _get_page_metadata(self, c: WebflowGetPageMetadataConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(t, "GET", f"/pages/{c.page_id}", action_name="get_page_metadata")

    async def _update_page_metadata(self, c: WebflowUpdatePageMetadataConfig, t: str) -> Dict[str, Any]:
        body = _parse_json_obj(c.metadata_json, "Metadata")
        return await _webflow_request(t, "PUT", f"/pages/{c.page_id}", json_body=body, action_name="update_page_metadata")

    async def _list_components(self, c: WebflowListComponentsConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(t, "GET", f"/sites/{c.site_id}/components", action_name="list_components")

    async def _get_component_content(self, c: WebflowGetComponentContentConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(t, "GET", f"/sites/{c.site_id}/components/{c.component_id}/dom", action_name="get_component_content")

    async def _update_component_content(self, c: WebflowUpdateComponentContentConfig, t: str) -> Dict[str, Any]:
        nodes = _parse_json_obj(c.nodes_json, "DOM Nodes")
        return await _webflow_request(t, "PATCH", f"/sites/{c.site_id}/components/{c.component_id}/dom", json_body={"nodes": nodes}, action_name="update_component_content")

    async def _get_component_properties(self, c: WebflowGetComponentPropertiesConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(t, "GET", f"/sites/{c.site_id}/components/{c.component_id}/properties", action_name="get_component_properties")

    async def _update_component_properties(self, c: WebflowUpdateComponentPropertiesConfig, t: str) -> Dict[str, Any]:
        props = _parse_json_obj(c.properties_json, "Properties")
        return await _webflow_request(t, "PATCH", f"/sites/{c.site_id}/components/{c.component_id}/properties", json_body={"properties": props}, action_name="update_component_properties")

    # ------------------------------------------------------------------
    # Handlers — Collections / Fields (extra)
    # ------------------------------------------------------------------
    async def _delete_collection(self, c: WebflowDeleteCollectionConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(t, "DELETE", f"/collections/{c.collection_id}", action_name="delete_collection")

    async def _update_collection_field(self, c: WebflowUpdateCollectionFieldConfig, t: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        if c.display_name:
            body["displayName"] = c.display_name
        if c.is_required:
            body["isRequired"] = c.is_required == "true"
        if c.help_text is not None:
            body["helpText"] = c.help_text
        return await _webflow_request(t, "PATCH", f"/collections/{c.collection_id}/fields/{c.field_id}", json_body=body, action_name="update_collection_field")

    async def _delete_collection_field(self, c: WebflowDeleteCollectionFieldConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(t, "DELETE", f"/collections/{c.collection_id}/fields/{c.field_id}", action_name="delete_collection_field")

    # ------------------------------------------------------------------
    # Handlers — CMS Items (live + bulk)
    # ------------------------------------------------------------------
    async def _list_live_items(self, c: WebflowListLiveItemsConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(t, "GET", f"/collections/{c.collection_id}/items/live", params={"limit": c.limit, "offset": c.offset}, action_name="list_live_items")

    async def _get_live_item(self, c: WebflowGetLiveItemConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(t, "GET", f"/collections/{c.collection_id}/items/{c.item_id}/live", action_name="get_live_item")

    async def _update_live_item(self, c: WebflowUpdateLiveItemConfig, t: str) -> Dict[str, Any]:
        field_data = _parse_json_obj(c.field_data_json, "Field Data")
        return await _webflow_request(t, "PATCH", f"/collections/{c.collection_id}/items/{c.item_id}/live", json_body={"fieldData": field_data}, action_name="update_live_item")

    async def _delete_live_item(self, c: WebflowDeleteLiveItemConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(t, "DELETE", f"/collections/{c.collection_id}/items/{c.item_id}/live", action_name="delete_live_item")

    async def _create_bulk_items(self, c: WebflowCreateBulkItemsConfig, t: str) -> Dict[str, Any]:
        items = _parse_json_obj(c.items_json, "Items")
        return await _webflow_request(t, "POST", f"/collections/{c.collection_id}/items/bulk", json_body={"items": items}, action_name="create_bulk_items")

    # ------------------------------------------------------------------
    # Handlers — Ecommerce (extra)
    # ------------------------------------------------------------------
    async def _get_product(self, c: WebflowGetProductConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(t, "GET", f"/sites/{c.site_id}/products/{c.product_id}", action_name="get_product")

    async def _update_product(self, c: WebflowUpdateProductConfig, t: str) -> Dict[str, Any]:
        product = _parse_json_obj(c.product_field_data_json, "Product Field Data")
        return await _webflow_request(t, "PATCH", f"/sites/{c.site_id}/products/{c.product_id}", json_body={"product": {"fieldData": product}}, action_name="update_product")

    async def _create_skus(self, c: WebflowCreateSkusConfig, t: str) -> Dict[str, Any]:
        skus = _parse_json_obj(c.skus_json, "SKUs")
        return await _webflow_request(t, "POST", f"/sites/{c.site_id}/products/{c.product_id}/skus", json_body={"skus": skus}, action_name="create_skus")

    async def _update_sku(self, c: WebflowUpdateSkuConfig, t: str) -> Dict[str, Any]:
        sku = _parse_json_obj(c.sku_field_data_json, "SKU Field Data")
        return await _webflow_request(t, "PATCH", f"/sites/{c.site_id}/products/{c.product_id}/skus/{c.sku_id}", json_body={"sku": {"fieldData": sku}}, action_name="update_sku")

    async def _update_inventory(self, c: WebflowUpdateInventoryConfig, t: str) -> Dict[str, Any]:
        body = _parse_json_obj(c.inventory_json, "Inventory")
        return await _webflow_request(t, "PATCH", f"/collections/{c.collection_id}/items/{c.sku_id}/inventory", json_body=body, action_name="update_inventory")

    async def _get_ecommerce_settings(self, c: WebflowGetEcommerceSettingsConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(t, "GET", f"/sites/{c.site_id}/ecommerce/settings", action_name="get_ecommerce_settings")

    async def _update_order(self, c: WebflowUpdateOrderConfig, t: str) -> Dict[str, Any]:
        body = _parse_json_obj(c.order_json, "Order Fields")
        return await _webflow_request(t, "PATCH", f"/sites/{c.site_id}/orders/{c.order_id}", json_body=body, action_name="update_order")

    async def _unfulfill_order(self, c: WebflowUnfulfillOrderConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(t, "POST", f"/sites/{c.site_id}/orders/{c.order_id}/unfulfill", json_body={}, action_name="unfulfill_order")

    async def _refund_order(self, c: WebflowRefundOrderConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(t, "POST", f"/sites/{c.site_id}/orders/{c.order_id}/refund", json_body={"reason": c.reason}, action_name="refund_order")

    # ------------------------------------------------------------------
    # Handlers — Forms (extra)
    # ------------------------------------------------------------------
    async def _list_site_form_submissions(self, c: WebflowListSiteFormSubmissionsConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(t, "GET", f"/sites/{c.site_id}/form_submissions", params={"limit": c.limit, "offset": c.offset}, action_name="list_site_form_submissions")

    async def _modify_submission(self, c: WebflowModifySubmissionConfig, t: str) -> Dict[str, Any]:
        body = _parse_json_obj(c.data_json, "Data")
        return await _webflow_request(t, "PATCH", f"/form_submissions/{c.form_submission_id}", json_body=body, action_name="modify_submission")

    async def _delete_submission(self, c: WebflowDeleteSubmissionConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(t, "DELETE", f"/form_submissions/{c.form_submission_id}", action_name="delete_submission")

    # ------------------------------------------------------------------
    # Handlers — Assets
    # ------------------------------------------------------------------
    async def _get_asset(self, c: WebflowGetAssetConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(t, "GET", f"/assets/{c.asset_id}", action_name="get_asset")

    async def _create_asset(self, c: WebflowCreateAssetConfig, t: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {"fileName": c.file_name, "fileHash": c.file_hash}
        if c.parent_folder:
            body["parentFolder"] = c.parent_folder
        return await _webflow_request(t, "POST", f"/sites/{c.site_id}/assets", json_body=body, action_name="create_asset")

    async def _update_asset(self, c: WebflowUpdateAssetConfig, t: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        if c.display_name:
            body["displayName"] = c.display_name
        if c.alt_text is not None:
            body["altText"] = c.alt_text
        return await _webflow_request(t, "PATCH", f"/assets/{c.asset_id}", json_body=body, action_name="update_asset")

    async def _delete_asset(self, c: WebflowDeleteAssetConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(t, "DELETE", f"/assets/{c.asset_id}", action_name="delete_asset")

    async def _list_asset_folders(self, c: WebflowListAssetFoldersConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(t, "GET", f"/sites/{c.site_id}/asset_folders", action_name="list_asset_folders")

    async def _get_asset_folder(self, c: WebflowGetAssetFolderConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(t, "GET", f"/asset_folders/{c.asset_folder_id}", action_name="get_asset_folder")

    async def _create_asset_folder(self, c: WebflowCreateAssetFolderConfig, t: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {"displayName": c.display_name}
        if c.parent_folder:
            body["parentFolder"] = c.parent_folder
        return await _webflow_request(t, "POST", f"/sites/{c.site_id}/asset_folders", json_body=body, action_name="create_asset_folder")

    # ------------------------------------------------------------------
    # Handlers — Comments / Webhooks / Token (extra)
    # ------------------------------------------------------------------
    async def _get_comment_thread(self, c: WebflowGetCommentThreadConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(t, "GET", f"/sites/{c.site_id}/comments/{c.comment_thread_id}", action_name="get_comment_thread")

    async def _list_comment_replies(self, c: WebflowListCommentRepliesConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(t, "GET", f"/sites/{c.site_id}/comments/{c.comment_thread_id}/replies", action_name="list_comment_replies")

    async def _get_webhook(self, c: WebflowGetWebhookConfig, t: str) -> Dict[str, Any]:
        # Single-webhook GET is top-level (/webhooks/{id}), not site-scoped.
        return await _webflow_request(t, "GET", f"/webhooks/{c.webhook_id}", action_name="get_webhook")

    async def _introspect_token(self, c: WebflowIntrospectTokenConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(t, "GET", "/token/introspect", action_name="introspect_token")

    # ------------------------------------------------------------------
    # Handlers — Custom Code
    # ------------------------------------------------------------------
    async def _register_hosted_script(self, c: WebflowRegisterHostedScriptConfig, t: str) -> Dict[str, Any]:
        body = _parse_json_obj(c.script_json, "Script")
        return await _webflow_request(t, "POST", f"/sites/{c.site_id}/registered_scripts/hosted", json_body=body, action_name="register_hosted_script")

    async def _register_inline_script(self, c: WebflowRegisterInlineScriptConfig, t: str) -> Dict[str, Any]:
        body = _parse_json_obj(c.script_json, "Script")
        return await _webflow_request(t, "POST", f"/sites/{c.site_id}/registered_scripts/inline", json_body=body, action_name="register_inline_script")

    async def _list_registered_scripts(self, c: WebflowListRegisteredScriptsConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(t, "GET", f"/sites/{c.site_id}/registered_scripts", action_name="list_registered_scripts")

    async def _get_site_custom_code(self, c: WebflowGetSiteCustomCodeConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(t, "GET", f"/sites/{c.site_id}/custom_code", action_name="get_site_custom_code")

    async def _apply_site_custom_code(self, c: WebflowApplySiteCustomCodeConfig, t: str) -> Dict[str, Any]:
        body = _parse_json_obj(c.scripts_json, "Scripts")
        return await _webflow_request(t, "PUT", f"/sites/{c.site_id}/custom_code", json_body=body, action_name="apply_site_custom_code")

    async def _remove_site_custom_code(self, c: WebflowRemoveSiteCustomCodeConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(t, "DELETE", f"/sites/{c.site_id}/custom_code", action_name="remove_site_custom_code")

    async def _get_page_custom_code(self, c: WebflowGetPageCustomCodeConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(t, "GET", f"/pages/{c.page_id}/custom_code", action_name="get_page_custom_code")

    async def _apply_page_custom_code(self, c: WebflowApplyPageCustomCodeConfig, t: str) -> Dict[str, Any]:
        body = _parse_json_obj(c.scripts_json, "Scripts")
        return await _webflow_request(t, "PUT", f"/pages/{c.page_id}/custom_code", json_body=body, action_name="apply_page_custom_code")

    async def _remove_page_custom_code(self, c: WebflowRemovePageCustomCodeConfig, t: str) -> Dict[str, Any]:
        return await _webflow_request(t, "DELETE", f"/pages/{c.page_id}/custom_code", action_name="remove_page_custom_code")
