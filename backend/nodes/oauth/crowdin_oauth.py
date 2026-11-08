"""Crowdin standard confidential OAuth with PKCE and rotating refresh tokens.

Authorize/token: https://support.crowdin.com/developer/authorizing-oauth-apps/
Identity: https://support.crowdin.com/developer/api/v2/#operation/api.user.get
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.crowdin import CROWDIN_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="crowdin",
    authorize_url="https://accounts.crowdin.com/oauth/authorize",
    token_url="https://accounts.crowdin.com/oauth/token",
    identity_url="https://api.crowdin.com/api/v2/user",
    name_field="data.username",
    scope_registry=CROWDIN_SCOPES,
    client_id_env="CROWDIN_CLIENT_ID",
    client_secret_env="CROWDIN_CLIENT_SECRET",
    redirect_uri_env="CROWDIN_REDIRECT_URI",
    credential_type="crowdin_oauth",
    pkce=True,
    token_auth="body",
    rotates_refresh_tokens=True,
)

refresh_access_token = OAUTH_PROVIDER.refresh
