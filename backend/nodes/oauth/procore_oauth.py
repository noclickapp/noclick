"""Procore authorization, token exchange, identity and rotating refresh.

All endpoints: https://developers.procore.com/documentation/content/oauth-installed-apps
App registration: https://developers.procore.com/developer_apps
"""
import os
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.procore import PROCORE_SCOPES


class ProcoreOAuthProviderSpec(OAuthProviderSpec):
    async def refresh(self, refresh_token: str, *, context=None):
        # Procore documents the registered redirect_uri on refresh as well.
        tokens, _ = await self._tokens({
            "grant_type": "refresh_token", "refresh_token": refresh_token,
            "redirect_uri": os.environ[self.redirect_uri_env],
        })
        return tokens


OAUTH_PROVIDER = ProcoreOAuthProviderSpec(
    provider="procore",
    authorize_url="https://login.procore.com/oauth/authorize",
    token_url="https://login.procore.com/oauth/token",
    identity_url="https://api.procore.com/rest/v1.0/me",
    name_field="login",
    scope_registry=PROCORE_SCOPES,
    client_id_env="PROCORE_CLIENT_ID",
    client_secret_env="PROCORE_CLIENT_SECRET",
    redirect_uri_env="PROCORE_REDIRECT_URI",
    credential_type="procore_oauth",
    token_auth="body",
    rotates_refresh_tokens=True,
)
refresh_access_token = OAUTH_PROVIDER.refresh
