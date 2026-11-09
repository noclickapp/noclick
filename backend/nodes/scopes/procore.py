"""User authorization follows Procore permissions, without named OAuth scopes.

https://developers.procore.com/documentation/content/oauth-installed-apps
https://developers.procore.com/documentation/content/building-data-connection-apps
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from nodes.procore_operations import PROCORE_OPERATIONS

PROCORE_SCOPES = ScopeRegistry(provider="procore", requirements={
    operation: ScopeRequirement() for operation in (*PROCORE_OPERATIONS, "on_resource_event")
})
