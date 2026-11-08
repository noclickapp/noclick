"""Miro OAuth2 declaration and token context.

Authorize/token/rotation: https://developers.miro.com/docs/getting-started-with-oauth
Identity: https://developers.miro.com/reference/get-access-token-context
Configure an expiring-token app at https://miro.com/app/settings/user-profile/apps.
"""

import httpx

from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.miro import MIRO_SCOPES

CONTEXT_URL = "https://api.miro.com/v1/oauth-token"

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="miro",
    authorize_url="https://miro.com/oauth/authorize",
    token_url="https://api.miro.com/v1/oauth/token",
    identity_url=CONTEXT_URL,
    name_field="user.name",
    scope_registry=MIRO_SCOPES,
    client_id_env="MIRO_CLIENT_ID",
    client_secret_env="MIRO_CLIENT_SECRET",
    redirect_uri_env="MIRO_REDIRECT_URI",
    credential_type="miro_oauth",
    token_auth="body",
    rotates_refresh_tokens=True,
    token_fields=("team_id", "user_id"),
)

refresh_access_token = OAUTH_PROVIDER.refresh


async def get_token_context(access_token: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(CONTEXT_URL, headers={"Authorization": f"Bearer {access_token}"})
    if response.is_error:
        raise ValueError(f"Miro token context failed ({response.status_code})")
    return response.json()
