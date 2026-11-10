"""Zoho Books regional authorization-code OAuth.

Endpoints/scopes: https://www.zoho.com/books/api/v3/oauth/
Identity: https://www.zoho.com/accounts/protocol/oauth/use-access-token.html
"""
from nodes.core.oauth_provider import OAuthProviderSpec, OAuthContextField
from nodes.scopes.zoho_books import ZOHO_BOOKS_SCOPES

ACCOUNTS = tuple("https://" + host for host in (
    "accounts.zoho.com", "accounts.zoho.eu", "accounts.zoho.in", "accounts.zoho.com.au",
    "accounts.zoho.com.cn", "accounts.zoho.jp", "accounts.zoho.sa", "accounts.zohocloud.ca"))
APIS = tuple("https://www.zohoapis." + suffix for suffix in ("com", "eu", "in", "com.au", "com.cn", "jp", "sa", "ca"))

def validate_api_domain(value):
    if value not in APIS:
        raise ValueError("Zoho returned an invalid regional endpoint")
    return value

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="zoho_books", credential_type="zoho_books_oauth",
    authorize_url="{accounts}/oauth/v2/auth", token_url="{accounts_server}/oauth/v2/token",
    refresh_url="{accounts_server}/oauth/v2/token",
    identity_url="{accounts_server}/oauth/user/info", name_field="Display_Name",
    scope_registry=ZOHO_BOOKS_SCOPES, scope_separator=",",
    client_id_env="ZOHO_BOOKS_CLIENT_ID", client_secret_env="ZOHO_BOOKS_CLIENT_SECRET",
    redirect_uri_env="ZOHO_BOOKS_REDIRECT_URI", token_auth="body",
    authorize_params={"access_type": "offline", "prompt": "consent"},
    context_fields={
        "accounts": OAuthContextField(source="input", kind="origin", label="Data centre", choices=ACCOUNTS),
        "accounts_server": OAuthContextField(source="callback", callback_name="accounts-server", kind="origin", choices=ACCOUNTS),
        "api_domain": OAuthContextField(source="token", kind="origin", choices=APIS),
    },
)
refresh_access_token = OAUTH_PROVIDER.refresh
