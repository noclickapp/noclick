"""Qonto's rotating OAuth authorization-code flow for registered webhooks.
The declaration lets the shared sign-in flow connect Qonto without a shared-file edit.

Authorize/token: https://docs.qonto.com/guides/authentication/oauth-flow
Identity: https://docs.qonto.com/api-reference/business-api/organization-accounts/organizations/retrieve-the-authenticated-organization-and-list-bank-accounts
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.qonto import QONTO_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="qonto",
    authorize_url="https://oauth.qonto.com/oauth2/auth",
    token_url="https://oauth.qonto.com/oauth2/token",
    identity_url="https://thirdparty.qonto.com/v2/organization",
    name_field="organization.name",
    scope_registry=QONTO_SCOPES,
    client_id_env="QONTO_CLIENT_ID",
    client_secret_env="QONTO_CLIENT_SECRET",
    redirect_uri_env="QONTO_REDIRECT_URI",
    credential_type="qonto_oauth",
    token_auth="body",
    rotates_refresh_tokens=True,
)

refresh_access_token = OAUTH_PROVIDER.refresh
