"""GoTo Connect authorization-code flow with provider-managed refresh tokens.

Authorize/token: https://developer.goto.com/Authentication
Identity: https://developer.goto.com/GoToConnect/#tag/Me
Client console: https://developer.logmeininc.com/clients
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.go_to_connect import GO_TO_CONNECT_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="go_to_connect",
    authorize_url="https://authentication.logmeininc.com/oauth/authorize",
    token_url="https://authentication.logmeininc.com/oauth/token",
    identity_url="https://api.goto.com/users/v1/me",
    name_field="items.0.accountKey",
    scope_registry=GO_TO_CONNECT_SCOPES,
    client_id_env="GO_TO_CONNECT_CLIENT_ID",
    client_secret_env="GO_TO_CONNECT_CLIENT_SECRET",
    redirect_uri_env="GO_TO_CONNECT_REDIRECT_URI",
    credential_type="go_to_connect_oauth",
    token_auth="basic", pkce=False, rotates_refresh_tokens=False,
)
refresh_access_token = OAUTH_PROVIDER.refresh
