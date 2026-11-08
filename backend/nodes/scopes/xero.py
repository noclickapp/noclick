"""Xero scopes: https://developer.xero.com/documentation/guides/oauth2/scopes/."""

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from nodes.xero_operations import OPERATIONS

XERO_SCOPES = ScopeRegistry(
    provider="xero",
    requirements={name: ScopeRequirement(scopes=(op.scope,) if op.scope else ())
                  for name, op in OPERATIONS.items()},
    extra_scopes={"default": ("openid", "email", "offline_access")},
)
