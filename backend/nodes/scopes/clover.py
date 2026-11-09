"""Clover permissions are selected in the developer dashboard, not OAuth scope strings.

https://docs.clover.com/dev/docs/gdp-set-app-permissions
https://docs.clover.com/dev/docs/high-trust-app-auth-flow
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from nodes.clover_operations import CLOVER_OPERATIONS, CLOVER_TRIGGERS

CLOVER_SCOPES = ScopeRegistry(
    provider="clover",
    requirements={name: ScopeRequirement(note="Grant the corresponding merchant permission in your Clover app settings.")
                  for name in (*CLOVER_OPERATIONS, *CLOVER_TRIGGERS)},
)
