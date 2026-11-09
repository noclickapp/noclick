"""Bitly OAuth web flow: non-expiring tokens, no refresh tokens.
Authorize/token: https://dev.bitly.com/docs/getting-started/authentication/
Identity (GET /user): https://dev.bitly.com/v4/v4.json
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.bitly import BITLY_SCOPES


OAUTH_PROVIDER = OAuthProviderSpec(
    provider="bitly", authorize_url="https://bitly.com/oauth/authorize",
    token_url="https://api-ssl.bitly.com/oauth/access_token",
    identity_url="https://api-ssl.bitly.com/v4/user", name_field="login",
    scope_registry=BITLY_SCOPES, client_id_env="BITLY_CLIENT_ID",
    client_secret_env="BITLY_CLIENT_SECRET", redirect_uri_env="BITLY_REDIRECT_URI",
    credential_type="bitly_oauth", token_auth="body",
)
