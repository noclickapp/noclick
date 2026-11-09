"""Front OAuth: https://dev.frontapp.com/docs/oauth
Identity: https://dev.frontapp.com/reference/api-token-details
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.front import FRONT_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="front",
    authorize_url="https://app.frontapp.com/oauth/authorize",
    token_url="https://app.frontapp.com/oauth/token",
    identity_url="https://api2.frontapp.com/me",
    name_field="name",
    scope_registry=FRONT_SCOPES,
    client_id_env="FRONT_CLIENT_ID",
    client_secret_env="FRONT_CLIENT_SECRET",
    redirect_uri_env="FRONT_REDIRECT_URI",
    credential_type="front_oauth",
    token_auth="basic",
    expires_at_field="expires_at",
    # Front returns the current refresh token until its final 24 hours.
    rotates_refresh_tokens=False,
)

refresh_access_token = OAUTH_PROVIDER.refresh
exchange_code_for_tokens = OAUTH_PROVIDER.exchange
