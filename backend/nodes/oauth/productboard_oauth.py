"""Productboard OAuth declaration with its documented query-parameter transport.

Authorize, token, identity and app registration documentation:
https://developer.productboard.com/reference/oauth-authorization-code

The generic handler still owns exchange, validation, storage and scope checks;
the node's refresh hooks still use the shared lock/re-read/audit/CAS path.
"""
from __future__ import annotations

import httpx

from nodes.core.oauth_provider import OAuthProviderSpec, read_field
from nodes.scopes.productboard import PRODUCTBOARD_SCOPES


class ProductboardOAuthProviderSpec(OAuthProviderSpec):
    """Productboard requires token and identity arguments in the URL query."""

    def token_request(self, grant: dict[str, str]) -> dict:
        request = super().token_request(grant)
        request["params"] = request.pop("data")
        return request

    async def _tokens(self, grant: dict[str, str]):
        try:
            return await super()._tokens(grant)
        except httpx.HTTPError:
            # Transport exceptions may embed the URL containing client secrets.
            raise ValueError("Productboard OAuth token request failed") from None

    async def account_name(self, access_token: str) -> str:
        # Do not propagate HTTPStatusError: its request URL contains the token.
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(
                    self.identity_url,
                    params={"access_token": access_token},
                    headers={"Accept": "application/json"},
                )
            if response.is_error:
                raise ValueError("Productboard OAuth identity request failed")
            name = read_field(response.json(), self.name_field)
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            raise ValueError("Productboard OAuth identity could not be verified") from None
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Productboard returned no workspace name")
        return name


OAUTH_PROVIDER = ProductboardOAuthProviderSpec(
    provider="productboard",
    authorize_url="https://app.productboard.com/oauth2/authorize",
    token_url="https://app.productboard.com/oauth2/token",
    scope_registry=PRODUCTBOARD_SCOPES,
    client_id_env="PRODUCTBOARD_CLIENT_ID",
    client_secret_env="PRODUCTBOARD_CLIENT_SECRET",
    redirect_uri_env="PRODUCTBOARD_REDIRECT_URI",
    credential_type="productboard_oauth",
    identity_url="https://app.productboard.com/oauth2/token/info",
    name_field="space.name",
    pkce=True,
    token_auth="body",
    rotates_refresh_tokens=True,
)

refresh_access_token = OAUTH_PROVIDER.refresh
