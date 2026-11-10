"""ezeep's confidential-client authorization-code flow with refresh rotation.
Authorize/token: https://apidocs.ezeep.com/ezeepblue/auth/auth_code_flow/auth_code_flow.html
Identity: https://api2.ezeep.com/printing/v1/schema/ (GET /printing/v1/users/me/)
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.ezeep_printing import EZEEP_PRINTING_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="ezeep-printing",
    authorize_url="https://account.ezeep.com/oauth/authorize/",
    token_url="https://account.ezeep.com/oauth/access_token/",
    identity_url="https://api2.ezeep.com/printing/v1/users/me/",
    name_field="id",
    scope_registry=EZEEP_PRINTING_SCOPES,
    client_id_env="EZEEP_PRINTING_CLIENT_ID",
    client_secret_env="EZEEP_PRINTING_CLIENT_SECRET",
    redirect_uri_env="EZEEP_PRINTING_REDIRECT_URI",
    credential_type="ezeep_printing_oauth",
    token_auth="basic",
    rotates_refresh_tokens=True,
)

refresh_access_token = OAUTH_PROVIDER.refresh
