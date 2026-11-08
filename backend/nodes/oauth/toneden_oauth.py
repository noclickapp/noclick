"""ToneDen authorization, JSON token exchange and identity.

All three endpoints: https://developers.toneden.io/docs/getting-started
Identity response: https://developers.toneden.io/reference/get_users-userid
The documented token response has neither expiry nor a refresh token.
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.toneden import TONEDEN_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="toneden",
    authorize_url="https://www.toneden.io/auth/oauth2/authorize",
    token_url="https://www.toneden.io/auth/oauth2/token",
    identity_url="https://www.toneden.io/api/v1/users/me",
    name_field="user.display_name",
    scope_registry=TONEDEN_SCOPES,
    client_id_env="TONEDEN_CLIENT_ID",
    client_secret_env="TONEDEN_CLIENT_SECRET",
    redirect_uri_env="TONEDEN_REDIRECT_URI",
    credential_type="toneden_oauth",
    token_format="json",
    token_auth="body",
)
