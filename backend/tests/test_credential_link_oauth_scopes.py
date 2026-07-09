"""Regression tests for OAuth scopes surfaced to the credential-request link.

The credential-provide page (`/credential/provide/{token}`) builds each provider's
authorize URL from the request details. Two scope facts must reach it, or the link
diverges from the in-app connect hooks:

  1. Slack (and any provider with `x-oauth-user-scopes`) needs its USER scopes carried
     as `oauth_user_scopes` so the link can forward them as Slack's `user_scope` param.
  2. The link must NOT invent identity scopes (`email`/`profile`) for a provider — those
     are Google's, and Slack rejects them on /oauth/v2/authorize as "Invalid permissions
     requested". So a provider's bot scopes must stay clean of them at the source.

These pin the backend half of the fix; the FE half (augmentScopes) is pinned in
frontend/app/utils/oauthProviders.test.ts. The cache is schema-driven, so no DB.
"""
from utils.credential_request_routes import _get_sibling_methods


def _method(credential_type: str) -> dict:
    methods = _get_sibling_methods(credential_type)
    return next((m for m in methods if m['credential_type'] == credential_type), {})


def test_slack_exposes_user_scopes_to_the_link():
    slack = _method('slack_oauth')
    assert slack, "slack_oauth should resolve via sibling methods"
    assert slack['oauth_user_scopes'], "Slack must surface x-oauth-user-scopes for the link"
    # chat:write is the baseline user scope Slack automation relies on
    assert 'chat:write' in slack['oauth_user_scopes']


def test_slack_bot_scopes_are_not_polluted_with_identity_scopes():
    # The bug was the link appending Google's email/profile to every provider; the
    # source-of-truth bot scopes must never contain them so the fix stays honest.
    slack = _method('slack_oauth')
    assert 'email' not in slack['oauth_scopes']
    assert 'profile' not in slack['oauth_scopes']


def test_non_oauth_method_carries_no_user_scopes():
    # User scopes are gated on is_oauth: Slack's bot-token sibling (an API key, not an
    # OAuth flow) must surface an empty list, never inherit the OAuth method's scopes.
    slack_bot = _method('slack_bot_token')
    assert slack_bot, "slack_bot_token should resolve as a Slack sibling"
    assert slack_bot['is_oauth'] is False
    assert slack_bot['oauth_user_scopes'] == []
