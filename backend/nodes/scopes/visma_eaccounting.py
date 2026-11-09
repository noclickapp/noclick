"""Scopes verified against the descriptions of each selected v2 endpoint.
https://developer.vismaonline.com/docs/authentication
https://eaccountingapi.vismaonline.com/openapi/v2.json
Read operations use the full-access alternative because this node also writes.
"""
from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement
from nodes.visma_eaccounting_operations import VISMA_OPERATIONS

VISMA_EACCOUNTING_SCOPES = ScopeRegistry(
    provider="visma-eaccounting",
    requirements={name: ScopeRequirement((spec["scope"],)) for name, spec in VISMA_OPERATIONS.items()},
    extra_scopes={"default": ("ea:api", "offline_access")},
    enforcement=Enforcement.STRICT,
)
