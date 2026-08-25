"""LinkedIn operation → OAuth scope requirements.

LinkedIn splits reads and writes across separate permissions and gates the read
side behind partner approval. Only three permissions are self-service ("Open
Permissions"): ``profile`` and ``email`` from Sign In with LinkedIn using
OpenID Connect, and ``w_member_social`` from Share on LinkedIn. ``openid`` is
the OIDC scope that makes ``/v2/userinfo`` addressable at all.

The consequence for this node: ``w_member_social`` covers create and delete on
``/rest/posts``, but **every read of a member's own posts needs
``r_member_social``, a restricted permission granted to approved users only**
(https://learn.microsoft.com/linkedin/marketing/community-management/shares/posts-api).
The two read operations that needed it (``get_post``, ``list_user_posts``) were
deleted from the node — a self-service user can never be granted the scope.

The six ``scrape_*``/``search_*`` operations do not touch LinkedIn's API at
all; they run Apify actors with NoClick's own server-side token, so they carry
an empty requirement rather than being left unmapped.
"""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement


def _s(*scopes: str, note: str = "") -> ScopeRequirement:
    return ScopeRequirement(scopes=scopes, note=note)


_APIFY_NOTE = (
    "Runs an Apify actor with NoClick's server-side token; no LinkedIn "
    "credential is used."
)


_REQUIREMENTS: dict[str, ScopeRequirement] = {
    # GET /v2/userinfo — OIDC UserInfo. `openid` addresses the endpoint,
    # `profile` returns name/headline/picture, `email` the primary address.
    "get_authenticated_profile": _s("openid", "profile", "email"),
    # POST /rest/posts — "Post, comment and like posts on behalf of an
    # authenticated member."
    "create_text_post": _s("w_member_social"),
    "create_article_post": _s("w_member_social"),
    # DELETE /rest/posts/{urn} — same write permission.
    "delete_post": _s("w_member_social"),
    # Apify-backed scraping; no LinkedIn OAuth involved.
    "scrape_user_profiles": _s(note=_APIFY_NOTE),
    "scrape_company_employees": _s(note=_APIFY_NOTE),
    "search_companies": _s(note=_APIFY_NOTE),
    "search_job_listings": _s(note=_APIFY_NOTE),
    "search_posts": _s(note=_APIFY_NOTE),
    "search_user_profiles": _s(note=_APIFY_NOTE),
}

LINKEDIN_SCOPES = ScopeRegistry(
    provider="linkedin",
    requirements=_REQUIREMENTS,
)
