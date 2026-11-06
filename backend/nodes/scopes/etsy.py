"""Etsy scopes transcribed from each official OpenAPI operation's security.

https://www.etsy.com/openapi/generated/oas/3.0.0.json (version 3.0.0).
Pasted OAuth user tokens must already carry these grants. Public reads have
an empty requirement; account evidence getMe requires shops_r.
"""
from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement

ETSY_SCOPES = ScopeRegistry(
    provider="etsy",
    requirements={
        "get_me": ScopeRequirement(scopes=("shops_r",)),
        "get_shop": ScopeRequirement(scopes=()),
        "update_shop": ScopeRequirement(scopes=("shops_r", "shops_w")),
        "list_shop_sections": ScopeRequirement(scopes=()),
        "create_shop_section": ScopeRequirement(scopes=("shops_w",)),
        "update_shop_section": ScopeRequirement(scopes=("shops_w",)),
        "list_shipping_profiles": ScopeRequirement(scopes=("shops_r",)),
        "list_listings": ScopeRequirement(scopes=("listings_r",)),
        "get_listing": ScopeRequirement(scopes=()),
        "create_draft_listing": ScopeRequirement(scopes=("listings_w",)),
        "update_listing": ScopeRequirement(scopes=("listings_w",)),
        "delete_listing": ScopeRequirement(scopes=("listings_d",)),
        "get_listing_inventory": ScopeRequirement(scopes=("listings_r",)),
        "update_listing_inventory": ScopeRequirement(scopes=("listings_w",)),
        "list_listing_images": ScopeRequirement(scopes=()),
        "list_orders": ScopeRequirement(scopes=("transactions_r",)),
        "get_order": ScopeRequirement(scopes=("transactions_r",)),
        "update_order": ScopeRequirement(scopes=("transactions_w",)),
        "create_shipment": ScopeRequirement(scopes=("transactions_w",)),
        "list_order_transactions": ScopeRequirement(scopes=("transactions_r",)),
    },
    enforcement=Enforcement.STRICT,
)
