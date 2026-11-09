"""Tenant-bound Scoro authorization-code flow with PKCE and rotating refresh.

Authorize/token/identity/header contract:
https://api.scoro.com/api/v4/reference/openapi
App registration: https://developers.scoro.com/login
"""
from nodes.core.oauth_provider import OAuthContextField, OAuthProviderSpec, read_field
from nodes.scopes.scoro import SCORO_SCOPES

SITE_HOST = OAuthContextField(
    source="input",
    kind="host",
    label="Scoro site host (acme.scoro.com)",
    pattern=r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.scoro\.com",
)
COMPANY_ACCOUNT = OAuthContextField(
    source="input",
    label="Company account ID (Settings > Integrations > API)",
    pattern=r"[A-Za-z0-9_-]{1,128}",
)


class ScoroOAuthProviderSpec(OAuthProviderSpec):
    """Scoro's identity request must also select the user's company account."""

    async def account_name(self, access_token, *, context=None):
        context = self.validate_context(context)
        async with self._client(self.identity_url) as client:
            response = await client.get(
                self.endpoint(self.identity_url, context),
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Scoro-Company-Account": context["company_account_id"],
                    "Accept": "application/json",
                },
            )
        response.raise_for_status()
        name = read_field(response.json(), self.name_field)
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Scoro returned no account name")
        return name


OAUTH_PROVIDER = ScoroOAuthProviderSpec(
    provider="scoro",
    authorize_url="https://{site_host}/auth/oauth/authorize",
    token_url="https://{site_host}/auth/oauth/token",
    identity_url="https://{site_host}/api/v4/users/me",
    name_field="firstName",
    scope_registry=SCORO_SCOPES,
    client_id_env="SCORO_CLIENT_ID",
    client_secret_env="SCORO_CLIENT_SECRET",
    redirect_uri_env="SCORO_REDIRECT_URI",
    credential_type="scoro_oauth",
    pkce=True,
    token_auth="body",
    rotates_refresh_tokens=True,
    context_fields={"site_host": SITE_HOST, "company_account_id": COMPANY_ACCOUNT},
)
