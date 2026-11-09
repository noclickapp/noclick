"""Weeztix currently does not use scopes; authorization follows user roles.
https://docs.weeztix.com/docs/introduction/authentication/remarks/
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

WEEZTIX_SCOPES = ScopeRegistry("weeztix", {
    operation: ScopeRequirement((), note="Weeztix does not currently use scopes; company access and user roles apply.")
    for operation in ('list_events', 'get_event', 'update_event', 'list_event_dates', 'get_event_scanning_stats', 'list_event_tickets', 'list_event_shops', 'get_ticket', 'update_ticket', 'get_order', 'update_order_receiver', 'get_order_download_link', 'resend_order_confirmation', 'list_order_emails', 'get_shop', 'list_shop_tickets', 'list_shop_products', 'attach_shop_ticket', 'detach_shop_ticket', 'get_product', 'list_locations', 'get_location')
})
