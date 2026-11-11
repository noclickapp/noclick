"""Scopes published at https://bitsnap.pl/api/v1/openapi.json, version 1.0.0."""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

BITSNAP_SCOPES = ScopeRegistry(
    provider="bitsnap",
    requirements={
        'get_account': ScopeRequirement(()),
        'list_products': ScopeRequirement(('products:read',)),
        'get_product': ScopeRequirement(('products:read',)),
        'create_product': ScopeRequirement(('products:write',)),
        'update_product': ScopeRequirement(('products:write',)),
        'list_orders': ScopeRequirement(('orders:read',)),
        'get_order': ScopeRequirement(('orders:read',)),
        'list_coupons': ScopeRequirement(('coupons:read',)),
        'create_coupon': ScopeRequirement(('coupons:write',)),
        'update_coupon': ScopeRequirement(('coupons:write',)),
        'delete_coupon': ScopeRequirement(('coupons:write',)),
        'create_coupon_code': ScopeRequirement(('coupons:write',)),
        'delete_coupon_code': ScopeRequirement(('coupons:write',)),
        'create_checkout_link': ScopeRequirement(('checkout:create',)),
        'list_payment_links': ScopeRequirement(('payment_links:read',)),
        'get_payment_link': ScopeRequirement(('payment_links:read',)),
        'create_payment_link': ScopeRequirement(('payment_links:write',)),
        'archive_payment_link': ScopeRequirement(('payment_links:write',)),
        'send_payment_link': ScopeRequirement(('payment_links:write',)),
        'get_sales_summary': ScopeRequirement(('stats:read',)),
        'list_forms': ScopeRequirement(('leads:read',)),
        'list_leads': ScopeRequirement(('leads:read',)),
        'get_lead': ScopeRequirement(('leads:read',)),
        'update_lead': ScopeRequirement(('leads:write',)),
        'on_event': ScopeRequirement(('webhooks:write',)),
    },
)
