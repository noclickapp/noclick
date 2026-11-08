"""Netlify authorization-code OAuth through the shared provider flow.

Authorize, token and identity endpoints:
https://github.com/netlify-labs/oauth-example/blob/master/functions/utils/auth.js
https://docs.netlify.com/api-and-cli-guides/api-guides/get-started-with-api/#authentication
"""
from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.scopes.netlify import NETLIFY_SCOPES

OAUTH_PROVIDER = OAuthProviderSpec(
    provider="netlify",
    authorize_url="https://app.netlify.com/authorize",
    token_url="https://api.netlify.com/oauth/token",
    identity_url="https://api.netlify.com/api/v1/user",
    name_field="email",
    scope_registry=NETLIFY_SCOPES,
    client_id_env="NETLIFY_CLIENT_ID",
    client_secret_env="NETLIFY_CLIENT_SECRET",
    redirect_uri_env="NETLIFY_REDIRECT_URI",
    credential_type="netlify_oauth",
    token_auth="basic",
)
