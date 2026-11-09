"""DigitalOcean OAuth2 using staging's generic authorization-code flow.

Authorize/token/refresh: https://docs.digitalocean.com/reference/api/oauth/
Identity: https://docs.digitalocean.com/reference/api/digitalocean/#tag/Account
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.digitalocean import DIGITALOCEAN_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="digitalocean",
    authorize_url="https://cloud.digitalocean.com/v1/oauth/authorize",
    token_url="https://cloud.digitalocean.com/v1/oauth/token",
    identity_url="https://api.digitalocean.com/v2/account",
    name_field="account.email",
    scope_registry=DIGITALOCEAN_SCOPES,
    client_id_env="DIGITALOCEAN_CLIENT_ID",
    client_secret_env="DIGITALOCEAN_CLIENT_SECRET",
    redirect_uri_env="DIGITALOCEAN_REDIRECT_URI",
    credential_type="digitalocean_oauth",
    pkce=True,
    token_auth="body",
    rotates_refresh_tokens=True,
)

refresh_access_token = OAUTH_PROVIDER.refresh
