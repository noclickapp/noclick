"""Kommo permissions are configured on the integration, not scope strings.

https://developers.kommo.com/docs/oauth-20 documents authorization without a
scope parameter; API access follows the authorizing user's permissions.
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from nodes.kommo_operations import KOMMO_OPERATIONS

KOMMO_SCOPES = ScopeRegistry(
    provider="kommo",
    requirements={operation: ScopeRequirement() for operation in KOMMO_OPERATIONS},
)
