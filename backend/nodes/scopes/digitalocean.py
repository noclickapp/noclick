"""Full-access OAuth scope for the complete DigitalOcean operation catalog.

https://docs.digitalocean.com/reference/api/scopes/ documents api:write as
full API access. PAT users may instead select granular scopes in the console.
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from nodes.digitalocean_operations import OPERATIONS

DIGITALOCEAN_SCOPES = ScopeRegistry(
    provider="digitalocean",
    requirements={name: ScopeRequirement(scopes=("api:write",))
                  for name in (*OPERATIONS, "on_new_alert")},
)
