"""Join It OAuth authorization-code flow with permanent Bearer tokens.

Authorize/token URLs and form-encoded exchange example:
https://docs.joinitapi.com/docs/authentication
Identity URL: https://docs.joinitapi.com/reference/get-organizations
Organization name field: https://join-it.github.io/core/#organization-details
Join It registers application keys on request, rather than in a self-service
console. Tokens do not expire and the provider documents no refresh flow.
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.join_it import JOIN_IT_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="join-it",
    authorize_url="https://app.joinit.com/oauth2/authorize",
    token_url="https://app.joinitapi.com/oauth2/token",
    identity_url="https://app.joinitapi.com/api/v1/organizations/me/details",
    name_field="name",
    scope_registry=JOIN_IT_SCOPES,
    client_id_env="JOIN_IT_CLIENT_ID",
    client_secret_env="JOIN_IT_CLIENT_SECRET",
    redirect_uri_env="JOIN_IT_REDIRECT_URI",
    credential_type="join_it_oauth",
    token_auth="body",
)
