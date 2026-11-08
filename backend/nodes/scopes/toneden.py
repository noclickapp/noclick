"""ToneDen documents no scope strings; access follows the authorizing account.

https://developers.toneden.io/docs/getting-started
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from nodes.toneden_operations import TONEDEN_OPERATIONS

TONEDEN_SCOPES = ScopeRegistry(
    provider="toneden",
    requirements={operation: ScopeRequirement() for operation in TONEDEN_OPERATIONS},
)
