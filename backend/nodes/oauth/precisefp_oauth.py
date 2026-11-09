"""PreciseFP authorization-code sign-in and shared refresh declaration.

The provider registers client applications on request; no credentials are embedded.
Authorize/token: https://app.precisefp.com/docs/api/#authentication
Identity: https://app.precisefp.com/docs/api/#operation--user-get
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.precisefp import PRECISEFP_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="precisefp",
    authorize_url="https://four.precisefp.com/oauth/authorize",
    token_url="https://four.precisefp.com/oauth/token",
    identity_url="https://four.precisefp.com/api/user",
    name_field="email",
    scope_registry=PRECISEFP_SCOPES,
    client_id_env="PRECISEFP_CLIENT_ID",
    client_secret_env="PRECISEFP_CLIENT_SECRET",
    redirect_uri_env="PRECISEFP_REDIRECT_URI",
    credential_type="precisefp_oauth",
    token_auth="body",
)
refresh_access_token = OAUTH_PROVIDER.refresh
