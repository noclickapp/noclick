"""Shopify operation → Admin API access scope requirements.

Shopify scopes are ``read_<resource>`` / ``write_<resource>`` pairs, and
**write implies read** ("The read access scope is omitted because it's implied
by the write access scope" —
https://shopify.dev/docs/apps/build/authentication-authorization/access-tokens/authorization-code-grant).
Entries below therefore name only the half an operation actually needs.

Three quirks matter for reading this table:

- **The REST reference names the scope FAMILY, not the half.** A product page
  says ``Requires `products` access scope``; the read/write split comes from the
  GraphQL page for the same operation (``productCreate`` → ``write_products``)
  plus the scope table at https://shopify.dev/docs/api/usage/access-scopes.
- **``read_fulfillments``/``write_fulfillments`` does NOT cover fulfillments.**
  The scope table maps it to ``FulfillmentService`` only — registering a
  fulfillment service. Creating and cancelling fulfillments runs on the
  fulfillment-ORDER scope family (``*_merchant_managed_fulfillment_orders`` and
  friends), which is why the node requests all six of those.
- **Several Shopify requirements are an OR of scopes.** ``fulfillmentCreate``
  accepts any of three fulfillment-order write scopes; the orders family accepts
  ``marketplace_orders`` as an alternative. A ``ScopeRequirement`` tuple is an
  AND, so the alternatives are recorded in ``note`` and the entry names the
  scope this node's flow actually uses.

Operations whose resource scope is selected dynamically remain in ``unmapped``.
Operations that require scopes outside NoClick's public app grant are omitted
from the node schema entirely so users cannot build workflows that always fail.
"""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement


def _s(*scopes: str, note: str = "") -> ScopeRequirement:
    return ScopeRequirement(scopes=scopes, note=note)


# Fulfillment writes accept any ONE of the three fulfillment-order write
# scopes; an order-management app (which is what this node is) uses the
# merchant-managed one.
_FULFILL_OR = (
    "fulfillmentCreate accepts write_assigned_fulfillment_orders, "
    "write_merchant_managed_fulfillment_orders or "
    "write_third_party_fulfillment_orders; an order-management app uses the "
    "merchant-managed scope."
)
_ORDERS_OR = "marketplace_orders is a documented alternative to orders."
_WEBHOOK_ADMIN = "Webhook management endpoints require no access scope."


def _reads(*operations: str, scope: str, note: str = "") -> dict:
    return {op: _s(scope, note=note) for op in operations}


