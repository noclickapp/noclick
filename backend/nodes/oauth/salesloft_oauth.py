"""Salesloft authorization-code flow with single-use refresh rotation.

Authorize/token/rotation and form encoding:
https://developers.salesloft.com/docs/platform/api-basics/oauth-authentication/
Identity endpoint and display-name field:
https://developers.salesloft.com/docs/api/me-index/
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.salesloft import SALESLOFT_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="salesloft",
    authorize_url="https://accounts.salesloft.com/oauth/authorize",
    token_url="https://accounts.salesloft.com/oauth/token",
    identity_url="https://api.salesloft.com/v2/me",
    name_field="data.name",
    scope_registry=SALESLOFT_SCOPES,
    client_id_env="SALESLOFT_CLIENT_ID",
    client_secret_env="SALESLOFT_CLIENT_SECRET",
    redirect_uri_env="SALESLOFT_REDIRECT_URI",
    credential_type="salesloft_oauth",
    token_auth="body",
    rotates_refresh_tokens=True,
)

refresh_access_token = OAUTH_PROVIDER.refresh
