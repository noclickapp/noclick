"""Todoist OAuth: https://developer.todoist.com/api/v1/#tag/OAuth.

User identity: https://developer.todoist.com/api/v1/#tag/User/Get-User.
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.todoist import TODOIST_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="todoist",
    authorize_url="https://app.todoist.com/oauth/authorize",
    token_url="https://api.todoist.com/oauth/access_token",
    identity_url="https://api.todoist.com/api/v1/user",
    name_field="full_name",
    scope_registry=TODOIST_SCOPES,
    scope_separator=",",
    rotates_refresh_tokens=True,
    client_id_env="TODOIST_CLIENT_ID",
    client_secret_env="TODOIST_CLIENT_SECRET",
    redirect_uri_env="TODOIST_REDIRECT_URI",
    credential_type="todoist_oauth",
)

refresh_access_token = OAUTH_PROVIDER.refresh
