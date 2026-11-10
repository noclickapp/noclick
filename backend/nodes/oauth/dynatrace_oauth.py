"""Dynatrace PKCE OAuth with the provider's published SSO identity endpoint.

Protocol: https://docs.dynatrace.com/docs/manage/identity-access-management/access-tokens-and-oauth-clients/oauth-clients
Identity and claims: https://sso.dynatrace.com/.well-known/openid-configuration
"""
from nodes.core.oauth_provider import OAuthContextField, OAuthProviderSpec
from nodes.scopes.dynatrace import DYNATRACE_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="dynatrace",
    authorize_url="https://sso.dynatrace.com/oauth2/authorize",
    token_url="https://sso.dynatrace.com/sso/oauth2/token",
    identity_url="https://sso.dynatrace.com/sso/oauth2/userinfo",
    name_field="name",
    scope_registry=DYNATRACE_SCOPES,
    client_id_env="DYNATRACE_CLIENT_ID",
    client_secret_env="DYNATRACE_CLIENT_SECRET",
    redirect_uri_env="DYNATRACE_REDIRECT_URI",
    credential_type="dynatrace_oauth",
    pkce=True,
    token_auth="body",
    rotates_refresh_tokens=False,
    context_fields={
        "account_uuid": OAuthContextField(
            source="input", label="Account UUID", pattern=r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}",
        ),
    },
)

refresh_access_token = OAUTH_PROVIDER.refresh
