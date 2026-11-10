"""Scopes verified against Egnyte's OAuth scope table.

https://us-partner-integrations.egnyte.com/integration/cfs/api-docs/authentication#oauth-scopes
File System scope includes Search, Comments and Events; Links has its own scope.
The token's userinfo endpoint needs no additional scope. Webhook registration
requires Egnyte.webhooks:
https://developers.egnyte.com/integration/cfs/api-docs/webhooks
"""
from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement
from nodes.egnyte_operations import EGNYTE_OPERATIONS

EGNYTE_SCOPES = ScopeRegistry(
    provider="egnyte",
    requirements={**{name: ScopeRequirement((scope,) if scope else ())
                  for name, (_, _, scope) in EGNYTE_OPERATIONS.items()},
                  "on_file_uploaded": ScopeRequirement(("Egnyte.webhooks",))},
    enforcement=Enforcement.STRICT,
)
