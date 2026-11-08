"""Zoho CRM regional OAuth, declared without shared routes or hooks.

Protocol: https://www.zoho.com/crm/developer/docs/api/v8/auth-request.html
Tokens/header: https://www.zoho.com/crm/developer/docs/api/v8/access-refresh.html
Identity: https://www.zoho.com/crm/developer/docs/api/v8/get-users.html
"""
from urllib.parse import urlparse

from nodes.core.oauth_provider import OAuthContextField, OAuthProviderSpec, read_field
from nodes.scopes.zoho_crm import ZOHO_CRM_SCOPES

ACCOUNT_HOSTS = {
    "accounts.zoho.com", "accounts.zoho.com.au", "accounts.zoho.eu",
    "accounts.zoho.in", "accounts.zoho.com.cn", "accounts.zoho.jp",
    "accounts.zoho.sa", "accounts.zohocloud.ca",
}
API_HOSTS = {
    "www.zohoapis.com", "www.zohoapis.com.au", "www.zohoapis.eu",
    "www.zohoapis.in", "www.zohoapis.com.cn", "www.zohoapis.jp",
    "www.zohoapis.sa", "www.zohoapis.ca",
}


def _validated_origin(value: str, hosts: set[str]) -> str:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if (parsed.scheme != "https" or host not in hosts or parsed.port
            or parsed.username or parsed.password or parsed.path not in {"", "/"}
            or parsed.query or parsed.fragment):
        raise ValueError("Zoho returned an invalid regional endpoint")
    return f"https://{host}"


def validate_accounts_server(value: str) -> str:
    return _validated_origin(value, ACCOUNT_HOSTS)


def validate_api_domain(value: str) -> str:
    return _validated_origin(value, API_HOSTS)



class ZohoCRMProviderSpec(OAuthProviderSpec):
    """Zoho CRM documents a provider-specific authorization scheme."""

    async def account_name(self, access_token: str, *, context=None) -> str:
        context = self.validate_context(context)
        async with self._client(self.identity_url) as client:
            response = await client.get(
                self.endpoint(self.identity_url, context),
                headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
            )
        response.raise_for_status()
        name = read_field(response.json(), self.name_field)
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Zoho CRM returned no account name")
        return name


OAUTH_PROVIDER = ZohoCRMProviderSpec(
    provider="zoho_crm",
    # Zoho redirects to the user's data centre and returns accounts-server.
    authorize_url="https://accounts.zoho.com/oauth/v2/auth",
    token_url="{accounts_server}/oauth/v2/token",
    refresh_url="{accounts_server}/oauth/v2/token",
    identity_url="{api_domain}/crm/v8/users?type=CurrentUser",
    name_field="users.0.full_name",
    scope_registry=ZOHO_CRM_SCOPES,
    scope_separator=",",
    client_id_env="ZOHO_CRM_CLIENT_ID",
    client_secret_env="ZOHO_CRM_CLIENT_SECRET",
    redirect_uri_env="ZOHO_CRM_REDIRECT_URI",
    credential_type="zoho_crm_oauth",
    authorize_params={"access_type": "offline", "prompt": "consent"},
    context_fields={
        "accounts_server": OAuthContextField(
            source="callback", callback_name="accounts-server", kind="origin",
            choices=tuple(f"https://{host}" for host in sorted(ACCOUNT_HOSTS)),
        ),
        "api_domain": OAuthContextField(
            source="token", kind="origin",
            choices=tuple(f"https://{host}" for host in sorted(API_HOSTS)),
        ),
    },
)
refresh_access_token = OAUTH_PROVIDER.refresh
