"""Newie public-client OAuth with PKCE and rotating refresh tokens.

Endpoints, resource and client registration:
https://api.newie.app/docs/guides/identity.md
https://auth.newie.app/.well-known/openid-configuration
Identity: https://api.newie.app/docs/reference/user.md
Newie does not support client secrets; NEWIE_CLIENT_SECRET is an unused env name
required by the declaration schema. Register a public client with auth method none.
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.newie import NEWIE_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="newie",
    authorize_url="https://auth.newie.app/auth",
    token_url="https://auth.newie.app/token",
    identity_url="https://api.newie.app/v1/users/me",
    name_field="name",
    scope_registry=NEWIE_SCOPES,
    client_id_env="NEWIE_CLIENT_ID",
    client_secret_env="NEWIE_CLIENT_SECRET",
    redirect_uri_env="NEWIE_REDIRECT_URI",
    credential_type="newie_oauth",
    pkce=True,
    token_auth="none",
    rotates_refresh_tokens=True,
    authorize_params={"resource": "https://api.newie.app"},
    token_params={"resource": "https://api.newie.app"},
)

refresh_access_token = OAUTH_PROVIDER.refresh
