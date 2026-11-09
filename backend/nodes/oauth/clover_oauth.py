"""Clover high-trust OAuth using staging's generic context-aware provider.

Authorize/token endpoints: https://docs.clover.com/dev/docs/high-trust-app-auth-flow
Refresh/Unix expiry: https://docs.clover.com/dev/docs/refresh-access-tokens
Identity: https://docs.clover.com/dev/reference/merchantgetmerchant
Production regional domains are documented in the endpoint tables above.
Sandbox merchants can connect with their merchant API token.
"""
from nodes.core.oauth_provider import OAuthContextField, OAuthProviderSpec
from nodes.scopes.clover import CLOVER_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="clover",
    authorize_url="https://www.{clover_domain}/oauth/v2/authorize",
    token_url="https://api.{clover_domain}/oauth/v2/token",
    refresh_url="https://api.{clover_domain}/oauth/v2/refresh",
    identity_url="https://api.{clover_domain}/v3/merchants/{merchant_id}",
    name_field="name",
    scope_registry=CLOVER_SCOPES,
    client_id_env="CLOVER_CLIENT_ID",
    client_secret_env="CLOVER_CLIENT_SECRET",
    redirect_uri_env="CLOVER_REDIRECT_URI",
    credential_type="clover_oauth",
    token_format="json",
    token_auth="body",
    refresh_token_auth="none",
    token_grant_fields={"authorization_code": ("code",), "refresh_token": ("refresh_token",)},
    expires_at_field="access_token_expiration",
    rotates_refresh_tokens=True,
    context_fields={
        "clover_domain": OAuthContextField(source="input", kind="host", label="Clover Region",
            choices=("clover.com", "eu.clover.com", "la.clover.com")),
        "merchant_id": OAuthContextField(source="callback", pattern=r"[A-Za-z0-9_-]+"),
    },
)

refresh_access_token = OAUTH_PROVIDER.refresh
