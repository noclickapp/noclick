"""Cvent EA authorization code, token and account-user identity endpoints.

Contract for all three endpoints:
https://raw.githubusercontent.com/cvent/rest-sdks/main/cvent-public-spec/openapi.yaml
Portal and setup: https://developers.cvent.com/docs/rest-api/tutorials/developer-quickstart
The identity label is an account user's email, not an assertion of current-user identity.
"""
import os
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.cvent import CVENT_SCOPES


class CventOAuthProviderSpec(OAuthProviderSpec):
    def token_request(self, grant, *, context=None):
        # Cvent requires client_id in the form even with HTTP Basic authentication.
        request = super().token_request(grant, context=context)
        request["data"]["client_id"] = os.environ[self.client_id_env]
        return request


OAUTH_PROVIDER = CventOAuthProviderSpec(
    provider="cvent",
    authorize_url="https://api-platform.cvent.com/ea/oauth2/authorize",
    token_url="https://api-platform.cvent.com/ea/oauth2/token",
    identity_url="https://api-platform.cvent.com/ea/users?limit=1",
    name_field="data.0.contact.email",
    scope_registry=CVENT_SCOPES,
    client_id_env="CVENT_CLIENT_ID",
    client_secret_env="CVENT_CLIENT_SECRET",
    redirect_uri_env="CVENT_REDIRECT_URI",
    credential_type="cvent_oauth",
    token_auth="basic",
)
refresh_access_token = OAUTH_PROVIDER.refresh
