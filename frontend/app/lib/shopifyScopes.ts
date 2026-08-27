// Minimal scopes used by the public Shopify app. The Shopify node schema lists
// read and write choices separately for custom connections, while Shopify's
// public-app write scopes already include read access to the same resource.
// App-review-only `read_all_orders` is intentionally absent until Shopify
// approves the separate protected-access request.
export const SHOPIFY_APP_SCOPES = [
    'write_products',
    'write_orders',
    'write_customers',
    'write_inventory',
    'write_fulfillments',
    'write_shipping',
    'read_locations',
    'write_merchant_managed_fulfillment_orders',
    'write_assigned_fulfillment_orders',
    'write_third_party_fulfillment_orders',
    'write_content',
] as const;

export const SHOPIFY_APP_SCOPES_PARAM = SHOPIFY_APP_SCOPES.join(',');
