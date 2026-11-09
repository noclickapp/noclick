"""SoundCloud OAuth 2.1 with PKCE and single-use refresh tokens.

Authorize, token, refresh and identity endpoints:
https://developers.soundcloud.com/docs/api/guide#authentication
App registration: https://soundcloud.com/you/apps
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.core.credential_fields import clean_secret
from nodes.scopes.soundcloud import SOUNDCLOUD_SCOPES


class SoundcloudOAuthProvider(OAuthProviderSpec):
    async def account_name(self, access_token, *, context=None):
        # SoundCloud requires the OAuth scheme, including on its identity read.
        # Keep that provider-specific difference out of the shared transport.
        self.validate_context(context)
        access_token = clean_secret(access_token, field_name="Access token")
        if any(c.isspace() for c in access_token):
            raise ValueError("Use an access token without whitespace")
        async with self._client(self.identity_url) as client:
            response = await client.get(
                self.identity_url,
                headers={
                    "Authorization": "OAuth " + access_token,
                    "Accept": "application/json; charset=utf-8",
                },
            )
        response.raise_for_status()
        body = response.json()
        name = body.get("username") if isinstance(body, dict) else None
        if not isinstance(name, str) or not name.strip():
            raise ValueError("SoundCloud returned no account name")
        return name


OAUTH_PROVIDER = SoundcloudOAuthProvider(
    provider="soundcloud",
    authorize_url="https://secure.soundcloud.com/authorize",
    token_url="https://secure.soundcloud.com/oauth/token",
    identity_url="https://api.soundcloud.com/me",
    name_field="username",
    scope_registry=SOUNDCLOUD_SCOPES,
    client_id_env="SOUNDCLOUD_CLIENT_ID",
    client_secret_env="SOUNDCLOUD_CLIENT_SECRET",
    redirect_uri_env="SOUNDCLOUD_REDIRECT_URI",
    credential_type="soundcloud_oauth",
    pkce=True,
    token_auth="body",
    rotates_refresh_tokens=True,
)
refresh_access_token = OAUTH_PROVIDER.refresh
