"""Sellsy OAuth2 with mandatory PKCE and rotating refresh tokens.

Authorize/token/refresh: https://docs.sellsy.com/api/v2/#section/Authentication
Staff identity (/staffs/{id} accepts `me`): https://docs.sellsy.com/api/v2/#operation/get-staff
Client registration: https://www.sellsy.fr/developer/api-v2
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.sellsy import SELLSY_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="sellsy",
    authorize_url="https://login.sellsy.com/oauth2/authorization",
    token_url="https://login.sellsy.com/oauth2/access-tokens",
    identity_url="https://api.sellsy.com/v2/staffs/me",
    name_field="email",
    scope_registry=SELLSY_SCOPES,
    client_id_env="SELLSY_CLIENT_ID",
    client_secret_env="SELLSY_CLIENT_SECRET",
    redirect_uri_env="SELLSY_REDIRECT_URI",
    credential_type="sellsy_oauth",
    pkce=True,
    token_format="json",
    token_auth="body",
    rotates_refresh_tokens=True,
)

refresh_access_token = OAUTH_PROVIDER.refresh
