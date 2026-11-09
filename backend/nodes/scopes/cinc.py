"""CINC endpoint permissions: https://public.cincapi.com/v2/docs/#cinc-all-scopes"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement, Enforcement
from nodes.cinc_operations import OPERATIONS

CINC_SCOPES = ScopeRegistry(
    provider="cinc",
    requirements={name: ScopeRequirement(scopes=(op["scope"],)) for name, op in OPERATIONS.items()},
    enforcement=Enforcement.STRICT,
)
