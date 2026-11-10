"""Standard Zoho Inventory OAuth with validated regional endpoints.

Authorize/token: https://www.zoho.com/inventory/api/v1/oauth/
Identity: https://www.zoho.com/accounts/protocol/oauth/use-access-token.html
Identity schema/scopes: https://docs.catalyst.zoho.com/en/zest/help/zest-specification-file/authentication-schema/oauth2/
"""
from urllib.parse import urlparse
from nodes.core.oauth_provider import OAuthContextField, OAuthProviderSpec
from nodes.scopes.zoho_inventory import ZOHO_INVENTORY_SCOPES

ACCOUNT_ORIGINS = (
    "https://accounts.zoho.com", "https://accounts.zoho.eu", "https://accounts.zoho.in",
    "https://accounts.zoho.com.au", "https://accounts.zoho.jp", "https://accounts.zoho.sa",
    "https://accounts.zohocloud.ca", "https://accounts.zoho.com.cn",
)

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


def validate_api_domain(value: str) -> str:
    return _validated_origin(value, API_HOSTS)


OAUTH_PROVIDER = OAuthProviderSpec(
    provider="zoho_inventory",
    authorize_url="{accounts}/oauth/v2/auth",
    token_url="{accounts_server}/oauth/v2/token",
    refresh_url="{accounts_server}/oauth/v2/token",
    identity_url="{accounts_server}/oauth/user/info",
    name_field="Display_Name",
    scope_registry=ZOHO_INVENTORY_SCOPES,
    client_id_env="ZOHO_INVENTORY_CLIENT_ID",
    client_secret_env="ZOHO_INVENTORY_CLIENT_SECRET",
    redirect_uri_env="ZOHO_INVENTORY_REDIRECT_URI",
    credential_type="zoho_inventory_oauth",
    authorize_params={"access_type": "offline", "prompt": "consent"},
    scope_separator=",",
    context_fields={
        "accounts": OAuthContextField(source="input", kind="origin", label="Data Center",
                                      choices=ACCOUNT_ORIGINS),
        "accounts_server": OAuthContextField(source="callback", callback_name="accounts-server",
                                             kind="origin", choices=ACCOUNT_ORIGINS),
        "api_domain": OAuthContextField(source="token", kind="origin",
                                       choices=tuple("https://" + host for host in sorted(API_HOSTS))),
    },
)
refresh_access_token = OAUTH_PROVIDER.refresh
