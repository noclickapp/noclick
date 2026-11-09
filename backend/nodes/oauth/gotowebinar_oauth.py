"""GoTo Webinar authorization-code flow.

Authorize/token (HTTP Basic, optional refresh rotation):
https://developer.goto.com/guides/Authentication/03_HOW_accessToken/
https://developer.goto.com/guides/Authentication/New_Token_Retrieval_Migration_Guide/
Identity: https://developer.goto.com/Scim
Register client: https://developer.logmeininc.com/clients
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.gotowebinar import GOTOWEBINAR_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="gotowebinar",
    authorize_url="https://authentication.logmeininc.com/oauth/authorize",
    token_url="https://authentication.logmeininc.com/oauth/token",
    identity_url="https://api.getgo.com/identity/v1/Users/me",
    name_field="displayName",
    scope_registry=GOTOWEBINAR_SCOPES,
    client_id_env="GOTOWEBINAR_CLIENT_ID",
    client_secret_env="GOTOWEBINAR_CLIENT_SECRET",
    redirect_uri_env="GOTOWEBINAR_REDIRECT_URI",
    credential_type="gotowebinar_oauth",
    token_auth="basic",
    pkce=False,
    rotates_refresh_tokens=False,
)
refresh_access_token = OAUTH_PROVIDER.refresh
