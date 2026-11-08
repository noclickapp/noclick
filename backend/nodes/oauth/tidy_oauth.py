"""TidyHQ authorization-code flow (form body, no named scopes or PKCE).

Authorize/token: https://docs.tidyhq.com/guides/getting-started
Identity: https://docs.tidyhq.com/api/get-contacts-me
Registration: https://dev.tidyhq.com/oauth_applications
Tidy documents expires_in=null and refresh_token=null, so refresh is optional.
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.tidy import TIDY_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="tidy",
    authorize_url="https://accounts.tidyhq.com/oauth/authorize",
    token_url="https://accounts.tidyhq.com/oauth/token",
    identity_url="https://api.tidyhq.com/v2/contacts/me",
    name_field="full_name",
    scope_registry=TIDY_SCOPES,
    client_id_env="TIDY_CLIENT_ID",
    client_secret_env="TIDY_CLIENT_SECRET",
    redirect_uri_env="TIDY_REDIRECT_URI",
    credential_type="tidy_oauth",
    token_auth="body",
)

refresh_access_token = OAUTH_PROVIDER.refresh
