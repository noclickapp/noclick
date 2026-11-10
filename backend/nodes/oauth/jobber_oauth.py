"""Jobber OAuth and POST GraphQL identity, per official authorization docs.
Authorize/token: https://developer.getjobber.com/docs/building_your_app/app_authorization
Identity: https://developer.getjobber.com/docs/getting_started
Rotation: https://developer.getjobber.com/docs/building_your_app/refresh_token_rotation
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.jobber import JOBBER_SCOPES

API_URL = "https://api.getjobber.com/api/graphql"
API_VERSION = "2026-09-25"

class JobberOAuthProviderSpec(OAuthProviderSpec):
    async def account_name(self, access_token, *, context=None):
        self.validate_context(context)
        async with self._client(self.identity_url) as client:
            response = await client.post(self.identity_url,
                headers={"Authorization": f"Bearer {access_token}",
                         "X-JOBBER-GRAPHQL-VERSION": API_VERSION},
                json={"query": "{ account { id name } }"})
        response.raise_for_status()
        body = response.json()
        if body.get("errors"):
            raise ValueError("Jobber account identity query failed")
        account = (body.get("data") or {}).get("account") or {}
        name = account.get("name")
        if not account.get("id") or not isinstance(name, str) or not name.strip():
            raise ValueError("Jobber returned no account identity")
        return name

OAUTH_PROVIDER = JobberOAuthProviderSpec(
    provider="jobber", authorize_url="https://api.getjobber.com/api/oauth/authorize",
    token_url="https://api.getjobber.com/api/oauth/token",
    identity_url=API_URL, name_field="data.account.name", scope_registry=JOBBER_SCOPES,
    client_id_env="JOBBER_CLIENT_ID", client_secret_env="JOBBER_CLIENT_SECRET",
    redirect_uri_env="JOBBER_REDIRECT_URI", credential_type="jobber_oauth",
    pkce=True, token_auth="body", rotates_refresh_tokens=True,
)
refresh_access_token = OAUTH_PROVIDER.refresh
