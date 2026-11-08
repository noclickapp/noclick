"""ZoomInfo user authorization with PKCE and one-use rotating refresh tokens.

Authorize/token: https://docs.gtm.ai/docs/authorization-code-flow-pkce
Refresh: https://docs.gtm.ai/docs/refresh-tokens-flow
Account proof: https://docs.gtm.ai/reference/userinterface_userusage
The usage resource's unique ID labels the connection; it is not a personal name.
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.zoominfo import ZOOMINFO_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="zoominfo",
    authorize_url="https://api.zoominfo.com/gtm/oauth/v1/authorize",
    token_url="https://api.zoominfo.com/gtm/oauth/v1/token",
    identity_url="https://api.zoominfo.com/gtm/data/v1/users/usage",
    name_field="data.0.id",
    scope_registry=ZOOMINFO_SCOPES,
    client_id_env="ZOOMINFO_CLIENT_ID",
    client_secret_env="ZOOMINFO_CLIENT_SECRET",
    redirect_uri_env="ZOOMINFO_REDIRECT_URI",
    credential_type="zoominfo_oauth",
    pkce=True,
    token_auth="basic",
    rotates_refresh_tokens=True,
)
