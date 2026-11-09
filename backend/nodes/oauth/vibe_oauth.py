"""Vibe authorization-code OAuth with PKCE S256 and rotating refresh tokens.

Authorize/token/rotation: https://developers.vibe.co/docs/start-your-oauth-flow
Identity: https://developers.vibe.co/reference/listaccounts-1
Revision header: https://developers.vibe.co/docs/universal-authorization
Register apps: https://vibe.co/dashboard/settings/my-applications
"""
from nodes.core.oauth_provider import OAuthProviderSpec, read_field
from nodes.scopes.vibe import VIBE_SCOPES


class VibeOAuthProviderSpec(OAuthProviderSpec):
    async def account_name(self, access_token: str, *, context=None) -> str:
        # Vibe requires its revision header on identity reads as on every resource
        # call. The standard token/exchange/rotation transports remain shared.
        context = self.validate_context(context)
        async with self._client(self.identity_url) as client:
            response = await client.get(self.endpoint(self.identity_url, context), headers={
                "Authorization": f"Bearer {access_token}", "X-Vibe-Revision": "2026-06-01"})
        response.raise_for_status()
        name = read_field(response.json(), self.name_field)
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Vibe returned no account name")
        return name


OAUTH_PROVIDER = VibeOAuthProviderSpec(
    provider="vibe",
    authorize_url="https://api.vibe.co/oauth2/auth",
    token_url="https://api.vibe.co/oauth2/token",
    identity_url="https://api.vibe.co/accounts",
    name_field="0.name",
    scope_registry=VIBE_SCOPES,
    client_id_env="VIBE_CLIENT_ID",
    client_secret_env="VIBE_CLIENT_SECRET",
    redirect_uri_env="VIBE_REDIRECT_URI",
    credential_type="vibe_oauth",
    pkce=True,
    token_auth="basic",
    rotates_refresh_tokens=True,
)

refresh_access_token = OAUTH_PROVIDER.refresh
