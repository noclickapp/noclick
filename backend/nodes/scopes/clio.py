"""Clio app permissions are configured in the developer console, not OAuth scopes.
https://docs.developers.clio.com/api-docs/clio-manage/authorization/
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from nodes.clio_operations import OPERATIONS

CLIO_SCOPES = ScopeRegistry(
    provider="clio",
    requirements={name: ScopeRequirement(scopes=()) for name in OPERATIONS},
)
