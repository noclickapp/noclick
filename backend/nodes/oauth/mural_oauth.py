"""Mural's standard OAuth2 provider, discovered without shared routes.

Authorize/token endpoints and reusable refresh tokens:
https://developers.mural.co/public/docs/oauth
Identity endpoint and its value.firstName field:
https://developers.mural.co/public/reference/getcurrentmember
"""

from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.mural import MURAL_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="mural",
    authorize_url="https://app.mural.co/api/public/v1/authorization/oauth2/",
    token_url="https://app.mural.co/api/public/v1/authorization/oauth2/token",
    identity_url="https://app.mural.co/api/public/v1/users/me",
    name_field="value.firstName",
    scope_registry=MURAL_SCOPES,
    client_id_env="MURAL_CLIENT_ID",
    client_secret_env="MURAL_CLIENT_SECRET",
    redirect_uri_env="MURAL_REDIRECT_URI",
    credential_type="mural_oauth",
    pkce=True,
    token_auth="body",
    rotates_refresh_tokens=False,
)

refresh_access_token = OAUTH_PROVIDER.refresh
