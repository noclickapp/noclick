"""Delegated Power BI permissions from each REST operation's Required Scope.

Read/write alternatives use the write scope already required by mutations.
Graph User.Read is first so Microsoft's shared exchange can identify the user.
https://learn.microsoft.com/en-us/rest/api/power-bi/
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from nodes.microsoft_power_bi_operations import OPERATIONS

RESOURCE = "https://analysis.windows.net/powerbi/api/"
POWER_BI_SCOPES = ScopeRegistry(
    provider="microsoft",
    requirements={name: ScopeRequirement(scopes=(RESOURCE + op.scope,))
                  for name, op in OPERATIONS.items()},
    extra_scopes={"default": ("https://graph.microsoft.com/User.Read", "offline_access")},
)
# The shared exchange identifies the user with a Graph token. Entra can consent
# to several resources at authorize, but tokens are minted for one at a time.
CONNECT_SCOPES = ["https://graph.microsoft.com/User.Read"] + sorted(
    set(POWER_BI_SCOPES.declared_scopes()) - {"https://graph.microsoft.com/User.Read"}
)
RESOURCE_SCOPES = " ".join(sorted({RESOURCE + op.scope for op in OPERATIONS.values()}))
