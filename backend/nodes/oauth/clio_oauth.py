"""Clio US authorization-code flow.
Authorize/token/identity: https://docs.developers.clio.com/api-docs/clio-manage/authorization/
Regional selection from the former bespoke flow is not part of this declaration.
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.clio import CLIO_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="clio",
    authorize_url="https://app.clio.com/oauth/authorize",
    token_url="https://app.clio.com/oauth/token",
    identity_url="https://app.clio.com/api/v4/users/who_am_i.json?fields=id,name",
    name_field="data.name",
    scope_registry=CLIO_SCOPES,
    client_id_env="CLIO_CLIENT_ID",
    client_secret_env="CLIO_CLIENT_SECRET",
    redirect_uri_env="CLIO_REDIRECT_URI",
    credential_type="clio_oauth",
    token_auth="body",
)
refresh_access_token = OAUTH_PROVIDER.refresh
