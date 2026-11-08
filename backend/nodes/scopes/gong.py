"""Gong operation scopes from the official endpoint references."""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from nodes.gong_operations import OPERATIONS

GONG_SCOPES = ScopeRegistry(
    provider="gong",
    requirements={name: ScopeRequirement(scopes=op.scopes) for name, op in OPERATIONS.items()},
)
