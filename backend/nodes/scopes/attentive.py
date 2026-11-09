"""Attentive permissions for private custom apps.

https://docs.attentive.com/docs/authentication documents private-app API keys
and the corresponding API permissions. V1 operation scopes are pinned in
https://docs.attentive.com/openapi/attentive-api-bundled.yaml. V2 operations
below declare only bearer authentication in the pinned v2 contract.
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

ATTENTIVE_SCOPES = ScopeRegistry(
    provider="attentive",
    requirements={
        **{operation: ScopeRequirement(()) for operation in (
            "get_me", "list_segments", "create_segment", "get_segment",
            "update_segment", "archive_segment",
        )},
        "send_custom_event": ScopeRequirement(("events:write",)),
        "set_custom_attributes": ScopeRequirement(("attributes:write",)),
        "get_custom_attributes": ScopeRequirement(("attributes:write",)),
        "subscribe_user": ScopeRequirement(("subscriptions:write",)),
        "get_subscriptions": ScopeRequirement(("subscriptions:read",)),
        "unsubscribe_user": ScopeRequirement(("subscriptions:write",)),
        **{operation: ScopeRequirement(("ecommerce:write",)) for operation in (
            "record_product_view", "record_add_to_cart", "record_purchase",
        )},
    },
)
