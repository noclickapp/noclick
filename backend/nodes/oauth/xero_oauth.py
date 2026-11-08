"""Xero standard OAuth, using staging's generic provider transport.

Authorize/token/refresh: https://developer.xero.com/documentation/guides/oauth2/auth-flow/
Identity discovery: https://identity.xero.com/.well-known/openid-configuration
Identity scopes: https://developer.xero.com/documentation/xero-app-store/app-partner-guides/sign-in/
"""

import httpx

from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.xero import XERO_SCOPES

CONNECTIONS_URL = "https://api.xero.com/connections"

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="xero",
    authorize_url="https://login.xero.com/identity/connect/authorize",
    token_url="https://identity.xero.com/connect/token",
    identity_url="https://identity.xero.com/connect/userinfo",
    name_field="email",
    scope_registry=XERO_SCOPES,
    client_id_env="XERO_CLIENT_ID",
    client_secret_env="XERO_CLIENT_SECRET",
    redirect_uri_env="XERO_REDIRECT_URI",
    credential_type="xero_oauth",
    token_auth="basic",
    rotates_refresh_tokens=True,
)

refresh_access_token = OAUTH_PROVIDER.refresh


async def get_connections(access_token: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            CONNECTIONS_URL, headers={"Authorization": f"Bearer {access_token}",
                                      "Accept": "application/json"})
    if response.is_error:
        raise ValueError(f"Xero connection lookup failed ({response.status_code})")
    data = response.json()
    if not isinstance(data, list):
        raise ValueError("Xero returned an invalid connection list")
    return data
