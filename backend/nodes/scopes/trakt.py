"""Trakt account access uses the public scope (the published OAuth flow).
https://developer.trakt.tv/openapi.json#/components/securitySchemes/traktOAuth
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from nodes.trakt_operations import TRAKT_OPERATIONS

TRAKT_SCOPES = ScopeRegistry(
    provider="trakt",
    requirements={name: ScopeRequirement("public") for name in TRAKT_OPERATIONS},
)
