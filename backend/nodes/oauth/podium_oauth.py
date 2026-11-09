"""Podium authorization-code flow, with JSON token requests.

Authorize/token/refresh: https://docs.podium.com/docs/oauth
Identity (account's accessible locations): https://docs.podium.com/reference/locationindex-1
App registration: https://developer.podium.com/
"""
from datetime import datetime, timedelta, timezone

from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.podium import PODIUM_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="podium",
    authorize_url="https://api.podium.com/oauth/authorize",
    token_url="https://api.podium.com/oauth/token",
    identity_url="https://api.podium.com/v4/locations",
    name_field="data.0.displayName",
    scope_registry=PODIUM_SCOPES,
    client_id_env="PODIUM_CLIENT_ID",
    client_secret_env="PODIUM_CLIENT_SECRET",
    redirect_uri_env="PODIUM_REDIRECT_URI",
    credential_type="podium_oauth",
    token_format="json",
)


async def refresh_access_token(refresh_token, **kwargs):
    token = await OAUTH_PROVIDER.refresh(refresh_token, **kwargs)
    # Podium documents a ten-hour lifetime but its published token example
    # omits expires_in. Retain a provider-supplied expiry when one is present.
    if token.expires_at is None:
        token.expires_at = (
            datetime.now(timezone.utc) + timedelta(hours=10)
        ).isoformat()
    return token


def is_token_expired(expires_at):
    # Tokens without expires_in need a first refresh to establish the documented
    # lifetime. The shared seam persists that expiry for subsequent calls.
    from nodes.core.oauth_refresh import is_token_expired as shared_expired

    return not expires_at or shared_expired(expires_at)
