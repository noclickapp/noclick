"""Spiro OAuth, using its published discovery and REST authentication contract.

Authorize: https://engine.spiro.ai/.well-known/oauth-authorization-server
JSON token requests and rotation: https://support.spiro.ai/article/76-using-spiros-api
Organization users: https://developers.spiro.ai/#tag/Users
"""
from nodes.core.oauth_provider import OAuthProviderSpec, read_field
from nodes.scopes.spiro import SPIRO_SCOPES
from utils.ssrf import guarded_async_client


class _SpiroProvider(OAuthProviderSpec):
    async def account_name(self, access_token, *, context=None):
        # The REST token spans the organization. This is a recognizable member,
        # not a claim that the first listed member is the authorizing person.
        async with guarded_async_client(
            timeout=30, trust_env=False, follow_redirects=False
        ) as client:
            response = await client.get(
                self.identity_url,
                headers={
                    "Authorization": "Bearer " + access_token,
                    "Accept": "application/vnd.api+json",
                    "Content-Type": "application/vnd.api+json",
                },
            )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or "errors" in payload or "error" in payload:
            raise ValueError("Spiro did not return organization users")
        name = read_field(payload, self.name_field)
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Spiro did not return a recognizable organization member")
        return "Spiro organization · " + name


OAUTH_PROVIDER = _SpiroProvider(
    provider="spiro",
    authorize_url="https://engine.spiro.ai/oauth/authorize",
    token_url="https://engine.spiro.ai/oauth/token",
    identity_url="https://api.spiro.ai/api/v1/users?page[number]=1&page[size]=1",
    name_field="data.0.attributes.email",
    scope_registry=SPIRO_SCOPES,
    client_id_env="SPIRO_CLIENT_ID",
    client_secret_env="SPIRO_CLIENT_SECRET",
    redirect_uri_env="SPIRO_REDIRECT_URI",
    credential_type="spiro_oauth",
    pkce=True,
    token_auth="body",
    token_format="json",
    rotates_refresh_tokens=True,
)
refresh_access_token = OAUTH_PROVIDER.refresh
