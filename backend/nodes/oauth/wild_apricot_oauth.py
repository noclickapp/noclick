"""Wild Apricot's documented member sign-in, token exchange and account identity.

Authorize/token: https://gethelp.wildapricot.com/en/articles/484-api-authentication
Identity: https://api.wildapricot.org/ui/swagger/publicAccess#/Accounts
App registration: https://gethelp.wildapricot.com/en/articles/180-authorizing-external-applications
"""
import os

from nodes.core.oauth_provider import OAuthContextField, OAuthProviderSpec
from nodes.scopes.wild_apricot import WILD_APRICOT_SCOPES


class WildApricotOAuthProviderSpec(OAuthProviderSpec):
    """The documented code exchange includes client_id beside HTTP Basic auth."""

    def token_request(self, grant, *, context=None):
        request = super().token_request(grant, context=context)
        if grant.get("grant_type") == "authorization_code":
            request["data"]["client_id"] = os.environ[self.client_id_env]
        return request


OAUTH_PROVIDER = WildApricotOAuthProviderSpec(
    provider="wild_apricot",
    authorize_url="https://{organization}/sys/login/OAuthLogin",
    token_url="https://oauth.wildapricot.org/auth/token",
    identity_url="https://api.wildapricot.org/publicview/v1/accounts",
    name_field="0.Name",
    scope_registry=WILD_APRICOT_SCOPES,
    credential_type="wild_apricot_oauth",
    client_id_env="WILD_APRICOT_CLIENT_ID",
    client_secret_env="WILD_APRICOT_CLIENT_SECRET",
    redirect_uri_env="WILD_APRICOT_REDIRECT_URI",
    token_auth="basic",
    token_params={"scope": "auto"},
    context_fields={
        "organization": OAuthContextField(
            source="input", kind="host", label="Organization host",
            pattern=r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.wildapricot\.org",
        ),
    },
)
