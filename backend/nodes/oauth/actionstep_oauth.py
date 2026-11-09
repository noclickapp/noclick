"""Actionstep's OAuth2 flow and token-selected regional endpoint.

Authorize/token/rotation: https://docs.actionstep.com/authentication/
Regions: https://docs.actionstep.com/testing-and-debugging/
Identity: https://docs.actionstep.com/downloads/Platform-JSON-V1-public-API-postman-collection.json
Identity fields: https://github.com/actionstep/Actionstep.API.WebClient/blob/master/Data%20Transfer%20Objects/Responses/CurrentUserResponseDto.cs
"""
import os
from urllib.parse import urlsplit

from nodes.core.oauth_provider import OAuthContextField, OAuthProviderSpec, read_field
from nodes.scopes.actionstep import ACTIONSTEP_SCOPES

REGIONS = ("ap-southeast-1", "ap-southeast-2", "eu-west-1", "us-east-1", "us-west-2", "ca-central-1")
ORIGINS = tuple("https://" + region + ".actionstep.com" for region in REGIONS)


class _RegionalEndpoint(OAuthContextField):
    def validate(self, value):
        # Tokens include /api/; keep the origin as URL context, with the fixed
        # API path in the declaration. No request can choose another path/host.
        if not isinstance(value, str):
            raise ValueError("Actionstep API endpoint is required")
        parsed = urlsplit(value)
        if parsed.path not in ("", "/api/") or parsed.query or parsed.fragment:
            raise ValueError("Use the regional API endpoint returned by Actionstep")
        return super().validate(value.removesuffix("/api/"))


API_ENDPOINT = _RegionalEndpoint(source="token", kind="origin", choices=ORIGINS)


class _ActionstepProvider(OAuthProviderSpec):
    async def account_name(self, access_token, *, context=None):
        # The REST API requires its vendor media type, including on identity.
        from utils.ssrf import guarded_async_client
        context = self.validate_context(context)
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.get(self.endpoint(self.identity_url, context), headers={
                "Authorization": "Bearer " + access_token,
                "Accept": "application/vnd.api+json", "Content-Type": "application/vnd.api+json"})
        response.raise_for_status()
        name = read_field(response.json(), self.name_field)
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Actionstep returned no current-user name")
        return name

    def token_request(self, grant, *, context=None):
        request = super().token_request(grant, context=context)
        if grant.get("grant_type") == "refresh_token":
            # Actionstep also requires the original redirect URI on refresh.
            request["data"]["redirect_uri"] = os.environ[self.redirect_uri_env]
        return request


OAUTH_PROVIDER = _ActionstepProvider(
    provider="actionstep",
    authorize_url="https://go.actionstep.com/api/oauth/authorize",
    token_url="https://api.actionstep.com/api/oauth/token",
    identity_url="{api_endpoint}/api/rest/users/current?include=participant&fields[participants]=id,firstName,lastName",
    name_field="linked.participants.0.firstName",
    scope_registry=ACTIONSTEP_SCOPES,
    client_id_env="ACTIONSTEP_CLIENT_ID",
    client_secret_env="ACTIONSTEP_CLIENT_SECRET",
    redirect_uri_env="ACTIONSTEP_REDIRECT_URI",
    credential_type="actionstep_oauth",
    token_auth="body",
    rotates_refresh_tokens=True,
    context_fields={"api_endpoint": API_ENDPOINT},
    token_fields=("orgkey",),
)

refresh_access_token = OAUTH_PROVIDER.refresh
