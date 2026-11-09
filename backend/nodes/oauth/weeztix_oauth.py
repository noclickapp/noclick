"""Weeztix OAuth authorization-code flow; refresh tokens rotate.
Authorize/token: https://docs.weeztix.com/docs/introduction/authentication/request-token/
Identity: https://docs.weeztix.com/docs/introduction/issue-request/
Refresh: https://docs.weeztix.com/docs/introduction/authentication/refresh-token/
Register: https://docs.weeztix.com/docs/introduction/authentication/create-client/
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.weeztix import WEEZTIX_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="weeztix",
    authorize_url="https://login.weeztix.com/login",
    token_url="https://auth.weeztix.com/tokens",
    identity_url="https://auth.weeztix.com/users/me",
    name_field="name",
    scope_registry=WEEZTIX_SCOPES,
    credential_type="weeztix_oauth",
    client_id_env="WEEZTIX_CLIENT_ID",
    client_secret_env="WEEZTIX_CLIENT_SECRET",
    redirect_uri_env="WEEZTIX_REDIRECT_URI",
    pkce=False,  # Not documented by Weeztix; confidential client authentication.
    token_auth="body",
    rotates_refresh_tokens=True,
)
refresh_access_token = OAUTH_PROVIDER.refresh
