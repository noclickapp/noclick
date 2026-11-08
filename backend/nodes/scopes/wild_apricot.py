"""The provider detects permissions from the signing-in member with scope auto.

https://gethelp.wildapricot.com/en/articles/484-api-authentication
The token's permissions are account-specific; auto does not elevate that user.
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from nodes.wild_apricot_operations import OPERATIONS

WILD_APRICOT_SCOPES = ScopeRegistry(
    provider="wild_apricot",
    requirements={name: ScopeRequirement(scopes=("auto",)) for name in OPERATIONS},
)
