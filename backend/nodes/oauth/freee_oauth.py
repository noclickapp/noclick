"""Authorize/token: https://developer.freee.co.jp/reference/認可コード
Rotation: https://developer.freee.co.jp/reference/faq/token_lifetime
Identity: https://developer.freee.co.jp/docs/accounting/reference#/Users/get_users_me
Registration: https://developer.freee.co.jp/startguide/starting-api
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.freee import FREEE_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="freee",
    authorize_url="https://accounts.secure.freee.co.jp/public_api/authorize",
    token_url="https://accounts.secure.freee.co.jp/public_api/token",
    scope_registry=FREEE_SCOPES,
    client_id_env="FREEE_CLIENT_ID", client_secret_env="FREEE_CLIENT_SECRET",
    redirect_uri_env="FREEE_REDIRECT_URI", credential_type="freee_oauth",
    identity_url="https://api.freee.co.jp/api/1/users/me", name_field="user.email",
    pkce=False, token_auth="body", authorize_params={"prompt": "select_company"},
    rotates_refresh_tokens=True,
)
refresh_access_token = OAUTH_PROVIDER.refresh
