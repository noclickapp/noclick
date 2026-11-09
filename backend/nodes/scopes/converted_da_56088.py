"""Estimate Rocket v1 security contract requests both read and write globally.

https://estimaterocketapi.com/api-docs/v1/swagger-production.yaml
https://support.estimaterocket.com/44018-integrations/estimate-rocket-2024-enhancements-to-api
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from nodes.converted_da_56088_operations import ROUTES

ESTIMATE_ROCKET_SCOPES = ScopeRegistry(
    provider="estimaterocket",
    requirements={operation: ScopeRequirement(("read", "write")) for operation in ROUTES},
)
