"""Google Ads → OAuth scope requirements (Google's shared scope notes are in google_cloud.py)."""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry
from nodes.scopes.google_cloud import _s


# ---------------------------------------------------------------------------
# Google Ads — googleads.googleapis.com
# ---------------------------------------------------------------------------

# The Google Ads API has exactly one OAuth scope; every operation is a GAQL
# search against customers/{id}/googleAds:search. Access is additionally gated by
# a developer token, which is not an OAuth concern.
_ADS = _s("adwords")

GOOGLE_ADS_SCOPES = ScopeRegistry(
    provider="google-ads",
    requirements={
        "run_gaql_query": _ADS,
        "get_campaign_performance_metrics": _ADS,
        "get_ad_group_performance_metrics": _ADS,
        "get_keyword_performance_metrics": _ADS,
        "get_search_terms_triggering_ads": _ADS,
    },
)
