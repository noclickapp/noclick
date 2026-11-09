"""Domain scopes: https://docs.actionstep.com/api-scopes/"""
from nodes.actionstep_operations import OPERATIONS
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

ACTIONSTEP_SCOPES = ScopeRegistry(
    provider="actionstep",
    requirements={name: ScopeRequirement(scopes=(resource,))
                  for name, (_, resource, _) in OPERATIONS.items()},
    extra_scopes={"default": ("users",)},  # OAuth's current-user identity read.
)
