"""Keap confidential OAuth app using the shared authorization-code flow.

Authorize/token: https://developer.infusionsoft.com/authentication/
Identity: https://github.com/infusionsoft/keap-sdk-php/blob/66039324bec4af130eb676a58702272e939e4519/docs/Api/UsersApi.md#getuserinfo
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.keap import KEAP_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="keap",
    authorize_url="https://accounts.infusionsoft.com/app/oauth/authorize",
    token_url="https://api.infusionsoft.com/token",
    identity_url="https://api.keap.com/crm/rest/v2/oauth/connect/userinfo",
    name_field="email",
    scope_registry=KEAP_SCOPES,
    client_id_env="KEAP_CLIENT_ID",
    client_secret_env="KEAP_CLIENT_SECRET",
    redirect_uri_env="KEAP_REDIRECT_URI",
    credential_type="keap_oauth",
    token_auth="basic",
    rotates_refresh_tokens=True,
)

refresh_access_token = OAUTH_PROVIDER.refresh
