"""Webex standard OAuth2 integration declaration.

Authorize/token: https://developer.webex.com/admin/docs/authentication
Identity: https://developer.webex.com/docs/api/v1/people/get-my-own-details
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.webex import WEBEX_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="webex",
    authorize_url="https://webexapis.com/v1/authorize",
    token_url="https://webexapis.com/v1/access_token",
    identity_url="https://webexapis.com/v1/people/me",
    scope_registry=WEBEX_SCOPES,
    client_id_env="WEBEX_CLIENT_ID",
    client_secret_env="WEBEX_CLIENT_SECRET",
    redirect_uri_env="WEBEX_REDIRECT_URI",
    credential_type="webex_oauth",
    name_field="displayName",
    token_auth="body",
)

refresh_access_token = OAUTH_PROVIDER.refresh
