"""Crowdin full-access scope: https://support.crowdin.com/developer/understanding-scopes/"""
from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement
from nodes.crowdin_operations import OPERATIONS

CROWDIN_SCOPES = ScopeRegistry(
    "crowdin", {name: ScopeRequirement(("*",)) for name in OPERATIONS},
    enforcement=Enforcement.STRICT,
)
