"""net2phone's authorization-code flow and its documented refresh header.

Authorize/token: https://developer.net2phone.com/api-explorer/v1?articleId=authentication
Identity: https://developer.net2phone.com/api-explorer/v1 (Getting Started).
The refresh header is Bearer base64(client_id:client_secret), not HTTP Basic.
"""
import base64
import os

from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.net2phone import NET2PHONE_SCOPES


class Net2PhoneOAuthProviderSpec(OAuthProviderSpec):
    def token_request(self, grant, *, context=None):
        request = super().token_request(grant, context=context)
        if grant.get("grant_type") == "refresh_token":
            encoded = base64.b64encode(
                f"{os.environ[self.client_id_env]}:{os.environ[self.client_secret_env]}".encode()
            ).decode()
            request["headers"]["Authorization"] = "Bearer " + encoded
            request["json"] = dict(grant)
        return request

    async def account_name(self, access_token, *, context=None):
        async with self._client(self.identity_url) as client:
            response = await client.get(self.identity_url, headers={
                "Authorization": "Bearer " + access_token,
                "Accept": "application/vnd.integrate.v1.10.0+json",
            })
        response.raise_for_status()
        name = response.json().get("email")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("net2phone returned no account email")
        return name


OAUTH_PROVIDER = Net2PhoneOAuthProviderSpec(
    provider="net2phone",
    authorize_url="https://api.n2p.io/v1/oauth/authorize/n2p/",
    token_url="https://api.n2p.io/v1/oauth/token/",
    identity_url="https://api.n2p.io/v1/users/current/",
    name_field="email",
    scope_registry=NET2PHONE_SCOPES,
    client_id_env="NET2PHONE_CLIENT_ID",
    client_secret_env="NET2PHONE_CLIENT_SECRET",
    redirect_uri_env="NET2PHONE_REDIRECT_URI",
    credential_type="net2phone_oauth",
    token_auth="none",
    token_format="json",
    pkce=False,
    rotates_refresh_tokens=False,
)

refresh_access_token = OAUTH_PROVIDER.refresh
