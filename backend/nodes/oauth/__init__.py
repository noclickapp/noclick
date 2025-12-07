# OAuth utilities for workflow nodes.
# Provides OAuth 2.0 token management for various providers (Google, Airtable, GitHub).

from nodes.oauth.google_oauth import (
    GoogleTokens,
    GoogleUserInfo,
    get_google_client_config,
    exchange_code_for_tokens as google_exchange_code_for_tokens,
    refresh_access_token as google_refresh_access_token,
    validate_token as google_validate_token,
    is_token_expired as google_is_token_expired,
    get_google_auth_url,
    revoke_token as google_revoke_token,
)

from nodes.oauth.airtable_oauth import (
    AirtableTokens,
    AirtableUserInfo,
    get_airtable_client_config,
    generate_pkce_verifier,
    generate_pkce_challenge,
    exchange_code_for_tokens as airtable_exchange_code_for_tokens,
    refresh_access_token as airtable_refresh_access_token,
    is_token_expired as airtable_is_token_expired,
    get_airtable_auth_url,
    AIRTABLE_FULL_SCOPES,
)

from nodes.oauth.github_oauth import (
    GithubTokens,
    GithubUserInfo,
    get_github_client_config,
    exchange_code_for_tokens as github_exchange_code_for_tokens,
    refresh_access_token as github_refresh_access_token,
    is_token_expired as github_is_token_expired,
    get_github_auth_url,
    GITHUB_WORKFLOW_SCOPES,
    GITHUB_PUBLIC_SCOPES,
)

__all__ = [
    # Google
    'GoogleTokens',
    'GoogleUserInfo',
    'get_google_client_config',
    'google_exchange_code_for_tokens',
    'google_refresh_access_token',
    'google_validate_token',
    'google_is_token_expired',
    'get_google_auth_url',
    'google_revoke_token',
    # Airtable
    'AirtableTokens',
    'AirtableUserInfo',
    'get_airtable_client_config',
    'generate_pkce_verifier',
    'generate_pkce_challenge',
    'airtable_exchange_code_for_tokens',
    'airtable_refresh_access_token',
    'airtable_is_token_expired',
    'get_airtable_auth_url',
    'AIRTABLE_FULL_SCOPES',
    # GitHub
    'GithubTokens',
    'GithubUserInfo',
    'get_github_client_config',
    'github_exchange_code_for_tokens',
    'github_refresh_access_token',
    'github_is_token_expired',
    'get_github_auth_url',
    'GITHUB_WORKFLOW_SCOPES',
    'GITHUB_PUBLIC_SCOPES',
]
