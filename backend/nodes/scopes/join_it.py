"""Join It has no granular scopes; tokens report the fixed scope 'all'.

https://docs.joinitapi.com/docs/authentication
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from nodes.join_it_operations import OPERATIONS

JOIN_IT_SCOPES = ScopeRegistry(
    provider="join-it",
    requirements={operation: ScopeRequirement() for operation in OPERATIONS},
)
