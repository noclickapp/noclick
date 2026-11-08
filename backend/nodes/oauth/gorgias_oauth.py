"""Tenant-scoped Gorgias OAuth.

Authorize, exchange, refresh and account identity:
https://developers.gorgias.com/docs/set-up-oauth2-app-store
"""
from nodes.core.oauth_provider import OAuthContextField, OAuthProviderSpec
from nodes.scopes.gorgias import GORGIAS_SCOPES


class GorgiasOAuthProviderSpec(OAuthProviderSpec):
    def parse_tokens(self, response, *, context=None):
        # Gorgias documents a 24-hour lifetime even when expires_in is zero.
        tokens, payload = super().parse_tokens(response, context=context)
        if payload.get("expires_in") == 0:
            from datetime import datetime, timedelta, timezone
            tokens.expires_at = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
        return tokens, payload


OAUTH_PROVIDER = GorgiasOAuthProviderSpec(
    provider="gorgias",
    authorize_url="https://{subdomain}/oauth/authorize",
    token_url="https://{subdomain}/oauth/token",
    identity_url="https://{subdomain}/api/account",
    name_field="domain",
    scope_registry=GORGIAS_SCOPES,
    client_id_env="GORGIAS_CLIENT_ID",
    client_secret_env="GORGIAS_CLIENT_SECRET",
    redirect_uri_env="GORGIAS_REDIRECT_URI",
    credential_type="gorgias_oauth",
    token_auth="basic",
    context_fields={
        "subdomain": OAuthContextField(
            source="input", kind="host", label="Gorgias account host (acme.gorgias.com)",
            pattern=r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.gorgias\.com",
        ),
    },
)
