"""Kit OAuth declaration using the shared authorization-code transport.

Authorize/token: https://developers.kit.com/api-reference/oauth-refresh-token-flow
Identity: https://developers.kit.com/api-reference/accounts/get-current-account
Kit’s official strategy uses the standard OAuth2 client:
https://github.com/Kit/omniauth-kit-oauth2/blob/main/lib/omniauth/strategies/kit_oauth2.rb
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.kit import KIT_SCOPES


OAUTH_PROVIDER = OAuthProviderSpec(
    provider="kit",
    authorize_url="https://api.kit.com/v4/oauth/authorize",
    token_url="https://api.kit.com/v4/oauth/token",
    identity_url="https://api.kit.com/v4/account",
    name_field="account.name",
    scope_registry=KIT_SCOPES,
    client_id_env="KIT_CLIENT_ID",
    client_secret_env="KIT_CLIENT_SECRET",
    redirect_uri_env="KIT_REDIRECT_URI",
    credential_type="kit_oauth",
    token_auth="body",
    rotates_refresh_tokens=True,
)

refresh_access_token = OAUTH_PROVIDER.refresh
