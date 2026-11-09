"""MyCase authorization-code OAuth; client registration is through support.

Authorize, token and refresh:
https://stoplight.io/api/v1/projects/mycaseapi/mycase-api-documentation/nodes/docs/Getting-Started.md
Identity: https://stoplight.io/api/v1/projects/mycaseapi/mycase-api-documentation/nodes/reference/Staff.json
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.mycase import MYCASE_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="mycase",
    authorize_url="https://auth.mycase.com/login_sessions/new",
    token_url="https://auth.mycase.com/tokens",
    identity_url="https://external-integrations.mycase.com/v1/me",
    name_field="email",
    scope_registry=MYCASE_SCOPES,
    client_id_env="MYCASE_CLIENT_ID",
    client_secret_env="MYCASE_CLIENT_SECRET",
    redirect_uri_env="MYCASE_REDIRECT_URI",
    credential_type="mycase_oauth",
    token_auth="body",
    token_format="json",
    rotates_refresh_tokens=True,
)
refresh_access_token = OAUTH_PROVIDER.refresh
