"""v1 has role-based permissions and no OAuth scopes in its published contract.

https://api.n2p.io/v1/openapi-1.10.json#/components/securitySchemes/versatureOauth
"""
from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement

NET2PHONE_SCOPES = ScopeRegistry(
    provider="net2phone",
    requirements={name: ScopeRequirement(()) for name in (
        "get_current_user", "get_account", "list_users", "get_user",
        "list_current_user_cdrs", "list_user_cdrs", "list_cdrs",
        "list_available_endpoints", "place_call", "create_subscription",
        "get_subscription", "delete_subscription", "on_call_event",
    )},
    enforcement=Enforcement.STRICT,
)
