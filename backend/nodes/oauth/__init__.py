# OAuth utilities for workflow nodes.
# Provides OAuth 2.0 token management for various providers (Google, Airtable, GitHub, Linear, Notion, Reddit, Microsoft, Facebook).

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

from nodes.oauth.linear_oauth import (
    LinearTokens,
    LinearUserInfo,
    get_linear_client_config,
    exchange_code_for_tokens as linear_exchange_code_for_tokens,
    refresh_access_token as linear_refresh_access_token,
    is_token_expired as linear_is_token_expired,
    get_linear_auth_url,
    revoke_token as linear_revoke_token,
    LINEAR_DEFAULT_SCOPES,
)

from nodes.oauth.reddit_oauth import (
    RedditTokens,
    RedditUserInfo,
    get_reddit_client_config,
    exchange_code_for_tokens as reddit_exchange_code_for_tokens,
    refresh_access_token as reddit_refresh_access_token,
    is_token_expired as reddit_is_token_expired,
    get_reddit_auth_url,
    REDDIT_WORKFLOW_SCOPES,
)

from nodes.oauth.notion_oauth import (
    NotionTokens,
    NotionWorkspaceInfo,
    get_notion_client_config,
    exchange_code_for_tokens as notion_exchange_code_for_tokens,
    refresh_access_token as notion_refresh_access_token,
    is_token_expired as notion_is_token_expired,
    get_notion_auth_url,
)

from nodes.oauth.microsoft_oauth import (
    MicrosoftTokens,
    MicrosoftUserInfo,
    get_microsoft_client_config,
    exchange_code_for_tokens as microsoft_exchange_code_for_tokens,
    refresh_access_token as microsoft_refresh_access_token,
    validate_token as microsoft_validate_token,
    is_token_expired as microsoft_is_token_expired,
    get_microsoft_auth_url,
    revoke_token as microsoft_revoke_token,
)

from nodes.oauth.facebook_oauth import (
    FacebookTokens,
    InstagramAccountInfo,
    get_facebook_client_config,
    exchange_code_for_tokens as facebook_exchange_code_for_tokens,
    refresh_access_token as facebook_refresh_access_token,
    validate_token as facebook_validate_token,
    is_token_expired as facebook_is_token_expired,
    get_facebook_auth_url,
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
    # Linear
    'LinearTokens',
    'LinearUserInfo',
    'get_linear_client_config',
    'linear_exchange_code_for_tokens',
    'linear_refresh_access_token',
    'linear_is_token_expired',
    'get_linear_auth_url',
    'linear_revoke_token',
    'LINEAR_DEFAULT_SCOPES',
    # Reddit
    'RedditTokens',
    'RedditUserInfo',
    'get_reddit_client_config',
    'reddit_exchange_code_for_tokens',
    'reddit_refresh_access_token',
    'reddit_is_token_expired',
    'get_reddit_auth_url',
    'REDDIT_WORKFLOW_SCOPES',
    # Notion
    'NotionTokens',
    'NotionWorkspaceInfo',
    'get_notion_client_config',
    'notion_exchange_code_for_tokens',
    'notion_refresh_access_token',
    'notion_is_token_expired',
    'get_notion_auth_url',
    # Microsoft
    'MicrosoftTokens',
    'MicrosoftUserInfo',
    'get_microsoft_client_config',
    'microsoft_exchange_code_for_tokens',
    'microsoft_refresh_access_token',
    'microsoft_validate_token',
    'microsoft_is_token_expired',
    'get_microsoft_auth_url',
    'microsoft_revoke_token',
    # Facebook (for Instagram)
    'FacebookTokens',
    'InstagramAccountInfo',
    'get_facebook_client_config',
    'facebook_exchange_code_for_tokens',
    'facebook_refresh_access_token',
    'facebook_validate_token',
    'facebook_is_token_expired',
    'get_facebook_auth_url',
]
