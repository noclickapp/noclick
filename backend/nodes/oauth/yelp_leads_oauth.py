"""Partner OAuth; no public self-service OAuth app registration is offered.

Authorize: https://docs.developer.yelp.com/docs/authorization-code-workflow
Token/rotation: https://docs.developer.yelp.com/reference/oauth2_token_v3
Identity/access: https://docs.developer.yelp.com/reference/get-lead-ids-for-business
"""
from nodes.core.oauth_provider import OAuthContextField, OAuthProviderSpec
from nodes.scopes.yelp_leads import YELP_LEADS_SCOPES


class YelpLeadsOAuthProviderSpec(OAuthProviderSpec):
    async def account_name(self, access_token: str, *, context=None) -> str:
        # leads does not grant the unrelated r2r_business_owner/r2r_get_businesses
        # identity APIs. Verify access to the selected business, including when
        # it has no leads; the label is its ID, never an invented owner name.
        context = self.validate_context(context)
        async with self._client(self.identity_url) as client:
            response = await client.get(self.endpoint(self.identity_url, context),
                headers={"Authorization": f"Bearer {access_token}"})
        response.raise_for_status()
        payload = response.json()
        if (not isinstance(payload, dict) or "error" in payload
                or not isinstance(payload.get("lead_ids"), list)
                or any(not isinstance(item, str) for item in payload["lead_ids"])):
            raise ValueError("Yelp did not confirm business access")
        return context["business_id"]


OAUTH_PROVIDER = YelpLeadsOAuthProviderSpec(
    provider="yelp_leads",
    authorize_url="https://biz.yelp.com/oauth2/authorize",
    token_url="https://api.yelp.com/oauth2/token/v3",
    identity_url="https://api.yelp.com/v3/businesses/{business_id}/lead_ids",
    name_field="lead_ids.0",
    scope_registry=YELP_LEADS_SCOPES,
    client_id_env="YELP_LEADS_CLIENT_ID",
    client_secret_env="YELP_LEADS_CLIENT_SECRET",
    redirect_uri_env="YELP_LEADS_REDIRECT_URI",
    credential_type="yelp_leads_oauth",
    pkce=True,
    token_auth="body",
    rotates_refresh_tokens=True,
    context_fields={"business_id": OAuthContextField(source="input",
        pattern=r"[A-Za-z0-9_-]+", label="Yelp business ID")},
)
