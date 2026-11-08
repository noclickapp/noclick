"""Productboard operation scopes from its official API v2 catalog.

https://developer.productboard.com/reference/oauth-authorization-code#access-scopes
"""
from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement
from nodes.productboard_operations import PRODUCTBOARD_OPERATIONS

PRODUCTBOARD_SCOPES = ScopeRegistry(
    provider="productboard",
    requirements={
        name: ScopeRequirement(scopes=tuple(operation["scopes"]))
        for name, operation in PRODUCTBOARD_OPERATIONS.items()
    },
    enforcement=Enforcement.STRICT,
)
