"""Scoro v4 endpoint security declarations.

https://api.scoro.com/api/v4/reference/openapi
The current-user endpoint accepts base:r OR users:r; choose base:r.
Read and write scopes are cumulative; request the literal declared requirements.
"""
from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement
from nodes.scoro_operations import SCORO_OPERATIONS

SCORO_SCOPES = ScopeRegistry(
    provider="scoro",
    requirements={
        name: ScopeRequirement(spec["scope"]) for name, spec in SCORO_OPERATIONS.items()
    },
    extra_scopes={"default": ("offline_access",)},
    enforcement=Enforcement.STRICT,
)
