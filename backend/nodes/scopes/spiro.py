"""Spiro's REST API grants organization-wide admin access only.

https://developers.spiro.ai/#section/Generating-an-Access-Token
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement, Enforcement
from nodes.spiro_operations import OPERATIONS

SPIRO_SCOPES = ScopeRegistry(
    provider="spiro",
    enforcement=Enforcement.STRICT,
    requirements={name: ScopeRequirement(scopes=("admin",)) for name in OPERATIONS},
)
