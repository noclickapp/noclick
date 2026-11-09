"""Partner OAuth: https://docs.perfectvenue.com/#section/Authentication

Perfect Venue provisions apps through eng@perfectvenue.com. GET /venues is
its documented first authenticated call, naming accessible venues rather than
claiming the first venue is the user. No separate current-user API is published.
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.perfect_venue import PERFECT_VENUE_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="perfect-venue",
    authorize_url="https://api.perfectvenue.com/oauth/authorize",
    token_url="https://api.perfectvenue.com/oauth/token",
    identity_url="https://api.perfectvenue.com/api/v1/venues",
    name_field="data.0.name",
    scope_registry=PERFECT_VENUE_SCOPES,
    credential_type="perfect_venue_oauth",
    client_id_env="PERFECT_VENUE_CLIENT_ID",
    client_secret_env="PERFECT_VENUE_CLIENT_SECRET",
    redirect_uri_env="PERFECT_VENUE_REDIRECT_URI",
    token_auth="basic",
    rotates_refresh_tokens=True,
)
refresh_access_token = OAUTH_PROVIDER.refresh
