"""Egnyte's tenant-specific authorization-code flow.

Authorize, token, refresh, identity and scopes:
https://us-partner-integrations.egnyte.com/integration/cfs/api-docs/authentication
Register an application at https://developers.egnyte.com/.
"""
from nodes.core.oauth_provider import OAuthContextField, OAuthProviderSpec
from nodes.scopes.egnyte import EGNYTE_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="egnyte",
    authorize_url="https://{account_host}/puboauth/token",
    token_url="https://{account_host}/puboauth/token",
    identity_url="https://{account_host}/pubapi/v1/userinfo",
    name_field="username",
    scope_registry=EGNYTE_SCOPES,
    client_id_env="EGNYTE_CLIENT_ID",
    client_secret_env="EGNYTE_CLIENT_SECRET",
    redirect_uri_env="EGNYTE_REDIRECT_URI",
    credential_type="egnyte_oauth",
    token_auth="body",
    rotates_refresh_tokens=True,
    context_fields={
        "account_host": OAuthContextField(
            source="input", kind="host", label="Egnyte account host",
            pattern=r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.egnyte\.com",
        ),
    },
)
