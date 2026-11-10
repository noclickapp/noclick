"""FieldView authorization-code OAuth with single-use refresh tokens.

Protocol: https://dev.fieldview.com/api-details. The account-access probe uses
GET /v4/fields from https://dev.fieldview.com/openapi/platform.yaml.
"""
from datetime import datetime, timedelta, timezone

from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.climate import CLIMATE_SCOPES


class ClimateOAuthProviderSpec(OAuthProviderSpec):
    async def _tokens(self, grant, *, context=None):
        tokens, payload = await super()._tokens(grant, context=context)
        # The protocol guide fixes access-token lifetime at four hours; the
        # official example's TokenResponse does not require expires_in.
        # Stamp newly issued tokens so the shared refresh path can expire them.
        if tokens.expires_at is None:
            tokens.expires_at = (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
        return tokens, payload

    async def account_name(self, access_token, *, context=None):
        # FieldView requires its partner quota key even on the account probe.
        from nodes.climate_node import partner_api_key
        self.validate_context(context)
        async with self._client(self.identity_url) as client:
            response = await client.get(self.identity_url, headers={
                "Authorization": "Bearer " + access_token,
                "X-Api-Key": partner_api_key(), "X-Limit": "1", "Accept": "application/json"})
        if response.status_code == 304:
            return "FieldView account (no fields)"
        response.raise_for_status()
        body = response.json()
        rows = body.get("results") if isinstance(body, dict) else None
        if not isinstance(rows, list):
            raise ValueError("FieldView returned no account field list")
        if not rows:
            return "FieldView account (no fields)"
        name = rows[0].get("name") if isinstance(rows[0], dict) else None
        if not isinstance(name, str) or not name.strip():
            raise ValueError("FieldView returned an invalid field name")
        return "FieldView: " + name


OAUTH_PROVIDER = ClimateOAuthProviderSpec(
    provider="climate",
    authorize_url="https://climate.com/static/app-login/index.html",
    token_url="https://api.climate.com/api/oauth/token",
    identity_url="https://platform.climate.com/v4/fields",
    name_field="results.0.name",
    scope_registry=CLIMATE_SCOPES,
    client_id_env="CLIMATE_CLIENT_ID",
    client_secret_env="CLIMATE_CLIENT_SECRET",
    redirect_uri_env="CLIMATE_REDIRECT_URI",
    credential_type="climate_oauth",
    token_auth="basic",
    rotates_refresh_tokens=True,
)
refresh_access_token = OAUTH_PROVIDER.refresh
