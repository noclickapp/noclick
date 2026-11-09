"""Zoho Cliq US authorization-code sign-in through the generic OAuth flow.

Authorize/token: https://www.zoho.com/cliq/help/restapi/v3/oauth/
Identity: https://www.zoho.com/accounts/protocol/oauth/use-access-token.html
Identity fields: https://docs.catalyst.zoho.com/en/zest/help/zest-specification-file/authentication-schema/oauth2/
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.zoho_cliq import ZOHO_CLIQ_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="zoho_cliq",
    authorize_url="https://accounts.zoho.com/oauth/v2/auth",
    token_url="https://accounts.zoho.com/oauth/v2/token",
    identity_url="https://accounts.zoho.com/oauth/user/info",
    name_field="Email",
    scope_registry=ZOHO_CLIQ_SCOPES,
    client_id_env="ZOHO_CLIQ_CLIENT_ID",
    client_secret_env="ZOHO_CLIQ_CLIENT_SECRET",
    redirect_uri_env="ZOHO_CLIQ_REDIRECT_URI",
    credential_type="zoho_cliq_oauth",
    scope_separator=",",
    authorize_params={"access_type": "offline", "prompt": "consent"},
)
