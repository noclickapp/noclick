"""Omnisend authorization-code OAuth declaration.

Authorize/token: https://api-docs.omnisend.com/reference/oauth
Identity: https://api-docs.omnisend.com/reference/get_brands-current
"""
import httpx

from nodes.core.oauth_provider import OAuthProviderSpec, read_field
from nodes.scopes.omnisend import OMNISEND_SCOPES


class OmnisendOAuthProviderSpec(OAuthProviderSpec):
    async def account_name(self, access_token: str) -> str:
        # Omnisend requires an API version header on its brand identity endpoint.
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.get(
                self.identity_url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Omnisend-Version": "2026-03-15",
                    "Accept": "application/json",
                },
            )
        response.raise_for_status()
        name = read_field(response.json(), self.name_field)
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Omnisend returned no brand name")
        return name


OAUTH_PROVIDER = OmnisendOAuthProviderSpec(
    provider="omnisend",
    authorize_url="https://app.omnisend.com/oauth2/authorize",
    token_url="https://app.omnisend.com/oauth2/token",
    identity_url="https://api.omnisend.com/api/brands/current",
    name_field="name",
    scope_registry=OMNISEND_SCOPES,
    client_id_env="OMNISEND_CLIENT_ID",
    client_secret_env="OMNISEND_CLIENT_SECRET",
    redirect_uri_env="OMNISEND_REDIRECT_URI",
    credential_type="omnisend_oauth",
    token_auth="body",
)

refresh_access_token = OAUTH_PROVIDER.refresh
