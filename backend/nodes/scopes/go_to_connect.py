"""Scopes copied from the GoTo Connect endpoint authentication descriptions.

The current-user setup identity read uses users.v1.read.
https://developer.goto.com/GoToConnect/
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement, Enforcement
from nodes.go_to_connect_operations import OPERATIONS

GO_TO_CONNECT_SCOPES = ScopeRegistry(
    provider="go_to_connect",
    requirements={name: ScopeRequirement(scopes=op["scopes"]) for name, op in OPERATIONS.items()},
    enforcement=Enforcement.STRICT,
)
