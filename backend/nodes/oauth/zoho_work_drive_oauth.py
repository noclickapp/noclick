"""Regional Zoho WorkDrive authorization-code OAuth.

Authorize: https://www.zoho.com/accounts/protocol/oauth/web-apps/authorization.html
Token: https://www.zoho.com/accounts/protocol/oauth/web-apps/access-token.html
Identity: https://www.zoho.com/workdrive/developer/docs/api/v1/get-user-info.html
Regions: https://www.zoho.com/workdrive/developer/docs/api/v1/getting-started-multi-dc-support.html
"""
from nodes.core.oauth_provider import OAuthContextField, OAuthProviderSpec
from nodes.scopes.zoho_work_drive import ZOHO_WORK_DRIVE_SCOPES

REGIONS = {
    "com": "com", "eu": "eu", "in": "in", "com.au": "com.au",
    "com.cn": "com.cn", "jp": "jp", "ae": "ae", "zohocloud.ca": "ca", "sa": "sa",
}
ACCOUNTS_ORIGINS = tuple(
    "https://accounts." + (region if region == "zohocloud.ca" else "zoho." + region)
    for region in REGIONS
)
API_ORIGINS = tuple("https://www.zohoapis." + region for region in REGIONS.values())


def validate_api_domain(value: str) -> str:
    if not isinstance(value, str) or value not in API_ORIGINS:
        raise ValueError("Use a documented Zoho WorkDrive regional API origin")
    return value


OAUTH_PROVIDER = OAuthProviderSpec(
    provider="zoho_work_drive",
    authorize_url="https://accounts.zoho.com/oauth/v2/auth",
    token_url="{accounts_server}/oauth/v2/token",
    refresh_url="{accounts_server}/oauth/v2/token",
    identity_url="{api_domain}/workdrive/api/v1/users/me",
    name_field="data.attributes.display_name",
    scope_registry=ZOHO_WORK_DRIVE_SCOPES,
    client_id_env="ZOHO_WORK_DRIVE_CLIENT_ID",
    client_secret_env="ZOHO_WORK_DRIVE_CLIENT_SECRET",
    redirect_uri_env="ZOHO_WORK_DRIVE_REDIRECT_URI",
    credential_type="zoho_work_drive_oauth",
    scope_separator=",",
    authorize_params={"access_type": "offline", "prompt": "consent"},
    context_fields={
        "accounts_server": OAuthContextField(
            source="callback", callback_name="accounts-server", kind="origin",
            choices=ACCOUNTS_ORIGINS,
        ),
        "api_domain": OAuthContextField(source="token", kind="origin", choices=API_ORIGINS),
    },
)
