"""EVE SSO authorization-code provider.

Authorize/token: https://developers.eveonline.com/docs/services/sso/
Identity: https://developers.eveonline.com/blog/spring-cleaning-legacy-routes-removed-24-march-2026
"""
from nodes.core.oauth_provider import OAuthContextField, OAuthProviderSpec
from nodes.scopes.evetech import EVETECH_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="evetech",
    authorize_url="https://login.eveonline.com/v2/oauth/authorize",
    token_url="https://login.eveonline.com/v2/oauth/token",
    identity_url="https://login.eveonline.com/v2/oauth/verify",
    name_field="CharacterName",
    scope_registry=EVETECH_SCOPES,
    client_id_env="EVETECH_CLIENT_ID",
    client_secret_env="EVETECH_CLIENT_SECRET",
    redirect_uri_env="EVETECH_REDIRECT_URI",
    credential_type="evetech_oauth",
    token_auth="basic",
    rotates_refresh_tokens=True,
    context_fields={"character_id": OAuthContextField(
        source="input", pattern=r"[1-9][0-9]{0,18}", label="Character ID (choose this character during EVE sign-in)")},
)
refresh_access_token = OAUTH_PROVIDER.refresh
