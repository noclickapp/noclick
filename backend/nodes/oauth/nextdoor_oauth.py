"""Nextdoor user OAuth, with its documented access-token refresh convention.

Authorize: https://developer.nextdoor.com/reference/sharing-get-authorization-code
Token: https://developer.nextdoor.com/reference/sharing-get-access-token
Refresh: https://developer.nextdoor.com/reference/sharing-refresh-access-token
Identity: https://developer.nextdoor.com/reference/me-1

Nextdoor documents an *unexpired access token* in the refresh_token request
field, and returns no separate refresh token. Store the successor access token
as the refresh handle too, so the shared refresh lock/CAS owns rotation.
"""
import os

from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.nextdoor import NEXTDOOR_SCOPES


class _NextdoorOAuthSpec(OAuthProviderSpec):
    def token_request(self, grant, *, context=None):
        request = super().token_request(grant, context=context)
        # Nextdoor requires client_id in the form as well as HTTP Basic auth.
        request["data"]["client_id"] = os.environ[self.client_id_env]
        return request

    async def _tokens(self, *args, **kwargs):
        tokens, name = await super()._tokens(*args, **kwargs)
        return tokens.model_copy(update={"refresh_token": tokens.access_token}), name


OAUTH_PROVIDER = _NextdoorOAuthSpec(
    provider="nextdoor",
    authorize_url="https://www.nextdoor.com/v3/authorize/",
    token_url="https://auth.nextdoor.com/v2/token",
    identity_url="https://nextdoor.com/external/api/partner/v1/me/",
    name_field="first_name",
    scope_registry=NEXTDOOR_SCOPES,
    client_id_env="NEXTDOOR_CLIENT_ID",
    client_secret_env="NEXTDOOR_CLIENT_SECRET",
    redirect_uri_env="NEXTDOOR_REDIRECT_URI",
    credential_type="nextdoor_oauth",
    token_auth="basic",
    token_params={"scope": " ".join(sorted(NEXTDOOR_SCOPES.declared_scopes()))},
    rotates_refresh_tokens=True,
)
refresh_access_token = OAUTH_PROVIDER.refresh
