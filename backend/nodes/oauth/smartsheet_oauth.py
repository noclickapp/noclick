"""Smartsheet OAuth declaration and rotating refresh through the shared transport.

Authorize/token flow:
https://developers.smartsheet.com/api/smartsheet/guides/advanced-topics/oauth
Identity endpoint:
https://developers.smartsheet.com/api/smartsheet/openapi/users/get-current-user
"""

from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.smartsheet import SMARTSHEET_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="smartsheet",
    authorize_url="https://app.smartsheet.com/b/authorize",
    token_url="https://api.smartsheet.com/2.0/token",
    identity_url="https://api.smartsheet.com/2.0/users/me",
    name_field="email",
    scope_registry=SMARTSHEET_SCOPES,
    client_id_env="SMARTSHEET_CLIENT_ID",
    client_secret_env="SMARTSHEET_CLIENT_SECRET",
    redirect_uri_env="SMARTSHEET_REDIRECT_URI",
    credential_type="smartsheet_oauth",
    token_auth="body",
    rotates_refresh_tokens=True,
)

refresh_access_token = OAUTH_PROVIDER.refresh
