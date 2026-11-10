"""Google Business Profile → OAuth scope requirements (Google's shared scope notes are in google_cloud.py)."""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry
from nodes.scopes.google_cloud import _s


# ---------------------------------------------------------------------------
# Google Business Profile — mybusiness*, businessprofileperformance
# ---------------------------------------------------------------------------

# The Business Profile APIs are split across five hosts but share a single
# scope. Their discovery documents declare no per-method scopes; the scope is
# published on the OAuth scopes reference as "Manage your Business Profile on
# Google".
_GBP = _s("business.manage")

GOOGLE_BUSINESS_PROFILE_SCOPES = ScopeRegistry(
    provider="google-business-profile",
    requirements={
        # mybusinessbusinessinformation/v1
        "list_business_profile_locations": _GBP,
        "get_location": _GBP,
        "update_location": _GBP,
        "get_location_attributes": _GBP,
        "update_location_attributes": _GBP,
        # mybusiness/v4 — reviews
        "list_location_reviews": _GBP,
        "get_review": _GBP,
        "reply_to_review": _GBP,
        "delete_review_reply": _GBP,
        # mybusiness/v4 — local posts
        "list_local_posts": _GBP,
        "get_local_post": _GBP,
        "create_local_post": _GBP,
        "update_local_post": _GBP,
        "delete_local_post": _GBP,
        "get_local_post_insights": _GBP,
        # mybusiness/v4 — media
        "list_media": _GBP,
        "get_media": _GBP,
        "create_media": _GBP,
        "delete_media": _GBP,
        "list_customer_media": _GBP,
        # businessprofileperformance/v1
        "fetch_location_performance_metrics": _GBP,
        "fetch_location_search_keywords": _GBP,
        # mybusinessplaceactions/v1
        "list_place_action_links": _GBP,
        "create_place_action_link": _GBP,
        "update_place_action_link": _GBP,
        "delete_place_action_link": _GBP,
    },
)
