"""Smokeball US OAuth. The app key is required on identity and API reads.
Authorize/token: https://docs.smokeball.com/docs/api-docs/2t26gcuuqf1wk-authorization-code-grant
Identity: https://docs.smokeball.com/api-reference/firm/get-firm
Headers: https://docs.smokeball.com/docs/api-docs/ivmfjbc61tvjs-making-requests
"""
import os
from nodes.core.credential_fields import clean_secret
from nodes.core.oauth_provider import OAuthProviderSpec, read_field
from nodes.scopes.smokeball import SMOKEBALL_SCOPES


def application_api_key() -> str:
    value = os.environ.get("SMOKEBALL_API_KEY", "")
    if not value:
        raise ValueError("Configure the application's SMOKEBALL_API_KEY")
    value = clean_secret(value, field_name="API key")
    if any(ord(c) < 33 or ord(c) > 126 for c in value):
        raise ValueError("Smokeball application API key is invalid")
    return value


class SmokeballOAuthProviderSpec(OAuthProviderSpec):
    async def account_name(self, access_token: str) -> str:
        async with self._client(self.identity_url) as client:
            response = await client.get(self.identity_url, headers={
                "Authorization": f"Bearer {access_token}", "x-api-key": application_api_key(),
                "Accept": "application/json"})
        response.raise_for_status()
        name = read_field(response.json(), self.name_field)
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Smokeball returned no firm name")
        return name


OAUTH_PROVIDER = SmokeballOAuthProviderSpec(
    provider="smokeball",
    authorize_url="https://auth.smokeball.com/oauth2/authorize",
    token_url="https://auth.smokeball.com/oauth2/token",
    identity_url="https://api.smokeball.com/firm", name_field="name",
    scope_registry=SMOKEBALL_SCOPES,
    client_id_env="SMOKEBALL_CLIENT_ID", client_secret_env="SMOKEBALL_CLIENT_SECRET",
    redirect_uri_env="SMOKEBALL_REDIRECT_URI", credential_type="smokeball_oauth",
    pkce=True, token_auth="basic", rotates_refresh_tokens=False,
)
refresh_access_token = OAUTH_PROVIDER.refresh
