"""Kommo's account-specific authorization-code flow.

Authorization and callback referer: https://developers.kommo.com/docs/oauth-20
Token exchange and refresh: https://developers.kommo.com/reference/get-token
Identity: https://developers.kommo.com/reference/account-parameters
"""
import os

from nodes.core.oauth_provider import OAuthContextField, OAuthProviderSpec
from nodes.scopes.kommo import KOMMO_SCOPES


class KommoOAuthProviderSpec(OAuthProviderSpec):
    """Kommo also requires the registered redirect URI on refresh."""

    async def refresh(self, refresh_token: str, *, context=None):
        tokens, _ = await self._tokens(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "redirect_uri": os.environ[self.redirect_uri_env],
            },
            context=context,
        )
        return tokens


OAUTH_PROVIDER = KommoOAuthProviderSpec(
    provider="kommo",
    authorize_url="https://www.kommo.com/oauth",
    authorize_params={"mode": "post_message"},
    token_url="https://{referer}/oauth2/access_token",
    identity_url="https://{referer}/api/v4/account",
    name_field="name",
    scope_registry=KOMMO_SCOPES,
    client_id_env="KOMMO_CLIENT_ID",
    client_secret_env="KOMMO_CLIENT_SECRET",
    redirect_uri_env="KOMMO_REDIRECT_URI",
    credential_type="kommo_oauth",
    token_format="json",
    token_auth="body",
    rotates_refresh_tokens=True,
    context_fields={
        "referer": OAuthContextField(
            source="callback",
            kind="host",
            pattern=r"[a-z0-9-]+\.kommo\.com",
        ),
    },
)
