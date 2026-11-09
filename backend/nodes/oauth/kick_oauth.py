"""Kick OAuth 2.1 declaration.

Authorize/token/refresh: https://docs.kick.com/getting-started/generating-tokens-oauth2-flow
Identity: https://docs.kick.com/apis/users (GET /public/v1/users without IDs).
App registration: https://docs.kick.com/getting-started/kick-apps-setup
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.kick import KICK_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="kick",
    authorize_url="https://id.kick.com/oauth/authorize",
    token_url="https://id.kick.com/oauth/token",
    identity_url="https://api.kick.com/public/v1/users",
    name_field="data.0.name",
    scope_registry=KICK_SCOPES,
    client_id_env="KICK_CLIENT_ID",
    client_secret_env="KICK_CLIENT_SECRET",
    redirect_uri_env="KICK_REDIRECT_URI",
    credential_type="kick_oauth",
    pkce=True,
    token_auth="body",
    # Kick made refresh tokens reusable on 2025-11-25.
    rotates_refresh_tokens=False,
)

refresh_access_token = OAUTH_PROVIDER.refresh
