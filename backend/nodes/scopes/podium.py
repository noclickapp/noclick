"""Provider-published operation scopes: https://docs.podium.com/docs/oauth-scopes.

Each read and write follows the corresponding Podium reference requirement.
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from nodes.podium_operations import OPERATIONS

PODIUM_SCOPES = ScopeRegistry(
    provider="podium",
    requirements={
        name: ScopeRequirement(scopes=(op["scope"],)) for name, op in OPERATIONS.items()
    },
)
