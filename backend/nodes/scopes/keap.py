"""Keap offers a single full-access scope for its REST API.

https://developer.infusionsoft.com/authentication/
"""
from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement
from nodes.keap_operations import OPERATIONS

KEAP_SCOPES = ScopeRegistry(
    "keap", {name: ScopeRequirement(("full",)) for name in OPERATIONS},
    enforcement=Enforcement.STRICT,
)
