"""Google Analytics → OAuth scope requirements (Google's shared scope notes are in google_cloud.py)."""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry
from nodes.scopes.google_cloud import _s


# ---------------------------------------------------------------------------
# Google Analytics (GA4) — analyticsdata/v1beta + analyticsadmin/v1beta
# ---------------------------------------------------------------------------

# Every operation is a read: the Data API reports accept analytics.readonly, and
# so does accountSummaries.list behind the property dropdown.
_GA = _s("analytics.readonly")

GOOGLE_ANALYTICS_SCOPES = ScopeRegistry(
    provider="google-analytics",
    requirements={
        "run_ga4_standard_report": _GA,  # properties.runReport
        "run_ga4_realtime_report": _GA,  # properties.runRealtimeReport
        "fetch_ga4_dimensions_and_metrics": _GA,  # properties.getMetadata
    },
)
