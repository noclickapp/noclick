"""Spotify authorization-code flow, with optional refresh-token replacement.

Authorize and token: https://developer.spotify.com/documentation/web-api/tutorials/code-flow
Refresh: https://developer.spotify.com/documentation/web-api/tutorials/refreshing-tokens
Identity: https://developer.spotify.com/documentation/web-api/reference/get-current-users-profile
Register apps: https://developer.spotify.com/dashboard
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.spotify import SPOTIFY_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="spotify",
    authorize_url="https://accounts.spotify.com/authorize",
    token_url="https://accounts.spotify.com/api/token",
    identity_url="https://api.spotify.com/v1/me",
    name_field="account_id",
    scope_registry=SPOTIFY_SCOPES,
    client_id_env="SPOTIFY_CLIENT_ID",
    client_secret_env="SPOTIFY_CLIENT_SECRET",
    redirect_uri_env="SPOTIFY_REDIRECT_URI",
    credential_type="spotify_oauth",
    token_auth="basic",
    pkce=False,
    rotates_refresh_tokens=False,
)
refresh_access_token = OAUTH_PROVIDER.refresh
