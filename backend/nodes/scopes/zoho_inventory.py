"""Zoho Inventory API and account identity scopes.

https://www.zoho.com/inventory/api/v1/oauth/
https://docs.catalyst.zoho.com/en/zest/help/zest-specification-file/authentication-schema/oauth2/
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from nodes.zoho_inventory_operations import OPERATIONS

ZOHO_INVENTORY_SCOPES = ScopeRegistry(
    provider="zoho_inventory",
    requirements={name: ScopeRequirement(scopes=("ZohoInventory.FullAccess.all",))
                  for name in (*OPERATIONS, "on_item_created_or_updated", "on_sales_order_created_or_updated",
                               "on_purchase_order_created_or_updated", "on_invoice_created_or_updated")},
    extra_scopes={"default": ("AaaServer.profile.READ", "email")},
)
