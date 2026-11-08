"""GoTo authorization-code OAuth, with non-mandatory refresh-token rotation.

Authorize/token: https://developer.goto.com/Authentication
Identity: https://developer.goto.com/Scim
Client registration: https://developer.goto.com/guides/Get%20Started/02_HOW_createClient/
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.go_to_training import GO_TO_TRAINING_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="go_to_training",
    authorize_url="https://authentication.logmeininc.com/oauth/authorize",
    token_url="https://authentication.logmeininc.com/oauth/token",
    identity_url="https://api.getgo.com/identity/v1/Users/me",
    name_field="displayName",
    scope_registry=GO_TO_TRAINING_SCOPES,
    client_id_env="GO_TO_TRAINING_CLIENT_ID",
    client_secret_env="GO_TO_TRAINING_CLIENT_SECRET",
    redirect_uri_env="GO_TO_TRAINING_REDIRECT_URI",
    credential_type="go_to_training_oauth",
    token_auth="basic",
    pkce=False,
    rotates_refresh_tokens=False,
)
refresh_access_token = OAUTH_PROVIDER.refresh
