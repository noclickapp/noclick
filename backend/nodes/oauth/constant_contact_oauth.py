"""Constant Contact OAuth declaration.

Authorize/token: https://developer.constantcontact.com/api_guide/server_flow.html
Identity: https://v3.developer.constantcontact.com/api_guide/account-services/account-get-details
Refresh: https://developer.constantcontact.com/api_guide/server_flow.html
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.constant_contact import CONSTANT_CONTACT_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="constant_contact",
    authorize_url="https://authz.constantcontact.com/oauth2/default/v1/authorize",
    token_url="https://authz.constantcontact.com/oauth2/default/v1/token",
    identity_url="https://api.cc.email/v3/account/summary",
    name_field="organization_name",
    scope_registry=CONSTANT_CONTACT_SCOPES,
    client_id_env="CONSTANT_CONTACT_CLIENT_ID",
    client_secret_env="CONSTANT_CONTACT_CLIENT_SECRET",
    redirect_uri_env="CONSTANT_CONTACT_REDIRECT_URI",
    credential_type="constant_contact_oauth",
    token_auth="basic",
    rotates_refresh_tokens=True,
)

refresh_access_token = OAUTH_PROVIDER.refresh
