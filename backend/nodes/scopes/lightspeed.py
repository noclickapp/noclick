"""Required scopes from each operation in Lightspeed's official 2026-10 contract.

https://x-series-api.lightspeedhq.com/openapi/api-2026-10.yaml
Private app tokens select these permissions in the Developer Portal.
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

LIGHTSPEED_SCOPES = ScopeRegistry(
    "lightspeed",
    {
        "get_retailer": ScopeRequirement(("retailer:read", "payment_types:read")),
        "list_customers": ScopeRequirement(("customers:read",)),
        "get_customer": ScopeRequirement(("customers:read",)),
        "create_customer": ScopeRequirement(("customers:write",)),
        "update_customer": ScopeRequirement(("customers:write",)),
        "list_products": ScopeRequirement(("products:read",)),
        "get_product": ScopeRequirement(("products:read",)),
        "list_sales": ScopeRequirement(("sales:read",)),
        "get_sale": ScopeRequirement(("sales:read",)),
        "list_product_inventory": ScopeRequirement(("inventory:read",)),
        "list_outlets": ScopeRequirement(("outlets:read",)),
        "get_outlet": ScopeRequirement(("outlets:read",)),
        "list_registers": ScopeRequirement(("registers:read",)),
        "get_register": ScopeRequirement(("registers:read",)),
        "list_brands": ScopeRequirement(("products:read",)),
        "get_brand": ScopeRequirement(("products:read",)),
        "create_brand": ScopeRequirement(("products:write",)),
        "update_brand": ScopeRequirement(("products:write",)),
        "list_suppliers": ScopeRequirement(("suppliers:read",)),
        "get_supplier": ScopeRequirement(("suppliers:read",)),
        "create_supplier": ScopeRequirement(("suppliers:write",)),
        "list_customer_groups": ScopeRequirement(("customers:read",)),
        "list_taxes": ScopeRequirement(("taxes:read",)),
    },
)
