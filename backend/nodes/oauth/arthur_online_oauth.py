"""Arthur Online's declared authorization-code flow with entity-scoped identity.

Authorize, token, entity header and entity read:
https://documenter.getpostman.com/view/22554870/2s93sZ5YeM
Register applications under Settings > OAuth Applications in Arthur.
"""
from nodes.core.oauth_provider import OAuthContextField, OAuthProviderSpec, read_field
from nodes.scopes.arthur_online import ARTHUR_ONLINE_SCOPES


class ArthurOnlineOAuthProvider(OAuthProviderSpec):
    async def account_name(self, access_token, *, context=None):
        context = self.validate_context(context)
        async with self._client(self.identity_url) as client:
            response = await client.get(self.endpoint(self.identity_url, context), headers={
                "Authorization": f"Bearer {access_token}", "X-EntityID": context["entity_id"],
                "Accept": "application/json",
            })
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") != 200:
            raise ValueError("Arthur Online did not confirm the entity read")
        name = read_field(payload, self.name_field)
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Arthur Online returned no entity name")
        return name

    def token_request(self, grant, *, context=None):
        request = super().token_request(grant, context=context)
        request["headers"]["Cache-Control"] = "no-cache"
        return request


OAUTH_PROVIDER = ArthurOnlineOAuthProvider(
    provider="arthur-online",
    authorize_url="https://auth.arthuronline.co.uk/oauth/authorize",
    token_url="https://auth.arthuronline.co.uk/oauth/token",
    identity_url="https://api.arthuronline.co.uk/v2/entities/{entity_id}",
    name_field="data.name",
    scope_registry=ARTHUR_ONLINE_SCOPES,
    client_id_env="ARTHUR_ONLINE_CLIENT_ID",
    client_secret_env="ARTHUR_ONLINE_CLIENT_SECRET",
    redirect_uri_env="ARTHUR_ONLINE_REDIRECT_URI",
    credential_type="arthur_online_oauth",
    token_auth="body",
    context_fields={"entity_id": OAuthContextField(source="input", pattern=r"[1-9][0-9]*", label="Entity ID")},
)
refresh_access_token = OAUTH_PROVIDER.refresh
