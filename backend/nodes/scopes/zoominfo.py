"""Scopes from https://docs.gtm.ai/docs/zoominfo-oauth-scopes and endpoint contracts.

Usage and lookup endpoints accept ANY of their listed data scopes. We select
company for usage and lookup for field metadata; all scopes are requested
because the node exposes all five kinds of search.
"""
from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement
from nodes.zoominfo_operations import ZOOMINFO_OPERATIONS

ZOOMINFO_SCOPES = ScopeRegistry(
    provider="zoominfo",
    requirements={name: ScopeRequirement((spec["scope"],)) for name, spec in ZOOMINFO_OPERATIONS.items()},
    enforcement=Enforcement.STRICT,
)
