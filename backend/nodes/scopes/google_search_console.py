"""Google Search Console → OAuth scope requirements (Google's shared scope notes are in google_cloud.py)."""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from nodes.scopes.google_cloud import _s


# ---------------------------------------------------------------------------
# Google Search Console — webmasters/v3 + searchconsole/v1
# ---------------------------------------------------------------------------

# Reads accept webmasters.readonly, which the node does not request; writes
# accept only webmasters. One scope for both keeps the table honest.
_GSC = _s("webmasters")

GOOGLE_SEARCH_CONSOLE_SCOPES = ScopeRegistry(
    provider="google-search-console",
    requirements={
        "list_sites": _GSC,
        "get_site": _GSC,
        "add_site": _GSC,
        "delete_site": _GSC,
        "list_sitemaps": _GSC,
        "get_sitemap": _GSC,
        "submit_sitemap": _GSC,
        "delete_sitemap": _GSC,
        "query_search_analytics": _GSC,
        "inspect_url": _GSC,
        # urlTestingTools.mobileFriendlyTest.run declares no scopes — it is a
        # public testing endpoint that authenticates but authorizes nothing.
        "mobile_friendly_test": ScopeRequirement(
            scopes=(),
            note="Public URL testing endpoint; requires no OAuth scope.",
        ),
    },
)
