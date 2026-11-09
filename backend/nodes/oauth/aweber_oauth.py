"""AWeber OAuth2 declaration using the shared authorization and refresh transport.

Authorize/token: https://api.aweber.com/oauth2example.yaml
Basic client authentication and rotation: https://api.aweber.com/oauth2traces.yaml
Account identity: https://api.aweber.com/accounts.yaml
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.aweber import AWEBER_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="aweber",
    authorize_url="https://auth.aweber.com/oauth2/authorize",
    token_url="https://auth.aweber.com/oauth2/token",
    identity_url="https://api.aweber.com/1.0/accounts",
    name_field="entries.0.company",
    scope_registry=AWEBER_SCOPES,
    client_id_env="AWEBER_CLIENT_ID",
    client_secret_env="AWEBER_CLIENT_SECRET",
    redirect_uri_env="AWEBER_REDIRECT_URI",
    credential_type="aweber_oauth",
    token_auth="basic",
    rotates_refresh_tokens=True,
)

refresh_access_token = OAUTH_PROVIDER.refresh
