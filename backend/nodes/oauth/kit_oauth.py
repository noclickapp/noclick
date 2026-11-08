"""Kit OAuth declaration and its documented JSON token transport.

Authorize/token: https://developers.kit.com/api-reference/oauth-refresh-token-flow
Identity: https://developers.kit.com/api-reference/accounts/get-current-account
"""
import os

from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.kit import KIT_SCOPES


class KitOAuthProviderSpec(OAuthProviderSpec):
    def token_request(self, grant: dict[str, str]) -> dict:
        # Kit documents JSON token requests, and only requires the client secret
        # for code exchange, not for single-use refresh-token rotation.
        payload = {**grant, "client_id": os.environ[self.client_id_env]}
        if grant["grant_type"] == "authorization_code":
            payload["client_secret"] = os.environ[self.client_secret_env]
        return {
            "url": self.token_url,
            "json": payload,
            "headers": {"Accept": "application/json"},
        }


OAUTH_PROVIDER = KitOAuthProviderSpec(
    provider="kit",
    authorize_url="https://api.kit.com/v4/oauth/authorize",
    token_url="https://api.kit.com/v4/oauth/token",
    identity_url="https://api.kit.com/v4/account",
    name_field="account.name",
    scope_registry=KIT_SCOPES,
    client_id_env="KIT_CLIENT_ID",
    client_secret_env="KIT_CLIENT_SECRET",
    redirect_uri_env="KIT_REDIRECT_URI",
    credential_type="kit_oauth",
    rotates_refresh_tokens=True,
)

refresh_access_token = OAUTH_PROVIDER.refresh
