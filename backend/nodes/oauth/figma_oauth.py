"""Figma OAuth with its documented separate refresh endpoint.

Authorize, token exchange, PKCE and refresh:
https://developers.figma.com/docs/rest-api/oauth-apps/
Identity: https://developers.figma.com/docs/rest-api/users-endpoints/
"""

from dataclasses import replace

from nodes.core.oauth_provider import OAuthProviderSpec, OAuthTokens
from nodes.scopes.figma import FIGMA_SCOPES


class FigmaOAuthProviderSpec(OAuthProviderSpec):
    async def refresh(self, refresh_token: str) -> OAuthTokens:
        # Figma uses a separate URL and no grant_type when refreshing.
        refresh_spec = replace(self, token_url="https://api.figma.com/v1/oauth/refresh")
        tokens, _ = await refresh_spec._tokens({"refresh_token": refresh_token})
        # Figma refresh tokens are reusable and not returned by this endpoint.
        tokens.refresh_token = tokens.refresh_token or refresh_token
        return tokens


OAUTH_PROVIDER = FigmaOAuthProviderSpec(
    provider="figma",
    authorize_url="https://www.figma.com/oauth",
    token_url="https://api.figma.com/v1/oauth/token",
    identity_url="https://api.figma.com/v1/me",
    name_field="handle",
    scope_registry=FIGMA_SCOPES,
    client_id_env="FIGMA_CLIENT_ID",
    client_secret_env="FIGMA_CLIENT_SECRET",
    redirect_uri_env="FIGMA_REDIRECT_URI",
    credential_type="figma_oauth",
    pkce=True,
    token_auth="basic",
    rotates_refresh_tokens=False,
)

refresh_access_token = OAUTH_PROVIDER.refresh
