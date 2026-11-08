"""Pinterest OAuth2 declaration.

Authorize/token: https://developers.pinterest.com/docs/getting-started/set-up-authentication-and-authorization/
Identity: https://developers.pinterest.com/docs/api/v5/user_account-get/
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.pinterest import PINTEREST_SCOPES


OAUTH_PROVIDER = OAuthProviderSpec(
    provider="pinterest",
    authorize_url="https://www.pinterest.com/oauth/",
    token_url="https://api.pinterest.com/v5/oauth/token",
    identity_url="https://api.pinterest.com/v5/user_account",
    name_field="username",
    scope_registry=PINTEREST_SCOPES,
    client_id_env="PINTEREST_CLIENT_ID",
    client_secret_env="PINTEREST_CLIENT_SECRET",
    redirect_uri_env="PINTEREST_REDIRECT_URI",
    credential_type="pinterest_oauth",
    token_auth="basic",
    rotates_refresh_tokens=True,
    token_params={"continuous_refresh": "true"},
)

refresh_access_token = OAUTH_PROVIDER.refresh
