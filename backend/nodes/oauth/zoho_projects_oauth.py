"""Declarative Zoho Projects regional OAuth.

Authorize/token: https://www.zoho.com/developer/oauth/web-server-apps/get-authorization-code.html
Token: https://www.zoho.com/developer/oauth/web-server-apps/get-access-token.html
Identity/Bearer: https://www.zoho.com/accounts/protocol/oauth/use-access-token.html
Identity Email field: https://github.com/zohodesk-developers/ZohoDeskOAuth/blob/master/src/com/zoho/oauth/client/ZohoOAuthClient.java
Regions: https://projects.zoho.com/api-docs
"""
from nodes.core.oauth_provider import OAuthContextField, OAuthProviderSpec
from nodes.scopes.zoho_projects import ZOHO_PROJECTS_SCOPES

DC_HOSTS = {
    "us": ("accounts.zoho.com", "projects.zoho.com"),
    "eu": ("accounts.zoho.eu", "projects.zoho.eu"),
    "in": ("accounts.zoho.in", "projects.zoho.in"),
    "au": ("accounts.zoho.com.au", "projects.zoho.com.au"),
    "jp": ("accounts.zoho.jp", "projects.zoho.jp"),
    "ca": ("accounts.zohocloud.ca", "projects.zohocloud.ca"),
    "cn": ("accounts.zoho.com.cn", "projects.zoho.com.cn"),
    "sa": ("accounts.zoho.sa", "projects.zoho.sa"),
    "uk": ("accounts.zoho.uk", "projects.zoho.uk"),
    "ae": ("accounts.zoho.ae", "projects.zoho.ae"),
    "sg": ("accounts.zoho.sg", "projects.zoho.sg"),
}


def hosts_for(location: str, accounts_server: str | None = None) -> tuple[str, str]:
    if not isinstance(location, str):
        raise ValueError("Unsupported Zoho data center")
    loc = location.lower().strip()
    if loc not in DC_HOSTS:
        raise ValueError("Unsupported Zoho data center")
    accounts, projects = DC_HOSTS[loc]
    if accounts_server is not None and (
        not isinstance(accounts_server, str)
        or accounts_server.rstrip("/") != f"https://{accounts}"
    ):
        raise ValueError("Zoho data center and accounts server do not match")
    return f"https://{accounts}", f"https://{projects}"


ACCOUNTS_ORIGINS = tuple("https://" + hosts[0] for hosts in DC_HOSTS.values())

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="zoho_projects",
    authorize_url="{accounts}/oauth/v2/auth",
    token_url="{accounts_server}/oauth/v2/token",
    refresh_url="{accounts_server}/oauth/v2/token",
    identity_url="{accounts_server}/oauth/user/info",
    name_field="Email",
    scope_registry=ZOHO_PROJECTS_SCOPES,
    client_id_env="ZOHO_PROJECTS_CLIENT_ID",
    client_secret_env="ZOHO_PROJECTS_CLIENT_SECRET",
    redirect_uri_env="ZOHO_PROJECTS_REDIRECT_URI",
    credential_type="zoho_projects_oauth",
    scope_separator=",",
    authorize_params={"access_type": "offline", "prompt": "consent"},
    context_fields={
        "accounts": OAuthContextField(source="input", kind="origin",
            label="Zoho accounts data center", choices=ACCOUNTS_ORIGINS),
        "accounts_server": OAuthContextField(source="callback", kind="origin",
            callback_name="accounts-server", choices=ACCOUNTS_ORIGINS),
        "location": OAuthContextField(source="callback", choices=tuple(DC_HOSTS)),
    },
)
