"""CINC OAuth2. App registration is by contacting CINC's integrations team.

Authorize: https://public.cincapi.com/v2/docs/#cinc-obtain-users-consent
Token: https://public.cincapi.com/v2/docs/#cinc-obtain-an-access-token
Identity: https://public.cincapi.com/v2/docs/#get-site-me
Registration: https://public.cincapi.com/v2/docs/#cinc-developer-sign-up
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.cinc import CINC_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="cinc",
    authorize_url="https://authv2.cincapi.com/integrator/authorize",
    token_url="https://authv2.cincapi.com/integrator/token",
    identity_url="https://public.cincapi.com/v2/site/me",
    name_field="body.username",
    scope_registry=CINC_SCOPES,
    client_id_env="CINC_CLIENT_ID",
    client_secret_env="CINC_CLIENT_SECRET",
    redirect_uri_env="CINC_REDIRECT_URI",
    credential_type="cinc_oauth",
    token_auth="body",
    pkce=False,
    rotates_refresh_tokens=False,
)
refresh_access_token = OAUTH_PROVIDER.refresh
