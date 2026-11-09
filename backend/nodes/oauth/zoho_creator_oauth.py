"""Zoho Creator regional authorization-code OAuth.

Authorize: https://www.zoho.com/developer/oauth/web-server-apps/get-authorization-code.html
Token: https://www.zoho.com/developer/oauth/web-server-apps/get-access-token.html
Identity: https://www.zoho.com/accounts/protocol/oauth/use-access-token.html
Identity response: https://github.com/zohodesk-developers/ZohoDeskOAuth/blob/master/src/com/zoho/oauth/client/ZohoOAuthClient.java
Regions: https://www.zoho.com/creator/help/api/v2.1/oauth-overview.html
"""
from nodes.core.oauth_provider import OAuthContextField, OAuthProviderSpec
from nodes.scopes.zoho_creator import ZOHO_CREATOR_SCOPES

ACCOUNTS_ORIGINS = tuple("https://accounts." + host for host in (
    "zoho.com", "zoho.eu", "zoho.in", "zoho.com.au", "zoho.jp",
    "zohocloud.ca", "zoho.sa", "zoho.com.cn", "zoho.ae",
))
API_ORIGINS = tuple("https://www.zohoapis." + dc for dc in (
    "com", "eu", "in", "com.au", "jp", "ca", "sa", "com.cn", "ae",
))

# The provider OAS lists bare zohoapis origins; current token responses and docs
# use www. Both sets are provider-published HTTPS origins. Preserve the token value.
API_ORIGINS += tuple(origin.replace("https://www.", "https://") for origin in API_ORIGINS)


def validate_api_domain(value):
    if value not in API_ORIGINS:
        raise ValueError("Use a documented Zoho Creator regional API origin, such as https://www.zohoapis.com")
    return value


def validate_accounts_server(value):
    if value not in ACCOUNTS_ORIGINS:
        raise ValueError("Use a documented Zoho accounts origin, such as https://accounts.zoho.com")
    return value


OAUTH_PROVIDER = OAuthProviderSpec(
    provider="zoho_creator",
    authorize_url="https://accounts.zoho.com/oauth/v2/auth",
    token_url="{accounts_server}/oauth/v2/token",
    refresh_url="{accounts_server}/oauth/v2/token",
    identity_url="{accounts_server}/oauth/user/info",
    name_field="Email",
    scope_registry=ZOHO_CREATOR_SCOPES,
    client_id_env="ZOHO_CREATOR_CLIENT_ID",
    client_secret_env="ZOHO_CREATOR_CLIENT_SECRET",
    redirect_uri_env="ZOHO_CREATOR_REDIRECT_URI",
    credential_type="zoho_creator_oauth",
    scope_separator=",",
    authorize_params={"access_type": "offline", "prompt": "consent"},
    context_fields={
        "accounts_server": OAuthContextField(source="callback", callback_name="accounts-server",
            kind="origin", choices=ACCOUNTS_ORIGINS),
        "api_domain": OAuthContextField(source="token", kind="origin", choices=API_ORIGINS),
    },
)
refresh_access_token = OAUTH_PROVIDER.refresh
