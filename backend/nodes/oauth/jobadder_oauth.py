"""JobAdder authorization code flow with rotating refresh tokens.

Authorize/token/refresh: https://developers.jobadder.com/docs#section/Getting-Started/Authentication
Identity: https://developers.jobadder.com/docs#operation/GetCurrentUser
Registration: https://developers.jobadder.com/
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.jobadder import JOBADDER_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="jobadder",
    authorize_url="https://id.jobadder.com/connect/authorize",
    token_url="https://id.jobadder.com/connect/token",
    identity_url="https://api.jobadder.com/v2/users/current",
    name_field="email",
    scope_registry=JOBADDER_SCOPES,
    client_id_env="JOBADDER_CLIENT_ID",
    client_secret_env="JOBADDER_CLIENT_SECRET",
    redirect_uri_env="JOBADDER_REDIRECT_URI",
    credential_type="jobadder_oauth",
    token_auth="body",
    rotates_refresh_tokens=True,
)
