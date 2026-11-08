"""Gong account OAuth with its token-selected customer API origin.

Authorization, token endpoint and customer host:
https://help.gong.io/docs/create-an-app-for-gong
Identity response and workspace name:
https://help.gong.io/apidocs/list-all-company-workspaces-v2workspaces
"""
from nodes.core.oauth_provider import OAuthContextField, OAuthProviderSpec
from nodes.scopes.gong import GONG_SCOPES

CUSTOMER_ORIGIN = OAuthContextField(
    source="token", kind="origin",
    pattern=r"https://[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.api\.gong\.io",
)

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="gong",
    authorize_url="https://app.gong.io/oauth2/authorize",
    token_url="https://app.gong.io/oauth2/generate-customer-token",
    identity_url="{api_base_url_for_customer}/v2/workspaces",
    name_field="workspaces.0.name",
    scope_registry=GONG_SCOPES,
    client_id_env="GONG_CLIENT_ID",
    client_secret_env="GONG_CLIENT_SECRET",
    redirect_uri_env="GONG_REDIRECT_URI",
    credential_type="gong_oauth",
    token_auth="basic",
    context_fields={"api_base_url_for_customer": CUSTOMER_ORIGIN},
)


def validate_api_base_url(value: str) -> str:
    """Apply the same customer-origin contract to OAuth and access-key calls."""
    try:
        return CUSTOMER_ORIGIN.validate(value)
    except ValueError as exc:
        raise ValueError("Gong API URL must be an HTTPS *.api.gong.io origin") from exc
