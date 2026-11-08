"""Goody API v1 gifting operations, pinned to the provider's OpenAPI 1.0.0.

Every operation sends one request to a fixed documented endpoint. Lists return
one page and its next page number; writes are never automatically retried.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union
from uuid import UUID
from urllib.parse import quote

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
    model_validator,
)

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.ongoody.com"


class GoodyAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Goody API Key",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developer.ongoody.com/introduction",
            "x-credential-instructions": "Create an API key in your Goody account, then paste it here. NoClick sends it as a bearer token to api.ongoody.com. Connecting reads your workspaces and current user. Creating an order batch can charge your payment method and send gifts; use Calculate order batch price first to estimate the cost.",
        },
    )
    credential_type: Literal["goody_api_key"] = Field(
        "goody_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API key",
        min_length=1,
        max_length=4096,
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(ch.isspace() for ch in value) or value.lower().startswith("bearer"):
            raise ValueError("Paste only the Goody API key, without a Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class GoodyListBrandsConfig(_Input):
    """List all active brands."""

    operation: Literal["list_brands"] = Field(
        "list_brands", json_schema_extra={"ui:hidden": True}
    )
    page: int = Field(1, description="Page for pagination, starting at 1", ge=1)
    per_page: int = Field(20, description="Items per page for pagination", ge=1, le=100)
    country_code: Optional[str] = Field(
        "US", description="Filter by a specific shipping country code"
    )


class GoodyListCardsConfig(_Input):
    """Retrieve cards."""

    operation: Literal["list_cards"] = Field(
        "list_cards", json_schema_extra={"ui:hidden": True}
    )
    page: int = Field(1, description="Page for pagination, starting at 1", ge=1)
    per_page: int = Field(20, description="Items per page for pagination", ge=1, le=100)
    custom: Optional[StrictBool] = Field(
        None,
        description="Return the caller's custom cards (their own, their organization's, and their teams') instead of Goody's stock cards.",
    )


class GoodyListCollectionsConfig(_Input):
    """List collections."""

    operation: Literal["list_collections"] = Field(
        "list_collections", json_schema_extra={"ui:hidden": True}
    )
    page: int = Field(1, description="Page number for pagination (starts at 1)", ge=1)
    per_page: int = Field(
        20,
        description="Number of collections to return per page (maximum 100)",
        ge=1,
        le=100,
    )
    published: Optional[StrictBool] = Field(
        None, description="Return only published collections when true"
    )
    workspace_id: Optional[UUID] = Field(
        None,
        description="Return only collections in this workspace. Must be a workspace the caller belongs to.",
    )
    exclude_archived: Optional[StrictBool] = Field(
        None, description="Exclude archived collections when true"
    )


class GoodyGetCollectionConfig(_Input):
    """Retrieve a collection."""

    operation: Literal["get_collection"] = Field(
        "get_collection", json_schema_extra={"ui:hidden": True}
    )
    id: UUID = Field(..., description="Collection ID")


class GoodyListGiftTemplatesConfig(_Input):
    """List all gift templates."""

    operation: Literal["list_gift_templates"] = Field(
        "list_gift_templates", json_schema_extra={"ui:hidden": True}
    )
    page: int = Field(1, description="Page for pagination, starting at 1", ge=1)
    per_page: int = Field(20, description="Items per page for pagination", ge=1, le=100)


class GoodyGetGiftTemplateConfig(_Input):
    """Retrieve a gift template."""

    operation: Literal["get_gift_template"] = Field(
        "get_gift_template", json_schema_extra={"ui:hidden": True}
    )
    id: UUID = Field(..., description="Gift template ID")


class GoodyListGiftsOfChoiceConfig(_Input):
    """List Gifts of Choice."""

    operation: Literal["list_gifts_of_choice"] = Field(
        "list_gifts_of_choice", json_schema_extra={"ui:hidden": True}
    )


class GoodyGetCurrentUserConfig(_Input):
    """Retrieve current user."""

    operation: Literal["get_current_user"] = Field(
        "get_current_user", json_schema_extra={"ui:hidden": True}
    )


class GoodyListOrderActivitiesConfig(_Input):
    """List order activities."""

    operation: Literal["list_order_activities"] = Field(
        "list_order_activities", json_schema_extra={"ui:hidden": True}
    )
    page: int = Field(1, description="Page for pagination, starting at 1", ge=1)
    per_page: int = Field(20, description="Items per page for pagination", ge=1, le=100)
    after: Optional[AwareDatetime] = Field(
        None,
        description="Filter activities created at or after this timestamp (ISO 8601)",
    )
    before: Optional[AwareDatetime] = Field(
        None,
        description="Filter activities created at or before this timestamp (ISO 8601)",
    )
    statuses: Optional[str] = Field(
        None,
        description='Comma-separated list of statuses to filter by (e.g. "created,opened,shipped")',
    )


class MailingAddress(_Input):
    first_name: Optional[str] = Field(None)
    last_name: Optional[str] = Field(None)
    address_1: str = Field(...)
    address_2: Optional[str] = Field(None)
    city: str = Field(...)
    state: str = Field(...)
    postal_code: str = Field(...)
    country: Optional[str] = Field(
        ...,
        description='The two-letter country code, e.g. "US". Only US is supported at this time.',
    )


class RecipientInput(_Input):
    first_name: str = Field(..., min_length=1)
    last_name: Optional[str] = Field(None)
    email: Optional[str] = Field(None)
    phone: Optional[str] = Field(
        None,
        description="Optional. Phone number for text notifications. E164 format (e.g. +15552347890), US only.",
    )
    mailing_address: Optional[MailingAddress] = Field(
        None,
        description="Optional mailing address to pre-populate into the order. This field is only available for approved API partners.",
    )


class CartItemInput(_Input):
    product_id: Optional[UUID] = Field(
        None,
        description="ID of the product. Preferred over URL since this is always stable. Either `product_id` or `product_url` must be provided.",
    )
    product_url: Optional[str] = Field(
        None,
        description="URL of the product. Either `product_id` or `product_url` must be provided.",
    )
    quantity: int = Field(..., ge=1)
    variable_price: Optional[int] = Field(
        None,
        ge=1,
        description="If this product has a variable price (e.g. a flex gift or a gift card), then this must be provided. A positive integer represented in cents.",
    )
    variants: Optional[list[str]] = Field(
        None,
        description="An array of variant names (not IDs). When using the Direct Send send method with a product with variants, the variants must be provided. The length of the array must be equal to `variants_num_selectable` on the product, and the variants must come from the names of the `varaints` on the product. For example, for a t-shirt with `variants_num_selectable` = 1 and variants S, M, L, pass ['M']. Or, for a box of cookies with `variants_num_selectable` = 2 and variants Sugar, Caramel, Chocolate, pass ['Sugar', 'Chocolate'].",
    )

    @model_validator(mode="after")
    def product_reference(self):
        if not self.product_id and not self.product_url:
            raise ValueError("Choose a product ID or provide its Goody product URL")
        return self


class CartInput(_Input):
    items: list[CartItemInput] = Field(
        ..., min_length=1, max_length=100, description="An array of cart items."
    )


class GoodyCreateOrderBatchConfig(_Input):
    """Create an order batch."""

    operation: Literal["create_order_batch"] = Field(
        "create_order_batch", json_schema_extra={"ui:hidden": True}
    )
    from_name: str = Field(
        ...,
        description='The name of the sender of the order (typically a gift), to be displayed as "from".',
    )
    message: Optional[str] = Field(
        None,
        description="For gifts, a message for the gift to be displayed in the digital unwrapping and email notifications, if enabled.",
    )
    recipients: list[RecipientInput] = Field(..., min_length=1, max_length=1000)
    cart: CartInput = Field(...)
    send_method: Literal[
        "email_and_link", "link_multiple_custom_list", "direct_send"
    ] = Field(...)
    card_id: Optional[UUID] = Field(
        None,
        description="The digital greeting card to attach to gifts. A card must be specified if a message is specified, since the message is displayed after the card is opened.",
    )
    custom_form_id: Optional[UUID] = Field(
        None,
        description="Optional. An existing custom form (a set of question fields recipients answer when they accept) to attach to gifts. Must be a form you own or one shared with the workspace. This does not create new questions, and is ignored for the `direct_send` send method.",
    )
    payment_method_id: Optional[str] = Field(
        None,
        description="The payment method used to pay for this order batch. If not specified, defaults to the first payment method on the account. If the account has no payment methods, then the order batch creation will fail.",
    )
    workspace_id: Optional[UUID] = Field(
        None,
        description="Workspace to create the order batch in. If not specified, creates the order batch in the oldest workspace the user has access to.",
    )
    scheduled_send_on: Optional[AwareDatetime] = Field(
        None,
        description="The date and time at which the order batch will be sent. If not specified, the order batch is sent immediately. If an order batch is scheduled to be sent in the future, then orders will not be created until the scheduled send time. ISO 8601 format.",
    )
    expires_at: Optional[AwareDatetime] = Field(
        None,
        description="The date and time at which the order batch will expire. If not specified, the order batch does not expire. An expiry must be set for orders paid using account balance. ISO 8601 format.",
    )
    swap: Optional[Literal["single", "multiple", "disabled"]] = Field(None)
    international_shipping_tier: Optional[
        Literal["disabled", "standard", "full"]
    ] = Field(None)
    international_gift_cards_enabled: Optional[StrictBool] = Field(
        None,
        description="Whether to enable international gift cards on this order. If `true` and the `international_shipping_tier` is `standard`, then international gift cards can be swapped to. If `false`, then international gift cards are not available to be swapped to.",
    )
    allow_recipient_topup: Optional[StrictBool] = Field(
        None,
        description="Whether recipients can pay to upgrade their gift. If `true` and `swap` is `multiple`, recipients see gift prices when swapping and can pay the difference to choose a more expensive item. If `false` (default), recipients can only swap to items at or below the gift's value.",
    )
    notifications_enabled: Optional[StrictBool] = Field(
        None,
        description="Direct Send only. Whether to enable notifications for Direct Send orders. If `true`, we send confirmation and shipping notifications to Direct Send recipients. If `false`, we do not send any notifications to Direct Send recipients.",
    )
    commerce_end_user_id: Optional[str] = Field(
        None,
        description="If associating this gift with a Commerce End User (i.e. your app's user), provide the user ID here. Required if using a Commerce User Payment Method in the `payment_method_id` field.",
    )
    customer_reference_id: Optional[str] = Field(
        None,
        description="A unique, client-supplied identifier for this order batch, which can be used as an idempotency key to prevent duplicate creation. If an order batch with the same `customer_reference_id` already exists for your account, the request is rejected with an error instead of creating a duplicate. Returned on the order batch as `customer_reference_id`.",
    )


class GoodyListOrderBatchesConfig(_Input):
    """List order batches."""

    operation: Literal["list_order_batches"] = Field(
        "list_order_batches", json_schema_extra={"ui:hidden": True}
    )
    page: int = Field(1, description="Page for pagination, starting at 1", ge=1)
    per_page: int = Field(20, description="Items per page for pagination", ge=1, le=100)


class GoodyListOrderBatchOrdersConfig(_Input):
    """Retrieve orders for an order batch."""

    operation: Literal["list_order_batch_orders"] = Field(
        "list_order_batch_orders", json_schema_extra={"ui:hidden": True}
    )
    id: UUID = Field(..., description="Order batch ID")
    page: int = Field(1, description="Page for pagination, starting at 1", ge=1)
    per_page: int = Field(20, description="Items per page for pagination", ge=1, le=100)


class GoodyCalculateOrderBatchPriceConfig(_Input):
    """Calculate the price for an order batch."""

    operation: Literal["calculate_order_batch_price"] = Field(
        "calculate_order_batch_price", json_schema_extra={"ui:hidden": True}
    )
    recipients: list[RecipientInput] = Field(..., min_length=1, max_length=1000)
    cart: CartInput = Field(...)
    send_method: Literal[
        "email_and_link", "link_multiple_custom_list", "direct_send"
    ] = Field(...)


class GoodyListOrderBatchRecipientsConfig(_Input):
    """Retrieve recipients for an order batch."""

    operation: Literal["list_order_batch_recipients"] = Field(
        "list_order_batch_recipients", json_schema_extra={"ui:hidden": True}
    )
    id: UUID = Field(..., description="Order batch ID")
    page: int = Field(1, description="Page for pagination, starting at 1", ge=1)
    per_page: int = Field(20, description="Items per page for pagination", ge=1, le=100)


class GoodyGetOrderBatchConfig(_Input):
    """Retrieve an order batch."""

    operation: Literal["get_order_batch"] = Field(
        "get_order_batch", json_schema_extra={"ui:hidden": True}
    )
    id: UUID = Field(..., description="Order batch ID")


class GoodyCancelOrderConfig(_Input):
    """Cancel an order."""

    operation: Literal["cancel_order"] = Field(
        "cancel_order", json_schema_extra={"ui:hidden": True}
    )
    id: UUID = Field(..., description="id")


class GoodyListOrdersConfig(_Input):
    """List orders."""

    operation: Literal["list_orders"] = Field(
        "list_orders", json_schema_extra={"ui:hidden": True}
    )
    page: int = Field(1, description="Page for pagination, starting at 1", ge=1)
    per_page: int = Field(20, description="Items per page for pagination", ge=1, le=100)
    created_at_after: Optional[AwareDatetime] = Field(
        None,
        description="Filter orders created at or after this timestamp (ISO 8601, UTC unless otherwise specified in timestamp)",
        alias="created_at[after]",
    )
    created_at_before: Optional[AwareDatetime] = Field(
        None,
        description="Filter orders created at or before this timestamp (ISO 8601, UTC unless otherwise specified in timestamp)",
        alias="created_at[before]",
    )


class GoodyGetOrderConfig(_Input):
    """Retrieve an order."""

    operation: Literal["get_order"] = Field(
        "get_order", json_schema_extra={"ui:hidden": True}
    )
    id: UUID = Field(..., description="id")


class GoodyUpdateOrderExpirationConfig(_Input):
    """Update expiration for an order."""

    operation: Literal["update_order_expiration"] = Field(
        "update_order_expiration", json_schema_extra={"ui:hidden": True}
    )
    id: UUID = Field(..., description="id")
    expiration: AwareDatetime = Field(
        ..., description="New expiration date in ISO 8601 format"
    )


class GoodyListPaymentMethodsConfig(_Input):
    """List all payment methods."""

    operation: Literal["list_payment_methods"] = Field(
        "list_payment_methods", json_schema_extra={"ui:hidden": True}
    )


class GoodyListProductsConfig(_Input):
    """List all active products."""

    operation: Literal["list_products"] = Field(
        "list_products", json_schema_extra={"ui:hidden": True}
    )
    page: int = Field(1, description="Page for pagination, starting at 1", ge=1)
    per_page: int = Field(20, description="Items per page for pagination", ge=1, le=100)
    use_custom_catalog: Optional[StrictBool] = Field(
        None, description="Limit to custom catalog only (for approved API partners)"
    )
    country_code: Optional[str] = Field(
        "US", description="Filter by a specific shipping country code"
    )
    custom_catalog_show_inactive: Optional[StrictBool] = Field(
        None,
        description="Show inactive products in the custom catalog. Only for Commerce API customers with a custom catalog.",
    )
    brand_id: Optional[str] = Field(
        None, description="Limit to products from a specific brand"
    )
    category_id: Optional[Union[str, list[str]]] = Field(
        None,
        description="Limit to products in a category (see the categories endpoint). Accepts a single ID or an array of IDs.",
    )
    min_price: Optional[int] = Field(
        None,
        description="Limit to products priced at or above this amount, in cents",
        ge=0,
    )
    max_price: Optional[int] = Field(
        None,
        description="Limit to products priced at or below this amount, in cents",
        ge=0,
    )
    brand_values: Optional[list[str]] = Field(
        None,
        description="Limit to products whose brand has at least one of these brand values (e.g. Sustainable, Female Founded)",
    )


class GoodyGetProductConfig(_Input):
    """Retrieve a product."""

    operation: Literal["get_product"] = Field(
        "get_product", json_schema_extra={"ui:hidden": True}
    )
    id: UUID = Field(..., description="Product ID")
    country_code: Optional[str] = Field(
        "US",
        description="Look up the product in a specific shipping country's catalog. Products are scoped to a country (default US), so a product that only ships elsewhere — e.g. an international gift card — 404s unless its country is passed here.",
    )
    use_custom_catalog: Optional[StrictBool] = Field(
        None, description="Limit to custom catalog only (for approved API partners)"
    )


class GoodyListWorkspacesConfig(_Input):
    """List all workspaces."""

    operation: Literal["list_workspaces"] = Field(
        "list_workspaces", json_schema_extra={"ui:hidden": True}
    )


GoodyConfig = Annotated[
    Union[
        GoodyListBrandsConfig,
        GoodyListCardsConfig,
        GoodyListCollectionsConfig,
        GoodyGetCollectionConfig,
        GoodyListGiftTemplatesConfig,
        GoodyGetGiftTemplateConfig,
        GoodyListGiftsOfChoiceConfig,
        GoodyGetCurrentUserConfig,
        GoodyListOrderActivitiesConfig,
        GoodyCreateOrderBatchConfig,
        GoodyListOrderBatchesConfig,
        GoodyListOrderBatchOrdersConfig,
        GoodyCalculateOrderBatchPriceConfig,
        GoodyListOrderBatchRecipientsConfig,
        GoodyGetOrderBatchConfig,
        GoodyCancelOrderConfig,
        GoodyListOrdersConfig,
        GoodyGetOrderConfig,
        GoodyUpdateOrderExpirationConfig,
        GoodyListPaymentMethodsConfig,
        GoodyListProductsConfig,
        GoodyGetProductConfig,
        GoodyListWorkspacesConfig,
    ],
    Field(discriminator="operation"),
]


class GoodyFullConfig(NodeConfig[GoodyConfig, GoodyAPIKeyCredential]):
    pass


# One contract operation per user-facing operation.
ROUTES = {
    "list_brands": ("GET", "/v1/brands", 200),
    "list_cards": ("GET", "/v1/cards", 200),
    "list_collections": ("GET", "/v1/collections", 200),
    "get_collection": ("GET", "/v1/collections/{id}", 200),
    "list_gift_templates": ("GET", "/v1/gift_templates", 200),
    "get_gift_template": ("GET", "/v1/gift_templates/{id}", 200),
    "list_gifts_of_choice": ("GET", "/v1/gifts_of_choice", 200),
    "get_current_user": ("GET", "/v1/me", 200),
    "list_order_activities": ("GET", "/v1/order_activities", 200),
    "create_order_batch": ("POST", "/v1/order_batches", 201),
    "list_order_batches": ("GET", "/v1/order_batches", 200),
    "list_order_batch_orders": ("GET", "/v1/order_batches/{id}/orders", 200),
    "list_orders": ("GET", "/v1/orders", 200),
    "calculate_order_batch_price": ("POST", "/v1/order_batches/price", 200),
    "list_order_batch_recipients": ("GET", "/v1/order_batches/{id}/recipients", 200),
    "get_order_batch": ("GET", "/v1/order_batches/{id}", 200),
    "cancel_order": ("POST", "/v1/orders/{id}/cancel", 200),
    "get_order": ("GET", "/v1/orders/{id}", 200),
    "update_order_expiration": ("POST", "/v1/orders/{id}/update_expiration", 200),
    "list_payment_methods": ("GET", "/v1/payment_methods", 200),
    "list_products": ("GET", "/v1/products", 200),
    "get_product": ("GET", "/v1/products/{id}", 200),
    "list_workspaces": ("GET", "/v1/workspaces", 200),
}
QUERY_FIELDS = {
    "list_brands": ["page", "per_page", "country_code"],
    "list_cards": ["page", "per_page", "custom"],
    "list_collections": [
        "page",
        "per_page",
        "published",
        "workspace_id",
        "exclude_archived",
    ],
    "get_collection": [],
    "list_gift_templates": ["page", "per_page"],
    "get_gift_template": [],
    "list_gifts_of_choice": [],
    "get_current_user": [],
    "list_order_activities": ["page", "per_page", "after", "before", "statuses"],
    "create_order_batch": [],
    "list_order_batches": ["page", "per_page"],
    "list_order_batch_orders": ["page", "per_page"],
    "list_orders": ["page", "per_page", "created_at[after]", "created_at[before]"],
    "calculate_order_batch_price": [],
    "list_order_batch_recipients": ["page", "per_page"],
    "get_order_batch": [],
    "cancel_order": [],
    "get_order": [],
    "update_order_expiration": [],
    "list_payment_methods": [],
    "list_products": [
        "page",
        "per_page",
        "use_custom_catalog",
        "country_code",
        "custom_catalog_show_inactive",
        "brand_id",
        "category_id",
        "min_price",
        "max_price",
        "brand_values",
    ],
    "get_product": ["country_code", "use_custom_catalog"],
    "list_workspaces": [],
}
BODY_FIELDS = {
    "create_order_batch": [
        "from_name",
        "message",
        "recipients",
        "cart",
        "send_method",
        "card_id",
        "custom_form_id",
        "payment_method_id",
        "workspace_id",
        "scheduled_send_on",
        "expires_at",
        "swap",
        "international_shipping_tier",
        "international_gift_cards_enabled",
        "allow_recipient_topup",
        "notifications_enabled",
        "commerce_end_user_id",
        "customer_reference_id",
    ],
    "calculate_order_batch_price": ["recipients", "cart", "send_method"],
    "update_order_expiration": ["expiration"],
}
LIST_OPERATIONS = {
    "list_brands",
    "list_cards",
    "list_collections",
    "list_gift_templates",
    "list_gifts_of_choice",
    "list_order_activities",
    "list_order_batch_orders",
    "list_orders",
    "list_order_batch_recipients",
    "list_order_batches",
    "list_payment_methods",
    "list_products",
    "list_workspaces",
}


def _guard_credential_family(data):
    raw = data.get("credentials")
    if raw is not None:
        if (
            not isinstance(raw, dict)
            or raw.get("credential_type", "goody_api_key") != "goody_api_key"
        ):
            raise ValueError("Attach a Goody API key credential")
    for scope in (data, data.get("config", {})):
        mapping = scope.get("credentialIds", {}) if isinstance(scope, dict) else {}
        if not isinstance(mapping, dict):
            raise ValueError("Choose one saved Goody credential")
        if any(
            k not in {"goody_api_key", "credential_type"} and v
            for k, v in mapping.items()
        ):
            raise ValueError("Attach only a Goody API key credential")


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {
            _redact(key, secret): _redact(item, secret) for key, item in value.items()
        }
    return value


class GoodyNode(WorkflowNode):
    integration_type = "automation-goody"
    connection_evidence = ConnectionEvidence(
        noun="workspaces",
        operation="list_workspaces",
        identity_operation="get_current_user",
    )

    @classmethod
    def get_config_model(cls):
        return GoodyFullConfig

    @classmethod
    def parse_config(cls, config_data):
        _guard_credential_family(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            _guard_credential_family(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(config_data)

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Goody API key")
        op = self.config.config
        action = op.operation
        method, path, expected_status = ROUTES[action]
        values = op.model_dump(mode="json", by_alias=True, exclude_none=True)
        if "{id}" in path:
            path = path.replace("{id}", quote(values["id"], safe=""))
        params = {key: values[key] for key in QUERY_FIELDS[action] if key in values}
        # httpx represents native booleans using the documented lowercase form.
        body_values = op.model_dump(
            mode="json", by_alias=True, exclude_unset=True, exclude_none=True
        )
        body = {
            key: body_values[key]
            for key in BODY_FIELDS.get(action, [])
            if key in body_values
        }
        for item in body.get("cart", {}).get("items", []):
            if "product_id" not in item:
                item["product_id"] = None
        key = self.config.credentials.api_key
        try:
            async with guarded_async_client(
                timeout=30, follow_redirects=False, trust_env=False
            ) as client:
                response = await client.request(
                    method,
                    BASE_URL + path,
                    headers={
                        "Authorization": "Bearer " + key,
                        "Accept": "application/json",
                    },
                    params=params,
                    **({"json": body} if action in BODY_FIELDS else {}),
                )
        except Exception:
            # A timed-out write may have completed; never encourage automatic retry.
            raise ValueError(
                "Goody request did not complete; inspect order history before retrying a write"
            ) from None
        try:
            if len(response.content) > 10_000_000:
                raise ValueError()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError()
        except Exception:
            raise ValueError(
                "Goody returned an unexpected response; inspect order history before retrying a write"
            ) from None
        # Preserve the provider's rejection text for the shared connection seam,
        # while ensuring it can never echo the credential into an output.
        payload = _redact(payload, key)
        if response.status_code != expected_status or payload.get("error"):
            result = {
                "status": "error",
                "http_status": response.status_code,
                "message": payload.get("error") or "Goody request was not accepted",
            }
        else:
            result = {
                "status": "success",
                "http_status": response.status_code,
                "data": payload,
            }
            if action in LIST_OPERATIONS:
                rows = payload.get("data")
                meta = payload.get("list_meta")
                if not isinstance(rows, list) or not isinstance(meta, dict):
                    raise ValueError("Goody returned an unexpected list envelope")
                total = meta.get("total_count")
                if total is not None and (type(total) is not int or total < 0):
                    raise ValueError("Goody returned an unexpected list total")
                result["data"] = rows
                result["list_meta"] = meta
                if "page" in values:
                    page = values["page"]
                    per_page = values["per_page"]
                    more = (
                        (page - 1) * per_page + len(rows) < total
                        if total is not None
                        else len(rows) == per_page
                    )
                    result["next_page"] = page + 1 if rows and more else None
                else:
                    result["next_page"] = None
            if method != "GET":
                result["write_outcome"] = "acknowledged"
        await self.emit(result)
        return result
