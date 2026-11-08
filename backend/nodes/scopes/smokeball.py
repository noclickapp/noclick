"""Resource and parent-matter scopes.
https://docs.smokeball.com/docs/api-docs/qf83nz2scopes-scopes
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from nodes.smokeball_operations import OPERATIONS

SMOKEBALL_SCOPES = ScopeRegistry(
    provider="smokeball",
    requirements={name: ScopeRequirement(scopes=op.scopes) for name, op in OPERATIONS.items()},
)
