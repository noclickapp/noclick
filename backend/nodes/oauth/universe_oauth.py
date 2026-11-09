"""Universe OAuth: https://developers.universe.com/docs/authorizing-with-oauth

Identity: https://developers.universe.com/reference/current-user
Register apps: https://www.universe.com/oauth/applications
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.universe import UNIVERSE_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="universe",
    authorize_url="https://www.universe.com/oauth/authorize",
    token_url="https://www.universe.com/oauth/token",
    identity_url="https://www.universe.com/api/v2/current_user",
    name_field="current_user.email",
    scope_registry=UNIVERSE_SCOPES,
    client_id_env="UNIVERSE_CLIENT_ID",
    client_secret_env="UNIVERSE_CLIENT_SECRET",
    redirect_uri_env="UNIVERSE_REDIRECT_URI",
    credential_type="universe_oauth",
    token_auth="body",
)
