"""Teamwork permanent bearer tokens via its documented JSON app login flow.

Authorize, token and identity contracts:
https://apidocs.teamwork.com/guides/teamwork/app-login-flow
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.teamwork import TEAMWORK_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="teamwork",
    authorize_url="https://www.teamwork.com/launchpad/login/",
    token_url="https://www.teamwork.com/launchpad/v1/token.json",
    identity_url="https://www.teamwork.com/launchpad/v1/userinfo.json",
    name_field="email",
    scope_registry=TEAMWORK_SCOPES,
    client_id_env="TEAMWORK_CLIENT_ID",
    client_secret_env="TEAMWORK_CLIENT_SECRET",
    redirect_uri_env="TEAMWORK_REDIRECT_URI",
    credential_type="teamwork_oauth",
    token_format="json",
    token_grant_fields={"authorization_code": ("code", "redirect_uri")},
    token_fields=("installation",),
)
