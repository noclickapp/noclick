"""Front app permissions are selected in the developer console, not in the authorize URL.
https://dev.frontapp.com/docs/oauth
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from nodes.front_operations import OPERATIONS

FRONT_SCOPES = ScopeRegistry(
    provider="front",
    requirements={name: ScopeRequirement() for name in (*OPERATIONS, "on_new_or_updated_conversation")},
)