_REQUIREMENTS: dict[str, ScopeRequirement] = {
    # ---------------------------------------------------------------- products
    # Product / ProductVariant / ProductImage / Collection / Collect all sit
    # under the `products` family.
    **_reads(
        "list_products",
        "get_product_by_id",
        "count_products",
        "list_product_variants",
        "get_product_variant_by_id",
        "count_product_variants",
        "list_product_images",
        "get_product_image_by_id",
        "list_collections",
        "get_collection_by_id",
        "query_products_with_graphql",
        "query_collections_with_graphql",
        scope="read_products",
    ),
    **_reads(
        "create_product",
        "update_product",
        "delete_product",
        "create_product_variant",
        "update_product_variant",
        "delete_product_variant",
        "create_product_image",
        "delete_product_image",
        "create_collection",
        "update_collection",
        "delete_collection",
        "add_product_to_collection",
        "create_product_with_graphql",
        "update_product_with_graphql",
        scope="write_products",
    ),
    # ------------------------------------------------------------------ orders
    # Order / Refund / Transaction / (legacy) Fulfillment reads.
    **_reads(
        "list_orders",
        "get_order_by_id",
        "count_orders",
        "list_order_refunds",
        "get_order_refund_by_id",
        "list_order_transactions",
        "get_order_transaction_by_id",
        "count_order_transactions",
        "list_order_fulfillments",
        "get_order_fulfillment",
        "query_orders_with_graphql",
        scope="read_orders",
        note=_ORDERS_OR,
    ),
    **_reads(
        "create_order",
        "update_order",
        "delete_order",
        "cancel_order",
        "close_order",
        "reopen_closed_order",
        "create_order_refund",
        # POST /refunds/calculate.json is non-mutating but sits under the same
        # resource banner as the create; Shopify documents no read-only variant.
        "calculate_order_refund",
        "create_order_transaction",
        scope="write_orders",
        note=_ORDERS_OR,
    ),
    # `read_orders` alone only reaches the last 60 days of orders; `read_all_orders`
    # (app-review gated) is required for older ones and is NOT requested.
    # Webhook topics carry the topic's own scope, and read is implied by write.
    **_reads(
        "on_order_created",
        "on_order_paid",
        "on_order_fulfilled",
        "on_order_cancelled",
        scope="read_orders",
        note="Webhook topic orders/* requires the orders access scope.",
    ),
    # ------------------------------------------------------------ fulfillments
    **_reads(
        "create_order_fulfillment",
        "update_order_fulfillment",
        "complete_order_fulfillment",
        "cancel_order_fulfillment",
        scope="write_merchant_managed_fulfillment_orders",
        note=_FULFILL_OR,
    ),
    "query_fulfillment_orders_with_graphql": _s(
        "read_merchant_managed_fulfillment_orders",
        note=(
            "The fulfillmentOrders query accepts read_assigned_/"
            "read_merchant_managed_/read_third_party_/"
            "read_marketplace_fulfillment_orders and filters results to the "
            "granted subset."
        ),
    ),
    # --------------------------------------------------------------- customers
    **_reads(
        "list_customers",
        "get_customer_by_id",
        "search_customers",
        "count_customers",
        "list_customer_addresses",
        "get_customer_address_by_id",
        "query_customers_with_graphql",
        scope="read_customers",
    ),
    **_reads(
        "create_customer",
        "update_customer",
        "delete_customer",
        "create_customer_address",
        "update_customer_address",
        "delete_customer_address",
        "set_default_customer_address",
        "create_customer_with_graphql",
        scope="write_customers",
    ),
    "on_customer_created": _s(
        "read_customers",
        note="Webhook topic customers/create requires the customers scope.",
    ),
    **_reads(
        "on_product_created",
        "on_product_updated",
        scope="read_products",
        note="Webhook topic products/* requires the products access scope.",
    ),
    # --------------------------------------------------------------- inventory
    **_reads(
        "list_inventory_levels",
        "query_inventory_with_graphql",
        scope="read_inventory",
    ),
    **_reads(
        "adjust_inventory_level_at_location",
        "set_inventory_level_at_location",
        "connect_inventory_item_to_location",
        "delete_inventory_level",
        scope="write_inventory",
    ),
    # --------------------------------------------------------------- locations
    # The REST Location page states no scope; the scope table and the GraphQL
    # Location object both name read_locations (read_inventory also works).
    **_reads(
        "list_all_locations",
        "get_location_by_id",
        scope="read_locations",
        note="read_inventory is a documented alternative.",
    ),
    # -------------------------------------------------------------------- shop
    # Neither the REST Shop resource, the GraphQL `shop` query nor the `Shop`
    # object documents a required scope, and no `read_shop` scope exists.
    "get_shop_information": _s(
        note="Shopify documents no scope for the Shop resource."
    ),
    "get_shop_with_graphql": _s(note="Shopify documents no scope for the shop query."),
    # -------------------------------------------------------------------- blog
    # Blog + Article ride the Online Store `content` scope family (the REST
    # Article/Blog pages both state "Requires `content` access scope").
    **_reads(
        "list_blogs",
        "list_blog_articles",
        "get_blog_article_by_id",
        scope="read_content",
    ),
    **_reads(
        "create_blog_article",
        "update_blog_article",
        "delete_blog_article",
        scope="write_content",
    ),
    # ---------------------------------------------------------------- webhooks
    # Webhook management itself needs no scope (there is no read_/write_webhooks
    # scope); only the subscribed TOPIC carries one.
    "list_webhooks": _s(note=_WEBHOOK_ADMIN),
    "get_webhook_by_id": _s(note=_WEBHOOK_ADMIN),
    "delete_webhook": _s(note=_WEBHOOK_ADMIN),
}


SHOPIFY_SCOPES = ScopeRegistry(
    provider="shopify",
    requirements=_REQUIREMENTS,
    unmapped=(
        # Scope is the OWNER resource's scope, chosen at runtime: the node's
        # `resource` field targets product/order/customer metafields or the
        # shop-level collection. Shopify documents no metafield scope at any
        # layer (REST, GraphQL object, or the scope table).
        "list_metafields",
        "get_metafield_by_id",
        "create_metafield",
        "update_metafield",
        "delete_metafield",
        # Scope is the SUBSCRIBED TOPIC's scope, chosen at runtime. Registering
        # a topic the app lacks the scope for returns 422 with "Is there a
        # missing access scope?".
        "create_webhook",
        "update_webhook",
        # The caller supplies arbitrary GraphQL, so the scope is whatever the
        # document touches.
        "execute_custom_graphql_query",
        "execute_custom_graphql_mutation",
        # Shopify's REST Customer page is the only endpoint on it without a
        # "Requires" banner, and the GraphQL equivalent (Customer.orders) also
        # states none. Plainly needs the orders family, but it is undocumented.
        "get_customer_orders",
    ),
)
