"""Outreach's standard OAuth flow and rotating refresh tokens.

Authorize/token: https://developers.outreach.io/api/oauth
Rotation: https://developers.outreach.io/api/getting-started#token-availability
Organization-user label: https://developers.outreach.io/api/reference/user/paths/~1users/get.md
The first visible user's name labels the connected organization, not the signer.
"""
from nodes.core.oauth_provider import OAuthProviderSpec, read_field
from nodes.scopes.outreach import OUTREACH_SCOPES
from utils.ssrf import guarded_async_client


class OutreachOAuthProviderSpec(OAuthProviderSpec):
    async def account_name(self, access_token, *, context=None):
        # Outreach's JSON:API requires its media type. Like Spiro, label the
        # organization with a visible member rather than claiming /users is /me.
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.get(self.identity_url, headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.api+json",
                "Content-Type": "application/vnd.api+json",
            })
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or "errors" in payload or "error" in payload:
            raise ValueError("Outreach did not return organization users")
        try:
            name = read_field(payload, self.name_field)
        except (KeyError, IndexError, TypeError, ValueError):
            raise ValueError("Outreach did not return an organization member's name") from None
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Outreach did not return an organization member's name")
        return "Outreach organization · " + name.strip()


OAUTH_PROVIDER = OutreachOAuthProviderSpec(
    provider="outreach",
    authorize_url="https://api.outreach.io/oauth/authorize",
    token_url="https://api.outreach.io/oauth/token",
    identity_url="https://api.outreach.io/api/v2/users?page[size]=1",
    name_field="data.0.attributes.name",
    scope_registry=OUTREACH_SCOPES,
    client_id_env="OUTREACH_CLIENT_ID",
    client_secret_env="OUTREACH_CLIENT_SECRET",
    redirect_uri_env="OUTREACH_REDIRECT_URI",
    credential_type="outreach_oauth",
    token_auth="body",
    rotates_refresh_tokens=True,
)
refresh_access_token = OAUTH_PROVIDER.refresh
