"""Arthur Online requests no OAuth scopes, as its Postman setup directs.

https://documenter.getpostman.com/view/22554870/2s93sZ5YeM
The operation map still provides exhaustive scope coverage for every call.
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement, Enforcement
from nodes.arthur_online_operations import OPERATIONS

ARTHUR_ONLINE_SCOPES = ScopeRegistry(
    provider="arthur-online",
    requirements={name: ScopeRequirement(scopes=()) for name in OPERATIONS},
    enforcement=Enforcement.STRICT,
)
