"""Bookeo OAuth2 connection details: https://www.bookeo.com/api/setup/.

The developer console shows the authorization and token endpoints after the
application selects OAuth2. Business identity is documented on the same page.
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.bookeo import BOOKEO_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="bookeo",
    authorize_url="https://oauth.bookeo.com/o2/authorize",
    token_url="https://oauth.bookeo.com/o2/token",
    identity_url="https://api.bookeo.com/v2/settings/business",
    name_field="name",
    scope_registry=BOOKEO_SCOPES,
    credential_type="bookeo_oauth",
    client_id_env="BOOKEO_CLIENT_ID",
    client_secret_env="BOOKEO_CLIENT_SECRET",
    redirect_uri_env="BOOKEO_REDIRECT_URI",
    pkce=True,
    token_auth="basic",
)
refresh_access_token = OAUTH_PROVIDER.refresh
