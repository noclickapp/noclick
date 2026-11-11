"""Trakt PKCE OAuth with the API headers required on account identity reads.
Authorize/token: https://developer.trakt.tv/docs/pkce
Identity: https://developer.trakt.tv/?section=reference&operation=getUsersSettings
Headers: https://developer.trakt.tv/docs/required-headers
"""
import os
from nodes.core.oauth_provider import OAuthProviderSpec, read_field
from nodes.scopes.trakt import TRAKT_SCOPES


class TraktOAuthProviderSpec(OAuthProviderSpec):
    def token_request(self, grant, *, context=None):
        request = super().token_request(grant, context=context)
        request["headers"].update(
            {"trakt-api-key": os.environ[self.client_id_env], "trakt-api-version": "2"}
        )
        if grant.get("grant_type") == "refresh_token":
            request["json"]["redirect_uri"] = os.environ[self.redirect_uri_env]
        return request

    async def account_name(self, access_token, *, context=None):
        async with self._client(self.identity_url) as client:
            response = await client.get(
                self.identity_url,
                headers={
                    "Authorization": "Bearer " + access_token,
                    "trakt-api-key": os.environ[self.client_id_env],
                    "trakt-api-version": "2",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "User-Agent": "NoClick/1.0",
                },
            )
        response.raise_for_status()
        name = read_field(response.json(), self.name_field)
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Trakt returned no account username")
        return name


OAUTH_PROVIDER = TraktOAuthProviderSpec(
    provider="trakt",
    authorize_url="https://auth.trakt.tv/oauth/authorize",
    token_url="https://auth.trakt.tv/oauth/token",
    identity_url="https://api.trakt.tv/users/settings",
    name_field="user.username",
    scope_registry=TRAKT_SCOPES,
    client_id_env="TRAKT_CLIENT_ID",
    client_secret_env="TRAKT_CLIENT_SECRET",
    redirect_uri_env="TRAKT_REDIRECT_URI",
    credential_type="trakt_oauth",
    pkce=True,
    token_auth="none",
    token_format="json",
    rotates_refresh_tokens=True,
)
refresh_access_token = OAUTH_PROVIDER.refresh
