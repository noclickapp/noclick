"""Estimate Rocket authorization code flow.

Authorize/token URLs: components.securitySchemes.oauth in
https://estimaterocketapi.com/api-docs/v1/swagger-production.yaml
Identity: GET /api/v1/me in the same published contract.
API enablement/registration: https://estimaterocketapi.com/
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.converted_da_56088 import ESTIMATE_ROCKET_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="estimaterocket",
    authorize_url="https://estimate-rocket-api.herokuapp.com/oauth/authorize",
    token_url="https://estimate-rocket-api.herokuapp.com/oauth/token",
    identity_url="https://estimate-rocket-api.herokuapp.com/api/v1/me",
    name_field="employee.name",
    scope_registry=ESTIMATE_ROCKET_SCOPES,
    client_id_env="ESTIMATE_ROCKET_CLIENT_ID",
    client_secret_env="ESTIMATE_ROCKET_CLIENT_SECRET",
    redirect_uri_env="ESTIMATE_ROCKET_REDIRECT_URI",
    credential_type="estimaterocket_oauth",
    token_auth="body",
)

refresh_access_token = OAUTH_PROVIDER.refresh
