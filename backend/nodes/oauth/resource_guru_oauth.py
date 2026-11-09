"""Resource Guru standard authorization-code OAuth and rotating token refresh.

Authorize/token/identity: https://resourceguruapp.com/docs/api#section/Authentication
Identity endpoint: https://resourceguruapp.com/docs/api#tag/user/paths/~1v1~1me/get
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.resource_guru import RESOURCE_GURU_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="resource-guru",
    authorize_url="https://api.resourceguruapp.com/oauth/authorize",
    token_url="https://api.resourceguruapp.com/oauth/token",
    identity_url="https://api.resourceguruapp.com/v1/me",
    name_field="email",
    scope_registry=RESOURCE_GURU_SCOPES,
    client_id_env="RESOURCE_GURU_CLIENT_ID",
    client_secret_env="RESOURCE_GURU_CLIENT_SECRET",
    redirect_uri_env="RESOURCE_GURU_REDIRECT_URI",
    credential_type="resource_guru_oauth",
    token_auth="body",
    rotates_refresh_tokens=True,
)
refresh_access_token = OAUTH_PROVIDER.refresh
