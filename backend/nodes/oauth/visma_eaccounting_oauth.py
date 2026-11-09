"""Authorize/token and company identity:
https://developer.vismaonline.com/docs/authentication
https://developer.vismaonline.com/docs/environments
https://eaccountingapi.vismaonline.com/openapi/v2.json#/paths/~1companysettings/get
Rotation: https://developer.vismaonline.com/changelog/changes-to-identityserver-clients
App registration: https://selfservice.developer.vismaonline.com/
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.visma_eaccounting import VISMA_EACCOUNTING_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="visma-eaccounting",
    authorize_url="https://identity.vismaonline.com/connect/authorize",
    token_url="https://identity.vismaonline.com/connect/token",
    identity_url="https://eaccountingapi.vismaonline.com/v2/companysettings",
    name_field="Name",
    scope_registry=VISMA_EACCOUNTING_SCOPES,
    client_id_env="VISMA_EACCOUNTING_CLIENT_ID",
    client_secret_env="VISMA_EACCOUNTING_CLIENT_SECRET",
    redirect_uri_env="VISMA_EACCOUNTING_REDIRECT_URI",
    credential_type="visma_eaccounting_oauth",
    pkce=False, token_auth="basic", rotates_refresh_tokens=True,
    authorize_params={"prompt": "select_account", "acr_values": "service:44643EB1-3F76-4C1C-A672-402AE8085934"},
)
refresh_access_token = OAUTH_PROVIDER.refresh
