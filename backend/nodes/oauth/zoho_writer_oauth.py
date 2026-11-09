"""Zoho Writer OAuth for the US data centre.
Authorize: https://www.zoho.com/accounts/protocol/oauth/web-apps/authorization.html
Token: https://www.zoho.com/accounts/protocol/oauth/web-apps/access-token.html
Identity: https://www.zoho.com/workdrive/developer/docs/api/v1/get-user-info.html
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.zoho_writer import ZOHO_WRITER_SCOPES
OAUTH_PROVIDER = OAuthProviderSpec(
    provider="zoho_writer", authorize_url="https://accounts.zoho.com/oauth/v2/auth",
    token_url="https://accounts.zoho.com/oauth/v2/token",
    identity_url="https://www.zohoapis.com/workdrive/api/v1/users/me",
    name_field="data.attributes.display_name", scope_registry=ZOHO_WRITER_SCOPES,
    client_id_env="ZOHO_WRITER_CLIENT_ID", client_secret_env="ZOHO_WRITER_CLIENT_SECRET",
    redirect_uri_env="ZOHO_WRITER_REDIRECT_URI", credential_type="zoho_writer_oauth",
    scope_separator=",", authorize_params={"access_type": "offline", "prompt": "consent"},
)
